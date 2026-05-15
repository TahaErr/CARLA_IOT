"""Tests for v2xsim.compute_budget — Sprint 3 module 4.

Verifies admit semantics (per-RSU + aggregate gating), state isolation
across RSUs and across windows, utilization reporting, and the three
profile presets (unconstrained / Orin / Xavier) used by proposal §4.6's
ablation matrix.

Run from repo root:
    pytest tests/test_compute_budget.py -v
"""
from __future__ import annotations

import math

import pytest

from v2xsim.compute_budget import (
    BudgetTracker,
    orin_profile,
    unconstrained_profile,
    xavier_profile,
)


# === Admit semantics =======================================================

def test_admit_within_budget_returns_true():
    t = BudgetTracker(per_rsu_budget_ms=20.0, aggregate_budget_ms=100.0)
    assert t.admit("rsu0", 5.0) is True


def test_admit_exceeding_per_rsu_returns_false():
    t = BudgetTracker(per_rsu_budget_ms=20.0, aggregate_budget_ms=100.0)
    assert t.admit("rsu0", 25.0) is False


def test_admit_exceeding_aggregate_returns_false():
    """One huge frame can exhaust the aggregate even with idle per-RSU budget."""
    t = BudgetTracker(per_rsu_budget_ms=100.0, aggregate_budget_ms=50.0)
    assert t.admit("rsu0", 60.0) is False  # 60 ≤ 100 per-RSU, but > 50 aggregate


def test_admit_at_exact_budget_accepts():
    """A frame whose cost is exactly the budget is accepted (≤ not <)."""
    t = BudgetTracker(per_rsu_budget_ms=20.0, aggregate_budget_ms=20.0)
    assert t.admit("rsu0", 20.0) is True


def test_drop_does_not_advance_counters():
    """A dropped frame must not consume any budget."""
    t = BudgetTracker(per_rsu_budget_ms=20.0, aggregate_budget_ms=100.0)
    assert t.admit("rsu0", 5.0) is True
    assert t.admit("rsu0", 30.0) is False  # exceeds per-RSU
    # The state for rsu0 should still reflect only the 5 ms accepted.
    assert t.per_rsu_used_ms["rsu0"] == 5.0
    assert t.aggregate_used_ms == 5.0


def test_accumulates_across_admits_for_same_rsu():
    t = BudgetTracker(per_rsu_budget_ms=20.0, aggregate_budget_ms=100.0)
    t.admit("rsu0", 7.0)
    t.admit("rsu0", 8.0)
    # 15 ms used, next 6 ms would push to 21 → reject
    assert t.admit("rsu0", 6.0) is False
    # but 5 ms (→ 20) still fits exactly
    assert t.admit("rsu0", 5.0) is True


def test_negative_inference_clamped_to_zero():
    """Defensive: negative inference time is clamped, not rejected."""
    t = BudgetTracker(per_rsu_budget_ms=20.0, aggregate_budget_ms=100.0)
    assert t.admit("rsu0", -5.0) is True
    assert t.per_rsu_used_ms.get("rsu0", 0.0) == 0.0


# === State isolation =======================================================

def test_per_rsu_budgets_are_independent():
    """RSUs don't share their per-RSU budget — only the aggregate."""
    t = BudgetTracker(per_rsu_budget_ms=10.0, aggregate_budget_ms=1000.0)
    assert t.admit("rsu0", 10.0) is True  # fills rsu0
    assert t.admit("rsu0", 1.0) is False  # rsu0 full
    assert t.admit("rsu1", 10.0) is True  # rsu1 untouched


def test_aggregate_is_shared_across_rsus():
    """All RSUs draw from the same aggregate pool."""
    t = BudgetTracker(per_rsu_budget_ms=100.0, aggregate_budget_ms=20.0)
    assert t.admit("rsu0", 15.0) is True
    # 5 ms left in aggregate; rsu1 wants 10 → reject
    assert t.admit("rsu1", 10.0) is False
    # rsu1 can still get 5
    assert t.admit("rsu1", 5.0) is True


# === Window reset ==========================================================

def test_reset_window_clears_all_counters():
    t = BudgetTracker(per_rsu_budget_ms=20.0, aggregate_budget_ms=100.0)
    t.admit("rsu0", 15.0)
    t.admit("rsu1", 5.0)
    t.reset_window()
    assert t.per_rsu_used_ms == {}
    assert t.aggregate_used_ms == 0.0
    # And new admits after reset should work normally.
    assert t.admit("rsu0", 20.0) is True


def test_reset_window_preserves_budgets():
    """Budgets are config; reset only clears the counters."""
    t = BudgetTracker(per_rsu_budget_ms=20.0, aggregate_budget_ms=100.0)
    t.admit("rsu0", 10.0)
    t.reset_window()
    assert t.per_rsu_budget_ms == 20.0
    assert t.aggregate_budget_ms == 100.0


# === Utilization ===========================================================

def test_utilization_reports_per_rsu_and_aggregate_fractions():
    t = BudgetTracker(per_rsu_budget_ms=20.0, aggregate_budget_ms=100.0)
    t.admit("rsu0", 10.0)  # 50% of rsu0's budget
    t.admit("rsu1", 5.0)   # 25% of rsu1's budget
    u = t.utilization()
    assert u["per_rsu"]["rsu0"] == 0.5
    assert u["per_rsu"]["rsu1"] == 0.25
    assert u["aggregate"] == 0.15  # 15 / 100


def test_utilization_for_unconstrained_is_zero():
    """Infinite budget → utilization reported as 0 (fraction of infinity)."""
    t = unconstrained_profile(n_rsus=15)
    t.admit("rsu0", 100.0)
    u = t.utilization()
    assert u["per_rsu"] == {}  # nothing tracked when per-RSU is infinite
    assert u["aggregate"] == 0.0


# === Profile presets =======================================================

def test_unconstrained_admits_everything():
    t = unconstrained_profile(n_rsus=15)
    for _ in range(1000):
        assert t.admit("rsu_any", 1e6) is True


def test_orin_profile_budget_values():
    t = orin_profile(n_rsus=15)
    assert t.per_rsu_budget_ms == 20.0
    assert t.aggregate_budget_ms == 20.0 * 15 * 0.3  # 90 ms


def test_xavier_profile_budget_values():
    t = xavier_profile(n_rsus=15)
    assert t.per_rsu_budget_ms == 50.0
    assert t.aggregate_budget_ms == 50.0 * 15 * 0.3  # 225 ms


def test_orin_aggregate_binding_under_busy_hour():
    """With Orin profile + Town05 (15 RSUs), aggregate (90 ms) is binding
    when ~30% of RSUs run at full per-RSU load."""
    t = orin_profile(n_rsus=15)
    # 4 RSUs each consuming 20 ms = 80 ms total → all admit (≤ 90 agg)
    for i in range(4):
        assert t.admit(f"rsu{i}", 20.0) is True
    # 5th RSU at full 20 ms would push aggregate to 100 → reject
    assert t.admit("rsu4", 20.0) is False
    # but 10 ms would fit (90 total)
    assert t.admit("rsu4", 10.0) is True


def test_profile_signatures_are_swappable():
    """All three preset factories accept the same n_rsus arg and return
    a BudgetTracker, so the ablation runner can swap freely."""
    for factory in (unconstrained_profile, orin_profile, xavier_profile):
        t = factory(n_rsus=15)
        assert isinstance(t, BudgetTracker)
