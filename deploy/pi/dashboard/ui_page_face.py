"""/face and /face-avatar — LiveAvatar page, HeyGen session helpers, camera MJPEG.

Split out of supervaise_ui.py on 2026-08-29 (shared names star-copied from
ui_common so page code reads exactly as before; ui_routes is the facade).
"""
import json, os, subprocess, time  # noqa: F401
import ui_common as _c
import ui_page_audience as _e
for _m in (_c, _e):
    globals().update({k: v for k, v in vars(_m).items() if not k.startswith('__')})


FACE_AVATAR_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CJAP LiveAvatar</title><link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,500;0,600;1,500&family=EB+Garamond:ital,wght@0,400;0,500;1,400&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/livekit-client@2/dist/livekit-client.umd.min.js"></script>
<style>
""" + EXHIBIT_CSS + """
/* avatar page: the HeyGen portrait (9:10) where the camera sits on /audience —
   frameless (2026-08-25, user): no gilt moulding, mat rings, or glow */
#cam,#cam.live{width:min(36vw,calc(58vh * 9 / 10));aspect-ratio:9/10;top:4vh;
  border:0;border-image:none;box-shadow:none;border-radius:.8vh}
#cam video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;background:#000}
/* picture-frame idle (2026-08-25, user): a frozen frame of the avatar sits
   over the live video whenever it is not speaking — and stays up after the
   sandbox session expires, so the portrait never goes black */
#cam canvas#still{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:none;z-index:2}
#cam .idle{z-index:1}
/* no on-page operator strip (2026-08-25, user): Stop/Resume, voice mode and
   the status line live on /maintain ("LiveAvatar page" card) and reach this
   page through /api/state (avatar_cmd) — status goes back via /api/avatar-status */
</style></head><body>
<div id="cam"><video id="vid" autoplay playsinline muted></video><canvas id="still"></canvas><audio id="aud" autoplay></audio>
  <div class="idle" id="camidle"><b>CJAP</b>
    <span>Chief Justice Artemio V. Panganiban</span></div>
</div>
""" + EXHIBIT_PLAQUES + """<script>
""" + EXHIBIT_JS + """const $ = id => document.getElementById(id);
const KEY = new URLSearchParams(location.search).get("key") || localStorage.getItem("cjkey") || "";
if (KEY) try { localStorage.setItem("cjkey", KEY); } catch (e) {}
let room = null, ws = null, ready = false, sessTok = null, startP = null;
let avatarMuted = true, lastStart = 0, keepTimer = null;
let pendingLagT0 = null, lagEma = null, skew = 0;
$("aud").muted = true;
const sleep = ms => new Promise(r => setTimeout(r, ms));

// status line → /maintain (posted on change, plus a 3s heartbeat so the
// card can tell "page open" from "page gone")
let stText = "starting", stSentAt = 0;
function report(){
  stSentAt = Date.now();
  post("/api/avatar-status", {status: stText, mode: voiceMode, ready: ready,
    stopped: stopped, parked: !ready && !stopped, frozen: frozen, lag: lagEma}).catch(() => {});
}
function st(msg){ stText = msg; if (Date.now() - stSentAt > 700) report(); }
setInterval(report, 3000);

async function post(path, doc){
  doc.key = KEY;
  const r = await fetch(path, {method:"POST",
    headers:{"Content-Type":"application/json"}, body:JSON.stringify(doc)});
  return r.json();
}

// ---- session ------------------------------------------------------------
function start(){
  if (ready || stopped) return Promise.resolve();
  if (startP) return startP;                // one start in flight at a time
  if (Date.now() - lastStart < 8000) return Promise.resolve();
  lastStart = Date.now();
  startP = _start().catch(e => st("start failed: " + e.message))
                   .finally(() => { startP = null; });
  return startP;
}
async function _start(){
  st("creating session…");
  const out = await post("/api/avatar-session", {});
  if (!out.ok){
    st("session failed: " + JSON.stringify(out.output) +
       (String(out.output) === "bad key" ? " — open this page as /face?key=cjap (the dashboard key)" : ""));
    return; }
  const s = out.output;
  sessTok = s.session_token;
  if (stopped){ await park(); return; }          // Stop landed during session creation
  st("connecting to room…");
  try{
    room = new LivekitClient.Room();
    room.on(LivekitClient.RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === "video"){ track.attach($("vid"));
        $("camidle").style.display = "none"; }
      if (track.kind === "audio"){ track.attach($("aud"));
        $("aud").muted = avatarMuted; }
    });
    await room.connect(s.livekit_url, s.livekit_client_token);
  }catch(e){ st("LiveKit connect failed: " + e.message); return; }
  if (stopped){ await park(); return; }
  st("opening control socket…");
  const sock = new WebSocket(s.ws_url);
  ws = sock;
  const connected = new Promise(res => {
    sock.addEventListener("message", ev => {
      let m = {}; try{ m = JSON.parse(ev.data); }catch(e){ return; }
      if (m.type === "session.state_updated" && m.state === "connected") res(true);
    });
    sock.addEventListener("close", () => res(false));
    setTimeout(() => res(false), 15000);
  });
  sock.onmessage = ev => {
    let m = {};
    try{ m = JSON.parse(ev.data); }catch(e){ return; }
    if (m.type === "session.state_updated"){
      st("session " + m.state +
         (m.state === "connected" ? " — portrait still until asked" : ""));
      const was = ready;
      ready = (m.state === "connected");
      if (ready && !was) setVoice(voiceMode);   // re-assert (default: robot voice, avatar mouths along)
    }
    if (m.type === "agent.speak_started"){
      const name = sentOrder.shift();          // attribute to the oldest queued clip
      if (name) avatarStart[name] = Date.now()/1000;
      if (pendingLagT0){
        // closed-loop sync: how long after the feed publish did the avatar
        // actually start speaking? The robot delays its audio by this much.
        const lag = Date.now()/1000 - pendingLagT0;
        pendingLagT0 = null;
        if (lag > 0 && lag < 5){
          lagEma = lagEma === null ? lag : lagEma*.6 + lag*.4;
          post("/api/avatar-lag", {lag: +lagEma.toFixed(2)});
          st("speaking — avatar start lag " + lagEma.toFixed(2) + "s (auto-sync)");
        }
      }
    }
  };
  sock.onclose = () => {
    if (ws !== sock) return;
    ready = false; stopKeep(); sentOrder.length = 0;   // nothing queued survives the session
    if (parking){ parking = false; st("parked — portrait held, no credits while idle"); return; }
    const busy = speakingNow || turnActive();
    st("session ended (sandbox caps at ~1 min)" +
       (busy ? " — reconnecting…" : " — portrait held, restarts on next question"));
    if (busy) setTimeout(start, 300);   // pick the answer back up
  };
  sock.onerror = () => { ready = false; };
  keepTimer = setInterval(() => {
    if (ws && ws.readyState === 1)
      ws.send(JSON.stringify({type:"session.keep_alive",
                              event_id:String(Date.now())}));
  }, 25000);
  await connected;
  if (stopped){ await park(); await post("/api/ctl", {action: "avatar-voice-off"}); }
}
function stopKeep(){ if (keepTimer){ clearInterval(keepTimer);
  keepTimer = null; } }

// park = end the HeyGen session but stay armed: the still portrait covers
// the gap and the next question pre-starts a fresh session (no idle credits)
let parking = false;
async function park(){
  if (!ready && !sessTok) return;
  parking = true; stopKeep(); ready = false;
  try{ if (ws) ws.close(); }catch(e){}
  try{ if (room) room.disconnect(); }catch(e){}
  const tok = sessTok; sessTok = null; sent.clear(); sentOrder.length = 0;
  if (tok) await post("/api/avatar-stop", {session_token: tok});
  setTimeout(() => { parking = false; }, 5000);   // onclose normally clears it first
}
async function stop(){
  stopped = true;                                    // blocks every auto-start
  await park();
  await post("/api/ctl", {action: "avatar-voice-off"});   // robot: no holds
  st("stopped — portrait held; press Resume to mouth along again");
}
let stopped = false;
function resume(){ if (!stopped) return; stopped = false; heartbeat(); start(); }
// commands from /maintain arrive in /api/state.avatar_cmd; anything already
// queued before this page loaded is ignored (lastCmdTs primes on first poll)
let lastCmdTs = null;
function applyCmd(c){
  if (!c || !c.ts) return;
  if (lastCmdTs === null){ lastCmdTs = c.ts; return; }
  if (c.ts <= lastCmdTs) return;
  lastCmdTs = c.ts;
  if (c.cmd === "stop") stop();
  else if (c.cmd === "resume") resume();
  else if (c.cmd === "voice" && MODES.includes(c.mode)) setVoice(c.mode);
}
// Session lifecycle (2026-08-25, user: "automatically start and stop so no
// credits are lost while idle"):
//  • page load: a cached portrait (localStorage) is shown at once and NO
//    session is opened; without one, a session runs just long enough to
//    capture the portrait, then parks
//  • a question being transcribed pre-starts the session (~8-15s before the
//    first sentence), answers/asides start it if it is not up yet
//  • IDLE_PARK_MS after the last activity the session is parked
const IDLE_PARK_MS = 45000;
let lastActivity = Date.now(), turnUntil = 0, lastTurnKey = "";
function touch(){ lastActivity = Date.now(); }
function turnActive(){ return Date.now() < turnUntil; }
setTimeout(() => { if (!restoreStill()) start(); }, 0);   // deferred past the lets below
setInterval(() => {
  if (!ready) return;
  if (stopped){ park(); return; }                  // a session that outlived Stop
  if (speakingNow || turnActive() || sentOrder.length || Date.now() < busyUntil) return;
  if (Date.now() - lastActivity > IDLE_PARK_MS) park();
}, 1000);

// ---- picture-frame idle ---------------------------------------------------
// The live video shows only while the avatar is mouthing something; the rest
// of the time a frozen frame of it is displayed. The frame is re-taken a few
// times right after freezing (the first decoded frames can be transitional)
// and then held — through sandbox session expiry — until the next answer.
let wantLive = false, liveUntil = 0, freezeAt = 0, frozen = false,
    snaps = 0, lastSnap = 0, busyUntil = 0;   // busyUntil: avatar still mouthing a fed clip
function restoreStill(){
  let url = null;
  try{ url = localStorage.getItem("cjap_still"); }catch(e){}
  if (!url) return false;
  const img = new Image();
  img.onload = () => { const c = $("still"); c.width = img.width; c.height = img.height;
    c.getContext("2d").drawImage(img, 0, 0); c.style.display = "block"; frozen = true;
    $("camidle").style.display = "none"; st("portrait — starts on the next question"); };
  img.onerror = () => { frozen = false; start(); };   // corrupt cache: capture a fresh one
  img.src = url;
  return true;
}
function videoLive(){
  const v = $("vid");
  return ready && v.videoWidth > 0 && v.readyState >= 2 && !v.paused;
}
function snap(){
  const v = $("vid"), c = $("still");
  if (!videoLive()) return false;
  c.width = v.videoWidth; c.height = v.videoHeight;
  try{ c.getContext("2d").drawImage(v, 0, 0); }catch(e){ return false; }
  $("camidle").style.display = "none";
  return true;
}
function frameTick(){
  const live = wantLive || Date.now() < liveUntil || Date.now() < busyUntil;
  if (live){
    if (frozen && videoLive()){ $("still").style.display = "none"; frozen = false; }
  } else if (Date.now() >= freezeAt){
    if (!frozen){
      if (snap()){ $("still").style.display = "block"; frozen = true; snaps = 1; lastSnap = Date.now();
        if (!speakingNow) st(ready ? "portrait — still until asked" : "portrait — starts on the next question"); }
    } else if (snaps < 4 && Date.now() - lastSnap > 1000 && snap()){
      snaps++; lastSnap = Date.now();
      if (snaps === 4) try{ localStorage.setItem("cjap_still",
        $("still").toDataURL("image/jpeg", 0.85)); }catch(e){}
    }
  }
  setTimeout(frameTick, 150);
}
setTimeout(frameTick, 150);   // deferred: the poll section below declares speakingNow

// ---- voice mode -----------------------------------------------------------
// robot = avatar muted here but its mouth still tracks the robot ("lips");
// avatar = avatar is the only voice; sync = both, robot delayed to coincide
const MODES = ["sync", "avatar", "robot"];
let voiceMode = "robot";
function modeAction(){
  return voiceMode === "avatar" ? "avatar-voice-on"
       : voiceMode === "sync"   ? "avatar-voice-sync" : "avatar-voice-lips";
}
async function setVoice(mode){
  voiceMode = mode;
  avatarMuted = (mode === "robot");
  $("aud").muted = avatarMuted;
  await post("/api/ctl", {action: modeAction()});
  report();
}
// the robot only holds its head start while this page is alive: re-assert
// the mode every 5s (flag older than 15s = page gone)
function heartbeat(){ if (!stopped) post("/api/ctl", {action: modeAction()}); }
setInterval(heartbeat, 5000); heartbeat();
addEventListener("beforeunload", () => {
  navigator.sendBeacon("/api/ctl",
    new Blob([JSON.stringify({key:KEY, action:"avatar-voice-off"})],
             {type:"application/json"}));
});

// ---- feed the avatar our ElevenLabs sentence audio -----------------------
function b64(u8){
  let s = "";
  for (let i = 0; i < u8.length; i += 32768)
    s += String.fromCharCode.apply(null, u8.subarray(i, i + 32768));
  return btoa(s);
}
function wavPcm(buf){          // RIFF walk → the data chunk's bytes
  const dv = new DataView(buf), u8 = new Uint8Array(buf);
  let pos = 12;
  while (pos + 8 <= u8.length){
    const id = String.fromCharCode(u8[pos], u8[pos+1], u8[pos+2], u8[pos+3]);
    const size = dv.getUint32(pos + 4, true);
    if (id === "data") return u8.subarray(pos + 8, pos + 8 + size);
    pos += 8 + size + (size % 2);
  }
  return null;
}
// Everything the robot voices goes through ONE ordered queue: answer
// sentences (current + the pre-fed next one), plus ack/filler asides. The
// avatar plays them back-to-back in exactly the robot's order.
const sent = new Set(), sentOrder = [], avatarStart = {};
let chain = Promise.resolve();
function enqueue(name){
  if (!name || sent.has(name)) return;
  sent.add(name);
  chain = chain.then(() => sendWav(name)).catch(() => {});
}
async function sendWav(name){
  if (stopped) return;
  if (!ready) await start();
  for (let w = 0; w < 40 && !ready && !stopped; w++) await sleep(250);
  if (!ready){ st("session not ready — clip skipped"); sent.delete(name); return; }
  try{
    const r = await fetch("/api/sentence.wav?name=" + name);
    if (!r.ok){ st("clip gone: " + name); return; }
    const pcm = wavPcm(await r.arrayBuffer());
    if (!pcm){ st("bad wav"); return; }
    for (let i = 0; i < pcm.length; i += 48000)     // 1s @ 24kHz 16-bit
      ws.send(JSON.stringify({type:"agent.speak",
                              audio: b64(pcm.subarray(i, i + 48000))}));
    ws.send(JSON.stringify({type:"agent.speak_end",
                            event_id:String(Date.now())}));
    sentOrder.push(name);
    // the avatar mouths this clip from ~lag after now for its full length —
    // keep the live video up (and the session unparked) until then
    const durMs = pcm.length / 48 + (lagEma || 1.5) * 1000 + 800;
    busyUntil = Math.max(busyUntil, Date.now() + durMs); touch();
  }catch(e){ st("audio feed failed: " + e.message); }
}

// ---- state poll ----------------------------------------------------------
let curKey = "", speakingNow = false, lastAsideTs = 0, driftShown = "", uiRev = null;
async function poll(){
  try{
    const stt = await (await fetch("/api/state")).json();
    if (stt.ts) skew = Date.now()/1000 - stt.ts;   // Pi clock → browser clock
    if (uiRev === null) uiRev = stt.ui_rev || null;
    else if (stt.ui_rev && stt.ui_rev !== uiRev){ st("new version — reloading"); location.reload(); return; }
    applyCmd(stt.avatar_cmd);                        // Stop/Resume/voice from /maintain
    // a question is being transcribed → warm the session before the answer
    const stg = stt.stage || {}, tr = (stg.steps || {}).transcribe || {};
    const heard = tr.state === "done" || (tr.state === "active" && /transcrib/i.test(tr.detail || ""));
    if (heard && stg.turn_ts && (Date.now()/1000 - (stg.turn_ts + skew)) < 60){
      const tk = stg.turn_ts + "|" + tr.state;
      if (tk !== lastTurnKey){ lastTurnKey = tk; touch(); turnUntil = Date.now() + 60000;
        if (!ready) st("question heard — starting the avatar session…");
        start(); }
    }
    renderExhibit(stt);                              // same plaques as /audience
    const sp = stt.speaking || {}, as = stt.aside || {};
    // ack / filler clips ("Hmm.", "let me think…") — mouth them, no caption
    if (as.wav && as.ts && as.ts !== lastAsideTs && (Date.now()/1000 - (as.ts + skew)) < 6){
      lastAsideTs = as.ts; enqueue(as.wav); touch();
      liveUntil = Date.now() + 6000;          // mouth the aside, then still again
    }
    if (sp.current && !sp.done){
      const key = sp.wav || (sp.ts + "|" + sp.current);
      if (key !== curKey){
        const wasIdle = !speakingNow;
        curKey = key; speakingNow = true; wantLive = true; touch();
        if (sp.wav){
          // measure start lag only on an answer's FIRST sentence with the
          // session already live (a cold session start isn't speak lag)
          if (wasIdle && ready && !sent.has(sp.wav))
            pendingLagT0 = sp.ts + skew;
          enqueue(sp.wav);
        }
      }
      if (sp.next && sp.next.wav) enqueue(sp.next.wav);   // queue ahead
      // drift readout: avatar start vs the robot's real audio start
      if (sp.wav && sp.play_ts && avatarStart[sp.wav] && driftShown !== sp.wav){
        driftShown = sp.wav;
        const d = avatarStart[sp.wav] - (sp.play_ts + skew);
        st("speaking — avatar " + (d >= 0 ? "+" : "") + d.toFixed(2) + "s vs robot" +
           (lagEma !== null ? " (lag " + lagEma.toFixed(2) + "s)" : ""));
      }
    } else if (sp.done){
      if (speakingNow){
        if (sp.interrupted && ws && ws.readyState === 1)
          ws.send(JSON.stringify({type:"agent.interrupt"}));
        speakingNow = false; curKey = ""; wantLive = false; touch();
        turnUntil = 0;                        // answer done: the turn is over
        freezeAt = Date.now() + Math.round(((lagEma || 0.8) + 0.7) * 1000);
        if (sp.interrupted) busyUntil = 0;    // cut short: freeze with the robot
        sentOrder.length = 0;
        if (sent.size > 64) sent.clear();
      }
    }
  }catch(e){}
  setTimeout(poll, 120);
}
poll();
</script></body></html>"""


# ---------------------------------------------------------------------------
# LiveAvatar / camera helpers (dispatch lives in ui_routes.handle_*)
# ---------------------------------------------------------------------------


def _sentence_pcm24k(path):
    """The avatar page streams the wav's raw PCM as 24 kHz/16-bit/mono. Every
    clip we produce already is; anything else is converted once (ffmpeg)."""
    import wave
    try:
        with wave.open(path, "rb") as w:
            ok = (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (24000, 1, 2)
    except Exception:
        ok = False
    if ok:
        return open(path, "rb").read()
    out = path + ".24k.wav"
    if not os.path.exists(out):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet", "-i", path,
                        "-ar", "24000", "-ac", "1", "-sample_fmt", "s16", out],
                       timeout=20)
    return open(out, "rb").read()


def _liveavatar_request(path, payload, auth_header):
    """POST to api.liveavatar.com (stdlib urllib; 15s timeout)."""
    import urllib.request
    req = urllib.request.Request(
        "https://api.liveavatar.com" + path,
        json.dumps(payload).encode(),
        {"Content-Type": "application/json",
         # their edge 403s python-urllib's default UA
         "User-Agent": "supervaise-cjap/1.0", **auth_header})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def avatar_session():
    """Create a LiveAvatar LITE session (sandbox by default) and return
    the connection material for the /face-avatar page. The API key stays
    server-side (assets/liveavatar.json — never sent to the browser)."""
    conf = _read_json(LIVEAVATAR_CONF)
    if not conf or not conf.get("api_key"):
        return False, ("no assets/liveavatar.json — create it with "
                       '{"api_key": "...", "avatar_id": "...", '
                       '"sandbox": true}')
    try:
        tok = _liveavatar_request(
            "/v1/sessions/token",
            {"mode": "LITE",
             "avatar_id": conf.get(
                 "avatar_id", "dd73ea75-1218-4ef3-92ce-606d5f7fbc0a"),
             "is_sandbox": bool(conf.get("sandbox", True))},
            {"X-API-KEY": conf["api_key"]})
        data = tok.get("data") or {}
        session_token = data.get("session_token")
        if not session_token:
            return False, f"token refused: {tok.get('message')}"
        start = _liveavatar_request(
            "/v1/sessions/start", {},
            {"Authorization": "Bearer " + session_token})
        sd = start.get("data") or {}
        if not sd.get("livekit_url"):
            return False, f"start refused: {start.get('message')}"
        sd["session_token"] = session_token   # page needs it for stop
        return True, sd
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def avatar_stop(session_token):
    try:
        _liveavatar_request("/v1/sessions/stop", {"reason": "USER_CLOSED"},
                            {"Authorization": "Bearer " + (session_token or "")})
        return True, "stopped"
    except Exception as e:
        return False, f"{type(e).__name__}"


def _serve_mjpeg(h):
    boundary = "cjapframe"
    h.close_connection = True   # unbounded stream: never reuse this connection
    try:
        h.send_response(200)
        h.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        last_ts = 0.0
        while True:
            frame = cam_frame()
            if not frame:
                break
            if _cam["ts"] != last_ts:
                last_ts = _cam["ts"]
                h.wfile.write(f"--{boundary}\r\nContent-Type: image/jpeg\r\n"
                              f"Content-Length: {len(frame)}\r\n\r\n".encode())
                h.wfile.write(frame + b"\r\n")
            time.sleep(0.1)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
