"""End-to-end V2X latency model (Sprint 3 module 2).

Per proposal §4.3.1, adopted from Coll-Perales et al. (IEEE TVT 2022) with
the 5G NR PHY decomposition of Yi et al. (PLOS One 2025):

    T_e2e(d, load, size) = T_proc_tx + T_tx(size) + T_prop(d)
                         + T_queue(load) + T_proc_rx

Components:
    T_proc_tx, T_proc_rx ∈ [1, 3] ms per UE class (3GPP TS 38.214).
    T_tx                = ceil(payload_bits / bits_per_slot) * slot_duration.
                          Defaults are Sub-6 GHz, SCS = 30 kHz (5G NR
                          numerology 1) → slot ≈ 0.5 ms; bits_per_slot is
                          a conservative average accounting for MCS and PRB
                          allocation in Mode 2 sidelink. Tunable per ablation.
    T_prop(d)           = d / c   (speed of light; not a tunable parameter).
    T_queue(load)       = queue_slope_ms * channel_busy_ratio.
                          A linear approximation of the M/D/1 queue formula
                          ρ² / (2μ(1-ρ)), valid for ρ ≲ 0.7. Coefficient is
                          tunable per ablation; documented as deviating from
                          a full M/D/1 in the deliverable.

Per-message latency draws an additive Gaussian jitter ~ N(0, σ²) around the
deterministic mean and clamps to [0, ∞). Default σ = 5 ms matches urban-dense
NR-V2X measurements reported by Coll-Perales et al.

Three presets covering proposal §4.6's latency-profile ablation axis:
  - realistic_profile : LatencyModel with the defaults above
  - ideal_profile     : all components zero (the proposal's "0 ms" baseline)
  - degraded_profile  : 2× the realistic mean (proposal's "×2" stress case)
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

import numpy as np


SPEED_OF_LIGHT_M_PER_S = 299_792_458.0


def _default_rng() -> np.random.Generator:
    return np.random.default_rng(0)


@dataclass
class LatencyModel:
    """Per-message end-to-end V2X latency, in milliseconds.

    The model is stateful only in its `rng` — every other field is a fixed
    parameter set at construction. Seed the rng (or pass a pre-seeded
    generator) to keep ablation runs deterministic across seeds (§4.5).
    """

    # 3GPP TS 38.214 UE processing time bounds. Middle of [1, 3] ms.
    proc_tx_ms: float = 2.0
    proc_rx_ms: float = 2.0

    # 5G NR numerology 1 (Sub-6 GHz, SCS = 30 kHz): slot = 0.5 ms.
    slot_duration_ms: float = 0.5
    # Bits per slot capacity envelope; calibrated so a typical 500-byte CPM
    # uses ~1-2 slots → T_tx ∈ [0.5, 1.0] ms, matching the proposal's
    # "0.5-2 ms for typical CPM sizes" envelope.
    bits_per_slot: int = 4000

    # Linear M/D/1 approximation: T_queue(ρ) = queue_slope_ms * ρ.
    # 10 ms at ρ=1 (saturation), 5 ms at ρ=0.5 (heavy load).
    queue_slope_ms: float = 10.0

    # Gaussian jitter σ; tuned to NR-V2X urban-dense measurements.
    jitter_sigma_ms: float = 5.0

    rng: np.random.Generator = field(default_factory=_default_rng)

    # --- queries --------------------------------------------------------

    def components(
        self,
        distance_m: float,
        msg_size_bytes: int,
        channel_busy_ratio: float,
    ) -> dict[str, float]:
        """Return the deterministic mean components (no jitter applied)."""
        # T_tx: at least one slot even for a zero-byte payload (header takes
        # a slot in practice).
        bits = max(0, msg_size_bytes) * 8
        slots = max(1, -(-bits // self.bits_per_slot))  # ceil division
        t_tx = slots * self.slot_duration_ms

        t_prop = max(0.0, distance_m) / SPEED_OF_LIGHT_M_PER_S * 1000.0

        cbr = max(0.0, min(1.0, channel_busy_ratio))
        t_queue = self.queue_slope_ms * cbr

        return {
            "proc_tx_ms": self.proc_tx_ms,
            "t_tx_ms":    t_tx,
            "t_prop_ms":  t_prop,
            "t_queue_ms": t_queue,
            "proc_rx_ms": self.proc_rx_ms,
        }

    def mean(
        self,
        distance_m: float,
        msg_size_bytes: int,
        channel_busy_ratio: float,
    ) -> float:
        """Deterministic mean E2E latency in ms (no jitter)."""
        return sum(self.components(distance_m, msg_size_bytes, channel_busy_ratio).values())

    def sample(
        self,
        distance_m: float,
        msg_size_bytes: int,
        channel_busy_ratio: float,
    ) -> float:
        """Sample one E2E latency: mean + N(0, σ²), clamped to [0, ∞)."""
        m = self.mean(distance_m, msg_size_bytes, channel_busy_ratio)
        if self.jitter_sigma_ms == 0.0:
            return m
        return max(0.0, m + float(self.rng.normal(0.0, self.jitter_sigma_ms)))


# === Profile factories =====================================================
#
# These cover the latency axis of proposal §4.6's ablation matrix:
#   ideal (0 ms) | realistic (default) | degraded (×2)

def realistic_profile(rng: Optional[np.random.Generator] = None) -> LatencyModel:
    """Default LatencyModel — the proposal's 'Realistic' latency profile."""
    return LatencyModel(rng=rng if rng is not None else _default_rng())


def ideal_profile(rng: Optional[np.random.Generator] = None) -> LatencyModel:
    """Zero-latency baseline: every component is 0, no jitter.

    The proposal's 'Ideal (0 ms)' arm of the latency ablation. Note bits_per_slot
    is left at a huge value so T_tx (= slots * 0) is 0 regardless of msg size.
    """
    return LatencyModel(
        proc_tx_ms=0.0, proc_rx_ms=0.0,
        slot_duration_ms=0.0,
        bits_per_slot=10**9,
        queue_slope_ms=0.0,
        jitter_sigma_ms=0.0,
        rng=rng if rng is not None else _default_rng(),
    )


def degraded_profile(rng: Optional[np.random.Generator] = None) -> LatencyModel:
    """2× the realistic protocol-mean, for proposal's 'Degraded (×2)' arm.

    Doubles every tunable protocol-overhead component:
      - proc_tx_ms, proc_rx_ms  (worse UE processing)
      - t_tx                    (via bits_per_slot halved → 2× slots per msg;
                                 slot_duration_ms is held fixed since it's a
                                 5G NR numerology constant, not a tunable)
      - queue_slope_ms          (more contention)
      - jitter_sigma_ms         (more variance)

    Propagation t_prop = d/c is left alone — it's a physical constant, not a
    tunable protocol parameter.
    """
    base = realistic_profile()
    return replace(
        base,
        proc_tx_ms=base.proc_tx_ms * 2.0,
        proc_rx_ms=base.proc_rx_ms * 2.0,
        # slot_duration_ms unchanged: physical NR numerology.
        # bits_per_slot halved → 2× slots per msg → T_tx doubled.
        bits_per_slot=base.bits_per_slot // 2,
        queue_slope_ms=base.queue_slope_ms * 2.0,
        jitter_sigma_ms=base.jitter_sigma_ms * 2.0,
        rng=rng if rng is not None else _default_rng(),
    )
