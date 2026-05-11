"""18_survey_intersections.py — one frame from every signalized intersection.

Quick survey tool. Spawns ambient traffic, then walks through every
intersection in the map and grabs a single frame from the chosen light pole
(default: light 0) with auto-yaw pointing at the intersection centroid.
Useful for sanity-checking camera framing across the whole map before
running the full dataset sweep.

Single camera at a time (spawn → capture → destroy → next), so the
multi-camera CARLA 0.9.16 bug never fires.

Output:
  <out>/intersection_NN_lL.png      # one image per intersection
  <out>/_summary.txt                # one line per intersection: id, coords, yaw

Run:
  python scripts\\18_survey_intersections.py
  python scripts\\18_survey_intersections.py --map Town10 --out ./out/survey_t10
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time
from typing import List

import carla

from v2xsim.carla_utils import connect, ensure_map, synchronous_mode
from v2xsim.intersections import discover_intersections


def spawn_traffic_global(world: carla.World, tm, n: int) -> List[carla.Actor]:
    """Spawn up to n vehicles in autopilot at random spawn points."""
    bp_lib = world.get_blueprint_library()
    vehicle_bps = list(bp_lib.filter("vehicle.*"))
    spawn_points = list(world.get_map().get_spawn_points())
    random.shuffle(spawn_points)
    spawned: List[carla.Actor] = []
    for i, sp in enumerate(spawn_points[:n]):
        bp = vehicle_bps[i % len(vehicle_bps)]
        try:
            v = world.spawn_actor(bp, sp)
            v.set_autopilot(True, tm.get_port())
            spawned.append(v)
        except RuntimeError:
            continue
    return spawned


def main(args) -> int:
    random.seed(args.seed)
    os.makedirs(args.out, exist_ok=True)

    client = connect(args.host, args.port)
    world = ensure_map(client, args.map)
    print(f"map: {world.get_map().name}")

    intersections = discover_intersections(world)
    print(f"discovered {len(intersections)} intersection(s)")
    if not intersections:
        print("FAIL — no intersections", file=sys.stderr)
        return 1

    bp_lib = world.get_blueprint_library()
    vehicles: List[carla.Actor] = []
    summary_lines: List[str] = []
    saved = {"img": None}

    wall_start = time.time()

    try:
        with synchronous_mode(client) as (world, tm):
            try:
                tm.set_random_device_seed(args.seed)
            except Exception:
                pass
            world.tick()

            print(f"spawning up to {args.vehicles} vehicles...")
            vehicles = spawn_traffic_global(world, tm, args.vehicles)
            print(f"  {len(vehicles)} vehicles in autopilot")

            for _ in range(args.settle_ticks):
                world.tick()

            cam_bp = bp_lib.find("sensor.camera.rgb")
            cam_bp.set_attribute("image_size_x", str(args.image_w))
            cam_bp.set_attribute("image_size_y", str(args.image_h))
            cam_bp.set_attribute("fov", str(args.fov))

            for it in intersections:
                if args.light_idx >= len(it.lights):
                    print(f"  [t{it.id:02d}] SKIP — only {len(it.lights)} lights, "
                          f"asked for light {args.light_idx}")
                    summary_lines.append(
                        f"t{it.id:02d}  SKIPPED  only {len(it.lights)} lights"
                    )
                    continue

                light = it.lights[args.light_idx]
                loc = light.get_location()
                dx = it.center.x - loc.x
                dy = it.center.y - loc.y
                yaw = math.degrees(math.atan2(dy, dx))

                transform = carla.Transform(
                    carla.Location(x=loc.x, y=loc.y, z=loc.z + 6.0),
                    carla.Rotation(pitch=-25.0, yaw=yaw),
                )

                saved["img"] = None
                cam = world.spawn_actor(cam_bp, transform)
                cam.listen(lambda img: saved.update(img=img))

                try:
                    for _ in range(args.warmup_ticks):
                        world.tick()

                    if saved["img"] is None:
                        print(f"  [t{it.id:02d}] FAIL — no frame received")
                        summary_lines.append(f"t{it.id:02d}  FAIL  no frame")
                        continue

                    fname = f"intersection_{it.id:02d}_l{args.light_idx}.png"
                    out_path = os.path.join(args.out, fname)
                    saved["img"].save_to_disk(out_path)
                    print(
                        f"  [t{it.id:02d}] center=({it.center.x:7.1f},{it.center.y:7.1f}) "
                        f"yaw={yaw:+6.1f}°  →  {fname}"
                    )
                    summary_lines.append(
                        f"t{it.id:02d}  center=({it.center.x:.1f},{it.center.y:.1f})  "
                        f"light={args.light_idx}/{len(it.lights)}  yaw={yaw:+.1f}°  "
                        f"file={fname}"
                    )
                finally:
                    try:
                        cam.stop()
                    except Exception:
                        pass
                    try:
                        cam.destroy()
                    except Exception:
                        pass

            with open(os.path.join(args.out, "_summary.txt"), "w") as f:
                f.write(f"map: {world.get_map().name}\n")
                f.write(f"intersections: {len(intersections)}\n")
                f.write(f"light_idx requested: {args.light_idx}\n\n")
                for line in summary_lines:
                    f.write(line + "\n")

            print()
            print(f"OK — survey complete in {time.time() - wall_start:.1f}s")
            print(f"  output dir: {args.out}")
            return 0
    finally:
        for v in vehicles:
            try:
                v.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=2000)
    p.add_argument("--out", default="./out/intersection_survey")
    p.add_argument("--map", default="Town05")
    p.add_argument("--light-idx", type=int, default=0,
                   help="which traffic-light pole to mount on, per intersection")
    p.add_argument("--vehicles", type=int, default=50,
                   help="ambient traffic so the frames aren't empty")
    p.add_argument("--settle-ticks", type=int, default=60,
                   help="ticks to let traffic flow before the survey starts")
    p.add_argument("--warmup-ticks", type=int, default=10,
                   help="ticks per intersection (camera stabilisation)")
    p.add_argument("--image-w", type=int, default=1280)
    p.add_argument("--image-h", type=int, default=720)
    p.add_argument("--fov", type=float, default=90.0)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    sys.exit(main(args))
