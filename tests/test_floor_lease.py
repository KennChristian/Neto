"""Operator console / floor lease tests ($0, offline, deterministic clock).

Run:  app/.venv/bin/python -m pytest tests/test_floor_lease.py -q

What is asserted:
  * INVARIANT — no sequence of API calls (random, seeded, through the same
    `console.api` dispatcher the HTTP routes use) ever leaves both robots
    holding the floor;
  * with two simulated robots polling the console (TTL 3 s, dropped polls,
    unreachable server), both mics are never open at the same instant and a
    grant is never issued while the other mic is still open
    (close-both-then-open);
  * an expired lease closes the mic; an unreachable server closes the mic;
    a fresh boot holds nothing; a server TTL longer than 3 s is capped;
  * duet mode forces the floor to none and refuses floor requests;
  * a change that arrives mid-answer drains (queued, applied at turn end)
    unless the operator cuts short (interrupt_seq bumps);
  * config resolves profile -> drop-in -> .env -> override, per key;
  * locked gates cannot be changed here; an unlock request needs a reason
    and only journals.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))
sys.path.insert(0, str(ROOT / "app"))

import console as cs          # noqa: E402
import floor_lease as fl      # noqa: E402

ROBOTS = cs.ROBOTS


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s
        return self.t


def make_console(tmp_path, clock, **kw):
    src = cs.ConfigSources(modes_dir=str(ROOT / "config" / "modes"),
                           dropin_path=str(tmp_path / "absent.conf"),
                           dotenv_path=str(tmp_path / "absent.env"),
                           robots_path=str(ROOT / "config" / "robots.json"))
    return cs.Console(src, clock=clock, wall=clock, state_path=str(tmp_path / "state.json"),
                      journal_path=str(tmp_path / "journal.jsonl"), log=lambda *a, **k: None,
                      restore=False, **kw)


def lease(c, robot, now, **obs):
    body = {"robot": robot, **obs}
    st, d = cs.api(c, "POST", "/api/lease", body=body, authed=True, now=now)
    assert st == 200, d
    return d


def granted(c, now):
    return {r: lease(c, r, now)["granted"] for r in ROBOTS}


# ────────────────────────────────────────────────────────────────────────────
# 1. the invariant, under random API sequences
# ────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("seed", range(25))
def test_no_api_sequence_grants_both(tmp_path, seed):
    rng = random.Random(seed)
    clock = Clock()
    c = make_console(tmp_path, clock)
    for _ in range(300):
        op = rng.choice(["floor", "floor", "role", "config", "report", "pending", "wait", "state"])
        now = clock()
        if op == "role":
            cs.api(c, "POST", "/api/role", body={"cjap_is": rng.choice(cs.ROBOTS),
                                                 "force": rng.random() < 0.3}, authed=True, now=now)
        elif op == "floor":
            cs.api(c, "POST", "/api/floor", body={"floor": rng.choice(cs.FLOORS),
                                                  "force": rng.random() < 0.3}, authed=True, now=now)
        elif op == "config":
            body = {}
            if rng.random() < 0.5:
                body["mode"] = rng.choice(cs.MODES)
            if rng.random() < 0.5:
                body["profile"] = rng.choice(cs.PROFILES)
            if rng.random() < 0.5:
                body["settings"] = {"speech_threshold": rng.randint(50, 5000),
                                    "wake_word": rng.random() < 0.5}
            body["force"] = rng.random() < 0.3
            cs.api(c, "POST", "/api/config", body=body, authed=True, now=now)
        elif op == "report":
            r = rng.choice(ROBOTS)
            lease(c, r, now, mic_open=rng.random() < 0.5, turn_active=rng.random() < 0.4,
                  speaking=rng.random() < 0.3, rms=rng.randint(50, 1500))
        elif op == "pending":
            cs.api(c, "POST", "/api/pending", body={"action": rng.choice(["cut", "cancel"])},
                   authed=True, now=now)
        elif op == "wait":
            clock.advance(rng.choice([0.2, 0.9, 1.1, 3.6, 6.0]))
        st, doc = cs.api(c, "GET", "/api/state", now=clock())
        assert st == 200 and doc["floor"] in cs.FLOORS
        g = granted(c, clock())
        assert not (g["alpha"] and g["beta"]), f"seed {seed}: both granted: {g}"
        assert sum(g.values()) <= 1
        if doc["mode"] == "duet":
            assert doc["floor"] == "none" and not any(g.values())
        # exactly one Panganiban, always — from the state AND from what each robot is told
        personas = {r: lease(c, r, clock())["persona"] for r in ROBOTS}
        assert sorted(personas.values()) == ["cjap", "host"], personas
        assert doc["cjap_is"] in ROBOTS and personas[doc["cjap_is"]] == "cjap"
        assert [r for r, x in doc["roles"].items() if x["role"] == "cjap"] == [doc["cjap_is"]]


# ────────────────────────────────────────────────────────────────────────────
# 2. two robots on the wire: TTL, dropped polls, close-both-then-open
# ────────────────────────────────────────────────────────────────────────────
class SimRobot:
    """A floor_lease.LeaseClient wired to the console through an in-process
    transport that can be told to fail (unreachable server)."""

    def __init__(self, role, console, clock, other_mic, log):
        self.role, self.console, self.clock = role, console, clock
        self.mic_open = False
        self.turn_active = False
        self.unreachable = False
        self.grants_seen = 0
        self.other_mic = other_mic   # callable -> the OTHER robot's mic state
        self.log = log
        self.client = fl.LeaseClient(role, "sim://", ttl_s=3.0, poll_s=1.0, clock=clock,
                                     transport=self._transport, on_mic=self._on_mic,
                                     observe=self._observe, log=lambda *a: None)

    def _observe(self):
        return {"mic_open": self.mic_open, "turn_active": self.turn_active,
                "rms": 300, "speaking": self.turn_active, "persona": self.client.persona}

    def _on_mic(self, want):
        self.mic_open = want

    def _transport(self, payload):
        if self.unreachable:
            raise ConnectionError("server unreachable")
        st, reply = cs.api(self.console, "POST", "/api/lease", body=payload, authed=True, now=self.clock())
        assert st == 200
        if reply["granted"]:
            self.grants_seen += 1
            # close-both-then-open: never a grant while the other mic is open
            assert self.other_mic() is False, (
                f"{self.role} granted at t={self.clock():.1f} while the other mic is open")
        return reply

    def poll(self):
        self.client.poll_once()
        self.client.enforce()


@pytest.mark.parametrize("seed", range(20))
def test_two_robots_never_both_open(tmp_path, seed):
    rng = random.Random(1000 + seed)
    clock = Clock()
    c = make_console(tmp_path, clock)
    robots = {}
    robots["alpha"] = SimRobot("alpha", c, clock, lambda: robots["beta"].mic_open, None)
    robots["beta"] = SimRobot("beta", c, clock, lambda: robots["alpha"].mic_open, None)
    next_poll = {"alpha": 0.0, "beta": 0.4}
    both_open_ever = False
    grants = 0
    for step in range(1500):                 # 150 s of simulated time, 0.1 s steps
        now = clock()
        for r, rb in robots.items():
            if now >= next_poll[r]:
                if rng.random() < 0.15:      # a dropped poll now and then
                    next_poll[r] = now + 1.0
                    continue
                rb.poll()
                next_poll[r] = now + 1.0
        # the model's own tick: expiry is a pure function of the clock
        for rb in robots.values():
            rb.client.enforce()
        if rng.random() < 0.04:
            cs.api(c, "POST", "/api/floor", body={"floor": rng.choice(cs.FLOORS),
                                                  "force": rng.random() < 0.5}, authed=True, now=now)
        if rng.random() < 0.02:
            cs.api(c, "POST", "/api/config", body={"mode": rng.choice(cs.MODES), "force": True},
                   authed=True, now=now)
        if rng.random() < 0.03:
            cs.api(c, "POST", "/api/role", body={"cjap_is": rng.choice(cs.ROBOTS), "force": rng.random() < 0.5},
                   authed=True, now=now)
        if rng.random() < 0.02:
            r = rng.choice(ROBOTS)
            robots[r].unreachable = not robots[r].unreachable
        if rng.random() < 0.05:
            r = rng.choice(ROBOTS)
            robots[r].turn_active = not robots[r].turn_active
        if robots["alpha"].mic_open and robots["beta"].mic_open:
            both_open_ever = True
        assert not both_open_ever, f"seed {seed} step {step}: both mics open"
        # a robot that cannot reach the console must be closed within the TTL
        for r, rb in robots.items():
            if rb.unreachable and rb.client.last_ok is not None and now - rb.client.last_ok > 3.0:
                assert rb.mic_open is False, f"{r} still open {now - rb.client.last_ok:.1f}s after last contact"
        clock.advance(0.1)
        grants += sum(rb.grants_seen for rb in robots.values())
    assert grants > 0, "simulation never granted anything — test is vacuous"


# ────────────────────────────────────────────────────────────────────────────
# 3. client-side fail-closed
# ────────────────────────────────────────────────────────────────────────────
def _client(clock, replies, role="alpha"):
    mic = []

    def transport(payload):
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    cl = fl.LeaseClient(role, "sim://", clock=clock, transport=transport,
                        on_mic=mic.append, log=lambda *a: None)
    return cl, mic


def test_fresh_boot_holds_nothing():
    clock = Clock()
    cl, mic = _client(clock, [])
    assert cl.has_floor() is False
    cl.enforce()
    assert mic == [False]


def test_expired_lease_closes_mic():
    clock = Clock()
    cl, mic = _client(clock, [{"floor": "alpha", "ttl": 3.0}])
    assert cl.poll_once() and cl.has_floor() and mic[-1] is True
    clock.advance(2.9)
    assert cl.has_floor()
    clock.advance(0.2)                       # 3.1 s since the grant, no poll in between
    assert cl.has_floor() is False
    cl.enforce()                             # the run loop calls this every tick
    assert mic[-1] is False


def test_unreachable_server_closes_mic_after_ttl():
    clock = Clock()
    cl, mic = _client(clock, [{"floor": "alpha", "ttl": 3.0},
                              ConnectionError("down"), ConnectionError("down"),
                              ConnectionError("down"), ConnectionError("down")])
    cl.poll_once()
    assert mic[-1] is True
    for _ in range(4):
        clock.advance(1.0)
        cl.poll_once()
    assert cl.has_floor() is False and mic[-1] is False
    assert cl.failures == 4 and "down" in cl.last_error


def test_server_ttl_is_capped_at_three_seconds():
    clock = Clock()
    cl, mic = _client(clock, [{"floor": "alpha", "ttl": 100}])
    cl.poll_once()
    clock.advance(3.01)
    assert cl.has_floor() is False


def test_floor_moving_away_revokes_on_next_poll():
    clock = Clock()
    cl, mic = _client(clock, [{"floor": "alpha", "ttl": 3.0}, {"floor": "none", "ttl": 3.0},
                              {"floor": "beta", "ttl": 3.0}])
    cl.poll_once(); assert mic[-1] is True
    clock.advance(0.5); cl.poll_once(); assert mic[-1] is False and cl.has_floor() is False
    clock.advance(0.5); cl.poll_once(); assert cl.has_floor() is False


def test_unknown_role_never_opens():
    clock = Clock()
    cl, mic = _client(clock, [{"floor": "alpha", "ttl": 3.0}], role=None)
    cl.poll_once()
    assert cl.has_floor() is False and True not in mic


def test_malformed_reply_revokes():
    clock = Clock()
    cl, mic = _client(clock, [{"floor": "alpha", "ttl": 3.0}, {"floor": "both"}])
    cl.poll_once(); assert mic[-1] is True
    cl.poll_once(); assert mic[-1] is False and "bad reply" in cl.last_error


def test_counters_fire_only_on_witnessed_change():
    clock = Clock()
    fired = []
    replies = [{"floor": "none", "interrupt_seq": 7, "intro_seq": 2},
               {"floor": "none", "interrupt_seq": 7, "intro_seq": 2},
               {"floor": "none", "interrupt_seq": 8, "intro_seq": 3}]
    cl = fl.LeaseClient("alpha", "sim://", clock=clock, transport=lambda p: replies.pop(0),
                        on_interrupt=lambda: fired.append("cut"), on_intro=lambda: fired.append("intro"),
                        log=lambda *a: None)
    cl.poll_once(); cl.poll_once()
    assert fired == []                       # first sight of 7/2 must not fire
    cl.poll_once()
    assert fired == ["cut", "intro"]


# ────────────────────────────────────────────────────────────────────────────
# 4. console behaviour
# ────────────────────────────────────────────────────────────────────────────
def test_floor_transition_closes_both_then_opens(tmp_path):
    clock = Clock()
    c = make_console(tmp_path, clock)
    st, d = cs.api(c, "POST", "/api/floor", body={"floor": "alpha"}, authed=True, now=clock())
    assert st == 200 and d["ok"]
    assert c.floor == "none" and c.transition["target"] == "alpha"      # closed first
    g = granted(c, clock())
    assert not any(g.values())
    clock.advance(1.0)
    assert not lease(c, "alpha", clock())["granted"]                      # still settling
    clock.advance(2.6)                                                    # > ttl + margin
    assert lease(c, "alpha", clock())["granted"]
    # alpha -> beta: alpha must be revoked before beta is named
    cs.api(c, "POST", "/api/floor", body={"floor": "beta"}, authed=True, now=clock())
    assert not lease(c, "alpha", clock())["granted"]
    assert not lease(c, "beta", clock())["granted"]
    # both report closed after the move began -> early completion
    clock.advance(0.3)
    lease(c, "alpha", clock(), mic_open=False)
    lease(c, "beta", clock(), mic_open=False)
    assert c.floor == "beta"
    assert lease(c, "beta", clock())["granted"] and not lease(c, "alpha", clock())["granted"]


def test_duet_forces_none_and_refuses_floor(tmp_path):
    clock = Clock()
    c = make_console(tmp_path, clock)
    cs.api(c, "POST", "/api/floor", body={"floor": "alpha"}, authed=True, now=clock())
    clock.advance(4)
    assert lease(c, "alpha", clock())["granted"]
    st, d = cs.api(c, "POST", "/api/config", body={"mode": "duet"}, authed=True, now=clock())
    assert st == 200 and c.mode == "duet" and c.floor == "none" and c.transition is None
    st, d = cs.api(c, "POST", "/api/floor", body={"floor": "beta"}, authed=True, now=clock())
    assert st == 409 and not d["ok"]
    clock.advance(10)
    assert not any(granted(c, clock()).values())
    cs.api(c, "POST", "/api/config", body={"mode": "direct"}, authed=True, now=clock())
    # direct: the floor follows the role — with the intro on, the Host holds it first
    assert c.floor == "none" and c.transition["target"] == c.slot_of("host") and c.floor_role == "host"


def test_mid_answer_change_drains_unless_cut(tmp_path):
    clock = Clock()
    c = make_console(tmp_path, clock)
    cs.api(c, "POST", "/api/floor", body={"floor": "alpha"}, authed=True, now=clock())
    clock.advance(4)
    lease(c, "alpha", clock(), mic_open=True, turn_active=True)
    st, d = cs.api(c, "POST", "/api/floor", body={"floor": "beta"}, authed=True, now=clock())
    assert st == 202 and "queued" in d["output"]
    assert c.floor == "alpha" and c.pending["floor"] == "beta"           # not interrupted
    seq_before = c.interrupt_seq["alpha"]
    clock.advance(1)
    lease(c, "alpha", clock(), mic_open=True, turn_active=True)
    assert c.floor == "alpha"                                            # still draining
    clock.advance(1)
    lease(c, "alpha", clock(), mic_open=True, turn_active=False)         # turn ended
    assert c.pending is None and c.floor == "none" and c.transition["target"] == "beta"
    assert c.interrupt_seq["alpha"] == seq_before                        # never cut
    # now the explicit override
    clock.advance(4)
    lease(c, "beta", clock(), mic_open=True, turn_active=True)
    cs.api(c, "POST", "/api/floor", body={"floor": "alpha"}, authed=True, now=clock())
    assert c.pending is not None
    st, d = cs.api(c, "POST", "/api/pending", body={"action": "cut"}, authed=True, now=clock())
    assert st == 200 and c.pending is None and c.interrupt_seq["beta"] == 1
    assert lease(c, "beta", clock())["interrupt_seq"] == 1
    # a mode change mid-answer drains too
    clock.advance(4)
    lease(c, "alpha", clock(), mic_open=True, turn_active=True)
    st, d = cs.api(c, "POST", "/api/config", body={"mode": "duet"}, authed=True, now=clock())
    assert st == 202 and c.mode == "direct" and c.floor == "alpha"
    st, d = cs.api(c, "POST", "/api/config", body={"mode": "duet", "force": True}, authed=True, now=clock())
    assert st == 200 and c.mode == "duet" and c.floor == "none"


def test_state_document_shape_and_divergence_warning(tmp_path):
    clock = Clock()
    c = make_console(tmp_path, clock)
    st, doc = cs.api(c, "GET", "/api/state", now=clock())
    for k in ("floor", "mode", "profile", "observed", "leaseTtl", "speaking", "rms", "settings",
              "locked", "warnings", "pending"):
        assert k in doc, k
    assert set(doc["observed"]) == set(ROBOTS) and set(doc["rms"]) == set(ROBOTS)
    assert doc["leaseTtl"] == 3.0
    # observed is what the robot said, not the intended value
    cs.api(c, "POST", "/api/floor", body={"floor": "alpha"}, authed=True, now=clock())
    clock.advance(4)
    lease(c, "alpha", clock(), mic_open=False, rms=900)
    lease(c, "beta", clock(), mic_open=True, rms=100)
    doc = cs.api(c, "GET", "/api/state", now=clock())[1]
    assert doc["floor"] == "alpha"
    assert doc["observed"]["alpha"]["intended"] == "open" and doc["observed"]["alpha"]["mic"] is False
    assert doc["observed"]["beta"]["intended"] == "closed" and doc["observed"]["beta"]["mic"] is True
    assert doc["observed"]["alpha"]["diverges"] and doc["observed"]["beta"]["diverges"]
    assert any(w["robot"] == "beta" and w["level"] == "bad" for w in doc["warnings"])
    assert doc["rms"] == {"alpha": 900, "beta": 100}
    # speech-threshold warning: kiosk cap 1500 vs room 900 -> 600 apart, no warning;
    # room 1200 -> 300 apart -> warning
    assert not any(w.get("kind") == "rms" and w["robot"] == "alpha" for w in doc["warnings"])
    lease(c, "alpha", clock(), mic_open=True, rms=1200)
    doc = cs.api(c, "GET", "/api/state", now=clock())[1]
    assert any(w.get("kind") == "rms" and w["robot"] == "alpha" for w in doc["warnings"])
    # a stale report becomes unknown, not a stale echo
    clock.advance(5)
    doc = cs.api(c, "GET", "/api/state", now=clock())[1]
    assert doc["observed"]["alpha"]["mic"] is None and doc["observed"]["alpha"]["fresh"] is False


def test_no_sequence_produces_two_cjap(tmp_path):
    """Structural: cjap_is is one value; role_of() derives both personas."""
    clock = Clock()
    c = make_console(tmp_path, clock)
    for bad in ("both", "alpha,beta", None, ["alpha", "beta"], "cjap"):
        st, d = cs.api(c, "POST", "/api/role", body={"cjap_is": bad}, authed=True, now=clock())
        assert st == 400
    for want in ("beta", "alpha", "beta", "beta"):
        st, d = cs.api(c, "POST", "/api/role", body={"cjap_is": want}, authed=True, now=clock())
        assert st == 200 and c.cjap_is == want
        assert {r: c.role_of(r) for r in ROBOTS} == {want: "cjap", ("alpha" if want == "beta" else "beta"): "host"}
        assert sorted(lease(c, r, clock())["persona"] for r in ROBOTS) == ["cjap", "host"]


def test_role_swap_in_direct_moves_floor(tmp_path):
    clock = Clock()
    c = make_console(tmp_path, clock)
    # intro off so entering direct hands the floor straight to Panganiban
    cs.api(c, "POST", "/api/config", body={"mode": "duet"}, authed=True, now=clock())
    cs.api(c, "POST", "/api/config", body={"mode": "direct", "settings": {"host_intro": False}},
           authed=True, now=clock())
    assert c.cjap_is == "alpha" and c.floor_role == "cjap" and c.transition["target"] == "alpha"
    clock.advance(4); c.tick()
    assert c.floor == "alpha" and lease(c, "alpha", clock())["granted"]
    # swap: Panganiban -> beta. The floor is bound to the cjap ROLE, so it moves.
    st, d = cs.api(c, "POST", "/api/role", body={"cjap_is": "beta"}, authed=True, now=clock())
    assert st == 200
    assert c.floor == "none" and c.transition["target"] == "beta"      # closed both first
    assert not lease(c, "alpha", clock())["granted"] and not lease(c, "beta", clock())["granted"]
    assert lease(c, "alpha", clock())["persona"] == "host" and lease(c, "beta", clock())["persona"] == "cjap"
    clock.advance(4)
    assert lease(c, "beta", clock())["granted"] and not lease(c, "alpha", clock())["granted"]
    # the same swap with the floor bound to the HOST role moves it to the new host
    cs.api(c, "POST", "/api/floor", body={"floor": "alpha"}, authed=True, now=clock())   # alpha is host now
    assert c.floor_role == "host"
    clock.advance(4); c.tick()
    cs.api(c, "POST", "/api/role", body={"cjap_is": "alpha"}, authed=True, now=clock())
    assert c.transition["target"] == "beta" and c.floor_role == "host"
    # in duet the floor stays none through a swap
    cs.api(c, "POST", "/api/config", body={"mode": "duet"}, authed=True, now=clock())
    cs.api(c, "POST", "/api/role", body={"cjap_is": "beta"}, authed=True, now=clock())
    clock.advance(4); c.tick()
    assert c.floor == "none" and c.transition is None
    # a role swap mid-answer drains like everything else
    cs.api(c, "POST", "/api/config", body={"mode": "direct", "settings": {"host_intro": False}},
           authed=True, now=clock())
    clock.advance(4)
    lease(c, "beta", clock(), mic_open=True, turn_active=True)
    st, d = cs.api(c, "POST", "/api/role", body={"cjap_is": "alpha"}, authed=True, now=clock())
    assert st == 202 and c.cjap_is == "beta" and c.pending["cjap_is"] == "alpha"
    lease(c, "beta", clock(), mic_open=True, turn_active=False)
    assert c.cjap_is == "alpha" and c.pending is None


def test_intro_handoff_host_then_panganiban(tmp_path):
    clock = Clock()
    c = make_console(tmp_path, clock)
    cs.api(c, "POST", "/api/config", body={"mode": "duet"}, authed=True, now=clock())
    cs.api(c, "POST", "/api/config", body={"mode": "direct", "settings": {"host_intro": None}},
           authed=True, now=clock())
    host, cjap = c.slot_of("host"), c.slot_of("cjap")
    assert c.floor_role == "host" and c.transition["target"] == host and c.intro_seq == 1
    clock.advance(4)
    r = lease(c, host, clock(), mic_open=True, intro_done=0)
    assert r["granted"] and r["intro_seq"] == 1
    # host reports the intro done -> floor hands over to Panganiban (close both first)
    lease(c, host, clock(), mic_open=True, intro_done=1)
    assert c.floor == "none" and c.transition["target"] == cjap and c.floor_role == "cjap"
    clock.advance(4)
    assert lease(c, cjap, clock())["granted"] and not lease(c, host, clock())["granted"]
    # a stale intro_done never hands over twice
    lease(c, host, clock(), mic_open=False, intro_done=1)
    assert c.floor == cjap


def test_client_holds_persona_when_authority_unreachable():
    clock = Clock()
    seen = []
    replies = [{"floor": "alpha", "ttl": 3.0, "cjap_is": "alpha"},
               ConnectionError("down"), ConnectionError("down"), ConnectionError("down"),
               {"floor": "alpha", "ttl": 3.0, "cjap_is": "beta"}]
    mic = []
    cl = fl.LeaseClient("alpha", "sim://", clock=clock, transport=lambda p: (_ for _ in ()).throw(replies[0])
                        if isinstance(replies[0], Exception) and replies.pop(0) else replies.pop(0),
                        on_mic=mic.append, on_persona=lambda p, w: seen.append((p, w)), log=lambda *a: None)
    assert cl.persona is None                          # fresh boot: no persona yet
    cl.poll_once()
    assert cl.persona == "cjap" and seen == [("cjap", "alpha")] and mic[-1] is True
    for _ in range(3):
        clock.advance(1.2)
        cl.poll_once()
    assert cl.persona == "cjap" and cl.has_floor() is False and mic[-1] is False   # mic gone, role held
    cl.poll_once()
    assert cl.persona == "host" and seen[-1] == ("host", "beta")


def test_config_resolution_order(tmp_path):
    modes = tmp_path / "modes"
    modes.mkdir()
    (modes / "direct.json").write_text(json.dumps({
        "mode": "direct", "host_intro_text": "hello",
        "defaults": {"wake_word": True, "wake_threshold": 0.01, "speech_threshold": 100,
                     "speech_threshold_mult": 2.0, "speech_threshold_cap": 1000,
                     "silence_timeout_s": 1.0, "post_answer_window_s": 20, "host_intro": True,
                     "dry_run": False},
        "profiles": {"kiosk": {}, "event": {"wake_word": False, "speech_threshold": 700,
                                             "post_answer_window_s": 0}}}))
    (modes / "duet.json").write_text(json.dumps({"mode": "duet", "defaults": {}, "profiles": {}}))
    dropin = tmp_path / "wakeword.conf"
    dropin.write_text("[Service]\n# comment\nEnvironment=CJ_MIC_RMS_FLOOR=250\n"
                      "Environment=\"CJ_WAKE_PHRASE=Hi Cee-Jap\"\nEnvironment=CJ_LISTEN_IDLE_S=25\n")
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENAI_API_KEY=secret\nCJ_LISTEN_IDLE_S=30\n")
    src = cs.ConfigSources(modes_dir=str(modes), dropin_path=str(dropin), dotenv_path=str(dotenv))
    v, s, errs = src.resolve("direct", "event", {"silence_timeout_s": 2.5})
    assert errs == []
    assert v["wake_word"] is False and s["wake_word"].endswith("/event")
    assert v["speech_threshold"] == 250 and s["speech_threshold"] == "systemd drop-in"   # drop-in beats profile
    assert v["post_answer_window_s"] == 30 and s["post_answer_window_s"] == "app/.env"    # .env beats drop-in
    assert v["silence_timeout_s"] == 2.5 and s["silence_timeout_s"] == "console override"
    assert v["wake_threshold"] == 0.01 and s["wake_threshold"].endswith("defaults")
    c = cs.Console(src, clock=Clock(), wall=Clock(), state_path=str(tmp_path / "s.json"),
                   journal_path=str(tmp_path / "j.jsonl"), log=lambda *a, **k: None, restore=False)
    cs.api(c, "POST", "/api/config", body={"profile": "event", "settings": {"post_answer_window_s": 0}},
           authed=True)
    env = c.lease_for("alpha")["env"]
    assert env["CJ_LISTEN_IDLE_S"] == "0" and env["CJ_ALWAYS_LISTEN"] == "0"
    assert env["CJ_WAKE_LISTEN"] == "0" and env["CJ_MIC_RMS_FLOOR"] == "250"
    # the effective config is journaled with sources on every change
    rows = [r for r in c.journal(50) if r["kind"] == "config"]
    assert rows and rows[-1]["sources"]["post_answer_window_s"] == "console override"
    # secrets never leak into what the robots receive
    assert "OPENAI_API_KEY" not in json.dumps(c.lease_for("alpha"))


def test_settings_validation_and_locked_gates(tmp_path):
    clock = Clock()
    c = make_console(tmp_path, clock)
    st, d = cs.api(c, "POST", "/api/config", body={"settings": {"speech_threshold": 99999}},
                   authed=True, now=clock())
    assert st == 400 and "outside" in d["output"]
    st, d = cs.api(c, "POST", "/api/config", body={"settings": {"speech_threshold_cap": 5}},
                   authed=True, now=clock())
    assert st == 400 and "profile" in d["output"]
    for gate in cs.LOCKED_GATES:
        st, d = cs.api(c, "POST", "/api/config", body={"settings": {gate: False}}, authed=True, now=clock())
        assert st == 400
    locked_before = json.dumps(c.state()["locked"], sort_keys=True)
    st, d = cs.api(c, "POST", "/api/unlock-request", body={"gate": "fact_audit", "reason": "no"},
                   authed=True, now=clock())
    assert st == 400
    st, d = cs.api(c, "POST", "/api/unlock-request",
                   body={"gate": "fact_audit", "reason": "rehearsal only, sound check at 9am"},
                   authed=True, now=clock())
    assert st == 200 and d["ok"]
    assert json.dumps(c.state()["locked"], sort_keys=True) == locked_before
    rows = c.journal(10)
    assert rows[-1]["kind"] == "unlock-request" and rows[-1]["gate"] == "fact_audit"
    # auth is required for every mutating call
    for path, body in (("/api/floor", {"floor": "alpha"}), ("/api/config", {"mode": "duet"}),
                       ("/api/lease", {"robot": "alpha"}), ("/api/pending", {"action": "cut"}),
                       ("/api/unlock-request", {"gate": "fact_audit", "reason": "long enough reason"})):
        st, d = cs.api(c, "POST", path, body=body, authed=False, now=clock())
        assert st == 403, path


def test_restart_retakes_floor_through_transition(tmp_path):
    clock = Clock()
    c = make_console(tmp_path, clock)
    cs.api(c, "POST", "/api/floor", body={"floor": "beta"}, authed=True, now=clock())
    clock.advance(4)
    c.tick()                                 # transitions complete on the next request/tick
    assert c.floor == "beta"
    src = c.sources
    c2 = cs.Console(src, clock=clock, wall=clock, state_path=str(tmp_path / "state.json"),
                    journal_path=str(tmp_path / "journal.jsonl"), log=lambda *a, **k: None, restore=True)
    assert c2.floor == "none" and c2.transition["target"] == "beta"      # never straight back
    assert not lease(c2, "beta", clock())["granted"]
    clock.advance(4)
    assert lease(c2, "beta", clock())["granted"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ────────────────────────────────────────────────────────────────────────────
# 5. modes and the shipped profiles (step 2)
# ────────────────────────────────────────────────────────────────────────────
def test_shipped_profiles_direct_kiosk_vs_event(tmp_path):
    src = cs.ConfigSources(modes_dir=str(ROOT / "config" / "modes"),
                           dropin_path=str(tmp_path / "absent.conf"), dotenv_path=str(tmp_path / "absent.env"),
                           robots_path=str(ROOT / "config" / "robots.json"))
    kiosk, _, e1 = src.resolve("direct", "kiosk", {})
    event, _, e2 = src.resolve("direct", "event", {})
    assert e1 == [] and e2 == []
    assert kiosk["wake_word"] is True and kiosk["post_answer_window_s"] > 0
    assert event["wake_word"] is False                      # mic gated by the handheld transmitter
    assert event["post_answer_window_s"] == 0               # zero post-answer window
    assert event["speech_threshold"] > kiosk["speech_threshold"]
    duet, _, e3 = src.resolve("duet", "kiosk", {})
    assert e3 == [] and duet["wake_word"] is False


def test_duet_never_grants_and_direct_event_env(tmp_path):
    clock = Clock()
    c = make_console(tmp_path, clock)
    cs.api(c, "POST", "/api/config", body={"mode": "duet", "profile": "event"}, authed=True, now=clock())
    for _ in range(20):
        clock.advance(1.0)
        for r in ROBOTS:
            reply = lease(c, r, clock(), mic_open=False, turn_active=False)
            assert reply["granted"] is False and reply["mode"] == "duet"
        assert c.floor == "none"
    cs.api(c, "POST", "/api/config", body={"mode": "direct", "settings": {"host_intro": False}}, authed=True, now=clock())
    clock.advance(4)
    env = lease(c, c.cjap_is, clock())["env"]
    assert env["CJ_WAKE_LISTEN"] == "0" and env["CJ_LISTEN_IDLE_S"] == "0" and env["CJ_ALWAYS_LISTEN"] == "0"
    cs.api(c, "POST", "/api/config", body={"profile": "kiosk"}, authed=True, now=clock())
    env = lease(c, c.cjap_is, clock())["env"]
    assert env["CJ_WAKE_LISTEN"] == "1" and float(env["CJ_LISTEN_IDLE_S"]) > 0


# ────────────────────────────────────────────────────────────────────────────
# 6. room calibration + per-turn threshold journal
# ────────────────────────────────────────────────────────────────────────────
def test_room_calibration_proposes_and_applies_only_on_accept(tmp_path):
    clock = Clock()
    c = make_console(tmp_path, clock)
    st, d = cs.api(c, "POST", "/api/calibrate", body={"action": "start", "robot": "alpha", "seconds": 20},
                   authed=True, now=clock())
    assert st == 409 and "floor" in d["output"]                    # mic must be open on that robot
    cs.api(c, "POST", "/api/floor", body={"floor": "alpha"}, authed=True, now=clock())
    clock.advance(4); c.tick()
    st, d = cs.api(c, "POST", "/api/calibrate", body={"action": "start", "robot": "alpha", "seconds": 20},
                   authed=True, now=clock())
    assert st == 200 and d["calibration"]["status"] == "running"
    rng = random.Random(7)
    for i in range(21):                                            # 21 one-second reports
        clock.advance(1.0)
        peak = 900 + rng.randint(0, 300) + (2000 if i == 10 else 0)   # one loud second
        lease(c, "alpha", clock(), mic_open=True, rms=850, rms_1s={"p50": 880, "max": peak, "min": 700})
    view = c.state()["calibration"]
    assert view["status"] == "done" and view["n"] >= 20
    res = view["result"]
    assert res["peaks"]["max"] >= 2900 and 900 <= res["peaks"]["p50"] <= 1200
    prop = res["proposal"]
    assert prop["speech_threshold"] == -(-(res["peaks"]["p95"] + cs.CALIB_HEADROOM) // 10) * 10
    assert prop["speech_threshold_cap"] >= 2 * prop["speech_threshold"]
    before = c.effective()["values"]["speech_threshold"]
    st, d = cs.api(c, "POST", "/api/calibrate", body={"action": "reject"}, authed=True, now=clock())
    assert st == 200 and c.effective()["values"]["speech_threshold"] == before and c.calib is None
    # again, accept this time
    cs.api(c, "POST", "/api/calibrate", body={"action": "start", "robot": "alpha", "seconds": 10}, authed=True, now=clock())
    for _ in range(11):
        clock.advance(1.0)
        lease(c, "alpha", clock(), mic_open=True, rms=850, rms_1s={"p50": 880, "max": 1000, "min": 700})
    st, d = cs.api(c, "POST", "/api/calibrate", body={"action": "accept"}, authed=True, now=clock())
    assert st == 200
    eff = c.effective()
    assert eff["values"]["speech_threshold"] == 1400 and eff["sources"]["speech_threshold"] == "console override"
    assert eff["values"]["speech_threshold_cap"] >= 2800
    assert any(r["kind"] == "calibrate" and "ACCEPTED" in r["msg"] for r in c.journal(20))


def test_turn_journals_resolved_threshold(tmp_path):
    clock = Clock()
    c = make_console(tmp_path, clock)
    lease(c, "alpha", clock(), mic_open=True, turn_active=False)
    lease(c, "alpha", clock(), mic_open=True, turn_active=True,
          turn_threshold={"rms": 923, "threshold": 1500, "binding": "cap"})
    rows = [r for r in c.journal(20) if r["kind"] == "turn"]
    assert len(rows) == 1 and rows[0]["rms"] == 923 and rows[0]["threshold"] == 1500 and rows[0]["binding"] == "cap"
    lease(c, "alpha", clock(), mic_open=True, turn_active=True,
          turn_threshold={"rms": 923, "threshold": 1500, "binding": "cap"})
    assert len([r for r in c.journal(20) if r["kind"] == "turn"]) == 1     # once per turn, not per poll


# ── authority address (2026-09-12 venue kit) ────────────────────────────────
# mDNS is the one venue-dependent piece of the robot-to-robot link: guest
# networks and some travel routers do not forward .local between clients, and
# the lease fails closed, so an unresolvable name takes the mic down. An
# optional `authority.ip` replaces the name everywhere.

def _robots_doc(**authority):
    return {"slots": {"alpha": "reachy-cjap", "beta": "cj-beta"},
            "authority": {"host": "reachy-cjap", "port": 8080, **authority}}


def _robots_file(tmp_path, name="robots.json", **authority):
    p = tmp_path / name
    p.write_text(json.dumps(_robots_doc(**authority)))
    return p


def test_authority_ip_replaces_mdns_for_the_lease_client(monkeypatch):
    monkeypatch.setattr(fl, "robots_config", lambda *a, **k: _robots_doc(ip="192.168.8.2"))
    monkeypatch.delenv("CJ_CONSOLE_URL", raising=False)
    monkeypatch.setattr(fl, "hostname", lambda: "cj-beta")          # the OTHER machine
    assert fl.authority()["ip"] == "192.168.8.2"
    assert fl.console_url() == "http://192.168.8.2:8080"
    monkeypatch.setattr(fl, "hostname", lambda: "reachy-cjap")      # the authority itself
    assert fl.console_url() == "http://127.0.0.1:8080"              # still loopback: survives any outage
    monkeypatch.setenv("CJ_CONSOLE_URL", "http://10.0.0.5:8080")    # explicit override still wins
    assert fl.console_url() == "http://10.0.0.5:8080"


def test_authority_without_ip_keeps_the_mdns_name(monkeypatch):
    monkeypatch.setattr(fl, "robots_config", lambda *a, **k: _robots_doc())
    monkeypatch.setattr(fl, "hostname", lambda: "cj-beta")
    monkeypatch.delenv("CJ_CONSOLE_URL", raising=False)
    assert fl.authority()["ip"] == "" and fl.console_url() == "http://reachy-cjap.local:8080"


def test_console_authority_url_prefers_the_ip(tmp_path):
    src = cs.ConfigSources(modes_dir=str(ROOT / "config" / "modes"),
                           dropin_path=str(tmp_path / "absent.conf"),
                           dotenv_path=str(tmp_path / "absent.env"),
                           robots_path=str(_robots_file(tmp_path, ip="192.168.8.2")))
    assert src.authority()["url"] == "http://192.168.8.2:8080"
    assert cs.authority_url(src) == "http://192.168.8.2:8080"
    src2 = cs.ConfigSources(modes_dir=str(ROOT / "config" / "modes"),
                            dropin_path=str(tmp_path / "absent.conf"),
                            dotenv_path=str(tmp_path / "absent.env"),
                            robots_path=str(_robots_file(tmp_path, "robots-noip.json")))
    assert src2.authority()["url"] == "http://reachy-cjap.local:8080"


# ── Host asks (2026-09-12) ──────────────────────────────────────────────────
# The operator types a question, the HOST robot says it in the room, and only
# when the Host has finished does Panganiban get the text to answer live. The
# console owns that sequencing so the two robots never talk over each other.

def _reporting(con, robot, clock, **obs):
    ok, reply, st = con.report(robot, {"robot": robot, "boot_id": f"boot-{robot}", **obs}, clock())
    assert ok and st == 200
    return reply


def test_host_ask_waits_for_the_host_then_releases_to_panganiban(tmp_path):
    clock = Clock()
    con = make_console(tmp_path, clock)
    con.set_config(mode="direct", profile="kiosk")
    host, cjap = con.slot_of("host"), con.slot_of("cjap")
    _reporting(con, host, clock)
    _reporting(con, cjap, clock)

    ok, out, st = con.host_ask("What did the rule of law cost you?", clip="q1.wav", now=clock())
    assert ok and st == 200 and con.name(host) in out
    assert con.ask["stage"] == "host" and con.ask["seq"] == 1

    # only the Host is told to ask; Panganiban is told nothing yet
    lh, lc = con.lease_for(host, clock()), con.lease_for(cjap, clock())
    assert lh["ask_seq"] == 1 and lh["ask_text"].startswith("What did") and lh["ask_clip"] == "q1.wav"
    assert lc["ask_seq"] == 0 and lc["ask_text"] == "" and lc["question_seq"] == 0

    # the Host is still speaking: nothing is released
    clock.advance(1)
    _reporting(con, host, clock, ask_done=0, speaking=True)
    assert con.lease_for(cjap, clock())["question_seq"] == 0 and con.ask["stage"] == "host"

    # the Host finishes -> the question reaches Panganiban, and only Panganiban
    clock.advance(1)
    _reporting(con, host, clock, ask_done=1)
    assert con.ask["stage"] == "cjap"
    lc = con.lease_for(cjap, clock())
    assert lc["question_seq"] == 1 and lc["question_text"] == "What did the rule of law cost you?"
    assert con.lease_for(host, clock())["question_seq"] == 0
    assert [r for r in con.journal(50) if r["kind"] == "ask"]


def test_host_ask_goes_straight_to_panganiban_when_no_host_reports(tmp_path):
    clock = Clock()
    con = make_console(tmp_path, clock)
    con.set_config(mode="direct", profile="kiosk")
    cjap = con.slot_of("cjap")
    _reporting(con, cjap, clock)                      # only one machine on the network
    ok, out, st = con.host_ask("Who are you?", now=clock())
    assert ok and "directly" in out
    assert con.ask["stage"] == "cjap"
    assert con.lease_for(cjap, clock())["question_text"] == "Who are you?"


def test_host_ask_validation_and_duet(tmp_path):
    clock = Clock()
    con = make_console(tmp_path, clock)
    con.set_config(mode="direct", profile="kiosk")
    assert con.host_ask("   ", now=clock())[0] is False
    assert con.host_ask("x" * 401, now=clock())[0] is False
    assert con.host_ask("ok?", clip="../etc/passwd", now=clock())[0] is False
    con.set_config(mode="duet", profile="kiosk")
    ok, out, st = con.host_ask("anything?", now=clock())
    assert not ok and st == 409 and "duet" in out


def test_role_swap_moves_who_asks_and_who_answers(tmp_path):
    clock = Clock()
    con = make_console(tmp_path, clock)
    con.set_config(mode="direct", profile="kiosk")
    for r in ROBOTS:
        _reporting(con, r, clock)
    con.host_ask("A question", now=clock())
    host_before = con.slot_of("host")
    clock.advance(1)
    _reporting(con, host_before, clock, ask_done=1)
    con.set_role(con.slot_of("host"), force=True, now=clock())   # the Host becomes Panganiban
    # the text follows the ROLE, not the machine: the new Panganiban answers it
    assert con.lease_for(host_before, clock())["question_text"] == "A question"
    assert con.lease_for(con.slot_of("host"), clock())["question_seq"] == 0


def test_client_fires_the_first_question_and_not_a_role_swap():
    """The robot side of Host-asks. Two traps: the first non-zero seq must not
    be swallowed as "no previous value", and a role swap re-points both halves
    at this machine — it must adopt the numbers silently, never re-ask what the
    other robot already handled."""
    seen = {"ask": [], "q": []}
    box = {"reply": {}}
    c = fl.LeaseClient("alpha", "http://x", transport=lambda payload: box["reply"],
                       on_ask=lambda t, clip: seen["ask"].append((t, clip)),
                       on_question=lambda t: seen["q"].append(t),
                       log=lambda *a, **k: None)
    base = {"granted": True, "floor": "alpha", "cjap_is": "alpha", "slot": "alpha",
            "ask_seq": 0, "ask_text": "", "ask_clip": "",
            "question_seq": 0, "question_text": ""}

    def poll(**over):
        box["reply"] = {**base, **over}
        assert c.poll_once()

    poll()                                                    # boot: nothing pending
    assert seen == {"ask": [], "q": []}
    poll(question_seq=1, question_text="first one")
    assert seen["q"] == ["first one"] and seen["ask"] == []   # the FIRST one is not swallowed
    poll(question_seq=1, question_text="first one")
    assert seen["q"] == ["first one"]                         # same seq: no repeat
    # role swap: this machine becomes the Host and inherits ask_seq 4
    poll(cjap_is="beta", ask_seq=4, ask_text="already asked")
    assert seen["ask"] == []                                  # adopted, not replayed
    poll(cjap_is="beta", ask_seq=5, ask_text="new one", ask_clip="q.wav")
    assert seen["ask"] == [("new one", "q.wav")]
