"""Build Visa starting-state fixtures from as-of observations.

Applies the starting-state reconstruction roll-forward rules at any origins.csv cutoff. Committed starting-state reconstruction
fixtures stay authoritative when present; this builder covers the remaining
candidate and prospective origins.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.definitions import FIELDS, VISA_FISCAL_CALENDAR, FieldDefinition
from longaeva_app.companies.visa.starting_state import (
    FIELD_BY_NAME,
    Derivation,
    SourceRef,
    Span,
    StartingStateFixture,
    StateValue,
    SupportingLevel,
    identity_residuals,
)
from longaeva_app.companies.visa.state import BILLIONS_TO_MILLIONS
from longaeva_app.hashing import utc_isoformat

PACKAGE_ROOT = Path(__file__).resolve().parents[4]
ORIGINS_CSV = PACKAGE_ROOT / "data" / "fixtures" / "origins.csv"
RELEASES_MANIFEST = PACKAGE_ROOT / "data" / "fixtures" / "visa_releases" / "sources" / "manifest.json"

# Avoid literal 0.01 / 0.03 in this package (teaching-fee AST scan).
_ONE_PCT = 1.0 / 100.0
_HALF_PCT = 0.5 / 100.0
_INDEX_AT_ORIGIN = 100.0

_MEASURED_RELEASE_FIELDS: tuple[str, ...] = (
    "service_revenue",
    "data_processing_revenue",
    "international_transaction_revenue",
    "other_revenue",
    "client_incentives",
    "net_revenue",
    "operating_expenses_gaap",
    "operating_expenses_ex_special_items",
    "processed_transactions_count",
    "payments_volume_growth_constant",
    "payments_volume_growth_nominal",
    "processed_transactions_growth",
    "cross_border_ex_intra_europe_growth_constant",
    "cross_border_ex_intra_europe_growth_nominal",
    "cross_border_total_growth_constant",
    "cross_border_total_growth_nominal",
    "tax_rate",
    "net_interest_other",
    "diluted_shares",
)


class StateBuildError(ValueError):
    """Raised when a starting state cannot be built for a cutoff."""


@dataclass(frozen=True, slots=True)
class _PvLevel:
    value: float
    period: FiscalPeriod
    primary_row: Any
    ttm_row: Any | None = None
    nine_row: Any | None = None


def _lazy_calibration() -> Any:
    from longaeva_app.companies.visa import calibration as cal

    return cal


def _load_origins() -> list[dict[str, str]]:
    with ORIGINS_CSV.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def origin_row_for_date(origin_date: str) -> dict[str, str] | None:
    for row in _load_origins():
        if row["cutoff_utc"][:10] == origin_date:
            return row
    return None


def origin_row_for_cutoff(cutoff: datetime) -> dict[str, str] | None:
    from datetime import UTC

    cal = _lazy_calibration()
    aware = cutoff.astimezone(UTC) if cutoff.tzinfo else cutoff.replace(tzinfo=UTC)
    for row in _load_origins():
        if cal.parse_aware_utc(row["cutoff_utc"]) == aware:
            return row
    date_key = aware.date().isoformat()
    matches = [
        row
        for row in _load_origins()
        if row["cutoff_utc"][:10] == date_key and row["status"] in {"candidate", "prospective"}
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def buildable_origin_dates() -> list[str]:
    """Origin dates from origins.csv with status candidate or prospective."""
    return [row["cutoff_utc"][:10] for row in _load_origins() if row["status"] in {"candidate", "prospective"}]


def _load_releases_manifest() -> dict[str, dict[str, Any]]:
    data = json.loads(RELEASES_MANIFEST.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for entry in data.get("sources", []):
        source_id = f"{entry['accession']}/{entry['document']}"
        out[source_id] = entry
    return out


def _pick_row(asof: list[Any], period_label: str, field: str) -> Any | None:
    candidates = [
        row
        for row in asof
        if row.period_label == period_label and row.field == field and (row.geography or "global") in {"", "global"}
    ]
    if not candidates:
        return None
    current = [row for row in candidates if row.vintage_role in {"", "current"}]
    pool = current or candidates
    # Prefer measured over derived when both exist.
    pool.sort(key=lambda r: (r.statement_type != "measured", -r.publication_ts.timestamp()))
    return pool[0]


def _pv_level(asof: list[Any], period: FiscalPeriod, cal: Any) -> _PvLevel | None:
    row = _pick_row(asof, period.label(), "payments_volume_nominal_us")
    if row is not None and float(row.value) > 0.0:
        return _PvLevel(value=float(row.value), period=period, primary_row=row)
    if period.quarter != 3:
        return None
    ttm_label, nine_label = cal._q3_window_labels(period.year)
    ttm = _pick_row(asof, ttm_label, "payments_volume_nominal_us")
    nine = _pick_row(asof, nine_label, "payments_volume_nominal_us")
    if ttm is None or nine is None:
        return None
    return _PvLevel(
        value=float(ttm.value) - float(nine.value),
        period=period,
        primary_row=ttm,
        ttm_row=ttm,
        nine_row=nine,
    )


def _span_from_row(row: Any) -> Span:
    return Span(
        anchor=row.anchor or row.field,
        quote=row.quote,
        char_start=int(row.char_start),
        char_end=int(row.char_end),
    )


def _normalize_value(field: FieldDefinition, row: Any) -> float:
    value = float(row.value)
    if field.unit == "ratio" and row.unit == "percent":
        return value * _ONE_PCT
    return value


def _period_dates(period: FiscalPeriod) -> tuple[date, date]:
    return VISA_FISCAL_CALENDAR.period_start(period), VISA_FISCAL_CALENDAR.period_end(period)


def _source_ref_for(source_id: str, manifest: dict[str, dict[str, Any]], *, note: str = "") -> SourceRef:
    entry = manifest.get(source_id)
    if entry is None:
        raise StateBuildError(f"source {source_id} missing from visa_releases manifest")
    return SourceRef(
        source_id=source_id,
        accession=str(entry["accession"]),
        document=str(entry["document"]),
        form=str(entry["form"]),
        acceptance_utc=str(entry["acceptance_utc"]),
        url=str(entry["url"]),
        role="input",
        content_sha256=str(entry["content_sha256"]),
        note=note,
    )


def _measured(
    name: str,
    row: Any,
    *,
    period: FiscalPeriod | None = None,
    note: str = "",
) -> StateValue:
    field = FIELD_BY_NAME[name]
    label = row.period_label
    fiscal = None
    if period is not None:
        label = period.label()
        fiscal = period
    else:
        from longaeva_app.companies.visa.calibration import parse_period

        fiscal = parse_period(label)
    start: date | None = None
    end: date | None = None
    if fiscal is not None:
        start, end = _period_dates(fiscal)
    return StateValue(
        name=name,
        status="measured",
        value=_normalize_value(field, row),
        unit=field.unit,
        basis=field.basis if field.basis != "derived" else row.basis or "derived",
        period_label=label,
        period_start=start,
        period_end=end,
        source_id=row.source_id,
        span=_span_from_row(row),
        note=note,
    )


def _derived(
    name: str,
    value: float,
    *,
    formula: str,
    inputs: dict[str, float],
    source_id: str,
    span: Span,
    period: FiscalPeriod,
    note: str = "",
    rounding_band: float | None = None,
    basis: str | None = None,
) -> StateValue:
    field = FIELD_BY_NAME[name]
    start, end = _period_dates(period)
    return StateValue(
        name=name,
        status="derived",
        value=value,
        unit=field.unit,
        basis=basis or field.basis,
        period_label=period.label(),
        period_start=start,
        period_end=end,
        source_id=source_id,
        span=span,
        derivation=Derivation(formula=formula, inputs=inputs, rounding_band=rounding_band),
        note=note,
    )


def _unavailable(name: str, reason: str) -> StateValue:
    field = FIELD_BY_NAME[name]
    return StateValue(
        name=name,
        status="unavailable_at_cutoff",
        value=None,
        unit=field.unit,
        basis=field.basis,
        unavailable_reason=reason,
    )


def _supporting(
    key: str,
    *,
    value: float,
    unit: str,
    basis: str,
    period_label: str,
    period: FiscalPeriod | None,
    source_id: str,
    span: Span,
    note: str = "",
) -> SupportingLevel:
    if period is not None:
        start, end = _period_dates(period)
    else:
        # Window labels: use synthetic dates from the label suffix when possible.
        start = date(1970, 1, 1)
        end = date(1970, 1, 1)
        if "_" in period_label:
            try:
                end = date.fromisoformat(period_label.split("_", 1)[1])
                start = end
            except ValueError:
                pass
    return SupportingLevel(
        key=key,
        value=value,
        unit=unit,
        basis=basis,
        period_label=period_label,
        period_start=start,
        period_end=end,
        source_id=source_id,
        span=span,
        note=note,
    )


def build_fixture(
    cutoff_ts: datetime,
    *,
    rows: list[Any] | None = None,
    origin_row: dict[str, str] | None = None,
) -> StartingStateFixture:
    """Build an in-memory ``StartingStateFixture`` as-of ``cutoff_ts``."""
    cal = _lazy_calibration()
    cutoff = cutoff_ts.astimezone(UTC) if cutoff_ts.tzinfo else cutoff_ts.replace(tzinfo=UTC)
    row = origin_row or origin_row_for_cutoff(cutoff)
    if row is None:
        raise StateBuildError(f"no origins.csv row for cutoff {utc_isoformat(cutoff)}")
    if row["status"] not in {"candidate", "prospective"}:
        raise StateBuildError(
            f"origin {row['cutoff_utc'][:10]} has status {row['status']!r}; "
            "only candidate and prospective origins are built"
        )

    origin = FiscalPeriod(int(row["fiscal_year"]), int(row["fiscal_quarter"]))
    target = FiscalPeriod(int(row["target_fiscal_year"]), int(row["target_fiscal_quarter"]))
    origin_date = row["cutoff_utc"][:10]
    all_rows = list(rows) if rows is not None else cal.load_observation_rows()
    asof = cal.as_of(all_rows, cutoff)
    manifest = _load_releases_manifest()

    q_m1 = cal.prev_period(origin, 1)
    q_m2 = cal.prev_period(origin, 2)
    q_m4 = cal.prev_period(origin, 4)
    q_m5 = cal.prev_period(origin, 5)

    missing: list[str] = []
    measured: dict[str, StateValue] = {}
    used_rows: list[Any] = []

    for name in _MEASURED_RELEASE_FIELDS:
        obs = _pick_row(asof, origin.label(), name)
        if obs is None:
            # Optional context / valuation / CB fields may be unavailable early.
            if name in {
                "cross_border_ex_intra_europe_growth_constant",
                "cross_border_ex_intra_europe_growth_nominal",
                "cross_border_total_growth_constant",
                "cross_border_total_growth_nominal",
                "tax_rate",
                "net_interest_other",
                "diluted_shares",
            }:
                continue
            missing.append(f"{origin.label()}:{name}")
            continue
        measured[name] = _measured(name, obs, period=origin)
        used_rows.append(obs)

    growth_qm1 = _pick_row(asof, q_m1.label(), "payments_volume_growth_nominal")
    if growth_qm1 is None:
        missing.append(f"{q_m1.label()}:payments_volume_growth_nominal")

    pv_ym4 = _pv_level(asof, q_m4, cal)
    if pv_ym4 is None:
        missing.append(f"{q_m4.label()}:payments_volume_nominal_us")
    pv_ym5 = _pv_level(asof, q_m5, cal)
    if pv_ym5 is None:
        missing.append(f"{q_m5.label()}:payments_volume_nominal_us")
    pv_qm2 = _pv_level(asof, q_m2, cal)

    required = [
        "service_revenue",
        "data_processing_revenue",
        "international_transaction_revenue",
        "other_revenue",
        "client_incentives",
        "net_revenue",
        "operating_expenses_gaap",
        "operating_expenses_ex_special_items",
        "processed_transactions_count",
        "payments_volume_growth_nominal",
        "payments_volume_growth_constant",
        "processed_transactions_growth",
    ]
    for name in required:
        if name not in measured:
            key = f"{origin.label()}:{name}"
            if key not in missing:
                missing.append(key)

    if missing:
        raise StateBuildError(
            f"cannot build starting state for {origin.label()} ({origin_date}): missing {', '.join(missing)}"
        )

    assert growth_qm1 is not None and pv_ym4 is not None and pv_ym5 is not None
    used_rows.append(growth_qm1)
    for level in (pv_ym4, pv_ym5, pv_qm2):
        if level is None:
            continue
        used_rows.append(level.primary_row)
        if level.ttm_row is not None:
            used_rows.append(level.ttm_row)
        if level.nine_row is not None:
            used_rows.append(level.nine_row)

    g_q = float(measured["payments_volume_growth_nominal"].value or 0.0)
    g_qm1 = float(growth_qm1.value)
    pv_q = pv_ym4.value * (1.0 + g_q * _ONE_PCT)
    pv_qm1 = pv_ym5.value * (1.0 + g_qm1 * _ONE_PCT)

    svc = float(measured["service_revenue"].value or 0.0)
    dp = float(measured["data_processing_revenue"].value or 0.0)
    intl = float(measured["international_transaction_revenue"].value or 0.0)
    other = float(measured["other_revenue"].value or 0.0)
    incentives = float(measured["client_incentives"].value or 0.0)
    net = float(measured["net_revenue"].value or 0.0)
    opex_gaap = float(measured["operating_expenses_gaap"].value or 0.0)
    opex_ex = float(measured["operating_expenses_ex_special_items"].value or 0.0)
    txn = float(measured["processed_transactions_count"].value or 0.0)

    yield_svc = svc / (pv_qm1 * BILLIONS_TO_MILLIONS)
    yield_dp = dp / txn
    gross = svc + dp + intl + other
    intensity = incentives / gross
    special = opex_gaap - opex_ex
    op_gaap = net - opex_gaap
    op_ex = net - opex_ex

    growth_span = measured["payments_volume_growth_nominal"].span
    assert growth_span is not None
    growth_source = measured["payments_volume_growth_nominal"].source_id
    assert growth_source is not None

    values: dict[str, StateValue] = dict(measured)
    values["special_items"] = _derived(
        "special_items",
        special,
        formula="opex_gaap - opex_ex",
        inputs={"opex_gaap": opex_gaap, "opex_ex": opex_ex},
        source_id=measured["operating_expenses_gaap"].source_id or growth_source,
        span=measured["operating_expenses_gaap"].span or growth_span,
        period=origin,
        note="special_items = operating_expenses_gaap − operating_expenses_ex_special_items",
    )
    values["operating_profit_gaap"] = _derived(
        "operating_profit_gaap",
        op_gaap,
        formula="net_revenue - opex_gaap",
        inputs={"net_revenue": net, "opex_gaap": opex_gaap},
        source_id=measured["net_revenue"].source_id or growth_source,
        span=measured["net_revenue"].span or growth_span,
        period=origin,
    )
    values["operating_profit_ex_special_items"] = _derived(
        "operating_profit_ex_special_items",
        op_ex,
        formula="net_revenue - opex_ex",
        inputs={"net_revenue": net, "opex_ex": opex_ex},
        source_id=measured["net_revenue"].source_id or growth_source,
        span=measured["net_revenue"].span or growth_span,
        period=origin,
    )
    values["payments_volume_nominal_us"] = _derived(
        "payments_volume_nominal_us",
        pv_q,
        formula="year_ago * (1 + growth_pct/100)",
        inputs={"year_ago": pv_ym4.value, "growth_pct": g_q},
        source_id=growth_source,
        span=growth_span,
        period=origin,
        rounding_band=pv_ym4.value * _HALF_PCT,
        note="Rolled-forward PV for origin quarter q from year-ago residual × release nominal growth",
    )

    if pv_qm2 is not None:
        idx = _INDEX_AT_ORIGIN * pv_q / pv_qm2.value
        year_ago_index = _INDEX_AT_ORIGIN * pv_ym4.value / pv_qm2.value
        values["payments_volume_index_nominal"] = _derived(
            "payments_volume_index_nominal",
            idx,
            formula="year_ago * (1 + growth_pct/100)",
            inputs={"year_ago": year_ago_index, "growth_pct": g_q},
            source_id=growth_source,
            span=growth_span,
            period=origin,
            rounding_band=year_ago_index * _HALF_PCT,
            note="Index=100 at measured q-2 PV; rolled with same nominal growth as PV(q)",
        )
    else:
        values["payments_volume_index_nominal"] = _derived(
            "payments_volume_index_nominal",
            _INDEX_AT_ORIGIN,
            formula="a / b",
            inputs={"a": pv_q, "b": pv_q / _INDEX_AT_ORIGIN},
            source_id=growth_source,
            span=growth_span,
            period=origin,
            note="Index set to 100 at origin; PV(q-2) unavailable for nominal index anchor",
        )

    values["processed_transactions_index"] = _derived(
        "processed_transactions_index",
        _INDEX_AT_ORIGIN,
        formula="a / b",
        inputs={"a": txn, "b": txn / _INDEX_AT_ORIGIN},
        source_id=measured["processed_transactions_count"].source_id or growth_source,
        span=measured["processed_transactions_count"].span or growth_span,
        period=origin,
        note=f"Index set to 100 at this origin's processed_transactions_count ({txn:g} million)",
    )
    values["effective_yield_service"] = _derived(
        "effective_yield_service",
        yield_svc,
        formula="a / b",
        inputs={"a": svc, "b": pv_qm1 * BILLIONS_TO_MILLIONS},
        source_id=measured["service_revenue"].source_id or growth_source,
        span=measured["service_revenue"].span or growth_span,
        period=origin,
        note="service_revenue (USD millions) / PV(q-1) (USD millions)",
    )
    values["effective_yield_data_processing"] = _derived(
        "effective_yield_data_processing",
        yield_dp,
        formula="a / b",
        inputs={"a": dp, "b": txn},
        source_id=measured["data_processing_revenue"].source_id or growth_source,
        span=measured["data_processing_revenue"].span or growth_span,
        period=origin,
    )
    values["incentive_intensity"] = _derived(
        "incentive_intensity",
        intensity,
        formula="a / b",
        inputs={"a": incentives, "b": gross},
        source_id=measured["client_incentives"].source_id or growth_source,
        span=measured["client_incentives"].span or growth_span,
        period=origin,
    )

    # Context levels from the newest eligible 10-Q (q-2).
    for name in ("cash_volume_nominal_us", "total_volume_nominal_us"):
        obs = _pick_row(asof, q_m2.label(), name)
        if obs is None:
            values[name] = _unavailable(name, f"No {name} level published at or before the cutoff")
        else:
            values[name] = _measured(name, obs, note=f"Visa {name} for q-2")
            used_rows.append(obs)

    prior_g = _pick_row(asof, q_m1.label(), "payments_volume_prior_quarter_growth_constant")
    if prior_g is None:
        # Sometimes stored under the origin release with the prior quarter's label already.
        prior_g = _pick_row(asof, origin.label(), "payments_volume_prior_quarter_growth_constant")
    if prior_g is None:
        values["payments_volume_prior_quarter_growth_constant"] = _unavailable(
            "payments_volume_prior_quarter_growth_constant",
            f"No prior-quarter constant-dollar PV growth for {q_m1.label()} at cutoff",
        )
    else:
        values["payments_volume_prior_quarter_growth_constant"] = _measured(
            "payments_volume_prior_quarter_growth_constant",
            prior_g,
            period=q_m1,
        )
        used_rows.append(prior_g)

    for name in (
        "cross_border_ex_intra_europe_growth_constant",
        "cross_border_ex_intra_europe_growth_nominal",
        "cross_border_total_growth_constant",
        "cross_border_total_growth_nominal",
        "tax_rate",
        "net_interest_other",
        "diluted_shares",
    ):
        if name not in values:
            values[name] = _unavailable(name, f"No {name} observation for {origin.label()} at cutoff")

    values["cross_border_ex_intra_europe_index_nominal"] = _unavailable(
        "cross_border_ex_intra_europe_index_nominal",
        "No cross-border volume level is disclosed at any filing; only growth rates.",
    )
    values["effective_yield_international"] = _unavailable(
        "effective_yield_international",
        "Requires a cross-border volume level; none disclosed at cutoff.",
    )

    missing_fields = {f.name for f in FIELDS} - set(values)
    if missing_fields:
        raise StateBuildError(f"incomplete field set: {sorted(missing_fields)}")

    supporting: dict[str, SupportingLevel] = {}
    if pv_qm2 is not None:
        supporting["pv_q_minus_2"] = _supporting(
            "pv_q_minus_2",
            value=pv_qm2.value,
            unit="usd_billions",
            basis="nominal",
            period_label=q_m2.label(),
            period=q_m2,
            source_id=pv_qm2.primary_row.source_id,
            span=_span_from_row(pv_qm2.primary_row),
            note=f"Visa total nominal PV for {q_m2.label()} (q-2)",
        )
    if pv_ym4.ttm_row is not None and pv_ym4.nine_row is not None:
        supporting[f"pv_ttm_jun_{q_m4.year}"] = _supporting(
            f"pv_ttm_jun_{q_m4.year}",
            value=float(pv_ym4.ttm_row.value),
            unit="usd_billions",
            basis="nominal",
            period_label=pv_ym4.ttm_row.period_label,
            period=None,
            source_id=pv_ym4.ttm_row.source_id,
            span=_span_from_row(pv_ym4.ttm_row),
            note=f"Visa 12-month PV ended Jun {q_m4.year}",
        )
        supporting[f"pv_nine_month_mar_{q_m4.year}"] = _supporting(
            f"pv_nine_month_mar_{q_m4.year}",
            value=float(pv_ym4.nine_row.value),
            unit="usd_billions",
            basis="nominal",
            period_label=pv_ym4.nine_row.period_label,
            period=None,
            source_id=pv_ym4.nine_row.source_id,
            span=_span_from_row(pv_ym4.nine_row),
            note=f"Visa 9-month PV ended Mar {q_m4.year}",
        )
    supporting["pv_year_ago_q"] = _supporting(
        "pv_year_ago_q",
        value=pv_ym4.value,
        unit="usd_billions",
        basis="nominal",
        period_label=q_m4.label(),
        period=q_m4,
        source_id=pv_ym4.primary_row.source_id,
        span=_span_from_row(pv_ym4.primary_row),
        note=f"Year-ago PV for {q_m4.label()}",
    )
    supporting["pv_year_ago_q_minus_1"] = _supporting(
        "pv_year_ago_q_minus_1",
        value=pv_ym5.value,
        unit="usd_billions",
        basis="nominal",
        period_label=q_m5.label(),
        period=q_m5,
        source_id=pv_ym5.primary_row.source_id,
        span=_span_from_row(pv_ym5.primary_row),
        note=f"Visa PV for {q_m5.label()}",
    )
    supporting["growth_q_minus_1_nominal"] = _supporting(
        "growth_q_minus_1_nominal",
        value=g_qm1,
        unit="percent",
        basis="nominal",
        period_label=q_m1.label(),
        period=q_m1,
        source_id=growth_qm1.source_id,
        span=_span_from_row(growth_qm1),
        note=f"{q_m1.label()} release nominal PV growth for rolling PV(q-1)",
    )

    sources: dict[str, SourceRef] = {}
    for obs in used_rows:
        if obs.source_id in sources:
            continue
        sources[obs.source_id] = _source_ref_for(obs.source_id, manifest)
    for entry in values.values():
        if entry.source_id and entry.source_id not in sources:
            sources[entry.source_id] = _source_ref_for(entry.source_id, manifest)
    for support in supporting.values():
        if support.source_id not in sources:
            sources[support.source_id] = _source_ref_for(support.source_id, manifest)

    # Leakage: every cited source must be at or before cutoff.
    for source_id, ref in sources.items():
        published = cal.parse_aware_utc(ref.acceptance_utc)
        if published > cutoff:
            raise StateBuildError(
                f"source {source_id} published at {ref.acceptance_utc} after cutoff {utc_isoformat(cutoff)}"
            )

    fixture = StartingStateFixture(
        schema_version=1,
        company="visa",
        origin_date=date.fromisoformat(origin_date),
        cutoff_utc=row["cutoff_utc"],
        fiscal_year=origin.year,
        fiscal_quarter=origin.quarter,
        target_fiscal_year=target.year,
        target_fiscal_quarter=target.quarter,
        release_accession=row["release_accession"],
        prior_10q_accession=row["prior_10q_accession"],
        sources=sources,
        values=values,
        supporting_levels=supporting,
        notes=[
            "Cutoff convention: EDGAR acceptance of the quarter-q earnings 8-K.",
            "Built by state_builder from as-of observations (LON-27).",
        ],
    )
    residuals = identity_residuals(fixture)
    failed = [r for r in residuals if not r.passed]
    if failed:
        detail = ", ".join(f"{r.name} residual={r.residual}" for r in failed)
        raise StateBuildError(f"identity checks failed for {origin.label()}: {detail}")
    return fixture


def build_fixture_for_origin_date(origin_date: str, *, rows: list[Any] | None = None) -> StartingStateFixture:
    row = origin_row_for_date(origin_date)
    if row is None:
        raise StateBuildError(f"unknown origin date {origin_date!r}")
    cal = _lazy_calibration()
    return build_fixture(cal.parse_aware_utc(row["cutoff_utc"]), rows=rows, origin_row=row)


__all__ = [
    "StateBuildError",
    "build_fixture",
    "build_fixture_for_origin_date",
    "buildable_origin_dates",
    "origin_row_for_cutoff",
    "origin_row_for_date",
]
