"""Plattform switch: mechanischen Gong ein-/ausschalten (nur mit Gong-Schalter)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DEFAULT_GONG_ENABLED, DOMAIN, KEY_GONG
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
    """Schalter nur anlegen, wenn ein Gong-Schalter konfiguriert ist."""
    hub = entry.runtime_data
    if hub.gong_entity_id is None:
        async_remove_stale_entity(hass, "switch", f"{entry.entry_id}_{KEY_GONG}")
        return
    async_add_entities([GongSwitch(hub)])


@callback
def async_remove_stale_entity(hass: HomeAssistant, platform: str, unique_id: str) -> None:
    """Verwaisten Registry-Eintrag entfernen (z. B. nachdem der Gong abgewählt wurde)."""
    ent_reg = er.async_get(hass)
    if entity_id := ent_reg.async_get_entity_id(platform, DOMAIN, unique_id):
        ent_reg.async_remove(entity_id)


class GongSwitch(TuerklingelEntity, SwitchEntity, RestoreEntity):
    """Aus = Gong stumm; HomeKit und Push melden das Klingeln weiterhin."""

    def __init__(self, hub: TuerklingelHub) -> None:
        """Schalter anlegen."""
        super().__init__(hub, KEY_GONG)

    @property
    def is_on(self) -> bool:
        """Gong aktiv."""
        return self.hub.gong_enabled

    @property
    def icon(self) -> str:
        """Symbol je nach Zustand."""
        return "mdi:bell" if self.hub.gong_enabled else "mdi:bell-off"

    async def async_added_to_hass(self) -> None:
        """Letzten Zustand wiederherstellen und in den Hub übernehmen."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in (STATE_ON, STATE_OFF):
            self.hub.gong_enabled = last.state == STATE_ON
        else:
            self.hub.gong_enabled = DEFAULT_GONG_ENABLED

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Gong einschalten."""
        self.hub.gong_enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Gong stumm schalten."""
        self.hub.gong_enabled = False
        self.async_write_ha_state()
