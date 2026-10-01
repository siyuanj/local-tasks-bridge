"""Tests for the product layer: language, sign-in, account binding v2, helpers,
proxy, scheduler controls, the JSON command line, migration, and the login item."""
from __future__ import annotations

import base64
import contextlib
import datetime as dt
import http.client
import io
import json
import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine" / "local_tasks_bridge.py"
sys.path.insert(0, str(ROOT / "engine"))

import local_tasks_bridge as sync  # noqa: E402

_TEST_HOME = tempfile.TemporaryDirectory(prefix="ltb-product-tests-")
os.environ.update(
    {
        "XDG_CONFIG_HOME": str(Path(_TEST_HOME.name) / "config"),
        "LTB_LOG_DIR": str(Path(_TEST_HOME.name) / "logs"),
        "LTB_LAUNCH_AGENTS_DIR": str(Path(_TEST_HOME.name) / "LaunchAgents"),
        "LTB_NO_LAUNCHCTL": "1",
        "LTB_LANG": "en",
    }
)
for _name in ("LTB_EVENT_STREAM", "LTB_BUNDLED_OAUTH_CLIENT", "LTB_REMINDERS_EXPORTER", "LTB_REMINDERS_APPLY"):
    os.environ.pop(_name, None)


def jwt(claims: dict[str, object]) -> str:
    def part(payload: dict[str, object]) -> str:
        raw = json.dumps(payload).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return f"{part({'alg': 'none'})}.{part(claims)}.signature"


def token_for(subject: str, refresh: str) -> dict[str, object]:
    return {
        "refresh_token": refresh,
        "access_token": "synthetic-access",
        "expires_at": 4_102_444_800,
        "id_token": jwt({"sub": subject, "email": f"{subject}@example.invalid"}),
    }


def isolated_config(base: Path, **overrides: object) -> dict[str, object]:
    config = sync.default_config()
    config.update(
        {
            "_config_path": str(base / "config.json"),
            "credentials_path": str(base / "credentials.json"),
            "token_path": str(base / "token.json"),
            "state_path": str(base / "state.json"),
            "status_path": str(base / "status.json"),
            "adc_credentials_path": str(base / "adc.json"),
        }
    )
    config.update(overrides)
    return config


def run_engine(home: Path, *arguments: str, stdin: str | None = None, extra_env: dict[str, str] | None = None):
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "LTB_NO_LAUNCHCTL": "1",
        "LTB_LAUNCH_AGENTS_DIR": str(home / "Library" / "LaunchAgents"),
        "LTB_LOG_DIR": str(home / "Library" / "Logs" / "LocalTasksBridge"),
        "LTB_LANG": "en",
    }
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-B", str(ENGINE), *arguments],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


# Built from code points so this file itself contains no Hangul.
HANGUL_FIRST, HANGUL_LAST = chr(0xAC00), chr(0xD7A3)


class LanguageTests(unittest.TestCase):
    def tearDown(self) -> None:
        sync.set_language("en")

    def test_detection_prefers_explicit_choice_then_environment(self) -> None:
        with mock.patch.dict(os.environ, {"LTB_LANG": "zh-Hans", "LANG": "en_US.UTF-8"}):
            self.assertEqual(sync.detect_language("auto"), "zh")
            self.assertEqual(sync.detect_language("en"), "en")
        with mock.patch.dict(os.environ, {"LTB_LANG": "", "LC_ALL": "", "LC_MESSAGES": "", "LANG": "zh_CN.UTF-8"}):
            self.assertEqual(sync.detect_language(None), "zh")
        with mock.patch.dict(os.environ, {"LTB_LANG": "ko"}):
            self.assertEqual(sync.detect_language(None), "en")

    def test_messages_switch_language(self) -> None:
        sync.set_language("zh")
        self.assertEqual(sync.tr("Hello", "你好"), "你好")
        _code, headline, _action = sync.management_condition(
            {
                "config_exists": True,
                "runtime_ready": True,
                "helpers_ready": True,
                "status_state": "ok",
                "auth_material_ready": True,
                "agent_loaded": True,
                "status_result": "available",
            }
        )
        self.assertIn("已同步", headline)
        self.assertIn("小时", sync.duration_text(7200))
        sync.set_language("en")
        self.assertEqual(sync.duration_text(7200), "2 hours")
        self.assertEqual(sync.duration_text(60), "1 minute")

    def test_repository_contains_no_korean_text(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(tracked.returncode, 0, tracked.stderr)
        offenders = []
        for name in tracked.stdout.splitlines():
            path = ROOT / name
            if not path.is_file() or path.suffix in {".png", ".icns", ".zip", ".gz", ".pdf"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if any(HANGUL_FIRST <= character <= HANGUL_LAST for character in text):
                offenders.append(name)
        self.assertEqual(offenders, [])


class RepositoryHygieneTests(unittest.TestCase):
    def tracked_files(self) -> list[str]:
        listed = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(listed.returncode, 0, listed.stderr)
        return listed.stdout.splitlines()

    def test_no_google_client_secret_or_shared_client_is_committed(self) -> None:
        names = self.tracked_files()
        self.assertFalse([name for name in names if Path(name).name == "oauth_client.json"])
        marker = "GOC" + "SPX-"
        offenders = []
        for name in names:
            path = ROOT / name
            if not path.is_file():
                continue
            try:
                if marker in path.read_text(encoding="utf-8"):
                    offenders.append(name)
            except (UnicodeDecodeError, OSError):
                continue
        self.assertEqual(offenders, [])


class EndpointOverrideTests(unittest.TestCase):
    def test_only_https_or_loopback_http_is_accepted(self) -> None:
        with mock.patch.dict(os.environ, {"LTB_TEST_URL": "https://example.invalid/api/"}):
            self.assertEqual(sync.endpoint_override("LTB_TEST_URL", "x"), "https://example.invalid/api")
        with mock.patch.dict(os.environ, {"LTB_TEST_URL": "http://127.0.0.1:8080/tasks/v1"}):
            self.assertEqual(sync.endpoint_override("LTB_TEST_URL", "x"), "http://127.0.0.1:8080/tasks/v1")
        with mock.patch.dict(os.environ, {"LTB_TEST_URL": "http://attacker.example/token"}):
            with self.assertRaises(SystemExit):
                sync.endpoint_override("LTB_TEST_URL", "x")
        with mock.patch.dict(os.environ, {"LTB_TEST_URL": ""}):
            self.assertEqual(sync.endpoint_override("LTB_TEST_URL", "default"), "default")


class OAuthClientTests(unittest.TestCase):
    installed = {"installed": {"client_id": "123-abc.apps.googleusercontent.com", "client_secret": "s"}}

    def test_only_desktop_clients_are_accepted(self) -> None:
        self.assertEqual(
            sync.validate_oauth_client_document(self.installed)["client_id"],
            "123-abc.apps.googleusercontent.com",
        )
        with self.assertRaises(SystemExit) as caught:
            sync.validate_oauth_client_document({"web": {"client_id": "x.apps.googleusercontent.com"}})
        self.assertIn("Desktop app", str(caught.exception))
        with self.assertRaises(SystemExit):
            sync.validate_oauth_client_document({"installed": {"client_id": "not-a-google-client"}})

    def test_resolution_prefers_own_client_then_bundled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            bundled = base / "bundled.json"
            bundled.write_text(json.dumps(self.installed), encoding="utf-8")
            config = isolated_config(base)
            with mock.patch.dict(os.environ, {"LTB_BUNDLED_OAUTH_CLIENT": str(bundled)}):
                self.assertEqual(sync.resolve_oauth_client(config)[0], "bundled")
                self.assertEqual(sync.oauth_client_status(config)["active"], "bundled")
                (base / "credentials.json").write_text(json.dumps(self.installed), encoding="utf-8")
                self.assertEqual(sync.resolve_oauth_client(config)[0], "custom")
                config["oauth_client"] = "bundled"
                self.assertEqual(sync.resolve_oauth_client(config)[0], "bundled")
            with mock.patch.dict(os.environ, {"LTB_BUNDLED_OAUTH_CLIENT": str(base / "missing.json")}):
                config["oauth_client"] = "bundled"
                with self.assertRaises(sync.OAuthClientMissing):
                    sync.resolve_oauth_client(config)

    def fake_auth(self, base: Path, token_response: dict[str, object]) -> dict[str, object]:
        config = isolated_config(base, manual_oauth_browser=True)
        server = mock.Mock(server_address=("127.0.0.1", 12345))

        def callback() -> None:
            server.oauth_result = {"state": "synthetic-state", "code": "synthetic-code"}

        server.handle_request.side_effect = callback
        with mock.patch.object(
            sync, "resolve_oauth_client", return_value=("custom", {"client_id": "id.apps.googleusercontent.com", "client_secret": "s"})
        ), mock.patch.object(sync.http.server, "HTTPServer", return_value=server), mock.patch.object(
            sync.secrets, "token_urlsafe", return_value="synthetic-state"
        ), mock.patch.object(sync, "post_form", return_value=dict(token_response)), contextlib.redirect_stdout(io.StringIO()):
            return sync.run_auth_flow(config)

    def test_sign_in_without_the_tasks_permission_is_rejected_and_not_saved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            with self.assertRaises(SystemExit) as caught:
                self.fake_auth(base, {"access_token": "a", "refresh_token": "r", "scope": "openid email"})
            self.assertIn("Google Tasks", str(caught.exception))
            self.assertFalse((base / "token.json").exists())

    def test_sign_in_records_client_and_account_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            result = self.fake_auth(
                base,
                {
                    "access_token": "a",
                    "refresh_token": "r",
                    "scope": f"{sync.TASKS_SCOPE} openid email",
                    "id_token": jwt({"sub": "SUBJECT-1", "email": "owner@example.invalid"}),
                },
            )
            saved = json.loads((base / "token.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["client_id"], "id.apps.googleusercontent.com")
            self.assertEqual(saved["_oauth_client_mode"], "custom")
            self.assertEqual(saved["_account_subject"], "SUBJECT-1")
            self.assertEqual(stat.S_IMODE((base / "token.json").stat().st_mode), 0o600)
            self.assertEqual(result["account_email"], "owner@example.invalid")
            self.assertNotIn("SUBJECT-1", json.dumps(result))

    def test_loopback_callback_ignores_unrelated_requests(self) -> None:
        server = sync.http.server.HTTPServer(("127.0.0.1", 0), sync.OAuthCallbackHandler)
        server.oauth_result = None
        server.timeout = 5
        port = server.server_address[1]
        try:
            responses: list[int] = []

            def request(path: str) -> None:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                connection.request("GET", path)
                responses.append(connection.getresponse().status)
                connection.close()

            for path in ("/favicon.ico", "/?unrelated=1", "/?state=abc&code=xyz"):
                worker = threading.Thread(target=request, args=(path,))
                worker.start()
                server.handle_request()
                worker.join(5)
            self.assertEqual(responses, [404, 404, 200])
            self.assertEqual(server.oauth_result, {"state": "abc", "code": "xyz"})
        finally:
            server.server_close()


class AccountBindingV2Tests(unittest.TestCase):
    def apple(self) -> str:
        return sync.sha256_text("synthetic-apple")

    def test_subject_comes_from_the_id_token(self) -> None:
        token = token_for("SUBJECT-A", "REFRESH-1")
        self.assertEqual(sync.google_account_subject(token), "SUBJECT-A")
        self.assertEqual(sync.google_account_subject({"_account_subject": "SAVED"}), "SAVED")
        self.assertEqual(sync.decode_jwt_payload("not-a-jwt"), {})
        version, value = sync.google_account_binding(token)
        self.assertEqual(version, 2)
        self.assertNotIn("SUBJECT-A", value)
        self.assertEqual(sync.google_account_binding({"refresh_token": "R"})[0], 1)

    def binding(self, token: dict[str, object]) -> dict[str, object]:
        with mock.patch.object(sync, "run_reminders_lists_export", return_value=[{"account_id": "synthetic-apple"}]), \
                mock.patch.object(sync, "load_token", return_value=token):
            return sync.resolve_sync_account_binding(sync.default_config(), [])

    def test_signing_in_again_to_the_same_account_keeps_the_state(self) -> None:
        state: dict[str, object] = {"version": 1, "events": {}, "tasks": {}}
        sync.bind_or_validate_sync_state_accounts(state, self.binding(token_for("SUBJECT-A", "REFRESH-1")))
        self.assertEqual(state["account_binding"]["version"], 2)
        self.assertNotIn("google_credential", state["account_binding"])
        state["tasks"] = {"k": {"task_id": "t"}}
        sync.bind_or_validate_sync_state_accounts(state, self.binding(token_for("SUBJECT-A", "REFRESH-2")))
        with self.assertRaises(sync.AccountBindingRequired):
            sync.bind_or_validate_sync_state_accounts(state, self.binding(token_for("SUBJECT-B", "REFRESH-3")))

    def test_version_one_state_upgrades_only_for_the_same_credential(self) -> None:
        token = token_for("SUBJECT-A", "REFRESH-1")
        legacy = {
            "version": 1,
            "events": {},
            "tasks": {"k": {"task_id": "t"}},
            "account_binding": {
                "version": 1,
                "apple": sync.apple_account_binding([{"account_id": "synthetic-apple"}]),
                "google": sync.google_credential_binding(token),
            },
        }
        upgraded = json.loads(json.dumps(legacy))
        sync.bind_or_validate_sync_state_accounts(upgraded, self.binding(token))
        self.assertEqual(upgraded["account_binding"]["version"], 2)
        self.assertEqual(upgraded["account_binding"]["google"], sync.google_subject_binding("SUBJECT-A"))
        rotated = json.loads(json.dumps(legacy))
        with self.assertRaises(sync.AccountBindingRequired):
            sync.bind_or_validate_sync_state_accounts(rotated, self.binding(token_for("SUBJECT-A", "REFRESH-NEW")))
        self.assertEqual(rotated, legacy)

    def test_token_use_is_pinned_to_the_bound_account(self) -> None:
        config = sync.default_config()
        sync.expect_google_binding(config, {"version": 2, "google": sync.google_subject_binding("SUBJECT-A")})
        sync.require_expected_google_credential_binding(config, token_for("SUBJECT-A", "ANY"))
        with self.assertRaises(sync.AccountBindingRequired):
            sync.require_expected_google_credential_binding(config, token_for("SUBJECT-B", "ANY"))
        with self.assertRaises(sync.AccountBindingRequired):
            sync.require_expected_google_credential_binding(config, {"refresh_token": "NO-ID-TOKEN"})

    def test_browser_reauth_is_allowed_for_account_bound_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            config = isolated_config(Path(tmp_name), use_adc=True)
            Path(config["state_path"]).write_text(
                json.dumps({"account_binding": {"version": 2, "apple": "a", "google": "g"}}), encoding="utf-8"
            )
            self.assertTrue(sync.local_reauth_can_satisfy_binding(config))


class RemindersHelperTests(unittest.TestCase):
    def test_configured_and_environment_paths_win_and_must_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            helper = Path(tmp_name) / "ltb-reminders-export"
            helper.write_text("#!/bin/sh\necho '[]'\n", encoding="utf-8")
            helper.chmod(0o755)
            config = sync.default_config()
            config["reminders_exporter_path"] = str(helper)
            self.assertEqual(sync.reminders_helper_command(config, "export"), [str(helper)])
            config["reminders_exporter_path"] = str(Path(tmp_name) / "missing")
            with self.assertRaises(sync.RemindersUnavailable):
                sync.resolve_reminders_helper(config, "export")
            config["reminders_exporter_path"] = ""
            with mock.patch.dict(os.environ, {"LTB_REMINDERS_EXPORTER": str(helper)}):
                self.assertEqual(sync.resolve_reminders_helper(config, "export"), helper)
            helper.chmod(0o644)
            config["reminders_exporter_path"] = str(helper)
            with self.assertRaises(sync.RemindersUnavailable):
                sync.reminders_helper_command(config, "export")

    def test_app_bundle_helper_is_found_next_to_the_engine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            bundle = Path(tmp_name) / "Local Tasks Bridge.app"
            engine_dir = bundle / "Contents" / "Resources" / "engine"
            engine_dir.mkdir(parents=True)
            helper = bundle / "Contents" / "MacOS" / "ltb-reminders-apply"
            helper.parent.mkdir(parents=True)
            helper.write_text("#!/bin/sh\n", encoding="utf-8")
            helper.chmod(0o755)
            with mock.patch.object(sync, "ENGINE_DIR", engine_dir):
                self.assertEqual(sync.resolve_reminders_helper(sync.default_config(), "apply"), helper)
                self.assertEqual(sync.app_bundle_of_engine(engine_dir), bundle.resolve())

    def test_swift_source_runs_through_swift_and_failures_explain_permissions(self) -> None:
        config = sync.default_config()
        with mock.patch.object(sync.shutil, "which", return_value="/usr/bin/swift"):
            command = sync.reminders_helper_command(config, "export")
        self.assertEqual(command[0], "swift")
        self.assertTrue(command[1].endswith("RemindersExport.swift"))
        failed = mock.Mock(returncode=1, stdout="", stderr="Reminders access was denied.")
        with mock.patch.object(sync.shutil, "which", return_value="/usr/bin/swift"), \
                mock.patch.object(sync.subprocess, "run", return_value=failed):
            with self.assertRaises(sync.RemindersUnavailable) as caught:
                sync.run_reminders_eventkit_lists_export(config, all_lists=True)
        self.assertIn("Privacy & Security", str(caught.exception))


class ProxyAndConfigTests(unittest.TestCase):
    def test_proxy_settings(self) -> None:
        self.assertEqual(sync.normalize_proxy_setting(""), "")
        self.assertEqual(sync.normalize_proxy_setting("auto"), "")
        self.assertEqual(sync.normalize_proxy_setting("None"), "none")
        self.assertEqual(sync.normalize_proxy_setting("http://127.0.0.1:7890"), "http://127.0.0.1:7890")
        for invalid in ("socks5://127.0.0.1:1080", "127.0.0.1:7890", "http://host:notaport"):
            with self.subTest(invalid=invalid), self.assertRaises(SystemExit):
                sync.normalize_proxy_setting(invalid)
        self.assertIsNone(sync.proxy_handler_for(""))
        self.assertEqual(sync.proxy_handler_for("none").proxies, {})
        self.assertEqual(
            sync.proxy_handler_for("http://127.0.0.1:7890").proxies,
            {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
        )

    def test_private_paths_default_next_to_the_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            config_path = Path(tmp_name) / "elsewhere" / "config.json"
            config_path.parent.mkdir()
            config_path.write_text(json.dumps({"language": "zh", "oauth_client": "custom"}), encoding="utf-8")
            args = sync.build_parser().parse_args(["--config", str(config_path), "status"])
            config = sync.load_config(args)
            self.assertEqual(Path(config["state_path"]), (config_path.parent / "state.json").resolve())
            self.assertEqual(Path(config["token_path"]), (config_path.parent / "token.json").resolve())
            self.assertEqual(config["reminders_exporter_path"], "")
            self.assertEqual(sync.current_language(), "zh")
            sync.set_language("en")
            config_path.write_text(json.dumps({"oauth_client": "someone-else"}), encoding="utf-8")
            with self.assertRaises(SystemExit):
                sync.load_config(args)

    def test_product_defaults_are_two_way_and_safe(self) -> None:
        defaults = sync.product_default_config()
        self.assertTrue(defaults["bidirectional"])
        self.assertTrue(defaults["delete_stale"])
        self.assertEqual(defaults["max_destructive_changes"], 25)
        self.assertEqual(defaults["auto_approve_destructive_loops"], 0)
        self.assertFalse(sync.default_config()["use_adc"])


class SchedulerControlTests(unittest.TestCase):
    def test_sync_now_and_pause_wake_the_wait(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            config = isolated_config(Path(tmp_name), trigger_min_interval_seconds=0)
            started = time.time()
            self.assertFalse(sync.loop_wake_requested(
                config, was_paused=False, cycle_started_wall=started, cycle_started_monotonic=time.monotonic()
            ))
            request = sync.sync_now_path(config)
            sync.touch_private_file(request)
            os.utime(request, (started - 30, started - 30))
            self.assertFalse(sync.loop_wake_requested(
                config, was_paused=False, cycle_started_wall=started, cycle_started_monotonic=time.monotonic()
            ))
            self.assertFalse(request.exists())
            sync.touch_private_file(request)
            os.utime(request, (started + 1, started + 1))
            self.assertTrue(sync.loop_wake_requested(
                config, was_paused=False, cycle_started_wall=started, cycle_started_monotonic=time.monotonic()
            ))
            config["trigger_min_interval_seconds"] = 3600
            self.assertFalse(sync.loop_wake_requested(
                config, was_paused=False, cycle_started_wall=started, cycle_started_monotonic=time.monotonic()
            ))
            sync.touch_private_file(sync.pause_flag_path(config), "user")
            self.assertTrue(sync.loop_wake_requested(
                config, was_paused=False, cycle_started_wall=started, cycle_started_monotonic=time.monotonic()
            ))
            self.assertFalse(sync.loop_wake_requested(
                config, was_paused=True, cycle_started_wall=started, cycle_started_monotonic=time.monotonic()
            ))

    def test_wait_returns_as_soon_as_wake_is_true(self) -> None:
        approvals = mock.Mock()
        approvals.dialog_open.return_value = False
        checks = iter([False, False, True])
        clock = iter(float(value) for value in range(100, 200))
        with mock.patch.object(sync.time, "monotonic", side_effect=lambda: next(clock)), \
                mock.patch.object(sync.time, "sleep") as sleep:
            sync.wait_for_next_cycle(60, approvals, cycle_started_at=100.0, wake=lambda: next(checks))
        self.assertEqual(sleep.call_count, 2)

    def test_only_one_loop_holds_the_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            config = isolated_config(Path(tmp_name))
            self.assertFalse(sync.background_loop_running(config))
            first = sync.acquire_loop_lock(config)
            try:
                self.assertIsNotNone(first)
                self.assertIsNone(sync.acquire_loop_lock(config))
                self.assertTrue(sync.background_loop_running(config))
            finally:
                first.close()
            self.assertFalse(sync.background_loop_running(config))

    def test_paused_loop_skips_sync_and_reports_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            config = isolated_config(Path(tmp_name), sync_interval_seconds=60)
            sync.touch_private_file(sync.pause_flag_path(config), "user")
            events: list[str] = []
            with mock.patch.object(sync, "load_config", return_value=config), \
                    mock.patch.object(sync, "run_sync", side_effect=AssertionError("paused loop must not sync")), \
                    mock.patch.object(sync, "harden_runtime_log_modes"), \
                    mock.patch.object(sync, "emit_event", side_effect=lambda name, **_fields: events.append(name)), \
                    mock.patch.object(sync, "wait_for_next_cycle", side_effect=[None, KeyboardInterrupt]), \
                    contextlib.redirect_stdout(io.StringIO()):
                sync.cmd_run_loop(mock.Mock())
            self.assertEqual(events, ["loop_started", "paused"])
            self.assertEqual(sync.read_sync_status(config)["state"], "paused")

    def test_run_loop_writes_to_a_private_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            config = isolated_config(base, sync_interval_seconds=60, macos_notifications=False)
            log_path = base / "logs" / "engine.log"
            args = argparse_namespace(log_file=str(log_path), log_max_bytes=1024)
            original = sys.stdout
            with mock.patch.object(sync, "load_config", return_value=config), \
                    mock.patch.object(sync, "run_sync", return_value={}), \
                    mock.patch.object(sync, "wait_for_next_cycle", side_effect=KeyboardInterrupt):
                sync.cmd_run_loop(args)
            self.assertIs(sys.stdout, original)
            self.assertIn("sync start", log_path.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(log_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(log_path.parent.stat().st_mode), 0o700)

    def test_external_hold_reaches_the_scheduler(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            config = isolated_config(Path(tmp_name))
            approvals = sync.MutationPlanApprovals(config)
            fingerprint = "a" * 64
            sync.write_sync_status(
                config,
                {sync.MUTATION_APPROVAL_STATUS_KEY: sync.mutation_approval_memory(fingerprint, "hold", now=sync.utc_now())},
            )
            approvals.collect()
            self.assertEqual(approvals.memory["decision"], "hold")
            self.assertFalse(approvals.should_ask(fingerprint, sync.utc_now()))

    def test_manager_hold_never_overrides_a_pause_the_person_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            config = isolated_config(Path(tmp_name))
            snapshot = {"control_dir": str(sync.control_dir(config))}
            self.assertTrue(sync.stop_management_agent(snapshot))
            self.assertTrue(sync.sync_paused(config))
            sync.start_management_agent(snapshot)
            self.assertFalse(sync.sync_paused(config))
            sync.touch_private_file(sync.pause_flag_path(config), "user")
            self.assertFalse(sync.stop_management_agent(snapshot))
            sync.start_management_agent(snapshot)
            self.assertTrue(sync.sync_paused(config))


class QuotaFriendlySchedulingTests(unittest.TestCase):
    def orchestrate(self, existing_matches: bool) -> mock.Mock:
        with tempfile.TemporaryDirectory() as directory:
            config = sync.default_config()
            config.update(
                state_path=str(Path(directory) / "state.json"),
                bidirectional=False,
                verify_title_due_after_sync=True,
                verify_title_due_retry_delay_seconds=0,
            )
            reminder = {
                "stable_id": "r1", "title": "Synthetic", "notes": "", "list_title": "Trial",
                "list_id": "apple-list", "account_id": "synthetic-account", "due_date": "2026-10-01",
                "due_at": None, "all_day": True, "is_completed": False,
                "modified_at": "2026-10-01T00:00:00Z", "completed_at": None,
            }
            uid, body, digest = sync.build_task(reminder, config)
            tasks = [{**body, "id": "t1", "status": "needsAction"}] if existing_matches else []
            client = mock.Mock()
            client.insert_task.return_value = {**body, "id": "t-new", "status": "needsAction"}
            binding = {"version": 1, "apple": "a", "google": "g"}
            with contextlib.ExitStack() as stack:
                def patch(name: str, **kwargs: object) -> mock.Mock:
                    return stack.enter_context(mock.patch.object(sync, name, **kwargs))

                patch("build_desired_tasks", return_value=([reminder], {"Trial": {uid: (body, digest, reminder)}}, 0))
                patch("build_completed_tasks", return_value=([], {}, 0))
                patch("resolve_sync_account_binding", return_value=binding)
                patch("GoogleTasksClient", return_value=client)
                patch("inspect_tasklists_for_desired", return_value=({"Trial": "google-list"}, []))
                patch("list_task_snapshot", return_value=(tasks, []))
                verify = patch("verify_google_tasks_title_due_consistency", return_value=1)
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                sync.run_tasks_sync(config)
            return verify

    def test_idle_cycles_skip_the_second_read_but_writes_are_verified(self) -> None:
        self.assertEqual(self.orchestrate(existing_matches=True).call_count, 0)
        self.assertEqual(self.orchestrate(existing_matches=False).call_count, 1)

    def test_shared_client_polls_google_at_most_every_five_minutes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            config = isolated_config(base, sync_interval_seconds=60, trigger_min_interval_seconds=10)
            (base / "token.json").write_text(json.dumps({"_oauth_client_mode": "custom"}), encoding="utf-8")
            self.assertEqual(sync.effective_scheduler_timing(config), (60, 10))
            (base / "token.json").write_text(json.dumps({"_oauth_client_mode": "bundled"}), encoding="utf-8")
            self.assertEqual(sync.effective_scheduler_timing(config), (300, 30))
            config["sync_interval_seconds"] = 900
            self.assertEqual(sync.effective_scheduler_timing(config)[0], 900)


def argparse_namespace(**values: object):
    import argparse

    return argparse.Namespace(**values)


class PrivateLogTests(unittest.TestCase):
    def test_rotation_and_symlink_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            log_path = base / "logs" / "engine.log"
            log_path.parent.mkdir()
            log_path.write_text("x" * 64, encoding="utf-8")
            stream = sync.open_private_log(log_path, 32)
            stream.write("fresh\n")
            stream.close()
            self.assertEqual(log_path.read_text(encoding="utf-8"), "fresh\n")
            rotated = log_path.with_name("engine.log.1")
            self.assertEqual(stat.S_IMODE(rotated.stat().st_mode), 0o600)
            victim = base / "victim.txt"
            victim.write_text("keep", encoding="utf-8")
            victim.chmod(0o644)
            log_path.unlink()
            log_path.symlink_to(victim)
            with self.assertRaises(SystemExit):
                sync.open_private_log(log_path, 32)
            self.assertEqual(stat.S_IMODE(victim.stat().st_mode), 0o644)
            linked_dir = base / "linked"
            linked_dir.symlink_to(base / "logs")
            with self.assertRaises(SystemExit):
                sync.prepare_private_log(linked_dir / "engine.log", 32)

    def test_only_own_regular_legacy_tmp_logs_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            base = Path(tmp_name)
            old = base / "old.out.log"
            old.write_text("CANARY", encoding="utf-8")
            (base / "old.out.log.1").write_text("CANARY", encoding="utf-8")
            link = base / "old.err.log"
            link.symlink_to(base / "elsewhere")
            with mock.patch.object(sync, "LEGACY_TMP_LOGS", (old, link)):
                removed = sync.retire_legacy_tmp_logs()
            self.assertEqual(sorted(Path(item).name for item in removed), ["old.out.log", "old.out.log.1"])
            self.assertTrue(link.is_symlink())


class EventStreamTests(unittest.TestCase):
    def test_events_go_to_stdout_only_when_the_app_asks(self) -> None:
        captured = io.StringIO()
        with mock.patch.object(sync.sys, "__stdout__", captured):
            with mock.patch.dict(os.environ, {"LTB_EVENT_STREAM": ""}):
                sync.emit_event("cycle_started")
            self.assertEqual(captured.getvalue(), "")
            with mock.patch.dict(os.environ, {"LTB_EVENT_STREAM": "stdout"}):
                sync.emit_event("cycle_finished", state="ok")
        line = captured.getvalue().strip()
        self.assertTrue(line.startswith(sync.EVENT_STREAM_PREFIX))
        payload = json.loads(line[len(sync.EVENT_STREAM_PREFIX):])
        self.assertEqual((payload["event"], payload["state"]), ("cycle_finished", "ok"))

    def test_app_hosted_notifications_never_call_osascript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            config = isolated_config(Path(tmp_name), macos_notifications=True)
            captured = io.StringIO()
            with mock.patch.dict(os.environ, {"LTB_EVENT_STREAM": "stdout"}), \
                    mock.patch.object(sync.sys, "__stdout__", captured), \
                    mock.patch.object(sync.subprocess, "run", side_effect=AssertionError("no osascript")):
                sync.REAL_SEND_NOTIFICATION(config, "Title", "Message", "last_failure_notification_at", 300)
            payload = json.loads(captured.getvalue().strip()[len(sync.EVENT_STREAM_PREFIX):])
            self.assertEqual(payload["event"], "notification")
            self.assertEqual(payload["severity"], "problem")


sync.REAL_SEND_NOTIFICATION = sync.send_macos_notification


class JsonCommandTests(unittest.TestCase):
    def run_json(self, error: BaseException) -> tuple[int, dict[str, object]]:
        stdout = io.StringIO()
        args = argparse_namespace(json=True)

        def handler() -> dict[str, object]:
            raise error

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                sync.run_cli_command(args, handler)
        return int(caught.exception.code), json.loads(stdout.getvalue())

    def test_failures_map_to_documented_exit_codes(self) -> None:
        cases = [
            (sync.MutationPlanApprovalRequired("blocked", {"destructive_count": 3}), 5, "approval_required"),
            (sync.AccountBindingRequired("changed"), 4, "account_binding_required"),
            (sync.AuthenticationRequired("expired"), 3, "auth_required"),
            (sync.RemindersUnavailable("denied"), 6, "reminders_unavailable"),
            (sync.OAuthClientMissing("none"), 8, "oauth_client_missing"),
            (urllib.error.URLError("offline"), 9, "network"),
            (sync.CommandError("plan_changed", "changed"), 10, "plan_changed"),
            (RuntimeError("boom"), 1, "failed"),
        ]
        for error, exit_code, code in cases:
            with self.subTest(code=code):
                status, payload = self.run_json(error)
                self.assertEqual(status, exit_code)
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["error"]["code"], code)
        _status, payload = self.run_json(sync.MutationPlanApprovalRequired("blocked", {"destructive_count": 3}))
        self.assertEqual(payload["plan"], {"destructive_count": 3})

    def test_progress_text_never_reaches_json_stdout(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        def handler() -> dict[str, object]:
            print("progress line")
            return {"value": 1}

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            sync.run_cli_command(argparse_namespace(json=True), handler)
        self.assertEqual(json.loads(stdout.getvalue()), {"ok": True, "value": 1})
        self.assertIn("progress line", stderr.getvalue())


class CommandLineTests(unittest.TestCase):
    def test_config_lifecycle_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            home = Path(tmp_name)
            created = run_engine(home, "config", "init", "--json")
            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertTrue(json.loads(created.stdout)["created"])
            config_path = home / ".config" / "local-tasks-bridge" / "config.json"
            self.assertEqual(stat.S_IMODE(config_path.stat().st_mode), 0o600)
            merged = run_engine(
                home, "config", "merge", "--json",
                stdin=json.dumps({"include_lists": ["My Tasks", "My Tasks"], "proxy": "none", "language": "zh"}),
            )
            self.assertEqual(merged.returncode, 0, merged.stderr)
            view = json.loads(merged.stdout)["config"]
            self.assertEqual((view["include_lists"], view["proxy"], view["language"]), (["My Tasks"], "none", "zh"))
            for bad in ({"unknown": 1}, {"delete_stale": "yes"}, {"sync_interval_seconds": 30}, {"proxy": "socks5://x:1"},
                        {"list_policies": {"Work": {"direction": "sideways"}}}):
                with self.subTest(bad=bad):
                    rejected = run_engine(home, "config", "merge", "--json", stdin=json.dumps(bad))
                    self.assertEqual(rejected.returncode, 7, rejected.stdout)
                    self.assertEqual(json.loads(rejected.stdout)["error"]["code"], "config_invalid")
            self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["include_lists"], ["My Tasks"])

    def test_status_reports_a_legacy_install_and_the_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            home = Path(tmp_name)
            legacy = home / ".config" / "reminders-task-bridge-trial"
            legacy.mkdir(parents=True)
            (legacy / "daily-config.json").write_text("{}", encoding="utf-8")
            result = run_engine(home, "status", "--json", extra_env={"LTB_LANG": "zh"})
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["legacy_install_detected"])
            self.assertEqual(payload["condition"], "setup_required")
            self.assertTrue(any(chr(0x4E00) <= character <= chr(0x9FFF) for character in payload["headline"]))

    def test_client_import_accepts_desktop_clients_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            home = Path(tmp_name)
            web = home / "web.json"
            web.write_text(json.dumps({"web": {"client_id": "x.apps.googleusercontent.com"}}), encoding="utf-8")
            rejected = run_engine(home, "client", "import", str(web), "--json")
            self.assertEqual(rejected.returncode, 8)
            desktop = home / "client_secret.json"
            desktop.write_text(json.dumps(OAuthClientTests.installed), encoding="utf-8")
            imported = run_engine(home, "client", "import", str(desktop), "--json")
            self.assertEqual(imported.returncode, 0, imported.stderr)
            self.assertNotIn("123-abc", imported.stdout)
            credentials = home / ".config" / "local-tasks-bridge" / "credentials.json"
            self.assertEqual(stat.S_IMODE(credentials.stat().st_mode), 0o600)
            status = json.loads(run_engine(home, "client", "status", "--json").stdout)
            self.assertEqual(status["active"], "custom")

    def test_pause_resume_and_sync_now_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            home = Path(tmp_name)
            config_dir = home / ".config" / "local-tasks-bridge"
            self.assertEqual(run_engine(home, "pause", "--json").returncode, 0)
            self.assertTrue((config_dir / "paused").is_file())
            self.assertTrue(json.loads(run_engine(home, "status", "--json").stdout)["paused"])
            self.assertEqual(run_engine(home, "resume", "--json").returncode, 0)
            self.assertFalse((config_dir / "paused").exists())
            self.assertTrue((config_dir / "sync-now").is_file())

    def test_login_item_plist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            home = Path(tmp_name)
            app = home / "Applications" / "Local Tasks Bridge.app"
            executable = app / "Contents" / "MacOS" / "LocalTasksBridge"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            installed = run_engine(home, "agent", "install", "--app", str(app), "--json")
            self.assertEqual(installed.returncode, 0, installed.stderr)
            plist_path = home / "Library" / "LaunchAgents" / "io.github.siyuanj.local-tasks-bridge.plist"
            document = plistlib.loads(plist_path.read_bytes())
            self.assertEqual(document["ProgramArguments"], [str(executable.resolve()), "--background"])
            self.assertEqual(document["KeepAlive"], {"SuccessfulExit": False})
            self.assertEqual(document["LimitLoadToSessionType"], "Aqua")
            self.assertTrue(document["StandardOutPath"].endswith("LocalTasksBridge/app.log"))
            not_an_app = run_engine(home, "agent", "install", "--app", str(home), "--json")
            self.assertNotEqual(not_an_app.returncode, 0)
            removed = run_engine(home, "agent", "uninstall", "--json")
            self.assertTrue(json.loads(removed.stdout)["removed"])
            self.assertFalse(plist_path.exists())

    def test_migrate_imports_the_trial_install_without_touching_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            home = Path(tmp_name)
            legacy = home / ".config" / "reminders-task-bridge-trial"
            legacy.mkdir(parents=True)
            files = {
                "credentials.json": json.dumps(OAuthClientTests.installed),
                "token.json": json.dumps(token_for("SUBJECT-A", "REFRESH-1")),
                "daily-state.json": json.dumps({"version": 1, "tasks": {"k": {"task_id": "t"}}, "events": {}}),
                "daily-status.json": json.dumps({"state": "ok"}),
            }
            for name, content in files.items():
                (legacy / name).write_text(content, encoding="utf-8")
            (legacy / "daily-config.json").write_text(
                json.dumps(
                    {
                        "include_lists": ["My Tasks"],
                        "max_destructive_changes": 1,
                        "conflict_policy": "skip",
                        "credentials_path": str(legacy / "credentials.json"),
                        "token_path": str(legacy / "token.json"),
                        "state_path": str(legacy / "daily-state.json"),
                        "status_path": str(legacy / "daily-status.json"),
                        "reminders_exporter_path": "/gone/RemindersExport.swift",
                    }
                ),
                encoding="utf-8",
            )
            agents = home / "Library" / "LaunchAgents"
            agents.mkdir(parents=True)
            (agents / "com.icloud-reminders-google-sync.plist").write_bytes(
                plistlib.dumps({"Label": "com.icloud-reminders-google-sync",
                                "EnvironmentVariables": {"HTTPS_PROXY": "http://127.0.0.1:7897"}})
            )
            before = {name: (legacy / name).read_text(encoding="utf-8") for name in files}
            preview = run_engine(home, "migrate", "--dry-run", "--json")
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertFalse((home / ".config" / "local-tasks-bridge" / "config.json").exists())
            result = run_engine(home, "migrate", "--yes", "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(sorted(payload["copied"]), ["credentials", "state", "status", "token"])
            target = home / ".config" / "local-tasks-bridge"
            config = json.loads((target / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["include_lists"], ["My Tasks"])
            self.assertEqual(config["max_destructive_changes"], 1)
            self.assertEqual(config["proxy"], "http://127.0.0.1:7897")
            self.assertNotIn("reminders_exporter_path", config)
            self.assertTrue(config["setup_completed_at"])
            self.assertEqual((target / "state.json").read_text(encoding="utf-8"), files["daily-state.json"])
            self.assertEqual(stat.S_IMODE((target / "token.json").stat().st_mode), 0o600)
            self.assertFalse((agents / "com.icloud-reminders-google-sync.plist").exists())
            self.assertTrue(payload["legacy_agent_plist_backup"])
            self.assertEqual({name: (legacy / name).read_text(encoding="utf-8") for name in files}, before)
            again = run_engine(home, "migrate", "--yes", "--json")
            self.assertEqual(again.returncode, 7)

    def test_uninstall_deletes_only_the_product_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            home = Path(tmp_name)
            run_engine(home, "config", "init", "--json")
            logs = home / "Library" / "Logs" / "LocalTasksBridge"
            logs.mkdir(parents=True)
            (logs / "engine.log").write_text("x", encoding="utf-8")
            refused = run_engine(home, "uninstall", "--delete-data", "--json")
            self.assertNotEqual(refused.returncode, 0)
            self.assertTrue((home / ".config" / "local-tasks-bridge").exists())
            done = run_engine(home, "uninstall", "--delete-data", "--yes", "--json")
            self.assertEqual(done.returncode, 0, done.stderr)
            payload = json.loads(done.stdout)
            self.assertTrue(payload["data_deleted"])
            self.assertTrue(payload["logs_deleted"])
            self.assertFalse((home / ".config" / "local-tasks-bridge").exists())
            self.assertTrue((home / ".config").exists())

    def test_version_and_help(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            result = run_engine(Path(tmp_name), "version", "--json")
            self.assertEqual(json.loads(result.stdout)["version"], sync.__version__)
            usage = run_engine(Path(tmp_name), "--help")
            self.assertEqual(usage.returncode, 0)
            for command in ("status", "approvals", "migrate", "sync-now", "agent"):
                self.assertIn(command, usage.stdout)


if __name__ == "__main__":
    unittest.main()
