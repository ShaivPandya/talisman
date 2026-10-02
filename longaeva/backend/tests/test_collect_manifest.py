"""Manifest loader and builder tests (LON-13)."""

from __future__ import annotations

from pathlib import Path

import yaml

from longaeva_app.collect.manifest import MANIFEST_DIR, build_manifests, load_manifests

PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def test_all_manifests_load_with_unique_keys() -> None:
    entries = load_manifests()
    keys = [e.key for e in entries]
    assert len(keys) == len(set(keys))
    assert len(entries) > 100
    assert any(e.availability != "available" for e in entries)


def test_visa_coverage_spans_fy2017q1_to_fy2026q3() -> None:
    entries = load_manifests(names=["visa.yaml"])
    releases = [e for e in entries if e.key.startswith("visa:release:")]
    assert releases[0].key == "visa:release:FY2017Q1"
    assert releases[-1].key == "visa:release:FY2026Q3"
    assert len(releases) == 39


def test_committed_yaml_equals_regeneration(tmp_path: Path) -> None:
    built = build_manifests(manifest_dir=tmp_path, write=True)
    for name in ("visa.yaml", "booking.yaml", "census.yaml"):
        committed = yaml.safe_load((MANIFEST_DIR / name).read_text(encoding="utf-8"))
        fresh = yaml.safe_load((tmp_path / name).read_text(encoding="utf-8"))
        assert committed["documents"] == fresh["documents"], name
        assert len(built[name]) == len(committed["documents"])


def test_visa_ir_and_second_wave_adapters() -> None:
    ir = load_manifests(names=["visa_ir.yaml"])
    assert any(e.key == "visa_ir:quarterly_html" and e.availability != "available" for e in ir)
    assert any(e.doc_type == "ir_deck" for e in ir)
    sw = load_manifests(names=["second_wave.yaml"])
    assert len(sw) == 10
    assert all(e.company in {"united", "costco", "paypal"} for e in sw)
