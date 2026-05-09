"""Sprint 2 step 2 — record an RSU video with per-frame YOLO detections.

Same camera + traffic setup as 12, but each captured frame is run through
YOLOv8s and the annotated frame (with bounding boxes + labels) is what
gets written to the MP4.

The model is loaded once at startup and reused. On a CPU-only torch this
costs ~50-150 ms per 320x240 frame; on GPU much less.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from collections import Counter

import carla
import cv2
import numpy as np
from ultralytics import YOLO

from v2xsim.carla_utils import connect, ensure_map, synchronous_mode
from v2xsim.intersections import discover_intersections


def spawn_traffic_near(
    world: carla.World, tm, n_vehicles: int, anchor: carla.Location, radius_m: float
) -> list:
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
    model_name: str,
    conf_thresh: float,
) -> int:
    os.makedirs(out_dir, exist_ok=True)

    # Load YOLO once, before connecting to CARLA.
    print(f"loading YOLO model {model_name}...")
    model = YOLO(model_name)
    # Move to CUDA if available; ultralytics doesn't auto-place on first load.
    import torch
    if torch.cuda.is_available():
        model.to("cuda")
        device_str = f"cuda:0 ({torch.cuda.get_device_name(0)})"
    else:
        device_str = "cpu"
    print(f"  device={device_str}, classes={len(model.names)}")

    client = connect(host, port)
    world = ensure_map(client, target_map)
    print(f"map: {world.get_map().name}")

    intersections = discover_intersections(world)
    if not intersections or intersection_idx >= len(intersections):
        print("FAIL — bad intersection", file=sys.stderr)
        return 1
    target = intersections[intersection_idx]
    if light_idx >= len(target.lights):
        print(f"FAIL — light_idx out of range", file=sys.stderr)
        return 1

    light = target.lights[light_idx]
    loc = light.get_location()
    dx = target.center.x - loc.x
    dy = target.center.y - loc.y
    yaw_to_center = math.degrees(math.atan2(dy, dx))
    yaw = yaw_override if yaw_override is not None else 0.0
    print(
        f"intersection {target.id}, light {light_idx}: "
        f"yaw used = {yaw:.1f}°  (yaw to center = {yaw_to_center:.1f}°)"
    )

    sim_dt = 0.05
    fps_out = int(round(1.0 / sim_dt))
    n_ticks = int(round(duration_s / sim_dt))

    out_path = os.path.join(
        out_dir, f"rsu{target.id:02d}_light{light_idx}_{int(duration_s)}s_yolo.mp4"
    )
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out_path, fourcc, fps_out, (image_w, image_h))
    if not writer.isOpened():
        print("FAIL — could not open video writer", file=sys.stderr)
        return 1

    cam = None
    vehicles: list = []
    saved = {"img": None}
    class_counts: Counter = Counter()
    total_detections = 0
    inference_time_total = 0.0

    try:
        with synchronous_mode(client, dt=sim_dt) as (world, tm):
            world.tick()

            print(f"spawning up to {n_vehicles} vehicles...")
            vehicles = spawn_traffic_near(world, tm, n_vehicles, target.center, radius_m)
            print(f"  {len(vehicles)} vehicle(s) spawned")

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

            for _ in range(40):
                world.tick()

            print(
                f"recording {duration_s:.0f}s ({n_ticks} ticks) at {fps_out} fps "
                f"with detection (conf>={conf_thresh})..."
            )
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
                bgr = arr[..., :3]

                t0 = time.time()
                results = model(bgr, conf=conf_thresh, device=0 if torch.cuda.is_available() else "cpu", verbose=False)[0]
                inference_time_total += time.time() - t0

                # Tally classes
                for box in results.boxes:
                    cls_id = int(box.cls[0].item())
                    class_counts[results.names[cls_id]] += 1
                    total_detections += 1

                annotated = results.plot()
                writer.write(annotated)
                written += 1

                if (i + 1) % 100 == 0:
                    elapsed = time.time() - wall_start
                    avg_inf_ms = (inference_time_total / written) * 1000.0
                    print(
                        f"  tick {i+1}/{n_ticks}  written={written}  "
                        f"wall={elapsed:.1f}s  avg_inf={avg_inf_ms:.0f}ms"
                    )

            wall_total = time.time() - wall_start
            avg_inf_ms = (inference_time_total / max(1, written)) * 1000.0
            print(f"OK — wrote {out_path}")
            print(f"  {written} frames, wall={wall_total:.1f}s, avg inference={avg_inf_ms:.0f}ms")
            print(f"  total detections: {total_detections}")
            if class_counts:
                print("  per-class counts:")
                for name, count in class_counts.most_common(10):
                    print(f"    {name:14s}  {count}")
            else:
                print("  (no detections — try lower --conf or check camera framing)")
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
    p.add_argument("--light-idx", type=int, default=0)
    p.add_argument("--duration", type=float, default=20.0)
    p.add_argument("--vehicles", type=int, default=80)
    p.add_argument("--radius", type=float, default=1000.0)
    p.add_argument("--image-w", type=int, default=1280)
    p.add_argument("--image-h", type=int, default=720)
    p.add_argument("--yaw", type=float, default=None)
    p.add_argument("--model", default="yolo26s.pt",
                   help="yolo26n/s/m/l/x .pt; default yolo26s — Sep-2025 release "
                   "with NMS-free inference and improved small-object accuracy")
    p.add_argument("--conf", type=float, default=0.25)
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
            args.model,
            args.conf,
        )
    )
