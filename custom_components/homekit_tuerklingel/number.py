"""Plattform number: Entprellzeit und Gong-Dauer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.number import (
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DEFAULT_COOLDOWN,
    DEFAULT_GONG_DURATION,
    KEY_COOLDOWN,
    KEY_GONG_DURATION,
    MAX_COOLDOWN,
    MAX_GONG_DURATION,
    MIN_COOLDOWN,
    MIN_GONG_DURATION,
)
from .entity import TuerklingelEntity
from .hub import TuerklingelHub

if TYPE_CHECKING:
    from . import TuerklingelConfigEntry

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class TuerklingelNumberDescription(NumberEntityDescription):
    """Beschreibung inkl. Standardwert und Attribut im Hub."""

    default: float
    hub_attr: str


NUMBERS: tuple[TuerklingelNumberDescription, ...] = (
    TuerklingelNumberDescription(
        key=KEY_COOLDOWN,
        native_min_value=MIN_COOLDOWN,
        native_max_value=MAX_COOLDOWN,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer-sand",
        default=DEFAULT_COOLDOWN,
        hub_attr="cooldown",
    ),
    TuerklingelNumberDescription(
        key=KEY_GONG_DURATION,
        native_min_value=MIN_GONG_DURATION,
        native_max_value=MAX_GONG_DURATION,
        native_step=0.1,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:timer-outline",
        default=DEFAULT_GONG_DURATION,
        hub_attr="gong_duration",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TuerklingelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Zahlen-Entitäten anlegen."""
    hub = entry.runtime_data
    async_add_entities(TuerklingelNumber(hub, desc) for desc in NUMBERS)


class TuerklingelNumber(TuerklingelEntity, RestoreNumber):
    """Einstellwert, der direkt in den Hub geschrieben wird."""

    entity_description: TuerklingelNumberDescription

    def __init__(
        self, hub: TuerklingelHub, description: TuerklingelNumberDescription
    ) -> None:
        """Entität anlegen."""
        super().__init__(hub, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float:
        """Aktueller Wert aus dem Hub."""
        return float(getattr(self.hub, self.entity_description.hub_attr))

    async def async_added_to_hass(self) -> None:
        """Letzten Wert (nur im erlaubten Bereich) wiederherstellen und in den Hub übernehmen."""
        await super().async_added_to_hass()
        desc = self.entity_description
        value = desc.default
        if (last := await self.async_get_last_number_data()) is not None and (
            last.native_value is not None
        ):
            restored = float(last.native_value)
            if desc.native_min_value <= restored <= desc.native_max_value:
                value = restored
        setattr(self.hub, desc.hub_attr, value)

    async def async_set_native_value(self, value: float) -> None:
        """Neuen Wert setzen."""
        setattr(self.hub, self.entity_description.hub_attr, float(value))
        self.async_write_ha_state()
