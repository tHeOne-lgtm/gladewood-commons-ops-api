# Underwriting per property (Prospect Hub port)

Built 2026-11-21 on the owner's backlog item 2 (2026-11-20) and Atlas gap 6. The Prospect Hub's underwriting view
(artifact BH7nsdF1LXHVEEfSqasFAz) now lives in the API; the staff app page that renders it is the next step in the
GLADEWOOD-staff-app repository, which is not on this Mac.

## What is in the API

| Route | Does |
|---|---|
| `GET /api/underwriting` | One summary row per property: stage, deal type, beds, cash flow, coverage, break-even, cash-on-cash, targets met, or what is missing. The Hub's underwriting board. |
| `GET /api/underwriting/{property_id}` | The full view: stored fields, resolved inputs (overrides merged with settings), calc, checks, three scenarios, 5-year projection. Works before any edit (`exists: false`, defaults shown). |
| `PUT /api/underwriting/{property_id}` | Upsert. Fields: `deal_type` (lease or buy), `private_rooms`, `shared_rooms` (2 beds each), `bedrooms`, `lease_cost`, `sale_price`, `utilities`, `inputs` (per-property overrides, see below), `notes`. Omitted fields keep their value. Audit `underwriting.create` or `underwriting.update` with the changes. |
| `POST /api/underwriting/{property_id}/stage` | The stage drop-down: Found, Contacted, Toured, Underwriting, Negotiating, Leased, Passed. Audit `underwriting.stage` with `{"stage": [from, to]}`. Nothing else fires yet (see below). |
| `GET /api/underwriting/{property_id}/summary.txt` | The copy-to-text block. 409 with the missing list when the model cannot run. |
| `GET /api/underwriting/{property_id}/export.csv` | The CSV export. |
| `GET` and `PUT /api/underwriting/settings` | Planning defaults and targets (the Hub's Settings page). PUT takes `{"values": {key: number}}`; unknown keys are refused. Audit `underwriting.settings`. |

Overrides accepted in `inputs` (the Hub's `record.uw` keys): `mode`, `privRent`, `sharedRent`, `occ`, `creditLoss`,
`otherIncome`, `leaseEsc`, `deposit`, `internet`, `cleaning`, `supplies`, `insurance`, `marketing`, `repairsPct`,
`mgmtPct`, `reservePerBed`, `growth`, `expGrowth`, `furnishPerBed`, `makeReady`, `setupCosts`, `reserveMonths`,
`price`, `downPct`, `rate`, `years`, `closingPct`, `taxAnnual`, `insAnnual`. A blank means "use the default";
anything else is refused with 422. `market` (rent and value estimate from listing research) is stored on the row
and returned, with no write route yet; backlog item 3 sets it.

## The math

`app/underwriting.py` is a line-for-line port of the page's `uwInputs`, `uwReady`, `uwCalc`, `uwProject`, `uwChecks`
and `uwScenario`, plus the text and CSV builders. `tools/underwriting_reference.mjs` is the page's own JavaScript,
copied verbatim; `node tools/underwriting_golden.mjs` runs it over eight cases and `tests/test_underwriting_math.py`
checks the Python against that output to 1e-9. If the Hub's formulas change, refresh the reference file and the
fixture, then the test says what moved.

Numbers are planning estimates, not financial advice. The settings defaults are the Hub's: planning rents $950
private and $600 per shared bed, 90% target occupancy, and the targets 1.30× rent coverage (1.25× debt coverage
when buying), break-even at most 75%, cash flow at least $300 per month, cash-on-cash at least 15%, cap rate at
least 6%.

## Not built here, and why

- The staff app page. The repository is not on this Mac. The page needs: the board (`GET /api/underwriting`),
  the full view opened from the address, the stage drop-down, the lease or buy toggle, the five input panels, the
  occupancy slider (call `GET` again with the row's inputs and an `occ` override), copy text and CSV buttons.
- The workflow builder (trigger, conditions, actions) and user-created tables. The stage change writes an audit
  row so a rule engine can read it later; `app/automations.py` runs only on deals today.
- Owner contact, phone, email and source fields. The CRM already holds the owner as a contact or company on the
  property's deal; duplicating them on the underwriting row would make two places to keep in step.
- Migrating the Hub's existing records. Paul decided they migrate once (2026-11-20); that is a one-off import
  through `PUT /api/underwriting/{id}` after the properties exist, not a feature.
