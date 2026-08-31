#!/usr/bin/env python3
"""P2.5 dual web UI for the CJAP demo — served by pi_dashboard/dashboard.py.

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
    POST /api/ctl           {"action": mute|unmute|interrupt|force-listen|replay, "key": K}
    GET/POST /api/entities  entity_overrides.json read / validated atomic write
                            (takes effect immediately via P0 hot-reload).

Stdlib only, same discipline as dashboard.py.
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
LAST_ANSWER = "/dev/shm/cj_last_answer.mp3"
SPEAKING = "/dev/shm/cj_speaking.json"   # live per-sentence caption feed
MUTE_TRIGGER = "/dev/shm/cj_mute_trigger"
MUTED_FLAG = "/dev/shm/cj_muted"      # persistent mute state (Mute/Unmute buttons)
WAKE_TRIGGER = "/dev/shm/cj_wake_trigger"
ENTITY_OVERLAY = os.path.join(MAIN, "data", "entities", "entity_overrides.json")
CANNED_PATH = os.path.join(MAIN, "data", "entities", "canned_answers.json")
ASK_TRIGGER = "/dev/shm/cj_ask_trigger"   # /event buttons -> cj_voice_cloud
# Event mode: while this flag exists, spoken questions can match the
# scripted event_* canned entries (canned_answers.event_mode()). Persistent
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
            # auto-stop when nobody has fetched a frame for 90s
            if _cam["last_read"] and time.time() - _cam["last_read"] > 90:
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


def cam_frame(timeout=4.0):
    """Latest JPEG frame (lazy-starts the camera). b'' if unavailable."""
    _cam["last_read"] = time.time()
    with _cam["lock"]:
        if _cam["proc"] is None or _cam["proc"].poll() is not None:
            try:
                p = subprocess.Popen(_CAM_CMD, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)
                _cam["proc"] = p
                threading.Thread(target=_cam_reader, args=(p,), daemon=True).start()
            except Exception:
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
    h["camera"] = bool(_cam["frame"]) and time.time() - _cam["ts"] < 3
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
        "has_last_answer": os.path.exists(LAST_ANSWER),
        "event_mode": os.path.exists(EVENT_FLAG),
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

UI_REV = str(int(os.path.getmtime(__file__)))   # pages reload when this changes
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
        open(MUTED_FLAG, "w").close()      # stays muted until Unmute
        open(MUTE_TRIGGER, "w").close()    # cut whatever is playing right now
        return True, "MUTED — playback cut; wake word and event buttons ignored until Unmute"
    if action == "unmute":
        for f in (MUTED_FLAG, MUTE_TRIGGER):
            try:
                os.unlink(f)
            except OSError:
                pass
        return True, "unmuted — wake word armed again"
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
            return False, "robot is MUTED — press Unmute first"
        open(WAKE_TRIGGER, "w").close()
        return True, "listening activated"
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
        def _play():
            wav = "/dev/shm/cj_replay.wav"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet",
                            "-i", LAST_ANSWER, wav])
            subprocess.run(["aplay", "-q", wav])
            try:
                os.unlink(wav)
            except OSError:
                pass
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
# pages
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


def event_page():
    def esc(t):
        return (t.replace("&", "&amp;").replace("<", "&lt;")
                 .replace(">", "&gt;").replace('"', "&quot;"))
    entries = _event_entries()
    btns = "\n".join(
        f'<button class="q" onclick="ask(\'{esc(e["id"])}\',this)">'
        f'<b>{i + 1}.</b> {esc(e["q"])}</button>'
        for i, e in enumerate(entries)) or \
        '<p class="sub">No event_* entries found in canned_answers.json.</p>'
    return EVENT_PAGE.replace("%BUTTONS%", btns)


# Shared "gallery exhibit" look (2026-08-25): /audience and /face-avatar render
# the same gilt frame + two ivory plaques; only the framed content differs
# (live camera vs the HeyGen avatar video).
EXHIBIT_CSS = """:root{--wall:#1c1916;--ink:#2b2418;--ink2:#5a4d3a;--faint:#8a7b64;--ivory:#f4eddc;--ivory2:#eadfc6;
  --maroon:#6e1f2b;--maroon2:#8b2a38;--brass:#c9a961;--brass2:#8f7332;--ok:#4f7d4a;--warn:#a8642a;--blue:#3b5b8a}
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;color:var(--ink);overflow:hidden;
  font-family:'EB Garamond',Georgia,'Times New Roman',serif;
  /* gallery wall: warm charcoal with a spotlight falling on the portrait */
  background:var(--wall) radial-gradient(ellipse 58% 52% at 50% 34%,rgba(214,190,140,.22) 0%,rgba(214,190,140,.07) 45%,rgba(0,0,0,0) 72%)}
/* the portrait: a gilt frame around the live camera. knobs ?cam=<vw> ?pos=tr|tl */
#cam{position:fixed;top:5.5vh;left:50%;transform:translateX(-50%);
  width:min(44vw,calc(58vh * 16 / 9));aspect-ratio:16/9;background:#000;overflow:hidden;
  /* gallery frame: bevelled gilt moulding, ivory linen mat, dark liners */
  border:1.3vh solid #b8944f;
  border-image:linear-gradient(160deg,#f3e4b4 0%,#c8a55c 18%,#8f7332 34%,#e6cf8f 50%,#a5813f 66%,#f0dda6 84%,#8a6d2c 100%) 1;
  box-shadow:0 0 0 .3vh #2a2115,0 0 0 1.6vh #efe4c8,0 0 0 1.9vh #6b5323,0 0 0 2.1vh #d9c07a,
    0 3.5vh 9vh rgba(0,0,0,.8),inset 0 0 0 .45vh #12100c;
  transition:box-shadow .8s ease}
#cam.live{box-shadow:0 0 0 .3vh #2a2115,0 0 0 1.6vh #efe4c8,0 0 0 1.9vh #6b5323,0 0 0 2.1vh #d9c07a,
    0 3.5vh 9vh rgba(0,0,0,.8),0 0 8vh 1.5vh rgba(230,200,130,.3),inset 0 0 0 .45vh #12100c}
#cam.tr,#cam.tl{transform:none;left:auto;top:5vh;width:min(30vw,calc(34vh * 16 / 9))}
#cam.tr{right:2vw}  #cam.tl{left:2vw}
#cam img{width:100%;height:100%;object-fit:cover;object-position:center;display:block}
#cam .idle{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;
  justify-content:center;color:#cbb98f;font-size:2.4vh;gap:1.2vh;letter-spacing:.06em;
  background:radial-gradient(ellipse at 50% 40%,#2a241b,#120f0b 75%)}
#cam .idle b{font-family:'Playfair Display',Georgia,serif;color:var(--brass);font-size:5.5vh;letter-spacing:.24em;font-weight:500}
/* floor shadow under the plaques */
#scrim{position:fixed;left:0;right:0;bottom:0;height:30vh;pointer-events:none;
  background:linear-gradient(to top,rgba(0,0,0,.3),rgba(0,0,0,0))}
/* the two exhibit plaques: question left, answer right, levelled */
#bar{position:fixed;left:2vw;right:2vw;bottom:2.6vh;display:flex;justify-content:space-between;
  align-items:stretch;gap:2vw;pointer-events:none}
/* plaques (2026-08-25, user): no outline/ring, ivory fades top -> bottom.
   Bottom stop stays ~.45 so the dark ink is still readable over the wall;
   fading to 0 would need light ink. */
.card{min-width:0;min-height:22vh;max-height:42vh;display:flex;flex-direction:column;
  padding:2vh 1.8vw 3vh;border-radius:.6vh;color:var(--ink);
  background:linear-gradient(180deg,rgba(247,241,227,.97) 0%,rgba(244,237,220,.9) 35%,
    rgba(234,223,198,.7) 70%,rgba(234,223,198,.45) 100%);
  box-shadow:none;border:0;
  transition:opacity .6s ease,transform .6s cubic-bezier(.2,.8,.2,1)}
#qbox{flex:0 1 42%} #abox{flex:0 1 46%}
.card.hide{opacity:0;transform:translateY(3vh);pointer-events:none}
.card h3{flex:0 0 auto;display:flex;align-items:center;gap:1vw;margin-bottom:1.3vh;
  font-family:'Playfair Display',Georgia,serif;font-weight:500;font-size:1.7vh;
  letter-spacing:.24em;text-transform:uppercase;color:var(--maroon)}
.card h3::after{content:'';flex:1;height:1px;background:linear-gradient(90deg,var(--brass2),rgba(143,115,50,0))}
.card h3.big{font-size:2.2vh;font-weight:600;color:#4f121c;letter-spacing:.26em}
.row.q{background:none;padding:0 0 .6vh 0;grid-template-columns:minmax(0,1fr) auto}
.row.q .qt{font-size:2.7vh;line-height:1.35;color:#1e1810;font-weight:600}
/* answer */
#a{flex:1;min-height:9vh;overflow-y:auto;scrollbar-width:none;text-align:left;
  font-size:3vh;line-height:1.5;color:var(--ink)}
#a::-webkit-scrollbar{display:none}
#a span{color:var(--ink2);transition:color .5s}
#a .cur{color:var(--maroon);animation:rise .45s ease-out}
#a.idle-text,#qidle{display:flex;flex-wrap:wrap;align-items:center;row-gap:.6vh;font-style:italic;
  color:var(--faint);font-size:2.6vh;line-height:1.5}
#a.idle-text em,#qidle em{color:var(--maroon);font-style:normal;padding:0 .4vw;white-space:nowrap}
/* opening display (2026-08-26, user): the wake phrases show on BOTH plaques */
#qidle{display:none;flex:1} #qbox.idle #qidle{display:flex}
#qbox.idle #qtext,#qbox.idle #rows{display:none}
.rise{animation:rise .45s ease-out}
@keyframes rise{from{opacity:0;transform:translateY(1.2vh)}to{opacity:1;transform:none}}
.think::after{content:'';animation:dots 1.5s steps(4,end) infinite}
@keyframes dots{0%{content:''}25%{content:'.'}50%{content:'..'}75%{content:'...'}}
@keyframes blink{50%{opacity:.25}}
/* question intake rows — exhibit provenance lines */
/* the transcribed question is PINNED above the scrolling pipeline rows (2026-08-25):
   it used to be the first row of #rows and scrolled out of view once the
   Scope/Routed/Composed/Fidelity rows pushed the container to its max height. */
#qtext{flex:0 0 auto;max-height:16vh;overflow-y:auto;scrollbar-width:none}
#qtext::-webkit-scrollbar{display:none}
#rows{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;gap:.7vh;overflow-y:auto;scrollbar-width:none}
#rows::-webkit-scrollbar{display:none}
.row{display:grid;grid-template-columns:2.4vh minmax(0,1fr) auto;gap:.2vh .8vw;align-items:start;
  padding:.9vh 1vw;border-radius:.4vh;background:rgba(120,95,50,.07);animation:rise .45s ease-out}
.row.done{background:rgba(79,125,74,.09)} .row.active{background:rgba(201,169,97,.16)}
.row.flagged{background:rgba(168,100,42,.14)}
.row .ck{font-size:1.9vh;line-height:1.35;text-align:center;color:var(--faint)}
.row.done .ck{color:var(--ok)} .row.flagged .ck{color:var(--warn)}
.row.active .ck{color:var(--brass2);animation:blink 1.1s ease-in-out infinite}
.row .b{min-width:0;font-size:1.9vh;line-height:1.4;color:var(--ink)}
.row .lb{font-family:'Playfair Display',Georgia,serif;font-size:1.3vh;letter-spacing:.18em;
  text-transform:uppercase;color:var(--maroon);margin-right:.6vw;white-space:nowrap}
.row.active .lb{color:var(--brass2)} .row.done .lb{color:var(--maroon)} .row.flagged .lb{color:var(--warn)}
.row .t{font-family:'EB Garamond',Georgia,serif;font-variant-numeric:tabular-nums;font-size:1.5vh;
  color:var(--faint);padding-top:.3vh;white-space:nowrap}
.row code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:1.55vh;padding:.15vh .6vh;
  border-radius:.4vh;background:rgba(79,125,74,.14);color:#2f5a2b}
.row .conf{color:var(--blue);font-size:1.6vh}
.row .rs{display:-webkit-box;color:var(--ink2);font-size:1.65vh;line-height:1.35;margin-top:.3vh;
  overflow:hidden;-webkit-line-clamp:3;-webkit-box-orient:vertical}
.row .qt{font-family:'Playfair Display',Georgia,serif;font-weight:500;font-size:2.1vh;color:var(--ink)}
"""

EXHIBIT_PLAQUES = """<div id="scrim"></div>
<div id="bar">
  <div class="card hide" id="qbox"><h3 class="big">The Question</h3><div id="qidle"></div><div id="qtext"></div><div id="rows"></div></div>
  <div class="card" id="abox"><h3>The Chief Justice Answers</h3><div id="a" class="idle-text"></div></div>
</div>"""

EXHIBIT_JS = """const esc=s=>{const d=document.createElement('div');d.innerText=s||'';return d.innerHTML};
const IDLE='Approach and say <em>&ldquo;Hey, Cee-Jap&rdquo;</em> <em>&ldquo;Hi, Cee-Jap&rdquo;</em> <em>&ldquo;Cee-Jap&rdquo;</em>';
// seconds after the answer ends before the question/answer plaques clear back
// to the idle display (2026-08-26, user); ?idle=<s> overrides, 0 = never clear
const IDLE_AFTER_S=(()=>{const v=parseFloat(new URLSearchParams(location.search).get('idle'));return v>=0?v:8;})();
let curState='';
function setState(st){
  if(st===curState)return;curState=st;
  document.getElementById('cam').classList.toggle('live',st==='speaking');
}
let lastRows='',lastQ='';
function rowHtml(state,label,body,t){
  const ck=state==='done'?'&#10003;':state==='flagged'?'&#9888;':state==='active'?'&#9679;':'&#9675;';
  const ts=(t!=null&&state!=='active')?t.toFixed(1)+'s':'';
  return '<div class="row '+state+'"><span class="ck">'+ck+'</span><div class="b">'+
    '<span class="lb">'+label+'</span>'+body+'</div><span class="t">'+ts+'</span></div>';
}
function renderRows(stage,qText){
  const st=(stage&&stage.steps)||{};
  const tr=st.transcribe||{},rt=st.route||{},cp=st.compose||{},fd=st.fidelity||{};
  const parts=[];
  const qHtml=qText?'<div class="row q"><div class="b"><span class="qt">&ldquo;'+esc(qText)+'&rdquo;</span></div>'+
    '<span class="t">'+(tr.state==='done'&&tr.t!=null?tr.t.toFixed(1)+'s':'')+'</span></div>':'';
  if(qHtml!==lastQ){lastQ=qHtml;document.getElementById('qtext').innerHTML=qHtml;}
  if(!qText&&tr.state==='active')parts.push(rowHtml('active','Transcribed','<span class="think">'+esc(tr.detail||'listening')+'</span>'));
  if(rt.scope)parts.push(rowHtml('done','Scope','<code>'+esc(rt.scope)+'</code>'+
    (rt.scope_reason?'<span class="rs">'+esc(rt.scope_reason)+'</span>':''),rt.t));
  if(rt.state==='active')parts.push(rowHtml('active','Routed','<span class="think">'+esc(rt.detail||'choosing the topic')+'</span>'));
  else if(rt.state==='done')parts.push(rowHtml('done','Routed','<code>'+esc(rt.topic||rt.detail||'')+'</code>'+
    (rt.confidence?' <span class="conf">('+esc(rt.confidence)+')</span>':'')+
    (rt.route_reason?'<span class="rs">'+esc(rt.route_reason)+'</span>':''),rt.t));
  if(cp.state==='active')parts.push(rowHtml('active','Composed','<span class="think">'+esc(cp.detail||'writing')+'</span>'));
  else if(cp.state==='done')parts.push(rowHtml('done','Composed',esc(cp.detail||''),cp.t));
  if(fd.state==='active')parts.push(rowHtml('active','Fidelity','<span class="think">'+esc(fd.detail||'checking')+'</span>'));
  else if(fd.state==='done'||fd.state==='flagged')parts.push(rowHtml(fd.state,'Fidelity',esc(fd.detail||'')+
    (fd.state==='flagged'&&fd.reason?'<span class="rs">'+esc(fd.reason)+'</span>':''),fd.t));
  const html=parts.join('');
  if(html===lastRows)return;lastRows=html;
  const el=document.getElementById('rows');el.innerHTML=html;el.scrollTop=el.scrollHeight;
}
let lastRender='';
function render(html,idle,showQ){
  const a=document.getElementById('a');
  const key=html+(showQ?1:0);
  if(key===lastRender)return;lastRender=key;
  const opening=idle&&!showQ;   // first-turned-on display: wake phrases on both plaques
  const qb=document.getElementById('qbox');
  qb.classList.toggle('hide',!showQ&&!opening);qb.classList.toggle('idle',opening);
  if(opening)document.getElementById('qidle').innerHTML=html;
  a.classList.toggle('idle-text',!!idle);
  a.innerHTML=html;
  const cur=a.querySelector('.cur');
  if(cur)cur.scrollIntoView({block:'center',behavior:'smooth'});
  else a.scrollTop=a.scrollHeight;
}
function renderExhibit(s){
    const turns=s.turns||[];
    const lastU=turns.filter(t=>t.role==='user').slice(-1)[0];
    const lastC=turns.filter(t=>t.role==='cj').slice(-1)[0];
    const sp=s.speaking,stg=s.stage;
    const turnTs=stg?stg.turn_ts:0;
    const qNow=(lastU&&lastU.ts>=turnTs-1)?lastU.text:'';
    const listening=stg&&stg.steps&&stg.steps.transcribe&&
      stg.steps.transcribe.state==='active'&&(s.ts-stg.ts)<60;
    renderRows(stg,qNow||(lastU?lastU.text:''));
    // 1. speaking right now: sentence-by-sentence, current in gold
    if(sp&&!sp.done&&(sp.spoken||[]).length){
      setState('speaking');
      render(sp.spoken.map((t,i)=>'<span'+(i===sp.spoken.length-1?' class="cur"':'')+
          '>'+esc(t)+'</span>').join(' '),false,true);
      return;
    }
    // 2. mic open / transcribing
    if(listening&&!qNow){setState('listening');
      render('<span class="think">Listening</span>',true,true);return;}
    // 3. question heard, answer being prepared
    if(lastU&&(!sp||lastU.ts>sp.ts)&&(!lastC||lastU.ts>lastC.ts)){setState('thinking');
      render('<span class="think">The Chief Justice is considering</span>',true,true);return;}
    // 4. finished: keep the full answer and its intake on screen
    setState('idle');
    // ...then IDLE_AFTER_S seconds later (robot clock) fade back to the opening display
    const endTs=(sp&&sp.done&&(sp.spoken||[]).length)?sp.ts:(lastC?lastC.ts:0);
    const stale=IDLE_AFTER_S>0&&endTs>0&&(s.ts-endTs)>=IDLE_AFTER_S;
    if(!stale&&sp&&sp.done&&(sp.spoken||[]).length){render(esc(sp.spoken.join(' ')),false,!!lastU);return;}
    if(!stale&&lastC){render(esc(lastC.text),false,!!lastU);return;}
    render(IDLE,true,false);
}
"""

AUDIENCE_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chief Justice Artemio V. Panganiban</title><link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,500;0,600;1,500&family=EB+Garamond:ital,wght@0,400;0,500;1,400&display=swap" rel="stylesheet">
<style>
""" + EXHIBIT_CSS + """
/* robot status pill, top-left (2026-08-25, user): green = listening, red
   waveform = speaking (follows the sentence audio), gray = idle, red = muted */
#rs{position:fixed;top:2.4vh;left:2vw;z-index:5;display:flex;align-items:center;gap:1vw;
  padding:1vh 1.5vw;border-radius:999px;background:rgba(20,16,12,.74);
  border:1px solid rgba(201,169,97,.45);box-shadow:0 .6vh 2vh rgba(0,0,0,.5);pointer-events:none;
  font-family:'Playfair Display',Georgia,serif;letter-spacing:.2em;text-transform:uppercase;
  font-size:1.6vh;color:#e8dcc0;transition:border-color .3s}
#rs.tr{left:auto;right:2vw}
#rs .dot{width:2.2vh;height:2.2vh;border-radius:50%;background:#7a7368;flex:0 0 auto;
  box-shadow:0 0 0 .3vh rgba(255,255,255,.08);transition:background .3s,box-shadow .3s}
#rs.listening .dot{background:#3fb950;box-shadow:0 0 1.6vh .2vh rgba(63,185,80,.55);animation:rspulse 1.2s ease-in-out infinite}
#rs.listening{border-color:rgba(63,185,80,.6)}
#rs.thinking .dot{background:#c9a961;box-shadow:0 0 1.2vh .1vh rgba(201,169,97,.5);animation:rspulse 1.2s ease-in-out infinite}
#rs.muted .dot{background:#e5484d;box-shadow:0 0 1.6vh .2vh rgba(229,72,77,.55)}
#rs.muted{border-color:rgba(229,72,77,.6)}
#rs.talking .dot{display:none}
#rs canvas{display:none;height:3.2vh;width:13vh}
#rs.talking canvas{display:block}
#rs.talking{border-color:rgba(229,72,77,.6)}
@keyframes rspulse{50%{transform:scale(.78);opacity:.65}}
</style></head><body>
<div id="cam"><img id="camimg" alt="">
  <div class="idle" id="camidle"><b>CJAP</b>
    <span>Chief Justice Artemio V. Panganiban</span></div>
</div>
<div id="rs" class="idle"><span class="dot"></span><canvas id="rsw" width="160" height="40"></canvas><span class="lbl">Idle</span></div>
""" + EXHIBIT_PLAQUES + """<script>
""" + EXHIBIT_JS + """const qs=new URLSearchParams(location.search),camW=parseFloat(qs.get('cam'));
if(camW>10&&camW<=100)document.getElementById('cam').style.width=camW+'vw';
if(['tr','tl'].includes(qs.get('pos')))document.getElementById('cam').classList.add(qs.get('pos'));
// ---- robot status pill ----------------------------------------------------
const RS=document.getElementById('rs'),RSW=document.getElementById('rsw'),RSL=RS.querySelector('.lbl');
if(qs.get('pos')==='tl')RS.classList.add('tr');   // portrait is top-left: pill moves right
let rsState='',rsClock=0,rsClip=null;const rsEnv={};
function setIndicator(st,label){
  if(st!==rsState){rsState=st;RS.className=st+(qs.get('pos')==='tl'?' tr':'');}   // keep the side class
  if(RSL.innerText!==label)RSL.innerText=label;
}
// loudness envelope (40 ms windows) of a sentence wav, parsed from the PCM
// directly (24 kHz/16-bit/mono from /api/sentence.wav) — no AudioContext,
// so it works without a user gesture on the kiosk browser
async function loadEnv(name){
  if(rsEnv[name]!==undefined)return;rsEnv[name]=null;
  try{
    const b=await(await fetch('/api/sentence.wav?name='+encodeURIComponent(name))).arrayBuffer();
    const dv=new DataView(b);let off=12,sr=24000,data=null;
    while(off+8<=b.byteLength){
      const id=String.fromCharCode(dv.getUint8(off),dv.getUint8(off+1),dv.getUint8(off+2),dv.getUint8(off+3));
      const sz=dv.getUint32(off+4,true);
      if(id==='fmt ')sr=dv.getUint32(off+12,true);
      if(id==='data'){const end=Math.min(b.byteLength,off+8+sz);data=new Int16Array(b.slice(off+8,end-((end-off-8)%2)));break;}
      off+=8+sz+(sz&1);
    }
    if(!data||!data.length)return;
    const win=Math.max(1,Math.round(sr*0.04)),env=[];
    for(let i=0;i+win<=data.length;i+=win){let a=0;for(let j=i;j<i+win;j++){const v=data[j]/32768;a+=v*v;}env.push(Math.sqrt(a/win));}
    const mx=Math.max(0.05,...env);
    rsEnv[name]={sr:sr,win:win,env:env.map(v=>v/mx)};
  }catch(e){}
}
function drawWave(){
  requestAnimationFrame(drawWave);
  if(rsState!=='talking')return;
  const ctx=RSW.getContext('2d'),W=RSW.width,H=RSW.height;ctx.clearRect(0,0,W,H);
  const n=18,bw=W/n,e=rsClip&&rsClip.wav?rsEnv[rsClip.wav]:null;
  const t=Date.now()/1000-rsClock-(rsClip?rsClip.t0:0);   // seconds into the clip (robot clock)
  ctx.fillStyle='#e5484d';
  for(let i=0;i<n;i++){
    let v;
    if(e&&e.env.length){const k=Math.floor((t+(i-n/2)*0.04)*e.sr/e.win);v=(k>=0&&k<e.env.length)?e.env[k]:0.06;}
    else v=0.2+0.55*Math.abs(Math.sin(Date.now()/95+i*0.8));   // no envelope: generic motion
    const h=Math.max(3,v*H);ctx.fillRect(i*bw+1.5,(H-h)/2,bw-3,h);
  }
}
drawWave();
function updateIndicator(s){
  rsClock=Date.now()/1000-s.ts;   // browser-vs-robot clock offset (refreshed every poll)
  const sp=s.speaking,as=s.aside;
  if(s.muted){rsClip=null;setIndicator('muted','Muted');return;}
  const answer=sp&&!sp.done&&(sp.spoken||[]).length;
  const aside=as&&as.wav&&(s.ts-as.ts)<((as.dur||1.5)+0.3);   // ack / filler clip on air
  if(answer||aside){
    const src=answer?sp:as,t0=src.play_ts||src.ts;
    if(!rsClip||rsClip.wav!==src.wav||rsClip.t0!==t0){rsClip={wav:src.wav||null,t0:t0};if(src.wav)loadEnv(src.wav);}
    setIndicator('talking','Speaking');return;
  }
  rsClip=null;
  if(curState==='listening'){setIndicator('listening','Listening');return;}
  if(curState==='thinking'){setIndicator('thinking','Thinking');return;}
  setIndicator('idle','Idle');
}
let camOK=false;
function camTick(){
  const img=document.getElementById('camimg'),probe=new Image();
  probe.onload=()=>{img.src=probe.src;camOK=true;document.getElementById('camidle').style.display='none';};
  probe.onerror=()=>{if(!camOK)document.getElementById('camidle').style.display='flex';};
  probe.src='/api/camera.jpg?t='+Date.now();
}
async function poll(){
  try{
    const s=await (await fetch('/api/state')).json();
    if(window.__uiRev==null)window.__uiRev=s.ui_rev||null;else if(s.ui_rev&&s.ui_rev!==window.__uiRev){location.reload();return;}
    renderExhibit(s);
    updateIndicator(s);
  }catch(e){/* audience view never shows errors */}
}
setInterval(poll,300);poll();
setInterval(camTick,150);camTick();
</script></body></html>"""


MAINTAIN_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CJAP — Maintenance</title><style>
:root{--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;--dim:#8b949e;--gold:#c9a227;
  --ok:#3fb950;--bad:#f85149;--line:#21262d;--btn:#21262d;--btnline:#30363d}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,Segoe UI,Arial,sans-serif;padding:0 16px 24px}
.hdr{position:sticky;top:0;z-index:5;background:rgba(13,17,23,.96);backdrop-filter:blur(6px);
  border-bottom:1px solid var(--line);margin:0 -16px 16px;padding:12px 16px;
  display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px 16px}
h1{font-size:24px;font-weight:700;line-height:1.2}h1 b{color:var(--gold)}
h1 small{display:block;font-size:14px;font-weight:400;color:var(--dim);margin-top:2px}
h1 small a{color:var(--gold);text-decoration:none}h1 small a:hover{text-decoration:underline}
.statuslinks{display:flex;gap:10px;flex-wrap:wrap}
.statuslinks a{display:inline-flex;align-items:center;gap:9px;padding:11px 18px;border-radius:10px;
  font-size:16px;font-weight:600;background:var(--btn);border:1px solid var(--btnline);
  color:var(--ink);text-decoration:none;white-space:nowrap}
.statuslinks a:hover{border-color:var(--gold);color:var(--gold)}
.statuslinks a i{width:10px;height:10px;border-radius:50%;background:var(--ok);display:inline-block}
.grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:14px}
.sec{grid-column:1/-1;font-size:13px;color:var(--dim);text-transform:uppercase;letter-spacing:.14em;
  margin-top:10px;padding-bottom:4px;border-bottom:1px solid var(--line)}
.sec:first-child{margin-top:0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;min-width:0;grid-column:span 4}
.c6{grid-column:span 6}.c8{grid-column:span 8}.c12{grid-column:1/-1}
@media(max-width:1200px){.card,.c6,.c8{grid-column:span 6}.c12{grid-column:1/-1}}
@media(max-width:760px){.card,.c6,.c8,.c12{grid-column:1/-1}body{padding:0 10px 20px}
  .hdr{margin:0 -10px 12px;padding:10px}h1{font-size:20px}.statuslinks a{flex:1;justify-content:center}}
h2{font-size:15px;color:var(--gold);text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px;
  display:flex;align-items:center;gap:8px;flex-wrap:wrap}
h3{font-size:15px;margin:0 0 6px}
.chip{display:inline-block;padding:4px 12px;border-radius:999px;font-size:13px;margin:0 6px 6px 0;background:#21262d}
.chip.ok{color:var(--ok)}.chip.bad{color:var(--bad)}
button{background:var(--btn);border:1px solid var(--btnline);color:var(--ink);border-radius:10px;
  padding:12px 18px;margin:0;font-size:16px;font-weight:600;cursor:pointer;min-height:46px}
button:hover{border-color:var(--gold)}button:active{transform:translateY(1px)}
button.sm{padding:6px 12px;font-size:14px;min-height:0;font-weight:500}
.btns{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:10px}
.btns .lbl{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.1em;min-width:56px}
input[type=text],input[type=password],input:not([type]){background:#0d1117;color:var(--ink);border:1px solid #30363d;border-radius:8px;padding:10px 12px;font-size:15px}
select{background:#21262d;color:var(--ink);border:1px solid #30363d;border-radius:8px;padding:6px 10px;font-size:14px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
td,th{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--dim);font-weight:600}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:13px}
.bar{height:8px;background:#21262d;border-radius:4px;overflow:hidden;margin:2px 0 6px}
.bar i{display:block;height:100%;background:var(--gold)}
textarea{width:100%;height:240px;background:#0d1117;color:var(--ink);border:1px solid #30363d;
  border-radius:8px;font-family:ui-monospace,Consolas,monospace;font-size:13px;padding:10px;margin-bottom:10px}
.raw{color:var(--bad)}.fix{color:var(--ok)}
#msg{color:var(--dim);font-size:13px;display:block;min-height:1.3em}
.saybox{flex-wrap:nowrap}.saybox input{flex:1 1 auto;min-width:0;height:46px}
@media(max-width:600px){.saybox{flex-wrap:wrap}.saybox input{flex-basis:100%}}
img#cam{width:100%;border-radius:8px;background:#000;min-height:120px;display:block}
.dim{color:var(--dim)}
pre{max-height:280px;overflow:auto;white-space:pre-wrap;background:#0d1117;border-radius:8px;padding:10px}
</style></head><body>
<div class="hdr">
<h1><b>CJAP</b> Maintenance<small>audience view: <a href="/audience" target="_blank">/audience</a> &middot; ops: <a href="/" target="_blank">/</a></small></h1>
<div class="statuslinks" title="Provider status pages (open in new tab)">
  <a href="https://status.claude.com" target="_blank" rel="noopener"><i></i>Claude status</a>
  <a href="https://status.elevenlabs.io" target="_blank" rel="noopener"><i></i>ElevenLabs status</a>
</div>
</div>
<div class="grid">
<div class="sec">Live</div>
<div class="card c8"><h2>Health</h2><div id="health"></div><div id="flags"></div>
  <h2 style="margin-top:12px">Controls</h2>
  <div class="btns"><span class="lbl">Speech</span>
    <button id="btn-mute" onclick="ctl('mute')">&#128263; Mute</button>
    <button id="btn-unmute" onclick="ctl('unmute')" style="display:none;background:var(--bad)">&#128266; UNMUTE</button>
    <button onclick="ctl('interrupt')">&#9209; Interrupt</button>
    <button onclick="ctl('force-listen')">&#127908; Force listen</button>
    <button onclick="ctl('replay')">&#128260; Replay last</button></div>
  <div class="btns"><span class="lbl">App</span>
    <button onclick="act('restart-app')">&#8635; Restart app</button>
    <button onclick="act('test-sound')">&#128266; Test sound</button>
    <button onclick="act('tagalog-sample')">&#127908; Tagalog sample</button>
    <button onclick="rebootPi()" style="border-color:var(--bad)">&#9211; Reboot Pi</button></div>
  <div class="btns"><span class="lbl">Event</span>
    <button id="btn-ev-on" onclick="ctl('event-on')">&#127915; Event mode ON</button>
    <button id="btn-ev-off" onclick="ctl('event-off')" style="display:none;border-color:var(--gold)">&#127915; Event mode OFF</button>
    <span class="dim" id="ev-hint">scripted event questions answer with the script (paraphrases too)</span></div>
  <div class="btns saybox"><span class="lbl">Say</span>
    <input type="text" id="say-text" maxlength="500" placeholder="Type what CJ should say, then press Enter or Speak" autocomplete="off">
    <button id="say-btn" onclick="sayText()">&#128483; Speak</button></div>
  <span id="msg"></span>
</div>
<div class="card c8"><h2>Manual actions</h2>
  <div class="btns"><span class="lbl">Tuning</span>
    <label class="dim">Wake threshold <input type="number" id="tn-wake" step="0.01" min="0.01" max="1" style="width:92px"></label>
    <label class="dim">Stop threshold <input type="number" id="tn-stop" step="0.005" min="0.001" max="1" style="width:92px"></label>
    <label class="dim">Listen time (s) <input type="number" id="tn-listen" step="0.1" min="0.3" max="10" style="width:92px"></label>
    <button onclick="applyTuning()">&#10003; Apply &amp; restart app</button>
    <span class="dim" id="tn-hint">values from wakeword.conf; listen time = silence after your last word before CJ answers; applying restarts the voice app (~25 s quiet)</span></div>
  <div class="btns"><span class="lbl">Speaker</span>
    <button onclick="act('audio-sony')">&#128264; Sony</button>
    <button onclick="act('audio-marshall')">&#128264; Marshall</button>
    <button onclick="act('audio-internal')">&#129302; Internal</button>
    <button onclick="ctl('bt-connect-sony')">&#128268; Reconnect Sony</button>
    <button onclick="ctl('bt-connect-marshall')">&#128268; Reconnect Marshall</button>
    <button onclick="ctl('bt-pulse')">&#12336; Pulse BT speaker</button>
    <button onclick="act('stop-watchdog')">Watchdog off</button>
    <button onclick="act('start-watchdog')">Watchdog on</button>
    <span class="dim">the watchdog puts audio back on a connected Bluetooth speaker within 15 s — switch it off first to stay on Internal</span></div>
  <div class="btns"><span class="lbl">Voice ID</span>
    <button onclick="act('enroll-voice')">&#127908; Enroll voice</button>
    <button onclick="act('gate-on')">Gate on</button>
    <button onclick="act('gate-off')">Gate off</button></div>
  <div class="btns"><span class="lbl">Services</span>
    <button onclick="ctl('restart-keepalive')">&#8635; bt-keepalive</button>
    <button onclick="ctl('restart-watchdog')">&#8635; speaker-watchdog</button>
    <button onclick="ctl('restart-dashboard')">&#8635; dashboard</button></div>
  <span id="msg2" class="dim"></span>
</div>
<div class="card"><h2>Camera</h2><img id="cam" alt="(camera offline)"></div>
<div class="card"><h2>System</h2><div id="services"></div><div id="sys" class="dim">loading&hellip;</div></div>
<div class="card"><h2>Wake meter <span class="dim" id="wakenow"></span></h2>
  <div class="bar" style="height:14px"><i id="wakebar" style="width:0%"></i></div>
  <canvas id="spark" style="width:100%;height:64px;background:#0d1117;border-radius:6px"></canvas>
  <table id="wake"><tr><th>time</th><th>score</th></tr></table></div>
<div class="card"><h2>Stop meter <span class="dim" id="stopnow"></span></h2>
  <div class="bar" style="height:14px"><i id="stopbar" style="width:0%"></i></div>
  <canvas id="stopspark" style="width:100%;height:64px;background:#0d1117;border-radius:6px"></canvas>
  <table id="stopt"><tr><th>time</th><th>score</th></tr></table></div>
<div class="card"><h2>LiveAvatar page <span class="dim" id="avstate"></span></h2>
  <div id="avstatus" class="dim" style="margin-bottom:10px">no /face-avatar page open</div>
  <div class="btns"><span class="lbl">Page</span>
    <button id="av-stop" onclick="ctl('avatar-page-stop')">&#9209; Stop</button>
    <button id="av-resume" onclick="ctl('avatar-page-resume')">&#9654; Resume</button></div>
  <div class="btns"><span class="lbl">Voice</span>
    <button id="av-robot" onclick="ctl('avatar-page-voice-robot')">robot (avatar mouths along)</button>
    <button id="av-avatar" onclick="ctl('avatar-page-voice-avatar')">avatar only</button>
    <button id="av-sync" onclick="ctl('avatar-page-voice-sync')">both synced</button></div>
  <a class="dim" href="/face?key=" id="avlink" target="_blank">open page &#8599;</a></div>
<div class="sec">Connectivity</div>
<div class="card c6"><h2>WiFi <span class="dim" id="wifinow"></span></h2>
  <div id="wifi-list" class="dim" style="margin-bottom:10px">tap Scan to list networks (tap a network to switch)</div>
  <div class="btns"><button onclick="wifiScan()">&#128246; Scan networks</button><span id="netmsg" class="dim"></span></div>
  <div class="btns" style="margin-top:4px">
    <input id="wm-ssid" placeholder="network name" style="flex:1;min-width:140px">
    <input id="wm-pw" type="password" placeholder="password" style="flex:1;min-width:140px">
    <button onclick="wifiManual()">Join</button></div>
  <div class="dim" style="font-size:13px">Manual entry works in setup-hotspot mode and for hidden networks.
    &#9888; Switching networks drops this page — rejoin the same WiFi on your phone.</div>
</div>
<div class="card c6"><h2>Bluetooth <span class="dim" id="btnow"></span></h2>
  <div id="bt-list" class="dim" style="margin-bottom:10px">loading&hellip;</div>
  <div class="btns"><button onclick="btScan(false)">&#8635; Refresh</button>
    <button onclick="btScan(true)">&#128270; Scan (~10 s)</button><span id="btmsg" class="dim"></span></div>
  <div class="btns"><span class="lbl">Speaker</span>
    <button onclick="act('audio-internal')">&#129302; Internal</button>
    <button onclick="act('audio-sony')">&#128266; Sony</button>
    <button onclick="act('audio-marshall')">&#128266; Marshall</button></div>
  <div class="dim" style="font-size:13px">Tap a device to connect / disconnect / pair. The speaker watchdog re-routes to the Sony within 15 s when it is connected.</div>
</div>
<div class="sec">Conversation</div>
<div class="card"><h2>Current turn</h2><div id="turn" class="dim">no turn yet</div>
  <h2 style="margin-top:12px">Stage latency</h2><div id="lat" class="dim">&mdash;</div></div>
<div class="card c8"><h2>Grounding documents <span class="dim">(composer context, last turn)</span></h2>
  <div id="docs" class="dim" style="max-height:280px;overflow:auto">no turn yet</div></div>
<div class="card c8"><h2>Conversation (raw vs corrected)</h2>
  <table id="conv"><tr><th>who</th><th>text</th></tr></table></div>
<div class="card"><h2>NER corrections (P0)</h2>
  <table id="ner"><tr><th>heard</th><th>&rarr; canonical</th><th>class</th><th>conf</th></tr></table></div>
<div class="card c12"><h2>Recent turns (tracking)</h2>
  <div style="overflow-x:auto"><table id="hist"><tr><th>time</th><th>question</th><th>theme</th>
  <th>docs</th><th>tokens</th><th>cost</th><th>STT s</th><th>compose s</th><th>speech</th><th>wpm</th><th>flags</th></tr></table></div></div>
<div class="sec">Providers</div>
<div class="card c12"><h2>Usage &amp; errors <span class="dim" id="usagets"></span></h2>
  <div id="prov" class="dim" style="margin-bottom:10px">checking providers&hellip;</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px">
    <div><h3>Claude (Anthropic)</h3><div id="u-claude" class="dim">loading&hellip;</div></div>
    <div><h3>ElevenLabs (cloned voice)</h3><div id="u-eleven" class="dim">loading&hellip;</div></div>
    <div><h3>OpenAI (speech-to-text)</h3><div id="u-openai" class="dim">loading&hellip;</div></div>
  </div>
  <h3 style="margin:14px 0 6px">Recent errors &amp; operator actions <span class="dim">(this boot, newest last)</span></h3>
  <pre id="errs" class="mono">loading&hellip;</pre>
</div>
<div class="sec">Admin</div>
<div class="card c6"><h2>Logs
  <select id="logunit" onchange="loadLogs()">
    <option value="supervaise">supervaise</option>
    <option value="wifi-fallback">wifi-fallback</option>
    <option value="speaker-watchdog">speaker-watchdog</option>
  </select>
  <button class="sm" onclick="loadLogs()">refresh</button></h2>
  <pre id="logs" class="mono"></pre></div>
<div class="card c6"><h2>Entity dictionary overlay <span class="dim">(saves live, no restart)</span></h2>
  <textarea id="ov" spellcheck="false"></textarea>
  <div class="btns"><button onclick="saveOv()">&#128190; Save overlay</button><span id="ovmsg" class="dim"></span></div></div>
</div><script>
const KEY=new URLSearchParams(location.search).get('key')||localStorage.getItem('cjkey')||'';
if(KEY)localStorage.setItem('cjkey',KEY);
const esc=s=>{const d=document.createElement('div');d.innerText=s==null?'':s;return d.innerHTML};
const $=id=>document.getElementById(id);
function note(t){$('msg').innerText=t;if($('msg2'))$('msg2').innerText=t;}
async function ctl(a){note(a+'\\u2026');const r=await(await fetch('/api/ctl',{method:'POST',
  body:JSON.stringify({action:a,key:KEY})})).json();
  note(r.output||'');}
async function loadTuning(){try{const r=await(await fetch('/api/tuning?key='+KEY)).json();const t=r.tuning||{};
  for(const k of ['wake','stop','listen']){const el=$('tn-'+k);if(el&&t[k]!=null&&document.activeElement!==el)el.value=t[k];}
  if(t.error)$('tn-hint').innerText=t.error;}catch(e){}}
async function applyTuning(){const b={key:KEY};for(const k of ['wake','stop','listen'])b[k]=$('tn-'+k).value;
  if(!confirm('Apply tuning and restart the voice app? CJ goes quiet for about 25 s.'))return;
  note('applying\\u2026');const r=await(await fetch('/api/tuning',{method:'POST',body:JSON.stringify(b)})).json();
  note((r.ok?'':'FAILED: ')+(r.output||''));setTimeout(loadTuning,3000);}
loadTuning();
async function sayText(){const t=$('say-text').value.trim();if(!t)return;
  const b=$('say-btn');b.disabled=true;$('msg').innerText='speaking\\u2026';
  try{const r=await(await fetch('/api/say-text',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text:t,key:KEY})})).json();
    $('msg').innerText=r.ok?'spoken: '+t.slice(0,80):'FAILED: '+(r.output||'');
    if(r.ok)$('say-text').value='';}
  catch(e){$('msg').innerText='FAILED: '+e.message}
  b.disabled=false;}
$('say-text').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();sayText();}});
async function act(a){note(a+'\\u2026');
  const r=await(await fetch('/api/action',{method:'POST',
    body:JSON.stringify({action:a})})).json();
  note(r.ok?a+' ok':'FAILED: '+(r.output||''));}
async function rebootPi(){
  if(!confirm('Reboot the Pi? The robot goes quiet for about a minute.'))return;
  const say=t=>{$('msg').innerText=t;};
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  // fetch with a hard timeout: a SYN to a dead host can hang 1-2 min otherwise
  const ping=async()=>{const c=new AbortController();const t=setTimeout(()=>c.abort(),4000);
    try{const r=await fetch('/api/state?_='+Date.now(),{cache:'no-store',signal:c.signal});
      if(!r.ok)return null;return await r.json();}catch(e){return null;}finally{clearTimeout(t);}};
  const before=await ping();const oldBoot=before&&before.boot_id||null;
  // stop every poller/camera timer on this page so they don't pile up hung
  // requests against the dead host (browser caps 6 connections per host)
  const top=setInterval(()=>{},100000);for(let i=1;i<=top;i++)clearInterval(i);
  window.__rebooting=true;
  say('rebooting... this page reconnects on its own');
  try{const c=new AbortController();setTimeout(()=>c.abort(),8000);
    const r=await fetch('/api/action',{method:'POST',body:JSON.stringify({action:'reboot'}),signal:c.signal});
    const j=await r.json();if(!j.ok){say('reboot FAILED: '+(j.output||''));return;}
  }catch(e){}   // server usually dies before answering - that is fine
  const t0=Date.now();const el=()=>Math.round((Date.now()-t0)/1000)+'s';
  // phase 1: wait for the box to actually go away (a reload now would just
  // land on a dying server).  Give up waiting after 3 min and go to phase 2.
  let down=false;
  while(Date.now()-t0<180000){const s=await ping();
    if(!s||(oldBoot&&s.boot_id&&s.boot_id!==oldBoot)){down=true;break;}
    say('shutting down... '+el());await sleep(2000);}
  if(!down)say('server still answering after 3 min - waiting for it to come back anyway');
  // phase 2: wait for a *fresh* boot (new boot_id, or uptime < 5 min when the
  // old id is unknown), then hard-navigate.  Up to 10 min.
  while(Date.now()-t0<600000){const s=await ping();
    if(s&&((oldBoot&&s.boot_id&&s.boot_id!==oldBoot)||(!oldBoot&&s.uptime_s!=null&&s.uptime_s<300))){
      say('back up - reloading');await sleep(1500);
      location.replace(location.pathname+location.search);return;}
    say(s?'still shutting down... '+el():'waiting for the Pi to come back... '+el());
    await sleep(3000);}
  say('still offline after 10 min - reload manually');}
async function loadOv(){const r=await(await fetch('/api/entities?key='+KEY)).json();
  if(r.ok)$('ov').value=r.content;}
async function saveOv(){const r=await(await fetch('/api/entities?key='+KEY,{method:'POST',
  body:JSON.stringify({content:$('ov').value,key:KEY})})).json();
  $('ovmsg').innerText=r.output;}
function fmtTok(n){n=n||0;return n>=1e6?(n/1e6).toFixed(2)+'M':n>=1e3?(n/1e3).toFixed(1)+'k':String(Math.round(n))}
function claudeRow(name,s){if(!s)return '';const t=(s.input||0)+(s.cache_write||0)+(s.cache_read||0);
  return '<b>'+name+'</b>: '+s.calls+' calls · in '+fmtTok(t)+' (cached '+fmtTok(s.cache_read)+') · out '+fmtTok(s.output)+' · $'+(s.cost_usd||0).toFixed(3)+'<br>'}
async function loadUsage(){try{
  const u=await(await fetch('/api/usage')).json();const L=u.usage.lifetime||{},S=u.usage.session||{};
  const cost=o=>Object.values(o.anthropic||{}).reduce((a,s)=>a+(s.cost_usd||0),0);
  let h='<span class="dim">session</span><br>';for(const k of ['router','inference'])h+=claudeRow(k==='router'?'Haiku router/gate/audit':'Sonnet composer',(S.anthropic||{})[k]);
  h+='<b>session total $'+cost(S).toFixed(3)+'</b> · lifetime $'+cost(L).toFixed(2)+' ('+fmtTok(Object.values(L.anthropic||{}).reduce((a,s)=>a+(s.input||0)+(s.cache_write||0)+(s.cache_read||0)+(s.output||0),0))+' tok)';
  $('u-claude').innerHTML=h;
  const e=u.eleven||{},el=L.elevenlabs||{},es=S.elevenlabs||{};
  let g='';
  if(e.error){g+='<span class="raw">quota: '+esc(e.error)+'</span><br>'}else{const pct=e.character_limit?Math.round(100*e.character_count/e.character_limit):0;
    g+='<b>'+fmtTok(e.character_count)+' / '+fmtTok(e.character_limit)+' chars</b> used this cycle ('+pct+'%) · '+esc(e.tier)+' · resets '+(e.next_character_count_reset_unix?new Date(e.next_character_count_reset_unix*1000).toLocaleDateString():'?')+bar(e.character_count||0,e.character_limit||1)}
  g+='<span class="dim">session</span>: '+(es.requests||0)+' synth · '+fmtTok(es.chars)+' chars billed · '+(es.cache_hits||0)+' from cache<br><span class="dim">lifetime</span>: '+fmtTok(el.chars)+' billed · '+fmtTok(el.cache_chars)+' cached';
  $('u-eleven').innerHTML=g;
  const os_=S.openai||{},ol=L.openai||{};
  $('u-openai').innerHTML='<span class="dim">session</span>: '+(os_.stt_calls||0)+' transcriptions · '+Math.round(os_.stt_seconds||0)+' s audio<br><span class="dim">lifetime</span>: '+(ol.stt_calls||0)+' · '+Math.round((ol.stt_seconds||0)/60)+' min';
  $('usagets').innerText='updated '+new Date(u.ts*1000).toLocaleTimeString();
}catch(err){for(const id of ['u-claude','u-eleven','u-openai'])$(id).innerText='usage fetch failed';}}
async function loadErrors(){try{const r=await(await fetch('/api/errors')).json();
  const rows=r.rows||[];$('errs').textContent=rows.length?rows.map(x=>x.t+'  '+x.unit.padEnd(5)+' '+x.msg).join('\\n'):'no errors this boot';
  $('errs').scrollTop=$('errs').scrollHeight;}catch(e){$('errs').textContent='error fetch failed';}}
function provChip(label,p){if(!p)return '';const api=p.ok?chip(label+' API',true,'OK '+(p.s!=null?p.s+'s':'')):chip(label+' API',false,p.error||('HTTP '+p.code));
  const pg=p.page||{},ind=pg.indicator||'unknown',good=ind==='none';
  const pageTxt=ind==='unknown'?'status page n/a':(pg.description||ind);
  return '<span style="display:inline-block;margin:0 14px 6px 0">'+api+
    '<span class="'+(good?'fix':(ind==='unknown'?'dim':'raw'))+'" style="font-size:12px">'+esc(pageTxt)+'</span></span>'}
async function loadProviders(){try{const p=await(await fetch('/api/providers')).json();
  $('prov').innerHTML=provChip('Claude',p.claude)+provChip('ElevenLabs',p.elevenlabs)+provChip('OpenAI',p.openai)+
    '<span class="dim" style="font-size:11px">checked '+new Date(p.ts*1000).toLocaleTimeString()+'</span>';
}catch(e){$('prov').innerText='provider check failed';}}
setInterval(loadProviders,60000);loadProviders();
setInterval(loadUsage,15000);setInterval(loadErrors,10000);loadUsage();loadErrors();
async function loadLogs(){try{
  const t=await(await fetch('/api/logs?unit='+$('logunit').value+'&lines=80')).text();
  $('logs').textContent=t;
  $('logs').scrollTop=$('logs').scrollHeight;}catch(e){$('logs').textContent='log fetch failed';}}
function bar(v,max){return '<div class="bar"><i style="width:'+Math.min(100,100*v/max)+'%"></i></div>'}
function chip(k,ok,txt){return '<span class="chip '+(ok?'ok':'bad')+'">'+k+' '+(txt||(ok?'&#10003;':'&#10007;'))+'</span>'}
async function poll(){try{
  const s=await(await fetch('/api/state')).json();
  if(window.__uiRev==null)window.__uiRev=s.ui_rev||null;else if(s.ui_rev&&s.ui_rev!==window.__uiRev){location.reload();return;}
  $('health').innerHTML=Object.entries(s.health||{}).map(([k,v])=>chip(k,v)).join('')
    +chip('mute',!s.muted,s.muted?'MUTED':'off')
    +chip('event mode',true,s.event_mode?'ON':'off');
  $('btn-mute').style.display=s.muted?'none':'';
  $('btn-unmute').style.display=s.muted?'':'none';
  $('btn-ev-on').style.display=s.event_mode?'none':'';
  $('btn-ev-off').style.display=s.event_mode?'':'none';
  $('ev-hint').innerText=s.event_mode?'ON \u2014 spoken event questions (and paraphrases) get the scripted answers':'off \u2014 normal conversation; the /event buttons still work';
  const av=s.avatar_page||{},avAge=av.ts?(s.ts-av.ts):1e9,avOn=avAge<10;
  $('avstate').innerHTML=avOn?chip('page',true,av.stopped?'stopped':av.ready?'session live (credits ticking)':'parked — no credits')
    :chip('page',false,'not open');
  $('avstatus').innerText=avOn?(av.status||'')+(av.lag!=null?'  ·  lag '+(+av.lag).toFixed(2)+'s':''):
    'no /face-avatar page open (open it on the laptop: /face?key=…)';
  for(const m of ['robot','avatar','sync'])$('av-'+m).style.borderColor=(avOn&&av.mode===m)?'var(--gold)':'';
  $('av-stop').style.display=avOn&&av.stopped?'none':'';
  $('av-resume').style.display=avOn&&!av.stopped?'none':'';
  $('avlink').href='/face?key='+KEY;
  const m=s.meta,sp=s.spoken;
  if(m){$('turn').innerHTML=
    '<b>Q:</b> '+esc(m.question)+'<br><b>raw ASR:</b> <span class="mono raw">'+esc(m.raw_asr)+'</span>'+
    '<br><b>topic:</b> '+esc(m.topic)+' <b>theme:</b> '+esc(m.theme)+
    ' <b>conf:</b> '+esc(m.confidence)+
    '<br><b>token budget:</b> '+esc(m.token_budget)+(m.dynamic_tokens?' (dynamic)':' (fixed)')+
    (m.cost_usd!=null?'<br><b>cost:</b> '+(100*m.cost_usd).toFixed(2)+'&cent; this turn'+
      (m.cost_total_usd!=null?' &middot; $'+m.cost_total_usd.toFixed(2)+' since service start':'')+
      ' <span class="dim">(Anthropic only)</span>':'')+
    (m.fidelity_flags?(m.fidelity_flags.length
      ?'<br><b>fidelity:</b> <span class="raw">'+esc(m.fidelity_flags.join(', '))+'</span> &mdash; '+
        esc((m.fidelity_reasoning||'').slice(0,120))
      :'<br><b>fidelity:</b> <span class="fix">clean</span>'):'');
    $('docs').innerHTML=(m.docs&&m.docs.length)?m.docs.map(d=>
      '<div style="margin-bottom:8px'+(d.dropped_for_budget?';opacity:.45':'')+'">'+
      '<b>'+esc(d.title||d.doc_id)+'</b>'+
      (d.dropped_for_budget?' <span class="raw">dropped (token budget)</span>':'')+
      '<br><span class="mono dim">'+esc(d.doc_id)+(d.date?' &middot; '+esc(d.date):'')+
      (d.theme_label?' &middot; '+esc(d.theme_label):'')+'</span>'+
      (d.summary?'<br><span class="dim">'+esc(d.summary)+'</span>':'')+'</div>').join('')
      :(m.docs?'<span class="dim">none (canned / out-of-topic / meta turn)</span>'
        :'<span class="dim">no doc data (turn predates this feature)</span>');
    let lat='STT '+m.stt_s+'s'+bar(m.stt_s,10)+'Compose '+m.compose_s+'s'+bar(m.compose_s,20);
    if(sp&&sp.question===m.question)
      lat+=(sp.streamed?'First audio '+(sp.first_audio_s!=null?sp.first_audio_s:'?')+'s'+bar(sp.first_audio_s||0,15)
        :'TTS synth '+sp.synth_s+'s'+bar(sp.synth_s,10)+'Playback '+sp.play_s+'s'+bar(sp.play_s,40))
        +(sp.wpm?'Speech '+sp.wpm+' wpm <span class="dim">('+sp.words+' words / '+sp.audio_s+'s audio)</span>'+bar(sp.wpm,200):'')
        +(sp.interrupted?'<span class="raw">interrupted</span>':'');
    $('lat').innerHTML=lat;}
  const byQ={};
  (s.metas||[]).forEach(x=>{const k=x.question||'';byQ[k]=Object.assign(byQ[k]||{},x);});
  $('hist').innerHTML='<tr><th>time</th><th>question</th><th>theme</th><th>docs</th><th>tokens</th>'+
    '<th>cost</th><th>STT s</th><th>compose s</th><th>speech</th><th>wpm</th><th>flags</th></tr>'+
    Object.values(byQ).sort((a,b)=>(b.ts||0)-(a.ts||0)).slice(0,12).map(x=>{
      const sp2=x.streamed?('first audio '+(x.first_audio_s!=null?x.first_audio_s+'s':'?'))
        :(x.synth_s!=null?('synth '+x.synth_s+'s / play '+x.play_s+'s'):'');
      const fl=[x.streamed?'stream':'',x.dynamic_tokens?'dyn-tok':'',x.interrupted?'CUT':'',
        (x.fidelity_flags&&x.fidelity_flags.length)?('FID:'+x.fidelity_flags.join(',')):''].filter(Boolean).join(' ');
      const dks=(x.docs||[]).filter(d=>!d.dropped_for_budget).map(d=>d.doc_id).join(', ');
      return '<tr><td>'+(x.ts?new Date(1000*x.ts).toLocaleTimeString():'')+'</td><td>'+
        esc((x.question||'').slice(0,60))+'</td><td>'+esc(x.theme||'')+
        '</td><td title="'+esc(dks)+'">'+esc(dks.slice(0,48)+(dks.length>48?'\\u2026':''))+
        '</td><td>'+esc(x.token_budget||'')+
        '</td><td>'+(x.cost_usd!=null?(x.cost_usd?(100*x.cost_usd).toFixed(2)+'¢':'free'):'')+
        '</td><td>'+esc(x.stt_s!=null?x.stt_s:'')+'</td><td>'+esc(x.compose_s!=null?x.compose_s:'')+
        '</td><td>'+esc(sp2)+'</td><td title="'+(x.words?x.words+' words / '+x.audio_s+'s':'')+'">'+(x.wpm||'')+
        '</td><td'+(x.interrupted?' class="raw"':'')+'>'+esc(fl)+'</td></tr>';}).join('');
  $('conv').innerHTML='<tr><th>who</th><th>text</th></tr>'+
    (s.turns||[]).slice(-14).reverse().map(t=>'<tr><td>'+esc(t.role)+'</td><td>'+esc(t.text)+'</td></tr>').join('');
  $('ner').innerHTML='<tr><th>heard</th><th>&rarr; canonical</th><th>class</th><th>conf</th></tr>'+
    (s.corrections||[]).slice(-14).reverse().map(c=>'<tr><td class="raw">'+esc(c.surface)+
    '</td><td class="fix">'+esc(c.canonical)+'</td><td>'+esc(c.class)+'</td><td>'+esc(c.confidence)+'</td></tr>').join('');
  const evRows=(evs)=>'<tr><th>time</th><th>score</th></tr>'+
    (evs||[]).slice(-8).reverse().map(e=>'<tr><td>'+
    new Date(1000*(e.ts||0)).toLocaleTimeString()+'</td><td>'+esc((e.score||0).toFixed?e.score.toFixed(3):e.score)+'</td></tr>').join('');
  $('wake').innerHTML=evRows(s.wake_events);
  $('stopt').innerHTML=evRows(s.stop_events);
}catch(e){}}
// Wake meter + Stop meter (2026-08-26): same drawing, separate feeds —
// /api/wake scores while idle-listening, /api/stop scores while an answer
// plays (barge-in listener). Exactly one of them is live at any moment.
let spark=[],stopspark=[];
function drawMeter(w,ids,buf,color,liveLabel,idleLabel,defThr){
  const sc=w.score!=null?w.score:0,th=w.threshold!=null?w.threshold:defThr;
  $(ids.now).innerText=(w.live?liveLabel+' ':idleLabel+' ')+sc.toFixed(3)+' / thr '+th;
  $(ids.bar).style.width=Math.min(100,100*sc/Math.max(th*2,0.01))+'%';
  $(ids.bar).style.background=sc>=th?'var(--bad)':color;
  buf.push(w.live?sc:0);if(buf.length>200)buf.shift();
  const c=$(ids.spark),g=c.getContext('2d');
  if(c.width!==c.clientWidth){c.width=c.clientWidth;c.height=64;}
  g.clearRect(0,0,c.width,c.height);
  const ymax=Math.max(th*2,0.1);
  g.strokeStyle='#f8514966';g.beginPath();
  g.moveTo(0,64-64*th/ymax);g.lineTo(c.width,64-64*th/ymax);g.stroke();
  g.strokeStyle=color;g.beginPath();
  buf.forEach((v,i)=>{const x=i*c.width/200,y=64-Math.min(64,64*v/ymax);
    i?g.lineTo(x,y):g.moveTo(x,y);});
  g.stroke();
}
async function wakeTick(){try{
  const [w,st]=await Promise.all([fetch('/api/wake').then(r=>r.json()),
                                  fetch('/api/stop').then(r=>r.json())]);
  drawMeter(w,{now:'wakenow',bar:'wakebar',spark:'spark'},spark,'#c9a227',
            'live',st.live?'answering':'OFFLINE',0.07);
  drawMeter(st,{now:'stopnow',bar:'stopbar',spark:'stopspark'},stopspark,'#58a6ff',
            'armed',w.live?'idle':'OFFLINE',0.02);
}catch(e){}}
async function sysTick(){try{
  const st=await(await fetch('/api/status')).json();
  $('services').innerHTML=Object.entries(st.services||{}).map(
    ([k,v])=>chip(k,v.active==='active')).join('')+chip('daemon',!!st.reachy_daemon);
  const sy=st.system||{},wf=st.wifi||{};
  $('sys').innerHTML=
    '<b>CPU</b> '+(sy.temp_c!=null?sy.temp_c+'&deg;C':'?')+' &nbsp;<b>load</b> '+
    ((sy.load||[])[0]!=null?sy.load[0].toFixed(2):'?')+
    ' &nbsp;<b>mem</b> '+(sy.mem_used_pct!=null?sy.mem_used_pct+'%':'?')+
    ' &nbsp;<b>disk</b> '+(sy.disk_used_pct!=null?sy.disk_used_pct+'%':'?')+
    ' &nbsp;<b>throttle</b> '+esc(sy.throttled||'?')+
    '<br><b>WiFi</b> '+esc(wf.essid||'none')+' '+esc(wf.signal_dbm||'')+'dBm &nbsp;<b>IP</b> '+esc(wf.ip||'?')+
    '<br><b>Audio</b> '+esc((st.audio||{}).route||'?');
  try{netFromStatus(st)}catch(e){}
  const env=((st.wake||{}).env)||{};
  $('flags').innerHTML=[['stream','CJ_STREAM_SPEECH'],['dyn-filler','CJ_DYNAMIC_FILLER'],
    ['dyn-tokens','CJ_DYNAMIC_TOKENS_ENABLED'],['postproc','CJ_POSTPROC_ENABLED'],
    ['stop-word','CJ_STOP_WORD_ENABLED']].map(([n,k])=>chip(n,env[k]==='1')).join('');
}catch(e){}}
function camTick(){const p=new Image();p.onload=()=>{$('cam').src=p.src};
  p.src='/api/camera.jpg?t='+Date.now();}
setInterval(poll,1000);poll();
setInterval(wakeTick,300);wakeTick();
setInterval(sysTick,5000);sysTick();
setInterval(camTick,200);camTick();loadOv();loadLogs();
// ── Connectivity (WiFi / Bluetooth) — same endpoints as the ops page ──
let _nets=[],_bts=[],_watchdog=false;
function netFromStatus(st){const wf=st.wifi||{};
  $('wifinow').innerHTML=wf.essid?chip(esc(wf.essid),true,esc(wf.signal_dbm||'?')+' dBm · '+esc(wf.ip||'?')):chip('no wifi',false,'');
  _watchdog=((st.services||{})['speaker-watchdog']||{}).active==='active';
  const sp=(st.audio||{}).speakers||{},route=(st.audio||{}).route||'?';
  $('btnow').innerHTML=chip('route',true,esc(route))+Object.entries(sp).map(([n,c])=>chip(n,c,c?'connected':'off')).join('');}
function netRow(left,right,onclick){return '<div style="display:flex;justify-content:space-between;gap:10px;padding:8px 6px;border-bottom:1px solid var(--line);cursor:pointer" onclick="'+onclick+'"><span>'+left+'</span><span class="dim">'+right+'</span></div>'}
async function wifiScan(){$('wifi-list').textContent='scanning…';
  try{const w=await(await fetch('/api/wifi?rescan=1')).json();_nets=w.networks||[];
    if(w.hotspot&&!_nets.length){$('wifi-list').textContent='setup hotspot active — scanning unavailable; type the network below';return}
    if(!_nets.length){$('wifi-list').textContent='no networks found';return}
    $('wifi-list').innerHTML=_nets.map((n,i)=>{const bars=n.signal>66?'▂▄▆':n.signal>33?'▂▄':'▂';
      const tag=n.in_use?' — connected':(n.saved?' (saved)':'');const lock=n.security==='open'?'':' 🔒';
      return netRow((n.in_use?'✅ ':'')+esc(n.ssid)+lock+'<span class="dim">'+tag+'</span>',bars+' '+n.signal+'%','wifiJoinIdx('+i+')')}).join('');
  }catch(e){$('wifi-list').textContent='scan failed: '+e.message}}
async function wifiSend(ssid,password){
  if(!confirm('Switch the robot to "'+ssid+'"? This page will drop until your phone is on the same network.'))return;
  $('netmsg').textContent='switching to '+ssid+'…';
  try{const r=await(await fetch('/api/wifi/connect',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ssid,password})})).json();
    $('netmsg').textContent=r.ok?(r.output||('now on '+ssid)):'FAILED — '+(r.output||'');
  }catch(e){$('netmsg').textContent='dashboard dropped — rejoin '+ssid+' on your phone and reload'}}
function wifiJoinIdx(i){const n=_nets[i];if(!n)return;let pw=null;
  if(!(n.saved||n.security==='open')){pw=prompt('Password for "'+n.ssid+'" (leave empty if open):');if(pw===null)return}
  wifiSend(n.ssid,pw)}
function wifiManual(){const ssid=$('wm-ssid').value.trim(),pw=$('wm-pw').value;
  if(!ssid){$('netmsg').textContent='enter a network name';return}wifiSend(ssid,pw||null)}
async function btScan(rescan){$('bt-list').textContent=rescan?'scanning (~10 s)…':'loading…';
  try{const b=await(await fetch('/api/bt'+(rescan?'?scan=1':''))).json();_bts=b.devices||[];
    if(!_bts.length){$('bt-list').textContent='no devices known — tap Scan';return}
    $('bt-list').innerHTML=_bts.map((d,i)=>{const state=d.connected?'<span style="color:var(--ok)">connected</span>':d.paired?'paired':'not paired';
      return netRow((d.connected?'✅ ':'')+(d.audio?'🔊 ':'')+esc(d.name),state,'btTapIdx('+i+')')}).join('');
  }catch(e){$('bt-list').textContent='bluetooth list failed: '+e.message}}
async function btTapIdx(i){const d=_bts[i];if(!d)return;
  const action=d.connected?'disconnect':d.paired?'connect':'pair';
  const warn=(action==='disconnect'&&_watchdog)?' ⚠ The watchdog is running — Sony reconnects within 15 s.':'';
  if(!confirm(action.charAt(0).toUpperCase()+action.slice(1)+' "'+d.name+'"?'+warn))return;
  $('btmsg').textContent=action+'ing '+d.name+'…';
  try{const r=await(await fetch('/api/bt/action',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({mac:d.mac,action})})).json();
    $('btmsg').textContent=d.name+': '+(r.ok?action+' ok ✓':'FAILED — '+(r.output||''));
  }catch(e){$('btmsg').textContent=action+' failed: '+e.message}
  setTimeout(()=>btScan(false),1500)}
btScan(false);
</script></body></html>"""

GATE_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>CJAP</title>
<style>body{background:#0d1117;color:#e6edf3;font-family:Arial;display:flex;align-items:center;
justify-content:center;height:100vh}form{text-align:center}input{padding:10px;border-radius:8px;
border:1px solid #30363d;background:#161b22;color:#e6edf3;font-size:16px}
button{padding:10px 18px;margin-left:8px;border-radius:8px;border:1px solid #c9a227;
background:#21262d;color:#e6edf3;font-size:16px}</style></head><body>
<form onsubmit="location='/maintain?key='+document.getElementById('k').value;return false">
<p style="margin-bottom:10px">Maintenance access key</p>
<input id="k" type="password" autofocus><button>Enter</button></form></body></html>"""


EVENT_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CJAP Event Questions</title><style>
body{background:#0d1117;color:#e6edf3;font-family:Arial;margin:0;padding:16px;
 max-width:560px;margin-left:auto;margin-right:auto}
h1{font-size:18px;color:#c9a227;margin:4px 0 2px}
p.sub{color:#8b949e;font-size:13px;margin:0 0 14px}
button.q{display:block;width:100%;text-align:left;margin:10px 0;padding:15px 16px;
 border-radius:12px;border:1px solid #30363d;background:#161b22;color:#e6edf3;
 font-size:16px;line-height:1.35;cursor:pointer}
button.q:active{background:#21262d;border-color:#c9a227}
button.q:disabled{opacity:.45}
button.q b{color:#c9a227;margin-right:6px}
#status{margin-top:14px;padding:10px 12px;border-radius:10px;background:#161b22;
 border:1px solid #30363d;font-size:14px;color:#8b949e;min-height:20px}
.ok{color:#3fb950}.warn{color:#d29922}
#mode{display:flex;align-items:center;justify-content:space-between;gap:12px;
 margin:12px 0;padding:12px 14px;border-radius:12px;background:#161b22;
 border:1px solid #30363d}
#modeTxt{font-size:14px;color:#8b949e;line-height:1.35}
#modeTxt b{display:block;font-size:15px;color:#e6edf3}
#modeBtn{flex-shrink:0;width:64px;height:34px;border-radius:17px;border:1px solid
 #30363d;background:#21262d;position:relative;cursor:pointer;transition:background .15s}
#modeBtn span{position:absolute;top:3px;left:4px;width:26px;height:26px;
 border-radius:13px;background:#8b949e;transition:left .15s,background .15s}
#modeBtn.on{background:#1f3524;border-color:#3fb950}
#modeBtn.on span{left:32px;background:#3fb950}
</style></head><body>
<h1>CJAP &mdash; Event Questions</h1>
<p class="sub">Backup buttons: if the robot mishears the emcee, tap the question
and it speaks the exact scripted answer.</p>
<div id="mode"><div id="modeTxt"><b>Event mode: &hellip;</b>&hellip;</div>
<div id="modeBtn" onclick="toggleMode()"><span></span></div></div>
%BUTTONS%
<div id="status">&hellip;</div>
<script>
const KEY=new URLSearchParams(location.search).get('key')||'';
const st=document.getElementById('status');
let queuedAt=0, evMode=null;
function paintMode(on){
  evMode=on;
  document.getElementById('modeBtn').className=on?'on':'';
  document.getElementById('modeTxt').innerHTML=on
    ?'<b>Event mode: ON</b>Spoken event questions are answered with the script.'
    :'<b>Event mode: OFF</b>Normal conversation \\u2014 the buttons below still work.';
}
async function toggleMode(){
  const action=evMode?'event-off':'event-on';
  try{
    const r=await fetch('/api/ctl',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({key:KEY,action})});
    const j=await r.json();
    if(j.ok) paintMode(!evMode);
    else st.innerHTML='<span class="warn">Toggle failed:</span> '+String(j.output||'error').replace(/</g,'&lt;');
  }catch(e){st.innerHTML='<span class="warn">Network error &mdash; try again.</span>';}
}
async function ask(id,btn){
  btn.disabled=true; setTimeout(()=>btn.disabled=false,4000);
  try{
    const r=await fetch('/api/ask',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({key:KEY,id})});
    const j=await r.json();
    if(j.ok){queuedAt=Date.now();
      st.innerHTML='<span class="ok">Queued.</span> The robot answers as soon as it is idle (a tap expires after 30s).';}
    else st.innerHTML='<span class="warn">Failed:</span> '+String(j.output||'error').replace(/</g,'&lt;');
  }catch(e){st.innerHTML='<span class="warn">Network error &mdash; try again.</span>';}
}
async function poll(){
  try{
    const s=await(await fetch('/api/state')).json();
    if(s.event_mode!==evMode) paintMode(!!s.event_mode);
    const sp=s.speaking||{};
    if(sp.current && !sp.done){
      st.innerHTML='<b class="ok">Speaking:</b> '+String(sp.current).replace(/</g,'&lt;');
      queuedAt=0;
    }else if(!(queuedAt && Date.now()-queuedAt<30000)){
      st.textContent='Robot idle \\u2014 listening for the wake word.';
    }
  }catch(e){}
}
setInterval(poll,1000);poll();
</script></body></html>"""


FACE_AVATAR_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CJAP LiveAvatar</title><link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,500;0,600;1,500&family=EB+Garamond:ital,wght@0,400;0,500;1,400&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/livekit-client@2/dist/livekit-client.umd.min.js"></script>
<style>
""" + EXHIBIT_CSS + """
/* avatar page: the HeyGen portrait (9:10) where the camera sits on /audience —
   frameless (2026-08-25, user): no gilt moulding, mat rings, or glow */
#cam,#cam.live{width:min(36vw,calc(58vh * 9 / 10));aspect-ratio:9/10;top:4vh;
  border:0;border-image:none;box-shadow:none;border-radius:.8vh}
#cam video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;background:#000}
/* picture-frame idle (2026-08-25, user): a frozen frame of the avatar sits
   over the live video whenever it is not speaking — and stays up after the
   sandbox session expires, so the portrait never goes black */
#cam canvas#still{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:none;z-index:2}
#cam .idle{z-index:1}
/* no on-page operator strip (2026-08-25, user): Stop/Resume, voice mode and
   the status line live on /maintain ("LiveAvatar page" card) and reach this
   page through /api/state (avatar_cmd) — status goes back via /api/avatar-status */
</style></head><body>
<div id="cam"><video id="vid" autoplay playsinline muted></video><canvas id="still"></canvas><audio id="aud" autoplay></audio>
  <div class="idle" id="camidle"><b>CJAP</b>
    <span>Chief Justice Artemio V. Panganiban</span></div>
</div>
""" + EXHIBIT_PLAQUES + """<script>
""" + EXHIBIT_JS + """const $ = id => document.getElementById(id);
const KEY = new URLSearchParams(location.search).get("key") || localStorage.getItem("cjkey") || "";
if (KEY) try { localStorage.setItem("cjkey", KEY); } catch (e) {}
let room = null, ws = null, ready = false, sessTok = null, startP = null;
let avatarMuted = true, lastStart = 0, keepTimer = null;
let pendingLagT0 = null, lagEma = null, skew = 0;
$("aud").muted = true;
const sleep = ms => new Promise(r => setTimeout(r, ms));

// status line → /maintain (posted on change, plus a 3s heartbeat so the
// card can tell "page open" from "page gone")
let stText = "starting", stSentAt = 0;
function report(){
  stSentAt = Date.now();
  post("/api/avatar-status", {status: stText, mode: voiceMode, ready: ready,
    stopped: stopped, parked: !ready && !stopped, frozen: frozen, lag: lagEma}).catch(() => {});
}
function st(msg){ stText = msg; if (Date.now() - stSentAt > 700) report(); }
setInterval(report, 3000);

async function post(path, doc){
  doc.key = KEY;
  const r = await fetch(path, {method:"POST",
    headers:{"Content-Type":"application/json"}, body:JSON.stringify(doc)});
  return r.json();
}

// ---- session ------------------------------------------------------------
function start(){
  if (ready || stopped) return Promise.resolve();
  if (startP) return startP;                // one start in flight at a time
  if (Date.now() - lastStart < 8000) return Promise.resolve();
  lastStart = Date.now();
  startP = _start().catch(e => st("start failed: " + e.message))
                   .finally(() => { startP = null; });
  return startP;
}
async function _start(){
  st("creating session…");
  const out = await post("/api/avatar-session", {});
  if (!out.ok){
    st("session failed: " + JSON.stringify(out.output) +
       (String(out.output) === "bad key" ? " — open this page as /face?key=cjap (the dashboard key)" : ""));
    return; }
  const s = out.output;
  sessTok = s.session_token;
  if (stopped){ await park(); return; }          // Stop landed during session creation
  st("connecting to room…");
  try{
    room = new LivekitClient.Room();
    room.on(LivekitClient.RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === "video"){ track.attach($("vid"));
        $("camidle").style.display = "none"; }
      if (track.kind === "audio"){ track.attach($("aud"));
        $("aud").muted = avatarMuted; }
    });
    await room.connect(s.livekit_url, s.livekit_client_token);
  }catch(e){ st("LiveKit connect failed: " + e.message); return; }
  if (stopped){ await park(); return; }
  st("opening control socket…");
  const sock = new WebSocket(s.ws_url);
  ws = sock;
  const connected = new Promise(res => {
    sock.addEventListener("message", ev => {
      let m = {}; try{ m = JSON.parse(ev.data); }catch(e){ return; }
      if (m.type === "session.state_updated" && m.state === "connected") res(true);
    });
    sock.addEventListener("close", () => res(false));
    setTimeout(() => res(false), 15000);
  });
  sock.onmessage = ev => {
    let m = {};
    try{ m = JSON.parse(ev.data); }catch(e){ return; }
    if (m.type === "session.state_updated"){
      st("session " + m.state +
         (m.state === "connected" ? " — portrait still until asked" : ""));
      const was = ready;
      ready = (m.state === "connected");
      if (ready && !was) setVoice(voiceMode);   // re-assert (default: robot voice, avatar mouths along)
    }
    if (m.type === "agent.speak_started"){
      const name = sentOrder.shift();          // attribute to the oldest queued clip
      if (name) avatarStart[name] = Date.now()/1000;
      if (pendingLagT0){
        // closed-loop sync: how long after the feed publish did the avatar
        // actually start speaking? The robot delays its audio by this much.
        const lag = Date.now()/1000 - pendingLagT0;
        pendingLagT0 = null;
        if (lag > 0 && lag < 5){
          lagEma = lagEma === null ? lag : lagEma*.6 + lag*.4;
          post("/api/avatar-lag", {lag: +lagEma.toFixed(2)});
          st("speaking — avatar start lag " + lagEma.toFixed(2) + "s (auto-sync)");
        }
      }
    }
  };
  sock.onclose = () => {
    if (ws !== sock) return;
    ready = false; stopKeep(); sentOrder.length = 0;   // nothing queued survives the session
    if (parking){ parking = false; st("parked — portrait held, no credits while idle"); return; }
    const busy = speakingNow || turnActive();
    st("session ended (sandbox caps at ~1 min)" +
       (busy ? " — reconnecting…" : " — portrait held, restarts on next question"));
    if (busy) setTimeout(start, 300);   // pick the answer back up
  };
  sock.onerror = () => { ready = false; };
  keepTimer = setInterval(() => {
    if (ws && ws.readyState === 1)
      ws.send(JSON.stringify({type:"session.keep_alive",
                              event_id:String(Date.now())}));
  }, 25000);
  await connected;
  if (stopped){ await park(); await post("/api/ctl", {action: "avatar-voice-off"}); }
}
function stopKeep(){ if (keepTimer){ clearInterval(keepTimer);
  keepTimer = null; } }

// park = end the HeyGen session but stay armed: the still portrait covers
// the gap and the next question pre-starts a fresh session (no idle credits)
let parking = false;
async function park(){
  if (!ready && !sessTok) return;
  parking = true; stopKeep(); ready = false;
  try{ if (ws) ws.close(); }catch(e){}
  try{ if (room) room.disconnect(); }catch(e){}
  const tok = sessTok; sessTok = null; sent.clear(); sentOrder.length = 0;
  if (tok) await post("/api/avatar-stop", {session_token: tok});
  setTimeout(() => { parking = false; }, 5000);   // onclose normally clears it first
}
async function stop(){
  stopped = true;                                    // blocks every auto-start
  await park();
  await post("/api/ctl", {action: "avatar-voice-off"});   // robot: no holds
  st("stopped — portrait held; press Resume to mouth along again");
}
let stopped = false;
function resume(){ if (!stopped) return; stopped = false; heartbeat(); start(); }
// commands from /maintain arrive in /api/state.avatar_cmd; anything already
// queued before this page loaded is ignored (lastCmdTs primes on first poll)
let lastCmdTs = null;
function applyCmd(c){
  if (!c || !c.ts) return;
  if (lastCmdTs === null){ lastCmdTs = c.ts; return; }
  if (c.ts <= lastCmdTs) return;
  lastCmdTs = c.ts;
  if (c.cmd === "stop") stop();
  else if (c.cmd === "resume") resume();
  else if (c.cmd === "voice" && MODES.includes(c.mode)) setVoice(c.mode);
}
// Session lifecycle (2026-08-25, user: "automatically start and stop so no
// credits are lost while idle"):
//  • page load: a cached portrait (localStorage) is shown at once and NO
//    session is opened; without one, a session runs just long enough to
//    capture the portrait, then parks
//  • a question being transcribed pre-starts the session (~8-15s before the
//    first sentence), answers/asides start it if it is not up yet
//  • IDLE_PARK_MS after the last activity the session is parked
const IDLE_PARK_MS = 45000;
let lastActivity = Date.now(), turnUntil = 0, lastTurnKey = "";
function touch(){ lastActivity = Date.now(); }
function turnActive(){ return Date.now() < turnUntil; }
setTimeout(() => { if (!restoreStill()) start(); }, 0);   // deferred past the lets below
setInterval(() => {
  if (!ready) return;
  if (stopped){ park(); return; }                  // a session that outlived Stop
  if (speakingNow || turnActive() || sentOrder.length || Date.now() < busyUntil) return;
  if (Date.now() - lastActivity > IDLE_PARK_MS) park();
}, 1000);

// ---- picture-frame idle ---------------------------------------------------
// The live video shows only while the avatar is mouthing something; the rest
// of the time a frozen frame of it is displayed. The frame is re-taken a few
// times right after freezing (the first decoded frames can be transitional)
// and then held — through sandbox session expiry — until the next answer.
let wantLive = false, liveUntil = 0, freezeAt = 0, frozen = false,
    snaps = 0, lastSnap = 0, busyUntil = 0;   // busyUntil: avatar still mouthing a fed clip
function restoreStill(){
  let url = null;
  try{ url = localStorage.getItem("cjap_still"); }catch(e){}
  if (!url) return false;
  const img = new Image();
  img.onload = () => { const c = $("still"); c.width = img.width; c.height = img.height;
    c.getContext("2d").drawImage(img, 0, 0); c.style.display = "block"; frozen = true;
    $("camidle").style.display = "none"; st("portrait — starts on the next question"); };
  img.onerror = () => { frozen = false; start(); };   // corrupt cache: capture a fresh one
  img.src = url;
  return true;
}
function videoLive(){
  const v = $("vid");
  return ready && v.videoWidth > 0 && v.readyState >= 2 && !v.paused;
}
function snap(){
  const v = $("vid"), c = $("still");
  if (!videoLive()) return false;
  c.width = v.videoWidth; c.height = v.videoHeight;
  try{ c.getContext("2d").drawImage(v, 0, 0); }catch(e){ return false; }
  $("camidle").style.display = "none";
  return true;
}
function frameTick(){
  const live = wantLive || Date.now() < liveUntil || Date.now() < busyUntil;
  if (live){
    if (frozen && videoLive()){ $("still").style.display = "none"; frozen = false; }
  } else if (Date.now() >= freezeAt){
    if (!frozen){
      if (snap()){ $("still").style.display = "block"; frozen = true; snaps = 1; lastSnap = Date.now();
        if (!speakingNow) st(ready ? "portrait — still until asked" : "portrait — starts on the next question"); }
    } else if (snaps < 4 && Date.now() - lastSnap > 1000 && snap()){
      snaps++; lastSnap = Date.now();
      if (snaps === 4) try{ localStorage.setItem("cjap_still",
        $("still").toDataURL("image/jpeg", 0.85)); }catch(e){}
    }
  }
  setTimeout(frameTick, 150);
}
setTimeout(frameTick, 150);   // deferred: the poll section below declares speakingNow

// ---- voice mode -----------------------------------------------------------
// robot = avatar muted here but its mouth still tracks the robot ("lips");
// avatar = avatar is the only voice; sync = both, robot delayed to coincide
const MODES = ["sync", "avatar", "robot"];
let voiceMode = "robot";
function modeAction(){
  return voiceMode === "avatar" ? "avatar-voice-on"
       : voiceMode === "sync"   ? "avatar-voice-sync" : "avatar-voice-lips";
}
async function setVoice(mode){
  voiceMode = mode;
  avatarMuted = (mode === "robot");
  $("aud").muted = avatarMuted;
  await post("/api/ctl", {action: modeAction()});
  report();
}
// the robot only holds its head start while this page is alive: re-assert
// the mode every 5s (flag older than 15s = page gone)
function heartbeat(){ if (!stopped) post("/api/ctl", {action: modeAction()}); }
setInterval(heartbeat, 5000); heartbeat();
addEventListener("beforeunload", () => {
  navigator.sendBeacon("/api/ctl",
    new Blob([JSON.stringify({key:KEY, action:"avatar-voice-off"})],
             {type:"application/json"}));
});

// ---- feed the avatar our ElevenLabs sentence audio -----------------------
function b64(u8){
  let s = "";
  for (let i = 0; i < u8.length; i += 32768)
    s += String.fromCharCode.apply(null, u8.subarray(i, i + 32768));
  return btoa(s);
}
function wavPcm(buf){          // RIFF walk → the data chunk's bytes
  const dv = new DataView(buf), u8 = new Uint8Array(buf);
  let pos = 12;
  while (pos + 8 <= u8.length){
    const id = String.fromCharCode(u8[pos], u8[pos+1], u8[pos+2], u8[pos+3]);
    const size = dv.getUint32(pos + 4, true);
    if (id === "data") return u8.subarray(pos + 8, pos + 8 + size);
    pos += 8 + size + (size % 2);
  }
  return null;
}
// Everything the robot voices goes through ONE ordered queue: answer
// sentences (current + the pre-fed next one), plus ack/filler asides. The
// avatar plays them back-to-back in exactly the robot's order.
const sent = new Set(), sentOrder = [], avatarStart = {};
let chain = Promise.resolve();
function enqueue(name){
  if (!name || sent.has(name)) return;
  sent.add(name);
  chain = chain.then(() => sendWav(name)).catch(() => {});
}
async function sendWav(name){
  if (stopped) return;
  if (!ready) await start();
  for (let w = 0; w < 40 && !ready && !stopped; w++) await sleep(250);
  if (!ready){ st("session not ready — clip skipped"); sent.delete(name); return; }
  try{
    const r = await fetch("/api/sentence.wav?name=" + name);
    if (!r.ok){ st("clip gone: " + name); return; }
    const pcm = wavPcm(await r.arrayBuffer());
    if (!pcm){ st("bad wav"); return; }
    for (let i = 0; i < pcm.length; i += 48000)     // 1s @ 24kHz 16-bit
      ws.send(JSON.stringify({type:"agent.speak",
                              audio: b64(pcm.subarray(i, i + 48000))}));
    ws.send(JSON.stringify({type:"agent.speak_end",
                            event_id:String(Date.now())}));
    sentOrder.push(name);
    // the avatar mouths this clip from ~lag after now for its full length —
    // keep the live video up (and the session unparked) until then
    const durMs = pcm.length / 48 + (lagEma || 1.5) * 1000 + 800;
    busyUntil = Math.max(busyUntil, Date.now() + durMs); touch();
  }catch(e){ st("audio feed failed: " + e.message); }
}

// ---- state poll ----------------------------------------------------------
let curKey = "", speakingNow = false, lastAsideTs = 0, driftShown = "", uiRev = null;
async function poll(){
  try{
    const stt = await (await fetch("/api/state")).json();
    if (stt.ts) skew = Date.now()/1000 - stt.ts;   // Pi clock → browser clock
    if (uiRev === null) uiRev = stt.ui_rev || null;
    else if (stt.ui_rev && stt.ui_rev !== uiRev){ st("new version — reloading"); location.reload(); return; }
    applyCmd(stt.avatar_cmd);                        // Stop/Resume/voice from /maintain
    // a question is being transcribed → warm the session before the answer
    const stg = stt.stage || {}, tr = (stg.steps || {}).transcribe || {};
    const heard = tr.state === "done" || (tr.state === "active" && /transcrib/i.test(tr.detail || ""));
    if (heard && stg.turn_ts && (Date.now()/1000 - (stg.turn_ts + skew)) < 60){
      const tk = stg.turn_ts + "|" + tr.state;
      if (tk !== lastTurnKey){ lastTurnKey = tk; touch(); turnUntil = Date.now() + 60000;
        if (!ready) st("question heard — starting the avatar session…");
        start(); }
    }
    renderExhibit(stt);                              // same plaques as /audience
    const sp = stt.speaking || {}, as = stt.aside || {};
    // ack / filler clips ("Hmm.", "let me think…") — mouth them, no caption
    if (as.wav && as.ts && as.ts !== lastAsideTs && (Date.now()/1000 - (as.ts + skew)) < 6){
      lastAsideTs = as.ts; enqueue(as.wav); touch();
      liveUntil = Date.now() + 6000;          // mouth the aside, then still again
    }
    if (sp.current && !sp.done){
      const key = sp.wav || (sp.ts + "|" + sp.current);
      if (key !== curKey){
        const wasIdle = !speakingNow;
        curKey = key; speakingNow = true; wantLive = true; touch();
        if (sp.wav){
          // measure start lag only on an answer's FIRST sentence with the
          // session already live (a cold session start isn't speak lag)
          if (wasIdle && ready && !sent.has(sp.wav))
            pendingLagT0 = sp.ts + skew;
          enqueue(sp.wav);
        }
      }
      if (sp.next && sp.next.wav) enqueue(sp.next.wav);   // queue ahead
      // drift readout: avatar start vs the robot's real audio start
      if (sp.wav && sp.play_ts && avatarStart[sp.wav] && driftShown !== sp.wav){
        driftShown = sp.wav;
        const d = avatarStart[sp.wav] - (sp.play_ts + skew);
        st("speaking — avatar " + (d >= 0 ? "+" : "") + d.toFixed(2) + "s vs robot" +
           (lagEma !== null ? " (lag " + lagEma.toFixed(2) + "s)" : ""));
      }
    } else if (sp.done){
      if (speakingNow){
        if (sp.interrupted && ws && ws.readyState === 1)
          ws.send(JSON.stringify({type:"agent.interrupt"}));
        speakingNow = false; curKey = ""; wantLive = false; touch();
        turnUntil = 0;                        // answer done: the turn is over
        freezeAt = Date.now() + Math.round(((lagEma || 0.8) + 0.7) * 1000);
        if (sp.interrupted) busyUntil = 0;    // cut short: freeze with the robot
        sentOrder.length = 0;
        if (sent.size > 64) sent.clear();
      }
    }
  }catch(e){}
  setTimeout(poll, 120);
}
poll();
</script></body></html>"""


# ---------------------------------------------------------------------------
# request dispatch (called from dashboard.Handler)
# ---------------------------------------------------------------------------

def handle_get(h, path, params):
    """Returns True if this module handled the request."""
    if path == "/audience":
        h._send(200, AUDIENCE_PAGE, "text/html; charset=utf-8")
    elif path == "/notes":   # plain-text project notes, downloadable from any device
        try:
            h._send(200, open(os.path.join(HOME, "PROJECT_NOTES.txt"),
                              encoding="utf-8").read(),
                    "text/plain; charset=utf-8")
        except OSError:
            h._send(404, "notes file not found", "text/plain; charset=utf-8")
    elif path == "/canned-qa":  # compiled canned Q&A (scripts/export_canned_qa.py)
        try:
            h._send(200, open(os.path.join(HOME, "canned_qa.txt"),
                              encoding="utf-8").read(),
                    "text/plain; charset=utf-8")
        except OSError:
            h._send(404, "canned_qa.txt not found — run "
                    "scripts/export_canned_qa.py", "text/plain; charset=utf-8")
    elif path == "/backup":  # newest checkpoint tarball from ~/backups, streamed
        import glob as _glob
        files = sorted(_glob.glob(os.path.join(HOME, "backups", "checkpoint-*.tar.gz")))
        if not files:
            h._send(404, "no checkpoint found", "text/plain; charset=utf-8")
        else:
            fp = files[-1]
            try:
                size = os.path.getsize(fp)
                h.send_response(200)
                h.send_header("Content-Type", "application/gzip")
                h.send_header("Content-Length", str(size))
                h.send_header("Content-Disposition",
                              f'attachment; filename="{os.path.basename(fp)}"')
                h.end_headers()
                with open(fp, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        h.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
    elif path == "/maintain":
        if _authed(params):
            h._send(200, MAINTAIN_PAGE, "text/html; charset=utf-8")
        else:
            h._send(200, GATE_PAGE, "text/html; charset=utf-8")
    elif path == "/event":
        if _authed(params):
            h._send(200, event_page(), "text/html; charset=utf-8")
        else:
            h._send(200, GATE_PAGE.replace("/maintain?key=", "/event?key="),
                    "text/html; charset=utf-8")
    elif path == "/phone":   # easy-to-type alias for the event page
        h.send_response(302)
        h.send_header("Location", "/event?key=" + DASH_KEY)
        h.end_headers()
    elif path == "/api/tuning":
        if not _authed(params):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            h._send(200, json.dumps({"ok": True, "tuning": tuning_get()}))
    elif path == "/api/usage":
        h._send(200, json.dumps(usage()))
    elif path == "/api/providers":
        h._send(200, json.dumps(provider_status()))
    elif path == "/api/errors":
        h._send(200, json.dumps({"ts": time.time(), "rows": recent_errors()}))
    elif path == "/api/state":
        h._send(200, json.dumps(state()))
    elif path == "/api/camera.jpg":
        frame = cam_frame()
        if frame:
            h._send(200, frame, "image/jpeg")
        else:
            h._send(503, json.dumps({"error": "camera unavailable"}))
    elif path == "/face":   # retired drawn-face page → the avatar is the face
        # keep the query string (2026-08-25 fix: "/face?key=cjap" used to land on
        # /face-avatar WITHOUT the key -> "session failed: bad key")
        qs = h.path.split("?", 1)[1] if "?" in h.path else ""
        h.send_response(302)
        h.send_header("Location", "/face-avatar" + ("?" + qs if qs else ""))
        h.end_headers()
    elif path == "/face-avatar":
        h._send(200, FACE_AVATAR_PAGE, "text/html; charset=utf-8")
    elif path == "/api/sentence.wav":
        name = params.get("name", "")
        if not re.fullmatch(r"cj_sent_[0-9]+\.wav", name):
            h._send(400, json.dumps({"error": "bad name"}))
        else:
            try:
                h._send(200, _sentence_pcm24k("/dev/shm/" + name), "audio/wav")
            except OSError:
                h._send(404, json.dumps({"error": "gone"}))
    elif path == "/api/camera.mjpg":
        _serve_mjpeg(h)
    elif path == "/api/entities":
        if not _authed(params):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            ok, content = entities_get()
            h._send(200, json.dumps({"ok": ok, "content": content}))
    else:
        return False
    return True


def handle_post(h, path, body):
    if path == "/api/tuning":
        if not _authed({}, body):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            ok, out = tuning_set(body)
            print(f"[ctl] {h.client_address[0]} tuning -> {out}", flush=True)
            h._send(200, json.dumps({"ok": ok, "output": out}))
    elif path == "/api/ctl":
        if not _authed({}, body):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            ok, out = control(body.get("action", ""))
            act = body.get("action", "")
            if not act.startswith("avatar-voice-"):   # page heartbeats, not operator actions
                print(f"[ctl] {h.client_address[0]} {act} -> {out}", flush=True)
            h._send(200, json.dumps({"ok": ok, "output": out}))
    elif path == "/api/entities":
        if not _authed({}, body):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            ok, out = entities_put(body.get("content", ""))
            h._send(200, json.dumps({"ok": ok, "output": out}))
    elif path == "/api/avatar-session":
        if not _authed({}, body):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            ok, out = avatar_session()
            h._send(200, json.dumps({"ok": ok, "output": out}))
    elif path == "/api/avatar-stop":
        if not _authed({}, body):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            ok, out = avatar_stop(body.get("session_token"))
            h._send(200, json.dumps({"ok": ok, "output": out}))
    elif path == "/api/ask":
        # /event question button: queue one scripted canned answer
        if not _authed({}, body):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            ok, out = ask_event(body.get("id", ""))
            print(f"[ask] {h.client_address[0]} {body.get('id', '')} -> {out}", flush=True)
            h._send(200, json.dumps({"ok": ok, "output": out}))
    elif path == "/api/avatar-status":
        if not _authed({}, body):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            ok, out = avatar_status_put(body)
            h._send(200, json.dumps({"ok": ok, "output": out}))
    elif path == "/api/avatar-lag":
        # measured publish→speak_started delay from the /face-avatar page;
        # the robot delays its own audio by this much in "sync" voice mode
        if not _authed({}, body):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            try:
                lag = max(0.0, min(4.0, float(body.get("lag"))))
                with open("/dev/shm/cj_avatar_lag", "w") as f:
                    f.write(f"{lag:.2f}")
                h._send(200, json.dumps({"ok": True, "output": lag}))
            except (TypeError, ValueError):
                h._send(200, json.dumps({"ok": False, "output": "bad lag"}))
    else:
        return False
    return True


def _sentence_pcm24k(path):
    """The avatar page streams the wav's raw PCM as 24 kHz/16-bit/mono. Every
    clip we produce already is; anything else is converted once (ffmpeg)."""
    import wave
    try:
        with wave.open(path, "rb") as w:
            ok = (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (24000, 1, 2)
    except Exception:
        ok = False
    if ok:
        return open(path, "rb").read()
    out = path + ".24k.wav"
    if not os.path.exists(out):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet", "-i", path,
                        "-ar", "24000", "-ac", "1", "-sample_fmt", "s16", out],
                       timeout=20)
    return open(out, "rb").read()


def _liveavatar_request(path, payload, auth_header):
    """POST to api.liveavatar.com (stdlib urllib; 15s timeout)."""
    import urllib.request
    req = urllib.request.Request(
        "https://api.liveavatar.com" + path,
        json.dumps(payload).encode(),
        {"Content-Type": "application/json",
         # their edge 403s python-urllib's default UA
         "User-Agent": "supervaise-cjap/1.0", **auth_header})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def avatar_session():
    """Create a LiveAvatar LITE session (sandbox by default) and return
    the connection material for the /face-avatar page. The API key stays
    server-side (assets/liveavatar.json — never sent to the browser)."""
    conf = _read_json(LIVEAVATAR_CONF)
    if not conf or not conf.get("api_key"):
        return False, ("no assets/liveavatar.json — create it with "
                       '{"api_key": "...", "avatar_id": "...", '
                       '"sandbox": true}')
    try:
        tok = _liveavatar_request(
            "/v1/sessions/token",
            {"mode": "LITE",
             "avatar_id": conf.get(
                 "avatar_id", "dd73ea75-1218-4ef3-92ce-606d5f7fbc0a"),
             "is_sandbox": bool(conf.get("sandbox", True))},
            {"X-API-KEY": conf["api_key"]})
        data = tok.get("data") or {}
        session_token = data.get("session_token")
        if not session_token:
            return False, f"token refused: {tok.get('message')}"
        start = _liveavatar_request(
            "/v1/sessions/start", {},
            {"Authorization": "Bearer " + session_token})
        sd = start.get("data") or {}
        if not sd.get("livekit_url"):
            return False, f"start refused: {start.get('message')}"
        sd["session_token"] = session_token   # page needs it for stop
        return True, sd
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def avatar_stop(session_token):
    try:
        _liveavatar_request("/v1/sessions/stop", {"reason": "USER_CLOSED"},
                            {"Authorization": "Bearer " + (session_token or "")})
        return True, "stopped"
    except Exception as e:
        return False, f"{type(e).__name__}"


def _serve_mjpeg(h):
    boundary = "cjapframe"
    try:
        h.send_response(200)
        h.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        last_ts = 0.0
        while True:
            frame = cam_frame()
            if not frame:
                break
            if _cam["ts"] != last_ts:
                last_ts = _cam["ts"]
                h.wfile.write(f"--{boundary}\r\nContent-Type: image/jpeg\r\n"
                              f"Content-Length: {len(frame)}\r\n\r\n".encode())
                h.wfile.write(frame + b"\r\n")
            time.sleep(0.1)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
