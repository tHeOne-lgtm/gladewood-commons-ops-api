# Portal v1: roles, Rule 11 screening, files on the Mac mini

Built 2026-11-20 on Paul's gate answers of the same day: residents may log in; six roles with per-individual scoping; a submission is held, logged, and alerted when the Rule 11 router is unreachable; files live on the Mac mini with a Google Drive copy. Plan Section 6 and 9 (Phase 2).

## Roles (API `users.role`)

| Role | CRM | Housing (staff routes) | Portal | Notes |
|---|---|---|---|---|
| `owner` | all | all | | Only an owner grants or removes the owner role; audit export (Phase 2 follow-up) |
| `management` | all | all, plus grant overrides and document removal | | Role assignment for every role but owner; settings; campaign sends |
| `ops_staff` | all | rooms, tenancies, documents, maintenance queue | | No role changes, no grant overrides |
| `audit` | read-only | read-only | | Every request writes an `audit.read` row; any write returns 403 |
| `resident` | none | none | own tenancy, documents shared with them, own requests, own profile | Password or email link; MFA not required |
| `case_manager` | none | none | tenancies with an active grant, within the grant's scopes | Grant binds to the account on first sign-in by email |

Old names are mapped on sign-in and by migration 0010: `admin` to `owner`, `staff` to `ops_staff`, `tenant` to `resident`. Staff MFA (`REQUIRE_STAFF_MFA`) applies to owner, management, ops_staff, and audit.

## How a login finds its records

A resident or case manager login is matched to a `contacts` row by `portal_user_id`, else by email (then stored). Staff create the resident contact and the tenancy first (Housing in the staff app); the resident signs up with the same email and sees it on the next request. Case manager access comes only from a grant: the resident gives it in the portal (email plus scopes plus optional expiry), or management records one from a signed authorization on file. Every case manager read of a grant-scoped record writes `portal.grant_read` to the audit log.

## Rule 11 screening (n8n router)

Every resident or case manager free-text submission (maintenance request title and description, comments) is posted to the router before it is kept.

Request: `POST $RULE11_ROUTER_URL`, header `X-Rule11-Secret: $RULE11_SECRET`, JSON `{"channel": "portal.maintenance" | "portal.comment", "category": "...", "text": "...", "ref": "maintenance_requests:<id>", "submitted_at": "<iso>"}`.
Response: JSON `{"flagged": true|false, "reason": "..."}` with status 200. The router keeps its own log and emails Paul for flagged items, as it does for the website today.

| Router answer | What the API keeps |
|---|---|
| `flagged: false` | The text; request status `open` |
| `flagged: true` | No text (title and description blanked); a marker: date, channel, category, reference; status `withheld`; audit `rule11.flagged` |
| No answer (timeout, error, non-2xx) | The text is held unread with status `pending_screening`; audit `rule11.router_unreachable`; one alert email to `PORTAL_ALERT_EMAIL` on the first failure; the 15 minute cron (`retry-screening`) re-screens until the router answers. Staff screens show the request as pending with no text. |

Without `RULE11_ROUTER_URL` the API applies the local word list from `app/fair_housing.py`. That is a development fallback; production sets the URL.

## Files: Mac mini file service with a Google Drive copy

The API never holds file bytes. `documents` rows hold metadata, sharing flags, and a `storage_key`. The n8n file service on the Mac mini (reachable through the Funnel path `/webhook/gc/files`) stores the bytes and copies them to Google Drive.

1. **Upload.** Staff create the document (`POST /api/housing/documents`). The response carries `upload.url` and `upload.token`. The browser sends the file as multipart to `upload.url` with the token. The service verifies the token, writes the file, copies it to Drive, then calls `POST /api/integrations/documents/{id}/stored` with `X-Api-Key` and `{storage_key, size_bytes, content_type, drive_file_id}`. Until then the document is `pending_upload` and invisible in the portal.
2. **Download.** `GET /api/portal/documents/{id}/link` (after the access check and an audit row) returns a 5 minute link `download.url?token=...`. The service verifies the token and streams the file.
3. **Token recipe** (`app/files.py`): `payload` is compact JSON with sorted keys; `body = urlsafe_base64(payload)` without padding; `token = body + "." + hex(HMAC-SHA256(FILES_SERVICE_SECRET, body))`. Upload payload `{"by","doc","exp","op":"upload"}`; download payload `{"by","doc","exp","key","op":"download"}`. Reject when the HMAC differs or `exp` is past.

The n8n workflow for the file service is a Paul-side step: an Upload webhook (verify token, write under `storage_key = tenancies/<tenancy_id>/<doc id>-<safe name>`, Google Drive node to copy, HTTP Request node to the stored callback) and a Download webhook (verify token, respond with the file).

## Environment variables

`RULE11_ROUTER_URL`, `RULE11_SECRET`, `PORTAL_ALERT_EMAIL`, `FILES_SERVICE_URL`, `FILES_SERVICE_SECRET` on the API service and the automations cron. `CORS_ORIGINS` gains the portal site's origin.

## Routes

Staff: `/api/housing/rooms`, `/api/housing/tenancies`, `/api/housing/documents`, `/api/housing/maintenance` (queue, update, comments, redact), `/api/housing/grants` (list; create and revoke need management).
Portal: `/api/portal/me` (GET, PUT), `/api/portal/documents`, `/api/portal/documents/{id}/link`, `/api/portal/maintenance` (list, submit, detail, comments), `/api/portal/grants` (list, give, revoke).

## Verification (Paul)

1. Set the five variables on Render and add the portal origin to `CORS_ORIGINS`.
2. In the staff app, create a property, a room, a resident contact with your own test email, and a tenancy.
3. Sign up in the portal with that email: the tenancy shows on the home page.
4. Submit a maintenance request with ordinary text: it appears open in the staff queue. Submit one the router flags: the portal says it was routed to Paul, the queue shows a withheld marker with no text, and the router's email arrives.
5. Stop the router and submit again: the request shows pending, an alert email arrives, and the cron clears it once the router is back.
