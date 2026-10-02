# Changelog

All notable changes to Local Tasks Bridge are documented in this file. The
format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-10-01

The first release as **Local Tasks Bridge**, the maintained fork of
[syncweave-labs/reminders-task-bridge](https://github.com/syncweave-labs/reminders-task-bridge).

### Added

- **Menu bar app** `Local Tasks Bridge.app`, which owns the Reminders
  permission, supervises the sync engine, and shows status, notifications and
  held changes. It starts at login through the LaunchAgent
  `io.github.siyuanj.local-tasks-bridge`.
- **Setup assistant**: Reminders access, choice of sign-in method, Google
  sign-in, list selection (including creating a matching Reminders list for an
  existing Google list such as My Tasks), options, and a safe first sync — a
  dry run, then a sync without deletions or completions. Earlier installations
  are offered **Import My Existing Setup**.
- **English and Simplified Chinese** in the app, engine messages, `ltb`
  output, notifications, the approval dialog, the installer and the
  documentation (`language` setting, `LTB_LANG`).
- **Compiled EventKit helpers** (`ltb-reminders-export`,
  `ltb-reminders-apply`) inside the app, instead of interpreting the Swift
  sources with `swift` on every cycle.
- **Two Google sign-in methods**: the shared “Local Tasks Bridge” client
  embedded in release builds, or your own Google Cloud “Desktop app” client
  (`ltb client import`); Web clients are refused with an explanation
  (`oauth_client` setting).
- **Account binding by Google account ID** (OpenID subject): signing in again
  to the same account keeps the sync map, a different account stops the sync.
  Bindings from earlier versions are upgraded in place.
- **Proxy setting** (`proxy`): the system default, `none`, or an explicit HTTP
  proxy — for networks such as mainland China, where Google is reachable only
  through a proxy.
- **Instant sync of local edits**: the app starts a cycle as soon as Reminders
  reports a change (`sync-now`, `trigger_min_interval_seconds`).
- **Quota protection for the shared client**: while signed in through it, the
  engine polls Google at most every 5 minutes and spaces triggered syncs at
  least 30 seconds apart; local edits still upload within seconds. Cycles that
  wrote nothing skip the verification re-read.
- **Review Pending Changes** window: when the app hosts the engine, large
  batches of deletions and completions are reviewed there (**Apply N Changes**
  or **Keep On Hold**); without the app, the engine asks with an `osascript`
  dialog.
- **Reset Settings…** when `config.json` can't be read, and **Pair Accounts
  Again…** for account changes (with **Use a Different Google Account** when
  the change was a mistake).
- A proxy setting on the sign-in step of the setup assistant, so the proxy is
  in place before signing in.
- **Pause and resume** (`ltb pause`, `ltb resume`); the paused state survives
  restarts.
- **JSON command-line interface** for the app — `version`, `status`, `lists`,
  `config show|init|merge|validate`, `client import|status`, `auth`,
  `account`, `signout`, `sync`, `approvals show|apply|hold`, `pause`,
  `resume`, `sync-now`, `doctor --json`, `migrate`, `agent`, `uninstall` —
  with documented exit codes ([contract](docs/app-engine-contract.md)).
- **`ltb rebuild`**: recovery from *account binding required* after you
  confirm the account pair — it backs up, holds the background loop and the
  sync lock, and builds a new sync map without deleting anything.
- **The `ltb` command**, linked into `~/.local/bin` by the installer.
- **One-line installer** `install.sh`: installs and updates from GitHub
  releases with checksum verification, installs a downloaded zip (`--zip`) or
  a source build (`--from-source`), and uninstalls (`--uninstall`). It never
  uses `sudo`.
- **Release automation**: Apple silicon and Intel zips with an embedded
  Python, `SHA256SUMS` and a release manifest; prepared for Developer ID
  signing and notarization.
- **Simulated end-to-end tests**: the real engine CLI against a fake Google
  OAuth/Tasks server and fake Reminders helpers; hermetic installer tests.
- **Migration** from the 2026-09 private trial and from upstream installations
  (`ltb migrate`, **Import My Existing Setup**), keeping the Google sign-in and
  the sync map.
- **Check for Updates…**, **Copy Diagnostics**, **Open Logs** and
  **Open Data Folder** in the menu.
- Documentation in English and Chinese: README, Google Cloud setup,
  configuration and command-line reference, troubleshooting and FAQ,
  architecture, migration, releasing, roadmap and the privacy policy.

### Changed

- **Name and locations.** The product is now Local Tasks Bridge (formerly
  “iCloud Reminders ↔ Google Tasks Sync”, `icloud-reminders-google-sync`):
  bundle identifier `io.github.siyuanj.LocalTasksBridge`; LaunchAgent
  `io.github.siyuanj.local-tasks-bridge` (was
  `com.icloud-reminders-google-sync`); settings in
  `~/.config/local-tasks-bridge/` (was `~/.config/icloud-reminders-google-sync/`);
  logs in `~/Library/Logs/LocalTasksBridge/`; program files inside the app
  bundle (was `~/.local/share/icloud-reminders-google-sync/releases/…`).
- **Defaults for new setups**: two-way sync; completions and deletions within
  the safety limits (25 items / 25 %); reminders without a due date included;
  existing Google tasks imported; a 1-minute interval (5 minutes with the
  shared client); approval prompts on.
- Google sign-in requests only the Google Tasks scope plus `openid` and
  `email`; upstream also requested Google Calendar access.
- The Reminders write helper receives the same list boundary as the exporter,
  so reads and writes cover only the selected lists.
- Private files default to the folder that contains `config.json`.
- Repository layout: `engine/`, `macos/`, `tests/`, `scripts/`, `docs/`.
- The Chinese interface uses Apple's term 列表 for lists.

### Fixed

From the 2026-09 trial:

- A task completed in Google could be misread as a deletion in the same cycle
  and deleted; completed reminders are now re-read after inbound changes.
- Completing the last remaining item of a list now propagates, while the
  empty-source guard still blocks deletions.
- Completing a Google task after an unknown network outcome is retried only
  once a read confirms that the task is still open; other writes are never
  repeated blindly.
- Google Tasks reads are retried a bounded number of times after transient
  network errors, such as TLS failures through a local proxy.
- Scheduled cycles keep a fixed 60-second start-to-start cadence instead of
  waiting a full interval after each cycle (previously 66–104 s between
  starts).
- A sign-in that left the Google Tasks permission unticked is rejected
  immediately instead of failing on every cycle.
- A stray request to the loopback sign-in port, such as a browser's favicon
  request, no longer breaks the sign-in.

From the simulated end-to-end tests and reviews before release:

- Unselecting a list, renaming or removing a list on either side, or a Google
  list title that now points to a different list is never read as deletions;
  tasks of lists outside the sync are left alone. A list renamed on one side is
  treated as a new list.
- Reminders due more than 365 days ahead are synced and no longer look
  deleted; the lookahead window applies only to the inherited calendar mode.
- A Google edit keeps the reminder's time of day; a date changed in Google
  moves the reminder to the new date at the same time.
- A due date changed or cleared in Google is applied on the Mac instead of
  being reverted.
- Editing a reminder on the Mac after its Google task was deleted no longer
  loses the edit: if the edit is newer, the task is created again.
- `status.json` and notifications keep only the first line of an error, so
  titles stay in the private log.
- Reads get up to 3 attempts after dropped connections, timeouts, HTTP 429
  and 5xx.
- The sync map is saved before a conflict (with `conflict_policy: skip`) or a
  failed verification ends a cycle.
- A failed manual sync is recorded as failed instead of staying “running”, and
  a failed sync is reported before “background sync isn't running”.
- A refused consent or an unticked Tasks permission is reported as a sign-in
  error (exit code 3).
- Signing out stops using a migrated gcloud credential, and an empty success
  response from Google's revoke endpoint counts as revoked.
- `ltb uninstall` and `ltb agent uninstall` run from Terminal stop the running
  login item; the app marks its own calls with `LTB_CALLER=app`.
- A background loop hosted by the app stops when the app is gone.

From the second review round:

- A list with no entries in the sync map yet — first sync, rebuilt or lost map,
  newly selected list — syncs without deletions or completions on that cycle.
- A deleted Google task is recreated only when the reminder was edited after
  the deletion or the list doesn't sync deletions; while deletions are held,
  nothing is recreated or written.
- Pairing an existing Google task with a reminder keeps the Google notes on
  both sides.
- Pausing keeps the last sync state visible.
- `uninstall --delete-data` removes only the product's own files, works with
  an unreadable `config.json`, and reports a failed revocation.
- `migrate` moves legacy `/tmp` logs into the backup folder; `migrate --force`
  also backs up the replaced `config.json`.
- A network failure while refreshing the sign-in is reported as a network
  problem (exit code 9), not as “sign in again”.
- Write commands finish before honouring SIGTERM, and the app never cancels
  them; Quit waits. `config init --force` works on an unreadable config.
- The app refuses to turn on Start at login, import, finish setup or install
  the command-line tool while it runs from a temporary location.
- The installer updates an existing copy where it is, refuses a `--dest`
  ending in `.app`, and explains the `https_proxy` setting when a download
  fails.

### Removed

- The Korean user interface and documentation.
- The gcloud-based setup script `setup-new-mac.sh`; `ltb gcloud-login` remains
  as an advanced, legacy command.
- The migration bundle script `make-migration-bundle.sh`.
- The private trial scripts (`install-local-background.py`,
  `package-local-launcher.py`, `LocalBridgeLauncher.swift`,
  `trial_acceptance.py`) and the Finder manager
  `google-tasks-manager.command`, replaced by the app and `ltb manage`.

## Before the fork

The upstream project had no numbered releases. Its history is preserved in
this repository (`git log 3501800`):

- **2026-07-23 — initial open-source release** by Syncweave Labs:
  bidirectional sync between Apple Reminders and Google Tasks (plus a Google
  Calendar mode), a user LaunchAgent, mutation plans with fingerprints and
  destructive limits, account binding, `doctor` and a Terminal manager.
- **#1 (2026-07-26)** A refresh-token fallback that belongs to another
  credential no longer dead-ends the sync loop; a new sign-in is requested
  instead.
- **#2 (2026-07-26)** No browser sign-in is opened when the account binding
  would reject its result.
- **#4 (2026-07-28)** Apple due dates are preserved during conflicts when a
  newer Google change has no due date.
- **#5 (2026-07-28)** Tombstones are ignored for Google tasks that were
  recreated with the same identity.
- **#6 (2026-09-13)** Logs moved out of world-readable `/tmp` into a private
  folder; the Reminders check no longer leaves files in `/tmp`.
- **#7 (2026-09-23)** Restored reminders aren't deleted again by old
  tombstones, and repeated destructive plans stay blocked by default.
- **#8 (2026-09-29)** Large deletions are held and asked about in a dialog
  while everything else keeps syncing, instead of pausing the whole sync.

The fork starts from upstream commit `3501800` (#8).

[Unreleased]: https://github.com/siyuanj/local-tasks-bridge/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/siyuanj/local-tasks-bridge/releases/tag/v1.0.0
