"""PTZ buttons and preset select of a camera."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.conftest import device_entry
from tests.fakedevice import FakeDevice
from tests.model.test_ptz import CAPS, PRESETS
from tests.test_status_entities import _entity


async def test_ptz_entities(hass: HomeAssistant, serve) -> None:
    device = FakeDevice("camera_g3")
    device.documents.update(
        {
            "/ISAPI/PTZCtrl/channels/1/capabilities": CAPS,
            "/ISAPI/PTZCtrl/channels/1/presets": PRESETS,
        }
    )
    server = await serve(device)
    entry = device_entry(server, device)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    preset = _entity(hass, entry, "select", "_ptz_preset")
    state = hass.states.get(preset.entity_id)
    assert state.attributes["options"] == ["Gate", "Gate (2)", "Preset 3"]
    device.writes.clear()
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": preset.entity_id, "option": "Gate (2)"},
        blocking=True,
    )
    assert device.writes == [("PUT", "/ISAPI/PTZCtrl/channels/1/presets/2/goto", "")]

    left = _entity(hass, entry, "button", "_ptz_pan_left")
    device.writes.clear()
    await hass.services.async_call("button", "press", {"entity_id": left.entity_id}, blocking=True)
    assert [(m, p) for m, p, _ in device.writes] == [
        ("PUT", "/ISAPI/PTZCtrl/channels/1/continuous"),
        ("PUT", "/ISAPI/PTZCtrl/channels/1/continuous"),
    ]
    assert "<pan>-50</pan>" in device.writes[0][2]
    assert "<pan>0</pan><tilt>0</tilt><zoom>0</zoom>" in device.writes[1][2]

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_fixed_camera_has_no_ptz(hass: HomeAssistant, serve) -> None:
    device = FakeDevice("camera_g3")
    server = await serve(device)
    entry = device_entry(server, device)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert not [
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if "_ptz_" in e.unique_id
    ]
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
