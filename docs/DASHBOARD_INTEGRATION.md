# Command Center Dashboard: API Integration After Phase 0

**Dashboard:** https://psgccommandcenter.live (Netlify). Single static HTML file, vanilla JavaScript, state in `localStorage`, no build step. Source is not in GitHub; it lives on Paul's Mac. (Source fact: page fetched 2026-11-07; title "Command Center", 20 inline script blocks, no external scripts, no framework markers.)

**What the original does with this API (Source fact):** a "Gladewood sync" card with an API base URL field and Test, Pull, Push buttons. The `api(path, opt)` wrapper calls `/api/health`, `/api/properties`, `/api/prospects`, `/api/residents`, and `/api/conflict-log` with only a `Content-Type` header. After Phase 0 every one of those calls except `/api/health` returns 401 until the page sends a Supabase access token.

**Decision 2026-11-09 (Paul): counts only.** The patched page no longer pulls property, prospect, or resident records into the browser. The Pull button is replaced by **Today counts**, which calls `GET /api/today` and shows counts (overdue and due-today deals and tasks, open deals) for the signed-in member and for everyone, plus a link to the API. Push is unchanged. Rows pulled by an earlier build stay in that browser's `localStorage` until cleared with the page's own reset.

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
2. Inlines supabase-js into `index.html` (the page already allows inline scripts), so the site stays a single self-contained file and a deploy that uploads only `index.html` still works.
3. Replaces `api()` so every call carries `Authorization: Bearer <token>` and reports 401 and 403 in plain words.
4. Adds four fields to the Gladewood sync card: Supabase publishable key, Staff email, Password, and the buttons Sign in (password), Email me a sign-in link instead, and Sign out, with a status line. The key is stored under its own `localStorage` key (`gw-sb-key.v1`) because the page's state loader drops unknown settings. The password is never stored; the field is cleared after a successful sign-in. Password sign-in calls `signInWithPassword()` and was added on 2026-11-07 after the magic-link flow failed in production (see `ATTEMPT_LOG.md`).
5. Hands the captured token to supabase-js with `setSession()` (URL detection is turned off), so sign-in does not depend on the URL surviving the router.
6. Adds the API and Supabase origins to `connect-src` in `_headers`.
7. (2026-11-09) Replaces the Pull branch of `sync()` with the Today counts call, renames the button, adds a `#gwToday` line, shows the API's own 403 message (so the MFA refusal reads correctly), and appends a second-factor notice to the status line when `/api/me` returns `mfa_required`.

Three defects found while testing in a real browser, all fixed in the script: the router erased the token fragment; the key did not persist across reloads; and the Supabase URL variable was declared after the init code that used it, which threw "supabaseUrl is required" and silently broke the sync card on a fresh load (the blank status line).

Verified end to end in headless Chromium with Supabase and the API simulated: request link, open link in a fresh page load, status shows email and role, Test returns Connected, session persists after reload.

Password sign-in verified the same way on 2026-11-07 with `tools/command_center_check.mjs` (installed Google Chrome driven by `playwright-core`; Supabase Auth and `/api/me` simulated): fresh load, key pasted, email and password entered, status shows `(admin)`, password field cleared, session survives a reload, API receives the bearer token, sign-out returns to "Not signed in", no page errors. The original to patch is `command-center-site-canvaslink.zip` (2026-10-31); it reproduces the shipped build byte for byte, and the older `2610b` zip does not.

Counts-only build verified the same way on 2026-11-09: the Pull button is absent, Today counts calls `/api/today` with the bearer token and renders the counts line and link, none of the record endpoints is called, sign-in, reload, and sign-out still pass, no page errors. The verified folder is at `~/Projects/cc-patched`, not yet deployed.

## 4. First sign-in sequence

1. Deploy the API (Render runs `alembic upgrade head` first).
2. Set the Render and Supabase values above.
3. In Supabase, Authentication, Users: **Add user**, **Create new user**, enter the staff email and a password, keep **Auto Confirm User** on, create. (Source: third-party screenshots of the current modal, not Supabase's own docs, which only document the invitation path and the `auth.admin.createUser()` API. If the dashboard says the email already exists from the earlier magic-link attempts, delete that user first; the API has no `users` row yet, so nothing is lost.)
4. Open the Command Center, Data view, Gladewood sync card: enter the API base URL and the publishable key, then the staff email and password, and click Sign in. The email-link button remains as a fallback.
5. The first login creates your `users` row with role `admin` because the email matches `BOOTSTRAP_ADMIN_EMAILS`. Test should now say Connected and Today counts should show the counts line.
6. Remove `BOOTSTRAP_ADMIN_EMAILS` from Render.
7. Any later person signs in the same way and lands as `pending`; grant `staff` with `PUT /api/users/{id}/role`.
8. Before any tenant uses a portal, configure custom SMTP in Supabase (Authentication, SMTP Settings) so the hourly auth-email limit no longer applies.

## 5. Notes (Analysis)

- The HTML file is public on the internet. Keep resident data out of the file itself. Since 2026-11-09 the sync card pulls counts only, so the API's contact and deal records never enter this page; the page's own local grids are whatever Paul types into them.
- Staff MFA: once Paul has enrolled a TOTP factor in Supabase Auth and set `REQUIRE_STAFF_MFA=true` on Render, a session without the authenticator step shows "second factor required" on the status line and every other API call returns the API's 403 text. The page does not yet run the Supabase MFA challenge itself; until the staff app exists, enrol and verify through the Supabase dashboard or the staff app, then sign in here.
- The Make webhook sync in the same page is unrelated to this API and is unchanged.
- The anon key plus a user session is the standard Supabase browser pattern; the API verifies the user's JWT, so the anon key alone grants nothing on this API.
