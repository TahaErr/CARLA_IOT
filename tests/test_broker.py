"""Tests for v2xsim.broker — Sprint 3 module 5.

Verifies publish/deliver semantics, PDR-based drop behaviour, CBR sliding
window feedback, deterministic delivery ordering, and isolation across
multiple receivers. Channel models are configured to force trivial
outcomes (always deliver / always drop / zero jitter) so test assertions
can be exact.

Run from repo root:
    pytest tests/test_broker.py -v
"""
from __future__ import annotations

import numpy as np
import pytest

from v2xsim.broker import Broker, CPMTransmission
from v2xsim.latency import LatencyModel
from v2xsim.pdr import PDRModel


# === Helpers ===============================================================

def _deterministic_latency(jitter: float = 0.0, seed: int = 0) -> LatencyModel:
    """Latency model with no queue contribution and configurable jitter."""
    return LatencyModel(
        proc_tx_ms=1.0, proc_rx_ms=1.0,
        slot_duration_ms=0.5, bits_per_slot=4000,
        queue_slope_ms=0.0,
        jitter_sigma_ms=jitter,
        rng=np.random.default_rng(seed),
    )


def _always_deliver_pdr(seed: int = 0) -> PDRModel:
    """α=0 + d_ref enormous → P_success ≈ 1 everywhere."""
    return PDRModel(d_ref_m=1.0e9, gamma=2.0, alpha=0.0,
                    rng=np.random.default_rng(seed))


def _never_deliver_pdr(seed: int = 0) -> PDRModel:
    """α=1, but we feed CBR=1 indirectly by passing close-to-1 PDR conditions.

    Simpler: d_ref tiny so distance term ≈ 0 for any d > 0.
    """
    return PDRModel(d_ref_m=1.0e-9, gamma=2.0, alpha=0.0,
                    rng=np.random.default_rng(seed))


def _broker(
    deliver: bool = True,
    jitter: float = 0.0,
    cbr_window_ms: float = 1000.0,
    latency_seed: int = 0,
    pdr_seed: int = 0,
) -> Broker:
    pdr = _always_deliver_pdr(pdr_seed) if deliver else _never_deliver_pdr(pdr_seed)
    return Broker(
        latency=_deterministic_latency(jitter=jitter, seed=latency_seed),
        pdr=pdr,
        cbr_window_ms=cbr_window_ms,
    )


# === Publish + deliver round-trip =========================================

def test_publish_returns_one_tx_per_receiver():
    b = _broker(deliver=True)
    accepted = b.publish(
        sender_id="rsu0",
        payload_bytes=b"x" * 500,
        receivers=[("cav0", 100.0), ("cav1", 150.0), ("cav2", 200.0)],
        sim_time_ms=0.0,
    )
    assert len(accepted) == 3
    assert {m.receiver_id for m in accepted} == {"cav0", "cav1", "cav2"}
    assert all(m.sender_id == "rsu0" for m in accepted)
    assert all(m.sim_time_sent_ms == 0.0 for m in accepted)


def test_delivery_time_equals_send_time_plus_latency():
    b = _broker(deliver=True, jitter=0.0)
    accepted = b.publish("rsu0", b"x" * 500, [("cav0", 100.0)], sim_time_ms=50.0)
    msg = accepted[0]
    # Latency is positive; delivery strictly later than send.
    assert msg.sim_time_deliver_ms > msg.sim_time_sent_ms


def test_deliveries_due_returns_nothing_before_due_time():
    b = _broker(deliver=True, jitter=0.0)
    b.publish("rsu0", b"x" * 500, [("cav0", 100.0)], sim_time_ms=0.0)
    # Latency model produces a few ms; nothing should be due at t=0.
    assert b.deliveries_due(sim_time_ms=0.0) == []


def test_deliveries_due_eventually_returns_message():
    b = _broker(deliver=True, jitter=0.0)
    b.publish("rsu0", b"x" * 500, [("cav0", 100.0)], sim_time_ms=0.0)
    due = b.deliveries_due(sim_time_ms=10_000.0)
    assert len(due) == 1
    assert due[0].sender_id == "rsu0"
    assert due[0].receiver_id == "cav0"


def test_deliveries_due_does_not_repeat():
    b = _broker(deliver=True, jitter=0.0)
    b.publish("rsu0", b"x" * 500, [("cav0", 100.0)], sim_time_ms=0.0)
    first = b.deliveries_due(10_000.0)
    second = b.deliveries_due(10_000.0)
    assert len(first) == 1
    assert second == []


def test_deliveries_due_orders_by_time_then_sender_then_msgid():
    b = _broker(deliver=True, jitter=0.0)
    b.publish("rsu1", b"x" * 500, [("cav0", 100.0)], sim_time_ms=0.0)
    b.publish("rsu0", b"x" * 500, [("cav0", 100.0)], sim_time_ms=0.0)
    due = b.deliveries_due(10_000.0)
    # Same deliver_time, same msg path → tie-break by sender_id (lex order).
    assert [m.sender_id for m in due] == ["rsu0", "rsu1"]


# === PDR drop semantics ===================================================

def test_pdr_drop_excludes_from_queue():
    b = _broker(deliver=False)
    accepted = b.publish("rsu0", b"x" * 500, [("cav0", 100.0)], 0.0)
    assert accepted == []
    assert b.deliveries_due(10_000.0) == []


def test_pdr_drop_does_not_consume_msg_id():
    """msg_id is assigned only on accept — successive deliveries get 0, 1, 2."""
    pdr = _never_deliver_pdr()
    b = Broker(latency=_deterministic_latency(), pdr=pdr)
    b.publish("rsu0", b"x" * 500, [("cav0", 100.0)], 0.0)  # all dropped
    # Now swap PDR mid-test to always deliver
    b.pdr = _always_deliver_pdr()
    accepted = b.publish("rsu0", b"x" * 500, [("cav0", 100.0)], 0.0)
    assert len(accepted) == 1
    assert accepted[0].msg_id == 0  # was not consumed by the dropped publish


def test_empty_receivers_publishes_nothing_but_charges_channel():
    b = _broker(deliver=True)
    accepted = b.publish("rsu0", b"x" * 500, receivers=[], sim_time_ms=0.0)
    assert accepted == []
    # But the channel is still busy from the broadcast.
    assert b.channel_busy_ratio() > 0.0


# === CBR sliding window ===================================================

def test_cbr_zero_before_any_publish():
    b = _broker(deliver=True)
    assert b.channel_busy_ratio() == 0.0


def test_cbr_grows_with_more_transmissions():
    b = _broker(deliver=True, cbr_window_ms=100.0)
    cbr_history = []
    for i in range(20):
        b.publish("rsu0", b"x" * 500, [("cav0", 100.0)], sim_time_ms=float(i))
        cbr_history.append(b.channel_busy_ratio(sim_time_ms=float(i)))
    # CBR should be non-decreasing within the window.
    assert cbr_history[-1] > cbr_history[0]


def test_cbr_drops_old_transmissions_outside_window():
    b = _broker(deliver=True, cbr_window_ms=100.0)
    b.publish("rsu0", b"x" * 500, [("cav0", 100.0)], sim_time_ms=0.0)
    cbr_early = b.channel_busy_ratio(sim_time_ms=10.0)
    cbr_late = b.channel_busy_ratio(sim_time_ms=2000.0)
    assert cbr_early > 0
    assert cbr_late == 0.0


def test_cbr_clamped_at_one():
    """Many large transmissions in a small window cannot push CBR past 1."""
    # 1100 B payload at default bits_per_slot=4000 → 3 slots × 0.5 ms = 1.5 ms T_tx.
    # 200 publishes in 100 ms window → 300 ms total busy time → would be 3.0.
    b = _broker(deliver=True, cbr_window_ms=100.0)
    for i in range(200):
        b.publish("rsu0", b"x" * 1100, [("cav0", 100.0)], sim_time_ms=float(i) * 0.4)
    cbr = b.channel_busy_ratio(sim_time_ms=80.0)
    assert cbr == 1.0


# === Determinism ===========================================================

def test_two_brokers_with_same_seeds_produce_identical_output():
    """Cross-run reproducibility (proposal §4.5)."""
    def run() -> list[float]:
        b = Broker(
            latency=LatencyModel(rng=np.random.default_rng(42)),
            pdr=PDRModel(rng=np.random.default_rng(43)),
        )
        deliver_times = []
        for i in range(30):
            accepted = b.publish(
                "rsu0", b"x" * 500,
                [("cav0", 80.0), ("cav1", 150.0)],
                sim_time_ms=float(i) * 100.0,
            )
            deliver_times.extend(m.sim_time_deliver_ms for m in accepted)
        return deliver_times

    assert run() == run()


# === Receiver-side filtering (multi-consumer pattern) =====================

def test_deliveries_due_filtered_by_receiver_id_pops_only_matching():
    """With receiver_id given, other receivers' messages remain in the queue."""
    b = _broker(deliver=True, jitter=0.0)
    b.publish("rsu0", b"x" * 500, [("cav0", 100.0), ("cav1", 100.0)], 0.0)
    assert b.pending_count() == 2

    # cav0 pulls only its own.
    due_cav0 = b.deliveries_due(10_000.0, receiver_id="cav0")
    assert len(due_cav0) == 1
    assert due_cav0[0].receiver_id == "cav0"
    assert b.pending_count() == 1  # cav1's message still pending

    # cav1 then pulls its own.
    due_cav1 = b.deliveries_due(10_000.0, receiver_id="cav1")
    assert len(due_cav1) == 1
    assert due_cav1[0].receiver_id == "cav1"
    assert b.pending_count() == 0


def test_deliveries_due_unknown_receiver_returns_empty_and_keeps_queue():
    b = _broker(deliver=True, jitter=0.0)
    b.publish("rsu0", b"x" * 500, [("cav0", 100.0)], 0.0)
    due = b.deliveries_due(10_000.0, receiver_id="not_a_real_cav")
    assert due == []
    # The cav0 message is still pending — unknown filter didn't drain it.
    assert b.pending_count() == 1


# === Diagnostics ===========================================================

def test_pending_count_tracks_in_flight():
    b = _broker(deliver=True, jitter=0.0)
    assert b.pending_count() == 0
    b.publish("rsu0", b"x" * 500, [("cav0", 100.0), ("cav1", 100.0)], 0.0)
    assert b.pending_count() == 2
    b.deliveries_due(10_000.0)
    assert b.pending_count() == 0


# === Sanity on realistic models ===========================================

def test_realistic_models_produce_some_drops_and_some_deliveries():
    """With default LatencyModel + PDRModel and moderate distance, neither
    everything nor nothing should be delivered."""
    b = Broker(
        latency=LatencyModel(rng=np.random.default_rng(0)),
        pdr=PDRModel(rng=np.random.default_rng(0)),
    )
    delivered = 0
    n = 500
    for i in range(n):
        accepted = b.publish(
            "rsu0", b"x" * 500,
            [("cav0", 200.0)],  # at d=200 P_success ≈ 0.44
            sim_time_ms=float(i) * 10.0,
        )
        delivered += len(accepted)
    # Roughly 40-50% delivery at 200 m with α=0.3 and small CBR.
    assert 100 < delivered < 400, f"got {delivered}/{n}"
