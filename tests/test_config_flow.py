"""Tests für Config-Flow und Options-Flow."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_tuerklingel.config_flow import WEBHOOK_OFF_HINT
from custom_components.homekit_tuerklingel.const import (
    CONF_ALLOWED_SOURCES,
    CONF_AUTO_OFF,
    CONF_CAMERA_ENTITY,
    CONF_GONG_ENTITY,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_MESSAGE,
    CONF_NOTIFY_SERVICES,
    CONF_NOTIFY_TITLE,
    CONF_RESTRICT_IP,
    CONF_TRIGGER_ENTITIES,
    CONF_WEBHOOK_ENABLED,
    CONF_WEBHOOK_ID,
    CONFIG_VERSION,
    DEFAULT_AUTO_OFF,
    DEFAULT_NOTIFY_ENABLED,
    DEFAULT_NOTIFY_MESSAGE,
    DEFAULT_NOTIFY_TITLE,
    DOMAIN,
    ISSUE_GONG_SELECT,
)

from .conftest import CAMERA, GONG, SHELLY_HOST, TRIGGER, WEBHOOK_ID

INTERNAL_URL = "http://192.168.1.10:8123"
CAMERA_2 = "camera.garten"


@pytest.fixture(autouse=True)
def mock_setup_entry():
    """Einrichtung des Entry umgehen – hier geht es nur um den Flow."""
    with patch(
        "custom_components.homekit_tuerklingel.async_setup_entry", return_value=True
    ) as mock:
        yield mock


@pytest.fixture(autouse=True)
async def internal_url(hass: HomeAssistant) -> None:
    """Feste interne URL, damit die Webhook-URL vorhersagbar ist."""
    await async_process_ha_core_config(hass, {"internal_url": INTERNAL_URL})


async def _start(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


def _user_input(**overrides) -> dict:
    data = {
        CONF_NAME: " Haustür ",
        CONF_CAMERA_ENTITY: CAMERA,
        CONF_WEBHOOK_ENABLED: True,
        CONF_TRIGGER_ENTITIES: [TRIGGER],
        CONF_GONG_ENTITY: GONG,
    }
    data.update(overrides)
    return {key: value for key, value in data.items() if value is not None}


def _selector_config(result: dict, key: str) -> dict:
    for marker, value in result["data_schema"].schema.items():
        if marker == key:
            return value.config
    raise AssertionError(key)


def _suggested(result: dict, key: str):
    for marker in result["data_schema"].schema:
        if marker == key:
            return (marker.description or {}).get("suggested_value")
    raise AssertionError(key)


# ---------------------------------------------------------------- Config-Flow


async def test_flow_mit_webhook_und_quellen(hass: HomeAssistant) -> None:
    """Webhook mit Beschränkung: Quellen werden zerlegt, Entry vollständig angelegt."""
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch(
        "custom_components.homekit_tuerklingel.config_flow.async_generate_id",
        return_value=WEBHOOK_ID,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _user_input()
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "webhook"
    url = f"{INTERNAL_URL}/api/webhook/{WEBHOOK_ID}"
    assert result["description_placeholders"] == {"webhook_url": url}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_RESTRICT_IP: True,
            CONF_ALLOWED_SOURCES: f" {SHELLY_HOST}, [fe80::1]; klingel.local ",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Haustür"
    assert result["data"] == {CONF_WEBHOOK_ID: WEBHOOK_ID, CONF_CAMERA_ENTITY: CAMERA}
    assert result["options"] == {
        CONF_WEBHOOK_ENABLED: True,
        CONF_RESTRICT_IP: True,
        CONF_ALLOWED_SOURCES: [SHELLY_HOST, "fe80::1", "klingel.local"],
        CONF_TRIGGER_ENTITIES: [TRIGGER],
        CONF_GONG_ENTITY: GONG,
        CONF_AUTO_OFF: DEFAULT_AUTO_OFF,
        CONF_NOTIFY_ENABLED: DEFAULT_NOTIFY_ENABLED,
        CONF_NOTIFY_SERVICES: [],
        CONF_NOTIFY_TITLE: DEFAULT_NOTIFY_TITLE,
        CONF_NOTIFY_MESSAGE: DEFAULT_NOTIFY_MESSAGE,
    }
    assert result["description_placeholders"] == {"webhook_hint": f"`{url}`"}
    entry = result["result"]
    assert entry.version == CONFIG_VERSION
    assert entry.minor_version == 1


async def test_flow_webhook_ohne_beschraenkung(hass: HomeAssistant) -> None:
    """Webhook ohne Beschränkung, keine Entitäten, kein Gong."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _user_input(**{CONF_TRIGGER_ENTITIES: None, CONF_GONG_ENTITY: None}),
    )
    assert result["step_id"] == "webhook"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    options = result["options"]
    assert options[CONF_RESTRICT_IP] is False
    assert options[CONF_ALLOWED_SOURCES] == []
    assert options[CONF_TRIGGER_ENTITIES] == []
    assert options[CONF_GONG_ENTITY] is None
    assert result["data"][CONF_WEBHOOK_ID]  # zufällig erzeugt


async def test_flow_nur_entitaeten(hass: HomeAssistant) -> None:
    """Ohne Webhook: kein Webhook-Schritt, Hinweis „—“."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input(**{CONF_WEBHOOK_ENABLED: False})
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_WEBHOOK_ENABLED] is False
    assert result["options"][CONF_TRIGGER_ENTITIES] == [TRIGGER]
    assert result["description_placeholders"] == {"webhook_hint": WEBHOOK_OFF_HINT}


async def test_flow_fehler_user(hass: HomeAssistant) -> None:
    """Kein Auslöser und leerer Name werden gemeldet, Eingaben bleiben erhalten."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _user_input(
            **{CONF_NAME: "   ", CONF_WEBHOOK_ENABLED: False, CONF_TRIGGER_ENTITIES: []}
        ),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "no_trigger", CONF_NAME: "name_required"}
    assert _suggested(result, CONF_CAMERA_ENTITY) == CAMERA


async def test_flow_kamera_belegt(hass: HomeAssistant, mock_entry) -> None:
    """Eine Kamera gehört höchstens zu einer Klingel."""
    mock_entry.add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input()
    )
    assert result["errors"] == {CONF_CAMERA_ENTITY: "camera_in_use"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input(**{CONF_CAMERA_ENTITY: CAMERA_2})
    )
    assert result["step_id"] == "webhook"


@pytest.mark.parametrize(
    ("restrict", "sources", "error"),
    [
        (False, "192.168.1.50, -ungültig-", "invalid_source"),
        (True, "999.1.1.1", "invalid_source"),
        (True, " , ", "source_required"),
        (True, None, "source_required"),
    ],
)
async def test_flow_fehler_quellen(
    hass: HomeAssistant, restrict: bool, sources: str | None, error: str
) -> None:
    """Ungültige oder fehlende Quellen; danach lässt sich der Flow abschließen."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input()
    )
    user_input = {CONF_RESTRICT_IP: restrict}
    if sources is not None:
        user_input[CONF_ALLOWED_SOURCES] = sources
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "webhook"
    assert result["errors"] == {CONF_ALLOWED_SOURCES: error}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RESTRICT_IP: True, CONF_ALLOWED_SOURCES: SHELLY_HOST}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_ALLOWED_SOURCES] == [SHELLY_HOST]


async def test_flow_eigene_entitaeten_ausgeschlossen(hass: HomeAssistant) -> None:
    """Eigene Entitäten der Integration stehen nicht zur Auswahl (keine Schleifen)."""
    ent_reg = er.async_get(hass)
    own_cam = ent_reg.async_get_or_create("camera", DOMAIN, "x_kamera").entity_id
    own_event = ent_reg.async_get_or_create("event", DOMAIN, "x_klingel").entity_id
    own_bs = ent_reg.async_get_or_create(
        "binary_sensor", DOMAIN, "x_klingelt"
    ).entity_id
    own_gong = ent_reg.async_get_or_create("switch", DOMAIN, "x_gong").entity_id
    ent_reg.async_get_or_create("switch", "shelly", "relais")

    result = await _start(hass)
    assert _selector_config(result, CONF_CAMERA_ENTITY)["exclude_entities"] == [own_cam]
    triggers = _selector_config(result, CONF_TRIGGER_ENTITIES)
    assert triggers["multiple"] is True
    assert sorted(triggers["exclude_entities"]) == sorted([own_event, own_bs])
    assert _selector_config(result, CONF_GONG_ENTITY)["exclude_entities"] == [own_gong]


# ---------------------------------------------------------------- Options-Flow


async def _options(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    entry.add_to_hass(hass)
    return await hass.config_entries.options.async_init(entry.entry_id)


def _options_input(**overrides) -> dict:
    data = {
        CONF_CAMERA_ENTITY: CAMERA,
        CONF_WEBHOOK_ENABLED: True,
        CONF_RESTRICT_IP: True,
        CONF_ALLOWED_SOURCES: SHELLY_HOST,
        CONF_TRIGGER_ENTITIES: [TRIGGER],
        CONF_GONG_ENTITY: GONG,
        CONF_AUTO_OFF: 7.0,
        CONF_NOTIFY_ENABLED: False,
    }
    data.update(overrides)
    return {key: value for key, value in data.items() if value is not None}


async def test_options_formular(hass: HomeAssistant, mock_entry) -> None:
    """Formular zeigt aktuelle Werte, Webhook-URL und notify-Dienste."""

    async def _handler(call: ServiceCall) -> None:
        return None

    hass.services.async_register("notify", "mobile_app_telefon", _handler)
    hass.services.async_register("notify", "send_message", _handler)
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_entry,
        options={
            **mock_entry.options,
            CONF_ALLOWED_SOURCES: [SHELLY_HOST, "klingel.local"],
            CONF_GONG_ENTITY: None,
            CONF_NOTIFY_SERVICES: ["alter_dienst"],
        },
    )
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    url = f"{INTERNAL_URL}/api/webhook/{WEBHOOK_ID}"
    assert result["description_placeholders"] == {
        "webhook_url": f"`{url}`",
        "name": "{name}",
    }
    assert _suggested(result, CONF_CAMERA_ENTITY) == CAMERA
    assert _suggested(result, CONF_ALLOWED_SOURCES) == f"{SHELLY_HOST}, klingel.local"
    assert _suggested(result, CONF_GONG_ENTITY) is None
    assert _suggested(result, CONF_AUTO_OFF) == DEFAULT_AUTO_OFF
    assert _selector_config(result, CONF_NOTIFY_SERVICES)["options"] == [
        "alter_dienst",
        "mobile_app_telefon",
    ]


async def test_options_webhook_aus_hinweis(hass: HomeAssistant, mock_entry) -> None:
    """Bei ausgeschaltetem Webhook zeigt die Beschreibung „—“."""
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_entry, options={**mock_entry.options, CONF_WEBHOOK_ENABLED: False}
    )
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    assert result["description_placeholders"]["webhook_url"] == WEBHOOK_OFF_HINT


async def test_options_speichern(hass: HomeAssistant, mock_entry) -> None:
    """Kamera wechseln (entry.data), Gong leer → None, notify bereinigt, Hinweis gelöscht."""
    mock_entry.add_to_hass(hass)
    issue_id = f"{ISSUE_GONG_SELECT}_{mock_entry.entry_id}"
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_GONG_SELECT,
        translation_placeholders={"name": mock_entry.title},
    )
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _options_input(
            **{
                CONF_CAMERA_ENTITY: CAMERA_2,
                CONF_GONG_ENTITY: None,
                CONF_ALLOWED_SOURCES: f"{SHELLY_HOST},klingel.local",
                CONF_NOTIFY_ENABLED: True,
                CONF_NOTIFY_SERVICES: ["notify.mobile_app_telefon", "  ", "pushover"],
                CONF_NOTIFY_TITLE: "  ",
                CONF_NOTIFY_MESSAGE: " Tür {name} ",
            }
        ),
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    expected = {
        CONF_WEBHOOK_ENABLED: True,
        CONF_RESTRICT_IP: True,
        CONF_ALLOWED_SOURCES: [SHELLY_HOST, "klingel.local"],
        CONF_TRIGGER_ENTITIES: [TRIGGER],
        CONF_GONG_ENTITY: None,
        CONF_AUTO_OFF: 7,
        CONF_NOTIFY_ENABLED: True,
        CONF_NOTIFY_SERVICES: ["mobile_app_telefon", "pushover"],
        CONF_NOTIFY_TITLE: DEFAULT_NOTIFY_TITLE,
        CONF_NOTIFY_MESSAGE: "Tür {name}",
    }
    assert result["data"] == expected
    assert dict(mock_entry.options) == expected
    assert dict(mock_entry.data) == {
        CONF_WEBHOOK_ID: WEBHOOK_ID,
        CONF_CAMERA_ENTITY: CAMERA_2,
    }
    assert isinstance(mock_entry.options[CONF_AUTO_OFF], int)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_options_ein_neuladen(hass: HomeAssistant, mock_entry) -> None:
    """Daten und Optionen werden zusammen gespeichert: Update-Listener nur einmal."""
    mock_entry.add_to_hass(hass)
    calls: list[str] = []

    async def _listener(hass: HomeAssistant, entry) -> None:
        calls.append(entry.data[CONF_CAMERA_ENTITY])

    mock_entry.add_update_listener(_listener)
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], _options_input(**{CONF_CAMERA_ENTITY: CAMERA_2})
    )
    await hass.async_block_till_done()
    assert calls == [CAMERA_2]


async def test_options_nur_entitaeten(hass: HomeAssistant, mock_entry) -> None:
    """Webhook aus: Beschränkung ohne Quellen ist erlaubt."""
    result = await _options(hass, mock_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _options_input(**{CONF_WEBHOOK_ENABLED: False, CONF_ALLOWED_SOURCES: None}),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_WEBHOOK_ENABLED] is False
    assert result["data"][CONF_ALLOWED_SOURCES] == []


@pytest.mark.parametrize(
    ("overrides", "errors"),
    [
        (
            {CONF_WEBHOOK_ENABLED: False, CONF_TRIGGER_ENTITIES: []},
            {"base": "no_trigger"},
        ),
        (
            {CONF_WEBHOOK_ENABLED: False, CONF_TRIGGER_ENTITIES: None},
            {"base": "no_trigger"},
        ),
        (
            {CONF_ALLOWED_SOURCES: "klingel..local"},
            {CONF_ALLOWED_SOURCES: "invalid_source"},
        ),
        ({CONF_ALLOWED_SOURCES: None}, {CONF_ALLOWED_SOURCES: "source_required"}),
        ({CONF_CAMERA_ENTITY: CAMERA_2}, {CONF_CAMERA_ENTITY: "camera_in_use"}),
    ],
)
async def test_options_fehler(
    hass: HomeAssistant, mock_entry, overrides: dict, errors: dict
) -> None:
    """Gleiche Prüfungen wie bei der Einrichtung; Eingaben bleiben erhalten."""
    MockConfigEntry(
        domain=DOMAIN,
        title="Garten",
        data={CONF_WEBHOOK_ID: "anderer", CONF_CAMERA_ENTITY: CAMERA_2},
        version=CONFIG_VERSION,
    ).add_to_hass(hass)
    result = await _options(hass, mock_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _options_input(**overrides)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == errors
    assert _suggested(result, CONF_AUTO_OFF) == 7.0
    assert dict(mock_entry.data)[CONF_CAMERA_ENTITY] == CAMERA


async def test_options_eigene_kamera_bleibt_erlaubt(
    hass: HomeAssistant, mock_entry
) -> None:
    """Die eigene Kamera gilt nicht als belegt."""
    result = await _options(hass, mock_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _options_input()
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(mock_entry.data)[CONF_CAMERA_ENTITY] == CAMERA
