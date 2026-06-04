"""Vehicle-to-Vehicle (V2V) message layer (Sprint 5).

Sprint 3/4 built the RSU→CAV (V2I) cooperative-perception path on top of
ETSI CPM (ASN.1 UPER) with a *static* per-RSU reference position. Sprint 5
adds the V2V leg: CAVs broadcast to other CAVs. A V2V sender is **mobile**,
so unlike a fixed RSU its reference position must travel inside every
message. Rather than overload the ETSI CPM lat/lon `referencePosition`
fields (the whole simulator works in a local cartesian metre frame, not
WGS84), this module defines a small self-contained V2V message that carries
the sender's live pose in metres.

A single V2V message combines two ETSI concepts so the runner only needs
one broadcast per CAV per period:

  * **Cooperative perception** (CPM-like): the objects this CAV currently
    perceives with its own sensor, encoded relative to the sender's pose —
    the receiver translates them back to world frame using the pose carried
    in the same message.
  * **Cooperative awareness / hazard** (CAM/DENM-like): the sender's own
    pose + velocity, plus a `hard_brake` intent flag. A follower acts on a
    leader's declared hard brake before it could perceive the hazard itself.

Transport: the encoded bytes flow through the *same* `Broker` as RSU CPMs,
so V2V messages get identical PDR / latency / CBR channel modelling. The
payload is tagged with a 4-byte magic header so a receiver can tell a V2V
message from an ETSI CPM without trying both decoders blindly — see
`is_v2v()`.

CARLA-agnostic and asn1-light: encoding is compact JSON (debuggable, easy
to log). Fully unit-testable. `CPMObject` is reused from `cpm.py` so the
object model stays identical across the V2I and V2V paths.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache

from .cpm import CPMObject


# 4-byte tag that prefixes every V2V payload. Lets a receiver distinguish a
# V2V message from a raw ETSI CPM (which never starts with these bytes)
# before choosing a decoder.
V2V_MAGIC = b"V2V1"


@dataclass(frozen=True)
class V2VMessage:
    """One V2V broadcast from a single CAV.

    Coordinates are in the simulator's local cartesian metre frame.
    Perceived `objects` are encoded **relative to the sender's pose**
    (`x_m`, `y_m`), matching how an RSU encodes CPM objects relative to its
    reference position — so the receiver reconstructs world coordinates as
    `sender_pose + object_offset`.
    """
    sender_id: str
    x_m: float
    y_m: float
    vx_ms: float
    vy_ms: float
    gen_time_ms: int
    yaw_deg: float = 0.0
    hard_brake: bool = False
    objects: tuple[CPMObject, ...] = field(default_factory=tuple)


def is_v2v(payload: bytes) -> bool:
    """True if `payload` is a V2V message (vs. an ETSI CPM or other bytes)."""
    return payload[:len(V2V_MAGIC)] == V2V_MAGIC


def encode_v2v(msg: V2VMessage) -> bytes:
    """Serialise a V2VMessage to magic-prefixed JSON bytes.

    Object fields are written positionally to keep the payload compact —
    the byte length feeds the broker's latency / CBR model, so we keep it
    representative of a real CAM+CPM-sized message rather than verbose.
    """
    body = {
        "s": msg.sender_id,
        "x": msg.x_m,
        "y": msg.y_m,
        "vx": msg.vx_ms,
        "vy": msg.vy_ms,
        "yaw": msg.yaw_deg,
        "t": int(msg.gen_time_ms),
        "hb": 1 if msg.hard_brake else 0,
        # [object_id, class, x, y, vx, vy, confidence]
        "o": [
            [o.object_id, o.object_class, o.x_m, o.y_m, o.vx_ms, o.vy_ms, o.confidence]
            for o in msg.objects
        ],
    }
    return V2V_MAGIC + json.dumps(body, separators=(",", ":")).encode("utf-8")


@lru_cache(maxsize=1024)
def decode_v2v(data: bytes) -> V2VMessage:
    """Inverse of `encode_v2v`. Raises ValueError if the magic is missing."""
    if not is_v2v(data):
        raise ValueError("payload is not a V2V message (bad magic header)")
    body = json.loads(data[len(V2V_MAGIC):].decode("utf-8"))
    objects = tuple(
        CPMObject(
            object_id=int(o[0]),
            object_class=o[1],
            x_m=float(o[2]),
            y_m=float(o[3]),
            vx_ms=float(o[4]),
            vy_ms=float(o[5]),
            confidence=float(o[6]),
        )
        for o in body.get("o", [])
    )
    return V2VMessage(
        sender_id=body["s"],
        x_m=float(body["x"]),
        y_m=float(body["y"]),
        vx_ms=float(body["vx"]),
        vy_ms=float(body["vy"]),
        yaw_deg=float(body.get("yaw", 0.0)),
        gen_time_ms=int(body["t"]),
        hard_brake=bool(body.get("hb", 0)),
        objects=objects,
    )
