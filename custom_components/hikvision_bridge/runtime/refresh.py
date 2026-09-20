"""Polling of switch states, alarm I/O, channel status and storage, with availability hysteresis."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import time
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ..const import (
    DOMAIN,
    FAILURES_BEFORE_UNAVAILABLE,
    FAST_INTERVAL,
    GRACE_BEFORE_UNAVAILABLE,
)
from ..model.discover import CLOUD_PATH, read_cloud_state
from ..model.features import detection, image, io, storage
from ..model.features.detection import DetectionState
from ..model.features.image import ImageValue
from ..model.inventory import StorageUnit
from ..model.vocabulary import Kind
from ..wire.faults import BadCredentials, BridgeFault, LockedOut, Unreachable
from ..wire.scrub import scrubbed_logger

if TYPE_CHECKING:
    from .bridge import DeviceBridge

_LOGGER = scrubbed_logger(__name__)

# Multiples of the base interval (30 s).
DETECTION_EVERY = 2  # 60 s
CHANNELS_EVERY = 4  # 120 s
STORAGE_EVERY = 20  # 10 min


@dataclass(slots=True)
class Snapshot:
    detections: dict[tuple[str, Kind], DetectionState] = field(default_factory=dict)
    inputs: dict[str, bool | None] = field(default_factory=dict)
    outputs: dict[str, bool | None] = field(default_factory=dict)
    channels_online: dict[str, bool | None] = field(default_factory=dict)
    storage: list[StorageUnit] = field(default_factory=list)
    stream_encrypted: bool | None = None
    image: dict[str, dict[str, ImageValue]] = field(default_factory=dict)


class StatusRefresher(DataUpdateCoordinator[Snapshot]):
    """One coordinator per device entry. Different resources refresh at different cadences."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, bridge: DeviceBridge) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=FAST_INTERVAL,
            always_update=False,
        )
        self._bridge = bridge
        self._tick = 0
        self._failures = 0
        self._last_success = time.monotonic()
        self._force_full = True

    def request_full(self) -> None:
        """Make the next refresh read every resource (after writes or events)."""
        self._force_full = True

    async def _async_update_data(self) -> Snapshot:
        previous = self.data
        full = self._force_full or previous is None
        self._force_full = False
        due = lambda every: full or self._tick % every == 0  # noqa: E731
        self._tick += 1
        snapshot = (
            Snapshot()
            if previous is None
            else Snapshot(
                detections=dict(previous.detections),
                inputs=dict(previous.inputs),
                outputs=dict(previous.outputs),
                channels_online=dict(previous.channels_online),
                storage=list(previous.storage),
                stream_encrypted=previous.stream_encrypted,
                image=dict(previous.image),
            )
        )
        try:
            await self._read_io(snapshot)
            if due(DETECTION_EVERY):
                await self._read_detections(snapshot)
            if due(CHANNELS_EVERY):
                await self._read_channels(snapshot)
                await self._read_cloud(snapshot)
                await self._read_image(snapshot)
            if due(STORAGE_EVERY):
                snapshot.storage = await storage.read(self._bridge.link)
        except BadCredentials as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except LockedOut as err:
            self._bridge.report_lockout(err)
            raise UpdateFailed("device locked the account") from err
        except BridgeFault as err:
            return self._tolerate(err, previous)
        self._failures = 0
        self._last_success = time.monotonic()
        return snapshot

    def _tolerate(self, err: BridgeFault, previous: Snapshot | None) -> Snapshot:
        """Keep the last data through short outages (3 failures or 90 s)."""
        self._failures += 1
        quiet_for = time.monotonic() - self._last_success
        if (
            previous is not None
            and self._failures < FAILURES_BEFORE_UNAVAILABLE
            and quiet_for < GRACE_BEFORE_UNAVAILABLE.total_seconds()
        ):
            _LOGGER.debug(
                "Ignoring transient error %s (%d in a row)", type(err).__name__, self._failures
            )
            return previous
        raise UpdateFailed(f"{type(err).__name__}: {err}") from err

    async def _read_io(self, snapshot: Snapshot) -> None:
        profile = self._bridge.profile
        link = self._bridge.link
        ports = [*profile.inputs.values(), *profile.outputs.values()]
        results = await asyncio.gather(
            *(io.read_state(link, port) for port in ports), return_exceptions=True
        )
        for port, result in zip(ports, results, strict=True):
            target = snapshot.outputs if port.output else snapshot.inputs
            if isinstance(result, (BadCredentials, LockedOut)):
                raise result
            if isinstance(result, Unreachable) or (
                isinstance(result, BaseException) and not isinstance(result, BridgeFault)
            ):
                raise result
            target[port.port_id] = None if isinstance(result, BaseException) else result

    async def _read_detections(self, snapshot: Snapshot) -> None:
        jobs = []
        keys = []
        for channel in self._bridge.profile.channels.values():
            link, remote = self._bridge.route(channel.channel_id)
            for kind in channel.switchable:
                keys.append((channel.channel_id, kind))
                jobs.append(detection.read(link, kind, remote))
        results = await asyncio.gather(*jobs, return_exceptions=True)
        failures = 0
        for key, result in zip(keys, results, strict=True):
            if isinstance(result, (BadCredentials, LockedOut)):
                if self._bridge.is_main_link_fault(key[0]):
                    raise result
                self._bridge.report_channel_fault(key[0], result)
                snapshot.detections.pop(key, None)
            elif isinstance(result, BridgeFault):
                failures += 1
                snapshot.detections.pop(key, None)
            elif isinstance(result, BaseException):
                raise result
            elif result is None:
                snapshot.detections.pop(key, None)
            else:
                snapshot.detections[key] = result
        if keys and failures == len(keys):
            raise next(r for r in results if isinstance(r, BridgeFault))

    async def _read_cloud(self, snapshot: Snapshot) -> None:
        """Follow the Hik-Connect settings, so that switching stream encryption takes effect."""
        if self._bridge.profile.cloud is None:
            return
        state = read_cloud_state(await self._bridge.link.read_xml(CLOUD_PATH, optional=True))
        if state is not None:
            self._bridge.update_cloud_state(state)
            snapshot.stream_encrypted = state.stream_encrypted

    async def _read_image(self, snapshot: Snapshot) -> None:
        """Image settings, one document per channel that offers any."""
        for channel in self._bridge.profile.channels.values():
            if not channel.image:
                continue
            link, remote = self._bridge.route(channel.channel_id)
            try:
                values = await image.read_values(link, remote, set(channel.image))
            except (BadCredentials, LockedOut) as err:
                if self._bridge.is_main_link_fault(channel.channel_id):
                    raise
                self._bridge.report_channel_fault(channel.channel_id, err)
                values = None
            except BridgeFault as err:
                _LOGGER.debug("Image settings of channel unreadable: %s", type(err).__name__)
                values = None
            if values is None:
                snapshot.image.pop(channel.channel_id, None)
            else:
                snapshot.image[channel.channel_id] = values

    async def _read_channels(self, snapshot: Snapshot) -> None:
        profile = self._bridge.profile
        if not profile.shape.records:
            return
        status = await self._bridge.link.read_xml(
            "/ISAPI/ContentMgmt/InputProxy/channels/status", optional=True
        )
        if status is None:
            return
        for node in status.children("InputProxyChannelStatus"):
            channel_id = node.text("id")
            if channel_id:
                snapshot.channels_online[channel_id] = node.flag("online")
