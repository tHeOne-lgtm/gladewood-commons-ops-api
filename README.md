# Gladewood Commons Operations API

FastAPI backend for Gladewood Commons operations: property and landlord pipeline, demand validation, financial model, resident operations. Postgres on Supabase; hosted on Render.

Plan and assessment: `docs/CRM_BOOKKEEPING_PORTAL_PLAN.md`, `docs/PLAN_ASSESSMENT.md`.

## Layout

```
app/
  main.py        application factory, CORS, router registration, lifespan (DB pool)
  config.py      settings from environment or .env
  db.py          engine, session dependency, DATABASE_URL normalization
  auth.py        Supabase JWT verification, roles, require_staff / require_admin
  audit.py       append-only audit log writer
  models.py      SQLAlchemy models
  schemas.py     Pydantic request and response models
  crud.py        generic staff-only CRUD router factory (audited, paginated)
  routers/       health, users, records (properties, prospects, residents, conflict log), financials, demand
  routers/crm/   companies, contacts, pipelines, deals, activities, notes, timeline
  schemas_crm.py CRM request and response models
  crm_common.py  tags, CSV import and export, snapshot and diff helpers
  seed.py        default Gladewood pipelines (property, resident inquiry, referral partner)
  legacy_migration.py  dry-run migration of prospects, residents, properties into the CRM
  cli.py         python -m app.cli migrate-legacy | seed-pipelines
alembic/         migrations (run `alembic upgrade head`)
tests/           pytest suite (SQLite by default, Postgres when TEST_DATABASE_URL is set)
api_server.py    compatibility entry point; imports app.main:app
render.yaml      Render blueprint (secrets stay in the dashboard)
```

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | Yes | Supabase Postgres connection string. Pasted dashboard comment lines and the `pgbouncer` query flag are stripped automatically. |
| `CORS_ORIGINS` | Yes | Comma-separated browser origins allowed to call the API. Empty means no browser origin is allowed. |
| `SUPABASE_URL` | One of these two | Project URL; JWTs are verified against `/auth/v1/.well-known/jwks.json`. |
| `SUPABASE_JWT_SECRET` | One of these two | Legacy HS256 secret for projects that still use it. |
| `BOOTSTRAP_ADMIN_EMAILS` | First deploy | Emails that receive the `admin` role on their first login. Remove after the first admin exists. |
| `ENV` | No | `development`, `test`, or `production`. |

Copy `.env.example` to `.env` for local work. Never commit `.env`.

## Authentication and roles

Every endpoint except `GET /api/health` requires `Authorization: Bearer <Supabase access token>`.

- A user's first login creates a `users` row with role `pending` (or `admin` if the email is in `BOOTSTRAP_ADMIN_EMAILS`).
- Roles: `admin`, `staff`, `tenant`, `case_manager`, `pending`. The operations endpoints require `admin` or `staff`.
- Admins assign roles with `PUT /api/users/{id}/role`. `GET /api/me` returns the caller's role.
- Every create, update, delete, role change, and first login writes to `audit_log`. The application never updates or deletes audit rows.

## Run locally

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # fill in values
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

## Test and lint

```
python -m pytest -q
python -m pyflakes app tests alembic api_server.py
python -m bandit -q -ll -r app api_server.py
python -m pip_audit -r requirements.txt
```

Set `TEST_DATABASE_URL=postgresql+psycopg://...` to run the suite against Postgres. CI runs both, and also applies, rolls back, and re-applies the migrations against Postgres 16.

## CRM module (Phase 1)

All routes require `admin` or `staff`. Every write is audited; `GET /api/timeline?entity=deal&entity_id=5` merges audit entries, notes, activities, and stage moves for one record.

| Resource | Routes | Notes |
|---|---|---|
| Companies | `/api/companies`, `/export`, `/import` | Kinds: property_owner, brokerage, agency, hospital, employer, vendor, other |
| Contacts | `/api/contacts`, `/{id}/tags`, `/duplicates`, `/export`, `/import` | Filters: `q`, `kind`, `status` (`active`, `archived`, `all`), `company_id`, `tag`. Duplicates by email, phone, or name |
| Pipelines | `/api/pipelines`, `/{id}/summary` | Create and edit need `admin`; a stage holding deals cannot be removed |
| Deals | `/api/deals`, `/{id}/move`, `/export` | A move into a won or lost stage closes the deal; stage history is kept |
| Activities | `/api/activities`, `/{id}/complete`, `/export` | Kinds: task, event, call. Filters: `mine`, `overdue`, `due_before`, `open_only` |
| Notes | `/api/notes?entity=&entity_id=` | Only the author or an admin can edit or delete |

Every CRM record accepts `extra`, a flat JSON object of up to 30 snake_case keys, for fields that do not deserve a column yet. Resident and prospect records use initials as `display_name`; keep health, disability, and clinical details out of every field.

### Migrating the legacy tables into the CRM

```
python -m app.cli migrate-legacy            # dry run: prints scanned counts and every rejected row
python -m app.cli migrate-legacy --apply    # writes only when there are zero rejections
python -m app.cli migrate-legacy --apply --allow-partial --actor <your user id>
```

Prospects become `prospect` contacts plus deals in the Resident inquiry pipeline; residents become `resident` contacts; properties become deals in the Property pipeline linked by `property_id`. Money and date text is parsed and unparseable values are rejected. Re-running skips rows already migrated (`legacy_ref`). The legacy tables are left in place.

## Migrations

`alembic/versions/0001_baseline.py` adopts the existing production tables with `CREATE TABLE IF NOT EXISTS` and adds `users` and `audit_log`. Render runs `alembic upgrade head` before each deploy (`preDeployCommand` in `render.yaml`). New schema changes go in new revisions: `alembic revision -m "describe change"`.

## Phase 0 steps that need Paul

Verified against the Supabase, Render, and Netlify documentation on 2026-11-07. Direct links use `_`, which the Supabase dashboard resolves to the current project.

**Supabase**

1. Reset the database password: https://supabase.com/dashboard/project/_/database/settings (Database password, Reset). The old string was hand-copied at least once.
2. Get the connection string: click **Connect** in the top bar and choose **Session pooler** (port 5432). The direct connection is IPv6 by default and Render needs IPv4; the transaction pooler (port 6543) is for serverless. Paste the new password into the string.
3. Network restrictions (same Database Settings page): allow only Render's outbound IPs, found on the Render service under Settings, Outbound IP addresses. Needs Owner or Admin on the org.
4. Auth URLs: https://supabase.com/dashboard/project/_/auth/url-configuration. Site URL `https://psgccommandcenter.live`; add Redirect URL `https://psgccommandcenter.live/**`.
5. Browser key for the Command Center patch: https://supabase.com/dashboard/project/_/settings/api-keys. Use the **publishable** key (`sb_publishable_...`); `anon` is the legacy name. Never a `sb_secret_` or `service_role` key.
6. JWT mode: https://supabase.com/dashboard/project/_/settings/jwt. If a current signing key is listed (ES256, RS256, or EdDSA), set only `SUPABASE_URL` on Render. If the project still uses the legacy HS256 secret, either click **Migrate JWT secret** then **Rotate keys**, or set `SUPABASE_JWT_SECRET` on Render.
7. Project URL is `https://<Project ID>.supabase.co`; the Project ID is on Project Settings, General.
8. Backups: https://supabase.com/dashboard/project/_/database/backups/scheduled. Daily backups with 7 day retention are on Pro and above; Free has none. Add a nightly `pg_dump` to a private bucket and run one restore drill from it. PITR deferred (see `docs/PLAN_ASSESSMENT.md` Section 10).

**Render**

1. Service, **Environment** (left pane), **+ Add Environment Variable**: `DATABASE_URL`, `CORS_ORIGINS=https://psgccommandcenter.live`, `SUPABASE_URL` (or `SUPABASE_JWT_SECRET`), `BOOTSTRAP_ADMIN_EMAILS=paulselman@gladewoodcommons.com`, `ENV=production`. Choose **Save only** until the code is merged.
2. Service, **Settings**: Build Command `pip install -r requirements.txt`; Start Command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`; Health Check Path `/api/health`; Auto-Deploy **On Commit** or **After CI Checks Pass**; branch `master`.
3. Migrations: the **Pre-Deploy Command** `alembic upgrade head` is available only on paid instance types. On a Free instance, use this Start Command instead: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
4. After the first sign-in, remove `BOOTSTRAP_ADMIN_EMAILS` and choose **Save and deploy**.

**Netlify (Command Center)**

1. The site's security policy lives in `_headers` in the publish directory or in `netlify.toml` under `[[headers]]`. Add the Render API origin and `https://<Project ID>.supabase.co` to `connect-src`, and `https://cdn.jsdelivr.net` to `script-src`.
2. Apply the patch in `docs/DASHBOARD_INTEGRATION.md` and redeploy the site the same way as before.

**Then**

1. Merge PR #1. Check `https://<service>.onrender.com/api/health` returns `{"ok":true,"db":true}`.
2. Sign in from the Command Center with the magic link; Test should report Connected and Pull should load rows.
3. Run `python -m app.cli migrate-legacy` locally with the new `DATABASE_URL` in `.env`, review the rejections, then `--apply`.
4. Apply for Stripe ACH so Phase 3 is not blocked.
