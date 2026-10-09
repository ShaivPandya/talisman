"""Baselines scored through the evaluation harness."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.calibration import CalibrationResult, artifact_path, load_observation_rows
from longaeva_app.db.models import EvaluationResult
from longaeva_app.evaluation.baselines import BASELINE_VARIANTS, run_baseline
from longaeva_app.evaluation.baselines import guidance as guidance_mod
from longaeva_app.evaluation.baselines.common import (
    SeriesPoint,
    assert_history_before_cutoff,
    index_series,
    level_log_residual,
    normal_draws,
    seasonal_level_point,
)
from longaeva_app.evaluation.baselines.financial_only import baseline_payload as financial_payload
from longaeva_app.evaluation.baselines.guidance import (
    ESTIMATES_NOTE,
    FOUR_QUARTER_REASON,
    NO_DRIVER_REASON,
    NO_OPEX_REASON,
    NO_QUARTER_REASON,
    choose_guidance_scale,
    derived_operating_profit,
    growth_midpoint_ratio,
    lexicon_range,
    load_statements,
    relative_opex_growth,
    statements_for,
)
from longaeva_app.evaluation.baselines.guidance import (
    baseline_payload as guidance_payload,
)
from longaeva_app.evaluation.harness import (
    EvaluationConfig,
    build_config,
    config_hash,
    load_calibration_artifact,
)
from longaeva_app.evaluation.leakage import LeakageError
from longaeva_app.evaluation.origins import load_evaluation_origins
from longaeva_app.storage.local import LocalArtifactStore

N_PATHS = 256
ORIGINS = ["2024-07-23", "2025-10-28"]
_EVAL_DIR = Path(__file__).resolve().parents[2] / "data" / "evaluation"
_TS = datetime(2023, 6, 1, tzinfo=UTC)


def _point(period: FiscalPeriod, value: float, published: datetime | None = None) -> SeriesPoint:
    return SeriesPoint(period, value, published or _TS, "toy")


def _calibrate_fn(origin_date: str) -> CalibrationResult:
    path = artifact_path(origin_date)
    assert path.is_file(), path
    return load_calibration_artifact(path)


def test_seasonal_point_and_log_residual_match_hand_calculation() -> None:
    levels = {
        FiscalPeriod(2022, 1): _point(FiscalPeriod(2022, 1), 100.0),
        FiscalPeriod(2022, 2): _point(FiscalPeriod(2022, 2), 110.0),
        FiscalPeriod(2022, 3): _point(FiscalPeriod(2022, 3), 120.0),
        FiscalPeriod(2022, 4): _point(FiscalPeriod(2022, 4), 130.0),
        FiscalPeriod(2023, 1): _point(FiscalPeriod(2023, 1), 110.0),
        FiscalPeriod(2023, 2): _point(FiscalPeriod(2023, 2), 121.0),
        FiscalPeriod(2023, 3): _point(FiscalPeriod(2023, 3), 132.0),
        FiscalPeriod(2023, 4): _point(FiscalPeriod(2023, 4), 143.0),
    }
    # Year-ago FY2023Q1 is 110; each of the last four YoY changes is 10%.
    assert seasonal_level_point(levels, FiscalPeriod(2024, 1)) == pytest.approx(121.0)
    shocked = dict(levels)
    shocked[FiscalPeriod(2024, 1)] = _point(FiscalPeriod(2024, 1), 121.0 * math.exp(0.1))
    assert level_log_residual(shocked, FiscalPeriod(2024, 1)) == pytest.approx(0.1)


def test_derived_operating_profit_history_skips_the_image_era() -> None:
    origin = next(item for item in load_evaluation_origins(origin_dates=["2024-07-23"]) if item.scored)
    levels = index_series(load_observation_rows(), origin.cutoff_ts, "operating_profit_ex_special_items")
    assert FiscalPeriod(2019, 4) not in levels
    assert levels[FiscalPeriod(2024, 3)].value > 1000.0
    point = seasonal_level_point(levels, origin.target, cutoff=origin.cutoff_ts)
    assert point is not None
    assert point > 1000.0


def test_image_era_net_revenue_is_excluded_from_the_level_history() -> None:
    origin = next(item for item in load_evaluation_origins(origin_dates=["2022-01-27"]) if item.scored)
    levels = index_series(load_observation_rows(), origin.cutoff_ts, "net_revenue")
    assert FiscalPeriod(2021, 2) not in levels
    assert levels[FiscalPeriod(2021, 3)].value > 1000.0


def test_late_history_point_raises_leakage() -> None:
    late = _point(FiscalPeriod(2023, 1), 110.0, datetime(2024, 8, 1, tzinfo=UTC))
    cutoff = datetime(2024, 1, 25, tzinfo=UTC)
    with pytest.raises(LeakageError):
        assert_history_before_cutoff([late], cutoff)
    with pytest.raises(LeakageError):
        seasonal_level_point({FiscalPeriod(2023, 1): late}, FiscalPeriod(2024, 1), cutoff=cutoff)


def test_guidance_midpoint_derived_profit_and_relative_opex() -> None:
    assert growth_midpoint_ratio(18.0, 19.0) == pytest.approx(0.185)
    # Revenue 110 grown 18.5%; opex 40 grown 10% -> profit 110*1.185 - 44.
    revenue = 110.0 * (1.0 + growth_midpoint_ratio(18.0, 19.0))
    assert derived_operating_profit(revenue, 40.0, 0.10) == pytest.approx(revenue - 44.0)
    phrase = "2 to 3 points lower than the first quarter"
    assert relative_opex_growth(0.15, phrase) == pytest.approx(0.125)


def test_guidance_scale_falls_back_below_four_errors() -> None:
    seasonal = [0.1, -0.1, 0.2, -0.2, 0.05, -0.05]
    _scale, _low, source = choose_guidance_scale([0.01, 0.02, 0.03], seasonal)
    assert source == "seasonal_trend_fallback"
    scale, low, source = choose_guidance_scale([0.01, 0.02, 0.03, 0.04], seasonal)
    assert source == "guidance_errors"
    assert low is False
    assert scale == pytest.approx(float(np.std([0.01, 0.02, 0.03, 0.04], ddof=1)))


def test_stored_guidance_ranges_match_the_lexicon() -> None:
    for statement in load_statements():
        if statement.comparable != "true":
            continue
        if statement.metric not in {"net_revenue", "operating_expenses"}:
            continue
        low, high = lexicon_range(statement)
        assert statement.range_low == pytest.approx(low)
        assert statement.range_high == pytest.approx(high)


def test_guidance_gaps_are_marked_and_drivers_are_not_guided() -> None:
    statements = load_statements()
    for label in ("FY2022Q2", "FY2023Q3", "FY2023Q4"):
        assert "net_revenue" not in statements_for(statements, label)
    fy2022q1 = statements_for(statements, "FY2022Q1")
    assert "net_revenue" in fy2022q1
    assert "operating_expenses" not in fy2022q1
    fy2023q1 = statements_for(statements, "FY2023Q1")
    assert fy2023q1["operating_expenses"].comparable == "derived"
    assert NO_DRIVER_REASON == "no numeric driver guidance"
    assert NO_QUARTER_REASON
    assert NO_OPEX_REASON
    assert FOUR_QUARTER_REASON


def test_consensus_appears_only_in_the_permitted_estimates_string() -> None:
    source = Path(guidance_mod.__file__).read_text(encoding="utf-8")
    assert source.count("consensus") == 1
    assert ESTIMATES_NOTE in source
    payload = json.dumps(guidance_payload())
    assert payload.count("consensus") == 1
    assert "consensus" not in json.dumps(financial_payload())


def test_seeded_draws_are_deterministic() -> None:
    first = normal_draws(27000, 64, 0.02)
    second = normal_draws(27000, 64, 0.02)
    other = normal_draws(27001, 64, 0.02)
    assert np.array_equal(first, second)
    assert not np.array_equal(first, other)


def test_empty_baseline_does_not_change_the_full_model_hash() -> None:
    origins = [origin for origin in load_evaluation_origins(origin_dates=ORIGINS) if origin.scored]
    plain = build_config(origins, n_paths=N_PATHS)
    empty = build_config(origins, n_paths=N_PATHS, baseline={})
    assert "baseline" not in plain.to_hashable()
    assert config_hash(plain) == config_hash(empty)
    changed = build_config(origins, n_paths=N_PATHS, baseline={"method": "financial_only"})
    assert config_hash(changed) != config_hash(plain)


@pytest.mark.db
def test_baselines_on_two_fixture_origins(
    db_session: Session,
    artifact_store: LocalArtifactStore,
) -> None:
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    reports = []
    distribution_variants = tuple(name for name in BASELINE_VARIANTS if name != "llm_baseline")
    for name in distribution_variants:
        report = run_baseline(
            name,
            factory,
            origin_dates=ORIGINS,
            n_paths=N_PATHS,
            use_cache=False,
            calibrate_fn=_calibrate_fn,
            artifact_store=artifact_store,
        )
        assert report.n_scored == 2, name
        assert report.n_excluded == 0
        assert all(item.error is None for item in report.origins), report.origins
        assert all(item.rows for item in report.origins)
        reports.append(report)

    hashes = {report.config.model_variant: report.config_hash for report in reports}
    assert len(hashes) == 3
    with factory() as session:
        rows = list(session.scalars(select(EvaluationResult)))
    assert {row.model_variant for row in rows} == set(distribution_variants)
    assert {row.config_hash for row in rows} == set(hashes.values())
    by_variant: dict[str, list[EvaluationResult]] = {name: [] for name in BASELINE_VARIANTS}
    for row in rows:
        by_variant[row.model_variant].append(row)

    for row in by_variant["financial_only"]:
        assert row.details["external_updates"] == []
        assert row.details["label"] == "financial-only"
    guidance_rows = by_variant["guidance"]
    assert guidance_rows
    blob = json.dumps([row.details for row in guidance_rows])
    assert "consensus" not in blob
    assert all(row.details["label"] == "company guidance" for row in guidance_rows)
    driver_marks = [row for row in guidance_rows if row.metric == "q1.payments_volume_growth_constant.available"]
    assert len(driver_marks) == 2
    assert all(row.details["reason"] == NO_DRIVER_REASON for row in driver_marks)

    # Same config hash, same row count on a second seasonal run.
    seasonal_n = len(by_variant["seasonal_trend"])
    again = run_baseline(
        "seasonal_trend",
        factory,
        origin_dates=ORIGINS,
        n_paths=N_PATHS,
        use_cache=False,
        calibrate_fn=_calibrate_fn,
        artifact_store=artifact_store,
    )
    assert again.config_hash == hashes["seasonal_trend"]
    with factory() as session:
        seasonal_rows = list(
            session.scalars(select(EvaluationResult).where(EvaluationResult.model_variant == "seasonal_trend"))
        )
    assert len(seasonal_rows) == seasonal_n


def _rebuild_config(data: dict[str, Any]) -> EvaluationConfig:
    config = data["config"]
    assert isinstance(config, dict)
    quantiles = config["quantiles"]
    origin_dates = config["origin_dates"]
    switches = config["switches"]
    scoring = config["scoring_bases"]
    baseline = config.get("baseline", {})
    assert isinstance(quantiles, list)
    assert isinstance(origin_dates, list)
    assert isinstance(switches, dict)
    assert isinstance(scoring, dict)
    assert isinstance(baseline, dict)
    return EvaluationConfig(
        evaluation_code_hash=str(config.get("evaluation_code_hash", "")),
        evaluation_inputs=config.get("evaluation_inputs", {}),
        suite_version=str(config["suite_version"]),
        model_variant=str(config["model_variant"]),
        n_paths=int(config["n_paths"]),
        n_quarters=int(config["n_quarters"]),
        base_seed=int(config["base_seed"]),
        quantiles=tuple(float(item) for item in quantiles),
        coverage_level=float(config["coverage_level"]),
        include_pandemic=bool(config["include_pandemic"]),
        switches={str(key): bool(value) for key, value in switches.items()},
        origin_dates=[str(item) for item in origin_dates],
        code_version=str(config["code_version"]),
        observations_hash=str(config["observations_hash"]),
        manifest_hash=str(config["manifest_hash"]),
        origins_hash=str(config["origins_hash"]),
        driver_method=str(config["driver_method"]),
        scoring_bases={str(key): str(value) for key, value in scoring.items()},
        baseline={str(key): value for key, value in baseline.items()},
    )


def test_committed_baseline_results_when_present() -> None:
    names = ("visa_full_model.json", "visa_seasonal_trend.json", "visa_financial_only.json", "visa_guidance.json")
    missing = [name for name in names if not (_EVAL_DIR / name).is_file()]
    if missing:
        pytest.skip("committed baseline results not written yet: " + ", ".join(missing))
    loaded: dict[str, dict[str, Any]] = {}
    for name in names:
        payload = json.loads((_EVAL_DIR / name).read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        rebuilt = _rebuild_config(payload)
        assert config_hash(rebuilt) == payload["config_hash"]
        assert payload["n_scored"] == 16
        assert payload["n_excluded"] == 2
        loaded[name] = payload
    full = loaded["visa_full_model.json"]["aggregates"]
    financial = loaded["visa_financial_only.json"]["aggregates"]
    assert full != financial
    removed = json.loads((_EVAL_DIR / "visa_no_external_commentary.json").read_text(encoding="utf-8"))
    assert removed["aggregates"] == financial
