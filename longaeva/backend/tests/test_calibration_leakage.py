"""Chronological leakage guards for Visa calibration (LON-20 / MR-10)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from longaeva_app.companies.visa.calibration import (
    CalibrationLeakageError,
    ObsRow,
    as_of,
    assert_no_leakage,
    build_panel,
    load_observation_rows,
    parse_aware_utc,
)
from longaeva_app.extract.visa_tables import observation_uuid_for
from longaeva_app.hashing import content_hash

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
CALIBRATION_DIR = PACKAGE_ROOT / "data" / "calibration"

CUTOFF_FY2024Q3 = parse_aware_utc("2024-07-23T20:05:38Z")
CUTOFF_FY2024Q4 = parse_aware_utc("2024-10-29T20:06:08Z")


def _pv(panel: object, label: str) -> float | None:
    import pandas as pd

    assert isinstance(panel, pd.DataFrame)
    matched = panel.loc[panel["period"] == label]
    if matched.empty or "payments_volume_nominal_us" not in matched.columns:
        return None
    value = matched.iloc[0]["payments_volume_nominal_us"]
    if value != value:  # NaN
        return None
    return float(value)


def _panel_fingerprint(rows: list[ObsRow], cutoff: datetime) -> str:
    asof = as_of(rows, cutoff)
    panel, exclusions, _evidence = build_panel(asof, cutoff=cutoff)
    payload = {
        "periods": panel["period"].tolist() if not panel.empty else [],
        "pv": (
            panel[["period", "payments_volume_nominal_us"]].astype(str).to_dict(orient="records")
            if not panel.empty and "payments_volume_nominal_us" in panel.columns
            else []
        ),
        "exclusions": [(e.period, e.field, e.reason, e.value) for e in exclusions],
    }
    return content_hash(payload)


def test_as_of_rejects_post_cutoff_publication() -> None:
    rows = load_observation_rows()
    asof = as_of(rows, CUTOFF_FY2024Q3)
    assert_no_leakage(asof, CUTOFF_FY2024Q3)
    for row in asof:
        assert row.publication_ts <= CUTOFF_FY2024Q3


def test_fy2023q2_restatement_2957_vs_2963() -> None:
    """Same-quarter 10-Q after the FY2024Q3 cutoff restates FY2023Q2 PV to 2963."""
    rows = load_observation_rows()
    panel_q3, _, _ = build_panel(as_of(rows, CUTOFF_FY2024Q3), cutoff=CUTOFF_FY2024Q3)
    panel_q4, _, _ = build_panel(as_of(rows, CUTOFF_FY2024Q4), cutoff=CUTOFF_FY2024Q4)
    assert _pv(panel_q3, "FY2023Q2") == 2957.0
    assert _pv(panel_q4, "FY2023Q2") == 2963.0


def test_poisoned_late_row_does_not_change_panel_hash() -> None:
    rows = load_observation_rows()
    base = next(
        r
        for r in rows
        if r.period_label == "FY2023Q2"
        and r.field == "payments_volume_nominal_us"
        and r.geography == "global"
        and r.vintage_role == "current"
    )
    poison = replace(
        base,
        value=2963.0,
        publication_ts=CUTOFF_FY2024Q3 + timedelta(seconds=1),
        char_start=base.char_start + 99991,
        char_end=base.char_end + 99991,
        observation_id=observation_uuid_for(
            source_id=base.source_id,
            field=base.field,
            period_label=base.period_label,
            geography=base.geography,
            vintage_role=base.vintage_role,
            char_start=base.char_start + 99991,
            char_end=base.char_end + 99991,
        ),
    )
    assert _panel_fingerprint(rows, CUTOFF_FY2024Q3) == _panel_fingerprint([*rows, poison], CUTOFF_FY2024Q3)


def test_assert_no_leakage_raises_on_late_row() -> None:
    rows = load_observation_rows()
    base = next(r for r in rows if r.field == "payments_volume_growth_constant")
    late = replace(base, publication_ts=CUTOFF_FY2024Q3 + timedelta(seconds=1))
    with pytest.raises(CalibrationLeakageError):
        assert_no_leakage([late], CUTOFF_FY2024Q3)


def test_golden_evidence_index_publication_not_after_cutoff() -> None:
    for name in ("visa_2024-07-23.json", "visa_2025-10-28.json"):
        payload = json.loads((CALIBRATION_DIR / name).read_text(encoding="utf-8"))
        cutoff = parse_aware_utc(payload["cutoff_ts"])
        for entry in payload["evidence_index"].values():
            published = parse_aware_utc(entry["publication_ts"])
            assert published <= cutoff, (name, entry["field"], entry["period_label"])
