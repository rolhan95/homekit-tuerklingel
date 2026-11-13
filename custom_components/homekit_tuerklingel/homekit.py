"""Anbindung an die HomeKit Bridge: eigenes Zubehör (Modus „accessory“) anlegen.

Die HomeKit Bridge verknüpft beim Start eines Kamera-Zubehörs selbstständig ein
event.* mit device_class „doorbell“ auf demselben Gerät als Türklingel
(homekit.HomeKit._async_configure_linked_sensors). Es genügt daher, für die
Proxy-Kamera dieser Integration ein Zubehör im Modus „accessory“ anzulegen.

Der Weg führt über den offiziellen Config-Flow der HomeKit Bridge
(source „accessory“), den HomeKit selbst für Kameras, Schlösser usw. nutzt.
homekit ist nur after_dependency: Importe erfolgen erst in den Funktionen.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, KEY_CAMERA

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

HOMEKIT_DOMAIN = "homekit"
CONF_HOMEKIT_MODE = "mode"
"""Schlüssel des Modus in data/options (homekit.const.CONF_HOMEKIT_MODE)."""
HOMEKIT_MODE_ACCESSORY = "accessory"
HOMEKIT_START_PORT = 21064
"""Standard-Port der HomeKit Bridge; gesucht wird ab hier der nächste freie."""


class HomeKitResult(StrEnum):
    """Ergebnis von async_create_homekit_accessory."""

    CREATED = "created"
    ALREADY_EXISTS = "already_exists"
    CAMERA_MISSING = "camera_missing"
    FAILED = "homekit_failed"


@callback
def async_get_proxy_camera_entity_id(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """entity_id der eigenen Proxy-Kamera aus der Entity-Registry (oder None)."""
    return er.async_get(hass).async_get_entity_id(
        "camera", DOMAIN, f"{entry.entry_id}_{KEY_CAMERA}"
    )


def _accessory_entity_ids(data: Any) -> list[str]:
    """Eingeschlossene Entitäten eines HomeKit-Entry im Modus „accessory“."""
    if not isinstance(data, Mapping) or data.get(CONF_HOMEKIT_MODE) != HOMEKIT_MODE_ACCESSORY:
        return []
    entity_filter = data.get("filter")
    if not isinstance(entity_filter, Mapping):
        return []
    return list(entity_filter.get("include_entities") or [])


@callback
def async_homekit_accessory_entries(
    hass: HomeAssistant, camera_entity_id: str
) -> list[ConfigEntry]:
    """HomeKit-Entries im Modus „accessory“ für die Kamera (auch deaktivierte).

    Wie in HomeKit selbst gilt options vor data, sobald options den Modus enthält
    (frisch angelegte Einträge haben ihn bis zum ersten Start nur in data).
    """
    found: list[ConfigEntry] = []
    for hk_entry in hass.config_entries.async_entries(
        HOMEKIT_DOMAIN, include_ignore=False, include_disabled=True
    ):
        target = hk_entry.options if CONF_HOMEKIT_MODE in hk_entry.options else hk_entry.data
        if camera_entity_id in _accessory_entity_ids(target):
            found.append(hk_entry)
    return found


@callback
def async_has_homekit_accessory(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """True, wenn für die Proxy-Kamera der Klingel ein HomeKit-Zubehör existiert."""
    if (camera_entity_id := async_get_proxy_camera_entity_id(hass, entry)) is None:
        return False
    return bool(async_homekit_accessory_entries(hass, camera_entity_id))


async def async_create_homekit_accessory(
    hass: HomeAssistant, entry: ConfigEntry
) -> HomeKitResult:
    """HomeKit-Zubehör für die Proxy-Kamera über den HomeKit-Config-Flow anlegen.

    Der Flow legt den Entry an und richtet ihn direkt ein; die Bridge startet
    sofort (bzw. nach dem Start von Home Assistant) und meldet den Pairing-Code
    als Benachrichtigung.
    """
    camera_entity_id = async_get_proxy_camera_entity_id(hass, entry)
    if camera_entity_id is None or hass.states.get(camera_entity_id) is None:
        # Der HomeKit-Flow setzt einen vorhandenen Zustand voraus (assert).
        _LOGGER.warning(
            "%s: Proxy-Kamera noch nicht verfügbar – HomeKit-Zubehör nicht angelegt",
            entry.title,
        )
        return HomeKitResult.CAMERA_MISSING

    if async_homekit_accessory_entries(hass, camera_entity_id):
        return HomeKitResult.ALREADY_EXISTS

    try:
        from homeassistant.components.homekit.util import (
            async_find_next_available_port,
        )

        port = async_find_next_available_port(hass, HOMEKIT_START_PORT)
        result = await hass.config_entries.flow.async_init(
            HOMEKIT_DOMAIN,
            context={"source": "accessory"},
            data={"entity_id": camera_entity_id, "port": port},
        )
    except ImportError as err:
        _LOGGER.error("%s: HomeKit Bridge nicht verfügbar: %s", entry.title, err)
        return HomeKitResult.FAILED
    except Exception:
        _LOGGER.exception(
            "%s: HomeKit-Zubehör für %s konnte nicht angelegt werden",
            entry.title,
            camera_entity_id,
        )
        return HomeKitResult.FAILED

    if result.get("type") != "create_entry":
        _LOGGER.error(
            "%s: HomeKit-Flow für %s endete ohne Eintrag: %s",
            entry.title,
            camera_entity_id,
            result.get("reason", result.get("type")),
        )
        return HomeKitResult.FAILED

    _LOGGER.info(
        "%s: HomeKit-Zubehör für %s auf Port %s angelegt",
        entry.title,
        camera_entity_id,
        port,
    )
    return HomeKitResult.CREATED
