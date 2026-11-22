# Outbox: the outbound queue with approval and four gates

Built 2026-11-22 for Atlas gap 2 (outbound queue with four-gate dispatch). Not an attorney or CPA: the
texting-hours and consent rules below are operational practice; confirm with counsel.

## The rule it keeps

The Staged Path says Paul approves every send and there is no send tool for agents. The queue keeps
both: a row never leaves until an admin (owner or management role) approves it, and the integration key
can only create drafts. Shadow mode is on by default, so a fresh deploy runs the queue dry until you
turn it off on purpose.

## Lifecycle

`draft` (created by staff or an agent, linted) → `approved` (admin, after lint and consent checks pass) →
one of `sent`, `shadowed`, `held` (with `hold_reason`), `failed` (with `error`), or `cancelled`. A held or
draft row can be edited (it goes back to draft) and approved again. Approved rows cannot be edited; cancel
them instead.

## The gates, in order, every 15 minutes

The cron job `gladewood-automations` runs `python -m app.cli dispatch-outbox` after the automations,
campaigns and screening retries. An admin can also run `POST /api/outbox/dispatch` at any time.

| Gate | What it checks | When it fails |
|---|---|---|
| 1. Lint | The A4 Draft Check scan ported to `app/outbox_lint.py`: banned resident descriptors, care words, health detail, door or lock codes, injection text, personal identifiers, dashes, and every dollar figure against `OUTBOX_ALLOWED_PRICES`; plus the CRM's protected-trait list. Runs at create, at approval and again at dispatch on the current text. | Row is `held`, reason `lint`, the failures in `gate_log`. |
| 2. Kill switch | `OUTBOX_PAUSED=true` in the environment, or the admin flag `outbox_paused` (`PUT /api/outbox/flags {"paused": true}`). | Nothing moves. Rows stay `approved`; one audit row `outbox.paused` per run that had due rows. |
| 3. Schedule | `send_after` has passed (null means the next run). SMS and WhatsApp also wait for `OUTBOX_TEXT_HOURS` (default 8 to 21) in `OUTBOX_TIMEZONE` (default America/New_York). | The row waits; `deferred` in the report. No status change. |
| 4. Shadow | `OUTBOX_SHADOW=true` (the default) or the admin flag `outbox_shadow`. | Row becomes `shadowed` with the channel and the last four characters of the address in `gate_log`; nothing is sent. |

The environment values are a floor: a flag cannot lift `OUTBOX_PAUSED=true` or `OUTBOX_SHADOW=true`.

Before the send, the consent and address checks run (at approval too, for early feedback): the contact
is active and has the address; email uses the same gate as 1:1 email (`unsubscribed`, `bounced`,
`no_consent` for marketing); SMS and WhatsApp hold on `stopped` (a STOP with no newer consent),
`no_consent` for marketing, and WhatsApp holds on `window_closed` unless `allow_outside_window` is set.

## Sends, receipts and threading

- **Email** goes through `app.emailing.send_to_contact`: footer with postal address, Equal Housing
  Opportunity line and unsubscribe link, an `emails` row, the same provider as everything else
  (`EMAIL_PROVIDER`). The queue row links `email_id`; `delivery_status` on the row is the `emails` status,
  which the Resend webhook updates (delivered, bounced, complained).
- **SMS** goes from `TWILIO_SMS_FROM`, **WhatsApp** from `TWILIO_WHATSAPP_FROM`, both with the status
  callback. A `messages` row (direction out) is written, so the message shows in the conversation thread
  next to inbound replies, and `delivery_status` is Twilio's status.
- **Reply threading.** SMS and WhatsApp thread by phone number (`thread_key`). An email reply names
  `in_reply_to_email_id`; when that email went out over SMTP its stored id is a real Message-ID and the
  reply carries `In-Reply-To` and `References`. Resend's ids are not Message-IDs, so a Resend reply gets
  no header (Assumption: Resend accepts custom headers; not verified from the build environment).

## Routes

| Route | Role | Does |
|---|---|---|
| `GET /api/outbox` | staff | list; filters `status`, `open_only`, `contact_id`, `thread_key`, `limit` |
| `POST /api/outbox` | staff | create a draft (linted) |
| `GET /api/outbox/{id}` | staff | one row with `delivery_status` |
| `PUT /api/outbox/{id}` | staff | edit a draft or held row; it returns to draft |
| `POST /api/outbox/{id}/approve` | admin | lint and consent checks, then `approved` |
| `POST /api/outbox/{id}/cancel` | staff | cancel a draft, approved or held row |
| `GET /api/outbox/flags` | staff | effective pause and shadow state, texting hours, whether prices are set |
| `PUT /api/outbox/flags` | admin | flip `paused` and `shadow` |
| `POST /api/outbox/dispatch` | admin | run the gates now |
| `POST /api/integrations/outbox` | X-Api-Key | an agent's draft, with `agent` name; never approves or sends |

Audit actions: `outbox.create`, `outbox.update`, `outbox.approve`, `outbox.cancel`, `outbox.hold`,
`outbox.shadow`, `outbox.sent`, `outbox.failed`, `outbox.paused`, `flag.set`, plus `message.out` or
`email.send` from the channel. Audit rows carry ids, channel, status and reason, never the text.

## Environment (Render)

On the web service and the `gladewood-automations` cron:

| Key | Value |
|---|---|
| `OUTBOX_SHADOW` | `true` until you have watched a week of shadowed rows; then `false` |
| `OUTBOX_PAUSED` | `false`; set `true` to stop the queue across restarts |
| `OUTBOX_ALLOWED_PRICES` | the figures from the Fact Sheet, space separated, for example `550 650 850 1100 350 1M 2M`. Empty means every dollar figure fails lint. |
| `OUTBOX_TEXT_HOURS` | `8-21` (optional) |
| `OUTBOX_TIMEZONE` | `America/New_York` (optional) |
| `TWILIO_SMS_FROM` | the SMS-capable number in E.164; without it SMS rows cannot be approved |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, `EMAIL_*`, `PUBLIC_BASE_URL` | already on the web service; the cron needs the same values to send |

## Not built

- ~~A staff app page.~~ Built 2026-11-22 in GLADEWOOD-staff-app (branch `claude/outbox-and-underwriting-2026-11-22`,
  page `/outbox`).
- The n8n kill switch does not reach this queue (owner decision 2026-11-18: it stops agents only). A later
  step could have it call `PUT /api/outbox/flags` through the integration key.
- Inbound email replies are not matched to outbox rows (the CRM has no inbound email path; n8n triage owns
  the inbox).

## Verified on 2026-11-22

16 outbox tests and the full suite on SQLite; migration 0013 upgrade, downgrade, upgrade on Postgres 16;
the suite on the migrated schema and on plain Postgres; pyflakes and bandit clean. Not run: a real Twilio
or Resend send (fakes record the calls), the Render cron with the new command, the staff app.
