from __future__ import annotations

import pytest

from api.routers import agent
from decision_quality.chat_eval_runner import AgentChatRun, _routing_expectation_checks, load_cases
from decision_quality.routing_signals import extract_candidate_ticker, extract_tickers, is_contextual_followup

ROUTING_CASES = load_cases(case_selectors=["routing_"], statuses={"approved", "review"})
NEGATIVE_CASES = [case for case in ROUTING_CASES if "candidate_tickers" in case.data["routing_expectations"]]


@pytest.mark.parametrize("case", ROUTING_CASES, ids=lambda case: case.case_id)
def test_routing_corpus_against_actual_regex_route(case, monkeypatch):
    monkeypatch.setenv("AGENT_INTENT_ROUTER_ENABLED", "false")
    monkeypatch.setenv("AGENT_INTENT_ROUTER_SUPERVISED_ENABLED", "false")
    screen = case.data.get("screen_context")
    decision, metadata = agent._resolve_chat_route(
        user_text=case.data["user_message"],
        screen_context=agent.ScreenContextModel(**screen) if screen else None,
        recent_conversation=case.data.get("recent_conversation"),
    )
    run = AgentChatRun(
        final_text="",
        events=[],
        tool_names=[],
        done_payload={"intent_router": {"applied": decision.to_meta(), "telemetry": metadata}},
    )
    checks = []
    _routing_expectation_checks(checks, case=case, run=run)
    assert all(check["passed"] for check in checks), checks


@pytest.mark.parametrize(
    "message,tickers",
    [
        ("CPI GDP AI CEO CFO EPS FCF USD ECB FOMC ETF", []),
        ("What about $AI and $F?", ["AI", "F"]),
        ("NVDA and MSFT", ["NVDA", "MSFT"]),
        ("nvidia and microsoft", ["NVDA", "MSFT"]),
        ("AI demand for NVDA and META", ["NVDA", "META"]),
    ],
)
def test_ticker_disambiguation(message, tickers):
    assert extract_tickers(message) == tickers


def test_screen_ticker_requires_reference_and_explicit_ticker_wins():
    screen = {"ticker": "NVDA"}
    assert extract_candidate_ticker("Pressure-test this position", screen) == "NVDA"
    assert extract_candidate_ticker("Review my thesis", screen) == "NVDA"
    assert extract_candidate_ticker("Should I buy it here?", screen) == "NVDA"
    assert extract_candidate_ticker("Give me the short version", screen) is None
    assert extract_candidate_ticker("How will GDP affect rates?", screen) is None
    assert extract_candidate_ticker("What do you think of this CPI report?", screen) is None
    assert extract_candidate_ticker("Pressure-test MSFT", screen) == "MSFT"


@pytest.mark.parametrize(
    "message",
    [
        "Scan semiconductors for anything interesting right now?",
        "Find undervalued stocks",
        "Rank my watchlist",
        "Look for investment ideas in energy",
        "Screen companies for improving margins",
        "Find an investment opportunity",
        "Any ideas in semiconductors?",
    ],
)
def test_explicit_discovery_phrases_remain_supported(message):
    assert agent._should_run_opportunity_candidate_preflight(message)


def test_named_thesis_review_remains_an_explicit_evaluation():
    assert agent._should_run_decision_quality_chat("Review my NVDA thesis")


@pytest.mark.parametrize(
    "message",
    [
        "What does investment thesis mean?",
        "NVDA stock split date?",
        "Scan this report for anything interesting",
        "Find the latest stock prices",
        "Find the earnings report for NVDA stock",
        "Rank the risks in my stock portfolio",
    ],
)
def test_investment_words_without_evaluation_intent_skip_hidden_passes(message):
    assert not agent._should_run_decision_quality_chat(message)
    assert not agent._should_run_opportunity_candidate_preflight(message)


def test_followup_uses_completed_turn_and_stops_at_topic_change():
    history = [
        {"role": "user", "content": "Chart NVDA"},
        {"role": "assistant", "content": "NVDA is trending higher."},
        {"role": "user", "content": "Chart MSFT"},
        {"role": "assistant", "content": "", "is_streaming": True},
    ]
    assert is_contextual_followup("What about its valuation?", history)
    assert agent._routing_tickers("What about its valuation?", recent_conversation=history) == ["NVDA"]
    assert not is_contextual_followup("How do CPI and GDP affect rates?", history)
    assert not is_contextual_followup("What about its valuation?", [])


def test_inherited_ticker_reaches_hidden_context_tools():
    history = [
        {"role": "user", "content": "Compare NVDA and MSFT"},
        {"role": "assistant", "content": "1. NVDA is expensive. 2. MSFT has more stable cash flows."},
    ]
    screen = agent.ScreenContextModel(page_name="Research", route="/research/AAPL", ticker="AAPL")
    message = "Should I buy the second one?"
    assert agent._should_run_decision_quality_chat(message, screen, recent_conversation=history)
    calls = agent._decision_quality_chat_tool_calls(message, screen, recent_conversation=history)
    assert next(call["args"]["ticker"] for call in calls if call["name"] == "get_thesis") == "MSFT"


def test_explicit_ticker_replaces_inherited_tickers_but_keeps_tools():
    case = next(case for case in NEGATIVE_CASES if case.case_id == "routing_second_followup_2026")
    history = case.data["recent_conversation"]
    assert agent._routing_tickers("What about $AI?", recent_conversation=history) == ["AI"]
    tools = agent._select_tool_names("What about $AI?", recent_conversation=history)
    assert "fetch_alternative_data" in tools
    assert "get_financials" in tools
