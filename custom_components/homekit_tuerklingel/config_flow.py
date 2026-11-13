"""Config-Flow und Options-Flow der Integration HomeKit Türklingel.

Eine Klingel besteht aus:
- Auslöser: Webhook (GET/POST, nur LAN) und/oder beliebige HA-Entitäten
- Kamera: beliebige camera-Entität (eine Klingel pro Kamera, wegen HomeKit)
- Gong (optional): beliebige switch-Entität, die beim Klingeln gepulst wird

Alle Einstellungen außer dem Namen lassen sich später über die Optionen ändern;
reauth und reconfigure gibt es deshalb nicht.
"""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.components.webhook import async_generate_id
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import selector
from homeassistant.util.network import is_host_valid

from .const import (
    CONF_ALLOWED_SOURCES,
    CONF_AUTO_OFF,
    CONF_CAMERA_ENTITY,
    CONF_GONG_ENTITY,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_MESSAGE,
    CONF_NOTIFY_SERVICES,
    CONF_NOTIFY_TITLE,
    CONF_RESTRICT_IP,
    CONF_TRIGGER_ENTITIES,
    CONF_WEBHOOK_ENABLED,
    CONF_WEBHOOK_ID,
    CONFIG_VERSION,
    DEFAULT_AUTO_OFF,
    DEFAULT_NOTIFY_ENABLED,
    DEFAULT_NOTIFY_MESSAGE,
    DEFAULT_NOTIFY_TITLE,
    DEFAULT_RESTRICT_IP,
    DEFAULT_WEBHOOK_ENABLED,
    DOMAIN,
    ISSUE_GONG_SELECT,
    TRIGGER_DOMAINS,
)
from .util import async_get_webhook_url

MIN_AUTO_OFF = 1
MAX_AUTO_OFF = 300
WEBHOOK_OFF_HINT = "—"
"""Platzhalter für die Webhook-URL, wenn der Webhook ausgeschaltet ist."""

_SOURCE_SPLIT = re.compile(r"[,;\s]+")


def _own_entities(hass: HomeAssistant, domain: str) -> list[str]:
    """Entitäten dieser Integration einer Domain (dürfen nicht ausgewählt werden).

    Verhindert Schleifen, z. B. die eigene Proxy-Kamera als Kamera, das eigene
    Klingel-Event als Auslöser oder den eigenen Gong-Schalter als Gong.
    """
    return sorted(
        entry.entity_id
        for entry in er.async_get(hass).entities.values()
        if entry.platform == DOMAIN and entry.domain == domain
    )


def _entity_selector(
    hass: HomeAssistant, domains: str | list[str], *, multiple: bool = False
) -> selector.EntitySelector:
    """Entitäts-Auswahl ohne die eigenen Entitäten der Integration."""
    domain_list = [domains] if isinstance(domains, str) else domains
    exclude = [eid for domain in domain_list for eid in _own_entities(hass, domain)]
    config = selector.EntitySelectorConfig(
        domain=domains, multiple=multiple, exclude_entities=exclude
    )
    return selector.EntitySelector(config)


def _parse_sources(value: Any) -> list[str]:
    """Kommagetrennte Liste (auch Semikolon/Leerzeichen) in einzelne Quellen zerlegen."""
    if isinstance(value, list):
        value = ",".join(str(item) for item in value)
    parts = _SOURCE_SPLIT.split(str(value or "").strip())
    # IPv6 darf in eckigen Klammern stehen, gespeichert wird ohne.
    return [part.strip("[]") for part in parts if part.strip("[]")]


def _source_valid(source: str) -> bool:
    """IP-Adresse (IPv4/IPv6) oder gültiger Hostname."""
    return is_host_valid(source)


def _validate_sources(
    sources: list[str], webhook_enabled: bool, restrict_ip: bool
) -> dict[str, str]:
    """Fehler der Quell-Liste (leer, wenn alles in Ordnung)."""
    if any(not _source_valid(source) for source in sources):
        return {CONF_ALLOWED_SOURCES: "invalid_source"}
    if webhook_enabled and restrict_ip and not sources:
        return {CONF_ALLOWED_SOURCES: "source_required"}
    return {}


def _camera_in_use(
    hass: HomeAssistant, camera_entity_id: str, own_entry_id: str | None = None
) -> bool:
    """Nutzt schon eine andere Klingel dieser Integration diese Kamera?"""
    return any(
        entry.data.get(CONF_CAMERA_ENTITY) == camera_entity_id
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.entry_id != own_entry_id
    )


def _default_options() -> dict[str, Any]:
    """Standardwerte aller Optionen."""
    return {
        CONF_WEBHOOK_ENABLED: DEFAULT_WEBHOOK_ENABLED,
        CONF_RESTRICT_IP: DEFAULT_RESTRICT_IP,
        CONF_ALLOWED_SOURCES: [],
        CONF_TRIGGER_ENTITIES: [],
        CONF_GONG_ENTITY: None,
        CONF_AUTO_OFF: DEFAULT_AUTO_OFF,
        CONF_NOTIFY_ENABLED: DEFAULT_NOTIFY_ENABLED,
        CONF_NOTIFY_SERVICES: [],
        CONF_NOTIFY_TITLE: DEFAULT_NOTIFY_TITLE,
        CONF_NOTIFY_MESSAGE: DEFAULT_NOTIFY_MESSAGE,
    }


def _webhook_hint(hass: HomeAssistant, webhook_id: str, enabled: bool) -> str:
    """Webhook-URL als Code oder „—“, wenn der Webhook ausgeschaltet ist."""
    if not enabled:
        return WEBHOOK_OFF_HINT
    return f"`{async_get_webhook_url(hass, webhook_id)}`"


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    """None-Werte entfernen (sonst zeigt das Formular „None“ als Vorschlag)."""
    return {key: value for key, value in values.items() if value is not None}


class TuerklingelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Einrichtung einer Klingel: Auslöser, Kamera, Gong, ggf. Webhook-Schutz."""

    VERSION = CONFIG_VERSION
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Zwischenstand des Flows."""
        self._name: str = ""
        self._camera: str = ""
        self._webhook_id: str = ""
        self._options: dict[str, Any] = _default_options()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> TuerklingelOptionsFlow:
        """Options-Flow liefern."""
        return TuerklingelOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name, Kamera, Auslöser und Gong abfragen."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name = str(user_input[CONF_NAME]).strip()
            camera = user_input[CONF_CAMERA_ENTITY]
            webhook_enabled = bool(user_input.get(CONF_WEBHOOK_ENABLED, True))
            triggers = list(user_input.get(CONF_TRIGGER_ENTITIES) or [])
            if not name:
                errors[CONF_NAME] = "name_required"
            if _camera_in_use(self.hass, camera):
                errors[CONF_CAMERA_ENTITY] = "camera_in_use"
            if not webhook_enabled and not triggers:
                errors["base"] = "no_trigger"
            if not errors:
                self._name = name
                self._camera = camera
                self._webhook_id = async_generate_id()
                self._options.update(
                    {
                        CONF_WEBHOOK_ENABLED: webhook_enabled,
                        CONF_TRIGGER_ENTITIES: triggers,
                        CONF_GONG_ENTITY: user_input.get(CONF_GONG_ENTITY) or None,
                    }
                )
                if webhook_enabled:
                    return await self.async_step_webhook()
                return self._async_create()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): selector.TextSelector(),
                vol.Required(CONF_CAMERA_ENTITY): _entity_selector(self.hass, "camera"),
                vol.Required(
                    CONF_WEBHOOK_ENABLED, default=DEFAULT_WEBHOOK_ENABLED
                ): selector.BooleanSelector(),
                vol.Optional(CONF_TRIGGER_ENTITIES): _entity_selector(
                    self.hass, list(TRIGGER_DOMAINS), multiple=True
                ),
                vol.Optional(CONF_GONG_ENTITY): _entity_selector(self.hass, "switch"),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_webhook(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Webhook optional auf bestimmte Quellen beschränken."""
        errors: dict[str, str] = {}
        if user_input is not None:
            restrict = bool(user_input.get(CONF_RESTRICT_IP, DEFAULT_RESTRICT_IP))
            sources = _parse_sources(user_input.get(CONF_ALLOWED_SOURCES))
            errors = _validate_sources(sources, True, restrict)
            if not errors:
                self._options[CONF_RESTRICT_IP] = restrict
                self._options[CONF_ALLOWED_SOURCES] = sources
                return self._async_create()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_RESTRICT_IP, default=DEFAULT_RESTRICT_IP
                ): selector.BooleanSelector(),
                vol.Optional(CONF_ALLOWED_SOURCES): selector.TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="webhook",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
            description_placeholders={
                "webhook_url": async_get_webhook_url(self.hass, self._webhook_id)
            },
        )

    @callback
    def _async_create(self) -> ConfigFlowResult:
        """Entry anlegen."""
        return self.async_create_entry(
            title=self._name,
            data={CONF_WEBHOOK_ID: self._webhook_id, CONF_CAMERA_ENTITY: self._camera},
            options=dict(self._options),
            description_placeholders={
                "webhook_hint": _webhook_hint(
                    self.hass, self._webhook_id, self._options[CONF_WEBHOOK_ENABLED]
                )
            },
        )


class TuerklingelOptionsFlow(OptionsFlow):
    """Optionen einer Klingel (inkl. Kamera).

    Bewusst kein OptionsFlowWithReload: __init__.py lädt über seinen
    Update-Listener neu. Daten und Optionen werden in einem Schritt
    gespeichert, damit nur einmal neu geladen wird.
    """

    def _notify_service_options(self, configured: list[str]) -> list[str]:
        """Registrierte notify-Dienste (ohne send_message) plus bereits gewählte."""
        services = {
            name
            for name in self.hass.services.async_services_for_domain("notify")
            if name != "send_message"
        }
        services.update(configured)
        return sorted(services)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Optionen bearbeiten."""
        entry = self.config_entry
        errors: dict[str, str] = {}
        if user_input is not None:
            camera = user_input[CONF_CAMERA_ENTITY]
            webhook_enabled = bool(user_input.get(CONF_WEBHOOK_ENABLED))
            restrict = bool(user_input.get(CONF_RESTRICT_IP))
            sources = _parse_sources(user_input.get(CONF_ALLOWED_SOURCES))
            triggers = list(user_input.get(CONF_TRIGGER_ENTITIES) or [])
            errors = _validate_sources(sources, webhook_enabled, restrict)
            if _camera_in_use(self.hass, camera, entry.entry_id):
                errors[CONF_CAMERA_ENTITY] = "camera_in_use"
            if not webhook_enabled and not triggers:
                errors["base"] = "no_trigger"
            if not errors:
                options = {
                    CONF_WEBHOOK_ENABLED: webhook_enabled,
                    CONF_RESTRICT_IP: restrict,
                    CONF_ALLOWED_SOURCES: sources,
                    CONF_TRIGGER_ENTITIES: triggers,
                    # Leeres Feld: Das Frontend lässt den Schlüssel weg → kein Gong.
                    CONF_GONG_ENTITY: user_input.get(CONF_GONG_ENTITY) or None,
                    CONF_AUTO_OFF: int(user_input[CONF_AUTO_OFF]),
                    CONF_NOTIFY_ENABLED: bool(user_input.get(CONF_NOTIFY_ENABLED)),
                    CONF_NOTIFY_SERVICES: [
                        str(svc).strip().removeprefix("notify.")
                        for svc in user_input.get(CONF_NOTIFY_SERVICES) or []
                        if str(svc).strip()
                    ],
                    CONF_NOTIFY_TITLE: str(
                        user_input.get(CONF_NOTIFY_TITLE) or ""
                    ).strip()
                    or DEFAULT_NOTIFY_TITLE,
                    CONF_NOTIFY_MESSAGE: str(
                        user_input.get(CONF_NOTIFY_MESSAGE) or ""
                    ).strip()
                    or DEFAULT_NOTIFY_MESSAGE,
                }
                # Kamera liegt in entry.data: Daten und Optionen zusammen speichern
                # (ein Neuladen). async_create_entry findet danach keine Änderung mehr.
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_CAMERA_ENTITY: camera},
                    options=options,
                )
                ir.async_delete_issue(
                    self.hass, DOMAIN, f"{ISSUE_GONG_SELECT}_{entry.entry_id}"
                )
                return self.async_create_entry(data=options)

        current: dict[str, Any] = {
            **_default_options(),
            **entry.options,
            CONF_CAMERA_ENTITY: entry.data.get(CONF_CAMERA_ENTITY),
        }
        current[CONF_ALLOWED_SOURCES] = ", ".join(
            _parse_sources(current.get(CONF_ALLOWED_SOURCES))
        )
        configured: list[str] = list(current.get(CONF_NOTIFY_SERVICES) or [])
        schema = vol.Schema(
            {
                vol.Required(CONF_CAMERA_ENTITY): _entity_selector(self.hass, "camera"),
                vol.Required(CONF_WEBHOOK_ENABLED): selector.BooleanSelector(),
                vol.Required(CONF_RESTRICT_IP): selector.BooleanSelector(),
                vol.Optional(CONF_ALLOWED_SOURCES): selector.TextSelector(),
                vol.Optional(CONF_TRIGGER_ENTITIES): _entity_selector(
                    self.hass, list(TRIGGER_DOMAINS), multiple=True
                ),
                vol.Optional(CONF_GONG_ENTITY): _entity_selector(self.hass, "switch"),
                vol.Required(CONF_AUTO_OFF): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_AUTO_OFF,
                        max=MAX_AUTO_OFF,
                        step=1,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_NOTIFY_ENABLED): selector.BooleanSelector(),
                vol.Optional(CONF_NOTIFY_SERVICES): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=self._notify_service_options(configured),
                        multiple=True,
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_NOTIFY_TITLE): selector.TextSelector(),
                vol.Optional(CONF_NOTIFY_MESSAGE): selector.TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema, _without_none(user_input or current)
            ),
            errors=errors,
            description_placeholders={
                "webhook_url": _webhook_hint(
                    self.hass,
                    entry.data[CONF_WEBHOOK_ID],
                    bool(current.get(CONF_WEBHOOK_ENABLED)),
                ),
                # Wörtlich anzeigen: Der Text erklärt den Platzhalter {name}.
                "name": "{name}",
            },
        )
