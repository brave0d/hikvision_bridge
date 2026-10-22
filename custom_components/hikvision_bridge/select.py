"""Selects: image setting modes per channel (day/night, light, WDR, ...) and PTZ presets."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import BridgeEntity, ImageSettingEntity, add_entities, image_entities
from .model.features import ptz
from .model.features.image import ImageCapability, option_key
from .runtime.bridge import DeviceBridge
from .wire.faults import BridgeFault

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    bridge: DeviceBridge = entry.runtime_data
    entities: list[BridgeEntity] = list(image_entities(bridge, "select", ImageSelect))
    entities.extend(
        PtzPresetSelect(bridge, channel.channel_id, channel.ptz.presets)
        for channel in bridge.profile.channels.values()
        if channel.ptz is not None and channel.ptz.presets
    )
    add_entities(bridge, async_add_entities, entities)


class ImageSelect(ImageSettingEntity, SelectEntity):
    def __init__(self, bridge: DeviceBridge, channel_id: str, capability: ImageCapability) -> None:
        super().__init__(bridge, channel_id, capability)
        if capability.labels:
            # Device-named choices (alarm sounds): show the device's names.
            self._device_option = dict(zip(capability.labels, capability.options, strict=True))
        else:
            # Options use a translatable form and map back to the device spelling.
            self._device_option = {option_key(o): o for o in capability.options}
        self._from_device = {device: shown for shown, device in self._device_option.items()}
        self._attr_options = list(self._device_option)

    @property
    def current_option(self) -> str | None:
        current = self.current
        if current is None:
            return None
        if current.value in self._from_device:
            return self._from_device[current.value]
        key = option_key(current.value)
        return key if key in self._device_option else None

    async def async_select_option(self, option: str) -> None:
        await self.async_write_value(self._device_option[option])


class PtzPresetSelect(BridgeEntity, SelectEntity):
    """Moves a PTZ channel to a stored preset.

    The device does not report whether it still stands at a preset, so no option is shown
    as current and the same preset can be chosen again.
    """

    _attr_translation_key = "ptz_preset"
    _attr_current_option = None

    def __init__(self, bridge: DeviceBridge, channel_id: str, presets: dict[str, str]) -> None:
        super().__init__(bridge, channel_id, "ptz_preset")
        self._preset_id = {name: preset_id for preset_id, name in presets.items()}
        self._attr_options = list(self._preset_id)

    async def async_select_option(self, option: str) -> None:
        link, remote = self.bridge.route(self.channel_id)
        try:
            await ptz.goto_preset(link, remote, self._preset_id[option])
        except BridgeFault as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"reason": type(err).__name__},
            ) from err
