"""/console — operator console for the two-robot installation (2026-09-10).

One page, one poll (/api/state every second). The floor selector is the
primary element; everything else is secondary. Copy is written for a
technician in a dim room under time pressure: plain words, no jargon.
The model lives in console.py; this page only renders and posts.
"""
import ui_common as _c
globals().update({k: v for k, v in vars(_c).items() if not k.startswith("__")})

CONSOLE_PAGE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CJAP Operator Console</title><style>
:root{--bg:#0b0f14;--card:#141a22;--line:#2a333f;--text:#e9eef4;--dim:#9aa7b6;--amber:#e0b23a;
 --green:#42c26b;--red:#ff5c5c;--blue:#5aa9ff;--focus:#ffffff}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0;
 padding:14px 16px 40px;font-size:16px;line-height:1.35}
h1{font-size:20px;margin:0 0 4px;color:var(--amber);display:flex;align-items:center;gap:12px;flex-wrap:wrap}
h2{font-size:15px;margin:0 0 10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px;align-items:start}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.card.wide{grid-column:1/-1}
.sub{color:var(--dim);font-size:14px;margin:0 0 10px}
button{font:inherit;color:var(--text);background:#1d2530;border:1px solid var(--line);border-radius:10px;
 padding:10px 14px;cursor:pointer;min-height:44px}
button:hover{background:#243040}
button:disabled{opacity:.45;cursor:default}
button:focus-visible,input:focus-visible,[role=switch]:focus-visible,select:focus-visible{outline:3px solid var(--focus);outline-offset:3px}
/* floor selector — the primary element */
#floor{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.fbtn{display:flex;flex-direction:column;align-items:flex-start;gap:6px;padding:16px;min-height:132px;
 border-width:2px;text-align:left;background:#161d27}
.fbtn .who{font-size:22px;font-weight:700}
.fbtn .role{color:var(--dim);font-size:14px}
.fbtn.sel{border-color:var(--amber);background:#2a2412}
.fbtn.sel .who{color:var(--amber)}
.fbtn.moving{border-style:dashed}
.pill{display:inline-block;padding:3px 10px;border-radius:999px;font-size:13px;border:1px solid var(--line);color:var(--dim)}
.pill.open{color:#0b0f14;background:var(--green);border-color:var(--green);font-weight:700}
.pill.closed{color:var(--dim)}
.pill.unknown{color:var(--amber);border-color:var(--amber)}
.pill.bad{color:#0b0f14;background:var(--red);border-color:var(--red);font-weight:700}
.fbtn .obs{margin-top:auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:14px}
.banner{border-radius:12px;padding:12px 14px;margin:12px 0 0;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.banner.info{background:#15233a;border:1px solid #2b4a7a}
.banner.warn{background:#3a2d12;border:1px solid #7a5a1c}
.banner.bad{background:#3a1616;border:1px solid #7a2b2b}
.banner b{font-size:16px}
#warnings:empty{display:none}
#warnings .banner{margin-top:8px}
/* mode / profile */
.seg{display:flex;gap:8px;flex-wrap:wrap}
.seg button{flex:1;min-width:120px;border-width:2px}
.seg button.sel{border-color:var(--amber);color:var(--amber);background:#2a2412}
.hint{color:var(--dim);font-size:13px;margin-top:6px}
/* settings */
.row{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;padding:10px 0;border-top:1px solid var(--line)}
.row:first-of-type{border-top:0}
.row label,.row .lbl{font-size:16px}
.row .help{color:var(--dim);font-size:13px}
.row .src{font-size:12px;color:var(--dim);margin-top:2px}
.row .src.override{color:var(--amber)}
.row input[type=number]{font:inherit;width:120px;padding:8px 10px;border-radius:8px;border:1px solid var(--line);
 background:#0f141b;color:var(--text)}
[role=switch]{width:66px;height:36px;border-radius:18px;position:relative;padding:0;background:#222b36}
[role=switch] i{position:absolute;top:3px;left:4px;width:28px;height:28px;border-radius:14px;background:var(--dim);transition:left .15s}
[role=switch][aria-checked=true]{background:#1f3b27;border-color:var(--green)}
[role=switch][aria-checked=true] i{left:32px;background:var(--green)}
.meter{height:8px;background:#0f141b;border-radius:4px;overflow:hidden;margin-top:6px;position:relative}
.meter i{display:block;height:100%;background:var(--blue);width:0;transition:width .3s}
.meter b{position:absolute;top:-3px;width:2px;height:14px;background:var(--amber)}
.rmsline{font-size:13px;color:var(--dim);margin-top:4px}
.rmsline.warn{color:var(--amber)}
.actions{display:flex;gap:10px;margin-top:12px;flex-wrap:wrap}
.primary{background:#3b3010;border-color:var(--amber);color:var(--amber);font-weight:700}
.danger{border-color:var(--red);color:#ffb3b3}
/* locked */
.lock{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:center;padding:9px 0;border-top:1px solid var(--line)}
.lock:first-of-type{border-top:0}
.lock .st{font-weight:700;min-width:44px}
.lock .st.on{color:var(--green)} .lock .st.off{color:var(--red)}
.lock small{display:block;color:var(--dim);font-size:12px}
#unlockbox{margin-top:10px;display:none;gap:8px;flex-wrap:wrap;align-items:center}
#unlockbox.show{display:flex}
#unlockbox input{flex:1;min-width:220px;font:inherit;padding:9px 10px;border-radius:8px;border:1px solid var(--line);background:#0f141b;color:var(--text)}
/* journal */
#journal{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;max-height:320px;overflow:auto;
 background:#0f141b;border-radius:10px;padding:8px 10px;border:1px solid var(--line)}
#journal div{padding:2px 0;white-space:pre-wrap;word-break:break-word}
#journal .k{color:var(--amber);display:inline-block;min-width:110px}
#journal .t{color:var(--dim);margin-right:8px}
#journal .unlock-request .k{color:var(--red)}
/* robots strip */
.robots{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.robot{background:#0f141b;border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-size:14px}
.robot b{display:block;font-size:15px;margin-bottom:4px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;color:var(--dim)}
.kv span:nth-child(even){color:var(--text)}
#status{font-size:13px;color:var(--dim);margin-left:auto}
#status.bad{color:var(--red);font-weight:700}
.toast{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);background:#1d2530;border:1px solid var(--line);
 border-radius:10px;padding:10px 16px;font-size:14px;display:none;max-width:90vw}
.toast.show{display:block}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
@media (max-width:720px){#floor{grid-template-columns:1fr}.robots{grid-template-columns:1fr}}
</style></head><body>
<h1>CJAP Operator Console
 <span class="pill" id="modechip">…</span><span class="pill" id="profchip">…</span>
 <span id="status">connecting…</span></h1>
<p class="sub">Only one microphone can be open at a time. Pick who has the floor; the robots follow within a second and close on their own if this page's server goes away.</p>

<div class="card wide">
 <h2>Who has the floor</h2>
 <div id="floor" role="group" aria-label="Who has the floor">
  <button class="fbtn" id="f-alpha" onclick="setFloor('alpha')"><span class="who">Panganiban</span><span class="role">robot cj-alpha · composes answers live</span><span class="obs"><span class="pill" id="o-alpha">no report</span><span id="r-alpha"></span></span></button>
  <button class="fbtn" id="f-beta" onclick="setFloor('beta')"><span class="who">Host</span><span class="role">robot cj-beta · intro line, then silent</span><span class="obs"><span class="pill" id="o-beta">no report</span><span id="r-beta"></span></span></button>
  <button class="fbtn" id="f-none" onclick="setFloor('none')"><span class="who">No one</span><span class="role">both microphones closed</span><span class="obs"><span class="pill" id="o-none">closed</span></span></button>
 </div>
 <div id="transition"></div>
 <div id="pending"></div>
 <div id="warnings" aria-live="polite"></div>
</div>

<div class="grid">
 <div class="card">
  <h2>Mode</h2>
  <div class="seg" role="group" aria-label="Mode">
   <button id="m-duet" onclick="setMode('duet')">Duet<br><small>pre-recorded exchange · no mic anywhere</small></button>
   <button id="m-direct" onclick="setMode('direct')">Direct<br><small>a visitor talks to Panganiban</small></button>
  </div>
  <div class="hint">Choosing Duet closes every microphone and keeps them closed.</div>
  <h2 style="margin-top:16px">Profile</h2>
  <div class="seg" role="group" aria-label="Profile">
   <button id="p-kiosk" onclick="setProfile('kiosk')">Kiosk<br><small>museum floor, self-service</small></button>
   <button id="p-event" onclick="setProfile('event')">Event<br><small>emcee-driven hall · no wake word · louder room · no follow-up window</small></button>
  </div>
  <div class="hint">Profiles come from <code>config/modes/*.json</code>. Your changes below sit on top of the profile and are marked as such.</div>
  <div class="hint" id="introline"></div>
 </div>

 <div class="card">
  <h2>Listening settings</h2>
  <div id="settings"></div>
  <div class="actions"><button class="primary" onclick="applySettings()">Apply</button><button onclick="resetOverrides()">Back to profile values</button></div>
 </div>

 <div class="card">
  <h2>Locked — cannot be changed here</h2>
  <p class="sub">These keep him truthful. Their state is shown; a change can only be requested and the request is logged.</p>
  <div id="locked"></div>
  <div id="unlockbox"><span id="unlockfor"></span><input id="unlockreason" placeholder="Why? (logged, nothing changes)" aria-label="Reason for the unlock request"><button onclick="sendUnlock()">Log request</button><button onclick="hideUnlock()">Cancel</button></div>
 </div>

 <div class="card">
  <h2>Robots</h2>
  <div class="robots"><div class="robot" id="rb-alpha"></div><div class="robot" id="rb-beta"></div></div>
  <div class="hint">“Reports” is what the robot says its own microphone is doing, read from the robot every second — not what this page last asked for.</div>
 </div>

 <div class="card wide">
  <h2>Journal <span class="hint" style="display:inline">floor · mode · profile · settings · unlock requests</span></h2>
  <div id="journal" aria-live="polite"></div>
 </div>
</div>
<div class="toast" id="toast" role="status"></div>
<script>
const KEY=new URLSearchParams(location.search).get('key')||localStorage.getItem('cjkey')||'';
if(KEY)localStorage.setItem('cjkey',KEY);
let S=null,SCHEMA=null,EDITED={},lastJournalN=0,failures=0;
const $=id=>document.getElementById(id);
const esc=t=>String(t==null?'':t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
function toast(msg,bad){const t=$('toast');t.textContent=msg;t.className='toast show'+(bad?' bad':'');clearTimeout(t._h);t._h=setTimeout(()=>t.className='toast',3500);}
async function post(path,body){
  body=Object.assign({key:KEY,who:'console@'+(localStorage.getItem('cjwho')||'operator')},body||{});
  try{const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const d=await r.json();toast(d.output||(d.ok?'done':'failed'),!d.ok);poll();return d;}
  catch(e){toast('server not reachable: '+e,true);return{ok:false};}
}
function setFloor(f){post('/api/floor',{floor:f});}
function setMode(m){post('/api/config',{mode:m});}
function setProfile(p){post('/api/config',{profile:p});}
function cutShort(){if(confirm('Cut the current answer short and apply the queued change now?'))post('/api/pending',{action:'cut'});}
function cancelPending(){post('/api/pending',{action:'cancel'});}
function pillFor(o){
  if(!o.fresh)return['unknown','no report'+(o.age_s!=null?' for '+Math.round(o.age_s)+' s':'')];
  if(o.mic===true)return[o.intended==='open'?'open':'bad','mic OPEN'+(o.intended==='open'?'':' — should be closed')];
  if(o.mic===false)return[o.intended==='open'?'unknown':'closed','mic closed'+(o.intended==='open'?' — should be open':'')];
  return['unknown','mic state unknown'];
}
function renderFloor(s){
  const target=s.floorTarget||s.floor;
  for(const f of['alpha','beta','none']){const b=$('f-'+f);b.className='fbtn'+(target===f?' sel':'')+(s.transition&&s.transition.target===f?' moving':'');b.setAttribute('aria-pressed',target===f);
    b.disabled=(s.mode==='duet'&&f!=='none');}
  for(const r of['alpha','beta']){const o=s.observed[r]||{};const[c,t]=pillFor(o);const p=$('o-'+r);p.className='pill '+c;p.textContent=t;
    const rms=s.rms&&s.rms[r];$('r-'+r).textContent=rms!=null?'room '+Math.round(rms):'';}
  const tr=$('transition');
  if(s.transition){const t=s.transition;tr.innerHTML='<div class="banner info"><b>Closing both microphones…</b> then opening '+(t.target==='alpha'?'Panganiban':'Host')+' (waits up to '+t.settle_s+' s for both to confirm; '+t.elapsed_s+' s so far)</div>';}
  else tr.innerHTML='';
  const pd=$('pending');
  if(s.pending){const w=(s.pending.waiting_on||[]).map(r=>r==='alpha'?'Panganiban':'Host').join(' and ')||'the answer';
    pd.innerHTML='<div class="banner warn"><b>Queued:</b> '+esc(s.pending.what)+' — waiting for '+esc(w)+' to finish the answer ('+s.pending.queued_s+' s). <button class="danger" onclick="cutShort()">Cut the answer short and apply now</button><button onclick="cancelPending()">Cancel</button></div>';}
  else pd.innerHTML='';
  const wl=$('warnings');wl.innerHTML=(s.warnings||[]).filter(w=>w.level!=='info').map(w=>'<div class="banner '+(w.level==='bad'?'bad':'warn')+'">'+esc(w.msg)+'</div>').join('');
}
function renderMode(s){
  for(const m of['duet','direct']){const b=$('m-'+m);b.className=s.mode===m?'sel':'';b.setAttribute('aria-pressed',s.mode===m);}
  for(const p of['kiosk','event']){const b=$('p-'+p);b.className=s.profile===p?'sel':'';b.setAttribute('aria-pressed',s.profile===p);}
  $('modechip').textContent=(s.mode||'?')+' mode';$('profchip').textContent=(s.profile||'?')+' profile';
  $('introline').textContent=s.hostIntroText?'Host intro line: “'+s.hostIntroText+'”':'';
}
function srcClass(src){return src==='console override'?'src override':'src';}
function renderSettings(s){
  const st=s.settings,eff=st.effective||{},src=st.sources||{};SCHEMA=st.schema||{};
  const box=$('settings');
  if(box.dataset.built!=='1'){
    box.innerHTML=(st.tunable||[]).map(k=>{const sc=SCHEMA[k]||{};
      const ctl=sc.type==='bool'
        ?'<button role="switch" aria-checked="false" id="in-'+k+'" onclick="flip(\''+k+'\')" aria-labelledby="lb-'+k+'"><i></i></button>'
        :'<input type="number" id="in-'+k+'" min="'+sc.min+'" max="'+sc.max+'" step="'+sc.step+'" oninput="EDITED[\''+k+'\']=1" aria-labelledby="lb-'+k+'">';
      const extra=k==='speech_threshold'?'<div class="meter" id="mt-alpha"><i></i><b></b></div><div class="rmsline" id="ml-alpha"></div><div class="meter" id="mt-beta"><i></i><b></b></div><div class="rmsline" id="ml-beta"></div>':'';
      return '<div class="row"><div><div class="lbl" id="lb-'+k+'">'+esc(sc.label||k)+'</div><div class="help">'+esc(sc.help||'')+'</div><div class="'+srcClass('')+'" id="src-'+k+'"></div>'+extra+'</div><div>'+ctl+'</div></div>';}).join('');
    box.dataset.built='1';
  }
  for(const k of st.tunable||[]){const sc=SCHEMA[k]||{},el=$('in-'+k);if(!el)continue;
    if(!EDITED[k]){if(sc.type==='bool')el.setAttribute('aria-checked',eff[k]?'true':'false');else if(document.activeElement!==el)el.value=eff[k];}
    const sp=$('src-'+k);sp.className=srcClass(src[k]);sp.textContent='now '+(sc.type==='bool'?(eff[k]?'on':'off'):eff[k])+' · from '+(src[k]||'?');}
  for(const r of['alpha','beta']){const m=$('mt-'+r),l=$('ml-'+r);if(!m)continue;const rms=s.rms&&s.rms[r],o=s.observed[r]||{};
    const thr=o.speech_threshold||Math.min(Math.max(Math.round((rms||0)*(eff.speech_threshold_mult||1)),eff.speech_threshold||0),eff.speech_threshold_cap||1e9);
    const max=Math.max(2000,thr*1.3,(rms||0)*1.3);m.querySelector('i').style.width=(rms!=null?Math.min(100,100*rms/max):0)+'%';m.querySelector('b').style.left=Math.min(100,100*thr/max)+'%';
    const gap=rms!=null?thr-rms:null;l.className='rmsline'+(gap!=null&&gap<400?' warn':'');
    l.textContent=(r==='alpha'?'Panganiban':'Host')+': '+(rms!=null?'room '+Math.round(rms)+' · talking counts from '+thr+(gap<400?' — only '+gap+' apart, too close':''):'no room level reported');}
}
function flip(k){const el=$('in-'+k);el.setAttribute('aria-checked',el.getAttribute('aria-checked')==='true'?'false':'true');EDITED[k]=1;}
function applySettings(){const out={};for(const k of Object.keys(EDITED)){const el=$('in-'+k),sc=SCHEMA[k]||{};out[k]=sc.type==='bool'?el.getAttribute('aria-checked')==='true':Number(el.value);}
  if(!Object.keys(out).length){toast('nothing changed');return;}EDITED={};post('/api/config',{settings:out});}
function resetOverrides(){const out={};for(const k of Object.keys(SCHEMA||{}))if((SCHEMA[k]||{}).ui)out[k]=null;EDITED={};post('/api/config',{settings:out});}
let unlockGate=null;
function renderLocked(s){const L=s.locked||{};$('locked').innerHTML=Object.keys(L).map(g=>{const x=L[g];return '<div class="lock"><span class="st '+(x.on?'on':'off')+'">'+(x.on?'ON':'OFF')+'</span><span>'+esc(x.label)+'<small>'+esc(x.how)+' · from '+esc(x.source)+'</small></span><button onclick="askUnlock(\''+g+'\',\''+esc(x.label).replace(/'/g,'')+'\')">Request unlock</button></div>';}).join('');}
function askUnlock(g,label){unlockGate=g;$('unlockfor').textContent='Unlock “'+label+'”:';$('unlockbox').className='show';$('unlockreason').focus();}
function hideUnlock(){unlockGate=null;$('unlockbox').className='';$('unlockreason').value='';}
async function sendUnlock(){const r=$('unlockreason').value.trim();if(!unlockGate)return;const d=await post('/api/unlock-request',{gate:unlockGate,reason:r});if(d.ok)hideUnlock();}
function renderRobots(s){for(const r of['alpha','beta']){const o=s.observed[r]||{};const box=$('rb-'+r);
  const rows=[['reports',o.fresh?'yes ('+o.age_s+' s ago)':'NO'+(o.age_s!=null?' — last '+Math.round(o.age_s)+' s ago':' — never')],
    ['should be',o.intended],['mic is',o.mic==null?'unknown':(o.mic?'open':'closed')],['holds lease',o.has_floor==null?'?':(o.has_floor?'yes':'no')],
    ['answering',o.turn_active==null?'?':(o.turn_active?'yes':'no')],['speaking',o.speaking==null?'?':(o.speaking?'yes':'no')],
    ['room level',s.rms&&s.rms[r]!=null?Math.round(s.rms[r]):'—'],['boot',(o.boot_id||'').slice(-14)||'—']];
  box.innerHTML='<b>'+(r==='alpha'?'Panganiban (cj-alpha)':'Host (cj-beta)')+'</b><div class="kv">'+rows.map(([k,v])=>'<span>'+k+'</span><span>'+esc(v)+'</span>').join('')+'</div>';}}
async function loadJournal(){try{const r=await fetch('/api/journal?n=40&key='+encodeURIComponent(KEY));const d=await r.json();const rows=(d.rows||[]).filter(x=>['floor','mode','profile','settings','unlock-request','queued','drain','interrupt','intro','restore','config-warning'].includes(x.kind));
  $('journal').innerHTML=rows.slice().reverse().map(x=>'<div class="'+x.kind+'"><span class="t">'+new Date(x.ts*1000).toLocaleTimeString()+'</span><span class="k">'+esc(x.kind)+'</span>'+esc(x.msg)+(x.who?' <span class="t">— '+esc(x.who)+'</span>':'')+'</div>').join('')||'<div class="t">nothing yet</div>';}catch(e){}}
async function poll(){try{const r=await fetch('/api/state');const s=await r.json();failures=0;S=s;
  if(s.console_error){$('status').className='bad';$('status').textContent='console error: '+s.console_error;return;}
  $('status').className='';$('status').textContent='live · lease '+s.leaseTtl+' s · '+new Date().toLocaleTimeString();
  renderFloor(s);renderMode(s);renderSettings(s);renderLocked(s);renderRobots(s);
  const n=(s.seq&&(s.seq.config+s.seq.intro+(s.seq.interrupt.alpha||0)+(s.seq.interrupt.beta||0)))||0;if(n!==lastJournalN){lastJournalN=n;loadJournal();}
 }catch(e){failures++;$('status').className='bad';$('status').textContent='NOT REACHABLE ('+failures+') — robots close their mics 3 s after they stop hearing this server';}}
poll();setInterval(poll,1000);loadJournal();setInterval(loadJournal,5000);
</script></body></html>
"""
