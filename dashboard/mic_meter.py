"""Live microphone meter for /maintain (2026-09-01, user: "volume and wavelength
from the mic … the combined with filter and the raw of the 4 mic").

The Reachy Mini Audio card (XVF3800) exposes ONE stereo 16 kHz USB capture
stream. By default both channels carry the processed auto-selected beam
(AUDIO_MGR_OP_L/R = 8,0). Since 2026-09-01 the voice app reads channel L only
(~/.asoundrc reachymini_audio_src_left), so channel R is free: this module
points it at whatever the operator wants to see — an amplified raw mic
(category 3, index 0-3: the exact signal the chip's DSP receives), or the
AEC reference (12,0: what the chip is cancelling against — silent when a
Bluetooth speaker plays, which is the self-hearing problem in one picture).

arecord reads the dsnoop PCM (shared with the app) only while a page is
polling; 20 s without a poll stops the capture and puts channel R back to
the processed beam. Chip readings (beam energies, AEC converged, selected
azimuth) are refreshed once a second through ~/bin/xvf-ctl.
"""
import json
import math
import os
import re
import subprocess
import threading
import time
from collections import deque

try:
    import numpy as np
except ImportError:      # pragma: no cover - the Pi has numpy
    np = None

XVF = os.path.expanduser("~/bin/xvf-ctl")
DEV = "reachymini_audio_src"        # dsnoop, 2 ch: L = what CJ hears, R = pick
RATE = 16000
BLOCK = 320                         # 20 ms
HIST = 150                          # 3 s of (min, max) pairs per channel
IDLE_STOP_S = 20.0
PEAK_HOLD_S = 1.2

SOURCES = {                         # name -> (category, index) for AUDIO_MGR_OP_R
    "mic0": (3, 0), "mic1": (3, 1), "mic2": (3, 2), "mic3": (3, 3),
    "ref": (12, 0),                 # AEC reference as the DSP sees it (gain + system delay)
    "proc": (8, 0),                 # default: same processed beam as L
}
LABELS = {"mic0": "raw mic 0", "mic1": "raw mic 1", "mic2": "raw mic 2", "mic3": "raw mic 3",
          "ref": "AEC reference", "proc": "processed (same as L)"}

# connected microphones (2026-09-02, user: "microphone meter in connected
# microphone"): any OTHER capture-capable ALSA card — a USB mic, a webcam
# mic — can be picked for the R row. It is read by a second arecord on
# plughw:<card>,0 (plughw resamples to 16 kHz mono); the XVF chip's channel
# R goes back to the processed beam while an external pick is active.
_EXT_CACHE = {"ts": 0.0, "rows": []}


def ext_devices():
    now = time.monotonic()
    if now - _EXT_CACHE["ts"] < 5.0:
        return _EXT_CACHE["rows"]
    rows = []
    try:
        txt = open("/proc/asound/cards").read()
        for m in re.finditer(r"^\s*(\d+)\s+\[\S+\s*\]:\s+\S+\s*-\s*(.+)$", txt, re.M):
            n, name = int(m.group(1)), m.group(2).strip()
            if "Reachy Mini" in name:            # the array is already sources mic0-3
                continue
            if not os.path.isdir(f"/proc/asound/card{n}/pcm0c"):
                continue                          # playback-only (HDMI etc.)
            rows.append({"id": f"ext{n}", "card": n, "label": f"connected: {name}"})
    except OSError:
        pass
    _EXT_CACHE["ts"], _EXT_CACHE["rows"] = now, rows
    return rows


def _ext_row(source):
    return next((d for d in ext_devices() if d["id"] == source), None)
CHIP_PARAMS = ["AEC_SPENERGY_VALUES", "AEC_AECCONVERGED", "AUDIO_MGR_SELECTED_AZIMUTHS",
               "AUDIO_MGR_OP_R", "AUDIO_MGR_OP_L"]


def _xvf(*args, timeout=6):
    try:
        r = subprocess.run([XVF, *args], capture_output=True, text=True, timeout=timeout)
        line = [l for l in r.stdout.splitlines() if l.startswith("{")]
        return json.loads(line[-1]) if line else {"ok": False, "error": (r.stderr or r.stdout)[-160:]}
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": str(e)[:160]}


def _db(x):
    return round(20.0 * math.log10(max(x, 1.0) / 32768.0), 1)


class _Chan:
    def __init__(self):
        self.wave = deque(maxlen=HIST)
        self.rms_db = -90.0
        self.peak_db = -90.0
        self._peak_ts = 0.0

    def push(self, samples):
        lo = int(samples.min()); hi = int(samples.max())
        self.wave.append((lo * 100 // 32768, hi * 100 // 32768))
        rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
        self.rms_db = _db(rms)
        pk = _db(max(abs(lo), abs(hi)))
        now = time.monotonic()
        if pk >= self.peak_db or now - self._peak_ts > PEAK_HOLD_S:
            self.peak_db, self._peak_ts = pk, now

    def clear(self):
        self.wave.clear(); self.rms_db = self.peak_db = -90.0

    def snap(self):
        return {"rms_db": self.rms_db, "peak_db": self.peak_db, "wave": list(self.wave)}


class MicMeter:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.ext_proc = None            # second arecord for a connected mic
        self.ext_active = False         # True: R row is fed by ext_proc, not the chip
        self._ext_retry = 0.0           # last reopen attempt (2 s backoff on busy)
        self.source = "mic0"
        self.left = _Chan(); self.right = _Chan()
        self.chip = {}; self.chip_ts = 0.0
        self.last_poll = 0.0
        self.error = ""
        self.started = 0.0
        self._threads = []

    # ── lifecycle ──────────────────────────────────────────────────────
    def _alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        with self.lock:
            if self._alive():
                return True
            if np is None:
                self.error = "numpy missing"; return False
            try:
                self.proc = subprocess.Popen(
                    ["arecord", "-q", "-D", DEV, "-f", "S16_LE", "-c", "2", "-r", str(RATE), "-t", "raw"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
            except OSError as e:
                self.error = f"arecord: {e}"; return False
            self.error = ""; self.started = time.monotonic()
            self.left.clear(); self.right.clear()
            t1 = threading.Thread(target=self._reader, args=(self.proc,), daemon=True)
            t2 = threading.Thread(target=self._chip_loop, args=(self.proc,), daemon=True)
            self._threads = [t1, t2]; t1.start(); t2.start()
        op = SOURCES.get(self.source, (8, 0))   # ext pick: chip R stays on the beam
        r = _xvf("write", "AUDIO_MGR_OP_R", *map(str, op))
        if not r.get("ok"):
            self.error = "chip: " + str(r.get("error") or r)
        print(f"[mic-meter] started (R <- {self.source} {op})", flush=True)
        return True

    def stop(self, reason=""):
        self._ext_stop()
        with self.lock:
            p, self.proc = self.proc, None
        if p is not None:
            try:
                p.kill(); p.wait(timeout=3)
            except Exception:
                pass
            r = _xvf("write", "AUDIO_MGR_OP_R", "8", "0")   # leave the chip as found
            print(f"[mic-meter] stopped{(' — ' + reason) if reason else ''}; R restored "
                  f"({'ok' if r.get('ok') else r.get('error')})", flush=True)

    # ── workers ────────────────────────────────────────────────────────
    def _reader(self, p):
        need = BLOCK * 2 * 2
        buf = b""
        while p.poll() is None:
            chunk = p.stdout.read(need - len(buf))
            if not chunk:
                break
            buf += chunk
            if len(buf) < need:
                continue
            frames = np.frombuffer(buf, dtype=np.int16).reshape(-1, 2)
            buf = b""
            self.left.push(frames[:, 0])
            if not self.ext_active:
                self.right.push(frames[:, 1])
        if p.poll() is not None and p is self.proc:
            err = (p.stderr.read() or b"").decode(errors="ignore").strip()[-160:]
            self.error = f"arecord exited ({p.returncode}) {err}"
            print(f"[mic-meter] {self.error}", flush=True)

    def _chip_loop(self, p):
        while p.poll() is None and p is self.proc:
            r = _xvf("read", *CHIP_PARAMS)
            if r.get("ok"):
                en = r.get("AEC_SPENERGY_VALUES") or []
                az = r.get("AUDIO_MGR_SELECTED_AZIMUTHS") or []
                self.chip = {
                    "beam_energy": [round(float(x), 4) if x is not None else None for x in en],
                    "converged": bool((r.get("AEC_AECCONVERGED") or [0])[0]),
                    "azimuth_deg": [round(math.degrees(a)) if a is not None else None for a in az],
                    "op_l": r.get("AUDIO_MGR_OP_L"), "op_r": r.get("AUDIO_MGR_OP_R"),
                }
                self.chip_ts = time.time()
            if time.monotonic() - self.last_poll > IDLE_STOP_S:
                self.stop("no page polling"); return
            time.sleep(1.0)

    # ── connected-mic capture ──────────────────────────────────────────
    def _ext_stop(self):
        with self.lock:
            p, self.ext_proc = self.ext_proc, None
            self.ext_active = False
        if p is not None:
            try:
                p.kill(); p.wait(timeout=3)
            except Exception:
                pass

    def _ext_start(self, card):
        self._ext_stop()
        try:
            p = subprocess.Popen(
                ["arecord", "-q", "-D", f"plughw:{card},0", "-f", "S16_LE",
                 "-c", "1", "-r", str(RATE), "-t", "raw"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        except OSError as e:
            self.error = f"arecord ext: {e}"; return False
        with self.lock:
            self.ext_proc, self.ext_active = p, True
        threading.Thread(target=self._ext_reader, args=(p,), daemon=True).start()
        print(f"[mic-meter] connected mic on (plughw:{card},0)", flush=True)
        return True

    def _ext_reader(self, p):
        need = BLOCK * 2                       # mono S16
        buf = b""
        while p.poll() is None:
            chunk = p.stdout.read(need - len(buf))
            if not chunk:
                break
            buf += chunk
            if len(buf) < need:
                continue
            samples = np.frombuffer(buf, dtype=np.int16)
            buf = b""
            if p is self.ext_proc:
                self.right.push(samples)
        if p.poll() is not None and p is self.ext_proc:
            err = (p.stderr.read() or b"").decode(errors="ignore").strip()[-160:]
            if "busy" in err:
                err += " — is the audio-ui console (port 8090) holding this mic?"
            self.error = f"connected mic exited ({p.returncode}) {err}"
            self.right.clear()          # drop the frozen last level/wave
            print(f"[mic-meter] {self.error}", flush=True)

    # ── API ────────────────────────────────────────────────────────────
    def select(self, source):
        if source == "off":
            self.stop("operator"); return True, "meter off"
        ext = _ext_row(source)
        if source not in SOURCES and not ext:
            return False, "unknown source"
        self.source = source
        self.right.clear()
        self.last_poll = time.monotonic()
        if ext:
            if not self._alive():
                self.start()               # keeps the L row + chip readings
            else:
                _xvf("write", "AUDIO_MGR_OP_R", "8", "0")   # chip R back to the beam
            if not self._ext_start(ext["card"]):
                return False, self.error
            return True, f"R <- {ext['label']} (plughw:{ext['card']},0)"
        self._ext_stop()                   # back to a chip source
        if not self._alive():
            self.start()
        else:
            r = _xvf("write", "AUDIO_MGR_OP_R", *map(str, SOURCES[source]))
            if not r.get("ok"):
                return False, "chip write failed: " + str(r.get("error") or r)
        return True, f"R <- {LABELS[source]} {SOURCES[source]}"

    def snapshot(self):
        self.last_poll = time.monotonic()
        if not self._alive():
            self.start()
        ext = _ext_row(self.source)
        if ext and (self.ext_proc is None or self.ext_proc.poll() is not None) \
                and time.monotonic() - self._ext_retry > 2.0:
            self._ext_retry = time.monotonic()
            self._ext_start(ext["card"])   # picked mic re-plugged or died: retry
        return {
            "on": self._alive(), "error": self.error, "source": self.source,
            "label": ext["label"] if ext else LABELS[self.source],
            "op": SOURCES.get(self.source),
            "sources": [{"id": k, "label": LABELS[k]} for k in SOURCES] + ext_devices(),
            "proc": self.left.snap(), "pick": self.right.snap(),
            "chip": self.chip, "chip_age_s": round(time.time() - self.chip_ts, 1) if self.chip_ts else None,
            "uptime_s": round(time.monotonic() - self.started, 1) if self._alive() else 0,
            "hist_ms": HIST * BLOCK * 1000 // RATE,
        }


METER = MicMeter()


def mic_get():
    return METER.snapshot()


def mic_set(body):
    return METER.select(str((body or {}).get("source", "")))


def mic_status():
    """Cheap status-strip item (no side effects)."""
    return {"on": METER._alive(), "source": METER.source if METER._alive() else None}
