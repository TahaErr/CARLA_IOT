"""15_generate_dataset.py — sweep-aware ground-truth dataset generator.

Captures (image, YOLO-label) pairs from CARLA, sweeping across:
  - Intersections (configurable subset of the map's signalized intersections)
  - Lights (one camera per traffic-light pole at each intersection)
  - Weather presets (CARLA built-in WeatherParameters)

Per configuration: spawn a single standalone camera at the chosen light,
warm up sim ticks so traffic populates the view, capture N frames separated
by a few sim ticks each, write each frame's image + YOLO label .txt.

Single camera at a time (we never spawn two simultaneously — works around
the CARLA 0.9.16 Windows multi-camera bug discovered during Sprint 1).

Train/val split: intersection_idx % val_stride == 0 → val, else train.
For a Town10 test set, run the script with --val-stride 1 (everything → val).

Class set (4 classes — see proposal §2.2 for future 5-class subdivision):
  0 vehicle      (4-wheeled vehicles)
  1 motorcycle   (2-wheeled motor vehicles: harley/kawasaki/yamaha/vespa)
  2 bicycle      (2-wheeled non-motor: bh/crossbike/diamondback/gazelle)
  3 pedestrian   (walker.*)

Bbox math: CARLA cameras use UE4 left-handed (x=fwd, y=right, z=up). We use
`bb.get_world_vertices(actor.get_transform())` for 8 world-space corners,
transform to camera frame via `cam.get_transform().get_inverse_matrix()`,
swizzle to OpenCV (x=right, y=down, z=fwd), project with K, take
axis-aligned (min,max) of the projected vertices.

Output layout (YOLO standard):
  <out_dir>/
    images/{train,val}/<frame_id>.png
    labels/{train,val}/<frame_id>.txt          # class cx cy w h, normalized 0..1
    debug/<frame_id>_debug.png                 # only if --debug-vis
    data.yaml
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time
from typing import List, Optional, Tuple

import carla
import cv2
import numpy as np

from v2xsim.carla_utils import connect, ensure_map, synchronous_mode
from v2xsim.intersections import Intersection, discover_intersections


# --- Class scheme -----------------------------------------------------------

CLS_VEHICLE = 0
CLS_MOTORCYCLE = 1
CLS_BICYCLE = 2
CLS_PEDESTRIAN = 3
CLASS_NAMES = ["vehicle", "motorcycle", "bicycle", "pedestrian"]

_MOTORCYCLE_KEYS = ("harley", "kawasaki", "yamaha", "vespa")
_BICYCLE_KEYS = ("bh.crossbike", "diamondback", "gazelle", "omafiets")


def classify_actor(actor: carla.Actor) -> Optional[int]:
    """Return YOLO class id for the actor, or None if it should be skipped."""
    tid = actor.type_id.lower()
    if tid.startswith("walker."):
        return CLS_PEDESTRIAN
    if tid.startswith("vehicle."):
        n_wheels = int(actor.attributes.get("number_of_wheels", "4"))
        if n_wheels == 2:
            if any(k in tid for k in _MOTORCYCLE_KEYS):
                return CLS_MOTORCYCLE
            return CLS_BICYCLE  # default 2-wheeler when uncertain
        return CLS_VEHICLE
    return None


# --- Geometry ---------------------------------------------------------------


def build_intrinsic(image_w: int, image_h: int, fov_deg: float) -> np.ndarray:
    fx = image_w / (2.0 * math.tan(math.radians(fov_deg) / 2.0))
    return np.array([[fx, 0.0, image_w / 2.0],
                     [0.0, fx, image_h / 2.0],
                     [0.0, 0.0, 1.0]])


def world_to_image(
    K: np.ndarray, world_to_cam: np.ndarray, world_pt: np.ndarray
) -> Optional[Tuple[float, float, float]]:
    """Project a homogeneous world point [x, y, z, 1] to (u, v, depth).
    Returns None if the point is behind the camera."""
    p_cam = world_to_cam @ world_pt
    # CARLA cam frame: x=fwd, y=right, z=up. OpenCV image frame: x=right, y=down, z=fwd.
    x = p_cam[1]
    y = -p_cam[2]
    z = p_cam[0]
    if z <= 0.1:
        return None
    p_img = K @ np.array([x, y, z])
    return float(p_img[0] / p_img[2]), float(p_img[1] / p_img[2]), float(z)


def project_bbox_2d(
    actor: carla.Actor,
    K: np.ndarray,
    world_to_cam: np.ndarray,
    image_w: int,
    image_h: int,
    cam_world_pos: np.ndarray,
    max_distance_m: float = 80.0,
    min_pixel_area: int = 25,
) -> Optional[Tuple[int, int, int, int]]:
    """Project actor's 3D bbox to 2D image axis-aligned bbox. None if filtered out."""
    actor_loc = actor.get_location()
    if actor_loc.distance(carla.Location(*cam_world_pos.tolist())) > max_distance_m:
        return None

    bb = actor.bounding_box
    verts = bb.get_world_vertices(actor.get_transform())

    us, vs = [], []
    for v in verts:
        proj = world_to_image(K, world_to_cam, np.array([v.x, v.y, v.z, 1.0]))
        if proj is None:
            continue
        us.append(proj[0])
        vs.append(proj[1])

    if len(us) < 2:
        return None

    x_min = max(0, int(min(us)))
    y_min = max(0, int(min(vs)))
    x_max = min(image_w - 1, int(max(us)))
    y_max = min(image_h - 1, int(max(vs)))
    if x_max <= x_min or y_max <= y_min:
        return None
    if (x_max - x_min) * (y_max - y_min) < min_pixel_area:
        return None
    return x_min, y_min, x_max, y_max


# --- CLI list parsing -------------------------------------------------------


def parse_int_list(s: str, max_n: int) -> List[int]:
    """Parse 'all' or '0,1,5' into a list of indices, filtered to [0, max_n)."""
    if s.strip().lower() == "all":
        return list(range(max_n))
    out = []
    for x in s.split(","):
        x = x.strip()
        if not x:
            continue
        idx = int(x)
        if 0 <= idx < max_n:
            out.append(idx)
    return out


def parse_str_list(s: str) -> List[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


# --- Traffic & walker spawning ----------------------------------------------


def spawn_traffic_global(world: carla.World, tm, n: int) -> List[carla.Actor]:
    """Spawn up to n vehicles at random spawn points across the whole map, autopilot."""
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


def spawn_walkers_global(
    client: carla.Client, world: carla.World, n: int
) -> Tuple[List[carla.Actor], List[carla.Actor]]:
    """Spawn n walkers + AI controllers at navigation-mesh points across the whole map.

    Returns (walkers, controllers). Both must be destroyed at cleanup;
    controllers must be .stop()'d first.
    """
    bp_lib = world.get_blueprint_library()
    walker_bps = list(bp_lib.filter("walker.pedestrian.*"))
    controller_bp = bp_lib.find("controller.ai.walker")

    # 1. spawn walker actors at random nav-mesh points
    spawn_transforms = []
    attempts = 0
    while len(spawn_transforms) < n and attempts < n * 5:
        loc = world.get_random_location_from_navigation()
        if loc is not None:
            spawn_transforms.append(carla.Transform(loc))
        attempts += 1

    walkers: List[carla.Actor] = []
    for t in spawn_transforms:
        bp = random.choice(walker_bps)
        if bp.has_attribute("is_invincible"):
            bp.set_attribute("is_invincible", "false")
        try:
            w = world.spawn_actor(bp, t)
            walkers.append(w)
        except RuntimeError:
            continue

    # 2. spawn controllers
    controllers: List[carla.Actor] = []
    for w in walkers:
        try:
            c = world.spawn_actor(controller_bp, carla.Transform(), attach_to=w)
            controllers.append(c)
        except RuntimeError:
            continue

    return walkers, controllers


def start_walker_ai(world: carla.World, controllers: List[carla.Actor]) -> None:
    """Activate each walker controller. Call after at least one world.tick()."""
    for c in controllers:
        try:
            c.start()
            target = world.get_random_location_from_navigation()
            if target is not None:
                c.go_to_location(target)
            c.set_max_speed(1.0 + random.random() * 0.5)
        except RuntimeError:
            continue


# --- Weather ----------------------------------------------------------------


def set_weather(world: carla.World, preset_name: str) -> bool:
    """Apply a named WeatherParameters preset. Returns True if succeeded."""
    preset = getattr(carla.WeatherParameters, preset_name, None)
    if preset is None:
        print(f"  WARN — unknown weather preset '{preset_name}', skipping",
              file=sys.stderr)
        return False
    world.set_weather(preset)
    return True


# --- Debug visualization ----------------------------------------------------


_DEBUG_COLORS = [
    (0, 255, 0),     # vehicle — green
    (0, 165, 255),   # motorcycle — orange
    (0, 255, 255),   # bicycle — yellow
    (255, 0, 255),   # pedestrian — magenta
]


def draw_debug(bgr: np.ndarray, labels: List[Tuple[int, float, float, float, float]],
               image_w: int, image_h: int) -> np.ndarray:
    for cls_id, xc, yc, w, h in labels:
        x_min = int((xc - w / 2.0) * image_w)
        y_min = int((yc - h / 2.0) * image_h)
        x_max = int((xc + w / 2.0) * image_w)
        y_max = int((yc + h / 2.0) * image_h)
        color = _DEBUG_COLORS[cls_id % len(_DEBUG_COLORS)]
        cv2.rectangle(bgr, (x_min, y_min), (x_max, y_max), color, 2)
        cv2.putText(bgr, CLASS_NAMES[cls_id], (x_min, max(0, y_min - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return bgr


# --- Per-config capture loop -----------------------------------------------


def capture_config(
    world: carla.World,
    bp_lib,
    intersection: Intersection,
    light_idx: int,
    weather_idx: int,
    K: np.ndarray,
    image_w: int, image_h: int, fov: float,
    n_frames: int, ticks_between: int, warmup_ticks: int,
    images_dir: str, labels_dir: str, debug_dir: Optional[str],
    split_name: str,
) -> Tuple[int, int, List[int]]:
    """Spawn camera at this light, warmup, capture N frames, destroy camera.
    Returns (frames_written, labels_written, per_class_counts)."""
    light = intersection.lights[light_idx]
    loc = light.get_location()
    cam_transform = carla.Transform(
        carla.Location(x=loc.x, y=loc.y, z=loc.z + 6.0),
        carla.Rotation(pitch=-25.0, yaw=0.0),  # yaw=0: proven safe (test 04)
    )

    bp = bp_lib.find("sensor.camera.rgb")
    bp.set_attribute("image_size_x", str(image_w))
    bp.set_attribute("image_size_y", str(image_h))
    bp.set_attribute("fov", str(fov))

    cam = world.spawn_actor(bp, cam_transform)
    saved = {"img": None}
    cam.listen(lambda img: saved.update(img=img))

    cam_world_pos = np.array([loc.x, loc.y, loc.z + 6.0])

    frames_written = 0
    labels_written = 0
    class_counts = [0] * len(CLASS_NAMES)

    try:
        # Warmup
        for _ in range(warmup_ticks):
            world.tick()

        for cap_i in range(n_frames):
            for _ in range(ticks_between):
                world.tick()

            img = saved["img"]
            if img is None:
                continue
            arr = np.frombuffer(img.raw_data, dtype=np.uint8).reshape(
                img.height, img.width, 4)
            bgr = arr[..., :3].copy()  # writable

            w2c = np.array(cam.get_transform().get_inverse_matrix())

            labels: List[Tuple[int, float, float, float, float]] = []
            actors = list(world.get_actors().filter("vehicle.*")) + \
                     list(world.get_actors().filter("walker.*"))
            for actor in actors:
                cls_id = classify_actor(actor)
                if cls_id is None:
                    continue
                box = project_bbox_2d(actor, K, w2c, image_w, image_h,
                                      cam_world_pos=cam_world_pos)
                if box is None:
                    continue
                x_min, y_min, x_max, y_max = box
                xc = (x_min + x_max) / 2.0 / image_w
                yc = (y_min + y_max) / 2.0 / image_h
                w = (x_max - x_min) / image_w
                h = (y_max - y_min) / image_h
                labels.append((cls_id, xc, yc, w, h))
                class_counts[cls_id] += 1

            frame_id = (
                f"t{intersection.id:02d}_l{light_idx}_w{weather_idx}_{cap_i:03d}"
            )
            img_path = os.path.join(images_dir, f"{frame_id}.png")
            lbl_path = os.path.join(labels_dir, f"{frame_id}.txt")

            cv2.imwrite(img_path, bgr)
            with open(lbl_path, "w") as f:
                for cls_id, xc, yc, w, h in labels:
                    f.write(f"{cls_id} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}\n")

            if debug_dir is not None:
                debug_img = draw_debug(bgr.copy(), labels, image_w, image_h)
                cv2.imwrite(os.path.join(debug_dir, f"{frame_id}_debug.png"),
                            debug_img)

            frames_written += 1
            labels_written += len(labels)

    finally:
        try:
            cam.stop()
        except Exception:
            pass
        try:
            cam.destroy()
        except Exception:
            pass

    return frames_written, labels_written, class_counts


# --- Main -------------------------------------------------------------------


def main(args) -> int:
    random.seed(args.seed)
    np.random.seed(args.seed)

    images_train = os.path.join(args.out, "images", "train")
    images_val = os.path.join(args.out, "images", "val")
    labels_train = os.path.join(args.out, "labels", "train")
    labels_val = os.path.join(args.out, "labels", "val")
    debug_dir = os.path.join(args.out, "debug") if args.debug_vis else None
    for d in (images_train, images_val, labels_train, labels_val):
        os.makedirs(d, exist_ok=True)
    if debug_dir is not None:
        os.makedirs(debug_dir, exist_ok=True)

    K = build_intrinsic(args.image_w, args.image_h, args.fov)

    # Connect & load map
    client = connect(args.host, args.port)
    world = ensure_map(client, args.map)
    print(f"map: {world.get_map().name}")

    intersections = discover_intersections(world)
    print(f"discovered {len(intersections)} intersection(s)")

    target_intersections = parse_int_list(args.intersections, len(intersections))
    if not target_intersections:
        print("FAIL — empty intersections list", file=sys.stderr)
        return 1
    print(f"sweeping {len(target_intersections)} intersection(s): {target_intersections}")

    weathers = parse_str_list(args.weathers)
    if not weathers:
        print("FAIL — empty weathers list", file=sys.stderr)
        return 1
    print(f"weathers: {weathers}")

    # ----- main run -----
    bp_lib = world.get_blueprint_library()
    vehicles: List[carla.Actor] = []
    walkers: List[carla.Actor] = []
    controllers: List[carla.Actor] = []

    total_train_frames = 0
    total_val_frames = 0
    total_labels = 0
    grand_class_counts = [0] * len(CLASS_NAMES)
    n_skipped_configs = 0

    wall_start = time.time()

    try:
        with synchronous_mode(client) as (world, tm):
            world.tick()

            print(f"spawning up to {args.vehicles} vehicles globally...")
            vehicles = spawn_traffic_global(world, tm, args.vehicles)
            print(f"  {len(vehicles)} vehicles in autopilot")

            if args.walkers > 0:
                print(f"spawning up to {args.walkers} walkers globally...")
                walkers, controllers = spawn_walkers_global(client, world, args.walkers)
                world.tick()  # required before .start() on controllers
                start_walker_ai(world, controllers)
                print(f"  {len(walkers)} walkers, {len(controllers)} controllers")

            # Let the world settle before the first config
            for _ in range(60):
                world.tick()

            n_configs_total = sum(
                len(parse_int_list(args.lights, intersections[ii].n_approaches)) *
                len(weathers)
                for ii in target_intersections
            )
            print(f"total configs to capture: {n_configs_total}")
            config_i = 0

            for ii in target_intersections:
                target = intersections[ii]
                light_ids = parse_int_list(args.lights, target.n_approaches)
                # split: this intersection -> train or val?
                if args.val_stride > 0 and (ii % args.val_stride == 0):
                    split = "val"
                    img_d, lbl_d = images_val, labels_val
                else:
                    split = "train"
                    img_d, lbl_d = images_train, labels_train

                for li in light_ids:
                    for wi, w_name in enumerate(weathers):
                        config_i += 1
                        if not set_weather(world, w_name):
                            n_skipped_configs += 1
                            continue
                        # Let the new weather settle (one tick is enough)
                        world.tick()

                        cfg_t0 = time.time()
                        frames_w, labels_w, cls_counts = capture_config(
                            world=world, bp_lib=bp_lib,
                            intersection=target, light_idx=li, weather_idx=wi,
                            K=K, image_w=args.image_w, image_h=args.image_h, fov=args.fov,
                            n_frames=args.frames_per_config,
                            ticks_between=args.ticks_between_frames,
                            warmup_ticks=args.warmup_ticks_per_config,
                            images_dir=img_d, labels_dir=lbl_d,
                            debug_dir=debug_dir, split_name=split,
                        )
                        cfg_dt = time.time() - cfg_t0

                        for k in range(len(grand_class_counts)):
                            grand_class_counts[k] += cls_counts[k]
                        total_labels += labels_w
                        if split == "train":
                            total_train_frames += frames_w
                        else:
                            total_val_frames += frames_w

                        elapsed = time.time() - wall_start
                        eta = (elapsed / config_i) * (n_configs_total - config_i)
                        print(
                            f"  [{config_i:3d}/{n_configs_total}] t{target.id:02d} l{li} "
                            f"w={w_name:15s} split={split} "
                            f"frames={frames_w} labels={labels_w} "
                            f"({cfg_dt:.1f}s, ETA {eta/60:.1f}m)"
                        )

            # Done — write data.yaml
            data_yaml_path = os.path.join(args.out, "data.yaml")
            abs_out = os.path.abspath(args.out).replace("\\", "/")
            with open(data_yaml_path, "w") as f:
                f.write(f"path: {abs_out}\n")
                f.write("train: images/train\n")
                f.write("val: images/val\n")
                f.write(f"nc: {len(CLASS_NAMES)}\n")
                f.write("names:\n")
                for i, n in enumerate(CLASS_NAMES):
                    f.write(f"  {i}: {n}\n")

            wall_total = time.time() - wall_start
            print()
            print(f"OK — sweep complete in {wall_total/60:.1f} minutes")
            print(f"  train frames: {total_train_frames}")
            print(f"  val frames:   {total_val_frames}")
            print(f"  total labels: {total_labels}")
            print(f"  skipped configs: {n_skipped_configs}")
            print("  per-class label totals:")
            for i, n in enumerate(CLASS_NAMES):
                print(f"    {i} {n:12s}  {grand_class_counts[i]}")
            print(f"  data.yaml: {data_yaml_path}")
            return 0
    finally:
        # Order matters: controllers stop before destroy; walkers after controllers.
        for c in controllers:
            try:
                c.stop()
            except Exception:
                pass
            try:
                c.destroy()
            except Exception:
                pass
        for w in walkers:
            try:
                w.destroy()
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
    p.add_argument("--out", default="./dataset_town05")
    p.add_argument("--map", default="Town05")
    p.add_argument("--intersections", default="all",
                   help="'all' or comma-separated indices like '0,1,5'")
    p.add_argument("--lights", default="all",
                   help="'all' or comma-separated light indices per intersection")
    p.add_argument("--weathers", default="ClearNoon,CloudyNoon,WetNoon",
                   help="comma-separated CARLA WeatherParameters preset names")
    p.add_argument("--frames-per-config", type=int, default=8)
    p.add_argument("--ticks-between-frames", type=int, default=5,
                   help="sim ticks between consecutive captures (decorrelates frames)")
    p.add_argument("--warmup-ticks-per-config", type=int, default=80)
    p.add_argument("--vehicles", type=int, default=100)
    p.add_argument("--walkers", type=int, default=50)
    p.add_argument("--val-stride", type=int, default=5,
                   help="intersection_idx %% val_stride == 0 → val. "
                        "Set to 1 to put everything in val (test-set use). "
                        "Set to 0 to disable val split (everything → train).")
    p.add_argument("--image-w", type=int, default=1280)
    p.add_argument("--image-h", type=int, default=720)
    p.add_argument("--fov", type=float, default=90.0)
    p.add_argument("--debug-vis", action="store_true")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    sys.exit(main(args))
