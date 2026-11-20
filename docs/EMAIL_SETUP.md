# Email setup: provider, domain, webhook, first send

**Decision still open (plan section 8, item 3).** The code ships two drivers. Recommendation: Resend, because campaign reports need delivered, opened, clicked, and bounced events, and Resend posts those to a webhook. Google Workspace SMTP works for 1:1 mail but reports nothing back. Not an attorney or CPA; the compliance notes below are operational practice, confirm with counsel.

**Costs (Assumption; check the pricing page when you sign up):** Resend has a free tier sized for a small sender and a paid tier above it. Google Workspace SMTP is included with the mailbox you already pay for.

## Option A: Resend (recommended)

1. **Create the account and verify the domain.** Sign up at resend.com, add `gladewoodcommons.com` under Domains, and add the DNS records it shows (DKIM, SPF, and the return-path CNAME) at your DNS host. Wait for the domain to show Verified. Until then every send is refused.
2. **API key.** Resend dashboard, API Keys, Create. Permission: Sending access only. Copy it once.
3. **Webhook.** Resend dashboard, Webhooks, Add. Endpoint URL: `https://gladewood-commons-ops-api.onrender.com/api/webhooks/resend`. Events: `email.delivered`, `email.opened`, `email.clicked`, `email.bounced`, `email.complained` (add `email.delivery_delayed` if offered; the API ignores it). Copy the signing secret, which starts with `whsec_`.
4. **Render environment variables** on the `gladewood-commons-ops-api` service:

   | Key | Value |
   |---|---|
   | `EMAIL_PROVIDER` | `resend` |
   | `EMAIL_FROM` | `Paul Selman <paul@gladewoodcommons.com>` (a mailbox on the verified domain) |
   | `EMAIL_REPLY_TO` | the inbox you read, if different |
   | `EMAIL_POSTAL_ADDRESS` | the business mailing address, one line |
   | `EMAIL_UNSUBSCRIBE_SECRET` | output of `openssl rand -hex 32` |
   | `RESEND_API_KEY` | from step 2 |
   | `RESEND_WEBHOOK_SECRET` | from step 3 |

   Add the same `EMAIL_*` and `RESEND_API_KEY` values to the two cron jobs (`gladewood-automations`, `gladewood-digest`) when Render asks after the next Blueprint sync.
5. **Test.** In the staff app open your own contact record, pick the Welcome template, Preview, Send. Within a minute the timeline shows the email, and after the webhook fires the log row reads `delivered`. Click the unsubscribe link in the test email and confirm the contact's email consent shows withdrawn; then record a new consent so your own record can receive mail again.

## Option B: Google Workspace SMTP

Google Admin, Apps, Google Workspace, Gmail, Routing: turn on the SMTP relay service for your domain, or use an app password on the sending mailbox with `smtp.gmail.com`, port 587. Set `EMAIL_PROVIDER=smtp`, `SMTP_HOST`, `SMTP_PORT=587`, `SMTP_USER`, `SMTP_PASSWORD`, plus the `EMAIL_*` values above. No webhook; campaign reports show only sent, skipped, and failed. Gmail's daily sending limits apply to campaigns.

## What every email carries

- Footer: "Gladewood Commons, LLC, <postal address>", "Equal Housing Opportunity.", and an unsubscribe link (Source fact: CAN-SPAM requires a physical postal address and a working opt-out; the Fair Housing advertising rule is in plan section 7).
- Headers `List-Unsubscribe` and `List-Unsubscribe-Post`, so Gmail and Apple Mail show their own unsubscribe button (Source fact: RFC 8058).
- Templates are refused when they contain a protected-trait term (the list in `app/fair_housing.py`) or an unknown merge field. Write about the housing, never about the resident.

## Consent

| Send type | Needs |
|---|---|
| Transactional (tour confirmation, application received, fact sheet after a call) | Contact has an email, is active, has not unsubscribed, has not bounced |
| Marketing 1:1 (`marketing=true`) and every campaign | All of the above plus an active `email` consent recorded on the contact (form checkbox, verbal with a note, or import with a source) |

A bounce marks the contact and blocks further sends until staff clear `email_bounced_at` on the record after fixing the address. A spam complaint withdraws consent as well.

## Merge fields

`{{first_name}}`, `{{display_name}}`, `{{email}}`, `{{company_name}}`, `{{deal_title}}`, `{{stage_name}}`, `{{next_action_at}}`, `{{room_preference}}`, `{{move_in_target}}`, `{{sender_name}}`, `{{unsubscribe_url}}`. Deal fields are empty when no deal is attached.
