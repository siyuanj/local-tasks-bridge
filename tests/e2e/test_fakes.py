"""Unit tests for the e2e fakes and harness, independent of the engine."""
from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import fake_google, fake_reminders, harness

CLIENT_ID = "1111-fake.apps.googleusercontent.com"
CLIENT_SECRET = "fake-secret"
ALICE = ("sub-alice", "alice@example.com")
BOB = ("sub-bob", "bob@example.com")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def call(
    url: str,
    *,
    method: str = "GET",
    token: Optional[str] = None,
    body: Any = None,
    form: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Any, Dict[str, str]]:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _DIRECT.open(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else None), dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = raw
        return exc.code, payload, dict(exc.headers)


class FakeGoogleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.google = fake_google.FakeGoogle().start()
        self.addCleanup(self.google.stop)
        self.google.register_client(CLIENT_ID, CLIENT_SECRET)
        self.google.add_account(*ALICE)
        self.google.add_account(*BOB)
        self.token = self.google.issue_tokens(ALICE[0], CLIENT_ID)["access_token"]
        self.api = self.google.tasks_api_url

    def default_list_id(self, token: Optional[str] = None) -> str:
        status, payload, _ = call(f"{self.api}/users/@me/lists", token=token or self.token)
        self.assertEqual(status, 200)
        return payload["items"][0]["id"]

    def test_authorization_code_flow_checks_pkce_and_issues_an_id_token(self) -> None:
        verifier = "v" * 64
        params = {
            "client_id": CLIENT_ID,
            "redirect_uri": "http://127.0.0.1:5555/",
            "response_type": "code",
            "scope": f"{fake_google.TASKS_SCOPE} openid email",
            "state": "state-123",
            "code_challenge": fake_google.pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
        status, _payload, headers = call(self.google.auth_url, params=params)
        self.assertEqual(status, 302)
        location = urllib.parse.urlsplit(headers["Location"])
        query = dict(urllib.parse.parse_qsl(location.query))
        self.assertEqual((location.hostname, location.port, query["state"]), ("127.0.0.1", 5555, "state-123"))
        exchange = {
            "grant_type": "authorization_code",
            "code": query["code"],
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": params["redirect_uri"],
        }
        status, payload, _ = call(self.google.token_url, method="POST", form={**exchange, "code_verifier": "w" * 64})
        self.assertEqual((status, payload["error"]), (400, "invalid_grant"))
        status, payload, _ = call(self.google.token_url, method="POST", form={**exchange, "code_verifier": verifier})
        self.assertEqual(status, 200, payload)
        self.assertEqual(set(payload["scope"].split()), {fake_google.TASKS_SCOPE, "openid", "email"})
        self.assertTrue(payload["refresh_token"])
        self.assertEqual(payload["token_type"], "Bearer")
        claims = fake_google.decode_jwt_payload(payload["id_token"])
        self.assertEqual((claims["sub"], claims["email"], claims["aud"]), (ALICE[0], ALICE[1], CLIENT_ID))
        self.assertEqual(claims["iss"], fake_google.ISSUER)
        self.assertGreater(claims["exp"], claims["iat"])
        self.assertEqual(len(payload["id_token"].split(".")), 3)
        # A code works once.
        status, payload, _ = call(self.google.token_url, method="POST", form={**exchange, "code_verifier": verifier})
        self.assertEqual((status, payload["error"]), (400, "invalid_grant"))

    def test_consent_can_sign_in_another_account_untick_tasks_or_be_cancelled(self) -> None:
        params = {
            "client_id": CLIENT_ID,
            "redirect_uri": "http://127.0.0.1:5555/",
            "response_type": "code",
            "scope": f"{fake_google.TASKS_SCOPE} openid email",
            "state": "s",
        }
        self.google.login = fake_google.LoginBehaviour(sub=BOB[0], untick_tasks=True)
        _status, _payload, headers = call(self.google.auth_url, params=params)
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(headers["Location"]).query))
        self.assertNotIn(fake_google.TASKS_SCOPE, query["scope"].split())
        form = {
            "grant_type": "authorization_code",
            "code": query["code"],
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": params["redirect_uri"],
        }
        status, grant, _ = call(self.google.token_url, method="POST", form=form)
        self.assertEqual(status, 200)
        self.assertEqual(fake_google.decode_jwt_payload(grant["id_token"])["sub"], BOB[0])
        status, payload, _ = call(f"{self.api}/users/@me/lists", token=grant["access_token"])
        self.assertEqual((status, payload["error"]["status"]), (403, "PERMISSION_DENIED"))

        self.google.login = fake_google.LoginBehaviour(error="access_denied")
        _status, _payload, headers = call(self.google.auth_url, params=params)
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(headers["Location"]).query))
        self.assertEqual(query, {"state": "s", "error": "access_denied"})

    def test_refresh_grant_revocation_and_wrong_client(self) -> None:
        grant = self.google.issue_tokens(ALICE[0], CLIENT_ID)
        form = {
            "grant_type": "refresh_token",
            "refresh_token": grant["refresh_token"],
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        }
        status, refreshed, _ = call(self.google.token_url, method="POST", form=form)
        self.assertEqual(status, 200)
        self.assertNotIn("refresh_token", refreshed)
        self.assertNotEqual(refreshed["access_token"], grant["access_token"])
        self.assertEqual(fake_google.decode_jwt_payload(refreshed["id_token"])["sub"], ALICE[0])
        status, payload, _ = call(self.google.token_url, method="POST", form={**form, "client_secret": "nope"})
        self.assertEqual((status, payload["error"]), (401, "invalid_client"))

        status, payload, _ = call(self.google.revoke_url, method="POST", form={"token": grant["refresh_token"]})
        self.assertEqual(status, 200)
        status, payload, _ = call(self.google.token_url, method="POST", form=form)
        self.assertEqual((status, payload["error"]), (400, "invalid_grant"))
        status, _payload, _ = call(f"{self.api}/users/@me/lists", token=refreshed["access_token"])
        self.assertEqual(status, 401)
        status, payload, _ = call(self.google.revoke_url, method="POST", form={"token": "unknown"})
        self.assertEqual((status, payload["error"]), (400, "invalid_token"))

    def test_tasks_api_requires_a_valid_bearer_token(self) -> None:
        url = f"{self.api}/users/@me/lists"
        status, payload, headers = call(url)
        self.assertEqual((status, payload["error"]["status"]), (401, "UNAUTHENTICATED"))
        status, _payload, headers = call(url, token="ya29.unknown")
        self.assertEqual(status, 401)
        self.assertIn("invalid_token", headers.get("WWW-Authenticate", ""))
        self.assertEqual(call(url, token=self.token)[0], 200)
        self.google.expire_access_tokens()
        self.assertEqual(call(url, token=self.token)[0], 401)

    def test_userinfo_returns_the_signed_in_account(self) -> None:
        status, payload, _ = call(self.google.userinfo_url, token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"sub": ALICE[0], "email": ALICE[1], "email_verified": True})
        self.assertEqual(call(self.google.userinfo_url, token="bad")[0], 401)

    def test_task_write_semantics(self) -> None:
        list_id = self.default_list_id()
        tasks_url = f"{self.api}/lists/{list_id}/tasks"
        status, task, _ = call(
            tasks_url, method="POST", token=self.token, body={"title": "Buy milk", "due": "2026-10-05T15:30:00.000Z"}
        )
        self.assertEqual(status, 200, task)
        self.assertEqual(task["due"], "2026-10-05T00:00:00.000Z")
        self.assertEqual(task["status"], "needsAction")
        self.assertNotIn("notes", task)
        self.assertNotIn("completed", task)
        self.assertRegex(task["updated"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        task_url = f"{tasks_url}/{task['id']}"

        status, completed, _ = call(task_url, method="PATCH", token=self.token, body={"status": "completed"})
        self.assertEqual(status, 200)
        self.assertEqual(completed["status"], "completed")
        self.assertIn("completed", completed)
        self.assertGreater(completed["updated"], task["updated"])
        self.assertNotEqual(completed["etag"], task["etag"])
        status, reopened, _ = call(
            task_url, method="PATCH", token=self.token, body={"status": "needsAction", "due": None, "notes": "n"}
        )
        self.assertEqual(status, 200)
        self.assertNotIn("completed", reopened)
        self.assertNotIn("due", reopened)
        self.assertEqual(reopened["notes"], "n")

        self.assertEqual(call(task_url, method="PATCH", token=self.token, body={"colour": "red"})[0], 400)
        self.assertEqual(call(task_url, method="PATCH", token=self.token, body={"status": "done"})[0], 400)
        self.assertEqual(call(task_url, method="PATCH", token=self.token, body={"due": "2026-10-05"})[0], 400)

        status, _payload, _ = call(task_url, method="DELETE", token=self.token)
        self.assertEqual(status, 204)
        status, listing, _ = call(tasks_url, token=self.token)
        self.assertNotIn("items", listing)
        status, listing, _ = call(tasks_url, token=self.token, params={"showDeleted": "true"})
        self.assertEqual([item["deleted"] for item in listing["items"]], [True])
        status, fetched, _ = call(task_url, token=self.token)
        self.assertEqual((status, fetched["deleted"]), (200, True))
        self.assertEqual(call(f"{tasks_url}/missing", token=self.token)[0], 404)
        self.assertEqual(call(f"{self.api}/lists/missing/tasks", token=self.token)[0], 404)

    def test_listing_filters_and_paging(self) -> None:
        self.google.max_page_size = 2
        for index in range(5):
            self.google.add_task("My Tasks", f"task {index}")
        self.google.complete_task("task 0")  # first-party completion: hidden
        self.google.edit_task("task 1", status="completed")  # completed, not hidden
        list_id = self.default_list_id()
        tasks_url = f"{self.api}/lists/{list_id}/tasks"

        def titles(**params: Any) -> list:
            collected, page_token, pages = [], None, 0
            while True:
                query = dict(params, **({"pageToken": page_token} if page_token else {}))
                status, payload, _ = call(tasks_url, token=self.token, params=query)
                self.assertEqual(status, 200, payload)
                pages += 1
                collected.extend(item["title"] for item in payload.get("items", []))
                page_token = payload.get("nextPageToken")
                if not page_token:
                    return sorted(collected), pages

        self.assertEqual(titles(maxResults=100), (["task 1", "task 2", "task 3", "task 4"], 2))
        self.assertEqual(titles(maxResults=100, showHidden="true")[0], [f"task {index}" for index in range(5)])
        self.assertEqual(titles(showCompleted="false", showHidden="true")[0], ["task 2", "task 3", "task 4"])
        self.assertEqual(call(tasks_url, token=self.token, params={"pageToken": "garbage"})[0], 400)
        self.assertEqual(call(tasks_url, token=self.token, params={"showDeleted": "maybe"})[0], 400)

    def test_tasklists_can_be_listed_paged_and_created(self) -> None:
        self.google.max_page_size = 1
        status, created, _ = call(f"{self.api}/users/@me/lists", method="POST", token=self.token, body={"title": "Work"})
        self.assertEqual((status, created["title"], created["kind"]), (200, "Work", "tasks#taskList"))
        status, first, _ = call(f"{self.api}/users/@me/lists", token=self.token, params={"maxResults": 1000})
        self.assertEqual([item["title"] for item in first["items"]], ["My Tasks"])
        status, second, _ = call(
            f"{self.api}/users/@me/lists", token=self.token, params={"pageToken": first["nextPageToken"]}
        )
        self.assertEqual([item["title"] for item in second["items"]], ["Work"])
        self.assertNotIn("nextPageToken", second)
        # Accounts are separate.
        bob = self.google.issue_tokens(BOB[0], CLIENT_ID)["access_token"]
        status, listing, _ = call(f"{self.api}/users/@me/lists", token=bob)
        self.assertEqual([item["title"] for item in listing["items"]], ["My Tasks"])

    def test_faults_and_request_log(self) -> None:
        list_id = self.default_list_id()
        tasks_url = f"{self.api}/lists/{list_id}/tasks"
        self.google.inject_fault("GET", fake_google.TASKS_PATH, 503)
        self.assertEqual(call(tasks_url, token=self.token)[0], 503)
        self.assertEqual(call(tasks_url, token=self.token)[0], 200)

        self.google.inject_fault("GET", fake_google.TASKS_PATH, "drop")
        with self.assertRaises(http.client.RemoteDisconnected):
            call(tasks_url, token=self.token)

        self.google.inject_fault("POST", fake_google.TASKS_PATH, "drop_after_apply")
        with self.assertRaises(http.client.RemoteDisconnected):
            call(tasks_url, method="POST", token=self.token, body={"title": "Applied"})
        self.assertIsNotNone(self.google.find_task("Applied"))
        self.assertEqual(self.google.pending_faults(), 0)

        applied = self.google.find_task("Applied")
        self.google.inject_fault("PATCH", fake_google.TASK_PATH, fake_google.STALE_WRITE_FAULT)
        status, stale, _ = call(f"{tasks_url}/{applied['id']}", method="PATCH", token=self.token, body={"title": "New"})
        self.assertEqual((status, stale["title"]), (200, "Applied"))
        self.assertEqual(self.google.find_task("Applied")["etag"], applied["etag"])

        statuses = [entry["status"] for entry in self.google.requests("GET", fake_google.TASKS_PATH)]
        self.assertEqual(statuses, [503, 200, "dropped"])
        writes = self.google.write_requests()
        self.assertEqual([(entry["method"], entry["status"], entry["fault"]) for entry in writes],
                         [("POST", "dropped", "drop_after_apply"), ("PATCH", 200, "stale_write")])
        self.assertEqual(writes[0]["body"], {"title": "Applied"})
        self.assertEqual(writes[0]["sub"], ALICE[0])

    def test_requests_through_a_proxy_are_served_and_marked(self) -> None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": self.google.base_url}))
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.google.port}/tasks/v1/users/@me/lists",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        with opener.open(request, timeout=10) as response:
            self.assertEqual(response.status, 200)
        self.assertTrue(self.google.requests("GET", fake_google.TASKLISTS_PATH)[-1]["via_proxy"])

    def test_user_side_helpers(self) -> None:
        task = self.google.add_task("My Tasks", "Call mom", due="2026-10-05", notes="soon")
        self.assertEqual((task["due"], task["notes"]), ("2026-10-05T00:00:00.000Z", "soon"))
        edited = self.google.edit_task("Call mom", title="Call mum", due=None)
        self.assertNotIn("due", edited)
        self.assertGreater(edited["updated"], task["updated"])
        completed = self.google.complete_task("Call mum")
        self.assertEqual((completed["status"], completed["hidden"]), ("completed", True))
        self.google.delete_task("Call mum")
        self.assertIsNone(self.google.find_task("Call mum"))
        self.assertTrue(self.google.find_task("Call mum", include_deleted=True)["deleted"])
        self.google.add_task("My Tasks", "Twin")
        self.google.add_task("My Tasks", "Twin")
        with self.assertRaises(LookupError):
            self.google.find_task("Twin")


class FakeRemindersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="fake-reminders-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.directory, ignore_errors=True))
        self.store = fake_reminders.FakeReminders.create(self.directory / "store.json", lists=("My Tasks", "Work"))

    def export(self, *argv: str) -> list:
        code, payload, stderr = self.store.run("export", *argv)
        self.assertEqual(code, 0, stderr)
        return payload

    def test_export_filters_and_record_shape(self) -> None:
        soon = (fake_reminders.utc_now() + fake_google.dt.timedelta(days=3)).date().isoformat()
        far = (fake_reminders.utc_now() + fake_google.dt.timedelta(days=30)).date().isoformat()
        self.store.add_reminder("all-day", due_date=soon)
        self.store.add_reminder("timed", due_at="2026-10-05T15:30:00Z")
        self.store.add_reminder("alarm only", alarm_at="2026-10-06T08:00:00Z")
        self.store.add_reminder("undated")
        self.store.add_reminder("far away", due_date=far)
        self.store.add_reminder("done", due_date=soon, completed=True)
        self.store.add_reminder("work item", "Work", due_date=soon)

        default = {item["title"] for item in self.export("--list", "My Tasks", "--lookahead-days", "365")}
        self.assertEqual(default, {"all-day", "timed", "alarm only", "far away"} if far > "2026-10-06" else default)
        self.assertNotIn("undated", default)
        self.assertNotIn("done", default)
        narrow = {item["title"] for item in self.export("--list", "My Tasks", "--lookahead-days", "7", "--include-undated")}
        self.assertIn("undated", narrow)
        self.assertNotIn("far away", narrow)
        self.assertEqual([item["title"] for item in self.export("--completed-only")], ["done"])
        everything = {item["title"] for item in self.export("--include-undated")}
        self.assertIn("work item", everything)

        records = {item["title"]: item for item in self.export("--include-undated")}
        expected_keys = {
            "id", "external_id", "stable_id", "title", "notes", "list_title", "list_id", "account_title",
            "account_id", "priority", "is_completed", "is_recurring", "recurrence_count", "created_at",
            "modified_at", "completed_at", "due_at", "due_date", "all_day", "date_source",
        }
        for record in records.values():
            self.assertEqual(set(record), expected_keys)
            self.assertEqual(record["stable_id"], record["external_id"])
            self.assertRegex(record["id"], r"^[0-9A-F-]{36}$")
            self.assertRegex(record["modified_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual((records["all-day"]["due_date"], records["all-day"]["all_day"]), (soon, True))
        self.assertEqual(records["all-day"]["date_source"], "due")
        self.assertEqual(
            (records["timed"]["due_at"], records["timed"]["due_date"], records["timed"]["all_day"]),
            ("2026-10-05T15:30:00Z", None, False),
        )
        self.assertEqual((records["alarm only"]["date_source"], records["alarm only"]["due_at"]),
                         ("alarm", "2026-10-06T08:00:00Z"))
        self.assertEqual((records["undated"]["date_source"], records["undated"]["due_at"]), ("none", None))
        self.assertEqual(records["all-day"]["list_title"], "My Tasks")
        self.assertEqual(records["all-day"]["account_title"], "iCloud")

    def test_lists_only_and_unmatched_list_filter(self) -> None:
        lists = self.export("--lists-only")
        self.assertEqual([item["title"] for item in lists], ["My Tasks", "Work"])
        self.assertEqual(set(lists[0]), {"id", "title", "account_title", "account_id"})
        self.assertEqual([item["title"] for item in self.export("--lists-only", "--list", "Work")], ["Work"])
        code, payload, stderr = self.store.run("export", "--list", "Nope")
        self.assertEqual((code, payload), (1, None))
        self.assertIn("No Reminders lists matched: Nope", stderr)
        self.assertEqual(self.store.run("export", "--bogus")[0], 1)
        self.assertEqual(self.store.run("export", "--lookahead-days", "x")[0], 1)

    def test_apply_creates_in_the_right_list(self) -> None:
        work_id = self.store.list_id("Work")
        operations = [
            {"create": True, "list_id": work_id, "list_title": "My Tasks", "title": "by id", "all_day": True,
             "due_date": "2026-10-05"},
            {"create": True, "list_id": "UNKNOWN", "list_title": "My Tasks", "title": "unknown id"},
            {"create": True, "list_title": "My Tasks", "title": "by title", "notes": "n"},
            {"create": True, "list_title": "Elsewhere", "title": "no such list"},
            {"create": True, "title": "first list"},
        ]
        code, results, stderr = self.store.run("apply", stdin=operations)
        self.assertEqual(code, 0, stderr)
        self.assertEqual([item["status"] for item in results],
                         ["created", "missing_list", "created", "missing_list", "created"])
        self.assertEqual(results[1]["reason"], "list_id_not_found")
        self.assertEqual(results[3]["reason"], "list_title_not_found")
        self.assertEqual(results[0]["list_title"], "Work")
        self.assertEqual(results[4]["list_title"], "My Tasks")
        self.assertEqual(set(results[0]), {"stable_id", "id", "external_id", "status", "list_title", "list_id",
                                           "account_title", "account_id", "created_at", "modified_at"})
        created = self.store.find("by id")
        self.assertEqual((created["due_date"], created["stable_id"]), ("2026-10-05", results[0]["stable_id"]))

        self.store.add_list("Twins")
        self.store.add_list("Twins")
        code, results, _ = self.store.run("apply", stdin=[{"create": True, "list_title": "Twins", "title": "x"}])
        self.assertEqual((results[0]["status"], results[0]["reason"]), ("missing_list", "ambiguous_list_title"))

    def test_apply_updates_completes_and_deletes_by_normalized_identifier(self) -> None:
        reminder = self.store.add_reminder("Pay rent", due_date="2026-10-05", modified_at="2026-09-01T00:00:00Z")
        loose_id = reminder["external_id"].lower().replace("-", "")
        code, results, _ = self.store.run("apply", stdin=[{"stable_id": loose_id, "title": "Pay rent!", "clear_due": True}])
        self.assertEqual([item["status"] for item in results], ["updated"])
        self.assertEqual(results[0]["stable_id"], reminder["external_id"])
        updated = self.store.find("Pay rent!")
        self.assertIsNone(updated["due_date"])
        self.assertNotEqual(updated["modified_at"], "2026-09-01T00:00:00Z")

        before = self.store.find("Pay rent!")["modified_at"]
        self.store.edit_reminder("Pay rent!", modified_at="2026-09-02T00:00:00Z")
        self.store.run("apply", stdin=[{"stable_id": reminder["id"], "title": "Pay rent!"}])
        self.assertEqual(self.store.find("Pay rent!")["modified_at"], "2026-09-02T00:00:00Z", before)

        operations = [
            {"stable_id": reminder["id"], "all_day": True, "due_date": "2026-11-01"},
            {"stable_id": reminder["id"], "all_day": False, "due_at": "2026-11-02T09:00:00.000Z"},
            {"stable_id": reminder["id"], "all_day": True, "due_date": "2026-11-03T00:00:00Z"},  # ignored
        ]
        self.store.run("apply", stdin=operations)
        timed = self.store.find("Pay rent!")
        self.assertEqual((timed["due_at"], timed["due_date"]), ("2026-11-02T09:00:00Z", None))

        self.store.run("apply", stdin=[{"stable_id": reminder["id"], "complete": True}])
        self.assertTrue(self.store.find("Pay rent!")["is_completed"])
        self.assertTrue(self.store.find("Pay rent!")["completed_at"])
        self.assertEqual(self.export(), [])
        self.assertEqual([item["title"] for item in self.export("--completed-only")], ["Pay rent!"])

        code, results, _ = self.store.run(
            "apply", stdin=[{"stable_id": reminder["id"], "delete": True}, {"stable_id": reminder["id"], "title": "x"}]
        )
        self.assertEqual([item["status"] for item in results], ["deleted", "missing"])
        self.assertIsNone(self.store.find("Pay rent!"))

    def test_apply_list_boundary_and_input_errors(self) -> None:
        work = self.store.add_reminder("work only", "Work")
        code, results, _ = self.store.run("apply", "--list", "My Tasks", stdin=[{"stable_id": work["id"], "title": "x"}])
        self.assertEqual(results, [{"stable_id": work["id"], "status": "missing"}])
        self.assertEqual(self.store.run("apply", "--list", "Nope", stdin=[])[0], 1)
        self.assertEqual(self.store.run("apply", "--list", stdin=[])[0], 1)
        self.assertEqual(self.store.run("apply", stdin=b"")[0], 1)
        self.assertEqual(self.store.run("apply", stdin=b"{not json")[0], 1)
        self.assertEqual(self.store.run("apply", stdin={"create": True})[0], 1)
        self.assertEqual(self.store.run("apply", stdin=[1, 2])[0], 1)

    def test_access_denied_and_injected_failures(self) -> None:
        self.store.set_access(False)
        for helper, stdin in (("export", b""), ("apply", b"[]")):
            code, payload, stderr = self.store.run(helper, stdin=stdin)
            self.assertEqual((code, payload), (1, None))
            self.assertIn("Reminders access was denied", stderr)
        self.store.set_access(True)
        self.store.fail_next("export", message="boom")
        self.assertEqual(self.store.run("export")[0:3:2], (1, "boom"))
        self.assertEqual(self.store.run("export")[0], 0)
        self.assertEqual([call.get("exit") for call in self.store.calls()][-4:], [1, 1, 1, 0])

    def test_helper_executables_follow_the_contract(self) -> None:
        paths = fake_reminders.install_helpers(self.directory / "bin")
        self.assertEqual(set(paths), {"export", "apply"})
        self.assertEqual(paths["export"].name, "ltb-reminders-export")
        self.assertEqual(os.stat(paths["apply"]).st_mode & 0o777, 0o755)
        environment = {"PATH": "/usr/bin:/bin", "TZ": "Asia/Shanghai",
                       fake_reminders.STORE_ENV: str(self.store.path)}
        self.store.add_reminder("买牛奶 🥛", due_date="2026-10-05")
        process = subprocess.run(
            [str(paths["export"]), "--include-undated", "--list", "My Tasks"],
            capture_output=True, env=environment, timeout=30, check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        exported = json.loads(process.stdout.decode("utf-8"))
        self.assertEqual(exported[0]["title"], "买牛奶 🥛")
        # All-day dates resolve to local midnight: 2026-10-05 00:00 in UTC+8.
        self.assertEqual((exported[0]["due_at"], exported[0]["due_date"]), ("2026-10-04T16:00:00Z", "2026-10-05"))
        environment["TZ"] = "America/Los_Angeles"
        process = subprocess.run([str(paths["export"])], capture_output=True, env=environment, timeout=30, check=False)
        self.assertEqual(json.loads(process.stdout.decode("utf-8"))[0]["due_at"], "2026-10-05T07:00:00Z")

        operations = json.dumps([{"stable_id": exported[0]["stable_id"], "title": "Buy milk"}]).encode("utf-8")
        process = subprocess.run(
            [str(paths["apply"]), "--list", "My Tasks"], input=operations,
            capture_output=True, env=environment, timeout=30, check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout.decode("utf-8"))[0]["status"], "updated")
        calls = self.store.calls()
        self.assertEqual(calls[-1]["argv"], ["--list", "My Tasks"])
        self.assertEqual(calls[-1]["operations"][0]["title"], "Buy milk")
        self.assertEqual(calls[0]["argv"], ["--include-undated", "--list", "My Tasks"])


class HarnessTests(unittest.TestCase):
    def test_environment_is_isolated_and_signed_in_at_the_fake(self) -> None:
        with harness.Environment() as env:
            self.assertTrue(str(env.home).startswith(str(env.root)))
            self.assertEqual(env.env["HOME"], str(env.home))
            self.assertTrue(env.env["PATH"].startswith(str(env.guard_dir) + ":"))
            self.assertTrue(env.env["PATH"].endswith(":/usr/bin:/bin"))
            for name in ("LTB_TASKS_API", "LTB_OAUTH_TOKEN_URL", "LTB_OAUTH_USERINFO_URL", "LTB_OAUTH_REVOKE_URL",
                         "LTB_OAUTH_AUTH_URL", "LTB_CALENDAR_API"):
                self.assertTrue(env.env[name].startswith("http://127.0.0.1:"), name)
            self.assertEqual(env.env["LTB_NO_LAUNCHCTL"], "1")
            self.assertEqual(harness.file_mode(env.config_dir), 0o700)
            for path in (env.config_path, env.credentials_path, env.token_path):
                self.assertEqual(harness.file_mode(path), 0o600, path)
            config = harness.read_json(env.config_path)
            self.assertEqual(config["include_lists"], ["My Tasks"])
            self.assertFalse(config["macos_notifications"])
            token = harness.read_json(env.token_path)
            self.assertGreater(token["expires_at"], time.time())
            self.assertEqual(fake_google.decode_jwt_payload(token["id_token"])["sub"], harness.ACCOUNT_A.sub)
            status, _payload, _ = call(f"{env.google.tasks_api_url}/users/@me/lists", token=token["access_token"])
            self.assertEqual(status, 200)
            self.assertEqual(harness.read_json(env.credentials_path)["installed"]["client_id"], harness.CLIENT_ID)
            root = env.root
        self.assertFalse(root.exists())

    def test_guard_scripts_record_and_refuse(self) -> None:
        with harness.Environment(install=False) as env:
            process = subprocess.run(["launchctl", "print", "gui/501"], env=env.env, capture_output=True, check=False)
            self.assertEqual(process.returncode, 1)
            self.assertEqual(env.guarded_invocations(), ["launchctl print gui/501"])

    def test_json_stdout_parsing_is_strict(self) -> None:
        self.assertEqual(harness.parse_json_stdout('{"ok": true}\n'), ({"ok": True}, ""))
        for text in ("", "progress\n{\"ok\": true}", '{"ok": true}\n{"ok": true}', "[1]"):
            payload, reason = harness.parse_json_stdout(text)
            self.assertIsNone(payload, text)
            self.assertTrue(reason)
        self.assertTrue(harness.is_utc_timestamp("2026-10-01T10:41:09+00:00"))
        self.assertFalse(harness.is_utc_timestamp("2026-10-01T10:41:09+08:00"))
        self.assertFalse(harness.is_utc_timestamp(None))

    def test_loop_process_reads_events_and_stops(self) -> None:
        script = (
            "import json, signal, sys, time\n"
            "signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))\n"
            "print('@@LTB ' + json.dumps({'event': 'loop_started', 'interval': 60}), flush=True)\n"
            "print('plain line', flush=True)\n"
            "print('@@LTB not-json', flush=True)\n"
            "time.sleep(0.2)\n"
            "print('@@LTB ' + json.dumps({'event': 'cycle_finished', 'state': 'ok'}), flush=True)\n"
            "time.sleep(30)\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            loop = harness.LoopProcess([sys.executable, "-c", script], dict(os.environ), Path(directory),
                                       Path(directory) / "stderr.txt")
            try:
                index, event = loop.wait_for("cycle_finished", timeout=10)
                self.assertEqual((index, event["state"]), (1, "ok"))
                self.assertEqual(loop.event_names(), ["loop_started", "cycle_finished"])
                self.assertEqual(loop.output, ["plain line"])
                self.assertEqual(loop.malformed, ["@@LTB not-json"])
                with self.assertRaises(AssertionError):
                    loop.wait_for("paused", timeout=0.3)
                loop.assert_no_event("paused", within=0.2)
                self.assertEqual(loop.stop(), 0)
            finally:
                loop.kill()


if __name__ == "__main__":
    unittest.main()
