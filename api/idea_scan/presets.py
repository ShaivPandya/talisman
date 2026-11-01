"""Idea scan presets and run limits, stored as an app setting so they change without a deploy."""

from __future__ import annotations

import copy
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.idea_scan.momentum import MOMENTUM_VERSION, MomentumRequirement
from api.llm_settings import get_setting, set_setting

IDEA_SCAN_SETTINGS_KEY = "idea_scan.settings"

UniverseKey = Literal["sp500", "sp400", "sp600", "russell2000"]
UNIVERSE_KEYS: tuple[UniverseKey, ...] = ("sp500", "sp400", "sp600", "russell2000")
UNIVERSE_LABELS: dict[str, str] = {
    "sp500": "S&P 500",
    "sp400": "S&P 400",
    "sp600": "S&P 600",
    "russell2000": "Russell 2000",
}

ScreenKind = Literal[
    "long_screen",
    "short_screen",
    "quality_value",
    "value_momentum",
    "composite_top",
    "breakdown",
    "liquid_covered",
    "percentile_rules",
]

# Factor-frame columns a percentile rule can rank, with the label its check shows.
RuleMetric = Literal[
    "quality",
    "eps_momentum",
    "revenue_momentum",
    "roic",
    "share_growth_3y",
    "fcf_margin",
    "capex_to_sales",
    "dollar_volume",
    "market_cap",
]
RULE_METRIC_LABELS: dict[str, str] = {
    "quality": "Quality",
    "eps_momentum": "EPS momentum",
    "revenue_momentum": "Revenue momentum",
    "roic": "ROIC",
    "share_growth_3y": "3-year share count growth",
    "fcf_margin": "FCF margin",
    "capex_to_sales": "Capex / sales",
    "dollar_volume": "Dollar volume",
    "market_cap": "Market cap",
}


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LongScreenParams(_Params):
    pb_threshold: float | None = Field(default=1.5, gt=0)
    profit_type: Literal["Gross Profit", "Operating Income"] | None = "Gross Profit"
    check_revenue: bool = True
    min_revenue_growth: float = 5.0
    check_eps: bool = True
    min_eps_growth: float = 5.0
    require_buybacks: bool = True
    check_ebit_multiple: bool = False
    max_ebit_multiple: float = Field(default=20.0, gt=0)
    check_52w_positive: bool = False
    check_3m_pos_momentum: bool = False
    check_3m_pos_rel_momentum: bool = False


class ShortScreenParams(_Params):
    pb_threshold: float | None = Field(default=3.0, gt=0)
    loss_type: Literal["Gross Loss", "Operating Loss"] | None = "Operating Loss"
    check_revenue: bool = True
    max_revenue_growth: float = 0.0
    check_eps: bool = False
    max_eps_growth: float = 0.0
    require_dilution: bool = False
    check_3m_neg_momentum: bool = False
    check_3m_neg_rel_momentum: bool = False


class QualityValueParams(_Params):
    min_quality_pct: float = Field(default=0.8, ge=0, le=1)
    valuation_metric: Literal["enterpriseToEbitda", "forwardPE", "trailingPE", "priceToBook"] = "enterpriseToEbitda"
    max_sector_valuation_pct: float = Field(default=0.5, gt=0, le=1)


class ValueMomentumParams(QualityValueParams):
    """Cheap within its sector, high quality, with directional momentum evidence."""

    min_quality_pct: float = Field(default=0.7, ge=0, le=1)
    max_sector_valuation_pct: float = Field(default=0.3, gt=0, le=1)
    momentum_requirement: MomentumRequirement = "either"


class CompositeTopParams(_Params):
    min_composite_pct: float = Field(default=0.9, ge=0, le=1)


class BreakdownParams(_Params):
    momentum_requirement: MomentumRequirement = "either"
    require_negative_revisions: bool = True


class LiquidityCoverageFilter(_Params):
    """Traded and followed more than its industry peers: dollar volume and analyst count, ranked within industry."""

    min_dollar_volume_industry_pct: float = Field(default=0.75, gt=0, le=1)
    require_above_median_coverage: bool = True


class PercentileRule(_Params):
    """One metric's percentile among the preset's universes: at least ``min_pct``, at most ``max_pct``, or both."""

    metric: RuleMetric
    min_pct: float | None = Field(default=None, ge=0, le=1)
    max_pct: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _bounded(self) -> PercentileRule:
        if self.min_pct is None and self.max_pct is None:
            raise ValueError("A percentile rule needs min_pct, max_pct or both.")
        if self.min_pct is not None and self.max_pct is not None and self.min_pct > self.max_pct:
            raise ValueError("min_pct can't be above max_pct.")
        return self


class PercentileRulesParams(_Params):
    """Every rule must hold. Percentiles are ranked within the preset's universes, not the whole data set."""

    rules: list[PercentileRule] = Field(default_factory=list, max_length=8)
    momentum_requirement: MomentumRequirement | None = None

    @model_validator(mode="after")
    def _has_condition(self) -> PercentileRulesParams:
        if not self.rules and not self.momentum_requirement:
            raise ValueError("At least one percentile rule or momentum condition is required.")
        return self


class LiquidCoveredParams(LiquidityCoverageFilter):
    """The liquidity and coverage filter as a screen of its own; the composite ranker orders the hits."""

    min_composite_pct: float | None = Field(default=None, ge=0, le=1)


PARAM_MODELS: dict[str, type[_Params]] = {
    "long_screen": LongScreenParams,
    "short_screen": ShortScreenParams,
    "quality_value": QualityValueParams,
    "value_momentum": ValueMomentumParams,
    "composite_top": CompositeTopParams,
    "breakdown": BreakdownParams,
    "liquid_covered": LiquidCoveredParams,
    "percentile_rules": PercentileRulesParams,
}

SCREEN_DIRECTIONS: dict[str, set[str]] = {
    "long_screen": {"long"},
    "short_screen": {"short"},
    "quality_value": {"long"},
    "value_momentum": {"long"},
    "composite_top": {"long"},
    "breakdown": {"short"},
    "liquid_covered": {"long", "short"},
    "percentile_rules": {"long", "short"},
}


class RankWeights(BaseModel):
    """Composite factor weights, as in portfolio/portfolio_optimizer/rank_universe.py."""

    model_config = ConfigDict(extra="forbid")

    quality: float = Field(default=0.33, ge=0)
    price_momentum: float = Field(default=0.33, ge=0)
    revenue_momentum: float = Field(default=0.20, ge=0)
    eps_momentum: float = Field(default=0.14, ge=0)

    @model_validator(mode="after")
    def _some_weight(self) -> RankWeights:
        if self.quality + self.price_momentum + self.revenue_momentum + self.eps_momentum <= 0:
            raise ValueError("At least one ranking weight must be positive.")
        return self


class IdeaScanPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,47}$")
    name: str = Field(min_length=1, max_length=80)
    direction: Literal["long", "short"]
    universes: list[UniverseKey] = Field(default_factory=lambda: list(UNIVERSE_KEYS), min_length=1)
    screen: ScreenKind
    params: dict[str, Any] = Field(default_factory=dict)
    weights: RankWeights = Field(default_factory=lambda: RankWeights())
    max_names: int = Field(default=10, ge=1, le=100)
    enabled: bool = True
    # Extra checks on top of the screen, for any screen kind.
    liquidity_coverage: LiquidityCoverageFilter | None = None

    # Preserve custom legacy cutoffs for review; these presets cannot run until resolved.
    legacy_momentum_params: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _migrate_momentum(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        value = copy.deepcopy(value)
        params = value.get("params") or {}
        if not isinstance(params, dict):
            return value
        original = copy.deepcopy(params)
        screen, pid = value.get("screen"), value.get("id")
        needs_review = False
        for side in ("pos", "neg"):
            old = f"check_2m_{side}_rel_momentum"
            if old in params:
                params.setdefault(f"check_3m_{side}_rel_momentum", params.pop(old))
        for field, kind, default_id, cutoff in (
            ("min_price_momentum_pct", "value_momentum", "long-value-momentum-quality", 0.7),
            ("max_price_momentum_pct", "breakdown", "short-breaking-down", 0.1),
        ):
            if field in params and screen == kind:
                threshold = float(params.pop(field))
                if not 0 <= threshold <= 1:
                    raise ValueError("Legacy momentum percentile must be between 0 and 1.")
                needs_review |= pid != default_id or threshold != cutoff
                params.setdefault("momentum_requirement", "either")
        if screen == "percentile_rules" and isinstance(params.get("rules"), list):
            if not all(isinstance(r, dict) for r in params["rules"]):
                return value
            old_rules = [r for r in params["rules"] if r.get("metric") == "price_momentum"]
            if old_rules:
                needs_review |= not (
                    pid == "short-small-weak-low-roic"
                    and [{k: v for k, v in rule.items() if v is not None} for rule in old_rules]
                    == [{"metric": "price_momentum", "max_pct": 0.4}]
                )
                params["rules"] = [r for r in params["rules"] if r.get("metric") != "price_momentum"]
                params.setdefault("momentum_requirement", "either")
        if needs_review and value.get("legacy_momentum_params") is None:
            value["legacy_momentum_params"] = original
        value["params"] = params
        return value

    @field_validator("universes")
    @classmethod
    def _dedupe_universes(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _validate_params(self) -> IdeaScanPreset:
        if self.direction not in SCREEN_DIRECTIONS[self.screen]:
            raise ValueError(f"The {self.screen} screen can't be used for {self.direction} ideas.")
        self.params = PARAM_MODELS[self.screen].model_validate(self.params).model_dump()
        return self


class IdeaScanConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_reviews: int = Field(default=15, ge=0, le=50)
    max_cost_usd: float = Field(default=4.0, ge=0, le=10)
    review_web_searches: int = Field(default=2, ge=0, le=5)
    macro_web_searches: int = Field(default=5, ge=0, le=10)
    near_miss_limit: int = Field(default=10, ge=0, le=50)
    use_news_digests: bool = True
    news_digest_days: int = Field(default=7, ge=1, le=14)


class IdeaScanSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    momentum_version: Literal[2] = MOMENTUM_VERSION
    presets: list[IdeaScanPreset]
    config: IdeaScanConfig = Field(default_factory=lambda: IdeaScanConfig())
    # Default preset ids these settings were saved alongside. A default added later is merged in on
    # read; one listed here but missing from ``presets`` was removed on purpose and stays removed.
    known_defaults: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> IdeaScanSettings:
        ids = [preset.id for preset in self.presets]
        if len(ids) != len(set(ids)):
            raise ValueError("Preset ids must be unique.")
        return self


def default_presets() -> list[IdeaScanPreset]:
    return [
        IdeaScanPreset(
            id="long-cheap-improving",
            name="Long · Cheap & improving",
            direction="long",
            screen="long_screen",
            params=LongScreenParams().model_dump(),
        ),
        IdeaScanPreset(
            id="long-momentum-quality",
            name="Long · Momentum + quality",
            direction="long",
            screen="composite_top",
            params=CompositeTopParams().model_dump(),
        ),
        IdeaScanPreset(
            id="long-quality-fair-price",
            name="Long · Quality at a fair price",
            direction="long",
            screen="quality_value",
            params=QualityValueParams().model_dump(),
        ),
        IdeaScanPreset(
            id="long-value-momentum-quality",
            name="Long · Value + momentum + quality",
            direction="long",
            screen="value_momentum",
            params=ValueMomentumParams().model_dump(),
        ),
        IdeaScanPreset(
            id="long-liquid-covered",
            name="Long · Liquid & well covered",
            direction="long",
            screen="liquid_covered",
            params=LiquidCoveredParams().model_dump(),
        ),
        IdeaScanPreset(
            id="short-expensive-deteriorating",
            name="Short · Expensive & deteriorating",
            direction="short",
            screen="short_screen",
            params=ShortScreenParams().model_dump(),
        ),
        IdeaScanPreset(
            id="short-breaking-down",
            name="Short · Breaking down",
            direction="short",
            screen="breakdown",
            params=BreakdownParams().model_dump(),
        ),
        IdeaScanPreset(
            id="short-small-weak-low-roic",
            name="Short · Small cap, weak momentum, low ROIC",
            direction="short",
            universes=["sp600", "russell2000"],
            screen="percentile_rules",
            params={
                "rules": [
                    {"metric": "roic", "max_pct": 0.4},
                ],
                "momentum_requirement": "either",
            },
        ),
        IdeaScanPreset(
            id="short-large-diluting-capex",
            name="Short · Large cap diluting, weak FCF, heavy capex",
            direction="short",
            universes=["sp500"],
            screen="percentile_rules",
            params={
                "rules": [
                    {"metric": "share_growth_3y", "min_pct": 0.7},
                    {"metric": "fcf_margin", "max_pct": 0.4},
                    {"metric": "capex_to_sales", "min_pct": 0.5},
                ]
            },
        ),
    ]


def default_settings() -> IdeaScanSettings:
    presets = default_presets()
    return IdeaScanSettings(presets=presets, known_defaults=[p.id for p in presets])


def merge_new_defaults(settings: IdeaScanSettings) -> IdeaScanSettings:
    """Append default presets added since these settings were saved."""
    known = set(settings.known_defaults) | {p.id for p in settings.presets}
    defaults = default_presets()
    added = [p for p in defaults if p.id not in known]
    return settings.model_copy(
        update={"presets": [*settings.presets, *added], "known_defaults": [p.id for p in defaults]}
    )


def get_idea_scan_settings() -> IdeaScanSettings:
    row = get_setting(IDEA_SCAN_SETTINGS_KEY)
    if not row:
        return default_settings()
    try:
        saved = IdeaScanSettings.model_validate(json.loads(str(row.get("value") or "{}")))
    except (TypeError, ValueError):
        return default_settings()
    return merge_new_defaults(saved)


def set_idea_scan_settings(settings: IdeaScanSettings | dict[str, Any]) -> IdeaScanSettings:
    normalized = IdeaScanSettings.model_validate(
        settings.model_dump() if isinstance(settings, IdeaScanSettings) else settings
    )
    normalized.known_defaults = [p.id for p in default_presets()]
    set_setting(IDEA_SCAN_SETTINGS_KEY, normalized.model_dump_json())
    return normalized


def reset_idea_scan_settings() -> IdeaScanSettings:
    return set_idea_scan_settings(default_settings())
