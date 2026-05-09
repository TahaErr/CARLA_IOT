"""Thin helpers around the CARLA client.

Two reasons to centralize this:
  1. The synchronous-mode + traffic-manager-sync pairing is easy to get wrong;
     leaving the server in sync mode after a crashed script wedges it.
  2. We will need the same connect/sync pattern in every script.
"""
from __future__ import annotations

import contextlib
from typing import Iterator, Tuple

import carla


def connect(host: str = "127.0.0.1", port: int = 2000, timeout: float = 20.0) -> carla.Client:
    """Open a CARLA client. Timeout is generous because the first connection
    on a freshly-started server can take several seconds while assets warm up."""
    client = carla.Client(host, port)
    client.set_timeout(timeout)
    return client


@contextlib.contextmanager
def synchronous_mode(
    client: carla.Client, dt: float = 0.05
) -> Iterator[Tuple[carla.World, "carla.TrafficManager"]]:
    """Enter synchronous mode for both the world and the traffic manager,
    and **always** restore the previous settings on exit (even on exception).

    The proposal pins dt = 0.05 s for deterministic replay (§4.5).
    """
    world = client.get_world()
    tm = client.get_trafficmanager()

    original = world.get_settings()
    new = world.get_settings()
    new.synchronous_mode = True
    new.fixed_delta_seconds = dt
    world.apply_settings(new)
    tm.set_synchronous_mode(True)

    try:
        yield world, tm
    finally:
        # Best-effort restore. Failure here only matters if the server is gone,
        # in which case there is nothing left to fix anyway.
        try:
            world.apply_settings(original)
            tm.set_synchronous_mode(False)
        except Exception:
            pass


def ensure_map(client: carla.Client, map_name: str) -> carla.World:
    """Load `map_name` if it is not already current, then return the world.

    CARLA stores map names like 'Carla/Maps/Town05'; we substring-match so the
    caller can pass the short name 'Town05'.
    """
    world = client.get_world()
    if map_name not in world.get_map().name:
        world = client.load_world(map_name)
    return world
