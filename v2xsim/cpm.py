"""ETSI CPM Release 2 encoder/decoder (Sprint 3 module 1).

Spec: ETSI TS 103 324 v2.1.1 (CPM) + ETSI TS 102 894-2 V2.2.1 (CDD).
Codec: ASN.1 UPER (canonical transport encoding for ETSI ITS messages).

This module provides:
  - CPM, CPMObject dataclasses (ergonomic Python API)
  - encode_cpm(cpm) -> bytes, decode_cpm(data) -> CPM
  - yolo_class_to_etsi(name) -> ETSI class string
  - quantize_confidence(), dequantize_confidence()
  - inspect_spec(), inspect_type() — diagnostics for spec exploration

Design notes (Sprint 3 §5 decisions from SPRINT3_HANDOFF.md):
  - YOLO 4-class → ETSI lossy mapping (no heavy-vehicle distinction yet).
  - Single VRU only; no pedestrian/cyclist cluster encoding yet.
  - Confidence: rounded quantization (not floor) to avoid downward bias.

Field-name caveat. ETSI Release 2 ASN.1 module names shift between drafts;
the dict produced by `_build_pdu_dict` is grouped per container so any
field-name fix is localized. If `encode_cpm()` raises, the asn1tools error
message names the offending field — fix here, re-run.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Optional

import asn1tools


# === Spec file locations ===================================================

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
_SPEC_ROOT = os.path.join(_REPO_ROOT, "specs", "cpm")

CPM_ASN_FILES = (
    os.path.join(_SPEC_ROOT, "cdd_ts102894_2", "ETSI-ITS-CDD.asn"),
    os.path.join(_SPEC_ROOT, "cpm_ts103324", "asn", "CPM-PDU-Descriptions.asn"),
    os.path.join(_SPEC_ROOT, "cpm_ts103324", "asn",
                 "CPM-OriginatingStationContainers.asn"),
    os.path.join(_SPEC_ROOT, "cpm_ts103324", "asn",
                 "CPM-PerceivedObjectContainer.asn"),
    os.path.join(_SPEC_ROOT, "cpm_ts103324", "asn",
                 "CPM-PerceptionRegionContainer.asn"),
    os.path.join(_SPEC_ROOT, "cpm_ts103324", "asn",
                 "CPM-SensorInformationContainer.asn"),
)

_CODEC = "uper"
_PDU_TYPE = "CollectivePerceptionMessage"

# CPM Release 2 wraps each container in WrappedCpmContainer:
#   { containerId: CpmContainerId, containerData: OCTET STRING }
# where containerData carries a separately-UPER-encoded instance of the
# specific container type — containerId is the discriminator. asn1tools
# does not transparently handle this open-type pattern, so we encode/decode
# the inner payload by the concrete ETSI type name selected from this map.
_CONTAINER_TYPES = {
    1: "OriginatingVehicleContainer",
    2: "OriginatingRsuContainer",
    3: "SensorInformationContainer",
    4: "PerceptionRegionContainer",
    5: "PerceivedObjectContainer",
}

# ETSI TS 103 324 v2.1.1 header values.
_CPM_PROTOCOL_VERSION = 2   # Release 2 ITS PDU header
_CPM_MESSAGE_ID = 14        # CPM in the ETSI message-id registry (Release 2)

# CPM_MTU per proposal §4.2 / TS 103 324 §6.1.x — ~1100 bytes payload cap.
CPM_MTU_BYTES = 1100


# === ASN.1 compiler (lazy + cached) ========================================

@lru_cache(maxsize=1)
def _compiler():
    """Compile the CPM + CDD ASN.1 modules on first use; cached afterwards."""
    missing = [f for f in CPM_ASN_FILES if not os.path.isfile(f)]
    if missing:
        raise FileNotFoundError(
            "ETSI ASN.1 spec files missing. "
            "Run `python scripts\\20_download_etsi_specs.py` first.\n  Missing:\n  "
            + "\n  ".join(missing)
        )
    return asn1tools.compile_files(list(CPM_ASN_FILES), codec=_CODEC)


def inspect_spec() -> dict[str, list[str]]:
    """Return {module_name: [type_names...]}. Diagnostic for field-name lookup."""
    c = _compiler()
    return {mod: sorted(c.modules[mod].keys()) for mod in c.modules}


def inspect_type(type_name: str, module: Optional[str] = None) -> Any:
    """Return the asn1tools internal representation of a type.

    Mostly useful as `repr(inspect_type('PerceivedObject'))` to see the
    expected SEQUENCE field list when debugging encode failures.
    """
    c = _compiler()
    if module is not None:
        return c.modules[module][type_name]
    for mod_types in c.modules.values():
        if type_name in mod_types:
            return mod_types[type_name]
    raise KeyError(f"type {type_name!r} not found in any module")


def describe_type(type_name: str) -> str:
    """Pretty-print one type with per-member optional/default info.

    Walks the inner asn1tools Sequence and lists each member's name plus
    whether it is OPTIONAL or has a DEFAULT — essential for figuring out
    which fields you actually have to populate in encode dicts.
    """
    t = inspect_type(type_name)
    inner = getattr(t, "_type", t)
    lines = [f"{type_name}:"]
    members = getattr(inner, "root_members", None)
    optionals = getattr(inner, "optionals", []) or []
    opt_names = {getattr(m, "name", None) for m in optionals}
    if members is None:
        return f"{type_name}: (no root_members; type is {type(inner).__name__}) {inner!r}"
    for m in members:
        name = getattr(m, "name", "?")
        kind = type(m).__name__
        flag = ""
        if name in opt_names:
            if getattr(m, "default", None) is not None:
                flag = f"  DEFAULT={m.default}"
            else:
                flag = "  OPTIONAL"
        lines.append(f"  {name:32s} {kind}{flag}")
    return "\n".join(lines)


# === YOLO 4-class -> ETSI ObjectClass mapping =============================

# Lossy mapping per SPRINT3_HANDOFF.md §5 decision (A):
#   - YOLO "vehicle" collapses to ETSI passengerCar; heavy-vehicle distinction
#     is deferred until/if a 5-class detector retrain happens in Sprint 3.5.
#   - ETSI Release 2 calls bicycles "pedalCycle" inside TrafficParticipantType.
YOLO_TO_ETSI: dict[str, str] = {
    "vehicle":    "passengerCar",
    "motorcycle": "motorcycle",
    "bicycle":    "pedalCycle",
    "pedestrian": "pedestrian",
}

# YOLO 4-class → ObjectClass CHOICE mapping.
#
# ETSI Release 2 ObjectClass branches:
#   - vehicleSubClass  : TrafficParticipantType, but **constrained to (0..0)**
#     in the context of ObjectClass — i.e. fixed at 0 ("unspecified vehicle").
#     Finer vehicle subtyping (passengerCar / heavyVehicle / ...) is not yet
#     defined in CDD V2.2.1 at this position; presumably reserved for a future
#     release. Our YOLO 4-class scheme already collapses all 4-wheelers to one
#     bucket, so this is information-preserving for us.
#   - vruSubClass      : VruProfileAndSubprofile (nested CHOICE), no integer
#     range issue; sub-profile values (VruSubProfile*) are Integer with 0
#     meaning "unavailable" — the safe sentinel.
#   - otherSubClass    : Integer, also send 0 for the "unknown" fallback.

# Map YOLO-derived ETSI class strings to nested VRU sub-profile names.
_VRU_BRANCH = {
    "pedestrian": "pedestrian",
    "motorcycle": "motorcyclist",
    "pedalCycle": "bicyclistAndLightVruVehicle",
}
_VRU_BRANCH_INVERSE = {v: k for k, v in _VRU_BRANCH.items()}


def _build_object_class(etsi_class: str) -> tuple:
    """Build the ObjectClass CHOICE value for one ETSI class string."""
    if etsi_class == "passengerCar":
        # vehicleSubClass is fixed at 0 in CDD V2.2.1 (see note above).
        return ("vehicleSubClass", 0)
    if etsi_class in _VRU_BRANCH:
        return ("vruSubClass", (_VRU_BRANCH[etsi_class], 0))
    return ("otherSubClass", 0)


def _parse_object_class(choice: tuple) -> str:
    """Map a decoded ObjectClass CHOICE back to an ETSI class string."""
    kind, _val = choice
    if kind == "vehicleSubClass":
        # Only value 0 is valid; YOLO 4-class collapses to "passengerCar".
        return "passengerCar"
    if kind == "vruSubClass":
        sub_kind, _ = _val
        return _VRU_BRANCH_INVERSE.get(sub_kind, "unknown")
    return "unknown"


def yolo_class_to_etsi(name: str) -> str:
    """Map a YOLO 4-class name to an ETSI class string. Raises on unknown."""
    try:
        return YOLO_TO_ETSI[name]
    except KeyError:
        raise ValueError(
            f"unknown YOLO class {name!r}; valid: {sorted(YOLO_TO_ETSI)}"
        ) from None


# === Confidence quantization ===============================================

# ETSI ObjectConfidence in CDD V2.2.1 is INTEGER(0..101): 0 = unavailable,
# 1..101 = 0%..100% (linear). We always have a YOLO confidence in [0, 1],
# so we never emit 0 (unavailable) — every detection has *some* confidence.
_CONF_UNAVAIL = 0
_CONF_MIN = 1
_CONF_MAX = 101


def quantize_confidence(c: float) -> int:
    """Map float in [0, 1] to ETSI ObjectConfidence integer in [1, 101].

    Rounded (per Sprint 3 §5 decision C) — avoids the systematic downward
    bias that floor would introduce in the fusion module's confidence
    thresholds (proposal §4.1.1).
    """
    if c < 0.0 or c > 1.0:
        raise ValueError(f"confidence {c} out of [0.0, 1.0]")
    return max(_CONF_MIN, min(_CONF_MAX, round(c * 100) + 1))


def dequantize_confidence(q: int) -> float:
    """Inverse of quantize_confidence. q=0 (unavailable) → 0.0."""
    if q == _CONF_UNAVAIL:
        return 0.0
    return max(0.0, min(1.0, (q - 1) / 100.0))


# === Dataclasses ===========================================================

@dataclass
class CPMObject:
    """One perceived object as it appears in a CPM PerceivedObjectContainer.

    Coordinates are in the ITS-S local cartesian frame (meters, east-north),
    relative to the CPM's reference position. The encoder converts to ETSI's
    centimeter-scaled CartesianCoordinate during ASN.1 build.
    """
    object_id: int
    object_class: str            # ETSI class string (see YOLO_TO_ETSI values)
    x_m: float
    y_m: float
    vx_ms: float = 0.0
    vy_ms: float = 0.0
    confidence: float = 1.0      # [0, 1]; will be quantized on encode


@dataclass
class CPM:
    """One Collective Perception Message.

    `generation_delta_time_ms` is ms since the start of the current UTC second
    (per ETSI's TimestampIts / referenceTime convention; 0..65535).
    `reference_lat_e7` / `reference_lon_e7` are WGS84 in tenths of microdegree
    (ETSI Latitude/Longitude integer type).
    """
    station_id: int
    generation_delta_time_ms: int
    reference_lat_e7: int = 0
    reference_lon_e7: int = 0
    objects: list[CPMObject] = field(default_factory=list)
    payload_size_bytes: int = 0   # filled by encode_cpm()


# === ASN.1 dict construction (per container) ===============================
#
# Field names below are this module's main risk surface. ETSI Release 2
# names tend to be camelCase mirroring the ASN.1 identifiers. Each container
# is its own function so a fix is one place to look.

def _build_header(cpm: CPM) -> dict:
    return {
        "protocolVersion": _CPM_PROTOCOL_VERSION,
        "messageId":       _CPM_MESSAGE_ID,
        "stationId":       cpm.station_id,
    }


def _build_reference_position(cpm: CPM) -> dict:
    # CDD V2.2.1 ReferencePositionWithConfidence — best-effort field names.
    return {
        "latitude":  cpm.reference_lat_e7,
        "longitude": cpm.reference_lon_e7,
        "positionConfidenceEllipse": {
            "semiMajorConfidence":   4095,   # "unavailable" sentinel
            "semiMinorConfidence":   4095,
            "semiMajorOrientation":  3601,   # "unavailable" sentinel
        },
        "altitude": {
            "altitudeValue":      800000,    # "unavailable" sentinel
            "altitudeConfidence": "unavailable",
        },
    }


def _build_management_container(cpm: CPM) -> dict:
    return {
        "referenceTime":     cpm.generation_delta_time_ms,
        "referencePosition": _build_reference_position(cpm),
    }


def _build_perceived_object(obj: CPMObject) -> dict:
    # Sprint 3 Module 1.1: position + velocity + classification.
    # Optional fields (acceleration, angles, dimensions, mapPosition, etc.)
    # remain omitted — they're not needed by the proposal's fusion module
    # (§4.1.1) which uses position, velocity, class, confidence.
    return {
        "objectId":             obj.object_id,
        "measurementDeltaTime": 0,
        "position": {
            "xCoordinate": {"value": int(round(obj.x_m * 100)), "confidence": 4095},
            "yCoordinate": {"value": int(round(obj.y_m * 100)), "confidence": 4095},
            "zCoordinate": {"value": 0,                          "confidence": 4095},
        },
        "velocity": ("cartesianVelocity", {
            "xVelocity": {"value": int(round(obj.vx_ms * 100)), "confidence": 127},
            "yVelocity": {"value": int(round(obj.vy_ms * 100)), "confidence": 127},
            # zVelocity OPTIONAL — omitted (we don't model vertical motion).
        }),
        "classification": [{
            "objectClass": _build_object_class(obj.object_class),
            "confidence":  quantize_confidence(obj.confidence),
        }],
    }


def _build_perceived_object_container(cpm: CPM) -> dict:
    return {
        "numberOfPerceivedObjects": len(cpm.objects),
        "perceivedObjects": [_build_perceived_object(o) for o in cpm.objects],
    }


def _encode_inner_container(container_id: int, payload: dict) -> bytes:
    """Encode the per-container payload as its specific ETSI type → bytes.
    These bytes go into WrappedCpmContainer.containerData (OCTET STRING).
    """
    type_name = _CONTAINER_TYPES.get(container_id)
    if type_name is None:
        raise ValueError(f"unknown CPM containerId {container_id}")
    try:
        return _compiler().encode(type_name, payload)
    except Exception as e:
        raise RuntimeError(
            f"Could not encode inner container (containerId={container_id}, "
            f"type={type_name!r}). Run `python -m v2xsim.cpm --type {type_name}` "
            f"to inspect the expected field shape. (asn1tools: {e})"
        ) from e


def _decode_inner_container(container_id: int, data: bytes) -> dict:
    type_name = _CONTAINER_TYPES.get(container_id)
    if type_name is None:
        raise ValueError(f"unknown CPM containerId {container_id}")
    return _compiler().decode(type_name, data)


def _build_pdu_dict(cpm: CPM) -> dict:
    containers: list[dict] = []
    if cpm.objects:
        inner = _encode_inner_container(
            5, _build_perceived_object_container(cpm)
        )
        containers.append({
            "containerId":   5,
            "containerData": inner,
        })
    if not containers:
        # CPM SIZE(1..8): at least one container required.
        inner = _encode_inner_container(5, {
            "numberOfPerceivedObjects": 0,
            "perceivedObjects": [],
        })
        containers.append({
            "containerId":   5,
            "containerData": inner,
        })
    return {
        "header":  _build_header(cpm),
        "payload": {
            "managementContainer": _build_management_container(cpm),
            "cpmContainers":       containers,
        },
    }


# === Inverse: ASN.1 dict -> dataclass =====================================

def _parse_perceived_object(d: dict) -> CPMObject:
    pos = d["position"]
    # velocity / classification not transmitted in Sprint 3 Module 1.0 — defaults
    # below mean a decoded CPM yields obj with zero velocity and "unknown" class.
    vel_choice = d.get("velocity")
    if vel_choice is not None and vel_choice[0] == "cartesianVelocity":
        vx = vel_choice[1]["xVelocity"]["value"] / 100.0
        vy = vel_choice[1]["yVelocity"]["value"] / 100.0
    else:
        vx = vy = 0.0

    cls_list = d.get("classification") or []
    if cls_list:
        etsi_class = _parse_object_class(cls_list[0]["objectClass"])
        conf = dequantize_confidence(cls_list[0].get("confidence", 0))
    else:
        etsi_class = "unknown"
        conf = 1.0

    return CPMObject(
        object_id=d.get("objectId", 0),    # OPTIONAL per ETSI Release 2
        object_class=etsi_class,
        x_m=pos["xCoordinate"]["value"] / 100.0,
        y_m=pos["yCoordinate"]["value"] / 100.0,
        vx_ms=vx,
        vy_ms=vy,
        confidence=conf,
    )


def _parse_pdu_dict(d: dict) -> CPM:
    hdr = d["header"]
    payload = d["payload"]
    mgmt = payload["managementContainer"]
    ref_pos = mgmt["referencePosition"]

    objects: list[CPMObject] = []
    for container in payload["cpmContainers"]:
        cid = container["containerId"]
        inner = _decode_inner_container(cid, container["containerData"])
        if cid == 5:  # PerceivedObjectContainer
            for po in inner["perceivedObjects"]:
                objects.append(_parse_perceived_object(po))

    return CPM(
        station_id=hdr["stationId"],
        generation_delta_time_ms=mgmt["referenceTime"],
        reference_lat_e7=ref_pos["latitude"],
        reference_lon_e7=ref_pos["longitude"],
        objects=objects,
    )


# === Public API ============================================================

def encode_cpm(cpm: CPM) -> bytes:
    """Serialize a CPM to ASN.1 UPER bytes; also fills cpm.payload_size_bytes."""
    d = _build_pdu_dict(cpm)
    data = _compiler().encode(_PDU_TYPE, d)
    cpm.payload_size_bytes = len(data)
    return data


@lru_cache(maxsize=1024)
def decode_cpm(data: bytes) -> CPM:
    """Parse ASN.1 UPER bytes back into a CPM dataclass."""
    d = _compiler().decode(_PDU_TYPE, data)
    cpm = _parse_pdu_dict(d)
    cpm.payload_size_bytes = len(data)
    return cpm


# === CLI diagnostic ========================================================

def _cli() -> int:
    import argparse
    p = argparse.ArgumentParser(description="CPM spec / encoder diagnostics")
    p.add_argument("--inspect", action="store_true",
                   help="list modules and top-level types in the compiled spec")
    p.add_argument("--type", default=None,
                   help="dump one ASN.1 type's structure (e.g. PerceivedObject)")
    p.add_argument("--detail", default=None,
                   help="dump one type's members with OPTIONAL/DEFAULT info")
    args = p.parse_args()

    if args.inspect:
        for mod, types in inspect_spec().items():
            print(f"[{mod}]")
            for t in types:
                print(f"  {t}")
    if args.type is not None:
        print(repr(inspect_type(args.type)))
    if args.detail is not None:
        print(describe_type(args.detail))
    if not (args.inspect or args.type or args.detail):
        p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
