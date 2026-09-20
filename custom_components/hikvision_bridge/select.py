"""Selects: image setting modes per channel (day/night, supplement light, WDR, ...)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import ImageSettingEntity, add_entities, image_entities
from .model.features.image import ImageCapability, option_key
from .runtime.bridge import DeviceBridge

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    bridge: DeviceBridge = entry.runtime_data
    add_entities(bridge, async_add_entities, image_entities(bridge, "select", ImageSelect))


class ImageSelect(ImageSettingEntity, SelectEntity):
    def __init__(self, bridge: DeviceBridge, channel_id: str, capability: ImageCapability) -> None:
        super().__init__(bridge, channel_id, capability)
        # Options use a translatable form and map back to the device spelling.
        self._device_option = {option_key(o): o for o in capability.options}
        self._attr_options = list(self._device_option)

    @property
    def current_option(self) -> str | None:
        current = self.current
        if current is None:
            return None
        key = option_key(current.value)
        return key if key in self._device_option else None

    async def async_select_option(self, option: str) -> None:
        await self.async_write_value(self._device_option[option])
