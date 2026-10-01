#!/bin/bash
# Builds and runs the app-core tests (macos/Tests/AppCore): child processes,
# engine JSON mapping against the real engine, the run-loop supervisor, and the
# private log. No GUI, Reminders access, network, or launchctl; HOME and every
# engine path point into a temporary directory that is removed afterwards.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
work="$(mktemp -d "${TMPDIR:-/tmp}/ltb-app-core.XXXXXX")"
trap 'rm -rf "$work"' EXIT

sdk="$(xcrun --show-sdk-path 2>/dev/null || echo /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk)"
app="$repo_root/macos/App"
swiftc -swift-version 5 -target "$(uname -m)-apple-macos13.0" -sdk "$sdk" -module-name AppCoreTests \
    -o "$work/app-core-tests" \
    "$app/AppInfo.swift" "$app/AppLog.swift" "$app/ChildProcess.swift" "$app/EngineClient.swift" \
    "$app/EngineModels.swift" "$app/EngineRuntime.swift" "$app/EngineSupervisor.swift" \
    "$app/JSONValue.swift" "$app/SyncOptions.swift" \
    "$repo_root/macos/Tests/AppCore/main.swift"

mkdir -p "$work/home" "$work/data"
env HOME="$work/home" XDG_CONFIG_HOME="$work/home/.config" LTB_NO_LAUNCHCTL=1 \
    LTB_LAUNCH_AGENTS_DIR="$work/home/LaunchAgents" LTB_LOG_DIR="$work/home/Logs" \
    "$work/app-core-tests" "$repo_root" "$work/data"
