"""Basisklasse der Entitäten."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONF_SHELLY_HOST, DOMAIN
from .hub import TuerklingelHub


def device_info(hub: TuerklingelHub) -> DeviceInfo:
    """Geräteinfo der Klingel; alle Entitäten (inkl. Kamera) hängen daran.

    Wichtig für HomeKit: Die HomeKit Bridge verknüpft ein event.* mit
    device_class 'doorbell' automatisch mit einer Kamera auf demselben Gerät.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, hub.entry.entry_id)},
        name=hub.name,
        manufacturer="HomeKit Türklingel",
        model="Shelly 1 (Gen1) + Kamera",
        configuration_url=f"http://{hub.entry.data[CONF_SHELLY_HOST]}",
    )


class TuerklingelEntity(Entity):
    """Gemeinsame Eigenschaften aller Entitäten einer Klingel."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: TuerklingelHub, key: str) -> None:
        """Entität mit Schlüssel (translation_key, unique_id-Suffix) anlegen."""
        self.hub = hub
        self._attr_translation_key = key
        self._attr_unique_id = f"{hub.entry.entry_id}_{key}"
        self._attr_device_info = device_info(hub)
