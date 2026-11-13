"""Konstanten der Integration HomeKit Türklingel."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "homekit_tuerklingel"

# --- Daten des Config-Entry (entry.data) ---
CONF_NAME: Final = "name"
CONF_SHELLY_HOST: Final = "shelly_host"
CONF_SHELLY_USERNAME: Final = "shelly_username"
CONF_SHELLY_PASSWORD: Final = "shelly_password"
CONF_SHELLY_MAC: Final = "shelly_mac"
CONF_CAMERA_ENTITY: Final = "camera_entity"
CONF_WEBHOOK_ID: Final = "webhook_id"

# --- Optionen (entry.options) ---
CONF_RESTRICT_IP: Final = "restrict_ip"
"""Webhook nur von der Shelly-IP (bzw. CONF_ALLOWED_IP) annehmen."""
CONF_ALLOWED_IP: Final = "allowed_ip"
"""Abweichende erlaubte Quell-IP; leer = CONF_SHELLY_HOST."""
CONF_AUTO_OFF: Final = "auto_off"
"""Sekunden, nach denen der Binärsensor 'Klingelt' wieder aus geht."""
CONF_CONNECTIVITY: Final = "connectivity"
"""Erreichbarkeit des Shelly regelmäßig prüfen (Binärsensor)."""
CONF_NOTIFY_ENABLED: Final = "notify_enabled"
CONF_NOTIFY_SERVICES: Final = "notify_services"
"""Liste von Dienstnamen ohne Domain, z. B. ['mobile_app_iphone']."""
CONF_NOTIFY_TITLE: Final = "notify_title"
CONF_NOTIFY_MESSAGE: Final = "notify_message"

DEFAULT_RESTRICT_IP: Final = True
DEFAULT_AUTO_OFF: Final = 5
DEFAULT_CONNECTIVITY: Final = True
DEFAULT_NOTIFY_ENABLED: Final = False
DEFAULT_NOTIFY_TITLE: Final = "Es klingelt"
DEFAULT_NOTIFY_MESSAGE: Final = "Jemand steht an der Tür ({name})."

# --- Laufzeitwerte, die über number-/switch-Entitäten eingestellt werden ---
DEFAULT_COOLDOWN: Final = 3.0
"""Entprellzeit in Sekunden: Klingeln innerhalb dieser Zeit wird verworfen."""
MIN_COOLDOWN: Final = 0.0
MAX_COOLDOWN: Final = 60.0
DEFAULT_GONG_DURATION: Final = 1.0
"""Impulsdauer des Relais (mechanischer Gong) in Sekunden."""
MIN_GONG_DURATION: Final = 0.2
MAX_GONG_DURATION: Final = 10.0
DEFAULT_GONG_ENABLED: Final = True

# --- Technik ---
SHELLY_TIMEOUT: Final = 5
"""Zeitlimit für HTTP-Aufrufe an den Shelly in Sekunden."""
SNAPSHOT_TIMEOUT: Final = 10
CONNECTIVITY_INTERVAL: Final = 60
"""Abfrageintervall der Shelly-Erreichbarkeit in Sekunden."""
WEBHOOK_METHODS: Final = ("GET", "POST")

# Schlüssel der Entitäten (translation_key und Teil der unique_id)
KEY_EVENT: Final = "klingel"
KEY_RINGING: Final = "klingelt"
KEY_CONNECTIVITY: Final = "shelly_erreichbar"
KEY_GONG: Final = "gong"
KEY_COOLDOWN: Final = "entprellzeit"
KEY_GONG_DURATION: Final = "gong_dauer"
KEY_SNAPSHOT: Final = "letztes_klingeln"
KEY_LAST_RING: Final = "zuletzt_geklingelt"
KEY_CAMERA: Final = "kamera"

EVENT_TYPE_RING: Final = "ring"

# Repair-Issues (Präfix, vollständige ID = f"{ISSUE_...}_{entry_id}")
ISSUE_HOMEKIT_SETUP: Final = "homekit_einrichten"
ISSUE_NOT_DETACHED: Final = "eingang_nicht_entkoppelt"
