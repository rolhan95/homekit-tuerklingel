"""Plattform camera: Proxy der gewählten Kamera auf dem Klingel-Gerät.

Die HomeKit Bridge verknüpft das Klingel-Event nur mit einer Kamera auf
DEMSELBEN Gerät. Diese Entität reicht Standbild und Stream der eigentlichen
Kamera (hub.camera_entity_id) durch. HomeKit holt beides über
camera.async_get_image bzw. camera.async_get_stream_source – also über
async_camera_image und stream_source dieser Entität.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components import camera
from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import KEY_CAMERA
from .entity import TuerklingelEntity
from .hub import TuerklingelHub

if TYPE_CHECKING:
    from . import TuerklingelConfigEntry

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TuerklingelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Proxy-Kamera anlegen."""
    async_add_entities([ProxyCamera(entry.runtime_data)])


class ProxyCamera(TuerklingelEntity, Camera):
    """Reicht Bild und Stream der Quellkamera durch."""

    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, hub: TuerklingelHub) -> None:
        """Entität anlegen."""
        TuerklingelEntity.__init__(self, hub, KEY_CAMERA)
        Camera.__init__(self)
        self._source = hub.camera_entity_id

    @property
    def available(self) -> bool:
        """Nur verfügbar, wenn die Quellkamera existiert und nicht unavailable ist."""
        state = self.hass.states.get(self._source)
        if state is None or state.state == STATE_UNAVAILABLE:
            return False
        return super().available

    def _source_entity(self) -> Camera | None:
        """Kamera-Objekt der Quelle (für Marke/Modell/Streaming), falls geladen."""
        try:
            return camera.get_camera_from_entity_id(self.hass, self._source)
        except HomeAssistantError:
            return None

    @property
    def is_streaming(self) -> bool:
        """Streaming-Status der Quelle."""
        src = self._source_entity()
        return bool(src.is_streaming) if src is not None else False

    @property
    def brand(self) -> str | None:
        """Marke der Quelle."""
        src = self._source_entity()
        return src.brand if src is not None else None

    @property
    def model(self) -> str | None:
        """Modell der Quelle."""
        src = self._source_entity()
        return src.model if src is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Quellkamera als Attribut (Diagnose)."""
        return {"source_entity_id": self._source}

    async def async_added_to_hass(self) -> None:
        """Zustandsänderungen der Quelle verfolgen (Verfügbarkeit)."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._source], self._handle_source
            )
        )

    @callback
    def _handle_source(self, _event: Event[EventStateChangedData]) -> None:
        self.async_write_ha_state()

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Standbild der Quellkamera (HomeKit-Snapshot)."""
        try:
            image = await camera.async_get_image(
                self.hass, self._source, width=width, height=height
            )
        except HomeAssistantError as err:
            _LOGGER.debug("Standbild von %s nicht verfügbar: %s", self._source, err)
            return None
        self.content_type = image.content_type
        return image.content

    async def stream_source(self) -> str | None:
        """Stream-URL der Quellkamera (HomeKit-Video)."""
        try:
            return await camera.async_get_stream_source(self.hass, self._source)
        except HomeAssistantError as err:
            _LOGGER.debug("Stream von %s nicht verfügbar: %s", self._source, err)
            return None
