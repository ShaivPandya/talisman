"""Benchmark gate tests (LON-6 / DR-01 / DR-07 / FR-14)."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any, cast

import pytest
import xlrd
import yaml

from longaeva_app.collect.benchmark_sources import (
    MANIFEST_PATH,
    PROBE_DIR,
    PROBE_PATH,
    coverage_ok,
    ex_dividend_date,
    html_to_text,
    load_manifest,
    parse_fred_csv,
    parse_ken_french_zip,
    parse_retained_visa_dividends,
    parse_shiller_xls,
    parse_visa_dividend_text,
)
from longaeva_app.collect.edgar_index import PACKAGE_ROOT

REQUIRED_SOURCE_FIELDS = {
    "provider",
    "series",
    "access_method",
    "url",
    "terms_url",
    "retrieval_date",
    "key_required",
    "key_env",
    "redistribution",
    "probe",
}


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return load_manifest()


@pytest.fixture(scope="module")
def probe() -> dict[str, Any]:
    assert PROBE_PATH.is_file(), "probe.json missing; run: python -m longaeva_app.collect.benchmark_sources probe"
    return cast(dict[str, Any], json.loads(PROBE_PATH.read_text(encoding="utf-8")))


def test_manifest_exists_and_loads(manifest: dict[str, Any]) -> None:
    assert MANIFEST_PATH.is_file()
    assert manifest["decision"]["primary_option"] == "B"
    assert manifest["decision"]["secondary_option"] == "C"
    assert manifest["decision"]["key_registration"] == "none"
    assert manifest["decision"]["visa_prices"] == "blocked"


def test_required_source_fields(manifest: dict[str, Any]) -> None:
    sources = manifest["sources"]
    assert isinstance(sources, dict)
    for source_id, cfg in sources.items():
        missing = REQUIRED_SOURCE_FIELDS - set(cfg)
        assert not missing, f"{source_id} missing fields: {missing}"
        assert cfg["retrieval_date"] == "2026-10-02"
        # Never embed secret material; only env var names.
        assert cfg["key_env"] in {None, "TIINGO_API_KEY", "ALPHA_VANTAGE_API_KEY"}
        assert cfg.get("api_key") is None
        blob = yaml.safe_dump(cfg)
        assert "TIINGO_API_KEY=" not in blob
        assert "ALPHA_VANTAGE_API_KEY=" not in blob
        assert "Bearer " not in blob


def test_label_rule(manifest: dict[str, Any]) -> None:
    labels = manifest["labels"]
    primary = labels["primary"]
    assert "S&P 500 total return" in primary
    assert "approximation" in primary.lower()
    assert "FRED" in primary
    assert "Shiller" in primary

    secondary = labels["secondary"]
    assert "not the S&P 500" in secondary

    for value in labels.values():
        assert "consensus" not in value.lower()

    footnote = labels["primary_footnote"]
    assert "Not the official S&P 500 Total Return" in footnote
    assert "FRED" in footnote and "Shiller" in footnote


def test_fallback_chain_and_roles(manifest: dict[str, Any]) -> None:
    assert manifest["fallback_chain"] == ["A", "B", "C"]
    series = {s["id"]: s for s in manifest["series"]}
    primaries = [s for s in manifest["series"] if s.get("role") == "primary_benchmark"]
    assert len(primaries) == 1
    assert primaries[0]["option"] == "B"
    assert primaries[0]["status"] == "selected"

    visa = series["visa_buy_and_hold"]
    assert visa["status"] == "blocked"
    assert visa["unblock_source"] == "tiingo_visa"
    assert "tiingo_visa" in manifest["sources"]

    rejected_a = series["spy_div_adjusted_proxy"]
    assert rejected_a["status"] == "rejected"
    assert rejected_a["option"] == "A"


def test_redistribution_policy(manifest: dict[str, Any]) -> None:
    for source_id, cfg in manifest["sources"].items():
        redist = cfg["redistribution"]
        assert redist in {"fetch_script", "bundle_ok", "n_a"}
        if source_id in {"fred_sp500", "shiller_ie_data", "ken_french_daily", "tiingo_eod", "tiingo_visa"}:
            assert redist == "fetch_script"
        if source_id == "visa_dividends_sec":
            assert redist == "bundle_ok"


def test_parse_fred_csv_handles_dots() -> None:
    csv_text = "observation_date,SP500\n2022-01-03,4796.56\n2022-01-04,.\n2022-01-05,4700.58\n"
    meta = parse_fred_csv(csv_text.encode("utf-8"))
    assert meta["row_count"] == 3
    assert meta["missing_value_count"] == 1
    assert meta["first_date"] == "2022-01-03"
    assert meta["last_date"] == "2022-01-05"
    assert meta["columns"] == ["observation_date", "SP500"]


def test_parse_ken_french_zip_synthetic() -> None:
    csv_body = (
        b"This file was created by XYZ\n"
        b"\n"
        b",Mkt-RF,SMB,HML,RF\n"
        b"20220103,1.23,0.10,-0.20,0.00\n"
        b"20220104,-0.50,0.05,0.01,0.00\n"
        b"\n"
        b"Copyright 2026\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("F-F_Research_Data_Factors_daily.CSV", csv_body)
    meta = parse_ken_french_zip(buf.getvalue())
    assert meta["row_count"] == 2
    assert meta["first_date"] == "2022-01-03"
    assert meta["last_date"] == "2022-01-04"
    assert "Mkt-RF" in meta["columns"]


def test_parse_shiller_yyyymm_helper() -> None:
    from longaeva_app.collect.benchmark_sources import _shiller_date_to_month

    assert _shiller_date_to_month(1871.01) == "1871-01"
    assert _shiller_date_to_month(2024.12) == "2024-12"
    assert _shiller_date_to_month(2026.09) == "2026-09"
    assert _shiller_date_to_month("2022.01") == "2022-01"
    assert _shiller_date_to_month(99.5) is None


def test_coverage_ok_month_and_day() -> None:
    window = {"window_start": "2022-01-27", "window_end": "2026-07-28"}
    assert coverage_ok({"first_date": "1871-01", "last_date": "2026-09"}, window)
    assert coverage_ok({"first_date": "2016-10-03", "last_date": "2026-10-01"}, window)
    assert not coverage_ok({"first_date": "2023-01-01", "last_date": "2026-10-01"}, window)
    assert not coverage_ok({"first_date": "2016-10-03", "last_date": "2025-01-01"}, window)


def test_ex_dividend_convention() -> None:
    # Before T+1 cutoff: one business day before record.
    assert ex_dividend_date("2024-05-17") == "2024-05-16"
    # On/after 2024-05-28: ex-date = record date.
    assert ex_dividend_date("2024-08-09") == "2024-08-09"
    assert ex_dividend_date("2025-11-12") == "2025-11-12"


def test_visa_dividend_parser_on_synthetic_text() -> None:
    text = (
        "On April 23, 2024, the board of directors declared a quarterly cash dividend "
        "of $0.520 per share of class A common stock payable on June 3, 2024, "
        "to all holders of record as of May 17, 2024."
    )
    parsed = parse_visa_dividend_text(text)
    assert parsed is not None
    assert parsed["amount_per_share"] == 0.52
    assert parsed["payable_date"] == "2024-06-03"
    assert parsed["record_date"] == "2024-05-17"


def test_visa_dividends_from_retained_releases() -> None:
    dividends = parse_retained_visa_dividends()
    assert len(dividends) == 4
    assert all(d["status"] == "ok" for d in dividends)
    amounts = {d["amount_per_share"] for d in dividends}
    assert 0.52 in amounts
    assert 0.67 in amounts


def test_html_to_text_strips_tags() -> None:
    raw = b"<html><body>declared a quarterly cash dividend of $0.520</body></html>"
    assert "quarterly cash dividend of $0.520" in html_to_text(raw)


def test_probe_json_consistency(manifest: dict[str, Any], probe: dict[str, Any]) -> None:
    assert probe["generated_for"] == "LON-6"
    assert probe["decision"]["primary_option"] == "B"
    assert probe["labels"]["primary"] == manifest["labels"]["primary"]

    probed_ids = {s["source_id"] for s in probe["sources"]}
    expected = {sid for sid, cfg in manifest["sources"].items() if cfg.get("probe") is True}
    assert probed_ids == expected

    for entry in probe["sources"]:
        assert entry["status"] == "ok"
        assert entry["covers_candidate_window"] is True
        assert "content_sha256" in entry
        assert len(entry["content_sha256"]) == 64
        # No price arrays leaked into the probe artifact.
        assert "prices" not in entry
        assert "values" not in entry
        assert "rows" not in entry

    assert len(probe["visa_dividends"]) == 4
    assert all(d["status"] == "ok" for d in probe["visa_dividends"])


def test_benchmarks_fixture_dir_metadata_only() -> None:
    assert PROBE_DIR.is_dir()
    files = sorted(p.name for p in PROBE_DIR.iterdir() if p.is_file())
    assert files == ["probe.json"]
    # Guard against accidental raw vendor dumps elsewhere under fixtures/benchmarks.
    for path in PROBE_DIR.rglob("*"):
        if path.is_file():
            assert path.name == "probe.json"
            assert path.suffix == ".json"


def test_no_users_paths_in_gate_artifacts() -> None:
    for path in (MANIFEST_PATH, PROBE_PATH, PACKAGE_ROOT / "docs" / "gates" / "benchmarks.md"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert "/Users/" not in text


def test_parse_shiller_xls_rejects_garbage() -> None:
    with pytest.raises((OSError, ValueError, xlrd.XLRDError)):
        parse_shiller_xls(b"not-an-xls")
