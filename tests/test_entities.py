"""Tests der Entitäten (event, binary_sensor, switch, number, image, sensor, camera)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.components import camera
from homeassistant.components.camera import CameraEntityFeature, Image
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, ServiceCall, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
    mock_restore_cache_with_extra_data,
)

from custom_components.homekit_tuerklingel.const import (
    CONF_ALLOWED_SOURCES,
    CONF_GONG_ENTITY,
    DOMAIN,
    EVENT_TYPE_RING,
    KEY_CAMERA,
    KEY_COOLDOWN,
    KEY_EVENT,
    KEY_GONG,
    KEY_GONG_DURATION,
    KEY_LAST_RING,
    KEY_RINGING,
    KEY_SNAPSHOT,
)

from .conftest import CAMERA, GONG, TRIGGER, WEBHOOK_ID

JPEG = b"\xff\xd8\xff\xe0fake-jpeg"
STREAM_URL = "rtsp://192.168.1.60:554/h264Preview_01_sub"

ALL_KEYS = (
    ("event", KEY_EVENT),
    ("binary_sensor", KEY_RINGING),
    ("switch", KEY_GONG),
    ("number", KEY_COOLDOWN),
    ("number", KEY_GONG_DURATION),
    ("image", KEY_SNAPSHOT),
    ("sensor", KEY_LAST_RING),
    ("camera", KEY_CAMERA),
)

_ORIG_GET_IMAGE = camera.async_get_image
_ORIG_GET_STREAM = camera.async_get_stream_source


@pytest.fixture
def source_camera(hass: HomeAssistant):
    """Quellkamera simulieren: Zustand setzen, Bild/Stream der Quelle patchen.

    Andere Kameras (die Proxy-Kamera) laufen über die echte Core-Funktion.
    """
    hass.states.async_set(CAMERA, "idle")
    calls: list[tuple[str, int | None, int | None]] = []

    async def _get_image(hass, entity_id, timeout=10, width=None, height=None):
        if entity_id == CAMERA:
            calls.append((entity_id, width, height))
            return Image("image/jpeg", JPEG)
        return await _ORIG_GET_IMAGE(hass, entity_id, timeout, width, height)

    async def _get_stream(hass, entity_id):
        if entity_id == CAMERA:
            return STREAM_URL
        return await _ORIG_GET_STREAM(hass, entity_id)

    with (
        patch.object(camera, "async_get_image", side_effect=_get_image),
        patch.object(camera, "async_get_stream_source", side_effect=_get_stream),
    ):
        yield calls


async def _tick(hass: HomeAssistant, freezer, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _eid(hass: HomeAssistant, entry: MockConfigEntry, platform: str, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{key}"
    )


def _preregister(
    hass: HomeAssistant, entry: MockConfigEntry, platform: str, key: str, object_id: str
) -> str:
    """Entität vorab registrieren, damit die Entitäts-ID für den Restore feststeht."""
    entry.add_to_hass(hass)
    return er.async_get(hass).async_get_or_create(
        platform,
        DOMAIN,
        f"{entry.entry_id}_{key}",
        suggested_object_id=object_id,
        config_entry=entry,
    ).entity_id


def _with_options(entry: MockConfigEntry, **changes) -> MockConfigEntry:
    """Kopie des Entry mit geänderten Optionen (None-Werte werden entfernt)."""
    options = {**entry.options, **changes}
    return MockConfigEntry(
        domain=DOMAIN,
        title=entry.title,
        unique_id=entry.unique_id,
        data=dict(entry.data),
        options={k: v for k, v in options.items() if v is not None},
        version=entry.version,
    )


def _gong_services(hass: HomeAssistant) -> tuple[list[ServiceCall], list[ServiceCall]]:
    """switch.turn_on/turn_off ersetzen (nach dem Setup aufrufen)."""
    return (
        async_mock_service(hass, "switch", "turn_on"),
        async_mock_service(hass, "switch", "turn_off"),
    )


@pytest.fixture
def local_entry(mock_entry: MockConfigEntry) -> MockConfigEntry:
    """Entry mit IP-Filter auf 127.0.0.1 (Quelle des Testclients)."""
    return _with_options(mock_entry, **{CONF_ALLOWED_SOURCES: ["127.0.0.1"]})


async def test_entities_on_one_device(
    hass: HomeAssistant, mock_entry, source_camera
) -> None:
    """Alle Entitäten existieren und hängen am selben Gerät (wichtig für HomeKit)."""
    await _setup(hass, mock_entry)

    ent_reg = er.async_get(hass)
    device_ids = set()
    for platform, key in ALL_KEYS:
        entity_id = _eid(hass, mock_entry, platform, key)
        assert entity_id is not None, key
        device_ids.add(ent_reg.async_get(entity_id).device_id)
        assert hass.states.get(entity_id) is not None, entity_id
    assert len(device_ids) == 1
    device = dr.async_get(hass).async_get(device_ids.pop())
    assert (DOMAIN, mock_entry.entry_id) in device.identifiers

    # Kein Erreichbarkeits-Sensor mehr: nur „Klingelt“ als binary_sensor
    binary_sensors = [
        e
        for e in er.async_entries_for_config_entry(ent_reg, mock_entry.entry_id)
        if e.domain == "binary_sensor"
    ]
    assert [e.unique_id for e in binary_sensors] == [f"{mock_entry.entry_id}_{KEY_RINGING}"]

    event_id = _eid(hass, mock_entry, "event", KEY_EVENT)
    event = hass.states.get(event_id)
    assert event.attributes["device_class"] == "doorbell"
    assert event.attributes["event_types"] == [EVENT_TYPE_RING]
    assert event.state == STATE_UNKNOWN

    # Standardwerte
    assert hass.states.get(_eid(hass, mock_entry, "switch", KEY_GONG)).state == STATE_ON
    assert float(hass.states.get(_eid(hass, mock_entry, "number", KEY_COOLDOWN)).state) == 3.0
    assert (
        float(hass.states.get(_eid(hass, mock_entry, "number", KEY_GONG_DURATION)).state)
        == 1.0
    )
    assert hass.states.get(_eid(hass, mock_entry, "sensor", KEY_LAST_RING)).state == STATE_UNKNOWN
    assert hass.states.get(_eid(hass, mock_entry, "image", KEY_SNAPSHOT)).state == STATE_UNKNOWN
    assert (
        hass.states.get(_eid(hass, mock_entry, "binary_sensor", KEY_RINGING)).state
        == STATE_OFF
    )
    hub = mock_entry.runtime_data
    assert hub.image_entity_id == _eid(hass, mock_entry, "image", KEY_SNAPSHOT)
    assert hub.event_entity_id == event_id

    # Entladen setzt Bild- und Event-Entität im Hub zurück
    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert hub.image_entity_id is None
    assert hub.event_entity_id is None


async def test_ring_via_webhook(
    hass: HomeAssistant,
    local_entry,
    source_camera,
    hass_client_no_auth,
) -> None:
    """Webhook → Event, Binärsensor, Zeitstempel, Snapshot und Gong."""
    await _setup(hass, local_entry)
    hub = local_entry.runtime_data
    on_calls, _off_calls = _gong_services(hass)
    client = await hass_client_no_auth()

    resp = await client.get(f"/api/webhook/{WEBHOOK_ID}")
    assert resp.status == 200
    assert await resp.text() == "ok"
    await hass.async_block_till_done()

    event = hass.states.get(_eid(hass, local_entry, "event", KEY_EVENT))
    assert event.attributes["event_type"] == EVENT_TYPE_RING
    assert event.state != STATE_UNKNOWN

    ringing_id = _eid(hass, local_entry, "binary_sensor", KEY_RINGING)
    assert hass.states.get(ringing_id).state == STATE_ON

    sensor = hass.states.get(_eid(hass, local_entry, "sensor", KEY_LAST_RING))
    assert dt_util.parse_datetime(sensor.state) == hub.last_ring.replace(microsecond=0)

    image_id = _eid(hass, local_entry, "image", KEY_SNAPSHOT)
    image_state = hass.states.get(image_id)
    assert image_state.state == hub.snapshot_time.isoformat()
    resp = await client.get(
        f"/api/image_proxy/{image_id}?token={image_state.attributes['access_token']}"
    )
    assert resp.status == 200
    assert await resp.read() == JPEG
    assert resp.content_type == "image/jpeg"

    assert [c.data[ATTR_ENTITY_ID] for c in on_calls] == [GONG]

    # Nach auto_off (Standard 5 s) wieder aus
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()
    assert hass.states.get(ringing_id).state == STATE_OFF

    # Zweiter Aufruf innerhalb der Entprellzeit
    resp = await client.get(f"/api/webhook/{WEBHOOK_ID}")
    assert resp.status == 200
    assert await resp.text() == "debounced"
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_webhook_rejected_from_other_source(
    hass: HomeAssistant, mock_entry, source_camera, hass_client_no_auth
) -> None:
    """Webhook nur von 192.168.1.50 erlaubt → Testclient (127.0.0.1) abgelehnt."""
    await _setup(hass, mock_entry)
    client = await hass_client_no_auth()
    resp = await client.get(f"/api/webhook/{WEBHOOK_ID}")
    assert resp.status == 403
    await hass.async_block_till_done()
    ringing_id = _eid(hass, mock_entry, "binary_sensor", KEY_RINGING)
    assert hass.states.get(ringing_id).state == STATE_OFF
    assert mock_entry.runtime_data.last_ring is None


async def test_ring_via_trigger_entity(
    hass: HomeAssistant, mock_entry, source_camera
) -> None:
    """Auslöser-Entität off → on klingelt: Event, Binärsensor, Zeitstempel."""
    hass.states.async_set(TRIGGER, STATE_OFF)
    await _setup(hass, mock_entry)
    hub = mock_entry.runtime_data
    on_calls, _off_calls = _gong_services(hass)
    event_id = _eid(hass, mock_entry, "event", KEY_EVENT)
    ringing_id = _eid(hass, mock_entry, "binary_sensor", KEY_RINGING)

    hass.states.async_set(TRIGGER, STATE_ON)
    await hass.async_block_till_done()

    assert hass.states.get(event_id).attributes["event_type"] == EVENT_TYPE_RING
    assert hass.states.get(ringing_id).state == STATE_ON
    assert hub.last_ring is not None
    assert hub.stats["entity_triggers"] == 1
    assert len(on_calls) == 1

    # Zurück auf off klingelt nicht
    hass.states.async_set(TRIGGER, STATE_OFF)
    await hass.async_block_till_done()
    assert hub.stats["entity_triggers"] == 1
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_ringing_timer_restarts(
    hass: HomeAssistant, mock_entry, source_camera, freezer
) -> None:
    """Erneutes Klingeln startet den Ausschalt-Timer neu."""
    await _setup(hass, mock_entry)
    hub = mock_entry.runtime_data
    _gong_services(hass)
    ringing_id = _eid(hass, mock_entry, "binary_sensor", KEY_RINGING)

    # Entprellung aus, damit zwei Klingeln direkt nacheinander zählen
    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: _eid(hass, mock_entry, "number", KEY_COOLDOWN), "value": 0},
        blocking=True,
    )
    assert hub.cooldown == 0.0

    assert hub.async_ring()
    await hass.async_block_till_done()
    await _tick(hass, freezer, 4)
    assert hass.states.get(ringing_id).state == STATE_ON

    # Zweites Klingeln nach 4 s: Timer neu, also nach weiteren 3 s noch an
    assert hub.async_ring()
    await hass.async_block_till_done()
    await _tick(hass, freezer, 3)
    assert hass.states.get(ringing_id).state == STATE_ON

    await _tick(hass, freezer, 3)
    assert hass.states.get(ringing_id).state == STATE_OFF

    # Entladen mit laufendem Timer bricht ihn ab
    assert hub.async_ring()
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    await hass.async_block_till_done()


async def test_gong_pulse(hass: HomeAssistant, mock_entry, source_camera) -> None:
    """Klingeln schaltet den Gong-Schalter ein und nach der Gong-Dauer wieder aus."""
    await _setup(hass, mock_entry)
    hub = mock_entry.runtime_data
    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: _eid(hass, mock_entry, "number", KEY_GONG_DURATION), "value": 0.2},
        blocking=True,
    )
    assert hub.gong_duration == 0.2
    on_calls, off_calls = _gong_services(hass)

    assert hub.async_ring()
    await hass.async_block_till_done()
    assert [c.data[ATTR_ENTITY_ID] for c in on_calls] == [GONG]
    assert off_calls == []  # Impuls läuft noch

    await hass.async_block_till_done(wait_background_tasks=True)
    assert [c.data[ATTR_ENTITY_ID] for c in off_calls] == [GONG]
    assert hub.stats["gong_pulses"] == 1


async def test_gong_switch(hass: HomeAssistant, mock_entry, source_camera) -> None:
    """Schalter aus → Gong stumm (keine Aufrufe); wieder an → Gong-Schalter gepulst."""
    await _setup(hass, mock_entry)
    hub = mock_entry.runtime_data
    switch_id = _eid(hass, mock_entry, "switch", KEY_GONG)
    entity = hass.data["switch"].get_entity(switch_id)

    # Über den Dienst stumm schalten (vor dem Ersetzen von switch.turn_off)
    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: switch_id}, blocking=True
    )
    state = hass.states.get(switch_id)
    assert state.state == STATE_OFF
    assert state.attributes["icon"] == "mdi:bell-off"
    assert hub.gong_enabled is False

    on_calls, off_calls = _gong_services(hass)
    hub.async_ring()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert on_calls == []
    assert off_calls == []

    # switch.turn_on ist jetzt ersetzt → direkt an der Entität einschalten
    await entity.async_turn_on()
    state = hass.states.get(switch_id)
    assert state.state == STATE_ON
    assert state.attributes["icon"] == "mdi:bell"
    assert hub.gong_enabled is True

    hub.cooldown = 0
    hub.gong_duration = 0
    hub.async_ring()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert [c.data[ATTR_ENTITY_ID] for c in on_calls] == [GONG]
    assert [c.data[ATTR_ENTITY_ID] for c in off_calls] == [GONG]

    await entity.async_turn_off()
    assert hub.gong_enabled is False


async def test_without_gong(hass: HomeAssistant, mock_entry, source_camera) -> None:
    """Ohne Gong-Schalter: keine Gong-Entitäten, verwaiste Einträge entfernt, kein Aufruf."""
    entry = _with_options(mock_entry, **{CONF_GONG_ENTITY: None})
    old_switch = _preregister(hass, entry, "switch", KEY_GONG, "alt_gong")
    old_number = _preregister(hass, entry, "number", KEY_GONG_DURATION, "alt_dauer")
    ent_reg = er.async_get(hass)
    assert ent_reg.async_get(old_switch) is not None
    assert ent_reg.async_get(old_number) is not None

    await _setup(hass, entry)
    hub = entry.runtime_data
    assert hub.gong_entity_id is None
    assert _eid(hass, entry, "switch", KEY_GONG) is None
    assert _eid(hass, entry, "number", KEY_GONG_DURATION) is None
    assert ent_reg.async_get(old_switch) is None
    assert ent_reg.async_get(old_number) is None
    assert hass.states.get(old_switch) is None
    # Entprellzeit gibt es immer
    assert _eid(hass, entry, "number", KEY_COOLDOWN) is not None

    on_calls, off_calls = _gong_services(hass)
    assert hub.async_ring()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert on_calls == []
    assert off_calls == []
    assert hass.states.get(_eid(hass, entry, "binary_sensor", KEY_RINGING)).state == STATE_ON


async def test_without_gong_nothing_to_remove(
    hass: HomeAssistant, mock_entry, source_camera
) -> None:
    """Ohne Gong und ohne alte Einträge: Setup läuft normal."""
    entry = _with_options(mock_entry, **{CONF_GONG_ENTITY: None})
    await _setup(hass, entry)
    assert _eid(hass, entry, "switch", KEY_GONG) is None
    assert _eid(hass, entry, "number", KEY_GONG_DURATION) is None
    assert _eid(hass, entry, "number", KEY_COOLDOWN) is not None


async def test_numbers_set_hub(hass: HomeAssistant, mock_entry, source_camera) -> None:
    """Zahlenwerte landen im Hub."""
    await _setup(hass, mock_entry)
    hub = mock_entry.runtime_data

    cooldown_id = _eid(hass, mock_entry, "number", KEY_COOLDOWN)
    duration_id = _eid(hass, mock_entry, "number", KEY_GONG_DURATION)
    state = hass.states.get(cooldown_id)
    assert state.attributes["min"] == 0.0
    assert state.attributes["max"] == 60.0
    assert state.attributes["step"] == 0.5
    assert state.attributes["mode"] == "box"
    assert state.attributes["unit_of_measurement"] == "s"
    state = hass.states.get(duration_id)
    assert state.attributes["min"] == 0.2
    assert state.attributes["max"] == 10.0
    assert state.attributes["step"] == 0.1
    ent_reg = er.async_get(hass)
    assert ent_reg.async_get(cooldown_id).entity_category == "config"
    assert ent_reg.async_get(duration_id).entity_category == "config"

    await hass.services.async_call(
        "number", "set_value", {ATTR_ENTITY_ID: cooldown_id, "value": 12.5}, blocking=True
    )
    await hass.services.async_call(
        "number", "set_value", {ATTR_ENTITY_ID: duration_id, "value": 2.3}, blocking=True
    )
    assert hub.cooldown == 12.5
    assert hub.gong_duration == 2.3
    assert float(hass.states.get(cooldown_id).state) == 12.5
    assert float(hass.states.get(duration_id).state) == 2.3


async def test_restore(hass: HomeAssistant, mock_entry, source_camera) -> None:
    """Schalter, Zahlen und Zeitstempel werden nach einem Neustart wiederhergestellt."""
    switch_id = _preregister(hass, mock_entry, "switch", KEY_GONG, "tuer_gong")
    cooldown_id = _preregister(hass, mock_entry, "number", KEY_COOLDOWN, "tuer_entprell")
    duration_id = _preregister(hass, mock_entry, "number", KEY_GONG_DURATION, "tuer_dauer")
    sensor_id = _preregister(hass, mock_entry, "sensor", KEY_LAST_RING, "tuer_zuletzt")
    last = dt_util.parse_datetime("2026-11-12T18:30:00+00:00")

    def _number(value: float, lo: float, hi: float, step: float) -> dict:
        return {
            "native_max_value": hi,
            "native_min_value": lo,
            "native_step": step,
            "native_unit_of_measurement": "s",
            "native_value": value,
        }

    mock_restore_cache_with_extra_data(
        hass,
        [
            (State(switch_id, STATE_OFF), {}),
            (State(cooldown_id, "7.5"), _number(7.5, 0, 60, 0.5)),
            # außerhalb des Bereichs → Standardwert
            (State(duration_id, "99"), _number(99, 0.2, 10, 0.1)),
            (
                State(sensor_id, last.isoformat()),
                {
                    "native_value": {
                        "__type": "<class 'datetime.datetime'>",
                        "isoformat": last.isoformat(),
                    },
                    "native_unit_of_measurement": None,
                },
            ),
        ],
    )
    await _setup(hass, mock_entry)
    hub = mock_entry.runtime_data

    assert hass.states.get(switch_id).state == STATE_OFF
    assert hub.gong_enabled is False
    assert hub.cooldown == 7.5
    assert float(hass.states.get(cooldown_id).state) == 7.5
    assert hub.gong_duration == 1.0
    assert hub.last_ring == last
    assert dt_util.parse_datetime(hass.states.get(sensor_id).state) == last


async def test_proxy_camera(hass: HomeAssistant, mock_entry, source_camera) -> None:
    """Bild und Stream der Quellkamera werden durchgereicht (so wie HomeKit sie holt)."""
    await _setup(hass, mock_entry)
    cam_id = _eid(hass, mock_entry, "camera", KEY_CAMERA)

    state = hass.states.get(cam_id)
    assert state.state != STATE_UNAVAILABLE
    assert state.attributes["supported_features"] == CameraEntityFeature.STREAM
    assert state.attributes["source_entity_id"] == CAMERA

    # Wie homekit/type_cameras.py: async_get_image mit Größe, async_get_stream_source
    source_camera.clear()
    image = await camera.async_get_image(hass, cam_id, width=640, height=360)
    assert image.content == JPEG
    assert source_camera == [(CAMERA, 640, 360)]
    assert await camera.async_get_stream_source(hass, cam_id) == STREAM_URL

    # Quelle ohne Kamera-Objekt: Marke/Modell/Streaming leer
    entity = hass.data["camera"].get_entity(cam_id)
    assert entity.brand is None
    assert entity.model is None
    assert entity.is_streaming is False

    # Fehler der Quelle → kein Bild / kein Stream
    with (
        patch.object(camera, "async_get_image", side_effect=HomeAssistantError("x")),
        patch.object(
            camera, "async_get_stream_source", side_effect=HomeAssistantError("x")
        ),
    ):
        assert await entity.async_camera_image() is None
        assert await entity.stream_source() is None

    # Quelle unavailable bzw. entfernt → Proxy unavailable
    hass.states.async_set(CAMERA, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    assert hass.states.get(cam_id).state == STATE_UNAVAILABLE
    hass.states.async_set(CAMERA, "idle")
    await hass.async_block_till_done()
    assert hass.states.get(cam_id).state != STATE_UNAVAILABLE
    hass.states.async_remove(CAMERA)
    await hass.async_block_till_done()
    assert hass.states.get(cam_id).state == STATE_UNAVAILABLE


async def test_proxy_camera_source_attributes(
    hass: HomeAssistant, mock_entry, source_camera
) -> None:
    """Marke, Modell und Streaming kommen von der Quellkamera, wenn sie geladen ist."""
    await _setup(hass, mock_entry)
    cam_id = _eid(hass, mock_entry, "camera", KEY_CAMERA)
    entity = hass.data["camera"].get_entity(cam_id)

    class _Src:
        brand = "Reolink"
        model = "Doorbell"
        is_streaming = True

    with patch.object(camera, "get_camera_from_entity_id", return_value=_Src()):
        assert entity.brand == "Reolink"
        assert entity.model == "Doorbell"
        assert entity.is_streaming is True
