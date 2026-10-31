"""Request models for action-item execution, kept free of LLM provider imports.

`api.routers.action_items` needs these at import time; importing them from
`api.action_item_execution` would load the provider SDKs on API startup.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ExecutionKind = Literal["thesis", "kill_conditions", "valuation"]
KINDS: tuple[ExecutionKind, ...] = ("thesis", "kill_conditions", "valuation")


class ExecutionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    automatic: bool = False
    enabled_kinds: list[ExecutionKind] = Field(default_factory=lambda: list(KINDS))
    max_cost_usd: float = Field(default=5, ge=1, le=25)
    daily_budget_usd: float = Field(default=15, ge=1, le=100)
    max_concurrent: int = Field(default=1, ge=1, le=3)
