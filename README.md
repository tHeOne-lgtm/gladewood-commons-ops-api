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
| `REQUIRE_STAFF_MFA` | No (default `false`) | When `true`, `admin` and `staff` tokens must carry Supabase's `aal` claim at `aal2` (an authenticator code was entered this session). `GET /api/me` still answers and reports `mfa_required` so a page can prompt for the code. Turn on only after every staff account has enrolled a TOTP factor. |
| `ENV` | No | `development`, `test`, or `production`. |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | For WhatsApp | From the Twilio console. The auth token also validates incoming webhooks. |
| `TWILIO_WHATSAPP_FROM` | For WhatsApp | The WhatsApp sender in E.164, for example `+14155238886`. |
| `PUBLIC_BASE_URL` | For WhatsApp | `https://gladewood-commons-ops-api.onrender.com`; used to validate Twilio signatures and as the status callback. |
| `TWILIO_VALIDATE_SIGNATURE` | No | Default `true`. Set `false` only for local testing. |
| `FORMS_WEBHOOK_SECRET` | For Netlify Forms | The JWS secret you type into the Netlify form notification; the API rejects unsigned deliveries to `/api/forms/netlify`. 32 or more random characters. |
| `FORMS_RATE_LIMIT_PER_HOUR` | No | Default `10` submissions per IP per hour on the public form endpoints. |
| `EMAIL_PROVIDER` | For email | `resend` (metrics through its webhook), `smtp` (Google Workspace relay, no metrics), or `log` (default; nothing leaves, rows are still written). |
| `EMAIL_FROM` | For email | Sender, for example `Paul Selman <paul@gladewoodcommons.com>`. The domain must be verified at the provider. |
| `EMAIL_REPLY_TO` | No | Reply-To address when different from the sender. |
| `EMAIL_POSTAL_ADDRESS` | For email | Physical postal address printed in every footer (CAN-SPAM). Campaigns refuse to send without it. |
| `EMAIL_UNSUBSCRIBE_SECRET` | For email | Signs unsubscribe links; 32 or more random characters. |
| `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET` | With `resend` | API key with sending access; the `whsec_...` secret shown when the webhook is created. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | With `smtp` | STARTTLS relay. |

Copy `.env.example` to `.env` for local work. Never commit `.env`.

## Authentication and roles

Every endpoint except `GET /api/health` requires `Authorization: Bearer <Supabase access token>`.

- A user's first login creates a `users` row with role `pending` (or `admin` if the email is in `BOOTSTRAP_ADMIN_EMAILS`).
- Roles: `admin`, `staff`, `tenant`, `case_manager`, `pending`. The operations endpoints require `admin` or `staff`.
- Admins assign roles with `PUT /api/users/{id}/role`. `GET /api/me` returns the caller's role and `mfa_required`.
- Staff MFA (decided 2026-11-09): staff enroll a TOTP authenticator in Supabase Auth. With `REQUIRE_STAFF_MFA=true` the API refuses `admin` and `staff` tokens whose `aal` claim is not `aal2`; `GET /api/me` is the one staff route that still answers, so the page can ask for the code.
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
| Contacts | `/api/contacts`, `/{id}/tags`, `/duplicates`, `/export`, `/import` | Filters: `q`, `kind`, `status` (`active`, `archived`, `all`), `company_id`, `tag`. Duplicates by email, phone, or name. Import rows that match an existing contact or an earlier row are listed under `duplicates` and skipped unless `?allow_duplicates=true` |
| Imports | `/api/imports`, `/{id}`, `/{id}/undo` | Every CSV import and the legacy migration is a batch; rows carry `import_batch_id`. Undo (admin) deletes the batch's rows once |
| Pipelines | `/api/pipelines`, `/{id}/summary` | Create and edit need `admin`; a stage holding deals cannot be removed |
| Deals | `/api/deals`, `/{id}/move`, `/export` | An open deal must have `owner_id` (defaults to the caller) and `next_action_at`; the database enforces the same rule. A move into a won or lost stage closes the deal and clears `next_action_at`; reopening needs a new one. Stage history is kept |
| Activities | `/api/activities`, `/{id}/complete`, `/export` | Kinds: task, event, call. Filters: `mine`, `overdue`, `due_before`, `open_only` |
| Notes | `/api/notes?entity=&entity_id=` | Only the author or an admin can edit or delete |
| Decisions | `/api/decisions`, `/{id}` | Append-only application decision log: entity (`deal` or `contact`), written criteria version, met or not, outcome (`approved`, `declined`, `withdrawn`), a reason of 500 characters or fewer. The reason must name the criterion; a reason containing a protected-trait, health, or care word is refused with the words listed. No edit or delete route; `retain_until` is two years out (Fair Housing Rule 11) |
| Consents | `/api/consents`, `/{id}/withdraw` | One active consent per contact per type (`sms`, `email`, `calls`, `portal`, `partner_sharing`) with source and times. Withdraw keeps the row; recording again after withdrawal starts a new row. `app.consents.has_consent()` is the check any message draft runs first |
| Today | `/api/today` | Counts of overdue and due-today deals and activities for the caller and for everyone, plus the caller's own items by title. No contact records, so it can feed the Command Center |

Every CRM record accepts `extra`, a flat JSON object of up to 30 snake_case keys, for fields that do not deserve a column yet. Resident and prospect records use initials as `display_name`; keep health, disability, and clinical details out of every field.

### Migrating the legacy tables into the CRM

```
python -m app.cli migrate-legacy                               # dry run: prints scanned counts and every rejected row
python -m app.cli migrate-legacy --apply --actor <your user id> # writes only when there are zero rejections
python -m app.cli migrate-legacy --apply --allow-partial --actor <your user id>
```

Prospects become `prospect` contacts plus deals in the Resident inquiry pipeline; residents become `resident` contacts; properties become deals in the Property pipeline linked by `property_id`. Money and date text is parsed and unparseable values are rejected. Re-running skips rows already migrated (`legacy_ref`). The legacy tables are left in place. `--actor` is required with `--apply`: that user becomes the owner of every open deal, the apply date becomes each open deal's first `next_action_at`, and the run is recorded as an import batch that an admin can undo with `POST /api/imports/{id}/undo`.

## WhatsApp (Twilio)

Point the Twilio WhatsApp sender's inbound webhook at `POST /api/webhooks/twilio/whatsapp` and its status callback at `POST /api/webhooks/twilio/status`, both on the public API URL. Every inbound message is signature-checked, matched to a contact by phone (or creates a `prospect` tagged `src-whatsapp`), records WhatsApp consent (a STOP keyword withdraws it), and opens a Resident inquiry deal when the contact has none open. Staff read and reply through `GET /api/conversations`, `GET /api/conversations/{phone}/messages`, `POST /api/conversations/{phone}/read`, and `POST /api/messages/whatsapp`. Replies outside the 24 hour window need `allow_outside_window` and an approved template on the Twilio side.

## Web forms (Phase 2b, item 7)

Two public endpoints take the marketing site's forms straight into the CRM, with no bearer token: `POST /api/forms/inquiry` (Tour Request, room inquiry) and `POST /api/forms/referral` (Referral Inquiry from a case manager, coordinator, or employer). Both accept JSON or form-encoded bodies, tolerate the usual field name variants (`full_name`, `tel`, `comments`, `first_name` plus `last_name`), drop any submission whose hidden `website` honeypot field is filled, and limit each IP to `FORMS_RATE_LIMIT_PER_HOUR`. A submission matches an existing contact by email, then by phone; otherwise it creates one (`source=web`, tag `src-web`). It leaves the message as a note, records email consent when the person opted in, opens a deal in the right pipeline when the contact has none open, and creates the first follow-up task. Netlify Forms can also deliver to `POST /api/forms/netlify`, which verifies Netlify's JWS signature with `FORMS_WEBHOOK_SECRET`. Setup for the marketing site is in `docs/FORMS_INTEGRATION.md`. Forms must not ask for health, disability, or benefit details; nothing in these endpoints stores them.

## Automations (Phase 2b, item 6)

Five hard-coded rules in `app/automations.py` run every 15 minutes from the Render cron job (`python -m app.cli run-automations`), and staff can run them on demand with `POST /api/automations/run` (`?dry_run=true` reports what would happen without writing). Each firing is recorded in `automation_runs`, so a rule never repeats itself for the same record, and in the audit log.

| Rule | Trigger | Action |
|---|---|---|
| `inquiry_callback` | Resident deal at Inquiry with no open activity | Task "Call back new inquiry" due in 24 hours |
| `tour_event` | Any deal at a stage named Tour scheduled with no event | Event on the deal's next action date at 3 pm UTC |
| `stale_escalation` | Open deal whose next action is 5 or more days overdue | `escalation_flag` set on the deal plus a high priority task due in 4 hours; the flag clears on the next run after staff set a current next action |
| `application_review` | Resident deal at Income verified | Task "Review application" due in 2 days |
| `partner_checkin` | Partner deal with no update or activity for 30 days | Task "Check in with partner" due in 2 days, at most once per 30 days |

`GET /api/automations/rules` lists the rules with the last time each fired. The 7 am email digest waits for the email phase.

## Email templates, 1:1 send, campaigns, digest (Phase 2c, items 9 and 10)

`app/emailing.py` renders `{{merge_field}}` templates (`first_name`, `display_name`, `email`, `company_name`, `deal_title`, `stage_name`, `next_action_at`, `room_preference`, `move_in_target`, `sender_name`, `unsubscribe_url`), appends the footer (postal address, Equal Housing Opportunity line, unsubscribe link) to every message, and sends through `app/email_provider.py`. Templates and ad hoc bodies are refused when they contain a protected-trait term from `app/fair_housing.py` or an unknown merge field. Five starter templates are seeded by migration 0008 (`seed-email-templates` adds any that are missing).

Consent gate: a marketing send (`marketing=true` or any campaign) needs an active `email` consent. A transactional send needs only that the contact has an email, is active, has not unsubscribed, and has not bounced. Every send, including skipped ones, is a row in `emails` and an `email.out` item on the contact and deal timelines.

| Route | What |
|---|---|
| `GET/POST /api/email/templates`, `GET/PUT /api/email/templates/{id}` | Templates (`include_inactive=true` to list retired ones) |
| `POST /api/email/preview` | Rendered subject, text, and HTML for a template or ad hoc body against a contact or deal, with the skip reason if it could not send |
| `POST /api/email/send` | 1:1 send; `409` with `skip_reason` when gated, `502` when the provider refuses |
| `GET /api/email/log` | Sends by contact, deal, or campaign |
| `GET/POST /api/email/unsubscribe/{token}` | Public; withdraws email consent. Also the RFC 8058 one-click target in the `List-Unsubscribe` headers |
| `POST /api/webhooks/resend` | Resend events (Svix signature): delivered, opened, clicked, bounced, complained. A bounce blocks future sends; a complaint also withdraws consent |
| `GET/POST /api/campaigns`, `GET/PUT /api/campaigns/{id}`, `POST .../cancel` | Campaigns; `scheduled_at` makes the cron send it |
| `POST /api/campaigns/{id}/preview` | Recipient count, skip reasons, sample, rendered copy |
| `POST /api/campaigns/{id}/send` | Sends now; a rerun after a crash never sends a recipient twice |
| `GET /api/campaigns/{id}/report` | Counts by status, opens, clicks, unsubscribes since the send |

Segments (`segment` on a campaign) accept only `contact_kind`, `company_kind`, `source`, `tags_any`, `tags_none`, `pipeline`, `stages`, `deal_status`, and `contact_ids`; any other key is a `422`. That keeps health, disability, and benefit details out of targeting by construction.

Cron: the 15 minute job also runs `send-due-campaigns`; a daily `send-digest` job emails each staff member their due and overdue list. Provider setup is in `docs/EMAIL_SETUP.md`.

## Dashboard and saved views (items 10 and 2)

`GET /api/dashboard?days=30` returns one payload for the staff app home: resident inquiries in the window by source (contact source: web, whatsapp, referral, phone, email, other), the resident funnel (deals that reached each stage in the window, open now, median days in stage), conversion (inquiries, moved in, closed without move-in, rate), overdue deals and activities, referral partners quiet for 30 days, channel volume (WhatsApp in and out, emails sent, opened, bounced), and the demand target (`demand_target` in financials, default 6) against open deals at Deposit received or Confirmed.

`GET/POST /api/views`, `PUT/DELETE /api/views/{id}`: named filter sets per list screen (`contacts`, `companies`, `deals`, `activities`). Filters are allowlisted per entity (`VIEW_FILTER_KEYS` in `app/schemas_crm.py`); any other key is a `422`. Views are shared by default; a private view is visible only to its owner. Owners and admins edit or delete.

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

1. Service, **Environment** (left pane), **+ Add Environment Variable**: `DATABASE_URL`, `CORS_ORIGINS=https://psgccommandcenter.live`, `SUPABASE_URL` (or `SUPABASE_JWT_SECRET`), `BOOTSTRAP_ADMIN_EMAILS=paulselman@gladewoodcommons.com`, `ENV=production`, `PYTHON_VERSION=3.12.8`. Choose **Save only** until the code is merged.
2. Merge PR #1 first; Settings changes redeploy the current `master`, and the new start command needs the `app` package. Then Service, **Settings**: Build Command `pip install -r requirements.txt`; Start Command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`; Health Check Path `/api/health`; Auto-Deploy **On Commit** or **After CI Checks Pass**; branch `master`.
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
