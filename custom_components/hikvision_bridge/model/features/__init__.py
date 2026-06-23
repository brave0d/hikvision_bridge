"""Per-feature reading and writing on top of the transport layer."""

from __future__ import annotations

from ...wire.faults import DeviceRejected, Unsupported
from ...wire.link import IsapiLink
from ...wire.xmlview import RawDocument


class VerifyMismatch(DeviceRejected):
    """The device accepted a write but reads back a different value."""

    translation_key = "verify_mismatch"


async def patch_and_verify(
    link: IsapiLink,
    path: str,
    edits: dict[str, str],
    *,
    fallback_path: str | None = None,
) -> RawDocument:
    """Read-modify-write ``path`` changing only ``edits`` (element path -> text).

    The original document text is kept, so unknown elements, ordering and namespace
    declarations survive. If the device refuses the full document as unsupported and a
    ``fallback_path`` exists, the same edit is applied there. The result is read back and
    compared.
    """
    target = path
    try:
        document = await _edit(link, target, edits)
    except Unsupported:
        if fallback_path is None:
            raise
        target = fallback_path
        document = await _edit(link, target, edits)

    check = RawDocument((await link.call("GET", target)).text)
    for element, value in edits.items():
        actual = check.get(element)
        if actual is not None and actual.lower() != value.lower():
            raise VerifyMismatch(
                f"{element} reads back as {actual!r} instead of {value!r}", 200, "verify"
            )
    return document


async def _edit(link: IsapiLink, path: str, edits: dict[str, str]) -> RawDocument:
    document = RawDocument((await link.call("GET", path)).text)
    for element, value in edits.items():
        if not document.set(element, value):
            raise Unsupported(f"{path} has no element {element}")
    await link.write_xml(path, document.text)
    return document
