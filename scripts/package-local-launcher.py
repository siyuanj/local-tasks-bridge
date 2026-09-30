"""Prepare a native privacy-permission host for the installed local bridge."""

import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import time


def main():
    os.umask(0o077)
    source = Path(__file__).resolve().parent.parent
    home = Path.home()
    app = home / "Applications/Local Tasks Bridge.app"
    if app.exists():
        raise SystemExit("Existing app requires review before replacement")
    contents = app / "Contents"
    binary = contents / "MacOS/LocalBridgeLauncher"
    binary.parent.mkdir(parents=True, mode=0o700)
    info = {
        "CFBundleIdentifier": "local.reminders.tasks.bridge",
        "CFBundleName": "Local Tasks Bridge", "CFBundleDisplayName": "Local Tasks Bridge",
        "CFBundleExecutable": binary.name, "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1", "CFBundleShortVersionString": "1.0",
        "LSUIElement": True, "LSMinimumSystemVersion": "14.0",
        "NSRemindersFullAccessUsageDescription": "Sync your selected My Tasks list with Google Tasks on this Mac.",
        "NSRemindersUsageDescription": "Sync your selected My Tasks list with Google Tasks on this Mac.",
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    env = dict(os.environ, SDKROOT="/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk")
    subprocess.run(["/usr/bin/swiftc", "-parse-as-library", "-O", "-framework", "AppKit",
                    "-framework", "EventKit", str(source / "LocalBridgeLauncher.swift"),
                    "-o", str(binary)], env=env, check=True)
    subprocess.run(["/usr/bin/codesign", "--sign", "-", "--identifier", info["CFBundleIdentifier"],
                    str(app)], check=True)
    subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(app)], check=True)
    provenance = {"source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip(),
                  "source_sha256": hashlib.sha256((source / "LocalBridgeLauncher.swift").read_bytes()).hexdigest(),
                  "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()}
    (home / ".config/reminders-task-bridge-trial/launcher-provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n")
    agent = home / "Library/LaunchAgents/com.icloud-reminders-google-sync.plist"
    shutil.copy2(agent, home / f".config/reminders-task-bridge-trial/agent-before-native-{time.time_ns()}.plist")
    data = plistlib.loads(agent.read_bytes())
    data["ProgramArguments"] = [str(binary)]
    agent.write_bytes(plistlib.dumps(data))
    agent.chmod(0o600)
    print("Native permission host prepared; no Reminders permission has been granted by this installer.")


if __name__ == "__main__":
    main()
