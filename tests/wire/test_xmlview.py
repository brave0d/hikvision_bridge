"""Namespace-free reading and raw in-place editing."""

from pathlib import Path

import pytest

from custom_components.hikvision_bridge.wire.xmlview import RawDocument, XmlError, parse

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_reads_across_namespaces() -> None:
    nvr = parse((FIXTURES / "nvr" / "ISAPI_System_deviceInfo.xml").read_text())
    assert nvr.name == "DeviceInfo"
    assert nvr.text("model") == "DS-0000NVR-T8"
    assert nvr.text("deviceType") == "NVR"

    cam = parse(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<A xmlns="http://www.hikvision.com/ver20/XMLSchema"><B><c>1</c></B></A>'
    )
    assert cam.text("B/c") == "1"
    assert cam.text("b/C") == "1"  # case-insensitive local names


def test_helpers() -> None:
    doc = parse("<r><on>true</on><n>42</n><e></e><cap opt='a, b,c'/></r>")
    assert doc.flag("on") is True
    assert doc.numeric("n") == 42
    assert doc.text("e") is None
    assert doc.text("missing", "x") == "x"
    assert doc.options("cap") == ["a", "b", "c"]


def test_rejects_entities() -> None:
    with pytest.raises((XmlError, Exception)):
        parse('<!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>')


def test_raw_edit_keeps_everything_else() -> None:
    original = (FIXTURES / "camera_g3" / "ISAPI_Smart_LineDetection_1.xml").read_text()
    doc = RawDocument(original)
    assert doc.get("enabled") == "false"
    assert doc.count("LineItemList/LineItem/enabled") == 4
    assert doc.set("enabled", "true")
    assert doc.get("enabled") == "true"
    # only the first top-level element changed
    assert doc.text.replace("<enabled>true</enabled>", "<enabled>false</enabled>", 1) == original
    assert doc.get("LineItemList/LineItem/enabled", 0) == "false"


def test_raw_edit_nested_occurrence_and_self_closing() -> None:
    doc = RawDocument("<r xmlns='x'><l><i><v>1</v></i><i><v>2</v></i></l><s/><s2 a='1'/></r>")
    assert doc.set("l/i/v", "9", occurrence=1)
    assert doc.text.count(">9<") == 1
    assert doc.get("l/i/v", 0) == "1"
    assert doc.set("s", "x")
    assert "<s>x</s>" in doc.text
    assert doc.set("s2", "<&>")
    assert "<s2 a='1'>&lt;&amp;&gt;</s2>" in doc.text
    assert not doc.set("missing", "1")
