"""Forecast capture, leakage/integrity guards and quantile scoring (LON-30)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from longaeva_app.config import Settings
from longaeva_app.evaluation.baselines.llm_docs import (
    ForecastResponse,
    capture_forecasts,
    load_packs,
    run_llm_docs,
    user_message,
    validate_response,
)
from longaeva_app.evaluation.harness import report_to_dict
from longaeva_app.evaluation.llm_inputs import SELECTION_POLICY, _verified, html_excerpts, validate_pack
from longaeva_app.evaluation.metrics import aggregate_scores, score_quantiles, score_samples
from longaeva_app.evaluation.origins import EvaluationOrigin, load_evaluation_origins
from longaeva_app.extract.providers import ProviderError, ProviderResult, StubProvider, build_provider
from longaeva_app.hashing import content_hash, sha256_hex, utc_isoformat
from longaeva_app.runs.inputs import resolve_fixture


def origin() -> EvaluationOrigin:
    return next(o for o in load_evaluation_origins() if o.origin_date == "2024-07-23")


def pack_for(o: EvaluationOrigin) -> dict[str, Any]:
    text = "Historical revenue and payments volume."
    pack = {
        "origin_date": o.origin_date,
        "origin_period": o.origin.label(),
        "target_period": o.target.label(),
        "cutoff_ts": utc_isoformat(o.cutoff_ts),
        "selection_policy": SELECTION_POLICY,
        "documents": [
            {
                "document_key": "test",
                "publication_ts": utc_isoformat(o.cutoff_ts),
                "content_sha256": sha256_hex(text),
                "url": "https://example.test/source",
                "excerpts": [{"text": text, "text_sha256": sha256_hex(text), "char_start": 0, "char_end": len(text)}],
            }
        ],
    }
    pack["pack_hash"] = content_hash(pack)
    return pack


def response_for(o: EvaluationOrigin) -> dict[str, Any]:
    from longaeva_app.evaluation.baselines.llm_docs import TARGETS

    return {
        "target_period": o.target.label(),
        "forecasts": {
            name: {
                "quantiles": {"q05": 0.0, "q10": 1.0, "q25": 2.0, "q50": 3.0, "q75": 4.0, "q90": 5.0, "q95": 6.0},
                "unavailable_reason": None,
            }
            for name in TARGETS
        },
    }


def settings(**kwargs: Any) -> Settings:
    return Settings(**{"_env_file": None, **kwargs})


def test_response_requires_all_targets_ordered_finite_quantiles_and_exact_horizon() -> None:
    o = origin()
    valid = response_for(o)
    assert validate_response(valid, o.target.label()).target_period == "FY2024Q4"
    for field, value in [("q50", -1.0), ("q95", float("nan")), ("q05", "0")]:
        invalid = copy.deepcopy(valid)
        invalid["forecasts"]["net_revenue"]["quantiles"][field] = value
        with pytest.raises(ValueError):
            validate_response(invalid, o.target.label())
    invalid = copy.deepcopy(valid)
    invalid["forecasts"].pop("net_revenue")
    with pytest.raises(ValueError):
        validate_response(invalid, o.target.label())
    with pytest.raises(ValueError, match="horizon"):
        validate_response(valid, "FY2025Q1")
    valid["forecasts"]["net_revenue"] = {"quantiles": None, "unavailable_reason": "No comparable evidence"}
    assert validate_response(valid, o.target.label()).forecasts.net_revenue.quantiles is None
    valid["forecasts"]["net_revenue"]["unavailable_reason"] = " "
    with pytest.raises(ValueError):
        validate_response(valid, o.target.label())


def test_source_hash_and_cutoff_guard(tmp_path: Path) -> None:
    source = tmp_path / "source.html"
    source.write_text("retained original")
    assert _verified(source, sha256_hex(source.read_bytes())) == source.read_bytes()
    with pytest.raises(ValueError, match="hash mismatch"):
        _verified(source, "wrong")
    o = origin()
    pack = pack_for(o)
    validate_pack(pack, o)  # Publication exactly at cutoff is eligible.
    pack["documents"][0]["publication_ts"] = "2024-07-23T20:05:39Z"
    pack["pack_hash"] = content_hash({k: v for k, v in pack.items() if k != "pack_hash"})
    with pytest.raises(ValueError, match="after cutoff"):
        validate_pack(pack, o)
    pack = pack_for(o)
    pack["documents"][0]["excerpts"][0]["text"] = "altered"
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_pack(pack, o)


def test_partial_failure_and_response_integrity_do_not_inflate_scored_count(tmp_path: Path) -> None:
    origins = [o for o in load_evaluation_origins() if o.scored][:2]
    packs = {o.origin_date: pack_for(o) for o in origins}
    provider = StubProvider([json.dumps(response_for(origins[0])), "invalid JSON"])
    cache = tmp_path / "cached.json"
    capture_forecasts(
        origins, packs, provider=provider, provider_name="stub", model=provider.model, settings=settings(), output=cache
    )
    for o in origins:
        (tmp_path / f"{o.origin_date}.json").write_text(json.dumps(packs[o.origin_date]))
    report = run_llm_docs(origin_dates=[o.origin_date for o in origins], cache_path=cache, input_dir=tmp_path)
    assert report.n_scored == 1
    assert report.origins[1].error is not None and "invalid_response" in report.origins[1].error
    assert report.aggregates["overall"]["net_revenue"]["n"] == 1
    changed = json.loads(cache.read_text())
    changed["calls"][0]["parsed"]["forecasts"]["net_revenue"]["quantiles"]["q50"] = 3.5
    cache.write_text(json.dumps(changed))
    report = run_llm_docs(origin_dates=[o.origin_date for o in origins], cache_path=cache, input_dir=tmp_path)
    assert report.n_scored == 0
    assert "integrity mismatch" in (report.origins[0].error or "")


def test_table_excerpt_retains_headers_and_deduplicates_rows() -> None:
    raw = b"<p>Quarterly USD millions</p><table><tr><th>Metric</th><th>2024</th></tr><tr><td>Revenue</td><td>100</td></tr><tr><td>Profit</td><td>60</td></tr><tr><td>Unused</td><td>9</td></tr></table>"
    start = raw.index(b"100")
    once = html_excerpts(raw, [(start, start + 3)])
    assert once == html_excerpts(raw, [(start, start + 3), (start, start + 3)])
    assert "Metric | 2024" in once[0]["text"]
    assert "Revenue | 100" in once[0]["text"]
    assert "Unused" not in once[0]["text"]
    assert once[0]["text_sha256"] == sha256_hex(once[0]["text"])


def test_bundled_packs_match_state_sources_and_exclude_future_outcomes() -> None:
    from longaeva_app.companies.visa.calibration import load_observation_rows

    origins = [o for o in load_evaluation_origins() if o.scored]
    packs = load_packs(origins)
    history = load_observation_rows()
    assert len(packs) == 16
    for o in origins:
        pack = packs[o.origin_date]
        documents = {d["document_key"]: d for d in pack["documents"]}
        for source in resolve_fixture(o.cutoff_ts).sources.values():
            if source.role == "input":
                assert documents[source.source_id]["content_sha256"] == source.content_sha256
        eligible = {(r.source_id, r.period_label, r.field) for r in history if r.publication_ts <= o.cutoff_ts}
        assert all((r["source_id"], r["period"], r["field"]) in eligible for r in pack["historical_observations"])
        # The prompt payload is evidence only; scoring and model outputs stay outside it.
        assert set(pack) == {
            "selection_policy",
            "origin_date",
            "cutoff_ts",
            "origin_period",
            "target_period",
            "documents",
            "historical_observations",
            "external_observations",
            "pack_hash",
        }
        prompt = user_message(pack)
        assert '"future_actuals"' not in prompt and '"model_predictions"' not in prompt


def test_quantile_scores_match_existing_samples_without_invented_crps() -> None:
    samples = list(range(101))
    existing = score_samples(samples, 103.0)
    scores = score_quantiles(existing.quantiles, 103.0)
    assert scores["abs_error"] == existing.abs_error
    assert scores["signed_error"] == existing.signed_error
    assert scores["pct_error"] == existing.pct_error
    assert scores["covered_80"] == float(existing.covered_80)
    assert scores["wis"] == existing.wis
    assert "crps" not in scores and "mean" not in scores
    aggregate = aggregate_scores([scores])
    assert aggregate.n == 1 and aggregate.mean_crps is None and aggregate.mean_wis == existing.wis
    assert score_quantiles(existing.quantiles, 0.0)["pct_error"] is None
    assert score_quantiles(existing.quantiles, 10.0, percentage_error=False)["pct_error"] is None


def test_capture_resumes_success_and_failure_and_rejects_changed_inputs(tmp_path: Path) -> None:
    o = origin()
    pack = pack_for(o)
    provider = StubProvider([json.dumps(response_for(o))])
    output = tmp_path / "cached.json"
    kwargs: dict[str, Any] = dict(
        provider=provider, provider_name="stub", model=provider.model, settings=settings(), output=output
    )
    result = capture_forecasts([o], {o.origin_date: pack}, **kwargs)
    assert result["calls"][0]["status"] == "succeeded" and provider.calls == 1
    capture_forecasts([o], {o.origin_date: pack}, **kwargs)
    assert provider.calls == 1
    changed = pack_for(o)
    changed["documents"][0]["url"] = "https://example.test/different"
    changed["pack_hash"] = content_hash({k: v for k, v in changed.items() if k != "pack_hash"})
    with pytest.raises(ValueError, match="mismatch"):
        capture_forecasts([o], {o.origin_date: changed}, **kwargs)
    failed = StubProvider(['{"forecasts": {}}'])
    failed_kwargs = {**kwargs, "provider": failed, "output": tmp_path / "failed.json"}
    assert capture_forecasts([o], {o.origin_date: pack}, **failed_kwargs)["calls"][0]["status"] == "invalid_response"
    capture_forecasts([o], {o.origin_date: pack}, **failed_kwargs)
    assert failed.calls == 1


def test_disabled_capture_and_offline_scoring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    o = origin()
    pack = pack_for(o)
    cache = tmp_path / "cached.json"
    result = capture_forecasts(
        [o],
        {o.origin_date: pack},
        provider=None,
        provider_name="openai",
        model="gpt-5.4",
        settings=settings(),
        output=cache,
    )
    assert result["calls"] == []
    report = run_llm_docs(origin_dates=[o.origin_date], cache_path=cache, input_dir=tmp_path)
    assert report.n_scored == 0 and report.origins[0].error == "not run (no provider capture)"
    provider = StubProvider([json.dumps(response_for(o))])
    cache.unlink()
    capture_forecasts(
        [o],
        {o.origin_date: pack},
        provider=provider,
        provider_name="stub",
        model=provider.model,
        settings=settings(),
        output=cache,
    )
    (tmp_path / f"{o.origin_date}.json").write_text(json.dumps(pack))

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Offline scoring must not construct a provider")

    monkeypatch.setattr("longaeva_app.extract.providers.build_provider", forbidden)
    first = run_llm_docs(origin_dates=[o.origin_date], cache_path=cache, input_dir=tmp_path)
    second = run_llm_docs(origin_dates=[o.origin_date], cache_path=cache, input_dir=tmp_path)
    assert report_to_dict(first) == report_to_dict(second)
    assert first.n_scored == 1
    assert first.aggregates["overall"]["net_revenue"]["mean_crps"] is None
    assert first.four_quarter["net_revenue_sum"]["n"] == 0
    assert provider.calls == 1


@pytest.mark.parametrize("status", ["refused", "incomplete", "provider_error"])
def test_provider_failures_are_checkpointed(status: str, tmp_path: Path) -> None:
    class FailedProvider(StubProvider):
        def complete(self, *, system: str, user: str) -> ProviderResult:
            self.calls += 1
            if status == "provider_error":
                raise ProviderError("bounded transport failure", attempts=2)
            return ProviderResult(
                "",
                None,
                None,
                None,
                1,
                refusal="Refused" if status == "refused" else None,
                incomplete=status == "incomplete",
            )

    o = origin()
    provider = FailedProvider()
    kwargs: dict[str, Any] = dict(
        provider=provider,
        provider_name="stub",
        model=provider.model,
        settings=settings(),
        output=tmp_path / "cached.json",
    )
    assert capture_forecasts([o], {o.origin_date: pack_for(o)}, **kwargs)["calls"][0]["status"] == status
    capture_forecasts([o], {o.origin_date: pack_for(o)}, **kwargs)
    assert provider.calls == 1


@pytest.mark.parametrize("name", ["openai", "anthropic", "gemini"])
def test_provider_schema_is_forecast_specific_and_transport_retry_is_bounded(name: str) -> None:
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(503, text="retryable failure")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = build_provider(
        settings(openai_api_key="test-key", anthropic_api_key="test-key", gemini_api_key="test-key"),
        provider=name,
        model="test-model",
        client=client,
        response_schema=ForecastResponse.model_json_schema(),
        schema_name="visa_forecast",
    )
    assert provider is not None
    with pytest.raises(ProviderError) as caught:
        provider.complete(system="rules", user="evidence")
    assert caught.value.attempts == 2 and len(bodies) == 2
    schema = (
        bodies[0]["text"]["format"]["schema"]
        if name == "openai"
        else bodies[0]["tools"][0]["input_schema"]
        if name == "anthropic"
        else bodies[0]["generationConfig"]["responseSchema"]
    )
    assert "forecasts" in schema["properties"] and "observations" not in schema["properties"]
    assert "$ref" not in json.dumps(schema)
    assert "q50" in json.dumps(schema)
    client.close()
