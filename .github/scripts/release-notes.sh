#!/usr/bin/env bash
#
# Print the body of the "## [X.Y.Z]" section of CHANGELOG.md (Keep a Changelog
# format) so the release workflow can use it as the GitHub release notes.
#
# Usage: .github/scripts/release-notes.sh X.Y.Z [CHANGELOG.md]

set -euo pipefail

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  printf 'Usage: %s X.Y.Z [CHANGELOG.md]\n' "$0" >&2
  exit 2
fi
version="$1"
changelog="${2:-CHANGELOG.md}"
[ -f "$changelog" ] || { printf 'Error: %s not found.\n' "$changelog" >&2; exit 1; }

# Everything after the matching heading up to the next "## [" heading, without
# link reference definitions and leading blank lines.
notes="$(awk -v heading="## [${version}]" '
  index($0, "## [") == 1 {
    if (found) exit
    if (index($0, heading) == 1) { found = 1; next }
  }
  !found { next }
  /^\[[^]]+\]: / { next }
  !started && /^[[:space:]]*$/ { next }
  { started = 1; print }
' "$changelog")"

if [ -z "$notes" ]; then
  printf 'Error: %s has no non-empty "## [%s]" section.\n' "$changelog" "$version" >&2
  exit 1
fi
printf '%s\n' "$notes"
