"""HomeKit Türklingel: Shelly-1-Klingel + Kamera als HomeKit-Video-Türklingel."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .hub import TuerklingelHub
from .issues import async_check_issues, async_remove_issues

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CAMERA,
    Platform.EVENT,
    Platform.IMAGE,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

type TuerklingelConfigEntry = ConfigEntry[TuerklingelHub]


async def async_setup_entry(hass: HomeAssistant, entry: TuerklingelConfigEntry) -> bool:
    """Klingel einrichten.

    Ein nicht erreichbarer Shelly verhindert die Einrichtung bewusst nicht:
    Der Webhook (Klingeln) funktioniert unabhängig vom Relais.
    """
    hub = TuerklingelHub(hass, entry)
    entry.runtime_data = hub
    await hub.async_setup()
    entry.async_on_unload(hub.async_unload)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entry.async_create_background_task(
        hass, async_check_issues(hass, entry), "tuerklingel_issues"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TuerklingelConfigEntry) -> bool:
    """Klingel entladen."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: TuerklingelConfigEntry) -> None:
    """Beim Löschen offene Repair-Hinweise entfernen."""
    async_remove_issues(hass, entry)


async def _async_update_listener(hass: HomeAssistant, entry: TuerklingelConfigEntry) -> None:
    """Optionen geändert → neu laden."""
    await hass.config_entries.async_reload(entry.entry_id)
