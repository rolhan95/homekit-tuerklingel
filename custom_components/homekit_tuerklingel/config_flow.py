"""Config-Flow und Options-Flow der Integration HomeKit Türklingel."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
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
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util.network import is_host_valid

from .const import (
    CONF_ALLOWED_IP,
    CONF_AUTO_OFF,
    CONF_CAMERA_ENTITY,
    CONF_CONNECTIVITY,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_MESSAGE,
    CONF_NOTIFY_SERVICES,
    CONF_NOTIFY_TITLE,
    CONF_RESTRICT_IP,
    CONF_SHELLY_HOST,
    CONF_SHELLY_MAC,
    CONF_SHELLY_PASSWORD,
    CONF_SHELLY_USERNAME,
    CONF_WEBHOOK_ID,
    DEFAULT_AUTO_OFF,
    DEFAULT_CONNECTIVITY,
    DEFAULT_NOTIFY_ENABLED,
    DEFAULT_NOTIFY_MESSAGE,
    DEFAULT_NOTIFY_TITLE,
    DEFAULT_RESTRICT_IP,
    DOMAIN,
    SHELLY_TIMEOUT,
)
from .shelly import ShellyAuthError, ShellyConnectionError, ShellyGen1Client, ShellyInfo
from .util import async_get_webhook_url

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Haustür"
MIN_AUTO_OFF = 1
MAX_AUTO_OFF = 300

PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)
CAMERA_SELECTOR = selector.EntitySelector(selector.EntitySelectorConfig(domain="camera"))


class NotShellyGen1Error(Exception):
    """Unter der Adresse antwortet etwas, aber kein Shelly Gen1."""


def _normalize_host(host: str) -> str:
    """Eingabe bereinigen: Leerzeichen, Schema und abschließenden Schrägstrich entfernen."""
    host = host.strip()
    for prefix in ("http://", "https://"):
        if host.lower().startswith(prefix):
            host = host[len(prefix) :]
    return host.rstrip("/")


async def _async_check_gen1(hass: HomeAssistant, host: str) -> None:
    """Antwort von /shelly selbst prüfen, um 'kein Shelly Gen1' zu erkennen.

    Verbindungsfehler werden hier bewusst ignoriert; die meldet anschließend
    der eigentliche Verbindungstest als cannot_connect.
    """
    session = async_get_clientsession(hass)
    try:
        async with asyncio.timeout(SHELLY_TIMEOUT):
            async with session.get(f"http://{host}/shelly") as resp:
                if resp.status != 200:
                    raise NotShellyGen1Error(f"HTTP {resp.status}")
                try:
                    data = await resp.json(content_type=None)
                except ValueError as err:
                    raise NotShellyGen1Error("keine JSON-Antwort") from err
    except (TimeoutError, aiohttp.ClientError):
        return
    if not isinstance(data, dict) or not data.get("mac"):
        raise NotShellyGen1Error("keine MAC-Adresse")
    # Gen2/Gen3 liefern 'gen' >= 2; Gen1 kennt das Feld nicht.
    if data.get("gen", 1) != 1:
        raise NotShellyGen1Error(f"Generation {data.get('gen')}")


async def _async_test_shelly(
    hass: HomeAssistant, host: str, username: str | None, password: str | None
) -> tuple[ShellyInfo | None, dict[str, str]]:
    """Verbindungstest; liefert (Info, Fehler)."""
    try:
        await _async_check_gen1(hass, host)
        client = ShellyGen1Client(async_get_clientsession(hass), host, username, password)
        info = await client.async_get_info(with_settings=True)
    except NotShellyGen1Error as err:
        _LOGGER.debug("%s ist kein Shelly Gen1: %s", host, err)
        return None, {"base": "not_shelly_gen1"}
    except ShellyAuthError:
        return None, {"base": "invalid_auth"}
    except ShellyConnectionError as err:
        _LOGGER.debug("Shelly %s nicht erreichbar: %s", host, err)
        return None, {"base": "cannot_connect"}
    except Exception:
        _LOGGER.exception("Unerwarteter Fehler beim Verbindungstest mit %s", host)
        return None, {"base": "unknown"}
    return info, {}


def _detached_hint(info: ShellyInfo | None) -> str:
    """Hinweis, wenn der Eingang des Shelly nicht auf 'detached' steht."""
    if info is None or info.detached is not False:
        return ""
    return (
        f"\n\n⚠️ Der Eingang des Shelly steht auf „{info.btn_type}“. "
        "Für den stummschaltbaren Gong bitte „Detached Switch“ einstellen."
    )


def _default_options() -> dict[str, Any]:
    """Standardwerte der Optionen für einen neuen Entry."""
    return {
        CONF_RESTRICT_IP: DEFAULT_RESTRICT_IP,
        CONF_ALLOWED_IP: "",
        CONF_AUTO_OFF: DEFAULT_AUTO_OFF,
        CONF_CONNECTIVITY: DEFAULT_CONNECTIVITY,
        CONF_NOTIFY_ENABLED: DEFAULT_NOTIFY_ENABLED,
        CONF_NOTIFY_SERVICES: [],
        CONF_NOTIFY_TITLE: DEFAULT_NOTIFY_TITLE,
        CONF_NOTIFY_MESSAGE: DEFAULT_NOTIFY_MESSAGE,
    }


class TuerklingelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Einrichtung einer Klingel: Shelly prüfen, dann Kamera wählen."""

    VERSION = 1

    def __init__(self) -> None:
        """Zwischenstand des Flows."""
        self._user_input: dict[str, Any] = {}
        self._info: ShellyInfo | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> TuerklingelOptionsFlow:
        """Options-Flow liefern."""
        return TuerklingelOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name und Zugangsdaten des Shelly abfragen und testen."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = _normalize_host(user_input[CONF_SHELLY_HOST])
            username = user_input.get(CONF_SHELLY_USERNAME) or None
            password = user_input.get(CONF_SHELLY_PASSWORD) or None
            info, errors = await _async_test_shelly(self.hass, host, username, password)
            if info is not None:
                await self.async_set_unique_id(info.mac)
                self._abort_if_unique_id_configured(updates={CONF_SHELLY_HOST: host})
                self._info = info
                self._user_input = {
                    CONF_NAME: user_input[CONF_NAME].strip() or DEFAULT_NAME,
                    CONF_SHELLY_HOST: host,
                    CONF_SHELLY_USERNAME: username,
                    CONF_SHELLY_PASSWORD: password,
                    CONF_SHELLY_MAC: info.mac,
                }
                return await self.async_step_camera()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_SHELLY_HOST): str,
                vol.Optional(CONF_SHELLY_USERNAME): str,
                vol.Optional(CONF_SHELLY_PASSWORD): PASSWORD_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_camera(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Kamera-Entität wählen und Entry anlegen."""
        if user_input is not None:
            data = {
                key: value for key, value in self._user_input.items() if key != CONF_NAME
            }
            data[CONF_CAMERA_ENTITY] = user_input[CONF_CAMERA_ENTITY]
            data[CONF_WEBHOOK_ID] = async_generate_id()
            return self.async_create_entry(
                title=self._user_input[CONF_NAME],
                data=data,
                options=_default_options(),
                description_placeholders={
                    "webhook_url": async_get_webhook_url(self.hass, data[CONF_WEBHOOK_ID])
                },
            )

        return self.async_show_form(
            step_id="camera",
            data_schema=vol.Schema({vol.Required(CONF_CAMERA_ENTITY): CAMERA_SELECTOR}),
            description_placeholders={"detached_hint": _detached_hint(self._info)},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Shelly lehnt die gespeicherten Zugangsdaten ab."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Neue Zugangsdaten abfragen und testen."""
        entry = self._get_reauth_entry()
        host: str = entry.data[CONF_SHELLY_HOST]
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input.get(CONF_SHELLY_USERNAME) or None
            password = user_input.get(CONF_SHELLY_PASSWORD) or None
            info, errors = await _async_test_shelly(self.hass, host, username, password)
            if info is not None:
                await self.async_set_unique_id(info.mac)
                self._abort_if_unique_id_mismatch()
                # Neu laden übernimmt der Update-Listener aus __init__.py.
                return self.async_update_and_abort(
                    entry,
                    data_updates={
                        CONF_SHELLY_USERNAME: username,
                        CONF_SHELLY_PASSWORD: password,
                    },
                )

        schema = vol.Schema(
            {
                vol.Optional(CONF_SHELLY_USERNAME): str,
                vol.Optional(CONF_SHELLY_PASSWORD): PASSWORD_SELECTOR,
            }
        )
        suggested = user_input or {
            CONF_SHELLY_USERNAME: entry.data.get(CONF_SHELLY_USERNAME) or ""
        }
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders={"host": host},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Host, Zugangsdaten und Kamera ändern."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = _normalize_host(user_input[CONF_SHELLY_HOST])
            username = user_input.get(CONF_SHELLY_USERNAME) or None
            password = user_input.get(CONF_SHELLY_PASSWORD) or None
            if (
                username is not None
                and password is None
                and username == entry.data.get(CONF_SHELLY_USERNAME)
            ):
                # Leeres Kennwortfeld bei gleichem Benutzer: bisheriges behalten.
                password = entry.data.get(CONF_SHELLY_PASSWORD)
            info, errors = await _async_test_shelly(self.hass, host, username, password)
            if info is not None:
                await self.async_set_unique_id(info.mac)
                self._abort_if_unique_id_mismatch()
                # Neu laden übernimmt der Update-Listener aus __init__.py.
                return self.async_update_and_abort(
                    entry,
                    data_updates={
                        CONF_SHELLY_HOST: host,
                        CONF_SHELLY_USERNAME: username,
                        CONF_SHELLY_PASSWORD: password,
                        CONF_CAMERA_ENTITY: user_input[CONF_CAMERA_ENTITY],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_SHELLY_HOST): str,
                vol.Optional(CONF_SHELLY_USERNAME): str,
                vol.Optional(CONF_SHELLY_PASSWORD): PASSWORD_SELECTOR,
                vol.Required(CONF_CAMERA_ENTITY): CAMERA_SELECTOR,
            }
        )
        if user_input is not None:
            suggested: dict[str, Any] = {
                key: value
                for key, value in user_input.items()
                if key != CONF_SHELLY_PASSWORD
            }
        else:
            suggested = {
                CONF_SHELLY_HOST: entry.data[CONF_SHELLY_HOST],
                CONF_SHELLY_USERNAME: entry.data.get(CONF_SHELLY_USERNAME) or "",
                CONF_CAMERA_ENTITY: entry.data[CONF_CAMERA_ENTITY],
            }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )


class TuerklingelOptionsFlow(OptionsFlow):
    """Optionen einer Klingel.

    Bewusst kein OptionsFlowWithReload: __init__.py lädt über seinen
    Update-Listener neu, ein zweites Neuladen wird so vermieden.
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
        errors: dict[str, str] = {}
        if user_input is not None:
            allowed_ip = str(user_input.get(CONF_ALLOWED_IP) or "").strip()
            if allowed_ip and not is_host_valid(allowed_ip):
                errors[CONF_ALLOWED_IP] = "invalid_ip"
            else:
                return self.async_create_entry(
                    data={
                        CONF_RESTRICT_IP: user_input[CONF_RESTRICT_IP],
                        CONF_ALLOWED_IP: allowed_ip,
                        CONF_AUTO_OFF: int(user_input[CONF_AUTO_OFF]),
                        CONF_CONNECTIVITY: user_input[CONF_CONNECTIVITY],
                        CONF_NOTIFY_ENABLED: user_input[CONF_NOTIFY_ENABLED],
                        CONF_NOTIFY_SERVICES: [
                            str(svc).strip().removeprefix("notify.")
                            for svc in user_input.get(CONF_NOTIFY_SERVICES, [])
                            if str(svc).strip()
                        ],
                        CONF_NOTIFY_TITLE: str(
                            user_input.get(CONF_NOTIFY_TITLE) or DEFAULT_NOTIFY_TITLE
                        ).strip(),
                        CONF_NOTIFY_MESSAGE: str(
                            user_input.get(CONF_NOTIFY_MESSAGE) or DEFAULT_NOTIFY_MESSAGE
                        ).strip(),
                    }
                )

        current = {**_default_options(), **self.config_entry.options}
        configured: list[str] = list(current.get(CONF_NOTIFY_SERVICES) or [])
        schema = vol.Schema(
            {
                vol.Required(CONF_RESTRICT_IP): selector.BooleanSelector(),
                vol.Optional(CONF_ALLOWED_IP): selector.TextSelector(),
                vol.Required(CONF_AUTO_OFF): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_AUTO_OFF,
                        max=MAX_AUTO_OFF,
                        step=1,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_CONNECTIVITY): selector.BooleanSelector(),
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
            data_schema=self.add_suggested_values_to_schema(schema, user_input or current),
            errors=errors,
            description_placeholders={
                "webhook_url": async_get_webhook_url(
                    self.hass, self.config_entry.data[CONF_WEBHOOK_ID]
                ),
                # Wörtlich anzeigen: Der Text erklärt den Platzhalter {name}.
                "name": "{name}",
            },
        )
