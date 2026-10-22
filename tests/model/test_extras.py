"""Strobe light, siren, speaker, device status, recording and armable inputs."""

from __future__ import annotations

from datetime import UTC, datetime

from custom_components.hikvision_bridge.model.features import adjust, health, io, signals, speaker
from custom_components.hikvision_bridge.wire.xmlview import parse

NS = 'version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema"'


def test_strobe_capabilities_and_values() -> None:
    caps = signals.parse_strobe_capabilities(
        {
            "WhiteLightAlarmCap": {
                "durationTime": {"@min": 1, "@max": 60},
                "frequency": {"@opt": "high,medium,low,normallyOn"},
            }
        }
    )
    assert caps["strobe_duration"].minimum == 1
    assert caps["strobe_duration"].maximum == 60
    assert caps["strobe_frequency"].options == ("high", "medium", "low", "normallyOn")

    values = signals.parse_values(
        {"WhiteLightAlarm": {"durationTime": 15, "frequency": "low"}},
        "WhiteLightAlarm",
        signals.STROBE,
        None,
    )
    assert values["strobe_duration"].value == "15"
    assert values["strobe_frequency"].value == "low"


def test_strobe_without_usable_ranges_offers_nothing() -> None:
    caps = signals.parse_strobe_capabilities(
        {
            "WhiteLightAlarmCap": {
                "durationTime": {"@min": 5, "@max": 5},
                "frequency": {"@opt": "low"},
            }
        }
    )
    assert caps == {}
    assert signals.parse_strobe_capabilities(None) == {}


def test_siren_sounds_use_device_names() -> None:
    caps = signals.parse_siren_capabilities(
        {
            "AudioAlarmCap": {
                "AlertAudioTypeListCap": [
                    {"alertAudioID": 1, "alertAudioDescription": "Siren"},
                    {"alertAudioID": 2, "alertAudioDescription": "Warning"},
                ],
                "audioVolume": {"@min": 1, "@max": 100},
                "alarmTimes": {"@min": 1, "@max": 50},
            }
        }
    )
    assert caps["siren_sound"].options == ("1", "2")
    assert caps["siren_sound"].labels == ("Siren", "Warning")
    assert caps["siren_volume"].maximum == 100
    assert caps["siren_repeats"].maximum == 50


def test_siren_older_firmware_and_ambiguous_names() -> None:
    caps = signals.parse_siren_capabilities(
        {
            "AudioAlarmCap": {
                "audioTypeListCap": [
                    {"audioID": 1, "audioDescription": "Same"},
                    {"audioID": 2, "audioDescription": "Same"},
                ]
            }
        }
    )
    assert "siren_sound" not in caps

    values = signals.parse_values(
        {"AudioAlarm": {"audioID": 3, "audioVolume": 70}}, "AudioAlarm", signals.SIREN, None
    )
    assert values["siren_sound"].field == "audioID"
    assert values["siren_sound"].value == "3"
    assert values["siren_volume"].value == "70"


def test_speaker_volumes() -> None:
    document = parse(
        f"<TwoWayAudioChannel {NS}><id>1</id><speakerVolume>60</speakerVolume>"
        "<microphoneVolume>40</microphoneVolume></TwoWayAudioChannel>"
    )
    caps = parse(
        f'<TwoWayAudioChannelCap {NS}><speakerVolume min="0" max="10"/></TwoWayAudioChannelCap>'
    )
    found = speaker.parse_capabilities(document, caps)
    assert (found["speaker_volume"].minimum, found["speaker_volume"].maximum) == (0, 10)
    # No range given: volumes are percentages.
    assert found["microphone_volume"].maximum == 100
    values = speaker.parse_values(document, {"microphone_volume"})
    assert set(values) == {"microphone_volume"}
    assert values["microphone_volume"].value == "40"


def test_all_sources_are_registered() -> None:
    for key in ("strobe_duration", "siren_sound", "speaker_volume", "brightness"):
        assert key in adjust.BY_KEY
    assert adjust.SOURCES["siren"].direct_only
    assert not adjust.SOURCES["strobe"].direct_only


def test_recorder_status() -> None:
    document = parse(
        f"<DeviceStatus {NS}><deviceUpTime>3600</deviceUpTime>"
        "<CPUList><CPU><cpuUtilization>12</cpuUtilization></CPU></CPUList>"
        "<MemoryList><Memory><memoryUsage>300</memoryUsage>"
        "<memoryAvailable>700</memoryAvailable></Memory></MemoryList>"
        "<totalRebootCount>4</totalRebootCount></DeviceStatus>"
    )
    status = health.parse_status(document, memory_in_mb=True)
    assert status == health.DeviceHealth(
        uptime_seconds=3600, cpu_percent=12, memory_percent=30.0, reboots=4
    )
    camera = health.parse_status(document, memory_in_mb=False)
    assert camera is not None
    assert camera.memory_percent is None
    assert health.parse_status(parse(f"<DeviceStatus {NS}/>"), memory_in_mb=True) is None
    timestamp = health.parse_status(
        parse(
            f"<DeviceStatus {NS}><deviceUpTime>3600</deviceUpTime>"
            "<totalRebootCount>1650480027</totalRebootCount></DeviceStatus>"
        ),
        memory_in_mb=False,
    )
    assert timestamp == health.DeviceHealth(
        uptime_seconds=3600,
        reboots_timestamp=datetime(2022, 4, 20, 18, 40, 27, tzinfo=UTC),
    )
    nonsense = health.parse_status(
        parse(
            f"<DeviceStatus {NS}><deviceUpTime>3600</deviceUpTime>"
            "<totalRebootCount>500000</totalRebootCount></DeviceStatus>"
        ),
        memory_in_mb=False,
    )
    assert nonsense == health.DeviceHealth(uptime_seconds=3600)


def test_recording_per_channel() -> None:
    document = {
        "WorkingStatus": {
            "ChanStatus": [
                {"chanNo": 1, "record": 1},
                {"chanNo": 2, "record": 0},
                {"chanNo": 3},
            ]
        }
    }
    assert health.parse_recording(document) == {"1": True, "2": False}
    assert health.parse_recording({}) == {}


def test_armed_inputs() -> None:
    document = parse(
        f"<IOInputPortList {NS}>"
        "<IOInputPort><id>1</id><enabled>true</enabled></IOInputPort>"
        "<IOInputPort><id>2</id><enabled>false</enabled></IOInputPort>"
        "<IOInputPort><id>3</id></IOInputPort>"
        "</IOInputPortList>"
    )
    assert io.parse_armed(document) == {"1": True, "2": False}
    assert io.parse_armed(None) == {}
