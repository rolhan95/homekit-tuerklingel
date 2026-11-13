# HomeKit Türklingel – HomeKit-Video-Türklingel für Home Assistant

[English](README.md) · **Deutsch**

Eine Custom-Integration für Home Assistant, die **einen beliebigen Klingeltaster** und **eine beliebige
Kamera** zu einer **HomeKit-Video-Türklingel** macht – über die eingebaute HomeKit Bridge von
Home Assistant. Ohne Homebridge, ohne eigenen HomeKit-Server, ohne Cloud.

Der Klingeltaster kann alles sein, was eine URL aufrufen kann (Shelly, ESPHome, Tasmota, Skripte),
oder alles, was in Home Assistant schon als Entität vorhanden ist (Shelly, ESPHome, Zigbee, MQTT, …).
Ein vorhandener mechanischer Gong lässt sich optional über eine beliebige `switch`-Entität ansteuern
und jederzeit stumm schalten.

> [!IMPORTANT]
> **Teststand 0.2.0:** Nicht alles, was hier beschrieben ist, wurde mit echter Hardware geprüft.
> Webhook, IP-Filter, Entprellung, Entitäten und Proxy-Kamera wurden mit Version 0.1.1 in einem
> echten Home Assistant getestet. Die neuen Funktionen von 0.2.0 (Entitäts-Auslöser, Gong per
> `switch`, Migration aus 0.1.x) sind bisher nur durch automatische Tests geprüft. **Nie** echt
> getestet: HomeKit-Pairing, HomePods, Push-Benachrichtigung, Gong-Impuls an einem echten Relais.
> Siehe [Teststand](#teststand).

---

## Inhalt

- [Zweck und Funktionsweise](#zweck-und-funktionsweise)
- [Funktionen und Entitäten](#funktionen-und-entitäten)
- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Einrichtung in Home Assistant](#einrichtung-in-home-assistant)
- [Beispiele für Auslöser](#beispiele-für-auslöser)
- [Mechanischer Gong](#mechanischer-gong)
- [HomeKit koppeln](#homekit-koppeln)
- [Kamera-Empfehlungen](#kamera-empfehlungen)
- [Push-Benachrichtigung](#push-benachrichtigung)
- [Diagnose und Debug-Protokoll](#diagnose-und-debug-protokoll)
- [Fehlersuche](#fehlersuche)
- [Update von 0.1.x](#update-von-01x)
- [Umstieg von homebridge-shelly-doorbell](#umstieg-von-homebridge-shelly-doorbell)
- [Entwicklung und Tests](#entwicklung-und-tests)
- [Teststand](#teststand)
- [Lizenz](#lizenz)

---

## Zweck und Funktionsweise

```
Klingeltaster ──► beliebiges Gerät / Entität
                      │
       ┌──────────────┴───────────────┐
       │ (a) Webhook GET/POST (LAN)    │ (b) Zustandswechsel einer HA-Entität
       │     Shelly, ESPHome, Tasmota, │     binary_sensor / input_boolean → „an“
       │     Skripte …                 │     event / button / input_button → jedes Ereignis
       └──────────────┬───────────────┘
                      ▼
               Home Assistant ── Entprellung ──► Klingel-Event (Geräteklasse doorbell)
                      │                              │
                      │                              ├─► HomeKit: Klingelton auf HomePods, Mitteilung mit Kamerabild
                      │                              ├─► Snapshot „Letztes Klingeln“, optional Push
                      │                              └─► optional: Schalter-Impuls ──► mechanischer Gong (stummschaltbar)
                      ▼
               Proxy-Kamera (reicht die gewählte Kamera durch, auf dem Klingel-Gerät)
```

1. Ein Tastendruck erreicht die Integration entweder als **Webhook-Aufruf** (GET oder POST, nur im
   lokalen Netz) oder als **Zustandswechsel einer vorhandenen Entität**. Beides ist kombinierbar.
2. Eine **Entprellzeit** verwirft wiederholtes Klingeln innerhalb weniger Sekunden (Mehrfachdrücken,
   Kontaktprellen, zwei Auslöser für denselben Druck).
3. Die Integration löst eine **Event-Entität mit Geräteklasse `doorbell`** aus, speichert ein Standbild
   und schaltet – falls eingerichtet und nicht stumm – den **Gong-Schalter** für die eingestellte
   Impulsdauer ein.
4. Die Integration legt eine **Proxy-Kamera** auf demselben Gerät an. Wird diese Kamera als eigenes
   HomeKit-Zubehör (Modus *accessory*) exportiert, verknüpft die HomeKit Bridge das Klingel-Event
   desselben Geräts automatisch (`linked_doorbell_sensor`) – HomeKit zeigt dann eine
   Video-Türklingel.

## Funktionen und Entitäten

Pro eingerichteter Klingel entsteht ein Gerät mit diesen Entitäten:

| Entität | Typ | Bedeutung |
|---|---|---|
| Klingel | `event` (Geräteklasse `doorbell`) | Wird bei jedem (entprellten) Klingeln ausgelöst. Diese Entität verknüpft HomeKit als Türklingel. |
| Klingelt | `binary_sensor` | Geht beim Klingeln an und nach einstellbarer Zeit (Standard 5 s) automatisch aus. Praktisch für Automationen. |
| Zuletzt geklingelt | `sensor` (Zeitstempel) | Zeitpunkt des letzten Klingelns. |
| Letztes Klingeln | `image` | Standbild der Kamera vom letzten Klingeln. |
| Kamera | `camera` | Proxy der gewählten Kamera (Bild und Stream werden durchgereicht). Diese Kamera wird in HomeKit exportiert. |
| Entprellzeit | `number` (0–60 s, Standard 3 s) | Weiteres Klingeln innerhalb dieser Zeit wird verworfen. |
| Mechanischer Gong | `switch` | Nur wenn ein Gong-Schalter gewählt ist. An = der Gong läutet; aus = Gong stumm (z. B. nachts). |
| Gong-Dauer | `number` (0,2–10 s, Standard 1 s) | Nur wenn ein Gong-Schalter gewählt ist. Wie lange der Gong-Schalter pro Klingeln eingeschaltet bleibt. |

Außerdem:

- **Auslöser (kombinierbar):** Webhook (GET/POST, `local_only`, optional nur von erlaubten Quell-IPs
  oder Hostnamen) und/oder Home-Assistant-Entitäten (`binary_sensor`, `input_boolean`, `event`,
  `button`, `input_button`).
- **Reparatur-Hinweis „HomeKit-Türklingel anlegen“:** bietet an, das HomeKit-Zubehör für die
  Proxy-Kamera anzulegen (Modus *accessory*, Video-Codec `copy`).
- **Reparatur-Hinweis „Gong-Schalter wählen“:** nur nach einem Update von 0.1.x, wenn kein
  Gong-Schalter automatisch übernommen werden konnte.
- **Optionale Push-Benachrichtigung** mit Snapshot an beliebige `notify`-Dienste.
- **Diagnose-Download** (Geheimnisse unkenntlich) und ausführliches Debug-Protokoll (Quelle, Latenz).

Nicht enthalten: kein eigener HomeKit-Server (HAP), keine Cloud, kein Homebridge, kein eigenes
Geräteprotokoll – die Integration spricht selbst mit keiner Klingel-Hardware.

## Voraussetzungen

- **Home Assistant 2025.6.0 oder neuer** (Mindestversion in `hacs.json`). Automatisch getestet wird
  gegen Home Assistant 2026.10.4, die Tests im echten Betrieb liefen mit 2026.11.1. Ältere Versionen
  sind nicht geprüft. Das Integrations-Icon (lokale Brand-Bilder) zeigt Home Assistant erst ab 2026.3.
- Integration **HomeKit Bridge** (in Home Assistant enthalten) und ein Apple-Home-Zuhause mit
  Steuerzentrale (HomePod oder Apple TV) für Mitteilungen und Klingelton.
- Eine **Kamera-Entität** in Home Assistant (z. B. aus der Reolink-Integration), am besten mit
  H.264-Stream.
- Ein **Klingeltaster**, der entweder
  - im lokalen Netz eine HTTP-URL aufrufen kann (Webhook) oder
  - in Home Assistant bereits als Entität vorhanden ist.
- Optional: eine `switch`-Entität, die den mechanischen Gong ansteuert.

## Installation

### Über HACS (benutzerdefiniertes Repository)

1. HACS öffnen → Menü (⋮) oben rechts → **Benutzerdefinierte Repositories**.
2. Repository `https://github.com/rolhan95/homekit-tuerklingel`, Typ **Integration**, hinzufügen.
3. „HomeKit Türklingel“ suchen und **Herunterladen**.
4. Fordert Home Assistant einen Neustart an, neu starten. (Unter Home Assistant 2026.11.1 ließ sich
   die Integration direkt nach dem Herunterladen ohne Neustart hinzufügen.)

### Manuell

1. Den Ordner `custom_components/homekit_tuerklingel` aus diesem Repository in das Verzeichnis
   `config/custom_components/` von Home Assistant kopieren
   (Ergebnis: `config/custom_components/homekit_tuerklingel/manifest.json`).
2. Home Assistant neu starten.

## Einrichtung in Home Assistant

**Einstellungen → Geräte & Dienste → Integration hinzufügen → „HomeKit Türklingel“.**

Die erste Seite fragt Name, Kamera, „Klingeln per Webhook annehmen“, Auslöser-Entitäten und Gong-Schalter ab. Ist der Webhook eingeschaltet, folgt eine zweite Seite: Webhook nur von bestimmten Geräten annehmen.

1. **Name** – z. B. „Haustür“. Wird Gerätename und Name in HomeKit.
2. **Kamera** – die Kamera, deren Bild an der Tür gezeigt werden soll. Die Integration reicht sie über
   ihre eigene Proxy-Kamera durch.
3. **Auslöser** – einen oder beide wählen:
   - **Webhook**: Das Klingel-Gerät ruft eine URL auf. Optional nur von **erlaubten Quellen**
     annehmen (IP-Adressen oder Hostnamen, z. B. die IP des Shelly). Aufrufe von anderen Adressen
     werden mit HTTP 403 abgewiesen. Hostnamen werden einmal beim Laden der Klingel aufgelöst; nach
     einer IP-Änderung die Klingel neu laden.
   - **Entitäten**: eine oder mehrere vorhandene Entitäten. `binary_sensor`/`input_boolean` klingeln
     beim Wechsel auf „an“, `event`/`button`/`input_button` bei jedem neuen Ereignis bzw. Druck.
4. **Gong (optional)** – eine `switch`-Entität, die den mechanischen Gong ansteuert. Leer lassen, wenn
   es keinen Gong gibt oder Home Assistant ihn nicht ansteuern soll.
5. **Fertig** – ist der Webhook eingeschaltet, zeigt die Abschlussmeldung die **Webhook-URL**. Sie
   steht später jederzeit in den **Optionen** der Klingel (Zahnrad am Integrationseintrag →
   *Konfigurieren*).

Alle Einstellungen (Auslöser, erlaubte Quellen, Gong-Schalter, Auto-Aus von „Klingelt“, Push) lassen
sich später in den Optionen ändern.

**Warum nur im lokalen Netz?** Der Webhook ist `local_only` registriert: Home Assistant nimmt ihn nur
aus dem lokalen Netz an, nie über die externe oder Cloud-Adresse. Viele Geräte (z. B. Shelly Gen1)
können nur unverschlüsseltes HTTP aufrufen; die URL enthält deshalb die **interne** Adresse von
Home Assistant, z. B. `http://192.168.1.10:8123/api/webhook/<webhook-id>`. Die Webhook-ID ist zufällig
und lang – die URL wie ein Kennwort behandeln. Wenn möglich zusätzlich den Quellfilter einschalten.

## Beispiele für Auslöser

> [!NOTE]
> Der Webhook selbst wurde mit echten GET- und POST-Aufrufen geprüft (mit 0.1.1). Die folgenden
> Gerätekonfigurationen folgen der jeweiligen Herstellerdokumentation; keine davon wurde bisher vom
> Autor mit einem echten Gerät getestet. `192.168.1.10:8123` und `<webhook-id>` durch die URL aus den
> Optionen ersetzen.

### Shelly Gen1 (z. B. Shelly 1) – I/O URL action

In der Weboberfläche des Shelly (`http://<Shelly-IP>/`):

1. *Settings → Button Type → **Detached Switch*** – damit schaltet der Taster das Relais nicht mehr
   selbst (nötig, wenn das Relais den Gong ansteuert und stummschaltbar sein soll).
2. *I/O URL actions → **BUTTON SWITCHED ON URL*** → Webhook-URL einfügen, Häkchen **aktivieren**,
   speichern.
3. Dem Shelly eine feste IP geben (DHCP-Reservierung) und diese IP als erlaubte Quelle eintragen.

### Shelly Gen2/Plus/Pro – Actions / Webhooks

In der Weboberfläche des Shelly: **Actions** (neuere Firmware: **Webhooks**) → *Create* → als
Bedingung das Eingangsereignis, z. B. *Input 0 – button pushed* (Eingangstyp Button) bzw.
*switched on* (Eingangstyp Switch) → als Aktion **URL** = Webhook-URL → speichern. Den Ein-/Ausgang
auf **Detached** stellen, wenn das Relais den Gong ansteuert.

### ESPHome – `http_request` bei Tastendruck

```yaml
http_request:
  timeout: 3s

binary_sensor:
  - platform: gpio
    name: "Klingeltaster"
    pin:
      number: GPIO4
      mode: INPUT_PULLUP
      inverted: true
    filters:
      - delayed_on: 20ms
    on_press:
      - http_request.get:
          url: "http://192.168.1.10:8123/api/webhook/<webhook-id>"
```

Ist das ESPHome-Gerät bereits in Home Assistant eingebunden, kann stattdessen sein `binary_sensor`
direkt als **Entitäts-Auslöser** gewählt werden – ganz ohne Webhook.

### Tasmota – Rule mit WebSend

In der Tasmota-Konsole:

```
Rule1 ON Switch1#State=1 DO WebSend [192.168.1.10:8123] /api/webhook/<webhook-id> ENDON
Rule1 1
```

`WebSend` sendet ein HTTP-GET. Je nach Schaltermodus schaltet der Schalter mit einer Rule auf
`Switch1#State` das Relais nicht mehr selbst – soll das Relais den Gong getrennt ansteuern, die
Tasmota-Dokumentation zu `SwitchMode` und `SetOption114` prüfen.

### Alternative: Entität aus einer vorhandenen Integration

Statt eines Webhooks die Entität verwenden, die eine Integration schon liefert, zum Beispiel:

- **Shelly-Integration:** der Eingang des Shelly (Gen1: `binary_sensor` „Eingang“/„Input“, ggf.
  standardmäßig deaktiviert – in den Entitätseinstellungen aktivieren; Gen2 und neuer:
  `event`-Entität des Eingangs im Button-Modus).
- **Zigbee (ZHA/Zigbee2MQTT)**-Taster oder -Kontakte, **MQTT**-`binary_sensor`, **ESPHome**-
  `binary_sensor` oder ein Helfer `input_button`.

Hinweis: Ein `binary_sensor`, der von *nicht verfügbar* oder *unbekannt* auf „an“ wechselt (z. B. nach
einem Neustart), klingelt nicht. Der Webhook ist meist der schnellste Weg, weil er nicht von der
Aktualisierungsrate einer anderen Integration abhängt.

## Mechanischer Gong

- Als Gong-Schalter eine beliebige **`switch`-Entität** wählen (z. B. das Relais eines Shelly in der
  Shelly-Integration). Bei jedem Klingeln wird sie für die **Gong-Dauer eingeschaltet** und danach
  wieder **ausgeschaltet**. Läuft ein Impuls noch, wird kein zweiter gestartet.
- Der Schalter **„Mechanischer Gong“** schaltet den Gong stumm (z. B. nachts); die Zahl
  **„Gong-Dauer“** legt die Impulslänge fest (0,2–10 s). Beide Entitäten gibt es nur, wenn ein
  Gong-Schalter gewählt ist.
- **Wichtig:** Das Stummschalten wirkt nur, wenn der **Taster das Relais nicht selbst schaltet**. Beim
  Shelly den Eingang auf **„Detached“** stellen (Gen1: *Button Type → Detached Switch*; Gen2 und neuer:
  *Input/Output settings → Detached*). Sonst läutet der Gong per Hardware, unabhängig von
  Home Assistant.
- Die Verdrahtung des Gongs (Klingeltrafo, Relaiskontakt) ist nicht Teil dieser Integration. Arbeiten
  an Netzspannung nur durch eine Elektrofachkraft.

## HomeKit koppeln

HomeKit zeigt eine Video-Türklingel nur, wenn **Kamera und Klingel im selben Zubehör** stecken. Dazu muss
die **Proxy-Kamera dieser Integration** als **eigenes HomeKit-Zubehör (Modus „accessory“)** exportiert
werden. Die HomeKit Bridge findet das Klingel-Event auf demselben Gerät dann automatisch.

### Weg 1: Reparatur-Hinweis (empfohlen)

1. **Einstellungen → System → Reparaturen** → „HomeKit-Türklingel für *Name* anlegen“ öffnen.
2. Bestätigen. Es wird ein neuer HomeKit-Bridge-Eintrag im Modus *accessory* für die Proxy-Kamera
   angelegt (Video-Codec `copy`).
3. In Home Assistant erscheint die Benachrichtigung **„HomeKit Pairing“** mit QR-Code und
   8-stelligem Code.
4. iPhone: **Home-App → + → Gerät hinzufügen** → QR-Code scannen oder *Weitere Optionen* → Code
   eingeben.

### Weg 2: manuell

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen → HomeKit Bridge** – eine **neue**
   Bridge anlegen (beliebige Domain, wird gleich umgestellt).
2. Beim neuen Eintrag **Konfigurieren** → *Modus* = **accessory** → als Entität die **Kamera dieser
   Klingel** wählen (z. B. `camera.haustur_kamera`, nicht die Original-Kamera).
3. Im Kamera-Schritt „Video-Codec kopieren“ für die Kamera ankreuzen (siehe Empfehlungen unten).
4. Mit dem Code aus der Benachrichtigung „HomeKit Pairing“ in der Home-App koppeln.

> [!WARNING]
> Die Proxy-Kamera **nicht zusätzlich** in eine bestehende HomeKit Bridge (Modus *bridge*) aufnehmen.
> Kameras in einer Bridge zeigen den Türklingel-Dienst nicht zuverlässig, und das Gerät taucht doppelt
> in der Home-App auf. Die Original-Kamera ebenfalls nicht zusätzlich in HomeKit exportieren.

## Kamera-Empfehlungen

- Einen **H.264**-Stream verwenden – HomeKit kann nur H.264 empfangen. Bei Reolink den **Sub-** bzw.
  **Fluent-Stream** nehmen und ihn in der Kamera auf H.264 stellen (nicht H.265).
- **Video-Codec `copy`** (setzt der Reparatur-Hinweis automatisch): Der Stream wird unverändert
  weitergegeben – geringe Last, kurze Verzögerung. Funktioniert nur mit H.264.
- Liefert die Kamera nur **H.265**, in den Optionen des HomeKit-Eintrags als Video-Codec **`libx264`**
  wählen. Der Stream wird dann umgerechnet, was deutlich Rechenleistung kostet.
- **Audio** ist optional: In den Optionen des HomeKit-Eintrags *Audio unterstützen* (`support_audio`)
  einschalten. Der Ton wird umgewandelt, was etwas Rechenleistung kostet.

## Push-Benachrichtigung

Zusätzlich zur HomeKit-Mitteilung kann die Integration eine Push-Nachricht senden:

1. Optionen der Klingel → *Zusätzliche Push-Benachrichtigung* einschalten.
2. *Benachrichtigungsdienste*: einen oder mehrere `notify`-Dienste, z. B. `mobile_app_iphone`.
3. *Titel* und *Text* anpassen; `{name}` wird durch den Namen der Klingel ersetzt.

Die Nachricht enthält den Snapshot als Bild (über die Entität „Letztes Klingeln“), ist bei der
Companion-App als *zeitkritisch* markiert und ersetzt die vorige Mitteilung derselben Klingel.

## Diagnose und Debug-Protokoll

- **Diagnose:** Gerät bzw. Integrationseintrag → ⋮ → **Diagnose herunterladen**. Enthält die
  Einstellungen (Webhook-ID unkenntlich), Zähler (Webhook-Aufrufe, Entitäts-Auslöser, Klingeln,
  entprellt, abgelehnte IPs, Gong-Impulse und -Fehler, Snapshot- und Push-Fehler) und den letzten
  Auslöser.
- **Debug-Protokoll:** Integrationseintrag → ⋮ → *Debug-Protokollierung aktivieren* oder in
  `configuration.yaml`:

  ```yaml
  logger:
    default: warning
    logs:
      custom_components.homekit_tuerklingel: debug
  ```

  Das Protokoll zeigt jeden Auslöser mit seiner **Quelle** (Webhook-Methode und Quell-IP bzw.
  Entitäts-ID), verworfenes (entprelltes) Klingeln, Gong-Impulse und die **Latenz** vom Eingang des
  Auslösers bis zum ausgelösten Event in Millisekunden.

## Fehlersuche

| Problem | Ursache und Lösung |
|---|---|
| Kamera erscheint in HomeKit, aber **ohne Klingel** | Die Kamera war vorher schon ohne Klingel in HomeKit exportiert; HomeKit merkt sich die Dienste eines Zubehörs. Zubehör in der **Home-App entfernen**, in Home Assistant **zurücksetzen** (Aktion `homekit.reset_accessory` mit der Proxy-Kamera) oder den HomeKit-Eintrag **löschen und neu anlegen** (z. B. über den Reparatur-Hinweis), danach **neu koppeln**. Prüfen, dass die *Proxy*-Kamera exportiert ist, nicht die Original-Kamera. |
| **HomePods klingeln nicht** | Home-App → Klingel-Zubehör → Einstellungen → Mitteilungen bzw. Türklingel einschalten. Prüfen, dass eine Steuerzentrale (HomePod/Apple TV) aktiv ist. Wird gar keine Türklingel angezeigt, siehe erste Zeile. |
| **Webhook kommt nicht an** | URL am Gerät prüfen (interne HTTP-Adresse, Port 8123, keine externe/Cloud-Adresse). Debug-Protokoll einschalten: Erscheint gar nichts, erreicht das Gerät Home Assistant nicht (nur HTTPS, Firewall, VLAN, falscher Port). |
| Webhook antwortet mit **403** | Der Quellfilter hat den Aufruf abgewiesen. Das Protokoll zeigt die abgelehnte IP – sie (oder einen Hostnamen, der auf sie zeigt) bei den erlaubten Quellen eintragen und die Klingel neu laden. Hinter einem Reverse-Proxy sieht Home Assistant ggf. die IP des Proxys. |
| **Entitäts-Auslöser klingelt nicht** | `binary_sensor`/`input_boolean` klingeln nur beim Wechsel auf „an“ (nicht aus *nicht verfügbar*/*unbekannt*). Im Verlauf der Entität prüfen, ob sich der Zustand wirklich ändert. Entprellzeit zu lang? |
| **Gong läutet, obwohl „Mechanischer Gong“ aus ist** | Der Taster schaltet das Relais direkt. Den Eingang auf **Detached** stellen (Shelly: *Detached Switch*). |
| **Gong läutet nie** | Gong-Schalter gewählt und „Mechanischer Gong“ an? Lässt sich der Schalter von Hand schalten? „Gong-Dauer“ zu kurz für den Gong? Fehler im Debug-Protokoll prüfen. |
| **Schwarzes / kein Bild in HomeKit** | **H.264**-Stream verwenden; `copy` nur mit H.264, sonst `libx264`. Prüfen, ob die Original-Kamera in Home Assistant ein Bild liefert. |
| Klingeln wird **doppelt** gemeldet | „Entprellzeit“ erhöhen. Webhook und Entitäts-Auslöser für denselben Taster zählen als zwei Auslöser – die Entprellzeit fängt das ab. |

## Update von 0.1.x

Version 0.2.0 entfernt die direkte Shelly-Gen1-Anbindung per HTTP (Zugangsdaten, Verbindungstest,
„Shelly erreichbar“, Hinweis „nicht entkoppelt“). Die vorhandene Klingel wird **automatisch
umgestellt**:

- Die **Webhook-URL bleibt gleich** – am Shelly muss nichts geändert werden.
- Der Quellfilter behält seine Einstellung und erlaubt weiter die **IP des Shelly** (bzw. die vorher
  eingetragene abweichende IP).
- **Gong:** Ist derselbe Shelly zusätzlich in der **Shelly-Integration** von Home Assistant
  eingebunden, wird dessen Schalter als Gong-Schalter übernommen. Sonst erscheint der
  Reparatur-Hinweis **„Gong-Schalter wählen“**: den Shelly in der Shelly-Integration einbinden (oder
  einen anderen Schalter nehmen) und den Schalter in den Optionen der Klingel wählen. Bis dahin wird
  kein Gong angesteuert.
- Die Entität „Shelly erreichbar“ und die gespeicherten Shelly-Zugangsdaten werden entfernt.

Mit einer echten 0.1.1-Installation getestet (siehe Teststand). Hinweis: Vor 0.2.1 wurde der Gong-Schalter nicht gefunden, wenn das Shelly-Gerät zu mehreren Integrationen gehört (Home Assistant teilt solche Geräte seit 2026.10 auf); 0.2.1 behebt das.

## Umstieg von homebridge-shelly-doorbell

1. Diese Integration installieren und die Klingel einrichten (Auslöser: Webhook; erlaubte Quelle:
   Shelly-IP; Gong: auf Wunsch der Schalter des Shelly aus der Shelly-Integration).
2. Am Shelly unter *I/O URL actions → BUTTON SWITCHED ON URL* die bisherige Homebridge-URL durch die
   **Webhook-URL aus Home Assistant** ersetzen.
3. In der Home-App das alte Homebridge-Türklingel-Zubehör **entfernen** und das Plugin aus Homebridge
   nehmen.
4. Das neue Zubehör wie unter [HomeKit koppeln](#homekit-koppeln) beschrieben anlegen und koppeln.

## Entwicklung und Tests

Die Tests nutzen [`pytest-homeassistant-custom-component`](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)
mit **Python 3.14**:

```bash
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements_test.txt
pytest tests --cov=custom_components.homekit_tuerklingel --cov-report=term-missing
```

- Die automatischen Prüfungen laufen in GitHub Actions unter **Linux** (`tests.yml`: pytest mit
  mindestens 90 % Abdeckung; `validate.yml`: hassfest und HACS-Prüfung).
- Lokal laufen die Tests auch unter Windows; maßgeblich ist der Lauf unter Linux.
- **Die Tests nutzen nie das echte Netz:** Geräte, Kameras, Zeroconf/mDNS und der HomeKit-Server sind
  durch Simulationen ersetzt; ein Testlauf kündigt also nie Zubehör im eigenen Netz an.
- Jede Änderung erhöht die Version in `custom_components/homekit_tuerklingel/manifest.json` und
  bekommt einen Eintrag im [CHANGELOG](CHANGELOG.md).

## Teststand

Stand **0.2.1 (2026-11-13)**.

### Im echten Home Assistant getestet (HA 2026.11.1, Shelly 1 Gen1, Reolink)

Mit 0.2.0 (2026-11-13):

- Update 0.1.1 → 0.2.0 über HACS mit Migration: Webhook, Quellfilter (Shelly-IP) und Kamera
  übernommen, „Shelly erreichbar“ entfernt
- Hinweis „Gong-Schalter wählen“ erscheint, wenn kein Schalter zugeordnet werden konnte; Auswahl in
  den Optionen entfernt ihn (die automatische Zuordnung selbst griff in 0.2.0 nicht und ist in 0.2.1
  behoben, siehe Änderungsprotokoll)
- Entitäts-Auslöser (`input_boolean`): Event 0,2 ms nach dem Zustandswechsel, Snapshot und „Klingelt“
  gesetzt
- Gong stumm: Der Gong-Schalter wird nicht geschaltet
- Nimmt eine vorhandene HomeKit-Bridge alle Kameras auf, legt Home Assistant das HomeKit-Zubehör für
  die Proxy-Kamera beim nächsten Start selbst an (beobachtet); der Reparatur-Hinweis verschwindet dann

Mit 0.1.1 (gilt in 0.2.x weiter):

- Installation über HACS, Hinzufügen ohne Neustart (HA 2026.11.1)
- Webhook mit GET und POST (`local_only`), Event 1–2 ms nach dem Aufruf
- Quellfilter: Aufrufe von fremder IP werden mit 403 abgelehnt; abweichende erlaubte IP greift
- Entprellung: zweiter Aufruf innerhalb von 3 s wird verworfen
- Entitäten: „Klingelt“ geht nach 5 s aus; „Zuletzt geklingelt“ und Snapshot „Letztes Klingeln“
  werden gesetzt
- Proxy-Kamera liefert das Live-Bild einer echten Reolink-Kamera (auch skaliert)

### Nur durch automatische Tests geprüft (0.2.0)

136 Tests, Abdeckung 99 % (lokaler Lauf unter Windows und Linux-CI).

- Einrichtung und Optionen: Name, Kamera, Webhook mit Quellfilter (IP und Hostname),
  Entitäts-Auslöser, Gong-Schalter
- Entitäts-Auslöser: `binary_sensor`/`input_boolean` beim Wechsel auf „an“,
  `event`/`button`/`input_button` bei jedem Ereignis; kein Klingeln aus *nicht verfügbar*/*unbekannt*
- Gong per `switch`: Impuls ein/aus, stumm, Fehler
- Migration aus 0.1.x: Webhook-URL bleibt, erlaubte IP wird übernommen, Gong-Schalter aus der
  Shelly-Integration bzw. Reparatur-Hinweis „Gong-Schalter wählen“
- Reparatur-Hinweis und Anlegen des HomeKit-Zubehörs mit der echten HomeKit-Integration (ohne
  HomeKit-Server): `linked_doorbell_sensor` zeigt auf das Klingel-Event, `video_codec` ist `copy`
- Push-Inhalt (Titel, Text, Bild), Diagnose mit Schwärzung

### Im echten Home Assistant noch nicht getestet

- Entitäts-Auslöser (Entitäten aus Shelly, ESPHome, Zigbee, MQTT)
- Gong per `switch`, Stummschalter und Gong-Dauer an echter Hardware
- Migration einer echten 0.1.x-Installation
- Beispiele für Auslöser mit echten Geräten (Shelly-Gen1-URL-Action, Shelly Gen2+, ESPHome, Tasmota)
- Reparatur-Hinweis „HomeKit-Türklingel anlegen“ im echten Home Assistant
- HomeKit-Pairing, Klingelton auf HomePods, Mitteilung auf iPhone/Apple Watch, Live-Video in
  Apple Home
- Push-Benachrichtigung über die Companion-App
- Integrations-Icon (lokale Brand-Bilder, ab Home Assistant 2026.3)

## Lizenz

[MIT](LICENSE) – © 2026 rolhan95
