"""End-to-end idea scan runs over a fixed factor frame, with stubbed LLM, EDGAR and Scout writes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import llm_utils
from api.idea_scan import pipeline, store
from api.idea_scan.presets import get_idea_scan_settings, set_idea_scan_settings
from tests.test_idea_scan_llm_steps import FILINGS, SNAPSHOTS, _row, _usage
from tests.test_idea_scan_screening import make_frame


def scan_frame():
    rows = {f"F{i:02d}": {"quality": float(i), "price_momentum": float(i), "sector": "Utilities"} for i in range(20)}
    # Two names hit two presets each, two more hit one.
    rows["F19"].update(
        {"price_to_book": 1.0, "rev_yoy_avg": 10.0, "eps_yoy_avg": 10.0, "net_issuance": -1.0, "sector": "Technology"}
    )
    rows["F18"].update({"sector": "Technology"})
    rows["F17"].update({"sector": "Energy"})
    rows["F00"].update({"price_to_book": 8.0, "operating_income": -1.0, "rev_yoy_avg": -3.0, "sector": "Energy"})
    rows["F01"].update({"sector": "Energy"})
    return make_frame(rows)


def empty_frame():
    # Mid-ranked names everywhere: nothing reaches a decile, P/B 2.0 misses both screens.
    return make_frame({f"F{i:02d}": {"quality": 1.0, "price_momentum": 1.0} for i in range(20)})


class FakeWriteback:
    records: list[dict] = []

    def record_opportunity_candidate(self, *, record, actor, provenance_id, valid_from=None, approval_id=None):
        type(self).records.append(dict(record))
        return [
            {"object_type": "OpportunityCandidate", "object_uid": f"opportunity_candidate:{record['candidate_id']}"}
        ]


NEWS = {
    "window_days": 7,
    "digests": [{"id": "2026-10-26-digest", "title": "Digest", "generated_date": "2026-10-26"}],
    "stories": [
        {
            "ref": "2026-10-26-digest/story-1",
            "date": "2026-10-26",
            "section": "AI credit",
            "headline": "Neocloud bonds yield over 15%",
            "takeaway": "",
            "top_rank": None,
            "multi_signal": True,
            "confidence": 0.9,
        }
    ],
}


def macro_call(**_kwargs):
    llm_utils._notify_response_observer("anthropic", "claude-opus-5-5", _usage(30_000, 4_000, searches=3))
    rows = [_row("Technology", 2, confidence="high"), _row("Energy", -2, confidence="high")]
    return {"summary": "Tech strong, energy weak.", "rows": rows}, [], None, {"status": "ok"}


def review_call(cost_tokens=10_000):
    def call(**kwargs):
        llm_utils._notify_response_observer("anthropic", "claude-sonnet-5-5", _usage(cost_tokens, 1_000, searches=2))
        return (
            {
                "trigger": "Screen hit.",
                "why_now": "Estimates moved.",
                "consensus": "c",
                "variant_view": "v",
                "headlines": [{"title": "A", "url": "https://news.example.com/a", "date": "2026-10-20"}],
                "macro_fit": "fits",
                "missing_inputs": ["Margins"],
                "next_action": "research",
            },
            [("A", "https://news.example.com/a")],
            None,
            {"status": "ok"},
        )

    return call


def digest_call(**_kwargs):
    llm_utils._notify_response_observer("anthropic", "claude-sonnet-5-5", _usage(3_000, 300))
    return "This week leans toward quality tech.", [], None


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOCAL_ROOT", tmp_path / "runs")
    state = SimpleNamespace(frame=scan_frame(), fetches=0, tracked={}, existing={}, fail_fetch=False)

    def fake_fetch(membership, progress=None, **_kwargs):
        state.fetches += 1
        if state.fail_fetch:
            raise RuntimeError("yahoo down")
        if progress:
            progress("fundamentals", len(membership), len(membership))
        return SimpleNamespace(
            key="2026-W44-test", fetched_at="2026-10-24T12:00:00+00:00", reused_chunks=0, failed={"BAD": "x"}
        )

    monkeypatch.setattr(
        pipeline, "resolve_membership", lambda universes, tickers=None: {t: ["sp500"] for t in state.frame.index}
    )
    monkeypatch.setattr(pipeline, "fetch_dataset", fake_fetch)
    monkeypatch.setattr(pipeline, "build_factor_frame", lambda _dataset: state.frame)
    monkeypatch.setattr(pipeline, "fetch_eps_revisions", lambda tickers: {t: -0.05 for t in tickers})
    monkeypatch.setattr(pipeline, "tracked_tickers", lambda: dict(state.tracked))
    monkeypatch.setattr(pipeline, "_existing_scout_status", lambda cid: state.existing.get(cid))
    monkeypatch.setattr("api.idea_scan.review.recent_filings", lambda _t, now=None: FILINGS)
    monkeypatch.setattr("api.idea_scan.macro_view.gather_snapshots", lambda read=None: SNAPSHOTS)
    monkeypatch.setattr(pipeline, "gather_digest_stories", lambda days: NEWS)
    monkeypatch.setattr("decision_quality.opportunity_scout.DecisionOntologyWriteback", FakeWriteback)
    FakeWriteback.records = []
    return state


def run(**request):
    return pipeline.run_weekly_idea_scan(
        {"source": "scheduler", **request}, review_call=review_call(), macro_call=macro_call, digest_call=digest_call
    )


def test_scheduled_run_publishes_a_digest(env):
    progress = []
    out = pipeline.run_weekly_idea_scan(
        {"source": "scheduler"},
        progress_callback=lambda *args: progress.append(args),
        review_call=review_call(),
        macro_call=macro_call,
        digest_call=digest_call,
    )
    saved = store.get_run(out["run_id"])
    assert saved["status"] == "completed" and saved["source"] == "scheduler" and not saved["limited"]
    assert env.fetches == 1, "one shared fetch per run"
    assert len(saved["presets"]) == 9
    frame = store.load_frame(out["run_id"])
    assert frame is not None and set(frame.index) == set(env.frame.index)
    assert frame.loc["F00", "universes"] == list(env.frame.loc["F00", "universes"])
    assert "revision_30d" in frame.columns
    assert saved["macro_view"]["status"] == "ok"
    assert {r["sector"] for r in saved["macro_view"]["rows"]} == {"Technology", "Energy"}
    assert saved["macro_view"]["news"] == {"window_days": 7, "digests": NEWS["digests"], "stories": 1}

    cards = saved["candidates"]
    keys = [(c["ticker"], c["direction"]) for c in cards]
    assert len(keys) == len(set(keys))
    assert keys[0] == ("F19", "long"), "two presets plus a tech tailwind rank first"
    energy_short = next(c for c in cards if c["ticker"] == "F00")
    assert energy_short["macro_fit"]["fit"] == "tailwind" and energy_short["macro_boost"] > 0
    energy_long = next(c for c in cards if c["ticker"] == "F17")
    assert energy_long["macro_boost"] == 0, "a headwind never lowers a long"

    assert all(c["review_status"] == "reviewed" for c in cards)
    assert all(c["scout_status"] == "published" for c in cards)
    assert {r["candidate_id"] for r in FakeWriteback.records} == {c["scout_candidate_id"] for c in cards}
    assert all(r["opportunity_candidate_gate"]["status"] in {"pass", "downgraded"} for r in FakeWriteback.records)

    assert saved["summary"] == {"text": "This week leans toward quality tech.", "origin": "llm"}
    assert saved["stats"]["reviewed"] == len(cards) and saved["stats"]["published"] == len(cards)
    assert 0 < saved["cost"]["spent_usd"] <= 2.0
    assert set(saved["cost"]["by_step"]) == {"macro", "review", "digest"}
    assert saved["changes"]["new"] and not saved["changes"]["dropped"]
    assert ("reviews", len(cards), len(cards)) in progress
    assert store.list_runs()[0]["run_id"] == out["run_id"]


def test_review_cap_limits_llm_reviews(env):
    settings = get_idea_scan_settings()
    settings.config.max_reviews = 2
    set_idea_scan_settings(settings)
    saved = store.get_run(run()["run_id"])
    statuses = [c["review_status"] for c in saved["candidates"]]
    assert statuses.count("reviewed") == 2
    assert statuses.count("not_reviewed_cap") == len(statuses) - 2
    assert len(FakeWriteback.records) == 2


def test_budget_stops_starting_reviews(env):
    # Each review costs about $0.24; the macro view about $0.22; $1 leaves room for three reviews.
    out = pipeline.run_weekly_idea_scan(
        {"source": "manual", "max_cost_usd": 1.0},
        review_call=review_call(cost_tokens=100_000),
        macro_call=macro_call,
        digest_call=digest_call,
    )
    saved = store.get_run(out["run_id"])
    statuses = [c["review_status"] for c in saved["candidates"]]
    assert "not_reviewed_budget" in statuses
    assert statuses.count("reviewed") >= 1
    assert saved["cost"]["spent_usd"] <= 1.0
    assert any(s["step"] == "review" and s["reason"] == "budget" for s in saved["cost"]["skipped"])
    assert saved["limited"] is True


def test_tracked_names_skip_review_slots(env):
    env.tracked = {"F19": "position", "F18": "idea"}
    saved = store.get_run(run()["run_id"])
    assert {c["ticker"] for c in saved["already_tracked"]} == {"F19", "F18"}
    assert not {"F19", "F18"} & {c["ticker"] for c in saved["candidates"]}
    tracked = next(c for c in saved["already_tracked"] if c["ticker"] == "F19")
    assert tracked["tracked_as"] == "position" and len(tracked["presets"]) == 2


def test_empty_week_still_publishes_a_digest(env):
    env.frame = empty_frame()
    saved = store.get_run(run()["run_id"])
    assert saved["status"] == "completed"
    assert saved["candidates"] == []
    assert saved["summary"]["origin"] == "rule"
    assert saved["summary"]["text"].startswith("Nothing cleared the bar this week.")
    assert saved["near_misses"]
    assert saved["cost"]["by_step"] == {"macro": pytest.approx(saved["cost"]["spent_usd"])}


def test_rerun_does_not_reopen_dismissed_scout_candidates(env):
    first = store.get_run(run()["run_id"])
    dismissed = first["candidates"][0]["scout_candidate_id"]
    env.existing = {dismissed: "dismissed"}
    FakeWriteback.records = []
    second = store.get_run(run()["run_id"])
    card = next(c for c in second["candidates"] if c["scout_candidate_id"] == dismissed)
    assert card["scout_status"] == "kept_dismissed"
    assert dismissed not in {r["candidate_id"] for r in FakeWriteback.records}


def test_week_over_week_compares_with_last_full_run(env):
    first = store.get_run(run()["run_id"])
    env.frame = make_frame(
        {
            **{f"F{i:02d}": {"quality": float(i), "price_momentum": float(i)} for i in range(19)},
            "NEW": {"quality": 99.0, "price_momentum": 99.0},
        }
    )
    second = store.get_run(run()["run_id"])
    assert second["compared_with_run_id"] == first["run_id"]
    assert "NEW" in {c["ticker"] for c in second["changes"]["new"]}
    assert "F19" in {c["ticker"] for c in second["changes"]["dropped"]}
    assert "F00" in {c["ticker"] for c in second["changes"]["still"]}
    assert "F18" in {c["ticker"] for c in second["changes"]["still"]}
    assert second["macro_view"]["previous_run_id"] == first["run_id"]


def test_limited_manual_run_is_not_a_baseline(env):
    full = store.get_run(run()["run_id"])
    limited = store.get_run(run(source="manual", tickers=["F19"], publish_to_scout=False)["run_id"])
    assert limited["limited"] is True and limited["compared_with_run_id"] is None
    assert all(c["scout_status"] == "not_published" for c in limited["candidates"])
    third = store.get_run(run()["run_id"])
    assert third["compared_with_run_id"] == full["run_id"]


def test_failed_run_is_saved_as_failed(env):
    env.fail_fetch = True
    with pytest.raises(RuntimeError, match="yahoo down"):
        run()
    saved = store.list_runs()[0]
    assert saved["status"] == "failed"
    assert "yahoo down" in store.get_run(saved["run_id"])["error"]


def test_job_spec_resolves():
    from api.job_registry import get_job_spec, import_string

    spec = get_job_spec("weekly_idea_scan")
    assert spec.queue_name == "screens" and spec.supports_progress
    assert import_string(spec.compute_func) is pipeline.run_weekly_idea_scan
    assert import_string(spec.request_model) is pipeline.IdeaScanRunRequest
