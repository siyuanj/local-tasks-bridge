#!/bin/bash
#
# Build the release artifacts of Local Tasks Bridge:
#
#   dist/LocalTasksBridge-macos-<arch>.zip   the app with an embedded Python
#   dist/SHA256SUMS                          checksums that install.sh verifies
#   dist/release-manifest.json               what was built, from which commit, and how
#
# Usage: scripts/package-release.sh [--arch arm64|x86_64|all] [--output DIR]
#
# Optional environment (CI passes these from repository secrets):
#   LTB_OAUTH_CLIENT_JSON   contents of the shared Google OAuth "Desktop app" client
#   LTB_OAUTH_CLIENT_FILE   ...or the path to that JSON file (set only one of the two)
#   LTB_SIGN_IDENTITY       codesign identity; "-" (the default) means ad-hoc signing
#   LTB_NOTARIZE=1          notarize and staple; needs a Developer ID identity and
#                           APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD
#
# The OAuth client and Apple credentials are never printed.

set -euo pipefail

readonly BUNDLE_ID="io.github.siyuanj.LocalTasksBridge"
readonly APP_BUNDLE_NAME="Local Tasks Bridge.app"
readonly ASSET_PREFIX="LocalTasksBridge-macos"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
BUILD_ROOT="${REPO_ROOT}/build/release"
PYTHON_ROOT="${REPO_ROOT}/build/python"
DIST_DIR="${REPO_ROOT}/dist"
ARCH_CHOICE="all"
WORK_DIR=""

usage() {
  cat <<'USAGE'
Usage: scripts/package-release.sh [--arch arm64|x86_64|all] [--output DIR]

Builds "Local Tasks Bridge.app" with an embedded Python for each architecture
(default: all), then writes LocalTasksBridge-macos-<arch>.zip, SHA256SUMS, and
release-manifest.json into DIR (default: dist/).

Environment:
  LTB_OAUTH_CLIENT_JSON  shared Google OAuth Desktop client (JSON text), or
  LTB_OAUTH_CLIENT_FILE  path to it; without either, no shared client is embedded
  LTB_SIGN_IDENTITY      codesign identity (default "-", ad-hoc)
  LTB_NOTARIZE=1         notarize and staple (Developer ID identity plus
                         APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD required)
USAGE
}

log() {
  printf '==> %s\n' "$*" >&2
}

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  if [ -n "$WORK_DIR" ]; then
    rm -rf "$WORK_DIR"
  fi
}

plist_value() {
  /usr/libexec/PlistBuddy -c "Print :$2" "$1" 2>/dev/null
}

sha256_of() {
  shasum -a 256 "$1" | awk '{ print $1 }'
}

# Validate a Google OAuth client file without ever printing its contents.
validate_oauth_client() {
  local status=0
  python3 -I -B - "$1" >/dev/null 2>&1 <<'PY' || status=$?
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        data = json.load(handle)
except Exception:
    sys.exit(3)
if not isinstance(data, dict):
    sys.exit(4)
installed = data.get("installed")
if not isinstance(installed, dict):
    sys.exit(5)
client_id = installed.get("client_id")
if not isinstance(client_id, str) or not client_id.strip():
    sys.exit(6)
sys.exit(0)
PY
  case "$status" in
    0) return 0 ;;
    3|4) die "The shared OAuth client is not valid JSON." ;;
    5) die "The shared OAuth client must be a Google \"Desktop app\" client: an object with an \"installed\" key." ;;
    6) die "The shared OAuth client has no installed.client_id." ;;
    *) die "Could not validate the shared OAuth client (python3 exited with $status)." ;;
  esac
}

prepare_oauth_client() {
  local json="${LTB_OAUTH_CLIENT_JSON:-}" file="${LTB_OAUTH_CLIENT_FILE:-}"

  OAUTH_CLIENT_FILE=""
  if [ -n "$json" ] && [ -n "$file" ]; then
    die "Set only one of LTB_OAUTH_CLIENT_JSON and LTB_OAUTH_CLIENT_FILE."
  fi
  if [ -z "$json" ] && [ -z "$file" ]; then
    log "No shared OAuth client given: users sign in with their own Google Cloud client."
    return 0
  fi

  OAUTH_CLIENT_FILE="${WORK_DIR}/oauth_client.json"
  (
    umask 077
    if [ -n "$json" ]; then
      printf '%s' "$json" >"$OAUTH_CLIENT_FILE"
    else
      [ -f "$file" ] || die "LTB_OAUTH_CLIENT_FILE does not point to a file."
      cat -- "$file" >"$OAUTH_CLIENT_FILE"
    fi
  )
  chmod 600 "$OAUTH_CLIENT_FILE"
  validate_oauth_client "$OAUTH_CLIENT_FILE"
  log "Embedding the shared OAuth client (contents not shown)."
}

notarize_app() {
  local app="$1" arch="$2" zip result status submission

  zip="${WORK_DIR}/notarize-${arch}.zip"
  result="${WORK_DIR}/notarize-${arch}.json"
  log "Submitting the ${arch} app for notarization (this can take several minutes)"
  ditto -c -k --keepParent "$app" "$zip"
  if ! xcrun notarytool submit "$zip" \
    --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD" \
    --wait --timeout 45m --output-format json >"$result"; then
    die "notarytool submit failed for ${arch}."
  fi
  status="$(plutil -extract status raw -o - "$result" 2>/dev/null || true)"
  submission="$(plutil -extract id raw -o - "$result" 2>/dev/null || true)"
  if [ "$status" != "Accepted" ]; then
    if [ -n "$submission" ]; then
      xcrun notarytool log "$submission" \
        --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD" >&2 || true
    fi
    die "Notarization of the ${arch} app finished with status '${status:-unknown}'."
  fi
  xcrun stapler staple "$app" >&2
  xcrun stapler validate "$app" >&2
  spctl --assess --type execute --verbose=2 "$app" >&2
  rm -f "$zip"
}

# require_arch FILE ARCH: FILE must be a Mach-O binary that contains ARCH.
require_arch() {
  local archs
  [ -x "$1" ] || die "Missing $1"
  archs="$(lipo -archs "$1" 2>/dev/null || true)"
  case " $archs " in
    *" $2 "*) ;;
    *) die "$1 is built for '${archs}', not $2." ;;
  esac
}

# can_run_arch ARCH: succeeds when this Mac can execute ARCH binaries.
can_run_arch() {
  local host
  host="$(uname -m)"
  if [ "$(sysctl -in sysctl.proc_translated 2>/dev/null || true)" = "1" ]; then
    host="arm64"
  fi
  [ "$host" = "$1" ] && return 0
  [ "$host" = "arm64" ] && [ "$1" = "x86_64" ] && [ -e /Library/Apple/usr/libexec/oah/libRosettaRuntime ]
}

verify_app() {
  local app="$1" arch="$2" id version details helper

  [ -d "$app" ] || die "build-app.sh did not produce $app"
  id="$(plist_value "$app/Contents/Info.plist" CFBundleIdentifier || true)"
  [ "$id" = "$BUNDLE_ID" ] || die "Unexpected bundle identifier '${id}' in $app"
  version="$(plist_value "$app/Contents/Info.plist" CFBundleShortVersionString || true)"
  [ "$version" = "$VERSION" ] || die "The app reports version '${version}', expected ${VERSION}."

  require_arch "$app/Contents/MacOS/LocalTasksBridge" "$arch"
  for helper in ltb-reminders-export ltb-reminders-apply; do
    require_arch "$app/Contents/MacOS/$helper" "$arch"
  done
  require_arch "$app/Contents/Resources/python/bin/python3" "$arch"
  [ -x "$app/Contents/Resources/bin/ltb" ] || die "Contents/Resources/bin/ltb is missing from $app"
  [ -f "$app/Contents/Resources/engine/local_tasks_bridge.py" ] || die "The engine is missing from $app"
  if [ -n "$OAUTH_CLIENT_FILE" ]; then
    [ -f "$app/Contents/Resources/oauth_client.json" ] || die "The shared OAuth client was not embedded in $app"
  elif [ -e "$app/Contents/Resources/oauth_client.json" ]; then
    die "$app contains an OAuth client although none was given."
  fi

  codesign --verify --strict --deep "$app" || die "codesign verification failed for $app"
  if [ "$SIGNING" = "developer-id" ]; then
    details="$(codesign -dvv "$app" 2>&1 || true)"
    case "$details" in
      *"Authority=Developer ID Application:"*) ;;
      *) die "$app is not signed with a Developer ID Application certificate." ;;
    esac
  fi
}

# Run the app, the embedded Python, and the CLI when this Mac can execute the
# architecture. The checks run on a copy (so nothing can change the signed
# bundle) with a throwaway HOME (so the builder's own settings are untouched).
smoke_test_app() {
  local original="$1" arch="$2" python_version="$3" home="${WORK_DIR}/home" app output

  if ! can_run_arch "$arch"; then
    log "Skipping the ${arch} smoke test: this Mac cannot run ${arch} code."
    return 0
  fi
  mkdir -p "$home" "${WORK_DIR}/smoke-${arch}"
  app="${WORK_DIR}/smoke-${arch}/${APP_BUNDLE_NAME}"
  ditto "$original" "$app"
  output="$(env HOME="$home" "$app/Contents/MacOS/LocalTasksBridge" --version </dev/null 2>&1)" ||
    die "LocalTasksBridge --version failed for ${arch}."
  case "$output" in
    *"$VERSION"*) ;;
    *) die "LocalTasksBridge --version printed '${output}', expected ${VERSION}." ;;
  esac
  env -i HOME="$home" PATH=/usr/bin:/bin "$app/Contents/Resources/python/bin/python3" -I -B -c \
    'import ssl, sqlite3, json, urllib.request, _scproxy' </dev/null ||
    die "The embedded Python of the ${arch} app failed its import check."
  output="$(env HOME="$home" LTB_PYTHON= "$app/Contents/Resources/bin/ltb" version --json </dev/null)" ||
    die "ltb version --json failed for ${arch}."
  python3 -I -B -c '
import json, sys
data = json.loads(sys.argv[1])
assert data.get("ok") is True, data
assert data.get("version") == sys.argv[2], data
assert data.get("python") == sys.argv[3], data
' "$output" "$VERSION" "$python_version" ||
    die "ltb version --json did not report ${VERSION} running on the embedded Python ${python_version}: ${output}"
  log "Smoke test passed for ${arch}: ${output}"
}

write_manifest() {
  local manifest="$1"
  shift
  python3 -I -B - "$manifest" "$@" <<'PY'
import datetime
import json
import os
import sys

manifest_path, *rows = sys.argv[1:]
files = []
for row in rows:
    name, arch, sha256, size = row.split("|")
    files.append({"name": name, "arch": arch, "sha256": sha256, "size": int(size)})
env = os.environ
manifest = {
    "name": "Local Tasks Bridge",
    "version": env["MANIFEST_VERSION"],
    "git_commit": env["MANIFEST_COMMIT"],
    "git_dirty": env["MANIFEST_DIRTY"] == "true",
    "built_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
    "bundle_id": env["MANIFEST_BUNDLE_ID"],
    "minimum_macos": env["MANIFEST_MINIMUM_MACOS"],
    "python": {
        "version": env["MANIFEST_PYTHON_VERSION"],
        "python_build_standalone_release": env["MANIFEST_PBS_RELEASE"],
    },
    "shared_oauth_client_embedded": env["MANIFEST_OAUTH"] == "true",
    "signing": env["MANIFEST_SIGNING"],
    "notarized": env["MANIFEST_NOTARIZED"] == "true",
    "files": files,
}
with open(manifest_path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2)
    handle.write("\n")
PY
}

main() {
  local engine_version commit dirty arch app py_dir out_dir zip name sha size
  local minimum_macos="" python_version="" pbs_release="" notarized="false" oauth_embedded="false"
  local version_re='^[0-9]+\.[0-9]+\.[0-9]+$'
  local -a archs=() rows=() build_args=()

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --arch|--output)
        [ "$#" -ge 2 ] || die "$1 needs a value."
        case "$1" in
          --arch) ARCH_CHOICE="$2" ;;
          --output) DIST_DIR="$2" ;;
        esac
        shift
        ;;
      -h|--help) usage; exit 0 ;;
      *) usage >&2; die "Unknown option: $1" ;;
    esac
    shift
  done

  case "$ARCH_CHOICE" in
    all) archs=(arm64 x86_64) ;;
    arm64|x86_64) archs=("$ARCH_CHOICE") ;;
    *) die "--arch must be arm64, x86_64, or all." ;;
  esac

  [ "$(uname -s)" = "Darwin" ] || die "Releases are built on macOS."
  [ -x "${SCRIPT_DIR}/build-app.sh" ] || [ -f "${SCRIPT_DIR}/build-app.sh" ] || die "scripts/build-app.sh is missing."
  command -v python3 >/dev/null 2>&1 || die "python3 is required to validate inputs and write the manifest."

  VERSION="$(tr -d ' \t\r\n' <"${REPO_ROOT}/VERSION")"
  [[ $VERSION =~ $version_re ]] || die "VERSION must contain X.Y.Z, got '${VERSION}'."
  engine_version="$(sed -n 's/^__version__ = "\([^"]*\)".*/\1/p' "${REPO_ROOT}/engine/local_tasks_bridge.py" | head -n 1)"
  [ "$engine_version" = "$VERSION" ] ||
    die "VERSION is ${VERSION} but engine/local_tasks_bridge.py says __version__ = \"${engine_version}\"."

  SIGN_IDENTITY="${LTB_SIGN_IDENTITY:--}"
  if [ "$SIGN_IDENTITY" = "-" ]; then
    SIGNING="adhoc"
  else
    SIGNING="developer-id"
  fi
  case "${LTB_NOTARIZE:-0}" in
    0|"") NOTARIZE=0 ;;
    1) NOTARIZE=1 ;;
    *) die "LTB_NOTARIZE must be 0 or 1." ;;
  esac
  if [ "$NOTARIZE" -eq 1 ]; then
    [ "$SIGNING" = "developer-id" ] || die "Notarization needs a Developer ID identity in LTB_SIGN_IDENTITY."
    if [ -z "${APPLE_ID:-}" ] || [ -z "${APPLE_TEAM_ID:-}" ] || [ -z "${APPLE_APP_PASSWORD:-}" ]; then
      die "Notarization needs APPLE_ID, APPLE_TEAM_ID, and APPLE_APP_PASSWORD."
    fi
    notarized="true"
  fi

  if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    commit="$(git -C "$REPO_ROOT" rev-parse HEAD)"
    if [ -n "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=normal)" ]; then
      dirty="true"
      log "Warning: the worktree has uncommitted changes; the manifest records git_dirty=true."
    else
      dirty="false"
    fi
  else
    commit="${GITHUB_SHA:-unknown}"
    dirty="false"
  fi

  trap cleanup EXIT
  WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ltb-package.XXXXXX")"
  prepare_oauth_client
  if [ -n "$OAUTH_CLIENT_FILE" ]; then
    oauth_embedded="true"
  fi

  mkdir -p "$DIST_DIR"
  DIST_DIR="$(cd "$DIST_DIR" && pwd -P)"
  rm -f "${DIST_DIR}/${ASSET_PREFIX}-"*.zip "${DIST_DIR}/SHA256SUMS" "${DIST_DIR}/release-manifest.json"

  for arch in "${archs[@]}"; do
    log "Packaging Local Tasks Bridge ${VERSION} for ${arch} (signing: ${SIGNING})"
    py_dir="${PYTHON_ROOT}/${arch}"
    /bin/bash "${SCRIPT_DIR}/fetch-python.sh" --arch "$arch" --output "$py_dir" >/dev/null
    python_version="$(sed -n 's/^python_version=//p' "${py_dir}/LTB-PYTHON.txt")"
    pbs_release="$(sed -n 's/^python_build_standalone_release=//p' "${py_dir}/LTB-PYTHON.txt")"

    out_dir="${BUILD_ROOT}/${arch}"
    rm -rf "$out_dir"
    mkdir -p "$out_dir"
    build_args=(--output "$out_dir" --arch "$arch" --python "$py_dir" --version "$VERSION")
    # build-app.sh signs ad hoc by default; --sign selects a Developer ID
    # identity (hardened runtime and secure timestamp).
    if [ "$SIGNING" = "developer-id" ]; then
      build_args+=(--sign "$SIGN_IDENTITY")
    fi
    if [ -n "$OAUTH_CLIENT_FILE" ]; then
      build_args+=(--oauth-client "$OAUTH_CLIENT_FILE")
    fi
    /bin/bash "${SCRIPT_DIR}/build-app.sh" "${build_args[@]}"

    app="${out_dir}/${APP_BUNDLE_NAME}"
    verify_app "$app" "$arch"
    smoke_test_app "$app" "$arch" "$python_version"
    minimum_macos="$(plist_value "$app/Contents/Info.plist" LSMinimumSystemVersion || true)"
    if [ "$NOTARIZE" -eq 1 ]; then
      notarize_app "$app" "$arch"
    fi
    codesign --verify --strict --deep "$app" || die "The ${arch} app changed after it was signed."

    name="${ASSET_PREFIX}-${arch}.zip"
    zip="${DIST_DIR}/${name}"
    ditto -c -k --keepParent "$app" "$zip"
    sha="$(sha256_of "$zip")"
    size="$(wc -c <"$zip" | tr -d ' ')"
    rows+=("${name}|${arch}|${sha}|${size}")
    log "Wrote ${zip}"
  done

  (
    cd "$DIST_DIR"
    shasum -a 256 "${ASSET_PREFIX}-"*.zip >SHA256SUMS
  )
  MANIFEST_VERSION="$VERSION" MANIFEST_COMMIT="$commit" MANIFEST_DIRTY="$dirty" \
    MANIFEST_BUNDLE_ID="$BUNDLE_ID" MANIFEST_MINIMUM_MACOS="$minimum_macos" \
    MANIFEST_PYTHON_VERSION="$python_version" MANIFEST_PBS_RELEASE="$pbs_release" \
    MANIFEST_OAUTH="$oauth_embedded" MANIFEST_SIGNING="$SIGNING" MANIFEST_NOTARIZED="$notarized" \
    write_manifest "${DIST_DIR}/release-manifest.json" "${rows[@]}"

  log "Release artifacts in ${DIST_DIR}:"
  (cd "$DIST_DIR" && ls -l "${ASSET_PREFIX}-"*.zip SHA256SUMS release-manifest.json) >&2
  cat "${DIST_DIR}/SHA256SUMS" >&2
}

main "$@"
