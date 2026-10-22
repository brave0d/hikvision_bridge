"""Playback sessions: the device plays from a point in time over RTSP, ffmpeg makes HLS of it.

One session covers one stretch of contiguous recordings, so a position in the video maps to
the recorded time exactly (start of the session plus the playing time). Cameras serve only
one playback at a time; a viewer that seeks therefore replaces its session, and the old
process ends before the new one starts.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import time

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from ..model.features import recordings
from ..wire.scrub import scrub_text, scrubbed_logger
from . import playback
from .playback import PlaybackSource

_LOGGER = scrubbed_logger(__name__)

QUALITY_ORIGINAL = "original"
QUALITY_COMPATIBLE = "compatible"
QUALITIES = (QUALITY_ORIGINAL, QUALITY_COMPATIBLE)
SEGMENT_SECONDS = 2
FIRST_SEGMENT_TIMEOUT = 25
IDLE_SECONDS = 45
MAX_SESSIONS = 4
# Recordings closer than this count as one stretch.
JOIN_GAP = timedelta(seconds=3)
MAX_STRETCH = timedelta(hours=3)
PLAYLIST = "index.m3u8"
LOG = "ffmpeg.log"
FILE_NAME = re.compile(r"^[\w.-]+\.(m3u8|m4s|mp4|ts)$")
DATA_KEY = "hikvision_bridge_sessions"


class SessionError(Exception):
    """Playback could not start; ``reason`` is a translation key."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(slots=True)
class Stretch:
    """Contiguous recordings: where playback starts and where it ends."""

    start: datetime
    end: datetime
    kinds: set[str] = field(default_factory=set)


def stretches(found: list[recordings.Recording]) -> list[Stretch]:
    joined: list[Stretch] = []
    for item in sorted(found, key=lambda r: r.start):
        last = joined[-1] if joined else None
        if last and item.start - last.end <= JOIN_GAP and item.end - last.start <= MAX_STRETCH:
            last.end = max(last.end, item.end)
            last.kinds.add(item.kind)
        else:
            joined.append(Stretch(item.start, item.end, {item.kind}))
    return joined


def locate(found: list[recordings.Recording], moment: datetime) -> tuple[datetime, datetime] | None:
    """Start and end of playback for ``moment``; in a gap, the next recording."""
    for stretch in stretches(found):
        if stretch.end <= moment:
            continue
        return max(moment, stretch.start), stretch.end
    return None


def playback_uri(source: PlaybackSource, start: datetime, end: datetime) -> str:
    return (
        f"rtsp://device/Streaming/tracks/{source.track}/"
        f"?starttime={recordings.compact(start)}&endtime={recordings.compact(end)}"
    )


def hls_args(url: str, quality: str, codec: str | None, target: Path) -> list[str]:
    args = ["-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", url]
    args += ["-map", "0:v:0", "-map", "0:a:0?"]
    if quality == QUALITY_COMPATIBLE:
        args += [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "zerolatency",
            "-crf",
            "26",
            "-pix_fmt",
            "yuv420p",
            "-vf",
            f"scale='min({playback.H264_MAX_WIDTH},iw)':-2",
            "-g",
            str(SEGMENT_SECONDS * 25),
        ]
    else:
        args += ["-c:v", "copy"]
        if codec and "265" in codec:
            args += ["-tag:v", "hvc1"]
    args += ["-c:a", "aac", "-b:a", "64k"]
    args += [
        "-f",
        "hls",
        "-hls_time",
        str(SEGMENT_SECONDS),
        "-hls_list_size",
        "0",
        "-hls_segment_type",
        "fmp4",
        "-hls_playlist_type",
        "event",
        "-hls_flags",
        "independent_segments",
        str(target / PLAYLIST),
    ]
    return args


def _reason(errors: str) -> str:
    text = errors.lower()
    if "dimensions not set" in text or "invalid data" in text:
        return "playback_encrypted"
    if "453" in text or "not enough bandwidth" in text:
        return "playback_busy"
    if "401" in text or "unauthorized" in text:
        return "playback_auth"
    return "playback_failed"


@dataclass(slots=True)
class Session:
    session_id: str
    source_key: tuple[str, str, str]
    start: datetime
    end: datetime
    quality: str
    folder: Path
    process: asyncio.subprocess.Process
    last_access: float = field(default_factory=time.monotonic)

    @property
    def url(self) -> str:
        return f"/api/hikvision_bridge/session/{self.session_id}/{PLAYLIST}"

    def touch(self) -> None:
        self.last_access = time.monotonic()


class SessionManager:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()
        self._unsub: CALLBACK_TYPE | None = None

    def get(self, session_id: str) -> Session | None:
        session = self.sessions.get(session_id)
        if session is not None:
            session.touch()
        return session

    async def start(
        self,
        source: PlaybackSource,
        key: tuple[str, str, str],
        start: datetime,
        end: datetime,
        quality: str,
        codec: str | None,
        replace: str | None = None,
    ) -> Session:
        async with self._lock:
            if replace:
                await self._stop(replace)
            # A camera plays one recording at a time; a new view of it ends the old one.
            for other in [s for s in self.sessions.values() if s.source_key == key]:
                await self._stop(other.session_id)
            while len(self.sessions) >= MAX_SESSIONS:
                oldest = min(self.sessions.values(), key=lambda s: s.last_access)
                await self._stop(oldest.session_id)
            url = playback.rtsp_url(source, playback_uri(source, start, end))
            folder = Path(
                await self.hass.async_add_executor_job(tempfile.mkdtemp, "", "hikvision_")
            )
            for attempt in range(2):
                # Errors go to a file: a pipe nobody reads would stall a long session.
                log = await self.hass.async_add_executor_job((folder / LOG).open, "wb")
                try:
                    process = await asyncio.create_subprocess_exec(
                        playback.ffmpeg_binary(self.hass),
                        *hls_args(url, quality, codec, folder),
                        stdin=asyncio.subprocess.DEVNULL,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=log,
                    )
                finally:
                    await self.hass.async_add_executor_job(log.close)
                session = Session(
                    secrets.token_urlsafe(16), key, start, end, quality, folder, process
                )
                reason = await self._first_segment(session)
                if reason is None:
                    self.sessions[session.session_id] = session
                    self._watch()
                    return session
                if reason != "playback_busy" or attempt:
                    break
                await asyncio.sleep(1.5)  # the device releases the previous playback late
            await self.hass.async_add_executor_job(shutil.rmtree, folder, True)
            raise SessionError(reason)

    async def _first_segment(self, session: Session) -> str | None:
        """None once the first segment is written, else why ffmpeg gave up."""
        playlist = session.folder / PLAYLIST
        deadline = time.monotonic() + FIRST_SEGMENT_TIMEOUT
        while time.monotonic() < deadline:
            if session.process.returncode is not None:
                break
            text = await self.hass.async_add_executor_job(_read, playlist)
            if text and "#EXTINF" in text:
                return None
            await asyncio.sleep(0.25)
        await _end(session.process)
        errors = await self.hass.async_add_executor_job(_read, session.folder / LOG) or ""
        _LOGGER.debug("Playback did not start: %s", scrub_text(errors[-400:]))
        return _reason(errors) if errors else "playback_failed"

    async def stop(self, session_id: str) -> None:
        async with self._lock:
            await self._stop(session_id)

    async def _stop(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session is None:
            return
        await _end(session.process)
        await self.hass.async_add_executor_job(shutil.rmtree, session.folder, True)

    async def stop_all(self) -> None:
        async with self._lock:
            for session_id in list(self.sessions):
                await self._stop(session_id)
        if self._unsub:
            self._unsub()
            self._unsub = None

    def _watch(self) -> None:
        if self._unsub is None:
            self._unsub = async_track_time_interval(self.hass, self._reap, timedelta(seconds=10))

    @callback
    def _reap(self, _now: datetime) -> None:
        idle = [
            s.session_id
            for s in self.sessions.values()
            if time.monotonic() - s.last_access > IDLE_SECONDS
        ]
        for session_id in idle:
            self.hass.async_create_task(self.stop(session_id))


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


async def _end(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), 5)
    except TimeoutError:
        with suppress(ProcessLookupError):
            process.kill()
        await process.wait()


def manager(hass: HomeAssistant) -> SessionManager:
    if DATA_KEY not in hass.data:
        hass.data[DATA_KEY] = SessionManager(hass)
    return hass.data[DATA_KEY]
