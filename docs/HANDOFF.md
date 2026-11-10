# Hand-off: 2026-11-07

Written for Paul to continue on the Mac mini. Everything below is in `master` or on the open PR #2 unless marked otherwise.

## Where things stand

| Area | State |
|---|---|
| API code | Phase 0 (foundation) and Phase 1 (CRM core) merged to `master` via PR #1. 45 tests, CI green. |
| API deployment | Live at `https://gladewood-commons-ops-api.onrender.com` on a Render **Free** instance. Migrations `0001` and `0002` applied; `/api/health` returns `{"ok":true,"db":true}`. Start Command is `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`. |
| Supabase | Project `gladewood-commons-ops` (ref `ghzecqhfbtgrhbibqicp`, Free plan, org "PJS SubCrip Org"). Database password was rotated today. Auth URL configuration and email provider: Paul reports done. |
| Render env vars | `DATABASE_URL`, `CORS_ORIGINS=https://psgccommandcenter.live`, `SUPABASE_URL`, `ENV`, `PYTHON_VERSION=3.12.8` (confirmed in the build log on 2026-11-07). `BOOTSTRAP_ADMIN_EMAILS` was set to empty on 2026-11-07 20:37 UTC after the first admin sign-in (the app treats empty as unset). |
| Command Center (Netlify, psgccommandcenter.live) | Full folder deployed on 2026-11-07 (headers, icons and manifest confirmed live). The live `index.html` is the magic-link build. The build staged at `~/Projects/cc-patched` (rebuilt 2026-11-09 from the canvaslink original) carries password sign-in and the counts-only Today button instead of Pull; verified headless, not yet deployed. |
| Migration 0003 (2026-11-09) | In the working tree, not yet pushed or applied on Render: `next_action_at` plus the open-deal rule on `deals`, `import_batches` with `import_batch_id` on contacts, companies, deals. Applied, rolled back, and re-applied on a local Postgres 16; 58 tests pass on SQLite and on the migrated schema. |
| First sign-in | Completed 2026-11-07 20:24 UTC by magic link; `/api/me` returned 200 and the status line shows `(admin)`. |
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

1. Deploy the whole `~/Projects/cc-patched` **folder** to Netlify (drag the folder, not the file). The 2026-11-07 afternoon deploy uploaded only `index.html`, so the live site is missing `_headers` (CSP, frame denial, noindex) and the icons. The staged folder now also carries password sign-in.
2. Create your staff user with a password in Supabase (Authentication, Users, Add user, Create new user, Auto Confirm User on). If the email already exists from the magic-link attempts, delete that user first.
3. Sign in: Data view, Gladewood sync card, API base URL and publishable key filled, staff email and password, Sign in. Expected: status shows your email and `(admin)`; Test shows "Connected." The magic-link flow failed in production on 2026-11-07 (reported by Paul); password sign-in was verified in headless Chrome with Supabase and the API simulated, not yet in production. Configure custom SMTP (Authentication, SMTP Settings) before any tenant uses the portal.
4. Done 2026-11-07: `BOOTSTRAP_ADMIN_EMAILS` blanked on Render.
5. Run the legacy migration dry run from the Mac, review rejections, apply with `--actor <your user id>` (id from `select id, email, role from users;` in the Supabase SQL Editor). `--actor` is now required with `--apply`; the run becomes an import batch you can undo. Per the 2026-11-09 decision this waits for the "real data allowed" gate: items 1, 4, 7, 8, and 9 of the comparison. Items 1, 4, and 7 are built; 8 (your yes) and 9 (staging project) are open.
6. Decide Supabase Free versus Pro (backups) and apply for Stripe ACH (walkthrough G3).
6a. Staff MFA (decided 2026-11-09): in Supabase, Authentication, Multi-Factor, make sure TOTP is enabled; enroll your authenticator app for your account (the Supabase dashboard has no "enroll for user" button, so enrollment happens through a client: the staff app once it exists, or a short one-off page using `supabase.auth.mfa.enroll`). Only after a verified factor exists on every staff account, set `REQUIRE_STAFF_MFA=true` on Render. Set it earlier and you lock yourself out of everything but `/api/me`.
6b. Create the staging Supabase project `gladewood-commons-ops-staging` (Free, same region) and tell me it exists; no keys in chat.
7. Before switching Bigin off: export contacts, companies, pipelines, and notes from Bigin and import them here (Phase 1 import exists for CSV; Bigin's export format not yet checked). Before switching Make off: follow Step 11 of Paul's migration document (directory scenarios off the day the n8n versions publish; Command Center Sync stays on 7 days as fallback).

## Phase 2 (started 2026-11-09 with the comparison items)

Built on 2026-11-09 (working tree): comparison items 1 (open-deal rule), 2 (`GET /api/today`), 4 (import batches, duplicate review, undo), 7 (data tiers in the plan and model docstrings), the `REQUIRE_STAFF_MFA` gate, and the counts-only Command Center build. Built 2026-11-10: item 5 (`decision_log`, `consents`, migration 0004, the `app/fair_housing.py` protected-term guard that item 13 will reuse). Still to build from the comparison: 3 (stuck-in-stage n8n job), 6 (`lookup_values`), 10 (test gate scripts), 13 (weekly keyword-scan endpoint and n8n job); 8, 9, 11, and 12 are Paul's gates, project, metrics, and fallbacks.

Scope per `docs/CRM_BOOKKEEPING_PORTAL_PLAN.md`: rule engine (trigger, condition, action) with a per-action `draft`/`auto` mode that all ships in `draft`, email, inquiry and maintenance web forms, dashboards, a machine credential and webhooks for n8n, portal v1 (tenant login, documents, maintenance requests routed through the n8n Rule 11 intake before storage). The earlier "hard-coded automations, not a rule engine" cut was reversed by Paul on 2026-11-07. Decision pending from Paul: CRM screens inside the Command Center versus a separate staff app. The Command Center is a single hand-maintained HTML file; adding contacts, pipelines, deals, and activities screens there is feasible with the same patch-script approach, but a separate small app would be easier to test and version.

## Decisions on record

- 2026-11-07 (Paul): the custom CRM stays and replaces Zoho Bigin. Bigin and Make.com go dormant to cut subscriptions and can be reactivated if client load grows. n8n on the Mac mini is the automation runtime for custom tools. The n8n "draft only, Paul approves every send" rule is the first operating stage, not the ceiling; the CRM is designed for full automation with a per-action mode Paul switches when ready. Rule 11 handling stays in the n8n intake. Paul's document "Command Center: Moving from Make.com to n8n" (six n8n workflows plus `switch_to_n8n.py`) is the migration plan for the Make scenarios; its Bigin nodes re-point to this API and its Step 1 is replaced by the existing compose stack (plan Section 9).
- 2026-11-09 (Paul): the Oct 9 "GC Housing CRM Enhanced Build Plan" (Softr Pro plus Supabase) was compared with this plan (`docs/PLAN_COMPARISON_2026-11-09.md`). Decided: Command Center feed becomes counts only (no records in the public page); comparison Section 4 items 1 to 13 adopted as scope, with items 1, 4, 7, 8, and 9 before the legacy migration applies; staff MFA is Supabase TOTP and the API will refuse staff and admin tokens without `aal2`. Open: staging Supabase project, marking the Oct 9 plan superseded.
- Books module: AR subledger in this system plus a sync to Zoho Books; Zoho Books is the book of record (plan decision log). Zoho Books stays on the Free plan (verified 2026-11-07 against Zoho's pricing pages; plan Section 10, item 4 lists the limits and the $50K revenue ceiling). Confirm API access on Free with one live call before the Phase 4 sync is built.
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
