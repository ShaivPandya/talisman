"""Run one real, capped research evaluation without publishing company-sheet changes.

Usage: python -m scripts.evaluate_company_research --ticker EL
Repeat with --resume RUN_ID to continue under the SAME original deadline and budget.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--output", type=Path, default=Path("tmp/company-research-eval"))
    parser.add_argument("--resume")
    args = parser.parse_args()
    load_dotenv()
    # Isolate persistence and prohibit publication; keep real egress governance checks.
    os.environ.update(
        STATE_DB_BACKEND="sqlite",
        TALISMAN_ALLOW_SQLITE_STATE="true",
        STATE_STORAGE_BACKEND="local",
        DATABASE_URL="",
        ENVIRONMENT="development",
    )
    from api import company_research as research
    from api import company_research_store as store
    from api.company_research_workflow import CompanyResearchRunRequest, run_company_research_run
    from api.routers.overview import _normalize_ticker, _validate_ticker
    from ontology.policy import actor_to_dict, user_actor

    ticker = _normalize_ticker(args.ticker)
    _validate_ticker(ticker)
    research.require_research_key()
    args.output.mkdir(parents=True, exist_ok=True)
    research.LOCAL_REPORTS_DIR = args.output / "reports"
    store.SQLITE_PATH = args.output / "runs.sqlite3"
    if args.resume:
        state = store.get_run(args.resume)
        if state["apply"] or state["ticker"] != ticker:
            raise ValueError("Only the same non-publishing evaluation can be resumed.")
        state = store.resume_run(args.resume)
    else:
        prompts = research.ResearchPrompts().model_dump()
        state, _ = store.create_run(
            {
                "ticker": ticker,
                "kinds": list(research.RESEARCH_KINDS),
                "prompts": {kind: prompts[f"{kind}_prompt"] for kind in research.RESEARCH_KINDS},
                "prompt_version": "default-v1",
                "model": research.research_model(),
                "actor": actor_to_dict(user_actor("company-research-evaluation", roles=("admin",))),
                "requested_at": datetime.now(UTC).isoformat(),
                "pricing_version": "gpt-6.1-sol-standard-2026-10-17",
            },
            apply=False,
        )
    (args.output / "run-id.txt").write_text(state["run_id"] + "\n")
    print(json.dumps({"run_id": state["run_id"], "budget": store.budget_summary(state)}), flush=True)
    result = run_company_research_run(CompanyResearchRunRequest(run_id=state["run_id"]), job_id="evaluation")
    (args.output / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)
    return 0 if result["status"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
