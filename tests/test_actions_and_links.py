"""Actions, the linkage repair, duplicate detection and direct camera connections."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, issue_registry as ir
import pytest

from custom_components.hikvision_bridge import repairs
from custom_components.hikvision_bridge.const import DOMAIN, SUBENTRY_CHANNEL_LINK
from tests.conftest import device_entry
from tests.fakedevice import FakeDevice


@pytest.fixture
async def recorder(hass: HomeAssistant, serve):
    device = FakeDevice("nvr")
    server = await serve(device)
    entry = device_entry(server, device)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, unique_id="testserial101")
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield device, entry
    await hass.async_block_till_done()
    if entry.state is config_entries.ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


def _main_device(hass: HomeAssistant, entry) -> str:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, "testserial101"), entry.entry_id
    )
    return device.id


async def test_isapi_request_reads_and_masks(hass: HomeAssistant, recorder) -> None:
    _, entry = recorder
    response = await hass.services.async_call(
        DOMAIN,
        "isapi_request",
        {"device_id": _main_device(hass, entry), "path": "/ISAPI/System/deviceInfo"},
        blocking=True,
        return_response=True,
    )
    assert response["ok"]
    assert "TESTSERIAL101" not in response["body"]
    assert "02:00:00:00:01:01" not in response["body"]


async def test_isapi_request_refuses_unconfirmed_writes(hass: HomeAssistant, recorder) -> None:
    device, entry = recorder
    target = _main_device(hass, entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "isapi_request",
            {"device_id": target, "method": "PUT", "path": "/ISAPI/System/reboot"},
            blocking=True,
            return_response=True,
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "isapi_request",
            {"device_id": target, "path": "/SDK/whatever"},
            blocking=True,
            return_response=True,
        )
    assert device.writes == []


async def test_add_center_links_previews_then_writes(hass: HomeAssistant, recorder) -> None:
    device, entry = recorder
    target = _main_device(hass, entry)
    preview = await hass.services.async_call(
        DOMAIN, "add_center_links", {"device_id": target}, blocking=True, return_response=True
    )
    assert preview["dry_run"] is True
    assert preview["triggers"]
    assert device.writes == []

    done = await hass.services.async_call(
        DOMAIN,
        "add_center_links",
        {"device_id": target, "dry_run": False, "kinds": ["intrusion"]},
        blocking=True,
        return_response=True,
    )
    assert done["triggers"]
    assert all("center" in body for _, _, body in device.writes)
    assert {path for _, path, _ in device.writes} <= {
        f"/ISAPI/Event/triggers/{t}" for t in done["triggers"]
    }


async def test_notification_host_needs_webhook(hass: HomeAssistant, recorder) -> None:
    device, entry = recorder
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_notification_host",
            {"device_id": _main_device(hass, entry), "confirm_write": True},
            blocking=True,
            return_response=True,
        )
    assert device.writes == []


async def test_center_link_repair_writes_only_after_confirmation(
    hass: HomeAssistant, recorder
) -> None:
    device, entry = recorder
    await entry.runtime_data.async_run_audit()
    issues = [
        (issue_id, issue)
        for (domain, issue_id), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue.translation_key == "center_link_missing"
    ]
    assert issues
    issue_id, issue = issues[0]
    assert issue.is_fixable
    flow = await repairs.async_create_fix_flow(hass, issue_id, issue.data)
    flow.hass = hass
    form = await flow.async_step_init()
    assert form["type"] is FlowResultType.FORM
    assert device.writes == []
    done = await flow.async_step_confirm({})
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert len(device.writes) == 1


async def test_camera_already_on_recorder_offers_link(hass: HomeAssistant, recorder, serve) -> None:
    _, entry = recorder
    camera = FakeDevice("camera_g3", password="camera-own-pass")
    server = await serve(camera)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "device"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: server.host,
            CONF_PORT: server.port,
            "connection": "http",
            "verify_tls": True,
            CONF_USERNAME: camera.username,
            CONF_PASSWORD: camera.password,
        },
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "duplicate"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "link_to_channel"}
    )
    assert result["reason"] == "linked_to_channel"
    (link,) = [s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_CHANNEL_LINK]
    assert link.unique_id == "1"
    assert link.data[CONF_PASSWORD] == "camera-own-pass"


async def test_direct_link_refuses_wrong_camera(hass: HomeAssistant, recorder, serve) -> None:
    _, entry = recorder
    other = FakeDevice("camera_noio")
    server = await serve(other)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_CHANNEL_LINK), context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "channel_id": "1",
            CONF_HOST: server.host,
            CONF_PORT: server.port,
            "connection": "http",
            "verify_tls": True,
            "reuse_recorder_credentials": False,
            CONF_USERNAME: other.username,
            CONF_PASSWORD: other.password,
            "event_source": "recorder",
        },
    )
    assert result["errors"] == {"base": "wrong_camera"}
