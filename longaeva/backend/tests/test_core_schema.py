"""Core schema constraint and behavior tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from longaeva_app.db.models import DocumentText, Forecast, ParameterSet, Run, Scenario, Source, SourceRetrieval


def _source(**overrides: object) -> Source:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "provider": "sec",
        "company": "visa",
        "doc_type": "8-K",
        "url": "https://example.test/doc",
        "publication_ts": now - timedelta(hours=1),
        "retrieval_ts": now,
        "content_hash": f"hash-{uuid4().hex}",
        "original_path": f"originals/ab/{uuid4().hex}",
    }
    defaults.update(overrides)
    return Source(**defaults)


@pytest.mark.db
def test_publication_ts_must_precede_retrieval_ts(db_session: Session) -> None:
    now = datetime.now(UTC)
    source = _source(publication_ts=now, retrieval_ts=now)
    db_session.add(source)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.db
def test_reingest_same_hash_one_source_two_retrievals(db_session: Session) -> None:
    content_hash = f"hash-{uuid4().hex}"
    source = _source(content_hash=content_hash)
    db_session.add(source)
    db_session.flush()

    first = SourceRetrieval(
        source_id=source.id,
        retrieved_at=source.retrieval_ts,
        url=source.url,
        http_status=200,
    )
    second = SourceRetrieval(
        source_id=source.id,
        retrieved_at=source.retrieval_ts + timedelta(minutes=5),
        url=source.url,
        http_status=200,
        notes="re-fetch",
    )
    db_session.add_all([first, second])
    db_session.commit()

    count = db_session.scalar(
        text("SELECT count(*) FROM source WHERE content_hash = :h"),
        {"h": content_hash},
    )
    retrievals = db_session.scalar(
        text("SELECT count(*) FROM source_retrieval WHERE source_id = :id"),
        {"id": source.id},
    )
    assert count == 1
    assert retrievals == 2

    dup = _source(content_hash=content_hash)
    db_session.add(dup)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.db
def test_document_text_full_text_search(db_session: Session) -> None:
    source = _source()
    db_session.add(source)
    db_session.flush()
    passage = DocumentText(
        source_id=source.id,
        page=1,
        char_start=0,
        char_end=40,
        text="Cross-border volume excluding intra-Europe grew.",
    )
    db_session.add(passage)
    db_session.commit()

    hit = db_session.execute(
        text(
            """
            SELECT id FROM document_text
            WHERE tsv @@ plainto_tsquery('english', 'cross-border')
            """
        )
    ).scalar()
    assert hit == passage.id


@pytest.mark.db
def test_forecast_update_and_delete_rejected(db_session: Session) -> None:
    now = datetime.now(UTC)
    param_set = ParameterSet(
        company="visa",
        cutoff_ts=now,
        values={"yield": 0.01},
        ranges={},
        evidence_links={"yield": {"assumption": True, "rationale": "stub"}},
        assumption_flags={"yield": True},
        content_hash=f"ps-{uuid4().hex}",
    )
    db_session.add(param_set)
    db_session.flush()
    scenario = Scenario(
        company="visa",
        name="baseline",
        parameter_set_id=param_set.id,
        interventions=[],
    )
    db_session.add(scenario)
    db_session.flush()
    run = Run(
        scenario_id=scenario.id,
        cutoff_ts=now,
        source_manifest=[],
        source_manifest_hash=f"sm-{uuid4().hex}",
        parameter_set_hash=param_set.content_hash,
        code_version="0.1.0",
        seed=1,
        n_paths=10,
        switches={},
        lib_versions={},
        status="succeeded",
        outputs_path="runs/fixture/paths.npz",
        outputs_hash="a" * 64,
        summary=[{"metric": "net_revenue", "quarter_index": 0, "period_label": "FY2024Q4", "mean": 1.0}],
    )
    db_session.add(run)
    db_session.flush()
    forecast = Forecast(
        run_id=run.id,
        origin_ts=now,
        cutoff_ts=now,
        target_period_start=now.date(),
        target_period_end=now.date(),
        metric="net_revenue",
        quantiles={"0.5": 1.0},
        kind="retrospective",
    )
    db_session.add(forecast)
    db_session.commit()
    forecast_id = forecast.id

    with pytest.raises(Exception) as update_exc:
        db_session.execute(
            text("UPDATE forecast SET metric = 'other' WHERE id = :id"),
            {"id": forecast_id},
        )
        db_session.commit()
    db_session.rollback()
    assert "immutable" in str(update_exc.value).lower()

    with pytest.raises(Exception) as delete_exc:
        db_session.execute(text("DELETE FROM forecast WHERE id = :id"), {"id": forecast_id})
        db_session.commit()
    db_session.rollback()
    assert "immutable" in str(delete_exc.value).lower()

    # ORM path
    row = db_session.get(Forecast, forecast_id)
    assert row is not None
    row.metric = "changed"
    with pytest.raises((Exception, StaleDataError)):
        db_session.commit()
    db_session.rollback()
