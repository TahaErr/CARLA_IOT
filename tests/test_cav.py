"""Tests for v2xsim.cav — Sprint 4 module 2.

Pure-Python tests for the time-aware late-fusion logic of proposal §4.1.1.
No CARLA, no ASN.1 — only CPM/CPMObject dataclasses (which import without
the ETSI spec files), so this suite runs anywhere.

Test groups:
  A. Track lifecycle: creation, association, TTL pruning, unknown RSU drop
  B. Propagation: forward in time under constant velocity
  C. Confidence decay: linear-with-age, clamped at zero
  D. Hysteresis: rules (a), (b), (c) of proposal §4.1.1 step 5
  E. TTC + action: ladder selection by ttc/confidence
  F. Phantom-brake suppression
  G. Local sensor injection
  H. Diagnostics

Run from repo root:
    pytest tests/test_cav.py -v
"""
from __future__ import annotations

import pytest

from v2xsim.cav import (
    Action,
    CAVCore,
    CAVDecision,
    LocalDetection,
    Track,
    DEFAULT_TTC_LADDER,
)
from v2xsim.cpm import CPM, CPMObject


# === Helpers ==============================================================

def _cpm(objects: list[CPMObject], station_id: int = 1) -> CPM:
    """Build a CPM with the given objects. Empty header — only objects matter."""
    return CPM(
        station_id=station_id,
        generation_delta_time_ms=0,
        objects=objects,
    )


def _obj(
    *,
    cls: str = "passengerCar",
    x: float = 0.0, y: float = 0.0,
    vx: float = 0.0, vy: float = 0.0,
    conf: float = 0.9,
    oid: int = 1,
) -> CPMObject:
    """Build a CPMObject with named, defaulted fields."""
    return CPMObject(
        object_id=oid, object_class=cls,
        x_m=x, y_m=y, vx_ms=vx, vy_ms=vy, confidence=conf,
    )


def _core(**overrides) -> CAVCore:
    """Build a CAVCore with the test default RSU 'A' at the origin already
    registered. Override defaults via kwargs."""
    c = CAVCore(cav_id="cav_test", **overrides)
    c.register_rsu("A", (0.0, 0.0))
    return c


# === A. Track lifecycle ===================================================

def test_first_cpm_creates_new_track():
    c = _core()
    c.ingest_cpm(_cpm([_obj(x=10.0, y=0.0)]), "A", 0.0, 0.0)
    tracks = c.get_tracks()
    assert len(tracks) == 1
    assert tracks[0].object_class == "passengerCar"
    assert tracks[0].x_m == pytest.approx(10.0)
    assert tracks[0].rsu_observation_count == 1


def test_second_cpm_associates_to_existing_track():
    c = _core()
    c.ingest_cpm(_cpm([_obj(x=10.0, y=0.0)]), "A", 0.0, 0.0)
    c.ingest_cpm(_cpm([_obj(x=10.5, y=0.0)]), "A", 100.0, 100.0)
    tracks = c.get_tracks()
    # Only one track — the second CPM merged with the first.
    assert len(tracks) == 1
    assert tracks[0].rsu_observation_count == 2


def test_track_pruned_after_ttl():
    c = _core(track_ttl_ms=1000.0)
    c.ingest_cpm(_cpm([_obj(x=10.0, y=0.0)]), "A", 0.0, 0.0)
    # update() at t > TTL after last_seen prunes the track.
    decision = c.update(ego_x_m=0, ego_y_m=0, ego_vx_ms=0, ego_vy_ms=0,
                        sim_time_ms=1500.0)
    assert decision.confirmed_tracks == ()
    assert decision.unconfirmed_tracks == ()
    assert c.get_tracks() == []


def test_unknown_rsu_silently_drops_cpm():
    c = _core()  # only RSU 'A' registered
    c.ingest_cpm(_cpm([_obj(x=10.0, y=0.0)]), "B_unknown", 0.0, 0.0)
    assert c.get_tracks() == []


# === B. Propagation ========================================================

def test_zero_delta_no_propagation():
    """send_t == sim_time → object stays at its CPM-reported position."""
    c = _core()
    c.ingest_cpm(_cpm([_obj(x=10.0, y=0.0, vx=5.0)]), "A", 100.0, 100.0)
    t = c.get_tracks()[0]
    assert t.x_m == pytest.approx(10.0)


def test_moving_object_propagates_forward_with_delta():
    """Δt = 200 ms, vx = 5 m/s → x advances by 1.0 m."""
    c = _core()
    c.ingest_cpm(_cpm([_obj(x=10.0, y=0.0, vx=5.0)]), "A",
                 cpm_send_sim_time_ms=0.0, sim_time_ms=200.0)
    t = c.get_tracks()[0]
    assert t.x_m == pytest.approx(11.0)


def test_negative_delta_clamped_to_zero():
    """Clock skew (send_t > now) → propagation clamped to 0 (no time travel)."""
    c = _core()
    c.ingest_cpm(_cpm([_obj(x=10.0, y=0.0, vx=5.0)]), "A",
                 cpm_send_sim_time_ms=200.0, sim_time_ms=100.0)
    t = c.get_tracks()[0]
    # Δt clamped to 0, but confidence decay also uses dt (signed), need to check.
    # Confidence-decay path uses delta_t_ms = sim - send = -100 → max(0, 1 - (-100)/TTL)
    #   = max(0, 1 + 100/TTL) = max(0, 1.1) = 1.1 → cap at 1.0 implicit (conf*1.1)
    # → confidence stays at 0.9 (no over-amplification because conf in [0,1] from caller).
    # Position propagation gates on positive delta_t_s only.
    assert t.x_m == pytest.approx(10.0)


# === C. Confidence decay ==================================================

def test_confidence_at_creation_equals_cpm_value():
    c = _core(track_ttl_ms=1000.0)
    c.ingest_cpm(_cpm([_obj(x=10.0, y=0.0, conf=0.8)]), "A", 0.0, 0.0)
    t = c.get_tracks()[0]
    # No age yet → confidence == base.
    assert t.confidence == pytest.approx(0.8)


def test_confidence_decays_linearly_with_age():
    """After 500 ms with TTL=1000 ms, confidence should be half its base."""
    c = _core(track_ttl_ms=1000.0)
    c.ingest_cpm(_cpm([_obj(x=10.0, y=0.0, conf=0.8)]), "A", 0.0, 0.0)
    # Force update at t=500 ms (track not yet pruned: 500 < TTL).
    d = c.update(0, 0, 0, 0, sim_time_ms=500.0)
    # Track present in either confirmed or unconfirmed; find it.
    all_tracks = list(d.confirmed_tracks) + list(d.unconfirmed_tracks)
    assert len(all_tracks) == 1
    assert all_tracks[0].confidence == pytest.approx(0.8 * 0.5)


def test_confidence_zero_immediately_after_ttl():
    """At t = TTL the linear decay gives 0; pruning then removes the track."""
    c = _core(track_ttl_ms=1000.0)
    c.ingest_cpm(_cpm([_obj(x=10.0, y=0.0, conf=0.8)]), "A", 0.0, 0.0)
    d = c.update(0, 0, 0, 0, sim_time_ms=1000.0)
    # At t=1000 (== TTL), pruning hasn't fired yet (uses > strict).
    # But confidence has decayed to 0.
    all_tracks = list(d.confirmed_tracks) + list(d.unconfirmed_tracks)
    if all_tracks:
        assert all_tracks[0].confidence == pytest.approx(0.0)


# === D. Hysteresis ========================================================

def test_single_cpm_not_confirmed_by_default():
    c = _core()
    c.ingest_cpm(_cpm([_obj(x=10.0, y=0.0)]), "A", 0.0, 0.0)
    t = c.get_tracks()[0]
    assert t.is_confirmed is False


def test_two_cpms_same_rsu_confirm_track():
    """Rule (b): ≥ 2 CPMs from the same RSU → confirmed."""
    c = _core()
    c.ingest_cpm(_cpm([_obj(x=10.0, y=0.0)]), "A", 0.0, 0.0)
    c.ingest_cpm(_cpm([_obj(x=10.5, y=0.0)]), "A", 100.0, 100.0)
    t = c.get_tracks()[0]
    assert t.is_confirmed is True


def test_two_distinct_rsus_within_window_confirm_track():
    """Rule (c): ≥ 2 distinct RSUs within hysteresis window → confirmed."""
    c = _core(hysteresis_window_ms=500.0)
    c.register_rsu("B", (100.0, 0.0))  # RSU B at (100, 0)
    c.ingest_cpm(_cpm([_obj(x=10.0, y=0.0)]), "A", 0.0, 0.0)
    # Same world point (10, 0) is "x = -90" relative to RSU B at (100, 0).
    c.ingest_cpm(_cpm([_obj(x=-90.0, y=0.0)]), "B", 100.0, 100.0)
    t = c.get_tracks()[0]
    assert t.is_confirmed is True
    assert t.distinct_rsus_in_window == 2


def test_two_distinct_rsus_outside_window_not_confirmed():
    """If the window has passed between the two RSU reports, rule (c) fails."""
    c = _core(hysteresis_window_ms=500.0, track_ttl_ms=10_000.0)  # extend TTL
    c.register_rsu("B", (100.0, 0.0))
    c.ingest_cpm(_cpm([_obj(x=10.0, y=0.0)]), "A", 0.0, 0.0)
    # 1000 ms later — outside the 500 ms hysteresis window.
    c.ingest_cpm(_cpm([_obj(x=-90.0, y=0.0)]), "B", 1000.0, 1000.0)
    # Force a fresh decision at the same time as the latest observation
    # so the snapshot uses the right "now" for the window check.
    d = c.update(0, 0, 0, 0, sim_time_ms=1000.0)
    tracks = list(d.confirmed_tracks) + list(d.unconfirmed_tracks)
    assert len(tracks) == 1
    assert tracks[0].distinct_rsus_in_window == 1   # only RSU B is in window now
    # ...but the track has rsu_observation_count = 2.
    # Rule (b) needs ≥ 2 from same RSU — we have 1 each. Should NOT be confirmed.
    assert tracks[0].is_confirmed is False


def test_local_detection_immediately_confirms():
    """Rule (a): local sensor confirms regardless of CPM history."""
    c = _core()
    c.ingest_local_detections(
        [LocalDetection(object_class="pedestrian", x_m=5.0, y_m=2.0)],
        sim_time_ms=0.0,
    )
    t = c.get_tracks()[0]
    assert t.is_confirmed is True
    assert t.confirmed_by_local is True


# === E. TTC and action ladder =============================================

def test_no_threat_when_object_far_away():
    """Object 100 m away, ego stationary → no TTC, no action."""
    c = _core()
    c.ingest_cpm(_cpm([_obj(x=100.0, y=0.0)]), "A", 0.0, 0.0)
    c.ingest_cpm(_cpm([_obj(x=100.0, y=0.0)]), "A", 100.0, 100.0)  # confirm
    d = c.update(0, 0, 0, 0, sim_time_ms=100.0)
    assert d.action == Action.NONE


def test_imminent_collision_high_conf_triggers_hard_brake():
    """Stationary obstacle 5 m ahead, ego moving +x at 10 m/s, conf=0.9.
    TTC = 5/10 = 0.5 s < 1.0 s → HARD_BRAKE if conf ≥ 0.8."""
    c = _core()
    # Two CPMs for hysteresis confirmation.
    c.ingest_cpm(_cpm([_obj(x=5.0, y=0.0, conf=0.9)]), "A", 0.0, 0.0)
    c.ingest_cpm(_cpm([_obj(x=5.0, y=0.0, conf=0.9)]), "A", 50.0, 50.0)
    d = c.update(ego_x_m=0, ego_y_m=0, ego_vx_ms=10.0, ego_vy_ms=0,
                 sim_time_ms=50.0)
    assert d.action == Action.HARD_BRAKE
    assert d.ttc_s is not None
    assert d.ttc_s <= 1.0


def test_mid_ttc_medium_conf_triggers_soft_brake():
    """Obstacle 20 m ahead, ego 10 m/s → TTC = 2.0 s. With conf 0.7 → SOFT_BRAKE."""
    c = _core()
    c.ingest_cpm(_cpm([_obj(x=20.0, y=0.0, conf=0.7)]), "A", 0.0, 0.0)
    c.ingest_cpm(_cpm([_obj(x=20.0, y=0.0, conf=0.7)]), "A", 50.0, 50.0)
    d = c.update(0, 0, 10.0, 0, sim_time_ms=50.0)
    assert d.action == Action.SOFT_BRAKE


def test_far_ttc_low_conf_triggers_decelerate():
    """Obstacle 35 m ahead, ego 10 m/s → TTC = 3.5 s. With conf 0.5 → DECELERATE."""
    c = _core()
    c.ingest_cpm(_cpm([_obj(x=35.0, y=0.0, conf=0.5)]), "A", 0.0, 0.0)
    c.ingest_cpm(_cpm([_obj(x=35.0, y=0.0, conf=0.5)]), "A", 50.0, 50.0)
    d = c.update(0, 0, 10.0, 0, sim_time_ms=50.0)
    assert d.action == Action.DECELERATE


def test_low_confidence_gate_blocks_action_even_with_low_ttc():
    """Imminent collision but conf=0.3 < all min_confidence gates → no action."""
    c = _core()
    c.ingest_cpm(_cpm([_obj(x=5.0, y=0.0, conf=0.3)]), "A", 0.0, 0.0)
    c.ingest_cpm(_cpm([_obj(x=5.0, y=0.0, conf=0.3)]), "A", 50.0, 50.0)
    d = c.update(0, 0, 10.0, 0, sim_time_ms=50.0)
    assert d.action == Action.NONE


# === F. Phantom-brake suppression =========================================

def test_unconfirmed_close_track_does_not_trigger_brake():
    """Single CPM, high conf, imminent collision — unconfirmed, suppressed."""
    c = _core()
    c.ingest_cpm(_cpm([_obj(x=5.0, y=0.0, conf=0.9)]), "A", 0.0, 0.0)
    d = c.update(0, 0, 10.0, 0, sim_time_ms=0.0)
    assert d.action == Action.NONE
    assert d.phantom_brake_suppressed is True


def test_confirmed_close_track_does_trigger_brake():
    """Two-CPM confirmation → brake fires, no phantom suppression flag."""
    c = _core()
    c.ingest_cpm(_cpm([_obj(x=5.0, y=0.0, conf=0.9)]), "A", 0.0, 0.0)
    c.ingest_cpm(_cpm([_obj(x=5.0, y=0.0, conf=0.9)]), "A", 50.0, 50.0)
    d = c.update(0, 0, 10.0, 0, sim_time_ms=50.0)
    assert d.action == Action.HARD_BRAKE
    assert d.phantom_brake_suppressed is False


# === G. Local sensor injection ============================================

def test_local_detection_creates_new_confirmed_track():
    c = _core()
    c.ingest_local_detections(
        [LocalDetection(object_class="pedestrian", x_m=5.0, y_m=2.0, confidence=0.9)],
        sim_time_ms=0.0,
    )
    tracks = c.get_tracks()
    assert len(tracks) == 1
    assert tracks[0].is_confirmed is True
    assert tracks[0].confirmed_by_local is True


def test_local_detection_confirms_existing_unconfirmed_cpm_track():
    """A previously-unconfirmed CPM track becomes confirmed after the CAV's
    own sensor sees it — rule (a) overrides hysteresis."""
    c = _core(association_gate_m=5.0)
    c.ingest_cpm(_cpm([_obj(cls="pedestrian", x=5.0, y=2.0)]), "A", 0.0, 0.0)
    pre = c.get_tracks()[0]
    assert pre.is_confirmed is False

    c.ingest_local_detections(
        [LocalDetection(object_class="pedestrian", x_m=5.0, y_m=2.0)],
        sim_time_ms=50.0,
    )
    post = c.get_tracks()[0]
    assert post.is_confirmed is True
    assert post.confirmed_by_local is True


# === H. Diagnostics =======================================================

def test_get_tracks_returns_sorted_immutable_snapshot():
    c = _core()
    c.ingest_cpm(_cpm([
        _obj(oid=1, x=10.0, y=0.0, cls="passengerCar"),
        _obj(oid=2, x=20.0, y=0.0, cls="pedestrian"),
    ]), "A", 0.0, 0.0)
    tracks = c.get_tracks()
    assert len(tracks) == 2
    assert [t.track_id for t in tracks] == sorted(t.track_id for t in tracks)
    # Frozen dataclass — can't mutate.
    with pytest.raises(Exception):  # FrozenInstanceError
        tracks[0].x_m = 999.0
