# Migrating from an earlier installation

**English** · [简体中文](migration.zh-CN.md)

Local Tasks Bridge 1.0 can take over from two earlier installations without
losing the Google sign-in or the sync map — so nothing is re-created,
duplicated or deleted:

| | 2026-09 private trial | Upstream project |
| --- | --- | --- |
| Name | Local Tasks Bridge trial | `syncweave-labs/reminders-task-bridge` (“iCloud Reminders ↔ Google Tasks Sync”) |
| Settings | `~/.config/reminders-task-bridge-trial/daily-config.json` | `~/.config/icloud-reminders-google-sync/config.json` |
| Login item | LaunchAgent `com.icloud-reminders-google-sync` | LaunchAgent `com.icloud-reminders-google-sync` |
| Program files | `~/.local/share/icloud-reminders-google-sync/` and a permission host app `~/Applications/Local Tasks Bridge.app` (identifier `local.reminders.tasks.bridge`) | `~/.local/share/icloud-reminders-google-sync/` and a Finder manager in `~/Applications` named `Google Tasks ….command` |
| Logs | `~/Library/Logs/icloud-reminders-google-sync/` | `~/Library/Logs/icloud-reminders-google-sync/` |

If both exist, the trial is imported. Choose explicitly with `--from`.

## What the import does

1. It finds the earlier settings file (or the one given with `--from`). If this
   Mac already has a 1.0 configuration, it stops — `--force` imports anyway and
   keeps backups of the files it replaces, `config.json` included.
2. It writes a new `~/.config/local-tasks-bridge/config.json` from the 1.0
   defaults plus your earlier choices: selected lists, per-list policies,
   direction, deletion and conflict settings, undated and import options, the
   sync interval, the safety limits and approval settings, notifications and
   sign-in options. The Google client choice is set to `auto`, so an imported
   own client is used. The old helper paths are dropped — 1.0 uses its compiled
   helpers.
3. If the old settings had no proxy but the old login item set `HTTPS_PROXY` or
   `HTTP_PROXY`, that proxy becomes the `proxy` setting.
4. It stops the old background job (`launchctl bootout
   gui/<uid>/com.icloud-reminders-google-sync`) **before** copying anything, so
   its last cycle can't write after the copy was taken, and moves the old
   LaunchAgent plist into `~/.config/local-tasks-bridge/backups/<time>-migrate/`
   so it no longer starts at login.
5. It copies the OAuth client, the token, the sync map and the status file into
   `~/.config/local-tasks-bridge/` with private permissions.
6. It moves world-readable logs that very old upstream versions left in
   `/tmp` (`/tmp/icloud-reminders-google-sync.*`) into the same backup folder.

Everything else stays where it was: the old settings folder, program files and
logs are not touched.

The account binding comes along with the sync map. Maps from earlier versions
are bound to the Google sign-in itself; on the first 1.0 sync, the bridge sees
that the sign-in is unchanged and upgrades the binding to your Google account
ID in place.

## Import with the app

1. Install 1.0 ([README](../README.md#install)). The installer recognizes the
   trial's app of the same name in `~/Applications` and moves it to the Trash
   as “Local Tasks Bridge (trial build …).app”.
2. Open Local Tasks Bridge. It detects the earlier installation and offers
   **Import My Existing Setup**. Choose it and confirm. The app must run from
   the Applications folder for this.
3. When macOS asks whether Local Tasks Bridge may access your reminders, click
   **Allow**. To macOS, 1.0 is a different app from the trial's permission
   host, so the permission is asked for again.
4. Review the settings (see [Check the result](#check-the-result)).

## Import with the command line

```bash
ltb migrate --dry-run   # shows what would be imported; changes nothing
ltb migrate             # asks for confirmation, then imports
```

To pick a specific installation:

```bash
ltb migrate --from ~/.config/icloud-reminders-google-sync/config.json
```

Then open Local Tasks Bridge so that background sync starts.

## Check the result

1. **Status:** `ltb status` should show `healthy` after the first cycle.
   `ltb doctor` lists the individual checks.
2. **A dry run should be close to empty:**

   ```bash
   ltb sync --dry-run
   ```

   A few updates are normal. If the plan wants to create or delete many items,
   don't continue: choose **Pause Sync**, then look at `ltb status` and the
   log.
3. **The old job is gone:**

   ```bash
   launchctl print gui/$(id -u)/com.icloud-reminders-google-sync
   ```

   should report that the service can't be found.
4. **Your settings came along unchanged** — check them with `ltb config show`
   or in **Settings**. The trial ran with stricter values (for example a limit
   of one deletion or completion per cycle and `conflict_policy: skip`). To use
   the 1.0 defaults instead:

   ```bash
   echo '{"max_destructive_changes": 25, "max_destructive_ratio": 0.25,
          "conflict_policy": "newer_wins", "mutation_approval_prompt": true,
          "macos_notifications": true}' | ltb config merge --json
   ```

5. **A real round trip:** change one test reminder on the Mac and one test task
   in Google, and check that both changes arrive on the other side.

### Upstream installations that signed in with gcloud

If the upstream installation signed in through gcloud Application Default
Credentials (`use_adc: true`), the import keeps using those credentials. That
legacy method works but isn't supported by the app. To switch to a normal
sign-in, set `use_adc` to `false` in `~/.config/local-tasks-bridge/config.json`,
quit and reopen the app, and choose **Reconnect Google…**. Because the old sync
map was bound to the gcloud credential, the bridge may then report *account
binding required*; choose **Pair Accounts Again…** (or run `ltb rebuild`) to rebuild the map — it backs up
first and deletes nothing (see
[Troubleshooting](troubleshooting.md#account-binding-required)).

## Roll back

The old files are unchanged and the old LaunchAgent plist is in the backup
folder, so you can go back:

1. Quit Local Tasks Bridge (menu → **Quit Local Tasks Bridge**) and remove its
   login item:

   ```bash
   ltb agent uninstall --bootout
   ```

2. Put the old login item back:

   ```bash
   mv ~/.config/local-tasks-bridge/backups/*-migrate/com.icloud-reminders-google-sync.plist \
      ~/Library/LaunchAgents/
   ```

3. **Trial only:** the trial's login item starts its permission host
   `~/Applications/Local Tasks Bridge.app/Contents/MacOS/LocalBridgeLauncher`,
   which the 1.0 app replaced. Move the 1.0 app elsewhere, take
   “Local Tasks Bridge (trial build …).app” out of the Trash, rename it to
   `Local Tasks Bridge.app` and put it back into `~/Applications`. (It can also
   be rebuilt from the trial source, commit `b1c868a`,
   `scripts/package-local-launcher.py`.)
4. Before the old version runs on its own, check what it would do with a dry
   run of the old engine, using the Python and file paths from the old
   LaunchAgent plist:

   ```bash
   <old-python> ~/.local/share/icloud-reminders-google-sync/current/icloud_reminders_google_sync.py \
     --config <old-settings-file> sync --dry-run --no-delete-stale
   ```

5. Start it again:

   ```bash
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.icloud-reminders-google-sync.plist
   ```

Changes made while 1.0 was running are already in Reminders and Google; the old
engine recognizes items by the same notes footer. Never run the old and the new
version at the same time.

## Clean up

After 1.0 has worked well for a while (a week, say), you can remove what the
earlier installation left behind:

- the old settings folder — `~/.config/reminders-task-bridge-trial/` or
  `~/.config/icloud-reminders-google-sync/` (it contains private copies of the
  old token and sync map);
- the old program files `~/.local/share/icloud-reminders-google-sync/`;
- the old logs `~/Library/Logs/icloud-reminders-google-sync/`;
- trial: the trial build in the Trash, and its old Reminders permission entry
  (`tccutil reset Reminders local.reminders.tasks.bridge`);
- upstream: the Finder manager `~/Applications/Google Tasks ….command`, and, if you
  used gcloud only for this, its credentials
  (`gcloud auth application-default revoke`);
- the old plist in `~/.config/local-tasks-bridge/backups/<time>-migrate/`.

**Don't revoke the old Google sign-in** at Google: 1.0 now uses that same
sign-in.
