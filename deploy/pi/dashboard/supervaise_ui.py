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
<div class="card" style="grid-column:1/-1"><h2>Recent turns (tracking)</h2>
  <div style="overflow-x:auto"><table id="hist"><tr><th>time</th><th>question</th><th>theme</th>
  <th>tokens</th><th>cost</th><th>STT s</th><th>compose s</th><th>speech</th><th>flags</th></tr></table></div></div>
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
      ' <span class="dim">(Anthropic only)</span>':'');
    let lat='STT '+m.stt_s+'s'+bar(m.stt_s,10)+'Compose '+m.compose_s+'s'+bar(m.compose_s,20);
    if(sp&&sp.question===m.question)
      lat+=(sp.streamed?'First audio '+(sp.first_audio_s!=null?sp.first_audio_s:'?')+'s'+bar(sp.first_audio_s||0,15)
        :'TTS synth '+sp.synth_s+'s'+bar(sp.synth_s,10)+'Playback '+sp.play_s+'s'+bar(sp.play_s,40))
        +(sp.interrupted?'<span class="raw">interrupted</span>':'');
    $('lat').innerHTML=lat;}
  const byQ={};
  (s.metas||[]).forEach(x=>{const k=x.question||'';byQ[k]=Object.assign(byQ[k]||{},x);});
  $('hist').innerHTML='<tr><th>time</th><th>question</th><th>theme</th><th>tokens</th>'+
    '<th>cost</th><th>STT s</th><th>compose s</th><th>speech</th><th>flags</th></tr>'+
    Object.values(byQ).sort((a,b)=>(b.ts||0)-(a.ts||0)).slice(0,12).map(x=>{
      const sp2=x.streamed?('first audio '+(x.first_audio_s!=null?x.first_audio_s+'s':'?'))
        :(x.synth_s!=null?('synth '+x.synth_s+'s / play '+x.play_s+'s'):'');
      const fl=[x.streamed?'stream':'',x.dynamic_tokens?'dyn-tok':'',x.interrupted?'CUT':''].filter(Boolean).join(' ');
      return '<tr><td>'+(x.ts?new Date(1000*x.ts).toLocaleTimeString():'')+'</td><td>'+
        esc((x.question||'').slice(0,60))+'</td><td>'+esc(x.theme||'')+'</td><td>'+esc(x.token_budget||'')+
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
    else:
        return False
    return True


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
