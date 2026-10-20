"""Dashboard/metric contract and repeatable provisioning without cloud writes."""

import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra/gcp"
spec = importlib.util.spec_from_file_location("performance_monitoring", INFRA / "setup-performance-monitoring.py")
monitoring = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitoring)


def dashboard():
    return monitoring.render_dashboard(sentry_org="example", sentry_project="123", api_service="talisman-api")


def test_dashboard_queries_reference_defined_metrics_and_merge_before_percentiles():
    metrics = json.loads((INFRA / "performance-metrics.json").read_text())
    names = {item["name"] for item in metrics}
    source = json.dumps(dashboard())
    references = re.findall(r"logging_googleapis_com:user_(talisman_\w+)_(?:bucket|count|sum)\{", source)
    assert references and set(references) <= names
    assert "topk(20," in source
    assert 'route!=\\"/api/health\\"' in source
    assert "${release}" in source and "${release.value}" not in source
    assert "__SENTRY_" not in source
    for widget in dashboard()["gridLayout"]["widgets"]:
        content = json.dumps(widget)
        if "histogram_quantile" in content:
            assert "sum by (le" in content
            assert "rate(" in content
    for item in metrics:
        assert item["metricDescriptor"]["valueType"] == "DISTRIBUTION"
        bounds = item["bucketOptions"]["explicitBuckets"]["bounds"]
        assert bounds == sorted(set(bounds))
        assert item["valueExtractor"].startswith("EXTRACT(jsonPayload.")
        assert "request_id" not in item["labelExtractors"]
    checkout = next(item for item in metrics if item["name"] == "talisman_pool_checkout_ms")
    assert {1, 2, 3, 4, 5} <= set(checkout["bucketOptions"]["explicitBuckets"]["bounds"])


def test_dry_run_is_offline(monkeypatch, tmp_path):
    monkeypatch.setattr(monitoring.subprocess, "run", lambda *_a, **_kw: pytest.fail("dry run called gcloud"))
    monitoring.provision(project="test-project", dashboard=dashboard(), output=tmp_path, dry_run=True)
    assert json.loads((tmp_path / "dashboard.json").read_text())["displayName"].endswith("(TL-179)")
    assert len(list(tmp_path.glob("talisman_*.json"))) >= 10


def test_two_provisioning_runs_update_resources_and_preserve_etag(monkeypatch, tmp_path):
    metrics = {}
    dashboards = []
    actions = []

    def run(command, **_kwargs):
        args = command[1:4]
        actions.append(tuple(args))
        config_arg = next((arg for arg in command if arg.startswith("--config-from-file=")), None)
        config = json.loads(Path(config_arg.split("=", 1)[1]).read_text()) if config_arg else None
        result = None
        if args[:2] == ["logging", "metrics"]:
            action = args[2]
            if action == "list":
                result = list(metrics.values())
            else:
                assert (config["name"] in metrics) is (action == "update")
                metrics[config["name"]] = config
        elif args == ["monitoring", "dashboards", "list"]:
            result = dashboards.copy()
        elif args == ["monitoring", "dashboards", "describe"]:
            result = dashboards[0]
        elif args == ["monitoring", "dashboards", "create"]:
            result = {**config, "name": "projects/test-project/dashboards/1", "etag": "first"}
            dashboards.append(result)
        elif args == ["monitoring", "dashboards", "update"]:
            assert config["etag"] == "first"
            result = {**config, "etag": "second"}
            dashboards[0] = result
        else:
            pytest.fail(str(command))
        return SimpleNamespace(stdout=json.dumps(result) if result is not None else "")

    monkeypatch.setattr(monitoring.subprocess, "run", run)
    monitoring.provision(project="test-project", dashboard=dashboard(), output=tmp_path)
    monitoring.provision(project="test-project", dashboard=dashboard(), output=tmp_path)
    assert len(dashboards) == 1
    assert actions.count(("monitoring", "dashboards", "create")) == 1
    assert actions.count(("monitoring", "dashboards", "update")) == 1
    assert len([a for a in actions if a == ("logging", "metrics", "update")]) == len(metrics)


def test_postgres_setup_is_idempotent_and_never_changes_flags_or_resets_stats():
    sql = (INFRA / "setup-performance-postgres.sql").read_text()
    assert "CREATE EXTENSION IF NOT EXISTS pg_stat_statements" in sql
    assert "current_setting('shared_preload_libraries')" in sql
    assert "ALTER SYSTEM" not in sql and "pg_stat_statements_reset(" not in sql
