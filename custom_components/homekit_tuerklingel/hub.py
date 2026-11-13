"""Zentrale Logik einer Klingel: Auslöser, Entprellung, Gong, Snapshot, Push.

Auslöser (beliebig kombinierbar):
- Webhook (GET/POST, nur LAN), optional nur von bestimmten Quell-IPs
- HA-Entitäten: binary_sensor/input_boolean (Wechsel auf 'on'),
  event/button/input_button (jedes neue Ereignis bzw. jeder Druck)

Gong (optional): beliebige switch-Entität, die für die Impulsdauer eingeschaltet wird.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.components import camera, webhook
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
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
    DEFAULT_AUTO_OFF,
    DEFAULT_COOLDOWN,
    DEFAULT_GONG_DURATION,
    DEFAULT_GONG_ENABLED,
    DEFAULT_NOTIFY_ENABLED,
    DEFAULT_NOTIFY_MESSAGE,
    DEFAULT_NOTIFY_TITLE,
    DEFAULT_RESTRICT_IP,
    DEFAULT_WEBHOOK_ENABLED,
    DOMAIN,
    SNAPSHOT_TIMEOUT,
    WEBHOOK_METHODS,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

RingListener = Callable[[datetime], None]
UpdateListener = Callable[[], None]

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# Domains, bei denen jede neue Zustandsänderung ein Klingeln ist (Zeitstempel-Zustand)
_STATELESS_DOMAINS = ("event", "button", "input_button")


def normalize_ip(value: str | None) -> IPAddress | None:
    """IP-Adresse parsen; IPv4-gemappte IPv6-Adressen auf IPv4 abbilden."""
    if not value:
        return None
    try:
        addr = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def is_ring_transition(entity_id: str, old_state: Any, new_state: Any) -> bool:
    """Ist dieser Zustandswechsel einer Auslöser-Entität ein Klingeln?

    - event/button/input_button: jeder neue gültige Zustand, sofern es vorher
      einen gültigen (nicht 'unavailable') Zustand gab – so klingelt es nicht,
      wenn die Entität nur verfügbar wird (gleiche Logik wie die HomeKit Bridge).
    - binary_sensor/input_boolean: Wechsel von 'off' (oder anderem) auf 'on',
      nicht aber von 'unavailable'/'unknown' auf 'on' (z. B. nach Neustart).
    """
    if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return False
    if old_state is None or old_state.state == STATE_UNAVAILABLE:
        return False
    if entity_id.split(".", 1)[0] in _STATELESS_DOMAINS:
        return new_state.state != old_state.state
    if old_state.state == STATE_UNKNOWN:
        return False
    return new_state.state == STATE_ON and old_state.state != STATE_ON


class TuerklingelHub:
    """Laufzeitobjekt einer Klingel (entry.runtime_data)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Hub aus den Daten des Config-Entry anlegen."""
        self.hass = hass
        self.entry = entry
        self.webhook_id: str = entry.data[CONF_WEBHOOK_ID]
        self.camera_entity_id: str = entry.data[CONF_CAMERA_ENTITY]

        # Über switch-/number-Entitäten gesetzt (dort wiederhergestellt)
        self.gong_enabled: bool = DEFAULT_GONG_ENABLED
        self.cooldown: float = DEFAULT_COOLDOWN
        self.gong_duration: float = DEFAULT_GONG_DURATION

        # Zustand
        self.last_ring: datetime | None = None
        self._last_ring_mono: float | None = None
        self.snapshot: bytes | None = None
        self.snapshot_time: datetime | None = None
        self.image_entity_id: str | None = None
        """Wird von der image-Entität gesetzt (für den Push-Anhang)."""
        self.event_entity_id: str | None = None
        """Wird von der event-Entität gesetzt (Schutz vor Schleifen)."""

        self.stats: dict[str, Any] = {
            "webhook_calls": 0,
            "entity_triggers": 0,
            "rings": 0,
            "debounced": 0,
            "rejected_ip": 0,
            "gong_pulses": 0,
            "gong_errors": 0,
            "snapshot_errors": 0,
            "notify_errors": 0,
            "last_call": None,
        }

        self._allowed_ips: set[IPAddress] = set()
        self._ring_listeners: list[RingListener] = []
        self._snapshot_listeners: list[UpdateListener] = []
        self._unsub_triggers: CALLBACK_TYPE | None = None
        self._webhook_registered = False
        self._gong_lock = asyncio.Lock()

    # ------------------------------------------------------------------ Optionen
    def _opt(self, key: str, default: Any) -> Any:
        return self.entry.options.get(key, default)

    @property
    def name(self) -> str:
        """Name der Klingel (Titel des Entry)."""
        return self.entry.title

    @property
    def webhook_enabled(self) -> bool:
        """Klingeln per Webhook annehmen."""
        return bool(self._opt(CONF_WEBHOOK_ENABLED, DEFAULT_WEBHOOK_ENABLED))

    @property
    def restrict_ip(self) -> bool:
        """Nur Aufrufe von den erlaubten Quellen annehmen."""
        return bool(self._opt(CONF_RESTRICT_IP, DEFAULT_RESTRICT_IP))

    @property
    def allowed_sources(self) -> list[str]:
        """Erlaubte Quellen (IP-Adressen oder Hostnamen)."""
        return [str(s).strip() for s in self._opt(CONF_ALLOWED_SOURCES, []) or [] if str(s).strip()]

    @property
    def trigger_entities(self) -> list[str]:
        """Auslöser-Entitäten."""
        return list(self._opt(CONF_TRIGGER_ENTITIES, []) or [])

    @property
    def gong_entity_id(self) -> str | None:
        """switch-Entität des mechanischen Gongs (None = kein Gong)."""
        return self._opt(CONF_GONG_ENTITY, None) or None

    @property
    def auto_off(self) -> int:
        """Sekunden bis der Binärsensor 'Klingelt' wieder aus geht."""
        return int(self._opt(CONF_AUTO_OFF, DEFAULT_AUTO_OFF))

    # ------------------------------------------------------------- Lebenszyklus
    async def async_setup(self) -> None:
        """Webhook registrieren und Auslöser-Entitäten beobachten."""
        if self.webhook_enabled:
            await self._async_resolve_allowed()
            webhook.async_register(
                self.hass,
                DOMAIN,
                self.name,
                self.webhook_id,
                self._async_handle_webhook,
                local_only=True,
                allowed_methods=WEBHOOK_METHODS,
            )
            self._webhook_registered = True
        if self.trigger_entities:
            self._unsub_triggers = async_track_state_change_event(
                self.hass, self.trigger_entities, self._async_trigger_changed
            )

    @callback
    def async_unload(self) -> None:
        """Webhook abmelden und Beobachtung beenden."""
        if self._webhook_registered:
            webhook.async_unregister(self.hass, self.webhook_id)
            self._webhook_registered = False
        if self._unsub_triggers is not None:
            self._unsub_triggers()
            self._unsub_triggers = None

    async def _async_resolve_allowed(self) -> None:
        """Erlaubte Quell-IPs bestimmen; Hostnamen einmalig auflösen."""
        self._allowed_ips = set()
        for host in self.allowed_sources:
            if (addr := normalize_ip(host)) is not None:
                self._allowed_ips.add(addr)
                continue
            try:
                infos = await self.hass.loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            except OSError as err:
                _LOGGER.warning(
                    "%s: erlaubte Quelle %s nicht auflösbar (%s)", self.name, host, err
                )
                continue
            for info in infos:
                if (addr := normalize_ip(str(info[4][0]))) is not None:
                    self._allowed_ips.add(addr)

    def ip_allowed(self, remote: str | None) -> bool:
        """Prüfen, ob die Quell-IP den Webhook auslösen darf."""
        if not self.restrict_ip:
            return True
        addr = normalize_ip(remote)
        return addr is not None and addr in self._allowed_ips

    # ------------------------------------------------------------------ Webhook
    async def _async_handle_webhook(
        self, hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        """Webhook-Aufruf (GET oder POST)."""
        t0 = time.monotonic()
        remote = request.remote
        method = request.method
        self.stats["webhook_calls"] += 1
        self.stats["last_call"] = {
            "time": dt_util.utcnow().isoformat(),
            "source": "webhook",
            "method": method,
            "remote": remote,
        }
        _LOGGER.debug("%s: Webhook %s von %s", self.name, method, remote)

        if not self.ip_allowed(remote):
            self.stats["rejected_ip"] += 1
            self.stats["last_call"]["result"] = "ip_rejected"
            _LOGGER.warning(
                "%s: Webhook-Aufruf von %s abgelehnt (erlaubt: %s)",
                self.name,
                remote,
                ", ".join(self.allowed_sources) or "-",
            )
            return web.Response(status=403, text="forbidden")

        rang = self.async_ring(source=f"Webhook {method} von {remote}", started=t0)
        self.stats["last_call"]["result"] = "ring" if rang else "debounced"
        return web.Response(status=200, text="ok" if rang else "debounced")

    # ------------------------------------------------------- Auslöser-Entitäten
    @callback
    def _async_trigger_changed(self, event: Event[EventStateChangedData]) -> None:
        t0 = time.monotonic()
        entity_id = event.data["entity_id"]
        if entity_id == self.event_entity_id:
            return
        if not is_ring_transition(entity_id, event.data["old_state"], event.data["new_state"]):
            return
        self.stats["entity_triggers"] += 1
        self.stats["last_call"] = {
            "time": dt_util.utcnow().isoformat(),
            "source": "entity",
            "entity_id": entity_id,
        }
        rang = self.async_ring(source=f"Entität {entity_id}", started=t0)
        self.stats["last_call"]["result"] = "ring" if rang else "debounced"

    # ----------------------------------------------------------------- Klingeln
    @callback
    def async_ring(self, source: str = "manuell", started: float | None = None) -> bool:
        """Klingeln auslösen. False, wenn es durch die Entprellung verworfen wurde."""
        now = time.monotonic()
        if (
            self._last_ring_mono is not None
            and now - self._last_ring_mono < self.cooldown
        ):
            self.stats["debounced"] += 1
            _LOGGER.debug(
                "%s: %s verworfen (Entprellung, %.2f s seit letztem Klingeln < %.1f s)",
                self.name,
                source,
                now - self._last_ring_mono,
                self.cooldown,
            )
            return False

        self._last_ring_mono = now
        self.last_ring = dt_util.utcnow()
        self.stats["rings"] += 1
        for listener in list(self._ring_listeners):
            listener(self.last_ring)
        latency_ms = (time.monotonic() - (started if started is not None else now)) * 1000
        _LOGGER.debug(
            "%s: Klingeln (%s), Event nach %.1f ms ausgelöst", self.name, source, latency_ms
        )
        self.entry.async_create_background_task(
            self.hass, self._async_after_ring(), f"tuerklingel_{self.entry.entry_id}_ring"
        )
        return True

    async def _async_after_ring(self) -> None:
        """Gong, Snapshot und Push parallel abarbeiten."""
        await asyncio.gather(self.async_gong(), self._async_snapshot_and_notify())

    async def async_gong(self) -> None:
        """Gong-Schalter für die Impulsdauer einschalten (falls konfiguriert und aktiv)."""
        gong = self.gong_entity_id
        if gong is None:
            return
        if not self.gong_enabled:
            _LOGGER.debug("%s: Gong stumm geschaltet", self.name)
            return
        if self._gong_lock.locked():
            _LOGGER.debug("%s: Gong läuft bereits", self.name)
            return
        async with self._gong_lock:
            try:
                await self.hass.services.async_call(
                    "switch", "turn_on", {"entity_id": gong}, blocking=True
                )
            except (HomeAssistantError, ValueError) as err:
                self.stats["gong_errors"] += 1
                _LOGGER.warning("%s: Gong %s nicht einschaltbar: %s", self.name, gong, err)
                return
            try:
                await asyncio.sleep(self.gong_duration)
            finally:
                # Auch beim Entladen/Abbruch sicher wieder ausschalten
                await asyncio.shield(self._async_gong_off(gong))
            self.stats["gong_pulses"] += 1
            _LOGGER.debug("%s: Gong %s %.1f s gepulst", self.name, gong, self.gong_duration)

    async def _async_gong_off(self, gong: str) -> None:
        try:
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": gong}, blocking=True
            )
        except (HomeAssistantError, ValueError) as err:
            self.stats["gong_errors"] += 1
            _LOGGER.warning("%s: Gong %s nicht ausschaltbar: %s", self.name, gong, err)

    async def _async_snapshot_and_notify(self) -> None:
        await self.async_take_snapshot()
        await self.async_notify()

    async def async_take_snapshot(self) -> None:
        """Standbild der Kamera speichern."""
        try:
            image = await camera.async_get_image(
                self.hass, self.camera_entity_id, timeout=SNAPSHOT_TIMEOUT
            )
        except HomeAssistantError as err:
            self.stats["snapshot_errors"] += 1
            _LOGGER.warning(
                "%s: Snapshot von %s fehlgeschlagen: %s",
                self.name,
                self.camera_entity_id,
                err,
            )
            return
        self.snapshot = image.content
        self.snapshot_time = dt_util.utcnow()
        for listener in list(self._snapshot_listeners):
            listener()

    def _notify_payload(self) -> dict[str, Any]:
        title = str(self._opt(CONF_NOTIFY_TITLE, DEFAULT_NOTIFY_TITLE) or DEFAULT_NOTIFY_TITLE)
        message = str(
            self._opt(CONF_NOTIFY_MESSAGE, DEFAULT_NOTIFY_MESSAGE) or DEFAULT_NOTIFY_MESSAGE
        ).replace("{name}", self.name)
        extra: dict[str, Any] = {
            "tag": f"{DOMAIN}_{self.entry.entry_id}",
            "push": {"interruption-level": "time-sensitive"},
        }
        if self.image_entity_id and self.snapshot is not None:
            extra["image"] = f"/api/image_proxy/{self.image_entity_id}"
        return {"title": title, "message": message, "data": extra}

    async def async_notify(self) -> None:
        """Push an die gewählten notify-Dienste senden (optional)."""
        if not self._opt(CONF_NOTIFY_ENABLED, DEFAULT_NOTIFY_ENABLED):
            return
        services: list[str] = list(self._opt(CONF_NOTIFY_SERVICES, []) or [])
        if not services:
            return
        payload = self._notify_payload()
        for service in services:
            svc = service.removeprefix("notify.")
            try:
                await self.hass.services.async_call("notify", svc, payload, blocking=True)
            except (HomeAssistantError, ValueError) as err:
                self.stats["notify_errors"] += 1
                _LOGGER.warning("%s: Push über notify.%s fehlgeschlagen: %s", self.name, svc, err)

    # ---------------------------------------------------------------- Listener
    @callback
    def async_add_ring_listener(self, listener: RingListener) -> CALLBACK_TYPE:
        """Listener für Klingeln registrieren; gibt die Abmeldefunktion zurück."""
        self._ring_listeners.append(listener)
        return lambda: self._ring_listeners.remove(listener)

    @callback
    def async_add_snapshot_listener(self, listener: UpdateListener) -> CALLBACK_TYPE:
        """Listener für neue Snapshots registrieren."""
        self._snapshot_listeners.append(listener)
        return lambda: self._snapshot_listeners.remove(listener)
