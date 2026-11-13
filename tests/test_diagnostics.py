"""Tests für die Diagnosedaten (Schwärzung)."""

from __future__ import annotations

import json

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_tuerklingel.const import DOMAIN, KEY_CAMERA
from custom_components.homekit_tuerklingel.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import CAMERA, SHELLY_HOST, SHELLY_MAC, WEBHOOK_ID

BASE = f"http://{SHELLY_HOST}"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/shelly", json={"mac": SHELLY_MAC, "type": "SHSW-1"})
    aioclient_mock.get(f"{BASE}/settings", json={"relays": [{"btn_type": "detached"}]})
    hass.states.async_set(CAMERA, "idle")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_diagnostics_redacted(hass: HomeAssistant, mock_entry, aioclient_mock) -> None:
    """Zugangsdaten, Webhook-ID und MAC tauchen nirgends auf."""
    await _setup(hass, mock_entry, aioclient_mock)
    hub = mock_entry.runtime_data
    hub.snapshot = b"12345"
    hub.async_ring()
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, mock_entry)
    text = json.dumps(diag, default=str)
    for secret in ("geheim", "admin", WEBHOOK_ID, SHELLY_MAC):
        assert secret not in text

    data = diag["entry"]["data"]
    assert data["shelly_password"] == REDACTED
    assert data["shelly_username"] == REDACTED
    assert data["webhook_id"] == REDACTED
    assert data["shelly_mac"] == REDACTED
    assert data["shelly_host"] == SHELLY_HOST
    assert data["camera_entity"] == CAMERA
    assert diag["entry"]["unique_id"] == REDACTED
    assert diag["webhook_url"].endswith(f"/api/webhook/{REDACTED}")

    proxy = er.async_get(hass).async_get_entity_id(
        "camera", DOMAIN, f"{mock_entry.entry_id}_{KEY_CAMERA}"
    )
    assert diag["proxy_camera_entity_id"] == proxy
    assert diag["homekit"] == {"accessory_exists": False, "entries": []}

    status = diag["hub"]
    assert status["camera_entity_id"] == CAMERA
    assert status["shelly_available"] is True
    assert status["stats"]["rings"] == 1
    assert status["last_ring"] is not None
    assert status["snapshot"]["present"] is True
    assert status["snapshot"]["size"] == len(hub.snapshot)
    assert set(status) >= {"gong_enabled", "cooldown", "gong_duration", "restrict_ip"}


async def test_diagnostics_homekit_and_unloaded(
    hass: HomeAssistant, mock_entry, aioclient_mock
) -> None:
    """HomeKit-Zubehör wird angezeigt; ohne Laufzeitobjekt kein Hub-Teil."""
    await _setup(hass, mock_entry, aioclient_mock)
    proxy = er.async_get(hass).async_get_entity_id(
        "camera", DOMAIN, f"{mock_entry.entry_id}_{KEY_CAMERA}"
    )
    MockConfigEntry(
        domain="homekit",
        title="Haustür:21065",
        data={"mode": "accessory", "filter": {"include_entities": [proxy]}},
    ).add_to_hass(hass)
    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    mock_entry.runtime_data = None

    diag = await async_get_config_entry_diagnostics(hass, mock_entry)
    assert diag["hub"] is None
    assert diag["homekit"]["accessory_exists"] is True
    assert diag["homekit"]["entries"][0]["title"] == "Haustür:21065"
    assert diag["homekit"]["entries"][0]["disabled_by"] is None


async def test_diagnostics_without_proxy_camera(hass: HomeAssistant, mock_entry) -> None:
    """Nie eingerichteter Entry: keine Proxy-Kamera, kein Hub."""
    mock_entry.add_to_hass(hass)
    diag = await async_get_config_entry_diagnostics(hass, mock_entry)
    assert diag["proxy_camera_entity_id"] is None
    assert diag["homekit"]["accessory_exists"] is False
    assert diag["hub"] is None
