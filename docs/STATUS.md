# Local trial status

## 2026-09-30 Asia/Shanghai — reviewed manual trial

- User request: try Apple Reminders/Google Tasks synchronization, keep Google Tasks, avoid a full Xcode installation, and check that data is not sent to the repository author.
- Base: upstream 3501800b672ef58c823eb0711c22412c2db98dce. Work branch codex/local-safe-trial. The installer and persistent LaunchAgent have not run.
- Changes: OAuth requests only the selected service plus openid/email; manual OAuth URL handoff; RemindersApply accepts the same list allowlist as the exporter. Added offline regression checks.
- Review: inspected imports, network destinations, subprocess calls, token files, read/write helper paths, list filtering and installer side effects. Observed destinations are Google API/OAuth endpoints; no developer telemetry or remote-control endpoint was found in inspected paths. This is not a malware-free guarantee or a full formal audit.
- Validation: baseline 91 tests and patched 93 tests pass in a macOS sandbox denying network and other user-file data reads. First sandbox run reported 4 failures due to denied test lock location and parent metadata access; after isolated XDG_CONFIG_HOME and permitted metadata, the suite passed. Network and private-file denial probes passed. Shell syntax and release-gate self-tests pass. Both Swift helpers typecheck using the existing CLT SDK explicitly; no EventKit data access was executed. Existing nonoptional nil-coalescing warning in RemindersApply remains.
- Live setup: private config is outside the repository at ~/.config/reminders-task-bridge-trial/config.json (0600, parent 0700); only Bridge Test 2026-09-30 selected, no ADC fallback, no auto-login/UI notifications, no deletion propagation or scheduled process. No credential/token has been acquired.
- Google Cloud: independent reminders-tasks-local-bridge project created in the user's account; OAuth branding draft My Local Tasks Bridge is at the User Data Policy agreement step. No billing enrollment, API key reuse or third-party account.
- Pending: user agreement to Google's policy; OAuth desktop client/API setup; Google and Reminders consent; single-list dry-run then create/edit/complete round trip and widget rendering. No production deployment or synchronization is claimed.
- Source-only results do not establish native permissions, actual cloud writes, background reliability or visible widget behavior.
