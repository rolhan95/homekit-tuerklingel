"""Plattform image: Snapshot des letzten Klingelns (auch als Push-Anhang)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import KEY_SNAPSHOT
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
    """Bild-Entität anlegen."""
    async_add_entities([SnapshotImage(hass, entry.runtime_data)])


class SnapshotImage(TuerklingelEntity, ImageEntity):
    """Standbild, das der Hub beim Klingeln von der Kamera holt."""

    _attr_content_type = "image/jpeg"

    def __init__(self, hass: HomeAssistant, hub: TuerklingelHub) -> None:
        """Entität anlegen (ImageEntity braucht hass für Zugriffstoken/HTTP)."""
        TuerklingelEntity.__init__(self, hub, KEY_SNAPSHOT)
        ImageEntity.__init__(self, hass)
        self._attr_image_last_updated = hub.snapshot_time

    async def async_added_to_hass(self) -> None:
        """Snapshot-Listener registrieren und Entitäts-ID im Hub hinterlegen."""
        await super().async_added_to_hass()
        self.hub.image_entity_id = self.entity_id
        self.async_on_remove(self._clear_entity_id)
        self.async_on_remove(
            self.hub.async_add_snapshot_listener(self._handle_snapshot)
        )

    @callback
    def _clear_entity_id(self) -> None:
        if self.hub.image_entity_id == self.entity_id:
            self.hub.image_entity_id = None

    @callback
    def _handle_snapshot(self) -> None:
        self._attr_image_last_updated = self.hub.snapshot_time
        self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        """Gespeicherten Snapshot liefern."""
        return self.hub.snapshot
