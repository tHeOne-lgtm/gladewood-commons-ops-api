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

## 3. The patch (applied by `tools/command_center_patch.py`)

Run `python3 tools/command_center_patch.py <original site folder> <output folder> <path to supabase-js UMD bundle>`. The bundle is `dist/umd/supabase.js` from the `@supabase/supabase-js` npm package (2.119.0 was used). The script copies the site, then:

1. Inserts a first `<script>` in `<head>` that sets `window.GW_SB_URL` and captures the sign-in fragment (`#access_token=...`) the magic link returns, before the page's hash router can erase it, and points the router at the Data view.
2. Serves supabase-js from the site itself (`supabase.js`), so the existing `script-src 'self'` policy is unchanged.
3. Replaces `api()` so every call carries `Authorization: Bearer <token>` and reports 401 and 403 in plain words.
4. Adds three fields to the Gladewood sync card: Supabase publishable key, Staff email, and the sign-in and sign-out buttons with a status line. The key is stored under its own `localStorage` key (`gw-sb-key.v1`) because the page's state loader drops unknown settings.
5. Hands the captured token to supabase-js with `setSession()` (URL detection is turned off), so sign-in does not depend on the URL surviving the router.
6. Adds the API and Supabase origins to `connect-src` in `_headers`.

Three defects found while testing in a real browser, all fixed in the script: the router erased the token fragment; the key did not persist across reloads; and the Supabase URL variable was declared after the init code that used it, which threw "supabaseUrl is required" and silently broke the sync card on a fresh load (the blank status line).

Verified end to end in headless Chromium with Supabase and the API simulated: request link, open link in a fresh page load, status shows email and role, Test returns Connected, session persists after reload.

## 4. First sign-in sequence

1. Deploy the API (Render runs `alembic upgrade head` first).
2. Set the Render and Supabase values above.
3. Open the Command Center, Data view, Gladewood sync card: enter the API base URL and the publishable key, request a sign-in link, open it in the same browser.
4. The first login creates your `users` row with role `admin` because the email matches `BOOTSTRAP_ADMIN_EMAILS`. Test should now say Connected and Pull should return rows.
5. Remove `BOOTSTRAP_ADMIN_EMAILS` from Render.
6. Any later person signs in the same way and lands as `pending`; grant `staff` with `PUT /api/users/{id}/role`.

## 5. Notes (Analysis)

- The HTML file is public on the internet. Keep resident data out of the file itself; the sync card already stores records in the browser and the API, not in the HTML.
- The Make webhook sync in the same page is unrelated to this API and is unchanged.
- The anon key plus a user session is the standard Supabase browser pattern; the API verifies the user's JWT, so the anon key alone grants nothing on this API.
