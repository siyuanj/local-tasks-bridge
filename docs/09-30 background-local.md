# Private background synchronization, 2026-09-30

The user requested automatic synchronization after the manual round trip and
My Tasks import passed. This is a private reviewed fork, not an upstream release.
The source gate's documented non-main/unpushed overrides are used with a recorded
reason and an exact clean commit. The source is not pushed to the repository
author. The standard installer is not used because it would replace the bounded
configuration and authentication workflow.

`scripts/install-local-background.py` copies the reviewed sync engine and both
Swift helpers to a release directory named by the source commit, records SHA-256
hashes, and creates the standard stable `current` pointer. It copies only the
existing Python runtime and standard library (excluding site-packages) so Codex
cache removal does not break the service. No dependencies are downloaded.

The existing private `daily-config.json`, Google credentials, and state stay in
`~/.config/reminders-task-bridge-trial/`. Only My Tasks is selected. The existing
one-destructive-change limit, conflict skipping, empty-source guard, and lack of
automatic destructive approval remain. More than one completion/deletion in a
cycle may be held; the private status records that condition. General deletion
has not been live-tested. OAuth Testing's seven-day expiry is still a limitation.

The LaunchAgent runs the named `~/Applications/Local Tasks Bridge.app` permission
host, which requests its own Reminders grant and launches the reviewed Python
`run-loop`. Direct launchd Python could not inherit Codex's privacy access.
`scripts/package-local-launcher.py` builds the host using the existing CLT,
ad-hoc signs it, verifies the signature, and records source/binary hashes outside
the bundle. The user allowed the system prompt.

The loop uses a 60-second sleep after each synchronization pass. It starts at
login and restarts after unexpected process exit. It runs in
the signed-in user's session. A sleeping or offline Mac cannot synchronize; the
loop resumes after waking/network recovery. No logout/reboot test is implied by
loading the agent and observing scheduled cycles.

Start:

```sh
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.icloud-reminders-google-sync.plist"
```

Stop (also prevents further cycles until next login or start):

```sh
launchctl bootout "gui/$(id -u)/com.icloud-reminders-google-sync"
```

Inspect:

```sh
launchctl print "gui/$(id -u)/com.icloud-reminders-google-sync"
```

For a lasting disable, use `launchctl disable` on that service target in addition
to bootout; `launchctl enable` reverses it. Logs are in the private
`~/Library/Logs/icloud-reminders-google-sync/` directory. Do not share these logs:
they contain task titles. The runtime installer backs up the prior config before
changing helper paths. Rollback: unload the LaunchAgent, restore that config
backup, and use the previously verified manual workflow.

Actual acceptance: two scheduled cycles completed, read the two active My Tasks
reminders and verified their Google title/due consistency. Stop/restart terminated
the old launcher/Python children, and a subsequent new cycle completed.
Ten previously completed Mac test tasks remain held for explicit bulk approval;
other synchronization proceeds. There is no reboot/login or long-duration test.
See STATUS for timestamps, process IDs, incomplete installation attempts, and
remaining OAuth limitations.
