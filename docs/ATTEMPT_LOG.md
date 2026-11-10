# Attempt Log

One entry per problem that needed more than one attempt. Newest first.

## 2026-11-09: open-deal rule refused with a database error instead of a 422

| Attempt | What was tried | Why it failed |
|---|---|---|
| 1 | Validate the deal after applying the stage and field changes to the ORM row | The refused request left the row dirty in the session; the next query autoflushed it and the new CHECK constraint raised an IntegrityError. Also surfaced that a PUT without `owner_id` would clear the owner of an open deal. |
| 2 | Compute the target stage, owner, and next action first, validate, then mutate; a PUT without `owner_id` keeps the current owner | Passed. 58 tests on SQLite and on the Alembic-migrated Postgres 16 schema. |

Lesson: when a database constraint backs an API rule, validate before touching the row, or a refused request can poison the session.

Also noted the same day: the rebuilt `_headers` from the canvaslink original lacked `https://api.openalex.org`, which the Nov 7 deployed copy has. The patch script now adds it, so a rebuild matches the live headers.

## 2026-11-07: Command Center sign-in showed a blank status and never signed in

Took four builds, which is two over the agreed limit; the rule was set after this.

| Attempt | What was tried | Why it failed |
|---|---|---|
| 1 | Hand-written patch: load supabase-js from a CDN, replace `api()`, store the key in page settings | Three defects at once: the hash router erased the token fragment; the state loader dropped the key; the Supabase URL variable was declared after the init code that used it, so `createClient` threw and the sync card stopped working with a blank status |
| 2 | Capture the fragment in the first script and restore it before creating the client | Did not touch the two other defects; the blank status remained because the URL variable was still undefined at init |
| 3 | Rebuilt from the original with one script; URL defined first, key in its own storage slot, token handed to `setSession()`; verified in headless Chromium | Worked in test. Deploy failed in production because the library was a separate file and the deploy uploaded only `index.html` (404 on `/supabase.js`) |
| 4 | Inline the library into `index.html`; re-verified | Pending Paul's confirmation; blocked for the moment by Supabase's hourly auth-email limit after repeated test links |

Checked 2026-11-07 (later session, from the live site): the attempt 4 `index.html` is live and byte-identical to the patched build, but the deploy again uploaded only that file. `manifest.webmanifest`, the three icons, and `robots.txt` return 404, and none of the headers from `_headers` (Content-Security-Policy, X-Frame-Options, X-Robots-Tag noindex, no-cache on the page) are in the live response. Sign-in is not blocked by this, because no CSP is applied at all, but the site has lost its security headers and is indexable until the whole folder is deployed. The full folder is staged at `~/Projects/cc-patched`; deploy by dragging the folder, not the file, onto Netlify Deploys.

Lesson: diagnose by reproduction before patching. Attempts 1 and 2 were guesses about the live page; attempt 3 came from running the page in a browser and reading the exception.

Alternative on the table if attempt 4 fails: password sign-in for staff alongside the email link, and custom SMTP to remove the email limit.

2026-11-07 (later session): Paul reported attempt 4 did not sign in. Per the rule, the alternative was taken rather than a fifth variation of the link flow. `tools/command_center_patch.py` now adds a Password field and a Sign in button calling `signInWithPassword()`; the link button stays as a fallback. Verified in headless Chrome against the `command-center-site-canvaslink.zip` original (the one that reproduces the shipped build byte for byte; `2610b` does not): sign-in shows `(admin)`, the password field is cleared, the session survives a reload, the API receives a bearer token, no page errors. Not yet confirmed in production. The page's own `#ccLock` overlay (present in the original) had to be bypassed in the test harness; it is unrelated to sign-in.
