"""Kleiner asynchroner Client für die HTTP-API eines Shelly 1 (Gen1).

Benutzt nur lokale Aufrufe (kein Cloud-Zugriff):
- GET /shelly              Geräteinfo, immer ohne Anmeldung abrufbar
- GET /settings            Einstellungen, ggf. mit Basic-Auth
- GET /relay/0?turn=on&timer=<s>   Relais für <s> Sekunden einschalten
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import logging
from typing import Any

import aiohttp

from .const import SHELLY_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class ShellyError(Exception):
    """Allgemeiner Fehler bei der Kommunikation mit dem Shelly."""


class ShellyConnectionError(ShellyError):
    """Shelly nicht erreichbar oder ungültige Antwort."""


class ShellyAuthError(ShellyError):
    """Shelly lehnt die Zugangsdaten ab (HTTP 401)."""


@dataclass(slots=True)
class ShellyInfo:
    """Ausgewählte Angaben aus /shelly und /settings."""

    mac: str
    model: str
    firmware: str | None
    auth_required: bool
    btn_type: str | None = None
    """Eingangsmodus von Relais 0, z. B. 'detached', 'momentary', 'toggle'."""

    @property
    def detached(self) -> bool | None:
        """True, wenn der Eingang vom Relais entkoppelt ist (None = unbekannt)."""
        if self.btn_type is None:
            return None
        return self.btn_type == "detached"


def format_timer(seconds: float) -> str:
    """Impulsdauer für den Parameter 'timer' formatieren (max. 1 Nachkommastelle)."""
    value = round(float(seconds), 1)
    if value.is_integer():
        return str(int(value))
    return f"{value:.1f}"


class ShellyGen1Client:
    """Zugriff auf einen Shelly Gen1 im lokalen Netz."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        """Client anlegen. host ist IP oder Hostname ohne Schema."""
        self._session = session
        self.host = host.strip()
        self._headers: dict[str, str] = {}
        if username:
            token = base64.b64encode(f"{username}:{password or ''}".encode()).decode()
            self._headers["Authorization"] = f"Basic {token}"

    @property
    def base_url(self) -> str:
        """Basis-URL des Geräts."""
        return f"http://{self.host}"

    async def _get(
        self, path: str, params: dict[str, str] | None = None, *, auth: bool = True
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with asyncio.timeout(SHELLY_TIMEOUT):
                async with self._session.get(
                    url,
                    params=params,
                    headers=self._headers if auth else None,
                ) as resp:
                    if resp.status == 401:
                        raise ShellyAuthError(f"{path}: Anmeldung abgelehnt")
                    if resp.status != 200:
                        raise ShellyConnectionError(f"{path}: HTTP {resp.status}")
                    data = await resp.json(content_type=None)
        except ShellyError:
            raise
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            raise ShellyConnectionError(f"{path}: {err!r}") from err
        if not isinstance(data, dict):
            raise ShellyConnectionError(f"{path}: unerwartete Antwort")
        return data

    async def async_get_info(self, *, with_settings: bool = True) -> ShellyInfo:
        """Geräteinfo lesen; mit with_settings zusätzlich den Eingangsmodus.

        Wirft ShellyAuthError, wenn /settings Zugangsdaten verlangt und die
        hinterlegten falsch sind oder fehlen.
        """
        data = await self._get("/shelly", auth=False)
        mac = str(data.get("mac", "")).upper()
        if not mac:
            raise ShellyConnectionError("/shelly: keine MAC-Adresse – kein Shelly Gen1?")
        info = ShellyInfo(
            mac=mac,
            model=str(data.get("type", "unbekannt")),
            firmware=data.get("fw"),
            auth_required=bool(data.get("auth", False)),
        )
        if with_settings:
            settings = await self._get("/settings")
            relays = settings.get("relays") or []
            if relays and isinstance(relays[0], dict):
                info.btn_type = relays[0].get("btn_type")
        return info

    async def async_ping(self) -> bool:
        """True, wenn /shelly antwortet."""
        try:
            await self._get("/shelly", auth=False)
        except ShellyError:
            return False
        return True

    async def async_pulse(self, seconds: float) -> None:
        """Relais 0 für die angegebene Dauer einschalten (Gong-Impuls)."""
        await self._get(
            "/relay/0", {"turn": "on", "timer": format_timer(seconds)}
        )
