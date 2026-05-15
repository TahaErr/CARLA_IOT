"""Roadside Unit pipeline (Sprint 3 module 6).

CARLA-agnostic per-intersection pipeline that turns detector outputs into
ETSI CPMs and pushes them through the broker. Sprint 4's CARLA-tied wrapper
(camera attach + actor lifecycle + tick orchestration) builds on top of this.

The Sprint 1 multi-camera `RSU` class is intentionally replaced here:
   - It was buggy under CARLA 0.9.16 Windows (multi-camera crash, see
     PROGRESS.md §3.2.2);
   - It was never imported by any script (`findstr` confirmed orphan);
   - Single-camera-per-RSU is the production deployment pattern (NYC DOT,
     FDOT ATSPM cited in PROGRESS.md §3.2.3).

Data flow per tick:
    Detection[]  ─┐
                  │
                  │  (build_cpm)
                  ▼
                 CPM dataclass ── (encode_cpm) ──► bytes ──► Broker.publish()

Optional compute-budget gating: if a BudgetTracker is attached, every
inference cost is checked against per-RSU + aggregate budgets before the
CPM is built. A budget-gated tick is a no-op (no bytes generated, no
broker traffic) — graceful degradation per proposal §4.4.

The class holds only per-RSU state: station_id, reference position (used
as the local cartesian origin per ETSI's ITS-S frame convention), and the
optional budget tracker. Everything else flows through the tick() args.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .broker import Broker
from .compute_budget import BudgetTracker
from .cpm import CPM, CPMObject, YOLO_TO_ETSI, encode_cpm


# YOLO 4-class output index → class name (matches Sprint 2 detector head).
YOLO_CLASS_NAMES = ("vehicle", "motorcycle", "bicycle", "pedestrian")


@dataclass(frozen=True)
class Detection:
    """One detection from the YOLO pipeline, projected to world coordinates.

    The RSU's job is to fuse the detector's pixel-space output with the
    camera's extrinsic + intrinsic into world-frame east/north metres.
    Sprint 4's CARLA wrapper does that projection; this dataclass is the
    handoff format between the projection step and the CPM encoder.

    Velocity components default to 0 — many detectors emit position-only.
    Sprint 4 may estimate velocity via inter-frame association; until then,
    consumers (the CAV fusion module in Sprint 4) treat unknown velocity
    as 0 and let the message-age extrapolation rule handle motion.
    """
    yolo_class_idx: int     # 0..3, indexes YOLO_CLASS_NAMES
    confidence: float       # [0, 1]
    world_x_m: float        # east-positive, simulation cartesian frame
    world_y_m: float        # north-positive
    world_vx_ms: float = 0.0
    world_vy_ms: float = 0.0


class RSU:
    """Per-intersection CPM-emitting pipeline.

    One instance per signalised intersection. CARLA-agnostic: takes
    already-projected detections, never touches the CARLA SDK. The Sprint 4
    CARLA wrapper feeds it.
    """

    def __init__(
        self,
        station_id: int,
        reference_position_xy_m: tuple[float, float],
        compute_budget: Optional[BudgetTracker] = None,
    ):
        """Args:
            station_id: ITS-S station identifier (ETSI int32 field).
                Use the intersection index from `discover_intersections`.
            reference_position_xy_m: (east, north) world position of this
                RSU's reference point. CPM object coordinates are encoded
                relative to this point.
            compute_budget: Optional shared BudgetTracker. If provided,
                each tick is gated by it; if None, every tick proceeds.
        """
        self.station_id = station_id
        self.reference_x_m, self.reference_y_m = reference_position_xy_m
        self.compute_budget = compute_budget

    # --- assembly -------------------------------------------------------

    def build_cpm(
        self,
        detections: list[Detection],
        sim_time_ms: float,
    ) -> CPM:
        """Convert a list of detections into one CPM dataclass.

        World coordinates in each Detection are translated to RSU-relative
        per ETSI's ITS-S local cartesian convention (CPM §6.5.1.4).
        """
        objects: list[CPMObject] = []
        for i, d in enumerate(detections):
            yolo_name = YOLO_CLASS_NAMES[d.yolo_class_idx]
            etsi_class = YOLO_TO_ETSI[yolo_name]
            objects.append(CPMObject(
                object_id=i + 1,
                object_class=etsi_class,
                x_m=d.world_x_m - self.reference_x_m,
                y_m=d.world_y_m - self.reference_y_m,
                vx_ms=d.world_vx_ms,
                vy_ms=d.world_vy_ms,
                confidence=d.confidence,
            ))

        # ETSI generationDeltaTime is ms since current UTC second (0..65535).
        # We use sim_time_ms mod 65536 — preserves relative ordering inside
        # any 65.5-second window, which is more than long enough for the
        # CAV fusion module's TTL (default 1.0 s in proposal §4.1.1).
        return CPM(
            station_id=self.station_id,
            generation_delta_time_ms=int(sim_time_ms) % 65536,
            objects=objects,
        )

    # --- main entry point -----------------------------------------------

    def tick(
        self,
        broker: Broker,
        detections: list[Detection],
        inference_cost_ms: float,
        receivers: list[tuple[str, float]],
        sim_time_ms: float,
    ) -> bool:
        """One CPM generation cycle.

        Order matters:
          1. Budget gate (skip everything if rejected — no inference output
             counts as no CPM).
          2. Build the CPM dataclass.
          3. Encode to ASN.1 UPER bytes.
          4. Hand to broker for distribution.

        Args:
            broker: shared Broker instance.
            detections: already-projected detections from the YOLO pipeline.
            inference_cost_ms: observed wall-clock cost of the detection
                step on this RSU. Submitted to the budget; if larger than
                the budget, the tick is dropped.
            receivers: (cav_id, distance_m) pairs from the simulator's
                in-range query. Each pair gets its own PDR + latency draw
                inside the broker.
            sim_time_ms: current simulation time, used as both the CPM's
                generationDeltaTime and the broker's reception time origin.

        Returns:
            True if the CPM was published (budget admitted), False if the
            tick was dropped at the budget gate.
        """
        if self.compute_budget is not None:
            if not self.compute_budget.admit(str(self.station_id), inference_cost_ms):
                return False

        cpm = self.build_cpm(detections, sim_time_ms)
        payload = encode_cpm(cpm)
        broker.publish(
            sender_id=str(self.station_id),
            payload_bytes=payload,
            receivers=receivers,
            sim_time_ms=sim_time_ms,
        )
        return True
