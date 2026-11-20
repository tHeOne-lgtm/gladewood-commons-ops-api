# Your task list, 2026-11-20

Everything below is a step only you can do (accounts, secrets, decisions). Each task says who does it, what to click, what done looks like, and what to watch for. Dashboard tasks work on a phone; the ones marked "computer" need a keyboard and file access. Costs in play today: Render Starter $7 per month and Supabase Pro $25 per month (both verified 2026-11-07); Netlify's free tier covers the two small sites and Resend's free tier covers the first sends (Assumption; confirm on the pricing pages when you sign up).

## 1. Confirm the Command Center sync works (Paul, phone or computer, 5 minutes)

1. Open the Command Center, Data view, and press Sync.
2. Done: the status line shows "N Bigin accounts" where N is the number of companies of kind agency, hospital, employer, or other in the staff app.
3. Then move any partner card off "Not contacted", press Sync again, open that company in the staff app, and look at its timeline for `integration.bigin_upsert`.
4. Error to watch: "No Bigin accounts came back" means the Make scenario could not reach the API; open Make, scenario "Command Center Sync", and read the last run's module 6 error, then tell Paul's assistant (me) the text.

## 2. Make Render deploy on its own (Paul, computer, 5 minutes)

1. Go to dashboard.render.com, open the service gladewood-commons-ops-api, then Settings.
2. Under Build and Deploy, confirm Auto-Deploy is On and the GitHub connection shows the repository. If GitHub shows disconnected or asks to reinstall, follow its Connect prompt and grant the repository.
3. Done: the next merge to master starts a deploy by itself within a minute. Until then deploys are triggered by hand.

## 3. Add the Render environment variables (Paul, computer, 15 minutes)

1. Render, service gladewood-commons-ops-api, Environment, Add Environment Variable, one row per key, then Save Changes (Render redeploys).
2. Keys and where the values come from:
   - `PUBLIC_BASE_URL` = `https://gladewood-commons-ops-api.onrender.com`
   - `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM` from console.twilio.com (Account Info panel; the WhatsApp sender in E.164, such as +1415...).
   - `FORMS_WEBHOOK_SECRET` = the output of `openssl rand -hex 32` in Terminal (keep a copy for task 5).
   - `CORS_ORIGINS` = the staff site URL and the portal site URL from task 4, comma separated, no trailing slashes.
   - `EMAIL_PROVIDER`, `EMAIL_FROM`, `EMAIL_REPLY_TO`, `EMAIL_POSTAL_ADDRESS`, `EMAIL_UNSUBSCRIBE_SECRET`, `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET` after task 6.
   - `RULE11_ROUTER_URL`, `RULE11_SECRET`, `PORTAL_ALERT_EMAIL`, `FILES_SERVICE_URL`, `FILES_SERVICE_SECRET` after task 8 (`RULE11_SECRET` and `FILES_SERVICE_SECRET` are two more `openssl rand -hex 32` outputs).
3. Repeat the `EMAIL_*`, `RESEND_API_KEY`, `RULE11_*`, `PORTAL_ALERT_EMAIL`, and `FILES_*` rows on the cron job gladewood-automations (Render lists it next to the web service after a Blueprint sync).
4. Done: the service shows "Live" after the redeploy and `GET /api/health` returns ok.
5. Error to watch: a 503 from any route that names a missing variable means that row is empty or misspelled.

## 4. Create the two Netlify sites (Paul, computer, 20 minutes)

Full click path, the Supabase redirect step, and the error table: `docs/NETLIFY_SITES.md`. When both sites exist, paste their URLs in the chat and I set `CORS_ORIGINS` on Render for you.

1. Go to app.netlify.com, Add new site (or Add new project), Import an existing project, pick GitHub, choose GLADEWOOD-staff-app.
2. Staff site: leave Base directory empty, Build command `npm run build`, Publish directory `dist`. Add environment variables `VITE_API_URL` = the Render URL, `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` from supabase.com (Project Settings, API; use the publishable key, never the secret key). Deploy.
3. Portal site: repeat with the same repository, Base directory `portal`, same three variables. Deploy.
4. Copy both site URLs into `CORS_ORIGINS` (task 3).
5. Done: the staff site shows the sign-in page and, after sign-in, the Dashboard; the portal site shows "Gladewood Commons" sign-in.
6. Error to watch: "Cannot reach the API" after sign-in means `CORS_ORIGINS` does not contain that exact site URL.

## 5. Point the website forms at the API (Paul, computer, 10 minutes)

1. Netlify, the gladewoodcommons.com site, Forms, Form notifications (older layout: Site configuration, Notifications), Add notification, Outgoing webhook.
2. Event: New form submission. URL: `https://gladewood-commons-ops-api.onrender.com/api/forms/netlify`. Form: Tour Request. JWS secret token: the `FORMS_WEBHOOK_SECRET` value. Save. Repeat for the Referral Inquiry form.
3. Done: a test submission appears in the staff app Contacts within a minute, tagged src-web, with a deal and a task.
4. Error to watch: Netlify shows a 403 on the delivery when the two secrets differ; 503 when the Render variable is missing.

## 6. Choose and connect the email provider (Paul, computer, 30 minutes)

Shortlist: Resend (campaign metrics through a webhook, free tier for small volume), Postmark (same capability, paid from the start), Google Workspace SMTP (already paid for, no delivery or open tracking). Recommendation: Resend, because campaign reports need delivered, opened, and bounced events and the free tier fits current volume (Assumption on tiers; confirm on resend.com/pricing).

1. resend.com, sign up, Domains, Add domain `gladewoodcommons.com`, copy the DNS records it shows into your DNS host, wait for Verified.
2. API Keys, Create, permission Sending access, copy once into Render as `RESEND_API_KEY`.
3. Webhooks, Add, URL `https://gladewood-commons-ops-api.onrender.com/api/webhooks/resend`, events email.delivered, email.opened, email.clicked, email.bounced, email.complained; copy the signing secret into Render as `RESEND_WEBHOOK_SECRET`.
4. Set `EMAIL_PROVIDER=resend`, `EMAIL_FROM` to a mailbox on the verified domain, `EMAIL_POSTAL_ADDRESS` to the business mailing address, `EMAIL_UNSUBSCRIBE_SECRET` to an `openssl rand -hex 32` output.
5. Done: in the staff app, open your own contact, Email, pick Welcome, Preview, Send; the timeline shows the email and the log row turns to delivered after the webhook.
6. Error to watch: a 502 on Send with "domain not verified" means step 1 is not finished.

## 7. Move the partner directory out of Bigin (Paul, computer, 20 minutes)

1. Bigin, Settings (gear), Data Administration, Export (menu names may differ slightly). Export Accounts as CSV, then Contacts as CSV.
2. Staff app, Imports, choose the two files, Preview (dry run). Read the counts: expect about 130 companies and 120 contacts created or matched, 1 skipped (the Google forwarding address).
3. Import. Done: Contacts filtered by tag src-bigin shows the partner staff; Companies shows the organizations.
4. Then make Bigin read-only for your users and keep the export files for 30 days before cancelling.
5. Error to watch: if Preview reports many "matched" rows you did not expect, stop and send me the counts before pressing Import; Undo exists on the Imports page if needed.

## 8. Build the two n8n pieces on the Mac mini (Paul, computer, 60 minutes; the most technical task)

1. Rule 11 router: in n8n create a Webhook node (POST) under the `gc/` path, a node that applies the Rule 11 keyword list to the `text` field of the incoming JSON, and a Respond to Webhook node returning `{"flagged": true|false, "reason": "..."}`. Reject requests whose `X-Rule11-Secret` header does not equal `RULE11_SECRET`. Set the webhook's public URL as `RULE11_ROUTER_URL` on Render.
2. File service: an upload Webhook that verifies the token (recipe in `docs/PORTAL_V1.md`), writes the file under `tenancies/<id>/`, copies it with a Google Drive node, then calls `POST .../api/integrations/documents/<id>/stored` with header `X-Api-Key` = `INTEGRATION_API_KEY`; and a download Webhook that verifies the token and responds with the file. Set the base URL as `FILES_SERVICE_URL`.
3. Command Center sync: import the workflow from your migration document, replace its two Bigin nodes with HTTP Request nodes to `/api/integrations/bigin-accounts` and `/api/integrations/bigin-accounts/upsert` with the `X-Api-Key` header. Keep the Make scenario on for 7 days after n8n is live, then deactivate it.
4. Done: task 11 passes end to end.
5. Error to watch: the Funnel exposes only `/webhook/gc`; webhooks outside that path are unreachable from Render.

## 9. Point Twilio WhatsApp at the API (Paul, phone or computer, 5 minutes)

1. console.twilio.com, Messaging, Senders, WhatsApp senders, open the Gladewood sender.
2. Webhook URL for incoming messages: `https://gladewood-commons-ops-api.onrender.com/api/webhooks/twilio/whatsapp`; Status callback URL: `.../api/webhooks/twilio/status`. Save.
3. Done: a WhatsApp message to the business number appears in the staff app WhatsApp view with a new inquiry deal.
4. Error to watch: Twilio shows 403 on the request when `TWILIO_AUTH_TOKEN` on Render is wrong.

## 10. Turn on custom SMTP for sign-in emails (Paul, computer, 10 minutes)

1. supabase.com, the project, Authentication, SMTP Settings, Enable custom SMTP, enter the Resend SMTP details (host, port, user, password from the Resend dashboard) or Google Workspace's.
2. Done: a resident requesting an email link receives it within a minute; the hourly limit on Supabase's built-in sender no longer applies.

## 11. Verify the portal end to end (Paul plus one staff member, computer, 20 minutes)

1. Staff app, Housing: New room on a property; New tenancy with a contact that uses a test email you control.
2. Portal site: sign up with that email; Done: the home page shows that room.
3. Portal, Maintenance: submit one ordinary request; Done: it shows as Open in the staff app Maintenance queue.
4. Submit one with a word the router flags; Done: the portal says it was routed to Paul and the queue shows "Routed to Paul (text withheld)" with no text.
5. Stop the router in n8n and submit a third; Done: the portal says "being reviewed", the alert email arrives at `PORTAL_ALERT_EMAIL`, and the request opens by itself once the router is back.
6. Staff app, tenancy page: upload a small file; Done: it shows "stored" after the file service callback and opens from the portal Documents page.

## 12. Decisions still open (Paul, any time)

- Phase 3: Stripe for card and ACH (yes or no), and whether some residents pay through agency checks that need manual posting.
- Phase 4: Plaid bank feeds or CSV import first.
- Attorney review before Phase 3: deposit handling, late fees, the case manager authorization form, the screening criteria, and the Rule 11 keyword list.
- Assign roles on the staff app's Users page (owner and management see it): pick the role next to each email and confirm. Nobody can change their own role, and only an owner can grant or remove owner.

## End goal

- Command Center, website forms, WhatsApp, and email all land in the one CRM.
- The partner directory is in the CRM and Bigin is read-only.
- Staff sign in with their own role; residents and case managers use the portal, with every free-text submission screened by n8n and every file on the Mac mini with a Drive copy.
- Render deploys on its own, and the three remaining product decisions are made.
