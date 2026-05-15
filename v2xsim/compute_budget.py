"""Edge-compute budget tracker for the RSU pipeline (Sprint 3 module 4).

Per proposal §4.4, every RSU's inference work is gated by two limits:

  1. **Per-RSU budget**: max inference time the local edge platform can
     spend per CPM period. Models a Jetson-class device's compute envelope:
       - Orin-class    ≈ 20 ms / frame
       - Xavier-class  ≈ 50 ms / frame
       - Unconstrained = no limit (proposal §4.6 baseline arm)

  2. **Aggregate budget**: city-wide pool that all RSUs share, motivated by
     the observation that an MEC backhaul compresses real shared compute
     into roughly 10% of an idealised L4 onboard stack. We approximate this
     by setting aggregate = per_rsu × n_rsus × 0.3 — a calibration knob, not
     a derived quantity. (At ratio 1.0 the aggregate is non-binding; at 0
     no RSU ever admits. 0.3 leaves room for ~30% of RSUs running flat-out
     simultaneously, which matches the busy-hour intuition in §4.4.)

A frame is **ACCEPTed** iff its inference cost fits in BOTH budgets;
otherwise it is **DROPped** and the simulator must skip that frame's
detection (one of the "graceful degradation" modes proposal §4.4 mentions).
Resolution down-sampling, the other degradation mode, is handled by the
Sprint 4 ablation runner varying `imgsz`, not by this module.

Accounting window: the model is window-based (default 100 ms = one 10 Hz
CPM period). Call `reset_window()` at the start of each new accounting
window. State carries no time semantics on its own.

Profile presets covering the ablation matrix (proposal §4.6):
  - unconstrained_profile : no limit, no DROPs (the baseline)
  - orin_profile          : 20 ms/RSU, aggregate scaled
  - xavier_profile        : 50 ms/RSU, aggregate scaled
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


# Fraction of (per_rsu × n_rsus) that the aggregate budget represents.
# At 0.3, the aggregate is binding when ~30% of RSUs are at full per-RSU
# load — roughly the "busy-hour" intuition in §4.4.
_AGGREGATE_FRACTION = 0.3


@dataclass
class BudgetTracker:
    """Window-based per-RSU + aggregate inference-time budget tracker.

    The class is purely an accountant; it does not know simulation time.
    The caller is responsible for invoking `reset_window()` at the start
    of each new CPM period.
    """

    per_rsu_budget_ms: float
    aggregate_budget_ms: float

    per_rsu_used_ms: dict[str, float] = field(default_factory=dict)
    aggregate_used_ms: float = 0.0

    # --- counters --------------------------------------------------------

    def admit(self, rsu_id: str, inference_ms: float) -> bool:
        """Try to admit one inference event from `rsu_id` costing `inference_ms`.

        Returns True (ACCEPT) iff the new total fits in both this RSU's
        per-window budget AND the city-wide aggregate. On accept, both
        counters advance; on drop, neither changes.

        Negative `inference_ms` is treated as 0 (defensive against caller bugs).
        """
        cost = max(0.0, inference_ms)
        new_per_rsu = self.per_rsu_used_ms.get(rsu_id, 0.0) + cost
        new_aggregate = self.aggregate_used_ms + cost

        if new_per_rsu > self.per_rsu_budget_ms:
            return False
        if new_aggregate > self.aggregate_budget_ms:
            return False

        self.per_rsu_used_ms[rsu_id] = new_per_rsu
        self.aggregate_used_ms = new_aggregate
        return True

    def reset_window(self) -> None:
        """Start a new accounting window — clears all per-RSU and aggregate
        counters but keeps the configured budgets."""
        self.per_rsu_used_ms.clear()
        self.aggregate_used_ms = 0.0

    # --- queries ---------------------------------------------------------

    def utilization(self) -> dict:
        """Return budget utilization fractions for the current window.

        Returns:
            {
              "per_rsu": {rsu_id: used_fraction, ...},  # in [0, 1]
              "aggregate": used_fraction,               # in [0, 1]
            }

        For unconstrained (infinite) budgets, the corresponding fractions
        are reported as 0.0 (well-defined choice — fraction of infinity is 0).
        """
        per_rsu: dict[str, float] = {}
        if self.per_rsu_budget_ms > 0 and not math.isinf(self.per_rsu_budget_ms):
            for rsu_id, used in self.per_rsu_used_ms.items():
                per_rsu[rsu_id] = used / self.per_rsu_budget_ms

        aggregate = 0.0
        if self.aggregate_budget_ms > 0 and not math.isinf(self.aggregate_budget_ms):
            aggregate = self.aggregate_used_ms / self.aggregate_budget_ms

        return {"per_rsu": per_rsu, "aggregate": aggregate}


# === Profile factories =====================================================

def unconstrained_profile(n_rsus: int) -> BudgetTracker:
    """No edge constraints — proposal §4.6 baseline arm.

    `n_rsus` is accepted but unused; the signature matches the constrained
    profiles so the caller can swap freely between them.
    """
    _ = n_rsus  # kept for API symmetry with constrained profiles
    return BudgetTracker(
        per_rsu_budget_ms=float("inf"),
        aggregate_budget_ms=float("inf"),
    )


def orin_profile(n_rsus: int) -> BudgetTracker:
    """Jetson AGX Orin class: 20 ms/frame per RSU, aggregate scaled."""
    per_rsu = 20.0
    return BudgetTracker(
        per_rsu_budget_ms=per_rsu,
        aggregate_budget_ms=per_rsu * n_rsus * _AGGREGATE_FRACTION,
    )


def xavier_profile(n_rsus: int) -> BudgetTracker:
    """Jetson Xavier class: 50 ms/frame per RSU, aggregate scaled."""
    per_rsu = 50.0
    return BudgetTracker(
        per_rsu_budget_ms=per_rsu,
        aggregate_budget_ms=per_rsu * n_rsus * _AGGREGATE_FRACTION,
    )
