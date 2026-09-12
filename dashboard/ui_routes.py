"""Route dispatch for the dashboard: handle_get / handle_post.

Facade module (2026-08-29 split): re-exports every name from ui_common and the
ui_page_* modules so ui_server.py, tests and tools can keep using one namespace
(`import ui_routes as ui`).
"""
import json, os, re, time  # noqa: F401
import ui_common, ui_page_audience, ui_page_maintenance, ui_page_event, ui_page_face, ui_page_console
import console as _console   # operator console model (floor lease, mode/profile, journal) — 2026-09-10
_MODULES = (ui_common, ui_page_audience, ui_page_maintenance, ui_page_event, ui_page_face, ui_page_console)
for _m in _MODULES:
    globals().update({k: v for k, v in vars(_m).items()
                      if not k.startswith("__") and k not in ("_c", "_a", "_m")})


class _Facade(__import__("types").ModuleType):
    """Setting `ui_routes.NAME = x` also sets it on every module that defines
    NAME, so tests/tools that patch paths through the facade reach the code."""
    def __setattr__(self, name, value):
        for m in _MODULES:
            if hasattr(m, name):
                setattr(m, name, value)
        super().__setattr__(name, value)


__import__("sys").modules[__name__].__class__ = _Facade


def state_doc():
    """The /api/state document: app state plus the operator console's view.
    Operator console (2026-09-10): floor / mode / profile / observed /
    leaseTtl / rms / settings ride on the same document. `speaking` keeps
    the caption feed the older pages read and gains the per-robot flags
    {alpha, beta} the console needs. Also what the /api/events push stream
    sends (2026-09-12)."""
    doc = state()
    try:
        if _console.is_authority():
            cdoc = _console.get_console().state()
            cdoc["speaking"] = {**(doc.get("speaking") or {}), **cdoc["speaking"]}
            doc.update(cdoc)
        else:
            doc["console_authority"] = _console.authority_url()
    except Exception as e:
        doc["console_error"] = f"{type(e).__name__}: {e}"
    return doc


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
                h.close_connection = True   # partial/no body on a keep-alive socket
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
        h.send_header("Content-Length", "0")
        h.end_headers()
    elif path == "/api/tuning":
        if not _authed(params):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            h._send(200, json.dumps({"ok": True, "tuning": tuning_get()}))
    elif path == "/api/volume":   # 2026-09-01 master output level (slider on /maintain)
        h._send(200, json.dumps({"ok": True, **volume_get()}))
    elif path == "/api/mic":   # 2026-09-01 live mic meter; polling keeps the capture alive
        h._send(200, json.dumps({"ok": True, **mic_get()}))
    elif path == "/api/usage":
        h._send(200, json.dumps(usage()))
    elif path == "/api/providers":
        h._send(200, json.dumps(provider_status()))
    elif path == "/api/errors":
        h._send(200, json.dumps({"ts": time.time(), "rows": recent_errors()}))
    elif path == "/api/state":
        h._send(200, json.dumps(state_doc()))
    elif path == "/console":
        if not _console.is_authority():
            # this machine is not the lease authority: send the operator to
            # the one that is (config/robots.json) — one console, one truth
            h.send_response(302)
            h.send_header("Location", _console.authority_url() + "/console?key=" + params.get("key", ""))
            h.send_header("Content-Length", "0")
            h.end_headers()
        elif _authed(params):
            h._send(200, CONSOLE_PAGE, "text/html; charset=utf-8")
        else:
            h._send(200, GATE_PAGE.replace("/maintain?key=", "/console?key="),
                    "text/html; charset=utf-8")
    elif path == "/api/host-clips":   # Host asks card (2026-09-12): recordings on disk
        if not _authed(params):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            h._send(200, json.dumps({"clips": host_question_clips(), "dir": HOST_Q_DIR}))
    elif path == "/api/voices":     # Guest voice card (2026-09-12): key hint + voice list, never the key
        if not _authed(params):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            h._send(200, json.dumps(eleven_voices(refresh=params.get("refresh") in ("1", "true"))))
    elif path in _console.CONSOLE_PATHS_GET:
        code, out = _console.api(_console.get_console(), "GET", path, params,
                                 authed=_authed(params))
        h._send(code, json.dumps(out))
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
        h.send_header("Content-Length", "0")
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
    elif path == "/api/videos":   # 2026-09-02 "Video clips" card
        if not _authed(params):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            base, lead = video_lead_ms()
            _, route_label = _video_route_primary()   # name the speaker on the Sound button
            h._send(200, json.dumps({"ok": True, "videos": videos_list(),
                                     "lead_offset_ms": video_lead_offset(),
                                     "lead_base_ms": base, "lead_ms": lead,
                                     "route": route_label}))
    elif path == "/api/video":    # clip stream for the /face-avatar <video>
        serve_video(h, params.get("name", ""))
    else:
        return False
    return True


def handle_post(h, path, body):
    if path in _console.CONSOLE_PATHS_POST:
        # /api/lease is the robots' 1 Hz poll — never logged. The operator
        # calls are journaled by the console itself.
        if not _console.is_authority():
            h._send(409, json.dumps({"ok": False, "output": "not the lease authority — use "
                                     + _console.authority_url(), "authority": _console.authority_url()}))
            return True
        who = body.get("who") or f"console@{h.client_address[0]}"
        code, out = _console.api(_console.get_console(), "POST", path, {}, body,
                                 authed=_authed({}, body), who=who)
        h._send(code, json.dumps(out))
    elif path == "/api/tuning":
        if not _authed({}, body):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            ok, out = tuning_set(body)
            print(f"[ctl] {h.client_address[0]} tuning -> {out}", flush=True)
            h._send(200, json.dumps({"ok": ok, "output": out}))
    elif path == "/api/volume":
        if not _authed({}, body):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            ok, out = volume_set(body.get("level"))
            print(f"[ctl] {h.client_address[0]} volume -> {out}", flush=True)
            h._send(200, json.dumps({"ok": ok, "output": out, **volume_get()}))
    elif path == "/api/mic":
        if not _authed({}, body):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            ok, out = mic_set(body)
            print(f"[ctl] {h.client_address[0]} mic meter -> {out}", flush=True)
            h._send(200, json.dumps({"ok": ok, "output": out}))
    elif path == "/api/ctl":
        if not _authed({}, body):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            ok, out = control(body.get("action", ""))
            act = body.get("action", "")
            resp = {"ok": ok}
            if isinstance(out, dict):      # 2026-09-02: handlers may return extra fields (video sync)
                resp.update(out)
            else:
                resp["output"] = out
            if not act.startswith("avatar-voice-"):   # page heartbeats, not operator actions
                print(f"[ctl] {h.client_address[0]} {act} -> {resp.get('output')}", flush=True)
            h._send(200, json.dumps(resp))
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
    elif path == "/api/voices":
        # Guest voice card: store the ElevenLabs key / pick a voice for a role.
        # Never logged in full - the body can carry the key.
        if not _authed({}, body):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            ok, out = eleven_conf_set(body)
            print(f"[ctl] {h.client_address[0]} voices "
                  f"{'key' if body.get('api_key') else ''} {body.get('role', '')} {body.get('voice_id', '')} -> "
                  f"{out if ok else 'REFUSED: ' + str(out)}", flush=True)
            h._send(200, json.dumps({"ok": ok, "output": out}))
    elif path == "/api/avatar-conf":
        # /maintain "Avatar" row: switch the LiveAvatar avatar (and, if the new
        # one lives on another account, its API key). Never logged - the body
        # can carry a secret.
        if not _authed({}, body):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            if body.get("read"):
                ok, out = avatar_conf_get(refresh=True)
            else:
                ok, out = avatar_conf_set(body)
                print(f"[ctl] {h.client_address[0]} avatar-conf -> "
                      f"{out if ok else 'REFUSED: ' + str(out)}", flush=True)
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
