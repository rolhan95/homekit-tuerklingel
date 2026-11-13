"""Repair-Hinweise (HomeKit-Einrichtung; nach der Migration: Gong-Schalter wählen)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import SIGNAL_CONFIG_ENTRY_CHANGED, ConfigEntryChange
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, ISSUE_GONG_SELECT, ISSUE_HOMEKIT_SETUP
from .homekit import HOMEKIT_DOMAIN, async_has_homekit_accessory

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


def homekit_issue_id(entry: ConfigEntry) -> str:
    """ID des Hinweises „HomeKit-Türklingel anlegen“."""
    return f"{ISSUE_HOMEKIT_SETUP}_{entry.entry_id}"


def gong_issue_id(entry: ConfigEntry) -> str:
    """ID des Hinweises „Gong-Schalter wählen“ (aus der Migration v1 → v2)."""
    return f"{ISSUE_GONG_SELECT}_{entry.entry_id}"


@callback
def async_check_homekit_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Hinweis anlegen, solange es kein HomeKit-Zubehör für die Proxy-Kamera gibt."""
    if async_has_homekit_accessory(hass, entry):
        ir.async_delete_issue(hass, DOMAIN, homekit_issue_id(entry))
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        homekit_issue_id(entry),
        is_fixable=True,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_HOMEKIT_SETUP,
        translation_placeholders={"name": entry.title},
        data={"entry_id": entry.entry_id},
    )


async def async_check_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Hinweise nach dem Einrichten prüfen und anlegen/entfernen.

    Läuft als Hintergrund-Task nach dem Plattform-Setup; die Proxy-Kamera steht
    dann bereits in der Entity-Registry. Danach wird der HomeKit-Hinweis bei
    jeder Änderung an HomeKit-Einträgen (angelegt, geändert, gelöscht) neu
    bewertet.
    """
    async_check_homekit_issue(hass, entry)

    @callback
    def _async_entry_changed(change: ConfigEntryChange, changed: ConfigEntry) -> None:
        if changed.domain == HOMEKIT_DOMAIN:
            async_check_homekit_issue(hass, entry)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_CONFIG_ENTRY_CHANGED, _async_entry_changed)
    )


@callback
def async_remove_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Alle Hinweise dieses Entry entfernen."""
    ir.async_delete_issue(hass, DOMAIN, homekit_issue_id(entry))
    ir.async_delete_issue(hass, DOMAIN, gong_issue_id(entry))
