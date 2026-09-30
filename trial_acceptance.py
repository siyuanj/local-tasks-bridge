"""Manual acceptance probes restricted to one disposable trial list."""

import argparse
import json
from pathlib import Path

import icloud_reminders_google_sync as bridge

LIST = "Bridge Test 2026-09-30"
A = "Bridge test A - created on Mac"
A_GOOGLE = "Bridge test A - edited in Google"
B = "Bridge test B - created in Google"
B_MAC = "Bridge test B - edited on Mac"
C = "Bridge test C - complete from desktop widget"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", "google-create-edit", "google-complete"])
    args = parser.parse_args()
    path = Path.home() / ".config/reminders-task-bridge-trial/config.json"
    config = bridge.load_config(argparse.Namespace(config=str(path)))
    if config["include_lists"] != [LIST] or config["target_service"] != "tasks":
        raise SystemExit("Refusing a configuration outside the isolated trial list")
    client = bridge.GoogleTasksClient(config)
    lists = [x for x in client.list_tasklists() if x["title"] == LIST]
    if len(lists) != 1:
        raise SystemExit("Expected exactly one trial list")
    list_id = lists[0]["id"]
    tasks = client.list_tasks(list_id)
    if args.action == "google-create-edit":
        matching_a = [t for t in tasks if t["title"] in (A, A_GOOGLE)]
        if len(matching_a) != 1:
            raise SystemExit("Expected exactly one known test A")
        if not any(t["title"] == B for t in tasks):
            client.insert_task(list_id, {"title": B, "notes": "Disposable bidirectional synchronization test."})
        if matching_a[0]["title"] == A:
            client.patch_task(list_id, matching_a[0]["id"], {"title": A_GOOGLE})
        tasks = client.list_tasks(list_id)
    elif args.action == "google-complete":
        matching_b = [t for t in tasks if t["title"] == B_MAC]
        if len(matching_b) != 1:
            raise SystemExit("Expected exactly one Mac-edited test B")
        if matching_b[0]["status"] != "completed":
            client.patch_task(list_id, matching_b[0]["id"], {"status": "completed"})
        if not any(t["title"] == C for t in tasks):
            client.insert_task(list_id, {"title": C})
        tasks = client.list_tasks(list_id)
    print(json.dumps([{"title": t["title"], "status": t["status"]} for t in tasks], indent=2))


if __name__ == "__main__":
    main()
