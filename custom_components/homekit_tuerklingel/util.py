"""Hilfsfunktionen."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url


def webhook_path(webhook_id: str) -> str:
    """Pfad des Webhooks."""
    return f"/api/webhook/{webhook_id}"


def async_get_webhook_url(hass: HomeAssistant, webhook_id: str) -> str:
    """URL des Webhooks für das auslösende Gerät (nur LAN, http).

    Bevorzugt die interne URL von Home Assistant; fällt auf die lokale IP und
    den HTTP-Port zurück. Externe/Cloud-URLs werden bewusst nicht verwendet,
    da der Webhook local_only ist.
    """
    try:
        base = get_url(
            hass,
            allow_internal=True,
            allow_external=False,
            allow_cloud=False,
            allow_ip=True,
            prefer_external=False,
        )
    except NoURLAvailableError:
        port = 8123
        if hass.config.api is not None:
            port = hass.config.api.port
        base = f"http://{hass.config.api.local_ip if hass.config.api else '<HA-IP>'}:{port}"
    return f"{base.rstrip('/')}{webhook_path(webhook_id)}"
