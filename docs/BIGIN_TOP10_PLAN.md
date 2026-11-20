# Bigin Feature Evaluation and Top 10 Integration Plan

**Date:** 2026-11-20
**Purpose:** Pick the ten Bigin capabilities that matter for Gladewood Commons and plan how each lands in the custom CRM.

Evidence labels: **Source fact** (Bigin marketing pages fetched 2026-11-07; Paul's Bigin account metadata read through the Bigin connector on 2026-11-20, metadata and counts only, no record contents), **Analysis**, **Assumption**.

## 1. What Bigin offers (Source fact, bigin.com, 2026-11-07)

Modules: Contacts, Companies, Pipelines (deals), Products, Activities (tasks, events, calls), Notes, Dashboards. Capabilities listed on the features and pricing pages: team pipelines and sub-pipelines, connected pipelines, customizable stages, custom fields (10 per module on the higher edition), custom views, sheet view, tags, lookup and unique fields, timeline and audit log, instant and scheduled workflow automations, signals, two-way email, email templates, mass email with insights, no-code web forms, booking pages, target meter, duplicates cleanup, import and export, roles and profiles, built-in and third-party telephony, WhatsApp, business card scanner, AI, mobile app, document signing (Zoho Sign), file cabinet, and integrations (Gmail, Outlook, Calendar, Zoho Books, QuickBooks, Mailchimp, Zapier, Zoho Desk, Zoho Forms, Zoho Flow).

## 2. How Paul uses Bigin today (Source fact, account read 2026-11-20)

| Item | Finding |
|---|---|
| Contacts | 121 records; no custom fields; no tags; system views only |
| Companies | 130 records; no custom fields |
| Pipelines (deals) | **0 records**, although three pipeline layouts exist |
| Tasks, Events, Calls, Products | 0 records each |
| Pipeline layouts | **Sales Pipeline** (Bigin default: Qualification, Needs Analysis, Proposal, Negotiation, Closed Won, Closed Lost). **Resident Pipeline** (19 stages mixing resident steps such as New Lead, Contacted, Tour Scheduled, Toured, Application Sent, Application Complete, Under Review, Accepted, with partner steps such as Master Lease Signed, Company One Page Fact-sheet Sent, MOA Sent, MOA Signed, plus the default sales stages; probabilities run 7, 14, 21... in a straight line, which is auto-numbering rather than a designed forecast). **Grants and Donors** (Research, Application Draft, Submitted, Awarded, Declined, Closed Lost). |
| Resident Pipeline custom fields | Move_in_Target_Date, Room_Type_Preference, Budget_Range, Escalation_Flag, Application_Complete_Date, Decision, Lease_Start, Lease_End, Last_Touch_Date, Welcome_Step |
| Pipeline tags | Hot, tour, welcome, email-in, src-email, src-web, src-referral, src-phone |
| External sharing | Bigin "external share" views exist for all three layouts (a Bigin feature that lets outside people see a pipeline) |
| Automation in use | The Command Center pushes "engaged referral partners" into Bigin by name (upsert) through a Make webhook |

**Reading (Analysis):** Bigin is functioning as a referral-partner directory (contacts and companies) that the Command Center feeds. The pipeline, activity, and automation features are configured but unused. The Resident Pipeline layout combines two different processes (resident inquiry and partner agreement), which is why Phase 1 seeded them as separate pipelines. "Grants and Donors" belongs to the WASH nonprofit work, not Gladewood, and stays out of this CRM under the domain-isolation rule.

## 3. The top 10, ranked for Gladewood

Ranking weights: daily use by a one-person operator, direct effect on filling rooms and keeping referral partners engaged, and cost to build given what Phase 1 already has.

| # | Bigin feature | Why it matters to Gladewood | Custom CRM status | What gets built |
|---|---|---|---|---|
| 1 | **Team pipelines** with per-pipeline stages and custom fields | Three real processes: resident inquiry to move-in, property and landlord sourcing, referral partner engagement | Done (Phase 1): three pipelines seeded, stages with won and lost flags, `extra` fields | Migration 0003 promotes Paul's ten Resident Pipeline fields to typed columns on resident deals (move-in target, room preference, budget range, escalation flag, application complete date, decision, lease start and end, last touch, welcome step). Partner pipeline gets `agreement_status` (fact sheet sent, MOA sent, MOA signed) as a typed field instead of stages. |
| 2 | **Kanban pipeline view** with drag to move stage, plus list and sheet views | The screen Paul will live in; Bigin reviewers rate this highest | API done (`/deals`, `/deals/{id}/move`, summary); no UI | Staff app: kanban per pipeline with drag and drop, card shows contact, days in stage, next task; list view with column picker; inline edit |
| 3 | **Contacts and Companies** with lookups | 121 contacts and 130 partner organizations already exist | Done | One-time import from Bigin (contacts, companies, pipeline tags) into the custom CRM with `legacy_ref = bigin:<id>`; the Command Center's Make push is repointed to an API upsert endpoint |
| 4 | **Tags** | Paul's source tags (src-web, src-referral, src-phone, src-email) and stage-ish tags (tour, welcome, Hot) | Contacts only | Tags on deals and companies; `source` becomes a structured field on deals; tag filter and bulk tag in the UI |
| 5 | **Activities** (tasks, events, calls) with reminders and "my open" and "overdue" views | Zero activities in Bigin means follow-ups live in Paul's head today | API done; no UI, no reminders | Staff app: Today view (due and overdue), quick add from any record, complete in one click; daily email digest at 7 am of due and overdue items |
| 6 | **Workflow automations** (instant and scheduled) | The only way follow-ups happen without memory: new inquiry creates a call task due in 24 hours; stage Tour Scheduled creates the event; 5 days with no touch sets the escalation flag; Application Complete creates a review task; 30 days dormant partner creates a check-in task | Not built | Six hard-coded automations in the API plus a Render cron job every 15 minutes; each run logged to the audit trail; no general rule engine (per assessment) |
| 7 | **Web forms** into the pipeline | The marketing site already has Tour Request and Referral Inquiry forms (Netlify Forms); they should create a contact and a deal with `src-web` instead of landing in an inbox | Not built | Public `POST /api/forms/{inquiry,referral}` with rate limit and honeypot; the site's form handler posts there; form content never includes health details (Fair Housing notice stays on the form) |
| 8 | **Email templates, send from a record, log to timeline** | Welcome, tour confirmation, application received, partner fact sheet; Bigin tags show these are the recurring messages | Not built | Phase 2c: templates with merge fields, send through SMTP (Resend or Google Workspace), every send logged on the timeline, mass send to a filtered partner list with per-recipient log; two-way inbox sync deferred |
| 9 | **Saved views and duplicate control** | Bigin's My Deals, Closing This Month, Recently Modified, Unread; Paul's push already upserts by name | Filters done; duplicates for contacts done; no saved views; no upsert endpoint | `saved_views` table (name, module, filters, sort, columns) and a view switcher in the UI; `POST /api/contacts/upsert` and `/companies/upsert` matching on email, then phone, then name |
| 10 | **Dashboard and target meter** | One screen answering: how many inquiries this month, by source, conversion by stage, rooms to fill against the demand target, overdue follow-ups, partners gone quiet | Pipeline summary endpoint done | Staff app home: funnel per pipeline, source mix, time in stage, demand target meter (`demand_target` already stored), overdue count, dormant partners list |

## 4. Deliberately excluded

| Bigin feature | Reason |
|---|---|
| Built-in telephony, WhatsApp, call recording | Twilio later if call volume justifies it; no evidence of need (0 calls logged) |
| Business card scanner, AI assistant, mobile app | Responsive web covers phone use; the rest is cost without a Gladewood use |
| Products module | 0 products; room types are a field, not a catalog, until the Books phase |
| Grants and Donors pipeline | WASH nonprofit work; different entity, stays out of Gladewood data |
| Zoho Sign, Zoho Desk, Zoho Campaigns, marketplace | E-sign comes in Phase 3 with leases; the rest has no current use |
| Sub-pipelines and connected pipelines | Three flat pipelines cover the processes; add later only if a pipeline grows past ten stages |
| Bigin external share | Replaced by the portal's case-manager grants, which are scoped per tenant rather than per pipeline |

## 5. Build plan

| Phase | Features | API work | Staff app work | Exit check |
|---|---|---|---|---|
| **2a. Staff app foundation** | 1, 2, 3, 4, 5 | Migration 0003 (resident deal fields, partner agreement status, tags on deals and companies); Bigin import CLI; upsert endpoints | New repo `gladewood-staff-app` (Vite, React, TypeScript); sign-in (magic link plus password); contacts, companies, kanban, deal page, activities Today view, notes and timeline; CI with unit and browser tests | Paul runs a week of inquiries in the app with no spreadsheet; Bigin import shows 121 contacts and 130 companies with zero rejections |
| **2b. Automation and intake** | 6, 7, 9, 10 | Six automations plus cron; forms endpoints; saved views; dashboard queries | Dashboard home; saved view switcher; form success pages on the marketing site | A test tour request on the site creates a contact, a deal, and a call task within one minute; the 7 am digest arrives |
| **2c. Email** | 8 | Templates, send, log; provider credentials in Render | Compose from a record; template picker; partner mass send with preview | Welcome email sent from a deal appears on its timeline; partner send logs one row per recipient |
| **Cutover** | 3 | Repoint the Command Center's Make push to `/api/contacts/upsert`; freeze Bigin to read-only; export a final Bigin backup | | Bigin subscription cancelled after 30 days with no reads |

**Effort (Assumption):** 2a about 3 weeks, 2b about 3 weeks, 2c about 2 weeks of full-time work; scale by available hours. The order front-loads the screens Paul uses daily and defers email, which is the most integration-heavy piece.

## 6. Checked against the two-attempt rule

Each item above was checked twice: once against Bigin's own feature pages and once against Paul's account metadata. Items 6, 7, and 8 are the ones with external dependencies (cron, Netlify forms, an email provider) and are the likeliest to need a second attempt; their alternatives are recorded here in advance: a manual "run automations now" button if cron is unreliable on Render Free; a Netlify Forms webhook if direct POST from the site is blocked by its policy; and Supabase's SMTP relay if a separate provider is not wanted.

## 7. Decisions needed

1. Confirm the ten and the exclusions.
2. Confirm the Bigin import and cutover timeline (recommendation: import during 2a, cancel after 2b is live).
3. Email provider for 8: Resend, Postmark, or Google Workspace SMTP.
4. Name for the staff app repository (recommendation: `gladewood-staff-app`).
