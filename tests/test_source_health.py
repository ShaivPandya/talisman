from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from api.snapshot_store import SnapshotRecord
from api.source_health import build_approval_source_health_review, build_workspace_source_health


def _snapshot(
    key: str,
    *,
    fetched_at: datetime,
    as_of_date: str | None = None,
    status: str = "ok",
    quality: str = "ok",
    error: str | None = None,
) -> SnapshotRecord:
    return SnapshotRecord(
        snapshot_key=key,
        payload={"value": 1},
        as_of_date=as_of_date if as_of_date is not None else fetched_at.date().isoformat(),
        fetched_at=fetched_at.isoformat(),
        status=status,
        error=error,
        version=1,
        artifact_uri=None,
        quality=quality,
    )


def _sources(payload: dict) -> dict[str, dict]:
    return {source["id"]: source for domain in payload["domains"] for source in domain["sources"]}


def _portfolio_risk(now: datetime) -> dict:
    source_status = {
        "portfolio": {
            "status": "ok",
            "quality": "ok",
            "required": True,
            "as_of": now.isoformat(),
            "fetched_at": now.isoformat(),
            "freshness": {"fresh": True, "observed_as_of_date": now.date().isoformat()},
        }
    }
    for module, snapshot_key in {
        "market_breadth": "market_breadth:sp500:1y",
        "top50_breadth": "top50_breadth:sp500:2y",
        "vix_term_structure": "vix_term_structure:current:v1",
        "sector_metrics": "sector_metrics:sp500:2y",
        "liquidity": "liquidity:current:v1",
        "economic_growth": "economic_growth:current:v1",
    }.items():
        source_status[module] = {
            "status": "ok",
            "quality": "ok",
            "required": True,
            "snapshot_key": snapshot_key,
            "as_of": now.isoformat(),
            "fetched_at": now.isoformat(),
            "freshness": {"fresh": True, "observed_as_of_date": now.date().isoformat()},
        }
    return {"source_status": source_status}


def test_alternative_health_uses_one_named_provider_and_its_observation_cadence():
    now = datetime(2026, 10, 17, 19, 0, tzinfo=ZoneInfo("America/New_York"))
    fetched = now - timedelta(days=3)
    payload = build_workspace_source_health(
        now=now,
        portfolio_risk=_portfolio_risk(now),
        snapshot_records=[
            _snapshot("signal_aggregator:current:v1", fetched_at=now, as_of_date="2026-10-16"),
            _snapshot("alternative:alternative_tsa:query1", fetched_at=now - timedelta(days=90)),
            _snapshot("alternative:alternative_tsa:query2", fetched_at=fetched),
            _snapshot("alternative:latest:alternative_tsa", fetched_at=fetched),
        ],
    )

    sources = _sources(payload)
    alternative = [source for source in sources.values() if source["domain"] == "alternative"]
    assert len(alternative) == 1
    assert alternative[0]["source_name"] == "alternative_tsa"
    assert alternative[0]["display_name"] == "TSA Checkpoint Travel Numbers"
    assert alternative[0]["status"] == "ok"
    assert alternative[0]["sla_seconds"] == 10 * 86400
    assert payload["counts"]["sla_breach"] == 0
    assert payload["counts"]["optional_degraded"] == 0


def test_alternative_health_keeps_real_staleness_even_after_a_recent_fetch():
    now = datetime(2026, 10, 17, 19, 0, tzinfo=ZoneInfo("America/New_York"))
    payload = build_workspace_source_health(
        now=now,
        snapshot_records=[
            _snapshot("alternative:latest:alternative_tsa", fetched_at=now, as_of_date="2026-09-01"),
        ],
    )
    source = _sources(payload)["alternative:latest:alternative_tsa"]
    assert source["status"] == "stale"
    assert source["sla_breach"] is True
    assert "2026-09-01" in source["detail"]


def test_historical_research_queries_do_not_claim_current_provider_health():
    now = datetime(2026, 10, 29, 14, 0, tzinfo=ZoneInfo("America/New_York"))
    for provider, start, end, as_of in (
        ("noaa_cdo", "2026-10-01", "2026-10-03", "2026-10-03"),
        ("census", "2026-08-01", "2026-08-31", "2026-08-01"),
    ):
        record = replace(
            _snapshot(f"alternative:latest:alternative_{provider}", fetched_at=now, as_of_date=as_of),
            payload={"parameters": {"start_date": start, "end_date": end}},
        )
        health = build_workspace_source_health(now=now, snapshot_records=[record])
        source = _sources(health)[record.snapshot_key]
        assert source["status"] == "historical"
        assert source["stale"] is False
        assert source["sla_breach"] is False
        assert source["gate_action"] == "inform"
        assert source["expected_as_of_date"] is None
        assert source["freshness"]["fresh"] is None
        assert "does not monitor current data" in source["detail"]
        assert health["counts"]["historical"] == 1
        assert health["counts"]["optional_degraded"] == 0
        assert (
            next(domain for domain in health["domains"] if domain["domain"] == "alternative")["overall_quality"]
            == "historical"
        )

        approval = build_approval_source_health_review({"source_dependencies": [record.snapshot_key]}, health)
        assert any(issue["id"] == record.snapshot_key for issue in approval["blockers"])


def test_current_query_still_becomes_stale_and_historical_failure_stays_visible():
    now = datetime(2026, 10, 29, 14, 0, tzinfo=ZoneInfo("America/New_York"))
    record = replace(
        _snapshot("alternative:latest:alternative_noaa_cdo", fetched_at=now - timedelta(days=20)),
        payload={"parameters": {"end_date": "2026-10-09"}, "fetched_at": "2026-10-09T18:00:00+00:00"},
    )
    health = build_workspace_source_health(now=now, snapshot_records=[record])
    assert _sources(health)[record.snapshot_key]["status"] == "stale"
    assert _sources(health)[record.snapshot_key]["sla_breach"] is True

    record = replace(
        record,
        payload={"parameters": {"end_date": "2026-10-03"}},
        status="error",
        error="Provider denied access (HTTP 403)",
    )
    health = build_workspace_source_health(now=now, snapshot_records=[record])
    assert _sources(health)[record.snapshot_key]["status"] == "degraded"
    assert "HTTP 403" in _sources(health)[record.snapshot_key]["detail"]


def test_dashboard_health_explains_missing_fields_and_degraded_dependencies():
    now = datetime(2026, 10, 29, 14, 0, tzinfo=ZoneInfo("America/New_York"))
    record = replace(
        _snapshot("portfolio_risk_dashboard:current:v1", fetched_at=now),
        payload={
            "quality": "degraded",
            "positions": [{"issues": ["missing_sector"]}] * 3,
            "stress": {"degraded_modules": [{"module": "sentiment", "reason": "NAAIM requires subscription"}]},
        },
    )
    health = build_workspace_source_health(now=now, snapshot_records=[record])
    source = _sources(health)[record.snapshot_key]
    assert source["status"] == "degraded"
    assert "missing sector (3 holdings)" in source["detail"]
    assert "sentiment: NAAIM requires subscription" in source["detail"]


def test_partial_sentiment_snapshot_remains_degraded_without_a_storage_failure():
    now = datetime(2026, 10, 29, 14, 0, tzinfo=ZoneInfo("America/New_York"))
    record = replace(
        _snapshot("sentiment:current:v1", fetched_at=now),
        payload={"surveys": {"errors": {"naaim": "Current data requires subscription"}}},
    )
    source = _sources(build_workspace_source_health(now=now, snapshot_records=[record]))[record.snapshot_key]
    assert source["status"] == "degraded"
    assert source["detail"] == "naaim: Current data requires subscription"


def test_sentiment_weekend_freshness_preserves_real_provider_errors():
    now = datetime(2026, 10, 18, 19, 0, tzinfo=ZoneInfo("America/New_York"))
    fetched = now - timedelta(days=2)
    for status, expected in (("ok", "ok"), ("error", "degraded")):
        payload = build_workspace_source_health(
            now=now,
            snapshot_records=[
                _snapshot(
                    "sentiment:current:v1",
                    fetched_at=fetched,
                    status=status,
                    error="NAAIM current data requires member access" if status == "error" else None,
                ),
            ],
        )
        source = _sources(payload)["sentiment:current:v1"]
        assert source["status"] == expected
        assert source["sla_breach"] is False
        if status == "error":
            assert source["detail"] == "NAAIM current data requires member access"


def test_source_health_keeps_refreshed_dashboard_quality_warning():
    now = datetime(2026, 10, 16, 19, 0, tzinfo=ZoneInfo("America/New_York"))
    snapshot = replace(
        _snapshot("portfolio_risk_dashboard:current:v1", fetched_at=now),
        payload={"quality": "degraded"},
    )
    payload = build_workspace_source_health(now=now, snapshot_records=[snapshot])
    assert _sources(payload)[snapshot.snapshot_key]["status"] == "degraded"


def test_source_health_marks_fresh_snapshot_ok():
    now = datetime(2026, 5, 14, 18, 0)
    payload = build_workspace_source_health(
        now=now,
        portfolio_risk=_portfolio_risk(now),
        snapshot_records=[
            _snapshot("market_breadth:sp500:1y", fetched_at=now - timedelta(hours=1)),
            _snapshot("signal_aggregator:current:v1", fetched_at=now - timedelta(hours=1)),
        ],
    )

    sources = _sources(payload)
    assert sources["market_breadth:sp500:1y"]["status"] == "ok"
    assert sources["market_breadth:sp500:1y"]["required"] is True
    assert sources["market_breadth:sp500:1y"]["source_registry"]["source_id"] == "market_breadth"


def test_source_health_stale_required_affects_overall_quality():
    now = datetime(2026, 5, 14, 18, 0)
    payload = build_workspace_source_health(
        now=now,
        portfolio_risk=_portfolio_risk(now),
        snapshot_records=[
            _snapshot("market_breadth:sp500:1y", fetched_at=now - timedelta(days=3)),
            _snapshot("signal_aggregator:current:v1", fetched_at=now - timedelta(hours=1)),
        ],
    )

    sources = _sources(payload)
    assert sources["market_breadth:sp500:1y"]["status"] == "stale"
    assert sources["market_breadth:sp500:1y"]["reliability_tier"] == "critical"
    assert sources["market_breadth:sp500:1y"]["sla_breach"] is True
    assert payload["overall_quality"] == "stale"
    assert payload["counts"]["required_stale"] == 1
    assert payload["counts"]["critical_stale"] == 1
    assert payload["tier_counts"]["critical"] >= 1


def test_source_health_market_snapshot_fresh_on_sunday_after_friday_close():
    eastern = ZoneInfo("America/New_York")
    now = datetime(2026, 5, 31, 12, 0, tzinfo=eastern)
    fetched = datetime(2026, 5, 29, 23, 30, tzinfo=ZoneInfo("UTC"))
    payload = build_workspace_source_health(
        now=now,
        portfolio_risk=_portfolio_risk(now),
        snapshot_records=[
            _snapshot("market_breadth:sp500:1y", fetched_at=fetched, as_of_date="2026-05-29"),
            _snapshot("signal_aggregator:current:v1", fetched_at=fetched, as_of_date="2026-05-29"),
        ],
    )

    sources = _sources(payload)
    assert sources["market_breadth:sp500:1y"]["status"] == "ok"
    assert sources["market_breadth:sp500:1y"]["stale"] is False
    assert sources["market_breadth:sp500:1y"]["expected_as_of_date"] == "2026-05-29"


def test_source_health_market_snapshot_fresh_monday_before_close_and_stale_after_close():
    eastern = ZoneInfo("America/New_York")
    fetched = datetime(2026, 5, 29, 23, 30, tzinfo=ZoneInfo("UTC"))

    before_close = build_workspace_source_health(
        now=datetime(2026, 6, 1, 15, 30, tzinfo=eastern),
        portfolio_risk=_portfolio_risk(datetime(2026, 6, 1, 15, 30, tzinfo=eastern)),
        snapshot_records=[
            _snapshot("market_breadth:sp500:1y", fetched_at=fetched, as_of_date="2026-05-29"),
            _snapshot("signal_aggregator:current:v1", fetched_at=fetched, as_of_date="2026-05-29"),
        ],
    )
    after_close = build_workspace_source_health(
        now=datetime(2026, 6, 1, 16, 30, tzinfo=eastern),
        portfolio_risk=_portfolio_risk(datetime(2026, 6, 1, 16, 30, tzinfo=eastern)),
        snapshot_records=[
            _snapshot("market_breadth:sp500:1y", fetched_at=fetched, as_of_date="2026-05-29"),
            _snapshot("signal_aggregator:current:v1", fetched_at=fetched, as_of_date="2026-05-29"),
        ],
    )

    assert _sources(before_close)["market_breadth:sp500:1y"]["status"] == "ok"
    assert _sources(after_close)["market_breadth:sp500:1y"]["status"] == "stale"
    assert _sources(after_close)["market_breadth:sp500:1y"]["expected_as_of_date"] == "2026-06-01"


def test_source_health_macro_cadence_windows_do_not_use_wall_clock_sla():
    now = datetime(2026, 5, 31, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    fetched = datetime(2026, 5, 29, 23, 30, tzinfo=ZoneInfo("UTC"))
    payload = build_workspace_source_health(
        now=now,
        portfolio_risk=_portfolio_risk(now),
        snapshot_records=[
            _snapshot("liquidity:current:v1", fetched_at=fetched, as_of_date="2026-05-22"),
            _snapshot("labor_market:current:v1", fetched_at=fetched, as_of_date="2026-05-22"),
            _snapshot("positioning_summary:current:v1", fetched_at=fetched, as_of_date="2026-05-22"),
            _snapshot("housing:current:v1", fetched_at=fetched, as_of_date="2026-04-20"),
            _snapshot("economic_growth:current:v1", fetched_at=fetched, as_of_date="2026-04-20"),
            _snapshot("signal_aggregator:current:v1", fetched_at=fetched, as_of_date="2026-05-29"),
        ],
    )

    sources = _sources(payload)
    assert sources["liquidity:current:v1"]["status"] == "ok"
    assert sources["labor_market:current:v1"]["status"] == "ok"
    assert sources["positioning_summary:current:v1"]["status"] == "ok"
    assert sources["housing:current:v1"]["status"] == "ok"
    assert sources["economic_growth:current:v1"]["status"] == "ok"


def test_source_health_prefers_newer_snapshot_over_stale_embedded_risk_status():
    now = datetime(2026, 6, 1, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    portfolio_risk = _portfolio_risk(now)
    portfolio_risk["source_status"]["liquidity"].update(
        {
            "status": "stale",
            "quality": "degraded",
            "as_of": "2026-05-20",
            "fetched_at": "2026-05-20T20:00:00+00:00",
            "freshness": {
                "fresh": False,
                "observed_as_of_date": "2026-05-20",
                "oldest_acceptable_date": "2026-05-22",
                "reason": "snapshot as-of 2026-05-20 is older than freshness window 2026-05-22",
            },
            "detail": "snapshot as-of 2026-05-20 is older than freshness window 2026-05-22",
        }
    )

    payload = build_workspace_source_health(
        now=now,
        portfolio_risk=portfolio_risk,
        snapshot_records=[
            _snapshot("liquidity:current:v1", fetched_at=now - timedelta(hours=1), as_of_date="2026-05-27"),
            _snapshot("signal_aggregator:current:v1", fetched_at=now - timedelta(hours=1), as_of_date="2026-05-29"),
        ],
    )

    source = _sources(payload)["liquidity:current:v1"]
    assert source["status"] == "ok"
    assert source["stale"] is False
    assert source["observed_as_of_date"] == "2026-05-27"


def test_source_health_missing_required_source_does_not_throw():
    now = datetime(2026, 5, 14, 18, 0)
    payload = build_workspace_source_health(now=now, snapshot_records=[])

    sources = _sources(payload)
    assert sources["portfolio"]["status"] == "missing"
    assert payload["overall_quality"] == "failed"
    assert payload["counts"]["required_failed"] > 0


def test_source_health_uses_workspace_runtime_sources_for_missing_freshness_records():
    now = datetime(2026, 5, 14, 18, 0)
    payload = build_workspace_source_health(
        now=now,
        portfolio_data={"positions": [{"ticker": "MU", "as_of": now.isoformat()}]},
        regime_data={
            "status": "ok",
            "as_of": now.date().isoformat(),
            "_meta": {
                "snapshot": {
                    "key": "signal_aggregator:current:v1",
                    "as_of": now.date().isoformat(),
                    "fetched_at": now.isoformat(),
                    "refresh_status": "ok",
                    "stale": False,
                }
            },
            "module_status": {
                "liquidity": {
                    "status": "ok",
                    "detail": "live fallback",
                }
            },
        },
        snapshot_records=[
            _snapshot("market_breadth:sp500:1y", fetched_at=now - timedelta(hours=1)),
            _snapshot("top50_breadth:sp500:2y", fetched_at=now - timedelta(hours=1)),
            _snapshot("vix_term_structure:current:v1", fetched_at=now - timedelta(hours=1)),
            _snapshot("sector_metrics:sp500:2y", fetched_at=now - timedelta(hours=1)),
            _snapshot("economic_growth:current:v1", fetched_at=now - timedelta(hours=1)),
        ],
    )

    sources = _sources(payload)
    assert sources["portfolio"]["status"] == "ok"
    assert sources["signal_aggregator:current:v1"]["status"] == "ok"
    assert sources["liquidity:current:v1"]["status"] == "ok"
    assert payload["overall_quality"] == "ok"
    assert payload["counts"]["required_failed"] == 0


def test_source_health_degraded_optional_is_not_required_failure():
    now = datetime(2026, 5, 14, 18, 0)
    payload = build_workspace_source_health(
        now=now,
        portfolio_risk=_portfolio_risk(now),
        snapshot_records=[
            _snapshot("housing:current:v1", fetched_at=now - timedelta(hours=1), status="error", error="timeout"),
            _snapshot("signal_aggregator:current:v1", fetched_at=now - timedelta(hours=1)),
        ],
    )

    sources = _sources(payload)
    assert sources["housing:current:v1"]["required"] is False
    assert sources["housing:current:v1"]["status"] == "degraded"
    assert payload["counts"]["optional_degraded"] == 1


def test_approval_source_health_blocks_required_missing_source():
    now = datetime(2026, 5, 14, 18, 0)
    payload = build_workspace_source_health(now=now, snapshot_records=[])

    review = build_approval_source_health_review({"id": "approval:1", "proposed_change": {}}, payload)

    assert review["status"] == "blocked"
    assert any(row["status"] == "missing" and row["required"] is True for row in review["blockers"])


def test_approval_source_health_blocks_critical_stale_source():
    now = datetime(2026, 5, 14, 18, 0)
    payload = build_workspace_source_health(
        now=now,
        portfolio_risk=_portfolio_risk(now),
        snapshot_records=[
            _snapshot("market_breadth:sp500:1y", fetched_at=now - timedelta(days=3)),
            _snapshot("signal_aggregator:current:v1", fetched_at=now - timedelta(hours=1)),
        ],
    )

    review = build_approval_source_health_review({"id": "approval:1", "proposed_change": {}}, payload)

    assert review["status"] == "blocked"
    assert review["blockers"]
    assert review["blockers"][0]["id"] == "market_breadth:sp500:1y"
    assert review["blockers"][0]["reliability_tier"] == "critical"


def test_approval_source_health_warns_on_standard_stale_source():
    now = datetime(2026, 5, 14, 18, 0)
    payload = build_workspace_source_health(
        now=now,
        portfolio_risk=_portfolio_risk(now),
        snapshot_records=[
            _snapshot("market_breadth:sp500:1y", fetched_at=now - timedelta(hours=1)),
            _snapshot("signal_aggregator:current:v1", fetched_at=now - timedelta(days=3)),
        ],
    )

    review = build_approval_source_health_review({"id": "approval:1", "proposed_change": {}}, payload)

    assert review["status"] == "warning"
    assert review["blockers"] == []
    assert any(row["id"] == "signal_aggregator:current:v1" for row in review["warnings"])
    assert review["warnings"][0]["reliability_tier"] == "standard"


def test_approval_source_health_blocks_explicit_stale_dependency():
    now = datetime(2026, 5, 14, 18, 0)
    payload = build_workspace_source_health(
        now=now,
        portfolio_risk=_portfolio_risk(now),
        snapshot_records=[
            _snapshot("housing:current:v1", fetched_at=now - timedelta(days=60)),
            _snapshot("signal_aggregator:current:v1", fetched_at=now - timedelta(hours=1)),
        ],
    )

    review = build_approval_source_health_review(
        {
            "id": "approval:1",
            "proposed_change": {"source_dependencies": ["housing:current:v1"]},
        },
        payload,
    )

    assert review["status"] == "blocked"
    assert review["blockers"][0]["id"] == "housing:current:v1"


def test_approval_source_health_warns_on_optional_degraded_source():
    now = datetime(2026, 5, 14, 18, 0)
    payload = build_workspace_source_health(
        now=now,
        portfolio_risk=_portfolio_risk(now),
        snapshot_records=[
            _snapshot("housing:current:v1", fetched_at=now - timedelta(hours=1), status="error", error="timeout"),
            _snapshot("signal_aggregator:current:v1", fetched_at=now - timedelta(hours=1)),
        ],
    )

    review = build_approval_source_health_review({"id": "approval:1", "proposed_change": {}}, payload)

    assert review["status"] == "warning"
    assert review["blockers"] == []
    assert review["warnings"][0]["id"] == "housing:current:v1"
