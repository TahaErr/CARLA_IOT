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
import itertools
import os
import socket
import subprocess
import sys
import time


def main() -> int:
    # Force UTF-8 console output. Under Windows' default cp1252 codepage,
    # printing the non-ASCII chars in our status lines (→, ×, —) raises
    # UnicodeEncodeError as soon as stdout is a pipe/file (i.e. every time
    # this sweep is launched in the background). Reconfiguring sidesteps it.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

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
    p.add_argument("--penetrations", default="0.0,0.5,1.0",
                   help="Comma-separated penetration values to sweep. "
                        "Default '0.0,0.5,1.0'. Override to '0.9' for the "
                        "fleet-transition extension sweep (45 cells).")
    p.add_argument("--cav-attentive", action="store_true",
                   help="Pass --cav-attentive to each child run "
                        "(CAVs get ATTENTIVE driving; HDVs stay on HOSTILE_MIX). "
                        "Use together with --penetrations 0.9 for the fleet-transition sweep.")
    p.add_argument("--hdv-mix", choices=["hostile", "default"], default="hostile",
                   help="Pass --hdv-mix to each child run.")
    p.add_argument("--no-v2v", action="store_true",
                   help="Pass --no-v2v to each child run (V2I-only arm: CAVs keep "
                        "RSU CPMs + local sensor but no CAV↔CAV V2V). Use to run the "
                        "V2V-isolation phase into a separate --out-dir.")
    p.add_argument("--no-v2x", action="store_true",
                   help="Pass --no-v2x to each child run (V2V-only arm: CAVs keep V2V but no RSU CPMs).")
    p.add_argument("--cpm-period-ms", type=float, default=100.0,
                   help="Pass-through CPM/V2V broadcast period in ms (default 100 = 10 Hz).")
    p.add_argument("--dt", type=float, default=0.05,
                   help="Pass-through fixed simulation timestep in s (default 0.05 = 20 Hz).")
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--max-hours", type=float, default=0.0,
                   help="Wall-clock budget in hours. When exceeded, the sweep "
                        "stops launching new cells and exits gracefully (0 = no "
                        "limit). Combine with --skip-existing to resume later.")
    p.add_argument("--deadline-epoch", type=float, default=0.0,
                   help="Absolute Unix time to stop launching new cells by "
                        "(0 = none). Shared across multiple sweep invocations so "
                        "a multi-phase orchestration honours one global budget.")
    p.add_argument("--cell-timeout-s", type=float, default=0.0,
                   help="Hard per-cell wall timeout in seconds (0 = auto = "
                        "max(900, duration*5+120)). Heavy full-penetration cells "
                        "on dense maps can need >600 s at max fidelity.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=2000)
    p.add_argument("--carla-exe", default=None,
                   help="Path to CarlaUE4.exe. If set, a watchdog restarts the "
                        "server when several cells fail in a row and the port is "
                        "down (overnight resilience).")
    p.add_argument("--restart-after-fails", type=int, default=3,
                   help="Consecutive cell failures before the watchdog checks/"
                        "restarts the CARLA server (default 3).")
    p.add_argument("--cell-retries", type=int, default=2,
                   help="Extra attempts per cell on failure (default 2 = up to "
                        "3 tries). Transient CARLA map-load/spawn crashes leave a "
                        "0-byte log and no JSON; a retry recovers them so a sweep "
                        "finishes with no gaps. Between attempts the server health "
                        "is checked (and restarted if --carla-exe was given).")
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

    try:
        penetrations = [float(x.strip()) for x in args.penetrations.split(",") if x.strip()]
    except ValueError:
        print(f"FAIL — --penetrations must be comma-separated floats, got: {args.penetrations}",
              file=sys.stderr)
        return 1
    if not penetrations:
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

    deadline = sweep_t0 + args.max_hours * 3600.0 if args.max_hours > 0 else None
    if args.deadline_epoch > 0:
        deadline = (args.deadline_epoch if deadline is None
                    else min(deadline, args.deadline_epoch))
    cell_timeout = (args.cell_timeout_s if args.cell_timeout_s > 0
                    else max(900.0, args.duration * 5.0 + 120.0))

    def _carla_up() -> bool:
        try:
            with socket.create_connection((args.host, args.port), timeout=3.0):
                return True
        except OSError:
            return False

    def _try_restart_carla() -> bool:
        """Best-effort: if the server port is down, relaunch CarlaUE4.exe and
        wait for it to come back. No-op unless --carla-exe was given."""
        if not args.carla_exe or not os.path.isfile(args.carla_exe):
            return False
        if _carla_up():
            return True  # server fine; failures were client-side
        print(f"   [watchdog] CARLA port {args.port} down — relaunching server",
              file=sys.stderr)
        try:
            subprocess.Popen([args.carla_exe, "-quality-level=Epic"],
                             cwd=os.path.dirname(args.carla_exe) or None)
        except Exception as e:
            print(f"   [watchdog] relaunch failed: {e}", file=sys.stderr)
            return False
        for _ in range(60):                 # up to ~3 min for boot
            time.sleep(3.0)
            if _carla_up():
                time.sleep(15.0)            # let maps/assets warm up
                print("   [watchdog] CARLA back online", file=sys.stderr)
                return True
        print("   [watchdog] CARLA did not return in time", file=sys.stderr)
        return False

    # Flat cell list. Order: map → weather → walker → penetration → seed,
    # matching the historical naming so --skip-existing resumes cleanly.
    cells = list(itertools.product(maps, weathers, walker_counts, penetrations, seeds))
    consecutive_fail = 0
    for (map_name, weather, n_walkers, p_value, seed) in cells:
        done += 1
        if deadline is not None and time.time() > deadline:
            print(f"\n[{done}/{total}] DEADLINE reached ({args.max_hours:.2f} h) "
                  f"— stopping; rerun with --skip-existing to finish.")
            break

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
            "--cpm-period-ms", str(args.cpm_period_ms),
            "--dt", str(args.dt),
            "--out", out_path,
            "--quiet",
        ]
        if args.cav_attentive:
            cmd.append("--cav-attentive")
        if args.no_v2v:
            cmd.append("--no-v2v")
        if args.no_v2x:
            cmd.append("--no-v2x")
        cmd.extend(["--hdv-mix", args.hdv_mix])
        cell_ok = False
        attempts = max(1, args.cell_retries + 1)
        for attempt in range(1, attempts + 1):
            cell_t0 = time.time()
            try:
                with open(log_path, "w", encoding="utf-8") as log_f:
                    result = subprocess.run(
                        cmd,
                        stdout=log_f, stderr=subprocess.STDOUT,
                        timeout=cell_timeout,
                    )
                cell_wall = time.time() - cell_t0
                if result.returncode == 0 and os.path.exists(out_path):
                    tag = "ok  " if attempt == 1 else f"ok (retry {attempt-1})"
                    print(f"   {tag} ({cell_wall:.0f}s wall)  log: {log_path}")
                    cell_ok = True
                    break
                reason = f"rc={result.returncode}, json={'yes' if os.path.exists(out_path) else 'no'}"
            except subprocess.TimeoutExpired:
                cell_wall = time.time() - cell_t0
                reason = "TIMEOUT"
            except Exception as e:
                cell_wall = time.time() - cell_t0
                reason = f"ERROR: {e}"

            if attempt < attempts:
                print(f"   FAIL attempt {attempt}/{attempts} ({cell_wall:.0f}s wall, "
                      f"{reason}) — retrying  log: {log_path}", file=sys.stderr)
                # A failed attempt often means the server hiccuped on the map
                # load/spawn. Check the port (restart if --carla-exe) before retry.
                if not _carla_up():
                    _try_restart_carla()
                else:
                    time.sleep(3.0)  # brief settle; lets stale streams drain
            else:
                crashed += 1
                print(f"   FAIL ({cell_wall:.0f}s wall, {reason}) after {attempts} "
                      f"attempts  log: {log_path}", file=sys.stderr)

        # Watchdog: a run of consecutive failures usually means the CARLA
        # server died. Check the port and relaunch if --carla-exe was given.
        if cell_ok:
            consecutive_fail = 0
        else:
            consecutive_fail += 1
            if consecutive_fail >= args.restart_after_fails:
                if _try_restart_carla():
                    consecutive_fail = 0

    elapsed = time.time() - sweep_t0
    print(f"\n=== Subprocess sweep complete in {elapsed/60:.1f} min ===")
    print(f"   ok:      {done - crashed - skipped}/{total}")
    print(f"   crashed: {crashed}")
    print(f"   skipped: {skipped}")
    print(f"\nNext: python scripts\\41_ablation_aggregate.py --in-dir {args.out_dir}")
    return 0 if crashed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
