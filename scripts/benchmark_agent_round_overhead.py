"""Paired, offline TL-205 measurements; no provider calls or database writes.

Run from the worktree with:
    .venv/bin/python -m scripts.benchmark_agent_round_overhead \
        --baseline-ref 5ce0a70bb --output outputs/agent-round-overhead.json

Both arms use identical growing transcripts. Policy/settings and audit I/O are
stubbed equally: governance timings include redaction, classification, token
estimation and manifest construction, but exclude storage and provider latency.
Router timings measure only the routing gate with a fixed simulated call delay,
not end-to-end chat TTFT. Streaming order is verified by the integration tests.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


def baseline_module(ref: str, path: str, name: str) -> ModuleType:
    source = subprocess.check_output(["git", "show", f"{ref}:{path}"], text=True)
    module = ModuleType(name)
    sys.modules[name] = module
    exec(compile(source, path, "exec"), module.__dict__)
    return module


def percentiles(values: list[float]) -> dict:
    ordered = sorted(values)
    return {
        "samples": len(values),
        "p50_ms": round(ordered[max(0, math.ceil(len(values) * 0.5) - 1)], 3),
        "p95_ms": round(ordered[max(0, math.ceil(len(values) * 0.95) - 1)], 3),
    }


def payloads(provider: str, rounds: int) -> list[dict]:
    content = "Fabricated portfolio research and market data. " * 180
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"{i}: {content}"} for i in range(24)]
    requests = []
    for index in range(rounds):
        history.append({"role": "user", "content": f"Tool result {index}: {content}"})
        kwargs = {"model": "benchmark", "max_tokens": 1024, "system": "Research instructions. " * 180}
        if provider == "gemini":
            kwargs = {
                "model": "benchmark",
                "config": {"system_instruction": kwargs["system"], "max_output_tokens": 1024},
            }
            kwargs["contents"] = [{"role": row["role"], "parts": [{"text": row["content"]}]} for row in history]
        elif provider == "openai":
            kwargs["instructions"] = kwargs.pop("system")
            kwargs["input"] = deepcopy(history)
        else:
            kwargs["messages"] = deepcopy(history)
        requests.append(kwargs)
    return requests


def governance_run(module: ModuleType, provider: str, requests: list[dict], *, count: bool = False) -> dict:
    state_class = getattr(module, "ModelEgressScanState", None)
    state = {"scan_state": state_class()} if state_class else {}
    durations = []
    scanned_bytes = 0
    original = module.redact_secrets

    def scan(value, **kwargs):
        nonlocal scanned_bytes
        scanned_bytes += len(json.dumps(value).encode())
        return original(value, **kwargs)

    decision = module.ModelGatewayDecision("allowed", "allowed", "external_allowed", "active", False)
    with (
        patch.object(module, "_record_audit"),
        patch.object(module, "_model_gateway_decision", return_value=decision),
        patch.object(module, "redact_secrets", scan if count else original),
    ):
        for request in requests:
            # Inputs are independent of provider mutations and previous pairs.
            request = deepcopy(request)
            started = time.perf_counter()
            module.prepare_model_egress(
                provider=provider, purpose="agent_chat", stream_kwargs=request, actor=None, **state
            )
            durations.append((time.perf_counter() - started) * 1000)
    return {"round_ms": durations, "turn_ms": sum(durations), "scanned_bytes": scanned_bytes}


def provenance_reads(module: ModuleType, unique: bool) -> int:
    reads = []

    class Objects:
        def get_object(self, uid):
            reads.append(uid)

        def write_object(self, kind, uid, properties, *args, **kwargs):
            return {"object_uid": uid, "properties": properties}

    with (
        patch.object(module, "should_attempt_optional_ontology_write", return_value=True),
        patch.object(module, "OntologyObjectService", Objects),
    ):
        module.start_event(
            event_id="benchmark-fresh-uuid",
            event_type="model_call",
            event_name="benchmark",
            **({"unique_event_id": True} if unique else {}),
        )
    return len(reads)


def router_gate(module: ModuleType, deferred: bool, delay: float) -> float:
    baseline = module.RouteDecision("general_research", False, False, None, None, [], 1.0, "regex")

    def simulated_call(**kwargs):
        time.sleep(delay)
        return baseline

    with patch.object(module, "run_llm_route_decision", simulated_call):
        started = time.perf_counter()
        module.resolve_agent_route(
            context=module.build_route_context(user_text="How is market breadth?"),
            regex_baseline=baseline,
            provider="anthropic",
            api_key="offline-placeholder",
            system_prompt="route",
            **({"defer_shadow": True} if deferred else {}),
        )
        return (time.perf_counter() - started) * 1000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--pairs", type=int, default=12)
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--router-delay-ms", type=float, default=75)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.pairs < 1 or args.rounds < 1:
        parser.error("pairs and rounds must be positive")
    # Never inherit credentials/state settings from .env or contact production.
    os.environ.update(STATE_DB_BACKEND="sqlite", TALISMAN_ALLOW_SQLITE_STATE="true", DATABASE_URL="")
    os.environ.update(
        AGENT_INTENT_ROUTER_ENABLED="true",
        AGENT_INTENT_ROUTER_SHADOW_MODE="true",
        AGENT_INTENT_ROUTER_SUPERVISED_ENABLED="false",
    )
    from api import agent_governance, provenance
    from decision_quality import intent_router

    old_governance = baseline_module(args.baseline_ref, "api/agent_governance.py", "baseline_governance")
    old_provenance = baseline_module(args.baseline_ref, "api/provenance.py", "baseline_provenance")
    old_router = baseline_module(args.baseline_ref, "decision_quality/intent_router.py", "baseline_router")
    result = {"baseline_ref": args.baseline_ref, "pairs": args.pairs, "rounds": args.rounds, "governance": {}}
    for provider in ("anthropic", "openai", "gemini", "talisman"):
        requests = payloads(provider, args.rounds)
        samples = {"before": [], "after": []}
        arms = [("before", old_governance), ("after", agent_governance)]
        for pair in range(args.pairs):
            for label, module in arms[:: 1 if pair % 2 == 0 else -1]:
                samples[label].append(governance_run(module, provider, requests))
        result["governance"][provider] = {
            label: {
                "turn": percentiles([row["turn_ms"] for row in samples[label]]),
                "round": percentiles([duration for row in samples[label] for duration in row["round_ms"]]),
                "scanned_bytes_per_turn": governance_run(module, provider, requests, count=True)["scanned_bytes"],
                "observations": samples[label],
            }
            for label, module in arms
        }
    result["provenance_get_object_reads_per_fresh_event"] = {
        "before": provenance_reads(old_provenance, False),
        "after": provenance_reads(provenance, True),
    }
    gates = {"before": [], "after": []}
    for pair in range(args.pairs):
        arms = [("before", old_router, False), ("after", intent_router, True)]
        for label, module, deferred in arms[:: 1 if pair % 2 == 0 else -1]:
            gates[label].append(router_gate(module, deferred, args.router_delay_ms / 1000))
    result["shadow_router_gate"] = {
        "simulated_delay_ms": args.router_delay_ms,
        **{label: {**percentiles(values), "observations_ms": values} for label, values in gates.items()},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                **result,
                "governance": {
                    provider: {
                        label: {key: value for key, value in arm.items() if key != "observations"}
                        for label, arm in arms.items()
                    }
                    for provider, arms in result["governance"].items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
