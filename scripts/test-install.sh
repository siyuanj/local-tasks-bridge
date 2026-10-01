#!/bin/bash
#
# Hermetic tests for install.sh.
#
# Every case runs the installer with a temporary HOME, a fake app built here,
# and file:// or local release files. Nothing touches the network, the real
# HOME, a real app, launchd, or the GUI: open, osascript, launchctl, sudo,
# xcode-select, and git are replaced by recording shims.
#
# Usage: scripts/test-install.sh    (LTB_TEST_BASH selects the bash that runs install.sh)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
INSTALLER="${REPO_ROOT}/install.sh"
TEST_BASH="${LTB_TEST_BASH:-/bin/bash}"
BUNDLE_ID="io.github.siyuanj.LocalTasksBridge"
APP_NAME="Local Tasks Bridge.app"
REAL_HOME="${HOME:-}"

[ "$(uname -s)" = "Darwin" ] || { printf 'SKIP: install.sh tests need macOS.\n'; exit 0; }
[ -f "$INSTALLER" ] || { printf 'FAIL: %s not found\n' "$INSTALLER"; exit 1; }

TMP_PARENT="${TMPDIR:-/tmp}"
TMP_ROOT="$(mktemp -d "${TMP_PARENT%/}/ltb-test-install.XXXXXX")"
TMP_ROOT="$(cd "$TMP_ROOT" && pwd -P)"
SHIM_DIR="${TMP_ROOT}/shims"
FIXTURES="${TMP_ROOT}/fixtures"
CALLS="${TMP_ROOT}/calls"
mkdir -p "$SHIM_DIR" "$FIXTURES" "$CALLS" "${TMP_ROOT}/tmp" "${TMP_ROOT}/logs" "${TMP_ROOT}/homes"
TEST_PATH="${SHIM_DIR}:/usr/bin:/bin:/usr/sbin:/sbin"

BACKGROUND_PIDS=""
cleanup() {
  local pid
  for pid in $BACKGROUND_PIDS; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

PASSES=0
FAILURES=0
CASE_NO=0
STATUS=0
LOG=""
TEST_HOME=""
TEST_LANG="en"
EXTRA_ENV=()

pass() {
  PASSES=$((PASSES + 1))
  printf 'PASS: %s\n' "$1"
}

fail() {
  FAILURES=$((FAILURES + 1))
  printf 'FAIL: %s\n' "$1"
  if [ -n "$LOG" ] && [ -f "$LOG" ]; then
    sed 's/^/    | /' "$LOG"
  fi
}

# check LABEL COMMAND...: PASS when COMMAND succeeds.
check() {
  local label="$1"
  shift
  if "$@"; then pass "$label"; else fail "$label"; fi
}

# ---------------------------------------------------------------------------
# Snapshot of the real HOME paths the installer would touch
# ---------------------------------------------------------------------------

real_home_snapshot() {
  local path
  for path in "${REAL_HOME}/.local/bin/ltb" "${REAL_HOME}/Applications/${APP_NAME}"; do
    if [ -e "$path" ] || [ -L "$path" ]; then
      stat -f '%N %i %m' "$path" 2>/dev/null || printf '%s present\n' "$path"
    else
      printf '%s absent\n' "$path"
    fi
  done
}
REAL_HOME_BEFORE="$(real_home_snapshot)"

# ---------------------------------------------------------------------------
# Shims
# ---------------------------------------------------------------------------

write_shim() {
  local name="$1" body="$2"
  {
    printf '#!/bin/bash\n'
    printf 'printf "%%s\\n" "%s $*" >>"%s/%s.log"\n' "$name" "$CALLS" "$name"
    printf '%s\n' "$body"
  } >"${SHIM_DIR}/${name}"
  chmod 755 "${SHIM_DIR}/${name}"
}

# open: record only. osascript: simulate the app quitting when a fake app is
# "running" (its PID file exists). Everything else must never be called.
# The shim bodies are single-quoted on purpose: they expand when the shim runs.
write_shim open 'exit 0'
# shellcheck disable=SC2016
write_shim osascript 'if [ -f "$HOME/fake-app.pid" ]; then kill -TERM "$(cat "$HOME/fake-app.pid")" 2>/dev/null || true; fi
exit 0'
write_shim launchctl 'exit 97'
write_shim sudo 'exit 97'
write_shim git 'exit 97'
# shellcheck disable=SC2016
write_shim xcode-select 'if [ "${1:-}" = "-p" ]; then echo /Library/Developer/CommandLineTools; exit 0; fi
exit 97'

never_called_with() {
  ! grep -F -q -- "$2" "${CALLS}/$1.log" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# make_app DIR VERSION [BUNDLE_ID] [VERSION_EXIT] [CLI_OK] [EMBEDDED_PYTHON]
make_app() {
  local dir="$1" version="$2" bundle_id="${3:-$BUNDLE_ID}" version_exit="${4:-0}" cli_ok="${5:-1}" embedded="${6:-0}"
  local app="${dir}/${APP_NAME}"

  rm -rf "$app"
  mkdir -p "${app}/Contents/MacOS" "${app}/Contents/Resources/bin"
  cat >"${app}/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>LocalTasksBridge</string>
  <key>CFBundleIdentifier</key><string>${bundle_id}</string>
  <key>CFBundleName</key><string>Local Tasks Bridge</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${version}</string>
  <key>CFBundleVersion</key><string>${version}</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST

  # The fake app never shows UI: it answers --version, or idles when a test
  # needs a "running" copy, and refuses anything else.
  cat >"${app}/Contents/MacOS/LocalTasksBridge" <<APP
#!/bin/bash
case "\${1:-}" in
  --version)
    if [ "${version_exit}" -ne 0 ]; then echo "broken fixture" >&2; exit ${version_exit}; fi
    echo "Local Tasks Bridge ${version}"
    exit 0
    ;;
  --test-idle)
    echo "\$\$" >"\$HOME/fake-app.pid"
    sleep 60 &
    child=\$!
    trap 'kill "\$child" 2>/dev/null; rm -f "\$HOME/fake-app.pid"; exit 0' TERM
    wait "\$child"
    exit 0
    ;;
esac
echo "fake Local Tasks Bridge: no UI in tests" >&2
exit 64
APP

  cat >"${app}/Contents/Resources/bin/ltb" <<LTB
#!/bin/bash
printf '%s\n' "\$*" >>"\$HOME/ltb-calls.log"
case "\${1:-}" in
  version)
    if [ "${cli_ok}" -eq 1 ]; then printf '{"ok": true, "version": "%s"}\n' "${version}"; exit 0; fi
    echo "python missing" >&2
    exit 1
    ;;
  uninstall)
    exit "\${LTB_STUB_UNINSTALL_EXIT:-0}"
    ;;
esac
exit 0
LTB

  printf '%s\n' "$version" >"${app}/Contents/Resources/fixture-${version}.txt"
  if [ "$embedded" -eq 1 ]; then
    mkdir -p "${app}/Contents/Resources/python/bin"
    printf '#!/bin/bash\nexit 0\n' >"${app}/Contents/Resources/python/bin/python3"
    chmod 755 "${app}/Contents/Resources/python/bin/python3"
  fi
  chmod 755 "${app}/Contents/MacOS/LocalTasksBridge" "${app}/Contents/Resources/bin/ltb"
  # Ad-hoc signature, like the real builds; install.sh verifies it.
  codesign --force --sign - "$app" 2>/dev/null
}

# make_release DIR VERSION [make_app options...]: release-shaped directory with
# both arch zips and SHA256SUMS.
make_release() {
  local dir="$1" version="$2"
  shift 2
  mkdir -p "${dir}/stage"
  make_app "${dir}/stage" "$version" "$@"
  ditto -c -k --keepParent "${dir}/stage/${APP_NAME}" "${dir}/LocalTasksBridge-macos-arm64.zip"
  cp "${dir}/LocalTasksBridge-macos-arm64.zip" "${dir}/LocalTasksBridge-macos-x86_64.zip"
  (
    cd "$dir"
    shasum -a 256 LocalTasksBridge-macos-arm64.zip LocalTasksBridge-macos-x86_64.zip >SHA256SUMS
  )
  rm -rf "${dir}/stage"
}

corrupt_sums() {
  local sums="$1/SHA256SUMS" bad="0000000000000000000000000000000000000000000000000000000000000000"
  awk -v bad="$bad" '{ print bad "  " $2 }' "$sums" >"${sums}.new"
  mv "${sums}.new" "$sums"
}

quarantine() {
  xattr -w com.apple.quarantine "0083;$(printf '%x' "$(date +%s)");Safari;" "$1"
}

# ---------------------------------------------------------------------------
# Running the installer
# ---------------------------------------------------------------------------

new_home() {
  TEST_HOME="${TMP_ROOT}/homes/$1"
  mkdir -p "$TEST_HOME"
}

run_installer() {
  CASE_NO=$((CASE_NO + 1))
  LOG="${TMP_ROOT}/logs/case-${CASE_NO}.log"
  STATUS=0
  env -i HOME="$TEST_HOME" PATH="$TEST_PATH" TMPDIR="${TMP_ROOT}/tmp" SHELL=/bin/zsh \
    USER="${USER:-tester}" LTB_LANG="$TEST_LANG" ${EXTRA_ENV[@]+"${EXTRA_ENV[@]}"} \
    "$TEST_BASH" "$INSTALLER" "$@" >"$LOG" 2>&1 </dev/null || STATUS=$?
}

succeeded() { [ "$STATUS" -eq 0 ]; }
failed() { [ "$STATUS" -ne 0 ]; }
exited_with() { [ "$STATUS" -eq "$1" ]; }
output_has() { grep -F -q -- "$1" "$LOG"; }
output_lacks() { ! grep -F -q -- "$1" "$LOG"; }

app_version() {
  /usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$1/Contents/Info.plist" 2>/dev/null || true
}
app_id() {
  /usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$1/Contents/Info.plist" 2>/dev/null || true
}
version_is() { [ "$(app_version "$1")" = "$2" ]; }
id_is() { [ "$(app_id "$1")" = "$2" ]; }
no_quarantine() {
  local listing
  listing="$(xattr -r -l "$1" 2>/dev/null || true)"
  case "$listing" in
    *com.apple.quarantine*) return 1 ;;
  esac
  return 0
}
has_quarantine() { ! no_quarantine "$1"; }
link_points_to() { [ -L "$1" ] && [ "$(readlink "$1")" = "$2" ]; }
no_staging_left() {
  local leftovers
  leftovers="$(find "$1" -maxdepth 1 -name '.ltb-install.*' 2>/dev/null)"
  [ -z "$leftovers" ]
}
file_has() { [ -f "$1" ] && grep -F -q -- "$2" "$1"; }
missing() { [ ! -e "$1" ] && [ ! -L "$1" ]; }
ltb_runs() { env HOME="$TEST_HOME" "$1" version >/dev/null 2>&1; }

REL1="${FIXTURES}/release-1.0.0"
REL2="${FIXTURES}/release-1.0.1"
make_release "$REL1" 1.0.0
make_release "$REL2" 1.0.1

# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

new_home cli
run_installer --help
check "--help exits 0 and prints usage" succeeded
check "--help mentions --uninstall" output_has "--uninstall"
TEST_LANG=zh
run_installer --help
check "Chinese help with LTB_LANG=zh" output_has "用法："
TEST_LANG=en
run_installer --bogus
check "unknown option exits 2" exited_with 2
run_installer --revoke
check "--revoke without --uninstall is refused" exited_with 2
run_installer --zip x.zip --from-source
check "--zip together with --from-source is refused" exited_with 2
run_installer --version 1.0
check "malformed --version is refused" exited_with 2
run_installer --uninstall --zip x.zip
check "--uninstall together with --zip is refused" exited_with 2

# ---------------------------------------------------------------------------
# Fresh install from a quarantined zip
# ---------------------------------------------------------------------------

new_home main
APP="${TEST_HOME}/Applications/${APP_NAME}"
LINK="${TEST_HOME}/.local/bin/ltb"

QREL="${FIXTURES}/quarantined"
mkdir -p "${QREL}/stage"
make_app "${QREL}/stage" 1.0.0
quarantine "${QREL}/stage/${APP_NAME}/Contents/MacOS/LocalTasksBridge"
quarantine "${QREL}/stage/${APP_NAME}/Contents/Resources/bin/ltb"
ditto -c -k --keepParent "${QREL}/stage/${APP_NAME}" "${QREL}/LocalTasksBridge-macos-arm64.zip"
(cd "$QREL" && shasum -a 256 LocalTasksBridge-macos-arm64.zip >SHA256SUMS)
quarantine "${QREL}/LocalTasksBridge-macos-arm64.zip"
mkdir -p "${FIXTURES}/quarantine-probe"
ditto -x -k --noqtn "${QREL}/LocalTasksBridge-macos-arm64.zip" "${FIXTURES}/quarantine-probe"
check "fixture zip carries quarantined files (precondition)" has_quarantine "${FIXTURES}/quarantine-probe/${APP_NAME}"

run_installer --zip "${QREL}/LocalTasksBridge-macos-arm64.zip" --no-open
check "fresh install from --zip succeeds" succeeded
check "app is installed in ~/Applications" id_is "$APP" "$BUNDLE_ID"
check "installed version is 1.0.0" version_is "$APP" 1.0.0
check "checksum next to the zip was verified" output_has "Verified SHA-256 of LocalTasksBridge-macos-arm64.zip"
check "quarantine attribute removed" no_quarantine "$APP"
check "CLI symlink points into the app" link_points_to "$LINK" "${APP}/Contents/Resources/bin/ltb"
check "linked ltb runs" ltb_runs "$LINK"
# shellcheck disable=SC2016 # The hint is printed literally.
check "PATH hint printed when ~/.local/bin is not on PATH" output_has 'export PATH="$HOME/.local/bin:$PATH"'
check "no staging directory left behind" no_staging_left "${TEST_HOME}/Applications"
check "--no-open does not open the app" missing "${CALLS}/open.log"

# ---------------------------------------------------------------------------
# Update through the download path (file:// release URL)
# ---------------------------------------------------------------------------

EXTRA_ENV=(LTB_RELEASE_BASE_URL="file://${REL2}")
run_installer --no-open
check "update from the release URL succeeds" succeeded
check "app was replaced with 1.0.1" version_is "$APP" 1.0.1
check "files of the old version are gone" missing "${APP}/Contents/Resources/fixture-1.0.0.txt"
check "update is reported as 1.0.0 → 1.0.1" output_has "Updated Local Tasks Bridge 1.0.0 → 1.0.1"
check "CLI symlink still points into the app" link_points_to "$LINK" "${APP}/Contents/Resources/bin/ltb"
check "no staging directory left after the update" no_staging_left "${TEST_HOME}/Applications"

run_installer --no-open
check "reinstalling the same version is idempotent" succeeded
check "version is still 1.0.1 after the reinstall" version_is "$APP" 1.0.1

run_installer --no-open --version v1.0.1
check "--version matching the release succeeds" succeeded
run_installer --no-open --version v9.9.9
check "--version that does not match the bundle is refused" failed
check "mismatch is explained" output_has "Expected version 9.9.9"
check "app kept after a version mismatch" version_is "$APP" 1.0.1

# ---------------------------------------------------------------------------
# Refusals keep the installed app
# ---------------------------------------------------------------------------

BAD="${FIXTURES}/bad-checksum"
make_release "$BAD" 1.0.2
corrupt_sums "$BAD"
EXTRA_ENV=(LTB_RELEASE_BASE_URL="file://${BAD}")
run_installer --no-open
check "checksum mismatch on download is refused" failed
check "checksum mismatch is explained" output_has "Checksum mismatch"
check "old app kept after a checksum mismatch" version_is "$APP" 1.0.1
check "no staging directory left after a refusal" no_staging_left "${TEST_HOME}/Applications"
EXTRA_ENV=()

run_installer --zip "${BAD}/LocalTasksBridge-macos-arm64.zip" --no-open
check "checksum mismatch next to a local zip is refused" failed
check "old app kept after a local checksum mismatch" version_is "$APP" 1.0.1

NOENTRY="${FIXTURES}/no-entry"
make_release "$NOENTRY" 1.0.2
printf '%s  %s\n' "$(printf '%064d' 0)" "other-file.zip" >"${NOENTRY}/SHA256SUMS"
EXTRA_ENV=(LTB_RELEASE_BASE_URL="file://${NOENTRY}")
run_installer --no-open
check "SHA256SUMS without an entry for the zip is refused" failed
check "old app kept when SHA256SUMS has no entry" version_is "$APP" 1.0.1
EXTRA_ENV=()

WRONGID="${FIXTURES}/wrong-id"
make_release "$WRONGID" 1.0.2 com.example.not-ltb
run_installer --zip "${WRONGID}/LocalTasksBridge-macos-arm64.zip" --no-open
check "zip with a different bundle identifier is refused" failed
check "old app kept after a wrong bundle identifier" version_is "$APP" 1.0.1

BROKEN="${FIXTURES}/broken"
make_release "$BROKEN" 1.0.2 "$BUNDLE_ID" 1
run_installer --zip "${BROKEN}/LocalTasksBridge-macos-arm64.zip" --no-open
check "app whose --version fails is refused" failed
check "old app kept after a failed self-check" version_is "$APP" 1.0.1

BADCLI="${FIXTURES}/bad-cli"
make_release "$BADCLI" 1.0.2 "$BUNDLE_ID" 0 0 1
run_installer --zip "${BADCLI}/LocalTasksBridge-macos-arm64.zip" --no-open
check "app with embedded Python whose ltb fails is refused" failed
check "old app kept after a failed ltb self-check" version_is "$APP" 1.0.1

UNSIGNED="${FIXTURES}/tampered"
mkdir -p "${UNSIGNED}/stage"
make_app "${UNSIGNED}/stage" 1.0.2
printf 'changed after signing\n' >>"${UNSIGNED}/stage/${APP_NAME}/Contents/Resources/fixture-1.0.2.txt"
ditto -c -k --keepParent "${UNSIGNED}/stage/${APP_NAME}" "${UNSIGNED}/LocalTasksBridge-macos-arm64.zip"
run_installer --zip "${UNSIGNED}/LocalTasksBridge-macos-arm64.zip" --no-open
check "app modified after signing is refused" failed
check "invalid signature is explained" output_has "code signature is missing or invalid"
check "old app kept after an invalid signature" version_is "$APP" 1.0.1

NOPY="${FIXTURES}/no-python"
make_release "$NOPY" 1.0.2 "$BUNDLE_ID" 0 0 0
run_installer --zip "${NOPY}/LocalTasksBridge-macos-arm64.zip" --no-open
check "app without embedded Python installs even when ltb cannot find Python" succeeded
check "missing Python produces a warning" output_has "did not find Python"
check "version 1.0.2 installed" version_is "$APP" 1.0.2

# ---------------------------------------------------------------------------
# Quitting a running copy before replacing it
# ---------------------------------------------------------------------------

start_fake_app() {
  rm -f "${TEST_HOME}/fake-app.pid"
  HOME="$TEST_HOME" "${APP}/Contents/MacOS/LocalTasksBridge" --test-idle >/dev/null 2>&1 &
  FAKE_PID=$!
  BACKGROUND_PIDS="${BACKGROUND_PIDS} ${FAKE_PID}"
  local waited=0
  while [ ! -f "${TEST_HOME}/fake-app.pid" ] && [ "$waited" -lt 50 ]; do
    sleep 0.1
    waited=$((waited + 1))
  done
}
process_gone() {
  local state
  state="$(ps -p "$1" -o state= 2>/dev/null || true)"
  case "$state" in
    ''|Z*) return 0 ;;
  esac
  return 1
}

start_fake_app
run_installer --zip "${REL2}/LocalTasksBridge-macos-arm64.zip" --no-open
check "install succeeds while the app is running" succeeded
check "running app was asked to quit through its bundle identifier" file_has "${CALLS}/osascript.log" "tell application id \"${BUNDLE_ID}\" to quit"
check "running app exited before the swap" process_gone "$FAKE_PID"

# The osascript shim only stops processes that wrote a PID file; remove it so
# the installer has to fall back to SIGTERM.
start_fake_app
rm -f "${TEST_HOME}/fake-app.pid"
run_installer --zip "${REL2}/LocalTasksBridge-macos-arm64.zip" --no-open
check "install succeeds when the app ignores the quit request" succeeded
check "leftover process was terminated" process_gone "$FAKE_PID"

# ---------------------------------------------------------------------------
# Opening the app, CLI options, other locations
# ---------------------------------------------------------------------------

run_installer --zip "${REL2}/LocalTasksBridge-macos-arm64.zip"
check "install without --no-open succeeds" succeeded
check "app is opened after installing" file_has "${CALLS}/open.log" "open ${APP}"

new_home nocli
run_installer --zip "${REL1}/LocalTasksBridge-macos-arm64.zip" --no-open --no-cli
check "--no-cli install succeeds" succeeded
check "--no-cli creates no ltb link" missing "${TEST_HOME}/.local/bin/ltb"

new_home keep-own-ltb
mkdir -p "${TEST_HOME}/.local/bin"
printf '#!/bin/sh\necho mine\n' >"${TEST_HOME}/.local/bin/ltb"
run_installer --zip "${REL1}/LocalTasksBridge-macos-arm64.zip" --no-open
check "install succeeds next to an unrelated ltb file" succeeded
check "an existing ltb file is not replaced" file_has "${TEST_HOME}/.local/bin/ltb" "echo mine"

new_home on-path
EXTRA_ENV=(PATH="${TEST_HOME}/.local/bin:${TEST_PATH}")
run_installer --zip "${REL1}/LocalTasksBridge-macos-arm64.zip" --no-open
check "no PATH hint when ~/.local/bin is already on PATH" output_lacks "export PATH="
EXTRA_ENV=()

new_home custom-dest
CUSTOM="${TMP_ROOT}/Custom Apps"
run_installer --zip "${REL1}/LocalTasksBridge-macos-arm64.zip" --no-open --dest "$CUSTOM"
check "--dest installs into the given folder" id_is "${CUSTOM}/${APP_NAME}" "$BUNDLE_ID"
check "CLI link points into the custom folder" link_points_to "${TEST_HOME}/.local/bin/ltb" "${CUSTOM}/${APP_NAME}/Contents/Resources/bin/ltb"
check "nothing installed in ~/Applications with --dest" missing "${TEST_HOME}/Applications/${APP_NAME}"

new_home foreign
mkdir -p "${TEST_HOME}/Applications"
make_app "${TEST_HOME}/Applications" 5.0.0 com.example.other
run_installer --zip "${REL1}/LocalTasksBridge-macos-arm64.zip" --no-open
check "an unrelated app with the same name is not replaced" failed
check "the unrelated app is untouched" id_is "${TEST_HOME}/Applications/${APP_NAME}" com.example.other

new_home legacy
mkdir -p "${TEST_HOME}/Applications"
make_app "${TEST_HOME}/Applications" 1.0 local.reminders.tasks.bridge
run_installer --zip "${REL1}/LocalTasksBridge-macos-arm64.zip" --no-open
check "the earlier trial build is replaced" id_is "${TEST_HOME}/Applications/${APP_NAME}" "$BUNDLE_ID"
LEGACY_TRASHED="$(find "${TEST_HOME}/.Trash" -maxdepth 1 -name 'Local Tasks Bridge (trial build *).app' 2>/dev/null | head -n 1)"
check "the trial build was moved to the Trash" id_is "${LEGACY_TRASHED:-/nonexistent}" local.reminders.tasks.bridge

new_home piped
STATUS=0
LOG="${TMP_ROOT}/logs/piped.log"
env -i HOME="$TEST_HOME" PATH="$TEST_PATH" TMPDIR="${TMP_ROOT}/tmp" SHELL=/bin/zsh LTB_LANG=en \
  "$TEST_BASH" -s -- --zip "${REL1}/LocalTasksBridge-macos-arm64.zip" --no-open --no-cli \
  <"$INSTALLER" >"$LOG" 2>&1 || STATUS=$?
check "install works when the script is piped into bash" succeeded
check "piped install put the app in place" id_is "${TEST_HOME}/Applications/${APP_NAME}" "$BUNDLE_ID"

new_home chinese
TEST_LANG=zh
run_installer --zip "${REL1}/LocalTasksBridge-macos-arm64.zip" --no-open --no-cli
check "Chinese messages with LTB_LANG=zh" output_has "已安装 Local Tasks Bridge 1.0.0"
TEST_LANG=en

# ---------------------------------------------------------------------------
# --from-source with a stub build (no compiler, no network)
# ---------------------------------------------------------------------------

SRC="${FIXTURES}/source tree"
mkdir -p "${SRC}/scripts" "${SRC}/engine" "${FIXTURES}/prebuilt"
: >"${SRC}/engine/local_tasks_bridge.py"
make_app "${FIXTURES}/prebuilt" 1.0.0
cat >"${SRC}/scripts/build-app.sh" <<STUB
#!/bin/bash
set -euo pipefail
printf '%s\n' "\$*" >"\$HOME/build-app-args.log"
out=build
while [ "\$#" -gt 0 ]; do
  case "\$1" in
    --output) out="\$2"; shift ;;
  esac
  shift
done
mkdir -p "\$out"
ditto "${FIXTURES}/prebuilt/${APP_NAME}" "\$out/${APP_NAME}"
STUB
cat >"${SRC}/scripts/fetch-python.sh" <<'STUB'
#!/bin/bash
set -euo pipefail
printf '%s\n' "$*" >"$HOME/fetch-python-args.log"
out=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output) out="$2"; shift ;;
  esac
  shift
done
mkdir -p "$out/bin"
printf '%s\n' "$out"
STUB

new_home source
run_installer --from-source "$SRC" --embed-python --no-open --no-cli
check "--from-source DIR builds and installs" succeeded
check "source build installed the app" id_is "${TEST_HOME}/Applications/${APP_NAME}" "$BUNDLE_ID"
check "build-app.sh received --arch and --output" file_has "${TEST_HOME}/build-app-args.log" "--arch"
check "--embed-python passes --python to build-app.sh" file_has "${TEST_HOME}/build-app-args.log" "--python"
check "--embed-python runs fetch-python.sh" file_has "${TEST_HOME}/fetch-python-args.log" "--output"

run_installer --from-source "${FIXTURES}" --no-open
check "--from-source refuses a directory without build-app.sh" failed

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

TEST_HOME="${TMP_ROOT}/homes/main"
APP="${TEST_HOME}/Applications/${APP_NAME}"
LINK="${TEST_HOME}/.local/bin/ltb"
rm -f "${TEST_HOME}/ltb-calls.log"

if (: </dev/tty) 2>/dev/null; then
  printf 'SKIP: uninstall without --yes (a terminal is attached, so the installer would prompt)\n'
else
  run_installer --uninstall
  check "uninstall without --yes and without a terminal is refused" failed
  check "app kept when uninstall was not confirmed" id_is "$APP" "$BUNDLE_ID"
fi

EXTRA_ENV=(LTB_STUB_UNINSTALL_EXIT=3)
run_installer --uninstall --yes
check "failing 'ltb uninstall' stops the uninstaller" failed
check "app kept when 'ltb uninstall' fails" id_is "$APP" "$BUNDLE_ID"
check "CLI link kept when 'ltb uninstall' fails" link_points_to "$LINK" "${APP}/Contents/Resources/bin/ltb"
EXTRA_ENV=()

rm -f "${TEST_HOME}/ltb-calls.log"
run_installer --uninstall --yes --revoke --delete-data
check "uninstall succeeds" succeeded
check "uninstall passed --yes --revoke --delete-data to ltb" file_has "${TEST_HOME}/ltb-calls.log" "uninstall --yes --revoke --delete-data"
check "uninstall stopped the login item with ltb agent uninstall --bootout" file_has "${TEST_HOME}/ltb-calls.log" "agent uninstall --bootout --json"
check "uninstall removed the app" missing "$APP"
check "uninstall removed the CLI link" missing "$LINK"

run_installer --uninstall --yes
check "uninstalling again is a no-op" succeeded
check "second uninstall reports nothing to remove" output_has "is not installed"

TEST_HOME="${TMP_ROOT}/homes/custom-dest"
run_installer --uninstall --yes --dest "$CUSTOM"
check "uninstall with --dest removes the app there" missing "${CUSTOM}/${APP_NAME}"
check "uninstall with --dest removes the CLI link" missing "${TEST_HOME}/.local/bin/ltb"

# ---------------------------------------------------------------------------
# Global invariants
# ---------------------------------------------------------------------------

LOG=""
for tool in launchctl sudo git; do
  check "$tool was never called" missing "${CALLS}/${tool}.log"
done
check "xcode-select --install was never called" never_called_with xcode-select --install
check "real HOME was not touched" test "$(real_home_snapshot)" = "$REAL_HOME_BEFORE"

printf '\n%d passed, %d failed\n' "$PASSES" "$FAILURES"
[ "$FAILURES" -eq 0 ]
