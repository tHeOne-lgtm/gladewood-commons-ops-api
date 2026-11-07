# Pre-Phase 0 Assessment: CRM, Bookkeeping, and Portal Plan

**Scope:** Independent review of `docs/CRM_BOOKKEEPING_PORTAL_PLAN.md` and the current `api_server.py` before any Phase 0 work starts.
**Date:** 2026-11-07
**Disclaimer:** Engineering assessment only. Not legal advice (not an attorney) and not accounting advice (not a CPA). Items marked "Verify" need your Tennessee attorney or CPA.

Evidence labels: **Source fact** (verified by running a command or reading a file in this repo, or a retrieved vendor page), **Analysis** (my reasoning), **Assumption** (needs your confirmation).

## 1. Verdict

**Proceed with Phase 0, with five changes to the plan before Phase 1 (Analysis):**

1. Re-decide build versus buy for the Books module before Phase 3. The double-entry ledger, bank reconciliation, and financial statements are the costliest and riskiest 12 weeks in the plan, and they are the least differentiated. A thin accounts receivable subledger in this system plus a sync to QuickBooks Online or Zoho Books gets you online rent collection and tenant balances in Phase 3 at roughly half the effort.
2. Cut the Bigin parity target for the workflow engine and custom fields to what Gladewood runs today. A general rule engine is a multi-month project on its own.
3. Treat the effort estimate as calendar time of 2 to 3 times the stated weeks. The plan assumes one full-time engineer; you are an ED nurse and a student.
4. Add seven Phase 0 items the plan omits (Section 6).
5. Fix two live defects in the current API during Phase 0 (Section 4).

Scores (1 low to 5 high, Analysis): Efficiency 3, Effectiveness 4, Viability 2, Risk posture 3, Security design 4, Current code health 2.

## 2. Strengths

| Strength | Rationale |
|---|---|
| Parity maps are explicit (build, integrate, skip) | Prevents the "identical to Bigin" goal from turning into unbounded scope. The skip list (telephony, card scanner, AI assistant, marketplace, multi-currency, inventory) removes the most expensive and least relevant features. |
| Portal access model is correct by design | Default no access, tenant-granted scopes for case managers, expiry and revocation, audit on every grant-scoped read. This matches the Fair Housing boundary and gives you an evidence trail. |
| No clinical fields anywhere | Removing free-text `notes` and adding form notices is the right control. It makes the independent-living boundary structural rather than a policy people have to remember. |
| Ledger rules are sound | Balanced entries in one transaction, immutable lines, reversal-only corrections, deposits as a liability, period locks. These are the rules a CPA will expect. |
| Phase 0 puts auth and CORS first | Nothing user-facing ships before the security floor exists. |
| Existing DSN-masking code | `_mask_dsn_for_log` never prints a password, even on malformed input (Source fact, `api_server.py`). Keep that discipline. |

## 3. Weaknesses and concerns

### 3.1 Viability (score 2)

- **Operator capacity (Analysis):** The 22 week estimate assumes 40 hours per week. At 8 to 10 hours per week the calendar is 12 to 18 months. The risk is not the technology; it is a half-finished ledger that nobody can close the month in.
- **Books module is the long pole (Analysis):** Reconciliation, ACH return handling, 1099 tracking, and financial statements each have edge cases that take weeks to get right. Zoho Books and QuickBooks Online already handle them and your CPA already knows one of them.
- **No front end exists in this repo (Source fact).** The README refers to an "operations dashboard" but the repo holds only the API. The plan's React/Next.js assumption adds a second codebase, build pipeline, and deployment. **Assumption:** the dashboard lives outside this repo; its location and stack change the Phase 0 scope.
- **Stripe ACH for a housing LLC (Assumption):** Stripe approves ACH Direct Debit per account and may ask for business documentation. Apply during Phase 0 so Phase 3 is not blocked.

### 3.2 Efficiency (score 3)

- **Custom fields via JSONB plus a field registry (Analysis):** This is a platform feature. For one operator with a known schema, typed columns plus Alembic migrations are faster to build, easier to query, and safer to validate. Add a small JSONB `extra` column per module for the rare one-off.
- **Workflow engine (Analysis):** Bigin's instant and scheduled automations are a general trigger-condition-action system. Gladewood needs perhaps six automations: inquiry received, stage changed, move-in scheduled, rent due in 5 days, rent overdue, maintenance request opened. Hard-code them as scheduled jobs and event handlers in Phase 2; add a rule table only if the list passes 15.
- **Two front-end apps (Analysis):** One app with role-based routing halves the build and deploy surface. Keep the portal on its own subdomain by routing, not by separate deployment, until traffic or risk justify a split.
- **Phase 1 before Phase 2 portal (Analysis):** The maintenance-request portal in Phase 2 depends on only `tenancies`, `documents`, and `maintenance_requests`. It could ship inside Phase 1 and give tenants value before the CRM is complete.

### 3.3 Effectiveness (score 4)

- **Migration of TEXT money and dates (Analysis):** The plan names a rejection report but not a dry-run. Add a migration dry-run command that prints every row that would fail parsing, run it against production data before the real migration.
- **Rent roll and deposit liability report (Analysis):** Correctly identified as missing from Zoho Books. These two reports are the most valuable custom output in the plan and should be in Phase 3, not later.
- **Third-party payers (Analysis):** The plan models vouchers and agency payments as payers on a payment. It does not yet model a partial-payer split (for example an agency pays a fixed amount and the tenant pays the balance). Add `expected_payer_splits` on the tenancy in Phase 3.

## 4. Diagnostics on the current code

All findings below are **Source fact** from commands run on 2026-11-07 unless marked otherwise.

| # | Finding | Evidence | Severity | Recommendation |
|---|---|---|---|---|
| D1 | Database connection opens at import time; the module cannot be imported without a reachable database | `env -u DATABASE_URL python3 -c "import api_server"` raises `RuntimeError`; an unreachable host raises `OperationalError` | High | Move connection setup into the FastAPI `lifespan`; inject a connection dependency. Without this, no unit tests can run. |
| D2 | One global `psycopg2` connection with `autocommit = True`, no pool, no reconnect | `db = psycopg2.connect(...)` at module scope; `make_crud` reuses `db` | High | If the Supabase pooler drops the idle connection, every request fails until Render restarts the process. Use `psycopg_pool` or SQLAlchemy's pool with `pool_pre_ping`. |
| D3 | CORS allows every origin, every method, every header, with no authentication on any write endpoint | `allow_origins=["*"]` plus unauthenticated `POST`, `PUT`, `DELETE` | High | Any website can read or delete resident rows if it knows the URL. Phase 0 item; already in the plan. |
| D4 | `demand_summary` computes `screened` and never returns it; the API returns `verified` under the key `screened_verified` | pyflakes: `local variable 'screened' is assigned to but never used` (line 376) | Low | Either return both counts or remove the dead variable. The dashboard may be showing the wrong number. |
| D5 | `DELETE` returns `200 {"deleted": id}` even when the row does not exist | `delete_row` never checks `rowcount` | Low | Return 404 when `rowcount == 0`. |
| D6 | Requirements are unpinned | `requirements.txt` lists `fastapi`, `uvicorn[standard]`, `psycopg2-binary`, `pydantic` with no versions | Medium | Pin with a lock file (`pip-compile` or `uv lock`). An upstream major release can break a deploy with no code change. |
| D7 | No tests, no CI workflow, no deploy manifest in the repo | `.github/workflows` absent; no `test_*` files; no `render.yaml` | Medium | Phase 0 adds all three. Add `render.yaml` so the deployment is reviewable and reproducible. |
| D8 | Bandit flags five `B608` SQL string-construction sites | `make_crud` builds `SELECT`, `INSERT`, `UPDATE`, `DELETE` with f-strings | Informational | Verified not exploitable: table and column names come from hard-coded Python lists; all user values go through `%s` parameters. Keep it that way, and add a `# nosec B608` with a comment, or switch to SQLAlchemy Core in Phase 0, which removes the question. |
| D9 | Bandit flags `B104` bind to `0.0.0.0` | `uvicorn.run(app, host="0.0.0.0", ...)` | Informational | Correct for Render; document it. |
| D10 | DSN-extraction code exists to recover from a pasted connection string that included dashboard comment text | `_extract_dsn` and `_normalize_dsn` docstrings | Low | The code is defensive and safe. The process it compensates for is the risk: a connection string with the database password was copied by hand at least once. Rotate the Supabase database password during Phase 0 and store the new one only in Render. |
| D11 | `Pydantic.dict()` is deprecated in Pydantic v2 | `item.dict()` in `make_crud`; installed Pydantic is 2.13.5 | Low | Use `model_dump()`. |
| D12 | No pagination or limits on list endpoints | `SELECT * FROM {table} ORDER BY id` | Low | Fine at current scale; add `limit` and `offset` before the CRM tables grow. |
| D13 | Hard-coded `target: 6` in `demand_summary` | line 383 | Low | Move to the planning key/value table. |

## 5. Security review of the plan

| Area | Plan status | Gap and recommendation (Analysis unless noted) |
|---|---|---|
| Authentication | Supabase Auth JWT, staff MFA | Good. Add: short access-token lifetime, refresh rotation, and a `portal` audience claim so a staff token cannot be replayed against portal endpoints and vice versa. |
| Authorization | Service layer plus Postgres RLS | Mixing is a known footgun. If FastAPI connects with the service-role key, RLS does not apply. Decide one of two patterns: (a) FastAPI is the policy enforcement point and RLS is defense in depth using `SET LOCAL request.jwt.claims` per transaction, or (b) the portal front end talks to Supabase directly under RLS and FastAPI handles staff only. Pattern (a) is simpler to audit; choose it and write it down. |
| Case manager grants | Table with scope, expiry, revocation, audit | Add: a stored copy of the signed tenant authorization (document reference on the grant), a maximum grant duration (12 months, then renew), and a monthly report of active grants for your review. |
| Payments | Stripe hosted elements, webhook signature, idempotency | Good. Add: handle `charge.refunded`, `payment_intent.payment_failed`, and ACH `charge.dispute.created`; post each as a reversing entry; never mark an ACH payment as cleared until the settlement event. |
| File uploads | Private buckets, signed URLs, 5 minute expiry | Add: content-type allowlist (PDF, PNG, JPEG), size cap, filename sanitization, and malware scanning for anything a tenant or case manager uploads. |
| Logging | Never log DSNs or tokens | Add: never log request bodies on portal endpoints; redact email and phone in structured logs; set log retention to 30 days. |
| Data minimization | No clinical fields | Add a written data inventory listing every column that holds personal data, its purpose, and its retention period. Delete inquiry records that never convert after 12 months. |
| Breach response | Not addressed | Tennessee has a data breach notification statute (Tenn. Code Ann. 47-18-2107). **Verify** notice timelines with your attorney and write a one-page response plan before the portal goes live. |
| Screening data | FCRA and HUD marked Verify | Correct. Add: store screening results outside this system (in the screening vendor) and keep only the decision and date here. |
| Secrets | Render environment variables | Add: rotate the Supabase password (D10), enable Supabase network restrictions to Render's egress IPs, and turn on Supabase audit logging. |
| Backups | PITR and a restore drill | Good. Schedule the restore drill as a Phase 0 exit criterion, not a later task. |
| Dependency hygiene | Not addressed | Pin versions, enable Dependabot or Renovate, run `pip-audit` in CI. |
| Rate limiting | Only on public forms | Add rate limits on login, password reset, and payment endpoints. |

## 6. Phase 0 additions

Add these to the Phase 0 scope in the plan (Analysis):

1. Move the database connection into `lifespan` with a pool and `pool_pre_ping` (D1, D2).
2. Pin dependencies and add a lock file (D6).
3. Add `pytest` with a test database, and a CI workflow that runs tests, `pyflakes`, `bandit`, and `pip-audit` (D7).
4. Add `render.yaml` (D7).
5. Rotate the Supabase database password and restrict network access (D10).
6. Apply for Stripe ACH approval so Phase 3 is not blocked.
7. Locate the existing dashboard front end, record its stack and location in the README, and decide whether it becomes the staff app or is replaced.

Fix D4 and D5 in Phase 0 as well; both are small and both affect data correctness.

## 7. Risk register (updated)

| Risk | Likelihood | Impact | Mitigation | Owner | Review |
|---|---|---|---|---|---|
| Operator time runs out mid-Books module | High | High | Decide build versus buy for Books before Phase 3; ship AR subledger plus accounting sync first | Paul | Before Phase 3 |
| Portal exposes one tenant's data to another | Low with plan, High today | High | Phase 0 auth and CORS; RLS pattern (a); penetration test before Phase 3 | Paul | Each phase |
| Ledger does not balance or cannot be closed | Medium | High | Balanced-entry constraint, posting tests, CPA review of chart of accounts, monthly close checklist | Paul and CPA | Monthly after Phase 3 |
| Fair Housing or ADA exposure from stored data | Low with plan | High | No clinical fields, form notices, data inventory, attorney review of forms | Paul and attorney | Each schema change |
| Production connection drops and the API stays down | High today | Medium | D2 fix in Phase 0; health check pings the database | Paul | Phase 0 |
| Migration corrupts money or date values | Medium | High | Dry-run migration with rejection report against a production copy | Paul | Phase 1 |
| Stripe ACH not approved in time | Medium | Medium | Apply in Phase 0 | Paul | Phase 0 |
| Dependency break on deploy | Medium today | Medium | Pin and lock; Dependabot | Paul | Phase 0 |
| Single engineer, no documentation | Medium | Medium | Architecture decision records in `docs/`, tests as documentation | Paul | Quarterly |

## 8. Evaluation plan

Measure each phase against these, and stop the phase if the gate fails (Analysis):

| Phase | Gate | How to measure |
|---|---|---|
| 0 | Every existing endpoint works behind auth; tests pass in CI; wildcard CORS gone; restore drill done | CI green; manual check from a non-allowlisted origin returns a CORS error; a restored copy of the database serves `/api/properties` |
| 1 | Prospect and property data migrated with zero rejected rows; pipelines used daily for two weeks | Migration report; count of deals moved per week |
| 2 | Test tenant submits a maintenance request that appears as a staff task within one minute | End-to-end test in CI |
| 3 | Test tenant pays rent online; trial balance difference is zero; rent roll matches the tenancy table | Posting tests; a `trial_balance` query asserting `SUM(debits) = SUM(credits)` |
| 4 | One real month closed, locked, and reconciled to the bank statement within 5 business days | Close checklist signed by you and your CPA |

## 9. Decisions needed before Phase 0

1. Books module: build the full ledger, or AR subledger plus sync to QuickBooks Online or Zoho Books? (Recommendation: subledger plus sync.)
2. Where does the existing dashboard front end live, and what is it built with?
3. Weekly hours you can commit, so the phase calendar is honest.
4. Approval to rotate the Supabase database password during Phase 0.
5. Approval to apply for Stripe ACH during Phase 0.

Voice check: 37/40
