"""Gemeinsame Fixtures."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if sys.platform == "win32":  # pragma: no cover - nur lokale Entwicklung unter Windows
    # Unter Windows braucht die asyncio-Ereignisschleife echte Sockets (socketpair).
    # In CI (Linux) bleibt die Socket-Sperre des HA-Test-Plugins aktiv.
    import pytest_socket

    pytest_socket.disable_socket = lambda *a, **k: None

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_tuerklingel.const import (
    CONF_CAMERA_ENTITY,
    CONF_SHELLY_HOST,
    CONF_SHELLY_MAC,
    CONF_SHELLY_PASSWORD,
    CONF_SHELLY_USERNAME,
    CONF_WEBHOOK_ID,
    DOMAIN,
)

SHELLY_HOST = "192.168.1.50"
SHELLY_MAC = "AABBCCDDEEFF"
CAMERA = "camera.eingang"
WEBHOOK_ID = "test_webhook_id_0123456789"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Custom-Integrationen in allen Tests erlauben."""
    return


@pytest.fixture(autouse=True)
def _kein_echtes_netz(mock_async_zeroconf):
    """Tests dürfen nie etwas im echten Netz ankündigen oder öffnen.

    - Zeroconf/mDNS ist durch mock_async_zeroconf ersetzt.
    - Der HomeKit-Server (HAP) startet nie; Tests, die den Start prüfen, patchen
      async_start zusätzlich selbst.
    - Die Port-Prüfung von HomeKit nutzt keinen echten Socket.
    Hintergrund: Unter Windows ist die Socket-Sperre aufgehoben; ein Testlauf hat
    sonst Test-Zubehör per mDNS im LAN angekündigt.
    """
    with (
        patch("homeassistant.components.homekit.HomeKit.async_start", AsyncMock()),
        patch(
            "homeassistant.components.homekit.util._get_test_socket",
            return_value=MagicMock(),
        ),
    ):
        yield


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    """Ein fertig eingerichteter Config-Entry (noch nicht hinzugefügt)."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Haustür",
        unique_id=SHELLY_MAC,
        data={
            CONF_SHELLY_HOST: SHELLY_HOST,
            CONF_SHELLY_USERNAME: "admin",
            CONF_SHELLY_PASSWORD: "geheim",
            CONF_SHELLY_MAC: SHELLY_MAC,
            CONF_CAMERA_ENTITY: CAMERA,
            CONF_WEBHOOK_ID: WEBHOOK_ID,
        },
        options={},
        version=1,
    )
