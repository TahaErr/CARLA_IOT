"""Roadside Unit (RSU): the perception node at one smart intersection.

Geometry rationale: real pole-mounted intersection cameras sit roughly 6 m up
on the traffic-light arm and look down (~25°) along the approach. We replicate
this by spawning one RGB camera per traffic-light actor in the intersection
group, raised by `POLE_HEIGHT_M` and yawed toward the intersection centroid.

Threading note: `sensor.listen()` callbacks fire from a CARLA worker thread,
so the latest-frame map is guarded by a lock. `snapshot()` returns a shallow
copy that the caller can iterate without holding the lock.
"""
from __future__ import annotations

import math
import threading
from typing import Dict, Tuple

import carla

from .intersections import Intersection

# Mount geometry
POLE_HEIGHT_M = 6.0
CAMERA_PITCH_DEG = -25.0  # downward tilt

# Default optics
DEFAULT_RES: Tuple[int, int] = (800, 600)
DEFAULT_FOV: float = 90.0


class RSU:
    """One roadside unit covering one signalized intersection.

    Camera count == number of traffic lights in the intersection's group
    (typically 4 for a standard 4-way intersection, but we don't hard-code it
    — Town05 has T-intersections too).
    """

    def __init__(
        self,
        world: carla.World,
        intersection: Intersection,
        image_size: Tuple[int, int] = DEFAULT_RES,
        fov: float = DEFAULT_FOV,
    ) -> None:
        self.id = intersection.id
        self.center = intersection.center
        self._cameras: list[carla.Sensor] = []
        self._latest: Dict[int, carla.Image] = {}
        self._lock = threading.Lock()

        bp = world.get_blueprint_library().find("sensor.camera.rgb")
        bp.set_attribute("image_size_x", str(image_size[0]))
        bp.set_attribute("image_size_y", str(image_size[1]))
        bp.set_attribute("fov", str(fov))

        for idx, tl in enumerate(intersection.lights):
            transform = self._camera_transform(tl, self.center)
            cam = world.spawn_actor(bp, transform)
            # `idx=idx` captures by value: avoids the late-binding closure bug
            # where every callback would otherwise see the final loop value.
            cam.listen(lambda img, idx=idx: self._on_frame(idx, img))
            self._cameras.append(cam)

    @staticmethod
    def _camera_transform(tl: carla.TrafficLight, center: carla.Location) -> carla.Transform:
        loc = tl.get_location()
        cam_loc = carla.Location(x=loc.x, y=loc.y, z=loc.z + POLE_HEIGHT_M)
        # face the intersection center
        dx = center.x - cam_loc.x
        dy = center.y - cam_loc.y
        yaw_deg = math.degrees(math.atan2(dy, dx))
        return carla.Transform(
            cam_loc,
            carla.Rotation(pitch=CAMERA_PITCH_DEG, yaw=yaw_deg),
        )

    def _on_frame(self, idx: int, image: carla.Image) -> None:
        with self._lock:
            self._latest[idx] = image

    def snapshot(self) -> Dict[int, carla.Image]:
        """Latest frame per camera, keyed by camera index. Shallow copy."""
        with self._lock:
            return dict(self._latest)

    def destroy(self) -> None:
        """Stop and despawn all cameras. Safe to call more than once."""
        for cam in self._cameras:
            try:
                cam.stop()
            except Exception:
                pass
            try:
                cam.destroy()
            except Exception:
                pass
        self._cameras = []
