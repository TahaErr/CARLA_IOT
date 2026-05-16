"""Walker (pedestrian) spawn and AI orchestration for CARLA ablations.

Implements the VRU axis of proposal §2.2 and §4.7. Sprint 4's initial
ablations were vehicle-only; this module adds pedestrians so the V2X
benefit on Vulnerable Road User (VRU) safety can be measured separately
from vehicle-on-vehicle collisions.

Design choices:

* **Batch spawn via `client.apply_batch_sync`.** Mirrors the official
  CARLA pattern in `PythonAPI/examples/generate_traffic.py`. Sequential
  per-actor `world.spawn_actor` calls under sync mode were observed to
  trigger UE4 "Pure virtual function called" fatal errors when the
  walker controller is attached to the walker actor — CARLA's own
  recipes use 2-phase batch spawn for exactly this reason. See the
  CARLA docs: "Commands should be batched instead of issued one at a
  time" (https://carla.readthedocs.io/en/latest/adv_synchrony_timestep/).
* **Two-phase initialisation.** Phase 1 spawns walker actors, phase 2
  spawns controllers attached to those actors, both as batches. A
  `world.tick()` between phase 2 and `start_walker_controllers` is
  mandatory; without it CARLA 0.9.16 can crash on the first controller
  call (cf. carla-simulator/carla issue #4350).
* **Target speed.** Per-walker Gaussian sampling around the NHTSA mean
  pedestrian walking speed (1.4 m/s, sigma 0.3), clipped to
  [0.5, 2.5] m/s. Captures elderly to brisk-crosswalk-dash diversity.
* **Spawn anchoring.** Walkers are anchored to intersection centroids
  with a radius (default 50 m) so they enter the RSU camera frustums.
  Matches the Sprint 2 dataset generator pattern.
* **Deterministic.** Every random draw is seeded; same seed gives the
  same population every run.

CARLA imports are lazy (inside the spawn function) so the pure-data
helpers (`pick_walker_target_speeds`) remain unit-testable without
CARLA on the host.
"""
from __future__ import annotations

from typing import Any

import numpy as np


# NHTSA-derived pedestrian walking-speed distribution.
WALKER_MEAN_SPEED_MS = 1.4
WALKER_SPEED_SIGMA_MS = 0.3
WALKER_SPEED_MIN_MS = 0.5
WALKER_SPEED_MAX_MS = 2.5


def pick_walker_target_speeds(n_walkers: int, seed: int) -> list[float]:
    """Deterministic per-walker target-speed sampling (NHTSA-anchored)."""
    if n_walkers < 0:
        raise ValueError(f"n_walkers must be non-negative, got {n_walkers}")
    if n_walkers == 0:
        return []
    rng = np.random.default_rng(seed)
    raw = rng.normal(
        loc=WALKER_MEAN_SPEED_MS,
        scale=WALKER_SPEED_SIGMA_MS,
        size=n_walkers,
    )
    clipped = np.clip(raw, WALKER_SPEED_MIN_MS, WALKER_SPEED_MAX_MS)
    return [float(v) for v in clipped]


def pick_walker_blueprint_names(
    n_walkers: int,
    available_bp_names: list[str],
    seed: int,
) -> list[str]:
    """Deterministic per-walker blueprint name selection (with replacement)."""
    if n_walkers < 0:
        raise ValueError(f"n_walkers must be non-negative, got {n_walkers}")
    if n_walkers == 0:
        return []
    if not available_bp_names:
        raise ValueError("available_bp_names is empty — no walker blueprints loaded?")
    rng = np.random.default_rng(seed)
    idx = rng.integers(low=0, high=len(available_bp_names), size=n_walkers)
    return [available_bp_names[int(i)] for i in idx]


# === CARLA-bound batch spawn ==============================================

def spawn_walkers_near_intersections(
    client: Any,                         # carla.Client
    world: Any,                          # carla.World
    intersection_centroids: list[tuple[float, float, float]],
    n_walkers: int,
    radius_m: "float | None" = None,
    seed: int = 0,
    max_location_attempts: int = 50,
) -> tuple[list, list]:
    """Batch-spawn walkers and their AI controllers (official CARLA pattern).

    Uses CARLA's `client.apply_batch_sync` in two phases — first all
    walker actors, then all controller actors attached to them. This
    is the pattern in `PythonAPI/examples/generate_traffic.py` and the
    only one safe under synchronous mode (per-actor sequential spawn
    triggers UE4 Pure virtual function fatals).

    Spawn-location strategy:
      * `radius_m = None` (default): walkers are placed at any walkable
        nav-mesh point — i.e. map-wide. This is the realistic urban
        scenario: pedestrian density distributed across the whole town,
        not artificially concentrated at the 3 RSU intersections. The
        V2X benefit is then evaluated on whichever subset enters RSU
        camera frustums during the run.
      * `radius_m = float`: legacy behaviour. Walkers are constrained
        to within `radius_m` of one of the supplied intersection
        centroids (round-robin). Useful for synthetic stress tests but
        not for thesis ablation runs.

    Args:
        client: connected `carla.Client` (needed for `apply_batch_sync`).
        world: `client.get_world()` result (for blueprint lib + nav mesh).
        intersection_centroids: (x, y, z) tuples; consumed only when
            `radius_m is not None`. Always required for API stability
            but ignored in map-wide mode.
        n_walkers: target walker count.
        radius_m: see strategy notes above.
        seed: RNG seed for deterministic walker placement.
        max_location_attempts: nav-mesh sample retries per walker slot
            (only meaningful in radius mode).

    Returns:
        (walker_actors, controller_actors): parallel lists, each entry
        a CARLA actor object. Length may be less than `n_walkers` if
        CARLA rejected some spawns (off-mesh, collision). Each
        controller has its target speed stashed as
        `_v2xsim_target_speed` for later `start_walker_controllers`.
    """
    import carla  # lazy

    if n_walkers <= 0:
        return [], []
    if radius_m is not None and not intersection_centroids:
        raise ValueError(
            "intersection_centroids must be non-empty when radius_m is set"
        )

    SpawnActor = carla.command.SpawnActor

    bp_lib = world.get_blueprint_library()
    walker_bps_query = bp_lib.filter("walker.pedestrian.*")
    if not walker_bps_query:
        raise RuntimeError(
            "No walker.pedestrian.* blueprints found in this CARLA build "
            "(unexpected for 0.9.16 — verify the install)."
        )
    walker_bp_names = [bp.id for bp in walker_bps_query]
    chosen_bp_names = pick_walker_blueprint_names(n_walkers, walker_bp_names, seed)
    target_speeds = pick_walker_target_speeds(n_walkers, seed + 1)

    # === Phase 1: pick nav-mesh spawn locations =========================
    # In map-wide mode (radius_m is None) we just accept any walkable
    # point from `get_random_location_from_navigation()`. In radius mode
    # we bias toward an intersection centroid and reject points outside
    # the radius (with a per-walker retry budget).
    spawn_slots: list[tuple] = []  # list of (location, blueprint_idx)
    for i in range(n_walkers):
        found = None
        if radius_m is None:
            # Map-wide: one sample is usually enough; one retry if None.
            for _attempt in range(3):
                loc = world.get_random_location_from_navigation()
                if loc is not None:
                    found = loc
                    break
        else:
            cx, cy, _cz = intersection_centroids[i % len(intersection_centroids)]
            for _attempt in range(max_location_attempts):
                loc = world.get_random_location_from_navigation()
                if loc is None:
                    continue
                dx = loc.x - cx
                dy = loc.y - cy
                if (dx * dx + dy * dy) ** 0.5 <= radius_m:
                    found = loc
                    break
            if found is None:
                # Last resort: any walkable point.
                found = world.get_random_location_from_navigation()
        if found is not None:
            spawn_slots.append((found, i))

    if not spawn_slots:
        return [], []

    # === Phase 2: batch-spawn walker actors =============================
    batch = []
    for loc, i in spawn_slots:
        bp = bp_lib.find(chosen_bp_names[i])
        # Make walkers killable so vehicle-on-pedestrian collisions
        # register as physical events (not bounce-offs).
        if bp.has_attribute("is_invincible"):
            bp.set_attribute("is_invincible", "false")
        batch.append(SpawnActor(bp, carla.Transform(loc)))

    results = client.apply_batch_sync(batch, True)
    walker_ids: list[int] = []
    walker_target_speeds: list[float] = []
    for (loc, i), r in zip(spawn_slots, results):
        if r.error:
            # CARLA logs the error to its own console; just skip this slot.
            continue
        walker_ids.append(r.actor_id)
        walker_target_speeds.append(target_speeds[i])

    if not walker_ids:
        return [], []

    # === Phase 3: batch-spawn AI controllers attached to walkers ========
    controller_bp = bp_lib.find("controller.ai.walker")
    batch = [
        SpawnActor(controller_bp, carla.Transform(), wid)
        for wid in walker_ids
    ]
    results = client.apply_batch_sync(batch, True)
    controller_ids: list[int] = []
    matched_walker_ids: list[int] = []
    matched_speeds: list[float] = []
    for (wid, speed), r in zip(zip(walker_ids, walker_target_speeds), results):
        if r.error:
            continue
        controller_ids.append(r.actor_id)
        matched_walker_ids.append(wid)
        matched_speeds.append(speed)

    if not controller_ids:
        # Walker actors exist but controller attach failed — clean up
        # the orphans so they don't leak into the simulation.
        client.apply_batch([carla.command.DestroyActor(wid) for wid in walker_ids])
        return [], []

    # === Phase 4: resolve ids to actor objects =========================
    all_actors = world.get_actors(matched_walker_ids + controller_ids)
    actor_by_id = {a.id: a for a in all_actors}
    walkers = [actor_by_id[wid] for wid in matched_walker_ids if wid in actor_by_id]
    controllers = [actor_by_id[cid] for cid in controller_ids if cid in actor_by_id]

    # Stash target speeds on the controllers for start_walker_controllers.
    for c, speed in zip(controllers, matched_speeds):
        try:
            c._v2xsim_target_speed = speed
        except Exception:
            # Some CARLA actor subclasses are __slots__-only; just live
            # with the NHTSA mean if we can't attach the attribute.
            pass

    # Phase 5: set pedestrian crossing factor world-wide.
    # CARLA default is 0 — walkers never leave the sidewalk and so
    # never create vehicle-pedestrian conflicts. For VRU collision
    # ablations we need walkers to actually use crosswalks (and
    # occasionally jaywalk). NHTSA urban field studies report 40-60%
    # of pedestrians crossing at any given time during peak hours;
    # 0.5 is in the middle of that range.
    try:
        world.set_pedestrians_cross_factor(0.5)
    except Exception:
        # Older CARLA builds might not have this API. Not fatal —
        # walkers will just be sidewalk-only.
        pass

    return walkers, controllers


def start_walker_controllers(controllers: list, world: Any) -> None:
    """Start every AI controller and apply its target speed.

    Must be called AFTER at least one `world.tick()` has been run since
    the walkers were spawned, otherwise CARLA leaves the walkers frozen
    in their default pose (and may crash on the first start() call).
    The pattern in `40_ablation_run.py` is:

        walkers, controllers = spawn_walkers_near_intersections(...)
        world.tick()                              # sync after spawn
        for _ in range(40):
            world.tick()                          # warm-up
        start_walker_controllers(controllers, world)

    Args:
        controllers: list returned by `spawn_walkers_near_intersections`.
        world: connected carla.World (used to read nav-mesh random
            points for goal selection).
    """
    for controller in controllers:
        try:
            controller.start()
            goal = world.get_random_location_from_navigation()
            if goal is not None:
                controller.go_to_location(goal)
            speed = getattr(controller, "_v2xsim_target_speed", WALKER_MEAN_SPEED_MS)
            controller.set_max_speed(float(speed))
        except Exception:
            # Sequential start; one bad controller shouldn't block the rest.
            continue


def stop_walker_controllers(controllers: list) -> None:
    """Stop every AI controller. Call before destroy in cleanup."""
    for controller in controllers:
        try:
            controller.stop()
        except Exception:
            pass
