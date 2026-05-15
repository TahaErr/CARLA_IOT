"""Camera projection math (Sprint 4 module 1.1).

Pure numpy utilities for translating between three reference frames:
  - **World**: simulation's right-handed cartesian, +x east, +y north,
               +z up (matches Sprint 3 RSU.reference_position_xy_m).
  - **Camera (CARLA / UE4)**: left-handed, +x forward, +y right, +z up.
               This is what `cam.get_transform().get_inverse_matrix()`
               produces in CARLA.
  - **Image (OpenCV)**: pixel coordinates, +u right, +v down, origin at
               top-left.

Two paired primitives:
  - `world_to_image(K, world_to_cam, world_pt)` — forward projection
    (also used by Sprint 2's dataset generator for ground-truth bbox).
  - `image_to_ground_world(K, world_to_cam, u, v, ground_z=0)` — inverse
    projection assuming the detected object stands on the z=ground_z plane.
    The standard heuristic that lets a 2D bbox become a CPM-encodable
    world point: bbox bottom-center → ground-plane intersection.

Sandbox-friendly: no CARLA imports. The CARLA wrapper layer (Module 1.2)
builds `world_to_cam` from `carla.Transform` and feeds it in.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np


# === Intrinsic matrix construction ========================================

def make_intrinsic_matrix(image_w: int, image_h: int, fov_deg: float) -> np.ndarray:
    """Build pinhole K from horizontal FOV.

    Assumes square pixels (fx = fy) and the principal point at image
    centre — the configuration used by CARLA's RGB sensor with its
    default `fov` attribute.

    Returns a (3, 3) numpy array suitable for both projection directions.
    """
    fx = image_w / (2.0 * math.tan(math.radians(fov_deg) / 2.0))
    return np.array([
        [fx,  0.0, image_w / 2.0],
        [0.0, fx,  image_h / 2.0],
        [0.0, 0.0, 1.0],
    ])


# === Forward projection: world → image =====================================

def world_to_image(
    K: np.ndarray,
    world_to_cam: np.ndarray,
    world_pt_xyz: tuple[float, float, float],
) -> Optional[tuple[float, float, float]]:
    """Project a 3D world point into the 2D image.

    Returns `(u, v, depth_m)` where depth is the point's distance along the
    camera's optical axis (CARLA +x), or `None` if the point is behind the
    camera (depth ≤ 0.1 m, with a small clip to avoid numerical blow-up
    near the image plane).

    Coordinate handling matches Sprint 2's dataset generator: the CARLA
    camera frame (x=forward, y=right, z=up) is swizzled to OpenCV image
    convention (x=right, y=down, z=forward) before the K multiplication.
    """
    world_pt = np.array([world_pt_xyz[0], world_pt_xyz[1], world_pt_xyz[2], 1.0])
    p_cam = world_to_cam @ world_pt

    # CARLA cam (x=fwd, y=right, z=up)  →  OpenCV image (x=right, y=down, z=fwd)
    x_cv = p_cam[1]
    y_cv = -p_cam[2]
    z_cv = p_cam[0]
    if z_cv <= 0.1:
        return None

    p_img = K @ np.array([x_cv, y_cv, z_cv])
    return float(p_img[0] / p_img[2]), float(p_img[1] / p_img[2]), float(z_cv)


# === Inverse projection: image → world (ground-plane assumption) ==========

def image_to_ground_world(
    K: np.ndarray,
    world_to_cam: np.ndarray,
    u_px: float,
    v_px: float,
    ground_z: float = 0.0,
) -> Optional[tuple[float, float]]:
    """Cast a ray from one image pixel through the camera and intersect
    it with the world-frame ground plane z = `ground_z`.

    Returns `(world_x, world_y)` on the ground plane, or `None` when:
      - the ray is parallel to the ground (camera looking horizontal), or
      - the intersection would be behind the camera (camera looking up).

    Ground-plane assumption is the standard single-camera depth heuristic:
    given a bbox, we assume the object stands on the ground at its
    bbox-bottom-centre pixel. Wrong for elevated objects (e.g. a truck's
    cabin or a cyclist mid-jump), but defensible for the project's
    intersection-camera geometry where most detections are pedestrians and
    vehicles on a flat surface.

    Args:
        K: (3, 3) intrinsic, see `make_intrinsic_matrix`.
        world_to_cam: (4, 4) extrinsic, world → CARLA camera frame.
        u_px, v_px: image-frame pixel coordinates (OpenCV convention).
        ground_z: world-frame z of the assumed ground plane. Default 0
            matches CARLA's road-surface height in standard maps.
    """
    K_inv = np.linalg.inv(K)
    # Image pixel → OpenCV camera-frame ray (unnormalised; z=1).
    ray_cv = K_inv @ np.array([u_px, v_px, 1.0])

    # OpenCV cam (x=right, y=down, z=fwd) → CARLA cam (x=fwd, y=right, z=up):
    # inverse of the world_to_image swizzle.
    ray_cam = np.array([ray_cv[2], ray_cv[0], -ray_cv[1]])

    # Camera-frame ray → world-frame ray (rotation only — direction, not point).
    cam_to_world = np.linalg.inv(world_to_cam)
    rotation = cam_to_world[:3, :3]
    ray_world = rotation @ ray_cam

    # Camera origin in world frame (translation of cam_to_world).
    cam_origin_world = cam_to_world[:3, 3]

    # Ray-plane intersection: cam_origin + t * ray_world has z = ground_z.
    dz = ray_world[2]
    if abs(dz) < 1e-9:
        return None  # ray parallel to ground

    t = (ground_z - cam_origin_world[2]) / dz
    if t <= 0:
        return None  # plane behind the camera

    world_pt = cam_origin_world + t * ray_world
    return float(world_pt[0]), float(world_pt[1])


def bbox_bottom_center_to_world(
    K: np.ndarray,
    world_to_cam: np.ndarray,
    bbox_xyxy: tuple[float, float, float, float],
    ground_z: float = 0.0,
) -> Optional[tuple[float, float]]:
    """Convenience wrapper: take a 2D bbox (x_min, y_min, x_max, y_max) and
    return the ground-plane world point at its bottom-centre pixel.

    This is the standard ``object stands on the ground at bbox bottom''
    heuristic, mapped through `image_to_ground_world`. Used by Module 1.2
    (CarlaRSU) to turn YOLO outputs into CPM-encodable Detection objects.
    """
    x_min, y_min, x_max, y_max = bbox_xyxy
    u = (x_min + x_max) / 2.0
    v = y_max  # bottom edge in OpenCV convention
    return image_to_ground_world(K, world_to_cam, u, v, ground_z)
