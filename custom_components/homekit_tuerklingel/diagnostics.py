"""Diagnosedaten einer Klingel (Webhook-ID und erlaubte Quellen geschwärzt)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_ALLOWED_SOURCES, CONF_WEBHOOK_ID
from .homekit import async_get_proxy_camera_entity_id, async_homekit_accessory_entries
from .util import async_get_webhook_url

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

# Erlaubte Quellen sind zwar lokale Adressen, verraten aber den Netzaufbau.
# "remote" (Quell-IP des letzten Webhook-Aufrufs) aus demselben Grund.
TO_REDACT = {
    CONF_WEBHOOK_ID,
    CONF_ALLOWED_SOURCES,
    "remote",
    "unique_id",
}


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Diagnosedaten für den Config-Entry."""
    proxy_camera = async_get_proxy_camera_entity_id(hass, entry)
    homekit_entries = (
        async_homekit_accessory_entries(hass, proxy_camera) if proxy_camera else []
    )
    diag: dict[str, Any] = {
        "entry": async_redact_data(
            {
                "title": entry.title,
                "unique_id": entry.unique_id,
                "version": entry.version,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            TO_REDACT,
        ),
        "webhook_url": async_get_webhook_url(hass, REDACTED),
        "proxy_camera_entity_id": proxy_camera,
        "homekit": {
            "accessory_exists": bool(homekit_entries),
            "entries": [
                {
                    "title": hk.title,
                    "state": str(hk.state),
                    "disabled_by": hk.disabled_by,
                }
                for hk in homekit_entries
            ],
        },
    }

    hub = getattr(entry, "runtime_data", None)
    if hub is None:
        diag["hub"] = None
        return diag

    diag["hub"] = {
        "camera_entity_id": hub.camera_entity_id,
        "webhook_enabled": hub.webhook_enabled,
        "restrict_ip": hub.restrict_ip,
        "allowed_sources": REDACTED if hub.allowed_sources else [],
        "allowed_sources_count": len(hub.allowed_sources),
        "trigger_entities": hub.trigger_entities,
        "gong_entity_id": hub.gong_entity_id,
        "gong_enabled": hub.gong_enabled,
        "cooldown": hub.cooldown,
        "gong_duration": hub.gong_duration,
        "last_ring": _iso(hub.last_ring),
        "snapshot": {
            "present": hub.snapshot is not None,
            "size": len(hub.snapshot) if hub.snapshot is not None else 0,
            "time": _iso(hub.snapshot_time),
        },
        "image_entity_id": hub.image_entity_id,
        "event_entity_id": hub.event_entity_id,
        "stats": async_redact_data(dict(hub.stats), TO_REDACT),
    }
    return diag
