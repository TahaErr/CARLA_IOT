"""Step B3 — capture one frame from a camera mounted at one Town05 intersection.

This is intentionally an inline near-copy of test 04 (which is known to work),
with the only addition being the intersection-discovery + selection step.
The RSU class introduced earlier was failing in this CARLA build for reasons
we have not isolated; we revert to the proven inline pattern and revisit
the class refactor in Sprint 2.

PASS criterion: `out/rsu{XX}.png` exists.
"""
from __future__ import annotations

import argparse
import os
import sys

import carla

from v2xsim.carla_utils import connect, ensure_map, synchronous_mode
from v2xsim.intersections import discover_intersections


def main(
    host: str,
    port: int,
    out_dir: str,
    target_map: str,
    intersection_idx: int,
    warmup_ticks: int,
) -> int:
    os.makedirs(out_dir, exist_ok=True)

    client = connect(host, port)
    world = ensure_map(client, target_map)
    print(f"map: {world.get_map().name}")

    intersections = discover_intersections(world)
    if not intersections:
        print("FAIL — no intersections", file=sys.stderr)
        return 1
    if intersection_idx >= len(intersections):
        print(
            f"FAIL — intersection {intersection_idx} out of range "
            f"(only {len(intersections)} found)",
            file=sys.stderr,
        )
        return 1

    target = intersections[intersection_idx]
    first_light = target.lights[0]
    loc = first_light.get_location()
    print(
        f"intersection {target.id}: light @ ({loc.x:.1f}, {loc.y:.1f}, {loc.z:.1f}), "
        f"{target.n_approaches} approach(es)"
    )

    cam = None
    saved = {"img": None, "count": 0}

    try:
        with synchronous_mode(client) as (world, _tm):
            world.tick()

            # Exactly the parameters from test 04.
            bp = world.get_blueprint_library().find("sensor.camera.rgb")
            bp.set_attribute("image_size_x", "320")
            bp.set_attribute("image_size_y", "240")
            bp.set_attribute("fov", "90")

            transform = carla.Transform(
                carla.Location(x=loc.x, y=loc.y, z=loc.z + 6.0),
                carla.Rotation(pitch=-25.0, yaw=0.0),
            )

            cam = world.spawn_actor(bp, transform)
            print(f"camera spawned: id={cam.id}")

            def on_frame(img: carla.Image) -> None:
                saved["img"] = img
                saved["count"] += 1

            cam.listen(on_frame)
            print("listen attached, ticking")

            for i in range(warmup_ticks):
                world.tick()
                if i < 5:
                    print(f"  tick {i+1}: count={saved['count']}")

            if saved["img"] is None:
                print(
                    f"FAIL — no frame received after {warmup_ticks} ticks",
                    file=sys.stderr,
                )
                return 1

            path = os.path.join(out_dir, f"rsu{target.id:02d}.png")
            saved["img"].save_to_disk(path)
            print(f"OK — wrote {path} ({saved['img'].width}x{saved['img'].height})")
            return 0
    finally:
        if cam is not None:
            try:
                cam.stop()
            except Exception:
                pass
            try:
                cam.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=2000)
    p.add_argument("--out", default="./out")
    p.add_argument("--map", default="Town05")
    p.add_argument("--intersection", type=int, default=0)
    p.add_argument("--warmup-ticks", type=int, default=10)
    args = p.parse_args()
    sys.exit(
        main(
            args.host,
            args.port,
            args.out,
            args.map,
            args.intersection,
            args.warmup_ticks,
        )
    )
