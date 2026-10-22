from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from psycopg import InterfaceError, OperationalError, ProgrammingError
from psycopg_pool import PoolClosed, PoolTimeout, TooManyRequests

from api import postgres
from api.postgres_state import PostgresStateConnection


def test_use_postgres_state_rejects_sqlite_without_explicit_test_override(monkeypatch):
    monkeypatch.setenv("STATE_DB_BACKEND", "sqlite")
    monkeypatch.delenv("TALISMAN_ALLOW_SQLITE_STATE", raising=False)
    with pytest.raises(RuntimeError, match="Postgres-only"):
        postgres.use_postgres_state()


def test_use_postgres_state_allows_sqlite_with_explicit_test_override(monkeypatch):
    monkeypatch.setenv("STATE_DB_BACKEND", "sqlite")
    monkeypatch.setenv("TALISMAN_ALLOW_SQLITE_STATE", "true")
    assert postgres.use_postgres_state() is False


def test_pool_configures_vector_once_without_checkout_probe(monkeypatch):
    import pgvector.psycopg
    import psycopg_pool

    constructor = Mock()
    register = Mock()
    monkeypatch.setattr(psycopg_pool, "ConnectionPool", constructor)
    monkeypatch.setattr(pgvector.psycopg, "register_vector", register)
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    monkeypatch.setenv("POSTGRES_POOL_MIN_SIZE", "0")
    monkeypatch.setenv("POSTGRES_POOL_MAX_SIZE", "2")
    postgres._new_pool()
    options = constructor.call_args.kwargs
    assert "check" not in options
    assert options["max_size"] == 2
    connection = Mock()
    options["configure"](connection)
    register.assert_called_once_with(connection)
    connection.rollback.assert_called_once_with()


def test_pool_rejects_min_above_max(monkeypatch):
    monkeypatch.setenv("POSTGRES_POOL_MIN_SIZE", "3")
    monkeypatch.setenv("POSTGRES_POOL_MAX_SIZE", "2")
    with pytest.raises(ValueError, match="must not exceed"):
        postgres._new_pool()


def test_one_pool_for_vector_flags_url_aliases_and_concurrent_callers(monkeypatch):
    monkeypatch.setattr(postgres, "_POOLS", {})
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost/test")
    monkeypatch.setenv("DB_ALIAS", "postgresql://localhost/test")
    new_pool = Mock(return_value=object())
    monkeypatch.setattr(postgres, "_new_pool", new_pool)

    def acquire(i):
        return postgres._get_pool("DATABASE_URL" if i % 2 else "DB_ALIAS", register_pgvector=bool(i % 3))

    with ThreadPoolExecutor(max_workers=8) as executor:
        pools = list(executor.map(acquire, range(32)))
    assert all(pool is pools[0] for pool in pools)
    new_pool.assert_called_once()


class FakeConnection:
    def __init__(self):
        self.closed = False
        self.autocommit = False
        self.commit = Mock()
        self.rollback = Mock()

    def close(self):
        self.closed = True


@pytest.fixture
def borrowed(monkeypatch):
    connection = FakeConnection()
    pool = Mock()
    pool.getconn.return_value = connection
    monkeypatch.setattr(postgres, "_get_pool", lambda *args, **kwargs: pool)
    monkeypatch.setattr(postgres, "open_connection", Mock(side_effect=AssertionError("runtime bypass")))
    return connection, pool


def test_pool_is_mandatory_and_raw_context_does_not_commit(borrowed, monkeypatch):
    connection, pool = borrowed
    monkeypatch.setenv("POSTGRES_POOL_ENABLED", "false")
    with postgres.connect() as conn:
        assert conn is connection and conn.autocommit is False
    connection.commit.assert_not_called()
    assert not connection.closed
    pool.putconn.assert_called_once_with(connection)


def test_read_mode_is_restored_before_return(borrowed):
    connection, pool = borrowed
    with postgres.connect(read_only=True) as conn:
        assert conn.autocommit is True
    assert connection.autocommit is False
    pool.putconn.assert_called_once_with(connection)


@pytest.mark.parametrize("failure", [RuntimeError("body"), OperationalError("stale")])
def test_connection_returns_slot_after_body_error(borrowed, failure):
    connection, pool = borrowed
    with pytest.raises(type(failure), match=str(failure)):
        with postgres.connect(read_only=True):
            raise failure
    assert connection.closed is isinstance(failure, OperationalError)
    pool.putconn.assert_called_once_with(connection)


def test_failed_cleanup_discards_and_returns_slot(borrowed):
    connection, pool = borrowed
    connection.rollback.side_effect = OperationalError("rollback failed")
    with postgres.connect():
        pass
    assert connection.closed
    pool.putconn.assert_called_once_with(connection)


@pytest.mark.parametrize("fail_at", ["checkout", "return"])
def test_autocommit_failure_cannot_leak_slot(borrowed, fail_at):
    _, pool = borrowed

    class FailingModeConnection(FakeConnection):
        @property
        def autocommit(self):
            return getattr(self, "_autocommit", False)

        @autocommit.setter
        def autocommit(self, value):
            if getattr(self, "armed", False) and (value or fail_at == "return"):
                raise OperationalError("mode failed")
            self._autocommit = value

    connection = FailingModeConnection()
    pool.getconn.return_value = connection
    if fail_at == "checkout":
        connection.armed = True
        with pytest.raises(OperationalError, match="mode failed"), postgres.connect(read_only=True):
            pass
    else:
        with postgres.connect(read_only=True):
            connection.armed = True
    assert connection.closed
    pool.putconn.assert_called_once_with(connection)


def test_facade_commits_and_close_is_idempotent(borrowed):
    connection, pool = borrowed
    with PostgresStateConnection() as facade:
        assert facade._conn is connection
    facade.close()
    connection.commit.assert_called_once_with()
    assert not connection.closed
    pool.putconn.assert_called_once_with(connection)


def test_closed_facade_cannot_touch_a_returned_connection(borrowed):
    connection, pool = borrowed
    with PostgresStateConnection() as facade:
        facade.close()
    connection.commit.assert_not_called()
    pool.putconn.assert_called_once_with(connection)
    for operation in (
        facade.commit,
        facade.rollback,
        facade.__enter__,
        lambda: facade.execute("SELECT 1"),
        lambda: facade.executemany("SELECT ?", [(1,)]),
    ):
        with pytest.raises(InterfaceError, match="closed"):
            operation()


@pytest.mark.parametrize("failure", [RuntimeError("write failed"), OperationalError("write failed")])
def test_facade_commit_failure_releases_slot_without_retry(borrowed, failure):
    connection, pool = borrowed
    connection.commit.side_effect = failure
    with pytest.raises(type(failure), match="write failed"), PostgresStateConnection():
        pass
    connection.commit.assert_called_once_with()
    pool.getconn.assert_called_once()
    pool.putconn.assert_called_once_with(connection)


def test_facade_read_failure_is_discarded_before_retry(borrowed):
    connection, pool = borrowed
    replacement = FakeConnection()
    pool.getconn.side_effect = [connection, replacement]
    attempts = []

    def read():
        with PostgresStateConnection(read_only=True) as facade:
            attempts.append(facade._conn)
            if len(attempts) == 1:
                raise OperationalError("stale")
            return 42

    assert postgres.retry_read(read) == 42
    assert attempts == [connection, replacement]
    assert connection.closed and not replacement.closed
    assert pool.putconn.call_count == 2


def test_unclosed_facade_warns_and_releases_without_commit(borrowed):
    connection, pool = borrowed
    facade = PostgresStateConnection()
    with pytest.warns(ResourceWarning, match="Unclosed"):
        facade.__del__()
    connection.commit.assert_not_called()
    facade.close()
    pool.putconn.assert_called_once_with(connection)


@pytest.mark.parametrize("error", [PoolClosed, PoolTimeout, TooManyRequests, ProgrammingError, ValueError])
def test_reads_do_not_retry_capacity_or_non_operational_errors(error):
    operation = Mock(side_effect=error("failed"))
    with pytest.raises(error):
        postgres.retry_read(operation)
    operation.assert_called_once_with()


def test_read_retries_exactly_once():
    operation = Mock(side_effect=OperationalError("unavailable"))
    with pytest.raises(OperationalError, match="unavailable"):
        postgres.retry_read(operation)
    assert operation.call_count == 2
