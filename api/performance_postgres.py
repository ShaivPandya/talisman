"""Psycopg instrumentation, imported lazily to keep Postgres optional at import."""

import hashlib
import os
import re
import time
import traceback
from functools import lru_cache
from pathlib import Path

from api.performance import count, emit, measure

_REPO_ROOT = Path(__file__).resolve().parents[1]
# Frames that only forward a statement; the slow-statement caller is the first frame outside these.
_PASS_THROUGH_FILES = {"api/performance_postgres.py", "api/postgres.py", "api/performance.py"}
_DEFAULT_SLOW_STATEMENT_MS = 1000.0


def _slow_statement_threshold_ms() -> float:
    try:
        return float(os.getenv("DB_SLOW_STATEMENT_MS") or _DEFAULT_SLOW_STATEMENT_MS)
    except ValueError:
        return _DEFAULT_SLOW_STATEMENT_MS


def _statement_text(query: object) -> str:
    if isinstance(query, bytes):
        return query.decode("utf-8", "replace")
    as_string = getattr(query, "as_string", None)
    if callable(as_string):
        try:
            return str(as_string(None))
        except Exception:
            return repr(query)
    return str(query)


def _statement_caller() -> str:
    """Return the first repo frame that issued the statement, as path:line function."""
    for frame in reversed(traceback.extract_stack()):
        try:
            relative = Path(frame.filename).resolve().relative_to(_REPO_ROOT).as_posix()
        except ValueError:
            continue
        if relative in _PASS_THROUGH_FILES or relative.startswith(".venv/"):
            continue
        return f"{relative}:{frame.lineno} {frame.name}"
    return "unknown"


def _report_if_slow(query: object, started: float, *, batch: bool) -> None:
    duration_ms = (time.perf_counter() - started) * 1000
    if duration_ms < _slow_statement_threshold_ms():
        return
    try:
        text = _statement_text(query)
        verb = re.match(r"\s*(\w+)", text)
        normalized = re.sub(r"\s+", " ", text).strip()
        # SQL text and parameters stay out of logs; the caller and a stable hash identify the statement.
        emit(
            "db_slow_statement",
            duration_ms=duration_ms,
            caller=_statement_caller(),
            statement_kind=verb.group(1).upper() if verb else "UNKNOWN",
            statement_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12],
            batch=batch,
        )
    except Exception:
        pass


@lru_cache(maxsize=1)
def timing_cursor_class():
    from psycopg import Cursor

    class TimingCursor(Cursor):
        def execute(self, query, *args, **kwargs):
            count("db_calls")
            started = time.perf_counter()
            try:
                with measure("db_ms"):
                    return super().execute(query, *args, **kwargs)
            finally:
                _report_if_slow(query, started, batch=False)

        def executemany(self, query, *args, **kwargs):
            count("db_calls")
            started = time.perf_counter()
            try:
                with measure("db_ms"):
                    return super().executemany(query, *args, **kwargs)
            finally:
                _report_if_slow(query, started, batch=True)

    return TimingCursor
