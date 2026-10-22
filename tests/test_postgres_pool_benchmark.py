from contextlib import contextmanager

import pytest

from scripts import benchmark_postgres_pool as benchmark


def test_checkout_percentiles_preserve_missing_and_tail_observations():
    assert benchmark.percentile([], 0.95) is None
    assert benchmark.percentile([0.125], 0.95) == 0.125
    assert benchmark.percentile(list(range(1, 101)), 0.5) == 50
    assert benchmark.percentile(list(reversed(range(1, 101))), 0.95) == 95


def test_benchmark_never_falls_back_to_the_application_database(monkeypatch):
    monkeypatch.delenv("TEST_POSTGRES_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://production.invalid/live")
    with pytest.raises(ValueError, match="TEST_POSTGRES_URL"):
        benchmark.test_database_url()
    monkeypatch.setenv("TEST_POSTGRES_URL", "postgresql://production.invalid/live")
    with pytest.raises(ValueError, match="local TCP host"):
        benchmark.test_database_url()
    monkeypatch.setenv("TEST_POSTGRES_URL", "postgresql://localhost:55482/tl182_pool_bench")
    assert "55482/tl182_pool_bench" in benchmark.test_database_url()


def test_failed_workload_retains_checkout_timing_without_error_contents(monkeypatch):
    class Connection:
        def execute(self, *args):
            raise RuntimeError("private connection details")

    @contextmanager
    def connect(**kwargs):
        assert kwargs == {"read_only": True}
        yield Connection()

    monkeypatch.setattr(benchmark.postgres, "connect", connect)
    result = benchmark.sample(0)
    assert result.checkout_ms is not None
    assert result.operation_ms >= result.checkout_ms >= 0
    assert result.error == "RuntimeError"


def test_invalid_connection_information_is_not_echoed(monkeypatch, capsys):
    monkeypatch.setenv("TEST_POSTGRES_URL", "postgresql://user:private@localhost/db?private-option=private")
    with pytest.raises(SystemExit) as error:
        benchmark.main([])
    assert error.value.code == 2
    message = capsys.readouterr().err
    assert "not valid libpq" in message
    assert "private" not in message
