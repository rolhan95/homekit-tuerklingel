"""Repair-Hinweise (HomeKit-Einrichtung, Shelly-Eingang nicht entkoppelt).

PLATZHALTER – wird von Agent D implementiert. Signaturen nicht ändern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


async def async_check_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Hinweise nach dem Einrichten prüfen und anlegen/entfernen."""


@callback
def async_remove_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Alle Hinweise dieses Entry entfernen."""
