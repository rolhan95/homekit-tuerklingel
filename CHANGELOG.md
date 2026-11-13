# Änderungsprotokoll

Alle Änderungen an dieser Integration. Jede Änderung erhöht die Version in
`custom_components/homekit_tuerklingel/manifest.json`; jede Version bekommt hier einen Abschnitt.

## [0.2.1] – 2026-11-13

### Behoben

- Migration aus 0.1.x: Der Gong-Schalter des Shelly wurde nicht gefunden, wenn das Gerät zu mehreren
  Integrationen gehört (Home Assistant teilt solche Geräte seit 2026.10 auf; die Entität zeigt dann auf
  die alte, zusammengesetzte Geräte-ID). Die Suche geht jetzt über die Entitäten. Wer bereits auf 0.2.0
  umgestellt wurde, wählt den Gong-Schalter einmal in den Optionen (Hinweis „Gong-Schalter wählen“).

### Getestet (echter Home Assistant 2026.11.1, Shelly 1 Gen1, Reolink, mit 0.2.0)

- Update 0.1.1 → 0.2.0 über HACS: Migration von Webhook, Quellfilter und Kamera; Hinweis
  „Gong-Schalter wählen“ und dessen Entfernen über die Optionen
- Entitäts-Auslöser (`input_boolean`), Gong stumm
- Automatisches Anlegen des HomeKit-Zubehörs durch eine vorhandene Bridge, die alle Kameras aufnimmt
- 136 automatische Tests, Abdeckung 99 %

### Noch nicht getestet

- Die korrigierte automatische Gong-Zuordnung an einem geteilten Gerät im echten Home Assistant
  (die Installation war schon umgestellt)
- Gong-Impuls am echten Relais, HomeKit-Pairing, HomePods, Push-Benachrichtigung

## [0.2.0] – 2026-11-13

Die Integration ist jetzt **universell**: beliebiger Klingel-Auslöser, beliebiger Gong-Schalter,
beliebige Kamera. Sie spricht selbst mit keiner Klingel-Hardware mehr.

### Geändert

- Einrichtung: Name, Kamera, Auslöser (Webhook und/oder Entitäten), optionaler Gong-Schalter –
  ohne Shelly-Adresse, Zugangsdaten und Verbindungstest.
- Webhook (GET/POST, nur LAN) ist jetzt ein Auslöser unter mehreren, für jedes Gerät, das eine URL
  aufrufen kann (Shelly Gen1/Gen2+, ESPHome, Tasmota, Skripte). Der Quellfilter nimmt mehrere
  erlaubte Quellen an (IP-Adressen oder Hostnamen; Hostnamen werden beim Laden aufgelöst).
- Gong: statt des Shelly-Relais per HTTP eine beliebige `switch`-Entität, die für die Gong-Dauer
  ein- und danach wieder ausgeschaltet wird. „Mechanischer Gong“ und „Gong-Dauer“ gibt es nur noch,
  wenn ein Gong-Schalter gewählt ist.
- Debug-Protokoll und Diagnose nennen die Quelle des Auslösers (Webhook mit Methode und IP bzw.
  Entität) und zählen Entitäts-Auslöser.
- README neu auf Englisch (`README.md`), deutsche Fassung in `README.de.md`.

### Hinzugefügt

- Auslöser über vorhandene Home-Assistant-Entitäten: `binary_sensor`/`input_boolean` (Wechsel auf
  „an“), `event`/`button`/`input_button` (jedes Ereignis). Kein Klingeln, wenn eine Entität nur aus
  *nicht verfügbar*/*unbekannt* zurückkommt. Webhook und Entitäten sind kombinierbar; die Entprellung
  verhindert Doppel-Klingeln.
- Reparatur-Hinweis „Gong-Schalter wählen“ (nur nach Update von 0.1.x ohne übernehmbaren Schalter).
- Beispiele für Auslöser im README: Shelly Gen1 und Gen2+, ESPHome, Tasmota, Entität aus der
  Shelly-Integration.

### Entfernt

- Direkte Shelly-Gen1-HTTP-Anbindung: Zugangsdaten, Verbindungstest, erneute Anmeldung (Reauth),
  Binärsensor „Shelly erreichbar“, Reparatur-Hinweis „Eingang nicht entkoppelt“.

### Update-Hinweise

- Bestehende Klingeln aus 0.1.x werden beim Start automatisch umgestellt:
  - Die Webhook-URL bleibt gleich; am Shelly muss nichts geändert werden.
  - Der Quellfilter behält seine Einstellung und erlaubt weiter die Shelly-IP (bzw. die abweichende
    erlaubte IP).
  - Ist der Shelly zusätzlich in der Shelly-Integration eingebunden, wird dessen Schalter als
    Gong-Schalter übernommen. Sonst erscheint „Gong-Schalter wählen“ – bis dahin läutet der Gong nicht.
  - „Shelly erreichbar“ und die gespeicherten Shelly-Zugangsdaten werden entfernt.
- Das Stummschalten des Gongs wirkt weiterhin nur, wenn der Taster das Relais nicht selbst schaltet
  (Shelly: „Detached“).

### Getestet

<!-- KOORDINATOR: Anzahl Tests/Abdeckung und die Ergebnisse des Live-Tests mit 0.2.0 eintragen. -->

- Automatische Tests (pytest-homeassistant-custom-component, Python 3.14): Einrichtung und Optionen,
  Webhook mit Quellfilter (IP und Hostname), Entitäts-Auslöser, Entprellung, Gong per `switch`,
  Migration aus 0.1.x, Entitäten, Proxy-Kamera, Reparatur-Hinweise, Push-Inhalt, Diagnose.
- Im echten Home Assistant mit 0.1.1 geprüft und in 0.2.0 weiter vorhanden (erneuter Live-Test mit
  0.2.0 steht aus): Installation über HACS, Webhook GET/POST mit 1–2 ms bis zum Event, IP-Filter 403,
  Entprellung, Entitäten, Proxy-Kamera mit echter Reolink.

### Noch nicht getestet

- Im echten Home Assistant: Entitäts-Auslöser, Gong per `switch`, Migration einer echten
  0.1.x-Installation, Beispiele für Auslöser mit echten Geräten (Shelly Gen1/Gen2+, ESPHome, Tasmota).
- Nie im echten Home Assistant getestet: HomeKit-Pairing, Klingelton auf HomePods, Push-Benachrichtigung,
  Gong-Impuls an einem echten Relais, Reparatur-Hinweis „HomeKit-Türklingel anlegen“.

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
