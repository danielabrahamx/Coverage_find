"""Zetaris client: every dataset query goes through here.

    from coverage_detective.data.zetaris import query
    rows = query("SELECT cell_id, population FROM CD_CELLS.cells_r7 LIMIT 5")

Talks to the Zetaris web app (ZETARIS_URL, e.g. http://localhost:3000): it signs in at
/api/auth/login and sends SQL through its /api/proxy to the Zetaris API, as Zetaris's own
verify.sh does.
- query(sql): SELECT only (/query/sql/start, then /query/sql/page for more pages).
- execute(sql): any statement, e.g. CREATE LIGHTNING ... (the SQL editor's /sql-editor/sqls/run).

Zetaris returns every value as a string; query() turns numeric strings back into int/float
(except digit strings over 15 digits or with a leading zero, which are identifiers such as
Ookla quadkeys) and "null"/None into None. Every call is appended to logs/zetaris_queries.jsonl (time, SQL,
duration, row count, error) for the evidence trail, and the latest entries are kept in
QUERY_LOG.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections import deque
from datetime import datetime, timezone

import httpx

from coverage_detective.config import ROOT, env

LOG_PATH = ROOT / "logs" / "zetaris_queries.jsonl"
PAGE_LIMIT = 50_000
QUERY_LOG: deque[dict] = deque(maxlen=500)

_DIGITS = re.compile(r"-?\d+")
_INT = re.compile(r"-?(0|[1-9]\d*)")
_FLOAT = re.compile(r"-?\d+(\.\d+)?([eE][-+]?\d+)?|-?\d*\.\d+([eE][-+]?\d+)?")


class ZetarisError(RuntimeError):
    """A Zetaris call failed; the message says where and why."""


class _Session:
    def __init__(self) -> None:
        self.base = (env("ZETARIS_URL") or "").rstrip("/")
        self.headers: dict[str, str] | None = None

    def login(self, timeout: float) -> None:
        user, password = env("ZETARIS_USER"), env("ZETARIS_PASSWORD")
        if not (self.base and user and password):
            raise ZetarisError("Set ZETARIS_URL, ZETARIS_USER and ZETARIS_PASSWORD in .env")
        try:
            r = httpx.post(f"{self.base}/api/auth/login", json={"username": user, "password": password}, timeout=timeout)
        except httpx.HTTPError as e:
            raise ZetarisError(f"Cannot reach Zetaris at {self.base}: {e!r}. Is the stack up? (zetaris-platform/verify.sh)") from e
        if r.status_code != 200:
            raise ZetarisError(f"Zetaris login failed (HTTP {r.status_code}): {r.text[:200]}")
        body = r.json()
        self.headers = {"Authorization": f"Bearer {body['idToken']}", "X-Org-ID": str(body["orgId"])}

    def call(self, method: str, path: str, timeout: float, **kwargs) -> httpx.Response:
        """One API call, signing in first and once more if the token has expired."""
        for attempt in (1, 2):
            if self.headers is None:
                self.login(timeout)
            headers = {**self.headers, "X-Request-ID": str(uuid.uuid4())}
            try:
                r = httpx.request(method, f"{self.base}/api/proxy{path}", headers=headers, timeout=timeout, **kwargs)
            except httpx.TimeoutException as e:
                raise ZetarisError(f"Zetaris timed out after {timeout:.0f} s on {path}") from e
            except httpx.HTTPError as e:
                raise ZetarisError(f"Cannot reach Zetaris at {self.base}: {e!r}") from e
            if r.status_code in (401, 403) and attempt == 1:
                self.headers = None
                continue
            if r.status_code != 200:
                raise ZetarisError(f"Zetaris {path} returned HTTP {r.status_code}: {_error_text(r)}")
            return r
        raise AssertionError("unreachable")


_session = _Session()


def _error_text(r: httpx.Response) -> str:
    try:
        body = r.json()
        return str(body.get("msg", body))[:500]
    except ValueError:
        return r.text[:500]


def _coerce(value):
    if value is None or value == "null":
        return None
    if isinstance(value, str):
        if _DIGITS.fullmatch(value):
            # Long or zero-padded digit strings are identifiers (e.g. Ookla quadkeys).
            plain = _INT.fullmatch(value) and len(value.lstrip("-")) <= 15
            return int(value) if plain else value
        if _FLOAT.fullmatch(value):
            return float(value)
    return value


def _log(sql: str, started: float, rows: int | None, error: str | None) -> dict:
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sql": " ".join(sql.split()),
        "duration_ms": round(1000 * (time.perf_counter() - started)),
        "rows": rows,
        "error": error,
    }
    QUERY_LOG.append(entry)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def query(sql: str, timeout: float | None = None) -> list[dict]:
    """Run a SELECT through Zetaris and return every row as a dict."""
    timeout = timeout or float(env("ZETARIS_TIMEOUT", "120"))
    started = time.perf_counter()
    try:
        body = _session.call("POST", "/query/sql/start", timeout, json={"select": sql, "pageLimit": PAGE_LIMIT}).json()
        records = list(body.get("records", []))
        for page in range(2, int(body.get("totalPages") or 1) + 1):
            params = {"queryToken": body["queryToken"], "pageNumber": page, "pageLimit": PAGE_LIMIT}
            records += _session.call("GET", "/query/sql/page", timeout, params=params).json().get("records", [])
    except ZetarisError as e:
        _log(sql, started, None, str(e))
        raise
    rows = [{k: _coerce(v) for k, v in r.items()} for r in records]
    _log(sql, started, len(rows), None)
    return rows


def execute(sql: str, timeout: float | None = None) -> list[list]:
    """Run any statement (e.g. CREATE LIGHTNING ...) and return its result rows."""
    timeout = timeout or float(env("ZETARIS_TIMEOUT", "120"))
    started = time.perf_counter()
    try:
        body = _session.call(
            "POST", "/sql-editor/sqls/run", timeout,
            json={"sql": sql, "queryId": str(uuid.uuid4()), "source": "SqlEditor"},
        ).json()
    except ZetarisError as e:
        _log(sql, started, None, str(e))
        raise
    data = body.get("data", [])
    _log(sql, started, len(data), None)
    return data
