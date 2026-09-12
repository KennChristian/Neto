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
import queue
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _QuietServer(ThreadingHTTPServer):
    """2026-09-02: <video> elements abort /api/video Range requests on every
    seek/teardown — a routine BrokenPipe, not an error worth a traceback."""
    def handle_error(self, request, client_address):
        import sys
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)

try:  # P2.5 dual demo UI (/audience, /maintain) — optional module, fail-open
    import ui_routes as ui   # dashboard pages + routes (split 2026-08-29)
except Exception as _e:
    ui = None
    print(f"[dashboard] ui unavailable: {_e}")

PORT = 8080
# Bind address (2026-09-10): config/robots.json authority.bind, env CJ_DASH_BIND wins.
def _bind_host():
    try:
        import console as _console
        b = _console.ConfigSources().authority().get("bind") or "0.0.0.0"
    except Exception:
        b = "0.0.0.0"
    return os.environ.get("CJ_DASH_BIND", "").strip() or b
BIND = _bind_host()
HOME = os.path.expanduser("~")
AUDIO_OUT = os.path.join(HOME, "bin", "audio-out")
WAKE_MODEL = os.path.join(HOME, "Supervaise-Reachy-Mini-Project-main",
                          "app", "wake", "models", "hey_cee_jap.onnx")
TEST_WAV = os.path.join(HOME, "fillers", "01.wav")

UNITS = {
    "supervaise": "supervaise.service",
    "speaker-watchdog": "speaker-watchdog.service",
    "bt-keepalive": "bt-keepalive.service",
    "bluealsa": "bluealsa.service",
    "pi-dashboard": "pi-dashboard.service",
    "wifi-fallback": "wifi-fallback.service",
}

SPEAKERS = {
    "C41": "66:EA:C5:C3:E5:6B",          # C41 speaker (2026-09-02)
    "Sony ULT FIELD 1": "50:1B:6A:8B:16:F2",
    "Marshall EMBERTON": "04:21:44:84:1F:C1",
    "Laptop": "24:EE:9A:B2:13:D9",       # DESKTOP-B9F1GQ2 as a Bluetooth sink (2026-09-02; Stealth forgotten)
}
# ElevenLabs Voice Isolator before STT (2026-09-02): flag file the voice app
# checks per turn (main_voice_robot._stt_isolate) + its last-result record.
ISOLATE_FLAG = os.path.join(HOME, ".cj_stt_isolate_on")
ISOLATE_LAST = "/dev/shm/cj_isolate_last.json"

# relay-file paths live in ui_common (single source since 2026-08-29)
try:
    from ui_common import (WAKE_LIVE, WAKE_EVENTS, STOP_LIVE, STOP_EVENTS,   # noqa: E402
                           TRANSCRIPT, SPEAKING, WAKE_TRIGGER)
except Exception:   # degrade like `ui = None` above instead of dying at import
    WAKE_LIVE, WAKE_EVENTS = "/dev/shm/cj_wake_live.json", "/dev/shm/cj_wake_events.jsonl"
    STOP_LIVE, STOP_EVENTS = "/dev/shm/cj_stop_live.json", "/dev/shm/cj_stop_events.jsonl"
    TRANSCRIPT, SPEAKING, WAKE_TRIGGER = ("/dev/shm/cj_transcript.jsonl", "/dev/shm/cj_speaking.json",
                                          "/dev/shm/cj_wake_trigger")

ACTIONS = {
    "restart-app":      ["sudo", "-n", "systemctl", "restart", "supervaise.service"],
    "stop-app":         ["sudo", "-n", "systemctl", "stop", "supervaise.service"],
    "start-app":        ["sudo", "-n", "systemctl", "start", "supervaise.service"],
    "start-watchdog":   ["sudo", "-n", "systemctl", "start", "speaker-watchdog.service"],
    "stop-watchdog":    ["sudo", "-n", "systemctl", "stop", "speaker-watchdog.service"],
    "audio-internal":   [AUDIO_OUT, "internal"],
    "audio-c41":        [AUDIO_OUT, "c41"],         # 2026-09-02: C41 speaker
    "audio-sony":       [AUDIO_OUT, "sony"],
    "audio-marshall":   [AUDIO_OUT, "marshall"],
    "audio-laptop":     [AUDIO_OUT, "laptop"],      # 2026-09-02: laptop as a BT sink
    "audio-both":       [AUDIO_OUT, "both"],        # 2026-09-02: BT speaker + laptop at once
    "audio-dac":        [AUDIO_OUT, "dac"],         # 2026-09-05: USB DAC on the robot's hub
    "isolate-on":       ["touch", ISOLATE_FLAG],
    "isolate-off":      ["rm", "-f", ISOLATE_FLAG],
    "test-sound":       ["aplay", "-q", TEST_WAV],
    "tagalog-sample":   ["aplay", "-q", os.path.join(HOME, "demo_clips", "tagalog_sample_2026-08-13.wav")],
    "activate-listening": ["touch", WAKE_TRIGGER],
    "enroll-voice":     ["touch", "/dev/shm/cj_enroll_trigger"],
    "gate-on":          ["touch", os.path.join(HOME, "speaker_id", "enabled")],
    "gate-off":         ["rm", "-f", os.path.join(HOME, "speaker_id", "enabled")],
    "reboot":           ["sudo", "-n", "reboot"],
}

SPEAKER_LAST = "/dev/shm/cj_speaker_last.json"
SPEAKER_ENROLLED = os.path.join(HOME, "speaker_id", "enrolled.npz")
SPEAKER_ENABLED = os.path.join(HOME, "speaker_id", "enabled")
CERT_DIR = os.path.join(HOME, "pi_dashboard", "certs")
HTTPS_PORT = 8443

_play_lock = threading.Lock()   # serialize phone-mic playback


# ── WiFi (rewritten 2026-09-12, user: "double check the wifi part so that it would
# really connect") ────────────────────────────────────────────────────────────
# The dashboard runs as a systemd service: no login session. polkit's implicit
# policy for a session-less subject is auth_admin for wifi.scan and
# network-control and auth_admin_keep for settings.modify.system, and the
# netdev rule only helps local+active sessions. Plain nmcli therefore returned
# the STALE scan cache (only the network we were already on — verified: 11 in
# range, 1 listed) and could not activate or create a profile. Every control
# call now goes through sudo -n (pollen: NOPASSWD), like systemctl elsewhere.
NMCLI = ["sudo", "-n", "nmcli"]


def _nm(args, timeout=10):
    return run(NMCLI + list(args), timeout=timeout)


def _nm_split(line):
    """Split one `nmcli -t` line on unescaped colons (values escape ':' and '\\')."""
    out, cur, i = [], [], 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if c == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    out.append("".join(cur))
    return out


_wifi_profiles_cache = {"ts": 0.0, "data": None}


def wifi_profiles(refresh=False):
    """Saved wireless profiles -> {profile name: ssid}. Profile names are not
    always the SSID (ReachySetup / Hotspot both carry "CJAP Reachy"), and the
    scan list speaks SSIDs, so the mapping is what "saved" and "join" key on.
    One nmcli call per profile, cached 60 s."""
    c = _wifi_profiles_cache
    if not refresh and c["data"] is not None and time.time() - c["ts"] < 60:
        return c["data"]
    names = []
    _, out = _nm(["-t", "-f", "NAME,TYPE", "connection", "show"])
    for line in out.splitlines():
        parts = _nm_split(line)
        if len(parts) >= 2 and "wireless" in parts[1]:
            names.append(parts[0])
    data = {}
    for n in names:
        _, ssid = _nm(["-g", "802-11-wireless.ssid", "connection", "show", n], timeout=5)
        ssid = re.sub(r"\\(.)", r"\1", ssid.strip())     # -g escapes ':' and '\' like -t does
        data[n] = ssid or n
    c.update(ts=time.time(), data=data)
    return data


def wifi_active():
    """Name of the active wireless profile (None when the radio is idle)."""
    _, out = _nm(["-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"])
    for line in out.splitlines():
        parts = _nm_split(line)
        if len(parts) >= 3 and "wireless" in parts[1] and parts[2]:
            return parts[0]
    return None


def wifi_status():
    """-> (saved SSIDs, active profile name)."""
    profiles = wifi_profiles()
    return sorted(set(profiles.values())), wifi_active()


def wifi_scan(rescan=False):
    cmd = ["-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "dev", "wifi", "list"]
    if rescan:
        cmd += ["--rescan", "yes"]
    _, out = _nm(cmd, timeout=40)
    nets, seen = [], set()
    for line in out.splitlines():
        parts = _nm_split(line)
        if len(parts) < 4 or not parts[0] or parts[0] in seen:
            continue
        seen.add(parts[0])
        try:
            signal = int(parts[1] or 0)
        except ValueError:
            signal = 0
        nets.append({"ssid": parts[0], "signal": signal,
                     "security": parts[2] or "open",
                     "in_use": parts[3] == "*"})
    nets.sort(key=lambda n: -n["signal"])
    return nets


SETUP_CON = "ReachySetup"   # wifi_fallback.sh setup-hotspot profile name


def hotspot_active():
    return wifi_active() == SETUP_CON


def _profile_for(ssid):
    """Saved profile name for an SSID (never the setup hotspot)."""
    for name, s in wifi_profiles(refresh=True).items():
        if s == ssid and name != SETUP_CON:
            return name
    return None


def _wifi_join(ssid, password=None, hidden=False):
    name = _profile_for(ssid)
    had_profile = name is not None
    if name and password:
        # `nmcli dev wifi connect` reuses an existing profile and would keep
        # its OLD password — write the new one into the profile first, then
        # activate that profile (this is how a changed router password is fixed).
        code, out = _nm(["connection", "modify", name, "wifi-sec.psk", password], timeout=15)
        if code != 0:
            return False, f"could not store the password in profile {name!r}: {out[-200:]}"
    if name:
        code, out = _nm(["connection", "up", "id", name], timeout=60)
    else:
        cmd = ["dev", "wifi", "connect", ssid]
        if password:
            cmd += ["password", password]
        if hidden:
            cmd += ["hidden", "yes"]
        code, out = _nm(cmd, timeout=60)
    _wifi_profiles_cache["ts"] = 0.0
    if code != 0 and not had_profile and _profile_for(ssid):
        # a failed first join leaves a half-made profile behind (it would even
        # autoconnect later) — drop it so the list stays honest
        _nm(["connection", "delete", "id", _profile_for(ssid)], timeout=10)
        _wifi_profiles_cache["ts"] = 0.0
    return code == 0, out[-300:]


def wifi_connect(ssid, password=None, hidden=False):
    """Bring up a saved connection, or join a new network. NOTE: on success
    the phone loses the dashboard until it re-joins the same network. On
    failure the robot is put back on the network it came from. `hidden` is
    the operator's word that the SSID does not broadcast: without it a name
    that is not in the last scan is refused instead of costing a 60 s outage
    on a typo."""
    ssid = (ssid or "").strip()
    if not ssid or len(ssid.encode("utf-8")) > 32:
        return False, "invalid ssid"
    hidden = bool(hidden)
    if not hidden and not hotspot_active() and ssid not in {n["ssid"] for n in wifi_scan()}:
        return False, (f'"{ssid}" was not in the last scan — tap Scan networks again, '
                       "or tick \u201chidden network\u201d if it does not broadcast its name")
    if hotspot_active():
        # The phone is on the setup hotspot: joining a network takes the AP
        # (and this HTTP connection) down, so reply first and switch in the
        # background; on failure the hotspot comes straight back.
        def _switch():
            _nm(["connection", "down", SETUP_CON], timeout=15)
            ok, out = _wifi_join(ssid, password, hidden)
            if not ok:
                print(f"[wifi-fallback] join {ssid!r} failed ({out}) — hotspot back up", flush=True)
                _nm(["connection", "up", SETUP_CON], timeout=20)
        threading.Thread(target=_switch, daemon=True).start()
        return True, (f'trying to join "{ssid}" — reconnect your phone to that '
                      "network and reopen the dashboard; if joining fails, the "
                      "CJAP Reachy hotspot returns within a minute")
    prev = wifi_active()
    ok, out = _wifi_join(ssid, password, hidden)
    if ok:
        return True, f'now on "{ssid}"'
    if prev and wifi_active() is None:
        back_code, _ = _nm(["connection", "up", "id", prev], timeout=45)
        out += f" — back on {prev!r}" if back_code == 0 else f" — and {prev!r} did not come back"
    return False, out


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


def _robot_busy():
    """'speaking' / None — typed speech must not play over the
    app's own answer (it also clobbers cj_speaking.json and freezes the
    avatar portrait mid-answer). Mic mute (2026-08-29) does NOT block typed
    speech — the operator muted the microphone, not the robot's voice."""
    try:
        with open(SPEAKING) as f:
            doc = json.load(f)
        # "current" without "done" = a clip on air; but if the app was
        # restarted/crashed mid-answer nobody writes done=true, so bound the
        # staleness by that clip's length (+ grace) rather than a flat 2 min.
        age = time.time() - float(doc.get("ts") or 0)
        limit = min(120.0, float(doc.get("dur") or 30.0) + 8.0)
        if doc.get("current") and not doc.get("done") and age < limit:
            return "speaking"
    except Exception:
        pass
    return None


def say_text(text):
    """Speak typed text in the CJ voice (cloud TTS via the app venv)."""
    text = (text or "").strip()
    if not text or len(text) > 500:
        return False, "text empty or over 500 characters"
    busy = _robot_busy()
    if busy:
        return False, f"robot is {busy} — try again when it is idle"
    wav = tempfile.mktemp(dir="/dev/shm", suffix=".wav")
    try:
        code, out = run([APP_VENV_PY, SAY_HELPER, text, wav], timeout=60)
        if code != 0:
            return False, out[-250:]
        with _play_lock:
            busy = _robot_busy()      # re-check: an answer may have started during synthesis
            if busy:
                return False, f"robot is {busy} — try again when it is idle"
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
                if code != 0:   # 2026-09-01: Bluetooth speaker dropped? fall back now, not in a minute
                    ec, eo = run([os.path.expanduser("~/bin/audio-out"), "ensure"], timeout=30)
                    if ec == 10:
                        code, out = run(["aplay", "-q", wav], timeout=120)
                        out = "Bluetooth speaker gone — switched to the internal speaker and replayed. " + out
            _publish_say_speaking(text, done=True)
        return code == 0, out[-200:]
    finally:
        for p in (wav, wav + ".align.json"):
            if os.path.exists(p):
                os.unlink(p)


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
        os.replace(tmp, SPEAKING)
    except OSError:
        pass


def _publish_sentence_copy(wav):
    """Same contract as speech_streaming.publish_sentence_wav (kept in step by
    hand — the dashboard runs on system python, not the app venv)."""
    try:
        import glob as _glob
        name = f"cj_sent_{int(time.time()*1000)}.wav"
        tmp = "/dev/shm/." + name
        with open(wav, "rb") as src, open(tmp, "wb") as dst:
            dst.write(src.read())
        os.replace(tmp, "/dev/shm/" + name)
        for p in sorted(_glob.glob("/dev/shm/cj_sent_*.wav"))[:-24]:
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


def voice_audition(voice_id):
    """Preview clip of an ElevenLabs voice through the robot's current audio route."""
    busy = _robot_busy()
    if busy:
        return False, f"robot is {busy} \u2014 try again when it is idle"
    ok, data = ui.eleven_voice_sample(voice_id)
    if not ok:
        return False, data
    ok, out = play_phone_audio(data)
    return ok, ("played" if ok else out)


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


# Fire-and-forget actions (2026-08-29, user: "make the actions fire and
# forget"): POST /api/action answers at once with a job id; the command runs
# in a thread and the page polls GET /api/action/status?id=N until done. A
# 30 s systemctl restart or BT reconnect no longer holds the browser's
# request slot (and the "ok" note) hostage.
_JOBS = {}
_JOBS_LOCK = threading.Lock()
_JOB_SEQ = [0]


def start_job(name, cmd, timeout, who=""):
    with _JOBS_LOCK:
        _JOB_SEQ[0] += 1
        jid = _JOB_SEQ[0]
        _JOBS[jid] = {"id": jid, "name": name, "state": "running", "ok": None,
                      "output": "", "started": time.time(), "finished": None}
        for old_id in sorted(_JOBS)[:-40]:   # keep the last 40
            _JOBS.pop(old_id, None)

    def _worker():
        code, out = run(cmd, timeout=timeout)
        try:
            print(f"[action] {who} {name} -> rc={code}", flush=True)
        except Exception:
            pass
        with _JOBS_LOCK:
            _JOBS[jid].update({"state": "done", "ok": code == 0,
                               "output": out[-500:], "finished": time.time()})
    threading.Thread(target=_worker, daemon=True, name=f"action-{name}").start()
    return jid


def job_status(jid):
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        return dict(j) if j else None


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
    rc, dac = run([AUDIO_OUT, "dac-present"], timeout=5)   # 2026-09-05: USB DAC sink, or ""
    return {"route": route, "speakers": speakers, "dac": dac.strip() if rc == 0 else ""}


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


_stop_thr_cache = {"t": 0, "v": 0.02}


def stop_threshold():
    if time.time() - _stop_thr_cache["t"] > 10:
        try:
            _stop_thr_cache["v"] = float(wake_info()["env"].get("CJ_STOP_OWW_THRESHOLD", 0.02))
        except Exception:
            pass
        _stop_thr_cache["t"] = time.time()
    return _stop_thr_cache["v"]


def stop_live():
    """Stop-word meter feed (2026-08-26): what the barge-in listener scores
    while an answer plays. live=False between answers (nothing scoring)."""
    out = {"live": False, "threshold": stop_threshold(), "events": []}
    try:
        d = json.load(open(STOP_LIVE))
        age = time.time() - d.get("ts", 0)
        out.update(d)
        out["age"] = round(age, 2)
        out["live"] = age < 2.0
    except Exception:
        pass
    try:
        lines = open(STOP_EVENTS).read().splitlines()[-8:]
        out["events"] = [json.loads(ln) for ln in lines][::-1]
    except Exception:
        pass
    return out


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
    iso = {"enabled": os.path.exists(ISOLATE_FLAG), "last": None}
    try:
        iso["last"] = json.load(open(ISOLATE_LAST))
    except Exception:
        pass
    out["isolate"] = iso
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
  <div class="row" style="margin-top:6px"><span class="lbl">Voice isolator (ElevenLabs)</span>
    <span class="val" id="iso-state">—</span></div>
  <div class="row"><span class="lbl">Last isolation</span>
    <span class="val" id="iso-last">—</span></div>
  <div class="btns">
    <button id="iso-btn" onclick="toggleIsolate()">…</button>
  </div>
  <div class="row" style="border:0"><span class="lbl" style="font-size:12px">
    ON: each capture is cleaned by the ElevenLabs Voice Isolator before
    speech-to-text (adds ~2-3 s per turn; falls back to the raw capture on
    any error). Turn it OFF if answers get slow or transcripts get worse.</span></div>
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
  <div class="row"><span class="lbl">C41</span><span class="val" id="spk-c41"></span></div>
  <div class="row"><span class="lbl">Sony ULT FIELD 1</span><span class="val" id="spk-sony"></span></div>
  <div class="row"><span class="lbl">Marshall EMBERTON</span><span class="val" id="spk-marshall"></span></div>
  <div class="row"><span class="lbl">USB DAC</span><span class="val" id="spk-dac"></span></div>
  <div class="row"><span class="lbl">Laptop (Bluetooth)</span><span class="val" id="spk-laptop"></span></div>
  <div class="row"><span class="lbl">Speaker watchdog</span><span class="val" id="svc-watchdog"></span></div>
  <div class="btns">
    <button onclick="act('audio-internal')">Route: internal</button>
    <button onclick="act('audio-c41')">Route: C41</button>
    <button onclick="act('audio-dac')">Route: USB DAC</button>
    <button onclick="act('audio-sony')">Route: Sony</button>
    <button onclick="act('audio-marshall')">Route: Marshall</button>
    <button onclick="act('audio-laptop')">Route: laptop</button>
    <button onclick="act('audio-both')">Route: speaker + laptop</button>
    <button onclick="act('test-sound')">Play test sound</button>
    <button onclick="act('tagalog-sample')">Play Tagalog sample</button>
    <button id="wd-btn" onclick="toggleWatchdog()">…</button>
  </div>
  <div class="row" style="border:0;margin-top:6px"><span class="lbl" style="font-size:12px">
    Watchdog keeps audio on a Bluetooth speaker (Sony first) whenever one works,
    but leaves a working manual choice alone (laptop, speaker + laptop). Internal
    speaker is required for echo-cancel. "Speaker + laptop" plays every answer on
    both at once — the laptop must have Bluetooth on and accept audio from the
    robot (it is paired as DESKTOP-B9F1GQ2).</span></div>
</div>

<div class="card"><h2>Bluetooth</h2>
  <div class="row" style="border:0"><span class="lbl">Devices (tap to connect / disconnect)</span></div>
  <div id="bt-list" style="font-size:14px">loading…</div>
  <div class="btns"><button onclick="btScan(true)">Scan for new devices (~8 s)</button></div>
  <div class="row" style="border:0"><span class="lbl" style="font-size:12px">
    Pairing a new speaker connects it, but the playback route still follows the
    Audio buttons above (Sony / Marshall / laptop / internal). While the watchdog runs,
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
    <option value="bt-keepalive">bt-keepalive</option>
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
    $("spk-c41").innerHTML = dot(s.audio.speakers["C41"],
      s.audio.speakers["C41"] ? "connected" : "not connected");
    $("spk-sony").innerHTML = dot(s.audio.speakers["Sony ULT FIELD 1"],
      s.audio.speakers["Sony ULT FIELD 1"] ? "connected" : "not connected");
    $("spk-marshall").innerHTML = dot(s.audio.speakers["Marshall EMBERTON"],
      s.audio.speakers["Marshall EMBERTON"] ? "connected" : "not connected");
    $("spk-dac").innerHTML = dot(!!s.audio.dac, s.audio.dac ? "plugged in" : "not plugged in");
    $("spk-laptop").innerHTML = dot(s.audio.speakers["Laptop"],
      s.audio.speakers["Laptop"] ? "connected" : "not connected");
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
    let out = await r.json();
    if (out.queued) {           // fire-and-forget: poll the job until it finishes
      toast(name + " sent…");
      for (let i = 0; i < 400 && out.state !== "done"; i++) {
        await new Promise(res => setTimeout(res, 300));
        out = await (await fetch("/api/action/status?id=" + out.id)).json();
      }
    }
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
    renderIsolate(w.isolate);
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

// ── ElevenLabs voice isolator (before STT) ────────────────────────
let isolateEnabled = false;
function renderIsolate(iso) {
  if (!iso) return;
  isolateEnabled = !!iso.enabled;
  $("iso-state").innerHTML = dot(isolateEnabled,
    isolateEnabled ? "ON — captures cleaned before STT" : "off — raw capture to STT");
  $("iso-btn").textContent = isolateEnabled ? "Isolator: turn OFF" : "Isolator: turn ON";
  if (iso.last) {
    $("iso-last").innerHTML = dot(iso.last.ok,
      (iso.last.ok ? "ok" : "failed") + " · " + (iso.last.ms / 1000).toFixed(1) + " s for " +
      iso.last.in_s + " s  " + fmtClock(iso.last.ts) + (iso.last.note ? " — " + iso.last.note : ""));
  }
}
function toggleIsolate() { act(isolateEnabled ? "isolate-off" : "isolate-on"); }

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
    const key = new URLSearchParams(location.search).get("key") || "";
    const r = await fetch("/api/say-text", { method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text, key}) });
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


# ── Live push (2026-09-12, user: "implement the push version") ──────────────
# /api/events is a Server-Sent Events stream. ONE background publisher samples
# the state document every 250 ms, the meters every 300 ms and the system
# status every 5 s, and sends a frame only when the document changed (the
# state frame is also resent every 2 s so the page's clocks stay honest). N
# open pages share that work; each holds one server thread and a small queue.
# The page falls back to polling if the stream cannot connect.
def _stable(doc):
    """The document minus the fields that change on every sample (clocks and
    ages) — what the publisher compares to decide whether anything happened."""
    if isinstance(doc, dict):
        return {k: _stable(v) for k, v in doc.items() if k not in ("ts", "age", "age_s", "uptime_s", "score", "consoleWall", "elapsed_s")}
    if isinstance(doc, list):
        return [_stable(v) for v in doc]
    return doc


class _Push:
    def __init__(self):
        self.lock = threading.Lock()
        self.subs = set()
        self.thread = None
        self.last = {}          # event -> last frame bytes (new subscribers get a snapshot)
        self._status_busy = False

    def subscribe(self):
        q = queue.Queue(maxsize=60)
        with self.lock:
            self.subs.add(q)
            for ev in ("state", "meters", "status"):
                if ev in self.last:
                    q.put_nowait(self.last[ev])
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._loop, daemon=True, name="push")
                self.thread.start()
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.subs.discard(q)

    def _emit(self, event, data):
        frame = f"event: {event}\ndata: {data}\n\n".encode("utf-8")
        with self.lock:
            self.last[event] = frame
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait(frame)
            except queue.Full:
                pass    # a stalled page drops a frame; the next one carries the whole document anyway

    def _status_async(self):
        def go():
            try:
                d = json.dumps(status())
                if d != self._last_status:
                    self._last_status = d
                    self._emit("status", d)
            except Exception:
                pass
            finally:
                self._status_busy = False
        if not self._status_busy:
            self._status_busy = True
            threading.Thread(target=go, daemon=True).start()

    def _loop(self):
        key_state = last_meters = None
        self._last_status = None
        t_state = t_meters = t_status = 0.0
        sent_state = time.time()
        while True:
            with self.lock:
                if not self.subs:
                    self.thread = None
                    return
            now = time.time()
            if now - t_meters >= 0.3:
                t_meters = now
                try:
                    md = {"wake": wake_live(), "stop": stop_live()}
                    mk = json.dumps(_stable(md), sort_keys=True, default=str)
                    if mk != last_meters:      # a live meter's score changes every sample: that IS the feed
                        last_meters = mk
                        self._emit("meters", json.dumps(md))
                except Exception:
                    pass
            if now - t_state >= 0.25 and ui is not None:
                t_state = now
                try:
                    doc = ui.state_doc()
                    key = json.dumps(_stable(doc), sort_keys=True, default=str)
                    # resend every 2 s even when nothing changed: the page's "wake listener
                    # armed" check compares clocks that ride on this document
                    if key != key_state or now - sent_state >= 2:
                        key_state, sent_state = key, now
                        self._emit("state", json.dumps(doc))
                except Exception:
                    pass
            if now - t_status >= 5:
                t_status = now
                self._status_async()      # status() probes take ~0.6 s — never in this loop
            time.sleep(0.05)


PUSH = _Push()


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.1 keep-alive (2026-08-29, user: "make the maintenance UI faster"):
    # the /maintain page polls ~10 req/s (wake meter 300 ms, state 500 ms,
    # camera 200 ms). Under the HTTP/1.0 default every poll paid a fresh TCP
    # handshake over WiFi and the browser's 6-connection cap queued the rest.
    # Every response must carry Content-Length (or set close_connection) —
    # _send does; the 302 redirects and the MJPEG stream were patched to.
    protocol_version = "HTTP/1.1"
    timeout = 60   # idle keep-alive connection → reap its thread

    def log_message(self, *a):  # journald picks up real errors; skip access noise
        pass

    def handle_error(self, *a):  # a phone closing a page mid-response is not an error
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, TimeoutError)):
            return
        super().handle_error(*a)

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
        if path == "/api/action/status":
            try:
                j = job_status(int(params.get("id", "0")))
            except ValueError:
                j = None
            self._send(200 if j else 404, json.dumps(j or {"error": "no such job"}))
            return
        if path == "/api/events":
            q = PUSH.subscribe()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                self.wfile.write(b"retry: 2000\n\n")
                self.wfile.flush()
                while True:
                    try:
                        frame = q.get(timeout=15)
                    except queue.Empty:
                        frame = b": ping\n\n"     # keeps phones and proxies from closing an idle stream
                    self.wfile.write(frame)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
                pass
            finally:
                PUSH.unsubscribe(q)
                self.close_connection = True
            return
        if ui and ui.handle_get(self, path, params):
            return
        if path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif path == "/api/status":
            self._send(200, json.dumps(status()))
        elif path == "/api/wake":
            self._send(200, json.dumps(wake_live()))
        elif path == "/api/stop":
            self._send(200, json.dumps(stop_live()))
        elif path == "/api/meters":   # 2026-09-12: /maintain polls both meters in ONE request (was two at 300 ms)
            self._send(200, json.dumps({"wake": wake_live(), "stop": stop_live()}))
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
        if ui and self.path.partition("?")[0] == "/api/video-upload":
            # raw video bytes from the /maintain "Video clips" card — never
            # json.loads'd; ui.video_upload streams rfile straight to disk
            _, _, q = self.path.partition("?")
            params = {k: v for k, v in
                      (p.split("=", 1) for p in q.split("&") if "=" in p)}
            if not ui._authed(params):
                self.close_connection = True   # don't read a large body we reject
                self._send(403, json.dumps({"ok": False, "output": "bad key"}))
                return
            ok, out = ui.video_upload(self, params)
            print(f"[ctl] {self.client_address[0]} video-upload -> {out}", flush=True)
            self._send(200, json.dumps({"ok": ok, "output": out}))
            return
        if ui and self.path.partition("?")[0] in (
                "/api/ctl", "/api/entities", "/api/avatar-session",
                "/api/avatar-stop", "/api/avatar-lag", "/api/avatar-status",
                "/api/avatar-conf", "/api/voices",
                "/api/ask", "/api/tuning", "/api/volume", "/api/mic",
                # operator console (2026-09-10): floor lease + mode/profile
                "/api/lease", "/api/floor", "/api/role", "/api/config", "/api/pending",
                "/api/host-ask",
                "/api/calibrate", "/api/unlock-request"):
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                body = {}
            if ui.handle_post(self, self.path.partition("?")[0], body):
                return
        if self.path == "/api/wifi/connect":
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                ok, out = wifi_connect(body.get("ssid", ""),
                                       body.get("password") or None,
                                       hidden=bool(body.get("hidden")))
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
        if self.path.partition("?")[0] == "/api/say-text":
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                from urllib.parse import parse_qs
                params = {k: v[0] for k, v in
                          parse_qs(self.path.partition("?")[2]).items()}
                if not ui._authed(params, body):
                    # anyone on the LAN could make the robot speak / spend
                    # ElevenLabs credits (2026-08-25 review)
                    self._send(403, json.dumps({
                        "ok": False, "output": "bad key — open the page with ?key=cjap"}))
                    return
                print(f"[say] {self.client_address[0]} {body.get('text', '')[:80]!r}",
                      flush=True)
                ok, out = say_text(body.get("text", ""))
            except Exception as e:
                ok, out = False, str(e)
            self._send(200, json.dumps({"ok": ok, "output": out}))
            return
        if self.path.partition("?")[0] == "/api/voice-audition":
            # Guest voice card (2026-09-12): play an ElevenLabs voice's preview
            # clip on the robot's speaker (free) so the operator can compare
            # voices in the room, not just on the phone.
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                if not ui._authed({}, body):
                    self._send(403, json.dumps({"ok": False, "output": "bad key"}))
                    return
                ok, out = voice_audition(body.get("voice_id"))
                print(f"[say] {self.client_address[0]} audition {body.get('voice_id', '')} -> "
                      f"{'ok' if ok else out}", flush=True)
            except Exception as e:
                ok, out = False, str(e)
            self._send(200, json.dumps({"ok": ok, "output": out}))
            return
        if self.path == "/api/say-audio":
            try:
                n = int(self.headers.get("Content-Length", 0))
                if n > 15_000_000:
                    self.close_connection = True   # body left unread: don't reuse the socket
                    raise ValueError("audio too large")
                ok, out = play_phone_audio(self.rfile.read(n))
            except Exception as e:
                ok, out = False, str(e)
            self._send(200, json.dumps({"ok": ok, "output": out}))
            return
        if self.path != "/api/action":
            try:  # drain the body so the keep-alive stream stays in sync
                self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
            except Exception:
                pass
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
        if name == "reboot":
            # 2026-08-25: answer the browser FIRST, then reboot a moment later —
            # otherwise this process is SIGTERMed mid-request and the page never
            # learns whether the button worked.
            self._send(200, json.dumps({"ok": True, "output": "rebooting"}))
            try:
                print(f"[action] {self.client_address[0]} reboot -> scheduled", flush=True)
            except Exception:
                pass
            threading.Timer(1.5, lambda: subprocess.run(ACTIONS["reboot"], timeout=30)).start()
            return
        if name == "activate-listening" and ui is not None and os.path.exists(ui.MUTED_FLAG):
            self._send(200, json.dumps({"ok": False, "output": "mic is MUTED — press Unmute mic first"}))
            return
        # tagalog-sample is a ~45 s clip — the generic 30 s cap would cut it off
        jid = start_job(name, ACTIONS[name],
                        timeout=90 if name == "tagalog-sample" else 30,
                        who=self.client_address[0])
        self._send(200, json.dumps({"ok": True, "queued": True, "id": jid,
                                    "output": "queued"}))


def serve_https():
    cert = os.path.join(CERT_DIR, "cert.pem")
    key = os.path.join(CERT_DIR, "key.pem")
    if not (os.path.exists(cert) and os.path.exists(key)):
        print("[dashboard] no TLS cert — HTTPS (phone mic) disabled")
        return
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    srv = _QuietServer((BIND, HTTPS_PORT), Handler)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print(f"[dashboard] HTTPS (phone mic) on {BIND}:{HTTPS_PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    threading.Thread(target=serve_https, daemon=True).start()
    print(f"[dashboard] serving on {BIND}:{PORT}", flush=True)
    _QuietServer((BIND, PORT), Handler).serve_forever()
