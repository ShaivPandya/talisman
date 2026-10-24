"""Compare turn writes and context building on branched conversations with a Git baseline.

Uses disposable SQLite files and no provider calls. The baseline modules come from
``git show <ref>:<path>``; branches are regenerated answers added every 20th turn.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from types import ModuleType


def load_baseline(ref: str, path: str, **injected) -> ModuleType:
    module = ModuleType(f"baseline_{Path(path).stem}")
    module.__file__ = str(Path(path).resolve())
    module.__dict__.update(injected)
    source = subprocess.check_output(["git", "show", f"{ref}:{path}"], text=True)
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def seed(store, count: int, branched: bool) -> str:
    sid = store.get_or_create_session()["session_id"]
    parent = None
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        message = {"id": f"m{i}", "role": role, "content": "x" * 2000}
        if parent:
            message["parent_id"] = parent
        store.append_messages(sid, [message])
        parent = message["id"]
        if branched and role == "assistant" and i % 40 == 1:
            store.append_messages(sid, [{**message, "id": f"alt{i}", "parent_id": f"m{i - 1}"}])
    return sid


def timed(fn, repeats: int) -> list[float]:
    samples = []
    for iteration in range(repeats + 3):
        started = time.perf_counter()
        fn(iteration)
        if iteration >= 3:
            samples.append((time.perf_counter() - started) * 1000)
    return samples


def stats(samples: list[float]) -> dict:
    return {
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(sorted(samples)[max(0, int(len(samples) * 0.95) - 1)], 3),
    }


def measure(store, manager, count: int, repeats: int, branched: bool, lineage_kwargs: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix="tl224-") as directory:
        store._DB_PATH = Path(directory) / "memory.db"
        store._conn = None
        sid = seed(store, count, branched)
        session = store.get_or_create_session(sid)
        context = stats(
            timed(
                lambda _i: manager.build_conversation_context(
                    sid, "next question", enable_retrieval=False, session=session, **lineage_kwargs(session)
                ),
                repeats,
            )
        )
        statements: list[str] = []

        def write_turn(iteration: int) -> None:
            turn = f"bench-{iteration}"
            store.begin_turn(
                sid,
                {"role": "user", "client_turn_id": turn, "content": "question"},
                {"role": "assistant", "client_turn_id": turn, "content": "", "is_streaming": True},
            )
            store.update_assistant_message(sid, turn, {"content": "answer" * 100}, only_streaming=True)

        store._conn.set_trace_callback(statements.append)
        write = stats(timed(write_turn, repeats))
        store._conn.set_trace_callback(None)
        writes = [s for s in statements if s.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))]
        store._conn.close()
        store._conn = None
    return {
        "messages": count,
        "branched": branched,
        "context": context,
        "write_turn": write,
        "write_statements_per_turn": round(len(writes) / (repeats + 3), 1),
        "write_sql_bytes_per_turn": round(sum(len(s.encode()) for s in writes) / (repeats + 3)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="0275ede8b6add505a565b278c267a1e3517c812e")
    parser.add_argument("--repeats", type=int, default=30)
    args = parser.parse_args()
    os.environ.update(STATE_DB_BACKEND="sqlite", TALISMAN_ALLOW_SQLITE_STATE="true", ASYNC_JOB_BACKEND="local")
    from api import memory_db, memory_manager
    from api.conversation_messages import resolve_turn_lineage

    baseline_db = load_baseline(args.baseline_ref, "api/memory_db.py")
    baseline_manager = load_baseline(args.baseline_ref, "api/memory_manager.py", memory_db=baseline_db)

    def current_lineage(session):
        return {"lineage": resolve_turn_lineage(session["server_messages"])}

    results = {"baseline_ref": args.baseline_ref, "repeats": args.repeats, "baseline": [], "current": []}
    for count in (100, 1000):
        results["baseline"].append(measure(baseline_db, baseline_manager, count, args.repeats, False, lambda s: {}))
        results["current"].append(measure(memory_db, memory_manager, count, args.repeats, False, current_lineage))
        results["current"].append(measure(memory_db, memory_manager, count, args.repeats, True, current_lineage))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
