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

ASSETS = os.path.join(HOME, "pi_dashboard", "assets")
FACE_PHOTO = os.path.join(ASSETS, "cjap.jpg")       # real-photo face mode
FACE_CALIB = os.path.join(ASSETS, "face_calib.json")  # eye/mouth landmarks
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
        "wake_events": _tail_jsonl(WAKE_EVENTS, 12),
        "corrections": _tail_jsonl(POSTPROC_LOG, 20),
        "health": _health(),
        "has_last_answer": os.path.exists(LAST_ANSWER),
    }


# ---------------------------------------------------------------------------
# controls + entity editor
# ---------------------------------------------------------------------------

def control(action):
    if action == "mute":
        open(MUTE_TRIGGER, "w").close()
        return True, "mute trigger set (cuts current playback)"
    if action == "force-listen":
        open(WAKE_TRIGGER, "w").close()
        return True, "listening activated"
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

AUDIENCE_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chief Justice Artemio V. Panganiban</title><style>
:root{--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;--dim:#8b949e;--gold:#c9a227}
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;background:var(--bg);color:var(--ink);
  font-family:Georgia,'Times New Roman',serif;overflow:hidden}
#wrap{display:flex;flex-direction:column;height:100vh;padding:1.6vh 1.6vw;gap:1.6vh;
  align-items:center}
#cam{flex:0 0 62%;width:auto;max-width:96vw;aspect-ratio:16/9;display:flex;
  align-items:center;justify-content:center;background:#000;border-radius:14px;
  border:1px solid #21262d;overflow:hidden;position:relative}
#cam img{width:100%;height:100%;object-fit:contain}
#cam .idle{position:absolute;inset:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center;color:var(--dim);font-size:3vh;
  background:var(--panel)}
#cam .idle b{color:var(--gold);font-size:5vh;letter-spacing:.2em}
#say{flex:1;width:96vw;background:var(--panel);border-radius:14px;
  padding:2.4vh 3vw;display:flex;flex-direction:column;min-height:0;overflow:hidden}
#q{font-size:2.8vh;line-height:1.35;color:var(--dim);text-align:center;
  flex:0 0 auto;margin-bottom:1.2vh}
#q b{color:var(--ink);font-weight:normal}
#a{font-size:4.4vh;line-height:1.55;text-align:center;overflow-y:auto;
  flex:1;min-height:0;scrollbar-width:none}
#a::-webkit-scrollbar{display:none}
#a .cur{color:var(--gold)}
.idle-text{color:var(--dim);font-style:italic}
.think::after{content:'';animation:dots 1.5s steps(4,end) infinite}
@keyframes dots{0%{content:''}25%{content:'.'}50%{content:'..'}75%{content:'...'}}
</style></head><body><div id="wrap">
<div id="cam"><img id="camimg" alt="">
  <div class="idle" id="camidle"><b>CJAP</b><span>Chief Justice Artemio V. Panganiban</span></div></div>
<div id="say"><div id="q"></div>
  <div class="idle-text" id="a">Say &ldquo;Hey Cee-Jap&rdquo; to ask a question</div></div>
</div><script>
const esc=s=>{const d=document.createElement('div');d.innerText=s||'';return d.innerHTML};
let camOK=false;
function camTick(){
  const img=document.getElementById('camimg');
  const probe=new Image();
  probe.onload=()=>{img.src=probe.src;camOK=true;
    document.getElementById('camidle').style.display='none';};
  probe.onerror=()=>{if(!camOK)document.getElementById('camidle').style.display='flex';};
  probe.src='/api/camera.jpg?t='+Date.now();
}
let lastRender='';
function render(qText,html,idle){
  const q=document.getElementById('q'),a=document.getElementById('a');
  const key=qText+'\\u0000'+html;
  if(key===lastRender)return;lastRender=key;
  q.innerHTML=qText?'<b>&ldquo;'+esc(qText)+'&rdquo;</b>':'';
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
    const sp=s.speaking;
    // 1. speaking RIGHT NOW: trace sentence-by-sentence, current in gold
    if(sp&&!sp.done&&(sp.spoken||[]).length){
      render(lastU?lastU.text:'',
        sp.spoken.map((t,i)=>'<span'+(i===sp.spoken.length-1?' class="cur"':'')+
          '>'+esc(t)+'</span>').join(' '),false);
      return;
    }
    // 2. question heard, answer not yet speaking: show it immediately
    if(lastU&&(!sp||lastU.ts>sp.ts)&&(!lastC||lastU.ts>lastC.ts)){
      render(lastU.text,'<span class="think">Allow me a moment</span>',true);
      return;
    }
    // 3. finished: keep the full answer on screen
    if(sp&&sp.done&&(sp.spoken||[]).length){
      render(lastU?lastU.text:'',esc(sp.spoken.join(' ')),false);
      return;
    }
    if(lastC){render(lastU?lastU.text:'',esc(lastC.text),false);return;}
    render('','Say &ldquo;Hey Cee-Jap&rdquo; to ask a question',true);
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


FACE_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CJAP</title><style>
:root{--bg:#0d1117;--ink:#e6edf3;--gold:#c9a227;--dim:#8b949e}
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;background:var(--bg);color:var(--ink);overflow:hidden;
  font-family:Georgia,'Times New Roman',serif}
#stage{display:flex;flex-direction:column;align-items:center;
  justify-content:center;height:100vh;gap:1vh}
#face{width:min(60vw,66vh)}
#photoFrame{position:relative;overflow:hidden;border-radius:1.5vh;
  display:none}
#photoInner{position:relative;transform-origin:50% 62%}
#ph{display:block;width:100%;height:auto;user-select:none}
#phsvg{position:absolute;left:0;top:0;width:100%;height:100%}
#vig{position:absolute;inset:-2px;pointer-events:none;
  background:radial-gradient(ellipse at 50% 42%,transparent 58%,#0d1117 96%)}
#calBar{display:none;max-width:88vw;text-align:center;font-size:2.4vh;
  color:var(--ink)}
#calBar a{color:var(--gold)}
#calBar input{margin-top:.8vh;color:var(--dim)}
#cap{min-height:13vh;max-width:90vw;text-align:center;font-size:4vh;
  line-height:1.35;color:var(--dim)}
#cap b{color:var(--gold);font-weight:normal}
</style></head><body><div id="stage">
<svg id="face" viewBox="-170 -200 340 420">
<defs>
  <radialGradient id="gskin" cx="50%" cy="38%" r="75%">
    <stop offset="0%" stop-color="#c9a081"/>
    <stop offset="70%" stop-color="#b08663"/>
    <stop offset="100%" stop-color="#96694c"/></radialGradient>
  <linearGradient id="ghair" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="#dcdcdc"/>
    <stop offset="100%" stop-color="#93989e"/></linearGradient>
  <radialGradient id="giris" cx="40%" cy="35%" r="70%">
    <stop offset="0%" stop-color="#6b442a"/>
    <stop offset="100%" stop-color="#2a180d"/></radialGradient>
</defs>
<g id="headG">
  <ellipse cx="0" cy="168" rx="128" ry="66" fill="#232830"/>
  <path d="M -30 96 L 30 96 L 26 140 L -26 140 Z" fill="url(#gskin)"/>
  <path d="M -34 128 L 0 150 L 34 128 L 60 200 L -60 200 Z" fill="#f0ede6"/>
  <path d="M -6 138 L 6 138 L 10 176 L 0 196 L -10 176 Z" fill="#7a1f2b"/>
  <g id="head">
    <ellipse cx="-104" cy="-22" rx="14" ry="23" fill="url(#gskin)"/>
    <ellipse cx="104" cy="-22" rx="14" ry="23" fill="url(#gskin)"/>
    <path d="M 0 -148 C 88 -148 104 -76 99 -12 C 95 52 58 106 0 114
             C -58 106 -95 52 -99 -12 C -104 -76 -88 -148 0 -148 Z"
          fill="url(#gskin)"/>
    <path d="M -99 -38 C -112 -132 -58 -172 0 -172 C 58 -172 112 -132 99 -38
             C 94 -88 66 -122 0 -122 C -66 -122 -94 -88 -99 -38 Z"
          fill="url(#ghair)"/>
    <path d="M -46 -96 Q 0 -104 46 -96" stroke="rgba(60,35,20,.14)"
          stroke-width="2.5" fill="none"/>
    <path d="M -40 -85 Q 0 -92 40 -85" stroke="rgba(60,35,20,.10)"
          stroke-width="2" fill="none"/>
    <g id="browL"><path d="M -70 -64 Q -48 -74 -25 -65"
        stroke="#8b8f94" stroke-width="7.5" fill="none"
        stroke-linecap="round"/></g>
    <g id="browR"><path d="M 25 -65 Q 48 -74 70 -64"
        stroke="#8b8f94" stroke-width="7.5" fill="none"
        stroke-linecap="round"/></g>
    <g id="eyeL" transform="translate(-45,-38)">
      <ellipse rx="21" ry="11.5" fill="#f5f1ea"/>
      <g id="gazeL"><circle r="8.5" fill="url(#giris)"/>
        <circle r="3.6" fill="#140c06"/>
        <circle cx="2.6" cy="-2.6" r="1.7" fill="#fff" opacity=".85"/></g>
      <path id="lidLtop" fill="url(#gskin)"/>
      <path id="lidLbot" fill="url(#gskin)"/>
      <ellipse rx="21" ry="11.5" fill="none"
        stroke="rgba(60,35,20,.35)" stroke-width="1.2"/>
    </g>
    <g id="eyeR" transform="translate(45,-38)">
      <ellipse rx="21" ry="11.5" fill="#f5f1ea"/>
      <g id="gazeR"><circle r="8.5" fill="url(#giris)"/>
        <circle r="3.6" fill="#140c06"/>
        <circle cx="2.6" cy="-2.6" r="1.7" fill="#fff" opacity=".85"/></g>
      <path id="lidRtop" fill="url(#gskin)"/>
      <path id="lidRbot" fill="url(#gskin)"/>
      <ellipse rx="21" ry="11.5" fill="none"
        stroke="rgba(60,35,20,.35)" stroke-width="1.2"/>
    </g>
    <g stroke="#383c44" stroke-width="3.2" fill="none" opacity=".92">
      <rect x="-74" y="-59" width="58" height="42" rx="13"/>
      <rect x="16" y="-59" width="58" height="42" rx="13"/>
      <path d="M -16 -45 Q 0 -53 16 -45"/>
      <path d="M -74 -45 L -101 -34"/><path d="M 74 -45 L 101 -34"/>
    </g>
    <path d="M -4 -28 C -8 -6 -13 4 -15 12 M -15 12 Q -7 19 0 17 Q 7 19 15 12
             M 4 -28 C 8 -6 13 4 15 12"
          stroke="rgba(85,50,30,.40)" stroke-width="2.3" fill="none"
          stroke-linecap="round"/>
    <path d="M -20 22 Q -30 40 -34 50 M 20 22 Q 30 40 34 50"
          stroke="rgba(0,0,0,.08)" stroke-width="2.5" fill="none"/>
    <g id="mouthG" transform="translate(0,55)">
      <clipPath id="mclip"><path id="mclipP"/></clipPath>
      <path id="mInner" fill="#4e1f1c"/>
      <g clip-path="url(#mclip)">
        <rect id="teeth" x="-33" y="-16" width="66" height="15" rx="3"
              fill="#efe9dc"/>
        <ellipse id="tongue" cx="0" cy="16" rx="19" ry="10" fill="#9a4a42"/>
      </g>
      <path id="lipTop" fill="#a96b58"/>
      <path id="lipBot" fill="#b87862"/>
    </g>
    <path d="M -14 86 Q 0 92 14 86" stroke="rgba(0,0,0,.10)"
          stroke-width="2.5" fill="none"/>
  </g>
</g>
</svg>
<div id="photoFrame"><div id="photoInner">
  <img id="ph" alt=""><svg id="phsvg"></svg>
</div><div id="vig"></div></div>
<div id="calBar"><span id="calMsg"></span><br>
  <input type="file" id="phFile" accept="image/jpeg,image/png"></div>
<div id="cap"></div></div><script>
const $ = id => document.getElementById(id);
const SVGNS = "http://www.w3.org/2000/svg";
const Q = new URLSearchParams(location.search);
const KEY = Q.get("key") || "";
let MODE = "vector", havePhoto = false, calib = null;

const EMO = {
  neutral: {brow:0, tiltL:0, tiltR:0, squint:.12, smile:5,  head:0},
  warm:    {brow:1, tiltL:0, tiltR:0, squint:.30, smile:11, head:0},
  solemn:  {brow:5, tiltL:8, tiltR:-8, squint:.28, smile:-4, head:0},
  emphatic:{brow:-7, tiltL:0, tiltR:0, squint:.02, smile:6, head:0},
  question:{brow:-3, tiltL:-10, tiltR:2, squint:.10, smile:4, head:-3.5},
  amused:  {brow:-2, tiltL:0, tiltR:0, squint:.55, smile:14, head:2.5},
};
let emo = EMO.neutral, emoName = "neutral";

function setEmotion(name){
  emoName = name in EMO ? name : "neutral";
  emo = EMO[emoName];
  $("browL").setAttribute("transform",
    "translate(0," + emo.brow + ") rotate(" + emo.tiltL + ",-25,-65)");
  $("browR").setAttribute("transform",
    "translate(0," + emo.brow + ") rotate(" + emo.tiltR + ",25,-65)");
}

// ---- viseme lip sync -----------------------------------------------------
function visemeOf(ch){
  ch = ch.toLowerCase();
  if ("mbp".indexOf(ch) >= 0) return {o:.03, w:1};
  if ("fv".indexOf(ch) >= 0)  return {o:.13, w:1.05};
  if ("ouw".indexOf(ch) >= 0) return {o:.52, w:.62};
  if (ch === "a")             return {o:.85, w:.98};
  if (ch === "e")             return {o:.45, w:1.10};
  if ("iy".indexOf(ch) >= 0)  return {o:.30, w:1.14};
  if ("sz".indexOf(ch) >= 0)  return {o:.12, w:1.08};
  return {o:.22, w:.95};
}
let timeline = [], tlEnd = 0, audioStart = -1;
let capWords = [], capTimes = [];
function buildTimeline(words){
  timeline = []; capWords = []; capTimes = [];
  let prevEnd = 0;
  for (const wse of words){
    const w = wse[0], s = wse[1], e = wse[2];
    capWords.push(w); capTimes.push(s);
    if (s > prevEnd + .03) timeline.push({t:prevEnd, o:.05, w:1});
    const L = Math.max(1, w.length), dur = (e - s) / L;
    for (let i = 0; i < L; i++){
      const v = visemeOf(w[i]);
      timeline.push({t:s + i*dur, o:v.o, w:v.w});
    }
    prevEnd = e;
  }
  timeline.push({t:prevEnd, o:0, w:1});
  tlEnd = prevEnd;
}
function estimateWords(text){
  const ws = text.split(" ").filter(Boolean);
  let t = .12; const out = [];
  for (const w of ws){
    const d = .09 + .052*w.length;
    out.push([w, +t.toFixed(3), +(t+d).toFixed(3)]);
    t += d + .055;
  }
  return out;
}
function targetAt(tt){
  if (!timeline.length || tt < 0 || tt > tlEnd + .4) return {o:0, w:1};
  let cur = {o:0, w:1};
  for (const k of timeline){ if (k.t <= tt) cur = k; else break; }
  return cur;
}
function renderCap(tt){
  if (!capWords.length){ $("cap").innerHTML = ""; return; }
  let html = "";
  for (let i = 0; i < capWords.length; i++)
    html += (capTimes[i] <= tt ? "<b>"+capWords[i]+"</b>" : capWords[i]) + " ";
  $("cap").innerHTML = html;
}

// ---- shared mouth geometry (vector ids or photo-overlay ids) -------------
function mouthPaths(o, wdt, s){
  const cx = 36*wdt, cy = -s*.55;
  const top = -2 - o*7, bot = 2 + o*30;
  const inner = "M " + (-cx) + " " + cy + " Q 0 " + top + " " + cx + " " + cy
              + " Q 0 " + bot + " " + (-cx) + " " + cy + " Z";
  return {inner: inner, top: top, bot: bot,
    lipTop: "M " + (-cx-5) + " " + cy + " Q 0 " + (top-8) + " " + (cx+5)
      + " " + cy + " Q 0 " + (top+2) + " " + (-cx-5) + " " + cy + " Z",
    lipBot: "M " + (-cx-5) + " " + cy + " Q 0 " + (bot+9) + " " + (cx+5)
      + " " + cy + " Q 0 " + (bot-1) + " " + (-cx-5) + " " + cy + " Z"};
}
function setMouthVector(o, wdt, s){
  const m = mouthPaths(o, wdt, s);
  $("mInner").setAttribute("d", m.inner);
  $("mclipP").setAttribute("d", m.inner);
  $("teeth").setAttribute("y", m.top - 2);
  $("tongue").setAttribute("cy", m.bot - 4);
  $("lipTop").setAttribute("d", m.lipTop);
  $("lipBot").setAttribute("d", m.lipBot);
}
function setLids(side, closed, squint){
  const topY = -12 + Math.min(1, closed)*25;
  $("lid"+side+"top").setAttribute("d",
    "M -22 -16 L 22 -16 L 22 -12 Q 0 " + topY + " -22 -12 Z");
  const botY = 12 - squint*13;
  $("lid"+side+"bot").setAttribute("d",
    "M -22 16 L 22 16 L 22 12 Q 0 " + botY + " -22 12 Z");
}

// ---- photo mode ----------------------------------------------------------
let phGeom = null;   // {mx,my,scale,angle, eyes:[{x,y}], eyeRx, cheek}
function setupPhoto(){
  MODE = "photo";
  $("face").style.display = "none";
  const fr = $("photoFrame"), ph = $("ph");
  fr.style.display = "block";
  const ar = ph.naturalWidth / ph.naturalHeight;
  const w = Math.min(innerWidth*.66, innerHeight*.72*ar);
  fr.style.width = w + "px";
  const W = w, H = w/ar;
  const P = (nx, ny) => ({x: nx*W, y: ny*H});
  const L = P(calib.lx, calib.ly), R = P(calib.rx, calib.ry);
  const ML = P(calib.mlx, calib.mly), MR = P(calib.mrx, calib.mry);
  const eyeDist = Math.hypot(R.x-L.x, R.y-L.y);
  const mw = Math.hypot(MR.x-ML.x, MR.y-ML.y);
  phGeom = {
    mx: (ML.x+MR.x)/2, my: (ML.y+MR.y)/2,
    scale: mw/68,
    angle: Math.atan2(MR.y-ML.y, MR.x-ML.x)*180/Math.PI,
    eyes: [L, R], eyeRx: eyeDist*.16, cheek: "rgb(172,132,100)",
  };
  try{  // sample real cheek color for the eyelid patches
    const cv = document.createElement("canvas");
    cv.width = ph.naturalWidth; cv.height = ph.naturalHeight;
    const g = cv.getContext("2d");
    g.drawImage(ph, 0, 0);
    const sx = Math.round(calib.lx*ph.naturalWidth);
    const sy = Math.round((calib.ly + (calib.mly-calib.ly)*.4)
                          * ph.naturalHeight);
    const d = g.getImageData(sx, sy, 3, 3).data;
    phGeom.cheek = "rgb(" + d[0] + "," + d[1] + "," + d[2] + ")";
  }catch(e){}
  const svg = $("phsvg");
  svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  svg.innerHTML =
    '<defs><clipPath id="mclipPh"><path id="mclipPhP"/></clipPath></defs>' +
    '<g id="mouthPh" opacity=".2">' +
    '<path id="mInnerPh" fill="#3d1714"/>' +
    '<g clip-path="url(#mclipPh)">' +
    '<rect id="teethPh" x="-33" y="-16" width="66" height="15" rx="3" ' +
    'fill="#efe9dc"/>' +
    '<ellipse id="tonguePh" cx="0" cy="16" rx="19" ry="10" fill="#8e423b"/>' +
    '</g><path id="lipTopPh" fill="rgba(140,80,64,.55)"/>' +
    '<path id="lipBotPh" fill="rgba(155,90,70,.55)"/></g>' +
    '<ellipse id="lidPhL" opacity="0"/><ellipse id="lidPhR" opacity="0"/>';
  $("mouthPh").setAttribute("transform",
    "translate(" + phGeom.mx + "," + phGeom.my + ") rotate("
    + phGeom.angle + ") scale(" + phGeom.scale + ")");
  for (let i = 0; i < 2; i++){
    const el = $(i ? "lidPhR" : "lidPhL");
    el.setAttribute("cx", phGeom.eyes[i].x);
    el.setAttribute("cy", phGeom.eyes[i].y);
    el.setAttribute("rx", phGeom.eyeRx);
    el.setAttribute("fill", phGeom.cheek);
  }
}
function setMouthPhoto(o, wdt, s){
  const m = mouthPaths(o, wdt, s);
  $("mInnerPh").setAttribute("d", m.inner);
  $("mclipPhP").setAttribute("d", m.inner);
  $("teethPh").setAttribute("y", m.top - 2);
  $("tonguePh").setAttribute("cy", m.bot - 4);
  $("lipTopPh").setAttribute("d", m.lipTop);
  $("lipBotPh").setAttribute("d", m.lipBot);
  $("mouthPh").setAttribute("opacity",
    Math.min(1, .15 + o*2.4).toFixed(2));
}

// ---- calibration mode ----------------------------------------------------
const CAL_STEPS = [
  ["lx","ly","Click the CENTER of the eye on the LEFT of the photo"],
  ["rx","ry","Click the CENTER of the eye on the RIGHT"],
  ["mlx","mly","Click the LEFT corner of the mouth"],
  ["mrx","mry","Click the RIGHT corner of the mouth"]];
let calStep = 0, calDraft = {};
function setupCal(){
  MODE = "cal";
  $("face").style.display = "none";
  $("calBar").style.display = "block";
  const fr = $("photoFrame"), ph = $("ph");
  if (!havePhoto){
    $("calMsg").textContent =
      "No photo yet — choose a clear FRONTAL photo (JPEG/PNG, under 8 MB):";
    return;
  }
  fr.style.display = "block";
  const ar = ph.naturalWidth / ph.naturalHeight;
  fr.style.width = Math.min(innerWidth*.66, innerHeight*.66*ar) + "px";
  $("calMsg").textContent = CAL_STEPS[0][2];
  ph.style.cursor = "crosshair";
  ph.addEventListener("click", ev => {
    if (calStep >= CAL_STEPS.length) return;
    const r = ph.getBoundingClientRect();
    const nx = (ev.clientX - r.left)/r.width;
    const ny = (ev.clientY - r.top)/r.height;
    const st = CAL_STEPS[calStep];
    calDraft[st[0]] = nx; calDraft[st[1]] = ny;
    const svg = $("phsvg");
    svg.setAttribute("viewBox", "0 0 " + r.width + " " + r.height);
    const dot = document.createElementNS(SVGNS, "circle");
    dot.setAttribute("cx", nx*r.width); dot.setAttribute("cy", ny*r.height);
    dot.setAttribute("r", 5); dot.setAttribute("fill", "#c9a227");
    svg.appendChild(dot);
    calStep++;
    if (calStep < CAL_STEPS.length){
      $("calMsg").textContent = CAL_STEPS[calStep][2];
    } else {
      $("calMsg").textContent = "Saving…";
      fetch("/api/face-calib", {method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({key: KEY, calib: calDraft})})
      .then(r => r.json()).then(out => {
        $("calMsg").innerHTML = out.ok
          ? 'Saved. <a href="/face">Open the live face</a>'
          : "Failed: " + out.output;
      });
    }
  });
}
$("phFile").addEventListener("change", ev => {
  const f = ev.target.files[0];
  if (!f) return;
  $("calMsg").textContent = "Uploading…";
  const rd = new FileReader();
  rd.onload = () => {
    const b64 = String(rd.result).split(",")[1] || "";
    fetch("/api/face-photo", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({key: KEY, image_b64: b64})})
    .then(r => r.json()).then(out => {
      if (out.ok) location.reload();
      else $("calMsg").textContent = "Upload failed: " + out.output;
    });
  };
  rd.readAsDataURL(f);
});

// ---- animation loop ------------------------------------------------------
let mouthO = 0, mouthW = 1, blink = 0, blinkPhase = 0;
let nextBlink = Date.now() + 2600, gx = 0, gy = 0, gtx = 0, gty = 0;
function tick(){
  const now = Date.now();
  const tt = audioStart > 0 ? now/1000 - audioStart : -1;
  const tgt = targetAt(tt);
  mouthO += (tgt.o - mouthO)*.45;
  mouthW += (tgt.w - mouthW)*.3;
  if (tt >= 0 && tt <= tlEnd + .4) renderCap(tt);

  if (blinkPhase === 0 && now > nextBlink) blinkPhase = 1;
  if (blinkPhase === 1){ blink = Math.min(1, blink+.34);
    if (blink === 1) blinkPhase = 2; }
  else if (blinkPhase === 2){ blink = Math.max(0, blink-.22);
    if (blink === 0){ blinkPhase = 0;
      nextBlink = now + 2200 + Math.random()*3800; } }

  const talking = tt >= 0 && tt <= tlEnd;
  const breath = Math.sin(now/1900)*1.4;
  const nod = talking ? mouthO*2.2 : 0;
  const sway = talking ? Math.sin(now/700)*.7 : 0;

  if (MODE === "photo" && phGeom){
    setMouthPhoto(mouthO, mouthW, emo.smile*.5);
    const lidAmt = Math.max(blink, emo.squint*.4);
    for (const id of ["lidPhL","lidPhR"]){
      $(id).setAttribute("ry", Math.max(.5, phGeom.eyeRx*.62*lidAmt));
      $(id).setAttribute("opacity", lidAmt > .03 ? ".96" : "0");
    }
    $("photoInner").style.transform =
      "scale(1.06) rotate(" + ((emo.head*.5 + sway)*.6).toFixed(2)
      + "deg) translateY(" + ((breath - nod)*.6).toFixed(2) + "px)";
  } else if (MODE === "vector"){
    setMouthVector(mouthO, mouthW, emo.smile);
    setLids("L", blink, emo.squint); setLids("R", blink, emo.squint);
    if (!talking && Math.random() < .005){
      gtx = (Math.random()-.5)*10; gty = (Math.random()-.5)*5; }
    if (talking){ gtx = 0; gty = 1.5; }
    gx += (gtx-gx)*.07; gy += (gty-gy)*.07;
    $("gazeL").setAttribute("transform", "translate("+gx+","+gy+")");
    $("gazeR").setAttribute("transform", "translate("+gx+","+gy+")");
    $("headG").setAttribute("transform",
      "rotate(" + (emo.head + sway) + ") translate(0," + (breath - nod) + ")");
  }
  requestAnimationFrame(tick);
}
tick();

// ---- state poll ----------------------------------------------------------
let sentKey = "";
async function poll(){
  if (MODE === "cal"){ setTimeout(poll, 2000); return; }
  try{
    const st = await (await fetch("/api/state")).json();
    const sp = st.speaking || {};
    const skew = st.ts ? Date.now()/1000 - st.ts : 0;
    const fresh = sp.ts && (Date.now()/1000 - (sp.ts + skew)) < 30;
    if (fresh && sp.current && !sp.done){
      const key = sp.ts + "|" + sp.current;
      if (key !== sentKey){
        sentKey = key;
        setEmotion(sp.emotion || "neutral");
        buildTimeline(sp.words && sp.words.length ? sp.words
                      : estimateWords(sp.current));
        audioStart = sp.ts + skew;
        renderCap(0);
      }
    } else {
      if (sp.interrupted && timeline.length){
        timeline = []; tlEnd = 0; audioStart = -1;
        $("cap").innerHTML = ""; setEmotion("neutral");
      }
      const idle = audioStart < 0 || Date.now()/1000 - audioStart > tlEnd + 2;
      if (idle && emoName !== "neutral") setEmotion("neutral");
      if (idle && audioStart > 0 &&
          Date.now()/1000 - audioStart > tlEnd + 7){
        audioStart = -1; timeline = []; capWords = [];
        $("cap").innerHTML = "";
      }
      sentKey = "";
    }
  }catch(e){}
  setTimeout(poll, 250);
}
poll();

// ---- mode selection ------------------------------------------------------
(async function init(){
  try{
    const c = await (await fetch("/api/face-calib")).json();
    if (c && c.lx !== undefined) calib = c;
  }catch(e){}
  const ph = $("ph");
  ph.onload = () => { havePhoto = true; decide(); };
  ph.onerror = () => { havePhoto = false; decide(); };
  ph.src = "/assets/cjap.jpg?t=" + Date.now();
})();
function decide(){
  if (Q.get("calibrate")){ setupCal(); return; }
  if (havePhoto && calib) setupPhoto();
  else if (havePhoto && !calib)
    $("cap").innerHTML = "photo uploaded — finish setup at " +
      "/face?calibrate=1&key=…";
}
</script></body></html>"""


# ---------------------------------------------------------------------------
# request dispatch (called from dashboard.Handler)
# ---------------------------------------------------------------------------

def handle_get(h, path, params):
    """Returns True if this module handled the request."""
    if path == "/audience":
        h._send(200, AUDIENCE_PAGE, "text/html; charset=utf-8")
    elif path == "/face":
        h._send(200, FACE_PAGE, "text/html; charset=utf-8")
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
    elif path == "/api/state":
        h._send(200, json.dumps(state()))
    elif path == "/api/camera.jpg":
        frame = cam_frame()
        if frame:
            h._send(200, frame, "image/jpeg")
        else:
            h._send(503, json.dumps({"error": "camera unavailable"}))
    elif path == "/assets/cjap.jpg":
        try:
            h._send(200, open(FACE_PHOTO, "rb").read(), "image/jpeg")
        except OSError:
            h._send(404, json.dumps({"error": "no face photo uploaded"}))
    elif path == "/api/face-calib":
        h._send(200, json.dumps(_read_json(FACE_CALIB) or {}))
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
    elif path == "/api/face-photo":
        if not _authed({}, body):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            ok, out = _face_photo_put(body.get("image_b64", ""))
            h._send(200, json.dumps({"ok": ok, "output": out}))
    elif path == "/api/face-calib":
        if not _authed({}, body):
            h._send(403, json.dumps({"ok": False, "output": "bad key"}))
        else:
            ok, out = _face_calib_put(body.get("calib"))
            h._send(200, json.dumps({"ok": ok, "output": out}))
    else:
        return False
    return True


def _face_photo_put(image_b64):
    """Save the uploaded face photo (JPEG bytes, base64; ≤8 MB decoded)."""
    import base64
    try:
        raw = base64.b64decode(image_b64 or "", validate=True)
    except Exception:
        return False, "invalid base64"
    if not (1000 < len(raw) <= 8_000_000):
        return False, f"bad size ({len(raw)} bytes; need 1KB-8MB)"
    if not (raw[:3] == b"\xff\xd8\xff" or raw[:8] == b"\x89PNG\r\n\x1a\n"):
        return False, "not a JPEG/PNG file"
    try:
        tmp = FACE_PHOTO + ".tmp"
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, FACE_PHOTO)
        return True, "photo saved — now calibrate"
    except OSError as e:
        return False, str(e)


def _face_calib_put(calib):
    """Save normalized landmark coords {lx,ly,rx,ry,mlx,mly,mrx,mry}."""
    keys = ("lx", "ly", "rx", "ry", "mlx", "mly", "mrx", "mry")
    if not isinstance(calib, dict):
        return False, "calib must be an object"
    try:
        clean = {k: round(float(calib[k]), 4) for k in keys}
    except (KeyError, TypeError, ValueError):
        return False, f"calib needs float fields {keys}"
    if not all(0.0 <= v <= 1.0 for v in clean.values()):
        return False, "coords must be normalized 0..1"
    try:
        tmp = FACE_CALIB + ".tmp"
        with open(tmp, "w") as f:
            json.dump(clean, f)
        os.replace(tmp, FACE_CALIB)
        return True, "calibration saved"
    except OSError as e:
        return False, str(e)


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
