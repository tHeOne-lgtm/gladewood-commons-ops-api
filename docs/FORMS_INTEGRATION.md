# Marketing site forms into the CRM

**Goal.** A Tour Request or Referral Inquiry on gladewoodcommons.com creates a contact, a deal, a note, and a follow-up task in the CRM within seconds, with nothing to copy out of an inbox.

**Two ways to wire it.** Pick one per form. Option A keeps Netlify Forms (spam filtering, submissions list, email notifications) and adds a webhook. Option B posts straight to the API from the page and skips Netlify Forms.

## Option A: Netlify Forms outgoing webhook (recommended)

Source fact (Netlify docs, read 2026-11-20): an outgoing webhook notification sends a JSON body and an `X-Webhook-Signature` header. The header is a JWS signed with HS256 using the secret you set, with claims `iss` = `netlify` and `sha256` = hex SHA-256 of the request body. The API verifies both before it stores anything.

1. **Create the secret.** On the Mac, run `openssl rand -hex 32` in Terminal and copy the 64-character result.
2. **Add it to Render.** Render dashboard, the `gladewood-commons-ops-api` service, Environment, Add Environment Variable: key `FORMS_WEBHOOK_SECRET`, value the string from step 1. Save, and let the service redeploy.
3. **Add the notification in Netlify.** Netlify dashboard, the gladewoodcommons.com site, then Forms in the left menu, then Form notifications (older layouts: Site configuration, Notifications, Form submission notifications). Choose Add notification, Outgoing webhook.
   - Event to listen for: New form submission.
   - URL to notify: `https://gladewood-commons-ops-api.onrender.com/api/forms/netlify`
   - Form: pick the Tour Request form. Repeat the whole step for the Referral Inquiry form.
   - JWS secret token: paste the same string from step 1.
4. **Check the form names.** The API routes by the form's `name` attribute. Names containing `referral` or `partner` go to the referral partner pipeline; `tour`, `inquiry`, `contact`, or anything else goes to the resident inquiry pipeline. A submission with an `organization` field also routes to referral.
5. **Test.** Submit each form once with your own details and the message "test". Within a few seconds the contact appears at `/contacts` in the staff app tagged `src-web`, with an open deal and a task due in 24 hours. Delete the test records from the staff app afterward.

If the webhook fails, Netlify shows the attempt under the form's submission detail. A 403 means the secret in Netlify and Render differ; a 503 means `FORMS_WEBHOOK_SECRET` is not set on Render.

## Option B: post from the page

Send the form with `fetch` to `https://gladewood-commons-ops-api.onrender.com/api/forms/inquiry` or `/api/forms/referral`, JSON or form-encoded. Add `https://gladewoodcommons.com` to `CORS_ORIGINS` on Render first. Responses: `201` with `{ok, contact_id, deal_id, created_contact}`, `422` for a missing name or organization, `429` after ten submissions from one address in an hour, `204` when the honeypot field is filled.

```html
<form id="tour" method="post">
  <input name="name" required placeholder="Full name">
  <input name="email" type="email" placeholder="Email">
  <input name="phone" type="tel" placeholder="Phone">
  <select name="room_preference"><option value="">Room preference</option><option>Private</option><option>Shared</option></select>
  <input name="move_in_target" placeholder="Target move-in month">
  <textarea name="message" placeholder="Anything we should know to schedule your tour?"></textarea>
  <label><input type="checkbox" name="contact_ok" value="yes"> You may email me about availability</label>
  <input name="website" tabindex="-1" autocomplete="off" style="position:absolute;left:-9999px" aria-hidden="true">
  <button>Request a tour</button>
</form>
<script>
document.getElementById('tour').addEventListener('submit', async (e) => {
  e.preventDefault();
  const r = await fetch('https://gladewood-commons-ops-api.onrender.com/api/forms/inquiry', {
    method: 'POST', body: new FormData(e.target)
  });
  e.target.outerHTML = r.ok ? '<p>Thanks. Paul will reach out within one business day.</p>'
                             : '<p>Something went wrong. Text or WhatsApp us instead.</p>';
});
</script>
```

## Fields the API accepts

| Inquiry form | Referral form | Notes |
|---|---|---|
| `name` (or `first_name` + `last_name`, `full_name`) | `name` | Required |
| `email` | `email` | Used to match an existing contact first |
| `phone` (or `tel`, `mobile`) | `phone` | Matched by the last ten digits; stored in E.164 |
| `message` (or `comments`, `notes`, `details`) | `message` | Stored as a note on the contact |
| `room_preference` (or `room`, `room_type`) | | Stored on the deal |
| `move_in_target` (or `move_in`, `timeline`) | | Stored on the deal as typed, no parsing |
| `contact_ok` (or `consent`, `opt_in`) | | `yes`, `true`, `on`, or `1` records email consent |
| | `organization` (or `company`, `agency`, `employer`) | Required; creates or matches a company |
| | `organization_type` | One of `agency`, `hospital`, `employer`, `property_owner`, `brokerage`, `vendor`, `other`; default `agency` |
| | `role` (or `title`, `position`) | Stored on the contact |
| `page` (or `referrer`) | `page` | Which page sent it |
| `website` (or `bot-field`) | `website` | Honeypot. Keep it hidden and empty |

**What the forms must not ask.** No health conditions, disability, medication, treatment, benefit type, or criminal history. The Fair Housing notice stays on the page. The API stores only the fields above; anything else in a submission is ignored.

## What happens on the API side

Analysis: a web inquiry becomes a `prospect` contact named by initials (for example "S. L."), a resident inquiry deal at Inquiry owned by the first admin, a note "Web form: ...", and a task "Call back new web inquiry" due in 24 hours. A referral becomes a company (if new), a `case_manager` contact linked to it, a partner deal at Contacted, and a task "Send partner fact sheet" due in 24 hours. A second submission from the same email or phone updates the contact and adds a note but opens no second deal while one is open.
