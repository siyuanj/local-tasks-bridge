# Contributing

**English** · [简体中文](CONTRIBUTING.zh-CN.md)

Thank you for helping improve Local Tasks Bridge! The project is deliberately
conservative: correctness, data safety, privacy and recoverability come before
new features. Small, focused changes with tests are the easiest to accept.

## Reporting a problem

- Search the existing issues first, and try the latest release or `main`.
- Use the bug report template. Describe what you did, what you expected and
  what happened, and include `ltb version`, your macOS version and Mac
  (Apple silicon or Intel), and the sign-in method.
- Share `ltb doctor` output or **Copy Diagnostics** instead of logs. Remove
  reminder and task titles, notes, e-mail addresses, account identifiers, local
  paths, tokens and OAuth responses from anything you post.
- Report security problems privately as described in [SECURITY.md](SECURITY.md),
  never in a public issue.

## Development setup

You need a Mac with:

- the **Xcode Command Line Tools** (`xcode-select --install`), which provide
  `swiftc` and Python 3; the full Xcode app is not needed;
- **Python 3.9 or newer** (`python3 --version`). The engine supports 3.9, the
  version macOS ships with the Command Line Tools, so don't use newer language
  features.

Optional: `shellcheck` and `actionlint` (`brew install shellcheck actionlint`)
for `make lint`.

```bash
git clone https://github.com/siyuanj/local-tasks-bridge.git
cd local-tasks-bridge
make help
```

## Make targets

| Target | What it does |
| --- | --- |
| `make test` | All Python tests — unit and end-to-end. Offline; touches no real data |
| `make test-e2e` | Only the end-to-end tests (`tests/test_e2e*.py`): the real engine CLI against a fake Google OAuth/Tasks server on `127.0.0.1` and fake Reminders helpers, in a temporary `HOME` |
| `make lint` | `bash -n` with macOS's bash 3.2 and `shellcheck` on every shell script, `actionlint` on the workflows, and a syntax check of all Python files |
| `make helpers` | Compile the two Reminders helpers into `build/helpers/` |
| `make app` | Build `build/Local Tasks Bridge.app` for this Mac's architecture (no embedded Python) |
| `make app-universal` | Build a universal (arm64 + x86_64) app |
| `make python` | Download and verify the embedded Python into `build/python/` |
| `make package` | Build the release zips, `SHA256SUMS` and `release-manifest.json` into `dist/` |
| `make install` | Build this checkout and install it into `~/Applications` with `install.sh` (`INSTALL_ARGS="--embed-python --no-open"` and so on are passed through) |
| `make uninstall` | Remove the installed app, its login item and the `ltb` link |
| `make clean` | Remove build outputs and `dist/` |

`scripts/test-install.sh` tests `install.sh` hermetically (temporary `HOME`,
local release files, shims for `open`, `launchctl` and friends). Run it when you
change the installer.

You can run the engine from the checkout without building anything; it uses
`build/helpers/` after `make helpers`, or interprets the Swift sources with
`swift`:

```bash
python3 -B engine/local_tasks_bridge.py --config ~/ltb-dev/config.json status
```

**Careful:** commands like `sync`, `auth`, `approvals apply`, `migrate` or
`agent install` act on real accounts and on your login items. Use a separate
config folder and a test list — or better, the end-to-end harness.

## Repository layout

| Path | Contents |
| --- | --- |
| `engine/local_tasks_bridge.py` | The sync engine and the `ltb` command line (Python, standard library only) |
| `macos/App/` | The menu bar app (Swift) |
| `macos/Helpers/` | `RemindersExport.swift` and `RemindersApply.swift`, the EventKit helpers |
| `macos/Resources/` | `Info.plist`, entitlements, the `bin/ltb` wrapper, `en.lproj` and `zh-Hans.lproj` |
| `tests/` | Unit and regression tests (`test_engine.py`, `test_local_safety.py`) and end-to-end scenarios (`test_e2e_sync.py`) |
| `tests/e2e/` | The end-to-end harness: fake Google server and fake Reminders helpers |
| `scripts/` | Build, packaging, Python download, installer tests and the release source gate |
| `site/` | The website: home page and privacy policy in English and Chinese, plain HTML published to GitHub Pages |
| `install.sh` | The installer and uninstaller |
| `docs/` | Documentation in English and Chinese; [app-engine-contract.md](docs/app-engine-contract.md) is the interface between app and engine |

## Rules for changes

1. **Every change to sync behavior comes with a regression test** that fails
   without the change. Reproduce bugs with synthetic data first.
2. **Never weaken a safety guard or privacy protection** — the destructive
   limits and approval flow, the deletion-free first sync, the empty-source
   guard, the account binding, the post-write verification, private file
   permissions, keeping titles out of `status.json`, logs on disk and argv —
   unless the pull request explains a security reason and the maintainer
   agrees.
3. **Synthetic data only.** Tests must never read or write real Reminders,
   Google Tasks, OAuth credentials, `~/.config`, `~/Library` or launchd. Use
   temporary directories, the test-only overrides
   (`LTB_TASKS_API`, `LTB_OAUTH_*_URL`, `LTB_REMINDERS_EXPORTER`,
   `LTB_REMINDERS_APPLY`, `LTB_BUNDLED_OAUTH_CLIENT`, `LTB_LAUNCH_AGENTS_DIR`,
   `LTB_NO_LAUNCHCTL=1`, `LTB_LOG_DIR`), `example.invalid` addresses and
   obviously fake identifiers.
4. **Every user-facing message exists in English and Simplified Chinese.** In
   the engine use `tr("English", "中文")`; in the app use `NSLocalizedString`
   with entries in both `en.lproj` and `zh-Hans.lproj`. Documentation pages
   come in pairs (`page.md` and `page.zh-CN.md`); update both. Use Apple's
   Chinese terms (提醒事项, 系统设置, 隐私与安全性, 登录项, 小组件). Log lines
   and machine-readable output stay in English.
5. **Keep the contract.** Changes to commands, JSON output, exit codes or files
   update [docs/app-engine-contract.md](docs/app-engine-contract.md) and both
   sides (engine and app) in the same pull request.
6. **No new dependencies** for the engine (standard library only) and no
   network destinations other than Google's OAuth and Tasks endpoints. No
   telemetry.
7. **No secrets or personal data in the repository** — no OAuth clients,
   tokens, sync state, logs, exports or real task titles. `.gitignore` helps;
   check `git status` before committing.

## Pull requests

- One behavioral change per pull request, on a branch from `main`.
- Fill in the template: what changed, how you verified it (`make test`,
  `make lint`, `make app` for changes to `macos/`, `scripts/` or `install.sh`,
  `scripts/test-install.sh` for installer changes), and the impact on installed
  apps, the login item or user data, with a rollback note.
- Add an entry under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md).
- CI must be green.

By contributing, you agree that your contribution is licensed under the
[MIT License](LICENSE). Participation follows the
[Code of Conduct](CODE_OF_CONDUCT.md).
