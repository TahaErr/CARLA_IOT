"""CARLA-bound RSU wrapper (Sprint 4 module 1.2).

Couples the Sprint 3 RSU pipeline to a real CARLA world: spawns one
overhead camera on a chosen traffic-light pole, loads a fine-tuned YOLO
detector, runs the full
    frame → infer → project → Detection[] → CPM → broker
loop on each call to `tick()`.

Architectural notes:

  - **Single camera per RSU.** PROGRESS.md §3.2.3 documents the CARLA
    0.9.16 Windows multi-camera bug and the deliberate single-camera
    architectural choice. Mount geometry matches the proven-safe config
    (z + 6 m above the pole, pitch = -25°, yaw = 0°, FOV = 90°).
  - **Lazy CARLA imports.** The `carla` module is imported inside
    `__init__` so this module can be loaded in environments without
    the CARLA SDK (CI / sandbox / unit tests of the free function below).
  - **Cached extrinsic.** `world_to_cam` is computed once on the first
    tick after the camera has populated its first frame. Intersection
    RSUs don't move during a simulation, so caching is correct and saves
    one CARLA API call per tick across ~100k-tick ablation runs.
  - **Velocity not estimated.** Detections emit `vx = vy = 0`. Inter-frame
    association / Kalman tracking is deferred to a later sprint; the CAV
    fusion module (proposal §4.1.1) already handles unknown velocity via
    the message-age extrapolation rule.

Test strategy: `yolo_result_to_detections` is a module-level free
function — fully unit-tested in `tests/test_carla_rsu.py` with mock YOLO
results. The CarlaRSU class itself requires a CARLA world; smoke-tested
manually via the Module 1.3 demo script.
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from .broker import Broker
from .compute_budget import BudgetTracker
from .projection import bbox_bottom_center_to_world, make_intrinsic_matrix
from .rsu import RSU, Detection

if TYPE_CHECKING:
    import carla
    from .intersections import Intersection


# === Detection conversion (CARLA-agnostic, unit-tested) ====================

def yolo_result_to_detections(
    yolo_result: Any,
    K: np.ndarray,
    world_to_cam: np.ndarray,
    confidence_threshold: float = 0.25,
) -> list[Detection]:
    """Convert an Ultralytics YOLO Results object into a Detection list.

    Filters by confidence threshold, rejects classes outside the 4-class
    head (0..3), and drops any detection whose bbox bottom-centre cannot
    be back-projected to the ground plane (off-screen up, behind camera).

    Pure-Python: no CARLA, no ultralytics types at runtime — accepts
    anything with a `.boxes` iterable whose elements expose `.cls`, `.conf`
    and `.xyxy` (each a length-1 sequence containing a scalar / 4-tuple).
    """
    detections: list[Detection] = []
    for box in yolo_result.boxes:
        conf = float(box.conf[0])
        if conf < confidence_threshold:
            continue
        cls_idx = int(box.cls[0])
        if not 0 <= cls_idx < 4:
            continue  # outside the 4-class detector head
        xyxy = tuple(float(v) for v in box.xyxy[0])
        if len(xyxy) != 4:
            continue
        world_pt = bbox_bottom_center_to_world(K, world_to_cam, xyxy)
        if world_pt is None:
            continue
        detections.append(Detection(
            yolo_class_idx=cls_idx,
            confidence=conf,
            world_x_m=world_pt[0],
            world_y_m=world_pt[1],
        ))
    return detections


# === CarlaRSU =============================================================

class CarlaRSU:
    """One CARLA-bound RSU: camera + YOLO detector + Sprint 3 pipeline.

    Construction blocks on spawning the camera actor and loading the
    detector weights; expect ~1-3 s startup cost per RSU. Once running,
    `tick()` is the only hot path; `destroy()` cleans up the camera
    actor on shutdown (always call it, even on exceptions).
    """

    def __init__(
        self,
        world: "carla.World",
        intersection: "Intersection",
        light_idx: int,
        broker: Broker,
        detector_path: str,
        station_id: Optional[int] = None,
        compute_budget: Optional[BudgetTracker] = None,
        image_size: tuple[int, int] = (1280, 720),
        fov_deg: float = 90.0,
        confidence_threshold: float = 0.25,
        device: str = "cuda:0",
        sensor_tick_s: float = 0.0,
    ) -> None:
        """Spawn the camera + load the detector.

        Args:
            world: connected `carla.World`.
            intersection: Sprint 1's `Intersection` dataclass.
            light_idx: which traffic-light pole at the intersection to
                mount on (0 = first; range checked).
            broker: shared `Broker` instance — every RSU writes to it.
            detector_path: path to a fine-tuned YOLO .pt file. Sprint 2's
                output: `runs/.../yolo26s_carla_multi-2/weights/best.pt`.
            station_id: ETSI station identifier. Defaults to the
                intersection's index (which is deterministic across
                CARLA restarts thanks to Sprint 1's sorted discovery).
            compute_budget: optional shared `BudgetTracker` for proposal
                §4.4's edge-compute ablation arm.
            image_size, fov_deg: camera optics. Defaults match the
                Sprint 1 / Sprint 2 dataset generator.
            confidence_threshold: passed to both YOLO and the post-filter.
            device: "cuda:0" / "cpu" / etc. Falls back to CPU if CUDA
                isn't available (matches Sprint 2's GPU detection).
        """
        # Lazy imports so this module can be loaded without CARLA / ultralytics.
        import carla
        from ultralytics import YOLO

        if not 0 <= light_idx < len(intersection.lights):
            raise IndexError(
                f"light_idx {light_idx} out of range for intersection "
                f"{intersection.id} ({len(intersection.lights)} lights)"
            )

        self.station_id = station_id if station_id is not None else intersection.id
        self.broker = broker
        self.confidence_threshold = confidence_threshold
        self.image_size = image_size
        self.fov_deg = fov_deg

        # === Camera mount ==============================================
        light = intersection.lights[light_idx]
        loc = light.get_location()
        bp_lib = world.get_blueprint_library()
        bp = bp_lib.find("sensor.camera.rgb")
        bp.set_attribute("image_size_x", str(image_size[0]))
        bp.set_attribute("image_size_y", str(image_size[1]))
        bp.set_attribute("fov", str(fov_deg))
        # Render only as often as the RSU consumes a frame (one per CPM
        # period). In synchronous mode a camera with sensor_tick > 0 skips
        # rendering on the in-between ticks, cutting GPU cost with no effect
        # on the pipeline (the RSU already only reads a frame per CPM period).
        if sensor_tick_s and sensor_tick_s > 0.0:
            bp.set_attribute("sensor_tick", str(sensor_tick_s))
        transform = carla.Transform(
            carla.Location(x=loc.x, y=loc.y, z=loc.z + 6.0),
            carla.Rotation(pitch=-25.0, yaw=0.0),
        )
        self._camera: Optional["carla.Sensor"] = world.spawn_actor(bp, transform)

        # Latest-frame slot — CARLA worker thread writes, tick() reads.
        self._latest_frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._camera.listen(self._on_frame)

        # === Detector ==================================================
        self._device = self._resolve_device(device)
        self._model = YOLO(detector_path)
        if self._device.startswith("cuda"):
            self._model.to(self._device)

        # === Projection cache ==========================================
        self._K = make_intrinsic_matrix(image_size[0], image_size[1], fov_deg)
        self._world_to_cam: Optional[np.ndarray] = None  # lazy-init on first tick

        # === Sprint 3 pipeline =========================================
        self._rsu_core = RSU(
            station_id=self.station_id,
            reference_position_xy_m=(loc.x, loc.y),
            compute_budget=compute_budget,
        )

    # --- internal helpers ----------------------------------------------

    @staticmethod
    def _resolve_device(requested: str) -> str:
        """Return `requested` if CUDA is available; otherwise fall back to CPU."""
        if not requested.startswith("cuda"):
            return requested
        try:
            import torch
            if torch.cuda.is_available():
                return requested
        except ImportError:
            pass
        return "cpu"

    def _on_frame(self, image: "carla.Image") -> None:
        """CARLA sensor callback — fires on the simulator's worker thread.

        We BGRA → BGR and stash the latest frame in a lock-protected slot.
        """
        arr = np.frombuffer(image.raw_data, dtype=np.uint8).reshape(
            image.height, image.width, 4
        )
        bgr = arr[..., :3].copy()
        with self._lock:
            self._latest_frame = bgr

    def _ensure_extrinsic(self) -> np.ndarray:
        """Return `world_to_cam`, computing and caching it on first call."""
        if self._world_to_cam is None:
            assert self._camera is not None, "camera destroyed before tick"
            self._world_to_cam = np.array(
                self._camera.get_transform().get_inverse_matrix()
            )
        return self._world_to_cam

    # --- main entry point ----------------------------------------------

    def tick(
        self,
        sim_time_ms: float,
        receivers: list[tuple[str, float]],
    ) -> bool:
        """One simulation tick.

        Returns True if a CPM was published. False indicates either:
          - no camera frame yet (camera spawned but no images received), or
          - budget-gated drop (compute_budget rejected this tick's cost).

        Inference cost is the real wall-clock time around the YOLO call —
        this is what's submitted to the BudgetTracker, so the budget gate
        reflects actual hardware behaviour, not assumed numbers.
        """
        with self._lock:
            frame = self._latest_frame
        if frame is None:
            return False

        t0 = time.perf_counter()
        result = self._model(
            frame,
            conf=self.confidence_threshold,
            device=self._device,
            verbose=False,
        )[0]
        inference_ms = (time.perf_counter() - t0) * 1000.0

        detections = yolo_result_to_detections(
            result,
            self._K,
            self._ensure_extrinsic(),
            confidence_threshold=self.confidence_threshold,
        )

        return self._rsu_core.tick(
            broker=self.broker,
            detections=detections,
            inference_cost_ms=inference_ms,
            receivers=receivers,
            sim_time_ms=sim_time_ms,
        )

    # --- lifecycle ------------------------------------------------------

    def destroy(self) -> None:
        """Stop the camera and despawn the actor. Idempotent."""
        if self._camera is None:
            return
        try:
            self._camera.stop()
        except Exception:
            pass
        try:
            self._camera.destroy()
        except Exception:
            pass
        self._camera = None
