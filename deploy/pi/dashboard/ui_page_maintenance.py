"""/maintain — operator maintenance page (MAINTAIN_PAGE + GATE_PAGE).

Split out of supervaise_ui.py on 2026-08-29 (shared names star-copied from
ui_common so page code reads exactly as before; ui_routes is the facade).
"""
import ui_common as _c
globals().update({k: v for k, v in vars(_c).items() if not k.startswith("__")})


MAINTAIN_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CJAP — Maintenance</title><style>
:root{--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;--dim:#8b949e;--gold:#c9a227;
  --ok:#3fb950;--bad:#f85149;--line:#21262d;--btn:#21262d;--btnline:#30363d}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,Segoe UI,Arial,sans-serif;padding:0 16px 24px}
.hdr{position:sticky;top:0;z-index:5;background:rgba(13,17,23,.96);backdrop-filter:blur(6px);
  border-bottom:1px solid var(--line);margin:0 -16px 16px;padding:12px 16px;
  display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px 16px}
h1{font-size:24px;font-weight:700;line-height:1.2}h1 b{color:var(--gold)}
h1 small{display:block;font-size:14px;font-weight:400;color:var(--dim);margin-top:2px}
h1 small a{color:var(--gold);text-decoration:none}h1 small a:hover{text-decoration:underline}
.statuslinks{display:flex;gap:10px;flex-wrap:wrap}
.statuslinks a{display:inline-flex;align-items:center;gap:9px;padding:11px 18px;border-radius:10px;
  font-size:16px;font-weight:600;background:var(--btn);border:1px solid var(--btnline);
  color:var(--ink);text-decoration:none;white-space:nowrap}
.statuslinks a:hover{border-color:var(--gold);color:var(--gold)}
.statuslinks a i{width:10px;height:10px;border-radius:50%;background:var(--ok);display:inline-block}
.grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:14px}
.sec{grid-column:1/-1;font-size:13px;color:var(--dim);text-transform:uppercase;letter-spacing:.14em;
  margin-top:10px;padding-bottom:4px;border-bottom:1px solid var(--line)}
.sec:first-child{margin-top:0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;min-width:0;grid-column:span 4}
.c6{grid-column:span 6}.c8{grid-column:span 8}.c12{grid-column:1/-1}
.strip{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;margin:8px 0 14px;padding:10px 14px;border:1px solid var(--line);border-radius:12px;background:var(--panel);font-size:14px}
.strip b{font-weight:600}.strip .ok{color:#3fb950}.strip .bad{color:#e5484d}.strip .warn{color:var(--gold)}.strip .k{color:var(--dim);margin-right:4px}
.stack{grid-column:span 6;display:flex;flex-direction:row;gap:14px;min-width:0;align-self:start}.stack .card{flex:1 1 0;min-width:0;min-height:0;grid-column:auto;display:flex;flex-direction:column;overflow:hidden}.stack .mtbl{flex:1 1 auto;min-height:0;overflow:auto;margin-top:6px}
@media(max-width:1200px){.card,.c6,.c8,.stack{grid-column:span 6}.c12{grid-column:1/-1}}
@media(max-width:760px){.card,.c6,.c8,.c12,.stack{grid-column:1/-1}.stack{flex-direction:column}body{padding:0 10px 20px}
  .hdr{margin:0 -10px 12px;padding:10px}h1{font-size:20px}.statuslinks a{flex:1;justify-content:center}}
h2{font-size:15px;color:var(--gold);text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px;
  display:flex;align-items:center;gap:8px;flex-wrap:wrap}
h3{font-size:15px;margin:0 0 6px}
.chip{display:inline-block;padding:4px 12px;border-radius:999px;font-size:13px;margin:0 6px 6px 0;background:#21262d}
.chip.ok{color:var(--ok)}.chip.bad{color:var(--bad)}
button{background:var(--btn);border:1px solid var(--btnline);color:var(--ink);border-radius:10px;
  padding:12px 18px;margin:0;font-size:16px;font-weight:600;cursor:pointer;min-height:46px}
button:hover{border-color:var(--gold)}button:active{transform:translateY(1px)}
button.sm{padding:6px 12px;font-size:14px;min-height:0;font-weight:500}
.btns{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:10px}
.btns .lbl{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.1em;min-width:56px}
input[type=text],input[type=password],input:not([type]){background:#0d1117;color:var(--ink);border:1px solid #30363d;border-radius:8px;padding:10px 12px;font-size:15px}
select{background:#21262d;color:var(--ink);border:1px solid #30363d;border-radius:8px;padding:6px 10px;font-size:14px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
td,th{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--dim);font-weight:600}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:13px}
.bar{height:8px;background:#21262d;border-radius:4px;overflow:hidden;margin:2px 0 6px}
.bar i{display:block;height:100%;background:var(--gold)}
textarea{width:100%;height:240px;background:#0d1117;color:var(--ink);border:1px solid #30363d;
  border-radius:8px;font-family:ui-monospace,Consolas,monospace;font-size:13px;padding:10px;margin-bottom:10px}
.raw{color:var(--bad)}.fix{color:var(--ok)}
#msg{color:var(--dim);font-size:13px;display:block;min-height:1.3em}
.saybox{flex-wrap:nowrap}.saybox input{flex:1 1 auto;min-width:0;height:46px}
@media(max-width:600px){.saybox{flex-wrap:wrap}.saybox input{flex-basis:100%}}
img#cam{width:100%;border-radius:8px;background:#000;min-height:120px;display:block}
.dim{color:var(--dim)}
pre{max-height:280px;overflow:auto;white-space:pre-wrap;background:#0d1117;border-radius:8px;padding:10px}
</style></head><body>
<div class="hdr">
<h1><b>CJAP</b> Maintenance<small>audience view: <a href="/audience" target="_blank">/audience</a> &middot; ops: <a href="/" target="_blank">/</a></small></h1>
<div class="statuslinks" title="Provider status pages (open in new tab)">
  <a href="https://status.claude.com" target="_blank" rel="noopener"><i></i>Claude status</a>
  <a href="https://status.elevenlabs.io" target="_blank" rel="noopener"><i></i>ElevenLabs status</a>
</div>
</div>
<div id="strip" class="strip">loading&hellip;</div>
<div class="grid">
<div class="sec">Status</div>
<div class="card c6"><h2>Health</h2><div id="health"></div><div id="flags"></div></div>
<div class="card c6"><h2>System</h2><div id="services"></div><div id="sys" class="dim">loading&hellip;</div></div>
<div class="sec">Controls</div>
<div class="card c6" id="controls-card"><h2>Controls</h2>
  <div class="btns"><span class="lbl">Speech</span>
    <button id="btn-mute" onclick="ctl('mute')" title="Robot stops listening (wake word + stop word ignored) but keeps speaking">&#127908; Mute mic</button>
    <button id="btn-unmute" onclick="ctl('unmute')" style="display:none;background:var(--bad)">&#127908; UNMUTE MIC</button>
    <button onclick="ctl('interrupt')">&#9209; Interrupt</button>
    <button onclick="ctl('force-listen')">&#127908; Force listen</button>
    <button onclick="ctl('replay')">&#128260; Replay last</button>
    <button onclick="ctl('tempo-reset')" title="Forget the session speaking-rate average used to smooth sentence tempo">&#8634; Reset voice tempo</button></div>
  <div class="btns"><span class="lbl">App</span>
    <button onclick="act('restart-app')">&#8635; Restart app</button>
    <button onclick="act('test-sound')">&#128266; Test sound</button>
    <button onclick="act('tagalog-sample')">&#127908; Tagalog sample</button>
    <button onclick="rebootPi()" style="border-color:var(--bad)">&#9211; Reboot Pi</button></div>
  <div class="btns"><span class="lbl">Event</span>
    <button id="btn-ev-on" onclick="ctl('event-on')">&#127915; Event mode ON</button>
    <button id="btn-ev-off" onclick="ctl('event-off')" style="display:none;border-color:var(--gold)">&#127915; Event mode OFF</button>
    <span class="dim" id="ev-hint">scripted event questions answer with the script (paraphrases too)</span></div>
  <div class="btns saybox"><span class="lbl">Say</span>
    <input type="text" id="say-text" maxlength="500" placeholder="Type what CJ should say, then press Enter or Speak" autocomplete="off">
    <button id="say-btn" onclick="sayText()">&#128483; Speak</button></div>
  <span id="msg"></span>
</div>
<div class="stack">
<div class="card"><h2>Wake meter <span class="dim" id="wakenow"></span></h2>
  <div class="bar" style="height:14px"><i id="wakebar" style="width:0%"></i></div>
  <canvas id="spark" style="width:100%;height:48px;background:#0d1117;border-radius:6px"></canvas>
  <div class="mtbl"><table id="wake"><tr><th>time</th><th>score</th></tr></table></div></div>
<div class="card"><h2>Stop meter <span class="dim" id="stopnow"></span></h2>
  <div class="bar" style="height:14px"><i id="stopbar" style="width:0%"></i></div>
  <canvas id="stopspark" style="width:100%;height:48px;background:#0d1117;border-radius:6px"></canvas>
  <div class="mtbl"><table id="stopt"><tr><th>time</th><th>score</th></tr></table></div></div>
</div>
<div class="card c8"><h2>Mechanical actions <span class="dim">(head, antennas, motors — runs via the voice app when idle)</span></h2>
  <div class="btns"><span class="lbl">Head</span>
    <button onclick="ctl('gesture-center')">&#127919; Center</button>
    <button onclick="ctl('gesture-nod')">&#128588; Nod</button>
    <button onclick="ctl('gesture-shake')">&#128581; Shake</button>
    <button onclick="ctl('gesture-look-left')">&#8592; Look left</button>
    <button onclick="ctl('gesture-look-right')">&#8594; Look right</button>
    <button onclick="ctl('gesture-look-up')">&#8593; Look up</button>
    <button onclick="ctl('gesture-look-down')">&#8595; Look down</button>
    <button onclick="ctl('gesture-tilt-left')">&#8630; Tilt left</button>
    <button onclick="ctl('gesture-tilt-right')">&#8631; Tilt right</button>
    <button onclick="ctl('gesture-bow')">&#128583; Bow</button></div>
  <div class="btns"><span class="lbl">Antennas</span>
    <button onclick="ctl('gesture-antennas-up')">&#9650; Up</button>
    <button onclick="ctl('gesture-antennas-down')">&#9660; Down</button>
    <button onclick="ctl('gesture-antennas-wiggle')">&#12336; Wiggle</button></div>
  <div class="btns"><span class="lbl">Behaviours</span>
    <button onclick="ctl('gesture-perk')">&#9889; Perk (wake ack)</button>
    <button onclick="ctl('gesture-scan')">&#128064; Scan (look around)</button></div>
  <div class="btns"><span class="lbl">Motion</span>
    <button onclick="ctl('gesture-idle-off')">&#10074;&#10074; Idle motion off</button>
    <button onclick="ctl('gesture-idle-on')">&#9654; Idle motion on</button>
    <button onclick="if(confirm('Motors off: the head goes limp. Support it if needed. Continue?'))ctl('gesture-motors-off')" style="background:var(--bad)">&#9940; Motors off</button>
    <button onclick="ctl('gesture-motors-on')">&#9889; Motors on</button>
    <span class="dim">motors off = servos unpowered (safe to reposition by hand); motors on re-centers and resumes idle motion</span></div>
  <span id="msg3" class="dim"></span>
</div>
<div class="sec">Live</div>
<div class="card c8"><h2>Manual actions</h2>
  <div class="btns"><span class="lbl">Tuning</span>
    <label class="dim">Wake threshold <input type="number" id="tn-wake" step="0.01" min="0.01" max="1" style="width:92px"></label>
    <label class="dim">Stop threshold <input type="number" id="tn-stop" step="0.005" min="0.001" max="1" style="width:92px"></label>
    <label class="dim">Listen time (s) <input type="number" id="tn-listen" step="0.1" min="0.3" max="10" style="width:92px"></label>
    <label class="dim" title="Maximum articulation rate; faster sentences are slowed (pitch unchanged). 13 = measured comfortable, 15 = brisk">Pace ceiling (chars/s) <input type="number" id="tn-pace" step="0.5" min="8" max="25" style="width:92px"></label>
    <label class="dim" title="Hard ceiling on spoken words per answer (60 ≈ 25 s)">Max words <input type="number" id="tn-length" step="5" min="30" max="150" style="width:92px"></label>
    <button onclick="applyTuning()">&#10003; Apply &amp; restart app</button>
    <span class="dim" id="tn-hint">values from wakeword.conf; listen time = silence after your last word before CJ answers; pace = speaking-speed ceiling (lower = slower); max words = hard ceiling per answer (60 ≈ 25 s of speech); applying restarts the voice app (~25 s quiet)</span></div>
  <div class="btns"><span class="lbl">Speaker</span>
    <button onclick="act('audio-sony')">&#128264; Sony</button>
    <button onclick="act('audio-marshall')">&#128264; Marshall</button>
    <button onclick="act('audio-internal')">&#129302; Internal</button>
    <button onclick="ctl('bt-connect-sony')">&#128268; Reconnect Sony</button>
    <button onclick="ctl('bt-connect-marshall')">&#128268; Reconnect Marshall</button>
    <button onclick="ctl('bt-pulse')">&#12336; Pulse BT speaker</button>
    <button onclick="act('stop-watchdog')">Watchdog off</button>
    <button onclick="act('start-watchdog')">Watchdog on</button>
    <span class="dim">the watchdog puts audio back on a connected Bluetooth speaker within 15 s — switch it off first to stay on Internal</span></div>
  <div class="btns"><span class="lbl">Voice ID</span>
    <button onclick="act('enroll-voice')">&#127908; Enroll voice</button>
    <button onclick="act('gate-on')">Gate on</button>
    <button onclick="act('gate-off')">Gate off</button></div>
  <div class="btns"><span class="lbl">Services</span>
    <button onclick="ctl('restart-keepalive')">&#8635; bt-keepalive</button>
    <button onclick="ctl('restart-watchdog')">&#8635; speaker-watchdog</button>
    <button onclick="ctl('restart-dashboard')">&#8635; dashboard</button></div>
  <span id="msg2" class="dim"></span>
</div>
<div class="card"><h2>Camera <span class="dim" id="camstate"></span></h2>
  <div class="btns"><span class="lbl">Camera</span>
    <button id="btn-cam-off" onclick="ctl('camera-off')">&#9210; Camera off</button>
    <button id="btn-cam-on" onclick="ctl('camera-on')">&#127909; Camera on</button>
    <span class="dim" id="cam-hint"></span></div>
  <img id="cam" alt="(camera offline)">
  <div id="cam-off-box" class="dim" style="display:none;padding:18px 0">camera is OFF &mdash; rpicam-vid stopped, nothing is capturing</div></div>
<div class="card"><h2>LiveAvatar page <span class="dim" id="avstate"></span></h2>
  <div id="avstatus" class="dim" style="margin-bottom:10px">no /face-avatar page open</div>
  <div class="btns"><span class="lbl">Page</span>
    <button id="av-stop" onclick="ctl('avatar-page-stop')">&#9209; Stop</button>
    <button id="av-resume" onclick="ctl('avatar-page-resume')">&#9654; Resume</button></div>
  <div class="btns"><span class="lbl">Voice</span>
    <button id="av-robot" onclick="ctl('avatar-page-voice-robot')">robot (avatar mouths along)</button>
    <button id="av-avatar" onclick="ctl('avatar-page-voice-avatar')">avatar only</button>
    <button id="av-sync" onclick="ctl('avatar-page-voice-sync')">both synced</button></div>
  <a class="dim" href="/face?key=" id="avlink" target="_blank">open page &#8599;</a></div>
<div class="sec">Connectivity</div>
<div class="card c6"><h2>WiFi <span class="dim" id="wifinow"></span></h2>
  <div id="wifi-list" class="dim" style="margin-bottom:10px">tap Scan to list networks (tap a network to switch)</div>
  <div class="btns"><button onclick="wifiScan()">&#128246; Scan networks</button><span id="netmsg" class="dim"></span></div>
  <div class="btns" style="margin-top:4px">
    <input id="wm-ssid" placeholder="network name" style="flex:1;min-width:140px">
    <input id="wm-pw" type="password" placeholder="password" style="flex:1;min-width:140px">
    <button onclick="wifiManual()">Join</button></div>
  <div class="dim" style="font-size:13px">Manual entry works in setup-hotspot mode and for hidden networks.
    &#9888; Switching networks drops this page — rejoin the same WiFi on your phone.</div>
</div>
<div class="card c6"><h2>Bluetooth <span class="dim" id="btnow"></span></h2>
  <div id="bt-list" class="dim" style="margin-bottom:10px">loading&hellip;</div>
  <div class="btns"><button onclick="btScan(false)">&#8635; Refresh</button>
    <button onclick="btScan(true)">&#128270; Scan (~10 s)</button><span id="btmsg" class="dim"></span></div>
  <div class="btns"><span class="lbl">Speaker</span>
    <button onclick="act('audio-internal')">&#129302; Internal</button>
    <button onclick="act('audio-sony')">&#128266; Sony</button>
    <button onclick="act('audio-marshall')">&#128266; Marshall</button></div>
  <div class="dim" style="font-size:13px">Tap a device to connect / disconnect / pair. The speaker watchdog re-routes to the Sony within 15 s when it is connected.</div>
</div>
<div class="sec">Conversation</div>
<div class="card"><h2>Current turn</h2><div id="turn" class="dim">no turn yet</div>
  <h2 style="margin-top:12px">Stage latency</h2><div id="lat" class="dim">&mdash;</div></div>
<div class="card c8"><h2>Grounding documents <span class="dim">(composer context, last turn)</span></h2>
  <div id="docs" class="dim" style="max-height:280px;overflow:auto">no turn yet</div></div>
<div class="card c8"><h2>Conversation (raw vs corrected)</h2>
  <table id="conv"><tr><th>who</th><th>text</th></tr></table></div>
<div class="card"><h2>NER corrections (P0)</h2>
  <table id="ner"><tr><th>heard</th><th>&rarr; canonical</th><th>class</th><th>conf</th></tr></table></div>
<div class="card c12"><h2>Recent turns (tracking)</h2>
  <div style="overflow-x:auto"><table id="hist"><tr><th>time</th><th>question</th><th>theme</th>
  <th>docs</th><th>tokens</th><th>cost</th><th>STT s</th><th>compose s</th><th>speech</th><th>wpm</th><th>flags</th></tr></table></div></div>
<div class="sec">Providers</div>
<div class="card c12"><h2>Usage &amp; errors <span class="dim" id="usagets"></span></h2>
  <div id="prov" class="dim" style="margin-bottom:10px">checking providers&hellip;</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px">
    <div><h3>Claude (Anthropic)</h3><div id="u-claude" class="dim">loading&hellip;</div></div>
    <div><h3>ElevenLabs (cloned voice)</h3><div id="u-eleven" class="dim">loading&hellip;</div></div>
    <div><h3>OpenAI (speech-to-text)</h3><div id="u-openai" class="dim">loading&hellip;</div></div>
  </div>
  <h3 style="margin:14px 0 6px">Recent errors &amp; operator actions <span class="dim">(this boot, newest last)</span></h3>
  <pre id="errs" class="mono">loading&hellip;</pre>
</div>
<div class="sec">Admin</div>
<div class="card c6"><h2>Logs
  <select id="logunit" onchange="loadLogs()">
    <option value="supervaise">supervaise</option>
    <option value="wifi-fallback">wifi-fallback</option>
    <option value="speaker-watchdog">speaker-watchdog</option>
  </select>
  <button class="sm" onclick="loadLogs()">refresh</button></h2>
  <pre id="logs" class="mono"></pre></div>
<div class="card c6"><h2>Entity dictionary overlay <span class="dim">(saves live, no restart)</span></h2>
  <textarea id="ov" spellcheck="false"></textarea>
  <div class="btns"><button onclick="saveOv()">&#128190; Save overlay</button><span id="ovmsg" class="dim"></span></div></div>
</div><script>
const KEY=new URLSearchParams(location.search).get('key')||localStorage.getItem('cjkey')||'';
if(KEY)localStorage.setItem('cjkey',KEY);
const esc=s=>{const d=document.createElement('div');d.innerText=s==null?'':s;return d.innerHTML};
const $=id=>document.getElementById(id);
function note(t){$('msg').innerText=t;if($('msg2'))$('msg2').innerText=t;if($('msg3'))$('msg3').innerText=t;}
async function ctl(a){note(a+'\\u2026');const r=await(await fetch('/api/ctl',{method:'POST',
  body:JSON.stringify({action:a,key:KEY})})).json();
  note(r.output||'');}
async function loadTuning(){try{const r=await(await fetch('/api/tuning?key='+KEY)).json();const t=r.tuning||{};
  for(const k of ['wake','stop','listen','pace','length']){const el=$('tn-'+k);if(el&&t[k]!=null&&document.activeElement!==el)el.value=t[k];}
  if(t.error)$('tn-hint').innerText=t.error;}catch(e){}}
async function applyTuning(){const b={key:KEY};for(const k of ['wake','stop','listen','pace','length'])b[k]=$('tn-'+k).value;
  if(!confirm('Apply tuning and restart the voice app? CJ goes quiet for about 25 s.'))return;
  note('applying\\u2026');const r=await(await fetch('/api/tuning',{method:'POST',body:JSON.stringify(b)})).json();
  note((r.ok?'':'FAILED: ')+(r.output||''));setTimeout(loadTuning,3000);}
loadTuning();
async function sayText(){const t=$('say-text').value.trim();if(!t)return;
  const b=$('say-btn');b.disabled=true;$('msg').innerText='speaking\\u2026';
  try{const r=await(await fetch('/api/say-text',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text:t,key:KEY})})).json();
    $('msg').innerText=r.ok?'spoken: '+t.slice(0,80):'FAILED: '+(r.output||'');
    if(r.ok)$('say-text').value='';}
  catch(e){$('msg').innerText='FAILED: '+e.message}
  b.disabled=false;}
$('say-text').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();sayText();}});
async function act(a){note(a+'\\u2026');
  let r=await(await fetch('/api/action',{method:'POST',
    body:JSON.stringify({action:a})})).json();
  if(r.queued){note(a+' sent \\u2014 running\\u2026');
    for(let i=0;i<400&&r.state!=='done';i++){await new Promise(res=>setTimeout(res,300));
      r=await(await fetch('/api/action/status?id='+r.id)).json();}}
  note(r.ok?a+' ok':'FAILED: '+(r.output||''));}
async function rebootPi(){
  if(!confirm('Reboot the Pi? The robot goes quiet for about a minute.'))return;
  const say=t=>{$('msg').innerText=t;};
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  // fetch with a hard timeout: a SYN to a dead host can hang 1-2 min otherwise
  const ping=async()=>{const c=new AbortController();const t=setTimeout(()=>c.abort(),4000);
    try{const r=await fetch('/api/state?_='+Date.now(),{cache:'no-store',signal:c.signal});
      if(!r.ok)return null;return await r.json();}catch(e){return null;}finally{clearTimeout(t);}};
  const before=await ping();const oldBoot=before&&before.boot_id||null;
  // stop every poller/camera timer on this page so they don't pile up hung
  // requests against the dead host (browser caps 6 connections per host)
  const top=setInterval(()=>{},100000);for(let i=1;i<=top;i++)clearInterval(i);
  window.__rebooting=true;
  say('rebooting... this page reconnects on its own');
  try{const c=new AbortController();setTimeout(()=>c.abort(),8000);
    const r=await fetch('/api/action',{method:'POST',body:JSON.stringify({action:'reboot'}),signal:c.signal});
    const j=await r.json();if(!j.ok){say('reboot FAILED: '+(j.output||''));return;}
  }catch(e){}   // server usually dies before answering - that is fine
  const t0=Date.now();const el=()=>Math.round((Date.now()-t0)/1000)+'s';
  // phase 1: wait for the box to actually go away (a reload now would just
  // land on a dying server).  Give up waiting after 3 min and go to phase 2.
  let down=false;
  while(Date.now()-t0<180000){const s=await ping();
    if(!s||(oldBoot&&s.boot_id&&s.boot_id!==oldBoot)){down=true;break;}
    say('shutting down... '+el());await sleep(2000);}
  if(!down)say('server still answering after 3 min - waiting for it to come back anyway');
  // phase 2: wait for a *fresh* boot (new boot_id, or uptime < 5 min when the
  // old id is unknown), then hard-navigate.  Up to 10 min.
  while(Date.now()-t0<600000){const s=await ping();
    if(s&&((oldBoot&&s.boot_id&&s.boot_id!==oldBoot)||(!oldBoot&&s.uptime_s!=null&&s.uptime_s<300))){
      say('back up - reloading');await sleep(1500);
      location.replace(location.pathname+location.search);return;}
    say(s?'still shutting down... '+el():'waiting for the Pi to come back... '+el());
    await sleep(3000);}
  say('still offline after 10 min - reload manually');}
async function loadOv(){const r=await(await fetch('/api/entities?key='+KEY)).json();
  if(r.ok)$('ov').value=r.content;}
async function saveOv(){const r=await(await fetch('/api/entities?key='+KEY,{method:'POST',
  body:JSON.stringify({content:$('ov').value,key:KEY})})).json();
  $('ovmsg').innerText=r.output;}
function fmtTok(n){n=n||0;return n>=1e6?(n/1e6).toFixed(2)+'M':n>=1e3?(n/1e3).toFixed(1)+'k':String(Math.round(n))}
function claudeRow(name,s){if(!s)return '';const t=(s.input||0)+(s.cache_write||0)+(s.cache_read||0);
  return '<b>'+name+'</b>: '+s.calls+' calls · in '+fmtTok(t)+' (cached '+fmtTok(s.cache_read)+') · out '+fmtTok(s.output)+' · $'+(s.cost_usd||0).toFixed(3)+'<br>'}
async function loadUsage(){try{
  const u=await(await fetch('/api/usage')).json();const L=u.usage.lifetime||{},S=u.usage.session||{};
  const cost=o=>Object.values(o.anthropic||{}).reduce((a,s)=>a+(s.cost_usd||0),0);
  let h='<span class="dim">session</span><br>';for(const k of ['router','inference'])h+=claudeRow(k==='router'?'Haiku router/gate/audit':'Sonnet composer',(S.anthropic||{})[k]);
  h+='<b>session total $'+cost(S).toFixed(3)+'</b> · lifetime $'+cost(L).toFixed(2)+' ('+fmtTok(Object.values(L.anthropic||{}).reduce((a,s)=>a+(s.input||0)+(s.cache_write||0)+(s.cache_read||0)+(s.output||0),0))+' tok)';
  $('u-claude').innerHTML=h;
  const e=u.eleven||{},el=L.elevenlabs||{},es=S.elevenlabs||{};
  let g='';
  if(e.error){g+='<span class="raw">quota: '+esc(e.error)+'</span><br>'}else{const pct=e.character_limit?Math.round(100*e.character_count/e.character_limit):0;
    g+='<b>'+fmtTok(e.character_count)+' / '+fmtTok(e.character_limit)+' chars</b> used this cycle ('+pct+'%) · '+esc(e.tier)+' · resets '+(e.next_character_count_reset_unix?new Date(e.next_character_count_reset_unix*1000).toLocaleDateString():'?')+bar(e.character_count||0,e.character_limit||1)}
  g+='<span class="dim">session</span>: '+(es.requests||0)+' synth · '+fmtTok(es.chars)+' chars billed · '+(es.cache_hits||0)+' from cache<br><span class="dim">lifetime</span>: '+fmtTok(el.chars)+' billed · '+fmtTok(el.cache_chars)+' cached';
  $('u-eleven').innerHTML=g;
  const os_=S.openai||{},ol=L.openai||{};
  $('u-openai').innerHTML='<span class="dim">session</span>: '+(os_.stt_calls||0)+' transcriptions · '+Math.round(os_.stt_seconds||0)+' s audio<br><span class="dim">lifetime</span>: '+(ol.stt_calls||0)+' · '+Math.round((ol.stt_seconds||0)/60)+' min';
  $('usagets').innerText='updated '+new Date(u.ts*1000).toLocaleTimeString();
}catch(err){for(const id of ['u-claude','u-eleven','u-openai'])$(id).innerText='usage fetch failed';}}
async function loadErrors(){try{const r=await(await fetch('/api/errors')).json();
  const rows=r.rows||[];$('errs').textContent=rows.length?rows.map(x=>x.t+'  '+x.unit.padEnd(5)+' '+x.msg).join('\\n'):'no errors this boot';
  $('errs').scrollTop=$('errs').scrollHeight;}catch(e){$('errs').textContent='error fetch failed';}}
function provChip(label,p){if(!p)return '';const api=p.ok?chip(label+' API',true,'OK '+(p.s!=null?p.s+'s':'')):chip(label+' API',false,p.error||('HTTP '+p.code));
  const pg=p.page||{},ind=pg.indicator||'unknown',good=ind==='none';
  const pageTxt=ind==='unknown'?'status page n/a':(pg.description||ind);
  return '<span style="display:inline-block;margin:0 14px 6px 0">'+api+
    '<span class="'+(good?'fix':(ind==='unknown'?'dim':'raw'))+'" style="font-size:12px">'+esc(pageTxt)+'</span></span>'}
async function loadProviders(){try{const p=await(await fetch('/api/providers')).json();
  $('prov').innerHTML=provChip('Claude',p.claude)+provChip('ElevenLabs',p.elevenlabs)+provChip('OpenAI',p.openai)+
    '<span class="dim" style="font-size:11px">checked '+new Date(p.ts*1000).toLocaleTimeString()+'</span>';
}catch(e){$('prov').innerText='provider check failed';}}
setInterval(loadProviders,60000);loadProviders();
setInterval(loadUsage,15000);setInterval(loadErrors,10000);loadUsage();loadErrors();
async function loadLogs(){try{
  const t=await(await fetch('/api/logs?unit='+$('logunit').value+'&lines=80')).text();
  $('logs').textContent=t;
  $('logs').scrollTop=$('logs').scrollHeight;}catch(e){$('logs').textContent='log fetch failed';}}
function bar(v,max){return '<div class="bar"><i style="width:'+Math.min(100,100*v/max)+'%"></i></div>'}
function chip(k,ok,txt){return '<span class="chip '+(ok?'ok':'bad')+'">'+k+' '+(txt||(ok?'&#10003;':'&#10007;'))+'</span>'}
async function poll(){try{
  const s=await(await fetch('/api/state')).json();
  try{  // quick-status strip (2026-08-29): mic · speaker · services · last turn timings
    const h=s.health||{},sp=(s.metas||[]).filter(m=>m.phase==='spoken').slice(-1)[0],cp=(s.metas||[]).filter(m=>m.phase==='composed').slice(-1)[0];
    const f=(v,u='s')=>v==null?'-':(+v).toFixed(1)+u;
    const item=(k,v,cls)=>`<span><span class="k">${k}</span><b class="${cls||''}">${v}</b></span>`;
    $('strip').innerHTML=item('mic',s.muted?'MUTED':'live',s.muted?'bad':'ok')
      +item('speaker',esc(s.audio_route||'?'),/internal/i.test(s.audio_route||'')?'ok':'warn')
      +item('app',h.supervaise?'up':'DOWN',h.supervaise?'ok':'bad')
      +item('internet',h.internet?'ok':'OFFLINE',h.internet?'ok':'bad')
      +item('camera',s.camera_off?'OFF':(h.camera?'ok':'idle'),s.camera_off?'bad':(h.camera?'ok':'warn'))
      +item('event mode',s.event_mode?'ON':'off',s.event_mode?'warn':'')
      +(cp?item('last turn',esc((cp.topic||'').replace('canned:','')+'  stt '+f(cp.stt_s)+' · compose '+f(cp.compose_s)+' · first audio '+f(cp.first_audio_s!=null?cp.first_audio_s:(sp||{}).synth_s)+(sp&&sp.wpm?' · '+sp.wpm+' wpm':'')),''):'')
      +(s.tempo_avg?item('tempo',(+s.tempo_avg).toFixed(1)+' ch/s',''):'');
  }catch(e){}
  if(window.__uiRev==null)window.__uiRev=s.ui_rev||null;else if(s.ui_rev&&s.ui_rev!==window.__uiRev){location.reload();return;}
  $('health').innerHTML=Object.entries(s.health||{}).map(([k,v])=>chip(k,v)).join('')
    +chip('mic',!s.muted,s.muted?'MUTED':'live')
    +chip('event mode',true,s.event_mode?'ON':'off');
  $('btn-mute').style.display=s.muted?'none':'';
  $('btn-unmute').style.display=s.muted?'':'none';
  window.__camOff=!!s.camera_off;
  $('btn-cam-off').style.display=s.camera_off?'none':'';
  $('btn-cam-on').style.display=s.camera_off?'':'none';
  $('cam').style.display=s.camera_off?'none':'';
  $('cam-off-box').style.display=s.camera_off?'':'none';
  $('camstate').innerHTML=chip('camera',!s.camera_off,s.camera_off?'OFF':'on');
  $('cam-hint').innerText=s.camera_off?'OFF \u2014 /audience shows its idle plaque instead of the portrait':'on \u2014 always running until Camera off';
  $('btn-ev-on').style.display=s.event_mode?'none':'';
  $('btn-ev-off').style.display=s.event_mode?'':'none';
  $('ev-hint').innerText=s.event_mode?'ON \u2014 spoken event questions (and paraphrases) get the scripted answers':'off \u2014 normal conversation; the /event buttons still work';
  const av=s.avatar_page||{},avAge=av.ts?(s.ts-av.ts):1e9,avOn=avAge<10;
  $('avstate').innerHTML=avOn?chip('page',true,av.stopped?'stopped':av.ready?'session live (credits ticking)':'parked — no credits')
    :chip('page',false,'not open');
  $('avstatus').innerText=avOn?(av.status||'')+(av.lag!=null?'  ·  lag '+(+av.lag).toFixed(2)+'s':''):
    'no /face-avatar page open (open it on the laptop: /face?key=…)';
  for(const m of ['robot','avatar','sync'])$('av-'+m).style.borderColor=(avOn&&av.mode===m)?'var(--gold)':'';
  $('av-stop').style.display=avOn&&av.stopped?'none':'';
  $('av-resume').style.display=avOn&&!av.stopped?'none':'';
  $('avlink').href='/face?key='+KEY;
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
        +(sp.wpm?'Speech '+sp.wpm+' wpm <span class="dim">('+sp.words+' words / '+sp.audio_s+'s audio)</span>'+bar(sp.wpm,200):'')
        +(sp.interrupted?'<span class="raw">interrupted</span>':'');
    $('lat').innerHTML=lat;}
  const byQ={};
  (s.metas||[]).forEach(x=>{const k=x.question||'';byQ[k]=Object.assign(byQ[k]||{},x);});
  $('hist').innerHTML='<tr><th>time</th><th>question</th><th>theme</th><th>docs</th><th>tokens</th>'+
    '<th>cost</th><th>STT s</th><th>compose s</th><th>speech</th><th>wpm</th><th>flags</th></tr>'+
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
        '</td><td>'+esc(sp2)+'</td><td title="'+(x.words?x.words+' words / '+x.audio_s+'s':'')+'">'+(x.wpm||'')+
        '</td><td'+(x.interrupted?' class="raw"':'')+'>'+esc(fl)+'</td></tr>';}).join('');
  $('conv').innerHTML='<tr><th>who</th><th>text</th></tr>'+
    (s.turns||[]).slice(-14).reverse().map(t=>'<tr><td>'+esc(t.role)+'</td><td>'+esc(t.text)+'</td></tr>').join('');
  $('ner').innerHTML='<tr><th>heard</th><th>&rarr; canonical</th><th>class</th><th>conf</th></tr>'+
    (s.corrections||[]).slice(-14).reverse().map(c=>'<tr><td class="raw">'+esc(c.surface)+
    '</td><td class="fix">'+esc(c.canonical)+'</td><td>'+esc(c.class)+'</td><td>'+esc(c.confidence)+'</td></tr>').join('');
  const evRows=(evs)=>'<tr><th>time</th><th>score</th></tr>'+
    (evs||[]).slice(-8).reverse().map(e=>'<tr><td>'+
    new Date(1000*(e.ts||0)).toLocaleTimeString()+'</td><td>'+esc((e.score||0).toFixed?e.score.toFixed(3):e.score)+'</td></tr>').join('');
  $('wake').innerHTML=evRows(s.wake_events);
  $('stopt').innerHTML=evRows(s.stop_events);
}catch(e){}}
// Wake meter + Stop meter (2026-08-26): same drawing, separate feeds —
// /api/wake scores while idle-listening, /api/stop scores while an answer
// plays (barge-in listener). Exactly one of them is live at any moment.
let spark=[],stopspark=[];
function drawMeter(w,ids,buf,color,liveLabel,idleLabel,defThr){
  const sc=w.score!=null?w.score:0,th=w.threshold!=null?w.threshold:defThr;
  $(ids.now).innerText=(w.live?liveLabel+' ':idleLabel+' ')+sc.toFixed(3)+' / thr '+th;
  $(ids.bar).style.width=Math.min(100,100*sc/Math.max(th*2,0.01))+'%';
  $(ids.bar).style.background=sc>=th?'var(--bad)':color;
  buf.push(w.live?sc:0);if(buf.length>200)buf.shift();
  const c=$(ids.spark),g=c.getContext('2d');
  if(c.width!==c.clientWidth){c.width=c.clientWidth;c.height=64;}
  g.clearRect(0,0,c.width,c.height);
  const ymax=Math.max(th*2,0.1);
  g.strokeStyle='#f8514966';g.beginPath();
  g.moveTo(0,64-64*th/ymax);g.lineTo(c.width,64-64*th/ymax);g.stroke();
  g.strokeStyle=color;g.beginPath();
  buf.forEach((v,i)=>{const x=i*c.width/200,y=64-Math.min(64,64*v/ymax);
    i?g.lineTo(x,y):g.moveTo(x,y);});
  g.stroke();
}
async function wakeTick(){try{
  const [w,st]=await Promise.all([fetch('/api/wake').then(r=>r.json()),
                                  fetch('/api/stop').then(r=>r.json())]);
  drawMeter(w,{now:'wakenow',bar:'wakebar',spark:'spark'},spark,'#c9a227',
            'live',st.live?'answering':'OFFLINE',0.07);
  drawMeter(st,{now:'stopnow',bar:'stopbar',spark:'stopspark'},stopspark,'#58a6ff',
            'armed',w.live?'idle':'OFFLINE',0.02);
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
  try{netFromStatus(st)}catch(e){}
  const env=((st.wake||{}).env)||{};
  $('flags').innerHTML=[['stream','CJ_STREAM_SPEECH'],['dyn-filler','CJ_DYNAMIC_FILLER'],
    ['dyn-tokens','CJ_DYNAMIC_TOKENS_ENABLED'],['postproc','CJ_POSTPROC_ENABLED'],
    ['stop-word','CJ_STOP_WORD_ENABLED']].map(([n,k])=>chip(n,env[k]==='1')).join('');
}catch(e){}}
function camTick(){if(window.__camOff)return;const p=new Image();p.onload=()=>{$('cam').src=p.src};
  p.src='/api/camera.jpg?t='+Date.now();}
// keep the wake/stop meter pair no taller than the Controls card (user: "just fitting the controls")
function fitMeters(){const c=$('controls-card'),st=document.querySelector('.stack');if(!c||!st)return;
  st.style.maxHeight=window.innerWidth<=760?'':c.offsetHeight+'px';}
try{new ResizeObserver(fitMeters).observe($('controls-card'));}catch(e){}
window.addEventListener('resize',fitMeters);fitMeters();
setInterval(poll,500);poll();
setInterval(wakeTick,300);wakeTick();
setInterval(sysTick,5000);sysTick();
setInterval(camTick,200);camTick();loadOv();loadLogs();
// ── Connectivity (WiFi / Bluetooth) — same endpoints as the ops page ──
let _nets=[],_bts=[],_watchdog=false;
function netFromStatus(st){const wf=st.wifi||{};
  $('wifinow').innerHTML=wf.essid?chip(esc(wf.essid),true,esc(wf.signal_dbm||'?')+' dBm · '+esc(wf.ip||'?')):chip('no wifi',false,'');
  _watchdog=((st.services||{})['speaker-watchdog']||{}).active==='active';
  const sp=(st.audio||{}).speakers||{},route=(st.audio||{}).route||'?';
  $('btnow').innerHTML=chip('route',true,esc(route))+Object.entries(sp).map(([n,c])=>chip(n,c,c?'connected':'off')).join('');}
function netRow(left,right,onclick){return '<div style="display:flex;justify-content:space-between;gap:10px;padding:8px 6px;border-bottom:1px solid var(--line);cursor:pointer" onclick="'+onclick+'"><span>'+left+'</span><span class="dim">'+right+'</span></div>'}
async function wifiScan(){$('wifi-list').textContent='scanning…';
  try{const w=await(await fetch('/api/wifi?rescan=1')).json();_nets=w.networks||[];
    if(w.hotspot&&!_nets.length){$('wifi-list').textContent='setup hotspot active — scanning unavailable; type the network below';return}
    if(!_nets.length){$('wifi-list').textContent='no networks found';return}
    $('wifi-list').innerHTML=_nets.map((n,i)=>{const bars=n.signal>66?'▂▄▆':n.signal>33?'▂▄':'▂';
      const tag=n.in_use?' — connected':(n.saved?' (saved)':'');const lock=n.security==='open'?'':' 🔒';
      return netRow((n.in_use?'✅ ':'')+esc(n.ssid)+lock+'<span class="dim">'+tag+'</span>',bars+' '+n.signal+'%','wifiJoinIdx('+i+')')}).join('');
  }catch(e){$('wifi-list').textContent='scan failed: '+e.message}}
async function wifiSend(ssid,password){
  if(!confirm('Switch the robot to "'+ssid+'"? This page will drop until your phone is on the same network.'))return;
  $('netmsg').textContent='switching to '+ssid+'…';
  try{const r=await(await fetch('/api/wifi/connect',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ssid,password})})).json();
    $('netmsg').textContent=r.ok?(r.output||('now on '+ssid)):'FAILED — '+(r.output||'');
  }catch(e){$('netmsg').textContent='dashboard dropped — rejoin '+ssid+' on your phone and reload'}}
function wifiJoinIdx(i){const n=_nets[i];if(!n)return;let pw=null;
  if(!(n.saved||n.security==='open')){pw=prompt('Password for "'+n.ssid+'" (leave empty if open):');if(pw===null)return}
  wifiSend(n.ssid,pw)}
function wifiManual(){const ssid=$('wm-ssid').value.trim(),pw=$('wm-pw').value;
  if(!ssid){$('netmsg').textContent='enter a network name';return}wifiSend(ssid,pw||null)}
async function btScan(rescan){$('bt-list').textContent=rescan?'scanning (~10 s)…':'loading…';
  try{const b=await(await fetch('/api/bt'+(rescan?'?scan=1':''))).json();_bts=b.devices||[];
    if(!_bts.length){$('bt-list').textContent='no devices known — tap Scan';return}
    $('bt-list').innerHTML=_bts.map((d,i)=>{const state=d.connected?'<span style="color:var(--ok)">connected</span>':d.paired?'paired':'not paired';
      return netRow((d.connected?'✅ ':'')+(d.audio?'🔊 ':'')+esc(d.name),state,'btTapIdx('+i+')')}).join('');
  }catch(e){$('bt-list').textContent='bluetooth list failed: '+e.message}}
async function btTapIdx(i){const d=_bts[i];if(!d)return;
  const action=d.connected?'disconnect':d.paired?'connect':'pair';
  const warn=(action==='disconnect'&&_watchdog)?' ⚠ The watchdog is running — Sony reconnects within 15 s.':'';
  if(!confirm(action.charAt(0).toUpperCase()+action.slice(1)+' "'+d.name+'"?'+warn))return;
  $('btmsg').textContent=action+'ing '+d.name+'…';
  try{const r=await(await fetch('/api/bt/action',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({mac:d.mac,action})})).json();
    $('btmsg').textContent=d.name+': '+(r.ok?action+' ok ✓':'FAILED — '+(r.output||''));
  }catch(e){$('btmsg').textContent=action+' failed: '+e.message}
  setTimeout(()=>btScan(false),1500)}
btScan(false);
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
