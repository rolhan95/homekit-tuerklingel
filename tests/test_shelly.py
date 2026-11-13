"""Tests für den Shelly-Gen1-Client."""

from __future__ import annotations

import base64

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.homekit_tuerklingel.shelly import (
    ShellyAuthError,
    ShellyConnectionError,
    ShellyGen1Client,
    ShellyInfo,
    format_timer,
)

from .conftest import SHELLY_HOST, SHELLY_MAC

BASE = f"http://{SHELLY_HOST}"


def _client(hass: HomeAssistant, user: str | None = "admin", pw: str | None = "geheim"):
    return ShellyGen1Client(async_get_clientsession(hass), f" {SHELLY_HOST} ", user, pw)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(1, "1"), (1.0, "1"), (0.5, "0.5"), (0.25, "0.2"), (2.06, "2.1"), (10, "10"), ("3", "3")],
)
def test_format_timer(seconds, expected) -> None:
    """Impulsdauer mit höchstens einer Nachkommastelle, ganze Zahlen ohne Punkt."""
    assert format_timer(seconds) == expected


def test_info_detached() -> None:
    """detached aus btn_type ableiten."""
    assert ShellyInfo("M", "SHSW-1", None, False).detached is None
    assert ShellyInfo("M", "SHSW-1", None, False, "detached").detached is True
    assert ShellyInfo("M", "SHSW-1", None, False, "momentary").detached is False


async def test_base_url_and_auth_header(hass: HomeAssistant, aioclient_mock) -> None:
    """Host wird getrimmt; Basic-Auth nur bei Benutzername, /shelly ohne Auth."""
    aioclient_mock.get(f"{BASE}/shelly", json={"mac": "aa"})
    aioclient_mock.get(f"{BASE}/relay/0", json={"ison": True})
    client = _client(hass)
    assert client.host == SHELLY_HOST
    assert client.base_url == BASE
    await client.async_ping()
    await client.async_pulse(1)
    token = base64.b64encode(b"admin:geheim").decode()
    assert aioclient_mock.mock_calls[0][3] is None
    assert aioclient_mock.mock_calls[1][3] == {"Authorization": f"Basic {token}"}

    no_auth = _client(hass, None, None)
    await no_auth.async_pulse(1)
    assert aioclient_mock.mock_calls[2][3] == {}

    user_only = _client(hass, "admin", None)
    await user_only.async_pulse(1)
    token = base64.b64encode(b"admin:").decode()
    assert aioclient_mock.mock_calls[3][3] == {"Authorization": f"Basic {token}"}


async def test_get_info_with_settings(hass: HomeAssistant, aioclient_mock) -> None:
    """Geräteinfo inkl. btn_type aus /settings."""
    aioclient_mock.get(
        f"{BASE}/shelly",
        json={"mac": SHELLY_MAC.lower(), "type": "SHSW-1", "fw": "1.14.0", "auth": True},
    )
    aioclient_mock.get(f"{BASE}/settings", json={"relays": [{"btn_type": "detached"}]})
    info = await _client(hass).async_get_info()
    assert info.mac == SHELLY_MAC
    assert info.model == "SHSW-1"
    assert info.firmware == "1.14.0"
    assert info.auth_required is True
    assert info.btn_type == "detached"
    assert info.detached is True


async def test_get_info_without_settings(hass: HomeAssistant, aioclient_mock) -> None:
    """Ohne with_settings kein Aufruf von /settings; Standardwerte."""
    aioclient_mock.get(f"{BASE}/shelly", json={"mac": SHELLY_MAC})
    info = await _client(hass).async_get_info(with_settings=False)
    assert info.model == "unbekannt"
    assert info.firmware is None
    assert info.auth_required is False
    assert info.btn_type is None
    assert aioclient_mock.call_count == 1


@pytest.mark.parametrize(
    "settings",
    [{}, {"relays": []}, {"relays": ["kaputt"]}, {"relays": [{}]}],
)
async def test_get_info_settings_without_btn_type(
    hass: HomeAssistant, aioclient_mock, settings
) -> None:
    """Fehlende/ungewöhnliche Relais-Angaben → btn_type unbekannt."""
    aioclient_mock.get(f"{BASE}/shelly", json={"mac": SHELLY_MAC})
    aioclient_mock.get(f"{BASE}/settings", json=settings)
    info = await _client(hass).async_get_info()
    assert info.btn_type is None
    assert info.detached is None


async def test_get_info_no_mac(hass: HomeAssistant, aioclient_mock) -> None:
    """Antwort ohne MAC → kein Shelly Gen1."""
    aioclient_mock.get(f"{BASE}/shelly", json={"type": "SHSW-1"})
    with pytest.raises(ShellyConnectionError, match="keine MAC"):
        await _client(hass).async_get_info()


async def test_get_info_settings_401(hass: HomeAssistant, aioclient_mock) -> None:
    """/settings mit falschen Zugangsdaten → ShellyAuthError."""
    aioclient_mock.get(f"{BASE}/shelly", json={"mac": SHELLY_MAC})
    aioclient_mock.get(f"{BASE}/settings", status=401)
    with pytest.raises(ShellyAuthError):
        await _client(hass).async_get_info()


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"exc": TimeoutError()}, "TimeoutError"),
        ({"exc": aiohttp.ClientConnectionError("weg")}, "weg"),
        ({"status": 500}, "HTTP 500"),
        ({"text": "kein json"}, "/shelly"),
        ({"json": ["liste"]}, "unerwartete Antwort"),
    ],
)
async def test_errors(hass: HomeAssistant, aioclient_mock, kwargs, match) -> None:
    """Timeout, Verbindungsfehler, HTTP-Fehler und Nicht-JSON → ShellyConnectionError."""
    aioclient_mock.get(f"{BASE}/shelly", **kwargs)
    with pytest.raises(ShellyConnectionError, match=match):
        await _client(hass).async_get_info()


async def test_ping(hass: HomeAssistant, aioclient_mock) -> None:
    """async_ping liefert True/False statt Ausnahmen."""
    aioclient_mock.get(f"{BASE}/shelly", json={"mac": SHELLY_MAC})
    assert await _client(hass).async_ping() is True
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/shelly", exc=TimeoutError())
    assert await _client(hass).async_ping() is False
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/shelly", status=401)
    assert await _client(hass).async_ping() is False


async def test_pulse(hass: HomeAssistant, aioclient_mock) -> None:
    """Gong-Impuls: GET /relay/0?turn=on&timer=<s>; 401 → ShellyAuthError."""
    aioclient_mock.get(f"{BASE}/relay/0", json={"ison": True})
    await _client(hass).async_pulse(0.5)
    url = aioclient_mock.mock_calls[0][1]
    assert url.path == "/relay/0"
    assert dict(url.query) == {"turn": "on", "timer": "0.5"}

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/relay/0", status=401)
    with pytest.raises(ShellyAuthError):
        await _client(hass).async_pulse(1)
