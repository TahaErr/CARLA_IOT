"""scripts/30_broker_demo.py — end-to-end Sprint 3+4 demo in real CARLA.

Spawns N CarlaRSU instances at chosen intersections, M autopilot vehicles
+ K walkers, marks a subset of vehicles as "mock CAVs" that pull deliveries
from the broker. Runs for a configurable duration, prints summary stats.

This is the **manual smoke test** for Sprint 4 Module 1 — exercises the
full pipeline on real RGB frames + real YOLO inference + real CARLA
actors. The CARLA-free unit tests (134 of them in pytest) verify the
math and protocol layers; this script verifies the wiring.

Sprint 4 Module 5 (ablation runner) will be a structured, headless,
metric-collecting evolution of this script.

Usage:
    :: 1. Start CARLA in another terminal: CarlaUE5.exe -quality-level=Low
    :: 2. Run:
    python scripts\\30_broker_demo.py ^
        --detector runs\\detect\\runs\\detect\\yolo26s_carla_multi-2\\weights\\best.pt ^
        --intersections 0,3,7 ^
        --duration 60 ^
        --budget-profile orin ^
        --metrics-json out\\demo_metrics.json

What to look for in the output:
  - "spawning N RSU(s)..." — each RSU should report a unique station_id
  - per-tick progress shows emit/drop counts growing, pending stays bounded
  - "Per-CAV inbox" — every CAV in range should have received CPMs from
    at least one RSU; long-distance CAVs may show 0 (PDR-filtered out)
  - CBR mean — should be a small fraction (each RSU's ~10 ms inference
    in a 1 s window with ~3 RSUs publishing at 10 Hz)
  - publish drops > 0 indicates the budget gate is working under load
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass, field

import carla
import numpy as np

from v2xsim.broker import Broker
from v2xsim.carla_rsu import CarlaRSU
from v2xsim.carla_utils import connect, ensure_map, synchronous_mode
from v2xsim.compute_budget import orin_profile, unconstrained_profile, xavier_profile
from v2xsim.cpm import decode_cpm
from v2xsim.intersections import discover_intersections
from v2xsim.latency import LatencyModel
from v2xsim.pdr import PDRModel


# === Mock CAV ============================================================

@dataclass
class MockCAV:
    """A CARLA vehicle marked as V2X-capable, with a delivery counter."""
    actor: "carla.Vehicle"
    received_count: int = 0
    received_by_sender: dict[str, int] = field(default_factory=dict)
    decode_errors: int = 0

    @property
    def id(self) -> str:
        return f"cav_{self.actor.id}"

    def position_xy(self) -> tuple[float, float]:
        loc = self.actor.get_location()
        return (loc.x, loc.y)


# === Helpers ============================================================

def _parse_int_list(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def _distance_2d(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5


def _spawn_vehicles(world: carla.World, tm, n: int) -> list:
    """Spawn up to n autopilot vehicles at random spawn points."""
    bp_lib = world.get_blueprint_library()
    vehicle_bps = list(bp_lib.filter("vehicle.*"))
    spawn_points = list(world.get_map().get_spawn_points())
    random.shuffle(spawn_points)
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


def _spawn_walkers(world: carla.World, n: int) -> tuple[list, list]:
    """Spawn up to n pedestrians + their AI controllers."""
    bp_lib = world.get_blueprint_library()
    walker_bps = list(bp_lib.filter("walker.pedestrian.*"))
    controller_bp = bp_lib.find("controller.ai.walker")

    spawn_transforms = []
    attempts = 0
    while len(spawn_transforms) < n and attempts < n * 5:
        loc = world.get_random_location_from_navigation()
        if loc is not None:
            spawn_transforms.append(carla.Transform(loc))
        attempts += 1

    walkers = []
    for t in spawn_transforms:
        bp = random.choice(walker_bps)
        if bp.has_attribute("is_invincible"):
            bp.set_attribute("is_invincible", "false")
        try:
            w = world.spawn_actor(bp, t)
            walkers.append(w)
        except RuntimeError:
            continue

    controllers = []
    for w in walkers:
        try:
            c = world.spawn_actor(controller_bp, carla.Transform(), attach_to=w)
            controllers.append(c)
        except RuntimeError:
            continue
    return walkers, controllers


def _start_walker_ai(world: carla.World, controllers: list) -> None:
    for c in controllers:
        try:
            c.start()
            target = world.get_random_location_from_navigation()
            if target is not None:
                c.go_to_location(target)
            c.set_max_speed(1.0 + random.random() * 0.5)
        except RuntimeError:
            continue


# === Main ===============================================================

def main(args) -> int:
    random.seed(args.seed)
    np.random.seed(args.seed)

    if not os.path.isfile(args.detector):
        print(f"FAIL — detector not found: {args.detector}", file=sys.stderr)
        return 1

    client = connect(args.host, args.port)
    world = ensure_map(client, args.map)
    print(f"map: {world.get_map().name}")

    intersections = discover_intersections(world)
    if not intersections:
        print("FAIL — no intersections discovered", file=sys.stderr)
        return 1
    print(f"discovered {len(intersections)} intersection(s)")

    target_idx = _parse_int_list(args.intersections)
    for i in target_idx:
        if not 0 <= i < len(intersections):
            print(f"FAIL — intersection {i} out of range "
                  f"(0..{len(intersections)-1})", file=sys.stderr)
            return 1
    target_intersections = [intersections[i] for i in target_idx]

    # === Channel models + broker ====================================
    broker = Broker(
        latency=LatencyModel(rng=np.random.default_rng(args.seed)),
        pdr=PDRModel(rng=np.random.default_rng(args.seed + 1)),
        cbr_window_ms=1000.0,
    )

    # === Compute budget =============================================
    n_rsus = len(target_intersections)
    if args.budget_profile == "orin":
        budget = orin_profile(n_rsus=n_rsus)
    elif args.budget_profile == "xavier":
        budget = xavier_profile(n_rsus=n_rsus)
    else:
        budget = unconstrained_profile(n_rsus=n_rsus)
    print(f"budget: {args.budget_profile} "
          f"(per_rsu={budget.per_rsu_budget_ms} ms, "
          f"aggregate={budget.aggregate_budget_ms} ms)")

    rsus: list[CarlaRSU] = []
    rsu_positions: list[tuple[float, float]] = []
    vehicles: list = []
    walkers: list = []
    walker_controllers: list = []
    cavs: list[MockCAV] = []

    try:
        with synchronous_mode(client) as (world, tm):
            world.tick()

            # === Spawn RSUs =========================================
            print(f"spawning {n_rsus} CarlaRSU(s)...")
            for target in target_intersections:
                rsu = CarlaRSU(
                    world=world,
                    intersection=target,
                    light_idx=args.light_idx,
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
                # Stash the RSU's reference (x, y) for later distance math.
                light_loc = target.lights[args.light_idx].get_location()
                rsu_positions.append((light_loc.x, light_loc.y))
                print(f"  station_id={target.id}  "
                      f"@ ({light_loc.x:.1f}, {light_loc.y:.1f})")

            # === Spawn traffic ======================================
            print(f"spawning up to {args.n_vehicles} vehicles + "
                  f"{args.n_walkers} walkers...")
            vehicles = _spawn_vehicles(world, tm, args.n_vehicles)
            walkers, walker_controllers = _spawn_walkers(world, args.n_walkers)
            world.tick()  # required before walker .start()
            _start_walker_ai(world, walker_controllers)
            print(f"  spawned: {len(vehicles)} vehicles, {len(walkers)} walkers")

            # === Pick mock CAVs =====================================
            n_cavs = min(args.n_cavs, len(vehicles))
            cav_vehicles = random.sample(vehicles, n_cavs)
            cavs = [MockCAV(actor=v) for v in cav_vehicles]
            print(f"  marked {len(cavs)} vehicle(s) as CAVs")

            # === Warmup =============================================
            print("warming up (40 ticks)...")
            for _ in range(40):
                world.tick()

            # === Main loop ==========================================
            sim_dt_ms = 50.0  # CARLA sync dt = 0.05 s
            ticks_per_cpm_period = max(1, int(round(args.cpm_period_ms / sim_dt_ms)))
            n_ticks = int(args.duration / 0.05)
            print(f"running {args.duration:.0f}s = {n_ticks} ticks "
                  f"(CPM every {ticks_per_cpm_period} ticks "
                  f"= {ticks_per_cpm_period * sim_dt_ms:.0f} ms)")

            cbr_samples: list[float] = []
            n_publishes_attempted = 0
            n_publishes_emitted = 0
            n_publishes_dropped = 0

            wall_t0 = time.time()
            for tick in range(n_ticks):
                world.tick()
                sim_time_ms = tick * sim_dt_ms

                # Publish once per CPM period.
                if tick % ticks_per_cpm_period == 0:
                    budget.reset_window()  # new accounting window for this period
                    for rsu, rsu_pos in zip(rsus, rsu_positions):
                        # Receivers: CAVs within range, with distance.
                        receivers: list[tuple[str, float]] = []
                        for cav in cavs:
                            d = _distance_2d(rsu_pos, cav.position_xy())
                            if d <= args.max_range:
                                receivers.append((cav.id, d))
                        n_publishes_attempted += 1
                        if rsu.tick(sim_time_ms, receivers):
                            n_publishes_emitted += 1
                        else:
                            n_publishes_dropped += 1

                # Every tick, every CAV pulls its own due deliveries.
                for cav in cavs:
                    for tx in broker.deliveries_due(sim_time_ms, receiver_id=cav.id):
                        try:
                            decode_cpm(tx.payload_bytes)
                            cav.received_count += 1
                            cav.received_by_sender[tx.sender_id] = (
                                cav.received_by_sender.get(tx.sender_id, 0) + 1
                            )
                        except Exception:
                            cav.decode_errors += 1

                # CBR sample every sim-second.
                if tick % 20 == 0:
                    cbr_samples.append(broker.channel_busy_ratio(sim_time_ms=sim_time_ms))

                # Progress every ~5 sim seconds.
                if (tick + 1) % 100 == 0:
                    wall = time.time() - wall_t0
                    sim = (tick + 1) * 0.05
                    print(f"  tick {tick+1:5d}/{n_ticks}  "
                          f"sim={sim:5.1f}s  wall={wall:5.1f}s  "
                          f"emit={n_publishes_emitted:4d}  "
                          f"drop={n_publishes_dropped:3d}  "
                          f"pending={broker.pending_count():4d}")

            wall_total = time.time() - wall_t0

            # === Summary ===========================================
            print()
            print("=" * 64)
            print(f"Run complete: wall={wall_total:.1f}s for sim={args.duration:.0f}s "
                  f"(ratio={wall_total/args.duration:.2f}x)")
            print(f"RSU publish attempts: {n_publishes_attempted}")
            print(f"  emitted:           {n_publishes_emitted}")
            print(f"  dropped (budget):  {n_publishes_dropped}")
            cbr_mean = float(np.mean(cbr_samples)) if cbr_samples else 0.0
            cbr_max  = float(np.max(cbr_samples))  if cbr_samples else 0.0
            print(f"CBR (mean / max):    {cbr_mean:.4f} / {cbr_max:.4f}")
            print(f"Broker pending end:  {broker.pending_count()}")
            print(f"Per-CAV inbox:")
            for cav in cavs:
                by_sender = ", ".join(f"{s}:{n}" for s, n in cav.received_by_sender.items())
                print(f"  {cav.id:14s}  received={cav.received_count:4d}  "
                      f"errors={cav.decode_errors}  by_sender={{{by_sender}}}")

            # === Optional JSON dump ================================
            if args.metrics_json:
                metrics = {
                    "config": {
                        "map": args.map,
                        "intersections": target_idx,
                        "n_rsus": n_rsus,
                        "n_vehicles": len(vehicles),
                        "n_walkers": len(walkers),
                        "n_cavs": len(cavs),
                        "duration_s": args.duration,
                        "budget_profile": args.budget_profile,
                        "max_range_m": args.max_range,
                        "cpm_period_ms": args.cpm_period_ms,
                        "seed": args.seed,
                    },
                    "wall_seconds": wall_total,
                    "publishes_attempted": n_publishes_attempted,
                    "publishes_emitted": n_publishes_emitted,
                    "publishes_dropped": n_publishes_dropped,
                    "cbr_mean": cbr_mean,
                    "cbr_max": cbr_max,
                    "broker_pending_final": broker.pending_count(),
                    "per_cav_received": {c.id: c.received_count for c in cavs},
                    "per_cav_by_sender": {c.id: dict(c.received_by_sender) for c in cavs},
                    "per_cav_decode_errors": {c.id: c.decode_errors for c in cavs},
                }
                with open(args.metrics_json, "w") as f:
                    json.dump(metrics, f, indent=2)
                print(f"metrics written to {args.metrics_json}")

            return 0

    finally:
        # Cleanup in reverse spawn order.
        for r in rsus:
            try: r.destroy()
            except Exception: pass
        for c in walker_controllers:
            try: c.stop()
            except Exception: pass
            try: c.destroy()
            except Exception: pass
        for w in walkers:
            try: w.destroy()
            except Exception: pass
        for v in vehicles:
            try: v.destroy()
            except Exception: pass


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=2000)
    p.add_argument("--map", default="Town05")
    p.add_argument("--intersections", default="0,3,7",
                   help="comma-separated intersection indices to instrument")
    p.add_argument("--light-idx", type=int, default=0,
                   help="traffic-light pole at each intersection")
    p.add_argument("--n-vehicles", type=int, default=40)
    p.add_argument("--n-walkers", type=int, default=30)
    p.add_argument("--n-cavs", type=int, default=8,
                   help="how many spawned vehicles are mock CAVs")
    p.add_argument("--duration", type=float, default=60.0,
                   help="simulation seconds")
    p.add_argument("--max-range", type=float, default=300.0,
                   help="NR-V2X PC5 range in metres; RSUs address CAVs within")
    p.add_argument("--cpm-period-ms", type=float, default=100.0,
                   help="CPM transmission period (ETSI default 100 ms = 10 Hz)")
    p.add_argument("--detector", required=True,
                   help="path to fine-tuned YOLO .pt")
    p.add_argument("--budget-profile",
                   choices=["unconstrained", "orin", "xavier"],
                   default="unconstrained")
    p.add_argument("--image-w", type=int, default=1280)
    p.add_argument("--image-h", type=int, default=720)
    p.add_argument("--fov", type=float, default=90.0)
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--metrics-json", default=None)
    args = p.parse_args()
    sys.exit(main(args))
