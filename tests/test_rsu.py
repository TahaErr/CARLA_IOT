"""Tests for v2xsim.rsu — Sprint 3 module 6.

Two layers:
  1. Pure-Python tests: build_cpm logic, world-to-relative coordinate
     translation, YOLO→ETSI class mapping. No ASN.1 specs needed.
  2. Encode tests (tick + real Broker integration): require ETSI spec
     files on disk (`specs/cpm/`). Auto-skipped if specs are absent.

Run from repo root:
    pytest tests/test_rsu.py -v
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from v2xsim.broker import Broker
from v2xsim.compute_budget import BudgetTracker, orin_profile
from v2xsim.latency import LatencyModel
from v2xsim.pdr import PDRModel
from v2xsim.rsu import RSU, YOLO_CLASS_NAMES, Detection


# Skip tests that need a working asn1tools compile (which needs spec files).
_SPECS_DIR = Path(__file__).resolve().parent.parent / "specs" / "cpm"
_SPECS_AVAILABLE = _SPECS_DIR.exists() and any(_SPECS_DIR.rglob("*.asn"))
skip_no_specs = pytest.mark.skipif(
    not _SPECS_AVAILABLE,
    reason="ETSI ASN.1 specs not on disk (run scripts/20_download_etsi_specs.py)",
)


# === Mocks ==================================================================

class _MockBroker:
    """Minimal Broker stand-in that records publish() calls."""
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, list[tuple[str, float]], float]] = []

    def publish(
        self,
        sender_id: str,
        payload_bytes: bytes,
        receivers: list[tuple[str, float]],
        sim_time_ms: float,
    ) -> list[Any]:
        self.calls.append((sender_id, payload_bytes, list(receivers), sim_time_ms))
        return []


def _det(idx: int = 0, conf: float = 0.8, x: float = 0.0, y: float = 0.0,
         vx: float = 0.0, vy: float = 0.0) -> Detection:
    return Detection(
        yolo_class_idx=idx, confidence=conf,
        world_x_m=x, world_y_m=y,
        world_vx_ms=vx, world_vy_ms=vy,
    )


# === build_cpm (pure-Python, no ASN.1) ====================================

def test_build_cpm_emits_relative_coords():
    rsu = RSU(station_id=1, reference_position_xy_m=(100.0, 200.0))
    cpm = rsu.build_cpm([_det(idx=0, conf=0.85, x=110.0, y=205.0)], sim_time_ms=500.0)
    assert cpm.station_id == 1
    assert cpm.generation_delta_time_ms == 500
    assert len(cpm.objects) == 1
    o = cpm.objects[0]
    assert o.object_id == 1
    assert o.object_class == "passengerCar"
    assert o.x_m == 10.0   # 110 - 100
    assert o.y_m == 5.0    # 205 - 200
    assert o.confidence == 0.85


def test_build_cpm_maps_each_yolo_class_to_etsi():
    rsu = RSU(station_id=1, reference_position_xy_m=(0.0, 0.0))
    dets = [_det(idx=i) for i in range(4)]
    cpm = rsu.build_cpm(dets, sim_time_ms=0.0)
    expected = ["passengerCar", "motorcycle", "pedalCycle", "pedestrian"]
    assert [o.object_class for o in cpm.objects] == expected


def test_build_cpm_object_ids_are_sequential():
    rsu = RSU(station_id=1, reference_position_xy_m=(0.0, 0.0))
    cpm = rsu.build_cpm([_det() for _ in range(5)], sim_time_ms=0.0)
    assert [o.object_id for o in cpm.objects] == [1, 2, 3, 4, 5]


def test_build_cpm_empty_detections_produces_empty_object_list():
    rsu = RSU(station_id=1, reference_position_xy_m=(0.0, 0.0))
    cpm = rsu.build_cpm([], sim_time_ms=100.0)
    assert cpm.objects == []
    assert cpm.station_id == 1
    assert cpm.generation_delta_time_ms == 100


def test_build_cpm_preserves_velocity():
    rsu = RSU(station_id=1, reference_position_xy_m=(0.0, 0.0))
    cpm = rsu.build_cpm([_det(vx=3.5, vy=-1.2)], sim_time_ms=0.0)
    assert cpm.objects[0].vx_ms == 3.5
    assert cpm.objects[0].vy_ms == -1.2


def test_build_cpm_generation_delta_wraps_at_65536():
    """ETSI's TimestampIts field wraps every 65.5 s; we mirror that."""
    rsu = RSU(station_id=1, reference_position_xy_m=(0.0, 0.0))
    cpm = rsu.build_cpm([], sim_time_ms=70_000.0)
    assert cpm.generation_delta_time_ms == 70_000 % 65536


def test_yolo_class_names_match_etsi_mapping():
    """YOLO_CLASS_NAMES order must match the 4-class detector head."""
    assert YOLO_CLASS_NAMES == ("vehicle", "motorcycle", "bicycle", "pedestrian")


# === tick with MockBroker (no encode needed) =============================
#
# tick() calls encode_cpm internally, which needs ASN.1 specs.  We skip
# these in sandbox/CI environments without specs on disk.

@skip_no_specs
def test_tick_publishes_to_broker():
    broker = _MockBroker()
    rsu = RSU(station_id=42, reference_position_xy_m=(0.0, 0.0))
    result = rsu.tick(
        broker=broker,  # type: ignore[arg-type]
        detections=[_det(x=10.0, y=5.0)],
        inference_cost_ms=10.0,
        receivers=[("cav0", 100.0)],
        sim_time_ms=500.0,
    )
    assert result is True
    assert len(broker.calls) == 1
    sender, payload, receivers, t = broker.calls[0]
    assert sender == "42"  # station_id stringified for broker
    assert isinstance(payload, bytes) and len(payload) > 0
    assert receivers == [("cav0", 100.0)]
    assert t == 500.0


@skip_no_specs
def test_tick_with_no_budget_always_publishes():
    """When no BudgetTracker is attached, every tick produces a CPM."""
    broker = _MockBroker()
    rsu = RSU(station_id=1, reference_position_xy_m=(0.0, 0.0))
    for i in range(10):
        result = rsu.tick(
            broker=broker,  # type: ignore[arg-type]
            detections=[],
            inference_cost_ms=999.0,  # huge — would be rejected with a budget
            receivers=[],
            sim_time_ms=float(i),
        )
        assert result is True
    assert len(broker.calls) == 10


@skip_no_specs
def test_tick_with_budget_drops_when_aggregate_exceeded():
    """Aggregate budget is the binding constraint with n_rsus=1."""
    # orin_profile(n_rsus=1) → per_rsu=20 ms, aggregate=20*1*0.3=6 ms
    budget = orin_profile(n_rsus=1)
    broker = _MockBroker()
    rsu = RSU(station_id=1, reference_position_xy_m=(0.0, 0.0),
              compute_budget=budget)
    # First admit: 5 ms (per_rsu 5/20 OK, aggregate 5/6 OK)
    assert rsu.tick(broker, [], 5.0, [], sim_time_ms=0.0) is True  # type: ignore[arg-type]
    # Second admit: 2 ms would push aggregate to 7 > 6 → reject
    assert rsu.tick(broker, [], 2.0, [], sim_time_ms=10.0) is False  # type: ignore[arg-type]
    # Only the first publish reached the broker.
    assert len(broker.calls) == 1


@skip_no_specs
def test_tick_budget_dropped_messages_are_silent():
    """A dropped tick produces no broker call at all (not even an empty CPM)."""
    budget = BudgetTracker(per_rsu_budget_ms=10.0, aggregate_budget_ms=100.0)
    broker = _MockBroker()
    rsu = RSU(station_id=1, reference_position_xy_m=(0.0, 0.0),
              compute_budget=budget)
    # Single 20 ms inference: exceeds per_rsu_budget=10 → drop.
    assert rsu.tick(broker, [], 20.0, [], sim_time_ms=0.0) is False  # type: ignore[arg-type]
    assert broker.calls == []


# === End-to-end with the real Broker + decode round-trip =================

@skip_no_specs
def test_tick_through_real_broker_decodes_round_trip():
    """RSU → real Broker → decode_cpm: the full Sprint 3 pipeline.

    Uses 'always deliver' channel (no jitter, no PDR drops) so the test
    asserts on exact field values.
    """
    from v2xsim.cpm import decode_cpm

    broker = Broker(
        latency=LatencyModel(rng=np.random.default_rng(0), jitter_sigma_ms=0.0),
        pdr=PDRModel(d_ref_m=1.0e9, alpha=0.0, rng=np.random.default_rng(0)),
    )
    rsu = RSU(station_id=7, reference_position_xy_m=(100.0, 200.0))

    rsu.tick(
        broker=broker,
        detections=[
            _det(idx=0, conf=0.8, x=110.0, y=205.0, vx=2.0, vy=-1.0),  # vehicle
            _det(idx=3, conf=0.7, x=115.0, y=208.0),                   # pedestrian
        ],
        inference_cost_ms=5.0,
        receivers=[("cav0", 100.0)],
        sim_time_ms=1000.0,
    )

    due = broker.deliveries_due(sim_time_ms=10_000.0)
    assert len(due) == 1

    decoded = decode_cpm(due[0].payload_bytes)
    assert decoded.station_id == 7
    assert decoded.generation_delta_time_ms == 1000
    assert len(decoded.objects) == 2

    veh, ped = decoded.objects
    assert veh.object_class == "passengerCar"
    assert veh.x_m == pytest.approx(10.0, abs=0.01)   # 110 - 100, allowing for ETSI cm quantization
    assert veh.y_m == pytest.approx(5.0, abs=0.01)    # 205 - 200
    assert veh.vx_ms == pytest.approx(2.0, abs=0.01)
    assert veh.vy_ms == pytest.approx(-1.0, abs=0.01)

    assert ped.object_class == "pedestrian"
    assert ped.x_m == pytest.approx(15.0, abs=0.01)
    assert ped.y_m == pytest.approx(8.0, abs=0.01)
