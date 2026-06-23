"""Sensors: storage units and event latency."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfInformation, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import PolledEntity, PushEntity
from .model.inventory import StorageUnit
from .runtime.bridge import DeviceBridge

PARALLEL_UPDATES = 0

STORAGE_STATES = ["ok", "unformatted", "error", "idle", "sleeping", "abnormal", "full", "unknown"]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    bridge: DeviceBridge = entry.runtime_data
    entities: list[SensorEntity] = []
    for unit in bridge.profile.storage:
        entities.append(StorageStatus(bridge, unit))
        entities.append(StorageFree(bridge, unit))
        entities.append(StorageCapacity(bridge, unit))
    entities.append(EventLatency(bridge))
    async_add_entities(entities)


class _StorageBase(PolledEntity, SensorEntity):
    def __init__(self, bridge: DeviceBridge, unit: StorageUnit, feature: str) -> None:
        super().__init__(bridge, None, f"storage_{unit.unit_id}_{feature}")
        self._unit_id = unit.unit_id
        self._attr_translation_placeholders = {"unit": unit.name}

    @property
    def _unit(self) -> StorageUnit | None:
        return next((u for u in self.coordinator.data.storage if u.unit_id == self._unit_id), None)

    @property
    def available(self) -> bool:
        return super().available and self._unit is not None


class StorageStatus(_StorageBase):
    _attr_translation_key = "storage_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_options = STORAGE_STATES

    def __init__(self, bridge: DeviceBridge, unit: StorageUnit) -> None:
        super().__init__(bridge, unit, "status")

    @property
    def native_value(self) -> str | None:
        unit = self._unit
        if unit is None:
            return None
        return unit.status if unit.status in STORAGE_STATES else "unknown"


class StorageFree(_StorageBase):
    _attr_translation_key = "storage_free"
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_native_unit_of_measurement = UnitOfInformation.MEBIBYTES
    _attr_suggested_unit_of_measurement = UnitOfInformation.GIBIBYTES
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, bridge: DeviceBridge, unit: StorageUnit) -> None:
        super().__init__(bridge, unit, "free")

    @property
    def native_value(self) -> int | None:
        unit = self._unit
        return unit.free_mb if unit else None


class StorageCapacity(_StorageBase):
    _attr_translation_key = "storage_capacity"
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_native_unit_of_measurement = UnitOfInformation.MEBIBYTES
    _attr_suggested_unit_of_measurement = UnitOfInformation.GIBIBYTES
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, bridge: DeviceBridge, unit: StorageUnit) -> None:
        super().__init__(bridge, unit, "capacity")

    @property
    def native_value(self) -> int | None:
        unit = self._unit
        return unit.capacity_mb if unit else None


class EventLatency(PushEntity, SensorEntity):
    _attr_translation_key = "event_latency"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MILLISECONDS
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, bridge: DeviceBridge) -> None:
        super().__init__(bridge, None, "event_latency")

    @property
    def native_value(self) -> float | None:
        return self.bridge.router.latency_ms
