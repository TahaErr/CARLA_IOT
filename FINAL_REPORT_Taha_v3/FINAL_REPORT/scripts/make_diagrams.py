"""make_diagrams.py -- Vector-style architecture / topology / scenario diagrams.

Draws three schematic figures with matplotlib (no external graphics tools)
and exports them as 300-DPI PNGs into ../figures/:

  fig01_architecture.png   end-to-end pipeline with BOTH V2I and V2V paths
  fig02_topology.png       network topology + the three ablation arms
  fig11_vru_scenario.png   cooperative VRU-protection use case (V2I + V2V relay)

Usage:
    python make_diagrams.py
"""
from __future__ import annotations
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle, Circle, Polygon
from matplotlib.lines import Line2D

HERE = os.path.dirname(os.path.abspath(__file__))
FIGDIR = os.path.join(os.path.dirname(HERE), "figures")
os.makedirs(FIGDIR, exist_ok=True)

# palette
BLUE   = "#0072B2"
VERM   = "#D55E00"
GREEN  = "#009E73"
ORANGE = "#E69F00"
SKY    = "#56B4E9"
PINK   = "#CC79A7"
GREY   = "#666666"
LGREY  = "#EDEDED"
DARK   = "#222222"

plt.rcParams.update({"font.family": "DejaVu Sans", "savefig.dpi": 300,
                     "savefig.bbox": "tight", "savefig.pad_inches": 0.08})


def box(ax, x, y, w, h, title, lines=None, fc=LGREY, ec=GREY, tc=DARK,
        title_fc=None, fs_title=9.5, fs_line=8.0, lw=1.4, bar_h=2.6, spacing=1.25):
    """Sharp-cornered box with a coloured title bar and vertically-centred lines."""
    ax.add_patch(Rectangle((x, y), w, h, fc=fc, ec=ec, lw=lw, zorder=2))
    if title_fc:
        ax.add_patch(Rectangle((x, y + h - bar_h), w, bar_h, fc=title_fc, ec=ec,
                               lw=lw, zorder=3))
        ax.text(x + w / 2, y + h - bar_h / 2, title, ha="center", va="center",
                fontsize=fs_title, fontweight="bold", color="white", zorder=4)
        ctop = y + h - bar_h
    else:
        ax.text(x + w / 2, y + h - 1.2, title, ha="center", va="center",
                fontsize=fs_title, fontweight="bold", color=tc, zorder=4)
        ctop = y + h - 2.6
    if lines:
        cbot = y + 0.4
        mid = (ctop + cbot) / 2.0
        ystart = mid + (len(lines) - 1) * spacing / 2.0
        for i, ln in enumerate(lines):
            ax.text(x + w / 2, ystart - i * spacing, ln, ha="center", va="center",
                    fontsize=fs_line, color=tc, zorder=4)


def arrow(ax, x1, y1, x2, y2, label=None, color=DARK, lw=1.8, style="-|>",
          ls="-", rad=0.0, fs=8, lab_dy=0.5, lab_dx=0.0, lab_color=None):
    a = FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style,
                        mutation_scale=14, color=color, lw=lw,
                        linestyle=ls, connectionstyle=f"arc3,rad={rad}", zorder=5)
    ax.add_patch(a)
    if label:
        ax.text((x1 + x2) / 2 + lab_dx, (y1 + y2) / 2 + lab_dy, label,
                ha="center", va="center", fontsize=fs,
                color=lab_color or color, fontweight="bold", zorder=6,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))


# =====================================================================
# FIG 1 -- End-to-end architecture with V2I and V2V paths
# =====================================================================
def fig_architecture():
    fig, ax = plt.subplots(figsize=(12.2, 5.2))
    ax.set_xlim(0, 124); ax.set_ylim(0, 46); ax.axis("off")

    # Physical world (tall, spans both source rows)
    box(ax, 2, 9, 17, 26, "Physical World",
        ["HDV (unconnected)", "VRU (no V2P radio)", "CAV (OBU-equipped)",
         "CARLA 0.9.16", "60 veh + 60 walkers"],
        fc="#F4F4F4", title_fc=GREY, spacing=2.2)

    # RSU edge (V2I source) -- top row
    box(ax, 26, 23, 26, 13, "RSU Edge  -  V2I",
        ["RGB camera 1280x720 @ 10 Hz", "YOLO26s <= 20 ms (Jetson Orin)",
         "ETSI CPM enc. TS 103 324 R2", "ASN.1 UPER  -  300 m range"],
        fc="#E7F0F7", title_fc=BLUE, fs_line=7.6, spacing=1.7)

    # Peer CAV (V2V source) -- bottom row
    box(ax, 26, 8, 26, 13, "Peer CAV  -  V2V",
        ["local sensor 50 m / 90 deg", "V2V broadcaster 150 m",
         "coop msg @ 10 Hz", "CPM-like + DENM brake"],
        fc="#E7F6F1", title_fc=GREEN, fs_line=7.6, spacing=1.7)

    # Channel (tall)
    box(ax, 59, 9, 20, 26, "5G NR-V2X Channel",
        ["broker  PUB / SUB", "latency  (Coll-Perales)",
         "PDR  (Thandavarayan)", "CBR  1 s window"],
        fc="#FFF3E0", title_fc=ORANGE, fs_line=7.8, spacing=2.2)

    # Ego CAV (tall)
    box(ax, 86, 9, 22, 26, "Ego CAV Core",
        ["CPM / V2V decoder", "time-aware late fusion",
         "confirmation hysteresis", "TTC evaluator"],
        fc="#E7F0F7", title_fc=BLUE, fs_line=7.8, spacing=2.2)

    # Avoidance (tall)
    box(ax, 113, 9, 9, 26, "Avoid",
        ["HARD", "<=1.0 s", "SOFT", "<=2.5 s", "DECEL", "<=4.0 s"],
        fc="#FBE9E7", title_fc=VERM, fs_line=7.4, spacing=2.0)

    # arrows
    arrow(ax, 19, 27, 26, 29.5, "VIS", color=GREY, lw=1.6, lab_dy=1.2, fs=7.5)
    arrow(ax, 19, 17, 26, 14.5, "VIS", color=GREY, lw=1.6, lab_dy=-1.2, fs=7.5)
    arrow(ax, 52, 29.5, 59, 26, "V2I", color=BLUE, lab_dy=1.6, fs=8.5)
    arrow(ax, 52, 14.5, 59, 19, "V2V", color=GREEN, lab_dy=-1.6, fs=8.5)
    arrow(ax, 79, 25, 86, 25, "deliver", color=ORANGE, lab_dy=1.6, fs=7.6)
    arrow(ax, 108, 22, 113, 22, "brake", color=VERM, lab_dy=1.6, fs=7.6)
    # ego CAV V2V broadcast back to channel (bidirectional, dashed)
    arrow(ax, 86, 15, 79, 15, color=GREEN, lw=1.4, ls=(0, (4, 2)))
    ax.text(82.5, 12.6, "V2V tx", ha="center", va="center", fontsize=6.8,
            color=GREEN, style="italic")

    ax.text(62, 43.6, "End-to-End Cooperative-Perception System Architecture",
            ha="center", va="center", fontsize=13, fontweight="bold")
    ax.text(62, 2.4, "Two perception sources -- infrastructure CPM (V2I) and "
            "vehicle-to-vehicle messages (V2V) -- are fused late inside every CAV; "
            "the three ablation arms enable V2I only, V2V only, or both.",
            ha="center", va="center", fontsize=8.2, color=GREY)
    fig.savefig(os.path.join(FIGDIR, "fig01-architecture.png"))
    plt.close(fig)
    print("wrote fig01-architecture.png")


# =====================================================================
# FIG 2 -- Network topology and the three communication arms
# =====================================================================
def fig_topology():
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    ax.set_xlim(0, 100); ax.set_ylim(0, 58); ax.axis("off")

    # central broker
    box(ax, 38, 23, 24, 13, "5G NR-V2X Broker",
        ["channel model:", "latency / PDR / CBR"],
        fc="#FFF3E0", title_fc=ORANGE, fs_title=10, fs_line=8.5, spacing=1.5)

    # RSU nodes (left)
    box(ax, 4, 40, 22, 12, "RSU Node 1", ["Intersection A", "cam + YOLO + CPM"],
        fc="#E7F0F7", title_fc=BLUE, fs_line=8, spacing=1.5)
    box(ax, 4, 8, 22, 12, "RSU Node 2", ["Intersection B", "cam + YOLO + CPM"],
        fc="#E7F0F7", title_fc=BLUE, fs_line=8, spacing=1.5)

    # CAVs and HDV (right)
    box(ax, 74, 42, 22, 11, "CAV Agent 1", ["OBU  -  late fusion"],
        fc="#E7F6F1", title_fc=GREEN, fs_line=8)
    box(ax, 74, 26, 22, 11, "CAV Agent 2", ["OBU  -  late fusion"],
        fc="#E7F6F1", title_fc=GREEN, fs_line=8)
    box(ax, 74, 10, 22, 11, "HDV", ["unconnected", "perceived only"],
        fc="#F4F4F4", title_fc=GREY, fs_line=8, spacing=1.5)

    # V2I links RSU -> broker -> CAV  (blue solid)
    arrow(ax, 26, 45, 38, 33, color=BLUE, lw=1.8)
    arrow(ax, 26, 14, 38, 27, color=BLUE, lw=1.8)
    arrow(ax, 62, 32, 74, 46, color=BLUE, lw=1.8, label="V2I  (ETSI CPM)", fs=7.5, lab_dy=1.6)
    arrow(ax, 62, 29, 74, 31, color=BLUE, lw=1.8)

    # V2V link CAV1 <-> CAV2 (green dashed, direct + via broker)
    arrow(ax, 85, 42, 85, 37, color=GREEN, lw=1.8, style="<|-|>", ls=(0, (4, 2)))
    ax.text(89.5, 39.5, "V2V", ha="center", va="center", fontsize=7.5,
            color=GREEN, fontweight="bold")
    arrow(ax, 74, 37, 62, 31, color=GREEN, lw=1.5, ls=(0, (4, 2)))
    arrow(ax, 74, 30, 62, 30, color=GREEN, lw=1.5, ls=(0, (4, 2)))

    # HDV visual tracking (grey dotted, no comms)
    arrow(ax, 74, 15, 62, 26, color=GREY, lw=1.4, ls=":", style="-|>")
    ax.text(67, 19, "visual\ntracking", ha="center", va="center", fontsize=6.6,
            color=GREY, style="italic")

    ax.text(50, 56.4, "Network Topology and the Three Communication Arms",
            ha="center", va="center", fontsize=13, fontweight="bold")

    # arm legend box
    lx, ly, lw_, lh = 30, 0.5, 40, 6.5
    ax.add_patch(Rectangle((lx, ly), lw_, lh, fc="white", ec=GREY, lw=1.0, zorder=2))
    ax.add_line(Line2D([lx + 2, lx + 6], [ly + 4.6, ly + 4.6], color=BLUE, lw=2.2))
    ax.add_line(Line2D([lx + 2, lx + 6], [ly + 2.7, ly + 2.7], color=GREEN, lw=2.2,
                       ls=(0, (4, 2))))
    ax.text(lx + 7, ly + 4.6, "V2I link (RSU CPM)", va="center", fontsize=7.6)
    ax.text(lx + 7, ly + 2.7, "V2V link (CAV<->CAV)", va="center", fontsize=7.6)
    ax.text(lx + 22, ly + 4.6, "Combined = V2I + V2V", va="center", fontsize=7.6, color=DARK)
    ax.text(lx + 22, ly + 2.7, "V2I-only  /  V2V-only", va="center", fontsize=7.6, color=DARK)
    ax.text(lx + lw_/2, ly + lh - 0.7, "Ablation arms toggle which links are active",
            ha="center", va="center", fontsize=7.2, style="italic", color=GREY)

    fig.savefig(os.path.join(FIGDIR, "fig02-topology.png"))
    plt.close(fig)
    print("wrote fig02-topology.png")


# =====================================================================
# FIG 11 -- Cooperative VRU-protection scenario (top-down)
# =====================================================================
def fig_vru_scenario():
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    ax.set_xlim(0, 100); ax.set_ylim(0, 56); ax.axis("off")

    # roads (cross intersection)
    ax.add_patch(Rectangle((0, 18), 100, 16, fc="#D9D9D9", ec="none", zorder=1))   # horiz road
    ax.add_patch(Rectangle((40, 0), 16, 56, fc="#D9D9D9", ec="none", zorder=1))    # vert road
    # lane dashes (horizontal)
    for xx in range(4, 100, 9):
        ax.add_line(Line2D([xx, xx + 4], [26, 26], color="white", lw=1.5, zorder=2))

    # RSU on a pole at the corner (high vantage)
    ax.add_patch(Rectangle((57, 35), 2, 7, fc=DARK, ec="none", zorder=4))
    ax.add_patch(Circle((58, 43), 1.6, fc=BLUE, ec="white", lw=1.0, zorder=5))
    ax.text(58, 47, "RSU camera\n(high vantage)", ha="center", va="bottom",
            fontsize=8, color=BLUE, fontweight="bold")
    # field-of-view cone toward the crossing
    fov = Polygon([(58, 42), (30, 20), (50, 14)], closed=True, fc=BLUE, ec="none",
                  alpha=0.12, zorder=2)
    ax.add_patch(fov)

    # occluding bus (blocks line of sight)
    ax.add_patch(FancyBboxPatch((30, 24), 13, 6, boxstyle="round,pad=0.1,rounding_size=0.5",
                                fc=VERM, ec="white", lw=1.2, zorder=5))
    ax.text(36.5, 27, "Occluding bus", ha="center", va="center", fontsize=7.5,
            color="white", fontweight="bold", zorder=6)

    # pedestrian stepping off behind the bus
    ax.add_patch(Circle((34, 17), 1.7, fc=GREEN, ec="white", lw=1.0, zorder=6))
    ax.text(34, 12.5, "Pedestrian\n(VRU)", ha="center", va="top", fontsize=7.5,
            color=GREEN, fontweight="bold")

    # approaching CAVs (CAV1 leading, CAV2 trailing)
    ax.add_patch(FancyBboxPatch((68, 25), 9, 5, boxstyle="round,pad=0.1,rounding_size=0.5",
                                fc=BLUE, ec="white", lw=1.2, zorder=5))
    ax.text(72.5, 27.5, "CAV 1", ha="center", va="center", fontsize=8,
            color="white", fontweight="bold", zorder=6)
    ax.add_patch(FancyBboxPatch((84, 25), 9, 5, boxstyle="round,pad=0.1,rounding_size=0.5",
                                fc=SKY, ec="white", lw=1.2, zorder=5))
    ax.text(88.5, 27.5, "CAV 2", ha="center", va="center", fontsize=8,
            color="white", fontweight="bold", zorder=6)

    # sight-blocked line CAV1 -> pedestrian (red dotted, X)
    arrow(ax, 68, 27, 44, 19, color=VERM, lw=1.6, ls=":", style="-")
    ax.text(55, 30.5, "sight blocked", ha="center", va="center", fontsize=7.5,
            color=VERM, style="italic", rotation=12)

    # V2I alert RSU -> CAV1
    arrow(ax, 59, 42, 72, 31, color=BLUE, lw=2.0, rad=-0.2,
          label="V2I alert\n(ETSI CPM)", fs=7.5, lab_dx=4, lab_dy=3)
    # V2V relay CAV1 -> CAV2
    arrow(ax, 77, 27.5, 84, 27.5, color=GREEN, lw=2.0,
          label="V2V relay", fs=7.5, lab_dy=2.0)

    # proactive braking markers
    for cx in (72.5, 88.5):
        ax.text(cx, 22.5, "proactive\nbraking", ha="center", va="top", fontsize=6.8,
                color=DARK, fontweight="bold")

    ax.text(50, 54.0, "Cooperative VRU-Protection Scenario",
            ha="center", va="center", fontsize=13, fontweight="bold")
    ax.text(50, 2.0, "The RSU sees the pedestrian the bus hides from CAV 1 and "
            "sends a V2I CPM alert; CAV 1 relays it over V2V to the trailing CAV 2, "
            "so both brake before line-of-sight.",
            ha="center", va="center", fontsize=8.0, color=GREY)
    fig.savefig(os.path.join(FIGDIR, "fig11-vru-scenario.png"))
    plt.close(fig)
    print("wrote fig11-vru-scenario.png")


if __name__ == "__main__":
    fig_architecture()
    fig_topology()
    fig_vru_scenario()
    print("Diagrams in", FIGDIR)
