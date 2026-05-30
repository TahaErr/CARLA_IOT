"""Tests for v2xsim.hdv — Sprint 4 module 3.

Validates the profile dataclass, weighted assignment statistics,
TM-binding mock-call accuracy, and edge-case handling for bad mix
arguments. All CARLA-free — `apply_profile_to_tm` is tested through
a recording mock TM.

Run from repo root:
    pytest tests/test_hdv.py -v
"""
from __future__ import annotations

from collections import Counter

import numpy as np
import pytest

from v2xsim.hdv import (
    AGGRESSIVE,
    AGGRESSIVE_HOSTILE,
    AI_REALISTIC,
    ATTENTIVE,
    DISTRACTED,
    DEFAULT_MIX,
    HOSTILE_MIX,
    DriverProfile,
    apply_mix_to_vehicles,
    apply_profile_to_tm,
    assign_profiles,
    disable_collision_detection_for,
    disable_tm_collision_detection,
)


# === Mocks ================================================================

class _MockVehicle:
    def __init__(self, actor_id: int) -> None:
        self.id = actor_id


class _MockTM:
    """Records every method call as (method_name, vehicle_id, value)."""
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, float]] = []

    def _record(self, method: str, vehicle: _MockVehicle, value: float) -> None:
        self.calls.append((method, vehicle.id, value))

    def vehicle_percentage_speed_difference(self, v, pct):
        self._record("speed_difference_pct", v, pct)

    def distance_to_leading_vehicle(self, v, d):
        self._record("distance_to_leading_m", v, d)

    def ignore_lights_percentage(self, v, pct):
        self._record("ignore_lights_pct", v, pct)

    def ignore_signs_percentage(self, v, pct):
        self._record("ignore_signs_pct", v, pct)

    def ignore_vehicles_percentage(self, v, pct):
        self._record("ignore_vehicles_pct", v, pct)

    def ignore_walkers_percentage(self, v, pct):
        self._record("ignore_walkers_pct", v, pct)

    def random_left_lanechange_percentage(self, v, pct):
        self._record("random_left_lanechange_pct", v, pct)

    def random_right_lanechange_percentage(self, v, pct):
        self._record("random_right_lanechange_pct", v, pct)

    def collision_detection(self, ref, other, detect):
        # Records (ref_id, other_id) so test can assert configured pairs.
        self.calls.append(("collision_detection",
                           getattr(ref, "id", -1),
                           getattr(other, "id", -1)))


# === Default mix sanity ===================================================

def test_default_mix_weights_sum_to_one():
    total = sum(w for _, w in DEFAULT_MIX)
    assert abs(total - 1.0) < 1e-9


def test_default_mix_uses_three_distinct_named_profiles():
    profiles = [p for p, _ in DEFAULT_MIX]
    names = [p.name for p in profiles]
    assert len(set(names)) == len(names) == 3
    assert {"attentive", "distracted", "aggressive"}.issubset(set(names))


def test_aggressive_profile_more_dangerous_than_attentive():
    """Sanity check that the three profiles are actually ordered as named."""
    assert AGGRESSIVE.ignore_lights_pct > ATTENTIVE.ignore_lights_pct
    assert AGGRESSIVE.speed_difference_pct > ATTENTIVE.speed_difference_pct
    assert AGGRESSIVE.distance_to_leading_m < ATTENTIVE.distance_to_leading_m
    assert DISTRACTED.ignore_vehicles_pct > ATTENTIVE.ignore_vehicles_pct


# === assign_profiles ======================================================

def test_assign_profiles_deterministic_with_same_seed():
    vehicles = [_MockVehicle(i) for i in range(20)]
    a = assign_profiles(vehicles, rng=np.random.default_rng(42))
    b = assign_profiles(vehicles, rng=np.random.default_rng(42))
    assert {k: v.name for k, v in a.items()} == {k: v.name for k, v in b.items()}


def test_assign_profiles_statistically_matches_mix():
    """Over 1000 vehicles, the empirical counts approach the mix weights."""
    vehicles = [_MockVehicle(i) for i in range(1000)]
    rng = np.random.default_rng(0)
    assignments = assign_profiles(vehicles, mix=DEFAULT_MIX, rng=rng)
    counts = Counter(p.name for p in assignments.values())
    # Mix is 70/20/10 → counts should be in those neighbourhoods within ~3σ.
    assert 650 < counts["attentive"] < 750
    assert 150 < counts["distracted"] < 250
    assert 60 < counts["aggressive"] < 140


def test_assign_profiles_empty_mix_raises():
    with pytest.raises(ValueError):
        assign_profiles([_MockVehicle(1)], mix=(), rng=np.random.default_rng(0))


def test_assign_profiles_negative_weights_raise():
    bad_mix = ((ATTENTIVE, 0.5), (DISTRACTED, -0.1), (AGGRESSIVE, 0.1))
    with pytest.raises(ValueError):
        assign_profiles([_MockVehicle(1)], mix=bad_mix, rng=np.random.default_rng(0))


def test_assign_profiles_zero_total_weight_raises():
    bad_mix = ((ATTENTIVE, 0.0), (DISTRACTED, 0.0))
    with pytest.raises(ValueError):
        assign_profiles([_MockVehicle(1)], mix=bad_mix, rng=np.random.default_rng(0))


def test_assign_profiles_normalises_unnormalised_weights():
    """Mix (2, 1, 1) is treated as (0.5, 0.25, 0.25)."""
    unnorm = ((ATTENTIVE, 2.0), (DISTRACTED, 1.0), (AGGRESSIVE, 1.0))
    vehicles = [_MockVehicle(i) for i in range(2000)]
    assignments = assign_profiles(vehicles, mix=unnorm,
                                  rng=np.random.default_rng(0))
    counts = Counter(p.name for p in assignments.values())
    # 50/25/25 ratio.
    assert 950 < counts["attentive"] < 1050
    assert 450 < counts["distracted"] < 550
    assert 450 < counts["aggressive"] < 550


# === apply_profile_to_tm ==================================================

def test_apply_profile_pushes_all_eight_parameters():
    """One profile produces exactly 8 TM calls, one per behavioural knob."""
    tm = _MockTM()
    v = _MockVehicle(actor_id=99)
    apply_profile_to_tm(tm, v, AGGRESSIVE)
    methods_called = [c[0] for c in tm.calls]
    assert set(methods_called) == {
        "speed_difference_pct", "distance_to_leading_m",
        "ignore_lights_pct", "ignore_signs_pct",
        "ignore_vehicles_pct", "ignore_walkers_pct",
        "random_left_lanechange_pct", "random_right_lanechange_pct",
    }
    assert len(tm.calls) == 8


def test_apply_profile_values_match_profile_fields():
    tm = _MockTM()
    v = _MockVehicle(actor_id=99)
    apply_profile_to_tm(tm, v, AGGRESSIVE)
    recorded = {method: value for method, _, value in tm.calls}
    assert recorded["speed_difference_pct"] == AGGRESSIVE.speed_difference_pct
    assert recorded["distance_to_leading_m"] == AGGRESSIVE.distance_to_leading_m
    assert recorded["ignore_lights_pct"] == AGGRESSIVE.ignore_lights_pct


# === apply_mix_to_vehicles (combined) =====================================

def test_apply_mix_returns_name_dict_and_pushes_to_tm():
    tm = _MockTM()
    vehicles = [_MockVehicle(i) for i in range(5)]
    names = apply_mix_to_vehicles(tm, vehicles, rng=np.random.default_rng(0))
    # Returned dict maps every actor.id to a profile name.
    assert set(names.keys()) == {v.id for v in vehicles}
    assert all(n in {"attentive", "distracted", "aggressive"} for n in names.values())
    # Each vehicle got 8 TM calls.
    assert len(tm.calls) == 5 * 8


def test_apply_mix_deterministic_with_same_seed():
    tm1 = _MockTM()
    tm2 = _MockTM()
    vs1 = [_MockVehicle(i) for i in range(10)]
    vs2 = [_MockVehicle(i) for i in range(10)]
    names1 = apply_mix_to_vehicles(tm1, vs1, rng=np.random.default_rng(7))
    names2 = apply_mix_to_vehicles(tm2, vs2, rng=np.random.default_rng(7))
    assert names1 == names2
    assert tm1.calls == tm2.calls


# === HOSTILE_MIX + AGGRESSIVE_HOSTILE =====================================

def test_hostile_mix_weights_sum_to_one():
    total = sum(w for _, w in HOSTILE_MIX)
    assert abs(total - 1.0) < 1e-9


def test_aggressive_hostile_strictly_more_dangerous_than_aggressive():
    """AGGRESSIVE_HOSTILE must dominate AGGRESSIVE on the rule-violation
    axes, otherwise the safety ablation can't separate baseline from V2X.

    NB: distance_to_leading_m is *not* tested as a danger axis any more:
    bumper-close following (< 1 m) caused mass pileups at spawn time
    in CARLA. The hostile profile now uses a spawn-safe distance.
    """
    assert AGGRESSIVE_HOSTILE.speed_difference_pct > AGGRESSIVE.speed_difference_pct
    assert AGGRESSIVE_HOSTILE.ignore_lights_pct > AGGRESSIVE.ignore_lights_pct
    assert AGGRESSIVE_HOSTILE.ignore_signs_pct > AGGRESSIVE.ignore_signs_pct
    assert AGGRESSIVE_HOSTILE.ignore_vehicles_pct > AGGRESSIVE.ignore_vehicles_pct


def test_hostile_mix_statistically_matches_50_20_30():
    vehicles = [_MockVehicle(i) for i in range(1000)]
    assignments = assign_profiles(vehicles, mix=HOSTILE_MIX,
                                  rng=np.random.default_rng(0))
    from collections import Counter
    counts = Counter(p.name for p in assignments.values())
    assert 450 < counts["attentive"] < 550
    assert 150 < counts["distracted"] < 250
    assert 250 < counts["aggressive_hostile"] < 350


# === disable_tm_collision_detection =======================================

def test_disable_collision_detection_configures_all_ordered_pairs():
    """For N vehicles there are N*(N-1) ordered pairs to configure."""
    tm = _MockTM()
    vehicles = [_MockVehicle(i) for i in range(4)]
    n_pairs = disable_tm_collision_detection(tm, vehicles)
    assert n_pairs == 4 * 3  # ordered pairs, no self-pairs
    coll_calls = [c for c in tm.calls if c[0] == "collision_detection"]
    assert len(coll_calls) == 12
    # Every (ref, other) with ref != other appears exactly once.
    pairs = {(c[1], c[2]) for c in coll_calls}
    expected = {(i, j) for i in range(4) for j in range(4) if i != j}
    assert pairs == expected


def test_disable_collision_detection_empty_list_is_noop():
    tm = _MockTM()
    n_pairs = disable_tm_collision_detection(tm, [])
    assert n_pairs == 0
    assert tm.calls == []


# === AI_REALISTIC (Sprint 5) ==============================================

def test_ai_realistic_is_careful_relative_to_hostile():
    """The CAV profile must be far safer than the hostile HDV profile on
    every rule-violation axis, and follow at a wider distance."""
    assert AI_REALISTIC.ignore_lights_pct < AGGRESSIVE_HOSTILE.ignore_lights_pct
    assert AI_REALISTIC.ignore_signs_pct < AGGRESSIVE_HOSTILE.ignore_signs_pct
    assert AI_REALISTIC.distance_to_leading_m > AGGRESSIVE_HOSTILE.distance_to_leading_m
    # Wider following gap than even the rule-compliant ATTENTIVE baseline.
    assert AI_REALISTIC.distance_to_leading_m > ATTENTIVE.distance_to_leading_m


def test_ai_realistic_never_ignores_vehicles_or_walkers():
    """The AV defers vehicle/pedestrian safety to its (enabled) avoidance
    layer — its driver profile must never deliberately ignore either."""
    assert AI_REALISTIC.ignore_vehicles_pct == 0.0
    assert AI_REALISTIC.ignore_walkers_pct == 0.0


def test_ai_realistic_has_small_nonzero_error_rate():
    """Not a flawless oracle: rare rule slips remain, but stay small (<=5%)."""
    assert 0.0 < AI_REALISTIC.ignore_lights_pct <= 5.0
    assert 0.0 < AI_REALISTIC.ignore_signs_pct <= 5.0


# === disable_collision_detection_for (role-aware, Sprint 5) ===============

def test_disable_collision_detection_for_only_configures_actors_as_ref():
    """HDVs (actors) lose avoidance against all vehicles; CAVs (only in
    `others`) are never configured as the avoiding party."""
    tm = _MockTM()
    hdvs = [_MockVehicle(i) for i in range(2)]       # ids 0,1
    cavs = [_MockVehicle(i) for i in range(2, 4)]    # ids 2,3
    all_vehicles = hdvs + cavs
    n_pairs = disable_collision_detection_for(tm, hdvs, all_vehicles)
    # 2 HDVs × (4-1) others = 6 ordered pairs.
    assert n_pairs == 6
    coll_calls = [c for c in tm.calls if c[0] == "collision_detection"]
    ref_ids = {c[1] for c in coll_calls}
    # Only HDV ids ever appear as the avoiding (ref) party.
    assert ref_ids == {0, 1}


def test_disable_collision_detection_for_empty_actors_is_noop():
    tm = _MockTM()
    cavs = [_MockVehicle(i) for i in range(3)]
    n_pairs = disable_collision_detection_for(tm, [], cavs)
    assert n_pairs == 0
    assert tm.calls == []
