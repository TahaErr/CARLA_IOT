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
    centroid is reported as the intersection's center. The returned list is
    sorted by (center.x, center.y) so IDs are stable across CARLA restarts —
    important for reproducible train/val splits over multi-run datasets.
    """
    all_lights = list(world.get_actors().filter("traffic.traffic_light"))
    seen_ids: set[int] = set()
    raw: List[Intersection] = []

    for tl in all_lights:
        if tl.id in seen_ids:
            continue
        group = tl.get_group_traffic_lights() or [tl]
        for g in group:
            seen_ids.add(g.id)
        center = _centroid([g.get_location() for g in group])
        raw.append(
            Intersection(
                id=-1,  # reassigned after sort
                center=center,
                lights=list(group),
            )
        )

    # Stable order by world coords; reassign sequential IDs.
    raw.sort(key=lambda i: (round(i.center.x, 1), round(i.center.y, 1)))
    for new_id, it in enumerate(raw):
        it.id = new_id
    return raw
