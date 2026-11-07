# Setup Walkthrough: Supabase, Render, Netlify, First Sign-in, Migration

Click-by-click version of the README "Phase 0 steps that need Paul". Dashboard paths and link patterns were checked against the vendors' docs on 2026-11-07; exact button wording can lag the docs by a release, so where two labels are plausible both are given. Links containing `_` open the current project in the Supabase dashboard.

Have ready: a password manager window, a blank text file outside any repo for pasting values, and your Mac.

---

## A. Supabase

### A1. Reset the database password

1. Go to https://supabase.com/dashboard and sign in as `pjssubscriptions@gmail.com`.
2. Click the project card **gladewood-commons-ops**.
3. In the left icon sidebar, click **Database** (cylinder icon).
4. In the Database sub-menu that opens, scroll to the bottom and click **Settings**. Shortcut: paste https://supabase.com/dashboard/project/_/database/settings into the address bar.
5. Find the card titled **Database password**.
6. Click **Reset database password**.
7. In the dialog, click **Generate a password**. If you would rather type one, use 24 or more characters, letters and digits only, no symbols; symbols force URL encoding and were the cause of the earlier connection-string trouble.
8. Click the copy icon next to the password and paste it into your password manager now. It is not shown again.
9. Click **Reset database password** (or **Update password**) to confirm.
10. Check: a green toast says the password was updated.

### A2. Copy the connection string

1. In the top bar of the same project, click **Connect**.
2. The **Connection String** tab is selected by default. Leave **Type** as **URI**.
3. In the **Method** (or **Connection type**) dropdown, choose **Session pooler**.
4. Click the copy icon. The string looks like `postgresql://postgres.<ref>:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres`.
5. Paste it into your blank text file. Replace `[YOUR-PASSWORD]`, including the square brackets, with the password from A1.
6. Keep this string for step B1. Do not save it into any repository folder.

### A3. Auth URLs

1. Left icon sidebar: click **Authentication** (person icon).
2. In the Authentication sub-menu, under **Configuration**, click **URL Configuration**. Shortcut: https://supabase.com/dashboard/project/_/auth/url-configuration.
3. In the **Site URL** field, delete what is there and type `https://psgccommandcenter.live`. Click **Save** for that card.
4. In the **Redirect URLs** card, click **Add URL**.
5. Type `https://psgccommandcenter.live/**` (two asterisks) and click **Save**.
6. Check: the new URL appears in the Redirect URLs list.

### A4. Email sign-in provider

1. Authentication sub-menu: click **Sign In / Providers**.
2. Click the **Email** row to expand it.
3. Confirm the **Enable Email provider** toggle is on. Leave the other toggles at their defaults; magic links work without further changes.
4. If you changed anything, click **Save**.

### A5. Publishable key (for the Command Center page)

1. Left icon sidebar: click the gear icon **Project Settings** (bottom of the sidebar).
2. Click **API Keys**. Shortcut: https://supabase.com/dashboard/project/_/settings/api-keys.
3. If you see a tab **Publishable and secret API keys**, click it. Under **Publishable key**, click the copy icon. It starts with `sb_publishable_`.
4. If you see only **Legacy API keys**, copy the key labeled **anon** **public** instead.
5. Paste it into your text file labeled "publishable key". Never copy anything labeled **secret**, `sb_secret_`, or **service_role**.

### A6. JWT signing mode

1. Project Settings: click **JWT Keys**. Shortcut: https://supabase.com/dashboard/project/_/settings/jwt.
2. Click the **JWT Signing Keys** tab.
3. If a **Current key** is listed (with an algorithm such as ES256, RS256, or EdDSA): nothing to do here. Render needs only `SUPABASE_URL`.
4. If instead you see a notice about the **legacy JWT secret** and a button **Migrate JWT secret**:
   1. Click **Migrate JWT secret**. A new asymmetric key appears as **Standby**.
   2. Click **Rotate keys** and confirm. The new key becomes **Current**. Nobody is signed in yet, so rotation disrupts no one.
   3. Leave the legacy secret as **Previously used**; do not revoke it today.
5. Write "JWKS" in your text file so you remember Render needs only `SUPABASE_URL`.

### A7. Project URL

1. Project Settings: click **General**.
2. In the **Project ID** row, click the copy icon.
3. Your Project URL is `https://<that id>.supabase.co`. Write it in your text file labeled "SUPABASE_URL".

### A8. Backups (decision, no clicks required today)

1. Left icon sidebar: **Database**, then **Backups**. Shortcut: https://supabase.com/dashboard/project/_/database/backups/scheduled.
2. On the Free plan the page says backups are not available. Pro adds daily backups with 7 day retention. Decide now or when real resident balances go in.

---

## B. Render

### B1. Environment variables

1. Go to https://dashboard.render.com and open the API web service (the one that deploys `gladewood-commons-ops-api`).
2. In the service's left pane, click **Environment**.
3. Under **Environment Variables**, for each row below click **+ Add Environment Variable**, type the **Key**, paste the **Value**:
   - `DATABASE_URL` = the full string from A2 (with the real password)
   - `CORS_ORIGINS` = `https://psgccommandcenter.live`
   - `SUPABASE_URL` = the URL from A7
   - `BOOTSTRAP_ADMIN_EMAILS` = `paulselman@gladewoodcommons.com`
   - `ENV` = `production`
   If `DATABASE_URL` already exists, click its pencil icon and replace the value instead of adding a second one.
4. Only if A6 showed a legacy secret and you did not rotate: add `SUPABASE_JWT_SECRET` = that secret.
5. Click the arrow next to the **Save** button and choose **Save only**. (Deploying now would run new code against old settings.)
6. Check: the five rows are listed with values masked.

### B2. Build, start, and health settings

1. Service left pane: click **Settings**.
2. Near the top, note the **Instance Type**. Free or Starter decides step 5.
3. Under **Build & Deploy**:
   - **Branch**: `master`.
   - **Build Command**: click **Edit**, set `pip install -r requirements.txt`, click **Save Changes**.
   - **Start Command**: click **Edit**, set `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, **Save Changes**.
   - **Auto-Deploy**: **On Commit** (or **After CI Checks Pass**).
4. Under **Health Checks** (may be further down): **Health Check Path**: click **Edit**, set `/api/health`, **Save Changes**.
5. Migrations:
   - **Starter or higher:** **Pre-Deploy Command**: click **Edit**, set `alembic upgrade head`, **Save Changes**.
   - **Free:** the Pre-Deploy field is not available. Go back to **Start Command** and set it to `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
6. While on Settings, find **Outbound IP Addresses** and copy them into your text file; you will need them for network restrictions later (step G2).

---

## C. Merge the pull request and deploy

1. Open https://github.com/tHeOne-lgtm/gladewood-commons-ops-api/pull/1.
2. Scroll to the bottom. Click **Ready for review**.
3. Click **Merge pull request**, then **Confirm merge**.
4. Back in Render, open the service and click **Events** (or **Deploys**). A new deploy starts within a minute.
5. Click the deploy row, then **Logs**. You are looking for these lines, in order:
   - `Running upgrade  -> 0001` and `Running upgrade 0001 -> 0002`
   - `Application startup complete`
6. In a browser tab, open `https://<your-service>.onrender.com/api/health`. Expect `{"ok":true,"db":true}`.
7. Open `https://<your-service>.onrender.com/api/properties`. Expect a small JSON body with "Missing bearer token". That 401 is correct.
8. If health shows `"db":false`, go to Render **Logs** and look for "Masked DSN"; it means the connection string or password is wrong. Redo A2 and B1.

---

## D. Patch the Command Center (on your Mac)

### D1. Find the source

1. In Finder, open the folder you upload to Netlify (the one containing the Command Center's `index.html`; your repo note says app code lives in `~/Developer`).
2. Look in that folder for a file named `_headers` or `netlify.toml`.
   - If neither exists, there is no security policy to edit; skip D2. The "Allowed by the site security policy" text in the page is the app's own webhook check, not a browser policy.
   - If one exists, do D2.

### D2. Security policy (only if a file was found)

1. Open the file in a plain text editor (VS Code, or TextEdit in plain text mode: Format, Make Plain Text).
2. Find the line containing `Content-Security-Policy`.
3. In the `connect-src` part, add a space and then `https://<your-service>.onrender.com https://<project id>.supabase.co`.
4. In the `script-src` part, add a space and then `https://cdn.jsdelivr.net`.
5. Save.

### D3. Edit index.html

1. Open `index.html` in VS Code (TextEdit will work but is slow on a 2.4 MB file).
2. Press Cmd+F and search `</head>`. Place the cursor on the line before it and paste:
   `<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js"></script>`
3. Search `function api(path,opt)`. Select from `function api(path,opt){` through the end of that function, which is `return r.status===204?null:r.json()})}`. Delete the selection.
4. Paste the block from `docs/DASHBOARD_INTEGRATION.md` section **3b**. Replace `https://YOUR-PROJECT.supabase.co` with the URL from A7 and `sb_publishable_...` with the key from A5.
5. Search `id="apiUrl"`. Just after that input's closing `</label>`, paste the HTML from section **3c**.
6. Search `$('#apiUrl').onchange`. Just after that statement ends (the `save()};`), paste the JavaScript from section **3c**.
7. Save the file.

### D4. Deploy to Netlify

1. Go to https://app.netlify.com, open the site for `psgccommandcenter.live`.
2. Click the **Deploys** tab.
3. Drag the whole folder from Finder onto the area labeled **Need to update your site? Drag and drop your site output folder here**. (If you normally run `netlify deploy --prod` in Terminal, do that instead.)
4. Wait for the deploy row to read **Published**.

---

## E. First sign-in

1. Open https://psgccommandcenter.live in a browser. Press Cmd+Shift+R once to bypass cache.
2. Go to the **Gladewood sync** card.
3. In **API base URL**, paste `https://<your-service>.onrender.com` with no trailing slash. Click outside the field so it saves.
4. In **Staff email**, type `paulselman@gladewoodcommons.com`. Click **Email me a sign-in link**.
5. Open the email from Supabase and click the link. It returns you to the site. The status next to the sign-in buttons should read your email and `(admin)`.
6. Click **Test**. Expect "Connected."
7. Click **Pull**. Confirm the prompt. Existing properties, prospects, residents, and conflict entries load.
8. If Test says "no staff role yet", the email you used does not match `BOOTSTRAP_ADMIN_EMAILS` exactly. Fix the variable in Render (B1), **Save and deploy**, sign out and in again.
9. Open the browser console (Option+Cmd+J in Chrome). If you see "Refused to connect", a security policy blocked it: do D2.

---

## F. Legacy migration (Mac Terminal)

1. Open Terminal.
2. Run, one line at a time:
   ```
   cd ~/Documents/GitHub/gladewood-commons-ops-api
   git checkout master
   git pull
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Create the local env file. Run `nano .env`, type exactly one line:
   `DATABASE_URL=postgresql://...` (the string from A2), then press Ctrl+O, Enter, Ctrl+X.
4. Run the dry run:
   ```
   python -m app.cli migrate-legacy
   ```
5. Copy everything it prints and send it to me. `rejections` lists any row whose status, deposit, rent, or lease date could not be read.
6. Find your user id for the apply step: in Supabase, left sidebar **SQL Editor**, click **New query**, paste `select id, email, role from users;`, click **Run**. Copy the `id` for your email.
7. When rejections are empty (or you choose to proceed without those rows), run:
   ```
   python -m app.cli migrate-legacy --apply --actor <your id>
   ```
   Add `--allow-partial` only if you accept skipping the rejected rows.
8. Check in the Command Center: nothing changes there yet; the CRM screens come next. The API shows the result at `/api/pipelines/<id>/summary`.

---

## G. Cleanup

### G1. Remove the bootstrap variable

1. Render, service, **Environment**.
2. On the `BOOTSTRAP_ADMIN_EMAILS` row, click the trash icon.
3. Click the arrow next to **Save** and choose **Save and deploy**.
4. Reload the Command Center. The status still shows `(admin)`; the role lives in the `users` table.

### G2. Network restrictions (optional, after F is done)

1. Supabase: https://supabase.com/dashboard/project/_/database/settings, card **Network Restrictions**.
2. Click **Add restriction**. Enter each Render outbound IP from B2 as `x.x.x.x/32`. Click **Save**.
3. Also add your home IP as `/32` if you will run the Terminal migration again; otherwise the CLI is blocked. Find it at https://www.whatismyip.com.
4. If the card shows a paid-plan notice on Free, skip this step.

### G3. Stripe ACH (for Phase 3)

1. https://dashboard.stripe.com, **Settings** (gear), **Payments**, **Payment methods**.
2. Find **ACH Direct Debit** (under Bank debits) and click **Turn on**. Stripe may ask for business details; complete them. Approval can take days, which is why this starts now.
