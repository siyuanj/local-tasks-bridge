#!/usr/bin/env bash
#
# Self-test for scripts/check-release-source.sh. Builds throwaway Git
# repositories (a bare "remote" reached through url.<base>.insteadOf) in a
# temporary directory; never touches the network or the user's Git config.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
GATE="${SCRIPT_DIR}/check-release-source.sh"
EXPECTED_REPOSITORY="siyuanj/local-tasks-bridge"
EXPECTED_URL="https://github.com/${EXPECTED_REPOSITORY}.git"
FORK_REPOSITORY="example-fork/local-tasks-bridge"
FORK_URL="https://github.com/${FORK_REPOSITORY}.git"
TMP_PARENT="${TMPDIR:-/tmp}"
TMP_ROOT="$(mktemp -d "${TMP_PARENT%/}/ltb-release-gate.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT

# Isolate Git from the user's configuration (signing, hooks, default branch).
export HOME="${TMP_ROOT}/home"
export GIT_CONFIG_GLOBAL="${TMP_ROOT}/gitconfig"
export GIT_CONFIG_NOSYSTEM=1
export GIT_TERMINAL_PROMPT=0
unset DEPLOY_EXPECTED_COMMIT DEPLOY_GIT_ALLOW_DIRTY DEPLOY_GIT_ALLOW_NON_MAIN DEPLOY_GIT_ALLOW_UNPUSHED \
  DEPLOY_GIT_ALLOW_BOOTSTRAP DEPLOY_GIT_OVERRIDE_REASON LTB_EXPECTED_REPOSITORY
mkdir -p "$HOME"
: >"$GIT_CONFIG_GLOBAL"
git config --global init.defaultBranch main

REMOTE_DIR="${TMP_ROOT}/remote.git"
SOURCE_DIR="${TMP_ROOT}/source"
OTHER_DIR="${TMP_ROOT}/other-clone"
OUTPUT_PATH="${TMP_ROOT}/gate-output.txt"
REASON="release gate self-test"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  if [ -f "$OUTPUT_PATH" ]; then
    sed 's/^/    | /' "$OUTPUT_PATH" >&2
  fi
  exit 1
}

expect_pass() {
  local label="$1"
  shift
  if ! "$@" >"$OUTPUT_PATH" 2>&1; then
    fail "$label unexpectedly failed"
  fi
  printf 'PASS: %s\n' "$label"
}

expect_failure() {
  local label="$1"
  shift
  if "$@" >"$OUTPUT_PATH" 2>&1; then
    fail "$label unexpectedly passed"
  fi
  printf 'PASS (blocked): %s\n' "$label"
}

expect_output() {
  grep -F -q -- "$1" "$OUTPUT_PATH" || fail "expected output containing: $1"
}

gate() {
  env DEPLOY_EXPECTED_COMMIT="$1" "$GATE" --source-dir "$SOURCE_DIR"
}

git init --quiet --bare "$REMOTE_DIR"
git init --quiet "$SOURCE_DIR"
git -C "$SOURCE_DIR" config user.name "Release Gate Test"
git -C "$SOURCE_DIR" config user.email "release-gate@example.invalid"
git -C "$SOURCE_DIR" config commit.gpgsign false
git -C "$SOURCE_DIR" branch -M main
printf 'source\n' >"${SOURCE_DIR}/tracked.txt"
git -C "$SOURCE_DIR" add tracked.txt
git -C "$SOURCE_DIR" commit --quiet -m "Initial source"
git -C "$SOURCE_DIR" remote add origin "$EXPECTED_URL"
# Every GitHub URL used below resolves to the local bare repository.
git config --global --add "url.file://${REMOTE_DIR}.insteadOf" "$EXPECTED_URL"
git config --global --add "url.file://${REMOTE_DIR}.insteadOf" "git@github.com:${EXPECTED_REPOSITORY}.git"
git config --global --add "url.file://${REMOTE_DIR}.insteadOf" "https://github.com/SiyuanJ/Local-Tasks-Bridge"
git config --global --add "url.file://${REMOTE_DIR}.insteadOf" "$FORK_URL"
git -C "$SOURCE_DIR" push --quiet -u origin main

HEAD_COMMIT="$(git -C "$SOURCE_DIR" rev-parse HEAD)"

expect_pass "clean reviewed main" gate "$HEAD_COMMIT"
expect_output "Release source verified: repository=${EXPECTED_REPOSITORY} branch=main commit=${HEAD_COMMIT}"
expect_pass "upper-case expected commit" gate "$(printf '%s' "$HEAD_COMMIT" | tr '[:lower:]' '[:upper:]')"

expect_failure "missing expected commit" env -u DEPLOY_EXPECTED_COMMIT "$GATE" --source-dir "$SOURCE_DIR"
expect_failure "abbreviated expected commit" gate "${HEAD_COMMIT:0:12}"
expect_failure "non-hexadecimal expected commit" gate "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"
expect_failure "expected commit mismatch" gate "0000000000000000000000000000000000000000"
expect_output "does not match DEPLOY_EXPECTED_COMMIT"
expect_failure "invalid override flag value" env DEPLOY_GIT_ALLOW_DIRTY=yes DEPLOY_GIT_OVERRIDE_REASON="$REASON" \
  DEPLOY_EXPECTED_COMMIT="$HEAD_COMMIT" "$GATE" --source-dir "$SOURCE_DIR"
expect_failure "subdirectory instead of repository root" env DEPLOY_EXPECTED_COMMIT="$HEAD_COMMIT" \
  "$GATE" --source-dir "${SOURCE_DIR}/.git"
expect_failure "unknown option" env DEPLOY_EXPECTED_COMMIT="$HEAD_COMMIT" "$GATE" --source-dir "$SOURCE_DIR" --bogus

# The migration-bundle bootstrap mode was removed and must stay unusable.
expect_failure "removed --bootstrap-manifest option" env DEPLOY_EXPECTED_COMMIT="$HEAD_COMMIT" \
  "$GATE" --source-dir "$SOURCE_DIR" --bootstrap-manifest release-source.txt
expect_output "bootstrap was removed"
expect_failure "removed DEPLOY_GIT_ALLOW_BOOTSTRAP flag" env DEPLOY_GIT_ALLOW_BOOTSTRAP=1 \
  DEPLOY_GIT_OVERRIDE_REASON="$REASON" DEPLOY_EXPECTED_COMMIT="$HEAD_COMMIT" "$GATE" --source-dir "$SOURCE_DIR"

printf 'dirty\n' >>"${SOURCE_DIR}/tracked.txt"
expect_failure "dirty worktree" gate "$HEAD_COMMIT"
expect_output "Release source has tracked or untracked changes."
expect_failure "override without reason" env DEPLOY_EXPECTED_COMMIT="$HEAD_COMMIT" DEPLOY_GIT_ALLOW_DIRTY=1 \
  "$GATE" --source-dir "$SOURCE_DIR"
expect_output "DEPLOY_GIT_OVERRIDE_REASON is required"
expect_pass "audited dirty override" env DEPLOY_EXPECTED_COMMIT="$HEAD_COMMIT" DEPLOY_GIT_ALLOW_DIRTY=1 \
  DEPLOY_GIT_OVERRIDE_REASON="$REASON" "$GATE" --source-dir "$SOURCE_DIR"
expect_output "AUDIT OVERRIDE: dirty worktree; reason=${REASON}"
printf 'source\n' >"${SOURCE_DIR}/tracked.txt"

printf 'untracked\n' >"${SOURCE_DIR}/untracked.txt"
expect_failure "untracked file" gate "$HEAD_COMMIT"
rm -f "${SOURCE_DIR}/untracked.txt"

git -C "$SOURCE_DIR" checkout --quiet -b feature
expect_failure "non-main branch" gate "$HEAD_COMMIT"
expect_output "Release source must be on main, got: feature"
expect_pass "audited non-main override" env DEPLOY_EXPECTED_COMMIT="$HEAD_COMMIT" DEPLOY_GIT_ALLOW_NON_MAIN=1 \
  DEPLOY_GIT_OVERRIDE_REASON="$REASON" "$GATE" --source-dir "$SOURCE_DIR"
expect_output "AUDIT OVERRIDE: non-main branch feature"
git -C "$SOURCE_DIR" checkout --quiet --detach
expect_failure "detached HEAD" gate "$HEAD_COMMIT"
git -C "$SOURCE_DIR" checkout --quiet main

printf 'second\n' >>"${SOURCE_DIR}/tracked.txt"
git -C "$SOURCE_DIR" commit --quiet -am "Unpushed source"
UNPUSHED_COMMIT="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
expect_failure "unpushed commit" gate "$UNPUSHED_COMMIT"
expect_output "HEAD must match both local origin/main and live origin main."
expect_pass "audited unpushed override" env DEPLOY_EXPECTED_COMMIT="$UNPUSHED_COMMIT" DEPLOY_GIT_ALLOW_UNPUSHED=1 \
  DEPLOY_GIT_OVERRIDE_REASON="$REASON" "$GATE" --source-dir "$SOURCE_DIR"
expect_output "AUDIT OVERRIDE: HEAD differs from origin/main or live origin main"
git -C "$SOURCE_DIR" push --quiet origin main
expect_pass "pushed main" gate "$UNPUSHED_COMMIT"

# Someone else pushes to main: the live remote moves ahead of local origin/main.
git clone --quiet "$EXPECTED_URL" "$OTHER_DIR"
git -C "$OTHER_DIR" config user.name "Other Maintainer"
git -C "$OTHER_DIR" config user.email "other@example.invalid"
git -C "$OTHER_DIR" config commit.gpgsign false
printf 'remote change\n' >"${OTHER_DIR}/remote.txt"
git -C "$OTHER_DIR" add remote.txt
git -C "$OTHER_DIR" commit --quiet -m "Remote change"
git -C "$OTHER_DIR" push --quiet origin main
expect_failure "live origin main moved ahead" gate "$UNPUSHED_COMMIT"
expect_output "HEAD must match both local origin/main and live origin main."
git -C "$SOURCE_DIR" pull --quiet --ff-only origin main
LATEST_COMMIT="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
expect_pass "main updated to the live origin" gate "$LATEST_COMMIT"

git -C "$SOURCE_DIR" remote set-url origin "git@github.com:${EXPECTED_REPOSITORY}.git"
expect_pass "SSH origin URL" gate "$LATEST_COMMIT"
git -C "$SOURCE_DIR" remote set-url origin "https://github.com/SiyuanJ/Local-Tasks-Bridge"
expect_pass "origin URL with different letter case" gate "$LATEST_COMMIT"

git -C "$SOURCE_DIR" remote set-url origin "https://github.com/not-the-owner/not-this-repo.git"
expect_failure "unexpected origin" gate "$LATEST_COMMIT"
expect_output "origin must be ${EXPECTED_REPOSITORY}"
expect_failure "unexpected origin cannot be overridden" env DEPLOY_EXPECTED_COMMIT="$LATEST_COMMIT" \
  DEPLOY_GIT_ALLOW_DIRTY=1 DEPLOY_GIT_ALLOW_NON_MAIN=1 DEPLOY_GIT_ALLOW_UNPUSHED=1 \
  DEPLOY_GIT_OVERRIDE_REASON="$REASON" "$GATE" --source-dir "$SOURCE_DIR"
git -C "$SOURCE_DIR" remote set-url origin "https://gitlab.com/${EXPECTED_REPOSITORY}.git"
expect_failure "non-GitHub origin" gate "$LATEST_COMMIT"

# Forks configure their own repository.
git -C "$SOURCE_DIR" remote set-url origin "$FORK_URL"
expect_failure "fork origin with the default expected repository" gate "$LATEST_COMMIT"
expect_output "origin must be ${EXPECTED_REPOSITORY}, got: ${FORK_URL}"
expect_pass "fork origin with LTB_EXPECTED_REPOSITORY" env LTB_EXPECTED_REPOSITORY="$FORK_REPOSITORY" \
  DEPLOY_EXPECTED_COMMIT="$LATEST_COMMIT" "$GATE" --source-dir "$SOURCE_DIR"
expect_output "NOTICE: expected repository is ${FORK_REPOSITORY}"
expect_output "Release source verified: repository=${FORK_REPOSITORY}"
git -C "$SOURCE_DIR" remote set-url origin "$EXPECTED_URL"
expect_failure "upstream origin when a fork is expected" env LTB_EXPECTED_REPOSITORY="$FORK_REPOSITORY" \
  DEPLOY_EXPECTED_COMMIT="$LATEST_COMMIT" "$GATE" --source-dir "$SOURCE_DIR"
expect_failure "malformed LTB_EXPECTED_REPOSITORY" env LTB_EXPECTED_REPOSITORY="not a repository" \
  DEPLOY_EXPECTED_COMMIT="$LATEST_COMMIT" "$GATE" --source-dir "$SOURCE_DIR"
expect_output "LTB_EXPECTED_REPOSITORY must be a GitHub owner/name"
expect_failure "LTB_EXPECTED_REPOSITORY with a path" env LTB_EXPECTED_REPOSITORY="owner/name/extra" \
  DEPLOY_EXPECTED_COMMIT="$LATEST_COMMIT" "$GATE" --source-dir "$SOURCE_DIR"
expect_pass "LTB_EXPECTED_REPOSITORY with a .git suffix" env LTB_EXPECTED_REPOSITORY="${EXPECTED_REPOSITORY}.git" \
  DEPLOY_EXPECTED_COMMIT="$LATEST_COMMIT" "$GATE" --source-dir "$SOURCE_DIR"

printf 'Release source gate self-test passed.\n'
