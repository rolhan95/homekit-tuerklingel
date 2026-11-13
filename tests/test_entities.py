"""Tests der Entitäten (event, binary_sensor, switch, number, image, sensor, camera)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from aiohttp import ClientError
from homeassistant.components import camera
from homeassistant.components.camera import CameraEntityFeature, Image
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.homekit_tuerklingel.const import (
    CONF_CONNECTIVITY,
    CONF_RESTRICT_IP,
    DOMAIN,
    EVENT_TYPE_RING,
    KEY_CAMERA,
    KEY_CONNECTIVITY,
    KEY_COOLDOWN,
    KEY_EVENT,
    KEY_GONG,
    KEY_GONG_DURATION,
    KEY_LAST_RING,
    KEY_RINGING,
    KEY_SNAPSHOT,
)

from .conftest import CAMERA, SHELLY_HOST, SHELLY_MAC, WEBHOOK_ID

BASE = f"http://{SHELLY_HOST}"
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"
STREAM_URL = "rtsp://192.168.1.60:554/h264Preview_01_sub"

ALL_KEYS = (
    ("event", KEY_EVENT),
    ("binary_sensor", KEY_RINGING),
    ("binary_sensor", KEY_CONNECTIVITY),
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


def _mock_shelly(aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE}/shelly", json={"mac": SHELLY_MAC, "type": "SHSW-1"})
    aioclient_mock.get(
        f"{BASE}/settings", json={"relays": [{"btn_type": "detached"}]}
    )
    aioclient_mock.get(f"{BASE}/relay/0", json={"ison": True})


def _relay_calls(aioclient_mock: AiohttpClientMocker) -> int:
    return sum(1 for call in aioclient_mock.mock_calls if call[1].path == "/relay/0")


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


def _with_options(entry: MockConfigEntry, options: dict) -> MockConfigEntry:
    """Kopie des Entry mit anderen Optionen."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=entry.title,
        unique_id=entry.unique_id,
        data=dict(entry.data),
        options=options,
        version=entry.version,
    )


@pytest.fixture
def open_entry(mock_entry: MockConfigEntry) -> MockConfigEntry:
    """Entry ohne IP-Filter (Testclient kommt von 127.0.0.1)."""
    return _with_options(mock_entry, {CONF_RESTRICT_IP: False})


async def test_entities_on_one_device(
    hass: HomeAssistant, mock_entry, aioclient_mock, source_camera
) -> None:
    """Alle Entitäten existieren und hängen am selben Gerät (wichtig für HomeKit)."""
    _mock_shelly(aioclient_mock)
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

    event = hass.states.get(_eid(hass, mock_entry, "event", KEY_EVENT))
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

    # Entladen setzt die Bild-Entität im Hub zurück
    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert hub.image_entity_id is None


async def test_ring_via_webhook(
    hass: HomeAssistant,
    open_entry,
    aioclient_mock,
    source_camera,
    hass_client_no_auth,
) -> None:
    """Webhook → Event, Binärsensor, Zeitstempel, Snapshot und Gong."""
    _mock_shelly(aioclient_mock)
    await _setup(hass, open_entry)
    hub = open_entry.runtime_data
    client = await hass_client_no_auth()

    resp = await client.get(f"/api/webhook/{WEBHOOK_ID}")
    assert resp.status == 200
    await hass.async_block_till_done()

    event = hass.states.get(_eid(hass, open_entry, "event", KEY_EVENT))
    assert event.attributes["event_type"] == EVENT_TYPE_RING
    assert event.state != STATE_UNKNOWN

    ringing_id = _eid(hass, open_entry, "binary_sensor", KEY_RINGING)
    assert hass.states.get(ringing_id).state == STATE_ON

    sensor = hass.states.get(_eid(hass, open_entry, "sensor", KEY_LAST_RING))
    assert dt_util.parse_datetime(sensor.state) == hub.last_ring.replace(microsecond=0)

    image_id = _eid(hass, open_entry, "image", KEY_SNAPSHOT)
    image_state = hass.states.get(image_id)
    assert image_state.state == hub.snapshot_time.isoformat()
    resp = await client.get(
        f"/api/image_proxy/{image_id}?token={image_state.attributes['access_token']}"
    )
    assert resp.status == 200
    assert await resp.read() == JPEG
    assert resp.content_type == "image/jpeg"

    assert _relay_calls(aioclient_mock) == 1

    # Nach auto_off (Standard 5 s) wieder aus
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()
    assert hass.states.get(ringing_id).state == STATE_OFF

    # Zweiter Aufruf innerhalb der Entprellzeit
    resp = await client.get(f"/api/webhook/{WEBHOOK_ID}")
    assert resp.status == 200
    assert await resp.text() == "debounced"


async def test_ringing_timer_restarts(
    hass: HomeAssistant, open_entry, aioclient_mock, source_camera, freezer
) -> None:
    """Erneutes Klingeln startet den Ausschalt-Timer neu."""
    _mock_shelly(aioclient_mock)
    await _setup(hass, open_entry)
    hub = open_entry.runtime_data
    ringing_id = _eid(hass, open_entry, "binary_sensor", KEY_RINGING)

    # Entprellung aus, damit zwei Klingeln direkt nacheinander zählen
    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: _eid(hass, open_entry, "number", KEY_COOLDOWN), "value": 0},
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
    assert await hass.config_entries.async_unload(open_entry.entry_id)
    await hass.async_block_till_done()


async def test_gong_switch(
    hass: HomeAssistant, mock_entry, aioclient_mock, source_camera
) -> None:
    """Schalter aus → Hub stumm, kein Relais-Aufruf; wieder an → Relais."""
    _mock_shelly(aioclient_mock)
    await _setup(hass, mock_entry)
    hub = mock_entry.runtime_data
    switch_id = _eid(hass, mock_entry, "switch", KEY_GONG)

    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: switch_id}, blocking=True
    )
    state = hass.states.get(switch_id)
    assert state.state == STATE_OFF
    assert state.attributes["icon"] == "mdi:bell-off"
    assert hub.gong_enabled is False

    hub.async_ring()
    await hass.async_block_till_done()
    assert _relay_calls(aioclient_mock) == 0

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: switch_id}, blocking=True
    )
    state = hass.states.get(switch_id)
    assert state.state == STATE_ON
    assert state.attributes["icon"] == "mdi:bell"
    assert hub.gong_enabled is True

    hub.cooldown = 0
    hub.async_ring()
    await hass.async_block_till_done()
    assert _relay_calls(aioclient_mock) == 1


async def test_numbers_set_hub(
    hass: HomeAssistant, mock_entry, aioclient_mock, source_camera
) -> None:
    """Zahlenwerte landen im Hub; Gong-Dauer geht als timer an den Shelly."""
    _mock_shelly(aioclient_mock)
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


async def test_restore(hass: HomeAssistant, mock_entry, aioclient_mock, source_camera) -> None:
    """Schalter, Zahlen und Zeitstempel werden nach einem Neustart wiederhergestellt."""
    _mock_shelly(aioclient_mock)
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


async def test_connectivity(
    hass: HomeAssistant, mock_entry, aioclient_mock, source_camera
) -> None:
    """Erreichbarkeit folgt dem Ping des Hubs."""
    _mock_shelly(aioclient_mock)
    await _setup(hass, mock_entry)
    hub = mock_entry.runtime_data
    conn_id = _eid(hass, mock_entry, "binary_sensor", KEY_CONNECTIVITY)
    assert er.async_get(hass).async_get(conn_id).entity_category == "diagnostic"
    state = hass.states.get(conn_id)
    assert state.attributes["device_class"] == "connectivity"
    assert state.state == STATE_ON

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/shelly", exc=ClientError())
    await hub.async_update_availability()
    await hass.async_block_till_done()
    assert hass.states.get(conn_id).state == STATE_OFF


async def test_connectivity_unknown(
    hass: HomeAssistant, mock_entry, aioclient_mock, source_camera
) -> None:
    """Noch nicht geprüft → unbekannt."""
    _mock_shelly(aioclient_mock)
    with patch(
        "custom_components.homekit_tuerklingel.hub.TuerklingelHub.async_update_availability"
    ):
        await _setup(hass, mock_entry)
    conn_id = _eid(hass, mock_entry, "binary_sensor", KEY_CONNECTIVITY)
    assert hass.states.get(conn_id).state == STATE_UNKNOWN


async def test_connectivity_disabled(
    hass: HomeAssistant, mock_entry, aioclient_mock, source_camera
) -> None:
    """Ohne Erreichbarkeitsprüfung gibt es keinen Erreichbarkeits-Sensor."""
    _mock_shelly(aioclient_mock)
    entry = _with_options(mock_entry, {CONF_CONNECTIVITY: False})
    await _setup(hass, entry)
    assert _eid(hass, entry, "binary_sensor", KEY_CONNECTIVITY) is None
    assert _eid(hass, entry, "binary_sensor", KEY_RINGING) is not None


async def test_proxy_camera(
    hass: HomeAssistant, mock_entry, aioclient_mock, source_camera
) -> None:
    """Bild und Stream der Quellkamera werden durchgereicht (so wie HomeKit sie holt)."""
    _mock_shelly(aioclient_mock)
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
    hass: HomeAssistant, mock_entry, aioclient_mock, source_camera
) -> None:
    """Marke, Modell und Streaming kommen von der Quellkamera, wenn sie geladen ist."""
    _mock_shelly(aioclient_mock)
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
