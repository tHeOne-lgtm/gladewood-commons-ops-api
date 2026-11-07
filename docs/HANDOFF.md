# Hand-off: 2026-11-07

Written for Paul to continue on the Mac mini. Everything below is in `master` or on the open PR #2 unless marked otherwise.

## Where things stand

| Area | State |
|---|---|
| API code | Phase 0 (foundation) and Phase 1 (CRM core) merged to `master` via PR #1. 45 tests, CI green. |
| API deployment | Live at `https://gladewood-commons-ops-api.onrender.com` on a Render **Free** instance. Migrations `0001` and `0002` applied; `/api/health` returns `{"ok":true,"db":true}`. Start Command is `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`. |
| Supabase | Project `gladewood-commons-ops` (ref `ghzecqhfbtgrhbibqicp`, Free plan, org "PJS SubCrip Org"). Database password was rotated today. Auth URL configuration and email provider: Paul reports done. |
| Render env vars | `DATABASE_URL`, `CORS_ORIGINS=https://psgccommandcenter.live`, `SUPABASE_URL`, `BOOTSTRAP_ADMIN_EMAILS=paulselman@gladewoodcommons.com`, `ENV`. `PYTHON_VERSION=3.12.8` recommended but not confirmed set. `BOOTSTRAP_ADMIN_EMAILS` must be removed after the first successful sign-in. |
| Command Center (Netlify, psgccommandcenter.live) | Patched build delivered as `command-center-site-patched.zip` (folder `cc-patched`, single self-contained `index.html` with supabase-js inlined, plus `_headers` and icons). Verified in headless Chromium. **Not yet confirmed working in production**: the last live deploy lacked the library file (fixed by inlining), and the next test is blocked by Supabase's hourly auth-email limit. |
| First sign-in | Not completed. No `users` row exists yet, so no admin exists yet. |
| Legacy migration | Not run. `python -m app.cli migrate-legacy` (dry run) is the next data step after sign-in. |
| PR #2 | Draft, CI green: `tools/command_center_patch.py`, docs, working agreements, attempt log. Merge when convenient; it changes no API behavior. |

## Resume on the Mac

```
cd ~/Documents/GitHub/gladewood-commons-ops-api
git fetch origin
git checkout master && git pull
git checkout claude/custom-crm-bookkeeping-portal-bmhdw5 && git pull    # PR #2 branch, if you want the docs before merging
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env     # fill DATABASE_URL (Session pooler, port 5432) and SUPABASE_URL
python -m pytest -q      # expect 45 passed
```

To rebuild the Command Center from its original folder:

```
npm pack @supabase/supabase-js@2 && tar -xzf supabase-supabase-js-*.tgz
python3 tools/command_center_patch.py "<original site folder>" ~/Projects/cc-patched package/dist/umd/supabase.js
```

Deploy `~/Projects/cc-patched` to Netlify (drag the folder onto Deploys).

## Immediate next steps, in order

1. Deploy the patched Command Center (the zip already sent, or rebuild as above).
2. Sign in: Data view, Gladewood sync card, API base URL and publishable key filled, request one link, open it in the same browser. If the email limit is still active, wait an hour. Expected: status shows your email and `(admin)`; Test shows "Connected."
3. If sign-in still fails after that one attempt, do not try a third variation of the same flow. Use the recorded alternative: add password sign-in for staff (a 20-line change in `tools/command_center_patch.py`: a password field plus `signInWithPassword`), set a password in Supabase Authentication, Users, and sign in without email. Then configure custom SMTP (Authentication, SMTP Settings) so the email limit goes away before any tenant uses the portal.
4. Remove `BOOTSTRAP_ADMIN_EMAILS` in Render (Save and deploy).
5. Run the legacy migration dry run from the Mac, review rejections, apply with `--actor <your user id>` (id from `select id, email, role from users;` in the Supabase SQL Editor).
6. Decide Supabase Free versus Pro (backups) and apply for Stripe ACH (walkthrough G3).

## Phase 2 (not started)

Scope per `docs/CRM_BOOKKEEPING_PORTAL_PLAN.md`: workflows (hard-coded automations, not a rule engine), email, inquiry and maintenance web forms, dashboards, portal v1 (tenant login, documents, maintenance requests). Decision pending from Paul: CRM screens inside the Command Center versus a separate staff app. The Command Center is a single hand-maintained HTML file; adding contacts, pipelines, deals, and activities screens there is feasible with the same patch-script approach, but a separate small app would be easier to test and version.

## Decisions on record

- Books module: AR subledger in this system plus a sync to Zoho Books; Zoho Books is the book of record (plan decision log).
- PITR deferred; daily backups on Pro plus a nightly `pg_dump` (assessment Section 10).
- Custom fields: typed columns plus a bounded `extra` JSON object; saved views deferred.
- Working agreement: two attempts per problem, verified plans, attempt log (`docs/WORKING_AGREEMENTS.md`, `docs/ATTEMPT_LOG.md`).

## Known gaps and cautions

- Render Free instance sleeps after idle; the first API call can take 50 seconds or more. Starter ($7) removes that and enables the Pre-Deploy Command.
- `prepare_threshold` is not disabled in the engine; use the Session pooler (port 5432), not the Transaction pooler (6543), or the psycopg driver's prepared statements will fail.
- The marketing site's `_headers` file was edited by mistake earlier today; confirm it was restored before any deploy of that site.
- Supabase Free has no backups; nothing irreplaceable should be entered until Pro or a `pg_dump` routine is in place.
- Legacy tables (`properties`, `prospects`, `residents`, `conflict_log`) are untouched by design; the migration copies into CRM tables and leaves them.

## Documents

- `README.md`: layout, env vars, auth model, CRM routes, migration CLI, Phase 0 steps.
- `docs/SETUP_WALKTHROUGH.md`: click-by-click setup (verified paths).
- `docs/DASHBOARD_INTEGRATION.md`: the Command Center patch, what it changes, and the three defects found.
- `docs/CRM_BOOKKEEPING_PORTAL_PLAN.md`, `docs/PLAN_ASSESSMENT.md`: plan, assessment, pricing comparison.
