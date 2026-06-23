"""Alarm inputs and outputs."""

from __future__ import annotations

from ...wire.link import IsapiLink
from ...wire.xmlview import XmlNode
from ..inventory import IoPort

_OUTPUT_COMMAND = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<IOPortData version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">'
    "<outputState>{state}</outputState></IOPortData>"
)


def parse_ports(document: XmlNode | None, *, output: bool) -> dict[str, IoPort]:
    if document is None:
        return {}
    element = "IOOutputPort" if output else "IOInputPort"
    ports: dict[str, IoPort] = {}
    for node in document.children(element):
        port_id = node.text("id")
        if not port_id:
            continue
        proxied = node.first("IODescriptor") is not None or (node.text("IOType") or "").lower() == (
            "digitalchannel"
        )
        channel = None
        if proxied and port_id.isdigit() and len(port_id) >= 3:
            channel = str(int(port_id) // 100)
        ports[port_id] = IoPort(
            port_id=port_id,
            output=output,
            name=node.text("name"),
            channel_id=channel,
            proxied=proxied,
        )
    return ports


def _status_path(port: IoPort) -> str:
    direction = "outputs" if port.output else "inputs"
    return f"/ISAPI/System/IO/{direction}/{port.port_id}/status"


async def read_state(link: IsapiLink, port: IoPort) -> bool | None:
    document = await link.read_xml(_status_path(port), optional=True)
    if document is None:
        return None
    state = (document.text("ioState") or document.text("IOState") or "").lower()
    if state in ("active", "high"):
        return True
    if state in ("inactive", "low"):
        return False
    return None


async def set_output(link: IsapiLink, port: IoPort, on: bool) -> None:
    await link.write_xml(
        f"/ISAPI/System/IO/outputs/{port.port_id}/trigger",
        _OUTPUT_COMMAND.format(state="high" if on else "low"),
    )
