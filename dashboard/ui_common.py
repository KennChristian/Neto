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
# Name/preview of whatever avatar_id is configured, resolved once when the
# operator applies it (ui_page_face.avatar_conf_set). state() is polled ~3x/s
# by every open page, so it reads this cache and never calls the API.
LIVEAVATAR_CACHE = os.path.join(ASSETS, "liveavatar_avatar.json")
AVATAR_ID_DEFAULT = "dd73ea75-1218-4ef3-92ce-606d5f7fbc0a"   # "Wayne", the stock avatar
# How big the avatar sits on /face-avatar (2026-09-04, user: "make the avatar
# full ... or make a button for flexibility"). Persistent so a page reload and
# a reboot keep the operator's choice.
AVATAR_VIEW_FILE = os.path.join(HOME, ".cj_avatar_view")
AVATAR_VIEWS = ("framed", "wide", "full")
os.makedirs(ASSETS, exist_ok=True)

DASH_KEY = os.environ.get("CJ_DASH_KEY", "cjap")


def _authed(params, body=None):
    key = params.get("key") or (body or {}).get("key")
    return key == DASH_KEY


# ---------------------------------------------------------------------------
# camera — one rpicam-vid MJPEG process, latest frame shared by all viewers
# ---------------------------------------------------------------------------

_cam = {"proc": None, "frame": b"", "ts": 0.0, "last_read": 0.0, "lock": threading.Lock(),
        "cv": threading.Condition()}   # cv: MJPEG streamers wake per frame (2026-09-01)
# Camera OFF switch (2026-08-30, user: "a button for turning off the camera").
# Persistent flag file (survives dashboard restarts AND reboots): while it
# exists cam_frame() never launches rpicam-vid and any running instance is
# killed, so /dev/video* is not held by anything the dashboard controls.
# /maintain Camera card: On / Off buttons (ctl camera-on / camera-off).
CAMERA_OFF_FLAG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "camera.off")


def camera_off() -> bool:
    return os.path.exists(CAMERA_OFF_FLAG)


def _cam_kill():
    """Stop the capture process (if any) and drop the stale frame. Deliberate:
    never counts toward the GStreamer→rpicam fallback."""
    with _cam["lock"]:
        p, _cam["proc"] = _cam["proc"], None
    if p is not None:
        p._cj_deliberate = True      # its reader must not count this as a crash
        try:
            if p.stdin is not None:
                try:
                    p.stdin.write(b"quit\n"); p.stdin.flush()
                except (OSError, ValueError):
                    pass
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            try:
                p.kill(); p.wait(timeout=2)
            except Exception:
                pass
    _cam_reap_strays()
    _cam["frame"], _cam["ts"] = b"", 0.0


def camera_set(on: bool):
    if on:
        try:
            os.unlink(CAMERA_OFF_FLAG)
        except OSError:
            pass
        _cam_state["backend"], _cam_state["fails"] = _CAM_BACKEND, 0
        _cam_ensure()
        return True, "camera ON — camera running (stays on until Camera off)"
    with open(CAMERA_OFF_FLAG, "w") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
    _cam_kill()
    return True, "camera OFF — capture stopped; stays off across restarts/reboots until Camera on"
_CAM_W, _CAM_H = 800, 450
_CAM_FPS = int(os.environ.get("CJ_CAMERA_FPS", "15"))   # 2026-09-01: 10 -> 15 (livestream "faster")
_CAM_CMD_RPICAM = ["rpicam-vid", "-n", "-t", "0", "--codec", "mjpeg", "--width", str(_CAM_W),
                   "--height", str(_CAM_H), "--framerate", str(_CAM_FPS), "--inline", "-o", "-"]
# 2026-09-01 (user: "make the camera streaming from gstreamer"): the capture
# engine is a GStreamer pipeline (libcamerasrc) emitting the same concatenated
# JPEG stream on stdout, so every consumer (/api/camera.jpg, .mjpg, /audience,
# /face) is unchanged. Encoder: CJ_CAMERA_ENC=sw (jpegenc q70 — ~16 KB frames,
# ~26 % of one core, default) | hw (v4l2jpegenc — ~9 % CPU but the M2M encoder
# ignores its quality control here: ~80 KB frames). CJ_CAMERA_BACKEND=rpicam
# restores rpicam-vid; a GStreamer pipeline that dies twice within 10 s of
# starting also falls back to rpicam-vid for the rest of the session.
_CAM_BACKEND = os.environ.get("CJ_CAMERA_BACKEND", "gst").strip().lower()
_CAM_ENC = os.environ.get("CJ_CAMERA_ENC", "sw").strip().lower()
# 2026-09-01 blurry-display fix: the IMX708 wide has an autofocus lens and
# libcamerasrc defaults af-mode=manual (lens parked, never focuses), whereas
# rpicam-vid ran continuous AF by default — hence the soft picture after the
# GStreamer switch. af-mode=continuous restores rpicam-vid's behaviour.
# 2026-09-01 (user: "continuous but add a refocus button"): the pipeline runs in
# cam_stream.py (python-gi) instead of gst-launch so autofocus can be driven at
# runtime over stdin ("refocus", "lens N", "lens auto"). Same JPEG stream on stdout.
_CAM_STREAM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cam_stream.py")
_CAM_CMD_GST = ["/usr/bin/python3", _CAM_STREAM, str(_CAM_W), str(_CAM_H), str(_CAM_FPS), _CAM_ENC]
_CAM_LOG = "/dev/shm/cam_stream.log"
# Focus policy (2026-09-01, user: "continuous but add a refocus button" → "refocus
# is not functioning well"): libcamera's AF picks the NEAREST object in view, so
# on stage it parks at macro on the table / the robot's own housing. "auto" =
# continuous AF measured only in CJ_CAM_AF_WINDOW (upper middle, where faces
# are); a number = fixed lens position in dioptres (0.5 = 2 m, 1 = 1 m) for a
# rock-steady stage picture. Both restart the capture (~2 s), because
# libcamerasrc ignores focus changes once playing.
_CAM_AF_WINDOW = os.environ.get("CJ_CAM_AF_WINDOW", "0.15,0.05,0.85,0.55")
_CAM_FOCUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "camera.focus")


def _cam_focus_load():
    """Remembered focus policy ('auto' or dioptres) — survives dashboard restarts and reboots."""
    try:
        v = open(_CAM_FOCUS_FILE).read().strip()
        return v if v == "auto" or 0 <= float(v) <= 12 else "auto"
    except (OSError, ValueError):
        return "auto"


# Camera options (2026-09-02, user: "multiple options for the camera ... in the
# maintain UI"): resolution / framerate / encoder are runtime state, persisted
# like the focus policy, applied by restarting the capture (~2 s).
_CAM_OPTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "camera.opts")
CAM_RES_PRESETS = ("640x360", "800x450", "1280x720", "1920x1080")
CAM_FPS_PRESETS = (5, 10, 15, 30)


def _cam_opts_load():
    try:
        d = json.loads(open(_CAM_OPTS_FILE).read())
        res = f"{int(d['w'])}x{int(d['h'])}"
        return {"w": int(d["w"]), "h": int(d["h"]),
                "fps": int(d["fps"]) if 1 <= int(d["fps"]) <= 60 else _CAM_FPS,
                "enc": d["enc"] if d.get("enc") in ("sw", "hw") else _CAM_ENC}             if res in CAM_RES_PRESETS else             {"w": _CAM_W, "h": _CAM_H, "fps": _CAM_FPS, "enc": _CAM_ENC}
    except (OSError, ValueError, KeyError, TypeError):
        return {"w": _CAM_W, "h": _CAM_H, "fps": _CAM_FPS, "enc": _CAM_ENC}


_cam_state = {"backend": _CAM_BACKEND, "fails": 0, "started": 0.0, "focus": _cam_focus_load(),
              **_cam_opts_load()}
CAM_FOCUS_PRESETS = {"auto": "autofocus", "0": "far (∞)", "0.33": "3 m", "0.5": "2 m",
                     "1": "1 m", "2": "50 cm"}


def _cam_cmd():
    w, h, fps = _cam_state["w"], _cam_state["h"], _cam_state["fps"]
    if _cam_state["backend"] == "gst":
        if any(os.path.exists(os.path.join(d, "gst-launch-1.0")) for d in os.environ.get("PATH", "").split(":")):
            return ["/usr/bin/python3", _CAM_STREAM, str(w), str(h), str(fps),
                    _cam_state["enc"], _cam_state["focus"], _CAM_AF_WINDOW]
        print("[cam] gst-launch-1.0 not found — rpicam-vid", flush=True)
        _cam_state["backend"] = "rpicam"
    return ["rpicam-vid", "-n", "-t", "0", "--codec", "mjpeg", "--width", str(w),
            "--height", str(h), "--framerate", str(fps), "--inline", "-o", "-"]


def _cam_reap_strays(keep_pid=None):
    """Kill capture processes the dashboard no longer tracks (a restart race or
    an earlier dashboard) — libcamera allows one owner, so a stray blocks us."""
    try:
        out = subprocess.run(["pgrep", "-f", r"^/usr/bin/python3 \S*/cam_stream\.py|^rpicam-vid "],
                             capture_output=True, text=True, timeout=3).stdout.split()
    except Exception:
        return
    for pid in out:
        if keep_pid is not None and int(pid) == keep_pid:
            continue
        try:
            os.kill(int(pid), 15)
            print(f"[cam] reaped stray capture pid {pid}", flush=True)
        except OSError:
            pass


def cam_focus_label():
    f = _cam_state["focus"]
    if f in CAM_FOCUS_PRESETS:
        return CAM_FOCUS_PRESETS[f]
    try:
        d = float(f)
        if d <= 0:
            return "far (∞)"
        m = 1.0 / d
        return f"{m:.1f} m" if m >= 1 else f"{m * 100:.0f} cm"
    except ValueError:
        return str(f)


def camera_focus(value):
    """'auto' or a dioptre preset (see CAM_FOCUS_PRESETS): restart the capture
    with that focus policy. ~2 s frozen picture; the pages re-attach."""
    value = str(value).strip()
    if value != "auto":
        try:
            d = float(value)
            if not 0 <= d <= 12:
                return False, "focus must be 0-12 dioptres"
            value = ("%g" % d)
        except ValueError:
            return False, f"bad focus {value!r}"
    _cam_state["focus"] = value
    try:
        with open(_CAM_FOCUS_FILE, "w") as f:
            f.write(value)
    except OSError:
        pass
    _cam_state["backend"], _cam_state["fails"] = _CAM_BACKEND, 0   # operator action: back on GStreamer
    if camera_off():
        return True, f"focus set to {cam_focus_label()} (camera is off — applies at Camera on)"
    _cam_kill()
    _cam_state["fails"] = 0
    time.sleep(1.0)      # libcamera releases the sensor a beat after the process exits
    ok = _cam_ensure()
    return ok, (f"camera restarting with {cam_focus_label()} (~2 s)" if ok
                else "focus: capture did not restart")


def _cam_apply(msg):
    """Persist current opts and restart the capture with them."""
    try:
        with open(_CAM_OPTS_FILE, "w") as f:
            json.dump({k: _cam_state[k] for k in ("w", "h", "fps", "enc")}, f)
    except OSError:
        pass
    _cam_state["backend"], _cam_state["fails"] = _CAM_BACKEND, 0
    if camera_off():
        return True, f"{msg} (camera is off — applies at Camera on)"
    _cam_kill()
    _cam_state["fails"] = 0
    time.sleep(1.0)
    ok = _cam_ensure()
    return ok, (f"camera restarting: {msg} (~2 s)" if ok
                else f"{msg} — capture did not restart")


def camera_opt(kind, value):
    """kind: 'res' (WxH preset), 'fps' (preset), 'enc' (sw|hw)."""
    if kind == "res":
        if value not in CAM_RES_PRESETS:
            return False, f"resolution must be one of {', '.join(CAM_RES_PRESETS)}"
        w, h = (int(v) for v in value.split("x"))
        _cam_state["w"], _cam_state["h"] = w, h
        return _cam_apply(f"resolution {value}")
    if kind == "fps":
        try:
            fps = int(value)
        except ValueError:
            return False, "bad framerate"
        if fps not in CAM_FPS_PRESETS:
            return False, f"framerate must be one of {CAM_FPS_PRESETS}"
        _cam_state["fps"] = fps
        return _cam_apply(f"{fps} fps")
    if kind == "enc":
        if value not in ("sw", "hw"):
            return False, "encoder must be sw or hw"
        _cam_state["enc"] = value
        return _cam_apply("software JPEG (q70, sharper, more CPU)" if value == "sw"
                          else "hardware JPEG (low CPU, bigger frames)")
    return False, f"unknown camera option {kind!r}"


def camera_refocus():
    """Refocus = fresh continuous-AF scan (auto policy). libcamerasrc ignores AF
    changes once playing and V4L2 lens pokes are overridden, but every capture
    start runs a full scan (verified lens 591->434->582->591), so: restart."""
    return camera_focus("auto")


def cam_backend():
    """'gst:sw' / 'gst:hw' / 'rpicam' for the status strip."""
    b = _cam_state["backend"]
    return ((f"gst:{_cam_state['enc']}" if b == "gst" else b)
            + f" {_cam_state['w']}x{_cam_state['h']}@{_cam_state['fps']}"
            + " · " + cam_focus_label())


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
                cv = _cam.get("cv")
                if cv is not None:
                    with cv:
                        cv.notify_all()   # wake MJPEG streamers (2026-09-01)
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
        # GStreamer fallback bookkeeping (2026-09-01): an early death counts —
        # unless the dashboard stopped it on purpose (Camera off / Refocus / preset)
        if _cam_state["backend"] == "gst" and not camera_off() and not getattr(proc, "_cj_deliberate", False):
            if time.time() - getattr(proc, "_cj_started", _cam_state["started"]) < 10:
                _cam_state["fails"] += 1
                if _cam_state["fails"] >= 3:
                    _cam_state["backend"] = "rpicam"
                    print("[cam] GStreamer pipeline died twice — rpicam-vid for this session", flush=True)
            else:
                _cam_state["fails"] = 0


def _cam_ensure() -> bool:
    """Start rpicam-vid if it is not running (and the camera is not switched
    off). Returns False when it could not be started."""
    if camera_off():
        return False
    with _cam["lock"]:
        if _cam["proc"] is None or _cam["proc"].poll() is not None:
            try:
                cmd = _cam_cmd()
                _cam_reap_strays()
                try:
                    errf = open(_CAM_LOG, "ab", buffering=0)
                except OSError:
                    errf = subprocess.DEVNULL
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE,
                                     stderr=errf)
                p._cj_started = time.time()
                p._cj_deliberate = False
                _cam["proc"] = p
                _cam_state["started"] = p._cj_started
                print(f"[cam] started {cmd[0]} ({cam_backend()})", flush=True)
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
        time.sleep(2)   # 2026-09-01: was 5 — a failed hand-off after Refocus recovers sooner


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


def avatar_view():
    """framed (9:10 portrait, the original exhibit look), wide (16:9 window,
    whole frame) or full (edge to edge)."""
    try:
        v = open(AVATAR_VIEW_FILE).read().strip()
    except OSError:
        return "framed"
    return v if v in AVATAR_VIEWS else "framed"


_av_conf_cache = {"key": None, "doc": None}


def avatar_conf_view():
    """Which LiveAvatar avatar the next session will use, for the /maintain
    card. File reads only, re-done when either file changes — never a network
    call: state() runs on every page poll."""
    def _mt(p):
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0
    key = (_mt(LIVEAVATAR_CONF), _mt(LIVEAVATAR_CACHE))
    if _av_conf_cache["key"] != key:
        conf = _read_json(LIVEAVATAR_CONF) or {}
        aid = conf.get("avatar_id") or AVATAR_ID_DEFAULT
        doc = {"avatar_id": aid,
               "sandbox": bool(conf.get("sandbox", True)),
               "has_key": bool(conf.get("api_key")),
               "configured": bool(conf.get("avatar_id"))}
        cache = _read_json(LIVEAVATAR_CACHE) or {}
        if cache.get("id") == aid:
            for k in ("name", "preview_url", "status", "voice", "ts"):
                doc[k] = cache.get(k)
        _av_conf_cache.update({"key": key, "doc": doc})
    return _av_conf_cache["doc"]


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


def _volume_level():
    """Stored master level (0-100) from ~/.cj_volume, without running anything."""
    try:
        return max(0, min(100, int(open(os.path.expanduser("~/.cj_volume")).read().strip())))
    except (OSError, ValueError):
        return None


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


def _video_mute_on():
    """True while /dev/shm/cj_video_mute holds a future epoch (clip playing)."""
    try:
        return float(open("/dev/shm/cj_video_mute").read().strip() or 0) > time.time()
    except (OSError, ValueError):
        return False


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
        "avatar_conf": avatar_conf_view(),   # which avatar the next session opens with
        "avatar_view": avatar_view(),        # how big it sits on /face-avatar
        "avatar_cmd": _read_json(AVATAR_PAGE_CMD),
        "video_cmd": _read_json(VIDEO_PAGE_CMD),   # /maintain → page: play/stop a clip
        "wake_events": _tail_jsonl(WAKE_EVENTS, 12),
        "stop": _read_json(STOP_LIVE),
        "stop_events": _tail_jsonl(STOP_EVENTS, 12),
        "corrections": _tail_jsonl(POSTPROC_LOG, 20),
        "health": _health(),
        "audio_route": _audio_route(),
        "volume": _volume_level(),   # 2026-09-01 status-strip item (read from file, no subprocess)
        "camera_backend": cam_backend(),
        "camera_focus": _cam_state["focus"],   # "auto" or dioptres (slider sync)
        "camera_opts": {k: _cam_state[k] for k in ("w", "h", "fps", "enc")},
        "tempo_avg": (_read_json("/dev/shm/cj_tempo_avg.json") or {}).get("avg"),
        "has_last_answer": os.path.exists(LAST_ANSWER),
        "event_mode": os.path.exists(EVENT_FLAG),
        "camera_off": camera_off(),
        "muted": os.path.exists(MUTED_FLAG),
        "video_mute": _video_mute_on(),   # 2026-09-02 mode banner: mic muted while a clip plays
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


APP_ENV = os.path.join(MAIN, "app", ".env")   # the app's secrets + voice ids (loaded at app start)


def _env_value(name):
    """Read one key from the app's .env (server-side only, never sent out)."""
    try:
        with open(APP_ENV, encoding="utf-8") as f:
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

# ---------------------------------------------------------------------------
# video clips — uploaded from /maintain ("Video clips" card), played
# full-screen on the /face-avatar page (2026-09-02)
# ---------------------------------------------------------------------------
VIDEO_DIR = os.path.join(HOME, "videos")              # uploaded clip files
VIDEO_PAGE_CMD = "/dev/shm/cj_video_cmd.json"         # /maintain → page
VIDEO_MAX_BYTES = 1_500_000_000                       # 1.5 GB upload cap


def _video_page_cmd(cmd, name=None, audio=None):
    """Queue a play/stop command for the /face-avatar page (same relay shape
    as _avatar_page_cmd: the page applies any command newer than the last)."""
    doc = {"ts": time.time(), "cmd": cmd}
    if name:
        doc["name"] = name
    if audio:
        doc["audio"] = audio    # "robot" (ffmpeg|aplay on the Pi) or "page" (browser)
    tmp = f"{VIDEO_PAGE_CMD}.{threading.get_ident()}.tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f)
    os.replace(tmp, VIDEO_PAGE_CMD)


# Robot-speaker audio for a playing clip (2026-09-02, user: "make the video
# play the sound to the speaker"): the /face-avatar page plays the video MUTED
# and posts video-audio-go-<name> once buffered; the Pi then decodes the
# clip's audio track straight to aplay (default route = current speaker,
# same as the Replay button). ffmpeg|aplay exits by itself at clip end.
VIDEO_AUDIO = {"ff": None, "ap": None, "ap2": None, "name": None}
# 2026-09-02 picture/sound sync (user: "merge it well especially in the video"):
# the go request now BLOCKS until aplay has the output device set up (aplay -v
# dumps its params right before the write loop), then answers with lead_ms —
# how long the page should wait before starting the picture: the device's
# own latency (PipeWire ~0.1 s, Bluetooth A2DP ~0.3 s) plus an operator
# offset kept in VIDEO_LEAD_FILE (ms, may be negative; /maintain "Sync" box).
VIDEO_LEAD_FILE = os.path.join(HOME, ".cj_video_lead")
VIDEO_LEAD_BASE = {"internal": 120, "bluetooth": 320}
# 2026-09-02 (user: "make sure the video clip also has audio through the
# bluetooth reachy is connected to"): a Bluetooth speaker does NOT start
# playing the instant aplay opens the pcm — BlueALSA fills a 0.5 s buffer and
# the speaker's amp wakes on the first frames, so the clip's opening word is
# swallowed and the operator hears silence. Feed the stream that much digital
# silence FIRST (ffmpeg adelay), and hold the picture back by the same amount
# so sound and picture still land together.
VIDEO_PRIME_MS = {"internal": 0, "bluetooth": 700}
# 2026-09-02 (user: "audio is not playing" — during the event): the route was
# fine; the uploaded clip's own audio track was simply far too quiet to hear
# (Avatar Video_1080p (3).mp4 measured mean -38.6 dBFS, PEAK -20.1 dBFS, i.e.
# ~10x below normal speech) so on a Bluetooth speaker in a loud hall it
# vanished under the room. Every clip is now peak-normalised to -1 dBFS
# before it is sent to the speaker; the measurement (ffmpeg volumedetect,
# ~1.5 s) runs when Play is pressed and is cached per file+mtime, so the
# picture never waits for it. Extra operator trim in dB: ~/.cj_video_gain.
VIDEO_GAIN = {}                                        # (path, mtime) -> dB
VIDEO_GAIN_FILE = os.path.join(HOME, ".cj_video_gain")  # operator trim, dB
VIDEO_GAIN_MAX = 26.0
VIDEO_GAIN_FALLBACK = 12.0     # not measured yet: boost + limiter instead


def video_gain_trim():
    try:
        return max(-20.0, min(20.0, float(open(VIDEO_GAIN_FILE).read().strip())))
    except (OSError, ValueError):
        return 0.0


def _video_gain_db(fp, measure=True):
    """dB of gain that brings this clip's peak to -1 dBFS (0 when unknown)."""
    try:
        key = (fp, os.path.getmtime(fp))
    except OSError:
        return None
    if key in VIDEO_GAIN:
        return VIDEO_GAIN[key]
    if not measure:
        return None
    peak = None
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-i", fp, "-vn",
                              "-af", "volumedetect", "-f", "null", "-"],
                             capture_output=True, text=True, timeout=45).stderr
        m = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB", out)
        if m:
            peak = float(m.group(1))
    except (OSError, subprocess.TimeoutExpired):
        pass
    if peak is None:
        return None
    VIDEO_GAIN[key] = max(0.0, min(VIDEO_GAIN_MAX, -1.0 - peak))
    return VIDEO_GAIN[key]


def _video_route_bt():
    try:
        return "bluealsa" in open(os.path.expanduser("~/.asoundrc.route")).read()
    except OSError:
        return False


def _video_route_dual():
    try:
        m = re.search(r"^# Secondary: (\S+)", open(os.path.expanduser("~/.asoundrc.route")).read(), re.M)
        return bool(m) and m.group(1) != "none"
    except OSError:
        return False


def _video_route_primary():
    """('internal'|MAC, label) for the output NEW playback streams open on —
    i.e. the speaker the robot is connected to right now. ~/bin/audio-out
    writes both header lines into ~/.asoundrc.route."""
    tgt = "internal"
    try:
        m = re.search(r"^# Primary: (\S+)",
                      open(os.path.expanduser("~/.asoundrc.route")).read(), re.M)
        if m:
            tgt = m.group(1)
    except OSError:
        pass
    label = _audio_route() or ("internal speaker" if tgt == "internal" else tgt)
    label = re.sub(r"\s*\([0-9A-Fa-f:]{17}\)", "", label).strip()   # drop the MAC
    return tgt, label


def _bt_connected(mac):
    try:
        out = subprocess.run(["bluetoothctl", "info", mac],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "Connected: yes" in out


def video_route_warm(reconnect=True):
    """(link_ok, label) for the routed speaker, having first tried to bring a
    dropped Bluetooth link back. A2DP goes silent the moment the speaker drops
    off and ALSA only notices when aplay opens the pcm, so reconnect first —
    but the answer is advisory only: aplay, not bluetoothctl, decides whether
    a clip plays (a slow/busy bluetoothctl must never veto a working speaker)."""
    tgt, label = _video_route_primary()
    if tgt == "internal" or ":" not in tgt:
        return True, label
    if _bt_connected(tgt):
        return True, label
    if reconnect:
        try:
            subprocess.run(["bluetoothctl", "connect", tgt],
                           capture_output=True, text=True, timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            pass
        if _bt_connected(tgt):
            return True, label
    return False, label


def video_lead_offset():
    try:
        return int(float(open(VIDEO_LEAD_FILE).read().strip()))
    except (OSError, ValueError):
        return 0


def video_prime_ms():
    """Silence written to the speaker ahead of the clip's own audio."""
    return VIDEO_PRIME_MS["bluetooth" if _video_route_bt() else "internal"]


def video_lead_ms():
    bt = _video_route_bt()
    base = VIDEO_LEAD_BASE["bluetooth" if bt else "internal"] + video_prime_ms()
    return base, max(-2000, min(3000, base + video_lead_offset()))
VIDEO_MUTE_FLAG = "/dev/shm/cj_video_mute"   # clip playing until <epoch> — the
# voice app treats it as mic mute so the robot cannot wake on the clip's own
# voice (2026-09-02, user: "why is it always speaking" — it answered the video)


def _video_mute_set(name):
    """Flag the mic muted until the clip ends (+3 s room tail). ffprobe gives
    the duration; if it cannot, cap at 15 min so the flag always self-expires."""
    fp = _video_path(name)
    dur = 900.0
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", fp], capture_output=True, text=True, timeout=6).stdout.strip()
        dur = min(float(out), 3600.0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    with open(VIDEO_MUTE_FLAG, "w") as f:
        f.write(f"{time.time() + dur + 3.0:.1f}")


def _video_mute_clear():
    try:
        os.unlink(VIDEO_MUTE_FLAG)
    except OSError:
        pass


def _video_audio_stop():
    ff, ap, ap2 = VIDEO_AUDIO["ff"], VIDEO_AUDIO["ap"], VIDEO_AUDIO["ap2"]
    VIDEO_AUDIO.update(ff=None, ap=None, ap2=None, name=None)
    for p in (ff, ap, ap2):
        if p is not None and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass


def _video_audio_start(name):
    fp = _video_path(name)
    if not fp:
        return False, f"no such video {name!r}"
    # 2026-09-02 (user: "make sure the video speaks towards the speaker reachy
    # mini is connected to" / "make it work through the bluetooth speakers,
    # especially C41"): aplay's default device follows pcm.audio_out_route, so
    # the clip always lands on the CURRENT route. On a Bluetooth route the link
    # may have dropped since the last clip — pull it back up first, then play
    # regardless: aplay's own open is the real verdict.
    link_ok, route_label = video_route_warm()
    _video_audio_stop()
    t0 = time.monotonic()
    try:
        prime = video_prime_ms()
        gain = _video_gain_db(fp, measure=False)        # measured when Play was pressed
        trim = video_gain_trim()
        chain = []
        if prime:
            chain.append(f"adelay={prime}|{prime}")
        if gain is None:                                # not measured yet: boost + limit
            gain_txt = f"+{VIDEO_GAIN_FALLBACK + trim:.1f} dB (unmeasured)"
            chain += [f"volume={VIDEO_GAIN_FALLBACK + trim:.1f}dB", "alimiter=limit=0.9"]
        elif gain + trim:
            gain_txt = f"+{gain + trim:.1f} dB (peak-normalised)"
            chain += [f"volume={gain + trim:.1f}dB", "alimiter=limit=0.95"]
        else:
            gain_txt = "no boost needed"
        ff = subprocess.Popen(
            ["ffmpeg", "-v", "quiet", "-i", fp, "-vn"]
            + (["-af", ",".join(chain)] if chain else [])
            + ["-f", "wav", "-ar", "48000", "-ac", "2", "-"],
            stdout=subprocess.PIPE)
        # -v: aplay dumps hw/sw params (last line "boundary") right before it
        # starts writing — our "device is set up" signal for the page.
        ap = subprocess.Popen(["aplay", "-v", "-t", "wav", "-"], stdin=subprocess.PIPE,
                              stderr=subprocess.PIPE)
        ap2 = None
        if _video_route_dual():           # dual route: same sound on the second device
            try:
                ap2 = subprocess.Popen(["aplay", "-q", "-t", "wav", "-D", "audio_out_route2", "-"],
                                       stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            except OSError:
                ap2 = None
        ready = threading.Event()
        errlines = []                      # aplay's last words, for a failed open

        def _stderr_watch(ap=ap):
            try:
                for raw in ap.stderr:
                    if b"boundary" in raw:
                        ready.set()
                    else:
                        line = raw.decode("utf-8", "replace").strip()
                        if line:
                            errlines.append(line)
                            del errlines[:-6]
            except Exception:
                pass
            ready.set()                    # EOF/failure: never leave the page waiting
        threading.Thread(target=_stderr_watch, daemon=True).start()

        def _tee(ff=ff, sinks=[p for p in (ap, ap2) if p is not None]):
            live = list(sinks)
            try:
                while live:
                    chunk = ff.stdout.read(32768)
                    if not chunk:
                        break
                    for p in list(live):
                        try:
                            p.stdin.write(chunk)
                        except (BrokenPipeError, OSError):
                            live.remove(p)
            finally:
                for p in sinks:
                    try:
                        p.stdin.close()
                    except OSError:
                        pass
                if ff.poll() is None:
                    try:
                        ff.kill()
                    except OSError:
                        pass
        threading.Thread(target=_tee, daemon=True).start()
        VIDEO_AUDIO.update(ff=ff, ap=ap, ap2=ap2, name=name)

        def _wait_reap(ap=ap, ff=ff, ap2=ap2):
            ap.wait(); ff.wait()
            if ap2 is not None:
                ap2.wait()
            if VIDEO_AUDIO["ap"] is ap:          # not superseded by a newer clip
                _video_mute_clear()              # mic re-arms ~3 s early
        threading.Thread(target=_wait_reap, daemon=True).start()
        ready.wait(3.0)
        if ap.poll() is not None:          # device never opened: the clip would be silent
            tail = "; ".join(l for l in errlines if not l.startswith(("Playing", "  ")))[:180]
            _video_audio_stop()
            _video_mute_clear()
            why = "" if link_ok else " (Bluetooth link is down — power the speaker on / reconnect it)"
            return False, f"clip audio failed on {route_label}{why}: {tail or 'aplay exited'}"
        setup_ms = int((time.monotonic() - t0) * 1000)
        base, lead = video_lead_ms()
        where = route_label + (" + second output" if ap2 is not None else "")
        return True, {"output": f"clip audio -> {where} ({name}); device ready in {setup_ms} ms, "
                                f"{prime} ms silence primed, {gain_txt}, picture lead {lead} ms",
                      "where": where, "lead_ms": lead, "lead_base_ms": base,
                      "setup_ms": setup_ms}
    except OSError as e:
        _video_audio_stop()
        return False, f"clip audio failed: {e}"


def _video_path(name):
    """VIDEO_DIR path for a stored clip, or None for a bad/unknown name."""
    if not name or "/" in name or name.startswith("."):
        return None
    fp = os.path.join(VIDEO_DIR, name)
    return fp if os.path.isfile(fp) else None


def videos_list():
    try:
        return [{"name": n, "size": os.path.getsize(os.path.join(VIDEO_DIR, n))}
                for n in sorted(os.listdir(VIDEO_DIR))
                if not n.startswith(".")
                and os.path.isfile(os.path.join(VIDEO_DIR, n))]
    except OSError:
        return []


def video_upload(h, params):
    """Raw-body upload (POST /api/video-upload?key=&name=) streamed to
    VIDEO_DIR in 1 MB chunks — a 1080p mp4 never sits whole in RAM."""
    from urllib.parse import unquote
    name = re.sub(r"[^A-Za-z0-9._ ()-]+", "_",
                  unquote(params.get("name", ""))).strip().lstrip(".")
    if not name:
        name = "clip.mp4"
    try:
        n = int(h.headers.get("Content-Length", 0))
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return False, "empty upload"
    if n > VIDEO_MAX_BYTES:
        return False, f"file too large ({n / 1e9:.1f} GB > 1.5 GB cap)"
    os.makedirs(VIDEO_DIR, exist_ok=True)
    tmp = os.path.join(VIDEO_DIR, "." + name + ".part")
    try:
        left = n
        with open(tmp, "wb") as f:
            while left > 0:
                chunk = h.rfile.read(min(1 << 20, left))
                if not chunk:
                    raise OSError("connection dropped mid-upload")
                f.write(chunk)
                left -= len(chunk)
        os.replace(tmp, os.path.join(VIDEO_DIR, name))
        return True, f"{name} uploaded ({n / 1e6:.1f} MB)"
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        h.close_connection = True   # body may be half-read on a keep-alive socket
        return False, str(e)


def serve_video(h, raw_name):
    """GET /api/video?name= — streams a stored clip with single-Range support
    (Chromium wants Accept-Ranges/206 for seeking in <video>)."""
    from urllib.parse import unquote
    fp = _video_path(unquote(raw_name))
    if not fp:
        h._send(404, json.dumps({"error": "no such video"}))
        return
    low = fp.lower()
    ctype = ("video/mp4" if low.endswith((".mp4", ".m4v", ".mov"))
             else "video/webm" if low.endswith(".webm")
             else "application/octet-stream")
    size = os.path.getsize(fp)
    start, end, partial = 0, size - 1, False
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", h.headers.get("Range") or "")
    if m and (m.group(1) or m.group(2)):
        partial = True
        if m.group(1):
            start = int(m.group(1))
            if m.group(2):
                end = min(int(m.group(2)), size - 1)
        else:                                   # suffix range: bytes=-N
            start = max(0, size - int(m.group(2)))
        if start > end or start >= size:
            h._send(416, json.dumps({"error": "bad range"}))
            return
    try:
        h.send_response(206 if partial else 200)
        h.send_header("Content-Type", ctype)
        h.send_header("Accept-Ranges", "bytes")
        # 2026-09-02 event: with no cache headers the display browser re-pulled
        # the whole clip over the event WiFi on EVERY play (33 MB ≈ 11-14 s of
        # black screen before the sound could start). The name+size+mtime tag
        # lets it reuse what it already has; a re-uploaded clip changes the tag.
        try:
            h.send_header("ETag", f'"{size}-{int(os.path.getmtime(fp))}"')
        except OSError:
            pass
        h.send_header("Cache-Control", "public, max-age=86400")
        if partial:
            h.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        h.send_header("Content-Length", str(end - start + 1))
        h.end_headers()
        with open(fp, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(65536, left))
                if not chunk:
                    break
                h.wfile.write(chunk)
                left -= len(chunk)
    except (BrokenPipeError, ConnectionResetError, OSError):
        h.close_connection = True   # partial body on a keep-alive socket


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
            # keep null a null: lag is null until the page has measured one,
            # and str(None) would reach the card as the text "None"
            doc[k] = v if v is None or isinstance(v, (bool, int, float)) else str(v)[:200]
    tmp = f"{AVATAR_PAGE_STATUS}.{threading.get_ident()}.tmp"   # per-thread: posts overlap
    with open(tmp, "w") as f:
        json.dump(doc, f)
    os.replace(tmp, AVATAR_PAGE_STATUS)
    return True, "ok"


# ---- Manual actions card (2026-08-26): operator tuning without SSH ---------
TUNING_CONF = "/etc/systemd/system/supervaise.service.d/wakeword.conf"
TUNING_KNOBS = {   # field -> (env var, min, max, label)
    "wake":   ("CJ_WAKE_OWW_THRESHOLD",     0.001, 1.0,  "wake threshold"),  # floor 0.01->0.001 2026-09-02 (threshold 0.005 in use)
    "stop":   ("CJ_STOP_OWW_THRESHOLD",     0.001, 1.0,  "stop threshold"),
    "listen": ("CJ_MIC_TRAILING_SILENCE_S", 0.3,   10.0, "listen time (s)"),
    "pace":   ("CJ_TEMPO_RATE_MAX",         8.0,   25.0, "pace ceiling (chars/s)"),
    "length": ("CJ_MAX_WORDS",              30,    150,  "answer length (max words)"),
}
BT_MACS = {"c41": "66:EA:C5:C3:E5:6B", "sony": "50:1B:6A:8B:16:F2", "marshall": "04:21:44:84:1F:C1"}


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
            # 2026-09-10: the listening knobs moved to config/modes/*.json and
            # the operator console; a value written back here would override
            # the profile for every mode, so the card refuses instead.
            return False, f"{lbl}: now set on /console (mode profile) — not in wakeword.conf"
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


VOLUME_BIN = os.path.join(HOME, "bin", "audio-volume")   # 2026-09-01 master level

try:   # 2026-09-01 live mic meter (/maintain): arecord on the shared dsnoop + XVF3800 channel-R pick
    from mic_meter import mic_get, mic_set, mic_status
except Exception as _e:   # pragma: no cover
    print(f"[ui] mic_meter unavailable: {_e}", flush=True)
    def mic_get(): return {"on": False, "error": "mic_meter unavailable"}
    def mic_set(body): return False, "mic_meter unavailable"
    def mic_status(): return {"on": False, "source": None}


def volume_get():
    """{'level': 0-100, 'applied': 'internal' | 'bt:MAC' | 'none', 'route': …}."""
    try:
        r = subprocess.run([VOLUME_BIN, "get"], capture_output=True, text=True, timeout=8)
        d = json.loads(r.stdout.strip() or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        d = {"level": None, "applied": "error: " + str(e)[:80]}
    d["route"] = _audio_route()
    return d


def volume_set(level):
    try:
        lvl = max(0, min(100, int(float(level))))
    except (TypeError, ValueError):
        return False, "bad level"
    try:
        r = subprocess.run([VOLUME_BIN, "set", str(lvl)], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"audio-volume failed: {e}"
    out = (r.stdout + r.stderr).strip()[-160:]
    return r.returncode == 0, out or f"volume {lvl}%"


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
    if action == "audio-console":   # 2026-09-02: /maintain button -> ~/audio-ui.py console on :8090
        def _port_up():
            try:
                with socket.create_connection(("127.0.0.1", 8090), timeout=0.5):
                    return True
            except OSError:
                return False
        if _port_up():
            return True, "audio console already running on :8090"
        try:
            with open("/dev/shm/audio_ui.log", "ab") as log:
                subprocess.Popen(
                    ["python3", os.path.expanduser("~/audio-ui.py"), "--no-monitor"],
                    stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                    start_new_session=True)
        except OSError as e:
            return False, f"audio console failed to start: {e}"
        for _ in range(20):   # ~5 s for the device scan before the port opens
            time.sleep(0.25)
            if _port_up():
                return True, "audio console started on :8090 (--no-monitor — the robot keeps the mic)"
        return False, "audio console did not come up in 5 s — see /dev/shm/audio_ui.log"
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
    if action.startswith("avatar-view-"):
        v = action[len("avatar-view-"):]
        if v not in AVATAR_VIEWS:
            return False, "unknown avatar view " + v
        with open(AVATAR_VIEW_FILE, "w") as f:
            f.write(v)
        return True, {"framed": "avatar view: 9:10 portrait (16:9 source is cropped)",
                      "wide": "avatar view: 16:9 window — the whole frame",
                      "full": "avatar view: full screen"}[v]
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
    if action.startswith(("video-play-", "video-playlocal-")):
        local = action.startswith("video-playlocal-")   # sound on the page's device
        name = action[len("video-playlocal-" if local else "video-play-"):]
        if not _video_path(name):
            return False, f"no such video {name!r}"
        _video_audio_stop()          # switching clips: silence the old one now
        _video_mute_set(name)        # robot mic sleeps until the clip ends
        threading.Thread(target=_video_gain_db, args=(_video_path(name),),
                         daemon=True).start()   # loudness, ready before the go
        if local:
            _video_page_cmd("play", name, audio="page")
            return True, f"video: playing {name} on the face page (sound on the face-page device)"
        # Sound on the robot: normally the /face-avatar page asks for it
        # (video-audio-go) once it has the picture buffered — that request is
        # what keeps the two in step. With no such page live, only an exhibit /
        # audience screen is showing the clip and nobody would ever ask, so
        # start the sound here first and let the picture follow the next poll
        # (2026-09-02: otherwise an audience-only display played silently).
        av = _read_json(AVATAR_PAGE_STATUS) or {}
        try:
            face_live = (time.time() - float(av.get("ts") or 0)) < 10
        except (TypeError, ValueError):
            face_live = False
        if face_live:
            _video_page_cmd("play", name, audio="robot")
            _, route_label = _video_route_primary()
            return True, f"video: playing {name} on the face page (sound on {route_label})"
        ok_a, out_a = _video_audio_start(name)
        if not ok_a:
            _video_mute_clear()
            return False, out_a
        _video_page_cmd("play", name, audio="robot")
        return True, f"video: playing {name} (no face page — {out_a['output']})"
    if action.startswith("video-audio-go-"):
        # posted by the /face-avatar page once the muted video is buffered.
        # Idempotent: a second page (or a page reload) re-posting the same
        # clip must not restart the sound from 0.
        name = action[len("video-audio-go-"):]
        cmd = _read_json(VIDEO_PAGE_CMD) or {}
        if cmd.get("cmd") != "play" or cmd.get("name") != name or cmd.get("audio") != "robot":
            # Stop (or another clip) landed while the page was still buffering.
            # Without this the late go starts sound with no picture on screen —
            # and it plays on the robot speaker for the whole clip (2026-09-02).
            return False, f"clip {name!r} is no longer on air — sound not started"
        ap = VIDEO_AUDIO["ap"]
        if VIDEO_AUDIO["name"] == name and ap is not None and ap.poll() is None:
            return True, "clip audio already playing"
        return _video_audio_start(name)
    if action.startswith("video-lead-"):
        # operator sync offset (ms, +/-) added to the route's base picture lead
        try:
            v = int(float(action[len("video-lead-"):]))
        except ValueError:
            return False, "video-lead needs a number (ms)"
        v = max(-2000, min(2000, v))
        with open(VIDEO_LEAD_FILE, "w") as f:
            f.write(str(v))
        base, lead = video_lead_ms()
        return True, f"video sync offset {v:+d} ms (picture starts {lead} ms after the sound is sent on this route)"
    if action == "video-stop":
        _video_audio_stop()
        _video_mute_clear()          # mic re-arms right away
        _video_page_cmd("stop")
        return True, "video: stop sent to the face page"
    if action.startswith("video-delete-"):
        name = action[len("video-delete-"):]
        fp = _video_path(name)
        if not fp:
            return False, f"no such video {name!r}"
        os.unlink(fp)
        return True, f"video: {name} deleted"
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
    if action == "camera-refocus":
        return camera_refocus()
    if action.startswith("camera-focus-"):
        return camera_focus(action[len("camera-focus-"):])
    if action.startswith("camera-res-"):
        return camera_opt("res", action[len("camera-res-"):])
    if action.startswith("camera-fps-"):
        return camera_opt("fps", action[len("camera-fps-"):])
    if action.startswith("camera-enc-"):
        return camera_opt("enc", action[len("camera-enc-"):])
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


# ────────────────────────────────────────────────────────────────────────────
# Guest voice card (2026-09-12, user: "another UI for guest for easy putting
# the API key or accessing the elevenlabs voices for easy voice switching").
# The ElevenLabs key and the two voice ids live in app/.env: ELEVEN_API_KEY,
# ELEVEN_VOICE_ID (CJAP — Panganiban's cloned voice, read by voice/config.py
# at app start) and ELEVEN_HOST_VOICE_ID (GUEST — the Host robot; only the
# render scripts synthesise with it, app/personas.py). The key never reaches
# the browser: the card sees a 4-char hint. Writes are atomic rewrites of
# .env that keep comments and order.
# ────────────────────────────────────────────────────────────────────────────
ELEVEN_API = "https://api.elevenlabs.io"
VOICE_ID_RE = re.compile(r"^[A-Za-z0-9]{10,40}$")
ELEVEN_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{16,128}$")
_voices_cache = {"ts": 0.0, "key": None, "data": None}


def _env_set(pairs):
    """Rewrite KEY=value lines in app/.env (comments/order kept, missing keys
    appended, atomic replace). Returns the keys whose value changed."""
    try:
        with open(APP_ENV, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        lines = []
    todo, changed = dict(pairs), []
    for i, line in enumerate(lines):
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        k = line.split("=", 1)[0].strip()
        if k in todo:
            new = f"{k}={todo.pop(k)}"
            if new != line:
                lines[i] = new
                changed.append(k)
    for k, v in todo.items():
        lines.append(f"{k}={v}")
        changed.append(k)
    if not changed:
        return []
    tmp = APP_ENV + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    try:
        os.chmod(tmp, os.stat(APP_ENV).st_mode & 0o777)
    except OSError:
        pass
    os.replace(tmp, APP_ENV)
    return changed


def _eleven_get(path, key, timeout=10):
    """GET on the ElevenLabs API -> (ok, json_or_error_text)."""
    import urllib.request, urllib.error
    req = urllib.request.Request(ELEVEN_API + path, headers={"xi-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, json.load(r)
    except urllib.error.HTTPError as e:
        msg = ""
        try:
            d = json.load(e).get("detail")
            msg = d.get("message") if isinstance(d, dict) else str(d or "")
        except Exception:
            pass
        return False, f"HTTP {e.code}" + (f": {msg[:120]}" if msg else "")
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"[:160]


def _fetch_bytes(url, timeout=15, limit=8_000_000):
    import urllib.request
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read(limit)


def _voice_row(v):
    labels = v.get("labels") or {}
    return {"voice_id": v.get("voice_id"), "name": v.get("name") or v.get("voice_id"),
            "category": v.get("category") or "",
            "labels": ", ".join(str(labels[k]) for k in ("gender", "age", "accent", "description", "use_case")
                                if labels.get(k)),
            "preview_url": v.get("preview_url"),
            "description": (v.get("description") or "")[:160]}


def eleven_voices(refresh=False):
    """What the card shows: key hint, both voice ids, the account's voices
    (cached 5 min per key; cloned/professional voices first)."""
    key = _env_value("ELEVEN_API_KEY") or ""
    out = {"has_key": bool(key), "key_hint": ("\u2026" + key[-4:]) if key else "",
           "cjap_voice_id": _env_value("ELEVEN_VOICE_ID") or "",
           "host_voice_id": _env_value("ELEVEN_HOST_VOICE_ID") or "",
           "voices": [], "error": None}
    if not key:
        out["error"] = "no ELEVEN_API_KEY in app/.env \u2014 paste one below"
        return out
    c = _voices_cache
    if not refresh and c["data"] is not None and c["key"] == key and time.time() - c["ts"] < 300:
        out["voices"] = c["data"]
        return out
    ok, d = _eleven_get("/v1/voices?show_legacy=true", key)
    if not ok:
        out["error"] = f"ElevenLabs voices: {d}"
        out["voices"] = c["data"] if c["key"] == key and c["data"] else []
        return out
    rows = [_voice_row(v) for v in (d.get("voices") or []) if v.get("voice_id")]
    order = {"cloned": 0, "professional": 0, "generated": 1, "premade": 2}
    rows.sort(key=lambda r: (order.get(r["category"], 3), r["name"].lower()))
    c.update(ts=time.time(), key=key, data=rows)
    out["voices"] = rows
    return out


def _restart_app():
    threading.Thread(target=lambda: subprocess.run(
        ["sudo", "-n", "systemctl", "restart", "supervaise.service"], timeout=60),
        daemon=True).start()


def eleven_conf_set(body):
    """Operator pasted a key and/or picked a voice for a role on /maintain.
    Both are checked against ElevenLabs before app/.env is touched. A new key
    or a new CJAP voice restarts the voice app (it reads them at start); the
    GUEST voice is only read by the render scripts, so no restart."""
    api_key = str(body.get("api_key") or "").strip()
    role = str(body.get("role") or "").strip()
    voice_id = str(body.get("voice_id") or "").strip()
    pairs, notes = {}, []
    if api_key:
        if not ELEVEN_KEY_RE.match(api_key):
            return False, "that does not look like an ElevenLabs API key"
        ok, d = _eleven_get("/v1/user/subscription", api_key)
        if not ok:
            return False, f"key refused by ElevenLabs ({d})"
        pairs["ELEVEN_API_KEY"] = api_key
        notes.append(f"API key stored (tier {d.get('tier')}, "
                     f"{d.get('character_count')}/{d.get('character_limit')} characters used)")
    if role:
        if role not in ("host", "cjap"):
            return False, "role must be host (GUEST) or cjap"
        var = "ELEVEN_HOST_VOICE_ID" if role == "host" else "ELEVEN_VOICE_ID"
        label = "GUEST" if role == "host" else "CJAP"
        if not voice_id:
            if role == "cjap":
                return False, "CJAP always needs a voice \u2014 pick another one instead of clearing"
            pairs[var] = ""
            notes.append("GUEST voice cleared")
        else:
            if not VOICE_ID_RE.match(voice_id):
                return False, "that does not look like a voice id"
            key = pairs.get("ELEVEN_API_KEY") or _env_value("ELEVEN_API_KEY") or ""
            if not key:
                return False, "no API key stored \u2014 paste one first"
            ok, v = _eleven_get(f"/v1/voices/{voice_id}", key)
            if not ok:
                return False, f"voice {voice_id} is not on this account ({v})"
            pairs[var] = voice_id
            notes.append(f"{label} voice \u2192 {v.get('name') or voice_id} ({voice_id})")
    if not pairs:
        return False, "nothing to change"
    try:
        changed = _env_set(pairs)
    except OSError as e:
        return False, f"cannot write app/.env: {e}"
    if not changed:
        return True, "no change \u2014 already set"
    for c in (_eleven_cache, _prov_cache, _voices_cache):
        c["ts"] = 0.0
    if "ELEVEN_VOICE_ID" in changed or "ELEVEN_API_KEY" in changed:
        _restart_app()
        notes.append("voice app restarting (~25 s) so it picks up the change")
    return True, "; ".join(notes)


def eleven_voice_sample(voice_id):
    """The voice's ElevenLabs preview clip (free, no credits) -> (ok, mp3 bytes | error)."""
    voice_id = str(voice_id or "").strip()
    if not VOICE_ID_RE.match(voice_id):
        return False, "bad voice id"
    d = eleven_voices()
    v = next((x for x in d["voices"] if x["voice_id"] == voice_id), None)
    if v is None:
        return False, d.get("error") or "voice not in this account's list"
    if not v.get("preview_url"):
        return False, f"{v['name']} has no preview clip"
    try:
        return True, _fetch_bytes(v["preview_url"])
    except Exception as e:
        return False, f"preview download failed: {type(e).__name__}: {e}"[:160]
