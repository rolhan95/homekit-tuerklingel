"""Plattform binary_sensor: „Klingelt“ und „Shelly erreichbar“."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import KEY_CONNECTIVITY, KEY_RINGING
from .entity import TuerklingelEntity
from .hub import TuerklingelHub

if TYPE_CHECKING:
    from . import TuerklingelConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TuerklingelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Binärsensoren anlegen; Erreichbarkeit nur, wenn die Prüfung aktiv ist."""
    hub = entry.runtime_data
    entities: list[BinarySensorEntity] = [RingingBinarySensor(hub)]
    if hub.connectivity_enabled:
        entities.append(ConnectivityBinarySensor(hub))
    async_add_entities(entities)


class RingingBinarySensor(TuerklingelEntity, BinarySensorEntity):
    """An für hub.auto_off Sekunden nach jedem Klingeln (für Automationen)."""

    _attr_icon = "mdi:bell-ring"
    _attr_is_on = False

    def __init__(self, hub: TuerklingelHub) -> None:
        """Sensor anlegen."""
        super().__init__(hub, KEY_RINGING)
        self._unsub_off: CALLBACK_TYPE | None = None

    async def async_added_to_hass(self) -> None:
        """Ring-Listener registrieren, Timer beim Entfernen abbrechen."""
        await super().async_added_to_hass()
        self.async_on_remove(self.hub.async_add_ring_listener(self._handle_ring))
        self.async_on_remove(self._cancel_timer)

    @callback
    def _cancel_timer(self) -> None:
        if self._unsub_off is not None:
            self._unsub_off()
            self._unsub_off = None

    @callback
    def _handle_ring(self, _when: datetime) -> None:
        # Bei erneutem Klingeln den Ausschalt-Timer neu starten
        self._cancel_timer()
        self._attr_is_on = True
        self.async_write_ha_state()
        self._unsub_off = async_call_later(self.hass, self.hub.auto_off, self._turn_off)

    @callback
    def _turn_off(self, _now: datetime) -> None:
        self._unsub_off = None
        self._attr_is_on = False
        self.async_write_ha_state()


class ConnectivityBinarySensor(TuerklingelEntity, BinarySensorEntity):
    """Erreichbarkeit des Shelly (HTTP-Ping des Hubs)."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub: TuerklingelHub) -> None:
        """Sensor anlegen."""
        super().__init__(hub, KEY_CONNECTIVITY)

    @property
    def is_on(self) -> bool | None:
        """Erreichbar; None (unbekannt), solange noch nicht geprüft."""
        return self.hub.shelly_available

    async def async_added_to_hass(self) -> None:
        """Listener für Erreichbarkeitsänderungen registrieren."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hub.async_add_availability_listener(self.async_write_ha_state)
        )
