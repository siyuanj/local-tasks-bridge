# Configuration and command-line reference

**English** · [简体中文](configuration.zh-CN.md)

Most people never need this page: the setup assistant and **Settings** in the
app cover everyday choices. This is the reference for the settings file, the
per-list policies, the proxy, the sync interval and every `ltb` command.

The technical interface between the app and the engine is specified in
[app-engine-contract.md](app-engine-contract.md).

## File locations

| Path | What it is | Permissions |
| --- | --- | --- |
| `~/.config/local-tasks-bridge/` | Settings and private data folder | `0700` (only you) |
| `…/config.json` | Settings (this page) | `0600` |
| `…/credentials.json` | Your own Google OAuth client, if you imported one | `0600` |
| `…/token.json` | Google sign-in (OAuth tokens) | `0600` |
| `…/state.json` | Sync map: which reminder belongs to which Google task, change fingerprints, account binding hashes, item titles | `0600` |
| `…/status.json` | Result of the last cycle, counts and hashes — never titles | `0600` |
| `…/paused` | Present while sync is paused | `0600` |
| `…/sync-now` | Touched to request an immediate cycle | `0600` |
| `…/backups/` | Private backups made before risky operations | `0700` |
| `~/Library/Logs/LocalTasksBridge/engine.log` | Engine log; **contains task titles** | `0600`, folder `0700` |
| `~/Library/Logs/LocalTasksBridge/app.log` | App and launchd output | `0600` |
| `~/Library/LaunchAgents/io.github.siyuanj.local-tasks-bridge.plist` | Login item that starts the app | `0644` |
| `~/Applications/Local Tasks Bridge.app` | The app (default location; `/Applications` also works) | |
| `~/.local/bin/ltb` | Optional link to the `ltb` command inside the app | link |

Never share `credentials.json`, `token.json`, `state.json` or the logs.

## Changing settings

- **In the app:** **Settings…** in the menu, with the tabs General, Lists,
  Safety, Google, Network and Advanced. Changes take effect when you click
  **Apply**.
- **On the command line:**

  ```bash
  ltb config show                                    # the current user-facing settings
  echo '{"sync_interval_seconds": 300}' | ltb config merge --json
  ```

  `config merge` reads a JSON object from standard input, validates the whole
  result, writes it atomically with mode `0600` and prints the new settings.
  Unknown keys and invalid values are rejected with `config_invalid` and
  nothing is written.
- **By hand:** you can edit `config.json` with a text editor, which is the only
  way to change the [advanced keys](#advanced-keys). Make a copy first, keep it
  valid JSON, and quit and reopen the app afterwards so that background sync
  reloads the file. An invalid file stops syncing until it is fixed.

`ltb config init` writes the product defaults when no `config.json` exists;
`ltb config init --force` replaces an existing file after making a backup.

## Settings reference

These are the keys `ltb config show` displays and `ltb config merge` accepts.
“Default” is what the setup assistant and `config init` write. If a key is
missing from the file, the engine falls back to the value in the last column,
which is sometimes more conservative — keep the keys that setup wrote.

| Key | Values | Default | Meaning | If missing |
| --- | --- | --- | --- | --- |
| `include_lists` | array of Reminders list names | your selection | The Reminders lists to sync. Names must match exactly. **An empty array means every Reminders list.** Removing a list only stops syncing it; nothing is deleted. | `[]` |
| `list_policies` | object | `{}` | Per-list overrides, see [below](#per-list-policies) | `{}` |
| `bidirectional` | `true` / `false` | `true` | Two-way sync for lists without their own `direction`; `false` means Reminders → Google only | `false` |
| `delete_stale` | `true` / `false` | `true` | Copy completions and deletions to the other side (the default for each list's `delete_propagation`) | `true` |
| `conflict_policy` | `newer_wins` / `skip` | `newer_wins` | What to do when an item changed on both sides, see [Conflicts](#conflicts) | `newer_wins` |
| `tasks_sync_undated` | `true` / `false` | `true` | Also sync reminders and tasks without a due date | `false` |
| `tasks_import_unsynced` | `true` / `false` | `true` | Import Google tasks that aren't linked to a reminder yet (no footer), see [Importing](#importing-existing-google-tasks) | `false` |
| `tasks_create_missing_lists` | `true` / `false` | `true` | Create a Google list when a selected Reminders list has no Google list of the same name; if `false`, such a list stops the cycle with an error | `true` |
| `tasks_complete_stale` | `true` / `false` | `true` | When you complete a reminder, complete its Google task. If `false`, a completed reminder counts as removed, so its Google task is **deleted** (when deletions propagate) | `true` |
| `sync_interval_seconds` | integer ≥ 60 | `60` | Seconds from the start of one scheduled cycle to the start of the next. With the shared client the engine waits at least 300 s (5 minutes), whatever this says | `900` |
| `trigger_min_interval_seconds` | integer ≥ 0 | not written | Minimum seconds between the start of a cycle and an extra cycle triggered by a Reminders change, **Sync Now** or `ltb sync-now`; at least 30 with the shared client | `10` |
| `max_destructive_changes` | integer ≥ 0 | `25` | A plan with **more than** this many deletions and completions needs your approval; `0` asks for every one | `25` |
| `max_destructive_ratio` | number 0–1 | `0.25` | A plan whose deletions and completions are **more than** this share of the managed items needs approval; `1` turns the ratio check off | `0.25` |
| `mutation_approval_prompt` | `true` / `false` | `true` | Ask about held changes — in the app's **Review Pending Changes** window, or with a dialog when the engine runs without the app; if `false`, you only get a notification and review them with **Review Pending Changes…** or `ltb approvals` | `true` |
| `macos_notifications` | `true` / `false` | `true` | Show macOS notifications about problems and held changes | `true` |
| `language` | `auto` / `en` / `zh` | `auto` | Language of engine messages, notifications and `ltb` output; `auto` follows macOS | `auto` |
| `proxy` | `""` / `"none"` / `"http://host:port"` | `""` | How to reach Google, see [Proxy](#proxy) | `""` |
| `oauth_client` | `auto` / `custom` / `bundled` | `auto` | Which Google client to sign in with: `custom` = yours (`credentials.json`), `bundled` = the shared one, `auto` = yours if imported, otherwise the shared one | `auto` |
| `setup_completed_at` | timestamp or `null` | set by the assistant | When setup finished; `ltb status` reports `setup_completed` | — |

`config_version` (currently `2`) is written by setup and identifies the file
format.

### Conflicts

A conflict is an item that changed on both sides between two cycles.

- `newer_wins` (default): the side modified more recently wins as a whole —
  title, notes, date and completion. One special case protects your dates: when
  a newer Google change has no due date while a date was just added in
  Reminders, the date is kept.
- `skip`: the item is left untouched on both sides and the cycle is reported as
  failed (“Bidirectional conflicts left Apple Reminders and Google Tasks
  unsynced”) until you make both sides match by editing one of them or switch
  to `newer_wins`. Other items are still synced, and the sync map is saved first.

One-way lists don't have conflicts: their source side always wins.

### Importing existing Google tasks

With `tasks_import_unsynced` on, a Google task without the footer in a list
that syncs Google → Mac is handled like this:

- If an active reminder in the paired list has the same title and due date, the
  two are linked and the footer is added to the Google task.
- Otherwise a new reminder is created in the paired Reminders list and the
  Google task gets the footer.
- Completed Google tasks are not imported, so your Google history doesn't flood
  Reminders. Tasks without a due date are imported only if undated items are
  synced for that list.

## Per-list policies

`list_policies` overrides the global choices for individual lists. The key is
the Reminders list name, exactly as shown in Reminders; fields you leave out
inherit the global values.

```json
{
  "bidirectional": true,
  "delete_stale": true,
  "tasks_sync_undated": true,
  "conflict_policy": "newer_wins",
  "list_policies": {
    "Work": {
      "direction": "bidirectional",
      "delete_propagation": true,
      "sync_undated": true,
      "conflict_policy": "newer_wins"
    },
    "Archive": {
      "direction": "apple_to_google",
      "delete_propagation": false,
      "sync_undated": false
    },
    "My Tasks": {
      "direction": "google_to_apple",
      "conflict_policy": "skip"
    }
  }
}
```

| Field | Values | Inherits from | Meaning |
| --- | --- | --- | --- |
| `direction` | `bidirectional`, `apple_to_google`, `google_to_apple` | `bidirectional` (`true` → `bidirectional`, `false` → `apple_to_google`) | Which way changes flow. In a one-way list the source side is authoritative. |
| `delete_propagation` | `true` / `false` | `delete_stale` | Copy completions and deletions for this list, in the directions it syncs. Cleaning up duplicate Google tasks follows this setting too. |
| `sync_undated` | `true` / `false` | `tasks_sync_undated` | Include items without a due date: export undated reminders and import undated Google tasks. |
| `conflict_policy` | `newer_wins`, `skip` | `conflict_policy` | Only matters for `bidirectional` lists. |

Rules:

- A listed name must also be in `include_lists` to be synced at all.
- Unknown fields, unknown values and booleans written as strings (`"true"`)
  are configuration errors: the engine stops before signing in or writing
  anything.
- A `google_to_apple` list whose Google list doesn't exist is skipped instead
  of creating an empty Google list.
- `ltb sync --no-delete-stale` switches off completions and deletions for every
  list, whatever `delete_propagation` says.

## Advanced keys

The engine understands more keys than `config merge` accepts. You only need
them in special cases; edit `config.json` by hand (see
[Changing settings](#changing-settings)). Values in parentheses are the
defaults.

**Safety and approvals**

- `destructive_approval_ttl_seconds` (`600`, minimum `60`) — how long an
  approval stays valid after you click **Apply**.
- `mutation_approval_prompt_repeat_seconds` (`21600` = 6 hours, minimum `600`)
  — after **Hold**, how long the bridge waits before asking again.
- `auto_approve_destructive_loops` (`0`) — if greater than 0, a held plan is
  applied automatically after it showed up that many cycles in a row. Leave it
  at `0`; this exists for unattended test setups.
- `allow_empty_source_delete` (`false`) — allow deletions even when every
  selected Reminders list comes back empty. Leave it off: an empty result is
  more often a temporary Reminders or iCloud problem than a real cleanup.
- `verify_title_due_after_sync` (`true`), `verify_title_due_retry_attempts`
  (`3`), `verify_title_due_retry_delay_seconds` (`2.0`) — re-read Google after
  writing and check every title and due date; the cycle fails if they still
  differ after the retries.

**What is synced**

- `lookahead_days` (`365`) — used only by the inherited Google Calendar mode.
  In Google Tasks mode every dated reminder is synced, however far ahead it is
  due.
- `tasks_mirror_lists` (`true`) — pair lists by name. Setting it to `false`
  sends all selected lists into one Google list (`tasks_list_id` or
  `tasks_list_title`, otherwise the first Google list); the app does not
  support this inherited mode.
- `tasks_mirror_empty_lists` (`true`) — pair and create Google lists even for
  empty Reminders lists.

**Sign-in**

- `manual_oauth_browser` (`false`) — print the sign-in address instead of
  opening the browser (the same as `ltb auth --no-browser`).
- `auto_reauth_browser` (`false`) and `auto_reauth_min_interval_seconds`
  (`21600`), `auto_reauth_timeout_seconds` (`300`),
  `auto_reauth_timeout_retry_interval_seconds` (`300`) — let the background
  engine open a browser sign-in by itself when the sign-in expires, with
  exponential back-off. Off in the product: the app asks you instead.
- `use_adc`, `adc_credentials_path` — sign in through gcloud Application
  Default Credentials (`ltb gcloud-login`). Legacy upstream method, not
  supported by the app.

**Notifications**

- `notify_success_min_interval_seconds` (`3600`) and
  `notify_failure_min_interval_seconds` (`300`) — minimum time between
  “synced” and “needs attention” notifications.

**Paths and helpers**

- `credentials_path`, `token_path`, `state_path`, `status_path` — default to
  files next to `config.json`.
- `reminders_exporter_path`, `reminders_apply_path` (empty) — empty means the
  helpers shipped with the app (`Contents/MacOS`), then `build/helpers/` in a
  source checkout, then the Swift sources in `macos/Helpers/` run with
  `swift`.
- `reminders_source` (`eventkit`) — `eventkit` reads Reminders through Apple's
  official framework. The inherited `sqlite` mode, which reads the Reminders
  database directly, and `auto` (EventKit with SQLite fallback) are not
  supported.

**Inherited Google Calendar mode**

`target_service` is `tasks`. The upstream project could also write reminders as
Google Calendar events (`target_service: "calendar"`, with `calendar_id`,
`default_duration_minutes`, `prefix_list`, `transparency` and
`google_popup_minutes`). The engine still contains that mode, but the app, the
shared client and this documentation cover Google Tasks only.

## Proxy

| `proxy` | Behavior |
| --- | --- |
| `""` (default) | Use the `HTTPS_PROXY` / `HTTP_PROXY` environment variables if set, otherwise the macOS system proxy (System Settings → Network → your connection → Details → Proxies) |
| `"none"` | Always connect directly, ignoring system and environment proxies |
| `"http://host:port"` | Send every Google request through this HTTP proxy, for example `http://127.0.0.1:7890` |

Notes:

- Only `http://` and `https://` proxy addresses are accepted. For a SOCKS-only
  client, use its HTTP or “mixed” port.
- Background processes don't always see the same proxy as your browser. If
  sync fails with network errors while websites load fine, set the proxy
  explicitly.
- **Mainland China:** Google is not reachable directly. Run a proxy client and
  set its local HTTP port, for example:

  ```bash
  echo '{"proxy": "http://127.0.0.1:7890"}' | ltb config merge --json
  ```

  Clash and ClashX use port `7890` by default, Clash Verge Rev `7897`; check
  your client's settings for the actual “HTTP” or “mixed” port. A client in
  TUN / enhanced mode routes all traffic itself, so `""` works too. The
  browser used for Google sign-in needs a working route to Google as well.

## Sync interval and Google quota

Scheduled cycles start every `sync_interval_seconds` (minimum 60), measured from
the start of one cycle to the start of the next; if a cycle runs longer than
the interval, the next one starts right away. Local Reminders changes trigger
extra cycles, at most one every `trigger_min_interval_seconds` (10 s).

**With the shared client** the engine enforces gentler timing, because all its
users share one Google quota: scheduled cycles at least 5 minutes apart and
triggered cycles at least 30 seconds apart, whatever the settings say. It
re-checks this on every cycle, so switching the sign-in method takes effect
right away. Local edits still reach Google within seconds.

Google Tasks API requests per cycle, for N synced lists:

- **Nothing changed:** about **1 + N** — one request for your task lists and
  one read per list. The verification re-read is skipped because nothing was
  written.
- **Something was written:** about **1 + 2 × N** plus one request per change —
  the extra read per list verifies titles and due dates.
- A list holding more than 100 tasks, counting completed and recently deleted
  ones, needs one more request per 100 tasks for each read.

Idle cycles alone come to:

| Interval | 1 list | 3 lists |
| --- | --- | --- |
| 1 minute (own client default) | ≈ 2,900 requests/day | ≈ 5,800 requests/day |
| 5 minutes (shared client) | ≈ 580 requests/day | ≈ 1,150 requests/day |

Each burst of local edits adds a cycle with writes. Your own client has 50,000
requests per day to itself, so 1 minute is comfortable. With the shared client
every user's requests count against one 50,000-per-day quota for everyone
together.

## Command-line reference

`ltb` is a small wrapper inside the app
(`Local Tasks Bridge.app/Contents/Resources/bin/ltb`) that finds a suitable
Python and runs the engine with your config file. In a source checkout you can
run the engine directly:

```bash
python3 -B engine/local_tasks_bridge.py --config ~/.config/local-tasks-bridge/config.json status
```

Two global options go before the command: `--language auto|en|zh` sets the
message language for this run (`ltb --language zh status`), and `--version`
prints the version.

Commands that read or write Reminders (`lists`, `sync`, `approvals show`,
`approvals apply`, `export`, `manage`) depend on macOS Reminders access for the
app that started them; in Terminal, that is Terminal itself.

### Machine-readable output

With `--json`, a command prints exactly one JSON object on standard output
after all other work; progress goes to standard error. Success is
`{"ok": true, …}` with exit code 0; failures look like
`{"ok": false, "error": {"code": "…", "message": "…"}}` with one of these exit
codes:

| Exit | `error.code` | Meaning |
| --- | --- | --- |
| 1 | `failed` | Unexpected failure; details in the log |
| 2 | — | Command-line usage error |
| 3 | `auth_required` | Google sign-in missing, expired or revoked |
| 4 | `account_binding_required` | The Apple or Google account differs from the one the sync map belongs to |
| 5 | `approval_required` | The plan exceeds the deletion/completion safety limits |
| 6 | `reminders_unavailable` | Reminders couldn't be read or written (usually permission) |
| 7 | `config_invalid` | The config file or a merged setting is invalid |
| 8 | `oauth_client_missing` | No usable Google client (neither your own nor a shared one) |
| 9 | `network` | Google is unreachable; try again later |
| 10 | `plan_changed` | An approval no longer matches the current plan |

Timestamps are ISO 8601 in UTC. Messages follow `language` / `LTB_LANG`.

### Information

**`ltb version [--json]`** — engine version, Python version and engine path.

**`ltb status [--json]`** — the current condition, a headline, the recommended
action, the last success, failure count, pending held changes, sign-in and
client state, selected lists, interval and login-item state. Reads local files
only: no network, no Reminders access, instant. The `condition` is one of
`setup_required`, `auth_required`, `account_binding_required`,
`mutation_approval_pending`, `mutation_blocked`, `paused`, `running`, `failed`,
`never_synced`, `status_unreadable`, `agent_stopped`, `attention`, `healthy`,
`unknown` (see [Troubleshooting](troubleshooting.md#status-conditions)).
`loop_running` tells whether a background sync loop is running.

**`ltb lists [--google] [--json]`** — all Reminders lists with their account
(ignores `include_lists`). With `--google`, also your Google task lists (needs
network and sign-in).

**`ltb doctor [--online] [--json]`** — checks configuration, helpers, sign-in
files, login item and the last result, and prints one next step. Local and
read-only by default; stored error texts and paths are not shown, so the output
is safe to share. `--online` also refreshes the Google sign-in and calls the
Tasks API.

### Settings

**`ltb config show [--json]`**, **`ltb config merge --json`**,
**`ltb config init [--force] [--json]`** — see [Changing settings](#changing-settings).
**`ltb config validate [--json]`** checks `config.json` without changing it.

### Google sign-in

**`ltb client import <path> [--json]`** — validate a Google OAuth client JSON of
type **Desktop app**, copy it to `credentials.json` and select it
(`oauth_client: "custom"`). Web clients are refused with an explanation. Prints
a client ID hint.

```bash
ltb client import ~/Downloads/client_secret_*.apps.googleusercontent.com.json
```

**`ltb client status [--json]`** — which client is active (`custom`, `bundled`
or `missing`), whether your own client is present and whether this build has a
shared client.

**`ltb auth [--no-browser] [--json]`** — sign in to Google (PKCE with a loopback
redirect on `127.0.0.1`). Opens your default browser, or with `--no-browser`
prints the address to open. Waits up to 5 minutes.

**`ltb account [--json]`** — refresh the sign-in and prove the Tasks API works;
prints the account e-mail and the number of task lists.

**`ltb signout [--revoke] [--json]`** — delete `token.json` (after a private
backup); with `--revoke`, ask Google to revoke the token first. The sync map is
kept: signing in again to the same Google account continues where it left off.

### Syncing

**`ltb sync [--dry-run] [--no-delete-stale] [--json]`** — run one sync in the
foreground. `--dry-run` computes and prints the plan without changing anything.
`--no-delete-stale` copies no completions or deletions in either direction —
the setup assistant uses it for the first sync. If the plan exceeds the safety
limits, nothing is written and the command exits with code 5.

```bash
ltb sync --dry-run                    # what would happen?
ltb sync --dry-run --no-delete-stale  # the same, without completions and deletions
ltb sync                              # do it
```

The JSON result contains `summary` counts (`apple_exported`, `google_lists`,
`inserted`, `updated`, `unchanged`, `completed`, `deleted`,
`duplicate_deleted`, `google_applied`, `bidir_conflicts`, `skipped_invalid`)
and `plan` counts keyed `<target>.<operation>`, such as `google_tasks.create`,
`google_tasks.complete`, `google_tasks.delete`, `google_tasks.create_list`,
`apple_reminders.create`, `apple_reminders.complete` or
`apple_reminders.delete`.

**`ltb pause [--json]`**, **`ltb resume [--json]`** — create or remove the
`paused` file. While paused, scheduled and triggered cycles are skipped.

**`ltb sync-now [--json]`** — touch `sync-now`; the background loop starts a
cycle within about a second.

**`ltb run-loop [--log-file PATH] [--log-max-bytes N]`** — the background
scheduler itself. The app runs it for you; run it by hand only for testing.
Only one loop runs per config folder: a second one exits with status 1 while
another holds `run-loop.lock`. To stop a loop, send it SIGTERM (or press
Control-C) and give it up to 30 seconds — an idle loop exits at once, a loop in
the middle of a cycle finishes the cycle first so its state is never left
half-written. With `--log-file`, human-readable output goes to that private
log, rotated by size.

### Held changes

**`ltb approvals show [--json]`** — compute the next plan without writing
anything (needs network and Reminders access) and list the deletions and
completions waiting for approval: operation, list and title. Titles appear only
here, in the review window and in the dialog, never in `status.json` or the
logs.

**`ltb approvals apply <fingerprint> [--json]`** — perform exactly that set of
deletions and completions in one live sync. If the plan changed in the
meantime, nothing is applied and the command fails with `plan_changed`; look
again with `approvals show`.

**`ltb approvals hold <fingerprint> [--json]`** — record your decision to hold;
background sync keeps syncing everything else and asks again later.

```bash
ltb approvals show
ltb approvals apply 3b6f…e91c   # the 64-character destructive fingerprint shown above
```

### Recovery

**`ltb manage [ACTION] [--yes]`** — an interactive menu in Terminal. You can
also name the action directly:

| Action | What it does |
| --- | --- |
| `status` | Show the status (read-only) |
| `check` | Check the Google connection online (may refresh the sign-in) |
| `reconnect` | Reconnect Google safely: back up private files, pause background sync, verify the account, and — only after you confirm — rebuild the sync map without copying deletions or completions |
| `restart` | Restart background sync |
| `approve` | Review held deletions and completions in Terminal, then apply or hold them |

`--yes` answers every confirmation with yes; it exists for controlled testing.

**`ltb rebuild [--dry-run] [--yes] [--json]`** — the recovery for
`account_binding_required`, once you have confirmed that the Apple and Google
accounts now in use are the pair you want to sync. `--dry-run` shows what a
rebuild would do — computed against an empty sync map with completions and
deletions switched off — without writing anything. `--yes` holds the
background loop, backs up the private files, moves the old `state.json` into
the backup and runs one safe sync that builds a new map, all while holding the
sync lock. Nothing is deleted on either side. **Reconnect Google…** in the app
and `ltb manage reconnect` lead to the same result interactively.

**`ltb migrate [--from PATH] [--dry-run] [--force] [--yes] [--json]`** — import
an earlier installation, see [migration.md](migration.md).

### Login item and removal

**`ltb agent install --app <path-to-.app> [--json]`** — write and load the
login item (LaunchAgent `io.github.siyuanj.local-tasks-bridge`) that starts the
app at login; it is loaded only if it isn't already (`--no-load` only writes
it). **`ltb agent uninstall
[--bootout] [--json]`** deletes the login item, so the app no longer starts at
login. Run from Terminal, it also stops the running job; the app's own calls
(marked with `LTB_CALLER=app`) stop it only with `--bootout`.
**`ltb agent status [--json]`** reports `installed`, `loaded`, `label`, `plist`
and `program`. The app manages all of this for you.

**`ltb uninstall [--revoke] [--delete-data] --yes [--json]`** — remove the login
item and, when run from Terminal, stop the running job (which quits an app that
was started at login); `--revoke` also revokes the Google sign-in;
`--delete-data` also deletes `~/.config/local-tasks-bridge/` and the logs. It
doesn't delete the app: move it to the Trash yourself, or use the app's
**Uninstall…** (which runs this command and then moves the app to the Trash) or
the installer's `--uninstall` (which quits the app, runs this command and
removes the app and the `ltb` link).

### Other terminal commands

- `ltb export` — print the selected reminders as JSON (contains your data;
  don't share it).
- `ltb init-config` — write a raw engine template (prefer `ltb config init`).
- `ltb gcloud-login` — sign in through the gcloud CLI (advanced, legacy).
- `ltb doctor` without `--json` prints a readable report.

## Environment variables

| Variable | Effect |
| --- | --- |
| `LTB_LANG` | `en` or `zh`: language of engine messages when `language` is `auto`. The app sets it to match its own language. Otherwise `LC_ALL`, `LC_MESSAGES`, `LANG` and the macOS language are consulted. |
| `LTB_PYTHON` | Python interpreter to use (3.9 or newer); otherwise the app's embedded Python, then `/usr/bin/python3` (only if the Command Line Tools are installed), then Homebrew's `python3` |
| `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY` | Honored when `proxy` is `""` |
| `XDG_CONFIG_HOME` | Moves the config folder to `$XDG_CONFIG_HOME/local-tasks-bridge`. The app started at login doesn't see variables from your shell profile, so if you set this only in Terminal, `ltb` and the app use different folders. |
| `LTB_EVENT_STREAM`, `LTB_APP_BUNDLE`, `LTB_CALLER` | Set by the app for the engine it runs (`LTB_CALLER=app` marks the app's own calls); not for manual use |

For tests only — the app never sets these: `LTB_TASKS_API`,
`LTB_OAUTH_AUTH_URL`, `LTB_OAUTH_TOKEN_URL`, `LTB_OAUTH_USERINFO_URL`,
`LTB_OAUTH_REVOKE_URL` (each must be `https://…` or a loopback `http://` URL),
`LTB_REMINDERS_EXPORTER`, `LTB_REMINDERS_APPLY` (helper paths),
`LTB_BUNDLED_OAUTH_CLIENT` (path), `LTB_LAUNCH_AGENTS_DIR`, `LTB_NO_LAUNCHCTL=1`
and `LTB_LOG_DIR`. See [CONTRIBUTING.md](../CONTRIBUTING.md).
