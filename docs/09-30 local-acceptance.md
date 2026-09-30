# Local acceptance, 2026-09-30

## Scope and authorization

The user explicitly approved the Google User Data Policy, creation of the local
desktop OAuth client, and Google Tasks read/write access. They requested a free,
Google-preserving Mac desktop workflow and protection from sending data to the
repository author. This is a manually run, private fork trial, not an upstream
production deployment. No installer, LaunchAgent, or billing enrollment ran.

The user's independent Google Cloud project is `reminders-tasks-local-bridge`.
The Google Tasks API is enabled and only their own account is a test user.
OAuth credentials and tokens are outside this checkout in
`~/.config/reminders-task-bridge-trial/`, with directory mode 0700 and credential
files 0600. The granted scopes are Tasks, userinfo.email, and openid; there is no
Calendar or Cloud Platform scope. No credentials belong in this document.

## Actual acceptance results

All live changes were restricted to `Bridge Test 2026-09-30` in Google Tasks and
the matching iCloud Reminders list. The pre-existing `My Tasks` list was not
selected for synchronization.

| Case | Result |
| --- | --- |
| Mac creates A, Google receives A | API and Google Tasks webpage verified |
| Google creates B, Mac receives B | Reminders UI verified |
| Google changes A title, Mac receives title | Reminders UI verified |
| Mac changes B title, Google receives title | API verified |
| Mac completes A, Google receives completion | API verified |
| Google completes B, Mac receives completion | Initially exposed a deletion bug; repaired and rerun |
| Repeat sync after convergence | Zero mutations, one active item unchanged |
| Desktop widget rendering and checkbox | Not yet verified; native window automation failed |

Current disposable test state: A and B completed on both sides; C remains active
for the desktop-widget checkbox test. The original Google B was accidentally
deleted by the upstream bug during the isolated trial. B was reactivated on the
Mac and recreated in Google under a new task ID before retesting. No everyday
list was connected.

## Reproduced defect and repair

`run_tasks_sync` reads active and completed reminders before planning inbound
Google changes. After applying a Google completion it refreshed active reminders
but retained the old completed snapshot. Outbound stale cleanup therefore
classified the newly completed reminder as deleted and deleted its Google task.

The local repair refreshes the completed snapshot whenever inbound changes are
applied and completion propagation is enabled. A regression test reproduces the
full synchronization orchestration with mocked external boundaries: before the
repair it observes one unexpected `delete_task`, and afterward it preserves the
same Google task ID and stores the completed mapping. The isolated full suite
passes 94 tests. The live rerun recorded `google_applied=1, deleted=0`; Google API
and Reminders UI both verified B remained completed. A subsequent live pass
recorded `total=0` mutations.

Evidence:

- Task folder `audit/completion-regression-before.log`: expected failing regression.
- Task folder `audit/completion-regression-after.log`: 94 tests passed, network denied.
- Private `sync-google-complete.log`: original defect, one deletion.
- Private `sync-google-complete-fixed.log`: repaired live case, zero deletions.
- Private `sync-idempotence.log`: zero-mutation repeat pass.

Private logs live in `~/.config/reminders-task-bridge-trial/` and are not committed.

## Manual reproduction

Use the existing Python 3.12 runtime and Apple Command Line Tools. The local
Swift invocation requires an explicit SDK; full Xcode was not installed.

```sh
SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk \
  /Users/jiangsiyuan/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  -B icloud_reminders_google_sync.py \
  --config ~/.config/reminders-task-bridge-trial/config.json sync --dry-run
```

Inspect the plan before a manual live run. `trial_acceptance.py inspect` reads
only the named trial list. Its mutation subcommands explicitly identify the
disposable A/B/C tasks and do not accept arbitrary list names.

Current trial config allows completion propagation with at most one destructive
action per plan, `conflict_policy=skip`, and exactly one selected test list.
Completion and deletion propagation share the upstream `delete_stale` option;
this trial has not separately validated general deletion, recurring tasks,
subtasks, exact-time reminders, all-empty-list behavior, or a persistent agent.

## Remaining work

1. Open the Mac widget editor and add Reminders, selecting the test list.
2. Verify C visibly renders and a desktop checkbox completion reaches Google.
3. Only then configure the everyday list and an explicitly documented persistent
   runtime; the current Python path belongs to the existing Codex runtime.
4. Address Google External/Testing's seven-day refresh-token expiry before
   describing this as a low-maintenance daily installation.

The reviewed network paths use official Google endpoints and local EventKit.
This source review and bounded trial are evidence of observed behavior, not a
formal guarantee against all security or synchronization defects.
