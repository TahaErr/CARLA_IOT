"""scripts/40_ablation_run.py — ablation runner (Sprint 4 + Sprint 5).

Executes proposal §4.6's V2X-penetration sweep: 3 cells × N seeds in
Town05 with 3 fixed RSUs (intersections 0/3/7), 60 vehicles, 5-min sim
per cell.

Sprint 5 behaviour model (role-based):
  - HDVs (human-driven): HOSTILE_MIX (50/20/30) with TM collision
    avoidance DISABLED — the conflict generators.
  - CAVs (V2X fleet): careful AI_REALISTIC profile, TM avoidance ENABLED,
    plus cooperative perception (RSU CPM) AND V2V (CAV→CAV shared objects +
    hard-brake intent).
  - Collisions are counted once per pair; the vehicles involved are
    immobilised in place (no runaway counter, no interpenetration).

Penetration sweep:
  - p = 0.0  : baseline. No CAVs; all-HDV hostile traffic.
  - p = 0.5  : half the spawned vehicles are V2X-equipped CAVs.
  - p = 1.0  : every spawned vehicle is a CAV.

Per-run output: one JSON in `--out-dir` with collision counts, action
histogram, phantom-brake-suppression count, CBR samples, and decode
error counters. Aggregator (Module 5b) reads these and produces the
thesis-ready summary CSV + figures.

Usage:
    :: Single run:
    python scripts\\40_ablation_run.py ^
        --detector runs\\detect\\runs\\detect\\yolo26s_carla_multi-2\\weights\\best.pt ^
        --penetration 0.5 --seed 42 --out out\\ablation\\p050_s42.json

    :: Full 3 × 10 sweep:
    python scripts\\40_ablation_run.py --sweep ^
        --detector runs\\detect\\runs\\detect\\yolo26s_carla_multi-2\\weights\\best.pt ^
        --out-dir out\\ablation

The --sweep mode iterates p ∈ {0.0, 0.5, 1.0} × seed ∈ {0..n_seeds-1}.
Use --skip-existing to resume an interrupted sweep without redoing
completed cells.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

import carla
import numpy as np

from v2xsim.broker import Broker
from v2xsim.carla_cav import CarlaCAV
from v2xsim.carla_rsu import CarlaRSU
from v2xsim.carla_utils import connect, ensure_map, synchronous_mode
from v2xsim.cav import Action
from v2xsim.compute_budget import unconstrained_profile
from v2xsim.hdv import (
    AI_REALISTIC,
    ATTENTIVE,
    HOSTILE_MIX,
    DEFAULT_MIX,
    apply_mix_to_vehicles,
    apply_profile_to_tm,
    disable_collision_detection_for,
)
from v2xsim.intersections import discover_intersections
from v2xsim.latency import LatencyModel
from v2xsim.pdr import PDRModel
from v2xsim.walker import (
    spawn_walkers_near_intersections,
    start_walker_controllers,
    stop_walker_controllers,
)
from v2xsim.weather import apply_weather_preset


# === Small helpers ========================================================

def _distance_2d(p1, p2):
    return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5


def _select_spaced_spawn_points(spawn_points, n, rng, min_sep_m=6.0):
    """Greedily pick up to `n` spawn points with a minimum pairwise spacing.

    CARLA map spawn points can sit a couple of metres apart (parallel lanes,
    junction stubs); filling them densely makes vehicles appear to spawn
    *inside* each other. Enforcing a min separation removes that artefact
    (Sprint 5 fix for item 3).
    """
    rng.shuffle(spawn_points)
    chosen: list = []
    for sp in spawn_points:
        loc = sp.location
        if all(
            _distance_2d((loc.x, loc.y), (c.location.x, c.location.y)) >= min_sep_m
            for c in chosen
        ):
            chosen.append(sp)
            if len(chosen) >= n:
                break
    return chosen


def _spawn_vehicles(world, tm, n, rng):
    """Spawn up to `n` autopilot vehicles at well-separated spawn points.

    Uses `try_spawn_actor` (returns None on a blocked spawn instead of
    raising) plus the min-separation filter above, so vehicles never
    materialise overlapping. Returns list of carla.Vehicle.
    """
    bp_lib = world.get_blueprint_library()
    vehicle_bps = list(bp_lib.filter("vehicle.*"))
    spawn_points = list(world.get_map().get_spawn_points())
    chosen = _select_spaced_spawn_points(spawn_points, n, rng)
    spawned = []
    for i, sp in enumerate(chosen):
        bp = vehicle_bps[i % len(vehicle_bps)]
        v = world.try_spawn_actor(bp, sp)
        if v is None:
            continue  # blocked by a residual occupant — skip, never force
        v.set_autopilot(True, tm.get_port())
        spawned.append(v)
    return spawned


def _attach_collision_sensor(world, vehicle, on_collision):
    bp = world.get_blueprint_library().find("sensor.other.collision")
    sensor = world.spawn_actor(bp, carla.Transform(), attach_to=vehicle)
    sensor.listen(on_collision)
    return sensor


def _apply_decision(vehicle, action):
    """Translate CAVDecision.action to a carla.VehicleControl override.

    HARD_BRAKE / SOFT_BRAKE / DECELERATE override autopilot for this
    one tick. NONE returns control to Traffic Manager (no apply_control).
    """
    if action == Action.HARD_BRAKE:
        vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0))
    elif action == Action.SOFT_BRAKE:
        vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=0.5))
    elif action == Action.DECELERATE:
        vehicle.apply_control(carla.VehicleControl(throttle=0.2, brake=0.0))
    # Action.NONE: no override


def _control_for(action):
    """Return the VehicleControl override for an action, or None for NONE.

    Same mapping as `_apply_decision` but returns the control so the caller
    can collect them and apply all CAV overrides in ONE batched RPC
    (`client.apply_batch`) instead of one `apply_control` call per CAV.
    """
    if action == Action.HARD_BRAKE:
        return carla.VehicleControl(throttle=0.0, brake=1.0)
    if action == Action.SOFT_BRAKE:
        return carla.VehicleControl(throttle=0.0, brake=0.5)
    if action == Action.DECELERATE:
        return carla.VehicleControl(throttle=0.2, brake=0.0)
    return None


def _immobilize(vehicle, tm_port, freeze_physics=True):
    """Bring a crashed vehicle to a permanent stop in place (Sprint 5 item 1).

    After a collision the vehicle would otherwise keep its autopilot throttle
    and grind/interpenetrate, and its collision sensor would keep firing —
    inflating the count. We hand control back from the TM, slam the brakes +
    handbrake, and (optionally) freeze its physics so it becomes a static
    wreck. No actor destruction — that reintroduces the CARLA-0.9.16-Windows
    mid-run destroy crash the Sprint 4 cleanup was built to avoid.
    """
    try:
        vehicle.set_autopilot(False, tm_port)
    except Exception:
        pass
    try:
        vehicle.apply_control(
            carla.VehicleControl(throttle=0.0, brake=1.0, hand_brake=True)
        )
    except Exception:
        pass
    if freeze_physics:
        try:
            vehicle.set_simulate_physics(False)
        except Exception:
            pass


class _ActorSnap:
    """Lightweight per-tick snapshot of an actor's pose + velocity.

    The CAV local-sensor cone (`actors_in_cone`) only duck-types
    `.id`, `.type_id`, `.get_location()`, `.get_velocity()`. Building one
    snapshot per actor per tick and handing the *same* list to every CAV
    turns the cone query pure-Python — instead of O(n_cav × n_actors) CARLA
    round-trips per tick we pay O(n_actors). Big speedup at high penetration.
    """
    __slots__ = ("id", "type_id", "_loc", "_vel")

    def __init__(self, actor_id, type_id, loc, vel):
        self.id = actor_id
        self.type_id = type_id
        self._loc = loc
        self._vel = vel

    def get_location(self):
        return self._loc

    def get_velocity(self):
        return self._vel


def _count_profile_assignments(assignments: dict) -> dict:
    counts: dict[str, int] = {}
    for name in assignments.values():
        counts[name] = counts.get(name, 0) + 1
    return counts


# === Single run ==========================================================

def run_single(args, penetration: float, seed: int) -> dict:
    """Execute one ablation cell.

    Returns a metrics dict ready to be JSON-serialised. Cleans up actors
    in `finally`. Reraises any exception to the caller (--sweep level
    catches and continues).
    """
    random.seed(seed)
    np.random.seed(seed)
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    client = connect(args.host, args.port)
    world = ensure_map(client, args.map)

    # === Per-cell world reset =========================================
    # CARLA 0.9.16 Windows binding leaves UE4 mesh "zombies" after
    # subprocess actor destroy: the Python API reports actor count = 0
    # but the geometry stays in the scene, complete with rigid-body
    # colliders that newly-spawned vehicles can crash into. The result
    # is inflated collision counts in subsequent cells.
    #
    # reload_world(False) is the official CARLA escape hatch — it
    # reloads the current map while keeping the world settings
    # (synchronous_mode + fixed_delta_seconds) intact. ~2-3 s per cell
    # but eliminates inter-cell contamination entirely.
    try:
        client.reload_world(False)
        # reload_world invalidates the world handle; fetch a fresh one.
        world = client.get_world()
    except Exception:
        # Some old CARLA builds don't support keep_settings; fall back
        # to the per-actor zombie sweep below.
        pass

    # Safety net: even after reload_world, very rarely a sensor or
    # controller actor survives. Force-destroy anything in vehicle /
    # walker / sensor / controller namespaces before we start.
    try:
        for actor in world.get_actors():
            tid = actor.type_id
            if tid.startswith(("vehicle.", "walker.", "sensor.",
                                "controller.ai.walker")):
                try:
                    actor.destroy()
                except Exception:
                    pass
    except Exception:
        pass

    intersections = discover_intersections(world)
    # Pick three intersection slots for the RSU triangle. Original
    # choice was the hard-coded [0, 3, 7] which works for Town05
    # (signalised count ~15) and Town01 (~12 grid), but Town10HD_Opt is
    # a small downtown with fewer signalised intersections — index 7
    # raises IndexError. Adapt to the map: if at least 8 intersections
    # exist, keep the legacy [0, 3, 7] for reproducibility with the
    # earlier sweep; otherwise spread three picks evenly across the
    # available range.
    n_avail = len(intersections)
    if n_avail >= 8:
        target_idx = [0, 3, 7]
    elif n_avail >= 3:
        target_idx = [0, n_avail // 2, n_avail - 1]
    else:
        # Last resort — fewer than 3 signalised intersections is
        # almost certainly the wrong map; fail loudly rather than
        # silently producing a degenerate RSU triangle.
        raise RuntimeError(
            f"Map {args.map!r} has only {n_avail} signalised "
            f"intersection(s); the V2X ablation requires at least 3."
        )
    target_intersections = [intersections[i] for i in target_idx]

    broker = Broker(
        latency=LatencyModel(rng=np.random.default_rng(seed + 100)),
        pdr=PDRModel(rng=np.random.default_rng(seed + 200)),
        cbr_window_ms=1000.0,
    )
    budget = unconstrained_profile(n_rsus=len(target_intersections))

    rsus: list = []
    rsu_positions: list = []
    vehicles: list = []
    cavs: list = []
    collision_sensors: list = []
    collision_events: list = []
    walkers: list = []
    walker_controllers: list = []
    current_sim_time = [0.0]  # mutable closure for callback timestamps

    try:
        with synchronous_mode(client, dt=args.dt) as (world, tm):
            world.tick()

            # === Weather preset =======================================
            # Apply BEFORE spawning RSUs/vehicles so cameras render
            # under the target preset from frame 0. Validated against
            # the WEATHER_PRESETS whitelist; ValueError on unknown.
            apply_weather_preset(world, args.weather)
            world.tick()

            # === RSUs ==================================================
            if not getattr(args, 'no_v2x', False):
                for target in target_intersections:
                    rsu = CarlaRSU(
                        world=world,
                        intersection=target,
                        light_idx=0,
                        broker=broker,
                        detector_path=args.detector,
                        station_id=target.id,
                        compute_budget=budget,
                        image_size=(args.image_w, args.image_h),
                        fov_deg=args.fov,
                        confidence_threshold=args.conf,
                        device=args.device,
                        sensor_tick_s=args.cpm_period_ms / 1000.0,
                    )
                    rsus.append(rsu)
                    light_loc = target.lights[0].get_location()
                    rsu_positions.append((light_loc.x, light_loc.y))

            # === Vehicles ==============================================
            vehicles = _spawn_vehicles(world, tm, args.n_vehicles, rng)
            world.tick()

            # === Role split: pick CAVs first, the rest are HDVs ========
            # Sprint 5: behaviour is role-based.
            #   * HDVs (human-driven) carry the HOSTILE_MIX and run with TM
            #     collision-avoidance DISABLED (applied after warmup) — they
            #     are the conflict generators that keep the baseline's
            #     collision rate non-zero and measurable.
            #   * CAVs (the V2X fleet) carry the careful AI_REALISTIC profile,
            #     keep TM collision-avoidance ENABLED, and run the
            #     cooperative-perception + V2V layer on top. --cav-attentive
            #     swaps AI_REALISTIC for the flawless ATTENTIVE profile as an
            #     ablation arm.
            n_cavs = int(round(penetration * len(vehicles)))
            cav_vehicles = rng.sample(vehicles, n_cavs) if n_cavs > 0 else []
            cav_actor_ids: set = {v.id for v in cav_vehicles}
            hdv_vehicles = [v for v in vehicles if v.id not in cav_actor_ids]

            # HDV behaviour mix (TM avoidance disabled later, after warmup).
            hdv_mix_obj = HOSTILE_MIX if getattr(args, 'hdv_mix', 'hostile') == "hostile" else DEFAULT_MIX
            hdv_assignments = apply_mix_to_vehicles(
                tm, hdv_vehicles, mix=hdv_mix_obj, rng=np_rng,
            )
            # CAV driving profile — careful AI by default.
            cav_profile = ATTENTIVE if args.cav_attentive else AI_REALISTIC
            for v in cav_vehicles:
                apply_profile_to_tm(tm, v, cav_profile)
            # Combined per-vehicle profile map, for collision attribution.
            vehicle_profile: dict[int, str] = dict(hdv_assignments)
            for v in cav_vehicles:
                vehicle_profile[v.id] = cav_profile.name

            # === CAV wrappers (V2V enabled) ===========================
            for v in cav_vehicles:
                cav = CarlaCAV(
                    vehicle=v,
                    broker=broker,
                    local_sensor_enabled=True,
                    local_sensor_range_m=50.0,
                    local_sensor_angle_deg=90.0,
                    enable_v2v=True,
                )
                for rsu_id, rsu_xy in zip(
                    [str(t.id) for t in target_intersections],
                    rsu_positions,
                ):
                    cav.register_rsu(rsu_id, rsu_xy)
                cavs.append(cav)

            if not args.quiet:
                print(f"   roles: {len(hdv_vehicles)} HDV (HOSTILE_MIX, avoidance OFF) + "
                      f"{len(cav_vehicles)} CAV ({cav_profile.name}, avoidance ON, V2V)")

            # === Walkers (pedestrians, optional VRU axis) ============
            # Map-wide spawn (radius_m=None): pedestrians are distributed
            # across the whole town, not artificially concentrated at the
            # 3 RSU intersections. Realistic urban pedestrian density;
            # V2X benefit is evaluated on whichever subset enters RSU
            # camera frustums during the run.
            #
            # After spawn we MUST tick once before starting controllers,
            # otherwise CARLA crashes on the first controller.start()
            # call (cf. carla-simulator/carla #4350).
            walker_actor_ids: set = set()
            if args.n_walkers > 0:
                intersection_centroids = []
                for target in target_intersections:
                    c = target.lights[0].get_location()
                    intersection_centroids.append((c.x, c.y, c.z))
                walkers, walker_controllers = spawn_walkers_near_intersections(
                    client=client,
                    world=world,
                    intersection_centroids=intersection_centroids,
                    n_walkers=args.n_walkers,
                    radius_m=None,     # map-wide spawn
                    seed=seed + 300,
                )
                walker_actor_ids = {w.id for w in walkers}
                # Sync tick so the just-spawned walker transforms reach
                # the client and the controllers have a valid actor to
                # attach behaviour to.
                world.tick()

            # === Collision sensors on EVERY vehicle ==================
            # We attach a collision sensor to every spawned vehicle, not
            # just CAVs, so that baseline (p=0) runs still report HDV-HDV
            # collisions.
            #
            # IMPORTANT: the listener runs on a CARLA-side thread. Doing
            # *any* attribute access on `event.other_actor` beyond `.id`
            # has been observed to crash CARLA on Windows when the other
            # actor is destroyed near the end of the run (`type_id` in
            # particular causes STATUS_STACK_BUFFER_OVERRUN). Mirror the
            # bisect-step-2 callback exactly: capture only the IDs and
            # the simulation time. All per-vehicle metadata (is_cav,
            # profile, type) is looked up post-loop via local dicts.
            #
            # Hard cap on the event list size: unbounded growth was
            # suspected of contributing to the late-sim crash pattern.
            # 25,000 is above the highest raw count observed in
            # successful runs (~20k), so realistic runs are unaffected.
            COLLISION_EVENT_CAP = 25000

            # vehicle_profile already includes both HDV and CAV assignments.
            vehicle_is_cav: dict[int, bool] = {v.id: (v.id in cav_actor_ids) for v in vehicles}
            # id → actor, so a crash can immobilise the colliding vehicles.
            actor_by_id: dict[int, "carla.Actor"] = {v.id: v for v in vehicles}

            def _make_listener(vehicle_id: int):
                def listener(event):
                    if len(collision_events) >= COLLISION_EVENT_CAP:
                        return  # cap reached — silent drop
                    try:
                        collision_events.append((
                            current_sim_time[0],
                            vehicle_id,
                            event.other_actor.id,
                        ))
                    except Exception:
                        # Never block the listener thread on anything.
                        pass
                return listener

            for v in vehicles:
                sensor = _attach_collision_sensor(world, v, _make_listener(v.id))
                collision_sensors.append(sensor)

            # Walkers also get collision sensors so we can count walker-hit
            # events from the walker's side (vehicle's sensor will see it
            # too, producing a paired event for the same physical collision
            # — same dedup logic handles both).
            for w in walkers:
                sensor = _attach_collision_sensor(world, w, _make_listener(w.id))
                collision_sensors.append(sensor)

            # === Warmup ================================================
            # Run the 40-tick warmup with TM collision detection still
            # ENABLED, so vehicles spread out from their spawn clusters
            # before we remove the avoidance layer.
            for _ in range(40):
                world.tick()

            # Walker AI controllers must start AFTER at least one tick
            # has elapsed since their spawn, otherwise the walkers freeze
            # in their default T-pose. The warmup above guarantees this.
            if walker_controllers:
                start_walker_controllers(walker_controllers, world)
                world.tick()

            # === Disable TM collision avoidance — HDVs only (after warmup) ===
            # NOW the vehicles have dispersed; remove the avoidance safety
            # net from HDVs (one-way, against every vehicle) so their
            # profile violations produce measurable collisions. CAVs are
            # NOT in the actor list, so they keep avoidance and behave as
            # careful AVs (Sprint 5 item 4).
            # disable_collision_detection_for(tm, hdv_vehicles, vehicles)
            world.tick()

            # === Main loop =============================================
            sim_dt_ms = args.dt * 1000.0
            # CPM/V2V broadcast cadence. 100 ms = 10 Hz (ETSI default).
            # Larger periods (e.g. 200 ms = 5 Hz) cut RSU rendering + YOLO
            # load proportionally and are a legitimate lower broadcast rate.
            cpm_period_ticks = max(1, round(args.cpm_period_ms / sim_dt_ms))
            n_ticks = int(args.duration / args.dt)

            action_counts = {a.value: 0 for a in Action}
            phantom_brakes_suppressed = 0
            cooperative_brakes = 0          # decisions raised by a V2V brake warning
            cbr_samples: list = []
            n_publishes_attempted = 0
            n_publishes_emitted = 0
            n_publishes_dropped = 0
            v2v_publishes_attempted = 0     # CAV→CAV broadcasts issued
            v2v_deliveries_emitted = 0      # per-receiver V2V messages PDR-accepted
            dead_cav_ids: set = set()       # CAVs destroyed OR immobilised by a crash
            # cav.id → True if it hard-braked since its last V2V broadcast.
            # Latching this (vs sampling only the publish tick) makes the
            # hard-brake intent robust to the broadcast period.
            cav_hard_brake_pending: dict = {}

            # --- Collision incident tracking (Sprint 5 item 1) ---------
            # Count each colliding pair once and immobilise the vehicles
            # involved, so they stop accelerating / interpenetrating and
            # stop re-firing their collision sensors (which is what inflated
            # the old contact-frame count).
            seen_collision_pairs: set = set()
            collision_incidents: list = []  # (sim_t, a_id, b_id) — one per pair
            frozen_ids: set = set()
            processed_collision_idx = 0

            # --- Per-section profiler (always accumulates; printed if --profile) ---
            prof: dict = {}

            def _lap(key, t_prev):
                now = time.perf_counter()
                prof[key] = prof.get(key, 0.0) + (now - t_prev)
                return now

            wall_t0 = time.time()
            for tick in range(n_ticks):
                _t = time.perf_counter()
                world.tick()
                _t = _lap("1_world_tick", _t)
                sim_time_ms = tick * sim_dt_ms
                current_sim_time[0] = sim_time_ms

                # One world snapshot per tick: every actor's pose + velocity
                # in a SINGLE RPC. snap.find(id) then reads locally, replacing
                # the hundreds of per-actor get_location/get_transform/
                # get_velocity round-trips that made this loop RPC-latency-
                # bound (low GPU/CPU, laggy UE4 window). Also yields cav_xy
                # for the RSU + V2V range queries.
                snap = world.get_snapshot()
                cav_xy: dict = {}
                for cav in cavs:
                    if cav.id in dead_cav_ids:
                        continue
                    s = snap.find(cav.actor.id)
                    if s is None:
                        dead_cav_ids.add(cav.id)
                        continue
                    loc = s.get_transform().location
                    cav_xy[cav.id] = (loc.x, loc.y)
                _t = _lap("2_snapshot", _t)

                # --- RSU publishes once per CPM period --------------
                if tick % cpm_period_ticks == 0:
                    budget.reset_window()
                    for rsu, rsu_pos in zip(rsus, rsu_positions):
                        receivers: list = []
                        for cav in cavs:
                            xy = cav_xy.get(cav.id)
                            if xy is None:
                                continue
                            d = _distance_2d(rsu_pos, xy)
                            if d <= args.max_range:
                                receivers.append((cav.id, d))
                        n_publishes_attempted += 1
                        if rsu.tick(sim_time_ms, receivers):
                            n_publishes_emitted += 1
                        else:
                            n_publishes_dropped += 1
                _t = _lap("3_rsu_yolo", _t)

                # --- CAV decisions every sim tick -------------------
                if cavs:
                    # Cone input built from the snapshot (no per-actor RPC).
                    other_actors = []
                    for a in vehicles + walkers:
                        s = snap.find(a.id)
                        if s is None:
                            continue  # destroyed / not in this frame
                        other_actors.append(_ActorSnap(
                            a.id, a.type_id,
                            s.get_transform().location, s.get_velocity()))
                    _t = _lap("4_actors_build", _t)
                    control_cmds = []
                    for cav in cavs:
                        if cav.id in dead_cav_ids:
                            continue
                        s = snap.find(cav.actor.id)
                        if s is None:
                            dead_cav_ids.add(cav.id)
                            continue
                        t = s.get_transform(); v = s.get_velocity()
                        ego_state = (t.location.x, t.location.y,
                                     t.rotation.yaw, v.x, v.y)
                        try:
                            decision = cav.tick(sim_time_ms, other_actors,
                                                ego_state=ego_state)
                        except RuntimeError as e:
                            if "destroyed actor" in str(e):
                                dead_cav_ids.add(cav.id)
                                continue
                            raise
                        if decision is None:
                            # CarlaCAV reported itself dead via internal guard.
                            dead_cav_ids.add(cav.id)
                            continue
                        action_counts[decision.action.value] += 1
                        if decision.phantom_brake_suppressed:
                            phantom_brakes_suppressed += 1
                        if decision.cooperative_brake:
                            cooperative_brakes += 1
                        if decision.action == Action.HARD_BRAKE:
                            cav_hard_brake_pending[cav.id] = True
                        ctrl = _control_for(decision.action)
                        if ctrl is not None:
                            control_cmds.append(
                                carla.command.ApplyVehicleControl(cav.actor.id, ctrl))
                    # Apply every CAV override in ONE batched RPC.
                    if control_cmds:
                        client.apply_batch(control_cmds)
                    _t = _lap("5_cav_decide", _t)

                # --- V2V broadcast once per CPM period --------------
                # Each live CAV broadcasts (a) the objects it perceives and
                # (b) its own pose + hard-brake intent to other CAVs in
                # range, through the same broker (so PDR / latency / CBR
                # apply identically to the RSU path). HDVs are non-connected
                # and neither send nor receive. --no-v2v disables this leg
                # (CAVs keep RSU CPMs + local sensor) for the V2I-only arm.
                if cavs and not args.no_v2v and tick % cpm_period_ticks == 0:
                    for cav in cavs:
                        if cav.id not in cav_xy:
                            continue
                        sx, sy = cav_xy[cav.id]
                        receivers = []
                        for oid, opos in cav_xy.items():
                            if oid == cav.id:
                                continue
                            d = _distance_2d((sx, sy), opos)
                            if d <= args.v2v_range:
                                receivers.append((oid, d))
                        if not receivers:
                            continue
                        hard_brake = cav_hard_brake_pending.pop(cav.id, False)
                        payload = cav.encode_v2v_message(sim_time_ms, hard_brake=hard_brake)
                        if payload is None:
                            continue
                        v2v_publishes_attempted += 1
                        v2v_deliveries_emitted += len(
                            broker.publish(cav.id, payload, receivers, sim_time_ms)
                        )
                _t = _lap("6_v2v", _t)

                # --- CBR sample every sim-second --------------------
                if tick % 20 == 0:
                    cbr_samples.append(broker.channel_busy_ratio(sim_time_ms=sim_time_ms))

                # --- Process new collisions: count once, immobilise -
                n_events_now = len(collision_events)
                while processed_collision_idx < n_events_now:
                    sim_t, a_id, b_id = collision_events[processed_collision_idx]
                    processed_collision_idx += 1
                    key = (a_id, b_id) if a_id <= b_id else (b_id, a_id)
                    if key in seen_collision_pairs:
                        continue
                    seen_collision_pairs.add(key)
                    collision_incidents.append((sim_t, a_id, b_id))
                    # Immobilise any vehicle parties (walkers are left alone).
                    for pid in (a_id, b_id):
                        if pid in frozen_ids:
                            continue
                        veh = actor_by_id.get(pid)
                        if veh is None:
                            continue  # walker / untracked actor
                        _immobilize(veh, tm.get_port())
                        frozen_ids.add(pid)
                        if pid in cav_actor_ids:
                            # A wrecked CAV stops deciding / overriding / sending.
                            dead_cav_ids.add(f"cav_{pid}")
                _t = _lap("7_collision", _t)

                # --- Progress every ~10 sim seconds -----------------
                if (tick + 1) % 200 == 0 and not args.quiet:
                    wall = time.time() - wall_t0
                    sim = (tick + 1) * 0.05
                    print(f"    tick {tick+1:5d}/{n_ticks}  "
                          f"sim={sim:5.0f}s wall={wall:5.0f}s  "
                          f"emit={n_publishes_emitted:4d}  "
                          f"collisions={len(collision_incidents):3d}  "
                          f"frozen={len(frozen_ids):3d}")

            wall_total = time.time() - wall_t0

            # === Profile breakdown =====================================
            prof_total = sum(prof.values()) or 1e-9
            if args.profile:
                print(f"\n=== PROFILE (loop wall {wall_total:.1f}s, "
                      f"{n_ticks} ticks, {wall_total/n_ticks*1000:.1f} ms/tick) ===")
                for k in sorted(prof):
                    sec = prof[k]
                    print(f"  {k:18s} {sec:8.1f}s  {sec/prof_total*100:5.1f}%  "
                          f"{sec/n_ticks*1000:6.2f} ms/tick")

            # === Aggregation ===========================================
            cbr_mean = float(np.mean(cbr_samples)) if cbr_samples else 0.0
            cbr_max = float(np.max(cbr_samples)) if cbr_samples else 0.0

            # Sprint 5: collisions were already deduplicated *during* the
            # loop into one incident per unordered pair (and the colliding
            # vehicles were immobilised so a pair cannot re-fire). The raw
            # contact-frame stream stays available as `collision_events` for
            # diagnostics; `collision_incidents` is the reported metric.
            deduped_events: list[tuple] = collision_incidents

            # Look up per-vehicle metadata from the local maps built before
            # the loop — never touch the now-destroyed CARLA actors.
            cav_collisions = 0
            collisions_per_profile: dict[str, int] = {}
            # VRU axis — classify each deduped event by whether either
            # party is a walker. The dedup runs over ordered (a, b) pairs
            # so a single physical vehicle↔walker collision shows up as
            # exactly one deduped event (no double-count).
            vru_collisions = 0
            cav_hit_pedestrian = 0
            hdv_hit_pedestrian = 0
            for sim_t, v_id, other_id in deduped_events:
                # CAV-involved if EITHER party is a CAV — a CAV rear-ended by
                # an HDV still counts even though the HDV's sensor (v_id) may
                # have reported the contact first. hdv_collision_count is then
                # the HDV-only remainder.
                if vehicle_is_cav.get(v_id, False) or vehicle_is_cav.get(other_id, False):
                    cav_collisions += 1
                p = vehicle_profile.get(v_id, "unknown")
                collisions_per_profile[p] = collisions_per_profile.get(p, 0) + 1

                # Is this collision a VRU collision (either side is a walker)?
                v_is_walker = v_id in walker_actor_ids
                other_is_walker = other_id in walker_actor_ids
                if v_is_walker or other_is_walker:
                    vru_collisions += 1
                    # Which side is the vehicle? Classify CAV vs HDV
                    # using the non-walker party.
                    vehicle_party_id = other_id if v_is_walker else v_id
                    if vehicle_is_cav.get(vehicle_party_id, False):
                        cav_hit_pedestrian += 1
                    else:
                        hdv_hit_pedestrian += 1
            hdv_collisions = len(deduped_events) - cav_collisions
            decode_errors = sum(c.decode_errors for c in cavs)

            metrics_dict = {
                "config": {
                    "map": args.map,
                    "intersections": target_idx,
                    "penetration": penetration,
                    "seed": seed,
                    "n_vehicles": len(vehicles),
                    "n_cavs": len(cavs),
                    "n_walkers": len(walkers),
                    "weather": args.weather,
                    "duration_s": args.duration,
                    "max_range_m": args.max_range,
                    "local_sensor_enabled": True,
                    "local_sensor_range_m": 50.0,
                    "local_sensor_angle_deg": 90.0,
                    "v2v_enabled": not args.no_v2v,
                    "v2v_range_m": args.v2v_range,
                    "cpm_period_ms": args.cpm_period_ms,
                    "dt_s": args.dt,
                },
                "wall_seconds": wall_total,
                "sim_seconds": args.duration,
                "wall_to_sim_ratio": wall_total / max(args.duration, 1e-9),
                "publishes_attempted": n_publishes_attempted,
                "publishes_emitted": n_publishes_emitted,
                "publishes_dropped": n_publishes_dropped,
                "cbr_mean": cbr_mean,
                "cbr_max": cbr_max,
                "collision_count": len(deduped_events),
                "raw_collision_events": len(collision_events),
                "cav_collision_count": cav_collisions,
                "hdv_collision_count": hdv_collisions,
                "vru_collision_count": vru_collisions,
                "cav_hit_pedestrian_count": cav_hit_pedestrian,
                "hdv_hit_pedestrian_count": hdv_hit_pedestrian,
                "collisions_per_profile": collisions_per_profile,
                "actions_taken": action_counts,
                "phantom_brakes_suppressed": phantom_brakes_suppressed,
                "cooperative_brakes": cooperative_brakes,
                "frozen_vehicle_count": len(frozen_ids),
                "v2v_publishes_attempted": v2v_publishes_attempted,
                "v2v_deliveries_emitted": v2v_deliveries_emitted,
                "v2v_received_total": sum(c.v2v_received for c in cavs),
                "dead_cav_count": len(dead_cav_ids),
                "decode_errors": decode_errors,
                "hdv_profile_counts": _count_profile_assignments(hdv_assignments),
                "cav_profile": cav_profile.name,
                "profile_seconds": {k: round(v, 3) for k, v in prof.items()},
            }

            # === In-sync-mode cleanup ===================================
            # Suspected root cause of late-sim crashes: sensors firing
            # on the CARLA thread while we're tearing down actors in
            # async mode (outer finally below). We now stop sensor
            # callbacks, drain the queue with one tick, then destroy
            # actors — all while sync mode is still active so timing
            # is deterministic. The outer finally still runs as a
            # safety net for any actors that survive this block.
            for s in collision_sensors:
                try: s.stop()
                except Exception: pass
            # Stop walker AI controllers BEFORE destroying them — same
            # reason: a controller firing after its walker is gone has
            # been observed to crash CARLA on Windows.
            stop_walker_controllers(walker_controllers)
            try: world.tick()
            except Exception: pass
            for s in collision_sensors:
                try: s.destroy()
                except Exception: pass
            collision_sensors.clear()
            for c in walker_controllers:
                try: c.destroy()
                except Exception: pass
            walker_controllers.clear()
            for w in walkers:
                try: w.destroy()
                except Exception: pass
            walkers.clear()
            for r in rsus:
                try: r.destroy()
                except Exception: pass
            rsus.clear()
            for v in vehicles:
                try: v.destroy()
                except Exception: pass
            vehicles.clear()
            try: world.tick()
            except Exception: pass

            return metrics_dict

    finally:
        # Safety-net cleanup for the exception path. Normal exits clear
        # the lists inside the with-block (in-sync-mode cleanup above),
        # so this is a no-op on the happy path. If an exception is raised
        # before reaching that block, this catches the spawned actors.
        for s in collision_sensors:
            try: s.stop()
            except Exception: pass
            try: s.destroy()
            except Exception: pass
        try: stop_walker_controllers(walker_controllers)
        except Exception: pass
        for c in walker_controllers:
            try: c.destroy()
            except Exception: pass
        for w in walkers:
            try: w.destroy()
            except Exception: pass
        for r in rsus:
            try: r.destroy()
            except Exception: pass
        for v in vehicles:
            try: v.destroy()
            except Exception: pass


# === Sweep mode ==========================================================

def run_sweep(args) -> int:
    """Iterate 3 penetration × n_seeds = 3·n_seeds runs."""
    os.makedirs(args.out_dir, exist_ok=True)

    penetrations = [0.0, 0.5, 1.0]
    seeds = list(range(args.n_seeds))
    total = len(penetrations) * len(seeds)
    done = 0
    crashed = 0

    print(f"=== Sweep: {len(penetrations)} penetration × {len(seeds)} seeds "
          f"= {total} runs of {args.duration:.0f}s each ===")
    sweep_t0 = time.time()

    for p in penetrations:
        for seed in seeds:
            done += 1
            out_path = os.path.join(
                args.out_dir,
                f"p{int(p * 100):03d}_s{seed:02d}.json",
            )
            if args.skip_existing and os.path.exists(out_path):
                print(f"[{done}/{total}] SKIP existing: {out_path}")
                continue

            print(f"\n[{done}/{total}] === run p={p} seed={seed} → {out_path}")
            try:
                metrics = run_single(args, penetration=p, seed=seed)
                metrics["status"] = "ok"
                print(f"   ok — collisions={metrics['collision_count']} "
                      f"(cav={metrics['cav_collision_count']} hdv={metrics['hdv_collision_count']})  "
                      f"phantom_brakes_suppressed={metrics['phantom_brakes_suppressed']}")
            except Exception as e:
                crashed += 1
                metrics = {
                    "status": "crashed",
                    "error": repr(e),
                    "config": {"penetration": p, "seed": seed},
                }
                print(f"   CRASHED: {e}", file=sys.stderr)

            with open(out_path, "w") as f:
                json.dump(metrics, f, indent=2, default=str)

    elapsed = time.time() - sweep_t0
    print(f"\n=== Sweep complete in {elapsed/60:.1f} min "
          f"({done} runs, {crashed} crashed) ===")
    print(f"Aggregate with: python scripts\\41_ablation_aggregate.py --in-dir {args.out_dir}")
    return 0 if crashed == 0 else 2


# === Main ================================================================

def main() -> int:
    # Force UTF-8 console output so non-ASCII status chars never raise
    # UnicodeEncodeError under Windows cp1252 when stdout is redirected.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=2000)
    p.add_argument("--map", default="Town05")
    p.add_argument("--detector", required=True)

    # single-run mode
    p.add_argument("--penetration", type=float, default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--out", default=None)

    # sweep mode
    p.add_argument("--sweep", action="store_true")
    p.add_argument("--out-dir", default="out/ablation")
    p.add_argument("--n-seeds", type=int, default=5,
                   help="seeds per penetration cell (default 5)")
    p.add_argument("--skip-existing", action="store_true")

    # common
    p.add_argument("--duration", type=float, default=120.0,
                   help="simulation seconds per run (default 120 = 2 min)")
    p.add_argument("--dt", type=float, default=0.05,
                   help="fixed simulation timestep in seconds (default 0.05 = "
                        "20 Hz). 0.1 (10 Hz) halves the tick count for ~2x "
                        "wall-speed; CARLA sub-steps physics so collisions stay "
                        "stable, but reaction/collision timing is coarser.")
    p.add_argument("--n-vehicles", type=int, default=60,
                   help="vehicles to spawn (default 60 — scenario B 'downtown realistic'. "
                        "Higher values risk Town05 spawn-point exhaustion (~302 total, ~100 usable).)")
    p.add_argument("--n-walkers", type=int, default=0,
                   help="pedestrians to spawn (default 0 = vehicle-only baseline; "
                        "60-120 enables the VRU axis with map-wide pedestrian distribution)")
    p.add_argument("--weather", default="ClearNoon",
                   help="CARLA weather preset (default ClearNoon = best-case visibility). "
                        "Weather ablation axis defaults to ClearNoon/ClearSunset/HardRainNoon. "
                        "Must be in WEATHER_PRESETS whitelist (see v2xsim/weather.py).")
    p.add_argument("--max-range", type=float, default=300.0)
    p.add_argument("--cpm-period-ms", type=float, default=100.0,
                   help="CPM/V2V broadcast period in ms (default 100 = 10 Hz, "
                        "ETSI default). 200 = 5 Hz roughly halves RSU render + "
                        "YOLO cost (~2x faster) at a realistic lower rate. Also "
                        "sets the RSU camera sensor_tick.")
    p.add_argument("--v2v-range", type=float, default=150.0,
                   help="CAV→CAV V2V broadcast range in metres (default 150). "
                        "Receivers beyond this are not scheduled.")
    p.add_argument("--no-v2v", action="store_true",
                   help="Disable the CAV→CAV V2V leg (V2I-only arm). CAVs keep "
                        "RSU CPMs + their local sensor. Use to isolate V2V's "
                        "marginal benefit vs RSU-only cooperative perception.")
    p.add_argument("--no-v2x", action="store_true",
                   help="Disable RSU/V2I CPM broadcasts completely (V2V-only arm).")
    p.add_argument("--image-w", type=int, default=1280)
    p.add_argument("--image-h", type=int, default=720)
    p.add_argument("--fov", type=float, default=90.0)
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--profile", action="store_true",
                   help="Time each per-tick loop section (world tick, snapshot, "
                        "RSU/YOLO, actor build, CAV decide, V2V, collisions) and "
                        "print a breakdown at the end. Diagnostic for where wall "
                        "time goes.")
    p.add_argument("--hdv-mix", choices=["hostile", "default"], default="hostile",
                   help="HDV behaviour mix. 'hostile' = HOSTILE_MIX, 'default' = DEFAULT_MIX.")
    p.add_argument("--cav-attentive", action="store_true",
                   help="Ablation arm: give CAVs the flawless ATTENTIVE profile "
                        "instead of the default careful AI_REALISTIC (small "
                        "real-world error rate). HDVs always run HOSTILE_MIX.")

    args = p.parse_args()

    if not os.path.isfile(args.detector):
        print(f"FAIL — detector not found: {args.detector}", file=sys.stderr)
        return 1

    if args.sweep:
        return run_sweep(args)

    if args.penetration is None or args.seed is None or args.out is None:
        print("FAIL — single-run mode requires --penetration, --seed, --out",
              file=sys.stderr)
        return 1

    print(f"=== Single run: penetration={args.penetration} seed={args.seed}")
    try:
        metrics = run_single(args, penetration=args.penetration, seed=args.seed)
        metrics["status"] = "ok"
        metrics.setdefault("config", {})["cav_attentive"] = args.cav_attentive
    except Exception as e:
        print(f"FAIL — run crashed: {e}", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print(f"wrote {args.out}")
    print(f"  collisions:                {metrics['collision_count']} "
          f"(cav={metrics['cav_collision_count']} hdv={metrics['hdv_collision_count']})")
    if metrics['config'].get('n_walkers', 0) > 0:
        print(f"  VRU collisions:            {metrics['vru_collision_count']} "
              f"(cav-hit={metrics['cav_hit_pedestrian_count']} "
              f"hdv-hit={metrics['hdv_hit_pedestrian_count']})")
    print(f"  phantom brakes suppressed: {metrics['phantom_brakes_suppressed']}")
    print(f"  actions taken:             {metrics['actions_taken']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
