"""Weather preset wrapper for CARLA ablations.

Implements the weather axis of proposal §4.7. CARLA exposes ~14
named `carla.WeatherParameters` presets (`ClearNoon`, `HardRainNoon`,
etc.); this module wraps the subset useful for V2X safety ablations
and gives a single typed entry point — `apply_weather_preset` —
that the ablation runner uses.

The detector (Sprint 2) was fine-tuned on a 7-preset rotation
(ClearNoon, CloudyNoon, WetNoon, ClearSunset, CloudySunset,
HardRainNoon, SoftRainNoon). The weather ablation reuses three of
these to bracket the visibility / surface-friction axis:

  * `ClearNoon`     — best-case (detector mAP=0.53 measured here)
  * `ClearSunset`   — mid-difficulty (low-sun glare, long shadows)
  * `HardRainNoon`  — worst-case (rain + reduced visibility)

Trends across these three should make the V2X-under-degraded-vision
benefit visible: at HardRainNoon the RSU YOLO detector loses recall,
so cooperative CPMs (multi-RSU + CAV local sensor) contribute more
new information per equipped vehicle.

This module is CARLA-bound for `apply_weather_preset` (it touches
`carla.WeatherParameters`) but the constants are pure Python and
unit-testable without CARLA. Imports are lazy.
"""
from __future__ import annotations

from typing import Any


# Whitelist of weather presets the ablation runner accepts. Adding a
# new one is one line — but verify the detector has been fine-tuned
# on it (or document the OOD setting in the thesis methodology).
WEATHER_PRESETS = (
    "ClearNoon",
    "CloudyNoon",
    "WetNoon",
    "WetCloudyNoon",
    "MidRainyNoon",
    "HardRainNoon",
    "SoftRainNoon",
    "ClearSunset",
    "CloudySunset",
    "WetSunset",
    "WetCloudySunset",
    "MidRainSunset",
    "HardRainSunset",
    "SoftRainSunset",
)


# The three-preset ablation matrix recommended for the thesis weather
# axis. Brackets the visibility/friction spectrum with three points
# rather than the full 14, keeping the matrix tractable.
DEFAULT_WEATHER_AXIS = ("ClearNoon", "ClearSunset", "HardRainNoon")


def get_weather_preset_names() -> tuple[str, ...]:
    """Return the immutable tuple of accepted preset names."""
    return WEATHER_PRESETS


def is_valid_preset(name: str) -> bool:
    """True if `name` is in the WEATHER_PRESETS whitelist."""
    return name in WEATHER_PRESETS


def apply_weather_preset(world: Any, preset_name: str) -> None:
    """Apply a named weather preset to the given CARLA world.

    Args:
        world: connected `carla.World`.
        preset_name: one of `WEATHER_PRESETS`.

    Raises:
        ValueError: if `preset_name` is not in the whitelist.
        AttributeError: if the running CARLA build lacks the preset
            (very old CARLA versions may not have every name).
    """
    if not is_valid_preset(preset_name):
        raise ValueError(
            f"Unknown weather preset {preset_name!r}; valid options: "
            f"{', '.join(WEATHER_PRESETS)}"
        )
    import carla  # lazy
    preset = getattr(carla.WeatherParameters, preset_name)
    world.set_weather(preset)
