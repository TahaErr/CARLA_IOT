"""Packet Delivery Ratio (PDR) model for NR-V2X (Sprint 3 module 3).

Per proposal §4.3.2, following Thandavarayan et al. (IEEE TVT 2020) and
Ahangar et al. (Vehicles 2023):

    P_success(d, ρ) = (1 − α · ρ) · exp(−(d / d_ref)^γ)

where d is the broadcaster→receiver distance in metres, ρ is the channel
busy ratio (CBR) in [0, 1], and (d_ref, γ, α) are tunable parameters.

Defaults from proposal §4.3.2:
    d_ref = 220 m   — distance at which the distance term reaches e⁻¹ ≈ 37%
    γ     = 2       — squared decay (free-space attenuation envelope)
    α     = 0.3     — mid of [0.2, 0.4] load-sensitivity range

These defaults are calibrated to anchor PDR ≈ 81% at 100 m under idle
channel, matching the proposal's quoted "≈80% at 100 m" empirical anchor.
The proposal's secondary anchor "≈50% at 250 m" is not strictly consistent
with γ=2; with these defaults we get ≈28% at 250 m. The two-anchor target
fits γ≈1 better, but proposal explicitly mandates γ=2 with a free-space
rationale, so we follow that and treat d_ref as the dominant tunable.

Each transmitted CPM is a single Bernoulli draw at probability P_success(d, ρ);
no retransmission (CPM Release 2 broadcast is unacknowledged).

Profile presets covering the ablation matrix:
  - realistic_profile : the proposal default
  - ideal_profile     : P_success ≈ 1 everywhere (control arm; the 'perfect
                        channel' baseline that lets us isolate detector and
                        fusion-module contributions from channel effects)
  - lossy_profile     : d_ref halved + α at top of range (defensive stress
                        case for ablations where degraded latency is paired
                        with worsened delivery)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


def _default_rng() -> np.random.Generator:
    return np.random.default_rng(0)


@dataclass
class PDRModel:
    """Distance- and load-dependent packet delivery probability.

    Stateful only in `rng`. All other fields are fixed at construction; vary
    them through the profile factories (or directly) for ablation sweeps.
    """

    # Distance at which the distance term equals e^-1 (≈ 37%).
    d_ref_m: float = 220.0
    # Decay exponent (γ=2: free-space-style envelope).
    gamma: float = 2.0
    # Load sensitivity coefficient; α·ρ scales the distance term down.
    alpha: float = 0.3

    rng: np.random.Generator = field(default_factory=_default_rng)

    # --- queries --------------------------------------------------------

    def success_probability(
        self,
        distance_m: float,
        channel_busy_ratio: float,
    ) -> float:
        """Return the deterministic P_success(d, ρ) ∈ [0, 1].

        Negative distance is treated as 0; CBR outside [0, 1] is clamped.
        """
        d = max(0.0, distance_m)
        cbr = max(0.0, min(1.0, channel_busy_ratio))
        load_term = max(0.0, 1.0 - self.alpha * cbr)
        distance_term = math.exp(-((d / self.d_ref_m) ** self.gamma))
        return load_term * distance_term

    def delivers(
        self,
        distance_m: float,
        channel_busy_ratio: float,
    ) -> bool:
        """Bernoulli draw: True iff one CPM transmission succeeds."""
        p = self.success_probability(distance_m, channel_busy_ratio)
        return float(self.rng.random()) < p


# === Profile factories =====================================================

def realistic_profile(rng: Optional[np.random.Generator] = None) -> PDRModel:
    """Default PDRModel — the proposal's stated channel."""
    return PDRModel(rng=rng if rng is not None else _default_rng())


def ideal_profile(rng: Optional[np.random.Generator] = None) -> PDRModel:
    """Perfect-channel control arm: P_success ≈ 1 everywhere.

    Implemented by parameter override (α = 0, d_ref enormous) rather than
    branch logic in `delivers`, so calibration scripts and tests still
    exercise the same probability formula.
    """
    return PDRModel(
        d_ref_m=1.0e9,
        gamma=2.0,
        alpha=0.0,
        rng=rng if rng is not None else _default_rng(),
    )


def lossy_profile(rng: Optional[np.random.Generator] = None) -> PDRModel:
    """Stress channel: shorter effective range + top-of-spec load sensitivity.

    d_ref halved (→ same P at half the distance), α at the upper end
    of [0.2, 0.4]. Use this in ablation runs paired with degraded latency
    to characterise the floor of system safety.
    """
    return PDRModel(
        d_ref_m=110.0,
        gamma=2.0,
        alpha=0.4,
        rng=rng if rng is not None else _default_rng(),
    )
