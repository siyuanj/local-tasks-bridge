"""Install the reviewed private fork without changing Google authentication."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--python-runtime", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    source = Path(__file__).resolve().parent.parent
    home = Path.home()
    private = home / ".config/reminders-task-bridge-trial"
    config_path = private / "daily-config.json"
    config = json.loads(config_path.read_text())
    if config.get("include_lists") != ["My Tasks"] or config.get("target_service") != "tasks":
        raise SystemExit("Refusing a configuration outside the selected daily list")
    for key in ("credentials_path", "token_path", "state_path", "status_path"):
        if Path(config[key]).parent != private:
            raise SystemExit(f"Unexpected private path: {key}")
    if config.get("use_adc") or config.get("auto_approve_destructive_loops"):
        raise SystemExit("Refusing ADC fallback or automatic destructive approval")
    if config.get("max_destructive_changes") != 1:
        raise SystemExit("Expected the reviewed one-change safety limit")
    root = home / ".local/share/icloud-reminders-google-sync"
    current = root / "current"
    release = root / "releases" / args.expected_commit
    python_root = root / "python-3.12"
    plist_path = home / "Library/LaunchAgents/com.icloud-reminders-google-sync.plist"
    if any(p.exists() or p.is_symlink() for p in (current, release, python_root, plist_path)):
        raise SystemExit("Existing installation requires review before replacement")
    env = dict(os.environ, DEPLOY_EXPECTED_COMMIT=args.expected_commit,
               DEPLOY_GIT_ALLOW_NON_MAIN="1", DEPLOY_GIT_ALLOW_UNPUSHED="1",
               DEPLOY_GIT_ALLOW_DIRTY="0", DEPLOY_GIT_OVERRIDE_REASON=args.reason)
    subprocess.run(["bash", str(source / "scripts/check-release-source.sh")],
                   env=env, check=True)
    release.mkdir(parents=True, mode=0o700)
    hashes = {}
    for name in ("icloud_reminders_google_sync.py", "RemindersExport.swift", "RemindersApply.swift"):
        original = source / name
        target = release / name
        shutil.copy2(original, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != hashlib.sha256(original.read_bytes()).hexdigest():
            raise SystemExit("Runtime copy checksum mismatch")
        hashes[name] = digest
        target.chmod(0o400)
    (release / "provenance.json").write_text(json.dumps({
        "commit": args.expected_commit, "reason": args.reason,
        "files": hashes, "mode": "private-reviewed-fork",
    }, indent=2) + "\n")
    shutil.copytree(args.python_runtime, python_root, symlinks=True,
                    ignore=shutil.ignore_patterns("site-packages", "__pycache__", "include", "share", "pkgconfig"))
    python = python_root / "bin/python3.12"
    subprocess.run([str(python), "-B", "-c", "import ssl,sqlite3,urllib.request; print('Private Python runtime ready')"],
                   check=True)
    current.symlink_to(release, target_is_directory=True)
    shutil.copy2(config_path, private / f"daily-config-before-background-{time.time_ns()}.json")
    config["reminders_exporter_path"] = str(current / "RemindersExport.swift")
    config["reminders_apply_path"] = str(current / "RemindersApply.swift")
    config["sync_interval_seconds"] = 60
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    config_path.chmod(0o600)
    log_dir = home / "Library/Logs/icloud-reminders-google-sync"
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_dir.chmod(0o700)
    logs = [log_dir / "sync.out.log", log_dir / "sync.err.log"]
    for path in logs:
        if path.is_symlink():
            raise SystemExit("Refusing a symlinked log")
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)
    plist = {
        "Label": "com.icloud-reminders-google-sync",
        "ProgramArguments": [str(python), "-B", "-u", str(current / "icloud_reminders_google_sync.py"),
                             "--config", str(config_path), "run-loop"],
        "WorkingDirectory": str(current), "RunAtLoad": True, "KeepAlive": True,
        "ThrottleInterval": 30, "ProcessType": "Background",
        "EnvironmentVariables": {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "SDKROOT": "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk",
            "SSL_CERT_FILE": "/etc/ssl/cert.pem",
            "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
        },
        "StandardOutPath": str(logs[0]), "StandardErrorPath": str(logs[1]),
    }
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_bytes(plistlib.dumps(plist))
    plist_path.chmod(0o600)
    subprocess.run(["/usr/bin/plutil", "-lint", str(plist_path)], check=True)
    print("Prepared background installation; launchctl bootstrap is the separate start step.")


if __name__ == "__main__":
    main()
