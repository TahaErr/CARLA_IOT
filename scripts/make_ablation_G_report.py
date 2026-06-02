"""Generate the Configuration-G ablation PDF report.

Reads the raw per-cell JSONs under out/ablation_G/{combined,v2i_only,v2v_only}
and synthesises a self-contained report: experimental design, the code
changes that produced this run, the full result tables (collisions by
penetration / map / weather / arm, communication load, performance), and an
HONEST findings section documenting the inverted/flat safety curve plus the
braking regression that explains it.

Pure reportlab/Platypus; ASCII-only text (built-in fonts lack fancy glyphs).

    python scripts/make_ablation_G_report.py   # -> ABLATION_G_REPORT.pdf
"""
from __future__ import annotations

import glob
import json
import os
from collections import defaultdict

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "out", "ablation_G")
OUT = os.path.join(ROOT, "ABLATION_G_REPORT.pdf")

ARMS = [("combined", "Combined (V2X+V2V)"),
        ("v2i_only", "V2I-only (no V2V)"),
        ("v2v_only", "V2V-only (no V2X)")]
MAPS = ["Town01", "Town05", "Town10HD_Opt"]
WEATHERS = ["ClearNoon", "HardRainNoon"]
PENS = [0.0, 0.5, 0.9, 1.0]

# ---- colours / styles -----------------------------------------------------
NAVY = colors.HexColor("#1f2d4d")
BLUE = colors.HexColor("#1f77b4")
GREEN = colors.HexColor("#2ca02c")
RED = colors.HexColor("#b3261e")
AMBER = colors.HexColor("#9a6700")
GREY = colors.HexColor("#5b6470")
LIGHT2 = colors.HexColor("#f7f9fc")
BOXBG = colors.HexColor("#fbf4e6")
REDBG = colors.HexColor("#fdecea")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=15, textColor=NAVY,
                    spaceBefore=14, spaceAfter=6, leading=18)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=12, textColor=BLUE,
                    spaceBefore=10, spaceAfter=4, leading=15)
BODY = ParagraphStyle("BODY", parent=ss["BodyText"], fontSize=9.5, leading=14,
                      spaceAfter=6, alignment=TA_LEFT)
SMALL = ParagraphStyle("SMALL", parent=ss["BodyText"], fontSize=8, leading=11,
                       textColor=GREY)
BULLET = ParagraphStyle("BULLET", parent=BODY, leftIndent=12, spaceAfter=3)
TITLE = ParagraphStyle("TITLE", parent=ss["Title"], fontSize=22, textColor=NAVY,
                       leading=26, spaceAfter=2)
SUB = ParagraphStyle("SUB", parent=ss["Normal"], fontSize=11, textColor=GREY,
                     alignment=TA_CENTER, leading=15)
CELL = ParagraphStyle("CELL", parent=BODY, fontSize=8.5, leading=11, spaceAfter=0)

story = []


def P(t, s=BODY): story.append(Paragraph(t, s))
def H(t, s=H1): story.append(Paragraph(t, s))
def gap(h=6): story.append(Spacer(1, h))
def bullets(items):
    for it in items:
        story.append(Paragraph(f"&bull;&nbsp; {it}", BULLET))


def table(data, col_widths, header=True, size=8.5):
    t = Table(data, colWidths=col_widths, hAlign="LEFT")
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), size),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#cdd4e0")),
    ]
    if header:
        cmds += [("BACKGROUND", (0, 0), (-1, 0), NAVY),
                 ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                 ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    for r in range(1, len(data)):
        if r % 2 == 0:
            cmds.append(("BACKGROUND", (0, r), (-1, r), LIGHT2))
    t.setStyle(TableStyle(cmds))
    story.append(t)


def callout(title, text, bg=BOXBG, border=AMBER):
    inner = [[Paragraph(f"<b>{title}</b><br/>{text}", CELL)]]
    t = Table(inner, colWidths=[16.8 * cm], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 0.6, border),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)


# ---- load data ------------------------------------------------------------
def load_arm(arm):
    out = {}
    for f in glob.glob(os.path.join(DATA_DIR, arm, "*.json")):
        d = json.load(open(f))
        c = d["config"]
        out[(round(c["penetration"], 2), c["weather"], c["map"])] = d
    return out


DATA = {a: load_arm(a) for a, _ in ARMS}
NCELLS = {a: len(DATA[a]) for a, _ in ARMS}


def avg(arm, metric, pen=None, mp=None, wea=None):
    vals = []
    for (p, w, m), d in DATA[arm].items():
        if pen is not None and abs(p - pen) > 1e-6:
            continue
        if mp is not None and m != mp:
            continue
        if wea is not None and w != wea:
            continue
        v = d
        for key in metric.split("."):
            v = v.get(key, 0) if isinstance(v, dict) else 0
        vals.append(v)
    return (sum(vals) / len(vals)) if vals else None


def cell(arm, metric, pen, fmt="{:.1f}"):
    v = avg(arm, metric, pen=pen)
    return fmt.format(v) if v is not None else "-"


# ===========================================================================
# COVER
# ===========================================================================
P("V2X-Sim &mdash; Cooperative Perception Study", SUB)
gap(4)
P("Configuration G Ablation Report", TITLE)
P("Three-arm V2X / V2I / V2V penetration sweep across three maps and two weather presets", SUB)
gap(10)
story.append(HRFlowable(width="100%", thickness=1.2, color=NAVY))
gap(8)

total = sum(NCELLS.values())
callout(
    "At a glance",
    f"This run completed {total} of 72 planned cells (combined {NCELLS['combined']}/24, "
    f"v2i_only {NCELLS['v2i_only']}/24, v2v_only {NCELLS['v2v_only']}/24). The cooperative "
    "communication stack is mechanically active and the simulation is stable across all "
    "three maps. <b>However, the safety result is inverted and flat:</b> collisions rise "
    "when connected vehicles are introduced, and the three communication arms are "
    "statistically indistinguishable. This report documents the design, the data, and the "
    "root cause &mdash; a braking-logic regression introduced alongside the deadlock fix &mdash; "
    "so the numbers are not mistaken for a finished result.",
    bg=REDBG, border=RED,
)
gap(8)

# ===========================================================================
# 1. EXPERIMENTAL DESIGN
# ===========================================================================
H("1. Experimental design")
P("Configuration G is a 2&times;2-style technology ablation that isolates the contribution of "
  "each cooperative channel as the connected-vehicle penetration rate sweeps from an all-human "
  "baseline to a fully connected fleet. Every cell runs in CARLA 0.9.16 synchronous mode on a "
  "single Epic-quality server.")
table([
    ["Dimension", "Values"],
    ["Communication arms", "Combined (V2X+V2V) | V2I-only (--no-v2v) | V2V-only (--no-v2x)"],
    ["Penetration p", "0.0, 0.5, 0.9, 1.0  (fraction of vehicles that are CAVs)"],
    ["Maps", "Town01 (grid), Town05 (multi-lane), Town10HD_Opt (dense downtown)"],
    ["Weather", "ClearNoon, HardRainNoon"],
    ["Seeds", "0 (single seed)"],
    ["Sim duration", "60 s per cell  @ dt 0.05 (20 Hz physics)"],
    ["Population", "60 vehicles + 60 walkers"],
    ["HDV behaviour", "HOSTILE_MIX: 50% attentive, 20% distracted (20% ignore-veh), 30% aggressive-hostile (40% ignore-veh)"],
    ["CAV behaviour", "AI_REALISTIC: 3.0 m lead gap, ~1% rule slips, TM avoidance ON"],
    ["RSU CPM / V2V cadence", "10 Hz (100 ms)"],
    ["Cells per arm / total", "24 (3 maps x 2 weather x 4 pen) / 72 planned"],
], [4.6 * cm, 12.2 * cm])
gap(4)
P("At p = 0.0 there are no CAVs, so that cell is the shared no-V2X / no-V2V human baseline "
  "regardless of arm. The two missing v2i_only cells (Town01 p0.0 ClearNoon and p0.9 HardRainNoon) "
  "crashed at spawn with empty logs and are excluded from that arm's averages.", SMALL)

# ===========================================================================
# 2. WHAT CHANGED
# ===========================================================================
H("2. Code changes that produced this run")
P("This sweep was run after a round of fixes targeting four reported defects: immediate "
  "spawn-time crashes, absurd hard-braking between vehicles in opposing lanes, V2V channel "
  "congestion slowing the sim, and CAVs failing to stop for hazards. The changes:")
bullets([
    "<b>Broker dispatch O(N^2)-&gt;O(N):</b> per-receiver message queues replace the flat scan; "
    "CPM/V2V payload decoding is memoised (lru_cache). This removed the V2V congestion slowdown.",
    "<b>V2V directional + lateral gating:</b> a received hard-brake warning now only acts if the "
    "sender is ahead within the heading cone (yaw dot-product &gt; 0) AND within 2.0 m lateral "
    "offset &mdash; killing the opposing-lane phantom braking.",
    "<b>Distance-based safety fallback:</b> a confirmed in-lane track triggers DECELERATE / "
    "SOFT_BRAKE / HARD_BRAKE at 9.0 / 6.5 / 4.0 m even when TTC is undefined (stopped wreck case).",
    "<b>Restored TM avoidance for HDVs:</b> the blanket disable_collision_detection_for() call was "
    "removed so HDVs no longer pile up at spawn; conflicts now come from their profile ignore-rates.",
    "<b>HDV ignore-rate boost:</b> aggressive-hostile ignore-vehicles 10%-&gt;40%, distracted "
    "10%-&gt;20%, to keep a non-trivial baseline conflict rate with TM avoidance back on.",
    "<b>Ego self-exclusion (the deadlock fix):</b> tracks within 3.0 m of ego centre are dropped to "
    "stop CAVs braking on the RSU's ghost reflection of their own body. <b>This is the prime suspect "
    "for the regression below</b> &mdash; see section 4.",
])

story.append(PageBreak())

# ===========================================================================
# 3. RESULTS
# ===========================================================================
H("3. Results")

H("3.1 Total collisions by penetration and arm", H2)
P("Mean collision incidents per cell, averaged over the 3 maps and 2 weather presets. Lower is "
  "better; a working cooperative stack should fall as p rises and should differ between arms.")
rows = [["p", "Combined", "V2I-only", "V2V-only"]]
for p in PENS:
    rows.append([f"{p:.1f}", cell("combined", "collision_count", p),
                 cell("v2i_only", "collision_count", p),
                 cell("v2v_only", "collision_count", p)])
table(rows, [3.0 * cm] + [4.6 * cm] * 3)
gap(3)
P("The curve goes the wrong way: collisions roughly <b>double</b> from the human baseline (p=0.0) "
  "to any connected condition, then stay flat. The three arms are within noise of each other at "
  "every penetration &mdash; turning V2X or V2V on or off barely moves the outcome.", SMALL)

gap(6)
H("3.2 Who is crashing (Combined arm)", H2)
rows = [["p", "CAV collisions", "HDV collisions", "VRU (pedestrian)"]]
for p in PENS:
    rows.append([f"{p:.1f}", cell("combined", "cav_collision_count", p),
                 cell("combined", "hdv_collision_count", p),
                 cell("combined", "vru_collision_count", p)])
table(rows, [3.0 * cm, 4.6 * cm, 4.6 * cm, 4.6 * cm])
gap(3)
P("As p rises the human crashes vanish (fewer HDVs remain) and are <b>more than replaced</b> by "
  "CAV crashes. The connected vehicles are the ones colliding &mdash; the opposite of the intended "
  "effect.", SMALL)

gap(6)
H("3.3 Collisions by map (Combined arm, averaged over weather)", H2)
rows = [["Map", "p0.0", "p0.5", "p0.9", "p1.0"]]
for m in MAPS:
    rows.append([m] + [f"{avg('combined', 'collision_count', pen=p, mp=m):.1f}"
                       if avg('combined', 'collision_count', pen=p, mp=m) is not None else "-"
                       for p in PENS])
table(rows, [4.6 * cm] + [3.05 * cm] * 4)
gap(3)
P("Town10HD_Opt (dense downtown) is the stress case at every penetration; Town01/Town05 are "
  "milder but show the same upward trend.", SMALL)

gap(6)
H("3.4 Cooperative-communication load (confirms the stack is live)", H2)
P("These metrics prove the messaging itself works: V2V traffic and cooperative brakes appear only "
  "in the arms that enable them, scaling with penetration. The problem is not that messages fail to "
  "flow &mdash; it is that they barely change driving outcomes.")
rows = [["p", "V2V recv (combined)", "Coop brakes (combined)", "Coop brakes (v2v-only)", "Coop brakes (v2i-only)"]]
for p in PENS:
    rows.append([f"{p:.1f}",
                 cell("combined", "v2v_received_total", p, "{:.0f}"),
                 cell("combined", "cooperative_brakes", p, "{:.0f}"),
                 cell("v2v_only", "cooperative_brakes", p, "{:.0f}"),
                 cell("v2i_only", "cooperative_brakes", p, "{:.0f}")])
table(rows, [2.0 * cm, 3.9 * cm, 3.9 * cm, 3.6 * cm, 3.4 * cm])
gap(3)
P("Half a million V2V messages per cell at high penetration, yet only ~65 cooperative-brake "
  "actions result &mdash; a vanishingly small share of the ~72,000 CAV decision cycles per cell. "
  "v2i-only correctly shows zero cooperative brakes (no V2V).", SMALL)

gap(6)
H("3.5 Performance (wall-to-sim ratio, Combined arm)", H2)
rows = [["Map", "p0.0", "p0.5", "p0.9", "p1.0"]]
for m in MAPS:
    rows.append([m] + [f"{avg('combined', 'wall_to_sim_ratio', pen=p, mp=m):.2f}"
                       if avg('combined', 'wall_to_sim_ratio', pen=p, mp=m) is not None else "-"
                       for p in PENS])
table(rows, [4.6 * cm] + [3.05 * cm] * 4)
gap(3)
P("Ratio = wall seconds per sim second (lower is faster than real time). The broker rewrite keeps "
  "even Town10 at p=1.0 around 4.4x &mdash; tractable, where earlier versions stalled. Cost scales "
  "with map density and penetration, as expected.", SMALL)

story.append(PageBreak())

# ===========================================================================
# 4. FINDINGS / ROOT CAUSE
# ===========================================================================
H("4. Findings and root cause")
P("Three facts in the data, taken together, identify the failure mode:")
bullets([
    "<b>Inverted curve:</b> collisions rise from ~6 (all-human) to ~9-11 once CAVs are present, "
    "then plateau. Adding connected vehicles makes things worse.",
    "<b>Flat across arms:</b> Combined, V2I-only and V2V-only are within noise at every "
    "penetration. The cooperative <i>content</i> is not what determines outcomes.",
    "<b>CAVs are the victims:</b> at high p the crashes are almost entirely CAV-on-something, and "
    "~15 of 60 vehicles end each Town cell frozen (immobilised after a collision).",
])
callout(
    "Root cause: the deadlock fix over-corrected",
    "The green-light deadlock was caused by CAVs braking on the RSU's ghost detection of their own "
    "body. The fix drops every track within 3.0 m of ego centre (cav.py ~L399, a blanket spatial "
    "'continue'). But it is a <b>position-only</b> gate: a genuine threat in that radius is "
    "discarded just like a self-ghost. Combined with a distance-fallback ladder whose 4.0 m "
    "hard-brake band sits below typical centre-to-centre spacing, the emergency-braking range is "
    "effectively blanked out. CAVs under-brake and drive into hazards. A correct fix must identify "
    "the ego-ghost by <b>velocity match</b> (co-located AND co-moving), not proximity alone.",
    bg=REDBG, border=RED,
)
gap(4)
P("The flat-across-arms result points to a second, structural contributor independent of braking "
  "tuning: when two vehicles collide they are immobilised in place, becoming stationary obstacles "
  "that downstream traffic &mdash; including careful CAVs &mdash; then rear-ends, propagating "
  "incidents. This inflates counts in a way no amount of message-passing can prevent, which is why "
  "the cooperative arms do not separate.")

# ===========================================================================
# 5. VALIDITY
# ===========================================================================
H("5. Threats to validity")
bullets([
    "<b>Single seed.</b> One spawn layout per cell; the +/-0 error bars are not real variance. "
    "Trends are directional only.",
    "<b>Braking regression.</b> Per section 4 the CAV decision layer is mis-calibrated for this "
    "run, so absolute collision counts overstate real CAV risk and must not be quoted as a "
    "V2X-effectiveness result.",
    "<b>Immobilise-as-obstacle.</b> The freeze-on-collision policy couples incidents together; it "
    "is a metric-design choice that needs review before the next sweep.",
    "<b>Two missing v2i cells.</b> Town01 p0.0 ClearNoon and p0.9 HardRainNoon crashed at spawn; "
    "v2i_only averages use the surviving cells.",
])

# ===========================================================================
# 6. NEXT STEPS
# ===========================================================================
H("6. Recommended next steps")
bullets([
    "Replace the 3.0 m self-exclusion with a velocity-matched ego-ghost filter and add a regression "
    "test asserting a closing in-lane track within 3 m still produces HARD_BRAKE.",
    "Audit the collision / immobilise loop in 40_ablation_run.py to quantify how many CAV crashes "
    "are secondary rear-ends into frozen wrecks vs primary failures.",
    "Re-validate on a small grid (1 map x 4 pen x combined arm) and confirm the curve falls before "
    "committing to a full multi-seed sweep.",
    "Once corrected, re-run Configuration G (or the larger Compromise matrix) for the report-grade "
    "result; keep this G data archived as the pre-fix baseline.",
])
gap(6)
P("Data source: out/ablation_G/{combined, v2i_only, v2v_only}. Generated by "
  "scripts/make_ablation_G_report.py directly from the per-cell JSON metrics.", SMALL)


# ---- build ----------------------------------------------------------------
def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GREY)
    canvas.drawString(2 * cm, 1.0 * cm, "V2X-Sim - Configuration G Ablation Report")
    canvas.drawRightString(A4[0] - 2 * cm, 1.0 * cm, f"Page {doc.page}")
    canvas.restoreState()


def main():
    doc = SimpleDocTemplate(OUT, pagesize=A4,
                            leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                            title="Configuration G Ablation Report")
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
