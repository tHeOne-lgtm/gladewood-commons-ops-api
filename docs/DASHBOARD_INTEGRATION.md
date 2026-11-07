# Command Center Dashboard: API Integration After Phase 0

**Dashboard:** https://psgccommandcenter.live (Netlify). Single static HTML file, vanilla JavaScript, state in `localStorage`, no build step. Source is not in GitHub; it lives on Paul's Mac. (Source fact: page fetched 2026-11-07; title "Command Center", 20 inline script blocks, no external scripts, no framework markers.)

**What it does with this API today (Source fact):** a "Gladewood sync" card with an API base URL field and Test, Pull, Push buttons. The `api(path, opt)` wrapper calls `/api/health`, `/api/properties`, `/api/prospects`, `/api/residents`, and `/api/conflict-log` with only a `Content-Type` header. After Phase 0 every one of those calls except `/api/health` returns 401 until the page sends a Supabase access token.

## 1. Render settings (Paul)

| Variable | Value |
|---|---|
| `CORS_ORIGINS` | `https://psgccommandcenter.live` |
| `SUPABASE_URL` | `https://<Project ID>.supabase.co`; Project ID is on Project Settings, General |
| `BOOTSTRAP_ADMIN_EMAILS` | `paulselman@gladewoodcommons.com` (remove after first sign-in) |

Add `http://localhost:8000` to `CORS_ORIGINS` only on a local `.env`, never on Render.

## 2. Supabase Auth settings (Paul)

- https://supabase.com/dashboard/project/_/auth/url-configuration: Site URL `https://psgccommandcenter.live`; Redirect URL `https://psgccommandcenter.live/**`.
- Authentication, Sign In / Providers: Email enabled. Magic link (no password) is enough for a one-person staff login and avoids storing a password in the page.
- https://supabase.com/dashboard/project/_/settings/api-keys: copy the **publishable** key (`sb_publishable_...`; `anon` on older projects). It is safe to ship in the page. A `sb_secret_` or `service_role` key never is.

## 3. Patch for the Command Center HTML (Analysis: drop-in replacement)

**3a. Load supabase-js once, in `<head>`:**

```html
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js"></script>
```

**3b. Replace the existing `api` function in the Gladewood sync block with this:**

```js
var SB_URL = 'https://YOUR-PROJECT.supabase.co';   // Supabase > Project Settings > API
var SB_ANON = 'sb_publishable_...';                 // publishable (or legacy anon) key only; never a secret key
var sb = window.supabase.createClient(SB_URL, SB_ANON);

function token(){
  return sb.auth.getSession().then(function(r){
    var s = r.data && r.data.session;
    if(!s) throw new Error('Sign in to Gladewood first.');
    return s.access_token;                           // supabase-js refreshes it automatically
  });
}

function api(path, opt){
  var base = S().settings.api;
  if(!base) return Promise.reject(new Error('Set the API base URL first.'));
  opt = opt || {};
  return token().then(function(t){
    opt.headers = {'Content-Type':'application/json', 'Authorization':'Bearer ' + t};
    return fetch(base + path, opt);
  }).then(function(r){
    if(r.status === 401) throw new Error('Session expired. Sign in again.');
    if(r.status === 403) throw new Error('This account has no staff role yet. Ask Paul to assign one.');
    if(!r.ok) throw new Error(path + ' → HTTP ' + r.status);
    return r.status === 204 ? null : r.json();
  });
}

function gwSignIn(email){
  return sb.auth.signInWithOtp({ email: email, options: { emailRedirectTo: location.origin } })
    .then(function(r){ if(r.error) throw r.error; });
}
function gwSignOut(){ return sb.auth.signOut(); }
function gwWhoAmI(){ return api('/api/me'); }      // returns {id, email, role}
```

**3c. Add a sign-in row to the Gladewood sync card, next to the API base URL field:**

```html
<label class="f">Staff email<input class="in" id="gwEmail" type="email" autocomplete="email"></label>
<div class="row" style="margin-top:8px;gap:8px">
  <button class="btn sm" id="gwSignIn">Email me a sign-in link</button>
  <button class="btn sm" id="gwSignOut">Sign out</button>
  <span class="small" id="gwWho"></span>
</div>
```

```js
$('#gwSignIn').onclick = function(){
  var e = $('#gwEmail').value.trim(); if(!e) return;
  gwSignIn(e).then(function(){ msg('Check your email for the sign-in link.'); })
             .catch(function(err){ msg(err.message, 1); });
};
$('#gwSignOut').onclick = function(){ gwSignOut().then(function(){ $('#gwWho').textContent = ''; msg('Signed out.'); }); };
sb.auth.onAuthStateChange(function(){
  gwWhoAmI().then(function(u){ $('#gwWho').textContent = u.email + ' (' + u.role + ')'; })
            .catch(function(){ $('#gwWho').textContent = ''; });
});
```

The existing Test, Pull, and Push buttons need no change; they already go through `api()`.

**3d. Content Security Policy.** The page shows "Allowed by the site security policy: hook.us2.make.com", so a CSP exists outside the HTML: Netlify reads it from a `_headers` file in the publish directory or from `[[headers]]` in `netlify.toml`. Add to `connect-src`: the Render API origin and `https://YOUR-PROJECT.supabase.co`. Add to `script-src`: `https://cdn.jsdelivr.net`. Without this the browser blocks the calls before they leave the page.

## 4. First sign-in sequence

1. Deploy the API (Render runs `alembic upgrade head` first).
2. Set the Render and Supabase values above.
3. Open the Command Center, enter the API base URL, request a sign-in link, click it.
4. The first login creates your `users` row with role `admin` because the email matches `BOOTSTRAP_ADMIN_EMAILS`. Test should now say Connected and Pull should return rows.
5. Remove `BOOTSTRAP_ADMIN_EMAILS` from Render.
6. Any later person signs in the same way and lands as `pending`; grant `staff` with `PUT /api/users/{id}/role`.

## 5. Notes (Analysis)

- The HTML file is public on the internet. Keep resident data out of the file itself; the sync card already stores records in the browser and the API, not in the HTML.
- The Make webhook sync in the same page is unrelated to this API and is unchanged.
- The anon key plus a user session is the standard Supabase browser pattern; the API verifies the user's JWT, so the anon key alone grants nothing on this API.
