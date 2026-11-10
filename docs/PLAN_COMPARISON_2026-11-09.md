# Comparison: "GC Housing CRM, Enhanced Build Plan" (Oct 9, 2026) against the current plan

Written 2026-11-09 for Paul. Compares the Oct 9 Softr-based plan with `CRM_BOOKKEEPING_PORTAL_PLAN.md`, `PLAN_ASSESSMENT.md`, and the code in this repo.

**How I know each item:** "compared docs" (the Oct 9 text against the two plan docs), "compared code" (`app/models.py`, `alembic/versions`, `app/routers`, tests), "vendor page" (softr.io/pricing and zoho.com fetched 2026-11-09 and 2026-11-07), or "not checked".

## 1. Bottom line (Analysis)

The Oct 9 plan and the current plan agree on the foundation (Supabase as the single source of truth, FastAPI on Render for jobs, no health data, row-level isolation, audit log, staging before real data). They differ on three things, and on all three the current plan is the one to keep:

1. **Screens.** Oct 9 buys them from Softr Pro ($99 a month, or $74 billed annually; vendor page). The 2026-11-07 decision is to cut subscriptions, and Softr Pro does not list two-factor authentication (that is on Business at $329) or audit logs (Enterprise). Oct 9 itself names "route screens through the FastAPI backend" as its fallback; that fallback is what has been built.
2. **Identity.** Oct 9 admits Softr signs into Supabase with one database login per app, so per-person security rests on Softr's filters. The current build verifies each person's Supabase token in the API, which is the stronger model Oct 9 wanted.
3. **Scope.** Oct 9 has no bookkeeping, no payments, no Zoho Books, and no automation runtime. The current plan has the AR subledger, Stripe, the Zoho Books sync, n8n, and the Rule 11 routing, none of which existed on Oct 9.

Where Oct 9 is better is operations design: the Today screen, required owner/status/next action, import batches with undo, the decision log, consents, data tiers, four go/no-go gates, pilot metrics, and a pre-mortem with fallbacks. The current plan should adopt those. Section 4 lists exactly what to add.

## 2. Side by side (compared docs and code)

| Area | Oct 9 plan | Current plan and build | Verdict |
|---|---|---|---|
| Source of truth | Supabase Postgres | Same, through the FastAPI API | Same |
| Screens | Softr Pro | Not built. Open decision: Command Center screens versus a separate staff app (HANDOFF, Phase 2) | Current plan wins on cost and security; the build hours are the real price (Section 5) |
| Who checks access | Softr filters plus RLS keyed to a shared database login | API checks every request against the person's Supabase JWT and role; RLS planned as a second layer for portal tables, not yet written (compared code: no RLS in migrations) | Current is stronger; RLS still owed |
| Staff MFA | Required, unresolved on Softr Pro | Stated in plan Section 3, not configured (not checked in Supabase dashboard) | Both open; Supabase Auth TOTP removes the vendor question |
| Audit log | Database triggers so it does not depend on Softr's plan | `audit_log` table written by the API (compared code) | Same intent; add trigger-level coverage for direct DB edits later |
| Data model | 25 blueprint tables plus 5 new (status_history, consents, decision_log, import_batches, lookup_values) | Built: users, audit_log, contacts, companies, pipelines, stages, deals, deal_stage_history, activities, notes, tags, record_tags, plus legacy tables. Planned: housing, books, portal grants | Names differ (organizations vs companies, inquiries/applicants vs deals in the inquiry pipeline, service_requests vs maintenance_requests). Keep current names; add Oct 9's five new tables |
| Required owner, status, next action | Enforced by the database | `deals.owner_id` nullable, `next_action` defaults to empty (compared code) | Adopt Oct 9's rule |
| Today screen, stuck-in-stage alert | Yes, from status_history | `deal_stage_history` exists; no Today endpoint or alert | Adopt |
| Imports and duplicates | Import batches with undo, duplicate check, 100-row test with 10 planted duplicates | `migrate-legacy` with dry run and rejection report; no batch id, no undo, no duplicate check (compared code) | Adopt |
| Fair Housing records | decision_log with criteria used and reason; no protected traits | Section 8 says verify screening storage with attorney; no decision log | Adopt; it also satisfies Rule 11's "application decisions with reasons, kept 2 years" |
| Health data rule | None in CRM; weekly scan of free-text fields | Same rule; plus the n8n Rule 11 router screens every free-text submission before storage (decision 2026-11-07) | Current is stronger at intake; add Oct 9's periodic scan |
| Incidents | Restricted tier, switched off at launch | `conflict_log` kept as a legacy table; plan maps it to staff-only incident activities | Adopt Oct 9's "off until approved" and the three-tier labels |
| Accommodation requests, complaints | Not covered (written the day the Fair Housing rules were adopted) | Routed to the n8n Rule 11 intake, text never stored here | Current only |
| Bookkeeping, payments | charges and payments tables only; no ledger, no Stripe | AR subledger, Stripe, Zoho Books Free as book of record | Current only |
| Automation | Softr workflows (10K actions a month cap) | n8n plus a rule engine with per-action draft/auto mode | Current only |
| Command Center feed | Daily counts only (overdue, due today, new inquiries), never names | Today's sync card pulls full property, prospect, and resident records into the browser (the Pull dialog you saw on 2026-11-07) | Oct 9 is stricter; decision for Paul (Section 6) |
| Staging | Separate Supabase project and Softr workspace; monthly restore to staging | Plan Section 9 lists staging in Phase 0; none exists (not checked beyond HANDOFF, which does not mention one) | Adopt; one Supabase Free project is allowed as the second free project |
| Backups | Daily, restore test monthly | Supabase Free has none; Pro or nightly `pg_dump` pending (HANDOFF) | Same gap in both; Oct 9 sets a cadence |
| Gates | Four: design locked, real data allowed, resident login allowed, go-live | Phase exit criteria only | Adopt the four gates |
| Pilot metrics | Six blueprint targets plus "Today screen opened 4 of 5 days" | None stated | Adopt |
| Timeline | 90 days, about 150 hours at 12 hours a week | Phases in engineer-weeks; assessment says multiply by 2 to 3 for calendar time | Both optimistic; Oct 9's fallback "ship Phases 0 to 3 only" is the right shape |
| Blueprint scorecard | Formula bug found (SUMPRODUCT on the wrong columns) | Not used here | Fix only if the workbook is still consulted |

## 3. Where the Oct 9 plan is now superseded (Analysis)

- **Softr Pro.** Vendor page, 2026-11-09: Pro is $99 monthly or $74 billed annually, 10 team users, 50 client users, 10K workflow actions a month, Supabase listed as a Pro integration. "Two-factor authentication (2FA)" appears under Business ($329 monthly, $264 annually). "Audit logs" appears under Enterprise. So Oct 9's open decision 1 (can Pro enforce staff MFA) answers itself: not as a listed feature. With Supabase Auth, MFA is a project setting, not a vendor tier.
- **One database login per Softr app.** Oct 9 says the Softr connector cannot pass each person's identity to row-level security, so it proposed `softr_staff` and `softr_portal` logins and Softr-side filters. That makes Softr's filter configuration the only thing between a resident and another resident's row. The current build never exposes the database to the browser at all; the API is the only reader, and it knows who is asking.
- **No ledger, no payments, no Zoho Books.** Oct 9 stops at charges and payments as tables. Online rent collection, deposits, rent roll, AR aging, and the CPA handoff were decided on 2026-11-07 and are not in Oct 9's scope at all.
- **Automation.** Oct 9's automations run inside Softr against a monthly action cap. The 2026-11-07 decision puts outside-service automation in n8n (already running on the Mac mini) and in-system rules in the API, each action starting in draft mode.
- **Rule 11.** Oct 9 has no path for accommodation requests, complaints, or privacy requests. The n8n intake now handles those for the website and will take portal submissions too.

## 4. What to adopt from the Oct 9 plan (recommended changes to the current plan)

Each is small and none conflicts with a 2026-11-07 decision.

1. **Required fields on open records.** Database constraint: an open deal (or later, an open maintenance request or tenancy case) must have `owner_id`, a status, and a `next_action_at` date. Add `next_action_at` to `deals`; make `owner_id` non-null for open deals via a check constraint. Phase 2, migration 0003.
2. **Today endpoint.** `GET /api/today`: overdue and due-today activities and deals for the signed-in staff member, plus counts. Feed the Command Center from the counts. Phase 2.
3. **Stuck-in-stage alert.** n8n scheduled workflow reads `deal_stage_history` through the API and drafts a note when a deal has had no activity for 14 days (starting value). Draft mode, per the 2026-11-07 rule.
4. **Import batches.** `import_batches` table; every imported row carries `import_batch_id`; an admin can undo a batch; duplicate check on email, phone, and normalized name before insert, with a review list instead of silent merge. Extend `migrate-legacy` to write a batch id now, before it runs for real. Phase 1 follow-up.
5. **Decision log and consents.** `decision_log` (record, criteria version, criteria met or not, reason, decided_by, decided_at; no protected traits, no free text beyond the reason) and `consents` (contact, consent type, given_at, withdrawn_at, source). Retention 2 years minimum per Rule 11. Phase 2.
6. **Lookup values.** Stage names and categories already live in `pipeline_stages`; add a small `lookup_values` table for categories that are not stages (request types, document classes) so wording changes without a migration. Phase 2.
7. **Data tiers.** Label every table Business, Personal, or Restricted in the plan's Section 7 and in each model's docstring. Restricted tables (incidents, screening results) stay out until they have an approval, an access list, and logging. `conflict_log` stays legacy and unmigrated until then.
8. **Four gates.** Design locked (before migration 0003 adds housing and books tables), real data allowed (before the legacy migration applies), resident login allowed (before any portal account), go-live. Each needs your explicit yes after the tests in item 10 pass.
9. **Staging.** A second Supabase Free project (`gladewood-commons-ops-staging`) and a Render branch service, fictional data only. Restore the production dump into it once a month.
10. **Test gates.** Copy Oct 9's table: role-by-table access script, resident and partner isolation (two of each, by screen and by direct link), 100-row import with 10 planted duplicates, required-field refusal, each automation fires once, backup restore row counts match, audit log shows edit, delete, and view.
11. **Pilot metrics.** Record completeness 90% or more, overdue tasks over 2 business days at most 5, median first response within 1 business day, portal privacy 100%, adoption 85% or more, backup checks 100%, Today screen opened on at least 4 of 5 workdays.
12. **Pre-mortem fallbacks.** Builder time: if two phases in a row finish more than a week late, freeze scope at CRM plus intake and push residents and portal later. Side spreadsheets: set a read-only date. Flagged words in notes: weekly scan through the same keyword list the n8n Rule 11 router uses, so there is one list for counsel to review.
13. **Periodic free-text scan.** Weekly n8n job calls an API endpoint that scans notes and request text for the Rule 11 keyword list and reports counts only.

## 5. Cost (vendor pages; Analysis on the hours)

| | Oct 9 plan | Current plan |
|---|---|---|
| Screens | Softr Pro $1,188 a year monthly, $888 annually | $0; built in-house |
| Database and auth | Supabase Free or Pro ($0 or $300 a year) | Same |
| API hosting | Render (existing) | Render Starter $84 a year once the Free sleep is a problem |
| Bookkeeping | Not in scope | Zoho Books Free ($0 under $50K revenue; Standard $180 a year after) |
| Automation | Inside Softr's action cap | n8n, $0 (Mac mini already running); Anthropic API usage for the directory workflows, estimated $5 to $10 a month in Paul's migration document |
| Subscriptions dropped | None named | Bigin, Make (2026-11-07 decision) |

The honest difference is not dollars but hours. Oct 9 assigned about 68 of its 150 hours to Softr screen phases (2, 3, and 5). In the current plan those hours become front-end build hours, and a hand-built staff UI plus portal will take more than 68 hours (Assumption; no estimate exists yet because the Command Center versus separate app decision is open). That is the one place the Oct 9 plan is cheaper, and it is the trade you chose on 2026-11-07.

## 6. Decisions for Paul

Status 2026-11-09: items 1, 2, and 3 decided by Paul (1: counts only; 2: adopt items 1 to 13; 3: Paul asked for the strongest reliable option, and Supabase TOTP with the API requiring `aal2` for staff and admin was chosen). Items 4 and 5 were explained to Paul the same day and are open. Recorded in the plan's decision log.

1. **Command Center feed.** Keep the full Pull of properties, prospects, and residents into the browser, or move to Oct 9's counts-only daily summary plus links into the staff UI? Counts-only is the safer default for a public HTML page (DASHBOARD_INTEGRATION Section 5 already warns about resident data in that page).
2. **Adopt items 1 to 13 in Section 4** as Phase 2 scope, or pick a subset. My recommendation: all, with items 1, 4, 7, 8, and 9 before the legacy migration applies, since they are the gate conditions for "real data allowed".
3. **Staff MFA.** Turn on Supabase Auth TOTP for your account now (project setting, Free plan; Assumption that no add-on is needed, flagged in the assessment Section 10) and make the API refuse staff tokens without the `aal2` claim. Yes or no.
4. **Staging project.** Create `gladewood-commons-ops-staging` in Supabase (your account; I cannot create projects) so Phase 2 work and the import tests never touch production.
5. **The Oct 9 plan's status.** Mark it superseded by this comparison, keeping its operations design as adopted above, so there is one plan of record.

## 7. What this comparison did not check

- The GC Housing CRM Blueprint workbook (six sheets) that Oct 9 reviewed: not on disk in this repo, not read.
- Supabase dashboard settings (MFA, Auth providers, whether a staging project already exists): not checked this session.
- Softr's Supabase connector behavior: taken from Oct 9's own statement, not tested.
