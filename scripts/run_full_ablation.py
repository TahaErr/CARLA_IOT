"""Sprint 5 FINAL ablation — one-command, seed-splittable orchestrator.

Runs the three communication arms (Combined / V2I-only / V2V-only) over the
full matrix below, for whichever seeds this machine is assigned. Two people
split the seeds and each run this once:

    Doruk:  python scripts/run_full_ablation.py --seeds 0,1 \
                --detector runs/detect/runs/detect/yolo26s_carla_multi-2/weights/best.pt \
                --carla-exe "C:/Users/<you>/Desktop/CARLA_0.9.16/CarlaUE4.exe"

    Taha:   python scripts/run_full_ablation.py --seeds 2,3 \
                --detector runs/detect/runs/detect/yolo26s_carla_multi-2/weights/best.pt \
                --carla-exe "C:/.../CarlaUE4.exe"

Fixed matrix (do not change between runners, or results won't merge):
    arms        : combined (V2X+V2V) | v2i_only (--no-v2v) | v2v_only (--no-v2x)
    penetrations: 0.0, 0.5, 0.9, 1.0
    maps        : Town01, Town05, Town10HD_Opt
    weathers    : ClearNoon, HardRainNoon
    duration    : 90 s   | dt 0.05 (20 Hz) | CPM/V2V 100 ms (10 Hz)
    population  : 60 vehicles + 60 walkers | HDV mix = hostile (v2 realism model)

Per runner: 3 maps x 2 weather x len(seeds) x 4 pen = 48 cells/arm x 3 arms.
For a 2-seed split that is 144 cells. Cell filenames carry sNN, so the two
runners' output folders drop straight together for aggregation.

CARLA (CarlaUE4.exe) must be running at --quality-level=Epic before launch.
Pass --carla-exe so the per-cell watchdog can relaunch it if it dies overnight.

Resumable: re-running with the same args skips finished cells (--skip-existing).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

# --- fixed experiment matrix (shared across both runners) ------------------
ARMS = [
    ("combined", []),               # V2X + V2V (default)
    ("v2i_only", ["--no-v2v"]),     # RSU CPM only, no CAV<->CAV
    ("v2v_only", ["--no-v2x"]),     # CAV<->CAV only, no RSU CPM
]
MAPS = "Town01,Town05,Town10HD_Opt"
WEATHERS = "ClearNoon,HardRainNoon"
PENETRATIONS = "0.0,0.5,0.9,1.0"
N_VEHICLES = "60"
WALKER_COUNTS = "60"
DT = "0.05"
CPM_PERIOD_MS = "100"
HDV_MIX = "hostile"
CELL_RETRIES = "2"


def main() -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    p = argparse.ArgumentParser(description="Sprint 5 final 3-arm ablation orchestrator")
    p.add_argument("--seeds", required=True,
                   help="This machine's seeds, comma-separated (e.g. '0,1' or '2,3').")
    p.add_argument("--detector", required=True, help="YOLO weights .pt path")
    p.add_argument("--carla-exe", default=None,
                   help="Path to CarlaUE4.exe for the overnight server watchdog.")
    p.add_argument("--out-root", default="out/ablation_sprint5_final",
                   help="Root output dir; one subfolder per arm.")
    p.add_argument("--duration", type=float, default=90.0)
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--dry-run", action="store_true",
                   help="Print the three arm commands and exit (no runs).")
    args = p.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    sweep = os.path.join(here, "42_ablation_sweep_subprocess.py")
    if not os.path.isfile(sweep):
        print(f"FAIL - sweep script not found: {sweep}", file=sys.stderr)
        return 1
    if not args.dry_run and not os.path.isfile(args.detector):
        print(f"FAIL - detector not found: {args.detector}", file=sys.stderr)
        return 1

    seed_list = [s.strip() for s in args.seeds.split(",") if s.strip()]
    print("=" * 70)
    print("Sprint 5 FINAL ablation")
    print(f"  seeds       : {seed_list}")
    print(f"  arms        : {[a for a, _ in ARMS]}")
    print(f"  penetrations: {PENETRATIONS}")
    print(f"  maps        : {MAPS}")
    print(f"  weathers    : {WEATHERS}")
    print(f"  duration    : {args.duration:.0f} s | dt {DT} | CPM {CPM_PERIOD_MS} ms")
    print(f"  population  : {N_VEHICLES} veh + {WALKER_COUNTS} walkers | hdv-mix {HDV_MIX}")
    cells_per_arm = 3 * 2 * len(seed_list) * 4
    print(f"  cells       : {cells_per_arm}/arm x {len(ARMS)} arms = {cells_per_arm * len(ARMS)} total")
    print(f"  out-root    : {args.out_root}")
    print("=" * 70)

    rc_total = 0
    for arm, flags in ARMS:
        out_dir = os.path.join(args.out_root, arm)
        cmd = [
            args.python, sweep,
            "--detector", args.detector,
            "--maps", MAPS,
            "--weathers", WEATHERS,
            "--penetrations", PENETRATIONS,
            "--seeds", args.seeds,
            "--walker-counts", WALKER_COUNTS,
            "--n-vehicles", N_VEHICLES,
            "--duration", str(args.duration),
            "--dt", DT,
            "--cpm-period-ms", CPM_PERIOD_MS,
            "--hdv-mix", HDV_MIX,
            "--cell-retries", CELL_RETRIES,
            "--skip-existing",
            "--out-dir", out_dir,
        ] + flags
        if args.carla_exe:
            cmd += ["--carla-exe", args.carla_exe]

        print(f"\n{'#' * 70}\n# ARM: {arm}  ->  {out_dir}\n{'#' * 70}")
        print(" ".join(cmd))
        if args.dry_run:
            continue
        rc = subprocess.run(cmd).returncode
        print(f"# ARM {arm} finished (rc={rc})")
        if rc != 0:
            rc_total = rc  # keep going; some cells may have crashed but others are fine

    print(f"\n=== ALL ARMS DONE for seeds {seed_list} (rc={rc_total}) ===")
    print(f"Aggregate each arm with:  python scripts/41_ablation_aggregate.py --in-dir {args.out_root}/<arm>")
    return rc_total


if __name__ == "__main__":
    sys.exit(main())
