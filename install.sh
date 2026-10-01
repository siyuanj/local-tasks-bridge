#!/bin/bash
#
# Install, update, or remove Local Tasks Bridge on this Mac.
#
#   curl -fsSL https://raw.githubusercontent.com/siyuanj/local-tasks-bridge/main/install.sh | bash
#
# Pass options through the pipe after `bash -s --`, for example:
#
#   curl -fsSL https://raw.githubusercontent.com/siyuanj/local-tasks-bridge/main/install.sh | bash -s -- --version v1.0.0
#
# Run with --help for every option. The installer never uses sudo and refuses
# to run as root. All work happens in main(), which is called on the last line,
# so a partially downloaded copy of this script does nothing.

set -euo pipefail

readonly DEFAULT_REPOSITORY="siyuanj/local-tasks-bridge"
readonly APP_BUNDLE_NAME="Local Tasks Bridge.app"
readonly BUNDLE_ID="io.github.siyuanj.LocalTasksBridge"
# The 2026-09 private trial used the same app name with this identifier. Such a
# bundle may be replaced; it is moved to the Trash instead of being deleted.
readonly LEGACY_BUNDLE_ID="local.reminders.tasks.bridge"
readonly LAUNCH_AGENT_LABEL="io.github.siyuanj.local-tasks-bridge"
readonly ASSET_PREFIX="LocalTasksBridge-macos"
readonly MIN_MACOS_MAJOR=13

# Options.
MODE=""                 # release | zip | source | uninstall
REQUESTED_VERSION=""    # X.Y.Z, without the leading "v"
ZIP_PATH=""
SOURCE_DIR=""
DEST_DIR=""
INSTALL_CLI=1
OPEN_APP=1
EMBED_PYTHON=0
ASSUME_YES=0
REVOKE=0
DELETE_DATA=0

# Runtime state.
UI_LANG="en"
REPOSITORY="$DEFAULT_REPOSITORY"
SYSTEM_APPS_DIR="/Applications"
HOST_ARCH=""
WORK_DIR=""
STAGING_DIR=""
KEEP_STAGING=0
TARGET_APP=""
BACKUP_APP=""
EXISTING_KIND="none"    # none | current | legacy
EXISTING_VERSION=""
ZIP_FILE=""
BUILT_APP=""
NEW_VERSION=""

# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

detect_language() {
  local preferred locale
  case "${LTB_LANG:-}" in
    zh*) UI_LANG="zh"; return 0 ;;
    en*) UI_LANG="en"; return 0 ;;
  esac
  preferred=""
  if command -v defaults >/dev/null 2>&1; then
    preferred="$(defaults read -g AppleLanguages 2>/dev/null | tr -d ' \t",()' | sed '/^$/d' | head -n 1 || true)"
  fi
  locale="${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}"
  case "$preferred" in
    zh*) UI_LANG="zh" ;;
    *)
      case "$locale" in
        zh*) UI_LANG="zh" ;;
        *) UI_LANG="en" ;;
      esac
      ;;
  esac
}

# say ENGLISH CHINESE: print the message in the user's language.
say() {
  if [ "$UI_LANG" = "zh" ]; then
    printf '%s\n' "$2"
  else
    printf '%s\n' "$1"
  fi
}

step() {
  say "==> $1" "==> $2"
}

warn() {
  say "Warning: $1" "警告：$2" >&2
}

die() {
  say "Error: $1" "错误：$2" >&2
  exit 1
}

usage_error() {
  say "Error: $1" "错误：$2" >&2
  say "Run with --help to see the options." "使用 --help 查看所有选项。" >&2
  exit 2
}

usage() {
  if [ "$UI_LANG" = "zh" ]; then
    cat <<'USAGE'
安装、更新或卸载 Local Tasks Bridge（在本机同步 Apple 提醒事项与 Google Tasks）。

用法：
  curl -fsSL https://raw.githubusercontent.com/siyuanj/local-tasks-bridge/main/install.sh | bash
  curl -fsSL https://raw.githubusercontent.com/siyuanj/local-tasks-bridge/main/install.sh | bash -s -- [选项]
  ./install.sh [选项]

选项：
  --version vX.Y.Z     安装指定版本，而不是最新版本。
  --dest 目录          安装到该文件夹。不指定时，会就地更新已安装的副本（~/Applications
                       或 /Applications）；首次安装默认放在 ~/Applications。
  --zip 路径           从已下载的发布 zip 安装；如果 zip 旁边有 SHA256SUMS，会先校验。
  --from-source [目录] 从源代码构建（默认：本安装脚本所在的源代码目录，否则重新克隆）。
                       需要 Xcode Command Line Tools。
  --embed-python       与 --from-source 一起使用：在 App 内附带独立的 Python 3.13。
  --no-cli             不在 ~/.local/bin 中创建 ltb 命令链接。
  --no-open            安装后不自动打开 App。
  --uninstall          卸载 App、登录项和 ltb 命令链接。除非加上 --delete-data，
                       设置和同步数据会保留。
  --yes                与 --uninstall 一起使用：不再询问确认。
  --revoke             与 --uninstall 一起使用：同时撤销 Google 授权。
  --delete-data        与 --uninstall 一起使用：同时删除设置、同步对应关系和日志。
  -h, --help           显示本帮助。

环境变量：
  LTB_RELEASE_BASE_URL 从这个地址下载发布文件（zip 与 SHA256SUMS），而不是 GitHub。
  LTB_REPOSITORY       用于下载和克隆的 GitHub 仓库（默认 siyuanj/local-tasks-bridge）。
  LTB_LANG             安装程序的语言：en 或 zh。
  https_proxy          下载使用的代理（curl 不使用 macOS 系统代理），例如 http://127.0.0.1:7890。

安装程序从不使用 sudo，也不能以 root 身份运行。
USAGE
  else
    cat <<'USAGE'
Install, update, or remove Local Tasks Bridge (local-first sync between
Apple Reminders and Google Tasks).

Usage:
  curl -fsSL https://raw.githubusercontent.com/siyuanj/local-tasks-bridge/main/install.sh | bash
  curl -fsSL https://raw.githubusercontent.com/siyuanj/local-tasks-bridge/main/install.sh | bash -s -- [options]
  ./install.sh [options]

Options:
  --version vX.Y.Z     Install this release instead of the latest one.
  --dest DIR           Install into the folder DIR. Without --dest an existing copy
                       is updated where it is (~/Applications or /Applications);
                       a first install goes to ~/Applications.
  --zip PATH           Install a downloaded release zip. A SHA256SUMS file next to
                       the zip is verified when present.
  --from-source [DIR]  Build from source (default: the checkout that contains this
                       installer, otherwise a fresh clone). Needs the Xcode Command
                       Line Tools.
  --embed-python       With --from-source: bundle a private Python 3.13 in the app.
  --no-cli             Do not link the ltb command into ~/.local/bin.
  --no-open            Do not open the app after installing.
  --uninstall          Remove the app, its login item, and the ltb link. Settings
                       and sync data are kept unless you add --delete-data.
  --yes                With --uninstall: do not ask for confirmation.
  --revoke             With --uninstall: also revoke the Google sign-in.
  --delete-data        With --uninstall: also delete settings, the sync map, and logs.
  -h, --help           Show this help.

Environment:
  LTB_RELEASE_BASE_URL Download the release zip and SHA256SUMS from this URL
                       instead of GitHub.
  LTB_REPOSITORY       GitHub repository to download and clone from
                       (default siyuanj/local-tasks-bridge).
  LTB_LANG             Language of the installer: en or zh.
  https_proxy          Proxy for downloads (curl does not use the macOS system proxy),
                       for example http://127.0.0.1:7890.

The installer never uses sudo and does not run as root.
USAGE
  fi
}

# ---------------------------------------------------------------------------
# Arguments and preflight checks
# ---------------------------------------------------------------------------

parse_args() {
  local from_source=0 uninstall=0 version_re='^v?[0-9]+\.[0-9]+\.[0-9]+$'

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --version|--dest|--zip)
        [ "$#" -ge 2 ] || usage_error "$1 needs a value." "$1 需要一个值。"
        case "$1" in
          --version) REQUESTED_VERSION="$2" ;;
          --dest) DEST_DIR="$2" ;;
          --zip) ZIP_PATH="$2" ;;
        esac
        shift
        ;;
      --version=*) REQUESTED_VERSION="${1#*=}" ;;
      --dest=*) DEST_DIR="${1#*=}" ;;
      --zip=*) ZIP_PATH="${1#*=}" ;;
      --from-source)
        from_source=1
        if [ "$#" -ge 2 ]; then
          case "$2" in
            -*) ;;
            *) SOURCE_DIR="$2"; shift ;;
          esac
        fi
        ;;
      --from-source=*) from_source=1; SOURCE_DIR="${1#*=}" ;;
      --embed-python) EMBED_PYTHON=1 ;;
      --no-cli) INSTALL_CLI=0 ;;
      --no-open) OPEN_APP=0 ;;
      --uninstall) uninstall=1 ;;
      -y|--yes) ASSUME_YES=1 ;;
      --revoke) REVOKE=1 ;;
      --delete-data) DELETE_DATA=1 ;;
      -h|--help) usage; exit 0 ;;
      *) usage_error "Unknown option: $1" "未知选项：$1" ;;
    esac
    shift
  done

  case "${DEST_DIR%/}" in
    *.app)
      usage_error "--dest is the folder that contains the app (for example ~/Applications), not the app itself." \
        "--dest 应该是存放 App 的文件夹（例如 ~/Applications），而不是 App 本身。"
      ;;
  esac

  if [ -n "$REQUESTED_VERSION" ]; then
    [[ $REQUESTED_VERSION =~ $version_re ]] ||
      usage_error "--version must look like v1.2.3, got: $REQUESTED_VERSION" "--version 的格式应为 v1.2.3，实际为：$REQUESTED_VERSION"
    REQUESTED_VERSION="${REQUESTED_VERSION#v}"
  fi

  if [ "$uninstall" -eq 1 ]; then
    if [ "$from_source" -eq 1 ] || [ -n "$ZIP_PATH" ] || [ -n "$REQUESTED_VERSION" ] || [ "$EMBED_PYTHON" -eq 1 ]; then
      usage_error "--uninstall cannot be combined with --zip, --from-source, --version, or --embed-python." \
        "--uninstall 不能与 --zip、--from-source、--version 或 --embed-python 一起使用。"
    fi
    MODE="uninstall"
    return 0
  fi

  if [ "$REVOKE" -eq 1 ] || [ "$DELETE_DATA" -eq 1 ]; then
    usage_error "--revoke and --delete-data are only valid with --uninstall." "--revoke 和 --delete-data 只能与 --uninstall 一起使用。"
  fi
  if [ "$from_source" -eq 1 ] && [ -n "$ZIP_PATH" ]; then
    usage_error "Choose either --zip or --from-source." "--zip 和 --from-source 只能选择一个。"
  fi
  if [ -n "$REQUESTED_VERSION" ] && [ -n "$ZIP_PATH" ]; then
    usage_error "--version cannot be combined with --zip." "--version 不能与 --zip 一起使用。"
  fi
  if [ -n "$REQUESTED_VERSION" ] && [ -n "$SOURCE_DIR" ]; then
    usage_error "--version cannot be combined with a local source directory." "--version 不能与本地源代码目录一起使用。"
  fi
  if [ "$EMBED_PYTHON" -eq 1 ] && [ "$from_source" -eq 0 ]; then
    usage_error "--embed-python is only valid with --from-source." "--embed-python 只能与 --from-source 一起使用。"
  fi

  if [ "$from_source" -eq 1 ]; then
    MODE="source"
  elif [ -n "$ZIP_PATH" ]; then
    MODE="zip"
  else
    MODE="release"
  fi
}

preflight() {
  local product major tool repo_re='^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'

  [ "$(uname -s)" = "Darwin" ] || die "Local Tasks Bridge runs on macOS only." "Local Tasks Bridge 只能在 macOS 上运行。"
  if [ "$(id -u)" -eq 0 ]; then
    die "Do not run this installer as root or with sudo; run it as your normal user." \
      "请不要以 root 身份或通过 sudo 运行安装程序，请用你平时的用户身份运行。"
  fi
  if [ -z "${HOME:-}" ] || [ ! -d "$HOME" ]; then
    die "HOME must point to your home folder." "HOME 必须指向你的个人文件夹。"
  fi

  product="$(sw_vers -productVersion 2>/dev/null || true)"
  major="${product%%.*}"
  case "$major" in
    ''|*[!0-9]*) major=0 ;;
  esac
  if [ "$major" -lt "$MIN_MACOS_MAJOR" ]; then
    die "Local Tasks Bridge needs macOS 13 Ventura or later (this Mac runs ${product:-an unknown version})." \
      "Local Tasks Bridge 需要 macOS 13 Ventura 或更高版本（这台 Mac 的版本：${product:-未知}）。"
  fi

  for tool in curl ditto shasum xattr ps awk codesign; do
    command -v "$tool" >/dev/null 2>&1 || die "Required tool not found: $tool" "缺少必需的工具：$tool"
  done
  [ -x /usr/libexec/PlistBuddy ] || die "Required tool not found: /usr/libexec/PlistBuddy" "缺少必需的工具：/usr/libexec/PlistBuddy"

  REPOSITORY="${LTB_REPOSITORY:-$DEFAULT_REPOSITORY}"
  # Tests point this at a temporary folder so they never touch /Applications.
  SYSTEM_APPS_DIR="${LTB_SYSTEM_APPLICATIONS_DIR:-/Applications}"
  SYSTEM_APPS_DIR="${SYSTEM_APPS_DIR%/}"
  [[ $REPOSITORY =~ $repo_re ]] ||
    die "LTB_REPOSITORY must look like owner/name, got: $REPOSITORY" "LTB_REPOSITORY 的格式应为 owner/name，实际为：$REPOSITORY"
}

detect_arch() {
  case "$(uname -m)" in
    arm64)
      HOST_ARCH="arm64"
      ;;
    x86_64)
      # A shell running under Rosetta reports x86_64 on Apple silicon.
      if [ "$(sysctl -in sysctl.proc_translated 2>/dev/null || true)" = "1" ]; then
        HOST_ARCH="arm64"
      else
        HOST_ARCH="x86_64"
      fi
      ;;
    *)
      die "Unsupported processor: $(uname -m)" "不支持的处理器：$(uname -m)"
      ;;
  esac
}

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

plist_value() {
  /usr/libexec/PlistBuddy -c "Print :$2" "$1" 2>/dev/null
}

bundle_id_of() {
  [ -f "$1/Contents/Info.plist" ] || return 1
  plist_value "$1/Contents/Info.plist" CFBundleIdentifier
}

expand_tilde() {
  case "$1" in
    \~) printf '%s\n' "$HOME" ;;
    \~/*) printf '%s\n' "$HOME/${1#\~/}" ;;
    *) printf '%s\n' "$1" ;;
  esac
}

# run_with_timeout SECONDS COMMAND...: run COMMAND with stdin closed and stop
# it if it is still running after SECONDS.
run_with_timeout() {
  local limit=$(($1 * 10)) ticks=0 pid
  shift
  "$@" </dev/null &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$ticks" -ge "$limit" ]; then
      kill -TERM "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      return 124
    fi
    sleep 0.1
    ticks=$((ticks + 1))
  done
  wait "$pid"
}

# Print the PIDs of processes whose command line refers to files inside the
# given app bundle (the menu bar app and the engine it runs).
app_pids() {
  ps -axww -o pid=,command= 2>/dev/null |
    LTB_MATCH="$1/Contents/" awk -v self="$$" 'index($0, ENVIRON["LTB_MATCH"]) > 0 && $1 != self { print $1 }' || true
}

wait_for_exit() {
  local app="$1" ticks=0 limit=$(($2 * 2))
  while [ -n "$(app_pids "$app")" ] && [ "$ticks" -lt "$limit" ]; do
    sleep 0.5
    ticks=$((ticks + 1))
  done
  [ -z "$(app_pids "$app")" ]
}

quit_running_copy() {
  local app="$1" pids
  pids="$(app_pids "$app")"
  [ -n "$pids" ] || return 0

  step "Quitting the running Local Tasks Bridge…" "正在退出正在运行的 Local Tasks Bridge…"
  osascript -e "tell application id \"$BUNDLE_ID\" to quit" >/dev/null 2>&1 || true
  if wait_for_exit "$app" 10; then
    return 0
  fi

  pids="$(app_pids "$app")"
  if [ -n "$pids" ]; then
    # Word splitting is intended: one PID per word.
    # shellcheck disable=SC2086
    kill -TERM $pids 2>/dev/null || true
  fi
  if ! wait_for_exit "$app" 5; then
    warn "Some Local Tasks Bridge processes are still running; continuing anyway." \
      "仍有 Local Tasks Bridge 进程在运行；继续安装。"
  fi
}

remove_quarantine() {
  local listing
  xattr -r -d com.apple.quarantine "$1" 2>/dev/null || true
  listing="$(xattr -r -l "$1" 2>/dev/null || true)"
  case "$listing" in
    *com.apple.quarantine*)
      die "Could not remove the quarantine attribute from $1." "无法移除 $1 的隔离属性（com.apple.quarantine）。"
      ;;
  esac
}

# ---------------------------------------------------------------------------
# Getting the app
# ---------------------------------------------------------------------------

# curl protocol restrictions for a URL; dies for anything but https://,
# file://, or loopback http:// (the last two exist for tests and mirrors).
url_protocols() {
  case "$1" in
    https://*) printf '%s\n' "=https" ;;
    file://*) printf '%s\n' "=file" ;;
    http://127.0.0.1:*|http://127.0.0.1/*|http://localhost:*|http://localhost/*) printf '%s\n' "=http" ;;
    *) return 1 ;;
  esac
}

require_allowed_url() {
  url_protocols "$1" >/dev/null ||
    die "Refusing to download from $1 (use https://, file://, or a loopback http:// URL)." \
      "拒绝从 $1 下载（只允许 https://、file:// 或本机回环 http:// 地址）。"
}

download() {
  local url="$1" output="$2" progress="${3:-0}" protocols
  local -a args=(--fail --location --retry 3 --retry-delay 2 --connect-timeout 30 --output "$output")

  require_allowed_url "$url"
  protocols="$(url_protocols "$url")"
  args+=(--proto "$protocols")
  if [ "$protocols" = "=https" ]; then
    args+=(--proto-redir "=https" --tlsv1.2)
  fi
  if [ "$progress" = "1" ] && [ -t 2 ]; then
    args+=(--progress-bar)
  else
    args+=(--silent --show-error)
  fi
  curl "${args[@]}" "$url"
}

verify_checksum() {
  local file="$1" sums="$2" name="$3" expected actual

  expected="$(awk -v name="$name" '$2 == name || $2 == ("*" name) { print tolower($1); exit }' "$sums")"
  case "$expected" in
    ''|*[!0-9a-f]*)
      die "SHA256SUMS has no valid entry for $name; nothing was changed." "SHA256SUMS 中没有 $name 的有效校验值；没有做任何更改。"
      ;;
  esac
  if [ "${#expected}" -ne 64 ]; then
    die "SHA256SUMS has no valid entry for $name; nothing was changed." "SHA256SUMS 中没有 $name 的有效校验值；没有做任何更改。"
  fi

  actual="$(shasum -a 256 "$file" | awk '{ print $1 }')"
  if [ "$actual" != "$expected" ]; then
    die "Checksum mismatch for $name (expected $expected, got $actual). The file may be damaged or tampered with; nothing was changed." \
      "$name 的校验值不匹配（应为 $expected，实际为 $actual）。文件可能已损坏或被篡改；没有做任何更改。"
  fi
  say "Verified SHA-256 of $name." "已校验 $name 的 SHA-256。"
}

# Downloads go through curl, which ignores the macOS system proxy.
proxy_hint() {
  local current="${https_proxy:-${HTTPS_PROXY:-${all_proxy:-${ALL_PROXY:-}}}}"
  if [ -n "$current" ]; then
    say "Downloads use the proxy $current; check that it is running." "下载使用代理 $current；请确认代理软件正在运行。" >&2
    return 0
  fi
  say "Tip: curl does not use the macOS system proxy. If you need a proxy to reach GitHub (common in mainland China), set it first, for example:" \
    "提示：curl 不会使用 macOS 的系统代理。如果访问 GitHub 需要代理（在中国大陆很常见），请先设置代理，例如：" >&2
  printf '    export https_proxy=http://127.0.0.1:7890\n' >&2
  say "(use the HTTP proxy port shown in your proxy app), then run the installer again." \
    "（端口以你的代理软件显示的 HTTP 代理端口为准），然后重新运行安装程序。" >&2
}

release_base_url() {
  if [ -n "${LTB_RELEASE_BASE_URL:-}" ]; then
    printf '%s\n' "${LTB_RELEASE_BASE_URL%/}"
  elif [ -n "$REQUESTED_VERSION" ]; then
    printf 'https://github.com/%s/releases/download/v%s\n' "$REPOSITORY" "$REQUESTED_VERSION"
  else
    printf 'https://github.com/%s/releases/latest/download\n' "$REPOSITORY"
  fi
}

fetch_release() {
  local base asset
  base="$(release_base_url)"
  asset="${ASSET_PREFIX}-${HOST_ARCH}.zip"
  require_allowed_url "$base/"

  step "Downloading $asset…" "正在下载 $asset…"
  if ! download "$base/SHA256SUMS" "$WORK_DIR/SHA256SUMS"; then
    proxy_hint
    die "Could not download SHA256SUMS from $base. Check your network connection and that the release exists." \
      "无法从 $base 下载 SHA256SUMS。请检查网络连接，并确认该版本存在。"
  fi
  if ! download "$base/$asset" "$WORK_DIR/$asset" 1; then
    proxy_hint
    die "Could not download $asset from $base." "无法从 $base 下载 $asset。"
  fi
  verify_checksum "$WORK_DIR/$asset" "$WORK_DIR/SHA256SUMS" "$asset"
  ZIP_FILE="$WORK_DIR/$asset"
}

prepare_local_zip() {
  local path dir name
  path="$(expand_tilde "$ZIP_PATH")"
  [ -f "$path" ] || die "Zip file not found: $path" "找不到 zip 文件：$path"
  dir="$(cd "$(dirname "$path")" && pwd -P)"
  name="$(basename "$path")"
  ZIP_FILE="$dir/$name"
  if [ -f "$dir/SHA256SUMS" ]; then
    verify_checksum "$ZIP_FILE" "$dir/SHA256SUMS" "$name"
  else
    warn "No SHA256SUMS file next to $name; installing it without a checksum check." \
      "$name 旁边没有 SHA256SUMS 文件；将在不校验的情况下安装。"
  fi
}

installer_dir() {
  local source="${BASH_SOURCE[0]:-}"
  case "$source" in
    ''|bash|-bash|/dev/stdin|/dev/fd/*) return 0 ;;
  esac
  [ -f "$source" ] || return 0
  (cd "$(dirname "$source")" && pwd -P)
}

is_source_tree() {
  [ -f "$1/scripts/build-app.sh" ] && [ -f "$1/engine/local_tasks_bridge.py" ]
}

require_command_line_tools() {
  if xcode-select -p >/dev/null 2>&1; then
    return 0
  fi
  step "Asking macOS to install the Xcode Command Line Tools…" "正在请求 macOS 安装 Xcode Command Line Tools…"
  xcode-select --install >/dev/null 2>&1 || true
  die "Building from source needs the Xcode Command Line Tools. Finish the installation in the window that opened, then run this installer again." \
    "从源代码构建需要 Xcode Command Line Tools。请在弹出的窗口中完成安装，然后重新运行本安装程序。"
}

build_from_source() {
  local src="" here
  local -a build_args clone_args

  require_command_line_tools

  if [ -n "$SOURCE_DIR" ]; then
    src="$(expand_tilde "$SOURCE_DIR")"
    [ -d "$src" ] || die "Source directory not found: $src" "找不到源代码目录：$src"
    src="$(cd "$src" && pwd -P)"
    is_source_tree "$src" ||
      die "$src is not a Local Tasks Bridge source checkout (scripts/build-app.sh is missing)." \
        "$src 不是 Local Tasks Bridge 的源代码目录（缺少 scripts/build-app.sh）。"
  else
    here="$(installer_dir)"
    if [ -n "$here" ] && [ -z "$REQUESTED_VERSION" ] && is_source_tree "$here"; then
      src="$here"
    fi
  fi

  if [ -z "$src" ]; then
    command -v git >/dev/null 2>&1 || die "git is required to download the source code." "下载源代码需要 git。"
    clone_args=(clone --quiet --depth 1)
    if [ -n "$REQUESTED_VERSION" ]; then
      clone_args+=(--branch "v$REQUESTED_VERSION")
    fi
    step "Downloading the source code of $REPOSITORY…" "正在下载 $REPOSITORY 的源代码…"
    if ! git "${clone_args[@]}" "https://github.com/$REPOSITORY.git" "$WORK_DIR/source"; then
      proxy_hint
      die "Could not clone https://github.com/$REPOSITORY.git." "无法克隆 https://github.com/$REPOSITORY.git。"
    fi
    src="$WORK_DIR/source"
  fi

  build_args=(--output "$WORK_DIR/build" --arch "$HOST_ARCH")
  if [ "$EMBED_PYTHON" -eq 1 ]; then
    step "Downloading a private Python for the app…" "正在为 App 下载独立的 Python…"
    if ! /bin/bash "$src/scripts/fetch-python.sh" --arch "$HOST_ARCH" --output "$WORK_DIR/python" >/dev/null; then
      die "Could not prepare the embedded Python; nothing was changed." "无法准备内置 Python；没有做任何更改。"
    fi
    build_args+=(--python "$WORK_DIR/python")
  fi

  step "Building Local Tasks Bridge from $src…" "正在从 $src 构建 Local Tasks Bridge…"
  if ! /bin/bash "$src/scripts/build-app.sh" "${build_args[@]}"; then
    die "The build failed (see the messages above); nothing was changed." "构建失败（见上方信息）；没有做任何更改。"
  fi
  BUILT_APP="$WORK_DIR/build/$APP_BUNDLE_NAME"
  [ -d "$BUILT_APP" ] || die "The build did not produce $APP_BUNDLE_NAME." "构建没有生成 $APP_BUNDLE_NAME。"
}

# ---------------------------------------------------------------------------
# Validating and installing the bundle
# ---------------------------------------------------------------------------

check_cli() {
  local app="$1" output=""
  if output="$(PYTHONDONTWRITEBYTECODE=1 run_with_timeout 60 "$app/Contents/Resources/bin/ltb" version --json 2>/dev/null)"; then
    case "$output" in
      *'"ok": true'*|*'"ok":true'*) return 0 ;;
    esac
  fi
  if [ -e "$app/Contents/Resources/python/bin/python3" ]; then
    die "The ltb command inside the new app failed its self-check (ltb version); nothing was changed." \
      "新 App 内的 ltb 命令未通过自检（ltb version）；没有做任何更改。"
  fi
  warn "The ltb command did not find Python 3.9 or newer yet; the app will show how to install it." \
    "ltb 命令暂时找不到 Python 3.9 或更高版本；App 会提示如何安装。"
}

validate_bundle() {
  local app="$1" id version output first_line

  id="$(bundle_id_of "$app" || true)"
  if [ "$id" != "$BUNDLE_ID" ]; then
    die "The new app has the bundle identifier '${id:-none}' instead of $BUNDLE_ID; nothing was changed." \
      "新 App 的标识符是 ${id:-无}，而不是 $BUNDLE_ID；没有做任何更改。"
  fi
  if [ ! -x "$app/Contents/MacOS/LocalTasksBridge" ] || [ ! -x "$app/Contents/Resources/bin/ltb" ]; then
    die "The new app is incomplete (Contents/MacOS/LocalTasksBridge or Contents/Resources/bin/ltb is missing); nothing was changed." \
      "新 App 不完整（缺少 Contents/MacOS/LocalTasksBridge 或 Contents/Resources/bin/ltb）；没有做任何更改。"
  fi
  version="$(plist_value "$app/Contents/Info.plist" CFBundleShortVersionString || true)"
  [ -n "$version" ] || die "The new app has no version number; nothing was changed." "新 App 没有版本号；没有做任何更改。"
  if [ -n "$REQUESTED_VERSION" ] && [ "$version" != "$REQUESTED_VERSION" ]; then
    die "Expected version $REQUESTED_VERSION but the app is version $version; nothing was changed." \
      "期望版本 $REQUESTED_VERSION，但 App 的版本是 $version；没有做任何更改。"
  fi

  if ! output="$(run_with_timeout 30 "$app/Contents/MacOS/LocalTasksBridge" --version 2>&1)"; then
    die "The new app failed its self-check (LocalTasksBridge --version); nothing was changed. Is this the right download for this Mac ($HOST_ARCH)?" \
      "新 App 未通过自检（LocalTasksBridge --version）；没有做任何更改。请确认下载的是适用于这台 Mac（$HOST_ARCH）的版本。"
  fi
  first_line="${output%%$'\n'*}"
  case "$output" in
    *"$version"*) ;;
    *)
      die "The app reported '$first_line' instead of version $version; nothing was changed." \
        "App 报告的版本（$first_line）与 $version 不一致；没有做任何更改。"
      ;;
  esac

  check_cli "$app"

  # Last, so it also notices anything the checks above changed in the bundle.
  if ! codesign --verify --strict --deep "$app" 2>/dev/null; then
    die "The new app's code signature is missing or invalid; nothing was changed." \
      "新 App 的代码签名缺失或无效；没有做任何更改。"
  fi
  NEW_VERSION="$version"
}

# Without --dest, update an existing copy where it is; a first install goes
# to ~/Applications, which needs no administrator rights.
default_dest_dir() {
  if [ ! -e "$HOME/Applications/$APP_BUNDLE_NAME" ] &&
    [ "$(bundle_id_of "$SYSTEM_APPS_DIR/$APP_BUNDLE_NAME" || true)" = "$BUNDLE_ID" ]; then
    printf '%s\n' "$SYSTEM_APPS_DIR"
  else
    printf '%s\n' "$HOME/Applications"
  fi
}

prepare_dest_dir() {
  local dest
  if [ -n "$DEST_DIR" ]; then
    dest="$(expand_tilde "$DEST_DIR")"
  else
    dest="$(default_dest_dir)"
  fi
  if ! mkdir -p "$dest" 2>/dev/null; then
    die "Could not create $dest. Choose a folder you can write to with --dest; this installer never uses sudo." \
      "无法创建 $dest。请用 --dest 选择一个你有写入权限的目录；安装程序从不使用 sudo。"
  fi
  dest="$(cd "$dest" && pwd -P)"
  if [ ! -w "$dest" ]; then
    die "You cannot write to $dest. Choose another folder with --dest (for example ~/Applications); this installer never uses sudo." \
      "你没有 $dest 的写入权限。请用 --dest 选择其他目录（例如 ~/Applications）；安装程序从不使用 sudo。"
  fi
  DEST_DIR="$dest"
  TARGET_APP="$DEST_DIR/$APP_BUNDLE_NAME"
}

inspect_target() {
  local id
  EXISTING_KIND="none"
  if [ ! -e "$TARGET_APP" ] && [ ! -L "$TARGET_APP" ]; then
    return 0
  fi
  id="$(bundle_id_of "$TARGET_APP" || true)"
  case "$id" in
    "$BUNDLE_ID")
      EXISTING_KIND="current"
      EXISTING_VERSION="$(plist_value "$TARGET_APP/Contents/Info.plist" CFBundleShortVersionString || true)"
      ;;
    "$LEGACY_BUNDLE_ID")
      EXISTING_KIND="legacy"
      ;;
    "")
      die "$TARGET_APP exists but is not a valid app. Move it away, then run the installer again." \
        "$TARGET_APP 已存在，但不是有效的 App。请先把它移走，然后重新运行安装程序。"
      ;;
    *)
      die "$TARGET_APP belongs to another app ($id). Move it away or choose another folder with --dest." \
        "$TARGET_APP 属于另一个 App（$id）。请把它移走，或用 --dest 选择其他目录。"
      ;;
  esac
}

restore_backup() {
  if [ -n "$BACKUP_APP" ] && [ -e "$BACKUP_APP" ] && [ ! -e "$TARGET_APP" ]; then
    if mv "$BACKUP_APP" "$TARGET_APP"; then
      BACKUP_APP=""
    fi
  fi
}

retire_legacy_app() {
  local old="$1" trash="$HOME/.Trash" name
  name="Local Tasks Bridge (trial build $(date +%Y%m%d-%H%M%S)).app"
  if mkdir -p "$trash" 2>/dev/null && mv "$old" "$trash/$name" 2>/dev/null; then
    say "Moved the earlier trial build to the Trash ($name)." "已将早期试用版移到废纸篓（$name）。"
    say "Open Local Tasks Bridge to import its settings, Google sign-in, and sync map." \
      "打开 Local Tasks Bridge 即可导入它的设置、Google 登录和同步对应关系。"
  else
    KEEP_STAGING=1
    warn "Could not move the earlier trial build to the Trash; it was kept at $old." \
      "无法将早期试用版移到废纸篓；它保留在 $old。"
  fi
}

swap_in() {
  local new_app="$1" previous

  if [ "$EXISTING_KIND" != "none" ]; then
    previous="$STAGING_DIR/previous.app"
    if ! mv "$TARGET_APP" "$previous"; then
      die "Could not move the installed app aside; nothing was changed." "无法移开已安装的 App；没有做任何更改。"
    fi
    BACKUP_APP="$previous"
  fi

  if ! mv "$new_app" "$TARGET_APP"; then
    restore_backup
    die "Could not install the new app; the previous version (if any) was kept." "无法安装新 App；已保留原来的版本（如有）。"
  fi
  BACKUP_APP=""

  if [ "$EXISTING_KIND" = "legacy" ]; then
    retire_legacy_app "$previous"
  fi
}

link_cli() {
  local bin_dir="$HOME/.local/bin" link="$HOME/.local/bin/ltb" current profile

  if [ -L "$link" ]; then
    current="$(readlink "$link" || true)"
    case "$current" in
      */Contents/Resources/bin/ltb) ;;
      *)
        warn "$link already points to $current; leaving it unchanged." "$link 已经指向 $current；保持不变。"
        return 0
        ;;
    esac
  elif [ -e "$link" ]; then
    warn "$link already exists and is not a link; leaving it unchanged." "$link 已存在且不是链接；保持不变。"
    return 0
  fi

  if ! mkdir -p "$bin_dir" || ! ln -sfn "$TARGET_APP/Contents/Resources/bin/ltb" "$link"; then
    warn "Could not create $link; the ltb command is still available inside the app." \
      "无法创建 $link；ltb 命令仍可在 App 内使用。"
    return 0
  fi
  say "Linked the ltb command: $link" "已链接 ltb 命令：$link"

  case ":${PATH:-}:" in
    *":$bin_dir:"*|*":$bin_dir/:"*) ;;
    *)
      case "${SHELL:-}" in
        */bash) profile=".bash_profile" ;;
        *) profile=".zprofile" ;;
      esac
      say "Your PATH does not include ~/.local/bin. To use ltb, add this line to ~/$profile and open a new Terminal window:" \
        "PATH 中没有 ~/.local/bin。要使用 ltb，请把下面这一行加入 ~/$profile，然后打开新的终端窗口："
      # The single quotes are intentional: this prints the literal line to add.
      # shellcheck disable=SC2016
      printf '    export PATH="$HOME/.local/bin:$PATH"\n'
      ;;
  esac
}

warn_about_other_copies() {
  local other
  for other in "$HOME/Applications/$APP_BUNDLE_NAME" "$SYSTEM_APPS_DIR/$APP_BUNDLE_NAME"; do
    [ "$other" != "$TARGET_APP" ] || continue
    if [ -d "$other" ] && [ "$(bundle_id_of "$other" || true)" = "$BUNDLE_ID" ]; then
      warn "Another copy is installed at $other. Remove it so only one copy runs." \
        "在 $other 还安装了另一份副本。请删除它，以免同时运行两份。"
    fi
  done
}

run_install() {
  local new_app

  detect_arch
  prepare_dest_dir
  inspect_target

  case "$MODE" in
    release) fetch_release ;;
    zip) prepare_local_zip ;;
    source) build_from_source ;;
  esac

  STAGING_DIR="$(mktemp -d "$DEST_DIR/.ltb-install.XXXXXX")"
  new_app="$STAGING_DIR/new/$APP_BUNDLE_NAME"
  mkdir -p "$STAGING_DIR/new"
  if [ -n "$ZIP_FILE" ]; then
    step "Unpacking $(basename "$ZIP_FILE")…" "正在解压 $(basename "$ZIP_FILE")…"
    if ! ditto -x -k --noqtn "$ZIP_FILE" "$STAGING_DIR/new"; then
      die "Could not unpack $(basename "$ZIP_FILE"); nothing was changed." "无法解压 $(basename "$ZIP_FILE")；没有做任何更改。"
    fi
    [ -d "$new_app" ] || die "The zip does not contain $APP_BUNDLE_NAME; nothing was changed." "zip 中没有 $APP_BUNDLE_NAME；没有做任何更改。"
  else
    ditto "$BUILT_APP" "$new_app"
  fi

  remove_quarantine "$new_app"
  step "Checking the new app…" "正在检查新 App…"
  validate_bundle "$new_app"

  if [ "$EXISTING_KIND" = "current" ]; then
    quit_running_copy "$TARGET_APP"
  fi
  step "Installing into $DEST_DIR…" "正在安装到 $DEST_DIR…"
  swap_in "$new_app"
  if [ "$EXISTING_KIND" = "current" ] && [ -n "$EXISTING_VERSION" ] && [ "$EXISTING_VERSION" != "$NEW_VERSION" ]; then
    say "Updated Local Tasks Bridge $EXISTING_VERSION → $NEW_VERSION: $TARGET_APP" \
      "已将 Local Tasks Bridge 从 $EXISTING_VERSION 更新到 $NEW_VERSION：$TARGET_APP"
  else
    say "Installed Local Tasks Bridge $NEW_VERSION: $TARGET_APP" "已安装 Local Tasks Bridge $NEW_VERSION：$TARGET_APP"
  fi

  if [ "$INSTALL_CLI" -eq 1 ]; then
    link_cli
  fi
  warn_about_other_copies

  if [ "$OPEN_APP" -eq 1 ]; then
    step "Opening Local Tasks Bridge…" "正在打开 Local Tasks Bridge…"
    if open "$TARGET_APP"; then
      say "Look for its icon in the menu bar and follow the setup steps." "请在菜单栏中找到它的图标，并按照设置步骤完成配置。"
    else
      warn "Could not open the app automatically; open it from $DEST_DIR." "无法自动打开 App；请从 $DEST_DIR 打开它。"
    fi
  else
    say "Open it from $DEST_DIR to finish the setup." "请从 $DEST_DIR 打开它以完成设置。"
  fi
}

# ---------------------------------------------------------------------------
# Uninstalling
# ---------------------------------------------------------------------------

remove_cli_link() {
  local link="$HOME/.local/bin/ltb" target
  [ -L "$link" ] || return 0
  target="$(readlink "$link" || true)"
  case "$target" in
    */"$APP_BUNDLE_NAME"/Contents/Resources/bin/ltb)
      # Only remove the link once it no longer leads to an installed app.
      if [ ! -e "$link" ]; then
        rm -f "$link"
        say "Removed the ltb link: $link" "已删除 ltb 命令链接：$link"
      fi
      ;;
  esac
}

confirm_uninstall() {
  local answer
  if [ "$ASSUME_YES" -eq 1 ]; then
    return 0
  fi
  if ! (: </dev/tty) 2>/dev/null; then
    die "No terminal is available to confirm; run again with --yes to remove Local Tasks Bridge." \
      "没有可用于确认的终端；如确定要卸载 Local Tasks Bridge，请加上 --yes 重新运行。"
  fi
  if [ "$DELETE_DATA" -eq 1 ]; then
    say "This also deletes your settings, the sync map, and the logs." "这也会删除你的设置、同步对应关系和日志。" >/dev/tty
  else
    say "Settings and sync data stay in ~/.config/local-tasks-bridge (add --delete-data to remove them)." \
      "设置和同步数据会保留在 ~/.config/local-tasks-bridge（加上 --delete-data 可一并删除）。" >/dev/tty
  fi
  if [ "$UI_LANG" = "zh" ]; then
    printf '确定要卸载 Local Tasks Bridge 吗？[y/N] ' >/dev/tty
  else
    printf 'Remove Local Tasks Bridge? [y/N] ' >/dev/tty
  fi
  answer=""
  IFS= read -r answer </dev/tty || true
  case "$answer" in
    y|Y|yes|Yes|YES|是) return 0 ;;
  esac
  say "Cancelled; nothing was removed." "已取消；没有删除任何内容。"
  exit 1
}

run_uninstall() {
  local candidate app dest ltb status output=""
  local -a candidates=() apps=() ltb_args=(uninstall --yes)

  if [ -n "$DEST_DIR" ]; then
    dest="$(expand_tilde "$DEST_DIR")"
    candidates=("${dest%/}/$APP_BUNDLE_NAME")
  else
    candidates=("$HOME/Applications/$APP_BUNDLE_NAME" "$SYSTEM_APPS_DIR/$APP_BUNDLE_NAME")
  fi
  for candidate in "${candidates[@]}"; do
    if [ -d "$candidate" ] && [ "$(bundle_id_of "$candidate" || true)" = "$BUNDLE_ID" ]; then
      apps+=("$candidate")
    fi
  done

  if [ "${#apps[@]}" -eq 0 ]; then
    say "Local Tasks Bridge is not installed in: ${candidates[*]}" "未在以下位置找到 Local Tasks Bridge：${candidates[*]}"
    remove_cli_link
    return 0
  fi

  confirm_uninstall
  for app in "${apps[@]}"; do
    quit_running_copy "$app"
  done

  if [ "$REVOKE" -eq 1 ]; then
    ltb_args+=(--revoke)
  fi
  if [ "$DELETE_DATA" -eq 1 ]; then
    ltb_args+=(--delete-data)
  fi
  ltb="${apps[0]}/Contents/Resources/bin/ltb"
  step "Removing the login item…" "正在移除登录项…"
  status=0
  if [ -x "$ltb" ]; then
    # The ltb wrapper exports LTB_APP_BUNDLE, which makes `ltb uninstall`
    # behave as if the app called it and leave the launchd job loaded; stop
    # the job explicitly first (the app has already quit).
    if ! LTB_LANG="$UI_LANG" "$ltb" agent uninstall --bootout --json </dev/null >/dev/null; then
      warn "Could not stop the login item; continuing." "无法停止登录项；继续卸载。"
    fi
    output="$(LTB_LANG="$UI_LANG" "$ltb" "${ltb_args[@]}" --json </dev/null)" || status=$?
  else
    status=127
  fi
  if [ "$status" -ne 0 ]; then
    if [ -n "$output" ]; then
      printf '%s\n' "$output" >&2
    fi
    die "'ltb uninstall' failed (exit $status); the app was left in place. To remove the login item by hand run: launchctl bootout gui/$(id -u)/$LAUNCH_AGENT_LABEL; rm -f ~/Library/LaunchAgents/$LAUNCH_AGENT_LABEL.plist — then run this uninstaller again." \
      "ltb uninstall 执行失败（退出码 $status）；App 保持不变。可手动移除登录项：launchctl bootout gui/$(id -u)/$LAUNCH_AGENT_LABEL; rm -f ~/Library/LaunchAgents/$LAUNCH_AGENT_LABEL.plist，然后重新运行卸载。"
  fi

  say "Removed the login item." "已移除登录项。"
  if [ "$REVOKE" -eq 1 ]; then
    case "$output" in
      *'"revoke_failed": true'*|*'"revoke_failed":true'*)
        warn "Google access could not be revoked (network problem?). Revoke it yourself at https://myaccount.google.com/permissions" \
          "未能撤销 Google 授权（可能是网络问题）。请在 https://myaccount.google.com/permissions 手动撤销。"
        ;;
      *'"revoked": true'*|*'"revoked":true'*)
        say "Google access was revoked." "已撤销 Google 授权。"
        ;;
      *)
        say "There was no Google sign-in to revoke." "没有需要撤销的 Google 登录。"
        ;;
    esac
  fi

  for app in "${apps[@]}"; do
    if ! rm -rf "$app"; then
      die "Could not remove $app; remove it in Finder." "无法删除 $app；请在访达中手动删除。"
    fi
    say "Removed $app" "已删除 $app"
  done
  remove_cli_link

  if [ "$DELETE_DATA" -eq 1 ]; then
    say "Local Tasks Bridge and its data were removed." "已卸载 Local Tasks Bridge 并删除其数据。"
  else
    say "Local Tasks Bridge was removed. Your settings and sync map are still in ~/.config/local-tasks-bridge." \
      "已卸载 Local Tasks Bridge。你的设置和同步对应关系仍保留在 ~/.config/local-tasks-bridge。"
  fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

cleanup() {
  local status=$?
  restore_backup || true
  if [ -n "$STAGING_DIR" ] && [ "$KEEP_STAGING" -eq 0 ]; then
    rm -rf "$STAGING_DIR" || true
  fi
  if [ -n "$WORK_DIR" ]; then
    rm -rf "$WORK_DIR" || true
  fi
  exit "$status"
}

main() {
  local tmp_root

  detect_language
  parse_args "$@"
  preflight

  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  tmp_root="${TMPDIR:-/tmp}"
  WORK_DIR="$(mktemp -d "${tmp_root%/}/ltb-install.XXXXXX")"

  if [ "$MODE" = "uninstall" ]; then
    run_uninstall
  else
    run_install
  fi
}

main "$@"
