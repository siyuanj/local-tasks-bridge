#!/bin/bash
#
# Render the Homebrew cask from packaging/homebrew/local-tasks-bridge.rb with a
# release version and the sha256 values from that release's SHA256SUMS.
#
# Usage: packaging/homebrew/update-cask.sh [--version X.Y.Z] [--sums FILE] [--output FILE]
#
#   --version  release version (default: the VERSION file)
#   --sums     SHA256SUMS of the release (default: dist/SHA256SUMS)
#   --output   where to write the cask (default: dist/local-tasks-bridge.rb)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
TEMPLATE="${SCRIPT_DIR}/local-tasks-bridge.rb"
VERSION=""
SUMS="${REPO_ROOT}/dist/SHA256SUMS"
OUTPUT="${REPO_ROOT}/dist/local-tasks-bridge.rb"

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

usage() {
  sed -n '3,10s/^# \{0,1\}//p' "${BASH_SOURCE[0]}"
}

# sha_for NAME: the sha256 of NAME in $SUMS.
sha_for() {
  local value
  value="$(awk -v name="$1" '$2 == name || $2 == ("*" name) { print tolower($1); exit }' "$SUMS")"
  case "$value" in
    ''|*[!0-9a-f]*) die "$SUMS has no valid sha256 for $1." ;;
  esac
  [ "${#value}" -eq 64 ] || die "$SUMS has no valid sha256 for $1."
  printf '%s\n' "$value"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version|--sums|--output)
      [ "$#" -ge 2 ] || die "$1 needs a value."
      case "$1" in
        --version) VERSION="${2#v}" ;;
        --sums) SUMS="$2" ;;
        --output) OUTPUT="$2" ;;
      esac
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
  shift
done

if [ -z "$VERSION" ]; then
  VERSION="$(tr -d ' \t\r\n' <"${REPO_ROOT}/VERSION")"
fi
version_re='^[0-9]+\.[0-9]+\.[0-9]+$'
[[ $VERSION =~ $version_re ]] || die "The version must look like 1.2.3, got '${VERSION}'."
[ -f "$SUMS" ] || die "SHA256SUMS not found: $SUMS"
[ -f "$TEMPLATE" ] || die "Template not found: $TEMPLATE"

SHA_ARM64="$(sha_for LocalTasksBridge-macos-arm64.zip)"
SHA_X86_64="$(sha_for LocalTasksBridge-macos-x86_64.zip)"

mkdir -p "$(dirname "$OUTPUT")"
partial="${OUTPUT}.partial"
sed -e "s/@VERSION@/${VERSION}/g" \
  -e "s/@SHA256_ARM64@/${SHA_ARM64}/g" \
  -e "s/@SHA256_X86_64@/${SHA_X86_64}/g" \
  "$TEMPLATE" >"$partial"
if grep -Eq '@(VERSION|SHA256_[A-Z0-9_]+)@' "$partial"; then
  rm -f "$partial"
  die "Some template values were not filled in."
fi
if command -v ruby >/dev/null 2>&1; then
  ruby -c "$partial" >/dev/null || { rm -f "$partial"; die "The rendered cask is not valid Ruby."; }
fi
mv "$partial" "$OUTPUT"
printf 'Wrote %s (version %s)\n' "$OUTPUT" "$VERSION"
