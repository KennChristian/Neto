#!/usr/bin/env python3
"""P2.5 dual web UI for the CJAP demo — served by pi_dashboard/dashboard.py.

Two views, one backend, one state feed:

    GET  /audience          public page for the external monitor:
                            camera feed TOP, transcribed question BOTTOM-LEFT,
                            the spoken answer BOTTOM-RIGHT (per EPK/Kenn spec).
                            No internals, no errors — degrades to a neutral idle.
    GET  /maintain?key=K    operator page (key-gated, CJ_DASH_KEY, default "cjap"):
                            everything + raw-vs-corrected ASR, NER log, theme/
                            token budget, stage latency, wake events, health,
                            controls, entity-dictionary editor.
    GET  /api/state         the single source of truth both views poll.
    GET  /api/camera.mjpg   MJPEG stream (rpicam-vid, lazy-started, auto-stops
                            ~90s after the last viewer leaves).
    POST /api/ctl           {"action": mute|force-listen|replay, "key": K}
    GET/POST /api/entities  entity_overrides.json read / validated atomic write
                            (takes effect immediately via P0 hot-reload).

Stdlib only, same discipline as dashboard.py.
"""
import json
import os
import re
import socket
import subprocess
import threading
import time

HOME = os.path.expanduser("~")
MAIN = os.path.join(HOME, "Supervaise-Reachy-Mini-Project-main")
TRANSCRIPT = "/dev/shm/cj_transcript.jsonl"
TURN_META = "/dev/shm/cj_turn_meta.jsonl"
WAKE_LIVE = "/dev/shm/cj_wake_live.json"
WAKE_EVENTS = "/dev/shm/cj_wake_events.jsonl"
POSTPROC_LOG = "/dev/shm/cj_postproc_corrections.jsonl"
LAST_ANSWER = "/dev/shm/cj_last_answer.mp3"
SPEAKING = "/dev/shm/cj_speaking.json"   # live per-sentence caption feed
MUTE_TRIGGER = "/dev/shm/cj_mute_trigger"
WAKE_TRIGGER = "/dev/shm/cj_wake_trigger"
ENTITY_OVERLAY = os.path.join(MAIN, "data", "entities", "entity_overrides.json")
CANNED_PATH = os.path.join(MAIN, "data", "entities", "canned_answers.json")
ASK_TRIGGER = "/dev/shm/cj_ask_trigger"   # /event buttons -> cj_voice_cloud
# Event mode: while this flag exists, spoken questions can match the
# scripted event_* canned entries (canned_answers.event_mode()). Persistent
# (survives reboot); toggled from the /event page. Buttons work regardless.
EVENT_FLAG = os.path.join(MAIN, "data", "entities", "event_mode.on")

ASSETS = os.path.join(HOME, "pi_dashboard", "assets")
LIVEAVATAR_CONF = os.path.join(ASSETS, "liveavatar.json")  # api_key etc.
os.makedirs(ASSETS, exist_ok=True)

DASH_KEY = os.environ.get("CJ_DASH_KEY", "cjap")


def _authed(params, body=None):
    key = params.get("key") or (body or {}).get("key")
    return key == DASH_KEY


# ---------------------------------------------------------------------------
# camera — one rpicam-vid MJPEG process, latest frame shared by all viewers
# ---------------------------------------------------------------------------

_cam = {"proc": None, "frame": b"", "ts": 0.0, "last_read": 0.0, "lock": threading.Lock()}
_CAM_CMD = ["rpicam-vid", "-n", "-t", "0", "--codec", "mjpeg", "--width", "800",
            "--height", "450", "--framerate", "10", "--inline", "-o", "-"]


def _cam_reader(proc):
    buf = b""
    try:
        while proc.poll() is None:
            chunk = proc.stdout.read(16384)
            if not chunk:
                break
            buf += chunk
            while True:
                s = buf.find(b"\xff\xd8")
                e = buf.find(b"\xff\xd9", s + 2) if s >= 0 else -1
                if s < 0 or e < 0:
                    if len(buf) > 4_000_000:
                        buf = b""
                    break
                _cam["frame"], _cam["ts"] = buf[s:e + 2], time.time()
                buf = buf[e + 2:]
            # auto-stop when nobody has fetched a frame for 90s
            if _cam["last_read"] and time.time() - _cam["last_read"] > 90:
                break
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            pass
        with _cam["lock"]:
            if _cam["proc"] is proc:
                _cam["proc"] = None


def cam_frame(timeout=4.0):
    """Latest JPEG frame (lazy-starts the camera). b'' if unavailable."""
    _cam["last_read"] = time.time()
    with _cam["lock"]:
        if _cam["proc"] is None or _cam["proc"].poll() is not None:
            try:
                p = subprocess.Popen(_CAM_CMD, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)
                _cam["proc"] = p
                threading.Thread(target=_cam_reader, args=(p,), daemon=True).start()
            except Exception:
                return b""
    t0 = time.time()
    while time.time() - _cam["ts"] > 2.0 and time.time() - t0 < timeout:
        time.sleep(0.1)
    return _cam["frame"] if time.time() - _cam["ts"] <= 2.0 else b""


# ---------------------------------------------------------------------------
# state aggregation
# ---------------------------------------------------------------------------

def _tail_jsonl(path, n):
    try:
        out = []
        for line in open(path).read().splitlines()[-n:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out
    except OSError:
        return []


def _read_json(path):
    try:
        return json.loads(open(path).read())
    except (OSError, ValueError):
        return None


_health_cache = {"ts": 0.0, "data": {}}


def _health():
    if time.time() - _health_cache["ts"] < 10:
        return _health_cache["data"]
    h = {}
    try:
        h["supervaise"] = subprocess.run(
            ["systemctl", "is-active", "supervaise.service"],
            capture_output=True, text=True, timeout=3).stdout.strip() == "active"
    except Exception:
        h["supervaise"] = False
    try:
        h["mic"] = "seeed" in open("/proc/asound/cards").read().lower() or \
                   "array" in open("/proc/asound/cards").read().lower() or \
                   len(open("/proc/asound/cards").read().strip()) > 10
    except OSError:
        h["mic"] = False
    try:
        s = socket.create_connection(("api.openai.com", 443), timeout=1.5)
        s.close()
        h["internet"] = True
    except OSError:
        h["internet"] = False
    h["camera"] = bool(_cam["frame"]) and time.time() - _cam["ts"] < 3
    _health_cache.update(ts=time.time(), data=h)
    return h


def state():
    """The single state document both views poll."""
    turns = _tail_jsonl(TRANSCRIPT, 30)
    metas = _tail_jsonl(TURN_META, 12)
    composed = [m for m in metas if m.get("phase") == "composed"]
    spoken = [m for m in metas if m.get("phase") == "spoken"]
    return {
        "ts": time.time(),
        "turns": turns,
        "meta": composed[-1] if composed else None,
        "spoken": spoken[-1] if spoken else None,
        "metas": metas,   # full recent-turn history for the tracking table
        "wake": _read_json(WAKE_LIVE),
        "speaking": _read_json(SPEAKING),
        "aside": _read_json("/dev/shm/cj_aside.json"),
        "stage": _read_json("/dev/shm/cj_stage.json"),
        "wake_events": _tail_jsonl(WAKE_EVENTS, 12),
        "corrections": _tail_jsonl(POSTPROC_LOG, 20),
        "health": _health(),
        "has_last_answer": os.path.exists(LAST_ANSWER),
        "event_mode": os.path.exists(EVENT_FLAG),
    }


# ---------------------------------------------------------------------------
# controls + entity editor
# ---------------------------------------------------------------------------

def control(action):
    if action == "mute":
        open(MUTE_TRIGGER, "w").close()
        return True, "mute trigger set (cuts current playback)"
    if action == "avatar-voice-on":
        with open("/dev/shm/cj_avatar_audio", "w") as f:
            f.write("solo")
        return True, "robot silenced — the avatar page is the voice"
    if action == "avatar-voice-sync":
        with open("/dev/shm/cj_avatar_audio", "w") as f:
            f.write("sync")
        return True, "both voices — robot delayed to match the avatar"
    if action == "avatar-voice-lips":
        # page open, avatar muted: robot keeps its voice but still holds the
        # head start so the avatar's mouth tracks it. Re-posted every 5s by
        # the page — the robot treats a stale flag (>15s) as "page gone".
        with open("/dev/shm/cj_avatar_audio", "w") as f:
            f.write("lips")
        return True, "avatar mouths along — robot voice"
    if action == "avatar-voice-off":
        try:
            os.unlink("/dev/shm/cj_avatar_audio")
        except OSError:
            pass
        return True, "robot speaker restored"
    if action == "force-listen":
        open(WAKE_TRIGGER, "w").close()
        return True, "listening activated"
    if action == "event-on":
        with open(EVENT_FLAG, "w") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
        return True, "event mode ON — spoken event questions get the script"
    if action == "event-off":
        try:
            os.unlink(EVENT_FLAG)
        except OSError:
            pass
        return True, "event mode OFF — normal conversation (buttons still work)"
    if action == "replay":
        if not os.path.exists(LAST_ANSWER):
            return False, "no stored answer yet"
        def _play():
            wav = "/dev/shm/cj_replay.wav"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet",
                            "-i", LAST_ANSWER, wav])
            subprocess.run(["aplay", "-q", wav])
            try:
                os.unlink(wav)
            except OSError:
                pass
        threading.Thread(target=_play, daemon=True).start()
        return True, "replaying last answer"
    return False, f"unknown action {action!r}"


def entities_get():
    try:
        return True, open(ENTITY_OVERLAY, encoding="utf-8").read()
    except OSError as e:
        return False, str(e)


def entities_put(text):
    try:
        doc = json.loads(text)
        for k in ("add", "merge", "remove"):
            if k not in doc:
                return False, f"missing top-level key {k!r}"
        if not isinstance(doc["add"], list) or not isinstance(doc["merge"], dict) \
                or not isinstance(doc["remove"], list):
            return False, "add must be a list, merge a dict, remove a list"
        tmp = ENTITY_OVERLAY + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp, ENTITY_OVERLAY)  # atomic; P0 hot-reload picks it up
        return True, "saved — live immediately (no restart)"
    except ValueError as e:
        return False, f"invalid JSON: {e}"
    except OSError as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# /event — phone page with one button per scripted event question
# ---------------------------------------------------------------------------

def _event_entries():
    """The event_* entries from canned_answers.json: scripted question +
    single verbatim answer each. Re-read per request (hot-editable)."""
    try:
        with open(CANNED_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        return [{"id": e["id"], "q": (e.get("ask") or [e["id"]])[0],
                 "a": e["answers"][0]}
                for e in raw.get("entries", [])
                if str(e.get("id", "")).startswith("event_") and e.get("answers")]
    except (OSError, ValueError, KeyError) as e:
        print(f"[event] canned_answers.json unreadable: {e}")
        return []


def ask_event(entry_id):
    """Queue one scripted answer for the robot: write the ask trigger the
    wake loop polls (30 s freshness on the robot side)."""
    for e in _event_entries():
        if e["id"] == entry_id:
            try:
                tmp = ASK_TRIGGER + ".tmp"
                with open(tmp, "w") as f:
                    json.dump({"q": e["q"], "a": e["a"], "id": e["id"]}, f)
                os.replace(tmp, ASK_TRIGGER)
                return True, "queued"
            except OSError as err:
                return False, str(err)
    return False, f"unknown question id: {entry_id!r}"


def event_page():
    def esc(t):
        return (t.replace("&", "&amp;").replace("<", "&lt;")
                 .replace(">", "&gt;").replace('"', "&quot;"))
    entries = _event_entries()
    btns = "\n".join(
        f'<button class="q" onclick="ask(\'{esc(e["id"])}\',this)">'
        f'<b>{i + 1}.</b> {esc(e["q"])}</button>'
        for i, e in enumerate(entries)) or \
        '<p class="sub">No event_* entries found in canned_answers.json.</p>'
    return EVENT_PAGE.replace("%BUTTONS%", btns)


AUDIENCE_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chief Justice Artemio V. Panganiban</title><style>
:root{--ink:#f2f6fa;--dim:#aab4c0;--mute:#6f7a88;--gold:#e6c352;--gold2:#b8952a;
  --ok:#7fd8a4;--warn:#f0a050;--blue:#7fc2ff;--panel:13,17,23}
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;color:var(--ink);overflow:hidden;
  font-family:Georgia,'Times New Roman',serif;
  background:#05080c radial-gradient(ellipse 70% 60% at 50% 38%,#151c26 0%,#0a0e14 55%,#05080c 100%)}
@keyframes blink{50%{opacity:.25}}
/* camera: a framed tile centred on the stage; knobs ?cam=<vw> ?pos=tr|tl */
#cam{position:fixed;top:5vh;left:50%;transform:translateX(-50%);
  width:min(44vw,calc(58vh * 16 / 9));aspect-ratio:16/9;background:#000;overflow:hidden;
  border-radius:1.6vh;border:1px solid rgba(255,255,255,.12);
  box-shadow:0 2.4vh 7vh rgba(0,0,0,.75),0 0 0 0 rgba(230,195,82,0);
  transition:box-shadow .8s ease,border-color .8s ease}
#cam.live{border-color:rgba(230,195,82,.55);
  box-shadow:0 2.4vh 7vh rgba(0,0,0,.75),0 0 4vh .3vh rgba(230,195,82,.18)}
#cam.tr,#cam.tl{transform:none;left:auto;top:6.5vh;width:min(30vw,calc(34vh * 16 / 9))}
#cam.tr{right:2vw}  #cam.tl{left:2vw}
#cam img{width:100%;height:100%;object-fit:cover;object-position:center}
#cam .idle{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;
  justify-content:center;color:var(--dim);font-size:2.6vh;gap:1.4vh;
  background:radial-gradient(ellipse at 50% 40%,#161b22,#06090d 70%)}
#cam .idle b{color:var(--gold);font-size:6vh;letter-spacing:.22em}
/* bottom scrim keeps text legible; the centre stays clear for the tile */
#scrim{position:fixed;left:0;right:0;bottom:0;height:36vh;pointer-events:none;
  background:linear-gradient(to top,rgba(4,7,10,.9) 0%,rgba(4,7,10,.4) 55%,rgba(4,7,10,0) 100%)}
/* the two floating cards: question intake left, answer right, levelled */
#bar{position:fixed;left:2vw;right:2vw;bottom:2.6vh;display:flex;justify-content:space-between;
  align-items:stretch;gap:2vw;pointer-events:none}
.card{min-width:0;min-height:22vh;max-height:42vh;display:flex;flex-direction:column;
  padding:1.7vh 1.6vw 1.6vh;border-radius:1.8vh;
  background:linear-gradient(to bottom,rgba(var(--panel),.8) 0%,rgba(var(--panel),.48) 60%,rgba(var(--panel),.08) 100%);
  -webkit-backdrop-filter:blur(18px) saturate(1.3);backdrop-filter:blur(18px) saturate(1.3);
  box-shadow:0 1.6vh 4vh rgba(0,0,0,.5);
  transition:opacity .6s ease,transform .6s cubic-bezier(.2,.8,.2,1)}
#qbox{flex:0 1 42%} #abox{flex:0 1 46%}
.card.hide{opacity:0;transform:translateY(3vh);pointer-events:none}
.card h3{flex:0 0 auto;display:flex;align-items:center;gap:1vw;margin-bottom:1.2vh;
  font-family:-apple-system,Segoe UI,Arial,sans-serif;font-size:1.45vh;font-weight:600;
  letter-spacing:.22em;text-transform:uppercase;color:var(--gold);opacity:.9}
.card h3::after{content:'';flex:1;height:1px;background:linear-gradient(90deg,rgba(230,195,82,.45),transparent)}
/* answer */
#a{flex:1;min-height:9vh;overflow-y:auto;scrollbar-width:none;text-align:left;
  font-size:3vh;line-height:1.5;text-shadow:0 .2vh .6vh rgba(0,0,0,.6)}
#a::-webkit-scrollbar{display:none}
#a span{color:rgba(242,246,250,.72);transition:color .5s}
#a .cur{color:var(--gold);text-shadow:0 0 1.6vh rgba(230,195,82,.25);animation:rise .45s ease-out}
#a.idle-text{display:flex;align-items:center;font-style:italic;color:var(--dim);font-size:2.6vh}
#a.idle-text em{color:var(--gold);font-style:normal;padding:0 .4vw}
.rise{animation:rise .45s ease-out}
@keyframes rise{from{opacity:0;transform:translateY(1.2vh)}to{opacity:1;transform:none}}
.think::after{content:'';animation:dots 1.5s steps(4,end) infinite}
@keyframes dots{0%{content:''}25%{content:'.'}50%{content:'..'}75%{content:'...'}}
/* question intake rows */
#rows{display:flex;flex-direction:column;gap:.8vh;overflow-y:auto;scrollbar-width:none;
  font-family:-apple-system,Segoe UI,Arial,sans-serif}
#rows::-webkit-scrollbar{display:none}
.row{display:grid;grid-template-columns:2.4vh minmax(0,1fr) auto;gap:.2vh .8vw;align-items:start;
  padding:1vh 1.1vw;border-radius:1.2vh;background:rgba(255,255,255,.035);animation:rise .45s ease-out}
.row.done{background:rgba(127,216,164,.07)} .row.active{background:rgba(230,195,82,.08)}
.row.flagged{background:rgba(240,160,80,.09)}
.row .ck{font-size:1.9vh;line-height:1.35;text-align:center;color:var(--mute)}
.row.done .ck{color:var(--ok)} .row.flagged .ck{color:var(--warn)}
.row.active .ck{color:var(--gold);animation:blink 1.1s ease-in-out infinite}
.row .b{min-width:0;font-size:1.85vh;line-height:1.4;color:var(--ink)}
.row .lb{font-size:1.3vh;font-weight:600;letter-spacing:.16em;text-transform:uppercase;
  color:var(--dim);margin-right:.6vw;white-space:nowrap}
.row.active .lb{color:var(--gold)} .row.done .lb{color:var(--ok)} .row.flagged .lb{color:var(--warn)}
.row .t{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:1.35vh;color:var(--mute);
  padding-top:.35vh;white-space:nowrap}
.row code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:1.6vh;padding:.15vh .6vh;
  border-radius:.6vh;background:rgba(127,216,164,.14);color:#b9f0cf}
.row .conf{color:var(--blue);font-size:1.6vh}
.row .rs{display:-webkit-box;color:var(--dim);font-size:1.55vh;line-height:1.35;margin-top:.3vh;
  overflow:hidden;-webkit-line-clamp:3;-webkit-box-orient:vertical}
.row .qt{font-weight:bold;font-family:Georgia,'Times New Roman',serif;font-size:2.1vh;color:var(--ink)}
</style></head><body>
<div id="cam"><img id="camimg" alt="">
  <div class="idle" id="camidle"><b>CJAP</b>
    <span>Chief Justice Artemio V. Panganiban</span></div>
</div>
<div id="scrim"></div>
<div id="bar">
  <div class="card hide" id="qbox"><h3>Question intake</h3><div id="rows"></div></div>
  <div class="card" id="abox"><h3>Answer</h3><div id="a" class="idle-text"></div></div>
</div><script>
const esc=s=>{const d=document.createElement('div');d.innerText=s||'';return d.innerHTML};
const IDLE='Say <em>&ldquo;Hey Cee-Jap&rdquo;</em> to ask a question';
const qs=new URLSearchParams(location.search),camW=parseFloat(qs.get('cam'));
if(camW>10&&camW<=100)document.getElementById('cam').style.width=camW+'vw';
if(['tr','tl'].includes(qs.get('pos')))document.getElementById('cam').classList.add(qs.get('pos'));
let camOK=false;
function camTick(){
  const img=document.getElementById('camimg'),probe=new Image();
  probe.onload=()=>{img.src=probe.src;camOK=true;document.getElementById('camidle').style.display='none';};
  probe.onerror=()=>{if(!camOK)document.getElementById('camidle').style.display='flex';};
  probe.src='/api/camera.jpg?t='+Date.now();
}
let curState='';
function setState(st){
  if(st===curState)return;curState=st;
  document.getElementById('cam').classList.toggle('live',st==='speaking');
}
let lastRows='';
function rowHtml(state,label,body,t){
  const ck=state==='done'?'&#10003;':state==='flagged'?'&#9888;':state==='active'?'&#9679;':'&#9675;';
  const ts=(t!=null&&state!=='active')?t.toFixed(1)+'s':'';
  return '<div class="row '+state+'"><span class="ck">'+ck+'</span><div class="b">'+
    '<span class="lb">'+label+'</span>'+body+'</div><span class="t">'+ts+'</span></div>';
}
function renderRows(stage,qText){
  const st=(stage&&stage.steps)||{};
  const tr=st.transcribe||{},rt=st.route||{},cp=st.compose||{},fd=st.fidelity||{};
  const parts=[];
  if(qText)parts.push(rowHtml('done','Transcribed','<span class="qt">'+esc(qText)+'</span>',tr.state==='done'?tr.t:null));
  else if(tr.state==='active')parts.push(rowHtml('active','Transcribed','<span class="think">'+esc(tr.detail||'listening')+'</span>'));
  if(rt.scope)parts.push(rowHtml('done','Scope','<code>'+esc(rt.scope)+'</code>'+
    (rt.scope_reason?'<span class="rs">'+esc(rt.scope_reason)+'</span>':''),rt.t));
  if(rt.state==='active')parts.push(rowHtml('active','Routed','<span class="think">'+esc(rt.detail||'choosing the topic')+'</span>'));
  else if(rt.state==='done')parts.push(rowHtml('done','Routed','<code>'+esc(rt.topic||rt.detail||'')+'</code>'+
    (rt.confidence?' <span class="conf">('+esc(rt.confidence)+')</span>':'')+
    (rt.route_reason?'<span class="rs">'+esc(rt.route_reason)+'</span>':''),rt.t));
  if(cp.state==='active')parts.push(rowHtml('active','Composed','<span class="think">'+esc(cp.detail||'writing')+'</span>'));
  else if(cp.state==='done')parts.push(rowHtml('done','Composed',esc(cp.detail||''),cp.t));
  if(fd.state==='active')parts.push(rowHtml('active','Fidelity','<span class="think">'+esc(fd.detail||'checking')+'</span>'));
  else if(fd.state==='done'||fd.state==='flagged')parts.push(rowHtml(fd.state,'Fidelity',esc(fd.detail||'')+
    (fd.state==='flagged'&&fd.reason?'<span class="rs">'+esc(fd.reason)+'</span>':''),fd.t));
  const html=parts.join('');
  if(html===lastRows)return;lastRows=html;
  const el=document.getElementById('rows');el.innerHTML=html;el.scrollTop=el.scrollHeight;
}
let lastRender='';
function render(html,idle,showQ){
  const a=document.getElementById('a');
  const key=html+(showQ?1:0);
  if(key===lastRender)return;lastRender=key;
  document.getElementById('qbox').classList.toggle('hide',!showQ);
  a.classList.toggle('idle-text',!!idle);
  a.innerHTML=html;
  const cur=a.querySelector('.cur');
  if(cur)cur.scrollIntoView({block:'center',behavior:'smooth'});
  else a.scrollTop=a.scrollHeight;
}
async function poll(){
  try{
    const s=await (await fetch('/api/state')).json();
    const turns=s.turns||[];
    const lastU=turns.filter(t=>t.role==='user').slice(-1)[0];
    const lastC=turns.filter(t=>t.role==='cj').slice(-1)[0];
    const sp=s.speaking,stg=s.stage;
    const turnTs=stg?stg.turn_ts:0;
    const qNow=(lastU&&lastU.ts>=turnTs-1)?lastU.text:'';
    const listening=stg&&stg.steps&&stg.steps.transcribe&&
      stg.steps.transcribe.state==='active'&&(s.ts-stg.ts)<60;
    renderRows(stg,qNow||(lastU?lastU.text:''));
    // 1. speaking right now: sentence-by-sentence, current in gold
    if(sp&&!sp.done&&(sp.spoken||[]).length){
      setState('speaking');
      render(sp.spoken.map((t,i)=>'<span'+(i===sp.spoken.length-1?' class="cur"':'')+
          '>'+esc(t)+'</span>').join(' '),false,true);
      return;
    }
    // 2. mic open / transcribing
    if(listening&&!qNow){setState('listening');
      render('<span class="think">Listening</span>',true,true);return;}
    // 3. question heard, answer being prepared
    if(lastU&&(!sp||lastU.ts>sp.ts)&&(!lastC||lastU.ts>lastC.ts)){setState('thinking');
      render('<span class="think">Allow me a moment</span>',true,true);return;}
    // 4. finished: keep the full answer and its intake on screen
    setState('idle');
    if(sp&&sp.done&&(sp.spoken||[]).length){render(esc(sp.spoken.join(' ')),false,!!lastU);return;}
    if(lastC){render(esc(lastC.text),false,!!lastU);return;}
    render(IDLE,true,false);
  }catch(e){/* audience view never shows errors */}
}
setInterval(poll,300);poll();
setInterval(camTick,150);camTick();
</script></body></html>"""


MAINTAIN_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CJAP — Maintenance</title><style>
:root{--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;--dim:#8b949e;--gold:#c9a227;
  --ok:#3fb950;--bad:#f85149;--line:#21262d}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,Segoe UI,Arial,sans-serif;padding:12px}
h1{font-size:18px;margin-bottom:10px}h1 b{color:var(--gold)}
h2{font-size:13px;color:var(--gold);text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;min-width:0}
.chip{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;margin:0 6px 6px 0;background:#21262d}
.chip.ok{color:var(--ok)}.chip.bad{color:var(--bad)}
button{background:#21262d;border:1px solid #30363d;color:var(--ink);border-radius:8px;
  padding:8px 14px;margin:0 8px 8px 0;font-size:14px;cursor:pointer}
button:hover{border-color:var(--gold)}
table{width:100%;border-collapse:collapse;font-size:12.5px}
td,th{padding:4px 6px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--dim);font-weight:600}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:12px}
.bar{height:8px;background:#21262d;border-radius:4px;overflow:hidden;margin:2px 0 6px}
.bar i{display:block;height:100%;background:var(--gold)}
textarea{width:100%;height:220px;background:#0d1117;color:var(--ink);border:1px solid #30363d;
  border-radius:8px;font-family:ui-monospace,Consolas,monospace;font-size:12px;padding:8px}
.raw{color:var(--bad)}.fix{color:var(--ok)}
#msg{color:var(--dim);font-size:12px;margin-left:6px}
img#cam{width:100%;border-radius:8px;background:#000;min-height:120px}
.dim{color:var(--dim)}
</style></head><body>
<h1><b>CJAP</b> Maintenance — <span class="dim">audience view: <a style="color:var(--gold)" href="/audience" target="_blank">/audience</a> · ops: <a style="color:var(--gold)" href="/" target="_blank">/</a></span></h1>
<div class="grid">
<div class="card"><h2>Health</h2><div id="health"></div><div id="flags"></div>
  <h2 style="margin-top:8px">Controls</h2>
  <button onclick="ctl('mute')">&#128263; Mute / interrupt</button>
  <button onclick="ctl('force-listen')">&#127908; Force listen</button>
  <button onclick="ctl('replay')">&#128260; Replay last</button>
  <button onclick="act('restart-app')">&#8635; Restart app</button>
  <button onclick="act('test-sound')">&#128266; Test sound</button>
  <button onclick="act('tagalog-sample')">&#127908; Tagalog sample</button>
  <span id="msg"></span>
  <h2 style="margin-top:8px">Camera</h2><img id="cam" alt="(camera offline)">
</div>
<div class="card"><h2>System</h2><div id="services"></div><div id="sys" class="dim">loading&hellip;</div></div>
<div class="card"><h2>Wake meter <span class="dim" id="wakenow"></span></h2>
  <div class="bar" style="height:14px"><i id="wakebar" style="width:0%"></i></div>
  <canvas id="spark" style="width:100%;height:64px;background:#0d1117;border-radius:6px"></canvas>
  <table id="wake"><tr><th>time</th><th>score</th></tr></table></div>
<div class="card"><h2>Current turn</h2><div id="turn" class="dim">no turn yet</div>
  <h2 style="margin-top:10px">Stage latency</h2><div id="lat" class="dim">&mdash;</div></div>
<div class="card"><h2>Grounding documents <span class="dim">(composer context, last turn)</span></h2>
  <div id="docs" class="dim" style="max-height:260px;overflow:auto">no turn yet</div></div>
<div class="card" style="grid-column:1/-1"><h2>Recent turns (tracking)</h2>
  <div style="overflow-x:auto"><table id="hist"><tr><th>time</th><th>question</th><th>theme</th>
  <th>docs</th><th>tokens</th><th>cost</th><th>STT s</th><th>compose s</th><th>speech</th><th>flags</th></tr></table></div></div>
<div class="card"><h2>Conversation (raw vs corrected)</h2>
  <table id="conv"><tr><th>who</th><th>text</th></tr></table></div>
<div class="card"><h2>NER corrections (P0)</h2>
  <table id="ner"><tr><th>heard</th><th>&rarr; canonical</th><th>class</th><th>conf</th></tr></table></div>
<div class="card"><h2>Logs
  <select id="logunit" onchange="loadLogs()" style="background:#21262d;color:var(--ink);
    border:1px solid #30363d;border-radius:6px;padding:2px 6px;margin-left:8px">
    <option value="supervaise">supervaise</option>
    <option value="wifi-fallback">wifi-fallback</option>
    <option value="speaker-watchdog">speaker-watchdog</option>
  </select>
  <button style="padding:2px 10px;margin-left:6px" onclick="loadLogs()">refresh</button></h2>
  <pre id="logs" class="mono" style="max-height:240px;overflow:auto;white-space:pre-wrap"></pre></div>
<div class="card"><h2>Entity dictionary overlay <span class="dim">(saves live, no restart)</span></h2>
  <textarea id="ov" spellcheck="false"></textarea>
  <button onclick="saveOv()">Save overlay</button><span id="ovmsg"></span></div>
</div><script>
const KEY=new URLSearchParams(location.search).get('key')||localStorage.getItem('cjkey')||'';
if(KEY)localStorage.setItem('cjkey',KEY);
const esc=s=>{const d=document.createElement('div');d.innerText=s==null?'':s;return d.innerHTML};
const $=id=>document.getElementById(id);
async function ctl(a){const r=await(await fetch('/api/ctl',{method:'POST',
  body:JSON.stringify({action:a,key:KEY})})).json();
  $('msg').innerText=r.output||'';}
async function act(a){$('msg').innerText=a+'\\u2026';
  const r=await(await fetch('/api/action',{method:'POST',
    body:JSON.stringify({action:a})})).json();
  $('msg').innerText=r.ok?a+' ok':'FAILED: '+(r.output||'');}
async function loadOv(){const r=await(await fetch('/api/entities?key='+KEY)).json();
  if(r.ok)$('ov').value=r.content;}
async function saveOv(){const r=await(await fetch('/api/entities?key='+KEY,{method:'POST',
  body:JSON.stringify({content:$('ov').value,key:KEY})})).json();
  $('ovmsg').innerText=r.output;}
async function loadLogs(){try{
  const t=await(await fetch('/api/logs?unit='+$('logunit').value+'&lines=80')).text();
  $('logs').textContent=t;
  $('logs').scrollTop=$('logs').scrollHeight;}catch(e){$('logs').textContent='log fetch failed';}}
function bar(v,max){return '<div class="bar"><i style="width:'+Math.min(100,100*v/max)+'%"></i></div>'}
function chip(k,ok,txt){return '<span class="chip '+(ok?'ok':'bad')+'">'+k+' '+(txt||(ok?'&#10003;':'&#10007;'))+'</span>'}
async function poll(){try{
  const s=await(await fetch('/api/state')).json();
  $('health').innerHTML=Object.entries(s.health||{}).map(([k,v])=>chip(k,v)).join('');
  const m=s.meta,sp=s.spoken;
  if(m){$('turn').innerHTML=
    '<b>Q:</b> '+esc(m.question)+'<br><b>raw ASR:</b> <span class="mono raw">'+esc(m.raw_asr)+'</span>'+
    '<br><b>topic:</b> '+esc(m.topic)+' <b>theme:</b> '+esc(m.theme)+
    ' <b>conf:</b> '+esc(m.confidence)+
    '<br><b>token budget:</b> '+esc(m.token_budget)+(m.dynamic_tokens?' (dynamic)':' (fixed)')+
    (m.cost_usd!=null?'<br><b>cost:</b> '+(100*m.cost_usd).toFixed(2)+'&cent; this turn'+
      (m.cost_total_usd!=null?' &middot; $'+m.cost_total_usd.toFixed(2)+' since service start':'')+
      ' <span class="dim">(Anthropic only)</span>':'')+
    (m.fidelity_flags?(m.fidelity_flags.length
      ?'<br><b>fidelity:</b> <span class="raw">'+esc(m.fidelity_flags.join(', '))+'</span> &mdash; '+
        esc((m.fidelity_reasoning||'').slice(0,120))
      :'<br><b>fidelity:</b> <span class="fix">clean</span>'):'');
    $('docs').innerHTML=(m.docs&&m.docs.length)?m.docs.map(d=>
      '<div style="margin-bottom:8px'+(d.dropped_for_budget?';opacity:.45':'')+'">'+
      '<b>'+esc(d.title||d.doc_id)+'</b>'+
      (d.dropped_for_budget?' <span class="raw">dropped (token budget)</span>':'')+
      '<br><span class="mono dim">'+esc(d.doc_id)+(d.date?' &middot; '+esc(d.date):'')+
      (d.theme_label?' &middot; '+esc(d.theme_label):'')+'</span>'+
      (d.summary?'<br><span class="dim">'+esc(d.summary)+'</span>':'')+'</div>').join('')
      :(m.docs?'<span class="dim">none (canned / out-of-topic / meta turn)</span>'
        :'<span class="dim">no doc data (turn predates this feature)</span>');
    let lat='STT '+m.stt_s+'s'+bar(m.stt_s,10)+'Compose '+m.compose_s+'s'+bar(m.compose_s,20);
    if(sp&&sp.question===m.question)
      lat+=(sp.streamed?'First audio '+(sp.first_audio_s!=null?sp.first_audio_s:'?')+'s'+bar(sp.first_audio_s||0,15)
        :'TTS synth '+sp.synth_s+'s'+bar(sp.synth_s,10)+'Playback '+sp.play_s+'s'+bar(sp.play_s,40))
        +(sp.interrupted?'<span class="raw">interrupted</span>':'');
    $('lat').innerHTML=lat;}
  const byQ={};
  (s.metas||[]).forEach(x=>{const k=x.question||'';byQ[k]=Object.assign(byQ[k]||{},x);});
  $('hist').innerHTML='<tr><th>time</th><th>question</th><th>theme</th><th>docs</th><th>tokens</th>'+
    '<th>cost</th><th>STT s</th><th>compose s</th><th>speech</th><th>flags</th></tr>'+
    Object.values(byQ).sort((a,b)=>(b.ts||0)-(a.ts||0)).slice(0,12).map(x=>{
      const sp2=x.streamed?('first audio '+(x.first_audio_s!=null?x.first_audio_s+'s':'?'))
        :(x.synth_s!=null?('synth '+x.synth_s+'s / play '+x.play_s+'s'):'');
      const fl=[x.streamed?'stream':'',x.dynamic_tokens?'dyn-tok':'',x.interrupted?'CUT':'',
        (x.fidelity_flags&&x.fidelity_flags.length)?('FID:'+x.fidelity_flags.join(',')):''].filter(Boolean).join(' ');
      const dks=(x.docs||[]).filter(d=>!d.dropped_for_budget).map(d=>d.doc_id).join(', ');
      return '<tr><td>'+(x.ts?new Date(1000*x.ts).toLocaleTimeString():'')+'</td><td>'+
        esc((x.question||'').slice(0,60))+'</td><td>'+esc(x.theme||'')+
        '</td><td title="'+esc(dks)+'">'+esc(dks.slice(0,48)+(dks.length>48?'\\u2026':''))+
        '</td><td>'+esc(x.token_budget||'')+
        '</td><td>'+(x.cost_usd!=null?(x.cost_usd?(100*x.cost_usd).toFixed(2)+'¢':'free'):'')+
        '</td><td>'+esc(x.stt_s!=null?x.stt_s:'')+'</td><td>'+esc(x.compose_s!=null?x.compose_s:'')+
        '</td><td>'+esc(sp2)+'</td><td'+(x.interrupted?' class="raw"':'')+'>'+esc(fl)+'</td></tr>';}).join('');
  $('conv').innerHTML='<tr><th>who</th><th>text</th></tr>'+
    (s.turns||[]).slice(-14).reverse().map(t=>'<tr><td>'+esc(t.role)+'</td><td>'+esc(t.text)+'</td></tr>').join('');
  $('ner').innerHTML='<tr><th>heard</th><th>&rarr; canonical</th><th>class</th><th>conf</th></tr>'+
    (s.corrections||[]).slice(-14).reverse().map(c=>'<tr><td class="raw">'+esc(c.surface)+
    '</td><td class="fix">'+esc(c.canonical)+'</td><td>'+esc(c.class)+'</td><td>'+esc(c.confidence)+'</td></tr>').join('');
  $('wake').innerHTML='<tr><th>time</th><th>score</th></tr>'+
    (s.wake_events||[]).slice(-8).reverse().map(e=>'<tr><td>'+
    new Date(1000*(e.ts||0)).toLocaleTimeString()+'</td><td>'+esc((e.score||0).toFixed?e.score.toFixed(3):e.score)+'</td></tr>').join('');
}catch(e){}}
let spark=[];
async function wakeTick(){try{
  const w=await(await fetch('/api/wake')).json();
  const sc=w.score!=null?w.score:0,th=w.threshold!=null?w.threshold:0.07;
  $('wakenow').innerText=(w.live?'live ':'OFFLINE ')+sc.toFixed(3)+' / thr '+th;
  $('wakebar').style.width=Math.min(100,100*sc/Math.max(th*2,0.01))+'%';
  $('wakebar').style.background=sc>=th?'var(--bad)':'var(--gold)';
  spark.push(sc);if(spark.length>200)spark.shift();
  const c=$('spark'),g=c.getContext('2d');
  if(c.width!==c.clientWidth){c.width=c.clientWidth;c.height=64;}
  g.clearRect(0,0,c.width,c.height);
  const ymax=Math.max(th*2,0.1);
  g.strokeStyle='#f8514966';g.beginPath();
  g.moveTo(0,64-64*th/ymax);g.lineTo(c.width,64-64*th/ymax);g.stroke();
  g.strokeStyle='#c9a227';g.beginPath();
  spark.forEach((v,i)=>{const x=i*c.width/200,y=64-Math.min(64,64*v/ymax);
    i?g.lineTo(x,y):g.moveTo(x,y);});
  g.stroke();
}catch(e){}}
async function sysTick(){try{
  const st=await(await fetch('/api/status')).json();
  $('services').innerHTML=Object.entries(st.services||{}).map(
    ([k,v])=>chip(k,v.active==='active')).join('')+chip('daemon',!!st.reachy_daemon);
  const sy=st.system||{},wf=st.wifi||{};
  $('sys').innerHTML=
    '<b>CPU</b> '+(sy.temp_c!=null?sy.temp_c+'&deg;C':'?')+' &nbsp;<b>load</b> '+
    ((sy.load||[])[0]!=null?sy.load[0].toFixed(2):'?')+
    ' &nbsp;<b>mem</b> '+(sy.mem_used_pct!=null?sy.mem_used_pct+'%':'?')+
    ' &nbsp;<b>disk</b> '+(sy.disk_used_pct!=null?sy.disk_used_pct+'%':'?')+
    ' &nbsp;<b>throttle</b> '+esc(sy.throttled||'?')+
    '<br><b>WiFi</b> '+esc(wf.essid||'none')+' '+esc(wf.signal_dbm||'')+'dBm &nbsp;<b>IP</b> '+esc(wf.ip||'?')+
    '<br><b>Audio</b> '+esc((st.audio||{}).route||'?');
  const env=((st.wake||{}).env)||{};
  $('flags').innerHTML=[['stream','CJ_STREAM_SPEECH'],['dyn-filler','CJ_DYNAMIC_FILLER'],
    ['dyn-tokens','CJ_DYNAMIC_TOKENS_ENABLED'],['postproc','CJ_POSTPROC_ENABLED'],
    ['stop-word','CJ_STOP_WORD_ENABLED']].map(([n,k])=>chip(n,env[k]==='1')).join('');
}catch(e){}}
function camTick(){const p=new Image();p.onload=()=>{$('cam').src=p.src};
  p.src='/api/camera.jpg?t='+Date.now();}
setInterval(poll,1000);poll();
setInterval(wakeTick,300);wakeTick();
setInterval(sysTick,5000);sysTick();
setInterval(camTick,200);camTick();loadOv();loadLogs();
</script></body></html>"""

GATE_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>CJAP</title>
<style>body{background:#0d1117;color:#e6edf3;font-family:Arial;display:flex;align-items:center;
justify-content:center;height:100vh}form{text-align:center}input{padding:10px;border-radius:8px;
border:1px solid #30363d;background:#161b22;color:#e6edf3;font-size:16px}
button{padding:10px 18px;margin-left:8px;border-radius:8px;border:1px solid #c9a227;
background:#21262d;color:#e6edf3;font-size:16px}</style></head><body>
<form onsubmit="location='/maintain?key='+document.getElementById('k').value;return false">
<p style="margin-bottom:10px">Maintenance access key</p>
<input id="k" type="password" autofocus><button>Enter</button></form></body></html>"""


EVENT_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CJAP Event Questions</title><style>
body{background:#0d1117;color:#e6edf3;font-family:Arial;margin:0;padding:16px;
 max-width:560px;margin-left:auto;margin-right:auto}
h1{font-size:18px;color:#c9a227;margin:4px 0 2px}
p.sub{color:#8b949e;font-size:13px;margin:0 0 14px}
button.q{display:block;width:100%;text-align:left;margin:10px 0;padding:15px 16px;
 border-radius:12px;border:1px solid #30363d;background:#161b22;color:#e6edf3;
 font-size:16px;line-height:1.35;cursor:pointer}
button.q:active{background:#21262d;border-color:#c9a227}
button.q:disabled{opacity:.45}
button.q b{color:#c9a227;margin-right:6px}
#status{margin-top:14px;padding:10px 12px;border-radius:10px;background:#161b22;
 border:1px solid #30363d;font-size:14px;color:#8b949e;min-height:20px}
.ok{color:#3fb950}.warn{color:#d29922}
#mode{display:flex;align-items:center;justify-content:space-between;gap:12px;
 margin:12px 0;padding:12px 14px;border-radius:12px;background:#161b22;
 border:1px solid #30363d}
#modeTxt{font-size:14px;color:#8b949e;line-height:1.35}
#modeTxt b{display:block;font-size:15px;color:#e6edf3}
#modeBtn{flex-shrink:0;width:64px;height:34px;border-radius:17px;border:1px solid
 #30363d;background:#21262d;position:relative;cursor:pointer;transition:background .15s}
#modeBtn span{position:absolute;top:3px;left:4px;width:26px;height:26px;
 border-radius:13px;background:#8b949e;transition:left .15s,background .15s}
#modeBtn.on{background:#1f3524;border-color:#3fb950}
#modeBtn.on span{left:32px;background:#3fb950}
</style></head><body>
<h1>CJAP &mdash; Event Questions</h1>
<p class="sub">Backup buttons: if the robot mishears the emcee, tap the question
and it speaks the exact scripted answer.</p>
<div id="mode"><div id="modeTxt"><b>Event mode: &hellip;</b>&hellip;</div>
<div id="modeBtn" onclick="toggleMode()"><span></span></div></div>
%BUTTONS%
<div id="status">&hellip;</div>
<script>
const KEY=new URLSearchParams(location.search).get('key')||'';
const st=document.getElementById('status');
let queuedAt=0, evMode=null;
function paintMode(on){
  evMode=on;
  document.getElementById('modeBtn').className=on?'on':'';
  document.getElementById('modeTxt').innerHTML=on
    ?'<b>Event mode: ON</b>Spoken event questions are answered with the script.'
    :'<b>Event mode: OFF</b>Normal conversation \\u2014 the buttons below still work.';
}
async function toggleMode(){
  const action=evMode?'event-off':'event-on';
  try{
    const r=await fetch('/api/ctl',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({key:KEY,action})});
    const j=await r.json();
    if(j.ok) paintMode(!evMode);
    else st.innerHTML='<span class="warn">Toggle failed:</span> '+String(j.output||'error').replace(/</g,'&lt;');
  }catch(e){st.innerHTML='<span class="warn">Network error &mdash; try again.</span>';}
}
async function ask(id,btn){
  btn.disabled=true; setTimeout(()=>btn.disabled=false,4000);
  try{
    const r=await fetch('/api/ask',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({key:KEY,id})});
    const j=await r.json();
    if(j.ok){queuedAt=Date.now();
      st.innerHTML='<span class="ok">Queued.</span> The robot answers as soon as it is idle (a tap expires after 30s).';}
    else st.innerHTML='<span class="warn">Failed:</span> '+String(j.output||'error').replace(/</g,'&lt;');
  }catch(e){st.innerHTML='<span class="warn">Network error &mdash; try again.</span>';}
}
async function poll(){
  try{
    const s=await(await fetch('/api/state')).json();
    if(s.event_mode!==evMode) paintMode(!!s.event_mode);
    const sp=s.speaking||{};
    if(sp.current && !sp.done){
      st.innerHTML='<b class="ok">Speaking:</b> '+String(sp.current).replace(/</g,'&lt;');
      queuedAt=0;
    }else if(!(queuedAt && Date.now()-queuedAt<30000)){
      st.textContent='Robot idle \\u2014 listening for the wake word.';
    }
  }catch(e){}
}
setInterval(poll,1000);poll();
</script></body></html>"""


FACE_AVATAR_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CJAP LiveAvatar</title>
<script src="https://cdn.jsdelivr.net/npm/livekit-client@2/dist/livekit-client.umd.min.js"></script>
<style>
:root{--bg:#0d1117;--ink:#e6edf3;--gold:#c9a227;--dim:#8b949e}
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;background:var(--bg);color:var(--ink);overflow:hidden;
  font-family:Georgia,'Times New Roman',serif}
#stage{display:flex;flex-direction:column;align-items:center;
  justify-content:center;height:100vh;gap:1.2vh}
#vidbox{position:relative;width:min(64vw,74vh);aspect-ratio:9/10;
  background:#161b22;border-radius:1.5vh;overflow:hidden;
  display:flex;align-items:center;justify-content:center}
video{width:100%;height:100%;object-fit:cover}
#bar{display:flex;gap:1.2vw;align-items:center;font-size:2.2vh}
button{background:#21262d;color:var(--ink);border:1px solid #30363d;
  border-radius:.8vh;padding:.8vh 1.6vw;font-size:2.2vh;cursor:pointer}
button:hover{border-color:var(--gold)}
#st{color:var(--dim);font-size:2vh;max-width:88vw;text-align:center}
#cap{min-height:10vh;max-width:90vw;text-align:center;font-size:3.6vh;
  line-height:1.35;color:var(--gold)}
</style></head><body><div id="stage">
<div id="vidbox"><span id="hint" style="color:var(--dim)">
  press Start to open the sandbox avatar session</span>
<video id="vid" autoplay playsinline></video>
<audio id="aud" autoplay></audio></div>
<div id="bar">
  <button id="btnStart">Start</button>
  <button id="btnStop">Stop</button>
  <button id="btnMute">voice: robot</button>
</div>
<div id="st">idle</div><div id="cap"></div></div><script>
const $ = id => document.getElementById(id);
const KEY = new URLSearchParams(location.search).get("key") || "";
let room = null, ws = null, ready = false, sessTok = null, startP = null;
let avatarMuted = true, lastStart = 0, keepTimer = null;
let pendingLagT0 = null, lagEma = null, skew = 0;
$("aud").muted = true;
const sleep = ms => new Promise(r => setTimeout(r, ms));

function st(msg){ $("st").textContent = msg; }

async function post(path, doc){
  doc.key = KEY;
  const r = await fetch(path, {method:"POST",
    headers:{"Content-Type":"application/json"}, body:JSON.stringify(doc)});
  return r.json();
}

// ---- session ------------------------------------------------------------
function start(){
  if (ready) return Promise.resolve();
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
  if (!out.ok){ st("session failed: " + JSON.stringify(out.output)); return; }
  const s = out.output;
  sessTok = s.session_token;
  st("connecting to room…");
  try{
    room = new LivekitClient.Room();
    room.on(LivekitClient.RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === "video"){ track.attach($("vid"));
        $("hint").style.display = "none"; }
      if (track.kind === "audio"){ track.attach($("aud"));
        $("aud").muted = avatarMuted; }
    });
    await room.connect(s.livekit_url, s.livekit_client_token);
  }catch(e){ st("LiveKit connect failed: " + e.message); return; }
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
         (m.state === "connected" ? " — ask the robot something" : ""));
      const was = ready;
      ready = (m.state === "connected");
      if (ready && !was) setVoice(voiceMode === "robot" ? "sync" : voiceMode);
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
    ready = false; stopKeep();
    st("session ended (sandbox caps at ~1 min)" +
       (speakingNow ? " — reconnecting mid-answer…" : " — restarts on next answer"));
    if (speakingNow) setTimeout(start, 300);   // pick the answer back up
  };
  sock.onerror = () => { ready = false; };
  keepTimer = setInterval(() => {
    if (ws && ws.readyState === 1)
      ws.send(JSON.stringify({type:"session.keep_alive",
                              event_id:String(Date.now())}));
  }, 25000);
  await connected;
}
function stopKeep(){ if (keepTimer){ clearInterval(keepTimer);
  keepTimer = null; } }

async function stop(){
  stopKeep(); ready = false;
  try{ if (ws) ws.close(); }catch(e){}
  try{ if (room) room.disconnect(); }catch(e){}
  if (sessTok) await post("/api/avatar-stop", {session_token: sessTok});
  sessTok = null; sent.clear(); sentOrder.length = 0;
  await post("/api/ctl", {action: "avatar-voice-off"});   // robot: no holds
  st("stopped — press Start to resume mouthing along");
  stopped = true;
}
let stopped = false;
$("btnStart").onclick = () => { stopped = false; heartbeat(); start(); };
$("btnStop").onclick = stop;

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
  $("btnMute").textContent = "voice: " + (mode === "robot" ? "robot (avatar mouths along)"
    : mode === "avatar" ? "AVATAR only" : "BOTH synced");
}
$("btnMute").onclick = () => setVoice(
  MODES[(MODES.indexOf(voiceMode) + 1) % MODES.length]);
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
  }catch(e){ st("audio feed failed: " + e.message); }
}

// ---- state poll ----------------------------------------------------------
let curKey = "", speakingNow = false, lastAsideTs = 0, driftShown = "";
async function poll(){
  try{
    const stt = await (await fetch("/api/state")).json();
    if (stt.ts) skew = Date.now()/1000 - stt.ts;   // Pi clock → browser clock
    const sp = stt.speaking || {}, as = stt.aside || {};
    // ack / filler clips ("Hmm.", "let me think…") — mouth them, no caption
    if (as.wav && as.ts && as.ts !== lastAsideTs && (Date.now()/1000 - (as.ts + skew)) < 6){
      lastAsideTs = as.ts; enqueue(as.wav);
    }
    if (sp.current && !sp.done){
      const key = sp.wav || (sp.ts + "|" + sp.current);
      if (key !== curKey){
        const wasIdle = !speakingNow;
        curKey = key; speakingNow = true;
        $("cap").textContent = sp.current;
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
        speakingNow = false; curKey = "";
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
# request dispatch (called from dashboard.Handler)
# ---------------------------------------------------------------------------

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
                pass
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
        h.end_headers()
    elif path == "/api/state":
        h._send(200, json.dumps(state()))
    elif path == "/api/camera.jpg":
        frame = cam_frame()
        if frame:
            h._send(200, frame, "image/jpeg")
        else:
            h._send(503, json.dumps({"error": "camera unavailable"}))
    elif path == "/face":   # retired drawn-face page → the avatar is the face
        h.send_response(302)
        h.send_header("Location", "/face-avatar")
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
    else:
        return False
    return True


def handle_post(h, path, body):
    if path == "/api/ctl":
        if not _authed({}, body):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            ok, out = control(body.get("action", ""))
            h._send(200, json.dumps({"ok": ok, "output": out}))
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
