"""/face and /face-avatar — LiveAvatar page, HeyGen session helpers, camera MJPEG.

Split out of supervaise_ui.py on 2026-08-29 (shared names star-copied from
ui_common so page code reads exactly as before; ui_routes is the facade).
"""
import json, os, re, subprocess, time  # noqa: F401
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
/* idle loop (2026-09-12): a few seconds of the avatar connected-but-silent,
   looped while parked so it blinks and breathes instead of being a photo */
#cam video#idle{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:none;z-index:2}
#cam .idle{z-index:1}
/* avatar view (2026-09-04, user: "make the avatar full" → "or make a button for
   flexibility"): picked on /maintain, persisted in ~/.cj_avatar_view, applied
   from /api/state so a reload keeps it. The LiveAvatar video is 1920x1080, so
   the default 9:10 box crops roughly half the frame width away.
     framed = the box above (original exhibit look)
     wide   = 16:9 window, contain — the whole frame, nothing cropped
     full   = edge to edge, cover — the avatar IS the page                    */
#cam.v-wide{width:min(74vw,calc(58vh * 16 / 9));aspect-ratio:16/9;top:4vh}
#cam.v-wide video,#cam.v-wide canvas#still,#cam.v-wide video#idle{object-fit:contain;background:#000}
#cam.v-full{top:0;left:0;transform:none;width:100vw;height:100vh;max-width:none;
  aspect-ratio:auto;border-radius:0}
#cam.v-full video,#cam.v-full canvas#still,#cam.v-full video#idle{object-fit:cover}
/* no on-page operator strip (2026-08-25, user): Stop/Resume, voice mode and
   the status line live on /maintain ("LiveAvatar page" card) and reach this
   page through /api/state (avatar_cmd) — status goes back via /api/avatar-status.
   The #rs state pill added 2026-09-04 is not an operator control: it is the same
   audience-facing Idle/Listening/Thinking/Speaking indicator /audience shows,
   so both screens read the same. ?pill=off hides it. */
</style></head><body>
<div id="cam"><video id="vid" autoplay playsinline muted></video><canvas id="still"></canvas><video id="idle" loop muted playsinline></video><audio id="aud" autoplay></audio>
  <div class="idle" id="camidle"><b>CJAP</b>
    <span>Chief Justice Artemio V. Panganiban</span></div>
</div>
<video id="clip" playsinline style="position:fixed;inset:0;width:100%;height:100%;
  object-fit:contain;background:#000;z-index:50;display:none;opacity:0;
  transition:opacity .9s ease"></video>
""" + EXHIBIT_PILL + EXHIBIT_PLAQUES + """<script>
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
// /maintain applied a different avatar id: the cached still is the OLD face,
// so drop it, end the session (the next one is created with the new id) and
// open one straight away to capture the new portrait.
async function newAvatar(){
  try{ localStorage.removeItem("cjap_still"); }catch(e){}
  $("still").style.display = "none"; frozen = false; snaps = 0;
  $("camidle").style.display = "flex";
  await park();
  stopped = false;
  touch();          // the page may have been idle for ages — without this the
                    // idle timer parks the new session before the still caches
  st("avatar changed — fetching the new portrait…");
  setTimeout(start, 600);
}
// commands from /maintain arrive in /api/state.avatar_cmd; anything already
// queued before this page loaded is ignored (lastCmdTs primes on first poll).
// 2026-09-04: prime on the first poll even when there is NO command yet —
// priming on the first command instead swallowed it, so the very first
// Stop/Resume/voice/avatar after a reboot (no cmd file) did nothing.
let lastCmdTs = 0, cmdPrimed = false;
function applyCmd(c){
  if (!cmdPrimed){ cmdPrimed = true; lastCmdTs = (c && c.ts) || 0; return; }
  if (!c || !c.ts || c.ts <= lastCmdTs) return;
  lastCmdTs = c.ts;
  if (c.cmd === "stop") stop();
  else if (c.cmd === "resume") resume();
  else if (c.cmd === "avatar") newAvatar();
  else if (c.cmd === "voice" && MODES.includes(c.mode)) setVoice(c.mode);
}
// video clips (2026-09-02): /maintain uploads a file and posts
// video-play-<name> / video-stop; the command lands here via
// /api/state.video_cmd and the clip plays full-screen over the portrait.
let lastVidCmdTs = 0, vidCmdPrimed = false;
function applyVideoCmd(c){
  if (!vidCmdPrimed){ vidCmdPrimed = true; lastVidCmdTs = (c && c.ts) || 0; return; }   // pre-load leftovers
  if (!c || !c.ts || c.ts <= lastVidCmdTs) return;
  lastVidCmdTs = c.ts;
  if (c.cmd === "play" && c.name){
    // sound target picked on /maintain (2026-09-02): "robot" = the video plays
    // muted here while the Pi decodes the audio track (ffmpeg|aplay) — go signal
    // once buffered, picture starts ~350 ms later to cover the spawn; "page" =
    // the browser plays it with sound on THIS device (the laptop showing the page).
    const v = $("clip");
    const local = c.audio === "page";
    clearTimeout(clipFadeT);                 // re-play during a fade-out
    v.src = "/api/video?name=" + encodeURIComponent(c.name);
    v.style.display = "block"; v.style.opacity = 0; v.currentTime = 0;
    v.addEventListener("playing", () => { v.style.opacity = 1; }, {once: true});
    if (local){
      v.muted = false;
      st("video clip (sound on this device): " + c.name);
      v.play().catch(() => {          // autoplay-with-sound blocked: play muted
        v.muted = true;
        v.play().catch(e2 => st("video clip failed: " + e2.message));
        st("video clip MUTED (browser blocked sound — tap the page once): " + c.name);
      });
    } else {
      v.muted = true;
      st("video clip (sound on robot): " + c.name);
      let went = false;
      const go = async () => {
        if (went) return;                 // canplay + canplaythrough both fire
        went = true;
        v.removeEventListener("canplaythrough", go);
        v.removeEventListener("canplay", go);
        v.removeEventListener("progress", onProgress);
        // 2026-09-02 sync: the Pi answers once aplay has the device set up and
        // says how long to wait (route latency + operator offset)
        let lead = 350;
        try { const r = await post("/api/ctl", {action: "video-audio-go-" + c.name});
              if (r && r.lead_ms != null) lead = r.lead_ms;
              // routed speaker gone / aplay could not open it: say so instead of
              // rolling a silent picture (2026-09-02)
              if (r && r.ok === false) st("clip sound FAILED: " + (r.output || "no audio"));
              else if (r && r.where) st("video clip (sound on " + r.where + "): " + c.name);
        } catch (e) {}
        setTimeout(() => v.play().catch(e2 => st("video clip failed: " + e2.message)), Math.max(0, lead));
      };
      // 2026-09-02: waiting for canplaythrough on a 33 MB clip held the sound
      // back ~14 s (measured on the event LAN) — the operator sees the picture
      // and hears nothing. Start as soon as a few seconds are buffered.
      const onProgress = () => {
        try { if (v.buffered.length && v.buffered.end(0) >= 2) go(); } catch (e) {}
      };
      v.addEventListener("progress", onProgress);
      v.addEventListener("canplay", onProgress);
      v.addEventListener("canplaythrough", go);
      v.load();
    }
  } else if (c.cmd === "stop") stopClip();
}
let clipFadeT = null;
function stopClip(){
  const v = $("clip");
  if (v.style.display === "none") return;
  v.style.opacity = 0;                       // fade back to the portrait…
  clearTimeout(clipFadeT);
  clipFadeT = setTimeout(() => {             // …then actually tear down
    v.pause(); v.removeAttribute("src"); v.load();
    v.style.display = "none";
  }, 950);
  st("video clip done — portrait back");
}
$("clip").addEventListener("ended", stopClip);
$("clip").addEventListener("error", () => {
  if ($("clip").style.display !== "none") st("video clip failed to load");
});
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
// portrait size, driven by /maintain's View row (no command channel needed:
// it rides /api/state, so a reloaded page comes back in the same view)
let viewNow = "";
function applyView(v){
  if (v !== "wide" && v !== "full") v = "framed";
  if (v === viewNow) return;
  viewNow = v;
  const c = $("cam");
  c.classList.toggle("v-wide", v === "wide");
  c.classList.toggle("v-full", v === "full");
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
// ---- idle loop (2026-09-12, user: "how about closing of the eye randomly") -
// The parked portrait is ONE captured frame, so the avatar never blinks: for
// most of the exhibit the audience is looking at a photograph. Painting a fake
// blink onto a photo-real face looks worse than stillness, so instead we keep
// a few seconds of the avatar's own footage — connected, silent, blinking on
// its own — and loop that. The footage only exists while a session is up, and
// a session is only up while it speaks, so the ONE place to get it is the
// moment after an answer ends: we hold the session a little longer, once, and
// record there. After that the loop is reused and nothing is extended again.
const IDLE_SETTLE_MS = 1200;   // let the last word's mouth movement finish first
const IDLE_RECORD_MS = 5000;
let wantIdleLoop = false, idleUrl = null, idleRec = null, idleBusy = false, idleFails = 0;

function idleLoopReady(){ return !!(wantIdleLoop && idleUrl); }

function idleStream(){
  const v = $("vid");
  let ms = null;
  try{ ms = (v.srcObject instanceof MediaStream) ? v.srcObject
            : (v.captureStream ? v.captureStream() : null); }catch(e){ return null; }
  if (!ms) return null;
  const vids = ms.getVideoTracks();
  if (!vids.length) return null;
  try{ return new MediaStream([vids[0]]); }catch(e){ return ms; }   // video only: the loop is silent
}

function idleMime(){
  for (const m of ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm", "video/mp4"])
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) return m;
  return null;
}

function recordIdle(){
  if (idleBusy || !wantIdleLoop || idleUrl || idleFails >= 3) return;
  const mime = idleMime();
  if (!window.MediaRecorder || !mime){ idleFails = 99; st("idle loop: this browser cannot record"); return; }
  idleBusy = true;
  // hold the session up long enough to capture the silent tail
  liveUntil = Math.max(liveUntil, Date.now() + IDLE_SETTLE_MS + IDLE_RECORD_MS + 700);
  touch();
  setTimeout(() => {
    const ms = idleStream();
    if (!ms || !videoLive() || speakingNow){ idleBusy = false; idleFails++; return; }
    let chunks = [];
    try{ idleRec = new MediaRecorder(ms, {mimeType: mime, videoBitsPerSecond: 1200000}); }
    catch(e){ idleBusy = false; idleFails++; st("idle loop: recorder refused (" + e.message + ")"); return; }
    idleRec.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
    idleRec.onerror = () => { idleBusy = false; idleFails++; };
    idleRec.onstop = () => {
      idleRec = null; idleBusy = false;
      const blob = new Blob(chunks, {type: mime}); chunks = [];
      if (blob.size < 20000){ idleFails++; st("idle loop: clip too short, keeping the still"); return; }
      try{
        const url = URL.createObjectURL(blob);
        const el = $("idle");
        el.src = url; el.loop = true; el.muted = true;
        el.play().catch(() => {});
        if (idleUrl) URL.revokeObjectURL(idleUrl);
        idleUrl = url;
        st("idle loop captured (" + (blob.size / 1024 | 0) + " kB) — the portrait breathes now");
        // captured while idle and the flag is on: end the session so it stops
        // costing credits; the loop keeps the face alive on its own
        if (wantIdleLoop && !speakingNow && !turnActive()){ liveUntil = 0; park(); }
      }catch(e){ idleFails++; }
    };
    try{ idleRec.start(); setTimeout(() => { try{ idleRec && idleRec.stop(); }catch(e){} }, IDLE_RECORD_MS); }
    catch(e){ idleBusy = false; idleFails++; }
  }, IDLE_SETTLE_MS);
}

function dropIdleLoop(){
  try{ if (idleRec) idleRec.stop(); }catch(e){}
  idleRec = null; idleBusy = false;
  const el = $("idle");
  try{ el.pause(); el.removeAttribute("src"); el.load(); }catch(e){}
  el.style.display = "none";
  if (idleUrl){ URL.revokeObjectURL(idleUrl); idleUrl = null; }
}

function frameTick(){
  const live = wantLive || Date.now() < liveUntil || Date.now() < busyUntil;
  if (live){
    if (frozen && videoLive()){ $("still").style.display = "none"; frozen = false; }
    $("idle").style.display = "none";
  } else if (Date.now() >= freezeAt){
    if (!frozen){
      if (snap()){ $("still").style.display = "block"; frozen = true; snaps = 1; lastSnap = Date.now();
        if (!speakingNow) st(ready ? "portrait — still until asked" : "portrait — starts on the next question"); }
    } else if (snaps < 4 && Date.now() - lastSnap > 1000 && snap()){
      snaps++; lastSnap = Date.now();
      if (snaps === 4) try{ localStorage.setItem("cjap_still",
        $("still").toDataURL("image/jpeg", 0.85)); }catch(e){}
    }
    // the loop sits OVER the still, so a failed capture always falls back to it
    const useLoop = idleLoopReady();
    $("idle").style.display = useLoop ? "block" : "none";
    if (useLoop && $("idle").paused) $("idle").play().catch(() => {});
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
// until (2026-09-05): browser-clock epoch (s) by which the ROBOT has finished
// this clip; Infinity = unknown (a pre-fed `next` sentence). A clip that only
// reaches the session after that moment is dropped instead of mouthed late —
// while the session was still connecting, queued acks/fillers/sentences used
// to play back-to-back once it came up, leaving the lips seconds behind the
// voice for the whole answer. Sentences are never dropped in "avatar only"
// mode (the avatar IS the voice there).
function enqueue(name, until, aside){
  if (!name || sent.has(name)) return;
  sent.add(name);
  chain = chain.then(() => sendWav(name, until === undefined ? Infinity : until, !!aside)).catch(() => {});
}
async function sendWav(name, until, aside){
  if (stopped) return;
  if (!ready) await start();
  for (let w = 0; w < 40 && !ready && !stopped; w++) await sleep(250);
  if (!ready){ st("session not ready — clip skipped"); sent.delete(name); return; }
  if (Date.now()/1000 > until && (aside || voiceMode !== "avatar")){
    st((aside ? "aside" : "sentence") + " skipped — robot already finished it (session came up late)");
    return;
  }
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
    applyVideoCmd(stt.video_cmd);                    // play/stop an uploaded clip
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
    updateIndicator(stt);                            // same state pill as /audience
    applyView(stt.avatar_view);                      // /maintain View buttons
    wantIdleLoop = !!stt.avatar_idle_loop;           // 2026-09-12: was never wired — the loop was dormant
    // Alive whenever the page is open (flag on): with no loop captured yet,
    // open a session and record a few seconds of the avatar silent, then it
    // parks and loops that — blinking, breathing, its own micro-motion — with
    // no ongoing credits. Once captured, nothing re-opens until a question.
    if (wantIdleLoop && !idleUrl && !idleBusy && !stopped){
      if (ready){ if (!speakingNow) recordIdle(); }
      else { start(); }
    }
    const sp = stt.speaking || {}, as = stt.aside || {};
    // ack / filler clips ("Hmm.", "let me think…") — mouth them, no caption
    if (as.wav && as.ts && as.ts !== lastAsideTs && (Date.now()/1000 - (as.ts + skew)) < 6){
      lastAsideTs = as.ts; touch();
      enqueue(as.wav, as.ts + skew + (lagEma || 0.8) + (as.dur || 1.5), true);
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
          enqueue(sp.wav, sp.ts + skew + (lagEma || 0.8) + (sp.dur || 3));
        }
      }
      if (sp.next && sp.next.wav) enqueue(sp.next.wav);   // queue ahead (robot timing unknown yet)
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
        if (!sp.interrupted) recordIdle();   // the one moment the avatar is live and silent
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


def _liveavatar_get(path, api_key):
    """GET from api.liveavatar.com (stdlib urllib; 15s timeout)."""
    import urllib.request
    req = urllib.request.Request(
        "https://api.liveavatar.com" + path,
        headers={"X-API-KEY": api_key,
                 # their edge 403s python-urllib's default UA
                 "User-Agent": "supervaise-cjap/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


AVATAR_ID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")


def _avatar_lookup(avatar_id, api_key):
    """Ask LiveAvatar what this id is. Returns (ok, dict|message)."""
    try:
        out = _liveavatar_get("/v1/avatars/" + avatar_id, api_key)
    except Exception as e:
        # 404 = no such avatar on this key's account; 401 = wrong key
        code = getattr(e, "code", None)
        if code == 404:
            return False, ("no avatar " + avatar_id[:8] + "… on this account — "
                           "check the id, or paste the API key of the account that owns it")
        if code in (401, 403):
            return False, "LiveAvatar refused the API key (401/403)"
        return False, f"{type(e).__name__}: {e}"
    d = out.get("data") or {}
    if not d.get("id"):
        return False, "avatar not found: " + str(out.get("message"))
    return True, {"id": d["id"], "name": d.get("name") or "(unnamed)",
                  "status": d.get("status"), "preview_url": d.get("preview_url"),
                  "voice": (d.get("default_voice") or {}).get("name"),
                  "expired": bool(d.get("is_expired"))}


def _avatar_usable(avatar_id, api_key, sandbox):
    """Dry-run a session token for this avatar. The catalogue lookup only says
    whether the id exists on the key's space; this says whether a session can
    actually be opened with it. Custom avatars in particular are refused in
    sandbox mode ("not supported in sandbox mode"), which would otherwise only
    surface mid-exhibit on the next question. A token is not a session — nothing
    is started, so nothing is billed."""
    try:
        out = _liveavatar_request(
            "/v1/sessions/token",
            {"mode": "LITE", "avatar_id": avatar_id, "is_sandbox": bool(sandbox)},
            {"X-API-KEY": api_key})
    except Exception as e:
        body = ""
        try:
            body = e.read().decode("utf8", "replace")   # HTTPError carries the reasons
        except Exception:
            pass
        msgs = []
        try:
            for item in (json.loads(body).get("data") or []):
                if item.get("message"):
                    msgs.append(item["message"])
        except Exception:
            pass
        if not msgs:
            return False, f"{type(e).__name__}: {e}"
        why = "; ".join(msgs)
        if any("sandbox" in m.lower() for m in msgs) and sandbox:
            why += " — untick sandbox and apply again"
        if any("access" in m.lower() for m in msgs):
            why += " — paste the API key of the LiveAvatar account that owns it"
        return False, why
    if not (out.get("data") or {}).get("session_token"):
        return False, "LiveAvatar refused a session: " + str(out.get("message"))
    return True, "ok"


def avatar_conf_get(refresh=False):
    """The configured avatar, with its name/preview. `refresh` re-asks the API
    and updates the cache /maintain reads through state()."""
    conf = _read_json(LIVEAVATAR_CONF) or {}
    doc = avatar_conf_view()
    if not refresh or not conf.get("api_key"):
        return True, doc
    ok, info = _avatar_lookup(doc["avatar_id"], conf["api_key"])
    if not ok:
        return False, info
    _avatar_cache_put(info)
    return True, avatar_conf_view()


def _avatar_cache_put(info):
    tmp = f"{LIVEAVATAR_CACHE}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump({"id": info["id"], "name": info["name"], "status": info["status"],
                   "preview_url": info["preview_url"], "voice": info["voice"],
                   "ts": time.time()}, f)
    os.replace(tmp, LIVEAVATAR_CACHE)


def avatar_conf_set(body):
    """Operator picked a different avatar on /maintain. Validates the id against
    the API before storing it, so a typo can never leave the exhibit with a face
    that will not start. The live page is told to drop its cached portrait and
    re-capture; the next session opens with the new avatar."""
    conf = _read_json(LIVEAVATAR_CONF) or {}
    avatar_id = str(body.get("avatar_id") or "").strip()
    api_key = str(body.get("api_key") or "").strip() or conf.get("api_key") or ""
    if not avatar_id:
        return False, "paste an avatar id (LiveAvatar dashboard → the avatar → its ID)"
    if not AVATAR_ID_RE.match(avatar_id):
        return False, "that does not look like a LiveAvatar avatar id (hex UUID)"
    if not api_key:
        return False, "no API key stored — paste one alongside the avatar id"
    sandbox = bool(body.get("sandbox", conf.get("sandbox", True)))
    # can a session actually be opened with it? (the gate: a catalogue hit is
    # not enough — a custom avatar exists but is refused in sandbox mode)
    ok, why = _avatar_usable(avatar_id, api_key, sandbox)
    if not ok:
        return False, why
    ok, info = _avatar_lookup(avatar_id, api_key)
    if not ok:
        # usable but not in this key's catalogue listing: store it anyway,
        # the card just shows the id until ⟳ resolves a name
        info = {"id": avatar_id, "name": "(name not in the catalogue)",
                "status": "ACTIVE", "preview_url": None, "voice": None,
                "expired": False}
    new = dict(conf)
    new.update({"api_key": api_key, "avatar_id": avatar_id, "sandbox": sandbox})
    tmp = f"{LIVEAVATAR_CONF}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(new, f, indent=1)
    os.chmod(tmp, 0o600)          # the API key lives in this file
    os.replace(tmp, LIVEAVATAR_CONF)
    _avatar_cache_put(info)
    _avatar_page_cmd("avatar")    # page: drop the old portrait, re-capture
    warn = ""
    if info["expired"]:
        warn = " — WARNING: LiveAvatar reports this avatar as expired"
    elif info["status"] and info["status"] != "ACTIVE":
        warn = f" — WARNING: status {info['status']}"
    return True, (f"avatar → {info['name']} ({info['status']})"
                  f"{'' if new['sandbox'] else ', production'}{warn}")


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
             "avatar_id": conf.get("avatar_id") or AVATAR_ID_DEFAULT,
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
        cv = _cam.get("cv")
        while True:
            frame = cam_frame()
            if not frame:
                break
            if _cam["ts"] != last_ts:
                last_ts = _cam["ts"]
                h.wfile.write(f"--{boundary}\r\nContent-Type: image/jpeg\r\n"
                              f"Content-Length: {len(frame)}\r\n\r\n".encode())
                h.wfile.write(frame + b"\r\n")
                h.wfile.flush()
            # 2026-09-01 (user: "make the livestream faster"): push each frame the
            # moment the capture thread lands it instead of sleeping 100 ms per loop
            if cv is not None:
                with cv:
                    if _cam["ts"] == last_ts:
                        cv.wait(timeout=0.5)
            else:
                time.sleep(0.02)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
