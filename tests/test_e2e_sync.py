"""End-to-end scenarios: the real engine CLI against fake Google and fake Reminders.

Every test builds a fresh environment (tests/e2e/harness.py): a temporary
HOME, a fake Google OAuth + Tasks server on 127.0.0.1, fake EventKit helpers
on a JSON store, and the engine run as a subprocess exactly as the app runs
it (docs/app-engine-contract.md). Nothing touches the real Reminders, Google,
~/.config or ~/Library.

    python3 -B -m unittest tests.test_e2e_sync
    python3 -B -m unittest discover -s tests -t .

Set LTB_E2E_KEEP=1 to keep each test's temporary directory for inspection.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import plistlib
import re
import signal
import socket
import sys
import time
import unittest
from typing import Any, Dict, List, Sequence

from tests.e2e import fake_google, harness
from tests.e2e.harness import ACCOUNT_A, ACCOUNT_B, APPLE_LIST, E2ETestCase, Environment

TODAY = dt.date.today()

CONDITIONS = {
    "setup_required", "auth_required", "account_binding_required", "mutation_approval_pending",
    "mutation_blocked", "paused", "running", "failed", "never_synced", "status_unreadable",
    "agent_stopped", "attention", "healthy", "unknown",
}
SUMMARY_KEYS = {
    "apple_exported", "google_lists", "inserted", "updated", "unchanged", "completed", "deleted",
    "duplicate_deleted", "google_applied", "bidir_conflicts", "skipped_invalid",
}
DOCUMENTED_PLAN_OPERATIONS = {
    "google_tasks.create_list", "google_tasks.create", "google_tasks.update", "google_tasks.attach",
    "google_tasks.attach_after_create", "google_tasks.complete", "google_tasks.delete", "google_tasks.dedupe_delete",
    "apple_reminders.create", "apple_reminders.update", "apple_reminders.complete", "apple_reminders.delete",
}
CONFIG_MERGE_KEYS = {
    "include_lists", "list_policies", "bidirectional", "delete_stale", "conflict_policy", "tasks_sync_undated",
    "tasks_import_unsynced", "tasks_create_missing_lists", "tasks_complete_stale", "sync_interval_seconds",
    "max_destructive_changes", "max_destructive_ratio", "mutation_approval_prompt", "macos_notifications",
    "language", "proxy", "oauth_client", "setup_completed_at", "trigger_min_interval_seconds",
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def day(offset: int) -> str:
    """A date ``offset`` days from today (inside the 365-day export window)."""

    return (TODAY + dt.timedelta(days=offset)).isoformat()


def legacy_google_binding(refresh_token: str) -> str:
    """The version-1 Google half of the account binding (a hash of the refresh token)."""

    return hashlib.sha256(f"google-oauth-refresh\n{refresh_token}".encode("utf-8")).hexdigest()


class SyncScenario(E2ETestCase):
    """Helpers shared by the scenarios."""

    def seed(
        self,
        env: Environment,
        apple: Sequence[str] = (),
        google: Sequence[str] = (),
        *,
        first_day: int = 20,
    ) -> Dict[str, Any]:
        """Create dated items on both sides and run the first sync; returns its JSON."""

        for index, title in enumerate(apple):
            env.reminders.add_reminder(title, due_date=day(first_day + index))
        for index, title in enumerate(google):
            env.google.add_task(APPLE_LIST, title, due=day(first_day + len(apple) + index))
        payload = self.sync(env, msg="the first sync failed")
        self.assert_converged(env, [*apple, *google], msg="after the first sync")
        return payload

    def google_task(self, env: Environment, title: str, **options: Any) -> Dict[str, Any]:
        task = env.google.find_task(title, APPLE_LIST, **options)
        self.assertIsNotNone(task, f"no Google task titled {title!r}: {env.google.tasks(APPLE_LIST, include_deleted=True)}")
        return task

    def reminder(self, env: Environment, title: str) -> Dict[str, Any]:
        reminder = env.reminders.find(title)
        self.assertIsNotNone(reminder, f"no reminder titled {title!r}: {env.reminders.reminders()}")
        return reminder


# a. First sync in both directions -----------------------------------------------------


class FirstSyncTests(SyncScenario):
    def test_first_sync_merges_both_sides_and_a_second_sync_has_nothing_to_do(self) -> None:
        env = self.make_env()
        apple = {"Apple one": day(20), "Buy milk 买牛奶 🥛": day(21)}
        google = {"Google one": day(22), "Call Zoë ☎️": day(23)}
        for title, due in apple.items():
            env.reminders.add_reminder(title, due_date=due)
        for title, due in google.items():
            env.google.add_task(APPLE_LIST, title, due=due)

        first = self.sync(env)
        expected = {**apple, **google}
        self.assertEqual(env.apple_dues(), expected, "Apple Reminders after the first sync")
        self.assertEqual(env.google_dues(), expected, "Google Tasks after the first sync")
        self.assertEqual(len(env.google.tasks(APPLE_LIST, include_deleted=True)), 4, "duplicate Google tasks")
        self.assertEqual(len(env.reminders.reminders()), 4, "duplicate reminders")
        self.assertFalse(first.get("dry_run"))
        summary = first.get("summary") or {}
        self.assertEqual(SUMMARY_KEYS - set(summary), set(), f"summary keys missing: {summary}")
        self.assertEqual((summary.get("inserted"), summary.get("google_applied")), (2, 2), summary)
        for title in google:
            self.assertEqual(self.reminder(env, title)["notes"], "", "Apple reminders imported from Google got notes")

        writes, applies = len(env.google.write_requests()), len(env.reminders.calls("apply"))
        self.assert_quiet_sync(env)
        self.assertEqual(len(env.google.write_requests()), writes, "the converged sync wrote to Google")
        self.assertEqual(len(env.reminders.calls("apply")), applies, "the converged sync wrote to Reminders")


# b. Title edits ---------------------------------------------------------------------------


class EditTests(SyncScenario):
    def test_title_edits_flow_apple_to_google_and_google_to_apple(self) -> None:
        env = self.make_env()
        self.seed(env, apple=["Edited on the Mac", "Edited in Google"])
        env.reminders.edit_reminder("Edited on the Mac", title="Renamed on the Mac")
        env.google.edit_task("Edited in Google", title="Renamed in Google")

        self.sync(env)
        self.assert_converged(env, ["Renamed in Google", "Renamed on the Mac"])
        self.assertEqual(env.apple_dues(), env.google_dues(), "due dates changed during a title edit")
        self.assertEqual(len(env.google.tasks(APPLE_LIST, include_deleted=True)), 2, "an edit became delete + create")
        self.assert_quiet_sync(env)


# c. Completion in either app -------------------------------------------------------------------


class CompletionTests(SyncScenario):
    # One completion out of four managed items stays inside the default 25 % limit.
    ITEMS = ["Item A", "Item B", "Item C", "Item D"]

    def test_completing_a_reminder_completes_the_google_task(self) -> None:
        env = self.make_env()
        self.seed(env, apple=self.ITEMS)
        env.reminders.complete_reminder("Item A")

        payload = self.sync(env)
        task = self.google_task(env, "Item A")
        self.assertEqual(task["status"], "completed", task)
        self.assertNotIn("deleted", task)
        self.assertEqual((payload.get("summary") or {}).get("completed"), 1, payload)
        self.assert_converged(env, self.ITEMS[1:])
        self.assert_quiet_sync(env)

    def test_completing_a_google_task_completes_the_reminder_and_keeps_the_task(self) -> None:
        """Regression (2026-09): a stale completed-reminders snapshot made the
        engine delete the Google task right after completing the reminder."""

        env = self.make_env()
        self.seed(env, apple=self.ITEMS)
        task_id = self.google_task(env, "Item A")["id"]
        env.google.complete_task("Item A")  # the Google Tasks app also hides it

        self.sync(env)
        self.assertTrue(self.reminder(env, "Item A")["is_completed"], "the reminder was not completed")
        deletes = [entry for entry in env.google.requests("DELETE") if entry["path"].endswith("/" + task_id)]
        self.assertEqual(deletes, [], "the engine deleted the Google task it should only have completed")
        task = env.google.get_task(task_id)
        self.assertEqual((task["status"], task.get("deleted", False)), ("completed", False), task)
        self.assert_converged(env, self.ITEMS[1:])
        self.assert_quiet_sync(env)
        self.assertFalse(env.google.get_task(task_id).get("deleted", False), "deleted on the follow-up sync")


# d. Deletion within the safety limits --------------------------------------------------------------


class DeletionTests(SyncScenario):
    def test_deletions_within_the_limits_propagate_both_ways(self) -> None:
        env = self.make_env()
        items = [f"Item {number}" for number in range(1, 9)]
        self.seed(env, apple=items)
        removed_on_mac = self.google_task(env, "Item 1")["id"]
        env.reminders.delete_reminder("Item 1")
        env.google.delete_task("Item 2")

        # 2 of 8 is exactly the default 25 % ratio, which is still allowed.
        payload = self.sync(env)
        plan = payload.get("plan") or {}
        self.assertEqual(plan.get("destructive_count"), 2, plan)
        self.assertIsNone(env.reminders.find("Item 2"), "the reminder deleted in Google is still there")
        self.assertTrue(env.google.get_task(removed_on_mac).get("deleted"), "the task deleted on the Mac is still active")
        self.assert_converged(env, items[2:])
        self.assert_quiet_sync(env)


# e. Bulk deletions above the limit --------------------------------------------------------------


class BulkApprovalTests(SyncScenario):
    ITEMS = ["Item 1", "Item 2", "Item 3", "Item 4", "Item 5", "Item 6"]
    REMOVED = ["Item 1", "Item 2", "Item 3", "Item 4"]

    def blocked_env(self, **config: Any) -> Environment:
        env = self.make_env(config={"max_destructive_changes": 3, "max_destructive_ratio": 1.0, **config})
        self.seed(env, apple=self.ITEMS)
        for title in self.REMOVED:
            env.reminders.delete_reminder(title)
        return env

    def pending_review(self, env: Environment) -> Dict[str, Any]:
        review = self.assert_ok(env.run("approvals", "show"))
        self.assertIs(review.get("pending"), True, review)
        self.assertRegex(str(review.get("destructive_fingerprint")), HEX64)
        return review

    def test_over_the_limit_nothing_is_deleted_until_the_reviewed_set_is_applied(self) -> None:
        env = self.blocked_env()
        writes = len(env.google.write_requests())

        blocked = self.assert_error(env.run("sync"), "approval_required")
        plan = blocked.get("plan") or {}
        self.assertEqual(plan.get("destructive_count"), 4, plan)
        self.assertEqual((plan.get("counts") or {}).get("google_tasks.delete"), 4, plan)
        self.assertEqual(len(env.google.write_requests()), writes, "a blocked plan wrote to Google")
        self.assertEqual(env.google_titles(), self.ITEMS)
        status = self.assert_ok(env.run("status"))
        self.assertEqual(status.get("condition"), "mutation_blocked", status)
        self.assertEqual(status.get("pending_destructive_counts"), {"google_tasks.delete": 4}, status)

        review = self.pending_review(env)
        self.assertEqual(review.get("destructive_count"), 4, review)
        self.assertIsInstance(review.get("population"), int)
        self.assertIsInstance(review.get("ratio"), (int, float))
        items = review.get("items") or []
        self.assertEqual(sorted(item.get("title") for item in items), self.REMOVED, items)
        for item in items:
            self.assertEqual((item.get("operation"), item.get("list")), ("google_tasks.delete", APPLE_LIST), item)
            self.assertTrue(isinstance(item.get("label"), str) and item["label"], item)
        self.assertEqual(len(env.google.write_requests()), writes, "approvals show wrote to Google")

        applied = self.assert_ok(env.run("approvals", "apply", review["destructive_fingerprint"]))
        self.assertTrue(applied.get("applied", True), applied)
        self.assert_converged(env, ["Item 5", "Item 6"])
        self.assert_quiet_sync(env)
        after = self.assert_ok(env.run("approvals", "show"))
        self.assertEqual((after.get("pending"), after.get("items")), (False, []), after)

    def test_an_approval_for_a_plan_that_changed_meanwhile_applies_nothing(self) -> None:
        env = self.blocked_env()
        review = self.pending_review(env)
        env.reminders.delete_reminder("Item 5")

        self.assert_error(env.run("approvals", "apply", review["destructive_fingerprint"]), "plan_changed")
        self.assertEqual(env.google_titles(), self.ITEMS, "a stale approval deleted Google tasks")

    def test_hold_keeps_the_items_while_the_scheduler_syncs_everything_else(self) -> None:
        # Hosted by the app: the event stream replaces the dialog with approval_requested.
        env = self.blocked_env(mutation_approval_prompt=True)
        loop = env.start_loop()
        first, finished = loop.wait_for("cycle_finished", timeout=30)
        self.assertEqual(
            (finished.get("state"), finished.get("condition")),
            ("awaiting_mutation_approval", "mutation_approval_pending"),
            loop.describe(),
        )
        self.assertEqual(env.google_titles(), self.ITEMS, "the scheduler deleted without an approval")

        # The plan has to look the same on two cycles before anyone is asked.
        self.assert_ok(env.run("sync-now"))
        _index, requested = loop.wait_for("approval_requested", after=first, timeout=30)
        self.assertRegex(str(requested.get("destructive_fingerprint")), HEX64)
        self.assertEqual(requested.get("destructive_count"), 4, requested)
        last, _ = loop.wait_for("cycle_finished", after=first + 1, timeout=30)

        self.assert_ok(env.run("approvals", "hold", requested["destructive_fingerprint"]))
        env.reminders.add_reminder("Unrelated new reminder", due_date=day(40))
        self.assert_ok(env.run("sync-now"))
        held, finished = loop.wait_for("cycle_finished", after=last + 1, timeout=30)
        self.assertEqual(finished.get("state"), "awaiting_mutation_approval", loop.describe())
        self.assertIn("Unrelated new reminder", env.google_titles(), "other changes stopped syncing during a hold")
        self.assertEqual(sorted(set(env.google_titles()) - {"Unrelated new reminder"}), self.ITEMS)
        self.assertEqual(
            [event for event in loop.events[last + 1:held + 1] if event.get("event") == "approval_requested"], [],
            "asked again right after a hold",
        )
        self.assertEqual(loop.stop(), 0, loop.describe())
        self.assertTrue(self.pending_review(env)["destructive_fingerprint"], "the held plan is no longer pending")


# f. Due dates -----------------------------------------------------------------------------------


class DueDateTests(SyncScenario):
    # 20:00 UTC is already the next day in Shanghai (UTC+8) and still the same
    # day in Los Angeles (UTC-7/-8).
    TIMED_INSTANT = f"{day(24)}T20:00:00Z"

    def first_sync_with_dates(self, tz: str, timed_local_date: str) -> Environment:
        env = self.make_env(tz=tz)
        env.reminders.add_reminder("Dentist", due_date=day(20))
        env.reminders.add_reminder("Timed call", due_at=self.TIMED_INSTANT)
        env.google.add_task(APPLE_LIST, "Renew passport", due=day(22))
        self.sync(env)
        self.assertEqual(
            env.google_dues(),
            {"Dentist": day(20), "Timed call": timed_local_date, "Renew passport": day(22)},
            f"Google due dates after the first sync (TZ={tz})",
        )
        imported = self.reminder(env, "Renew passport")
        self.assertEqual((imported["due_date"], imported["due_at"]), (day(22), None), "not imported as all-day")
        return env

    def test_due_dates_east_of_utc_and_changes_in_both_directions(self) -> None:
        env = self.first_sync_with_dates("Asia/Shanghai", day(25))
        env.google.edit_task("Renew passport", due=day(26))
        env.reminders.edit_reminder("Timed call", due_date=day(27))
        env.reminders.edit_reminder("Dentist", due_date=None)
        self.sync(env)

        dues = env.google_dues()
        with self.subTest("a date changed in Reminders moves the Google due date"):
            self.assertEqual(dues["Timed call"], day(27), dues)
        with self.subTest("a date removed in Reminders clears the Google due date"):
            self.assertIsNone(dues["Dentist"], dues)
        with self.subTest("a due date changed in Google moves the reminder"):
            moved = self.reminder(env, "Renew passport")
            self.assertEqual(
                (moved["due_date"], dues["Renew passport"]),
                (day(26), day(26)),
                "the reminder kept its old date and the Google change was overwritten",
            )
        with self.subTest("converged"):
            self.assert_quiet_sync(env)

    def test_due_dates_west_of_utc(self) -> None:
        env = self.first_sync_with_dates("America/Los_Angeles", day(24))
        self.assert_quiet_sync(env)

    def test_clearing_a_due_date_in_google_makes_the_reminder_undated(self) -> None:
        env = self.make_env()
        self.seed(env, apple=["Clear me in Google"])
        env.google.edit_task("Clear me in Google", due=None)
        self.sync(env)

        reminder = self.reminder(env, "Clear me in Google")
        self.assertEqual(
            ((reminder["due_date"], reminder["due_at"]), env.google_dues()["Clear me in Google"]),
            ((None, None), None),
            "removing the date in Google Tasks was undone instead of reaching Reminders",
        )
        self.assert_quiet_sync(env)


# g. Undated reminders and tasks -----------------------------------------------------------------------


class UndatedTests(SyncScenario):
    def test_undated_items_sync_when_enabled(self) -> None:
        env = self.make_env()
        env.reminders.add_reminder("Someday (Apple)")
        env.google.add_task(APPLE_LIST, "Someday (Google)")

        self.sync(env)
        self.assert_converged(env, ["Someday (Apple)", "Someday (Google)"])
        imported = self.reminder(env, "Someday (Google)")
        self.assertEqual((imported["due_date"], imported["due_at"]), (None, None))
        self.assertNotIn("due", self.google_task(env, "Someday (Apple)"))
        self.assert_quiet_sync(env)

    def test_undated_items_stay_on_their_side_when_disabled(self) -> None:
        env = self.make_env(config={"tasks_sync_undated": False})
        env.reminders.add_reminder("Someday (Apple)")
        env.reminders.add_reminder("Dated (Apple)", due_date=day(20))
        env.google.add_task(APPLE_LIST, "Someday (Google)")

        self.sync(env)
        self.assertEqual(env.apple_titles(), ["Dated (Apple)", "Someday (Apple)"])
        self.assertEqual(env.google_titles(), ["Dated (Apple)", "Someday (Google)"])
        exports = [call["argv"] for call in env.reminders.calls("export") if "--lists-only" not in call["argv"]]
        self.assertTrue(exports)
        self.assertEqual([argv for argv in exports if "--include-undated" in argv], [], exports)
        self.assert_quiet_sync(env)


# h. Account binding ------------------------------------------------------------------------------------


class AccountBindingTests(SyncScenario):
    def test_signing_in_again_to_the_same_account_keeps_the_sync_map(self) -> None:
        env = self.make_env()
        self.seed(env, apple=["Apple one", "Apple two"])
        binding = env.state().get("account_binding")
        old_refresh = harness.read_json(env.token_path)["refresh_token"]

        new_refresh = env.write_token(ACCOUNT_A)["refresh_token"]
        self.assertNotEqual(new_refresh, old_refresh)
        self.assert_quiet_sync(env, "signing in again to the same Google account lost the sync map")
        self.assertEqual(env.state().get("account_binding"), binding)
        self.assert_converged(env, ["Apple one", "Apple two"])

    def test_a_different_google_account_stops_before_anything_is_written(self) -> None:
        env = self.make_env()
        self.seed(env, apple=["Apple one", "Apple two"])
        state_before = env.state_path.read_bytes()
        writes, applies = len(env.google.write_requests()), len(env.reminders.calls("apply"))

        env.write_token(ACCOUNT_B)
        self.assert_error(env.run("sync"), "account_binding_required")
        self.assertEqual(len(env.google.write_requests()), writes, "wrote to Google with another account")
        self.assertEqual(len(env.reminders.calls("apply")), applies, "wrote to Reminders with another account")
        self.assertEqual(env.google.tasks(APPLE_LIST, sub=ACCOUNT_B.sub), [], "account B's tasks were changed")
        self.assertEqual(env.state_path.read_bytes(), state_before, "the sync map was modified")
        status = self.assert_ok(env.run("status"))
        self.assertEqual(status.get("condition"), "account_binding_required", status)

    def test_a_version_one_binding_upgrades_only_for_the_same_credential(self) -> None:
        env = self.make_env()
        self.seed(env, apple=["Apple one", "Apple two"])
        state = env.state()
        apple_hash = state["account_binding"]["apple"]
        refresh = harness.read_json(env.token_path)["refresh_token"]

        state["account_binding"] = {"version": 1, "apple": apple_hash, "google": legacy_google_binding("1//older-token")}
        harness.write_private_json(env.state_path, state)
        self.assert_error(env.run("sync"), "account_binding_required", "a v1 binding of another credential")

        legacy = {"version": 1, "apple": apple_hash, "google": legacy_google_binding(refresh)}
        state["account_binding"] = legacy
        harness.write_private_json(env.state_path, state)
        self.sync(env, "--dry-run")
        self.assertEqual(env.state().get("account_binding"), legacy, "a dry run rewrote the binding")
        self.assert_quiet_sync(env, "a v1 binding for the current credential was not accepted")
        upgraded = env.state().get("account_binding") or {}
        self.assertEqual(upgraded.get("version"), 2, upgraded)
        self.assertEqual(upgraded.get("apple"), apple_hash)
        self.assertRegex(str(upgraded.get("google")), HEX64)
        self.assertNotEqual(upgraded.get("google"), legacy["google"])
        self.assertNotIn(ACCOUNT_A.sub, env.state_path.read_text(encoding="utf-8"), "raw account ID in state.json")
        self.assert_converged(env, ["Apple one", "Apple two"])


# i. Token refresh ------------------------------------------------------------------------------------------


class TokenRefreshTests(SyncScenario):
    def refresh_requests(self, env: Environment) -> List[Dict[str, Any]]:
        return [
            entry for entry in env.google.requests("POST", fake_google.TOKEN_PATH)
            if (entry.get("body") or {}).get("grant_type") == "refresh_token"
        ]

    def test_an_expired_access_token_is_refreshed_and_the_sync_continues(self) -> None:
        env = self.make_env()
        old = env.write_token(ACCOUNT_A, expired=True)
        env.reminders.add_reminder("After refresh", due_date=day(20))

        self.sync(env)
        refreshes = self.refresh_requests(env)
        self.assertEqual(len(refreshes), 1, refreshes)
        self.assertEqual(refreshes[0]["body"].get("refresh_token"), old["refresh_token"])
        self.assertEqual(env.google_titles(), ["After refresh"])
        token = harness.read_json(env.token_path)
        self.assertNotEqual(token["access_token"], old["access_token"])
        self.assertEqual(token["refresh_token"], old["refresh_token"])
        self.assertGreater(token["expires_at"], time.time() + 600)
        self.assertEqual(harness.file_mode(env.token_path), 0o600)

    def test_a_rejected_access_token_is_refreshed_once_and_the_request_retried(self) -> None:
        env = self.make_env()
        env.google.expire_access_tokens()  # token.json still claims it is valid
        env.reminders.add_reminder("After a 401", due_date=day(20))

        self.sync(env)
        self.assertEqual(len(self.refresh_requests(env)), 1)
        self.assertEqual([entry["status"] for entry in env.google.requests(path=fake_google.TASKS_API_PATH)][0], 401)
        self.assertEqual(env.google_titles(), ["After a 401"])

    def test_a_revoked_refresh_token_asks_to_sign_in_again(self) -> None:
        env = self.make_env()
        token = env.write_token(ACCOUNT_A, expired=True)
        env.google.revoke(token["refresh_token"])
        env.reminders.add_reminder("Never synced", due_date=day(20))

        self.assert_error(env.run("sync"), "auth_required")
        self.assertEqual(env.google.write_requests(), [])
        status = self.assert_ok(env.run("status"))
        self.assertEqual(status.get("condition"), "auth_required", status)


# j. Transient failures -------------------------------------------------------------------------------------------


class TransientFailureTests(SyncScenario):
    def assert_read_glitch_is_survived(self, kind: Any, count: int = 1) -> None:
        env = self.make_env()
        self.seed(env, apple=["Apple one", "Apple two"])
        env.reminders.add_reminder("After the glitch", due_date=day(30))
        env.google.inject_fault("GET", fake_google.TASKS_PATH, kind, count=count)

        result = env.run("sync")
        if not result.ok:
            retry = env.run("sync")
            self.fail(
                f"{count} transient {kind!r} answer(s) to a task-list GET failed the sync "
                f"(exit {result.returncode}, error {result.error_code!r}); reads are not retried. "
                f"A second sync then {'converged' if retry.ok else 'failed too'}.\n{result.describe()}"
            )
        self.assertEqual(env.google.pending_faults(), 0, "the injected fault was never hit")
        self.assert_converged(env, ["After the glitch", "Apple one", "Apple two"])
        self.assertEqual(len(env.google.tasks(APPLE_LIST, include_deleted=True)), 3, "duplicates after a retry")

    def test_a_server_error_on_a_task_list_read_is_retried(self) -> None:
        self.assert_read_glitch_is_survived(500)

    def test_a_dropped_connection_on_a_task_list_read_is_retried(self) -> None:
        self.assert_read_glitch_is_survived("drop")

    def test_a_lost_answer_to_a_task_insert_is_never_blindly_repeated(self) -> None:
        env = self.make_env()
        self.seed(env, apple=["Apple one"])
        env.reminders.add_reminder("Exactly once", due_date=day(30))
        env.google.inject_fault("POST", fake_google.TASKS_PATH, "drop_after_apply", count=1)

        first = env.run("sync")
        inserts = [
            entry for entry in env.google.requests("POST", fake_google.TASKS_PATH)
            if (entry.get("body") or {}).get("title") == "Exactly once"
        ]
        self.assertEqual(len(inserts), 1, f"the insert was repeated after an unknown outcome\n{first.describe()}")
        if not first.ok:
            self.assertEqual(first.payload and first.payload.get("ok"), False, first.describe())
            self.sync(env, msg="the sync after a lost insert answer failed")
        self.assertEqual([task["title"] for task in env.google.tasks(APPLE_LIST)].count("Exactly once"), 1,
                         "a lost insert answer produced a duplicate task")
        self.assert_converged(env, ["Apple one", "Exactly once"])
        self.assert_quiet_sync(env)


# k. The background scheduler ---------------------------------------------------------------------------------------


class RunLoopTests(SyncScenario):
    def test_run_loop_events_sync_now_pause_resume_and_sigterm(self) -> None:
        env = self.make_env()
        env.reminders.add_reminder("Loop item", due_date=day(20))
        loop = env.start_loop()

        _index, started = loop.wait_for("loop_started", timeout=15)
        self.assertEqual(started.get("interval"), 60, started)
        self.assertIsInstance(started.get("version"), str)
        first, _ = loop.wait_for("cycle_started", timeout=15)
        cycle_end, finished = loop.wait_for("cycle_finished", after=first, timeout=30)
        self.assertEqual(
            (finished.get("state"), finished.get("condition"), finished.get("consecutive_failures")),
            ("ok", "healthy", 0),
            loop.describe(),
        )
        self.assertTrue(harness.is_utc_timestamp(finished.get("at")), finished)
        self.assertEqual(env.google_titles(), ["Loop item"])

        env.reminders.add_reminder("Requested now", due_date=day(21))
        requested_at = time.monotonic()
        self.assert_ok(env.run("sync-now"))
        second, _ = loop.wait_for("cycle_started", after=cycle_end + 1, timeout=10)
        self.assertLess(loop.event_times[second] - requested_at, 3.5, "sync-now took too long to start a cycle")
        cycle_end, _ = loop.wait_for("cycle_finished", after=second, timeout=30)
        self.assertIn("Requested now", env.google_titles())

        paused = self.assert_ok(env.run("pause"))
        self.assertIs(paused.get("paused", True), True, paused)
        pause_index, _ = loop.wait_for("paused", after=cycle_end + 1, timeout=10)
        env.reminders.add_reminder("While paused", due_date=day(22))
        self.assert_ok(env.run("sync-now"))
        loop.assert_no_event("cycle_started", within=2.0, after=pause_index)
        self.assertNotIn("While paused", env.google_titles())
        status = self.assert_ok(env.run("status"))
        self.assertEqual((status.get("paused"), status.get("condition")), (True, "paused"), status)
        self.assertIs(status.get("loop_running"), True, status)

        self.assert_ok(env.run("resume"))
        loop.wait_for("resumed", after=pause_index, timeout=10)
        third, _ = loop.wait_for("cycle_started", after=pause_index, timeout=10)
        loop.wait_for("cycle_finished", after=third, timeout=30)
        self.assertIn("While paused", env.google_titles())

        self.assertEqual(loop.stop(signal.SIGTERM, timeout=30), 0, loop.describe())
        status = self.assert_ok(env.run("status"))
        self.assertIs(status.get("loop_running"), False, status)
        self.assertNotEqual(status.get("state"), "running", status)
        self.assertEqual(loop.malformed, [], "malformed @@LTB lines")
        stream = json.dumps(loop.events, ensure_ascii=False)
        for title in ("Loop item", "Requested now", "While paused"):
            self.assertNotIn(title, stream, "a title appeared in the event stream")

    def test_config_merge_while_the_loop_runs_applies_on_the_next_cycle(self) -> None:
        # Found in real-device acceptance: `ltb config merge` changed the
        # selected lists, but the running loop kept syncing the old ones.
        env = self.make_env(reminder_lists=(APPLE_LIST, "Acceptance"))
        env.reminders.add_reminder("Old list item", due_date=day(20))
        env.reminders.add_reminder("New list item", "Acceptance", due_date=day(21))
        loop = env.start_loop()
        first, _ = loop.wait_for("cycle_started", timeout=15)
        cycle_end, _ = loop.wait_for("cycle_finished", after=first, timeout=30)
        self.assertEqual(env.google_titles(), ["Old list item"])
        with self.assertRaises(KeyError):  # the unselected list was not created in Google
            env.google_titles("Acceptance")

        merged = self.assert_ok(env.run("config", "merge", stdin={"include_lists": ["Acceptance"]}))
        self.assertEqual(merged["config"]["include_lists"], ["Acceptance"], merged)
        self.assert_ok(env.run("sync-now"))
        second, _ = loop.wait_for("cycle_started", after=cycle_end + 1, timeout=10)
        loop.wait_for("cycle_finished", after=second, timeout=30)
        self.assertEqual(env.google_titles("Acceptance"), ["New list item"], loop.describe())
        # Unselecting a list is never a deletion.
        self.assertEqual(env.google_titles(), ["Old list item"])
        self.assertEqual(loop.stop(signal.SIGTERM, timeout=30), 0, loop.describe())

    def test_a_second_run_loop_for_the_same_config_exits(self) -> None:
        env = self.make_env()
        first = env.start_loop()
        first.wait_for("loop_started", timeout=15)
        second = env.start_loop()
        self.assertEqual(second.process.wait(timeout=30), 1, second.describe())
        self.assertNotIn("cycle_started", second.event_names())
        self.assertEqual(first.stop(), 0, first.describe())


# l. Migrating the 2026-09 trial install ------------------------------------------------------------------------------


class MigrationTests(SyncScenario):
    def make_trial_install(self, env: Environment) -> Dict[str, Any]:
        """The trial layout: daily-config.json and its files in ~/.config/reminders-task-bridge-trial."""

        trial = env.xdg_config_home / "reminders-task-bridge-trial"
        trial.mkdir(mode=0o700)
        harness.write_private_json(trial / "credentials.json", env.oauth_client_document())
        token = env.write_token(ACCOUNT_A, path=trial / "token.json")
        settings = {
            "target_service": "tasks",
            "include_lists": [APPLE_LIST],
            "bidirectional": True,
            "delete_stale": True,
            "conflict_policy": "newer_wins",
            "tasks_import_unsynced": True,
            "tasks_sync_undated": True,
            "macos_notifications": False,
            "mutation_approval_prompt": False,
            "verify_title_due_retry_delay_seconds": 0,
            "sync_interval_seconds": 900,
            "credentials_path": "~/.config/reminders-task-bridge-trial/credentials.json",
            "token_path": "~/.config/reminders-task-bridge-trial/token.json",
            "state_path": "~/.config/reminders-task-bridge-trial/daily-state.json",
            "status_path": "~/.config/reminders-task-bridge-trial/daily-status.json",
        }
        # Build a real sync map with the trial's own paths, then make its
        # binding what the trial engine wrote (version 1, refresh-token hash).
        harness.write_private_json(trial / "prepare.json", settings)
        self.sync(env, config_path=trial / "prepare.json", msg="preparing the trial sync map failed")
        (trial / "prepare.json").unlink()
        state = harness.read_json(trial / "daily-state.json")
        state["account_binding"] = {
            "version": 1,
            "apple": state["account_binding"]["apple"],
            "google": legacy_google_binding(token["refresh_token"]),
        }
        harness.write_private_json(trial / "daily-state.json", state)
        # The trial ran the Swift helpers from its own runtime.
        settings["reminders_exporter_path"] = "~/.local/share/icloud-reminders-google-sync/current/RemindersExport.swift"
        settings["reminders_apply_path"] = "~/.local/share/icloud-reminders-google-sync/current/RemindersApply.swift"
        harness.write_private_json(trial / "daily-config.json", settings)
        return {"dir": trial, "files": {path.name: path.read_bytes() for path in sorted(trial.iterdir())}}

    def test_migrating_the_trial_keeps_the_sync_map_and_leaves_the_old_files(self) -> None:
        env = self.make_env(install=False)
        env.reminders.add_reminder("Trial reminder", due_date=day(20))
        env.google.add_task(APPLE_LIST, "Trial task", due=day(21))
        trial = self.make_trial_install(env)
        self.assert_converged(env, ["Trial reminder", "Trial task"])

        before = self.assert_ok(env.run("status"))
        self.assertEqual((before.get("config_exists"), before.get("legacy_install_detected")), (False, True), before)

        migrated = self.assert_ok(env.run("migrate", "--yes"))
        self.assertEqual(migrated.get("migrated_from"), str(trial["dir"] / "daily-config.json"), migrated)
        self.assertEqual(set(migrated.get("copied") or []), {"credentials", "token", "state", "status"}, migrated)
        self.assertIs(migrated.get("dry_run"), False)
        self.assertTrue(env.config_path.is_file())
        self.assertEqual(harness.file_mode(env.config_path), 0o600)
        self.assertEqual(harness.file_mode(env.config_dir), 0o700)
        for name, content in trial["files"].items():
            self.assertEqual((trial["dir"] / name).read_bytes(), content, f"migrate changed the old {name}")

        self.assert_quiet_sync(env, "the first sync after migrating did not continue the old sync map")
        self.assert_converged(env, ["Trial reminder", "Trial task"])
        self.assertEqual(len(env.google.tasks(APPLE_LIST, include_deleted=True)), 2, "duplicated after migrating")
        self.assertEqual((env.state().get("account_binding") or {}).get("version"), 2)
        after = self.assert_ok(env.run("status"))
        self.assertEqual(after.get("legacy_install_detected"), False, after)

    def test_migration_retires_the_old_launch_agent_and_keeps_its_proxy(self) -> None:
        env = self.make_env(install=False)
        trial = self.make_trial_install(env)
        plist = env.launch_agents_dir / "com.icloud-reminders-google-sync.plist"
        env.launch_agents_dir.mkdir(parents=True, exist_ok=True)
        plist.write_bytes(plistlib.dumps({
            "Label": "com.icloud-reminders-google-sync",
            "ProgramArguments": ["/usr/bin/python3", "sync"],
            "EnvironmentVariables": {"HTTPS_PROXY": env.google.base_url},
        }))

        migrated = self.assert_ok(env.run("migrate", "--yes"))
        self.assertFalse(plist.exists(), "the old LaunchAgent plist was left in LaunchAgents")
        backups = list((env.config_dir / "backups").rglob(plist.name))
        self.assertEqual(len(backups), 1, f"the old plist is not in backups/: {migrated}")
        shown = self.assert_ok(env.run("config", "show"))
        self.assertEqual((shown.get("config") or {}).get("proxy"), env.google.base_url, shown)
        self.assertTrue((trial["dir"] / "daily-config.json").is_file())
        self.assert_quiet_sync(env)


# m. Shapes of the read-only commands ---------------------------------------------------------------------------------


class ContractShapeTests(SyncScenario):
    def test_status_json(self) -> None:
        env = self.make_env()
        fresh = self.assert_ok(env.run("status"))
        self.assertIn(fresh.get("condition"), CONDITIONS, fresh)
        self.seed(env, apple=["Apple one"])

        status = self.assert_ok(env.run("status"))
        expected_types = {
            "version": str, "config_path": str, "config_exists": bool, "setup_completed": bool, "condition": str,
            "headline": str, "action": str, "state": str, "paused": bool, "consecutive_failures": int,
            "pending_destructive_counts": dict, "oauth_client": dict, "token_ready": bool, "include_lists": list,
            "sync_interval_seconds": int, "loop_running": bool, "agent": dict, "log_path": str,
            "legacy_install_detected": bool,
        }
        for key, kind in expected_types.items():
            self.assertIsInstance(status.get(key), kind, f"status.{key}: {status.get(key)!r}")
        for key in ("last_success_at", "last_start_at", "last_end_at", "updated_at"):
            self.assertTrue(harness.is_utc_timestamp(status.get(key)), f"status.{key}: {status.get(key)!r}")
        self.assertIn(status["condition"], CONDITIONS)
        self.assertTrue(status["headline"].strip() and status["action"].strip())
        self.assertEqual(
            (status["config_path"], status["config_exists"], status["setup_completed"], status["state"]),
            (str(env.config_path), True, True, "ok"),
        )
        self.assertEqual((status["paused"], status["consecutive_failures"], status["pending_destructive_counts"]),
                         (False, 0, {}))
        self.assertEqual(status["oauth_client"],
                         {"mode": "auto", "active": "custom", "custom_ready": True, "bundled_available": False})
        self.assertEqual((status["token_ready"], status["include_lists"], status["sync_interval_seconds"]),
                         (True, [APPLE_LIST], 60))
        self.assertEqual(status["agent"].get("label"), "io.github.siyuanj.local-tasks-bridge")
        self.assertIs(status["agent"].get("installed"), False)
        self.assertIsNone(status["agent"].get("loaded"), "agent.loaded must be null without launchctl")
        self.assertEqual((status["log_path"], status["loop_running"], status["legacy_install_detected"]),
                         (str(env.engine_log_path), False, False))

    def test_lists_json(self) -> None:
        env = self.make_env(reminder_lists=(APPLE_LIST, "Work"), google_lists=("Errands",))
        apple_only = self.assert_ok(env.run("lists"))
        self.assertIsNone(apple_only.get("google"), apple_only)
        self.assertEqual([item.get("title") for item in apple_only.get("apple") or []], [APPLE_LIST, "Work"],
                         "lists must ignore include_lists")
        for item in apple_only["apple"]:
            self.assertEqual(set(item), {"id", "title", "account_title", "account_id"}, item)
            self.assertEqual(item["account_title"], "iCloud")
        both = self.assert_ok(env.run("lists", "--google"))
        self.assertEqual([item.get("title") for item in both.get("google") or []], [APPLE_LIST, "Errands"])
        for item in both["google"]:
            self.assertEqual(set(item), {"id", "title"}, item)

    def test_doctor_json(self) -> None:
        env = self.make_env()
        self.seed(env, apple=["Apple one"])
        doctor = self.assert_ok(env.run("doctor"))
        checks = doctor.get("checks")
        self.assertIsInstance(checks, list)
        ids = [check.get("id") for check in checks]
        self.assertEqual(len(ids), len(set(ids)), ids)
        for check in checks:
            self.assertIsInstance(check.get("id"), str, check)
            self.assertIsInstance(check.get("ok"), bool, check)
            self.assertTrue(isinstance(check.get("label"), str) and check["label"], check)
        self.assertIs(dict(zip(ids, (check["ok"] for check in checks))).get("config"), True, checks)
        self.assertTrue(isinstance(doctor.get("next_step"), str) and doctor["next_step"], doctor)
        self.assertIn(doctor.get("condition"), CONDITIONS, doctor)

    def test_config_show_and_merge(self) -> None:
        env = self.make_env()
        token = harness.read_json(env.token_path)
        shown = self.assert_ok(env.run("config", "show"))
        self.assertEqual(shown.get("config_path"), str(env.config_path))
        config = shown.get("config") or {}
        self.assertEqual(set(config) - CONFIG_MERGE_KEYS, set(), "config show lists keys config merge does not take")
        self.assertEqual((config.get("include_lists"), config.get("bidirectional")), ([APPLE_LIST], True))
        for secret in (harness.CLIENT_SECRET, token["refresh_token"], token["access_token"]):
            self.assertNotIn(secret, json.dumps(shown), "config show revealed a credential")

        merged = self.assert_ok(env.run("config", "merge", stdin={"sync_interval_seconds": 120,
                                                                   "include_lists": [APPLE_LIST, "Work"]}))
        self.assertEqual((merged.get("config") or {}).get("sync_interval_seconds"), 120, merged)
        self.assertEqual(set(merged) - {"ok"}, set(shown) - {"ok"}, "config merge must return the config show shape")
        saved = harness.read_json(env.config_path)
        self.assertEqual((saved["sync_interval_seconds"], saved["include_lists"]), (120, [APPLE_LIST, "Work"]))
        self.assertEqual((saved["conflict_policy"], saved["macos_notifications"]), ("newer_wins", False))
        self.assertEqual(harness.file_mode(env.config_path), 0o600)

        before = env.config_path.read_bytes()
        for bad in ({"not_a_setting": 1}, {"sync_interval_seconds": 30}, {"conflict_policy": "maybe"}, [1, 2]):
            with self.subTest(bad=bad):
                self.assert_error(env.run("config", "merge", stdin=bad), "config_invalid")
                self.assertEqual(env.config_path.read_bytes(), before, "a rejected merge changed config.json")

    def test_client_status_and_import(self) -> None:
        env = self.make_env()
        status = self.assert_ok(env.run("client", "status"))
        client = status.get("oauth_client", status)
        self.assertEqual({key: client.get(key) for key in ("mode", "active", "custom_ready", "bundled_available")},
                         {"mode": "auto", "active": "custom", "custom_ready": True, "bundled_available": False}, status)

        credentials_before = env.credentials_path.read_bytes()
        web = env.root / "web-client.json"
        harness.write_private_json(web, env.oauth_client_document(kind="web"))
        rejected = env.run("client", "import", str(web))
        self.assertFalse(rejected.ok, rejected.describe())
        self.assertIs((rejected.payload or {}).get("ok"), False, rejected.describe())
        self.assertEqual(env.credentials_path.read_bytes(), credentials_before, "a Web client replaced the client")

        desktop = env.oauth_client_document()
        desktop["installed"]["client_id"] = "987654321098-other.apps.googleusercontent.com"
        source = env.root / "desktop-client.json"
        harness.write_private_json(source, desktop)
        imported = self.assert_ok(env.run("client", "import", str(source)))
        hint = str(imported.get("client_id_hint") or "")
        self.assertTrue(hint.startswith("9876") and hint.endswith("apps.googleusercontent.com"), imported)
        self.assertNotIn(desktop["installed"]["client_id"], json.dumps(imported), "the full client ID was echoed")
        self.assertEqual(harness.read_json(env.credentials_path)["installed"]["client_id"],
                         desktop["installed"]["client_id"])
        self.assertEqual(harness.file_mode(env.credentials_path), 0o600)
        self.assertEqual(harness.read_json(env.config_path).get("oauth_client"), "custom")

    def test_version_json(self) -> None:
        env = self.make_env()
        version = self.assert_ok(env.run("version"))
        self.assertIsInstance(version.get("version"), str)
        self.assertEqual(version.get("python"), ".".join(str(part) for part in sys.version_info[:3]))
        self.assertEqual(version.get("engine_path"), str(harness.ENGINE_PATH))

    def test_sync_plan_counts_use_the_documented_operation_names(self) -> None:
        env = self.make_env()
        env.reminders.add_reminder("Apple one", due_date=day(20))
        env.google.add_task(APPLE_LIST, "Google one", due=day(21))
        plan = self.sync(env, "--dry-run").get("plan") or {}
        for key in ("total_count", "destructive_count", "counts"):
            self.assertIn(key, plan, plan)
        counts = plan["counts"]
        self.assertEqual(
            set(counts) - DOCUMENTED_PLAN_OPERATIONS,
            set(),
            f"plan.counts uses operation names the contract does not document: {counts}",
        )
        self.assertEqual((counts.get("google_tasks.create"), counts.get("apple_reminders.create")), (1, 1), counts)

    def test_browserless_sign_in(self) -> None:
        env = self.make_env(signed_in=False)
        signed_in = self.assert_ok(env.run_browserless_sign_in(login=fake_google.LoginBehaviour(sub=ACCOUNT_A.sub)))
        self.assertEqual((signed_in.get("account_email"), signed_in.get("client_mode")), (ACCOUNT_A.email, "custom"))
        token = harness.read_json(env.token_path)
        self.assertEqual(fake_google.decode_jwt_payload(token["id_token"])["sub"], ACCOUNT_A.sub)
        self.assertEqual((env.google.refresh_token_info(token["refresh_token"]) or {}).get("sub"), ACCOUNT_A.sub)
        self.assertEqual(harness.file_mode(env.token_path), 0o600)

        env.token_path.unlink()
        unticked = env.run_browserless_sign_in(login=fake_google.LoginBehaviour(untick_tasks=True))
        self.assert_error(unticked, "auth_required", "signing in without the Tasks permission")
        self.assertFalse(env.token_path.exists(), "a token without the Tasks permission was saved")


# n. Privacy -------------------------------------------------------------------------------------------------------------


class PrivacyTests(SyncScenario):
    CANARIES = ["CANARY-7f3a apple secret", "CANARY-9b2c google secret", "CANARY-41de doomed one",
                "CANARY-58ef doomed two"]

    def test_titles_never_reach_status_json_helper_arguments_or_sync_json(self) -> None:
        env = self.make_env(config={"max_destructive_changes": 1, "max_destructive_ratio": 1.0})
        apple, google, doomed_one, doomed_two = self.CANARIES
        for index, title in enumerate((apple, doomed_one, doomed_two)):
            env.reminders.add_reminder(title, due_date=day(20 + index))
        env.google.add_task(APPLE_LIST, google, due=day(30))
        token = harness.read_json(env.token_path)

        outputs = [env.run("sync"), env.run("status"), env.run("doctor")]
        self.assert_ok(outputs[0])
        env.reminders.delete_reminder(doomed_one)
        env.reminders.delete_reminder(doomed_two)
        outputs.append(env.run("sync"))
        self.assert_error(outputs[-1], "approval_required")
        outputs.append(env.run("status"))
        review = self.assert_ok(env.run("approvals", "show"))
        self.assertEqual(sorted(item.get("title") for item in review.get("items") or []), sorted([doomed_one, doomed_two]),
                         "approvals show is the one place that lists titles")

        status_text = env.status_path.read_text(encoding="utf-8")
        for canary in self.CANARIES:
            self.assertNotIn(canary, status_text, "a title reached status.json")
            self.assertNotIn(canary.split()[0], status_text, "a title reached status.json")
            for result in outputs:
                self.assertNotIn(canary, result.stdout, f"a title reached the JSON of {result.args[5:]}")
            for call in env.reminders.calls():
                self.assertNotIn(canary, " ".join(call["argv"]), "a title reached a helper's argv")
        for secret in (token["refresh_token"], token["access_token"], harness.CLIENT_SECRET):
            self.assertNotIn(secret, status_text, "a credential reached status.json")
            for result in outputs:
                self.assertNotIn(secret, result.stdout + result.stderr, "a credential reached engine output")
        self.assertEqual(harness.file_mode(env.status_path), 0o600)
        self.assertEqual(harness.file_mode(env.state_path), 0o600)
        if env.engine_log_path.exists():
            self.assertEqual(harness.file_mode(env.engine_log_path), 0o600)
            self.assertEqual(harness.file_mode(env.log_dir), 0o700)


# o. Concurrent changes and failure reporting -------------------------------------------------------------------------


class RaceTests(SyncScenario):
    def test_an_apple_edit_newer_than_a_google_deletion_wins(self) -> None:
        """With conflict_policy newer_wins, editing a reminder after its task
        was deleted in Google keeps the item on both sides."""

        env = self.make_env()
        self.seed(env, apple=["Item A", "Item B", "Item C", "Item D"])
        env.google.delete_task("Item A", updated=fake_google.rfc3339_ms(time.time() - 120))
        env.reminders.edit_reminder("Item A", title="Item A, edited after the deletion")

        results = [env.run("sync"), env.run("sync")]
        with self.subTest("both syncs succeed"):
            failed = [result for result in results if not result.ok]
            self.assertEqual([result.returncode for result in results], [0, 0],
                             "\n\n".join(result.describe() for result in failed))
        with self.subTest("the newer edit survives on both sides"):
            self.assertIsNotNone(env.reminders.find("Item A, edited after the deletion"),
                                 "the edited reminder was deleted on the Mac")
            self.assert_converged(env, ["Item A, edited after the deletion", "Item B", "Item C", "Item D"])
            self.assert_quiet_sync(env)


class FailureReportingTests(SyncScenario):
    def test_a_failed_manual_sync_is_recorded_as_failed(self) -> None:
        env = self.make_env(config={"conflict_policy": "skip"})
        self.seed(env, apple=["Edited on both sides"])
        env.reminders.edit_reminder("Edited on both sides", title="Changed on the Mac")
        env.google.edit_task("Edited on both sides", title="Changed in Google")

        result = env.run("sync")
        self.assertFalse(result.ok, result.describe())
        self.assertEqual(env.status_file().get("state"), "failed", "status.json does not record the failed sync")
        status = self.assert_ok(env.run("status"))
        self.assertEqual(status.get("condition"), "failed", status)

    def test_a_failing_cycle_reports_no_titles_and_the_next_cycle_recovers(self) -> None:
        env = self.make_env()
        canary = "CANARY-5d1e renamed"
        self.seed(env, apple=["Watched item"])
        env.write_config(macos_notifications=True)  # posted through the event stream, never osascript
        env.reminders.edit_reminder("Watched item", title=canary)
        # Google acknowledges the rename without applying it, so verification fails.
        env.google.inject_fault("PATCH", fake_google.TASK_PATH, fake_google.STALE_WRITE_FAULT, count=5)
        loop = env.start_loop()

        failed_index, failed = loop.wait_for("cycle_finished", timeout=30)
        with self.subTest("the cycle is reported as failed"):
            self.assertEqual(
                (failed.get("state"), failed.get("condition"), failed.get("consecutive_failures")),
                ("failed", "failed", 1),
                loop.describe(),
            )
            notices = [event for event in loop.events if event.get("event") == "notification"]
            self.assertEqual([event.get("severity") for event in notices], ["problem"], notices)
        with self.subTest("no title in the event stream"):
            self.assertNotIn("CANARY", json.dumps(loop.events, ensure_ascii=False))
        with self.subTest("no title in status.json"):
            self.assertNotIn("CANARY", env.status_path.read_text(encoding="utf-8"))
        with self.subTest("the next cycle recovers"):
            env.google.clear_faults()
            self.assert_ok(env.run("sync-now"))
            _index, finished = loop.wait_for("cycle_finished", after=failed_index + 1, timeout=30)
            self.assertEqual((finished.get("state"), finished.get("consecutive_failures")), ("ok", 0), loop.describe())
            self.assertEqual(env.google_titles(), [canary])
        self.assertEqual(loop.stop(), 0, loop.describe())


# p. Setup, errors, sign-out, login item, paging, several lists -------------------------------------------------------


class SetupFlowTests(SyncScenario):
    def test_the_setup_preview_writes_nothing_and_the_first_sync_keeps_deletions_off(self) -> None:
        env = self.make_env()
        env.reminders.add_reminder("On the Mac", due_date=day(20))
        env.google.add_task(APPLE_LIST, "In Google", due=day(21))

        preview = self.sync(env, "--dry-run", "--no-delete-stale")
        self.assertIs(preview.get("dry_run"), True, preview)
        self.assertGreater((preview.get("plan") or {}).get("total_count", 0), 0, preview)
        self.assertEqual(env.google.write_requests(), [], "the dry run wrote to Google")
        self.assertEqual(env.reminders.calls("apply"), [], "the dry run wrote to Reminders")
        self.assertFalse(env.state_path.exists(), "the dry run saved a sync map")

        self.sync(env, "--no-delete-stale")
        self.assert_converged(env, ["In Google", "On the Mac"])
        env.reminders.delete_reminder("On the Mac")
        kept = self.sync(env, "--no-delete-stale")
        self.assertEqual((kept.get("plan") or {}).get("destructive_count"), 0, kept)
        self.assertIn("On the Mac", env.google_titles(), "--no-delete-stale propagated a deletion")


class ErrorCodeTests(SyncScenario):
    def test_failures_map_to_the_documented_exit_codes(self) -> None:
        env = self.make_env()
        config, token, credentials = (path.read_bytes() for path in (env.config_path, env.token_path, env.credentials_path))

        def restore() -> None:
            for path, content in ((env.config_path, config), (env.token_path, token), (env.credentials_path, credentials)):
                path.write_bytes(content)
                path.chmod(0o600)
            env.reminders.set_access(True)

        with self.subTest("auth_required: not signed in"):
            env.token_path.unlink()
            self.assert_error(env.run("sync"), "auth_required")
            restore()
        with self.subTest("reminders_unavailable: Reminders access denied"):
            env.reminders.set_access(False)
            self.assert_error(env.run("sync"), "reminders_unavailable")
            self.assert_error(env.run("lists"), "reminders_unavailable")
            restore()
        with self.subTest("config_invalid: config.json is not JSON"):
            env.config_path.write_text("{not json", encoding="utf-8")
            self.assert_error(env.run("sync"), "config_invalid")
            restore()
        with self.subTest("config_invalid: unsupported value"):
            env.write_config(conflict_policy="sometimes")
            self.assert_error(env.run("sync"), "config_invalid")
            restore()
        with self.subTest("oauth_client_missing: no OAuth client"):
            env.credentials_path.unlink()
            self.assert_error(env.run("auth", "--no-browser"), "oauth_client_missing")
            restore()
        with self.subTest("network: Google unreachable"):
            unreachable = f"http://127.0.0.1:{free_port()}/tasks/v1"
            self.assert_error(env.run("sync", env={"LTB_TASKS_API": unreachable}), "network")
        with self.subTest("usage error"):
            self.assertEqual(env.run("sync", "--no-such-option").returncode, 2)


class AccountLifecycleTests(SyncScenario):
    def test_signing_out_and_back_in_continues_the_sync_map(self) -> None:
        env = self.make_env()
        self.seed(env, apple=["Apple one", "Apple two"])
        account = self.assert_ok(env.run("account"))
        self.assertEqual((account.get("account_email"), account.get("tasklist_count")), (ACCOUNT_A.email, 1), account)
        refresh = harness.read_json(env.token_path)["refresh_token"]

        self.assert_ok(env.run("signout", "--revoke"))
        self.assertFalse(env.token_path.exists(), "signout left token.json")
        self.assertTrue((env.google.refresh_token_info(refresh) or {}).get("revoked"), "--revoke did not revoke")
        self.assertTrue(env.state_path.exists(), "signing out deleted the sync map")
        self.assert_error(env.run("sync"), "auth_required")
        self.assertEqual(self.assert_ok(env.run("status")).get("condition"), "auth_required")

        env.write_token(ACCOUNT_A)
        self.assert_quiet_sync(env, "signing back in to the same account did not continue where it left off")


class LoginItemTests(SyncScenario):
    LABEL = "io.github.siyuanj.local-tasks-bridge"

    def test_agent_install_status_and_uninstall(self) -> None:
        env = self.make_env()
        app = env.root / "Local Tasks Bridge.app"
        executable = app / "Contents" / "MacOS" / "LocalTasksBridge"
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

        installed = self.assert_ok(env.run("agent", "install", "--app", str(app)))
        plist = env.launch_agents_dir / f"{self.LABEL}.plist"
        app_log = str(env.log_dir / "app.log")
        self.assertEqual(
            plistlib.loads(plist.read_bytes()),
            {
                "Label": self.LABEL,
                "ProgramArguments": [str(executable), "--background"],
                "RunAtLoad": True,
                "KeepAlive": {"SuccessfulExit": False},
                "LimitLoadToSessionType": "Aqua",
                "ProcessType": "Interactive",
                "ThrottleInterval": 30,
                "StandardOutPath": app_log,
                "StandardErrorPath": app_log,
            },
        )
        self.assertEqual(harness.file_mode(plist), 0o644)
        status = self.assert_ok(env.run("agent", "status"))
        self.assertEqual(
            {key: status.get(key) for key in ("installed", "loaded", "label", "plist", "program")},
            {"installed": True, "loaded": None, "label": self.LABEL, "plist": str(plist), "program": str(executable)},
            installed,
        )
        removed = self.assert_ok(env.run("agent", "uninstall"))
        self.assertEqual((removed.get("installed"), plist.exists()), (False, False), removed)

    def test_uninstall_with_delete_data_removes_only_the_product_directories(self) -> None:
        env = self.make_env()
        self.seed(env, apple=["Apple one"])
        neighbours = [env.xdg_config_home / "another-app" / "settings.json", env.home / "Library" / "Logs" / "Other" / "x.log"]
        for path in neighbours:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("keep", encoding="utf-8")

        removed = self.assert_ok(env.run("uninstall", "--delete-data", "--yes"))
        self.assertIs(removed.get("data_deleted"), True, removed)
        self.assertFalse(env.config_dir.exists(), "the config dir is still there")
        self.assertFalse(env.log_dir.exists(), "the log dir is still there")
        for path in neighbours:
            self.assertEqual(path.read_text(encoding="utf-8"), "keep", f"uninstall touched {path}")
        self.assertEqual(env.google_titles(), ["Apple one"], "uninstall changed Google Tasks")
        self.assertEqual(env.apple_titles(), ["Apple one"], "uninstall changed Reminders")


class PagingTests(SyncScenario):
    def test_paged_listings_are_read_completely(self) -> None:
        env = self.make_env(max_page_size=2)
        items = [f"Paged {number}" for number in range(1, 8)]
        self.seed(env, apple=items)
        env.google.add_task(APPLE_LIST, "Paged in Google", due=day(40))

        self.sync(env)
        self.assert_converged(env, [*items, "Paged in Google"])
        self.assertTrue(
            [entry for entry in env.google.requests("GET", fake_google.TASKS_PATH) if entry["query"].get("pageToken")],
            "the engine never asked for a second page",
        )
        self.assert_quiet_sync(env)


class MultiListTests(SyncScenario):
    def test_each_included_list_syncs_with_its_own_google_list(self) -> None:
        env = self.make_env(
            reminder_lists=(APPLE_LIST, "Work", "Private"),
            config={"include_lists": [APPLE_LIST, "Work"]},
        )
        env.reminders.add_reminder("Home item", due_date=day(20))
        env.reminders.add_reminder("Work item", "Work", due_date=day(21))
        env.reminders.add_reminder("Private item", "Private", due_date=day(22))

        first = self.sync(env)
        self.assertEqual(((first.get("plan") or {}).get("counts") or {}).get("google_tasks.create_list"), 1, first)
        self.assertEqual(sorted(item["title"] for item in env.google.lists()), [APPLE_LIST, "Work"])
        self.assertEqual((env.google_titles(), env.google_titles("Work")), (["Home item"], ["Work item"]))

        env.google.add_task("Work", "Added in Google", due=day(23))
        self.sync(env)
        self.assertEqual(env.apple_titles("Work"), ["Added in Google", "Work item"])
        self.assertEqual((env.apple_titles(), env.apple_titles("Private")), (["Home item"], ["Private item"]))
        for call in env.reminders.calls("apply"):
            self.assertEqual(call["argv"], ["--list", APPLE_LIST, "--list", "Work"], "apply outside include_lists")
        self.assert_quiet_sync(env)


def free_port() -> int:
    """A loopback port nothing listens on (connections are refused)."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: Any) -> unittest.TestSuite:
    """Run the scenarios side by side: each one owns its whole environment."""

    return harness.ConcurrentSuite(tests)


if __name__ == "__main__":
    unittest.main()
