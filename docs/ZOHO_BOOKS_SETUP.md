# Zoho Books setup for Gladewood Commons

Written 2026-11-09 for Paul. Zoho Books (Free plan) is the book of record; this API keeps the rent subledger and will push customers, invoices, and payments to Books in Phase 4 (plan decision log, 2026-11-07). Everything below is done once, in the Zoho Books web app, in this order. Nothing here needs a developer.

Sources: Zoho Books help pages read 2026-11-09 (Getting Started, Organization Profile, Opening Balances, Chart of Accounts, Recurring Invoices, Stripe); the Free-plan limits verified 2026-11-07 (plan Section 10, item 4); `~/gladewood/docs/Gladewood-Zoho-Connection-Guide.md` for the API steps. Not checked: your live organization (I cannot see it), and whether the Free plan includes the Data Backup export (Step 13).

## Before you start

- **Data classification.** Residents' names, emails, and payment records will live in Zoho Books. Zoho Books is the system of record for money, so this is the intended destination; confirm once that you are comfortable with that (org rule: confirm the destination before resident data goes to a third-party tool). Never put health, disability, accommodation, or screening information anywhere in Books: not in customer notes, not in invoice notes, not in attachments (Fair Housing Rules 2, 5, 11).
- **Free-plan limits that shape the setup** (Source fact, 2026-11-07): 1 user plus 1 accountant; 1,000 invoices and 1,000 expenses a year; no bank feeds (statements are imported); no custom fields; no period locking; no workflow rules. Free ends when revenue for the financial year passes $50K.
- Have ready: legal entity name and EIN, mailing address, bank account details, logo file, your CPA's email.

## Step 1. Organization profile

Settings (gear icon), Organization, **Organization Profile**.

1. Organization name: Gladewood Commons (or the legal entity name your CPA wants on invoices).
2. Industry: real estate or property rental. Location: Chattanooga, TN. Currency USD. Time zone America/New_York.
3. Fiscal year start: January, unless your CPA says otherwise.
4. Primary contact email: `info@gladewoodcommons.com`, so customer emails come from the shared address, not a personal one.
5. Upload the logo.

## Step 2. Accounting basis and preferences

Settings, Preferences, **General**.

1. Accounting basis: ask your CPA (accrual is Zoho's default and is what the rent subledger here assumes; cash basis is common for small rentals). Record the answer in the plan decision log.
2. Settings, Preferences, **Customers and Vendors**: keep customer "Notes" fields unused by policy.
3. Settings, Preferences, **Invoices**: default payment terms **Due on receipt** or **Net 5** (rent due on the 1st, late after the 5th; confirm the late-fee rule with counsel before any late fee is charged). Turn **off** automatic invoice reminders for now: reminders to residents are resident-facing messages and go through the review gate and the n8n draft-only stage first.

## Step 3. Users

Settings, **Users and Roles**.

1. You are the one Free-plan user.
2. Invite your CPA with the **Accountant** role (the Free plan includes one accountant seat).
3. No other users on Free. Staff who need numbers get them from this API's dashboards, not from Books.

## Step 4. Chart of accounts

Accountant, **Chart of Accounts**. Zoho creates a standard list. Add only these (names are suggestions; your CPA may rename):

| Account | Type | Used for |
|---|---|---|
| Rent Income | Income | Monthly room rent (all-inclusive, utilities included) |
| Late Fee Income | Income | Only if counsel approves a late fee |
| Security Deposits Held | Other Current Liability | Deposits are a liability, not income, until applied or returned |
| Master Lease Rent | Expense | Rent paid to the property owner |
| Utilities | Expense | Power, water, gas, internet |
| Furnishings and Equipment | Expense or Fixed Asset (CPA decides by amount) | Beds, furniture, appliances |
| Repairs and Maintenance | Expense | |
| Cleaning and Supplies | Expense | |
| Insurance | Expense | |
| Software and Subscriptions | Expense | Render, Supabase, domains |
| Stripe Fees | Expense | Zoho fills this from the Stripe integration |

Zoho adds a **Stripe Clearing** account by itself when Stripe is connected (Step 9).

## Step 5. Items (what gets invoiced)

Sales, **Items**, New Item. One item per room type, sales account **Rent Income**, tax **not applicable**:

| Item | Rate | Note |
|---|---|---|
| Private room, monthly rent | the confirmed private-room price for that house | Prices confirmed 2026-10-07 (Fact Sheet): private $850 to $1,100 |
| Shared room, monthly rent | the confirmed shared-room price | shared $550 to $650 |
| Security deposit | amount per lease | Sales account **Security Deposits Held**, not income |

Put the room number on the invoice line, never in the item name. Prices on invoices must match the lease and the Fact Sheet; no other price appears anywhere public (Fair Housing Rule 2).

## Step 6. Taxes

Settings, **Taxes**. Long-term residential rent is not subject to Tennessee sales tax; the Chattanooga occupancy tax applies to short stays, not month-to-month residents (Analysis; confirm with your CPA). Leave sales tax off the rent items. Do not enable Zoho's automatic sales tax.

## Step 7. Customers (residents) and how they map to the CRM

Sales, **Customers**. Create a customer only when a lease is signed, with: display name, first and last name, email, phone. Nothing else.

- Customer type: Individual. Portal language English.
- The CRM contact id is **not** stored in Books (no custom fields on Free). The mapping lives in this API's tables, and each invoice pushed by the sync carries the subledger invoice number in Zoho's **Reference#** field (plan Section 10, item 4).
- Until the Phase 4 sync exists, enter customers by hand and keep the same name as the CRM contact so the sync can match them later.

## Step 8. Recurring invoices

Sales, **Recurring Invoices**, New.

1. One profile per resident: item from Step 5, repeat **every 1 month**, start on the first rent date, no end date, invoice date **1st of the month**, payment terms from Step 2.
2. **Create as Draft**, not "Create and send", until you decide to let Books email invoices. Sending is a resident-facing message; the draft-only rule applies.
3. Security deposits are one-time invoices, not recurring.

## Step 9. Online payments (Stripe)

Settings, Integrations, **Online Payments**, Stripe: connect your Stripe account (the same one as the hand-off's Stripe ACH application, item 6).

1. Enable **Cards** and **ACH**; Zoho says ACH customers verify a bank account by micro-deposits or Stripe Financial Connections (Source fact, Zoho Stripe help).
2. Auto-charge: leave **off**. A resident can save a bank account in the portal and opt in later; you can turn auto-charge on per recurring invoice when the lease and counsel allow it.
3. Zoho creates the Stripe Clearing account and records Stripe fees on its own; your only reconciliation step is matching each Stripe payout to the bank statement line.

## Step 10. Bank account and statements

Banking, **Add Bank or Credit Card**, choose **Add manually** (the Free plan has no feeds).

1. Enter the operating account. Opening balance as of the go-live date.
2. Each month: download the statement as CSV or OFX from the bank, Banking, **Import Statement**, then **Reconcile** against the statement's closing balance.
3. Add the Stripe payout matching here, not in Stripe.

## Step 11. Customer portal

Settings, **Customer Portal**: enable. Portal name `gladewoodcommons`. Allow residents to view invoices and pay online; **do not** allow them to edit their own contact details yet (the CRM is the source for those). Portal invitation emails use Zoho's template; before customizing any text, run it through the review gate (it is resident-facing copy).

## Step 12. Opening balances

Settings, Setup and Configurations, **Opening Balances** (Source fact). Opening balance date = the day Books goes live. Gladewood is pre-launch, so this is mostly zeros: the bank balance, any deposits already held (liability), and any furnishings already bought if your CPA wants them on the books. Your CPA signs off on this screen before the first invoice.

## Step 13. Templates, data export, and plan triggers

1. Settings, **Templates**: pick a clean invoice template, add the logo. Footer text stays Zoho's default until the review gate has passed any custom wording.
2. Settings, **Data Backup** (if the Free plan shows it; not checked): export once a month to Drive alongside the n8n backup. If it is not on Free, export Invoices, Customers, and Payments as CSV from each list's export menu instead.
3. Move to **Standard** ($15 a month billed annually, verified 2026-11-07) when any of these happens: financial-year revenue nears $50K, you want bank feeds instead of statement import, you need period locking after the first year-end close, or the sync needs custom fields.

## Step 14. API access for this system (do this last)

This is the only technical step, and it is the one already waiting on you.

1. Go to `https://api-console.zoho.com`, **Self Client**, **Generate Code**, scope `ZohoBooks.settings.READ`, duration 10 minutes.
2. Run `bash tools/zoho_books_check.sh` in the repo. It asks for the Client ID, Client Secret, and that code with hidden input, prints two HTTP status lines, the organization line (name, `organization_id`, plan fields), and the refresh token once. Save the refresh token in your password manager; paste nothing from it into chat, docs, or Drive.
3. Report to me only the two status lines and the organization line. A `200` on both proves the Free plan allows API calls (the one point Zoho's pages disagree on). Save the `organization_id` in the plan; it is not a secret.
4. Later, for the Phase 4 sync, we generate a **second** Self Client grant with write scopes (`ZohoBooks.contacts.CREATE`, `ZohoBooks.invoices.CREATE`, `ZohoBooks.customerpayments.CREATE`, plus their READ scopes), kept as a separate credential from the read-only grant used by the n8n A5 workflow (Zoho Connection Guide, Section 1). The write scopes stay unissued until that sync is built and tested on staging.

## Done when

- Organization profile, basis, CPA invited, chart of accounts, items, no sales tax: Steps 1 to 6.
- Stripe connected with cards and ACH, bank added, portal on, opening balances signed off: Steps 9 to 12.
- `tools/zoho_books_check.sh` reports 200 and 200: Step 14.

Record the accounting basis, the organization id, and the date Books went live in `docs/CRM_BOOKKEEPING_PORTAL_PLAN.md`, decision log.
