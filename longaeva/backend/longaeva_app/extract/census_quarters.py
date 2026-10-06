"""One verified Census trailing-three-month print per Visa quarter (LON-31)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, datetime
from functools import lru_cache

from longaeva_app.extract.census_vintages import (
    PARSE_STATUS_PATH,
    VINTAGES_PATH,
    VintageRow,
    as_of,
    load_parse_status,
    load_vintages,
)


@lru_cache(maxsize=2)
def _retained(mtime_ns: int, size: int, status_mtime_ns: int) -> tuple[VintageRow, ...]:
    del mtime_ns, size, status_mtime_ns
    verified = {
        item["release_id"]
        for item in load_parse_status()
        if item["status"] == "parsed" and item["hash_verified"] == "true" and item["integrity_flag"] == "ok"
    }
    return tuple(row for row in load_vintages() if row.release_id in verified)


def quarter_prints(cutoff: datetime, rows: Sequence[VintageRow] | None = None) -> list[VintageRow]:
    """Use the latest eligible vintage of each quarter-end cell; never count a quarter twice."""
    if rows is None:
        stat = VINTAGES_PATH.stat()
        rows = _retained(stat.st_mtime_ns, stat.st_size, PARSE_STATUS_PATH.stat().st_mtime_ns)
    candidates = as_of(
        cutoff,
        list(rows),
        series="retail_food_services_total",
        measure="yoy_3m_pct",
        basis="sa",
        allow_possibly_replaced=False,
    )
    selected: dict[str, VintageRow] = {}
    for row in candidates:
        end = date.fromisoformat(row.period_end)
        expected_day = 30 if end.month in {6, 9} else 31
        if end.month not in {3, 6, 9, 12} or end.day != expected_day:
            continue
        if row.estimate_status != "three_month" or row.value_flag or row.unit != "pct":
            continue
        try:
            value = float(row.value)
        except ValueError:
            continue
        if not math.isfinite(value):
            continue
        previous = selected.get(row.period_end)
        if previous is None or (row.publication_ts, row.release_id) > (previous.publication_ts, previous.release_id):
            selected[row.period_end] = row
    return [selected[key] for key in sorted(selected)]
