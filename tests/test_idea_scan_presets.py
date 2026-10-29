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
        "short-expensive-deteriorating",
        "short-breaking-down",
    ]
    assert {preset.direction for preset in settings.presets} == {"long", "short"}
    assert all(set(preset.universes) == set(p.UNIVERSE_KEYS) for preset in settings.presets)
    assert settings.config.max_reviews == 15
    assert settings.config.max_cost_usd == 2.0


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
