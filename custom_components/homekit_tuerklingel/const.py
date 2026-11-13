"""Konstanten der Integration HomeKit Türklingel."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "homekit_tuerklingel"

CONFIG_VERSION: Final = 2
"""Version 1 (0.1.x): Shelly Gen1 per HTTP. Version 2 (ab 0.2.0): universell."""

# --- Daten des Config-Entry (entry.data) ---
CONF_NAME: Final = "name"
CONF_CAMERA_ENTITY: Final = "camera_entity"
CONF_WEBHOOK_ID: Final = "webhook_id"
"""Wird immer erzeugt; registriert wird der Webhook nur bei CONF_WEBHOOK_ENABLED."""

# --- Optionen (entry.options) ---
CONF_WEBHOOK_ENABLED: Final = "webhook_enabled"
"""Klingeln per Webhook (GET/POST, nur LAN) annehmen."""
CONF_RESTRICT_IP: Final = "restrict_ip"
"""Webhook nur von CONF_ALLOWED_SOURCES annehmen."""
CONF_ALLOWED_SOURCES: Final = "allowed_sources"
"""Liste erlaubter Quellen (IP-Adressen oder Hostnamen)."""
CONF_TRIGGER_ENTITIES: Final = "trigger_entities"
"""HA-Entitäten, die das Klingeln auslösen (binary_sensor, event, button, input_button, input_boolean)."""
CONF_GONG_ENTITY: Final = "gong_entity"
"""Optionale switch-Entität für den mechanischen Gong (wird gepulst)."""
CONF_AUTO_OFF: Final = "auto_off"
"""Sekunden, nach denen der Binärsensor 'Klingelt' wieder aus geht."""
CONF_NOTIFY_ENABLED: Final = "notify_enabled"
CONF_NOTIFY_SERVICES: Final = "notify_services"
"""Liste von Dienstnamen ohne Domain, z. B. ['mobile_app_iphone']."""
CONF_NOTIFY_TITLE: Final = "notify_title"
CONF_NOTIFY_MESSAGE: Final = "notify_message"

TRIGGER_DOMAINS: Final = ("binary_sensor", "event", "button", "input_button", "input_boolean")
"""Erlaubte Domains für Auslöser-Entitäten."""

DEFAULT_WEBHOOK_ENABLED: Final = True
DEFAULT_RESTRICT_IP: Final = False
DEFAULT_AUTO_OFF: Final = 5
DEFAULT_NOTIFY_ENABLED: Final = False
DEFAULT_NOTIFY_TITLE: Final = "Es klingelt"
DEFAULT_NOTIFY_MESSAGE: Final = "Jemand steht an der Tür ({name})."

# --- Laufzeitwerte, die über number-/switch-Entitäten eingestellt werden ---
DEFAULT_COOLDOWN: Final = 3.0
"""Entprellzeit in Sekunden: Klingeln innerhalb dieser Zeit wird verworfen."""
MIN_COOLDOWN: Final = 0.0
MAX_COOLDOWN: Final = 60.0
DEFAULT_GONG_DURATION: Final = 1.0
"""Impulsdauer des Gong-Schalters in Sekunden."""
MIN_GONG_DURATION: Final = 0.2
MAX_GONG_DURATION: Final = 10.0
DEFAULT_GONG_ENABLED: Final = True

# --- Technik ---
SNAPSHOT_TIMEOUT: Final = 10
WEBHOOK_METHODS: Final = ("GET", "POST")

# Schlüssel der Entitäten (translation_key und Teil der unique_id)
KEY_EVENT: Final = "klingel"
KEY_RINGING: Final = "klingelt"
KEY_GONG: Final = "gong"
KEY_COOLDOWN: Final = "entprellzeit"
KEY_GONG_DURATION: Final = "gong_dauer"
KEY_SNAPSHOT: Final = "letztes_klingeln"
KEY_LAST_RING: Final = "zuletzt_geklingelt"
KEY_CAMERA: Final = "kamera"
KEY_CONNECTIVITY_V1: Final = "shelly_erreichbar"
"""Nur Version 1; wird bei der Migration aus der Entity-Registry entfernt."""

EVENT_TYPE_RING: Final = "ring"

# Repair-Issues (vollständige ID = f"{ISSUE_...}_{entry_id}")
ISSUE_HOMEKIT_SETUP: Final = "homekit_einrichten"
ISSUE_GONG_SELECT: Final = "gong_waehlen"
"""Nach der Migration aus 0.1.x: kein Gong-Schalter gefunden."""
ISSUE_NOT_DETACHED_V1: Final = "eingang_nicht_entkoppelt"
"""Nur Version 1; wird bei der Migration entfernt."""

# Version-1-Schlüssel (nur für die Migration)
V1_SHELLY_HOST: Final = "shelly_host"
V1_SHELLY_USERNAME: Final = "shelly_username"
V1_SHELLY_PASSWORD: Final = "shelly_password"
V1_SHELLY_MAC: Final = "shelly_mac"
V1_ALLOWED_IP: Final = "allowed_ip"
V1_CONNECTIVITY: Final = "connectivity"
