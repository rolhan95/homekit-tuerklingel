"""Zentrale Logik einer Klingel: Webhook, Entprellung, Gong, Snapshot, Push."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.components import camera, webhook
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
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
    CONF_SHELLY_PASSWORD,
    CONF_SHELLY_USERNAME,
    CONF_WEBHOOK_ID,
    CONNECTIVITY_INTERVAL,
    DEFAULT_AUTO_OFF,
    DEFAULT_CONNECTIVITY,
    DEFAULT_COOLDOWN,
    DEFAULT_GONG_DURATION,
    DEFAULT_GONG_ENABLED,
    DEFAULT_NOTIFY_ENABLED,
    DEFAULT_NOTIFY_MESSAGE,
    DEFAULT_NOTIFY_TITLE,
    DEFAULT_RESTRICT_IP,
    DOMAIN,
    SNAPSHOT_TIMEOUT,
    WEBHOOK_METHODS,
)
from .shelly import ShellyAuthError, ShellyError, ShellyGen1Client

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

RingListener = Callable[[datetime], None]
UpdateListener = Callable[[], None]


def _normalize_ip(value: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
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


class TuerklingelHub:
    """Laufzeitobjekt einer Klingel (entry.runtime_data)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Hub aus den Daten des Config-Entry anlegen."""
        self.hass = hass
        self.entry = entry
        data = entry.data
        self.webhook_id: str = data[CONF_WEBHOOK_ID]
        self.camera_entity_id: str = data[CONF_CAMERA_ENTITY]
        self.client = ShellyGen1Client(
            async_get_clientsession(hass),
            data[CONF_SHELLY_HOST],
            data.get(CONF_SHELLY_USERNAME) or None,
            data.get(CONF_SHELLY_PASSWORD) or None,
        )

        # Über switch-/number-Entitäten gesetzt (dort wiederhergestellt)
        self.gong_enabled: bool = DEFAULT_GONG_ENABLED
        self.cooldown: float = DEFAULT_COOLDOWN
        self.gong_duration: float = DEFAULT_GONG_DURATION

        # Zustand
        self.last_ring: datetime | None = None
        self._last_ring_mono: float | None = None
        self.snapshot: bytes | None = None
        self.snapshot_time: datetime | None = None
        self.shelly_available: bool | None = None
        self.image_entity_id: str | None = None
        """Wird von der image-Entität gesetzt (für den Push-Anhang)."""

        self.stats: dict[str, Any] = {
            "webhook_calls": 0,
            "rings": 0,
            "debounced": 0,
            "rejected_ip": 0,
            "gong_pulses": 0,
            "gong_errors": 0,
            "snapshot_errors": 0,
            "notify_errors": 0,
            "last_call": None,
        }

        self._allowed_ips: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
        self._ring_listeners: list[RingListener] = []
        self._snapshot_listeners: list[UpdateListener] = []
        self._availability_listeners: list[UpdateListener] = []
        self._unsub_poll: CALLBACK_TYPE | None = None
        self._webhook_registered = False

    # ------------------------------------------------------------------ Optionen
    def _opt(self, key: str, default: Any) -> Any:
        return self.entry.options.get(key, default)

    @property
    def name(self) -> str:
        """Name der Klingel (Titel des Entry)."""
        return self.entry.title

    @property
    def restrict_ip(self) -> bool:
        """Nur Aufrufe von der erlaubten IP annehmen."""
        return bool(self._opt(CONF_RESTRICT_IP, DEFAULT_RESTRICT_IP))

    @property
    def allowed_host(self) -> str:
        """Erlaubte Quelle (IP oder Hostname); Standard ist die Shelly-Adresse."""
        return (self._opt(CONF_ALLOWED_IP, "") or self.entry.data[CONF_SHELLY_HOST]).strip()

    @property
    def auto_off(self) -> int:
        """Sekunden bis der Binärsensor 'Klingelt' wieder aus geht."""
        return int(self._opt(CONF_AUTO_OFF, DEFAULT_AUTO_OFF))

    @property
    def connectivity_enabled(self) -> bool:
        """Erreichbarkeit des Shelly prüfen."""
        return bool(self._opt(CONF_CONNECTIVITY, DEFAULT_CONNECTIVITY))

    # ------------------------------------------------------------- Lebenszyklus
    async def async_setup(self) -> None:
        """Webhook registrieren und ggf. die Erreichbarkeitsprüfung starten."""
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
        if self.connectivity_enabled:
            self.entry.async_create_background_task(
                self.hass, self.async_update_availability(), "tuerklingel_ping"
            )
            self._unsub_poll = async_track_time_interval(
                self.hass,
                self._async_poll,
                timedelta(seconds=CONNECTIVITY_INTERVAL),
                name="tuerklingel_ping",
            )

    @callback
    def async_unload(self) -> None:
        """Webhook abmelden und Timer beenden."""
        if self._webhook_registered:
            webhook.async_unregister(self.hass, self.webhook_id)
            self._webhook_registered = False
        if self._unsub_poll is not None:
            self._unsub_poll()
            self._unsub_poll = None

    async def _async_resolve_allowed(self) -> None:
        """Erlaubte Quell-IP(s) bestimmen; Hostnamen einmalig auflösen."""
        host = self.allowed_host
        self._allowed_ips = set()
        if (addr := _normalize_ip(host)) is not None:
            self._allowed_ips.add(addr)
            return
        try:
            infos = await self.hass.loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except OSError as err:
            _LOGGER.warning(
                "%s: erlaubte Quelle %s nicht auflösbar (%s) – IP-Filter lässt nichts durch",
                self.name,
                host,
                err,
            )
            return
        for info in infos:
            if (addr := _normalize_ip(str(info[4][0]))) is not None:
                self._allowed_ips.add(addr)

    def ip_allowed(self, remote: str | None) -> bool:
        """Prüfen, ob die Quell-IP den Webhook auslösen darf."""
        if not self.restrict_ip:
            return True
        addr = _normalize_ip(remote)
        return addr is not None and addr in self._allowed_ips

    # ------------------------------------------------------------------ Webhook
    async def _async_handle_webhook(
        self, hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        """Webhook-Aufruf des Shelly (GET oder POST)."""
        t0 = time.monotonic()
        remote = request.remote
        method = request.method
        self.stats["webhook_calls"] += 1
        self.stats["last_call"] = {
            "time": dt_util.utcnow().isoformat(),
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
                self.allowed_host,
            )
            return web.Response(status=403, text="forbidden")

        rang = self.async_ring(source=f"Webhook {method} von {remote}", started=t0)
        self.stats["last_call"]["result"] = "ring" if rang else "debounced"
        return web.Response(status=200, text="ok" if rang else "debounced")

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
        """Mechanischen Gong pulsen, falls eingeschaltet."""
        if not self.gong_enabled:
            _LOGGER.debug("%s: Gong stumm geschaltet", self.name)
            return
        try:
            await self.client.async_pulse(self.gong_duration)
        except ShellyAuthError:
            self.stats["gong_errors"] += 1
            _LOGGER.error(
                "%s: Shelly lehnt die Zugangsdaten ab – Gong nicht ausgelöst", self.name
            )
            self.entry.async_start_reauth(self.hass)
        except ShellyError as err:
            self.stats["gong_errors"] += 1
            _LOGGER.warning("%s: Gong konnte nicht ausgelöst werden: %s", self.name, err)
        else:
            self.stats["gong_pulses"] += 1
            _LOGGER.debug("%s: Gong %.1f s gepulst", self.name, self.gong_duration)

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

    # ------------------------------------------------------------ Erreichbarkeit
    async def _async_poll(self, _now: datetime) -> None:
        await self.async_update_availability()

    async def async_update_availability(self) -> None:
        """Shelly anpingen und Änderungen melden (einmalig loggen)."""
        available = await self.client.async_ping()
        if available == self.shelly_available:
            return
        if available:
            if self.shelly_available is False:
                _LOGGER.info("%s: Shelly %s wieder erreichbar", self.name, self.client.host)
        else:
            _LOGGER.info("%s: Shelly %s nicht erreichbar", self.name, self.client.host)
        self.shelly_available = available
        for listener in list(self._availability_listeners):
            listener()

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

    @callback
    def async_add_availability_listener(self, listener: UpdateListener) -> CALLBACK_TYPE:
        """Listener für die Shelly-Erreichbarkeit registrieren."""
        self._availability_listeners.append(listener)
        return lambda: self._availability_listeners.remove(listener)
