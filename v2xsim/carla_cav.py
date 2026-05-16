"""CARLA-bound CAV wrapper (Sprint 4 module 4).

Couples the Sprint 4 Module 2 `CAVCore` to a real CARLA `Vehicle` actor:
ego-state polling, broker-delivery pulling, optional ground-truth-cone
local-sensor synthesis, decision computation.

The wrapper deliberately does NOT apply the decision to the actor —
the ablation runner (Sprint 4 Module 5) is responsible for translating
`CAVDecision.action` to a `carla.VehicleControl` (or letting Traffic
Manager handle it). This keeps the wrapper testable without a CARLA
session and lets the runner experiment with different control policies
(autopilot override vs. TM speed-difference, etc.) without touching
this class.

Architectural notes:

  - **Local sensor**: optional. When enabled, synthesises `LocalDetection`s
    from CARLA ground truth within a 50 m × 90° cone in front of the
    ego (proposal §4.1.1 references "AV's own local sensor"). The cone
    geometry is itself a CARLA-free pure function — fully unit-tested.
  - **Class mapping**: CARLA blueprint type_id strings → ETSI class
    names (passengerCar / motorcycle / pedalCycle / pedestrian). Two-
    wheeler blueprints are an explicit allow-list to match the Sprint 2
    4-class detector head.
  - **Lazy CARLA imports**. Same pattern as `carla_rsu.py`.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Optional

from .broker import Broker
from .cav import CAVCore, CAVDecision, LocalDetection
from .cpm import decode_cpm

if TYPE_CHECKING:
    import carla


# === CARLA blueprint → ETSI class mapping ===============================

# Two-wheeler allow-lists for CARLA 0.9.16 (Sprint 2 verified blueprints).
_MOTORCYCLE_KEYWORDS = ("yamaha", "kawasaki", "harley", "vespa")
_BICYCLE_KEYWORDS = ("crossbike", "century", "omafiets")


def carla_type_to_etsi(type_id: str) -> Optional[str]:
    """Map a CARLA actor `type_id` to the 4-class ETSI string.

    Returns None for actor types outside the 4-class scheme (e.g.
    sensors, traffic lights, props). Matches the YOLO detector head:
    passengerCar / motorcycle / pedalCycle / pedestrian.
    """
    if type_id.startswith("walker.pedestrian"):
        return "pedestrian"
    if type_id.startswith("vehicle."):
        lower = type_id.lower()
        if any(k in lower for k in _MOTORCYCLE_KEYWORDS):
            return "motorcycle"
        if any(k in lower for k in _BICYCLE_KEYWORDS):
            return "pedalCycle"
        return "passengerCar"
    return None


# === Ground-truth cone (pure-Python, unit-testable) =====================

def actors_in_cone(
    ego_x: float,
    ego_y: float,
    ego_yaw_deg: float,
    actors: list,
    cone_range_m: float,
    cone_angle_deg: float,
    class_filter: Optional[tuple[str, ...]] = None,
    ego_actor_id: Optional[int] = None,
) -> list[LocalDetection]:
    """Build LocalDetections from CARLA ground truth within a vision cone.

    Pure-Python: `actors` need only expose `.id`, `.type_id`,
    `.get_location()` (returning something with .x/.y), and
    `.get_velocity()` (.x/.y). This makes the function trivially
    testable with lightweight mocks.

    Args:
        ego_x, ego_y: ego world position.
        ego_yaw_deg: ego world yaw (CARLA / UE4 convention, deg).
        actors: list of CARLA actor objects (or mocks).
        cone_range_m: max distance to include an actor.
        cone_angle_deg: full cone aperture (cone is ±half centred on yaw).
        class_filter: if given, only ETSI classes in this set are included.
        ego_actor_id: if given, skip the actor whose .id matches (avoids
            self-detection when the ego is in the actors list).
    """
    ego_yaw_rad = math.radians(ego_yaw_deg)
    half_cone_rad = math.radians(cone_angle_deg / 2.0)
    cos_half = math.cos(half_cone_rad)
    fwd_x = math.cos(ego_yaw_rad)
    fwd_y = math.sin(ego_yaw_rad)

    result: list[LocalDetection] = []
    for actor in actors:
        if ego_actor_id is not None and getattr(actor, "id", None) == ego_actor_id:
            continue

        etsi_class = carla_type_to_etsi(getattr(actor, "type_id", ""))
        if etsi_class is None:
            continue
        if class_filter is not None and etsi_class not in class_filter:
            continue

        loc = actor.get_location()
        dx = loc.x - ego_x
        dy = loc.y - ego_y
        d = math.hypot(dx, dy)
        if d < 0.1 or d > cone_range_m:
            continue

        # Cosine of angle between ego forward and the actor direction.
        cos_to_actor = (dx * fwd_x + dy * fwd_y) / d
        if cos_to_actor < cos_half:
            continue

        vel = actor.get_velocity()
        result.append(LocalDetection(
            object_class=etsi_class,
            x_m=loc.x, y_m=loc.y,
            vx_ms=vel.x, vy_ms=vel.y,
            confidence=1.0,
        ))
    return result


# === CarlaCAV ===========================================================

class CarlaCAV:
    """One CAV: CARLA Vehicle actor + CAVCore state machine.

    Construction does NOT take any CARLA-only types in its signature —
    everything is duck-typed so this class can also be exercised by
    a structured smoke test if useful. CARLA imports are deferred.

    Per-tick contract (caller orchestrates):
      1. (optional) update list of in-world actors for local sensor
      2. cav.tick(sim_time_ms, other_actors) → CAVDecision
      3. caller applies decision.action to its `actor` via apply_control
         or TM commands (this class doesn't impose a control policy)
    """

    def __init__(
        self,
        vehicle: "carla.Vehicle",
        broker: Broker,
        cav_core: Optional[CAVCore] = None,
        local_sensor_enabled: bool = False,
        local_sensor_range_m: float = 50.0,
        local_sensor_angle_deg: float = 90.0,
        local_sensor_class_filter: tuple[str, ...] = ("passengerCar", "pedestrian"),
    ) -> None:
        """Args:
            vehicle: CARLA Vehicle actor.
            broker: shared Broker.
            cav_core: pre-configured CAVCore. If None, creates a default
                one using `cav_<actor_id>` as the id.
            local_sensor_enabled: if True, synthesise local detections
                from `other_actors` passed to `tick()` each frame.
            local_sensor_range_m, local_sensor_angle_deg: vision cone.
            local_sensor_class_filter: ETSI classes the local sensor
                will emit. Defaults to passenger cars + pedestrians, which
                is the proposal's main safety target.
        """
        self.actor = vehicle
        self.broker = broker
        self.local_sensor_enabled = local_sensor_enabled
        self.local_sensor_range_m = local_sensor_range_m
        self.local_sensor_angle_deg = local_sensor_angle_deg
        self.local_sensor_class_filter = tuple(local_sensor_class_filter)

        self.id = f"cav_{vehicle.id}"
        self._core = cav_core if cav_core is not None else CAVCore(cav_id=self.id)
        self.decode_errors = 0
        self._alive = True

    # --- lifecycle / liveness -----------------------------------------

    def is_alive(self) -> bool:
        """Check whether the underlying CARLA actor is still usable.

        CARLA may destroy a Vehicle actor mid-simulation (driving off the
        map, nav-mesh underflow, etc.). Once destroyed, any further method
        call on the actor raises RuntimeError. This method returns False
        as soon as we've observed either an `is_alive=False` actor attr
        or a "destroyed actor" RuntimeError on a previous tick.
        """
        if not self._alive:
            return False
        try:
            # CARLA 0.9.13+ exposes `actor.is_alive` directly.
            if hasattr(self.actor, "is_alive") and not self.actor.is_alive:
                self._alive = False
        except Exception:
            self._alive = False
        return self._alive

    # --- setup ---------------------------------------------------------

    def register_rsu(self, rsu_id: str, world_xy: tuple[float, float]) -> None:
        """Forward to the underlying CAVCore. Call once per RSU at setup."""
        self._core.register_rsu(rsu_id, world_xy)

    # --- main entry point ---------------------------------------------

    def tick(
        self,
        sim_time_ms: float,
        other_actors: Optional[list] = None,
    ) -> Optional[CAVDecision]:
        """One decision cycle. Returns None if the underlying actor is dead.

        Steps:
          1. (optional) local-sensor synthesis from `other_actors`.
          2. Drain broker queue for this CAV's deliveries, ingest CPMs.
          3. Poll ego state from the CARLA actor.
          4. CAVCore.update() → CAVDecision.

        Any "destroyed actor" RuntimeError raised by the CARLA actor is
        caught, the CAV is marked dead via `_alive = False`, and None is
        returned. Subsequent calls return None immediately. The caller
        (typically the ablation runner) is responsible for pruning dead
        CAVs from its own per-tick loop.

        Args:
            sim_time_ms: current simulation time in ms.
            other_actors: list of CARLA actors visible in the world.
                Used only if local_sensor_enabled. The ego itself is
                auto-skipped via its actor id.
        """
        if not self.is_alive():
            return None
        try:
            # === 1. Local sensor (optional) ========================
            if self.local_sensor_enabled and other_actors:
                ego_t = self.actor.get_transform()
                local_dets = actors_in_cone(
                    ego_x=ego_t.location.x,
                    ego_y=ego_t.location.y,
                    ego_yaw_deg=ego_t.rotation.yaw,
                    actors=other_actors,
                    cone_range_m=self.local_sensor_range_m,
                    cone_angle_deg=self.local_sensor_angle_deg,
                    class_filter=self.local_sensor_class_filter,
                    ego_actor_id=self.actor.id,
                )
                self._core.ingest_local_detections(local_dets, sim_time_ms)

            # === 2. Pull + ingest CPMs =============================
            for tx in self.broker.deliveries_due(sim_time_ms, receiver_id=self.id):
                try:
                    cpm = decode_cpm(tx.payload_bytes)
                    self._core.ingest_cpm(
                        cpm,
                        rsu_id=tx.sender_id,
                        cpm_send_sim_time_ms=tx.sim_time_sent_ms,
                        sim_time_ms=sim_time_ms,
                    )
                except Exception:
                    self.decode_errors += 1

            # === 3. Ego state ======================================
            ego_t = self.actor.get_transform()
            ego_v = self.actor.get_velocity()

            # === 4. Decision =======================================
            return self._core.update(
                ego_x_m=ego_t.location.x,
                ego_y_m=ego_t.location.y,
                ego_vx_ms=ego_v.x,
                ego_vy_ms=ego_v.y,
                sim_time_ms=sim_time_ms,
            )
        except RuntimeError as e:
            if "destroyed actor" in str(e):
                self._alive = False
                return None
            raise

    # --- diagnostics --------------------------------------------------

    def get_tracks(self):
        """Pass-through to CAVCore.get_tracks() for diagnostics / logging."""
        return self._core.get_tracks()
