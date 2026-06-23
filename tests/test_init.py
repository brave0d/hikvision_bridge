"""Setup, unload, device tree, diagnostics and failure handling of device entries."""

from __future__ import annotations

import json

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.hikvision_bridge.const import DOMAIN
from custom_components.hikvision_bridge.diagnostics import async_get_config_entry_diagnostics
from tests.conftest import device_entry
from tests.fakedevice import FakeDevice


async def _set_up_entry(hass: HomeAssistant, entry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_recorder_setup_builds_device_tree_and_unloads(hass: HomeAssistant, serve) -> None:
    device = FakeDevice("nvr")
    server = await serve(device)
    entry = device_entry(server, device)
    await _set_up_entry(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    devices = dr.async_get(hass)
    main = devices.async_get_device_by_identifier((DOMAIN, "testserial101"), entry.entry_id)
    assert main is not None
    assert main.serial_number == "TESTSERIAL101"
    channels = [
        d for d in dr.async_entries_for_config_entry(devices, entry.entry_id) if d.via_device_id
    ]
    assert channels, "recorder channels must be separate devices below the recorder"
    assert all(d.via_device_id == main.id for d in channels)

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    domains = {e.domain for e in entities}
    assert {Platform.BINARY_SENSOR, Platform.SWITCH, Platform.CAMERA} <= domains
    # unique ids are derived from the serial, never from the address
    assert all(e.unique_id.startswith("testserial101_") for e in entities)
    assert all(server.host not in e.unique_id for e in entities)

    # setup only reads
    assert {method for method, _ in device.requests} == {"GET"}

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics_leak_nothing(hass: HomeAssistant, serve) -> None:
    device = FakeDevice("nvr")
    server = await serve(device)
    entry = device_entry(server, device)
    await _set_up_entry(hass, entry)

    result = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(result, default=str)
    for secret in (
        device.password,
        device.username,
        "TESTSERIAL101",
        "TESTSERIAL201",
        "02:00:00:00:01:01",
    ):
        assert secret not in text
    assert "profile" in result

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_wrong_password_starts_reauth_after_single_attempt(
    hass: HomeAssistant, serve
) -> None:
    device = FakeDevice("nvr")
    server = await serve(device)
    entry = device_entry(server, device, password="not-the-password")
    await _set_up_entry(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert device.failed_logins == 1
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_locked_device_is_not_hammered(hass: HomeAssistant, serve) -> None:
    device = FakeDevice("nvr", lock_after=0)
    server = await serve(device)
    entry = device_entry(server, device)
    await _set_up_entry(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert len(device.requests) == 1


async def test_other_device_at_address_is_refused(hass: HomeAssistant, serve) -> None:
    device = FakeDevice("camera_g3")
    server = await serve(device)
    entry = device_entry(server, device, serial="TESTSERIAL101")
    await _set_up_entry(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_unreachable_device_retries_later(hass: HomeAssistant, serve) -> None:
    device = FakeDevice("nvr")
    server = await serve(device)
    entry = device_entry(server, device)
    await server.close()
    await _set_up_entry(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_RETRY
