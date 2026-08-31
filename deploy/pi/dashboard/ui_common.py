#!/usr/bin/env python3
"""Shared state, paths and controls for the CJAP dashboard pages — served by ui_server.py.

Two views, one backend, one state feed:

    GET  /audience          public page for the external monitor:
                            camera feed TOP, transcribed question BOTTOM-LEFT,
                            the spoken answer BOTTOM-RIGHT (per EPK/Kenn spec).
                            No internals, no errors — degrades to a neutral idle.
    GET  /maintain?key=K    operator page (key-gated, CJ_DASH_KEY, default "cjap"):
                            everything + raw-vs-corrected ASR, NER log, theme/
                            token budget, stage latency, wake events, health,
                            controls, entity-dictionary editor.
    GET  /api/state         the single source of truth both views poll.
    GET  /api/camera.mjpg   MJPEG stream (rpicam-vid, lazy-started, auto-stops
                            ~90s after the last viewer leaves).
    POST /api/ctl           {"action": <control() action>, "key": K}  — see control() / _manual_action()
    GET/POST /api/entities  entity_overrides.json read / validated atomic write
                            (takes effect immediately via P0 hot-reload).

Stdlib only, same discipline as ui_server.py.
"""
import json
import os
import re
import socket
import subprocess
import threading
import time

HOME = os.path.expanduser("~")
MAIN = os.path.join(HOME, "Supervaise-Reachy-Mini-Project-main")
TRANSCRIPT = "/dev/shm/cj_transcript.jsonl"
TURN_META = "/dev/shm/cj_turn_meta.jsonl"
WAKE_LIVE = "/dev/shm/cj_wake_live.json"
WAKE_EVENTS = "/dev/shm/cj_wake_events.jsonl"
STOP_LIVE = "/dev/shm/cj_stop_live.json"        # barge-in meter (2026-08-26)
STOP_EVENTS = "/dev/shm/cj_stop_events.jsonl"
POSTPROC_LOG = "/dev/shm/cj_postproc_corrections.jsonl"
LAST_ANSWER = "/dev/shm/cj_last_answer.wav"        # 2026-08-29: wav (was mp3 → needed an ffmpeg decode)
SPEAKING = "/dev/shm/cj_speaking.json"   # live per-sentence caption feed
MUTE_TRIGGER = "/dev/shm/cj_mute_trigger"
GESTURE_TRIGGER = "/dev/shm/cj_gesture_trigger"   # Mechanical actions card (2026-08-29)
MECH_ACTIONS = ("center", "nod", "shake", "look-left", "look-right", "look-up",
                "look-down", "tilt-left", "tilt-right", "bow", "antennas-up",
                "antennas-down", "antennas-wiggle", "perk", "scan",
                "idle-off", "idle-on", "motors-off", "motors-on")
MUTED_FLAG = "/dev/shm/cj_muted"      # persistent MIC mute (2026-08-29: wake/stop word ignored; robot still speaks)
WAKE_TRIGGER = "/dev/shm/cj_wake_trigger"
ENTITY_OVERLAY = os.path.join(MAIN, "data", "entities", "entity_overrides.json")
CANNED_PATH = os.path.join(MAIN, "data", "entities", "canned_answers.json")
ASK_TRIGGER = "/dev/shm/cj_ask_trigger"   # /event buttons -> main_voice_robot
# Event mode: while this flag exists, spoken questions can match the
# scripted event_* canned entries (answer_canned.event_mode()). Persistent
# (survives reboot); toggled from the /event page. Buttons work regardless.
EVENT_FLAG = os.path.join(MAIN, "data", "entities", "event_mode.on")

ASSETS = os.path.join(HOME, "pi_dashboard", "assets")
LIVEAVATAR_CONF = os.path.join(ASSETS, "liveavatar.json")  # api_key etc.
os.makedirs(ASSETS, exist_ok=True)

DASH_KEY = os.environ.get("CJ_DASH_KEY", "cjap")


def _authed(params, body=None):
    key = params.get("key") or (body or {}).get("key")
    return key == DASH_KEY


# ---------------------------------------------------------------------------
# camera — one rpicam-vid MJPEG process, latest frame shared by all viewers
# ---------------------------------------------------------------------------

_cam = {"proc": None, "frame": b"", "ts": 0.0, "last_read": 0.0, "lock": threading.Lock()}
# Camera OFF switch (2026-08-30, user: "a button for turning off the camera").
# Persistent flag file (survives dashboard restarts AND reboots): while it
# exists cam_frame() never launches rpicam-vid and any running instance is
# killed, so /dev/video* is not held by anything the dashboard controls.
# /maintain Camera card: On / Off buttons (ctl camera-on / camera-off).
CAMERA_OFF_FLAG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "camera.off")


def camera_off() -> bool:
    return os.path.exists(CAMERA_OFF_FLAG)


def _cam_kill():
    """Stop the rpicam-vid process (if any) and drop the stale frame."""
    with _cam["lock"]:
        p, _cam["proc"] = _cam["proc"], None
    if p is not None:
        try:
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    _cam["frame"], _cam["ts"] = b"", 0.0


def camera_set(on: bool):
    if on:
        try:
            os.unlink(CAMERA_OFF_FLAG)
        except OSError:
            pass
        _cam_ensure()
        return True, "camera ON — rpicam-vid running (stays on until Camera off)"
    with open(CAMERA_OFF_FLAG, "w") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
    _cam_kill()
    return True, "camera OFF — rpicam-vid stopped; stays off across restarts/reboots until Camera on"
_CAM_CMD = ["rpicam-vid", "-n", "-t", "0", "--codec", "mjpeg", "--width", "800",
            "--height", "450", "--framerate", "10", "--inline", "-o", "-"]


def _cam_reader(proc):
    buf = b""
    try:
        while proc.poll() is None:
            chunk = proc.stdout.read(16384)
            if not chunk:
                break
            buf += chunk
            while True:
                s = buf.find(b"\xff\xd8")
                e = buf.find(b"\xff\xd9", s + 2) if s >= 0 else -1
                if s < 0 or e < 0:
                    if len(buf) > 4_000_000:
                        buf = b""
                    break
                _cam["frame"], _cam["ts"] = buf[s:e + 2], time.time()
                buf = buf[e + 2:]
            # 2026-08-30 (user: "do not off camera when it is not manually
            # off"): no idle auto-stop any more — the camera runs from
            # dashboard start until the operator presses Camera off.
            if camera_off():
                break
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            pass
        with _cam["lock"]:
            if _cam["proc"] is proc:
                _cam["proc"] = None


def _cam_ensure() -> bool:
    """Start rpicam-vid if it is not running (and the camera is not switched
    off). Returns False when it could not be started."""
    if camera_off():
        return False
    with _cam["lock"]:
        if _cam["proc"] is None or _cam["proc"].poll() is not None:
            try:
                p = subprocess.Popen(_CAM_CMD, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)
                _cam["proc"] = p
                threading.Thread(target=_cam_reader, args=(p,), daemon=True).start()
            except Exception:
                return False
    return True


def _cam_keepalive():
    """Camera always on unless manually off (2026-08-30): start at dashboard
    boot and restart rpicam-vid whenever it dies (unplug/replug, crash),
    checking every 5 s. Camera off stops it; Camera on lets this restart it."""
    while True:
        try:
            _cam_ensure()
        except Exception:
            pass
        time.sleep(5)


threading.Thread(target=_cam_keepalive, daemon=True).start()


def cam_frame(timeout=4.0):
    """Latest JPEG frame (camera is kept running by _cam_keepalive). b'' if unavailable."""
    if camera_off():
        return b""
    _cam["last_read"] = time.time()
    if not _cam_ensure():
        return b""
    t0 = time.time()
    while time.time() - _cam["ts"] > 2.0 and time.time() - t0 < timeout:
        time.sleep(0.1)
    return _cam["frame"] if time.time() - _cam["ts"] <= 2.0 else b""


# ---------------------------------------------------------------------------
# state aggregation
# ---------------------------------------------------------------------------

def _tail_jsonl(path, n):
    try:
        out = []
        for line in open(path).read().splitlines()[-n:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out
    except OSError:
        return []


def _read_json(path):
    try:
        return json.loads(open(path).read())
    except (OSError, ValueError):
        return None


_health_cache = {"ts": 0.0, "data": {}}


def _audio_route():
    """'internal speaker (XMOS)' / 'Sony' / … from the audio-out route file header."""
    try:
        for line in open(os.path.expanduser("~/.asoundrc.route")):
            if line.startswith("# Route:"):
                return line[len("# Route:"):].split(" via ")[0].strip(" .\n")
    except OSError:
        pass
    return "unknown"


def _health():
    if time.time() - _health_cache["ts"] < 10:
        return _health_cache["data"]
    h = {}
    try:
        h["supervaise"] = subprocess.run(
            ["systemctl", "is-active", "supervaise.service"],
            capture_output=True, text=True, timeout=3).stdout.strip() == "active"
    except Exception:
        h["supervaise"] = False
    try:
        h["mic"] = "seeed" in open("/proc/asound/cards").read().lower() or \
                   "array" in open("/proc/asound/cards").read().lower() or \
                   len(open("/proc/asound/cards").read().strip()) > 10
    except OSError:
        h["mic"] = False
    try:
        s = socket.create_connection(("api.openai.com", 443), timeout=1.5)
        s.close()
        h["internet"] = True
    except OSError:
        h["internet"] = False
    h["camera"] = (not camera_off()) and bool(_cam["frame"]) and time.time() - _cam["ts"] < 3
    _health_cache.update(ts=time.time(), data=h)
    return h


def state():
    """The single state document both views poll."""
    turns = _tail_jsonl(TRANSCRIPT, 30)
    metas = _tail_jsonl(TURN_META, 12)
    composed = [m for m in metas if m.get("phase") == "composed"]
    spoken = [m for m in metas if m.get("phase") == "spoken"]
    return {
        "ts": time.time(),
        "ui_rev": UI_REV,
        "turns": turns,
        "meta": composed[-1] if composed else None,
        "spoken": spoken[-1] if spoken else None,
        "metas": metas,   # full recent-turn history for the tracking table
        "wake": _read_json(WAKE_LIVE),
        "speaking": _read_json(SPEAKING),
        "aside": _read_json("/dev/shm/cj_aside.json"),
        "stage": _read_json("/dev/shm/cj_stage.json"),
        "voice_lock": _read_json("/dev/shm/cj_voice_lock.json"),
        # /face-avatar page heartbeat + the pending command from /maintain
        "avatar_page": _read_json(AVATAR_PAGE_STATUS),
        "avatar_cmd": _read_json(AVATAR_PAGE_CMD),
        "wake_events": _tail_jsonl(WAKE_EVENTS, 12),
        "stop": _read_json(STOP_LIVE),
        "stop_events": _tail_jsonl(STOP_EVENTS, 12),
        "corrections": _tail_jsonl(POSTPROC_LOG, 20),
        "health": _health(),
        "audio_route": _audio_route(),
        "tempo_avg": (_read_json("/dev/shm/cj_tempo_avg.json") or {}).get("avg"),
        "has_last_answer": os.path.exists(LAST_ANSWER),
        "event_mode": os.path.exists(EVENT_FLAG),
        "camera_off": camera_off(),
        "muted": os.path.exists(MUTED_FLAG),
        # 2026-08-25 Reboot-button fix: the page compares these to know the box
        # really went down and came back before it reloads itself
        "boot_id": _read_text("/proc/sys/kernel/random/boot_id"),
        "uptime_s": _uptime_s(),
    }


def _read_text(path):
    try:
        return open(path).read().strip()
    except Exception:
        return None


def _uptime_s():
    try:
        return int(float(open("/proc/uptime").read().split()[0]))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# controls + entity editor
# ---------------------------------------------------------------------------

UI_REV = str(int(max(os.path.getmtime(f) for f in __import__("glob").glob(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_*.py")))))   # any page file change → open pages reload
USAGE_PATH = os.path.expanduser("~/cj_usage.json")   # written by app/usage_meter.py
_eleven_cache = {"ts": 0.0, "data": None}
ERROR_RE = re.compile(
    r"Traceback|Error|error|FAILED|failed|refused|offline|exception|timed out|"
    r"Timeout|denied|\[ctl\]|\[action\]|\[ask\] (bad|question)|muted from|— answer cut|"
    r"fidelity\] AUDIT flagged|no speech heard|empty transcript|PLAYBACK|discarded", re.I)
ERROR_SKIP_RE = re.compile(r"fails? open|failed open|Pending kernel|Consumed .* CPU|onnxruntime|"
                           r"GetGpuDevices|stop word armed|avatar-voice-|"
                           r"D: bluealsa-pcm\.c", re.I)   # BlueALSA plugin debug chatter ("Getting BlueALSA PCM: PLAYBACK ...")


def _env_value(name):
    """Read one key from the app's .env (server-side only, never sent out)."""
    try:
        with open(os.path.join(MAIN, "app", ".env"), encoding="utf-8") as f:
            for line in f:
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def _eleven_quota():
    """ElevenLabs subscription quota, cached 5 min (one call per refresh)."""
    if time.time() - _eleven_cache["ts"] < 300 and _eleven_cache["data"] is not None:
        return _eleven_cache["data"]
    key = _env_value("ELEVEN_API_KEY")
    data = {"error": "no ELEVEN_API_KEY in app/.env"} if not key else None
    if key:
        try:
            import urllib.request
            req = urllib.request.Request("https://api.elevenlabs.io/v1/user/subscription",
                                         headers={"xi-api-key": key})
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.load(r)
            data = {k: d.get(k) for k in ("tier", "character_count", "character_limit",
                                          "next_character_count_reset_unix", "status")}
        except Exception as e:
            data = {"error": f"{type(e).__name__}: {e}"[:120]}
    _eleven_cache.update(ts=time.time(), data=data)
    return data


_prov_cache = {"ts": 0.0, "data": None}
_status_cache = {}


def _http_probe(url, headers, timeout=3):
    """(http_status_or_None, seconds, error_text)."""
    import urllib.request, urllib.error
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read(2048)
            return r.status, round(time.time() - t0, 2), None
    except urllib.error.HTTPError as e:
        return e.code, round(time.time() - t0, 2), f"HTTP {e.code} {e.reason}"
    except Exception as e:
        return None, round(time.time() - t0, 2), f"{type(e).__name__}: {e}"[:100]


def _statuspage(name, urls):
    """Vendor public status page (Statuspage-style JSON), cached 5 min."""
    c = _status_cache.get(name)
    if c and time.time() - c["ts"] < 300:
        return c["data"]
    import urllib.request
    data = {"description": "unavailable", "indicator": "unknown"}
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 cjap-kiosk"})
            with urllib.request.urlopen(req, timeout=3) as r:
                d = json.load(r)
            st = d.get("status") or {}
            if st:
                data = {"description": st.get("description"), "indicator": st.get("indicator"),
                        "url": url.split("/api/")[0]}
                break
        except Exception:
            continue
    _status_cache[name] = {"ts": time.time(), "data": data}
    return data


_prov_lock = threading.Lock()


def provider_status():
    """Live reachability of each API we depend on (one cheap authenticated
    call each, cached 60 s) + the vendor status pages (cached 5 min).
    Serialized: with several /maintain tabs open, one probes and the rest
    get the cache instead of each stalling the handler (2026-08-25 review)."""
    with _prov_lock:
        return _provider_status_locked()


def _provider_status_locked():
    if _prov_cache["data"] is not None and time.time() - _prov_cache["ts"] < 60:
        return _prov_cache["data"]
    ak, ek, ok = (_env_value("ANTHROPIC_API_KEY"), _env_value("ELEVEN_API_KEY"),
                  _env_value("OPENAI_API_KEY"))
    checks = {
        "claude": ("https://api.anthropic.com/v1/models",
                   {"x-api-key": ak or "", "anthropic-version": "2023-06-01"}, bool(ak)),
        "elevenlabs": ("https://api.elevenlabs.io/v1/user/subscription",
                       {"xi-api-key": ek or ""}, bool(ek)),
        "openai": ("https://api.openai.com/v1/models",
                   {"Authorization": "Bearer " + (ok or "")}, bool(ok)),
    }
    out = {}
    for name, (url, hdrs, has_key) in checks.items():
        if not has_key:
            out[name] = {"ok": False, "code": None, "s": None, "error": "no API key in app/.env"}
            continue
        code, secs, err = _http_probe(url, hdrs)
        out[name] = {"ok": code == 200, "code": code, "s": secs, "error": err}
    out["claude"]["page"] = _statuspage("claude", [
        "https://status.anthropic.com/api/v2/status.json",
        "https://status.claude.com/api/v2/status.json"])
    out["elevenlabs"]["page"] = _statuspage("elevenlabs", [
        "https://status.elevenlabs.io/api/v2/status.json"])
    out["openai"]["page"] = _statuspage("openai", [
        "https://status.openai.com/api/v2/status.json"])
    out["ts"] = time.time()
    _prov_cache.update(ts=time.time(), data=out)
    return out


def usage():
    return {"ts": time.time(), "usage": _read_json(USAGE_PATH) or {},
            "eleven": _eleven_quota()}


_err_cache = {"ts": 0.0, "rows": None}


def recent_errors(limit=25):
    """Error-ish lines + operator actions from the robot and dashboard
    journals (this boot), newest last — the fast path to a diagnosis.
    journalctl is cached 10 s (each open /maintain tab polls every 10 s)."""
    if _err_cache["rows"] is not None and time.time() - _err_cache["ts"] < 10:
        return _err_cache["rows"][-limit:]
    rows = _recent_errors_uncached()
    _err_cache.update(ts=time.time(), rows=rows)
    return rows[-limit:]


def _recent_errors_uncached(limit=25):
    try:
        out = subprocess.run(
            ["journalctl", "-u", "supervaise.service", "-u", "pi-dashboard.service",
             "-b", "-n", "1500", "-o", "short-iso", "--no-pager"],
            capture_output=True, text=True, timeout=10).stdout
    except Exception as e:
        return [{"t": "", "unit": "", "msg": f"journalctl failed: {e}"}]
    rows = []
    for line in out.splitlines():
        if not ERROR_RE.search(line) or ERROR_SKIP_RE.search(line):
            continue
        # 2026-08-25T12:05:20+0100 host python[1234]: message
        m = re.match(r"(\S+) \S+ (\S+?)\[\d+\]: (.*)", line)
        if not m:
            continue
        t, proc, msg = m.groups()
        if msg.strip().startswith(("File ", "~", "^", "self.", "return ", "raise ")):
            continue   # traceback body lines; the header + final line are enough
        rows.append({"t": t[11:19], "unit": "dash" if proc == "python3" else "robot",
                     "msg": msg.strip()[:220]})
    return rows[-limit:]

AVATAR_PAGE_STATUS = "/dev/shm/cj_avatar_page.json"   # page → /maintain
AVATAR_PAGE_CMD = "/dev/shm/cj_avatar_cmd.json"       # /maintain → page
AVATAR_VOICE_MODES = ("robot", "avatar", "sync")


def _avatar_page_cmd(cmd, mode=None):
    """Queue a command for the /face-avatar page (it polls /api/state and
    applies any command newer than the last one it saw)."""
    doc = {"ts": time.time(), "cmd": cmd}
    if mode:
        doc["mode"] = mode
    tmp = f"{AVATAR_PAGE_CMD}.{threading.get_ident()}.tmp"   # per-thread: two ctl posts may overlap
    with open(tmp, "w") as f:
        json.dump(doc, f)
    os.replace(tmp, AVATAR_PAGE_CMD)


def avatar_status_put(body):
    """The /face-avatar page reports its state here every few seconds."""
    doc = {"ts": time.time()}
    for k in ("status", "mode", "ready", "stopped", "frozen", "lag", "parked"):
        if k in body:
            v = body[k]
            doc[k] = v if isinstance(v, (bool, int, float)) else str(v)[:200]
    tmp = f"{AVATAR_PAGE_STATUS}.{threading.get_ident()}.tmp"   # per-thread: posts overlap
    with open(tmp, "w") as f:
        json.dump(doc, f)
    os.replace(tmp, AVATAR_PAGE_STATUS)
    return True, "ok"


# ---- Manual actions card (2026-08-26): operator tuning without SSH ---------
TUNING_CONF = "/etc/systemd/system/supervaise.service.d/wakeword.conf"
TUNING_KNOBS = {   # field -> (env var, min, max, label)
    "wake":   ("CJ_WAKE_OWW_THRESHOLD",     0.01,  1.0,  "wake threshold"),
    "stop":   ("CJ_STOP_OWW_THRESHOLD",     0.001, 1.0,  "stop threshold"),
    "listen": ("CJ_MIC_TRAILING_SILENCE_S", 0.3,   10.0, "listen time (s)"),
    "pace":   ("CJ_TEMPO_RATE_MAX",         8.0,   25.0, "pace ceiling (chars/s)"),
    "length": ("CJ_MAX_WORDS",              30,    150,  "answer length (max words)"),
}
BT_MACS = {"sony": "50:1B:6A:8B:16:F2", "marshall": "04:21:44:84:1F:C1"}


def tuning_get():
    """Current values of the operator knobs, read from the wakeword.conf drop-in."""
    out = {}
    try:
        text = open(TUNING_CONF).read()
    except OSError as e:
        return {"error": str(e)}
    for field, (var, _lo, _hi, _lbl) in TUNING_KNOBS.items():
        m = re.search(rf"^Environment={var}=([0-9.]+)\s*$", text, re.M)
        out[field] = float(m.group(1)) if m else None
    return out


def tuning_set(body):
    """Rewrite changed Environment= lines in wakeword.conf (via sudo, with a
    timestamped backup), then daemon-reload + restart the voice app in the
    background. Returns (ok, message)."""
    try:
        text = open(TUNING_CONF).read()
    except OSError as e:
        return False, f"cannot read {TUNING_CONF}: {e}"
    changes = []
    for field, (var, lo, hi, lbl) in TUNING_KNOBS.items():
        if body.get(field) in (None, ""):
            continue
        try:
            val = float(body[field])
        except (TypeError, ValueError):
            return False, f"{lbl}: not a number"
        if not lo <= val <= hi:
            return False, f"{lbl}: must be between {lo} and {hi}"
        pat = re.compile(rf"^Environment={var}=([0-9.]+)\s*$", re.M)
        m = pat.search(text)
        if not m:
            return False, f"{var} not found in wakeword.conf"
        if abs(float(m.group(1)) - val) < 1e-9:
            continue
        text = pat.sub(f"Environment={var}={val:g}", text, count=1)
        changes.append(f"{lbl} {m.group(1)} -> {val:g}")
    if not changes:
        return True, "no change"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tmp = f"/dev/shm/wakeword.conf.{stamp}"
    with open(tmp, "w") as f:
        f.write(text)
    for cmd in (["sudo", "-n", "cp", TUNING_CONF, f"{TUNING_CONF}.bak-dash-{stamp}"],
                ["sudo", "-n", "install", "-m", "644", tmp, TUNING_CONF],
                ["sudo", "-n", "systemctl", "daemon-reload"]):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            return False, f"{' '.join(cmd[2:4])} failed: {r.stderr.strip()[:120]}"
    try:
        os.unlink(tmp)
    except OSError:
        pass
    threading.Thread(target=lambda: subprocess.run(
        ["sudo", "-n", "systemctl", "restart", "supervaise.service"], timeout=60),
        daemon=True).start()
    return True, "applied: " + "; ".join(changes) + " — voice app restarting (~25 s)"


def _manual_action(action):
    """Extra operator buttons; returns (ok, msg) or None when not ours."""
    if action == "tempo-reset":   # 2026-08-29: forget the session speaking-rate average
        try:
            os.unlink("/dev/shm/cj_tempo_avg.json")
            return True, "voice tempo reference reset — the next answer sets a fresh pace"
        except FileNotFoundError:
            return True, "voice tempo reference was already clear"
        except OSError as e:
            return False, f"tempo reset failed: {e}"
    if action.startswith("gesture-"):
        name = action[len("gesture-"):]
        if name not in MECH_ACTIONS:
            return False, "unknown gesture " + name
        with open(GESTURE_TRIGGER, "w") as f:
            json.dump({"g": name, "ts": time.time()}, f)
        return True, f"{name} sent — the app runs it when idle (not mid-answer); result in Logs as [gesture]"
    if action == "bt-pulse":
        r = subprocess.run([os.path.expanduser("~/bt-keepalive.sh"), "test"],
                           capture_output=True, text=True, timeout=30)
        return r.returncode == 0, (r.stdout + r.stderr).strip()[-200:] or "done"
    for name, mac in BT_MACS.items():
        if action == f"bt-connect-{name}":
            r = subprocess.run(["bluetoothctl", "connect", mac],
                               capture_output=True, text=True, timeout=20)
            ok = "Connection successful" in r.stdout
            last = ((r.stdout + r.stderr).strip().splitlines() or ["no reply"])[-1]
            return ok, (f"{name} connected" if ok else f"{name}: {last[:120]}")
        if action == f"bt-disconnect-{name}":
            r = subprocess.run(["bluetoothctl", "disconnect", mac],
                               capture_output=True, text=True, timeout=20)
            return "Successful" in r.stdout, f"{name} disconnect: " + r.stdout.strip()[-80:]
    units = {"restart-keepalive": "bt-keepalive.service",
             "restart-watchdog": "speaker-watchdog.service",
             "restart-dashboard": "pi-dashboard.service"}
    if action in units:
        unit = units[action]
        if action == "restart-dashboard":   # reply first, then restart ourselves
            def _later():
                time.sleep(0.8)
                subprocess.run(["sudo", "-n", "systemctl", "restart", unit], timeout=30)
            threading.Thread(target=_later, daemon=True).start()
            return True, "dashboard restarting — reload this page in a few seconds"
        r = subprocess.run(["sudo", "-n", "systemctl", "restart", unit],
                           capture_output=True, text=True, timeout=30)
        return r.returncode == 0, (f"{unit} restarted" if r.returncode == 0
                                   else r.stderr.strip()[-120:])
    return None


def control(action):
    r = _manual_action(action)
    if r is not None:
        return r
    if action == "avatar-page-stop":
        _avatar_page_cmd("stop")
        return True, "avatar page: stop sent (portrait held)"
    if action == "avatar-page-resume":
        _avatar_page_cmd("resume")
        return True, "avatar page: resume sent"
    if action.startswith("avatar-page-voice-"):
        mode = action[len("avatar-page-voice-"):]
        if mode not in AVATAR_VOICE_MODES:
            return False, "unknown voice mode " + mode
        _avatar_page_cmd("voice", mode)
        return True, "avatar page: voice → " + mode
    if action == "mute":
        # MIC mute (2026-08-29, user: "mute mic instead of muting the robot"):
        # no MUTE_TRIGGER — playback keeps going; use Interrupt to cut it.
        open(MUTED_FLAG, "w").close()      # stays muted until Unmute mic
        return True, "MIC MUTED — wake word and stop word ignored; robot still speaks (event buttons + Say box work; Interrupt cuts playback)"
    if action == "unmute":
        try:
            os.unlink(MUTED_FLAG)
        except OSError:
            pass
        return True, "mic unmuted — wake word armed again"
    if action == "interrupt":
        open(MUTE_TRIGGER, "w").close()
        return True, "interrupt: current playback cut (not muted)"
    if action == "avatar-voice-on":
        with open("/dev/shm/cj_avatar_audio", "w") as f:
            f.write("solo")
        return True, "robot silenced — the avatar page is the voice"
    if action == "avatar-voice-sync":
        with open("/dev/shm/cj_avatar_audio", "w") as f:
            f.write("sync")
        return True, "both voices — robot delayed to match the avatar"
    if action == "avatar-voice-lips":
        # page open, avatar muted: robot keeps its voice but still holds the
        # head start so the avatar's mouth tracks it. Re-posted every 5s by
        # the page — the robot treats a stale flag (>15s) as "page gone".
        with open("/dev/shm/cj_avatar_audio", "w") as f:
            f.write("lips")
        return True, "avatar mouths along — robot voice"
    if action == "avatar-voice-off":
        try:
            os.unlink("/dev/shm/cj_avatar_audio")
        except OSError:
            pass
        return True, "robot speaker restored"
    if action == "force-listen":
        if os.path.exists(MUTED_FLAG):
            return False, "mic is MUTED — press Unmute mic first"
        open(WAKE_TRIGGER, "w").close()
        return True, "listening activated"
    if action == "camera-off":
        return camera_set(False)
    if action == "camera-on":
        return camera_set(True)
    if action == "event-on":
        with open(EVENT_FLAG, "w") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
        return True, "event mode ON — spoken event questions get the script"
    if action == "event-off":
        try:
            os.unlink(EVENT_FLAG)
        except OSError:
            pass
        return True, "event mode OFF — normal conversation (buttons still work)"
    if action == "replay":
        if not os.path.exists(LAST_ANSWER):
            return False, "no stored answer yet"
        def _play():   # raw-PCM wav written by the app: play directly, no decode
            subprocess.run(["aplay", "-q", LAST_ANSWER])
        threading.Thread(target=_play, daemon=True).start()
        return True, "replaying last answer"
    return False, f"unknown action {action!r}"


def entities_get():
    try:
        return True, open(ENTITY_OVERLAY, encoding="utf-8").read()
    except OSError as e:
        return False, str(e)


def entities_put(text):
    try:
        doc = json.loads(text)
        for k in ("add", "merge", "remove"):
            if k not in doc:
                return False, f"missing top-level key {k!r}"
        if not isinstance(doc["add"], list) or not isinstance(doc["merge"], dict) \
                or not isinstance(doc["remove"], list):
            return False, "add must be a list, merge a dict, remove a list"
        tmp = ENTITY_OVERLAY + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp, ENTITY_OVERLAY)  # atomic; P0 hot-reload picks it up
        return True, "saved — live immediately (no restart)"
    except ValueError as e:
        return False, f"invalid JSON: {e}"
    except OSError as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# /event — phone page with one button per scripted event question
# ---------------------------------------------------------------------------

def _event_entries():
    """The event_* entries from canned_answers.json: scripted question +
    single verbatim answer each. Re-read per request (hot-editable)."""
    try:
        with open(CANNED_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        return [{"id": e["id"], "q": (e.get("ask") or [e["id"]])[0],
                 "a": e["answers"][0]}
                for e in raw.get("entries", [])
                if str(e.get("id", "")).startswith("event_") and e.get("answers")]
    except (OSError, ValueError, KeyError) as e:
        print(f"[event] canned_answers.json unreadable: {e}")
        return []


def ask_event(entry_id):
    """Queue one scripted answer for the robot: write the ask trigger the
    wake loop polls (30 s freshness on the robot side)."""
    for e in _event_entries():
        if e["id"] == entry_id:
            try:
                tmp = ASK_TRIGGER + ".tmp"
                with open(tmp, "w") as f:
                    json.dump({"q": e["q"], "a": e["a"], "id": e["id"]}, f)
                os.replace(tmp, ASK_TRIGGER)
                return True, "queued"
            except OSError as err:
                return False, str(err)
    return False, f"unknown question id: {entry_id!r}"
