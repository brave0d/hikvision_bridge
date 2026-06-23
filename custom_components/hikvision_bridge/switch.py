"""Switches: detections per channel and alarm outputs."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import PolledEntity
from .model.features import detection, io
from .model.inventory import IoPort
from .model.vocabulary import Kind
from .runtime.bridge import DeviceBridge
from .wire.faults import BridgeFault

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    bridge: DeviceBridge = entry.runtime_data
    entities: list[SwitchEntity] = [
        DetectionSwitch(bridge, channel.channel_id, kind)
        for channel in bridge.profile.channels.values()
        for kind in sorted(channel.switchable)
    ]
    entities.extend(AlarmOutputSwitch(bridge, port) for port in bridge.profile.outputs.values())
    async_add_entities(entities)


def _raise_write_error(err: BridgeFault) -> None:
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="write_failed",
        translation_placeholders={"reason": type(err).__name__},
    ) from err


class DetectionSwitch(PolledEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, bridge: DeviceBridge, channel_id: str, kind: Kind) -> None:
        super().__init__(bridge, channel_id, f"switch_{kind.value}")
        self._kind = kind
        self._attr_translation_key = f"{kind.value}_detection"

    @property
    def _state(self) -> detection.DetectionState | None:
        return self.coordinator.data.detections.get((self.channel_id, self._kind))

    @property
    def available(self) -> bool:
        return super().available and self._state is not None

    @property
    def is_on(self) -> bool | None:
        state = self._state
        return state.enabled if state else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        state = self._state
        if state is None or state.area_defined is None:
            return None
        return {"area_defined": state.area_defined}

    async def _apply(self, on: bool) -> None:
        link, remote = self.bridge.route(self.channel_id)
        try:
            state = await detection.switch(link, self._kind, remote, on)
        except BridgeFault as err:
            _raise_write_error(err)
            return
        self.coordinator.data.detections[(self.channel_id, self._kind)] = state
        self.async_write_ha_state()
        self.bridge.refresher.request_full()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._apply(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._apply(False)


class AlarmOutputSwitch(PolledEntity, SwitchEntity):
    _attr_translation_key = "alarm_output"

    def __init__(self, bridge: DeviceBridge, port: IoPort) -> None:
        super().__init__(bridge, port.channel_id, f"output_{port.port_id}")
        self._port = port
        self._attr_translation_placeholders = {"port": port.name or port.port_id}

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.outputs.get(self._port.port_id)

    async def _apply(self, on: bool) -> None:
        try:
            await io.set_output(self.bridge.link, self._port, on)
        except BridgeFault as err:
            _raise_write_error(err)
            return
        self.coordinator.data.outputs[self._port.port_id] = on
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._apply(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._apply(False)
