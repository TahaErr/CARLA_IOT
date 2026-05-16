"""Unit tests for `v2xsim.weather`.

Only the CARLA-free pure helpers are tested here (whitelist
membership, default axis, validation). `apply_weather_preset` is
CARLA-bound and exercised by the ablation runner.
"""
from __future__ import annotations

import pytest

from v2xsim.weather import (
    DEFAULT_WEATHER_AXIS,
    WEATHER_PRESETS,
    apply_weather_preset,
    get_weather_preset_names,
    is_valid_preset,
)


def test_whitelist_is_non_empty():
    assert len(WEATHER_PRESETS) > 0


def test_whitelist_contains_the_three_thesis_presets():
    # The default ablation axis must all live in the whitelist.
    for name in DEFAULT_WEATHER_AXIS:
        assert name in WEATHER_PRESETS, f"{name} missing from whitelist"


def test_default_axis_brackets_visibility_spectrum():
    # Sanity: clear day, sunset, hard rain — three points, in order.
    assert DEFAULT_WEATHER_AXIS == ("ClearNoon", "ClearSunset", "HardRainNoon")


def test_get_preset_names_returns_immutable_tuple():
    names = get_weather_preset_names()
    assert isinstance(names, tuple)
    # Mutating the returned object must not touch the module constant.
    with pytest.raises((TypeError, AttributeError)):
        names.append("InvalidPreset")  # type: ignore[attr-defined]


def test_is_valid_preset_accepts_whitelist_names():
    assert is_valid_preset("ClearNoon") is True
    assert is_valid_preset("HardRainNoon") is True
    assert is_valid_preset("ClearSunset") is True


def test_is_valid_preset_rejects_unknown_names():
    assert is_valid_preset("Tornado") is False
    assert is_valid_preset("") is False
    assert is_valid_preset("clear_noon") is False  # case-sensitive


def test_apply_weather_preset_rejects_unknown_preset():
    # Validation runs before any CARLA call, so we don't need a world.
    with pytest.raises(ValueError, match="Unknown weather preset"):
        apply_weather_preset(world=None, preset_name="NotAPreset")
