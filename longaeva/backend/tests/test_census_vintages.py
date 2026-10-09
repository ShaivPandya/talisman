"""Census MARTS vintage table tests."""

from __future__ import annotations

import csv

from longaeva_app.collect.census_sources import CENSUS_DIR, sample_release_ids
from longaeva_app.collect.edgar_index import ORIGINS_CSV_PATH
from longaeva_app.extract.census_marts import parse_marts_pdf
from longaeva_app.extract.census_vintages import (
    SELECTED_SERIES,
    as_of,
    first_print,
    load_parse_status,
    load_vintages,
    revision_history,
)

JUNE_2024 = "2024-06-01"
TOTAL = "retail_food_services_total"
WINDOW = 116
PARSE_FLOOR = 0.95


def test_parse_status_covers_the_window_and_lists_failures() -> None:
    status = load_parse_status()
    assert len(status) == WINDOW
    assert [row["release_id"] for row in status][0] == "adv1611"
    assert status[-1]["release_id"] == "adv2606"
    parsed = [row for row in status if row["status"] == "parsed"]
    failed = [row for row in status if row["status"] != "parsed"]
    assert len(parsed) / WINDOW >= PARSE_FLOOR
    assert failed, "a replaced file should stay listed rather than parsed from new bytes"
    assert all(row["error"] for row in failed)
    assert all(row["hash_verified"] == "true" for row in parsed)
    replaced = next(row for row in failed if row["release_id"] == "adv2301")
    assert "sha256" in replaced["error"]
    assert {row["release_id"] for row in failed} == {"adv2301"}


def test_as_of_cutoff_returns_the_first_print_not_a_later_revision() -> None:
    rows = load_vintages()
    hit = as_of(
        "2024-07-23T23:59:59Z",
        rows,
        series=TOTAL,
        measure="level",
        basis="sa",
        period_start=JUNE_2024,
    )
    assert len(hit) == 1
    assert hit[0].release_id == "adv2406"
    assert hit[0].estimate_status == "advance"
    assert float(hit[0].value) == 704324.0
    assert hit[0].publication_ts <= "2024-07-23T23:59:59Z"


def test_later_cutoff_sees_only_revisions_published_by_then() -> None:
    rows = load_vintages()
    hit = as_of(
        "2025-07-17T12:30:00Z",
        rows,
        series=TOTAL,
        measure="level",
        basis="sa",
        period_start=JUNE_2024,
    )
    assert len(hit) == 1
    assert hit[0].release_id == "adv2506"
    assert float(hit[0].value) == 692922.0
    assert hit[0].release_id != "adv2406"


def test_first_print_and_revision_chain_for_june_2024() -> None:
    rows = load_vintages()
    printed = first_print(TOTAL, "sa", JUNE_2024, rows)
    assert printed is not None
    assert printed.release_id == "adv2406"
    assert printed.supersedes_release_id == ""
    history = revision_history(TOTAL, "sa", JUNE_2024, rows)
    assert history[0].release_id == "adv2406"
    assert history[1].supersedes_release_id == "adv2406"
    revised = next(row for row in history if row.release_id == "adv2506")
    assert float(revised.value) == 692922.0
    assert revised.supersedes_release_id
    assert all(history[index].publication_ts <= history[index + 1].publication_ts for index in range(len(history) - 1))


def test_possibly_replaced_release_is_skipped_when_asked() -> None:
    rows = load_vintages()
    cutoff = "2019-02-20T00:00:00Z"
    included = as_of(
        cutoff,
        rows,
        series=TOTAL,
        measure="level",
        basis="sa",
        period_start="2018-12-01",
        allow_possibly_replaced=True,
    )
    excluded = as_of(
        cutoff,
        rows,
        series=TOTAL,
        measure="level",
        basis="sa",
        period_start="2018-12-01",
        allow_possibly_replaced=False,
    )
    assert len(included) == 1
    assert included[0].release_id == "adv1812"
    assert included[0].integrity_flag == "possibly_replaced"
    assert excluded == []
    fallback = as_of(
        cutoff,
        rows,
        series=TOTAL,
        measure="level",
        basis="sa",
        period_start="2018-11-01",
        allow_possibly_replaced=False,
    )
    assert len(fallback) == 1
    assert fallback[0].integrity_flag == "ok"
    assert fallback[0].release_id != "adv1812"


def test_origin_cutoffs_never_see_a_later_publication() -> None:
    rows = load_vintages()
    with ORIGINS_CSV_PATH.open(encoding="utf-8", newline="") as handle:
        origins = list(csv.DictReader(handle))
    assert origins
    for origin in origins:
        visible = as_of(origin["cutoff_utc"], rows, series=TOTAL)
        assert visible, origin["cutoff_utc"]
        assert all(row.publication_ts <= origin["cutoff_utc"] for row in visible)


def test_department_store_code_change_is_not_a_revision_link() -> None:
    rows = load_vintages()
    history = [row for row in revision_history("naics_452_dept", "sa", JUNE_2024, rows) if row.measure == "level"]
    codes = {row.naics_code for row in history}
    assert "4521" in codes
    assert "4522" in codes
    for previous, current in zip(history, history[1:], strict=False):
        if previous.naics_code != current.naics_code:
            assert current.supersedes_release_id == ""


def test_selected_series_and_gate_glob() -> None:
    names = sorted(path.name for path in CENSUS_DIR.glob("adv*.csv"))
    assert names == ["adv2406.csv", "adv2506.csv"]
    rows = load_vintages()
    assert {row.series_key for row in rows} <= SELECTED_SERIES
    assert TOTAL in {row.series_key for row in rows}
    assert all(row.measure == "level" or row.table == "2" for row in rows)


def test_fixture_pdfs_match_the_vintage_table() -> None:
    rows = load_vintages()
    release_ids = ["adv2406", "adv2506", *sample_release_ids()]
    for release_id in release_ids:
        _meta, parsed = parse_marts_pdf(CENSUS_DIR / "sources" / f"{release_id}.pdf", release_id=release_id)
        fresh = {
            (row.series_key, row.measure, row.basis, row.period_start, row.estimate_status): row.value
            for row in parsed
            if row.series_key in SELECTED_SERIES
            and ((row.table == "1" and row.measure == "level") or row.table == "2")
            and row.value
        }
        committed = {
            (row.series_key, row.measure, row.basis, row.period_start, row.estimate_status): row.value
            for row in rows
            if row.release_id == release_id and row.value
        }
        assert fresh == committed, release_id
