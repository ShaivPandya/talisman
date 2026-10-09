"""Publication gating, frozen registration, recovery and offline replay."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.companies.visa.calibration import CalibrationResult, artifact_path
from longaeva_app.db.models import Forecast, Run
from longaeva_app.evaluation.harness import load_calibration_artifact
from longaeva_app.hashing import content_hash
from longaeva_app.runs import registration
from longaeva_app.runs.prospective import (
    CUTOFF,
    PUBLICATION_URL,
    REGISTRATION_FILE,
    PublicationCheck,
    load_registration,
    replay_registration,
)
from longaeva_app.storage.local import LocalArtifactStore


def _check() -> PublicationCheck:
    return PublicationCheck(
        source_url=PUBLICATION_URL,
        checked_at=datetime.now(UTC),
        method="rendered_official_quarterly_table",
        release_links=[
            f"https://s1.q4cdn.com/050606653/files/doc_financials/2026/q{q}/Q{q}-2026-Earnings-Release_vF.pdf"
            for q in (1, 2, 3)
        ],
    )


def _calibration(*_args: Any, **_kwargs: Any) -> CalibrationResult:
    # Reuse the retained calibration fixture to test persistence without fitting.
    result = load_calibration_artifact(artifact_path("2024-07-23"))
    return replace(
        result,
        origin_date="2026-07-28",
        origin_label="FY2026Q3",
        cutoff_ts=CUTOFF,
        pooled=result.pooled.model_copy(update={"cutoff_ts": CUTOFF}),
    )


def test_publication_check_fails_closed() -> None:
    check = _check()
    check.assert_unpublished(datetime.now(UTC))
    with pytest.raises(ValueError, match="past hour"):
        check.assert_unpublished(check.checked_at + timedelta(hours=2))
    with pytest.raises(ValueError, match="past hour"):
        check.assert_unpublished(check.checked_at - timedelta(seconds=1))
    check.release_links.pop()
    with pytest.raises(ValueError, match="Cannot establish"):
        check.assert_unpublished(datetime.now(UTC))
    check = _check()
    check.release_links.append(
        "https://s1.q4cdn.com/050606653/files/doc_financials/2026/q4/Q4-2026-Earnings-Release.pdf"
    )
    with pytest.raises(ValueError, match="already published"):
        check.assert_unpublished(datetime.now(UTC))
    check = _check()
    check.release_links[0] = "https://example.invalid/2026/q1/release.pdf"
    with pytest.raises(ValueError, match="non-Visa"):
        check.assert_unpublished(datetime.now(UTC))


@pytest.mark.db
def test_register_once_recover_export_and_replay_offline(
    db_session: Session,
    artifact_store: LocalArtifactStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "")
    monkeypatch.setattr(registration, "calibrate", _calibration)
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    destination = tmp_path / "registration"
    with pytest.raises(ValueError, match="fresh --publication-check"):
        registration.register_prospective(factory, artifact_store, destination, None, n_paths=32)
    bundle = registration.register_prospective(factory, artifact_store, destination, _check(), n_paths=32)
    assert len(bundle.forecasts) == 20
    assert bundle.registered_at > CUTOFF
    assert bundle.replay["recorded_outputs_hash"] == bundle.replay["recomputed_outputs_hash"]
    before = (destination / REGISTRATION_FILE).read_bytes()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Forecast)) == 20
        assert session.scalar(select(func.count()).select_from(Run)) == 1
        forecast = session.scalars(select(Forecast)).first()
        assert forecast is not None
        with pytest.raises(Exception, match="immutable"):
            session.execute(text("UPDATE forecast SET metric = 'changed' WHERE id = :id"), {"id": forecast.id})
            session.commit()
        session.rollback()
    repeated = registration.register_prospective(factory, artifact_store, destination, None, n_paths=32)
    assert repeated.content_hash == bundle.content_hash
    assert (destination / REGISTRATION_FILE).read_bytes() == before
    # A lost final export can be recovered from the same archived run/checkpoint.
    recovered = registration.register_prospective(factory, artifact_store, tmp_path / "recovered", None, n_paths=32)
    assert recovered.model_dump() == bundle.model_dump()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Run)) == 1
        assert session.scalar(select(func.count()).select_from(Forecast)) == 20
    report = replay_registration(destination / REGISTRATION_FILE)
    assert report["status"] == "exact_match"
    assert not report["llm_provider"]
    paths = destination / bundle.paths_file
    paths.write_bytes(paths.read_bytes() + b"corrupted")
    with pytest.raises(ValueError, match="path-file hash"):
        load_registration(destination / REGISTRATION_FILE)


@pytest.mark.db
def test_late_calibration_evidence_never_creates_run(
    db_session: Session,
    artifact_store: LocalArtifactStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _calibration()
    result.evidence_index["poison"] = {"publication_ts": "2026-07-29T00:00:00Z"}
    monkeypatch.setattr(registration, "calibrate", lambda *_a, **_kw: result)
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    with pytest.raises(ValueError, match="leakage"):
        registration.register_prospective(factory, artifact_store, tmp_path, _check(), n_paths=32)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Run)) == 0
        assert session.scalar(select(func.count()).select_from(Forecast)) == 0


def test_packaged_hashes_and_replay(tmp_path: Path) -> None:
    package = Path(__file__).resolve().parents[2]
    source = package / "data/demo/forecasts"
    shutil.copytree(source, tmp_path / "bundle")
    path = tmp_path / "bundle" / REGISTRATION_FILE
    original = json.loads(path.read_text())
    assert load_registration(path).run["n_paths"] == 5000
    assert replay_registration(path)["status"] in {"exact_match", "numerically_equivalent"}
    original["run"]["starting_state"]["net_revenue"] = -1
    path.write_text(json.dumps(original))
    with pytest.raises(ValueError, match="content hash"):
        load_registration(path)
    original["content_hash"] = content_hash({k: v for k, v in original.items() if k != "content_hash"})
    path.write_text(json.dumps(original))
    with pytest.raises(ValueError, match="Starting-state hash"):
        load_registration(path)
