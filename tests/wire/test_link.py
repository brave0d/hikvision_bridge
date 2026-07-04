"""Authentication negotiation, lockout protection and error mapping of IsapiLink."""

import asyncio

import aiohttp
from aiohttp.test_utils import TestServer
import pytest

from custom_components.hikvision_bridge.wire import faults
from custom_components.hikvision_bridge.wire.link import Endpoint, IsapiLink
from tests.fakedevice import FakeDevice

pytestmark = pytest.mark.usefixtures("socket_enabled")


async def _serve(device: FakeDevice):
    server = TestServer(device.app())
    await server.start_server()
    return server


@pytest.fixture
async def rig():
    started = []

    async def make(device: FakeDevice, *, username=None, password=None):
        server = await _serve(device)
        session = aiohttp.ClientSession()
        started.append((server, session))
        link = IsapiLink(
            session,
            Endpoint(server.host, server.port, "http"),
            username if username is not None else device.username,
            password if password is not None else device.password,
        )
        return link

    yield make
    for server, session in started:
        await session.close()
        await server.close()


async def test_first_request_is_unauthenticated_and_digest_follows(rig) -> None:
    device = FakeDevice()
    link = await rig(device)
    info = await link.read_xml("/ISAPI/System/deviceInfo")
    assert info.text("deviceType") == "NVR"
    assert link.auth_scheme == "digest"
    assert device.failed_logins == 0
    assert device.requests[0] == ("GET", "/ISAPI/System/deviceInfo")


async def test_wrong_password_stops_after_one_attempt(rig) -> None:
    device = FakeDevice()
    link = await rig(device, password="wrong")
    with pytest.raises(faults.BadCredentials):
        await link.read_xml("/ISAPI/System/deviceInfo")
    assert device.failed_logins == 1
    # Further calls never reach the device.
    before = len(device.requests)
    for _ in range(3):
        with pytest.raises(faults.BadCredentials):
            await link.read_xml("/ISAPI/Event/triggers")
    assert len(device.requests) == before
    assert device.failed_logins == 1

    link.replace_credentials(device.username, device.password)
    assert (await link.read_xml("/ISAPI/System/deviceInfo")) is not None


async def test_expired_nonce_is_renewed_once_without_counting_as_failure(rig) -> None:
    device = FakeDevice()
    link = await rig(device)
    await link.read_xml("/ISAPI/System/deviceInfo")
    device.expire_nonces()
    assert (await link.read_xml("/ISAPI/Event/triggers")) is not None
    assert device.failed_logins == 0


async def test_parallel_requests_survive_an_expired_nonce(rig) -> None:
    device = FakeDevice()
    link = await rig(device)
    await link.read_xml("/ISAPI/System/deviceInfo")
    for _ in range(3):
        device.expire_nonces()
        results = await asyncio.gather(
            link.read_xml("/ISAPI/Event/triggers"),
            link.read_xml("/ISAPI/System/deviceInfo"),
        )
        assert all(result is not None for result in results)
    assert link.blocked is None
    assert device.failed_logins == 0


async def test_lock_is_reported_and_blocks(rig) -> None:
    device = FakeDevice(lock_after=0)
    link = await rig(device)
    with pytest.raises(faults.LockedOut) as caught:
        await link.read_xml("/ISAPI/System/deviceInfo")
    assert caught.value.retry_after == 1800
    assert isinstance(link.blocked, faults.LockedOut)


async def test_optional_unsupported_is_remembered(rig) -> None:
    device = FakeDevice()
    link = await rig(device)
    assert await link.read_xml("/ISAPI/System/Holidays", optional=True) is None
    count = len(device.requests)
    assert await link.read_xml("/ISAPI/System/Holidays", optional=True) is None
    assert len(device.requests) == count
    with pytest.raises(faults.Unsupported):
        await link.read_xml("/ISAPI/ContentMgmt/storage/hdd")
    # 503 on the host capability endpoint is "unsupported", not an outage.
    assert (
        await link.read_xml("/ISAPI/Event/notification/httpHosts/capabilities", optional=True)
        is None
    )


async def test_unreachable() -> None:
    async with aiohttp.ClientSession() as session:
        link = IsapiLink(session, Endpoint("127.0.0.1", 1, "http"), "u", "p", connect_timeout=1)
        with pytest.raises(faults.Unreachable):
            await link.read_xml("/ISAPI/System/deviceInfo")


async def test_not_isapi(rig) -> None:
    device = FakeDevice(require_auth=False)
    device._index["/ISAPI/System/deviceInfo"] = (404, "<html>nope</html>")
    link = await rig(device)
    with pytest.raises(faults.NotIsapi):
        await link.read_xml("/ISAPI/System/deviceInfo")


async def test_write_round_trip(rig) -> None:
    device = FakeDevice(profile="camera_g3")
    link = await rig(device)
    reply = await link.write_xml(
        "/ISAPI/Smart/LineDetection/1", "<LineDetection><enabled>true</enabled></LineDetection>"
    )
    assert reply.status == 200
    assert device.writes[0][1] == "/ISAPI/Smart/LineDetection/1"
