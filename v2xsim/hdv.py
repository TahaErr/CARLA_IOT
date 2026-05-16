"""Human-driver behaviour profiles for CARLA Traffic Manager (Sprint 4 module 3).

Implements proposal §4.1.2 — the heterogeneous-driver mix that lets us
measure V2X benefit in mixed traffic. Without these profiles every NPC
vehicle runs default Traffic Manager rules (rule-compliant, well-spaced,
near-zero collision rate), and there is no safety benefit for V2X to
provide. Distracted + aggressive drivers create the genuine conflicts
that confirmed CPM tracks help the CAV avoid.

Default mix is from NHTSA-style observational categories:
  - **attentive (70%)**: rule-compliant, default TM behaviour
  - **distracted (20%)**: occasional rule misses + slower reactions
  - **aggressive (10%)**: closer following, faster, more rule violations

Numbers below are calibrated heuristically — small enough that vanilla
TM still does most of the driving, large enough that conflicts emerge
within a few minutes of simulated traffic. Tunable per ablation if
proposal §4.1.2's calibration needs revisiting in the deliverable.

Pure data + thin Traffic Manager wrapper. No CARLA imports at module
load (TM is a typed argument); fully unit-testable with a mock TM.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import numpy as np


@dataclass(frozen=True)
class DriverProfile:
    """Behavioural parameters for one driver class.

    All `*_pct` fields are percentages (0..100) interpreted by CARLA's
    Traffic Manager as "fraction of decision events where this rule
    is ignored or violated". `speed_difference_pct` is signed: negative
    drives below speed limit, positive drives above.
    """
    name: str
    speed_difference_pct: float            # -100..+100; signed
    distance_to_leading_m: float           # minimum following distance
    ignore_lights_pct: float
    ignore_signs_pct: float
    ignore_vehicles_pct: float
    ignore_walkers_pct: float
    random_left_lanechange_pct: float
    random_right_lanechange_pct: float


# === Three NHTSA-style profiles ===========================================

ATTENTIVE = DriverProfile(
    name="attentive",
    speed_difference_pct=0.0,
    distance_to_leading_m=2.5,
    ignore_lights_pct=0.0,
    ignore_signs_pct=0.0,
    ignore_vehicles_pct=0.0,
    ignore_walkers_pct=0.0,
    random_left_lanechange_pct=0.0,
    random_right_lanechange_pct=0.0,
)

DISTRACTED = DriverProfile(
    name="distracted",
    speed_difference_pct=-10.0,            # slower than limit on average
    distance_to_leading_m=2.0,
    ignore_lights_pct=5.0,
    ignore_signs_pct=10.0,
    ignore_vehicles_pct=10.0,
    ignore_walkers_pct=10.0,
    random_left_lanechange_pct=2.0,
    random_right_lanechange_pct=2.0,
)

AGGRESSIVE = DriverProfile(
    name="aggressive",
    speed_difference_pct=20.0,             # over speed limit
    distance_to_leading_m=1.0,             # tailgating
    ignore_lights_pct=15.0,
    ignore_signs_pct=20.0,
    ignore_vehicles_pct=5.0,
    ignore_walkers_pct=0.0,                # aggressive ≠ careless w/ pedestrians
    random_left_lanechange_pct=10.0,
    random_right_lanechange_pct=10.0,
)


# === Hostile profile + mix ================================================
#
# `AGGRESSIVE` above is calibrated to be qualitatively realistic in mixed
# traffic. For *safety ablations* we need stronger conflict generation —
# without it, CARLA Traffic Manager's built-in collision avoidance keeps
# the baseline at zero collisions and the V2X benefit is unmeasurable.
#
# `AGGRESSIVE_HOSTILE` and `HOSTILE_MIX` below are calibrated empirically
# to produce non-zero baseline collision rates in 2-minute Town05 runs
# (see Sprint 4 module 5 ablation deliverable). Use these only in the
# ablation runner, never in user-facing demos.

AGGRESSIVE_HOSTILE = DriverProfile(
    name="aggressive_hostile",
    speed_difference_pct=25.0,             # well over limit
    distance_to_leading_m=2.0,             # tighter than ATTENTIVE (2.5) but not bumper-stuck.
                                           # 0.8 caused mass pileups at spawn — physical contact
                                           # at the spawn instant locked entire intersections.
    ignore_lights_pct=50.0,
    ignore_signs_pct=60.0,
    ignore_vehicles_pct=10.0,              # 2× AGGRESSIVE — softened from 30 to limit collision-event flood
    ignore_walkers_pct=20.0,
    random_left_lanechange_pct=25.0,
    random_right_lanechange_pct=25.0,
)


# Proposal §4.1.2 default population mix.
DEFAULT_MIX: tuple[tuple[DriverProfile, float], ...] = (
    (ATTENTIVE,  0.70),
    (DISTRACTED, 0.20),
    (AGGRESSIVE, 0.10),
)


# Hostile mix for safety ablations only. 50/20/30 weighting.
HOSTILE_MIX: tuple[tuple[DriverProfile, float], ...] = (
    (ATTENTIVE,           0.50),
    (DISTRACTED,          0.20),
    (AGGRESSIVE_HOSTILE,  0.30),
)


# === Assignment ===========================================================

def assign_profiles(
    vehicles: list,
    mix: tuple = DEFAULT_MIX,
    rng: Optional[np.random.Generator] = None,
) -> dict[int, DriverProfile]:
    """Assign each vehicle one profile via weighted random sample.

    Args:
        vehicles: list of CARLA actor objects (anything with a `.id` attr).
        mix: tuple of (DriverProfile, weight) pairs. Weights need not sum
            to 1.0 — they're normalised here.
        rng: numpy Generator for reproducibility. Defaults to a fresh
            unseeded generator if None.

    Returns:
        dict mapping actor.id → DriverProfile. Caller decides whether to
        apply right away via `apply_profile_to_tm`, or just store for
        later (e.g., per-tick logging of which profiles were involved
        in collisions).
    """
    if rng is None:
        rng = np.random.default_rng()
    if not mix:
        raise ValueError("mix must be non-empty")
    if any(w < 0 for _, w in mix):
        raise ValueError("mix weights must be non-negative")
    profiles = [p for p, _ in mix]
    weights = np.array([w for _, w in mix], dtype=float)
    total = weights.sum()
    if total <= 0:
        raise ValueError("mix weights must have positive sum")
    weights /= total
    assignments: dict[int, DriverProfile] = {}
    for v in vehicles:
        idx = rng.choice(len(profiles), p=weights)
        assignments[v.id] = profiles[idx]
    return assignments


# === Traffic Manager binding ==============================================

def apply_profile_to_tm(tm: Any, vehicle: Any, profile: DriverProfile) -> None:
    """Push one profile's parameters into one vehicle via Traffic Manager.

    `tm` is a `carla.TrafficManager` instance. Each TM method below maps
    one profile field to the corresponding behavioural knob. We call them
    explicitly (not via setattr) so failures stay readable at the call site.
    """
    tm.vehicle_percentage_speed_difference(vehicle, profile.speed_difference_pct)
    tm.distance_to_leading_vehicle(vehicle, profile.distance_to_leading_m)
    tm.ignore_lights_percentage(vehicle, profile.ignore_lights_pct)
    tm.ignore_signs_percentage(vehicle, profile.ignore_signs_pct)
    tm.ignore_vehicles_percentage(vehicle, profile.ignore_vehicles_pct)
    tm.ignore_walkers_percentage(vehicle, profile.ignore_walkers_pct)
    tm.random_left_lanechange_percentage(vehicle, profile.random_left_lanechange_pct)
    tm.random_right_lanechange_percentage(vehicle, profile.random_right_lanechange_pct)


def apply_mix_to_vehicles(
    tm: Any,
    vehicles: list,
    mix: tuple = DEFAULT_MIX,
    rng: Optional[np.random.Generator] = None,
) -> dict[int, str]:
    """Combined convenience: assign profiles + push them to the TM.

    Returns a {actor_id: profile_name} dict for caller logging — useful
    when later attributing a collision to a particular driver class in
    the metric infrastructure (Sprint 4 Module 4).
    """
    assignments = assign_profiles(vehicles, mix, rng)
    for v in vehicles:
        apply_profile_to_tm(tm, v, assignments[v.id])
    return {actor_id: p.name for actor_id, p in assignments.items()}


# === TM collision detection control =======================================

def disable_tm_collision_detection(tm: Any, vehicles: list) -> int:
    """Tell Traffic Manager to ignore vehicle-vehicle collision avoidance
    between every pair in the given list.

    By default CARLA Traffic Manager applies its own collision-avoidance
    layer on top of every autopilot decision — this keeps NPC traffic
    looking sensible but hides driver-profile differences in the
    collision-count metric. For safety ablations we disable this layer
    so the per-profile ignore_*_pct parameters actually produce
    measurable collisions.

    Returns the number of (ordered) pairs configured.
    """
    n_pairs = 0
    for v in vehicles:
        for other in vehicles:
            if v.id == other.id:
                continue
            tm.collision_detection(v, other, False)
            n_pairs += 1
    return n_pairs
