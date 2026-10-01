#!/usr/bin/env python3
"""Local Tasks Bridge: a local-first bridge between Apple Reminders and Google Tasks.

This single-file engine reads and writes Apple Reminders through small EventKit
helpers, talks to the official Google Tasks API with the signed-in user's own
OAuth token, and keeps every credential, sync state file, and log on this Mac.

The engine runs under Python 3.9 or newer and uses only the standard library.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import fcntl
import hashlib
import http.client
import http.server
import io
import json
import os
from pathlib import Path
import plistlib
import secrets
import shutil
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request
import webbrowser


__version__ = "1.0.0"
PRODUCT_NAME = "Local Tasks Bridge"
APP_NAME = "local-tasks-bridge"
APP_BUNDLE_ID = "io.github.siyuanj.LocalTasksBridge"
LAUNCH_AGENT_LABEL = "io.github.siyuanj.local-tasks-bridge"
PROJECT_URL = "https://github.com/siyuanj/local-tasks-bridge"
# Earlier installations (the upstream project and the 2026-09 private trial)
# used these names. They are only read to migrate or retire old installs.
LEGACY_APP_NAME = "icloud-reminders-google-sync"
LEGACY_LAUNCH_AGENT_LABEL = "com.icloud-reminders-google-sync"
LEGACY_TRIAL_CONFIG_DIR_NAME = "reminders-task-bridge-trial"
ENGINE_DIR = Path(__file__).resolve().parent
ENGINE_FILENAME = Path(__file__).name
SYNC_MARKER_KEY = "irsync"
SYNC_MARKER_VALUE = "v1"
UID_KEY = "iruid"
DIGEST_KEY = "irdigest"


def endpoint_override(name: str, default: str) -> str:
    """Return a Google endpoint, optionally redirected for local testing.

    Only HTTPS endpoints or plain HTTP on the loopback interface are accepted,
    so an override can point the engine at a local test double but can never
    send tokens over the network unencrypted.
    """

    value = str(os.environ.get(name) or "").strip().rstrip("/")
    if not value:
        return default
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme == "https" and parsed.hostname:
        return value
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return value
    raise SystemExit(f"{name} must be an https:// URL or an http:// loopback URL.")


CALENDAR_API = endpoint_override("LTB_CALENDAR_API", "https://www.googleapis.com/calendar/v3")
TASKS_API = endpoint_override("LTB_TASKS_API", "https://tasks.googleapis.com/tasks/v1")
OAUTH_AUTH_URL = endpoint_override("LTB_OAUTH_AUTH_URL", "https://accounts.google.com/o/oauth2/v2/auth")
OAUTH_TOKEN_URL = endpoint_override("LTB_OAUTH_TOKEN_URL", "https://oauth2.googleapis.com/token")
OAUTH_USERINFO_URL = endpoint_override("LTB_OAUTH_USERINFO_URL", "https://openidconnect.googleapis.com/v1/userinfo")
OAUTH_REVOKE_URL = endpoint_override("LTB_OAUTH_REVOKE_URL", "https://oauth2.googleapis.com/revoke")
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"
TASKS_SCOPE = "https://www.googleapis.com/auth/tasks"
LOCAL_OAUTH_SCOPES = " ".join([CALENDAR_SCOPE, TASKS_SCOPE, "openid", "email"])
APPLE_EPOCH_OFFSET_SECONDS = 978307200
GCLOUD_LOGIN_SCOPES = ",".join(
    [
        CALENDAR_SCOPE,
        TASKS_SCOPE,
        "https://www.googleapis.com/auth/cloud-platform",
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
    ]
)
LIST_POLICY_DIRECTIONS = {"bidirectional", "apple_to_google", "google_to_apple"}
LIST_POLICY_KEYS = {"direction", "delete_propagation", "sync_undated", "conflict_policy"}
CONFLICT_POLICIES = {"skip", "newer_wins"}
SAFE_OAUTH_ERROR_CODES = {
    "access_denied",
    "invalid_client",
    "invalid_grant",
    "invalid_request",
    "server_error",
    "temporarily_unavailable",
    "unauthorized_client",
    "unsupported_grant_type",
}
KNOWN_STATUS_STATES = {
    "account_binding_required",
    "auth_prompt_open",
    "auth_refreshed",
    "auth_required",
    "auth_timeout",
    "awaiting_mutation_approval",
    "blocked_mutation_plan",
    "dry_run_ok",
    "failed",
    "ok",
    "paused",
    "running",
}
OAUTH_CLIENT_MODES = {"auto", "custom", "bundled"}
SUPPORTED_LANGUAGES = ("en", "zh")
LANGUAGE_PREFERENCES = {"auto", *SUPPORTED_LANGUAGES}
EVENT_STREAM_PREFIX = "@@LTB "
DEFAULT_LOG_MAX_BYTES = 5 * 1024 * 1024
SYNC_NOW_POLL_SECONDS = 1.0
MIN_SYNC_INTERVAL_SECONDS = 60


# --- Language -------------------------------------------------------------
#
# Every message a person reads (the manager, doctor, status, notifications and
# the bulk-change dialog) is available in English and Simplified Chinese. Log
# lines and machine-readable output stay English so they remain stable for
# support and for the app that parses them.

_LANGUAGE: str | None = None


def normalize_language(value: Any) -> str | None:
    text = str(value or "").strip().lower().replace("_", "-")
    if not text or text in {"c", "posix"} or text.startswith(("c.", "posix.")):
        return None
    if text.startswith("zh"):
        return "zh"
    if text.startswith("en"):
        return "en"
    return "other"


def macos_preferred_language() -> str | None:
    if sys.platform != "darwin" or not shutil.which("defaults"):
        return None
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleLanguages"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    for raw_line in result.stdout.splitlines():
        candidate = raw_line.strip().strip('(),"').strip()
        if candidate:
            return candidate
    return None


def detect_language(preference: Any = None) -> str:
    """Pick "en" or "zh": explicit preference, LTB_LANG, locale, then macOS."""

    explicit = normalize_language(preference) if str(preference or "auto") != "auto" else None
    if explicit in SUPPORTED_LANGUAGES:
        return explicit
    for name in ("LTB_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        detected = normalize_language(os.environ.get(name))
        if detected in SUPPORTED_LANGUAGES:
            return detected
        if detected == "other" and name == "LTB_LANG":
            return "en"
    detected = normalize_language(macos_preferred_language())
    return detected if detected in SUPPORTED_LANGUAGES else "en"


def set_language(language: str | None) -> str:
    global _LANGUAGE
    _LANGUAGE = language if language in SUPPORTED_LANGUAGES else detect_language(language)
    return _LANGUAGE


def current_language() -> str:
    if _LANGUAGE is None:
        return set_language(None)
    return _LANGUAGE


def tr(en: str, zh: str) -> str:
    """Return the message in the active language."""

    return zh if current_language() == "zh" else en


def default_config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / APP_NAME


CONFIG_PATH_KEYS = ("credentials_path", "token_path", "state_path", "status_path")
CONFIG_PATH_DEFAULT_NAMES = {
    "credentials_path": "credentials.json",
    "token_path": "token.json",
    "state_path": "state.json",
    "status_path": "status.json",
}
CONFIG_VERSION = 2


def default_config() -> dict[str, Any]:
    """Engine defaults for keys a config file does not set."""

    config_dir = default_config_dir()
    return {
        "language": "auto",
        "oauth_client": "auto",
        "proxy": "",
        "manual_oauth_browser": False,
        "trigger_min_interval_seconds": 10,
        "use_adc": False,
        "adc_credentials_path": str(Path.home() / ".config/gcloud/application_default_credentials.json"),
        "credentials_path": str(config_dir / "credentials.json"),
        "token_path": str(config_dir / "token.json"),
        "state_path": str(config_dir / "state.json"),
        "status_path": str(config_dir / "status.json"),
        "auto_reauth_browser": False,
        "auto_reauth_min_interval_seconds": 21600,
        "auto_reauth_timeout_seconds": 300,
        "auto_reauth_timeout_retry_interval_seconds": 300,
        "macos_notifications": True,
        "notify_success_min_interval_seconds": 3600,
        "notify_failure_min_interval_seconds": 300,
        "verify_title_due_after_sync": True,
        "verify_title_due_retry_attempts": 3,
        "verify_title_due_retry_delay_seconds": 2.0,
        "max_destructive_changes": 25,
        "max_destructive_ratio": 0.25,
        "destructive_approval_ttl_seconds": 600,
        "auto_approve_destructive_loops": 0,
        "mutation_approval_prompt": True,
        "mutation_approval_prompt_repeat_seconds": 21600,
        # Empty means "find the helper that ships with this engine".
        "reminders_exporter_path": "",
        "reminders_apply_path": "",
        "reminders_source": "auto",
        "reminders_sqlite_dir": str(Path.home() / "Library/Group Containers/group.com.apple.reminders/Container_v1/Stores"),
        "target_service": "tasks",
        "calendar_id": "primary",
        "tasks_list_id": "",
        "tasks_list_title": "",
        "tasks_mirror_lists": True,
        "tasks_mirror_empty_lists": True,
        "tasks_create_missing_lists": True,
        "tasks_complete_stale": True,
        "tasks_import_unsynced": False,
        "tasks_sync_undated": False,
        "lookahead_days": 365,
        "sync_interval_seconds": 900,
        "default_duration_minutes": 30,
        "include_lists": [],
        "list_policies": {},
        "prefix_list": False,
        "delete_stale": True,
        "allow_empty_source_delete": False,
        "bidirectional": False,
        "conflict_policy": "newer_wins",
        "transparency": "transparent",
        "google_popup_minutes": [],
    }


def product_default_config() -> dict[str, Any]:
    """The choices a new installation starts with.

    Two-way sync of the selected lists, including undated reminders and
    existing Google tasks, with completions and deletions propagated inside
    the destructive-change safety limits.
    """

    return {
        "config_version": CONFIG_VERSION,
        "language": "auto",
        "oauth_client": "auto",
        "proxy": "",
        "target_service": "tasks",
        "reminders_source": "eventkit",
        "include_lists": [],
        "list_policies": {},
        "bidirectional": True,
        "delete_stale": True,
        "allow_empty_source_delete": False,
        "conflict_policy": "newer_wins",
        "tasks_mirror_lists": True,
        "tasks_mirror_empty_lists": True,
        "tasks_create_missing_lists": True,
        "tasks_complete_stale": True,
        "tasks_import_unsynced": True,
        "tasks_sync_undated": True,
        "sync_interval_seconds": 60,
        "max_destructive_changes": 25,
        "max_destructive_ratio": 0.25,
        "auto_approve_destructive_loops": 0,
        "mutation_approval_prompt": True,
        "macos_notifications": True,
        "auto_reauth_browser": False,
        "verify_title_due_after_sync": True,
    }


class GoogleApiError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(google_api_failure_summary(status))


class OAuthTokenError(RuntimeError):
    def __init__(self, status: int, body: str, payload: dict[str, Any] | None = None) -> None:
        self.status = status
        self.body = body
        self.payload = payload or {}
        error = str(self.payload.get("error") or "")
        description = str(self.payload.get("error_description") or body)
        self.error = error
        self.error_description = description
        suffix = f", code={error}" if error in SAFE_OAUTH_ERROR_CODES else ""
        super().__init__(f"Google OAuth token request failed (HTTP {status}{suffix}).")

    @property
    def invalid_grant(self) -> bool:
        return self.error == "invalid_grant"


class AuthenticationRequired(RuntimeError):
    pass


class AccountBindingRequired(RuntimeError):
    pass


class OAuthCallbackTimeout(RuntimeError):
    pass


class RemindersUnavailable(SystemExit):
    """The EventKit helper could not read or write Apple Reminders."""


class OAuthClientMissing(SystemExit):
    """No usable Google OAuth client (neither the user's own nor a bundled one)."""


def google_api_failure_summary(status: int) -> str:
    if status in (401, 403):
        action = "Reauthorize Google access and confirm the Tasks API permission."
    elif status == 429:
        action = "Google rate-limited the request; wait before retrying."
    elif status >= 500:
        action = "Google is temporarily unavailable; retry later."
    else:
        action = "Review the private log, then retry the diagnostic."
    return f"Google API request failed (HTTP {status}). {action}"


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def harden_log_stream_mode(stream: Any) -> None:
    """Make a redirected log file private to this user.

    The LaunchAgent writes reminder and task titles to its stdout/stderr files.
    launchd recreates a missing StandardOutPath/StandardErrorPath itself, so an
    install-time chmod does not survive; re-apply 0600 to our own descriptor at
    startup. Working on the open descriptor rather than a path means a symlink
    or a replaced file cannot redirect the permission change.
    """

    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError):
        return
    try:
        info = os.fstat(fd)
    except OSError:
        return
    if not stat.S_ISREG(info.st_mode):
        return
    if info.st_uid != os.getuid():
        return
    if not stat.S_IMODE(info.st_mode) & 0o077:
        return
    try:
        os.fchmod(fd, 0o600)
    except OSError:
        pass


def harden_runtime_log_modes() -> None:
    for stream in (sys.stdout, sys.stderr):
        harden_log_stream_mode(stream)


def expand_path(value: str | os.PathLike[str]) -> Path:
    return Path(value).expanduser().resolve()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(path)


@contextlib.contextmanager
def sync_lock(config: dict[str, Any], wait: bool) -> Any:
    lock_path = expand_path(config["state_path"]).with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as handle:
        flags = fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(handle.fileno(), flags)
        except BlockingIOError:
            yield False
            return

        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(value: str, length: int | None = None) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return digest[:length] if length else digest


class MutationPlanApprovalRequired(SystemExit):
    def __init__(
        self,
        message: str,
        summary: dict[str, Any],
        review: dict[str, Any] | None = None,
    ) -> None:
        self.summary = summary
        # Titles and list names for the signed-in user's own approval prompt.
        # They are never written to status.json or the logs; `summary` is the
        # sanitized half that is.
        self.review = review or {}
        super().__init__(message)


class MutationPlanPreview(Exception):
    """Raised in place of any write when a caller asked only for the plan."""

    def __init__(self, plan: dict[str, Any], reasons: list[str]) -> None:
        self.plan = plan
        self.reasons = reasons
        super().__init__("mutation plan preview")


def planned_mutation(
    target: str,
    operation: str,
    identity: Any,
    *,
    destructive: bool = False,
    list_title: str = "",
    title: str = "",
) -> dict[str, Any]:
    action: dict[str, Any] = {
        "target": target,
        "operation": operation,
        "resource": sha256_text(canonical_json(identity), 24),
        "destructive": bool(destructive),
    }
    if destructive:
        # A local-only label so a person can review what a large plan would
        # delete or complete. It is excluded from every fingerprint and from
        # the sanitized summary.
        action["review"] = {"list": str(list_title or ""), "title": str(title or "")}
    return action


def build_mutation_plan(actions: list[dict[str, Any]], population: int) -> dict[str, Any]:
    normalized = sorted(
        (
            {
                "target": str(action["target"]),
                "operation": str(action["operation"]),
                "resource": str(action["resource"]),
                "destructive": bool(action.get("destructive")),
            }
            for action in actions
        ),
        key=lambda action: (
            action["target"],
            action["operation"],
            action["resource"],
            action["destructive"],
        ),
    )
    counts: dict[str, int] = {}
    destructive_counts: dict[str, int] = {}
    for action in normalized:
        key = f"{action['target']}.{action['operation']}"
        counts[key] = counts.get(key, 0) + 1
        if action["destructive"]:
            destructive_counts[key] = destructive_counts.get(key, 0) + 1

    destructive_count = sum(destructive_counts.values())
    safe_population = max(0, int(population))
    destructive_ratio = destructive_count / safe_population if safe_population else float(bool(destructive_count))
    fingerprint_material = {
        "version": 1,
        "population": safe_population,
        "actions": normalized,
    }
    # The exact set of deletions and completions, independent of unrelated
    # creates and updates. A person approves this set, so an approval stays
    # valid when a new reminder appears but not when one more item would go.
    destructive_material = {
        "version": 1,
        "actions": [action for action in normalized if action["destructive"]],
    }
    review_items = sorted(
        (
            {
                "operation": f"{action['target']}.{action['operation']}",
                "list": str((action.get("review") or {}).get("list") or ""),
                "title": str((action.get("review") or {}).get("title") or ""),
            }
            for action in actions
            if action.get("destructive")
        ),
        key=lambda item: (item["operation"], item["list"], item["title"]),
    )
    return {
        "version": 1,
        "actions": normalized,
        "counts": dict(sorted(counts.items())),
        "destructive_counts": dict(sorted(destructive_counts.items())),
        "total_count": len(normalized),
        "destructive_count": destructive_count,
        "population": safe_population,
        "destructive_ratio": destructive_ratio,
        "fingerprint": sha256_text(canonical_json(fingerprint_material)),
        "destructive_fingerprint": sha256_text(canonical_json(destructive_material)),
        "review_items": review_items,
    }


def mutation_plan_review(plan: dict[str, Any]) -> dict[str, Any]:
    """The local-only view of a plan that a person reviews before approving it."""
    return {
        "destructive_fingerprint": str(plan.get("destructive_fingerprint") or ""),
        "destructive_count": int(plan.get("destructive_count") or 0),
        "population": int(plan.get("population") or 0),
        "destructive_ratio": float(plan.get("destructive_ratio") or 0.0),
        "items": [dict(item) for item in plan.get("review_items") or []],
    }


def mutation_plan_limit_reasons(config: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if int(plan["destructive_count"]) > int(config["max_destructive_changes"]):
        reasons.append("destructive_count_limit")
    if float(plan["destructive_ratio"]) > float(config["max_destructive_ratio"]):
        reasons.append("destructive_ratio_limit")
    return reasons


def mutation_plan_approval_token(
    plan: dict[str, Any],
    issued_at: dt.datetime | None = None,
) -> str:
    now = issued_at or dt.datetime.now(dt.timezone.utc)
    return f"{plan['fingerprint']}:{int(now.timestamp())}"


def next_blocked_plan_streak(
    previous_fingerprint: str,
    previous_streak: int,
    fingerprint: str,
) -> tuple[str, int]:
    """Track how many consecutive loop iterations produced the identical blocked plan."""
    if fingerprint and fingerprint == previous_fingerprint:
        return fingerprint, previous_streak + 1
    return fingerprint, 1 if fingerprint else 0


def should_auto_approve_blocked_plan(config: dict[str, Any], streak: int) -> bool:
    loops = int(config.get("auto_approve_destructive_loops", 0) or 0)
    return loops > 0 and streak >= loops


def validate_mutation_plan_approval(
    config: dict[str, Any],
    plan: dict[str, Any],
    approval: str,
    *,
    now: dt.datetime | None = None,
    fingerprint_key: str = "fingerprint",
) -> tuple[bool, str]:
    if not approval:
        return False, "approval_missing"
    fingerprint, separator, raw_timestamp = approval.rpartition(":")
    if not separator or len(fingerprint) != 64 or not raw_timestamp.isdigit() or not fingerprint.isascii():
        return False, "approval_invalid"
    expected = str(plan.get(fingerprint_key) or "")
    if not expected.isascii() or not secrets.compare_digest(fingerprint, expected):
        return False, "approval_fingerprint_mismatch"

    checked_at = now or dt.datetime.now(dt.timezone.utc)
    issued_at = dt.datetime.fromtimestamp(int(raw_timestamp), tz=dt.timezone.utc)
    age_seconds = (checked_at - issued_at).total_seconds()
    if age_seconds < -60:
        return False, "approval_from_future"
    if age_seconds > int(config["destructive_approval_ttl_seconds"]):
        return False, "approval_expired"
    return True, "approved"


def sanitized_mutation_plan(plan: dict[str, Any], reasons: list[str] | None = None) -> dict[str, Any]:
    return {
        "version": int(plan["version"]),
        "fingerprint": str(plan["fingerprint"]),
        "total_count": int(plan["total_count"]),
        "destructive_count": int(plan["destructive_count"]),
        "population": int(plan["population"]),
        "destructive_ratio": round(float(plan["destructive_ratio"]), 6),
        "counts": dict(plan["counts"]),
        "destructive_counts": dict(plan["destructive_counts"]),
        "destructive_fingerprint": str(plan.get("destructive_fingerprint") or ""),
        "reasons": list(reasons or []),
    }


def enforce_mutation_plan(
    config: dict[str, Any],
    plan: dict[str, Any],
    *,
    dry_run: bool,
    now: dt.datetime | None = None,
) -> None:
    reasons = mutation_plan_limit_reasons(config, plan)
    ratio_percent = float(plan["destructive_ratio"]) * 100
    print(
        "Mutation plan: "
        f"total={plan['total_count']}, destructive={plan['destructive_count']}, "
        f"population={plan['population']}, destructive_ratio={ratio_percent:.2f}%"
    )
    print(f"Mutation plan fingerprint: {plan['fingerprint']}")
    # Counts and hashes only, for `sync --json`; never titles.
    config["_last_mutation_plan"] = sanitized_mutation_plan(plan, reasons)
    if config.get("_mutation_plan_preview"):
        # Every write in both sync modes happens after this point, so a
        # preview can return the complete plan without touching anything.
        raise MutationPlanPreview(plan, reasons)
    if not reasons:
        return

    if dry_run:
        token = mutation_plan_approval_token(plan, issued_at=now)
        print("Destructive mutation plan exceeds the configured safety limit.")
        print(f"Short-lived approval token: {token}")
        return

    approved, approval_reason = validate_mutation_plan_approval(
        config,
        plan,
        str(config.get("_mutation_plan_approval") or ""),
        now=now,
    )
    destructive_approval = str(config.get("_mutation_plan_destructive_approval") or "")
    if not approved and destructive_approval:
        # Set only internally, after a person reviewed exactly this set of
        # deletions and completions in the prompt or the manager.
        approved, approval_reason = validate_mutation_plan_approval(
            config,
            plan,
            destructive_approval,
            now=now,
            fingerprint_key="destructive_fingerprint",
        )
    if approved:
        print("Destructive mutation plan approval accepted.")
        return

    block_reasons = [*reasons, approval_reason]
    summary = sanitized_mutation_plan(plan, block_reasons)
    message = (
        "Mutation plan blocked before Apple/Google writes: "
        f"destructive={plan['destructive_count']}, population={plan['population']}, "
        f"ratio={ratio_percent:.2f}%, reason={approval_reason}. "
        "Run a dry-run and pass its matching short-lived token with --approve-mutation-plan."
    )
    write_sync_status(
        config,
        {
            "state": "blocked_mutation_plan",
            "last_end_at": utc_now_text(),
            "last_error": message,
            "mutation_plan": summary,
        },
    )
    raise MutationPlanApprovalRequired(message, summary, mutation_plan_review(plan))


def state_key(calendar_id: str, uid: str) -> str:
    return f"{sha256_text(calendar_id, 12)}:{uid}"


def target_state_key(target_id: str, uid: str) -> str:
    return f"{sha256_text(target_id, 12)}:{uid}"


def normalize_list_policies(value: Any) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SystemExit("list_policies must be a JSON object keyed by Apple Reminders list title")

    normalized: dict[str, dict[str, Any]] = {}
    for raw_title, raw_policy in value.items():
        if not isinstance(raw_title, str) or not raw_title.strip():
            raise SystemExit("list_policies keys must be non-empty Apple Reminders list titles")
        if not isinstance(raw_policy, dict):
            raise SystemExit(f"list_policies[{raw_title!r}] must be a JSON object")

        unknown = sorted(set(raw_policy) - LIST_POLICY_KEYS)
        if unknown:
            raise SystemExit(
                f"Unsupported list_policies field(s) for {raw_title!r}: {', '.join(unknown)}. "
                f"Supported fields: {', '.join(sorted(LIST_POLICY_KEYS))}"
            )

        policy: dict[str, Any] = {}
        if "direction" in raw_policy:
            direction = raw_policy["direction"]
            if not isinstance(direction, str) or direction not in LIST_POLICY_DIRECTIONS:
                raise SystemExit(
                    f"Unsupported direction for list_policies[{raw_title!r}]. "
                    "Supported values: apple_to_google, google_to_apple, bidirectional"
                )
            policy["direction"] = direction

        for key in ("delete_propagation", "sync_undated"):
            if key not in raw_policy:
                continue
            if not isinstance(raw_policy[key], bool):
                raise SystemExit(f"list_policies[{raw_title!r}].{key} must be true or false")
            policy[key] = raw_policy[key]

        if "conflict_policy" in raw_policy:
            conflict_policy = raw_policy["conflict_policy"]
            if not isinstance(conflict_policy, str) or conflict_policy not in CONFLICT_POLICIES:
                raise SystemExit(
                    f"Unsupported conflict_policy for list_policies[{raw_title!r}]. "
                    "Supported values: skip, newer_wins"
                )
            policy["conflict_policy"] = conflict_policy

        normalized[raw_title] = policy
    return normalized


def list_sync_policy(config: dict[str, Any], list_title: str) -> dict[str, Any]:
    policies = config.get("list_policies") or {}
    override = policies.get(list_title, {}) if isinstance(policies, dict) else {}
    default_direction = "bidirectional" if config.get("bidirectional") else "apple_to_google"
    return {
        "direction": override.get("direction", default_direction),
        "delete_propagation": override.get("delete_propagation", bool(config.get("delete_stale"))),
        "sync_undated": override.get("sync_undated", bool(config.get("tasks_sync_undated"))),
        "conflict_policy": override.get("conflict_policy", str(config.get("conflict_policy") or "skip")),
    }


def list_allows_apple_to_google(config: dict[str, Any], list_title: str) -> bool:
    return list_sync_policy(config, list_title)["direction"] in ("apple_to_google", "bidirectional")


def list_allows_google_to_apple(config: dict[str, Any], list_title: str) -> bool:
    return list_sync_policy(config, list_title)["direction"] in ("google_to_apple", "bidirectional")


def list_allows_delete_propagation(
    config: dict[str, Any],
    list_title: str,
    *,
    safety_allows_deletes: bool = True,
) -> bool:
    if config.get("_disable_delete_propagation"):
        return False
    return bool(safety_allows_deletes and list_sync_policy(config, list_title)["delete_propagation"])


def reminders_export_needs_undated(config: dict[str, Any]) -> bool:
    if config.get("tasks_sync_undated"):
        return True
    if str(config.get("target_service") or "tasks") != "tasks":
        return False
    policies = config.get("list_policies") or {}
    return bool(
        isinstance(policies, dict)
        and any(isinstance(policy, dict) and policy.get("sync_undated") is True for policy in policies.values())
    )


def reminder_is_undated(reminder: dict[str, Any]) -> bool:
    return task_due_date(reminder) is None


def load_config(args: argparse.Namespace) -> dict[str, Any]:
    config = default_config()
    config_path = expand_path(args.config)
    loaded: dict[str, Any] = {}

    if config_path.exists():
        loaded = read_json(config_path)
        if not isinstance(loaded, dict):
            raise SystemExit(f"Config file is not a JSON object: {config_path}")
        config.update(loaded)

    # Private files live next to the config unless the config says otherwise,
    # so --config can point at a self-contained directory.
    for key in CONFIG_PATH_KEYS:
        if key not in loaded:
            config[key] = str(config_path.parent / CONFIG_PATH_DEFAULT_NAMES[key])

    for key in (
        "language",
        "proxy",
        "oauth_client",
        "credentials_path",
        "adc_credentials_path",
        "token_path",
        "state_path",
        "status_path",
        "auto_reauth_browser",
        "auto_reauth_min_interval_seconds",
        "auto_reauth_timeout_seconds",
        "auto_reauth_timeout_retry_interval_seconds",
        "macos_notifications",
        "notify_success_min_interval_seconds",
        "notify_failure_min_interval_seconds",
        "verify_title_due_after_sync",
        "verify_title_due_retry_attempts",
        "verify_title_due_retry_delay_seconds",
        "max_destructive_changes",
        "max_destructive_ratio",
        "destructive_approval_ttl_seconds",
        "reminders_exporter_path",
        "reminders_apply_path",
        "reminders_source",
        "reminders_sqlite_dir",
        "target_service",
        "calendar_id",
        "tasks_list_id",
        "tasks_list_title",
        "tasks_mirror_lists",
        "tasks_mirror_empty_lists",
        "tasks_create_missing_lists",
        "tasks_complete_stale",
        "tasks_import_unsynced",
        "tasks_sync_undated",
        "lookahead_days",
        "sync_interval_seconds",
        "default_duration_minutes",
        "include_lists",
        "list_policies",
        "prefix_list",
        "delete_stale",
        "allow_empty_source_delete",
        "bidirectional",
        "conflict_policy",
        "transparency",
        "google_popup_minutes",
        "use_adc",
    ):
        if hasattr(args, key) and getattr(args, key) is not None:
            config[key] = getattr(args, key)

    if getattr(args, "no_adc", False):
        config["use_adc"] = False
    if getattr(args, "no_delete_stale", False):
        config["delete_stale"] = False
    config["_disable_delete_propagation"] = bool(getattr(args, "no_delete_stale", False))
    if getattr(args, "no_tasks_mirror_lists", False):
        config["tasks_mirror_lists"] = False
    if getattr(args, "no_tasks_mirror_empty_lists", False):
        config["tasks_mirror_empty_lists"] = False
    if getattr(args, "no_tasks_create_missing_lists", False):
        config["tasks_create_missing_lists"] = False
    if getattr(args, "no_tasks_complete_stale", False):
        config["tasks_complete_stale"] = False
    if getattr(args, "tasks_import_unsynced", False):
        config["tasks_import_unsynced"] = True
    if getattr(args, "no_tasks_import_unsynced", False):
        config["tasks_import_unsynced"] = False
    if getattr(args, "tasks_sync_undated", False):
        config["tasks_sync_undated"] = True
    if getattr(args, "no_tasks_sync_undated", False):
        config["tasks_sync_undated"] = False
    if getattr(args, "no_macos_notifications", False):
        config["macos_notifications"] = False
    if getattr(args, "no_verify_title_due_after_sync", False):
        config["verify_title_due_after_sync"] = False
    if getattr(args, "busy", False):
        config["transparency"] = "opaque"

    for path_key in (
        "credentials_path",
        "adc_credentials_path",
        "token_path",
        "state_path",
        "status_path",
        "reminders_sqlite_dir",
    ):
        config[path_key] = str(expand_path(config[path_key]))
    for path_key in ("reminders_exporter_path", "reminders_apply_path"):
        value = str(config.get(path_key) or "").strip()
        config[path_key] = str(expand_path(value)) if value else ""

    config["_config_path"] = str(config_path)
    config["auto_reauth_browser"] = bool(config.get("auto_reauth_browser"))
    config["auto_reauth_min_interval_seconds"] = int(config.get("auto_reauth_min_interval_seconds") or 21600)
    config["auto_reauth_timeout_seconds"] = int(config.get("auto_reauth_timeout_seconds") or 300)
    config["auto_reauth_timeout_retry_interval_seconds"] = int(
        config.get("auto_reauth_timeout_retry_interval_seconds") or 300
    )
    config["macos_notifications"] = bool(config.get("macos_notifications"))
    config["notify_success_min_interval_seconds"] = int(config.get("notify_success_min_interval_seconds") or 3600)
    config["notify_failure_min_interval_seconds"] = int(config.get("notify_failure_min_interval_seconds") or 300)
    config["verify_title_due_after_sync"] = bool(config.get("verify_title_due_after_sync"))
    config["verify_title_due_retry_attempts"] = max(1, int(config.get("verify_title_due_retry_attempts") or 1))
    config["verify_title_due_retry_delay_seconds"] = max(
        0.0,
        float(config.get("verify_title_due_retry_delay_seconds") or 0.0),
    )
    config["max_destructive_changes"] = max(0, int(config.get("max_destructive_changes") or 0))
    config["max_destructive_ratio"] = min(
        1.0,
        max(0.0, float(config.get("max_destructive_ratio") or 0.0)),
    )
    config["destructive_approval_ttl_seconds"] = max(
        60,
        int(config.get("destructive_approval_ttl_seconds") or 600),
    )
    config["mutation_approval_prompt"] = bool(config.get("mutation_approval_prompt"))
    config["mutation_approval_prompt_repeat_seconds"] = max(
        600,
        int(config.get("mutation_approval_prompt_repeat_seconds") or 21600),
    )
    config["_mutation_plan_approval"] = str(getattr(args, "approve_mutation_plan", "") or "").strip()
    config["lookahead_days"] = int(config["lookahead_days"])
    config["sync_interval_seconds"] = int(config["sync_interval_seconds"])
    config["default_duration_minutes"] = int(config["default_duration_minutes"])
    config["include_lists"] = list(config.get("include_lists") or [])
    config["list_policies"] = normalize_list_policies(config.get("list_policies"))
    config["google_popup_minutes"] = [int(value) for value in config.get("google_popup_minutes") or []]
    config["prefix_list"] = bool(config.get("prefix_list"))
    config["delete_stale"] = bool(config.get("delete_stale"))
    config["allow_empty_source_delete"] = bool(config.get("allow_empty_source_delete"))
    config["bidirectional"] = bool(config.get("bidirectional"))
    config["tasks_mirror_lists"] = bool(config.get("tasks_mirror_lists"))
    config["tasks_mirror_empty_lists"] = bool(config.get("tasks_mirror_empty_lists"))
    config["tasks_create_missing_lists"] = bool(config.get("tasks_create_missing_lists"))
    config["tasks_complete_stale"] = bool(config.get("tasks_complete_stale"))
    config["tasks_import_unsynced"] = bool(config.get("tasks_import_unsynced"))
    config["tasks_sync_undated"] = bool(config.get("tasks_sync_undated"))
    config["use_adc"] = bool(config.get("use_adc"))
    config["reminders_source"] = str(config.get("reminders_source") or "auto")
    config["target_service"] = str(config.get("target_service") or "tasks")
    config["tasks_list_id"] = str(config.get("tasks_list_id") or "")
    config["tasks_list_title"] = str(config.get("tasks_list_title") or "")
    config["conflict_policy"] = str(config.get("conflict_policy") or "skip")
    config["transparency"] = str(config.get("transparency") or "transparent")
    if config["target_service"] not in ("tasks", "calendar"):
        raise SystemExit("Unsupported target_service. Supported values: tasks, calendar")
    if config["conflict_policy"] not in CONFLICT_POLICIES:
        raise SystemExit("Unsupported conflict_policy. Currently supported: skip, newer_wins")
    config["language"] = str(config.get("language") or "auto").strip().lower()
    if config["language"] not in LANGUAGE_PREFERENCES:
        raise SystemExit("Unsupported language. Supported values: auto, en, zh")
    config["oauth_client"] = str(config.get("oauth_client") or "auto").strip().lower()
    if config["oauth_client"] not in OAUTH_CLIENT_MODES:
        raise SystemExit("Unsupported oauth_client. Supported values: auto, custom, bundled")
    config["proxy"] = normalize_proxy_setting(config.get("proxy"))
    config["manual_oauth_browser"] = bool(config.get("manual_oauth_browser"))
    config["trigger_min_interval_seconds"] = max(0, int(config.get("trigger_min_interval_seconds") or 0))
    set_language(detect_language(config["language"]))
    return config


def normalize_proxy_setting(value: Any) -> str:
    """"" uses the environment or macOS system proxy, "none" connects directly."""

    text = str(value or "").strip()
    if not text or text.lower() == "auto":
        return ""
    if text.lower() in {"none", "direct", "off"}:
        return "none"
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SystemExit("proxy must be empty (system proxy), \"none\", or an http://host:port URL.")
    try:
        parsed.port
    except ValueError as exc:
        raise SystemExit("proxy has an invalid port.") from exc
    return text


def proxy_handler_for(setting: str) -> urllib.request.ProxyHandler | None:
    if setting == "none":
        return urllib.request.ProxyHandler({})
    if setting:
        return urllib.request.ProxyHandler({"http": setting, "https": setting})
    return None


def apply_network_config(config: dict[str, Any]) -> None:
    """Route Google requests through the configured proxy.

    Without a setting, urllib already honours HTTP(S)_PROXY and, on macOS, the
    system proxy from System Settings. Many users in mainland China reach
    Google only through a local proxy, so the app can pin one explicitly.
    """

    handler = proxy_handler_for(str(config.get("proxy") or ""))
    if handler is None:
        return
    urllib.request.install_opener(urllib.request.build_opener(handler))


def load_credentials(path: Path) -> dict[str, str]:
    if not path.exists():
        raise OAuthClientMissing(
            tr(
                f"Google OAuth client file not found: {path}\n"
                "Create a Desktop app OAuth client in your Google Cloud project with the Google Tasks API "
                "enabled, download its JSON, and import it with `ltb client import <file>` "
                "(or from the app's setup assistant).",
                f"找不到 Google OAuth 客户端文件：{path}\n"
                "请在你的 Google Cloud 项目中启用 Google Tasks API，创建“桌面应用”类型的 OAuth 客户端，"
                "下载 JSON 后用 `ltb client import <文件>` 导入（或在 App 的设置向导中导入）。",
            )
        )

    raw = read_json(path)
    client = raw.get("installed") or raw.get("web") or raw
    client_id = client.get("client_id")
    client_secret = client.get("client_secret", "")
    if not client_id:
        raise SystemExit(f"Could not find client_id in {path}")
    return {"client_id": client_id, "client_secret": client_secret}


def validate_oauth_client_document(raw: Any) -> dict[str, str]:
    """Accept only a Google "Desktop app" client, the type loopback OAuth needs."""

    if not isinstance(raw, dict):
        raise SystemExit(tr("The OAuth client file is not a JSON object.", "OAuth 客户端文件不是 JSON 对象。"))
    if "web" in raw and "installed" not in raw:
        raise SystemExit(
            tr(
                "This is a \"Web application\" OAuth client. Create a client of type \"Desktop app\" "
                "in Google Cloud (Google Auth Platform → Clients) and download that JSON instead.",
                "这是“Web 应用”类型的 OAuth 客户端。请在 Google Cloud（Google Auth Platform → 客户端）"
                "中创建“桌面应用”类型的客户端，并下载那个 JSON。",
            )
        )
    client = raw.get("installed")
    if not isinstance(client, dict):
        raise SystemExit(
            tr(
                "This file is not a Google OAuth client. Download the JSON of a \"Desktop app\" client "
                "from Google Cloud (Google Auth Platform → Clients).",
                "这不是 Google OAuth 客户端文件。请从 Google Cloud（Google Auth Platform → 客户端）"
                "下载“桌面应用”客户端的 JSON。",
            )
        )
    client_id = str(client.get("client_id") or "").strip()
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise SystemExit(tr("The OAuth client file has no valid client_id.", "OAuth 客户端文件缺少有效的 client_id。"))
    return {"client_id": client_id, "client_secret": str(client.get("client_secret") or "")}


def bundled_oauth_client_path() -> Path | None:
    """The OAuth client a release build ships with, if any.

    Release builds may embed the maintainer's "Local Tasks Bridge" Desktop
    client as Resources/oauth_client.json. It is injected at build time and is
    never committed to the repository.
    """

    override = str(os.environ.get("LTB_BUNDLED_OAUTH_CLIENT") or "").strip()
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None
    candidate = ENGINE_DIR.parent / "oauth_client.json"
    return candidate if candidate.is_file() else None


def resolve_oauth_client(config: dict[str, Any]) -> tuple[str, dict[str, str]]:
    """Return ("custom" | "bundled", client) for a new Google sign-in."""

    mode = str(config.get("oauth_client") or "auto")
    custom_path = expand_path(config["credentials_path"])
    if mode == "custom" or (mode == "auto" and custom_path.exists()):
        return "custom", load_credentials(custom_path)
    bundled = bundled_oauth_client_path()
    if bundled is not None:
        return "bundled", validate_oauth_client_document(read_json(bundled))
    if mode == "bundled":
        raise OAuthClientMissing(
            tr(
                "This build does not include a shared Google OAuth client. Import your own Desktop app "
                "client with `ltb client import <file>`; see docs/google-cloud-setup.md.",
                "这个版本没有内置共享的 Google OAuth 客户端。请用 `ltb client import <文件>` 导入你自己的"
                "桌面应用客户端，步骤见 docs/google-cloud-setup.zh-CN.md。",
            )
        )
    return "custom", load_credentials(custom_path)


def oauth_client_status(config: dict[str, Any]) -> dict[str, Any]:
    custom_ready = expand_path(config["credentials_path"]).is_file()
    bundled_ready = bundled_oauth_client_path() is not None
    mode = str(config.get("oauth_client") or "auto")
    if mode == "custom" or (mode == "auto" and custom_ready):
        active = "custom" if custom_ready else "missing"
    elif bundled_ready:
        active = "bundled"
    else:
        active = "missing"
    return {"mode": mode, "active": active, "custom_ready": custom_ready, "bundled_available": bundled_ready}


def decode_jwt_payload(token: str) -> dict[str, Any]:
    """Read an ID token's claims.

    The token comes straight from Google's token endpoint over TLS, which is
    the case where OpenID Connect allows skipping signature validation. Only
    the subject is used, and only as a local, hashed account identity.
    """

    parts = str(token or "").split(".")
    if len(parts) != 3:
        return {}
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def google_account_subject(token: dict[str, Any]) -> str:
    """The stable Google account ID ("sub") behind a token, or ""."""

    claims = decode_jwt_payload(str((token or {}).get("id_token") or ""))
    subject = str(claims.get("sub") or "").strip()
    if subject:
        return subject
    return str((token or {}).get("_account_subject") or "").strip()


def load_adc_credentials(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    raw = read_json(path)
    if raw.get("type") != "authorized_user":
        raise SystemExit(f"Unsupported ADC credentials type in {path}: {raw.get('type')}")
    if not raw.get("refresh_token") or not raw.get("client_id"):
        raise SystemExit(
            f"ADC credentials are missing refresh_token/client_id: {path}\n"
            "Run: gcloud auth application-default login "
            f"--scopes={GCLOUD_LOGIN_SCOPES}"
        )

    raw["_credential_source"] = "gcloud_adc"
    return raw


def make_code_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")


def make_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


OAUTH_CALLBACK_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Local Tasks Bridge</title>
<style>body{font:16px -apple-system,BlinkMacSystemFont,sans-serif;margin:15vh auto;max-width:34em;
padding:0 1.5em;color:#1d1d1f}h1{font-size:1.5em}p{color:#555;line-height:1.5}</style></head>
<body><h1>Local Tasks Bridge</h1><p>%s</p><p>%s</p></body></html>
"""


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        # Only Google's redirect carries these parameters. A favicon request or
        # a stray local connection must not end the sign-in with a mismatch.
        if parsed.path not in ("", "/") or not any(key in params for key in ("code", "error", "state")):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.server.oauth_result = {key: values[0] for key, values in params.items()}  # type: ignore[attr-defined]

        if "error" in params:
            english = "Google sign-in was not completed. You can close this tab and try again from Local Tasks Bridge."
            chinese = "Google 登录没有完成。可以关闭此页面，然后在 Local Tasks Bridge 中重试。"
        else:
            english = "Google authorization received. You can close this tab and return to Local Tasks Bridge."
            chinese = "已收到 Google 授权。可以关闭此页面，回到 Local Tasks Bridge。"
        body = (OAUTH_CALLBACK_PAGE % (english, chinese)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: Any) -> None:
        return


# Failures after which the outcome of a request is unknown. Only reads are
# retried blindly; a completion is retried after reading the task back.
TRANSIENT_NETWORK_ERRORS = (
    urllib.error.URLError,
    http.client.HTTPException,
    ConnectionError,
    TimeoutError,
    socket.timeout,
)
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}


def is_transient_url_error(exc: urllib.error.URLError) -> bool:
    reason = getattr(exc, "reason", exc)
    text = str(reason).lower()
    return isinstance(reason, TimeoutError) or "timed out" in text or "timeout" in text


def post_form(url: str, fields: dict[str, str], attempts: int = 3) -> dict[str, Any]:
    data = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    last_error: urllib.error.URLError | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            payload = None
            try:
                decoded = json.loads(body)
                if isinstance(decoded, dict):
                    payload = decoded
            except json.JSONDecodeError:
                payload = None
            raise OAuthTokenError(exc.code, body, payload) from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt < attempts and is_transient_url_error(exc):
                time.sleep(min(2**attempt, 10))
                continue
            raise OAuthTokenError(0, f"OAuth request failed: {exc.reason}") from exc

    raise OAuthTokenError(0, f"OAuth request failed: {last_error}")


def open_auth_url(url: str) -> bool:
    if sys.platform == "darwin" and shutil.which("open"):
        result = subprocess.run(["open", url], check=False)
        if result.returncode == 0:
            return True

    return webbrowser.open(url)


def token_granted_scopes(token: dict[str, Any]) -> set[str]:
    return {scope for scope in str((token or {}).get("scope") or "").split() if scope}


def required_google_scope(config: dict[str, Any]) -> str:
    return TASKS_SCOPE if config.get("target_service", "tasks") == "tasks" else CALENDAR_SCOPE


def run_auth_flow(config: dict[str, Any]) -> dict[str, Any]:
    client_mode, credentials = resolve_oauth_client(config)
    token_path = expand_path(config["token_path"])
    verifier = make_code_verifier()
    state = secrets.token_urlsafe(24)

    server = http.server.HTTPServer(("127.0.0.1", 0), OAuthCallbackHandler)
    server.oauth_result = None  # type: ignore[attr-defined]
    server.timeout = 1
    redirect_uri = f"http://127.0.0.1:{server.server_address[1]}/"

    query = {
        "client_id": credentials["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join([required_google_scope(config), "openid", "email"]),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": make_code_challenge(verifier),
        "code_challenge_method": "S256",
    }
    auth_url = f"{OAUTH_AUTH_URL}?{urllib.parse.urlencode(query)}"

    print(
        tr(
            "Sign in with Google in your browser. Keep the Google Tasks permission checked.",
            "请在浏览器中登录 Google，并保持勾选 Google Tasks 权限。",
        ),
        flush=True,
    )
    if config.get("manual_oauth_browser") or not open_auth_url(auth_url):
        print(tr("Open this URL manually:", "请手动打开这个网址："), flush=True)
        print(auth_url, flush=True)

    timeout_seconds = max(60, int(config.get("auto_reauth_timeout_seconds") or 300))
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline and server.oauth_result is None:  # type: ignore[attr-defined]
        server.handle_request()

    result = server.oauth_result  # type: ignore[attr-defined]
    server.server_close()

    if not result:
        raise OAuthCallbackTimeout("Timed out waiting for Google OAuth callback.")
    if result.get("state") != state:
        raise SystemExit("OAuth state mismatch; refusing to save token.")
    if result.get("error"):
        raise AuthenticationRequired(
            tr(
                f"Google sign-in was not completed ({result['error']}).",
                f"Google 登录未完成（{result['error']}）。",
            )
        )
    if not result.get("code"):
        raise SystemExit("OAuth callback did not include an authorization code.")

    fields = {
        "code": result["code"],
        "client_id": credentials["client_id"],
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    if credentials.get("client_secret"):
        fields["client_secret"] = credentials["client_secret"]

    try:
        token = post_form(OAUTH_TOKEN_URL, fields)
    except OAuthTokenError as exc:
        raise SystemExit(str(exc)) from exc
    granted = token_granted_scopes(token)
    if granted and required_google_scope(config) not in granted:
        # Google's consent screen lets people untick individual permissions.
        raise AuthenticationRequired(
            tr(
                "Google did not grant access to Google Tasks. Sign in again and leave the "
                "\"Create, edit, organize, and delete all your tasks\" permission checked.",
                "Google 没有授予 Google Tasks 权限。请重新登录，并保持勾选"
                "“创建、修改、整理和删除你的所有任务”这一项。",
            )
        )
    token["created_at"] = int(time.time())
    token["expires_at"] = int(time.time()) + int(token.get("expires_in", 3600)) - 60
    token["_credential_source"] = "local_oauth"
    token["_oauth_client_mode"] = client_mode
    token["client_id"] = credentials["client_id"]
    if credentials.get("client_secret"):
        token["client_secret"] = credentials["client_secret"]
    subject = google_account_subject(token)
    if subject:
        token["_account_subject"] = subject
    write_json_atomic(token_path, token)
    print(tr(f"Saved Google OAuth token: {token_path}", f"已保存 Google OAuth 令牌：{token_path}"), flush=True)
    claims = decode_jwt_payload(str(token.get("id_token") or ""))
    return {
        "client_mode": client_mode,
        "account_email": " ".join(str(claims.get("email") or "").split()),
        "account_fingerprint": sha256_text(f"google-openid-sub\n{subject}", 12) if subject else "",
    }


def same_refresh_token(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return bool(left.get("refresh_token")) and (
        str(left.get("refresh_token")) == str(right.get("refresh_token"))
        and str(left.get("client_id") or "") == str(right.get("client_id") or "")
    )


def load_token_candidates(config: dict[str, Any]) -> list[dict[str, Any]]:
    token_path = expand_path(config["token_path"])
    candidates: list[dict[str, Any]] = []

    if config.get("use_adc"):
        adc_token = load_adc_credentials(expand_path(config["adc_credentials_path"]))
        if adc_token:
            candidates.append(adc_token)

    if token_path.exists():
        local_token = read_json(token_path)
        if "_credential_source" not in local_token:
            local_token["_credential_source"] = "local_oauth"
        if not any(same_refresh_token(local_token, candidate) for candidate in candidates):
            candidates.append(local_token)

    return candidates


def load_token(config: dict[str, Any]) -> dict[str, Any]:
    candidates = load_token_candidates(config)
    if candidates:
        return candidates[0]

    raise AuthenticationRequired(
        tr(
            "Not signed in to Google yet. Open Local Tasks Bridge and choose \"Sign In with Google\", "
            "or run `ltb auth`.",
            "尚未登录 Google。请打开 Local Tasks Bridge 并选择“使用 Google 登录”，或运行 `ltb auth`。",
        )
    )


def load_fallback_token(config: dict[str, Any], failed_token: dict[str, Any]) -> dict[str, Any] | None:
    for candidate in load_token_candidates(config):
        if same_refresh_token(candidate, failed_token):
            continue
        return candidate
    return None


def google_reauth_message(config: dict[str, Any]) -> str:
    return tr(
        "Google sign-in has expired or was revoked, so sync is paused. Open Local Tasks Bridge from the "
        "menu bar and choose \"Reconnect Google…\", or run `ltb auth`. Sync resumes on the next cycle.",
        "Google 登录已过期或被撤销，同步已暂停。请在菜单栏打开 Local Tasks Bridge 并选择“重新连接 Google…”，"
        "或运行 `ltb auth`。完成后会在下一轮自动恢复同步。",
    )


def refresh_token(config: dict[str, Any], token: dict[str, Any]) -> dict[str, Any]:
    refresh = token.get("refresh_token")
    if not refresh:
        raise SystemExit("Token has no refresh_token. Run auth again with prompt=consent.")

    if token.get("client_id"):
        credentials = {
            "client_id": str(token["client_id"]),
            "client_secret": str(token.get("client_secret") or ""),
        }
    else:
        # Tokens written before the client was recorded in token.json.
        _mode, credentials = resolve_oauth_client(config)

    fields = {
        "client_id": credentials["client_id"],
        "refresh_token": refresh,
        "grant_type": "refresh_token",
    }
    if credentials.get("client_secret"):
        fields["client_secret"] = credentials["client_secret"]

    new_token = post_form(OAUTH_TOKEN_URL, fields)
    merged = dict(token)
    merged.update(new_token)
    merged["refresh_token"] = new_token.get("refresh_token", refresh)
    if credentials.get("client_id"):
        merged["client_id"] = credentials["client_id"]
    if credentials.get("client_secret"):
        merged["client_secret"] = credentials["client_secret"]
    merged["_credential_source"] = str(token.get("_credential_source") or "local_oauth")
    subject = google_account_subject(merged)
    if subject:
        merged["_account_subject"] = subject
    merged["created_at"] = int(time.time())
    merged["expires_at"] = int(time.time()) + int(merged.get("expires_in", 3600)) - 60
    if merged.get("_credential_source") != "gcloud_adc":
        write_json_atomic(expand_path(config["token_path"]), merged)
    return merged


def refresh_token_with_fallback(config: dict[str, Any], token: dict[str, Any]) -> dict[str, Any]:
    require_expected_google_credential_binding(config, token)
    try:
        return refresh_token(config, token)
    except OAuthTokenError as exc:
        if not exc.invalid_grant:
            raise SystemExit(str(exc)) from exc

        fallback = load_fallback_token(config, token)
        if fallback:
            # load_fallback_token only ever returns a candidate whose refresh
            # token differs from the one that just failed, while the binding is
            # derived from that same failed token. A fallback that belongs to a
            # different credential is therefore the normal case, not an
            # emergency: it is unusable, so drop it and ask for reauthorization.
            # Raising here instead left the loop with no way forward, because
            # the actionable AuthenticationRequired below was never reached.
            try:
                require_expected_google_credential_binding(config, fallback)
            except AccountBindingRequired:
                fallback = None

        if fallback:
            try:
                return refresh_token(config, fallback)
            except OAuthTokenError as fallback_exc:
                if not fallback_exc.invalid_grant:
                    raise SystemExit(str(fallback_exc)) from fallback_exc

        raise AuthenticationRequired(google_reauth_message(config)) from exc


class GoogleCalendarClient:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.token = load_token(config)

    def access_token(self) -> str:
        require_expected_google_credential_binding(self.config, self.token)
        if int(self.token.get("expires_at", 0)) <= int(time.time()) + 60:
            self.token = refresh_token_with_fallback(self.config, self.token)
        return str(self.token["access_token"])

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> dict[str, Any]:
        query = f"?{urllib.parse.urlencode(params, doseq=True)}" if params else ""
        url = f"{CALENDAR_API}{path}{query}"
        data = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token()}",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            if exc.code == 401 and retry:
                self.token = refresh_token_with_fallback(self.config, self.token)
                return self.request(method, path, params=params, body=body, retry=False)
            raise GoogleApiError(exc.code, f"{method} {path}: {raw}") from exc

    def list_synced_events(self, calendar_id: str) -> list[dict[str, Any]]:
        encoded_calendar = urllib.parse.quote(calendar_id, safe="")
        params: dict[str, Any] = {
            "privateExtendedProperty": f"{SYNC_MARKER_KEY}={SYNC_MARKER_VALUE}",
            "showDeleted": "false",
            "singleEvents": "true",
            "maxResults": 2500,
        }
        events: list[dict[str, Any]] = []

        while True:
            response = self.request("GET", f"/calendars/{encoded_calendar}/events", params=params)
            events.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
            params["pageToken"] = page_token

        return events

    def insert_event(self, calendar_id: str, body: dict[str, Any]) -> dict[str, Any]:
        encoded_calendar = urllib.parse.quote(calendar_id, safe="")
        return self.request("POST", f"/calendars/{encoded_calendar}/events", body=body)

    def update_event(self, calendar_id: str, event_id: str, body: dict[str, Any]) -> dict[str, Any]:
        encoded_calendar = urllib.parse.quote(calendar_id, safe="")
        encoded_event = urllib.parse.quote(event_id, safe="")
        return self.request("PUT", f"/calendars/{encoded_calendar}/events/{encoded_event}", body=body)

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        encoded_calendar = urllib.parse.quote(calendar_id, safe="")
        encoded_event = urllib.parse.quote(event_id, safe="")
        try:
            self.request("DELETE", f"/calendars/{encoded_calendar}/events/{encoded_event}")
        except GoogleApiError as exc:
            if exc.status not in (404, 410):
                raise


class GoogleTasksClient:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.token = load_token(config)

    def access_token(self) -> str:
        require_expected_google_credential_binding(self.config, self.token)
        if int(self.token.get("expires_at", 0)) <= int(time.time()) + 60:
            self.token = refresh_token_with_fallback(self.config, self.token)
        return str(self.token["access_token"])

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> dict[str, Any]:
        query = f"?{urllib.parse.urlencode(params, doseq=True)}" if params else ""
        url = f"{TASKS_API}{path}{query}"
        data = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token()}",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        # Local proxy connections can occasionally end during TLS setup. Only
        # retry idempotent reads: repeating a POST/PATCH/DELETE after an unknown
        # transport outcome could duplicate or overwrite a user change.
        network_attempts = 3 if method == "GET" else 1
        for attempt in range(1, network_attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                if exc.code == 401 and retry:
                    self.token = refresh_token_with_fallback(self.config, self.token)
                    return self.request(method, path, params=params, body=body, retry=False)
                if exc.code in RETRYABLE_HTTP_STATUSES and attempt < network_attempts:
                    time.sleep(min(2**attempt, 10))
                    continue
                raise GoogleApiError(exc.code, raw) from exc
            except TRANSIENT_NETWORK_ERRORS:
                if attempt >= network_attempts:
                    raise
                time.sleep(min(2**attempt, 10))

        raise AssertionError("unreachable Google Tasks request retry state")

    def list_tasklists(self) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"maxResults": 1000}
        lists: list[dict[str, Any]] = []

        while True:
            response = self.request("GET", "/users/@me/lists", params=params)
            lists.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
            params["pageToken"] = page_token

        return lists

    def insert_tasklist(self, title: str) -> dict[str, Any]:
        return self.request("POST", "/users/@me/lists", body={"title": title})

    def resolve_tasklist_id(self) -> str:
        configured_id = str(self.config.get("tasks_list_id") or "").strip()
        if configured_id:
            return configured_id

        tasklists = self.list_tasklists()
        if not tasklists:
            raise SystemExit("No Google Tasks task lists were found.")

        title = str(self.config.get("tasks_list_title") or "").strip()
        if title:
            for tasklist in tasklists:
                if str(tasklist.get("title") or "") == title:
                    return str(tasklist["id"])
            raise SystemExit(f"Google Tasks list not found by title: {title}")

        return str(tasklists[0]["id"])

    def list_tasks(self, tasklist_id: str, show_deleted: bool = False) -> list[dict[str, Any]]:
        encoded_list = urllib.parse.quote(tasklist_id, safe="")
        params: dict[str, Any] = {
            "showCompleted": "true",
            "showDeleted": "true" if show_deleted else "false",
            "showHidden": "true",
            "maxResults": 100,
        }
        tasks: list[dict[str, Any]] = []

        while True:
            response = self.request("GET", f"/lists/{encoded_list}/tasks", params=params)
            tasks.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
            params["pageToken"] = page_token

        return tasks

    def get_task(self, tasklist_id: str, task_id: str) -> dict[str, Any]:
        encoded_list = urllib.parse.quote(tasklist_id, safe="")
        encoded_task = urllib.parse.quote(task_id, safe="")
        return self.request("GET", f"/lists/{encoded_list}/tasks/{encoded_task}")

    def insert_task(self, tasklist_id: str, body: dict[str, Any]) -> dict[str, Any]:
        encoded_list = urllib.parse.quote(tasklist_id, safe="")
        return self.request("POST", f"/lists/{encoded_list}/tasks", body=body)

    def patch_task(self, tasklist_id: str, task_id: str, body: dict[str, Any]) -> dict[str, Any]:
        encoded_list = urllib.parse.quote(tasklist_id, safe="")
        encoded_task = urllib.parse.quote(task_id, safe="")
        return self.request("PATCH", f"/lists/{encoded_list}/tasks/{encoded_task}", body=body)

    def complete_task(self, tasklist_id: str, task_id: str) -> dict[str, Any]:
        """Complete one task, confirming an unknown PATCH outcome before retrying."""
        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                return self.patch_task(tasklist_id, task_id, {"status": "completed"})
            except TRANSIENT_NETWORK_ERRORS:
                # Completion is idempotent, but the transport may have failed
                # after Google accepted the PATCH. Read the task before another
                # write so an unknown successful outcome is never repeated.
                task = self.get_task(tasklist_id, task_id)
                if str(task.get("status") or "") == "completed":
                    return task
                if attempt >= attempts:
                    raise
                time.sleep(min(2**attempt, 10))

        raise AssertionError("unreachable Google Tasks completion retry state")

    def delete_task(self, tasklist_id: str, task_id: str) -> None:
        encoded_list = urllib.parse.quote(tasklist_id, safe="")
        encoded_task = urllib.parse.quote(task_id, safe="")
        try:
            self.request("DELETE", f"/lists/{encoded_list}/tasks/{encoded_task}")
        except GoogleApiError as exc:
            if exc.status not in (404, 410):
                raise


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "events": {}, "tasks": {}}
    state = read_json(path)
    if not isinstance(state.get("events"), dict):
        state["events"] = {}
    if not isinstance(state.get("tasks"), dict):
        state["tasks"] = {}
    return state


def google_credential_binding(token: dict[str, Any]) -> str:
    refresh = str((token or {}).get("refresh_token") or "")
    if not refresh:
        raise AuthenticationRequired(
            "Google OAuth credential identity is unavailable. Reauthorize Google access before syncing."
        )
    return sha256_text(f"google-oauth-refresh\n{refresh}")


def google_subject_binding(subject: str) -> str:
    return sha256_text(f"google-openid-sub\n{subject}")


def google_account_binding(token: dict[str, Any]) -> tuple[int, str]:
    """The Google half of the sync-state binding.

    Version 2 hashes the Google account ID from the OpenID ID token, so signing
    in again to the same account (which mints a new refresh token) keeps the
    sync map. Tokens without an ID token fall back to version 1, which hashes
    the refresh token itself.
    """

    subject = google_account_subject(token)
    if subject:
        return 2, google_subject_binding(subject)
    return 1, google_credential_binding(token)


def require_expected_google_credential_binding(config: dict[str, Any], token: dict[str, Any]) -> None:
    expected = str(config.get("_expected_google_credential_binding") or "")
    if not expected:
        return
    if int(config.get("_expected_google_binding_version") or 1) >= 2:
        subject = google_account_subject(token)
        actual = google_subject_binding(subject) if subject else ""
    else:
        actual = google_credential_binding(token)
    if actual != expected:
        raise AccountBindingRequired(
            "Google OAuth credentials changed during fallback; refusing to reuse the existing sync state."
        )


def expect_google_binding(config: dict[str, Any], binding: dict[str, Any]) -> None:
    """Pin every later token use in this sync to the account the state belongs to."""

    config["_expected_google_credential_binding"] = str(binding.get("google") or "")
    config["_expected_google_binding_version"] = int(binding.get("version") or 1)


def apple_account_binding(records: list[dict[str, Any]]) -> str:
    account_ids = sorted({
        str(record.get("account_id") or "").strip()
        for record in records
        if isinstance(record, dict) and str(record.get("account_id") or "").strip()
    })
    if not account_ids:
        raise AccountBindingRequired(
            "Apple Reminders account identity is unavailable; refusing to reuse sync state."
        )
    return sha256_text(canonical_json({"apple_account_ids": account_ids}))


def resolve_sync_account_binding(
    config: dict[str, Any],
    reminders: list[dict[str, Any]],
) -> dict[str, Any]:
    # Lists cover empty accounts and lists whose reminders fall outside the
    # current lookahead window. Only opaque hashes are persisted.
    reminder_lists = run_reminders_lists_export(config)
    apple_records = [*reminder_lists, *reminders]
    token = load_token(config)
    version, google = google_account_binding(token)
    binding: dict[str, Any] = {
        "version": version,
        "apple": apple_account_binding(apple_records),
        "google": google,
    }
    if version >= 2:
        # Transient: lets a version-1 state bound to this exact credential be
        # upgraded in place. Never persisted.
        with contextlib.suppress(AuthenticationRequired):
            binding["google_credential"] = google_credential_binding(token)
    return binding


def bind_or_validate_sync_state_accounts(
    state: dict[str, Any],
    binding: dict[str, Any],
) -> None:
    normalized = {
        "version": max(1, int(binding.get("version") or 1)),
        "apple": str(binding.get("apple") or ""),
        "google": str(binding.get("google") or ""),
    }
    if not normalized["apple"] or not normalized["google"]:
        raise AccountBindingRequired("Sync account binding is incomplete; refusing to continue.")

    existing = state.get("account_binding")
    has_legacy_records = bool(state.get("events") or state.get("tasks"))
    if existing is None:
        if has_legacy_records:
            raise AccountBindingRequired(
                "Existing sync state has no account binding; back it up and explicitly rebuild state before syncing."
            )
        state["account_binding"] = normalized
        return
    if not isinstance(existing, dict):
        raise AccountBindingRequired("Stored sync account binding is invalid; refusing to continue.")
    current = {
        "version": int(existing.get("version") or 0),
        "apple": str(existing.get("apple") or ""),
        "google": str(existing.get("google") or ""),
    }
    if current == normalized:
        return
    credential = str(binding.get("google_credential") or "")
    if (
        current["version"] == 1
        and normalized["version"] >= 2
        and current["apple"] == normalized["apple"]
        and current["google"]
        and credential
        and secrets.compare_digest(current["google"], credential)
    ):
        # The state is bound to this exact refresh token, so it belongs to the
        # same Google account; record the account identity instead.
        state["account_binding"] = normalized
        return
    raise AccountBindingRequired(
        "Apple Reminders or Google OAuth account binding changed; refusing to reuse the existing sync state."
    )


def run_reminders_export(config: dict[str, Any], completed_only: bool = False) -> list[dict[str, Any]]:
    source = str(config.get("reminders_source") or "auto")
    if source == "sqlite":
        return run_reminders_sqlite_export(config, completed_only=completed_only)
    if source not in ("auto", "eventkit"):
        raise SystemExit(f"Unknown reminders_source: {source}")

    try:
        return run_reminders_eventkit_export(config, completed_only=completed_only)
    except SystemExit as exc:
        if source == "eventkit":
            raise
        eprint(f"EventKit Reminders export failed; falling back to SQLite export. {exc}")
        return run_reminders_sqlite_export(config, completed_only=completed_only)


REMINDERS_HELPER_NAMES = {
    "export": ("ltb-reminders-export", "RemindersExport.swift", "reminders_exporter_path", "LTB_REMINDERS_EXPORTER"),
    "apply": ("ltb-reminders-apply", "RemindersApply.swift", "reminders_apply_path", "LTB_REMINDERS_APPLY"),
}


def reminders_helper_candidates(kind: str) -> list[Path]:
    binary, script, _key, _env = REMINDERS_HELPER_NAMES[kind]
    return [
        # Inside the app bundle: Contents/Resources/engine -> Contents/MacOS.
        ENGINE_DIR.parent.parent / "MacOS" / binary,
        # A source checkout after `make helpers`.
        ENGINE_DIR.parent / "build" / "helpers" / binary,
        # A source checkout without a build: interpret the Swift source.
        ENGINE_DIR.parent / "macos" / "Helpers" / script,
    ]


def resolve_reminders_helper(config: dict[str, Any], kind: str) -> Path:
    """Locate the EventKit helper: config, environment, then the shipped copy."""

    _binary, _script, key, env_name = REMINDERS_HELPER_NAMES[kind]
    configured = str(config.get(key) or "").strip() or str(os.environ.get(env_name) or "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.exists():
            raise RemindersUnavailable(f"Reminders helper not found: {path}")
        return path
    for candidate in reminders_helper_candidates(kind):
        if candidate.is_file():
            return candidate
    raise RemindersUnavailable(
        tr(
            "The Reminders helper programs are missing. Reinstall Local Tasks Bridge, "
            "or run `make helpers` in a source checkout.",
            "缺少提醒事项辅助程序。请重新安装 Local Tasks Bridge，或在源码目录中运行 `make helpers`。",
        )
    )


def reminders_helper_command(config: dict[str, Any], kind: str) -> list[str]:
    path = resolve_reminders_helper(config, kind)
    if path.suffix == ".swift":
        if not shutil.which("swift"):
            raise RemindersUnavailable(
                tr(
                    "Swift is not installed. Install the Xcode Command Line Tools (xcode-select --install) "
                    "or use the app build, which ships compiled helpers.",
                    "未安装 Swift。请安装 Xcode 命令行工具（xcode-select --install），或使用自带已编译辅助程序的 App 版本。",
                )
            )
        return ["swift", str(path)]
    if not os.access(path, os.X_OK):
        raise RemindersUnavailable(f"Reminders helper is not executable: {path}")
    return [str(path)]


def reminders_access_hint() -> str:
    return tr(
        "Allow Reminders access for Local Tasks Bridge in System Settings > Privacy & Security > Reminders. "
        "When running from Terminal, allow Terminal instead.",
        "请在“系统设置 > 隐私与安全性 > 提醒事项”中允许 Local Tasks Bridge 访问。"
        "如果是在“终端”中运行，请允许“终端”。",
    )


def run_reminders_helper(
    config: dict[str, Any],
    kind: str,
    arguments: list[str],
    *,
    stdin_text: str | None = None,
    failure: str,
) -> list[dict[str, Any]]:
    command = [*reminders_helper_command(config, kind), *arguments]
    process = subprocess.run(command, input=stdin_text, capture_output=True, text=True, check=False)
    if process.returncode != 0:
        detail = process.stderr.strip()
        raise RemindersUnavailable(f"{failure}\n{detail}\n{reminders_access_hint()}".rstrip())
    try:
        payload = json.loads(process.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RemindersUnavailable(f"Reminders helper returned invalid JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise RemindersUnavailable("Reminders helper did not return a JSON array.")
    return payload


TASKS_LOOKAHEAD_DAYS = 36500


def export_lookahead_days(config: dict[str, Any]) -> int:
    """Calendar mode mirrors a window of dated reminders; Google Tasks has no
    window, and a reminder moved far ahead must not look deleted."""

    if str(config.get("target_service") or "tasks") == "tasks":
        return max(int(config["lookahead_days"]), TASKS_LOOKAHEAD_DAYS)
    return int(config["lookahead_days"])


def run_reminders_eventkit_export(config: dict[str, Any], completed_only: bool = False) -> list[dict[str, Any]]:
    arguments = ["--lookahead-days", str(export_lookahead_days(config))]
    if reminders_export_needs_undated(config):
        arguments.append("--include-undated")
    if completed_only:
        arguments.append("--completed-only")
    for list_name in config["include_lists"]:
        arguments.extend(["--list", list_name])
    return run_reminders_helper(config, "export", arguments, failure="Failed to read Apple Reminders.")


def run_reminders_lists_export(config: dict[str, Any]) -> list[dict[str, Any]]:
    source = str(config.get("reminders_source") or "auto")
    if source == "sqlite":
        return run_reminders_sqlite_lists_export(config)
    if source not in ("auto", "eventkit"):
        raise SystemExit(f"Unknown reminders_source: {source}")

    try:
        return run_reminders_eventkit_lists_export(config)
    except SystemExit as exc:
        if source == "eventkit":
            raise
        eprint(f"EventKit Reminders lists export failed; falling back to SQLite. {exc}")
        return run_reminders_sqlite_lists_export(config)


def run_reminders_eventkit_lists_export(
    config: dict[str, Any],
    *,
    all_lists: bool = False,
) -> list[dict[str, Any]]:
    arguments = ["--lists-only"]
    if not all_lists:
        for list_name in config["include_lists"]:
            arguments.extend(["--list", list_name])
    return run_reminders_helper(config, "export", arguments, failure="Failed to read Apple Reminders lists.")


def apple_timestamp_to_datetime(value: Any) -> dt.datetime | None:
    if value is None:
        return None
    try:
        seconds = float(value) + APPLE_EPOCH_OFFSET_SECONDS
    except (TypeError, ValueError):
        return None
    return dt.datetime.fromtimestamp(seconds, tz=dt.timezone.utc)


def apple_timestamp_to_iso(value: Any) -> str | None:
    date = apple_timestamp_to_datetime(value)
    return format_rfc3339(date) if date else None


def apple_timestamp_to_local_date(value: Any) -> str | None:
    date = apple_timestamp_to_datetime(value)
    if not date:
        return None
    return date.astimezone().date().isoformat()


def blob_to_hex(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def list_reminders_sqlite_paths(config: dict[str, Any]) -> list[Path]:
    stores_dir = expand_path(config["reminders_sqlite_dir"])
    if not stores_dir.exists():
        raise SystemExit(f"Reminders SQLite store directory not found: {stores_dir}")
    return sorted(
        path
        for path in stores_dir.glob("Data-*.sqlite")
        if path.name != "Data-local.sqlite" and not path.name.endswith(("-wal", "-shm"))
    )


def run_reminders_sqlite_export(config: dict[str, Any], completed_only: bool = False) -> list[dict[str, Any]]:
    latest_date = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=export_lookahead_days(config))
    list_filter = set(config["include_lists"])
    include_undated = reminders_export_needs_undated(config)
    reminders: dict[str, dict[str, Any]] = {}
    paths = list_reminders_sqlite_paths(config)

    query = """
        SELECT
            r.Z_PK AS pk,
            r.ZTITLE AS title,
            r.ZNOTES AS notes,
            r.ZCOMPLETED AS completed,
            r.ZMARKEDFORDELETION AS marked_for_deletion,
            r.ZPRIORITY AS priority,
            r.ZALLDAY AS all_day,
            r.ZDISPLAYDATEISALLDAY AS display_date_is_all_day,
            r.ZCREATIONDATE AS creation_date,
            r.ZLASTMODIFIEDDATE AS modified_date,
            r.ZCOMPLETIONDATE AS completion_date,
            r.ZDISPLAYDATEDATE AS display_date,
            r.ZDUEDATE AS due_date,
            r.ZSTARTDATE AS start_date,
            r.ZTIMEZONE AS timezone,
            r.ZDISPLAYDATETIMEZONE AS display_timezone,
            r.ZEXTERNALIDENTIFIER AS external_id,
            r.ZIDENTIFIER AS identifier,
            r.ZLIST AS list_pk,
            l.ZNAME AS list_title,
            l.ZEXTERNALIDENTIFIER AS list_external_id,
            l.ZIDENTIFIER AS list_identifier
        FROM ZREMCDREMINDER r
        LEFT JOIN ZREMCDBASELIST l ON l.Z_PK = r.ZLIST
        WHERE COALESCE(r.ZMARKEDFORDELETION, 0) = 0
    """
    if completed_only:
        query += """
          AND COALESCE(r.ZCOMPLETED, 0) != 0
        """
    else:
        query += """
          AND COALESCE(r.ZCOMPLETED, 0) = 0
        """
    if not completed_only and not include_undated:
        query += """
          AND (r.ZDUEDATE IS NOT NULL OR r.ZDISPLAYDATEDATE IS NOT NULL OR r.ZSTARTDATE IS NOT NULL)
        """

    for path in paths:
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            eprint(f"Skipping unreadable Reminders store {path}: {exc}")
            continue

        with connection:
            try:
                rows = connection.execute(query).fetchall()
            except sqlite3.Error as exc:
                eprint(f"Skipping incompatible Reminders store {path}: {exc}")
                continue

        account_id = path.stem.replace("Data-", "")
        account_title = account_id
        for row in rows:
            list_title = str(row["list_title"] or "")
            if list_filter and list_title not in list_filter:
                continue

            raw_date = row["due_date"] if row["due_date"] is not None else row["display_date"]
            if raw_date is None:
                raw_date = row["start_date"]
            chosen_date = apple_timestamp_to_datetime(raw_date)
            if not completed_only and not chosen_date and not include_undated:
                continue
            if not completed_only and chosen_date and chosen_date > latest_date:
                continue

            all_day = bool(row["all_day"] or row["display_date_is_all_day"])
            external_id = str(row["external_id"] or "")
            identifier = blob_to_hex(row["identifier"])
            stable_id = external_id or identifier or f"{account_id}:{row['pk']}"
            list_id = str(row["list_external_id"] or blob_to_hex(row["list_identifier"]) or row["list_pk"] or "")
            uid_seed = f"{account_id}:{stable_id}"

            item = {
                "id": f"{account_id}:{row['pk']}",
                "external_id": external_id,
                "stable_id": stable_id,
                "title": row["title"] or "",
                "notes": row["notes"] or "",
                "list_title": list_title,
                "list_id": list_id,
                "account_title": account_title,
                "account_id": account_id,
                "priority": row["priority"] or 0,
                "is_completed": bool(row["completed"]),
                "is_recurring": False,
                "recurrence_count": 0,
                "created_at": apple_timestamp_to_iso(row["creation_date"]),
                "modified_at": apple_timestamp_to_iso(row["modified_date"]),
                "completed_at": apple_timestamp_to_iso(row["completion_date"]),
                "due_at": apple_timestamp_to_iso(raw_date),
                "due_date": apple_timestamp_to_local_date(raw_date) if raw_date is not None and all_day else None,
                "all_day": all_day if raw_date is not None else False,
                "date_source": "sqlite" if raw_date is not None else "none",
            }
            reminders[uid_seed] = item

    return list(reminders.values())


def run_reminders_sqlite_lists_export(config: dict[str, Any]) -> list[dict[str, Any]]:
    list_filter = set(config["include_lists"])
    lists_by_key: dict[str, dict[str, Any]] = {}

    query = """
        SELECT
            l.Z_PK AS pk,
            l.ZNAME AS title,
            l.ZEXTERNALIDENTIFIER AS external_id,
            l.ZIDENTIFIER AS identifier
        FROM ZREMCDBASELIST l
        WHERE COALESCE(l.ZMARKEDFORDELETION, 0) = 0
          AND l.ZNAME IS NOT NULL
    """

    for path in list_reminders_sqlite_paths(config):
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            eprint(f"Skipping unreadable Reminders store {path}: {exc}")
            continue

        with connection:
            try:
                rows = connection.execute(query).fetchall()
            except sqlite3.Error as exc:
                eprint(f"Skipping incompatible Reminders store {path}: {exc}")
                continue

        account_id = path.stem.replace("Data-", "")
        for row in rows:
            title = str(row["title"] or "")
            if not title or (list_filter and title not in list_filter):
                continue
            list_id = str(row["external_id"] or blob_to_hex(row["identifier"]) or row["pk"])
            key = f"{account_id}:{list_id}:{title}"
            lists_by_key[key] = {
                "id": list_id,
                "title": title,
                "account_title": account_id,
                "account_id": account_id,
            }

    return sorted(lists_by_key.values(), key=lambda item: str(item.get("title") or ""))


def parse_rfc3339(value: str) -> dt.datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def format_rfc3339(value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def reminder_uid(reminder: dict[str, Any]) -> str:
    raw_id = reminder.get("stable_id") or reminder.get("external_id") or reminder.get("id")
    if not raw_id:
        raw_id = canonical_json(
            {
                "title": reminder.get("title", ""),
                "list_id": reminder.get("list_id", ""),
                "due_at": reminder.get("due_at", ""),
            }
        )
    raw = "|".join(
        [
            str(reminder.get("account_id") or ""),
            str(reminder.get("list_id") or ""),
            str(raw_id),
        ]
    )
    return sha256_text(raw, 40)


def reminder_description(reminder: dict[str, Any], uid: str) -> str:
    parts: list[str] = []
    notes = str(reminder.get("notes") or "").strip()
    if notes:
        parts.append(notes)

    metadata = [
        "Synced from Apple Reminders.",
        f"List: {reminder.get('list_title') or '(unknown)'}",
        f"Source UID: {uid}",
    ]
    if parts:
        parts.append("")
    parts.extend(metadata)
    return "\n".join(parts)


def strip_tasks_sync_metadata(notes: str) -> str:
    lines = notes.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "Synced from Apple Reminders.":
            return "\n".join(lines[:index]).rstrip()
    return notes.rstrip()


def parse_tasks_sync_metadata(notes: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    lines = notes.splitlines()
    in_metadata = False

    for line in lines:
        stripped = line.strip()
        if stripped == "Synced from Apple Reminders.":
            in_metadata = True
            metadata[SYNC_MARKER_KEY] = SYNC_MARKER_VALUE
            continue
        if not in_metadata or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        metadata[key.strip().lower()] = value.strip()

    return metadata


def task_due_date(reminder: dict[str, Any]) -> str | None:
    if reminder.get("due_date"):
        try:
            return dt.date.fromisoformat(str(reminder["due_date"])[:10]).isoformat()
        except ValueError:
            return None
    due_at = reminder.get("due_at")
    if not due_at:
        return None
    try:
        return parse_rfc3339(str(due_at)).astimezone().date().isoformat()
    except ValueError:
        return None


def task_due_rfc3339(date_text: str | None) -> str | None:
    if not date_text:
        return None
    try:
        due_date = dt.date.fromisoformat(str(date_text)[:10]).isoformat()
    except ValueError:
        return None
    return f"{due_date}T00:00:00.000Z"


def task_body_for_patch(body: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    patch_body = dict(body)
    if "due" not in patch_body and existing and existing.get("due"):
        patch_body["due"] = None
    return patch_body


def task_has_current_source_digest(task: dict[str, Any], digest: str) -> bool:
    metadata = parse_tasks_sync_metadata(str(task.get("notes") or ""))
    return metadata.get("source digest") == digest


def task_material_without_due(material: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": material.get("title"),
        "notes": material.get("notes"),
        "status": material.get("status"),
    }


def task_only_due_differs(
    current_task: dict[str, Any],
    desired_body: dict[str, Any],
    reminder: dict[str, Any],
    config: dict[str, Any],
) -> bool:
    current = task_change_material(current_task, reminder, config)
    desired = task_change_material(desired_body, reminder, config)
    return task_material_without_due(current) == task_material_without_due(desired) and current != desired


def task_matches_desired(
    current_task: dict[str, Any],
    desired_body: dict[str, Any],
    reminder: dict[str, Any],
    config: dict[str, Any],
) -> bool:
    return task_change_digest(current_task, reminder, config) == task_change_digest(desired_body, reminder, config)


def reminder_tasks_notes(reminder: dict[str, Any], uid: str, digest: str) -> str:
    parts: list[str] = []
    notes = str(reminder.get("notes") or "").strip()
    if notes:
        parts.append(notes)

    metadata = [
        "Synced from Apple Reminders.",
        f"List: {reminder.get('list_title') or '(unknown)'}",
        f"Source UID: {uid}",
        f"Source Digest: {digest}",
    ]
    if parts:
        parts.append("")
    parts.extend(metadata)
    return "\n".join(parts)


def build_task(reminder: dict[str, Any], config: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    uid = reminder_uid(reminder)
    title = str(reminder.get("title") or "").strip() or "(Untitled reminder)"
    due_date = task_due_date(reminder)
    status = "completed" if reminder.get("is_completed") else "needsAction"
    body: dict[str, Any] = {
        "title": title,
        "status": status,
    }
    due = task_due_rfc3339(due_date)
    if due:
        body["due"] = due

    digest_material = {
        "task": {
            "title": title,
            "notes": str(reminder.get("notes") or "").strip(),
            "due_date": due_date,
            "status": status,
        },
        "source_modified_at": reminder.get("modified_at"),
        "source_completed_at": reminder.get("completed_at"),
    }
    digest = sha256_text(canonical_json(digest_material))
    body["notes"] = reminder_tasks_notes(reminder, uid, digest)
    return uid, body, digest


def build_desired_tasks(
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, tuple[dict[str, Any], str, dict[str, Any]]]], int]:
    exported_reminders = run_reminders_export(config)
    reminders = [
        reminder
        for reminder in exported_reminders
        if not reminder_is_undated(reminder)
        or list_sync_policy(config, str(reminder.get("list_title") or "Apple Reminders"))["sync_undated"]
    ]
    desired: dict[str, dict[str, tuple[dict[str, Any], str, dict[str, Any]]]] = {}
    skipped_invalid = 0

    if config.get("tasks_mirror_lists") and config.get("tasks_mirror_empty_lists"):
        for reminder_list in run_reminders_lists_export(config):
            title = str(reminder_list.get("title") or "").strip()
            if title:
                desired.setdefault(title, {})

    for reminder in reminders:
        try:
            uid, body, digest = build_task(reminder, config)
            list_title = str(reminder.get("list_title") or "Apple Reminders")
            desired.setdefault(list_title, {})[uid] = (body, digest, reminder)
        except (ValueError, KeyError) as exc:
            skipped_invalid += 1
            eprint(f"Skipping reminder: {exc}")

    return reminders, desired, skipped_invalid


def build_completed_tasks(
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, tuple[dict[str, Any], str, dict[str, Any]]]], int]:
    reminders = run_reminders_export(config, completed_only=True)
    completed: dict[str, dict[str, tuple[dict[str, Any], str, dict[str, Any]]]] = {}
    skipped_invalid = 0

    for reminder in reminders:
        try:
            uid, body, digest = build_task(reminder, config)
            list_title = str(reminder.get("list_title") or "Apple Reminders")
            completed.setdefault(list_title, {})[uid] = (body, digest, reminder)
        except (ValueError, KeyError) as exc:
            skipped_invalid += 1
            eprint(f"Skipping completed reminder: {exc}")

    return reminders, completed, skipped_invalid


def build_event(reminder: dict[str, Any], config: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    uid = reminder_uid(reminder)
    title = str(reminder.get("title") or "").strip() or "(Untitled reminder)"
    if config["prefix_list"] and reminder.get("list_title"):
        title = f"[{reminder['list_title']}] {title}"

    body: dict[str, Any] = {
        "summary": title,
        "description": reminder_description(reminder, uid),
        "transparency": config["transparency"],
        "extendedProperties": {
            "private": {
                SYNC_MARKER_KEY: SYNC_MARKER_VALUE,
                UID_KEY: uid,
            }
        },
    }

    if reminder.get("all_day"):
        due_date = reminder.get("due_date")
        if not due_date:
            raise ValueError(f"All-day reminder is missing due_date: {title}")
        start_date = dt.date.fromisoformat(str(due_date))
        end_date = start_date + dt.timedelta(days=1)
        body["start"] = {"date": start_date.isoformat()}
        body["end"] = {"date": end_date.isoformat()}
    else:
        due_at = reminder.get("due_at")
        if not due_at:
            raise ValueError(f"Timed reminder is missing due_at: {title}")
        start = parse_rfc3339(str(due_at))
        end = start + dt.timedelta(minutes=int(config["default_duration_minutes"]))
        body["start"] = {"dateTime": format_rfc3339(start)}
        body["end"] = {"dateTime": format_rfc3339(end)}

    popup_minutes = config.get("google_popup_minutes") or []
    if popup_minutes:
        body["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": int(minutes)} for minutes in popup_minutes],
        }
    else:
        body["reminders"] = {"useDefault": False}

    digest_material = {
        "event": body,
        "source_modified_at": reminder.get("modified_at"),
        "source_completed_at": reminder.get("completed_at"),
    }
    digest = sha256_text(canonical_json(digest_material))
    body["extendedProperties"]["private"][DIGEST_KEY] = digest
    return uid, body, digest


def build_desired_events(
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, tuple[dict[str, Any], str, dict[str, Any]]], int]:
    reminders = run_reminders_export(config)
    desired: dict[str, tuple[dict[str, Any], str, dict[str, Any]]] = {}
    skipped_invalid = 0

    for reminder in reminders:
        try:
            uid, body, digest = build_event(reminder, config)
            desired[uid] = (body, digest, reminder)
        except (ValueError, KeyError) as exc:
            skipped_invalid += 1
            eprint(f"Skipping reminder: {exc}")

    return reminders, desired, skipped_invalid


def private_props(event: dict[str, Any]) -> dict[str, str]:
    return event.get("extendedProperties", {}).get("private", {}) or {}


def index_existing_events(events: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    by_uid: dict[str, dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []

    for event in events:
        uid = private_props(event).get(UID_KEY)
        if not uid:
            continue
        if uid in by_uid:
            duplicates.append(event)
        else:
            by_uid[uid] = event
    return by_uid, duplicates


def index_existing_tasks(tasks: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    by_uid: dict[str, dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []

    for task in tasks:
        metadata = parse_tasks_sync_metadata(str(task.get("notes") or ""))
        if metadata.get(SYNC_MARKER_KEY) != SYNC_MARKER_VALUE:
            continue
        uid = metadata.get("source uid")
        if not uid:
            continue
        if uid in by_uid:
            duplicates.append(task)
        else:
            by_uid[uid] = task

    return by_uid, duplicates


def task_fingerprint(task_or_body: dict[str, Any]) -> str:
    due = str(task_or_body.get("due") or "")
    return canonical_json(
        {
            "title": str(task_or_body.get("title") or "").strip(),
            "due_date": due[:10] if len(due) >= 10 else "",
        }
    )


def task_title_due_material(task_or_body: dict[str, Any]) -> dict[str, Any]:
    due = str(task_or_body.get("due") or "")
    due_date = due[:10] if len(due) >= 10 else None
    return {
        "title": str(task_or_body.get("title") or "").strip() or "(Untitled reminder)",
        "due_date": due_date,
    }


def parse_optional_rfc3339(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        return parse_rfc3339(str(value)).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def google_task_is_newer_than_reminder(task: dict[str, Any], reminder: dict[str, Any]) -> bool:
    google_updated = parse_optional_rfc3339(task.get("updated"))
    apple_modified = parse_optional_rfc3339(reminder.get("modified_at") or reminder.get("created_at"))
    if google_updated and apple_modified:
        return google_updated > apple_modified
    return bool(google_updated and not apple_modified)


def index_synced_tasks_by_fingerprint(tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_fingerprint: dict[str, dict[str, Any]] = {}
    duplicate_fingerprints: set[str] = set()

    for task in tasks:
        metadata = parse_tasks_sync_metadata(str(task.get("notes") or ""))
        if metadata.get(SYNC_MARKER_KEY) != SYNC_MARKER_VALUE:
            continue
        fingerprint = task_fingerprint(task)
        if fingerprint in by_fingerprint:
            duplicate_fingerprints.add(fingerprint)
        else:
            by_fingerprint[fingerprint] = task

    for fingerprint in duplicate_fingerprints:
        by_fingerprint.pop(fingerprint, None)
    return by_fingerprint


def task_title_fingerprint(task_or_body: dict[str, Any]) -> str:
    return str(task_or_body.get("title") or "").strip()


def index_synced_tasks_by_title(tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_title: dict[str, dict[str, Any]] = {}
    duplicate_titles: set[str] = set()

    for task in tasks:
        metadata = parse_tasks_sync_metadata(str(task.get("notes") or ""))
        if metadata.get(SYNC_MARKER_KEY) != SYNC_MARKER_VALUE:
            continue
        title = task_title_fingerprint(task)
        if title in by_title:
            duplicate_titles.add(title)
        else:
            by_title[title] = task

    for title in duplicate_titles:
        by_title.pop(title, None)
    return by_title


def task_source_uid(task: dict[str, Any]) -> str:
    metadata = parse_tasks_sync_metadata(str(task.get("notes") or ""))
    return str(metadata.get("source uid") or "")


def can_reuse_task_fallback(
    task: dict[str, Any],
    uid: str,
    desired: dict[str, tuple[dict[str, Any], str, dict[str, Any]]],
    tasklist_id: str,
    claimed_task_ids: set[tuple[str, str]],
) -> bool:
    task_id = str(task.get("id") or "")
    if task_id and (tasklist_id, task_id) in claimed_task_ids:
        return False
    source_uid = task_source_uid(task)
    return not source_uid or source_uid == uid or source_uid not in desired


def can_use_task_state_record(
    record: dict[str, Any],
    uid: str,
    desired: dict[str, tuple[dict[str, Any], str, dict[str, Any]]],
    tasklist_id: str,
    existing_by_id: dict[str, dict[str, Any]],
    claimed_task_ids: set[tuple[str, str]],
) -> bool:
    task_id = str(record.get("task_id") or "")
    if not task_id:
        return False
    if (tasklist_id, task_id) in claimed_task_ids:
        return False
    existing = existing_by_id.get(task_id)
    return not existing or can_reuse_task_fallback(existing, uid, desired, tasklist_id, claimed_task_ids)


def strip_sync_metadata(description: str) -> str:
    lines = description.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "Synced from Apple Reminders.":
            return "\n".join(lines[:index]).rstrip()
    return description.rstrip()


def event_summary_to_reminder_title(
    event_or_body: dict[str, Any],
    reminder: dict[str, Any],
    config: dict[str, Any],
) -> str:
    summary = str(event_or_body.get("summary") or "").strip()
    if config.get("prefix_list") and reminder.get("list_title"):
        prefix = f"[{reminder['list_title']}] "
        if summary.startswith(prefix):
            return summary[len(prefix):].strip()
    return summary or "(Untitled reminder)"


def event_time_fields(event_or_body: dict[str, Any]) -> dict[str, Any]:
    start = event_or_body.get("start") or {}
    if "date" in start:
        return {
            "all_day": True,
            "due_date": str(start.get("date") or ""),
            "due_at": None,
        }

    due_at = str(start.get("dateTime") or "")
    if due_at:
        try:
            due_at = format_rfc3339(parse_rfc3339(due_at))
        except ValueError:
            pass

    return {
        "all_day": False,
        "due_date": None,
        "due_at": due_at,
    }


def google_change_material(
    event_or_body: dict[str, Any],
    reminder: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    material = {
        "title": event_summary_to_reminder_title(event_or_body, reminder, config),
        "notes": strip_sync_metadata(str(event_or_body.get("description") or "")),
    }
    material.update(event_time_fields(event_or_body))
    return material


def google_change_digest(
    event_or_body: dict[str, Any],
    reminder: dict[str, Any],
    config: dict[str, Any],
) -> str:
    return sha256_text(canonical_json(google_change_material(event_or_body, reminder, config)))


def google_event_to_reminder_operation(
    event: dict[str, Any],
    reminder: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    material = google_change_material(event, reminder, config)
    operation = {
        "stable_id": reminder.get("stable_id") or reminder.get("external_id") or reminder.get("id"),
        "id": reminder.get("id"),
        "title": material["title"],
        "notes": material["notes"],
        "all_day": bool(material["all_day"]),
    }
    if material["all_day"]:
        operation["due_date"] = material["due_date"]
    else:
        operation["due_at"] = material["due_at"]
    return operation


def task_change_material(
    task_or_body: dict[str, Any],
    reminder: dict[str, Any],
    _config: dict[str, Any],
) -> dict[str, Any]:
    due = str(task_or_body.get("due") or "")
    due_date = due[:10] if len(due) >= 10 else None
    return {
        "title": str(task_or_body.get("title") or "").strip() or "(Untitled reminder)",
        "notes": strip_tasks_sync_metadata(str(task_or_body.get("notes") or "")),
        "status": str(task_or_body.get("status") or "needsAction"),
        "all_day": bool(due_date),
        "due_date": due_date,
    }


def task_change_digest(
    task_or_body: dict[str, Any],
    reminder: dict[str, Any],
    config: dict[str, Any],
) -> str:
    return sha256_text(canonical_json(task_change_material(task_or_body, reminder, config)))


def google_updated_since_sync(task: dict[str, Any], record: dict[str, Any] | None) -> bool:
    """True when Google recorded a modification after the bridge last saw this task."""

    seen = parse_optional_rfc3339((record or {}).get("google_updated"))
    current = parse_optional_rfc3339(task.get("updated"))
    return bool(seen and current and current > seen)


def reminder_timed_due(reminder: dict[str, Any]) -> dt.datetime | None:
    """The reminder's due time in local time, or None for all-day/undated reminders."""

    if reminder.get("all_day") or reminder.get("due_date") or not reminder.get("due_at"):
        return None
    try:
        return parse_rfc3339(str(reminder["due_at"])).astimezone()
    except ValueError:
        return None


def google_task_to_reminder_operation(
    task: dict[str, Any],
    reminder: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    material = task_change_material(task, reminder, config)
    operation = {
        "stable_id": reminder.get("stable_id") or reminder.get("external_id") or reminder.get("id"),
        "id": reminder.get("id"),
        "title": material["title"],
        "notes": material["notes"],
    }
    timed_due = reminder_timed_due(reminder)
    if material["due_date"] and timed_due is not None:
        # Google Tasks stores dates only. Keep the reminder's time of day:
        # leave it alone when the date is unchanged, move it when it changed.
        if timed_due.date().isoformat() != material["due_date"]:
            moved = dt.datetime.combine(dt.date.fromisoformat(material["due_date"]), timed_due.time()).astimezone()
            operation["all_day"] = False
            operation["due_at"] = format_rfc3339(moved)
    elif material["due_date"]:
        operation["all_day"] = True
        operation["due_date"] = material["due_date"]
    else:
        operation["clear_due"] = True
    if task.get("status") == "completed":
        operation["complete"] = True
    return operation


def google_task_to_new_reminder_operation(
    task: dict[str, Any],
    list_title: str,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    material = task_change_material(task, {}, config)
    due_date = material.get("due_date")
    if not due_date and not list_sync_policy(config, list_title)["sync_undated"]:
        return None

    operation: dict[str, Any] = {
        "create": True,
        "list_title": list_title,
        "title": material["title"],
        "notes": material["notes"],
    }
    if due_date:
        operation["all_day"] = True
        operation["due_date"] = due_date
    return operation


def reminder_from_created_task_result(
    result: dict[str, Any],
    task: dict[str, Any],
    list_title: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    material = task_change_material(task, {}, config)
    return {
        "id": result.get("id") or result.get("stable_id") or "",
        "external_id": result.get("external_id") or "",
        "stable_id": result.get("stable_id") or result.get("external_id") or result.get("id") or "",
        "title": material["title"],
        "notes": material["notes"],
        "list_title": result.get("list_title") or list_title,
        "list_id": result.get("list_id") or "",
        "account_title": result.get("account_title") or "",
        "account_id": result.get("account_id") or "",
        "priority": 0,
        "is_completed": False,
        "created_at": result.get("created_at"),
        "modified_at": result.get("modified_at"),
        "completed_at": None,
        "due_at": None,
        "due_date": material["due_date"],
        "all_day": bool(material["due_date"]),
        "date_source": "due" if material["due_date"] else "none",
    }


def unique_desired_by_task_fingerprint(
    desired: dict[str, tuple[dict[str, Any], str, dict[str, Any]]],
) -> dict[str, tuple[str, dict[str, Any], str, dict[str, Any]]]:
    by_fingerprint: dict[str, tuple[str, dict[str, Any], str, dict[str, Any]]] = {}
    duplicate_fingerprints: set[str] = set()

    for uid, (body, digest, reminder) in desired.items():
        fingerprint = task_fingerprint(body)
        if fingerprint in by_fingerprint:
            duplicate_fingerprints.add(fingerprint)
        else:
            by_fingerprint[fingerprint] = (uid, body, digest, reminder)

    for fingerprint in duplicate_fingerprints:
        by_fingerprint.pop(fingerprint, None)
    return by_fingerprint


def run_reminders_apply(config: dict[str, Any], operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    arguments: list[str] = []
    for list_name in config.get("include_lists", []):
        arguments.extend(["--list", list_name])
    return run_reminders_helper(
        config,
        "apply",
        arguments,
        stdin_text=json.dumps(operations, ensure_ascii=False),
        failure="Failed to update Apple Reminders from Google.",
    )


def plan_google_changes_to_reminders(
    config: dict[str, Any],
    calendar_id: str,
    desired: dict[str, tuple[dict[str, Any], str, dict[str, Any]]],
    existing_by_uid: dict[str, dict[str, Any]],
    state: dict[str, Any],
) -> dict[str, Any]:
    if not config["bidirectional"]:
        return {
            "operations": [],
            "initialized": 0,
            "conflicts": [],
            "blocked_uids": set(),
            "source_controlled": set(),
            "actions": [],
        }

    operations: list[dict[str, Any]] = []
    initialized = 0
    conflicts: list[str] = []
    blocked_uids: set[str] = set()
    source_controlled: set[str] = set()
    actions: list[dict[str, Any]] = []

    for uid, (body, digest, reminder) in desired.items():
        existing = existing_by_uid.get(uid)
        if not existing:
            continue

        record = state_record(state, calendar_id, uid)
        current_google_digest = google_change_digest(existing, reminder, config)
        expected_google_digest = google_change_digest(body, reminder, config)
        stored_google_digest = record.get("google_digest") if record else None

        if stored_google_digest:
            google_changed = current_google_digest != stored_google_digest
        else:
            google_changed = current_google_digest != expected_google_digest
            if not google_changed:
                initialized += 1

        if not google_changed:
            continue

        apple_changed = bool(record and record.get("digest") and record.get("digest") != digest)
        title = str(existing.get("summary") or body.get("summary") or uid)
        if apple_changed:
            if current_google_digest == expected_google_digest:
                initialized += 1
                continue
            conflicts.append(title)
            blocked_uids.add(uid)
            continue

        operations.append(google_event_to_reminder_operation(existing, reminder, config))
        source_controlled.add(uid)
        actions.append(planned_mutation("apple_reminders", "update", [calendar_id, uid]))

    return {
        "operations": operations,
        "initialized": initialized,
        "conflicts": conflicts,
        "blocked_uids": blocked_uids,
        "source_controlled": source_controlled,
        "actions": actions,
    }


def apply_google_changes_to_reminders(
    config: dict[str, Any],
    calendar_id: str,
    desired: dict[str, tuple[dict[str, Any], str, dict[str, Any]]],
    existing_by_uid: dict[str, dict[str, Any]],
    state: dict[str, Any],
    dry_run: bool,
    *,
    planned: dict[str, Any] | None = None,
) -> tuple[int, int, int, set[str]]:
    preview = planned or plan_google_changes_to_reminders(
        config,
        calendar_id,
        desired,
        existing_by_uid,
        state,
    )
    operations = preview["operations"]
    initialized = int(preview["initialized"])
    conflicts = list(preview["conflicts"])
    blocked_uids = set(preview["blocked_uids"])

    if conflicts:
        for title in conflicts:
            print(f"Skipping bidirectional conflict: {title}")

    if not operations:
        if initialized:
            print(f"Bidirectional state initialized for {initialized} synced events.")
        return 0, initialized, len(conflicts), blocked_uids

    if dry_run:
        for operation in operations:
            print(f"DRY-RUN apply Google change to Apple Reminders: {operation.get('title')}")
        return len(operations), initialized, len(conflicts), blocked_uids

    results = run_reminders_apply(config, operations)
    missing = [result for result in results if result.get("status") == "missing"]
    for result in missing:
        eprint(f"Could not find Apple reminder for Google change: {result.get('stable_id')}")
    applied = sum(1 for result in results if result.get("status") in ("updated", "deleted", "completed"))
    if applied:
        print(f"Applied Google changes to Apple Reminders: {applied}")
    if initialized:
        print(f"Bidirectional state initialized for {initialized} synced events.")
    return applied, initialized, len(conflicts), blocked_uids


def plan_google_task_changes_to_reminders(
    config: dict[str, Any],
    desired_by_list: dict[str, dict[str, tuple[dict[str, Any], str, dict[str, Any]]]],
    tasklists: dict[str, str],
    existing_by_list: dict[str, dict[str, dict[str, Any]]],
    all_tasks_by_list: dict[str, list[dict[str, Any]]],
    deleted_tasks_by_list: dict[str, list[dict[str, Any]]],
    state: dict[str, Any],
    *,
    allow_deletes: bool,
) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    operation_contexts: list[tuple[str, Any]] = []
    google_patches: list[tuple[str, str, str, dict[str, Any], str, dict[str, Any], dict[str, Any]]] = []
    initialized = 0
    conflicts: list[str] = []
    blocked: set[tuple[str, str]] = set()
    source_controlled: set[tuple[str, str]] = set()
    actions: list[dict[str, Any]] = []
    seen_deleted_uids: set[tuple[str, str]] = set()

    if allow_deletes:
        for list_title, tasks in deleted_tasks_by_list.items():
            if not list_allows_google_to_apple(config, list_title):
                continue
            if not list_allows_delete_propagation(
                config,
                list_title,
                safety_allows_deletes=allow_deletes,
            ):
                continue
            tasklist_id = tasklists.get(list_title)
            if not tasklist_id:
                continue
            desired = desired_by_list.get(list_title, {})
            active_by_uid = existing_by_list.get(list_title, {})

            for task in tasks:
                if not task.get("deleted"):
                    continue
                metadata = parse_tasks_sync_metadata(str(task.get("notes") or ""))
                if metadata.get(SYNC_MARKER_KEY) != SYNC_MARKER_VALUE:
                    continue
                uid = metadata.get("source uid")
                if not uid or (list_title, uid) in seen_deleted_uids:
                    continue
                if uid in active_by_uid:
                    continue

                record = task_state_record(state, tasklist_id, uid)
                # A tombstone is an edge from the currently tracked task, not
                # a permanent ban on this source UID. Successful deletion in
                # either direction removes that mapping. Replaying its old
                # tombstone would delete an Apple reminder the user restored.
                if not record or not task.get("id") or record.get("task_id") != task.get("id"):
                    continue
                desired_item = desired.get(uid)
                reminder = desired_item[2] if desired_item else {}
                if record and desired_item and record.get("digest") and record.get("digest") != desired_item[1]:
                    policy = list_sync_policy(config, list_title)
                    if policy["direction"] != "google_to_apple":
                        if policy["conflict_policy"] == "newer_wins":
                            if not google_task_is_newer_than_reminder(task, reminder):
                                continue
                        else:
                            title = str(task.get("title") or reminder.get("title") or record.get("title") or uid)
                            conflicts.append(title)
                            blocked.add((list_title, uid))
                            continue

                stable_id = (
                    reminder.get("stable_id")
                    or reminder.get("external_id")
                    or reminder.get("id")
                    or (record or {}).get("source_stable_id")
                )
                if not stable_id:
                    continue

                title = str(task.get("title") or reminder.get("title") or (record or {}).get("title") or uid)
                operations.append(
                    {
                        "stable_id": stable_id,
                        "id": stable_id,
                        "title": title,
                        "delete": True,
                    }
                )
                operation_contexts.append(("delete", (list_title, tasklist_id, uid)))
                blocked.add((list_title, uid))
                source_controlled.add((list_title, uid))
                seen_deleted_uids.add((list_title, uid))
                actions.append(
                    planned_mutation(
                        "apple_reminders",
                        "delete",
                        [list_title, tasklist_id, uid, stable_id],
                        destructive=True,
                        list_title=list_title,
                        title=title,
                    )
                )

    for list_title, desired in desired_by_list.items():
        if not list_allows_google_to_apple(config, list_title):
            continue
        tasklist_id = tasklists.get(list_title)
        if not tasklist_id:
            continue
        existing_by_uid = existing_by_list.get(list_title, {})
        for uid, (body, digest, reminder) in desired.items():
            existing = existing_by_uid.get(uid)
            if not existing:
                continue

            record = task_state_record(state, tasklist_id, uid)
            current_google_digest = task_change_digest(existing, reminder, config)
            expected_google_digest = task_change_digest(body, reminder, config)
            stored_google_digest = record.get("google_digest") if record else None

            if stored_google_digest:
                google_changed = current_google_digest != stored_google_digest
            else:
                google_changed = current_google_digest != expected_google_digest
                if not google_changed:
                    initialized += 1

            if not google_changed:
                continue

            apple_changed = bool(record and record.get("digest") and record.get("digest") != digest)
            title = str(existing.get("title") or body.get("title") or uid)
            policy = list_sync_policy(config, list_title)
            google_is_authoritative = policy["direction"] == "google_to_apple"
            preserve_concurrent_apple_due = bool(
                apple_changed
                and not google_is_authoritative
                and body.get("due")
                and not existing.get("due")
            )

            # Google Tasks can temporarily omit a generated due field. Also,
            # when both sides changed, a newer Google title or note must not
            # erase a date that was concurrently added in Apple Reminders.
            # A due date that was changed, or removed after the bridge last
            # wrote the task, is a real edit in Google and flows to Apple.
            google_due_missing = bool(body.get("due")) and not existing.get("due")
            stale_google_read = google_due_missing and not google_updated_since_sync(existing, record)
            if task_only_due_differs(existing, body, reminder, config) and (
                (stale_google_read and task_has_current_source_digest(existing, digest))
                or preserve_concurrent_apple_due
            ):
                continue

            # A completed Google task can outlive its local state record while the
            # matching Apple reminder is completed. If the reminder is reopened
            # later, resolve that recordless completion mismatch with the configured
            # conflict policy instead of always completing the Apple reminder again.
            reopened_without_state = bool(
                not record
                and str(existing.get("status") or "needsAction") == "completed"
                and str(body.get("status") or "needsAction") == "needsAction"
            )
            if reopened_without_state and not google_is_authoritative:
                if policy["conflict_policy"] != "newer_wins":
                    conflicts.append(title)
                    blocked.add((list_title, uid))
                    continue
                if not google_task_is_newer_than_reminder(existing, reminder):
                    continue

            if apple_changed:
                if current_google_digest == expected_google_digest:
                    initialized += 1
                    continue
                if google_is_authoritative or policy["conflict_policy"] == "newer_wins":
                    if google_is_authoritative or google_task_is_newer_than_reminder(existing, reminder):
                        operation = google_task_to_reminder_operation(existing, reminder, config)
                        if preserve_concurrent_apple_due:
                            operation.pop("clear_due", None)
                        if operation.get("complete") and not list_allows_delete_propagation(
                            config,
                            list_title,
                            safety_allows_deletes=allow_deletes,
                        ):
                            blocked.add((list_title, uid))
                            source_controlled.add((list_title, uid))
                            continue
                        operations.append(operation)
                        operation_contexts.append(("update", None))
                        if not preserve_concurrent_apple_due or operation.get("complete"):
                            source_controlled.add((list_title, uid))
                        operation_name = "complete" if operation.get("complete") else "update"
                        actions.append(
                            planned_mutation(
                                "apple_reminders",
                                operation_name,
                                [list_title, tasklist_id, uid],
                                destructive=operation_name == "complete",
                                list_title=list_title,
                                title=title,
                            )
                        )
                    continue
                conflicts.append(title)
                blocked.add((list_title, uid))
                continue

            operation = google_task_to_reminder_operation(existing, reminder, config)
            if operation.get("complete") and not list_allows_delete_propagation(
                config,
                list_title,
                safety_allows_deletes=allow_deletes,
            ):
                blocked.add((list_title, uid))
                source_controlled.add((list_title, uid))
                continue
            operations.append(operation)
            operation_contexts.append(("update", None))
            source_controlled.add((list_title, uid))
            operation_name = "complete" if operation.get("complete") else "update"
            actions.append(
                planned_mutation(
                    "apple_reminders",
                    operation_name,
                    [list_title, tasklist_id, uid],
                    destructive=operation_name == "complete",
                    list_title=list_title,
                    title=title,
                )
            )

    if config.get("tasks_import_unsynced"):
        for list_title, tasks in all_tasks_by_list.items():
            if not list_allows_google_to_apple(config, list_title):
                continue
            tasklist_id = tasklists.get(list_title)
            if not tasklist_id:
                continue
            desired = desired_by_list.get(list_title, {})
            desired_by_fingerprint = unique_desired_by_task_fingerprint(desired)
            existing_by_uid = existing_by_list.get(list_title, {})

            for task in tasks:
                task_id = str(task.get("id") or "")
                if not task_id:
                    continue
                if str(task.get("status") or "needsAction") == "completed":
                    continue

                metadata = parse_tasks_sync_metadata(str(task.get("notes") or ""))
                if metadata.get(SYNC_MARKER_KEY) == SYNC_MARKER_VALUE:
                    continue

                matched = desired_by_fingerprint.get(task_fingerprint(task))
                if matched:
                    uid, body, digest, reminder = matched
                    if uid in existing_by_uid:
                        continue
                    google_patches.append((list_title, tasklist_id, uid, body, digest, reminder, task))
                    source_controlled.add((list_title, uid))
                    actions.append(
                        planned_mutation(
                            "google_tasks",
                            "attach",
                            [list_title, tasklist_id, uid, task_id],
                        )
                    )
                    continue

                operation = google_task_to_new_reminder_operation(task, list_title, config)
                if not operation:
                    continue

                operations.append(operation)
                operation_contexts.append(("create", (list_title, tasklist_id, task)))
                actions.append(
                    planned_mutation(
                        "apple_reminders",
                        "create",
                        [list_title, tasklist_id, task_id],
                    )
                )
                actions.append(
                    planned_mutation(
                        "google_tasks",
                        "attach_after_create",
                        [list_title, tasklist_id, task_id],
                    )
                )

    return {
        "operations": operations,
        "operation_contexts": operation_contexts,
        "google_patches": google_patches,
        "initialized": initialized,
        "conflicts": conflicts,
        "blocked": blocked,
        "source_controlled": source_controlled,
        "actions": actions,
    }


def apply_google_task_changes_to_reminders(
    config: dict[str, Any],
    client: GoogleTasksClient,
    desired_by_list: dict[str, dict[str, tuple[dict[str, Any], str, dict[str, Any]]]],
    tasklists: dict[str, str],
    existing_by_list: dict[str, dict[str, dict[str, Any]]],
    all_tasks_by_list: dict[str, list[dict[str, Any]]],
    deleted_tasks_by_list: dict[str, list[dict[str, Any]]],
    state: dict[str, Any],
    dry_run: bool,
    *,
    planned: dict[str, Any] | None = None,
    allow_deletes: bool = True,
) -> tuple[int, int, int, set[tuple[str, str]]]:
    preview = planned or plan_google_task_changes_to_reminders(
        config,
        desired_by_list,
        tasklists,
        existing_by_list,
        all_tasks_by_list,
        deleted_tasks_by_list,
        state,
        allow_deletes=allow_deletes,
    )
    operations = preview["operations"]
    operation_contexts = preview["operation_contexts"]
    google_patches = preview["google_patches"]
    initialized = int(preview["initialized"])
    conflicts = list(preview["conflicts"])
    blocked = set(preview["blocked"])

    if conflicts:
        for title in conflicts:
            print(f"Skipping bidirectional conflict: {title}")

    if not operations and not google_patches:
        if initialized:
            print(f"Bidirectional state initialized for {initialized} synced tasks.")
        return 0, initialized, len(conflicts), blocked

    if dry_run:
        for operation in operations:
            if operation.get("delete"):
                print(f"DRY-RUN delete Apple Reminder from deleted Google Tasks: {operation.get('title')}")
            elif operation.get("create"):
                print(f"DRY-RUN create Apple Reminder from Google Tasks: {operation.get('title')}")
            else:
                print(f"DRY-RUN apply Google Tasks change to Apple Reminders: {operation.get('title')}")
        for _list_title, _tasklist_id, _uid, body, _digest, _reminder, task in google_patches:
            print(f"DRY-RUN attach existing Google Tasks item to Apple Reminder: {task.get('title') or body.get('title')}")
        return len(operations) + len(google_patches), initialized, len(conflicts), blocked

    applied = 0
    for list_title, tasklist_id, uid, body, digest, reminder, task in google_patches:
        task_id = str(task.get("id") or "")
        patched = client.patch_task(tasklist_id, task_id, task_body_for_patch(body, task))
        save_task_state(state, tasklist_id, uid, patched, digest, str(body.get("title") or uid), reminder, config, list_title)
        blocked.add((list_title, uid))
        applied += 1

    results = run_reminders_apply(config, operations) if operations else []
    for result, (kind, _context) in zip(results, operation_contexts):
        if result.get("status") == "missing" and kind != "delete":
            eprint(f"Could not find Apple reminder for Google Tasks change: {result.get('stable_id')}")
    missing_lists = [result for result in results if result.get("status") == "missing_list"]
    for result in missing_lists:
        eprint(f"Could not find Apple Reminders list for Google Tasks import: {result.get('list_title')}")

    for result, (kind, context) in zip(results, operation_contexts):
        status = str(result.get("status") or "")
        if kind == "delete" and context:
            list_title, tasklist_id, uid = context
            if status in ("deleted", "missing"):
                remove_task_state_record(state, tasklist_id, uid)
                blocked.add((list_title, uid))
                if status == "deleted":
                    applied += 1
            continue

        if status in ("updated", "deleted", "completed"):
            applied += 1
            continue
        if status != "created" or not context:
            continue

        list_title, tasklist_id, task = context
        task_id = str(task.get("id") or "")
        reminder = reminder_from_created_task_result(result, task, list_title, config)
        uid, body, digest = build_task(reminder, config)
        patched = client.patch_task(tasklist_id, task_id, task_body_for_patch(body, task))
        save_task_state(state, tasklist_id, uid, patched, digest, str(body.get("title") or uid), reminder, config, list_title)
        blocked.add((list_title, uid))
        applied += 1

    if applied:
        print(f"Applied Google Tasks changes to Apple Reminders: {applied}")
    if initialized:
        print(f"Bidirectional state initialized for {initialized} synced tasks.")
    return applied, initialized, len(conflicts), blocked


def save_event_state(
    state: dict[str, Any],
    calendar_id: str,
    uid: str,
    event: dict[str, Any],
    digest: str,
    title: str,
    reminder: dict[str, Any],
    config: dict[str, Any],
) -> None:
    state["events"][state_key(calendar_id, uid)] = {
        "calendar_id": calendar_id,
        "event_id": event["id"],
        "digest": digest,
        "google_digest": google_change_digest(event, reminder, config),
        "source_stable_id": reminder.get("stable_id") or reminder.get("external_id") or reminder.get("id"),
        "source_modified_at": reminder.get("modified_at"),
        "apple_completed": bool(reminder.get("is_completed")),
        "apple_recurring": bool(reminder.get("is_recurring")),
        "title": title,
        "synced_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }


def save_task_state(
    state: dict[str, Any],
    tasklist_id: str,
    uid: str,
    task: dict[str, Any],
    digest: str,
    title: str,
    reminder: dict[str, Any],
    config: dict[str, Any],
    list_title: str,
) -> None:
    state.setdefault("tasks", {})[target_state_key(tasklist_id, uid)] = {
        "tasklist_id": tasklist_id,
        "tasklist_title": list_title,
        "task_id": task["id"],
        "digest": digest,
        "google_digest": task_change_digest(task, reminder, config),
        # Google's own modification time as last written or seen by the bridge;
        # a later value proves a change made in Google rather than a stale read.
        "google_updated": str(task.get("updated") or ""),
        "source_stable_id": reminder.get("stable_id") or reminder.get("external_id") or reminder.get("id"),
        "source_modified_at": reminder.get("modified_at"),
        "apple_completed": bool(reminder.get("is_completed")),
        "apple_recurring": bool(reminder.get("is_recurring")),
        "title": title,
        "synced_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }


def state_record(state: dict[str, Any], calendar_id: str, uid: str) -> dict[str, Any] | None:
    record = state["events"].get(state_key(calendar_id, uid))
    return record if isinstance(record, dict) else None


def task_state_record(state: dict[str, Any], tasklist_id: str, uid: str) -> dict[str, Any] | None:
    tasks_state = state.setdefault("tasks", {})
    record = tasks_state.get(target_state_key(tasklist_id, uid))
    return record if isinstance(record, dict) else None


def remove_state_record(state: dict[str, Any], calendar_id: str, uid: str) -> None:
    state["events"].pop(state_key(calendar_id, uid), None)


def remove_task_state_record(state: dict[str, Any], tasklist_id: str, uid: str) -> None:
    state.setdefault("tasks", {}).pop(target_state_key(tasklist_id, uid), None)


def cmd_gcloud_login(args: argparse.Namespace) -> None:
    config = load_config(args)
    if not shutil.which("gcloud"):
        raise SystemExit("gcloud is not installed. Install Google Cloud CLI first.")

    credentials_path = expand_path(config["credentials_path"])
    if not credentials_path.exists():
        raise SystemExit(
            "Google Cloud CLI cannot request Google Calendar/Tasks scopes with its built-in OAuth client.\n"
            "Create a Desktop OAuth client JSON and save it here first:\n"
            f"  {credentials_path}\n"
            "Then rerun:\n"
            "  ltb gcloud-login\n"
            "Google's own gcloud help documents this requirement for non-Google-Cloud scopes."
        )

    command = [
        "gcloud",
        "auth",
        "application-default",
        "login",
        f"--client-id-file={credentials_path}",
        f"--scopes={GCLOUD_LOGIN_SCOPES}",
    ]
    print("Running Google Cloud ADC login. Complete the browser login when it opens.")
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    adc_path = expand_path(config["adc_credentials_path"])
    if adc_path.exists():
        write_sync_status(
            config,
            {
                "state": "auth_refreshed",
                "last_manual_auth_completed_at": utc_now_text(),
                **auto_reauth_failure_epoch_reset_updates(),
                "last_error": "",
            },
        )
        print(f"ADC credentials ready: {adc_path}")
    else:
        raise SystemExit(f"gcloud finished but ADC credentials were not found: {adc_path}")


def cmd_export(args: argparse.Namespace) -> None:
    config = load_config(args)
    reminders = run_reminders_export(config)
    print(json.dumps(reminders, indent=2, ensure_ascii=False, sort_keys=True))


# --- Installation layout ----------------------------------------------------


def launchctl_available() -> bool:
    if os.environ.get("LTB_NO_LAUNCHCTL") == "1":
        return False
    return sys.platform == "darwin" and shutil.which("launchctl") is not None


def launch_agents_dir() -> Path:
    override = str(os.environ.get("LTB_LAUNCH_AGENTS_DIR") or "").strip()
    return Path(override).expanduser() if override else Path.home() / "Library" / "LaunchAgents"


def launch_agent_path() -> Path:
    return launch_agents_dir() / f"{LAUNCH_AGENT_LABEL}.plist"


def legacy_launch_agent_path() -> Path:
    return launch_agents_dir() / f"{LEGACY_LAUNCH_AGENT_LABEL}.plist"


def log_dir() -> Path:
    override = str(os.environ.get("LTB_LOG_DIR") or "").strip()
    return Path(override).expanduser() if override else Path.home() / "Library" / "Logs" / "LocalTasksBridge"


def default_engine_log_path() -> Path:
    return log_dir() / "engine.log"


def app_bundle_of_engine(engine_dir: Path | None = None) -> Path | None:
    """The .app this engine runs from (…/X.app/Contents/Resources/engine), if any."""

    directory = (engine_dir or ENGINE_DIR).resolve()
    parents = directory.parents
    if (
        directory.name == "engine"
        and len(parents) >= 3
        and parents[0].name == "Resources"
        and parents[1].name == "Contents"
        and parents[2].suffix == ".app"
    ):
        return parents[2]
    return None


def app_bundle_from_launch_agent(path: Path | None = None) -> Path | None:
    """The .app the login item starts, read from its LaunchAgent plist."""

    plist_path = path or launch_agent_path()
    try:
        payload = plistlib.loads(plist_path.read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    arguments = payload.get("ProgramArguments") if isinstance(payload, dict) else None
    if not isinstance(arguments, list) or not arguments:
        return None
    program = Path(str(arguments[0]))
    for parent in program.parents:
        if parent.suffix == ".app":
            return parent
    return None


def running_from_installed_engine() -> bool:
    """Whether this engine is the copy the background service runs.

    Recovery actions refuse to run from a different copy (for example a
    source checkout next to an installed app) so the two versions never
    take turns on the same sync state.
    """

    installed = app_bundle_from_launch_agent()
    if installed is None:
        return True
    current = app_bundle_of_engine()
    try:
        return current is not None and current.resolve() == installed.resolve()
    except OSError:
        return False


def control_dir(config: dict[str, Any]) -> Path:
    """Where the pause flag, sync-now request, and loop lock live: next to the config."""

    if config.get("_config_path"):
        return expand_path(config["_config_path"]).parent
    return expand_path(config.get("state_path") or default_config_dir() / "state.json").parent


def pause_flag_path(config: dict[str, Any]) -> Path:
    return control_dir(config) / "paused"


def sync_now_path(config: dict[str, Any]) -> Path:
    return control_dir(config) / "sync-now"


def loop_lock_path(config: dict[str, Any]) -> Path:
    return control_dir(config) / "run-loop.lock"


def sync_paused(config: dict[str, Any]) -> bool:
    return pause_flag_path(config).exists()


def touch_private_file(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.chmod(path, 0o600)


def background_loop_running(config: dict[str, Any]) -> bool:
    """True while some `run-loop` process holds the loop lock."""

    path = loop_lock_path(config)
    if not path.exists():
        return False
    try:
        with path.open("a", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        return False
    return False


def launch_agent_loaded() -> bool | None:
    if not launchctl_available():
        return None
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{LAUNCH_AGENT_LABEL}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode == 0


def local_status_snapshot(config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    status_path = expand_path(config["status_path"])
    if not status_path.exists():
        return "missing", {}
    try:
        status = read_json(status_path)
    except (OSError, json.JSONDecodeError):
        return "unreadable", {}
    if not isinstance(status, dict):
        return "unreadable", {}
    return "available", status


def safe_status_time(value: Any) -> str:
    parsed = parse_status_time(value)
    return parsed.isoformat(timespec="seconds") if parsed else "unknown"


def doctor_next_step(
    *,
    config_exists: bool,
    swift_ready: bool,
    helpers_ready: bool,
    runtime_ready: bool,
    auth_material_ready: bool,
    launch_agent_installed: bool,
    agent_loaded: bool | None,
    status_result: str,
    status_state: str,
) -> str:
    if not config_exists:
        return tr(
            "Open Local Tasks Bridge and complete the setup assistant (or run `ltb config init`).",
            "请打开 Local Tasks Bridge 并完成设置向导（或运行 `ltb config init`）。",
        )
    if not swift_ready or not helpers_ready or not runtime_ready:
        return tr(
            "Reinstall Local Tasks Bridge; the Reminders helper programs are missing.",
            "请重新安装 Local Tasks Bridge：缺少提醒事项辅助程序。",
        )
    if status_state == "auth_prompt_open":
        return tr(
            "Finish the Google sign-in that is open in your browser, then check again.",
            "请完成浏览器中正在进行的 Google 登录，然后再检查一次。",
        )
    if not auth_material_ready or status_state in {"auth_required", "auth_timeout"}:
        return tr(
            "Sign in to Google again: choose \"Reconnect Google…\" in the app, or run `ltb auth`.",
            "请重新登录 Google：在 App 中选择“重新连接 Google…”，或运行 `ltb auth`。",
        )
    if status_state == "account_binding_required":
        return tr(
            "The Apple or Google account changed. Run `ltb manage reconnect` (or Settings > Google > Reconnect): "
            "it checks Google, backs up the private state, and rebuilds it with --no-delete-stale after you confirm.",
            "Apple 或 Google 账号发生了变化。请运行 `ltb manage reconnect`（或在设置 > Google 中重新连接）："
            "它会先检查 Google、备份私有状态，并在你确认后用 --no-delete-stale 安全重建。",
        )
    if status_state == "awaiting_mutation_approval":
        return tr(
            "A large deletion/completion plan is waiting for your answer while other changes keep syncing. "
            "Answer the on-screen prompt, or choose \"Review Pending Changes…\" (`ltb approvals show`).",
            "有一批较多的删除/完成操作在等待你确认，其余改动仍在正常同步。请回答屏幕上的确认框，"
            "或选择“查看待确认的更改…”（`ltb approvals show`）。",
        )
    if status_state == "blocked_mutation_plan":
        return tr(
            "Review the blocked plan with `ltb approvals show`, then apply or hold it.",
            "请用 `ltb approvals show` 查看被拦下的计划，然后选择执行或暂缓。",
        )
    if status_state == "dry_run_ok":
        return tr(
            "Review the dry-run counts, then run the first live sync with --no-delete-stale "
            "before relying on scheduled synchronization.",
            "请先查看试运行的数量，再用 --no-delete-stale 执行第一次正式同步，之后再依赖后台定时同步。",
        )
    if status_result == "unreadable":
        return tr(
            "Back up the private status file, repair its JSON, then check again.",
            "请先备份私有状态文件并修复其 JSON，然后再检查。",
        )
    if status_result == "missing":
        return tr(
            "Run a first dry-run with --no-delete-stale (the setup assistant does this for you).",
            "请先用 --no-delete-stale 做一次试运行（设置向导会自动完成）。",
        )
    if status_state == "paused":
        return tr("Sync is paused. Resume it from the menu bar or with `ltb resume`.", "同步已暂停。可在菜单栏或用 `ltb resume` 恢复。")
    if agent_loaded is False:
        return tr(
            "Background sync is not running. Open Local Tasks Bridge (it starts at login once set up).",
            "后台同步没有运行。请打开 Local Tasks Bridge（完成设置后会在登录时自动启动）。",
        )
    if status_state == "failed":
        return tr(
            "Check the private log (Open Logs in the app), fix the reported cause, then check again. "
            "Stored error details are intentionally hidden here.",
            "请查看私有日志（App 中“打开日志”），处理报错原因后再检查。此处有意不显示具体错误内容。",
        )
    if status_state == "running":
        return tr("Wait for the current cycle to finish, then check again.", "请等待当前这一轮同步结束后再检查。")
    if status_state in {"ok", "auth_refreshed"}:
        return tr("No action needed.", "无需任何操作。")
    return tr(
        "Check the private log and look again after the next scheduled cycle.",
        "请查看私有日志，并在下一轮定时同步后再检查。",
    )


def run_online_doctor_checks(config: dict[str, Any]) -> None:
    print(tr("Online Google checks:", "在线 Google 检查："))
    result = check_google_connection(config)
    if result["state"] == "ok":
        print(tr("  Google auth refresh: ok", "  Google 授权刷新：正常"))
        if config["target_service"] == "tasks":
            print(tr("  Google Tasks API: ok", "  Google Tasks API：正常"))
    elif result["state"] == "auth_required":
        if result.get("source") == "google_api":
            print(f"  Google API: {result['message']}")
        else:
            print(tr("  Google auth refresh: sign-in required", "  Google 授权刷新：需要重新登录"))
    elif result["state"] == "api_error":
        print(f"  Google API: {result['message']}")
    else:
        print(tr(
            "  Google checks: unavailable; check the network or proxy and retry later",
            "  Google 检查：暂时不可用；请检查网络或代理后重试",
        ))


def check_google_connection(config: dict[str, Any]) -> dict[str, Any]:
    """Refresh the selected credential and prove the configured Google API is reachable.

    The returned message is deliberately sanitized. Callers may show it in a local
    management UI without exposing Google response bodies, tokens, or local paths.
    """
    try:
        token = load_token(config)
        refreshed = refresh_token_with_fallback(config, token)
        tasklist_count = 0
        if config["target_service"] == "tasks":
            client = GoogleTasksClient(config)
            client.token = refreshed
            tasklist_count = len(client.list_tasklists())
        identity = fetch_google_account_identity(str(refreshed.get("access_token") or ""))
        return {
            "state": "ok",
            "source": "google_api",
            "tasklist_count": tasklist_count,
            **identity,
            "message": tr("Google connection is healthy.", "Google 连接正常。"),
        }
    except AuthenticationRequired:
        return {
            "state": "auth_required",
            "source": "oauth",
            "tasklist_count": 0,
            "message": tr("Google authorization has expired or was revoked.", "Google 授权已过期或已被撤销。"),
        }
    except OAuthTokenError as exc:
        return {"state": "auth_required", "source": "oauth", "tasklist_count": 0, "message": str(exc)}
    except GoogleApiError as exc:
        state = "auth_required" if exc.status in (401, 403) else "api_error"
        return {
            "state": state,
            "source": "google_api",
            "tasklist_count": 0,
            "message": str(exc),
        }
    except SystemExit:
        return {
            "state": "auth_required",
            "source": "oauth",
            "tasklist_count": 0,
            "message": tr("Google sign-in information is missing or invalid.", "缺少 Google 登录信息，或信息无效。"),
        }
    except (OSError, json.JSONDecodeError, ValueError):
        return {
            "state": "unavailable",
            "source": "network",
            "tasklist_count": 0,
            "message": message_network(),
        }


def fetch_google_account_identity(access_token: str) -> dict[str, str]:
    """Return display-only Google identity details without persisting raw claims."""
    if not access_token:
        return {"account_email": "", "account_fingerprint": ""}
    request = urllib.request.Request(
        OAUTH_USERINFO_URL,
        headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return {"account_email": "", "account_fingerprint": ""}
    if not isinstance(payload, dict):
        return {"account_email": "", "account_fingerprint": ""}
    email = " ".join(str(payload.get("email") or "").split())
    subject = str(payload.get("sub") or "").strip()
    return {
        "account_email": email,
        "account_fingerprint": sha256_text(f"google-openid-sub\n{subject}", 12) if subject else "",
    }


class ManagementActionError(RuntimeError):
    pass


def setup_completed(config: dict[str, Any], status: dict[str, Any] | None = None) -> bool:
    if config.get("setup_completed_at"):
        return True
    return bool((status or {}).get("last_success_at"))


def collect_management_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    config_exists = expand_path(config["_config_path"]).is_file()
    helpers_ready = True
    try:
        resolve_reminders_helper(config, "export")
        resolve_reminders_helper(config, "apply")
    except RemindersUnavailable:
        helpers_ready = False
    status_result, status = local_status_snapshot(config)
    raw_state = str(status.get("state") or "unknown")
    try:
        failure_count = max(0, int(status.get("consecutive_failures") or 0))
    except (TypeError, ValueError):
        failure_count = 0
    client = oauth_client_status(config)
    agent_path = launch_agent_path()
    return {
        "config_exists": config_exists,
        "setup_completed": setup_completed(config, status),
        "swift_ready": helpers_ready,
        "helpers_ready": helpers_ready,
        "oauth_client_ready": client["active"] != "missing",
        "oauth_client": client,
        "auth_material_ready": expand_path(config["token_path"]).is_file()
        or (bool(config.get("use_adc")) and expand_path(config["adc_credentials_path"]).is_file()),
        "runtime_ready": helpers_ready and Path(__file__).is_file(),
        "running_from_stable_runtime": running_from_installed_engine(),
        "control_dir": str(control_dir(config)),
        "launch_agent_path": agent_path,
        "launch_agent_installed": agent_path.is_file(),
        "launch_agent_loaded": launch_agent_loaded(),
        # "agent_loaded" means "the background sync loop is running", whether
        # the menu bar app or a command-line run-loop hosts it.
        "agent_loaded": background_loop_running(config),
        "paused": sync_paused(config),
        "status_result": status_result,
        "status_state": raw_state if raw_state in KNOWN_STATUS_STATES else "unknown",
        "last_success_at": status.get("last_success_at"),
        "last_start_at": status.get("last_start_at"),
        "last_end_at": status.get("last_end_at"),
        "updated_at": status.get("updated_at"),
        "failure_count": failure_count,
        "pending_destructive_counts": pending_destructive_counts(status),
    }


def pending_destructive_counts(status: dict[str, Any]) -> dict[str, int]:
    """Counts of a plan still waiting for a decision; hashes and counts only."""
    if str(status.get("state") or "") not in {"awaiting_mutation_approval", "blocked_mutation_plan"}:
        return {}
    plan = status.get("mutation_plan")
    counts = plan.get("destructive_counts") if isinstance(plan, dict) else None
    if not isinstance(counts, dict):
        return {}
    pending: dict[str, int] = {}
    for key, value in counts.items():
        try:
            pending[str(key)] = max(0, int(value))
        except (TypeError, ValueError):
            continue
    return dict(sorted(pending.items()))


def management_condition(snapshot: dict[str, Any]) -> tuple[str, str, str]:
    """(condition code, headline, recommended action) for people and the app."""

    if not snapshot["config_exists"] or not snapshot["runtime_ready"] or not snapshot["helpers_ready"]:
        return (
            "setup_required",
            tr("Setup is not complete.", "尚未完成设置。"),
            tr(
                "Open Local Tasks Bridge and finish the setup assistant.",
                "请打开 Local Tasks Bridge 并完成设置向导。",
            ),
        )
    state = str(snapshot["status_state"])
    if state == "account_binding_required":
        return (
            "account_binding_required",
            tr(
                "Sync stopped safely because the Apple or Google account changed.",
                "检测到 Apple 或 Google 账号发生变化，同步已安全停止。",
            ),
            tr(
                "Choose \"Reconnect Google\" to back up and rebuild the sync map without propagating deletions.",
                "请选择“重新连接 Google”：会先备份，再在不传播删除的前提下重建同步对应关系。",
            ),
        )
    if state in {"auth_required", "auth_timeout"} or not snapshot["auth_material_ready"]:
        return (
            "auth_required",
            tr(
                "Google sign-in has expired or is missing.",
                "Google 登录已过期或尚未登录。",
            ),
            tr(
                "Choose \"Reconnect Google\" and finish signing in in the browser.",
                "请选择“重新连接 Google”，并在浏览器中完成登录。",
            ),
        )
    if state == "awaiting_mutation_approval":
        return (
            "mutation_approval_pending",
            tr(
                "A large batch of deletions/completions is waiting for your review; everything else keeps syncing.",
                "有一批较多的删除/完成操作在等待你确认；其余改动仍在继续同步。",
            ),
            tr(
                "Answer the on-screen prompt, or choose \"Review Pending Changes\".",
                "请回答屏幕上的确认框，或选择“查看待确认的更改”。",
            ),
        )
    if state == "blocked_mutation_plan":
        return (
            "mutation_blocked",
            tr(
                "A large batch of deletions/completions exceeded the safety limit and needs review.",
                "一批删除/完成操作超过了安全上限，需要你确认。",
            ),
            tr(
                "Choose \"Review Pending Changes\" to see the items, then apply or hold them.",
                "请选择“查看待确认的更改”查看具体条目，再决定执行或暂缓。",
            ),
        )
    if snapshot.get("paused"):
        return (
            "paused",
            tr("Sync is paused.", "同步已暂停。"),
            tr("Choose \"Resume Sync\" when you are ready.", "需要时请选择“恢复同步”。"),
        )
    if state == "failed":
        return (
            "failed",
            tr("The last sync failed.", "最近一次同步失败。"),
            tr(
                "Check the Google connection, then look at the private log for the cause.",
                "请检查 Google 连接，再在私有日志中查看原因。",
            ),
        )
    if snapshot["agent_loaded"] is False and snapshot.get("setup_completed", True):
        return (
            "agent_stopped",
            tr("Background sync is not running.", "后台同步没有在运行。"),
            tr(
                "Open Local Tasks Bridge; it keeps syncing in the menu bar and starts at login.",
                "请打开 Local Tasks Bridge；它会在菜单栏持续同步，并在登录时自动启动。",
            ),
        )
    if snapshot["status_result"] == "missing":
        return (
            "never_synced",
            tr("Nothing has been synced yet.", "还没有进行过同步。"),
            tr(
                "Run the first safe sync from the setup assistant (no deletions are propagated).",
                "请在设置向导中完成第一次安全同步（不会传播任何删除）。",
            ),
        )
    if snapshot["status_result"] == "unreadable":
        return (
            "status_unreadable",
            tr("The status file cannot be read.", "无法读取状态文件。"),
            tr(
                "Back up the private status file; it is rewritten after the next sync.",
                "请备份私有状态文件；下一次同步后会重新生成。",
            ),
        )
    if state == "running":
        return ("running", tr("Syncing now…", "正在同步…"), tr("Check again in a moment.", "请稍后再查看。"))
    if state == "ok":
        return (
            "healthy",
            tr("Apple Reminders and Google Tasks are in sync.", "Apple 提醒事项与 Google Tasks 已同步。"),
            tr("No action needed.", "无需任何操作。"),
        )
    if state in {"dry_run_ok", "auth_refreshed"}:
        return (
            "attention",
            tr(
                "Checks passed, but no full sync has completed since.",
                "检查已通过，但之后还没有完成一次完整同步。",
            ),
            tr(
                "Finish the first sync, or check again after the next scheduled cycle.",
                "请完成第一次同步，或等下一轮定时同步后再查看。",
            ),
        )
    return (
        "unknown",
        tr("The current state is unclear.", "当前状态无法确定。"),
        tr("Run \"Check Google connection\" to narrow it down.", "请运行“检查 Google 连接”进一步定位。"),
    )


def management_local_time(value: Any) -> str:
    parsed = parse_status_time(value)
    if not parsed:
        return tr("never", "无记录")
    return parsed.astimezone().isoformat(timespec="seconds")


def yes_no(value: bool, yes_en: str, yes_zh: str, no_en: str, no_zh: str) -> str:
    return tr(yes_en, yes_zh) if value else tr(no_en, no_zh)


def print_management_summary(config: dict[str, Any]) -> dict[str, Any]:
    snapshot = collect_management_snapshot(config)
    condition, headline, action = management_condition(snapshot)
    print("\n" + tr("Local Tasks Bridge — sync manager", "Local Tasks Bridge — 同步管理"))
    print("=" * 40)
    print(tr(f"Status: {headline}", f"状态：{headline}"))
    print(tr(f"Condition code: {condition}", f"状态代码：{condition}"))
    print(tr(
        f"Last successful sync: {management_local_time(snapshot['last_success_at'])}",
        f"最近成功同步：{management_local_time(snapshot['last_success_at'])}",
    ))
    print(tr(f"Consecutive failures: {snapshot['failure_count']}", f"连续失败次数：{snapshot['failure_count']}"))
    print(tr("Background sync: ", "后台同步：") + yes_no(bool(snapshot["agent_loaded"]), "running", "运行中", "stopped", "已停止"))
    if snapshot.get("paused"):
        print(tr("Paused: yes", "已暂停：是"))
    print(tr("Google sign-in: ", "Google 登录：") + yes_no(bool(snapshot["auth_material_ready"]), "ready", "已就绪", "missing", "缺失"))
    pending = snapshot.get("pending_destructive_counts") or {}
    if pending:
        print(
            tr("Pending large changes: ", "待确认的大批量更改：")
            + ", ".join(f"{mutation_review_label(key)} × {count}" for key, count in pending.items())
        )
    print(tr(f"Recommended: {action}", f"建议操作：{action}"))
    return snapshot


def management_confirm(args: argparse.Namespace, prompt: str) -> bool:
    if bool(getattr(args, "yes", False)):
        return True
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes", "是", "好"}


def backup_management_files(config: dict[str, Any], reason: str) -> Path:
    def private_path(value: str | os.PathLike[str]) -> Path:
        return Path(os.path.abspath(os.path.expanduser(os.fspath(value))))

    config_path = private_path(config["_config_path"])
    backup_root = config_path.parent / "backups"
    stamp = dt.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    backup_dir = backup_root / f"{stamp}-{reason}-{os.getpid()}"
    backup_dir.mkdir(parents=True, mode=0o700)
    os.chmod(backup_root, 0o700)
    os.chmod(backup_dir, 0o700)

    private_paths = {
        "config.json": config_path,
        "credentials.json": private_path(config["credentials_path"]),
        "gcloud-application-default-credentials.json": private_path(config["adc_credentials_path"]),
        "token.json": private_path(config["token_path"]),
        "state.json": private_path(config["state_path"]),
        "status.json": private_path(config["status_path"]),
    }
    copied = 0
    for backup_name, source in private_paths.items():
        if not source.is_file() or source.is_symlink():
            continue
        destination = backup_dir / backup_name
        shutil.copy2(source, destination)
        os.chmod(destination, 0o600)
        copied += 1
    if copied == 0:
        backup_dir.rmdir()
        raise ManagementActionError(
            tr("No private settings or state files were found to back up.", "没有找到可以备份的私有设置或状态文件。")
        )
    return backup_dir


MANAGEMENT_PAUSE_MARKER = "held-by-manager"


def stop_management_agent(snapshot: dict[str, Any]) -> bool:
    """Hold the background loop during a manual operation.

    Returns True when this call placed the hold, so the caller knows to
    release it. A pause the person set themselves is left alone.
    """

    config_dir = Path(snapshot.get("control_dir") or "")
    if not str(config_dir) or not config_dir.is_dir():
        return False
    flag = config_dir / "paused"
    if flag.exists():
        return False
    touch_private_file(flag, MANAGEMENT_PAUSE_MARKER)
    return True


def start_management_agent(snapshot: dict[str, Any]) -> None:
    """Release a hold placed by stop_management_agent and wake the loop."""

    config_dir = Path(snapshot.get("control_dir") or "")
    if not str(config_dir):
        return
    flag = config_dir / "paused"
    try:
        if flag.read_text(encoding="utf-8").strip() == MANAGEMENT_PAUSE_MARKER:
            flag.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ManagementActionError(
            tr("Could not resume background sync.", "无法恢复后台同步。")
        ) from exc
    with contextlib.suppress(OSError):
        touch_private_file(config_dir / "sync-now")


def run_management_safe_sync(
    config: dict[str, Any],
    *,
    dry_run: bool,
    lock_held: bool = False,
) -> dict[str, Any]:
    """One sync with deletion and completion propagation turned off."""

    safe_config = dict(config)
    safe_config["delete_stale"] = False
    safe_config["_disable_delete_propagation"] = True
    safe_config["_mutation_plan_approval"] = ""
    safe_config["auto_reauth_browser"] = False
    lock = contextlib.nullcontext(True) if lock_held else sync_lock(safe_config, wait=True)
    with lock as acquired:
        if not acquired:
            raise ManagementActionError(
                tr("Another sync is running. Try again in a moment.", "另一轮同步正在进行，请稍后再试。")
            )
        write_sync_status(
            safe_config,
            {"state": "running", "last_start_at": utc_now_text(), "last_error": "", "mutation_plan": None},
        )
        try:
            summary = run_sync(safe_config, dry_run=dry_run)
        except AccountBindingRequired as exc:
            write_sync_status(
                safe_config,
                {"state": "account_binding_required", "last_end_at": utc_now_text(), "last_error": str(exc)},
            )
            raise
        except (Exception, SystemExit) as exc:
            write_sync_status(
                safe_config,
                {
                    "state": "failed",
                    "last_end_at": utc_now_text(),
                    "last_error": str(exc.code if isinstance(exc, SystemExit) else exc),
                },
            )
            raise
        write_sync_status(
            safe_config,
            {
                "state": "dry_run_ok" if dry_run else "ok",
                "last_end_at": utc_now_text(),
                "last_success_at": utc_now_text(),
                **auto_reauth_failure_epoch_reset_updates(),
                "last_error": "",
                "consecutive_failures": 0,
            },
        )
    return {"summary": summary or {}, "plan": safe_config.get("_last_mutation_plan") or {}}


def reminders_account_titles(config: dict[str, Any]) -> list[str]:
    records = run_reminders_lists_export(config)
    return sorted(
        {
            str(record.get("account_title") or "").strip()
            for record in records
            if isinstance(record, dict) and str(record.get("account_title") or "").strip()
        }
    )


def authorize_google_for_management(config: dict[str, Any], args: argparse.Namespace) -> None:
    if config.get("use_adc") and shutil.which("gcloud"):
        try:
            cmd_gcloud_login(argparse.Namespace(config=config["_config_path"], adc_credentials_path=None))
            return
        except SystemExit as exc:
            print(tr(f"gcloud sign-in failed: {exc}", f"gcloud 登录失败：{exc}"))
            if not management_confirm(args, tr("Sign in directly in the browser instead?", "改为直接在浏览器中登录吗？")):
                raise ManagementActionError(tr("Google sign-in was not completed.", "Google 登录未完成。")) from exc
    cmd_auth(argparse.Namespace(config=config["_config_path"], credentials_path=None))


def archive_state_for_rebuild(config: dict[str, Any], backup_dir: Path) -> bool:
    state_path = expand_path(config["state_path"])
    if not state_path.exists():
        return False
    destination = backup_dir / "state.active-before-rebuild.json"
    if destination.exists():
        raise ManagementActionError(
            tr(
                "A state backup with the same name already exists; the current state was not moved.",
                "已存在同名的状态备份，因此没有移动当前状态。",
            )
        )
    state_path.replace(destination)
    os.chmod(destination, 0o600)
    return True


def google_account_display(result: dict[str, Any]) -> str:
    email = str(result.get("account_email") or "").strip()
    if email:
        return email
    fingerprint = str(result.get("account_fingerprint") or "").strip()
    if fingerprint:
        return tr(f"private ID {fingerprint}", f"私有标识 {fingerprint}")
    return tr("unknown", "无法确定")


def google_connection_line(result: dict[str, Any], *, reconnected: bool = False) -> str:
    account = google_account_display(result)
    count = int(result.get("tasklist_count") or 0)
    if reconnected:
        return tr(
            f"Google reconnected: OK ({account}, {count} task lists found)",
            f"Google 已重新连接：正常（{account}，找到 {count} 个任务列表）",
        )
    return tr(
        f"Google connection: OK ({account}, {count} task lists found)",
        f"Google 连接：正常（{account}，找到 {count} 个任务列表）",
    )


def management_reconnect(config: dict[str, Any], args: argparse.Namespace) -> None:
    snapshot = print_management_summary(config)
    snapshot.setdefault("control_dir", str(control_dir(config)))
    if not all(
        [
            snapshot["config_exists"],
            snapshot["runtime_ready"],
            snapshot["running_from_stable_runtime"],
            snapshot["helpers_ready"],
            snapshot["oauth_client_ready"],
        ]
    ):
        raise ManagementActionError(
            tr(
                "Run this from the installed Local Tasks Bridge (its `ltb` command) after setup is complete.",
                "请在完成设置后，使用已安装的 Local Tasks Bridge（其自带的 `ltb` 命令）执行此操作。",
            )
        )
    if not management_confirm(
        args,
        tr(
            "Back up the private state, hold background sync, and start reconnecting?",
            "要先备份私有状态、暂停后台同步，然后开始重新连接吗？",
        ),
    ):
        print(tr("Cancelled; nothing was changed.", "已取消，没有做任何更改。"))
        return

    backup_dir = backup_management_files(config, "reconnect")
    print(tr(f"Private backup saved: {backup_dir}", f"已保存私有备份：{backup_dir}"))
    was_loaded = stop_management_agent(snapshot)
    state_path = expand_path(config["state_path"])
    state_existed = state_path.is_file()
    state_archived = False
    completed = False

    try:
        online = check_google_connection(config)
        if online["state"] == "ok":
            print(google_connection_line(online))
        elif online["state"] == "auth_required":
            print(tr("Google sign-in is required. Opening the browser.", "需要登录 Google，正在打开浏览器。"))
            authorize_google_for_management(config, args)
            online = check_google_connection(config)
            if online["state"] != "ok":
                raise ManagementActionError(
                    tr(
                        f"Google still could not be verified after signing in: {online['message']}",
                        f"重新登录后仍无法确认 Google 连接：{online['message']}",
                    )
                )
            print(google_connection_line(online, reconnected=True))
        else:
            raise ManagementActionError(
                tr(
                    f"The network or Google is temporarily unavailable; try again later: {online['message']}",
                    f"网络或 Google 暂时不可用，请稍后再试：{online['message']}",
                )
            )

        print("\n" + tr(
            "Running a safe dry-run with deletion and completion propagation turned off.",
            "正在进行安全试运行（已关闭删除与完成的传播）。",
        ))
        try:
            run_management_safe_sync(config, dry_run=True)
        except AccountBindingRequired:
            if not online.get("account_email"):
                print(tr(
                    "The current Google sign-in cannot identify the account safely.",
                    "当前的 Google 登录无法安全地识别账号。",
                ))
                print(tr("Signing in once more, including account identity.", "将重新登录一次，并包含账号身份信息。"))
                authorize_google_for_management(config, args)
                online = check_google_connection(config)
                if online["state"] != "ok" or not online.get("account_email"):
                    raise ManagementActionError(
                        tr(
                            "The Google account could not be identified; the rebuild was stopped.",
                            "无法识别 Google 账号，已停止重建。",
                        )
                    )
            account_titles = reminders_account_titles(config)
            print("\n" + tr(
                "Google sign-in works, but the accounts differ from the ones the sync map belongs to.",
                "Google 登录正常，但当前账号与同步对应关系所属的账号不一致。",
            ))
            accounts = ", ".join(account_titles) if account_titles else tr("unknown", "无法确定")
            print(tr(f"Apple Reminders accounts now: {accounts}", f"当前 Apple 提醒事项账号：{accounts}"))
            print(tr(f"Google account now: {google_account_display(online)}", f"当前 Google 账号：{google_account_display(online)}"))
            print(tr("The previous state is already preserved in the private backup.", "之前的状态已保存在私有备份中。"))
            if not management_confirm(
                args,
                tr(
                    "If these are the accounts you intend to pair, rebuild the sync map safely?",
                    "如果这就是你想要配对的账号组合，要安全地重建同步对应关系吗？",
                ),
            ):
                raise ManagementActionError(
                    tr(
                        "Account confirmation was cancelled; background sync stays on hold.",
                        "已取消账号确认，后台同步保持暂停。",
                    )
                )
            state_archived = archive_state_for_rebuild(config, backup_dir)
            print(tr(
                "Moved the active state into the backup. No Google or Apple items were deleted.",
                "已把当前状态移入备份。没有删除任何 Google 或 Apple 条目。",
            ))
            run_management_safe_sync(config, dry_run=True)

        needs_live_rebuild = state_archived or not state_existed
        if needs_live_rebuild:
            print("\n" + tr(
                "The dry-run above is a rebuild plan with deletion and completion propagation blocked.",
                "上面的试运行是一份已禁止删除和完成传播的重建计划。",
            ))
            if not management_confirm(args, tr("Save a new sync map from this plan?", "要按这份计划保存新的同步对应关系吗？")):
                raise ManagementActionError(
                    tr(
                        "Saving the new sync map was cancelled; background sync stays on hold.",
                        "已取消保存新的同步对应关系，后台同步保持暂停。",
                    )
                )
            run_management_safe_sync(config, dry_run=False)

        start_management_agent(snapshot)
        completed = True
        print("\n" + tr(
            "Done: Google and a safe sync were verified, and background sync resumed.",
            "完成：已确认 Google 连接与安全同步，后台同步已恢复。",
        ))
        print_management_summary(config)
    finally:
        if not completed and was_loaded and not state_archived:
            try:
                start_management_agent(snapshot)
                print(tr(
                    "The active state was not changed and background sync resumed.",
                    "当前状态没有改变，后台同步已恢复。",
                ))
            except ManagementActionError:
                print(tr("Warning: background sync could not be resumed automatically.", "注意：无法自动恢复后台同步。"))


def management_restart(config: dict[str, Any], args: argparse.Namespace) -> None:
    snapshot = print_management_summary(config)
    if not snapshot["running_from_stable_runtime"]:
        raise ManagementActionError(
            tr(
                "Restart from the installed Local Tasks Bridge (its `ltb` command).",
                "请使用已安装的 Local Tasks Bridge（其自带的 `ltb` 命令）重新启动。",
            )
        )
    condition = management_condition(snapshot)[0]
    if condition in {"account_binding_required", "auth_required"}:
        raise ManagementActionError(
            tr(
                "Restarting will not help until the cause is fixed. Run \"Reconnect Google\" first.",
                "在解决根本原因之前重启没有帮助。请先运行“重新连接 Google”。",
            )
        )
    if not management_confirm(args, tr("Restart background sync?", "要重新启动后台同步吗？")):
        print(tr("Cancelled; nothing was changed.", "已取消，没有做任何更改。"))
        return
    flag = pause_flag_path(config)
    with contextlib.suppress(FileNotFoundError):
        flag.unlink()
    if snapshot["launch_agent_installed"] and launchctl_available():
        result = subprocess.run(
            ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LAUNCH_AGENT_LABEL}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
        if result.returncode != 0:
            raise ManagementActionError(tr("Could not restart background sync.", "无法重新启动后台同步。"))
        print(tr("Background sync restarted.", "后台同步已重新启动。"))
        return
    touch_private_file(sync_now_path(config))
    if background_loop_running(config):
        print(tr("Background sync resumed.", "后台同步已恢复。"))
    else:
        print(tr(
            "Background sync is not running here. Open Local Tasks Bridge to start it.",
            "这里没有运行后台同步。请打开 Local Tasks Bridge 来启动它。",
        ))


def preview_mutation_plan(config: dict[str, Any]) -> dict[str, Any] | None:
    """Compute the next sync's complete plan without writing anything."""
    preview_config = dict(config)
    preview_config["_mutation_plan_preview"] = True
    preview_config["_mutation_plan_approval"] = ""
    preview_config["_mutation_plan_destructive_approval"] = ""
    preview_config["auto_reauth_browser"] = False
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            run_sync(preview_config, dry_run=True)
    except MutationPlanPreview as preview:
        return preview.plan
    return None


def run_management_sync(config: dict[str, Any], *, destructive_approval: str) -> None:
    """One live sync from the manager, recorded like a scheduler cycle. Hold the lock."""
    live_config = dict(config)
    live_config["_mutation_plan_approval"] = ""
    live_config["_mutation_plan_destructive_approval"] = destructive_approval
    live_config["auto_reauth_browser"] = False
    write_sync_status(
        live_config,
        {"state": "running", "last_start_at": utc_now_text(), "last_error": "", "mutation_plan": None},
    )
    try:
        run_sync(live_config, dry_run=False)
    except MutationPlanApprovalRequired:
        # enforce_mutation_plan has already recorded the blocked plan.
        raise
    except AccountBindingRequired as exc:
        write_sync_status(
            live_config,
            {"state": "account_binding_required", "last_end_at": utc_now_text(), "last_error": str(exc)},
        )
        raise
    except AuthenticationRequired as exc:
        write_sync_status(
            live_config,
            {"state": "auth_required", "last_end_at": utc_now_text(), "last_error": str(exc)},
        )
        raise
    except (Exception, SystemExit) as exc:
        write_sync_status(
            live_config,
            {"state": "failed", "last_end_at": utc_now_text(), "last_error": str(exc)},
        )
        raise
    write_sync_status(
        live_config,
        {
            "state": "ok",
            "last_end_at": utc_now_text(),
            "last_success_at": utc_now_text(),
            **auto_reauth_failure_epoch_reset_updates(),
            "last_error": "",
            "mutation_plan": None,
            "consecutive_failures": 0,
            MUTATION_APPROVAL_STATUS_KEY: None,
        },
    )


def management_approve(config: dict[str, Any], args: argparse.Namespace) -> None:
    """Review a blocked bulk change in Terminal, then apply it or hold it."""
    snapshot = print_management_summary(config)
    snapshot.setdefault("control_dir", str(control_dir(config)))
    if not snapshot["running_from_stable_runtime"]:
        raise ManagementActionError(
            tr(
                "Apply large changes from the installed Local Tasks Bridge (its `ltb` command).",
                "请使用已安装的 Local Tasks Bridge（其自带的 `ltb` 命令）来执行大批量更改。",
            )
        )
    condition = management_condition(snapshot)[0]
    if condition == "setup_required":
        raise ManagementActionError(
            tr("Finish the setup assistant first.", "请先完成设置向导。")
        )
    if condition in {"account_binding_required", "auth_required"}:
        raise ManagementActionError(
            tr("Fix the Google connection first with \"Reconnect Google\".", "请先用“重新连接 Google”修复 Google 连接。")
        )

    print("\n" + tr(
        "Holding background sync and computing the next plan. Nothing is changed yet.",
        "正在暂停后台同步并计算下一轮计划。此时还不会做任何更改。",
    ))
    was_loaded = stop_management_agent(snapshot)
    try:
        with sync_lock(config, wait=True) as acquired:
            if not acquired:
                raise ManagementActionError(
                    tr("Another sync is running. Try again in a moment.", "另一轮同步正在进行，请稍后再试。")
                )
            plan = preview_mutation_plan(config)
            if plan is None or not mutation_plan_limit_reasons(config, plan):
                print("\n" + tr(
                    "No large change needs approval. Background sync handles everything as usual.",
                    "没有需要确认的大批量更改，后台同步会照常处理。",
                ))
                return
            review = mutation_plan_review(plan)
            print_mutation_review(review)
            if not management_confirm(
                args,
                "\n" + tr(
                    "Apply exactly these changes to Apple Reminders and Google Tasks?",
                    "要把上面这些更改原样应用到 Apple 提醒事项和 Google Tasks 吗？",
                ),
            ):
                write_sync_status(
                    config,
                    {
                        MUTATION_APPROVAL_STATUS_KEY: mutation_approval_memory(
                            review["destructive_fingerprint"],
                            "hold",
                            now=utc_now(),
                            prompted=True,
                        )
                    },
                )
                repeat = duration_text(int(config["mutation_approval_prompt_repeat_seconds"]))
                print(tr(
                    f"Not applied. Only these deletions/completions are held; everything else keeps syncing. "
                    f"You will be asked again in {repeat}.",
                    f"未执行。只暂缓这些删除/完成，其余改动继续同步。{repeat}后会再次询问。",
                ))
                return
            backup_dir = backup_management_files(config, "approve")
            print(tr(f"Private backup saved: {backup_dir}", f"已保存私有备份：{backup_dir}"))
            token = mutation_plan_approval_token({"fingerprint": review["destructive_fingerprint"]})
            try:
                run_management_sync(config, destructive_approval=token)
            except MutationPlanApprovalRequired as exc:
                raise ManagementActionError(
                    tr(
                        "The plan changed while you were reviewing it, so nothing was applied. Run this again to see the new plan.",
                        "在你确认期间计划发生了变化，因此没有执行。请重新运行以查看新的计划。",
                    )
                ) from exc
            print("\n" + tr("Applied the reviewed changes.", "已应用你确认过的更改。"))
    finally:
        if was_loaded:
            try:
                start_management_agent(snapshot)
                print(tr("Background sync resumed.", "后台同步已恢复。"))
            except ManagementActionError:
                print(tr(
                    "Warning: background sync could not be resumed. Choose \"Restart background sync\".",
                    "注意：无法恢复后台同步。请选择“重新启动后台同步”。",
                ))
        elif snapshot.get("agent_loaded") is False:
            print(tr(
                "Background sync is not running. Open Local Tasks Bridge to start it.",
                "后台同步没有在运行。请打开 Local Tasks Bridge 来启动它。",
            ))


def management_online_check(config: dict[str, Any]) -> bool:
    print_management_summary(config)
    print("\n" + tr("Refreshing the Google token and checking the Tasks API.", "正在刷新 Google 令牌并检查 Tasks API。"))
    result = check_google_connection(config)
    if result["state"] == "ok":
        print(google_connection_line(result))
        return True
    print(tr(f"Google connection: needs attention ({result['message']})", f"Google 连接：需要处理（{result['message']}）"))
    return False


def run_management_action(config: dict[str, Any], args: argparse.Namespace, action: str) -> bool:
    if action == "status":
        print_management_summary(config)
        return True
    if action == "check":
        return management_online_check(config)
    if action == "reconnect":
        management_reconnect(config, args)
        return True
    if action == "restart":
        management_restart(config, args)
        return True
    if action == "approve":
        management_approve(config, args)
        return True
    raise ManagementActionError(tr(f"Unsupported action: {action}", f"不支持的操作：{action}"))


def cmd_manage(args: argparse.Namespace) -> None:
    try:
        config = load_config(args)
    except (OSError, json.JSONDecodeError, SystemExit, TypeError, ValueError) as exc:
        raise SystemExit(
            tr(
                "The private settings cannot be read. Open Local Tasks Bridge to repair the setup.",
                "无法读取私有设置。请打开 Local Tasks Bridge 修复设置。",
            )
        ) from exc
    apply_network_config(config)

    action = str(getattr(args, "action", "menu") or "menu")
    stopped = tr("Stopped", "已中止")
    if action != "menu":
        try:
            ok = run_management_action(config, args, action)
        except (
            ManagementActionError,
            AccountBindingRequired,
            AuthenticationRequired,
            MutationPlanApprovalRequired,
        ) as exc:
            raise SystemExit(f"{stopped}: {exc}") from exc
        if not ok:
            raise SystemExit(1)
        return

    while True:
        print_management_summary(config)
        print("\n1. " + tr("Show status (read-only)", "查看状态（只读）"))
        print("2. " + tr("Check Google connection (may refresh the token)", "检查 Google 连接（可能刷新令牌）"))
        print("3. " + tr("Reconnect Google safely", "安全地重新连接 Google"))
        print("4. " + tr("Restart background sync", "重新启动后台同步"))
        print("5. " + tr("Review and apply large changes", "查看并执行大批量更改"))
        print("0. " + tr("Quit", "退出"))
        try:
            choice = input(tr("Choose: ", "请选择：")).strip()
        except EOFError:
            choice = "0"
        action_by_choice = {"1": "status", "2": "check", "3": "reconnect", "4": "restart", "5": "approve"}
        if choice == "0":
            print(tr("Bye.", "已退出管理工具。"))
            return
        selected = action_by_choice.get(choice)
        if not selected:
            print(tr("Choose a number from 0 to 5.", "请输入 0 到 5 之间的数字。"))
            continue
        try:
            run_management_action(config, args, selected)
        except (ManagementActionError, AccountBindingRequired, AuthenticationRequired) as exc:
            print(f"\n{stopped}: {exc}")
        except SystemExit as exc:
            print(f"\n{stopped}: {exc}")
        input("\n" + tr("Press Enter to return to the menu.", "按回车键返回菜单。"))


def inspect_tasklists_for_desired(
    client: GoogleTasksClient,
    desired_by_list: dict[str, dict[str, tuple[dict[str, Any], str, dict[str, Any]]]],
    config: dict[str, Any],
) -> tuple[dict[str, str], list[str]]:
    if not config["tasks_mirror_lists"]:
        tasklist_id = client.resolve_tasklist_id()
        title = str(config.get("tasks_list_title") or "Google Tasks")
        return ({list_title: tasklist_id for list_title in desired_by_list} or {title: tasklist_id}, [])

    existing_lists = client.list_tasklists()
    by_title: dict[str, str] = {}
    for tasklist in existing_lists:
        title = str(tasklist.get("title") or "")
        if title and title not in by_title:
            by_title[title] = str(tasklist["id"])

    resolved: dict[str, str] = {}
    missing: list[str] = []
    for list_title in sorted(desired_by_list):
        if list_title in by_title:
            resolved[list_title] = by_title[list_title]
            continue

        if not list_allows_apple_to_google(config, list_title):
            continue

        if not config["tasks_create_missing_lists"]:
            raise SystemExit(
                "A selected Reminders list has no Google Tasks list and creating lists is turned off.\n"
                f"List: {list_title}"
            )
        missing.append(list_title)
        resolved[list_title] = f"planned:{sha256_text(list_title, 24)}"

    return resolved, missing


def materialize_missing_tasklists(
    client: GoogleTasksClient,
    tasklists: dict[str, str],
    missing: list[str],
    *,
    dry_run: bool,
) -> dict[str, str]:
    resolved = dict(tasklists)
    for list_title in missing:
        if dry_run:
            print(f"DRY-RUN create Google Tasks list: {list_title}")
            continue
        tasklist = client.insert_tasklist(list_title)
        resolved[list_title] = str(tasklist["id"])
        print(f"Created Google Tasks list: {list_title}")
    return resolved


def list_task_snapshot(client: GoogleTasksClient, tasklist_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tasks = client.list_tasks(tasklist_id, show_deleted=True)
    active_tasks = [task for task in tasks if not task.get("deleted")]
    deleted_tasks = [task for task in tasks if task.get("deleted")]
    return active_tasks, deleted_tasks


def get_active_task_by_id(client: GoogleTasksClient, tasklist_id: str, task_id: str) -> dict[str, Any] | None:
    try:
        task = client.get_task(tasklist_id, task_id)
    except GoogleApiError as exc:
        if exc.status not in (404, 410):
            raise
        return None
    return None if task.get("deleted") else task


def google_tasks_title_due_consistency_issues(
    client: GoogleTasksClient,
    desired_by_list: dict[str, dict[str, tuple[dict[str, Any], str, dict[str, Any]]]],
    tasklists: dict[str, str],
    blocked: set[tuple[str, str]],
    recently_synced_task_ids: dict[tuple[str, str], str],
) -> tuple[list[str], int]:
    issues: list[str] = []
    verified = 0

    for list_title, desired in desired_by_list.items():
        tasklist_id = tasklists[list_title]
        if tasklist_id.startswith("dry-run:"):
            continue
        tasks, _deleted_tasks = list_task_snapshot(client, tasklist_id)
        existing_by_uid, _duplicates = index_existing_tasks(tasks)

        for uid, (body, _digest, _reminder) in desired.items():
            if (list_title, uid) in blocked:
                continue

            task = existing_by_uid.get(uid)
            expected = task_title_due_material(body)
            task_id = recently_synced_task_ids.get((tasklist_id, uid))
            if not task and task_id:
                task = get_active_task_by_id(client, tasklist_id, task_id)
            if not task:
                issues.append(f"[{list_title}] missing Google task for {expected['title']}")
                continue

            actual = task_title_due_material(task)
            if actual != expected and task_id:
                refreshed = get_active_task_by_id(client, tasklist_id, task_id)
                if refreshed:
                    task = refreshed
                    actual = task_title_due_material(task)
            if actual != expected:
                issues.append(
                    f"[{list_title}] {expected['title']}: "
                    f"title/due mismatch expected={expected} actual={actual}"
                )
                continue

            verified += 1

    return issues, verified


def verify_google_tasks_title_due_consistency(
    client: GoogleTasksClient,
    desired_by_list: dict[str, dict[str, tuple[dict[str, Any], str, dict[str, Any]]]],
    tasklists: dict[str, str],
    blocked: set[tuple[str, str]],
    recently_synced_task_ids: dict[tuple[str, str], str] | None = None,
    retry_attempts: int = 1,
    retry_delay_seconds: float = 0.0,
) -> int:
    attempts = max(1, retry_attempts)
    delay_seconds = max(0.0, retry_delay_seconds)
    task_ids = recently_synced_task_ids or {}
    issues: list[str] = []
    verified = 0

    for attempt in range(1, attempts + 1):
        issues, verified = google_tasks_title_due_consistency_issues(
            client,
            desired_by_list,
            tasklists,
            blocked,
            task_ids,
        )
        if not issues:
            print(f"Google Tasks title/due consistency verified: {verified}")
            return verified
        if attempt < attempts and delay_seconds:
            time.sleep(delay_seconds)

    if issues:
        shown = "\n".join(f"- {issue}" for issue in issues[:10])
        remaining = len(issues) - 10
        suffix = f"\n... and {remaining} more" if remaining > 0 else ""
        raise SystemExit(f"Google Tasks title/due consistency check failed:\n{shown}{suffix}")

    return verified


def plan_google_task_outbound_mutations(
    config: dict[str, Any],
    desired_by_list: dict[str, dict[str, tuple[dict[str, Any], str, dict[str, Any]]]],
    tasklists: dict[str, str],
    existing_by_list: dict[str, dict[str, dict[str, Any]]],
    existing_fallback_by_list: dict[str, dict[str, dict[str, Any]]],
    existing_title_by_list: dict[str, dict[str, dict[str, Any]]],
    existing_id_by_list: dict[str, dict[str, dict[str, Any]]],
    duplicates_by_list: dict[str, list[dict[str, Any]]],
    state: dict[str, Any],
    blocked: set[tuple[str, str]],
    completed_by_list: dict[str, dict[str, tuple[dict[str, Any], str, dict[str, Any]]]],
    *,
    allow_deletes: bool,
    allow_completions: bool | None = None,
    deleted_tasks_by_list: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    if allow_completions is None:
        allow_completions = allow_deletes
    deleted_ids_by_list = deleted_task_ids_by_list(deleted_tasks_by_list or {})
    actions: list[dict[str, Any]] = []
    desired_keys: set[tuple[str, str]] = set()
    claimed_task_ids: set[tuple[str, str]] = set()

    for list_title, desired in desired_by_list.items():
        if not list_allows_apple_to_google(config, list_title):
            continue
        tasklist_id = tasklists.get(list_title)
        if not tasklist_id:
            continue
        existing_by_uid = existing_by_list.get(list_title, {})
        existing_by_fingerprint = existing_fallback_by_list.get(list_title, {})
        existing_by_title = existing_title_by_list.get(list_title, {})
        existing_by_id = existing_id_by_list.get(list_title, {})
        for uid, (body, digest, reminder) in desired.items():
            desired_keys.add((tasklist_id, uid))
            if (list_title, uid) in blocked:
                continue

            existing = existing_by_uid.get(uid)
            matched_old_uid = None
            if not existing:
                fallback = existing_by_fingerprint.get(task_fingerprint(body))
                if fallback and can_reuse_task_fallback(fallback, uid, desired, tasklist_id, claimed_task_ids):
                    existing = fallback
                    matched_old_uid = task_source_uid(existing)
            if not existing:
                fallback = existing_by_title.get(task_title_fingerprint(body))
                if fallback and can_reuse_task_fallback(fallback, uid, desired, tasklist_id, claimed_task_ids):
                    existing = fallback
                    matched_old_uid = task_source_uid(existing)

            record = task_state_record(state, tasklist_id, uid)
            if not record and matched_old_uid:
                record = task_state_record(state, tasklist_id, matched_old_uid)
            if record and not can_use_task_state_record(
                record,
                uid,
                desired,
                tasklist_id,
                existing_by_id,
                claimed_task_ids,
            ):
                record = None
            task_id = existing.get("id") if existing else record.get("task_id") if record else None
            if task_id and not existing and str(task_id) in deleted_ids_by_list.get(list_title, set()):
                # The tracked Google task is a deletion tombstone, yet the
                # reminder still syncs (its edit is newer than the deletion,
                # or deletions are not propagated): recreate the task rather
                # than writing to the tombstone, which stays deleted.
                task_id = None
            existing_metadata = parse_tasks_sync_metadata(str(existing.get("notes") or "")) if existing else {}
            existing_digest = existing_metadata.get("source digest") if existing else record.get("digest") if record else None
            existing_matches_desired = bool(existing and task_matches_desired(existing, body, reminder, config))
            needs_update = bool(
                task_id
                and (
                    existing_digest != digest
                    or not existing_matches_desired
                    or bool(matched_old_uid and matched_old_uid != uid)
                    or (existing and existing.get("status") == "completed")
                )
            )
            if task_id:
                claimed_task_ids.add((tasklist_id, str(task_id)))
            if needs_update:
                actions.append(planned_mutation("google_tasks", "update", [list_title, tasklist_id, uid, task_id]))
            elif not task_id:
                actions.append(planned_mutation("google_tasks", "create", [list_title, tasklist_id, uid]))

    if allow_deletes or allow_completions:
        stale: dict[tuple[str, str], dict[str, Any]] = {}
        for key, record in list(state.setdefault("tasks", {}).items()):
            if not isinstance(record, dict):
                continue
            tasklist_id = str(record.get("tasklist_id") or "")
            list_title = str(record.get("tasklist_title") or "")
            uid = key.split(":", 1)[1] if ":" in key else ""
            task_id = str(record.get("task_id") or "")
            if not record_list_in_scope(desired_by_list, tasklists, list_title, tasklist_id):
                continue
            if not list_allows_apple_to_google(config, list_title):
                continue
            if not list_allows_delete_propagation(
                config,
                list_title,
                safety_allows_deletes=allow_deletes or allow_completions,
            ):
                continue
            if (tasklist_id, task_id) in claimed_task_ids:
                continue
            if (list_title, uid) in blocked:
                continue
            if tasklist_id and uid and (tasklist_id, uid) not in desired_keys and task_id:
                stale[(tasklist_id, uid)] = {
                    "task_id": task_id,
                    "list_title": list_title,
                    "task": None,
                    "record": record,
                }

        for list_title, tasklist_id in tasklists.items():
            if not list_allows_apple_to_google(config, list_title):
                continue
            if not list_allows_delete_propagation(
                config,
                list_title,
                safety_allows_deletes=allow_deletes or allow_completions,
            ):
                continue
            for uid, task in existing_by_list.get(list_title, {}).items():
                record = task_state_record(state, tasklist_id, uid)
                if str(task.get("status") or "") == "completed" and not record:
                    continue
                if (tasklist_id, str(task.get("id") or "")) in claimed_task_ids:
                    continue
                if (list_title, uid) in blocked:
                    continue
                if (tasklist_id, uid) not in desired_keys and task.get("id"):
                    stale[(tasklist_id, uid)] = {
                        "task_id": str(task["id"]),
                        "list_title": list_title,
                        "task": task,
                        "record": record,
                    }

        for (tasklist_id, uid), candidate in stale.items():
            task_id = str(candidate["task_id"])
            list_title = str(candidate.get("list_title") or "")
            task = candidate.get("task") if isinstance(candidate.get("task"), dict) else None
            record = candidate.get("record") if isinstance(candidate.get("record"), dict) else None
            review_title = str((task or {}).get("title") or (record or {}).get("title") or "")
            completed_item = completed_by_list.get(list_title, {}).get(uid)
            if allow_completions and config["tasks_complete_stale"] and completed_item:
                _body, digest, _reminder = completed_item
                already_recorded = bool(
                    record
                    and record.get("apple_completed")
                    and record.get("digest") == digest
                    and task
                    and str(task.get("status") or "") == "completed"
                )
                already_completed = bool(task and str(task.get("status") or "") == "completed")
                if not already_recorded and not already_completed:
                    actions.append(
                        planned_mutation(
                            "google_tasks",
                            "complete",
                            [list_title, tasklist_id, uid, task_id],
                            destructive=True,
                            list_title=list_title,
                            title=review_title,
                        )
                    )
                continue
            if not allow_deletes:
                continue
            actions.append(
                planned_mutation(
                    "google_tasks",
                    "delete",
                    [list_title, tasklist_id, uid, task_id],
                    destructive=True,
                    list_title=list_title,
                    title=review_title,
                )
            )

        for list_title, duplicates in duplicates_by_list.items():
            if not list_allows_apple_to_google(config, list_title):
                continue
            if not list_allows_delete_propagation(
                config,
                list_title,
                safety_allows_deletes=allow_deletes,
            ):
                continue
            tasklist_id = tasklists.get(list_title)
            if not tasklist_id:
                continue
            for task in duplicates:
                task_id = str(task.get("id") or "")
                if task_id:
                    actions.append(
                        planned_mutation(
                            "google_tasks",
                            "dedupe_delete",
                            [list_title, tasklist_id, task_id],
                            destructive=True,
                            list_title=list_title,
                            title=str(task.get("title") or ""),
                        )
                    )

    return actions


def deleted_task_ids_by_list(deleted_tasks_by_list: dict[str, list[dict[str, Any]]]) -> dict[str, set[str]]:
    return {
        list_title: {str(task.get("id")) for task in tasks if task.get("id")}
        for list_title, tasks in deleted_tasks_by_list.items()
    }


def record_list_in_scope(
    desired_by_list: dict[str, Any],
    tasklists: dict[str, str],
    list_title: str,
    tasklist_id: str,
) -> bool:
    """Whether a tracked task still belongs to a list this sync manages.

    A list that is no longer selected, was renamed or removed on either side,
    or now maps to a different Google list is out of scope: its tasks are left
    alone instead of being read as deletions.
    """

    return list_title in desired_by_list and bool(tasklist_id) and tasklists.get(list_title) == tasklist_id


def managed_google_task_population(
    tasklists: dict[str, str],
    tasks_by_list: dict[str, list[dict[str, Any]]],
    state: dict[str, Any],
) -> int:
    active_managed = sum(
        1
        for tasks in tasks_by_list.values()
        for task in tasks
        if parse_tasks_sync_metadata(str(task.get("notes") or "")).get(SYNC_MARKER_KEY) == SYNC_MARKER_VALUE
    )
    tasklist_ids = set(tasklists.values())
    state_managed = sum(
        1
        for record in state.setdefault("tasks", {}).values()
        if isinstance(record, dict) and str(record.get("tasklist_id") or "") in tasklist_ids
    )
    return max(active_managed, state_managed)


def plan_google_calendar_outbound_mutations(
    config: dict[str, Any],
    calendar_id: str,
    desired: dict[str, tuple[dict[str, Any], str, dict[str, Any]]],
    existing_by_uid: dict[str, dict[str, Any]],
    duplicates: list[dict[str, Any]],
    state: dict[str, Any],
    blocked_uids: set[str],
    *,
    allow_deletes: bool,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for uid, (_body, digest, _reminder) in desired.items():
        if uid in blocked_uids:
            continue
        existing = existing_by_uid.get(uid)
        record = state_record(state, calendar_id, uid)
        event_id = existing.get("id") if existing else record.get("event_id") if record else None
        existing_digest = private_props(existing).get(DIGEST_KEY) if existing else record.get("digest") if record else None
        if event_id and existing_digest != digest:
            actions.append(planned_mutation("google_calendar", "update", [calendar_id, uid, event_id]))
        elif not event_id:
            actions.append(planned_mutation("google_calendar", "create", [calendar_id, uid]))

    if allow_deletes:
        desired_uids = set(desired)
        stale: dict[str, str] = {}
        for key, record in list(state["events"].items()):
            if not isinstance(record, dict) or record.get("calendar_id") != calendar_id:
                continue
            uid = key.split(":", 1)[1] if ":" in key else ""
            if uid and uid not in desired_uids and record.get("event_id"):
                stale[uid] = str(record["event_id"])
        for uid, event in existing_by_uid.items():
            if uid not in desired_uids and event.get("id"):
                stale[uid] = str(event["id"])
        for uid, event_id in stale.items():
            record = state_record(state, calendar_id, uid) or {}
            actions.append(
                planned_mutation(
                    "google_calendar",
                    "delete",
                    [calendar_id, uid, event_id],
                    destructive=True,
                    title=str((existing_by_uid.get(uid) or {}).get("summary") or record.get("title") or ""),
                )
            )
        for event in duplicates:
            event_id = str(event.get("id") or "")
            if event_id:
                actions.append(
                    planned_mutation(
                        "google_calendar",
                        "dedupe_delete",
                        [calendar_id, event_id],
                        destructive=True,
                        title=str(event.get("summary") or ""),
                    )
                )
    return actions


def managed_google_calendar_population(
    calendar_id: str,
    existing_by_uid: dict[str, dict[str, Any]],
    state: dict[str, Any],
) -> int:
    state_managed = sum(
        1
        for record in state["events"].values()
        if isinstance(record, dict) and record.get("calendar_id") == calendar_id
    )
    return max(len(existing_by_uid), state_managed)


def run_tasks_sync(config: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    reminders, desired_by_list, skipped_invalid = build_desired_tasks(config)

    print(f"Apple Reminders exported: {len(reminders)}")
    print(f"Google Tasks lists desired: {len(desired_by_list)}")
    print(f"Google Tasks desired: {sum(len(items) for items in desired_by_list.values())}")

    state_path = expand_path(config["state_path"])
    state = load_state(state_path)
    account_binding = resolve_sync_account_binding(config, reminders)
    bind_or_validate_sync_state_accounts(state, account_binding)
    expect_google_binding(config, account_binding)
    client = GoogleTasksClient(config)
    tasklists, missing_tasklists = inspect_tasklists_for_desired(client, desired_by_list, config)
    tasks_by_list: dict[str, list[dict[str, Any]]] = {}
    deleted_tasks_by_list: dict[str, list[dict[str, Any]]] = {}
    existing_by_list: dict[str, dict[str, dict[str, Any]]] = {}
    existing_fallback_by_list: dict[str, dict[str, dict[str, Any]]] = {}
    existing_title_by_list: dict[str, dict[str, dict[str, Any]]] = {}
    existing_id_by_list: dict[str, dict[str, dict[str, Any]]] = {}
    duplicates_by_list: dict[str, list[dict[str, Any]]] = {}

    for list_title, tasklist_id in tasklists.items():
        if tasklist_id.startswith("planned:"):
            tasks: list[dict[str, Any]] = []
            deleted_tasks: list[dict[str, Any]] = []
        else:
            tasks, deleted_tasks = list_task_snapshot(client, tasklist_id)
        tasks_by_list[list_title] = tasks
        deleted_tasks_by_list[list_title] = deleted_tasks
        existing_by_uid, duplicates = index_existing_tasks(tasks)
        existing_by_list[list_title] = existing_by_uid
        existing_fallback_by_list[list_title] = index_synced_tasks_by_fingerprint(tasks)
        existing_title_by_list[list_title] = index_synced_tasks_by_title(tasks)
        existing_id_by_list[list_title] = {str(task["id"]): task for task in tasks if task.get("id")}
        duplicates_by_list[list_title] = duplicates

    source_count = sum(len(items) for items in desired_by_list.values())
    policy_list_titles = set(desired_by_list) | set(tasklists) | set(config.get("list_policies") or {})
    policy_list_titles.update(
        str(record.get("tasklist_title") or "")
        for record in state.setdefault("tasks", {}).values()
        if isinstance(record, dict)
    )
    delete_requested = any(
        list_allows_delete_propagation(config, list_title)
        for list_title in policy_list_titles
    )
    skip_stale = bool(delete_requested and not config["allow_empty_source_delete"] and source_count == 0)
    allow_deletes = bool(delete_requested and not skip_stale)
    # An explicit completed reminder is positive evidence even when no active
    # reminders remain. Missing items and duplicates still need deletion safety.
    allow_completions = bool(delete_requested and config["tasks_complete_stale"])
    completed_by_list: dict[str, dict[str, tuple[dict[str, Any], str, dict[str, Any]]]] = {}
    if allow_completions:
        _completed_reminders, completed_by_list, completed_skipped = build_completed_tasks(config)
        skipped_invalid += completed_skipped

    bidirectional_plan = plan_google_task_changes_to_reminders(
        config,
        desired_by_list,
        tasklists,
        existing_by_list,
        tasks_by_list,
        deleted_tasks_by_list,
        state,
        allow_deletes=allow_deletes,
    )
    preflight_blocked = set(bidirectional_plan["blocked"]) | set(bidirectional_plan["source_controlled"])
    planned_actions = [
        planned_mutation("google_tasks", "create_list", list_title)
        for list_title in missing_tasklists
    ]
    planned_actions.extend(bidirectional_plan["actions"])
    planned_actions.extend(
        plan_google_task_outbound_mutations(
            config,
            desired_by_list,
            tasklists,
            existing_by_list,
            existing_fallback_by_list,
            existing_title_by_list,
            existing_id_by_list,
            duplicates_by_list,
            state,
            preflight_blocked,
            completed_by_list,
            allow_deletes=allow_deletes,
            allow_completions=allow_completions,
            deleted_tasks_by_list=deleted_tasks_by_list,
        )
    )
    population = max(source_count, managed_google_task_population(tasklists, tasks_by_list, state))
    mutation_plan = build_mutation_plan(planned_actions, population)
    enforce_mutation_plan(config, mutation_plan, dry_run=dry_run)

    tasklists = materialize_missing_tasklists(
        client,
        tasklists,
        missing_tasklists,
        dry_run=dry_run,
    )

    google_applied, bidir_initialized, bidir_conflicts, blocked = apply_google_task_changes_to_reminders(
        config,
        client,
        desired_by_list,
        tasklists,
        existing_by_list,
        tasks_by_list,
        deleted_tasks_by_list,
        state,
        dry_run,
        planned=bidirectional_plan,
        allow_deletes=allow_deletes,
    )
    if google_applied and not dry_run:
        time.sleep(1)
        reminders, desired_by_list, skipped_invalid = build_desired_tasks(config)
        # Inbound completions move reminders out of the active snapshot. Refresh
        # the completed snapshot too, or stale cleanup can misread them as deleted.
        if allow_completions:
            _completed_reminders, completed_by_list, completed_skipped = build_completed_tasks(config)
            skipped_invalid += completed_skipped
        print(f"Apple Reminders re-exported after Google Tasks changes: {len(reminders)}")
        print(f"Google Tasks desired: {sum(len(items) for items in desired_by_list.values())}")
        tasks_by_list = {}
        deleted_tasks_by_list = {}
        existing_by_list = {}
        existing_fallback_by_list = {}
        existing_title_by_list = {}
        existing_id_by_list = {}
        duplicates_by_list = {}
        for list_title, tasklist_id in tasklists.items():
            tasks, deleted_tasks = list_task_snapshot(client, tasklist_id)
            tasks_by_list[list_title] = tasks
            deleted_tasks_by_list[list_title] = deleted_tasks
            existing_by_uid, duplicates = index_existing_tasks(tasks)
            existing_by_list[list_title] = existing_by_uid
            existing_fallback_by_list[list_title] = index_synced_tasks_by_fingerprint(tasks)
            existing_title_by_list[list_title] = index_synced_tasks_by_title(tasks)
            existing_id_by_list[list_title] = {str(task["id"]): task for task in tasks if task.get("id")}
            duplicates_by_list[list_title] = duplicates

    inserted = updated = unchanged = completed = deleted = duplicate_deleted = 0
    desired_keys: set[tuple[str, str]] = set()
    claimed_task_ids: set[tuple[str, str]] = set()
    recently_synced_task_ids: dict[tuple[str, str], str] = {}
    deleted_ids_by_list = deleted_task_ids_by_list(deleted_tasks_by_list)

    for list_title, desired in desired_by_list.items():
        if not list_allows_apple_to_google(config, list_title):
            continue
        tasklist_id = tasklists.get(list_title)
        if not tasklist_id:
            continue
        existing_by_uid = existing_by_list.get(list_title, {})
        existing_by_fingerprint = existing_fallback_by_list.get(list_title, {})
        existing_by_title = existing_title_by_list.get(list_title, {})
        existing_by_id = existing_id_by_list.get(list_title, {})
        for uid, (body, digest, reminder) in desired.items():
            desired_keys.add((tasklist_id, uid))
            if (list_title, uid) in blocked:
                continue

            existing = existing_by_uid.get(uid)
            matched_old_uid = None
            if not existing:
                fallback = existing_by_fingerprint.get(task_fingerprint(body))
                if fallback and can_reuse_task_fallback(fallback, uid, desired, tasklist_id, claimed_task_ids):
                    existing = fallback
                    matched_old_uid = task_source_uid(existing)
            if not existing:
                fallback = existing_by_title.get(task_title_fingerprint(body))
                if fallback and can_reuse_task_fallback(fallback, uid, desired, tasklist_id, claimed_task_ids):
                    existing = fallback
                    matched_old_uid = task_source_uid(existing)

            record = task_state_record(state, tasklist_id, uid)
            if not record and matched_old_uid:
                record = task_state_record(state, tasklist_id, matched_old_uid)
            if record and not can_use_task_state_record(
                record,
                uid,
                desired,
                tasklist_id,
                existing_by_id,
                claimed_task_ids,
            ):
                record = None
            task_id = existing.get("id") if existing else record.get("task_id") if record else None
            if task_id and not existing and str(task_id) in deleted_ids_by_list.get(list_title, set()):
                # The tracked Google task is a deletion tombstone, yet the
                # reminder still syncs (its edit is newer than the deletion,
                # or deletions are not propagated): recreate the task rather
                # than writing to the tombstone, which stays deleted.
                task_id = None
            existing_metadata = parse_tasks_sync_metadata(str(existing.get("notes") or "")) if existing else {}
            existing_digest = existing_metadata.get("source digest") if existing else record.get("digest") if record else None
            title = str(body.get("title") or reminder.get("title") or uid)
            existing_matches_desired = bool(existing and task_matches_desired(existing, body, reminder, config))
            needs_update = bool(
                task_id
                and (
                    existing_digest != digest
                    or not existing_matches_desired
                    or bool(matched_old_uid and matched_old_uid != uid)
                    or (existing and existing.get("status") == "completed")
                )
            )

            if dry_run:
                action = "update" if needs_update else "insert" if not task_id else "skip"
                print(f"DRY-RUN {action} task in [{list_title}]: {title}")
                if task_id:
                    claimed_task_ids.add((tasklist_id, str(task_id)))
                continue

            if existing and task_id and not needs_update:
                unchanged += 1
                save_task_state(state, tasklist_id, uid, existing, digest, title, reminder, config, list_title)
                if matched_old_uid and matched_old_uid != uid:
                    remove_task_state_record(state, tasklist_id, matched_old_uid)
                claimed_task_ids.add((tasklist_id, str(task_id)))
                recently_synced_task_ids[(tasklist_id, uid)] = str(task_id)
                continue

            if task_id:
                try:
                    task = client.patch_task(tasklist_id, task_id, task_body_for_patch(body, existing))
                    updated += 1
                except GoogleApiError as exc:
                    if exc.status not in (404, 410):
                        raise
                    task = client.insert_task(tasklist_id, body)
                    inserted += 1
            else:
                task = client.insert_task(tasklist_id, body)
                inserted += 1

            save_task_state(state, tasklist_id, uid, task, digest, title, reminder, config, list_title)
            if matched_old_uid and matched_old_uid != uid:
                remove_task_state_record(state, tasklist_id, matched_old_uid)
            claimed_task_ids.add((tasklist_id, str(task["id"])))
            recently_synced_task_ids[(tasklist_id, uid)] = str(task["id"])

    if skip_stale:
        print("Skipping stale deletion because the active Reminders source exported 0 items; explicit completions may still propagate.")

    if allow_deletes or allow_completions:
        stale: dict[tuple[str, str], dict[str, Any]] = {}
        for key, record in list(state.setdefault("tasks", {}).items()):
            if not isinstance(record, dict):
                continue
            tasklist_id = str(record.get("tasklist_id") or "")
            list_title = str(record.get("tasklist_title") or "")
            uid = key.split(":", 1)[1] if ":" in key else ""
            task_id = str(record.get("task_id") or "")
            if not record_list_in_scope(desired_by_list, tasklists, list_title, tasklist_id):
                continue
            if not list_allows_apple_to_google(config, list_title):
                continue
            if not list_allows_delete_propagation(
                config,
                list_title,
                safety_allows_deletes=allow_deletes or allow_completions,
            ):
                continue
            if (tasklist_id, task_id) in claimed_task_ids:
                continue
            if (list_title, uid) in blocked:
                continue
            if tasklist_id and uid and (tasklist_id, uid) not in desired_keys and record.get("task_id"):
                stale[(tasklist_id, uid)] = {
                    "task_id": str(record["task_id"]),
                    "list_title": list_title,
                    "task": None,
                    "record": record,
                }

        for list_title, tasklist_id in tasklists.items():
            if not list_allows_apple_to_google(config, list_title):
                continue
            if not list_allows_delete_propagation(
                config,
                list_title,
                safety_allows_deletes=allow_deletes or allow_completions,
            ):
                continue
            for uid, task in existing_by_list.get(list_title, {}).items():
                record = task_state_record(state, tasklist_id, uid)
                if str(task.get("status") or "") == "completed" and not record:
                    continue
                if (tasklist_id, str(task.get("id") or "")) in claimed_task_ids:
                    continue
                if (list_title, uid) in blocked:
                    continue
                if (tasklist_id, uid) not in desired_keys and task.get("id"):
                    stale[(tasklist_id, uid)] = {
                        "task_id": str(task["id"]),
                        "list_title": list_title,
                        "task": task,
                        "record": record,
                    }

        for (tasklist_id, uid), candidate in stale.items():
            task_id = str(candidate["task_id"])
            list_title = str(candidate.get("list_title") or "")
            task = candidate.get("task") if isinstance(candidate.get("task"), dict) else None
            record = candidate.get("record") if isinstance(candidate.get("record"), dict) else None
            completed_item = completed_by_list.get(list_title, {}).get(uid)

            if allow_completions and config["tasks_complete_stale"] and completed_item:
                body, digest, reminder = completed_item
                title = str(body.get("title") or reminder.get("title") or uid)
                if dry_run:
                    print(f"DRY-RUN complete stale task from completed Apple Reminder: {title}")
                    continue

                if (
                    record
                    and record.get("apple_completed")
                    and record.get("digest") == digest
                    and task
                    and str(task.get("status") or "") == "completed"
                ):
                    continue

                if task and str(task.get("status") or "") == "completed":
                    patched = task
                else:
                    try:
                        patched = client.complete_task(tasklist_id, task_id)
                        completed += 1
                    except GoogleApiError as exc:
                        if exc.status not in (404, 410):
                            raise
                        remove_task_state_record(state, tasklist_id, uid)
                        continue
                save_task_state(state, tasklist_id, uid, patched, digest, title, reminder, config, list_title)
                continue

            if not allow_deletes:
                continue
            if dry_run:
                print(f"DRY-RUN delete stale task: {uid}")
                continue
            client.delete_task(tasklist_id, task_id)
            deleted += 1
            remove_task_state_record(state, tasklist_id, uid)

    if allow_deletes:
        for list_title, duplicates in duplicates_by_list.items():
            if not list_allows_apple_to_google(config, list_title):
                continue
            if not list_allows_delete_propagation(
                config,
                list_title,
                safety_allows_deletes=allow_deletes,
            ):
                continue
            tasklist_id = tasklists.get(list_title)
            if not tasklist_id:
                continue
            for task in duplicates:
                task_id = task.get("id")
                if not task_id:
                    continue
                if dry_run:
                    print(f"DRY-RUN delete duplicate task in [{list_title}]: {task.get('title', task_id)}")
                    continue
                client.delete_task(tasklist_id, str(task_id))
                duplicate_deleted += 1

    if not dry_run:
        # Record what was written before a conflict or a failed verification
        # ends the cycle, so the next cycle does not redo or duplicate it.
        write_json_atomic(state_path, state)

    if config.get("verify_title_due_after_sync") and not dry_run:
        if bidir_conflicts:
            raise SystemExit(
                "Bidirectional conflicts left Apple Reminders and Google Tasks unsynced. "
                "Resolve the conflicts or use conflict_policy=newer_wins."
            )
        google_writes = (
            inserted + updated + completed + deleted + duplicate_deleted
            + google_applied + bidir_initialized + len(missing_tasklists)
        )
        if google_writes:
            outbound_desired_by_list = {
                list_title: desired
                for list_title, desired in desired_by_list.items()
                if list_allows_apple_to_google(config, list_title) and list_title in tasklists
            }
            verify_google_tasks_title_due_consistency(
                client,
                outbound_desired_by_list,
                tasklists,
                blocked,
                recently_synced_task_ids=recently_synced_task_ids,
                retry_attempts=int(config.get("verify_title_due_retry_attempts") or 1),
                retry_delay_seconds=float(config.get("verify_title_due_retry_delay_seconds") or 0.0),
            )
        else:
            # Every item already matched the snapshot read this cycle, so a
            # second full read would only spend Tasks API quota.
            print("Google Tasks title/due consistency: no writes this cycle; re-read skipped.")

    print(
        "Sync summary: "
        f"inserted={inserted}, updated={updated}, unchanged={unchanged}, "
        f"completed={completed}, deleted={deleted}, duplicate_deleted={duplicate_deleted}, "
        f"skipped_invalid={skipped_invalid}, google_applied={google_applied}, "
        f"bidir_initialized={bidir_initialized}, bidir_conflicts={bidir_conflicts}"
    )
    if dry_run:
        print("Dry run only; no Google Tasks or Apple Reminders changes were made.")
    return {
        "apple_exported": len(reminders),
        "google_lists": len(tasklists),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "completed": completed,
        "deleted": deleted,
        "duplicate_deleted": duplicate_deleted,
        "skipped_invalid": skipped_invalid,
        "google_applied": google_applied,
        "bidir_initialized": bidir_initialized,
        "bidir_conflicts": bidir_conflicts,
    }


def run_calendar_sync(config: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    calendar_id = str(config["calendar_id"])
    reminders, desired, skipped_invalid = build_desired_events(config)

    print(f"Apple Reminders exported: {len(reminders)}")
    print(f"Google Calendar events desired: {len(desired)}")

    state_path = expand_path(config["state_path"])
    state = load_state(state_path)
    account_binding = resolve_sync_account_binding(config, reminders)
    bind_or_validate_sync_state_accounts(state, account_binding)
    expect_google_binding(config, account_binding)
    client = GoogleCalendarClient(config)
    existing_by_uid: dict[str, dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []

    existing_events = client.list_synced_events(calendar_id)
    existing_by_uid, duplicates = index_existing_events(existing_events)

    skip_stale_delete = config["delete_stale"] and not config["allow_empty_source_delete"] and len(desired) == 0
    allow_deletes = bool(config["delete_stale"] and not skip_stale_delete)
    bidirectional_plan = plan_google_changes_to_reminders(
        config,
        calendar_id,
        desired,
        existing_by_uid,
        state,
    )
    preflight_blocked = set(bidirectional_plan["blocked_uids"]) | set(bidirectional_plan["source_controlled"])
    planned_actions = list(bidirectional_plan["actions"])
    planned_actions.extend(
        plan_google_calendar_outbound_mutations(
            config,
            calendar_id,
            desired,
            existing_by_uid,
            duplicates,
            state,
            preflight_blocked,
            allow_deletes=allow_deletes,
        )
    )
    population = max(len(desired), managed_google_calendar_population(calendar_id, existing_by_uid, state))
    mutation_plan = build_mutation_plan(planned_actions, population)
    enforce_mutation_plan(config, mutation_plan, dry_run=dry_run)

    google_applied, bidir_initialized, bidir_conflicts, blocked_uids = apply_google_changes_to_reminders(
        config,
        calendar_id,
        desired,
        existing_by_uid,
        state,
        dry_run,
        planned=bidirectional_plan,
    )
    if google_applied and not dry_run:
        time.sleep(1)
        reminders, desired, skipped_invalid = build_desired_events(config)
        print(f"Apple Reminders re-exported after Google changes: {len(reminders)}")
        print(f"Google Calendar events desired: {len(desired)}")

    inserted = updated = unchanged = deleted = duplicate_deleted = 0

    for uid, (body, digest, reminder) in desired.items():
        if uid in blocked_uids:
            continue

        existing = existing_by_uid.get(uid)
        record = state_record(state, calendar_id, uid)
        event_id = existing.get("id") if existing else record.get("event_id") if record else None
        existing_digest = private_props(existing).get(DIGEST_KEY) if existing else record.get("digest") if record else None
        title = str(body.get("summary") or reminder.get("title") or uid)

        if dry_run:
            action = "update" if event_id and existing_digest != digest else "insert" if not event_id else "skip"
            print(f"DRY-RUN {action}: {title}")
            continue

        if existing and event_id and existing_digest == digest:
            unchanged += 1
            save_event_state(state, calendar_id, uid, existing, digest, title, reminder, config)
            continue

        if event_id:
            try:
                event = client.update_event(calendar_id, event_id, body)
                updated += 1
            except GoogleApiError as exc:
                if exc.status not in (404, 410):
                    raise
                event = client.insert_event(calendar_id, body)
                inserted += 1
        else:
            event = client.insert_event(calendar_id, body)
            inserted += 1

        save_event_state(state, calendar_id, uid, event, digest, title, reminder, config)

    desired_uids = set(desired)

    if skip_stale_delete:
        print("Skipping stale deletion because the Reminders source exported 0 items.")

    if config["delete_stale"] and not skip_stale_delete:
        stale: dict[str, str] = {}
        for key, record in list(state["events"].items()):
            if not isinstance(record, dict) or record.get("calendar_id") != calendar_id:
                continue
            uid = key.split(":", 1)[1] if ":" in key else ""
            if uid and uid not in desired_uids and record.get("event_id"):
                stale[uid] = str(record["event_id"])

        for uid, event in existing_by_uid.items():
            if uid not in desired_uids and event.get("id"):
                stale[uid] = str(event["id"])

        for uid, event_id in stale.items():
            if dry_run:
                print(f"DRY-RUN delete stale: {uid}")
                continue
            client.delete_event(calendar_id, event_id)
            remove_state_record(state, calendar_id, uid)
            deleted += 1

    if allow_deletes and duplicates:
        for event in duplicates:
            event_id = event.get("id")
            if not event_id:
                continue
            if dry_run:
                print(f"DRY-RUN delete duplicate: {event.get('summary', event_id)}")
                continue
            client.delete_event(calendar_id, str(event_id))
            duplicate_deleted += 1

    if not dry_run:
        write_json_atomic(state_path, state)

    print(
        "Sync summary: "
        f"inserted={inserted}, updated={updated}, unchanged={unchanged}, "
        f"deleted={deleted}, duplicate_deleted={duplicate_deleted}, skipped_invalid={skipped_invalid}, "
        f"google_applied={google_applied}, bidir_initialized={bidir_initialized}, "
        f"bidir_conflicts={bidir_conflicts}"
    )
    if dry_run:
        print("Dry run only; no Google Calendar or Apple Reminders changes were made.")
    return {
        "apple_exported": len(reminders),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "deleted": deleted,
        "duplicate_deleted": duplicate_deleted,
        "skipped_invalid": skipped_invalid,
        "google_applied": google_applied,
        "bidir_initialized": bidir_initialized,
        "bidir_conflicts": bidir_conflicts,
    }


def run_sync(config: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    if config["target_service"] == "calendar":
        return run_calendar_sync(config, dry_run=dry_run)
    return run_tasks_sync(config, dry_run=dry_run)


def utc_now_text() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def status_error_text(error: Any, limit: int = 300) -> str:
    """The first line of an error message, for status.json and notifications.

    Messages put any item titles on later lines (for example the post-sync
    verification lists each mismatch), so the first line is safe to keep
    outside the private log.
    """

    if isinstance(error, SystemExit) and isinstance(error.code, str):
        text = error.code
    else:
        text = str(error or "")
    lines = [line for line in text.strip().splitlines() if line.strip()]
    first = " ".join(lines[0].split()) if lines else ""
    return first if len(first) <= limit else first[: limit - 1].rstrip() + "…"


def write_sync_status(config: dict[str, Any], updates: dict[str, Any]) -> None:
    if updates.get("last_error"):
        updates = {**updates, "last_error": status_error_text(updates["last_error"])}
    status_path = expand_path(config["status_path"])
    status: dict[str, Any] = {}
    if status_path.exists():
        try:
            status = read_json(status_path)
        except (OSError, json.JSONDecodeError):
            status = {}
    status.update(updates)
    status["updated_at"] = utc_now_text()
    write_json_atomic(status_path, status)


def read_sync_status(config: dict[str, Any]) -> dict[str, Any]:
    status_path = expand_path(config["status_path"])
    if not status_path.exists():
        return {}
    try:
        return read_json(status_path)
    except (OSError, json.JSONDecodeError):
        return {}


def parse_status_time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def seconds_until_retry(last_attempt: dt.datetime | None, interval_seconds: int, now: dt.datetime | None = None) -> int:
    if not last_attempt:
        return 0
    now = now or dt.datetime.now(dt.timezone.utc)
    elapsed = (now - last_attempt).total_seconds()
    return max(0, int(interval_seconds - elapsed))


def auto_reauth_failure_count(status: dict[str, Any]) -> int:
    counts = []
    for key in ("auto_reauth_failure_count", "auto_reauth_timeout_count"):
        try:
            counts.append(max(0, int(status.get(key) or 0)))
        except (TypeError, ValueError):
            continue
    return max(counts, default=0)


def auto_reauth_failure_epoch_reset_updates() -> dict[str, Any]:
    return {
        "last_auto_reauth_failed_at": None,
        "last_auto_reauth_timeout_at": None,
        "last_auto_reauth_runtime_failure_at": None,
        "auto_reauth_failure_count": 0,
        "auto_reauth_timeout_count": 0,
    }


def auto_reauth_failure_backoff_seconds(config: dict[str, Any], status: dict[str, Any]) -> int:
    base_interval = max(300, int(config.get("auto_reauth_timeout_retry_interval_seconds") or 300))
    max_interval = max(base_interval, int(config.get("auto_reauth_min_interval_seconds") or 21600))
    failure_count = max(1, auto_reauth_failure_count(status))
    exponent = min(failure_count - 1, 16)
    return min(max_interval, base_interval * (2**exponent))


def auto_reauth_retry_wait_seconds(
    config: dict[str, Any],
    status: dict[str, Any],
    now: dt.datetime | None = None,
) -> int:
    last_runtime_failure = parse_status_time(status.get("last_auto_reauth_runtime_failure_at"))
    last_timeout = parse_status_time(status.get("last_auto_reauth_timeout_at"))
    last_failure = parse_status_time(status.get("last_auto_reauth_failed_at"))
    last_started = parse_status_time(status.get("last_auto_reauth_started_at"))
    failure_times = [value for value in (last_failure, last_runtime_failure, last_timeout) if value]
    latest_failure = max(failure_times) if failure_times else None
    if latest_failure and (not last_started or latest_failure >= last_started):
        interval = auto_reauth_failure_backoff_seconds(config, status)
        return seconds_until_retry(latest_failure, interval, now=now)

    interval = max(300, int(config.get("auto_reauth_min_interval_seconds") or 21600))
    return seconds_until_retry(last_started, interval, now=now)


def recent_auto_reauth(config: dict[str, Any], status: dict[str, Any]) -> bool:
    return auto_reauth_retry_wait_seconds(config, status) > 0


def truncate_notification_text(value: str, limit: int = 180) -> str:
    collapsed = " ".join(str(value).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "..."


def event_stream_enabled() -> bool:
    return os.environ.get("LTB_EVENT_STREAM") == "stdout"


def emit_event(event: str, **fields: Any) -> None:
    """Tell the hosting app what happened, one JSON line on the real stdout.

    Only active when the app started this process with LTB_EVENT_STREAM=stdout.
    Events never carry reminder or task titles.
    """

    if not event_stream_enabled():
        return
    stream = sys.__stdout__
    if stream is None:
        return
    payload = {"event": event, "at": utc_now_text(), **fields}
    try:
        stream.write(EVENT_STREAM_PREFIX + json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
    except (OSError, ValueError):
        pass


def send_macos_notification(
    config: dict[str, Any],
    title: str,
    message: str,
    status_key: str,
    min_interval_seconds: int,
) -> None:
    if not config.get("macos_notifications"):
        return
    use_event_stream = event_stream_enabled()
    if not use_event_stream and (sys.platform != "darwin" or not shutil.which("osascript")):
        return

    status = read_sync_status(config)
    wait_seconds = seconds_until_retry(
        parse_status_time(status.get(status_key)),
        max(0, min_interval_seconds),
    )
    if wait_seconds > 0:
        return

    if use_event_stream:
        # The menu bar app posts the notification under its own name.
        emit_event(
            "notification",
            title=title,
            message=truncate_notification_text(message),
            severity="info" if status_key == "last_success_notification_at" else "problem",
        )
        write_sync_status(config, {status_key: utc_now_text()})
        return

    script = """
on run argv
  display notification (item 2 of argv) with title (item 1 of argv)
end run
"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script, title, truncate_notification_text(message)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return

    if result.returncode == 0:
        write_sync_status(config, {status_key: utc_now_text()})


def notify_sync_ok(config: dict[str, Any]) -> None:
    send_macos_notification(
        config,
        PRODUCT_NAME,
        tr("Apple Reminders and Google Tasks are in sync.", "Apple 提醒事项与 Google Tasks 已同步。"),
        "last_success_notification_at",
        int(config.get("notify_success_min_interval_seconds") or 3600),
    )


def notify_sync_problem(config: dict[str, Any], message: str) -> None:
    send_macos_notification(
        config,
        tr("Local Tasks Bridge needs attention", "Local Tasks Bridge 需要处理"),
        message,
        "last_failure_notification_at",
        int(config.get("notify_failure_min_interval_seconds") or 300),
    )


def message_binding_paused() -> str:
    return tr(
        "Sync paused because the Apple or Google account changed. Open Local Tasks Bridge to reconnect.",
        "Apple 或 Google 账号发生变化，同步已暂停。请打开 Local Tasks Bridge 重新连接。",
    )


def message_auth_required() -> str:
    return tr(
        "Google sign-in is required to resume sync. Open Local Tasks Bridge and choose \"Reconnect Google\".",
        "需要重新登录 Google 才能继续同步。请打开 Local Tasks Bridge 并选择“重新连接 Google”。",
    )


def message_sync_failed(detail: Any) -> str:
    summary = status_error_text(detail, limit=160)
    return tr(f"Sync failed: {summary}", f"同步失败：{summary}")


MUTATION_APPROVAL_STATUS_KEY = "mutation_approval"
MUTATION_APPROVAL_DECISIONS = {"", "apply", "hold", "unanswered", "unavailable"}
# A plan has to look the same on consecutive cycles before anyone is asked, so
# a momentary partial Reminders export cannot put a deletion question on screen.
MUTATION_APPROVAL_SETTLE_CYCLES = 2
# A plan that keeps changing is asked about at most this often.
MUTATION_APPROVAL_NEW_PLAN_GAP_SECONDS = 600
MUTATION_APPROVAL_DIALOG_SECONDS = 43200
MUTATION_APPROVAL_POLL_SECONDS = 2.0
MUTATION_REVIEW_LABELS = {
    "apple_reminders.complete": (
        "Complete in Apple Reminders (completed in Google)",
        "在 Apple 提醒事项中标为完成（已在 Google 完成）",
    ),
    "apple_reminders.delete": (
        "Delete from Apple Reminders (deleted in Google)",
        "从 Apple 提醒事项删除（已在 Google 删除）",
    ),
    "google_calendar.dedupe_delete": ("Remove duplicate Google Calendar events", "清理重复的 Google 日历事件"),
    "google_calendar.delete": (
        "Delete Google Calendar events (deleted on this Mac)",
        "删除 Google 日历事件（已在这台 Mac 上删除）",
    ),
    "google_tasks.complete": (
        "Complete in Google Tasks (completed on this Mac)",
        "在 Google Tasks 中标为完成（已在这台 Mac 上完成）",
    ),
    "google_tasks.dedupe_delete": ("Remove duplicate Google Tasks items", "清理重复的 Google Tasks 条目"),
    "google_tasks.delete": (
        "Delete in Google Tasks (deleted on this Mac)",
        "在 Google Tasks 中删除（已在这台 Mac 上删除）",
    ),
}


def mutation_approval_dialog_title() -> str:
    return tr("Local Tasks Bridge: review a large change", "Local Tasks Bridge：确认大批量更改")


def mutation_approval_apply_label() -> str:
    return tr("Apply", "执行")


def mutation_approval_hold_label() -> str:
    return tr("Hold", "暂缓")


# Plain ASCII on purpose, and no user-visible text inside it. The dialog body
# carries reminder titles, so it travels in the child's environment (readable
# only by this user) rather than in argv (visible to every local user through
# ps), and is read by a constant shell command that never re-evaluates it.
MUTATION_APPROVAL_TEXT_ENV = "IRSYNC_APPROVAL_TEXT"
MUTATION_APPROVAL_DIALOG_SCRIPT = r"""
on run argv
  set dialogTitle to item 1 of argv
  set holdLabel to item 2 of argv
  set applyLabel to item 3 of argv
  set waitSeconds to (item 4 of argv) as integer
  set dialogText to do shell script "printf '%s' \"$IRSYNC_APPROVAL_TEXT\"" without altering line endings
  try
    activate
  end try
  with timeout of (waitSeconds + 60) seconds
    set answer to display dialog dialogText with title dialogTitle buttons {holdLabel, applyLabel} default button holdLabel with icon caution giving up after waitSeconds
  end timeout
  if gave up of answer then return "timeout"
  if button returned of answer is applyLabel then return "apply"
  return "hold"
end run
"""


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def mutation_review_label(key: str) -> str:
    labels = MUTATION_REVIEW_LABELS.get(key)
    return tr(*labels) if labels else key


def untitled_text() -> str:
    return tr("(untitled)", "（无标题）")


def mutation_review_item_text(item: dict[str, Any], limit: int = 60) -> str:
    title = " ".join(str(item.get("title") or "").split()) or untitled_text()
    list_title = " ".join(str(item.get("list") or "").split())
    return truncate_notification_text(f"[{list_title}] {title}" if list_title else title, limit)


def mutation_review_by_list(items: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault(str(item.get("list") or ""), []).append(item)
    return sorted(groups.items(), key=lambda entry: (-len(entry[1]), entry[0]))


def mutation_review_by_operation(review: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in review.get("items") or []:
        if isinstance(item, dict):
            groups.setdefault(str(item.get("operation") or ""), []).append(item)
    return sorted(groups.items())


def mutation_review_samples(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Pick examples round-robin across lists so one large list cannot hide the rest."""
    queues = [list(group) for _list_title, group in mutation_review_by_list(items)]
    picked: list[dict[str, Any]] = []
    while len(picked) < limit and any(queues):
        for queue in queues:
            if queue and len(picked) < limit:
                picked.append(queue.pop(0))
    return picked


def duration_text(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds >= 3600 and seconds % 3600 == 0:
        hours = seconds // 3600
        return tr(f"{hours} hour{'s' if hours != 1 else ''}", f"{hours} 小时")
    minutes = max(1, seconds // 60)
    return tr(f"{minutes} minute{'s' if minutes != 1 else ''}", f"{minutes} 分钟")


def mutation_approval_dialog_text(review: dict[str, Any], repeat_seconds: int, sample_limit: int = 5) -> str:
    items = [item for item in review.get("items") or [] if isinstance(item, dict)]
    lines = [
        tr(
            "There are more deletions/completions than the safety limit allows in one go, so please confirm.",
            "这次要执行的删除/完成数量超过了单次安全上限，需要你确认。",
        ),
        "",
    ]
    no_list = tr("no list", "无列表")
    for key, group in mutation_review_by_operation(review):
        lines.append(f"{mutation_review_label(key)}: {len(group)}")
        by_list = mutation_review_by_list(group)
        if any(list_title for list_title, _entries in by_list):
            lines.append(
                "  " + " · ".join(f"{list_title or no_list} {len(entries)}" for list_title, entries in by_list)
            )
    samples = mutation_review_samples(items, sample_limit)
    if samples:
        lines.extend(["", tr("Examples", "示例")])
        lines.extend(f"· {mutation_review_item_text(item)}" for item in samples)
        if len(items) > len(samples):
            remaining = len(items) - len(samples)
            lines.append(tr(f"and {remaining} more", f"另外还有 {remaining} 项"))
    apply_label = mutation_approval_apply_label()
    hold_label = mutation_approval_hold_label()
    repeat = duration_text(repeat_seconds)
    lines.extend(
        [
            "",
            tr(
                f"If you really deleted or completed these, choose \"{apply_label}\".",
                f"如果这些确实是你删除或完成的，请选择“{apply_label}”。",
            ),
            tr(
                f"\"{hold_label}\" holds only the deletions/completions, keeps syncing everything else, "
                f"and asks again in {repeat}.",
                f"选择“{hold_label}”只会暂缓这些删除/完成，其余改动继续同步，{repeat}后会再次询问。",
            ),
        ]
    )
    return "\n".join(lines)


def print_mutation_review(review: dict[str, Any]) -> None:
    ratio = float(review.get("destructive_ratio") or 0.0) * 100
    count = int(review.get("destructive_count") or 0)
    population = int(review.get("population") or 0)
    print("\n" + tr(
        f"Pending large change: {count} items ({ratio:.1f}% of the {population} managed items)",
        f"待确认的大批量更改：{count} 项（占 {population} 个受管理条目的 {ratio:.1f}%）",
    ))
    for key, group in mutation_review_by_operation(review):
        print(f"\n{mutation_review_label(key)}: {len(group)}")
        for list_title, entries in mutation_review_by_list(group):
            if list_title:
                print(f"  [{list_title}] {len(entries)}")
            for item in entries:
                print(f"    - {' '.join(str(item.get('title') or '').split()) or untitled_text()}")


def launch_mutation_approval_dialog(title: str, text: str, wait_seconds: int) -> Any:
    """Open the approval question without blocking the scheduler; None if impossible."""
    if sys.platform != "darwin" or not shutil.which("osascript"):
        return None
    environment = dict(os.environ)
    environment[MUTATION_APPROVAL_TEXT_ENV] = text
    try:
        return subprocess.Popen(
            [
                "osascript",
                "-e",
                MUTATION_APPROVAL_DIALOG_SCRIPT,
                title,
                mutation_approval_hold_label(),
                mutation_approval_apply_label(),
                str(max(1, int(wait_seconds))),
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def parse_mutation_approval_answer(returncode: int | None, stdout: str, stderr: str) -> str:
    """Map the dialog process result to apply, hold, timeout, or unavailable."""
    if returncode == 0:
        answer = str(stdout or "").strip()
        # Anything unexpected is treated as the safe answer.
        return answer if answer in {"apply", "hold", "timeout"} else "hold"
    if "-128" in str(stderr or ""):
        return "hold"
    return "unavailable"


def restored_mutation_approval(status: dict[str, Any]) -> dict[str, Any]:
    raw = status.get(MUTATION_APPROVAL_STATUS_KEY)
    if not isinstance(raw, dict):
        return {}
    fingerprint = str(raw.get("destructive_fingerprint") or "")
    decision = str(raw.get("decision") or "")
    if (
        len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
        or decision not in MUTATION_APPROVAL_DECISIONS
    ):
        return {}
    return {
        "destructive_fingerprint": fingerprint,
        "decision": decision,
        "decided_at": raw.get("decided_at") if parse_status_time(raw.get("decided_at")) else None,
        "prompted_at": raw.get("prompted_at") if parse_status_time(raw.get("prompted_at")) else None,
    }


def mutation_approval_memory(
    fingerprint: str,
    decision: str,
    *,
    now: dt.datetime,
    previous: dict[str, Any] | None = None,
    prompted: bool = False,
) -> dict[str, Any]:
    now_text = now.astimezone(dt.timezone.utc).isoformat(timespec="seconds")
    same_plan = bool(previous and previous.get("destructive_fingerprint") == fingerprint)
    if prompted:
        prompted_at = now_text
    elif same_plan:
        prompted_at = (previous or {}).get("prompted_at")
    else:
        prompted_at = None
    return {
        "destructive_fingerprint": fingerprint,
        "decision": decision,
        "decided_at": now_text if decision else None,
        "prompted_at": prompted_at,
    }


class MutationPlanApprovals:
    """The scheduler's side of asking a person about a blocked destructive plan.

    At most one question is open, in its own process, so the scheduler keeps
    syncing everything except the held deletions and completions while it
    waits. Only the answer, a hash of the plan's destructive set, and
    timestamps are persisted in status.json; titles stay in the dialog text.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.memory = restored_mutation_approval(read_sync_status(config))
        self.process: Any = None
        self.process_fingerprint = ""
        self.observed_fingerprint = ""
        self.settled_cycles = 0
        self.blocked_fingerprint = ""
        self.blocked_streak = 0

    def dialog_open(self) -> bool:
        return self.process is not None

    def dialog_running(self) -> bool:
        if self.process is None:
            return False
        try:
            return self.process.poll() is None
        except OSError:
            return False

    def remember(self, fingerprint: str, decision: str, *, now: dt.datetime | None = None, prompted: bool = False) -> None:
        self.memory = mutation_approval_memory(
            fingerprint,
            decision,
            now=now or utc_now(),
            previous=self.memory,
            prompted=prompted,
        )
        write_sync_status(self.config, {MUTATION_APPROVAL_STATUS_KEY: self.memory})

    def observe(self, summary: dict[str, Any] | None, review: dict[str, Any] | None) -> None:
        """Count how many consecutive cycles produced this blocked plan."""
        fingerprint = str((summary or {}).get("fingerprint") or "")
        self.blocked_fingerprint, self.blocked_streak = next_blocked_plan_streak(
            self.blocked_fingerprint,
            self.blocked_streak,
            fingerprint,
        )
        destructive = str((review or {}).get("destructive_fingerprint") or "")
        if destructive and destructive == self.observed_fingerprint:
            self.settled_cycles += 1
        else:
            self.observed_fingerprint = destructive
            self.settled_cycles = 1 if destructive else 0

    def refresh_from_status(self) -> None:
        """Adopt a newer decision recorded by another process.

        The menu bar app and `ltb approvals hold` record answers in
        status.json; the scheduler honours them like a dialog answer.
        """

        stored = restored_mutation_approval(read_sync_status(self.config))
        if not stored or not stored.get("decision"):
            return
        stored_at = parse_status_time(stored.get("decided_at"))
        current_at = parse_status_time(self.memory.get("decided_at")) if self.memory else None
        if stored_at and (current_at is None or stored_at > current_at):
            self.memory = stored

    def collect(self, now: dt.datetime | None = None) -> None:
        """Record the answer of a question that has closed."""
        if self.process is None:
            self.refresh_from_status()
        if self.process is None or self.dialog_running():
            return
        process, fingerprint = self.process, self.process_fingerprint
        self.process, self.process_fingerprint = None, ""
        try:
            stdout, stderr = process.communicate(timeout=5)
        except (OSError, ValueError, subprocess.SubprocessError):
            stdout, stderr = "", ""
        answer = parse_mutation_approval_answer(process.returncode, stdout or "", stderr or "")
        decision = "unanswered" if answer == "timeout" else answer
        print(f"Bulk change prompt closed: {decision}.", flush=True)
        self.remember(fingerprint, decision, now=now)
        if decision == "unavailable":
            self.notify_manager_fallback()

    def approval_token(self, fingerprint: str, now: dt.datetime | None = None) -> str:
        """A destructive-set approval if the user approved exactly this set recently."""
        memory = self.memory
        if not fingerprint or memory.get("destructive_fingerprint") != fingerprint or memory.get("decision") != "apply":
            return ""
        decided_at = parse_status_time(memory.get("decided_at"))
        if not decided_at:
            return ""
        age_seconds = ((now or utc_now()) - decided_at).total_seconds()
        if age_seconds > int(self.config["destructive_approval_ttl_seconds"]):
            return ""
        return f"{fingerprint}:{int(decided_at.timestamp())}"

    def should_ask(self, fingerprint: str, now: dt.datetime) -> bool:
        if not fingerprint:
            return False
        memory = self.memory
        decision = str(memory.get("decision") or "")
        decided_at = parse_status_time(memory.get("decided_at"))
        repeat = int(self.config["mutation_approval_prompt_repeat_seconds"])
        # "Hold" means no bulk-change questions for a while, whatever the plan.
        if decision in {"hold", "unavailable"} and decided_at and (now - decided_at).total_seconds() < repeat:
            return False
        if memory.get("destructive_fingerprint") == fingerprint:
            if event_stream_enabled() and not memory.get("decision"):
                # The menu bar app is showing this question in its own
                # window; ask again only after it has been open a long time.
                prompted_at = parse_status_time(memory.get("prompted_at"))
                if prompted_at and (now - prompted_at).total_seconds() < MUTATION_APPROVAL_DIALOG_SECONDS:
                    return False
            return not self.approval_token(fingerprint, now)
        prompted_at = parse_status_time(memory.get("prompted_at"))
        return not (prompted_at and (now - prompted_at).total_seconds() < MUTATION_APPROVAL_NEW_PLAN_GAP_SECONDS)

    def consider(self, review: dict[str, Any] | None, now: dt.datetime | None = None) -> None:
        """Ask about this plan once it has settled and nobody has answered for it."""
        review = review or {}
        fingerprint = str(review.get("destructive_fingerprint") or "")
        if self.process is not None:
            if self.process_fingerprint == fingerprint:
                return
            print("Closing a bulk change prompt whose plan has changed.", flush=True)
            self.close()
        if not fingerprint or fingerprint != self.observed_fingerprint:
            return
        if self.settled_cycles < MUTATION_APPROVAL_SETTLE_CYCLES:
            return
        now = now or utc_now()
        if not self.should_ask(fingerprint, now):
            return
        process = None
        if self.config.get("mutation_approval_prompt") and event_stream_enabled():
            # Hosted by the menu bar app: it opens its review window on this
            # event and records the answer with `approvals apply/hold`.
            self.remember(fingerprint, "", now=now, prompted=True)
            print("Asked the menu bar app to review a large destructive mutation plan.", flush=True)
            emit_event(
                "approval_requested",
                destructive_fingerprint=fingerprint,
                destructive_count=len(review.get("items") or []),
            )
            return
        if self.config.get("mutation_approval_prompt"):
            process = launch_mutation_approval_dialog(
                mutation_approval_dialog_title(),
                mutation_approval_dialog_text(review, int(self.config["mutation_approval_prompt_repeat_seconds"])),
                MUTATION_APPROVAL_DIALOG_SECONDS,
            )
        if process is None:
            self.remember(fingerprint, "unavailable", now=now, prompted=True)
            self.notify_manager_fallback()
            return
        self.process, self.process_fingerprint = process, fingerprint
        self.remember(fingerprint, "", now=now, prompted=True)
        print("Asked the signed-in user to review a large destructive mutation plan.", flush=True)
        emit_event(
            "approval_requested",
            destructive_fingerprint=fingerprint,
            destructive_count=len(review.get("items") or []),
        )
        apply_label = mutation_approval_apply_label()
        hold_label = mutation_approval_hold_label()
        notify_sync_problem(
            self.config,
            tr(
                f"Please review a large batch of deletions/completions: choose \"{apply_label}\" or \"{hold_label}\".",
                f"有一批较多的删除/完成需要确认：请选择“{apply_label}”或“{hold_label}”。",
            ),
        )

    def notify_manager_fallback(self) -> None:
        notify_sync_problem(
            self.config,
            tr(
                "A large batch of deletions/completions needs review. Open Local Tasks Bridge and choose "
                "\"Review Pending Changes\" (or run `ltb approvals show`).",
                "有一批较多的删除/完成需要确认。请打开 Local Tasks Bridge 并选择“查看待确认的更改”"
                "（或运行 `ltb approvals show`）。",
            ),
        )

    def resolve(self) -> None:
        """The plan is gone (applied, undone, or never real): drop its question."""
        self.close()
        self.observed_fingerprint, self.settled_cycles = "", 0
        self.blocked_fingerprint, self.blocked_streak = "", 0
        if self.memory:
            self.memory = {}
            write_sync_status(self.config, {MUTATION_APPROVAL_STATUS_KEY: None})

    def close(self) -> None:
        process, self.process, self.process_fingerprint = self.process, None, ""
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            process.communicate(timeout=1)
        except Exception:  # noqa: BLE001 - closing a stale question must never stop the scheduler.
            pass


def held_destructive_config(config: dict[str, Any]) -> dict[str, Any]:
    """The same sync with every deletion and completion held back."""
    held = dict(config)
    held["delete_stale"] = False
    held["_disable_delete_propagation"] = True
    held["_mutation_plan_approval"] = ""
    held["_mutation_plan_destructive_approval"] = ""
    return held


def run_scheduled_sync(config: dict[str, Any], approvals: MutationPlanApprovals) -> dict[str, Any]:
    """Run one scheduler cycle. The caller holds the sync lock.

    A plan over the destructive limits is still never written without an
    approval. Instead of stopping the whole sync, the cycle asks the signed-in
    user once the plan has settled, applies exactly the destructive set they
    approved, and until then syncs everything else with deletions and
    completions held back.
    """
    try:
        run_sync(config, dry_run=False)
    except MutationPlanApprovalRequired as exc:
        blocked = exc
    else:
        approvals.resolve()
        return {"outcome": "ok"}

    eprint(f"Sync loop blocked by mutation plan: {blocked}")
    approvals.observe(blocked.summary, blocked.review)
    if should_auto_approve_blocked_plan(config, approvals.blocked_streak):
        print(
            f"Auto-approving destructive mutation plan after {approvals.blocked_streak} identical consecutive plans.",
            flush=True,
        )
        approved = dict(config)
        approved["_mutation_plan_approval"] = mutation_plan_approval_token(
            {"fingerprint": approvals.blocked_fingerprint}
        )
        run_sync(approved, dry_run=False)
        approvals.resolve()
        return {"outcome": "applied"}

    token = approvals.approval_token(str(blocked.review.get("destructive_fingerprint") or ""))
    if token:
        print("Applying the destructive mutation plan the signed-in user approved.", flush=True)
        approved = dict(config)
        approved["_mutation_plan_destructive_approval"] = token
        try:
            run_sync(approved, dry_run=False)
        except MutationPlanApprovalRequired as changed:
            eprint(f"Approved mutation plan changed before it was applied: {changed}")
            blocked = changed
            approvals.observe(blocked.summary, blocked.review)
        else:
            approvals.resolve()
            return {"outcome": "applied"}

    approvals.consider(blocked.review)
    print("Holding deletions and completions until the plan is approved; syncing everything else.", flush=True)
    run_sync(held_destructive_config(config), dry_run=False)
    return {"outcome": "held", "summary": blocked.summary}


def record_scheduled_sync_result(config: dict[str, Any], result: dict[str, Any]) -> None:
    finished = utc_now_text()
    if result.get("outcome") == "held":
        write_sync_status(
            config,
            {
                "state": "awaiting_mutation_approval",
                "last_end_at": finished,
                "last_success_at": finished,
                **auto_reauth_failure_epoch_reset_updates(),
                "last_error": "",
                "mutation_plan": result.get("summary"),
                "consecutive_failures": 0,
            },
        )
        return
    write_sync_status(
        config,
        {
            "state": "ok",
            "last_end_at": finished,
            "last_success_at": finished,
            **auto_reauth_failure_epoch_reset_updates(),
            "last_error": "",
            "mutation_plan": None,
            "consecutive_failures": 0,
        },
    )
    notify_sync_ok(config)


def wait_for_next_cycle(
    interval: int,
    approvals: MutationPlanApprovals,
    *,
    cycle_started_at: float | None = None,
    wake: Callable[[], bool] | None = None,
) -> None:
    """Keep a start-to-start cadence, waking early when a question is answered.

    With ``wake``, the wait also ends as soon as it returns True (a sync-now
    request, or a pause/resume), checked about once a second.
    """
    started_at = time.monotonic() if cycle_started_at is None else cycle_started_at
    deadline = started_at + interval
    if wake is None:
        if not approvals.dialog_open():
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            return
        while approvals.dialog_running():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(MUTATION_APPROVAL_POLL_SECONDS, remaining))
        return
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        if wake():
            return
        if approvals.dialog_open() and not approvals.dialog_running():
            return
        time.sleep(min(SYNC_NOW_POLL_SECONDS, remaining))


def local_reauth_can_satisfy_binding(config: dict[str, Any]) -> bool:
    """Whether a browser OAuth login could produce the credential the state expects.

    run_auth_flow only ever mints a local_oauth credential. When the sync state
    is bound to the gcloud ADC credential instead, that new token is a different
    identity and the binding guard has to reject it, so the flow opens a browser
    the owner did not ask for and leaves the loop exactly where it was.
    """
    try:
        state = load_state(expand_path(config["state_path"]))
    except Exception:
        return True
    binding = state.get("account_binding") or {}
    bound = str(binding.get("google") or "") if isinstance(binding, dict) else ""
    if not bound:
        return True
    if isinstance(binding, dict) and int(binding.get("version") or 1) >= 2:
        # Bound to the Google account itself: a browser sign-in to that same
        # account satisfies the binding whatever credential it produces.
        return True
    for candidate in load_token_candidates(config):
        if str(candidate.get("_credential_source") or "") != "gcloud_adc":
            continue
        try:
            if google_credential_binding(candidate) == bound:
                return False
        except AuthenticationRequired:
            continue
    return True


def maybe_run_auto_reauth(config: dict[str, Any], reason: str) -> bool:
    if not config.get("auto_reauth_browser"):
        return False

    if not local_reauth_can_satisfy_binding(config):
        message = (
            "Sync state is bound to the gcloud ADC credential, so a browser OAuth login "
            "would mint a different identity that the account binding must reject. "
            "Restore the bound credential instead:\n"
            "  gcloud auth application-default login"
        )
        eprint(message)
        write_sync_status(
            config,
            {
                "state": "auth_required",
                "last_auto_reauth_skipped_at": utc_now_text(),
                "last_error": message,
            },
        )
        return False

    status = read_sync_status(config)
    wait_seconds = auto_reauth_retry_wait_seconds(config, status)
    if wait_seconds > 0:
        eprint(f"Automatic browser reauth was already attempted recently; retrying in {wait_seconds} seconds.")
        write_sync_status(
            config,
            {
                "state": "auth_required",
                "last_auto_reauth_skipped_at": utc_now_text(),
                "last_error": reason,
            },
        )
        return False

    started = utc_now_text()
    timeout_seconds = max(60, int(config.get("auto_reauth_timeout_seconds") or 300))
    print(
        f"Starting automatic Google OAuth browser login; waiting up to {timeout_seconds} seconds.",
        flush=True,
    )
    write_sync_status(
        config,
        {
            "state": "auth_prompt_open",
            "last_auto_reauth_started_at": started,
            "last_auto_reauth_runtime_failure_at": None,
            "last_error": reason,
        },
    )

    try:
        run_auth_flow(config)
    except OAuthCallbackTimeout as exc:
        latest_status = read_sync_status(config)
        timeout_count = int(latest_status.get("auto_reauth_timeout_count") or 0) + 1
        failure_count = auto_reauth_failure_count(latest_status) + 1
        write_sync_status(
            config,
            {
                "state": "auth_timeout",
                "last_auto_reauth_failed_at": utc_now_text(),
                "last_auto_reauth_timeout_at": utc_now_text(),
                "auto_reauth_timeout_count": timeout_count,
                "auto_reauth_failure_count": failure_count,
                "last_error": str(exc),
            },
        )
        notify_sync_problem(
            config,
            tr("Google sign-in timed out; it will be retried automatically.", "Google 登录超时，稍后会自动重试。"),
        )
        eprint(f"Automatic browser reauth timed out: {exc}")
        return False
    except (SystemExit, AuthenticationRequired) as exc:
        # Denied consent, an unticked Tasks permission, or a refused client.
        latest_status = read_sync_status(config)
        failure_count = auto_reauth_failure_count(latest_status) + 1
        write_sync_status(
            config,
            {
                "state": "auth_required",
                "last_auto_reauth_failed_at": utc_now_text(),
                "auto_reauth_failure_count": failure_count,
                "last_error": str(exc),
            },
        )
        eprint(f"Automatic browser reauth failed: {exc}")
        return False
    except Exception as exc:  # noqa: BLE001 - an auth helper failure must not stop the scheduler.
        latest_status = read_sync_status(config)
        failure_count = auto_reauth_failure_count(latest_status) + 1
        error_text = truncate_notification_text(str(exc) or exc.__class__.__name__)
        write_sync_status(
            config,
            {
                "state": "auth_required",
                "last_auto_reauth_failed_at": utc_now_text(),
                "last_auto_reauth_runtime_failure_at": utc_now_text(),
                "auto_reauth_failure_count": failure_count,
                "last_error": f"Automatic Google OAuth browser login failed: {error_text}",
            },
        )
        notify_sync_problem(
            config,
            tr("Google sign-in could not start; it will be retried automatically.", "无法启动 Google 登录，稍后会自动重试。"),
        )
        eprint(f"Automatic browser reauth failed unexpectedly: {error_text}")
        return False

    write_sync_status(
        config,
        {
            "state": "auth_refreshed",
            "last_auto_reauth_completed_at": utc_now_text(),
            **auto_reauth_failure_epoch_reset_updates(),
            "last_error": "",
        },
    )
    print("Automatic Google OAuth browser login completed.", flush=True)
    return True


def restored_consecutive_failures(status: dict[str, Any]) -> int:
    if str(status.get("state") or "") in {"ok", "dry_run_ok"}:
        return 0
    try:
        return max(0, int(status.get("consecutive_failures") or 0))
    except (TypeError, ValueError):
        return 0


LEGACY_TMP_LOGS = (
    Path("/tmp/icloud-reminders-google-sync.out.log"),
    Path("/tmp/icloud-reminders-google-sync.err.log"),
)


def prepare_private_log(path: Path, max_bytes: int) -> None:
    """Make the log directory private and rotate an oversized log once.

    The log carries reminder and task titles, so it lives in a 0700
    directory, is written 0600, and is never followed through a symlink.
    """

    directory = path.parent
    if directory.is_symlink():
        raise SystemExit(f"Refusing to use a symlinked log directory: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    if path.is_symlink():
        raise SystemExit(f"Refusing to write the log through a symlink: {path}")
    if max_bytes > 0 and path.is_file() and path.stat().st_size >= max_bytes:
        rotated = path.with_name(path.name + ".1")
        if rotated.is_symlink():
            raise SystemExit(f"Refusing to rotate the log onto a symlink: {rotated}")
        with contextlib.suppress(FileNotFoundError):
            rotated.unlink()
        os.replace(path, rotated)
        os.chmod(rotated, 0o600)


def open_private_log(path: Path, max_bytes: int) -> Any:
    prepare_private_log(path, max_bytes)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    os.fchmod(descriptor, 0o600)
    return os.fdopen(descriptor, "a", buffering=1, encoding="utf-8", errors="replace")


def retire_legacy_tmp_logs() -> list[str]:
    """Delete world-readable logs that very old installs left in /tmp."""

    removed: list[str] = []
    for path in LEGACY_TMP_LOGS:
        for candidate in (path, path.with_name(path.name + ".1")):
            try:
                info = candidate.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid():
                candidate.unlink()
                removed.append(str(candidate))
    return removed


class LoopStopRequested(Exception):
    """SIGTERM arrived while the scheduler was idle."""


_LOOP_SIGNALS = {"in_cycle": False, "stop": False}


def handle_loop_termination(_signum: int, _frame: Any) -> None:
    # Never interrupt a cycle half-way: finish it, then stop. While idle,
    # leave the wait immediately.
    _LOOP_SIGNALS["stop"] = True
    if not _LOOP_SIGNALS["in_cycle"]:
        raise LoopStopRequested()


def acquire_loop_lock(config: dict[str, Any]) -> Any:
    """Hold run-loop.lock for this process's lifetime; None if another loop has it."""

    path = loop_lock_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
    return handle


def condition_for_state(state: str, *, paused: bool = False) -> str:
    if paused:
        return "paused"
    return {
        "ok": "healthy",
        "awaiting_mutation_approval": "mutation_approval_pending",
        "blocked_mutation_plan": "mutation_blocked",
        "auth_required": "auth_required",
        "auth_timeout": "auth_required",
        "auth_prompt_open": "auth_required",
        "account_binding_required": "account_binding_required",
        "failed": "failed",
        "running": "running",
        "paused": "paused",
    }.get(state, "unknown")


def loop_wake_requested(
    config: dict[str, Any],
    *,
    was_paused: bool,
    cycle_started_wall: float,
    cycle_started_monotonic: float,
) -> bool:
    paused = sync_paused(config)
    if paused != was_paused:
        return True
    if paused:
        return False
    request = sync_now_path(config)
    try:
        requested_at = request.stat().st_mtime
    except FileNotFoundError:
        return False
    if requested_at <= cycle_started_wall:
        # Asked for before the cycle that just ran started: already served.
        with contextlib.suppress(FileNotFoundError):
            request.unlink()
        return False
    minimum_gap = float(config.get("trigger_min_interval_seconds") or 0)
    return time.monotonic() - cycle_started_monotonic >= minimum_gap


def text_path_argument(args: argparse.Namespace, name: str) -> str | None:
    value = getattr(args, name, None)
    return value if isinstance(value, str) and value.strip() else None


def run_loop_cycle(
    config: dict[str, Any],
    approvals: MutationPlanApprovals,
    consecutive_failures: int,
) -> int:
    """One scheduler cycle with its error handling; returns the failure streak."""
    started = utc_now_text()
    print(f"[{started}] sync start", flush=True)
    try:
        approvals.collect()
        with sync_lock(config, wait=False) as acquired:
            if acquired:
                write_sync_status(
                    config,
                    {
                        "state": "running",
                        "last_start_at": started,
                        "last_error": "",
                        "mutation_plan": None,
                        "consecutive_failures": consecutive_failures,
                    },
                )
                result = run_scheduled_sync(config, approvals)
                consecutive_failures = 0
                record_scheduled_sync_result(config, result)
            else:
                print("Another sync is already running; skipping this cycle.", flush=True)
    except KeyboardInterrupt:
        approvals.close()
        raise
    except MutationPlanApprovalRequired as exc:
        # Reached only when a held or an approved pass is blocked itself.
        # The question to the user, if any, stays as it is.
        consecutive_failures += 1
        eprint(f"Sync loop blocked by mutation plan: {exc}")
        write_sync_status(
            config,
            {
                "state": "blocked_mutation_plan",
                "last_end_at": utc_now_text(),
                "last_error": str(exc),
                "mutation_plan": exc.summary,
                "consecutive_failures": consecutive_failures,
            },
        )
    except AccountBindingRequired as exc:
        consecutive_failures += 1
        eprint(f"Sync loop account binding blocked: {exc}")
        write_sync_status(
            config,
            {
                "state": "account_binding_required",
                "last_end_at": utc_now_text(),
                "last_error": str(exc),
                "consecutive_failures": consecutive_failures,
            },
        )
        notify_sync_problem(config, message_binding_paused())
    except AuthenticationRequired as exc:
        consecutive_failures += 1
        eprint(f"Sync loop auth required: {exc}")
        error_text = str(exc)
        write_sync_status(
            config,
            {
                "state": "auth_required",
                "last_end_at": utc_now_text(),
                "last_error": error_text,
                "consecutive_failures": consecutive_failures,
            },
        )
        notify_sync_problem(config, message_auth_required())
        if maybe_run_auto_reauth(config, error_text):
            print("Retrying sync after automatic Google OAuth login.", flush=True)
            try:
                with sync_lock(config, wait=False) as acquired:
                    if acquired:
                        result = run_scheduled_sync(config, approvals)
                        consecutive_failures = 0
                        record_scheduled_sync_result(config, result)
                    else:
                        print("Another sync is already running; skipping retry.", flush=True)
            except AuthenticationRequired as retry_exc:
                consecutive_failures += 1
                eprint(f"Sync retry still requires auth: {retry_exc}")
                write_sync_status(
                    config,
                    {
                        "state": "auth_required",
                        "last_end_at": utc_now_text(),
                        "last_error": str(retry_exc),
                        "consecutive_failures": consecutive_failures,
                    },
                )
                notify_sync_problem(config, message_auth_required())
            except MutationPlanApprovalRequired as retry_exc:
                consecutive_failures += 1
                eprint(f"Sync retry blocked by mutation plan: {retry_exc}")
                write_sync_status(
                    config,
                    {
                        "state": "blocked_mutation_plan",
                        "last_end_at": utc_now_text(),
                        "last_error": str(retry_exc),
                        "mutation_plan": retry_exc.summary,
                        "consecutive_failures": consecutive_failures,
                    },
                )
            except AccountBindingRequired as retry_exc:
                consecutive_failures += 1
                eprint(f"Sync retry account binding blocked: {retry_exc}")
                write_sync_status(
                    config,
                    {
                        "state": "account_binding_required",
                        "last_end_at": utc_now_text(),
                        "last_error": str(retry_exc),
                        "consecutive_failures": consecutive_failures,
                    },
                )
                notify_sync_problem(config, message_binding_paused())
            except SystemExit as retry_exc:
                consecutive_failures += 1
                eprint(f"Sync retry error: {retry_exc}")
                write_sync_status(
                    config,
                    {
                        "state": "failed",
                        "last_end_at": utc_now_text(),
                        "last_error": str(retry_exc),
                        "consecutive_failures": consecutive_failures,
                    },
                )
                notify_sync_problem(config, message_sync_failed(retry_exc))
            except Exception as retry_exc:  # noqa: BLE001 - keep the scheduler alive after retry failures.
                consecutive_failures += 1
                eprint(f"Sync retry error: {retry_exc}")
                write_sync_status(
                    config,
                    {
                        "state": "failed",
                        "last_end_at": utc_now_text(),
                        "last_error": str(retry_exc),
                        "consecutive_failures": consecutive_failures,
                    },
                )
                notify_sync_problem(config, message_sync_failed(retry_exc))
    except SystemExit as exc:
        consecutive_failures += 1
        eprint(f"Sync loop error: {exc}")
        write_sync_status(
            config,
            {
                "state": "failed",
                "last_end_at": utc_now_text(),
                "last_error": str(exc),
                "consecutive_failures": consecutive_failures,
            },
        )
        notify_sync_problem(config, message_sync_failed(exc))
    except Exception as exc:  # noqa: BLE001 - a scheduler should log and keep running.
        consecutive_failures += 1
        eprint(f"Sync loop error: {exc}")
        write_sync_status(
            config,
            {
                "state": "failed",
                "last_end_at": utc_now_text(),
                "last_error": str(exc),
                "consecutive_failures": consecutive_failures,
            },
        )
        notify_sync_problem(config, message_sync_failed(exc))
    print(f"[{utc_now_text()}] sync end", flush=True)
    return consecutive_failures


class LoopLog:
    """The run-loop's private log file, rotated by size between cycles."""

    def __init__(self, path: Path, max_bytes: int) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.stream = open_private_log(path, max_bytes)

    def rotate_if_needed(self) -> None:
        if self.max_bytes <= 0:
            return
        try:
            size = os.fstat(self.stream.fileno()).st_size
        except (OSError, ValueError):
            return
        if size < self.max_bytes:
            return
        self.stream.flush()
        self.stream.close()
        self.stream = open_private_log(self.path, self.max_bytes)
        sys.stdout = sys.stderr = self.stream

    def close(self) -> None:
        with contextlib.suppress(OSError, ValueError):
            self.stream.close()


def cmd_run_loop(args: argparse.Namespace) -> None:
    log_file = text_path_argument(args, "log_file")
    raw_max_bytes = getattr(args, "log_max_bytes", None)
    max_bytes = raw_max_bytes if isinstance(raw_max_bytes, int) else DEFAULT_LOG_MAX_BYTES
    original_streams = (sys.stdout, sys.stderr)
    loop_log: LoopLog | None = None
    if log_file:
        loop_log = LoopLog(Path(log_file).expanduser(), max_bytes)
        sys.stdout = sys.stderr = loop_log.stream
    else:
        harden_runtime_log_modes()
    try:
        run_scheduler(args, loop_log)
    finally:
        sys.stdout, sys.stderr = original_streams
        if loop_log is not None:
            loop_log.close()


SHARED_CLIENT_MIN_INTERVAL_SECONDS = 300
SHARED_CLIENT_MIN_TRIGGER_SECONDS = 30


def signed_in_with_shared_client(config: dict[str, Any]) -> bool:
    """Whether the current Google token was issued to the bundled OAuth client."""

    token_path = expand_path(config["token_path"])
    with contextlib.suppress(OSError, json.JSONDecodeError, AttributeError):
        mode = str(read_json(token_path).get("_oauth_client_mode") or "")
        if mode:
            return mode == "bundled"
    return oauth_client_status(config)["active"] == "bundled"


def effective_scheduler_timing(config: dict[str, Any]) -> tuple[int, int]:
    """(interval, minimum gap between triggered cycles) for this sign-in.

    Everyone signed in through the shared client shares one Google Tasks API
    quota, so their scheduler polls Google at most every five minutes. Local
    edits still trigger a sync within seconds through sync-now.
    """

    interval = int(config["sync_interval_seconds"])
    trigger_gap = int(config.get("trigger_min_interval_seconds") or 0)
    if signed_in_with_shared_client(config):
        interval = max(interval, SHARED_CLIENT_MIN_INTERVAL_SECONDS)
        trigger_gap = max(trigger_gap, SHARED_CLIENT_MIN_TRIGGER_SECONDS)
    return interval, trigger_gap


def run_scheduler(args: argparse.Namespace, loop_log: LoopLog | None) -> None:
    config = load_config(args)
    apply_network_config(config)
    if int(config["sync_interval_seconds"]) < MIN_SYNC_INTERVAL_SECONDS:
        raise SystemExit("sync_interval_seconds must be at least 60.")
    configured_trigger_gap = int(config.get("trigger_min_interval_seconds") or 0)
    interval, _trigger_gap = effective_scheduler_timing(config)

    lock_handle = acquire_loop_lock(config)
    if lock_handle is None:
        raise SystemExit(
            tr(
                "Another Local Tasks Bridge sync loop is already running; not starting a second one.",
                "已有另一个 Local Tasks Bridge 同步循环在运行，不会再启动第二个。",
            )
        )
    previous_handler: Any = None
    install_handler = threading.current_thread() is threading.main_thread()
    if install_handler:
        previous_handler = signal.signal(signal.SIGTERM, handle_loop_termination)
    _LOOP_SIGNALS.update(in_cycle=False, stop=False)
    # Hosted by the menu bar app: if the app dies (force quit, crash), this
    # process is re-parented and should not keep syncing on its own.
    host_pid = os.getppid() if event_stream_enabled() else 0

    def host_gone() -> bool:
        if host_pid and os.getppid() != host_pid:
            _LOOP_SIGNALS["stop"] = True
            return True
        return False

    approvals = MutationPlanApprovals(config)
    try:
        print(f"Starting sync loop every {interval} seconds. Press Ctrl-C to stop.", flush=True)
        emit_event("loop_started", version=__version__, interval=interval)
        consecutive_failures = restored_consecutive_failures(read_sync_status(config))
        was_paused = False
        while True:
            if host_gone():
                print("The hosting app is gone; stopping sync loop.", flush=True)
                approvals.close()
                return
            cycle_started_at = time.monotonic()
            cycle_started_wall = time.time()
            # Re-evaluated every cycle: signing in again can switch between
            # the person's own client and the shared one.
            interval, config["trigger_min_interval_seconds"] = effective_scheduler_timing(
                {**config, "trigger_min_interval_seconds": configured_trigger_gap}
            )
            if sync_paused(config):
                if not was_paused:
                    print(f"[{utc_now_text()}] sync paused", flush=True)
                    write_sync_status(config, {"state": "paused", "paused_at": utc_now_text()})
                    emit_event("paused")
                was_paused = True
            else:
                if was_paused:
                    print(f"[{utc_now_text()}] sync resumed", flush=True)
                    emit_event("resumed")
                    was_paused = False
                with contextlib.suppress(FileNotFoundError):
                    sync_now_path(config).unlink()
                emit_event("cycle_started")
                _LOOP_SIGNALS["in_cycle"] = True
                try:
                    consecutive_failures = run_loop_cycle(config, approvals, consecutive_failures)
                finally:
                    _LOOP_SIGNALS["in_cycle"] = False
                state = str(read_sync_status(config).get("state") or "")
                emit_event(
                    "cycle_finished",
                    state=state,
                    condition=condition_for_state(state),
                    consecutive_failures=consecutive_failures,
                )
            if loop_log is not None:
                loop_log.rotate_if_needed()
            if _LOOP_SIGNALS["stop"]:
                approvals.close()
                print("Stopping sync loop.", flush=True)
                return
            paused_now = was_paused
            try:
                wait_for_next_cycle(
                    interval,
                    approvals,
                    cycle_started_at=cycle_started_at,
                    wake=lambda: host_gone() or loop_wake_requested(
                        config,
                        was_paused=paused_now,
                        cycle_started_wall=cycle_started_wall,
                        cycle_started_monotonic=cycle_started_at,
                    ),
                )
            except KeyboardInterrupt:
                approvals.close()
                print("Stopping sync loop.", flush=True)
                return
    except LoopStopRequested:
        approvals.close()
        print("Stopping sync loop.", flush=True)
    finally:
        if install_handler:
            signal.signal(signal.SIGTERM, previous_handler or signal.SIG_DFL)
        lock_handle.close()


# --- Command-line interface for people and for the menu bar app -------------
#
# Every command that takes --json prints exactly one JSON object on stdout and
# sends progress text to stderr; see docs/app-engine-contract.md.

EXIT_CODES = {
    "failed": 1,
    "auth_required": 3,
    "account_binding_required": 4,
    "approval_required": 5,
    "reminders_unavailable": 6,
    "config_invalid": 7,
    "oauth_client_missing": 8,
    "network": 9,
    "plan_changed": 10,
}


class CommandError(Exception):
    def __init__(self, code: str, message: str, **extra: Any) -> None:
        self.code = code if code in EXIT_CODES else "failed"
        self.message = message
        self.extra = extra
        super().__init__(message)


def message_network() -> str:
    return tr(
        "Google could not be reached. Check the network or proxy setting and try again.",
        "无法连接到 Google。请检查网络或代理设置后重试。",
    )


def classify_exception(exc: BaseException) -> tuple[str, str, dict[str, Any]]:
    """Map an exception to (error code, localized message, extra JSON fields)."""

    if isinstance(exc, CommandError):
        return exc.code, exc.message, dict(exc.extra)
    if isinstance(exc, MutationPlanApprovalRequired):
        return (
            "approval_required",
            tr(
                "The plan deletes or completes more items than the safety limit allows; review it first.",
                "这次计划删除或完成的条目超过了安全上限，请先确认。",
            ),
            {"plan": dict(exc.summary or {})},
        )
    if isinstance(exc, AccountBindingRequired):
        return "account_binding_required", message_binding_paused(), {}
    if isinstance(exc, (AuthenticationRequired, OAuthCallbackTimeout)):
        return "auth_required", str(exc) or message_auth_required(), {}
    if isinstance(exc, RemindersUnavailable):
        return "reminders_unavailable", str(exc.code if isinstance(exc.code, str) else exc), {}
    if isinstance(exc, OAuthClientMissing):
        return "oauth_client_missing", str(exc.code if isinstance(exc.code, str) else exc), {}
    if isinstance(exc, GoogleApiError):
        if exc.status in (401, 403):
            return "auth_required", str(exc), {}
        if exc.status == 429 or exc.status >= 500:
            return "network", str(exc), {}
        return "failed", str(exc), {}
    if isinstance(exc, OAuthTokenError):
        if exc.invalid_grant:
            return "auth_required", message_auth_required(), {}
        if exc.status == 0:
            return "network", message_network(), {}
        return "failed", str(exc), {}
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return "network", message_network(), {}
    if isinstance(exc, SystemExit):
        text = exc.code if isinstance(exc.code, str) else str(exc)
        return "failed", text or tr("The command failed.", "命令执行失败。"), {}
    return "failed", str(exc) or exc.__class__.__name__, {}


def json_mode(args: argparse.Namespace) -> bool:
    return getattr(args, "json", False) is True


def write_json_document(payload: dict[str, Any], stream: Any = None) -> None:
    target = stream or sys.stdout
    target.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    target.flush()


def run_cli_command(
    args: argparse.Namespace,
    handler: Callable[[], dict[str, Any]],
    human: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    """Run a command; in JSON mode, emit one document and map failures to exit codes."""

    if not json_mode(args):
        try:
            result = handler()
        except CommandError as exc:
            raise SystemExit(exc.message) from exc
        except (AccountBindingRequired, AuthenticationRequired) as exc:
            raise SystemExit(str(exc)) from exc
        if human is not None:
            human(result)
        return result
    real_stdout = sys.stdout
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = handler()
    except KeyboardInterrupt:
        raise
    except BaseException as exc:  # noqa: BLE001 - every failure becomes one JSON document.
        if isinstance(exc, SystemExit) and exc.code in (0, None):
            result = {}
        else:
            code, message, extra = classify_exception(exc)
            write_json_document({"ok": False, "error": {"code": code, "message": message}, **extra}, real_stdout)
            raise SystemExit(EXIT_CODES[code]) from None
    write_json_document({"ok": True, **(result or {})}, real_stdout)
    return result


def load_cli_config(args: argparse.Namespace) -> dict[str, Any]:
    try:
        config = load_config(args)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise CommandError("config_invalid", tr(f"The config file is invalid: {exc}", f"配置文件无效：{exc}")) from exc
    except SystemExit as exc:
        if isinstance(exc, (OAuthClientMissing, RemindersUnavailable)):
            raise
        text = exc.code if isinstance(exc.code, str) else str(exc)
        raise CommandError("config_invalid", text) from exc
    apply_network_config(config)
    return config


# version -------------------------------------------------------------------


def cmd_version(args: argparse.Namespace) -> None:
    def handler() -> dict[str, Any]:
        return {
            "version": __version__,
            "python": ".".join(str(part) for part in sys.version_info[:3]),
            "engine_path": str(Path(__file__).resolve()),
        }

    run_cli_command(args, handler, lambda result: print(f"{PRODUCT_NAME} {result['version']}"))


# status --------------------------------------------------------------------


LEGACY_CONFIG_CANDIDATES = (
    (LEGACY_TRIAL_CONFIG_DIR_NAME, "daily-config.json"),
    (LEGACY_APP_NAME, "config.json"),
)


def legacy_config_paths() -> list[Path]:
    base = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    found = []
    for directory, name in LEGACY_CONFIG_CANDIDATES:
        candidate = base / directory / name
        if candidate.is_file():
            found.append(candidate)
    return found


def legacy_install_detected(config: dict[str, Any]) -> bool:
    if expand_path(config["_config_path"]).exists():
        return False
    return bool(legacy_config_paths())


def status_payload(config: dict[str, Any]) -> dict[str, Any]:
    snapshot = collect_management_snapshot(config)
    condition, headline, action = management_condition(snapshot)
    state = snapshot["status_state"]
    if snapshot["status_result"] == "missing":
        state = "never_synced"
    return {
        "version": __version__,
        "config_path": str(expand_path(config["_config_path"])),
        "config_exists": snapshot["config_exists"],
        "setup_completed": snapshot["setup_completed"],
        "condition": condition,
        "headline": headline,
        "action": action,
        "state": state,
        "paused": snapshot["paused"],
        "last_success_at": snapshot["last_success_at"],
        "last_start_at": snapshot["last_start_at"],
        "last_end_at": snapshot["last_end_at"],
        "updated_at": snapshot["updated_at"],
        "consecutive_failures": snapshot["failure_count"],
        "pending_destructive_counts": snapshot["pending_destructive_counts"],
        "oauth_client": snapshot["oauth_client"],
        "token_ready": snapshot["auth_material_ready"],
        "include_lists": list(config.get("include_lists") or []),
        "sync_interval_seconds": int(config["sync_interval_seconds"]),
        "effective_sync_interval_seconds": effective_scheduler_timing(config)[0],
        "loop_running": bool(snapshot["agent_loaded"]),
        "agent": {
            "installed": snapshot["launch_agent_installed"],
            "loaded": snapshot["launch_agent_loaded"],
            "label": LAUNCH_AGENT_LABEL,
        },
        "log_path": str(default_engine_log_path()),
        "legacy_install_detected": legacy_install_detected(config),
    }


def cmd_status(args: argparse.Namespace) -> None:
    if not json_mode(args):
        config = load_config(args)
        print_management_summary(config)
        return
    run_cli_command(args, lambda: status_payload(load_cli_config(args)))


# lists ---------------------------------------------------------------------


def all_reminders_lists(config: dict[str, Any]) -> list[dict[str, Any]]:
    if str(config.get("reminders_source") or "auto") == "sqlite":
        unfiltered = dict(config)
        unfiltered["include_lists"] = []
        return run_reminders_sqlite_lists_export(unfiltered)
    return run_reminders_eventkit_lists_export(config, all_lists=True)


def cmd_lists(args: argparse.Namespace) -> None:
    def handler() -> dict[str, Any]:
        config = load_cli_config(args)
        apple = [
            {
                "id": str(item.get("id") or ""),
                "title": str(item.get("title") or ""),
                "account_title": str(item.get("account_title") or ""),
                "account_id": str(item.get("account_id") or ""),
            }
            for item in all_reminders_lists(config)
            if isinstance(item, dict)
        ]
        google = None
        if getattr(args, "google", False) is True:
            client = GoogleTasksClient(config)
            google = [
                {"id": str(item.get("id") or ""), "title": str(item.get("title") or "")}
                for item in client.list_tasklists()
            ]
        return {"apple": apple, "google": google}

    def human(result: dict[str, Any]) -> None:
        print(tr("Apple Reminders lists:", "Apple 提醒事项列表："))
        for item in result["apple"]:
            print(f"  - {item['title']}  ({item['account_title']})")
        if result["google"] is not None:
            print(tr("Google Tasks lists:", "Google Tasks 列表："))
            for item in result["google"]:
                print(f"  - {item['title']}")

    run_cli_command(args, handler, human)


# config --------------------------------------------------------------------


def _expect_bool(key: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise CommandError("config_invalid", f"{key} must be true or false")
    return value


def _expect_int(key: str, value: Any, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CommandError("config_invalid", f"{key} must be an integer >= {minimum}")
    return value


def _expect_choice(key: str, value: Any, choices: set[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise CommandError("config_invalid", f"{key} must be one of: {', '.join(sorted(choices))}")
    return value


def _expect_lists(key: str, value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise CommandError("config_invalid", f"{key} must be a list of Reminders list titles")
    unique: list[str] = []
    for item in value:
        if item not in unique:
            unique.append(item)
    return unique


def _expect_ratio(key: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
        raise CommandError("config_invalid", f"{key} must be a number between 0 and 1")
    return float(value)


def _expect_list_policies(key: str, value: Any) -> dict[str, Any]:
    try:
        normalize_list_policies(value)
    except SystemExit as exc:
        raise CommandError("config_invalid", str(exc.code)) from exc
    return dict(value or {})


def _expect_proxy(key: str, value: Any) -> str:
    if not isinstance(value, str):
        raise CommandError("config_invalid", f"{key} must be a string")
    try:
        return normalize_proxy_setting(value)
    except SystemExit as exc:
        raise CommandError("config_invalid", str(exc.code)) from exc


def _expect_optional_text(key: str, value: Any) -> str | None:
    if value is not None and not isinstance(value, str):
        raise CommandError("config_invalid", f"{key} must be a string or null")
    return value


CONFIG_MERGE_VALIDATORS: dict[str, Callable[[str, Any], Any]] = {
    "include_lists": _expect_lists,
    "list_policies": _expect_list_policies,
    "bidirectional": _expect_bool,
    "delete_stale": _expect_bool,
    "conflict_policy": lambda key, value: _expect_choice(key, value, CONFLICT_POLICIES),
    "tasks_sync_undated": _expect_bool,
    "tasks_import_unsynced": _expect_bool,
    "tasks_create_missing_lists": _expect_bool,
    "tasks_complete_stale": _expect_bool,
    "sync_interval_seconds": lambda key, value: _expect_int(key, value, MIN_SYNC_INTERVAL_SECONDS),
    "max_destructive_changes": lambda key, value: _expect_int(key, value, 0),
    "max_destructive_ratio": _expect_ratio,
    "mutation_approval_prompt": _expect_bool,
    "macos_notifications": _expect_bool,
    "language": lambda key, value: _expect_choice(key, value, LANGUAGE_PREFERENCES),
    "proxy": _expect_proxy,
    "oauth_client": lambda key, value: _expect_choice(key, value, OAUTH_CLIENT_MODES),
    "setup_completed_at": _expect_optional_text,
    "trigger_min_interval_seconds": lambda key, value: _expect_int(key, value, 0),
}
CONFIG_VISIBLE_KEYS = tuple(CONFIG_MERGE_VALIDATORS)


def config_view(config: dict[str, Any]) -> dict[str, Any]:
    return {key: config.get(key) for key in CONFIG_VISIBLE_KEYS}


def read_config_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        document = read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise CommandError("config_invalid", tr(f"The config file is invalid: {exc}", f"配置文件无效：{exc}")) from exc
    if not isinstance(document, dict):
        raise CommandError("config_invalid", tr("The config file is not a JSON object.", "配置文件不是 JSON 对象。"))
    return document


def save_config_document(path: Path, document: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Validate a complete config document by loading it, then replace the file atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path.parent, 0o700)
    candidate = path.with_name(f".{path.name}.{os.getpid()}.candidate")
    write_json_atomic(candidate, document)
    try:
        probe = argparse.Namespace(**{**vars(args), "config": str(candidate)})
        for key in ("credentials_path", "token_path", "state_path", "status_path"):
            setattr(probe, key, None)
        loaded = load_config(probe)
    except SystemExit as exc:
        with contextlib.suppress(FileNotFoundError):
            candidate.unlink()
        text = exc.code if isinstance(exc.code, str) else str(exc)
        raise CommandError("config_invalid", text) from exc
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            candidate.unlink()
        raise
    os.replace(candidate, path)
    loaded["_config_path"] = str(path)
    return loaded


def cmd_config(args: argparse.Namespace) -> None:
    action = str(getattr(args, "config_action", "") or "show")
    path = expand_path(args.config)

    def show() -> dict[str, Any]:
        config = load_cli_config(args)
        return {"config_path": str(path), "config_exists": path.exists(), "config": config_view(config)}

    def init() -> dict[str, Any]:
        created = False
        if path.exists() and not getattr(args, "force", False) is True:
            config = load_cli_config(args)
        else:
            if path.exists():
                backup_management_files(load_cli_config(args), "config-init")
            config = save_config_document(path, product_default_config(), args)
            created = True
        return {"config_path": str(path), "created": created, "config": config_view(config)}

    def merge() -> dict[str, Any]:
        raw = sys.stdin.read()
        try:
            changes = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise CommandError("config_invalid", f"stdin is not valid JSON: {exc}") from exc
        if not isinstance(changes, dict):
            raise CommandError("config_invalid", "stdin must contain a JSON object")
        unknown = sorted(set(changes) - set(CONFIG_MERGE_VALIDATORS))
        if unknown:
            raise CommandError("config_invalid", f"Unsupported setting(s): {', '.join(unknown)}")
        document = read_config_document(path) or product_default_config()
        for key, value in changes.items():
            validated = CONFIG_MERGE_VALIDATORS[key](key, value)
            if value is None and key == "setup_completed_at":
                document.pop(key, None)
            else:
                document[key] = validated
        config = save_config_document(path, document, args)
        return {"config_path": str(path), "config_exists": True, "config": config_view(config)}

    def validate() -> dict[str, Any]:
        config = load_cli_config(args)
        return {"config_path": str(path), "valid": True, "config": config_view(config)}

    handlers = {"show": show, "init": init, "merge": merge, "validate": validate}

    def human(result: dict[str, Any]) -> None:
        print(json.dumps(result.get("config"), indent=2, ensure_ascii=False, sort_keys=True))

    run_cli_command(args, handlers[action], human)


def cmd_init_config(args: argparse.Namespace) -> None:
    path = expand_path(args.config)
    if path.exists() and not args.force:
        raise SystemExit(f"Config already exists: {path}\nUse --force to overwrite it.")
    write_json_atomic(path, product_default_config())
    print(f"Wrote config template: {path}")


# client --------------------------------------------------------------------


def masked_client_id(client_id: str) -> str:
    prefix, _separator, domain = client_id.partition("-")
    return f"{prefix[:4]}…{domain[-28:]}" if domain else f"{client_id[:4]}…"


def cmd_client(args: argparse.Namespace) -> None:
    action = str(getattr(args, "client_action", "") or "status")

    def import_client() -> dict[str, Any]:
        config = load_cli_config(args)
        source = Path(str(args.path)).expanduser()
        try:
            document = read_json(source)
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(
                "oauth_client_missing",
                tr(f"Could not read the OAuth client file: {exc}", f"无法读取 OAuth 客户端文件：{exc}"),
            ) from exc
        try:
            client = validate_oauth_client_document(document)
        except SystemExit as exc:
            raise CommandError("oauth_client_missing", str(exc.code)) from exc
        destination = expand_path(config["credentials_path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(destination.parent, 0o700)
        write_json_atomic(destination, {"installed": document["installed"]})
        path = expand_path(args.config)
        document_config = read_config_document(path) or product_default_config()
        document_config["oauth_client"] = "custom"
        save_config_document(path, document_config, args)
        return {"client_id_hint": masked_client_id(client["client_id"]), "credentials_path": str(destination)}

    def status() -> dict[str, Any]:
        return oauth_client_status(load_cli_config(args))

    def human(result: dict[str, Any]) -> None:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))

    run_cli_command(args, import_client if action == "import" else status, human)


# auth, account, signout ----------------------------------------------------


def cmd_auth(args: argparse.Namespace) -> None:
    def handler() -> dict[str, Any]:
        config = load_cli_config(args) if json_mode(args) else load_config(args)
        if not json_mode(args):
            apply_network_config(config)
        if getattr(args, "no_browser", False) is True:
            config["manual_oauth_browser"] = True
        try:
            result = run_auth_flow(config)
        except OAuthCallbackTimeout as exc:
            raise AuthenticationRequired(
                tr("Timed out waiting for the Google sign-in to finish.", "等待 Google 登录完成超时。")
            ) from exc
        write_sync_status(
            config,
            {
                "state": "auth_refreshed",
                "last_manual_auth_completed_at": utc_now_text(),
                **auto_reauth_failure_epoch_reset_updates(),
                "last_error": "",
            },
        )
        with contextlib.suppress(OSError):
            touch_private_file(sync_now_path(config))
        return result

    run_cli_command(args, handler)


def cmd_account(args: argparse.Namespace) -> None:
    def handler() -> dict[str, Any]:
        config = load_cli_config(args)
        result = check_google_connection(config)
        if result["state"] == "ok":
            return {
                "account_email": result.get("account_email") or "",
                "account_fingerprint": result.get("account_fingerprint") or "",
                "tasklist_count": int(result.get("tasklist_count") or 0),
            }
        code = "network" if result["state"] == "unavailable" else ("failed" if result["state"] == "api_error" else "auth_required")
        raise CommandError(code, str(result.get("message") or ""))

    def human(result: dict[str, Any]) -> None:
        print(google_connection_line(result))

    run_cli_command(args, handler, human)


def revoke_google_token(token: dict[str, Any]) -> bool:
    """Ask Google to revoke a token; True when it is no longer valid."""

    value = str(token.get("refresh_token") or token.get("access_token") or "")
    if not value:
        return False
    request = urllib.request.Request(
        OAUTH_REVOKE_URL,
        data=urllib.parse.urlencode({"token": value}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        # Google answers 200 with an empty body on success.
        with urllib.request.urlopen(request, timeout=30) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as exc:
        # 400 means Google no longer knows the token: it is already revoked.
        return exc.code == 400
    except TRANSIENT_NETWORK_ERRORS:
        return False


def cmd_signout(args: argparse.Namespace) -> None:
    def handler() -> dict[str, Any]:
        config = load_cli_config(args)
        token_path = expand_path(config["token_path"])
        revoked = False
        removed = False
        if token_path.is_file():
            backup_management_files(config, "signout")
            if getattr(args, "revoke", False) is True:
                with contextlib.suppress(OSError, json.JSONDecodeError):
                    revoked = revoke_google_token(read_json(token_path))
            token_path.unlink()
            removed = True
        adc_disabled = False
        if config.get("use_adc"):
            # A gcloud credential belongs to gcloud: leave the file, stop using it.
            path = expand_path(args.config)
            document = read_config_document(path)
            if document:
                document["use_adc"] = False
                save_config_document(path, document, args)
                adc_disabled = True
        write_sync_status(config, {"state": "auth_required", "last_error": "", "last_signed_out_at": utc_now_text()})
        return {"revoked": revoked, "token_removed": removed, "adc_disabled": adc_disabled}

    run_cli_command(args, handler, lambda result: print(tr("Signed out of Google.", "已退出 Google 登录。")))


# sync ----------------------------------------------------------------------


def cmd_sync(args: argparse.Namespace) -> None:
    def handler() -> dict[str, Any]:
        if json_mode(args):
            config = load_cli_config(args)
        else:
            config = load_config(args)
            apply_network_config(config)
        summary = sync_once(config, dry_run=bool(args.dry_run is True))
        return {
            "dry_run": bool(args.dry_run is True),
            "summary": summary or {},
            "plan": config.get("_last_mutation_plan") or {},
        }

    run_cli_command(args, handler)


def sync_once(config: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    with sync_lock(config, wait=True) as acquired:
        if not acquired:
            print("Another sync is already running; skipping.")
            return {}
        started = utc_now_text()
        write_sync_status(
            config,
            {
                "state": "running",
                "last_start_at": started,
                "last_error": "",
                "mutation_plan": None,
            },
        )
        try:
            summary = run_sync(config, dry_run=dry_run)
        except MutationPlanApprovalRequired:
            notify_sync_problem(
                config,
                tr(
                    "Sync paused: a large batch of deletions/completions needs your approval.",
                    "同步已暂停：有一批较多的删除/完成需要你确认。",
                ),
            )
            raise
        except AccountBindingRequired as exc:
            write_sync_status(
                config,
                {
                    "state": "account_binding_required",
                    "last_end_at": utc_now_text(),
                    "last_error": str(exc),
                },
            )
            notify_sync_problem(config, message_binding_paused())
            raise
        except AuthenticationRequired as exc:
            write_sync_status(
                config,
                {
                    "state": "auth_required",
                    "last_end_at": utc_now_text(),
                    "last_error": str(exc),
                },
            )
            notify_sync_problem(config, message_auth_required())
            raise
        except (Exception, SystemExit) as exc:
            write_sync_status(
                config,
                {
                    "state": "failed",
                    "last_end_at": utc_now_text(),
                    "last_error": str(exc.code if isinstance(exc, SystemExit) else exc),
                },
            )
            notify_sync_problem(config, message_sync_failed(exc.code if isinstance(exc, SystemExit) else exc))
            raise
        write_sync_status(
            config,
            {
                "state": "ok" if not dry_run else "dry_run_ok",
                "last_end_at": utc_now_text(),
                "last_success_at": utc_now_text(),
                **auto_reauth_failure_epoch_reset_updates(),
                "last_error": "",
            },
        )
        if not dry_run:
            notify_sync_ok(config)
        return summary


# approvals -----------------------------------------------------------------


def approvals_review_payload(config: dict[str, Any]) -> dict[str, Any]:
    plan = preview_mutation_plan(config)
    if plan is None or not mutation_plan_limit_reasons(config, plan):
        return {"pending": False, "items": [], "destructive_fingerprint": "", "destructive_count": 0}
    review = mutation_plan_review(plan)
    return {
        "pending": True,
        "destructive_fingerprint": review["destructive_fingerprint"],
        "destructive_count": review["destructive_count"],
        "population": review["population"],
        "ratio": round(float(review["destructive_ratio"]), 6),
        "items": [
            {
                "operation": str(item.get("operation") or ""),
                "label": mutation_review_label(str(item.get("operation") or "")),
                "list": str(item.get("list") or ""),
                "title": str(item.get("title") or ""),
            }
            for item in review["items"]
        ],
    }


def cmd_approvals(args: argparse.Namespace) -> None:
    action = str(getattr(args, "approvals_action", "") or "show")

    def locked(work: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        config = load_cli_config(args)
        with sync_lock(config, wait=True) as acquired:
            if not acquired:
                raise CommandError("failed", tr("Another sync is running. Try again in a moment.", "另一轮同步正在进行，请稍后再试。"))
            return work(config)

    def show() -> dict[str, Any]:
        return locked(approvals_review_payload)

    def apply(config: dict[str, Any]) -> dict[str, Any]:
        fingerprint = str(args.fingerprint or "").strip().lower()
        current = approvals_review_payload(config)
        if not current["pending"] or current["destructive_fingerprint"] != fingerprint:
            raise CommandError(
                "plan_changed",
                tr(
                    "The pending changes are different now; review them again.",
                    "待确认的更改已经变化，请重新查看。",
                ),
            )
        backup_management_files(config, "approve")
        token = mutation_plan_approval_token({"fingerprint": fingerprint})
        try:
            run_management_sync(config, destructive_approval=token)
        except MutationPlanApprovalRequired as exc:
            raise CommandError(
                "plan_changed",
                tr("The plan changed before it could be applied; nothing was applied.", "计划在执行前发生了变化，没有执行任何更改。"),
            ) from exc
        return {"applied": True, "destructive_count": current["destructive_count"]}

    def hold() -> dict[str, Any]:
        config = load_cli_config(args)
        fingerprint = str(args.fingerprint or "").strip().lower()
        if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
            raise CommandError("plan_changed", tr("That is not a valid change fingerprint.", "这不是有效的更改指纹。"))
        write_sync_status(
            config,
            {MUTATION_APPROVAL_STATUS_KEY: mutation_approval_memory(fingerprint, "hold", now=utc_now(), prompted=True)},
        )
        return {"held": True, "ask_again_in_seconds": int(config["mutation_approval_prompt_repeat_seconds"])}

    def human(result: dict[str, Any]) -> None:
        if action == "show":
            if not result.get("pending"):
                print(tr("No large change needs approval.", "没有需要确认的大批量更改。"))
                return
            print_mutation_review(
                {
                    "destructive_count": result["destructive_count"],
                    "population": result["population"],
                    "destructive_ratio": result["ratio"],
                    "items": result["items"],
                }
            )
            print("\n" + tr(
                f"To apply: ltb approvals apply {result['destructive_fingerprint']}",
                f"如需执行：ltb approvals apply {result['destructive_fingerprint']}",
            ))
        elif action == "apply":
            print(tr("Applied the reviewed changes.", "已应用你确认过的更改。"))
        else:
            print(tr("Held. Everything else keeps syncing.", "已暂缓，其余改动继续同步。"))

    handlers: dict[str, Callable[[], dict[str, Any]]] = {
        "show": show,
        "apply": lambda: locked(apply),
        "hold": hold,
    }
    run_cli_command(args, handlers[action], human)


# pause, resume, sync-now ---------------------------------------------------


def cmd_pause(args: argparse.Namespace) -> None:
    def handler() -> dict[str, Any]:
        config = load_cli_config(args)
        touch_private_file(pause_flag_path(config), "user")
        touch_private_file(sync_now_path(config))
        return {"paused": True, "loop_running": background_loop_running(config)}

    run_cli_command(args, handler, lambda result: print(tr("Sync paused.", "同步已暂停。")))


def cmd_resume(args: argparse.Namespace) -> None:
    def handler() -> dict[str, Any]:
        config = load_cli_config(args)
        with contextlib.suppress(FileNotFoundError):
            pause_flag_path(config).unlink()
        touch_private_file(sync_now_path(config))
        return {"paused": False, "loop_running": background_loop_running(config)}

    run_cli_command(args, handler, lambda result: print(tr("Sync resumed.", "同步已恢复。")))


def cmd_sync_now(args: argparse.Namespace) -> None:
    def handler() -> dict[str, Any]:
        config = load_cli_config(args)
        touch_private_file(sync_now_path(config))
        return {"requested": True, "loop_running": background_loop_running(config), "paused": sync_paused(config)}

    def human(result: dict[str, Any]) -> None:
        if result["loop_running"]:
            print(tr("A sync will start within a few seconds.", "几秒内将开始同步。"))
        else:
            print(tr(
                "Background sync is not running; open Local Tasks Bridge, or run `ltb sync`.",
                "后台同步没有运行；请打开 Local Tasks Bridge，或运行 `ltb sync`。",
            ))

    run_cli_command(args, handler, human)


# rebuild -------------------------------------------------------------------


def cmd_rebuild(args: argparse.Namespace) -> None:
    """Rebuild the sync map for the current accounts without propagating deletions.

    The recovery for `account_binding_required` once the person has confirmed
    that the Apple and Google accounts shown are the pair they want to sync.
    """

    def handler() -> dict[str, Any]:
        config = load_cli_config(args)
        if getattr(args, "dry_run", False) is True:
            with tempfile.TemporaryDirectory(prefix="ltb-rebuild-") as scratch:
                os.chmod(scratch, 0o700)
                preview = dict(config)
                preview["state_path"] = str(Path(scratch) / "state.json")
                preview["status_path"] = str(Path(scratch) / "status.json")
                result = run_management_safe_sync(preview, dry_run=True)
            return {"dry_run": True, **result}
        if getattr(args, "yes", False) is not True:
            raise CommandError(
                "failed",
                tr("Rebuilding the sync map needs confirmation (--yes).", "重建同步对应关系需要确认（--yes）。"),
            )
        snapshot = {"control_dir": str(control_dir(config))}
        held = stop_management_agent(snapshot)
        try:
            with sync_lock(config, wait=True) as acquired:
                if not acquired:
                    raise CommandError("failed", tr("Another sync is running. Try again in a moment.", "另一轮同步正在进行，请稍后再试。"))
                # Hold the lock from moving the old state until the new one
                # exists, so no regular cycle ever runs on an empty map.
                backup_dir = backup_management_files(config, "rebuild")
                archived = archive_state_for_rebuild(config, backup_dir)
                result = run_management_safe_sync(config, dry_run=False, lock_held=True)
        finally:
            if held:
                start_management_agent(snapshot)
        return {"dry_run": False, "rebuilt": True, "state_archived": archived, "backup": str(backup_dir), **result}

    def human(result: dict[str, Any]) -> None:
        if result["dry_run"]:
            print(json.dumps(result.get("plan"), indent=2, ensure_ascii=False, sort_keys=True))
        else:
            print(tr("Rebuilt the sync map. Nothing was deleted.", "已重建同步对应关系，没有删除任何内容。"))

    run_cli_command(args, handler, human)


# doctor --------------------------------------------------------------------


def doctor_checks(config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    snapshot = collect_management_snapshot(config)
    client = snapshot["oauth_client"]
    python_ok = sys.version_info >= (3, 9)
    helper_kind = ""
    with contextlib.suppress(RemindersUnavailable):
        helper_kind = "script" if resolve_reminders_helper(config, "export").suffix == ".swift" else "compiled"
    checks = [
        {"id": "config", "ok": snapshot["config_exists"], "label": tr("Configuration", "配置")},
        {
            "id": "python",
            "ok": python_ok,
            "label": tr("Python ≥ 3.9", "Python ≥ 3.9"),
            "detail": ".".join(str(part) for part in sys.version_info[:3]),
        },
        {
            "id": "reminders_helpers",
            "ok": snapshot["helpers_ready"],
            "label": tr("Reminders helpers", "提醒事项辅助程序"),
            "detail": helper_kind,
        },
        {
            "id": "oauth_client",
            "ok": client["active"] != "missing",
            "label": tr("Google OAuth client", "Google OAuth 客户端"),
            "detail": client["active"],
        },
        {"id": "google_token", "ok": snapshot["auth_material_ready"], "label": tr("Google sign-in", "Google 登录")},
        {
            "id": "background_loop",
            "ok": bool(snapshot["agent_loaded"]),
            "label": tr("Background sync running", "后台同步运行中"),
        },
        {
            "id": "login_item",
            "ok": snapshot["launch_agent_installed"],
            "label": tr("Starts at login", "登录时启动"),
        },
        {"id": "not_paused", "ok": not snapshot["paused"], "label": tr("Not paused", "未暂停")},
    ]
    return checks, snapshot


def cmd_doctor(args: argparse.Namespace) -> None:
    if json_mode(args):
        def handler() -> dict[str, Any]:
            config = load_cli_config(args)
            checks, snapshot = doctor_checks(config)
            condition, headline, action = management_condition(snapshot)
            result: dict[str, Any] = {
                "version": __version__,
                "checks": checks,
                "condition": condition,
                "headline": headline,
                "next_step": action,
                "state": snapshot["status_state"],
                "last_success_at": snapshot["last_success_at"],
                "consecutive_failures": snapshot["failure_count"],
                "last_error_recorded": bool(local_status_snapshot(config)[1].get("last_error")),
                "pending_destructive_counts": snapshot["pending_destructive_counts"],
            }
            if getattr(args, "online", False) is True:
                online = check_google_connection(config)
                result["online"] = {
                    "state": online["state"],
                    "tasklist_count": int(online.get("tasklist_count") or 0),
                    "message": online.get("message") or "",
                }
            return result

        run_cli_command(args, handler)
        return

    try:
        config = load_config(args)
    except (OSError, json.JSONDecodeError, SystemExit, TypeError, ValueError):
        print(tr("Local prerequisites:", "本机前置条件："))
        print(tr("  Configuration: invalid", "  配置：无效"))
        print(tr("Online Google checks: skipped (local read-only mode)", "在线 Google 检查：已跳过（本地只读模式）"))
        print(tr(
            "Next step: Repair the private config (or rerun the setup assistant), then run doctor again.",
            "下一步：修复私有配置（或重新运行设置向导），然后再运行 doctor。",
        ))
        return
    apply_network_config(config)

    checks, snapshot = doctor_checks(config)
    ok_text, missing_text = tr("ok", "正常"), tr("missing", "缺失")
    print(tr(f"{PRODUCT_NAME} {__version__}", f"{PRODUCT_NAME} {__version__}"))
    print(tr("Local prerequisites:", "本机前置条件："))
    for check in checks:
        detail = f" ({check['detail']})" if check.get("detail") else ""
        print(f"  {check['label']}: {ok_text if check['ok'] else missing_text}{detail}")
    agent_loaded = launch_agent_loaded()
    if agent_loaded is None:
        print(tr("  Login item loaded: unavailable here", "  登录项已加载：此环境无法确认"))
    else:
        print(tr("  Login item loaded: ", "  登录项已加载：") + (ok_text if agent_loaded else tr("not loaded", "未加载")))

    status_result, status = local_status_snapshot(config)
    raw_state = str(status.get("state") or "unknown")
    status_state = raw_state if raw_state in KNOWN_STATUS_STATES else "unknown"
    print(tr("Local sync status:", "本机同步状态："))
    print(tr(f"  Status file: {status_result}", f"  状态文件：{status_result}"))
    if status_result == "available":
        print(tr(f"  State: {status_state}", f"  状态：{status_state}"))
        print(tr(f"  Updated: {safe_status_time(status.get('updated_at'))}", f"  更新时间：{safe_status_time(status.get('updated_at'))}"))
        print(tr(
            f"  Last successful sync: {safe_status_time(status.get('last_success_at'))}",
            f"  最近成功同步：{safe_status_time(status.get('last_success_at'))}",
        ))
        try:
            failure_count = max(0, int(status.get("consecutive_failures") or 0))
        except (TypeError, ValueError):
            failure_count = 0
        print(tr(f"  Consecutive failures: {failure_count}", f"  连续失败次数：{failure_count}"))
        pending = pending_destructive_counts(status)
        if pending:
            print(
                tr("  Pending destructive changes: ", "  待确认的删除/完成：")
                + ", ".join(f"{key}={count}" for key, count in pending.items())
            )
        if status.get("last_error"):
            print(tr(
                "  Last sync error: recorded; details hidden to protect credentials and local paths",
                "  最近一次同步错误：已记录；为保护凭据和本地路径，此处不显示详情",
            ))

    if getattr(args, "online", False) is True:
        run_online_doctor_checks(config)
    else:
        print(tr("Online Google checks: skipped (local read-only mode)", "在线 Google 检查：已跳过（本地只读模式）"))
        print(tr(
            "  Use doctor --online only when a Google token refresh is acceptable.",
            "  只有在允许刷新 Google 令牌时才使用 doctor --online。",
        ))

    next_step = doctor_next_step(
        config_exists=snapshot["config_exists"],
        swift_ready=snapshot["swift_ready"],
        helpers_ready=snapshot["helpers_ready"],
        runtime_ready=snapshot["runtime_ready"],
        auth_material_ready=snapshot["auth_material_ready"],
        launch_agent_installed=snapshot["launch_agent_installed"],
        agent_loaded=snapshot["agent_loaded"],
        status_result=status_result,
        status_state="paused" if snapshot["paused"] and status_state not in {
            "account_binding_required", "auth_required", "auth_timeout", "awaiting_mutation_approval",
            "blocked_mutation_plan",
        } else status_state,
    )
    print(tr(f"Next step: {next_step}", f"下一步：{next_step}"))


# migrate -------------------------------------------------------------------


MIGRATED_SETTING_KEYS = (
    "target_service",
    "reminders_source",
    "include_lists",
    "list_policies",
    "bidirectional",
    "delete_stale",
    "allow_empty_source_delete",
    "conflict_policy",
    "tasks_mirror_lists",
    "tasks_mirror_empty_lists",
    "tasks_create_missing_lists",
    "tasks_complete_stale",
    "tasks_import_unsynced",
    "tasks_sync_undated",
    "tasks_list_id",
    "tasks_list_title",
    "calendar_id",
    "lookahead_days",
    "sync_interval_seconds",
    "max_destructive_changes",
    "max_destructive_ratio",
    "destructive_approval_ttl_seconds",
    "auto_approve_destructive_loops",
    "mutation_approval_prompt",
    "mutation_approval_prompt_repeat_seconds",
    "macos_notifications",
    "verify_title_due_after_sync",
    "verify_title_due_retry_attempts",
    "verify_title_due_retry_delay_seconds",
    "auto_reauth_browser",
    "auto_reauth_timeout_seconds",
    "manual_oauth_browser",
    "use_adc",
    "adc_credentials_path",
    "prefix_list",
    "transparency",
    "default_duration_minutes",
    "google_popup_minutes",
)
MIGRATED_FILES = (
    ("credentials", "credentials_path", "credentials.json"),
    ("token", "token_path", "token.json"),
    ("state", "state_path", "state.json"),
    ("status", "status_path", "status.json"),
)


def legacy_launch_agent_proxy(path: Path) -> str:
    try:
        payload = plistlib.loads(path.read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError):
        return ""
    environment = payload.get("EnvironmentVariables") if isinstance(payload, dict) else None
    if not isinstance(environment, dict):
        return ""
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = str(environment.get(key) or "").strip()
        if value:
            with contextlib.suppress(SystemExit):
                return normalize_proxy_setting(value)
    return ""


def stop_legacy_launch_agent(dry_run: bool, backup_dir: Path | None) -> dict[str, Any]:
    plist = legacy_launch_agent_path()
    result: dict[str, Any] = {"legacy_agent_found": plist.is_file(), "legacy_agent_stopped": False, "legacy_agent_plist_backup": ""}
    if dry_run:
        return result
    if launchctl_available():
        completed = subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}/{LEGACY_LAUNCH_AGENT_LABEL}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
        result["legacy_agent_stopped"] = completed.returncode == 0
    if plist.is_file() and backup_dir is not None:
        destination = backup_dir / plist.name
        shutil.move(str(plist), destination)
        os.chmod(destination, 0o600)
        result["legacy_agent_plist_backup"] = str(destination)
    return result


def cmd_migrate(args: argparse.Namespace) -> None:
    def handler() -> dict[str, Any]:
        target_path = expand_path(args.config)
        dry_run = getattr(args, "dry_run", False) is True
        if target_path.exists() and not getattr(args, "force", False) is True:
            raise CommandError(
                "config_invalid",
                tr(
                    f"{target_path} already exists; this Mac is already set up. Use --force to import anyway.",
                    f"{target_path} 已存在，说明这台 Mac 已经完成设置。如仍要导入，请加 --force。",
                ),
            )
        explicit = text_path_argument(args, "source")
        candidates = [Path(explicit).expanduser()] if explicit else legacy_config_paths()
        source = next((candidate for candidate in candidates if candidate.is_file()), None)
        if source is None:
            raise CommandError("config_invalid", tr("No earlier installation was found.", "没有找到旧的安装。"))
        legacy = read_config_document(source)
        if not dry_run and not json_mode(args) and getattr(args, "yes", False) is not True:
            if not management_confirm(
                args,
                tr(
                    f"Import {source} and stop the old background job?",
                    f"要导入 {source} 并停止旧的后台任务吗？",
                ),
            ):
                raise CommandError("failed", tr("Cancelled; nothing was changed.", "已取消，没有做任何更改。"))

        def legacy_file(key: str, default_name: str) -> Path:
            value = str(legacy.get(key) or "").strip()
            return Path(value).expanduser() if value else source.parent / default_name

        document = product_default_config()
        for key in MIGRATED_SETTING_KEYS:
            if key in legacy:
                document[key] = legacy[key]
        document["config_version"] = CONFIG_VERSION
        document["oauth_client"] = "auto"
        document["setup_completed_at"] = utc_now_text()
        document.pop("reminders_exporter_path", None)
        document.pop("reminders_apply_path", None)
        if not document.get("proxy"):
            document["proxy"] = legacy_launch_agent_proxy(legacy_launch_agent_path())

        target_dir = target_path.parent
        planned = []
        for name, key, default_name in MIGRATED_FILES:
            origin = legacy_file(key, default_name)
            if origin.is_file() and not origin.is_symlink():
                planned.append((name, origin, target_dir / default_name))
        if not any(name == "token" for name, _origin, _target in planned):
            print(tr(
                "Note: no Google token was found; you will be asked to sign in again.",
                "提示：没有找到 Google 令牌，之后需要重新登录。",
            ))

        result: dict[str, Any] = {
            "dry_run": dry_run,
            "migrated_from": str(source),
            "config_path": str(target_path),
            "copied": [name for name, _origin, _target in planned],
        }
        if dry_run:
            result.update(stop_legacy_launch_agent(True, None))
            return result

        target_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(target_dir, 0o700)
        backup_dir = target_dir / "backups" / f"{dt.datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')}-migrate"
        backup_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(backup_dir.parent, 0o700)
        os.chmod(backup_dir, 0o700)
        # Stop the old scheduler before copying, so its last cycle cannot
        # write the old state after the copy was taken.
        result.update(stop_legacy_launch_agent(False, backup_dir))
        for _name, origin, destination in planned:
            if destination.exists():
                shutil.copy2(destination, backup_dir / f"replaced-{destination.name}")
            shutil.copy2(origin, destination)
            os.chmod(destination, 0o600)
        save_config_document(target_path, document, args)
        result["legacy_tmp_logs_removed"] = retire_legacy_tmp_logs()
        return result

    def human(result: dict[str, Any]) -> None:
        verb = tr("Would import", "将导入") if result["dry_run"] else tr("Imported", "已导入")
        print(f"{verb}: {result['migrated_from']} → {result['config_path']}")
        print(tr(f"Files: {', '.join(result['copied']) or 'none'}", f"文件：{', '.join(result['copied']) or '无'}"))
        if result.get("legacy_agent_stopped"):
            print(tr("Stopped the old background job.", "已停止旧的后台任务。"))

    run_cli_command(args, handler, human)


# login item (LaunchAgent) --------------------------------------------------


def app_executable(app_path: Path) -> Path:
    return app_path / "Contents" / "MacOS" / "LocalTasksBridge"


def launch_agent_document(app_path: Path) -> dict[str, Any]:
    app_log = log_dir() / "app.log"
    return {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [str(app_executable(app_path)), "--background"],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "LimitLoadToSessionType": "Aqua",
        "ProcessType": "Interactive",
        "ThrottleInterval": 30,
        "StandardOutPath": str(app_log),
        "StandardErrorPath": str(app_log),
    }


def agent_status_payload() -> dict[str, Any]:
    path = launch_agent_path()
    app = app_bundle_from_launch_agent(path)
    return {
        "installed": path.is_file(),
        "loaded": launch_agent_loaded(),
        "label": LAUNCH_AGENT_LABEL,
        "plist": str(path),
        "program": str(app_executable(app)) if app else "",
    }


def install_launch_agent(app_path: Path, *, load: bool = True) -> dict[str, Any]:
    app_path = app_path.expanduser().resolve()
    executable = app_executable(app_path)
    if app_path.suffix != ".app" or not os.access(executable, os.X_OK):
        raise CommandError("failed", tr(f"Not a Local Tasks Bridge app bundle: {app_path}", f"不是 Local Tasks Bridge 应用包：{app_path}"))
    prepare_private_log(log_dir() / "app.log", DEFAULT_LOG_MAX_BYTES)
    path = launch_agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    candidate.write_bytes(plistlib.dumps(launch_agent_document(app_path)))
    os.chmod(candidate, 0o644)
    os.replace(candidate, path)
    loaded = launch_agent_loaded()
    if load and loaded is False:
        # Only when nothing is loaded yet: an app started by this job must
        # never boot itself out by reinstalling its own login item.
        completed = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            eprint(f"launchctl bootstrap failed: {completed.stderr.strip()}")
    retire_legacy_tmp_logs()
    return agent_status_payload()


def uninstall_launch_agent(*, bootout: bool) -> dict[str, Any]:
    path = launch_agent_path()
    removed = False
    if bootout and launch_agent_loaded():
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}/{LAUNCH_AGENT_LABEL}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    if path.is_file() or path.is_symlink():
        path.unlink()
        removed = True
    return {**agent_status_payload(), "removed": removed}


def called_from_app() -> bool:
    """The menu bar app marks its own engine processes; `ltb` in Terminal does not."""

    return os.environ.get("LTB_CALLER") == "app"


def cmd_agent(args: argparse.Namespace) -> None:
    action = str(getattr(args, "agent_action", "") or "status")

    def handler() -> dict[str, Any]:
        if action == "install":
            app = text_path_argument(args, "app") or os.environ.get("LTB_APP_BUNDLE") or ""
            if not app:
                bundle = app_bundle_of_engine()
                app = str(bundle) if bundle else ""
            if not app:
                raise CommandError("failed", tr("Pass --app with the path of Local Tasks Bridge.app.", "请用 --app 指定 Local Tasks Bridge.app 的路径。"))
            return install_launch_agent(Path(app), load=getattr(args, "no_load", False) is not True)
        if action == "uninstall":
            bootout = getattr(args, "bootout", False) is True or not called_from_app()
            return uninstall_launch_agent(bootout=bootout)
        return agent_status_payload()

    def human(result: dict[str, Any]) -> None:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))

    run_cli_command(args, handler, human)


# uninstall -----------------------------------------------------------------


def safe_private_directory(path: Path, expected_name: str) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    home = Path.home().resolve()
    return resolved.name == expected_name and resolved != home and home in resolved.parents


def cmd_uninstall(args: argparse.Namespace) -> None:
    def handler() -> dict[str, Any]:
        config = load_cli_config(args)
        if getattr(args, "yes", False) is not True:
            prompt = tr(
                "Remove the login item" + (", revoke Google access" if args.revoke else "")
                + (", and delete local settings, sync state and logs" if args.delete_data else "") + "?",
                "要移除登录项" + ("、撤销 Google 授权" if args.revoke else "")
                + ("，并删除本地设置、同步状态和日志" if args.delete_data else "") + "吗？",
            )
            if json_mode(args) or not management_confirm(args, prompt):
                raise CommandError("failed", tr("Uninstall needs confirmation (--yes).", "卸载需要确认（--yes）。"))
        result: dict[str, Any] = {"agent": uninstall_launch_agent(bootout=not called_from_app())}
        token_path = expand_path(config["token_path"])
        result["revoked"] = False
        if getattr(args, "revoke", False) is True and token_path.is_file():
            with contextlib.suppress(OSError, json.JSONDecodeError):
                result["revoked"] = revoke_google_token(read_json(token_path))
        result["data_deleted"] = False
        result["logs_deleted"] = False
        if getattr(args, "delete_data", False) is True:
            data_dir = control_dir(config)
            if data_dir.is_dir() and safe_private_directory(data_dir, APP_NAME):
                shutil.rmtree(data_dir)
                result["data_deleted"] = True
            logs = log_dir()
            if logs.is_dir() and safe_private_directory(logs, "LocalTasksBridge"):
                shutil.rmtree(logs)
                result["logs_deleted"] = True
        return result

    def human(result: dict[str, Any]) -> None:
        print(tr("Local Tasks Bridge was removed from login items.", "已从登录项中移除 Local Tasks Bridge。"))
        if result["revoked"]:
            print(tr("Google access was revoked.", "已撤销 Google 授权。"))
        if result["data_deleted"]:
            print(tr("Local settings and sync state were deleted.", "已删除本地设置和同步状态。"))

    run_cli_command(args, handler, human)


def add_json_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print one JSON object (for scripts and the app).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ltb",
        description=f"{PRODUCT_NAME} {__version__}: sync Apple Reminders with Google Tasks on this Mac.",
    )
    parser.add_argument(
        "--config",
        default=str(default_config_dir() / "config.json"),
        help="Path to config JSON. Default: ~/.config/local-tasks-bridge/config.json",
    )
    parser.add_argument("--language", choices=sorted(LANGUAGE_PREFERENCES), help="Message language (default: auto).")
    parser.add_argument("--version", action="version", version=f"{PRODUCT_NAME} {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    version_parser = subparsers.add_parser("version", help="Show the version.")
    add_json_option(version_parser)
    version_parser.set_defaults(func=cmd_version)

    status_parser = subparsers.add_parser("status", help="Show the sync status (local, read-only).")
    add_json_option(status_parser)
    status_parser.set_defaults(func=cmd_status)

    lists_parser = subparsers.add_parser("lists", help="List Reminders lists (and Google task lists with --google).")
    lists_parser.add_argument("--google", action="store_true", help="Also read Google Tasks lists (needs sign-in).")
    add_json_option(lists_parser)
    lists_parser.set_defaults(func=cmd_lists)

    config_parser = subparsers.add_parser("config", help="Show, create, or change settings.")
    config_actions = config_parser.add_subparsers(dest="config_action", required=True, metavar="ACTION")
    for name, help_text in (
        ("show", "Show the user-facing settings."),
        ("init", "Create config.json with the product defaults."),
        ("merge", "Merge a JSON object from stdin into config.json after validating it."),
        ("validate", "Check config.json."),
    ):
        action_parser = config_actions.add_parser(name, help=help_text)
        add_json_option(action_parser)
        if name == "init":
            action_parser.add_argument("--force", action="store_true", help="Replace an existing config (after a backup).")
    config_parser.set_defaults(func=cmd_config)

    client_parser = subparsers.add_parser("client", help="Manage the Google OAuth client.")
    client_actions = client_parser.add_subparsers(dest="client_action", required=True, metavar="ACTION")
    import_parser = client_actions.add_parser("import", help="Import your own Google Cloud \"Desktop app\" client JSON.")
    import_parser.add_argument("path")
    add_json_option(import_parser)
    client_status_parser = client_actions.add_parser("status", help="Show which OAuth client sign-in uses.")
    add_json_option(client_status_parser)
    client_parser.set_defaults(func=cmd_client)

    auth_parser = subparsers.add_parser("auth", help="Sign in to Google in the browser.")
    auth_parser.add_argument("--credentials-path")
    auth_parser.add_argument("--no-browser", action="store_true", help="Print the sign-in URL instead of opening it.")
    add_json_option(auth_parser)
    auth_parser.set_defaults(func=cmd_auth)

    account_parser = subparsers.add_parser("account", help="Check the Google account and the Tasks API (network).")
    add_json_option(account_parser)
    account_parser.set_defaults(func=cmd_account)

    signout_parser = subparsers.add_parser("signout", help="Forget the Google sign-in on this Mac.")
    signout_parser.add_argument("--revoke", action="store_true", help="Also revoke the token at Google.")
    add_json_option(signout_parser)
    signout_parser.set_defaults(func=cmd_signout)

    gcloud_login_parser = subparsers.add_parser(
        "gcloud-login",
        help="(Advanced) Authorize through gcloud Application Default Credentials.",
    )
    gcloud_login_parser.add_argument("--adc-credentials-path")
    gcloud_login_parser.set_defaults(func=cmd_gcloud_login)

    init_parser = subparsers.add_parser("init-config", help="Write a starter config file (same as `config init`).")
    init_parser.add_argument("--force", action="store_true", help="Overwrite an existing config.")
    init_parser.set_defaults(func=cmd_init_config)

    export_parser = subparsers.add_parser("export", help="Print Apple Reminders as JSON.")
    add_common_sync_options(export_parser)
    export_parser.set_defaults(func=cmd_export)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check prerequisites and the last sync result without changing anything.",
    )
    doctor_parser.add_argument(
        "--online",
        action="store_true",
        help="Also refresh Google auth and check the API; this can update the local OAuth token.",
    )
    add_json_option(doctor_parser)
    doctor_parser.set_defaults(func=cmd_doctor)

    manage_parser = subparsers.add_parser(
        "manage",
        help="Diagnose and safely recover the sync from one guided Terminal menu.",
    )
    manage_parser.add_argument(
        "action",
        nargs="?",
        choices=["menu", "status", "check", "reconnect", "restart", "approve"],
        default="menu",
        help="Management action. The default opens the interactive menu.",
    )
    manage_parser.add_argument(
        "--yes",
        action="store_true",
        help="Accept management confirmations. Intended for controlled testing and recovery only.",
    )
    manage_parser.set_defaults(func=cmd_manage)

    approvals_parser = subparsers.add_parser("approvals", help="Review a large batch of deletions/completions.")
    approval_actions = approvals_parser.add_subparsers(dest="approvals_action", required=True, metavar="ACTION")
    show_parser = approval_actions.add_parser("show", help="Show what needs approval (computes a preview).")
    add_json_option(show_parser)
    for name, help_text in (
        ("apply", "Apply exactly the reviewed set of deletions/completions."),
        ("hold", "Keep them on hold; everything else keeps syncing."),
    ):
        action_parser = approval_actions.add_parser(name, help=help_text)
        action_parser.add_argument("fingerprint", help="destructive_fingerprint from `approvals show`")
        add_json_option(action_parser)
    approvals_parser.set_defaults(func=cmd_approvals)

    for name, func, help_text in (
        ("pause", cmd_pause, "Pause background sync."),
        ("resume", cmd_resume, "Resume background sync."),
        ("sync-now", cmd_sync_now, "Ask the background sync to run within a few seconds."),
    ):
        control_parser = subparsers.add_parser(name, help=help_text)
        add_json_option(control_parser)
        control_parser.set_defaults(func=func)

    migrate_parser = subparsers.add_parser("migrate", help="Import an earlier installation (trial or upstream).")
    migrate_parser.add_argument("--from", dest="source", help="Path of the old config.json to import.")
    migrate_parser.add_argument("--dry-run", action="store_true")
    migrate_parser.add_argument("--force", action="store_true", help="Import even if this Mac is already set up.")
    migrate_parser.add_argument("--yes", action="store_true")
    add_json_option(migrate_parser)
    migrate_parser.set_defaults(func=cmd_migrate)

    rebuild_parser = subparsers.add_parser(
        "rebuild",
        help="Rebuild the sync map for the current accounts (no deletions), e.g. after an account change.",
    )
    rebuild_parser.add_argument("--dry-run", action="store_true", help="Show what the rebuild would do.")
    rebuild_parser.add_argument("--yes", action="store_true")
    add_json_option(rebuild_parser)
    rebuild_parser.set_defaults(func=cmd_rebuild)

    agent_parser = subparsers.add_parser("agent", help="Manage the start-at-login item.")
    agent_actions = agent_parser.add_subparsers(dest="agent_action", required=True, metavar="ACTION")
    agent_install = agent_actions.add_parser("install", help="Start Local Tasks Bridge at login.")
    agent_install.add_argument("--app", help="Path of Local Tasks Bridge.app (default: the app running this engine).")
    agent_install.add_argument("--no-load", action="store_true", help="Write the login item without starting it now.")
    add_json_option(agent_install)
    agent_uninstall = agent_actions.add_parser("uninstall", help="Stop starting at login.")
    agent_uninstall.add_argument("--bootout", action="store_true", help="Also stop the running job now.")
    add_json_option(agent_uninstall)
    agent_status = agent_actions.add_parser("status", help="Show the login item.")
    add_json_option(agent_status)
    agent_parser.set_defaults(func=cmd_agent)

    uninstall_parser = subparsers.add_parser("uninstall", help="Remove the login item and, optionally, all local data.")
    uninstall_parser.add_argument("--revoke", action="store_true", help="Revoke the Google sign-in at Google.")
    uninstall_parser.add_argument("--delete-data", action="store_true", help="Delete settings, sync state and logs.")
    uninstall_parser.add_argument("--yes", action="store_true")
    add_json_option(uninstall_parser)
    uninstall_parser.set_defaults(func=cmd_uninstall)

    sync_parser = subparsers.add_parser("sync", help="Sync Apple Reminders to Google Tasks or Google Calendar.")
    add_common_sync_options(sync_parser)
    sync_parser.add_argument("--credentials-path")
    sync_parser.add_argument("--adc-credentials-path")
    sync_parser.add_argument("--no-adc", action="store_true")
    sync_parser.add_argument("--token-path")
    sync_parser.add_argument("--state-path")
    sync_parser.add_argument("--status-path")
    sync_parser.add_argument("--auto-reauth-min-interval-seconds", type=int)
    sync_parser.add_argument("--auto-reauth-timeout-seconds", type=int)
    sync_parser.add_argument("--auto-reauth-timeout-retry-interval-seconds", type=int)
    sync_parser.add_argument("--notify-success-min-interval-seconds", type=int)
    sync_parser.add_argument("--notify-failure-min-interval-seconds", type=int)
    sync_parser.add_argument("--no-macos-notifications", action="store_true")
    sync_parser.add_argument("--no-verify-title-due-after-sync", action="store_true")
    sync_parser.add_argument("--verify-title-due-retry-attempts", type=int)
    sync_parser.add_argument("--verify-title-due-retry-delay-seconds", type=float)
    sync_parser.add_argument("--max-destructive-changes", type=int)
    sync_parser.add_argument("--max-destructive-ratio", type=float)
    sync_parser.add_argument("--destructive-approval-ttl-seconds", type=int)
    sync_parser.add_argument("--approve-mutation-plan")
    sync_parser.add_argument("--target-service", choices=["tasks", "calendar"])
    sync_parser.add_argument("--calendar-id")
    sync_parser.add_argument("--tasks-list-id")
    sync_parser.add_argument("--tasks-list-title")
    sync_parser.add_argument("--no-tasks-mirror-lists", action="store_true")
    sync_parser.add_argument("--no-tasks-mirror-empty-lists", action="store_true")
    sync_parser.add_argument("--no-tasks-create-missing-lists", action="store_true")
    sync_parser.add_argument("--no-tasks-complete-stale", action="store_true")
    sync_parser.add_argument("--tasks-import-unsynced", action="store_true", default=None)
    sync_parser.add_argument("--no-tasks-import-unsynced", action="store_true")
    sync_parser.add_argument("--tasks-sync-undated", action="store_true", default=None)
    sync_parser.add_argument("--no-tasks-sync-undated", action="store_true")
    sync_parser.add_argument("--reminders-apply-path")
    sync_parser.add_argument("--sync-interval-seconds", type=int)
    sync_parser.add_argument("--default-duration-minutes", type=int)
    sync_parser.add_argument("--prefix-list", action="store_true", default=None)
    sync_parser.add_argument("--no-delete-stale", action="store_true")
    sync_parser.add_argument("--allow-empty-source-delete", action="store_true", default=None)
    sync_parser.add_argument("--bidirectional", action="store_true", default=None)
    sync_parser.add_argument("--conflict-policy", choices=["skip", "newer_wins"])
    sync_parser.add_argument("--busy", action="store_true", help="Make synced events block calendar availability.")
    sync_parser.add_argument(
        "--google-popup-minutes",
        action="append",
        type=int,
        help="Add a Google popup reminder this many minutes before the event. May be repeated.",
    )
    sync_parser.add_argument("--dry-run", action="store_true")
    add_json_option(sync_parser)
    sync_parser.set_defaults(func=cmd_sync)

    loop_parser = subparsers.add_parser("run-loop", help="Run sync repeatedly in the foreground.")
    add_common_sync_options(loop_parser)
    loop_parser.add_argument("--credentials-path")
    loop_parser.add_argument("--adc-credentials-path")
    loop_parser.add_argument("--no-adc", action="store_true")
    loop_parser.add_argument("--token-path")
    loop_parser.add_argument("--state-path")
    loop_parser.add_argument("--status-path")
    loop_parser.add_argument("--auto-reauth-min-interval-seconds", type=int)
    loop_parser.add_argument("--auto-reauth-timeout-seconds", type=int)
    loop_parser.add_argument("--auto-reauth-timeout-retry-interval-seconds", type=int)
    loop_parser.add_argument("--notify-success-min-interval-seconds", type=int)
    loop_parser.add_argument("--notify-failure-min-interval-seconds", type=int)
    loop_parser.add_argument("--no-macos-notifications", action="store_true")
    loop_parser.add_argument("--no-verify-title-due-after-sync", action="store_true")
    loop_parser.add_argument("--verify-title-due-retry-attempts", type=int)
    loop_parser.add_argument("--verify-title-due-retry-delay-seconds", type=float)
    loop_parser.add_argument("--max-destructive-changes", type=int)
    loop_parser.add_argument("--max-destructive-ratio", type=float)
    loop_parser.add_argument("--destructive-approval-ttl-seconds", type=int)
    loop_parser.add_argument("--approve-mutation-plan")
    loop_parser.add_argument("--target-service", choices=["tasks", "calendar"])
    loop_parser.add_argument("--calendar-id")
    loop_parser.add_argument("--tasks-list-id")
    loop_parser.add_argument("--tasks-list-title")
    loop_parser.add_argument("--no-tasks-mirror-lists", action="store_true")
    loop_parser.add_argument("--no-tasks-mirror-empty-lists", action="store_true")
    loop_parser.add_argument("--no-tasks-create-missing-lists", action="store_true")
    loop_parser.add_argument("--no-tasks-complete-stale", action="store_true")
    loop_parser.add_argument("--tasks-import-unsynced", action="store_true", default=None)
    loop_parser.add_argument("--no-tasks-import-unsynced", action="store_true")
    loop_parser.add_argument("--tasks-sync-undated", action="store_true", default=None)
    loop_parser.add_argument("--no-tasks-sync-undated", action="store_true")
    loop_parser.add_argument("--reminders-apply-path")
    loop_parser.add_argument("--sync-interval-seconds", type=int)
    loop_parser.add_argument("--default-duration-minutes", type=int)
    loop_parser.add_argument("--prefix-list", action="store_true", default=None)
    loop_parser.add_argument("--no-delete-stale", action="store_true")
    loop_parser.add_argument("--allow-empty-source-delete", action="store_true", default=None)
    loop_parser.add_argument("--bidirectional", action="store_true", default=None)
    loop_parser.add_argument("--conflict-policy", choices=["skip", "newer_wins"])
    loop_parser.add_argument("--busy", action="store_true", help="Make synced events block calendar availability.")
    loop_parser.add_argument(
        "--google-popup-minutes",
        action="append",
        type=int,
        help="Add a Google popup reminder this many minutes before the event. May be repeated.",
    )
    loop_parser.add_argument("--log-file", help="Write all output to this private, size-rotated log file.")
    loop_parser.add_argument("--log-max-bytes", type=int, default=DEFAULT_LOG_MAX_BYTES)
    loop_parser.set_defaults(func=cmd_run_loop)

    return parser


def add_common_sync_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--reminders-exporter-path")
    parser.add_argument("--reminders-source", choices=["auto", "eventkit", "sqlite"])
    parser.add_argument("--reminders-sqlite-dir")
    parser.add_argument("--lookahead-days", type=int)
    parser.add_argument(
        "--include-lists",
        "--list",
        dest="include_lists",
        action="append",
        help="Limit to a Reminders list. May be repeated.",
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
