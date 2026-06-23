"""A single authenticated connection to one ISAPI endpoint."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import ipaddress
import json
import time
from typing import Any

import aiohttp
from yarl import URL

from .faults import (
    BadCredentials,
    BridgeFault,
    DeviceRejected,
    LockedOut,
    NameNotResolved,
    NotIsapi,
    TlsUntrusted,
    Unreachable,
    Unsupported,
    classify,
    is_lock,
    read_status,
)
from .scrub import LOG_SCRUBBER, scrubbed_logger
from .signer import DigestSigner, Signer, build_signer, parse_challenges, pick
from .xmlview import XmlError, XmlNode, decode, parse

_LOGGER = scrubbed_logger(__name__)

PROBE_PATH = "/ISAPI/System/deviceInfo"
MAX_PARALLEL = 2


@dataclass(frozen=True, slots=True)
class Endpoint:
    """Where a device is reached."""

    host: str
    port: int
    scheme: str = "http"

    @property
    def base(self) -> str:
        host = self.host
        try:
            if ipaddress.ip_address(host).version == 6:
                host = f"[{host}]"
        except ValueError:
            pass
        return f"{self.scheme}://{host}:{self.port}"


@dataclass(slots=True)
class Reply:
    status: int
    content_type: str
    body: bytes
    elapsed_ms: float

    @property
    def text(self) -> str:
        return decode(self.body)

    def xml(self) -> XmlNode:
        return parse(self.body)

    def json(self) -> Any:
        return json.loads(self.text)


@dataclass(slots=True)
class LinkStats:
    requests: int = 0
    failures: int = 0
    last_success: float | None = None
    last_error: str | None = None
    latency_ms: dict[str, float] = field(default_factory=dict)


class IsapiLink:
    """Serialises access to one device and owns its authentication state."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        endpoint: Endpoint,
        username: str,
        password: str,
        *,
        request_timeout: float = 15,
        write_timeout: float = 20,
        connect_timeout: float = 10,
    ) -> None:
        self._session = session
        self.endpoint = endpoint
        self._username = username
        self._password = password
        self._signer: Signer | None = None
        self._auth_checked = False
        self._blocked: BridgeFault | None = None
        self._gate = asyncio.Semaphore(MAX_PARALLEL)
        self._write_lock = asyncio.Lock()
        self._establish_lock = asyncio.Lock()
        self._read_timeout = aiohttp.ClientTimeout(total=request_timeout, connect=connect_timeout)
        self._write_timeout = aiohttp.ClientTimeout(total=write_timeout, connect=connect_timeout)
        self._connect_timeout = connect_timeout
        self.unsupported: set[str] = set()
        self.stats = LinkStats()
        LOG_SCRUBBER.remember(username, password)

    # ----------------------------------------------------------------- state

    @property
    def blocked(self) -> BridgeFault | None:
        """The fault that stopped all traffic (bad credentials, lockout), if any."""
        return self._blocked

    @property
    def auth_scheme(self) -> str | None:
        return self._signer.scheme if self._signer else None

    def replace_credentials(self, username: str, password: str) -> None:
        """Install new credentials and lift a credential block."""
        LOG_SCRUBBER.remember(username, password)
        self._username = username
        self._password = password
        self._signer = None
        self._auth_checked = False
        self._blocked = None

    # ------------------------------------------------------------ transport

    def _url(self, path: str) -> URL:
        return URL(self.endpoint.base + path, encoded=True)

    async def _raw(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes | None,
        limits: aiohttp.ClientTimeout,
    ) -> tuple[int, str, list[str], bytes]:
        try:
            async with self._session.request(
                method,
                self._url(path),
                headers=headers,
                data=body,
                timeout=limits,
                allow_redirects=False,
            ) as response:
                payload = await response.read()
                return (
                    response.status,
                    response.headers.get("Content-Type", ""),
                    response.headers.getall("WWW-Authenticate", []),
                    payload,
                )
        except aiohttp.ClientConnectorCertificateError as err:
            raise TlsUntrusted(str(err)) from err
        except aiohttp.ClientSSLError as err:
            raise TlsUntrusted(str(err)) from err
        except aiohttp.ClientConnectorDNSError as err:
            raise NameNotResolved(self.endpoint.host) from err
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            raise Unreachable(f"{type(err).__name__}: {err}") from err

    async def _establish(self) -> None:
        """Learn the authentication scheme with one unauthenticated request."""
        async with self._establish_lock:
            if self._auth_checked:
                return
            status, ctype, challenges, payload = await self._raw(
                "GET", PROBE_PATH, {}, None, self._read_timeout
            )
            if status == 200:
                head = payload.lstrip()[:64].lower()
                looks_xml = "xml" in ctype or head.startswith(b"<?xml")
                if "html" in ctype or head.startswith((b"<html", b"<!doctype")) or not looks_xml:
                    raise NotIsapi(f"unexpected content type {ctype}")
                _LOGGER.warning(
                    "%s answers without authentication; consider enabling it on the device",
                    self.endpoint.host,
                )
                self._signer = None
            elif status == 401:
                chosen = pick(parse_challenges(challenges))
                if chosen is None:
                    status_block = read_status(decode(payload))
                    if is_lock(status_block):
                        self._blocked = LockedOut(
                            "device reports a lock", status_block.unlock_seconds
                        )
                        raise self._blocked
                    raise NotIsapi("no usable authentication challenge")
                self._signer = build_signer(self._username, self._password, chosen)
            elif status in (301, 302, 307, 308):
                raise NotIsapi("redirected; try HTTPS")
            elif status == 404 or "html" in ctype:
                raise NotIsapi(f"HTTP {status}")
            else:
                raise Unreachable(f"HTTP {status} during authentication probe")
            self._auth_checked = True

    async def call(
        self,
        method: str,
        path: str,
        *,
        body: bytes | str | None = None,
        content_type: str = "application/xml; charset=UTF-8",
    ) -> Reply:
        """Send one request, handling digest nonce refresh. Raises a BridgeFault on errors."""
        if self._blocked is not None:
            raise self._blocked
        if not self._auth_checked:
            await self._establish()
        payload = body.encode("utf-8") if isinstance(body, str) else body
        writing = method != "GET"
        timeout = self._write_timeout if writing else self._read_timeout

        async with self._gate:
            if writing:
                async with self._write_lock:
                    return await self._authorized(method, path, payload, content_type, timeout)
            return await self._authorized(method, path, payload, content_type, timeout)

    async def _authorized(
        self,
        method: str,
        path: str,
        payload: bytes | None,
        content_type: str,
        limits: aiohttp.ClientTimeout,
    ) -> Reply:
        started = time.monotonic()
        self.stats.requests += 1
        for attempt in range(2):
            headers = {"Accept": "*/*"}
            if payload is not None:
                headers["Content-Type"] = content_type
            if self._signer is not None:
                headers["Authorization"] = self._signer.authorization(method, path)
            try:
                status, ctype, challenges, data = await self._raw(
                    method, path, headers, payload, limits
                )
            except BridgeFault as err:
                self.stats.failures += 1
                self.stats.last_error = type(err).__name__
                raise
            if status != 401:
                if self._signer is not None:
                    self._signer.mark_success()
                elapsed = (time.monotonic() - started) * 1000
                self.stats.last_success = time.monotonic()
                self.stats.latency_ms[path.split("?", maxsplit=1)[0]] = round(elapsed, 1)
                return self._finish(path, Reply(status, ctype, data, elapsed))
            if not self._may_retry(attempt, challenges, data):
                break
        raise self._blocked or BadCredentials("rejected")

    def _may_retry(self, attempt: int, challenges: list[str], data: bytes) -> bool:
        """Decide after a 401 whether one more attempt is safe; otherwise block the link."""
        status = read_status(decode(data))
        if is_lock(status):
            self._blocked = LockedOut("device reports a lock", status.unlock_seconds)
            return False
        fresh = pick(parse_challenges(challenges))
        signer = self._signer
        if (
            attempt == 0
            and fresh is not None
            and isinstance(signer, DigestSigner)
            and (fresh.stale or signer.nonce_proven)
        ):
            # The nonce expired; credentials were fine with it. Exactly one retry.
            signer.accept(fresh)
            return True
        self._blocked = BadCredentials("credentials rejected after a fresh challenge")
        _LOGGER.warning(
            "%s rejected the credentials; all requests stop until they are updated",
            self.endpoint.host,
        )
        return False

    def _finish(self, path: str, reply: Reply) -> Reply:
        fault = classify(reply.status, reply.text if reply.body else "")
        if fault is None:
            return reply
        if isinstance(fault, Unsupported):
            self.unsupported.add(path.split("?", maxsplit=1)[0])
        if isinstance(fault, LockedOut):
            self._blocked = fault
        raise fault

    # ------------------------------------------------------------ helpers

    async def read_xml(self, path: str, *, optional: bool = False) -> XmlNode | None:
        """GET an XML document. With ``optional`` unsupported resources return None."""
        if optional and path.split("?", maxsplit=1)[0] in self.unsupported:
            return None
        try:
            reply = await self.call("GET", path)
            return reply.xml()
        except Unsupported:
            if optional:
                return None
            raise
        except DeviceRejected as err:
            if optional and err.status in (400, 500, 501):
                self.unsupported.add(path.split("?", maxsplit=1)[0])
                return None
            raise
        except XmlError as err:
            if optional:
                return None
            raise NotIsapi(f"{path}: {err}") from err

    async def read_text(self, path: str, *, optional: bool = False) -> str | None:
        if optional and path.split("?", maxsplit=1)[0] in self.unsupported:
            return None
        try:
            return (await self.call("GET", path)).text
        except Unsupported:
            if optional:
                return None
            raise

    async def read_json(self, path: str, *, optional: bool = False) -> Any:
        text = await self.read_text(path, optional=optional)
        if text is None:
            return None
        try:
            return json.loads(text)
        except ValueError as err:
            if optional:
                return None
            raise NotIsapi(f"{path}: invalid JSON") from err

    async def read_bytes(self, path: str) -> Reply:
        return await self.call("GET", path)

    async def write_xml(self, path: str, document: str, method: str = "PUT") -> Reply:
        return await self.call(method, path, body=document)

    # ------------------------------------------------------------- streams

    @asynccontextmanager
    async def open_stream(self, path: str) -> AsyncIterator[aiohttp.ClientResponse]:
        """Open a long-lived authenticated GET (event stream). Does not use a request slot."""
        if self._blocked is not None:
            raise self._blocked
        if not self._auth_checked:
            await self._establish()
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=self._connect_timeout)
        for attempt in range(2):
            headers = {"Accept": "*/*"}
            if self._signer is not None:
                headers["Authorization"] = self._signer.authorization("GET", path)
            try:
                response = await self._session.get(
                    self._url(path), headers=headers, timeout=timeout, allow_redirects=False
                )
            except aiohttp.ClientConnectorCertificateError as err:
                raise TlsUntrusted(str(err)) from err
            except (aiohttp.ClientError, TimeoutError, OSError) as err:
                raise Unreachable(f"{type(err).__name__}: {err}") from err
            if response.status == 401:
                challenges = response.headers.getall("WWW-Authenticate", [])
                data = await response.read()
                response.release()
                if self._may_retry(attempt, challenges, data):
                    continue
                raise self._blocked or BadCredentials("rejected")
            if response.status != 200:
                data = await response.read()
                response.release()
                fault = classify(response.status, decode(data)) or DeviceRejected(
                    f"HTTP {response.status}", response.status
                )
                raise fault
            if self._signer is not None:
                self._signer.mark_success()
            try:
                yield response
            finally:
                response.close()
            return
        raise self._blocked or BadCredentials("rejected")
