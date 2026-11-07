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

## Migrations

`alembic/versions/0001_baseline.py` adopts the existing production tables with `CREATE TABLE IF NOT EXISTS` and adds `users` and `audit_log`. Render runs `alembic upgrade head` before each deploy (`preDeployCommand` in `render.yaml`). New schema changes go in new revisions: `alembic revision -m "describe change"`.

## Phase 0 steps that need Paul

These cannot be done from the repository.

1. Rotate the Supabase database password (Supabase dashboard, Project Settings, Database) and update `DATABASE_URL` in Render. The old string was hand-copied at least once.
2. Set `CORS_ORIGINS` in Render to the dashboard's origin. Until it is set, browsers cannot call the API.
3. Set `SUPABASE_URL` (or `SUPABASE_JWT_SECRET`) and `BOOTSTRAP_ADMIN_EMAILS=paulselman@gladewoodcommons.com` in Render, deploy, sign in once, then remove `BOOTSTRAP_ADMIN_EMAILS`.
4. Enable point-in-time recovery on Supabase and run one restore drill.
5. Apply for Stripe ACH Direct Debit so Phase 3 is not blocked.
6. Record where the dashboard front end lives and what it is built with; it must send the Supabase access token on every request.
