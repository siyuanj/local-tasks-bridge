"""Fake EventKit helpers on a JSON store, for end-to-end tests of the engine.

``ltb-reminders-export`` and ``ltb-reminders-apply`` (contract section 6) are
small Swift programs that read and write Apple Reminders through EventKit.
This module implements the same command lines on a JSON file named by
``$FAKE_REMINDERS_STORE`` and mirrors macos/Helpers/RemindersExport.swift and
RemindersApply.swift closely:

* export: ``--lookahead-days N``, ``--include-undated``, ``--completed-only``,
  repeated ``--list NAME`` (an unmatched filter is an error), ``--lists-only``;
  undated incomplete reminders only with ``--include-undated``; dated ones only
  inside the lookahead window; ``due_date`` only for all-day reminders;
  ``date_source`` ``due``/``alarm``/``none``; ISO 8601 ``Z`` timestamps.
* apply: creates honour ``list_id`` as authoritative, fall back to a unique
  ``list_title`` and otherwise report ``missing_list`` with the Swift reasons;
  updates and deletes match the normalized (lower-case hex) item or external
  identifier; ``complete`` sets the completion date; ``clear_due`` removes the
  date; ``modified_at`` moves whenever a reminder changes.
* Both exit 1 with a message on stderr when "Reminders access" is denied.

Identifiers look like EventKit's (upper-case UUIDs). All-day reminders store
date components and resolve to local midnight (``TZ`` of the helper process)
when exported, as EventKit does.

Run as a program (``python fake_reminders.py export|apply …``) it is the helper
itself; imported, ``FakeReminders`` lets a test play the person editing
Reminders on the Mac. The module only uses the standard library and no
relative imports, because the helper runs it as a top-level script.
"""
from __future__ import annotations

import contextlib
import copy
import datetime as dt
import fcntl
import json
import os
import re
import shlex
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

STORE_ENV = "FAKE_REMINDERS_STORE"
STORE_VERSION = 1
ACCESS_DENIED_MESSAGE = "Reminders access was denied. Enable it in System Settings > Privacy & Security > Reminders."
EXPORT_HELPER_NAME = "ltb-reminders-export"
APPLY_HELPER_NAME = "ltb-reminders-apply"
HELPERS = ("export", "apply")
MODULE_PATH = Path(__file__).resolve()

_UNSET: Any = object()
_ISO_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$")
_EXPORT_USAGE = """Usage: ltb-reminders-export [options]

Options:
  --lookahead-days DAYS   Export dated incomplete reminders due within this many days. Default: 365
  --include-undated       Also export incomplete reminders without a due date or alarm.
  --completed-only        Export completed reminders instead of incomplete reminders.
  --list NAME             Limit to a Reminders list. May be repeated.
  --lists-only            Export Reminders lists instead of reminders.
  --help                  Show this help.
"""


class HelperError(Exception):
    """What the Swift helpers report with ``fail(...)``: stderr text and exit 1."""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


# --- Time and identifiers --------------------------------------------------------


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(moment: Optional[dt.datetime]) -> Optional[str]:
    """ISO8601DateFormatter with .withInternetDateTime in UTC: 2026-10-01T10:41:09Z."""

    if moment is None:
        return None
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_instant(value: Any) -> Optional[dt.datetime]:
    """ISO8601DateFormatter's internet date-time, with or without fractional seconds."""

    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if not isinstance(value, str):
        return None
    match = _ISO_RE.match(value.strip())
    if not match:
        return None
    date_text, time_text, fraction, offset = match.groups()
    micro = (fraction or "0")[:6].ljust(6, "0")
    offset = "+00:00" if offset == "Z" else offset
    try:
        return dt.datetime.fromisoformat(f"{date_text}T{time_text}.{micro}{offset}")
    except ValueError:
        return None


def date_components(value: Any) -> Optional[str]:
    """RemindersApply.swift's dateComponents(from:): exactly ``Y-M-D`` integers."""

    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    parts = value.split("-")
    if len(parts) != 3 or not all(re.fullmatch(r"[+-]?\d+", part) for part in parts):
        return None
    try:
        return dt.date(int(parts[0]), int(parts[1]), int(parts[2])).isoformat()
    except ValueError:
        return None


def local_midnight(date_text: str) -> dt.datetime:
    """Midnight of an all-day date in the process time zone, as EventKit resolves it."""

    day = dt.date.fromisoformat(date_text)
    epoch = time.mktime((day.year, day.month, day.day, 0, 0, 0, 0, 0, -1))
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc)


def new_identifier() -> str:
    return str(uuid.uuid4()).upper()


def normalize_identifier(value: Any) -> str:
    """RemindersApply.swift's normalizeIdentifier: lower-case, hex digits only."""

    if not isinstance(value, str):
        return ""
    return "".join(character for character in value.lower() if character in "0123456789abcdef")


# --- The store --------------------------------------------------------------------------


def empty_store() -> Dict[str, Any]:
    return {
        "version": STORE_VERSION,
        "access": "granted",
        "accounts": [],
        "lists": [],
        "reminders": [],
        "faults": [],
        "calls": [],
    }


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[None]:
    lock_path = path.with_name(path.name + ".lock")
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _load(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return empty_store()
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or data.get("version") != STORE_VERSION:
        raise ValueError(f"not a fake Reminders store: {path}")
    return data


def _save(path: Path, data: Dict[str, Any]) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _account(data: Dict[str, Any], account_id: str) -> Dict[str, Any]:
    for account in data["accounts"]:
        if account["id"] == account_id:
            return account
    raise KeyError(account_id)


def _list(data: Dict[str, Any], list_id: str) -> Optional[Dict[str, Any]]:
    for reminder_list in data["lists"]:
        if reminder_list["id"] == list_id:
            return reminder_list
    return None


def _list_record(data: Dict[str, Any], reminder_list: Dict[str, Any]) -> Dict[str, Any]:
    account = _account(data, reminder_list["account_id"])
    return {
        "id": reminder_list["id"],
        "title": reminder_list["title"],
        "account_title": account["title"],
        "account_id": account["id"],
    }


def _due_instant(reminder: Dict[str, Any]) -> Tuple[Optional[dt.datetime], bool]:
    """(the date EventKit resolves dueDateComponents to, whether they are all-day)."""

    if reminder.get("due_date"):
        return local_midnight(reminder["due_date"]), True
    if reminder.get("due_at"):
        return parse_instant(reminder["due_at"]), False
    return None, False


def _export_record(data: Dict[str, Any], reminder: Dict[str, Any]) -> Dict[str, Any]:
    reminder_list = _list(data, reminder["list_id"]) or {}
    account = _account(data, reminder_list["account_id"]) if reminder_list else {}
    due, all_day = _due_instant(reminder)
    alarm = parse_instant(reminder.get("alarm_at"))
    chosen = due or alarm
    if chosen is None:
        date_source = "none"
    elif due is None and alarm is not None:
        date_source = "alarm"
    else:
        date_source = "due"
    external_id = str(reminder.get("external_id") or "")
    recurrence_count = int(reminder.get("recurrence_count") or 0)
    return {
        "id": reminder["id"],
        "external_id": external_id,
        "stable_id": external_id or reminder["id"],
        "title": reminder.get("title") or "",
        "notes": reminder.get("notes") or "",
        "list_title": reminder_list.get("title", ""),
        "list_id": reminder_list.get("id", ""),
        "account_title": account.get("title", ""),
        "account_id": account.get("id", ""),
        "priority": int(reminder.get("priority") or 0),
        "is_completed": bool(reminder.get("is_completed")),
        "is_recurring": recurrence_count > 0,
        "recurrence_count": recurrence_count,
        "created_at": reminder.get("created_at"),
        "modified_at": reminder.get("modified_at"),
        "completed_at": reminder.get("completed_at"),
        "due_at": iso(chosen),
        "due_date": reminder["due_date"] if chosen is not None and all_day else None,
        "all_day": bool(chosen is not None and all_day),
        "date_source": date_source,
    }


def _check_access(data: Dict[str, Any]) -> None:
    if data.get("access") != "granted":
        raise HelperError(ACCESS_DENIED_MESSAGE)


# --- ltb-reminders-export ------------------------------------------------------------------


def parse_export_options(argv: Sequence[str]) -> Dict[str, Any]:
    options: Dict[str, Any] = {
        "lookahead_days": 365,
        "list_names": set(),
        "include_undated": False,
        "completed_only": False,
        "lists_only": False,
        "show_help": False,
    }
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument in ("--help", "-h"):
            options["show_help"] = True
            index += 1
        elif argument == "--lookahead-days":
            value = argv[index + 1] if index + 1 < len(argv) else ""
            if not re.fullmatch(r"\+?\d+", value):
                raise HelperError("Invalid value for --lookahead-days")
            options["lookahead_days"] = int(value)
            index += 2
        elif argument == "--include-undated":
            options["include_undated"] = True
            index += 1
        elif argument == "--completed-only":
            options["completed_only"] = True
            index += 1
        elif argument == "--list":
            if index + 1 >= len(argv):
                raise HelperError("Missing value for --list")
            options["list_names"].add(argv[index + 1])
            index += 2
        elif argument == "--lists-only":
            options["lists_only"] = True
            index += 1
        else:
            raise HelperError(f"Unknown argument: {argument}")
    return options


def export_reminders(data: Dict[str, Any], argv: Sequence[str], *, now: Optional[dt.datetime] = None) -> List[Dict[str, Any]]:
    """What ``ltb-reminders-export <argv>`` prints, as Python objects."""

    options = parse_export_options(argv)
    _check_access(data)
    names = options["list_names"]
    selected = [reminder_list for reminder_list in data["lists"] if not names or reminder_list["title"] in names]
    if names and not selected:
        raise HelperError(f"No Reminders lists matched: {', '.join(sorted(names))}")
    if options["lists_only"]:
        return [_list_record(data, reminder_list) for reminder_list in selected]

    now = now or utc_now()
    latest = now + dt.timedelta(days=int(options["lookahead_days"]))
    selected_ids = {reminder_list["id"] for reminder_list in selected}
    exported = []
    for reminder in data["reminders"]:
        if reminder["list_id"] not in selected_ids:
            continue
        if bool(reminder.get("is_completed")) != options["completed_only"]:
            continue
        due, _all_day = _due_instant(reminder)
        chosen = due or parse_instant(reminder.get("alarm_at"))
        if not options["completed_only"] and chosen is None and not options["include_undated"]:
            continue
        if not options["completed_only"] and chosen is not None and chosen > latest:
            continue
        exported.append(_export_record(data, reminder))
    return exported


# --- ltb-reminders-apply ----------------------------------------------------------------------


def parse_apply_options(argv: Sequence[str]) -> set:
    allowed = set()
    index = 0
    while index < len(argv):
        if argv[index] != "--list" or index + 1 >= len(argv) or not argv[index + 1]:
            raise HelperError("Expected --list NAME.")
        allowed.add(argv[index + 1])
        index += 2
    return allowed


def _apply_fields(reminder: Dict[str, Any], operation: Dict[str, Any], now_text: str) -> None:
    """RemindersApply.swift's applyFields(to:operation:)."""

    if isinstance(operation.get("title"), str):
        reminder["title"] = operation["title"]
    if "notes" in operation:
        reminder["notes"] = operation["notes"] if isinstance(operation["notes"], str) else ""
    if operation.get("clear_due") is True:
        reminder["due_date"] = None
        reminder["due_at"] = None
    all_day = operation.get("all_day")
    if isinstance(all_day, bool):
        if all_day:
            due_date = date_components(operation.get("due_date"))
            if due_date:
                reminder["due_date"] = due_date
                reminder["due_at"] = None
        else:
            instant = parse_instant(operation.get("due_at"))
            if instant is not None:
                reminder["due_at"] = iso(instant)
                reminder["due_date"] = None
    if operation.get("complete") is True:
        reminder["is_completed"] = True
        reminder["completed_at"] = now_text


_MUTABLE_FIELDS = ("title", "notes", "due_date", "due_at", "is_completed", "completed_at")


def _apply_result(
    data: Dict[str, Any],
    reminder: Dict[str, Any],
    status: str,
    requested_stable_id: str = "",
) -> Dict[str, Any]:
    reminder_list = _list(data, reminder["list_id"]) or {}
    account = _account(data, reminder_list["account_id"]) if reminder_list else {}
    item_id = str(reminder.get("id") or "")
    external_id = str(reminder.get("external_id") or "")
    return {
        "stable_id": external_id or item_id or requested_stable_id,
        "id": item_id,
        "external_id": external_id,
        "status": status,
        "list_title": reminder_list.get("title", ""),
        "list_id": reminder_list.get("id", ""),
        "account_title": account.get("title", ""),
        "account_id": account.get("id", ""),
        "created_at": reminder.get("created_at") or "",
        "modified_at": reminder.get("modified_at") or "",
    }


def apply_operations(
    data: Dict[str, Any],
    argv: Sequence[str],
    stdin: bytes,
    *,
    now: Optional[dt.datetime] = None,
) -> List[Dict[str, Any]]:
    """Run ``ltb-reminders-apply <argv>`` with ``stdin``; mutates ``data``; returns the results."""

    allowed = parse_apply_options(argv)
    if not stdin:
        raise HelperError("Expected JSON operations on stdin.")
    try:
        payload = json.loads(stdin.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HelperError(f"Invalid JSON input: {exc}") from None
    if not isinstance(payload, list) or not all(isinstance(operation, dict) for operation in payload):
        raise HelperError("Expected a JSON array of operation objects.")
    _check_access(data)

    calendars = [reminder_list for reminder_list in data["lists"] if not allowed or reminder_list["title"] in allowed]
    if allowed and not calendars:
        raise HelperError("No allowed Reminders list was found; refusing to write.")
    by_identifier: Dict[str, Dict[str, Any]] = {}
    by_title: Dict[str, List[Dict[str, Any]]] = {}
    for reminder_list in calendars:
        identifier = reminder_list["id"].strip()
        if identifier:
            by_identifier[identifier] = reminder_list
        by_title.setdefault(reminder_list["title"], []).append(reminder_list)

    visible_ids = {reminder_list["id"] for reminder_list in calendars}
    by_normalized: Dict[str, Dict[str, Any]] = {}
    for reminder in data["reminders"]:
        if reminder["list_id"] not in visible_ids:
            continue
        for identifier in (reminder.get("id"), reminder.get("external_id")):
            key = normalize_identifier(identifier)
            if key:
                by_normalized[key] = reminder

    now_text = iso(now or utc_now()) or ""
    removed: set = set()
    results: List[Dict[str, Any]] = []
    for operation in payload:
        if operation.get("create") is True:
            list_id = operation.get("list_id") if isinstance(operation.get("list_id"), str) else ""
            list_id = list_id.strip()
            list_title = operation.get("list_title") if isinstance(operation.get("list_title"), str) else ""
            list_title = list_title.strip()
            title_matches = by_title.get(list_title, []) if list_title else []
            target: Optional[Dict[str, Any]]
            if list_id:
                # A stable identifier is authoritative; never fall through to a title.
                target, reason = by_identifier.get(list_id), "list_id_not_found"
            elif not list_title:
                target, reason = (calendars[0] if calendars else None), "no_reminder_lists"
            elif len(title_matches) == 1:
                target, reason = title_matches[0], ""
            else:
                target = None
                reason = "list_title_not_found" if not title_matches else "ambiguous_list_title"
            if target is None:
                results.append({"list_id": list_id, "list_title": list_title, "status": "missing_list", "reason": reason})
                continue
            reminder = {
                "id": new_identifier(),
                "external_id": new_identifier(),
                "list_id": target["id"],
                "title": "",
                "notes": "",
                "priority": 0,
                "is_completed": False,
                "completed_at": None,
                "created_at": now_text,
                "modified_at": now_text,
                "due_date": None,
                "due_at": None,
                "alarm_at": None,
                "recurrence_count": 0,
            }
            _apply_fields(reminder, operation, now_text)
            data["reminders"].append(reminder)
            results.append(_apply_result(data, reminder, "created"))
            continue

        stable_id = operation.get("stable_id")
        if not isinstance(stable_id, str):
            stable_id = operation.get("id") if isinstance(operation.get("id"), str) else ""
        reminder = by_normalized.get(normalize_identifier(stable_id))
        if reminder is None or id(reminder) in removed:
            results.append({"stable_id": stable_id, "status": "missing"})
            continue
        if operation.get("delete") is True:
            data["reminders"] = [item for item in data["reminders"] if item is not reminder]
            removed.add(id(reminder))
            results.append({"stable_id": stable_id, "status": "deleted"})
            continue
        before = {field: reminder.get(field) for field in _MUTABLE_FIELDS}
        _apply_fields(reminder, operation, now_text)
        if any(reminder.get(field) != value for field, value in before.items()):
            reminder["modified_at"] = now_text
        results.append(_apply_result(data, reminder, "updated", stable_id))
    return results


# --- Running the helpers -------------------------------------------------------------------


def _encode_output(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def run_helper(
    store_path: os.PathLike,
    helper: str,
    argv: Sequence[str],
    stdin: bytes = b"",
    *,
    now: Optional[dt.datetime] = None,
) -> Tuple[int, bytes, str]:
    """Run one helper invocation against the store: (exit code, stdout, stderr)."""

    if helper not in HELPERS:
        raise ValueError(f"unknown helper {helper!r}")
    path = Path(store_path)
    argv = [str(argument) for argument in argv]
    with _locked(path):
        data = _load(path)
        call: Dict[str, Any] = {"helper": helper, "argv": list(argv), "at": iso(now or utc_now())}
        exit_code, stdout, stderr = 0, b"", ""
        fault = _take_fault(data, helper)
        if fault is not None:
            exit_code = int(fault.get("exit", 1))
            stdout = str(fault.get("stdout") or "").encode("utf-8")
            stderr = str(fault.get("stderr") or "")
            call["fault"] = fault.get("stderr") or fault.get("stdout") or "fault"
        else:
            try:
                if helper == "export":
                    options = parse_export_options(argv)
                    if options["show_help"]:
                        stderr = _EXPORT_USAGE
                    else:
                        stdout = _encode_output(export_reminders(data, argv, now=now))
                else:
                    try:
                        call["operations"] = json.loads(stdin.decode("utf-8")) if stdin else None
                    except (UnicodeDecodeError, ValueError):
                        call["operations"] = stdin.decode("utf-8", errors="replace")
                    results = apply_operations(data, argv, stdin, now=now)
                    call["results"] = results
                    stdout = _encode_output(results)
            except HelperError as exc:
                exit_code, stdout, stderr = exc.code, b"", exc.message + "\n"
        call["exit"] = exit_code
        data["calls"].append(call)
        _save(path, data)
    return exit_code, stdout, stderr


def _take_fault(data: Dict[str, Any], helper: str) -> Optional[Dict[str, Any]]:
    for fault in data.get("faults", []):
        if fault.get("helper") in (helper, "*") and int(fault.get("remaining", 0)) > 0:
            fault["remaining"] = int(fault["remaining"]) - 1
            data["faults"] = [item for item in data["faults"] if int(item.get("remaining", 0)) > 0]
            return fault
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in HELPERS:
        sys.stderr.write("usage: fake_reminders.py export|apply [helper arguments]\n")
        return 2
    store_path = os.environ.get(STORE_ENV, "")
    if not store_path:
        sys.stderr.write(f"{STORE_ENV} is not set\n")
        return 1
    helper, helper_argv = arguments[0], arguments[1:]
    stdin = sys.stdin.buffer.read() if helper == "apply" else b""
    exit_code, stdout, stderr = run_helper(store_path, helper, helper_argv, stdin)
    if stdout:
        sys.stdout.buffer.write(stdout)
        sys.stdout.buffer.flush()
    if stderr:
        sys.stderr.write(stderr)
        sys.stderr.flush()
    return exit_code


def install_helpers(bin_dir: os.PathLike, *, python: Optional[str] = None) -> Dict[str, Path]:
    """Write executable ``ltb-reminders-export`` / ``ltb-reminders-apply`` into ``bin_dir``.

    Each is a tiny /bin/sh script that runs this module with the given Python
    (default: the interpreter running the tests). The store comes from
    ``$FAKE_REMINDERS_STORE`` in the helper's environment.
    """

    directory = Path(bin_dir)
    directory.mkdir(parents=True, exist_ok=True)
    interpreter = python or sys.executable
    paths = {}
    for helper, name in (("export", EXPORT_HELPER_NAME), ("apply", APPLY_HELPER_NAME)):
        path = directory / name
        path.write_text(
            "#!/bin/sh\n"
            f"exec {shlex.quote(interpreter)} -B -E -S {shlex.quote(str(MODULE_PATH))} {helper} \"$@\"\n",
            encoding="utf-8",
        )
        os.chmod(path, 0o755)
        paths[helper] = path
    return paths


# --- The person using Reminders on the Mac -------------------------------------------------


class FakeReminders:
    """Python access to a fake Reminders store (what someone does in Reminders.app)."""

    def __init__(self, store_path: os.PathLike) -> None:
        self.path = Path(store_path)

    @classmethod
    def create(
        cls,
        store_path: os.PathLike,
        *,
        account_title: str = "iCloud",
        lists: Sequence[str] = ("My Tasks",),
    ) -> "FakeReminders":
        store = cls(store_path)
        with _locked(store.path):
            data = empty_store()
            _save(store.path, data)
        store.add_account(account_title)
        for title in lists:
            store.add_list(title, account_title=account_title)
        return store

    @contextlib.contextmanager
    def _edit(self) -> Iterator[Dict[str, Any]]:
        with _locked(self.path):
            data = _load(self.path)
            yield data
            _save(self.path, data)

    def snapshot(self) -> Dict[str, Any]:
        with _locked(self.path):
            return _load(self.path)

    # Accounts and lists

    def add_account(self, title: str, *, account_id: Optional[str] = None) -> str:
        with self._edit() as data:
            account = {"id": account_id or new_identifier(), "title": title}
            data["accounts"].append(account)
            return account["id"]

    def add_list(self, title: str, *, account_title: str = "iCloud", list_id: Optional[str] = None) -> str:
        with self._edit() as data:
            account = next((item for item in data["accounts"] if item["title"] == account_title), None)
            if account is None:
                raise KeyError(f"no Reminders account titled {account_title!r}")
            reminder_list = {"id": list_id or new_identifier(), "title": title, "account_id": account["id"]}
            data["lists"].append(reminder_list)
            return reminder_list["id"]

    def lists(self) -> List[Dict[str, Any]]:
        data = self.snapshot()
        return [_list_record(data, reminder_list) for reminder_list in data["lists"]]

    def list_id(self, title: str) -> str:
        matches = [item["id"] for item in self.snapshot()["lists"] if item["title"] == title]
        if len(matches) != 1:
            raise LookupError(f"{len(matches)} Reminders lists are titled {title!r}")
        return matches[0]

    # Reminders

    def add_reminder(
        self,
        title: str,
        list_title: str = "My Tasks",
        *,
        notes: str = "",
        due_date: Any = None,
        due_at: Any = None,
        alarm_at: Any = None,
        completed: bool = False,
        completed_at: Any = None,
        priority: int = 0,
        recurrence_count: int = 0,
        created_at: Any = None,
        modified_at: Any = None,
        external_id: bool = True,
    ) -> Dict[str, Any]:
        """Add a reminder. ``due_date`` makes it all-day, ``due_at`` timed."""

        if due_date is not None and due_at is not None:
            raise ValueError("a reminder is either all-day (due_date) or timed (due_at)")
        now_text = iso(utc_now())
        with self._edit() as data:
            reminder_list = self._list_by_title(data, list_title)
            reminder = {
                "id": new_identifier(),
                "external_id": new_identifier() if external_id else "",
                "list_id": reminder_list["id"],
                "title": title,
                "notes": notes,
                "priority": int(priority),
                "is_completed": bool(completed),
                "completed_at": self._instant_text(completed_at) or (now_text if completed else None),
                "created_at": self._instant_text(created_at) or now_text,
                "modified_at": self._instant_text(modified_at) or self._instant_text(created_at) or now_text,
                "due_date": self._date_text(due_date),
                "due_at": self._instant_text(due_at),
                "alarm_at": self._instant_text(alarm_at),
                "recurrence_count": int(recurrence_count),
            }
            data["reminders"].append(reminder)
            return self._view(data, reminder)

    def edit_reminder(
        self,
        selector: str,
        *,
        title: Any = _UNSET,
        notes: Any = _UNSET,
        due_date: Any = _UNSET,
        due_at: Any = _UNSET,
        alarm_at: Any = _UNSET,
        priority: Any = _UNSET,
        list_title: Any = _UNSET,
        modified_at: Any = None,
    ) -> Dict[str, Any]:
        """Edit a reminder (selected by identifier or unique title). Setting
        ``due_date`` or ``due_at`` replaces the other; None removes the date."""

        with self._edit() as data:
            reminder = self._select(data, selector)
            if title is not _UNSET:
                reminder["title"] = str(title)
            if notes is not _UNSET:
                reminder["notes"] = str(notes or "")
            if due_date is not _UNSET:
                reminder["due_date"] = self._date_text(due_date)
                reminder["due_at"] = None
            if due_at is not _UNSET:
                reminder["due_at"] = self._instant_text(due_at)
                reminder["due_date"] = None
            if alarm_at is not _UNSET:
                reminder["alarm_at"] = self._instant_text(alarm_at)
            if priority is not _UNSET:
                reminder["priority"] = int(priority)
            if list_title is not _UNSET:
                reminder["list_id"] = self._list_by_title(data, str(list_title))["id"]
            reminder["modified_at"] = self._instant_text(modified_at) or iso(utc_now())
            return self._view(data, reminder)

    def complete_reminder(self, selector: str, *, completed_at: Any = None) -> Dict[str, Any]:
        with self._edit() as data:
            reminder = self._select(data, selector)
            moment = self._instant_text(completed_at) or iso(utc_now())
            reminder["is_completed"] = True
            reminder["completed_at"] = moment
            reminder["modified_at"] = moment
            return self._view(data, reminder)

    def uncomplete_reminder(self, selector: str, *, modified_at: Any = None) -> Dict[str, Any]:
        with self._edit() as data:
            reminder = self._select(data, selector)
            reminder["is_completed"] = False
            reminder["completed_at"] = None
            reminder["modified_at"] = self._instant_text(modified_at) or iso(utc_now())
            return self._view(data, reminder)

    def delete_reminder(self, selector: str) -> Dict[str, Any]:
        with self._edit() as data:
            reminder = self._select(data, selector)
            data["reminders"] = [item for item in data["reminders"] if item is not reminder]
            return self._view(data, reminder)

    def reminders(self, list_title: Optional[str] = None, *, include_completed: bool = True) -> List[Dict[str, Any]]:
        data = self.snapshot()
        views = []
        for reminder in data["reminders"]:
            view = self._view(data, reminder)
            if list_title is not None and view["list_title"] != list_title:
                continue
            if not include_completed and view["is_completed"]:
                continue
            views.append(view)
        return views

    def find(self, title: str, list_title: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """The one reminder with this title, None if there is none; LookupError if several."""

        matches = [view for view in self.reminders(list_title) if view["title"] == title]
        if len(matches) > 1:
            raise LookupError(f"{len(matches)} reminders are titled {title!r}")
        return matches[0] if matches else None

    # Permission, faults and the call log

    def set_access(self, granted: bool) -> None:
        with self._edit() as data:
            data["access"] = "granted" if granted else "denied"

    def fail_next(self, helper: str = "*", count: int = 1, *, message: str = "EventKit failed", exit_code: int = 1, stdout: str = "") -> None:
        """Make the next ``count`` runs of a helper ("export", "apply" or "*") fail."""

        with self._edit() as data:
            data["faults"].append(
                {"helper": helper, "remaining": int(count), "exit": int(exit_code), "stderr": message, "stdout": stdout}
            )

    def calls(self, helper: Optional[str] = None) -> List[Dict[str, Any]]:
        return [call for call in self.snapshot()["calls"] if helper is None or call["helper"] == helper]

    def clear_calls(self) -> None:
        with self._edit() as data:
            data["calls"] = []

    def run(self, helper: str, *argv: str, stdin: Any = b"") -> Tuple[int, Any, str]:
        """Run a helper in-process: (exit code, parsed stdout or None, stderr)."""

        if isinstance(stdin, (list, dict)):
            stdin = json.dumps(stdin).encode("utf-8")
        elif isinstance(stdin, str):
            stdin = stdin.encode("utf-8")
        exit_code, stdout, stderr = run_helper(self.path, helper, argv, stdin)
        return exit_code, (json.loads(stdout.decode("utf-8")) if stdout.strip() else None), stderr

    # Internals

    @staticmethod
    def _list_by_title(data: Dict[str, Any], title: str) -> Dict[str, Any]:
        matches = [item for item in data["lists"] if item["title"] == title]
        if len(matches) != 1:
            raise LookupError(f"{len(matches)} Reminders lists are titled {title!r}")
        return matches[0]

    @staticmethod
    def _select(data: Dict[str, Any], selector: str) -> Dict[str, Any]:
        key = normalize_identifier(selector)
        if len(key) == 32:
            for reminder in data["reminders"]:
                if key in (normalize_identifier(reminder.get("id")), normalize_identifier(reminder.get("external_id"))):
                    return reminder
        matches = [reminder for reminder in data["reminders"] if reminder.get("title") == selector]
        if len(matches) != 1:
            raise LookupError(f"{len(matches)} reminders match {selector!r}")
        return matches[0]

    @staticmethod
    def _view(data: Dict[str, Any], reminder: Dict[str, Any]) -> Dict[str, Any]:
        view = copy.deepcopy(reminder)
        reminder_list = _list(data, reminder["list_id"]) or {}
        view["list_title"] = reminder_list.get("title", "")
        view["stable_id"] = reminder.get("external_id") or reminder["id"]
        if reminder_list:
            account = _account(data, reminder_list["account_id"])
            view["account_title"], view["account_id"] = account["title"], account["id"]
        return view

    @staticmethod
    def _date_text(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = date_components(value)
        if text is None:
            raise ValueError(f"not a YYYY-MM-DD date: {value!r}")
        return text

    @staticmethod
    def _instant_text(value: Any) -> Optional[str]:
        if value is None:
            return None
        moment = parse_instant(value)
        if moment is None:
            raise ValueError(f"not an ISO 8601 timestamp: {value!r}")
        return iso(moment)


if __name__ == "__main__":
    sys.exit(main())
