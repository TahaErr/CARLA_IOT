"""Tests for v2xsim.carla_cav — Sprint 4 module 4.

Two CARLA-free logic primitives are unit-tested here:
  - `carla_type_to_etsi`: blueprint type_id → ETSI class string
  - `actors_in_cone`: ground-truth-cone local-sensor synthesis

The `CarlaCAV` class itself is smoke-tested via the ablation runner
(Module 5) with real CARLA actors. This test file ensures the math
and string-matching are right before that.

Run from repo root:
    pytest tests/test_carla_cav.py -v
"""
from __future__ import annotations

import math
from types import SimpleNamespace

from v2xsim.carla_cav import (
    actors_in_cone,
    carla_type_to_etsi,
    local_dets_to_cpm_objects,
)
from v2xsim.cav import Action, LocalDetection
from v2xsim.v2v import V2VMessage, encode_v2v


# === Mock CARLA actor objects ============================================

class _MockLoc:
    def __init__(self, x: float, y: float, z: float = 0.0) -> None:
        self.x, self.y, self.z = x, y, z


class _MockActor:
    def __init__(
        self,
        actor_id: int,
        type_id: str,
        x: float, y: float,
        vx: float = 0.0, vy: float = 0.0,
    ) -> None:
        self.id = actor_id
        self.type_id = type_id
        self._loc = _MockLoc(x, y)
        self._vel = _MockLoc(vx, vy)

    def get_location(self) -> _MockLoc:
        return self._loc

    def get_velocity(self) -> _MockLoc:
        return self._vel


# === carla_type_to_etsi ==================================================

def test_passenger_car_blueprints_map_to_passengerCar():
    assert carla_type_to_etsi("vehicle.tesla.model3") == "passengerCar"
    assert carla_type_to_etsi("vehicle.audi.tt") == "passengerCar"
    assert carla_type_to_etsi("vehicle.ford.crown") == "passengerCar"


def test_motorcycle_blueprints_map_to_motorcycle():
    assert carla_type_to_etsi("vehicle.yamaha.yzf") == "motorcycle"
    assert carla_type_to_etsi("vehicle.kawasaki.ninja") == "motorcycle"
    assert carla_type_to_etsi("vehicle.harley-davidson.low_rider") == "motorcycle"
    assert carla_type_to_etsi("vehicle.vespa.zx125") == "motorcycle"


def test_bicycle_blueprints_map_to_pedalCycle():
    assert carla_type_to_etsi("vehicle.bh.crossbike") == "pedalCycle"
    assert carla_type_to_etsi("vehicle.diamondback.century") == "pedalCycle"
    assert carla_type_to_etsi("vehicle.gazelle.omafiets") == "pedalCycle"


def test_walker_blueprints_map_to_pedestrian():
    assert carla_type_to_etsi("walker.pedestrian.0001") == "pedestrian"
    assert carla_type_to_etsi("walker.pedestrian.0042") == "pedestrian"


def test_unknown_types_return_none():
    assert carla_type_to_etsi("sensor.camera.rgb") is None
    assert carla_type_to_etsi("traffic.traffic_light") is None
    assert carla_type_to_etsi("static.prop.streetbarrier") is None
    assert carla_type_to_etsi("") is None


# === actors_in_cone ======================================================

def test_actor_directly_ahead_is_included():
    """Ego at origin facing +X. Actor at (10, 0). Inside cone."""
    actors = [_MockActor(actor_id=1, type_id="vehicle.tesla.model3", x=10, y=0)]
    dets = actors_in_cone(
        ego_x=0.0, ego_y=0.0, ego_yaw_deg=0.0,
        actors=actors,
        cone_range_m=50.0, cone_angle_deg=90.0,
    )
    assert len(dets) == 1
    assert dets[0].object_class == "passengerCar"
    assert dets[0].x_m == 10.0
    assert dets[0].y_m == 0.0


def test_actor_behind_ego_excluded():
    actors = [_MockActor(actor_id=1, type_id="vehicle.tesla.model3", x=-10, y=0)]
    dets = actors_in_cone(0.0, 0.0, 0.0, actors, cone_range_m=50, cone_angle_deg=90)
    assert dets == []


def test_actor_outside_range_excluded():
    actors = [_MockActor(actor_id=1, type_id="vehicle.tesla.model3", x=100, y=0)]
    dets = actors_in_cone(0.0, 0.0, 0.0, actors, cone_range_m=50, cone_angle_deg=90)
    assert dets == []


def test_actor_outside_cone_angle_excluded():
    """90° full-cone (±45°) — actor at 60° to the side is outside."""
    angle_rad = math.radians(60.0)
    x = 20.0 * math.cos(angle_rad)
    y = 20.0 * math.sin(angle_rad)
    actors = [_MockActor(actor_id=1, type_id="vehicle.tesla.model3", x=x, y=y)]
    dets = actors_in_cone(0.0, 0.0, 0.0, actors, cone_range_m=50, cone_angle_deg=90)
    assert dets == []


def test_actor_inside_cone_angle_included():
    """Same setup as above but at 30° — inside ±45° half-cone."""
    angle_rad = math.radians(30.0)
    x = 20.0 * math.cos(angle_rad)
    y = 20.0 * math.sin(angle_rad)
    actors = [_MockActor(actor_id=1, type_id="vehicle.tesla.model3", x=x, y=y)]
    dets = actors_in_cone(0.0, 0.0, 0.0, actors, cone_range_m=50, cone_angle_deg=90)
    assert len(dets) == 1


def test_ego_skipped_by_actor_id():
    """If ego is in the actors list, ego_actor_id excludes it."""
    actors = [
        _MockActor(actor_id=42, type_id="vehicle.tesla.model3", x=0, y=0),  # ego
        _MockActor(actor_id=1, type_id="vehicle.audi.tt", x=10, y=0),
    ]
    dets = actors_in_cone(0.0, 0.0, 0.0, actors,
                          cone_range_m=50, cone_angle_deg=90,
                          ego_actor_id=42)
    assert len(dets) == 1
    # The non-ego actor's position survived.
    assert dets[0].x_m == 10.0


def test_class_filter_excludes_other_etsi_classes():
    """class_filter only admits the listed ETSI classes."""
    actors = [
        _MockActor(actor_id=1, type_id="vehicle.tesla.model3", x=10, y=0),
        _MockActor(actor_id=2, type_id="walker.pedestrian.0001", x=5, y=0),
        _MockActor(actor_id=3, type_id="vehicle.yamaha.yzf", x=15, y=0),
    ]
    dets = actors_in_cone(
        ego_x=0.0, ego_y=0.0, ego_yaw_deg=0.0,
        actors=actors,
        cone_range_m=50.0, cone_angle_deg=90.0,
        class_filter=("passengerCar", "pedestrian"),
    )
    classes = {d.object_class for d in dets}
    assert classes == {"passengerCar", "pedestrian"}  # motorcycle excluded


def test_velocity_propagated_to_local_detection():
    actors = [_MockActor(actor_id=1, type_id="vehicle.tesla.model3",
                         x=10, y=0, vx=5.0, vy=-2.0)]
    dets = actors_in_cone(0.0, 0.0, 0.0, actors,
                          cone_range_m=50, cone_angle_deg=90)
    assert dets[0].vx_ms == 5.0
    assert dets[0].vy_ms == -2.0


def test_unknown_actor_types_silently_skipped():
    actors = [
        _MockActor(actor_id=1, type_id="sensor.camera.rgb", x=10, y=0),
        _MockActor(actor_id=2, type_id="traffic.traffic_light", x=20, y=0),
        _MockActor(actor_id=3, type_id="vehicle.tesla.model3", x=15, y=0),
    ]
    dets = actors_in_cone(0.0, 0.0, 0.0, actors,
                          cone_range_m=50, cone_angle_deg=90)
    assert len(dets) == 1  # only the vehicle


def test_yawed_ego_cone_rotated():
    """Ego facing +Y (yaw=90°): an actor at (0, 10) should be ahead."""
    actors = [_MockActor(actor_id=1, type_id="vehicle.tesla.model3", x=0, y=10)]
    dets = actors_in_cone(
        ego_x=0.0, ego_y=0.0, ego_yaw_deg=90.0,
        actors=actors,
        cone_range_m=50.0, cone_angle_deg=90.0,
    )
    assert len(dets) == 1


# === Module loads without CARLA ===========================================

def test_carla_cav_module_imports_without_carla_sdk():
    """The whole module should be importable in CARLA-free environments;
    only CarlaCAV instantiation should require CARLA."""
    from v2xsim import carla_cav
    assert hasattr(carla_cav, "CarlaCAV")
    assert hasattr(carla_cav, "actors_in_cone")
    assert hasattr(carla_cav, "carla_type_to_etsi")


# === Destroyed-actor handling ============================================

class _DestroyedActorMock:
    """Mock vehicle whose get_transform() raises 'destroyed actor' error
    (simulating CARLA's behaviour after backend destruction)."""
    def __init__(self) -> None:
        self.id = 999
        self.type_id = "vehicle.tesla.model3"
        self.is_alive = False

    def get_transform(self):
        raise RuntimeError(
            "trying to operate on a destroyed actor; an actor's function "
            "was called, but the actor is already destroyed."
        )

    def get_velocity(self):
        return _MockLoc(0, 0)

    def get_location(self):
        raise RuntimeError("trying to operate on a destroyed actor")


class _MinimalBroker:
    """Tiny stand-in for Broker so CarlaCAV.tick can be exercised
    without spinning up a full latency/PDR model. Returns no deliveries."""
    def deliveries_due(self, sim_time_ms, receiver_id=None):
        return []


def test_carla_cav_handles_destroyed_actor_gracefully():
    """tick() must catch 'destroyed actor' RuntimeError, mark the CAV
    dead, and return None instead of propagating the exception. This
    prevents one mid-sweep actor destruction from killing the whole
    ablation runner."""
    from v2xsim.carla_cav import CarlaCAV
    actor = _DestroyedActorMock()
    cav = CarlaCAV(vehicle=actor, broker=_MinimalBroker())  # type: ignore[arg-type]
    # First call: catches the destroyed-actor error, returns None.
    result = cav.tick(sim_time_ms=0.0)
    assert result is None
    # CAV is marked dead.
    assert cav.is_alive() is False
    # Subsequent calls also return None immediately (no exception raised).
    result2 = cav.tick(sim_time_ms=100.0)
    assert result2 is None


# === V2V (Sprint 5) =======================================================

class _MockRotation:
    def __init__(self, yaw: float) -> None:
        self.yaw = yaw


class _MockTransform:
    def __init__(self, x: float, y: float, yaw: float) -> None:
        self.location = _MockLoc(x, y)
        self.rotation = _MockRotation(yaw)


class _MockEgoVehicle:
    """Mock ego vehicle exposing the transform/velocity surface CarlaCAV
    polls each tick."""
    def __init__(self, actor_id: int, x: float, y: float,
                 yaw: float = 0.0, vx: float = 0.0, vy: float = 0.0) -> None:
        self.id = actor_id
        self.type_id = "vehicle.tesla.model3"
        self.is_alive = True
        self._t = _MockTransform(x, y, yaw)
        self._v = _MockLoc(vx, vy)

    def get_transform(self) -> _MockTransform:
        return self._t

    def get_velocity(self) -> _MockLoc:
        return self._v

    def get_location(self) -> _MockLoc:
        return self._t.location


class _ScriptedBroker:
    """Delivers a fixed list of (sender_id, payload_bytes) once, then nothing."""
    def __init__(self, deliveries=()) -> None:
        self._deliveries = list(deliveries)

    def deliveries_due(self, sim_time_ms, receiver_id=None):
        out = [
            SimpleNamespace(sender_id=s, payload_bytes=p, sim_time_sent_ms=sim_time_ms)
            for s, p in self._deliveries
        ]
        self._deliveries = []
        return out


def test_local_dets_to_cpm_objects_are_relative_to_sender():
    """World-frame local detections become CPMObjects relative to the
    sender's pose (so the receiver reconstructs world = sender + offset)."""
    dets = [
        LocalDetection(object_class="passengerCar", x_m=30.0, y_m=5.0,
                       vx_ms=2.0, vy_ms=-1.0, confidence=0.8),
    ]
    objs = local_dets_to_cpm_objects(dets, sender_x_m=10.0, sender_y_m=2.0)
    assert len(objs) == 1
    assert objs[0].x_m == 20.0      # 30 - 10
    assert objs[0].y_m == 3.0       # 5 - 2
    assert objs[0].vx_ms == 2.0     # velocity is frame-independent
    assert objs[0].object_class == "passengerCar"
    assert objs[0].confidence == 0.8


def test_build_v2v_message_uses_cached_pose_and_relative_objects():
    from v2xsim.carla_cav import CarlaCAV
    ego = _MockEgoVehicle(actor_id=7, x=10.0, y=0.0, yaw=0.0, vx=8.0, vy=0.0)
    cav = CarlaCAV(vehicle=ego, broker=_ScriptedBroker(),  # type: ignore[arg-type]
                   local_sensor_enabled=True, enable_v2v=True)
    # One tick to populate the cache; a leader straight ahead in world frame.
    leader = _MockActor(actor_id=1, type_id="vehicle.audi.tt", x=30.0, y=0.0)
    cav.tick(sim_time_ms=0.0, other_actors=[leader])

    msg = cav.build_v2v_message(sim_time_ms=0.0, hard_brake=True)
    assert msg is not None
    assert msg.sender_id == "cav_7"
    assert msg.x_m == 10.0 and msg.y_m == 0.0
    assert msg.hard_brake is True
    # Leader at world (30,0) becomes relative (20,0) to the sender at (10,0).
    assert len(msg.objects) == 1
    assert msg.objects[0].x_m == 20.0


def test_build_v2v_message_none_before_first_tick():
    from v2xsim.carla_cav import CarlaCAV
    ego = _MockEgoVehicle(actor_id=7, x=10.0, y=0.0)
    cav = CarlaCAV(vehicle=ego, broker=_ScriptedBroker())  # type: ignore[arg-type]
    assert cav.build_v2v_message(sim_time_ms=0.0) is None


def test_receive_v2v_ingests_brake_warning_and_objects():
    """A received V2V message with hard_brake from a leader ahead triggers a
    cooperative brake on the same tick, and its shared object becomes a track."""
    from v2xsim.carla_cav import CarlaCAV
    # Sender 20 m ahead of the ego, sharing one perceived object at rel (5,0).
    sender_msg = V2VMessage(
        sender_id="cav_99", x_m=20.0, y_m=0.0, vx_ms=0.0, vy_ms=0.0,
        gen_time_ms=0, hard_brake=True,
        objects=(local_dets_to_cpm_objects(
            [LocalDetection(object_class="passengerCar", x_m=25.0, y_m=0.0)],
            sender_x_m=20.0, sender_y_m=0.0)[0],),
    )
    broker = _ScriptedBroker([("cav_99", encode_v2v(sender_msg))])
    # Ego at origin moving +x toward the sender.
    ego = _MockEgoVehicle(actor_id=7, x=0.0, y=0.0, yaw=0.0, vx=10.0, vy=0.0)
    cav = CarlaCAV(vehicle=ego, broker=broker,  # type: ignore[arg-type]
                   local_sensor_enabled=False, enable_v2v=True)
    decision = cav.tick(sim_time_ms=100.0)
    assert cav.v2v_received == 1
    assert decision is not None
    assert decision.cooperative_brake is True
    assert decision.action == Action.SOFT_BRAKE
    # The shared object (world 25,0) is registered as a track.
    tracks = cav.get_tracks()
    assert any(abs(t.x_m - 25.0) < 1e-6 for t in tracks)


def test_receive_v2v_does_not_count_as_decode_error():
    from v2xsim.carla_cav import CarlaCAV
    msg = V2VMessage(sender_id="cav_99", x_m=20.0, y_m=0.0, vx_ms=0.0, vy_ms=0.0,
                     gen_time_ms=0, hard_brake=False)
    broker = _ScriptedBroker([("cav_99", encode_v2v(msg))])
    ego = _MockEgoVehicle(actor_id=7, x=0.0, y=0.0, vx=10.0, vy=0.0)
    cav = CarlaCAV(vehicle=ego, broker=broker, enable_v2v=True)  # type: ignore[arg-type]
    cav.tick(sim_time_ms=0.0)
    assert cav.v2v_received == 1
    assert cav.decode_errors == 0
