"""Floor lease client — the robot side of the ONE-OPEN-MIC invariant.

Two Reachy Mini units share one installation. The operator console (served
by the maintenance dashboard, dashboard/console.py) holds a single value,
the *floor*: ``alpha`` | ``beta`` | ``none``. A robot may open its
microphone only while it holds a fresh lease on the floor.

Lease semantics (fail closed everywhere):

* the robot POSTs its observation to ``<console>/api/lease`` about once a
  second and receives the current floor;
* a response naming this robot renews the lease for ``ttl_s`` (3 s cap —
  the server may shorten it, never lengthen it);
* any other floor value, an unreachable server, a malformed reply, or a
  fresh boot (no reply yet) leaves the lease unheld — the mic closes;
* ``has_floor()`` is the ONLY question the mic code asks. It is a pure
  function of (granted, lease_until, clock), so an expired lease closes the
  mic even if the poll thread is stuck.

Role comes from ``CJ_ROBOT_ROLE`` or the hostname (cj-alpha / cj-beta). An
unknown role never holds the floor.

The same reply carries the effective settings resolved by the console
(mode profile -> drop-in -> .env -> console override); ``on_settings`` is
invoked when they change so the app can apply them live. ``interrupt_seq``
and ``intro_seq`` are monotonically increasing counters the console bumps
to ask for "cut the answer short" and "host, say the intro line".

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

ROLE_BY_HOST = {"cj-alpha": "alpha", "cj-beta": "beta"}
ROLES = ("alpha", "beta")
DEFAULT_URL = "http://127.0.0.1:8080"
TTL_CAP_S = 3.0        # never trust a longer lease than this
POLL_S = 1.0
HTTP_TIMEOUT_S = 0.8   # < POLL_S so a hung server still yields one tick per second


def robot_role() -> str | None:
    """'alpha' | 'beta' from CJ_ROBOT_ROLE, else from the hostname; None when
    neither resolves (the mic then never opens — logged loudly by the app)."""
    r = os.environ.get("CJ_ROBOT_ROLE", "").strip().lower()
    if r in ROLES:
        return r
    host = socket.gethostname().split(".")[0].strip().lower()
    return ROLE_BY_HOST.get(host)


def console_url() -> str:
    return (os.environ.get("CJ_CONSOLE_URL", "").strip() or DEFAULT_URL).rstrip("/")


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
    (exceptions are swallowed and logged so the poll loop keeps ticking)."""

    def __init__(self, role: str | None, url: str = DEFAULT_URL, *,
                 ttl_s: float = TTL_CAP_S, poll_s: float = POLL_S,
                 clock=time.monotonic, transport=None,
                 on_mic=None, on_settings=None, on_interrupt=None, on_intro=None,
                 observe=None, log=print):
        self.role = role if role in ROLES else None
        self.url = url
        self.ttl_s = min(float(ttl_s), TTL_CAP_S)
        self.poll_s = float(poll_s)
        self.clock = clock
        self.transport = transport or http_transport(url)
        self.on_mic, self.on_settings = on_mic, on_settings
        self.on_interrupt, self.on_intro = on_interrupt, on_intro
        self.observe, self.log = observe, log
        # lease state — fresh boot = nothing held
        self.granted = False
        self.lease_until = 0.0
        self.floor = None
        self.settings: dict = {}
        self.env: dict = {}            # setting -> robot env mapping, resolved by the console
        self.host_intro_text = ""
        self.mode = self.profile = None
        self.interrupt_seq = None
        self.intro_seq = None
        self.last_ok = None       # clock() of the last good reply
        self.last_error = None
        self.polls = self.failures = 0
        self._mic_state = None    # last value handed to on_mic
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.boot_id = f"{socket.gethostname()}-{os.getpid()}-{int(time.time())}"

    # ── the one question the mic code asks ────────────────────────────────
    def has_floor(self) -> bool:
        return bool(self.role) and self.granted and self.clock() < self.lease_until

    def lease_left_s(self) -> float:
        return max(0.0, self.lease_until - self.clock()) if self.granted else 0.0

    def status(self) -> dict:
        return {"role": self.role, "floor": self.floor, "has_floor": self.has_floor(),
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
        payload = {"robot": self.role, "boot_id": self.boot_id,
                   "has_floor": self.has_floor(),
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
            self.enforce()
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
            if self.role and floor == self.role:
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
            iseq, nseq = reply.get("interrupt_seq"), reply.get("intro_seq")
        self.enforce()
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
