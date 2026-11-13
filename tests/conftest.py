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
    CONF_ALLOWED_SOURCES,
    CONF_CAMERA_ENTITY,
    CONF_GONG_ENTITY,
    CONF_RESTRICT_IP,
    CONF_TRIGGER_ENTITIES,
    CONF_WEBHOOK_ENABLED,
    CONF_WEBHOOK_ID,
    DOMAIN,
)

SHELLY_HOST = "192.168.1.50"
CAMERA = "camera.eingang"
GONG = "switch.gong_relais"
TRIGGER = "binary_sensor.klingeltaster"
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
    """Eingerichtete Klingel (Version 2): Webhook nur von SHELLY_HOST, Taster-Entität, Gong-Schalter."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Haustür",
        data={CONF_WEBHOOK_ID: WEBHOOK_ID, CONF_CAMERA_ENTITY: CAMERA},
        options={
            CONF_WEBHOOK_ENABLED: True,
            CONF_RESTRICT_IP: True,
            CONF_ALLOWED_SOURCES: [SHELLY_HOST],
            CONF_TRIGGER_ENTITIES: [TRIGGER],
            CONF_GONG_ENTITY: GONG,
        },
        version=2,
    )
