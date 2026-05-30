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
        "n_walkers":             cfg.get("n_walkers", 0),
        "weather":               cfg.get("weather", "ClearNoon"),
        "map":                   cfg.get("map", "Town05"),
        "duration_s":            cfg.get("duration_s"),
        "wall_seconds":          metrics.get("wall_seconds"),
        "wall_to_sim_ratio":     metrics.get("wall_to_sim_ratio"),
        "collision_count":       metrics.get("collision_count", 0),
        "raw_collision_events":  metrics.get("raw_collision_events", 0),
        "cav_collision_count":   metrics.get("cav_collision_count", 0),
        "hdv_collision_count":   metrics.get("hdv_collision_count", 0),
        "vru_collision_count":   metrics.get("vru_collision_count", 0),
        "cav_hit_pedestrian_count": metrics.get("cav_hit_pedestrian_count", 0),
        "hdv_hit_pedestrian_count": metrics.get("hdv_hit_pedestrian_count", 0),
        "action_none":           actions.get("none", 0),
        "action_decelerate":     actions.get("decelerate", 0),
        "action_soft_brake":     actions.get("soft_brake", 0),
        "action_hard_brake":     actions.get("hard_brake", 0),
        "phantom_brakes_suppressed": metrics.get("phantom_brakes_suppressed", 0),
        # Sprint 5 additions.
        "cooperative_brakes":    metrics.get("cooperative_brakes", 0),
        "frozen_vehicle_count":  metrics.get("frozen_vehicle_count", 0),
        "v2v_enabled":           cfg.get("v2v_enabled", True),
        "v2v_publishes_attempted": metrics.get("v2v_publishes_attempted", 0),
        "v2v_deliveries_emitted": metrics.get("v2v_deliveries_emitted", 0),
        "v2v_received_total":    metrics.get("v2v_received_total", 0),
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


def _aggregate_by_cell(rows: list[dict]) -> list[dict]:
    """Mean ± std for each (penetration, n_walkers_bucket, weather, map) cell, across seeds.

    Groups by the 4-tuple. Walker count is bucketed (see _bucket_walkers
    below) so that cells with the same requested walker count are grouped
    together even though CARLA's actual spawn yield varies cell-to-cell
    (e.g. requesting 60 may spawn 41..60 due to nav-mesh rejection).
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        key = (
            r["penetration"],
            _bucket_walkers(r.get("n_walkers", 0)),
            r.get("weather", "ClearNoon"),
            r.get("map", "Town05"),
        )
        groups[key].append(r)

    out = []
    metric_keys = [
        "collision_count", "cav_collision_count", "hdv_collision_count",
        "vru_collision_count", "cav_hit_pedestrian_count",
        "hdv_hit_pedestrian_count",
        "action_hard_brake", "action_soft_brake", "action_decelerate",
        "phantom_brakes_suppressed", "dead_cav_count",
        "cooperative_brakes", "frozen_vehicle_count", "v2v_received_total",
        "cbr_mean", "wall_to_sim_ratio",
    ]
    for key in sorted(groups.keys()):
        p, w_bucket, weather, map_name = key
        cell_rows = groups[key]
        # Report the mean actual yield for transparency
        actual_yield = sum(r.get("n_walkers", 0) for r in cell_rows) / len(cell_rows)
        summary = {
            "penetration": p,
            "n_walkers": w_bucket,           # bucketed value used for grouping
            "n_walkers_actual": actual_yield,  # mean actual spawn yield
            "weather": weather,
            "map": map_name,
            "n_seeds": len(cell_rows),
        }
        for k in metric_keys:
            mean, std = _mean_std([r[k] for r in cell_rows])
            summary[f"{k}_mean"] = mean
            summary[f"{k}_std"] = std
        out.append(summary)
    return out


def _bucket_walkers(n: int) -> int:
    """Bucket walker-yield value to its 'requested' bin.

    CARLA's spawn API may reject some walker requests (off-mesh,
    collision), so a sweep that requested 60 walkers can land anywhere
    in ~40-60 actual. Aggregating by exact yield would split each
    intended cell into ~20 single-seed groups. Buckets:
      0           -> 0      (no walkers)
      1..30       -> 20     (sparse VRU axis)
      31..90      -> 60     (medium VRU axis — default)
      91..150     -> 120    (dense VRU axis)
      >150        -> exact  (unusual setting; left ungrouped)
    """
    if n <= 0:
        return 0
    if n <= 30:
        return 20
    if n <= 90:
        return 60
    if n <= 150:
        return 120
    return n


# Backward-compatibility alias (older callers used _aggregate_by_penetration).
_aggregate_by_penetration = _aggregate_by_cell


# === Figures ============================================================

def _split_by_walkers(by_cell: list[dict]) -> dict[int, list[dict]]:
    """Split aggregated rows by n_walkers value (one series per walker count)."""
    out: dict[int, list[dict]] = defaultdict(list)
    for r in by_cell:
        out[r["n_walkers"]].append(r)
    for w in out:
        out[w].sort(key=lambda r: r["penetration"])
    return out


def _figure_collisions_vs_penetration(by_cell: list[dict], out_path: str):
    """Main thesis figure: collision count by penetration rate.

    If the sweep has multiple walker counts, draws one set of curves per
    walker count.
    """
    fig, ax = plt.subplots(figsize=(7, 5))
    series = _split_by_walkers(by_cell)
    for w, rows in sorted(series.items()):
        suffix = "" if len(series) == 1 else f" (w={w})"
        xs = [r["penetration"] for r in rows]
        total = [r["collision_count_mean"] for r in rows]
        total_e = [r["collision_count_std"] for r in rows]
        ax.errorbar(xs, total, yerr=total_e, marker="o", linewidth=2,
                    capsize=4, label=f"Total{suffix}")
        if len(series) == 1:
            # Only show HDV/CAV breakdown when not also splitting by walker count.
            hdv = [r["hdv_collision_count_mean"] for r in rows]
            hdv_e = [r["hdv_collision_count_std"] for r in rows]
            cav = [r["cav_collision_count_mean"] for r in rows]
            cav_e = [r["cav_collision_count_std"] for r in rows]
            ax.errorbar(xs, hdv, yerr=hdv_e, marker="s", linewidth=1.5,
                        capsize=4, label="HDV-involved")
            ax.errorbar(xs, cav, yerr=cav_e, marker="^", linewidth=1.5,
                        capsize=4, label="CAV-involved")

    ax.set_xlabel("V2X penetration rate")
    n_seeds = by_cell[0]["n_seeds"] if by_cell else 0
    ax.set_ylabel(f"Collisions per run ({n_seeds} seeds, mean ± std)")
    ax.set_title("Collisions vs. V2X penetration rate")
    ax.set_xticks([0.0, 0.5, 1.0])
    ax.set_xlim(-0.1, 1.1)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _figure_actions_vs_penetration(by_cell: list[dict], out_path: str):
    """Stacked-bar of CAV actions per penetration cell (walker-aware)."""
    fig, ax = plt.subplots(figsize=(7, 5))
    series = _split_by_walkers(by_cell)
    # If only one walker count, classic 3-bar-per-p layout. Otherwise we
    # draw separate sub-bars per walker count, narrower.
    walker_counts = sorted(series.keys())
    n_w = len(walker_counts)
    base_width = 0.22 if n_w == 1 else 0.18 / n_w

    for wi, w in enumerate(walker_counts):
        rows = series[w]
        xs = [r["penetration"] for r in rows]
        hard = [r["action_hard_brake_mean"] for r in rows]
        soft = [r["action_soft_brake_mean"] for r in rows]
        decel = [r["action_decelerate_mean"] for r in rows]
        offset = (wi - (n_w - 1) / 2) * (base_width * 3 + 0.05) if n_w > 1 else 0
        suffix = "" if n_w == 1 else f" w={w}"

        ax.bar([x - base_width + offset for x in xs], hard, base_width,
               label=f"Hard brake{suffix}",
               color="#d62728" if wi == 0 else "#e57c7c")
        ax.bar([x + offset for x in xs], soft, base_width,
               label=f"Soft brake{suffix}",
               color="#ff7f0e" if wi == 0 else "#ffc287")
        ax.bar([x + base_width + offset for x in xs], decel, base_width,
               label=f"Decelerate{suffix}",
               color="#2ca02c" if wi == 0 else "#7fc97f")

    ax.set_xlabel("V2X penetration rate")
    ax.set_ylabel("CAV actions per run (mean)")
    ax.set_title("CAV actions vs. V2X penetration rate")
    ax.set_xticks([0.0, 0.5, 1.0])
    ax.grid(True, alpha=0.3, axis="y")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _figure_phantom_brakes_vs_penetration(by_cell: list[dict], out_path: str):
    """Hysteresis contribution: phantom-brake-suppressed count per cell."""
    fig, ax = plt.subplots(figsize=(7, 5))
    series = _split_by_walkers(by_cell)
    for w, rows in sorted(series.items()):
        suffix = "" if len(series) == 1 else f" (w={w})"
        xs = [r["penetration"] for r in rows]
        means = [r["phantom_brakes_suppressed_mean"] for r in rows]
        stds = [r["phantom_brakes_suppressed_std"] for r in rows]
        ax.errorbar(xs, means, yerr=stds, marker="o", linewidth=2,
                    capsize=4, label=f"Phantom suppressed{suffix}")
    ax.set_xlabel("V2X penetration rate")
    ax.set_ylabel("Phantom brakes suppressed per run (mean ± std)")
    ax.set_title("Hysteresis contribution: phantom-brake suppression\n"
                 "(proposal §4.1.1 step 5)")
    ax.set_xticks([0.0, 0.5, 1.0])
    ax.grid(True, alpha=0.3)
    if len(series) > 1:
        ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _figure_vru_collisions_vs_penetration(by_cell: list[dict], out_path: str):
    """VRU axis: pedestrian collisions broken down by responsible vehicle type.

    Only meaningful when at least one cell has n_walkers > 0; the caller
    must filter accordingly. If the sweep used a multi-level walker axis
    (e.g. 0/20/40), one set of curves is drawn per walker count.
    """
    fig, ax = plt.subplots(figsize=(8, 5.5))
    # Only walker cells (skip vehicle-only baseline; all-zero data clutters)
    walker_cells = [r for r in by_cell if r["n_walkers"] > 0]
    if not walker_cells:
        plt.close(fig)
        return

    # Group by walker count so multi-level VRU axes get separate series
    series = defaultdict(list)
    for r in walker_cells:
        series[r["n_walkers"]].append(r)
    for w in series:
        series[w].sort(key=lambda r: r["penetration"])

    walker_counts = sorted(series.keys())
    # Distinct colour palettes per walker count: dimmer = fewer walkers
    color_map = {
        w: {
            "total": ["#1f77b4", "#1f77b4", "#1f77b4"][i % 3],
            "hdv":   ["#d62728", "#a02020", "#7a1818"][i],
            "cav":   ["#2ca02c", "#1f7a1f", "#155a15"][i],
        }
        for i, w in enumerate(walker_counts[:3])
    }

    for w in walker_counts:
        rows = series[w]
        suffix = "" if len(walker_counts) == 1 else f" (w={w})"
        xs = [r["penetration"] for r in rows]
        vru_total = [r["vru_collision_count_mean"] for r in rows]
        vru_total_e = [r["vru_collision_count_std"] for r in rows]
        cav_hits = [r["cav_hit_pedestrian_count_mean"] for r in rows]
        cav_hits_e = [r["cav_hit_pedestrian_count_std"] for r in rows]
        hdv_hits = [r["hdv_hit_pedestrian_count_mean"] for r in rows]
        hdv_hits_e = [r["hdv_hit_pedestrian_count_std"] for r in rows]
        cmap = color_map.get(w, {"total": "#1f77b4", "hdv": "#d62728", "cav": "#2ca02c"})

        # Different markers per walker count for printability
        markers = {0: "o", 20: "o", 40: "s", 60: "^"}.get(w, "o")
        ax.errorbar(xs, vru_total, yerr=vru_total_e, marker=markers, linewidth=2,
                    capsize=4, label=f"Total VRU{suffix}", color=cmap["total"])
        ax.errorbar(xs, hdv_hits, yerr=hdv_hits_e, marker=markers, linewidth=1.5,
                    capsize=4, label=f"HDV→ped{suffix}", color=cmap["hdv"],
                    linestyle="--")
        ax.errorbar(xs, cav_hits, yerr=cav_hits_e, marker=markers, linewidth=1.5,
                    capsize=4, label=f"CAV→ped{suffix}", color=cmap["cav"],
                    linestyle=":")

    ax.set_xlabel("V2X penetration rate")
    n_seeds = walker_cells[0]["n_seeds"]
    walker_axis_str = "/".join(str(w) for w in walker_counts)
    ax.set_ylabel(f"VRU collisions per run ({n_seeds} seeds, mean ± std)")
    ax.set_title(f"V2X benefit on Vulnerable Road Users\n"
                 f"(walker counts: {walker_axis_str})")
    ax.set_xticks([0.0, 0.5, 1.0])
    ax.set_xlim(-0.1, 1.1)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, ncol=len(walker_counts))
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _figure_weather_vs_collisions(by_cell: list[dict], out_path: str):
    """Weather ablation figure: collisions vs penetration, one series per preset.

    Skipped if the sweep used only one weather preset (the typical
    vehicle-only or walker-only sweep). When at least two presets are
    present, draws collision_count_mean for each preset across the
    penetration axis — directly visualises the thesis claim that V2X
    benefit grows under degraded perception (rain / dusk).
    """
    weather_present = {r.get("weather", "ClearNoon") for r in by_cell}
    if len(weather_present) < 2:
        return

    fig, ax = plt.subplots(figsize=(8, 5.5))
    # Group by weather, then plot one curve per preset
    by_weather: dict[str, list[dict]] = defaultdict(list)
    for r in by_cell:
        by_weather[r.get("weather", "ClearNoon")].append(r)
    for w_name in by_weather:
        by_weather[w_name].sort(key=lambda r: r["penetration"])

    # Weather order: best-case first, worst-case last (left-to-right by name)
    preferred_order = ("ClearNoon", "ClearSunset", "HardRainNoon",
                       "CloudyNoon", "WetNoon", "HardRainSunset")
    weather_order = [w for w in preferred_order if w in by_weather] + \
                    [w for w in sorted(by_weather) if w not in preferred_order]

    # Distinct colour per preset; markers vary too for printability.
    palette = ["#1f77b4", "#ff7f0e", "#d62728", "#2ca02c", "#9467bd", "#8c564b"]
    markers = ["o", "s", "^", "D", "v", "P"]

    for i, w_name in enumerate(weather_order):
        rows = by_weather[w_name]
        # If the sweep also varied n_walkers, average over walker counts
        # within each penetration so the series stays 1-D.
        by_p: dict[float, list[dict]] = defaultdict(list)
        for r in rows:
            by_p[r["penetration"]].append(r)
        ps = sorted(by_p.keys())
        means = []
        stds = []
        for p in ps:
            vals = [r["collision_count_mean"] for r in by_p[p]]
            std_vals = [r["collision_count_std"] for r in by_p[p]]
            means.append(sum(vals) / len(vals))
            # Combine stds with simple pooled estimate
            stds.append(sum(std_vals) / len(std_vals))
        color = palette[i % len(palette)]
        marker = markers[i % len(markers)]
        ax.errorbar(ps, means, yerr=stds, marker=marker, linewidth=2,
                    capsize=4, label=w_name, color=color)

    ax.set_xlabel("V2X penetration rate")
    n_seeds = by_cell[0]["n_seeds"] if by_cell else 0
    ax.set_ylabel(f"Collisions per run ({n_seeds} seeds, mean ± std)")
    ax.set_title("V2X benefit across weather presets")
    ax.set_xticks([0.0, 0.5, 1.0])
    ax.set_xlim(-0.1, 1.1)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _figure_map_vs_collisions(by_cell: list[dict], out_path: str):
    """Map ablation figure: collisions vs penetration, one series per map.

    Skipped if the sweep used only one map. When at least two maps are
    present, averages over any other multi-value axes (walker, weather)
    within each (penetration, map) cell and plots one curve per map —
    directly visualises cross-map generalisation of the V2X benefit.
    """
    maps_present = {r.get("map", "Town05") for r in by_cell}
    if len(maps_present) < 2:
        return

    fig, ax = plt.subplots(figsize=(8, 5.5))
    by_map: dict[str, list[dict]] = defaultdict(list)
    for r in by_cell:
        by_map[r.get("map", "Town05")].append(r)

    # Preferred order: fine-tune map first, then OOD maps
    preferred_order = ("Town05", "Town10HD_Opt", "Town10", "Town03",
                       "Town04", "Town02", "Town01", "Town07")
    map_order = [m for m in preferred_order if m in by_map] + \
                [m for m in sorted(by_map) if m not in preferred_order]

    palette = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b"]
    markers = ["o", "s", "^", "D", "v", "P"]

    for i, map_name in enumerate(map_order):
        rows = by_map[map_name]
        # If sweep also varied walker or weather, average within each
        # penetration so the per-map curve stays 1-D.
        by_p: dict[float, list[dict]] = defaultdict(list)
        for r in rows:
            by_p[r["penetration"]].append(r)
        ps = sorted(by_p.keys())
        means = []
        stds = []
        for p in ps:
            vals = [r["collision_count_mean"] for r in by_p[p]]
            std_vals = [r["collision_count_std"] for r in by_p[p]]
            means.append(sum(vals) / len(vals))
            stds.append(sum(std_vals) / len(std_vals))
        color = palette[i % len(palette)]
        marker = markers[i % len(markers)]
        ax.errorbar(ps, means, yerr=stds, marker=marker, linewidth=2,
                    capsize=4, label=map_name, color=color)

    ax.set_xlabel("V2X penetration rate")
    n_seeds = by_cell[0]["n_seeds"] if by_cell else 0
    ax.set_ylabel(f"Collisions per run ({n_seeds} seeds, mean ± std)")
    ax.set_title("V2X benefit across maps (cross-map generalisation)")
    ax.set_xticks([0.0, 0.5, 1.0])
    ax.set_xlim(-0.1, 1.1)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# === Main ===============================================================

def main() -> int:
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

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

    # Accept both legacy (pNNN_sNN.json) and walker-axis (pNNN_wNN_sNN.json)
    # filenames. Both contain "p" prefix and end in ".json".
    files = sorted(glob.glob(os.path.join(args.in_dir, "p*_s*.json")))
    files.extend(sorted(glob.glob(os.path.join(args.in_dir, "p*_w*_s*.json"))))
    # Dedupe preserving order
    files = list(dict.fromkeys(files))
    if not files:
        print(f"FAIL — no cell files match p*_s*.json or p*_w*_s*.json in {args.in_dir}",
              file=sys.stderr)
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
        fig_vru = os.path.join(figures_dir, "vru_collisions_vs_penetration.png")
        fig_weather = os.path.join(figures_dir, "weather_vs_collisions.png")
        fig_map = os.path.join(figures_dir, "map_vs_collisions.png")
        _figure_collisions_vs_penetration(by_pen, fig_collisions)
        _figure_actions_vs_penetration(by_pen, fig_actions)
        _figure_phantom_brakes_vs_penetration(by_pen, fig_phantom)
        _figure_vru_collisions_vs_penetration(by_pen, fig_vru)
        _figure_weather_vs_collisions(by_pen, fig_weather)
        _figure_map_vs_collisions(by_pen, fig_map)
        print(f"wrote {fig_collisions}")
        print(f"wrote {fig_actions}")
        print(f"wrote {fig_phantom}")
        # VRU figure is only emitted if some cells had walkers
        if any(r["n_walkers"] > 0 for r in by_pen):
            print(f"wrote {fig_vru}")
    elif not HAS_MPL:
        print("WARN — matplotlib not available, skipping figures", file=sys.stderr)

    # === Summary print to console =====================================
    has_walkers = any(r["n_walkers"] > 0 for r in by_pen)
    weathers_present = {r.get("weather", "ClearNoon") for r in by_pen}
    has_weather_axis = len(weathers_present) > 1
    maps_present = {r.get("map", "Town05") for r in by_pen}
    has_map_axis = len(maps_present) > 1
    print("\n=== Summary by cell ===")
    # Build header columns dynamically: always p, n, collisions, hard_brake;
    # add walker/weather/map/vru when those axes are present.
    cols = ["p"]
    if has_walkers:
        cols.append("w")
    if has_weather_axis:
        cols.append("weather")
    if has_map_axis:
        cols.append("map")
    cols.extend(["n", "collisions", "hard_brake"])
    if has_walkers:
        cols.append("vru_coll")
    header_fmts = {
        "p": f"{'p':>5}", "w": f"{'w':>3}",
        "weather": f"{'weather':>14}", "map": f"{'map':>14}",
        "n": f"{'n':>3}", "collisions": f"{'collisions':>20}",
        "hard_brake": f"{'hard_brake':>14}", "vru_coll": f"{'vru_coll':>10}",
    }
    print("  ".join(header_fmts[c] for c in cols))
    for r in by_pen:
        c_val = f"{r['collision_count_mean']:.1f} ± {r['collision_count_std']:.1f}"
        hb_val = f"{r['action_hard_brake_mean']:.0f} ± {r['action_hard_brake_std']:.0f}"
        vr_val = f"{r['vru_collision_count_mean']:.1f}"
        cell_vals = {
            "p": f"{r['penetration']:5.2f}",
            "w": f"{r['n_walkers']:3d}",
            "weather": f"{r['weather']:>14}",
            "map": f"{r['map']:>14}",
            "n": f"{r['n_seeds']:3d}",
            "collisions": f"{c_val:>20}",
            "hard_brake": f"{hb_val:>14}",
            "vru_coll": f"{vr_val:>10}",
        }
        print("  ".join(cell_vals[c] for c in cols))

    return 0


if __name__ == "__main__":
    sys.exit(main())
