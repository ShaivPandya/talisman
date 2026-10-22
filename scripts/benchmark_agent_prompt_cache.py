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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--reasoning-effort", default=None)
    parser.add_argument("--output", type=Path, default=Path("outputs/agent-prompt-cache.json"))
    args = parser.parse_args(argv)
    if args.pairs < 1 or args.rounds < 2:
        parser.error("Use at least one pair and two rounds.")

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
