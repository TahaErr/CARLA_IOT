"""scripts/40_ablation_run.py — Sprint 4 mini ablation runner.

Executes proposal §4.6's V2X-penetration sweep: 3 cells × N seeds in
Town05 with 3 fixed RSUs (intersections 0/3/7), 40 vehicles, HDV mix
(70/20/10 attentive/distracted/aggressive), 5-min sim per cell.

Penetration sweep:
  - p = 0.0  : baseline. No CAVs; HDV-only traffic.
  - p = 0.5  : half the spawned vehicles are V2X-equipped CAVs.
  - p = 1.0  : every spawned vehicle is a CAV.

Per-run output: one JSON in `--out-dir` with collision counts, action
histogram, phantom-brake-suppression count, CBR samples, and decode
error counters. Aggregator (Module 5b) reads these and produces the
thesis-ready summary CSV + figures.

Usage:
    :: Single run:
    python scripts\\40_ablation_run.py ^
        --detector runs\\detect\\runs\\detect\\yolo26s_carla_multi-2\\weights\\best.pt ^
        --penetration 0.5 --seed 42 --out out\\ablation\\p050_s42.json

    :: Full 3 × 10 sweep:
    python scripts\\40_ablation_run.py --sweep ^
        --detector runs\\detect\\runs\\detect\\yolo26s_carla_multi-2\\weights\\best.pt ^
        --out-dir out\\ablation

The --sweep mode iterates p ∈ {0.0, 0.5, 1.0} × seed ∈ {0..n_seeds-1}.
Use --skip-existing to resume an interrupted sweep without redoing
completed cells.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

import carla
import numpy as np

from v2xsim.broker import Broker
from v2xsim.carla_cav import CarlaCAV
from v2xsim.carla_rsu import CarlaRSU
from v2xsim.carla_utils import connect, ensure_map, synchronous_mode
from v2xsim.cav import Action
from v2xsim.compute_budget import unconstrained_profile
from v2xsim.hdv import HOSTILE_MIX, apply_mix_to_vehicles, disable_tm_collision_detection
from v2xsim.intersections import discover_intersections
from v2xsim.latency import LatencyModel
from v2xsim.pdr import PDRModel


# === Small helpers ========================================================

def _distance_2d(p1, p2):
    return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5


def _spawn_vehicles(world, tm, n, rng):
    """Spawn up to `n` autopilot vehicles. Returns list of carla.Vehicle."""
    bp_lib = world.get_blueprint_library()
    vehicle_bps = list(bp_lib.filter("vehicle.*"))
    spawn_points = list(world.get_map().get_spawn_points())
    rng.shuffle(spawn_points)
    spawned = []
    for i, sp in enumerate(spawn_points[:n]):
        bp = vehicle_bps[i % len(vehicle_bps)]
        try:
            v = world.spawn_actor(bp, sp)
            v.set_autopilot(True, tm.get_port())
            spawned.append(v)
        except RuntimeError:
            continue
    return spawned


def _attach_collision_sensor(world, vehicle, on_collision):
    bp = world.get_blueprint_library().find("sensor.other.collision")
    sensor = world.spawn_actor(bp, carla.Transform(), attach_to=vehicle)
    sensor.listen(on_collision)
    return sensor


def _apply_decision(vehicle, action):
    """Translate CAVDecision.action to a carla.VehicleControl override.

    HARD_BRAKE / SOFT_BRAKE / DECELERATE override autopilot for this
    one tick. NONE returns control to Traffic Manager (no apply_control).
    """
    if action == Action.HARD_BRAKE:
        vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0))
    elif action == Action.SOFT_BRAKE:
        vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=0.5))
    elif action == Action.DECELERATE:
        vehicle.apply_control(carla.VehicleControl(throttle=0.2, brake=0.0))
    # Action.NONE: no override


def _count_profile_assignments(assignments: dict) -> dict:
    counts: dict[str, int] = {}
    for name in assignments.values():
        counts[name] = counts.get(name, 0) + 1
    return counts


# === Single run ==========================================================

def run_single(args, penetration: float, seed: int) -> dict:
    """Execute one ablation cell.

    Returns a metrics dict ready to be JSON-serialised. Cleans up actors
    in `finally`. Reraises any exception to the caller (--sweep level
    catches and continues).
    """
    random.seed(seed)
    np.random.seed(seed)
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    client = connect(args.host, args.port)
    world = ensure_map(client, args.map)

    intersections = discover_intersections(world)
    target_idx = [0, 3, 7]
    target_intersections = [intersections[i] for i in target_idx]

    broker = Broker(
        latency=LatencyModel(rng=np.random.default_rng(seed + 100)),
        pdr=PDRModel(rng=np.random.default_rng(seed + 200)),
        cbr_window_ms=1000.0,
    )
    budget = unconstrained_profile(n_rsus=len(target_intersections))

    rsus: list = []
    rsu_positions: list = []
    vehicles: list = []
    cavs: list = []
    collision_sensors: list = []
    collision_events: list = []
    current_sim_time = [0.0]  # mutable closure for callback timestamps

    try:
        with synchronous_mode(client) as (world, tm):
            world.tick()

            # === RSUs ==================================================
            for target in target_intersections:
                rsu = CarlaRSU(
                    world=world,
                    intersection=target,
                    light_idx=0,
                    broker=broker,
                    detector_path=args.detector,
                    station_id=target.id,
                    compute_budget=budget,
                    image_size=(args.image_w, args.image_h),
                    fov_deg=args.fov,
                    confidence_threshold=args.conf,
                    device=args.device,
                )
                rsus.append(rsu)
                light_loc = target.lights[0].get_location()
                rsu_positions.append((light_loc.x, light_loc.y))

            # === Vehicles + HDV mix ====================================
            vehicles = _spawn_vehicles(world, tm, args.n_vehicles, rng)
            world.tick()
            # HOSTILE_MIX (50/20/30) is calibrated for safety ablations
            # where the baseline must have non-zero collisions for the
            # V2X-benefit metric to be measurable.
            hdv_assignments = apply_mix_to_vehicles(
                tm, vehicles, mix=HOSTILE_MIX, rng=np_rng,
            )
            # IMPORTANT: TM collision-detection-disable is moved to AFTER
            # warmup. Disabling at spawn time produced mass pileups
            # because vehicles arrive packed and have no chance to spread
            # before mutual avoidance is removed. Warm up first, then
            # disable.

            # === CAVs ==================================================
            n_cavs = int(round(penetration * len(vehicles)))
            cav_vehicles = rng.sample(vehicles, n_cavs) if n_cavs > 0 else []
            cav_actor_ids: set = set()
            for v in cav_vehicles:
                cav = CarlaCAV(
                    vehicle=v,
                    broker=broker,
                    local_sensor_enabled=True,
                    local_sensor_range_m=50.0,
                    local_sensor_angle_deg=90.0,
                )
                for rsu_id, rsu_xy in zip(
                    [str(t.id) for t in target_intersections],
                    rsu_positions,
                ):
                    cav.register_rsu(rsu_id, rsu_xy)
                cavs.append(cav)
                cav_actor_ids.add(v.id)

            # === Collision sensors on EVERY vehicle ==================
            # We attach a collision sensor to every spawned vehicle, not
            # just CAVs, so that baseline (p=0) runs still report HDV-HDV
            # collisions.
            #
            # IMPORTANT: the listener runs on a CARLA-side thread. Doing
            # *any* attribute access on `event.other_actor` beyond `.id`
            # has been observed to crash CARLA on Windows when the other
            # actor is destroyed near the end of the run (`type_id` in
            # particular causes STATUS_STACK_BUFFER_OVERRUN). Mirror the
            # bisect-step-2 callback exactly: capture only the IDs and
            # the simulation time. All per-vehicle metadata (is_cav,
            # profile, type) is looked up post-loop via local dicts.
            vehicle_profile: dict[int, str] = dict(hdv_assignments)
            vehicle_is_cav: dict[int, bool] = {v.id: (v.id in cav_actor_ids) for v in vehicles}

            def _make_listener(vehicle_id: int):
                def listener(event):
                    try:
                        collision_events.append((
                            current_sim_time[0],
                            vehicle_id,
                            event.other_actor.id,
                        ))
                    except Exception:
                        # Never block the listener thread on anything.
                        pass
                return listener

            for v in vehicles:
                sensor = _attach_collision_sensor(world, v, _make_listener(v.id))
                collision_sensors.append(sensor)

            # === Warmup ================================================
            # Run the 40-tick warmup with TM collision detection still
            # ENABLED, so vehicles spread out from their spawn clusters
            # before we remove the avoidance layer.
            for _ in range(40):
                world.tick()

            # === Disable TM collision detection (after warmup) =========
            # NOW the vehicles have dispersed; we can disable mutual
            # avoidance so the per-driver ignore_*_pct knobs actually
            # produce measurable collisions instead of being masked by
            # TM's built-in safety net.
            disable_tm_collision_detection(tm, vehicles)
            world.tick()

            # === Main loop =============================================
            sim_dt_ms = 50.0
            cpm_period_ticks = 2  # 100 ms CPM rate
            n_ticks = int(args.duration / 0.05)

            action_counts = {a.value: 0 for a in Action}
            phantom_brakes_suppressed = 0
            cbr_samples: list = []
            n_publishes_attempted = 0
            n_publishes_emitted = 0
            n_publishes_dropped = 0
            dead_cav_ids: set = set()  # CAVs whose CARLA actor was destroyed

            wall_t0 = time.time()
            for tick in range(n_ticks):
                world.tick()
                sim_time_ms = tick * sim_dt_ms
                current_sim_time[0] = sim_time_ms

                # --- RSU publishes once per CPM period --------------
                if tick % cpm_period_ticks == 0:
                    budget.reset_window()
                    for rsu, rsu_pos in zip(rsus, rsu_positions):
                        receivers: list = []
                        for cav in cavs:
                            if cav.id in dead_cav_ids:
                                continue
                            try:
                                v_loc = cav.actor.get_location()
                            except RuntimeError:
                                dead_cav_ids.add(cav.id)
                                continue
                            d = _distance_2d(rsu_pos, (v_loc.x, v_loc.y))
                            if d <= args.max_range:
                                receivers.append((cav.id, d))
                        n_publishes_attempted += 1
                        if rsu.tick(sim_time_ms, receivers):
                            n_publishes_emitted += 1
                        else:
                            n_publishes_dropped += 1

                # --- CAV decisions every sim tick -------------------
                if cavs:
                    other_actors = [
                        a for a in world.get_actors()
                        if (a.type_id.startswith("vehicle.") or
                            a.type_id.startswith("walker."))
                    ]
                    for cav in cavs:
                        if cav.id in dead_cav_ids:
                            continue
                        try:
                            decision = cav.tick(sim_time_ms, other_actors)
                        except RuntimeError as e:
                            if "destroyed actor" in str(e):
                                dead_cav_ids.add(cav.id)
                                continue
                            raise
                        if decision is None:
                            # CarlaCAV reported itself dead via internal guard.
                            dead_cav_ids.add(cav.id)
                            continue
                        action_counts[decision.action.value] += 1
                        if decision.phantom_brake_suppressed:
                            phantom_brakes_suppressed += 1
                        try:
                            _apply_decision(cav.actor, decision.action)
                        except RuntimeError:
                            dead_cav_ids.add(cav.id)

                # --- CBR sample every sim-second --------------------
                if tick % 20 == 0:
                    cbr_samples.append(broker.channel_busy_ratio(sim_time_ms=sim_time_ms))

                # --- Progress every ~10 sim seconds -----------------
                if (tick + 1) % 200 == 0 and not args.quiet:
                    wall = time.time() - wall_t0
                    sim = (tick + 1) * 0.05
                    print(f"    tick {tick+1:5d}/{n_ticks}  "
                          f"sim={sim:5.0f}s wall={wall:5.0f}s  "
                          f"emit={n_publishes_emitted:4d}  "
                          f"collisions={len(collision_events):3d}")

            wall_total = time.time() - wall_t0

            # === Aggregation ===========================================
            cbr_mean = float(np.mean(cbr_samples)) if cbr_samples else 0.0
            cbr_max = float(np.max(cbr_samples)) if cbr_samples else 0.0

            # Apply per-pair 1-second deduplication after the simulation.
            # CARLA's collision sensor fires once per contact frame while
            # contact persists; for the reported metric we want distinct
            # incidents, not contact-frame counts.
            COLLISION_DEDUP_WINDOW_MS = 1000.0
            last_collision: dict[tuple[int, int], float] = {}
            deduped_events: list[tuple] = []
            for ev in collision_events:
                sim_t, v_id, other_id = ev
                key = (v_id, other_id)
                prev = last_collision.get(key)
                if prev is not None and (sim_t - prev) < COLLISION_DEDUP_WINDOW_MS:
                    continue
                last_collision[key] = sim_t
                deduped_events.append(ev)

            # Look up per-vehicle metadata from the local maps built before
            # the loop — never touch the now-destroyed CARLA actors.
            cav_collisions = 0
            collisions_per_profile: dict[str, int] = {}
            for sim_t, v_id, other_id in deduped_events:
                if vehicle_is_cav.get(v_id, False):
                    cav_collisions += 1
                p = vehicle_profile.get(v_id, "unknown")
                collisions_per_profile[p] = collisions_per_profile.get(p, 0) + 1
            hdv_collisions = len(deduped_events) - cav_collisions
            decode_errors = sum(c.decode_errors for c in cavs)

            return {
                "config": {
                    "map": args.map,
                    "intersections": target_idx,
                    "penetration": penetration,
                    "seed": seed,
                    "n_vehicles": len(vehicles),
                    "n_cavs": len(cavs),
                    "duration_s": args.duration,
                    "max_range_m": args.max_range,
                    "local_sensor_enabled": True,
                    "local_sensor_range_m": 50.0,
                    "local_sensor_angle_deg": 90.0,
                },
                "wall_seconds": wall_total,
                "sim_seconds": args.duration,
                "wall_to_sim_ratio": wall_total / max(args.duration, 1e-9),
                "publishes_attempted": n_publishes_attempted,
                "publishes_emitted": n_publishes_emitted,
                "publishes_dropped": n_publishes_dropped,
                "cbr_mean": cbr_mean,
                "cbr_max": cbr_max,
                "collision_count": len(deduped_events),
                "raw_collision_events": len(collision_events),
                "cav_collision_count": cav_collisions,
                "hdv_collision_count": hdv_collisions,
                "collisions_per_profile": collisions_per_profile,
                "actions_taken": action_counts,
                "phantom_brakes_suppressed": phantom_brakes_suppressed,
                "dead_cav_count": len(dead_cav_ids),
                "decode_errors": decode_errors,
                "hdv_profile_counts": _count_profile_assignments(hdv_assignments),
            }

    finally:
        # Cleanup in reverse spawn order.
        for s in collision_sensors:
            try: s.stop()
            except Exception: pass
            try: s.destroy()
            except Exception: pass
        for r in rsus:
            try: r.destroy()
            except Exception: pass
        for v in vehicles:
            try: v.destroy()
            except Exception: pass


# === Sweep mode ==========================================================

def run_sweep(args) -> int:
    """Iterate 3 penetration × n_seeds = 3·n_seeds runs."""
    os.makedirs(args.out_dir, exist_ok=True)

    penetrations = [0.0, 0.5, 1.0]
    seeds = list(range(args.n_seeds))
    total = len(penetrations) * len(seeds)
    done = 0
    crashed = 0

    print(f"=== Sweep: {len(penetrations)} penetration × {len(seeds)} seeds "
          f"= {total} runs of {args.duration:.0f}s each ===")
    sweep_t0 = time.time()

    for p in penetrations:
        for seed in seeds:
            done += 1
            out_path = os.path.join(
                args.out_dir,
                f"p{int(p * 100):03d}_s{seed:02d}.json",
            )
            if args.skip_existing and os.path.exists(out_path):
                print(f"[{done}/{total}] SKIP existing: {out_path}")
                continue

            print(f"\n[{done}/{total}] === run p={p} seed={seed} → {out_path}")
            try:
                metrics = run_single(args, penetration=p, seed=seed)
                metrics["status"] = "ok"
                print(f"   ok — collisions={metrics['collision_count']} "
                      f"(cav={metrics['cav_collision_count']} hdv={metrics['hdv_collision_count']})  "
                      f"phantom_brakes_suppressed={metrics['phantom_brakes_suppressed']}")
            except Exception as e:
                crashed += 1
                metrics = {
                    "status": "crashed",
                    "error": repr(e),
                    "config": {"penetration": p, "seed": seed},
                }
                print(f"   CRASHED: {e}", file=sys.stderr)

            with open(out_path, "w") as f:
                json.dump(metrics, f, indent=2, default=str)

    elapsed = time.time() - sweep_t0
    print(f"\n=== Sweep complete in {elapsed/60:.1f} min "
          f"({done} runs, {crashed} crashed) ===")
    print(f"Aggregate with: python scripts\\41_ablation_aggregate.py --in-dir {args.out_dir}")
    return 0 if crashed == 0 else 2


# === Main ================================================================

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=2000)
    p.add_argument("--map", default="Town05")
    p.add_argument("--detector", required=True)

    # single-run mode
    p.add_argument("--penetration", type=float, default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--out", default=None)

    # sweep mode
    p.add_argument("--sweep", action="store_true")
    p.add_argument("--out-dir", default="out/ablation")
    p.add_argument("--n-seeds", type=int, default=5,
                   help="seeds per penetration cell (default 5)")
    p.add_argument("--skip-existing", action="store_true")

    # common
    p.add_argument("--duration", type=float, default=120.0,
                   help="simulation seconds per run (default 120 = 2 min)")
    p.add_argument("--n-vehicles", type=int, default=30,
                   help="vehicles to spawn (default 30 — 40 caused intersection congestion)")
    p.add_argument("--max-range", type=float, default=300.0)
    p.add_argument("--image-w", type=int, default=1280)
    p.add_argument("--image-h", type=int, default=720)
    p.add_argument("--fov", type=float, default=90.0)
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--quiet", action="store_true")

    args = p.parse_args()

    if not os.path.isfile(args.detector):
        print(f"FAIL — detector not found: {args.detector}", file=sys.stderr)
        return 1

    if args.sweep:
        return run_sweep(args)

    if args.penetration is None or args.seed is None or args.out is None:
        print("FAIL — single-run mode requires --penetration, --seed, --out",
              file=sys.stderr)
        return 1

    print(f"=== Single run: penetration={args.penetration} seed={args.seed}")
    try:
        metrics = run_single(args, penetration=args.penetration, seed=args.seed)
        metrics["status"] = "ok"
    except Exception as e:
        print(f"FAIL — run crashed: {e}", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print(f"wrote {args.out}")
    print(f"  collisions:                {metrics['collision_count']} "
          f"(cav={metrics['cav_collision_count']} hdv={metrics['hdv_collision_count']})")
    print(f"  phantom brakes suppressed: {metrics['phantom_brakes_suppressed']}")
    print(f"  actions taken:             {metrics['actions_taken']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
