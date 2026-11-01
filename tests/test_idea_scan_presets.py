from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.idea_scan import presets as p


def test_starting_presets_exist_and_validate():
    settings = p.default_settings()
    assert [preset.id for preset in settings.presets] == [
        "long-cheap-improving",
        "long-momentum-quality",
        "long-quality-fair-price",
        "long-value-momentum-quality",
        "long-liquid-covered",
        "short-expensive-deteriorating",
        "short-breaking-down",
        "short-small-weak-low-roic",
        "short-large-diluting-capex",
    ]
    assert {preset.direction for preset in settings.presets} == {"long", "short"}
    by_id = {preset.id: preset for preset in settings.presets}
    assert by_id["short-small-weak-low-roic"].universes == ["sp600", "russell2000"]
    assert by_id["short-large-diluting-capex"].universes == ["sp500"]
    others = [x for x in settings.presets if x.screen != "percentile_rules"]
    assert all(set(preset.universes) == set(p.UNIVERSE_KEYS) for preset in others)
    assert settings.config.max_reviews == 15
    assert settings.config.max_cost_usd == 4.0


def test_params_are_normalized_with_screen_defaults():
    preset = p.IdeaScanPreset(
        id="custom", name="Custom", direction="long", screen="long_screen", params={"pb_threshold": 2.0}
    )
    assert preset.params["pb_threshold"] == 2.0
    assert preset.params["require_buybacks"] is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"direction": "short", "screen": "long_screen"},
        {"direction": "long", "screen": "breakdown"},
        {"direction": "long", "screen": "long_screen", "params": {"unknown_knob": 1}},
        {"direction": "long", "screen": "quality_value", "params": {"min_quality_pct": 2}},
        {"direction": "short", "screen": "value_momentum"},
        {"direction": "long", "screen": "value_momentum", "params": {"min_price_momentum_pct": 1.5}},
        {"direction": "long", "screen": "composite_top", "universes": []},
        {"direction": "long", "screen": "composite_top", "universes": ["nasdaq100"]},
        {"direction": "long", "screen": "liquid_covered", "params": {"min_dollar_volume_industry_pct": 0}},
        {"direction": "long", "screen": "composite_top", "liquidity_coverage": {"min_dollar_volume_industry_pct": 2}},
        {"direction": "short", "screen": "percentile_rules"},
        {"direction": "short", "screen": "percentile_rules", "params": {"rules": []}},
        {"direction": "short", "screen": "percentile_rules", "params": {"rules": [{"metric": "roic"}]}},
        {"direction": "short", "screen": "percentile_rules", "params": {"rules": [{"metric": "pe", "max_pct": 0.4}]}},
        {
            "direction": "short",
            "screen": "percentile_rules",
            "params": {"rules": [{"metric": "roic", "min_pct": 0.6, "max_pct": 0.4}]},
        },
    ],
)
def test_invalid_presets_are_rejected(kwargs):
    with pytest.raises(ValidationError):
        p.IdeaScanPreset(id="bad", name="Bad", **kwargs)


def test_duplicate_preset_ids_are_rejected():
    preset = p.default_presets()[0]
    with pytest.raises(ValidationError):
        p.IdeaScanSettings(presets=[preset, preset])


def test_settings_round_trip_through_app_settings():
    assert p.get_idea_scan_settings() == p.default_settings()
    edited = p.default_settings()
    edited.presets[0].max_names = 3
    edited.presets[1].enabled = False
    edited.config.max_reviews = 5
    p.set_idea_scan_settings(edited)

    loaded = p.get_idea_scan_settings()
    assert loaded.presets[0].max_names == 3
    assert loaded.presets[1].enabled is False
    assert loaded.config.max_reviews == 5

    assert p.reset_idea_scan_settings() == p.default_settings()
    assert p.get_idea_scan_settings() == p.default_settings()


def test_corrupt_saved_settings_fall_back_to_defaults():
    from api.llm_settings import set_setting

    set_setting(p.IDEA_SCAN_SETTINGS_KEY, '{"presets": "nope"}')
    assert p.get_idea_scan_settings() == p.default_settings()


def test_liquidity_filter_is_optional_on_any_screen():
    preset = p.IdeaScanPreset(
        id="cheap-liquid",
        name="Cheap, liquid",
        direction="short",
        screen="short_screen",
        liquidity_coverage={"min_dollar_volume_industry_pct": 0.9},
    )
    assert preset.liquidity_coverage is not None
    assert preset.liquidity_coverage.min_dollar_volume_industry_pct == 0.9
    assert preset.liquidity_coverage.require_above_median_coverage is True
    assert p.default_presets()[0].liquidity_coverage is None
    assert p.IdeaScanPreset(id="lc", name="LC", direction="short", screen="liquid_covered").params == {
        "min_dollar_volume_industry_pct": 0.75,
        "require_above_median_coverage": True,
        "min_composite_pct": None,
    }


def test_new_default_presets_are_merged_into_saved_settings():
    from api.llm_settings import set_setting

    # Settings saved before the liquid-covered preset existed, with one old default edited.
    old = p.default_settings().model_dump()
    old["presets"] = [x for x in old["presets"] if x["id"] != "long-liquid-covered"]
    old["presets"][0]["max_names"] = 4
    del old["known_defaults"]
    set_setting(p.IDEA_SCAN_SETTINGS_KEY, p.IdeaScanSettings.model_validate(old).model_dump_json())

    loaded = p.get_idea_scan_settings()
    assert [x.id for x in loaded.presets][-1] == "long-liquid-covered"
    assert loaded.presets[0].max_names == 4

    # Once saved alongside it, removing a default sticks.
    loaded.presets = [x for x in loaded.presets if x.id != "short-breaking-down"]
    p.set_idea_scan_settings(loaded)
    assert "short-breaking-down" not in {x.id for x in p.get_idea_scan_settings().presets}
