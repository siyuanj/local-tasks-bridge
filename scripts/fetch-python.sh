#!/bin/bash
#
# Download, verify, and prune the private CPython that release builds embed
# as "Local Tasks Bridge.app/Contents/Resources/python".
#
# The interpreter comes from python-build-standalone (a relocatable CPython
# build). Release, version, and SHA-256 values are pinned below; change them
# together after checking the new release's SHA256SUMS.
#
# Usage: scripts/fetch-python.sh --arch arm64|x86_64 --output DIR [--cache-dir DIR]
#
# Progress goes to stderr; the absolute output directory is printed on stdout.

set -euo pipefail

readonly PBS_RELEASE="20260929"
readonly PYTHON_VERSION="3.13.15"
readonly PYTHON_MINOR="3.13"
readonly SHA256_AARCH64="d66c67f16148c7454b1509c32747175f7669c8b8e105b97b92a0000d66af6e6e"
readonly SHA256_X86_64="73b503a2d3f47f0601265d7936744b77dc4ee75d2a3e88a470594a014dcf6822"
readonly BASE_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_RELEASE}"
readonly MARKER_NAME="LTB-PYTHON.txt"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"

ARCH=""
OUTPUT_DIR=""
CACHE_DIR="${LTB_CACHE_DIR:-${REPO_ROOT}/build/cache}"
WORK_DIR=""

usage() {
  cat <<'USAGE'
Usage: scripts/fetch-python.sh --arch arm64|x86_64 --output DIR [--cache-dir DIR]

Downloads CPython 3.13.15 (python-build-standalone 20260929, install_only_stripped)
for the given architecture, verifies its pinned SHA-256, extracts it into DIR,
removes everything the engine never needs, and precompiles the standard library
into unchecked-hash .pyc files so the interpreter never writes into the signed
app bundle. When this Mac can run that architecture, it then checks that ssl,
sqlite3, json, urllib.request, and _scproxy import and that the engine loads.

Downloads are cached in build/cache (or --cache-dir, or $LTB_CACHE_DIR). DIR
must be missing, empty, or a previous output of this script.

The absolute path of DIR is printed on stdout.
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

sha256_of() {
  shasum -a 256 "$1" | awk '{ print $1 }'
}

absolute_path() {
  local path="$1" parent
  parent="$(dirname "$path")"
  mkdir -p "$parent"
  printf '%s/%s\n' "$(cd "$parent" && pwd -P)" "$(basename "$path")"
}

# The native architecture of this Mac (also when this shell runs under Rosetta).
host_arch() {
  if [ "$(sysctl -in sysctl.proc_translated 2>/dev/null || true)" = "1" ]; then
    printf 'arm64\n'
  else
    uname -m
  fi
}

# can_run_arch ARCH: succeeds when this Mac can execute ARCH binaries.
can_run_arch() {
  local host
  host="$(host_arch)"
  [ "$host" = "$1" ] && return 0
  # Apple silicon runs x86_64 code only when Rosetta 2 is installed.
  [ "$host" = "arm64" ] && [ "$1" = "x86_64" ] && [ -e /Library/Apple/usr/libexec/oah/libRosettaRuntime ]
}

# runner_for ARCH: the command prefix that runs ARCH code on this Mac.
runner_for() {
  if [ "$1" != "$(host_arch)" ]; then
    printf 'arch -%s\n' "$1"
  fi
}

# ensure_archive ARCH: reuse or download the archive for ARCH and verify its
# pinned SHA-256. Sets TRIPLE, EXPECTED_SHA, ARCHIVE, ARCHIVE_NAME, ARCHIVE_URL.
ensure_archive() {
  local actual partial

  case "$1" in
    arm64) TRIPLE="aarch64-apple-darwin"; EXPECTED_SHA="$SHA256_AARCH64" ;;
    x86_64) TRIPLE="x86_64-apple-darwin"; EXPECTED_SHA="$SHA256_X86_64" ;;
    *) die "Unsupported architecture: $1" ;;
  esac
  ARCHIVE_NAME="cpython-${PYTHON_VERSION}+${PBS_RELEASE}-${TRIPLE}-install_only_stripped.tar.gz"
  ARCHIVE_URL="${BASE_URL}/cpython-${PYTHON_VERSION}%2B${PBS_RELEASE}-${TRIPLE}-install_only_stripped.tar.gz"
  ARCHIVE="${CACHE_DIR}/${ARCHIVE_NAME}"

  if [ -f "$ARCHIVE" ]; then
    actual="$(sha256_of "$ARCHIVE")"
    if [ "$actual" = "$EXPECTED_SHA" ]; then
      log "Using cached $ARCHIVE_NAME (SHA-256 verified)"
      return 0
    fi
    log "Cached $ARCHIVE_NAME has the wrong SHA-256; downloading it again."
    rm -f "$ARCHIVE"
  fi

  log "Downloading $ARCHIVE_NAME"
  partial="$(mktemp "${CACHE_DIR}/.download.XXXXXX")"
  if ! curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
    --proto '=https' --proto-redir '=https' --tlsv1.2 --output "$partial" "$ARCHIVE_URL"; then
    rm -f "$partial"
    die "Download failed: $ARCHIVE_URL"
  fi
  actual="$(sha256_of "$partial")"
  if [ "$actual" != "$EXPECTED_SHA" ]; then
    rm -f "$partial"
    die "SHA-256 mismatch for $ARCHIVE_NAME: expected $EXPECTED_SHA, got $actual."
  fi
  mv "$partial" "$ARCHIVE"
  log "Verified SHA-256 $EXPECTED_SHA"
}

prune() {
  local root="$1" stdlib="$1/lib/python${PYTHON_MINOR}"

  [ -d "$stdlib" ] || die "Unexpected archive layout: $stdlib is missing."

  # Headers, man pages, pkg-config files, and the shared libpython: the app
  # runs bin/python3, which links the interpreter statically and never loads
  # libpython. Nothing in the bundle builds or embeds Python.
  rm -rf "$root/include" "$root/share" "$root/lib/pkgconfig" "$root/lib/libpython"*.dylib

  # Tcl/Tk and their extensions (only tkinter uses them).
  rm -rf "$root/lib/"libtcl* "$root/lib/"libtk* "$root/lib/"tcl[0-9]* "$root/lib/"tk[0-9]* \
    "$root/lib/"itcl* "$root/lib/"thread[0-9]*

  # Command-line tools the engine never runs.
  rm -f "$root/bin/"idle* "$root/bin/"pip* "$root/bin/"pydoc* "$root/bin/"*-config

  # Standard-library parts the engine never imports.
  rm -rf "$stdlib/idlelib" "$stdlib/tkinter" "$stdlib/turtledemo" "$stdlib/turtle.py" \
    "$stdlib/ensurepip" "$stdlib/pydoc_data" "$stdlib/test" "$stdlib/"config-*-darwin
  rm -f "$stdlib/lib-dynload/"_tkinter*
  find "$stdlib" -depth -type d \( -name test -o -name tests -o -name idle_test \) -exec rm -rf {} +

  # Third-party packages (pip) are never used; keep the empty directory.
  if [ -d "$stdlib/site-packages" ]; then
    find "$stdlib/site-packages" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  fi
}

# Precompile the standard library into unchecked-hash .pyc files (PEP 552).
# Python never rewrites those, so running the embedded interpreter, even
# without -B, cannot add or change files inside the signed app bundle.
# Bytecode does not depend on the CPU, so a cross build uses this Mac's own
# Python of the same version to compile it.
compile_bytecode() {
  local root="$1" arch="$2" compiler runner

  find "$root" -name __pycache__ -type d -prune -exec rm -rf {} +
  if can_run_arch "$arch"; then
    compiler="$root/bin/python3"
    runner="$(runner_for "$arch")"
  else
    log "Compiling bytecode with the $(host_arch) Python ${PYTHON_VERSION}"
    ensure_archive "$(host_arch)"
    mkdir -p "$WORK_DIR/compiler"
    tar -xzf "$ARCHIVE" -C "$WORK_DIR/compiler"
    compiler="$WORK_DIR/compiler/python/bin/python3"
    runner=""
  fi
  # Word splitting of $runner is intended ("arch -x86_64" or nothing).
  # shellcheck disable=SC2086
  # -s keeps the build directory out of the .pyc files (Python reports the
  # real location when it loads them), so builds are reproducible.
  env -i HOME="${HOME:-/tmp}" PATH=/usr/bin:/bin $runner "$compiler" -I -B -m compileall -q -j 0 \
    --invalidation-mode unchecked-hash -s "$root" "$root/lib/python${PYTHON_MINOR}" >&2 ||
    die "Compiling the standard library failed."
}

verify_python() {
  local root="$1" arch="$2" python="$1/bin/python3" runner before after
  local check='import sys
import ssl, sqlite3, json, urllib.request, _scproxy
assert sys.version_info[:3] == tuple(int(part) for part in sys.argv[1].split(".")), sys.version
context = ssl.create_default_context()
assert context.cert_store_stats()["x509_ca"] > 0, "no CA certificates are available"
print("Python %d.%d.%d, %s, SQLite %s" % (sys.version_info[:3] + (ssl.OPENSSL_VERSION, sqlite3.sqlite_version)))'

  [ -x "$python" ] || die "$python is missing after extraction."
  if ! can_run_arch "$arch"; then
    log "Skipping the import check: this Mac cannot run $arch code."
    return 0
  fi
  runner="$(runner_for "$arch")"
  # Run without -B on purpose: nothing may be written into the tree.
  before="$(find "$root" | LC_ALL=C sort | shasum -a 256)"
  # Word splitting of $runner is intended ("arch -x86_64" or nothing).
  # shellcheck disable=SC2086
  env -i HOME="${HOME:-/tmp}" PATH=/usr/bin:/bin $runner "$python" -I -c "$check" "$PYTHON_VERSION" >&2 ||
    die "The extracted Python failed the import check."
  after="$(find "$root" | LC_ALL=C sort | shasum -a 256)"
  [ "$before" = "$after" ] || die "Running the embedded Python wrote files into it; the bytecode is incomplete."
  if [ -f "${REPO_ROOT}/engine/local_tasks_bridge.py" ]; then
    # shellcheck disable=SC2086
    env -i HOME="${HOME:-/tmp}" PATH=/usr/bin:/bin $runner "$python" -I -B -c \
      'import sys; sys.path.insert(0, sys.argv[1]); import local_tasks_bridge' "${REPO_ROOT}/engine" ||
      die "The pruned Python cannot import engine/local_tasks_bridge.py."
    log "The engine imports cleanly with the pruned Python."
  fi
}

main() {
  local triple expected filename url archive staging size

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --arch|--output|--cache-dir)
        [ "$#" -ge 2 ] || die "$1 needs a value."
        case "$1" in
          --arch) ARCH="$2" ;;
          --output) OUTPUT_DIR="$2" ;;
          --cache-dir) CACHE_DIR="$2" ;;
        esac
        shift
        ;;
      -h|--help) usage; exit 0 ;;
      *) usage >&2; die "Unknown option: $1" ;;
    esac
    shift
  done

  case "$ARCH" in
    arm64|x86_64) ;;
    *) usage >&2; die "--arch must be arm64 or x86_64." ;;
  esac
  [ -n "$OUTPUT_DIR" ] || { usage >&2; die "--output is required."; }

  OUTPUT_DIR="$(absolute_path "$OUTPUT_DIR")"
  case "$OUTPUT_DIR" in
    /|"$HOME"|"$REPO_ROOT") die "Refusing to use $OUTPUT_DIR as the output directory." ;;
  esac
  if [ -e "$OUTPUT_DIR" ]; then
    [ -d "$OUTPUT_DIR" ] || die "$OUTPUT_DIR exists and is not a directory."
    if [ -n "$(ls -A "$OUTPUT_DIR")" ] && [ ! -f "$OUTPUT_DIR/$MARKER_NAME" ]; then
      die "$OUTPUT_DIR is not empty and was not created by this script; choose another --output."
    fi
  fi

  trap cleanup EXIT
  mkdir -p "$CACHE_DIR"
  CACHE_DIR="$(cd "$CACHE_DIR" && pwd -P)"
  ensure_archive "$ARCH"
  triple="$TRIPLE"
  expected="$EXPECTED_SHA"
  filename="$ARCHIVE_NAME"
  url="$ARCHIVE_URL"
  archive="$ARCHIVE"

  WORK_DIR="$(mktemp -d "$(dirname "$OUTPUT_DIR")/.fetch-python.XXXXXX")"
  tar -xzf "$archive" -C "$WORK_DIR"
  staging="$WORK_DIR/python"
  [ -x "$staging/bin/python${PYTHON_MINOR}" ] || die "Unexpected archive layout: python/bin/python${PYTHON_MINOR} is missing."

  log "Pruning files the engine never needs"
  prune "$staging"
  log "Precompiling the standard library"
  compile_bytecode "$staging" "$ARCH"
  {
    printf 'python_version=%s\n' "$PYTHON_VERSION"
    printf 'python_build_standalone_release=%s\n' "$PBS_RELEASE"
    printf 'target=%s\n' "$triple"
    printf 'archive=%s\n' "$filename"
    printf 'archive_sha256=%s\n' "$expected"
    printf 'source=%s\n' "$url"
  } >"$staging/$MARKER_NAME"

  verify_python "$staging" "$ARCH"

  rm -rf "$OUTPUT_DIR"
  mv "$staging" "$OUTPUT_DIR"
  size="$(du -sh "$OUTPUT_DIR" | awk '{ print $1 }')"
  log "Python ${PYTHON_VERSION} for ${ARCH} is ready (${size}): $OUTPUT_DIR"
  printf '%s\n' "$OUTPUT_DIR"
}

main "$@"
