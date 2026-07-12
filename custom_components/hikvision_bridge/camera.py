"""Camera entities: RTSP stream source and ISAPI snapshots per channel stream."""

from __future__ import annotations

from urllib.parse import quote

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    OPT_RTSP_PORT,
    OPT_RTSP_TRANSPORT,
    RTSP_PORT_DEFAULT,
    RTSP_TCP,
    SUBENTRY_CHANNEL_LINK,
)
from .entity import BridgeEntity
from .model.inventory import StreamSpec
from .runtime.bridge import DeviceBridge
from .wire.faults import BridgeFault, Unsupported
from .wire.link import IsapiLink
from .wire.scrub import scrubbed_logger

_LOGGER = scrubbed_logger(__name__)
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    bridge: DeviceBridge = entry.runtime_data
    entities = []
    for channel in bridge.profile.channels.values():
        streams = channel.streams
        if not streams and channel.channel_id.isdigit():
            streams = [StreamSpec(f"{int(channel.channel_id) * 100 + 1}")]
        for stream in streams:
            if stream.rank > 3:
                continue
            entities.append(ChannelCamera(bridge, channel.channel_id, stream))
    async_add_entities(entities)


class ChannelCamera(BridgeEntity, Camera):
    def __init__(self, bridge: DeviceBridge, channel_id: str, stream: StreamSpec) -> None:
        BridgeEntity.__init__(self, bridge, channel_id, f"stream_{stream.rank}")
        Camera.__init__(self)
        self._stream = stream
        self._attr_translation_key = {1: "main_stream", 2: "sub_stream"}.get(
            stream.rank, "third_stream"
        )
        # Main and sub stream are both useful (full view, light live view); the third is rare.
        self._attr_entity_registry_enabled_default = stream.rank <= 2
        encrypted = bool(bridge.profile.cloud and bridge.profile.cloud.stream_encrypted)
        direct = channel_id in bridge.routes and bridge.routes[channel_id].healthy
        self._playable = not encrypted or direct
        if self._playable:
            self._attr_supported_features = CameraEntityFeature.STREAM
        transport = bridge.entry.options.get(OPT_RTSP_TRANSPORT, RTSP_TCP)
        self.stream_options["rtsp_transport"] = transport
        self._attr_extra_state_attributes = {
            "codec": stream.codec,
            "resolution": f"{stream.width}x{stream.height}" if stream.width else None,
            "stream_encrypted": encrypted and not direct,
        }

    def _source(self) -> tuple[IsapiLink, str, dict]:
        """Link, stream id and credentials to use (direct camera link if configured)."""
        route = self.bridge.routes.get(self.channel_id)
        if route is not None and route.healthy:
            sub = next(
                s
                for s in self.bridge.entry.subentries.values()
                if s.subentry_type == SUBENTRY_CHANNEL_LINK and s.subentry_id == route.subentry_id
            )
            remote_stream = f"{int(route.remote_channel) * 100 + self._stream.rank}"
            return route.link, remote_stream, dict(sub.data)
        return self.bridge.link, self._stream.stream_id, dict(self.bridge.entry.data)

    async def stream_source(self) -> str | None:
        if not self._playable:
            return None
        link, stream_id, data = self._source()
        port = RTSP_PORT_DEFAULT
        if link is self.bridge.link:
            port = (
                self.bridge.entry.options.get(OPT_RTSP_PORT)
                or self.bridge.profile.rtsp_port
                or RTSP_PORT_DEFAULT
            )
        user = quote(data[CONF_USERNAME], safe="")
        password = quote(data[CONF_PASSWORD], safe="")
        host = link.endpoint.base.split("://", 1)[1].rsplit(":", 1)[0]
        return f"rtsp://{user}:{password}@{host}:{port}/Streaming/Channels/{stream_id}"

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        link, stream_id, _ = self._source()
        paths = [f"/ISAPI/Streaming/channels/{stream_id}/picture"]
        if link is self.bridge.link and self.bridge.profile.shape.records:
            paths.insert(0, f"/ISAPI/ContentMgmt/StreamingProxy/channels/{stream_id}/picture")
        for path in paths:
            if path in link.unsupported:
                continue
            try:
                reply = await link.read_bytes(path)
            except Unsupported:
                continue
            except BridgeFault as err:
                _LOGGER.debug("Snapshot failed: %s", type(err).__name__)
                return None
            if reply.content_type.startswith("image/"):
                return reply.body
        return None
