#!/usr/bin/env python3
"""apply_patches.py — Sprint 4 p=0.9 fleet-transition extension patches.

Applies minimal modifications to two existing scripts so a new
`--cav-attentive` flag becomes available:

  scripts/40_ablation_run.py
    1. Import ATTENTIVE + apply_profile_to_tm from v2xsim.hdv.
    2. Add --cav-attentive argparse flag.
    3. After CAV spawn loop, override CAV TM driving from HOSTILE_MIX
       to ATTENTIVE when --cav-attentive is set.
    4. Log cav_attentive flag into metrics["config"] for traceability.

  scripts/42_ablation_sweep_subprocess.py
    1. Add --penetrations argparse flag (defaults to "0.0,0.5,1.0").
    2. Replace hardcoded penetrations=[0.0,0.5,1.0] with the parsed list.
    3. Add --cav-attentive flag and pass it through to each child run.

Run from repo root:
    python apply_patches.py

Idempotent: re-running is safe; each patch detects whether it has been
applied and skips. Reports per-patch status.
"""
from __future__ import annotations

import os
import sys


# === Helpers ==============================================================

def patch_file(path: str, edits: list[tuple[str, str, str, str]]) -> int:
    """Apply a list of (label, marker, old, new) edits to a file.

    For each edit:
      - If `new` is already in the file → skip (already applied).
      - Else if `old` is in the file → replace with `new`.
      - Else → fail loudly (file shape doesn't match expected).

    Returns 0 on success, non-zero on failure.
    """
    if not os.path.isfile(path):
        print(f"FAIL — file not found: {path}", file=sys.stderr)
        return 1

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    changed = False
    for label, marker, old, new in edits:
        # Idempotency: if the unique marker for the new content is already
        # present, this edit has been applied before.
        if marker in src:
            print(f"  [skip]    {label}  (marker already present)")
            continue
        if old not in src:
            print(f"FAIL — {label}: expected old fragment not found in {path}",
                  file=sys.stderr)
            print(f"       old[:120]={old[:120]!r}", file=sys.stderr)
            return 2
        # Replace first occurrence only (safer).
        src = src.replace(old, new, 1)
        changed = True
        print(f"  [applied] {label}")

    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
        print(f"  → wrote {path}")
    else:
        print(f"  → {path} unchanged (all patches already applied)")
    return 0


# === scripts/40_ablation_run.py ==========================================

PATCH_40_EDITS = [
    # -----------------------------------------------------------------
    # 1. Expand imports from v2xsim.hdv
    # -----------------------------------------------------------------
    (
        "import-attentive-and-apply-profile",
        "from v2xsim.hdv import (\n    ATTENTIVE,",  # idempotency marker
        # OLD (single-line import):
        "from v2xsim.hdv import HOSTILE_MIX, apply_mix_to_vehicles, disable_tm_collision_detection",
        # NEW (multi-line import, adds ATTENTIVE + apply_profile_to_tm):
        "from v2xsim.hdv import (\n"
        "    ATTENTIVE,\n"
        "    HOSTILE_MIX,\n"
        "    apply_mix_to_vehicles,\n"
        "    apply_profile_to_tm,\n"
        "    disable_tm_collision_detection,\n"
        ")",
    ),
    # -----------------------------------------------------------------
    # 2. Add --cav-attentive argparse flag (right after --quiet)
    # -----------------------------------------------------------------
    (
        "argparse-cav-attentive-flag",
        '"--cav-attentive"',  # idempotency marker
        # OLD: the --quiet line stands alone in the argparse block.
        '    p.add_argument("--quiet", action="store_true")\n',
        # NEW: add --cav-attentive immediately after --quiet.
        '    p.add_argument("--quiet", action="store_true")\n'
        '    p.add_argument("--cav-attentive", action="store_true",\n'
        '                   help="Fleet-transition mode: override CAV TM driving from "\n'
        '                        "HOSTILE_MIX to ATTENTIVE. HDVs remain on HOSTILE_MIX. "\n'
        '                        "Use for p=0.9 fleet-transition sweep.")\n',
    ),
    # -----------------------------------------------------------------
    # 3. Override CAV driving with ATTENTIVE after CAV spawn loop
    # -----------------------------------------------------------------
    (
        "override-cav-tm-driving-attentive",
        "[fleet-transition] ATTENTIVE applied",  # idempotency marker
        # OLD: end of the CAV spawn loop, immediately before "Walkers" block.
        "                cavs.append(cav)\n"
        "                cav_actor_ids.add(v.id)\n"
        "\n"
        "            # === Walkers (pedestrians, optional VRU axis) ============",
        # NEW: insert the ATTENTIVE override block between the two markers.
        "                cavs.append(cav)\n"
        "                cav_actor_ids.add(v.id)\n"
        "\n"
        "            # === Fleet-transition mode: override CAV TM driving =======\n"
        "            # HDVs keep their HOSTILE_MIX assignment from earlier; only\n"
        "            # CAV vehicles get ATTENTIVE driving on top of their CAV layer.\n"
        "            # Conceptually: p=0.9 with --cav-attentive == 90% attentive CAV\n"
        "            # + 10% HOSTILE HDV (50/20/30 mix). The CAV layer (CPM listening,\n"
        "            # hysteresis, TTC ladder, brake decisions) stays active.\n"
        "            if args.cav_attentive and cav_vehicles:\n"
        "                for v in cav_vehicles:\n"
        "                    apply_profile_to_tm(tm, v, ATTENTIVE)\n"
        "                n_hdvs = len(vehicles) - len(cav_vehicles)\n"
        "                if not args.quiet:\n"
        "                    print(f\"   [fleet-transition] ATTENTIVE applied to \"\n"
        "                          f\"{len(cav_vehicles)} CAV(s); {n_hdvs} HDV(s) remain on HOSTILE_MIX\")\n"
        "\n"
        "            # === Walkers (pedestrians, optional VRU axis) ============",
    ),
    # -----------------------------------------------------------------
    # 4. Log cav_attentive flag into metrics["config"] (single-run path)
    # -----------------------------------------------------------------
    (
        "log-cav-attentive-into-metrics",
        'metrics.setdefault("config", {})["cav_attentive"]',  # idempotency marker
        # OLD: after the successful single-run, status is tagged "ok".
        '    print(f"=== Single run: penetration={args.penetration} seed={args.seed}")\n'
        "    try:\n"
        "        metrics = run_single(args, penetration=args.penetration, seed=args.seed)\n"
        '        metrics["status"] = "ok"\n',
        # NEW: also stamp the cav_attentive flag for downstream traceability.
        '    print(f"=== Single run: penetration={args.penetration} seed={args.seed}")\n'
        "    try:\n"
        "        metrics = run_single(args, penetration=args.penetration, seed=args.seed)\n"
        '        metrics["status"] = "ok"\n'
        '        metrics.setdefault("config", {})["cav_attentive"] = args.cav_attentive\n',
    ),
]


# === scripts/42_ablation_sweep_subprocess.py =============================

PATCH_42_EDITS = [
    # -----------------------------------------------------------------
    # 1. Add --penetrations and --cav-attentive argparse flags
    # -----------------------------------------------------------------
    (
        "argparse-penetrations-and-cav-attentive",
        '"--penetrations"',  # idempotency marker
        # OLD: --skip-existing flag standalone.
        '    p.add_argument("--skip-existing", action="store_true")\n',
        # NEW: add --penetrations + --cav-attentive right before --skip-existing.
        '    p.add_argument("--penetrations", default="0.0,0.5,1.0",\n'
        '                   help="Comma-separated penetration values to sweep. "\n'
        '                        "Default \'0.0,0.5,1.0\'. Override to \'0.9\' for the "\n'
        '                        "fleet-transition extension sweep (45 cells).")\n'
        '    p.add_argument("--cav-attentive", action="store_true",\n'
        '                   help="Pass --cav-attentive to each child run "\n'
        '                        "(CAVs get ATTENTIVE driving; HDVs stay on HOSTILE_MIX). "\n'
        '                        "Use together with --penetrations 0.9 for the fleet-transition sweep.")\n'
        '    p.add_argument("--skip-existing", action="store_true")\n',
    ),
    # -----------------------------------------------------------------
    # 2. Replace hardcoded penetrations list with the parsed argument
    # -----------------------------------------------------------------
    (
        "parse-penetrations-from-args",
        "penetrations = [float(x.strip()) for x in args.penetrations.split",  # idempotency marker
        # OLD: hardcoded list of three floats.
        "    penetrations = [0.0, 0.5, 1.0]\n"
        "    seeds = list(range(args.n_seeds))\n",
        # NEW: parse from --penetrations argument with validation.
        "    try:\n"
        "        penetrations = [float(x.strip()) for x in args.penetrations.split(\",\") if x.strip()]\n"
        "    except ValueError:\n"
        '        print(f"FAIL — --penetrations must be comma-separated floats, got: {args.penetrations}",\n'
        "              file=sys.stderr)\n"
        "        return 1\n"
        "    if not penetrations:\n"
        "        penetrations = [0.0, 0.5, 1.0]\n"
        "    seeds = list(range(args.n_seeds))\n",
    ),
    # -----------------------------------------------------------------
    # 3. Pass --cav-attentive through to each subprocess child run
    # -----------------------------------------------------------------
    (
        "pass-cav-attentive-to-subprocess",
        'if args.cav_attentive:\n                            cmd.append("--cav-attentive")',  # idempotency marker
        # OLD: end of the cmd list, before subprocess.run.
        '                            "--out", out_path,\n'
        '                            "--quiet",\n'
        '                        ]\n'
        '                        cell_t0 = time.time()\n',
        # NEW: append --cav-attentive conditionally after the cmd list is built.
        '                            "--out", out_path,\n'
        '                            "--quiet",\n'
        '                        ]\n'
        '                        if args.cav_attentive:\n'
        '                            cmd.append("--cav-attentive")\n'
        '                        cell_t0 = time.time()\n',
    ),
]


# === Main =================================================================

def main() -> int:
    repo_root = os.path.abspath(os.path.dirname(__file__) or ".")
    print(f"Repo root: {repo_root}\n")

    targets = [
        ("scripts/40_ablation_run.py",            PATCH_40_EDITS),
        ("scripts/42_ablation_sweep_subprocess.py", PATCH_42_EDITS),
    ]

    rc = 0
    for rel_path, edits in targets:
        abs_path = os.path.join(repo_root, rel_path)
        print(f"=== Patching {rel_path}")
        result = patch_file(abs_path, edits)
        if result != 0:
            rc = result
            print(f"   STOPPED on error in {rel_path}\n")
            break
        print()

    if rc == 0:
        print("=== All patches applied (or already present). ===")
        print()
        print("Run the p=0.9 fleet-transition sweep next:")
        print()
        print("  python scripts\\42_ablation_sweep_subprocess.py ^")
        print("    --detector runs\\detect\\runs\\detect\\yolo26s_carla_multi-2\\weights\\best.pt ^")
        print("    --out-dir out\\ablation_p09 ^")
        print("    --walker-counts 60 ^")
        print("    --weathers \"ClearNoon,ClearSunset,HardRainNoon\" ^")
        print("    --maps \"Town05,Town10HD_Opt,Town01\" ^")
        print("    --penetrations \"0.9\" ^")
        print("    --cav-attentive ^")
        print("    --skip-existing")
        print()
        print("Then aggregate:")
        print("  python scripts\\41_ablation_aggregate.py --in-dir out\\ablation_p09")
    return rc


if __name__ == "__main__":
    sys.exit(main())
