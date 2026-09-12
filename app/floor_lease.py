"""Floor lease client — the robot side of the ONE-OPEN-MIC invariant, plus
the assignable persona (2026-09-10).

Two Reachy Mini units share one installation. Each machine occupies one
SLOT, ``alpha`` or ``beta`` — a fixed identity looked up by hostname in
``config/robots.json`` (override: ``CJ_ROBOT_SLOT``). The lease authority
(dashboard/console.py, on the machine named in ``config/robots.json``
``authority``) holds two single values:

* the *floor* — ``alpha`` | ``beta`` | ``none`` — who may open a mic;
* ``cjap_is`` — ``alpha`` | ``beta`` — who is Panganiban. The other slot is
  the Host. Two Panganibans cannot be expressed.

Lease semantics (fail closed for the MIC, hold for the PERSONA):

* the robot POSTs its observation to ``<authority>/api/lease`` about once a
  second and receives the floor, ``cjap_is``, its persona and the settings;
* a reply naming this slot as the floor renews the lease for ``ttl_s``
  (3 s cap — the server may shorten it, never lengthen it);
* any other floor value, an unreachable server, a malformed reply, or a
  fresh boot (no reply yet) leaves the lease unheld — the mic closes;
* the persona is the LAST KNOWN one: an unreachable authority never
  changes it (losing the mic is safe, losing the persona mid-sentence is
  not). A fresh boot has no persona until the first reply.

``has_floor()`` is the ONLY question the mic code asks; it is a pure
function of (granted, lease_until, clock), so an expired lease closes the
mic even if the poll thread is stuck.

Stdlib only; injectable clock and transport so it is unit-testable without
a network (tests/test_floor_lease.py).
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

SLOTS = ("alpha", "beta")
PERSONAS = ("cjap", "host")
DEFAULT_URL = "http://127.0.0.1:8080"
TTL_CAP_S = 3.0        # never trust a longer lease than this
POLL_S = 1.0
HTTP_TIMEOUT_S = 0.8   # < POLL_S so a hung server still yields one tick per second
ROBOTS_PATH = Path(__file__).resolve().parent.parent / "config" / "robots.json"

_robots_cache: dict = {}


def hostname() -> str:
    return socket.gethostname().split(".")[0].strip().lower()


def robots_config(path: Path | str = ROBOTS_PATH) -> dict:
    """config/robots.json (slots -> hostnames, authority), cached by mtime.
    Missing/invalid file -> {} (the caller falls back to env/defaults)."""
    p = str(path)
    try:
        mtime = os.path.getmtime(p)
    except OSError:
        return {}
    hit = _robots_cache.get(p)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        with open(p, encoding="utf-8") as f:
            doc = json.load(f)
        if not isinstance(doc, dict):
            doc = {}
    except (OSError, ValueError):
        doc = {}
    _robots_cache[p] = (mtime, doc)
    return doc


def robot_slot() -> str | None:
    """'alpha' | 'beta' from CJ_ROBOT_SLOT (legacy alias CJ_ROBOT_ROLE),
    else by matching the hostname in config/robots.json slots; None when
    neither resolves (the mic then never opens — logged loudly by the app)."""
    for var in ("CJ_ROBOT_SLOT", "CJ_ROBOT_ROLE"):
        r = os.environ.get(var, "").strip().lower()
        if r in SLOTS:
            return r
    host = hostname()
    for slot, name in (robots_config().get("slots") or {}).items():
        if slot in SLOTS and str(name).strip().lower() == host:
            return slot
    return None


def authority() -> dict:
    a = robots_config().get("authority") or {}
    return {"host": str(a.get("host") or "").strip().lower(),
            "port": int(a.get("port") or 8080),
            "bind": str(a.get("bind") or "0.0.0.0"),
            "ip": str(a.get("ip") or "").strip(),
            "url_template": str(a.get("url_template") or "http://{host}.local:{port}")}


def is_authority_host() -> bool:
    return bool(authority()["host"]) and authority()["host"] == hostname()


def console_url() -> str:
    """Where the lease authority answers. CJ_CONSOLE_URL wins; else derived
    from config/robots.json (loopback when this machine IS the authority)."""
    env = os.environ.get("CJ_CONSOLE_URL", "").strip()
    if env:
        return env.rstrip("/")
    a = authority()
    if not a["host"]:
        return DEFAULT_URL
    if a["host"] == hostname():
        return f"http://127.0.0.1:{a['port']}"
    if a["ip"]:
        # 2026-09-12 venue kit: an address skips mDNS, which guest networks
        # and some travel routers do not forward between clients.
        return f"http://{a['ip']}:{a['port']}"
    return a["url_template"].format(host=a["host"], port=a["port"]).rstrip("/")


def http_transport(url: str, timeout_s: float = HTTP_TIMEOUT_S):
    """Default transport: POST JSON to <url>/api/lease, return the parsed
    reply. Raises on any failure (the client treats every failure the same:
    no renewal)."""
    endpoint = url.rstrip("/") + "/api/lease"

    def _send(payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(endpoint, data=data, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            body = r.read()
        reply = json.loads(body.decode("utf-8"))
        if not isinstance(reply, dict):
            raise ValueError("lease reply is not an object")
        return reply
    return _send


class LeaseClient:
    """See module docstring. All callbacks are optional and must not raise
    (exceptions are swallowed and logged so the poll loop keeps ticking).

    on_mic(bool)                      — open/close the capture stream
    on_settings(settings, mode, profile, env)
    on_persona(persona, cjap_is)      — 'cjap' | 'host', fires on every change
                                        (including the first reply)
    on_interrupt()                    — operator "cut short"
    on_intro()                        — host: say the intro line now
    on_ask(text, clip)                — host: ask this question in the room now
                                        (2026-09-12; `clip` is a pre-recorded
                                        file name, "" = say it in its own voice)
    on_question(text)                 — cjap: answer this question live; it was
                                        typed by the operator and asked aloud by
                                        the Host, so no microphone was involved
    observe() -> dict                 — what the mic is actually doing
    """

    def __init__(self, slot: str | None, url: str = DEFAULT_URL, *,
                 ttl_s: float = TTL_CAP_S, poll_s: float = POLL_S,
                 clock=time.monotonic, transport=None,
                 on_mic=None, on_settings=None, on_persona=None,
                 on_interrupt=None, on_intro=None, on_ask=None, on_question=None,
                 observe=None, log=print):
        self.slot = slot if slot in SLOTS else None
        self.url = url
        self.ttl_s = min(float(ttl_s), TTL_CAP_S)
        self.poll_s = float(poll_s)
        self.clock = clock
        self.transport = transport or http_transport(url)
        self.on_mic, self.on_settings, self.on_persona = on_mic, on_settings, on_persona
        self.on_interrupt, self.on_intro = on_interrupt, on_intro
        self.on_ask, self.on_question = on_ask, on_question
        self.observe, self.log = observe, log
        # lease state — fresh boot = nothing held, no persona known
        self.granted = False
        self.lease_until = 0.0
        self.floor = None
        self.cjap_is = None
        self.persona = None
        self.settings: dict = {}
        self.env: dict = {}            # setting -> robot env mapping, resolved by the console
        self.host_intro_text = ""
        self.mode = self.profile = None
        self.interrupt_seq = None
        self.intro_seq = None
        self.ask_seq = None          # last ask handed to this robot (host role)
        self.ask_done = 0            # highest ask this robot finished saying
        self.question_seq = None     # last question handed to this robot (cjap role)
        self.last_ok = None       # clock() of the last good reply
        self.last_error = None
        self.polls = self.failures = 0
        self._mic_state = None    # last value handed to on_mic
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.machine = hostname()
        self.boot_id = f"{self.machine}-{os.getpid()}-{int(time.time())}"

    # legacy name — the slot used to be called "role"
    @property
    def role(self):
        return self.slot

    # ── the one question the mic code asks ────────────────────────────────
    def has_floor(self) -> bool:
        return bool(self.slot) and self.granted and self.clock() < self.lease_until

    def lease_left_s(self) -> float:
        return max(0.0, self.lease_until - self.clock()) if self.granted else 0.0

    def status(self) -> dict:
        return {"slot": self.slot, "machine": self.machine, "floor": self.floor,
                "has_floor": self.has_floor(), "persona": self.persona, "cjap_is": self.cjap_is,
                "lease_left_s": round(self.lease_left_s(), 2), "mode": self.mode,
                "profile": self.profile, "polls": self.polls, "failures": self.failures,
                "last_error": self.last_error,
                "since_ok_s": (round(self.clock() - self.last_ok, 1)
                               if self.last_ok is not None else None)}

    # ── one poll ──────────────────────────────────────────────────────────
    def poll_once(self) -> bool:
        """Report our observation, apply the reply. Returns True on a good
        reply. Never raises."""
        self.polls += 1
        payload = {"robot": self.slot, "slot": self.slot, "machine": self.machine,
                   "boot_id": self.boot_id, "has_floor": self.has_floor(),
                   "persona": self.persona,
                   # the dashboard's shared key (CJ_DASH_KEY, default "cjap") —
                   # the same gate every operator POST passes
                   "key": os.environ.get("CJ_DASH_KEY", "cjap")}
        if self.observe is not None:
            try:
                obs = self.observe() or {}
                if isinstance(obs, dict):
                    payload.update(obs)
            except Exception as e:  # observation must never block the lease
                payload["observe_error"] = f"{type(e).__name__}: {e}"
        try:
            reply = self.transport(payload)
        except Exception as e:
            self.failures += 1
            self.last_error = f"{type(e).__name__}: {str(e)[:120]}"
            self.enforce()            # mic follows the clock; persona is HELD
            return False
        try:
            self.apply(reply)
        except Exception as e:
            self.failures += 1
            self.last_error = f"bad reply: {type(e).__name__}: {str(e)[:120]}"
            self.granted = False
            self.enforce()
            return False
        return True

    def apply(self, reply: dict) -> None:
        """Apply a console reply. A reply that names us renews the lease;
        anything else revokes it immediately."""
        now = self.clock()
        floor = reply.get("floor")
        if floor not in ("alpha", "beta", "none"):
            raise ValueError(f"floor={floor!r}")
        try:
            ttl = float(reply.get("ttl", self.ttl_s))
        except (TypeError, ValueError):
            ttl = self.ttl_s
        ttl = max(0.0, min(ttl, self.ttl_s))   # server may shorten, never lengthen
        with self._lock:
            self.floor = floor
            if self.slot and floor == self.slot:
                self.granted = True
                self.lease_until = now + ttl
            else:
                self.granted = False
                self.lease_until = 0.0
            self.last_ok = now
            self.last_error = None
            settings = reply.get("settings")
            mode, profile = reply.get("mode"), reply.get("profile")
            changed = (isinstance(settings, dict) and settings != self.settings) or \
                      mode != self.mode or profile != self.profile
            if isinstance(settings, dict):
                self.settings = dict(settings)
            if isinstance(reply.get("env"), dict):
                self.env = {str(k): str(v) for k, v in reply["env"].items()}
            if isinstance(reply.get("host_intro_text"), str):
                self.host_intro_text = reply["host_intro_text"]
            self.mode, self.profile = mode, profile
            # persona: from the reply's cjap_is (authoritative), else an
            # explicit persona field; unknown -> keep what we have
            cjap_is = reply.get("cjap_is")
            persona = reply.get("persona")
            if cjap_is in SLOTS and self.slot:
                persona = "cjap" if cjap_is == self.slot else "host"
            persona_changed = persona in PERSONAS and persona != self.persona
            if cjap_is in SLOTS:
                self.cjap_is = cjap_is
            if persona in PERSONAS:
                self.persona = persona
            iseq, nseq = reply.get("interrupt_seq"), reply.get("intro_seq")
        self.enforce()
        if persona_changed and self.on_persona is not None:
            self._call(self.on_persona, self.persona, self.cjap_is)
        if changed and self.on_settings is not None:
            self._call(self.on_settings, self.settings, mode, profile, self.env)
        # counters: fire only on a CHANGE we witnessed (never on first sight —
        # a robot that boots after ten interrupts must not cut a fresh answer)
        if isinstance(iseq, int):
            if self.interrupt_seq is not None and iseq != self.interrupt_seq:
                self._call(self.on_interrupt)
            self.interrupt_seq = iseq
        if isinstance(nseq, int):
            if self.intro_seq is not None and nseq != self.intro_seq:
                self._call(self.on_intro)
            self.intro_seq = nseq
        # Host-asked question (2026-09-12). Each robot only ever sees the half
        # that belongs to its role — the authority zeroes the other. Record the
        # seq even when it is 0, or the FIRST non-zero value looks like "no
        # previous value" and is swallowed. A role swap re-points both halves at
        # this machine, so adopt the new numbers silently rather than re-asking
        # what the other robot already handled.
        aseq, qseq = reply.get("ask_seq"), reply.get("question_seq")
        if isinstance(aseq, int):
            if aseq and self.ask_seq is not None and aseq != self.ask_seq and not persona_changed:
                self._call(self.on_ask, str(reply.get("ask_text") or ""),
                           str(reply.get("ask_clip") or ""))
            self.ask_seq = aseq
        if isinstance(qseq, int):
            if qseq and self.question_seq is not None and qseq != self.question_seq and not persona_changed:
                self._call(self.on_question, str(reply.get("question_text") or ""))
            self.question_seq = qseq

    def enforce(self) -> bool:
        """Push the current answer of has_floor() to on_mic (only on change).
        Called after every poll, every failure, and by the poll loop each
        tick, so an expired lease closes the mic within one tick."""
        want = self.has_floor()
        if want != self._mic_state:
            self._mic_state = want
            self._call(self.on_mic, want)
        return want

    def _call(self, fn, *args):
        if fn is None:
            return
        try:
            fn(*args)
        except Exception as e:
            try:
                self.log(f"[floor] callback {getattr(fn, '__name__', fn)} failed: "
                         f"{type(e).__name__}: {e}")
            except Exception:
                pass

    # ── background loop ───────────────────────────────────────────────────
    def run(self) -> None:
        while not self._stop.is_set():
            t0 = self.clock()
            self.poll_once()
            self.enforce()
            self._stop.wait(max(0.05, self.poll_s - (self.clock() - t0)))
        self.granted = False
        self.enforce()

    def start(self) -> "LeaseClient":
        if self._thread is None:
            self._thread = threading.Thread(target=self.run, name="floor-lease", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
