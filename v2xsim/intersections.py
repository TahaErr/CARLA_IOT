"""Discover signalized intersections in the currently loaded CARLA map.

Every traffic light in CARLA belongs to a *group* (the lights that change
together at one intersection). We use `get_group_traffic_lights()` rather than
spatial clustering: it's exact, comes from the OpenDRIVE data, and avoids
hand-tuning a distance threshold.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import carla


@dataclass
class Intersection:
    id: int
    center: carla.Location
    lights: List[carla.TrafficLight] = field(repr=False)

    @property
    def n_approaches(self) -> int:
        return len(self.lights)


def _centroid(locs: List[carla.Location]) -> carla.Location:
    n = len(locs)
    return carla.Location(
        x=sum(l.x for l in locs) / n,
        y=sum(l.y for l in locs) / n,
        z=sum(l.z for l in locs) / n,
    )


def discover_intersections(world: carla.World) -> List[Intersection]:
    """Return every signalized intersection in the current map.

    Each intersection is exactly one CARLA traffic-light group; the group's
    centroid is reported as the intersection's center.
    """
    all_lights = list(world.get_actors().filter("traffic.traffic_light"))
    seen_ids: set[int] = set()
    out: List[Intersection] = []

    for tl in all_lights:
        if tl.id in seen_ids:
            continue
        group = tl.get_group_traffic_lights() or [tl]
        for g in group:
            seen_ids.add(g.id)
        center = _centroid([g.get_location() for g in group])
        out.append(
            Intersection(
                id=len(out),
                center=center,
                lights=list(group),
            )
        )
    return out
