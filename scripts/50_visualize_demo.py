"""scripts/50_visualize_demo.py — V2X cooperative perception live demo.

Visualises the full V2X pipeline in real time:

  * **CARLA 3D world** — RSU positions (yellow spheres + labels), vehicle
    roles (CAV blue rings, HDV profile-coloured rings), pedestrian rings
    (purple), and the live cooperative-perception data flow as red lines
    drawn from each RSU to every CAV currently within its broadcast
    radius. Lines flicker once per tick when a CPM is "transmitted".
  * **Three OpenCV windows** — one per RSU, showing the live camera
    frame with the YOLO detector's bounding boxes drawn on top
    (colour-coded by class). Header shows RSU id, current weather, and
    detection count.

The demo runs the same detector + projection code paths as the ablation
runner, but skips the CPM encoder / latency / collision pipeline since
those add nothing visual. The "broadcast" is simulated as a range check:
every RSU within `broadcast_range_m` of a CAV draws a line to it.

Run example:
    python scripts/50_visualize_demo.py \
        --detector runs/detect/runs/detect/yolo26s_carla_multi-2/weights/best.pt \
        --map Town05 --duration 90 --n-cavs 6 --n-hdvs 12 --n-walkers 30

The CARLA server must already be running at Epic quality level on
127.0.0.1:2000.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import threading
import time
from typing import Any, Optional

import numpy as np

# Make v2xsim importable from a `scripts/` sibling directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import carla
import cv2
from ultralytics import YOLO

from v2xsim.carla_utils import connect, ensure_map, synchronous_mode
from v2xsim.intersections import discover_intersections
from v2xsim.walker import (
    spawn_walkers_near_intersections,
    start_walker_controllers,
    stop_walker_controllers,
)
from v2xsim.weather import apply_weather_preset


# === Visual constants =====================================================

# YOLO class index -> (BGR colour for bbox, label text)
YOLO_CLASS_VISUALS = {
    0: ((255, 200, 0),   "vehicle"),     # cyan-blue
    1: ((0, 255, 255),   "motorcycle"),  # yellow
    2: ((0, 255, 0),     "bicycle"),     # green
    3: ((128, 0, 255),   "pedestrian"),  # purple
}

# CARLA 3D world debug colours (carla.Color is RGB 0..255)
COLOR_RSU         = carla.Color(255, 215, 0)      # gold
COLOR_CPM_LINK    = carla.Color(255, 40, 40)      # bright red — RSU -> CAV
COLOR_DETECTION   = carla.Color(60, 160, 255)     # cyan-blue — RSU sees actor
COLOR_CAV         = carla.Color(60, 140, 255)     # cyan-blue
COLOR_HDV_ATT     = carla.Color(60, 220, 90)      # green
COLOR_HDV_DIS     = carla.Color(255, 200, 0)      # amber
COLOR_HDV_HOS     = carla.Color(255, 60, 60)      # red
COLOR_WALKER      = carla.Color(200, 60, 220)     # purple
COLOR_FRUSTUM     = carla.Color(255, 215, 0)      # gold (lighter)

# Line thickness constants — tuned so links are clearly visible from
# the CARLA wide-view altitude (~120-200 m above ground).
THICK_CPM_LINK    = 0.18    # RSU -> CAV broadcast
THICK_DETECTION   = 0.15    # RSU -> detected HDV/walker
THICK_FRUSTUM     = 0.08    # camera FOV cone


# === Stats panel ==========================================================
#
# A pure-numpy OpenCV image showing live counters: sim time, RSU/vehicle/
# walker counts, per-camera-RSU detection counts, active CPM links. Drawn
# every tick into the 4th quadrant of the demo's 2x2 layout.

STATS_BG = (28, 24, 24)              # dark slate (BGR)
STATS_TITLE_RGB = (255, 220, 180)    # warm white
STATS_LABEL_RGB = (180, 180, 180)
STATS_VALUE_RGB = (100, 220, 255)    # cyan-amber for values
STATS_HEADER_RGB = (200, 160, 100)
STATS_SEPARATOR_RGB = (80, 80, 100)


def render_stats_panel(width: int, height: int, lines: list) -> np.ndarray:
    """Render the live-stats OpenCV image.

    `lines` is a list of either:
      * ("section", "Header text")     -> section divider with header
      * ("kv", "Label", "Value text")  -> indented key/value row
      * ("blank",)                     -> empty line
    """
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:] = STATS_BG

    # Title
    title = "V2X Live Stats"
    cv2.putText(img, title, (24, 42), cv2.FONT_HERSHEY_SIMPLEX,
                0.9, STATS_TITLE_RGB, 2, cv2.LINE_AA)
    cv2.line(img, (24, 56), (width - 24, 56), STATS_SEPARATOR_RGB, 1)

    y = 88
    line_h = 24
    for item in lines:
        if item[0] == "section":
            y += 6
            cv2.putText(img, item[1], (20, y), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, STATS_HEADER_RGB, 1, cv2.LINE_AA)
            cv2.line(img, (20, y + 4), (width - 24, y + 4),
                     STATS_SEPARATOR_RGB, 1)
            y += line_h
        elif item[0] == "kv":
            label, value = item[1], item[2]
            cv2.putText(img, label, (36, y), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, STATS_LABEL_RGB, 1, cv2.LINE_AA)
            cv2.putText(img, str(value), (340, y), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, STATS_VALUE_RGB, 1, cv2.LINE_AA)
            y += line_h
        elif item[0] == "blank":
            y += int(line_h * 0.5)

    # Footer
    footer = "press 'q' in any window to exit"
    (tw, _), _ = cv2.getTextSize(footer, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
    cv2.putText(img, footer, (width - tw - 24, height - 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (130, 130, 130), 1, cv2.LINE_AA)
    return img


def project_actor_to_image(
    actor_loc: Any,
    cam_transform: Any,
    img_w: int,
    img_h: int,
    fov_deg: float = 110.0,
) -> Optional[tuple]:
    """Project a CARLA world point to (u, v) image pixel coordinates.

    Solves the inverse-projection ambiguity the old `actor_in_camera_view`
    approximation suffered from. Returns (u, v) in pixels if the actor
    is in front of the camera AND inside the image rectangle; returns
    None otherwise (behind camera, off-screen, or too close to be
    valid).

    CARLA's camera-local coordinate frame uses the UE4 convention:
    +X = forward, +Y = right, +Z = up. The standard pinhole projection
    convention is +Z = forward, +X = right, +Y = down. The function
    swaps the axes accordingly.
    """
    import math as _math
    # Focal length from horizontal FOV. Assume square pixels — CARLA
    # cameras have unit aspect by default unless explicitly overridden.
    fx = img_w / (2.0 * _math.tan(_math.radians(fov_deg) / 2.0))
    fy = fx
    cx = img_w / 2.0
    cy = img_h / 2.0

    # world -> camera-local inverse transform (4x4 numpy via CARLA)
    inv_mat = np.array(cam_transform.get_inverse_matrix())
    wp = np.array([actor_loc.x, actor_loc.y, actor_loc.z, 1.0])
    cp = inv_mat @ wp                 # camera-local (UE4 axes)

    # UE4 axes -> pinhole axes
    x_pin = cp[1]                     # right
    y_pin = -cp[2]                    # down
    z_pin = cp[0]                     # forward

    if z_pin < 0.5:                   # behind or too close
        return None
    u = fx * (x_pin / z_pin) + cx
    v = fy * (y_pin / z_pin) + cy
    if not (0.0 <= u < img_w and 0.0 <= v < img_h):
        return None
    return (u, v)


def actor_in_yolo_bboxes(
    actor_loc: Any,
    yolo_bboxes_xyxy: list,
    cam_transform: Any,
    img_w: int,
    img_h: int,
    fov_deg: float = 110.0,
) -> bool:
    """True iff the actor's projected image position lies inside any of
    the YOLO bounding boxes. Used to drive the BLUE 'RSU detected' link
    visualisation so it exactly matches what the detector saw."""
    pt = project_actor_to_image(actor_loc, cam_transform, img_w, img_h, fov_deg)
    if pt is None:
        return False
    u, v = pt
    for x1, y1, x2, y2 in yolo_bboxes_xyxy:
        if x1 <= u <= x2 and y1 <= v <= y2:
            return True
    return False


# Kept for any callers still using the old geometric approximation.
def actor_in_camera_view(
    cam_transform: Any,
    actor_loc: Any,
    max_range_m: float = 70.0,
    fov_deg: float = 110.0,
) -> bool:
    """Deprecated geometric frustum check (kept for backward compat).

    Use `actor_in_yolo_bboxes` instead — it matches the detector's
    actual recall by projecting through the camera's intrinsics and
    testing 2D image-plane membership of the YOLO bboxes.
    """
    import math as _math
    cam_loc = cam_transform.location
    cam_rot = cam_transform.rotation

    dx = actor_loc.x - cam_loc.x
    dy = actor_loc.y - cam_loc.y
    horizontal_dist = (dx * dx + dy * dy) ** 0.5
    if horizontal_dist > max_range_m or horizontal_dist < 1.5:
        return False

    angle_to_actor = _math.atan2(dy, dx)
    cam_yaw = _math.radians(cam_rot.yaw)
    angle_diff = abs(angle_to_actor - cam_yaw)
    # Normalise to [0, pi]
    while angle_diff > _math.pi:
        angle_diff = 2 * _math.pi - angle_diff
    return angle_diff < _math.radians(fov_deg / 2)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=2000)
    p.add_argument("--detector", required=True)
    p.add_argument("--map", default="Town05")
    p.add_argument("--weather", default="ClearNoon")
    p.add_argument("--duration", type=float, default=90.0,
                   help="seconds of sim time to run (default 90)")
    p.add_argument("--n-cavs", type=int, default=6)
    p.add_argument("--n-hdvs", type=int, default=12)
    p.add_argument("--n-walkers", type=int, default=30)
    p.add_argument("--n-rsu-cameras", type=int, default=2,
                   help="how many of the signalised intersections get a "
                        "full camera + YOLO + OpenCV window (default 2 "
                        "for the 2x2 quadrant demo layout). All other "
                        "intersections still get 3D RSU markers + CPM "
                        "link visualisation, just no detector inference.")
    p.add_argument("--image-size", default="960x540",
                   help="OpenCV window resolution per panel (default "
                        "960x540 = quarter of a 1920x1080 screen)")
    p.add_argument("--all-intersections-as-rsu", action="store_true", default=True,
                   help="mark every signalised intersection as an RSU in the "
                        "3D overlay (yellow sphere + label + CPM links). "
                        "On by default; pass --no-all-intersections to disable.")
    p.add_argument("--no-all-intersections", dest="all_intersections_as_rsu",
                   action="store_false",
                   help="only show the --n-rsu-cameras RSUs as 3D markers")
    p.add_argument("--broadcast-range-m", type=float, default=80.0,
                   help="max distance for RSU -> CAV link visualisation")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--spectator", default="wide",
                   choices=("bird", "wide", "follow_cav"),
                   help="bird = bird's-eye over intersection 0 (z+60); "
                        "wide = high altitude view covering multiple "
                        "intersections (z+200, default); "
                        "follow_cav = chase camera on the first CAV")
    p.add_argument("--record-frames", action="store_true",
                   help="save every Nth tick's screen as PNG for later ffmpeg")
    p.add_argument("--record-stride", type=int, default=4,
                   help="record every Nth tick (default 4 = 5 fps at 0.05 dt)")
    p.add_argument("--record-out", default="out/demo_frames",
                   help="output directory for recorded PNGs")
    args = p.parse_args()

    try:
        img_w, img_h = (int(x) for x in args.image_size.split("x"))
    except ValueError:
        print(f"FAIL — --image-size must be WxH, got {args.image_size!r}",
              file=sys.stderr)
        return 1

    if args.record_frames:
        os.makedirs(args.record_out, exist_ok=True)

    # === Connect + reset world ============================================
    client = connect(args.host, args.port)
    world = ensure_map(client, args.map)
    try:
        client.reload_world(False)  # clear any zombies from previous runs
        world = client.get_world()
    except Exception:
        pass
    # Force-destroy any lingering actors from a previous demo
    for a in world.get_actors():
        if a.type_id.startswith(("vehicle.", "walker.", "sensor.",
                                  "controller.ai.walker")):
            try:
                a.destroy()
            except Exception:
                pass

    rng = random.Random(args.seed)
    np_rng = np.random.default_rng(args.seed)

    rsu_cameras: list = []
    rsu_meta: list = []        # parallel list of dicts with location etc.
    rsu_models: list = []      # YOLO instances
    rsu_frame_buffers: list = []   # latest BGR np array per RSU
    rsu_frame_locks: list = []
    vehicles: list = []
    cav_ids: set = set()
    hdv_meta: dict = {}        # vehicle_id -> profile string
    walkers: list = []
    walker_controllers: list = []
    ticks_recorded = 0

    try:
        with synchronous_mode(client) as (world, tm):
            world.tick()

            # === Weather =====================================================
            apply_weather_preset(world, args.weather)
            world.tick()

            # === Intersections + RSU cameras + detectors =====================
            intersections = discover_intersections(world)
            print(f"discovered {len(intersections)} signalised intersections")
            n_avail = len(intersections)

            # Which N intersections get a real camera + YOLO + OpenCV window?
            # The rest get 3D marker visualisation only.
            n_cams = min(args.n_rsu_cameras, n_avail)
            if n_cams == 2 and n_avail >= 2:
                # Find the geographically closest pair so both fit in one
                # CARLA viewport. O(N^2) but N is small (<20).
                best_pair = (0, 1)
                best_d = float("inf")
                centroids_xy = [
                    (intersections[i].lights[0].get_location().x,
                     intersections[i].lights[0].get_location().y)
                    for i in range(n_avail)
                ]
                for i in range(n_avail):
                    for j in range(i + 1, n_avail):
                        dx = centroids_xy[i][0] - centroids_xy[j][0]
                        dy = centroids_xy[i][1] - centroids_xy[j][1]
                        d = (dx * dx + dy * dy) ** 0.5
                        if d < best_d:
                            best_d = d
                            best_pair = (i, j)
                camera_idx = list(best_pair)
                print(f"  nearest pair: RSUs {camera_idx[0]} and "
                      f"{camera_idx[1]}, separated by {best_d:.1f} m")
            elif n_avail >= 8:
                camera_idx = [0, 3, 7][:n_cams]
                if n_cams > 3:
                    step = max(1, n_avail // n_cams)
                    camera_idx = sorted(set(camera_idx + [i for i in range(0, n_avail, step)][:n_cams]))[:n_cams]
            elif n_avail >= 3:
                camera_idx = [0, n_avail // 2, n_avail - 1][:n_cams]
            else:
                print(f"FAIL — map {args.map} has only {n_avail} signalised "
                      f"intersections", file=sys.stderr)
                return 1

            # Which intersections get 3D RSU markers?
            if args.all_intersections_as_rsu:
                marker_idx = list(range(n_avail))
                print(f"  3D RSU markers: ALL {n_avail} intersections")
            else:
                marker_idx = list(camera_idx)
                print(f"  3D RSU markers: {len(marker_idx)} (camera-equipped only)")

            print(f"  detector cameras + OpenCV windows: {camera_idx}")

            # Build marker_meta list (everything that gets a 3D marker)
            marker_meta = []
            for i in marker_idx:
                target = intersections[i]
                light = target.lights[0]
                loc = light.get_location()
                marker_meta.append({
                    "idx": i,
                    "location": loc,
                    "has_camera": i in camera_idx,
                })

            cam_bp = world.get_blueprint_library().find("sensor.camera.rgb")
            cam_bp.set_attribute("image_size_x", str(img_w))
            cam_bp.set_attribute("image_size_y", str(img_h))
            # Wider FOV so the full intersection fits even from a corner pole.
            # Real-world RSU cameras are typically 100-120° wide-angle.
            cam_bp.set_attribute("fov", "110")

            print(f"loading detector: {args.detector}")
            # One YOLO instance shared across the camera-equipped RSUs — saves
            # ~3 GB VRAM vs spawning multiple separate model objects.
            shared_model = YOLO(args.detector)
            try:
                import torch
                if torch.cuda.is_available():
                    shared_model.to("cuda:0")
                    print(f"  device: cuda:0 ({torch.cuda.get_device_name(0)})")
            except ImportError:
                pass

            # Spawn cameras + windows only for camera_idx subset
            import math as _math
            cam_pole_height = 8.0   # metres above the traffic-light base
            for i in camera_idx:
                target = intersections[i]
                light = target.lights[0]
                pole_loc = light.get_location()
                cam_loc = carla.Location(
                    x=pole_loc.x, y=pole_loc.y, z=pole_loc.z + cam_pole_height,
                )

                # Compute the intersection centroid from ALL its traffic
                # lights (typically 4 at a 4-way intersection). This is the
                # geometric centre of the intersection, not just where this
                # single light pole stands.
                centroid_x = sum(l.get_location().x for l in target.lights) / len(target.lights)
                centroid_y = sum(l.get_location().y for l in target.lights) / len(target.lights)
                centroid_z = sum(l.get_location().z for l in target.lights) / len(target.lights)

                # Aim the camera from the pole at the centroid.
                dx = centroid_x - cam_loc.x
                dy = centroid_y - cam_loc.y
                horizontal_dist = (dx * dx + dy * dy) ** 0.5
                vertical_drop = cam_loc.z - (centroid_z + 0.3)   # 0.3 m = ground above light base

                if horizontal_dist < 1e-3:
                    # Camera is directly above the centroid: look straight down,
                    # arbitrary yaw.
                    yaw_deg = 0.0
                    pitch_deg = -85.0
                else:
                    yaw_deg = _math.degrees(_math.atan2(dy, dx))
                    pitch_deg = -_math.degrees(_math.atan2(vertical_drop, horizontal_dist))
                # Clamp pitch so the camera never points straight down (loses
                # the approach lanes) or too flat (loses the crosswalks)
                pitch_deg = max(-60.0, min(-15.0, pitch_deg))

                cam_transform = carla.Transform(
                    cam_loc,
                    carla.Rotation(pitch=pitch_deg, yaw=yaw_deg),
                )
                cam = world.spawn_actor(cam_bp, cam_transform)
                frame_buf = [None]   # mutable single-slot
                lock = threading.Lock()

                def make_listener(buf, lk):
                    def on_frame(image):
                        arr = np.frombuffer(image.raw_data, dtype=np.uint8).reshape(
                            image.height, image.width, 4
                        )
                        bgr = arr[..., :3].copy()
                        with lk:
                            buf[0] = bgr
                    return on_frame

                cam.listen(make_listener(frame_buf, lock))
                rsu_cameras.append(cam)
                rsu_frame_buffers.append(frame_buf)
                rsu_frame_locks.append(lock)
                rsu_models.append(shared_model)
                rsu_meta.append({
                    "idx": i,
                    "location": pole_loc,
                    "transform": cam_transform,
                    "window_name": f"RSU {i} ({args.map} / {args.weather})",
                })
                cv2.namedWindow(rsu_meta[-1]["window_name"], cv2.WINDOW_NORMAL)
                cv2.resizeWindow(rsu_meta[-1]["window_name"], img_w, img_h)
                print(f"  RSU {i} camera @ ({cam_loc.x:.1f}, {cam_loc.y:.1f}, "
                      f"{cam_loc.z:.1f}) aiming at intersection centroid "
                      f"({centroid_x:.1f}, {centroid_y:.1f})  "
                      f"yaw={yaw_deg:+6.1f}° pitch={pitch_deg:+5.1f}°")

            # === Spawn vehicles ============================================
            # Concentrate vehicle spawn near the camera-equipped intersections
            # so they enter the demo cameras' field of view quickly. Sort
            # spawn_points by their minimum distance to any of the
            # camera-equipped intersection centroids; take the N nearest.
            n_total = args.n_cavs + args.n_hdvs
            spawn_points = world.get_map().get_spawn_points()
            cam_xy = [
                (intersections[i].lights[0].get_location().x,
                 intersections[i].lights[0].get_location().y)
                for i in camera_idx
            ]

            def min_dist_to_cam_rsu(sp):
                x = sp.location.x
                y = sp.location.y
                return min(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                           for cx, cy in cam_xy)

            spawn_points.sort(key=min_dist_to_cam_rsu)
            # Take the nearest 3*n_total, then random-shuffle inside that
            # pool so seeds stay reproducible
            pool = spawn_points[:min(len(spawn_points), n_total * 3)]
            rng.shuffle(pool)
            spawn_points = pool[:n_total]
            if len(spawn_points) < n_total:
                print(f"warn — only {len(spawn_points)} spawn points on this map, "
                      f"reducing fleet")
                n_total = len(spawn_points)
                args.n_cavs = min(args.n_cavs, n_total // 2)
                args.n_hdvs = n_total - args.n_cavs

            vehicle_bps = world.get_blueprint_library().filter("vehicle.*")
            # Filter out 2-wheelers for cleaner visualisation
            vehicle_bps = [bp for bp in vehicle_bps
                           if int(bp.get_attribute("number_of_wheels")) == 4]
            for i, sp in enumerate(spawn_points):
                bp = rng.choice(vehicle_bps)
                v = world.try_spawn_actor(bp, sp)
                if v is None:
                    continue
                v.set_autopilot(True, tm.get_port())
                vehicles.append(v)
            print(f"spawned {len(vehicles)}/{n_total} vehicles")

            # Assign CAV / HDV roles
            cav_target_count = min(args.n_cavs, len(vehicles))
            rng.shuffle(vehicles)
            for v in vehicles[:cav_target_count]:
                cav_ids.add(v.id)
            for v in vehicles[cav_target_count:]:
                profile = rng.choice(["attentive", "distracted", "aggressive_hostile"])
                hdv_meta[v.id] = profile
            print(f"  {len(cav_ids)} CAVs, {len(hdv_meta)} HDVs")

            # === Spawn walkers =============================================
            # Walker spawn centroids: use the camera-equipped intersections
            # so walkers are densest where the demo camera windows can see them.
            intersection_centroids = [
                (intersections[i].lights[0].get_location().x,
                 intersections[i].lights[0].get_location().y,
                 intersections[i].lights[0].get_location().z)
                for i in camera_idx
            ]
            if args.n_walkers > 0:
                walkers, walker_controllers = spawn_walkers_near_intersections(
                    client=client,
                    world=world,
                    intersection_centroids=intersection_centroids,
                    n_walkers=args.n_walkers,
                    radius_m=80.0,   # tight around the 2 camera intersections
                    seed=args.seed + 300,
                )
                world.tick()
                # Warm up before starting controllers
                for _ in range(20):
                    world.tick()
                start_walker_controllers(walker_controllers, world)
                world.tick()
                print(f"spawned {len(walkers)}/{args.n_walkers} walkers")

            # === Spectator ================================================
            spectator = world.get_spectator()
            if args.spectator == "bird":
                ic = intersection_centroids[0]
                spectator.set_transform(carla.Transform(
                    carla.Location(x=ic[0], y=ic[1], z=ic[2] + 60),
                    carla.Rotation(pitch=-65.0),
                ))
                print(f"spectator: bird's-eye over intersection {camera_idx[0]}")
            elif args.spectator == "wide":
                # Centroid of the camera-equipped intersections.
                cx = sum(ic[0] for ic in intersection_centroids) / len(intersection_centroids)
                cy = sum(ic[1] for ic in intersection_centroids) / len(intersection_centroids)
                cz = sum(ic[2] for ic in intersection_centroids) / len(intersection_centroids)
                # Altitude: chosen so the two camera-equipped intersections
                # comfortably fit in the CARLA viewport. Roughly 2x the
                # inter-intersection separation.
                if len(intersection_centroids) >= 2:
                    dx = intersection_centroids[0][0] - intersection_centroids[1][0]
                    dy = intersection_centroids[0][1] - intersection_centroids[1][1]
                    sep = (dx * dx + dy * dy) ** 0.5
                    altitude = max(80.0, min(220.0, sep * 1.6 + 60.0))
                else:
                    altitude = 120.0
                spectator.set_transform(carla.Transform(
                    carla.Location(x=cx, y=cy, z=cz + altitude),
                    carla.Rotation(pitch=-75.0),
                ))
                print(f"spectator: wide view over {len(camera_idx)} "
                      f"intersections at z+{altitude:.0f}")
            else:
                if not cav_ids:
                    args.spectator = "bird"
                else:
                    print(f"spectator: chase camera on CAV")
            ego_cav = next(iter(cav_ids)) if args.spectator == "follow_cav" else None

            # === Stats panel window ======================================
            stats_window_name = "V2X Live Stats"
            cv2.namedWindow(stats_window_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(stats_window_name, img_w, img_h)
            # Per-RSU running counters
            rsu_total_detections = [0] * len(rsu_meta)
            rsu_last_detections = [0] * len(rsu_meta)
            total_cpm_tx = 0

            # === Main loop ================================================
            ticks_per_sec = 20  # at dt=0.05
            total_ticks = int(args.duration * ticks_per_sec)
            DEBUG_LIFETIME = 0.12   # slightly longer than 2 ticks
            t_start_wall = time.time()

            print(f"\n=== Running demo for {args.duration:.0f} s sim "
                  f"({total_ticks} ticks) ===")
            print(f"   focus the CARLA window for 3D V2X overlay,")
            print(f"   the {len(rsu_meta)} OpenCV windows for YOLO bboxes")
            print(f"   press 'q' in any OpenCV window to exit early\n")

            for tick_idx in range(total_ticks):
                world.tick()

                # --- 3D debug overlay: RSU markers + frustum (ALL marked intersections) -----
                for meta in marker_meta:
                    loc = meta["location"]
                    elevated = carla.Location(x=loc.x, y=loc.y, z=loc.z + 6.0)
                    # RSU sphere — slightly larger for camera-equipped RSUs
                    sphere_size = 0.35 if meta["has_camera"] else 0.22
                    world.debug.draw_point(elevated, size=sphere_size,
                                           color=COLOR_RSU,
                                           life_time=DEBUG_LIFETIME)
                    # Label distinguishes camera-equipped RSUs with "[CAM]"
                    label = (f"RSU {meta['idx']} [CAM]"
                             if meta["has_camera"] else f"RSU {meta['idx']}")
                    world.debug.draw_string(
                        carla.Location(x=loc.x, y=loc.y, z=loc.z + 8.0),
                        label,
                        color=COLOR_RSU, life_time=DEBUG_LIFETIME,
                    )
                    # Camera frustum (only on camera-equipped RSUs — non-camera
                    # ones are 'broadcast-only' nodes in this demo). Use the
                    # camera's actual aim direction, looked up by index.
                    if meta["has_camera"]:
                        # Find this RSU's entry in rsu_meta (the camera-equipped
                        # subset) to pull its transform.
                        cam_transform = None
                        for rm in rsu_meta:
                            if rm["idx"] == meta["idx"]:
                                cam_transform = rm["transform"]
                                break
                        if cam_transform is not None:
                            pitch = cam_transform.rotation.pitch * np.pi / 180
                            yaw = cam_transform.rotation.yaw * np.pi / 180
                            # Frustum is drawn from the actual camera location
                            # (slightly above the pole), not the pole base.
                            cam_xyz = carla.Location(
                                x=cam_transform.location.x,
                                y=cam_transform.location.y,
                                z=cam_transform.location.z,
                            )
                            for dyaw in (-0.55, -0.2, 0.2, 0.55):
                                # FOV 110° -> half-FOV 55° -> 0.96 rad
                                # Use ±0.55 rad horizontal spread (≈ ±31°),
                                # ±0.2 for the inner cone lines
                                end_y = carla.Location(
                                    x=cam_xyz.x + 30 * (np.cos(yaw + dyaw) * np.cos(pitch)),
                                    y=cam_xyz.y + 30 * (np.sin(yaw + dyaw) * np.cos(pitch)),
                                    z=cam_xyz.z + 30 * np.sin(pitch),
                                )
                                world.debug.draw_line(cam_xyz, end_y,
                                                      thickness=THICK_FRUSTUM,
                                                      color=COLOR_FRUSTUM,
                                                      life_time=DEBUG_LIFETIME)

                # --- 3D debug overlay: vehicles role rings ------
                cav_positions: list[carla.Location] = []
                for v in vehicles:
                    if not v.is_alive:
                        continue
                    loc = v.get_location()
                    if v.id in cav_ids:
                        color = COLOR_CAV
                        label = "CAV"
                        cav_positions.append((v.id, loc))
                    else:
                        profile = hdv_meta.get(v.id, "attentive")
                        color = {"attentive": COLOR_HDV_ATT,
                                 "distracted": COLOR_HDV_DIS,
                                 "aggressive_hostile": COLOR_HDV_HOS}[profile]
                        label = f"HDV {profile[:3].upper()}"
                    world.debug.draw_string(
                        carla.Location(x=loc.x, y=loc.y, z=loc.z + 2.6),
                        label, color=color, life_time=DEBUG_LIFETIME,
                    )
                    # ring around vehicle (small triangle)
                    world.debug.draw_point(
                        carla.Location(x=loc.x, y=loc.y, z=loc.z + 1.8),
                        size=0.18, color=color, life_time=DEBUG_LIFETIME,
                    )

                # --- 3D debug overlay: walkers ---------------------
                for w in walkers:
                    if not w.is_alive:
                        continue
                    loc = w.get_location()
                    world.debug.draw_point(
                        carla.Location(x=loc.x, y=loc.y, z=loc.z + 2.2),
                        size=0.12, color=COLOR_WALKER, life_time=DEBUG_LIFETIME,
                    )
                    world.debug.draw_string(
                        carla.Location(x=loc.x, y=loc.y, z=loc.z + 2.6),
                        "PED", color=COLOR_WALKER, life_time=DEBUG_LIFETIME,
                    )

                # --- 3D debug overlay: RSU -> CAV CPM links (red) -----
                # Every RSU within broadcast_range_m draws a line to every CAV.
                # In a real V2X deployment the link is asymmetric and per-cell;
                # for the demo we show the broadcast cone as it would look.
                # ALL signalised intersections participate in the V2X broadcast
                # mesh, not just the camera-equipped subset — non-camera RSUs
                # are 'relay-only' nodes in this visualisation.
                for meta in marker_meta:
                    rsu_loc = meta["location"]
                    rsu_elevated = carla.Location(
                        x=rsu_loc.x, y=rsu_loc.y, z=rsu_loc.z + 6.0)
                    for cav_id, cav_loc in cav_positions:
                        dx = cav_loc.x - rsu_loc.x
                        dy = cav_loc.y - rsu_loc.y
                        d = (dx * dx + dy * dy) ** 0.5
                        if d <= args.broadcast_range_m:
                            world.debug.draw_line(
                                rsu_elevated,
                                carla.Location(
                                    x=cav_loc.x, y=cav_loc.y, z=cav_loc.z + 1.8),
                                thickness=THICK_CPM_LINK,
                                color=COLOR_CPM_LINK,
                                life_time=DEBUG_LIFETIME,
                            )

                # --- 3D debug overlay: RSU -> detected actor (BLUE) ----
                # The BLUE detection links are now drawn inside the YOLO
                # inference loop below. Each actor (HDV or walker) whose
                # 3D world position projects into a YOLO bbox gets a
                # blue line drawn from the camera position to its 3D
                # location — so the visualisation exactly matches what
                # the detector reported. `detected_actor_count` is
                # incremented there.
                detected_actor_count = 0

                # --- Spectator (follow_cav mode) ---------------------
                if args.spectator == "follow_cav" and ego_cav is not None:
                    ego = world.get_actor(ego_cav)
                    if ego is not None and ego.is_alive:
                        t = ego.get_transform()
                        back = -t.get_forward_vector()
                        spectator.set_transform(carla.Transform(
                            carla.Location(
                                x=t.location.x + 8 * back.x,
                                y=t.location.y + 8 * back.y,
                                z=t.location.z + 5,
                            ),
                            carla.Rotation(pitch=-15, yaw=t.rotation.yaw),
                        ))

                # --- YOLO inference + OpenCV display per RSU -----------
                active_cpm_links = 0
                for meta in marker_meta:
                    rsu_loc = meta["location"]
                    for cav_id, cav_loc in cav_positions:
                        dx = cav_loc.x - rsu_loc.x
                        dy = cav_loc.y - rsu_loc.y
                        if (dx * dx + dy * dy) ** 0.5 <= args.broadcast_range_m:
                            active_cpm_links += 1

                for i, meta in enumerate(rsu_meta):
                    with rsu_frame_locks[i]:
                        frame = rsu_frame_buffers[i][0]
                    if frame is None:
                        continue
                    frame_display = frame.copy()
                    result = rsu_models[i](
                        frame, conf=0.25,
                        device="cuda:0" if hasattr(rsu_models[i], "device") else 0,
                        verbose=False,
                    )[0]
                    n_dets = 0
                    # Collect YOLO bboxes in image pixel coords for the
                    # 3D mavi-çizgi projection step below.
                    yolo_bboxes_xyxy = []
                    for box in result.boxes:
                        cls_idx = int(box.cls[0])
                        conf = float(box.conf[0])
                        if cls_idx not in YOLO_CLASS_VISUALS:
                            continue
                        x1f, y1f, x2f, y2f = (float(v) for v in box.xyxy[0])
                        x1, y1, x2, y2 = int(x1f), int(y1f), int(x2f), int(y2f)
                        yolo_bboxes_xyxy.append((x1f, y1f, x2f, y2f))
                        color, label = YOLO_CLASS_VISUALS[cls_idx]
                        cv2.rectangle(frame_display, (x1, y1), (x2, y2),
                                      color, 2)
                        text = f"{label} {conf:.2f}"
                        (tw, th), _ = cv2.getTextSize(
                            text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
                        cv2.rectangle(frame_display,
                                      (x1, y1 - th - 4),
                                      (x1 + tw + 4, y1),
                                      color, -1)
                        cv2.putText(frame_display, text, (x1 + 2, y1 - 3),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                                    (0, 0, 0), 1, cv2.LINE_AA)
                        n_dets += 1

                    rsu_last_detections[i] = n_dets
                    rsu_total_detections[i] += n_dets

                    # --- 3D BLUE lines: project every HDV / walker into
                    # this RSU's image plane; if the projected pixel
                    # falls inside any YOLO bbox, draw a line from the
                    # camera to that actor in the 3D world. This makes
                    # the blue links *exactly* reflect what the detector
                    # actually reported, fixing the missing-line bug
                    # caused by the previous geometric approximation.
                    #
                    # The line origin is offset 2m BELOW the camera lens
                    # (same elevation as the red CPM links). A camera
                    # cannot render a line whose start point sits inside
                    # its own optical centre — so without this offset,
                    # the blue lines were invisible in the RSU camera
                    # window itself (they were still visible in the
                    # bird's-eye view from above).
                    cam_tx = meta["transform"]
                    cam_loc_3d = cam_tx.location
                    line_start = carla.Location(
                        x=cam_loc_3d.x,
                        y=cam_loc_3d.y,
                        z=cam_loc_3d.z - 2.0,
                    )
                    if yolo_bboxes_xyxy:
                        for v in vehicles:
                            if not v.is_alive or v.id in cav_ids:
                                continue
                            v_loc = v.get_location()
                            if actor_in_yolo_bboxes(
                                    v_loc, yolo_bboxes_xyxy, cam_tx,
                                    img_w, img_h, fov_deg=110.0):
                                world.debug.draw_line(
                                    line_start,
                                    carla.Location(
                                        x=v_loc.x, y=v_loc.y, z=v_loc.z + 1.4),
                                    thickness=THICK_DETECTION,
                                    color=COLOR_DETECTION,
                                    life_time=DEBUG_LIFETIME,
                                )
                                detected_actor_count += 1
                        for w in walkers:
                            if not w.is_alive:
                                continue
                            w_loc = w.get_location()
                            if actor_in_yolo_bboxes(
                                    w_loc, yolo_bboxes_xyxy, cam_tx,
                                    img_w, img_h, fov_deg=110.0):
                                world.debug.draw_line(
                                    line_start,
                                    carla.Location(
                                        x=w_loc.x, y=w_loc.y, z=w_loc.z + 1.4),
                                    thickness=THICK_DETECTION,
                                    color=COLOR_DETECTION,
                                    life_time=DEBUG_LIFETIME,
                                )
                                detected_actor_count += 1

                    # Header banner
                    header = f"{meta['window_name']}  |  detections: {n_dets}"
                    cv2.rectangle(frame_display, (0, 0),
                                  (img_w, 24), (0, 0, 0), -1)
                    cv2.putText(frame_display, header, (8, 16),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                (255, 255, 255), 1, cv2.LINE_AA)
                    cv2.imshow(meta["window_name"], frame_display)

                    if args.record_frames and tick_idx % args.record_stride == 0:
                        out_path = os.path.join(
                            args.record_out,
                            f"rsu{meta['idx']}_t{tick_idx:05d}.png")
                        cv2.imwrite(out_path, frame_display)

                # Active CPM links assumed to be transmitted this tick
                total_cpm_tx += active_cpm_links

                # --- Stats panel ----------------------------------------
                sim_t_now = tick_idx / ticks_per_sec
                wall_now = time.time() - t_start_wall
                ratio = wall_now / max(sim_t_now, 1e-6)
                n_att = sum(1 for p in hdv_meta.values() if p == "attentive")
                n_dis = sum(1 for p in hdv_meta.values() if p == "distracted")
                n_hos = sum(1 for p in hdv_meta.values() if p == "aggressive_hostile")
                n_walker_alive = sum(1 for w in walkers if w.is_alive)

                lines = [
                    ("section", "Simulation"),
                    ("kv", "Map / Weather",
                        f"{args.map}  /  {args.weather}"),
                    ("kv", "Sim time (s)",
                        f"{sim_t_now:6.1f}  /  {args.duration:.0f}"),
                    ("kv", "Wall time (s)", f"{wall_now:6.1f}"),
                    ("kv", "Wall : sim ratio", f"{ratio:5.2f}x"),
                    ("kv", "Tick", f"{tick_idx:5d}  /  {total_ticks}"),
                    ("blank",),
                    ("section", "V2X infrastructure"),
                    ("kv", "Signalised intersections", f"{len(marker_meta)}"),
                    ("kv", "Camera-equipped RSUs", f"{len(rsu_meta)}"),
                    ("kv", "Broadcast range (m)",
                        f"{args.broadcast_range_m:.0f}"),
                    ("kv", "Active CPM links (now)", f"{active_cpm_links}"),
                    ("kv", "RSU detection links (now)", f"{detected_actor_count}"),
                    ("kv", "Total CPM transmissions",
                        f"{total_cpm_tx:,}"),
                    ("blank",),
                    ("section", "Fleet"),
                    ("kv", "CAVs (V2X-equipped)",
                        f"{len(cav_ids)}"),
                    ("kv", "HDVs attentive", f"{n_att}"),
                    ("kv", "HDVs distracted", f"{n_dis}"),
                    ("kv", "HDVs aggressive", f"{n_hos}"),
                    ("kv", "Pedestrians active",
                        f"{n_walker_alive}  /  {len(walkers)}"),
                    ("blank",),
                    ("section", "Detector inference (this tick)"),
                ]
                for i, meta in enumerate(rsu_meta):
                    lines.append((
                        "kv",
                        f"RSU {meta['idx']} detections",
                        f"{rsu_last_detections[i]:3d}  "
                        f"(total {rsu_total_detections[i]:5d})",
                    ))
                stats_img = render_stats_panel(img_w, img_h, lines)
                cv2.imshow(stats_window_name, stats_img)

                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    print("\n(early exit on 'q')")
                    break

                if tick_idx % 100 == 0:
                    sim_t = tick_idx / ticks_per_sec
                    wall = time.time() - t_start_wall
                    print(f"  tick {tick_idx:4d}/{total_ticks}  "
                          f"sim={sim_t:5.1f}s  wall={wall:5.1f}s  "
                          f"vehicles={len(vehicles)}  walkers={len(walkers)}")

            print(f"\ndemo finished in {time.time()-t_start_wall:.1f}s wall time")

    finally:
        print("\ncleaning up...")
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        for cam in rsu_cameras:
            try:
                cam.stop()
                cam.destroy()
            except Exception:
                pass
        try:
            stop_walker_controllers(walker_controllers)
        except Exception:
            pass
        try:
            for c in walker_controllers:
                c.destroy()
        except Exception:
            pass
        try:
            for w in walkers:
                w.destroy()
        except Exception:
            pass
        try:
            for v in vehicles:
                v.destroy()
        except Exception:
            pass
        print("done")

    return 0


if __name__ == "__main__":
    sys.exit(main())
