"""Tests für den Hub: Webhook, IP-Filter, Entprellung, Gong, Snapshot, Push."""

from __future__ import annotations

import base64
import socket
from datetime import timedelta
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.components.camera import Image
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.homekit_tuerklingel.const import (
    CONF_ALLOWED_IP,
    CONF_AUTO_OFF,
    CONF_CONNECTIVITY,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_MESSAGE,
    CONF_NOTIFY_SERVICES,
    CONF_NOTIFY_TITLE,
    CONF_RESTRICT_IP,
    CONNECTIVITY_INTERVAL,
    DOMAIN,
)
from custom_components.homekit_tuerklingel.hub import TuerklingelHub, _normalize_ip

from .conftest import CAMERA, SHELLY_HOST, SHELLY_MAC, WEBHOOK_ID

BASE = f"http://{SHELLY_HOST}"
WEBHOOK_PATH = f"/api/webhook/{WEBHOOK_ID}"
HUB_TIME = "custom_components.homekit_tuerklingel.hub.time"
GET_IMAGE = "custom_components.homekit_tuerklingel.hub.camera.async_get_image"


def _mock_shelly(aioclient_mock, *, relay: dict | None = None) -> None:
    """Shelly-Endpunkte für Setup (Ping, Issue-Prüfung) und Gong registrieren."""
    aioclient_mock.get(f"{BASE}/shelly", json={"mac": SHELLY_MAC, "type": "SHSW-1"})
    aioclient_mock.get(f"{BASE}/settings", json={"relays": [{"btn_type": "detached"}]})
    aioclient_mock.get(f"{BASE}/relay/0", **(relay or {"json": {"ison": True}}))


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock, options: dict | None = None,
    relay: dict | None = None,
) -> TuerklingelHub:
    """Entry mit Optionen einrichten und den Hub zurückgeben."""
    _mock_shelly(aioclient_mock, relay=relay)
    entry.add_to_hass(hass)
    if options is not None:
        hass.config_entries.async_update_entry(entry, options=options)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    hub: TuerklingelHub = entry.runtime_data
    # Laufzeitwerte festlegen (Entitäten könnten wiederhergestellte Werte setzen)
    hub.gong_enabled = False
    hub.cooldown = 3.0
    hub.gong_duration = 1.0
    return hub


def _relay_calls(aioclient_mock) -> list:
    return [c for c in aioclient_mock.mock_calls if c[1].path == "/relay/0"]


# --------------------------------------------------------------------- Webhook
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_webhook_get_and_post(
    hass: HomeAssistant, mock_entry, aioclient_mock, hass_client_no_auth, method
) -> None:
    """GET und POST lösen das Klingeln aus (Quelle in Tests: 127.0.0.1)."""
    hub = await _setup(
        hass, mock_entry, aioclient_mock, {CONF_ALLOWED_IP: "127.0.0.1"}
    )
    rings: list = []
    listener = rings.append
    unsub = hub.async_add_ring_listener(listener)
    client = await hass_client_no_auth()
    resp = await client.request(method, WEBHOOK_PATH)
    assert resp.status == HTTPStatus.OK
    assert await resp.text() == "ok"
    await hass.async_block_till_done()
    assert len(rings) == 1
    assert hub.last_ring is not None
    assert hub.stats["webhook_calls"] == 1
    assert hub.stats["rings"] == 1
    assert hub.stats["last_call"]["method"] == method
    assert hub.stats["last_call"]["remote"] == "127.0.0.1"
    assert hub.stats["last_call"]["result"] == "ring"
    unsub()
    assert listener not in hub._ring_listeners


async def test_webhook_other_method_rejected(
    hass: HomeAssistant, mock_entry, aioclient_mock, hass_client_no_auth
) -> None:
    """PUT ist nicht erlaubt (405, kein Klingeln)."""
    hub = await _setup(hass, mock_entry, aioclient_mock, {CONF_RESTRICT_IP: False})
    client = await hass_client_no_auth()
    resp = await client.put(WEBHOOK_PATH)
    assert resp.status == HTTPStatus.METHOD_NOT_ALLOWED
    assert hub.stats["rings"] == 0


async def test_webhook_ip_rejected(
    hass: HomeAssistant, mock_entry, aioclient_mock, hass_client_no_auth
) -> None:
    """Standard: nur die Shelly-IP darf klingeln → 127.0.0.1 erhält 403."""
    hub = await _setup(hass, mock_entry, aioclient_mock)
    assert hub.restrict_ip is True
    assert hub.allowed_host == SHELLY_HOST
    client = await hass_client_no_auth()
    resp = await client.get(WEBHOOK_PATH)
    assert resp.status == HTTPStatus.FORBIDDEN
    assert hub.stats["rejected_ip"] == 1
    assert hub.stats["rings"] == 0
    assert hub.stats["last_call"]["result"] == "ip_rejected"


async def test_webhook_restrict_ip_off(
    hass: HomeAssistant, mock_entry, aioclient_mock, hass_client_no_auth
) -> None:
    """IP-Filter ausgeschaltet → jede (lokale) Quelle darf klingeln."""
    hub = await _setup(hass, mock_entry, aioclient_mock, {CONF_RESTRICT_IP: False})
    client = await hass_client_no_auth()
    resp = await client.post(WEBHOOK_PATH)
    assert resp.status == HTTPStatus.OK
    assert hub.stats["rings"] == 1
    assert hub.ip_allowed("10.9.9.9") is True
    assert hub.ip_allowed(None) is True


async def test_webhook_local_only(
    hass: HomeAssistant, mock_entry, aioclient_mock, hass_client_no_auth
) -> None:
    """Nicht-lokale Quelle wird vom HA-Webhook verworfen (200, kein Aufruf des Hubs)."""
    hub = await _setup(hass, mock_entry, aioclient_mock, {CONF_RESTRICT_IP: False})
    client = await hass_client_no_auth()
    with patch(
        "homeassistant.components.webhook.network_util.is_local", return_value=False
    ):
        resp = await client.get(WEBHOOK_PATH)
    assert resp.status == HTTPStatus.OK
    assert hub.stats["webhook_calls"] == 0
    assert hub.stats["rings"] == 0


async def test_webhook_unregistered_on_unload(
    hass: HomeAssistant, mock_entry, aioclient_mock
) -> None:
    """Nach dem Entladen ist der Webhook weg und der Poll-Timer beendet."""
    hub = await _setup(hass, mock_entry, aioclient_mock)
    assert hub._unsub_poll is not None
    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    assert WEBHOOK_ID not in hass.data["webhook"]
    assert hub._unsub_poll is None
    hub.async_unload()  # zweiter Aufruf ist unschädlich


# ------------------------------------------------------------------- IP-Filter
def test_normalize_ip() -> None:
    """IPv4, IPv6, IPv4-gemappte IPv6 und Unsinn."""
    assert str(_normalize_ip(" 192.168.1.50 ")) == "192.168.1.50"
    assert str(_normalize_ip("::ffff:192.168.1.50")) == "192.168.1.50"
    assert str(_normalize_ip("fe80::1")) == "fe80::1"
    assert _normalize_ip("") is None
    assert _normalize_ip(None) is None
    assert _normalize_ip("kein-host") is None


async def test_ip_allowed_default(hass: HomeAssistant, mock_entry, aioclient_mock) -> None:
    """Shelly-IP erlaubt (auch als IPv4-gemappte IPv6), andere abgelehnt."""
    hub = await _setup(hass, mock_entry, aioclient_mock)
    assert hub.ip_allowed(SHELLY_HOST) is True
    assert hub.ip_allowed(f"::ffff:{SHELLY_HOST}") is True
    assert hub.ip_allowed("192.168.1.51") is False
    assert hub.ip_allowed(None) is False
    assert hub.ip_allowed("murks") is False


async def test_ip_allowed_override(hass: HomeAssistant, mock_entry, aioclient_mock) -> None:
    """Abweichende erlaubte IP ersetzt die Shelly-IP."""
    hub = await _setup(hass, mock_entry, aioclient_mock, {CONF_ALLOWED_IP: " 192.168.1.99 "})
    assert hub.allowed_host == "192.168.1.99"
    assert hub.ip_allowed("192.168.1.99") is True
    assert hub.ip_allowed(SHELLY_HOST) is False


async def test_ip_allowed_hostname(hass: HomeAssistant, mock_entry, aioclient_mock) -> None:
    """Hostname wird einmalig aufgelöst (alle Adressen erlaubt)."""
    infos = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.77", 0)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:192.168.1.78", 0, 0, 0)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fe80::1%eth0", 0, 0, 0)),
    ]
    with patch.object(hass.loop, "getaddrinfo", AsyncMock(return_value=infos)):
        hub = await _setup(hass, mock_entry, aioclient_mock, {CONF_ALLOWED_IP: "klingel.lan"})
    assert hub.ip_allowed("192.168.1.77") is True
    assert hub.ip_allowed("192.168.1.78") is True
    assert hub.ip_allowed(SHELLY_HOST) is False


async def test_ip_allowed_hostname_unresolvable(
    hass: HomeAssistant, mock_entry, aioclient_mock, caplog
) -> None:
    """Nicht auflösbarer Hostname → Filter lässt nichts durch, Warnung im Log."""
    with patch.object(hass.loop, "getaddrinfo", AsyncMock(side_effect=OSError("nx"))):
        hub = await _setup(hass, mock_entry, aioclient_mock, {CONF_ALLOWED_IP: "weg.lan"})
    assert hub.ip_allowed("192.168.1.77") is False
    assert "nicht auflösbar" in caplog.text


# ----------------------------------------------------------------- Entprellung
async def test_debounce(hass: HomeAssistant, mock_entry, aioclient_mock) -> None:
    """Zweites Klingeln innerhalb der Entprellzeit verworfen, danach wieder angenommen."""
    hub = await _setup(hass, mock_entry, aioclient_mock)
    rings: list = []
    hub.async_add_ring_listener(rings.append)
    with patch(HUB_TIME) as mock_time:
        mock_time.monotonic.return_value = 1000.0
        assert hub.async_ring() is True
        mock_time.monotonic.return_value = 1002.9
        assert hub.async_ring() is False
        assert hub.stats["debounced"] == 1
        mock_time.monotonic.return_value = 1003.1
        assert hub.async_ring() is True
        hub.cooldown = 0.0
        assert hub.async_ring() is True
    await hass.async_block_till_done()
    assert len(rings) == 3
    assert hub.stats["rings"] == 3


async def test_debounce_via_webhook(
    hass: HomeAssistant, mock_entry, aioclient_mock, hass_client_no_auth
) -> None:
    """Webhook antwortet bei Entprellung mit 'debounced'."""
    hub = await _setup(hass, mock_entry, aioclient_mock, {CONF_RESTRICT_IP: False})
    client = await hass_client_no_auth()
    assert await (await client.get(WEBHOOK_PATH)).text() == "ok"
    resp = await client.get(WEBHOOK_PATH)
    assert resp.status == HTTPStatus.OK
    assert await resp.text() == "debounced"
    assert hub.stats["last_call"]["result"] == "debounced"
    await hass.async_block_till_done()


# ------------------------------------------------------------------------ Gong
async def test_gong_enabled(hass: HomeAssistant, mock_entry, aioclient_mock) -> None:
    """Gong an → GET /relay/0?turn=on&timer=1 mit Authorization-Header."""
    hub = await _setup(hass, mock_entry, aioclient_mock)
    hub.gong_enabled = True
    aioclient_mock.mock_calls.clear()
    assert hub.async_ring() is True
    await hass.async_block_till_done()
    calls = _relay_calls(aioclient_mock)
    assert len(calls) == 1
    _method, url, _data, headers = calls[0]
    assert str(url) == f"{BASE}/relay/0?turn=on&timer=1"
    token = base64.b64encode(b"admin:geheim").decode()
    assert headers == {"Authorization": f"Basic {token}"}
    assert hub.stats["gong_pulses"] == 1
    assert hub.stats["gong_errors"] == 0


async def test_gong_duration_fraction(hass: HomeAssistant, mock_entry, aioclient_mock) -> None:
    """Impulsdauer wird mit einer Nachkommastelle übertragen."""
    hub = await _setup(hass, mock_entry, aioclient_mock)
    hub.gong_enabled = True
    hub.gong_duration = 0.5
    aioclient_mock.mock_calls.clear()
    await hub.async_gong()
    assert dict(_relay_calls(aioclient_mock)[0][1].query)["timer"] == "0.5"


async def test_gong_disabled(hass: HomeAssistant, mock_entry, aioclient_mock) -> None:
    """Gong stumm → kein Relais-Aufruf."""
    hub = await _setup(hass, mock_entry, aioclient_mock)
    hub.gong_enabled = False
    aioclient_mock.mock_calls.clear()
    hub.async_ring()
    await hass.async_block_till_done()
    assert _relay_calls(aioclient_mock) == []
    assert hub.stats["gong_pulses"] == 0


async def test_gong_auth_error_starts_reauth(
    hass: HomeAssistant, mock_entry, aioclient_mock
) -> None:
    """401 vom Relais → gong_errors und Reauth-Flow gestartet."""
    hub = await _setup(hass, mock_entry, aioclient_mock, relay={"status": 401})
    hub.gong_enabled = True
    with patch.object(mock_entry, "async_start_reauth") as start_reauth:
        await hub.async_gong()
    start_reauth.assert_called_once_with(hass)
    assert hub.stats["gong_errors"] == 1
    assert hub.stats["gong_pulses"] == 0


async def test_gong_auth_error_reauth_flow(
    hass: HomeAssistant, mock_entry, aioclient_mock
) -> None:
    """Der echte Reauth-Flow der Integration erscheint in der Flow-Liste."""
    hub = await _setup(hass, mock_entry, aioclient_mock, relay={"status": 401})
    hub.gong_enabled = True
    await hub.async_gong()
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_gong_connection_error(
    hass: HomeAssistant, mock_entry, aioclient_mock
) -> None:
    """Verbindungsfehler → nur gong_errors, kein Reauth."""
    hub = await _setup(
        hass, mock_entry, aioclient_mock, relay={"exc": aiohttp.ClientConnectionError()}
    )
    hub.gong_enabled = True
    with patch.object(mock_entry, "async_start_reauth") as start_reauth:
        await hub.async_gong()
    start_reauth.assert_not_called()
    assert hub.stats["gong_errors"] == 1


# -------------------------------------------------------------- Snapshot/Push
async def test_snapshot(hass: HomeAssistant, mock_entry, aioclient_mock) -> None:
    """Snapshot der Quellkamera speichern und Listener benachrichtigen."""
    hub = await _setup(hass, mock_entry, aioclient_mock)
    updates: list = []
    def snap_listener() -> None:
        updates.append(1)

    unsub = hub.async_add_snapshot_listener(snap_listener)
    with patch(GET_IMAGE, AsyncMock(return_value=Image("image/jpeg", b"jpegdata"))) as get:
        hub.async_ring()
        await hass.async_block_till_done()
    assert get.call_args.args[1] == CAMERA
    assert hub.snapshot == b"jpegdata"
    assert hub.snapshot_time is not None
    assert updates == [1]
    unsub()
    assert snap_listener not in hub._snapshot_listeners


async def test_snapshot_error(hass: HomeAssistant, mock_entry, aioclient_mock) -> None:
    """Kamerafehler → snapshot_errors, alter Snapshot bleibt."""
    hub = await _setup(hass, mock_entry, aioclient_mock)
    hub.snapshot = b"alt"
    with patch(GET_IMAGE, AsyncMock(side_effect=HomeAssistantError("aus"))):
        await hub.async_take_snapshot()
    assert hub.snapshot == b"alt"
    assert hub.stats["snapshot_errors"] == 1


NOTIFY_OPTS = {
    CONF_NOTIFY_ENABLED: True,
    CONF_NOTIFY_SERVICES: ["mobile_app_iphone", "notify.mobile_app_ipad"],
    CONF_NOTIFY_TITLE: "Ding Dong",
    CONF_NOTIFY_MESSAGE: "Besuch an der {name}",
}


async def test_notify(hass: HomeAssistant, mock_entry, aioclient_mock) -> None:
    """Push mit Titel, Text ({name} ersetzt) und Snapshot-Anhang an alle Dienste."""
    calls_phone = async_mock_service(hass, "notify", "mobile_app_iphone")
    calls_pad = async_mock_service(hass, "notify", "mobile_app_ipad")
    hub = await _setup(hass, mock_entry, aioclient_mock, NOTIFY_OPTS)
    hub.image_entity_id = "image.haustur_letztes_klingeln"
    with patch(GET_IMAGE, AsyncMock(return_value=Image("image/jpeg", b"x"))):
        hub.async_ring()
        await hass.async_block_till_done()
    assert len(calls_phone) == 1
    assert len(calls_pad) == 1
    data = calls_phone[0].data
    assert data["title"] == "Ding Dong"
    assert data["message"] == "Besuch an der Haustür"
    assert data["data"]["image"] == "/api/image_proxy/image.haustur_letztes_klingeln"
    assert data["data"]["tag"] == f"{DOMAIN}_{mock_entry.entry_id}"
    assert data["data"]["push"] == {"interruption-level": "time-sensitive"}


async def test_notify_defaults_without_image(
    hass: HomeAssistant, mock_entry, aioclient_mock
) -> None:
    """Standardtexte; ohne Snapshot kein Bildanhang."""
    calls = async_mock_service(hass, "notify", "mobile_app_iphone")
    hub = await _setup(
        hass,
        mock_entry,
        aioclient_mock,
        {
            CONF_NOTIFY_ENABLED: True,
            CONF_NOTIFY_SERVICES: ["mobile_app_iphone"],
            CONF_NOTIFY_TITLE: "",
        },
    )
    hub.image_entity_id = "image.x"
    await hub.async_notify()
    assert calls[0].data["title"] == "Es klingelt"
    assert calls[0].data["message"] == "Jemand steht an der Tür (Haustür)."
    assert "image" not in calls[0].data["data"]


async def test_notify_disabled(hass: HomeAssistant, mock_entry, aioclient_mock) -> None:
    """notify_enabled aus (oder keine Dienste) → keine Push-Nachricht."""
    calls = async_mock_service(hass, "notify", "mobile_app_iphone")
    hub = await _setup(
        hass,
        mock_entry,
        aioclient_mock,
        {**NOTIFY_OPTS, CONF_NOTIFY_ENABLED: False},
    )
    await hub.async_notify()
    assert calls == []
    hass.config_entries.async_update_entry(
        mock_entry, options={CONF_NOTIFY_ENABLED: True, CONF_NOTIFY_SERVICES: []}
    )
    await hass.async_block_till_done()
    await mock_entry.runtime_data.async_notify()
    assert calls == []


async def test_notify_error(hass: HomeAssistant, mock_entry, aioclient_mock) -> None:
    """Unbekannter Dienst → notify_errors, andere Dienste laufen weiter."""
    calls = async_mock_service(hass, "notify", "mobile_app_ipad")
    hub = await _setup(hass, mock_entry, aioclient_mock, NOTIFY_OPTS)
    await hub.async_notify()
    assert hub.stats["notify_errors"] == 1
    assert len(calls) == 1


# -------------------------------------------------------------- Erreichbarkeit
async def test_availability(hass: HomeAssistant, mock_entry, aioclient_mock, caplog) -> None:
    """Ping beim Start, Listener nur bei Änderung, Poll im Intervall."""
    hub = await _setup(hass, mock_entry, aioclient_mock)
    assert hub.connectivity_enabled is True
    assert hub.shelly_available is True
    changes: list = []
    def avail_listener() -> None:
        changes.append(hub.shelly_available)

    unsub = hub.async_add_availability_listener(avail_listener)

    await hub.async_update_availability()
    assert changes == []  # unverändert → kein Listener-Aufruf

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/shelly", exc=TimeoutError())
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=CONNECTIVITY_INTERVAL + 1))
    await hass.async_block_till_done()
    assert hub.shelly_available is False
    assert changes == [False]
    assert "nicht erreichbar" in caplog.text

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/shelly", json={"mac": SHELLY_MAC})
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=2 * CONNECTIVITY_INTERVAL + 2)
    )
    await hass.async_block_till_done()
    assert changes == [False, True]
    assert "wieder erreichbar" in caplog.text
    unsub()
    assert avail_listener not in hub._availability_listeners


async def test_availability_disabled(hass: HomeAssistant, mock_entry, aioclient_mock) -> None:
    """Option connectivity aus → kein Ping, kein Timer."""
    hub = await _setup(hass, mock_entry, aioclient_mock, {CONF_CONNECTIVITY: False})
    assert hub.connectivity_enabled is False
    assert hub.shelly_available is None
    assert hub._unsub_poll is None


async def test_options_properties(hass: HomeAssistant, mock_entry, aioclient_mock) -> None:
    """Name und auto_off aus Titel bzw. Optionen."""
    hub = await _setup(hass, mock_entry, aioclient_mock, {CONF_AUTO_OFF: 12})
    assert hub.name == "Haustür"
    assert hub.auto_off == 12
    assert hub.webhook_id == WEBHOOK_ID
    assert hub.camera_entity_id == CAMERA


async def test_hub_without_credentials(hass: HomeAssistant) -> None:
    """Leere Zugangsdaten → kein Authorization-Header."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Hinten",
        data={
            "shelly_host": SHELLY_HOST,
            "shelly_username": "",
            "shelly_password": "",
            "camera_entity": CAMERA,
            "webhook_id": "abc",
        },
    )
    entry.add_to_hass(hass)
    hub = TuerklingelHub(hass, entry)
    assert hub.client._headers == {}
    assert isinstance(hub.client, MagicMock) is False
