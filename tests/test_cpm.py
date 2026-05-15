"""Tests for v2xsim.cpm — Sprint 3 module 1.

Two tiers:
  1. Spec-independent tests (paths, mapping, quantization) — always green if
     the Python logic is sane.
  2. ASN.1 round-trip tests — exercise encode/decode against the actual
     compiled ETSI spec. These are the canaries for field-name mismatches in
     _build_pdu_dict / _parse_pdu_dict. asn1tools' error messages name the
     offending field.

Run from repo root:
    pytest tests/test_cpm.py -v
"""
from __future__ import annotations

import os

import pytest

from v2xsim import cpm as cpmmod
from v2xsim.cpm import (
    CPM,
    CPM_MTU_BYTES,
    CPMObject,
    YOLO_TO_ETSI,
    decode_cpm,
    dequantize_confidence,
    encode_cpm,
    inspect_spec,
    quantize_confidence,
    yolo_class_to_etsi,
)


# === Tier 1: spec-independent ==============================================

def test_spec_files_present():
    """All declared ASN.1 spec files exist on disk."""
    missing = [f for f in cpmmod.CPM_ASN_FILES if not os.path.isfile(f)]
    assert not missing, (
        f"missing spec files (run scripts\\20_download_etsi_specs.py): {missing}"
    )


def test_yolo_mapping_covers_all_four_classes():
    assert set(YOLO_TO_ETSI) == {"vehicle", "motorcycle", "bicycle", "pedestrian"}


def test_yolo_class_to_etsi_known():
    assert yolo_class_to_etsi("vehicle") == "passengerCar"
    assert yolo_class_to_etsi("pedestrian") == "pedestrian"


def test_yolo_class_to_etsi_unknown_raises():
    with pytest.raises(ValueError):
        yolo_class_to_etsi("airplane")


@pytest.mark.parametrize("c,expected_q", [
    (0.0, 1),
    (1.0, 101),
    (0.5, 51),
    (0.255, 27),    # round half-up: 0.255*100+1 = 26.5+1 → 27
    (0.66, 67),
])
def test_quantize_confidence_known_values(c, expected_q):
    assert quantize_confidence(c) == expected_q


def test_quantize_dequantize_roundtrip():
    """Quantization is rounded, so round-trip is exact only at the lattice."""
    for c in [0.0, 0.01, 0.5, 0.99, 1.0]:
        q = quantize_confidence(c)
        c2 = dequantize_confidence(q)
        assert abs(c - c2) <= 0.01 + 1e-9, f"round-trip drift {c}->{q}->{c2}"


def test_quantize_confidence_out_of_range_raises():
    with pytest.raises(ValueError):
        quantize_confidence(1.5)
    with pytest.raises(ValueError):
        quantize_confidence(-0.1)


def test_dequantize_unavailable():
    assert dequantize_confidence(0) == 0.0


# === Tier 2: ASN.1 round-trip ==============================================

def test_compiler_loads():
    """asn1tools compiles the CPM + CDD bundle without errors."""
    c = cpmmod._compiler()
    assert c is not None
    # At least one of the modules should expose CollectivePerceptionMessage.
    found = any(
        "CollectivePerceptionMessage" in types
        for types in inspect_spec().values()
    )
    assert found, "CollectivePerceptionMessage not found in compiled spec"


def _one_obj_cpm() -> CPM:
    return CPM(
        station_id=42,
        generation_delta_time_ms=1234,
        reference_lat_e7=414009810,    # Istanbul-ish: 41.4009810°N
        reference_lon_e7=290086170,    #              29.0086170°E
        objects=[
            CPMObject(
                object_id=7,
                object_class="passengerCar",
                x_m=12.34, y_m=-5.67,
                vx_ms=3.0, vy_ms=0.5,
                confidence=0.85,
            ),
        ],
    )


def _many_obj_cpm(n: int = 10) -> CPM:
    objs = []
    for i in range(n):
        objs.append(CPMObject(
            object_id=i,
            object_class="passengerCar" if i % 2 == 0 else "pedestrian",
            x_m=i * 2.5, y_m=-i * 1.2,
            vx_ms=0.8 * i, vy_ms=0.0,
            confidence=min(1.0, 0.5 + 0.03 * i),
        ))
    return CPM(
        station_id=99,
        generation_delta_time_ms=4321,
        reference_lat_e7=414009810,
        reference_lon_e7=290086170,
        objects=objs,
    )


def test_encode_one_object_returns_bytes():
    data = encode_cpm(_one_obj_cpm())
    assert isinstance(data, bytes)
    assert len(data) > 0


def test_encode_decode_roundtrip_one_object():
    src = _one_obj_cpm()
    data = encode_cpm(src)
    dst = decode_cpm(data)

    assert dst.station_id == src.station_id
    assert dst.generation_delta_time_ms == src.generation_delta_time_ms
    assert dst.reference_lat_e7 == src.reference_lat_e7
    assert dst.reference_lon_e7 == src.reference_lon_e7
    assert len(dst.objects) == 1

    a, b = src.objects[0], dst.objects[0]
    assert b.object_id == a.object_id
    assert b.object_class == a.object_class
    # Positions are cm-quantized; tolerate one cm of drift.
    assert abs(b.x_m - a.x_m) <= 0.011
    assert abs(b.y_m - a.y_m) <= 0.011
    # Velocities are cm/s-quantized.
    assert abs(b.vx_ms - a.vx_ms) <= 0.011
    assert abs(b.vy_ms - a.vy_ms) <= 0.011
    # Confidence quantized to 1% steps.
    assert abs(b.confidence - a.confidence) <= 0.011


def test_encode_decode_roundtrip_many_objects():
    src = _many_obj_cpm(10)
    data = encode_cpm(src)
    dst = decode_cpm(data)
    assert len(dst.objects) == 10
    assert dst.station_id == src.station_id


def test_payload_size_under_mtu_for_typical_load():
    """A CPM with ~15 objects (typical RSU scene) must fit under CPM_MTU.

    Proposal §4.2: payload cap ≈1100 bytes. If this fails we'll need the
    VRU-cluster encoding ahead of schedule.
    """
    src = _many_obj_cpm(15)
    data = encode_cpm(src)
    assert len(data) <= CPM_MTU_BYTES, (
        f"15-object CPM encoded to {len(data)} bytes, over MTU {CPM_MTU_BYTES}"
    )
    # Also assert payload_size_bytes is filled in.
    assert src.payload_size_bytes == len(data)


def test_decode_known_bytes_equals_encode_roundtrip():
    """encode -> decode -> encode should be byte-identical (canonical UPER)."""
    src = _one_obj_cpm()
    data1 = encode_cpm(src)
    mid = decode_cpm(data1)
    data2 = encode_cpm(mid)
    assert data1 == data2


@pytest.mark.parametrize("yolo_class,expected_etsi", [
    ("vehicle",    "passengerCar"),
    ("motorcycle", "motorcycle"),
    ("bicycle",    "pedalCycle"),
    ("pedestrian", "pedestrian"),
])
def test_class_roundtrip_through_wire(yolo_class, expected_etsi):
    """Full pipeline: YOLO label → ETSI string → CPM bytes → CPM → ETSI string.

    Verifies the ObjectClass CHOICE encoding (vehicleSubClass vs nested
    vruSubClass) round-trips for every YOLO class we transmit.
    """
    etsi = yolo_class_to_etsi(yolo_class)
    assert etsi == expected_etsi

    src = CPM(
        station_id=1,
        generation_delta_time_ms=0,
        objects=[CPMObject(
            object_id=1, object_class=etsi,
            x_m=1.0, y_m=2.0,
            vx_ms=0.5, vy_ms=0.0,
            confidence=0.7,
        )],
    )
    dst = decode_cpm(encode_cpm(src))
    assert dst.objects[0].object_class == etsi
