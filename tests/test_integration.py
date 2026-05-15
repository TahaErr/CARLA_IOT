"""End-to-end integration smoke test for the Sprint 3 V2X stack.

Exercises the full pipeline without CARLA: a small population of RSUs
(emitters) and mock CAVs (consumers) over a fixed-tick simulation, with
every Sprint 3 module wired in (CPM encode/decode, latency model, PDR
model, compute-budget gate, broker delivery).

Scenarios cover the system properties the proposal cares about:
  1. happy path (ideal channel + unconstrained compute → 100% delivery)
  2. PDR-driven drops at range (proposal §4.3.2 calibration)
  3. CBR feedback under heavy load (proposal §4.3)
  4. compute-budget gating under multi-RSU load (proposal §4.4)
  5. deterministic reproducibility across runs with same seeds (§4.5)
  6. multi-RSU × multi-CAV broadcast wiring

These are sanity tests, not benchmarks — exact numbers depend on parameter
choices in the channel models. Ablation runs in Sprint 4 produce the
benchmark numbers reported in §4.6.

Run from repo root:
    pytest tests/test_integration.py -v
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from v2xsim.broker import Broker
from v2xsim.compute_budget import orin_profile
from v2xsim.cpm import decode_cpm
from v2xsim.latency import LatencyModel
from v2xsim.latency import ideal_profile as ideal_latency
from v2xsim.pdr import PDRModel
from v2xsim.pdr import ideal_profile as ideal_pdr
from v2xsim.pdr import realistic_profile as realistic_pdr
from v2xsim.rsu import RSU, Detection


_SPECS_DIR = Path(__file__).resolve().parent.parent / "specs" / "cpm"
_SPECS_AVAILABLE = _SPECS_DIR.exists() and any(_SPECS_DIR.rglob("*.asn"))
pytestmark = pytest.mark.skipif(
    not _SPECS_AVAILABLE,
    reason="ETSI ASN.1 specs not on disk (run scripts/20_download_etsi_specs.py)",
)


# === Mock CAV ==============================================================

class MockCAV:
    """Minimal CAV stand-in for integration tests.

    Real CAVs (Sprint 4) implement the time-aware late-fusion module
    (proposal §4.1.1). Here we just collect decoded CPMs so we can assert
    on what the broker actually delivered.
    """

    def __init__(self, cav_id: str, position_xy_m: tuple[float, float]) -> None:
        self.id = cav_id
        self.x_m, self.y_m = position_xy_m
        self.received: list[tuple[float, "object"]] = []  # (deliver_time, decoded CPM)

    def pull_deliveries(self, broker: Broker, sim_time_ms: float) -> None:
        for tx in broker.deliveries_due(sim_time_ms, receiver_id=self.id):
            cpm = decode_cpm(tx.payload_bytes)
            self.received.append((tx.sim_time_deliver_ms, cpm))


# === Helpers ===============================================================

def _distance(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    return (dx * dx + dy * dy) ** 0.5


def _fixed_detections() -> list[Detection]:
    """A small, deterministic detection set used across scenarios."""
    return [
        Detection(yolo_class_idx=0, confidence=0.85, world_x_m=10.0, world_y_m=5.0),
        Detection(yolo_class_idx=3, confidence=0.70, world_x_m=15.0, world_y_m=8.0),
    ]


def _run_simulation(
    rsus: list[RSU],
    cavs: list[MockCAV],
    broker: Broker,
    n_ticks: int = 100,
    dt_ms: float = 100.0,
    inference_cost_ms: float = 5.0,
    reset_budget_between_ticks: bool = False,
) -> dict:
    """Drive a fixed-tick simulation; return per-scenario counts.

    Each tick:
      - (optional) reset compute-budget window
      - for each RSU: publish a CPM to every CAV (distance computed here)
      - for each CAV: pull any deliveries due at the current sim_time
    After the loop, advance sim_time by 10 s to flush in-flight messages.
    """
    publishes_accepted = 0
    publishes_dropped_budget = 0

    for tick in range(n_ticks):
        sim_time_ms = tick * dt_ms
        if reset_budget_between_ticks and rsus[0].compute_budget is not None:
            rsus[0].compute_budget.reset_window()

        for rsu in rsus:
            rsu_pos = (rsu.reference_x_m, rsu.reference_y_m)
            receivers = [(cav.id, _distance(rsu_pos, (cav.x_m, cav.y_m))) for cav in cavs]
            if rsu.tick(broker, _fixed_detections(), inference_cost_ms,
                        receivers, sim_time_ms):
                publishes_accepted += 1
            else:
                publishes_dropped_budget += 1

        for cav in cavs:
            cav.pull_deliveries(broker, sim_time_ms)

    # Flush remaining in-flight messages.
    flush_time = n_ticks * dt_ms + 10_000.0
    for cav in cavs:
        cav.pull_deliveries(broker, flush_time)

    return {
        "publishes_accepted": publishes_accepted,
        "publishes_dropped_budget": publishes_dropped_budget,
        "received_by_cav": {cav.id: len(cav.received) for cav in cavs},
    }


# === Scenario 1: happy path ================================================

def test_happy_path_single_rsu_single_cav_ideal_channel():
    """Ideal latency + ideal PDR + no budget → every published CPM arrives."""
    broker = Broker(
        latency=ideal_latency(np.random.default_rng(0)),
        pdr=ideal_pdr(np.random.default_rng(0)),
    )
    rsu = RSU(station_id=1, reference_position_xy_m=(0.0, 0.0))
    cav = MockCAV("cav0", (50.0, 50.0))

    stats = _run_simulation([rsu], [cav], broker, n_ticks=100)

    assert stats["publishes_accepted"] == 100
    assert stats["publishes_dropped_budget"] == 0
    assert stats["received_by_cav"]["cav0"] == 100

    # Inspect the first CPM end-to-end.
    _, first_cpm = cav.received[0]
    assert first_cpm.station_id == 1
    assert len(first_cpm.objects) == 2
    assert first_cpm.objects[0].object_class == "passengerCar"
    assert first_cpm.objects[1].object_class == "pedestrian"


# === Scenario 2: PDR-driven drops at range =================================

def test_realistic_pdr_drops_distant_cpms_more_than_near():
    """Near CAV gets > 70% of CPMs; far CAV gets significantly fewer."""
    broker = Broker(
        latency=ideal_latency(np.random.default_rng(0)),    # no latency variance
        pdr=realistic_pdr(np.random.default_rng(0)),         # but realistic PDR
    )
    rsu = RSU(station_id=1, reference_position_xy_m=(0.0, 0.0))
    near_cav = MockCAV("cav_near", (50.0, 50.0))     # d ≈ 71 m → P_success ≈ 0.90
    far_cav = MockCAV("cav_far", (200.0, 150.0))     # d ≈ 250 m → P_success ≈ 0.28

    _run_simulation([rsu], [near_cav, far_cav], broker, n_ticks=200)

    near_count = len(near_cav.received)
    far_count = len(far_cav.received)

    # Bounds chosen to be robust to RNG variance (200 trials, σ ≈ 0.03 per CAV).
    assert near_count > 140, f"near received only {near_count}/200"
    assert far_count < 100, f"far received {far_count}/200, expected < 100"
    assert near_count > far_count


# === Scenario 3: CBR feedback under load ===================================

def test_cbr_grows_with_more_concurrent_publishers():
    """30 RSUs publishing into a 1-second window should drive CBR > 0."""
    broker = Broker(
        latency=LatencyModel(rng=np.random.default_rng(0), jitter_sigma_ms=0.0),
        pdr=ideal_pdr(np.random.default_rng(0)),
        cbr_window_ms=1000.0,
    )
    rsus = [RSU(station_id=i, reference_position_xy_m=(0.0, 0.0))
            for i in range(1, 31)]
    cav = MockCAV("cav0", (50.0, 50.0))

    cbr_at_start = None
    cbr_at_end = None
    for tick in range(30):
        sim_time_ms = tick * 10.0
        for rsu in rsus:
            rsu.tick(broker, _fixed_detections(), 1.0,
                     [(cav.id, 50.0)], sim_time_ms)
        if tick == 0:
            cbr_at_start = broker.channel_busy_ratio(sim_time_ms=sim_time_ms)
        if tick == 29:
            cbr_at_end = broker.channel_busy_ratio(sim_time_ms=sim_time_ms)

    # CBR should rise as more transmissions accumulate within the window.
    assert cbr_at_end > cbr_at_start


# === Scenario 4: compute-budget gating =====================================

def test_orin_budget_drops_excess_rsus_each_window():
    """Aggregate budget for n_rsus=15 + 10 ms inference = 9 admits per window."""
    budget = orin_profile(n_rsus=15)  # per_rsu=20 ms, aggregate=90 ms
    broker = Broker(
        latency=ideal_latency(np.random.default_rng(0)),
        pdr=ideal_pdr(np.random.default_rng(0)),
    )
    rsus = [RSU(station_id=i, reference_position_xy_m=(0.0, 0.0),
                compute_budget=budget) for i in range(1, 16)]
    cav = MockCAV("cav0", (50.0, 50.0))

    stats = _run_simulation(
        rsus, [cav], broker,
        n_ticks=3, dt_ms=100.0,
        inference_cost_ms=10.0,
        reset_budget_between_ticks=True,
    )

    # Per tick: 15 RSUs × 10 ms = 150 ms requested, 90 ms aggregate budget.
    # → 9 admit (90 / 10), 6 drop. Over 3 ticks: 27 admit, 18 drop.
    assert stats["publishes_accepted"] == 27
    assert stats["publishes_dropped_budget"] == 18


# === Scenario 5: determinism ===============================================

def test_full_pipeline_is_deterministic_with_same_seeds():
    """Proposal §4.5 explicitly requires reproducible ablation runs."""
    def run():
        broker = Broker(
            latency=LatencyModel(rng=np.random.default_rng(42)),
            pdr=PDRModel(rng=np.random.default_rng(43)),
        )
        rsu = RSU(station_id=1, reference_position_xy_m=(0.0, 0.0))
        cav = MockCAV("cav0", (100.0, 50.0))
        _run_simulation([rsu], [cav], broker, n_ticks=50)
        return [(t, cpm.station_id, len(cpm.objects)) for t, cpm in cav.received]

    assert run() == run()


# === Scenario 6: multi-RSU × multi-CAV broadcast ===========================

def test_three_rsus_broadcast_to_two_cavs_ideal_channel():
    """Each CAV should receive a CPM from every RSU on every tick."""
    broker = Broker(
        latency=ideal_latency(np.random.default_rng(0)),
        pdr=ideal_pdr(np.random.default_rng(0)),
    )
    rsus = [
        RSU(station_id=1, reference_position_xy_m=(0.0, 0.0)),
        RSU(station_id=2, reference_position_xy_m=(100.0, 0.0)),
        RSU(station_id=3, reference_position_xy_m=(0.0, 100.0)),
    ]
    cavs = [
        MockCAV("cav0", (50.0, 50.0)),
        MockCAV("cav1", (60.0, 60.0)),
    ]

    stats = _run_simulation(rsus, cavs, broker, n_ticks=20)

    # 20 ticks × 3 RSUs × 2 CAVs = 120 deliveries total.
    assert stats["received_by_cav"]["cav0"] == 60
    assert stats["received_by_cav"]["cav1"] == 60

    # Each CAV should see all 3 senders represented in its inbox.
    cav0_senders = {cpm.station_id for _, cpm in cavs[0].received}
    cav1_senders = {cpm.station_id for _, cpm in cavs[1].received}
    assert cav0_senders == {1, 2, 3}
    assert cav1_senders == {1, 2, 3}
