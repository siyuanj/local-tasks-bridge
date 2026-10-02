# Agent instructions

Guidance for AI coding agents (and humans in a hurry) working in this
repository. Local Tasks Bridge is a local-first macOS menu bar app that syncs
Apple Reminders with Google Tasks. It handles people's real tasks and Google
credentials, so correctness, data safety and privacy come before everything
else.

Read these first:

- [docs/app-engine-contract.md](docs/app-engine-contract.md) — the interface
  between the app and the engine (commands, JSON, exit codes, files,
  environment). It is the technical source of truth.
- [CONTRIBUTING.md](CONTRIBUTING.md) — development setup and the rules for
  changes.
- [docs/architecture.md](docs/architecture.md) — how a sync cycle works and why.

## Product contract

- Two-way sync of the Reminders lists the user selects with the Google Tasks
  lists of the same names; completions and deletions propagate within the
  safety limits.
- Local-first: no server, no accounts, no telemetry or analytics. The engine
  talks only to Google's OAuth and Tasks endpoints; the app contacts GitHub only
  when the user chooses **Help** or **Check for Updates…**.
- The app never edits sync state itself. It runs engine commands and reads
  their JSON; anything the app does can also be done with `ltb`.
- Every user-facing message exists in English and Simplified Chinese.
- Fixed names: app `Local Tasks Bridge.app`, bundle identifier
  `io.github.siyuanj.LocalTasksBridge`, LaunchAgent
  `io.github.siyuanj.local-tasks-bridge`, settings `~/.config/local-tasks-bridge/`,
  logs `~/Library/Logs/LocalTasksBridge/`, CLI `ltb`.

## Safety invariants — never weaken them

1. **Plan before writing.** Every Apple or Google write happens only after the
   complete two-way mutation plan exists. A plan whose deletions and
   completions exceed `max_destructive_changes` (25) or `max_destructive_ratio`
   (25 %) is never written without an approval of exactly that destructive set
   (its destructive fingerprint); approvals expire.
2. **Hold, don't stop.** The scheduler holds only deletions and completions and
   keeps syncing everything else. It asks only after the same destructive set
   has been seen on two consecutive cycles; **Hold** waits 6 hours; nothing is
   approved automatically by default (`auto_approve_destructive_loops` = 0).
3. **Deletion-free start.** A list without entries in the sync map (first
   sync, rebuilt or lost map, newly selected list) never propagates deletions
   or completions on that cycle; rebuilds use `--no-delete-stale`. While
   deletions are held, nothing is recreated or written for them.
4. **Empty-source guard.** If the selected lists export no active reminders,
   deletions are skipped for that cycle.
5. **Account binding.** `state.json` is bound to hashes of the Apple account IDs
   and the Google account ID. A mismatch stops the sync before any remote list
   is read or written; rebuilding happens only after a backup and the user's
   confirmation.
6. **Minimal Google access.** Sign-in requests only the Tasks scope plus
   `openid` and `email`, and is rejected if the Tasks scope wasn't granted.
7. **Verify writes.** Titles and due dates are re-read from Google after
   writing.
8. **No blind retries of writes.** Only reads are retried; a completion is
   retried only after a read confirms the task is still open.
9. **Privacy of local data.** Private folders are `0700`, files `0600`. Titles
   never go into `status.json`, fingerprints or command-line arguments; the
   approval dialog receives its text through the environment. Logs with titles
   stay in `~/Library/Logs/LocalTasksBridge/`, never in `/tmp`.
10. **Engine dependencies.** Python 3.9+, standard library only.
11. **List scope changes are never deletions.** Completions and deletions
    apply only to items of lists that are still selected and still paired
    with the same Google list.
12. **Writes are never interrupted.** Write commands finish before honouring
    SIGTERM and the app never cancels them; `uninstall --delete-data` deletes
    only the product's own files.

Only change sync behavior with a reproducible case and a regression test that
fails without the change.

## Where things live

| Path | Contents |
| --- | --- |
| `engine/local_tasks_bridge.py` | Sync engine and `ltb` CLI (Python 3.9+, standard library) |
| `macos/App/` | Menu bar app (Swift): engine supervision, menus, setup, settings |
| `macos/Helpers/` | `RemindersExport.swift`, `RemindersApply.swift` — EventKit helpers, compiled into the app |
| `macos/Resources/` | `Info.plist`, entitlements, `bin/ltb`, `en.lproj`, `zh-Hans.lproj` |
| `tests/` | Unit/regression tests and end-to-end scenarios; `tests/e2e/` holds the fake Google server and fake Reminders helpers |
| `scripts/` | `build-app.sh`, `package-release.sh`, `fetch-python.sh`, `test-install.sh`, `check-release-source.sh` |
| `install.sh` | Installer, updater and uninstaller |
| `docs/` | Documentation, in English and Chinese pairs (`x.md`, `x.zh-CN.md`) |
| `site/` | Static website (home page and privacy policy, English / Chinese), published by `.github/workflows/pages.yml` |
| `promo/` | Promo video (Remotion, English / Chinese): one scene per feature; see `promo/README.md` |
| `.github/` | CI, release, website and promo workflows, issue and pull request templates |

## Required checks

Run before proposing a change:

```bash
make test    # unit and end-to-end tests; offline, synthetic data only
make lint    # shell, workflow and Python syntax checks
```

Also run `make app` when you touch `macos/`, `scripts/` or `install.sh`, and
`scripts/test-install.sh` when you touch `install.sh`. Builds need only the
Xcode Command Line Tools.

Tests must never read or write real Reminders, Google data, OAuth credentials,
`~/.config`, `~/Library` or launchd. Use the test-only overrides listed in the
contract (`LTB_TASKS_API`, `LTB_OAUTH_*_URL`, `LTB_REMINDERS_EXPORTER`,
`LTB_REMINDERS_APPLY`, `LTB_BUNDLED_OAUTH_CLIENT`, `LTB_LAUNCH_AGENTS_DIR`,
`LTB_NO_LAUNCHCTL=1`, `LTB_LOG_DIR`) and temporary directories.

## Live operations: only when the user asked

These change a real Mac, real accounts or real data. Do not run them unless the
user explicitly asked for that specific operation:

- the setup assistant, `ltb auth`, `ltb signout`, `ltb client import`;
- `ltb sync` without `--dry-run`, `ltb approvals apply|hold`, `ltb manage`
  actions that change anything, `ltb migrate`, `ltb rebuild`, `ltb config merge|init` against
  the real settings;
- `ltb agent install|uninstall`, `ltb uninstall`, `launchctl
  bootstrap|bootout|enable|disable`, `tccutil reset`;
- `./install.sh`, `make install`, `make uninstall`, or opening the installed
  app;
- editing anything in `~/.config/local-tasks-bridge/`,
  `~/Library/LaunchAgents/` or `~/Library/Logs/LocalTasksBridge/`, or in an
  earlier installation's folders.

Read-only diagnosis is fine when it helps: `ltb version`, `ltb status`,
`ltb doctor` (without `--online`). Even `ltb sync --dry-run`,
`ltb approvals show`, `ltb lists --google` and `ltb doctor --online` read real
reminders and Google data and may refresh the token — treat them as live reads.

Never copy tokens, client secrets, `state.json`, logs, exports or real task
titles into chat, commits, issues or test fixtures.

## Working in the repository

- Work on a branch from `main`; keep changes focused; stage explicit paths and
  preserve unrelated work in the tree.
- The `upstream` remote (`syncweave-labs/reminders-task-bridge`) is fetch-only.
  Don't push there and don't rewrite published history.
- When you change commands, JSON output, exit codes or files, update the
  contract and both the engine and the app in the same change.
- Every user-facing string gets English and Chinese text: `tr("…", "…")` in the
  engine, `NSLocalizedString` with entries in `en.lproj` and `zh-Hans.lproj` in
  the app. Documentation changes update both language versions. Use Apple's
  Chinese terms: 提醒事项, 系统设置, 隐私与安全性, 登录项, 小组件.
- Add a line to `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md) for
  user-visible changes.
- Never commit OAuth client JSON, tokens, sync state, logs or exports.
