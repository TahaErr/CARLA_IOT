"""Generate SPRINT5_FINAL_ABLATION.pdf — polished 2-seed, 3-arm ablation report.

Reads out/ablation_sprint5_final/* and embeds the aggregator's collisions-vs-
penetration and map figures.

    python scripts/make_sprint5_final_pdf.py
"""
from __future__ import annotations
import glob
import json
import os
import statistics as st
from collections import Counter

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable, Image,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "out", "ablation_sprint5_final")
OUT = os.path.join(ROOT, "SPRINT5_FINAL_ABLATION.pdf")
FIGDIR = os.path.join(DATA, "combined", "figures")

ARMS = [("combined", "Combined (V2X+V2V)"),
        ("v2i_only", "V2I-only (no V2V)"),
        ("v2v_only", "V2V-only (no V2X)")]
MAPS = ["Town01", "Town05", "Town10HD_Opt"]
WEA = ["ClearNoon", "HardRainNoon"]
PENS = [0.0, 0.5, 0.9, 1.0]

NAVY = colors.HexColor("#1f2d4d"); BLUE = colors.HexColor("#1f77b4")
GREEN = colors.HexColor("#2ca02c"); RED = colors.HexColor("#b3261e")
AMBER = colors.HexColor("#9a6700"); GREY = colors.HexColor("#5b6470")
LIGHT2 = colors.HexColor("#f7f9fc"); GREENBG = colors.HexColor("#eaf6ec")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=15, textColor=NAVY, spaceBefore=14, spaceAfter=6, leading=18)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=12, textColor=BLUE, spaceBefore=10, spaceAfter=4, leading=15)
BODY = ParagraphStyle("BODY", parent=ss["BodyText"], fontSize=9.5, leading=14, spaceAfter=6, alignment=TA_LEFT)
SMALL = ParagraphStyle("SMALL", parent=ss["BodyText"], fontSize=8, leading=11, textColor=GREY)
BULLET = ParagraphStyle("BULLET", parent=BODY, leftIndent=12, spaceAfter=3)
TITLE = ParagraphStyle("TITLE", parent=ss["Title"], fontSize=22, textColor=NAVY, leading=26, spaceAfter=2)
SUB = ParagraphStyle("SUB", parent=ss["Normal"], fontSize=11, textColor=GREY, alignment=TA_CENTER, leading=15)
CELL = ParagraphStyle("CELL", parent=BODY, fontSize=8.5, leading=11, spaceAfter=0)
CAP = ParagraphStyle("CAP", parent=SMALL, alignment=TA_CENTER)

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


def callout(title, text, bg=GREENBG, border=GREEN):
    inner = [[Paragraph(f"<b>{title}</b><br/>{text}", CELL)]]
    t = Table(inner, colWidths=[16.8 * cm], hAlign="LEFT")
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("BOX", (0, 0), (-1, -1), 0.6, border),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story.append(t)


def fig(name, caption, width=12.5 * cm):
    path = os.path.join(FIGDIR, name)
    if os.path.isfile(path):
        try:
            from PIL import Image as PILImage
            iw, ih = PILImage.open(path).size
            h = width * ih / iw
        except Exception:
            h = width * 0.62
        img = Image(path, width=width, height=h)
        img.hAlign = "CENTER"
        story.append(img)
        story.append(Paragraph(caption, CAP))
        gap(6)


def load(arm):
    out = {}
    for f in glob.glob(os.path.join(DATA, arm, "*.json")):
        d = json.load(open(f)); c = d["config"]
        out[(round(c["penetration"], 2), c["weather"], c["map"], c["seed"])] = d
    return out


D = {a: load(a) for a, _ in ARMS}
NCELLS = sum(len(D[a]) for a, _ in ARMS)


def sel(arm, key, p=None, m=None, w=None):
    return [r[key] for (pp, ww, mm, ss), r in D[arm].items()
            if (p is None or pp == p) and (m is None or mm == m) and (w is None or ww == w)]


def mean(arm, key, **kw):
    v = sel(arm, key, **kw); return sum(v) / len(v) if v else None


def ms(arm, key, **kw):
    v = sel(arm, key, **kw)
    return f"{st.mean(v):.1f}±{st.pstdev(v):.1f}" if v else "-"


def amean(arm, akey, sub, **kw):
    v = [r[akey].get(sub, 0) for (pp, ww, mm, ss), r in D[arm].items()
         if (kw.get('p') is None or pp == kw['p'])]
    return sum(v) / len(v) if v else None


def f1(x): return "-" if x is None else f"{x:.1f}"
def f2(x): return "-" if x is None else f"{x:.2f}"
def f0(x): return "-" if x is None else f"{x:.0f}"


# ---- cover ----
P("V2X-Sim &mdash; Cooperative Perception Study", SUB)
gap(4)
P("Sprint 5 &mdash; Final Ablation Report", TITLE)
P("Three-arm V2X / V2I / V2V penetration sweep &middot; 2 seeds &middot; 3 maps &middot; 2 weather", SUB)
gap(10)
story.append(HRFlowable(width="100%", thickness=1.2, color=NAVY))
gap(8)
callout(
    "Result",
    f"Replacing reckless human drivers with cooperative AVs yields a clean, monotonic safety gain: "
    f"mean collisions fall from <b>~22</b> (all-human baseline) to <b>~6</b> at full cooperative "
    f"penetration &mdash; a <b>~73% reduction</b> &mdash; with no inversion or plateau-then-rise. "
    f"All {NCELLS}/144 cells completed across two machines (seeds 0+1) with zero failures. A "
    f"consistent mild ordering holds: Combined &le; V2I-only &le; V2V-only.",
)
gap(8)

# ---- 1 design ----
H("1. Experimental design")
table([
    ["Dimension", "Value"],
    ["Communication arms", "Combined (V2X+V2V) | V2I-only (--no-v2v) | V2V-only (--no-v2x)"],
    ["Penetration p", "0.0, 0.5, 0.9, 1.0"],
    ["Maps", "Town01 (grid), Town05 (multi-lane), Town10HD_Opt (dense downtown)"],
    ["Weather", "ClearNoon, HardRainNoon"],
    ["Seeds", "0 + 1 (split across two machines)"],
    ["Sim duration", "90 s/cell @ dt 0.05 (20 Hz) | CPM/V2V 100 ms"],
    ["Population", "60 vehicles + 60 walkers"],
    ["HDV / CAV", "HOSTILE_MIX (attentive avoid; distracted+aggressive reckless) / AI_REALISTIC (7 m gap, steer-preserving, closing-gate)"],
    ["Cells", "144 (24/arm/seed)"],
], [4.2 * cm, 12.6 * cm])
gap(4)
P("Each value is a mean (± sd) over the 12 cells sharing a penetration (2 seeds × 3 maps "
  "× 2 weather). At p = 0.0 the fleet is 100% HDV — no V2X/V2V — so that column is the "
  "shared human baseline, identical across arms up to CARLA nondeterminism.", SMALL)

# ---- 2 headline ----
H("2. Headline &mdash; collisions by penetration and arm")
fig("collisions_vs_penetration.png",
    "Figure 1. Collisions vs penetration (Combined arm, mean ± sd over maps/weather/seeds).")
H("2a. Total collisions (mean ± sd)", H2)
rows = [["p", "Combined", "V2I-only", "V2V-only"]]
for p in PENS:
    rows.append([f"{p:.1f}", ms("combined", "collision_count", p=p), ms("v2i_only", "collision_count", p=p), ms("v2v_only", "collision_count", p=p)])
table(rows, [3.0 * cm] + [4.6 * cm] * 3)
gap(4)
H("2b. Primary collisions (frozen-wreck pileups excluded)", H2)
rows = [["p", "Combined", "V2I-only", "V2V-only"]]
for p in PENS:
    rows.append([f"{p:.1f}", ms("combined", "primary_collision_count", p=p), ms("v2i_only", "primary_collision_count", p=p), ms("v2v_only", "primary_collision_count", p=p)])
table(rows, [3.0 * cm] + [4.6 * cm] * 3)
gap(3)
P("Monotonic and steep on every arm: ~22 total / ~16 primary at the human baseline → ~6 / ~5 "
  "at full penetration. Combined ≤ V2I-only ≤ V2V-only at each p — infrastructure CPM "
  "is the stronger single channel; V2V-only is weakest but still beats baseline; both together best.", SMALL)

story.append(PageBreak())

# ---- 3 by map ----
H("3. Collisions by map")
fig("map_vs_collisions.png", "Figure 2. Collisions vs penetration per map (Combined arm).")
rows = [["Map", "p0.0", "p0.5", "p0.9", "p1.0"]]
for m in MAPS:
    rows.append([m] + [f1(mean("combined", "collision_count", p=p, m=m)) for p in PENS])
table(rows, [4.6 * cm] + [3.05 * cm] * 4)
gap(3)
P("Town05 (multi-lane) nearly eliminates collisions at full penetration (~2); Town01 drops to ~6; "
  "Town10HD_Opt plateaus ~10 — its dense junctions produce wide-turn / lane-crossing conflicts "
  "(a CARLA Traffic-Manager path-following limit on tight corners) that the cooperative layer can't "
  "fully prevent, so it caps the average.", SMALL)

# ---- 4 by weather ----
gap(6)
H("4. Collisions by weather")
rows = [["Weather", "p0.0", "p0.5", "p0.9", "p1.0"]]
for wx in WEA:
    rows.append([wx] + [f1(mean("combined", "collision_count", p=p, w=wx)) for p in PENS])
table(rows, [4.6 * cm] + [3.05 * cm] * 4)
gap(3)
P("HardRainNoon tracks ClearNoon closely — the cooperative stack is robust to the rain preset.", SMALL)

# ---- 5 per profile ----
gap(6)
H("5. At-fault collisions by driver profile (pooled)")
agg = Counter()
for x in D["combined"].values():
    for k, v in x.get("collisions_per_profile", {}).items():
        agg[k] += v
rows = [["Profile", "At-fault (sum)"]]
for k in ["attentive", "distracted", "aggressive_hostile", "ai_realistic"]:
    if k in agg:
        rows.append([k, str(agg[k])])
table(rows, [8.0 * cm, 4.0 * cm])
gap(3)
P("Reckless profiles (distracted + aggressive_hostile, avoidance OFF) dominate human-caused crashes "
  "as intended; attentive HDVs appear far less and mostly as victims. ai_realistic is the CAV total "
  "across all penetrations (high only because at high p every vehicle is a CAV).", SMALL)

# ---- 6 comms + perf ----
gap(6)
H("6. Cooperative-comms load & performance (Combined, mean)")
rows = [["p", "V2V recv", "Coop brakes", "CPMs", "frozen", "wall/sim"]]
for p in PENS:
    rows.append([f"{p:.1f}", f0(mean("combined", "v2v_received_total", p=p)),
                 f0(mean("combined", "cooperative_brakes", p=p)),
                 f0(mean("combined", "publishes_emitted", p=p)),
                 f1(mean("combined", "frozen_vehicle_count", p=p)),
                 f2(mean("combined", "wall_to_sim_ratio", p=p))])
table(rows, [2.2 * cm, 3.2 * cm, 3.0 * cm, 2.8 * cm, 2.6 * cm, 2.6 * cm])
gap(3)
P("V2V traffic + cooperative brakes scale with penetration (0 at baseline). Frozen wrecks fall "
  "~36→~10 as CAVs avoid conflicts.", SMALL)

story.append(PageBreak())

# ---- 7 model ----
H("7. The model &mdash; what produced this result")
bullets([
    "<b>Realism driver model:</b> attentive HDVs keep TM avoidance (never at-fault); "
    "distracted + aggressive_hostile have avoidance OFF and crash per their ignore-rates.",
    "<b>Velocity-matched ego self-exclusion (cav.py):</b> CAV still brakes for a stopped wreck at "
    "close range instead of treating it as its own RSU ghost.",
    "<b>Closing-rate gate on the distance fallback (cav.py):</b> emergency braking only fires when "
    "the gap is shrinking — no hard-braking on a safely-followed leader.",
    "<b>7 m CAV follow distance (hdv.py):</b> wider headway, far fewer panic stops.",
    "<b>Steer-preserving brake overrides (40_ablation_run.py):</b> highest-impact fix — a brake "
    "override no longer zeroes the wheel mid-turn, so CAVs stop arcing wide into oncoming traffic. "
    "Cut high-penetration collisions by &gt;50% in validation.",
    "<b>Primary/secondary split, determinism seeds, per-cell retry, server watchdog</b> for clean, "
    "reproducible, gap-free runs.",
])

# ---- 8 findings ----
H("8. Findings")
bullets([
    "<b>Cooperative perception works</b> — collisions fall monotonically with penetration, "
    "~73% baseline→full, on every arm and map.",
    "<b>Infrastructure (V2I) is the stronger channel</b> — Combined ≤ V2I-only ≤ "
    "V2V-only at every p; both help, combined is best.",
    "<b>Map complexity sets the floor</b> — Town05 ~eliminates collisions at full penetration; "
    "Town10HD_Opt plateaus ~10 due to junction-geometry artifacts.",
    "<b>Weather-robust</b> — ClearNoon and HardRainNoon give essentially the same curve.",
])
H("9. Threats to validity")
bullets([
    "2 seeds — real but modest variance (sd reported); arm-ordering gap is small relative to sd.",
    "Immobilise-in-place couples some incidents (mitigated by the primary metric).",
    "Town10 junction artifacts inflate that map's floor (simulator turn-geometry, not a perception "
    "failure).",
    "At-fault attribution credits the first sensor to fire, so attentive victims still appear in "
    "per-profile counts.",
])
gap(6)
P("Data: out/ablation_sprint5_final/{combined, v2i_only, v2v_only} (144 cells, seeds 0+1). "
  "Generated by scripts/make_sprint5_final_pdf.py. Full per-cell tables in SPRINT5_FINAL_ABLATION.md.", SMALL)


def _footer(canvas, doc):
    canvas.saveState(); canvas.setFont("Helvetica", 7.5); canvas.setFillColor(GREY)
    canvas.drawString(2 * cm, 1.0 * cm, "V2X-Sim - Sprint 5 Final Ablation")
    canvas.drawRightString(A4[0] - 2 * cm, 1.0 * cm, f"Page {doc.page}")
    canvas.restoreState()


def main():
    doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                            title="Sprint 5 Final Ablation Report")
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
