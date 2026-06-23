"""Discovery, audit findings and switching against simulated devices."""

import aiohttp
from aiohttp.test_utils import TestServer
import pytest

from custom_components.hikvision_bridge.model import audit, discover
from custom_components.hikvision_bridge.model.features import detection, linkage
from custom_components.hikvision_bridge.model.inventory import ChannelSource, DeviceShape
from custom_components.hikvision_bridge.model.vocabulary import Kind, canonical
from custom_components.hikvision_bridge.wire.link import Endpoint, IsapiLink
from tests.fakedevice import FakeDevice

pytestmark = pytest.mark.usefixtures("socket_enabled")


@pytest.fixture
async def link_to():
    opened = []

    async def make(device: FakeDevice) -> IsapiLink:
        server = TestServer(device.app())
        await server.start_server()
        session = aiohttp.ClientSession()
        opened.append((server, session))
        return IsapiLink(
            session, Endpoint(server.host, server.port), device.username, device.password
        )

    yield make
    for server, session in opened:
        await session.close()
        await server.close()


def test_vocabulary_aliases() -> None:
    assert canonical("VMD") is Kind.MOTION
    assert canonical("motionDetection") is Kind.MOTION
    assert canonical("fieldDetection") is Kind.INTRUSION
    assert canonical("linedetection") is Kind.LINE_CROSSING
    assert canonical("Shelteralarm") is Kind.TAMPER
    assert canonical("somethingNew") is Kind.OTHER


async def test_recorder_discovery(link_to) -> None:
    device = FakeDevice(profile="nvr")
    link = await link_to(device)
    profile = await discover.discover(link)

    assert profile.shape is DeviceShape.RECORDER
    assert sorted(profile.channels, key=int) == ["1", "2", "3", "4", "5", "6"]
    first = profile.channels["1"]
    assert first.source is ChannelSource.PROXY
    assert first.online is True
    assert first.camera_serial.startswith("TESTSERIAL")
    assert first.camera_address == "10.0.0.91"
    assert [s.stream_id for s in first.streams][:2] == ["101", "102"]
    assert {Kind.MOTION, Kind.INTRUSION, Kind.LINE_CROSSING, Kind.REGION_ENTRANCE} <= first.kinds
    # Captured switch documents exist for channel 1 only; others answer notSupport here.
    assert {
        Kind.MOTION,
        Kind.INTRUSION,
        Kind.LINE_CROSSING,
        Kind.REGION_ENTRANCE,
    } <= first.switchable
    assert profile.cloud.stream_encrypted is True
    assert profile.rtsp_port == 554
    assert profile.storage[0].status == "ok"
    assert "101" in profile.outputs
    assert profile.outputs["101"].channel_id == "1"
    # Only GET requests were sent during discovery.
    assert {method for method, _ in device.requests} == {"GET"}


async def test_recorder_audit_reports_missing_center_and_encryption(link_to) -> None:
    link = await link_to(FakeDevice(profile="nvr"))
    profile = await discover.discover(link)
    report = await audit.run_audit(link, profile)

    missing = {(i.channel_id, i.kind) for i in report.of(audit.Finding.CENTER_LINK_MISSING)}
    assert ("1", Kind.REGION_ENTRANCE) in missing
    assert ("1", Kind.MOTION) not in missing  # motion is linked on the recorder
    assert report.of(audit.Finding.STREAM_ENCRYPTED)
    assert report.of(audit.Finding.RECORDER_TARGET_FILTER)


async def test_camera_discovery_and_audit(link_to) -> None:
    link = await link_to(FakeDevice(profile="camera_g3"))
    profile = await discover.discover(link)
    assert profile.shape is DeviceShape.CAMERA
    assert list(profile.channels) == ["1"]
    channel = profile.channels["1"]
    assert channel.name == profile.identity.name
    assert Kind.LINE_CROSSING in channel.switchable
    report = await audit.run_audit(link, profile)
    assert not report.of(audit.Finding.CENTER_LINK_MISSING)
    off = {i.kind for i in report.of(audit.Finding.DETECTION_OFF)}
    assert {Kind.INTRUSION, Kind.LINE_CROSSING} <= off
    assert not report.of(audit.Finding.STREAM_ENCRYPTED)


async def test_switch_changes_only_enabled_and_verifies(link_to) -> None:
    device = FakeDevice(profile="camera_g3")
    link = await link_to(device)
    before = (await link.call("GET", "/ISAPI/Smart/LineDetection/1")).text
    state = await detection.switch(link, Kind.LINE_CROSSING, "1", True)
    assert state.enabled is True
    assert state.area_defined is True
    method, path, body = device.writes[-1]
    assert (method, path) == ("PUT", "/ISAPI/Smart/LineDetection/1")
    assert body == before.replace("<enabled>false</enabled>", "<enabled>true</enabled>", 1)


async def test_add_center_linkage(link_to) -> None:
    device = FakeDevice(profile="nvr")
    link = await link_to(device)
    assert await linkage.ensure_center(link, "fielddetection-1", dry_run=True) is True
    assert device.writes == []
    assert await linkage.ensure_center(link, "fielddetection-1", dry_run=False) is True
    written = device.writes[-1][2]
    assert written.count("<notificationMethod>center</notificationMethod>") == 1
    assert "<notificationMethod>record</notificationMethod>" in written
    # Already present: nothing to do.
    assert await linkage.ensure_center(link, "VMD-4", dry_run=False) is False
