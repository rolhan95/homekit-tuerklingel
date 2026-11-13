# HomeKit Türklingel – HomeKit video doorbell for Home Assistant

**English** · [Deutsch](README.de.md)

A Home Assistant custom integration that turns **any doorbell button** plus **any camera** into a
**HomeKit video doorbell** – through Home Assistant's built-in HomeKit Bridge. No Homebridge, no
separate HomeKit server, no cloud.

The doorbell button can be anything that can call a URL (Shelly, ESPHome, Tasmota, scripts) or
anything that already exists as an entity in Home Assistant (Shelly, ESPHome, Zigbee, MQTT, …).
An existing mechanical chime can optionally be driven by any `switch` entity and muted at any time.

> [!IMPORTANT]
> **Test status 0.2.0:** Not everything described here has been tested on real hardware. Webhook,
> IP filter, debouncing, entities and the proxy camera were tested in a real Home Assistant with
> version 0.1.1. The new 0.2.0 features (entity triggers, chime via `switch`, migration from 0.1.x)
> are covered by automated tests only so far. **Never** tested for real: HomeKit pairing, HomePods,
> push notification, chime pulse on a real relay. See [Test status](#test-status).

---

## Contents

- [Purpose and how it works](#purpose-and-how-it-works)
- [Features and entities](#features-and-entities)
- [Requirements](#requirements)
- [Installation](#installation)
- [Setup in Home Assistant](#setup-in-home-assistant)
- [Trigger examples](#trigger-examples)
- [Mechanical chime](#mechanical-chime)
- [HomeKit pairing](#homekit-pairing)
- [Camera recommendations](#camera-recommendations)
- [Push notification](#push-notification)
- [Diagnostics and debug logging](#diagnostics-and-debug-logging)
- [Troubleshooting](#troubleshooting)
- [Upgrading from 0.1.x](#upgrading-from-01x)
- [Migrating from homebridge-shelly-doorbell](#migrating-from-homebridge-shelly-doorbell)
- [Development and tests](#development-and-tests)
- [Test status](#test-status)
- [License](#license)

---

## Purpose and how it works

```
Doorbell button ──► any device / entity
                      │
       ┌──────────────┴───────────────┐
       │ (a) Webhook GET/POST (LAN)    │ (b) HA entity changes
       │     Shelly, ESPHome, Tasmota, │     binary_sensor / input_boolean → "on"
       │     scripts …                 │     event / button / input_button → every event
       └──────────────┬───────────────┘
                      ▼
               Home Assistant ── debouncing ──► Doorbell event (device class doorbell)
                      │                              │
                      │                              ├─► HomeKit: chime on HomePods, notification with camera image
                      │                              ├─► Snapshot "Last ring", optional push
                      │                              └─► optional: switch pulse ──► mechanical chime (can be muted)
                      ▼
               Proxy camera (passes the chosen camera through, on the doorbell device)
```

1. A button press reaches the integration either as a **webhook call** (GET or POST, local network
   only) or as a **state change of an existing entity**. Both can be combined.
2. A **debounce time** discards repeated rings within a few seconds (multiple presses, contact bounce,
   two triggers for the same press).
3. The integration fires an **event entity with device class `doorbell`**, stores a snapshot and – if
   configured and not muted – switches the **chime switch** on for the set pulse duration.
4. The integration creates a **proxy camera** on the same device. When this camera is exported to
   HomeKit as its own accessory (mode *accessory*), the HomeKit Bridge automatically links the
   doorbell event of the same device (`linked_doorbell_sensor`) – HomeKit then shows a video
   doorbell.

## Features and entities

Each configured doorbell becomes one device with these entities (English names; German in brackets):

| Entity | Type | Meaning |
|---|---|---|
| Doorbell (Klingel) | `event` (device class `doorbell`) | Fired on every (debounced) ring. HomeKit links this entity as the doorbell. |
| Ringing (Klingelt) | `binary_sensor` | Turns on when it rings and off automatically after a configurable time (default 5 s). Handy for automations. |
| Last rung (Zuletzt geklingelt) | `sensor` (timestamp) | Time of the last ring. |
| Last ring (Letztes Klingeln) | `image` | Camera snapshot taken at the last ring. |
| Camera (Kamera) | `camera` | Proxy of the chosen camera (image and stream are passed through). This camera is exported to HomeKit. |
| Debounce time (Entprellzeit) | `number` (0–60 s, default 3 s) | Further rings within this time are discarded. |
| Mechanical chime (Mechanischer Gong) | `switch` | Only if a chime switch is selected. On = the chime rings; off = chime muted (e.g. at night). |
| Chime duration (Gong-Dauer) | `number` (0.2–10 s, default 1 s) | Only if a chime switch is selected. How long the chime switch stays on per ring. |

Also included:

- **Triggers (combinable):** webhook (GET/POST, `local_only`, optionally only from allowed source IPs
  or host names) and/or Home Assistant entities (`binary_sensor`, `input_boolean`, `event`,
  `button`, `input_button`).
- **Repair issue "Create HomeKit doorbell"**: offers to create the HomeKit accessory for the proxy
  camera (mode *accessory*, video codec `copy`).
- **Repair issue "Select chime switch"**: only after upgrading from 0.1.x if no chime switch could be
  taken over automatically.
- **Optional push notification** with snapshot to any `notify` services.
- **Diagnostics download** (secrets redacted) and detailed debug log (source, latency).

Not included: no own HomeKit server (HAP), no cloud, no Homebridge, no direct device protocol – the
integration does not talk to any doorbell hardware itself.

## Requirements

- **Home Assistant 2025.6.0 or newer** (minimum in `hacs.json`). Automated tests run against
  Home Assistant 2026.10.4; the real-world tests used 2026.11.1. Older versions are not tested.
  The integration icon (local brand images) is only shown from Home Assistant 2026.3 on.
- The **HomeKit Bridge** integration (built into Home Assistant) and an Apple Home with a home hub
  (HomePod or Apple TV) for notifications and the doorbell chime.
- A **camera entity** in Home Assistant (e.g. from the Reolink integration), ideally with an H.264
  stream.
- A **doorbell button** that either
  - can call an HTTP URL in the local network (webhook), or
  - already exists as an entity in Home Assistant.
- Optional: a `switch` entity that drives the mechanical chime.

## Installation

### HACS (custom repository)

1. Open HACS → menu (⋮) top right → **Custom repositories**.
2. Add repository `https://github.com/rolhan95/homekit-tuerklingel`, type **Integration**.
3. Search for "HomeKit Türklingel" and **Download**.
4. If Home Assistant asks for a restart, restart it. (On Home Assistant 2026.11.1 the integration
   could be added right after downloading, without a restart.)

### Manual

1. Copy the folder `custom_components/homekit_tuerklingel` from this repository into the
   `config/custom_components/` folder of Home Assistant
   (result: `config/custom_components/homekit_tuerklingel/manifest.json`).
2. Restart Home Assistant.

## Setup in Home Assistant

**Settings → Devices & services → Add integration → "HomeKit Türklingel".**

The first page asks for name, camera, "Accept rings via webhook", trigger entities and chime switch. If the webhook is enabled, a second page asks whether to accept it only from specific devices.

1. **Name** – e.g. "Front door". Used as device name and as name in HomeKit.
2. **Camera** – the camera whose image should be shown at the door. The integration passes it through
   via its own proxy camera.
3. **Triggers** – choose one or both:
   - **Webhook**: the doorbell device calls a URL. Optionally restrict it to **allowed sources**
     (IP addresses or host names, e.g. the IP of your Shelly). Calls from other addresses are
     rejected with HTTP 403. Host names are resolved once when the doorbell is loaded; after an IP
     change reload the doorbell.
   - **Entities**: one or more existing entities. `binary_sensor`/`input_boolean` ring when they
     change to "on"; `event`/`button`/`input_button` ring on every new event or press.
4. **Chime (optional)** – a `switch` entity that drives the mechanical chime. Leave empty if you have
   no chime or it should not be driven by Home Assistant.
5. **Done** – if the webhook is enabled, the final message shows the **webhook URL**. You can find it
   again at any time in the doorbell's **options** (cog on the integration entry → *Configure*).

All settings (triggers, allowed sources, chime switch, "Ringing" auto-off time, push) can be
changed later in the options.

**Why local network only?** The webhook is registered `local_only`: Home Assistant accepts it only
from the local network, never via the external/cloud URL. Many devices (e.g. Shelly Gen1) can only
call plain HTTP, so the URL uses Home Assistant's **internal** address, e.g.
`http://192.168.1.10:8123/api/webhook/<webhook-id>`. The webhook ID is random and long – treat the
URL like a password. If possible, also enable the source filter.

## Trigger examples

> [!NOTE]
> The webhook itself was tested with real GET and POST calls (with 0.1.1). The device configurations
> below follow the respective manufacturer documentation; none of them has been tested by the author
> with a real device yet. Replace `192.168.1.10:8123` and `<webhook-id>` with the URL from the options.

### Shelly Gen1 (e.g. Shelly 1) – I/O URL action

In the Shelly web UI (`http://<shelly-ip>/`):

1. *Settings → Button Type → **Detached Switch*** – so the button no longer switches the relay
   itself (needed if the relay drives the chime and should be mutable).
2. *I/O URL actions → **BUTTON SWITCHED ON URL*** → paste the webhook URL, tick **enabled**, save.
3. Give the Shelly a fixed IP (DHCP reservation) and enter this IP as allowed source.

### Shelly Gen2/Plus/Pro – Actions / Webhooks

In the Shelly web UI: **Actions** (newer firmware: **Webhooks**) → *Create* → as condition the input
event, e.g. *Input 0 – button pushed* (input type Button) or *switched on* (input type Switch) → as
action **URL** = the webhook URL → save. Set the input/output mode to **Detached** if the relay drives
the chime.

### ESPHome – `http_request` on press

```yaml
http_request:
  timeout: 3s

binary_sensor:
  - platform: gpio
    name: "Doorbell button"
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

If the ESPHome device is already added to Home Assistant, you can instead select its
`binary_sensor` directly as an **entity trigger** – no webhook needed.

### Tasmota – rule with WebSend

In the Tasmota console:

```
Rule1 ON Switch1#State=1 DO WebSend [192.168.1.10:8123] /api/webhook/<webhook-id> ENDON
Rule1 1
```

`WebSend` sends an HTTP GET. Depending on the switch mode a rule on `Switch1#State` may stop the switch
from toggling the relay – check the Tasmota documentation (`SwitchMode`, `SetOption114`) if the relay
should drive the chime separately.

### Alternative: entity from an existing integration

Instead of a webhook, use the entity that an integration already provides, for example:

- **Shelly integration**: the input of the Shelly (Gen1: `binary_sensor` "Input", possibly disabled by
  default – enable it in the entity settings; Gen2+: `event` entity of the input in button mode).
- **Zigbee (ZHA/Zigbee2MQTT)** buttons or contacts, **MQTT** `binary_sensor`s, **ESPHome**
  `binary_sensor`s, or a helper `input_button`.

Note: a `binary_sensor` that becomes "on" coming from *unavailable* or *unknown* (e.g. after a
restart) does not ring. The webhook is usually the fastest path, because it does not depend on the
update rate of another integration.

## Mechanical chime

- Select any **`switch` entity** as chime switch (e.g. the relay of a Shelly in the Shelly
  integration). On every ring it is switched **on for the chime duration** and then **off** again.
  Overlapping pulses are not started twice.
- The switch **"Mechanical chime"** mutes the chime (e.g. at night); the **"Chime duration"** number
  sets the pulse length (0.2–10 s). Both entities only exist if a chime switch is selected.
- **Important:** muting only works if the **button does not switch the relay directly**. On a Shelly
  set the input to **"Detached"** (Gen1: *Button Type → Detached Switch*; Gen2+: *Input/Output
  settings → Detached*). Otherwise the chime rings by hardware, regardless of Home Assistant.
- Wiring the chime (bell transformer, relay contact) is outside the scope of this integration. Work on
  mains voltage must only be done by a qualified electrician.

## HomeKit pairing

HomeKit only shows a video doorbell if **camera and doorbell are in the same accessory**. For this the
**proxy camera of this integration** must be exported as **its own HomeKit accessory (mode
"accessory")**. The HomeKit Bridge then finds the doorbell event on the same device automatically.

### Option 1: repair issue (recommended)

1. **Settings → System → Repairs** → open "Create HomeKit doorbell for *name*".
2. Confirm. A new HomeKit Bridge entry in mode *accessory* is created for the proxy camera (video
   codec `copy`).
3. Home Assistant shows the notification **"HomeKit Pairing"** with QR code and 8-digit code.
4. iPhone: **Home app → + → Add Accessory** → scan the QR code or *More options* → enter the code.

### Option 2: manual

1. **Settings → Devices & services → Add integration → HomeKit Bridge** – create a **new** bridge (any
   domain, it is changed in the next step).
2. **Configure** the new entry → *Mode* = **accessory** → select the **camera of this doorbell** (e.g.
   `camera.front_door_camera`, not the original camera).
3. In the camera step tick "copy video codec" for the camera (see recommendations below).
4. Pair it in the Home app with the code from the "HomeKit Pairing" notification.

> [!WARNING]
> Do **not** additionally add the proxy camera to an existing HomeKit Bridge (mode *bridge*). Cameras
> inside a bridge do not reliably show the doorbell service, and the device would appear twice in the
> Home app. Do not export the original camera to HomeKit as well.

## Camera recommendations

- Use an **H.264** stream – HomeKit can only receive H.264. For Reolink use the **sub** or **fluent**
  stream and set it to H.264 in the camera (not H.265).
- **Video codec `copy`** (set automatically by the repair issue): the stream is passed through
  unchanged – low load and short delay. Only works with H.264.
- If your camera only delivers **H.265**, choose **`libx264`** as video codec in the options of the
  HomeKit entry. The stream is then transcoded, which costs considerable CPU.
- **Audio** is optional: enable *Support audio* (`support_audio`) in the options of the HomeKit entry.
  Audio is transcoded, which costs some CPU.

## Push notification

In addition to the HomeKit notification the integration can send a push message:

1. Doorbell options → enable *additional push notification*.
2. *Notification services*: one or more `notify` services, e.g. `mobile_app_iphone`.
3. Adjust *title* and *message*; `{name}` is replaced with the doorbell name.

The message contains the snapshot as image (via the "Last ring" entity), is marked *time-sensitive*
for the Companion app and replaces the previous notification of the same doorbell.

## Diagnostics and debug logging

- **Diagnostics:** device or integration entry → ⋮ → **Download diagnostics**. Contains the settings
  (webhook ID redacted), counters (webhook calls, entity triggers, rings, debounced, rejected IPs, chime
  pulses and errors, snapshot and push errors) and the last trigger.
- **Debug log:** integration entry → ⋮ → *Enable debug logging*, or in `configuration.yaml`:

  ```yaml
  logger:
    default: warning
    logs:
      custom_components.homekit_tuerklingel: debug
  ```

  The log shows each trigger with its **source** (webhook method and source IP, or entity ID),
  discarded (debounced) rings, chime pulses and the **latency** from receiving the trigger to the
  fired event in milliseconds.

## Troubleshooting

| Problem | Cause and solution |
|---|---|
| Camera appears in HomeKit but **without doorbell** | The camera was exported to HomeKit before without doorbell; HomeKit remembers the services of an accessory. **Remove** the accessory in the Home app, **reset** it in Home Assistant (action `homekit.reset_accessory` with the proxy camera) or **delete and recreate** the HomeKit entry (e.g. via the repair issue), then **pair again**. Make sure you exported the *proxy* camera, not the original. |
| **HomePods do not chime** | Home app → doorbell accessory → settings → enable notifications/doorbell. Check that a home hub (HomePod/Apple TV) is active. If it is not shown as doorbell at all, see the first row. |
| **Webhook does not arrive** | Check the URL on the device (internal HTTP address, port 8123, no external/cloud URL). Enable the debug log: no entry at all → the device does not reach Home Assistant (HTTPS-only setup, firewall, VLAN, wrong port). |
| Webhook answers **403** | The source filter rejected the call. The log shows the rejected IP – add it to the allowed sources (or a host name that resolves to it) and reload the doorbell. Behind a reverse proxy Home Assistant may see the proxy's IP. |
| **Entity trigger does not ring** | `binary_sensor`/`input_boolean` only ring on a change to "on" (not from *unavailable*/*unknown*). Check in the entity history that the state really changes. Is the debounce time too long? |
| **Chime rings although "Mechanical chime" is off** | The button switches the relay directly. Set the input to **Detached** (Shelly: *Detached Switch*). |
| **Chime never rings** | Is a chime switch selected and "Mechanical chime" on? Can the switch be switched manually? Is "Chime duration" too short for your chime? See the debug log for errors. |
| **Black / no image in HomeKit** | Use an **H.264** stream; use `copy` only with H.264, otherwise `libx264`. Check that the original camera shows an image in Home Assistant. |
| Ring is reported **twice** | Increase the "Debounce time". Webhook and entity trigger for the same button count as two triggers – the debounce time catches that. |

## Upgrading from 0.1.x

Version 0.2.0 removes the direct Shelly Gen1 HTTP connection (credentials, connection test, "Shelly
reachable", "input not detached" notice). The existing doorbell is **migrated automatically**:

- The **webhook URL stays the same** – nothing needs to change on the Shelly.
- The source filter keeps its setting and allows the **IP of the Shelly** (or the previously set
  deviating IP).
- **Chime:** if the same Shelly is also added to Home Assistant's **Shelly integration**, its switch is
  taken over as chime switch. Otherwise a repair issue **"Select chime switch"** appears: add the
  Shelly to the Shelly integration (or use another switch) and select the switch in the doorbell's
  options. Until then the chime is not driven.
- The entity "Shelly reachable" and the stored Shelly credentials are removed.

<!-- KOORDINATOR: nach dem Live-Test der Migration ergänzen, was im echten HA beobachtet wurde. -->

## Migrating from homebridge-shelly-doorbell

1. Install this integration and set up the doorbell (trigger: webhook; allowed source: the Shelly IP;
   chime: the Shelly's switch from the Shelly integration, if desired).
2. On the Shelly, replace the previous Homebridge URL under *I/O URL actions → BUTTON SWITCHED ON URL*
   with the **webhook URL from Home Assistant**.
3. **Remove** the old Homebridge doorbell accessory in the Home app and remove the plugin from
   Homebridge.
4. Create and pair the new accessory as described under [HomeKit pairing](#homekit-pairing).

## Development and tests

The tests use [`pytest-homeassistant-custom-component`](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)
with **Python 3.14**:

```bash
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements_test.txt
pytest tests --cov=custom_components.homekit_tuerklingel --cov-report=term-missing
```

- The automatic checks run in GitHub Actions on **Linux** (`tests.yml`: pytest with at least 90 %
  coverage; `validate.yml`: hassfest and HACS validation).
- Tests also run locally on Windows; the Linux run is authoritative.
- **The tests never use the real network:** devices, cameras, zeroconf/mDNS and the HomeKit server are
  replaced by simulations, so a test run never announces accessories in your network.
- Every change bumps the version in `custom_components/homekit_tuerklingel/manifest.json` and gets an
  entry in the [CHANGELOG](CHANGELOG.md) (German).

## Test status

Status **0.2.0 (2026-11-13)**.

### Tested in a real Home Assistant (with 0.1.1, HA 2026.11.1, Shelly 1 Gen1, Reolink)

These functions still exist in 0.2.0; a live re-test with 0.2.0 is pending.
<!-- KOORDINATOR: nach dem Live-Test mit 0.2.0 bestätigen bzw. ergänzen. -->

- Installation via HACS, adding without restart (HA 2026.11.1)
- Webhook with GET and POST (`local_only`), event 1–2 ms after the call
- Source filter: calls from a foreign IP are rejected with 403; a deviating allowed IP works
- Debouncing: a second call within 3 s is discarded
- Entities: "Ringing" turns off after 5 s; "Last rung" and snapshot "Last ring" are set
- Proxy camera delivers the live image of a real Reolink camera (also scaled)

### Covered by automated tests only (0.2.0)

<!-- KOORDINATOR: Anzahl Tests und Abdeckung des 0.2.0-Laufs eintragen. -->

- Setup and options: name, camera, webhook with source filter (IP and host name), entity triggers,
  chime switch
- Entity triggers: `binary_sensor`/`input_boolean` on change to "on", `event`/`button`/`input_button`
  on every event; no ring from *unavailable*/*unknown*
- Chime via `switch`: pulse on/off, muted, errors
- Migration from 0.1.x: webhook URL kept, allowed IP taken over, chime switch from the Shelly
  integration or repair issue "Select chime switch"
- Repair issue and creation of the HomeKit accessory with the real HomeKit integration (without
  HomeKit server): `linked_doorbell_sensor` points to the doorbell event, `video_codec` is `copy`
- Push content (title, message, image), diagnostics with redaction

### Not yet tested in a real Home Assistant

- Entity triggers (Shelly, ESPHome, Zigbee, MQTT entities)
- Chime via `switch`, mute switch and chime duration on real hardware
- Migration of a real 0.1.x installation
- Trigger examples with real devices (Shelly Gen1 URL action, Shelly Gen2+, ESPHome, Tasmota)
- Repair issue "Create HomeKit doorbell" in a real Home Assistant
- HomeKit pairing, chime on HomePods, notification on iPhone/Apple Watch, live video in Apple Home
- Push notification via the Companion app
- Integration icon (local brand images, from Home Assistant 2026.3)

## License

[MIT](LICENSE) – © 2026 rolhan95
