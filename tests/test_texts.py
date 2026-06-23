"""German and English texts cover the same keys, and every key the code uses exists."""

from __future__ import annotations

import json
from pathlib import Path
import re

from custom_components.hikvision_bridge.model.audit import Finding
from custom_components.hikvision_bridge.model.vocabulary import SMART, SWITCHABLE

PACKAGE = Path(__file__).parent.parent / "custom_components" / "hikvision_bridge"
EN = json.loads((PACKAGE / "translations" / "en.json").read_text(encoding="utf-8"))
DE = json.loads((PACKAGE / "translations" / "de.json").read_text(encoding="utf-8"))
SOURCE = "\n".join(p.read_text(encoding="utf-8") for p in PACKAGE.rglob("*.py"))


def _keys(tree: object, prefix: str = "") -> set[str]:
    if not isinstance(tree, dict):
        return {prefix}
    found: set[str] = set()
    for key, value in tree.items():
        found |= _keys(value, f"{prefix}.{key}" if prefix else key)
    return found


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", text))


def _leaves(tree: object, prefix: str = "") -> dict[str, str]:
    if isinstance(tree, dict):
        out: dict[str, str] = {}
        for key, value in tree.items():
            out |= _leaves(value, f"{prefix}.{key}" if prefix else key)
        return out
    return {prefix: str(tree)}


def test_languages_have_identical_keys_and_placeholders() -> None:
    assert _keys(EN) == _keys(DE)
    en, de = _leaves(EN), _leaves(DE)
    for key, text in en.items():
        assert _placeholders(text) == _placeholders(de[key]), key


def test_exception_keys_used_in_code_exist() -> None:
    used = set(re.findall(r'translation_domain=DOMAIN,\s*translation_key="(\w+)"', SOURCE))
    assert used
    assert used <= set(EN["exceptions"]), used - set(EN["exceptions"])


def test_issue_keys_exist() -> None:
    issues = set(EN["issues"])
    assert {f.value for f in Finding} <= issues
    assert {"locked_out", "channel_link_auth", "channel_link_mismatch"} <= issues


def test_entity_keys_exist() -> None:
    assert {f"{k.value}_detection" for k in SWITCHABLE} <= set(EN["entity"]["switch"])
    states = EN["entity"]["event"]["detection"]["state_attributes"]["event_type"]["state"]
    assert {k.value for k in SMART} <= set(states)


def test_config_errors_cover_flow_error_keys() -> None:
    flow = (PACKAGE / "config_flow.py").read_text(encoding="utf-8")
    keys = set(re.findall(r'faults\.\w+: "(\w+)"', flow)) | {"captcha_required", "wrong_camera"}
    assert keys <= set(EN["config"]["error"])
    assert keys - {"captcha_required"} <= set(EN["config_subentries"]["channel_link"]["error"])
