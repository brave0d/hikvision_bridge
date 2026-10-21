"""Recording, device status, address and armable inputs of a recorder."""

from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.conftest import device_entry
from tests.fakedevice import FakeDevice

NS = 'version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema"'
STATUS = (
    f"<DeviceStatus {NS}><deviceUpTime>3600</deviceUpTime>"
    "<CPUList><CPU><cpuUtilization>12</cpuUtilization></CPU></CPUList>"
    "<totalRebootCount>4</totalRebootCount></DeviceStatus>"
)
INPUT_1 = f"<IOInputPort {NS}><id>1</id><enabled>false</enabled><triggering>high</triggering></IOInputPort>"


def _entity(hass: HomeAssistant, entry, domain: str, suffix: str) -> er.RegistryEntry:
    for item in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if item.domain == domain and item.unique_id.endswith(suffix):
            return item
    raise AssertionError(f"no {domain} entity ending in {suffix}")


async def test_recorder_status_entities(hass: HomeAssistant, serve) -> None:
    device = FakeDevice("nvr")
    device.documents.update({"/ISAPI/System/status": STATUS, "/ISAPI/System/IO/inputs/1": INPUT_1})
    server = await serve(device)
    entry = device_entry(server, device)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    recording = _entity(hass, entry, "binary_sensor", "_ch1_recording")
    assert hass.states.get(recording.entity_id).state == STATE_ON

    address = _entity(hass, entry, "sensor", "_network_address")
    assert hass.states.get(address.entity_id).state == server.host

    # Device status is diagnostic and starts disabled.
    for feature in ("boot_time", "cpu_load", "reboots"):
        assert _entity(hass, entry, "sensor", f"_{feature}").disabled_by is not None

    armed = _entity(hass, entry, "switch", "_armed_1")
    assert hass.states.get(armed.entity_id).state == STATE_OFF
    device.writes.clear()
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": armed.entity_id}, blocking=True
    )
    method, path, body = device.writes[0]
    assert (method, path) == ("PUT", "/ISAPI/System/IO/inputs/1")
    assert body == INPUT_1.replace("<enabled>false<", "<enabled>true<")
    assert hass.states.get(armed.entity_id).state == STATE_ON

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
