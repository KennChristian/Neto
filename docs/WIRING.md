# CJAP demo wiring guide — Reachy → laptop → monitor

How to physically connect and start the demo setup with the dual web UI
(P2.5): the **Audience view** on the external monitor, the **Maintenance view**
on the operator's laptop.

## What runs where

| Piece | Where | How |
|---|---|---|
| Voice robot (`supervaise.service`) | Reachy Mini (CM4 inside) | auto-starts on boot |
| Web server (`pi-dashboard.service`, port **8080**) | Reachy Mini | auto-starts on boot |
| Audience view | browser tab on the **laptop**, mirrored to the monitor | `http://reachy-mini.local:8080/audience` |
| Maintenance view | browser tab on the laptop's own screen | `http://reachy-mini.local:8080/maintain` |

The robot renders nothing itself — it serves data; the laptop does the
displaying. (The CM4 has HDMI silicon, but no browser is installed and the
port may not be exposed by the enclosure — the laptop route needs neither.)

## Physical connections

1. **Reachy Mini power** — its own supply. Wait ~60 s after power-on: both
   services start automatically ("armed — say Hey Cee-Jap" in the journal).
2. **Microphone / camera** — built in (ReSpeaker array + IMX708 camera),
   nothing to plug.
3. **Speaker** — the internal speaker is the default and the right choice for
   the demo (the XMOS echo-cancel that stops the robot hearing itself only
   works on the internal speaker; Bluetooth speakers disable it).
4. **Network** — Reachy and the laptop must be on the **same network**.
   Options: both on the venue Wi-Fi, or the phone-hotspot ("Paoooo") both
   join, or an Ethernet cable from Reachy to the router. The robot's mDNS
   name is `reachy-mini.local`; if that doesn't resolve, find the IP on the
   ops dashboard (`http://<ip>:8080/`) or the router's client list.
5. **Laptop → monitor** — HDMI cable from the laptop to the external
   monitor/projector. Set the monitor as an **extended** display.

```
   [Reachy Mini] ──(Wi-Fi/Ethernet, same LAN)── [Laptop] ──HDMI── [Monitor]
     camera+mic          serves :8080            2 browser         audience
     speaker                                     tabs              view
```

## Startup sequence

1. Power Reachy; wait for the wake chime state (~60 s).
2. Laptop: open `http://reachy-mini.local:8080/maintain` → enter the access
   key (default `cjap`; change by setting `CJ_DASH_KEY=` in
   `pi-dashboard.service` and restarting it). Check the **Health** chips:
   supervaise / mic / internet / camera should all be green (camera goes
   green a second or two after the first page load starts the stream).
3. Laptop: open a second browser window with
   `http://reachy-mini.local:8080/audience`, drag it to the external monitor,
   press **F11** (full screen).
4. Sound check: Maintenance → **Replay last** (if a previous answer exists) or
   say "Hey Cee-Jap" and ask a question. Confirm the turn shows up on both
   views and audio comes from the robot.

## Audience view layout

Camera feed on **top** (what Reachy sees); bottom-left = the **transcribed
question**; bottom-right = **what the Chief Justice says**. Prior turns fade
in under each panel. The page never shows errors — if a feed drops it falls
back to a neutral CJAP idle card.

## Operator quick reference (Maintenance view)

- **Mute / interrupt** — cuts the current answer mid-playback.
- **Force listen** — puts the robot into listening without the wake word.
- **Replay last** — replays the last spoken answer.
- **Entity dictionary overlay** — edit and Save; corrections apply to the very
  next turn (P0 hot-reload, no restart).
- Raw-vs-corrected ASR, NER log, routed topic/theme + token budget, per-stage
  latency, and wake/stop events are all on this page; deeper ops (service
  restart, audio routing, Wi-Fi/BT) live on the old dashboard at `/`.

## Verification

`python3 scripts/run_dashboard_smoke.py` on the Pi checks state latency,
event-to-visible time, camera fps, and page weights →
`reports/dashboard_smoke.json`. Last run 2026-08-11: state p50 4.3 ms,
event-to-visible 3.7 ms, camera 8.7 fps effective. UI logic tests:
`python3 tests/test_dashboard_ui.py` (7 tests, offline).

## Fallback: monitor plugged into Reachy directly

Only if a physical HDMI port is accessible on the robot's carrier board and a
kiosk stack is installed (`chromium` + a compositor, ~0.5 GB — not currently
installed). Then autostart `chromium --kiosk http://localhost:8080/audience`.
The laptop route above needs none of this and is the recommended demo setup.
