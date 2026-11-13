"""Tests für Config-Flow und Options-Flow."""

from __future__ import annotations

from unittest.mock import patch

import aiohttp
import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homekit_tuerklingel.const import (
    CONF_ALLOWED_IP,
    CONF_AUTO_OFF,
    CONF_CAMERA_ENTITY,
    CONF_CONNECTIVITY,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_MESSAGE,
    CONF_NOTIFY_SERVICES,
    CONF_NOTIFY_TITLE,
    CONF_RESTRICT_IP,
    CONF_SHELLY_HOST,
    CONF_SHELLY_MAC,
    CONF_SHELLY_PASSWORD,
    CONF_SHELLY_USERNAME,
    CONF_WEBHOOK_ID,
    DEFAULT_AUTO_OFF,
    DEFAULT_NOTIFY_MESSAGE,
    DEFAULT_NOTIFY_TITLE,
    DOMAIN,
)

from .conftest import CAMERA, SHELLY_HOST, SHELLY_MAC, WEBHOOK_ID

BASE = f"http://{SHELLY_HOST}"
INTERNAL_URL = "http://192.168.1.10:8123"
SHELLY_JSON = {"type": "SHSW-1", "mac": SHELLY_MAC.lower(), "auth": False, "fw": "20230913"}
SETTINGS_DETACHED = {"relays": [{"btn_type": "detached"}]}

USER_INPUT = {
    CONF_NAME: "Haustür",
    CONF_SHELLY_HOST: f" http://{SHELLY_HOST}/ ",
    CONF_SHELLY_USERNAME: "admin",
    CONF_SHELLY_PASSWORD: "geheim",
}


@pytest.fixture(autouse=True)
def mock_setup_entry():
    """Einrichtung des Entry umgehen – hier geht es nur um den Flow."""
    with patch(
        "custom_components.homekit_tuerklingel.async_setup_entry", return_value=True
    ) as mock:
        yield mock


@pytest.fixture(autouse=True)
def internal_url(hass: HomeAssistant) -> None:
    """Feste interne URL für die Webhook-Adresse."""
    hass.config.internal_url = INTERNAL_URL


def mock_shelly(
    aioclient_mock: AiohttpClientMocker,
    *,
    shelly: dict | None = None,
    settings: dict | None = None,
    settings_status: int = 200,
    host: str = SHELLY_HOST,
) -> None:
    """Antworten des Shelly hinterlegen."""
    aioclient_mock.get(f"http://{host}/shelly", json=shelly or SHELLY_JSON)
    aioclient_mock.get(
        f"http://{host}/settings",
        json=settings if settings is not None else SETTINGS_DETACHED,
        status=settings_status,
    )


async def _start_user(hass: HomeAssistant, user_input: dict | None = None):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input or USER_INPUT
    )


async def test_user_flow_success(hass: HomeAssistant, aioclient_mock) -> None:
    """Kompletter Flow: Verbindungstest, Kamera, Entry mit Webhook-URL."""
    mock_shelly(aioclient_mock)
    result = await _start_user(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "camera"
    assert result["description_placeholders"] == {"detached_hint": ""}

    # Basic-Auth wurde an /settings gesendet, an /shelly nicht.
    settings_call = next(c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/settings"))
    assert settings_call[3]["Authorization"].startswith("Basic ")

    with patch(
        "custom_components.homekit_tuerklingel.config_flow.async_generate_id",
        return_value=WEBHOOK_ID,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CAMERA_ENTITY: CAMERA}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Haustür"
    assert result["data"] == {
        CONF_SHELLY_HOST: SHELLY_HOST,
        CONF_SHELLY_USERNAME: "admin",
        CONF_SHELLY_PASSWORD: "geheim",
        CONF_SHELLY_MAC: SHELLY_MAC,
        CONF_CAMERA_ENTITY: CAMERA,
        CONF_WEBHOOK_ID: WEBHOOK_ID,
    }
    assert CONF_NAME not in result["data"]
    assert result["options"] == {
        CONF_RESTRICT_IP: True,
        CONF_ALLOWED_IP: "",
        CONF_AUTO_OFF: DEFAULT_AUTO_OFF,
        CONF_CONNECTIVITY: True,
        CONF_NOTIFY_ENABLED: False,
        CONF_NOTIFY_SERVICES: [],
        CONF_NOTIFY_TITLE: DEFAULT_NOTIFY_TITLE,
        CONF_NOTIFY_MESSAGE: DEFAULT_NOTIFY_MESSAGE,
    }
    assert result["description_placeholders"] == {
        "webhook_url": f"{INTERNAL_URL}/api/webhook/{WEBHOOK_ID}"
    }
    assert result["result"].unique_id == SHELLY_MAC


async def test_user_flow_without_auth(hass: HomeAssistant, aioclient_mock) -> None:
    """Ohne Zugangsdaten: kein Authorization-Header, Werte None, Hinweis zum Eingang."""
    mock_shelly(aioclient_mock, settings={"relays": [{"btn_type": "momentary"}]})
    result = await _start_user(
        hass, {CONF_NAME: "  ", CONF_SHELLY_HOST: SHELLY_HOST}
    )
    assert result["step_id"] == "camera"
    hint = result["description_placeholders"]["detached_hint"]
    assert "„momentary“" in hint
    assert "Detached Switch" in hint
    assert all(not c[3] for c in aioclient_mock.mock_calls)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CAMERA_ENTITY: CAMERA}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Haustür"
    assert result["data"][CONF_SHELLY_USERNAME] is None
    assert result["data"][CONF_SHELLY_PASSWORD] is None
    assert len(result["data"][CONF_WEBHOOK_ID]) > 20


async def test_unknown_btn_type_no_hint(hass: HomeAssistant, aioclient_mock) -> None:
    """Eingangsmodus unbekannt → kein Hinweis."""
    mock_shelly(aioclient_mock, settings={})
    result = await _start_user(hass)
    assert result["description_placeholders"] == {"detached_hint": ""}


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"exc": aiohttp.ClientConnectionError()}, "cannot_connect"),
        ({"exc": TimeoutError()}, "cannot_connect"),
        ({"status": 404}, "not_shelly_gen1"),
        ({"text": "<html>Router</html>"}, "not_shelly_gen1"),
        ({"json": ["kein", "dict"]}, "not_shelly_gen1"),
        ({"json": {"type": "SHSW-1"}}, "not_shelly_gen1"),
        ({"json": {"mac": SHELLY_MAC, "gen": 2, "model": "SNSW-001X16EU"}}, "not_shelly_gen1"),
    ],
)
async def test_user_flow_shelly_errors(
    hass: HomeAssistant, aioclient_mock, kwargs: dict, error: str
) -> None:
    """Fehler beim Abruf von /shelly."""
    aioclient_mock.get(f"{BASE}/shelly", **kwargs)
    result = await _start_user(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": error}


async def test_user_flow_settings_errors_and_recovery(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """401 → invalid_auth, 500 → cannot_connect, danach Erfolg im selben Flow."""
    mock_shelly(aioclient_mock, settings_status=401)
    result = await _start_user(hass)
    assert result["errors"] == {"base": "invalid_auth"}
    # Eingaben bleiben erhalten (außer dem Kennwort, das im Formular gezeigt wird).
    assert result["step_id"] == "user"

    aioclient_mock.clear_requests()
    mock_shelly(aioclient_mock, settings_status=500)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "cannot_connect"}

    aioclient_mock.clear_requests()
    mock_shelly(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["step_id"] == "camera"


async def test_user_flow_unknown_error(hass: HomeAssistant, aioclient_mock, caplog) -> None:
    """Unerwartete Ausnahme → unknown und Protokolleintrag."""
    aioclient_mock.get(f"{BASE}/shelly", json=SHELLY_JSON)
    with patch(
        "custom_components.homekit_tuerklingel.config_flow.ShellyGen1Client.async_get_info",
        side_effect=RuntimeError("kaputt"),
    ):
        result = await _start_user(hass)
    assert result["errors"] == {"base": "unknown"}
    assert "Unerwarteter Fehler" in caplog.text


async def test_already_configured(
    hass: HomeAssistant, aioclient_mock, mock_entry: MockConfigEntry
) -> None:
    """Gleiche MAC → Abbruch; geänderte IP wird im bestehenden Entry übernommen."""
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_entry, data={**mock_entry.data, CONF_SHELLY_HOST: "192.168.1.99"}
    )
    mock_shelly(aioclient_mock)
    result = await _start_user(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_entry.data[CONF_SHELLY_HOST] == SHELLY_HOST


# ------------------------------------------------------------------ Reauth
async def test_reauth(hass: HomeAssistant, aioclient_mock, mock_entry: MockConfigEntry) -> None:
    """Neue Zugangsdaten: erst falsch, dann richtig."""
    mock_entry.add_to_hass(hass)
    result = await mock_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["host"] == SHELLY_HOST

    mock_shelly(aioclient_mock, settings_status=401)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SHELLY_USERNAME: "admin", CONF_SHELLY_PASSWORD: "falsch"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    aioclient_mock.clear_requests()
    mock_shelly(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SHELLY_USERNAME: "admin", CONF_SHELLY_PASSWORD: "neu"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_entry.data[CONF_SHELLY_PASSWORD] == "neu"
    assert mock_entry.data[CONF_SHELLY_USERNAME] == "admin"
    assert mock_entry.data[CONF_WEBHOOK_ID] == WEBHOOK_ID


async def test_reauth_wrong_device(
    hass: HomeAssistant, aioclient_mock, mock_entry: MockConfigEntry
) -> None:
    """Antwortet ein anderer Shelly, wird abgebrochen."""
    mock_entry.add_to_hass(hass)
    result = await mock_entry.start_reauth_flow(hass)
    mock_shelly(aioclient_mock, shelly={**SHELLY_JSON, "mac": "112233445566"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"
    assert mock_entry.data[CONF_SHELLY_PASSWORD] == "geheim"


# ------------------------------------------------------------ Reconfigure
async def test_reconfigure(
    hass: HomeAssistant, aioclient_mock, mock_entry: MockConfigEntry
) -> None:
    """Neue IP und Kamera, leeres Kennwortfeld behält das bisherige Kennwort."""
    mock_entry.add_to_hass(hass)
    result = await mock_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    new_host = "192.168.1.51"
    aioclient_mock.get(f"http://{new_host}/shelly", exc=aiohttp.ClientConnectionError())
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SHELLY_HOST: new_host,
            CONF_SHELLY_USERNAME: "admin",
            CONF_CAMERA_ENTITY: "camera.neu",
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    aioclient_mock.clear_requests()
    mock_shelly(aioclient_mock, host=new_host)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SHELLY_HOST: new_host,
            CONF_SHELLY_USERNAME: "admin",
            CONF_CAMERA_ENTITY: "camera.neu",
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_entry.data[CONF_SHELLY_HOST] == new_host
    assert mock_entry.data[CONF_SHELLY_PASSWORD] == "geheim"
    assert mock_entry.data[CONF_CAMERA_ENTITY] == "camera.neu"
    assert mock_entry.data[CONF_WEBHOOK_ID] == WEBHOOK_ID


async def test_reconfigure_remove_auth(
    hass: HomeAssistant, aioclient_mock, mock_entry: MockConfigEntry
) -> None:
    """Benutzer leer → Zugangsdaten werden entfernt."""
    mock_entry.add_to_hass(hass)
    result = await mock_entry.start_reconfigure_flow(hass)
    mock_shelly(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SHELLY_HOST: SHELLY_HOST, CONF_CAMERA_ENTITY: CAMERA}
    )
    assert result["reason"] == "reconfigure_successful"
    assert mock_entry.data[CONF_SHELLY_USERNAME] is None
    assert mock_entry.data[CONF_SHELLY_PASSWORD] is None


async def test_reconfigure_mismatch(
    hass: HomeAssistant, aioclient_mock, mock_entry: MockConfigEntry
) -> None:
    """Anderer Shelly unter der neuen Adresse → unique_id_mismatch."""
    mock_entry.add_to_hass(hass)
    result = await mock_entry.start_reconfigure_flow(hass)
    mock_shelly(aioclient_mock, host="192.168.1.60", shelly={**SHELLY_JSON, "mac": "112233445566"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SHELLY_HOST: "192.168.1.60",
            CONF_SHELLY_USERNAME: "admin",
            CONF_SHELLY_PASSWORD: "geheim",
            CONF_CAMERA_ENTITY: CAMERA,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"
    assert mock_entry.data[CONF_SHELLY_HOST] == SHELLY_HOST


# ---------------------------------------------------------------- Options
OPTIONS_INPUT = {
    CONF_RESTRICT_IP: True,
    CONF_ALLOWED_IP: " 192.168.1.77 ",
    CONF_AUTO_OFF: 12.0,
    CONF_CONNECTIVITY: False,
    CONF_NOTIFY_ENABLED: True,
    CONF_NOTIFY_SERVICES: ["mobile_app_iphone", "notify.mobile_app_ipad", " "],
    CONF_NOTIFY_TITLE: "Ding Dong",
    CONF_NOTIFY_MESSAGE: "Besuch an {name}",
}


async def test_options_flow(hass: HomeAssistant, mock_entry: MockConfigEntry) -> None:
    """Optionen: Dienste-Liste, Platzhalter, ungültige IP, Übernahme der Werte."""

    async def _noop(call: ServiceCall) -> None:
        return

    hass.services.async_register("notify", "mobile_app_iphone", _noop)
    hass.services.async_register("notify", "send_message", _noop)
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_entry, options={CONF_NOTIFY_SERVICES: ["alte_gruppe"]}
    )

    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["description_placeholders"] == {
        "webhook_url": f"{INTERNAL_URL}/api/webhook/{WEBHOOK_ID}",
        "name": "{name}",
    }
    schema = result["data_schema"].schema
    services_key = next(k for k in schema if k == CONF_NOTIFY_SERVICES)
    options = schema[services_key].config["options"]
    assert options == ["alte_gruppe", "mobile_app_iphone"]
    # Vorbelegung aus den Standardwerten
    auto_off_key = next(k for k in schema if k == CONF_AUTO_OFF)
    assert auto_off_key.description == {"suggested_value": DEFAULT_AUTO_OFF}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**OPTIONS_INPUT, CONF_ALLOWED_IP: "kein host!"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_ALLOWED_IP: "invalid_ip"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], OPTIONS_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_entry.options == {
        CONF_RESTRICT_IP: True,
        CONF_ALLOWED_IP: "192.168.1.77",
        CONF_AUTO_OFF: 12,
        CONF_CONNECTIVITY: False,
        CONF_NOTIFY_ENABLED: True,
        CONF_NOTIFY_SERVICES: ["mobile_app_iphone", "mobile_app_ipad"],
        CONF_NOTIFY_TITLE: "Ding Dong",
        CONF_NOTIFY_MESSAGE: "Besuch an {name}",
    }
    assert isinstance(mock_entry.options[CONF_AUTO_OFF], int)


async def test_options_flow_minimal(hass: HomeAssistant, mock_entry: MockConfigEntry) -> None:
    """Leere optionale Felder: Hostname erlaubt, Texte fallen auf Standard zurück."""
    mock_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_RESTRICT_IP: False,
            CONF_ALLOWED_IP: "shelly-klingel.local",
            CONF_AUTO_OFF: 300,
            CONF_CONNECTIVITY: True,
            CONF_NOTIFY_ENABLED: False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_entry.options[CONF_ALLOWED_IP] == "shelly-klingel.local"
    assert mock_entry.options[CONF_NOTIFY_SERVICES] == []
    assert mock_entry.options[CONF_NOTIFY_TITLE] == DEFAULT_NOTIFY_TITLE
    assert mock_entry.options[CONF_NOTIFY_MESSAGE] == DEFAULT_NOTIFY_MESSAGE


async def test_options_auto_off_range(hass: HomeAssistant, mock_entry: MockConfigEntry) -> None:
    """auto_off außerhalb 1–300 wird vom Selector abgelehnt."""
    from homeassistant.data_entry_flow import InvalidData

    mock_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_RESTRICT_IP: True,
                CONF_AUTO_OFF: 0,
                CONF_CONNECTIVITY: True,
                CONF_NOTIFY_ENABLED: False,
            },
        )
