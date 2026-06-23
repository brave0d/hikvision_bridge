"""Shared entity base classes."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .runtime import identity
from .runtime.bridge import DeviceBridge
from .runtime.refresh import StatusRefresher
from .runtime.router import signal_state


class BridgeEntity(Entity):
    """Entity bound to one device entry; never sets an entity_id."""

    _attr_has_entity_name = True

    def __init__(self, bridge: DeviceBridge, channel_id: str | None, feature: str) -> None:
        self.bridge = bridge
        self.channel_id = channel_id
        self._attr_unique_id = identity.entity_uid(bridge.profile, channel_id, feature)
        self._attr_device_info = DeviceInfo(
            identifiers={identity.entity_device_identifier(bridge.profile, channel_id)}
        )


class PushEntity(BridgeEntity):
    """Entity driven by device notifications."""

    _attr_should_poll = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_state(self.bridge.entry.entry_id), self._on_state
            )
        )

    @callback
    def _on_state(self, _slot: object) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self.bridge.router.feeds_healthy()


class PolledEntity(CoordinatorEntity[StatusRefresher], BridgeEntity):
    """Entity backed by the status refresher."""

    def __init__(self, bridge: DeviceBridge, channel_id: str | None, feature: str) -> None:
        CoordinatorEntity.__init__(self, bridge.refresher)
        BridgeEntity.__init__(self, bridge, channel_id, feature)
