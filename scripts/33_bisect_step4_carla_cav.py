"""scripts/33_bisect_step4_carla_cav.py — debug bisect.

Identical to scripts/32_bisect_step3_hostile_mix.py EXCEPT: replaces
MockCAV with real CarlaCAV (CAVCore fusion + local sensor + per-tick
ego polling + apply_control override on brake decisions).

If THIS crashes CARLA, the prime suspect is CarlaCAV.tick() — either
the local-sensor synthesis from world.get_actors() OR the per-tick
apply_control overrides.

Two knobs to bisect further:
  --no-apply-control  : skip the per-tick brake override
  --no-local-sensor   : skip world.get_actors() + actors_in_cone

Usage:
    python scripts\\33_bisect_step4_carla_cav.py ^
        --detector runs\\detect\\runs\\detect\\yolo26s_carla_multi-2\\weights\\best.pt ^
        --duration 20 --n-vehicles 30 --n-cavs 5 --intersections 0,3
"""
from __future__ import annotations

import argparse
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


def _distance_2d(p1, p2):
    return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5


def _apply_decision(vehicle, action):
    if action == Action.HARD_BRAKE:
        vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0))
    elif action == Action.SOFT_BRAKE:
        vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=0.5))
    elif action == Action.DECELERATE:
        vehicle.apply_control(carla.VehicleControl(throttle=0.2, brake=0.0))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=2000)
    p.add_argument("--map", default="Town05")
    p.add_argument("--detector", required=True)
    p.add_argument("--duration", type=float, default=20.0)
    p.add_argument("--n-vehicles", type=int, default=30)
    p.add_argument("--n-cavs", type=int, default=5)
    p.add_argument("--intersections", default="0,3")
    p.add_argument("--max-range", type=float, default=300.0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--image-w", type=int, default=1280)
    p.add_argument("--image-h", type=int, default=720)
    p.add_argument("--fov", type=float, default=90.0)
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--no-apply-control", action="store_true")
    p.add_argument("--no-local-sensor", action="store_true")
    args = p.parse_args()

    if not os.path.isfile(args.detector):
        print(f"FAIL — detector not found: {args.detector}", file=sys.stderr)
        return 1

    random.seed(args.seed)
    rng = random.Random(args.seed)
    np_rng = np.random.default_rng(args.seed)

    client = connect(args.host, args.port)
    world = ensure_map(client, args.map)
    print(f"map: {world.get_map().name}")

    intersections = discover_intersections(world)
    target_idx = [int(s) for s in args.intersections.split(",")]
    target_intersections = [intersections[i] for i in target_idx]

    broker = Broker(
        latency=LatencyModel(rng=np.random.default_rng(args.seed + 100)),
        pdr=PDRModel(rng=np.random.default_rng(args.seed + 200)),
        cbr_window_ms=1000.0,
    )
    budget = unconstrained_profile(n_rsus=len(target_intersections))

    rsus: list = []
    rsu_positions: list = []
    vehicles: list = []
    cavs: list = []
    collision_sensors: list = []
    collision_events: list = []
    print(f"  apply_control: {'OFF' if args.no_apply_control else 'ON'}")
    print(f"  local_sensor:  {'OFF' if args.no_local_sensor else 'ON'}")

    try:
        with synchronous_mode(client) as (world, tm):
            world.tick()

            # RSUs
            print(f"spawning {len(target_intersections)} CarlaRSU(s)...")
            for target in target_intersections:
                rsu = CarlaRSU(
                    world=world, intersection=target, light_idx=0,
                    broker=broker, detector_path=args.detector,
                    station_id=target.id, compute_budget=budget,
                    image_size=(args.image_w, args.image_h),
                    fov_deg=args.fov, confidence_threshold=args.conf,
                    device=args.device,
                )
                rsus.append(rsu)
                light_loc = target.lights[0].get_location()
                rsu_positions.append((light_loc.x, light_loc.y))
                print(f"  station_id={target.id}  @ ({light_loc.x:.1f}, {light_loc.y:.1f})")

            # Vehicles
            print(f"spawning up to {args.n_vehicles} vehicles...")
            bp_lib = world.get_blueprint_library()
            vehicle_bps = list(bp_lib.filter("vehicle.*"))
            spawn_points = list(world.get_map().get_spawn_points())
            rng.shuffle(spawn_points)
            for i, sp in enumerate(spawn_points[:args.n_vehicles]):
                bp = vehicle_bps[i % len(vehicle_bps)]
                try:
                    v = world.spawn_actor(bp, sp)
                    v.set_autopilot(True, tm.get_port())
                    vehicles.append(v)
                except RuntimeError:
                    continue
            print(f"  spawned: {len(vehicles)} vehicles")

            world.tick()

            # HOSTILE_MIX + disable TM collision (from step 3)
            apply_mix_to_vehicles(tm, vehicles, mix=HOSTILE_MIX, rng=np_rng)
            disable_tm_collision_detection(tm, vehicles)

            # === NEW: real CarlaCAV instead of MockCAV ===
            cav_count = min(args.n_cavs, len(vehicles))
            cav_vehicles = rng.sample(vehicles, cav_count) if cav_count > 0 else []
            for v in cav_vehicles:
                cav = CarlaCAV(
                    vehicle=v, broker=broker,
                    local_sensor_enabled=not args.no_local_sensor,
                    local_sensor_range_m=50.0,
                    local_sensor_angle_deg=90.0,
                )
                for rsu_id, rsu_xy in zip(
                    [str(t.id) for t in target_intersections], rsu_positions
                ):
                    cav.register_rsu(rsu_id, rsu_xy)
                cavs.append(cav)
            print(f"  marked {len(cavs)} vehicle(s) as CarlaCAV(s)")

            # Collision sensors
            print(f"attaching {len(vehicles)} collision sensors...")
            sensor_bp = bp_lib.find("sensor.other.collision")

            def _make_listener(vehicle_id: int):
                def listener(event):
                    try:
                        collision_events.append((vehicle_id, event.other_actor.id))
                    except Exception:
                        pass
                return listener

            for v in vehicles:
                sensor = world.spawn_actor(sensor_bp, carla.Transform(), attach_to=v)
                sensor.listen(_make_listener(v.id))
                collision_sensors.append(sensor)

            # Warmup
            print("warming up (40 ticks)...")
            for _ in range(40):
                world.tick()

            # Main loop
            sim_dt_ms = 50.0
            cpm_period_ticks = 2
            n_ticks = int(args.duration / 0.05)
            print(f"running {args.duration:.0f}s = {n_ticks} ticks")

            action_counts = {a.value: 0 for a in Action}
            phantom_brakes_suppressed = 0
            n_emit = 0
            n_drop = 0
            dead_cav_ids: set = set()
            wall_t0 = time.time()

            for tick in range(n_ticks):
                world.tick()
                sim_time_ms = tick * sim_dt_ms

                # RSU publishes
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
                        if rsu.tick(sim_time_ms, receivers):
                            n_emit += 1
                        else:
                            n_drop += 1

                # CAV ticks
                if cavs:
                    if not args.no_local_sensor:
                        other_actors = [
                            a for a in world.get_actors()
                            if (a.type_id.startswith("vehicle.") or
                                a.type_id.startswith("walker."))
                        ]
                    else:
                        other_actors = None

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
                            dead_cav_ids.add(cav.id)
                            continue
                        action_counts[decision.action.value] += 1
                        if decision.phantom_brake_suppressed:
                            phantom_brakes_suppressed += 1
                        if not args.no_apply_control:
                            try:
                                _apply_decision(cav.actor, decision.action)
                            except RuntimeError:
                                dead_cav_ids.add(cav.id)

                if (tick + 1) % 100 == 0:
                    wall = time.time() - wall_t0
                    sim = (tick + 1) * 0.05
                    print(f"  tick {tick+1:4d}/{n_ticks}  sim={sim:4.1f}s  wall={wall:5.1f}s  "
                          f"emit={n_emit:4d}  collisions={len(collision_events)}  "
                          f"dead_cavs={len(dead_cav_ids)}")

            wall_total = time.time() - wall_t0
            print("=" * 64)
            print(f"Run complete: wall={wall_total:.1f}s for sim={args.duration:.0f}s "
                  f"(ratio={wall_total/args.duration:.2f}x)")
            print(f"raw collision events: {len(collision_events)}")
            print(f"unique pairs: {len({tuple(sorted(e)) for e in collision_events})}")
            print(f"actions: {action_counts}")
            print(f"phantom_brakes_suppressed: {phantom_brakes_suppressed}")
            print(f"dead_cav_count: {len(dead_cav_ids)}")
            return 0
    finally:
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


if __name__ == "__main__":
    sys.exit(main())
