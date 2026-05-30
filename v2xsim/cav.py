"""CAV time-aware late-fusion module (Sprint 4 Module 2).

Implements proposal §4.1.1 — the project's main algorithmic contribution.
CARLA-agnostic; Sprint 4 Module 5 (ablation runner) wraps a CAVCore
instance per CARLA vehicle.

Per-tick interface (caller controls ordering):

  1. register_rsu(rsu_id, world_xy)                # once at setup
  2. ingest_local_detections(detections, t_now)    # optional, every tick
  3. ingest_cpm(cpm, rsu_id, send_t_ms, t_now)     # one call per arrival
  4. update(ego_x, ego_y, ego_vx, ego_vy, t_now)
     → CAVDecision (action + diagnostic snapshots)

Confirmation hysteresis (proposal §4.1.1 step 5) is the key safety
mechanism. A track triggers a CAV reaction ONLY IF at least one of:

  (a) confirmed by the CAV's own local sensor in any frame, OR
  (b) reported in ≥ 2 consecutive CPMs from the same RSU, OR
  (c) reported by ≥ 2 distinct RSUs within a sliding 500 ms window.

Single-CPM unconfirmed tracks are kept in the model (so the CAV is
"aware" of them) but cannot trigger braking — this prevents one spurious
detection from causing emergency braking (phantom-brake protection).
The CAVDecision.phantom_brake_suppressed flag reports when the hysteresis
rule actively prevented an action that would otherwise have fired.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .cpm import CPM


# === Action enum ===========================================================

class Action(Enum):
    NONE = "none"
    DECELERATE = "decelerate"
    SOFT_BRAKE = "soft_brake"
    HARD_BRAKE = "hard_brake"


# Action priority for "most aggressive wins" merging across tracks.
_ACTION_SEVERITY = {
    Action.NONE: 0,
    Action.DECELERATE: 1,
    Action.SOFT_BRAKE: 2,
    Action.HARD_BRAKE: 3,
}


# === Public dataclasses ====================================================

@dataclass(frozen=True)
class Track:
    """Snapshot of one tracked object, returned by `get_tracks()` and
    inside CAVDecision. Immutable; CAVCore holds mutable state internally."""
    track_id: int
    object_class: str
    x_m: float
    y_m: float
    vx_ms: float
    vy_ms: float
    confidence: float                    # current value (post-decay)
    last_seen_sim_time_ms: float
    confirmed_by_local: bool
    rsu_observation_count: int           # total CPMs received for this track
    distinct_rsus_in_window: int         # # distinct RSUs in sliding window
    is_confirmed: bool                   # hysteresis result


@dataclass(frozen=True)
class LocalDetection:
    """One detection from the CAV's own sensor.

    Local detections always mark the matched track confirmed_by_local,
    overriding the CPM-based hysteresis rules. In Sprint 4 the CARLA
    wrapper synthesises these from a ground-truth cone in front of
    the ego (proposal §4.1.1 references "AV's own local sensor").
    """
    object_class: str
    x_m: float
    y_m: float
    vx_ms: float = 0.0
    vy_ms: float = 0.0
    confidence: float = 1.0


@dataclass(frozen=True)
class CAVDecision:
    """Output of one CAVCore.update() call.

    `phantom_brake_suppressed` is True iff at least one unconfirmed
    track was close enough + confident enough to have triggered an
    action, but was held back by the hysteresis rule. This is the
    metric the proposal §4.1.1 contribution is measured against.

    `cooperative_brake` is True iff the action was raised (in whole or in
    part) by a V2V hard-brake warning from a leader ahead (Sprint 5
    cooperative-awareness / DENM path), rather than purely by the
    track-based TTC ladder.
    """
    action: Action
    triggering_track_id: Optional[int]
    ttc_s: Optional[float]
    confirmed_tracks: tuple[Track, ...]
    unconfirmed_tracks: tuple[Track, ...]
    phantom_brake_suppressed: bool
    cooperative_brake: bool = False


# === Defaults from proposal §4.1.1 step 6 =================================

DEFAULT_TTC_LADDER = (
    # (action, max_ttc_s, min_confidence)
    (Action.HARD_BRAKE, 1.0, 0.8),
    (Action.SOFT_BRAKE, 2.5, 0.6),
    (Action.DECELERATE, 4.0, 0.4),
)


# Per-class maximum-acceleration cap (proposal §4.1.1 step 2). Reserved
# for future use — exposed in the constructor so ablation studies can
# tune the cap on track propagation extrapolation.
_DEFAULT_MAX_ACCEL_MS2 = {
    "passengerCar": 5.0,
    "motorcycle":   6.0,
    "pedalCycle":   2.0,
    "pedestrian":   2.0,
}


# === Internal mutable track ===============================================

@dataclass
class _MutableTrack:
    track_id: int
    object_class: str
    x_m: float
    y_m: float
    vx_ms: float
    vy_ms: float
    base_confidence: float              # confidence from most recent CPM
    last_seen_sim_time_ms: float
    confirmed_by_local: bool = False
    # (rsu_id, sim_time_ms) — used for hysteresis rules (b) and (c).
    rsu_observations: list = field(default_factory=list)


# === CAVCore ==============================================================

class CAVCore:
    """Per-CAV time-aware late-fusion module.

    Owns track state for one V2X-equipped autonomous vehicle. Inputs are
    world-frame; ego state is passed at update() time only. Deterministic
    given input order — designed for full unit-testing without CARLA.
    """

    def __init__(
        self,
        cav_id: str,
        track_ttl_ms: float = 1000.0,
        association_gate_m: float = 5.0,
        hysteresis_window_ms: float = 500.0,
        ttc_ladder: tuple = DEFAULT_TTC_LADDER,
        safety_radius_m: float = 2.5,
        max_accel_ms2: Optional[dict] = None,
        brake_warning_ttl_ms: float = 1000.0,
        brake_warning_range_m: float = 40.0,
        brake_warning_cone_deg: float = 90.0,
        brake_warning_action: Action = Action.SOFT_BRAKE,
    ):
        """Args:
            cav_id: simulation identifier (used only in diagnostics).
            track_ttl_ms: track lifetime + confidence-decay scale.
                Proposal §4.1.1 default 1000 ms.
            association_gate_m: max distance for matching a new
                observation to an existing track (Euclidean).
            hysteresis_window_ms: sliding window for rule (c) — distinct
                RSU count. Proposal §4.1.1 default 500 ms.
            ttc_ladder: (action, max_ttc_s, min_confidence) tuples in
                priority order. Proposal §4.1.1 step 6 defaults.
            safety_radius_m: track must be predicted to come within
                this distance for TTC to be reported.
            max_accel_ms2: per-class acceleration caps. Reserved for
                future propagation refinement.
            brake_warning_ttl_ms: how long a received V2V hard-brake
                warning stays actionable (Sprint 5 cooperative awareness).
            brake_warning_range_m: only react to a warning whose sender is
                within this distance ahead.
            brake_warning_cone_deg: full forward aperture (±half) within
                which a warning sender counts as "a leader ahead".
            brake_warning_action: action floor a relevant warning imposes.
                A trusted V2V intent bypasses the perception hysteresis —
                the leader is *declaring* its own hard brake, not being
                perceived — so it acts immediately.
        """
        self.cav_id = cav_id
        self.track_ttl_ms = track_ttl_ms
        self.association_gate_m = association_gate_m
        self.hysteresis_window_ms = hysteresis_window_ms
        self.ttc_ladder = tuple(ttc_ladder)
        self.safety_radius_m = safety_radius_m
        self.max_accel_ms2 = dict(max_accel_ms2 or _DEFAULT_MAX_ACCEL_MS2)
        self.brake_warning_ttl_ms = brake_warning_ttl_ms
        self.brake_warning_range_m = brake_warning_range_m
        self.brake_warning_cone_deg = brake_warning_cone_deg
        self.brake_warning_action = brake_warning_action

        self._tracks: dict[int, _MutableTrack] = {}
        self._next_track_id = 1
        self._rsu_positions: dict[str, tuple[float, float]] = {}
        # Received V2V hard-brake warnings: (x, y, vx, vy, sim_time_ms).
        self._brake_warnings: list[tuple[float, float, float, float, float]] = []

    # --- setup ---------------------------------------------------------

    def register_rsu(self, rsu_id: str, world_xy: tuple[float, float]) -> None:
        """Tell the CAV where an RSU sits in world coordinates.

        CPMs carry object positions relative to the sender RSU's reference;
        the CAV must know absolute RSU positions to project incoming
        objects into the simulation world frame.
        """
        self._rsu_positions[rsu_id] = tuple(world_xy)  # type: ignore[arg-type]

    def register_station(self, station_id: str, world_xy: tuple[float, float]) -> None:
        """Alias of `register_rsu` for non-RSU senders (Sprint 5 V2V).

        The position registry is station-agnostic — a fixed RSU registers
        once at setup, while a mobile V2V (CAV) sender re-registers its
        *current* pose on every message before `ingest_cpm` is called.
        """
        self.register_rsu(station_id, world_xy)

    def ingest_brake_warning(
        self,
        sender_x_m: float,
        sender_y_m: float,
        sender_vx_ms: float,
        sender_vy_ms: float,
        sim_time_ms: float,
    ) -> None:
        """Record a V2V hard-brake warning from another vehicle (Sprint 5).

        Unlike a perceived object, this is the *sender's declaration of its
        own emergency braking*. It is consumed in `update()`: if the sender
        is a leader ahead within range, the ego pre-brakes without waiting
        for the perception hysteresis to confirm a track.
        """
        self._brake_warnings.append(
            (sender_x_m, sender_y_m, sender_vx_ms, sender_vy_ms, sim_time_ms)
        )

    # --- ingest --------------------------------------------------------

    def ingest_local_detections(
        self,
        detections: list[LocalDetection],
        sim_time_ms: float,
    ) -> None:
        """Inject the CAV's own sensor detections.

        Any track an incoming detection matches is marked
        `confirmed_by_local`, which makes it immediately eligible to
        trigger an action regardless of CPM observation history.
        New tracks created this way are also `confirmed_by_local=True`.
        """
        for det in detections:
            existing = self._find_associable_track(det.x_m, det.y_m, det.object_class)
            if existing is not None:
                existing.x_m = det.x_m
                existing.y_m = det.y_m
                existing.vx_ms = det.vx_ms
                existing.vy_ms = det.vy_ms
                existing.base_confidence = max(existing.base_confidence, det.confidence)
                existing.last_seen_sim_time_ms = sim_time_ms
                existing.confirmed_by_local = True
            else:
                self._create_track(
                    object_class=det.object_class,
                    x_m=det.x_m, y_m=det.y_m,
                    vx_ms=det.vx_ms, vy_ms=det.vy_ms,
                    base_confidence=det.confidence,
                    sim_time_ms=sim_time_ms,
                    confirmed_by_local=True,
                )

    def ingest_cpm(
        self,
        cpm: CPM,
        rsu_id: str,
        cpm_send_sim_time_ms: float,
        sim_time_ms: float,
    ) -> None:
        """Apply propagation + association + history bookkeeping for one CPM.

        Args:
            cpm: the decoded CPM.
            rsu_id: identifier matching `register_rsu()` and Broker sender_id.
            cpm_send_sim_time_ms: absolute sim time when the RSU sent it.
            sim_time_ms: current sim time at the CAV (= arrival time).

        CPM objects come with RSU-relative coordinates. We translate to
        world frame, propagate forward by Δt = (now - send) under
        constant-velocity assumption, decay the per-object confidence by
        the same Δt / TTL, and either associate to an existing track or
        create a new one. The CPM is silently dropped if `rsu_id` is
        not in the registry (caller's setup mistake).
        """
        if rsu_id not in self._rsu_positions:
            return

        rsu_x, rsu_y = self._rsu_positions[rsu_id]
        delta_t_ms = sim_time_ms - cpm_send_sim_time_ms
        delta_t_s = max(0.0, delta_t_ms / 1000.0)
        ttl_ms = self.track_ttl_ms

        for obj in cpm.objects:
            # CPM-relative → world frame.
            world_x = rsu_x + obj.x_m
            world_y = rsu_y + obj.y_m
            # Forward-propagate (constant-velocity).
            prop_x = world_x + obj.vx_ms * delta_t_s
            prop_y = world_y + obj.vy_ms * delta_t_s
            # Decay confidence linearly with age (proposal §4.1.1 step 4).
            decayed_conf = obj.confidence * max(0.0, 1.0 - delta_t_ms / ttl_ms)
            if decayed_conf <= 0.0:
                continue  # already expired before reaching us

            existing = self._find_associable_track(prop_x, prop_y, obj.object_class)
            if existing is not None:
                existing.x_m = prop_x
                existing.y_m = prop_y
                existing.vx_ms = obj.vx_ms
                existing.vy_ms = obj.vy_ms
                # Don't downgrade a recently-strongly-observed track.
                existing.base_confidence = max(existing.base_confidence, decayed_conf)
                existing.last_seen_sim_time_ms = sim_time_ms
                existing.rsu_observations.append((rsu_id, sim_time_ms))
            else:
                new_track = self._create_track(
                    object_class=obj.object_class,
                    x_m=prop_x, y_m=prop_y,
                    vx_ms=obj.vx_ms, vy_ms=obj.vy_ms,
                    base_confidence=decayed_conf,
                    sim_time_ms=sim_time_ms,
                    confirmed_by_local=False,
                )
                new_track.rsu_observations.append((rsu_id, sim_time_ms))

    # --- update --------------------------------------------------------

    def update(
        self,
        ego_x_m: float,
        ego_y_m: float,
        ego_vx_ms: float,
        ego_vy_ms: float,
        sim_time_ms: float,
    ) -> CAVDecision:
        """One decision cycle: prune, compute TTC, apply hysteresis,
        return the most aggressive surviving action.
        """
        self._prune_expired(sim_time_ms)

        confirmed_snapshots: list[Track] = []
        unconfirmed_snapshots: list[Track] = []

        final_action = Action.NONE
        triggering_track_id: Optional[int] = None
        triggering_ttc: Optional[float] = None
        phantom_brake_suppressed = False

        for track in self._tracks.values():
            current_conf = self._current_confidence(track, sim_time_ms)
            confirmed = self._is_confirmed(track, sim_time_ms)
            snap = self._track_snapshot(track, sim_time_ms, current_conf, confirmed)
            if confirmed:
                confirmed_snapshots.append(snap)
            else:
                unconfirmed_snapshots.append(snap)

            ttc = _compute_ttc(
                ego_x_m, ego_y_m, ego_vx_ms, ego_vy_ms,
                track.x_m, track.y_m, track.vx_ms, track.vy_ms,
                self.safety_radius_m,
            )
            if ttc is None:
                continue

            # Find the most aggressive ladder tier that this track meets.
            for candidate, max_ttc, min_conf in self.ttc_ladder:
                if ttc <= max_ttc and current_conf >= min_conf:
                    if not confirmed:
                        # Hysteresis-suppressed: track WOULD have fired
                        # but isn't confirmed. Record and skip.
                        phantom_brake_suppressed = True
                        break
                    if _ACTION_SEVERITY[candidate] > _ACTION_SEVERITY[final_action]:
                        final_action = candidate
                        triggering_track_id = track.track_id
                        triggering_ttc = ttc
                    break  # most aggressive tier wins per track

        # --- Cooperative awareness: V2V hard-brake warnings ------------
        # A leader ahead declaring its own hard brake (DENM-style intent)
        # is trusted directly — it bypasses the perception hysteresis,
        # which exists to filter *uncertain perceived* objects, not a
        # peer's explicit announcement of its own state.
        coop_action = self._cooperative_brake_action(
            ego_x_m, ego_y_m, ego_vx_ms, ego_vy_ms, sim_time_ms
        )
        cooperative_brake = coop_action is not Action.NONE
        if cooperative_brake and (
            _ACTION_SEVERITY[coop_action] > _ACTION_SEVERITY[final_action]
        ):
            final_action = coop_action

        return CAVDecision(
            action=final_action,
            triggering_track_id=triggering_track_id,
            ttc_s=triggering_ttc,
            confirmed_tracks=tuple(confirmed_snapshots),
            unconfirmed_tracks=tuple(unconfirmed_snapshots),
            phantom_brake_suppressed=phantom_brake_suppressed,
            cooperative_brake=cooperative_brake,
        )

    # --- diagnostics ---------------------------------------------------

    def get_tracks(self) -> list[Track]:
        """Snapshot of every track currently known, sorted by track_id.

        Convenience for tests / debug logs. The hysteresis/confidence
        snapshot uses the most recent `last_seen_sim_time_ms` across
        all tracks as the reference time (best-effort if no update()
        has been called yet).
        """
        if not self._tracks:
            return []
        sim_time_ms = max(t.last_seen_sim_time_ms for t in self._tracks.values())
        result = []
        for tid in sorted(self._tracks.keys()):
            t = self._tracks[tid]
            current_conf = self._current_confidence(t, sim_time_ms)
            confirmed = self._is_confirmed(t, sim_time_ms)
            result.append(self._track_snapshot(t, sim_time_ms, current_conf, confirmed))
        return result

    # --- internals -----------------------------------------------------

    def _create_track(
        self,
        object_class: str,
        x_m: float, y_m: float,
        vx_ms: float, vy_ms: float,
        base_confidence: float,
        sim_time_ms: float,
        confirmed_by_local: bool,
    ) -> _MutableTrack:
        tid = self._next_track_id
        self._next_track_id += 1
        track = _MutableTrack(
            track_id=tid,
            object_class=object_class,
            x_m=x_m, y_m=y_m, vx_ms=vx_ms, vy_ms=vy_ms,
            base_confidence=base_confidence,
            last_seen_sim_time_ms=sim_time_ms,
            confirmed_by_local=confirmed_by_local,
        )
        self._tracks[tid] = track
        return track

    def _find_associable_track(
        self, x_m: float, y_m: float, object_class: str
    ) -> Optional[_MutableTrack]:
        """Gated nearest-neighbour over (position, class).

        Class must match exactly; position within `association_gate_m`.
        """
        best = None
        best_d = self.association_gate_m
        for track in self._tracks.values():
            if track.object_class != object_class:
                continue
            d = math.hypot(track.x_m - x_m, track.y_m - y_m)
            if d <= best_d:
                best_d = d
                best = track
        return best

    def _prune_expired(self, sim_time_ms: float) -> None:
        expired = [
            tid for tid, t in self._tracks.items()
            if sim_time_ms - t.last_seen_sim_time_ms > self.track_ttl_ms
        ]
        for tid in expired:
            del self._tracks[tid]

    def _cooperative_brake_action(
        self,
        ego_x_m: float, ego_y_m: float,
        ego_vx_ms: float, ego_vy_ms: float,
        sim_time_ms: float,
    ) -> Action:
        """Return the action imposed by any actionable V2V brake warning.

        A warning is actionable when its sender sits ahead of the ego
        (within `brake_warning_cone_deg` of the ego's heading) and within
        `brake_warning_range_m`. Stale warnings (older than the TTL) are
        pruned here. Returns Action.NONE when nothing applies.
        """
        # Drop expired warnings first.
        self._brake_warnings = [
            w for w in self._brake_warnings
            if sim_time_ms - w[4] <= self.brake_warning_ttl_ms
        ]
        if not self._brake_warnings:
            return Action.NONE

        ego_speed = math.hypot(ego_vx_ms, ego_vy_ms)
        # A stopped ego has no rear-end risk to pre-empt; ignore warnings.
        if ego_speed < 0.5:
            return Action.NONE
        hx = ego_vx_ms / ego_speed
        hy = ego_vy_ms / ego_speed
        cos_half = math.cos(math.radians(self.brake_warning_cone_deg / 2.0))

        for sx, sy, _svx, _svy, _t in self._brake_warnings:
            dx = sx - ego_x_m
            dy = sy - ego_y_m
            d = math.hypot(dx, dy)
            if d < 1e-6 or d > self.brake_warning_range_m:
                continue
            if (dx * hx + dy * hy) / d >= cos_half:
                return self.brake_warning_action
        return Action.NONE

    def _current_confidence(self, track: _MutableTrack, sim_time_ms: float) -> float:
        dt_ms = sim_time_ms - track.last_seen_sim_time_ms
        return track.base_confidence * max(0.0, 1.0 - dt_ms / self.track_ttl_ms)

    def _is_confirmed(self, track: _MutableTrack, sim_time_ms: float) -> bool:
        # Rule (a): local sensor confirmed.
        if track.confirmed_by_local:
            return True
        # Rule (b): ≥ 2 observations from any single RSU.
        per_rsu: dict[str, int] = {}
        for rsu_id, _ in track.rsu_observations:
            per_rsu[rsu_id] = per_rsu.get(rsu_id, 0) + 1
        if any(c >= 2 for c in per_rsu.values()):
            return True
        # Rule (c): ≥ 2 distinct RSUs in sliding window.
        window_start = sim_time_ms - self.hysteresis_window_ms
        recent = {r for r, t in track.rsu_observations if t >= window_start}
        return len(recent) >= 2

    def _track_snapshot(
        self,
        track: _MutableTrack,
        sim_time_ms: float,
        current_conf: float,
        is_confirmed: bool,
    ) -> Track:
        window_start = sim_time_ms - self.hysteresis_window_ms
        distinct_in_win = len({r for r, t in track.rsu_observations if t >= window_start})
        return Track(
            track_id=track.track_id,
            object_class=track.object_class,
            x_m=track.x_m, y_m=track.y_m,
            vx_ms=track.vx_ms, vy_ms=track.vy_ms,
            confidence=current_conf,
            last_seen_sim_time_ms=track.last_seen_sim_time_ms,
            confirmed_by_local=track.confirmed_by_local,
            rsu_observation_count=len(track.rsu_observations),
            distinct_rsus_in_window=distinct_in_win,
            is_confirmed=is_confirmed,
        )


# === TTC computation (proposal §4.1.1 step 6) =============================

def _compute_ttc(
    ego_x: float, ego_y: float, ego_vx: float, ego_vy: float,
    obj_x: float, obj_y: float, obj_vx: float, obj_vy: float,
    safety_radius_m: float,
) -> Optional[float]:
    """Constant-velocity time-to-closest-approach, gated by safety radius.

    Returns:
        None if trajectories will not approach within safety_radius_m,
              or if closest approach is in the past (object behind/moving away),
              or if there's no relative motion and current distance > radius.
        0.0  already in collision (distance < radius, no motion).
        t > 0 seconds until the trajectories will pass within radius.
    """
    rx = obj_x - ego_x
    ry = obj_y - ego_y
    rvx = obj_vx - ego_vx
    rvy = obj_vy - ego_vy

    speed_sq = rvx * rvx + rvy * rvy
    if speed_sq < 1e-9:
        # No relative motion — check current distance.
        if rx * rx + ry * ry < safety_radius_m * safety_radius_m:
            return 0.0
        return None

    # Analytic closest-approach time.
    t_min = -(rx * rvx + ry * rvy) / speed_sq
    if t_min <= 0.0:
        return None

    cx = rx + rvx * t_min
    cy = ry + rvy * t_min
    d_min_sq = cx * cx + cy * cy
    if d_min_sq > safety_radius_m * safety_radius_m:
        return None

    return t_min
