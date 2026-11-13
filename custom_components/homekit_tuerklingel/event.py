"""Plattform event: das Klingel-Event (device_class doorbell) für HomeKit."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import EVENT_TYPE_RING, KEY_EVENT
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
    """Event-Entität anlegen."""
    async_add_entities([TuerklingelEvent(entry.runtime_data)])


class TuerklingelEvent(TuerklingelEntity, EventEntity):
    """Klingel-Event; die HomeKit Bridge macht daraus den Türklingel-Taster."""

    _attr_device_class = EventDeviceClass.DOORBELL
    _attr_event_types = [EVENT_TYPE_RING]  # noqa: RUF012

    def __init__(self, hub: TuerklingelHub) -> None:
        """Event-Entität anlegen."""
        super().__init__(hub, KEY_EVENT)

    async def async_added_to_hass(self) -> None:
        """Ring-Listener registrieren (letzten Zustand stellt EventEntity selbst her)."""
        await super().async_added_to_hass()
        self.async_on_remove(self.hub.async_add_ring_listener(self._handle_ring))

    @callback
    def _handle_ring(self, _when: datetime) -> None:
        self._trigger_event(EVENT_TYPE_RING)
        self.async_write_ha_state()
