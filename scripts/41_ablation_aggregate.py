"""scripts/41_ablation_aggregate.py — Sprint 4 Module 5b.

Reads every `pNNN_sNN.json` cell file produced by 40_ablation_run.py
(via the subprocess sweep 42_ablation_sweep_subprocess.py) and emits:

  - `summary.csv`           : one row per cell, all metrics flat
  - `summary_by_cell.csv`   : mean ± std per penetration cell
  - `figures/collisions_vs_penetration.png`    : main thesis figure
  - `figures/actions_vs_penetration.png`       : CAV action histogram per p
  - `figures/phantom_brakes_vs_penetration.png`: hysteresis contribution

Usage:
    python scripts\\41_ablation_aggregate.py --in-dir out\\ablation

Crashed cells (status != "ok") are listed in stderr and excluded from
aggregation, so a partially-completed sweep still produces a usable
summary. No CARLA dependency.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from collections import defaultdict

try:
    import matplotlib
    matplotlib.use("Agg")  # headless backend; no display required
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


def _flatten_cell(metrics: dict) -> dict:
    """Convert one cell's nested JSON to a flat row for CSV / aggregation."""
    cfg = metrics.get("config", {})
    actions = metrics.get("actions_taken", {})
    profiles = metrics.get("collisions_per_profile", {})
    return {
        "penetration":           cfg.get("penetration"),
        "seed":                  cfg.get("seed"),
        "n_vehicles":            cfg.get("n_vehicles"),
        "n_cavs":                cfg.get("n_cavs"),
        "duration_s":            cfg.get("duration_s"),
        "wall_seconds":          metrics.get("wall_seconds"),
        "wall_to_sim_ratio":     metrics.get("wall_to_sim_ratio"),
        "collision_count":       metrics.get("collision_count", 0),
        "raw_collision_events":  metrics.get("raw_collision_events", 0),
        "cav_collision_count":   metrics.get("cav_collision_count", 0),
        "hdv_collision_count":   metrics.get("hdv_collision_count", 0),
        "action_none":           actions.get("none", 0),
        "action_decelerate":     actions.get("decelerate", 0),
        "action_soft_brake":     actions.get("soft_brake", 0),
        "action_hard_brake":     actions.get("hard_brake", 0),
        "phantom_brakes_suppressed": metrics.get("phantom_brakes_suppressed", 0),
        "dead_cav_count":        metrics.get("dead_cav_count", 0),
        "decode_errors":         metrics.get("decode_errors", 0),
        "publishes_emitted":     metrics.get("publishes_emitted", 0),
        "publishes_dropped":     metrics.get("publishes_dropped", 0),
        "cbr_mean":              metrics.get("cbr_mean", 0.0),
        "cbr_max":               metrics.get("cbr_max", 0.0),
        "coll_attentive":        profiles.get("attentive", 0),
        "coll_distracted":       profiles.get("distracted", 0),
        "coll_aggressive_hostile": profiles.get("aggressive_hostile", 0),
    }


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return mean, var ** 0.5


def _aggregate_by_penetration(rows: list[dict]) -> list[dict]:
    """Mean ± std for each penetration value, across seeds."""
    groups: dict[float, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["penetration"]].append(r)

    out = []
    metric_keys = [
        "collision_count", "cav_collision_count", "hdv_collision_count",
        "action_hard_brake", "action_soft_brake", "action_decelerate",
        "phantom_brakes_suppressed", "dead_cav_count",
        "cbr_mean", "wall_to_sim_ratio",
    ]
    for p in sorted(groups.keys()):
        cell_rows = groups[p]
        summary = {"penetration": p, "n_seeds": len(cell_rows)}
        for k in metric_keys:
            mean, std = _mean_std([r[k] for r in cell_rows])
            summary[f"{k}_mean"] = mean
            summary[f"{k}_std"] = std
        out.append(summary)
    return out


# === Figures ============================================================

def _figure_collisions_vs_penetration(by_pen: list[dict], out_path: str):
    """Main thesis figure: collision count by penetration rate."""
    fig, ax = plt.subplots(figsize=(7, 5))
    xs = [r["penetration"] for r in by_pen]
    total = [r["collision_count_mean"] for r in by_pen]
    total_e = [r["collision_count_std"] for r in by_pen]
    hdv = [r["hdv_collision_count_mean"] for r in by_pen]
    hdv_e = [r["hdv_collision_count_std"] for r in by_pen]
    cav = [r["cav_collision_count_mean"] for r in by_pen]
    cav_e = [r["cav_collision_count_std"] for r in by_pen]

    ax.errorbar(xs, total, yerr=total_e, marker="o", linewidth=2,
                capsize=4, label="Total")
    ax.errorbar(xs, hdv, yerr=hdv_e, marker="s", linewidth=1.5,
                capsize=4, label="HDV-involved")
    ax.errorbar(xs, cav, yerr=cav_e, marker="^", linewidth=1.5,
                capsize=4, label="CAV-involved")

    ax.set_xlabel("V2X penetration rate")
    ax.set_ylabel(f"Collisions per run "
                  f"({int(by_pen[0]['n_seeds']) if by_pen else '?'} seeds, "
                  f"mean ± std)")
    ax.set_title("Collisions vs. V2X penetration rate")
    ax.set_xticks([0.0, 0.5, 1.0])
    ax.set_xlim(-0.1, 1.1)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _figure_actions_vs_penetration(by_pen: list[dict], out_path: str):
    """Stacked-bar of CAV actions per penetration cell."""
    fig, ax = plt.subplots(figsize=(7, 5))
    xs = [r["penetration"] for r in by_pen]
    hard = [r["action_hard_brake_mean"] for r in by_pen]
    soft = [r["action_soft_brake_mean"] for r in by_pen]
    decel = [r["action_decelerate_mean"] for r in by_pen]

    width = 0.25
    ax.bar([x - width for x in xs], hard, width, label="Hard brake",
           color="#d62728")
    ax.bar(xs, soft, width, label="Soft brake", color="#ff7f0e")
    ax.bar([x + width for x in xs], decel, width, label="Decelerate",
           color="#2ca02c")

    ax.set_xlabel("V2X penetration rate")
    ax.set_ylabel("CAV actions per run (mean)")
    ax.set_title("CAV actions vs. V2X penetration rate")
    ax.set_xticks([0.0, 0.5, 1.0])
    ax.grid(True, alpha=0.3, axis="y")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _figure_phantom_brakes_vs_penetration(by_pen: list[dict], out_path: str):
    """Hysteresis contribution: phantom-brake-suppressed count per cell."""
    fig, ax = plt.subplots(figsize=(7, 5))
    xs = [r["penetration"] for r in by_pen]
    means = [r["phantom_brakes_suppressed_mean"] for r in by_pen]
    stds = [r["phantom_brakes_suppressed_std"] for r in by_pen]
    ax.errorbar(xs, means, yerr=stds, marker="o", linewidth=2,
                capsize=4, color="#9467bd")
    ax.set_xlabel("V2X penetration rate")
    ax.set_ylabel("Phantom brakes suppressed per run (mean ± std)")
    ax.set_title("Hysteresis contribution: phantom-brake suppression\n"
                 "(proposal §4.1.1 step 5)")
    ax.set_xticks([0.0, 0.5, 1.0])
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# === Main ===============================================================

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--in-dir", default="out/ablation")
    p.add_argument("--summary-csv", default=None,
                   help="path for per-cell CSV (default: {in_dir}/summary.csv)")
    p.add_argument("--by-cell-csv", default=None,
                   help="path for aggregated CSV (default: {in_dir}/summary_by_cell.csv)")
    p.add_argument("--figures-dir", default=None,
                   help="path for matplotlib figures (default: {in_dir}/figures)")
    args = p.parse_args()

    if not os.path.isdir(args.in_dir):
        print(f"FAIL — input directory missing: {args.in_dir}", file=sys.stderr)
        return 1

    pattern = os.path.join(args.in_dir, "p*_s*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"FAIL — no cell files match {pattern}", file=sys.stderr)
        return 1

    summary_csv = args.summary_csv or os.path.join(args.in_dir, "summary.csv")
    by_cell_csv = args.by_cell_csv or os.path.join(args.in_dir, "summary_by_cell.csv")
    figures_dir = args.figures_dir or os.path.join(args.in_dir, "figures")
    os.makedirs(figures_dir, exist_ok=True)

    rows: list[dict] = []
    crashed: list[str] = []
    for fp in files:
        try:
            with open(fp) as f:
                metrics = json.load(f)
        except Exception as e:
            print(f"   skip (unreadable): {fp}  ({e})", file=sys.stderr)
            crashed.append(fp)
            continue
        status = metrics.get("status", "unknown")
        if status != "ok":
            print(f"   skip ({status}): {os.path.basename(fp)}", file=sys.stderr)
            crashed.append(fp)
            continue
        rows.append(_flatten_cell(metrics))

    print(f"=== Aggregating {len(rows)} cells from {args.in_dir}")
    print(f"   crashed/skipped: {len(crashed)}")
    if not rows:
        print("FAIL — no usable cells", file=sys.stderr)
        return 1

    # === Per-cell CSV =================================================
    fieldnames = list(rows[0].keys())
    with open(summary_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"wrote {summary_csv} ({len(rows)} rows)")

    # === Aggregated by penetration ====================================
    by_pen = _aggregate_by_penetration(rows)
    if by_pen:
        fieldnames2 = list(by_pen[0].keys())
        with open(by_cell_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames2)
            w.writeheader()
            for r in by_pen:
                w.writerow(r)
        print(f"wrote {by_cell_csv} ({len(by_pen)} cells)")

    # === Figures ======================================================
    if HAS_MPL and by_pen:
        fig_collisions = os.path.join(figures_dir, "collisions_vs_penetration.png")
        fig_actions = os.path.join(figures_dir, "actions_vs_penetration.png")
        fig_phantom = os.path.join(figures_dir, "phantom_brakes_vs_penetration.png")
        _figure_collisions_vs_penetration(by_pen, fig_collisions)
        _figure_actions_vs_penetration(by_pen, fig_actions)
        _figure_phantom_brakes_vs_penetration(by_pen, fig_phantom)
        print(f"wrote {fig_collisions}")
        print(f"wrote {fig_actions}")
        print(f"wrote {fig_phantom}")
    elif not HAS_MPL:
        print("WARN — matplotlib not available, skipping figures", file=sys.stderr)

    # === Summary print to console =====================================
    print("\n=== Summary by penetration rate ===")
    print(f"{'p':>5}  {'n':>3}  {'collisions':>20}  {'hard_brake':>14}  "
          f"{'phantom':>10}")
    for r in by_pen:
        c = f"{r['collision_count_mean']:.1f} ± {r['collision_count_std']:.1f}"
        hb = f"{r['action_hard_brake_mean']:.0f} ± {r['action_hard_brake_std']:.0f}"
        ph = f"{r['phantom_brakes_suppressed_mean']:.1f}"
        print(f"{r['penetration']:5.2f}  {r['n_seeds']:3d}  {c:>20}  {hb:>14}  {ph:>10}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
