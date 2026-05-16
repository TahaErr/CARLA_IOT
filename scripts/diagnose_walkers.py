"""scripts/diagnose_walkers.py — visual walker spawn diagnostic.

Spawns N walkers at the same intersections the ablation runner uses
(0, 3, 7), prints their world-coordinate locations + distance from each
centroid, moves the spectator camera to intersection 0 in a bird's-eye
view, and keeps the simulation running for 60 seconds so the operator
can verify visually whether walkers actually appear in the world.

Cleans up walkers + controllers on exit.

Usage (CARLA must already be running on 127.0.0.1:2000 in Epic level):
    python scripts\\diagnose_walkers.py --n-walkers 40

Expected output:
  - "Spawned N walkers (requested M)"
  - 20 sample lines with id / x / y / z
  - Coordinate range of all walkers
  - Per-centroid distance histogram (how many walkers near each intersection)
  - Spectator moved message
  - 60 second hold while walkers walk; check the CARLA viewport
  - "Done" on exit (walkers + controllers destroyed)
"""
from __future__ import annotations

import argparse
import os
import sys
import time

# Make v2xsim importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import carla

from v2xsim.intersections import discover_intersections
from v2xsim.walker import (
    spawn_walkers_near_intersections,
    start_walker_controllers,
    stop_walker_controllers,
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=2000)
    p.add_argument("--map", default="Town05")
    p.add_argument("--n-walkers", type=int, default=40)
    p.add_argument("--hold-seconds", type=float, default=60.0,
                   help="how long to keep walkers alive for visual inspection")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    client = carla.Client(args.host, args.port)
    client.set_timeout(30.0)
    world = client.get_world()
    current_map = world.get_map().name
    if args.map not in current_map:
        print(f"current map is {current_map}, switching to {args.map}...")
        client.load_world(args.map)
        world = client.get_world()

    # Sync mode (same as the ablation runner) — walker spawn behaves
    # differently between sync and async; we test the sync path.
    settings = world.get_settings()
    original_sync = settings.synchronous_mode
    original_dt = settings.fixed_delta_seconds
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    world.apply_settings(settings)
    world.tick()

    walkers: list = []
    controllers: list = []
    try:
        intersections = discover_intersections(world)
        print(f"discovered {len(intersections)} signalised intersections")
        target_idx = [0, 3, 7]
        target_intersections = [intersections[i] for i in target_idx]
        centroids = []
        for i, t in zip(target_idx, target_intersections):
            loc = t.lights[0].get_location()
            centroids.append((loc.x, loc.y, loc.z))
            print(f"  intersection {i}: light 0 at "
                  f"({loc.x:7.1f}, {loc.y:7.1f}, {loc.z:5.1f}), "
                  f"{len(t.lights)} lights")

        print(f"\nrequesting {args.n_walkers} walkers...")
        walkers, controllers = spawn_walkers_near_intersections(
            client=client,
            world=world,
            intersection_centroids=centroids,
            n_walkers=args.n_walkers,
            radius_m=50.0,
            seed=args.seed,
        )
        print(f"spawn returned {len(walkers)} walker actors, "
              f"{len(controllers)} controller actors")

        if not walkers:
            print("\n*** ZERO walkers spawned ***")
            print("CARLA rejected every spawn request. Possible causes:")
            print("  - Town05 navigation mesh isn't loaded "
                  "(restart CARLA with -map=/Game/Carla/Maps/Town05)")
            print("  - is_invincible attribute set failing on this build")
            print("  - Sync-mode race condition on apply_batch_sync")
            return 1

        # Sync the just-spawned transforms to the client
        world.tick()

        # Print the first 20 actual walker locations
        print(f"\n=== Walker world locations (first 20) ===")
        for w in walkers[:20]:
            loc = w.get_location()
            print(f"  id={w.id:4d}  x={loc.x:7.1f}  y={loc.y:7.1f}  z={loc.z:6.1f}")

        # Coordinate ranges
        xs = [w.get_location().x for w in walkers]
        ys = [w.get_location().y for w in walkers]
        zs = [w.get_location().z for w in walkers]
        print(f"\n=== Coordinate range across all {len(walkers)} walkers ===")
        print(f"  x: {min(xs):7.1f} .. {max(xs):7.1f}  (span {max(xs)-min(xs):6.1f} m)")
        print(f"  y: {min(ys):7.1f} .. {max(ys):7.1f}  (span {max(ys)-min(ys):6.1f} m)")
        print(f"  z: {min(zs):7.1f} .. {max(zs):7.1f}  (span {max(zs)-min(zs):6.1f} m)")

        # Per-intersection histogram
        print(f"\n=== Walkers within radius 50m of each intersection ===")
        for label, (cx, cy, _cz) in zip(["intersection 0", "intersection 3", "intersection 7"], centroids):
            close = 0
            for w in walkers:
                loc = w.get_location()
                d = ((loc.x - cx) ** 2 + (loc.y - cy) ** 2) ** 0.5
                if d <= 50.0:
                    close += 1
            print(f"  {label} ({cx:6.0f},{cy:6.0f}): {close}/{len(walkers)} walkers")

        # Start AI controllers so walkers actually walk
        for _ in range(3):
            world.tick()  # ensure walkers settled before controller start
        start_walker_controllers(controllers, world)
        print(f"\n=== Started {len(controllers)} AI controllers ===")

        # Move spectator to intersection 0, bird's-eye 40m up
        spectator = world.get_spectator()
        ic = centroids[0]
        spectator.set_transform(carla.Transform(
            carla.Location(x=ic[0], y=ic[1], z=ic[2] + 40),
            carla.Rotation(pitch=-90),
        ))
        print(f"spectator moved to intersection 0 bird's-eye view")
        print(f"\n*** WALKERS SHOULD NOW BE VISIBLE IN THE CARLA VIEWPORT ***")
        print(f"Holding simulation for {args.hold_seconds:.0f} seconds; "
              f"use mouse/WASD to look around if needed.")
        print(f"(Ctrl+C to exit early)")

        t_start = time.time()
        ticks = 0
        try:
            while time.time() - t_start < args.hold_seconds:
                world.tick()
                ticks += 1
                # Print a heartbeat every 5 sec so we know the sim is alive
                if ticks % 100 == 0:
                    elapsed = time.time() - t_start
                    # Sample one walker's current position to confirm they're moving
                    if walkers:
                        loc = walkers[0].get_location()
                        print(f"  t={elapsed:4.0f}s  walker[0]: "
                              f"x={loc.x:7.1f} y={loc.y:7.1f} z={loc.z:5.1f}")
        except KeyboardInterrupt:
            print("\n(interrupted)")

    finally:
        # Cleanup walkers and controllers
        print("\ncleaning up...")
        stop_walker_controllers(controllers)
        try:
            world.tick()
        except Exception:
            pass
        try:
            client.apply_batch([carla.command.DestroyActor(c.id) for c in controllers])
            client.apply_batch([carla.command.DestroyActor(w.id) for w in walkers])
        except Exception as e:
            print(f"  cleanup batch error: {e}")

        # Restore original sync mode
        settings.synchronous_mode = original_sync
        settings.fixed_delta_seconds = original_dt
        try:
            world.apply_settings(settings)
        except Exception:
            pass
        print("done")

    return 0


if __name__ == "__main__":
    sys.exit(main())
