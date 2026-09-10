"""/event — emcee question buttons page (+ EVENT_PAGE template).

Split out of supervaise_ui.py on 2026-08-29 (shared names star-copied from
ui_common so page code reads exactly as before; ui_routes is the facade).
"""
import ui_common as _c
globals().update({k: v for k, v in vars(_c).items() if not k.startswith("__")})


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
