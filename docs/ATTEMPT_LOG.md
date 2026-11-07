# Attempt Log

One entry per problem that needed more than one attempt. Newest first.

## 2026-11-07: Command Center sign-in showed a blank status and never signed in

Took four builds, which is two over the agreed limit; the rule was set after this.

| Attempt | What was tried | Why it failed |
|---|---|---|
| 1 | Hand-written patch: load supabase-js from a CDN, replace `api()`, store the key in page settings | Three defects at once: the hash router erased the token fragment; the state loader dropped the key; the Supabase URL variable was declared after the init code that used it, so `createClient` threw and the sync card stopped working with a blank status |
| 2 | Capture the fragment in the first script and restore it before creating the client | Did not touch the two other defects; the blank status remained because the URL variable was still undefined at init |
| 3 | Rebuilt from the original with one script; URL defined first, key in its own storage slot, token handed to `setSession()`; verified in headless Chromium | Worked in test. Deploy failed in production because the library was a separate file and the deploy uploaded only `index.html` (404 on `/supabase.js`) |
| 4 | Inline the library into `index.html`; re-verified | Pending Paul's confirmation; blocked for the moment by Supabase's hourly auth-email limit after repeated test links |

Lesson: diagnose by reproduction before patching. Attempts 1 and 2 were guesses about the live page; attempt 3 came from running the page in a browser and reading the exception.

Alternative on the table if attempt 4 fails: password sign-in for staff alongside the email link, and custom SMTP to remove the email limit.
