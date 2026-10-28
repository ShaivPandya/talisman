"""Request model for an idea scan run, kept light so the API can import it at startup."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from api.idea_scan.presets import UniverseKey


class IdeaScanRunRequest(BaseModel):
    """A scheduled run uses the saved settings as they are; a manual run can narrow them for testing."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["scheduler", "manual"] = "manual"
    universes: list[UniverseKey] | None = None
    tickers: list[str] | None = Field(default=None, max_length=300)
    preset_ids: list[str] | None = None
    max_reviews: int | None = Field(default=None, ge=0, le=50)
    max_cost_usd: float | None = Field(default=None, ge=0, le=10)
    publish_to_scout: bool = True
