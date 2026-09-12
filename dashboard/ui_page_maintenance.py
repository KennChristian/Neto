"""/maintain — operator maintenance page (MAINTAIN_PAGE + GATE_PAGE).

Split out of supervaise_ui.py on 2026-08-29 (shared names star-copied from
ui_common so page code reads exactly as before; ui_routes is the facade).
"""
import ui_common as _c
globals().update({k: v for k, v in vars(_c).items() if not k.startswith("__")})


MAINTAIN_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CJAP — Maintenance</title><style>
/* ── 2026-09-12 visual refresh: design tokens, sidebar/bottom nav, calmer cards ── */
:root{--bg:#0b0f14;--bg2:#0f141b;--panel:#131a23;--panel2:#18212c;--ink:#e8edf3;--dim:#8a95a3;--faint:#5c6773;
  --gold:#d4a835;--gold2:#f0c75e;--ok:#3fb950;--bad:#f0554d;--warn:#e3b341;--info:#58a6ff;
  --line:rgba(255,255,255,.07);--line2:rgba(255,255,255,.13);--btn:#1b2330;--btn2:#243040;
  --r:14px;--hdr:64px;--nav:220px;--shadow:0 8px 24px rgba(0,0,0,.28)}
*{margin:0;padding:0;box-sizing:border-box}
html{color-scheme:dark;scroll-behavior:smooth}
body{background:radial-gradient(1100px 500px at 15% -10%,rgba(212,168,53,.09),transparent 60%),var(--bg);color:var(--ink);
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;font-size:14.5px;line-height:1.5;min-height:100vh;-webkit-font-smoothing:antialiased}
a{color:var(--gold)}
[hidden]{display:none!important}
::selection{background:rgba(212,168,53,.35)}
/* header */
.hdr{position:sticky;top:0;z-index:20;height:var(--hdr);background:rgba(11,15,20,.86);backdrop-filter:blur(12px);
  border-bottom:1px solid var(--line);padding:0 22px;display:flex;align-items:center;gap:18px}
h1{font-size:18px;font-weight:700;letter-spacing:.01em;line-height:1.15;white-space:nowrap}h1 b{color:var(--gold)}
h1 small{display:block;font-size:12px;font-weight:500;color:var(--dim);margin-top:2px}h1 small a{text-decoration:none}h1 small a:hover{text-decoration:underline}
.statuslinks{margin-left:auto;display:flex;gap:8px}
.statuslinks a{display:inline-flex;align-items:center;gap:8px;padding:8px 13px;border-radius:999px;font-size:13px;font-weight:600;
  background:var(--btn);border:1px solid var(--line2);color:var(--ink);text-decoration:none;white-space:nowrap}
.statuslinks a:hover{border-color:var(--gold);color:var(--gold)}
.statuslinks a i{width:8px;height:8px;border-radius:50%;background:var(--ok);box-shadow:0 0 8px var(--ok);display:inline-block}
/* nav + page frame: sidebar on desktop, pill bar on tablets, bottom bar on phones */
.page{display:grid;grid-template-columns:var(--nav) minmax(0,1fr);gap:0 22px;padding:0 22px 32px}
.tabs{grid-column:1;position:sticky;top:calc(var(--hdr) + 16px);align-self:start;display:flex;flex-direction:column;gap:4px;padding:16px 0}
.tabs button{display:flex;align-items:center;gap:11px;width:100%;text-align:left;background:transparent;border:1px solid transparent;
  color:var(--dim);font-size:14px;font-weight:600;padding:10px 12px;height:auto;min-height:0;border-radius:10px;box-shadow:none}
.tabs button svg{width:18px;height:18px;flex:none;stroke:currentColor;fill:none;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}
.tabs button .short{display:none}
.tabs button:hover{color:var(--ink);background:var(--btn);border-color:transparent}
.tabs button.on{color:var(--gold2);background:rgba(212,168,53,.12);border-color:rgba(212,168,53,.35)}
.main{grid-column:2;min-width:0;padding-top:16px}
/* robot mode banner */
.mode{display:flex;flex-wrap:wrap;align-items:center;gap:8px 16px;padding:14px 18px;border:1px solid var(--line);border-radius:var(--r);
  background:linear-gradient(135deg,var(--panel2),var(--panel));box-shadow:var(--shadow);transition:border-color .3s,background .3s}
.mode .dot{width:16px;height:16px;border-radius:50%;background:#6b7280;flex:none;box-shadow:0 0 0 4px rgba(255,255,255,.05);transition:background .3s,box-shadow .3s}
.mode b.lbl{font-size:19px;letter-spacing:.14em;font-weight:800}
.mode .mdet{color:var(--dim);font-size:13.5px;margin-left:4px}
.mode .mage{color:var(--faint);font-size:12.5px;font-variant-numeric:tabular-nums}
.mode.listening{border-color:rgba(63,185,80,.5);background:linear-gradient(135deg,rgba(63,185,80,.14),var(--panel))}.mode.listening .dot{background:var(--ok);box-shadow:0 0 14px 2px rgba(63,185,80,.55);animation:mpulse 1.2s ease-in-out infinite}
.mode.thinking{border-color:rgba(212,168,53,.5);background:linear-gradient(135deg,rgba(212,168,53,.14),var(--panel))}.mode.thinking .dot{background:var(--gold);box-shadow:0 0 12px 1px rgba(212,168,53,.5);animation:mpulse 1.2s ease-in-out infinite}
.mode.speaking{border-color:rgba(240,85,77,.5);background:linear-gradient(135deg,rgba(240,85,77,.14),var(--panel))}.mode.speaking .dot{background:var(--bad);box-shadow:0 0 14px 2px rgba(240,85,77,.55);animation:mpulse .6s ease-in-out infinite}
.mode.muted .dot,.mode.down .dot{background:var(--bad)}.mode.down{border-color:var(--bad)}.mode.muted{border-color:rgba(240,85,77,.5)}
.msteps{display:flex;gap:6px;flex-wrap:wrap;margin-left:auto}
.msteps span{padding:3px 10px;border-radius:999px;border:1px solid var(--line2);font-size:12px;color:var(--dim);white-space:nowrap;background:rgba(0,0,0,.15)}
.msteps span.active{border-color:var(--gold);color:var(--gold2)}.msteps span.done{border-color:rgba(63,185,80,.6);color:var(--ok)}.msteps span.failed{border-color:var(--bad);color:var(--bad)}
.mtags{flex-basis:100%;display:flex;gap:4px 14px;flex-wrap:wrap;font-size:13px;color:var(--dim)}
.mtags .on{color:var(--ok)}.mtags .warn{color:var(--warn)}.mtags .bad{color:var(--bad)}
@keyframes mpulse{50%{transform:scale(.78);opacity:.65}}
/* quick-status strip: one pill per fact */
.strip{display:flex;flex-wrap:wrap;gap:6px 8px;margin:12px 0 18px;font-size:13px}
.strip>span{display:inline-flex;align-items:center;gap:6px;padding:6px 11px;border-radius:999px;background:var(--panel);border:1px solid var(--line)}
.strip b{font-weight:600}.strip .ok{color:var(--ok)}.strip .bad{color:var(--bad)}.strip .warn{color:var(--warn)}.strip .k{color:var(--dim)}
/* grid + cards */
.grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:16px}
.sec{grid-column:1/-1;font-size:12px;font-weight:700;color:var(--dim);text-transform:uppercase;letter-spacing:.16em;margin-top:14px;padding-bottom:8px;
  border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px}
.sec::before{content:'';width:10px;height:10px;border-radius:3px;background:var(--gold);flex:none}
.sec:first-child{margin-top:0}
.card{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:var(--r);padding:18px;min-width:0;grid-column:span 4;box-shadow:var(--shadow)}
.c6{grid-column:span 6}.c8{grid-column:span 8}.c12{grid-column:1/-1}
.stack{grid-column:span 6;display:flex;flex-direction:row;gap:16px;min-width:0;align-self:start}
.stack .card{flex:1 1 0;min-width:0;min-height:0;grid-column:auto;display:flex;flex-direction:column;overflow:hidden}
.stack .mtbl{flex:1 1 auto;min-height:0;overflow:auto;margin-top:6px}
h2{font-size:12.5px;font-weight:700;color:var(--gold2);text-transform:uppercase;letter-spacing:.13em;margin-bottom:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
h2 .dim,h2 select,h2 button{text-transform:none;letter-spacing:0;font-weight:500;font-size:12.5px}
h3{font-size:14px;font-weight:700;margin:0 0 6px}
.hint{color:var(--dim);font-size:13px;margin:-6px 0 12px}
/* chips */
.chip{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;font-size:12.5px;font-weight:600;margin:0 6px 6px 0;background:var(--btn);border:1px solid var(--line)}
.chip::before{content:'';width:7px;height:7px;border-radius:50%;background:currentColor;opacity:.9;flex:none}
.chip.ok{color:var(--ok)}.chip.bad{color:var(--bad)}
.chip.st-speaking{color:var(--bad)}.chip.st-listening{color:var(--ok)}.chip.st-thinking{color:var(--gold2)}.chip.st-muted{color:var(--bad)}.chip.st-down{color:var(--bad)}.chip.st-idle{color:var(--dim)}
/* buttons */
button{background:var(--btn);border:1px solid var(--line2);color:var(--ink);border-radius:10px;padding:0 15px;height:42px;min-height:42px;
  font-family:inherit;font-size:14px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:6px;white-space:nowrap;
  transition:background .12s,border-color .12s,transform .05s}
button:hover{background:var(--btn2);border-color:rgba(212,168,53,.55)}button:active{transform:translateY(1px)}
button:focus-visible{outline:2px solid var(--gold);outline-offset:2px}
button.sm{height:32px;min-height:32px;padding:0 11px;font-size:13px;font-weight:500;border-radius:8px}
button.primary{background:linear-gradient(180deg,var(--gold2),var(--gold));color:#141008;border-color:transparent}button.primary:hover{filter:brightness(1.06)}
button.danger{background:rgba(240,85,77,.12);border-color:rgba(240,85,77,.45);color:#ffb4ae}button.danger:hover{background:rgba(240,85,77,.22)}
button[disabled]{opacity:.5;cursor:default;transform:none}
.btns{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:10px}
.btns .lbl{color:var(--faint);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;min-width:64px}
/* toggles */
.sw{position:relative;display:inline-flex;align-items:center;gap:10px;cursor:pointer;user-select:none;font-weight:600;font-size:13.5px}
.sw input{position:absolute;opacity:0;width:0;height:0}
.sw i{width:46px;height:26px;border-radius:999px;background:var(--btn2);border:1px solid var(--line2);position:relative;transition:background .15s;flex:none}
.sw i::after{content:'';position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:50%;background:#fff;transition:left .15s}
.sw input:checked+i{background:var(--ok);border-color:var(--ok)}.sw input:checked+i::after{left:23px}
.sw input:focus-visible+i{outline:2px solid var(--gold)}.sw input:disabled+i{opacity:.4}
/* inputs */
input[type=text],input[type=password],input:not([type]),select{background:var(--bg2);color:var(--ink);border:1px solid var(--line2);border-radius:10px;padding:0 12px;height:40px;font-size:14px;font-family:inherit}
input[type=number]{background:var(--bg2);color:var(--ink);border:1px solid var(--line2);border-radius:8px;padding:0 8px;height:32px;font-size:13.5px;font-family:inherit;margin-left:4px}
select{height:32px;padding:0 8px;border-radius:8px;font-size:13px}
input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--gold);outline-offset:1px}
input[type=range]{accent-color:var(--gold)}input[type=file]{color:var(--dim);font-size:13px}
label.dim{display:inline-flex;align-items:center;gap:4px;font-size:13px}
/* tables + text blocks */
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--dim);font-weight:600;font-size:11.5px;text-transform:uppercase;letter-spacing:.08em;position:sticky;top:0;background:var(--panel2)}
tr:hover td{background:rgba(255,255,255,.025)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px}
.bar{height:8px;background:var(--btn);border-radius:4px;overflow:hidden;margin:2px 0 6px}.bar i{display:block;height:100%;background:var(--gold);border-radius:4px}
.microw{margin:4px 0 10px}.microw b{font-weight:600}.microw .mono{margin-left:8px;color:var(--dim)}
.mbar{display:inline-block;width:56px;height:8px;background:var(--btn);border-radius:4px;vertical-align:middle;overflow:hidden;margin-right:10px}.mbar i{display:block;height:100%;background:var(--info)}
textarea{width:100%;height:240px;background:var(--bg2);color:var(--ink);border:1px solid var(--line2);border-radius:10px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;padding:10px;margin-bottom:10px}
pre{max-height:280px;overflow:auto;white-space:pre-wrap;background:var(--bg2);border:1px solid var(--line);border-radius:10px;padding:10px;font-size:12.5px}
.raw{color:var(--bad)}.fix{color:var(--ok)}
#msg,#msg2,#msg3,#msg4,#msg5{color:var(--dim);font-size:13px;display:block;min-height:1.3em}
.saybox{flex-wrap:nowrap}.saybox input{flex:1 1 auto;min-width:0;height:42px}
img#cam{width:100%;border-radius:10px;background:#000;min-height:120px;display:block;border:1px solid var(--line)}
.dim{color:var(--dim)}
details.help{margin:2px 0 10px;font-size:13px;color:var(--dim);line-height:1.45}
details.help summary{cursor:pointer;color:var(--gold2);font-weight:600;font-size:12.5px;list-style:none;user-select:none;display:inline-flex;align-items:center;gap:6px}
details.help summary::-webkit-details-marker{display:none}
details.help summary::before{content:'ⓘ';font-size:14px}
details.help[open] summary{margin-bottom:4px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:10px 18px;align-items:start}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:6px 14px;font-size:14px;align-content:start}
.kv b{color:var(--faint);font-weight:700;text-transform:uppercase;font-size:11px;letter-spacing:.12em;padding-top:3px}
#role-row button{flex:1 1 200px;height:52px;font-size:15px}
/* responsive */
@media(max-width:1200px){.card,.c6,.c8,.stack{grid-column:span 6}.c12{grid-column:1/-1}}
@media(max-width:1099px){
  .page{display:block;padding:0 16px 32px}
  .tabs{position:sticky;top:var(--hdr);z-index:15;flex-direction:row;overflow-x:auto;padding:10px 0;margin:0 -16px;padding-left:16px;padding-right:16px;
    background:rgba(11,15,20,.92);backdrop-filter:blur(12px);border-bottom:1px solid var(--line);scrollbar-width:none}
  .tabs::-webkit-scrollbar{display:none}
  .tabs button{width:auto;padding:8px 13px;border-radius:999px;border-color:var(--line)}
  .main{padding-top:14px}}
@media(max-width:760px){
  :root{--hdr:56px}
  .hdr{padding:0 14px}.statuslinks{display:none}
  .page{padding:0 12px 92px}
  .card,.c6,.c8,.c12,.stack{grid-column:1/-1}.stack{flex-direction:column}.cols{grid-template-columns:1fr}
  .card{padding:15px;border-radius:12px}
  .tabs{position:fixed;top:auto;bottom:0;left:0;right:0;margin:0;padding:6px 4px calc(6px + env(safe-area-inset-bottom));
    border-top:1px solid var(--line2);border-bottom:0;justify-content:space-between;gap:0;overflow:visible;background:rgba(11,15,20,.96)}
  .tabs button{flex:1 1 0;flex-direction:column;gap:3px;font-size:10.5px;padding:6px 2px;border-radius:10px;border-color:transparent;min-width:0}
  .tabs button svg{width:21px;height:21px}
  .tabs button .long{display:none}.tabs button .short{display:inline}
  .mode{padding:12px 14px}.mode b.lbl{font-size:17px}
  .saybox{flex-wrap:wrap}.saybox input{flex-basis:100%}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}html{scroll-behavior:auto}}
</style></head><body>
<div class="hdr">
<h1><b>CJAP</b> Maintenance<small>audience: <a href="/audience" target="_blank">/audience</a> &middot; console: <a href="/console" id="consolelink" target="_blank">/console</a> &middot; ops: <a href="/" target="_blank">/</a></small></h1>
<div class="statuslinks" title="Provider status pages (open in new tab)">
  <a href="https://status.claude.com" target="_blank" rel="noopener"><i></i>Claude status</a>
  <a href="https://status.elevenlabs.io" target="_blank" rel="noopener"><i></i>ElevenLabs status</a>
</div>
</div>
<div class="page">
<nav class="tabs" id="tabs" role="tablist" aria-label="Sections"></nav>
<div class="main">
<div id="mode" class="mode"><span class="dot"></span><b class="lbl" id="mlbl">&hellip;</b><span class="mdet" id="mdet"></span><span class="mage" id="mage"></span>
  <div class="msteps" id="msteps"></div><div class="mtags" id="mtags"></div></div>
<div id="strip" class="strip">loading&hellip;</div>
<div class="grid">

<!-- ═══ LIVE ═══ -->
<div class="sec" data-tab="live">Live &mdash; run the show</div>
<div class="card c6" id="controls-card" data-tab="live"><h2>Controls</h2>
  <p class="hint">The buttons you need during a session. One tap each; the result shows below.</p>
  <div class="btns"><span class="lbl">Speech</span>
    <button id="btn-mute" onclick="ctl('mute')" title="Robot stops listening (wake word + stop word ignored) but keeps speaking">&#127908; Mute mic</button>
    <button id="btn-unmute" onclick="ctl('unmute')" class="danger" style="display:none;background:var(--bad)">&#127908; UNMUTE MIC</button>
    <button onclick="ctl('interrupt')" title="Cut the answer that is playing">&#9209; Interrupt</button>
    <button onclick="ctl('force-listen')" title="Open the mic now without the wake word">&#127908; Force listen</button>
    <button onclick="ctl('replay')" title="Play the last answer again">&#128260; Replay last</button>
    <button class="sm" onclick="ctl('tempo-reset')" title="Forget the session speaking-rate average used to smooth sentence tempo">&#8634; Reset voice tempo</button></div>
  <div class="btns"><span class="lbl">Event</span>
    <button id="btn-ev-on" onclick="ctl('event-on')">&#127915; Event mode ON</button>
    <button id="btn-ev-off" onclick="ctl('event-off')" style="display:none;border-color:var(--gold)">&#127915; Event mode OFF</button>
    <span class="dim" id="ev-hint">scripted event questions answer with the script (paraphrases too)</span></div>
  <div class="btns saybox"><span class="lbl">Say</span>
    <input type="text" id="say-text" maxlength="500" placeholder="Type what CJ should say, then press Enter or Speak" autocomplete="off">
    <button id="say-btn" class="primary" onclick="sayText()">&#128483; Speak</button></div>
  <div class="btns"><span class="lbl">App</span>
    <button onclick="act('restart-app')" title="Restart the voice app (~25 s, mic off meanwhile)">&#8635; Restart app</button>
    <button onclick="act('test-sound')">&#128266; Test sound</button>
    <button onclick="act('tagalog-sample')">&#127908; Tagalog sample</button>
    <button onclick="rebootPi()" class="danger">&#9211; Reboot Pi</button></div>
  <span id="msg"></span>
</div>
<div class="card c6" data-tab="live"><h2>Sound <span class="dim">(which speaker, how loud)</span></h2>
  <p class="hint">Pick where answers play, then set the level. The strip at the top shows the current route.</p>
  <div class="btns"><span class="lbl">Speaker</span>
    <button onclick="act('audio-internal')" title="the robot's own speaker (echo cancellation works here)">&#129302; Internal</button>
    <button onclick="act('audio-c41')" title="C41 Bluetooth speaker (66:EA:C5:C3:E5:6B)">&#128264; C41</button>
    <button onclick="act('audio-sony')">&#128264; Sony</button>
    <button onclick="act('audio-marshall')">&#128264; Marshall</button>
    <button onclick="act('audio-dac')" title="USB DAC plugged into the robot (any USB audio device that is not the Reachy Mini card; today a Synaptics JM6PRO_2). The XMOS gets an AEC reference copy so the robot still cancels its own voice.">&#127911; USB DAC</button>
    <button onclick="act('audio-laptop')" title="the laptop as a Bluetooth speaker (LAPTOP-BANC5VFE; its Bluetooth must be on)">&#128187; Laptop</button>
    <button onclick="act('audio-both')" title="every answer on the Bluetooth speaker AND the laptop at once">&#128266;+&#128187; Speaker + laptop</button></div>
  <div class="btns" id="vol-row"><span class="lbl">Volume</span>
    <button class="sm" onclick="setVol(0)" title="silence (mute the output, keep listening)">&#128263; 0</button>
    <button class="sm" onclick="setVol(Math.max(0,+$('vol').value-10))">&minus;</button>
    <input type="range" id="vol" min="0" max="100" step="5" value="100" style="width:180px;vertical-align:middle"
      oninput="$('volv').innerText=this.value+'%'" onchange="setVol(this.value)">
    <b id="volv" style="min-width:42px;display:inline-block">&hellip;</b>
    <button class="sm" onclick="setVol(Math.min(100,+$('vol').value+10))">+</button>
    <button class="sm" onclick="setVol(40)">40</button>
    <button class="sm" onclick="setVol(70)">70</button>
    <button class="sm" onclick="setVol(100)">100</button>
    <span class="dim" id="vol-hint"></span></div>
  <div class="btns"><span class="lbl">Bluetooth</span>
    <button class="sm" onclick="ctl('bt-connect-sony')">&#128268; Reconnect Sony</button>
    <button class="sm" onclick="ctl('bt-connect-marshall')">&#128268; Reconnect Marshall</button>
    <button class="sm" onclick="ctl('bt-pulse')" title="send a short inaudible pulse so a sleepy speaker wakes up">&#12336; Pulse speaker</button>
    <button class="sm" onclick="act('stop-watchdog')">Watchdog off</button>
    <button class="sm" onclick="act('start-watchdog')">Watchdog on</button></div>
  <details class="help"><summary>How the speaker choice sticks</summary>
    The watchdog puts audio back on a connected Bluetooth speaker within 15 s &mdash; switch it off first to stay on Internal; a working Laptop / Speaker + laptop / USB DAC choice is left alone.
    Volume applies to the internal speaker and to any connected Bluetooth speaker (it scales the stream below the speaker&rsquo;s own button level, so 100 = the speaker&rsquo;s setting) and is remembered per route.</details>
  <span id="msg4" class="dim"></span>
</div>
<div class="card c6" data-tab="live"><h2>Camera <span class="dim" id="camstate"></span></h2>
  <p class="hint">What the audience page shows. Fixed focus distances hold steady on stage.</p>
  <div class="btns"><span class="lbl">Camera</span>
    <button id="btn-cam-off" onclick="ctl('camera-off')">&#9210; Camera off</button>
    <button id="btn-cam-on" onclick="ctl('camera-on')">&#127909; Camera on</button>
    <button onclick="ctl('camera-refocus')" title="Autofocus again: the capture restarts (~2 s) and continuous AF scans afresh, measuring only the upper middle of the picture (faces, not the table)">&#127919; Refocus (auto)</button>
    <span class="dim" id="cam-hint"></span></div>
  <div class="btns"><span class="lbl">Focus</span>
    <button class="sm" onclick="ctl('camera-focus-2')" title="fixed focus 50 cm">50 cm</button>
    <button class="sm" onclick="ctl('camera-focus-1')" title="fixed focus 1 m">1 m</button>
    <button class="sm" onclick="ctl('camera-focus-0.5')" title="fixed focus 2 m">2 m</button>
    <button class="sm" onclick="ctl('camera-focus-0.33')" title="fixed focus 3 m">3 m</button>
    <button class="sm" onclick="ctl('camera-focus-0')" title="fixed focus at infinity">Far</button>
    <input type="range" id="focus" min="0" max="8" step="0.1" value="0.5" style="width:180px;vertical-align:middle" title="manual focus distance"
      oninput="$('focusv').innerText=focusLabel(this.value)" onchange="setFocus(this.value)">
    <b id="focusv" style="min-width:64px;display:inline-block">&hellip;</b></div>
  <div class="btns"><span class="lbl">Size</span>
    <button class="sm" id="cr-640x360" onclick="ctl('camera-res-640x360')">640&times;360</button>
    <button class="sm" id="cr-800x450" onclick="ctl('camera-res-800x450')">800&times;450</button>
    <button class="sm" id="cr-1280x720" onclick="ctl('camera-res-1280x720')">1280&times;720</button>
    <button class="sm" id="cr-1920x1080" onclick="ctl('camera-res-1920x1080')">1920&times;1080</button>
    <span class="lbl">FPS</span>
    <button class="sm" id="cf-5" onclick="ctl('camera-fps-5')">5</button>
    <button class="sm" id="cf-10" onclick="ctl('camera-fps-10')">10</button>
    <button class="sm" id="cf-15" onclick="ctl('camera-fps-15')">15</button>
    <button class="sm" id="cf-30" onclick="ctl('camera-fps-30')">30</button>
    <span class="lbl">Encoder</span>
    <button class="sm" id="ce-sw" onclick="ctl('camera-enc-sw')" title="jpegenc q70 — sharper, ~26% of a core at 800x450@15">sw</button>
    <button class="sm" id="ce-hw" onclick="ctl('camera-enc-hw')" title="v4l2jpegenc — ~9% CPU but bigger frames">hw</button></div>
  <details class="help"><summary>Focus and size notes</summary>
    Autofocus prefers the nearest object in view (table, keyboard, the robot&rsquo;s own housing), so the fixed distances are safer on stage; the slider sets any distance from 12 cm to infinity.
    Every size / FPS / encoder change restarts the capture (~2 s); big sizes with the sw encoder cost CPU.</details>
  <img id="cam" alt="(camera offline)">
  <div id="cam-off-box" class="dim" style="display:none;padding:18px 0">camera is OFF &mdash; capture stopped, nothing is streaming</div></div>
<div class="stack" data-tab="live audio">
<div class="card"><h2>Wake meter <span class="dim" id="wakenow"></span></h2>
  <div class="bar" style="height:14px"><i id="wakebar" style="width:0%"></i></div>
  <canvas id="spark" style="width:100%;height:48px;background:#0d1117;border-radius:6px"></canvas>
  <div class="mtbl"><table id="wake"><tr><th>time</th><th>score</th></tr></table></div></div>
<div class="card"><h2>Stop meter <span class="dim" id="stopnow"></span></h2>
  <div class="bar" style="height:14px"><i id="stopbar" style="width:0%"></i></div>
  <canvas id="stopspark" style="width:100%;height:48px;background:#0d1117;border-radius:6px"></canvas>
  <div class="mtbl"><table id="stopt"><tr><th>time</th><th>score</th></tr></table></div></div>
</div>

<!-- ═══ GUEST ═══ -->
<div class="sec" data-tab="guest">Guest &mdash; the second robot: roles and voice</div>
<div class="card c12" id="roles-card" data-tab="guest"><h2>Roles <span class="dim">(who is CJAP, who is GUEST)</span></h2>
  <p class="hint">Two robots, one Panganiban. The gold button is CJAP today; tap the GUEST one to swap. The other robot becomes the Host.</p>
  <div class="cols">
    <div>
      <div class="btns" id="role-row">
        <button id="role-alpha" onclick="setRole('alpha')">reachy &hellip;</button>
        <button id="role-beta" onclick="setRole('beta')">reachy &hellip;</button></div>
      <span class="dim" id="role-hint">loading&hellip;</span>
    </div>
    <div class="kv">
      <b>mode</b><span id="g-mode">&hellip;</span>
      <b>mic floor</b><span id="g-floor">&hellip;</span>
      <b>host intro</b><span id="g-intro">&hellip;</span>
      <b>console</b><span><a href="/console" id="g-console" target="_blank" style="color:var(--gold)">open the operator console &#8599;</a> <span class="dim">(floor, mode, listening profile)</span></span>
    </div>
  </div>
  <details class="help"><summary>What a swap does</summary>
    The role is held by the lease authority (config/robots.json), never by this page. A swap is queued until the current answer finishes and journaled on the console.
    In direct mode the mic floor moves with the role, so the visitor keeps talking to Panganiban. The Host robot never composes: it plays its intro line and pre-rendered duet audio only.</details>
</div>
<div class="card c12" id="hostask-card" data-tab="guest"><h2>Host asks <span class="dim">(you type it, the Host says it, Panganiban answers live)</span></h2>
  <p class="hint">The Host puts the question to the room and Panganiban answers it for real &mdash; router, corpus, his voice. No microphone is involved, so a noisy hall cannot mishear it.</p>
  <div class="btns"><span class="lbl">Presets</span><span id="ha-presets" class="dim">loading&hellip;</span></div>
  <div class="btns"><span class="lbl">Question</span>
    <input id="ha-text" maxlength="400" placeholder="What should the Host ask him? (or tap a preset above)" autocomplete="off"
      style="flex:1;min-width:260px" onkeydown="if(event.key==='Enter')hostAsk()">
    <button id="ha-go" class="primary" onclick="hostAsk()">&#127908; Ask</button></div>
  <div class="btns"><span class="lbl">Recording</span>
    <input id="ha-clip" list="ha-clips" placeholder="optional &mdash; a file the Host plays instead of speaking" autocomplete="off" style="flex:1;min-width:240px">
    <datalist id="ha-clips"></datalist>
    <button class="sm" onclick="haClips(true)" title="re-read data/host_questions/">&#8635;</button>
    <span class="dim" id="ha-clipinfo"></span></div>
  <div class="btns"><span class="lbl">Status</span><span class="dim" id="ha-state">&hellip;</span></div>
  <details class="help"><summary>How it is sequenced, and what the recording is for</summary>
    The console bumps the question to the Host, waits for the Host to report that it has finished speaking, and only then releases the text to Panganiban. The two never talk over each other.
    With no Host reporting &mdash; one machine on the network, or the other one down &mdash; the question goes straight to Panganiban instead of stalling.
    A <b>recording</b> is preferred over synthesis: the Host&rsquo;s voice is cloned by hand, so a real take sounds better and costs nothing per ask. Drop <span class="mono">.wav</span> files in <span class="mono">data/host_questions/</span>.
    The audio and the text are deliberately separate: the recording can be a warm, conversational reading while the text stays the precise question you want routed.</details>
  <span id="msg6"></span>
</div>
<div class="card c12" id="voices-card" data-tab="guest"><h2>Guest voice <span class="dim">(ElevenLabs &mdash; API key, voices, switching)</span></h2>
  <p class="hint">Store the ElevenLabs key once, then pick a voice for the Guest (or swap CJAP&rsquo;s). Listen before you choose.</p>
  <div class="btns"><span class="lbl">API key</span>
    <span id="ev-keystate" class="dim">&hellip;</span>
    <input id="ev-key" type="password" autocomplete="off" spellcheck="false" style="flex:1;min-width:210px"
      placeholder="paste an ElevenLabs API key (profile &rarr; API Keys; needs text_to_speech + voices_read)">
    <button id="ev-keysave" class="primary" onclick="evSaveKey()">Save key</button></div>
  <div class="btns"><span class="lbl">Now</span><span id="ev-now" class="dim">&hellip;</span>
    <button class="sm" onclick="evLoad(true)" title="re-ask ElevenLabs for the voice list">&#8635;</button></div>
  <div class="btns saybox"><span class="lbl">Test</span>
    <input type="text" id="ev-say" maxlength="500" placeholder="Type words for the Guest to say, then Enter or Speak" autocomplete="off">
    <button id="ev-saybtn" class="primary" onclick="guestSay()">&#128483; Speak as Guest</button></div>
  <div class="btns"><span class="lbl">Find</span>
    <input id="ev-filter" placeholder="filter by name, label or category" oninput="evRender()" style="flex:1;min-width:160px" autocomplete="off">
    <span class="dim" id="ev-count"></span></div>
  <div id="ev-list" style="max-height:360px;overflow:auto;margin:6px 0"></div>
  <details class="help"><summary>What the buttons do</summary>
    &#9654; plays the ElevenLabs preview here in the browser; &#128266; plays it on the robot&rsquo;s speaker (free preview, no credits).
    <b>GUEST</b> stores the voice as ELEVEN_HOST_VOICE_ID in app/.env for the Host robot&rsquo;s rendered lines (no restart).
    <b>CJAP</b> swaps Panganiban&rsquo;s cloned voice and restarts the voice app (~25 s). A new key also restarts the app.</details>
  <span id="msg5"></span>
</div>

<!-- ═══ AUDIO ═══ -->
<div class="sec" data-tab="audio">Audio &mdash; hearing, meters, listening settings</div>
<div class="card c6" id="mic-card" data-tab="audio"><h2>Microphone meter <span class="dim" id="micstate">off</span></h2>
  <p class="hint">Live levels from the mic array. L is what CJ hears after processing; R is a raw channel of your choice.</p>
  <div class="btns"><span class="lbl">Meter</span>
    <button id="mic-on" onclick="micOn(true)">&#127908; Meter on</button>
    <button id="mic-off" onclick="micOn(false)" style="display:none;border-color:var(--gold)">&#9632; Meter off</button>
    <span class="lbl">Channel R</span>
    <button class="sm" id="mp-mic0" onclick="micPick('mic0')">Mic 0</button>
    <button class="sm" id="mp-mic1" onclick="micPick('mic1')">Mic 1</button>
    <button class="sm" id="mp-mic2" onclick="micPick('mic2')">Mic 2</button>
    <button class="sm" id="mp-mic3" onclick="micPick('mic3')">Mic 3</button>
    <button class="sm" id="mp-ref" onclick="micPick('ref')">AEC reference</button>
    <button class="sm" id="mp-proc" onclick="micPick('proc')">Processed</button>
    <span id="mp-ext"></span></div>
  <details class="help"><summary>What L and R are</summary><span id="mic-hint">L = the filtered beam CJ actually hears (AEC + beamforming + noise suppression); R = your pick straight from the XVF3800: a raw mic as the DSP receives it, or the AEC reference (what the chip is told the speaker is playing), or the processed beam again.</span></details>
  <div class="microw"><b>CJ hears &mdash; processed beam (USB L)</b><span class="mono" id="mic-l-db">&hellip;</span>
    <div class="bar" style="height:12px"><i id="mic-l-bar" style="width:0%"></i></div>
    <canvas id="mic-l-wave" style="width:100%;height:72px;background:#0d1117;border-radius:6px"></canvas></div>
  <div class="microw"><b id="mic-r-lbl">R: raw mic 0</b><span class="mono" id="mic-r-db">&hellip;</span>
    <div class="bar" style="height:12px"><i id="mic-r-bar" style="width:0%"></i></div>
    <canvas id="mic-r-wave" style="width:100%;height:72px;background:#0d1117;border-radius:6px"></canvas></div>
  <div class="btns"><span class="lbl">Chip</span><span id="mic-beams" class="mono dim">beam energies appear once the meter is on</span></div>
</div>
<div class="card c12" data-tab="audio"><h2>Listening settings</h2>
  <p class="hint">How the robot hears. Wake and stop thresholds, how long it waits after you stop talking, speaking pace and answer length. Apply restarts the app.</p>
  <div class="btns"><span class="lbl">Tuning</span>
    <label class="dim">Wake threshold <input type="number" id="tn-wake" step="0.01" min="0.01" max="1" style="width:92px"></label>
    <label class="dim">Stop threshold <input type="number" id="tn-stop" step="0.005" min="0.001" max="1" style="width:92px"></label>
    <label class="dim">Listen time (s) <input type="number" id="tn-listen" step="0.1" min="0.3" max="10" style="width:92px"></label>
    <label class="dim" title="Maximum articulation rate; faster sentences are slowed (pitch unchanged). 13 = measured comfortable, 15 = brisk">Pace ceiling (chars/s) <input type="number" id="tn-pace" step="0.5" min="8" max="20" style="width:92px"></label>
    <label class="dim" title="Hard ceiling on spoken words per answer (60 ≈ 25 s)">Max words <input type="number" id="tn-length" step="5" min="30" max="150" style="width:92px"></label>
    <button class="primary" onclick="applyTuning()">&#10003; Apply &amp; restart app</button></div>
  <span class="dim" id="tn-hint">values from wakeword.conf; the listening knobs (wake threshold, listen time) now live on the console&rsquo;s mode profile</span>
  <div class="btns" style="margin-top:10px"><span class="lbl">Voice ID</span>
    <button onclick="act('enroll-voice')">&#127908; Enroll voice</button>
    <label class="sw" title="Speaker gate: when ON the robot ignores questions from voices that do not match the enrolled speaker">
      <input type="checkbox" id="gate-sw" onchange="setGate(this.checked)"><i></i><span id="gate-lbl">Gate &hellip;</span></label>
    <span class="dim" id="gate-hint">gate ON = only the enrolled voice is answered; needs an enrolled voice first</span></div>
  <div class="btns"><span class="lbl">Isolator</span>
    <label class="sw" title="ElevenLabs Voice Isolator cleans each capture before speech-to-text (adds ~2-3 s per turn; falls back to the raw capture on any error)">
      <input type="checkbox" id="iso-sw" onchange="setIso(this.checked)"><i></i><span id="iso-lbl">&hellip;</span></label>
    <span class="dim" id="iso-hint">ElevenLabs cleans each capture before speech-to-text (~2-3 s more per turn). Switch it off if answers get slow or transcripts get worse.</span></div>
  <div class="btns"><span class="lbl">Tools</span>
    <button class="sm" onclick="audioConsole()">&#127911; Audio console</button>
    <span class="dim">device console from ~/audio-ui.py (record, level meters, isolate) &mdash; starts it on :8090 if needed and opens it in a new tab</span></div>
  <span id="msg2" class="dim"></span>
</div>

<!-- ═══ ROBOT ═══ -->
<div class="sec" data-tab="robot">Robot &mdash; body, face, clips</div>
<div class="card c12" data-tab="robot"><h2>Mechanical actions <span class="dim">(head, antennas, motors &mdash; runs via the voice app when idle)</span></h2>
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
    <button onclick="ctl('gesture-antennas-wiggle')">&#12336; Wiggle</button>
    <span class="lbl">Behaviours</span>
    <button onclick="ctl('gesture-perk')">&#9889; Perk (wake ack)</button>
    <button onclick="ctl('gesture-scan')">&#128064; Scan (look around)</button></div>
  <div class="btns"><span class="lbl">Motion</span>
    <button onclick="ctl('gesture-idle-off')">&#10074;&#10074; Idle motion off</button>
    <button onclick="ctl('gesture-idle-on')">&#9654; Idle motion on</button>
    <button onclick="if(confirm('Motors off: the head goes limp. Support it if needed. Continue?'))ctl('gesture-motors-off')" class="danger" style="background:var(--bad)">&#9940; Motors off</button>
    <button onclick="ctl('gesture-motors-on')">&#9889; Motors on</button>
    <span class="dim">motors off = servos unpowered (safe to reposition by hand); motors on re-centers and resumes idle motion</span></div>
  <span id="msg3" class="dim"></span>
</div>
<div class="card c6" data-tab="robot"><h2>LiveAvatar page <span class="dim" id="avstate"></span></h2>
  <p class="hint">The face shown on the laptop&rsquo;s /face-avatar page.</p>
  <div id="avstatus" class="dim" style="margin-bottom:10px">no /face-avatar page open</div>
  <div class="btns"><span class="lbl">Page</span>
    <button id="av-stop" onclick="ctl('avatar-page-stop')">&#9209; Stop</button>
    <button id="av-resume" onclick="ctl('avatar-page-resume')">&#9654; Resume</button></div>
  <div class="btns"><span class="lbl">Voice</span>
    <button class="sm" id="av-robot" onclick="ctl('avatar-page-voice-robot')">robot (avatar mouths along)</button>
    <button class="sm" id="av-avatar" onclick="ctl('avatar-page-voice-avatar')">avatar only</button>
    <button class="sm" id="av-sync" onclick="ctl('avatar-page-voice-sync')">both synced</button></div>
  <div class="btns"><span class="lbl">View</span>
    <button class="sm" id="avv-framed" onclick="ctl('avatar-view-framed')"
      title="9:10 portrait window — the original exhibit look; a 16:9 avatar is cropped to fit">portrait</button>
    <button class="sm" id="avv-wide" onclick="ctl('avatar-view-wide')"
      title="16:9 window — the whole avatar frame, nothing cropped">wide</button>
    <button class="sm" id="avv-full" onclick="ctl('avatar-view-full')"
      title="edge to edge — the avatar fills the page, plaques float over it">full screen</button></div>
  <div class="btns"><span class="lbl">Idle</span>
    <button class="sm" id="av-loop-on" onclick="ctl('avatar-idle-loop-on')" title="Record a few seconds of the avatar connected but silent after the next answer, then loop it while parked — it blinks and breathes instead of being a photograph. Costs a few extra seconds of session ONCE.">&#9654; Loop live idle</button>
    <button class="sm" id="av-loop-off" onclick="ctl('avatar-idle-loop-off')" title="Back to the single captured frame">&#9632; Still frame</button>
    <span class="dim" id="av-loop-state"></span></div>
  <div class="btns"><span class="lbl">Avatar</span>
    <img id="av-thumb" alt="" style="display:none;height:46px;width:42px;object-fit:cover;
      border-radius:4px;border:1px solid var(--btnline)">
    <span id="av-cur" class="dim">&hellip;</span>
    <button class="sm" onclick="avRefresh()" title="re-ask LiveAvatar for this avatar's name and status">&#8635;</button></div>
  <div class="btns"><span class="lbl">Change</span>
    <input id="av-id" spellcheck="false" placeholder="avatar ID from the LiveAvatar dashboard"
      style="flex:1;min-width:250px">
    <button id="av-apply" class="primary" onclick="avApply()">Apply</button></div>
  <div class="btns"><span class="lbl">API key</span>
    <input id="av-key" type="password" autocomplete="off" style="flex:1;min-width:210px"
      placeholder="only if the new avatar is on another account">
    <label class="dim"><input type="checkbox" id="av-sandbox"> sandbox (free, ~1 min sessions)</label></div>
  <details class="help"><summary>How Apply works</summary>
    Apply checks the id against LiveAvatar first &mdash; a typo is refused instead of leaving the exhibit with a face that will not start. It then writes assets/liveavatar.json and tells the /face-avatar page to drop the old portrait and fetch the new one; a session already on air is ended first. Leave the key blank to keep the stored one. The avatar video is 16:9, so &ldquo;portrait&rdquo; crops about half its width.</details>
  <a class="dim" href="/face?key=" id="avlink" target="_blank">open page &#8599;</a></div>
<div class="card c6" data-tab="robot"><h2>Video clips <span class="dim" id="vidmsg"></span></h2>
  <p class="hint">Clips play full-screen on the /face-avatar page.</p>
  <div id="vid-list" class="dim" style="margin-bottom:10px">loading&hellip;</div>
  <div class="btns"><span class="lbl">Load</span>
    <input type="file" id="vid-file" accept="video/mp4,video/webm,video/quicktime,video/*"
      style="max-width:190px">
    <button onclick="vidUpload()">&#8682; Upload</button></div>
  <div class="btns"><span class="lbl">Sound</span>
    <button class="sm" id="vsnd-robot" onclick="vidSnd('robot')">robot speaker</button>
    <button class="sm" id="vsnd-page" onclick="vidSnd('page')">face-page device (laptop)</button>
    <button onclick="ctl('video-stop')">&#9209; Stop clip</button></div>
  <div class="btns"><span class="lbl">Sync</span>
    <label class="dim">picture offset (ms) <input type="number" id="vid-lead" step="20" min="-2000" max="2000" style="width:92px"></label>
    <button class="sm" onclick="vidLead()">Apply</button>
    <span class="dim" id="vid-lead-hint">&hellip;</span></div>
  <details class="help"><summary>Sound and sync notes</summary>
    Sound goes where Sound points &mdash; &ldquo;robot speaker&rdquo; is whatever the Sound card is routed to right now (the clip is refused if that speaker is not connected). With sound on the robot the picture waits for the speaker to be ready, then starts after the route&rsquo;s latency (internal ~120 ms, Bluetooth ~320 ms) plus this offset &mdash; sound BEFORE picture: raise it; picture before sound: lower it (negative allowed).</details></div>

<!-- ═══ CONVERSATION ═══ -->
<div class="sec" data-tab="conv">Conversation &mdash; what was heard, what was said</div>
<div class="card" data-tab="conv"><h2>Current turn</h2><div id="turn" class="dim">no turn yet</div>
  <h2 style="margin-top:12px">Stage latency</h2><div id="lat" class="dim">&mdash;</div></div>
<div class="card c8" data-tab="conv"><h2>Grounding documents <span class="dim">(composer context, last turn)</span></h2>
  <p class="hint">What Sonnet actually had in front of it. <b>full text</b> = the published column or speech; <b>summary only</b> = its sidecar, so nothing of his own wording reached the composer.</p>
  <div id="docs" class="dim" style="max-height:280px;overflow:auto">no turn yet</div></div>
<div class="card c8" data-tab="conv"><h2>Conversation <span class="dim">(raw vs corrected)</span></h2>
  <table id="conv"><tr><th>who</th><th>text</th></tr></table></div>
<div class="card" data-tab="conv"><h2>NER corrections <span class="dim">(P0)</span></h2>
  <table id="ner"><tr><th>heard</th><th>&rarr; canonical</th><th>class</th><th>conf</th></tr></table></div>
<div class="card c12" data-tab="conv"><h2>Recent turns <span class="dim">(tracking)</span></h2>
  <div style="overflow-x:auto"><table id="hist"><tr><th>time</th><th>question</th><th>theme</th>
  <th>docs</th><th>tokens</th><th>cost</th><th>STT s</th><th>compose s</th><th>speech</th><th>wpm</th><th>flags</th></tr></table></div></div>
<div class="card c12" data-tab="conv"><h2>Entity dictionary overlay <span class="dim">(saves live, no restart)</span></h2>
  <p class="hint">Names and places the transcriber tends to mishear, with their canonical spelling.</p>
  <textarea id="ov" spellcheck="false"></textarea>
  <div class="btns"><button class="primary" onclick="saveOv()">&#128190; Save overlay</button><span id="ovmsg" class="dim"></span></div></div>

<!-- ═══ SYSTEM ═══ -->
<div class="sec" data-tab="system">System &mdash; health, network, providers</div>
<div class="card c6" data-tab="system"><h2>Health</h2><div id="health"></div><div id="flags"></div></div>
<div class="card c6" data-tab="system"><h2>System</h2><div id="services"></div><div id="sys" class="dim">loading&hellip;</div>
  <div class="btns" style="margin-top:10px"><span class="lbl">Restart</span>
    <button class="sm" onclick="ctl('restart-keepalive')">&#8635; bt-keepalive</button>
    <button class="sm" onclick="ctl('restart-watchdog')">&#8635; speaker-watchdog</button>
    <button class="sm" onclick="ctl('restart-dashboard')">&#8635; dashboard</button></div></div>
<div class="card c6" data-tab="system"><h2>WiFi <span class="dim" id="wifinow"></span></h2>
  <div id="wifi-list" class="dim" style="margin-bottom:10px">tap Scan to list networks (tap a network to switch)</div>
  <div class="btns"><button onclick="wifiScan()">&#128246; Scan networks</button><span id="netmsg" class="dim"></span></div>
  <div class="btns" style="margin-top:4px">
    <input id="wm-ssid" placeholder="network name" style="flex:1;min-width:140px">
    <input id="wm-pw" type="password" placeholder="password" style="flex:1;min-width:140px">
    <label class="dim" title="tick when the network does not broadcast its name (it will not appear in a scan)"><input type="checkbox" id="wm-hidden"> hidden network</label>
    <button onclick="wifiManual()">Join</button></div>
  <div class="dim" style="font-size:13px">Tap a scanned network to switch (saved ones need no password; a new password for a saved one replaces the stored one). Manual entry is for hidden networks and setup-hotspot mode.
    &#9888; Switching networks drops this page &mdash; rejoin the same WiFi on your phone. If the join fails the robot goes back to the network it was on.</div>
</div>
<div class="card c6" data-tab="system"><h2>Bluetooth <span class="dim" id="btnow"></span></h2>
  <div id="bt-list" class="dim" style="margin-bottom:10px">loading&hellip;</div>
  <div class="btns"><button onclick="btScan(false)">&#8635; Refresh</button>
    <button onclick="btScan(true)">&#128270; Scan (~10 s)</button><span id="btmsg" class="dim"></span></div>
  <div class="dim" style="font-size:13px">Tap a device to connect / disconnect / pair. Choose which speaker plays on <b>Live &rarr; Sound</b>; the speaker watchdog re-routes to a connected Bluetooth speaker within 15 s.</div>
</div>
<div class="card c12" data-tab="system"><h2>Usage &amp; errors <span class="dim" id="usagets"></span></h2>
  <div id="prov" class="dim" style="margin-bottom:10px">checking providers&hellip;</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px">
    <div><h3>Claude (Anthropic)</h3><div id="u-claude" class="dim">loading&hellip;</div></div>
    <div><h3>ElevenLabs (cloned voice)</h3><div id="u-eleven" class="dim">loading&hellip;</div></div>
    <div><h3>OpenAI (speech-to-text)</h3><div id="u-openai" class="dim">loading&hellip;</div></div>
  </div>
  <h3 style="margin:14px 0 6px">Recent errors &amp; operator actions <span class="dim">(this boot, newest last)</span></h3>
  <pre id="errs" class="mono">loading&hellip;</pre>
</div>

<!-- ═══ LOGS ═══ -->
<div class="sec" data-tab="logs">Logs</div>
<div class="card c12" data-tab="logs"><h2>Logs
  <select id="logunit" onchange="loadLogs()">
    <option value="supervaise">supervaise</option>
    <option value="wifi-fallback">wifi-fallback</option>
    <option value="speaker-watchdog">speaker-watchdog</option>
  </select>
  <button class="sm" onclick="loadLogs()">refresh</button></h2>
  <pre id="logs" class="mono"></pre></div>
</div></div></div><script>
const KEY=new URLSearchParams(location.search).get('key')||localStorage.getItem('cjkey')||'';
if(KEY)localStorage.setItem('cjkey',KEY);
const esc=s=>{const d=document.createElement('div');d.innerText=s==null?'':s;return d.innerHTML};
const $=id=>document.getElementById(id);
// 2026-09-12 speed: the 500 ms poll rewrote every table and chip row even when nothing changed
// (layout work, lost text selection). These sinks now ignore a write that equals the last one.
(function(){const dH=Object.getOwnPropertyDescriptor(Element.prototype,'innerHTML'),dT=Object.getOwnPropertyDescriptor(HTMLElement.prototype,'innerText');
  for(const id of ['strip','health','flags','services','sys','msteps','mtags','turn','lat','docs','conv','ner','hist','wake','stopt','prov','errs',
      'u-claude','u-eleven','u-openai','vid-list','bt-list','wifi-list','ev-list','ev-now','avstatus','av-cur','avstate','camstate','cam-hint',
      'ev-hint','role-hint','mic-beams','logs','tn-hint','vol-hint','mlbl','mdet','mage','wakenow','stopnow','g-mode','g-floor','g-intro']){
    const el=$(id);if(!el)continue;let lh,lt;
    Object.defineProperty(el,'innerHTML',{configurable:true,get(){return dH.get.call(el)},set(v){if(v===lh)return;lh=v;lt=undefined;dH.set.call(el,v)}});
    Object.defineProperty(el,'innerText',{configurable:true,get(){return dT.get.call(el)},set(v){if(v===lt)return;lt=v;lh=undefined;dT.set.call(el,v)}});}})();
function note(t){$('msg').innerText=t;for(const k of ['msg2','msg3','msg4','msg5','msg6'])if($(k))$(k).innerText=t;}
document.addEventListener('change',e=>{if(e.target&&e.target.id==='av-sandbox')avSbTouched=true;});
async function ctl(a){note(a+'\\u2026');const r=await(await fetch('/api/ctl',{method:'POST',
  body:JSON.stringify({action:a,key:KEY})})).json();
  note(r.output||'');}
// Audio console button: the tab is opened INSIDE the click (popup blockers),
// then pointed at :8090 once the backend confirms audio-ui.py is listening.
async function audioConsole(){const w=window.open('','_blank');note('audio console\\u2026');
  const r=await(await fetch('/api/ctl',{method:'POST',
    body:JSON.stringify({action:'audio-console',key:KEY})})).json();
  note(r.output||'');
  if(r.ok&&w){w.location='http://'+location.hostname+':8090';}
  else if(w){w.close();}}
// 2026-08-31: fields are re-read from wakeword.conf every 10 s (an edit in
// progress is left alone) and Apply posts ONLY the fields you changed, so a tab
// left open overnight can no longer write stale values back over a newer conf.
const TUNING_LOADED={};
let VIDS=[];
async function vidList(){try{
  const r=await(await fetch('/api/videos?key='+KEY)).json();VIDS=r.videos||[];
  if(r.lead_offset_ms!=null&&document.activeElement!==$('vid-lead')){$('vid-lead').value=r.lead_offset_ms;
    $('vid-lead-hint').textContent='route base '+r.lead_base_ms+' ms \u2192 picture starts '+r.lead_ms+' ms after the sound is sent';}
  // name the speaker the clip's sound will actually come out of (2026-09-02)
  if(r.route)$('vsnd-robot').textContent='robot speaker ('+r.route+')';
  $('vid-list').innerHTML=VIDS.length?VIDS.map((v,i)=>
    '<div style="margin:3px 0"><button onclick="vidPlay('+i+')" title="play on the face page">&#9654;</button> '+
    '<button onclick="vidDel('+i+')" title="delete">&#10005;</button> '+esc(v.name)+
    ' <span class="dim">('+(v.size/1e6).toFixed(1)+' MB)</span></div>').join('')
    :'no clips uploaded yet';
}catch(e){$('vid-list').innerText='list failed: '+e.message;}}
let VID_SND='robot';try{VID_SND=localStorage.getItem('cj_vid_snd')||'robot';}catch(e){}
function vidSnd(m){VID_SND=m;try{localStorage.setItem('cj_vid_snd',m);}catch(e){}
  $('vsnd-robot').style.borderColor=m==='robot'?'var(--gold)':'';
  $('vsnd-page').style.borderColor=m==='page'?'var(--gold)':'';}
// Avatar swap (2026-09-04, user). Goes to its own endpoint, not /api/ctl:
// the body may carry an API key and /api/ctl prints every action to the journal.
let avSbTouched=false;
let AV_BUSY=false;
async function avConf(read){
  // 2026-09-05: each call is a live LiveAvatar round trip and rapid clicks
  // fired up to 5/s (journal 2026-09-04) — one in flight at a time.
  if(AV_BUSY)return;
  const b={key:KEY};
  if(read)b.read=1;
  else{
    b.avatar_id=$('av-id').value.trim();
    const k=$('av-key').value.trim();if(k)b.api_key=k;
    b.sandbox=$('av-sandbox').checked;
    if(!b.avatar_id){note('paste the avatar id first');return;}
  }
  note(read?'asking LiveAvatar\u2026':'applying avatar\u2026');
  AV_BUSY=true;const ab=$('av-apply');ab.disabled=true;
  try{
    let r={};
    try{r=await(await fetch('/api/avatar-conf',{method:'POST',body:JSON.stringify(b)})).json();}
    catch(e){note('avatar: '+e.message);return;}
    if(!r.ok){note('avatar REFUSED: '+(typeof r.output==='string'?r.output:JSON.stringify(r.output)));return;}
    if(read){note('avatar details refreshed');return;}
    note(r.output);$('av-id').value='';$('av-key').value='';avSbTouched=false;
  }finally{AV_BUSY=false;ab.disabled=false;}
}
const avApply=()=>avConf(false),avRefresh=()=>avConf(true);
for(const id of ['av-id','av-key'])$(id).addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();avApply();}});
async function vidLead(){const v=parseInt($('vid-lead').value||'0',10);await ctl('video-lead-'+v);vidList();}
async function vidPlay(i){await ctl((VID_SND==='page'?'video-playlocal-':'video-play-')+VIDS[i].name);}
async function vidDel(i){if(!confirm('Delete '+VIDS[i].name+'?'))return;
  await ctl('video-delete-'+VIDS[i].name);vidList();}
function vidUpload(){const f=$('vid-file').files[0];
  if(!f){$('vidmsg').innerText='choose a file first';return;}
  const x=new XMLHttpRequest();
  x.open('POST','/api/video-upload?key='+KEY+'&name='+encodeURIComponent(f.name));
  x.upload.onprogress=e=>{if(e.lengthComputable)
    $('vidmsg').innerText='uploading '+Math.round(100*e.loaded/e.total)+'%';};
  x.onload=()=>{let r={};try{r=JSON.parse(x.responseText);}catch(e){}
    $('vidmsg').innerText=r.ok?r.output:'FAILED: '+(r.output||x.status);
    $('vid-file').value='';vidList();};
  x.onerror=()=>{$('vidmsg').innerText='upload failed (network)';};
  x.send(f);}
async function loadTuning(){try{const r=await(await fetch('/api/tuning?key='+KEY)).json();const t=r.tuning||{};
  for(const k of ['wake','stop','listen','pace','length']){const el=$('tn-'+k);if(!el||t[k]==null)continue;
    if(document.activeElement!==el&&(TUNING_LOADED[k]==null||String(el.value)===String(TUNING_LOADED[k])))el.value=t[k];
    TUNING_LOADED[k]=t[k];}
  if(t.error)$('tn-hint').innerText=t.error;}catch(e){}}
async function applyTuning(){const b={key:KEY},ch=[];for(const k of ['wake','stop','listen','pace','length']){const v=$('tn-'+k).value;
    if(v!==''&&(TUNING_LOADED[k]==null||Number(v)!==Number(TUNING_LOADED[k]))){b[k]=v;ch.push(k+' '+TUNING_LOADED[k]+' \\u2192 '+v);}}
  if(!ch.length){note('no change');return;}
  if(!confirm('Apply '+ch.join(', ')+' and restart the voice app? CJ goes quiet for about 25 s.'))return;
  note('applying\\u2026');const r=await(await fetch('/api/tuning',{method:'POST',body:JSON.stringify(b)})).json();
  note((r.ok?'':'FAILED: ')+(r.output||''));setTimeout(loadTuning,3000);}
loadTuning();setInterval(loadTuning,10000);
// 2026-09-01 master volume: slider posts on release; re-read every 10 s unless being dragged
let VOL_LOADED=null;
async function loadVol(){try{const r=await(await fetch('/api/volume?key='+KEY)).json();
  if(r.level==null)return;const el=$('vol');
  if(document.activeElement!==el&&(VOL_LOADED==null||String(el.value)===String(VOL_LOADED)))el.value=r.level;
  VOL_LOADED=r.level;$('volv').innerText=r.level+'%';
  $('vol-hint').innerText='live on: '+(r.applied||'?')+' \u00b7 route: '+(r.route||'?')+' \u00b7 applies to the internal speaker and any connected Bluetooth speaker (scales below the speaker\u2019s own button level); kept across switches, reconnects and reboots';
  }catch(e){}}
async function setVol(v){v=Math.max(0,Math.min(100,Math.round(+v)));$('vol').value=v;$('volv').innerText=v+'%';note('volume '+v+'%\u2026');
  try{const r=await(await fetch('/api/volume',{method:'POST',body:JSON.stringify({key:KEY,level:v})})).json();
    VOL_LOADED=r.level;note((r.ok?'':'FAILED: ')+(r.output||''));$('vol').blur();loadVol();}catch(e){note('volume failed: '+e.message)}}
loadVol();setInterval(loadVol,10000);
// 2026-09-01 focus slider: dioptres 0..8 (∞ .. 12 cm); posts on release (each change restarts the capture)
function focusLabel(d){d=+d;if(d<=0)return'∞ far';const m=1/d;return m>=1?m.toFixed(m>=3?0:1)+' m':Math.round(m*100)+' cm';}
let FOCUS_LOADED=null;
async function setFocus(v){v=Math.max(0,Math.min(8,Math.round(+v*10)/10));note('focus '+focusLabel(v)+'…');
  try{const r=await(await fetch('/api/ctl',{method:'POST',body:JSON.stringify({key:KEY,action:'camera-focus-'+v})})).json();
    note((r.ok?'':'FAILED: ')+(r.output||''));FOCUS_LOADED=String(v);$('focus').blur();}catch(e){note('focus failed: '+e.message)}}
function syncFocus(f){if(f==null)return;const el=$('focus');if(!el)return;
  if(f==='auto'){$('focusv').innerText='auto';FOCUS_LOADED='auto';return;}
  if(document.activeElement!==el&&(FOCUS_LOADED==null||String(el.value)===String(FOCUS_LOADED)||FOCUS_LOADED==='auto'))el.value=f;
  FOCUS_LOADED=f;$('focusv').innerText=focusLabel(f);}
// 2026-09-01 microphone meter: L = processed beam (what CJ hears), R = XVF3800 channel pick via /api/mic
let MIC_ON=false,MIC_BUSY=false,MIC_EXT_SIG=null;
function micOn(v){MIC_ON=v;$('mic-on').style.display=v?'none':'';$('mic-off').style.display=v?'':'none';
  $('micstate').innerText=v?'starting…':'off';
  if(!v){fetch('/api/mic',{method:'POST',body:JSON.stringify({key:KEY,source:'off'})}).catch(()=>{});}else micTick();}
async function micPick(s){note('mic meter: '+s+'…');
  try{const r=await(await fetch('/api/mic',{method:'POST',body:JSON.stringify({key:KEY,source:s})})).json();
    note((r.ok?'':'FAILED: ')+(r.output||''));if(!MIC_ON)micOn(true);}catch(e){note('mic meter failed: '+e.message)}}
function micWave(id,w,col){const c=$(id);const dpr=window.devicePixelRatio||1;const W=c.clientWidth,H=c.clientHeight;if(!W)return;
  if(c.width!==Math.round(W*dpr)||c.height!==Math.round(H*dpr)){c.width=Math.round(W*dpr);c.height=Math.round(H*dpr);}
  const g=c.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);g.clearRect(0,0,W,H);
  g.strokeStyle='#30363d';g.lineWidth=1;g.beginPath();g.moveTo(0,H/2);g.lineTo(W,H/2);g.stroke();
  if(!w||!w.length)return;const n=w.length,sx=W/n;g.strokeStyle=col;g.lineWidth=Math.max(1,sx*0.8);g.beginPath();
  for(let i=0;i<n;i++){const x=i*sx+sx/2,y1=H/2-w[i][1]/100*(H/2-2),y2=H/2-w[i][0]/100*(H/2-2);g.moveTo(x,y1);g.lineTo(x,Math.max(y2,y1+1));}g.stroke();}
function micLvl(pre,ch){const db=ch.rms_db==null?-90:ch.rms_db,pk=ch.peak_db==null?-90:ch.peak_db;
  const pct=Math.max(0,Math.min(100,(db+60)/60*100));const b=$(pre+'-bar');b.style.width=pct+'%';
  b.style.background=pk>-3?'var(--bad)':(db>-20?'var(--gold)':'#3fb950');
  $(pre+'-db').innerText=(db<=-90?'silent':db.toFixed(1)+' dBFS')+' · peak '+(pk<=-90?'—':pk.toFixed(1)+' dBFS');}
async function micTick(){if(!MIC_ON||MIC_BUSY)return;MIC_BUSY=true;
  try{const r=await(await fetch('/api/mic?key='+KEY)).json();
    $('micstate').innerText=(r.on?'live · R = '+r.label:'not running')+(r.error?' · '+r.error:'');
    $('mic-r-lbl').innerText='R: '+(r.label||'?');
    const ext=(r.sources||[]).filter(s=>s.id.startsWith('ext'));
    const sig=ext.map(s=>s.id+'|'+s.label).join(';');
    if(sig!==MIC_EXT_SIG){MIC_EXT_SIG=sig;$('mp-ext').innerHTML=ext.map(s=>
      '<button class="sm" id="mp-'+s.id+'" onclick="micPick(&#39;'+s.id+'&#39;)" title="'+esc(s.label)+'">&#128900; '
      +esc(s.label.replace('connected: ',''))+'</button>').join('');}
    for(const s of (r.sources||[])){const b=$('mp-'+s.id);if(b)b.style.borderColor=s.id===r.source?'var(--gold)':'';}
    micLvl('mic-l',r.proc||{});micLvl('mic-r',r.pick||{});
    micWave('mic-l-wave',(r.proc||{}).wave,'#c9a227');micWave('mic-r-wave',(r.pick||{}).wave,'#58a6ff');
    const c=r.chip||{};if(c.beam_energy&&c.beam_energy.length){const mx=Math.max(1e-6,...c.beam_energy.map(x=>x||0));
      $('mic-beams').innerHTML=c.beam_energy.map((e,i)=>'beam '+i+' <span class="mbar"><i style="width:'+Math.round((e||0)/mx*100)+'%"></i></span>').join('')
        +' AEC <span style="color:'+(c.converged?'var(--ok)':'var(--gold)')+'">'+(c.converged?'converged':'not converged')+'</span>'
        +' &nbsp;azimuth '+((c.azimuth_deg||[]).map(a=>a==null?'?':a+'°').join(' / '))
        +' &nbsp;L='+JSON.stringify(c.op_l||[])+' R='+JSON.stringify(c.op_r||[])+(r.chip_age_s!=null?' ('+r.chip_age_s+' s ago)':'');}
  }catch(e){$('micstate').innerText='error '+e.message}finally{MIC_BUSY=false}}
setInterval(()=>{if(!document.hidden&&vis('mic-l-wave'))micTick()},250);
// Who is Panganiban (2026-09-12): the same role swap the /console page
// offers, from here. The lease authority (config/robots.json) decides; on
// the other machine the buttons are disabled and link to the authority.
async function setRole(slot){note('Panganiban \u2192 '+slot+'\u2026');
  try{const r=await(await fetch('/api/role',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({key:KEY,cjap_is:slot,who:'maintain'})})).json();
    note(r.output||(r.ok?'done':'role swap failed'));poll();}
  catch(e){note('role swap failed: '+e);}}
function renderRoles(s){const rs=s.roles;
  try{const txt=(id,v)=>{const el=$(id);if(el)el.innerText=v;};
    txt('g-mode',s.mode?s.mode+(s.profile?' \u00b7 '+s.profile+' profile':''):'\u2014');
    txt('g-floor',s.floor?(s.floor==='none'?'no one (both mics closed)':s.floor+(s.floorRole?' \u00b7 '+(s.floorRole==='cjap'?'CJAP':'GUEST'):'')+(s.transition?' \u2014 moving to '+s.transition.target:'')):'\u2014');
    txt('g-intro',s.hostIntroText?'\u201c'+s.hostIntroText+'\u201d':'none in this mode profile');
    const cl=$('g-console'),href=(s.console_authority||'')+'/console?key='+encodeURIComponent(KEY);if(cl)cl.href=href;const hl=$('consolelink');if(hl)hl.href=href;}catch(e){}
  if(rs){for(const r of ['alpha','beta']){const x=rs[r]||{},b=$('role-'+r),is=x.role==='cjap';b.disabled=is;
      b.innerHTML=is?'\u2696 reachy CJAP':'reachy GUEST';
      b.title=(x.machine||r)+' ('+r+') is '+(is?'CJAP \u2014 Panganiban, answers from the corpus':'GUEST \u2014 the Host; click to make it CJAP and swap');
      b.style.borderColor=is?'var(--gold)':'';b.style.color=is?'var(--gold)':'';b.setAttribute('aria-pressed',is);}
    const p=s.pending;
    $('role-hint').innerText=p&&/Panganiban/.test(p.what||'')?'swap queued '+fmtAge(p.queued_s)+(p.waiting_on?' \u2014 waits for the current turn to finish':''):
      'click reachy GUEST to swap the roles'+(s.mode==='direct'?' (direct mode: the floor follows CJAP)':'');}
  else{for(const r of ['alpha','beta'])$('role-'+r).disabled=true;
    $('role-hint').innerHTML=s.console_authority?'set on the lease authority: <a href="'+esc(s.console_authority)+'/maintain?key='+encodeURIComponent(KEY)+'">'+esc(s.console_authority)+'</a>':
      (s.console_error?'console unavailable: '+esc(s.console_error):'no console state');}}
// Host asks (2026-09-12): type a question, the Host says it, Panganiban answers live.
async function haPresets(){try{const r=await(await fetch('/api/event-questions?key='+encodeURIComponent(KEY))).json();
    const qs=r.questions||[];
    $('ha-presets').innerHTML=qs.length?qs.map((q,i)=>'<button class="sm" data-i="'+i+'" title="'+esc(q.q)+'">'+esc(q.q.length>34?q.q.slice(0,32)+'\u2026':q.q)+'</button>').join(' '):'no event questions in canned_answers.json';
    HA_PRESETS=qs;
    [].forEach.call($('ha-presets').getElementsByTagName('button'),function(b){b.onclick=function(){const q=HA_PRESETS[+b.dataset.i];if(!q)return;$('ha-text').value=q.q;hostAsk();};});
  }catch(e){$('ha-presets').textContent='presets: '+e;}}
let HA_PRESETS=[];
async function haClips(force){try{const r=await(await fetch('/api/host-clips?key='+encodeURIComponent(KEY)+(force?'&_='+Date.now():''),{cache:force?'no-store':'default'})).json();
    const cl=r.clips||[];$('ha-clips').innerHTML=cl.map(c=>'<option value="'+esc(c.name)+'">').join('');
    $('ha-clipinfo').textContent=cl.length?cl.length+' recording'+(cl.length>1?'s':'')+' on disk':'no recordings yet in data/host_questions/';
  }catch(e){$('ha-clipinfo').textContent='clip list: '+e;}}
async function hostAsk(){const t=$('ha-text').value.trim();if(!t){note('type a question first');return;}
  $('ha-go').disabled=true;note('handing it to the Host\u2026');
  try{const r=await(await fetch('/api/host-ask',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({key:KEY,text:t,clip:$('ha-clip').value.trim(),who:'maintain'})})).json();
    note(r.output||(r.ok?'asked':'refused'));if(r.ok)$('ha-text').value='';poll();}
  catch(e){note('ask failed: '+e);}finally{$('ha-go').disabled=false;}}
function renderAsk(s){const a=s.ask,el=$('ha-state');if(!el)return;
  if(!a||!a.seq){el.textContent='nothing asked yet this session';return;}
  const age=a.age_s!=null?' \u00b7 '+fmtAge(a.age_s)+' ago':'';
  el.innerHTML=(a.stage==='host'?'<b style="color:var(--gold)">the Host is asking it</b>'
    :a.stage==='cjap'?'<b style="color:var(--ok)">handed to Panganiban</b>':'sent')
    +' \u2014 \u201c'+esc(a.text)+'\u201d'+(a.clip?' <span class="mono">['+esc(a.clip)+']</span>':'')+age;}
haClips(false);haPresets();
// Guest voice card (2026-09-12): ElevenLabs key + voice list + role switch.
let EV={voices:[],cjap_voice_id:'',host_voice_id:''},EV_AUDIO=null;
async function evLoad(refresh){try{const r=await(await fetch('/api/voices?key='+encodeURIComponent(KEY)+(refresh?'&refresh=1&_='+Date.now():''),{cache:'no-store'})).json();
    if(r.ok===false){$('ev-now').innerText=r.output||'voices: refused';return;}EV=r;evRender();}
  catch(e){$('ev-now').innerText='voices: '+e;}}
function evName(id){if(!id)return'';const v=(EV.voices||[]).find(x=>x.voice_id===id);return v?v.name:'(id not on this account)';}
function evRender(){const d=EV,q=($('ev-filter').value||'').toLowerCase().trim();
  $('ev-keystate').innerText=d.has_key?'stored '+d.key_hint:'no key stored';
  $('ev-now').innerHTML='GUEST: <b style="color:var(--ink)">'+esc(d.host_voice_id?evName(d.host_voice_id):'not set')+'</b>'
    +(d.host_voice_id?' <span style="font-family:monospace;font-size:12px">'+esc(d.host_voice_id)+'</span>':'')
    +' &nbsp;&middot;&nbsp; CJAP: <b style="color:var(--ink)">'+esc(d.cjap_voice_id?evName(d.cjap_voice_id):'not set')+'</b>'
    +(d.cjap_voice_id?' <span style="font-family:monospace;font-size:12px">'+esc(d.cjap_voice_id)+'</span>':'')
    +(d.error?' <span class="bad" style="color:#e5484d">'+esc(d.error)+'</span>':'');
  const all=d.voices||[],rows=all.filter(v=>!q||(v.name+' '+v.labels+' '+v.category+' '+v.description).toLowerCase().includes(q));
  $('ev-count').innerText=all.length?rows.length+' of '+all.length+' voices':'';
  if(!rows.length){$('ev-list').innerHTML='<span class="dim">'+(d.has_key?(all.length?'no voice matches the filter':'no voices listed yet'):'paste an API key to list the account\u2019s voices')+'</span>';return;}
  $('ev-list').innerHTML='<table><tr><th>voice</th><th>category &middot; labels</th><th style="white-space:nowrap">listen</th><th style="white-space:nowrap">use as</th></tr>'+rows.map(v=>{const i=all.indexOf(v),isH=v.voice_id===d.host_voice_id,isC=v.voice_id===d.cjap_voice_id;
    return '<tr><td><b'+(isH||isC?' style="color:var(--gold)"':'')+'>'+esc(v.name)+'</b>'+(isH?' <span class="chip ok">GUEST</span>':'')+(isC?' <span class="chip ok">CJAP</span>':'')
      +(v.description?'<br><span class="dim">'+esc(v.description)+'</span>':'')+'<br><span style="font-family:monospace;font-size:11px" class="dim">'+esc(v.voice_id)+'</span></td>'
      +'<td class="dim">'+esc(v.category)+(v.labels?' &middot; '+esc(v.labels):'')+'</td>'
      +'<td style="white-space:nowrap"><button class="sm" onclick="evPlay('+i+')" title="play the preview in this browser"'+(v.preview_url?'':' disabled')+'>&#9654;</button> '
      +'<button class="sm" onclick="evRobot('+i+')" title="play the preview on the robot speaker"'+(v.preview_url?'':' disabled')+'>&#128266;</button></td>'
      +'<td style="white-space:nowrap"><button class="sm" onclick="evUse('+i+',&#39;host&#39;)"'+(isH?' disabled':'')+' title="Host robot voice (ELEVEN_HOST_VOICE_ID)">GUEST</button> '
      +'<button class="sm" onclick="evUse('+i+',&#39;cjap&#39;)"'+(isC?' disabled':'')+' title="Panganiban voice (ELEVEN_VOICE_ID) \u2014 restarts the app">CJAP</button></td></tr>';}).join('')+'</table>';}
function evPlay(i){const v=EV.voices[i];if(!v||!v.preview_url){note('no preview clip for this voice');return;}
  if(EV_AUDIO){EV_AUDIO.pause();EV_AUDIO=null;}EV_AUDIO=new Audio(v.preview_url);note('preview: '+v.name);EV_AUDIO.play().catch(e=>note('preview failed: '+e));}
async function evRobot(i){const v=EV.voices[i];if(!v)return;note('playing '+v.name+' on the robot\u2026');
  try{const r=await(await fetch('/api/voice-audition',{method:'POST',body:JSON.stringify({key:KEY,voice_id:v.voice_id})})).json();
    note(r.ok?'played '+v.name+' on the robot':'robot preview: '+(r.output||'failed'));}catch(e){note('robot preview: '+e);}}
async function evPost(b){b.key=KEY;try{const r=await(await fetch('/api/voices',{method:'POST',body:JSON.stringify(b)})).json();
    note(r.output||(r.ok?'done':'refused'));if(r.ok)evLoad(true);return r;}catch(e){note('voices: '+e);return null;}}
async function evUse(i,role){const v=EV.voices[i];if(!v)return;
  if(role==='cjap'&&!confirm('Make \u201c'+v.name+'\u201d the CJAP (Panganiban) voice? The voice app restarts (~25 s) and the mic is off meanwhile.'))return;
  note((role==='host'?'GUEST':'CJAP')+' voice \u2192 '+v.name+'\u2026');await evPost({role:role,voice_id:v.voice_id});}
async function guestSay(){const t=$('ev-say').value.trim();if(!t){note('type something for the Guest to say');return;}
  $('ev-saybtn').disabled=true;note('Guest speaking\u2026');
  try{const r=await(await fetch('/api/say-text?key='+encodeURIComponent(KEY),{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({key:KEY,text:t,voice:'host'})})).json();
    note(r.output||(r.ok?'spoke as Guest':'failed'));if(r.ok)$('ev-say').value='';}
  catch(e){note('Guest say failed: '+e);}finally{$('ev-saybtn').disabled=false;}}
document.addEventListener('keydown',function(e){if(e.key==='Enter'&&document.activeElement&&document.activeElement.id==='ev-say')guestSay();});
async function evSaveKey(){const k=$('ev-key').value.trim();if(!k){note('paste a key first');return;}
  if(!confirm('Store this ElevenLabs key in app/.env? The voice app restarts (~25 s).'))return;
  note('checking the key with ElevenLabs\u2026');const r=await evPost({api_key:k});if(r&&r.ok)$('ev-key').value='';}
evLoad(false);
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
// Robot mode (2026-09-02): APP DOWN > SPEAKING > LISTENING > THINKING > MUTED > IDLE.
// Rules mirror /audience renderExhibit() so the two views never disagree.
const STEP_ORDER=['transcribe','route','compose','fidelity'];
function robotMode(s){
  const h=s.health||{},sp=s.speaking,stg=s.stage,turns=s.turns||[];
  if(h.supervaise===false)return{st:'down',lbl:'APP DOWN',det:'supervaise.service is not active'};
  const lastU=turns.filter(t=>t.role==='user').slice(-1)[0],lastC=turns.filter(t=>t.role==='cj').slice(-1)[0];
  const steps=(stg&&stg.steps)||{},tr=steps.transcribe;
  const listening=tr&&tr.state==='active'&&(s.ts-stg.ts)<60;
  const qNow=lastU&&stg&&lastU.ts>=stg.turn_ts-1;
  if(sp&&!sp.done&&(sp.spoken||[]).length){
    const cur=sp.spoken[sp.spoken.length-1]||'';
    return{st:'speaking',lbl:'SPEAKING',det:'sentence '+sp.spoken.length+(sp.interrupted?' (interrupted)':'')+' — “'+cur.slice(0,110)+(cur.length>110?'…':'')+'”',since:sp.ts};}
  if(listening&&!qNow)return{st:'listening',lbl:'LISTENING',det:(tr.detail||'mic open, waiting for the question'),since:stg.ts};
  if(lastU&&(!sp||lastU.ts>sp.ts)&&(!lastC||lastU.ts>lastC.ts)){
    const act=STEP_ORDER.map(k=>[k,steps[k]]).filter(([k,v])=>v&&v.state==='active').slice(-1)[0];
    const last=STEP_ORDER.map(k=>[k,steps[k]]).filter(([k,v])=>v&&v.state==='done').slice(-1)[0];
    const d=act?act[0]+': '+(act[1].detail||'working…'):(last?last[0]+' done: '+(last[1].detail||''):'preparing the answer');
    return{st:'thinking',lbl:'THINKING',det:d+' — “'+(lastU.text||'').slice(0,80)+'”',since:lastU.ts};}
  if(s.muted)return{st:'muted',lbl:'MUTED',det:'mic muted — wake word and stop word ignored; robot still speaks'};
  if(s.video_mute)return{st:'muted',lbl:'VIDEO CLIP',det:'mic muted while the dashboard plays a clip'};
  const w=s.wake,alive=w&&(s.ts-w.ts)<3;
  const endTs=(sp&&sp.done&&(sp.spoken||[]).length)?sp.ts:(lastC?lastC.ts:0);
  return{st:'idle',lbl:'IDLE',det:alive?'listening for the wake phrase (score '+(+w.score).toFixed(3)+', peak '+(+w.peak1s).toFixed(3)+')':'wake meter silent — app starting or mic not open',since:endTs||null};
}
function fmtAge(sec){if(sec==null||!(sec>=0))return'';return sec<60?sec.toFixed(0)+'s':sec<3600?Math.floor(sec/60)+'m '+Math.floor(sec%60)+'s':Math.floor(sec/3600)+'h '+Math.floor(sec%3600/60)+'m';}
function renderMode(s){
  const m=robotMode(s),el=$('mode');
  el.className='mode '+m.st;$('mlbl').innerText=m.lbl;$('mdet').innerText=m.det||'';
  $('mage').innerText=m.since?'· '+fmtAge(s.ts-m.since)+(m.st==='idle'?' since last answer':''):'';
  // pipeline of the current/last turn + a synthetic "speak" step
  const steps=(s.stage&&s.stage.steps)||{},sp=s.speaking,html=[];
  for(const k of STEP_ORDER){const v=steps[k]||{};const st=v.state||'';
    html.push('<span class="'+st+'" title="'+esc(v.detail||'').replace(/"/g,'&quot;')+'">'+k+(v.t!=null&&st==='done'?' '+(+v.t).toFixed(1)+'s':'')+'</span>');}
  const spst=sp&&(sp.spoken||[]).length?(sp.done?'done':'active'):'';
  html.push('<span class="'+spst+'" title="'+(sp&&sp.spoken?esc(sp.spoken.join(' ')).slice(0,400).replace(/"/g,'&quot;'):'')+'">speak'+(sp&&sp.spoken&&sp.spoken.length?' '+sp.spoken.length+(sp.done?'':'…'):'')+'</span>');
  $('msteps').innerHTML=html.join('');
  const w=s.wake||{},h=s.health||{},tags=[];
  const t=(k,v,c)=>tags.push('<span><span class="k">'+k+'</span> <b class="'+(c||'')+'">'+v+'</b></span>');
  t('wake listener',w.ts&&(s.ts-w.ts)<3?'armed':'silent',w.ts&&(s.ts-w.ts)<3?'on':'bad');
  if(w.fired_ts)t('last wake',fmtAge(s.ts-w.fired_ts)+' ago ('+(+w.fired_score).toFixed(2)+')','');
  t('mic',s.muted?'MUTED':(s.video_mute?'video clip':'live'),s.muted||s.video_mute?'bad':'on');
  const st=s.stop||{};if(st.ts&&(s.ts-st.ts)<3)t('stop word','scoring '+(+st.score).toFixed(3),'warn');
  const vl=s.voice_lock;if(vl&&vl.locked!=null)t('voice lock',vl.locked?'locked'+(vl.until?' '+fmtAge(vl.until-s.ts)+' left':''):'open',vl.locked?'warn':'');
  t('event mode',s.event_mode?'ON':'off',s.event_mode?'warn':'');
  t('speaker',esc(s.audio_route||'?'),'');t('internet',h.internet?'ok':'OFFLINE',h.internet?'on':'bad');
  $('mtags').innerHTML=tags.join('');
}
async function poll(){try{render(await(await fetch('/api/state')).json())}catch(e){}}
function render(s){try{LAST_S=s;LAST_AT=Date.now();
  try{renderMode(s);}catch(e){}
  try{  // quick-status strip (2026-08-29): mic · speaker · services · last turn timings
    const h=s.health||{},sp=(s.metas||[]).filter(m=>m.phase==='spoken').slice(-1)[0],cp=(s.metas||[]).filter(m=>m.phase==='composed').slice(-1)[0];
    const f=(v,u='s')=>v==null?'-':(+v).toFixed(1)+u;
    const item=(k,v,cls)=>`<span><span class="k">${k}</span><b class="${cls||''}">${v}</b></span>`;
    $('strip').innerHTML=item('mic',s.muted?'MUTED':'live',s.muted?'bad':'ok')
      +item('speaker',esc(s.audio_route||'?'),/internal|dac/i.test(s.audio_route||'')?'ok':'warn')
      +(s.volume!=null?item('volume',s.volume+'%',s.volume==0?'bad':(s.volume<50?'warn':'ok')):'')
      +(s.camera_backend?item('camera',s.camera_backend,s.camera_backend.startsWith('gst')?'ok':'warn'):'')
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
  window.__camOff=!!s.camera_off;try{syncFocus(s.camera_focus)}catch(e){}
  try{const co=s.camera_opts||{};
    for(const r of ['640x360','800x450','1280x720','1920x1080'])$('cr-'+r).style.borderColor=(co.w+'x'+co.h)===r?'var(--gold)':'';
    for(const f of [5,10,15,30])$('cf-'+f).style.borderColor=co.fps===f?'var(--gold)':'';
    for(const e of ['sw','hw'])$('ce-'+e).style.borderColor=co.enc===e?'var(--gold)':'';}catch(e){}
  $('btn-cam-off').style.display=s.camera_off?'none':'';
  $('btn-cam-on').style.display=s.camera_off?'':'none';
  $('cam').style.display=s.camera_off?'none':'';
  $('cam-off-box').style.display=s.camera_off?'':'none';
  $('camstate').innerHTML=chip('camera',!s.camera_off,s.camera_off?'OFF':'on');
  $('cam-hint').innerText=s.camera_off?'OFF \u2014 /audience shows its idle plaque instead of the portrait':'on \u2014 always running until Camera off';
  $('btn-ev-on').style.display=s.event_mode?'none':'';
  $('btn-ev-off').style.display=s.event_mode?'':'none';
  $('ev-hint').innerText=s.event_mode?'ON \u2014 spoken event questions (and paraphrases) get the scripted answers':'off \u2014 normal conversation; the /event buttons still work';
  try{renderRoles(s);}catch(e){}
  try{renderAsk(s);}catch(e){}
  const av=s.avatar_page||{},avAge=av.ts?(s.ts-av.ts):1e9,avOn=avAge<10;
  // Idle / Listening / Thinking / Speaking / Muted — the same call robotMode()
  // makes for the banner, so this card, /audience and /face-avatar agree.
  const am=robotMode(s);
  $('avstate').innerHTML=
    chip('page',avOn,avOn?(av.stopped?'stopped':av.ready?'session live (credits ticking)':'parked — no credits'):'not open')+
    (avOn?'<span class="chip st-'+am.st+'">'+am.lbl.toLowerCase()+'</span>'+
          (av.mode?chip('voice',true,av.mode):'')+
          (typeof av.lag==='number'?chip('lag',true,av.lag.toFixed(2)+'s'):''):'');
  $('avstatus').innerText=avOn?(av.status||''):
    'no /face-avatar page open (open it on the laptop: /face?key=…)';
  const ac=s.avatar_conf||{};
  $('av-cur').innerHTML=ac.avatar_id?
    '<b style="color:var(--ink)">'+esc(ac.name||'(name unknown — press ⟳)')+'</b>'+
    (ac.status&&ac.status!=='ACTIVE'?' <span class="bad">'+esc(ac.status)+'</span>':'')+
    (ac.voice?' · voice '+esc(ac.voice):'')+' · '+(ac.sandbox?'sandbox':'production')+
    (ac.has_key?'':' · <span class="bad">no API key</span>')+
    '<br><span class="mono">'+esc(ac.avatar_id)+'</span>'+
    (ac.configured?'':' <span class="dim">(built-in default)</span>')
    :'no assets/liveavatar.json';
  const th=$('av-thumb');
  if(ac.preview_url){if(th.dataset.src!==ac.preview_url){th.dataset.src=ac.preview_url;th.src=ac.preview_url;}
    th.style.display='';}else th.style.display='none';
  if(!avSbTouched)$('av-sandbox').checked=ac.sandbox!==false;
  for(const m of ['robot','avatar','sync'])$('av-'+m).style.borderColor=(avOn&&av.mode===m)?'var(--gold)':'';
  try{const lp=!!s.avatar_idle_loop;
    $('av-loop-on').style.borderColor=lp?'var(--gold)':'';
    $('av-loop-off').style.borderColor=lp?'':'var(--gold)';
    $('av-loop-state').textContent=lp?'on — captures after the next answer, then loops'
                                     :'off — parked shows one still frame (never blinks)';}catch(e){}
  for(const v of ['framed','wide','full'])$('avv-'+v).style.borderColor=((s.avatar_view||'framed')===v)?'var(--gold)':'';
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
      (d.dropped_for_budget?' <span class="raw">dropped (token budget)</span>'
        :d.body?' <span class="chip ok">full text</span>'
        :' <span class="chip" style="color:var(--warn)">summary only</span>')+
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
// 2026-09-02 voice isolator switch: state = flag file ~/.cj_stt_isolate_on (via /api/wake .isolate)
let isoHold=0;
function isoUI(iso){if(!iso||Date.now()<isoHold)return;const sw=$('iso-sw');if(!sw)return;
  sw.checked=!!iso.enabled;
  let t=iso.enabled?'ON':'OFF';
  if(iso.last)t+=' \u00b7 last: '+(iso.last.ok?'ok':'failed')+' '+(iso.last.ms/1000).toFixed(1)+' s'+(iso.last.note?' ('+iso.last.note+')':'');
  $('iso-lbl').textContent=t;}
// speaker gate switch (2026-09-02): state = ~/speaker_id/enabled + enrolled.npz (via /api/wake .speaker)
let gateHold=0;
function gateUI(sp){if(!sp||Date.now()<gateHold)return;const sw=$('gate-sw');if(!sw)return;
  const on=!!(sp.enabled&&sp.enrolled);sw.checked=on;sw.disabled=!sp.enrolled;
  let t='Gate '+(on?'ON':'OFF');
  if(!sp.enrolled)t+=' \u00b7 no voice enrolled yet';
  else if(sp.last&&sp.last.sim!=null)t+=' \u00b7 last match '+sp.last.sim.toFixed(2)+(sp.last.ok?' \u2265 ':' < ')+(sp.last.threshold||0).toFixed(2);
  $('gate-lbl').textContent=t;}
async function setGate(on){gateHold=Date.now()+3000;$('gate-lbl').textContent=on?'turning gate on\u2026':'turning gate off\u2026';
  await act(on?'gate-on':'gate-off');gateHold=0;}
async function setIso(on){isoHold=Date.now()+3000;$('iso-lbl').textContent=on?'turning on\u2026':'turning off\u2026';
  await act(on?'isolate-on':'isolate-off');isoHold=0;}
async function wakeTick(){try{renderMeters(await(await fetch('/api/meters')).json())}catch(e){}}
function renderMeters(m){try{const w=m.wake||{},st=m.stop||{};
  isoUI(w.isolate);gateUI(w.speaker);
  drawMeter(w,{now:'wakenow',bar:'wakebar',spark:'spark'},spark,'#c9a227',
            'live',st.live?'answering':'OFFLINE',0.07);
  drawMeter(st,{now:'stopnow',bar:'stopbar',spark:'stopspark'},stopspark,'#58a6ff',
            'armed',w.live?'idle':'OFFLINE',0.02);
}catch(e){}}
async function sysTick(){try{renderStatus(await(await fetch('/api/status')).json())}catch(e){}}
function renderStatus(st){try{
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
// 2026-09-01: MJPEG stream for the picture; the 2 s probe only (re)starts it / detects camera off
let camStreaming=false;
function camTick(){const img=$('cam');
  if(window.__camOff){camStreaming=false;img.removeAttribute('src');return;}
  const p=new Image();
  p.onload=()=>{if(!camStreaming){camStreaming=true;img.src='/api/camera.mjpg?t='+Date.now();}};
  p.onerror=()=>{camStreaming=false;img.removeAttribute('src');};
  p.src='/api/camera.jpg?t='+Date.now();}
// keep the wake/stop meter pair no taller than the Controls card (user: "just fitting the controls")
function fitMeters(){const c=$('controls-card'),st=document.querySelector('.stack');if(!c||!st)return;if(c.hidden||st.hidden||!c.offsetHeight){st.style.maxHeight='';return;}
  st.style.maxHeight=window.innerWidth<=760?'':c.offsetHeight+'px';}
try{new ResizeObserver(fitMeters).observe($('controls-card'));}catch(e){}
window.addEventListener('resize',fitMeters);fitMeters();
// 2026-09-01 tabs (user: "desktop friendly" too): Live / Audio / Robot / Conversation / System / Logs / All.
// Phones open on Live, desktops on All; the choice is remembered per browser. Section dividers show only in All.
// 2026-09-12 (user: "organized well", "add a Guest setting in the tab"): Guest tab; a card may
// sit in several tabs (data-tab="live audio"); section headers show in their own tab and in All.
const ICON={live:'<path d="M6 4l14 8-14 8z"/>',guest:'<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/>',
  audio:'<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6"/>',
  robot:'<rect x="4" y="7" width="16" height="12" rx="3"/><path d="M12 3v4M9 12h.01M15 12h.01M9 16h6M2 12h2M20 12h2"/>',
  conv:'<path d="M21 12a8 8 0 0 1-11.6 7.1L4 21l1.9-5.4A8 8 0 1 1 21 12z"/>',
  system:'<path d="M4 6h8M16 6h4M4 12h2M10 12h10M4 18h10M18 18h2"/><circle cx="14" cy="6" r="2"/><circle cx="8" cy="12" r="2"/><circle cx="16" cy="18" r="2"/>',
  logs:'<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h8"/>',
  all:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>'};
const TABS=[['live','Live','Live'],['guest','Guest','Guest'],['audio','Audio','Audio'],['robot','Robot','Robot'],['conv','Conversation','Chat'],['system','System','System'],['logs','Logs','Logs'],['all','All','All']];
function showTab(t){try{localStorage.setItem('cjtab',t)}catch(e){}
  document.querySelectorAll('#tabs button').forEach(b=>{b.classList.toggle('on',b.dataset.t===t);b.setAttribute('aria-selected',b.dataset.t===t)});
  document.querySelectorAll('.grid > [data-tab]').forEach(el=>{el.hidden=(t!=='all'&&!el.dataset.tab.split(' ').includes(t))});
  try{fitMeters()}catch(e){}
  try{if(window.__booted){poll();wakeTick();camTick();}}catch(e){}}
(function(){const bar=$('tabs');if(!bar)return;TABS.forEach(([k,l,sh])=>{const b=document.createElement('button');b.type='button';b.setAttribute('role','tab');b.dataset.t=k;
    b.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true">'+(ICON[k]||'')+'</svg><span class="long">'+l+'</span><span class="short">'+sh+'</span>';b.onclick=()=>showTab(k);bar.appendChild(b)});
  let t=null;try{t=localStorage.getItem('cjtab')}catch(e){}
  if(!t||!TABS.some(x=>x[0]===t))t=window.innerWidth<=760?'live':'all';showTab(t);})();
// 2026-09-12 push: /api/events streams state / meters / status the moment they change (Server-Sent
// Events). The 500 ms / 300 ms / 5 s polls below only run while the stream is not connected, so a
// dashboard restart or a flaky link degrades to the old behaviour instead of a blank page. A hidden
// tab closes the stream (no server thread for it) and reopens on return.
const vis=id=>{const el=$(id);return !!(el&&el.offsetParent!==null)};
let LAST_S=null,LAST_AT=0,ES=null,ES_OK=false;
function pushOpen(){if(ES||!window.EventSource)return;try{ES=new EventSource('/api/events');}catch(e){ES=null;return;}
  ES.onopen=()=>{ES_OK=true;};
  ES.onerror=()=>{ES_OK=false;};                 // EventSource reconnects by itself; polling covers the gap
  ES.addEventListener('state',e=>{try{render(JSON.parse(e.data))}catch(x){}});
  ES.addEventListener('meters',e=>{try{if(vis('wakebar'))renderMeters(JSON.parse(e.data))}catch(x){}});
  ES.addEventListener('status',e=>{try{renderStatus(JSON.parse(e.data))}catch(x){}});}
function pushClose(){if(ES){try{ES.close()}catch(e){}ES=null;}ES_OK=false;}
pushOpen();
setInterval(()=>{if(!document.hidden&&!ES_OK)poll()},500);poll();
setInterval(()=>{if(!document.hidden&&!ES_OK&&vis('wakebar'))wakeTick()},300);wakeTick();
setInterval(()=>{if(!document.hidden&&!ES_OK)sysTick()},5000);sysTick();
setInterval(()=>{if(!document.hidden&&ES_OK&&LAST_S){try{renderMode(Object.assign({},LAST_S,{ts:LAST_S.ts+(Date.now()-LAST_AT)/1000}))}catch(e){}}},1000);
setInterval(()=>{if(!document.hidden&&vis('cam'))camTick()},2000);camTick();loadOv();loadLogs();vidList();vidSnd(VID_SND);
document.addEventListener('visibilitychange',()=>{if(document.hidden)pushClose();else{pushOpen();poll();wakeTick();camTick();}});
window.__booted=true;
// ── Connectivity (WiFi / Bluetooth) — same endpoints as the ops page ──
let _nets=[],_bts=[],_watchdog=false;
function netFromStatus(st){const wf=st.wifi||{};
  $('wifinow').innerHTML=wf.essid?chip(esc(wf.essid),true,esc(wf.signal_dbm||'?')+' dBm · '+esc(wf.ip||'?')):chip('no wifi',false,'');
  _watchdog=((st.services||{})['speaker-watchdog']||{}).active==='active';
  const sp=(st.audio||{}).speakers||{},route=(st.audio||{}).route||'?';
  $('btnow').innerHTML=chip('route',true,esc(route))+Object.entries(sp).map(([n,c])=>chip(n,c,c?'connected':'off')).join('');}
function netRow(left,right,onclick){return '<div style="display:flex;justify-content:space-between;gap:10px;padding:8px 6px;border-bottom:1px solid var(--line);cursor:pointer" onclick="'+onclick+'"><span>'+left+'</span><span class="dim">'+right+'</span></div>'}
async function wifiScan(){$('wifi-list').textContent='scanning (a few seconds)…';
  try{const w=await(await fetch('/api/wifi?rescan=1')).json();_nets=w.networks||[];
    $('wifinow').textContent=w.hotspot?'setup hotspot':(w.current?'on '+w.current:'not connected');
    if(w.hotspot&&!_nets.length){$('wifi-list').textContent='setup hotspot active — scanning unavailable; type the network below';return}
    if(!_nets.length){$('wifi-list').textContent='no networks found';return}
    $('wifi-list').innerHTML=_nets.map((n,i)=>{const bars=n.signal>66?'▂▄▆':n.signal>33?'▂▄':'▂';
      const tag=n.in_use?' — connected':(n.saved?' (saved)':'');const lock=n.security==='open'?'':' 🔒';
      return netRow((n.in_use?'✅ ':'')+esc(n.ssid)+lock+'<span class="dim">'+tag+'</span>',bars+' '+n.signal+'%','wifiJoinIdx('+i+')')}).join('');
  }catch(e){$('wifi-list').textContent='scan failed: '+e.message}}
async function wifiSend(ssid,password,hidden){
  if(!confirm('Switch the robot to "'+ssid+'"? This page will drop until your phone is on the same network.'))return;
  $('netmsg').textContent='switching to '+ssid+'… (up to a minute)';
  try{const r=await(await fetch('/api/wifi/connect',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ssid,password,hidden:!!hidden})})).json();
    $('netmsg').textContent=r.ok?(r.output||('now on '+ssid)):'FAILED — '+(r.output||'');
  }catch(e){$('netmsg').textContent='dashboard dropped — rejoin '+ssid+' on your phone and reload'}}
function wifiJoinIdx(i){const n=_nets[i];if(!n)return;let pw=null;
  if(!(n.saved||n.security==='open')){pw=prompt('Password for "'+n.ssid+'" (leave empty if open):');if(pw===null)return}
  wifiSend(n.ssid,pw)}
function wifiManual(){const ssid=$('wm-ssid').value.trim(),pw=$('wm-pw').value;
  if(!ssid){$('netmsg').textContent='enter a network name';return}wifiSend(ssid,pw||null,$('wm-hidden').checked)}
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
