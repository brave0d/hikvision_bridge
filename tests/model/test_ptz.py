"""PTZ capabilities and presets."""

from __future__ import annotations

from custom_components.hikvision_bridge.model.features import ptz
from custom_components.hikvision_bridge.wire.xmlview import parse

NS = 'version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema"'
CAPS = (
    f"<PTZChanelCap {NS}><ContinuousPanTiltSpace><XRange><Min>-100</Min><Max>100</Max></XRange>"
    "</ContinuousPanTiltSpace><ContinuousZoomSpace><XRange><Min>-100</Min><Max>100</Max>"
    "</XRange></ContinuousZoomSpace><maxPresetNum>300</maxPresetNum></PTZChanelCap>"
)
PRESETS = (
    f"<PTZPresetList {NS}>"
    "<PTZPreset><enabled>true</enabled><id>1</id><presetName>Gate</presetName></PTZPreset>"
    "<PTZPreset><enabled>true</enabled><id>2</id><presetName>Gate</presetName></PTZPreset>"
    "<PTZPreset><enabled>true</enabled><id>3</id><presetName/></PTZPreset>"
    "<PTZPreset><enabled>false</enabled><id>4</id><presetName>Unset</presetName></PTZPreset>"
    "</PTZPresetList>"
)


def test_ptz_capabilities() -> None:
    found = ptz.parse_capabilities(parse(CAPS), parse(PRESETS))
    assert found is not None
    assert found.directions == list(ptz.DIRECTIONS)
    assert found.presets == {"1": "Gate", "2": "Gate (2)", "3": "Preset 3"}


def test_zoom_only_lens() -> None:
    caps = parse(
        f"<PTZChanelCap {NS}><ContinuousZoomSpace><XRange><Min>-100</Min><Max>100</Max>"
        "</XRange></ContinuousZoomSpace></PTZChanelCap>"
    )
    found = ptz.parse_capabilities(caps, None)
    assert found is not None
    assert found.directions == ["zoom_in", "zoom_out"]


def test_no_ptz() -> None:
    assert ptz.parse_capabilities(None, None) is None
    assert ptz.parse_capabilities(parse(f"<PTZChanelCap {NS}/>"), None) is None
