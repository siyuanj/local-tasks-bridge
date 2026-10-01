# Local Tasks Bridge product roadmap

Date: 2026-10-01

## Current baseline

The private `siyuanj/local-tasks-bridge` repository is the maintained source of
truth. It preserves the original MIT license and upstream history. The current
Mac installation already provides a signed-in-user LaunchAgent, an Apple
Reminders permission host, Google Tasks OAuth, bounded destructive changes,
private local logs, and a verified bidirectional `My Tasks` workflow.

The public GitHub Pages homepage and privacy policy are OAuth branding documents.
They do not host the synchronization service and do not receive task content or
tokens. Synchronization runs locally between EventKit and the official Google
Tasks API.

## Product milestones

### 1. Reproducible developer release

- Replace trial-specific paths and names with a versioned product configuration.
- Keep `origin` fixed to `siyuanj/local-tasks-bridge`; retain the original
  project as the fetch-only `upstream` remote.
- Produce a clean release from an exact `main` commit with checksums and a
  rollback manifest.
- Add a migration path from the current private installation without resetting
  the task mapping or OAuth authorization.

Acceptance: a clean clone can run all offline checks and build the same local
app bundle from documented commands without reading the maintainer's private
configuration.

### 2. Installable macOS application

- Move setup, list selection, connection status, pause/resume, and diagnostics
  into the app UI.
- Build Apple silicon and Intel-compatible artifacts where supported.
- Sign and notarize release builds with the maintainer's Apple developer
  identity before distributing them to other Macs.
- Provide an uninstall path that removes the LaunchAgent and runtime while
  preserving or explicitly deleting user data according to the user's choice.

Acceptance: installation, first authorization, one round trip, restart, upgrade,
rollback, and uninstall pass on a clean test account and Mac user profile.

### 3. Credential and privacy hardening

- Store refresh tokens in macOS Keychain instead of a JSON token file.
- Keep task content out of diagnostics by default and add a user-controlled
  redacted support bundle.
- Retain minimum Google scopes and per-list synchronization boundaries.
- Add a documented threat model, dependency inventory, and release checksum.

Acceptance: repository and release artifacts contain no credentials; revoked
authorization fails closed; logs and support bundles pass a secret/content scan.

### 4. Broader Google OAuth distribution

- Decide whether releases require each user to provide a personal Google OAuth
  client or use a maintainer-operated OAuth client.
- Re-check current Google branding, privacy, publishing, and verification
  requirements for the selected scopes before public distribution.
- Keep the homepage, privacy policy, support contact, and data-deletion guidance
  aligned with actual application behavior.

Acceptance: a new user can understand who operates the OAuth client, what data
is accessed, where it is stored, and how to revoke access before authorizing.

### 5. Reliability and release automation

- Add end-to-end tests for login/restart, sleep/wake, temporary offline periods,
  duplicate titles, bulk completion, deletion, conflict handling, and upgrades.
- Test supported macOS versions and both processor architectures used by release
  targets.
- Build releases in CI from tagged `main` commits, publish checksums, and require
  the existing source gate and test suite before release.
- Add semantic versions and a changelog; do not auto-update until rollback and
  signature verification are proven.

Acceptance: the release matrix is green, a clean machine can install the tagged
artifact, and the resulting binary and source commit are traceable by checksum.

## Current no-go conditions for public release

- Tokens remain in plain JSON rather than Keychain.
- Reboot, sleep/wake, offline recovery, upgrade, and uninstall are not yet
  accepted on a clean machine.
- General deletion propagation has not completed a dedicated live acceptance.
- The current app has no user-facing onboarding or status UI for a new user.

