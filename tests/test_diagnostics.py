"""Tests für die Diagnosedaten (Schwärzung)."""

from __future__ import annotations

import json
from http import HTTPStatus

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_tuerklingel.const import (
    CONF_ALLOWED_SOURCES,
    CONF_RESTRICT_IP,
    CONF_TRIGGER_ENTITIES,
    DOMAIN,
    KEY_CAMERA,
)
from custom_components.homekit_tuerklingel.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import CAMERA, GONG, SHELLY_HOST, TRIGGER, WEBHOOK_ID


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    hass.states.async_set(CAMERA, "idle")
    hass.states.async_set(TRIGGER, "off")
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_diagnostics_redacted(hass: HomeAssistant, mock_entry) -> None:
    """Webhook-ID und erlaubte Quellen tauchen nirgends auf; keine Shelly-Felder."""
    await _setup(hass, mock_entry)
    hub = mock_entry.runtime_data
    hub.gong_enabled = False
    hub.snapshot = b"12345"
    hass.states.async_set(TRIGGER, "on")
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, mock_entry)
    text = json.dumps(diag, default=str)
    for secret in (WEBHOOK_ID, SHELLY_HOST):
        assert secret not in text
    assert "shelly" not in text.lower()

    entry = diag["entry"]
    assert entry["version"] == 2
    assert entry["unique_id"] is None  # None wird von async_redact_data nicht ersetzt
    assert entry["data"] == {"webhook_id": REDACTED, "camera_entity": CAMERA}
    options = entry["options"]
    assert options["allowed_sources"] == REDACTED
    assert options["restrict_ip"] is True
    assert options["trigger_entities"] == [TRIGGER]
    assert options["gong_entity"] == GONG
    assert diag["webhook_url"].endswith(f"/api/webhook/{REDACTED}")

    proxy = er.async_get(hass).async_get_entity_id(
        "camera", DOMAIN, f"{mock_entry.entry_id}_{KEY_CAMERA}"
    )
    assert diag["proxy_camera_entity_id"] == proxy
    assert diag["homekit"] == {"accessory_exists": False, "entries": []}

    status = diag["hub"]
    assert status["camera_entity_id"] == CAMERA
    assert status["webhook_enabled"] is True
    assert status["restrict_ip"] is True
    assert status["allowed_sources"] == REDACTED
    assert status["allowed_sources_count"] == 1
    assert status["trigger_entities"] == [TRIGGER]
    assert status["gong_entity_id"] == GONG
    assert status["gong_enabled"] is False
    assert status["event_entity_id"] == hub.event_entity_id
    assert status["stats"]["rings"] == 1
    assert status["stats"]["entity_triggers"] == 1
    assert status["stats"]["last_call"]["entity_id"] == TRIGGER
    assert status["last_ring"] is not None
    assert status["snapshot"]["present"] is True
    assert status["snapshot"]["size"] == len(hub.snapshot)
    assert set(status) >= {"cooldown", "gong_duration", "image_entity_id"}


async def test_diagnostics_webhook_remote_redacted(
    hass: HomeAssistant, mock_entry, hass_client_no_auth
) -> None:
    """Quell-IP des letzten Webhook-Aufrufs wird geschwärzt; leere Quellenliste bleibt []."""
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_entry,
        options={CONF_RESTRICT_IP: False, CONF_ALLOWED_SOURCES: [], CONF_TRIGGER_ENTITIES: []},
    )
    await _setup(hass, mock_entry)
    mock_entry.runtime_data.gong_enabled = False
    client = await hass_client_no_auth()
    assert (await client.get(f"/api/webhook/{WEBHOOK_ID}")).status == HTTPStatus.OK
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, mock_entry)
    last = diag["hub"]["stats"]["last_call"]
    assert last["source"] == "webhook"
    assert last["remote"] == REDACTED
    assert diag["hub"]["allowed_sources"] == []
    assert diag["hub"]["gong_entity_id"] is None


async def test_diagnostics_homekit_and_unloaded(hass: HomeAssistant, mock_entry) -> None:
    """HomeKit-Zubehör wird angezeigt; ohne Laufzeitobjekt kein Hub-Teil."""
    await _setup(hass, mock_entry)
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
