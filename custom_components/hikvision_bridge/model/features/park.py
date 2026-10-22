"""Park action of a PTZ channel: what the camera does after it was left idle.

``/ISAPI/PTZCtrl/channels/<ch>/parkaction`` holds whether the park action is on, the idle
time and the action (preset, patrol, pattern, scans) with its number. Ranges and action types
come from ``parkaction/capabilities`` where the device offers it; otherwise the limits of the
web interface are used, as long as the park action document itself is readable.
"""

from __future__ import annotations

from ...wire.link import IsapiLink
from ...wire.xmlview import XmlNode
from . import patch_and_verify
from .image import ImageCapability, ImageSetting, ImageValue, Platform

PARK_PATH = "/ISAPI/PTZCtrl/channels/{ch}/parkaction"


def _s(key: str, platform: Platform, field: str, **kw) -> ImageSetting:
    return ImageSetting(
        key, platform, "ParkAction", "", (field,), enabled_default=True, source="park", **kw
    )


SETTINGS: tuple[ImageSetting, ...] = (
    _s("park_action", "switch", "enabled"),
    _s("park_time", "number", "Parktime", seconds=True),
    _s("park_action_type", "select", "Action/ActionType"),
    _s("park_action_number", "number", "Action/ActionNum"),
)

# Used when the device has no capability document for the park action.
DEFAULT_TIME = (5, 720)
DEFAULT_NUMBER = (1, 300)
DEFAULT_TYPES = (
    "autoscan",
    "framescan",
    "randomscan",
    "patrol",
    "pattern",
    "preset",
    "panoramascan",
    "tiltscan",
)


def _span(node: XmlNode | None, default: tuple[int, int]) -> tuple[int, int]:
    if node is None:
        return default
    try:
        low, high = int(node.attrs["min"]), int(node.attrs["max"])
    except (KeyError, ValueError):
        return default
    return (low, high) if high > low else default


def parse_capabilities(
    document: XmlNode | None, caps: XmlNode | None
) -> dict[str, ImageCapability]:
    """Park settings of a channel; nothing when the park action document is missing."""
    if document is None:
        return {}
    present = {s.key for s in SETTINGS if document.first(s.fields[0]) is not None}
    found: dict[str, ImageCapability] = {}
    if "park_action" in present:
        found["park_action"] = ImageCapability("park_action")
    if "park_time" in present:
        low, high = _span(caps.first("Parktime") if caps else None, DEFAULT_TIME)
        found["park_time"] = ImageCapability("park_time", minimum=low, maximum=high)
    if "park_action_type" in present:
        types = tuple(caps.options("Action/ActionType")) if caps else ()
        found["park_action_type"] = ImageCapability(
            "park_action_type", options=types if len(types) > 1 else DEFAULT_TYPES
        )
    if "park_action_number" in present:
        low, high = _span(caps.first("Action/ActionNum") if caps else None, DEFAULT_NUMBER)
        found["park_action_number"] = ImageCapability(
            "park_action_number", minimum=low, maximum=high
        )
    return found


def parse_values(document: XmlNode | None, keys: set[str] | None = None) -> dict[str, ImageValue]:
    if document is None:
        return {}
    values: dict[str, ImageValue] = {}
    for setting in SETTINGS:
        if keys is not None and setting.key not in keys:
            continue
        field = setting.fields[0]
        text = document.text(field)
        if text is not None:
            values[setting.key] = ImageValue(field, text)
    return values


async def read_capabilities(link: IsapiLink, channel_id: str) -> dict[str, ImageCapability]:
    path = PARK_PATH.format(ch=channel_id)
    document = await link.read_xml(path, optional=True)
    if document is None:
        return {}
    caps = await link.read_xml(f"{path}/capabilities", optional=True)
    return parse_capabilities(document, caps)


async def read_values(
    link: IsapiLink, channel_id: str, keys: set[str] | None = None
) -> dict[str, ImageValue] | None:
    document = await link.read_xml(PARK_PATH.format(ch=channel_id), optional=True)
    return parse_values(document, keys) if document is not None else None


async def write(link: IsapiLink, channel_id: str, key: str, field: str, value: str) -> None:
    await patch_and_verify(link, PARK_PATH.format(ch=channel_id), {field: value})
