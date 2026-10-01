"""Tests for Visa origin inventory eligibility and builders (LON-1)."""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from longaeva_app.collect.edgar_index import (
    CSV_COLUMNS,
    ORIGINS_CSV_PATH,
    SNAPSHOT_PATH,
    FiscalQuarter,
    build_origins,
    fiscal_quarter_from_period_end,
    fiscal_quarter_from_release_date,
    is_eligible,
    load_snapshot,
    parse_acceptance_datetime,
    parse_submissions,
)

EASTERN = ZoneInfo("America/New_York")


def test_is_eligible_boundary_exact_and_one_second_late() -> None:
    cutoff = datetime(2024, 7, 23, 20, 5, 0, tzinfo=UTC)
    assert is_eligible(cutoff, cutoff) is True
    assert is_eligible(cutoff.replace(second=1), cutoff) is False
    assert is_eligible(cutoff.replace(second=0, microsecond=0), cutoff) is True


def test_is_eligible_rejects_naive_datetimes() -> None:
    cutoff = datetime(2024, 7, 23, 20, 5, 0, tzinfo=UTC)
    naive = datetime(2024, 7, 23, 20, 5, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        is_eligible(naive, cutoff)
    with pytest.raises(ValueError, match="timezone-aware"):
        is_eligible(cutoff, naive)


def test_parse_acceptance_datetime_eastern_wall_clock() -> None:
    # Planning note: 16:05 ET → 20:05 UTC (EDT)
    dt = parse_acceptance_datetime("2024-07-23 16:05:00")
    assert dt == datetime(2024, 7, 23, 20, 5, 0, tzinfo=UTC)


def test_fiscal_quarter_mapping_all_four_quarters() -> None:
    assert fiscal_quarter_from_release_date(date(2024, 1, 25)) == FiscalQuarter(2024, 1)
    assert fiscal_quarter_from_release_date(date(2024, 4, 23)) == FiscalQuarter(2024, 2)
    assert fiscal_quarter_from_release_date(date(2024, 7, 23)) == FiscalQuarter(2024, 3)
    assert fiscal_quarter_from_release_date(date(2024, 10, 29)) == FiscalQuarter(2024, 4)
    assert fiscal_quarter_from_period_end(date(2023, 12, 31)) == FiscalQuarter(2024, 1)
    assert fiscal_quarter_from_period_end(date(2024, 9, 30)) == FiscalQuarter(2024, 4)


def test_period_end_mismatch_recorded_as_exclusion_reason() -> None:
    """A release whose period_of_report disagrees with the date-based quarter is flagged."""
    snapshot = {
        "visa_filings": [
            {
                "cik": 1403161,
                "accession": "0001403161-24-000046",
                "form": "8-K",
                "filed_date": "2024-07-23",
                "accepted_utc": "2024-07-23T20:05:00Z",
                "period_of_report": "2024-03-31",  # Q2, not Q3
                "items": "2.02,9.01",
                "primary_document": "q3.htm",
                "is_amendment": False,
            },
            {
                "cik": 1403161,
                "accession": "0001403161-24-000040",
                "form": "10-Q",
                "filed_date": "2024-04-25",
                "accepted_utc": "2024-04-25T21:00:00Z",
                "period_of_report": "2024-03-31",
                "items": "",
                "primary_document": "q2.htm",
                "is_amendment": False,
            },
            # Prior for the mismatched Q2 mapping: need FY2024Q1 10-Q (period 2023-12-31)
            {
                "cik": 1403161,
                "accession": "0001403161-24-000020",
                "form": "10-Q",
                "filed_date": "2024-01-26",
                "accepted_utc": "2024-01-26T21:00:00Z",
                "period_of_report": "2023-12-31",
                "items": "",
                "primary_document": "q1.htm",
                "is_amendment": False,
            },
            # Target for Q2 → Q3 needs a later release to avoid "no realized target"
            {
                "cik": 1403161,
                "accession": "0001403161-24-000050",
                "form": "8-K",
                "filed_date": "2024-10-29",
                "accepted_utc": "2024-10-29T20:05:00Z",
                "period_of_report": "2024-09-30",
                "items": "2.02",
                "primary_document": "q4.htm",
                "is_amendment": False,
            },
            {
                "cik": 1403161,
                "accession": "0001403161-24-000045",
                "form": "10-Q",
                "filed_date": "2024-07-24",
                "accepted_utc": "2024-07-24T21:00:00Z",
                "period_of_report": "2024-06-30",
                "items": "",
                "primary_document": "q3.htm",
                "is_amendment": False,
            },
        ],
        "booking_filings": [
            {
                "cik": 1075531,
                "accession": "0001075531-24-000030",
                "form": "8-K",
                "filed_date": "2024-05-02",
                "accepted_utc": "2024-05-02T20:03:00Z",
                "period_of_report": "2024-03-31",
                "items": "2.02",
                "primary_document": "bk.htm",
                "is_amendment": False,
            }
        ],
        "spot_checks": [],
    }
    rows = build_origins(snapshot)
    # Prefer period_of_report → FY2024Q2
    q2 = next(r for r in rows if r["fiscal_year"] == 2024 and r["fiscal_quarter"] == 2)
    assert "period_of_report" in q2["exclusion_reasons"]
    assert "maps to" in q2["exclusion_reasons"]


def _toy_snapshot_for_late_document() -> dict:
    """Release at T; prior 10-Q before T; same-quarter 10-Q at T+2h; Booking after T."""
    return {
        "visa_filings": [
            {
                "cik": 1403161,
                "accession": "0001403161-24-000046",
                "form": "8-K",
                "filed_date": "2024-07-23",
                "accepted_utc": "2024-07-23T20:05:00Z",
                "period_of_report": "2024-06-30",
                "items": "2.02,9.01",
                "primary_document": "earn.htm",
                "is_amendment": False,
            },
            {
                "cik": 1403161,
                "accession": "0001403161-24-000050",
                "form": "8-K",
                "filed_date": "2024-10-29",
                "accepted_utc": "2024-10-29T20:05:00Z",
                "period_of_report": "2024-09-30",
                "items": "2.02",
                "primary_document": "earn2.htm",
                "is_amendment": False,
            },
            {
                "cik": 1403161,
                "accession": "0001403161-24-000040",
                "form": "10-Q",
                "filed_date": "2024-04-25",
                "accepted_utc": "2024-04-25T21:00:00Z",
                "period_of_report": "2024-03-31",
                "items": "",
                "primary_document": "prior.htm",
                "is_amendment": False,
            },
            {
                "cik": 1403161,
                "accession": "0001403161-24-000047",
                "form": "10-Q",
                "filed_date": "2024-07-23",
                "accepted_utc": "2024-07-23T22:05:00Z",  # +2 hours
                "period_of_report": "2024-06-30",
                "items": "",
                "primary_document": "same.htm",
                "is_amendment": False,
            },
            {
                "cik": 1403161,
                "accession": "0001403161-24-000051",
                "form": "10-K",
                "filed_date": "2024-11-15",
                "accepted_utc": "2024-11-15T21:00:00Z",
                "period_of_report": "2024-09-30",
                "items": "",
                "primary_document": "10k.htm",
                "is_amendment": False,
            },
        ],
        "booking_filings": [
            {
                "cik": 1075531,
                "accession": "0001075531-24-000030",
                "form": "8-K",
                "filed_date": "2024-05-02",
                "accepted_utc": "2024-05-02T20:03:00Z",
                "period_of_report": "2024-03-31",
                "items": "2.02",
                "primary_document": "bk.htm",
                "is_amendment": False,
            },
            {
                "cik": 1075531,
                "accession": "0001075531-24-000040",
                "form": "8-K",
                "filed_date": "2024-07-23",
                "accepted_utc": "2024-07-23T20:10:00Z",  # 5 minutes after Visa cutoff
                "period_of_report": "2024-06-30",
                "items": "2.02",
                "primary_document": "bk2.htm",
                "is_amendment": False,
            },
        ],
        "spot_checks": [],
    }


def test_late_document_fixture_same_quarter_excluded_prior_included() -> None:
    rows = build_origins(_toy_snapshot_for_late_document())
    origin = next(r for r in rows if r["fiscal_year"] == 2024 and r["fiscal_quarter"] == 3)
    assert origin["prior_10q_eligible"] == "true"
    assert origin["same_q_10q_eligible"] == "false"
    assert float(origin["same_q_10q_hours_after_cutoff"]) == pytest.approx(2.0)


def test_booking_release_minutes_after_cutoff_not_selected() -> None:
    rows = build_origins(_toy_snapshot_for_late_document())
    origin = next(r for r in rows if r["fiscal_year"] == 2024 and r["fiscal_quarter"] == 3)
    assert origin["booking_accession"] == "0001075531-24-000030"
    assert origin["booking_eligible"] == "true"
    assert "0001075531-24-000040" != origin["booking_accession"]


def test_prospective_origin_when_no_target_release() -> None:
    snapshot = {
        "visa_filings": [
            {
                "cik": 1403161,
                "accession": "0001403161-26-000040",
                "form": "8-K",
                "filed_date": "2026-07-28",
                "accepted_utc": "2026-07-28T20:05:00Z",
                "period_of_report": "2026-06-30",
                "items": "2.02",
                "primary_document": "earn.htm",
                "is_amendment": False,
            },
            {
                "cik": 1403161,
                "accession": "0001403161-26-000030",
                "form": "10-Q",
                "filed_date": "2026-04-29",
                "accepted_utc": "2026-04-29T21:00:00Z",
                "period_of_report": "2026-03-31",
                "items": "",
                "primary_document": "prior.htm",
                "is_amendment": False,
            },
        ],
        "booking_filings": [
            {
                "cik": 1075531,
                "accession": "0001075531-26-000020",
                "form": "8-K",
                "filed_date": "2026-05-01",
                "accepted_utc": "2026-05-01T20:03:00Z",
                "period_of_report": "2026-03-31",
                "items": "2.02",
                "primary_document": "bk.htm",
                "is_amendment": False,
            }
        ],
        "spot_checks": [],
    }
    rows = build_origins(snapshot)
    assert len(rows) == 1
    assert rows[0]["status"] == "prospective"
    assert rows[0]["origin_window"] == "prospective"
    assert rows[0]["target_release_accession"] == ""
    assert int(rows[0]["target_fiscal_year"]) == 2026
    assert int(rows[0]["target_fiscal_quarter"]) == 4


def test_duplicate_item_202_and_amendment_flagged() -> None:
    snapshot = {
        "visa_filings": [
            {
                "cik": 1403161,
                "accession": "0001403161-24-000046",
                "form": "8-K",
                "filed_date": "2024-07-23",
                "accepted_utc": "2024-07-23T20:05:00Z",
                "period_of_report": "2024-06-30",
                "items": "2.02",
                "primary_document": "earn.htm",
                "is_amendment": False,
            },
            {
                "cik": 1403161,
                "accession": "0001403161-24-000047",
                "form": "8-K",
                "filed_date": "2024-07-24",
                "accepted_utc": "2024-07-24T20:05:00Z",
                "period_of_report": "2024-06-30",
                "items": "2.02",
                "primary_document": "earn2.htm",
                "is_amendment": False,
            },
            {
                "cik": 1403161,
                "accession": "0001403161-24-000048",
                "form": "8-K/A",
                "filed_date": "2024-07-25",
                "accepted_utc": "2024-07-25T20:05:00Z",
                "period_of_report": "2024-06-30",
                "items": "2.02",
                "primary_document": "earn-a.htm",
                "is_amendment": True,
            },
            {
                "cik": 1403161,
                "accession": "0001403161-24-000050",
                "form": "8-K",
                "filed_date": "2024-10-29",
                "accepted_utc": "2024-10-29T20:05:00Z",
                "period_of_report": "2024-09-30",
                "items": "2.02",
                "primary_document": "q4.htm",
                "is_amendment": False,
            },
            {
                "cik": 1403161,
                "accession": "0001403161-24-000040",
                "form": "10-Q",
                "filed_date": "2024-04-25",
                "accepted_utc": "2024-04-25T21:00:00Z",
                "period_of_report": "2024-03-31",
                "items": "",
                "primary_document": "prior.htm",
                "is_amendment": False,
            },
        ],
        "booking_filings": [
            {
                "cik": 1075531,
                "accession": "0001075531-24-000030",
                "form": "8-K",
                "filed_date": "2024-05-02",
                "accepted_utc": "2024-05-02T20:03:00Z",
                "period_of_report": "2024-03-31",
                "items": "2.02",
                "primary_document": "bk.htm",
                "is_amendment": False,
            }
        ],
        "spot_checks": [],
    }
    rows = build_origins(snapshot)
    q3 = next(r for r in rows if r["fiscal_year"] == 2024 and r["fiscal_quarter"] == 3)
    assert q3["release_accession"] == "0001403161-24-000046"
    assert "duplicate Item 2.02" in q3["exclusion_reasons"]
    assert "0001403161-24-000047" in q3["exclusion_reasons"]
    # Amendment must not become its own origin row
    assert all(r["release_accession"] != "0001403161-24-000048" for r in rows)


def test_parse_submissions_dedupes_by_accession() -> None:
    primary = {
        "filings": {
            "recent": {
                "accessionNumber": ["0001403161-24-000046", "0001403161-24-000040"],
                "form": ["8-K", "10-Q"],
                "filingDate": ["2024-07-23", "2024-04-25"],
                "acceptanceDateTime": ["2024-07-23 16:05:00", "2024-04-25 17:00:00"],
                "reportDate": ["2024-06-30", "2024-03-31"],
                "items": ["2.02", ""],
                "primaryDocument": ["a.htm", "b.htm"],
            }
        }
    }
    page = {
        "accessionNumber": ["0001403161-24-000046", "0001403161-17-000001"],
        "form": ["8-K", "8-K"],
        "filingDate": ["2024-07-23", "2017-01-26"],
        "acceptanceDateTime": ["2024-07-23 16:05:00", "2017-01-26 16:05:00"],
        "reportDate": ["2024-06-30", "2016-12-31"],
        "items": ["2.02", "2.02"],
        "primaryDocument": ["a.htm", "old.htm"],
    }
    filings = parse_submissions(primary, [page], 1403161)
    accessions = [f.accession for f in filings]
    assert accessions.count("0001403161-24-000046") == 1
    assert "0001403161-17-000001" in accessions


@pytest.mark.skipif(not SNAPSHOT_PATH.exists(), reason="filing_index.json not generated yet")
def test_snapshot_regression_meets_acceptance() -> None:
    snapshot = load_snapshot()
    rows = build_origins(snapshot)

    # Rebuilding must reproduce the committed CSV exactly
    assert ORIGINS_CSV_PATH.exists(), "origins.csv must exist for regression"
    committed = ORIGINS_CSV_PATH.read_text(encoding="utf-8")
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in CSV_COLUMNS})
    assert buf.getvalue() == committed

    window = [
        r
        for r in rows
        if int(r["fiscal_year"]) >= 2022 and (int(r["fiscal_year"]) < 2026 or int(r["fiscal_quarter"]) <= 3)
    ]
    calibration = [r for r in rows if r["is_calibration"] == "true" and r["cutoff_utc"]]
    prospective = [r for r in rows if r["status"] == "prospective"]

    assert len(window) >= 18
    assert len(calibration) >= 28
    assert len(prospective) >= 1
    assert any(r["cutoff_utc"].startswith("2026-07-28") for r in prospective)

    # Spot checks should all match
    for s in snapshot.get("spot_checks", []):
        assert s.get("match") is True, f"spot-check failed: {s}"
