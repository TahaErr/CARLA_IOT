"""Tests for v2xsim.projection — Sprint 4 module 1.1.

Pure-numpy projection tests (no CARLA, no specs). Covers:
  - Intrinsic matrix construction from FOV
  - Forward projection (world → image) — same path Sprint 2 generator used
  - Inverse projection with ground-plane assumption
  - Forward/inverse round-trip for ground-plane world points
  - Edge cases: behind camera, parallel ray, point at camera origin

Run from repo root:
    pytest tests/test_projection.py -v
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from v2xsim.projection import (
    bbox_bottom_center_to_world,
    image_to_ground_world,
    make_intrinsic_matrix,
    world_to_image,
)


# === Helpers ===============================================================

def _carla_cam_at(
    pos_xyz: tuple[float, float, float],
    pitch_deg: float = 0.0,
    yaw_deg: float = 0.0,
) -> np.ndarray:
    """Build a CARLA-style world_to_cam matrix.

    Mirrors `carla.Transform.get_inverse_matrix()` for a camera at `pos_xyz`
    with the given pitch and yaw (roll = 0). Right-handed world, CARLA
    left-handed camera frame (x=forward, y=right, z=up).
    """
    p = math.radians(pitch_deg)
    y = math.radians(yaw_deg)

    # Camera-to-world rotation: yaw around world-z, then pitch around camera-y.
    cy, sy = math.cos(y), math.sin(y)
    cp, sp = math.cos(p), math.sin(p)
    # Cam axes in world coords (cam +x = forward, cam +y = right, cam +z = up)
    fwd   = np.array([cy * cp,  sy * cp, sp])     # +x_cam in world
    right = np.array([sy,      -cy,      0.0])    # +y_cam in world
    up    = np.array([-cy * sp, -sy * sp, cp])    # +z_cam in world
    R_cam_to_world = np.stack([fwd, right, up], axis=1)  # (3,3)
    t = np.array(pos_xyz)

    cam_to_world = np.eye(4)
    cam_to_world[:3, :3] = R_cam_to_world
    cam_to_world[:3, 3]  = t
    return np.linalg.inv(cam_to_world)


# === Intrinsic ============================================================

def test_intrinsic_matrix_shape_and_principal_point():
    K = make_intrinsic_matrix(image_w=1280, image_h=720, fov_deg=90.0)
    assert K.shape == (3, 3)
    assert K[0, 2] == 640.0  # cx
    assert K[1, 2] == 360.0  # cy


def test_intrinsic_fx_matches_fov():
    """fx = (W/2) / tan(FOV/2) — Sprint 2 dataset generator formula."""
    K = make_intrinsic_matrix(image_w=1280, image_h=720, fov_deg=90.0)
    # tan(45°) = 1 → fx = 640
    assert abs(K[0, 0] - 640.0) < 1e-9


# === Forward projection (world → image) ===================================

def test_world_to_image_point_in_front_of_camera_projects_to_image_centre():
    """A world point directly forward of the camera lands at (cx, cy)."""
    K = make_intrinsic_matrix(1280, 720, 90.0)
    w2c = _carla_cam_at(pos_xyz=(0, 0, 10), pitch_deg=0, yaw_deg=0)
    # 10m forward of camera (along world +x), same height as camera (z=10).
    result = world_to_image(K, w2c, world_pt_xyz=(10.0, 0.0, 10.0))
    assert result is not None
    u, v, depth = result
    assert abs(u - 640.0) < 1e-6
    assert abs(v - 360.0) < 1e-6
    assert abs(depth - 10.0) < 1e-6


def test_world_to_image_point_behind_camera_returns_none():
    K = make_intrinsic_matrix(1280, 720, 90.0)
    w2c = _carla_cam_at(pos_xyz=(0, 0, 10), yaw_deg=0)
    # World point at world (-5, 0, 10) — behind the camera looking +x.
    assert world_to_image(K, w2c, world_pt_xyz=(-5.0, 0.0, 10.0)) is None


# === Inverse projection (image → world) ===================================

def test_image_centre_with_camera_looking_straight_down_maps_to_directly_below():
    """Camera at (0, 0, 10) tilted 90° down (pitch=-90) → centre pixel
    intersects the ground at the spot directly under the camera."""
    K = make_intrinsic_matrix(1280, 720, 90.0)
    w2c = _carla_cam_at(pos_xyz=(0, 0, 10), pitch_deg=-90.0)
    result = image_to_ground_world(K, w2c, u_px=640.0, v_px=360.0, ground_z=0.0)
    assert result is not None
    x, y = result
    assert abs(x) < 1e-6
    assert abs(y) < 1e-6


def test_image_to_ground_returns_none_when_ray_parallel_to_ground():
    """Horizontal camera (pitch=0) looking at horizon — centre pixel ray
    is parallel to the ground plane, no intersection."""
    K = make_intrinsic_matrix(1280, 720, 90.0)
    w2c = _carla_cam_at(pos_xyz=(0, 0, 10), pitch_deg=0.0)
    # Centre pixel — perfectly horizontal ray.
    assert image_to_ground_world(K, w2c, 640.0, 360.0) is None


def test_image_to_ground_returns_none_when_ray_points_up():
    """Camera tilted upward (positive pitch) — ground plane is behind."""
    K = make_intrinsic_matrix(1280, 720, 90.0)
    w2c = _carla_cam_at(pos_xyz=(0, 0, 5), pitch_deg=30.0)
    # Centre pixel → ray goes upward → no ground intersection.
    assert image_to_ground_world(K, w2c, 640.0, 360.0) is None


# === Forward / inverse round-trip =========================================

@pytest.mark.parametrize("ground_pt", [
    (10.0, 0.0),
    (20.0, 5.0),
    (15.0, -3.0),
    (8.0, 12.0),
])
def test_round_trip_ground_point_world_to_image_to_world(ground_pt):
    """Project a known ground point to image, then back through
    image_to_ground_world. Should recover the original within rounding."""
    K = make_intrinsic_matrix(1280, 720, 90.0)
    # Camera 8m up, pitched down 25° (matches Sprint 1's RSU mount).
    w2c = _carla_cam_at(pos_xyz=(0, 0, 8), pitch_deg=-25.0)
    world_in = (ground_pt[0], ground_pt[1], 0.0)
    img = world_to_image(K, w2c, world_in)
    assert img is not None, f"point {ground_pt} not in camera FOV"
    u, v, _ = img
    recovered = image_to_ground_world(K, w2c, u, v, ground_z=0.0)
    assert recovered is not None
    assert abs(recovered[0] - ground_pt[0]) < 1e-4
    assert abs(recovered[1] - ground_pt[1]) < 1e-4


# === bbox bottom-centre convenience =======================================

def test_bbox_bottom_center_uses_bottom_edge():
    """bbox_bottom_center_to_world projects the centre-bottom pixel,
    not the bbox centre."""
    K = make_intrinsic_matrix(1280, 720, 90.0)
    w2c = _carla_cam_at(pos_xyz=(0, 0, 8), pitch_deg=-25.0)
    bbox = (100.0, 200.0, 200.0, 600.0)  # bottom = y=600

    via_bbox = bbox_bottom_center_to_world(K, w2c, bbox)
    via_direct = image_to_ground_world(K, w2c, u_px=150.0, v_px=600.0)
    assert via_bbox == via_direct


def test_bbox_bottom_center_returns_none_when_bottom_above_horizon():
    """If the bbox bottom is above the camera's horizon line, the ray
    is below-the-ground-plane — function returns None."""
    K = make_intrinsic_matrix(1280, 720, 90.0)
    w2c = _carla_cam_at(pos_xyz=(0, 0, 8), pitch_deg=-25.0)
    # bbox high in the frame — bottom-y = 50 (near top of image),
    # ray goes upward, no ground intersection.
    bbox = (600.0, 0.0, 700.0, 50.0)
    assert bbox_bottom_center_to_world(K, w2c, bbox) is None
