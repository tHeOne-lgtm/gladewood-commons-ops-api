# Netlify sites: staff app and portal

Two sites, one repository (`GLADEWOOD-staff-app`). The staff app builds from the repository root; the portal builds from the `portal` folder. Each site is its own origin, which is what keeps resident and case manager sessions apart from staff sessions (plan Section 3).

Netlify's dashboard and API are not reachable from the assistant's sandbox, so site creation is a Paul step. Everything the repository can do ahead of time is done: both `netlify.toml` files carry the build command, publish folder, Node 22 pin, SPA redirect, and security headers.

## Before you start (2 minutes)

Have these three values open in another tab:

| Variable | Where it comes from |
| --- | --- |
| `VITE_API_URL` | `https://gladewood-commons-ops-api.onrender.com` |
| `VITE_SUPABASE_URL` | supabase.com, your project, Project Settings, API, "Project URL" |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | same page, the key that starts with `sb_publishable_`. Never the secret key. |

Assumption: menu labels below match Netlify's and Supabase's current layouts; the names may differ slightly, the sequence does not.

## 1. Portal site (10 minutes)

1. app.netlify.com, Add new site (or Add new project), Import an existing project, GitHub, pick `GLADEWOOD-staff-app`.
2. Build settings: Branch `main`. Base directory `portal`. Leave Build command and Publish directory as Netlify fills them (`npm run build`, `portal/dist`); `portal/netlify.toml` sets them anyway.
3. Environment variables: add the three rows from the table above. Do not add `NODE_ENV`; a value of `production` stops Netlify installing the TypeScript compiler the build needs.
4. Site name: pick something short such as `gladewood-portal`. Netlify shows the final URL (`https://<name>.netlify.app`). Copy it.
5. Deploy site. Done when the deploy log ends in "Site is live" and the URL shows the "Gladewood Commons" sign-in card with Email link and Password tabs.

## 2. Staff site (5 minutes)

Repeat step 1 with Base directory left empty, the same three variables, and a name such as `gladewood-staff`. Done when the URL shows the staff sign-in page.

## 3. Tell Supabase both URLs (3 minutes)

The portal's "Email me a sign-in link" button asks Supabase to send the user back to the portal's own address. Supabase only honors addresses on its allow list; otherwise the link lands on whatever Site URL is set, which may be the staff site.

1. supabase.com, your project, Authentication, URL Configuration.
2. Site URL: the staff site URL.
3. Redirect URLs: add the portal URL and the staff URL, each with `/**` on the end (for example `https://gladewood-portal.netlify.app/**`).
4. Save. Done when a test "Email me a sign-in link" from the portal lands back on the portal, signed in.

## 4. Send the two URLs to the assistant (1 minute)

Paste both site URLs into the chat. The assistant sets `CORS_ORIGINS` on the Render web service to exactly those two origins and confirms the redeploy. Until that is done the sites show "Cannot reach the API" after sign-in; that message is expected and clears on the redeploy.

## 5. First real sign-in (5 minutes)

1. Staff site: sign in as the owner account. Dashboard loads.
2. Users page: any account that has signed in to either site without a role shows as pending. Assign resident or case_manager to your test account.
3. Portal site: sign in as that test account. Home shows the tenancy summary, or "Nothing to show yet" when no tenancy is linked.

## Errors to watch

| What you see | Cause | Fix |
| --- | --- | --- |
| Build fails with `Missing build-time setting VITE_...` | A variable is missing or misspelled on that site | Site configuration, Environment variables, add it, Trigger deploy |
| Build fails with `tsc: not found` | `NODE_ENV=production` set on the site | Remove it and redeploy |
| Page loads, sign-in says "Cannot reach the API" | `CORS_ORIGINS` on Render does not contain this exact origin | Step 4 |
| Email link opens the staff site instead of the portal | Portal URL missing from Supabase Redirect URLs | Step 3 |
| Portal says "This account is a staff account" | You signed in with a staff role | Expected; staff use the staff site |

## Custom domains (optional, later)

`portal.gladewoodcommons.com` and `staff.gladewoodcommons.com` can be added under Domain management on each site. Doing so changes the origins, so repeat steps 3 and 4 with the new addresses.
