"""Step B1 — list signalized intersections in the target map.

Useful as a sanity check before script 03 (so you know how many intersections
exist and which index to mount the RSU on).
"""
from __future__ import annotations

import argparse

from v2xsim.carla_utils import connect, ensure_map
from v2xsim.intersections import discover_intersections


def main(host: str, port: int, target_map: str) -> int:
    client = connect(host, port)
    world = ensure_map(client, target_map)
    print(f"map: {world.get_map().name}")

    intersections = discover_intersections(world)
    print(f"found {len(intersections)} signalized intersection(s)")
    for it in intersections:
        c = it.center
        print(
            f"  [{it.id:02d}] center=({c.x:7.1f}, {c.y:7.1f}, {c.z:5.1f})  "
            f"approaches={it.n_approaches}"
        )
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=2000)
    p.add_argument("--map", default="Town05")
    args = p.parse_args()
    raise SystemExit(main(args.host, args.port, args.map))
