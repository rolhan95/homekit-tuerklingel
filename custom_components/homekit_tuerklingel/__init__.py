"""HomeKit Türklingel: beliebiger Klingel-Auslöser + Kamera als HomeKit-Video-Türklingel."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from .const import (
    CONF_ALLOWED_SOURCES,
    CONF_CAMERA_ENTITY,
    CONF_GONG_ENTITY,
    CONF_RESTRICT_IP,
    CONF_TRIGGER_ENTITIES,
    CONF_WEBHOOK_ENABLED,
    CONF_WEBHOOK_ID,
    CONFIG_VERSION,
    DOMAIN,
    ISSUE_GONG_SELECT,
    ISSUE_NOT_DETACHED_V1,
    KEY_CONNECTIVITY_V1,
    V1_ALLOWED_IP,
    V1_CONNECTIVITY,
    V1_SHELLY_HOST,
    V1_SHELLY_MAC,
)
from .hub import TuerklingelHub
from .issues import async_check_issues, async_remove_issues

_LOGGER = logging.getLogger(__name__)

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
    """Klingel einrichten."""
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


def _find_switch_for_mac(hass: HomeAssistant, mac: str | None) -> str | None:
    """switch-Entität eines Geräts mit dieser MAC (z. B. aus der Shelly-Integration).

    Geht über die Entitäten und löst deren device_id mit dev_reg.async_get auf:
    Seit HA 2026.10 kann eine Entität noch auf eine zusammengesetzte Geräte-ID
    (aufgeteiltes Gerät mehrerer Integrationen) zeigen; nur async_get liefert dafür
    das Gerät samt Verbindungen. Eine Suche über async_get_devices fände dann
    zwar das Gerät, aber keine Entitäten.
    """
    if not mac:
        return None
    wanted = (dr.CONNECTION_NETWORK_MAC, dr.format_mac(mac))
    dev_reg = dr.async_get(hass)
    switches: list[str] = []
    for entity in er.async_get(hass).entities.values():
        if entity.domain != "switch" or entity.disabled_by is not None or not entity.device_id:
            continue
        device = dev_reg.async_get(entity.device_id)
        if device is not None and wanted in device.connections:
            switches.append(entity.entity_id)
    return switches[0] if len(switches) == 1 else None


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Version 1 (Shelly Gen1 per HTTP, 0.1.x) → Version 2 (universell)."""
    if entry.version > CONFIG_VERSION:
        return False
    if entry.version == 1:
        data = dict(entry.data)
        options = dict(entry.options)
        host = data.get(V1_SHELLY_HOST)
        allowed = (options.pop(V1_ALLOWED_IP, "") or host or "").strip()
        gong = _find_switch_for_mac(hass, data.get(V1_SHELLY_MAC))

        options.pop(V1_CONNECTIVITY, None)
        options[CONF_WEBHOOK_ENABLED] = True
        options[CONF_RESTRICT_IP] = bool(options.get(CONF_RESTRICT_IP, True))
        options[CONF_ALLOWED_SOURCES] = [allowed] if allowed else []
        options[CONF_TRIGGER_ENTITIES] = []
        options[CONF_GONG_ENTITY] = gong

        new_data = {
            CONF_WEBHOOK_ID: data[CONF_WEBHOOK_ID],
            CONF_CAMERA_ENTITY: data[CONF_CAMERA_ENTITY],
        }

        ent_reg = er.async_get(hass)
        if old := ent_reg.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{entry.entry_id}_{KEY_CONNECTIVITY_V1}"
        ):
            ent_reg.async_remove(old)
        ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_NOT_DETACHED_V1}_{entry.entry_id}")
        if gong is None:
            ir.async_create_issue(
                hass,
                DOMAIN,
                f"{ISSUE_GONG_SELECT}_{entry.entry_id}",
                is_fixable=False,
                is_persistent=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_GONG_SELECT,
                translation_placeholders={"name": entry.title},
            )

        hass.config_entries.async_update_entry(
            entry, data=new_data, options=options, version=CONFIG_VERSION
        )
        _LOGGER.info(
            "%s: auf Version 2 umgestellt (Webhook bleibt, erlaubte Quelle %s, Gong %s)",
            entry.title,
            allowed or "-",
            gong or "keiner gefunden",
        )
    return True
