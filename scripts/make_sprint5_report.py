"""Generate the Sprint 5 PDF report.

Builds a standalone report covering the project scenario, the evolution
across Sprints 1-5, what Sprint 5 changed, the results, and the
performance characterisation. Pure reportlab/Platypus; ASCII-only text
(the built-in fonts lack arrow/superscript glyphs).

    python scripts/make_sprint5_report.py            # -> SPRINT5_REPORT.pdf
"""
from __future__ import annotations

import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable,
)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "SPRINT5_REPORT.pdf")

# === Palette ==============================================================
NAVY = colors.HexColor("#1f2d4d")
BLUE = colors.HexColor("#1f77b4")
GREEN = colors.HexColor("#2ca02c")
RED = colors.HexColor("#d62728")
GREY = colors.HexColor("#5b6470")
LIGHT = colors.HexColor("#eef1f6")
LIGHT2 = colors.HexColor("#f7f9fc")

# === Styles ===============================================================
ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=15, textColor=NAVY,
                    spaceBefore=14, spaceAfter=6, leading=18)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=12, textColor=BLUE,
                    spaceBefore=10, spaceAfter=4, leading=15)
BODY = ParagraphStyle("BODY", parent=ss["BodyText"], fontSize=9.5, leading=14,
                      spaceAfter=6, alignment=TA_LEFT)
SMALL = ParagraphStyle("SMALL", parent=ss["BodyText"], fontSize=8, leading=11,
                       textColor=GREY)
BULLET = ParagraphStyle("BULLET", parent=BODY, leftIndent=12, bulletIndent=2,
                        spaceAfter=3)
TITLE = ParagraphStyle("TITLE", parent=ss["Title"], fontSize=22, textColor=NAVY,
                       leading=26, spaceAfter=2)
SUB = ParagraphStyle("SUB", parent=ss["Normal"], fontSize=11, textColor=GREY,
                     alignment=TA_CENTER, leading=15)
CELL = ParagraphStyle("CELL", parent=BODY, fontSize=8.5, leading=11, spaceAfter=0)
CELLB = ParagraphStyle("CELLB", parent=CELL, textColor=colors.white)

story = []


def P(text, style=BODY):
    story.append(Paragraph(text, style))


def H(text, style=H1):
    story.append(Paragraph(text, style))


def gap(h=6):
    story.append(Spacer(1, h))


def bullets(items, style=BULLET):
    for it in items:
        story.append(Paragraph(f"&bull;&nbsp; {it}", style))


def table(data, col_widths, header=True, body_size=8.5, zebra=True):
    t = Table(data, colWidths=col_widths, hAlign="LEFT")
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), body_size),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#cdd4e0")),
        ("LINEAFTER", (0, 0), (-2, -1), 0.25, colors.HexColor("#e3e8f0")),
    ]
    if header:
        cmds += [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), body_size),
        ]
    if zebra:
        for r in range(1, len(data)):
            if r % 2 == 0:
                cmds.append(("BACKGROUND", (0, r), (-1, r), LIGHT2))
    t.setStyle(TableStyle(cmds))
    story.append(t)


# ==========================================================================
# COVER
# ==========================================================================
gap(40)
P("V2X-Sim &mdash; Sprint 5 Report", TITLE)
P("Collision Realism &amp; Vehicle-to-Vehicle (V2V) Communication", SUB)
gap(10)
P("Cooperative Perception at Smart Intersections", SUB)
P("A CARLA study of 5G NR-V2X with ETSI CPM Release 2 under realistic "
  "edge-compute and latency constraints in mixed traffic", SUB)
gap(18)
story.append(HRFlowable(width="60%", thickness=1.2, color=BLUE, hAlign="CENTER"))
gap(10)
P("CMP794 Final Project &nbsp;|&nbsp; Taha Yasin Er &amp; Doruk Top&ccedil;u", SUB)
P("Report generated 2026-05-30", SUB)
gap(22)

# Executive summary box
P("<b>Executive summary</b>", H2)
P("Sprint 5 hardened the simulation's realism and added vehicle-to-vehicle "
  "communication on top of the existing roadside-to-vehicle (V2I) stack. "
  "Four correctness fixes (collision counting, driver-role behaviour, spawn "
  "overlap, hostility scope) plus a new V2V layer turned the ablation from a "
  "metric with inflated, hard-to-trust numbers into a clean, reproducible "
  "safety experiment. Two headline results emerged: (1) <b>vehicle "
  "penetration is the dominant safety lever and it generalises across maps</b> "
  "&mdash; replacing hostile human drivers with careful connected-autonomous "
  "vehicles collapses collisions monotonically; and (2) <b>V2V's marginal "
  "value over roadside-only perception depends on scenario difficulty</b> "
  "&mdash; neutral on the easy in-distribution map, but a clear collision "
  "reduction on the harder held-out map. The test suite grew 215 -&gt; 241, "
  "all passing.")

story.append(PageBreak())

# ==========================================================================
# 1. SCENARIO & CONTEXT
# ==========================================================================
H("1.&nbsp; Scenario and project context")
P("The project studies <b>cooperative perception at signalised "
  "intersections</b>: roadside units (RSUs) with cameras detect road users "
  "and broadcast what they see to connected vehicles, which fuse those "
  "messages with their own sensing to act earlier and more safely in mixed "
  "traffic. The simulator is built on CARLA 0.9.16 and models the full "
  "pipeline end to end rather than assuming an idealised channel.")
gap(2)
P("<b>Pipeline.</b> RSU camera -&gt; YOLO26 detector -&gt; ETSI CPM message "
  "-&gt; V2X channel (packet loss + latency + channel-busy ratio) -&gt; "
  "connected-vehicle late-fusion -&gt; braking decision.", BODY)
P("<b>Actors / roles.</b>", H2)
bullets([
    "<b>HDV</b> &mdash; human-driven vehicle, modelled by CARLA's Traffic "
    "Manager with behavioural driver profiles (attentive / distracted / "
    "aggressive). The source of conflicts.",
    "<b>CAV</b> &mdash; connected autonomous vehicle: a Traffic-Manager "
    "vehicle that additionally runs the cooperative-perception fusion and "
    "braking logic, and (Sprint 5) the V2V layer.",
    "<b>RSU</b> &mdash; roadside unit: one overhead camera at an intersection "
    "running the detector and broadcasting ETSI CPMs.",
])
P("<b>Penetration rate</b> is the fraction of vehicles that are CAVs: "
  "p=0.0 is an all-HDV baseline, p=0.5 is mixed traffic, p=1.0 is a fully "
  "connected fleet. It is the primary independent variable of the ablation.")

# ==========================================================================
# 2. WHERE WE WERE — Sprints 1-4
# ==========================================================================
H("2.&nbsp; Where we were: Sprints 1&ndash;4")
P("Sprint 5 builds directly on four prior sprints. The table summarises what "
  "each delivered.")
gap(2)
rows = [
    ["Sprint", "Delivered", "Key outcome"],
    [Paragraph("<b>1 &mdash; RSU infrastructure</b>", CELL),
     Paragraph("Deterministic intersection discovery; single-camera RSU "
               "(worked around a CARLA 0.9.16 multi-camera crash).", CELL),
     Paragraph("Programmatic RSUs on Town03/04/05/10.", CELL)],
    [Paragraph("<b>2 &mdash; Detector</b>", CELL),
     Paragraph("YOLO26 fine-tuned on Town03+04+05 (4 classes: vehicle / "
               "motorcycle / bicycle / pedestrian).", CELL),
     Paragraph("Held-out Town10: mAP@50 = 0.53, precision 0.85, recall 0.50.", CELL)],
    [Paragraph("<b>3 &mdash; V2X protocol stack</b>", CELL),
     Paragraph("CARLA-agnostic: ETSI CPM encoder, Coll-Perales latency model, "
               "Thandavarayan packet-delivery model, edge-compute budget, "
               "in-process broker.", CELL),
     Paragraph("Literature-grounded channel; 112 unit tests.", CELL)],
    [Paragraph("<b>4 &mdash; CARLA integration + ablation</b>", CELL),
     Paragraph("Camera projection, CARLA-bound RSU/CAV, the CAV late-fusion "
               "core (time-aware fusion + 3-rule hysteresis + time-to-collision "
               "ladder), NHTSA-style HDV profiles, the ablation runner.", CELL),
     Paragraph("First penetration sweep + a cross-map / weather / VRU "
               "extension (135 cells, 5 findings).", CELL)],
]
table(rows, [3.0 * cm, 8.6 * cm, 5.4 * cm])
gap(4)
P("<b>Carried-forward issues that Sprint 5 targets.</b> The Sprint 4 ablation "
  "was scientifically useful but had four realism problems: collision counts "
  "were inflated by counting contact-frames rather than incidents; every "
  "vehicle (including the notionally-autonomous ones) was made hostile; some "
  "vehicles spawned overlapping; and there was no vehicle-to-vehicle link "
  "&mdash; only roadside-to-vehicle.", BODY)

story.append(PageBreak())

# ==========================================================================
# 3. WHAT SPRINT 5 CHANGES
# ==========================================================================
H("3.&nbsp; What Sprint 5 changes")
P("Five aims, each a concrete before/after change.")
gap(2)
rows = [
    ["#", "Aim", "Before (Sprint 4)", "After (Sprint 5)"],
    ["1",
     Paragraph("Fix the collision counter", CELL),
     Paragraph("Counted contact-frames with a 1 s per-pair window; stuck/"
               "interpenetrating cars kept firing the sensor, inflating counts "
               "(e.g. ~650).", CELL),
     Paragraph("<b>One incident per unordered pair</b>; on contact both "
               "vehicles are <b>immobilised</b> (autopilot off, full brake + "
               "handbrake, physics frozen). Trustworthy counts; no actor "
               "destruction (avoids a Windows crash).", CELL)],
    ["2",
     Paragraph("Add V2V communication", CELL),
     Paragraph("Only RSU -&gt; CAV (V2I). Vehicles could not share what they "
               "saw or intended.", CELL),
     Paragraph("CAVs broadcast <b>perceived objects</b> (CPM-style) and "
               "<b>own pose + hard-brake intent</b> (CAM/DENM-style) to nearby "
               "CAVs; receivers fuse objects and pre-brake on a leader's "
               "warning. Same channel model.", CELL)],
    ["3",
     Paragraph("Vehicles spawn inside each other", CELL),
     Paragraph("Forced spawn on raw spawn points; nearby points produced "
               "overlapping vehicles.", CELL),
     Paragraph("<b>try_spawn_actor</b> (skips blocked spawns) + a "
               "<b>minimum-separation filter</b> on chosen points.", CELL)],
    ["4",
     Paragraph("Only HDVs should be hostile", CELL),
     Paragraph("Hostile mix applied to <b>all</b> vehicles; collision "
               "avoidance disabled for all.", CELL),
     Paragraph("<b>Role split</b>: HDVs = hostile mix, avoidance OFF (conflict "
               "generators). CAVs = new <b>AI_REALISTIC</b> profile (~1% rule-"
               "error rate, never ignores vehicles/pedestrians), avoidance ON.", CELL)],
    ["5",
     Paragraph("Run a new ablation", CELL),
     Paragraph("Single-phase sweep with the issues above.", CELL),
     Paragraph("<b>Two-phase V2V-isolation</b> sweep (V2V on vs V2I-only) on "
               "the Sprint 4 matrix; results in section 5.", CELL)],
]
table(rows, [0.7 * cm, 3.0 * cm, 6.4 * cm, 6.9 * cm])
gap(4)
P("Implementation added one module (<font face='Courier'>v2xsim/v2v.py</font>), "
  "extended four (<font face='Courier'>hdv, cav, carla_cav, carla_rsu</font>), "
  "and reworked the runner. <b>Tests grew 215 -&gt; 241, all passing.</b>", BODY)

# ==========================================================================
# 4. METHODOLOGY
# ==========================================================================
H("4.&nbsp; Methodology")
P("<b>Ablation design.</b> The headline experiment is a two-phase comparison "
  "that isolates the V2V contribution: every cell is run once with the full "
  "V2V system and once V2I-only (<font face='Courier'>--no-v2v</font>, CAVs "
  "keep RSU messages + their own sensor but no CAV-to-CAV link). Differences "
  "are therefore attributable to V2V alone.")
bullets([
    "<b>Matrix:</b> 3 maps (Town05 in-distribution, Town10HD_Opt held-out, "
    "Town01) x 3 weather x 3 penetration (0 / 0.5 / 1.0) x 5 seeds.",
    "<b>Population:</b> 60 vehicles + 60 pedestrians; 3 RSUs; 120 s of "
    "simulation per cell at max fidelity (20 Hz physics, 10 Hz broadcast).",
    "<b>Metrics:</b> collisions (total and CAV-involved, counted as distinct "
    "incidents), braking actions, phantom-brake suppression, cooperative "
    "brakes, V2V throughput, channel-busy ratio.",
    "<b>Robustness:</b> one OS process per cell (crash isolation), resumable, "
    "per-cell timeout, wall-clock deadline, and a CARLA-server watchdog.",
])
P("<b>Comparability caveat.</b> Because Sprint 4 counted contact-frames and "
  "Sprint 5 counts incidents, the <i>absolute</i> collision numbers are not "
  "comparable across sprints. The valid comparisons are <b>trends</b> "
  "(shape vs penetration) and the <b>V2V-on vs V2V-off</b> contrast within "
  "Sprint 5.", BODY)

story.append(PageBreak())

# ==========================================================================
# 5. RESULTS
# ==========================================================================
H("5.&nbsp; Results")
P("<b>5.1&nbsp; Town05 &mdash; complete V2V on/off isolation</b> "
  "(mean over 3 weather x 5 seeds, n=15 per cell). Collisions shown as "
  "total / CAV-involved.", H2)
rows = [
    ["Penetration", "V2I-only coll.", "+V2V coll.", "V2I hard-brakes", "+V2V hard-brakes"],
    ["0.0  (all HDV)", "27.5 / 0.0", "27.5 / 0.0", "0", "0"],
    ["0.5  (mixed)", "14.7 / 7.3", "15.5 / 7.3", "2,782", "13,892"],
    ["1.0  (all CAV)", "2.0 / 2.0", "3.2 / 3.2", "6,543", "45,651"],
]
table(rows, [3.4 * cm, 3.0 * cm, 3.0 * cm, 3.3 * cm, 3.3 * cm])
gap(6)
P("<b>5.2&nbsp; Town10HD_Opt &mdash; cross-map generalisation</b> "
  "(V2V phase; held-out map).", H2)
rows = [
    ["Penetration", "+V2V coll. (total / CAV)", "hard-brakes", "n"],
    ["0.0", "42.0 / 0.0", "0", "10"],
    ["0.5", "26.3 / 15.0", "13,756", "10"],
    ["1.0", "8.5 / 8.5", "45,398", "4 (others timed out)"],
]
table(rows, [3.0 * cm, 5.0 * cm, 3.2 * cm, 4.8 * cm])
gap(6)
P("<b>5.3&nbsp; V2V on/off across maps</b> at p=0.5 (the penetration where the "
  "two phases overlap on both maps).", H2)
rows = [
    ["Map", "V2I-only (total / CAV)", "+V2V (total / CAV)", "Change"],
    [Paragraph("Town05 (easy, in-dist, n=15)", CELL), "14.7 / 7.3", "15.5 / 7.3",
     Paragraph("~0 (no benefit)", CELL)],
    [Paragraph("Town10HD_Opt (hard, held-out, n~10)", CELL), "32.2 / 20.8",
     Paragraph("<b>26.3 / 15.0</b>", CELL),
     Paragraph("<b>-18% / -28%</b>", CELL)],
]
table(rows, [5.4 * cm, 4.0 * cm, 4.0 * cm, 2.6 * cm])
gap(8)

P("<b>Findings</b>", H2)
P("<b>Finding 1 &mdash; penetration is the dominant safety lever, and it "
  "generalises.</b> Replacing hostile HDVs with careful CAVs collapses "
  "collisions monotonically on both the in-distribution map (27.5 -&gt; 14.7 "
  "-&gt; 2.0) and the held-out Town10 (42 -&gt; 26 -&gt; 8.5). The Sprint 5 "
  "role split is the headline win and it is not a single-map artefact.", BODY)
P("<b>Finding 2 &mdash; V2V's marginal value over roadside-only perception "
  "depends on scenario difficulty.</b> On easy Town05 the RSU coverage already "
  "catches most conflicts, so V2V adds only braking churn (~5x more "
  "hard-brakes) with no collision benefit. On the harder, denser held-out "
  "Town10, V2V <b>cuts collisions 18% and CAV-involved collisions 28%</b> at "
  "p=0.5 &mdash; the extra cooperative perception pays off where there is more "
  "to catch.", BODY)
P("<b>Finding 3 &mdash; reactive cooperative braking has a cost.</b> V2V "
  "multiplies hard-braking 3&ndash;5x, and at full penetration on Town05 it is "
  "slightly worse than V2I-only (2.0 -&gt; 3.2): a saturation / string-"
  "instability effect of purely reactive braking. This points to "
  "<b>coordinated</b> (rather than independently reactive) longitudinal "
  "control as the natural next step &mdash; consistent with the Sprint 4 "
  "'saturation and rebound' observation, now cleanly isolated.", BODY)

story.append(PageBreak())

# ==========================================================================
# 6. PERFORMANCE
# ==========================================================================
H("6.&nbsp; Performance characterisation")
P("During the run the GPU and CPU sat at low utilisation while the simulator "
  "window stuttered &mdash; the classic signature of a workload that is "
  "<b>waiting, not computing</b>.")
bullets([
    "<b>Synchronous-mode ping-pong:</b> client and server alternate (one ticks "
    "while the other is idle), so neither is ever saturated.",
    "<b>Per-actor RPC flurry:</b> the runner originally made one CARLA remote "
    "call per actor per tick (poses, sensor snapshot, control). At full "
    "penetration with 120 actors that is ~500 round-trips/tick &mdash; ~150 ms "
    "of pure wire latency per frame.",
    "<b>O(N^2) V2V message storm:</b> at p=1.0, 60 CAVs broadcasting to each "
    "other generate ~500,000 messages per 30 s of simulation, all decoded and "
    "fused by a single-threaded Python broker.",
])
P("<b>Fix and outcome.</b> All reads were batched into a single per-tick world "
  "snapshot and all vehicle controls into one batched call. This gave a ~1.4x "
  "speedup and stopped the heaviest cells timing out, but it exposed the V2V "
  "message volume as the real ceiling at high penetration. That ceiling is "
  "<b>itself a result</b>: cooperative-perception load scales quadratically "
  "with connected-vehicle density &mdash; directly relevant to the project's "
  "edge-compute and channel-congestion theme.", BODY)
P("<b>Practical consequence.</b> A full 3-map x both-phase sweep at maximum "
  "fidelity does not fit an overnight window. Sprint 5 therefore prioritised "
  "and completed the clean Town05 V2V on/off comparison plus the Town10 "
  "cross-map generalisation; the remaining cells (all of Town01, the Town10 "
  "V2I pair, and reliable Town10 p=1.0) are documented follow-ups that need "
  "either a faster timestep setting or a multi-day budget.", BODY)

# ==========================================================================
# 7. CONCLUSIONS
# ==========================================================================
H("7.&nbsp; Conclusions and future work")
bullets([
    "<b>The realism fixes worked:</b> collision counts are now trustworthy, "
    "roles are physically meaningful (hostile humans vs careful autonomy), and "
    "spawns are clean.",
    "<b>Safety scales with connected-vehicle penetration</b>, and the effect "
    "generalises to a held-out map.",
    "<b>V2V helps where the scenario is hard enough to need it</b>, at a "
    "braking-churn cost &mdash; motivating coordinated longitudinal control.",
    "<b>Cooperative-perception load is quadratic</b> in CAV density, a "
    "concrete edge-compute / channel finding.",
])
P("<b>Future work:</b> coordinated (non-reactive) cooperative braking; "
  "complete the cross-map V2V-isolation (Town01 + Town10 V2I) at a faster "
  "timestep; per-detection confidence weighting to handle lower detector "
  "quality on out-of-distribution maps.", BODY)

# ==========================================================================
# 8. APPENDIX
# ==========================================================================
H("8.&nbsp; Appendix")
P("<b>New / changed code (Sprint 5)</b>", H2)
rows = [
    ["File", "Role"],
    ["v2xsim/v2v.py (new)", "V2V message: perceived objects + pose + hard-brake intent"],
    ["v2xsim/hdv.py", "AI_REALISTIC profile; role-aware avoidance disable"],
    ["v2xsim/cav.py", "Cooperative brake-warning ingestion + reaction"],
    ["v2xsim/carla_cav.py", "V2V send/receive; snapshot ego-state path"],
    ["scripts/40_ablation_run.py", "Incident counting + immobilise; role split; V2V loop; spawn fix; batching"],
    ["scripts/42_..._subprocess.py", "--no-v2v, --max-hours deadline, server watchdog"],
]
table(rows, [6.2 * cm, 10.8 * cm])
gap(6)
P("<b>New runner knobs</b>", H2)
rows = [
    ["Flag", "Default", "Purpose"],
    ["--no-v2v", "off", "V2I-only arm (isolate V2V)"],
    ["--v2v-range", "150 m", "CAV-to-CAV broadcast range"],
    ["--cpm-period-ms", "100 (10 Hz)", "Broadcast cadence; 200 ms ~1.7x faster"],
    ["--dt", "0.05 (20 Hz)", "Physics timestep; 0.1 ~2.3x faster, coarser"],
    ["--cav-attentive", "off", "CAVs flawless instead of AI_REALISTIC"],
]
table(rows, [3.6 * cm, 3.2 * cm, 10.2 * cm])
gap(8)
P("Detailed change log and raw cell data: <font face='Courier'>SPRINT5_RESULTS.md</font>, "
  "<font face='Courier'>out/ablation_sprint5_full/{v2v,noV2V}/summary*.csv</font>.", SMALL)


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GREY)
    canvas.drawString(2 * cm, 1.1 * cm, "V2X-Sim  |  Sprint 5 Report")
    canvas.drawRightString(A4[0] - 2 * cm, 1.1 * cm, "Page %d" % doc.page)
    canvas.setStrokeColor(colors.HexColor("#cdd4e0"))
    canvas.line(2 * cm, 1.4 * cm, A4[0] - 2 * cm, 1.4 * cm)
    canvas.restoreState()


doc = SimpleDocTemplate(
    OUT, pagesize=A4,
    leftMargin=2 * cm, rightMargin=2 * cm,
    topMargin=1.8 * cm, bottomMargin=1.8 * cm,
    title="V2X-Sim Sprint 5 Report",
    author="Taha Yasin Er & Doruk Topcu",
)
doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
print("wrote", OUT)
