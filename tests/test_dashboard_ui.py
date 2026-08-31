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
