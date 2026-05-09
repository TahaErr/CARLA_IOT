"""B3-extended — record an RSU video with traffic actually near the camera.

Improvements over the first version:
  - traffic spawned only at spawn points within --radius of the intersection
    center, so vehicles actually pass through the camera's view
  - --light-idx selects which traffic light at the intersection to mount on
    (run multiple times with different values for sequential multi-angle)
  - --yaw lets the user override camera direction (default 0 = proven-safe;
    the auto-computed yaw to look at intersection center is also printed)

Single-camera by design — see project notes on the CARLA 0.9.16 multi-camera
limitation. Sequential multi-angle is the workaround for Sprint 1.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

import carla
import cv2
import numpy as np

from v2xsim.carla_utils import connect, ensure_map, synchronous_mode
from v2xsim.intersections import discover_intersections


def spawn_traffic_near(
    world: carla.World, tm, n_vehicles: int, anchor: carla.Location, radius_m: float
) -> list:
    """Spawn up to n_vehicles in autopilot at spawn points within radius_m of anchor."""
    bp_lib = world.get_blueprint_library()
    vehicle_bps = list(bp_lib.filter("vehicle.*"))
    spawn_points = world.get_map().get_spawn_points()

    near = [(sp.location.distance(anchor), sp) for sp in spawn_points]
    near = [x for x in near if x[0] <= radius_m]
    near.sort(key=lambda x: x[0])
    print(f"  {len(near)} spawn point(s) within {radius_m:.0f} m of intersection")

    spawned = []
    for i, (_d, sp) in enumerate(near[:n_vehicles]):
        bp = vehicle_bps[i % len(vehicle_bps)]
        try:
            v = world.spawn_actor(bp, sp)
            v.set_autopilot(True, tm.get_port())
            spawned.append(v)
        except RuntimeError:
            # spawn collision at this point — skip
            continue
    return spawned


def main(
    host: str,
    port: int,
    out_dir: str,
    target_map: str,
    intersection_idx: int,
    light_idx: int,
    duration_s: float,
    n_vehicles: int,
    radius_m: float,
    image_w: int,
    image_h: int,
    yaw_override: float | None,
) -> int:
    os.makedirs(out_dir, exist_ok=True)

    client = connect(host, port)
    world = ensure_map(client, target_map)
    print(f"map: {world.get_map().name}")

    intersections = discover_intersections(world)
    if not intersections or intersection_idx >= len(intersections):
        print("FAIL — bad intersection", file=sys.stderr)
        return 1

    target = intersections[intersection_idx]
    if light_idx >= len(target.lights):
        print(
            f"FAIL — light_idx {light_idx} out of range (intersection {target.id} has "
            f"{len(target.lights)} lights)",
            file=sys.stderr,
        )
        return 1

    light = target.lights[light_idx]
    loc = light.get_location()

    # Compute yaw that points at the intersection center, for reference.
    dx = target.center.x - loc.x
    dy = target.center.y - loc.y
    yaw_to_center = math.degrees(math.atan2(dy, dx))
    yaw = yaw_override if yaw_override is not None else 0.0

    print(
        f"intersection {target.id}, light {light_idx}/{len(target.lights)}: "
        f"@ ({loc.x:.1f}, {loc.y:.1f}, {loc.z:.1f})"
    )
    print(
        f"camera yaw used = {yaw:.1f}°  (yaw to center would be {yaw_to_center:.1f}°)"
    )

    sim_dt = 0.05
    fps_out = int(round(1.0 / sim_dt))
    n_ticks = int(round(duration_s / sim_dt))

    out_path = os.path.join(
        out_dir, f"rsu{target.id:02d}_light{light_idx}_{int(duration_s)}s.mp4"
    )
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out_path, fourcc, fps_out, (image_w, image_h))
    if not writer.isOpened():
        print("FAIL — could not open video writer", file=sys.stderr)
        return 1

    cam = None
    vehicles: list = []
    saved = {"img": None}

    try:
        with synchronous_mode(client, dt=sim_dt) as (world, tm):
            world.tick()

            print(f"spawning up to {n_vehicles} vehicles near intersection...")
            vehicles = spawn_traffic_near(
                world, tm, n_vehicles, target.center, radius_m
            )
            print(f"  {len(vehicles)} vehicle(s) actually spawned")

            bp = world.get_blueprint_library().find("sensor.camera.rgb")
            bp.set_attribute("image_size_x", str(image_w))
            bp.set_attribute("image_size_y", str(image_h))
            bp.set_attribute("fov", "90")
            transform = carla.Transform(
                carla.Location(x=loc.x, y=loc.y, z=loc.z + 6.0),
                carla.Rotation(pitch=-25.0, yaw=yaw),
            )
            cam = world.spawn_actor(bp, transform)
            print(f"camera spawned: id={cam.id}")
            cam.listen(lambda img: saved.update(img=img))

            # Warmup so traffic is moving before recording starts.
            for _ in range(40):
                world.tick()

            print(f"recording {duration_s:.0f}s ({n_ticks} ticks) at {fps_out} fps...")
            wall_start = time.time()
            written = 0
            for i in range(n_ticks):
                world.tick()
                img = saved["img"]
                if img is None:
                    continue
                arr = np.frombuffer(img.raw_data, dtype=np.uint8).reshape(
                    img.height, img.width, 4
                )
                writer.write(arr[..., :3])
                written += 1
                if (i + 1) % 100 == 0:
                    elapsed = time.time() - wall_start
                    print(f"  tick {i+1}/{n_ticks}  written={written}  wall={elapsed:.1f}s")

            wall_total = time.time() - wall_start
            print(
                f"OK — wrote {out_path} ({written} frames, "
                f"{wall_total:.1f}s wall)"
            )
            return 0
    finally:
        try:
            writer.release()
        except Exception:
            pass
        if cam is not None:
            try:
                cam.stop()
            except Exception:
                pass
            try:
                cam.destroy()
            except Exception:
                pass
        for v in vehicles:
            try:
                v.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=2000)
    p.add_argument("--out", default="./out")
    p.add_argument("--map", default="Town05")
    p.add_argument("--intersection", type=int, default=0)
    p.add_argument("--light-idx", type=int, default=0,
                   help="which traffic light at the intersection to mount on")
    p.add_argument("--duration", type=float, default=30.0, help="simulated seconds")
    p.add_argument("--vehicles", type=int, default=40)
    p.add_argument("--radius", type=float, default=120.0,
                   help="spawn vehicles within this distance of the intersection center")
    p.add_argument("--image-w", type=int, default=320)
    p.add_argument("--image-h", type=int, default=240)
    p.add_argument("--yaw", type=float, default=None,
                   help="camera yaw degrees (default 0 = proven safe; pass yaw_to_center "
                        "from the prior run to look at the intersection)")
    args = p.parse_args()
    sys.exit(
        main(
            args.host,
            args.port,
            args.out,
            args.map,
            args.intersection,
            args.light_idx,
            args.duration,
            args.vehicles,
            args.radius,
            args.image_w,
            args.image_h,
            args.yaw,
        )
    )
