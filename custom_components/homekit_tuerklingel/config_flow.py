"""Config-Flow – PLATZHALTER, wird von Agent A implementiert."""

from __future__ import annotations

from homeassistant.config_entries import ConfigFlow

from .const import DOMAIN


class TuerklingelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config-Flow."""

    VERSION = 1
