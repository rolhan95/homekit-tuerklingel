# HomeKit Türklingel

Home-Assistant-Integration, die eine klassische 2-Draht-Klingel mit einem **Shelly 1 (Gen1)** und einer
vorhandenen Kamera (z. B. **Reolink**) zu einer **HomeKit-Video-Türklingel** macht – über die
HomeKit Bridge von Home Assistant, ohne Homebridge, ohne eigenen HomeKit-Server und ohne Cloud.

Sie ersetzt das Homebridge-Plugin `homebridge-shelly-doorbell`.

> [!IMPORTANT]
> **Teststand 0.1.1:** Einrichtung, Webhook, IP-Filter, Entprellung, Entitäten und Proxy-Kamera
> sind in einem echten Home Assistant mit echtem Shelly 1 und Reolink-Kamera geprüft. Noch **nicht**
> geprüft: Gong-Impuls am echten Relais, HomeKit-Pairing, Klingeln auf HomePods, Push.
> Siehe [Teststand](#teststand).

---

## Inhalt

- [So funktioniert es](#so-funktioniert-es)
- [Funktionen und Entitäten](#funktionen-und-entitäten)
- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Einrichtung in Home Assistant](#einrichtung-in-home-assistant)
- [Shelly 1 (Gen1) einrichten](#shelly-1-gen1-einrichten)
- [HomeKit koppeln](#homekit-koppeln)
- [Kamera-Empfehlung (Reolink)](#kamera-empfehlung-reolink)
- [Push-Benachrichtigung](#push-benachrichtigung)
- [Diagnose und Debug-Protokoll](#diagnose-und-debug-protokoll)
- [Fehlersuche](#fehlersuche)
- [Umstieg von homebridge-shelly-doorbell](#umstieg-von-homebridge-shelly-doorbell)
- [Entwicklung und Tests](#entwicklung-und-tests)
- [Teststand](#teststand)
- [Lizenz](#lizenz)

---

## So funktioniert es

```
Klingeltaster ──► Shelly 1 (Eingang SW, „Detached Switch“)
                     │  HTTP-GET (I/O URL action) im LAN
                     ▼
              Home Assistant ── Webhook ──► Klingel-Event (doorbell)
                     │                         │
                     │                         ├─► HomeKit: Klingelton auf HomePods, Mitteilung mit Kamerabild
                     │                         ├─► Snapshot „Letztes Klingeln“, optional Push
                     │                         └─► Relais-Impuls ──► mechanischer Gong (stummschaltbar)
                     ▼
              Proxy-Kamera (reicht die gewählte Kamera durch)
```

1. Der Klingeltaster hängt am Eingang des Shelly 1. Weil der Eingang **entkoppelt** ist („Detached
   Switch“), schaltet der Taster das Relais nicht mehr direkt.
2. Beim Drücken ruft der Shelly per **I/O URL action** eine Webhook-URL von Home Assistant auf
   (nur HTTP, nur im lokalen Netz, auf Wunsch nur von der Shelly-IP).
3. Die Integration löst ein **Event mit Geräteklasse `doorbell`** aus, nimmt ein Standbild auf und
   lässt – sofern eingeschaltet – über das Shelly-Relais den **mechanischen Gong** kurz anschlagen.
4. Die Integration legt eine **Proxy-Kamera** auf demselben Gerät an. Wird diese Kamera als eigenes
   HomeKit-Zubehör (Modus *accessory*) exportiert, verknüpft die HomeKit Bridge das Klingel-Event
   automatisch als Türklingel (`linked_doorbell_sensor`) – HomeKit sieht dann eine Video-Türklingel.

## Funktionen und Entitäten

Pro eingerichteter Klingel entsteht ein Gerät mit diesen Entitäten:

| Entität | Typ | Bedeutung |
|---|---|---|
| Klingel | `event` (Geräteklasse `doorbell`) | Wird bei jedem (entprellten) Klingeln ausgelöst. Diese Entität verknüpft HomeKit als Türklingel. |
| Klingelt | `binary_sensor` | Geht beim Klingeln an und nach einstellbarer Zeit (Standard 5 s) automatisch aus. Praktisch für Automationen und als Rückfall-Sensor. |
| Mechanischer Gong | `switch` | An = beim Klingeln schaltet das Shelly-Relais kurz und der vorhandene Gong läutet. Aus = Gong stumm (z. B. nachts oder wenn das Baby schläft). |
| Entprellzeit | `number` (0–60 s, Standard 3 s) | Weiteres Klingeln innerhalb dieser Zeit wird verworfen (Mehrfachdrücken, Kontaktprellen). |
| Gong-Dauer | `number` (0,2–10 s, Standard 1 s) | Wie lange das Relais beim Klingeln anzieht. |
| Letztes Klingeln | `image` | Standbild der Kamera vom letzten Klingeln. |
| Zuletzt geklingelt | `sensor` (Zeitstempel) | Zeitpunkt des letzten Klingelns. |
| Shelly erreichbar | `binary_sensor` (optional) | Prüft jede Minute, ob der Shelly antwortet. Abschaltbar in den Optionen. |
| Kamera | `camera` | Proxy der gewählten Kamera (Bild und Stream werden durchgereicht). Diese Kamera wird in HomeKit exportiert. |

Weitere Bestandteile:

- **Reparatur-Hinweis „HomeKit-Türklingel anlegen“:** bietet an, das HomeKit-Zubehör für die
  Proxy-Kamera automatisch anzulegen (über den Zubehör-Ablauf der HomeKit Bridge).
- **Reparatur-Hinweis „Shelly-Eingang ist nicht entkoppelt“:** erscheint, wenn am Shelly nicht
  „Detached Switch“ eingestellt ist – dann könnte der Gong nicht stumm geschaltet werden.
- **Optionale Push-Benachrichtigung** mit Snapshot an beliebige `notify`-Dienste.
- **Diagnose-Download** (Zugangsdaten werden unkenntlich gemacht) und ausführliches Debug-Protokoll.
- **Webhook-Schutz:** nur aus dem lokalen Netz (`local_only`), standardmäßig nur von der IP des Shelly.
- **Erneute Anmeldung (Reauth)**, wenn der Shelly die gespeicherten Zugangsdaten ablehnt, und
  **Ändern der Klingel** (IP, Zugangsdaten, Kamera) ohne Neuanlage.

Nicht enthalten: kein eigener HomeKit-Server (HAP), keine Cloud, kein Homebridge.

## Voraussetzungen

- **Home Assistant 2025.6.0 oder neuer** (Mindestversion in `hacs.json`).
  Begründung: Die Integration nutzt `AddConfigEntryEntitiesCallback` (seit 2025.2),
  typisierte `ConfigEntry[...]`-Laufzeitdaten und die Verknüpfung von **Event**-Entitäten als
  HomeKit-Türklingel (seit 2024.9). 2025.6.0 lässt Abstand zu diesen Grenzen.
  Das eigene Integrations-Icon zeigt Home Assistant erst **ab 2026.3** an (lokale Brand-Bilder);
  ältere Versionen zeigen ein Platzhalter-Icon.
  Automatisch getestet wird gegen **Home Assistant 2026.10.4**; ältere Versionen sind nicht geprüft.
- Integration **HomeKit Bridge** (in Home Assistant enthalten) und ein Apple-Home-Zuhause mit
  Steuerzentrale (HomePod oder Apple TV) für Mitteilungen und Klingelton.
- **Shelly 1 der ersten Generation (Gen1)** mit Firmware, die *I/O URL actions* anbietet, und einer
  **festen IP-Adresse** im LAN.
- Eine Kamera-Entität in Home Assistant (z. B. aus der Reolink-Integration).
- Home Assistant muss für den Shelly per **HTTP** im LAN erreichbar sein (siehe unten).

## Installation

### Über HACS (benutzerdefiniertes Repository)

1. HACS öffnen → Menü (⋮) oben rechts → **Benutzerdefinierte Repositories**.
2. Repository `https://github.com/rolhan95/homekit-tuerklingel`, Typ **Integration**, hinzufügen.
3. „HomeKit Türklingel“ suchen und **Herunterladen**.
4. Home Assistant **neu starten**.

### Manuell

1. Den Ordner `custom_components/homekit_tuerklingel` aus diesem Repository in das Verzeichnis
   `config/custom_components/` von Home Assistant kopieren
   (Ergebnis: `config/custom_components/homekit_tuerklingel/manifest.json`).
2. Home Assistant **neu starten**.

## Einrichtung in Home Assistant

**Einstellungen → Geräte & Dienste → Integration hinzufügen → „HomeKit Türklingel“.**

1. **Türklingel einrichten**
   - *Name der Klingel*, z. B. „Haustür“ – wird Gerätename und Name in HomeKit.
   - *IP-Adresse des Shelly*, z. B. `192.168.1.50`. Die Integration prüft, ob unter dieser Adresse ein
     Shelly Gen1 antwortet.
   - *Benutzername/Kennwort* nur angeben, wenn am Shelly „Restrict Login“ aktiv ist.
2. **Kamera wählen** – die Kamera, deren Bild an der Tür gezeigt werden soll. Ist der Shelly-Eingang
   noch nicht entkoppelt, steht hier zusätzlich ein Hinweis.
3. **Fertig** – die Abschlussmeldung zeigt die **Webhook-URL** für den Shelly. Die URL steht später
   jederzeit in den **Optionen** der Klingel (Zahnrad am Integrationseintrag → *Konfigurieren*).

Optionen (nachträglich änderbar):

| Option | Standard | Bedeutung |
|---|---|---|
| Webhook nur von der Shelly-IP annehmen | an | Aufrufe von anderen Adressen werden mit 403 abgewiesen. |
| Abweichende erlaubte IP | leer | Falls der Aufruf über eine andere Adresse kommt (z. B. Reverse-Proxy). Leer = Shelly-IP. |
| „Klingelt“ ausschalten nach | 5 s | Auto-Aus des Binärsensors „Klingelt“. |
| Erreichbarkeit des Shelly überwachen | an | Legt „Shelly erreichbar“ an und fragt jede Minute ab. |
| Zusätzliche Push-Benachrichtigung | aus | Siehe [Push-Benachrichtigung](#push-benachrichtigung). |

## Shelly 1 (Gen1) einrichten

Alle Einstellungen in der Weboberfläche des Shelly (`http://<Shelly-IP>/`):

1. **Feste IP-Adresse:** *Internet & Security → WiFi Mode – Client → Set static IP address*
   oder besser eine **DHCP-Reservierung** im Router. Der Webhook-Filter und das Schalten des Gongs
   hängen an dieser Adresse.
2. **Eingang entkoppeln:** *Settings → Button Type → **Detached Switch*** → Speichern.
   Nur so schaltet der Taster das Relais nicht mehr selbst, und der Schalter „Mechanischer Gong“ kann
   den Gong stumm schalten. (Ist das nicht eingestellt, meldet die Integration einen
   Reparatur-Hinweis.)
3. **Webhook eintragen:** *I/O URL actions → **BUTTON SWITCHED ON URL***
   - Die Webhook-URL aus Home Assistant einfügen, z. B.
     `http://192.168.1.10:8123/api/webhook/<webhook-id>`
   - Das Häkchen zum **Aktivieren** setzen und **Speichern**.
4. **Zugangsschutz (empfohlen):** *Internet & Security → **Restrict Login*** → Benutzer und Kennwort
   setzen. Dieselben Daten in Home Assistant bei der Klingel eintragen – damit darf nur Home Assistant
   das Relais (den Gong) schalten.
5. **Gong anschließen:** Der mechanische Gong hängt am Relais-Ausgang des Shelly 1 (potentialfreier
   Kontakt, Klingeltrafo-Kreis). Arbeiten an Netzspannung nur durch eine Elektrofachkraft.

**Warum nur HTTP im LAN?** Shelly-Geräte der ersten Generation können URL-Aktionen nur unverschlüsselt
per HTTP aufrufen. Der Webhook wird deshalb ausschließlich aus dem lokalen Netz angenommen
(`local_only`) und standardmäßig nur von der Shelly-IP. Die Webhook-ID ist zufällig und lang.
Die URL muss die **interne** HTTP-Adresse von Home Assistant enthalten – keine externe/Cloud-Adresse
und kein HTTPS. Läuft Home Assistant ausschließlich mit HTTPS, kann ein Gen1-Shelly es nicht aufrufen.

## HomeKit koppeln

HomeKit zeigt eine Video-Türklingel nur, wenn **Kamera und Klingel im selben Zubehör** stecken. Dazu muss
die **Proxy-Kamera dieser Integration** als **eigenes HomeKit-Zubehör (Modus „accessory“)** exportiert
werden. Die HomeKit Bridge findet das Klingel-Event auf demselben Gerät dann automatisch.

### Weg 1: Reparatur-Hinweis (empfohlen)

1. **Einstellungen → System → Reparaturen** → „HomeKit-Türklingel für *Name* anlegen“ öffnen.
2. Bestätigen. Es wird ein neuer HomeKit-Bridge-Eintrag im Modus *accessory* für die Proxy-Kamera
   angelegt (Video-Codec `copy` setzt die HomeKit Bridge dabei automatisch).
3. In Home Assistant erscheint die Benachrichtigung **„HomeKit Pairing“** mit QR-Code und
   8-stelligem Code.
4. iPhone: **Home-App → + → Gerät hinzufügen** → QR-Code scannen oder *Weitere Optionen* → Code
   eingeben.

### Weg 2: manuell

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen → HomeKit Bridge** – eine **neue**
   Bridge anlegen (beliebige Domain wählen, wird gleich umgestellt).
2. Beim neuen Eintrag **Konfigurieren** → *Modus* = **accessory** → als Entität die **Kamera dieser
   Klingel** wählen (z. B. `camera.haustur_kamera`, nicht die Original-Reolink-Kamera).
3. Im Kamera-Schritt „Video-Codec kopieren“ für die Kamera ankreuzen (siehe Empfehlung unten).
4. Mit dem Code aus der Benachrichtigung „HomeKit Pairing“ in der Home-App koppeln.

> [!WARNING]
> Die Proxy-Kamera **nicht zusätzlich** in eine bestehende HomeKit Bridge (Modus *bridge*)
> aufnehmen. Kameras in einer Bridge zeigen keinen Türklingel-Dienst zuverlässig, und das Gerät
> taucht doppelt in der Home-App auf. Die Original-Kamera sollte in HomeKit ebenfalls nicht doppelt
> exportiert werden.

## Kamera-Empfehlung (Reolink)

- In der Reolink-Integration den **Sub-** bzw. **Fluent-Stream** verwenden und ihn in der Kamera auf
  **H.264** stellen (nicht H.265). HomeKit kann nur H.264 empfangen.
- **Video-Codec `copy`** (setzt der Zubehör-Ablauf aus dem Reparatur-Hinweis automatisch): Der Stream
  wird ohne Umrechnung weitergegeben – geringe Last und kurze Verzögerung.
- **Audio** ist optional: In den Optionen des HomeKit-Eintrags *Audio unterstützen* (`support_audio`)
  einschalten. Der Ton wird dann umgewandelt (transkodiert), was etwas Rechenleistung kostet.

## Push-Benachrichtigung

Zusätzlich zur HomeKit-Mitteilung kann die Integration eine Push-Nachricht senden:

1. Optionen der Klingel → *Zusätzliche Push-Benachrichtigung senden* einschalten.
2. *Benachrichtigungsdienste*: einen oder mehrere `notify`-Dienste, z. B. `mobile_app_iphone`.
3. *Titel* und *Text* anpassen; `{name}` wird durch den Namen der Klingel ersetzt.

Die Nachricht enthält den Snapshot als Bild (über die Entität „Letztes Klingeln“), ist bei der
Companion-App als *zeitkritisch* markiert und ersetzt die vorige Mitteilung derselben Klingel.

## Diagnose und Debug-Protokoll

- **Diagnose:** Gerät bzw. Integrationseintrag → ⋮ → **Diagnose herunterladen**. Enthält Einstellungen
  (Kennwort und Webhook-ID unkenntlich), Zähler (Webhook-Aufrufe, Klingeln, entprellt, abgelehnte IPs,
  Gong-Impulse und -Fehler, Snapshot- und Push-Fehler) und den letzten Webhook-Aufruf.
- **Debug-Protokoll** in `configuration.yaml`:

  ```yaml
  logger:
    default: warning
    logs:
      custom_components.homekit_tuerklingel: debug
  ```

  Alternativ: Integrationseintrag → ⋮ → *Debug-Protokollierung aktivieren*. Das Protokoll zeigt jeden
  Webhook-Aufruf mit **Methode und Quell-IP**, verworfene (entprellte) Aufrufe und die **Latenz**
  vom Eingang des Webhooks bis zum ausgelösten Event in Millisekunden.

## Fehlersuche

| Problem | Ursache und Lösung |
|---|---|
| Kamera erscheint in HomeKit, aber **ohne Klingel** | Die Kamera war vorher schon ohne Klingel exportiert; HomeKit merkt sich die Dienste eines Zubehörs. Zubehör in der **Home-App entfernen**, in Home Assistant den HomeKit-Eintrag des Zubehörs **zurücksetzen** (Aktion `homekit.reset_accessory` mit der Proxy-Kamera) oder den Eintrag **löschen und neu anlegen** (z. B. über den Reparatur-Hinweis), danach **neu koppeln**. |
| **HomePods klingeln nicht** | Home-App → Klingel-Zubehör → Einstellungen → *Mitteilungen* bzw. *Türklingel* einschalten. Prüfen, dass eine Steuerzentrale (HomePod/Apple TV) aktiv ist. Wird die Klingel gar nicht als Türklingel angezeigt, siehe erste Zeile (neu koppeln). |
| **Webhook kommt nicht an** | URL am Shelly prüfen (interne HTTP-Adresse, Port 8123, Häkchen aktiv). Mit Debug-Protokoll prüfen: Erscheint ein Aufruf mit „abgelehnt“, stimmt die Quell-IP nicht – Shelly-IP bzw. *Abweichende erlaubte IP* korrigieren. Erscheint gar nichts, erreicht der Shelly Home Assistant nicht (HTTPS-only, Firewall, VLAN). |
| **Gong läutet, obwohl „Mechanischer Gong“ aus ist** | Der Shelly-Eingang ist nicht entkoppelt: *Settings → Button Type → Detached Switch*. |
| **Gong läutet nie** | Schalter „Mechanischer Gong“ an? Zugangsdaten korrekt (sonst Reparatur/erneute Anmeldung)? „Gong-Dauer“ zu kurz für den Gong? |
| **Kein Bild / schwarzes Bild in HomeKit** | Stream auf **H.264** stellen (Sub/Fluent bei Reolink), `copy` nur mit H.264 verwenden; prüfen, ob die Original-Kamera in Home Assistant ein Bild liefert. |
| Klingeln wird **doppelt** gemeldet | „Entprellzeit“ erhöhen. |

## Umstieg von homebridge-shelly-doorbell

1. Diese Integration installieren und die Klingel einrichten.
2. Am Shelly unter *I/O URL actions → BUTTON SWITCHED ON URL* die bisherige Homebridge-URL durch die
   **Webhook-URL aus Home Assistant** ersetzen.
3. In der Home-App das alte Homebridge-Türklingel-Zubehör **entfernen** und das Plugin in Homebridge
   deinstallieren bzw. aus der Konfiguration nehmen.
4. Das neue Zubehör wie unter [HomeKit koppeln](#homekit-koppeln) beschrieben anlegen und koppeln.

## Entwicklung und Tests

Die Tests nutzen [`pytest-homeassistant-custom-component`](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)
(Python 3.14):

```bash
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements_test.txt
pytest tests --cov=custom_components.homekit_tuerklingel --cov-report=term-missing
```

- Die automatischen Prüfungen laufen in GitHub Actions unter **Linux** (`tests.yml`: pytest mit
  mindestens 90 % Abdeckung; `validate.yml`: hassfest und HACS-Prüfung).
- Unter Windows laufen die Tests lokal ebenfalls; `tests/conftest.py` hebt dafür die Socket-Sperre
  des Test-Plugins auf. Maßgeblich ist der Lauf unter Linux.
- Jede Änderung erhöht die Version in `custom_components/homekit_tuerklingel/manifest.json` und
  bekommt einen Eintrag im [CHANGELOG](CHANGELOG.md).

## Teststand

Stand **0.1.1 (2026-11-13)**.

### Im echten Home Assistant getestet (HA 2026.11.1, 2026-11-13)

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

### Durch automatische Tests geprüft (simulierter Shelly, simulierte Kamera)

116 Tests, Abdeckung 99 % (Home Assistant 2026.10.4, lokal unter Windows; Lauf unter Linux in
GitHub Actions). Geprüft sind:

- Einrichtung: Verbindungstest, Fehler (nicht erreichbar, falsches Kennwort, kein Shelly Gen1,
  doppelt), Hinweis „nicht entkoppelt“, Webhook-URL, erneute Anmeldung, nachträgliches Ändern, Optionen
- Webhook mit GET und POST, IP-Filter (erlaubt, abgelehnt mit 403, abgeschaltet, abweichende IP)
- Entprellung (Klingeln innerhalb der Entprellzeit wird verworfen)
- Gong: Relais-Aufruf `/relay/0?turn=on&timer=…` mit Anmeldung, stumm, Fehler, erneute Anmeldung bei 401
- Alle Entitäten inkl. Auto-Aus, Wiederherstellung nach Neustart, Erreichbarkeit
- Proxy-Kamera reicht Bild und Stream-Quelle durch
- Reparatur-Hinweise und Anlegen des HomeKit-Zubehörs mit der echten HomeKit-Integration (ohne
  HomeKit-Server): Der Eintrag wird angelegt, `linked_doorbell_sensor` zeigt automatisch auf das
  Klingel-Event, `video_codec` ist `copy`
- Push-Inhalt (Titel, Text, Bild-Anhang), Diagnose mit Schwärzung

### Im Code vorhanden, im echten Home Assistant noch nicht getestet

- Gong-Impuls am echten Shelly-Relais (insbesondere Gong-Dauer mit Nachkommastelle, z. B. `timer=0.5`)
- Reparatur-Hinweis „HomeKit-Türklingel anlegen“ im echten Home Assistant
- Echte Reolink-Kamera über die Proxy-Kamera, Live-Video und Snapshot in Apple Home
- Pairing in der Home-App, Klingelton auf HomePods, Mitteilung auf iPhone/Apple Watch
- Push-Benachrichtigung über die Companion-App
- Integrations-Icon (lokale Brand-Bilder, ab Home Assistant 2026.3)

## Lizenz

[MIT](LICENSE) – © 2026 rolhan95
