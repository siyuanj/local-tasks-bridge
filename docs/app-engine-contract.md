# App ↔ engine contract

This document is the interface between the three parts of Local Tasks Bridge:

- **engine** — `engine/local_tasks_bridge.py`, a Python 3.9+ standard-library
  program that plans and performs synchronization and owns every private file;
- **Reminders helpers** — two small Swift command-line programs that read and
  write Apple Reminders through EventKit;
- **app** — `Local Tasks Bridge.app`, a native menu bar app that owns the
  Reminders privacy permission, supervises the engine, and provides setup,
  settings, status, and approval UI.

The app never edits sync state itself. It runs engine commands and reads their
JSON output. Anything a person can do in the app can also be done with the
`ltb` command-line tool, which runs the same engine.

## 1. Installed layout

```text
Local Tasks Bridge.app/Contents/
  Info.plist                     CFBundleIdentifier io.github.siyuanj.LocalTasksBridge
                                 CFBundleExecutable LocalTasksBridge, LSUIElement true,
                                 LSMinimumSystemVersion 13.0
  MacOS/LocalTasksBridge         menu bar app
  MacOS/ltb-reminders-export     compiled from macos/Helpers/RemindersExport.swift
  MacOS/ltb-reminders-apply      compiled from macos/Helpers/RemindersApply.swift
  Resources/engine/local_tasks_bridge.py
  Resources/bin/ltb              command-line wrapper (bash)
  Resources/python/              optional embedded CPython (python-build-standalone),
                                 entry point Resources/python/bin/python3
  Resources/oauth_client.json    optional shared Google OAuth client (release builds only)
  Resources/AppIcon.icns
  Resources/en.lproj/            Localizable.strings, InfoPlist.strings
  Resources/zh-Hans.lproj/       Localizable.strings, InfoPlist.strings
```

Per-user files:

| Path | Purpose | Mode |
| --- | --- | --- |
| `~/.config/local-tasks-bridge/` | config dir | 0700 |
| `…/config.json` | settings | 0600 |
| `…/credentials.json` | the user's own OAuth "Desktop app" client (optional) | 0600 |
| `…/token.json` | Google OAuth token | 0600 |
| `…/state.json` | sync map (task IDs, digests, account binding hashes) | 0600 |
| `…/status.json` | last result, counts, hashes; never titles | 0600 |
| `…/paused` | present while sync is paused | 0600 |
| `…/sync-now` | touched to request an immediate cycle | 0600 |
| `…/backups/` | private backups made before risky operations | 0700 |
| `~/Library/Logs/LocalTasksBridge/engine.log` | engine log (contains titles) | 0600, dir 0700 |
| `~/Library/Logs/LocalTasksBridge/app.log` | app and launchd output | 0600 |
| `~/Library/LaunchAgents/io.github.siyuanj.local-tasks-bridge.plist` | start at login | 0644 |
| `~/.local/bin/ltb` | optional symlink to `Resources/bin/ltb` | link |

Default install location is `~/Applications/Local Tasks Bridge.app` (no admin
rights needed). `/Applications` works too.

## 2. Finding Python

The app and `Resources/bin/ltb` choose the interpreter in this order and use
the first one that is executable and reports `sys.version_info >= (3, 9)`:

1. `$LTB_PYTHON`
2. `Contents/Resources/python/bin/python3` (embedded)
3. `/usr/bin/python3`, **only** if `xcode-select -p` exits 0 — otherwise
   running it would pop up the Command Line Tools installer
4. `/opt/homebrew/bin/python3`, then `/usr/local/bin/python3`

If none qualifies, the app shows a "Python is required" step that offers
`xcode-select --install` and links the docs.

Always run the engine as `python3 -B <engine> --config <config> <command> …`.

## 3. Environment the app sets for engine processes

| Variable | Value |
| --- | --- |
| `LTB_LANG` | `zh` when the app runs in Chinese (`Bundle.main.preferredLocalizations.first` starts with `zh`), else `en` |
| `LTB_EVENT_STREAM` | `stdout` — only for the long-running `run-loop` child |
| `LTB_APP_BUNDLE` | absolute path of the running `.app` |
| `PATH` | `/usr/bin:/bin:/usr/sbin:/sbin` |
| `PYTHONDONTWRITEBYTECODE` | `1` |
| `PYTHONUNBUFFERED` | `1` |

Proxy settings are part of `config.json` (`proxy`), not the environment.

Test-only overrides understood by the engine (the app never sets them):
`LTB_TASKS_API`, `LTB_OAUTH_AUTH_URL`, `LTB_OAUTH_TOKEN_URL`,
`LTB_OAUTH_USERINFO_URL`, `LTB_OAUTH_REVOKE_URL` (each must be `https://…` or
`http://127.0.0.1…`/`http://localhost…`), `LTB_REMINDERS_EXPORTER`,
`LTB_REMINDERS_APPLY` (helper paths), `LTB_BUNDLED_OAUTH_CLIENT` (path),
`LTB_LAUNCH_AGENTS_DIR` (where `agent install` writes), `LTB_NO_LAUNCHCTL=1`
(never call `launchctl`), `LTB_LOG_DIR` (log directory).

## 4. JSON conventions

Every command that accepts `--json` prints **exactly one JSON object** to
stdout, after all other work, and sends human-readable progress to stderr.

Success: `{"ok": true, ...}` with exit code 0.

Failure: `{"ok": false, "error": {"code": "<code>", "message": "<localized text>"}, ...}`
with a non-zero exit code:

| Exit | `error.code` | Meaning |
| --- | --- | --- |
| 1 | `failed` | unexpected failure; details in the log |
| 2 | — | command-line usage error (argparse) |
| 3 | `auth_required` | Google sign-in missing, expired, or revoked |
| 4 | `account_binding_required` | Apple or Google account differs from the one the sync map belongs to |
| 5 | `approval_required` | the plan exceeds the deletion/completion safety limits |
| 6 | `reminders_unavailable` | EventKit helper failed (usually Reminders permission) |
| 7 | `config_invalid` | config file or a merged setting is invalid |
| 8 | `oauth_client_missing` | no usable OAuth client (neither custom nor bundled) |
| 9 | `network` | Google unreachable; retry later |
| 10 | `plan_changed` | an approval no longer matches the current plan |

Timestamps are ISO 8601 strings in UTC (for example `2026-10-01T10:41:09+00:00`)
or `null`.

## 5. Commands

### `version --json`

```json
{"ok": true, "version": "1.0.0", "python": "3.13.15", "engine_path": "/…/local_tasks_bridge.py"}
```

### `status --json` (local only, fast, no network, no EventKit)

```json
{
  "ok": true,
  "version": "1.0.0",
  "config_path": "/Users/me/.config/local-tasks-bridge/config.json",
  "config_exists": true,
  "setup_completed": true,
  "condition": "healthy",
  "headline": "Apple Reminders and Google Tasks are in sync.",
  "action": "No action needed.",
  "state": "ok",
  "paused": false,
  "last_success_at": "2026-10-01T10:41:09+00:00",
  "last_start_at": "…", "last_end_at": "…", "updated_at": "…",
  "consecutive_failures": 0,
  "pending_destructive_counts": {"google_tasks.complete": 10},
  "oauth_client": {"mode": "auto", "active": "custom", "custom_ready": true, "bundled_available": false},
  "token_ready": true,
  "include_lists": ["My Tasks"],
  "sync_interval_seconds": 60,
  "loop_running": true,
  "agent": {"installed": true, "loaded": true, "label": "io.github.siyuanj.local-tasks-bridge"},
  "log_path": "/Users/me/Library/Logs/LocalTasksBridge/engine.log",
  "legacy_install_detected": false
}
```

`condition` is one of: `setup_required`, `auth_required`,
`account_binding_required`, `mutation_approval_pending`, `mutation_blocked`,
`paused`, `running`, `failed`, `never_synced`, `status_unreadable`,
`agent_stopped`, `attention` (checks passed but no full sync since),
`healthy`, `unknown`. `headline` and `action` are localized (`LTB_LANG`).
`setup_completed` is true when `config.json` contains `setup_completed_at`
(or a sync has succeeded before). `loop_running` is true while any `run-loop`
holds `run-loop.lock`; `agent.loaded` is `null` when `launchctl` is unavailable.

### `lists [--google] --json`

Reads **all** Reminders lists (ignores `include_lists`) through the export
helper. With `--google`, also reads Google task lists (network, sign-in needed).

```json
{"ok": true,
 "apple": [{"id": "…", "title": "My Tasks", "account_title": "iCloud", "account_id": "…"}],
 "google": [{"id": "…", "title": "My Tasks"}]}
```

`google` is `null` without `--google`.

### `config show --json`

```json
{"ok": true, "config_path": "…", "config": { "include_lists": ["My Tasks"], "bidirectional": true, … }}
```

Shows the user-facing keys listed under `config merge`; never credentials.

### `config init [--force] --json`

Writes the product defaults (two-way, completions and deletions within safety
limits, undated reminders, import existing Google tasks, 60-second interval)
if `config.json` does not exist. `--force` replaces it after a backup.

### `config merge --json` (JSON object on stdin)

Merges the given keys into `config.json` after validating the whole result,
writes atomically with mode 0600, and returns the same shape as `config show`.
Allowed keys:

`include_lists` (array of Reminders list titles), `list_policies`,
`bidirectional`, `delete_stale`, `conflict_policy` (`skip`|`newer_wins`),
`tasks_sync_undated`, `tasks_import_unsynced`, `tasks_create_missing_lists`,
`tasks_complete_stale`, `sync_interval_seconds` (>= 60),
`max_destructive_changes`, `max_destructive_ratio`, `mutation_approval_prompt`,
`macos_notifications`, `language` (`auto`|`en`|`zh`), `proxy` (`""`, `"none"`,
or `http://host:port`), `oauth_client` (`auto`|`custom`|`bundled`),
`setup_completed_at` (string or null), `trigger_min_interval_seconds`.

Unknown keys fail with `config_invalid`.

### `client import <path> --json` / `client status --json`

`import` validates a Google OAuth client JSON of type **Desktop app**
(`{"installed": {...}}`), rejects Web clients with a clear message, copies it
to `credentials.json` (0600) and sets `oauth_client` to `custom`.

```json
{"ok": true, "client_id_hint": "1234…apps.googleusercontent.com"}
```

`status` returns the `oauth_client` object shown in `status --json`.

### `auth [--no-browser] --json`

Runs Google sign-in with PKCE and a loopback redirect on `127.0.0.1`. Opens the
default browser unless `--no-browser` (then the URL is printed to stderr). Waits
up to 5 minutes. The app can cancel by sending SIGTERM.

```json
{"ok": true, "account_email": "me@gmail.com", "client_mode": "custom", "account_fingerprint": "1a2b3c4d5e6f"}
```

Sign-in is rejected (exit 3) when the person unticks the Google Tasks
permission on Google's consent screen.

### `account --json` (network)

Refreshes the token and proves the Tasks API works.

```json
{"ok": true, "account_email": "me@gmail.com", "tasklist_count": 3}
```

### `signout [--revoke] --json`

Deletes `token.json` (after a private backup); with `--revoke` first asks
Google to revoke the token. The sync map is kept; signing back in to the same
Google account continues where it left off.

### `sync [--dry-run] [--no-delete-stale] --json`

One synchronization. Setup runs `sync --dry-run --no-delete-stale --json`,
shows the counts, then `sync --no-delete-stale --json`.

```json
{"ok": true, "dry_run": true,
 "summary": {"apple_exported": 12, "google_lists": 1, "inserted": 0, "updated": 0,
             "unchanged": 12, "completed": 0, "deleted": 0, "duplicate_deleted": 0,
             "google_applied": 3, "bidir_conflicts": 0, "skipped_invalid": 0},
 "plan": {"total_count": 5, "destructive_count": 0,
          "counts": {"apple_reminders.create": 3, "google_tasks.insert": 2}}}
```

`plan.counts` keys are `<target>.<operation>`, for example
`google_tasks.insert`, `google_tasks.update`, `google_tasks.complete`,
`google_tasks.delete`, `google_tasks.create_list`, `apple_reminders.create`,
`apple_reminders.update`, `apple_reminders.complete`, `apple_reminders.delete`.
When the safety limits block the plan, exit code 5 and
`{"ok": false, "error": {"code": "approval_required", …}, "plan": {…}}`.

### `run-loop [--log-file PATH] [--log-max-bytes N]`

The background scheduler. Cycles start every `sync_interval_seconds`
(start-to-start). With `--log-file`, all human-readable output goes to that
private, size-rotated log. With `LTB_EVENT_STREAM=stdout`, one line per event is
written to stdout, each starting with `@@LTB ` followed by a JSON object:

| `event` | Fields |
| --- | --- |
| `loop_started` | `version`, `interval` |
| `cycle_started` | `at` |
| `cycle_finished` | `at`, `state`, `condition`, `consecutive_failures` |
| `paused` / `resumed` | `at` |
| `notification` | `title`, `message`, `severity` (`info` or `problem`) |
| `approval_requested` | `destructive_fingerprint`, `destructive_count` |

When the event stream is on, the engine does **not** call `osascript` for
notifications; the app posts them. The bulk-change approval dialog is still
shown by the engine via `osascript` (it has to wait for an answer), and the
app additionally offers **Review Pending Changes…** through `approvals`.

The loop starts a cycle within about one second when `sync-now` is touched
(no more often than `trigger_min_interval_seconds`, default 10, after the
previous start), and skips cycles while `paused` exists.

Only one `run-loop` runs per config directory: a second one exits with status 1
while another holds `run-loop.lock`. To stop the loop, send SIGTERM and allow up
to 30 seconds: an idle loop exits at once, a loop in the middle of a cycle
finishes that cycle first so state is never left half-written.

### `pause --json`, `resume --json`, `sync-now --json`

Create/remove the `paused` file and touch `sync-now`. All return `{"ok": true}`.

### `approvals show --json`

Computes the next plan without writing anything (network + EventKit) and lists
what needs approval. Titles appear only in this output and the dialog, never in
`status.json` or logs.

```json
{"ok": true, "pending": true,
 "destructive_fingerprint": "<64 hex>", "destructive_count": 7, "population": 20, "ratio": 0.35,
 "items": [{"operation": "google_tasks.delete", "label": "Delete in Google Tasks (deleted on this Mac)",
            "list": "My Tasks", "title": "Buy milk"}]}
```

`pending` is false (and `items` empty) when nothing needs approval.

### `approvals apply <fingerprint> --json` / `approvals hold <fingerprint> --json`

`apply` performs exactly that set of deletions/completions in one live sync;
if the plan changed meanwhile it fails with `plan_changed`. `hold` records the
decision so the scheduler keeps everything else syncing and asks again later.

### `doctor [--online] --json`

```json
{"ok": true, "checks": [{"id": "config", "ok": true, "label": "Configuration"}, …],
 "next_step": "…", "condition": "healthy"}
```

### `migrate [--from PATH] [--dry-run] [--yes] --json`

Imports an older installation without losing the sync map or Google sign-in:
the 2026-09 private trial (`~/.config/reminders-task-bridge-trial/daily-config.json`)
or the upstream layout (`~/.config/icloud-reminders-google-sync/config.json`).
Copies credentials, token, state, and status into the new config dir, keeps the
sync choices, carries over an `HTTPS_PROXY` from the old LaunchAgent as `proxy`,
then stops and disables the old LaunchAgent (`com.icloud-reminders-google-sync`)
and moves its plist into `backups/`. Old files are left in place.

```json
{"ok": true, "migrated_from": "/…/daily-config.json", "copied": ["credentials", "token", "state", "status"],
 "legacy_agent_stopped": true, "dry_run": false}
```

`status --json` reports `legacy_install_detected: true` while an old install
exists and no new `config.json` does.

### `agent install --app <path-to-.app> --json` / `agent uninstall --json` / `agent status --json`

Manages the login item as a user LaunchAgent:

```text
Label                  io.github.siyuanj.local-tasks-bridge
ProgramArguments       [<app>/Contents/MacOS/LocalTasksBridge, --background]
RunAtLoad              true
KeepAlive              {SuccessfulExit: false}   (Quit stays quit until next login)
LimitLoadToSessionType Aqua
ProcessType            Interactive
ThrottleInterval       30
StandardOutPath/StandardErrorPath  ~/Library/Logs/LocalTasksBridge/app.log
```

`install` writes the plist and bootstraps it only when the job is not already
loaded (so an app started by launchd never kills itself). `uninstall` deletes
the plist, and boots the running job out only when `--bootout` is given or when
it is not called by the app (`LTB_APP_BUNDLE` unset). `status` returns
`{"installed", "loaded", "label", "plist", "program"}`.

### `uninstall [--revoke] [--delete-data] --yes --json`

Removes the LaunchAgent (booting it out only when not called by the app);
with `--revoke`, revokes the Google token; with `--delete-data`, deletes the
config dir and logs. The app then moves itself to the Trash and quits with
exit status 0, so `KeepAlive` does not restart it.

### Terminal-only commands

`manage` (interactive recovery menu), `doctor` without `--json`,
`init-config`, `export`, `gcloud-login` (advanced, legacy).

## 6. Reminders helper contract

Unchanged from the upstream project so existing behavior and tests hold.

`ltb-reminders-export [--lookahead-days N] [--include-undated] [--completed-only] [--list NAME]… [--lists-only]`
prints a JSON array. Reminder objects have `id`, `external_id`, `stable_id`,
`title`, `notes`, `list_title`, `list_id`, `account_title`, `account_id`,
`priority`, `is_completed`, `is_recurring`, `recurrence_count`, `created_at`,
`modified_at`, `completed_at`, `due_at`, `due_date`, `all_day`, `date_source`.
With `--lists-only`, objects have `id`, `title`, `account_title`, `account_id`.

`ltb-reminders-apply [--list NAME]…` reads a JSON array of operations on stdin:

- create: `{"create": true, "list_id", "list_title", "title", "notes", "all_day", "due_date" | "due_at", "complete"}`
- update: `{"stable_id", "title"?, "notes"?, "clear_due"?, "all_day"?, "due_date"?, "due_at"?, "complete"?}`
- delete: `{"stable_id", "delete": true}`

and prints a JSON array of results with `status` in `created`, `updated`,
`deleted`, `missing`, `missing_list`, `error`.

Both exit 1 with a message on stderr when EventKit access is denied. When the
engine's configured helper path ends in `.swift` it runs `swift <path>`;
otherwise it executes the path directly.
