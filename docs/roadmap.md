# Roadmap

Where Local Tasks Bridge stands and what comes next. Dates are not promised;
safety and correctness come before new features.

## Done in 1.0

- A native menu bar app with a setup assistant, status, **Sync Now**,
  **Pause Sync**, **Review Pending Changes…**, diagnostics and an update check.
- English and Simplified Chinese throughout the app, the engine, `ltb` and the
  documentation.
- Two Google sign-in methods: the built-in shared client (release builds) and
  your own Google Cloud “Desktop app” client.
- The sync map bound to the Google account ID, so signing in again to the same
  account keeps it, while a different account stops the sync.
- Compiled EventKit helpers instead of interpreting Swift on every cycle.
- Instant sync of local Reminders changes; Google changes on a fixed
  start-to-start cadence (1 minute with your own client, 5 minutes with the
  shared client).
- The safety model: complete mutation plans with fingerprints, limits of 25
  items / 25 % for deletions and completions, held changes reviewed in the
  app's Review Pending Changes window while everything else keeps syncing, a deletion-free first sync, the
  empty-source guard and post-write verification.
- A proxy setting for networks where Google is reachable only through a proxy.
- The `ltb` command line with JSON output for every operation the app uses.
- A one-line installer, release automation for Apple silicon and Intel with an
  embedded Python, and checksums.
- Import of the 2026-09 private trial and of upstream installations.
- Simulated end-to-end tests against a fake Google Tasks server and fake
  Reminders helpers.
- Safe handling of list changes: unselecting, renaming or deleting a list is
  never read as deletions.
- Google edits keep a reminder's time of day, due dates changed or cleared in
  Google flow back to the Mac, and reminders due far in the future sync.
- `ltb rebuild` for recovering from an intended account change.

## Next

- **Developer ID signing and notarization.** Removes the Gatekeeper prompt and
  keeps the Reminders permission across updates. The release scripts are
  prepared; it needs an Apple Developer Program membership.
- **Keychain storage for the Google token**, once Developer ID signing makes
  Keychain access rules stable across updates. With ad-hoc signing every update
  would look like a different app to the Keychain and ask for access again.
- **Google OAuth verification of the shared client**, which lifts the 100-user
  cap and removes the “unverified app” warning, and a higher Tasks API quota
  for the shared project (see [releasing.md](releasing.md)).
- **A Homebrew cask** in a tap, after notarization.
- **Signed automatic updates**, for example with Sparkle and EdDSA-signed
  update feeds, so that updates are verified before they are installed.
- **Follow a renamed list** instead of treating a list renamed on one side as
  a new list.
- **More real-account acceptance testing:** logout and restart, long sleep and
  wake, offline periods, general deletion in both directions, upgrades and
  uninstalling on a clean Mac, and Intel Macs.

## Research

- **Subtasks.** Google Tasks has parent tasks; EventKit doesn't expose
  Reminders' subtasks. Find out whether a faithful mapping is possible.
- **Repeating reminders.** Verify how completions of repeating reminders behave
  in both directions and document the result.
- **Several Macs.** Explore identities that don't depend on one Mac, so that
  more than one Mac could run the bridge safely.

## Not planned

- A server or cloud service of any kind, accounts, telemetry or analytics.
- Windows, Linux or iOS versions — the bridge depends on macOS EventKit, and
  your other Apple devices already get every change through iCloud.
- Syncing other services. The project stays focused on Apple Reminders and
  Google Tasks.
