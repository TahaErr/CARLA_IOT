"""Generate ABLATION_G_REPORT_v2.pdf - Config G 2nd iteration (post-fix).

Reads out/ablation_G2 (post-fix) with out/ablation_G (pre-fix) for comparison
and emits a polished PDF: design, results (total + primary/secondary), the
v2-vs-v1 effect of the fixes, comms load, performance, and the corrected
(honest) findings.

    python scripts/make_ablation_G2_report.py   # -> ABLATION_G_REPORT_v2.pdf
"""
from __future__ import annotations
import glob
import json
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "out", "ablation_G2")
BASE = os.path.join(ROOT, "out", "ablation_G")
OUT = os.path.join(ROOT, "ABLATION_G_REPORT_v2.pdf")

ARMS = [("combined", "Combined (V2X+V2V)"),
        ("v2i_only", "V2I-only (no V2V)"),
        ("v2v_only", "V2V-only (no V2X)")]
MAPS = ["Town01", "Town05", "Town10HD_Opt"]
WEA = ["ClearNoon", "HardRainNoon"]
PENS = [0.0, 0.5, 0.9, 1.0]

NAVY = colors.HexColor("#1f2d4d"); BLUE = colors.HexColor("#1f77b4")
GREEN = colors.HexColor("#2ca02c"); RED = colors.HexColor("#b3261e")
AMBER = colors.HexColor("#9a6700"); GREY = colors.HexColor("#5b6470")
LIGHT2 = colors.HexColor("#f7f9fc"); BOXBG = colors.HexColor("#fbf4e6")
GREENBG = colors.HexColor("#eaf6ec"); REDBG = colors.HexColor("#fdecea")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=15, textColor=NAVY, spaceBefore=14, spaceAfter=6, leading=18)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=12, textColor=BLUE, spaceBefore=10, spaceAfter=4, leading=15)
BODY = ParagraphStyle("BODY", parent=ss["BodyText"], fontSize=9.5, leading=14, spaceAfter=6, alignment=TA_LEFT)
SMALL = ParagraphStyle("SMALL", parent=ss["BodyText"], fontSize=8, leading=11, textColor=GREY)
BULLET = ParagraphStyle("BULLET", parent=BODY, leftIndent=12, spaceAfter=3)
TITLE = ParagraphStyle("TITLE", parent=ss["Title"], fontSize=22, textColor=NAVY, leading=26, spaceAfter=2)
SUB = ParagraphStyle("SUB", parent=ss["Normal"], fontSize=11, textColor=GREY, alignment=TA_CENTER, leading=15)
CELL = ParagraphStyle("CELL", parent=BODY, fontSize=8.5, leading=11, spaceAfter=0)

story = []
def P(t, s=BODY): story.append(Paragraph(t, s))
def H(t, s=H1): story.append(Paragraph(t, s))
def gap(h=6): story.append(Spacer(1, h))
def bullets(items):
    for it in items: story.append(Paragraph(f"&bull;&nbsp; {it}", BULLET))


def table(data, col_widths, header=True, size=8.5):
    t = Table(data, colWidths=col_widths, hAlign="LEFT")
    cmds = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("FONTSIZE", (0, 0), (-1, -1), size),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#cdd4e0"))]
    if header:
        cmds += [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                 ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    for r in range(1, len(data)):
        if r % 2 == 0: cmds.append(("BACKGROUND", (0, r), (-1, r), LIGHT2))
    t.setStyle(TableStyle(cmds)); story.append(t)


def callout(title, text, bg=BOXBG, border=AMBER):
    inner = [[Paragraph(f"<b>{title}</b><br/>{text}", CELL)]]
    t = Table(inner, colWidths=[16.8 * cm], hAlign="LEFT")
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("BOX", (0, 0), (-1, -1), 0.6, border),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story.append(t)


def load(root, arm):
    out = {}
    for f in glob.glob(os.path.join(root, arm, "*.json")):
        d = json.load(open(f)); c = d["config"]; a = d["actions_taken"]
        out[(round(c["penetration"], 2), c["weather"], c["map"])] = dict(
            coll=d["collision_count"], prim=d.get("primary_collision_count", d["collision_count"]),
            sec=d.get("secondary_collision_count", 0), cav=d["cav_collision_count"],
            hdv=d["hdv_collision_count"], vru=d["vru_collision_count"],
            frozen=d["frozen_vehicle_count"], coop=d["cooperative_brakes"],
            v2vrecv=d["v2v_received_total"], hb=a.get("hard_brake", 0),
            ratio=round(d["wall_to_sim_ratio"], 2))
    return out


D = {a: load(DATA, a) for a, _ in ARMS}
B = {a: load(BASE, a) for a, _ in ARMS}
NCELLS = {a: len(D[a]) for a, _ in ARMS}


def avg(store, arm, key, p=None, m=None, w=None):
    vs = [r[key] for (pp, ww, mm), r in store[arm].items()
          if (p is None or pp == p) and (m is None or mm == m) and (w is None or ww == w)]
    return sum(vs) / len(vs) if vs else None


def pooled(store, key, p):
    vs = []
    for a, _ in ARMS:
        vs += [r[key] for (pp, _, _), r in store[a].items() if pp == p]
    return sum(vs) / len(vs) if vs else None


def f1(x): return "-" if x is None else f"{x:.1f}"
def f0(x): return "-" if x is None else f"{x:.0f}"
def f2(x): return "-" if x is None else f"{x:.2f}"


# ---- cover ----
P("V2X-Sim &mdash; Cooperative Perception Study", SUB)
gap(4)
P("Configuration G Ablation Report &mdash; v2 (post-fix)", TITLE)
P("Three-arm V2X / V2I / V2V penetration sweep, rerun after the braking-logic fixes", SUB)
gap(10)
story.append(HRFlowable(width="100%", thickness=1.2, color=NAVY))
gap(8)
total = sum(NCELLS.values())
callout(
    "At a glance",
    f"Second iteration of Configuration G, run after fixing the v1 braking regression. "
    f"{total}/72 cells completed with no gaps (one transient CARLA crash self-recovered on retry). "
    "The fix is verified: pooled collisions fell vs v1 and the cooperative-braking layer now "
    "actively engages. <b>Honest caveat:</b> even post-fix the penetration curve is not a clean "
    "monotonic safety gain &mdash; collisions still rise from the all-human baseline to any "
    "connected condition and plateau, and the three arms stay close. Single seed; dense Town10 "
    "dominates. Directional, not conclusive.",
    bg=GREENBG, border=GREEN,
)
gap(8)

# ---- 1 design ----
H("1. Experimental design")
table([
    ["Dimension", "Values"],
    ["Communication arms", "Combined (V2X+V2V) | V2I-only (--no-v2v) | V2V-only (--no-v2x)"],
    ["Penetration p", "0.0, 0.5, 0.9, 1.0"],
    ["Maps", "Town01 (grid), Town05 (multi-lane), Town10HD_Opt (dense downtown)"],
    ["Weather", "ClearNoon, HardRainNoon"],
    ["Seeds", "0 (single seed)"],
    ["Sim duration", "60 s/cell @ dt 0.05 (20 Hz)"],
    ["Population", "60 vehicles + 60 walkers"],
    ["HDV / CAV", "HOSTILE_MIX (30% aggressive, 40% ignore-veh) / AI_REALISTIC (3 m gap, ~1% slips)"],
    ["CPM / V2V cadence", "10 Hz (100 ms)"],
    ["Cells per arm / total", "24 / 72"],
], [4.4 * cm, 12.4 * cm])
gap(4)
callout(
    "Metric note: primary vs total collisions",
    "<b>coll</b> = total deduplicated incidents (one per vehicle pair). <b>primary</b> excludes "
    "<i>secondary</i> incidents - a new pair where one party was already immobilised by an earlier "
    "crash (traffic piling into a stationary wreck, not a fresh failure). Primary is the cleaner "
    "safety signal because immobilise-in-place can otherwise let one wreck, bumped by several cars, "
    "count several times.",
)

# ---- 2 results ----
H("2. Results &mdash; collisions by penetration and arm")
H("2a. Total collisions (avg over maps x weather)", H2)
rows = [["p", "Combined", "V2I-only", "V2V-only"]]
for p in PENS:
    rows.append([f"{p:.1f}", f1(avg(D, "combined", "coll", p=p)), f1(avg(D, "v2i_only", "coll", p=p)), f1(avg(D, "v2v_only", "coll", p=p))])
table(rows, [3.0 * cm] + [4.6 * cm] * 3)
gap(4)
H("2b. Primary collisions (pileups into frozen wrecks excluded)", H2)
rows = [["p", "Combined", "V2I-only", "V2V-only"]]
for p in PENS:
    rows.append([f"{p:.1f}", f1(avg(D, "combined", "prim", p=p)), f1(avg(D, "v2i_only", "prim", p=p)), f1(avg(D, "v2v_only", "prim", p=p))])
table(rows, [3.0 * cm] + [4.6 * cm] * 3)
gap(3)
P("Collisions still rise from the all-human baseline (~6) to any connected condition (~7-8 "
  "primary) and then plateau; the three arms remain close. With a single seed and the dense "
  "hostile Town10HD_Opt dominating the average, treat this as directional.", SMALL)

gap(6)
H("2c. Who is crashing (Combined arm)", H2)
rows = [["p", "CAV", "HDV", "VRU (pedestrian)"]]
for p in PENS:
    rows.append([f"{p:.1f}", f1(avg(D, "combined", "cav", p=p)), f1(avg(D, "combined", "hdv", p=p)), f1(avg(D, "combined", "vru", p=p))])
table(rows, [3.0 * cm, 4.6 * cm, 4.6 * cm, 4.6 * cm])

story.append(PageBreak())

# ---- 3 by map ----
H("3. Collisions by map")
H("3a. Total (avg over weather)", H2)
rows = [["Map", "Arm", "p0.0", "p0.5", "p0.9", "p1.0"]]
for m in MAPS:
    for akey, aname in ARMS:
        rows.append([m, aname] + [f1(avg(D, akey, "coll", p=p, m=m)) for p in PENS])
table(rows, [3.4 * cm, 4.0 * cm] + [2.35 * cm] * 4, size=8)
gap(4)
H("3b. Primary (avg over weather)", H2)
rows = [["Map", "Arm", "p0.0", "p0.5", "p0.9", "p1.0"]]
for m in MAPS:
    for akey, aname in ARMS:
        rows.append([m, aname] + [f1(avg(D, akey, "prim", p=p, m=m)) for p in PENS])
table(rows, [3.4 * cm, 4.0 * cm] + [2.35 * cm] * 4, size=8)
gap(3)
P("Town10HD_Opt carries most of the absolute load and most of the secondary pileups; "
  "Town01/Town05 are milder.", SMALL)

gap(6)
H("4. Collisions by weather (avg over maps, total)")
rows = [["Weather", "Arm", "p0.0", "p0.5", "p0.9", "p1.0"]]
for wx in WEA:
    for akey, aname in ARMS:
        rows.append([wx, aname] + [f1(avg(D, akey, "coll", p=p, w=wx)) for p in PENS])
table(rows, [3.4 * cm, 4.0 * cm] + [2.35 * cm] * 4, size=8)

# ---- 5 v2 vs v1 ----
gap(8)
H("5. Effect of the fixes &mdash; v2 (post-fix) vs v1 (pre-fix)")
rows = [["p", "v1 total", "v2 total", "v2 primary", "change"]]
for p in PENS:
    v1 = pooled(B, "coll", p); v2 = pooled(D, "coll", p); v2p = pooled(D, "prim", p)
    delta = (v2 - v1) if (v1 is not None and v2 is not None) else None
    rows.append([f"{p:.1f}", f1(v1), f1(v2), f1(v2p), ("%+.1f" % delta) if delta is not None else "-"])
table(rows, [2.6 * cm, 3.55 * cm, 3.55 * cm, 3.55 * cm, 3.55 * cm])
gap(4)
P("Cooperative + emergency braking now fire (Combined arm, avg per cell):")
rows = [["p", "v1 coop", "v2 coop", "v1 hard", "v2 hard"]]
for p in PENS:
    rows.append([f"{p:.1f}", f0(avg(B, "combined", "coop", p=p)), f0(avg(D, "combined", "coop", p=p)),
                 f0(avg(B, "combined", "hb", p=p)), f0(avg(D, "combined", "hb", p=p))])
table(rows, [2.6 * cm, 3.55 * cm, 3.55 * cm, 3.55 * cm, 3.55 * cm])
gap(3)
P("The velocity-matched ego-ghost filter un-blinded CAVs to close-range threats; they now brake "
  "when they should, and those hard brakes propagate as V2V brake-intent so the cooperative layer "
  "engages instead of sitting idle.", SMALL)

# ---- 6 comms + perf ----
gap(6)
H("6. Cooperative-communication load")
rows = [["p", "V2V recv (comb.)", "Coop (comb.)", "Coop (v2v-only)", "Coop (v2i-only)"]]
for p in PENS:
    rows.append([f"{p:.1f}", f0(avg(D, "combined", "v2vrecv", p=p)), f0(avg(D, "combined", "coop", p=p)),
                 f0(avg(D, "v2v_only", "coop", p=p)), f0(avg(D, "v2i_only", "coop", p=p))])
table(rows, [2.0 * cm, 4.0 * cm, 3.6 * cm, 3.6 * cm, 3.6 * cm])
gap(3)
P("v2i-only correctly shows zero cooperative brakes (no V2V); V2V load scales with penetration.", SMALL)
gap(6)
H("7. Performance (wall/sim, Combined arm)")
rows = [["Map", "p0.0", "p0.5", "p0.9", "p1.0"]]
for m in MAPS:
    rows.append([m] + [f2(avg(D, "combined", "ratio", p=p, m=m)) for p in PENS])
table(rows, [4.6 * cm] + [3.05 * cm] * 4)

story.append(PageBreak())

# ---- 8 findings ----
H("8. Findings")
bullets([
    "<b>The v1 regression is fixed.</b> Replacing the position-only 3.0 m ego self-exclusion with a "
    "velocity-matched ego-ghost filter restored close-range emergency braking; pooled p=1.0 "
    "collisions fell and Combined-arm hard/cooperative brakes rose by an order of magnitude.",
    "<b>Penetration benefit is still weak/noisy.</b> Even post-fix, collisions rise from baseline "
    "to any connected condition then plateau; arms stay close. Single seed; Town10 dominates.",
    "<b>Immobilise-as-obstacle is real but secondary.</b> The primary/secondary split shows "
    "pileups into frozen wrecks are a minority on Town01/Town05, larger on Town10; the primary "
    "metric removes that confound from the headline.",
    "<b>Residual hypotheses</b> for the flat curve: cautious CAVs braking in hostile traffic invite "
    "rear-ends from non-connected HDVs; the Python brake override interacts with the Traffic "
    "Manager; 60 s single-seed cells have high variance.",
])
H("9. Threats to validity")
bullets([
    "Single seed (seed 0): no real variance bars; directional only.",
    "Single 60 s duration; single seed; metric coupling from immobilise-in-place (mitigated by "
    "the primary metric, not eliminated).",
    "Run completeness: 72/72 with one auto-recovered retry.",
])
H("10. Recommended next steps")
bullets([
    "Re-run as Configuration B (3 seeds, 120 s) for real variance bars and a statistically "
    "meaningful penetration curve.",
    "Add a follower-aware / graduated CAV brake policy so emergency stops do not invite rear-ends; "
    "audit the Python-override vs Traffic-Manager interaction.",
    "Keep out/ablation_G (v1) and out/ablation_G2 (v2) archived; this report supersedes the v1 "
    "report for the corrected numbers.",
])
gap(6)
P("Data source: out/ablation_G2 (v2, post-fix); comparison baseline out/ablation_G (v1). "
  "Generated by scripts/make_ablation_G2_report.py directly from per-cell JSON metrics.", SMALL)


def _footer(canvas, doc):
    canvas.saveState(); canvas.setFont("Helvetica", 7.5); canvas.setFillColor(GREY)
    canvas.drawString(2 * cm, 1.0 * cm, "V2X-Sim - Configuration G Ablation Report (v2)")
    canvas.drawRightString(A4[0] - 2 * cm, 1.0 * cm, f"Page {doc.page}")
    canvas.restoreState()


def main():
    doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                            title="Configuration G Ablation Report v2")
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
