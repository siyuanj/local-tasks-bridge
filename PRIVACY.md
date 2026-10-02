# Privacy Policy

**English** · [简体中文](PRIVACY.zh-CN.md)

*Effective October 1, 2026 · applies to Local Tasks Bridge 1.0 and later*

Local Tasks Bridge is open-source software that runs on your Mac and syncs
Apple Reminders with Google Tasks. This policy explains, in plain language,
what data it touches, where that data goes, and how you stay in control. The
short version: **your data stays on your Mac and with Apple and Google. It is
never sent to the maintainer or to anyone else.**

The public version of this policy is at
<https://siyuanj.github.io/local-tasks-bridge-site/privacy/>.

## Who is responsible

Local Tasks Bridge is maintained by Siyuan Jiang
([@siyuanj](https://github.com/siyuanj)) as an open-source project. The
maintainer does not operate any server for it and does not receive, store or
process your tasks, reminders or credentials.

## What the software accesses

**On your Mac (Apple Reminders).** After you grant permission in macOS, the app
can read and write your reminders through Apple's EventKit framework. macOS
grants this for all lists; the bridge reads and writes only the lists you
select. To let you choose, it also reads the names of all your lists and the
accounts they belong to. For each synced reminder it uses the title, notes, due
date, completion state, list, and the identifiers and timestamps needed to
match it.

**In your Google account (Google Tasks).** When you sign in, you grant three
permissions (OAuth scopes):

| Scope | Used for |
| --- | --- |
| `https://www.googleapis.com/auth/tasks` | Reading your task lists and tasks, and creating, updating, completing and deleting tasks and lists, to keep them in sync |
| `openid` | Your Google account ID, so the sync map can be bound to your account |
| `email` | Your account's e-mail address, to show you which account is connected |

The bridge requests no other access — not Gmail, Calendar, Drive or contacts.

## What is stored, and where

Everything is stored locally on your Mac, in your user account:

| File | Contents |
| --- | --- |
| `~/.config/local-tasks-bridge/config.json` | Your settings, including the names of the selected lists |
| `…/token.json` | Your Google sign-in tokens, including an ID token that contains your account ID and e-mail address |
| `…/credentials.json` | Your own Google OAuth client, if you imported one |
| `…/state.json` | The sync map: identifiers and fingerprints that link each reminder to its Google task, the item titles and list names, and hashed account identifiers |
| `…/status.json` | The result of the last sync: times, counts and hashes, no titles |
| `…/backups/` | Copies of the files above made before risky operations |
| `~/Library/Logs/LocalTasksBridge/` | Logs of what each sync did, including task titles |

These folders and files are readable only by your macOS user account. Nothing
is stored on any server operated by the maintainer — there is none.

The bridge also adds a short footer to the notes of each synced Google task
(“Synced from Apple Reminders.”, the list name, and two identifiers). It is
stored in your Google account like the rest of the task.

## What is sent where

- **To Google:** requests to Google's sign-in endpoints (`accounts.google.com`,
  `oauth2.googleapis.com`, `openidconnect.googleapis.com`) and to the Google
  Tasks API (`tasks.googleapis.com`). To sync, these requests carry the content
  of your synced items — titles, notes with the footer, due dates, completion
  state and list names. They go directly from your Mac to Google over HTTPS,
  or through a proxy that you configure.
- **To Apple:** changes to your reminders, written through EventKit on your Mac.
  iCloud then syncs them to your other devices under Apple's terms.
- **To GitHub, only when you ask:** **Check for Updates…** asks GitHub's public
  API for the latest release, and **Help** opens GitHub pages in your browser.
  The installer downloads the app from GitHub. GitHub sees your IP address, as
  with any web request; nothing about your tasks is sent.
- **To the maintainer or anyone else:** nothing. There is no telemetry, no
  analytics, no crash reporting, no advertising and no tracking.

## The shared Google client

Release builds can include the maintainer's Google OAuth client named
“Local Tasks Bridge”, so you can sign in without creating your own:

- Google records that you authorized that client, and it appears under that
  name in your Google Account's list of connected apps.
- The client only identifies the app to Google. Your sign-in tokens are created
  for you and stored on your Mac, and your task data still goes only between
  your Mac and Google. The maintainer cannot access your account or your tasks
  through the shared client.
- In the Google Cloud console, the maintainer can see aggregate numbers for the
  project — for example how many users have authorized the client and how many
  API requests were made and failed — but not who you are or what your tasks
  contain.

If you prefer, use [your own Google Cloud client](docs/google-cloud-setup.md);
then Google sees your own project as the app.

## Google API Services User Data Policy

Local Tasks Bridge's use and transfer of information received from Google APIs
adheres to the
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
including the Limited Use requirements. In particular:

- Google user data is used only to provide the sync you set up — reading and
  updating your Google Tasks to match your selected Reminders lists — and to
  show you its status.
- It is not transferred to anyone, except to Apple Reminders on your own Mac as
  part of the sync you requested, or if required by law.
- It is not used for advertising, profiling, or training artificial
  intelligence or machine learning models.
- No person reads it. The software runs on your Mac; the maintainer has no
  access to it. If you choose to share diagnostics or logs with someone, you
  decide what to send.

## How long data is kept

Local data stays on your Mac until you delete it. Uninstalling with the
**Uninstall…** option to delete data, or `ltb uninstall --delete-data`,
removes the settings folder and the logs. Deleting local data does not delete
your reminders or your Google tasks; the footer lines remain in the notes of
synced Google tasks until you remove them.

## Your choices and controls

- **Revoke Google access** at any time at
  <https://myaccount.google.com/permissions> (look for “Local Tasks Bridge”, or
  the name of your own client), or with `ltb signout --revoke`.
- **Revoke Reminders access** in **System Settings → Privacy & Security →
  Reminders**.
- **Pause** syncing from the menu bar, choose which lists are synced, or
  uninstall the app at any time.
- **Inspect** everything: the software is open source, and all its files are in
  the locations listed above.

## Security

Sign-in uses Google's OAuth flow with PKCE and a redirect to your own Mac
(`127.0.0.1`), and the state of each sign-in is validated. Local files are
private to your user account. No method of storage or transmission is
completely secure; report security problems as described in
[SECURITY.md](SECURITY.md).

## Children

Local Tasks Bridge is a general-purpose productivity tool. It is not directed at
children and collects no data for the maintainer about anyone.

## Changes and contact

If the software's data practices change, this policy is updated in the
repository and on the public page, with a new effective date, and the change is
listed in the [changelog](CHANGELOG.md).

Questions: open an issue at
<https://github.com/siyuanj/local-tasks-bridge/issues> (don't include personal
data), or use the support address shown on the Google consent screen.
