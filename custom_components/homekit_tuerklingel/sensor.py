"""Plattform sensor: Zeitpunkt des letzten Klingelns."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.components.sensor import RestoreSensor, SensorDeviceClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import KEY_LAST_RING
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
    """Sensor anlegen."""
    async_add_entities([LastRingSensor(entry.runtime_data)])


class LastRingSensor(TuerklingelEntity, RestoreSensor):
    """Zeitstempel des letzten (nicht entprellten) Klingelns; übersteht Neustarts."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:doorbell"

    def __init__(self, hub: TuerklingelHub) -> None:
        """Sensor anlegen."""
        super().__init__(hub, KEY_LAST_RING)
        self._attr_native_value = hub.last_ring

    async def async_added_to_hass(self) -> None:
        """Letzten Wert wiederherstellen und Ring-Listener registrieren."""
        await super().async_added_to_hass()
        if (
            self.hub.last_ring is None
            and (last := await self.async_get_last_sensor_data()) is not None
            and isinstance(last.native_value, datetime)
        ):
            self.hub.last_ring = last.native_value
        self._attr_native_value = self.hub.last_ring
        self.async_on_remove(self.hub.async_add_ring_listener(self._handle_ring))

    @callback
    def _handle_ring(self, when: datetime) -> None:
        self._attr_native_value = when
        self.async_write_ha_state()
