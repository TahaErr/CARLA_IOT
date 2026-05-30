"""scripts/51_demo_ui.py — Interactive V2X demo with dearpygui UI.

A single-window 4-panel interface for V2X cooperative-perception
demonstration. Replaces the manual window-shuffling of the
50_visualize_demo.py script:

  +---------------------+-------------------------------+
  |  Config             |  Bird's-eye CARLA view        |
  |  - Map selector     |  (top-down camera, live)      |
  |  - Intersection     |                               |
  |    checkboxes       |                               |
  |  - Fleet sizes      |                               |
  |  - Start / Stop     |                               |
  +---------------------+-------------------------------+
  |  Live Stats         |  RSU Camera                   |
  |  - Sim time         |  - selectable via combo       |
  |  - CPM links        |  - YOLO bbox overlay          |
  |  - Detection links  |                               |
  |  - Fleet counters   |                               |
  +---------------------+-------------------------------+

CARLA's own UE4 window is auto-minimised; everything the user sees
sits inside the dearpygui viewport.

Usage:
    python scripts/51_demo_ui.py \
        --detector runs/detect/runs/detect/yolo26s_carla_multi-2/weights/best.pt

CARLA server must already be running at Epic quality level on
127.0.0.1:2000 before launching this script. Map switching is then
managed from the UI.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import carla
import cv2
import dearpygui.dearpygui as dpg
from ultralytics import YOLO

from v2xsim.carla_utils import connect, ensure_map, synchronous_mode
from v2xsim.intersections import discover_intersections
from v2xsim.walker import (
    spawn_walkers_near_intersections,
    start_walker_controllers,
    stop_walker_controllers,
)
from v2xsim.weather import apply_weather_preset, get_weather_preset_names


# === Layout constants (1920x1080 desktop) =================================
VIEWPORT_W = 1920
NAV_H = 30                  # height of the top navigation bar
VIEWPORT_H = 1040 + NAV_H   # leaves room for taskbar + nav
LEFT_COL_W = 480
RIGHT_COL_W = VIEWPORT_W - LEFT_COL_W
TOP_ROW_H = (VIEWPORT_H - NAV_H) // 2
BOTTOM_ROW_H = (VIEWPORT_H - NAV_H) - TOP_ROW_H

# Camera frame texture targets
BIRD_TEX_W = RIGHT_COL_W - 30      # padding
BIRD_TEX_H = TOP_ROW_H - 60
RSU_TEX_W = RIGHT_COL_W - 30
RSU_TEX_H = BOTTOM_ROW_H - 90

# === Map metadata (hard-coded to avoid CARLA round-trip on UI startup) ====
# Approximate signalised-intersection counts. Actual list is discovered
# when the simulation thread connects.
KNOWN_MAPS = {
    "Town01": 12,
    "Town02": 8,
    "Town03": 18,
    "Town04": 14,
    "Town05": 15,
    "Town07": 6,
    "Town10HD_Opt": 7,
}

YOLO_CLASS_VISUALS = {
    0: ((255, 200, 0),   "vehicle"),
    1: ((0, 255, 255),   "motorcycle"),
    2: ((0, 255, 0),     "bicycle"),
    3: ((128, 0, 255),   "pedestrian"),
}


# === Shared state between UI thread and sim thread ========================

@dataclass
class SimConfig:
    map_name: str = "Town05"
    weather: str = "ClearNoon"
    camera_rsu_indices: list = field(default_factory=lambda: [0, 7])
    n_vehicles: int = 30
    cav_percentage: int = 50
    n_walkers: int = 60
    duration_s: int = 150
    broadcast_range_m: float = 80.0
    detector_path: str = ""


class SharedState:
    """Thread-safe state shared between UI and sim threads."""

    def __init__(self):
        self.lock = threading.Lock()
        # Frames (numpy BGR uint8 arrays, or None when no fresh frame)
        self.bird_frame: Optional[np.ndarray] = None
        self.rsu_frames: dict = {}              # rsu_idx -> annotated BGR
        # Stats (updated each sim tick)
        self.stats: dict = {}                   # global / simulation-wide
        self.rsu_stats: dict = {}               # rsu_idx -> dict of metrics
        # Status messages
        self.status: str = "Idle"
        self.error_msg: Optional[str] = None
        # Discovered intersections after sim start (so UI dropdowns can be
        # repopulated with the actual list)
        self.discovered_intersection_count: Optional[int] = None


# === Win32 helper: minimise CARLA UE4 window ==============================

def minimise_carla_window() -> bool:
    """Find the CARLA UE4 native window and minimise it.

    Returns True if a window was found and minimised. No-op on non-Windows
    platforms.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return False
    user32 = ctypes.windll.user32
    found = []
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value.lower()
        if ("carla" in title and "ue4" in title) or "carlaue4" in title:
            found.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    SW_MINIMIZE = 6
    for hwnd in found:
        user32.ShowWindow(hwnd, SW_MINIMIZE)
    return bool(found)


# === Simulation thread ====================================================

def project_actor_to_image(actor_loc, cam_transform, img_w, img_h, fov_deg=110.0):
    """Project a CARLA world point to (u, v) image pixel coordinates.

    Returns (u, v) if the actor is in front of the camera AND inside
    the image rectangle; returns None otherwise. CARLA's camera-local
    frame uses UE4 axes (+X forward, +Y right, +Z up); the standard
    pinhole convention is (+Z forward, +X right, +Y down); the axes
    are swapped accordingly.
    """
    fx = img_w / (2.0 * math.tan(math.radians(fov_deg) / 2.0))
    fy = fx
    cx = img_w / 2.0
    cy = img_h / 2.0
    inv_mat = np.array(cam_transform.get_inverse_matrix())
    wp = np.array([actor_loc.x, actor_loc.y, actor_loc.z, 1.0])
    cp = inv_mat @ wp
    x_pin = cp[1]
    y_pin = -cp[2]
    z_pin = cp[0]
    if z_pin < 0.5:
        return None
    u = fx * (x_pin / z_pin) + cx
    v = fy * (y_pin / z_pin) + cy
    if not (0.0 <= u < img_w and 0.0 <= v < img_h):
        return None
    return (u, v)


def actor_in_yolo_bboxes(actor_loc, yolo_bboxes_xyxy, cam_transform,
                          img_w, img_h, fov_deg=110.0):
    """True iff the actor projects into any of the supplied YOLO bboxes.

    Used to drive the BLUE 3D detection links so they reflect what the
    detector actually reported, instead of a geometric frustum
    approximation.
    """
    pt = project_actor_to_image(actor_loc, cam_transform, img_w, img_h, fov_deg)
    if pt is None:
        return False
    u, v = pt
    for x1, y1, x2, y2 in yolo_bboxes_xyxy:
        if x1 <= u <= x2 and y1 <= v <= y2:
            return True
    return False


def actor_in_camera_view(cam_transform, actor_loc, max_range_m=70.0, fov_deg=110.0):
    cam_loc = cam_transform.location
    dx = actor_loc.x - cam_loc.x
    dy = actor_loc.y - cam_loc.y
    horizontal_dist = (dx * dx + dy * dy) ** 0.5
    if horizontal_dist > max_range_m or horizontal_dist < 1.5:
        return False
    angle_to_actor = math.atan2(dy, dx)
    cam_yaw = math.radians(cam_transform.rotation.yaw)
    angle_diff = abs(angle_to_actor - cam_yaw)
    while angle_diff > math.pi:
        angle_diff = 2 * math.pi - angle_diff
    return angle_diff < math.radians(fov_deg / 2)


def run_simulation(shared: SharedState, stop_event: threading.Event,
                    config: SimConfig) -> None:
    """The simulation loop. Runs in a background thread."""
    shared.status = "Connecting to CARLA..."
    client = connect("127.0.0.1", 2000)
    client.set_timeout(60.0)

    shared.status = f"Loading {config.map_name}..."
    world = ensure_map(client, config.map_name)
    try:
        client.reload_world(False)
        world = client.get_world()
    except Exception:
        pass
    for a in world.get_actors():
        if a.type_id.startswith(("vehicle.", "walker.", "sensor.",
                                  "controller.ai.walker")):
            try:
                a.destroy()
            except Exception:
                pass

    minimise_carla_window()

    rng = np.random.default_rng(0)
    import random as _random
    py_rng = _random.Random(0)

    # Tracking for cleanup
    rsu_cameras: list = []
    rsu_frame_buffers: list = []
    rsu_frame_locks: list = []
    bird_camera = None
    bird_frame_buf = [None]
    bird_frame_lock = threading.Lock()
    vehicles: list = []
    walkers: list = []
    walker_controllers: list = []

    try:
        with synchronous_mode(client) as (world, tm):
            world.tick()

            shared.status = f"Applying weather: {config.weather}"
            apply_weather_preset(world, config.weather)
            world.tick()

            intersections = discover_intersections(world)
            shared.discovered_intersection_count = len(intersections)
            shared.status = f"Discovered {len(intersections)} intersections"

            # Validate selected camera indices
            camera_idx = [i for i in config.camera_rsu_indices
                          if 0 <= i < len(intersections)]
            if not camera_idx:
                camera_idx = [0]

            camera_centroids = []
            for i in camera_idx:
                t = intersections[i]
                cx = sum(l.get_location().x for l in t.lights) / len(t.lights)
                cy = sum(l.get_location().y for l in t.lights) / len(t.lights)
                cz = sum(l.get_location().z for l in t.lights) / len(t.lights)
                camera_centroids.append((cx, cy, cz))

            # === Spawn RSU cameras at selected intersections ============
            # One YOLO instance PER camera-equipped RSU. ByteTrack keeps
            # per-camera tracker state that must NOT be shared across
            # cameras (object IDs would collide). RTX 5080 VRAM cost is
            # ~50 MB per yolo26s model so 2-3 RSUs is fine.
            shared.status = "Loading YOLO models (one per RSU)..."
            rsu_models = []
            for _ in camera_idx:
                m = YOLO(config.detector_path)
                try:
                    import torch
                    if torch.cuda.is_available():
                        m.to("cuda:0")
                except ImportError:
                    pass
                rsu_models.append(m)

            cam_bp = world.get_blueprint_library().find("sensor.camera.rgb")
            cam_bp.set_attribute("image_size_x", str(RSU_TEX_W))
            cam_bp.set_attribute("image_size_y", str(RSU_TEX_H))
            cam_bp.set_attribute("fov", "110")

            rsu_meta: list = []
            for i, (cx, cy, cz) in zip(camera_idx, camera_centroids):
                light = intersections[i].lights[0]
                pole_loc = light.get_location()
                # Offset the camera forward (towards the intersection
                # centroid) by CAM_FORWARD_OFFSET metres so that the
                # pole's own white control-box structure does not sit
                # at the bottom of the camera frame and get mis-detected
                # as a vehicle.
                dx_to_centroid = cx - pole_loc.x
                dy_to_centroid = cy - pole_loc.y
                d_to_centroid = (dx_to_centroid * dx_to_centroid
                                  + dy_to_centroid * dy_to_centroid) ** 0.5
                if d_to_centroid > 0.5:
                    ux = dx_to_centroid / d_to_centroid
                    uy = dy_to_centroid / d_to_centroid
                else:
                    ux, uy = 1.0, 0.0
                CAM_FORWARD_OFFSET = 2.5
                cam_loc = carla.Location(
                    x=pole_loc.x + ux * CAM_FORWARD_OFFSET,
                    y=pole_loc.y + uy * CAM_FORWARD_OFFSET,
                    z=pole_loc.z + 8.0,
                )
                dx, dy = cx - cam_loc.x, cy - cam_loc.y
                horiz = (dx * dx + dy * dy) ** 0.5
                if horiz < 1e-3:
                    yaw_deg, pitch_deg = 0.0, -85.0
                else:
                    yaw_deg = math.degrees(math.atan2(dy, dx))
                    pitch_deg = -math.degrees(math.atan2(cam_loc.z - (cz + 0.3), horiz))
                pitch_deg = max(-60.0, min(-15.0, pitch_deg))
                cam_tx = carla.Transform(cam_loc,
                                          carla.Rotation(pitch=pitch_deg, yaw=yaw_deg))
                cam = world.spawn_actor(cam_bp, cam_tx)
                buf = [None]
                lk = threading.Lock()

                def make_listener(b, l):
                    def on_frame(image):
                        arr = np.frombuffer(image.raw_data, dtype=np.uint8).reshape(
                            image.height, image.width, 4)
                        bgr = arr[..., :3].copy()
                        with l:
                            b[0] = bgr
                    return on_frame

                cam.listen(make_listener(buf, lk))
                rsu_cameras.append(cam)
                rsu_frame_buffers.append(buf)
                rsu_frame_locks.append(lk)
                rsu_meta.append({"idx": i, "transform": cam_tx,
                                  "location": pole_loc})

            # === Bird's-eye camera at centroid ==========================
            shared.status = "Spawning bird's-eye camera..."
            ccx = sum(c[0] for c in camera_centroids) / len(camera_centroids)
            ccy = sum(c[1] for c in camera_centroids) / len(camera_centroids)
            ccz = sum(c[2] for c in camera_centroids) / len(camera_centroids)
            if len(camera_centroids) >= 2:
                dx = camera_centroids[0][0] - camera_centroids[1][0]
                dy = camera_centroids[0][1] - camera_centroids[1][1]
                sep = (dx * dx + dy * dy) ** 0.5
                bird_alt = max(80.0, min(220.0, sep * 1.6 + 60.0))
            else:
                bird_alt = 120.0
            bird_bp = world.get_blueprint_library().find("sensor.camera.rgb")
            bird_bp.set_attribute("image_size_x", str(BIRD_TEX_W))
            bird_bp.set_attribute("image_size_y", str(BIRD_TEX_H))
            bird_bp.set_attribute("fov", "90")
            bird_tx = carla.Transform(
                carla.Location(x=ccx, y=ccy, z=ccz + bird_alt),
                carla.Rotation(pitch=-85.0, yaw=0.0),
            )
            bird_camera = world.spawn_actor(bird_bp, bird_tx)

            def bird_listener(image):
                arr = np.frombuffer(image.raw_data, dtype=np.uint8).reshape(
                    image.height, image.width, 4)
                bgr = arr[..., :3].copy()
                with bird_frame_lock:
                    bird_frame_buf[0] = bgr

            bird_camera.listen(bird_listener)

            # === Spawn vehicles ========================================
            shared.status = f"Spawning {config.n_vehicles} vehicles..."
            cam_xy = [(c[0], c[1]) for c in camera_centroids]

            def min_dist_to_cam(sp):
                x, y = sp.location.x, sp.location.y
                return min(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                            for cx, cy in cam_xy)

            spawn_points = world.get_map().get_spawn_points()
            spawn_points.sort(key=min_dist_to_cam)
            pool = spawn_points[:min(len(spawn_points), config.n_vehicles * 3)]
            py_rng.shuffle(pool)
            spawn_points = pool[:config.n_vehicles]
            vehicle_bps = [bp for bp in world.get_blueprint_library().filter("vehicle.*")
                           if int(bp.get_attribute("number_of_wheels")) == 4]
            cav_target_count = int(config.n_vehicles * config.cav_percentage / 100)
            cav_ids: set = set()
            hdv_meta: dict = {}
            for i, sp in enumerate(spawn_points):
                bp = py_rng.choice(vehicle_bps)
                v = world.try_spawn_actor(bp, sp)
                if v is None:
                    continue
                v.set_autopilot(True, tm.get_port())
                vehicles.append(v)
            # Assign CAV / HDV roles
            py_rng.shuffle(vehicles)
            for v in vehicles[:cav_target_count]:
                cav_ids.add(v.id)
            for v in vehicles[cav_target_count:]:
                hdv_meta[v.id] = py_rng.choice(
                    ["attentive", "distracted", "aggressive_hostile"])

            # === Spawn walkers =========================================
            shared.status = f"Spawning {config.n_walkers} walkers..."
            if config.n_walkers > 0:
                walkers, walker_controllers = spawn_walkers_near_intersections(
                    client=client, world=world,
                    intersection_centroids=camera_centroids,
                    n_walkers=config.n_walkers,
                    radius_m=80.0, seed=300,
                )
                world.tick()
                for _ in range(20):
                    world.tick()
                start_walker_controllers(walker_controllers, world)
                world.tick()

            # === Main loop ============================================
            ticks_per_sec = 20
            total_ticks = int(config.duration_s * ticks_per_sec)
            DEBUG_LIFETIME = 0.12
            t_start = time.time()
            tick_idx = 0
            total_cpm_tx = 0
            shared.status = "Running"

            COLOR_RSU = carla.Color(255, 215, 0)
            # CARLA's Epic-quality renderer treats debug-line colour as
            # emissive HDR input, so any moderately bright RGB triggers
            # post-process bloom and the lines look like neon laser beams.
            # To avoid that we pick near-black values whose magnitude is
            # below the bloom threshold; the lines are still clearly
            # tinted but no longer glow. If you switch CARLA to a Low
            # quality preset (no bloom), feel free to brighten them back.
            COLOR_CPM = carla.Color(70, 15, 15)         # very dark maroon
            COLOR_DET = carla.Color(20, 35, 70)         # very dark navy

            # Slimmer lines further reduce the bloomed pixel area
            THICK_CPM = 0.05
            THICK_DET = 0.05

            # Persistence window for the blue detection lines. ByteTrack
            # alone is reactive — it only labels boxes that the detector
            # produced this frame. To prevent the line flicker the user
            # sees when YOLO drops a detection for one or two frames,
            # we keep our own per-(RSU, actor) last-seen tick and draw
            # the blue line for any actor that was seen within the last
            # PERSISTENCE_TICKS ticks (1 s @ 20 Hz).
            PERSISTENCE_TICKS = 20
            actor_last_seen: dict = {}

            while not stop_event.is_set() and tick_idx < total_ticks:
                world.tick()
                tick_idx += 1

                # --- Build 3D debug overlay (still useful for the bird's-
                # eye camera image, since CARLA draws debug on rendered
                # frames too) ---
                cav_positions = []
                for v in vehicles:
                    if not v.is_alive:
                        continue
                    if v.id in cav_ids:
                        cav_positions.append((v.id, v.get_location()))

                # RSU markers are NOT drawn via CARLA debug API any more
                # — same contamination problem as the CPM/detection
                # lines. They are drawn as filled circles directly onto
                # the bird's-eye display frame via OpenCV later in the
                # tick.

                # Count CPM links — but DO NOT draw any CARLA debug lines.
                # CARLA debug draw_line writes into every camera sensor's
                # render, which contaminates the YOLO input frame and
                # causes bbox misses. All visualisation is now done via
                # OpenCV post-processing on the bird's-eye and RSU
                # camera display frames below. This keeps the raw frames
                # passed to YOLO completely clean.
                active_cpm_links = 0
                for inter in intersections:
                    rsu_loc = inter.lights[0].get_location()
                    for cav_id, cav_loc in cav_positions:
                        dx = cav_loc.x - rsu_loc.x
                        dy = cav_loc.y - rsu_loc.y
                        if (dx * dx + dy * dy) ** 0.5 <= config.broadcast_range_m:
                            active_cpm_links += 1
                total_cpm_tx += active_cpm_links

                # Detection links (camera-equipped RSUs)
                detected_count = 0
                # Detection links (BLUE) are drawn inside the YOLO loop
                # below — see comments there. `detected_count` is
                # incremented there.
                detected_count = 0

                # --- RSU camera frames + YOLO with ByteTrack -------------
                # `.track(persist=True)` keeps a per-camera tracker state
                # so an object that vanishes for a few frames (occluded,
                # exposure flicker, motion blur) is still considered the
                # same instance when it reappears. ByteTrack's default
                # `track_buffer=30` means up to 1.5 s of lost frames at
                # 20 Hz are tolerated. The blue 3D detection lines now
                # stay attached to the actor across these gaps because
                # the tracker fills in the missing bboxes from the
                # Kalman filter's predicted position.
                rsu_det_counts = {}
                rsu_track_counts = {}
                rsu_specific_stats = {}      # rsu_idx -> dict of metrics
                for i, rm in enumerate(rsu_meta):
                    with rsu_frame_locks[i]:
                        frame = rsu_frame_buffers[i][0]
                    if frame is None:
                        continue
                    display = frame.copy()
                    result = rsu_models[i].track(
                        frame, conf=0.25,
                        persist=True,
                        tracker="bytetrack.yaml",
                        verbose=False,
                    )[0]
                    n_dets = 0
                    unique_tracks = set()
                    # Collect bboxes in image coords for the 3D projection
                    # step below.
                    yolo_bboxes_xyxy = []
                    for box in result.boxes:
                        cls_idx = int(box.cls[0])
                        if cls_idx not in YOLO_CLASS_VISUALS:
                            continue
                        x1f, y1f, x2f, y2f = (float(v) for v in box.xyxy[0])
                        x1, y1, x2, y2 = int(x1f), int(y1f), int(x2f), int(y2f)
                        yolo_bboxes_xyxy.append((x1f, y1f, x2f, y2f))
                        color, label = YOLO_CLASS_VISUALS[cls_idx]
                        cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
                        conf = float(box.conf[0])
                        # Track ID may be None on the very first frame
                        # or for detections the tracker just promoted.
                        if box.id is not None:
                            track_id = int(box.id[0])
                            unique_tracks.add(track_id)
                            text = f"#{track_id} {label} {conf:.2f}"
                        else:
                            text = f"{label} {conf:.2f}"
                        (tw, th), _ = cv2.getTextSize(
                            text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
                        cv2.rectangle(display, (x1, y1 - th - 4),
                                       (x1 + tw + 4, y1), color, -1)
                        cv2.putText(display, text, (x1 + 2, y1 - 3),
                                     cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                                     (0, 0, 0), 1, cv2.LINE_AA)
                        n_dets += 1
                    rsu_det_counts[rm["idx"]] = n_dets
                    rsu_track_counts[rm["idx"]] = len(unique_tracks)
                    with shared.lock:
                        shared.rsu_frames[rm["idx"]] = display

                    # --- 3D BLUE detection links: project every HDV /
                    # walker into this RSU's image plane; draw a line
                    # only for those that fall inside an actual YOLO
                    # bbox. Replaces the previous geometric frustum
                    # approximation that produced inconsistent links.
                    #
                    # Line origin is placed 5m ABOVE the camera lens so
                    # that the camera's own FOV (pitched downward) does
                    # not include the line start — only the very end of
                    # the line, near the actor on the ground, can enter
                    # the camera frame. This minimises the line's
                    # contamination of the YOLO inference image.
                    #
                    # Actor-level persistence: even if YOLO drops a
                    # detection for a frame or two, the blue line stays
                    # drawn for PERSISTENCE_TICKS ticks after the actor
                    # was last seen. The per-(rsu, actor) timestamp is
                    # stored in `actor_last_seen`.
                    cam_tx = rm["transform"]
                    cam_loc = cam_tx.location
                    rsu_idx = rm["idx"]
                    pole_loc_3d = rm["location"]
                    img_w_local, img_h_local = RSU_TEX_W, RSU_TEX_H
                    line_anchor = (img_w_local // 2, 0)   # top centre
                    RED_BGR  = (70, 70, 230)              # CPM links
                    BLUE_BGR = (220, 140, 70)             # detection links

                    # --- RED CPM links FIRST (under the blue ones so the
                    # detection links remain visually dominant). Drawn
                    # from this RSU's pole to every CAV inside its
                    # broadcast radius, projected through THIS camera's
                    # intrinsics. CAVs outside the camera's FOV simply
                    # don't render — same as in reality, where the RSU
                    # broadcasts to vehicles it cannot directly see.
                    for cav_id, cav_loc in cav_positions:
                        dx = cav_loc.x - pole_loc_3d.x
                        dy = cav_loc.y - pole_loc_3d.y
                        if (dx * dx + dy * dy) ** 0.5 > config.broadcast_range_m:
                            continue
                        pt = project_actor_to_image(
                            cav_loc, cam_tx, img_w_local, img_h_local,
                            fov_deg=110.0)
                        if pt is not None:
                            cv2.line(display, line_anchor,
                                     (int(pt[0]), int(pt[1])),
                                     RED_BGR, 1, cv2.LINE_AA)

                    # --- BLUE detection links (drawn ON TOP of red, so
                    # the detected-actor relationship reads first).
                    # Pass 1: refresh last-seen timestamps for actors
                    # whose 3D position projects into a current YOLO
                    # bbox. Pass 2: draw a blue line for any actor whose
                    # last-seen tick is within the persistence window.
                    for v in vehicles:
                        if not v.is_alive or v.id in cav_ids:
                            continue
                        v_loc = v.get_location()
                        if yolo_bboxes_xyxy and actor_in_yolo_bboxes(
                                v_loc, yolo_bboxes_xyxy, cam_tx,
                                img_w_local, img_h_local, fov_deg=110.0):
                            actor_last_seen[(rsu_idx, v.id)] = tick_idx
                        last_tick = actor_last_seen.get(
                            (rsu_idx, v.id), -10**9)
                        if tick_idx - last_tick <= PERSISTENCE_TICKS:
                            pt = project_actor_to_image(
                                v_loc, cam_tx, img_w_local, img_h_local,
                                fov_deg=110.0)
                            if pt is not None:
                                cv2.line(display, line_anchor,
                                         (int(pt[0]), int(pt[1])),
                                         BLUE_BGR, 1, cv2.LINE_AA)
                                detected_count += 1
                    for w in walkers:
                        if not w.is_alive:
                            continue
                        w_loc = w.get_location()
                        if yolo_bboxes_xyxy and actor_in_yolo_bboxes(
                                w_loc, yolo_bboxes_xyxy, cam_tx,
                                img_w_local, img_h_local, fov_deg=110.0):
                            actor_last_seen[(rsu_idx, w.id)] = tick_idx
                        last_tick = actor_last_seen.get(
                            (rsu_idx, w.id), -10**9)
                        if tick_idx - last_tick <= PERSISTENCE_TICKS:
                            pt = project_actor_to_image(
                                w_loc, cam_tx, img_w_local, img_h_local,
                                fov_deg=110.0)
                            if pt is not None:
                                cv2.line(display, line_anchor,
                                         (int(pt[0]), int(pt[1])),
                                         BLUE_BGR, 1, cv2.LINE_AA)
                                detected_count += 1
                    # --- Per-RSU stats (this tick) -------------------
                    # Counted only across actors actually inside a YOLO
                    # bbox this frame; ignores persistence-based draws.
                    det_hdv = 0
                    det_ped = 0
                    if yolo_bboxes_xyxy:
                        for v in vehicles:
                            if not v.is_alive or v.id in cav_ids:
                                continue
                            if actor_in_yolo_bboxes(
                                    v.get_location(), yolo_bboxes_xyxy,
                                    cam_tx, img_w_local, img_h_local,
                                    fov_deg=110.0):
                                det_hdv += 1
                        for w in walkers:
                            if not w.is_alive:
                                continue
                            if actor_in_yolo_bboxes(
                                    w.get_location(), yolo_bboxes_xyxy,
                                    cam_tx, img_w_local, img_h_local,
                                    fov_deg=110.0):
                                det_ped += 1
                    # CAVs inside this RSU's broadcast range
                    cavs_in_range = 0
                    for _, cl in cav_positions:
                        dxv = cl.x - pole_loc_3d.x
                        dyv = cl.y - pole_loc_3d.y
                        if (dxv * dxv + dyv * dyv) ** 0.5 <= config.broadcast_range_m:
                            cavs_in_range += 1
                    rsu_specific_stats[rsu_idx] = {
                        "YOLO detections (this tick)": rsu_det_counts.get(rsu_idx, 0),
                        "Tracked objects": rsu_track_counts.get(rsu_idx, 0),
                        "Detected vehicles": det_hdv,
                        "Detected pedestrians": det_ped,
                        "CAVs in broadcast range": cavs_in_range,
                    }

                    # Push the now-annotated display frame back to the
                    # shared state (overwrites the bbox-only frame
                    # written above).
                    with shared.lock:
                        shared.rsu_frames[rm["idx"]] = display

                # --- Bird's-eye frame: OpenCV overlay ----------------
                # The bird's-eye sensor frame is post-processed here:
                # RED lines from every RSU pole to every CAV within
                # broadcast range, BLUE lines from every camera-equipped
                # RSU to every actor recently detected by it.
                with bird_frame_lock:
                    bird_frame = bird_frame_buf[0]
                if bird_frame is not None:
                    bird_display = bird_frame.copy()
                    RED_BGR = (70, 70, 230)
                    BLUE_BGR = (220, 140, 70)

                    def _proj_bird(loc):
                        pt = project_actor_to_image(
                            loc, bird_tx, BIRD_TEX_W, BIRD_TEX_H,
                            fov_deg=90.0)
                        if pt is None:
                            return None
                        return (int(pt[0]), int(pt[1]))

                    # --- YELLOW RSU markers (all signalised intersections) ---
                    YELLOW_BGR = (0, 215, 255)
                    cam_idx_set = set(camera_idx)
                    for i, inter in enumerate(intersections):
                        pole_loc = inter.lights[0].get_location()
                        rsu_uv = _proj_bird(carla.Location(
                            x=pole_loc.x, y=pole_loc.y,
                            z=pole_loc.z + 6.0))
                        if rsu_uv is None:
                            continue
                        radius = 9 if i in cam_idx_set else 6
                        cv2.circle(bird_display, rsu_uv, radius,
                                    YELLOW_BGR, -1, cv2.LINE_AA)
                        cv2.circle(bird_display, rsu_uv, radius + 1,
                                    (0, 0, 0), 1, cv2.LINE_AA)

                    # --- RED CPM links (all RSU poles -> all CAVs) ---
                    for inter in intersections:
                        pole_loc = inter.lights[0].get_location()
                        pole_uv = _proj_bird(carla.Location(
                            x=pole_loc.x, y=pole_loc.y,
                            z=pole_loc.z + 6.0))
                        if pole_uv is None:
                            continue
                        for cav_id, cav_loc in cav_positions:
                            dx = cav_loc.x - pole_loc.x
                            dy = cav_loc.y - pole_loc.y
                            if (dx * dx + dy * dy) ** 0.5 > config.broadcast_range_m:
                                continue
                            cav_uv = _proj_bird(carla.Location(
                                x=cav_loc.x, y=cav_loc.y,
                                z=cav_loc.z + 0.5))
                            if cav_uv is not None:
                                cv2.line(bird_display, pole_uv, cav_uv,
                                         RED_BGR, 1, cv2.LINE_AA)

                    # --- BLUE detection links from camera-equipped RSUs
                    for rm in rsu_meta:
                        pole_loc = rm["location"]
                        rsu_idx = rm["idx"]
                        pole_uv = _proj_bird(carla.Location(
                            x=pole_loc.x, y=pole_loc.y,
                            z=pole_loc.z + 6.0))
                        if pole_uv is None:
                            continue
                        for v in vehicles:
                            if not v.is_alive or v.id in cav_ids:
                                continue
                            last_tick = actor_last_seen.get(
                                (rsu_idx, v.id), -10**9)
                            if tick_idx - last_tick > PERSISTENCE_TICKS:
                                continue
                            v_uv = _proj_bird(v.get_location())
                            if v_uv is not None:
                                cv2.line(bird_display, pole_uv, v_uv,
                                         BLUE_BGR, 1, cv2.LINE_AA)
                        for w in walkers:
                            if not w.is_alive:
                                continue
                            last_tick = actor_last_seen.get(
                                (rsu_idx, w.id), -10**9)
                            if tick_idx - last_tick > PERSISTENCE_TICKS:
                                continue
                            w_uv = _proj_bird(w.get_location())
                            if w_uv is not None:
                                cv2.line(bird_display, pole_uv, w_uv,
                                         BLUE_BGR, 1, cv2.LINE_AA)

                    with shared.lock:
                        shared.bird_frame = bird_display

                # --- Stats --------------------------------------------
                sim_t_now = tick_idx / ticks_per_sec
                wall_now = time.time() - t_start
                n_walker_alive = sum(1 for w in walkers if w.is_alive)
                n_att = sum(1 for p in hdv_meta.values() if p == "attentive")
                n_dis = sum(1 for p in hdv_meta.values() if p == "distracted")
                n_hos = sum(1 for p in hdv_meta.values() if p == "aggressive_hostile")
                with shared.lock:
                    shared.stats = {
                        "Map / Weather": f"{config.map_name} / {config.weather}",
                        "Sim time (s)": f"{sim_t_now:.1f} / {config.duration_s}",
                        "Wall time (s)": f"{wall_now:.1f}",
                        "Wall : sim ratio": f"{wall_now / max(sim_t_now, 0.001):.2f}x",
                        "Tick": f"{tick_idx} / {total_ticks}",
                        "_sep1": None,
                        "Signalised intersections": str(len(intersections)),
                        "Camera-equipped RSUs": str(len(rsu_meta)),
                        "Broadcast range (m)": f"{config.broadcast_range_m:.0f}",
                        "Active CPM links": str(active_cpm_links),
                        "RSU detection links": str(detected_count),
                        "Total CPM TX": f"{total_cpm_tx:,}",
                        "_sep2": None,
                        "CAVs (V2X-equipped)": str(len(cav_ids)),
                        "HDVs attentive": str(n_att),
                        "HDVs distracted": str(n_dis),
                        "HDVs aggressive": str(n_hos),
                        "Pedestrians active": f"{n_walker_alive} / {len(walkers)}",
                    }
                    # Per-RSU stats live in their own dict, displayed
                    # inside each RSU tab instead of cluttering the
                    # global stats panel.
                    shared.rsu_stats = rsu_specific_stats

            shared.status = "Stopped" if stop_event.is_set() else "Finished"

    except Exception as e:
        shared.error_msg = f"{e}\n\n{traceback.format_exc()}"
        shared.status = "Error"
    finally:
        # Cleanup
        try:
            if bird_camera is not None:
                bird_camera.stop()
                bird_camera.destroy()
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
        for c in walker_controllers:
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


# === Sim controller ======================================================

class SimController:
    def __init__(self):
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.shared = SharedState()
        self.last_config: Optional[SimConfig] = None

    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, config: SimConfig):
        if self.is_running():
            return
        self.stop_event.clear()
        self.shared = SharedState()
        self.last_config = config

        def _target():
            try:
                run_simulation(self.shared, self.stop_event, config)
            except Exception as e:
                self.shared.error_msg = f"{e}\n\n{traceback.format_exc()}"
                self.shared.status = "Error"

        self.thread = threading.Thread(target=_target, daemon=True)
        self.thread.start()

    def stop(self):
        if not self.is_running():
            return
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)
            self.thread = None


# === UI helpers ==========================================================

def bgr_to_dpg(bgr: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
    if bgr.shape[1] != target_w or bgr.shape[0] != target_h:
        bgr = cv2.resize(bgr, (target_w, target_h))
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return (rgb.astype(np.float32) / 255.0).flatten()


def build_ui(controller: SimController, args):
    # Texture registry — bird's-eye is fixed-size, RSU textures are
    # created dynamically per camera-equipped RSU when Start is pressed.
    blank_bird = np.zeros(BIRD_TEX_W * BIRD_TEX_H * 3, dtype=np.float32)
    with dpg.texture_registry(show=False, tag="texture_registry"):
        dpg.add_raw_texture(width=BIRD_TEX_W, height=BIRD_TEX_H,
                            default_value=blank_bird,
                            format=dpg.mvFormat_Float_rgb, tag="bird_tex")

    # --- Top navigation bar (always visible) -----------------------------
    # Tab bar that drives view switching: "Home" shows the 4-window
    # layout below; each "RSU N" tab hides the home windows and shows a
    # fullscreen detail page for that RSU.
    with dpg.window(label="Nav", tag="top_nav_window",
                     pos=(0, 0), width=VIEWPORT_W, height=NAV_H,
                     no_title_bar=True, no_close=True, no_collapse=True,
                     no_resize=True, no_move=True, no_scrollbar=True):
        def on_nav_tab(sender, app_data):
            try:
                alias = dpg.get_item_alias(app_data) or ""
            except Exception:
                alias = ""
            if alias == "nav_tab_home" or not alias:
                show_view("home")
            elif alias.startswith("nav_tab_rsu_"):
                idx_str = alias.replace("nav_tab_rsu_", "")
                show_view(f"rsu_{idx_str}")
        with dpg.tab_bar(tag="nav_tab_bar", callback=on_nav_tab):
            dpg.add_tab(label="Home", tag="nav_tab_home")
            # RSU N tabs added dynamically in on_start()

    # --- Config window (top-left, shifted down by NAV_H) -----------------
    with dpg.window(label="Configuration", tag="config_window",
                     pos=(0, NAV_H), width=LEFT_COL_W, height=TOP_ROW_H,
                     no_close=True, no_collapse=True, no_resize=True,
                     no_move=True):
        dpg.add_text("V2X Demo Configuration", color=(255, 220, 100))
        dpg.add_separator()
        dpg.add_combo(list(KNOWN_MAPS.keys()), default_value="Town05",
                      label="Map", tag="map_combo",
                      callback=lambda s, a: refresh_intersection_checkboxes(a))
        dpg.add_combo(list(get_weather_preset_names()),
                      default_value="ClearNoon", label="Weather",
                      tag="weather_combo")
        dpg.add_separator()
        dpg.add_text("Camera RSUs (pick 1-3):", color=(180, 220, 255))
        with dpg.child_window(tag="rsu_checkbox_container",
                              width=-1, height=140, border=False):
            pass
        refresh_intersection_checkboxes("Town05")

        dpg.add_separator()
        dpg.add_slider_int(label="Vehicles", default_value=30,
                           min_value=10, max_value=100, tag="n_vehicles_slider")
        dpg.add_slider_int(label="CAV %", default_value=50,
                           min_value=0, max_value=100, tag="cav_pct_slider")
        dpg.add_slider_int(label="Walkers", default_value=60,
                           min_value=0, max_value=150, tag="n_walkers_slider")
        dpg.add_slider_int(label="Duration (s)", default_value=120,
                           min_value=20, max_value=600, tag="duration_slider")
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(label="  Start  ", tag="start_btn",
                           callback=lambda: on_start(controller, args))
            dpg.add_button(label="  Stop  ", tag="stop_btn",
                           callback=lambda: on_stop(controller),
                           enabled=False)

        dpg.add_separator()
        dpg.add_text("Status: Idle", tag="status_text")
        dpg.add_text("", tag="error_text", color=(255, 100, 100), wrap=440)

    # --- Bird's-eye window (top-right) ------------------------------------
    with dpg.window(label="CARLA Bird's-eye View", tag="bird_window",
                     pos=(LEFT_COL_W, NAV_H), width=RIGHT_COL_W, height=TOP_ROW_H,
                     no_close=True, no_collapse=True, no_resize=True,
                     no_move=True):
        dpg.add_image("bird_tex")

    # --- Stats window (bottom-left) ---------------------------------------
    with dpg.window(label="Live Statistics", tag="stats_window",
                     pos=(0, NAV_H + TOP_ROW_H), width=LEFT_COL_W, height=BOTTOM_ROW_H,
                     no_close=True, no_collapse=True, no_resize=True,
                     no_move=True):
        dpg.add_text("V2X Live Statistics", color=(255, 220, 100))
        dpg.add_separator()
        with dpg.group(tag="stats_group"):
            dpg.add_text("(idle)", tag="stats_placeholder",
                          color=(150, 150, 150))

    # --- RSU camera window (bottom-right) — tabbed -----------------------
    # One tab per camera-equipped RSU, each tab holds the live camera
    # frame plus that RSU's own statistics. Tabs are created dynamically
    # in on_start() once the user has chosen which intersections are
    # camera-equipped.
    with dpg.window(label="RSU Cameras (YOLO + per-RSU stats)",
                     tag="rsu_window",
                     pos=(LEFT_COL_W, NAV_H + TOP_ROW_H), width=RIGHT_COL_W,
                     height=BOTTOM_ROW_H,
                     no_close=True, no_collapse=True, no_resize=True,
                     no_move=True):
        dpg.add_tab_bar(tag="rsu_tab_bar")
        # Placeholder shown before Start is pressed.
        dpg.add_text("(no RSU cameras configured — pick at least one in "
                     "the Configuration panel and press Start)",
                     tag="rsu_placeholder",
                     color=(150, 150, 150))


def refresh_intersection_checkboxes(map_name):
    n = KNOWN_MAPS.get(map_name, 15)
    # Clear existing
    children = dpg.get_item_children("rsu_checkbox_container", 1)
    if children:
        for c in children:
            dpg.delete_item(c)
    # Re-add — 3 columns
    for i in range(n):
        with dpg.group(parent="rsu_checkbox_container", horizontal=True):
            dpg.add_checkbox(label=f"RSU {i}",
                              default_value=(i in (0, 7)),
                              tag=f"rsu_chk_{i}")


def collect_camera_indices():
    indices = []
    map_name = dpg.get_value("map_combo")
    n = KNOWN_MAPS.get(map_name, 15)
    for i in range(n):
        if dpg.does_item_exist(f"rsu_chk_{i}") and dpg.get_value(f"rsu_chk_{i}"):
            indices.append(i)
    # Limit to 3 to avoid VRAM spike + UI clutter
    return indices[:3] if indices else [0]


# Global tracking for view-switching: list of currently created detail
# window tags (one per camera-equipped RSU). Populated in on_start().
_detail_windows: list = []
_nav_rsu_tabs: list = []
HOME_WINDOWS = ["config_window", "bird_window", "stats_window", "rsu_window"]


def show_view(view_name: str):
    """Switch between the Home 4-pane layout and a fullscreen RSU
    detail page. `view_name` is either 'home' or 'rsu_{idx}'."""
    is_home = (view_name == "home")
    for w in HOME_WINDOWS:
        if dpg.does_item_exist(w):
            dpg.configure_item(w, show=is_home)
    target_detail = None
    if view_name.startswith("rsu_"):
        idx_str = view_name.replace("rsu_", "")
        target_detail = f"detail_window_{idx_str}"
    for w in _detail_windows:
        if dpg.does_item_exist(w):
            dpg.configure_item(w, show=(w == target_detail))


def on_start(controller, args):
    config = SimConfig(
        map_name=dpg.get_value("map_combo"),
        weather=dpg.get_value("weather_combo"),
        camera_rsu_indices=collect_camera_indices(),
        n_vehicles=dpg.get_value("n_vehicles_slider"),
        cav_percentage=dpg.get_value("cav_pct_slider"),
        n_walkers=dpg.get_value("n_walkers_slider"),
        duration_s=dpg.get_value("duration_slider"),
        detector_path=args.detector,
    )
    controller.start(config)
    dpg.configure_item("start_btn", enabled=False)
    dpg.configure_item("stop_btn", enabled=True)

    # --- Dynamic tab bar: one tab per camera-equipped RSU --------------
    # Clean up any tabs left from a previous run, plus any stale RSU
    # textures from a previous configuration (different intersections).
    existing_tabs = dpg.get_item_children("rsu_tab_bar", 1) or []
    for tab in existing_tabs:
        try:
            dpg.delete_item(tab)
        except Exception:
            pass
    # Stale nav RSU tabs and detail windows from a previous run
    global _detail_windows, _nav_rsu_tabs
    for t in _nav_rsu_tabs:
        if dpg.does_item_exist(t):
            try:
                dpg.delete_item(t)
            except Exception:
                pass
    _nav_rsu_tabs = []
    for w in _detail_windows:
        if dpg.does_item_exist(w):
            try:
                dpg.delete_item(w)
            except Exception:
                pass
    _detail_windows = []
    # Stale textures
    reg_children = dpg.get_item_children("texture_registry", 1) or []
    for child in reg_children:
        try:
            alias = dpg.get_item_alias(child) or ""
        except Exception:
            alias = ""
        if alias.startswith("rsu_tex_"):
            try:
                dpg.delete_item(child)
            except Exception:
                pass

    if dpg.does_item_exist("rsu_placeholder"):
        dpg.configure_item("rsu_placeholder", show=False)

    blank_rsu = np.zeros(RSU_TEX_W * RSU_TEX_H * 3, dtype=np.float32)

    # Sizes for the fullscreen detail layout
    detail_pos_y = NAV_H
    detail_h = VIEWPORT_H - NAV_H
    detail_img_w = VIEWPORT_W - 30           # widget width (texture upscaled)
    detail_img_h = int(detail_img_w * RSU_TEX_H / RSU_TEX_W)
    detail_stats_h = detail_h - detail_img_h - 70   # remaining vertical space

    for rsu_idx in config.camera_rsu_indices:
        tex_tag = f"rsu_tex_{rsu_idx}"
        if not dpg.does_item_exist(tex_tag):
            dpg.add_raw_texture(width=RSU_TEX_W, height=RSU_TEX_H,
                                default_value=blank_rsu,
                                format=dpg.mvFormat_Float_rgb,
                                tag=tex_tag,
                                parent="texture_registry")
        # Home-view tab (inside rsu_window's tab bar)
        tab_tag = f"rsu_tab_{rsu_idx}"
        dpg.add_tab(label=f"RSU {rsu_idx}", parent="rsu_tab_bar",
                    tag=tab_tag)
        dpg.add_image(tex_tag, parent=tab_tag)
        dpg.add_separator(parent=tab_tag)
        stats_tag = f"rsu_stats_{rsu_idx}"
        dpg.add_group(tag=stats_tag, parent=tab_tag)
        dpg.add_text("(waiting for data...)", color=(150, 150, 150),
                     parent=stats_tag)

        # Top-nav RSU tab — clicking it switches to the detail view
        nav_tab_tag = f"nav_tab_rsu_{rsu_idx}"
        dpg.add_tab(label=f"RSU {rsu_idx}", parent="nav_tab_bar",
                    tag=nav_tab_tag)
        _nav_rsu_tabs.append(nav_tab_tag)

        # Fullscreen detail window for this RSU — hidden by default
        detail_tag = f"detail_window_{rsu_idx}"
        dpg.add_window(label=f"RSU {rsu_idx} — Detail",
                       tag=detail_tag,
                       pos=(0, detail_pos_y),
                       width=VIEWPORT_W, height=detail_h,
                       no_close=True, no_collapse=True,
                       no_resize=True, no_move=True,
                       show=False)
        dpg.add_text(f"RSU {rsu_idx} — Fullscreen camera + statistics",
                     parent=detail_tag, color=(255, 220, 100))
        dpg.add_separator(parent=detail_tag)
        # Reuse the same texture as the home-view tab; the image widget
        # upscales it to detail_img_w x detail_img_h.
        dpg.add_image(tex_tag, parent=detail_tag,
                      width=detail_img_w, height=detail_img_h)
        dpg.add_separator(parent=detail_tag)
        dpg.add_text(f"Statistics — RSU {rsu_idx}",
                     parent=detail_tag, color=(180, 220, 255))
        detail_stats_tag = f"detail_stats_{rsu_idx}"
        dpg.add_group(tag=detail_stats_tag, parent=detail_tag)
        dpg.add_text("(waiting for data...)", color=(150, 150, 150),
                     parent=detail_stats_tag)
        _detail_windows.append(detail_tag)

    # Make sure we're showing the Home view after Start
    show_view("home")
    if dpg.does_item_exist("nav_tab_home"):
        dpg.set_value("nav_tab_bar", "nav_tab_home")


def on_stop(controller):
    controller.stop()
    dpg.configure_item("start_btn", enabled=True)
    dpg.configure_item("stop_btn", enabled=False)


def ui_update_loop(controller):
    """Called each UI frame: pull latest frames + stats from shared state."""
    shared = controller.shared
    with shared.lock:
        bird_frame = shared.bird_frame
        rsu_frames = dict(shared.rsu_frames)
        stats = dict(shared.stats)
        rsu_stats = {k: dict(v) for k, v in shared.rsu_stats.items()}
        status = shared.status
        err = shared.error_msg

    # Status
    dpg.set_value("status_text", f"Status: {status}")
    if err:
        dpg.set_value("error_text", err)
    else:
        dpg.set_value("error_text", "")

    # Bird's-eye texture
    if bird_frame is not None:
        try:
            dpg.set_value("bird_tex", bgr_to_dpg(bird_frame, BIRD_TEX_W, BIRD_TEX_H))
        except Exception:
            pass

    # Per-RSU camera tabs: update each texture and stats group
    for rsu_idx, frame in rsu_frames.items():
        tex_tag = f"rsu_tex_{rsu_idx}"
        if dpg.does_item_exist(tex_tag):
            try:
                dpg.set_value(tex_tag,
                              bgr_to_dpg(frame, RSU_TEX_W, RSU_TEX_H))
            except Exception:
                pass
    for rsu_idx, rsu_metrics in rsu_stats.items():
        # Update both the home-tab stats group AND the detail-view stats
        # group, since they show the same content.
        for stats_tag in (f"rsu_stats_{rsu_idx}",
                          f"detail_stats_{rsu_idx}"):
            if not dpg.does_item_exist(stats_tag):
                continue
            existing = dpg.get_item_children(stats_tag, 1) or []
            for c in existing:
                try:
                    dpg.delete_item(c)
                except Exception:
                    pass
            for k, v in rsu_metrics.items():
                try:
                    with dpg.group(parent=stats_tag, horizontal=True):
                        dpg.add_text(k + ":", color=(180, 180, 180))
                        dpg.add_text(str(v), color=(100, 220, 255))
                except Exception:
                    pass

    # Stats — clear and rebuild
    children = dpg.get_item_children("stats_group", 1)
    if children:
        for c in children:
            dpg.delete_item(c)
    if stats:
        for k, v in stats.items():
            if k.startswith("_sep"):
                dpg.add_separator(parent="stats_group")
                continue
            with dpg.group(parent="stats_group", horizontal=True):
                dpg.add_text(k + ":", color=(180, 180, 180))
                dpg.add_text(v, color=(100, 220, 255))
    else:
        dpg.add_text("(idle)", parent="stats_group", color=(150, 150, 150))

    # Re-enable Start button if sim finished
    if not controller.is_running():
        dpg.configure_item("start_btn", enabled=True)
        dpg.configure_item("stop_btn", enabled=False)


# === Main ================================================================

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--detector", required=True)
    args = p.parse_args()

    if not os.path.isfile(args.detector):
        print(f"FAIL — detector not found: {args.detector}", file=sys.stderr)
        return 1

    controller = SimController()

    dpg.create_context()
    dpg.create_viewport(title="V2X Cooperative Perception Demo",
                         width=VIEWPORT_W, height=VIEWPORT_H)
    dpg.setup_dearpygui()
    build_ui(controller, args)
    dpg.show_viewport()

    while dpg.is_dearpygui_running():
        ui_update_loop(controller)
        dpg.render_dearpygui_frame()

    controller.stop()
    dpg.destroy_context()
    return 0


if __name__ == "__main__":
    sys.exit(main())
