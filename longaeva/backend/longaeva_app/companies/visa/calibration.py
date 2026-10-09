"""Chronological Visa calibration, parameter ranges and ensemble weighting.

Loads structured parser observations as-of a cutoff, fits free parameters and residual scales
through the engine's own transitions, retains a three-member ensemble with
inverse-MSE weights, and emits a pooled ``ParameterSetCreate`` with evidence links.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy import optimize, stats

from longaeva_app.api.schemas import ParameterEvidence, ParameterSetCreate
from longaeva_app.companies.base import FiscalPeriod, PathArrays
from longaeva_app.companies.visa.model import VisaModel
from longaeva_app.companies.visa.parameters import ASSUMPTION_PARAMETER_NAMES, VISA_PARAMETERS
from longaeva_app.companies.visa.starting_state import load_fixture, required_fixture_paths, to_starting_state
from longaeva_app.companies.visa.state import BILLIONS_TO_MILLIONS
from longaeva_app.companies.visa.transitions import transition_quarter
from longaeva_app.extract.visa_tables import observation_uuid_for
from longaeva_app.hashing import content_hash, utc_isoformat

PACKAGE_ROOT = Path(__file__).resolve().parents[4]
RELEASES_DIR = PACKAGE_ROOT / "data" / "fixtures" / "visa_releases"
OBSERVATIONS_CSV = RELEASES_DIR / "observations.csv"
PARSE_STATUS_CSV = RELEASES_DIR / "parse_status.csv"
MANIFEST_JSON = RELEASES_DIR / "sources" / "manifest.json"
ORIGINS_CSV = PACKAGE_ROOT / "data" / "fixtures" / "origins.csv"
CALIBRATION_DIR = PACKAGE_ROOT / "data" / "calibration"

# Avoid literal 0.01 / 0.03 in this package (teaching-fee AST scan).
_ONE_PCT = 1.0 / 100.0
_THREE_PCT = 3.0 / 100.0
_TWENTY_FIVE_PCT = 25.0 / 100.0
_HALF = 0.5
_Z90 = 1.6448536269514722
_EPS = 1e-12
_MIN_FIT_N = 3
_MIN_CORR_N = 6
_FLOAT_SIGFIGS = 10
_SENSITIVITY_PATHS = 2000
_SENSITIVITY_SEED = 20240723
_CALIBRATED_SCENARIO_NAME = "calibrated"

_PERIOD_RE = re.compile(r"^FY(20\d{2})Q([1-4])$")
_TTM_RE = re.compile(r"^TTM_(\d{4})-(\d{2})-(\d{2})$")
_NINE_M_RE = re.compile(r"^9M_(\d{4})-(\d{2})-(\d{2})$")

FITTED_NAMES: tuple[str, ...] = (
    "payments_volume_growth",
    "transactions_growth_premium",
    "cross_border_growth_premium",
    "service_yield_drift",
    "data_processing_yield_drift",
    "international_yield_drift",
    "incentive_intensity_drift",
    "opex_growth",
    "other_revenue_growth",
)

GROWTH_FIELDS: frozenset[str] = frozenset(
    {
        "payments_volume_growth_constant",
        "payments_volume_growth_nominal",
        "processed_transactions_growth",
        "cross_border_ex_intra_europe_growth_constant",
        "cross_border_ex_intra_europe_growth_nominal",
    }
)

LEVEL_FIELDS: frozenset[str] = frozenset(
    {
        "payments_volume_nominal_us",
        "processed_transactions_count",
        "service_revenue",
        "data_processing_revenue",
        "international_transaction_revenue",
        "other_revenue",
        "client_incentives",
        "operating_expenses_ex_special_items",
        "net_revenue",
    }
)

PANEL_FIELDS: tuple[str, ...] = tuple(sorted(GROWTH_FIELDS | LEVEL_FIELDS))

SPEC_BY_NAME = {spec.name: spec for spec in VISA_PARAMETERS}


class CalibrationError(ValueError):
    """Base error for calibration failures."""


class CalibrationLeakageError(CalibrationError):
    """Raised when a value published after the cutoff feeds a fit."""


@dataclass(frozen=True, slots=True)
class ObsRow:
    period_label: str
    field: str
    value: float
    unit: str
    basis: str
    geography: str
    statement_type: str
    location: str
    source_id: str
    char_start: int
    char_end: int
    quote: str
    anchor: str
    vintage_role: str
    note: str
    publication_ts: datetime
    observation_id: UUID
    era: str
    measured: bool


@dataclass
class Exclusion:
    period: str
    field: str
    reason: str
    value: float | None = None


@dataclass
class MemberFit:
    name: str
    window_start: str
    window_end: str
    values: dict[str, float]
    ranges: dict[str, list[float]]
    evidence_ids: dict[str, list[str]]
    assumption_flags: dict[str, bool]
    rationales: dict[str, str]
    residuals: dict[str, list[float]]
    n_obs: dict[str, int]
    mse: float | None = None


@dataclass
class CalibrationResult:
    origin_date: str
    origin_label: str
    cutoff_ts: datetime
    members: list[MemberFit]
    weights: dict[str, float]
    pooled: ParameterSetCreate
    evidence_index: dict[str, dict[str, Any]]
    exclusions: list[Exclusion]
    pandemic_included: dict[str, Any]
    sensitivity: list[dict[str, Any]]
    result_hash: str
    panel_periods: list[str] = field(default_factory=list)


def parse_aware_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_period(label: str) -> FiscalPeriod | None:
    match = _PERIOD_RE.match(label)
    if match is None:
        return None
    return FiscalPeriod(int(match.group(1)), int(match.group(2)))


def period_ord(period: FiscalPeriod) -> int:
    return period.year * 4 + (period.quarter - 1)


def period_from_ord(value: int) -> FiscalPeriod:
    year, q0 = divmod(value, 4)
    return FiscalPeriod(year, q0 + 1)


def prev_period(period: FiscalPeriod, steps: int = 1) -> FiscalPeriod:
    return period_from_ord(period_ord(period) - steps)


def next_period(period: FiscalPeriod, steps: int = 1) -> FiscalPeriod:
    return period_from_ord(period_ord(period) + steps)


def is_pandemic_quarter(period: FiscalPeriod) -> bool:
    return period_ord(FiscalPeriod(2020, 2)) <= period_ord(period) <= period_ord(FiscalPeriod(2021, 4))


def yoy_estimation_weight(period: FiscalPeriod, *, include_pandemic: bool) -> float:
    if include_pandemic:
        return 1.0
    if is_pandemic_quarter(period) or is_pandemic_quarter(prev_period(period, 4)):
        return 0.0
    return 1.0


def qoq_estimation_weight(period: FiscalPeriod, *, include_pandemic: bool) -> float:
    if include_pandemic:
        return 1.0
    if is_pandemic_quarter(period) or is_pandemic_quarter(prev_period(period, 1)):
        return 0.0
    return 1.0


def round_sig(value: float, sigfigs: int = _FLOAT_SIGFIGS) -> float:
    if not math.isfinite(value) or value == 0.0:
        return 0.0 if value == 0.0 else value
    digits = sigfigs - int(math.floor(math.log10(abs(value)))) - 1
    return round(value, digits)


def _clip_to_spec(name: str, value: float) -> float:
    spec = SPEC_BY_NAME[name]
    return float(min(spec.upper, max(spec.lower, value)))


def _zero_shocks(n_paths: int = 1) -> PathArrays:
    return {
        name: np.zeros(n_paths, dtype=np.float64)
        for name in ("demand", "travel", "fx", "pricing", "incentives", "costs")
    }


def _load_eras() -> dict[str, str]:
    out: dict[str, str] = {}
    with PARSE_STATUS_CSV.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[row["period"]] = row["era"]
    return out


def _load_acceptance_by_source() -> dict[str, datetime]:
    payload = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
    out: dict[str, datetime] = {}
    for source in payload["sources"]:
        key = f"{source['accession']}/{source['document']}"
        out[key] = parse_aware_utc(source["acceptance_utc"])
    return out


def load_observation_rows(
    *,
    observations_path: Path | None = None,
    acceptance_by_source: Mapping[str, datetime] | None = None,
) -> list[ObsRow]:
    """Load parser observations joined to source acceptance times."""
    path = observations_path or OBSERVATIONS_CSV
    acceptance = dict(acceptance_by_source) if acceptance_by_source is not None else _load_acceptance_by_source()
    eras = _load_eras()
    rows: list[ObsRow] = []
    with path.open(encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            source_id = raw["source_id"]
            if source_id not in acceptance:
                raise CalibrationError(f"observation source_id not in manifest: {source_id}")
            period = raw["period_label"]
            era = eras.get(period, "")
            if not era:
                parsed = parse_period(period)
                if parsed is not None:
                    era = eras.get(parsed.label(), "")
            measured = raw["statement_type"] == "measured"
            obs_id = observation_uuid_for(
                source_id=source_id,
                field=raw["field"],
                period_label=period,
                geography=raw["geography"],
                vintage_role=raw["vintage_role"],
                char_start=int(raw["char_start"]),
                char_end=int(raw["char_end"]),
            )
            rows.append(
                ObsRow(
                    period_label=period,
                    field=raw["field"],
                    value=float(raw["value"]),
                    unit=raw["unit"],
                    basis=raw["basis"],
                    geography=raw["geography"],
                    statement_type=raw["statement_type"],
                    location=raw["location"],
                    source_id=source_id,
                    char_start=int(raw["char_start"]),
                    char_end=int(raw["char_end"]),
                    quote=raw["quote"],
                    anchor=raw["anchor"],
                    vintage_role=raw["vintage_role"],
                    note=raw["note"],
                    publication_ts=acceptance[source_id],
                    observation_id=obs_id,
                    era=era,
                    measured=measured,
                )
            )
    return rows


def _effective_period(row: ObsRow) -> str:
    """Map comparative quarterly levels to the year-ago period."""
    if row.vintage_role != "comparative":
        return row.period_label
    period = parse_period(row.period_label)
    if period is None or row.field not in LEVEL_FIELDS:
        return row.period_label
    return prev_period(period, 4).label()


def as_of(
    rows: Sequence[ObsRow],
    cutoff: datetime,
    *,
    raise_on_late: bool = False,
) -> list[ObsRow]:
    """Keep latest vintage published at or before ``cutoff`` per (period, field, geography)."""
    cutoff_utc = cutoff.astimezone(UTC) if cutoff.tzinfo else cutoff.replace(tzinfo=UTC)
    chosen: dict[tuple[str, str, str], ObsRow] = {}
    for row in rows:
        if row.publication_ts > cutoff_utc:
            if raise_on_late and row.field in PANEL_FIELDS:
                raise CalibrationLeakageError(
                    f"{row.field} for {row.period_label} published at "
                    f"{utc_isoformat(row.publication_ts)} after cutoff {utc_isoformat(cutoff_utc)}"
                )
            continue
        key = (_effective_period(row), row.field, row.geography or "global")
        prev = chosen.get(key)
        if prev is None or row.publication_ts > prev.publication_ts:
            chosen[key] = row
        elif (
            row.publication_ts == prev.publication_ts
            and row.vintage_role == "current"
            and prev.vintage_role != "current"
        ):
            chosen[key] = row
    return list(chosen.values())


def assert_no_leakage(rows: Sequence[ObsRow], cutoff: datetime) -> None:
    cutoff_utc = cutoff.astimezone(UTC) if cutoff.tzinfo else cutoff.replace(tzinfo=UTC)
    for row in rows:
        if row.publication_ts > cutoff_utc:
            raise CalibrationLeakageError(
                f"leakage: {row.field}@{row.period_label} published {utc_isoformat(row.publication_ts)} "
                f"> cutoff {utc_isoformat(cutoff_utc)}"
            )


def _to_ratio(value: float, unit: str) -> float:
    if unit == "percent":
        return value / 100.0
    return value


def _q3_window_labels(year: int) -> tuple[str, str]:
    return f"TTM_{year}-06-30", f"9M_{year}-03-31"


def _pick_global(rows: Sequence[ObsRow], period: str, field: str) -> ObsRow | None:
    candidates = [r for r in rows if r.period_label == period and r.field == field and r.geography in {"", "global"}]
    if not candidates:
        return None
    # Prefer the as_of-selected row whose effective period matches; fall back to first.
    for row in candidates:
        if _effective_period(row) == period or row.vintage_role in {"", "current"}:
            return row
    return candidates[0]


def build_panel(
    asof_rows: Sequence[ObsRow], *, cutoff: datetime
) -> tuple[pd.DataFrame, list[Exclusion], dict[str, list[ObsRow]]]:
    """Build a quarterly panel; derive Q3 payments volume as TTM − 9M."""
    exclusions: list[Exclusion] = []
    evidence: dict[str, list[ObsRow]] = {}
    by_period: dict[str, dict[str, Any]] = {}

    # Index as-of rows by effective period for quarterly fields.
    for row in asof_rows:
        if row.field not in PANEL_FIELDS:
            continue
        period = _effective_period(row)
        if parse_period(period) is None and not (_TTM_RE.match(row.period_label) or _NINE_M_RE.match(row.period_label)):
            continue
        if parse_period(period) is None:
            # Keep window rows under their original labels for Q3 derivation.
            period = row.period_label
        geo = row.geography or "global"
        if geo not in {"", "global"} and row.field == "payments_volume_nominal_us":
            continue
        cell = by_period.setdefault(period, {"period": period})
        value = _to_ratio(row.value, row.unit) if row.field in GROWTH_FIELDS else row.value
        cell[row.field] = value
        cell[f"__era__{row.field}"] = row.era
        cell[f"__measured__{row.field}"] = row.measured
        cell[f"__pub__{row.field}"] = row.publication_ts
        evidence.setdefault(f"{period}:{row.field}", []).append(row)

    # Derive Q3 PV levels.
    years = set()
    for label in list(by_period):
        ttm = _TTM_RE.match(label)
        nine = _NINE_M_RE.match(label)
        if ttm:
            years.add(int(ttm.group(1)))
        if nine:
            years.add(int(nine.group(1)))
    for year in sorted(years):
        ttm_label, nine_label = _q3_window_labels(year)
        ttm_row = _pick_global(asof_rows, ttm_label, "payments_volume_nominal_us")
        # Window rows keep their own period_label in as_of keys when not remapped.
        if ttm_row is None:
            ttm_candidates = [
                r
                for r in asof_rows
                if r.period_label == ttm_label
                and r.field == "payments_volume_nominal_us"
                and (r.geography or "global") in {"", "global"}
            ]
            ttm_row = max(ttm_candidates, key=lambda r: r.publication_ts) if ttm_candidates else None
        nine_candidates = [
            r
            for r in asof_rows
            if r.period_label == nine_label
            and r.field == "payments_volume_nominal_us"
            and (r.geography or "global") in {"", "global"}
            and r.vintage_role in {"", "current"}
        ]
        nine_row = max(nine_candidates, key=lambda r: r.publication_ts) if nine_candidates else None
        if ttm_row is None or nine_row is None:
            continue
        q3 = FiscalPeriod(year, 3).label()
        derived = float(ttm_row.value) - float(nine_row.value)
        pub = max(ttm_row.publication_ts, nine_row.publication_ts)
        if pub > cutoff.astimezone(UTC):
            exclusions.append(Exclusion(q3, "payments_volume_nominal_us", "q3_derived_after_cutoff", derived))
            continue
        cell = by_period.setdefault(q3, {"period": q3})
        cell["payments_volume_nominal_us"] = derived
        cell["__era__payments_volume_nominal_us"] = ttm_row.era or nine_row.era
        cell["__measured__payments_volume_nominal_us"] = False
        cell["__pub__payments_volume_nominal_us"] = pub
        cell["__derived__payments_volume_nominal_us"] = True
        evidence[f"{q3}:payments_volume_nominal_us"] = [ttm_row, nine_row]

    records: list[dict[str, Any]] = []
    for label, cell in sorted(by_period.items()):
        fiscal = parse_period(label)
        if fiscal is None:
            continue
        record: dict[str, Any] = {
            "period": label,
            "year": fiscal.year,
            "quarter": fiscal.quarter,
            "ord": period_ord(fiscal),
        }
        for name in PANEL_FIELDS:
            if name in cell:
                record[name] = cell[name]
                record[f"era_{name}"] = cell.get(f"__era__{name}", "")
                record[f"measured_{name}"] = cell.get(f"__measured__{name}", False)
                record[f"pub_{name}"] = cell.get(f"__pub__{name}")
        records.append(record)

    frame = pd.DataFrame.from_records(records)
    if not frame.empty:
        frame = frame.sort_values("ord").reset_index(drop=True)
    return frame, exclusions, evidence


def apply_quality_gates(panel: pd.DataFrame, exclusions: list[Exclusion]) -> pd.DataFrame:
    """Flag / null out values that fail quality gates; mutate exclusions in place."""
    if panel.empty:
        return panel
    out = panel.copy()

    # Drop FY2017 entirely and FY2018Q1 (failed parse) for estimation use flags.
    out["use_growth"] = True
    out["use_levels"] = True
    out["use_opex"] = True
    out["use_cb"] = True
    out["pandemic"] = out.apply(lambda r: is_pandemic_quarter(FiscalPeriod(int(r["year"]), int(r["quarter"]))), axis=1)

    for idx, row in out.iterrows():
        period = FiscalPeriod(int(row["year"]), int(row["quarter"]))
        label = period.label()
        era = ""
        for field_name in PANEL_FIELDS:
            key = f"era_{field_name}"
            if key in row and isinstance(row[key], str) and row[key]:
                era = str(row[key])
                break
        if period.year == 2017 or label == "FY2018Q1":
            out.at[idx, "use_growth"] = False
            out.at[idx, "use_levels"] = False
            out.at[idx, "use_opex"] = False
            out.at[idx, "use_cb"] = False
            exclusions.append(Exclusion(label, "*", "pre_history_or_failed_parse"))
            continue

        # Image-era / FY2017: no opex (GAAP-derived), no net revenue.
        if era in {"image_text_layer", "table_2017"} or (
            "era_operating_expenses_ex_special_items" in row
            and row.get("era_operating_expenses_ex_special_items") == "image_text_layer"
        ):
            out.at[idx, "use_opex"] = False
            if "operating_expenses_ex_special_items" in out.columns and pd.notna(
                row.get("operating_expenses_ex_special_items")
            ):
                exclusions.append(
                    Exclusion(
                        label,
                        "operating_expenses_ex_special_items",
                        "image_era_gaap_derived",
                        float(row["operating_expenses_ex_special_items"]),
                    )
                )
                out.at[idx, "operating_expenses_ex_special_items"] = np.nan
            if "net_revenue" in out.columns and pd.notna(row.get("net_revenue")):
                exclusions.append(Exclusion(label, "net_revenue", "image_era_misparsed", float(row["net_revenue"])))
                out.at[idx, "net_revenue"] = np.nan

        # Opex only when measured.
        if "operating_expenses_ex_special_items" in out.columns and pd.notna(
            row.get("operating_expenses_ex_special_items")
        ):
            measured = bool(row.get("measured_operating_expenses_ex_special_items", False))
            if not measured:
                out.at[idx, "use_opex"] = False
                exclusions.append(
                    Exclusion(
                        label,
                        "operating_expenses_ex_special_items",
                        "not_measured",
                        float(row["operating_expenses_ex_special_items"]),
                    )
                )
                out.at[idx, "operating_expenses_ex_special_items"] = np.nan

        # PV level quality: positive and within ±25% of prior quarter when both exist.
        if "payments_volume_nominal_us" in out.columns and pd.notna(row.get("payments_volume_nominal_us")):
            pv = float(row["payments_volume_nominal_us"])
            if pv <= 0.0:
                exclusions.append(Exclusion(label, "payments_volume_nominal_us", "non_positive", pv))
                out.at[idx, "payments_volume_nominal_us"] = np.nan
            else:
                prev_rows = out.loc[out["ord"] == int(row["ord"]) - 1]
                if not prev_rows.empty and pd.notna(prev_rows.iloc[0].get("payments_volume_nominal_us")):
                    prev_pv = float(prev_rows.iloc[0]["payments_volume_nominal_us"])
                    if prev_pv > 0 and abs(pv / prev_pv - 1.0) > _TWENTY_FIVE_PCT:
                        exclusions.append(Exclusion(label, "payments_volume_nominal_us", "qoq_jump_gt_25pct", pv))
                        out.at[idx, "payments_volume_nominal_us"] = np.nan

        # Cross-border only ex-intra-Europe (present from FY2021Q3).
        if period_ord(period) < period_ord(FiscalPeriod(2021, 3)):
            out.at[idx, "use_cb"] = False
            for cb_field in (
                "cross_border_ex_intra_europe_growth_constant",
                "cross_border_ex_intra_europe_growth_nominal",
            ):
                if cb_field in out.columns and pd.notna(row.get(cb_field)):
                    exclusions.append(
                        Exclusion(label, cb_field, "pre_ex_intra_europe_disclosure", float(row[cb_field]))
                    )
                    out.at[idx, cb_field] = np.nan

    return out


def _geo_mean_normalize(values: Sequence[float]) -> list[float]:
    arr = np.asarray(values, dtype=np.float64)
    if np.any(arr <= 0):
        raise CalibrationError("seasonal ratios must be positive")
    geo = float(np.exp(np.mean(np.log(arr))))
    return [float(v / geo) for v in arr]


def estimate_seasonals(
    panel: pd.DataFrame,
    *,
    include_pandemic: bool,
) -> tuple[dict[str, float], dict[str, list[ObsRow]], dict[str, str]]:
    """Demeaned mean log QoQ change by fiscal quarter; geo-mean normalized."""
    values: dict[str, float] = {}
    evidence: dict[str, list[ObsRow]] = {}
    rationales: dict[str, str] = {}

    def _seasonal_from_levels(col: str, prefix: str, use_col: str) -> None:
        logs: dict[int, list[float]] = {1: [], 2: [], 3: [], 4: []}
        if col not in panel.columns or panel.empty:
            for q in range(1, 5):
                values[f"{prefix}_q{q}"] = 1.0
            rationales[prefix] = f"Insufficient {col} history; seasonal ratios default to 1.0"
            return
        ordered = panel.sort_values("ord")
        for i in range(1, len(ordered)):
            cur = ordered.iloc[i]
            prev = ordered.iloc[i - 1]
            if int(cur["ord"]) != int(prev["ord"]) + 1:
                continue
            if not bool(cur.get(use_col, True)):
                continue
            period = FiscalPeriod(int(cur["year"]), int(cur["quarter"]))
            if qoq_estimation_weight(period, include_pandemic=include_pandemic) <= 0.0:
                continue
            if pd.isna(cur.get(col)) or pd.isna(prev.get(col)):
                continue
            cur_v = float(cur[col])
            prev_v = float(prev[col])
            if cur_v <= 0 or prev_v <= 0:
                continue
            logs[int(cur["quarter"])].append(math.log(cur_v / prev_v))
        means = []
        for q in range(1, 5):
            if len(logs[q]) >= 1:
                means.append(float(np.mean(logs[q])))
            else:
                means.append(0.0)
        # Demean in log space so geo-mean of exp(means) is 1 after normalize.
        demeaned = [m - float(np.mean(means)) for m in means]
        ratios = _geo_mean_normalize([math.exp(m) for m in demeaned])
        for q, ratio in enumerate(ratios, start=1):
            values[f"{prefix}_q{q}"] = _clip_to_spec(f"{prefix}_q{q}", ratio)
        if sum(len(v) for v in logs.values()) < _MIN_FIT_N:
            rationales[prefix] = f"Sparse {col} QoQ history; seasonals near 1.0"

    _seasonal_from_levels("payments_volume_nominal_us", "activity_seasonal", "use_levels")
    _seasonal_from_levels("operating_expenses_ex_special_items", "opex_seasonal", "use_opex")

    for q in range(1, 5):
        name = f"cross_border_seasonal_q{q}"
        values[name] = 1.0
    rationales["cross_border_seasonal"] = (
        "Cross-border seasonal ratios assumed 1.0; only YoY growth is disclosed (not identifiable)."
    )
    return values, evidence, rationales


def _default_params() -> dict[str, float]:
    return {spec.name: float(spec.default) for spec in VISA_PARAMETERS}


def _state_from_panel_row(row: Mapping[str, Any] | pd.Series, params: Mapping[str, float]) -> PathArrays | None:
    """Build a one-path state dict from a panel row when levels suffice."""
    needed = (
        "payments_volume_nominal_us",
        "service_revenue",
        "data_processing_revenue",
        "international_transaction_revenue",
        "other_revenue",
        "processed_transactions_count",
        "client_incentives",
        "operating_expenses_ex_special_items",
    )
    if any(pd.isna(row.get(name)) for name in needed):
        return None
    pv = float(row["payments_volume_nominal_us"])
    txn = float(row["processed_transactions_count"])
    sr = float(row["service_revenue"])
    dpr = float(row["data_processing_revenue"])
    intl = float(row["international_transaction_revenue"])
    other = float(row["other_revenue"])
    incentives = float(row["client_incentives"])
    opex = float(row["operating_expenses_ex_special_items"])
    if min(pv, txn, sr, dpr, other, opex) <= 0:
        return None
    share = float(params["cross_border_share_at_origin"])
    gross = sr + dpr + intl + other
    if gross <= 0:
        return None
    intensity = float(np.clip(incentives / gross, 1e-6, 1.0 - 1e-6))
    y_svc = sr / (pv * BILLIONS_TO_MILLIONS)  # approximate current-basis; lag uses same at start
    y_dp = dpr / txn
    y_intl = intl / (share * pv * BILLIONS_TO_MILLIONS)
    return {
        "payments_volume_nominal_us": np.array([pv], dtype=np.float64),
        "payments_volume_index_constant": np.array([100.0], dtype=np.float64),
        "cross_border_share": np.array([share], dtype=np.float64),
        "processed_transactions_count": np.array([txn], dtype=np.float64),
        "effective_yield_service": np.array([y_svc], dtype=np.float64),
        "effective_yield_service_current": np.array([y_svc], dtype=np.float64),
        "effective_yield_data_processing": np.array([y_dp], dtype=np.float64),
        "effective_yield_international": np.array([max(y_intl, _EPS)], dtype=np.float64),
        "incentive_intensity": np.array([intensity], dtype=np.float64),
        "other_revenue": np.array([other], dtype=np.float64),
        "operating_expenses_ex_special_items": np.array([opex], dtype=np.float64),
    }


def _synthetic_unit_state(params: Mapping[str, float]) -> PathArrays:
    share = float(params["cross_border_share_at_origin"])
    return {
        "payments_volume_nominal_us": np.array([1.0], dtype=np.float64),
        "payments_volume_index_constant": np.array([100.0], dtype=np.float64),
        "cross_border_share": np.array([share], dtype=np.float64),
        "processed_transactions_count": np.array([1.0], dtype=np.float64),
        "effective_yield_service": np.array([_ONE_PCT], dtype=np.float64),
        "effective_yield_service_current": np.array([_ONE_PCT], dtype=np.float64),
        "effective_yield_data_processing": np.array([_ONE_PCT], dtype=np.float64),
        "effective_yield_international": np.array([_ONE_PCT], dtype=np.float64),
        "incentive_intensity": np.array([0.2], dtype=np.float64),
        "other_revenue": np.array([1.0], dtype=np.float64),
        "operating_expenses_ex_special_items": np.array([1.0], dtype=np.float64),
    }


def _run_four_quarters(
    start_state: PathArrays,
    params: Mapping[str, float],
    start_period: FiscalPeriod,
) -> dict[str, float]:
    """Advance four zero-shock quarters; return ending metrics / state ratios."""
    state = {k: np.array(v, copy=True) for k, v in start_state.items()}
    shocks = _zero_shocks(1)
    switches = {"service_lag": True, "pool_mix": False}
    period = start_period
    metrics_last: dict[str, float] = {}
    for _ in range(4):
        period = period.next()
        step = transition_quarter(state, shocks, params, switches, period)
        state = step.state
        metrics_last = {k: float(np.asarray(v)[0]) for k, v in step.metrics.items()}
    index_start = float(np.asarray(start_state["payments_volume_index_constant"])[0])
    index_end = float(np.asarray(state["payments_volume_index_constant"])[0])
    txn_start = float(np.asarray(start_state["processed_transactions_count"])[0])
    txn_end = float(np.asarray(state["processed_transactions_count"])[0])
    opex_start = float(np.asarray(start_state["operating_expenses_ex_special_items"])[0])
    opex_end = float(np.asarray(state["operating_expenses_ex_special_items"])[0])
    other_start = float(np.asarray(start_state["other_revenue"])[0])
    other_end = float(np.asarray(state["other_revenue"])[0])
    y_svc_start = float(np.asarray(start_state["effective_yield_service"])[0])
    y_svc_end = float(np.asarray(state["effective_yield_service"])[0])
    y_dp_start = float(np.asarray(start_state["effective_yield_data_processing"])[0])
    y_dp_end = float(np.asarray(state["effective_yield_data_processing"])[0])
    y_intl_start = float(np.asarray(start_state["effective_yield_international"])[0])
    y_intl_end = float(np.asarray(state["effective_yield_international"])[0])
    inten_start = float(np.asarray(start_state["incentive_intensity"])[0])
    inten_end = float(np.asarray(state["incentive_intensity"])[0])
    # Reconstruct CB volume growth from share path under constant-dollar index.
    # Use last-step reported annualized CB growth metric average via index of CB.
    share_start = float(np.asarray(start_state["cross_border_share"])[0])
    share_end = float(np.asarray(state["cross_border_share"])[0])
    cb_growth = (index_end / index_start) * (share_end / max(share_start, _EPS)) - 1.0
    return {
        "pv_cd_yoy": index_end / index_start - 1.0,
        "txn_yoy": txn_end / txn_start - 1.0,
        "cb_cd_yoy": cb_growth,
        "opex_yoy": opex_end / opex_start - 1.0,
        "other_yoy": other_end / other_start - 1.0,
        "service_yield_yoy": y_svc_end / y_svc_start - 1.0,
        "dp_yield_yoy": y_dp_end / y_dp_start - 1.0,
        "intl_yield_yoy": y_intl_end / y_intl_start - 1.0,
        "intensity_end": inten_end,
        "intensity_start": inten_start,
        "net_revenue": metrics_last.get("net_revenue", float("nan")),
    }


def _panel_row(panel: pd.DataFrame, period: FiscalPeriod) -> pd.Series | None:
    matched = panel.loc[panel["period"] == period.label()]
    if matched.empty:
        return None
    return matched.iloc[0]


def _observed_targets(row: Mapping[str, Any] | pd.Series) -> dict[str, float | None]:
    def get(name: str) -> float | None:
        if name not in row or pd.isna(row.get(name)):
            return None
        return float(row[name])

    pv = get("payments_volume_growth_constant")
    txn = get("processed_transactions_growth")
    cb = get("cross_border_ex_intra_europe_growth_constant")
    # Yield YoY from levels when possible.
    return {
        "pv_cd_yoy": pv,
        "txn_yoy": txn,
        "cb_cd_yoy": cb,
        "opex_yoy": None,  # filled from levels below when available
        "other_yoy": None,
        "service_yield_yoy": None,
        "dp_yield_yoy": None,
        "intl_yield_yoy": None,
        "intensity_end": None,
    }


def _level_yoy(panel: pd.DataFrame, period: FiscalPeriod, col: str) -> float | None:
    cur = _panel_row(panel, period)
    base = _panel_row(panel, prev_period(period, 4))
    if cur is None or base is None:
        return None
    if pd.isna(cur.get(col)) or pd.isna(base.get(col)):
        return None
    a = float(cur[col])
    b = float(base[col])
    if b <= 0 or a <= 0:
        return None
    return a / b - 1.0


def _intensity_at(panel: pd.DataFrame, period: FiscalPeriod) -> float | None:
    row = _panel_row(panel, period)
    if row is None:
        return None
    needed = (
        "service_revenue",
        "data_processing_revenue",
        "international_transaction_revenue",
        "other_revenue",
        "client_incentives",
    )
    if any(pd.isna(row.get(n)) for n in needed):
        return None
    gross = float(row["service_revenue"]) + float(row["data_processing_revenue"])
    gross += float(row["international_transaction_revenue"]) + float(row["other_revenue"])
    if gross <= 0:
        return None
    return float(np.clip(float(row["client_incentives"]) / gross, 1e-6, 1.0 - 1e-6))


def _yield_yoy(panel: pd.DataFrame, period: FiscalPeriod, rev: str, scale: str) -> float | None:
    cur = _panel_row(panel, period)
    base = _panel_row(panel, prev_period(period, 4))
    if cur is None or base is None:
        return None
    if any(pd.isna(x.get(rev)) or pd.isna(x.get(scale)) for x in (cur, base)):
        return None
    # Service uses lag PV: approximate with prior-quarter PV when present.
    if scale == "payments_volume_nominal_us" and rev == "service_revenue":
        cur_pv = _panel_row(panel, prev_period(period, 1))
        base_pv = _panel_row(panel, prev_period(period, 5))
        if cur_pv is None or base_pv is None:
            return None
        if pd.isna(cur_pv.get(scale)) or pd.isna(base_pv.get(scale)):
            return None
        y1 = float(cur[rev]) / (float(cur_pv[scale]) * BILLIONS_TO_MILLIONS)
        y0 = float(base[rev]) / (float(base_pv[scale]) * BILLIONS_TO_MILLIONS)
    elif scale == "processed_transactions_count":
        y1 = float(cur[rev]) / float(cur[scale])
        y0 = float(base[rev]) / float(base[scale])
    else:
        y1 = float(cur[rev]) / (float(cur[scale]) * BILLIONS_TO_MILLIONS)
        y0 = float(base[rev]) / (float(base[scale]) * BILLIONS_TO_MILLIONS)
    if y0 <= 0 or y1 <= 0:
        return None
    return y1 / y0 - 1.0


def _collect_fit_quarters(
    panel: pd.DataFrame,
    *,
    window_start: FiscalPeriod,
    window_end: FiscalPeriod,
    include_pandemic: bool,
) -> list[FiscalPeriod]:
    quarters: list[FiscalPeriod] = []
    for _, row in panel.iterrows():
        period = FiscalPeriod(int(row["year"]), int(row["quarter"]))
        if period_ord(period) < period_ord(window_start) or period_ord(period) > period_ord(window_end):
            continue
        if yoy_estimation_weight(period, include_pandemic=include_pandemic) <= 0.0:
            continue
        if not bool(row.get("use_growth", True)):
            continue
        quarters.append(period)
    return quarters


def _residual_vector(
    x: np.ndarray,
    *,
    panel: pd.DataFrame,
    quarters: Sequence[FiscalPeriod],
    base_params: Mapping[str, float],
    include_cb: bool,
    include_opex: bool,
) -> npt.NDArray[np.floating[Any]]:
    params = dict(base_params)
    for name, value in zip(FITTED_NAMES, x, strict=True):
        params[name] = float(value)
    residuals: list[float] = []
    unit_state = _synthetic_unit_state(params)
    for period in quarters:
        row = _panel_row(panel, period)
        if row is None:
            continue
        start_period = prev_period(period, 4)
        start_row = _panel_row(panel, start_period)
        state = _state_from_panel_row(start_row, params) if start_row is not None else None
        if state is None:
            state = unit_state
        implied = _run_four_quarters(state, params, start_period)
        obs = _observed_targets(row)
        pairs: list[tuple[str, float | None, float, bool]] = [
            ("pv_cd_yoy", obs["pv_cd_yoy"], implied["pv_cd_yoy"], True),
            ("txn_yoy", obs["txn_yoy"], implied["txn_yoy"], True),
            (
                "cb_cd_yoy",
                obs["cb_cd_yoy"] if include_cb and bool(row.get("use_cb", True)) else None,
                implied["cb_cd_yoy"],
                include_cb and bool(row.get("use_cb", True)),
            ),
        ]
        opex_obs = (
            _level_yoy(panel, period, "operating_expenses_ex_special_items")
            if include_opex and bool(row.get("use_opex", True))
            else None
        )
        other_obs = _level_yoy(panel, period, "other_revenue")
        svc_obs = _yield_yoy(panel, period, "service_revenue", "payments_volume_nominal_us")
        dp_obs = _yield_yoy(panel, period, "data_processing_revenue", "processed_transactions_count")
        # International vs CB volume proxy: use PV * share assumption cancel → yield from intl / PV.
        intl_obs = _yield_yoy(panel, period, "international_transaction_revenue", "payments_volume_nominal_us")
        inten_obs = _intensity_at(panel, period)
        pairs.extend(
            [
                ("opex_yoy", opex_obs, implied["opex_yoy"], opex_obs is not None),
                ("other_yoy", other_obs, implied["other_yoy"], other_obs is not None),
                ("service_yield_yoy", svc_obs, implied["service_yield_yoy"], svc_obs is not None),
                ("dp_yield_yoy", dp_obs, implied["dp_yield_yoy"], dp_obs is not None),
                ("intl_yield_yoy", intl_obs, implied["intl_yield_yoy"], intl_obs is not None),
            ]
        )
        for _name, observed, model_v, ok in pairs:
            if not ok or observed is None:
                continue
            if observed <= -0.999 or model_v <= -0.999:
                continue
            residuals.append(math.log1p(observed) - math.log1p(model_v))
        if inten_obs is not None:
            # Logit-space residual on intensity end vs model.
            def _logit(v: float) -> float:
                v = min(max(v, 1e-6), 1.0 - 1e-6)
                return math.log(v / (1.0 - v))

            residuals.append(_logit(inten_obs) - _logit(implied["intensity_end"]))
    if not residuals:
        return np.zeros(1, dtype=np.float64)
    return np.asarray(residuals, dtype=np.float64)


def _fit_bounds() -> tuple[list[float], list[float]]:
    lower = [SPEC_BY_NAME[n].lower for n in FITTED_NAMES]
    upper = [SPEC_BY_NAME[n].upper for n in FITTED_NAMES]
    return lower, upper


def fit_free_parameters(
    panel: pd.DataFrame,
    *,
    window_start: FiscalPeriod,
    window_end: FiscalPeriod,
    seasonals: Mapping[str, float],
    include_pandemic: bool,
) -> tuple[dict[str, float], dict[str, list[float]], dict[str, list[float]], dict[str, int]]:
    """Bounded least_squares through ``transition_quarter`` on YoY log residuals."""
    base = _default_params()
    base.update(seasonals)
    quarters = _collect_fit_quarters(
        panel, window_start=window_start, window_end=window_end, include_pandemic=include_pandemic
    )
    lower, upper = _fit_bounds()
    x0 = np.array([base[n] for n in FITTED_NAMES], dtype=np.float64)

    def fun(x: np.ndarray) -> np.ndarray:
        return _residual_vector(
            x,
            panel=panel,
            quarters=quarters,
            base_params=base,
            include_cb=True,
            include_opex=True,
        )

    if len(quarters) < _MIN_FIT_N:
        values = {n: float(base[n]) for n in FITTED_NAMES}
        default_ranges = {n: [SPEC_BY_NAME[n].lower, SPEC_BY_NAME[n].upper] for n in FITTED_NAMES}
        return values, default_ranges, {n: [] for n in FITTED_NAMES}, {n: 0 for n in FITTED_NAMES}

    result = optimize.least_squares(fun, x0, bounds=(lower, upper), method="trf", xtol=1e-10)
    values = {name: _clip_to_spec(name, float(val)) for name, val in zip(FITTED_NAMES, result.x, strict=True)}

    # Jacobian-based 90% ranges; inflate SE ×2 for overlapping four-quarter windows.
    ranges: dict[str, list[float]] = {}
    resid = np.asarray(result.fun, dtype=np.float64)
    n = max(len(resid), 1)
    p = len(FITTED_NAMES)
    dof = max(n - p, 1)
    sigma2 = float(np.sum(resid**2) / dof)
    try:
        jac = np.asarray(result.jac, dtype=np.float64)
        jtj = jac.T @ jac
        cov = sigma2 * np.linalg.pinv(jtj)
        se = np.sqrt(np.maximum(np.diag(cov), 0.0)) * 2.0
    except Exception:
        se = np.full(p, _THREE_PCT)
    for i, name in enumerate(FITTED_NAMES):
        half = _Z90 * float(se[i])
        lo = _clip_to_spec(name, values[name] - half)
        hi = _clip_to_spec(name, values[name] + half)
        if lo > hi:
            lo, hi = hi, lo
        ranges[name] = [lo, hi]

    # Per-series residuals for shock scales.
    params = dict(base)
    params.update(values)
    series_resid: dict[str, list[float]] = {
        "demand": [],
        "travel": [],
        "fx": [],
        "pricing": [],
        "incentives": [],
        "costs": [],
        "other": [],
    }
    n_obs = {name: 0 for name in FITTED_NAMES}
    for period in quarters:
        row = _panel_row(panel, period)
        if row is None:
            continue
        start_period = prev_period(period, 4)
        start_row = _panel_row(panel, start_period)
        state = _state_from_panel_row(start_row, params) if start_row is not None else None
        if state is None:
            state = _synthetic_unit_state(params)
        implied = _run_four_quarters(state, params, start_period)
        pv_obs = (
            float(row["payments_volume_growth_constant"])
            if pd.notna(row.get("payments_volume_growth_constant"))
            else None
        )
        if pv_obs is not None:
            series_resid["demand"].append(math.log1p(pv_obs) - math.log1p(implied["pv_cd_yoy"]))
            n_obs["payments_volume_growth"] += 1
        txn_obs = (
            float(row["processed_transactions_growth"]) if pd.notna(row.get("processed_transactions_growth")) else None
        )
        if txn_obs is not None:
            n_obs["transactions_growth_premium"] += 1
        cb_obs = (
            float(row["cross_border_ex_intra_europe_growth_constant"])
            if bool(row.get("use_cb", True)) and pd.notna(row.get("cross_border_ex_intra_europe_growth_constant"))
            else None
        )
        if cb_obs is not None:
            series_resid["travel"].append(math.log1p(cb_obs) - math.log1p(implied["cb_cd_yoy"]))
            n_obs["cross_border_growth_premium"] += 1
        nom = (
            float(row["payments_volume_growth_nominal"])
            if pd.notna(row.get("payments_volume_growth_nominal"))
            else None
        )
        if pv_obs is not None and nom is not None:
            series_resid["fx"].append(nom - pv_obs)
        svc = _yield_yoy(panel, period, "service_revenue", "payments_volume_nominal_us")
        dp = _yield_yoy(panel, period, "data_processing_revenue", "processed_transactions_count")
        if svc is not None:
            series_resid["pricing"].append(math.log1p(svc) - math.log1p(implied["service_yield_yoy"]))
            n_obs["service_yield_drift"] += 1
        if dp is not None:
            series_resid["pricing"].append(math.log1p(dp) - math.log1p(implied["dp_yield_yoy"]))
            n_obs["data_processing_yield_drift"] += 1
        intl = _yield_yoy(panel, period, "international_transaction_revenue", "payments_volume_nominal_us")
        if intl is not None:
            n_obs["international_yield_drift"] += 1
        inten = _intensity_at(panel, period)
        if inten is not None:

            def _logit(v: float) -> float:
                v = min(max(v, 1e-6), 1.0 - 1e-6)
                return math.log(v / (1.0 - v))

            series_resid["incentives"].append(_logit(inten) - _logit(implied["intensity_end"]))
            n_obs["incentive_intensity_drift"] += 1
        opex = (
            _level_yoy(panel, period, "operating_expenses_ex_special_items")
            if bool(row.get("use_opex", True))
            else None
        )
        if opex is not None:
            series_resid["costs"].append(math.log1p(opex) - math.log1p(implied["opex_yoy"]))
            n_obs["opex_growth"] += 1
        other = _level_yoy(panel, period, "other_revenue")
        if other is not None:
            series_resid["other"].append(math.log1p(other) - math.log1p(implied["other_yoy"]))
            n_obs["other_revenue_growth"] += 1

    return values, ranges, series_resid, n_obs


def _chi2_vol_range(std: float, n: int, name: str) -> list[float]:
    spec = SPEC_BY_NAME[name]
    if n < 2:
        return [spec.lower, spec.upper]
    df = n - 1
    lo = math.sqrt(df * std * std / stats.chi2.ppf(0.95, df))
    hi = math.sqrt(df * std * std / stats.chi2.ppf(0.05, df))
    return [_clip_to_spec(name, lo), _clip_to_spec(name, hi)]


def estimate_shock_scales(
    series_resid: Mapping[str, list[float]],
    *,
    share: float,
) -> tuple[dict[str, float], dict[str, list[float]], dict[str, bool], dict[str, str]]:
    values: dict[str, float] = {}
    ranges: dict[str, list[float]] = {}
    flags: dict[str, bool] = {}
    rationales: dict[str, str] = {}

    def from_resid(key: str, param: str, scale: float = 0.5) -> None:
        samples = series_resid.get(key, [])
        if len(samples) < _MIN_FIT_N:
            values[param] = float(SPEC_BY_NAME[param].default)
            ranges[param] = [SPEC_BY_NAME[param].lower, SPEC_BY_NAME[param].upper]
            flags[param] = True
            rationales[param] = f"Fewer than {_MIN_FIT_N} residuals for {param}; using default."
            return
        std = float(np.std(samples, ddof=1)) * scale
        values[param] = _clip_to_spec(param, std)
        ranges[param] = _chi2_vol_range(values[param], len(samples), param)
        flags[param] = False

    from_resid("demand", "demand_vol", 0.5)
    # Travel: divide by (1-share) for logit share update.
    travel_scale = 0.5 / max(1.0 - share, _ONE_PCT)
    from_resid("travel", "travel_vol", travel_scale)
    # FX: RMS of nominal−constant gap (no /2 — already a quarterly-ish annual gap / 2 conceptually).
    fx_samples = series_resid.get("fx", [])
    if len(fx_samples) >= _MIN_FIT_N:
        fx = float(np.sqrt(np.mean(np.square(fx_samples)))) / 2.0
        values["fx_vol"] = _clip_to_spec("fx_vol", fx)
        ranges["fx_vol"] = _chi2_vol_range(values["fx_vol"], len(fx_samples), "fx_vol")
        flags["fx_vol"] = False
    else:
        values["fx_vol"] = float(SPEC_BY_NAME["fx_vol"].default)
        ranges["fx_vol"] = [SPEC_BY_NAME["fx_vol"].lower, SPEC_BY_NAME["fx_vol"].upper]
        flags["fx_vol"] = True
        rationales["fx_vol"] = "Insufficient nominal/constant gaps; using default fx_vol."
    from_resid("pricing", "pricing_vol", 0.5)
    from_resid("incentives", "incentive_vol", 0.5)
    from_resid("costs", "cost_vol", 0.5)
    return values, ranges, flags, rationales


def nearest_psd(matrix: npt.NDArray[np.floating[Any]]) -> npt.NDArray[np.floating[Any]]:
    arr = np.asarray(matrix, dtype=np.float64)
    sym = 0.5 * (arr + arr.T)
    eigvals, eigvecs = np.linalg.eigh(sym)
    eigvals = np.maximum(eigvals, 0.0)
    psd = eigvecs @ np.diag(eigvals) @ eigvecs.T
    # Rescale diagonal to 1.
    d = np.sqrt(np.maximum(np.diag(psd), _EPS))
    psd = psd / np.outer(d, d)
    np.fill_diagonal(psd, 1.0)
    return np.asarray(psd, dtype=np.float64)


def estimate_correlations(
    series_resid: Mapping[str, list[float]],
) -> tuple[dict[str, float], dict[str, list[float]], dict[str, bool], dict[str, str]]:
    demand = series_resid.get("demand", [])
    travel = series_resid.get("travel", [])
    fx = series_resid.get("fx", [])
    n = min(len(demand), len(travel), len(fx))
    values: dict[str, float] = {}
    ranges: dict[str, list[float]] = {}
    flags: dict[str, bool] = {}
    rationales: dict[str, str] = {}
    names = ("corr_demand_travel", "corr_demand_fx", "corr_travel_fx")
    if n < _MIN_CORR_N:
        for name in names:
            values[name] = float(SPEC_BY_NAME[name].default)
            ranges[name] = [SPEC_BY_NAME[name].lower, SPEC_BY_NAME[name].upper]
            flags[name] = True
        rationales["correlations"] = f"Fewer than {_MIN_CORR_N} common residual quarters; using defaults."
        return values, ranges, flags, rationales

    d = np.asarray(demand[:n], dtype=np.float64)
    t = np.asarray(travel[:n], dtype=np.float64)
    f = np.asarray(fx[:n], dtype=np.float64)
    corr_raw = np.corrcoef(np.vstack([d, t, f]))
    corr = nearest_psd(np.asarray(corr_raw, dtype=np.float64))
    raw = {
        "corr_demand_travel": float(corr[0, 1]),
        "corr_demand_fx": float(corr[0, 2]),
        "corr_travel_fx": float(corr[1, 2]),
    }
    for name, value in raw.items():
        values[name] = _clip_to_spec(name, value)
        # Fisher-z 90% interval.
        z = np.arctanh(np.clip(value, -0.999999, 0.999999))
        se = 1.0 / math.sqrt(max(n - 3, 1))
        lo = float(np.tanh(z - _Z90 * se))
        hi = float(np.tanh(z + _Z90 * se))
        ranges[name] = [_clip_to_spec(name, lo), _clip_to_spec(name, hi)]
        flags[name] = False
    return values, ranges, flags, rationales


def _member_window(
    origin: FiscalPeriod,
    name: str,
) -> tuple[FiscalPeriod, FiscalPeriod]:
    end = origin
    if name == "last_4q":
        start = prev_period(origin, 3)
    elif name == "last_8q":
        start = prev_period(origin, 7)
    else:
        start = FiscalPeriod(2018, 2)
    return start, end


def _evidence_for_window(
    evidence_map: Mapping[str, list[ObsRow]],
    panel: pd.DataFrame,
    start: FiscalPeriod,
    end: FiscalPeriod,
) -> dict[str, list[str]]:
    ids: dict[str, list[str]] = {name: [] for name in SPEC_BY_NAME}
    for _, row in panel.iterrows():
        period = FiscalPeriod(int(row["year"]), int(row["quarter"]))
        if period_ord(period) < period_ord(start) or period_ord(period) > period_ord(end):
            continue
        for field_name in PANEL_FIELDS:
            key = f"{period.label()}:{field_name}"
            for obs in evidence_map.get(key, []):
                # Map fields to parameters roughly.
                targets: list[str] = []
                if field_name == "payments_volume_growth_constant":
                    targets = [
                        "payments_volume_growth",
                        "demand_vol",
                        "activity_seasonal_q1",
                        "activity_seasonal_q2",
                        "activity_seasonal_q3",
                        "activity_seasonal_q4",
                    ]
                elif field_name == "processed_transactions_growth":
                    targets = ["transactions_growth_premium"]
                elif field_name == "cross_border_ex_intra_europe_growth_constant":
                    targets = ["cross_border_growth_premium", "travel_vol"]
                elif field_name == "payments_volume_growth_nominal":
                    targets = ["fx_vol"]
                elif field_name == "service_revenue":
                    targets = ["service_yield_drift", "pricing_vol"]
                elif field_name == "data_processing_revenue":
                    targets = ["data_processing_yield_drift", "pricing_vol"]
                elif field_name == "international_transaction_revenue":
                    targets = ["international_yield_drift"]
                elif field_name == "client_incentives":
                    targets = ["incentive_intensity_drift", "incentive_vol"]
                elif field_name == "operating_expenses_ex_special_items":
                    targets = [
                        "opex_growth",
                        "cost_vol",
                        "opex_seasonal_q1",
                        "opex_seasonal_q2",
                        "opex_seasonal_q3",
                        "opex_seasonal_q4",
                    ]
                elif field_name == "other_revenue":
                    targets = ["other_revenue_growth"]
                elif field_name == "payments_volume_nominal_us":
                    targets = [
                        "activity_seasonal_q1",
                        "activity_seasonal_q2",
                        "activity_seasonal_q3",
                        "activity_seasonal_q4",
                    ]
                for target in targets:
                    oid = str(obs.observation_id)
                    if oid not in ids[target]:
                        ids[target].append(oid)
    return ids


def fit_member(
    panel: pd.DataFrame,
    *,
    name: str,
    origin: FiscalPeriod,
    evidence_map: Mapping[str, list[ObsRow]],
    include_pandemic: bool,
    full_history_cache: MemberFit | None = None,
) -> MemberFit:
    start, end = _member_window(origin, name)
    seasonals, _sev, seasonal_rationales = estimate_seasonals(panel, include_pandemic=include_pandemic)
    fitted, fit_ranges, series_resid, n_obs = fit_free_parameters(
        panel,
        window_start=start,
        window_end=end,
        seasonals=seasonals,
        include_pandemic=include_pandemic,
    )
    # Fallback sparse series to full-history member.
    if full_history_cache is not None and name != "full_history":
        for param, count in n_obs.items():
            if count < _MIN_FIT_N and param in full_history_cache.values:
                fitted[param] = full_history_cache.values[param]
                fit_ranges[param] = full_history_cache.ranges.get(param, fit_ranges[param])

    share = float(SPEC_BY_NAME["cross_border_share_at_origin"].default)
    vols, vol_ranges, vol_flags, vol_rationales = estimate_shock_scales(series_resid, share=share)
    corrs, corr_ranges, corr_flags, corr_rationales = estimate_correlations(series_resid)

    values = _default_params()
    values.update(seasonals)
    values.update(fitted)
    values.update(vols)
    values.update(corrs)

    ranges = {spec.name: [spec.lower, spec.upper] for spec in VISA_PARAMETERS}
    ranges.update(fit_ranges)
    ranges.update(vol_ranges)
    ranges.update(corr_ranges)
    for q in range(1, 5):
        for prefix in ("activity_seasonal", "opex_seasonal", "cross_border_seasonal"):
            ranges[f"{prefix}_q{q}"] = [SPEC_BY_NAME[f"{prefix}_q{q}"].lower, SPEC_BY_NAME[f"{prefix}_q{q}"].upper]

    assumption_flags = {param: False for param in values}
    rationales: dict[str, str] = {}
    for key, text in seasonal_rationales.items():
        if key.startswith("cross_border_seasonal"):
            for q in range(1, 5):
                assumption_flags[f"cross_border_seasonal_q{q}"] = True
                rationales[f"cross_border_seasonal_q{q}"] = text
        else:
            rationales[key] = text
    for param, flag in vol_flags.items():
        assumption_flags[param] = flag
    rationales.update(vol_rationales)
    for param, flag in corr_flags.items():
        assumption_flags[param] = flag
    rationales.update(corr_rationales)
    for param in ASSUMPTION_PARAMETER_NAMES:
        assumption_flags[param] = True
        rationales[param] = SPEC_BY_NAME[param].description

    # Fallbacks for still-default fitted params with no obs.
    for param, count in n_obs.items():
        if count < _MIN_FIT_N and full_history_cache is None:
            assumption_flags[param] = True
            rationales[param] = f"Fewer than {_MIN_FIT_N} eligible observations; using default/fallback."

    evidence_ids = _evidence_for_window(evidence_map, panel, start, end)
    return MemberFit(
        name=name,
        window_start=start.label(),
        window_end=end.label(),
        values=values,
        ranges=ranges,
        evidence_ids=evidence_ids,
        assumption_flags=assumption_flags,
        rationales=rationales,
        residuals={k: list(v) for k, v in series_resid.items()},
        n_obs=n_obs,
    )


def _one_step_error(
    panel: pd.DataFrame,
    *,
    params: Mapping[str, float],
    period: FiscalPeriod,
) -> float | None:
    row = _panel_row(panel, period)
    if row is None or pd.isna(row.get("payments_volume_growth_constant")):
        return None
    start_period = prev_period(period, 4)
    start_row = _panel_row(panel, start_period)
    state = _state_from_panel_row(start_row, params) if start_row is not None else None
    if state is None:
        state = _synthetic_unit_state(params)
    implied = _run_four_quarters(state, params, start_period)
    obs = float(row["payments_volume_growth_constant"])
    return math.log1p(obs) - math.log1p(implied["pv_cd_yoy"])


def ensemble_weights(
    panel: pd.DataFrame,
    members: Sequence[MemberFit],
    *,
    origin: FiscalPeriod,
    include_pandemic: bool,
    full_history_scale: float,
) -> dict[str, float]:
    """Inverse-MSE weights on one-step pseudo-OOS errors over the last 4 eligible quarters."""
    score_quarters: list[FiscalPeriod] = []
    cursor = origin
    while len(score_quarters) < 4 and period_ord(cursor) >= period_ord(FiscalPeriod(2018, 2)):
        if yoy_estimation_weight(cursor, include_pandemic=include_pandemic) > 0:
            score_quarters.append(cursor)
        cursor = prev_period(cursor, 1)
    score_quarters = list(reversed(score_quarters))

    if len(score_quarters) < 2:
        w = 1.0 / len(members)
        return {m.name: w for m in members}

    scale = max(full_history_scale, _ONE_PCT)
    mse: dict[str, float] = {}
    for member in members:
        errors: list[float] = []
        for period in score_quarters:
            # Refit on earlier quarters only (expanding, member window capped).
            start, _end = _member_window(origin, member.name)
            refit_end = prev_period(period, 1)
            if period_ord(refit_end) < period_ord(start):
                continue
            seasonals = {k: member.values[k] for k in member.values if "seasonal" in k}
            try:
                fitted, _ranges, _resid, _n = fit_free_parameters(
                    panel,
                    window_start=start,
                    window_end=refit_end,
                    seasonals=seasonals,
                    include_pandemic=include_pandemic,
                )
            except Exception:
                continue
            params = dict(member.values)
            params.update(fitted)
            err = _one_step_error(panel, params=params, period=period)
            if err is not None:
                errors.append((err / scale) ** 2)
        mse[member.name] = float(np.mean(errors)) if errors else float("inf")

    inv = {name: (0.0 if not math.isfinite(val) or val <= 0 else 1.0 / val) for name, val in mse.items()}
    total = sum(inv.values())
    if total <= 0:
        w = 1.0 / len(members)
        return {m.name: w for m in members}
    return {name: inv[name] / total for name in inv}


def pool_members(
    members: Sequence[MemberFit],
    weights: Mapping[str, float],
    *,
    cutoff_ts: datetime,
) -> ParameterSetCreate:
    names = [spec.name for spec in VISA_PARAMETERS]
    values: dict[str, float] = {}
    ranges: dict[str, list[float]] = {}
    evidence_links: dict[str, ParameterEvidence] = {}
    assumption_flags: dict[str, Any] = {}

    for name in names:
        if "seasonal" in name:
            logs = []
            wts = []
            for member in members:
                w = weights[member.name]
                v = member.values[name]
                if v > 0 and w > 0:
                    logs.append(math.log(v) * w)
                    wts.append(w)
            values[name] = _clip_to_spec(name, math.exp(sum(logs) / sum(wts))) if wts else 1.0
        else:
            values[name] = _clip_to_spec(
                name,
                sum(weights[m.name] * m.values[name] for m in members),
            )
        lo = min(m.ranges[name][0] for m in members)
        hi = max(m.ranges[name][1] for m in members)
        ranges[name] = [_clip_to_spec(name, lo), _clip_to_spec(name, hi)]

        obs_ids: list[UUID] = []
        rationale_parts: list[str] = []
        any_assumption = False
        for member in members:
            for oid in member.evidence_ids.get(name, []):
                uid = UUID(oid)
                if uid not in obs_ids:
                    obs_ids.append(uid)
            if member.assumption_flags.get(name, False):
                any_assumption = True
                text = member.rationales.get(name)
                if text and text not in rationale_parts:
                    rationale_parts.append(text)
        if name in ASSUMPTION_PARAMETER_NAMES:
            any_assumption = True
            rationale_parts.append(SPEC_BY_NAME[name].description)
        if "seasonal" in name and name.startswith("cross_border_seasonal"):
            any_assumption = True
            rationale_parts.append("Cross-border seasonal ratios assumed 1.0; only YoY growth is disclosed.")
        if obs_ids:
            evidence_links[name] = ParameterEvidence(
                observation_ids=obs_ids,
                assumption=any_assumption,
                rationale="; ".join(rationale_parts) if any_assumption else None,
            )
            assumption_flags[name] = any_assumption
        else:
            evidence_links[name] = ParameterEvidence(
                assumption=True,
                rationale="; ".join(rationale_parts)
                if rationale_parts
                else "No eligible observations; assumption/default.",
            )
            assumption_flags[name] = True

    # Project correlations to PSD.
    corr_mat = nearest_psd(
        np.array(
            [
                [1.0, values["corr_demand_travel"], values["corr_demand_fx"]],
                [values["corr_demand_travel"], 1.0, values["corr_travel_fx"]],
                [values["corr_demand_fx"], values["corr_travel_fx"], 1.0],
            ],
            dtype=np.float64,
        )
    )
    values["corr_demand_travel"] = _clip_to_spec("corr_demand_travel", float(corr_mat[0, 1]))
    values["corr_demand_fx"] = _clip_to_spec("corr_demand_fx", float(corr_mat[0, 2]))
    values["corr_travel_fx"] = _clip_to_spec("corr_travel_fx", float(corr_mat[1, 2]))

    # Geo-mean normalize seasonals after pooling.
    for prefix in ("activity_seasonal", "opex_seasonal", "cross_border_seasonal"):
        keys = [f"{prefix}_q{q}" for q in range(1, 5)]
        normed = _geo_mean_normalize([values[k] for k in keys])
        for key, val in zip(keys, normed, strict=True):
            values[key] = _clip_to_spec(key, val)

    create = ParameterSetCreate(
        company="visa",
        cutoff_ts=cutoff_ts if cutoff_ts.tzinfo else cutoff_ts.replace(tzinfo=UTC),
        values={k: round_sig(v) for k, v in values.items()},
        ranges={k: [round_sig(a), round_sig(b)] for k, (a, b) in ranges.items()},
        evidence_links=evidence_links,
        assumption_flags=assumption_flags,
    )
    return create


def _origin_meta(origin_date: str) -> tuple[FiscalPeriod, datetime]:
    with ORIGINS_CSV.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            cutoff = parse_aware_utc(row["cutoff_utc"])
            if cutoff.date().isoformat() == origin_date:
                return FiscalPeriod(int(row["fiscal_year"]), int(row["fiscal_quarter"])), cutoff
    # Fall back to fixtures.
    for path in required_fixture_paths():
        fixture = load_fixture(path)
        if fixture.origin_date.isoformat() == origin_date:
            return FiscalPeriod(fixture.fiscal_year, fixture.fiscal_quarter), parse_aware_utc(fixture.cutoff_utc)
    raise CalibrationError(f"unknown origin date {origin_date!r}")


def _fixture_for_origin(origin_date: str) -> Any:
    for path in required_fixture_paths():
        fixture = load_fixture(path)
        if fixture.origin_date.isoformat() == origin_date:
            return fixture
    return None


def build_sensitivity_table(
    pooled: ParameterSetCreate,
    *,
    origin: FiscalPeriod,
    origin_date: str,
    pandemic_values: Mapping[str, float] | None,
) -> list[dict[str, Any]]:
    fixture = _fixture_for_origin(origin_date)
    if fixture is None:
        return []
    start = to_starting_state(fixture)
    model = VisaModel()
    base = {k: float(v) for k, v in pooled.values.items()}
    rows: list[dict[str, Any]] = []

    def run(label: str, params: Mapping[str, float]) -> dict[str, Any]:
        result = simulate_safe(model, start, params, origin=origin)
        nr = result.metrics["net_revenue"]
        op = result.metrics["operating_profit_ex_special_items"]
        return {
            "label": label,
            "next_quarter_mean_net_revenue": round_sig(float(np.mean(nr[:, 0]))),
            "next_quarter_mean_operating_profit_ex_special_items": round_sig(float(np.mean(op[:, 0]))),
            "four_quarter_mean_net_revenue": round_sig(float(np.mean(np.sum(nr, axis=1)))),
        }

    rows.append(run("baseline_pooled", base))
    for name in (
        "service_yield_drift",
        "data_processing_yield_drift",
        "international_yield_drift",
        "incentive_intensity_drift",
    ):
        lo, hi = pooled.ranges[name]
        for which, val in (("low", lo), ("high", hi)):
            params = dict(base)
            params[name] = float(val)
            rows.append(run(f"{name}_{which}", params))
    for name in ASSUMPTION_PARAMETER_NAMES:
        lo, hi = SPEC_BY_NAME[name].lower, SPEC_BY_NAME[name].upper
        for which, val in (("low", lo), ("high", hi)):
            params = dict(base)
            params[name] = float(val)
            rows.append(run(f"{name}_{which}", params))
    if pandemic_values is not None:
        params = dict(base)
        params.update({k: float(v) for k, v in pandemic_values.items() if k in params})
        rows.append(run("pandemic_included", params))
    return rows


def simulate_safe(
    model: VisaModel,
    start: Mapping[str, float],
    params: Mapping[str, float],
    *,
    origin: FiscalPeriod,
) -> Any:
    from longaeva_app.engine.runner import simulate

    return simulate(
        model,
        start,
        params,
        origin=origin,
        seed=_SENSITIVITY_SEED,
        n_paths=_SENSITIVITY_PATHS,
        n_quarters=4,
    )


def _evidence_index(rows: Iterable[ObsRow]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        index[str(row.observation_id)] = {
            "source_id": row.source_id,
            "field": row.field,
            "period_label": row.period_label,
            "geography": row.geography,
            "vintage_role": row.vintage_role,
            "char_start": row.char_start,
            "char_end": row.char_end,
            "publication_ts": utc_isoformat(row.publication_ts),
            "value": row.value,
            "unit": row.unit,
        }
    return index


def calibrate(
    origin_date: str,
    *,
    include_pandemic: bool = False,
    rows: Sequence[ObsRow] | None = None,
    run_sensitivity: bool = True,
) -> CalibrationResult:
    """Calibrate Visa parameters as-of the origin cutoff."""
    origin, cutoff = _origin_meta(origin_date)
    all_rows = list(rows) if rows is not None else load_observation_rows()
    asof_rows = as_of(all_rows, cutoff)
    assert_no_leakage(asof_rows, cutoff)
    panel, exclusions, evidence_map = build_panel(asof_rows, cutoff=cutoff)
    panel = apply_quality_gates(panel, exclusions)

    # Full history first for fallbacks.
    full = fit_member(
        panel,
        name="full_history",
        origin=origin,
        evidence_map=evidence_map,
        include_pandemic=include_pandemic,
    )
    members = [
        fit_member(
            panel,
            name="last_4q",
            origin=origin,
            evidence_map=evidence_map,
            include_pandemic=include_pandemic,
            full_history_cache=full,
        ),
        fit_member(
            panel,
            name="last_8q",
            origin=origin,
            evidence_map=evidence_map,
            include_pandemic=include_pandemic,
            full_history_cache=full,
        ),
        full,
    ]
    # Merge members that share the same eligible window.
    merged: list[MemberFit] = []
    seen: dict[tuple[str, str], MemberFit] = {}
    for member in members:
        key = (member.window_start, member.window_end)
        if key in seen:
            continue
        seen[key] = member
        merged.append(member)
    members = merged

    demand_resid = full.residuals.get("demand", [])
    scale = float(np.std(demand_resid, ddof=1)) if len(demand_resid) >= 2 else _ONE_PCT
    weights = ensemble_weights(
        panel,
        members,
        origin=origin,
        include_pandemic=include_pandemic,
        full_history_scale=scale,
    )
    # Renormalize after merge.
    total_w = sum(weights.get(m.name, 0.0) for m in members)
    if total_w <= 0:
        weights = {m.name: 1.0 / len(members) for m in members}
    else:
        weights = {m.name: weights.get(m.name, 0.0) / total_w for m in members}

    pooled = pool_members(members, weights, cutoff_ts=cutoff)

    # Pandemic-included alternative (values only).
    pandemic_alt = calibrate_values_only(
        panel,
        origin=origin,
        evidence_map=evidence_map,
        include_pandemic=True,
    )

    sensitivity: list[dict[str, Any]] = []
    if run_sensitivity:
        sensitivity = build_sensitivity_table(
            pooled,
            origin=origin,
            origin_date=origin_date,
            pandemic_values=pandemic_alt,
        )

    used_ids: set[str] = set()
    for member in members:
        for ids in member.evidence_ids.values():
            used_ids.update(ids)
    for link in pooled.evidence_links.values():
        used_ids.update(str(oid) for oid in link.observation_ids)
    index_rows = [row for row in asof_rows if str(row.observation_id) in used_ids]
    evidence_index = _evidence_index(index_rows)

    artifact = result_to_dict(
        origin_date=origin_date,
        origin_label=origin.label(),
        cutoff_ts=cutoff,
        members=members,
        weights=weights,
        pooled=pooled,
        evidence_index=evidence_index,
        exclusions=exclusions,
        pandemic_included={
            "values": {k: round_sig(v) for k, v in pandemic_alt.items()},
            "treatment": "excluded_in_primary",
        },
        sensitivity=sensitivity,
    )
    digest = content_hash(artifact)
    artifact["result_hash"] = digest

    return CalibrationResult(
        origin_date=origin_date,
        origin_label=origin.label(),
        cutoff_ts=cutoff,
        members=members,
        weights=weights,
        pooled=pooled,
        evidence_index=evidence_index,
        exclusions=exclusions,
        pandemic_included=artifact["pandemic_included"],
        sensitivity=sensitivity,
        result_hash=digest,
        panel_periods=[str(p) for p in panel["period"].tolist()] if not panel.empty else [],
    )


def calibrate_values_only(
    panel: pd.DataFrame,
    *,
    origin: FiscalPeriod,
    evidence_map: Mapping[str, list[ObsRow]],
    include_pandemic: bool,
) -> dict[str, float]:
    full = fit_member(
        panel,
        name="full_history",
        origin=origin,
        evidence_map=evidence_map,
        include_pandemic=include_pandemic,
    )
    members = [
        fit_member(
            panel,
            name="last_4q",
            origin=origin,
            evidence_map=evidence_map,
            include_pandemic=include_pandemic,
            full_history_cache=full,
        ),
        fit_member(
            panel,
            name="last_8q",
            origin=origin,
            evidence_map=evidence_map,
            include_pandemic=include_pandemic,
            full_history_cache=full,
        ),
        full,
    ]
    weights = {m.name: 1.0 / len(members) for m in members}
    # Use equal weights for the alternative to avoid recursive OOS cost.
    pooled = pool_members(members, weights, cutoff_ts=datetime(1970, 1, 1, tzinfo=UTC))
    return dict(pooled.values)


def result_to_dict(
    *,
    origin_date: str,
    origin_label: str,
    cutoff_ts: datetime,
    members: Sequence[MemberFit],
    weights: Mapping[str, float],
    pooled: ParameterSetCreate,
    evidence_index: Mapping[str, Mapping[str, Any]],
    exclusions: Sequence[Exclusion],
    pandemic_included: Mapping[str, Any],
    sensitivity: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "origin_date": origin_date,
        "origin_label": origin_label,
        "cutoff_ts": utc_isoformat(cutoff_ts),
        "pandemic_treatment": "exclude",
        "members": [
            {
                "name": m.name,
                "window_start": m.window_start,
                "window_end": m.window_end,
                "values": {k: round_sig(v) for k, v in m.values.items()},
                "ranges": {k: [round_sig(a), round_sig(b)] for k, (a, b) in m.ranges.items()},
                "n_obs": m.n_obs,
                "assumption_flags": m.assumption_flags,
            }
            for m in members
        ],
        "weights": {k: round_sig(v) for k, v in weights.items()},
        "pooled": {
            "company": pooled.company,
            "cutoff_ts": utc_isoformat(pooled.cutoff_ts),
            "values": pooled.values,
            "ranges": pooled.ranges,
            "evidence_links": {
                key: link.model_dump(mode="json") for key, link in sorted(pooled.evidence_links.items())
            },
            "assumption_flags": pooled.assumption_flags,
            "content_hash": pooled.computed_content_hash(),
        },
        "evidence_index": dict(sorted(evidence_index.items())),
        "exclusions": [
            {"period": e.period, "field": e.field, "reason": e.reason, "value": e.value} for e in exclusions
        ],
        "pandemic_included": dict(pandemic_included),
        "sensitivity": list(sensitivity),
    }


def artifact_path(origin_date: str) -> Path:
    return CALIBRATION_DIR / f"visa_{origin_date}.json"


def write_artifact(result: CalibrationResult, *, path: Path | None = None) -> Path:
    dest = path or artifact_path(result.origin_date)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = result_to_dict(
        origin_date=result.origin_date,
        origin_label=result.origin_label,
        cutoff_ts=result.cutoff_ts,
        members=result.members,
        weights=result.weights,
        pooled=result.pooled,
        evidence_index=result.evidence_index,
        exclusions=result.exclusions,
        pandemic_included=result.pandemic_included,
        sensitivity=result.sensitivity,
    )
    payload["result_hash"] = result.result_hash
    dest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dest


def persist_calibrated(
    result: CalibrationResult,
    session: Any,
    *,
    company: str = "visa",
    scenario_name: str = _CALIBRATED_SCENARIO_NAME,
) -> tuple[Any, Any]:
    """Save the pooled parameter set and a calibrated scenario; return (ParameterSet, Scenario)."""
    from sqlalchemy import select

    from longaeva_app.db.models import ParameterSet, Scenario

    create = result.pooled
    digest = create.computed_content_hash()
    existing = session.execute(select(ParameterSet).where(ParameterSet.content_hash == digest)).scalar_one_or_none()
    if existing is None:
        existing = ParameterSet(
            company=company,
            cutoff_ts=create.cutoff_ts,
            values=create.values,
            ranges=create.ranges,
            evidence_links={key: link.model_dump(mode="json") for key, link in create.evidence_links.items()},
            assumption_flags=create.assumption_flags,
            content_hash=digest,
        )
        session.add(existing)
        session.flush()
    stmt = (
        select(Scenario)
        .where(Scenario.parameter_set_id == existing.id)
        .where(Scenario.name == scenario_name)
        .where(Scenario.company == company)
    )
    scenario = session.execute(stmt).scalar_one_or_none()
    if scenario is None:
        scenario = Scenario(
            company=company,
            name=scenario_name,
            parameter_set_id=existing.id,
            interventions=[],
        )
        session.add(scenario)
        session.flush()
    return existing, scenario


def default_origin_dates() -> list[str]:
    return [path.stem.replace("visa_", "") for path in required_fixture_paths()]


__all__ = [
    "CALIBRATION_DIR",
    "CalibrationError",
    "CalibrationLeakageError",
    "CalibrationResult",
    "ObsRow",
    "as_of",
    "assert_no_leakage",
    "artifact_path",
    "calibrate",
    "default_origin_dates",
    "load_observation_rows",
    "parse_aware_utc",
    "persist_calibrated",
    "write_artifact",
]
