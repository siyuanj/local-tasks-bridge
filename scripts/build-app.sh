#!/bin/bash
# Builds "Local Tasks Bridge.app" with the Xcode Command Line Tools only
# (swiftc, no Xcode project or SwiftPM). The bundle layout is described in
# docs/app-engine-contract.md, section 1.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/build-app.sh [options]

  --output DIR          Where to put "Local Tasks Bridge.app" (default: build/)
  --arch ARCH           arm64, x86_64, or universal (default: this Mac's architecture)
  --python DIR          Embed this CPython (python-build-standalone layout with
                        bin/python3) as Contents/Resources/python
  --oauth-client FILE   Embed the shared Google OAuth "Desktop app" client JSON as
                        Contents/Resources/oauth_client.json (release builds only)
  --sign IDENTITY       Sign with this Developer ID identity, hardened runtime and
                        secure timestamp (default: ad-hoc signature)
  --version X.Y.Z       Version to write into Info.plist (default: VERSION file,
                        else __version__ from engine/local_tasks_bridge.py)
  -h, --help            Show this help

Prints the path of the finished bundle on stdout.
EOF
}

die() {
    printf 'build-app: %s\n' "$*" >&2
    exit 1
}

step() {
    printf '==> %s\n' "$*" >&2
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output="$repo_root/build"
arch=""
python_dir=""
oauth_client=""
sign_identity=""
version=""

while [ $# -gt 0 ]; do
    case "$1" in
        -h | --help)
            usage
            exit 0
            ;;
        --output | --arch | --python | --oauth-client | --sign | --version)
            if [ $# -lt 2 ] || [ -z "$2" ]; then
                die "$1 needs a value"
            fi
            case "$1" in
                --output) output="$2" ;;
                --arch) arch="$2" ;;
                --python) python_dir="$2" ;;
                --oauth-client) oauth_client="$2" ;;
                --sign) sign_identity="$2" ;;
                --version) version="$2" ;;
            esac
            shift 2
            ;;
        *)
            usage >&2
            die "unknown option: $1"
            ;;
    esac
done

# "-" is codesign's spelling of an ad-hoc signature.
if [ "$sign_identity" = "-" ]; then
    sign_identity=""
fi

for tool in swiftc swift codesign iconutil plutil ditto file; do
    command -v "$tool" >/dev/null 2>&1 || die "$tool not found; install the Xcode Command Line Tools (xcode-select --install)"
done

# --- Inputs -------------------------------------------------------------------

if [ -z "$version" ]; then
    if [ -f "$repo_root/VERSION" ]; then
        version="$(tr -d '[:space:]' <"$repo_root/VERSION")"
    else
        version="$(sed -n 's/^__version__ = "\([^"]*\)".*/\1/p' "$repo_root/engine/local_tasks_bridge.py" | head -n 1)"
    fi
fi
printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || die "version must look like 1.2.3 (got '$version')"

[ -n "$arch" ] || arch="$(uname -m)"
case "$arch" in
    arm64 | x86_64) arches="$arch" ;;
    universal) arches="arm64 x86_64" ;;
    *) die "--arch must be arm64, x86_64, or universal (got '$arch')" ;;
esac
if [ "$arch" = "universal" ]; then
    command -v lipo >/dev/null 2>&1 || die "lipo not found"
fi

if [ -n "$python_dir" ]; then
    [ -d "$python_dir" ] || die "--python: $python_dir is not a directory"
    [ -x "$python_dir/bin/python3" ] || die "--python: $python_dir/bin/python3 is missing or not executable"
fi

if [ -n "$oauth_client" ]; then
    [ -f "$oauth_client" ] || die "--oauth-client: file not found"
    # Validate the shape without ever printing the file's contents.
    command -v python3 >/dev/null 2>&1 || die "--oauth-client needs python3 to validate the file"
    python3 - "$oauth_client" <<'PY' || die "--oauth-client: not a Google OAuth \"Desktop app\" client JSON ({\"installed\": {...}})"
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    document = json.load(handle)
installed = document.get("installed") if isinstance(document, dict) else None
client_id = installed.get("client_id") if isinstance(installed, dict) else None
sys.exit(0 if isinstance(client_id, str) and client_id.endswith(".apps.googleusercontent.com") else 1)
PY
fi

entitlements="$repo_root/macos/Resources/LocalTasksBridge.entitlements"
sdk="$(xcrun --show-sdk-path 2>/dev/null || echo /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk)"
[ -d "$sdk" ] || die "macOS SDK not found at $sdk"

mkdir -p "$output"
output="$(cd "$output" && pwd)"
bundle="$output/Local Tasks Bridge.app"
contents="$bundle/Contents"
work="$(mktemp -d "${TMPDIR:-/tmp}/ltb-build.XXXXXX")"
trap 'rm -rf "$work"' EXIT

# --- Compile ------------------------------------------------------------------

# compile_swift OUTPUT MODULE "FRAMEWORKS" SOURCE...
compile_swift() {
    local destination="$1" module="$2" frameworks="$3"
    shift 3
    local framework_flags="" framework slices="" slice
    for framework in $frameworks; do
        framework_flags="$framework_flags -framework $framework"
    done
    for slice in $arches; do
        # $framework_flags is intentionally split into words.
        # shellcheck disable=SC2086
        swiftc -swift-version 5 -O -whole-module-optimization \
            -target "$slice-apple-macos13.0" -sdk "$sdk" \
            -module-name "$module" $framework_flags \
            -o "$work/$module.$slice" "$@"
        slices="$slices $work/$module.$slice"
    done
    if [ "$arch" = "universal" ]; then
        # shellcheck disable=SC2086
        lipo -create -output "$destination" $slices
    else
        cp "$work/$module.$arch" "$destination"
    fi
    chmod 0755 "$destination"
}

step "Building Local Tasks Bridge $version ($arch)"
rm -rf "$bundle"
mkdir -p "$contents/MacOS" "$contents/Resources/engine" "$contents/Resources/bin"

step "Compiling the menu bar app"
compile_swift "$contents/MacOS/LocalTasksBridge" LocalTasksBridge "AppKit SwiftUI EventKit UserNotifications" \
    "$repo_root"/macos/App/*.swift

step "Compiling the Reminders helpers"
compile_swift "$contents/MacOS/ltb-reminders-export" LTBRemindersExport "Foundation EventKit" \
    "$repo_root/macos/Helpers/RemindersExport.swift"
compile_swift "$contents/MacOS/ltb-reminders-apply" LTBRemindersApply "Foundation EventKit" \
    "$repo_root/macos/Helpers/RemindersApply.swift"

# --- Resources ----------------------------------------------------------------

step "Copying resources"
sed "s/__LTB_VERSION__/$version/g" "$repo_root/macos/Resources/Info.plist" >"$contents/Info.plist"
plutil -lint -s "$contents/Info.plist" || die "Info.plist is not valid"
printf 'APPL????' >"$contents/PkgInfo"

install -m 0644 "$repo_root/engine/local_tasks_bridge.py" "$contents/Resources/engine/local_tasks_bridge.py"
install -m 0755 "$repo_root/macos/Resources/bin/ltb" "$contents/Resources/bin/ltb"
for lproj in "$repo_root"/macos/Resources/*.lproj; do
    for strings in "$lproj"/*.strings; do
        plutil -lint -s "$strings" || die "$strings is not valid"
    done
    ditto "$lproj" "$contents/Resources/$(basename "$lproj")"
done

step "Rendering the app icon"
swift "$repo_root/macos/Tools/make-icon.swift" "$work/AppIcon.iconset"
iconutil -c icns "$work/AppIcon.iconset" -o "$contents/Resources/AppIcon.icns"

if [ -n "$python_dir" ]; then
    step "Embedding Python from $python_dir"
    ditto "$python_dir" "$contents/Resources/python"
    embedded_python="$contents/Resources/python/bin/python3"
    python_archs="$(lipo -archs "$embedded_python" 2>/dev/null || true)"
    case " $python_archs " in
        *" $(uname -m) "*)
            "$embedded_python" -I -B -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
                || die "the embedded Python must be 3.9 or newer"
            ;;
        *)
            # For example an x86_64 Python on Apple silicon without Rosetta;
            # scripts/fetch-python.sh already verified the download.
            printf 'note: not running the embedded Python (%s) on this %s Mac\n' "$python_archs" "$(uname -m)"
            ;;
    esac
fi

if [ -n "$oauth_client" ]; then
    step "Embedding the shared OAuth client"
    install -m 0644 "$oauth_client" "$contents/Resources/oauth_client.json"
fi

# Finder metadata or resource forks would make codesign refuse the bundle.
xattr -cr "$bundle" 2>/dev/null || true

# --- Sign ---------------------------------------------------------------------

# sign_code [--entitlements] PATH...
sign_code() {
    local with_entitlements=""
    if [ "$1" = "--entitlements" ]; then
        with_entitlements=1
        shift
    fi
    if [ -z "$sign_identity" ]; then
        codesign --force --sign - "$@"
    elif [ -n "$with_entitlements" ]; then
        codesign --force --sign "$sign_identity" --options runtime --timestamp --entitlements "$entitlements" "$@"
    else
        codesign --force --sign "$sign_identity" --options runtime --timestamp "$@"
    fi
}

if [ -n "$sign_identity" ]; then
    step "Signing with \"$sign_identity\" (hardened runtime)"
else
    step "Signing ad hoc"
fi

if [ -d "$contents/Resources/python" ]; then
    # Inside out: every Mach-O file of the embedded Python before the app seals it.
    python_code=()
    while IFS= read -r -d '' candidate; do
        case "$candidate" in
            *.py | *.pyc | *.pyi | *.txt | *.h | *.json | *.html | *.css | *.js | *.png | *.gif | *.xml | *.pem | *.exe) continue ;;
        esac
        case "$(file -b "$candidate")" in
            *Mach-O*) python_code+=("$candidate") ;;
        esac
    done < <(find "$contents/Resources/python" -type f -print0)
    index=0
    while [ "$index" -lt "${#python_code[@]}" ]; do
        sign_code "${python_code[@]:$index:50}"
        index=$((index + 50))
    done
fi

for helper in ltb-reminders-export ltb-reminders-apply; do
    sign_code --entitlements --identifier "io.github.siyuanj.LocalTasksBridge.$helper" "$contents/MacOS/$helper"
done
sign_code --entitlements "$bundle"

codesign --verify --strict --deep "$bundle" || die "signature verification failed"

step "Built $(du -sh "$bundle" | cut -f1 | tr -d '[:space:]') bundle"
printf '%s\n' "$bundle"
