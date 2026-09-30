"""Offline regression checks for the bounded local trial."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.parse

import icloud_reminders_google_sync as sync


class LocalSafetyTests(unittest.TestCase):
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
