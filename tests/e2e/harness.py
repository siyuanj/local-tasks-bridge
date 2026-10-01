"""Run the real engine CLI in a throwaway, fully local environment.

Each ``Environment`` gets its own temporary HOME and XDG_CONFIG_HOME, a fake
Google server on 127.0.0.1 (``fake_google``), fake EventKit helpers on a JSON
store (``fake_reminders``) and an environment that points every engine
endpoint override at them (docs/app-engine-contract.md, sections 3 and 6).
Nothing here reads or writes the real ~/.config, ~/Library, Reminders or
Google.

As a safety net, ``PATH`` starts with a directory of guard scripts for
commands an engine must never run in these tests (``launchctl``,
``osascript``, ``open``, ``swift`` …). A guard only records its arguments
and exits 1, so a regression such as ignoring ``LTB_NO_LAUNCHCTL`` or the
helper overrides (which would otherwise fall back to the real Swift helpers
and real Reminders) shows up as a test failure instead of touching the Mac.
After the guards, ``PATH`` is the app's ``/usr/bin:/bin``.
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import datetime as dt
import json as _json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, NamedTuple, Optional, Sequence, Tuple

from . import fake_google, fake_reminders

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = REPO_ROOT / "engine" / "local_tasks_bridge.py"
EVENT_PREFIX = "@@LTB "
# A fixed zone east of UTC: an all-day reminder's local midnight is the
# previous day in UTC, which catches dates read from the wrong field.
DEFAULT_TZ = "Asia/Shanghai"
KEEP_ENV_VARIABLE = "LTB_E2E_KEEP"


class Identity(NamedTuple):
    sub: str
    email: str


ACCOUNT_A = Identity("104857600000000000001", "alice.e2e@example.com")
ACCOUNT_B = Identity("104857600000000000002", "bob.e2e@example.com")
CLIENT_ID = "123456789012-ltbe2e.apps.googleusercontent.com"
CLIENT_SECRET = "fake-client-secret-for-tests"
SETUP_COMPLETED_AT = "2026-10-01T00:00:00+00:00"
APPLE_LIST = "My Tasks"

# docs/app-engine-contract.md, section 4.
EXIT_CODES = {
    "failed": 1,
    "usage": 2,
    "auth_required": 3,
    "account_binding_required": 4,
    "approval_required": 5,
    "reminders_unavailable": 6,
    "config_invalid": 7,
    "oauth_client_missing": 8,
    "network": 9,
    "plan_changed": 10,
}

BASE_CONFIG: Dict[str, Any] = {
    "config_version": 2,
    "target_service": "tasks",
    "reminders_source": "eventkit",
    "bidirectional": True,
    "delete_stale": True,
    "tasks_import_unsynced": True,
    "tasks_sync_undated": True,
    "include_lists": [APPLE_LIST],
    "conflict_policy": "newer_wins",
    "macos_notifications": False,
    "mutation_approval_prompt": False,
    "verify_title_due_after_sync": True,
    "verify_title_due_retry_delay_seconds": 0,
    "sync_interval_seconds": 60,
    # sync-now may start a cycle right away (the default waits 10 s after the last start).
    "trigger_min_interval_seconds": 0,
    "setup_completed_at": SETUP_COMPLETED_AT,
}

# Commands whose use in a test would reach outside the sandbox (launchd,
# AppleScript dialogs, the browser, the keychain, the real EventKit helpers).
DANGEROUS_COMMANDS = ("launchctl", "osascript", "open", "security", "gcloud", "swift", "swiftc", "xcrun")
# Harmless reads that are still recorded.
RECORDED_COMMANDS = ("defaults",)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def write_private_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def read_json(path: Path) -> Any:
    return _json.loads(path.read_text(encoding="utf-8"))


def parse_json_stdout(stdout: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """The single JSON object a ``--json`` command must print, or (None, why not)."""

    text = stdout.strip()
    if not text:
        return None, "stdout is empty"
    try:
        payload, end = _json.JSONDecoder().raw_decode(text)
    except ValueError as exc:
        return None, f"stdout does not start with a JSON object ({exc})"
    if text[end:].strip():
        return None, "stdout has more than exactly one JSON object"
    if not isinstance(payload, dict):
        return None, f"stdout is JSON but not an object ({type(payload).__name__})"
    return payload, ""


class RunResult:
    """One engine run. Unpacks as ``(returncode, payload, stdout, stderr)``."""

    __slots__ = ("returncode", "payload", "stdout", "stderr", "args", "json_error", "seconds")

    def __init__(
        self,
        returncode: int,
        payload: Optional[Dict[str, Any]],
        stdout: str,
        stderr: str,
        args: Sequence[str],
        json_error: str = "",
        seconds: float = 0.0,
    ) -> None:
        self.returncode = returncode
        self.payload = payload
        self.stdout = stdout
        self.stderr = stderr
        self.args = list(args)
        self.json_error = json_error
        self.seconds = seconds

    def __iter__(self) -> Iterator[Any]:
        return iter((self.returncode, self.payload, self.stdout, self.stderr))

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and isinstance(self.payload, dict) and self.payload.get("ok") is True

    @property
    def error_code(self) -> Optional[str]:
        error = (self.payload or {}).get("error")
        return error.get("code") if isinstance(error, dict) else None

    def describe(self, limit: int = 3000) -> str:
        def tail(text: str) -> str:
            return text if len(text) <= limit else "…" + text[-limit:]

        lines = [
            f"command: {' '.join(shlex.quote(part) for part in self.args)}",
            f"exit code: {self.returncode} ({self.seconds:.1f}s)",
        ]
        if self.json_error:
            lines.append(f"JSON: {self.json_error}")
        lines.append(f"stdout:\n{tail(self.stdout)}")
        lines.append(f"stderr:\n{tail(self.stderr)}")
        return "\n".join(lines)


class LoopProcess:
    """A background ``run-loop`` with ``LTB_EVENT_STREAM=stdout``."""

    def __init__(self, command: Sequence[str], env: Dict[str, str], cwd: Path, stderr_path: Path) -> None:
        self.command = list(command)
        self.stderr_path = stderr_path
        self._stderr = stderr_path.open("w+", encoding="utf-8")
        self.events: List[Dict[str, Any]] = []
        self.event_times: List[float] = []
        self.output: List[str] = []
        self.malformed: List[str] = []
        self._cond = threading.Condition()
        self._eof = False
        self.process = subprocess.Popen(
            self.command,
            env=env,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read, name="run-loop-reader", daemon=True)
        self._reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for raw_line in self.process.stdout:
            line = raw_line.rstrip("\n")
            with self._cond:
                if line.startswith(EVENT_PREFIX):
                    try:
                        event = _json.loads(line[len(EVENT_PREFIX):])
                    except ValueError:
                        event = None
                    if isinstance(event, dict):
                        self.events.append(event)
                        self.event_times.append(time.monotonic())
                    else:
                        self.malformed.append(line)
                else:
                    self.output.append(line)
                self._cond.notify_all()
        with self._cond:
            self._eof = True
            self._cond.notify_all()

    def event_names(self) -> List[str]:
        with self._cond:
            return [str(event.get("event")) for event in self.events]

    def wait_for(
        self,
        name: str,
        *,
        timeout: float = 10.0,
        after: int = 0,
        where: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        """Wait for event ``name`` at index >= ``after``; return (index, event)."""

        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                for index in range(after, len(self.events)):
                    event = self.events[index]
                    if event.get("event") == name and (where is None or where(event)):
                        return index, event
                if self._eof:
                    raise AssertionError(
                        f"run-loop exited (code {self.process.poll()}) before a {name!r} event.\n{self.describe()}"
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError(f"no {name!r} event within {timeout:.1f}s.\n{self.describe()}")
                self._cond.wait(remaining)

    def assert_no_event(self, name: str, *, within: float, after: int = 0) -> None:
        deadline = time.monotonic() + within
        with self._cond:
            while True:
                for event in self.events[after:]:
                    if event.get("event") == name:
                        raise AssertionError(f"unexpected {name!r} event: {event}\n{self.describe()}")
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._eof:
                    return
                self._cond.wait(remaining)

    def stop(self, sig: int = signal.SIGTERM, timeout: float = 10.0) -> int:
        """Send ``sig`` and wait for the exit; returns the exit status."""

        try:
            if self.process.poll() is None:
                self.process.send_signal(sig)
            try:
                return self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
                raise AssertionError(f"run-loop did not exit within {timeout:.0f}s of signal {sig}.\n{self.describe()}")
        finally:
            self._reader.join(timeout=5)
            self._stderr.flush()

    def kill(self) -> None:
        """Make sure the process is gone and its pipes and files are closed."""

        if self.process.poll() is None:
            self.process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.process.wait(timeout=5)
        self._reader.join(timeout=5)
        if self.process.stdout is not None:
            with contextlib.suppress(OSError, ValueError):
                self.process.stdout.close()
        with contextlib.suppress(ValueError):
            self._stderr.close()

    def stderr_text(self) -> str:
        with contextlib.suppress(ValueError):
            self._stderr.flush()
        try:
            return self.stderr_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def describe(self, limit: int = 3000) -> str:
        events = "\n".join(_json.dumps(event, sort_keys=True) for event in self.events) or "(none)"
        stderr = self.stderr_text()
        output = "\n".join(self.output)
        return (
            f"command: {' '.join(shlex.quote(part) for part in self.command)}\n"
            f"events:\n{events}\n"
            f"malformed event lines: {self.malformed or 'none'}\n"
            f"other stdout:\n{output[-limit:]}\n"
            f"stderr:\n{stderr[-limit:]}"
        )


class Environment:
    """A private HOME with the engine configured against the fakes."""

    def __init__(
        self,
        *,
        config: Optional[Dict[str, Any]] = None,
        tz: str = DEFAULT_TZ,
        install: bool = True,
        signed_in: bool = True,
        reminder_lists: Sequence[str] = (APPLE_LIST,),
        google_lists: Sequence[str] = (),
        max_page_size: Optional[int] = None,
    ) -> None:
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="ltb-e2e-")))
        self.home = self.root / "home"
        self.xdg_config_home = self.home / ".config"
        self.config_dir = self.xdg_config_home / "local-tasks-bridge"
        self.config_path = self.config_dir / "config.json"
        self.credentials_path = self.config_dir / "credentials.json"
        self.token_path = self.config_dir / "token.json"
        self.state_path = self.config_dir / "state.json"
        self.status_path = self.config_dir / "status.json"
        self.launch_agents_dir = self.home / "Library" / "LaunchAgents"
        self.log_dir = self.home / "Library" / "Logs" / "LocalTasksBridge"
        self.engine_log_path = self.log_dir / "engine.log"
        self.helpers_dir = self.root / "helpers"
        self.guard_dir = self.root / "guard-bin"
        self.guard_log = self.root / "guarded-commands.log"
        self.reminders_store_path = self.root / "reminders.json"
        self.tmp_dir = self.root / "tmp"
        self.history: List[RunResult] = []
        self._loops: List[LoopProcess] = []
        self._closed = False
        for directory in (self.home, self.xdg_config_home, self.tmp_dir):
            directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.home, 0o700)

        self.google = fake_google.FakeGoogle(max_page_size=max_page_size).start()
        try:
            self.google.register_client(CLIENT_ID, CLIENT_SECRET)
            self.google.add_account(ACCOUNT_A.sub, ACCOUNT_A.email)
            self.google.add_account(ACCOUNT_B.sub, ACCOUNT_B.email)
            for title in google_lists:
                self.google.add_list(title)
            self.reminders = fake_reminders.FakeReminders.create(self.reminders_store_path, lists=reminder_lists)
            self.helpers = fake_reminders.install_helpers(self.helpers_dir)
            self._write_guards()
            self.env = self._engine_environment(tz)
            if install:
                self.install(config=config, signed_in=signed_in)
        except BaseException:
            self.close()
            raise

    # Setup -----------------------------------------------------------------------

    def _write_guards(self) -> None:
        self.guard_dir.mkdir(parents=True, exist_ok=True)
        for name in (*DANGEROUS_COMMANDS, *RECORDED_COMMANDS):
            path = self.guard_dir / name
            path.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"{name} $*\" >> {shlex.quote(str(self.guard_log))}\n"
                "exit 1\n",
                encoding="utf-8",
            )
            os.chmod(path, 0o755)

    def _engine_environment(self, tz: str) -> Dict[str, str]:
        google = self.google
        loopback = "127.0.0.1,localhost,::1"
        return {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.xdg_config_home),
            "PATH": f"{self.guard_dir}:/usr/bin:/bin",
            "TMPDIR": str(self.tmp_dir),
            "TZ": tz,
            "LTB_LANG": "en",
            "LTB_TASKS_API": google.tasks_api_url,
            "LTB_CALENDAR_API": google.base_url + "/calendar/v3",
            "LTB_OAUTH_AUTH_URL": google.auth_url,
            "LTB_OAUTH_TOKEN_URL": google.token_url,
            "LTB_OAUTH_USERINFO_URL": google.userinfo_url,
            "LTB_OAUTH_REVOKE_URL": google.revoke_url,
            "LTB_REMINDERS_EXPORTER": str(self.helpers["export"]),
            "LTB_REMINDERS_APPLY": str(self.helpers["apply"]),
            # A path that does not exist: never pick up a shared client from the checkout.
            "LTB_BUNDLED_OAUTH_CLIENT": str(self.root / "no-bundled-oauth-client.json"),
            "LTB_NO_LAUNCHCTL": "1",
            "LTB_LAUNCH_AGENTS_DIR": str(self.launch_agents_dir),
            "LTB_LOG_DIR": str(self.log_dir),
            fake_reminders.STORE_ENV: str(self.reminders_store_path),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            # Never route 127.0.0.1 through an environment or system proxy.
            "NO_PROXY": loopback,
            "no_proxy": loopback,
        }

    def install(self, *, config: Optional[Dict[str, Any]] = None, signed_in: bool = True) -> None:
        """Write config.json, credentials.json and (signed in) token.json like a finished setup."""

        self.config_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.config_dir, 0o700)
        merged = dict(BASE_CONFIG)
        merged.update(config or {})
        write_private_json(self.config_path, merged)
        write_private_json(self.credentials_path, self.oauth_client_document())
        if signed_in:
            self.write_token(ACCOUNT_A)

    def oauth_client_document(self, *, kind: str = "installed") -> Dict[str, Any]:
        """A Google OAuth client JSON as downloaded from Google Cloud."""

        return {
            kind: {
                "client_id": CLIENT_ID,
                "project_id": "ltb-e2e",
                "auth_uri": self.google.auth_url,
                "token_uri": self.google.token_url,
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_secret": CLIENT_SECRET,
                "redirect_uris": ["http://localhost"],
            }
        }

    def mint_token(
        self,
        account: Identity = ACCOUNT_A,
        *,
        scopes: Sequence[str] = fake_google.DEFAULT_SCOPES,
        expired: bool = False,
    ) -> Dict[str, Any]:
        """A token.json document for ``account``, as the engine's sign-in writes it."""

        grant = self.google.issue_tokens(account.sub, CLIENT_ID, scopes=tuple(scopes))
        now = int(time.time())
        token = dict(grant)
        token.update(
            {
                "created_at": now,
                "expires_at": now + int(grant["expires_in"]) - 60,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "_credential_source": "local_oauth",
                "_oauth_client_mode": "custom",
                "_account_subject": account.sub,
            }
        )
        if expired:
            token["expires_at"] = now - 120
            self.google.expire_access_tokens(account.sub)
        return token

    def write_token(self, account: Identity = ACCOUNT_A, *, path: Optional[Path] = None, **options: Any) -> Dict[str, Any]:
        token = self.mint_token(account, **options)
        write_private_json(path or self.token_path, token)
        return token

    def write_config(self, **changes: Any) -> Dict[str, Any]:
        config = read_json(self.config_path)
        config.update(changes)
        write_private_json(self.config_path, config)
        return config

    # Running the engine ---------------------------------------------------------------

    def engine_command(self, *args: str, config_path: Optional[Path] = None) -> List[str]:
        return [sys.executable, "-B", str(ENGINE_PATH), "--config", str(config_path or self.config_path), *args]

    def run(
        self,
        *args: str,
        json: bool = True,
        stdin: Any = None,
        timeout: float = 60.0,
        env: Optional[Dict[str, str]] = None,
        config_path: Optional[Path] = None,
    ) -> RunResult:
        """Run one engine command. ``json`` appends ``--json`` and parses stdout."""

        arguments = list(args)
        if json and "--json" not in arguments:
            arguments.append("--json")
        if stdin is not None and not isinstance(stdin, str):
            stdin = _json.dumps(stdin)
        command = self.engine_command(*arguments, config_path=config_path)
        started = time.monotonic()
        try:
            process = subprocess.run(
                command,
                input=stdin,
                capture_output=True,
                env={**self.env, **(env or {})},
                cwd=str(self.root),
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AssertionError(f"engine command timed out after {timeout:.0f}s: {' '.join(command)}") from exc
        payload, json_error = parse_json_stdout(process.stdout) if json else (None, "")
        result = RunResult(
            process.returncode,
            payload,
            process.stdout,
            process.stderr,
            command,
            json_error,
            time.monotonic() - started,
        )
        self.history.append(result)
        return result

    def run_browserless_sign_in(
        self,
        *args: str,
        login: Optional[fake_google.LoginBehaviour] = None,
        timeout: float = 30.0,
    ) -> RunResult:
        """``auth --no-browser --json``, with the test playing the browser.

        Waits for the sign-in URL on stderr, lets the fake consent screen
        answer (``login`` picks the account, an unticked Tasks permission or a
        cancel) and delivers the redirect to the engine's loopback server.
        """

        if login is not None:
            self.google.login = login
        arguments = ["auth", "--no-browser", *args]
        if "--json" not in arguments:
            arguments.append("--json")
        command = self.engine_command(*arguments)
        started = time.monotonic()
        process = subprocess.Popen(
            command,
            env=self.env,
            cwd=str(self.root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
        )
        stderr_lines: List[str] = []
        found = threading.Event()
        url_holder: List[str] = []

        def read_stderr() -> None:
            assert process.stderr is not None
            for line in process.stderr:
                stderr_lines.append(line)
                text = line.strip()
                if not url_holder and text.startswith(self.google.auth_url + "?"):
                    url_holder.append(text)
                    found.set()

        reader = threading.Thread(target=read_stderr, daemon=True)
        reader.start()
        try:
            if not found.wait(timeout):
                raise AssertionError("the engine never printed the sign-in URL:\n" + "".join(stderr_lines))
            no_redirects = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
            try:
                no_redirects.open(url_holder[0], timeout=10)
                raise AssertionError("the fake consent screen did not redirect")
            except urllib.error.HTTPError as exc:
                if exc.code != 302:
                    raise
                location = exc.headers["Location"]
            with no_redirects.open(location, timeout=10) as response:
                response.read()
            stdout, _ = process.communicate(timeout=timeout)
        except BaseException:
            process.kill()
            process.wait(timeout=5)
            raise
        finally:
            reader.join(timeout=5)
        payload, json_error = parse_json_stdout(stdout)
        result = RunResult(
            process.returncode, payload, stdout, "".join(stderr_lines), command, json_error, time.monotonic() - started
        )
        self.history.append(result)
        return result

    def start_loop(self, *args: str, env: Optional[Dict[str, str]] = None) -> LoopProcess:
        command = self.engine_command("run-loop", *args)
        loop = LoopProcess(
            command,
            {**self.env, "LTB_EVENT_STREAM": "stdout", **(env or {})},
            self.root,
            self.root / f"run-loop-{len(self._loops) + 1}.stderr",
        )
        self._loops.append(loop)
        return loop

    # Inspection ----------------------------------------------------------------------------

    def state(self) -> Dict[str, Any]:
        return read_json(self.state_path)

    def status_file(self) -> Dict[str, Any]:
        return read_json(self.status_path)

    def guarded_invocations(self, *, dangerous_only: bool = True) -> List[str]:
        if not self.guard_log.exists():
            return []
        lines = [line for line in self.guard_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        if dangerous_only:
            lines = [line for line in lines if line.split(" ", 1)[0] in DANGEROUS_COMMANDS]
        return lines

    def apple_reminders(self, list_title: str = APPLE_LIST, *, include_completed: bool = False) -> List[Dict[str, Any]]:
        return self.reminders.reminders(list_title, include_completed=include_completed)

    def apple_titles(self, list_title: str = APPLE_LIST, *, include_completed: bool = False) -> List[str]:
        return sorted(item["title"] for item in self.apple_reminders(list_title, include_completed=include_completed))

    def google_tasks(
        self,
        list_title: str = APPLE_LIST,
        *,
        include_completed: bool = False,
        sub: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return [
            task
            for task in self.google.tasks(list_title, sub=sub)
            if include_completed or task.get("status") != "completed"
        ]

    def google_titles(self, list_title: str = APPLE_LIST, *, include_completed: bool = False) -> List[str]:
        return sorted(task["title"] for task in self.google_tasks(list_title, include_completed=include_completed))

    def apple_dues(self, list_title: str = APPLE_LIST) -> Dict[str, Optional[str]]:
        """Title -> the all-day date (or timed instant) of each active reminder."""

        return {item["title"]: item.get("due_date") or item.get("due_at") for item in self.apple_reminders(list_title)}

    def google_dues(self, list_title: str = APPLE_LIST) -> Dict[str, Optional[str]]:
        """Title -> the due date (YYYY-MM-DD) of each active task."""

        return {task["title"]: (task.get("due") or "")[:10] or None for task in self.google_tasks(list_title)}

    def text_files(self, *paths: Path) -> Dict[str, str]:
        contents = {}
        for path in paths:
            if path.is_file():
                contents[str(path)] = path.read_text(encoding="utf-8", errors="replace")
        return contents

    # Teardown -----------------------------------------------------------------------------------

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for loop in self._loops:
            loop.kill()
        with contextlib.suppress(Exception):
            self.google.stop()
        if os.environ.get(KEEP_ENV_VARIABLE):
            sys.stderr.write(f"\n[e2e] kept environment: {self.root}\n")
            return
        shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> "Environment":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def file_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def is_utc_timestamp(value: Any) -> bool:
    """An ISO 8601 UTC timestamp string (contract section 4)."""

    if not isinstance(value, str):
        return False
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == dt.timedelta(0)


WORKERS_ENV_VARIABLE = "LTB_E2E_WORKERS"


def default_workers() -> int:
    configured = os.environ.get(WORKERS_ENV_VARIABLE, "").strip()
    if configured.isdigit() and int(configured) > 0:
        return int(configured)
    return max(2, min(6, os.cpu_count() or 2))


def _iter_tests(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _iter_tests(test)
        else:
            yield test


class _RecordingResult(unittest.TestResult):
    """Collects one test's outcome so it can be replayed into the real result."""

    def __init__(self) -> None:
        super().__init__()
        self.events: List[Tuple[str, Tuple[Any, ...]]] = []

    def addSuccess(self, test: Any) -> None:  # noqa: N802 - unittest API
        self.events.append(("addSuccess", (test,)))

    def addFailure(self, test: Any, err: Any) -> None:  # noqa: N802
        self.events.append(("addFailure", (test, err)))

    def addError(self, test: Any, err: Any) -> None:  # noqa: N802
        self.events.append(("addError", (test, err)))

    def addSkip(self, test: Any, reason: str) -> None:  # noqa: N802
        self.events.append(("addSkip", (test, reason)))

    def addExpectedFailure(self, test: Any, err: Any) -> None:  # noqa: N802
        self.events.append(("addExpectedFailure", (test, err)))

    def addUnexpectedSuccess(self, test: Any) -> None:  # noqa: N802
        self.events.append(("addUnexpectedSuccess", (test,)))

    def addSubTest(self, test: Any, subtest: Any, err: Any) -> None:  # noqa: N802
        self.events.append(("addSubTest", (test, subtest, err)))

    def addDuration(self, test: Any, elapsed: float) -> None:  # noqa: N802 - Python 3.12+
        self.events.append(("addDuration", (test, elapsed)))

    def replay(self, result: unittest.TestResult, test: unittest.TestCase) -> None:
        result.startTest(test)
        for name, args in self.events:
            method = getattr(result, name, None)
            if method is not None:
                method(*args)
        result.stopTest(test)


class ConcurrentSuite(unittest.TestSuite):
    """Runs its tests on a few threads and reports each one when it finishes.

    Every e2e test owns its environment (temporary HOME, fake Google server,
    child processes), so tests can run side by side; the engine's own pauses
    (for example the second it waits after writing to Reminders) then overlap.
    Class- and module-level fixtures are not supported. Set LTB_E2E_WORKERS=1
    to run the tests one at a time.
    """

    def __init__(self, tests: Any = (), workers: Optional[int] = None) -> None:
        super().__init__(tests)
        self.workers = workers or default_workers()

    def run(self, result: unittest.TestResult, debug: bool = False) -> unittest.TestResult:  # type: ignore[override]
        tests = list(_iter_tests(self))
        if debug or self.workers <= 1 or len(tests) <= 1:
            for test in tests:
                if result.shouldStop:
                    break
                test.debug() if debug else test(result)
            return result
        lock = threading.Lock()

        def run_one(test: unittest.TestCase) -> None:
            if result.shouldStop:
                return
            recorder = _RecordingResult()
            test(recorder)
            with lock:
                recorder.replay(result, test)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="e2e") as pool:
            for future in [pool.submit(run_one, test) for test in tests]:
                future.result()
        return result


class E2ETestCase(unittest.TestCase):
    """Base class: fresh environments, contract-aware assertions, safety checks."""

    maxDiff = None

    def make_env(self, **options: Any) -> Environment:
        env = Environment(**options)
        self.addCleanup(env.close)
        # Cleanups run last-in first-out: this check runs before close().
        self.addCleanup(self._assert_sandbox_respected, env)
        return env

    def _assert_sandbox_respected(self, env: Environment) -> None:
        invocations = env.guarded_invocations()
        if invocations:
            self.fail(
                "the engine ran commands that must never run in these tests "
                "(LTB_NO_LAUNCHCTL / helper overrides / notifications off):\n" + "\n".join(invocations)
            )

    # Results

    def assert_ok(self, result: RunResult, msg: str = "") -> Dict[str, Any]:
        if result.payload is None:
            self.fail(f"{msg}\nexpected exactly one JSON object on stdout\n{result.describe()}")
        if not result.ok:
            self.fail(f"{msg}\nexpected {{'ok': true}} with exit code 0\n{result.describe()}")
        return result.payload

    def assert_error(self, result: RunResult, code: str, msg: str = "") -> Dict[str, Any]:
        expected_exit = EXIT_CODES[code]
        problems = []
        if result.payload is None:
            problems.append("stdout is not exactly one JSON object")
        else:
            if result.payload.get("ok") is not False:
                problems.append("'ok' is not false")
            error = result.payload.get("error")
            if not isinstance(error, dict):
                problems.append("no 'error' object")
            else:
                if error.get("code") != code:
                    problems.append(f"error.code is {error.get('code')!r}, expected {code!r}")
                if not isinstance(error.get("message"), str) or not error.get("message"):
                    problems.append("error.message is not a non-empty string")
        if result.returncode != expected_exit:
            problems.append(f"exit code {result.returncode}, expected {expected_exit}")
        if problems:
            self.fail(f"{msg}\n" + "; ".join(problems) + "\n" + result.describe())
        return result.payload or {}

    def sync(self, env: Environment, *args: str, msg: str = "", config_path: Optional[Path] = None) -> Dict[str, Any]:
        return self.assert_ok(env.run("sync", *args, config_path=config_path), msg or "sync failed")

    def assert_quiet_sync(self, env: Environment, msg: str = "") -> Dict[str, Any]:
        """A sync with nothing left to do (plan.total_count == 0)."""

        payload = self.sync(env, msg=msg or "follow-up sync failed")
        plan = payload.get("plan") or {}
        self.assertEqual(
            plan.get("total_count"),
            0,
            f"{msg}\nexpected a converged follow-up sync (plan.total_count 0), got {_json.dumps(plan, sort_keys=True)}",
        )
        return payload

    def assert_converged(self, env: Environment, titles: Sequence[str], *, msg: str = "") -> None:
        """Both sides show exactly ``titles`` (active items), with no duplicates."""

        expected = sorted(titles)
        self.assertEqual(env.apple_titles(), expected, f"{msg}\nApple Reminders (active) differ")
        self.assertEqual(env.google_titles(), expected, f"{msg}\nGoogle Tasks (active) differ")
