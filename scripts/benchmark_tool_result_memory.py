"""Paired offline TL-223 measurements against a Git baseline.

    .venv/bin/python -m scripts.benchmark_tool_result_memory --baseline-ref 0275ede8b

Both arms receive identical supplied sessions, with retrieval and database I/O
excluded. Timings measure context assembly, not provider or network latency.
The deterministic replay requests a tool only when the requested beta is absent
from the prompt, or on explicit refresh; it is not a live-model evaluation.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from types import ModuleType

from api import memory_manager
from api.agent_governance import estimate_tokens
from api.tool_result_memory import compact_tool_result


def session_fixture() -> tuple[dict, dict]:
    facts = {
        "as_of": "2026-10-22T16:00:00Z",
        "ranked": [
            {"ticker": ticker, "beta": beta, "history": [{"date": f"day-{i}", "price": 100 + i} for i in range(1000)]}
            for ticker, beta in (("NVDA", 1.8), ("AMD", 1.6), ("INTC", 1.2))
        ],
    }
    tool = {
        "id": "measured",
        "name": "query_ontology",
        "status": "ok",
        "arguments": {"query": "rank beta"},
        "result": json.dumps(facts),
    }
    messages = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": "Earlier portfolio discussion. " * 20}
        for i in range(20)
    ]
    messages += [
        {"role": "user", "content": "Rank NVDA, AMD and INTC."},
        {
            "role": "assistant",
            "content": "NVDA, AMD, then INTC.",
            "tool_calls": [tool],
            "tool_result_memory": [compact_tool_result(tool, observed_at="2026-10-23T12:00:00Z")],
        },
    ]
    return {"session_id": "offline-benchmark", "server_messages": messages}, tool


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="0275ede8b6add505a565b278c267a1e3517c812e")
    parser.add_argument("--repeats", type=int, default=50)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    baseline = ModuleType("baseline_memory_manager")
    source = subprocess.check_output(["git", "show", f"{args.baseline_ref}:api/memory_manager.py"], text=True)
    exec(compile(source, "baseline_memory_manager.py", "exec"), baseline.__dict__)
    session, tool = session_fixture()
    timings: dict[str, list[float]] = {"baseline": [], "current": []}
    conversations = {}
    arms = [("baseline", baseline), ("current", memory_manager)]
    for iteration in range(args.repeats + 5):
        for label, module in arms[:: 1 if iteration % 2 == 0 else -1]:
            started = time.perf_counter()
            conversation, _ = module.build_conversation_context(
                session["session_id"], "What's the beta on the third one?", session=session, enable_retrieval=False
            )
            elapsed = (time.perf_counter() - started) * 1000
            conversations[label] = conversation
            if iteration >= 5:
                timings[label].append(elapsed)
    report = {
        "baseline_ref": args.baseline_ref,
        "paired_repeats": args.repeats,
        "timing_scope": "context assembly only; no model/network calls",
        "arms": {},
    }
    for label, durations in timings.items():
        conversation = conversations[label]
        facts_present = '"beta":1.2' in json.dumps(conversation).replace('\\"', '"')
        report["arms"][label] = {
            "context_p50_ms": round(statistics.median(durations), 4),
            "context_p95_ms": round(sorted(durations)[max(0, int(len(durations) * 0.95) - 1)], 4),
            "estimated_prompt_tokens": estimate_tokens(conversation),
            "third_beta_available": facts_present,
            "scripted_followup_tool_calls": 0 if facts_present else 1,
            "scripted_explicit_refresh_tool_calls": 1,
        }
    report["raw_result_bytes"] = len(tool["result"].encode())
    report["compacted_result_bytes"] = len(json.dumps(session["server_messages"][-1]["tool_result_memory"][0]).encode())
    print(json.dumps(report, indent=2))
    assert report["arms"]["current"]["third_beta_available"], "Compaction lost the third result's beta"


if __name__ == "__main__":
    main()
