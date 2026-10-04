"""Hand-computed metric tests for the evaluation harness (LON-27)."""

from __future__ import annotations

import numpy as np

from longaeva_app.evaluation.metrics import (
    aggregate_scores,
    covered_80,
    empirical_crps,
    empirical_crps_quadratic,
    score_samples,
    weighted_interval_score,
)


def test_crps_toy_case() -> None:
    samples = [1.0, 2.0, 3.0, 4.0]
    assert abs(empirical_crps(samples, 2.5) - 0.375) < 1e-12


def test_crps_matches_quadratic() -> None:
    rng = np.random.default_rng(0)
    for _ in range(10):
        samples = rng.normal(size=32)
        y = float(rng.normal())
        assert abs(empirical_crps(samples, y) - empirical_crps_quadratic(samples, y)) < 1e-9


def test_wis_toy() -> None:
    quantiles = {
        "0.05": 0.0,
        "0.1": 1.0,
        "0.25": 2.0,
        "0.5": 3.0,
        "0.75": 4.0,
        "0.9": 5.0,
        "0.95": 6.0,
    }
    # y = 3 (at median): only width terms.
    # intervals: (0.05,0.95) alpha=0.1 width=6; (0.1,0.9) alpha=0.2 width=4; (0.25,0.75) alpha=0.5 width=2
    # score = |3-3| + 0.05*6 + 0.1*4 + 0.25*2 = 0 + 0.3 + 0.4 + 0.5 = 1.2
    # / (3+1) = 0.3
    assert abs(weighted_interval_score(quantiles, 3.0) - 0.3) < 1e-12


def test_coverage_inclusive() -> None:
    quantiles = {"0.1": 1.0, "0.5": 2.0, "0.9": 3.0}
    assert covered_80(quantiles, 1.0)
    assert covered_80(quantiles, 3.0)
    assert not covered_80(quantiles, 0.999)
    assert not covered_80(quantiles, 3.001)


def test_score_samples_and_aggregates() -> None:
    scores = score_samples([1.0, 2.0, 3.0, 4.0], 2.5)
    assert abs(scores.median - 2.5) < 1e-12 or abs(scores.median - 2.5) < 0.5  # quantile of even n
    assert scores.crps == empirical_crps([1.0, 2.0, 3.0, 4.0], 2.5)
    rows = [
        {
            "abs_error": 1.0,
            "signed_error": -1.0,
            "pct_error": 0.1,
            "covered_80": True,
            "crps": 0.5,
            "wis": 0.4,
        },
        {
            "abs_error": 3.0,
            "signed_error": 3.0,
            "pct_error": 0.3,
            "covered_80": False,
            "crps": 1.5,
            "wis": 1.2,
        },
    ]
    agg = aggregate_scores(rows)
    assert agg.n == 2
    assert agg.mae == 2.0
    assert agg.bias == 1.0
    assert abs((agg.mape or 0.0) - 0.2) < 1e-12
    assert agg.covered_k == 1 and agg.covered_n == 2
    assert abs((agg.mean_crps or 0.0) - 1.0) < 1e-12
