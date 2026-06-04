"""make_figures.py -- Generate all data-driven result figures for the final report.

Reads the Sprint-5 ablation master table (all_cells_144.csv) and produces
publication-quality PNG charts (300 DPI) into ../figures/.

Every figure draws directly from the per-cell data so the numbers are
guaranteed consistent with the deliverable. Means are taken over the 12
cells that share an (arm, penetration) -- 2 seeds x 3 maps x 2 weather --
and error bars are +/- 1 standard deviation across those cells, matching
the SPRINT5_FINAL_ABLATION report convention.

Usage:
    python make_figures.py
"""
from __future__ import annotations

import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

# ---------------------------------------------------------------- paths
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # FINAL_REPORT/
FIGDIR = os.path.join(ROOT, "figures")
os.makedirs(FIGDIR, exist_ok=True)

DELIV = os.path.normpath(os.path.join(
    ROOT, "..", "SPRINT5_DELIVERABLE"))
CSV = os.path.join(DELIV, "05_combined_eda", "all_cells_144.csv")

# ---------------------------------------------------------------- style
plt.rcParams.update({
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "legend.fontsize": 8.5,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "grid.linewidth": 0.6,
    "axes.axisbelow": True,
    "font.family": "DejaVu Sans",
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
})

# Wong colour-blind-safe palette
C_BLUE   = "#0072B2"
C_VERM   = "#D55E00"
C_GREEN  = "#009E73"
C_ORANGE = "#E69F00"
C_SKY    = "#56B4E9"
C_PINK   = "#CC79A7"
C_YELLOW = "#F0E442"
C_GREY   = "#555555"

ARMS = ["combined", "v2i_only", "v2v_only"]
ARM_LABEL  = {"combined": "Combined (V2I+V2V)", "v2i_only": "V2I-only", "v2v_only": "V2V-only"}
ARM_COLOR  = {"combined": C_BLUE, "v2i_only": C_VERM, "v2v_only": C_GREEN}
ARM_MARKER = {"combined": "o", "v2i_only": "s", "v2v_only": "^"}

MAPS = ["Town01", "Town05", "Town10HD_Opt"]
MAP_LABEL = {"Town01": "Town01 (grid)", "Town05": "Town05 (multi-lane)",
             "Town10HD_Opt": "Town10HD (downtown)"}
MAP_COLOR = {"Town01": C_ORANGE, "Town05": C_GREEN, "Town10HD_Opt": C_PINK}
MAP_MARKER = {"Town01": "o", "Town05": "s", "Town10HD_Opt": "^"}

WEATHER = ["ClearNoon", "HardRainNoon"]
W_LABEL = {"ClearNoon": "ClearNoon", "HardRainNoon": "HardRainNoon"}
W_COLOR = {"ClearNoon": C_BLUE, "HardRainNoon": C_SKY}
W_MARKER = {"ClearNoon": "o", "HardRainNoon": "D"}

PENS = [0.0, 0.5, 0.9, 1.0]
PEN_X = [0, 1, 2, 3]                                # even spacing on the axis
PEN_TICK = ["0.0", "0.5", "0.9", "1.0"]

# ---------------------------------------------------------------- load
df = pd.read_csv(CSV)
df = df[df["status"] == "ok"].copy()
print(f"Loaded {len(df)} ok cells from {CSV}")
print("arms:", sorted(df['arm'].unique()), "| pens:", sorted(df['penetration'].unique()))


def agg(arm, col):
    """mean & std of `col` over the 12 cells per penetration for one arm."""
    sub = df[df["arm"] == arm]
    g = sub.groupby("penetration")[col]
    m = g.mean().reindex(PENS)
    s = g.std(ddof=0).reindex(PENS)          # population sd, matches deliverable
    return m.values, s.values


def save(fig, name):
    path = os.path.join(FIGDIR, name)
    fig.savefig(path)
    plt.close(fig)
    print("  wrote", name)


# ================================================================ FIG 3
# Headline: total & primary collisions vs penetration, three arms.
def fig_headline():
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4))
    for ax, col, title in [(axes[0], "collision_count", "(a) Total collisions"),
                           (axes[1], "primary_collision_count", "(b) Primary collisions")]:
        for arm in ARMS:
            m, s = agg(arm, col)
            ax.errorbar(PEN_X, m, yerr=s, label=ARM_LABEL[arm],
                        color=ARM_COLOR[arm], marker=ARM_MARKER[arm],
                        markersize=5, linewidth=1.8, capsize=3, capthick=1)
        ax.set_xticks(PEN_X); ax.set_xticklabels(PEN_TICK)
        ax.set_xlabel("CAV penetration  $p$")
        ax.set_title(title)
        ax.set_ylim(bottom=0)
    axes[0].set_ylabel("Collisions per 90 s cell")
    axes[0].legend(frameon=False, loc="upper right")
    fig.tight_layout()
    save(fig, "fig03-collisions-vs-penetration.png")


# ================================================================ FIG: % reduction
def fig_reduction():
    fig, ax = plt.subplots(figsize=(6.6, 3.4))
    width = 0.25
    base = {arm: agg(arm, "collision_count")[0][0] for arm in ARMS}  # p=0 mean
    pens_plot = [0.5, 0.9, 1.0]
    idx = np.arange(len(pens_plot))
    for k, arm in enumerate(ARMS):
        m, _ = agg(arm, "collision_count")
        red = []
        for p in pens_plot:
            mp = m[PENS.index(p)]
            red.append(100.0 * (base[arm] - mp) / base[arm])
        bars = ax.bar(idx + (k - 1) * width, red, width, label=ARM_LABEL[arm],
                      color=ARM_COLOR[arm], edgecolor="white", linewidth=0.5)
        for b, r in zip(bars, red):
            ax.text(b.get_x() + b.get_width() / 2, r + 1.0, f"{r:.0f}",
                    ha="center", va="bottom", fontsize=7.5)
    ax.set_xticks(idx); ax.set_xticklabels([f"p={p}" for p in pens_plot])
    ax.set_ylabel("Collision reduction vs.\nall-human baseline (%)")
    ax.set_xlabel("CAV penetration")
    ax.set_ylim(0, 100)
    ax.legend(frameon=False, loc="upper left")
    ax.set_title("Monotonic safety gain across all three communication arms")
    fig.tight_layout()
    save(fig, "fig-reduction-summary.png")


# ================================================================ FIG 4
# Who is crashing: CAV / HDV / VRU vs penetration (Combined arm).
def fig_who_crashes():
    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    parts = [("hdv_collision_count", "HDV-involved", C_VERM),
             ("cav_collision_count", "CAV-involved", C_BLUE),
             ("vru_collision_count", "VRU (pedestrian)", C_GREEN)]
    width = 0.26
    idx = np.arange(len(PENS))
    for k, (col, lab, color) in enumerate(parts):
        m, s = agg("combined", col)
        ax.bar(idx + (k - 1) * width, m, width, yerr=s, label=lab,
               color=color, edgecolor="white", linewidth=0.5,
               error_kw=dict(lw=0.8, capsize=2))
    ax.set_xticks(idx); ax.set_xticklabels(PEN_TICK)
    ax.set_xlabel("CAV penetration  $p$")
    ax.set_ylabel("Collisions per cell (mean)")
    ax.set_title("Collision burden shifts from human drivers to the CAV fleet\n(Combined arm)")
    ax.legend(frameon=False)
    fig.tight_layout()
    save(fig, "fig04-who-crashes.png")


# ================================================================ FIG 5
# Collisions by map vs penetration (Combined arm).
def fig_by_map():
    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    sub = df[df["arm"] == "combined"]
    for mp in MAPS:
        s2 = sub[sub["map"] == mp].groupby("penetration")["collision_count"]
        m = s2.mean().reindex(PENS).values
        sd = s2.std(ddof=0).reindex(PENS).values
        ax.errorbar(PEN_X, m, yerr=sd, label=MAP_LABEL[mp], color=MAP_COLOR[mp],
                    marker=MAP_MARKER[mp], markersize=5, linewidth=1.8,
                    capsize=3, capthick=1)
    ax.set_xticks(PEN_X); ax.set_xticklabels(PEN_TICK)
    ax.set_xlabel("CAV penetration  $p$")
    ax.set_ylabel("Total collisions per cell")
    ax.set_ylim(bottom=0)
    ax.set_title("Map complexity sets the collision floor (Combined arm)")
    ax.legend(frameon=False)
    fig.tight_layout()
    save(fig, "fig05-collisions-by-map.png")


# ================================================================ FIG 6
# Collisions by weather vs penetration (Combined arm).
def fig_by_weather():
    fig, ax = plt.subplots(figsize=(6.6, 3.4))
    sub = df[df["arm"] == "combined"]
    for w in WEATHER:
        s2 = sub[sub["weather"] == w].groupby("penetration")["collision_count"]
        m = s2.mean().reindex(PENS).values
        sd = s2.std(ddof=0).reindex(PENS).values
        ax.errorbar(PEN_X, m, yerr=sd, label=W_LABEL[w], color=W_COLOR[w],
                    marker=W_MARKER[w], markersize=5, linewidth=1.8,
                    capsize=3, capthick=1)
    ax.set_xticks(PEN_X); ax.set_xticklabels(PEN_TICK)
    ax.set_xlabel("CAV penetration  $p$")
    ax.set_ylabel("Total collisions per cell")
    ax.set_ylim(bottom=0)
    ax.set_title("Weather robustness: the rain preset tracks clear weather\n(Combined arm)")
    ax.legend(frameon=False)
    fig.tight_layout()
    save(fig, "fig06-collisions-by-weather.png")


# ================================================================ FIG 7
# CAV evasive brake actions vs penetration (Combined arm), stacked.
def fig_brake_actions():
    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    cols = [("action_decelerate", "Decelerate", C_YELLOW),
            ("action_soft_brake", "Soft brake", C_ORANGE),
            ("action_hard_brake", "Hard brake", C_VERM)]
    idx = np.arange(len(PENS))
    bottom = np.zeros(len(PENS))
    for col, lab, color in cols:
        m, _ = agg("combined", col)
        m = np.nan_to_num(m)
        ax.bar(idx, m, 0.55, bottom=bottom, label=lab, color=color,
               edgecolor="white", linewidth=0.5)
        bottom += m
    ax.set_xticks(idx); ax.set_xticklabels(PEN_TICK)
    ax.set_xlabel("CAV penetration  $p$")
    ax.set_ylabel("CAV brake actions per cell (mean)")
    ax.set_title("Cooperative-perception evasive actions scale with penetration\n(Combined arm)")
    ax.legend(frameon=False)
    fig.tight_layout()
    save(fig, "fig07-brake-actions.png")


# ================================================================ FIG 8
# Cooperative communication load (Combined arm): V2V msgs + coop brakes.
def fig_coop_load():
    fig, ax1 = plt.subplots(figsize=(6.6, 3.6))
    idx = np.arange(len(PENS))
    v2v, _ = agg("combined", "v2v_received_total")
    coop, _ = agg("combined", "cooperative_brakes")
    v2v = np.nan_to_num(v2v) / 1000.0                  # thousands
    b = ax1.bar(idx, v2v, 0.55, color=C_SKY, edgecolor="white",
                linewidth=0.5, label="V2V messages received")
    ax1.set_xticks(idx); ax1.set_xticklabels(PEN_TICK)
    ax1.set_xlabel("CAV penetration  $p$")
    ax1.set_ylabel("V2V messages received\nper cell (thousands)", color=C_SKY)
    ax1.tick_params(axis="y", labelcolor=C_SKY)
    ax2 = ax1.twinx()
    ax2.grid(False)
    ax2.plot(idx, np.nan_to_num(coop), color=C_VERM, marker="o", linewidth=2,
             label="Cooperative brakes")
    ax2.set_ylabel("Cooperative (V2V-triggered)\nbrakes per cell", color=C_VERM)
    ax2.tick_params(axis="y", labelcolor=C_VERM)
    ax1.set_title("Cooperative-communication load grows with CAV penetration\n(Combined arm)")
    lines = [b, ax2.lines[0]]
    ax1.legend(lines, [l.get_label() for l in lines], frameon=False, loc="upper left")
    fig.tight_layout()
    save(fig, "fig08-coop-load.png")


# ================================================================ FIG 9
# Phantom brakes suppressed vs penetration, three arms.
def fig_phantom():
    fig, ax = plt.subplots(figsize=(6.6, 3.4))
    for arm in ARMS:
        m, s = agg(arm, "phantom_brakes_suppressed")
        ax.errorbar(PEN_X, m, yerr=s, label=ARM_LABEL[arm], color=ARM_COLOR[arm],
                    marker=ARM_MARKER[arm], markersize=5, linewidth=1.8,
                    capsize=3, capthick=1)
    ax.set_xticks(PEN_X); ax.set_xticklabels(PEN_TICK)
    ax.set_xlabel("CAV penetration  $p$")
    ax.set_ylabel("Phantom brakes suppressed\nper cell (mean)")
    ax.set_ylim(bottom=0)
    ax.set_title("Confirmation hysteresis suppresses more phantom brakes\nas penetration rises")
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    save(fig, "fig09-phantom-brakes.png")


# ================================================================ FIG 10
# VRU collisions vs penetration (three arms) + redistribution inset.
def fig_vru():
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4))
    ax = axes[0]
    for arm in ARMS:
        m, s = agg(arm, "vru_collision_count")
        ax.errorbar(PEN_X, m, yerr=s, label=ARM_LABEL[arm], color=ARM_COLOR[arm],
                    marker=ARM_MARKER[arm], markersize=5, linewidth=1.6,
                    capsize=3, capthick=1)
    ax.set_xticks(PEN_X); ax.set_xticklabels(PEN_TICK)
    ax.set_xlabel("CAV penetration  $p$")
    ax.set_ylabel("VRU (pedestrian) collisions per cell")
    ax.set_ylim(bottom=0)
    ax.set_title("(a) VRU collisions vs. penetration")
    ax.legend(frameon=False)

    # redistribution within Combined arm: who hits the pedestrian
    ax2 = axes[1]
    idx = np.arange(len(PENS))
    hdvp, _ = agg("combined", "hdv_hit_pedestrian")
    cavp, _ = agg("combined", "cav_hit_pedestrian")
    w = 0.38
    ax2.bar(idx - w/2, np.nan_to_num(hdvp), w, label="HDV -> pedestrian", color=C_VERM,
            edgecolor="white", linewidth=0.5)
    ax2.bar(idx + w/2, np.nan_to_num(cavp), w, label="CAV -> pedestrian", color=C_BLUE,
            edgecolor="white", linewidth=0.5)
    ax2.set_xticks(idx); ax2.set_xticklabels(PEN_TICK)
    ax2.set_xlabel("CAV penetration  $p$")
    ax2.set_ylabel("Pedestrian hits per cell (mean)")
    ax2.set_title("(b) Risk redistribution (Combined)")
    ax2.legend(frameon=False)
    fig.tight_layout()
    save(fig, "fig10-vru-collisions.png")


# ================================================================ FIG 12
# At-fault collisions by driver profile (Combined arm, pooled sum).
def fig_atfault():
    sub = df[df["arm"] == "combined"]
    prof = [("coll_attentive", "Attentive\n(avoid ON)", C_GREEN),
            ("coll_distracted", "Distracted\n(avoid OFF)", C_ORANGE),
            ("coll_aggressive_hostile", "Aggressive-\nhostile (OFF)", C_VERM),
            ("coll_ai_realistic", "AI realistic\n(CAV)", C_BLUE)]
    vals = [int(sub[c].sum()) for c, _, _ in prof]
    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    bars = ax.bar([p[1] for p in prof], vals, color=[p[2] for p in prof],
                  edgecolor="white", linewidth=0.5, width=0.62)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width()/2, v + 2, str(v), ha="center",
                va="bottom", fontsize=9)
    ax.set_ylabel("At-fault collisions (sum over all cells)")
    ax.set_title("Reckless human profiles dominate the at-fault collisions\n(Combined arm, all penetrations pooled)")
    ax.set_ylim(0, max(vals) * 1.18)
    fig.tight_layout()
    save(fig, "fig12-atfault-by-profile.png")


# ================================================================ run
if __name__ == "__main__":
    print("\nGenerating figures...")
    fig_headline()
    fig_reduction()
    fig_who_crashes()
    fig_by_map()
    fig_by_weather()
    fig_brake_actions()
    fig_coop_load()
    fig_phantom()
    fig_vru()
    fig_atfault()

    # ---- cross-check printout against SPRINT5 report tables ----
    print("\n=== CROSS-CHECK: total collisions mean (should match report 2a) ===")
    print(f"{'pen':>4} | {'combined':>10} {'v2i_only':>10} {'v2v_only':>10}")
    for i, p in enumerate(PENS):
        row = f"{p:>4} |"
        for arm in ARMS:
            m, s = agg(arm, "collision_count")
            row += f"  {m[i]:5.1f}+/-{s[i]:4.1f}"
        print(row)
    print("\n=== At-fault by profile (combined, sum) ===")
    sub = df[df["arm"] == "combined"]
    for c in ["coll_attentive", "coll_distracted", "coll_aggressive_hostile", "coll_ai_realistic"]:
        print(f"  {c:28s}: {int(sub[c].sum())}")
    print("\nDone. Figures in", FIGDIR)
