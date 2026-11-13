"""Tests für den Hub: Webhook, IP-Filter, Entitäts-Auslöser, Entprellung, Gong, Snapshot, Push."""

from __future__ import annotations

import asyncio
import socket
from http import HTTPStatus
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.camera import Image
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, ServiceCall, State
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.homekit_tuerklingel.const import (
    CONF_ALLOWED_SOURCES,
    CONF_AUTO_OFF,
    CONF_GONG_ENTITY,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_MESSAGE,
    CONF_NOTIFY_SERVICES,
    CONF_NOTIFY_TITLE,
    CONF_RESTRICT_IP,
    CONF_TRIGGER_ENTITIES,
    CONF_WEBHOOK_ENABLED,
    DOMAIN,
    TRIGGER_DOMAINS,
)
from custom_components.homekit_tuerklingel.hub import (
    TuerklingelHub,
    is_ring_transition,
    normalize_ip,
)

from .conftest import CAMERA, GONG, SHELLY_HOST, TRIGGER, WEBHOOK_ID

WEBHOOK_PATH = f"/api/webhook/{WEBHOOK_ID}"
HUB_TIME = "custom_components.homekit_tuerklingel.hub.time"
GET_IMAGE = "custom_components.homekit_tuerklingel.hub.camera.async_get_image"
TS1 = "2026-11-13T10:00:00.000+00:00"
TS2 = "2026-11-13T10:00:05.000+00:00"


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, options: dict | None = None
) -> TuerklingelHub:
    """Entry (optional mit ersetzten Optionen) einrichten und den Hub zurückgeben."""
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
    hub.gong_duration = 0
    return hub


def _mock_switch(hass: HomeAssistant) -> tuple[list, list]:
    """switch.turn_on/turn_off ersetzen (erst nach dem Setup, sonst überschreibt
    die switch-Plattform der Integration die Attrappen)."""
    return (
        async_mock_service(hass, "switch", "turn_on"),
        async_mock_service(hass, "switch", "turn_off"),
    )


def _webhooks(hass: HomeAssistant) -> dict:
    return hass.data.get("webhook", {})


# --------------------------------------------------------------------- Webhook
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_webhook_get_and_post(
    hass: HomeAssistant, mock_entry, hass_client_no_auth, method
) -> None:
    """GET und POST lösen das Klingeln aus (Quelle in Tests: 127.0.0.1)."""
    hub = await _setup(
        hass, mock_entry, {CONF_RESTRICT_IP: True, CONF_ALLOWED_SOURCES: ["127.0.0.1"]}
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
    last = hub.stats["last_call"]
    assert last["source"] == "webhook"
    assert last["method"] == method
    assert last["remote"] == "127.0.0.1"
    assert last["result"] == "ring"
    unsub()
    assert listener not in hub._ring_listeners


async def test_webhook_other_method_rejected(
    hass: HomeAssistant, mock_entry, hass_client_no_auth
) -> None:
    """PUT ist nicht erlaubt (405, kein Klingeln)."""
    hub = await _setup(hass, mock_entry, {CONF_RESTRICT_IP: False})
    client = await hass_client_no_auth()
    resp = await client.put(WEBHOOK_PATH)
    assert resp.status == HTTPStatus.METHOD_NOT_ALLOWED
    assert hub.stats["rings"] == 0


async def test_webhook_ip_rejected(
    hass: HomeAssistant, mock_entry, hass_client_no_auth, caplog
) -> None:
    """Nur SHELLY_HOST erlaubt → 127.0.0.1 erhält 403."""
    hub = await _setup(hass, mock_entry)
    assert hub.restrict_ip is True
    assert hub.allowed_sources == [SHELLY_HOST]
    client = await hass_client_no_auth()
    resp = await client.get(WEBHOOK_PATH)
    assert resp.status == HTTPStatus.FORBIDDEN
    assert hub.stats["rejected_ip"] == 1
    assert hub.stats["rings"] == 0
    assert hub.stats["last_call"]["result"] == "ip_rejected"
    assert SHELLY_HOST in caplog.text


async def test_webhook_ip_rejected_no_sources(
    hass: HomeAssistant, mock_entry, hass_client_no_auth, caplog
) -> None:
    """Filter an, aber keine Quelle eingetragen → alles abgelehnt, Log zeigt '-'."""
    hub = await _setup(hass, mock_entry, {CONF_RESTRICT_IP: True, CONF_ALLOWED_SOURCES: [" ", ""]})
    assert hub.allowed_sources == []
    client = await hass_client_no_auth()
    assert (await client.get(WEBHOOK_PATH)).status == HTTPStatus.FORBIDDEN
    assert "(erlaubt: -)" in caplog.text


async def test_webhook_restrict_ip_off(
    hass: HomeAssistant, mock_entry, hass_client_no_auth
) -> None:
    """IP-Filter ausgeschaltet → jede (lokale) Quelle darf klingeln."""
    hub = await _setup(hass, mock_entry, {CONF_RESTRICT_IP: False})
    client = await hass_client_no_auth()
    resp = await client.post(WEBHOOK_PATH)
    assert resp.status == HTTPStatus.OK
    assert hub.stats["rings"] == 1
    assert hub.ip_allowed("10.9.9.9") is True
    assert hub.ip_allowed(None) is True


async def test_webhook_local_only(
    hass: HomeAssistant, mock_entry, hass_client_no_auth
) -> None:
    """Nicht-lokale Quelle wird vom HA-Webhook verworfen (kein Aufruf des Hubs)."""
    hub = await _setup(hass, mock_entry, {CONF_RESTRICT_IP: False})
    client = await hass_client_no_auth()
    with patch("homeassistant.components.webhook.network_util.is_local", return_value=False):
        resp = await client.get(WEBHOOK_PATH)
    assert resp.status == HTTPStatus.OK
    assert hub.stats["webhook_calls"] == 0
    assert hub.stats["rings"] == 0


async def test_webhook_disabled(hass: HomeAssistant, mock_entry, hass_client_no_auth) -> None:
    """Webhook abgeschaltet → nicht registriert, Aufruf bleibt ohne Wirkung."""
    hub = await _setup(hass, mock_entry, {CONF_WEBHOOK_ENABLED: False})
    assert hub.webhook_enabled is False
    assert WEBHOOK_ID not in _webhooks(hass)
    client = await hass_client_no_auth()
    await client.get(WEBHOOK_PATH)
    assert hub.stats["webhook_calls"] == 0
    assert await hass.config_entries.async_unload(mock_entry.entry_id)


async def test_webhook_unregistered_on_unload(hass: HomeAssistant, mock_entry) -> None:
    """Nach dem Entladen sind Webhook und Entitäts-Beobachtung weg."""
    hub = await _setup(hass, mock_entry)
    assert WEBHOOK_ID in _webhooks(hass)
    assert hub._unsub_triggers is not None
    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    assert WEBHOOK_ID not in _webhooks(hass)
    assert hub._unsub_triggers is None
    assert hub._webhook_registered is False
    hub.async_unload()  # zweiter Aufruf ist unschädlich


# ------------------------------------------------------------------- IP-Filter
def test_normalize_ip() -> None:
    """IPv4, IPv6, IPv4-gemappte IPv6 und Unsinn."""
    assert str(normalize_ip(" 192.168.1.50 ")) == "192.168.1.50"
    assert str(normalize_ip("::ffff:192.168.1.50")) == "192.168.1.50"
    assert str(normalize_ip("fe80::1")) == "fe80::1"
    assert normalize_ip("") is None
    assert normalize_ip(None) is None
    assert normalize_ip("kein-host") is None


async def test_ip_allowed(hass: HomeAssistant, mock_entry) -> None:
    """Erlaubte IP (auch als IPv4-gemappte IPv6), andere abgelehnt."""
    hub = await _setup(hass, mock_entry)
    assert hub.ip_allowed(SHELLY_HOST) is True
    assert hub.ip_allowed(f"::ffff:{SHELLY_HOST}") is True
    assert hub.ip_allowed("192.168.1.51") is False
    assert hub.ip_allowed(None) is False
    assert hub.ip_allowed("murks") is False


async def test_ip_allowed_multiple_sources(hass: HomeAssistant, mock_entry) -> None:
    """Mehrere Quellen (mit Leerzeichen) sind alle erlaubt."""
    hub = await _setup(
        hass,
        mock_entry,
        {CONF_RESTRICT_IP: True, CONF_ALLOWED_SOURCES: [" 192.168.1.99 ", "fd00::5"]},
    )
    assert hub.allowed_sources == ["192.168.1.99", "fd00::5"]
    assert hub.ip_allowed("192.168.1.99") is True
    assert hub.ip_allowed("fd00::5") is True
    assert hub.ip_allowed(SHELLY_HOST) is False


async def test_ip_allowed_hostname(hass: HomeAssistant, mock_entry) -> None:
    """Hostname wird einmalig aufgelöst (alle Adressen erlaubt); keine echte Auflösung."""
    infos = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.77", 0)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:192.168.1.78", 0, 0, 0)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fe80::1%eth0", 0, 0, 0)),
    ]
    resolver = AsyncMock(return_value=infos)
    with patch.object(hass.loop, "getaddrinfo", resolver):
        hub = await _setup(
            hass,
            mock_entry,
            {CONF_RESTRICT_IP: True, CONF_ALLOWED_SOURCES: ["klingel.lan", SHELLY_HOST]},
        )
    resolver.assert_awaited_once()
    assert resolver.await_args.args[0] == "klingel.lan"
    assert hub.ip_allowed("192.168.1.77") is True
    assert hub.ip_allowed("192.168.1.78") is True
    assert hub.ip_allowed(SHELLY_HOST) is True
    assert hub.ip_allowed("192.168.1.79") is False


async def test_ip_allowed_hostname_unresolvable(hass: HomeAssistant, mock_entry, caplog) -> None:
    """Nicht auflösbarer Hostname → Filter lässt nichts durch, Warnung im Log."""
    with patch.object(hass.loop, "getaddrinfo", AsyncMock(side_effect=OSError("nx"))):
        hub = await _setup(
            hass, mock_entry, {CONF_RESTRICT_IP: True, CONF_ALLOWED_SOURCES: ["weg.lan"]}
        )
    assert hub.ip_allowed("192.168.1.77") is False
    assert "nicht auflösbar" in caplog.text


# -------------------------------------------------------- Entitäts-Auslöser
def _st(entity_id: str, state: str | None) -> State | None:
    return None if state is None else State(entity_id, state)


@pytest.mark.parametrize(
    ("domain", "old", "new", "expected"),
    [
        ("binary_sensor", STATE_OFF, STATE_ON, True),
        ("binary_sensor", STATE_UNAVAILABLE, STATE_ON, False),
        ("binary_sensor", STATE_UNKNOWN, STATE_ON, False),
        ("binary_sensor", STATE_ON, STATE_OFF, False),
        ("binary_sensor", STATE_ON, STATE_ON, False),
        ("binary_sensor", None, STATE_ON, False),
        ("binary_sensor", STATE_OFF, None, False),
        ("binary_sensor", STATE_OFF, STATE_UNAVAILABLE, False),
        ("input_boolean", STATE_OFF, STATE_ON, True),
        ("input_boolean", STATE_UNKNOWN, STATE_ON, False),
        ("event", TS1, TS2, True),
        ("event", STATE_UNKNOWN, TS1, True),
        ("event", STATE_UNAVAILABLE, TS1, False),
        ("event", TS1, TS1, False),
        ("event", TS1, STATE_UNKNOWN, False),
        ("event", None, TS1, False),
        ("button", TS1, TS2, True),
        ("button", STATE_UNAVAILABLE, TS2, False),
        ("input_button", STATE_UNKNOWN, TS2, True),
        ("input_button", TS2, None, False),
    ],
)
def test_is_ring_transition(domain, old, new, expected) -> None:
    """Tabelle der Zustandswechsel, die als Klingeln gelten."""
    entity_id = f"{domain}.taster"
    assert is_ring_transition(entity_id, _st(entity_id, old), _st(entity_id, new)) is expected


@pytest.mark.parametrize("domain", TRIGGER_DOMAINS)
async def test_entity_trigger_each_domain(hass: HomeAssistant, mock_entry, domain) -> None:
    """Für jede erlaubte Domain löst ein passender Zustandswechsel das Klingeln aus."""
    entity_id = f"{domain}.taster"
    stateless = domain in ("event", "button", "input_button")
    hass.states.async_set(entity_id, TS1 if stateless else STATE_OFF)
    hub = await _setup(hass, mock_entry, {CONF_TRIGGER_ENTITIES: [entity_id]})
    assert hub.trigger_entities == [entity_id]
    hass.states.async_set(entity_id, TS2 if stateless else STATE_ON)
    await hass.async_block_till_done()
    assert hub.stats["entity_triggers"] == 1
    assert hub.stats["rings"] == 1
    assert hub.stats["last_call"] == {
        "time": hub.stats["last_call"]["time"],
        "source": "entity",
        "entity_id": entity_id,
        "result": "ring",
    }


async def test_entity_trigger_ignored_transitions(hass: HomeAssistant, mock_entry) -> None:
    """Verfügbar werden, Ausschalten und Attributänderungen klingeln nicht."""
    hass.states.async_set(TRIGGER, STATE_UNAVAILABLE)
    hub = await _setup(hass, mock_entry)
    hass.states.async_set(TRIGGER, STATE_ON)
    hass.states.async_set(TRIGGER, STATE_ON, {"x": 1})
    hass.states.async_set(TRIGGER, STATE_OFF)
    await hass.async_block_till_done()
    assert hub.stats["entity_triggers"] == 0
    assert hub.stats["rings"] == 0


async def test_entity_trigger_own_event_ignored(hass: HomeAssistant, mock_entry) -> None:
    """Die eigene Event-Entität löst nie aus (Schutz vor Schleifen)."""
    own = "event.haustur_klingel"
    hass.states.async_set(own, TS1)
    hub = await _setup(hass, mock_entry, {CONF_TRIGGER_ENTITIES: [own]})
    hub.event_entity_id = own
    hass.states.async_set(own, TS2)
    await hass.async_block_till_done()
    assert hub.stats["entity_triggers"] == 0
    assert hub.stats["rings"] == 0


async def test_entity_trigger_debounced(hass: HomeAssistant, mock_entry) -> None:
    """Zweiter Tastendruck innerhalb der Entprellzeit → 'debounced'."""
    hass.states.async_set(TRIGGER, STATE_OFF)
    hub = await _setup(hass, mock_entry)
    hass.states.async_set(TRIGGER, STATE_ON)
    hass.states.async_set(TRIGGER, STATE_OFF)
    hass.states.async_set(TRIGGER, STATE_ON)
    await hass.async_block_till_done()
    assert hub.stats["entity_triggers"] == 2
    assert hub.stats["rings"] == 1
    assert hub.stats["debounced"] == 1
    assert hub.stats["last_call"]["result"] == "debounced"


async def test_no_trigger_entities(hass: HomeAssistant, mock_entry) -> None:
    """Ohne Auslöser-Entitäten wird nichts beobachtet."""
    hub = await _setup(hass, mock_entry, {CONF_TRIGGER_ENTITIES: []})
    assert hub._unsub_triggers is None


# ----------------------------------------------------------------- Entprellung
async def test_debounce(hass: HomeAssistant, mock_entry) -> None:
    """Zweites Klingeln innerhalb der Entprellzeit verworfen, danach wieder angenommen."""
    hub = await _setup(hass, mock_entry)
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


async def test_debounce_via_webhook(hass: HomeAssistant, mock_entry, hass_client_no_auth) -> None:
    """Webhook antwortet bei Entprellung mit 'debounced'."""
    hub = await _setup(hass, mock_entry, {CONF_RESTRICT_IP: False})
    client = await hass_client_no_auth()
    assert await (await client.get(WEBHOOK_PATH)).text() == "ok"
    resp = await client.get(WEBHOOK_PATH)
    assert resp.status == HTTPStatus.OK
    assert await resp.text() == "debounced"
    assert hub.stats["last_call"]["result"] == "debounced"
    await hass.async_block_till_done()


# ------------------------------------------------------------------------ Gong
async def test_gong_pulse(hass: HomeAssistant, mock_entry) -> None:
    """Gong an → switch.turn_on, nach der Impulsdauer switch.turn_off."""
    hub = await _setup(hass, mock_entry)
    on, off = _mock_switch(hass)
    assert hub.gong_entity_id == GONG
    hub.gong_enabled = True
    assert hub.async_ring() is True
    await hass.async_block_till_done(wait_background_tasks=True)
    assert [c.data["entity_id"] for c in on] == [GONG]
    assert [c.data["entity_id"] for c in off] == [GONG]
    assert hub.stats["gong_pulses"] == 1
    assert hub.stats["gong_errors"] == 0


async def test_gong_duration_used(hass: HomeAssistant, mock_entry) -> None:
    """Zwischen Ein und Aus wird die eingestellte Impulsdauer gewartet."""
    hub = await _setup(hass, mock_entry)
    _mock_switch(hass)
    hub.gong_enabled = True
    hub.gong_duration = 0.7
    with patch(
        "custom_components.homekit_tuerklingel.hub.asyncio.sleep", AsyncMock()
    ) as sleep:
        await hub.async_gong()
    sleep.assert_awaited_once_with(0.7)


async def test_gong_muted(hass: HomeAssistant, mock_entry) -> None:
    """Gong stumm → kein Schaltbefehl."""
    hub = await _setup(hass, mock_entry)
    on, _off = _mock_switch(hass)
    hub.gong_enabled = False
    hub.async_ring()
    await hass.async_block_till_done()
    assert on == []
    assert hub.stats["gong_pulses"] == 0


async def test_no_gong(hass: HomeAssistant, mock_entry) -> None:
    """Kein Gong-Schalter konfiguriert → nichts wird geschaltet."""
    hub = await _setup(hass, mock_entry, {CONF_GONG_ENTITY: None})
    on, _off = _mock_switch(hass)
    assert hub.gong_entity_id is None
    hub.gong_enabled = True
    await hub.async_gong()
    assert on == []
    assert hub.stats["gong_pulses"] == 0


async def test_gong_turn_on_error(hass: HomeAssistant, mock_entry, caplog) -> None:
    """Einschalten schlägt fehl → gong_errors, kein Ausschalten, kein Puls."""
    hub = await _setup(hass, mock_entry)
    _on, off = _mock_switch(hass)

    async def _fail(call: ServiceCall) -> None:
        raise HomeAssistantError("Relais weg")

    hass.services.async_register("switch", "turn_on", _fail)
    hub.gong_enabled = True
    await hub.async_gong()
    assert hub.stats["gong_errors"] == 1
    assert hub.stats["gong_pulses"] == 0
    assert off == []
    assert "nicht einschaltbar" in caplog.text


async def test_gong_service_missing(hass: HomeAssistant, mock_entry) -> None:
    """Dienst switch.turn_on fehlt (ServiceNotFound) → gong_errors."""
    hub = await _setup(hass, mock_entry)
    hass.services.async_remove("switch", "turn_on")
    hub.gong_enabled = True
    await hub.async_gong()
    assert hub.stats["gong_errors"] == 1


async def test_gong_turn_off_error(hass: HomeAssistant, mock_entry, caplog) -> None:
    """Ausschalten schlägt fehl → gong_errors; der Puls zählt trotzdem."""
    hub = await _setup(hass, mock_entry)
    _mock_switch(hass)
    hass.services.async_remove("switch", "turn_off")
    hub.gong_enabled = True
    await hub.async_gong()
    assert hub.stats["gong_errors"] == 1
    assert hub.stats["gong_pulses"] == 1
    assert "nicht ausschaltbar" in caplog.text


async def test_gong_overlap_and_cancel(hass: HomeAssistant, mock_entry) -> None:
    """Zweiter Gong während des Pulses wird übersprungen; Abbruch schaltet trotzdem aus."""
    hub = await _setup(hass, mock_entry)
    on, off = _mock_switch(hass)
    hub.gong_enabled = True
    hub.gong_duration = 30
    task = asyncio.create_task(hub.async_gong())
    for _ in range(20):
        await asyncio.sleep(0)
        if on:
            break
    assert len(on) == 1
    assert hub._gong_lock.locked()

    await hub.async_gong()  # läuft bereits → sofort zurück
    assert len(on) == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [c.data["entity_id"] for c in off] == [GONG]
    assert hub.stats["gong_pulses"] == 0
    assert not hub._gong_lock.locked()


# -------------------------------------------------------------- Snapshot/Push
async def test_snapshot(hass: HomeAssistant, mock_entry) -> None:
    """Snapshot der Quellkamera speichern und Listener benachrichtigen."""
    hub = await _setup(hass, mock_entry)
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


async def test_snapshot_error(hass: HomeAssistant, mock_entry) -> None:
    """Kamerafehler → snapshot_errors, alter Snapshot bleibt."""
    hub = await _setup(hass, mock_entry)
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


async def test_notify(hass: HomeAssistant, mock_entry) -> None:
    """Push mit Titel, Text ({name} ersetzt) und Snapshot-Anhang an alle Dienste."""
    calls_phone = async_mock_service(hass, "notify", "mobile_app_iphone")
    calls_pad = async_mock_service(hass, "notify", "mobile_app_ipad")
    hub = await _setup(hass, mock_entry, NOTIFY_OPTS)
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


async def test_notify_defaults_without_image(hass: HomeAssistant, mock_entry) -> None:
    """Standardtexte; ohne Snapshot kein Bildanhang."""
    calls = async_mock_service(hass, "notify", "mobile_app_iphone")
    hub = await _setup(
        hass,
        mock_entry,
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


async def test_notify_disabled(hass: HomeAssistant, mock_entry) -> None:
    """notify_enabled aus (oder keine Dienste) → keine Push-Nachricht."""
    calls = async_mock_service(hass, "notify", "mobile_app_iphone")
    hub = await _setup(hass, mock_entry, {**NOTIFY_OPTS, CONF_NOTIFY_ENABLED: False})
    await hub.async_notify()
    assert calls == []
    hass.config_entries.async_update_entry(
        mock_entry, options={CONF_NOTIFY_ENABLED: True, CONF_NOTIFY_SERVICES: []}
    )
    await hass.async_block_till_done()
    await mock_entry.runtime_data.async_notify()
    assert calls == []


async def test_notify_error(hass: HomeAssistant, mock_entry) -> None:
    """Unbekannter Dienst → notify_errors, andere Dienste laufen weiter."""
    calls = async_mock_service(hass, "notify", "mobile_app_ipad")
    hub = await _setup(hass, mock_entry, NOTIFY_OPTS)
    await hub.async_notify()
    assert hub.stats["notify_errors"] == 1
    assert len(calls) == 1


async def test_options_properties(hass: HomeAssistant, mock_entry) -> None:
    """Name, auto_off und Daten aus Titel, Optionen bzw. Entry-Daten."""
    hub = await _setup(hass, mock_entry, {CONF_AUTO_OFF: 12})
    assert hub.name == "Haustür"
    assert hub.auto_off == 12
    assert hub.webhook_id == WEBHOOK_ID
    assert hub.camera_entity_id == CAMERA
    # Standardwerte ohne Optionen
    assert hub.webhook_enabled is True
    assert hub.restrict_ip is False
    assert hub.allowed_sources == []
    assert hub.trigger_entities == []
    assert hub.gong_entity_id is None
