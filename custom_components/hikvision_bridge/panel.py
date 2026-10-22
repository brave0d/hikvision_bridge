"""Recordings panel in the sidebar and the dashboard card, served from this folder."""

from __future__ import annotations

import hashlib
from pathlib import Path

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant

from .runtime import sessions

URL_BASE = "/hikvision_bridge_static"
PANEL_PATH = "hikvision-bridge"
MODULE = "hikvision-bridge.js"
FOLDER = Path(__file__).parent / "frontend"


def _fingerprint() -> str:
    return hashlib.sha256((FOLDER / MODULE).read_bytes()).hexdigest()[:12]


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the files, add the sidebar panel and make the card available on dashboards."""

    async def _stop_sessions(_event: Event) -> None:
        await sessions.manager(hass).stop_all()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop_sessions)
    if "frontend" not in hass.config.components:
        return
    from homeassistant.components import frontend, panel_custom  # noqa: PLC0415
    from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

    await hass.http.async_register_static_paths(
        [StaticPathConfig(URL_BASE, str(FOLDER), cache_headers=False)]
    )
    # The fingerprint makes browsers load a changed file after an update.
    url = f"{URL_BASE}/{MODULE}?v={await hass.async_add_executor_job(_fingerprint)}"
    frontend.add_extra_js_url(hass, url)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_PATH,
        webcomponent_name="hikvision-bridge-panel",
        sidebar_title="Hikvision",
        sidebar_icon="mdi:cctv",
        module_url=url,
        require_admin=False,
    )
