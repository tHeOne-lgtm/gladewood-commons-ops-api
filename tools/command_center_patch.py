"""Build the patched Command Center from the original upload. Usage: python3 cc-patch.py <src_dir> <out_dir> <supabase_js>"""
import os, re, shutil, sys
src, out, lib = sys.argv[1], sys.argv[2], sys.argv[3]
SB_URL = "https://ghzecqhfbtgrhbibqicp.supabase.co"
API_URL = "https://gladewood-commons-ops-api.onrender.com"
if os.path.exists(out): shutil.rmtree(out)
os.makedirs(out)
for f in ("index.html", "_headers", "icon-192.png", "icon-512.png", "apple-touch-icon.png", "manifest.webmanifest", "robots.txt"):
    shutil.copy(os.path.join(src, f), out)
shutil.copy(lib, os.path.join(out, "supabase.js"))
p = os.path.join(out, "index.html"); t = open(p, encoding="utf-8").read()

def rep(old, new):
    global t
    assert t.count(old) == 1, f"expected exactly one match for: {old[:60]!r} (found {t.count(old)})"
    t = t.replace(old, new, 1)

# 1. first script: Supabase URL plus capture of the sign-in fragment before the hash router can erase it
rep("<head>", '<head>\n<script>window.GW_SB_URL="%s";(function(){var h=location.hash||"";if(/access_token=|refresh_token=|error_description=|type=magiclink/.test(h)){window.__gwAuthHash=h;try{history.replaceState(null,"",location.pathname+location.search+"#data")}catch(e){}}})();</script>' % SB_URL)
# 2. library, served from the site itself (script-src stays 'self')
rep("</head>", '<script src="supabase.js"></script>\n</head>')
# 3. api() with bearer token, plus sign-in helpers
a = t.index("function api(path,opt){"); b = t.index("return r.status===204?null:r.json()})}", a) + len("return r.status===204?null:r.json()})}")
t = t[:a] + r"""var sbClient=null;
function gwKey(){try{return (localStorage.getItem('gw-sb-key.v1')||'').trim()}catch(e){return ''}}
function sb(){var key=gwKey();if(!key)return null;
  if(!sbClient||sbClient.__key!==key){
    sbClient=window.supabase.createClient(window.GW_SB_URL,key,{auth:{detectSessionInUrl:false}});sbClient.__key=key;
    sbClient.auth.onAuthStateChange(function(ev){if(ev==='SIGNED_IN'||ev==='SIGNED_OUT'||ev==='USER_UPDATED')gwWho()});
    consumeAuthHash()}
  return sbClient}
function consumeAuthHash(){var h=window.__gwAuthHash||'';if(!h||!sbClient)return;window.__gwAuthHash=null;
  var q=new URLSearchParams(h.replace(/^#/,''));var err=q.get('error_description');if(err){msg(err,1);return}
  var at=q.get('access_token'),rt=q.get('refresh_token');if(!at)return;
  var el=$('#gwWho');if(el)el.textContent='Finishing sign-in…';
  sbClient.auth.setSession({access_token:at,refresh_token:rt||''}).then(function(r){if(r.error)throw r.error;try{history.replaceState(null,'',location.pathname+location.search+'#data')}catch(e){}gwWho()})
    .catch(function(e){msg('Sign-in failed: '+(e&&e.message||e),1);gwWho()})}
function token(){var c=sb();if(!c)return Promise.reject(new Error('Paste the Supabase publishable key first.'));return c.auth.getSession().then(function(r){var s=r.data&&r.data.session;if(!s)throw new Error('Sign in to Gladewood first.');return s.access_token})}
function api(path,opt){var base=S().settings.api;if(!base)return Promise.reject(new Error('Set the API base URL first.'));opt=opt||{};
  return token().then(function(tk){opt.headers={'Content-Type':'application/json','Authorization':'Bearer '+tk};return fetch(base+path,opt)}).then(function(r){
    if(r.status===401)throw new Error('Session expired. Sign in again.');
    if(r.status===403)throw new Error('This account has no staff role yet. Ask Paul to assign one.');
    if(!r.ok)throw new Error(path+' → HTTP '+r.status);return r.status===204?null:r.json()})}
function gwSignIn(email){var c=sb();if(!c)return Promise.reject(new Error('Paste the Supabase publishable key first.'));return c.auth.signInWithOtp({email:email,options:{emailRedirectTo:location.origin+location.pathname}}).then(function(r){if(r.error)throw r.error})}
function gwSignOut(){var c=sb();return c?c.auth.signOut():Promise.resolve()}
function gwWho(){var el=$('#gwWho');if(!el)return;var c=sb();if(!c){el.textContent='Paste the Supabase publishable key to enable sign-in.';return}
  el.textContent='Checking sign-in…';c.auth.getSession().then(function(r){var s=r.data&&r.data.session;if(!s){el.textContent='Not signed in';return}
    var em=(s.user&&s.user.email)||'';el.textContent='Signed in as '+em+'; contacting API (a sleeping free instance can take up to 60 s)…';
    return api('/api/me').then(function(u){el.textContent=u.email+' ('+u.role+')'}).catch(function(e){el.textContent='Signed in as '+em+'; API: '+e.message})})}""" + t[b:]
# 4. sign-in fields on the sync card
label = '<label class="f">API base URL<input class="in" id="apiUrl" placeholder="https://your-service.onrender.com"></label>'
rep(label, label +
 '\n        <label class="f">Supabase publishable key<input class="in" id="sbKey" placeholder="sb_publishable_..." autocomplete="off"></label>'
 '\n        <label class="f">Staff email<input class="in" id="gwEmail" type="email" autocomplete="email" placeholder="you@gladewoodcommons.com"></label>'
 '\n        <div class="row" style="margin-top:8px;gap:8px"><button class="btn sm" id="gwSignIn">Email me a sign-in link</button><button class="btn sm" id="gwSignOut">Sign out</button><span class="small" id="gwWho"></span></div>')
# 5. wiring, guarded so an error can never break the rest of the sync module
onchange = "$('#apiUrl').onchange=function(){S().settings.api=this.value.trim().replace(/\\/+$/,'');save()};"
rep(onchange, onchange + r"""
$('#sbKey').value=gwKey();$('#sbKey').onchange=function(){try{localStorage.setItem('gw-sb-key.v1',this.value.trim())}catch(e){}sbClient=null;gwWho()};
$('#gwSignIn').onclick=function(){var e=$('#gwEmail').value.trim();if(!e){msg('Enter your staff email.',1);return}gwSignIn(e).then(function(){msg('Check your email for the sign-in link.')}).catch(function(err){msg(err.message,1)})};
$('#gwSignOut').onclick=function(){gwSignOut().then(function(){msg('Signed out.');gwWho()})};
(function(){var h=window.__gwAuthHash||'';var m=/error_description=([^&]+)/.exec(h);if(m){msg(decodeURIComponent(m[1].replace(/\+/g,' ')),1)}try{if(gwKey())sb()}catch(e){msg('Sign-in setup error: '+(e&&e.message||e),1)}})();setTimeout(gwWho,300);
window.addEventListener('hashchange',function(){var h=location.hash||'';if(/access_token=|error_description=/.test(h)){window.__gwAuthHash=h;try{if(sb())consumeAuthHash()}catch(e){}}});""")
open(p, "w", encoding="utf-8").write(t)
# 6. headers: allow the API and Supabase; script-src unchanged
hp = os.path.join(out, "_headers"); h = open(hp, encoding="utf-8").read()
assert h.count("connect-src https://hook.us2.make.com") == 1
h = h.replace("connect-src https://hook.us2.make.com", "connect-src %s %s https://hook.us2.make.com" % (API_URL, SB_URL), 1)
open(hp, "w", encoding="utf-8").write(h)
print("patched:", out, "| connect-src:", re.search(r"connect-src[^;]+", h).group(0))
