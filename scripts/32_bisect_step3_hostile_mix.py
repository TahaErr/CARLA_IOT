"""scripts/32_bisect_step3_hostile_mix.py — debug bisect.

Identical to scripts/31_bisect_step2_collision_sensors.py EXCEPT:
  - applies HOSTILE_MIX to all vehicles
  - calls disable_tm_collision_detection on all vehicles

If THIS crashes CARLA, the hostile-mix + collision-detect-off
combination is the culprit. If it runs clean, the next layer (real
CarlaCAV with per-tick apply_control) is.

Usage:
    python scripts\\32_bisect_step3_hostile_mix.py ^
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
from v2xsim.carla_rsu import CarlaRSU
from v2xsim.carla_utils import connect, ensure_map, synchronous_mode
from v2xsim.compute_budget import unconstrained_profile
from v2xsim.cpm import decode_cpm
from v2xsim.hdv import HOSTILE_MIX, apply_mix_to_vehicles, disable_tm_collision_detection
from v2xsim.intersections import discover_intersections
from v2xsim.latency import LatencyModel
from v2xsim.pdr import PDRModel


def _distance_2d(p1, p2):
    return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5


class _MockCAV:
    def __init__(self, vehicle, broker):
        self.actor = vehicle
        self.broker = broker
        self.id = f"cav_{vehicle.id}"
        self.received = 0
        self.errors = 0
        self.by_sender: dict = {}

    def pull(self, sim_time_ms):
        for tx in self.broker.deliveries_due(sim_time_ms, receiver_id=self.id):
            try:
                _ = decode_cpm(tx.payload_bytes)
                self.received += 1
                self.by_sender[tx.sender_id] = self.by_sender.get(tx.sender_id, 0) + 1
            except Exception:
                self.errors += 1


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
    # bisect knobs — turn each layer on/off
    p.add_argument("--no-hostile-mix", action="store_true",
                   help="skip HOSTILE_MIX (default: applied)")
    p.add_argument("--no-disable-collision-detection", action="store_true",
                   help="skip disable_tm_collision_detection (default: applied)")
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
    mock_cavs: list = []
    collision_sensors: list = []
    collision_events: list = []

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

            # === NEW: HOSTILE_MIX ===
            if not args.no_hostile_mix:
                hdv_assignments = apply_mix_to_vehicles(
                    tm, vehicles, mix=HOSTILE_MIX, rng=np_rng,
                )
                from collections import Counter
                counts = Counter(hdv_assignments.values())
                print(f"  applied HOSTILE_MIX: {dict(counts)}")
            else:
                print(f"  HOSTILE_MIX skipped")

            # === NEW: disable_tm_collision_detection ===
            if not args.no_disable_collision_detection:
                n_pairs = disable_tm_collision_detection(tm, vehicles)
                print(f"  disabled TM collision detection for {n_pairs} ordered pairs")
            else:
                print(f"  TM collision detection: left enabled")

            # MockCAVs
            cav_count = min(args.n_cavs, len(vehicles))
            cav_vehicles = rng.sample(vehicles, cav_count) if cav_count > 0 else []
            for v in cav_vehicles:
                mock_cavs.append(_MockCAV(v, broker))
            print(f"  marked {len(mock_cavs)} vehicle(s) as CAVs")

            # Collision sensors (from step 2)
            print(f"attaching {len(vehicles)} collision sensors...")
            sensor_bp = bp_lib.find("sensor.other.collision")

            def _make_listener(vehicle_id: int):
                def listener(event):
                    try:
                        collision_events.append((
                            vehicle_id, event.other_actor.id,
                        ))
                    except Exception:
                        pass
                return listener

            for v in vehicles:
                sensor = world.spawn_actor(
                    sensor_bp, carla.Transform(), attach_to=v,
                )
                sensor.listen(_make_listener(v.id))
                collision_sensors.append(sensor)
            print(f"  attached {len(collision_sensors)} sensors")

            # Warmup
            print("warming up (40 ticks)...")
            for _ in range(40):
                world.tick()

            # Main loop
            sim_dt_ms = 50.0
            cpm_period_ticks = 2
            n_ticks = int(args.duration / 0.05)
            print(f"running {args.duration:.0f}s = {n_ticks} ticks")

            n_emit = 0
            n_drop = 0
            wall_t0 = time.time()

            for tick in range(n_ticks):
                world.tick()
                sim_time_ms = tick * sim_dt_ms

                if tick % cpm_period_ticks == 0:
                    budget.reset_window()
                    for rsu, rsu_pos in zip(rsus, rsu_positions):
                        receivers: list = []
                        for cav in mock_cavs:
                            v_loc = cav.actor.get_location()
                            d = _distance_2d(rsu_pos, (v_loc.x, v_loc.y))
                            if d <= args.max_range:
                                receivers.append((cav.id, d))
                        if rsu.tick(sim_time_ms, receivers):
                            n_emit += 1
                        else:
                            n_drop += 1

                for cav in mock_cavs:
                    cav.pull(sim_time_ms)

                if (tick + 1) % 100 == 0:
                    wall = time.time() - wall_t0
                    sim = (tick + 1) * 0.05
                    print(f"  tick {tick+1:4d}/{n_ticks}  sim={sim:4.1f}s  wall={wall:5.1f}s  "
                          f"emit={n_emit:4d}  collisions={len(collision_events)}")

            wall_total = time.time() - wall_t0
            print("=" * 64)
            print(f"Run complete: wall={wall_total:.1f}s for sim={args.duration:.0f}s "
                  f"(ratio={wall_total/args.duration:.2f}x)")
            print(f"COLLISION EVENT count (raw, frame-level): {len(collision_events)}")
            print(f"  unique pairs: {len({tuple(sorted(e)) for e in collision_events})}")
            print(f"Per-CAV inbox:")
            for cav in mock_cavs:
                print(f"  {cav.id:15s} received={cav.received:4d}  errors={cav.errors}")
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
