"""Offline regression checks for completion and deletion safety."""
from __future__ import annotations

import contextlib
import io
import os
import json
import tempfile
import unittest
from unittest import mock
import urllib.parse

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

import local_tasks_bridge as sync  # noqa: E402


_TEST_HOME = tempfile.TemporaryDirectory(prefix="ltb-tests-")
# Keep every default path inside a throwaway directory: no test may touch the
# developer's real config, logs, or LaunchAgents, or call launchctl.
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


class LocalSafetyTests(unittest.TestCase):
    def test_last_completion_propagates_without_deleting_missing_items(self):
        for propagation_enabled in (True, False):
            with self.subTest(propagation_enabled=propagation_enabled), tempfile.TemporaryDirectory() as directory:
                config = sync.default_config()
                config.update(state_path=str(Path(directory) / "state.json"),
                              delete_stale=propagation_enabled, tasks_complete_stale=True,
                              allow_empty_source_delete=False, max_destructive_ratio=1.0,
                              verify_title_due_after_sync=False)
                state = {"version": 1, "events": {}, "tasks": {}}
                binding = {"version": 1, "apple": "synthetic-apple", "google": "synthetic-google"}
                sync.bind_or_validate_sync_state_accounts(state, binding)
                tasks = []
                for name in ("finished", "missing"):
                    reminder = {"stable_id": name, "title": name, "notes": "",
                                "list_title": "Trial", "list_id": "apple-list",
                                "account_id": "synthetic-account", "due_date": "2026-09-30",
                                "due_at": None, "all_day": True, "is_completed": False,
                                "modified_at": "2026-09-30T00:00:00Z", "completed_at": None}
                    uid, body, digest = sync.build_task(reminder, config)
                    task = {**body, "id": name, "status": "needsAction"}
                    tasks.append(task)
                    sync.save_task_state(state, "google-list", uid, task, digest,
                                         name, reminder, config, "Trial")
                    if name == "finished":
                        finished = {**reminder, "is_completed": True,
                                    "completed_at": "2026-09-30T01:00:00Z"}
                        finished_uid, finished_body, finished_digest = sync.build_task(finished, config)
                client = mock.Mock()
                client.complete_task.return_value = {**tasks[0], "status": "completed"}
                with contextlib.ExitStack() as stack:
                    def patch(name, **kwargs):
                        return stack.enter_context(mock.patch.object(sync, name, **kwargs))
                    patch("build_desired_tasks", return_value=([], {"Trial": {}}, 0))
                    patch("build_completed_tasks", return_value=(
                        [finished], {"Trial": {finished_uid: (finished_body, finished_digest, finished)}}, 0))
                    patch("load_state", return_value=state)
                    patch("resolve_sync_account_binding", return_value=binding)
                    patch("GoogleTasksClient", return_value=client)
                    patch("inspect_tasklists_for_desired", return_value=({"Trial": "google-list"}, []))
                    patch("list_task_snapshot", return_value=(tasks, []))
                    stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                    sync.run_tasks_sync(config)
                client.delete_task.assert_not_called()
                client.patch_task.assert_not_called()
                if propagation_enabled:
                    client.complete_task.assert_called_once_with("google-list", "finished")
                else:
                    client.complete_task.assert_not_called()

    def test_inbound_completion_is_not_deleted_using_stale_completed_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            config = sync.default_config()
            config.update(
                state_path=str(Path(directory) / "state.json"),
                bidirectional=True, delete_stale=True, tasks_complete_stale=True,
                max_destructive_ratio=1.0, verify_title_due_after_sync=False,
            )
            reminder = {
                "stable_id": "synthetic-reminder", "title": "Completion regression",
                "notes": "", "list_title": "Trial", "list_id": "apple-list",
                "account_id": "synthetic-account", "due_date": "2026-09-30",
                "due_at": None, "all_day": True, "is_completed": False,
                "modified_at": "2026-09-30T00:00:00Z", "completed_at": None,
            }
            uid, body, digest = sync.build_task(reminder, config)
            active_task = {**body, "id": "synthetic-task", "status": "needsAction"}
            completed_task = {**active_task, "status": "completed"}
            finished = {**reminder, "is_completed": True,
                        "completed_at": "2026-09-30T01:00:00Z",
                        "modified_at": "2026-09-30T01:00:00Z"}
            _, finished_body, finished_digest = sync.build_task(finished, config)
            state = {"version": 1, "events": {}, "tasks": {}}
            binding = {"version": 1, "apple": "synthetic-apple", "google": "synthetic-google"}
            sync.bind_or_validate_sync_state_accounts(state, binding)
            sync.save_task_state(state, "google-list", uid, active_task, digest,
                                 reminder["title"], reminder, config, "Trial")
            client = mock.Mock()
            with contextlib.ExitStack() as stack:
                def patch(name, **kwargs):
                    return stack.enter_context(mock.patch.object(sync, name, **kwargs))
                patch("build_desired_tasks", side_effect=[
                    ([reminder], {"Trial": {uid: (body, digest, reminder)}}, 0),
                    ([], {"Trial": {}}, 0),
                ])
                patch("build_completed_tasks", side_effect=[
                    ([], {}, 0),
                    ([finished], {"Trial": {uid: (finished_body, finished_digest, finished)}}, 0),
                ])
                patch("load_state", return_value=state)
                patch("resolve_sync_account_binding", return_value=binding)
                patch("GoogleTasksClient", return_value=client)
                patch("inspect_tasklists_for_desired", return_value=({"Trial": "google-list"}, []))
                patch("list_task_snapshot", return_value=([completed_task], []))
                patch("apply_google_task_changes_to_reminders", return_value=(1, 0, 0, set()))
                stack.enter_context(mock.patch.object(sync.time, "sleep"))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                sync.run_tasks_sync(config)
            client.delete_task.assert_not_called()
            client.patch_task.assert_not_called()
            saved = json.loads(Path(config["state_path"]).read_text())
            record = sync.task_state_record(saved, "google-list", uid)
            self.assertEqual(record["task_id"], "synthetic-task")
            self.assertTrue(record["apple_completed"])

    def test_tasks_oauth_has_no_calendar_or_cloud_scope_and_no_browser_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            config = sync.default_config()
            config.update(token_path=str(Path(directory) / "token.json"), manual_oauth_browser=True)
            server = mock.Mock(server_address=("127.0.0.1", 12345))

            def callback():
                server.oauth_result = {"state": "synthetic-state", "code": "synthetic-code"}

            server.handle_request.side_effect = callback
            output = io.StringIO()
            with mock.patch.object(sync, "load_credentials", return_value={"client_id": "example.invalid"}), \
                 mock.patch.object(sync.http.server, "HTTPServer", return_value=server) as listener, \
                 mock.patch.object(sync.secrets, "token_urlsafe", return_value="synthetic-state"), \
                 mock.patch.object(sync, "post_form", return_value={"access_token": "synthetic"}), \
                 mock.patch.object(sync, "open_auth_url") as opener, contextlib.redirect_stdout(output):
                sync.run_auth_flow(config)
            url = next(line for line in output.getvalue().splitlines() if line.startswith("https://"))
            parsed = urllib.parse.urlsplit(url)
            params = urllib.parse.parse_qs(parsed.query)
            self.assertEqual(parsed.hostname, "accounts.google.com")
            self.assertEqual(set(params["scope"][0].split()), {sync.TASKS_SCOPE, "openid", "email"})
            self.assertEqual(params["code_challenge_method"], ["S256"])
            listener.assert_called_once_with(("127.0.0.1", 0), sync.OAuthCallbackHandler)
            opener.assert_not_called()
            self.assertEqual((Path(directory) / "token.json").stat().st_mode & 0o777, 0o600)

    def test_reminders_write_helper_receives_list_boundary_as_literal_argument(self):
        config = sync.default_config()
        config["include_lists"] = ['Bridge Test $(not-a-command)']
        operations = [{"stable_id": "synthetic", "title": "synthetic title"}]
        with mock.patch.object(sync.shutil, "which", return_value="/usr/bin/swift"), \
             mock.patch.object(sync.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="[]")) as runner:
            self.assertEqual(sync.run_reminders_apply(config, operations), [])
        args, kwargs = runner.call_args
        self.assertEqual(args[0][-2:], ["--list", config["include_lists"][0]])
        self.assertFalse(kwargs.get("shell", False))
        self.assertEqual(json.loads(kwargs["input"]), operations)


if __name__ == "__main__":
    unittest.main()
