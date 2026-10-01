"""A fake of the Google OAuth 2.0 and Tasks v1 endpoints the engine talks to.

The server binds 127.0.0.1 on an ephemeral port and keeps every account,
token and task in memory behind one lock. It follows the documented Google
behaviour the engine depends on:

* OAuth: authorization-code exchange with PKCE (S256), the refresh-token
  grant, well-formed (unsigned) ID tokens, ``invalid_grant`` for revoked or
  unknown refresh tokens, and the userinfo and revocation endpoints. A small
  authorization endpoint plays the consent screen (``login`` decides which
  account signs in, whether the Tasks permission is unticked, or whether the
  user cancels).
* Tasks: task lists and tasks with ``maxResults``/``pageToken`` paging,
  ``showCompleted``/``showDeleted``/``showHidden`` filters, soft deletion
  (tombstones are returned only with ``showDeleted=true``), date-only ``due``
  values, a ``completed`` timestamp that follows ``status``, PATCH with JSON
  ``null`` clearing a field, unknown body fields rejected, and unset fields
  omitted from responses (an empty page has no ``items``).
* Every Tasks request needs ``Authorization: Bearer <valid access token>``:
  an expired or unknown token gets 401 (so the engine's refresh path runs)
  and a token without the Tasks scope gets 403.

Tests act as the person using Google Tasks through ``add_task``,
``edit_task``, ``complete_task`` and friends, inject faults (an HTTP error or
a dropped connection for the next N matching requests) and inspect a log of
every request the engine made.
"""
from __future__ import annotations

import base64
import contextlib
import dataclasses
import datetime as dt
import hashlib
import http.server
import json
import re
import secrets
import socket
import threading
import time
import urllib.parse
from typing import Any, Dict, Iterator, List, Optional, Tuple

TASKS_SCOPE = "https://www.googleapis.com/auth/tasks"
DEFAULT_SCOPES: Tuple[str, ...] = (TASKS_SCOPE, "openid", "email")
ISSUER = "https://accounts.google.com"
ACCESS_TOKEN_TTL_SECONDS = 3599
AUTH_CODE_TTL_SECONDS = 600
DEFAULT_LIST_TITLE = "My Tasks"
TASKS_PREFIX = "/tasks/v1"
SELF_LINK_BASE = "https://www.googleapis.com/tasks/v1"
TASKS_DEFAULT_PAGE_SIZE = 20
TASKS_MAX_PAGE_SIZE = 100
LISTS_DEFAULT_PAGE_SIZE = 1000
LISTS_MAX_PAGE_SIZE = 1000
WRITE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})

# Request paths (regular expressions) for fault injection and log queries.
TASKLISTS_PATH = r"^/tasks/v1/users/@me/lists$"
TASKS_PATH = r"^/tasks/v1/lists/[^/]+/tasks$"
TASK_PATH = r"^/tasks/v1/lists/[^/]+/tasks/[^/]+$"
TASKS_API_PATH = r"^/tasks/v1/"
TOKEN_PATH = r"^/token$"
USERINFO_PATH = r"^/userinfo$"
REVOKE_PATH = r"^/revoke$"

# "drop" closes the connection without answering and without touching any
# state; "drop_after_apply" performs the request and then drops the answer,
# like a response lost on the way back after Google accepted a write.
DROP_FAULTS = frozenset({"drop", "drop_after_apply"})
# "stale_write" answers a task PATCH/PUT with 200 and the unchanged task, as
# an eventually consistent backend can; the change is not applied.
STALE_WRITE_FAULT = "stale_write"
HTTP_FAULT_STATUSES = frozenset({400, 401, 403, 404, 409, 429, 500, 502, 503})

_TASK_FIELDS = frozenset({
    "kind", "id", "etag", "title", "updated", "selfLink", "parent", "position", "notes",
    "status", "due", "completed", "deleted", "hidden", "links", "webViewLink", "assignmentInfo",
})
_TASKLIST_FIELDS = frozenset({"kind", "id", "etag", "title", "updated", "selfLink"})
_TASK_STATUSES = frozenset({"needsAction", "completed"})

_ERROR_DETAILS = {
    400: ("INVALID_ARGUMENT", "invalid", "Invalid value."),
    401: (
        "UNAUTHENTICATED",
        "authError",
        "Request had invalid authentication credentials. Expected OAuth 2 access token, login cookie "
        "or other valid authentication credential.",
    ),
    403: ("PERMISSION_DENIED", "insufficientPermissions", "Request had insufficient authentication scopes."),
    404: ("NOT_FOUND", "notFound", "Requested entity was not found."),
    409: ("ABORTED", "conflict", "The operation was aborted."),
    429: ("RESOURCE_EXHAUSTED", "rateLimitExceeded", "Quota exceeded for quota metric 'Queries'."),
    500: ("INTERNAL", "backendError", "Internal error encountered."),
    502: ("UNAVAILABLE", "backendError", "Bad Gateway."),
    503: ("UNAVAILABLE", "backendError", "The service is currently unavailable."),
}


# --- Small helpers -----------------------------------------------------------


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def rfc3339_ms(epoch: float) -> str:
    """Google's timestamp format: UTC with milliseconds and a ``Z``."""

    moment = dt.datetime.fromtimestamp(epoch, dt.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


_RFC3339_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|z|[+-]\d{2}:\d{2})$"
)


def parse_rfc3339(value: str) -> dt.datetime:
    """Parse an RFC 3339 timestamp (Python 3.9's fromisoformat is too strict)."""

    match = _RFC3339_RE.match(str(value).strip())
    if not match:
        raise ValueError(f"not an RFC 3339 timestamp: {value!r}")
    date_text, time_text, fraction, offset = match.groups()
    micro = (fraction or "0")[:6].ljust(6, "0")
    offset = "+00:00" if offset in ("Z", "z") else offset
    return dt.datetime.fromisoformat(f"{date_text}T{time_text}.{micro}{offset}")


def normalize_due(value: Any, *, strict: bool) -> Optional[str]:
    """Return the ``YYYY-MM-DD`` a due value stands for, or None to clear it.

    Google keeps only the date of ``due``; the time portion is discarded. The
    API (``strict``) takes RFC 3339 timestamps; test helpers may pass a bare
    date or a ``datetime.date``.
    """

    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if not isinstance(value, str):
        raise ApiError(400, "Invalid value for: due")
    text = value.strip()
    try:
        if not strict and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return dt.date.fromisoformat(text).isoformat()
        parse_rfc3339(text)
        return dt.date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        raise ApiError(400, f"Invalid value for: due ({text!r} is not an RFC 3339 timestamp)") from None


def make_id_token(
    *,
    sub: str,
    email: str,
    client_id: str,
    issued_at: float,
    lifetime: int = 3600,
    access_token: Optional[str] = None,
) -> str:
    """A well-formed but unsigned OpenID Connect ID token (header.payload.signature)."""

    header = {"alg": "RS256", "kid": "fake-google-e2e", "typ": "JWT"}
    payload: Dict[str, Any] = {
        "iss": ISSUER,
        "azp": client_id,
        "aud": client_id,
        "sub": sub,
        "email": email,
        "email_verified": True,
        "iat": int(issued_at),
        "exp": int(issued_at) + lifetime,
    }
    if access_token:
        payload["at_hash"] = b64url(hashlib.sha256(access_token.encode("ascii")).digest()[:16])
    segments = [
        b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        b64url(secrets.token_bytes(32)),  # Not a real signature.
    ]
    return ".".join(segments)


def decode_jwt_payload(token: str) -> Dict[str, Any]:
    parts = str(token or "").split(".")
    if len(parts) != 3:
        raise ValueError("not a JWT")
    return json.loads(b64url_decode(parts[1]).decode("utf-8"))


def pkce_challenge(verifier: str) -> str:
    return b64url(hashlib.sha256(verifier.encode("ascii")).digest())


class ApiError(Exception):
    """An error answer in Google's JSON error format."""

    def __init__(self, status: int, message: Optional[str] = None, *, headers: Optional[Dict[str, str]] = None):
        status_name, reason, default_message = _ERROR_DETAILS.get(status, ("UNKNOWN", "unknown", "Error."))
        self.status = status
        self.message = message or default_message
        self.headers = dict(headers or {})
        self.payload = {
            "error": {
                "code": status,
                "message": self.message,
                "errors": [{"message": self.message, "domain": "global", "reason": reason}],
                "status": status_name,
            }
        }
        if status == 401:
            self.headers.setdefault(
                "WWW-Authenticate", 'Bearer realm="https://accounts.google.com/", error="invalid_token"'
            )
        super().__init__(f"HTTP {status}: {self.message}")

    def response(self) -> "_Response":
        return _Response.of_json(self.status, self.payload, headers=self.headers)


@dataclasses.dataclass
class _Response:
    status: int
    body: bytes = b""
    headers: Dict[str, str] = dataclasses.field(default_factory=dict)

    @classmethod
    def of_json(cls, status: int, payload: Any, *, headers: Optional[Dict[str, str]] = None) -> "_Response":
        merged = {"Content-Type": "application/json; charset=UTF-8"}
        merged.update(headers or {})
        return cls(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), merged)

    @classmethod
    def empty(cls, status: int = 204) -> "_Response":
        return cls(status)


def _oauth_error(status: int, error: str, description: str) -> _Response:
    return _Response.of_json(
        status,
        {"error": error, "error_description": description},
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


# --- State ------------------------------------------------------------------


@dataclasses.dataclass
class _Task:
    id: str
    position: str
    title: str = ""
    notes: Optional[str] = None
    status: str = "needsAction"
    due: Optional[str] = None  # YYYY-MM-DD
    completed: Optional[str] = None
    deleted: bool = False
    hidden: bool = False
    parent: Optional[str] = None
    updated: str = ""
    etag: str = ""


@dataclasses.dataclass
class _TaskList:
    id: str
    title: str
    updated: str
    etag: str
    tasks: Dict[str, _Task] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class _Account:
    sub: str
    email: str
    lists: Dict[str, _TaskList] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class _Client:
    client_id: str
    client_secret: str


@dataclasses.dataclass
class _RefreshToken:
    token: str
    sub: str
    client_id: str
    scopes: Tuple[str, ...]
    revoked: bool = False


@dataclasses.dataclass
class _AccessToken:
    token: str
    sub: str
    client_id: str
    scopes: Tuple[str, ...]
    expires_at: float
    refresh_token: Optional[str]
    revoked: bool = False


@dataclasses.dataclass
class _AuthCode:
    code: str
    sub: str
    client_id: str
    redirect_uri: str
    scopes: Tuple[str, ...]
    code_challenge: str
    code_challenge_method: str
    expires_at: float
    used: bool = False


@dataclasses.dataclass
class LoginBehaviour:
    """What the fake consent screen does with the next authorization request."""

    sub: Optional[str] = None  # None: the primary account signs in.
    untick_tasks: bool = False  # Grant everything except the Tasks scope.
    error: Optional[str] = None  # For example "access_denied" (the user cancelled).


@dataclasses.dataclass
class _Fault:
    method: str
    pattern: "re.Pattern[str]"
    kind: str
    remaining: int


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "FakeGoogle/1.0"
    sys_version = ""
    timeout = 15

    def _dispatch(self) -> None:
        self.server.fake._handle(self)  # type: ignore[attr-defined]

    do_GET = _dispatch
    do_POST = _dispatch
    do_PATCH = _dispatch
    do_PUT = _dispatch
    do_DELETE = _dispatch

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signature from the base class
        return


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class FakeGoogle:
    """Google OAuth + Tasks v1 on 127.0.0.1. Thread-safe; use as a context manager."""

    def __init__(self, *, max_page_size: Optional[int] = None) -> None:
        self._lock = threading.RLock()
        self._accounts: Dict[str, _Account] = {}
        self._primary_sub: Optional[str] = None
        self._clients: Dict[str, _Client] = {}
        self._refresh_tokens: Dict[str, _RefreshToken] = {}
        self._access_tokens: Dict[str, _AccessToken] = {}
        self._codes: Dict[str, _AuthCode] = {}
        self._faults: List[_Fault] = []
        self._log: List[Dict[str, Any]] = []
        self._last_ms = 0
        self._next_position = 10**19 - 1
        self._server: Optional[_Server] = None
        self._thread: Optional[threading.Thread] = None
        # A server-side page size cap on top of Google's own, so a test can
        # make the engine page through a handful of items.
        self.max_page_size = max_page_size
        self.access_token_ttl = ACCESS_TOKEN_TTL_SECONDS
        self.login = LoginBehaviour()
        # Shifts the fake's clock (timestamps, token expiry) by this many seconds.
        self.time_offset = 0.0

    # Lifecycle ----------------------------------------------------------------

    def start(self) -> "FakeGoogle":
        if self._server is not None:
            return self
        server = _Server(("127.0.0.1", 0), _Handler)
        server.fake = self  # type: ignore[attr-defined]
        self._server = server
        # A short poll interval keeps stop() (shutdown) fast.
        self._thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.05}, name="fake-google", daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> "FakeGoogle":
        return self.start()

    def __exit__(self, *_exc: Any) -> None:
        self.stop()

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("FakeGoogle is not running")
        return int(self._server.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def tasks_api_url(self) -> str:
        return self.base_url + TASKS_PREFIX

    @property
    def token_url(self) -> str:
        return self.base_url + "/token"

    @property
    def auth_url(self) -> str:
        return self.base_url + "/auth"

    @property
    def userinfo_url(self) -> str:
        return self.base_url + "/userinfo"

    @property
    def revoke_url(self) -> str:
        return self.base_url + "/revoke"

    # Clock and identifiers ------------------------------------------------------

    def now(self) -> float:
        return time.time() + self.time_offset

    def _stamp(self) -> str:
        """A strictly increasing ``updated`` value with millisecond precision."""

        ms = int(self.now() * 1000)
        if ms <= self._last_ms:
            ms = self._last_ms + 1
        self._last_ms = ms
        return rfc3339_ms(ms / 1000)

    @staticmethod
    def _new_id(size: int = 12) -> str:
        return b64url(secrets.token_bytes(size))

    @staticmethod
    def _etag() -> str:
        return '"' + b64url(secrets.token_bytes(9)) + '"'

    def _position(self) -> str:
        # New tasks go to the top of their list, as in Google Tasks.
        self._next_position -= 1
        return f"{self._next_position:020d}"

    # Accounts and OAuth clients -------------------------------------------------

    def add_account(self, sub: str, email: str, *, default_list: bool = True) -> None:
        with self._lock:
            if sub in self._accounts:
                raise ValueError(f"account {sub} exists")
            self._accounts[sub] = _Account(sub=sub, email=email)
            if self._primary_sub is None:
                self._primary_sub = sub
            if default_list:
                self._create_list(self._accounts[sub], DEFAULT_LIST_TITLE)

    def register_client(self, client_id: str, client_secret: str = "") -> None:
        with self._lock:
            self._clients[client_id] = _Client(client_id, client_secret)

    def _account(self, sub: Optional[str]) -> _Account:
        key = sub or self._primary_sub
        if key is None or key not in self._accounts:
            raise KeyError(f"unknown account {sub!r}")
        return self._accounts[key]

    def _default_client_id(self, client_id: Optional[str]) -> str:
        if client_id:
            return client_id
        if len(self._clients) != 1:
            raise ValueError("pass client_id: zero or several OAuth clients are registered")
        return next(iter(self._clients))

    # Tokens ------------------------------------------------------------------------

    def issue_tokens(
        self,
        sub: Optional[str] = None,
        client_id: Optional[str] = None,
        *,
        scopes: Tuple[str, ...] = DEFAULT_SCOPES,
        access_ttl: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Mint what an authorization-code exchange returns (access, refresh, ID token)."""

        with self._lock:
            account = self._account(sub)
            return self._grant(
                account.sub,
                self._default_client_id(client_id),
                tuple(scopes),
                with_refresh=True,
                access_ttl=access_ttl,
            )

    def _grant(
        self,
        sub: str,
        client_id: str,
        scopes: Tuple[str, ...],
        *,
        refresh_token: Optional[str] = None,
        with_refresh: bool,
        access_ttl: Optional[int] = None,
    ) -> Dict[str, Any]:
        if with_refresh:
            refresh_token = "1//e2e-" + self._new_id(32)
            self._refresh_tokens[refresh_token] = _RefreshToken(refresh_token, sub, client_id, scopes)
        ttl = int(self.access_token_ttl if access_ttl is None else access_ttl)
        access_token = "ya29.e2e-" + self._new_id(32)
        self._access_tokens[access_token] = _AccessToken(
            access_token, sub, client_id, scopes, self.now() + ttl, refresh_token
        )
        response: Dict[str, Any] = {
            "access_token": access_token,
            "expires_in": ttl,
            "scope": " ".join(scopes),
            "token_type": "Bearer",
        }
        if with_refresh:
            response["refresh_token"] = refresh_token
        if "openid" in scopes:
            response["id_token"] = make_id_token(
                sub=sub,
                email=self._accounts[sub].email,
                client_id=client_id,
                issued_at=self.now(),
                access_token=access_token,
            )
        return response

    def expire_access_tokens(self, sub: Optional[str] = None) -> int:
        """Expire every access token (of one account): the next API call gets 401."""

        with self._lock:
            count = 0
            for record in self._access_tokens.values():
                if sub is None or record.sub == sub:
                    record.expires_at = min(record.expires_at, self.now() - 1)
                    count += 1
            return count

    def revoke(self, token: str) -> bool:
        """Revoke a refresh or access token the way Google's revocation endpoint does."""

        with self._lock:
            return self._revoke_token(token)

    def _revoke_token(self, token: str) -> bool:
        access = self._access_tokens.get(token)
        refresh_key = access.refresh_token if access else token
        if access is not None:
            access.revoked = True
        refresh = self._refresh_tokens.get(refresh_key or "")
        if refresh is None:
            return access is not None
        refresh.revoked = True
        for record in self._access_tokens.values():
            if record.refresh_token == refresh.token:
                record.revoked = True
        return True

    def refresh_token_info(self, token: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._refresh_tokens.get(token)
            return dataclasses.asdict(record) if record else None

    def access_token_info(self, token: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._access_tokens.get(token)
            return dataclasses.asdict(record) if record else None

    # Faults and the request log --------------------------------------------------

    def inject_fault(self, method: str, path: str, kind: Any = 500, count: int = 1) -> None:
        """Make the next ``count`` requests matching ``method`` and the ``path``
        regex fail. ``kind`` is an HTTP status (e.g. 500, 503, 401), one of
        ``"drop"`` / ``"drop_after_apply"``, or ``"stale_write"``."""

        kind_text = str(kind)
        known = kind_text in DROP_FAULTS or kind_text == STALE_WRITE_FAULT
        if not known and not (kind_text.isdigit() and int(kind_text) in HTTP_FAULT_STATUSES):
            raise ValueError(f"unsupported fault kind {kind!r}")
        with self._lock:
            self._faults.append(_Fault(method.upper(), re.compile(path), kind_text, int(count)))

    def clear_faults(self) -> None:
        with self._lock:
            self._faults.clear()

    def pending_faults(self) -> int:
        with self._lock:
            return sum(fault.remaining for fault in self._faults)

    def _take_fault(self, method: str, path: str) -> Optional[_Fault]:
        for fault in self._faults:
            if fault.remaining > 0 and fault.method in ("*", method) and fault.pattern.search(path):
                fault.remaining -= 1
                if fault.remaining == 0:
                    self._faults.remove(fault)
                return fault
        return None

    def requests(self, method: Optional[str] = None, path: Optional[str] = None) -> List[Dict[str, Any]]:
        """Logged requests, optionally filtered by method and a path regex."""

        with self._lock:
            pattern = re.compile(path) if path else None
            return [
                dict(entry)
                for entry in self._log
                if (method is None or entry["method"] == method.upper())
                and (pattern is None or pattern.search(entry["path"]))
            ]

    def count(self, method: Optional[str] = None, path: Optional[str] = None) -> int:
        return len(self.requests(method, path))

    def write_requests(self) -> List[Dict[str, Any]]:
        """Every POST/PATCH/PUT/DELETE that reached the Tasks API, whatever its outcome."""

        with self._lock:
            return [
                dict(entry)
                for entry in self._log
                if entry["method"] in WRITE_METHODS and entry["path"].startswith(TASKS_PREFIX + "/")
            ]

    def clear_requests(self) -> None:
        with self._lock:
            self._log.clear()

    # The person using Google Tasks ---------------------------------------------------

    def add_list(self, title: str, *, sub: Optional[str] = None) -> str:
        with self._lock:
            return self._create_list(self._account(sub), title).id

    def lists(self, *, sub: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            return [self._tasklist_resource(tasklist) for tasklist in self._account(sub).lists.values()]

    def find_list(self, title: str, *, sub: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            tasklist = self._list_by_title(self._account(sub), title)
            return self._tasklist_resource(tasklist) if tasklist else None

    def add_task(
        self,
        list_title: str,
        title: str,
        *,
        notes: Optional[str] = None,
        due: Any = None,
        status: str = "needsAction",
        completed: Optional[str] = None,
        hidden: bool = False,
        updated: Optional[str] = None,
        sub: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            tasklist = self._require_list_by_title(self._account(sub), list_title)
            if status not in _TASK_STATUSES:
                raise ValueError(f"bad status {status!r}")
            task = _Task(id=self._new_id(), position=self._position(), title=title, notes=notes or None)
            task.due = normalize_due(due, strict=False)
            task.status = status
            if status == "completed":
                task.completed = completed or self._stamp()
                task.hidden = hidden
            self._touch(task, updated)
            tasklist.tasks[task.id] = task
            return self._task_resource(tasklist.id, task)

    def edit_task(
        self,
        task: str,
        *,
        sub: Optional[str] = None,
        updated: Optional[str] = None,
        **changes: Any,
    ) -> Dict[str, Any]:
        """Change a task as the Google Tasks app would. ``task`` is an ID or a title.

        Supported changes: ``title``, ``notes``, ``due`` (None clears it),
        ``status``, ``hidden`` and ``deleted``. ``updated`` pins the timestamp.
        """

        unknown = set(changes) - {"title", "notes", "due", "status", "hidden", "deleted"}
        if unknown:
            raise TypeError(f"unsupported task changes: {sorted(unknown)}")
        with self._lock:
            tasklist, record = self._select_task(self._account(sub), task)
            if "title" in changes:
                record.title = str(changes["title"] or "")
            if "notes" in changes:
                record.notes = changes["notes"] or None
            if "due" in changes:
                record.due = normalize_due(changes["due"], strict=False)
            if "status" in changes:
                self._set_status(record, str(changes["status"]))
            if "hidden" in changes:
                record.hidden = bool(changes["hidden"])
            if "deleted" in changes:
                record.deleted = bool(changes["deleted"])
            self._touch(record, updated)
            return self._task_resource(tasklist.id, record)

    def complete_task(
        self,
        task: str,
        *,
        hidden: bool = True,
        sub: Optional[str] = None,
        updated: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Complete a task in a first-party client: Google also marks it hidden,
        so only ``showHidden=true`` returns it."""

        with self._lock:
            tasklist, record = self._select_task(self._account(sub), task)
            self._set_status(record, "completed")
            record.hidden = hidden
            self._touch(record, updated)
            return self._task_resource(tasklist.id, record)

    def uncomplete_task(self, task: str, *, sub: Optional[str] = None, updated: Optional[str] = None) -> Dict[str, Any]:
        return self.edit_task(task, sub=sub, updated=updated, status="needsAction")

    def delete_task(self, task: str, *, sub: Optional[str] = None, updated: Optional[str] = None) -> Dict[str, Any]:
        """Delete a task in Google Tasks: it becomes a tombstone (``deleted: true``)."""

        with self._lock:
            tasklist, record = self._select_task(self._account(sub), task)
            record.deleted = True
            self._touch(record, updated)
            return self._task_resource(tasklist.id, record)

    def purge_deleted(self, *, sub: Optional[str] = None) -> int:
        """Forget tombstones, as Google eventually does."""

        with self._lock:
            removed = 0
            for tasklist in self._account(sub).lists.values():
                for task_id in [task_id for task_id, task in tasklist.tasks.items() if task.deleted]:
                    del tasklist.tasks[task_id]
                    removed += 1
            return removed

    def tasks(
        self,
        list_title: str = DEFAULT_LIST_TITLE,
        *,
        include_deleted: bool = False,
        sub: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """API-shaped copies of a list's tasks (completed and hidden included)."""

        with self._lock:
            tasklist = self._require_list_by_title(self._account(sub), list_title)
            return [
                self._task_resource(tasklist.id, task)
                for task in sorted(tasklist.tasks.values(), key=lambda task: task.position)
                if include_deleted or not task.deleted
            ]

    def find_task(
        self,
        title: str,
        list_title: Optional[str] = None,
        *,
        include_deleted: bool = False,
        sub: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """The one task with this title, None if there is none; LookupError if several."""

        with self._lock:
            matches = []
            for tasklist in self._account(sub).lists.values():
                if list_title is not None and tasklist.title != list_title:
                    continue
                for task in tasklist.tasks.values():
                    if task.title == title and (include_deleted or not task.deleted):
                        matches.append(self._task_resource(tasklist.id, task))
            if len(matches) > 1:
                raise LookupError(f"{len(matches)} Google tasks are titled {title!r}")
            return matches[0] if matches else None

    def get_task(self, task_id: str, *, sub: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            for tasklist in self._account(sub).lists.values():
                if task_id in tasklist.tasks:
                    return self._task_resource(tasklist.id, tasklist.tasks[task_id])
            raise KeyError(task_id)

    # Internals: lists and tasks ------------------------------------------------------------

    def _create_list(self, account: _Account, title: str) -> _TaskList:
        tasklist = _TaskList(id=self._new_id(24), title=title, updated=self._stamp(), etag=self._etag())
        account.lists[tasklist.id] = tasklist
        return tasklist

    @staticmethod
    def _list_by_title(account: _Account, title: str) -> Optional[_TaskList]:
        for tasklist in account.lists.values():
            if tasklist.title == title:
                return tasklist
        return None

    def _require_list_by_title(self, account: _Account, title: str) -> _TaskList:
        tasklist = self._list_by_title(account, title)
        if tasklist is None:
            raise KeyError(f"no Google task list titled {title!r}")
        return tasklist

    def _select_task(self, account: _Account, selector: str) -> Tuple[_TaskList, _Task]:
        for tasklist in account.lists.values():
            if selector in tasklist.tasks:
                return tasklist, tasklist.tasks[selector]
        matches = [
            (tasklist, task)
            for tasklist in account.lists.values()
            for task in tasklist.tasks.values()
            if task.title == selector and not task.deleted
        ]
        if len(matches) != 1:
            raise LookupError(f"{len(matches)} Google tasks match {selector!r}")
        return matches[0]

    def _touch(self, task: _Task, updated: Optional[str] = None) -> None:
        if updated is not None:
            parse_rfc3339(updated)
        task.updated = updated or self._stamp()
        task.etag = self._etag()

    def _set_status(self, task: _Task, status: str, completed: Optional[str] = None) -> None:
        if status not in _TASK_STATUSES:
            raise ApiError(400, "Invalid value for: status")
        if status == "completed":
            if task.status != "completed" or not task.completed or completed:
                task.completed = completed or self._stamp()
        else:
            task.completed = None
            task.hidden = False
        task.status = status

    @staticmethod
    def _tasklist_resource(tasklist: _TaskList) -> Dict[str, Any]:
        return {
            "kind": "tasks#taskList",
            "id": tasklist.id,
            "etag": tasklist.etag,
            "title": tasklist.title,
            "updated": tasklist.updated,
            "selfLink": f"{SELF_LINK_BASE}/users/@me/lists/{tasklist.id}",
        }

    @staticmethod
    def _task_resource(list_id: str, task: _Task) -> Dict[str, Any]:
        resource: Dict[str, Any] = {
            "kind": "tasks#task",
            "id": task.id,
            "etag": task.etag,
            "title": task.title,
            "updated": task.updated,
            "selfLink": f"{SELF_LINK_BASE}/lists/{list_id}/tasks/{task.id}",
        }
        if task.parent:
            resource["parent"] = task.parent
        resource["position"] = task.position
        if task.notes:
            resource["notes"] = task.notes
        resource["status"] = task.status
        if task.due:
            resource["due"] = f"{task.due}T00:00:00.000Z"
        if task.completed:
            resource["completed"] = task.completed
        if task.deleted:
            resource["deleted"] = True
        if task.hidden:
            resource["hidden"] = True
        resource["links"] = []
        resource["webViewLink"] = f"https://tasks.google.com/task/{task.id}?sa=6"
        return resource

    # HTTP --------------------------------------------------------------------------------

    def _handle(self, handler: _Handler) -> None:
        method = handler.command.upper()
        target = handler.path
        via_proxy = target.startswith(("http://", "https://"))
        if via_proxy:
            absolute = urllib.parse.urlsplit(target)
            target = absolute.path + (f"?{absolute.query}" if absolute.query else "")
        split = urllib.parse.urlsplit(target)
        path = urllib.parse.unquote(split.path)
        query = {key: values[-1] for key, values in urllib.parse.parse_qs(split.query, keep_blank_values=True).items()}
        length = int(handler.headers.get("Content-Length") or 0)
        raw_body = handler.rfile.read(length) if length > 0 else b""

        with self._lock:
            entry: Dict[str, Any] = {
                "seq": len(self._log) + 1,
                "method": method,
                "path": path,
                "query": query,
                "body": _decode_body(raw_body, handler.headers.get("Content-Type") or ""),
                "status": None,
                "sub": None,
                "fault": None,
                "via_proxy": via_proxy,
                "at": self.now(),
            }
            fault = self._take_fault(method, path)
            response: Optional[_Response] = None
            if fault is not None:
                entry["fault"] = fault.kind
            if fault is not None and fault.kind == STALE_WRITE_FAULT:
                try:
                    response = self._stale_write(method, path, handler)
                except ApiError as exc:
                    response = exc.response()
            elif fault is not None and fault.kind not in DROP_FAULTS:
                response = ApiError(int(fault.kind)).response()
            elif fault is None or fault.kind == "drop_after_apply":
                try:
                    response = self._route(method, path, query, raw_body, handler, entry)
                except ApiError as exc:
                    response = exc.response()
            if fault is not None and fault.kind in DROP_FAULTS:
                response = None
            entry["status"] = response.status if response is not None else "dropped"
            self._log.append(entry)

        if response is None:
            handler.close_connection = True
            with contextlib.suppress(OSError):
                handler.connection.shutdown(socket.SHUT_RDWR)
            return
        handler.send_response(response.status)
        for name, value in response.headers.items():
            handler.send_header(name, value)
        handler.send_header("Content-Length", str(len(response.body)))
        handler.end_headers()
        if response.body:
            handler.wfile.write(response.body)

    def _route(
        self,
        method: str,
        path: str,
        query: Dict[str, str],
        raw_body: bytes,
        handler: _Handler,
        entry: Dict[str, Any],
    ) -> _Response:
        if path == "/token":
            self._require_method(method, "POST")
            return self._token_endpoint(raw_body)
        if path == "/auth":
            self._require_method(method, "GET")
            return self._authorize(query)
        if path == "/userinfo":
            self._require_method(method, "GET")
            return self._userinfo(handler.headers.get("Authorization") or "", entry)
        if path == "/revoke":
            self._require_method(method, "POST")
            return self._revoke_endpoint(query, raw_body)
        if path.startswith(TASKS_PREFIX + "/"):
            account = self._authenticate(handler.headers.get("Authorization") or "")
            entry["sub"] = account.sub
            return self._tasks_api(account, method, path[len(TASKS_PREFIX):], query, raw_body)
        raise ApiError(404)

    def _stale_write(self, method: str, path: str, handler: _Handler) -> _Response:
        match = re.fullmatch(TASKS_PREFIX + r"/lists/([^/]+)/tasks/([^/]+)", path)
        if method not in ("PATCH", "PUT") or not match:
            raise ApiError(400, "stale_write faults apply to task PATCH/PUT requests only")
        account = self._authenticate(handler.headers.get("Authorization") or "")
        tasklist = self._tasklist(account, match.group(1))
        task = tasklist.tasks.get(match.group(2))
        if task is None:
            raise ApiError(404)
        return _Response.of_json(200, self._task_resource(tasklist.id, task))

    @staticmethod
    def _require_method(method: str, expected: str) -> None:
        if method != expected:
            raise ApiError(404)

    # OAuth endpoints ------------------------------------------------------------------------

    def _token_endpoint(self, raw_body: bytes) -> _Response:
        form = _form_fields(raw_body)
        client = self._clients.get(form.get("client_id", ""))
        if client is None:
            return _oauth_error(401, "invalid_client", "The OAuth client was not found.")
        if client.client_secret and form.get("client_secret") != client.client_secret:
            return _oauth_error(401, "invalid_client", "Unauthorized")
        grant_type = form.get("grant_type", "")
        if grant_type == "authorization_code":
            return self._exchange_code(client, form)
        if grant_type == "refresh_token":
            record = self._refresh_tokens.get(form.get("refresh_token", ""))
            if record is None or record.revoked:
                return _oauth_error(400, "invalid_grant", "Token has been expired or revoked.")
            if record.client_id != client.client_id:
                return _oauth_error(401, "unauthorized_client", "Unauthorized")
            grant = self._grant(record.sub, client.client_id, record.scopes, refresh_token=record.token, with_refresh=False)
            return _Response.of_json(200, grant, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
        return _oauth_error(400, "unsupported_grant_type", f"Invalid grant_type: {grant_type}")

    def _exchange_code(self, client: _Client, form: Dict[str, str]) -> _Response:
        code = self._codes.get(form.get("code", ""))
        if code is None or code.used or code.expires_at < self.now():
            return _oauth_error(400, "invalid_grant", "Malformed auth code.")
        if code.client_id != client.client_id:
            return _oauth_error(400, "invalid_grant", "Bad Request")
        if form.get("redirect_uri", "") != code.redirect_uri:
            return _oauth_error(400, "redirect_uri_mismatch", "Bad Request")
        if code.code_challenge:
            verifier = form.get("code_verifier", "")
            if not re.fullmatch(r"[A-Za-z0-9\-._~]{43,128}", verifier):
                return _oauth_error(400, "invalid_request", "Invalid code verifier.")
            expected = pkce_challenge(verifier) if code.code_challenge_method == "S256" else verifier
            if expected != code.code_challenge:
                return _oauth_error(400, "invalid_grant", "Invalid code verifier.")
        code.used = True
        grant = self._grant(code.sub, client.client_id, code.scopes, with_refresh=True)
        return _Response.of_json(200, grant, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    def _authorize(self, query: Dict[str, str]) -> _Response:
        client_id = query.get("client_id", "")
        if client_id not in self._clients:
            return _html(401, "Error 401: invalid_client")
        redirect_uri = query.get("redirect_uri", "")
        parsed = urllib.parse.urlsplit(redirect_uri)
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            return _html(400, "Error 400: redirect_uri_mismatch")
        if query.get("response_type") != "code":
            return _html(400, "Error 400: unsupported_response_type")
        scopes = tuple(scope for scope in query.get("scope", "").split() if scope)
        if not scopes:
            return _html(400, "Error 400: invalid_request (missing scope)")
        method = query.get("code_challenge_method", "plain" if query.get("code_challenge") else "")
        if query.get("code_challenge") and method not in ("S256", "plain"):
            return _html(400, "Error 400: invalid_request (code_challenge_method)")
        params: Dict[str, str] = {}
        if query.get("state") is not None:
            params["state"] = query["state"]
        login = self.login
        if login.error:
            params["error"] = login.error
            return _redirect(redirect_uri, params)
        account = self._account(login.sub)
        granted = tuple(scope for scope in scopes if not (login.untick_tasks and scope == TASKS_SCOPE))
        code = "4/e2e-" + self._new_id(24)
        self._codes[code] = _AuthCode(
            code=code,
            sub=account.sub,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scopes=granted,
            code_challenge=query.get("code_challenge", ""),
            code_challenge_method=method,
            expires_at=self.now() + AUTH_CODE_TTL_SECONDS,
        )
        params.update({"code": code, "scope": " ".join(granted), "authuser": "0", "prompt": "consent"})
        return _redirect(redirect_uri, params)

    def _valid_access_token(self, authorization: str) -> Optional[_AccessToken]:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return None
        record = self._access_tokens.get(token.strip())
        if record is None or record.revoked or record.expires_at <= self.now():
            return None
        return record

    def _userinfo(self, authorization: str, entry: Dict[str, Any]) -> _Response:
        record = self._valid_access_token(authorization)
        if record is None:
            return _oauth_error(401, "invalid_request", "Invalid Credentials")
        entry["sub"] = record.sub
        payload: Dict[str, Any] = {"sub": record.sub}
        if "email" in record.scopes or "https://www.googleapis.com/auth/userinfo.email" in record.scopes:
            payload["email"] = self._accounts[record.sub].email
            payload["email_verified"] = True
        return _Response.of_json(200, payload)

    def _revoke_endpoint(self, query: Dict[str, str], raw_body: bytes) -> _Response:
        token = query.get("token") or _form_fields(raw_body).get("token", "")
        if not token or not self._revoke_token(token):
            return _oauth_error(400, "invalid_token", "Token expired or revoked")
        return _Response.of_json(200, {})

    def _authenticate(self, authorization: str) -> _Account:
        if not authorization.strip():
            raise ApiError(
                401,
                "Request is missing required authentication credential. Expected OAuth 2 access token, "
                "login cookie or other valid authentication credential.",
            )
        record = self._valid_access_token(authorization)
        if record is None:
            raise ApiError(401)
        if TASKS_SCOPE not in record.scopes:
            raise ApiError(403)
        return self._accounts[record.sub]

    # Tasks API --------------------------------------------------------------------------------

    def _tasks_api(
        self,
        account: _Account,
        method: str,
        path: str,
        query: Dict[str, str],
        raw_body: bytes,
    ) -> _Response:
        if path == "/users/@me/lists":
            if method == "GET":
                return self._list_tasklists(account, query)
            if method == "POST":
                return self._insert_tasklist(account, raw_body)
        match = re.fullmatch(r"/users/@me/lists/([^/]+)", path)
        if match:
            tasklist = self._tasklist(account, match.group(1))
            if method == "GET":
                return _Response.of_json(200, self._tasklist_resource(tasklist))
            if method in ("PATCH", "PUT"):
                body = _json_object(raw_body)
                _reject_unknown_fields(body, _TASKLIST_FIELDS)
                if "title" in body or method == "PUT":
                    tasklist.title = _string_field(body.get("title"), "title")
                tasklist.updated, tasklist.etag = self._stamp(), self._etag()
                return _Response.of_json(200, self._tasklist_resource(tasklist))
            if method == "DELETE":
                del account.lists[tasklist.id]
                return _Response.empty()
        match = re.fullmatch(r"/lists/([^/]+)/tasks", path)
        if match:
            tasklist = self._tasklist(account, match.group(1))
            if method == "GET":
                return self._list_tasks(tasklist, query)
            if method == "POST":
                return self._insert_task(tasklist, query, raw_body)
        match = re.fullmatch(r"/lists/([^/]+)/tasks/([^/]+)", path)
        if match:
            tasklist = self._tasklist(account, match.group(1))
            task = tasklist.tasks.get(match.group(2))
            if task is None:
                raise ApiError(404)
            if method == "GET":
                return _Response.of_json(200, self._task_resource(tasklist.id, task))
            if method in ("PATCH", "PUT"):
                self._write_task_fields(task, _json_object(raw_body), full=method == "PUT")
                self._touch(task)
                return _Response.of_json(200, self._task_resource(tasklist.id, task))
            if method == "DELETE":
                if not task.deleted:
                    task.deleted = True
                    self._touch(task)
                return _Response.empty()
        match = re.fullmatch(r"/lists/([^/]+)/clear", path)
        if match and method == "POST":
            tasklist = self._tasklist(account, match.group(1))
            for task in tasklist.tasks.values():
                if task.status == "completed" and not task.hidden:
                    task.hidden = True
                    self._touch(task)
            return _Response.empty()
        raise ApiError(404)

    @staticmethod
    def _tasklist(account: _Account, list_id: str) -> _TaskList:
        tasklist = account.lists.get(list_id)
        if tasklist is None:
            raise ApiError(404)
        return tasklist

    def _list_tasklists(self, account: _Account, query: Dict[str, str]) -> _Response:
        items = [self._tasklist_resource(tasklist) for tasklist in account.lists.values()]
        page, next_token = self._paginate(items, query, LISTS_DEFAULT_PAGE_SIZE, LISTS_MAX_PAGE_SIZE)
        body: Dict[str, Any] = {"kind": "tasks#taskLists", "etag": self._etag()}
        if next_token:
            body["nextPageToken"] = next_token
        if page:
            body["items"] = page
        return _Response.of_json(200, body)

    def _insert_tasklist(self, account: _Account, raw_body: bytes) -> _Response:
        body = _json_object(raw_body)
        _reject_unknown_fields(body, _TASKLIST_FIELDS)
        tasklist = self._create_list(account, _string_field(body.get("title"), "title"))
        return _Response.of_json(200, self._tasklist_resource(tasklist))

    def _list_tasks(self, tasklist: _TaskList, query: Dict[str, str]) -> _Response:
        show_completed = _bool_param(query, "showCompleted", True)
        show_deleted = _bool_param(query, "showDeleted", False)
        show_hidden = _bool_param(query, "showHidden", False)
        updated_min = None
        if query.get("updatedMin"):
            try:
                updated_min = parse_rfc3339(query["updatedMin"])
            except ValueError:
                raise ApiError(400, "Invalid value for: updatedMin") from None
        items = []
        for task in sorted(tasklist.tasks.values(), key=lambda task: task.position):
            if task.deleted and not show_deleted:
                continue
            if task.hidden and not show_hidden:
                continue
            if task.status == "completed" and not show_completed:
                continue
            if updated_min is not None and parse_rfc3339(task.updated) < updated_min:
                continue
            items.append(self._task_resource(tasklist.id, task))
        page, next_token = self._paginate(items, query, TASKS_DEFAULT_PAGE_SIZE, TASKS_MAX_PAGE_SIZE)
        body: Dict[str, Any] = {"kind": "tasks#tasks", "etag": self._etag()}
        if next_token:
            body["nextPageToken"] = next_token
        if page:
            body["items"] = page
        return _Response.of_json(200, body)

    def _insert_task(self, tasklist: _TaskList, query: Dict[str, str], raw_body: bytes) -> _Response:
        body = _json_object(raw_body)
        task = _Task(id=self._new_id(), position=self._position())
        self._write_task_fields(task, body, full=True)
        parent = query.get("parent")
        if parent:
            if parent not in tasklist.tasks:
                raise ApiError(400, "Invalid value for: parent")
            task.parent = parent
        self._touch(task)
        tasklist.tasks[task.id] = task
        return _Response.of_json(200, self._task_resource(tasklist.id, task))

    def _write_task_fields(self, task: _Task, body: Dict[str, Any], *, full: bool) -> None:
        """Apply a request body. ``full`` (insert, PUT) resets unspecified fields."""

        _reject_unknown_fields(body, _TASK_FIELDS)
        if full:
            values = {
                "title": body.get("title"),
                "notes": body.get("notes"),
                "due": body.get("due"),
                "status": body.get("status") or "needsAction",
                "completed": body.get("completed"),
                "deleted": body.get("deleted", False),
            }
        else:
            values = {
                key: body[key] for key in ("title", "notes", "due", "status", "completed", "deleted") if key in body
            }
        # Validate everything before changing anything.
        title = _string_field(values["title"], "title") if "title" in values else None
        notes = _optional_string(values["notes"], "notes") if "notes" in values else None
        due = normalize_due(values["due"], strict=True) if "due" in values else None
        status = values.get("status")
        if status is not None and status not in _TASK_STATUSES:
            raise ApiError(400, "Invalid value for: status")
        completed = values.get("completed")
        if completed is not None:
            if not isinstance(completed, str):
                raise ApiError(400, "Invalid value for: completed")
            try:
                completed = rfc3339_ms(parse_rfc3339(completed).timestamp())
            except ValueError:
                raise ApiError(400, "Invalid value for: completed") from None
        deleted = values.get("deleted")
        if deleted is not None and not isinstance(deleted, bool):
            raise ApiError(400, "Invalid value for: deleted")

        if "title" in values:
            task.title = title or ""
        if "notes" in values:
            task.notes = notes or None
        if "due" in values:
            task.due = due
        if status is not None:
            self._set_status(task, status, completed)
        elif completed and task.status == "completed":
            task.completed = completed
        if deleted is not None:
            task.deleted = deleted

    def _paginate(
        self,
        items: List[Dict[str, Any]],
        query: Dict[str, str],
        default_size: int,
        max_size: int,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        raw_size = query.get("maxResults")
        size = default_size
        if raw_size is not None:
            try:
                size = int(raw_size)
            except ValueError:
                raise ApiError(400, "Invalid value for: maxResults") from None
            if size < 1:
                raise ApiError(400, "Invalid value for: maxResults")
        size = min(size, max_size, self.max_page_size or max_size)
        offset = 0
        token = query.get("pageToken")
        if token:
            try:
                offset = int(json.loads(b64url_decode(token).decode("utf-8"))["offset"])
            except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                raise ApiError(400, "Invalid value for: pageToken") from None
            if offset < 0:
                raise ApiError(400, "Invalid value for: pageToken")
        return items[offset:offset + size], _page_token(offset + size) if offset + size < len(items) else None


def _page_token(offset: int) -> str:
    return b64url(json.dumps({"offset": offset}).encode("utf-8"))


def _decode_body(raw: bytes, content_type: str) -> Any:
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    if "json" in content_type:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    if "x-www-form-urlencoded" in content_type:
        return _form_fields(raw)
    return text


def _form_fields(raw: bytes) -> Dict[str, str]:
    parsed = urllib.parse.parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


def _json_object(raw: bytes) -> Dict[str, Any]:
    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ApiError(400, "Invalid JSON payload received.") from None
    if not isinstance(body, dict):
        raise ApiError(400, "Invalid JSON payload received. Expected an object.")
    return body


def _reject_unknown_fields(body: Dict[str, Any], known: frozenset) -> None:
    unknown = sorted(set(body) - known)
    if unknown:
        raise ApiError(400, f'Invalid JSON payload received. Unknown name "{unknown[0]}": Cannot find field.')


def _string_field(value: Any, name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ApiError(400, f"Invalid value for: {name}")
    return value


def _optional_string(value: Any, name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError(400, f"Invalid value for: {name}")
    return value


def _bool_param(query: Dict[str, str], name: str, default: bool) -> bool:
    value = query.get(name)
    if value is None:
        return default
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise ApiError(400, f"Invalid value for: {name}")


def _html(status: int, message: str) -> _Response:
    body = f"<!doctype html><title>{message}</title><p>{message}</p>".encode("utf-8")
    return _Response(status, body, {"Content-Type": "text/html; charset=UTF-8"})


def _redirect(redirect_uri: str, params: Dict[str, str]) -> _Response:
    separator = "&" if "?" in redirect_uri else "?"
    return _Response(302, b"", {"Location": redirect_uri + separator + urllib.parse.urlencode(params)})


@contextlib.contextmanager
def running(**kwargs: Any) -> Iterator[FakeGoogle]:
    fake = FakeGoogle(**kwargs).start()
    try:
        yield fake
    finally:
        fake.stop()
