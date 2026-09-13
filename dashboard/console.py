#!/usr/bin/env python3
"""Operator console core for the two-robot installation (2026-09-10).

Served by the maintenance dashboard (ui_server.py, port 8080) at /console;
this module is the whole model — the page and the routes are thin.

THE ONE INVARIANT — exactly one microphone open at a time.
    The floor is a single value: "alpha" | "beta" | "none". A robot may open
    its mic only while it holds a fresh lease on the floor (see
    app/floor_lease.py). Because the floor is one scalar, "both open" cannot
    be expressed at all — there is no per-robot toggle anywhere.

Lease, not flag:
    The console holds the value. Robots POST /api/lease about once a second
    with what their mic is ACTUALLY doing (`observed`) and receive the floor
    plus a TTL (3 s). A robot that stops hearing from us closes its mic when
    the TTL runs out; a robot that has never heard from us (fresh boot) has
    nothing to hold. Fail closed everywhere.

Close both, wait, then open:
    Moving the floor to a robot first sets it to "none" (every lease reply
    now revokes), then waits until BOTH robots have reported their mic
    closed after the move began — or the TTL plus a margin has elapsed, so
    an unreachable robot has certainly expired — and only then names the
    target. Never open-then-close.

Drain, don't interrupt:
    A floor or mode change that arrives while a robot reports a turn in
    progress is queued and applied when the turn ends. The operator can
    "cut short": the console bumps that robot's `interrupt_seq`, which the
    robot honours by cutting playback / abandoning capture, and the queued
    change applies at once.

Config resolution (per key, later wins):
    config/modes/<mode>.json defaults -> its profiles[<profile>]
    -> /etc/systemd/system/supervaise.service.d/wakeword.conf (Environment=)
    -> app/.env -> console override.
    The effective set (with the source of every value) is journaled and
    printed on every change and sent to the robots inside the lease reply.

Stdlib only; injectable clock and paths so tests/test_floor_lease.py can
drive it deterministically.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque

FLOORS = ("alpha", "beta", "none")
ROBOTS = ("alpha", "beta")      # the two SLOTS (machine identities, by hostname)
ROLES = ("cjap", "host")        # personas; cjap_is names the slot that is Panganiban
MODES = ("duet", "direct")
PROFILES = ("kiosk", "event")

TTL_S = 3.0             # lease TTL handed to the robots (they cap at 3 s too)
SETTLE_MARGIN_S = 0.5   # extra wait after TTL before a new holder is named
OBS_FRESH_S = 3.0       # a robot report older than this is "unknown"
TURN_FRESH_S = 5.0      # turn_active older than this no longer blocks a change
RMS_WARN_MARGIN = 400   # speech threshold this close to the room floor = warn
CALIB_DEFAULT_S = 120   # room calibration sample length
CALIB_HEADROOM = 400    # proposed floor = p95 of per-second peaks + this
JOURNAL_KEEP = 400

HOME = os.path.expanduser("~")
MAIN = os.path.join(HOME, "Supervaise-Reachy-Mini-Project-main")
MODES_DIR = os.path.join(MAIN, "config", "modes")
DROPIN_PATH = "/etc/systemd/system/supervaise.service.d/wakeword.conf"
DOTENV_PATH = os.path.join(MAIN, "app", ".env")
ROBOTS_PATH = os.path.join(MAIN, "config", "robots.json")
DUET_SCRIPT_PATH = os.path.join(MAIN, "corpus", "voice", "duet_script.json")
DUET_LOOP_GAP_S = 6.0      # silence between the end of the exchange and its restart
STATE_PATH = os.path.join(HOME, ".cj_console_state.json")
JOURNAL_PATH = os.path.join(HOME, ".cj_console_journal.jsonl")

# Tunables. `env` is the variable the robot applies; `ui` = editable from the
# console; the rest ride with the profile. Labels are for a technician in a
# dim room — no jargon.
SETTINGS = {
    "wake_word":            {"type": "bool",  "env": "CJ_WAKE_LISTEN", "ui": True,
                             "label": "Answer to “Hi Cee-Jap”",
                             "help": "On: a question starts with the wake phrase (kiosk). Off: any speech on the open mic starts a question — the visitor's handheld transmitter (event)."},
    "wake_threshold":       {"type": "float", "env": "CJ_WAKE_OWW_THRESHOLD", "ui": True,
                             "min": 0.0005, "max": 0.9, "step": 0.001,
                             "label": "How sure before it wakes",
                             "help": "Lower wakes more easily (and on more noise). Real callers score 0.010–0.056."},
    "speech_threshold":     {"type": "int",   "env": "CJ_MIC_RMS_FLOOR", "ui": True,
                             "min": 50, "max": 5000, "step": 10,
                             "label": "Loudness that counts as talking",
                             "help": "Room noise below this is ignored. Must sit well above the room level."},
    "speech_threshold_mult": {"type": "float", "env": "CJ_MIC_RMS_MULT", "ui": False},
    "speech_threshold_cap": {"type": "int",   "env": "CJ_MIC_RMS_CAP", "ui": False},
    "silence_timeout_s":    {"type": "float", "env": "CJ_MIC_TRAILING_SILENCE_S", "ui": True,
                             "min": 0.3, "max": 10, "step": 0.1,
                             "label": "Pause that ends a question (seconds)",
                             "help": "Longer tolerates mid-question pauses; every answer starts that much later."},
    "post_answer_window_s": {"type": "float", "env": "CJ_LISTEN_IDLE_S", "ui": True,
                             "min": 0, "max": 120, "step": 1,
                             "label": "Keep listening after an answer (seconds)",
                             "help": "0: back to sleep right after each answer."},
    "host_intro":           {"type": "bool",  "env": "CJ_HOST_INTRO", "ui": True,
                             "label": "Host says the intro line",
                             "help": "Spoken once by the Host robot when direct mode starts."},
    "dry_run":              {"type": "bool",  "env": "CJ_DRY_RUN", "ui": True,
                             "label": "Rehearse silently",
                             "help": "Everything runs, nothing is played through the speakers."},
}
UI_TUNABLE = tuple(k for k, s in SETTINGS.items() if s["ui"])

# Not editable here. Shown with their state; an unlock can only be REQUESTED
# with a logged reason — nothing in this module changes them.
LOCKED_GATES = {
    "specifics_rule": {"label": "Only states dates, numbers and titles that are in his notes",
                       "how": "text rule sent with every question (app/answer_pipeline.py GROUNDING_RULE)",
                       "source": "code"},
    "fact_audit":     {"label": "Checks each spoken sentence with a fact auditor",
                       "how": "CJ_FACT_AUDIT", "env": "CJ_FACT_AUDIT", "default": "1"},
    "year_gate":      {"label": "Blocks a year that is not in his notes",
                       "how": "CJ_FACT_GATE", "env": "CJ_FACT_GATE", "default": "1"},
    "ai_self_description_gate": {"label": "Never lets him call himself an AI, robot or machine",
                       "how": "CJ_ANSWER_GATE_ENABLED + data/entities/answer_gate_rules.json",
                       "env": "CJ_ANSWER_GATE_ENABLED", "default": "0"},
    "corpus_grounding": {"label": "Answers from his own columns and speeches",
                       "how": "CJ_CONTEXT_TOKEN_BUDGET > 0 and the topic map",
                       "env": "CJ_CONTEXT_TOKEN_BUDGET", "default": "12000"},
}

_TRUE = {"1", "true", "yes", "on"}


def _coerce(kind, raw):
    """Turn a JSON or env value into the setting's type; raises ValueError."""
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        return str(raw).strip().lower() in _TRUE
    if kind == "int":
        if isinstance(raw, bool):
            raise ValueError("bool is not an int")
        return int(round(float(raw)))
    if kind == "float":
        if isinstance(raw, bool):
            raise ValueError("bool is not a float")
        return float(raw)
    raise ValueError(kind)


def env_string(kind, value):
    """The string the robot puts in os.environ for a setting value."""
    if kind == "bool":
        return "1" if value else "0"
    if kind == "int":
        return str(int(value))
    return ("%g" % float(value))


# ────────────────────────────────────────────────────────────────────────────
# Config sources (profiles, drop-in, .env), cached by mtime
# ────────────────────────────────────────────────────────────────────────────
class ConfigSources:
    def __init__(self, modes_dir=MODES_DIR, dropin_path=DROPIN_PATH, dotenv_path=DOTENV_PATH,
                 robots_path=ROBOTS_PATH):
        self.modes_dir, self.dropin_path, self.dotenv_path = modes_dir, dropin_path, dotenv_path
        self.robots_path = robots_path
        self._cache: dict = {}

    # ── machines / authority (config/robots.json) ─────────────────────────
    def robots(self):
        return self._cached(self.robots_path, json.loads) or {}

    def machine_of(self, slot):
        return str((self.robots().get("slots") or {}).get(slot) or slot)

    def label_of(self, role):
        return str((self.robots().get("labels") or {}).get(role) or role)

    def authority(self):
        """Where the lease/console server runs. `url` is what every caller
        should use: the optional `ip` (2026-09-12 venue kit — an address skips
        mDNS, which guest networks often block) else the {host}.local template."""
        a = self.robots().get("authority") or {}
        host, port = str(a.get("host") or ""), int(a.get("port") or 8080)
        ip = str(a.get("ip") or "").strip()
        tmpl = str(a.get("url_template") or "http://{host}.local:{port}")
        url = f"http://{ip}:{port}" if ip else (tmpl.format(host=host, port=port) if host else "")
        return {"host": host, "port": port, "bind": str(a.get("bind") or "0.0.0.0"),
                "ip": ip, "url_template": tmpl, "url": url}

    def _cached(self, path, parser):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            self._cache.pop(path, None)
            return None
        hit = self._cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
        try:
            with open(path, encoding="utf-8") as f:
                val = parser(f.read())
        except Exception as e:
            val = {"_error": f"{type(e).__name__}: {e}"}
        self._cache[path] = (mtime, val)
        return val

    def profile_doc(self, mode):
        return self._cached(os.path.join(self.modes_dir, f"{mode}.json"), json.loads) or {}

    def duet_lines(self, path=DUET_SCRIPT_PATH):
        """[(id, who, pause_after_s), ...] for the duet exchange, in order.
        The order and the speaker of each line are all the console needs to
        sequence it; the audio and text live with the robots. [] if absent."""
        doc = self._cached(path, json.loads) or {}
        out = []
        for ln in doc.get("lines", []):
            if ln.get("who") in ROLES and ln.get("id"):
                out.append((str(ln["id"]), ln["who"], float(ln.get("pause_after_s", 0.6))))
        return out

    @staticmethod
    def _parse_env_lines(text):
        """KEY=VALUE lines (with optional `Environment=` prefix and quotes)."""
        out = {}
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("Environment="):
                s = s[len("Environment="):].strip()
            if s.startswith("export "):
                s = s[7:].strip()
            if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
                s = s[1:-1]
            if "=" not in s:
                continue
            k, v = s.split("=", 1)
            k = k.strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
                out[k] = v.strip().strip('"').strip("'")
        return out

    def dropin(self):
        return self._cached(self.dropin_path, self._parse_env_lines) or {}

    def dotenv(self):
        return self._cached(self.dotenv_path, self._parse_env_lines) or {}

    def resolve(self, mode, profile, overrides):
        """-> (values, sources, errors). Later layers win per key."""
        values, sources, errors = {}, {}, []
        doc = self.profile_doc(mode)
        if doc.get("_error"):
            errors.append(f"profile {mode}.json: {doc['_error']}")
        layers = [
            (f"profile {mode}.json defaults", doc.get("defaults") or {}),
            (f"profile {mode}.json/{profile}", (doc.get("profiles") or {}).get(profile) or {}),
        ]
        for name, src in (("systemd drop-in", self.dropin()), ("app/.env", self.dotenv())):
            if src.get("_error"):
                errors.append(f"{name}: {src['_error']}")
            layers.append((name, {k: src[s["env"]] for k, s in SETTINGS.items() if s["env"] in src}))
        layers.append(("console override", overrides or {}))
        for name, layer in layers:
            for key, raw in layer.items():
                if key not in SETTINGS or key.startswith("_"):
                    continue
                try:
                    values[key] = _coerce(SETTINGS[key]["type"], raw)
                    sources[key] = name
                except (TypeError, ValueError):
                    errors.append(f"{name}: bad {key}={raw!r} ignored")
        for key in SETTINGS:
            if key not in values:
                errors.append(f"{key}: no value in any source")
        return values, sources, errors

    def host_intro_text(self, mode):
        return str(self.profile_doc(mode).get("host_intro_text") or "")

    def signature(self, mode):
        """mtimes of the files a resolution depends on — a change here means
        the effective config must be recomputed (and re-journaled)."""
        sig = []
        for path in (os.path.join(self.modes_dir, f"{mode}.json"), self.dropin_path, self.dotenv_path):
            try:
                sig.append(os.path.getmtime(path))
            except OSError:
                sig.append(None)
        return tuple(sig)

    def locked_state(self):
        env = {}
        env.update(self.dropin())
        env.update(self.dotenv())      # .env loads with override=True in the app
        out = {}
        for gid, g in LOCKED_GATES.items():
            if g.get("source") == "code":
                on, src = True, "code"
            else:
                raw = env.get(g["env"])
                src = ("app/.env" if g["env"] in self.dotenv()
                       else "systemd drop-in" if g["env"] in self.dropin() else "code default")
                raw = g["default"] if raw is None else raw
                if gid == "corpus_grounding":
                    try:
                        on = float(raw) > 0
                    except ValueError:
                        on = False
                else:
                    on = str(raw).strip().lower() in _TRUE
            out[gid] = {"label": g["label"], "how": g["how"], "on": on, "source": src, "locked": True}
        return out


# ────────────────────────────────────────────────────────────────────────────
# The console
# ────────────────────────────────────────────────────────────────────────────
class Console:
    def __init__(self, sources: ConfigSources | None = None, *, clock=time.monotonic,
                 wall=time.time, state_path=STATE_PATH, journal_path=JOURNAL_PATH,
                 ttl_s=TTL_S, log=print, restore=True):
        self.sources = sources or ConfigSources()
        self.clock, self.wall, self.log = clock, wall, log
        self.state_path, self.journal_path = state_path, journal_path
        self.ttl_s = float(ttl_s)
        self._lock = threading.RLock()
        # the one value (mic) …
        self.floor = "none"
        self.floor_role = None     # which ROLE the floor is bound to (direct mode: follows role swaps)
        # … and the other one value (persona): the slot that is Panganiban
        self.cjap_is = "alpha"
        self._handoff_seq = 0      # intro_seq already handed from host to cjap
        self.calib = None          # room calibration run (see calibrate())
        self.mode, self.profile = "direct", "kiosk"
        self.overrides: dict = {}
        self.transition = None     # {"target", "started", "deadline"}
        self.pending = None        # {"floor"?, "mode"?, "profile"?, "settings"?, "queued_at", "who"}
        self.observed = {r: None for r in ROBOTS}
        self.interrupt_seq = {r: 0 for r in ROBOTS}
        self.intro_seq = 0
        # Host-asked question (2026-09-12, user: "manually input the question
        # from the host ... the host will say it while the CJAP robot will
        # process it"). Two hops, sequenced here so the answer never starts
        # before the room has heard the question: bump `ask` -> the Host robot
        # plays it (its own pre-recorded clip, or its voice) -> the Host
        # reports ask_done -> `question` is released to Panganiban, who routes
        # and composes it live. `stage` is which hop is outstanding.
        self.ask = {"seq": 0, "text": "", "clip": "", "stage": "", "at": 0.0}
        self.question = {"seq": 0, "text": "", "by": ""}
        # Duet (2026-09-12): the attract loop. In duet mode the console walks
        # the duet script line by line — it tells the robot whose ROLE owns the
        # current line to play its clip, waits for that robot to report it
        # finished, then advances. `seq` bumps per line so the robot fires once
        # per line; `idx` is the position in the script; `who` the role playing;
        # `until` is when the current line + its pause is expected to end, after
        # which tick() advances even without a report (a robot that cannot play
        # must not stall the loop). It loops with a gap. No mic, nothing live.
        self.duet = {"on": False, "seq": 0, "idx": -1, "who": "", "line": "", "until": 0.0,
                     "hold_until": 0.0}   # authored pause between lines (2026-09-13)
        self.config_seq = 0
        self.journal_mem: deque = deque(maxlen=JOURNAL_KEEP)
        self._effective_cache = None
        self._eff_sig = None
        if restore:
            self._restore()
        self._recompute(announce=True)

    # ── persistence / journal ─────────────────────────────────────────────
    def _restore(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            return
        if saved.get("mode") in MODES:
            self.mode = saved["mode"]
        if saved.get("profile") in PROFILES:
            self.profile = saved["profile"]
        if saved.get("cjap_is") in ROBOTS:
            self.cjap_is = saved["cjap_is"]
        if saved.get("floor_role") in ROLES:
            self.floor_role = saved["floor_role"]
        self._handoff_seq = int(saved.get("handoff_seq", 0))
        if isinstance(saved.get("overrides"), dict):
            self.overrides = {k: v for k, v in saved["overrides"].items() if k in SETTINGS}
        for r in ROBOTS:
            self.interrupt_seq[r] = int((saved.get("interrupt_seq") or {}).get(r, 0))
        self.intro_seq = int(saved.get("intro_seq", 0))
        self.config_seq = int(saved.get("config_seq", 0))
        # seqs survive a restart so a robot that never went away is not re-asked
        self.ask["seq"] = int((saved.get("ask") or {}).get("seq", 0))
        self.question["seq"] = int((saved.get("question") or {}).get("seq", 0))
        self.duet["seq"] = int((saved.get("duet") or {}).get("seq", 0))
        want = saved.get("floor")
        # A restart never hands a mic straight back: the saved floor is re-taken
        # through the normal close-both-then-open transition. The floor stays
        # bound to the role it had (state files from before 2026-09-10 have no
        # floor_role: derive it, so a later role swap still moves the floor).
        if want in ROBOTS and self.mode != "duet":
            if self.floor_role not in ROLES:
                self.floor_role = self.role_of(want)
            self._begin_transition(want, who="restore")
        elif want == "none":
            self.floor_role = None
        self._journal("restore", f"console restarted — mode {self.mode}, profile {self.profile}, "
                                 f"floor {'re-taking ' + want if want in ROBOTS else 'none'}", who="system")

    def _persist(self):
        doc = {"floor": self.transition["target"] if self.transition else self.floor,
               "floor_role": self.floor_role, "cjap_is": self.cjap_is, "handoff_seq": self._handoff_seq,
               "mode": self.mode, "profile": self.profile, "overrides": self.overrides,
               "interrupt_seq": self.interrupt_seq, "intro_seq": self.intro_seq,
               "config_seq": self.config_seq,
               "ask": {"seq": self.ask["seq"]}, "question": {"seq": self.question["seq"]},
               "duet": {"seq": self.duet["seq"]},
               "saved": self.wall()}
        if not self.state_path:
            return
        try:
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(doc, f)
            os.replace(tmp, self.state_path)
        except OSError as e:
            self.log(f"[console] state not saved: {e}")

    def _journal(self, kind, msg, who="console", **extra):
        ev = {"ts": self.wall(), "kind": kind, "msg": msg, "who": who}
        ev.update(extra)
        self.journal_mem.append(ev)
        try:
            self.log(f"[console] {kind}: {msg}" + (f" ({who})" if who else ""))
        except Exception:
            pass
        if self.journal_path:
            try:
                with open(self.journal_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(ev) + "\n")
            except OSError:
                pass
        return ev

    def journal(self, n=50):
        with self._lock:
            return list(self.journal_mem)[-max(1, min(int(n), JOURNAL_KEEP)):]

    # ── roles ─────────────────────────────────────────────────────────────
    def role_of(self, slot):
        return "cjap" if slot == self.cjap_is else "host"

    def slot_of(self, role):
        if role == "cjap":
            return self.cjap_is
        return "beta" if self.cjap_is == "alpha" else "alpha"

    def name(self, slot):
        """'machine · Role' — never identify a robot by its hostname alone."""
        return f"{self.sources.machine_of(slot)} · {self.sources.label_of(self.role_of(slot))}"

    def host_ask(self, text, clip="", who="console", now=None):
        """Operator typed a question for the Host to ask. Returns (ok, msg, status).

        The Host speaks it first and Panganiban answers only once the Host has
        finished, so the two robots never talk over each other. With no Host
        reporting — one machine on the network, or the other one down — the
        question goes straight to Panganiban rather than stalling."""
        text = " ".join(str(text or "").split())
        clip = str(clip or "").strip()
        now = self._now(now)
        if not text:
            return False, "type a question first", 400
        if len(text) > 400:
            return False, "question longer than 400 characters", 400
        if "/" in clip or clip.startswith("."):
            return False, "bad clip name", 400
        with self._lock:
            self.tick(now)
            if self.mode == "duet":
                return False, "duet mode composes nothing — switch to direct first", 409
            host, cjap = self.slot_of("host"), self.slot_of("cjap")
            self.ask.update(seq=self.ask["seq"] + 1, text=text, clip=clip, at=now)
            if self._obs_fresh(host, now):
                self.ask["stage"] = "host"
                self._journal("ask", f"{self.name(host)} asks: \u201c{text}\u201d"
                                     + (f" [{clip}]" if clip else " [its own voice]"), who=who,
                              robot=host, seq=self.ask["seq"])
                out = f"{self.name(host)} is asking it — {self.name(cjap)} answers when it finishes"
            else:
                self.ask["stage"] = ""
                self._release_question(now, who=who,
                                       note=f"no report from {self.name(host)} — asked {self.name(cjap)} directly")
                out = f"no Host reporting — asked {self.name(cjap)} directly"
            self._persist()
            return True, out, 200

    def _release_question(self, now, who="console", note=""):
        """Hand the pending question to Panganiban (caller holds the lock)."""
        self.question.update(seq=self.ask["seq"], text=self.ask["text"], by="host")
        self.ask["stage"] = "cjap"
        cjap = self.slot_of("cjap")
        self._journal("ask", note or f"question released to {self.name(cjap)}",
                      who=who, robot=cjap, seq=self.question["seq"])

    def set_role(self, cjap_is, force=False, who="console", now=None):
        """-> (ok, message, http_status). Two Panganibans are unrepresentable:
        this is the single value. In direct mode the floor follows the role."""
        now = self._now(now)
        if cjap_is not in ROBOTS:
            return False, "cjap_is must be alpha or beta", 400
        with self._lock:
            self.tick(now)
            if cjap_is == self.cjap_is and self.pending is None:
                return True, f"{self.sources.machine_of(cjap_is)} is already Panganiban", 200
            active = self._any_turn_active(now)
            if active and not force:
                self.pending = {"cjap_is": cjap_is, "queued_at": now, "who": who}
                self._journal("queued", f"role swap (Panganiban -> {self.sources.machine_of(cjap_is)}) queued "
                                        f"until {', '.join(active)} finishes", who=who, cjap_is=cjap_is)
                return True, f"queued — applies when {', '.join(active)} finishes; use Cut short to apply now", 202
            if active and force:
                self._cut(active, who, now)
            self.pending = None
            self._apply_change({"cjap_is": cjap_is}, now=now, who=who)
            return True, f"Panganiban is now {self.sources.machine_of(cjap_is)}", 200

    # ── config ────────────────────────────────────────────────────────────
    def _recompute(self, announce=False, who="console"):
        self._eff_sig = self.sources.signature(self.mode)
        values, sources, errors = self.sources.resolve(self.mode, self.profile, self.overrides)
        env = {SETTINGS[k]["env"]: env_string(SETTINGS[k]["type"], v) for k, v in values.items()}
        # A zero post-answer window also switches the always-listen fallback off.
        # Emit the key in BOTH directions (2026-09-13 audit): _floor_settings on the
        # robot only assigns keys PRESENT in this dict and never unsets, so omitting
        # it on the way back left a stale "0" in the live process — the lock-less
        # follow-up window stayed dead after any duet -> direct switch until a
        # restart. Both robots were found in that state. "1" matches the robot-side
        # default in main_voice_robot._always_listen().
        env["CJ_ALWAYS_LISTEN"] = "0" if values.get("post_answer_window_s", 1) == 0 else "1"
        self._effective_cache = {"values": values, "sources": sources, "errors": errors, "env": env}
        if announce:
            self.config_seq += 1
            summary = ", ".join(f"{k}={values[k]!r}<{sources[k]}>" for k in SETTINGS if k in values)
            self._journal("config", f"effective config — mode {self.mode}, profile {self.profile}: {summary}",
                          who=who, mode=self.mode, profile=self.profile, values=values, sources=sources)
            for e in errors:
                self._journal("config-warning", e, who="system")
        return self._effective_cache

    def effective(self):
        with self._lock:
            if self._effective_cache is None:
                return self._recompute()
            if self.sources.signature(self.mode) != self._eff_sig:
                # a profile / drop-in / .env edit on disk: re-resolve, re-journal
                return self._recompute(announce=True, who="file change")
            return self._effective_cache

    # ── time ──────────────────────────────────────────────────────────────
    def _now(self, now):
        return self.clock() if now is None else float(now)

    def _obs_fresh(self, robot, now):
        o = self.observed.get(robot)
        return bool(o) and (now - o["ts"]) <= OBS_FRESH_S

    def _turn_active(self, robot, now):
        o = self.observed.get(robot)
        return bool(o) and bool(o.get("turn_active")) and (now - o["ts"]) <= TURN_FRESH_S

    def _any_turn_active(self, now):
        return [r for r in ROBOTS if self._turn_active(r, now)]

    def _both_closed_since(self, started, now):
        for r in ROBOTS:
            o = self.observed.get(r)
            if not o or o["ts"] < started or o.get("mic_open") is not False:
                return False
            if (now - o["ts"]) > OBS_FRESH_S:
                return False
        return True

    def _duet_start(self, now, who="console"):
        """Begin (or restart) the exchange at line 0 (lock held)."""
        lines = self.sources.duet_lines()
        if not lines:
            self.duet.update(on=False, idx=-1, who="", line="", until=0.0, hold_until=0.0)
            self._journal("duet", "duet mode but no duet_script.json — nothing to play", who=who)
            return
        lid, lwho, pause = lines[0]
        self.duet.update(on=True, seq=self.duet["seq"] + 1, idx=0, who=lwho, line=lid,
                         until=now + 30.0,   # 30 s cap until the robot reports the real end
                         hold_until=0.0)
        self._journal("duet", f"duet start — line {lid} ({self.name(self.slot_of(lwho))})",
                      who=who, seq=self.duet["seq"], line=lid)

    def _duet_hold(self, now, who="console"):
        """A line just finished: wait its authored pause before the next one.

        Until 2026-09-13 `pause_after_s` was read out of the script and thrown
        away, and DUET_LOOP_GAP_S was never referenced at all, so the two
        robots traded lines back to back with no beat between them and the
        exchange restarted instantly. Holding here (rather than sleeping in the
        robot) keeps the authority the only thing that decides timing.
        """
        lines = self.sources.duet_lines()
        if not lines:
            self.duet["on"] = False
            return
        cur = self.duet["idx"]
        pause = lines[cur][2] if 0 <= cur < len(lines) else 0.6
        if cur + 1 >= len(lines):
            pause += DUET_LOOP_GAP_S      # a longer breath before it loops
        self.duet["hold_until"] = now + max(0.0, pause)

    def _duet_advance(self, now, who="console"):
        """Move to the next line, looping with a gap (lock held)."""
        lines = self.sources.duet_lines()
        if not lines:
            self.duet["on"] = False
            return
        nxt = self.duet["idx"] + 1
        if nxt >= len(lines):
            nxt = 0     # loop
        lid, lwho, pause = lines[nxt]
        self.duet.update(seq=self.duet["seq"] + 1, idx=nxt, who=lwho, line=lid,
                         until=now + 30.0, hold_until=0.0)
        self._journal("duet", f"duet line {lid} ({self.name(self.slot_of(lwho))})"
                              + (" — loop" if nxt == 0 else ""),
                      who=who, seq=self.duet["seq"], line=lid)

    def _duet_tick(self, now):
        """Drive the exchange (lock held). Starts it when duet mode is entered,
        stops it when it leaves, and advances on the deadline as a fallback —
        the real advance is the robot's duet_done report in report()."""
        if self.mode != "duet":
            if self.duet["on"]:
                self.duet.update(on=False, idx=-1, who="", line="", until=0.0, hold_until=0.0)
            return
        if not self.duet["on"]:
            self._duet_start(now)
            return
        # authored pause between lines: hold, then advance
        hold = self.duet.get("hold_until") or 0.0
        if hold:
            if now >= hold:
                self.duet["hold_until"] = 0.0
                self._duet_advance(now)
            return      # never let the deadline below fire during a hold
        # deadline fallback: a robot that never reports (cannot play, or gone)
        # must not freeze the loop
        if self.duet["until"] and now >= self.duet["until"]:
            self._journal("duet", f"line {self.duet['line']} timed out — advancing", who="console")
            self._duet_advance(now)

    def tick(self, now=None):
        """Advance transitions and queued changes. Cheap; called on every
        request so the model never depends on a background thread."""
        now = self._now(now)
        with self._lock:
            tr = self.transition
            if tr is not None:
                done, why = False, ""
                if self._both_closed_since(tr["started"], now):
                    done, why = True, "both robots reported mic closed"
                elif now >= tr["deadline"]:
                    done, why = True, f"{self.ttl_s + SETTLE_MARGIN_S:.1f} s settle elapsed"
                if done:
                    self.floor = tr["target"]
                    self.transition = None
                    self._journal("floor", f"floor is now {self.floor} — {why}",
                                  who=tr.get("who", "console"), floor=self.floor)
                    self._persist()
            if self.pending is not None and self.transition is None and not self._any_turn_active(now):
                p, self.pending = self.pending, None
                self._journal("drain", "turn finished — applying the queued change", who=p.get("who", "console"))
                self._apply_change(p, now=now, who=p.get("who", "console"))

            self._duet_tick(now)

    # ── floor ─────────────────────────────────────────────────────────────
    def _begin_transition(self, target, who="console", now=None):
        """Close both now; name the target only after the settle."""
        now = self._now(now)
        prev = self.floor
        self.floor = "none"            # every lease reply revokes from here on
        if target == "none":
            self.transition = None
            if prev != "none":
                self._journal("floor", "floor is now none — both mics closing", who=who, floor="none")
        else:
            self.transition = {"target": target, "started": now,
                               "deadline": now + self.ttl_s + SETTLE_MARGIN_S, "who": who}
            self._journal("floor", f"floor moving to {target} — closing both mics first"
                                   + (f" (was {prev})" if prev != "none" else ""),
                          who=who, floor="none", target=target)
        self._persist()

    def request_floor(self, target, force=False, who="console", now=None):
        """-> (ok, message, http_status)."""
        now = self._now(now)
        if target not in FLOORS:
            return False, f"floor must be one of {', '.join(FLOORS)}", 400
        with self._lock:
            self.tick(now)
            if self.mode == "duet" and target != "none":
                return False, "Duet mode keeps every microphone closed. Switch to direct first.", 409
            goal = self.transition["target"] if self.transition else self.floor
            if target == goal and self.pending is None:
                return True, f"floor already {target}", 200
            active = self._any_turn_active(now)
            if active and not force:
                self.pending = {"floor": target, "queued_at": now, "who": who}
                self._journal("queued", f"floor -> {target} queued until {', '.join(active)} finishes the answer",
                              who=who, target=target)
                return True, f"queued — applies when {', '.join(active)} finishes; use Cut short to apply now", 202
            if active and force:
                self._cut(active, who, now)
            self.pending = None
            self.floor_role = self.role_of(target) if target in ROBOTS else None
            self._begin_transition(target, who=who, now=now)
            return True, f"floor -> {self.name(target) if target in ROBOTS else 'no one'}", 200

    def _cut(self, robots, who, now):
        for r in robots:
            self.interrupt_seq[r] += 1
            self._journal("interrupt", f"{r}: answer cut short by the operator", who=who, robot=r)
        self._persist()

    def pending_action(self, action, who="console", now=None):
        now = self._now(now)
        with self._lock:
            self.tick(now)
            if self.pending is None:
                return False, "nothing is queued", 409
            if action == "cancel":
                p, self.pending = self.pending, None
                self._journal("queued", "queued change cancelled", who=who)
                return True, "queued change cancelled", 200
            if action == "cut":
                p, self.pending = self.pending, None
                active = self._any_turn_active(now)
                if active:
                    self._cut(active, who, now)
                self._apply_change(p, now=now, who=who)
                return True, "answer cut short — change applied", 200
            return False, "action must be cut or cancel", 400

    # ── config changes ────────────────────────────────────────────────────
    def _validate_settings(self, settings):
        clean, errs = {}, []
        for k, raw in (settings or {}).items():
            if k not in SETTINGS:
                errs.append(f"unknown setting {k}")
                continue
            if not SETTINGS[k]["ui"]:
                errs.append(f"{k} is set by the profile, not the console")
                continue
            if raw is None:
                clean[k] = None          # None = drop the override
                continue
            try:
                v = _coerce(SETTINGS[k]["type"], raw)
            except (TypeError, ValueError):
                errs.append(f"{k}: bad value {raw!r}")
                continue
            lo, hi = SETTINGS[k].get("min"), SETTINGS[k].get("max")
            if lo is not None and v < lo or hi is not None and v > hi:
                errs.append(f"{k}: {v} outside {lo}–{hi}")
                continue
            clean[k] = v
        return clean, errs

    def set_config(self, mode=None, profile=None, settings=None, force=False, who="console", now=None):
        now = self._now(now)
        if mode is not None and mode not in MODES:
            return False, f"mode must be duet or direct", 400
        if profile is not None and profile not in PROFILES:
            return False, f"profile must be kiosk or event", 400
        clean, errs = self._validate_settings(settings)
        if errs:
            return False, "; ".join(errs), 400
        with self._lock:
            self.tick(now)
            change = {"mode": mode, "profile": profile, "settings": clean}
            if mode is None and profile is None and not clean:
                return True, "nothing to change", 200
            active = self._any_turn_active(now)
            if active and not force and (mode is not None and mode != self.mode):
                # a MODE change mid-answer drains; settings/profile apply live
                self.pending = dict(change, queued_at=now, who=who)
                self._journal("queued", f"mode -> {mode} queued until {', '.join(active)} finishes",
                              who=who, mode=mode)
                return True, f"queued — applies when {', '.join(active)} finishes; use Cut short to apply now", 202
            if active and force and mode is not None and mode != self.mode:
                self._cut(active, who, now)
            self.pending = None
            self._apply_change(change, now=now, who=who)
            return True, "applied", 200

    def _apply_change(self, change, now, who):
        """Apply {floor|mode|profile|settings}; lock held."""
        if change.get("floor") is not None:
            if self.mode == "duet" and change["floor"] != "none":
                self._journal("floor", f"queued floor -> {change['floor']} dropped: duet mode", who=who)
            else:
                self._begin_transition(change["floor"], who=who, now=now)
            return
        old_mode, old_profile, old_cjap = self.mode, self.profile, self.cjap_is
        if change.get("cjap_is") in ROBOTS and change["cjap_is"] != self.cjap_is:
            self.cjap_is = change["cjap_is"]
            self._journal("role", f"Panganiban is now {self.sources.machine_of(self.cjap_is)} ({self.cjap_is}); "
                                  f"Host is {self.sources.machine_of(self.slot_of('host'))}",
                          who=who, cjap_is=self.cjap_is)
            if self.mode == "direct" and self.floor_role in ROLES:
                # the floor is bound to a ROLE: move it with the swap so the
                # visitor's transmitter feeds the right robot
                target = self.slot_of(self.floor_role)
                self._journal("floor", f"floor follows the {self.sources.label_of(self.floor_role)} role -> {self.name(target)}",
                              who=who, target=target)
                self._begin_transition(target, who=who, now=now)
            self._persist()
        if change.get("mode") in MODES:
            self.mode = change["mode"]
        if change.get("profile") in PROFILES:
            self.profile = change["profile"]
        for k, v in (change.get("settings") or {}).items():
            if v is None:
                self.overrides.pop(k, None)
            else:
                self.overrides[k] = v
        if self.mode != old_mode:
            self._journal("mode", f"mode -> {self.mode}" + (" — floor forced to none" if self.mode == "duet" else ""),
                          who=who, mode=self.mode)
            if self.mode == "duet":
                self.floor_role = None
                self._begin_transition("none", who=who, now=now)
        if self.profile != old_profile:
            self._journal("profile", f"profile -> {self.profile}", who=who, profile=self.profile)
        if change.get("settings"):
            self._journal("settings", "override " + ", ".join(
                f"{k}={'cleared' if v is None else v}" for k, v in change["settings"].items()), who=who)
        eff = self._recompute(announce=True, who=who)
        if self.mode == "direct" and old_mode != "direct":
            # direct: the floor follows the role. With the intro on, the Host
            # holds the floor for the intro and hands it to Panganiban when
            # done (see report()); otherwise Panganiban takes it straight away.
            if eff["values"].get("host_intro"):
                self.intro_seq += 1
                self.floor_role = "host"
                self._journal("intro", f"host ({self.sources.machine_of(self.slot_of('host'))}) asked to say the intro line — "
                                       "it holds the floor until the intro is done", who=who)
            else:
                self.floor_role = "cjap"
            self._begin_transition(self.slot_of(self.floor_role), who=who, now=now)
        self._persist()

    # ── robots ────────────────────────────────────────────────────────────
    def report(self, robot, obs, now=None):
        """A robot's poll: store what its mic is actually doing, answer with
        the lease. -> (ok, reply_or_message, status)."""
        now = self._now(now)
        if robot not in ROBOTS:
            return False, f"robot must be alpha or beta (got {robot!r})", 400
        obs = obs if isinstance(obs, dict) else {}
        rec = {"ts": now, "wall": self.wall(),
               "mic_open": obs.get("mic_open") if isinstance(obs.get("mic_open"), bool) else None,
               "speaking": bool(obs.get("speaking")),
               "turn_active": bool(obs.get("turn_active")),
               "rms": obs.get("rms") if isinstance(obs.get("rms"), (int, float)) else None,
               "speech_threshold": obs.get("speech_threshold")
               if isinstance(obs.get("speech_threshold"), (int, float)) else None,
               "boot_id": str(obs.get("boot_id") or "")[:80],
               "has_floor": bool(obs.get("has_floor")),
               "machine": str(obs.get("machine") or "")[:64],
               "rms_1s": obs.get("rms_1s") if isinstance(obs.get("rms_1s"), dict) else None,
               "threshold_binding": obs.get("threshold_binding") if isinstance(obs.get("threshold_binding"), str) else None,
               "turn_threshold": obs.get("turn_threshold") if isinstance(obs.get("turn_threshold"), dict) else None,
               "persona": obs.get("persona") if obs.get("persona") in ROLES else None,
               "intro_done": int(obs["intro_done"]) if isinstance(obs.get("intro_done"), int) else 0,
               "ask_done": int(obs["ask_done"]) if isinstance(obs.get("ask_done"), int) else 0,
               "duet_done": int(obs["duet_done"]) if isinstance(obs.get("duet_done"), int) else 0,
               "role_ok": obs.get("robot") == robot}
        with self._lock:
            prev = self.observed.get(robot)
            if prev is None or prev.get("boot_id") != rec["boot_id"]:
                self._journal("robot", f"{robot} reporting (boot {rec['boot_id'][-12:] or '?'})", who=robot)
            elif prev.get("mic_open") != rec["mic_open"]:
                self._journal("observed", f"{robot} mic {'open' if rec['mic_open'] else 'closed'}", who=robot)
            if rec["turn_active"] and not (prev or {}).get("turn_active"):
                # one line per turn: the RESOLVED threshold and what bound it
                t = rec["turn_threshold"] or {}
                self._journal("turn", f"{self.name(robot)}: question capture — room rms {t.get('rms', '?')}, "
                                      f"speech threshold {t.get('threshold', '?')} ({t.get('binding', '?')} binding)",
                              who=robot, robot=robot, **{k: t.get(k) for k in ("rms", "threshold", "binding")})
            self.observed[robot] = rec
            self._calib_sample(robot, rec, now)
            # intro handoff: the Host finished the intro -> floor to Panganiban
            if (self.mode == "direct" and self.floor_role == "host" and robot == self.slot_of("host")
                    and self.intro_seq > 0 and rec["intro_done"] >= self.intro_seq
                    and self._handoff_seq < self.intro_seq and self.pending is None):
                self._handoff_seq = self.intro_seq
                self.floor_role = "cjap"
                target = self.slot_of("cjap")
                self._journal("floor", f"intro done — floor to Panganiban ({self.name(target)})", who=robot, target=target)
                self._begin_transition(target, who=robot, now=now)
            # host-asked question: the Host has finished saying it -> Panganiban answers
            if (self.ask["stage"] == "host" and robot == self.slot_of("host")
                    and rec["ask_done"] >= self.ask["seq"]):
                self._release_question(now, who=robot,
                                       note=f"{self.name(robot)} finished the question — "
                                            f"{self.name(self.slot_of('cjap'))} answering")
            # duet: the robot that owns the current line reported it finished -> next line
            if (self.mode == "duet" and self.duet["on"] and rec["duet_done"] >= self.duet["seq"]
                    and self.duet["seq"] > 0 and robot == self.slot_of(self.duet["who"])):
                self._duet_hold(now, who=robot)
            self.tick(now)
            return True, self.lease_for(robot, now), 200

    def lease_for(self, robot, now=None):
        with self._lock:
            eff = self.effective()
            return {"floor": self.floor, "granted": self.floor == robot, "ttl": self.ttl_s,
                    "cjap_is": self.cjap_is, "persona": self.role_of(robot), "slot": robot,
                    "machine": self.sources.machine_of(robot),
                    "mode": self.mode, "profile": self.profile,
                    "settings": eff["values"], "env": eff["env"],
                    "interrupt_seq": self.interrupt_seq.get(robot, 0),
                    "intro_seq": self.intro_seq, "config_seq": self.config_seq,
                    "host_intro_text": self.sources.host_intro_text(self.mode),
                    # exactly one of these is ever non-zero for a given robot,
                    # so a role swap mid-flight cannot make both of them speak
                    "ask_seq": self.ask["seq"] if self.role_of(robot) == "host" else 0,
                    "ask_text": self.ask["text"] if self.role_of(robot) == "host" else "",
                    "ask_clip": self.ask["clip"] if self.role_of(robot) == "host" else "",
                    "question_seq": self.question["seq"] if self.role_of(robot) == "cjap" else 0,
                    "question_text": self.question["text"] if self.role_of(robot) == "cjap" else "",
                    # duet: only the robot whose ROLE owns the current line is told to play it
                    "duet_seq": self.duet["seq"] if (self.mode == "duet" and self.duet["on"]
                                                     and self.role_of(robot) == self.duet["who"]) else 0,
                    "duet_line": self.duet["line"] if (self.mode == "duet" and self.duet["on"]
                                                       and self.role_of(robot) == self.duet["who"]) else "",
                    "server_wall": self.wall()}

    # ── room calibration (event profile: 800/2500 were placeholders) ──────
    def calibrate(self, action, robot=None, seconds=None, who="console", now=None):
        """start | cancel | accept | reject. Samples the room on the robot
        that holds the floor for `seconds`, reports percentiles, proposes a
        speech threshold with headroom; accept writes it as an override."""
        now = self._now(now)
        with self._lock:
            self.tick(now)
            c = self.calib
            if action == "start":
                if robot not in ROBOTS:
                    return False, "robot must be alpha or beta", 400
                if c and c["status"] == "running":
                    return False, f"a calibration is already running on {self.name(c['robot'])}", 409
                if self.floor != robot:
                    return False, f"give the floor to {self.name(robot)} first — its mic must be open to hear the room", 409
                try:
                    secs = max(10, min(600, int(seconds or CALIB_DEFAULT_S)))
                except (TypeError, ValueError):
                    return False, "seconds must be a number", 400
                self.calib = {"robot": robot, "status": "running", "started": now, "seconds": secs,
                              "p50s": [], "maxs": [], "who": who, "result": None}
                self._journal("calibrate", f"room calibration started on {self.name(robot)} for {secs} s "
                                           "— keep the room as it will be during the event", who=who)
                return True, f"sampling the room on {self.name(robot)} for {secs} s", 200
            if c is None:
                return False, "no calibration to act on", 409
            if action == "cancel":
                self.calib = None
                self._journal("calibrate", "room calibration cancelled", who=who)
                return True, "cancelled", 200
            if c["status"] != "done":
                return False, "calibration still running — wait for the proposal", 409
            if action == "reject":
                self._journal("calibrate", f"proposal rejected ({c['result']['proposal']['speech_threshold']}) — nothing changed", who=who)
                self.calib = None
                return True, "rejected — nothing changed", 200
            if action == "accept":
                prop = c["result"]["proposal"]
                self.overrides["speech_threshold"] = int(prop["speech_threshold"])
                self.overrides["speech_threshold_cap"] = int(prop["speech_threshold_cap"])
                self._journal("calibrate", f"proposal ACCEPTED on {self.name(c['robot'])}: loudness {prop['speech_threshold']}, "
                                           f"cap {prop['speech_threshold_cap']} (from p95 peak {c['result']['peaks']['p95']} + {CALIB_HEADROOM})",
                              who=who, **prop)
                self.calib = None
                self._recompute(announce=True, who=who)
                self._persist()
                return True, f"applied: loudness {prop['speech_threshold']}, cap {prop['speech_threshold_cap']}", 200
            return False, "action must be start, cancel, accept or reject", 400

    def _calib_sample(self, robot, rec, now):
        """lock held; called from report()."""
        c = self.calib
        if not c or c["status"] != "running" or c["robot"] != robot:
            return
        r1 = rec.get("rms_1s")
        if rec.get("mic_open") and isinstance(r1, dict):
            c["p50s"].append(int(r1.get("p50", 0)))
            c["maxs"].append(int(r1.get("max", 0)))
        if now - c["started"] >= c["seconds"]:
            c["status"] = "done"
            c["result"] = self._calib_result(c)
            if c["result"] is None:
                self._journal("calibrate", "calibration ended with no samples — was the mic open?", who=c["who"])
                self.calib = None
            else:
                pk, pr = c["result"]["peaks"], c["result"]["proposal"]
                self._journal("calibrate", f"room on {self.name(robot)}: per-second peaks p50 {pk['p50']} p90 {pk['p90']} "
                                           f"p95 {pk['p95']} p99 {pk['p99']} max {pk['max']} ({c['result']['n']} s) — "
                                           f"proposal loudness {pr['speech_threshold']}, cap {pr['speech_threshold_cap']} — accept or reject",
                              who=c["who"])

    @staticmethod
    def _pct(sorted_vals, q):
        if not sorted_vals:
            return 0
        k = min(len(sorted_vals) - 1, max(0, int(round(q / 100.0 * (len(sorted_vals) - 1)))))
        return int(sorted_vals[k])

    def _calib_result(self, c):
        if not c["maxs"]:
            return None
        peaks, meds = sorted(c["maxs"]), sorted(c["p50s"])
        pk = {q: self._pct(peaks, n) for q, n in (("p50", 50), ("p90", 90), ("p95", 95), ("p99", 99))}
        pk["max"] = peaks[-1]
        md = {q: self._pct(meds, n) for q, n in (("p50", 50), ("p90", 90), ("p95", 95), ("p99", 99))}
        md["max"] = meds[-1]
        eff = self.effective()["values"]
        floor = int(-(-(pk["p95"] + CALIB_HEADROOM) // 10) * 10)           # round up to 10
        cap = int(max(floor * 2, pk["max"] + CALIB_HEADROOM * 2, eff.get("speech_threshold_cap", 0)))
        cap = int(-(-cap // 10) * 10)
        return {"n": len(peaks), "peaks": pk, "medians": md,
                "proposal": {"speech_threshold": floor, "speech_threshold_cap": cap},
                "why": f"loudness = p95 of the per-second peaks ({pk['p95']}) + {CALIB_HEADROOM} headroom; "
                       f"cap = at least twice that and above the loudest second ({pk['max']}) + {2 * CALIB_HEADROOM}",
                "current": {"speech_threshold": eff.get("speech_threshold"),
                            "speech_threshold_cap": eff.get("speech_threshold_cap")}}

    def calib_view(self, now):
        c = self.calib
        if not c:
            return None
        v = {"robot": c["robot"], "label": self.name(c["robot"]), "status": c["status"],
             "seconds": c["seconds"], "elapsed_s": round(now - c["started"], 1), "n": len(c["maxs"])}
        if c["maxs"]:
            v["live"] = {"peak_last": c["maxs"][-1], "p50_last": c["p50s"][-1], "peak_max": max(c["maxs"])}
        if c["result"]:
            v["result"] = c["result"]
        return v

    def unlock_request(self, gate, reason, who="console"):
        if gate not in LOCKED_GATES:
            return False, f"unknown gate {gate!r}", 400
        reason = (reason or "").strip()
        if len(reason) < 8:
            return False, "a reason of at least 8 characters is required", 400
        self._journal("unlock-request", f"{gate}: {reason[:300]} — NOT changed; edit the config by hand",
                      who=who, gate=gate, reason=reason[:300])
        return True, "logged. Nothing was changed — these gates are edited in the config, not here.", 200

    # ── the state document ────────────────────────────────────────────────
    def state(self, now=None):
        now = self._now(now)
        with self._lock:
            self.tick(now)
            eff = self.effective()
            values = eff["values"]
            observed, rms, speaking, warnings = {}, {}, {}, []
            for r in ROBOTS:
                o = self.observed.get(r)
                fresh = self._obs_fresh(r, now)
                intended = self.floor == r
                view = {"machine": self.sources.machine_of(r),
                        "role": self.role_of(r), "label": self.name(r),
                        "reported_persona": (o or {}).get("persona"),
                        "intended": "open" if intended else "closed",
                        "mic": None if not fresh else o["mic_open"],
                        "fresh": fresh,
                        "age_s": None if not o else round(now - o["ts"], 1),
                        "turn_active": bool(o and o["turn_active"]) if fresh else None,
                        "speaking": bool(o and o["speaking"]) if fresh else None,
                        "speech_threshold": (o or {}).get("speech_threshold"),
                        "threshold_binding": (o or {}).get("threshold_binding"),
                        "rms_1s": (o or {}).get("rms_1s") if fresh else None,
                        "boot_id": (o or {}).get("boot_id"),
                        "has_floor": bool(o and o["has_floor"]) if fresh else None,
                        "diverges": False}
                if not fresh:
                    view["diverges"] = intended
                    if intended:
                        warnings.append({"level": "bad", "robot": r,
                                         "msg": f"{r} should be listening but has not reported for "
                                                f"{'a while' if not o else '%.0f s' % (now - o['ts'])} — mic is closed by lease expiry"})
                    elif o is None:
                        warnings.append({"level": "info", "robot": r, "msg": f"{r} has never reported"})
                else:
                    if o.get("persona") and o["persona"] != self.role_of(r):
                        view["diverges"] = True
                        warnings.append({"level": "bad", "robot": r,
                                         "msg": f"{self.name(r)} still reports the {self.sources.label_of(o['persona'])} role — waiting for it to switch"})
                    if o["mic_open"] is True and not intended:
                        view["diverges"] = True
                        warnings.append({"level": "bad", "robot": r,
                                         "msg": f"{r} reports its mic OPEN but does not hold the floor"})
                    elif o["mic_open"] is False and intended and not self.transition:
                        view["diverges"] = True
                        warnings.append({"level": "warn", "robot": r,
                                         "msg": f"{r} holds the floor but reports its mic closed (still opening?)"})
                    # live speech-threshold warning against the room floor
                    room = o["rms"]
                    if room is not None:
                        thr = o["speech_threshold"]
                        if thr is None and "speech_threshold" in values:
                            thr = min(max(int(room * values.get("speech_threshold_mult", 1)),
                                          int(values["speech_threshold"])),
                                      int(values.get("speech_threshold_cap", 10 ** 6)))
                        if thr is not None and thr - room < RMS_WARN_MARGIN:
                            warnings.append({"level": "warn", "robot": r, "kind": "rms",
                                             "msg": f"{r}: room is at {int(room)}, talking counts from {int(thr)} — "
                                                    f"only {int(thr - room)} apart; raise the loudness setting or expect the mic to stay open on crowd noise"})
                observed[r] = view
                rms[r] = None if not fresh else o["rms"]
                speaking[r] = bool(o and o["speaking"]) if fresh else False
            for e in eff["errors"]:
                warnings.append({"level": "warn", "kind": "config", "msg": e})
            if self.pending:
                p = self.pending
                what = (f"floor -> {self.name(p['floor']) if p['floor'] in ROBOTS else 'no one'}" if p.get("floor") else
                        f"Panganiban -> {self.sources.machine_of(p['cjap_is'])}" if p.get("cjap_is") else
                        ", ".join(f"{k} -> {v}" for k, v in p.items()
                                  if k in ("mode", "profile") and v) or "settings")
                pending = {"what": what, "queued_s": round(now - p["queued_at"], 1),
                           "waiting_on": self._any_turn_active(now)}
            else:
                pending = None
            transition = None
            if self.transition:
                tr = self.transition
                transition = {"target": tr["target"], "elapsed_s": round(now - tr["started"], 1),
                              "settle_s": round(tr["deadline"] - tr["started"], 1)}
            auth = self.sources.authority()
            return {
                "floor": self.floor,
                "floorRole": self.floor_role,
                "cjap_is": self.cjap_is,
                "roles": {r: {"machine": self.sources.machine_of(r), "role": self.role_of(r),
                              "label": self.name(r)} for r in ROBOTS},
                "authority": {"host": auth["host"], "port": auth["port"], "url": auth["url"]},
                "floorTarget": self.transition["target"] if self.transition else self.floor,
                "transition": transition,
                "pending": pending,
                "mode": self.mode,
                "profile": self.profile,
                "observed": observed,
                "leaseTtl": self.ttl_s,
                "speaking": speaking,
                "rms": rms,
                "settings": {"effective": values, "sources": eff["sources"], "overrides": dict(self.overrides),
                             "env": eff["env"], "tunable": list(UI_TUNABLE),
                             "schema": {k: dict(s) for k, s in SETTINGS.items()}},
                "locked": self.sources.locked_state(),
                "hostIntroText": self.sources.host_intro_text(self.mode),
                "ask": {"seq": self.ask["seq"], "text": self.ask["text"], "clip": self.ask["clip"],
                        "stage": self.ask["stage"], "age_s": round(now - self.ask["at"], 1)
                        if self.ask["at"] else None},
                "duet": {"on": self.duet["on"], "line": self.duet["line"], "who": self.duet["who"],
                         "seq": self.duet["seq"]},
                "calibration": self.calib_view(now),
                "warnings": warnings,
                "seq": {"interrupt": dict(self.interrupt_seq), "intro": self.intro_seq, "config": self.config_seq},
                "consoleWall": self.wall(),
            }


# ────────────────────────────────────────────────────────────────────────────
# One dispatcher for the HTTP routes AND the tests
# ────────────────────────────────────────────────────────────────────────────
def api(console: Console, method, path, params=None, body=None, authed=False, now=None, who=None):
    """-> (http_status, json_dict). Auth is decided by the caller (the
    dashboard's shared key); robots send the same key."""
    params, body = params or {}, body if isinstance(body, dict) else {}
    who = who or body.get("who") or params.get("who") or "console"

    def need_auth():
        return (403, {"ok": False, "output": "bad key"}) if not authed else None

    if method == "GET" and path == "/api/state":
        return 200, {"ok": True, **console.state(now)}
    if method == "GET" and path == "/api/journal":
        return 200, {"ok": True, "rows": console.journal(params.get("n", 50))}
    if method == "GET" and path == "/api/lease":
        r = params.get("robot")
        ok, out, st = console.report(r, {"robot": r}, now) if r in ROBOTS else (False, "robot=alpha|beta", 400)
        return st, ({"ok": True, **out} if ok else {"ok": False, "output": out})
    if method == "POST" and path == "/api/lease":
        d = need_auth()
        if d:
            return d
        ok, out, st = console.report(body.get("robot"), body, now)
        return st, ({"ok": True, **out} if ok else {"ok": False, "output": out})
    if method == "POST" and path == "/api/floor":
        d = need_auth()
        if d:
            return d
        ok, out, st = console.request_floor(body.get("floor"), force=bool(body.get("force")), who=who, now=now)
        return st, {"ok": ok, "output": out, "floor": console.floor}
    if method == "POST" and path == "/api/role":
        d = need_auth()
        if d:
            return d
        ok, out, st = console.set_role(body.get("cjap_is"), force=bool(body.get("force")), who=who, now=now)
        return st, {"ok": ok, "output": out, "cjap_is": console.cjap_is}
    if method == "POST" and path == "/api/host-ask":
        d = need_auth()
        if d:
            return d
        ok, out, st = console.host_ask(body.get("text"), body.get("clip"), who=who, now=now)
        return st, {"ok": ok, "output": out, "ask": dict(console.ask)}
    if method == "POST" and path == "/api/config":
        d = need_auth()
        if d:
            return d
        ok, out, st = console.set_config(body.get("mode"), body.get("profile"), body.get("settings"),
                                         force=bool(body.get("force")), who=who, now=now)
        return st, {"ok": ok, "output": out, "mode": console.mode, "profile": console.profile}
    if method == "POST" and path == "/api/pending":
        d = need_auth()
        if d:
            return d
        ok, out, st = console.pending_action(body.get("action"), who=who, now=now)
        return st, {"ok": ok, "output": out}
    if method == "POST" and path == "/api/calibrate":
        d = need_auth()
        if d:
            return d
        ok, out, st = console.calibrate(body.get("action"), body.get("robot"), body.get("seconds"), who=who, now=now)
        return st, {"ok": ok, "output": out, "calibration": console.calib_view(console._now(now))}
    if method == "POST" and path == "/api/unlock-request":
        d = need_auth()
        if d:
            return d
        ok, out, st = console.unlock_request(body.get("gate"), body.get("reason"), who=who)
        return st, {"ok": ok, "output": out}
    return 404, {"ok": False, "output": f"no such endpoint {method} {path}"}


CONSOLE_PATHS_GET = ("/api/journal", "/api/lease")
CONSOLE_PATHS_POST = ("/api/lease", "/api/floor", "/api/role", "/api/config", "/api/pending",
                      "/api/host-ask",
                      "/api/calibrate", "/api/unlock-request")


def is_authority(sources: ConfigSources | None = None) -> bool:
    """True when THIS machine is the one config/robots.json names as the
    lease authority (or no authority is configured at all)."""
    import socket
    a = (sources or ConfigSources()).authority()
    return not a["host"] or a["host"].strip().lower() == socket.gethostname().split(".")[0].lower()


def authority_url(sources: ConfigSources | None = None) -> str:
    return (sources or ConfigSources()).authority()["url"]

_singleton = {}


def get_console() -> Console:
    """Process-wide instance for the dashboard."""
    c = _singleton.get("c")
    if c is None:
        c = _singleton["c"] = Console()
    return c
