"""Unit tests for `v2xsim.walker`.

Only the CARLA-free helpers are tested here (target-speed sampling and
blueprint-name selection). The CARLA-bound spawn / start functions are
exercised by `scripts/40_ablation_run.py` smoke tests; mocking them
deeply would just retest the mock.
"""
from __future__ import annotations

import pytest

from v2xsim.walker import (
    WALKER_MEAN_SPEED_MS,
    WALKER_SPEED_MAX_MS,
    WALKER_SPEED_MIN_MS,
    pick_walker_blueprint_names,
    pick_walker_target_speeds,
)


# === target-speed sampling ================================================

def test_target_speeds_returns_requested_count():
    speeds = pick_walker_target_speeds(n_walkers=20, seed=0)
    assert len(speeds) == 20


def test_target_speeds_zero_walkers_returns_empty_list():
    assert pick_walker_target_speeds(n_walkers=0, seed=0) == []


def test_target_speeds_negative_raises():
    with pytest.raises(ValueError):
        pick_walker_target_speeds(n_walkers=-1, seed=0)


def test_target_speeds_clipped_to_realistic_range():
    speeds = pick_walker_target_speeds(n_walkers=1000, seed=0)
    assert all(WALKER_SPEED_MIN_MS <= s <= WALKER_SPEED_MAX_MS for s in speeds)


def test_target_speeds_mean_near_nhtsa_value():
    # 1000 samples should average close to the 1.4 m/s NHTSA mean.
    speeds = pick_walker_target_speeds(n_walkers=1000, seed=0)
    mean = sum(speeds) / len(speeds)
    # Loose bound — clipping shifts the mean slightly.
    assert abs(mean - WALKER_MEAN_SPEED_MS) < 0.1


def test_target_speeds_deterministic_with_same_seed():
    a = pick_walker_target_speeds(n_walkers=20, seed=42)
    b = pick_walker_target_speeds(n_walkers=20, seed=42)
    assert a == b


def test_target_speeds_different_seeds_give_different_samples():
    a = pick_walker_target_speeds(n_walkers=20, seed=0)
    b = pick_walker_target_speeds(n_walkers=20, seed=1)
    assert a != b


# === blueprint name selection =============================================

def test_blueprint_names_returns_requested_count():
    pool = [f"walker.pedestrian.{i:04d}" for i in range(40)]
    names = pick_walker_blueprint_names(n_walkers=20, available_bp_names=pool, seed=0)
    assert len(names) == 20


def test_blueprint_names_zero_walkers_returns_empty_list():
    pool = [f"walker.pedestrian.{i:04d}" for i in range(10)]
    assert pick_walker_blueprint_names(0, pool, seed=0) == []


def test_blueprint_names_empty_pool_raises():
    with pytest.raises(ValueError):
        pick_walker_blueprint_names(n_walkers=5, available_bp_names=[], seed=0)


def test_blueprint_names_negative_raises():
    pool = ["walker.pedestrian.0001"]
    with pytest.raises(ValueError):
        pick_walker_blueprint_names(n_walkers=-1, available_bp_names=pool, seed=0)


def test_blueprint_names_deterministic_with_same_seed():
    pool = [f"walker.pedestrian.{i:04d}" for i in range(40)]
    a = pick_walker_blueprint_names(20, pool, seed=7)
    b = pick_walker_blueprint_names(20, pool, seed=7)
    assert a == b


def test_blueprint_names_sample_with_replacement_handles_pool_smaller_than_n():
    # We may need more walkers than CARLA's pool size; sampling with
    # replacement should still work and never raise.
    pool = ["walker.pedestrian.0001", "walker.pedestrian.0002"]
    names = pick_walker_blueprint_names(n_walkers=20, available_bp_names=pool, seed=0)
    assert len(names) == 20
    assert all(n in pool for n in names)


def test_blueprint_names_all_drawn_from_pool():
    pool = [f"walker.pedestrian.{i:04d}" for i in range(40)]
    names = pick_walker_blueprint_names(n_walkers=100, available_bp_names=pool, seed=11)
    assert set(names).issubset(set(pool))
