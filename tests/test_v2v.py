"""Tests for v2xsim.v2v — Sprint 5 V2V message layer.

CARLA-free. Validates the encode/decode round-trip, the magic-header
discriminator, intent-flag preservation, and relative-object fidelity.

Run from repo root:
    pytest tests/test_v2v.py -v
"""
from __future__ import annotations

import pytest

from v2xsim.cpm import CPMObject, encode_cpm, CPM
from v2xsim.v2v import (
    V2V_MAGIC,
    V2VMessage,
    decode_v2v,
    encode_v2v,
    is_v2v,
)


def _sample(objects=(), hard_brake=False):
    return V2VMessage(
        sender_id="cav_42",
        x_m=120.5, y_m=-30.25,
        vx_ms=8.0, vy_ms=-1.5,
        gen_time_ms=12345,
        hard_brake=hard_brake,
        objects=tuple(objects),
    )


# === magic / discrimination ===============================================

def test_encoded_payload_starts_with_magic():
    assert encode_v2v(_sample()).startswith(V2V_MAGIC)


def test_is_v2v_true_for_v2v_payload():
    assert is_v2v(encode_v2v(_sample())) is True


def test_is_v2v_false_for_etsi_cpm_payload():
    """A real ETSI CPM must not be mistaken for a V2V message."""
    cpm = CPM(station_id=1, generation_delta_time_ms=0,
              objects=[CPMObject(object_id=1, object_class="passengerCar",
                                 x_m=1.0, y_m=2.0)])
    cpm_bytes = encode_cpm(cpm)
    assert is_v2v(cpm_bytes) is False


def test_is_v2v_false_for_short_bytes():
    assert is_v2v(b"") is False
    assert is_v2v(b"V2") is False


# === round-trip ===========================================================

def test_roundtrip_no_objects_preserves_pose_and_time():
    msg = _sample()
    out = decode_v2v(encode_v2v(msg))
    assert out.sender_id == "cav_42"
    assert out.x_m == pytest.approx(120.5)
    assert out.y_m == pytest.approx(-30.25)
    assert out.vx_ms == pytest.approx(8.0)
    assert out.vy_ms == pytest.approx(-1.5)
    assert out.gen_time_ms == 12345
    assert out.hard_brake is False
    assert out.objects == ()


def test_roundtrip_hard_brake_flag():
    out = decode_v2v(encode_v2v(_sample(hard_brake=True)))
    assert out.hard_brake is True


def test_roundtrip_objects_preserve_all_fields():
    objs = [
        CPMObject(object_id=1, object_class="passengerCar",
                  x_m=5.0, y_m=-2.0, vx_ms=3.0, vy_ms=0.5, confidence=0.9),
        CPMObject(object_id=2, object_class="pedestrian",
                  x_m=-1.5, y_m=4.0, vx_ms=0.0, vy_ms=1.0, confidence=0.6),
    ]
    out = decode_v2v(encode_v2v(_sample(objects=objs)))
    assert len(out.objects) == 2
    a = out.objects[0]
    assert a.object_id == 1
    assert a.object_class == "passengerCar"
    assert a.x_m == pytest.approx(5.0)
    assert a.y_m == pytest.approx(-2.0)
    assert a.vx_ms == pytest.approx(3.0)
    assert a.vy_ms == pytest.approx(0.5)
    assert a.confidence == pytest.approx(0.9)
    assert out.objects[1].object_class == "pedestrian"


# === error handling =======================================================

def test_decode_rejects_non_v2v_payload():
    with pytest.raises(ValueError):
        decode_v2v(b"not a v2v message")


# === payload size sanity ==================================================

def test_payload_size_grows_with_object_count():
    """Byte length feeds the broker latency/CBR model, so it must scale
    with content (an empty message is smaller than a populated one)."""
    empty = len(encode_v2v(_sample()))
    full = len(encode_v2v(_sample(objects=[
        CPMObject(object_id=i, object_class="passengerCar", x_m=float(i), y_m=0.0)
        for i in range(10)
    ])))
    assert full > empty
