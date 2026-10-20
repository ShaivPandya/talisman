"""Psycopg instrumentation, imported lazily to keep Postgres optional at import."""

from functools import lru_cache

from api.performance import count, measure


@lru_cache(maxsize=1)
def timing_cursor_class():
    from psycopg import Cursor

    class TimingCursor(Cursor):
        def execute(self, *args, **kwargs):
            count("db_calls")
            with measure("db_ms"):
                return super().execute(*args, **kwargs)

        def executemany(self, *args, **kwargs):
            count("db_calls")
            with measure("db_ms"):
                return super().executemany(*args, **kwargs)

    return TimingCursor
