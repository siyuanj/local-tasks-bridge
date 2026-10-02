# Create your own Google Cloud client

**English** · [简体中文](google-cloud-setup.zh-CN.md)

Local Tasks Bridge can sign in to Google with **your own OAuth client** instead
of the shared one built into release builds. You need this when:

- you built the app from source (source builds don't contain the shared client);
- you want your own 50,000-requests-per-day Google Tasks quota and the
  1-minute default sync interval;
- the shared client is unavailable, for example because it has reached Google's
  100-user limit for unverified apps;
- your Google Workspace (company or school) account doesn't allow the shared
  client.

It takes about ten minutes and costs nothing: no billing account is needed. You
will create a Google Cloud project, enable the Google Tasks API, describe your
app to Google, publish it, create a client of type **Desktop app**, download its
JSON file and import that file into Local Tasks Bridge.

The steps follow the current Google Cloud console, where the OAuth settings
live under **Google Auth Platform**. If you use the console in another
language, the [Chinese version](google-cloud-setup.zh-CN.md) of this guide
lists the Chinese menu names.

## 1. Create a project

1. Open <https://console.cloud.google.com/projectcreate> and sign in. Using the
   same Google account you want to sync is simplest, but any account works.
2. **Project name:** for example `Local Tasks Bridge`. For a personal Gmail
   account, leave **Location** as **No organization**.
3. Click **Create**, then make sure the new project is selected in the project
   picker at the top of the page.

## 2. Enable the Google Tasks API

1. Open <https://console.cloud.google.com/apis/library/tasks.googleapis.com>.
2. Check that your new project is selected, then click **Enable**.

## 3. Describe your app (Branding)

1. Open <https://console.cloud.google.com/auth/overview>. If the page says that
   Google Auth Platform is not configured yet, click **Get started**:
   - **App information:** an **App name** such as `Local Tasks Bridge (personal)`
     and your address as **User support email**. Click **Next**.
   - **Audience:** choose **External** (see [Workspace accounts](#google-workspace-accounts)
     for **Internal**). Click **Next**.
   - **Contact information:** your e-mail address. Click **Next**.
   - **Finish:** agree to the *Google API Services: User Data Policy*, click
     **Continue**, then **Create**.
2. Open **Branding** (<https://console.cloud.google.com/auth/branding>) and check
   the app name and support e-mail. Don't upload a logo: adding one makes the
   app subject to Google's brand verification.
3. If **Publish app** in the next step stays disabled, Google wants the app's
   public pages first. Fill in, under **App domain** and **Authorized domains**:
   - **Application home page:** `https://siyuanj.github.io/local-tasks-bridge/`
   - **Application privacy policy link:** `https://siyuanj.github.io/local-tasks-bridge/privacy/`
   - **Authorized domain:** `siyuanj.github.io`

   These are the project's public pages describing this same local-only
   software, so they are accurate for your personal client too. You may use your
   own pages instead. Click **Save**.

## 4. Publish the app (Audience)

1. Open **Audience** (<https://console.cloud.google.com/auth/audience>).
2. Under **Publishing status** you will see **Testing**. Click **Publish app**
   and confirm. The status changes to **In production**.

Why publish? While an app is in **Testing**, Google lets only listed test users
sign in and **expires their sign-in after 7 days**, so the bridge would stop
every week. In production your sign-in lasts until you revoke it (Google may
still expire a sign-in that has not been used for about six months).

Publishing does not make your tasks public and does not list your app anywhere.
Your app stays **unverified**: when you sign in, Google shows **“Google hasn't
verified this app”**. Click **Advanced**, then **Go to *your app name*
(unsafe)**. That is expected for a client you created yourself — you are its
developer. Google requires verification only for apps used by more than 100
people; a personal client does not need it.

## 5. Data Access (optional)

You can skip this step: Local Tasks Bridge asks for exactly the scopes it needs
when you sign in. If you want them listed in the console anyway, open **Data
Access** (<https://console.cloud.google.com/auth/scopes>), click **Add or remove
scopes**, and select:

| Scope | Why |
| --- | --- |
| `https://www.googleapis.com/auth/tasks` | Read and write your task lists and tasks |
| `openid` | Identify the Google account, so the sync map stays bound to it |
| `https://www.googleapis.com/auth/userinfo.email` (`email`) | Show which account is connected |

Click **Update**, then **Save**. The bridge requests nothing else — no Gmail,
Calendar, Drive or Cloud access.

## 6. Create the Desktop app client

1. Open **Clients** (<https://console.cloud.google.com/auth/clients>) and click
   **Create client**.
2. **Application type:** **Desktop app**. Other types, such as **Web
   application**, don't work with the bridge's sign-in and are refused on
   import.
3. **Name:** anything, for example `Local Tasks Bridge – my Mac`. Click
   **Create**.
4. In the **OAuth client created** dialog, click **Download JSON**. The file is
   saved to your Downloads folder with a name like
   `client_secret_123456789012-abc….apps.googleusercontent.com.json`.

Download the file right away: Google shows the client secret only when the
client is created. If you lose it, open the client in **Clients** and add a new
secret, or create a new client.

Treat the file as private. Don't e-mail it, paste it into chats or commit it
to a Git repository.

## 7. Import the client into Local Tasks Bridge

- **In the app:** in the setup assistant, choose **Use my own Google Cloud
  OAuth client** and click **Choose Client JSON…**; later, use **Import Client
  JSON…** in **Settings… → Google**.
- **In Terminal:**

  ```bash
  ltb client import ~/Downloads/client_secret_*.apps.googleusercontent.com.json
  ```

The bridge checks that the file belongs to a **Desktop app** client, copies it
to `~/.config/local-tasks-bridge/credentials.json` (readable only by you) and
switches to it (`oauth_client` becomes `custom`). You can delete the copy in
Downloads afterwards. Check the result with `ltb client status`.

Then sign in: continue the setup assistant, choose **Reconnect Google…** in the
app, or run `ltb auth`. Your browser opens Google's sign-in page:

1. Choose your account.
2. On **“Google hasn't verified this app”**, click **Advanced** → **Go to …
   (unsafe)**.
3. Leave **“Create, edit, organize, and delete all your tasks”** ticked and click
   **Continue**.
4. The browser shows **“Google authorization received”**; return to the app.

The sign-in waits up to five minutes for you to finish.

### Switching from the shared client

Import your own client as above, then sign in again with the **same Google
account**. The sync map is bound to your Google account ID, not to the client,
so it is kept and syncing continues where it left off. The default interval
for your own client is 1 minute; you can change it in **Settings** (see
[configuration](configuration.md#sync-interval-and-google-quota)).

## Google Workspace accounts

If your Google account belongs to a company, school or university, the
administrator decides which third-party apps may access Google data:

- If sign-in fails with **“Access blocked”**, `admin_policy_enforced` or a
  message that your institution needs to review the app, ask the administrator
  to trust your client ID (Admin console → **Security → Access and data control
  → API controls → Manage third-party app access**), or use a personal Google
  account.
- If you create the project inside your organization, you can choose
  **Internal** as the audience. Internal apps can be used only by accounts of
  that organization, need no verification, show no “unverified” warning and
  have no 7-day limit. An account outside the organization then gets
  `org_internal`.

## Troubleshooting

| What you see | Cause | Fix |
| --- | --- | --- |
| `Error 403: access_denied` and “… has not completed the Google verification process” | The app is still in **Testing** and your account isn't a test user | [Publish the app](#4-publish-the-app-audience), or add yourself under **Audience → Test users** |
| `access_denied` right after you clicked **Cancel** | You declined the consent screen | Sign in again |
| `Error 400: redirect_uri_mismatch` | The client is a **Web application** | Create a **Desktop app** client and import its JSON; the bridge refuses Web clients on import |
| `Error 401: invalid_client` or `deleted_client` | The client was deleted, or its secret was reset | Download a fresh JSON (or create a new client) and import it |
| “This app is blocked” | Google blocked the sign-in — usual for accounts in Google's Advanced Protection Program, or because of Workspace policies | Use a personal account without Advanced Protection, or ask your administrator |
| `admin_policy_enforced`, “Access blocked: … admin” | Workspace policy | See [Workspace accounts](#google-workspace-accounts) |
| `org_internal` | The app is **Internal** and you used an account outside the organization | Use an account of that organization, or switch the audience to **External** |
| The app says Google did not grant access to Google Tasks | The Tasks permission was unticked on the consent screen | Sign in again and leave it ticked; the bridge rejects such a sign-in immediately |
| You must sign in again every week | The app is still in **Testing** | [Publish the app](#4-publish-the-app-audience), then sign in once more |
| “Google Tasks API has not been used in project … or it is disabled” in the log | The API isn't enabled in this project | [Enable it](#2-enable-the-google-tasks-api) and wait a few minutes |
| Later on: “sign-in expired or was revoked” | The token was revoked (for example at <https://myaccount.google.com/permissions>) or expired | Choose **Reconnect Google…** or run `ltb auth` |
| The browser can't load Google at all | No route to Google (common in mainland China) | Set up a proxy; see [Network and proxy](troubleshooting.md#network-and-proxy) |

More help: [troubleshooting.md](troubleshooting.md).
