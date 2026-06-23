"""Read and act through a logged-in Hik-Connect account."""

from __future__ import annotations

from .account import CloudAccount
from .catalog import MAX_PAGES, PAGE_PATH, CloudDevice, page_params, parse_page

# Not yet verified against a real door station.
UNLOCK_PATH = "/v3/devconfig/v1/call/{serial}/{channel}/remote/unlock"


async def fetch_devices(account: CloudAccount) -> dict[str, CloudDevice]:
    """All devices of the account, keyed by their normalised serial."""
    found: dict[str, CloudDevice] = {}
    offset = 0
    for _page in range(MAX_PAGES):
        payload = await account.request("GET", PAGE_PATH, params=page_params(offset))
        devices, more = parse_page(payload)
        for device in devices:
            found[device.key] = device
        if not more or not devices:
            break
        offset += len(devices)
    return found


async def open_door_relay(account: CloudAccount, device: CloudDevice, lock_id: int = 0) -> None:
    """Open the door relay of an intercom through the cloud (one request, no retry)."""
    await account.request(
        "PUT",
        UNLOCK_PATH.format(serial=device.serial, channel=1),
        params={"srcId": "1", "lockId": str(lock_id), "userType": "0"},
    )
