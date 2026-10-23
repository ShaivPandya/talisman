"""Compare per-message updates with a Git baseline using disposable SQLite files.

No .env, provider calls or application database are used. SQL byte counts include
bound values; SQLite trace records the statement after parameter substitution.
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


def measure(store, count: int, repeats: int) -> dict:
    timings, sql_bytes, writes = [], [], []
    with tempfile.TemporaryDirectory(prefix="tl220-") as directory:
        store._DB_PATH = Path(directory) / "memory.db"
        store._conn = None
        sid = store.get_or_create_session()["session_id"]
        store.append_messages(
            sid, [{"role": "user" if i % 2 == 0 else "assistant", "content": "x" * 4096} for i in range(count)]
        )
        store.begin_turn(
            sid,
            {"role": "user", "client_turn_id": "measured", "content": "question"},
            {"role": "assistant", "client_turn_id": "measured", "content": "", "is_streaming": True},
        )
        for iteration in range(repeats + 3):
            statements = []
            store._conn.set_trace_callback(statements.append)
            started = time.perf_counter()
            store.update_assistant_message(
                sid, "measured", {"content": "answer" * 100 + str(iteration)}, only_streaming=True
            )
            elapsed = (time.perf_counter() - started) * 1000
            store._conn.set_trace_callback(None)
            if iteration >= 3:
                timings.append(elapsed)
                changes = [s for s in statements if s.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))]
                sql_bytes.append(sum(len(s.encode()) for s in changes))
                writes.append(len(changes))
        store._conn.close()
        store._conn = None
    return {
        "messages": count,
        "p50_ms": round(statistics.median(timings), 3),
        "p95_ms": round(sorted(timings)[int(len(timings) * 0.95) - 1], 3),
        "write_sql_bytes": round(statistics.median(sql_bytes)),
        "write_statements": statistics.median(writes),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="aace36f352789f156dff6a23ba3c3cdefb47f5c4")
    parser.add_argument("--repeats", type=int, default=30)
    args = parser.parse_args()
    os.environ.update(STATE_DB_BACKEND="sqlite", TALISMAN_ALLOW_SQLITE_STATE="true", ASYNC_JOB_BACKEND="local")
    from api import memory_db

    baseline = ModuleType("baseline_memory_db")
    baseline.__file__ = str(Path(memory_db.__file__))
    source = subprocess.check_output(["git", "show", f"{args.baseline_ref}:api/memory_db.py"], text=True)
    exec(compile(source, baseline.__file__, "exec"), baseline.__dict__)
    print(
        json.dumps(
            {
                "baseline_ref": args.baseline_ref,
                "repeats": args.repeats,
                "baseline": [measure(baseline, n, args.repeats) for n in (10, 100, 1000)],
                "current": [measure(memory_db, n, args.repeats) for n in (10, 100, 1000)],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
