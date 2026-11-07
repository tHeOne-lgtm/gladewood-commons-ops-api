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

These cannot be done from the repository.

1. Rotate the Supabase database password (Supabase dashboard, Project Settings, Database) and update `DATABASE_URL` in Render. The old string was hand-copied at least once.
2. Set `CORS_ORIGINS` in Render to the dashboard's origin. Until it is set, browsers cannot call the API.
3. Set `SUPABASE_URL` (or `SUPABASE_JWT_SECRET`) and `BOOTSTRAP_ADMIN_EMAILS=paulselman@gladewoodcommons.com` in Render, deploy, sign in once, then remove `BOOTSTRAP_ADMIN_EMAILS`.
4. Turn on Supabase daily backups (Pro plan) and a nightly `pg_dump` to a private bucket, then run one restore drill from the dump. PITR deferred; see `docs/PLAN_ASSESSMENT.md` Section 10.
5. Apply for Stripe ACH Direct Debit so Phase 3 is not blocked.
6. Dashboard: `https://psgccommandcenter.live` (Netlify, single static HTML file, source on Paul's Mac). Set `CORS_ORIGINS=https://psgccommandcenter.live`. Apply the patch in `docs/DASHBOARD_INTEGRATION.md` so the page sends the Supabase access token on every request.
