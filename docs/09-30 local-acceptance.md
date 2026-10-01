# Local acceptance, 2026-09-30

## Scope and authorization

The user explicitly approved the Google User Data Policy, creation of the local
desktop OAuth client, and Google Tasks read/write access. They requested a free,
Google-preserving Mac desktop workflow and protection from sending data to the
repository author. The initial acceptance used a manually run private fork, not an upstream
production deployment. The initial trial used no installer or LaunchAgent. A native-hosted background
agent was added later at the user's request; billing enrollment never ran.

The user's independent Google Cloud project is `reminders-tasks-local-bridge`.
The Google Tasks API is enabled and only their own account is a test user.
OAuth credentials and tokens are outside this checkout in
`~/.config/reminders-task-bridge-trial/`, with directory mode 0700 and credential
files 0600. The granted scopes are Tasks, userinfo.email, and openid; there is no
Calendar or Cloud Platform scope. No credentials belong in this document.

## Actual acceptance results

The isolated trial used only `Bridge Test 2026-09-30` in Google Tasks and
the matching iCloud Reminders list. My Tasks was connected later after the user
selected it explicitly; see the everyday import record below.

| Case | Result |
| --- | --- |
| Mac creates A, Google receives A | API and Google Tasks webpage verified |
| Google creates B, Mac receives B | Reminders UI verified |
| Google changes A title, Mac receives title | Reminders UI verified |
| Mac changes B title, Google receives title | API verified |
| Mac completes A, Google receives completion | API verified |
| Google completes B, Mac receives completion | Initially exposed a deletion bug; repaired and rerun |
| Repeat sync after convergence | Zero mutations, one active item unchanged |
| Desktop widget rendering | User screenshot verifies the correct list and active C |
| Desktop widget checkbox completion | User clicked C; live sync completed=1, deleted=0; API confirms C completed |

Current disposable test state: A, B, and C are completed on both sides. The user
completed C from the desktop widget; a live sync propagated exactly one
completion and no deletion. A follow-up plan contains zero mutations. The original Google B was accidentally
deleted by the upstream bug during the isolated trial. B was reactivated on the
Mac and recreated in Google under a new task ID before retesting. No everyday
list was connected during that isolated defect trial.

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
  "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" \
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

1. Desktop rendering is verified by the user screenshot (audit/widget-visible-user.png).
2. Desktop checkbox completion is verified by Google API and the native completed list.
3. My Tasks initial import is verified below. The user confirmed its desktop widget selection;
   the persistent runtime is now documented in the background record; Python is now copied into a standalone private runtime.
4. Address Google External/Testing's seven-day refresh-token expiry before
   describing this as a low-maintenance daily installation.

## Last-item completion boundary

During widget preparation, an additional regression reproduced that completing
the last active reminder leaves its Google task incomplete: the empty-source
guard previously disabled both deletion and completion processing. The repair
separates permission to propagate a positively observed completed reminder from
permission to delete a missing item. Both planning and execution retain the
empty-source deletion guard, per-list policy checks, and destructive-plan limit.
The explicit no-deletion-propagation setting still suppresses completions.

The new orchestration test supplies one explicitly completed reminder and one
missing tracked reminder, with zero active reminders. Before the repair it fails
because no completion is written; afterward only the completed item is patched,
the missing item is never deleted, and a disabled-propagation subcase writes
nothing. The full isolated suite now passes 95 tests. Logs are in task-folder
`audit/last-completion-before.log` and `audit/last-completion-after.log`.
Live last-item/widget verification subsequently passed: completed=1, deleted=0;
Google API retains all three completed test tasks. The next plan is empty.

The user opened the widget gallery, and automation could select the native Mac
Reminders category. Adding the medium preview and pressing Done did not yield a
verifiable Reminders desktop window: subsequent native AX/screenshot observations
selected the existing Photos widget. The user has been asked to manually add the
Reminders widget and select `Bridge Test 2026-09-30`. The user subsequently
provided a screenshot showing the correct list and one active C on the desktop.
This verifies placement and rendering. Checkbox interaction remains pending;
a fresh Google API read at 22:48 CST still shows C needsAction and A/B completed.

The reviewed network paths use official Google endpoints and local EventKit.
This source review and bounded trial are evidence of observed behavior, not a
formal guarantee against all security or synchronization defects.

## Everyday My Tasks import

The user selected the existing Google My Tasks list. A native iCloud list with
the same name was created, and a separate private daily-config.json and state
were used. The initial import disabled stale completion/deletion propagation.
It imported 12 active Google tasks and attached synchronization metadata to
the existing Google records; no new Google task was created, completed, or
deleted. All pre-existing Google task IDs and completion/deletion states were
verified unchanged. EventKit and Google active-title multisets match at 12;
the native Reminders sidebar also shows 12. Twelve old completed Google records
were preserved in Google but were not imported into Mac Reminders.

After the initial state was established, completion propagation was enabled
with the prior one-destructive-change limit, conflict skipping, and empty-source
deletion protection. The resulting dry-run is empty. The upstream setting also
enables missing-item deletion within these limits; general deletion has not
been live-tested. A native-hosted persistent agent is installed; see docs/09-30 background-local.md. The user confirmed switching the desktop widget to My Tasks. This last UI
selection is user-reported; native UI automation did not independently verify it.
Private evidence: daily-first-live.log, daily-converged.log,
daily-google-before-latest.json, daily-google-after.json, daily-apple-after.json.
