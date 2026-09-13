"""P2.5 dual-UI tests — state aggregation, auth gating, graceful degradation.

$0/offline; does not touch the live /dev/shm channels or the camera.
Pytest-compatible; standalone:  python tests/test_dashboard_ui.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen, Request

sys.path.insert(0, os.path.join(os.path.expanduser("~"), "pi_dashboard"))
import ui_routes as ui  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="cj_ui_test_"))


def _fixture_files():
    (TMP / "transcript.jsonl").write_text(
        json.dumps({"ts": 1.0, "role": "user", "text": "What is the rule of law?"}) + "\n"
        + json.dumps({"ts": 2.0, "role": "cj", "text": "Law over force."}) + "\n")
    (TMP / "meta.jsonl").write_text(
        json.dumps({"ts": 2.0, "phase": "composed", "question": "q", "raw_asr": "kw",
                    "topic": "rule_of_law", "theme": "A", "token_budget": 260,
                    "stt_s": 1.1, "compose_s": 3.2}) + "\n"
        + json.dumps({"ts": 3.0, "phase": "spoken", "question": "q",
                      "synth_s": 2.0, "play_s": 9.5, "interrupted": False}) + "\n")
    (TMP / "corrections.jsonl").write_text(
        json.dumps({"surface": "lambino versus comelec",
                    "canonical": "Lambino v. Comelec", "class": "case",
                    "confidence": 1.0}) + "\n")
    (TMP / "overlay.json").write_text(json.dumps({"add": [], "merge": {}, "remove": []}))


def _point_at_fixtures(missing=False):
    base = TMP if not missing else TMP / "nope"
    ui.TRANSCRIPT = str(base / "transcript.jsonl")
    ui.TURN_META = str(base / "meta.jsonl")
    ui.POSTPROC_LOG = str(base / "corrections.jsonl")
    ui.WAKE_LIVE = str(base / "wake.json")
    ui.WAKE_EVENTS = str(base / "wake_events.jsonl")
    ui.LAST_ANSWER = str(base / "last.mp3")
    ui.ENTITY_OVERLAY = str(base / "overlay.json")
    ui.WAKE_TRIGGER = str(base / "wake_trigger")
    ui.MUTE_TRIGGER = str(base / "mute_trigger")
    ui.MUTED_FLAG = str(base / "muted")          # never read the live mic-mute flag
    ui._health_cache.update(ts=9e18, data={"stub": True})  # skip live probes


def test_state_schema_with_fixtures():
    _fixture_files()
    _point_at_fixtures()
    s = ui.state()
    assert [t["role"] for t in s["turns"]] == ["user", "cj"]
    assert s["meta"]["theme"] == "A" and s["meta"]["token_budget"] == 260
    assert s["spoken"]["play_s"] == 9.5
    assert s["corrections"][0]["canonical"] == "Lambino v. Comelec"


def test_state_degrades_when_files_missing():
    _point_at_fixtures(missing=True)
    s = ui.state()   # must not raise
    assert s["turns"] == [] and s["meta"] is None and s["corrections"] == []
    _point_at_fixtures()


def test_entities_put_rejects_bad_input():
    _point_at_fixtures()
    ok, out = ui.entities_put("{not json")
    assert not ok and "invalid JSON" in out
    ok, out = ui.entities_put(json.dumps({"add": []}))
    assert not ok and "merge" in out
    ok, out = ui.entities_put(json.dumps({"add": {}, "merge": {}, "remove": []}))
    assert not ok


def test_entities_put_atomic_roundtrip():
    _point_at_fixtures()
    doc = {"add": [], "merge": {"x": {"add_variants": ["y"]}}, "remove": []}
    ok, out = ui.entities_put(json.dumps(doc))
    assert ok, out
    ok2, content = ui.entities_get()
    assert ok2 and json.loads(content)["merge"]["x"]["add_variants"] == ["y"]


def test_control_force_listen_touches_trigger():
    _point_at_fixtures()
    ok, _ = ui.control("force-listen")
    assert ok and os.path.exists(ui.WAKE_TRIGGER)
    os.unlink(ui.WAKE_TRIGGER)
    ok, _ = ui.control("bogus")
    assert not ok


def test_control_replay_without_answer():
    _point_at_fixtures()
    ok, out = ui.control("replay")
    assert not ok and "no stored answer" in out


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        if not ui.handle_get(self, path, params):
            self._send(404, "{}")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        if not ui.handle_post(self, self.path.partition("?")[0], body):
            self._send(404, "{}")


def _serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_http_pages_and_gating():
    _fixture_files()
    _point_at_fixtures()
    srv, base = _serve()
    try:
        aud = urlopen(base + "/audience").read()
        assert b'id="qtext"' in aud and b'id="a"' in aud   # pinned question / answer plaque
        assert b"object-fit:cover" in aud                # full-bleed camera
        assert b'id="bar"' in aud                       # floating caption band
        assert b"You asked" not in aud and b"Chief Justice says" not in aud
        gate = urlopen(base + "/maintain").read()
        assert b"access key" in gate            # no key -> gate page
        page = urlopen(base + "/maintain?key=" + ui.DASH_KEY).read()
        assert b"NER corrections" in page
        s = json.loads(urlopen(base + "/api/state").read())
        assert "health" in s and "turns" in s
        # control without key -> 403
        req = Request(base + "/api/ctl", data=json.dumps(
            {"action": "force-listen", "key": "WRONG"}).encode(), method="POST")
        try:
            urlopen(req)
            assert False, "expected 403"
        except Exception as e:
            assert getattr(e, "code", None) == 403
    finally:
        srv.shutdown()


def test_event_mode_toggle():
    _point_at_fixtures()
    ui.EVENT_FLAG = str(TMP / "event_mode.on")   # keep the real flag untouched
    ok, _ = ui.control("event-on")
    assert ok and os.path.exists(ui.EVENT_FLAG)
    assert ui.state()["event_mode"] is True
    ok, _ = ui.control("event-off")
    assert ok and not os.path.exists(ui.EVENT_FLAG)
    assert ui.state()["event_mode"] is False
    ok, _ = ui.control("event-off")   # idempotent when already off
    assert ok


def test_event_page_and_ask():
    _fixture_files()
    _point_at_fixtures()
    ui.ASK_TRIGGER = str(TMP / "ask_trigger")   # keep /dev/shm untouched
    srv, base = _serve()
    try:
        gate = urlopen(base + "/event").read()
        assert b"access key" in gate and b"/event?key=" in gate
        page = urlopen(base + "/event?key=" + ui.DASH_KEY).read().decode()
        for q in ("How are you feeling today", "State Properties Corporation",
                  "ready to answer some questions", "end our program"):
            assert q in page, q
        assert "modeBtn" in page and "toggleMode" in page
        req = Request(base + "/api/ask", data=json.dumps(
            {"id": "event_ready", "key": "WRONG"}).encode(), method="POST")
        try:
            urlopen(req)
            assert False, "expected 403"
        except Exception as e:
            assert getattr(e, "code", None) == 403
        req = Request(base + "/api/ask", data=json.dumps(
            {"id": "event_ready", "key": ui.DASH_KEY}).encode(), method="POST")
        r = json.loads(urlopen(req).read())
        assert r["ok"], r
        trig = json.loads((TMP / "ask_trigger").read_text())
        assert trig["id"] == "event_ready" and trig["a"].startswith("I was born ready")
        req = Request(base + "/api/ask", data=json.dumps(
            {"id": "nope", "key": ui.DASH_KEY}).encode(), method="POST")
        r = json.loads(urlopen(req).read())
        assert not r["ok"] and "unknown" in r["output"]
    finally:
        srv.shutdown()


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  PASS {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {name}: {exc}")
    print(f"{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)


def test_maintain_role_switch(tmp_path, monkeypatch):
    """/maintain carries the Panganiban/Host switch (2026-09-12) and its
    POST /api/role reaches the console the same way /console does."""
    import console as cs
    _fixture_files()
    _point_at_fixtures()
    src = cs.ConfigSources(modes_dir=os.path.join(os.path.dirname(cs.__file__), "..", "config", "modes"),
                           dropin_path=str(tmp_path / "absent.conf"),
                           dotenv_path=str(tmp_path / "absent.env"),
                           robots_path=os.path.join(os.path.dirname(cs.__file__), "..", "config", "robots.json"))
    con = cs.Console(src, state_path=str(tmp_path / "state.json"),
                     journal_path=str(tmp_path / "journal.jsonl"), log=lambda *a, **k: None, restore=False)
    monkeypatch.setattr(ui._console, "get_console", lambda: con)
    monkeypatch.setattr(ui._console, "is_authority", lambda *a, **k: True)
    srv, base = _serve()
    try:
        page = urlopen(base + "/maintain?key=" + ui.DASH_KEY).read()
        assert b'id="role-alpha"' in page and b'id="role-beta"' in page and b"function setRole" in page
        s = json.loads(urlopen(base + "/api/state").read())
        assert s["cjap_is"] == "alpha" and s["roles"]["beta"]["role"] == "host"
        req = Request(base + "/api/role", data=json.dumps(
            {"key": ui.DASH_KEY, "cjap_is": "beta", "who": "maintain"}).encode(), method="POST")
        r = json.loads(urlopen(req).read())
        assert r["ok"] and r["cjap_is"] == "beta"
        s = json.loads(urlopen(base + "/api/state").read())
        assert s["roles"]["beta"]["role"] == "cjap" and s["roles"]["alpha"]["role"] == "host"
        # wrong key -> 403, role untouched
        req = Request(base + "/api/role", data=json.dumps(
            {"key": "WRONG", "cjap_is": "alpha"}).encode(), method="POST")
        try:
            urlopen(req)
            assert False, "expected 403"
        except Exception as e:
            assert getattr(e, "code", None) == 403
        assert con.cjap_is == "beta"
    finally:
        srv.shutdown()


def test_env_set_keeps_comments_and_appends(tmp_path):
    env = tmp_path / "app.env"
    env.write_text("# secrets\nANTHROPIC_API_KEY=a\nELEVEN_API_KEY=k1\n# ELEVEN_HOST_VOICE_ID=commented\n")
    ui.APP_ENV = str(env)
    assert ui._env_set({"ELEVEN_HOST_VOICE_ID": "abcdefghij12"}) == ["ELEVEN_HOST_VOICE_ID"]
    assert ui._env_set({"ELEVEN_HOST_VOICE_ID": "abcdefghij12"}) == []          # idempotent
    assert ui._env_set({"ELEVEN_API_KEY": "k2", "ELEVEN_VOICE_ID": "v1"}) == ["ELEVEN_API_KEY", "ELEVEN_VOICE_ID"]
    text = env.read_text()
    assert text.startswith("# secrets\nANTHROPIC_API_KEY=a\nELEVEN_API_KEY=k2\n# ELEVEN_HOST_VOICE_ID=commented\n")
    assert "ELEVEN_HOST_VOICE_ID=abcdefghij12\n" in text and text.endswith("ELEVEN_VOICE_ID=v1\n")
    assert ui._env_value("ELEVEN_HOST_VOICE_ID") == "abcdefghij12"
    assert not (tmp_path / "app.env.tmp").exists()


def test_guest_voice_card_api(tmp_path, monkeypatch):
    """/maintain Guest voice card (2026-09-12): list voices, store a key,
    assign GUEST / CJAP voices — all validated against (a fake) ElevenLabs,
    the key never echoed, restarts only when the app needs one."""
    _fixture_files()
    _point_at_fixtures()
    env = tmp_path / "app.env"
    env.write_text("ELEVEN_API_KEY=oldkey_0123456789abcdef\nELEVEN_VOICE_ID=cjapvoice0001\n")
    ui.APP_ENV = str(env)
    ui._voices_cache.update(ts=0.0, key=None, data=None)
    VOICES = {"cjapvoice0001": {"voice_id": "cjapvoice0001", "name": "Panganiban clone", "category": "cloned",
                                "labels": {}, "preview_url": "http://x/p1.mp3"},
              "hostvoice00002": {"voice_id": "hostvoice00002", "name": "Warm Host", "category": "premade",
                                 "labels": {"gender": "female", "accent": "filipino"}, "preview_url": "http://x/p2.mp3"}}
    calls = []

    def fake_get(path, key, timeout=10):
        calls.append((path, key))
        if key not in ("oldkey_0123456789abcdef", "newkey_0123456789abcdef"):
            return False, "HTTP 401: invalid api key"
        if path.startswith("/v1/voices?"):
            return True, {"voices": list(VOICES.values())}
        if path.startswith("/v1/voices/"):
            v = VOICES.get(path.rsplit("/", 1)[1])
            return (True, v) if v else (False, "HTTP 404")
        if path == "/v1/user/subscription":
            return True, {"tier": "starter", "character_count": 10, "character_limit": 30000}
        return False, "unexpected " + path
    restarts = []
    monkeypatch.setattr(ui, "_eleven_get", fake_get)
    monkeypatch.setattr(ui, "_restart_app", lambda: restarts.append(1))
    srv, base = _serve()
    try:
        page = urlopen(base + "/maintain?key=" + ui.DASH_KEY).read()
        assert b'id="voices-card"' in page and b"function evRender" in page
        try:
            urlopen(base + "/api/voices")
            assert False, "expected 403"
        except Exception as e:
            assert getattr(e, "code", None) == 403
        d = json.loads(urlopen(base + "/api/voices?key=" + ui.DASH_KEY).read())
        assert d["has_key"] and d["key_hint"] == "…cdef" and "oldkey" not in json.dumps(d)
        assert [v["name"] for v in d["voices"]] == ["Panganiban clone", "Warm Host"]   # cloned first
        assert d["voices"][1]["labels"] == "female, filipino"
        assert d["cjap_voice_id"] == "cjapvoice0001" and d["host_voice_id"] == ""

        def post(body):
            req = Request(base + "/api/voices", data=json.dumps({"key": ui.DASH_KEY, **body}).encode(),
                          method="POST")
            return json.loads(urlopen(req).read())
        r = post({"role": "host", "voice_id": "hostvoice00002"})
        assert r["ok"] and "GUEST voice" in r["output"] and "Warm Host" in r["output"]
        assert "ELEVEN_HOST_VOICE_ID=hostvoice00002\n" in env.read_text() and restarts == []
        r = post({"role": "host", "voice_id": "nosuchvoice0"})
        assert not r["ok"] and "not on this account" in r["output"]
        r = post({"role": "cjap", "voice_id": ""})
        assert not r["ok"]
        r = post({"role": "cjap", "voice_id": "hostvoice00002"})
        assert r["ok"] and restarts == [1] and "ELEVEN_VOICE_ID=hostvoice00002\n" in env.read_text()
        r = post({"api_key": "bad key with spaces"})
        assert not r["ok"]
        r = post({"api_key": "wrongkey_0123456789abcdef"})
        assert not r["ok"] and "refused" in r["output"]
        r = post({"api_key": "newkey_0123456789abcdef"})
        assert r["ok"] and "starter" in r["output"] and restarts == [1, 1]
        assert "ELEVEN_API_KEY=newkey_0123456789abcdef\n" in env.read_text()
        d = json.loads(urlopen(base + "/api/voices?key=" + ui.DASH_KEY).read())
        assert d["key_hint"] == "…cdef" and d["host_voice_id"] == "hostvoice00002"
        # audition resolves the preview from the cached list
        monkeypatch.setattr(ui, "_fetch_bytes", lambda url, **k: b"MP3" + url.encode())
        ok, data = ui.eleven_voice_sample("hostvoice00002")
        assert ok and data == b"MP3http://x/p2.mp3"
        ok, why = ui.eleven_voice_sample("nosuchvoice0")
        assert not ok
    finally:
        srv.shutdown()
        ui._voices_cache.update(ts=0.0, key=None, data=None)


def test_push_publisher_emits_and_stops(monkeypatch):
    """/api/events (2026-09-12): one publisher thread serves every subscriber,
    sends a frame only when a document changes, and exits when nobody listens."""
    import queue as _q
    import time as _t
    import ui_server as srv
    monkeypatch.setattr(srv, "wake_live", lambda: {"score": 0.1, "live": True})
    monkeypatch.setattr(srv, "stop_live", lambda: {"score": 0.0, "live": False})
    monkeypatch.setattr(srv, "status", lambda: {"services": {}})
    seq = {"n": 0}
    def fake_state():
        return {"ts": _t.time(), "turns": [], "n": seq["n"]}
    monkeypatch.setattr(srv.ui, "state_doc", fake_state)
    push = srv._Push()
    q = push.subscribe()
    frames = []
    deadline = _t.time() + 3
    while _t.time() < deadline and len(frames) < 3:
        try:
            frames.append(q.get(timeout=1).decode())
        except _q.Empty:
            pass
    kinds = {f.split("\n", 1)[0] for f in frames}
    assert "event: state" in kinds and "event: meters" in kinds and "event: status" in kinds
    # unchanged documents -> silence (only the 2 s state heartbeat would speak)
    _t.sleep(0.8)
    assert q.qsize() == 0
    seq["n"] += 1                                    # a change -> one state frame
    frame = q.get(timeout=2).decode()
    assert frame.startswith("event: state") and '"n": 1' in frame
    push.unsubscribe(q)
    _t.sleep(0.4)
    assert push.thread is None or not push.thread.is_alive()
    q2 = push.subscribe()                            # a late subscriber gets the snapshot at once
    assert q2.get(timeout=1).startswith(b"event: ")
    push.unsubscribe(q2)
