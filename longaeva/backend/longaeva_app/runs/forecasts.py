"""Immutable forecast archive writes (LON-23 / FR-17)."""

from __future__ import annotations

import csv
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.definitions import VISA_FISCAL_CALENDAR
from longaeva_app.config import PACKAGE_ROOT
from longaeva_app.db.models import Forecast, ParameterSet, Run, Scenario
from longaeva_app.runs.errors import RunError
from longaeva_app.runs.inputs import parameter_set_is_all_assumption, parse_aware_utc, resolve_fixture

ForecastKind = Literal["retrospective", "prospective"]

ORIGINS_CSV = PACKAGE_ROOT / "data" / "fixtures" / "origins.csv"

ARCHIVE_METRICS: tuple[str, ...] = (
    "net_revenue",
    "operating_profit_ex_special_items",
    "payments_volume_growth_constant",
    "cross_border_ex_intra_europe_growth_constant",
    "processed_transactions_growth",
)

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def expected_forecast_kind(
    *,
    fiscal_year: int,
    fiscal_quarter: int,
    now: datetime | None = None,
) -> ForecastKind:
    """Declare archive kind from whether the next-quarter release is already published."""
    clock = now or _utcnow()
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    else:
        clock = clock.astimezone(UTC)
    with ORIGINS_CSV.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if int(row["fiscal_year"]) != fiscal_year or int(row["fiscal_quarter"]) != fiscal_quarter:
                continue
            accepted = (row.get("target_release_accepted_utc") or "").strip()
            if not accepted:
                return "prospective"
            published = parse_aware_utc(accepted)
            if clock < published:
                return "prospective"
            return "retrospective"
    raise RunError(
        f"No origins.csv row for FY{fiscal_year}Q{fiscal_quarter}",
        status_code=422,
    )


def archive_forecasts(
    session: Session,
    run_id: uuid.UUID,
    *,
    kind: ForecastKind,
    now: datetime | None = None,
) -> list[Forecast]:
    run = session.get(Run, run_id)
    if run is None:
        raise RunError("Run not found", status_code=404)
    if run.status != "succeeded":
        raise RunError("Forecast archive requires a succeeded run", status_code=409)
    if not isinstance(run.summary, list) or not run.summary:
        raise RunError("Succeeded run is missing a summary payload", status_code=409)
    scenario = session.get(Scenario, run.scenario_id)
    if scenario is None:
        raise RunError("Scenario not found", status_code=422)
    if scenario.interventions or run.interventions:
        raise RunError("Intervention scenarios cannot be archived", status_code=422)
    param_row = session.get(ParameterSet, scenario.parameter_set_id)
    if param_row is None:
        raise RunError("Parameter set not found", status_code=422)
    if parameter_set_is_all_assumption(param_row):
        raise RunError("All-assumption (uncalibrated default) parameter sets cannot be archived", status_code=422)

    cutoff = run.cutoff_ts if run.cutoff_ts.tzinfo else run.cutoff_ts.replace(tzinfo=UTC)
    fixture = resolve_fixture(cutoff)
    expected = expected_forecast_kind(
        fiscal_year=fixture.fiscal_year,
        fiscal_quarter=fixture.fiscal_quarter,
        now=now,
    )
    if kind != expected:
        raise RunError(
            f"Declared kind {kind!r} does not match expected {expected!r} for origin {fixture.origin_date.isoformat()}",
            status_code=422,
        )

    existing = session.scalar(select(func.count()).select_from(Forecast).where(Forecast.run_id == run.id))
    if existing:
        raise RunError("This run is already archived", status_code=409)

    origin_period = FiscalPeriod(fixture.fiscal_year, fixture.fiscal_quarter)
    origin_ts = parse_aware_utc(fixture.cutoff_utc)
    by_key = {(item["metric"], int(item["quarter_index"])): item for item in run.summary}
    rows: list[Forecast] = []
    for quarter_index in range(run.n_quarters):
        period = origin_period.next()
        for _ in range(quarter_index):
            period = period.next()
        start = VISA_FISCAL_CALENDAR.period_start(period)
        end = VISA_FISCAL_CALENDAR.period_end(period)
        for metric in ARCHIVE_METRICS:
            item = by_key.get((metric, quarter_index))
            if item is None:
                raise RunError(f"Summary missing {metric} quarter {quarter_index}", status_code=422)
            rows.append(
                Forecast(
                    run_id=run.id,
                    origin_ts=origin_ts,
                    cutoff_ts=cutoff,
                    target_period_start=start,
                    target_period_end=end,
                    metric=metric,
                    quantiles=item.get("quantiles") or {},
                    kind=kind,
                )
            )
    session.add_all(rows)
    session.flush()
    return rows
