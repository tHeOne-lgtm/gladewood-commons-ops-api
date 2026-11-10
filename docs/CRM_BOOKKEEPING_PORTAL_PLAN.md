# Gladewood Custom CRM, Bookkeeping, and Tenant/Case Manager Portal

**Status:** Approved with amendments on 2026-11-07. Phase 0 in progress.
**Owner:** Paul Selman, Gladewood Commons, LLC
**Disclaimer:** This plan is engineering guidance. It is not legal advice (not an attorney) and not accounting advice (not a CPA). Items marked "Verify" need review by your Tennessee landlord/tenant attorney or CPA before launch.

Evidence labels: **Source fact** (verified from a retrieved page or this repo), **Analysis** (my reasoning), **Assumption** (needs your confirmation).

## 0. Decision log

| Date | Decision | Effect on this plan |
|---|---|---|
| 2026-11-07 | Books module is an **accounts receivable subledger in this system plus a sync to Zoho Books**, not a full general ledger. Zoho Books is the book of record for the chart of accounts, bills, banking, reconciliation, and financial statements. | Section 5 rows marked "Build" for chart of accounts, journals, period locking, bills, expenses, banking, reconciliation, and financial statements change to "Zoho Books via sync". This system keeps tenancies, invoices, payments, deposits, rent roll, AR aging, and the portal, and pushes customers, invoices, and payments to Zoho Books. Phase 4 shrinks to the sync and its reconciliation report. |
| 2026-11-07 | Phase 0 starts. | See `docs/PLAN_ASSESSMENT.md` Section 6 for the added Phase 0 items. |
| 2026-11-07 | Phase 0 complete in code; Phase 1 (CRM core) built. | Custom fields are typed columns plus a bounded `extra` JSON object, not a field registry (per assessment Section 3.2). Saved custom views deferred; list filters cover the Phase 1 need. Workflows, email, forms, and dashboards remain Phase 2. Legacy tables are migrated by `python -m app.cli migrate-legacy` with a dry-run rejection report and are not dropped. |
| 2026-11-07 (Paul) | **The custom CRM stays and replaces Zoho Bigin.** Bigin and Make.com go dormant to cut subscriptions; either can be reactivated if client load grows. Custom tools are built, operated, and maintained on the n8n server (Mac mini). | The Oct 22 n8n decision "CRM = Bigin" is superseded. Agent A6, the Bigin half of the Zoho Connection Guide, the "refer to people by Bigin record ID" rule, and the Command Center sync (Make scenario 6382382, moving to n8n) all re-point to this API. Section 4 parity map is unchanged. New Phase 2 item: a machine credential (header auth) and webhooks so n8n can call this API without a Supabase user token. |
| 2026-11-07 (Paul) | **Full automation is the design target.** "Draft only, Paul approves every send" is the first operating stage, not the ceiling; Paul switches automations to act on their own once he is satisfied. Rule 11 handling stays in the n8n intake. | The rule engine in Section 4 is built as designed; the assessment's "hard-coded automations only" cut is reversed. Every automation action carries a mode, `draft` (queue for Paul's approval) or `auto`. All ship in `draft`; switching to `auto` is a per-automation setting that writes an audit entry. Portal and web-form submissions pass through the n8n Rule 11 router before anything is stored (Section 6). Fair Housing Rule 8 still applies: nothing publishes to a public channel without Paul. |
| 2026-11-09 (Paul) | **Oct 9 "Enhanced Build Plan" compared; three decisions taken** (see `docs/PLAN_COMPARISON_2026-11-09.md`). (1) The Command Center feed moves to **counts only**: no property, prospect, or resident records are pulled into the public HTML page; it shows the Today counts with links into the staff UI. (2) **Section 4 items 1 to 13 of the comparison are adopted** as plan scope. (3) **Staff MFA: Supabase Auth TOTP (authenticator app) is turned on for every staff and admin account, and the API refuses staff and admin tokens whose `aal` claim is not `aal2`.** Paul asked for the strongest reliable option; TOTP was chosen over SMS (SMS is weaker and a paid Supabase add-on) and over passkeys (not a stable Supabase Auth feature; from memory, not checked this session). | Section 7 gains data tiers; Section 9 Phase 2 gains `GET /api/today`, `decision_log`, `consents`, `lookup_values`, the stuck-in-stage and weekly keyword-scan n8n jobs; migration 0003 adds `next_action_at` and the open-deal owner/status/next-action constraint; `import_batches` with undo and duplicate review lands before the legacy migration applies. Four gates (design locked, real data allowed, resident login allowed, go-live) each need Paul's yes. Items 1, 4, 7, 8, and 9 are done before the legacy migration applies. `tools/command_center_patch.py` changes from the full Pull to counts only. Staging project and "Oct 9 plan superseded" were explained to Paul on 2026-11-09 and are still open. |
| 2026-11-10 (Paul) | **Zoho Books API check passed** (`tools/zoho_books_check.sh`, Step 14): token exchange HTTP 200, `GET /books/v3/organizations` HTTP 200. Source fact: Paul pasted the two status lines. This proves the Free plan accepts API calls, closing the point on which Zoho's pages disagreed (Section 10, item 4). First run failed with `invalid_code` (single-use grant code); second run passed. Refresh token is in Paul's password manager only. | Organization line (Paul, 2026-11-10): name "Gladewood Commons" (trailing space in Zoho; trim before any name match), `organization_id` 943655056, plan_name FREE, plan_type 100, currency USD, time zone America/New_York, default org. Refresh token saved in Paul's password manager (Paul, 2026-11-10). No CPA engaged yet (Paul, 2026-11-10), so the accounting basis stays at Zoho's default (accrual) and the opening-balance date is unset; both are recorded when a CPA is engaged. Open: engage a CPA before the first invoice. The write-scope grant for Phase 4 stays unissued. |
| 2026-11-10 (Paul) | **Zoho Books setup reported done** (Paul: "done", against `docs/ZOHO_BOOKS_SETUP.md`). Taken to cover Steps 1 to 13 and the confirmation that resident names, emails, and payment records live in Zoho Books as the book of record. Not checked: the live organization (not reachable from here). | Still to record here: accounting basis (Step 2), Zoho `organization_id` (Step 14), Books go-live date, and the Step 14 API check result (two HTTP status lines). Resident customers are created only at lease signing; no health, accommodation, or screening text in Books. |

## 1. Decision summary

**Recommendation (Analysis):** Build one system with three surfaces on top of the existing FastAPI + Postgres (Supabase) backend:

1. **CRM module** with Bigin-equivalent functions for the workflows Gladewood runs (pipelines, contacts, companies, activities, automations, email, reports).
2. **Books module** with Zoho Books-equivalent bookkeeping (double-entry ledger, invoices, payments, bills, banking, reconciliation, financial statements).
3. **Portal** for tenants and case managers (balances, documents, payments, maintenance requests).

**On "identical" (Analysis):** Literal one-to-one parity with Bigin is not a sensible target. Bigin ships built-in telephony, WhatsApp, a mobile app, a business card scanner, AI assistant, a marketplace of add-ons, and 30+ third-party integrations (Source fact, bigin.com/pricing, retrieved 2026-11-07). Cloning all of that costs far more than it returns. This plan gives full parity on the core data model and workflow engine, and uses a vendor API (Gmail, Twilio, Stripe, Plaid) for the rest.

**Cheaper alternative to weigh (Analysis):** Bigin lists Zoho Books, Zoho Invoice, QuickBooks, and Zoho Sign integrations on its higher edition (Source fact, same page), and Zoho Books has its own Customer Portal that supports payments and custom modules (Source fact, zoho.com/books/help/customer-portal). A Zoho-only setup would not model rooms, beds, vouchers, or third-party payers well. That gap is the main reason to build custom.

## 2. What exists today

**Source fact (this repo, `api_server.py`):**

- One file, FastAPI, `psycopg2` against Supabase Postgres via `DATABASE_URL`.
- Tables: `properties`, `prospects`, `residents`, `conflict_log`, `financials` (key/value).
- No authentication, no users, no roles.
- CORS is `allow_origins=["*"]`.
- Money and dates are stored as `TEXT`.
- `residents` and `prospects` store initials and free-text `notes`.
- No ledger, invoices, payments, documents, or maintenance tables.

**Analysis (blockers before any portal ships):**

| Blocker | Why it blocks the portal |
|---|---|
| No auth or authorization | Tenants and case managers cannot be isolated from each other's data |
| Open CORS and unauthenticated writes | Any site can read or alter resident records |
| Money as TEXT | Cannot support a ledger or reconciliation |
| Free-text `notes` on residents | Invites health or disability details that Fair Housing and ADA rules restrict |
| Single file | Four more modules will not fit; needs routers and migrations |

## 3. Target architecture

**Stack (Assumption, confirm in Section 9):**

- **API:** FastAPI modular monolith (routers per module), Pydantic v2, SQLAlchemy 2 + Alembic migrations, psycopg 3.
- **DB:** Existing Supabase Postgres. `NUMERIC(14,2)` for money, `TIMESTAMPTZ` for time, `DATE` for dates.
- **Auth:** Supabase Auth issuing JWTs; FastAPI verifies the token and loads a role. Staff use MFA.
- **Front ends:** One React/Next.js repo with two apps: `/staff` (CRM + Books) and `/portal` (tenants, case managers). Portal on its own subdomain and CORS origin.
- **Payments:** Stripe (card and ACH Direct Debit) using hosted Checkout or Payment Element, so card data never touches Gladewood servers (PCI SAQ A scope). Webhooks with signature check and idempotency keys.
- **Bank feeds:** Plaid (or manual CSV import in Phase 3).
- **Files:** Supabase Storage private buckets, signed URLs, 5 minute expiry.
- **Email:** Gmail API / SMTP provider for two-way mail and templates. Telephony and SMS via Twilio in a later phase.
- **Jobs:** Scheduled worker (Render cron) for recurring invoices, late fees, reminders, bank sync.
- **Hosting:** Render (already in use per README).

**Modules and boundaries (Analysis):**

```
api/
  core/        auth, roles, audit log, config, db
  crm/         contacts, companies, pipelines, deals, activities, products, workflows, email, reports
  books/       accounts, journal, invoices, payments, bills, expenses, banking, reports
  housing/     properties, rooms, leases, tenancies, deposits, maintenance, documents
  portal/      read/write endpoints scoped to the logged-in tenant or case manager
  integrations/ stripe, plaid, gmail, twilio
```

The portal never queries CRM or Books tables directly. It calls `portal/` services that apply access grants (Section 6).

## 4. CRM module: Bigin parity map

**Source fact (bigin.com pages retrieved 2026-11-07):** Bigin modules are Contacts, Companies, Pipelines (deals), Products, Activities (tasks, events, calls), Notes, Dashboards. It also has team pipelines and sub-pipelines, timeline, audit log, workflows (instant and scheduled), signals, custom fields (10 per module on the higher edition), tags, lookup/unique/user fields, import/export, duplicate cleanup, roles and profiles, web forms, mass email with insights, email templates, and target meter.

| Bigin capability | Plan | Phase |
|---|---|---|
| Contacts, Companies, Notes, Tags | Build | 1 |
| Pipelines, stages, kanban + list views, sub-pipelines, team pipelines | Build | 1 |
| Activities (tasks, events, calls), reminders, calendar | Build; Google Calendar sync later | 1 |
| Custom fields and custom views (more than Bigin's limit) | Build (JSONB + field registry) | 1 |
| Timeline and audit log | Build (append-only) | 1 |
| Import/export, duplicate cleanup | Build | 1 |
| Roles and profiles | Build | 1 |
| Products (rooms/bed types as products) | Build; ties into Books items | 2 |
| Web forms (inquiry, referral, maintenance) | Build | 2 |
| Workflows (instant, scheduled) | Build rule engine: trigger, condition, action. Every action has a `draft` or `auto` mode; all start in `draft` (decision log, 2026-11-07) | 2 |
| Two-way email, templates, mass email + tracking | Build on Gmail API; every send obeys the action mode, so drafts queue for Paul until he switches that automation to `auto` | 2 |
| Dashboards, reports, target meter | Build | 2 |
| Document signing | Integrate (Dropbox Sign or DocuSign) | 3 |
| Telephony, call recording, WhatsApp | Integrate (Twilio); defer | 4 |
| Business card scanner, AI assistant, marketplace | Not building | n/a |

**Gladewood-specific pipelines (Analysis):** Property/landlord (existing), Resident inquiry to move-in (replaces `prospects`), Referral partner/case manager outreach, Maintenance.

## 5. Books module: Zoho Books parity map

**Amended 2026-11-07 (see Decision log):** rows below marked "Build" for general ledger functions are superseded. This system builds only the AR subledger (tenancies, invoices, recurring rent, payments, deposits, rent roll, AR aging) and a one-way sync of customers, invoices, and payments into Zoho Books through its API. Zoho Books owns the chart of accounts, journals, bills, banking, reconciliation, period locks, and statements. The ledger rules at the end of this section still apply to the subledger: every invoice and payment is immutable once synced, and corrections are credit notes or reversing payments.

**Source fact (zoho.com/books features and help index, retrieved 2026-11-07):** Zoho Books covers chart of accounts, manual and recurring journals, base currency adjustments, transaction locking, customers and vendors, invoices, recurring invoices, payments received, retainer invoices, payment links, bills, vendor credits, expenses, purchase orders, banking with feeds and transaction rules, reconciliation, customer and vendor portals, reminders, timesheets, taxes, multi-currency, reports, and API.

| Zoho Books capability | Plan | Phase |
|---|---|---|
| Chart of accounts (asset, liability, equity, income, expense) | Build; seed a rental-property chart | 3 |
| Double-entry journal, manual and recurring journals | Build; immutable lines, reversal entries only | 3 |
| Transaction locking by period | Build | 3 |
| Customers (tenants, payers) and vendors | Link to CRM contacts, one identity | 3 |
| Invoices, recurring invoices, credit notes | Build; monthly rent profiles per tenancy | 3 |
| Payments received, apply to invoices, refunds | Build; Stripe webhooks post to ledger | 3 |
| Payment links, online pay | Build via Stripe | 3 |
| Reminders and late fee rules | Build via scheduler | 3 |
| Bills, vendor credits, expenses, receipts | Build | 4 |
| Banking: feeds, rules, categorize, reconcile | Build on Plaid; CSV fallback | 4 |
| Reports: P&L, balance sheet, trial balance, cash flow, AR aging, general ledger | Build | 4 |
| Property-level tracking (class/location) | Build; every line tagged `property_id` | 3 |
| Rent roll, occupancy, deposit liability report | Build (not in Zoho Books by default) | 3 |
| 1099 vendor tracking | Build | 4 |
| Multi-currency, inventory, timesheets, purchase orders | Not building | n/a |
| Retainer invoices (retention) | Not building | n/a |

**Ledger rules (Analysis):**

- Every financial event writes a balanced `journal_entry` (sum of debits equals sum of credits) in one DB transaction.
- Journal lines are never updated or deleted. Corrections are reversing entries.
- Invoice, payment, and bill tables are subledgers that reference journal entries.
- Security deposits post to a liability account, not income. **Verify** with your attorney whether Tenn. Code Ann. Title 66, Chapter 28 requires a separate deposit account and what notice and return timelines apply.
- Master lease rent paid to property owners posts to expense with the master lease on a separate contract record from resident subleases (matches your commercial vs residential separation rule).
- Third-party payers (vouchers, case manager agencies) are payers on a payment, not owners of the tenancy balance.

## 6. Portal design

### Roles

| Role | Can see | Can do |
|---|---|---|
| Tenant | Own balance, invoices, payment history, lease, documents shared with them, own maintenance requests | Pay (card, ACH), set autopay, download documents, submit and comment on maintenance requests, update contact info |
| Case manager | Only for tenants who granted access: balance due, payment status, due dates, and documents the tenant chose to share | Make a payment on the tenant's behalf, upload voucher or agency payment documents, message Gladewood |
| Staff | Everything per role | Full CRM and Books |

### Access grants (Analysis)

A `portal_access_grants` table controls case manager visibility: `tenancy_id`, `case_manager_user_id`, `scope` (`balance`, `payments`, `documents`), `granted_by_tenant_at`, `expires_at`, `revoked_at`. Every portal query joins this table. Default is no access. Tenants can revoke in the portal. Every read of a grant-scoped record writes to the audit log.

### Fair Housing and ADA boundary (Analysis)

- Gladewood provides independent shared housing. It does not provide medical care, medication administration, personal care, or supervision.
- **No** diagnosis, medication, psychiatric, disability, or clinical fields in any table, form, or portal screen.
- Maintenance requests have a free-text description. Add an inline notice: "Do not include health information." Staff can redact.
- Accommodation requests, complaints, and privacy requests are not a workflow in this system (Rule 11; decision log, 2026-11-07). Every portal and web-form submission that carries free text, maintenance requests included, is posted to the n8n `SYS Rule 11 Referral Intake` router before it is stored. If the router flags it, this system keeps only a text-free marker (date, channel, category) and the n8n intake emails Paul and writes its own log; the text never lands in this database. Unflagged submissions are stored as normal. Counsel's review of the keyword list is an open item on the n8n side.
- Replace the free-text `notes` columns on `residents` and `prospects` with structured fields plus a short operational note field, and apply the same notice.
- Examples, demos, and training data use "Resident A" placeholders. No real resident data, occupancy numbers, or addresses in mockups.

### Portal features by phase

- **Phase 2:** login, profile, document list, maintenance request submit/track.
- **Phase 3:** balances, invoices, pay now, autopay, receipts, case manager role and grants.
- **Phase 4:** payment plans, statements export, e-sign of lease addenda.

## 7. Core data model (first cut)

**Core/auth:** `users`, `roles`, `user_roles`, `audit_log`
**CRM:** `contacts`, `companies`, `pipelines`, `pipeline_stages`, `deals`, `activities`, `notes`, `tags`, `custom_field_defs`, `workflow_rules`, `email_messages`, `email_templates`
**Housing:** `properties`, `rooms`, `master_leases`, `tenancies`, `deposits`, `documents`, `maintenance_requests`, `maintenance_comments`, `portal_access_grants`
**Books:** `accounts`, `journal_entries`, `journal_lines`, `invoices`, `invoice_lines`, `recurring_invoice_profiles`, `payments`, `payment_allocations`, `vendors`, `bills`, `bill_lines`, `expenses`, `bank_accounts`, `bank_transactions`, `reconciliations`, `period_locks`

**Data tiers (adopted 2026-11-09, comparison item 7).** Every table is labelled in its model docstring and here. *Business:* `properties`, `rooms`, `master_leases`, `pipelines`, `pipeline_stages`, `deals`, `deal_stage_history`, `activities`, `tags`, `record_tags`, `import_batches`, `lookup_values`, `audit_log`, the Books tables, `financials`. *Personal:* `contacts`, `companies` (contact details), `notes`, `users`, `tenancies`, `deposits`, `documents`, `maintenance_requests`, `maintenance_comments`, `portal_access_grants`, `decision_log`, `consents`, `email_messages`. *Restricted:* `conflict_log` (legacy, stays unmigrated), incidents, screening results, and anything from the Rule 11 path; these stay out of this system until each has Paul's approval, a named access list, and read logging. Nothing in any tier stores diagnoses, medical history, or disability status (Fair Housing Rule 5).

**Migration of existing data (Analysis):** `properties` maps to `properties`; `prospects` become `contacts` + `deals` in the inquiry pipeline; `residents` become `contacts` + `tenancies`; `conflict_log` becomes `activities` of type incident, staff-only; `financials` key/values move into a planning table, separate from the ledger. Text money and date columns are parsed and validated during migration with a rejection report for bad values.

## 8. Security and compliance checklist

- Replace `allow_origins=["*"]` with an explicit allowlist (staff and portal origins).
- All endpoints require a verified JWT except `/api/health` and public web forms (rate limited, captcha).
- Authorization in the service layer, plus Postgres row-level security as a second layer for portal tables.
- Secrets only in Render environment variables. Never log DSNs or tokens (the current masking code is a good pattern to keep).
- Encrypt sensitive columns (bank account tokens, government ID if ever collected). Store Stripe and Plaid tokens, never raw account numbers.
- Stripe webhooks: verify signature, store event ID, process once.
- Backups and point-in-time recovery enabled on Supabase; restore drill before go-live.
- Audit log is append-only and covers logins, grant changes, document access, ledger postings, period locks.
- Tenant screening data (credit, background) follows FCRA adverse action rules. **Verify** with your attorney before storing screening reports.
- Background-check and criminal-history screening criteria follow HUD guidance and Fair Housing Act. **Verify** policy with your attorney.

## 9. Phased delivery

| Phase | Scope | Exit criteria |
|---|---|---|
| **0. Foundation** | Split `api_server.py` into modules; Alembic; Supabase Auth; roles; audit log; CORS allowlist; CI with tests; staging environment | Every existing endpoint works behind auth; tests pass; no wildcard CORS |
| **1. CRM core** | Contacts, companies, pipelines, deals, activities, notes, tags, custom fields, views, import/export, timeline | Existing prospect and property data migrated; pipelines usable daily |
| **2. CRM automation + portal v1** | Rule engine with per-action `draft`/`auto` mode, email, forms, dashboards; machine credential and webhooks for n8n; portal login, documents, maintenance requests routed through the n8n Rule 11 intake | A test tenant submits a maintenance request that appears as a staff task; a flagged test submission reaches Paul through n8n and leaves no text in this database |
| **3. Books core + portal payments** | Chart of accounts, journal, invoices, recurring rent, payments (Stripe), deposits, rent roll, AR aging, case manager role | A test tenant pays rent online and the ledger balances; trial balance equals zero difference |
| **4. Books full** | Bills, expenses, bank feeds, reconciliation, P&L, balance sheet, cash flow, 1099 | One month closed and locked; reconciliation ties to the bank statement |
| **5. Integrations** | E-sign, Twilio, Google Calendar sync, accounting export | As prioritized |

**Rough effort (Assumption, one full-time engineer):** Phase 0 about 2 weeks, Phase 1 about 4, Phase 2 about 4, Phase 3 about 6, Phase 4 about 6. Treat as an estimate to refine, not a quote.

**Automation runtime (decided 2026-11-07):** jobs that touch outside services (Gmail, Google Sheets, Google Calendar, the Galen feed, the Anthropic API) run in n8n on the Mac mini and call this API through its machine credential. The rule engine inside this system handles rules over its own data (deal moved, invoice overdue, task due). The Make scenarios move to n8n per Paul's document "Command Center: Moving from Make.com to n8n" (received 2026-11-07); that document's two Bigin nodes in the Command Center Sync workflow re-point to this API, and its Step 1 (a fresh `docker run` and a Funnel on `/webhook`) is not followed as written, because the live stack is the compose project in `~/gladewood-n8n` with the Funnel limited to `/webhook/gc`. Import the workflows into that stack and put the sync webhook under the `gc/` path.

## 10. Decisions needed from Paul

1. **Stack:** Confirm FastAPI + Postgres + React/Next.js, or name a different front end.
2. **Payments:** Stripe for card and ACH? Do any residents pay through housing authority or agency checks that need manual posting?
3. **Bank feeds:** Plaid in Phase 4, or CSV import only at first?
4. **Accounting handoff:** Resolved 2026-11-07: Zoho Books is the book of record (decision log), on the **Free plan**. Checked against zoho.com/us/books pricing, the plan comparison, and the API-limit KB article on 2026-11-07 (Source fact): Free includes invoices, recurring invoices, credit notes, payments, customer portal, bank reconciliation, P&L and balance sheet, 1 user plus 1 accountant, 1,000 invoices a year, and 1,000 API requests a day (the comparison table and KB say so; the summary pricing page lists API under Standard, so confirm with one live call before building the sync). Free ends when revenue for the financial year passes $50K; Standard ($15 a month billed annually) then adds bank feeds, custom fields, and period locking. Sync design consequences: Free has no custom fields, so the ID mapping lives in this system plus Zoho's invoice `reference_number`; no bank feeds, so reconciliation is CSV import until Standard; no period locking or workflow rules, so this subledger's immutability rule is the lock and n8n stays the automation layer. Tiller or a custom ledger is not needed.
5. **Case manager scope:** Confirm access is limited to balance, payment status, and documents the tenant chooses to share, with written tenant authorization on file.
6. **Phase order:** Resolved: Phase 0 and 1 are built. Still open: which CRM pipelines matter most for daily use.
7. **Attorney review:** Schedule review of deposit handling, late fees, case manager authorization form, and screening policy before Phase 3.
8. **n8n documents to update (Rule 10 style, once):** `~/gladewood/CLAUDE.md` (Oct 22 "CRM = Bigin" decision and the Bigin record ID rule), `~/gladewood/docs/Gladewood-Zoho-Connection-Guide.md` (Bigin half), and the archived A6 agent prompt, so they point at this API. Paul's call whether to edit now or when Bigin is switched off.
9. **Switch-off order for Bigin and Make:** export Bigin (contacts, companies, pipelines, notes) before the subscription ends and run the import here; keep Make's Command Center Sync on for 7 days after the n8n version is live, per Paul's migration document, Step 11.

## 11. Open risks

| Risk | Severity | Mitigation | Review cadence |
|---|---|---|---|
| Scope creep toward "identical to Bigin" | High | Parity map in Section 4 is the contract; changes go through Paul | Each phase |
| Ledger errors | High | Double-entry constraint, reversal-only corrections, test suite on posting rules, CPA review of chart and reports | Each phase, monthly after launch |
| Portal data exposure | High | Access grants, RLS, audit log, penetration test before Phase 3 | Before launch, then quarterly |
| Fair Housing or ADA exposure from stored data | High | No clinical fields, form notices, attorney review | Each schema change |
| Payment disputes and ACH returns | Medium | Webhook reconciliation, return handling posts reversing entries | Monthly |
| Single-engineer bus factor | Medium | Docs, tests, migrations in repo | Quarterly |

Voice check: 37/40
