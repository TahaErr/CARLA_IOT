"""Tests for v2xsim.pdr — Sprint 3 module 3.

Anchors P_success to proposal §4.3.2's quoted calibration (≈80% at 100 m,
e^-1 at d_ref), verifies monotonicity in distance and CBR, Bernoulli
behaviour with seeded RNG, and the three profile presets.

Run from repo root:
    pytest tests/test_pdr.py -v
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from v2xsim.pdr import (
    PDRModel,
    ideal_profile,
    lossy_profile,
    realistic_profile,
)


# === Probability formula ===================================================

def test_p_success_in_unit_interval():
    """P_success must always lie in [0, 1] for any reasonable input."""
    m = PDRModel()
    for d in (0.0, 50.0, 100.0, 220.0, 500.0, 1000.0):
        for cbr in (0.0, 0.3, 0.7, 1.0):
            p = m.success_probability(d, cbr)
            assert 0.0 <= p <= 1.0, f"P({d}, {cbr}) = {p} out of [0,1]"


def test_p_success_at_origin_idle_is_one():
    """At zero distance and zero load, no loss is possible."""
    m = PDRModel()
    assert m.success_probability(0.0, 0.0) == 1.0


def test_p_success_at_d_ref_is_one_over_e():
    """By definition, P(d_ref, 0) = e^-1 ≈ 0.368."""
    m = PDRModel(d_ref_m=220.0, gamma=2.0, alpha=0.3)
    p = m.success_probability(220.0, 0.0)
    assert abs(p - math.exp(-1.0)) < 1e-9


def test_p_success_anchor_at_100m_matches_proposal():
    """Proposal §4.3.2: 'PDR ≈ 80% at 100 m' under idle channel.

    With d_ref=220, γ=2: exp(-(100/220)^2) = exp(-0.2066) ≈ 0.813.
    """
    m = PDRModel()
    p = m.success_probability(100.0, 0.0)
    assert 0.78 < p < 0.85, f"P(100m, 0) = {p}, expected ≈ 0.81"


def test_p_success_monotonic_in_distance():
    """Fixed CBR, P_success strictly decreases with distance."""
    m = PDRModel()
    last = float("inf")
    for d in (0.0, 50.0, 100.0, 200.0, 300.0, 500.0):
        p = m.success_probability(d, 0.3)
        assert p < last, f"non-monotonic at d={d}: {p} ≥ {last}"
        last = p


def test_p_success_monotonic_in_cbr():
    """Fixed distance, P_success monotonically non-increasing in CBR."""
    m = PDRModel(alpha=0.3)
    last = float("inf")
    for cbr in (0.0, 0.25, 0.5, 0.75, 1.0):
        p = m.success_probability(100.0, cbr)
        assert p <= last + 1e-12, f"non-monotonic at cbr={cbr}"
        last = p


def test_p_success_clamps_negative_distance():
    """Negative distance is clamped to 0 (no extrapolation)."""
    m = PDRModel()
    assert m.success_probability(-50.0, 0.0) == m.success_probability(0.0, 0.0)


def test_p_success_clamps_cbr_to_unit_interval():
    m = PDRModel()
    assert m.success_probability(100.0, 1.5) == m.success_probability(100.0, 1.0)
    assert m.success_probability(100.0, -0.2) == m.success_probability(100.0, 0.0)


def test_p_success_load_term_never_negative():
    """Even with α=1 and CBR=1, the load term is clamped at 0 (not negative)."""
    m = PDRModel(alpha=1.0)
    assert m.success_probability(100.0, 1.0) == 0.0


# === Bernoulli sampling ====================================================

def test_delivers_returns_bool():
    m = PDRModel()
    result = m.delivers(100.0, 0.3)
    assert isinstance(result, bool)


def test_delivers_deterministic_with_same_seed():
    m1 = PDRModel(rng=np.random.default_rng(42))
    m2 = PDRModel(rng=np.random.default_rng(42))
    seq1 = [m1.delivers(150.0, 0.4) for _ in range(50)]
    seq2 = [m2.delivers(150.0, 0.4) for _ in range(50)]
    assert seq1 == seq2


def test_delivers_empirical_matches_probability():
    """Empirical hit rate over many draws should match analytic P_success."""
    m = PDRModel(rng=np.random.default_rng(0))
    d, cbr = 100.0, 0.3
    p = m.success_probability(d, cbr)
    n = 20000
    hits = sum(1 for _ in range(n) if m.delivers(d, cbr))
    empirical = hits / n
    # Standard error of a Bernoulli proportion: sqrt(p(1-p)/n) ≈ 0.0028
    # for p≈0.7, n=20000. Allow 5σ.
    assert abs(empirical - p) < 0.02, f"empirical {empirical} vs analytic {p}"


def test_delivers_always_true_when_probability_is_one():
    m = PDRModel(rng=np.random.default_rng(0))
    # At d=0, ρ=0 → P=1 exactly; every draw must succeed.
    for _ in range(500):
        assert m.delivers(0.0, 0.0) is True


def test_delivers_always_false_when_probability_is_zero():
    m = PDRModel(alpha=1.0, rng=np.random.default_rng(0))
    # α=1, ρ=1 → load_term=0 → P=0; every draw must fail.
    for _ in range(500):
        assert m.delivers(100.0, 1.0) is False


# === Profile presets =======================================================

def test_realistic_profile_matches_default():
    a = realistic_profile()
    b = PDRModel()
    assert a.d_ref_m == b.d_ref_m
    assert a.gamma == b.gamma
    assert a.alpha == b.alpha


def test_ideal_profile_always_delivers():
    """Perfect-channel control: every draw succeeds regardless of d, ρ."""
    m = ideal_profile(np.random.default_rng(0))
    for d in (0.0, 100.0, 300.0, 1000.0):
        for cbr in (0.0, 0.5, 1.0):
            # Probability is effectively 1 (alpha=0, d_ref enormous).
            assert m.success_probability(d, cbr) > 0.9999
            # And actual draws all succeed.
            for _ in range(50):
                assert m.delivers(d, cbr) is True


def test_lossy_profile_strictly_worse_than_realistic():
    """At any non-trivial (d, ρ), lossy yields lower P_success than realistic."""
    realistic = realistic_profile()
    lossy = lossy_profile()
    for d in (50.0, 100.0, 200.0):
        for cbr in (0.0, 0.3, 0.7):
            pr = realistic.success_probability(d, cbr)
            pl = lossy.success_probability(d, cbr)
            assert pl < pr, f"at ({d}, {cbr}): lossy {pl} ≥ realistic {pr}"
