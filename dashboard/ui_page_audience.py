"""/audience — gallery-exhibit audience page (shared EXHIBIT_* pieces live here).

Split out of supervaise_ui.py on 2026-08-29 (shared names star-copied from
ui_common so page code reads exactly as before; ui_routes is the facade).
"""
import ui_common as _c
globals().update({k: v for k, v in vars(_c).items() if not k.startswith("__")})


# Shared "gallery exhibit" look (2026-08-25): /audience and /face-avatar render
# the same gilt frame + two ivory plaques; only the framed content differs
# (live camera vs the HeyGen avatar video).
EXHIBIT_CSS = """:root{--wall:#1c1916;--ink:#2b2418;--ink2:#5a4d3a;--faint:#8a7b64;--ivory:#f4eddc;--ivory2:#eadfc6;
  --maroon:#6e1f2b;--maroon2:#8b2a38;--brass:#c9a961;--brass2:#8f7332;--ok:#4f7d4a;--warn:#a8642a;--blue:#3b5b8a}
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;color:var(--ink);overflow:hidden;
  font-family:'EB Garamond',Georgia,'Times New Roman',serif;
  /* gallery wall: warm charcoal with a spotlight falling on the portrait */
  background:var(--wall) radial-gradient(ellipse 58% 52% at 50% 34%,rgba(214,190,140,.22) 0%,rgba(214,190,140,.07) 45%,rgba(0,0,0,0) 72%)}
/* the portrait: a gilt frame around the live camera. knobs ?cam=<vw> ?pos=tr|tl */
#cam{position:fixed;top:5.5vh;left:50%;transform:translateX(-50%);
  width:min(44vw,calc(58vh * 16 / 9));aspect-ratio:16/9;background:#000;overflow:hidden;
  /* gallery frame: bevelled gilt moulding, ivory linen mat, dark liners */
  border:1.3vh solid #b8944f;
  border-image:linear-gradient(160deg,#f3e4b4 0%,#c8a55c 18%,#8f7332 34%,#e6cf8f 50%,#a5813f 66%,#f0dda6 84%,#8a6d2c 100%) 1;
  box-shadow:0 0 0 .3vh #2a2115,0 0 0 1.6vh #efe4c8,0 0 0 1.9vh #6b5323,0 0 0 2.1vh #d9c07a,
    0 3.5vh 9vh rgba(0,0,0,.8),inset 0 0 0 .45vh #12100c;
  transition:box-shadow .8s ease}
#cam.live{box-shadow:0 0 0 .3vh #2a2115,0 0 0 1.6vh #efe4c8,0 0 0 1.9vh #6b5323,0 0 0 2.1vh #d9c07a,
    0 3.5vh 9vh rgba(0,0,0,.8),0 0 8vh 1.5vh rgba(230,200,130,.3),inset 0 0 0 .45vh #12100c}
#cam.tr,#cam.tl{transform:none;left:auto;top:5vh;width:min(30vw,calc(34vh * 16 / 9))}
#cam.tr{right:2vw}  #cam.tl{left:2vw}
#cam img{width:100%;height:100%;object-fit:cover;object-position:center;display:block}
#cam .idle{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;
  justify-content:center;color:#cbb98f;font-size:2.4vh;gap:1.2vh;letter-spacing:.06em;
  background:radial-gradient(ellipse at 50% 40%,#2a241b,#120f0b 75%)}
#cam .idle b{font-family:'Playfair Display',Georgia,serif;color:var(--brass);font-size:5.5vh;letter-spacing:.24em;font-weight:500}
/* floor shadow under the plaques */
#scrim{position:fixed;left:0;right:0;bottom:0;height:30vh;pointer-events:none;
  background:linear-gradient(to top,rgba(0,0,0,.3),rgba(0,0,0,0))}
/* the two exhibit plaques: question left, answer right, levelled */
#bar{position:fixed;left:2vw;right:2vw;bottom:2.6vh;display:flex;justify-content:space-between;
  align-items:stretch;gap:2vw;pointer-events:none}
/* plaques (2026-08-25, user): no outline/ring, ivory fades top -> bottom.
   Bottom stop stays ~.45 so the dark ink is still readable over the wall;
   fading to 0 would need light ink. */
.card{min-width:0;min-height:22vh;max-height:42vh;display:flex;flex-direction:column;
  padding:2vh 1.8vw 3vh;border-radius:.6vh;color:var(--ink);
  background:linear-gradient(180deg,rgba(247,241,227,.97) 0%,rgba(244,237,220,.9) 35%,
    rgba(234,223,198,.7) 70%,rgba(234,223,198,.45) 100%);
  box-shadow:none;border:0;
  transition:opacity .6s ease,transform .6s cubic-bezier(.2,.8,.2,1)}
#qbox{flex:0 1 42%} #abox{flex:0 1 46%}
.card.hide{opacity:0;transform:translateY(3vh);pointer-events:none}
.card h3{flex:0 0 auto;display:flex;align-items:center;gap:1vw;margin-bottom:1.3vh;
  font-family:'Playfair Display',Georgia,serif;font-weight:500;font-size:1.7vh;
  letter-spacing:.24em;text-transform:uppercase;color:var(--maroon)}
.card h3::after{content:'';flex:1;height:1px;background:linear-gradient(90deg,var(--brass2),rgba(143,115,50,0))}
.card h3.big{font-size:2.2vh;font-weight:600;color:#4f121c;letter-spacing:.26em}
.row.q{background:none;padding:0 0 .6vh 0;grid-template-columns:minmax(0,1fr) auto}
.row.q .qt{font-size:2.7vh;line-height:1.35;color:#1e1810;font-weight:600}
/* answer */
#a{flex:1;min-height:9vh;overflow-y:auto;scrollbar-width:none;text-align:left;
  font-size:3vh;line-height:1.5;color:var(--ink)}
#a::-webkit-scrollbar{display:none}
#a span{color:var(--ink2);transition:color .5s}
#a .cur{color:var(--maroon);animation:rise .45s ease-out}
#a.idle-text,#qidle{display:flex;flex-wrap:wrap;align-items:center;row-gap:.6vh;font-style:italic;
  color:var(--faint);font-size:2.6vh;line-height:1.5}
#a.idle-text em,#qidle em{color:var(--maroon);font-style:normal;padding:0 .4vw;white-space:nowrap}
/* opening display (2026-08-26, user): the wake phrases show on BOTH plaques */
#qidle{display:none;flex:1} #qbox.idle #qidle{display:flex}
#qbox.idle #qtext,#qbox.idle #rows{display:none}
.rise{animation:rise .45s ease-out}
@keyframes rise{from{opacity:0;transform:translateY(1.2vh)}to{opacity:1;transform:none}}
.think::after{content:'';animation:dots 1.5s steps(4,end) infinite}
@keyframes dots{0%{content:''}25%{content:'.'}50%{content:'..'}75%{content:'...'}}
@keyframes blink{50%{opacity:.25}}
/* question intake rows — exhibit provenance lines */
/* the transcribed question is PINNED above the scrolling pipeline rows (2026-08-25):
   it used to be the first row of #rows and scrolled out of view once the
   Scope/Routed/Composed/Fidelity rows pushed the container to its max height. */
#qtext{flex:0 0 auto;max-height:16vh;overflow-y:auto;scrollbar-width:none}
#qtext::-webkit-scrollbar{display:none}
#rows{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;gap:.7vh;overflow-y:auto;scrollbar-width:none}
#rows::-webkit-scrollbar{display:none}
.row{display:grid;grid-template-columns:2.4vh minmax(0,1fr) auto;gap:.2vh .8vw;align-items:start;
  padding:.9vh 1vw;border-radius:.4vh;background:rgba(120,95,50,.07);animation:rise .45s ease-out}
.row.done{background:rgba(79,125,74,.09)} .row.active{background:rgba(201,169,97,.16)}
.row.flagged{background:rgba(168,100,42,.14)}
.row .ck{font-size:1.9vh;line-height:1.35;text-align:center;color:var(--faint)}
.row.done .ck{color:var(--ok)} .row.flagged .ck{color:var(--warn)}
.row.active .ck{color:var(--brass2);animation:blink 1.1s ease-in-out infinite}
.row .b{min-width:0;font-size:1.9vh;line-height:1.4;color:var(--ink)}
.row .lb{font-family:'Playfair Display',Georgia,serif;font-size:1.3vh;letter-spacing:.18em;
  text-transform:uppercase;color:var(--maroon);margin-right:.6vw;white-space:nowrap}
.row.active .lb{color:var(--brass2)} .row.done .lb{color:var(--maroon)} .row.flagged .lb{color:var(--warn)}
.row .t{font-family:'EB Garamond',Georgia,serif;font-variant-numeric:tabular-nums;font-size:1.5vh;
  color:var(--faint);padding-top:.3vh;white-space:nowrap}
.row code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:1.55vh;padding:.15vh .6vh;
  border-radius:.4vh;background:rgba(79,125,74,.14);color:#2f5a2b}
.row .conf{color:var(--blue);font-size:1.6vh}
.row .rs{display:-webkit-box;color:var(--ink2);font-size:1.65vh;line-height:1.35;margin-top:.3vh;
  overflow:hidden;-webkit-line-clamp:3;-webkit-box-orient:vertical}
.row .qt{font-family:'Playfair Display',Georgia,serif;font-weight:500;font-size:2.1vh;color:var(--ink)}
/* state pill (2026-08-25, user; shared with /face-avatar 2026-09-04): green =
   listening, gold = thinking, red waveform = speaking (follows the sentence
   audio), gray = idle, red = muted. Only rendered on pages that include
   EXHIBIT_PILL; ?pos=tl moves it to the right so it clears the portrait. */
#rs{position:fixed;top:2.4vh;left:2vw;z-index:5;display:flex;align-items:center;gap:1vw;
  padding:1vh 1.5vw;border-radius:999px;background:rgba(20,16,12,.74);
  border:1px solid rgba(201,169,97,.45);box-shadow:0 .6vh 2vh rgba(0,0,0,.5);pointer-events:none;
  font-family:'Playfair Display',Georgia,serif;letter-spacing:.2em;text-transform:uppercase;
  font-size:1.6vh;color:#e8dcc0;transition:border-color .3s}
#rs.tr{left:auto;right:2vw}
#rs .dot{width:2.2vh;height:2.2vh;border-radius:50%;background:#7a7368;flex:0 0 auto;
  box-shadow:0 0 0 .3vh rgba(255,255,255,.08);transition:background .3s,box-shadow .3s}
#rs.listening .dot{background:#3fb950;box-shadow:0 0 1.6vh .2vh rgba(63,185,80,.55);animation:rspulse 1.2s ease-in-out infinite}
#rs.listening{border-color:rgba(63,185,80,.6)}
#rs.thinking .dot{background:#c9a961;box-shadow:0 0 1.2vh .1vh rgba(201,169,97,.5);animation:rspulse 1.2s ease-in-out infinite}
#rs.muted .dot{background:#e5484d;box-shadow:0 0 1.6vh .2vh rgba(229,72,77,.55)}
#rs.muted{border-color:rgba(229,72,77,.6)}
#rs.talking .dot{display:none}
#rs canvas{display:none;height:3.2vh;width:13vh}
#rs.talking canvas{display:block}
#rs.talking{border-color:rgba(229,72,77,.6)}
@keyframes rspulse{50%{transform:scale(.78);opacity:.65}}
"""

EXHIBIT_PLAQUES = """<video id="clip" muted playsinline style="position:fixed;inset:0;width:100%;height:100%;object-fit:contain;background:#000;z-index:50;display:none;opacity:0;transition:opacity .9s ease"></video>
<div id="scrim"></div>
<div id="bar">
  <div class="card hide" id="qbox"><h3 class="big">The Question</h3><div id="qidle"></div><div id="qtext"></div><div id="rows"></div></div>
  <div class="card" id="abox"><h3>The Chief Justice Answers</h3><div id="a" class="idle-text"></div></div>
</div>"""

# The state pill: Idle / Listening / Thinking / Speaking / Mic muted. Must sit
# in the document BEFORE the script block - EXHIBIT_JS binds #rs at parse time.
EXHIBIT_PILL = """<div id="rs" class="idle"><span class="dot"></span>\
<canvas id="rsw" width="160" height="40"></canvas><span class="lbl">Idle</span></div>"""

EXHIBIT_JS = """const esc=s=>{const d=document.createElement('div');d.innerText=s||'';return d.innerHTML};
const IDLE='Approach and say <em>&ldquo;Hey, Cee-Jap&rdquo;</em> <em>&ldquo;Hi, Cee-Jap&rdquo;</em> <em>&ldquo;Cee-Jap&rdquo;</em>';
// seconds after the answer ends before the question/answer plaques clear back
// to the idle display (2026-08-26, user); ?idle=<s> overrides, 0 = never clear
const IDLE_AFTER_S=(()=>{const v=parseFloat(new URLSearchParams(location.search).get('idle'));return v>=0?v:8;})();
let curState='';
function setState(st){
  if(st===curState)return;curState=st;
  document.getElementById('cam').classList.toggle('live',st==='speaking');
}
let lastRows='',lastQ='';
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
  const qHtml=qText?'<div class="row q"><div class="b"><span class="qt">&ldquo;'+esc(qText)+'&rdquo;</span></div>'+
    '<span class="t">'+(tr.state==='done'&&tr.t!=null?tr.t.toFixed(1)+'s':'')+'</span></div>':'';
  if(qHtml!==lastQ){lastQ=qHtml;document.getElementById('qtext').innerHTML=qHtml;}
  if(!qText&&tr.state==='active')parts.push(rowHtml('active','Transcribed','<span class="think">'+esc(tr.detail||'listening')+'</span>'));
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
  const opening=idle&&!showQ;   // first-turned-on display: wake phrases on both plaques
  const qb=document.getElementById('qbox');
  qb.classList.toggle('hide',!showQ&&!opening);qb.classList.toggle('idle',opening);
  if(opening)document.getElementById('qidle').innerHTML=html;
  a.classList.toggle('idle-text',!!idle);
  a.innerHTML=html;
  const cur=a.querySelector('.cur');
  if(cur)cur.scrollIntoView({block:'center',behavior:'smooth'});
  else a.scrollTop=a.scrollHeight;
}
function renderExhibit(s){
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
    // 3. question heard, answer being prepared. Bounded (2026-09-05): a turn
    // that ended without speech (bail-out clip, offline notice, error) left
    // "considering" up until the next question — 90 s covers the longest answer.
    if(lastU&&(!sp||lastU.ts>sp.ts)&&(!lastC||lastU.ts>lastC.ts)&&(s.ts-lastU.ts)<90){setState('thinking');
      render('<span class="think">The Chief Justice is considering</span>',true,true);return;}
    // 4. finished: keep the full answer and its intake on screen
    setState('idle');
    // ...then IDLE_AFTER_S seconds later (robot clock) fade back to the opening display
    const endTs=(sp&&sp.done&&(sp.spoken||[]).length)?sp.ts:(lastC?lastC.ts:0);
    const stale=IDLE_AFTER_S>0&&endTs>0&&(s.ts-endTs)>=IDLE_AFTER_S;
    if(!stale&&sp&&sp.done&&(sp.spoken||[]).length){render(esc(sp.spoken.join(' ')),false,!!lastU);return;}
    if(!stale&&lastC){render(esc(lastC.text),false,!!lastU);return;}
    render(IDLE,true,false);
}
// ---- state pill (shared: /audience and /face-avatar) ---------------------
// Idle / Listening / Thinking / Speaking / Mic muted, driven by the same
// setState() rules the plaques use. Every helper no-ops on a page that does
// not include EXHIBIT_PILL, so including EXHIBIT_JS alone stays safe.
const RSQS=new URLSearchParams(location.search);
const RS=document.getElementById('rs'),RSW=document.getElementById('rsw'),
      RSL=RS?RS.querySelector('.lbl'):null;
if(RS&&RSQS.get('pos')==='tl')RS.classList.add('tr');   // portrait is top-left: pill moves right
if(RS&&RSQS.get('pill')==='off')RS.style.display='none';   // clean portrait, no indicator
let rsState='',rsClock=0,rsClip=null;const rsEnv={};
function setIndicator(st,label){
  if(!RS)return;
  if(st!==rsState){rsState=st;RS.className=st+(RSQS.get('pos')==='tl'?' tr':'');}   // keep the side class
  if(RSL&&RSL.innerText!==label)RSL.innerText=label;
}
// loudness envelope (40 ms windows) of a sentence wav, parsed from the PCM
// directly (24 kHz/16-bit/mono from /api/sentence.wav) — no AudioContext,
// so it works without a user gesture on the kiosk browser
async function loadEnv(name){
  if(rsEnv[name]!==undefined)return;rsEnv[name]=null;
  try{
    const b=await(await fetch('/api/sentence.wav?name='+encodeURIComponent(name))).arrayBuffer();
    const dv=new DataView(b);let off=12,sr=24000,data=null;
    while(off+8<=b.byteLength){
      const id=String.fromCharCode(dv.getUint8(off),dv.getUint8(off+1),dv.getUint8(off+2),dv.getUint8(off+3));
      const sz=dv.getUint32(off+4,true);
      if(id==='fmt ')sr=dv.getUint32(off+12,true);
      if(id==='data'){const end=Math.min(b.byteLength,off+8+sz);data=new Int16Array(b.slice(off+8,end-((end-off-8)%2)));break;}
      off+=8+sz+(sz&1);
    }
    if(!data||!data.length)return;
    const win=Math.max(1,Math.round(sr*0.04)),env=[];
    for(let i=0;i+win<=data.length;i+=win){let a=0;for(let j=i;j<i+win;j++){const v=data[j]/32768;a+=v*v;}env.push(Math.sqrt(a/win));}
    const mx=Math.max(0.05,...env);
    rsEnv[name]={sr:sr,win:win,env:env.map(v=>v/mx)};
  }catch(e){}
}
function drawWave(){
  requestAnimationFrame(drawWave);
  if(!RSW||rsState!=='talking')return;
  const ctx=RSW.getContext('2d'),W=RSW.width,H=RSW.height;ctx.clearRect(0,0,W,H);
  const n=18,bw=W/n,e=rsClip&&rsClip.wav?rsEnv[rsClip.wav]:null;
  const t=Date.now()/1000-rsClock-(rsClip?rsClip.t0:0);   // seconds into the clip (robot clock)
  ctx.fillStyle='#e5484d';
  for(let i=0;i<n;i++){
    let v;
    if(e&&e.env.length){const k=Math.floor((t+(i-n/2)*0.04)*e.sr/e.win);v=(k>=0&&k<e.env.length)?e.env[k]:0.06;}
    else v=0.2+0.55*Math.abs(Math.sin(Date.now()/95+i*0.8));   // no envelope: generic motion
    const h=Math.max(3,v*H);ctx.fillRect(i*bw+1.5,(H-h)/2,bw-3,h);
  }
}
if(RSW)drawWave();
function updateIndicator(s){
  rsClock=Date.now()/1000-s.ts;   // browser-vs-robot clock offset (refreshed every poll)
  const sp=s.speaking,as=s.aside;
  const answer=sp&&!sp.done&&(sp.spoken||[]).length;
  const aside=as&&as.wav&&(s.ts-as.ts)<((as.dur||1.5)+0.3);   // ack / filler clip on air
  if(answer||aside){
    const src=answer?sp:as,t0=src.play_ts||src.ts;
    if(!rsClip||rsClip.wav!==src.wav||rsClip.t0!==t0){rsClip={wav:src.wav||null,t0:t0};if(src.wav)loadEnv(src.wav);}
    setIndicator('talking','Speaking');return;
  }
  rsClip=null;
  if(s.muted){setIndicator('muted','Mic muted');return;}   // mic mute: robot may still speak (handled above)
  if(curState==='listening'){setIndicator('listening','Listening');return;}
  if(curState==='thinking'){setIndicator('thinking','Thinking');return;}
  setIndicator('idle','Idle');
}
"""

AUDIENCE_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chief Justice Artemio V. Panganiban</title><link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,500;0,600;1,500&family=EB+Garamond:ital,wght@0,400;0,500;1,400&display=swap" rel="stylesheet">
<style>
""" + EXHIBIT_CSS + """
</style></head><body>
<div id="cam"><img id="camimg" alt="">
  <div class="idle" id="camidle"><b>CJAP</b>
    <span>Chief Justice Artemio V. Panganiban</span></div>
</div>
""" + EXHIBIT_PILL + EXHIBIT_PLAQUES + """<script>
""" + EXHIBIT_JS + """const qs=new URLSearchParams(location.search),camW=parseFloat(qs.get('cam'));
if(camW>10&&camW<=100)document.getElementById('cam').style.width=camW+'vw';
if(['tr','tl'].includes(qs.get('pos')))document.getElementById('cam').classList.add(qs.get('pos'));
let camOK=false;
// 2026-09-01 (user: "make the livestream faster"): the picture is one long-lived
// MJPEG stream (frames pushed as the camera produces them) instead of a JPEG
// fetch every 150 ms; the probe only checks liveness and (re)starts the stream.
let camStreaming=false;
function camTick(){
  const img=document.getElementById('camimg'),idle=document.getElementById('camidle');
  if(window.__camOff){camOK=false;camStreaming=false;img.removeAttribute('src');idle.style.display='flex';return;}
  const probe=new Image();
  probe.onload=()=>{camOK=true;idle.style.display='none';
    if(!camStreaming){camStreaming=true;img.src='/api/camera.mjpg?t='+Date.now();}};
  probe.onerror=()=>{camOK=false;camStreaming=false;img.removeAttribute('src');idle.style.display='flex';};
  probe.src='/api/camera.jpg?t='+Date.now();
}
// video clips (2026-09-02): the /maintain "Video clips" card can play an
// uploaded clip on the exhibit pages; here it fades in over the whole page
// (muted — sound is the robot speaker or the /face-avatar device) and fades
// back to the exhibit when it ends or Stop is pressed.
// 2026-09-05: prime on the first poll even when there is no command yet —
// priming on the first command swallowed the first clip after a reboot
// (same fix as ui_page_face.py applyVideoCmd, 2026-09-04).
let lastVidTs=0,vidPrimed=false,clipFadeT=null;
function clipStop(){const v=document.getElementById("clip");
  if(!v||v.style.display==="none"||!v.style.display)return;
  v.style.opacity=0;clearTimeout(clipFadeT);
  clipFadeT=setTimeout(()=>{v.pause();v.removeAttribute("src");v.load();v.style.display="none";},950);}
function clipTick(c){
  if(!vidPrimed){vidPrimed=true;lastVidTs=(c&&c.ts)||0;return;}
  if(!c||!c.ts||c.ts<=lastVidTs)return;
  lastVidTs=c.ts;
  const v=document.getElementById("clip");if(!v)return;
  if(c.cmd==="play"&&c.name){
    clearTimeout(clipFadeT);
    v.src="/api/video?name="+encodeURIComponent(c.name);
    v.style.display="block";v.style.opacity=0;v.currentTime=0;
    v.addEventListener("playing",()=>{v.style.opacity=1;},{once:true});
    v.addEventListener("ended",clipStop,{once:true});
    v.play().catch(()=>{});
  }else if(c.cmd==="stop")clipStop();
}
async function poll(){
  try{
    const s=await (await fetch('/api/state')).json();
    if(window.__uiRev==null)window.__uiRev=s.ui_rev||null;else if(s.ui_rev&&s.ui_rev!==window.__uiRev){location.reload();return;}
    window.__camOff=!!s.camera_off;   // /maintain "Camera off": show the idle plaque, stop probing
    renderExhibit(s);
    clipTick(s.video_cmd);
    updateIndicator(s);
  }catch(e){/* audience view never shows errors */}
}
setInterval(poll,300);poll();
setInterval(camTick,2000);camTick();
</script></body></html>"""
