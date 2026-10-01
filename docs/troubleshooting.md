# Troubleshooting and FAQ

**English** · [简体中文](troubleshooting.zh-CN.md)

Start here:

1. **Click the menu bar icon.** The first lines say what is going on and what
   to do next.
2. **In Terminal, run `ltb status`.** It is instant and reads only local
   files. `ltb doctor` checks the installation; `ltb doctor --online` also
   tests the Google connection.
3. **Look at the log** with **Open Logs** in the menu. The log contains task
   titles, so read it yourself rather than posting it (see
   [Logs and diagnostics](#logs-and-diagnostics)).

## Status conditions

`ltb status` and the app report one of these conditions:

| Condition | Meaning | What to do |
| --- | --- | --- |
| `healthy` | Reminders and Google Tasks are in sync | Nothing |
| `running` | A cycle is in progress | Wait a moment |
| `paused` | You paused syncing; the last sync result stays visible | **Resume Sync**, or `ltb resume` |
| `setup_required` | Setup isn't finished, or the Reminders helpers are missing | **Finish Setup…**; if helpers are missing, reinstall the app |
| `never_synced` | Nothing has been synced yet | Finish the first sync in the setup assistant |
| `attention` | A dry run or a sign-in succeeded, but no full sync has finished since | Finish the first sync, or check again after the next cycle |
| `auth_required` | The Google sign-in is missing, expired or revoked | **Reconnect Google…**, or `ltb auth` — see [below](#sign-in-expired-or-revoked) |
| `account_binding_required` | The Apple or Google account differs from the one the sync map belongs to | See [Account binding required](#account-binding-required) |
| `mutation_approval_pending` | A large batch of deletions or completions is held; everything else keeps syncing | Answer in **Review Pending Changes…** — see [below](#bulk-changes-waiting-for-approval) |
| `mutation_blocked` | A sync stopped because its plan exceeded the safety limits | **Review Pending Changes…**, or `ltb approvals show` |
| `failed` | The last cycle failed | `ltb doctor --online`, then the log; the sections below cover the usual causes |
| `agent_stopped` | Background sync isn't running | Open Local Tasks Bridge; it starts at login once set up |
| `status_unreadable` | The status file can't be read | Back up `~/.config/local-tasks-bridge/status.json`; it is rewritten after the next sync |
| `unknown` | The state is unclear | `ltb manage check`, then the log |

When several conditions apply, the most urgent one is shown — for example a
failed sync is reported before “background sync isn't running”.

## Installing and opening the app

### macOS says the app can't be opened, or “was not opened”

Version 1.0 is ad-hoc signed and not notarized by Apple, so Gatekeeper stops the
first launch of a copy downloaded with a browser:

- **macOS 15 Sequoia and later:** click **Done**, open **System Settings →
  Privacy & Security**, scroll to **Security**, click **Open Anyway** next to
  the message about Local Tasks Bridge and confirm with your password or Touch
  ID.
- **macOS 13 and 14:** Control-click the app, choose **Open**, then **Open**
  again.

Or let the installer install the zip; it verifies the checksum and clears the
quarantine flag, so there is no prompt:

```bash
curl -fsSL https://raw.githubusercontent.com/siyuanj/local-tasks-bridge/main/install.sh \
  | bash -s -- --zip ~/Downloads/LocalTasksBridge-macos-arm64.zip
```

If you prefer doing it by hand and have checked the download against
`SHA256SUMS`: `xattr -dr com.apple.quarantine ~/Applications/"Local Tasks Bridge.app"`.

### macOS says the app is damaged

That usually means an incomplete download or a zip unpacked by a tool that
broke the app's signature. Download the zip again, compare it with
`SHA256SUMS`, and unpack it with Finder or install it with the installer's
`--zip` option. Don't run a copy whose checksum doesn't match.

### Move the app into Applications before opening it

If you open the app straight from Downloads or a disk image, macOS may run it
from a hidden temporary location, and the login item can't find it after a
restart. Move **Local Tasks Bridge.app** into `~/Applications` or
`/Applications` first, then open it. While it runs from such a location, the
app refuses to turn on **Start at login**, import an earlier setup, finish
setup or install the command-line tool, and asks you to move it.

### “Python 3.9 or newer is required”

The sync engine runs on Python. Release builds include their own Python, so
this message normally appears only for an app built from source: it looks for
the Python of Apple's Command Line Tools, then Homebrew's. Install the Command
Line Tools:

```bash
xcode-select --install
```

Then quit and reopen the app. Alternatives: Python from
<https://www.python.org/downloads/> or `brew install python`. To force a
particular interpreter for `ltb`, set `LTB_PYTHON=/path/to/python3`.

### `ltb: command not found`

The installer links `ltb` into `~/.local/bin`. Add that folder to your `PATH`:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

and open a new Terminal window. You can always run it by its full path:
`~/Applications/"Local Tasks Bridge.app"/Contents/Resources/bin/ltb status`.

### Building from source fails

- `xcode-select: error` or `swiftc` not found: install the Command Line Tools
  with `xcode-select --install`.
- Errors after a macOS update: the Command Line Tools may need an update. Check
  **System Settings → General → Software Update**, or remove
  `/Library/Developer/CommandLineTools` and install them again.
- Python older than 3.9 is reported: the Command Line Tools include a suitable
  `python3`; make sure `xcode-select -p` prints a path.

### The settings file can't be read

If `config.json` is damaged, the app offers **Reset Settings…** — in the menu,
as a banner in **Settings… → General**, and on the setup screen. It keeps a
backup copy of the unreadable file, starts from the default settings and lets
you run the setup assistant again; your Google sign-in and sync map are kept.
In Terminal, `ltb config init --force` does the same.

## Reminders access

### Reminders access is denied or missing

Symptoms: the menu says *Local Tasks Bridge can't read Reminders*, or a command
fails with `reminders_unavailable` (exit code 6).

1. Open **System Settings → Privacy & Security → Reminders** and turn on
   **Local Tasks Bridge**. On macOS 14 and later the app needs full access,
   because it writes reminders as well as reading them.
2. If it isn't listed, or switching it on doesn't help, reset the permission so
   that macOS asks again, then quit and reopen the app and click **Allow**:

   ```bash
   tccutil reset Reminders io.github.siyuanj.LocalTasksBridge
   ```

If the app says it can only add reminders, it was given add-only access:
switch it to full access in the same place. If access is restricted by Screen
Time or a device management profile, ask whoever manages this Mac.

### macOS asks for Reminders access again after an update

1.0 builds are ad-hoc signed. macOS remembers privacy permissions per code
signature, and an ad-hoc signature changes with every build, so after an
update macOS may treat the app as new and ask again. Click **Allow**. If an old
entry stays switched off, use the `tccutil` command above. Builds signed with a
Developer ID, planned for a later version, keep the permission across updates.

### `ltb` in Terminal asks for Reminders access

macOS gives Reminders access to the app that starts a process. When the menu
bar app runs the engine, the helpers use the app's permission. When you run
`ltb sync`, `ltb lists` or `ltb approvals show` in Terminal, the responsible
app is Terminal (or iTerm, or your editor), so macOS asks for that app. Allow
it, or leave syncing to the menu bar app. `ltb status` and `ltb doctor` don't
read Reminders.

## Google sign-in

### Sign-in expired or revoked

The app says *Sign in to Google again to keep syncing*, or `ltb status` shows
`auth_required`. Usual causes: you removed the app's access at
<https://myaccount.google.com/permissions>; your own client is still in
**Testing**, where Google expires sign-ins after 7 days (see
[Publish the app](google-cloud-setup.md#4-publish-the-app-audience)); the
sign-in wasn't used for about six months; or a Google security event.

Fix: choose **Reconnect Google…** (**Settings → Google**) or run `ltb auth`.
Syncing resumes on the next cycle. As long as you sign in to the same Google
account, the sync map is kept.

If Google simply can't be reached while the sign-in is refreshed — no network,
or a missing proxy — the app reports a network problem (*Google can't be
reached*, exit code 9) instead. Fix the connection; no new sign-in is needed.

### Google hasn't verified this app

Google shows this warning for any OAuth client that hasn't gone through its
verification — the shared client until the maintainer completes verification,
and a personal client you created yourself. Click **Advanced**, then **Go to …
(unsafe)**. The consent screen lists exactly what you grant: your tasks, plus
your basic Google identity (account ID and e-mail address). The bridge runs on
your Mac; your tasks are never sent to the maintainer. See
[PRIVACY.md](../PRIVACY.md).

### Sign-in is rejected because the Tasks permission was unticked

Google's consent screen lets you untick individual permissions. Without
**“Create, edit, organize, and delete all your tasks”** the bridge can't work,
so it rejects the sign-in immediately. Sign in again and leave it ticked.

### The browser didn't open, or sign-in timed out

- Sign-in waits up to five minutes. Start it again if it timed out.
- To open the address yourself: `ltb auth --no-browser` prints it.
- After you approve, Google sends the browser to `http://127.0.0.1:<port>/` on
  your own Mac. If a browser proxy extension sends local addresses through the
  proxy, that page fails to load; add `127.0.0.1` and `localhost` to its bypass
  list.

### Errors shown on Google's page

`access_denied`, `redirect_uri_mismatch`, `invalid_client`, “This app is
blocked”, `admin_policy_enforced` and `org_internal` are explained in the
[Google Cloud setup troubleshooting](google-cloud-setup.md#troubleshooting).

### The shared client isn't offered, or doesn't accept new users

The shared client exists only in release builds that include it, never in
source builds. Until the maintainer completes Google's verification, Google
accepts at most 100 users for it in total. If it's missing or full, use
[your own client](google-cloud-setup.md) — it takes about ten minutes and has
no such limit.

## Account binding required

**What it protects.** The sync map records which reminder belongs to which
Google task. It is bound to the Apple account(s) your selected lists live in
and to your Google account ID; only hashes of these identifiers are stored.
If the bridge suddenly sees a different Google account, or reminders from a
different Apple account, reusing the map could make it treat everything as
deleted, or write into the wrong account. So it stops before reading or writing
any list.

**Typical causes:** you signed in to a different Google account by mistake; the
Mac's iCloud account changed; the config folder was copied from another Mac or
user; a very old sync map without a binding.

**What to do:**

- **The account change was a mistake** (for example you signed in to the wrong
  Google account): choose **Pair Accounts Again…** and, in the sheet that
  opens, **Use a Different Google Account** to sign in to the right one.
  Syncing then continues; nothing needs rebuilding.
- **The change is intended:** choose **Pair Accounts Again…** — in **Settings… →
  Google**, or through **Reconnect Google…** in the menu while the account
  check fails. The sheet shows the Apple and Google accounts now in use; when
  you confirm, the bridge backs up your private files, moves the old sync map
  into `~/.config/local-tasks-bridge/backups/` and builds a new one with one
  safe sync that copies no deletions or completions. Nothing is deleted on
  either side. Items that were synced before are matched again by their notes
  footer or by title and date; with a new Google account, your reminders are
  copied into it and its existing tasks are imported into Reminders.
- **In Terminal:** `ltb rebuild --dry-run` shows what a rebuild would do and
  `ltb rebuild --yes` performs it, with the same safeguards — a backup first,
  the background loop and the sync lock held while the map is replaced, and no
  deletions. `ltb manage reconnect` does the same interactively.
- Signing in again to the **same** Google account never needs this: 1.0 binds
  the map to the account ID, not to a particular sign-in. Maps created by
  earlier versions are upgraded automatically on the first sync.

## Bulk changes waiting for approval

A plan that would delete or complete **more than 25 items**, or **more than
25 %** of the items the bridge manages, needs your approval. The background
sync holds only those deletions and completions; creates and edits keep
syncing. Once the same set shows up on two cycles in a row, the app opens its
**Review Pending Changes** window, which lists the held changes by kind and
list.

- **Apply N Changes** carries out exactly that set. If the set changed in the
  meantime, nothing is applied and the window shows the new plan.
- **Keep On Hold** keeps the set waiting. The bridge doesn't ask again for 6
  hours, and everything else keeps syncing.
- If you close the window without answering, the question comes back after 12
  hours; **Review Pending Changes…** in the menu reopens it at any time.
- If the planned deletions go away — for example because you restored the
  items — the question is dropped.

When the engine runs without the app — for example `ltb run-loop` in Terminal —
it asks with a macOS dialog instead, whose buttons are **Apply** and **Hold**
(the default).

You can review the set at any time: **Review Pending Changes…** in the menu, or
in Terminal:

```bash
ltb approvals show                  # what is held, with titles
ltb approvals apply <fingerprint>   # apply exactly this set
ltb approvals hold <fingerprint>    # keep holding it
```

Common reasons, and whether to apply:

- You completed or deleted many items on purpose → **Apply**.
- All items of a list were deleted in Reminders or Google → apply only if you
  meant it.
- Reminders or iCloud returned incomplete data after a restart or an account
  problem → **Hold** and wait; the plan usually disappears by itself.

The limits can be changed with `max_destructive_changes` and
`max_destructive_ratio` ([configuration](configuration.md#settings-reference)).

## Renaming, moving and unselecting lists

Lists are paired by exact name. Changing which lists are synced never counts as
deleting: the bridge completes or deletes only items of lists that are still
selected and still paired with the same Google list, and leaves the items of
every other list alone. A list that is new to the sync map — on the first sync,
after a rebuild, or when you select it — syncs one cycle without completions
or deletions.

- **Unselecting a list** stops syncing it. Its reminders and its Google tasks
  stay as they are; select it again later and syncing continues where it left
  off.
- **Renaming a synced list:** rename it on **both** sides to the same new name,
  then update the selection in **Settings… → Lists**; the bridge keeps all
  links. A list renamed on one side only is treated as a new list: the bridge
  creates a list with the new name on the other side and copies the items into
  it, while the old list there is left alone. Delete whichever copy you don't
  want — the deletion syncs.
- **Deleting a synced list:** deleting it in Reminders leaves the Google list
  and its tasks alone. Deleting it in Google while it is still selected on the
  Mac makes the bridge create it again from Reminders; unselect it first if you
  want it gone.
- **Moving an item to another list:** do it in Reminders. The bridge moves the
  Google copy by deleting it in the old list and creating it in the new one
  (the deletion counts toward the safety limits). A move made in Google Tasks
  isn't understood: the item seems to vanish from one list and turn up in
  another with someone else's footer, and it may be moved back or removed.

## Conflicts

A conflict is an item that changed on both sides between two cycles.

- With `newer_wins` (the default), the more recently modified version wins as a
  whole — title, notes, date and completion. Nothing for you to do.
- With `skip`, the item is left alone on both sides and the cycle is reported as
  **failed** (“Bidirectional conflicts left Apple Reminders and Google Tasks
  unsynced”), while other items keep syncing and the sync map is saved. Edit the item on one side so both
  sides match, or switch the list to `newer_wins`.
- If you edit a reminder on the Mac after its Google task was deleted, the task
  is created again in Google only if your edit is newer than the deletion, or
  the list doesn't sync deletions; otherwise the deletion wins. While deletions
  are held — on a list's first sync, during a safe sync, or while a plan waits
  for approval — nothing is recreated or deleted: the pending deletion simply
  stays pending.

## Network and proxy

Symptoms: *Google can't be reached right now*, exit code 9 (`network`), or
timeouts and TLS errors in the log.

- Check that the Mac is online and that <https://tasks.google.com> opens in a
  browser.
- **Mainland China:** Google isn't reachable directly. Run a proxy client
  (Clash, ClashX, Clash Verge and so on) and enter its local HTTP or “mixed”
  port — on the setup assistant's sign-in step under **Network settings
  (proxy)**, before you sign in, or later in **Settings… → Network** — for
  example `http://127.0.0.1:7890` (Clash and ClashX)
  or `http://127.0.0.1:7897` (Clash Verge Rev):

  ```bash
  echo '{"proxy": "http://127.0.0.1:7890"}' | ltb config merge --json
  ```

  Then check with `ltb account`. A client running in TUN / enhanced mode needs
  no setting.
- **The one-line installer can't download:** curl doesn't use the macOS system
  proxy. Point it at your proxy app first (use its port):

  ```bash
  export https_proxy=http://127.0.0.1:7890
  curl -fsSL https://raw.githubusercontent.com/siyuanj/local-tasks-bridge/main/install.sh | bash
  ```

  The installer prints the same hint when a download fails.
- **The browser works but sync fails:** background processes don't always pick
  up the same proxy as your browser. Set the proxy explicitly as above.
- **A proxy is configured but you're on a network without it:** set the proxy
  to `none`, or back to the system default `""`.
- Only HTTP(S) proxy addresses are supported; for a SOCKS-only client use its
  HTTP or mixed port.

Transient read failures — dropped connections, timeouts, HTTP 429 and 5xx —
get up to 3 attempts. A failed write is not repeated
blindly — except for completing a task, which is retried only after Google
confirms the task is still open — so a network hiccup can't create
duplicates. The next cycle catches up.

## Duplicates

- **Duplicate Google tasks for the same reminder** (same footer) are removed
  automatically; the cleanup counts toward the safety limits.
- **Two items with the same title are fine.** Items are matched by their
  identity, not their title; title-based matching is only a fallback for unique
  titles.
- **A Google task and a reminder that describe the same thing but became two
  items:** when existing Google tasks are imported, they are linked to an active
  reminder only if title and due date are identical; otherwise a second
  reminder is created. Delete one copy; the deletion syncs.
- **A list renamed on one side** gives you a second copy of its items in a new
  list on the other side ([why](#renaming-moving-and-unselecting-lists)).
  Delete the copy you don't want.
- **Many duplicates at once:** usually two sync tools at work on the same lists
  — another sync app, an old installation that is still running (see
  [migration.md](migration.md)), or Local Tasks Bridge on a second Mac
  ([why that doesn't work](#can-i-run-it-on-two-macs)). Stop the other one,
  then delete the copies.

## The notes footer

Every synced Google task carries a few lines at the end of its notes:

```text
Synced from Apple Reminders.
List: My Tasks
Source UID: 9f2c41…
Source Digest: 7a1e05…
```

The **Source UID** identifies the reminder, the **Source Digest** fingerprints
its synced content, and the **List** line is informational. The footer is
always in English and is never copied into Reminders — notes you write above it
sync normally.

Please don't delete or edit these lines. If a footer goes missing, the bridge
usually restores it from its sync map; if you also change the title at the
same time, it can no longer tell that the task is the same, and you may end up
with a duplicate. The footer stays in Google after you uninstall; you can
delete it then.

## Times of day

Google Tasks stores a due **date** only. A reminder due on Tuesday at 15:00
appears in Google as due on Tuesday; the time stays in Reminders. Editing the
task in Google keeps that time: if the date is unchanged, the time is
untouched, and if you change the date in Google, the reminder moves to the new
date at the same time. A due date you clear in Google is cleared on the Mac
too. Alerts set in Reminders are not touched by the bridge.

## Repeating reminders

Google Tasks has no repeat rules in its API. A repeating reminder appears in
Google as a single task for its current occurrence; the rule stays in
Reminders, which remains the source of truth. When the reminder moves on to its
next occurrence in Reminders, the Google task's due date follows. Repeating
tasks created in Google arrive on the Mac as one-off reminders. Repeating
reminders have not been part of the real-account acceptance tests yet:
complete them in Reminders rather than in Google, and check the first few
occurrences.

## Subtasks

Subtasks are not mapped. The parent–child structure isn't copied in either
direction; a subtask may appear on the other side as an ordinary, top-level
item. Avoid relying on subtasks in synced lists.

## Reminders due far in the future

There is no time window: dated reminders are synced however far ahead they are
due. (The engine's `lookahead_days` setting applies only to the inherited
Google Calendar mode.)

## How fast do changes sync?

| Change | When it reaches the other side |
| --- | --- |
| Made in Reminders on this Mac | Usually within seconds — the app starts a cycle as soon as Reminders reports a change (at most one extra cycle every 10 seconds, or every 30 seconds with the shared client) |
| Made on iPhone, iPad or Watch | As soon as iCloud has delivered it to this Mac, then within seconds |
| Made in Google (Tasks, Gmail, Calendar, Gemini) | With the next scheduled cycle: within about 1 minute (own client) or 5 minutes (shared client) |
| Made while the Mac sleeps or is logged out | After the Mac wakes and you are logged in |

A cycle itself takes a few seconds — longer through a slow proxy or with many
items. **Sync Now** starts one immediately.

## Logs and diagnostics

| File | Contents |
| --- | --- |
| `~/Library/Logs/LocalTasksBridge/engine.log` | What each cycle did, **with task titles** |
| `~/Library/Logs/LocalTasksBridge/app.log` | The app and launchd |
| `~/.config/local-tasks-bridge/status.json` | The last result: state, times, counts and hashes, never titles |

Open them with **Open Logs** or **Open Data Folder** in the menu, or with the
Console app. The engine log is rotated when it grows past about 5 MB.

To ask for help, share something that leaves your data out:

- **Copy Diagnostics** in the menu copies a report without titles or tokens.
- `ltb doctor` (or `ltb doctor --json`) shows the checks and the last result
  without stored error texts or paths.

Read what you share before posting it. Never post the logs, `token.json`,
`credentials.json`, `state.json`, or the output of `ltb export` or
`ltb approvals show`. Report bugs with the issue template, and security
problems privately as described in [SECURITY.md](../SECURITY.md).

## Complete reset

This removes Local Tasks Bridge and everything it stored on this Mac. Your
reminders and Google tasks stay.

1. Quit the app (menu → **Quit Local Tasks Bridge**).
2. Remove the login item, revoke the sign-in and delete the data:

   ```bash
   ltb uninstall --revoke --delete-data --yes
   ```

   It removes only Local Tasks Bridge's own files (and the folder, once it is
   empty) and tells you if the Google revocation failed. Or by hand:

   ```bash
   launchctl bootout gui/$(id -u)/io.github.siyuanj.local-tasks-bridge
   rm -f ~/Library/LaunchAgents/io.github.siyuanj.local-tasks-bridge.plist
   rm -rf ~/.config/local-tasks-bridge ~/Library/Logs/LocalTasksBridge
   ```

   Deleting `~/.config/local-tasks-bridge` also deletes your imported Google
   client (`credentials.json`); keep a copy if you want to reuse it.
3. Reset the Reminders permission:
   `tccutil reset Reminders io.github.siyuanj.LocalTasksBridge`
4. Move the app to the Trash and delete `~/.local/bin/ltb`.
5. If you didn't use `--revoke`, remove the access at
   <https://myaccount.google.com/permissions>.

If you install again later on the same Mac, the first sync usually finds the
items it synced before by their notes footer, so it doesn't create
duplicates.

## FAQ

### Does the maintainer see my tasks?

No. The bridge talks only to Apple Reminders on your Mac and to Google. There is
no server run by the maintainer, no analytics and no telemetry. With the shared
client, Google knows that you authorized the maintainer's “Local Tasks Bridge”
client, and the maintainer can see aggregate numbers in Google Cloud such as
the user count and API request counts — but not your identity or your tasks.
Details in [PRIVACY.md](../PRIVACY.md).

### Can I run it on two Macs?

Please run it on **one** Mac per set of accounts. Each installation keeps its
own sync map, and the identifiers it uses to recognize reminders are specific
to the Mac, so a second Mac syncing the same lists would create duplicates.
Your other Apple devices still see every change through iCloud.

### Does it sync while my Mac is asleep?

No. It runs in your logged-in session. Changes made elsewhere in the meantime
are synced after the Mac wakes. A Mac that is always on — even an old one —
works well as the bridge.

### Can I sync only one way?

Yes, per list: set `direction` to `apple_to_google` or `google_to_apple` in
[`list_policies`](configuration.md#per-list-policies). You can also stop
completions and deletions from being copied for a list with
`delete_propagation: false`.

### Can I use several Google accounts?

One Google account per Mac user account. The sync map is bound to it.

### Why are completed Google tasks not in Reminders?

When existing Google tasks are imported, completed ones are skipped so that
years of history don't flood Reminders. Tasks completed after they were synced
stay linked and completed on both sides.

### Does uninstalling delete my tasks?

No. Uninstalling removes the app, its login item and, if you ask, its local
data. Reminders and Google tasks stay as they are, including the footer lines
in Google task notes.

### Is it free?

Yes. Local Tasks Bridge is open source under the MIT License. Google doesn't
charge for the Tasks API, and creating your own Google Cloud project needs no
billing account.
