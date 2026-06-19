"""The shareable WWSD bookmarklet + a small generator/tester page served at GET /.

The bookmarklet reads the live Meteor 'games' doc out of the spendee page, POSTs it to this
service's /move with the shared secret, and renders variant S's move in an injected overlay panel.
The secret is filled in CLIENT-SIDE on the page (typed by the user) so it is never sent to or
stored by this server; the generated text is what the user copies and shares with the friend.
"""
from __future__ import annotations
import json

# Overlay bookmarklet. Placeholders __MOVE_URL__ / __SECRET__ are filled in (here or in the page).
# ASCII-only; HTML built with backtick templates so single quotes inside attributes don't clash.
BOOKMARKLET_TEMPLATE = (
    "javascript:(function(){try{"
    "var g=Meteor.connection._mongo_livedata_collections['games'].find().fetch()"
    ".map(function(x){return{status:x.status,settings:x.settings,players:x.players,data:x.data};});"
    "var body=JSON.stringify({games:g});"
    "var b=document.getElementById('wwsd');"
    "if(!b){b=document.createElement('div');b.id='wwsd';"
    "b.style.cssText='position:fixed;top:12px;right:12px;z-index:2147483647;max-width:340px;"
    "background:#241a10;color:#f0e6d8;border:1px solid #b5852f;border-radius:10px;padding:12px 14px;"
    "font:14px system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.5)';"
    "document.body.appendChild(b);b.onclick=function(e){if(e.target.id==='wx')b.remove();};}"
    "var head=`<b style='color:#e8c170'>WWSD</b> <span id=wx style='float:right;cursor:pointer'>x</span>`;"
    "b.innerHTML=head+`<div style='margin-top:6px'>thinking... (first call can take ~40s to wake the server)</div>`;"
    "fetch('__MOVE_URL__',{method:'POST',headers:{'Content-Type':'application/json',"
    "'X-WWSD-Secret':'__SECRET__'},body:body})"
    ".then(function(r){return r.json();}).then(function(d){"
    "if(!d.ok){b.innerHTML=head+`<div style='margin-top:6px'>`+(d.message||'no result')+`</div>`;return;}"
    "var h=`<div style='margin-top:6px;font-weight:700;color:#e8c170'>`+d.recommendation+`</div>`"
    "+`<div style='margin-top:4px;color:#b8a888;font-size:12px'>`+d.turn_name+` - target `+d.target+` - `+d.sims+` sims</div>`;"
    "if(d.alternatives&&d.alternatives.length){h+=`<ul style='margin:6px 0 0;padding-left:18px;color:#cdbfa8;font-size:12px'>`;"
    "d.alternatives.forEach(function(a){h+=`<li>`+a.pct+`% `+a.text+`</li>`;});h+=`</ul>`;}"
    "b.innerHTML=head+h;"
    "}).catch(function(e){b.innerHTML=head+`<div>error: `+e.message+`</div>`;});"
    "}catch(e){alert('WWSD error: '+e.message);}})();"
)


def build_bookmarklet(move_url: str, secret: str) -> str:
    """Fill the template with a concrete /move URL + secret (used by tests / for direct generation)."""
    return BOOKMARKLET_TEMPLATE.replace("__MOVE_URL__", move_url).replace("__SECRET__", secret)


def page_html() -> str:
    """Generator + tester page. Builds the bookmarklet client-side from a typed secret +
    this page's own origin, so the secret never reaches the server."""
    tpl = json.dumps(BOOKMARKLET_TEMPLATE)   # safe JS string literal
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>What Would Steve Do?</title>
<style>
 :root{color-scheme:dark}
 body{background:#1b140d;color:#f0e6d8;font:16px/1.5 system-ui,sans-serif;max-width:760px;margin:32px auto;padding:0 18px}
 h1{font-family:Georgia,serif;color:#e8c170}
 input,textarea{width:100%;background:#241a10;color:#f0e6d8;border:1px solid #5a4630;border-radius:8px;padding:9px;font:13px ui-monospace,monospace;box-sizing:border-box}
 textarea{height:120px}
 button{background:#b5852f;color:#1b140d;border:0;border-radius:8px;padding:9px 16px;font-weight:700;cursor:pointer;margin-top:8px}
 button:hover{background:#e8c170}
 .box{background:#241a10;border:1px solid #5a4630;border-radius:10px;padding:14px;margin:14px 0}
 label{display:block;margin:8px 0 4px;color:#cdbfa8;font-size:14px}
 #out{min-height:24px}.rec{font-size:20px;font-weight:700;color:#e8c170}.meta{color:#b8a888;font-size:13px}
 .err{color:#e06a4a}.msg{color:#cdbfa8;font-style:italic}
 code{color:#e8c170}
</style></head><body>
<h1>What Would Steve Do?</h1>
<div class="box">
 <b style="color:#e8c170">1. Make your bookmarklet</b>
 <label>Your shared secret (the <code>WWSD_SECRET</code> set on the server)</label>
 <input id="secret" placeholder="paste the secret">
 <button id="gen">Build bookmarklet</button>
 <label>Copy this and save it as a bookmark named "WWSD" (share it with your friend):</label>
 <textarea id="bm" readonly placeholder="(generated here)"></textarea>
</div>
<div class="box">
 <b style="color:#e8c170">2. Or test a position by pasting its JSON</b>
 <label>game-state dump <code>{games:[...]}</code></label>
 <textarea id="inp" placeholder="paste the games doc"></textarea>
 <button id="go">What would Steve do?</button>
 <div id="out" style="margin-top:10px"><span class="msg">(result appears here)</span></div>
</div>
<script>
const TPL = __TPL__;
const MOVE = location.origin + '/move';
function esc(s){return (s+'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
document.getElementById('gen').onclick=()=>{
  const sec=document.getElementById('secret').value.trim();
  document.getElementById('bm').value = sec ? TPL.replace('__MOVE_URL__',MOVE).replace('__SECRET__',sec)
                                            : 'enter your secret first';
};
document.getElementById('go').onclick=async()=>{
  const out=document.getElementById('out'); const sec=document.getElementById('secret').value.trim();
  out.innerHTML='<span class="msg">thinking...</span>';
  try{
    const r=await fetch(MOVE,{method:'POST',headers:{'Content-Type':'application/json','X-WWSD-Secret':sec},
                             body:document.getElementById('inp').value});
    const d=await r.json();
    if(!d.ok){ out.innerHTML='<span class="msg">'+esc(d.message||'no result')+'</span>'; return; }
    let h='<div class="rec">'+esc(d.recommendation)+'</div><div class="meta">'+esc(d.turn_name)
      +' to move &middot; target '+d.target+' &middot; '+d.sims+' sims</div>';
    if(d.alternatives&&d.alternatives.length){h+='<ul style="color:#cdbfa8;font-size:13px">';
      d.alternatives.forEach(a=>h+='<li>'+a.pct+'% '+esc(a.text)+'</li>');h+='</ul>';}
    out.innerHTML=h;
  }catch(e){ out.innerHTML='<span class="err">error: '+esc(e.message)+'</span>'; }
};
</script></body></html>""".replace("__TPL__", tpl)
