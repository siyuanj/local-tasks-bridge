#!/usr/bin/env bash
#
# Fail-closed maintainer gate: verify that a release is cut from reviewed,
# pushed main of the expected GitHub repository.
#
# Run it before tagging a release:
#
#   DEPLOY_EXPECTED_COMMIT=<full-reviewed-sha> scripts/check-release-source.sh

set -euo pipefail

readonly DEFAULT_REPOSITORY="siyuanj/local-tasks-bridge"
readonly EXPECTED_BRANCH="main"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SOURCE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd -P)"

usage() {
  cat <<'USAGE'
Usage:
  DEPLOY_EXPECTED_COMMIT=<full-sha> bash scripts/check-release-source.sh [--source-dir DIR]

Options:
  --source-dir DIR  Git checkout to verify. Defaults to the repository root.
  -h, --help        Show this help.

A release source must be a clean main checkout whose HEAD equals local
origin/main, the live origin main ref, and DEPLOY_EXPECTED_COMMIT (mandatory,
the full 40-character SHA you reviewed). origin must point to the expected
GitHub repository.

Configuration:
  LTB_EXPECTED_REPOSITORY  GitHub owner/name that origin must point to
                           (default siyuanj/local-tasks-bridge). Forks set
                           their own repository here.

Emergency overrides (each needs a non-empty DEPLOY_GIT_OVERRIDE_REASON and is
reported as an AUDIT OVERRIDE line):
  DEPLOY_GIT_ALLOW_DIRTY=1     allow tracked or untracked changes
  DEPLOY_GIT_ALLOW_NON_MAIN=1  allow another branch or a detached HEAD
  DEPLOY_GIT_ALLOW_UNPUSHED=1  allow HEAD to differ from origin/main

There is no override for the origin check.
USAGE
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

warn_override() {
  printf 'AUDIT OVERRIDE: %s; reason=%s\n' "$1" "$DEPLOY_GIT_OVERRIDE_REASON" >&2
}

validate_flag() {
  case "$2" in
    0|1) ;;
    *) die "$1 must be 0 or 1." ;;
  esac
}

lowercase() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

# Print owner/name for a GitHub remote URL, or fail for anything else.
origin_repository() {
  local url="$1" repository

  case "$url" in
    https://github.com/*) repository="${url#https://github.com/}" ;;
    git@github.com:*) repository="${url#git@github.com:}" ;;
    ssh://git@github.com/*) repository="${url#ssh://git@github.com/}" ;;
    *) return 1 ;;
  esac
  repository="${repository%/}"
  repository="${repository%.git}"
  printf '%s\n' "$repository"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --source-dir)
      shift
      [ "$#" -gt 0 ] || die "--source-dir requires a value."
      [ -d "$1" ] || die "Source directory does not exist: $1"
      SOURCE_DIR="$(cd "$1" && pwd -P)"
      ;;
    --bootstrap-manifest|--bootstrap-manifest=*)
      die "Migration-bundle bootstrap was removed; releases are verified from a Git checkout only."
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
  shift
done

ALLOW_DIRTY="${DEPLOY_GIT_ALLOW_DIRTY:-0}"
ALLOW_NON_MAIN="${DEPLOY_GIT_ALLOW_NON_MAIN:-0}"
ALLOW_UNPUSHED="${DEPLOY_GIT_ALLOW_UNPUSHED:-0}"
DEPLOY_GIT_OVERRIDE_REASON="${DEPLOY_GIT_OVERRIDE_REASON:-}"
EXPECTED_COMMIT="${DEPLOY_EXPECTED_COMMIT:-}"
EXPECTED_REPOSITORY="${LTB_EXPECTED_REPOSITORY:-$DEFAULT_REPOSITORY}"
REPOSITORY_PATTERN='^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$'

case "${DEPLOY_GIT_ALLOW_BOOTSTRAP:-}" in
  ''|0) ;;
  *) die "DEPLOY_GIT_ALLOW_BOOTSTRAP is no longer supported: migration-bundle bootstrap was removed." ;;
esac

validate_flag DEPLOY_GIT_ALLOW_DIRTY "$ALLOW_DIRTY"
validate_flag DEPLOY_GIT_ALLOW_NON_MAIN "$ALLOW_NON_MAIN"
validate_flag DEPLOY_GIT_ALLOW_UNPUSHED "$ALLOW_UNPUSHED"

if [ "$ALLOW_DIRTY" -eq 1 ] || [ "$ALLOW_NON_MAIN" -eq 1 ] || [ "$ALLOW_UNPUSHED" -eq 1 ]; then
  [ -n "$DEPLOY_GIT_OVERRIDE_REASON" ] || die "DEPLOY_GIT_OVERRIDE_REASON is required when an override is enabled."
fi

EXPECTED_REPOSITORY="${EXPECTED_REPOSITORY%.git}"
[[ $EXPECTED_REPOSITORY =~ $REPOSITORY_PATTERN ]] ||
  die "LTB_EXPECTED_REPOSITORY must be a GitHub owner/name, got: ${EXPECTED_REPOSITORY}"
if [ "$(lowercase "$EXPECTED_REPOSITORY")" != "$(lowercase "$DEFAULT_REPOSITORY")" ]; then
  printf 'NOTICE: expected repository is %s (from LTB_EXPECTED_REPOSITORY)\n' "$EXPECTED_REPOSITORY" >&2
fi

[ -n "$EXPECTED_COMMIT" ] || die "DEPLOY_EXPECTED_COMMIT must contain the full reviewed commit SHA."
case "$EXPECTED_COMMIT" in
  *[!0-9a-fA-F]*) die "DEPLOY_EXPECTED_COMMIT must be a hexadecimal full commit SHA." ;;
esac
[ "${#EXPECTED_COMMIT}" -eq 40 ] || die "DEPLOY_EXPECTED_COMMIT must be the full 40-character commit SHA."
EXPECTED_COMMIT="$(lowercase "$EXPECTED_COMMIT")"

git -C "$SOURCE_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "Source is not a Git worktree: $SOURCE_DIR"
GIT_ROOT="$(git -C "$SOURCE_DIR" rev-parse --show-toplevel)"
GIT_ROOT="$(cd "$GIT_ROOT" && pwd -P)"
[ "$GIT_ROOT" = "$SOURCE_DIR" ] || die "Source directory must be the repository root: $GIT_ROOT"

ORIGIN_URL="$(git -C "$SOURCE_DIR" config --get remote.origin.url 2>/dev/null || true)"
[ -n "$ORIGIN_URL" ] || die "origin is not configured."
ORIGIN_REPOSITORY="$(origin_repository "$ORIGIN_URL" || true)"
# GitHub owner and repository names are case-insensitive.
[ "$(lowercase "$ORIGIN_REPOSITORY")" = "$(lowercase "$EXPECTED_REPOSITORY")" ] ||
  die "origin must be ${EXPECTED_REPOSITORY}, got: ${ORIGIN_URL}"

HEAD_COMMIT="$(lowercase "$(git -C "$SOURCE_DIR" rev-parse HEAD)")"
[ "$HEAD_COMMIT" = "$EXPECTED_COMMIT" ] || die "HEAD ${HEAD_COMMIT} does not match DEPLOY_EXPECTED_COMMIT ${EXPECTED_COMMIT}."

CURRENT_BRANCH="$(git -C "$SOURCE_DIR" branch --show-current)"
if [ "$CURRENT_BRANCH" != "$EXPECTED_BRANCH" ]; then
  [ "$ALLOW_NON_MAIN" -eq 1 ] || die "Release source must be on ${EXPECTED_BRANCH}, got: ${CURRENT_BRANCH:-detached HEAD}"
  warn_override "non-main branch ${CURRENT_BRANCH:-detached HEAD}"
fi

WORKTREE_STATUS="$(git -C "$SOURCE_DIR" status --porcelain --untracked-files=all)"
if [ -n "$WORKTREE_STATUS" ]; then
  [ "$ALLOW_DIRTY" -eq 1 ] || die "Release source has tracked or untracked changes."
  warn_override "dirty worktree"
fi

ORIGIN_MAIN="$(git -C "$SOURCE_DIR" rev-parse --verify refs/remotes/origin/main 2>/dev/null || true)"
REMOTE_MAIN="$(git -C "$SOURCE_DIR" ls-remote --exit-code origin refs/heads/main 2>/dev/null | awk 'NR == 1 {print $1}' || true)"
ORIGIN_MAIN="$(lowercase "$ORIGIN_MAIN")"
REMOTE_MAIN="$(lowercase "$REMOTE_MAIN")"

if [ "$ORIGIN_MAIN" != "$HEAD_COMMIT" ] || [ "$REMOTE_MAIN" != "$HEAD_COMMIT" ]; then
  [ "$ALLOW_UNPUSHED" -eq 1 ] || die "HEAD must match both local origin/main and live origin main."
  warn_override "HEAD differs from origin/main or live origin main"
fi

printf 'Release source verified: repository=%s branch=%s commit=%s\n' \
  "$EXPECTED_REPOSITORY" "${CURRENT_BRANCH:-detached}" "$HEAD_COMMIT"
