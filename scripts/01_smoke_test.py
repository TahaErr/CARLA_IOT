"""Step A — environment smoke test.

Connects to a running CARLA server, spawns a Tesla Model 3 with a chase
camera attached, runs 5 simulated seconds in autopilot, and saves one frame.

PASS criterion: `out/smoke_test.png` exists and shows a non-black scene.
"""
from __future__ import annotations

import argparse
import os
import sys

import carla

from v2xsim.carla_utils import connect, synchronous_mode


def run(host: str, port: int, out_dir: str, sim_seconds: float) -> int:
    os.makedirs(out_dir, exist_ok=True)
    client = connect(host, port)
    print(
        f"connected: server={client.get_server_version()} "
        f"client={client.get_client_version()}"
    )

    world = client.get_world()
    bp_lib = world.get_blueprint_library()
    spawn_points = world.get_map().get_spawn_points()
    if not spawn_points:
        print("FAIL — current map has no spawn points", file=sys.stderr)
        return 1

    vehicle_bp = bp_lib.filter("vehicle.tesla.model3")[0]
    vehicle = world.spawn_actor(vehicle_bp, spawn_points[0])

    cam_bp = bp_lib.find("sensor.camera.rgb")
    cam_bp.set_attribute("image_size_x", "800")
    cam_bp.set_attribute("image_size_y", "600")
    chase_transform = carla.Transform(
        carla.Location(x=-5.0, z=3.0), carla.Rotation(pitch=-15.0)
    )
    camera = world.spawn_actor(cam_bp, chase_transform, attach_to=vehicle)

    last = {"img": None}
    camera.listen(lambda img: last.update(img=img))

    try:
        with synchronous_mode(client, dt=0.05) as (world, tm):
            vehicle.set_autopilot(True, tm.get_port())
            ticks = int(round(sim_seconds / 0.05))
            for _ in range(ticks):
                world.tick()

        if last["img"] is None:
            print("FAIL — no frame received from camera", file=sys.stderr)
            return 1

        out_path = os.path.join(out_dir, "smoke_test.png")
        last["img"].save_to_disk(out_path)
        print(f"OK — wrote {out_path} ({last['img'].width}x{last['img'].height})")
        return 0
    finally:
        try:
            camera.stop()
        except Exception:
            pass
        camera.destroy()
        vehicle.destroy()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=2000)
    p.add_argument("--out", default="./out")
    p.add_argument("--seconds", type=float, default=5.0)
    args = p.parse_args()
    sys.exit(run(args.host, args.port, args.out, args.seconds))
