"""Tests for v2xsim.carla_rsu — Sprint 4 module 1.2.

We can't unit-test the CarlaRSU class itself in CI/sandbox (it needs a
running CARLA world), but we deliberately factored out the YOLO-result
→ Detection conversion as a free function `yolo_result_to_detections`
for exactly this reason. These tests use lightweight mock YOLO results
to verify the filtering, projection wiring, and class-index validation.

The CarlaRSU class itself is smoke-tested manually via the Module 1.3
demo script (`scripts/30_broker_demo.py`).

Run from repo root:
    pytest tests/test_carla_rsu.py -v
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from v2xsim.carla_rsu import yolo_result_to_detections
from v2xsim.projection import make_intrinsic_matrix


# === Mock YOLO objects =====================================================
#
# Minimal mocks: any object exposing .cls, .conf, .xyxy with [0] indexing
# returning a scalar (or 4-sequence for xyxy) is what the production code
# pulls out of an ultralytics Results object.

class _Box:
    """One mock detection box."""
    def __init__(self, cls_idx: int, conf: float, xyxy: tuple[float, float, float, float]) -> None:
        self.cls = [cls_idx]
        self.conf = [conf]
        self.xyxy = [xyxy]


class _Result:
    def __init__(self, boxes: list[_Box]) -> None:
        self.boxes = boxes


# === Helpers ===============================================================
#
# (Re-declared here rather than imported from test_projection; tests
# shouldn't reach into one another.)

def _carla_cam_at(
    pos_xyz: tuple[float, float, float],
    pitch_deg: float = 0.0,
    yaw_deg: float = 0.0,
) -> np.ndarray:
    p = math.radians(pitch_deg)
    y = math.radians(yaw_deg)
    cy, sy = math.cos(y), math.sin(y)
    cp, sp = math.cos(p), math.sin(p)
    fwd   = np.array([cy * cp,  sy * cp, sp])
    right = np.array([sy,      -cy,      0.0])
    up    = np.array([-cy * sp, -sy * sp, cp])
    R_cam_to_world = np.stack([fwd, right, up], axis=1)
    cam_to_world = np.eye(4)
    cam_to_world[:3, :3] = R_cam_to_world
    cam_to_world[:3, 3]  = np.array(pos_xyz)
    return np.linalg.inv(cam_to_world)


def _standard_intersection_cam() -> tuple[np.ndarray, np.ndarray]:
    """K + world_to_cam matching Sprint 1's RSU mount geometry."""
    K = make_intrinsic_matrix(1280, 720, 90.0)
    w2c = _carla_cam_at(pos_xyz=(0.0, 0.0, 8.0), pitch_deg=-25.0, yaw_deg=0.0)
    return K, w2c


# Bbox known to back-project to the ground for the standard cam above.
# Bottom y = 600 (well below horizon for a -25° pitched cam from 8 m).
_GOOD_BBOX = (550.0, 400.0, 700.0, 600.0)


# === Tests ================================================================

def test_yolo_result_to_detections_returns_empty_for_empty_result():
    K, w2c = _standard_intersection_cam()
    dets = yolo_result_to_detections(_Result([]), K, w2c)
    assert dets == []


def test_yolo_result_to_detections_passes_high_conf_box():
    K, w2c = _standard_intersection_cam()
    result = _Result([_Box(cls_idx=0, conf=0.85, xyxy=_GOOD_BBOX)])
    dets = yolo_result_to_detections(result, K, w2c, confidence_threshold=0.25)
    assert len(dets) == 1
    assert dets[0].yolo_class_idx == 0
    assert dets[0].confidence == 0.85
    assert dets[0].world_vx_ms == 0.0  # velocity not estimated
    assert dets[0].world_vy_ms == 0.0


def test_yolo_result_to_detections_filters_low_confidence():
    K, w2c = _standard_intersection_cam()
    result = _Result([
        _Box(cls_idx=0, conf=0.85, xyxy=_GOOD_BBOX),
        _Box(cls_idx=1, conf=0.10, xyxy=_GOOD_BBOX),  # below threshold
    ])
    dets = yolo_result_to_detections(result, K, w2c, confidence_threshold=0.25)
    assert len(dets) == 1
    assert dets[0].yolo_class_idx == 0


def test_yolo_result_to_detections_rejects_out_of_range_class():
    """Classes ≥ 4 are outside our detector head and must be skipped."""
    K, w2c = _standard_intersection_cam()
    result = _Result([
        _Box(cls_idx=0, conf=0.9, xyxy=_GOOD_BBOX),
        _Box(cls_idx=7, conf=0.9, xyxy=_GOOD_BBOX),   # invalid
        _Box(cls_idx=-1, conf=0.9, xyxy=_GOOD_BBOX),  # invalid
    ])
    dets = yolo_result_to_detections(result, K, w2c)
    assert len(dets) == 1
    assert dets[0].yolo_class_idx == 0


def test_yolo_result_to_detections_drops_off_screen_up():
    """Bbox whose bottom is above the horizon → no ground intersection."""
    K, w2c = _standard_intersection_cam()
    # Bbox bottom y = 50 — well above the horizon for a -25° pitched cam.
    above_horizon = (600.0, 0.0, 700.0, 50.0)
    result = _Result([_Box(cls_idx=0, conf=0.9, xyxy=above_horizon)])
    dets = yolo_result_to_detections(result, K, w2c)
    assert dets == []


def test_yolo_result_to_detections_handles_all_four_classes():
    """Each YOLO class (0..3) survives filtering when other conditions OK."""
    K, w2c = _standard_intersection_cam()
    result = _Result([_Box(cls_idx=i, conf=0.8, xyxy=_GOOD_BBOX) for i in range(4)])
    dets = yolo_result_to_detections(result, K, w2c)
    assert len(dets) == 4
    assert [d.yolo_class_idx for d in dets] == [0, 1, 2, 3]


def test_yolo_result_to_detections_world_coords_consistent_with_projection():
    """Detection world coords match what bbox_bottom_center_to_world produces directly."""
    from v2xsim.projection import bbox_bottom_center_to_world
    K, w2c = _standard_intersection_cam()
    result = _Result([_Box(cls_idx=0, conf=0.9, xyxy=_GOOD_BBOX)])
    dets = yolo_result_to_detections(result, K, w2c)
    expected = bbox_bottom_center_to_world(K, w2c, _GOOD_BBOX)
    assert expected is not None
    assert dets[0].world_x_m == expected[0]
    assert dets[0].world_y_m == expected[1]


def test_yolo_result_to_detections_filters_malformed_xyxy():
    """A degenerate xyxy (wrong length) is skipped, not crashed on."""
    K, w2c = _standard_intersection_cam()

    class _BadBox:
        cls = [0]
        conf = [0.9]
        xyxy = [(1.0, 2.0)]  # only 2 elements

    result = _Result([_BadBox()])
    dets = yolo_result_to_detections(result, K, w2c)
    assert dets == []


def test_carla_rsu_module_imports_without_carla_sdk():
    """The module itself must be importable in environments without CARLA.

    `yolo_result_to_detections` and the CarlaRSU symbol both need to be
    accessible — only INSTANTIATING CarlaRSU should require CARLA.
    """
    from v2xsim import carla_rsu
    assert hasattr(carla_rsu, "yolo_result_to_detections")
    assert hasattr(carla_rsu, "CarlaRSU")
