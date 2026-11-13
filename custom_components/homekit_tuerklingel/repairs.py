"""Reparatur-Flows: HomeKit-Zubehör für die Klingel anlegen."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import issue_registry as ir

from .const import CONF_CAMERA_ENTITY, DOMAIN, ISSUE_HOMEKIT_SETUP
from .homekit import (
    HomeKitResult,
    async_create_homekit_accessory,
    async_get_proxy_camera_entity_id,
)

PLACEHOLDER_CAMERA = "camera_entity_id"


class HomeKitSetupRepairFlow(RepairsFlow):
    """Legt nach Bestätigung das HomeKit-Zubehör für die Proxy-Kamera an."""

    def __init__(self, entry_id: str) -> None:
        """Flow für den Entry anlegen."""
        self._entry_id = entry_id

    def _camera_entity_id(self) -> str:
        """Proxy-Kamera (oder hilfsweise die Quellkamera) für die Anzeige."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return "?"
        return async_get_proxy_camera_entity_id(self.hass, entry) or str(
            entry.data.get(CONF_CAMERA_ENTITY, "?")
        )

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Erster Schritt: weiter zur Bestätigung."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Bestätigen und Zubehör anlegen."""
        camera_entity_id = self._camera_entity_id()
        placeholders = {PLACEHOLDER_CAMERA: camera_entity_id}
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                description_placeholders=placeholders,
            )

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(
                reason=HomeKitResult.CAMERA_MISSING, description_placeholders=placeholders
            )

        result = await async_create_homekit_accessory(self.hass, entry)
        if result is HomeKitResult.CREATED:
            return self.async_create_entry(data={})
        if result is HomeKitResult.ALREADY_EXISTS:
            # Erledigt – der Hinweis ist damit gegenstandslos.
            ir.async_delete_issue(self.hass, DOMAIN, self.issue_id)
        return self.async_abort(reason=str(result), description_placeholders=placeholders)


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Passenden Reparatur-Flow zum Hinweis liefern."""
    if issue_id.startswith(f"{ISSUE_HOMEKIT_SETUP}_"):
        entry_id = str(
            (data or {}).get("entry_id") or issue_id.removeprefix(f"{ISSUE_HOMEKIT_SETUP}_")
        )
        return HomeKitSetupRepairFlow(entry_id)
    return ConfirmRepairFlow()
