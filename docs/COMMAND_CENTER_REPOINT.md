# Command Center sync: repointed from Bigin to this API

**Decision context (Source fact, plan decision log 2026-11-07):** the custom CRM replaces Bigin; Make and Bigin go dormant; the Command Center Sync scenario (Make 6382382) moves to n8n on the Mac mini, and its two Bigin nodes re-point to this API through a machine credential.

**What changed on 2026-11-20.**

| Piece | Before | After |
|---|---|---|
| Push of engaged partners (Make module 3, "Key OK + partners to push") | Bigin `POST /v2/Accounts/upsert` with the page's body `{"data":[{Account_Name, Description, Phone?}], "duplicate_check_fields":["Account_Name"]}` | `POST https://gladewood-commons-ops-api.onrender.com/api/integrations/bigin-accounts/upsert`, same body, header `X-Api-Key` |
| Pull of the partner list (Make module 6, "Key OK") | Bigin `GET /v2/Accounts?fields=Account_Name,Phone,Website,Description,Modified_Time&per_page=200` | `GET .../api/integrations/bigin-accounts`, same response shape `{"data":[{id, Account_Name, Phone, Website, Description, Modified_Time}]}` |
| Module 8 (JSON for the webhook response) | `{{6.body}}` from the Bigin module | `{{6.data}}` from the HTTP module (response parsed) |
| Everything else in the scenario (cloud state, access code rotation, Google Calendar, Google Sheets, Galen feed, fix tracker) | unchanged | unchanged |

The Command Center page itself is unchanged: it still posts to the Make webhook, still reads `bigin.data` from the response, and still matches partners by name.

**How the API treats the data (Analysis).**

- Upsert matches a company by name, case-insensitive. A new name creates a company with the kind guessed from the name (agency, hospital, employer, other). Phone and website fill blanks only.
- The page's description ("type | CC: stage · last touch · next") is stored in `extra.cc_description` and returned as `Description`. Staff notes are never touched by the sync.
- The pull returns companies of kind agency, hospital, employer, and other. Property owners, brokerages, and vendors are not referral partners and stay out of the Command Center list.
- Every push writes one audit row (`integration.bigin_upsert`) with counts.

**Credential.** `INTEGRATION_API_KEY` on Render; the same value in the Make HTTP modules' `X-Api-Key` header, and later in the n8n HTTP Request nodes (Header Auth credential). The key opens only `/api/integrations/*`. Rotate by changing both places; the old key stops working at the next deploy.

**n8n (when the migration document's workflow is imported).** Replace the two Bigin nodes in the Command Center Sync workflow with HTTP Request nodes using the two URLs above and a Header Auth credential named `X-Api-Key`. Per plan Section 9, keep the Make scenario on for 7 days after the n8n version is live, then deactivate it.

**Verification steps (Paul).** Open the Command Center, Data view, and run Sync. The status line should read "N Bigin accounts" where N is the count of partner companies in the staff app (Companies filtered to agency, hospital, employer, other). Move one partner to any stage other than Not contacted, Sync again, then open that company in the staff app: its timeline shows `integration.bigin_upsert` and the record carries the "CC:" description in its extra fields.
