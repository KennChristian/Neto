#!/usr/bin/env python3
"""Reachy Mini troubleshooting dashboard — phone/tablet web UI on the LAN.

Stdlib only (no venv, no pip) so it works when the internet is down —
which is exactly when troubleshooting happens. Serves:

    GET  /            mobile-friendly status page (inline CSS/JS, no CDN)
    GET  /api/status  everything as JSON
    GET  /api/logs    journal tail  (?unit=supervaise|speaker-watchdog&lines=N)
    POST /api/action  {"action": "<name>"} from the strict allowlist below

Runs as user pollen under pi-dashboard.service; service/reboot actions go
through passwordless sudo. No auth — LAN-only by design.
"""
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:  # P2.5 dual demo UI (/audience, /maintain) — optional module, fail-open
    import supervaise_ui
except Exception as _e:
    supervaise_ui = None
    print(f"[dashboard] supervaise_ui unavailable: {_e}")

PORT = 8080
HOME = os.path.expanduser("~")
AUDIO_OUT = os.path.join(HOME, "bin", "audio-out")
WAKE_MODEL = os.path.join(HOME, "Supervaise-Reachy-Mini-Project-main",
                          "app", "wake", "models", "hey_cee_jap.onnx")
TEST_WAV = os.path.join(HOME, "fillers", "01.wav")

UNITS = {
    "supervaise": "supervaise.service",
    "speaker-watchdog": "speaker-watchdog.service",
    "bluealsa": "bluealsa.service",
    "pi-dashboard": "pi-dashboard.service",
    "wifi-fallback": "wifi-fallback.service",
}

SPEAKERS = {
    "Sony ULT FIELD 1": "50:1B:6A:8B:16:F2",
    "Marshall EMBERTON": "04:21:44:84:1F:C1",
}

ACTIONS = {
    "restart-app":      ["sudo", "-n", "systemctl", "restart", "supervaise.service"],
    "stop-app":         ["sudo", "-n", "systemctl", "stop", "supervaise.service"],
    "start-app":        ["sudo", "-n", "systemctl", "start", "supervaise.service"],
    "start-watchdog":   ["sudo", "-n", "systemctl", "start", "speaker-watchdog.service"],
    "stop-watchdog":    ["sudo", "-n", "systemctl", "stop", "speaker-watchdog.service"],
    "audio-internal":   [AUDIO_OUT, "internal"],
    "audio-sony":       [AUDIO_OUT, "sony"],
    "audio-marshall":   [AUDIO_OUT, "marshall"],
    "test-sound":       ["aplay", "-q", TEST_WAV],
    "tagalog-sample":   ["aplay", "-q", os.path.join(HOME, "demo_clips", "tagalog_sample_2026-08-13.wav")],
    "activate-listening": ["touch", "/dev/shm/cj_wake_trigger"],
    "enroll-voice":     ["touch", "/dev/shm/cj_enroll_trigger"],
    "gate-on":          ["touch", os.path.join(HOME, "speaker_id", "enabled")],
    "gate-off":         ["rm", "-f", os.path.join(HOME, "speaker_id", "enabled")],
    "reboot":           ["sudo", "-n", "reboot"],
}

WAKE_LIVE = "/dev/shm/cj_wake_live.json"
WAKE_EVENTS = "/dev/shm/cj_wake_events.jsonl"
TRANSCRIPT = "/dev/shm/cj_transcript.jsonl"
SPEAKER_LAST = "/dev/shm/cj_speaker_last.json"
SPEAKER_ENROLLED = os.path.join(HOME, "speaker_id", "enrolled.npz")
SPEAKER_ENABLED = os.path.join(HOME, "speaker_id", "enabled")
CERT_DIR = os.path.join(HOME, "pi_dashboard", "certs")
HTTPS_PORT = 8443

_play_lock = threading.Lock()   # serialize phone-mic playback


def wifi_status():
    saved, current = [], None
    _, out = run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show"])
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and "wireless" in parts[1]:
            saved.append(parts[0])
            if parts[2]:
                current = parts[0]
    return saved, current


def wifi_scan(rescan=False):
    cmd = ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "dev", "wifi", "list"]
    if rescan:
        cmd += ["--rescan", "yes"]
    _, out = run(cmd, timeout=25)
    nets, seen = [], set()
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 4 or not parts[0] or parts[0] in seen:
            continue
        seen.add(parts[0])
        nets.append({"ssid": parts[0], "signal": int(parts[1] or 0),
                     "security": parts[2] or "open",
                     "in_use": parts[3] == "*"})
    nets.sort(key=lambda n: -n["signal"])
    return nets


SETUP_CON = "ReachySetup"   # wifi_fallback.sh setup-hotspot profile name


def hotspot_active():
    _, out = run(["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"])
    return SETUP_CON in out.splitlines()


def _wifi_join(ssid, password=None):
    saved, _ = wifi_status()
    if password:
        code, out = run(["nmcli", "dev", "wifi", "connect", ssid,
                         "password", password], timeout=45)
    elif ssid in saved:
        code, out = run(["nmcli", "connection", "up", "id", ssid], timeout=45)
    else:
        code, out = run(["nmcli", "dev", "wifi", "connect", ssid], timeout=45)
    return code == 0, out[-300:]


def wifi_connect(ssid, password=None):
    """Bring up a saved connection, or join a new network. NOTE: on success
    the phone loses the dashboard until it re-joins the same network."""
    if not ssid or len(ssid) > 32:
        return False, "invalid ssid"
    if hotspot_active():
        # The phone is on the setup hotspot: joining a network takes the AP
        # (and this HTTP connection) down, so reply first and switch in the
        # background; on failure the hotspot comes straight back.
        def _switch():
            run(["nmcli", "connection", "down", SETUP_CON], timeout=15)
            ok, out = _wifi_join(ssid, password)
            if not ok:
                print(f"[wifi-fallback] join {ssid!r} failed ({out}) — hotspot back up")
                run(["nmcli", "connection", "up", SETUP_CON], timeout=20)
        threading.Thread(target=_switch, daemon=True).start()
        return True, (f'trying to join "{ssid}" — reconnect your phone to that '
                      "network and reopen the dashboard; if joining fails, the "
                      "ReachyMini-Setup hotspot returns within a minute")
    return _wifi_join(ssid, password)


MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")


def bt_devices():
    """All devices bluetoothctl knows about (paired + recently discovered)."""
    devices = []
    _, out = run(["bluetoothctl", "devices"], timeout=8)
    for line in out.splitlines():
        parts = line.split(" ", 2)          # "Device <MAC> <Name>"
        if len(parts) == 3 and parts[0] == "Device" and MAC_RE.match(parts[1]):
            if parts[2] == parts[1].replace(":", "-"):
                continue        # unnamed BLE address, not a pairable speaker
            devices.append({"mac": parts[1], "name": parts[2]})
    for d in devices:
        _, info = run(["bluetoothctl", "info", d["mac"]], timeout=5)
        d["paired"] = "Paired: yes" in info
        d["connected"] = "Connected: yes" in info
        d["audio"] = "Audio Sink" in info or "audio-card" in info
    devices.sort(key=lambda d: (not d["connected"], not d["paired"],
                                d["name"].lower()))
    return devices


def bt_scan():
    """Discover nearby devices, then return the full list. Discovered
    devices stay in the BlueZ cache long enough for a follow-up pair."""
    run(["bluetoothctl", "--timeout", "8", "scan", "on"], timeout=15)
    return bt_devices()


def bt_action(mac, action):
    if not MAC_RE.match(mac or ""):
        return False, "invalid MAC"
    if action == "connect":
        code, out = run(["bluetoothctl", "connect", mac], timeout=30)
    elif action == "disconnect":
        code, out = run(["bluetoothctl", "disconnect", mac], timeout=15)
    elif action == "pair":
        code, out = run(["bluetoothctl", "pair", mac], timeout=35)
        if code != 0 and "AlreadyExists" not in out:
            return False, out[-300:]
        run(["bluetoothctl", "trust", mac], timeout=10)
        code, out = run(["bluetoothctl", "connect", mac], timeout=30)
    else:
        return False, f"unknown bt action {action!r}"
    return code == 0, out[-300:]


APP_VENV_PY = os.path.join(HOME, "Supervaise-Reachy-Mini-Project-main",
                           "app", ".venv", "bin", "python")
SAY_HELPER = os.path.join(HOME, "pi_dashboard", "say_text_helper.py")


def say_text(text):
    """Speak typed text in the CJ voice (cloud TTS via the app venv)."""
    text = (text or "").strip()
    if not text or len(text) > 500:
        return False, "text empty or over 500 characters"
    wav = tempfile.mktemp(dir="/dev/shm", suffix=".wav")
    try:
        code, out = run([APP_VENV_PY, SAY_HELPER, text, wav], timeout=60)
        if code != 0:
            return False, out[-250:]
        with _play_lock:
            name = _publish_sentence_copy(wav)
            _publish_say_speaking(text, done=False, wav=name,
                                  dur=_wav_duration(wav))
            mode = _avatar_mode()
            if mode:   # /face-avatar page is live: give it its head start
                time.sleep(_avatar_lag())
            _publish_say_speaking(text, done=False, wav=name,
                                  dur=_wav_duration(wav), play_ts=time.time())
            if mode == "solo":   # avatar is the only voice
                time.sleep(_wav_duration(wav) or 2.0)
                code, out = 0, ""
            else:
                code, out = run(["aplay", "-q", wav], timeout=120)
            _publish_say_speaking(text, done=True)
        return code == 0, out[-200:]
    finally:
        if os.path.exists(wav):
            os.unlink(wav)


def _publish_say_speaking(text, done, wav=None, dur=None, play_ts=None):
    """Mirror the app's /dev/shm/cj_speaking.json feed for typed say-text
    lines so the /face-avatar and /audience pages speak/animate them too
    (fails open). wav = basename of the /dev/shm sentence copy."""
    try:
        tmp = "/dev/shm/cj_speaking.json.tmp"
        doc = {"ts": time.time(), "spoken": [text],
               "current": None if done else text, "done": done,
               "interrupted": False, "emotion": None,
               "wav": None if done else wav, "dur": dur}
        if play_ts is not None:
            doc["play_ts"] = play_ts
        with open(tmp, "w") as f:
            json.dump(doc, f)
        os.replace(tmp, "/dev/shm/cj_speaking.json")
    except OSError:
        pass


def _publish_sentence_copy(wav):
    """Same contract as stream_speak.publish_sentence_wav (kept in step by
    hand — the dashboard runs on system python, not the app venv)."""
    try:
        import glob as _glob
        name = f"cj_sent_{int(time.time()*1000)}.wav"
        tmp = "/dev/shm/." + name
        with open(wav, "rb") as src, open(tmp, "wb") as dst:
            dst.write(src.read())
        os.replace(tmp, "/dev/shm/" + name)
        for p in sorted(_glob.glob("/dev/shm/cj_sent_*.wav"))[:-8]:
            try:
                os.unlink(p)
            except OSError:
                pass
        return name
    except OSError:
        return None


def _wav_duration(path):
    try:
        import wave
        with wave.open(path, "rb") as w:
            return round(w.getnframes() / float(w.getframerate()), 2)
    except Exception:
        return None


def _avatar_mode():
    try:
        if time.time() - os.path.getmtime("/dev/shm/cj_avatar_audio") > 15:
            return None   # avatar page stopped heart-beating
        with open("/dev/shm/cj_avatar_audio") as f:
            return f.read().strip() or "solo"
    except OSError:
        return None


def _avatar_lag():
    try:
        return max(0.0, min(4.0, float(open("/dev/shm/cj_avatar_lag").read())))
    except (OSError, ValueError):
        return 0.8


def play_phone_audio(blob):
    """Decode whatever container the phone's MediaRecorder produced and play
    it out the robot's current audio route."""
    with tempfile.NamedTemporaryFile(dir="/dev/shm", suffix=".bin",
                                     delete=False) as f:
        f.write(blob)
        src = f.name
    wav = src + ".wav"
    try:
        code, out = run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                         "-ar", "48000", "-ac", "1", wav], timeout=20)
        if code != 0:
            return False, out[-200:]
        with _play_lock:
            code, out = run(["aplay", "-q", wav], timeout=60)
        return code == 0, out[-200:]
    finally:
        for p in (src, wav):
            if os.path.exists(p):
                os.unlink(p)


def run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def unit_state(unit):
    _, out = run(["systemctl", "show", unit, "--no-pager",
                  "-p", "ActiveState,SubState,ActiveEnterTimestamp"])
    d = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return {
        "active": d.get("ActiveState", "?"),
        "sub": d.get("SubState", "?"),
        "since": d.get("ActiveEnterTimestamp", ""),
    }


def internet_up(timeout=2.5):
    try:
        socket.create_connection(("api.openai.com", 443), timeout=timeout).close()
        return True
    except OSError:
        return False


def wifi_info():
    info = {"essid": None, "signal_dbm": None, "quality": None, "ip": None}
    _, out = run(["iwconfig", "wlan0"], timeout=5)
    for tok in out.replace("  ", "\n").splitlines():
        tok = tok.strip()
        if tok.startswith("ESSID:"):
            info["essid"] = tok.split(":", 1)[1].strip().strip('"')
        elif "Signal level=" in tok:
            info["signal_dbm"] = tok.split("Signal level=")[1].split()[0]
        elif "Link Quality=" in tok:
            info["quality"] = tok.split("Link Quality=")[1].split()[0]
    _, ip = run(["hostname", "-I"], timeout=5)
    info["ip"] = ip.split()[0] if ip.split() else None
    return info


def system_info():
    try:
        temp_c = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
    except Exception:
        temp_c = None
    try:
        up_s = float(open("/proc/uptime").read().split()[0])
    except Exception:
        up_s = None
    mem = {}
    try:
        for line in open("/proc/meminfo"):
            k, v = line.split(":", 1)
            if k in ("MemTotal", "MemAvailable"):
                mem[k] = int(v.strip().split()[0])
    except Exception:
        pass
    du = shutil.disk_usage("/")
    throttled = run(["vcgencmd", "get_throttled"], timeout=5)[1]
    return {
        "temp_c": round(temp_c, 1) if temp_c else None,
        "load": os.getloadavg(),
        "uptime_s": int(up_s) if up_s else None,
        "mem_used_pct": round(100 * (1 - mem["MemAvailable"] / mem["MemTotal"]), 1) if mem else None,
        "disk_used_pct": round(100 * du.used / du.total, 1),
        "throttled": throttled.replace("throttled=", "") or None,
    }


def audio_info():
    route = None
    try:
        for line in open(os.path.join(HOME, ".asoundrc.route")):
            if line.startswith("# Route:"):
                route = line.split(":", 1)[1].strip().rstrip(".")
                break
    except Exception:
        pass
    speakers = {}
    for name, mac in SPEAKERS.items():
        _, out = run(["bluetoothctl", "info", mac], timeout=5)
        speakers[name] = "Connected: yes" in out
    return {"route": route, "speakers": speakers}


def wake_info():
    _, out = run(["systemctl", "show", "supervaise.service", "-p", "Environment"])
    env = {}
    for tok in out.replace("Environment=", "").split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            if k.startswith(("CJ_", '"CJ_')):
                env[k.strip('"')] = v.strip('"')
    model = {}
    if os.path.exists(WAKE_MODEL):
        st = os.stat(WAKE_MODEL)
        model = {"file": os.path.basename(WAKE_MODEL),
                 "installed": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))}
    return {"env": env, "model": model}


_thr_cache = {"t": 0.0, "v": 0.5}


def wake_threshold():
    if time.time() - _thr_cache["t"] > 10:
        try:
            _thr_cache["v"] = float(wake_info()["env"].get("CJ_WAKE_OWW_THRESHOLD", 0.5))
        except Exception:
            pass
        _thr_cache["t"] = time.time()
    return _thr_cache["v"]


def wake_live():
    out = {"live": False, "threshold": wake_threshold(), "events": []}
    try:
        d = json.load(open(WAKE_LIVE))
        age = time.time() - d.get("ts", 0)
        out.update(d)
        out["age"] = round(age, 2)
        out["live"] = age < 2.0
    except Exception:
        pass
    try:
        lines = open(WAKE_EVENTS).read().splitlines()[-8:]
        out["events"] = [json.loads(ln) for ln in lines][::-1]
    except Exception:
        pass
    out["transcript"] = []
    try:
        lines = open(TRANSCRIPT).read().splitlines()[-10:]
        out["transcript"] = [json.loads(ln) for ln in lines]
    except Exception:
        pass
    sp = {"enrolled": os.path.exists(SPEAKER_ENROLLED),
          "enabled": os.path.exists(SPEAKER_ENABLED), "last": None}
    try:
        sp["last"] = json.load(open(SPEAKER_LAST))
    except Exception:
        pass
    out["speaker"] = sp
    return out


def journal(unit, lines):
    _, out = run(["journalctl", "-u", UNITS.get(unit, "supervaise.service"),
                  "-n", str(lines), "--no-pager", "-o", "short"], timeout=15)
    return out


def status():
    return {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hostname": socket.gethostname(),
        "internet": internet_up(),
        "wifi": wifi_info(),
        "services": {k: unit_state(v) for k, v in UNITS.items()},
        "reachy_daemon": run(["pgrep", "-f", "reachy_mini.daemon"], timeout=5)[0] == 0,
        "audio": audio_info(),
        "wake": wake_info(),
        "system": system_info(),
    }


PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>Reachy Mini</title>
<style>
  :root { --bg:#111418; --card:#1b2027; --line:#2a313b; --fg:#e8eaed; --dim:#9aa4b0;
          --ok:#3fb96f; --bad:#e05555; --warn:#e0a542; --accent:#4a90d9; }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--fg); font:16px/1.45 -apple-system,system-ui,sans-serif;
         padding:12px; max-width:640px; margin:0 auto; }
  h1 { font-size:20px; margin:4px 0 12px; }
  h1 small { color:var(--dim); font-weight:400; font-size:13px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:14px; margin-bottom:12px; }
  .card h2 { font-size:14px; text-transform:uppercase; letter-spacing:.06em;
             color:var(--dim); margin-bottom:10px; }
  .row { display:flex; justify-content:space-between; align-items:center;
         padding:5px 0; gap:8px; }
  .row + .row { border-top:1px solid var(--line); }
  .lbl { color:var(--dim); }
  .val { text-align:right; word-break:break-all; }
  .dot { display:inline-block; width:10px; height:10px; border-radius:50%;
         margin-right:6px; vertical-align:baseline; }
  .ok { background:var(--ok); } .bad { background:var(--bad); } .warn { background:var(--warn); }
  .btns { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }
  button { background:#242b34; color:var(--fg); border:1px solid var(--line);
           border-radius:10px; padding:12px 14px; font-size:15px; flex:1 1 40%;
           min-height:44px; cursor:pointer; }
  button:active { background:var(--accent); }
  button.danger { border-color:#5a2e2e; color:#f2b8b8; }
  pre { background:#0d1013; border:1px solid var(--line); border-radius:8px;
        padding:10px; font-size:11px; line-height:1.5; overflow-x:auto;
        white-space:pre-wrap; word-break:break-all; max-height:45vh; overflow-y:auto; }
  #toast { position:fixed; bottom:16px; left:50%; transform:translateX(-50%);
           background:var(--accent); color:#fff; padding:10px 18px; border-radius:10px;
           display:none; z-index:9; font-size:14px; max-width:90vw; }
  select { background:#242b34; color:var(--fg); border:1px solid var(--line);
           border-radius:8px; padding:8px; font-size:14px; }
</style></head><body>
<h1>Reachy Mini <small id="meta">connecting…</small></h1>

<div class="card"><h2>Robot app (supervaise)</h2>
  <div class="row"><span class="lbl">Status</span><span class="val" id="svc-app"></span></div>
  <div class="row"><span class="lbl">Since</span><span class="val" id="svc-app-since"></span></div>
  <div class="row"><span class="lbl">Wake model</span><span class="val" id="wake-model"></span></div>
  <div class="row"><span class="lbl">Threshold / window</span><span class="val" id="wake-thr"></span></div>
  <div class="btns">
    <button onclick="act('restart-app')">Restart app</button>
    <button onclick="act('stop-app')">Stop app</button>
    <button onclick="act('start-app')">Start app</button>
  </div>
</div>

<div class="card"><h2>Wake detection — "Hey Cee-Jap"</h2>
  <div class="row"><span class="lbl">Listening</span><span class="val" id="wk-state"></span></div>
  <div style="position:relative;height:28px;background:#0d1013;border:1px solid var(--line);
              border-radius:8px;margin:10px 0 4px;overflow:hidden;">
    <div id="wk-bar" style="position:absolute;left:0;top:0;bottom:0;width:0%;
         background:var(--accent);transition:width .15s;"></div>
    <div id="wk-thrline" style="position:absolute;top:0;bottom:0;width:2px;background:var(--warn);"></div>
    <span id="wk-score" style="position:absolute;right:8px;top:4px;font-size:13px;color:var(--fg);"></span>
  </div>
  <div class="row" style="border:0;padding-top:0"><span class="lbl" style="font-size:12px">
    live score (1 s peak) — orange line is the trigger threshold</span></div>
  <canvas id="wk-chart" height="80"
    style="width:100%;height:80px;background:#0d1013;border:1px solid var(--line);
           border-radius:8px;margin:6px 0;"></canvas>
  <div class="row"><span class="lbl">Last detection</span><span class="val" id="wk-last">—</span></div>
  <pre id="wk-events" style="max-height:18vh;margin-top:8px">no detections yet</pre>
  <div class="row" style="border:0"><span class="lbl">Transcript (what it heard / answered)</span></div>
  <div id="wk-transcript" style="max-height:30vh;overflow-y:auto;font-size:13px;
       background:#0d1013;border:1px solid var(--line);border-radius:8px;padding:10px;">
    no turns yet</div>
  <div class="row" style="margin-top:6px"><span class="lbl">Speaker gate</span>
    <span class="val" id="sp-state">—</span></div>
  <div class="row"><span class="lbl">Last voice match</span>
    <span class="val" id="sp-last">—</span></div>
  <div class="btns">
    <button onclick="act('activate-listening')" style="flex-basis:100%">
      🎙 Activate listening (skip wake word)</button>
    <button onclick="if(confirm('The robot will say a prompt, then record you for ~10 seconds. Speak naturally near the robot.')) act('enroll-voice')">
      Enroll voice</button>
    <button id="sp-btn" onclick="toggleGate()">…</button>
  </div>
  <div class="row" style="border:0"><span class="lbl" style="font-size:12px">
    When the gate is ON, the robot ignores questions from voices that do not
    match the enrolled speaker.</span></div>
</div>

<div class="card"><h2>Connectivity</h2>
  <div class="row"><span class="lbl">Internet (OpenAI API)</span><span class="val" id="net"></span></div>
  <div class="row"><span class="lbl">WiFi</span><span class="val" id="wifi"></span></div>
  <div class="row"><span class="lbl">IP</span><span class="val" id="ip"></span></div>
  <div class="row" style="border:0"><span class="lbl">Networks (tap to switch)</span></div>
  <div id="wifi-list" style="font-size:14px">tap Scan to list networks</div>
  <div class="btns"><button onclick="wifiScan()">Scan networks</button></div>
  <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap">
    <input id="wm-ssid" placeholder="network name" style="flex:1;min-width:110px;padding:8px;
      border-radius:8px;border:1px solid #30363d;background:#0d1117;color:inherit">
    <input id="wm-pw" type="password" placeholder="password" style="flex:1;min-width:110px;
      padding:8px;border-radius:8px;border:1px solid #30363d;background:#0d1117;color:inherit">
    <button onclick="wifiManual()">Join</button>
  </div>
  <div class="row" style="border:0;margin-top:4px"><span class="lbl" style="font-size:12px">
    Manual entry works even in setup-hotspot mode (where scanning is unavailable)
    and for hidden networks.</span></div>
  <div class="row" style="border:0"><span class="lbl" style="font-size:12px">
    ⚠ Switching networks drops this dashboard — rejoin the same WiFi on your
    phone to reconnect. New networks ask for a password.</span></div>
</div>

<div class="card"><h2>Remote voice — phone ➜ robot speaker</h2>
  <div class="row" style="border:0"><span class="lbl">Type and the robot says it (CJ voice, needs internet)</span></div>
  <div style="display:flex;gap:8px;margin:8px 0">
    <input id="say-text" type="text" maxlength="500" placeholder="Type something…"
      style="flex:1;background:#0d1013;color:var(--fg);border:1px solid var(--line);
             border-radius:10px;padding:12px;font-size:15px">
    <button style="flex:0 0 auto" onclick="sayText()">Say it</button>
  </div>
  <div class="row" style="border:0"><span class="lbl">Or hold to talk — your voice out of the robot</span></div>
  <button id="ptt" style="flex-basis:100%;width:100%;min-height:56px;font-size:16px">
    🎤 Hold to talk</button>
  <div class="row" style="border:0"><span class="lbl" id="ptt-hint" style="font-size:12px"></span></div>
</div>

<div class="card"><h2>Audio</h2>
  <div class="row"><span class="lbl">Playback route</span><span class="val" id="route"></span></div>
  <div class="row"><span class="lbl">Sony ULT FIELD 1</span><span class="val" id="spk-sony"></span></div>
  <div class="row"><span class="lbl">Marshall EMBERTON</span><span class="val" id="spk-marshall"></span></div>
  <div class="row"><span class="lbl">Speaker watchdog</span><span class="val" id="svc-watchdog"></span></div>
  <div class="btns">
    <button onclick="act('audio-internal')">Route: internal</button>
    <button onclick="act('audio-sony')">Route: Sony</button>
    <button onclick="act('audio-marshall')">Route: Marshall</button>
    <button onclick="act('test-sound')">Play test sound</button>
    <button onclick="act('tagalog-sample')">Play Tagalog sample</button>
    <button id="wd-btn" onclick="toggleWatchdog()">…</button>
  </div>
  <div class="row" style="border:0;margin-top:6px"><span class="lbl" style="font-size:12px">
    Watchdog forces the route to Sony every 15 s while running — stop it before
    switching manually. Internal speaker is required for echo-cancel.</span></div>
</div>

<div class="card"><h2>Bluetooth</h2>
  <div class="row" style="border:0"><span class="lbl">Devices (tap to connect / disconnect)</span></div>
  <div id="bt-list" style="font-size:14px">loading…</div>
  <div class="btns"><button onclick="btScan(true)">Scan for new devices (~8 s)</button></div>
  <div class="row" style="border:0"><span class="lbl" style="font-size:12px">
    Pairing a new speaker connects it, but the playback route still follows the
    Audio buttons above (Sony / Marshall / internal). While the watchdog runs,
    a disconnected Sony reconnects itself within 15 s.</span></div>
</div>

<div class="card"><h2>System</h2>
  <div class="row"><span class="lbl">CPU temp</span><span class="val" id="temp"></span></div>
  <div class="row"><span class="lbl">Load (1/5/15 min)</span><span class="val" id="load"></span></div>
  <div class="row"><span class="lbl">Memory / disk used</span><span class="val" id="memdisk"></span></div>
  <div class="row"><span class="lbl">Uptime</span><span class="val" id="uptime"></span></div>
  <div class="row"><span class="lbl">Reachy daemon</span><span class="val" id="daemon"></span></div>
  <div class="row"><span class="lbl">Throttled flags</span><span class="val" id="throttled"></span></div>
  <div class="btns">
    <button class="danger" onclick="if(confirm('Reboot the Pi?')) act('reboot')">Reboot Pi</button>
  </div>
</div>

<div class="card"><h2>Logs
  <select id="log-unit" onchange="loadLogs()">
    <option value="supervaise">supervaise</option>
    <option value="speaker-watchdog">speaker-watchdog</option>
    <option value="bluealsa">bluealsa</option>
    <option value="pi-dashboard">pi-dashboard</option>
  </select></h2>
  <pre id="log">loading…</pre>
  <div class="btns"><button onclick="loadLogs()">Refresh logs</button></div>
</div>

<div id="toast"></div>
<script>
const $ = id => document.getElementById(id);
const dot = (ok, txt) =>
  `<span class="dot ${ok ? "ok" : "bad"}"></span>${txt}`;

function fmtUp(s) {
  if (s == null) return "?";
  const d = Math.floor(s/86400), h = Math.floor(s%86400/3600), m = Math.floor(s%3600/60);
  return (d ? d+"d " : "") + h + "h " + m + "m";
}

let watchdogActive = false;

async function refresh() {
  try {
    const r = await fetch("/api/status");
    const s = await r.json();
    $("meta").textContent = s.hostname + " · " + s.time;
    const app = s.services["supervaise"];
    $("svc-app").innerHTML = dot(app.active === "active", app.active + " (" + app.sub + ")");
    $("svc-app-since").textContent = (app.since || "—").replace(/ [A-Z]+$/, "");
    $("wake-model").textContent = s.wake.model.file
      ? s.wake.model.file + " (installed " + s.wake.model.installed + ")" : "—";
    $("wake-thr").textContent = (s.wake.env.CJ_WAKE_OWW_THRESHOLD || "?") +
      " / " + (s.wake.env.CJ_WAKE_WINDOW_S || "?") + " s";
    $("net").innerHTML = dot(s.internet, s.internet ? "reachable" : "NOT CONNECTED");
    $("wifi").textContent = (s.wifi.essid || "?") + "  " + (s.wifi.signal_dbm || "?") +
      " dBm (" + (s.wifi.quality || "?") + ")";
    $("ip").textContent = s.wifi.ip || "?";
    $("route").textContent = s.audio.route || "?";
    $("spk-sony").innerHTML = dot(s.audio.speakers["Sony ULT FIELD 1"],
      s.audio.speakers["Sony ULT FIELD 1"] ? "connected" : "not connected");
    $("spk-marshall").innerHTML = dot(s.audio.speakers["Marshall EMBERTON"],
      s.audio.speakers["Marshall EMBERTON"] ? "connected" : "not connected");
    const wd = s.services["speaker-watchdog"];
    watchdogActive = wd.active === "active";
    $("svc-watchdog").innerHTML = dot(watchdogActive, wd.active);
    $("wd-btn").textContent = watchdogActive ? "Stop watchdog" : "Start watchdog";
    $("temp").innerHTML = s.system.temp_c == null ? "?" :
      `<span class="dot ${s.system.temp_c > 75 ? "bad" : s.system.temp_c > 65 ? "warn" : "ok"}"></span>` +
      s.system.temp_c + " °C";
    $("load").textContent = s.system.load.map(x => x.toFixed(2)).join(" / ");
    $("memdisk").textContent = (s.system.mem_used_pct ?? "?") + "% / " +
      (s.system.disk_used_pct ?? "?") + "%";
    $("uptime").textContent = fmtUp(s.system.uptime_s);
    $("daemon").innerHTML = dot(s.reachy_daemon, s.reachy_daemon ? "running" : "not running");
    $("throttled").textContent = s.system.throttled || "?";
  } catch (e) {
    $("meta").textContent = "unreachable — " + e.message;
  }
}

async function loadLogs() {
  const unit = $("log-unit").value;
  try {
    const r = await fetch("/api/logs?unit=" + unit + "&lines=150");
    const el = $("log");
    el.textContent = await r.text();
    el.scrollTop = el.scrollHeight;
  } catch (e) { $("log").textContent = "log fetch failed: " + e.message; }
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg; t.style.display = "block";
  setTimeout(() => t.style.display = "none", 2500);
}

async function act(name) {
  toast("running " + name + "…");
  try {
    const r = await fetch("/api/action", { method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({action: name}) });
    const out = await r.json();
    toast(name + ": " + (out.ok ? "ok" : "FAILED — " + (out.output || "")));
  } catch (e) { toast(name + " failed: " + e.message); }
  setTimeout(refresh, 1200);
}

function toggleWatchdog() { act(watchdogActive ? "stop-watchdog" : "start-watchdog"); }

// ── Live wake-score meter ─────────────────────────────────────────
const wkSamples = [];   // rolling ~60 s of polled peaks
let lastFiredTs = 0;

function fmtClock(ts) {
  return new Date(ts * 1000).toLocaleTimeString();
}

function drawChart(threshold) {
  const cv = $("wk-chart"), ctx = cv.getContext("2d");
  if (cv.width !== cv.clientWidth) cv.width = cv.clientWidth;
  const W = cv.width, H = cv.height;
  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = "#e0a542"; ctx.lineWidth = 1;
  const ty = H - threshold * H;
  ctx.beginPath(); ctx.moveTo(0, ty); ctx.lineTo(W, ty); ctx.stroke();
  ctx.strokeStyle = "#4a90d9"; ctx.lineWidth = 2;
  ctx.beginPath();
  const n = wkSamples.length, step = W / Math.max(n - 1, 1);
  wkSamples.forEach((v, i) => {
    const x = i * step, y = H - Math.min(v, 1) * H;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
}

async function wakePoll() {
  try {
    const r = await fetch("/api/wake");
    const w = await r.json();
    const thr = w.threshold ?? 0.5;
    $("wk-thrline").style.left = (thr * 100) + "%";
    if (w.live) {
      $("wk-state").innerHTML = dot(true, "live (armed)");
      const pk = w.peak1s ?? 0;
      $("wk-bar").style.width = Math.min(pk * 100, 100) + "%";
      $("wk-bar").style.background = pk >= thr ? "var(--bad)" : "var(--accent)";
      $("wk-score").textContent = pk.toFixed(3);
      wkSamples.push(pk);
    } else {
      $("wk-state").innerHTML = dot(false,
        "not listening (answering a question, or app stopped)");
      $("wk-bar").style.width = "0%";
      $("wk-score").textContent = "—";
      wkSamples.push(0);
    }
    if (wkSamples.length > 200) wkSamples.shift();
    drawChart(thr);
    if (w.fired_ts) {
      $("wk-last").textContent =
        fmtClock(w.fired_ts) + "  (score " + (w.fired_score ?? 0).toFixed(3) + ")";
      if (w.fired_ts > lastFiredTs && lastFiredTs) toast("wake fired!");
      lastFiredTs = w.fired_ts;
    }
    if (w.events && w.events.length) {
      $("wk-events").textContent = w.events.map(e =>
        fmtClock(e.ts) + "   score " + e.score.toFixed(3)).join("\\n");
    }
    if (w.transcript && w.transcript.length) {
      const el = $("wk-transcript");
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
      el.innerHTML = w.transcript.map(t => {
        const who = t.role === "user" ? "🎤 heard" : t.role === "cj" ? "🤖 CJ" : "ℹ️";
        const col = t.role === "user" ? "#7fc4ff" : t.role === "cj" ? "#9ee6a8" : "var(--dim)";
        const txt = t.text.replace(/&/g, "&amp;").replace(/</g, "&lt;");
        return `<div style="margin-bottom:6px"><span style="color:var(--dim);font-size:11px">` +
          fmtClock(t.ts) + `</span> <b style="color:${col}">` + who + `</b>  ` + txt + `</div>`;
      }).join("");
      if (atBottom) el.scrollTop = el.scrollHeight;
    }
    renderSpeaker(w.speaker);
  } catch (e) { /* dashboard unreachable; status poll reports it */ }
}

// ── Speaker gate ──────────────────────────────────────────────────
let gateEnabled = false;
function renderSpeaker(sp) {
  if (!sp) return;
  gateEnabled = sp.enabled && sp.enrolled;
  $("sp-state").innerHTML = !sp.enrolled ? dot(false, "no voice enrolled yet")
    : dot(gateEnabled, gateEnabled ? "ON — only enrolled voice" : "off — answers anyone");
  $("sp-btn").textContent = gateEnabled ? "Gate: turn OFF" : "Gate: turn ON";
  if (sp.last) {
    $("sp-last").innerHTML = dot(sp.last.ok,
      sp.last.sim.toFixed(2) + (sp.last.ok ? " ≥ " : " < ") +
      sp.last.threshold.toFixed(2) + "  " + fmtClock(sp.last.ts));
  }
}
function toggleGate() { act(gateEnabled ? "gate-off" : "gate-on"); }

// ── WiFi switching ────────────────────────────────────────────────
async function wifiScan() {
  $("wifi-list").textContent = "scanning…";
  try {
    const r = await fetch("/api/wifi?rescan=1");
    const w = await r.json();
    if (w.hotspot && !w.networks.length) {
      $("wifi-list").textContent =
        "setup hotspot active — scanning unavailable; type the network below";
      return;
    }
    if (!w.networks.length) { $("wifi-list").textContent = "no networks found"; return; }
    $("wifi-list").innerHTML = w.networks.map(n => {
      const bars = n.signal > 66 ? "▂▄▆" : n.signal > 33 ? "▂▄" : "▂";
      const tag = n.in_use ? " — connected" : (n.saved ? " (saved)" : "");
      const lock = n.security === "open" ? "" : " 🔒";
      return `<div class="row" style="cursor:pointer" onclick="wifiJoin('` +
        n.ssid.replace(/'/g, "\\\\'") + `',` + (n.saved || n.security === "open") + `)">` +
        `<span>${n.in_use ? "✅ " : ""}${n.ssid}${lock}<span style="color:var(--dim)">${tag}</span></span>` +
        `<span class="val" style="color:var(--dim)">${bars} ${n.signal}%</span></div>`;
    }).join("");
  } catch (e) { $("wifi-list").textContent = "scan failed: " + e.message; }
}

async function wifiSend(ssid, password) {
  if (!confirm("Switch the robot to \\"" + ssid + "\\"?\\n\\nThe dashboard will drop " +
      "until your phone is on the same network.")) return;
  toast("switching to " + ssid + "…");
  try {
    const r = await fetch("/api/wifi/connect", { method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ssid, password}) });
    const out = await r.json();
    toast(out.ok ? out.output || ("now on " + ssid) : "FAILED — " + out.output);
  } catch (e) {
    toast("dashboard dropped — rejoin " + ssid + " on your phone and reload");
  }
}
async function wifiJoin(ssid, known) {
  let password = null;
  if (!known) {
    password = prompt('Password for "' + ssid + '" (leave empty if open):');
    if (password === null) return;
  }
  wifiSend(ssid, password);
}
function wifiManual() {
  const ssid = $("wm-ssid").value.trim(), pw = $("wm-pw").value;
  if (!ssid) { toast("enter a network name"); return; }
  wifiSend(ssid, pw || null);
}

// ── Bluetooth connect / disconnect / pair ─────────────────────────
async function btScan(rescan) {
  $("bt-list").textContent = rescan ? "scanning (~8 s)…" : "loading…";
  try {
    const r = await fetch("/api/bt" + (rescan ? "?scan=1" : ""));
    const b = await r.json();
    if (!b.devices.length) {
      $("bt-list").textContent = "no devices known — tap Scan"; return;
    }
    $("bt-list").innerHTML = b.devices.map(d => {
      const state = d.connected ? "connected"
        : d.paired ? "paired" : "not paired";
      const col = d.connected ? "var(--ok)" : "var(--dim)";
      const icon = d.audio ? "🔊 " : "";
      return `<div class="row" style="cursor:pointer" onclick="btTap('${d.mac}','` +
        d.name.replace(/'/g, "\\\\'").replace(/</g, "&lt;") + `',` +
        d.connected + `,` + d.paired + `)">` +
        `<span>${d.connected ? "✅ " : ""}${icon}` +
        d.name.replace(/&/g, "&amp;").replace(/</g, "&lt;") + `</span>` +
        `<span class="val" style="color:${col}">${state}</span></div>`;
    }).join("");
  } catch (e) { $("bt-list").textContent = "bluetooth list failed: " + e.message; }
}

async function btTap(mac, name, connected, paired) {
  const action = connected ? "disconnect" : paired ? "connect" : "pair";
  const warn = action === "disconnect" && watchdogActive ?
    "\\n\\n⚠ The watchdog is running — Sony reconnects within 15 s." : "";
  if (!confirm(action.charAt(0).toUpperCase() + action.slice(1) + " \\"" +
      name + "\\"?" + warn)) return;
  toast(action + "ing " + name + "…");
  try {
    const r = await fetch("/api/bt/action", { method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({mac, action}) });
    const out = await r.json();
    toast(name + ": " + (out.ok ? action + " ok ✓" : "FAILED — " + (out.output || "")));
  } catch (e) { toast(action + " failed: " + e.message); }
  setTimeout(() => { btScan(false); refresh(); }, 1500);
}

// ── Typed text → robot voice ──────────────────────────────────────
async function sayText() {
  const text = $("say-text").value.trim();
  if (!text) return;
  toast("synthesizing…");
  try {
    const r = await fetch("/api/say-text", { method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text}) });
    const out = await r.json();
    toast(out.ok ? "spoken ✓" : "FAILED — " + out.output);
    if (out.ok) $("say-text").value = "";
  } catch (e) { toast("failed: " + e.message); }
}
$("say-text").addEventListener("keydown", e => { if (e.key === "Enter") sayText(); });

// ── Hold-to-talk: phone mic → robot speaker ───────────────────────
let rec = null, chunks = [];
const ptt = $("ptt");
const micOK = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
if (!micOK) {
  ptt.disabled = true;
  $("ptt-hint").innerHTML = "Phone-mic needs the secure address: open " +
    `<a style="color:var(--accent)" href="https://${location.hostname}:8443">` +
    `https://${location.hostname}:8443</a> and accept the certificate warning once.`;
} else {
  $("ptt-hint").textContent = "Hold the button, speak, release — the robot plays it.";
  async function pttStart(e) {
    e.preventDefault();
    if (rec) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio: true});
      chunks = [];
      rec = new MediaRecorder(stream);
      rec.ondataavailable = ev => chunks.push(ev.data);
      rec.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        const blob = new Blob(chunks, {type: rec.mimeType});
        rec = null;
        if (blob.size < 2000) { toast("too short"); return; }
        toast("sending " + Math.round(blob.size / 1024) + " KB…");
        try {
          const r = await fetch("/api/say-audio", {method: "POST", body: blob});
          const out = await r.json();
          toast(out.ok ? "playing on robot ✓" : "FAILED — " + out.output);
        } catch (err) { toast("send failed: " + err.message); }
      };
      rec.start();
      ptt.textContent = "🔴 Recording — release to send";
    } catch (err) { toast("mic blocked: " + err.message); rec = null; }
  }
  function pttStop(e) {
    e.preventDefault();
    if (rec && rec.state === "recording") {
      rec.stop();
      ptt.textContent = "🎤 Hold to talk";
    }
  }
  ptt.addEventListener("touchstart", pttStart); ptt.addEventListener("mousedown", pttStart);
  ptt.addEventListener("touchend", pttStop);    ptt.addEventListener("mouseup", pttStop);
  ptt.addEventListener("mouseleave", pttStop);  ptt.addEventListener("touchcancel", pttStop);
}

refresh(); loadLogs(); wakePoll(); btScan(false);
setInterval(() => { if (!document.hidden) refresh(); }, 5000);
setInterval(() => { if (!document.hidden) wakePoll(); }, 300);
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # journald picks up real errors; skip access noise
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        if supervaise_ui and supervaise_ui.handle_get(self, path, params):
            return
        if path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif path == "/api/status":
            self._send(200, json.dumps(status()))
        elif path == "/api/wake":
            self._send(200, json.dumps(wake_live()))
        elif path == "/api/wifi":
            saved, current = wifi_status()
            nets = wifi_scan(rescan=params.get("rescan") == "1")
            for n in nets:
                n["saved"] = n["ssid"] in saved
            self._send(200, json.dumps(
                {"current": current, "saved": saved, "networks": nets,
                 "hotspot": current == SETUP_CON}))
        elif path == "/api/bt":
            devs = bt_scan() if params.get("scan") == "1" else bt_devices()
            self._send(200, json.dumps({"devices": devs}))
        elif path == "/api/logs":
            lines = min(int(params.get("lines", "150") or 150), 1000)
            self._send(200, journal(params.get("unit", "supervaise"), lines),
                       "text/plain; charset=utf-8")
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if supervaise_ui and self.path.partition("?")[0] in (
                "/api/ctl", "/api/entities", "/api/avatar-session",
                "/api/avatar-stop", "/api/avatar-lag", "/api/ask"):
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                body = {}
            if supervaise_ui.handle_post(self, self.path.partition("?")[0], body):
                return
        if self.path == "/api/wifi/connect":
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                ok, out = wifi_connect(body.get("ssid", ""),
                                       body.get("password") or None)
            except Exception as e:
                ok, out = False, str(e)
            self._send(200, json.dumps({"ok": ok, "output": out}))
            return
        if self.path == "/api/bt/action":
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                ok, out = bt_action(body.get("mac", ""), body.get("action", ""))
            except Exception as e:
                ok, out = False, str(e)
            self._send(200, json.dumps({"ok": ok, "output": out}))
            return
        if self.path == "/api/say-text":
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                ok, out = say_text(body.get("text", ""))
            except Exception as e:
                ok, out = False, str(e)
            self._send(200, json.dumps({"ok": ok, "output": out}))
            return
        if self.path == "/api/say-audio":
            try:
                n = int(self.headers.get("Content-Length", 0))
                if n > 15_000_000:
                    raise ValueError("audio too large")
                ok, out = play_phone_audio(self.rfile.read(n))
            except Exception as e:
                ok, out = False, str(e)
            self._send(200, json.dumps({"ok": ok, "output": out}))
            return
        if self.path != "/api/action":
            self._send(404, json.dumps({"error": "not found"}))
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            name = body.get("action", "")
        except Exception:
            name = ""
        if name not in ACTIONS:
            self._send(400, json.dumps({"ok": False, "output": f"unknown action {name!r}"}))
            return
        # tagalog-sample is a ~45 s clip — the generic 30 s cap would cut it off
        code, out = run(ACTIONS[name], timeout=90 if name == "tagalog-sample" else 30)
        self._send(200, json.dumps({"ok": code == 0, "output": out[-500:]}))


def serve_https():
    cert = os.path.join(CERT_DIR, "cert.pem")
    key = os.path.join(CERT_DIR, "key.pem")
    if not (os.path.exists(cert) and os.path.exists(key)):
        print("[dashboard] no TLS cert — HTTPS (phone mic) disabled")
        return
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    srv = ThreadingHTTPServer(("0.0.0.0", HTTPS_PORT), Handler)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print(f"[dashboard] HTTPS (phone mic) on 0.0.0.0:{HTTPS_PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    threading.Thread(target=serve_https, daemon=True).start()
    print(f"[dashboard] serving on 0.0.0.0:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
