"""Sequential A/B replay of Anthropic chat prefill, using synthetic tool results.

Run with ``python -m scripts.benchmark_agent_prompt_cache --pairs 10``.
Uses the real stable agent prompt and selected tool schemas, never real user data
or tool execution. Loads only Anthropic credentials/model from the local .env.
The uncached arm reconstructs the original string-system request shape.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(fraction * len(ordered)) - 1)], 3)


def uncached_request(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Restore pre-caching transport shape while preserving the exact content."""
    result = copy.deepcopy(kwargs)
    result["system"] = "".join(block["text"] for block in result["system"])
    for message in result["messages"]:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        blocks = [{key: value for key, value in block.items() if key != "cache_control"} for block in content]
        if len(blocks) == 1 and blocks[0].get("type") == "text":
            message["content"] = blocks[0]["text"]
        else:
            message["content"] = blocks
    return result


def replay_conversation(round_index: int) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                "Synthetic latency replay with fabricated portfolio tool results, not investment advice. "
                "Do not call tools. Reply with exactly READY and no other text."
            ),
        }
    ]
    for index in range(round_index):
        call_id = f"benchmark-call-{index}"
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": call_id,
                            "name": "get_portfolio",
                            "input": {},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": call_id,
                            "content": json.dumps({"synthetic": True, "positions": [], "round": index}),
                        },
                        {"type": "text", "text": "Synthetic replay complete. Reply with exactly READY."},
                    ],
                },
            ]
        )
    return messages


def summarize(observations: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {}
    for cached in (False, True):
        rows = [row for row in observations if row["cache_enabled"] == cached]
        warm = [row for row in rows if row["round_index"] > 0]
        first = [row for row in rows if row["round_index"] == 0]
        ttfts = [row["first_token_ms"] for row in warm if row["first_token_ms"] is not None]
        first_ttfts = [row["first_token_ms"] for row in first if row["first_token_ms"] is not None]
        summary["cached" if cached else "uncached"] = {
            "calls": len(rows),
            "continuation_calls": len(warm),
            "continuation_ttft_samples": len(ttfts),
            "continuation_ttft_p50_ms": percentile(ttfts, 0.5),
            "continuation_ttft_p95_ms": percentile(ttfts, 0.95),
            "first_round_ttft_p50_ms": percentile(first_ttfts, 0.5),
            "cache_read_input_tokens": sum(row.get("cache_read_input_tokens", 0) for row in rows),
            "cache_creation_input_tokens": sum(row.get("cache_creation_input_tokens", 0) for row in rows),
            "uncached_input_tokens": sum(row.get("uncached_input_tokens", row["input_tokens"]) for row in rows),
        }
    cold_writes = {
        row["pair"]: row.get("cache_creation_input_tokens", 0)
        for row in observations
        if row["cache_enabled"] and row["round_index"] == 0
    }
    warm = [row for row in observations if row["cache_enabled"] and row["round_index"] > 0]
    summary["verification"] = {
        "continuations": len(warm),
        "cache_hits": sum(row.get("cache_read_input_tokens", 0) > 0 for row in warm),
        "reads_cover_first_request": sum(
            row.get("cache_read_input_tokens", 0) >= cold_writes[row["pair"]] > 0 for row in warm
        ),
    }
    return summary


def stable_tool_scenarios(provider: str) -> list[dict[str, Any]]:
    """Discovery, tool continuation, synthesis, then a changed-context turn."""
    from api.routers import agent

    question = "Synthetic replay only. Do not call tools. Reply with exactly READY."
    conversation: list[dict[str, Any]] = [{"role": "user", "content": question}]
    scenarios = []

    def snapshot(phase: str, turn: int, names: list[str], text_only: bool = False) -> None:
        scenarios.append(
            {
                "phase": phase,
                "turn": turn,
                "selected_names": list(names),
                "text_only": text_only,
                "conversation": copy.deepcopy(conversation),
            }
        )

    def tool_result(name: str, index: int, result: dict[str, Any]) -> None:
        call_id = f"benchmark-{index}"
        if provider == "anthropic":
            conversation.extend(
                [
                    {"role": "assistant", "content": [{"type": "tool_use", "id": call_id, "name": name, "input": {}}]},
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": call_id, "content": json.dumps(result)},
                            {"type": "text", "text": question},
                        ],
                    },
                ]
            )
        else:
            conversation.extend(
                [
                    {"type": "function_call", "call_id": call_id, "name": name, "arguments": "{}"},
                    {"type": "function_call_output", "call_id": call_id, "output": json.dumps(result)},
                    {"role": "user", "content": question},
                ]
            )

    names = agent._select_tool_names("Chart NVDA")
    snapshot("initial", 0, names)
    tool_result("search_agent_capabilities", 0, {"matches": [{"name": "get_fx_dashboard"}]})
    names.append("get_fx_dashboard")
    snapshot("discovery", 0, names)
    tool_result("get_fx_dashboard", 1, {"synthetic": True, "pairs": []})
    snapshot("tool_continuation", 0, names)
    snapshot("synthesis", 0, names, text_only=True)
    conversation = [
        {"role": "user", "content": question},
        {"role": "assistant", "content": "READY"},
        {"role": "user", "content": question + " This is a new synthetic turn."},
    ]
    names = agent._select_tool_names("How do rates affect my portfolio?")
    snapshot("next_turn", 1, names)
    tool_result("get_yield_curve", 2, {"synthetic": True, "yields": []})
    snapshot("next_turn_continuation", 1, names)
    return scenarios


def stable_tool_request(provider: str, scenario: dict[str, Any], *, after: bool, namespace: str) -> dict[str, Any]:
    """Use the actual builder; reconstruct only TL-221's previous transport choices."""
    from api.routers import agent

    tools = (
        agent._chat_tool_definitions(provider, scenario["selected_names"])
        if after
        else agent._tool_definitions_from_names(provider, scenario["selected_names"])
    )
    if not after and provider == "openai" and scenario["text_only"]:
        tools = []
    tools = copy.deepcopy(tools)
    if tools:
        # Isolate before the cacheable tool prefix, including on Anthropic.
        first = min(tools, key=lambda tool: tool["name"]) if provider == "anthropic" or after else tools[0]
        first["description"] = f"Synthetic benchmark {namespace}. " + first["description"]
    instructions = (
        agent._build_agent_base_instructions()
        + f"\n\n---\n\nSynthetic memory/screen/preferences: turn {scenario['turn']}."
    )
    kwargs = agent._model_stream_kwargs(
        provider=provider,
        instructions=instructions,
        conversation=copy.deepcopy(scenario["conversation"]),
        max_tokens=64,
        tool_defs=tools,
        disable_tool_use=scenario["text_only"],
        session_id=namespace if after else None,
        reasoning_effort=None,
    )
    if not after and provider == "openai" and tools:
        kwargs["tools"] = tools  # Previous OpenAI requests retained routing order.
    if provider == "anthropic":
        kwargs["system"][0]["text"] = f"Synthetic benchmark {namespace}.\n" + kwargs["system"][0]["text"]
    else:
        kwargs["instructions"] = f"Synthetic benchmark {namespace}.\n" + kwargs["instructions"]
    return kwargs


def summarize_stable_tools(observations: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {}
    for arm in ("before", "after"):
        rows = [row for row in observations if row["arm"] == arm]
        phases = {}
        for phase in dict.fromkeys(row["phase"] for row in rows):
            samples = [row for row in rows if row["phase"] == phase]
            ttfts = [row["first_token_ms"] for row in samples if row["first_token_ms"] is not None]
            total = sum(row.get("input_tokens", 0) for row in samples)
            reads = sum(row.get("cache_read_input_tokens", 0) for row in samples)
            phases[phase] = {
                "calls": len(samples),
                "ttft_samples": len(ttfts),
                "ttft_p50_ms": percentile(ttfts, 0.5),
                "ttft_p95_ms": percentile(ttfts, 0.95),
                "cache_hits": sum(row.get("cache_read_input_tokens", 0) > 0 for row in samples),
                "input_tokens": total,
                "cache_read_input_tokens": reads,
                "cache_creation_input_tokens": sum(row.get("cache_creation_input_tokens", 0) for row in samples),
                "uncached_input_tokens": sum(
                    row.get("uncached_input_tokens", row.get("input_tokens", 0)) for row in samples
                ),
                "cached_input_percent": round(100 * reads / total, 3) if total else None,
            }
        summary[arm] = phases
    return summary


def run_stable_tools_benchmark(args: argparse.Namespace) -> int:
    from dotenv import dotenv_values

    provider = args.provider
    values = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    prefix = provider.upper()
    for key in (f"{prefix}_API_KEY", f"{prefix}_MODEL_MID"):
        if values.get(key):
            os.environ.setdefault(key, str(values[key]))
    if not os.getenv(f"{prefix}_API_KEY"):
        raise RuntimeError(f"Set {prefix}_API_KEY or supply it in the worktree's .env.")
    os.environ.update(
        {
            "LLM_PROVIDER": provider,
            "ENVIRONMENT": "development",
            "STATE_DB_BACKEND": "sqlite",
            "TALISMAN_ALLOW_SQLITE_STATE": "true",
            "STATE_STORAGE_BACKEND": "local",
            "DATABASE_URL": "",
        }
    )
    import anthropic
    import openai

    from api.routers import agent

    client = (anthropic.Anthropic if provider == "anthropic" else openai.OpenAI)(max_retries=0, timeout=90)
    observations: list[dict[str, Any]] = []
    report = {
        "protocol": "stable-tools-v1",
        "provider": provider,
        "started_at": datetime.now(UTC).isoformat(),
        "pairs_per_run": args.pairs,
        "runs": args.runs,
        "concurrency": 1,
        "max_tokens": 64,
        "reasoning_effort": None,
        "sdk_version": anthropic.__version__ if provider == "anthropic" else openai.__version__,
        "router_sha256": hashlib.sha256(Path(agent.__file__).read_bytes()).hexdigest(),
        "workload": "Synthetic replay only; no tools, production state, or API server.",
        "observations": observations,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    failed = False
    try:
        for run in range(args.runs):
            for pair in range(args.pairs):
                namespaces = {arm: uuid.uuid4().hex for arm in ("before", "after")}
                for scenario in stable_tool_scenarios(provider):
                    for after in (False, True) if (run + pair) % 2 == 0 else (True, False):
                        arm = "after" if after else "before"
                        kwargs = stable_tool_request(provider, scenario, after=after, namespace=namespaces[arm])
                        report["model"] = kwargs["model"]
                        timing: dict[str, Any] = {"purpose": "prompt_cache_benchmark"}
                        started = time.perf_counter()
                        stream = agent._stream_llm_response(client, provider, kwargs, [], model_timing=timing)
                        while True:
                            try:
                                next(stream)
                            except StopIteration as done:
                                response = done.value
                                break
                        agent._record_model_timing(
                            {}, timing, started=started, status="ok", provider=provider, model=kwargs["model"]
                        )
                        row = {
                            "run": run,
                            "pair": pair,
                            "arm": arm,
                            "phase": scenario["phase"],
                            "first_token_ms": timing.get("first_token_ms"),
                            "duration_ms": timing["duration_ms"],
                            "cached_input_percent": timing["cached_input_percent"],
                            "tool_count": len(kwargs.get("tools", [])),
                            "load_average": os.getloadavg()[0],
                            **agent._usage_dict(response),
                        }
                        observations.append(row)
                        print(json.dumps(row), flush=True)
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "status_code": getattr(exc, "status_code", None)}
        failed = True
    finally:
        client.close()
        report["summary"] = summarize_stable_tools(observations)
        report["finished_at"] = datetime.now(UTC).isoformat()
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "summary": report["summary"], "error": report.get("error")}))
    return int(failed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, default=10)
    parser.add_argument("--protocol", choices=["legacy", "stable-tools"], default="legacy")
    parser.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--reasoning-effort", default=None)
    parser.add_argument("--output", type=Path, default=Path("outputs/agent-prompt-cache.json"))
    args = parser.parse_args(argv)
    if args.pairs < 1 or args.rounds < 2 or args.runs < 1:
        parser.error("Use at least one pair and two rounds.")

    if args.protocol == "stable-tools":
        return run_stable_tools_benchmark(args)
    if args.provider != "anthropic":
        parser.error("Use --protocol stable-tools for OpenAI.")

    from dotenv import dotenv_values

    root = Path(__file__).resolve().parents[1]
    values = dotenv_values(root / ".env")
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL_MID"):
        if values.get(key):
            os.environ.setdefault(key, str(values[key]))
    if not os.getenv("ANTHROPIC_API_KEY"):
        parser.error("Set ANTHROPIC_API_KEY or supply it in the worktree's .env.")
    # Imports must not connect to production state via inherited configuration.
    os.environ.update(
        {
            "LLM_PROVIDER": "anthropic",
            "ENVIRONMENT": "development",
            "STATE_DB_BACKEND": "sqlite",
            "TALISMAN_ALLOW_SQLITE_STATE": "true",
            "STATE_STORAGE_BACKEND": "local",
            "DATABASE_URL": "",
        }
    )
    import anthropic

    from api.routers import agent

    client = anthropic.Anthropic(max_retries=0, timeout=90)
    tools = agent._tool_definitions_from_names(
        "anthropic", ["get_portfolio", "get_portfolio_risk", "query_ontology", "search_agent_capabilities"]
    )
    instructions = agent._build_agent_base_instructions() + "\n\n---\n\nSynthetic screen context: empty portfolio."
    observations: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "pairs": args.pairs,
        "rounds": args.rounds,
        "concurrency": 1,
        "max_tokens": 64,
        "reasoning_effort": args.reasoning_effort,
        "sdk_version": anthropic.__version__,
        "router_sha256": hashlib.sha256(Path(agent.__file__).read_bytes()).hexdigest(),
        "workload": "Synthetic tool-result replay; provider prefill only, no tool execution or API server.",
        "observations": observations,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    failed = False
    try:
        for pair in range(args.pairs):
            namespace = uuid.uuid4().hex
            # Alternate arm order to reduce drift bias. A fresh prefix per pair
            # gives a measurable first cache write, isolated from other agents.
            for cached in (False, True) if pair % 2 == 0 else (True, False):
                for round_index in range(args.rounds):
                    kwargs = agent._model_stream_kwargs(
                        provider="anthropic",
                        instructions=instructions,
                        conversation=replay_conversation(round_index),
                        max_tokens=64,
                        tool_defs=tools,
                        disable_tool_use=True,
                        reasoning_effort=args.reasoning_effort,
                    )
                    kwargs["system"][0]["text"] = f"Benchmark namespace: {namespace}\n\n" + kwargs["system"][0]["text"]
                    if not cached:
                        kwargs = uncached_request(kwargs)
                    report["model"] = kwargs["model"]
                    timing = {"purpose": "prompt_cache_benchmark", "round_index": round_index}
                    started = time.perf_counter()
                    stream = agent._stream_llm_response(client, "anthropic", kwargs, [], model_timing=timing)
                    while True:
                        try:
                            next(stream)
                        except StopIteration as done:
                            response = done.value
                            break
                    agent._record_model_timing(
                        {}, timing, started=started, status="ok", provider="anthropic", model=kwargs["model"]
                    )
                    row = {
                        "pair": pair,
                        "round_index": round_index,
                        "cache_enabled": cached,
                        "first_token_ms": timing.get("first_token_ms"),
                        "duration_ms": timing["duration_ms"],
                        **agent._usage_dict(response),
                    }
                    observations.append(row)
                    print(json.dumps(row), flush=True)
    except Exception as exc:
        # Keep provider error bodies, prompts and credentials out of the report.
        report["error"] = {"type": type(exc).__name__, "status_code": getattr(exc, "status_code", None)}
        failed = True
    finally:
        client.close()
        report["summary"] = summarize(observations)
        report["finished_at"] = datetime.now(UTC).isoformat()
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "summary": report["summary"], "error": report.get("error")}))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
