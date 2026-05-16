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

from v2xsim.carla_cav import actors_in_cone, carla_type_to_etsi


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
