"""Tests for v2xsim.latency — Sprint 3 module 2.

Verifies component breakdown, monotonicity along each axis, sampling
determinism with seeded RNG, and the three profile presets (ideal /
realistic / degraded) used by proposal §4.6's ablation matrix.

Run from repo root:
    pytest tests/test_latency.py -v
"""
from __future__ import annotations

import numpy as np
import pytest

from v2xsim.latency import (
    SPEED_OF_LIGHT_M_PER_S,
    LatencyModel,
    degraded_profile,
    ideal_profile,
    realistic_profile,
)


# === Component breakdown ===================================================

def test_components_sum_equals_mean():
    m = LatencyModel()
    comps = m.components(distance_m=100.0, msg_size_bytes=500, channel_busy_ratio=0.3)
    assert abs(sum(comps.values()) - m.mean(100.0, 500, 0.3)) < 1e-9


def test_components_keys():
    m = LatencyModel()
    comps = m.components(0.0, 0, 0.0)
    assert set(comps.keys()) == {
        "proc_tx_ms", "t_tx_ms", "t_prop_ms", "t_queue_ms", "proc_rx_ms"
    }


# === Propagation ===========================================================

def test_propagation_at_zero_distance_is_zero():
    m = LatencyModel()
    assert m.components(0.0, 500, 0.0)["t_prop_ms"] == 0.0


def test_propagation_scales_linearly_with_distance():
    m = LatencyModel()
    p_100 = m.components(100.0, 500, 0.0)["t_prop_ms"]
    p_300 = m.components(300.0, 500, 0.0)["t_prop_ms"]
    assert abs(p_300 / p_100 - 3.0) < 1e-9


def test_propagation_300m_is_about_one_microsecond():
    """Proposal §4.3.1 explicitly notes: 'for 300 m it is ~1 µs'."""
    m = LatencyModel()
    p_300 = m.components(300.0, 500, 0.0)["t_prop_ms"]
    expected_ms = 300.0 / SPEED_OF_LIGHT_M_PER_S * 1000.0  # ≈ 0.001 ms
    assert abs(p_300 - expected_ms) < 1e-9
    assert p_300 < 0.002  # < 2 µs sanity


# === Queue =================================================================

def test_queue_zero_when_cbr_zero():
    m = LatencyModel(queue_slope_ms=10.0)
    assert m.components(100.0, 500, 0.0)["t_queue_ms"] == 0.0


def test_queue_scales_linearly_with_cbr():
    m = LatencyModel(queue_slope_ms=10.0)
    q_half = m.components(100.0, 500, 0.5)["t_queue_ms"]
    q_full = m.components(100.0, 500, 1.0)["t_queue_ms"]
    assert abs(q_half - 5.0) < 1e-9
    assert abs(q_full - 10.0) < 1e-9


def test_queue_clamps_cbr_to_unit_interval():
    m = LatencyModel(queue_slope_ms=10.0)
    # Out-of-range CBR is clamped, not extrapolated.
    assert m.components(100.0, 500, 1.5)["t_queue_ms"] == \
           m.components(100.0, 500, 1.0)["t_queue_ms"]
    assert m.components(100.0, 500, -0.3)["t_queue_ms"] == \
           m.components(100.0, 500, 0.0)["t_queue_ms"]


# === Transmission ==========================================================

def test_tx_at_least_one_slot_for_empty_payload():
    m = LatencyModel(slot_duration_ms=0.5)
    assert m.components(100.0, 0, 0.0)["t_tx_ms"] == 0.5


def test_tx_grows_with_msg_size():
    m = LatencyModel(slot_duration_ms=0.5, bits_per_slot=4000)
    # 500 bytes = 4000 bits → exactly 1 slot
    t_small = m.components(100.0, 500, 0.0)["t_tx_ms"]
    # 1100 bytes = 8800 bits → ceil(8800/4000) = 3 slots
    t_big = m.components(100.0, 1100, 0.0)["t_tx_ms"]
    assert t_small == 0.5
    assert t_big == 1.5


def test_tx_fits_proposal_envelope():
    """Proposal §4.3.1: 'T_tx ≈ 0.5–2 ms for typical CPM sizes'."""
    m = LatencyModel()
    for size_bytes in (100, 200, 500, 800, 1100):
        t = m.components(100.0, size_bytes, 0.0)["t_tx_ms"]
        assert 0.5 <= t <= 2.0, f"T_tx {t} out of envelope for {size_bytes} B"


# === Sampling determinism + clamping ======================================

def test_sample_deterministic_with_same_seed():
    rng1 = np.random.default_rng(42)
    rng2 = np.random.default_rng(42)
    m1 = LatencyModel(rng=rng1)
    m2 = LatencyModel(rng=rng2)
    samples1 = [m1.sample(100.0, 500, 0.3) for _ in range(20)]
    samples2 = [m2.sample(100.0, 500, 0.3) for _ in range(20)]
    assert samples1 == samples2


def test_sample_differs_with_different_seeds():
    m1 = LatencyModel(rng=np.random.default_rng(1))
    m2 = LatencyModel(rng=np.random.default_rng(2))
    s1 = [m1.sample(100.0, 500, 0.3) for _ in range(10)]
    s2 = [m2.sample(100.0, 500, 0.3) for _ in range(10)]
    assert s1 != s2


def test_sample_never_negative_under_extreme_jitter():
    """Heavy negative jitter is clamped at 0, not allowed to wrap."""
    m = LatencyModel(
        rng=np.random.default_rng(0),
        proc_tx_ms=1.0, proc_rx_ms=1.0,
        slot_duration_ms=0.5, bits_per_slot=4000,
        queue_slope_ms=0.0,
        jitter_sigma_ms=100.0,  # extremely wide
    )
    for _ in range(2000):
        assert m.sample(0.0, 500, 0.0) >= 0.0


def test_sample_centers_around_mean():
    """Empirical mean of a large sample should be close to the analytical mean."""
    m = LatencyModel(rng=np.random.default_rng(0), jitter_sigma_ms=2.0)
    analytical = m.mean(100.0, 500, 0.3)
    samples = [m.sample(100.0, 500, 0.3) for _ in range(20000)]
    empirical = sum(samples) / len(samples)
    # Standard error ≈ σ / sqrt(N) = 2 / sqrt(20000) ≈ 0.014 ms; allow 5×.
    assert abs(empirical - analytical) < 0.1


# === Profile presets =======================================================

def test_ideal_profile_zero_protocol_latency():
    """Ideal profile zeros all *protocol* overhead but not physical propagation.

    Proposal §4.6's 'Ideal (0 ms)' arm is an upper-bound idealization of the
    radio protocol — it can't repeal the speed of light. At distance_m=0
    the sample is exactly 0; at 300 m it's just the ~1 µs light-travel time.
    """
    m = ideal_profile(np.random.default_rng(0))
    for cbr in (0.0, 0.3, 0.7, 1.0):
        for size in (0, 100, 500, 1100):
            # At zero distance, sample is exactly 0.
            assert m.sample(0.0, size, cbr) == 0.0
            # At range, only the physical propagation term remains.
            sample_far = m.sample(300.0, size, cbr)
            assert sample_far < 0.002, f"got {sample_far} ms, expected < 2 µs"


def test_realistic_profile_matches_default():
    """realistic_profile() is just LatencyModel() with seeded rng."""
    a = realistic_profile(np.random.default_rng(0))
    b = LatencyModel(rng=np.random.default_rng(0))
    assert a.mean(100.0, 500, 0.3) == b.mean(100.0, 500, 0.3)


def test_degraded_profile_doubles_realistic_protocol_components():
    """Degraded doubles every protocol-overhead component but leaves
    propagation alone (physics is not a tunable).

    Test msg sizes are chosen as multiples of `bits_per_slot` so that
    ceiling artifacts in T_tx cancel; for arbitrary sizes the degraded
    T_tx is approximately 2× with up to one slot of quantization slack.
    """
    realistic = realistic_profile()
    degraded = degraded_profile()
    # 500 B = 4000 b = exactly 1 realistic slot, 2 degraded slots.
    # 1000 B = 8000 b = exactly 2 realistic slots, 4 degraded slots.
    for dist, size, cbr in [(100.0, 500, 0.3), (300.0, 1000, 0.7)]:
        r = realistic.components(dist, size, cbr)
        d = degraded.components(dist, size, cbr)
        for k in ("proc_tx_ms", "t_tx_ms", "t_queue_ms", "proc_rx_ms"):
            assert abs(d[k] - 2.0 * r[k]) < 1e-9, \
                f"{k}: degraded {d[k]} != 2× realistic {r[k]}"
        # Propagation unchanged (physics, not tunable).
        assert d["t_prop_ms"] == r["t_prop_ms"]
    # Jitter σ is also doubled, which we can't observe per-mean — check field.
    assert degraded.jitter_sigma_ms == 2.0 * realistic.jitter_sigma_ms


# === Sanity on combined output =============================================

def test_full_sample_in_reasonable_range():
    """Realistic profile should produce sub-50 ms latencies for normal load."""
    m = realistic_profile(np.random.default_rng(0))
    samples = [m.sample(200.0, 600, 0.4) for _ in range(1000)]
    # 95th percentile of N(mean, σ) with mean ≈ 8-10 ms, σ = 5 ms → ~18 ms.
    p95 = sorted(samples)[950]
    assert 1.0 < p95 < 50.0, f"p95 {p95} out of reasonable range"
