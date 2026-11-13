# Änderungsprotokoll

Alle Änderungen an dieser Integration. Jede Änderung erhöht die Version in
`custom_components/homekit_tuerklingel/manifest.json`; jede Version bekommt hier einen Abschnitt.

## [0.1.1] – 2026-11-13

### Behoben

- Tests: Lokale Testläufe unter Windows konnten Test-Zubehör („Haustür …“) per mDNS im echten Netz
  ankündigen; Home Assistant im selben Netz zeigte es als neu entdecktes „HomeKit Device“. Zeroconf
  und der HomeKit-Server sind in allen Tests jetzt ersetzt. Keine Änderung an der Integration selbst.

### Getestet (echter Home Assistant 2026.11.1, Shelly 1 Gen1, Reolink)

- Installation über HACS (Marketplace), Laden ohne Neustart (HA 2026.11.1)
- Einrichtung: Verbindungstest zu einem echten Shelly 1 (Gen1, Firmware 1.14.0, ohne Anmeldung),
  Kamerawahl (Reolink, Sub-Stream), alle Entitäten mit deutschen Namen auf einem Gerät
- Hinweis „Eingang nicht entkoppelt“: erkennt den Eingangsmodus „action“ richtig
- Webhook mit GET und POST (`local_only`), Event 1–2 ms nach dem Aufruf
- IP-Filter: Aufrufe von fremder IP werden mit 403 abgelehnt; abweichende erlaubte IP greift
- Entprellung: zweiter Aufruf innerhalb von 3 s wird verworfen
- „Klingelt“ geht nach 5 s aus; „Zuletzt geklingelt“ und Snapshot „Letztes Klingeln“ werden gesetzt
- Gong-Schalter „aus“: kein Relais-Aufruf
- Proxy-Kamera liefert das Live-Bild der Reolink-Kamera (auch skaliert)
- Erreichbarkeit „Shelly erreichbar“ zeigt „an“

### Noch nicht getestet

- Gong-Impuls am echten Relais, Reparatur-Hinweis „HomeKit-Türklingel anlegen“, HomeKit-Pairing,
  HomePods, Push-Benachrichtigung.

## [0.1.0] – 2026-11-13

Erste Version. Ersetzt das Homebridge-Plugin `homebridge-shelly-doorbell`.

### Hinzugefügt

- Einrichtung per Config-Flow: Shelly 1 (Gen1) mit Verbindungsprüfung, optionale Zugangsdaten,
  Kamerawahl, Anzeige der Webhook-URL; Ändern der Klingel und erneute Anmeldung bei falschen
  Zugangsdaten.
- Webhook für die I/O URL action des Shelly (GET/POST, nur LAN, standardmäßig nur von der Shelly-IP).
- Gerät mit den Entitäten Klingel (`event`, `doorbell`), Klingelt (`binary_sensor` mit Auto-Aus),
  Mechanischer Gong (`switch`), Entprellzeit und Gong-Dauer (`number`), Letztes Klingeln (`image`),
  Zuletzt geklingelt (`sensor`), Shelly erreichbar (`binary_sensor`, optional) und Kamera
  (Proxy der gewählten Kamera).
- Gong-Impuls über das Shelly-Relais (`/relay/0?turn=on&timer=…`, optional mit Basic-Auth), stummschaltbar.
- Reparatur-Hinweise: HomeKit-Türklingel anlegen (legt auf Wunsch das HomeKit-Zubehör im Modus
  *accessory* an) und Shelly-Eingang nicht entkoppelt.
- Optionale Push-Benachrichtigung mit Snapshot an `notify`-Dienste.
- Diagnose-Download und Debug-Protokoll (Quell-IP, Entprellung, Latenz).
- Integrations-Icon als lokales Brand-Bild (`brand/icon.png`, ab Home Assistant 2026.3).
- HACS-Unterstützung, GitHub-Actions für Tests (pytest, ≥ 90 % Abdeckung), hassfest und HACS-Prüfung.

### Getestet

- Automatische Tests: 116 Tests, Abdeckung 99 % (HA 2026.10.4): Einrichtung, Webhook GET/POST,
  IP-Filter, Entprellung, Gong/Relais, Entitäten, Proxy-Kamera, Reparatur-Hinweise inkl. Anlegen des
  HomeKit-Zubehörs mit automatischer Klingel-Verknüpfung, Push-Inhalt, Diagnose.
- In einem echten Home Assistant: noch nichts.

### Noch nicht getestet

- Alle oben genannten Funktionen im echten Home Assistant mit echtem Shelly 1, echter Kamera,
  HomeKit Bridge und Apple-Home (siehe README, Abschnitt „Teststand“). Teile davon werden durch
  automatische Tests mit simuliertem Shelly geprüft.
