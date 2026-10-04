"""Eligible evaluation origins from origins.csv (LON-27)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.runs.inputs import parse_aware_utc

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
ORIGINS_CSV = PACKAGE_ROOT / "data" / "fixtures" / "origins.csv"

EXCLUSION_FY2021Q3_PV = (
    "FY2021Q3 payments-volume level is not in the parsed observations "
    "(FY2020/FY2021 10-K 12-month tables not extracted); starting state cannot be built"
)


@dataclass(frozen=True, slots=True)
class EvaluationOrigin:
    origin_date: str
    cutoff_ts: datetime
    origin: FiscalPeriod
    target: FiscalPeriod
    origin_window: str
    status: str
    target_release_accession: str
    target_release_accepted_utc: str | None
    exclusion_reason: str | None = None

    @property
    def label(self) -> str:
        return self.origin.label()

    @property
    def scored(self) -> bool:
        return self.status == "candidate" and self.exclusion_reason is None


def _known_exclusions() -> dict[str, str]:
    return {
        "2022-07-26": EXCLUSION_FY2021Q3_PV,  # FY2022Q3
        "2022-10-25": EXCLUSION_FY2021Q3_PV,  # FY2022Q4
    }


def load_evaluation_origins(
    *,
    window: str = "all",
    origin_dates: list[str] | None = None,
    include_prospective: bool = False,
) -> list[EvaluationOrigin]:
    """Load candidate origins; mark known exclusions. Prospective is listed only when requested."""
    if window not in {"all", "primary", "extension"}:
        raise ValueError(f"window must be all|primary|extension, got {window!r}")
    exclusions = _known_exclusions()
    wanted = set(origin_dates) if origin_dates is not None else None
    out: list[EvaluationOrigin] = []
    with ORIGINS_CSV.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            status = row["status"]
            if status == "prospective" and not include_prospective:
                continue
            if status not in {"candidate", "prospective"}:
                continue
            origin_date = row["cutoff_utc"][:10]
            if wanted is not None and origin_date not in wanted:
                continue
            origin_window = row["origin_window"]
            if window != "all" and origin_window != window:
                continue
            target_accepted = row.get("target_release_accepted_utc") or None
            if target_accepted == "":
                target_accepted = None
            out.append(
                EvaluationOrigin(
                    origin_date=origin_date,
                    cutoff_ts=parse_aware_utc(row["cutoff_utc"]),
                    origin=FiscalPeriod(int(row["fiscal_year"]), int(row["fiscal_quarter"])),
                    target=FiscalPeriod(int(row["target_fiscal_year"]), int(row["target_fiscal_quarter"])),
                    origin_window=origin_window,
                    status=status,
                    target_release_accession=row.get("target_release_accession") or "",
                    target_release_accepted_utc=target_accepted,
                    exclusion_reason=exclusions.get(origin_date),
                )
            )
    out.sort(key=lambda item: item.cutoff_ts)
    return out


def scored_origins(**kwargs: object) -> list[EvaluationOrigin]:
    return [origin for origin in load_evaluation_origins(**kwargs) if origin.scored]  # type: ignore[arg-type]


__all__ = [
    "EXCLUSION_FY2021Q3_PV",
    "EvaluationOrigin",
    "ORIGINS_CSV",
    "load_evaluation_origins",
    "scored_origins",
]
