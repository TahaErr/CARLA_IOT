"""scripts/42_ablation_sweep_subprocess.py — process-isolated ablation sweep.

The bisect work in scripts/31..33 confirmed that a single 120-second
run with 3 RSUs / 40 vehicles / 20 CAVs runs cleanly under CARLA
0.9.16 — but the original sweep in 40_ablation_run.py (which loops
inside one Python process) crashes between cells. The CARLA backend
accumulates actor handles and sync-mode state across runs that no
amount of in-process cleanup fully releases.

This wrapper sidesteps the issue by spawning a fresh Python process
per cell:

    for each (penetration, seed):
        subprocess.run("python 40_ablation_run.py --penetration ... --seed ... --out ...")
        # Python interpreter exits cleanly → CARLA client objects GC'd
        # → CARLA server is reconnected fresh by the next subprocess.

Crash isolation: if one cell crashes, the wrapper logs it and moves
on. Resume on partial completion via --skip-existing.

Usage:
    python scripts\\42_ablation_sweep_subprocess.py ^
        --detector runs\\detect\\runs\\detect\\yolo26s_carla_multi-2\\weights\\best.pt ^
        --out-dir out\\ablation

The CARLA server (`CarlaUE4.exe`) must be running and stay running
through the whole sweep. We only restart the Python *client* per cell.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--detector", required=True)
    p.add_argument("--out-dir", default="out/ablation")
    p.add_argument("--n-seeds", type=int, default=5)
    p.add_argument("--duration", type=float, default=120.0)
    p.add_argument("--n-vehicles", type=int, default=60)
    p.add_argument("--walker-counts", default="0,60,120",
                   help="Comma-separated walker counts. Default '0,60,120' = "
                        "medium scenario (map-wide pedestrian distribution, NHTSA-realistic "
                        "urban density). Override to '0' for vehicle-only sweep, or to "
                        "'60' to fix the walker axis while sweeping weather.")
    p.add_argument("--weathers", default="ClearNoon",
                   help="Comma-separated CARLA weather presets. Default 'ClearNoon' "
                        "(single value = no weather sweep). For the weather ablation "
                        "use 'ClearNoon,ClearSunset,HardRainNoon' — the three-preset "
                        "axis recommended in v2xsim/weather.py.")
    p.add_argument("--maps", default="Town05",
                   help="Comma-separated CARLA map names. Default 'Town05' (single value "
                        "= no map sweep). For the cross-map generalisation ablation use "
                        "'Town05,Town10HD_Opt' — primary fine-tune map + downtown "
                        "out-of-distribution map.")
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--python", default=sys.executable,
                   help="Python interpreter to use for subprocesses")
    p.add_argument("--runner", default="scripts/40_ablation_run.py",
                   help="path to the single-run runner script")
    args = p.parse_args()

    if not os.path.isfile(args.runner):
        print(f"FAIL — runner not found: {args.runner}", file=sys.stderr)
        return 1
    if not os.path.isfile(args.detector):
        print(f"FAIL — detector not found: {args.detector}", file=sys.stderr)
        return 1

    try:
        walker_counts = [int(x.strip()) for x in args.walker_counts.split(",") if x.strip()]
    except ValueError:
        print(f"FAIL — --walker-counts must be comma-separated integers, got: {args.walker_counts}",
              file=sys.stderr)
        return 1
    if not walker_counts:
        walker_counts = [0]

    weathers = [w.strip() for w in args.weathers.split(",") if w.strip()]
    if not weathers:
        weathers = ["ClearNoon"]

    maps = [m.strip() for m in args.maps.split(",") if m.strip()]
    if not maps:
        maps = ["Town05"]

    os.makedirs(args.out_dir, exist_ok=True)
    log_dir = os.path.join(args.out_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    penetrations = [0.0, 0.5, 1.0]
    seeds = list(range(args.n_seeds))
    total = (len(maps) * len(penetrations) * len(seeds)
             * len(walker_counts) * len(weathers))
    done = 0
    crashed = 0
    skipped = 0

    # Cell naming strategy: omit single-value axes from the filename so
    # legacy sweeps keep their `pNNN_sNN.json` names. Multi-value axes
    # are embedded in cell-name order: penetration, walkers, weather, map, seed.
    walker_in_name = not (len(walker_counts) == 1 and walker_counts[0] == 0)
    weather_in_name = len(weathers) > 1
    map_in_name = len(maps) > 1

    print(f"=== Subprocess sweep: {len(maps)} maps × {len(weathers)} weather × "
          f"{len(walker_counts)} walker-counts × {len(penetrations)} penetration × "
          f"{len(seeds)} seeds = {total} cells of {args.duration:.0f}s each ===")
    print(f"   maps:            {maps}")
    print(f"   weather presets: {weathers}")
    print(f"   walker counts:   {walker_counts}")
    print(f"   runner: {args.runner}")
    print(f"   python: {args.python}")
    print(f"   logs:   {log_dir}\\")
    sweep_t0 = time.time()

    # Loop order: map (outermost — switching maps is expensive, batch them),
    # then weather, walker, penetration, seed (innermost).
    for map_name in maps:
        for weather in weathers:
            for n_walkers in walker_counts:
                for p_value in penetrations:
                    for seed in seeds:
                        done += 1
                        parts = [f"p{int(p_value * 100):03d}"]
                        if walker_in_name:
                            parts.append(f"w{n_walkers:03d}")
                        if weather_in_name:
                            parts.append(weather)
                        if map_in_name:
                            parts.append(map_name)
                        parts.append(f"s{seed:02d}")
                        cell_name = "_".join(parts)
                        out_path = os.path.join(args.out_dir, f"{cell_name}.json")
                        log_path = os.path.join(log_dir, f"{cell_name}.log")

                        if args.skip_existing and os.path.exists(out_path):
                            print(f"[{done}/{total}] SKIP existing: {out_path}")
                            skipped += 1
                            continue

                        print(f"\n[{done}/{total}] === subprocess: p={p_value} "
                              f"walkers={n_walkers} weather={weather} map={map_name} "
                              f"seed={seed} → {out_path}")
                        cmd = [
                            args.python, args.runner,
                            "--detector", args.detector,
                            "--penetration", str(p_value),
                            "--seed", str(seed),
                            "--duration", str(args.duration),
                            "--n-vehicles", str(args.n_vehicles),
                            "--n-walkers", str(n_walkers),
                            "--weather", weather,
                            "--map", map_name,
                            "--out", out_path,
                            "--quiet",
                        ]
                        cell_t0 = time.time()
                        try:
                            with open(log_path, "w", encoding="utf-8") as log_f:
                                result = subprocess.run(
                                    cmd,
                                    stdout=log_f, stderr=subprocess.STDOUT,
                                    timeout=args.duration * 4.0 + 60.0,
                                )
                            cell_wall = time.time() - cell_t0
                            if result.returncode == 0 and os.path.exists(out_path):
                                print(f"   ok   ({cell_wall:.0f}s wall)  log: {log_path}")
                            else:
                                crashed += 1
                                print(f"   FAIL ({cell_wall:.0f}s wall, rc={result.returncode})  "
                                      f"log: {log_path}", file=sys.stderr)
                        except subprocess.TimeoutExpired:
                            crashed += 1
                            cell_wall = time.time() - cell_t0
                            print(f"   TIMEOUT ({cell_wall:.0f}s wall)  log: {log_path}",
                                  file=sys.stderr)
                        except Exception as e:
                            crashed += 1
                            print(f"   ERROR: {e}", file=sys.stderr)

    elapsed = time.time() - sweep_t0
    print(f"\n=== Subprocess sweep complete in {elapsed/60:.1f} min ===")
    print(f"   ok:      {done - crashed - skipped}/{total}")
    print(f"   crashed: {crashed}")
    print(f"   skipped: {skipped}")
    print(f"\nNext: python scripts\\41_ablation_aggregate.py --in-dir {args.out_dir}")
    return 0 if crashed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
