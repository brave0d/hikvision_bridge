"""Buttons: device restart and capability rescan."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_ENTRY_KIND, DOMAIN, KIND_CLOUD
from .entity import BridgeEntity
from .runtime.bridge import DeviceBridge
from .wire.faults import BridgeFault

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    if entry.data.get(CONF_ENTRY_KIND) == KIND_CLOUD:
        from .cloud_entry import async_setup_cloud_buttons  # noqa: PLC0415

        await async_setup_cloud_buttons(hass, entry, async_add_entities)
        return
    bridge: DeviceBridge = entry.runtime_data
    async_add_entities([RestartButton(bridge), RescanButton(bridge)])


class RestartButton(BridgeEntity, ButtonEntity):
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "restart"

    def __init__(self, bridge: DeviceBridge) -> None:
        super().__init__(bridge, None, "restart")

    async def async_press(self) -> None:
        try:
            await self.bridge.link.write_xml("/ISAPI/System/reboot", "")
        except BridgeFault as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"reason": type(err).__name__},
            ) from err


class RescanButton(BridgeEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "rescan"

    def __init__(self, bridge: DeviceBridge) -> None:
        super().__init__(bridge, None, "rescan")

    async def async_press(self) -> None:
        self.hass.config_entries.async_schedule_reload(self.bridge.entry.entry_id)
