"""Failure-path coverage for final-export acceptance checks."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path
from typing import Any

import pytest

from longaeva_app.isolation_guard import resolve_root
from longaeva_app.submission import VerificationError, check_evidence, check_replay, validate_inventory


def test_final_refuses_skipped_tests_before_docker() -> None:
    result = subprocess.run(
        ["bash", str(resolve_root() / "scripts/verify_export.sh"), "--final", "--skip-tests"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--final cannot be combined with --skip-tests" in result.stderr


@pytest.mark.parametrize(
    "state", [{}, {"evidence": {}}, {"evidence": {"revenue": {"unavailable_reason": "missing source"}}}]
)
def test_missing_demo_evidence_fails(state: dict[str, Any]) -> None:
    with pytest.raises(VerificationError, match="evidence"):
        check_evidence(state)


def test_replay_cannot_claim_exact_when_hashes_differ() -> None:
    with pytest.raises(VerificationError, match="hashes differ"):
        check_replay(
            {"status": "exact_match", "llm_provider": "", "recorded_outputs_hash": "a", "recomputed_outputs_hash": "b"},
            bundled=True,
        )


def test_new_runs_require_exact_replay() -> None:
    report = {"status": "numerically_equivalent", "llm_provider": "", "max_relative_difference": 1e-12}
    check_replay(report, bundled=True)
    with pytest.raises(VerificationError, match="tolerance"):
        check_replay(report, bundled=False)
    report["max_relative_difference"] = 1e-6
    with pytest.raises(VerificationError, match="tolerance"):
        check_replay(report, bundled=True)


def test_license_inventory_rejects_missing_and_changed_files(tmp_path: Path) -> None:
    (tmp_path / ".exportignore").write_text(".git/\n")
    (tmp_path / "data").mkdir()
    (tmp_path / "docs").mkdir()
    fixture = tmp_path / "data/fixture.json"
    fixture.write_text("{}")
    with (tmp_path / "docs/data-license-inventory.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "sha256", "authorship", "retention_decision", "terms_or_provenance"])
        writer.writerow(["data/fixture.json", hashlib.sha256(b"{}").hexdigest(), "project", "derived", "source"])
    assert validate_inventory(tmp_path) == 1
    fixture.write_text("changed")
    with pytest.raises(VerificationError, match="checksum"):
        validate_inventory(tmp_path)
    fixture.unlink()
    with pytest.raises(VerificationError, match="coverage"):
        validate_inventory(tmp_path)
