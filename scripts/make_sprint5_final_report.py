"""Generate the Sprint 5 FINAL PDF report.

Synthesises the whole project arc (Sprints 1-5), the Sprint 5 changes, the
complete Town05 penetration study (p = 0.0 / 0.5 / 0.9 / 1.0, V2V on/off),
the partial held-out Town10 cross-map, and a clear, evidence-backed
explanation of why the full Town10 / Town01 coverage is absent.

Pure reportlab/Platypus; ASCII-only text (built-in fonts lack arrow/
superscript glyphs).

    python scripts/make_sprint5_final_report.py   # -> SPRINT5_FINAL_REPORT.pdf
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
                   "SPRINT5_FINAL_REPORT.pdf")

NAVY = colors.HexColor("#1f2d4d")
BLUE = colors.HexColor("#1f77b4")
GREEN = colors.HexColor("#2ca02c")
RED = colors.HexColor("#b3261e")
AMBER = colors.HexColor("#9a6700")
GREY = colors.HexColor("#5b6470")
LIGHT2 = colors.HexColor("#f7f9fc")
BOXBG = colors.HexColor("#fbf4e6")

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


def callout(title, text):
    inner = [[Paragraph(f"<b>{title}</b><br/>{text}", CELL)]]
    t = Table(inner, colWidths=[16.8 * cm], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BOXBG),
        ("BOX", (0, 0), (-1, -1), 0.6, AMBER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)


# === COVER ================================================================
gap(34)
P("V2X-Sim &mdash; Sprint 5 Final Report", TITLE)
P("Collision Realism, Vehicle-to-Vehicle Communication, and a "
  "Mixed-Traffic Penetration Study", SUB)
gap(8)
P("Cooperative Perception at Smart Intersections &mdash; a CARLA study of "
  "5G NR-V2X with ETSI CPM Release 2", SUB)
gap(16)
story.append(HRFlowable(width="60%", thickness=1.2, color=BLUE, hAlign="CENTER"))
gap(8)
P("CMP794 Final Project &nbsp;|&nbsp; Taha Yasin Er &amp; Doruk Top&ccedil;u", SUB)
P("2026-06-02", SUB)
gap(18)
P("<b>Executive summary</b>", H2)
P("Sprint 5 turned the cooperative-perception ablation from a metric with "
  "inflated, hard-to-trust numbers into a clean, reproducible safety "
  "experiment, and added vehicle-to-vehicle (V2V) communication on top of "
  "the existing roadside-to-vehicle (V2I) stack. Four correctness fixes "
  "(collision counting, driver-role behaviour, spawn overlap, hostility "
  "scope) plus the V2V layer support a full penetration study on the "
  "in-distribution map (Town05) at p = 0.0 / 0.5 / 0.9 / 1.0, with every "
  "cell run both with and without V2V to isolate its effect.")
P("<b>Two results stand out.</b> (1) <b>Vehicle penetration is the dominant "
  "safety lever and it generalises:</b> replacing hostile human drivers with "
  "careful connected-autonomous vehicles drives collisions down "
  "monotonically (Town05 with V2V: 27.5 -&gt; 15.5 -&gt; 5.6 -&gt; 3.2), and "
  "the same trend holds on the held-out Town10 map. (2) <b>V2V's marginal "
  "value over roadside-only perception depends on scenario difficulty:</b> "
  "roughly neutral on the easy map at mid penetration, but a clear "
  "collision reduction on the harder held-out map, at the cost of a 3-7x "
  "increase in braking. The test suite grew 215 -&gt; 241, all passing.")
P("<b>Scope honesty.</b> The full Town10 cross-map and all of Town01 are "
  "absent by design: at full V2V penetration the single-threaded message-"
  "fusion cost grows super-linearly and those cells cannot complete in "
  "feasible wall-time at the study's fidelity. Section 6 explains this with "
  "profiling evidence and the deliberate decision not to lower fidelity for "
  "a subset (which would break comparability).")

story.append(PageBreak())

# === 1. SCENARIO =========================================================
H("1.&nbsp; Scenario and project context")
P("The project studies <b>cooperative perception at signalised "
  "intersections</b>: roadside units (RSUs) with cameras detect road users "
  "and broadcast them to connected vehicles, which fuse those messages with "
  "their own sensing to react earlier in mixed traffic. The whole pipeline "
  "is modelled end-to-end on CARLA 0.9.16 rather than assuming an idealised "
  "channel.")
P("<b>Pipeline:</b> RSU camera -&gt; YOLO26 detector -&gt; ETSI CPM message "
  "-&gt; V2X channel (packet loss + latency + channel-busy ratio) -&gt; "
  "connected-vehicle late-fusion -&gt; braking decision.")
P("<b>Roles:</b>", H2)
bullets([
    "<b>HDV</b> &mdash; human-driven vehicle (CARLA Traffic Manager + driver "
    "profiles). The conflict source.",
    "<b>CAV</b> &mdash; connected autonomous vehicle: runs cooperative-"
    "perception fusion + braking, and (Sprint 5) the V2V layer.",
    "<b>RSU</b> &mdash; one overhead camera per intersection running the "
    "detector and broadcasting CPMs.",
    "<b>Penetration (p)</b> &mdash; fraction of vehicles that are CAVs; the "
    "primary independent variable (0.0 all-HDV, 1.0 all-CAV).",
])

# === 2. SPRINTS 1-4 ======================================================
H("2.&nbsp; Where we were: Sprints 1&ndash;4")
rows = [
    ["Sprint", "Delivered", "Key outcome"],
    [Paragraph("<b>1 RSU infra</b>", CELL),
     Paragraph("Deterministic intersection discovery; single-camera RSU.", CELL),
     Paragraph("Programmatic RSUs on Town03/04/05/10.", CELL)],
    [Paragraph("<b>2 Detector</b>", CELL),
     Paragraph("YOLO26 fine-tuned on Town03+04+05 (4 classes).", CELL),
     Paragraph("Held-out Town10: mAP@50 0.53, P 0.85, R 0.50.", CELL)],
    [Paragraph("<b>3 V2X stack</b>", CELL),
     Paragraph("ETSI CPM encoder, Coll-Perales latency, Thandavarayan "
               "packet-delivery, edge-compute budget, in-process broker.", CELL),
     Paragraph("Literature-grounded channel; 112 tests.", CELL)],
    [Paragraph("<b>4 CARLA + ablation</b>", CELL),
     Paragraph("Camera projection, CARLA RSU/CAV, the CAV late-fusion core "
               "(time-aware fusion + 3-rule hysteresis + TTC ladder), NHTSA "
               "driver profiles, ablation runner.", CELL),
     Paragraph("Penetration sweep + cross-map/weather/VRU extension.", CELL)],
]
table(rows, [2.6 * cm, 8.8 * cm, 5.6 * cm])
gap(3)
P("<b>Issues Sprint 5 targets:</b> the Sprint 4 ablation counted collision "
  "contact-frames (inflated counts), made every vehicle hostile, spawned "
  "some vehicles overlapping, and had no vehicle-to-vehicle link.", BODY)

# === 3. WHAT SPRINT 5 CHANGES ============================================
H("3.&nbsp; What Sprint 5 changes")
rows = [
    ["#", "Aim", "Before", "After"],
    ["1", Paragraph("Collision counter", CELL),
     Paragraph("Contact-frames; stuck cars kept incrementing (~650).", CELL),
     Paragraph("<b>One incident per pair</b> + crashed cars <b>immobilised</b>. "
               "Trustworthy counts, no actor-destroy crash.", CELL)],
    ["2", Paragraph("Add V2V", CELL),
     Paragraph("Only RSU -&gt; CAV (V2I).", CELL),
     Paragraph("CAVs broadcast <b>perceived objects</b> (CPM) + <b>pose + "
               "hard-brake intent</b> (CAM/DENM); receivers fuse + pre-brake.", CELL)],
    ["3", Paragraph("Spawn overlap", CELL),
     Paragraph("Forced spawn on raw points; overlaps.", CELL),
     Paragraph("<b>try_spawn_actor</b> + minimum-separation filter.", CELL)],
    ["4", Paragraph("Hostility scope", CELL),
     Paragraph("Hostile mix on <b>all</b> vehicles.", CELL),
     Paragraph("<b>HDVs</b> hostile, avoidance OFF; <b>CAVs</b> careful "
               "AI_REALISTIC (~1% errors), avoidance ON.", CELL)],
    ["5", Paragraph("New ablation", CELL),
     Paragraph("Single-phase sweep with the issues above.", CELL),
     Paragraph("<b>Two-phase V2V-isolation</b> study (Section 5).", CELL)],
]
table(rows, [0.7 * cm, 2.7 * cm, 6.3 * cm, 7.1 * cm])
gap(3)
P("One new module (<font face='Courier'>v2v.py</font>), four extended, runner "
  "reworked. <b>Tests 215 -&gt; 241, all passing.</b>", BODY)

story.append(PageBreak())

# === 4. METHODOLOGY ======================================================
H("4.&nbsp; Methodology")
P("<b>Two-phase isolation.</b> Each cell is run once with the full V2V system "
  "and once V2I-only (CAVs keep RSU messages + their own sensor but no "
  "CAV-to-CAV link). Differences are attributable to V2V alone.")
bullets([
    "<b>Primary map:</b> Town05 (in-distribution) at <b>p = 0.0 / 0.5 / 0.9 / "
    "1.0</b>, 3 weather presets, 5 seeds &mdash; full V2V on/off.",
    "<b>Held-out map:</b> Town10HD_Opt, partial (see Section 6).",
    "<b>Population:</b> 60 vehicles + 60 pedestrians; 3 RSUs; 120 s/cell at "
    "max fidelity (20 Hz physics, 10 Hz broadcast).",
    "<b>Metrics:</b> collisions as distinct incidents (total and CAV-involved), "
    "braking actions, phantom-brake suppression, cooperative brakes.",
])
callout("Comparability caveat",
        "Sprint 4 counted contact-frames; Sprint 5 counts incidents, so the "
        "<i>absolute</i> collision numbers are not comparable across sprints. "
        "Valid comparisons are <b>trends</b> (shape vs penetration) and the "
        "<b>V2V-on vs V2V-off</b> contrast within Sprint 5.")

# === 5. RESULTS ==========================================================
H("5.&nbsp; Results")
P("<b>5.1&nbsp; Town05 &mdash; full penetration curve, V2V on/off</b> "
  "(mean over 3 weather x 5 seeds; collisions total / CAV-involved).", H2)
rows = [
    ["Penetration", "V2I-only coll.", "+V2V coll.", "V2I hard-brakes", "+V2V hard-brakes"],
    ["0.0  (all HDV)", "27.5 / 0.0", "27.5 / 0.0", "0", "0"],
    ["0.5  (mixed)", "14.7 / 7.3", "15.5 / 7.3", "2,782", "13,892"],
    ["0.9", "19.4 / 19.1*", "5.6 / 5.1", "6,047", "58,455"],
    ["1.0  (all CAV)", "2.0 / 2.0", "3.2 / 3.2", "6,543", "45,651"],
]
table(rows, [3.2 * cm, 3.1 * cm, 3.0 * cm, 3.3 * cm, 3.4 * cm])
P("* p=0.9 V2I-only n=14 (one seed missing) and is non-monotonic vs p=0.5 "
  "&mdash; treat that point as high-variance (see Finding 2).", SMALL)
gap(6)
P("<b>5.2&nbsp; Town10HD_Opt &mdash; held-out cross-map (partial)</b> "
  "(ClearNoon+ClearSunset where both phases exist).", H2)
rows = [
    ["Penetration", "V2I-only (tot/cav)", "+V2V (tot/cav)", "n", "note"],
    ["0.0", "41.3 / 0.0", "42.0 / 0.0", "10", "baseline (no CAVs)"],
    ["0.5", "32.2 / 20.8", "26.3 / 15.0", "9-10", "V2V -18% / -28%"],
    ["1.0", Paragraph("&mdash;", CELL), "8.5 / 8.5", "4", "V2V only, partial"],
]
table(rows, [2.4 * cm, 3.6 * cm, 3.6 * cm, 1.6 * cm, 4.8 * cm])
gap(8)
P("<b>Findings</b>", H2)
P("<b>Finding 1 &mdash; penetration is the dominant safety lever, and it "
  "generalises.</b> Replacing hostile HDVs with careful CAVs collapses "
  "collisions monotonically. The +V2V Town05 curve is clean: "
  "<b>27.5 -&gt; 15.5 -&gt; 5.6 -&gt; 3.2</b> across p = 0 / 0.5 / 0.9 / 1.0; "
  "the held-out Town10 +V2V curve follows the same shape "
  "(42 -&gt; 26 -&gt; 8.5). This role-split safety effect is the headline "
  "result and is not a single-map artefact.", BODY)
P("<b>Finding 2 &mdash; V2V's marginal value depends on scenario "
  "difficulty.</b> On easy Town05 at p=0.5 the RSU coverage already catches "
  "most conflicts, so V2V is roughly neutral on collisions (14.7 -&gt; 15.5). "
  "On the harder held-out Town10 at p=0.5, V2V cuts collisions "
  "<b>-18%</b> and CAV-involved <b>-28%</b> (32.2 -&gt; 26.3). The Town05 "
  "p=0.9 point shows a large apparent V2V benefit (19.4 -&gt; 5.6), but the "
  "V2I-only baseline there is anomalously high versus p=0.5 and rests on "
  "n=14, so we read it as <b>suggestive, not conclusive</b>: the +V2V value "
  "(5.6) fits the monotone trend, while the V2I spike is likely variance "
  "(or a real 'a few hostiles disrupt an un-coordinated CAV fleet' effect) "
  "that needs more seeds to separate.", BODY)
P("<b>Finding 3 &mdash; reactive cooperative braking has a cost.</b> V2V "
  "multiplies hard-braking 3-7x, and at full penetration on Town05 it is "
  "slightly worse than V2I-only (2.0 -&gt; 3.2): a saturation / string-"
  "instability effect of independently-reactive braking, pointing to "
  "<b>coordinated</b> longitudinal control as the next step.", BODY)

story.append(PageBreak())

# === 6. WHY TOWN10 IS INCOMPLETE =========================================
H("6.&nbsp; Coverage, and why the full Town10 / Town01 tests are absent")
P("This section is deliberately explicit, because the absence is a "
  "performance limit, not an oversight.")
P("<b>6.1&nbsp; What exists.</b>", H2)
bullets([
    "<b>Town05:</b> complete &mdash; V2V on/off at all four penetrations, "
    "3 weather x 5 seeds.",
    "<b>Town10HD_Opt (held-out):</b> partial &mdash; V2V on/off at p0 and p0.5 "
    "(n~10); p1.0 only V2V at n=4.",
    "<b>Town01:</b> not run.",
])
P("<b>6.2&nbsp; The measured reason.</b> A profiling run (a "
  "<font face='Courier'>--profile</font> mode added to the runner) breaks the "
  "Town10 p=1.0 cell down by loop section:", H2)
rows = [
    ["Section", "V2V on (ms/tick)", "V2I-only (ms/tick)"],
    ["world tick (physics+render)", "12.7", "14.8"],
    ["RSU YOLO (GPU)", "23.0", "19.7"],
    ["CAV decide (fuse + decode)", "207.1", "27.5"],
    ["V2V publish", "5.9", "n/a"],
    ["TOTAL", "248.9", "62.3"],
]
table(rows, [7.4 * cm, 4.8 * cm, 4.6 * cm])
gap(4)
P("The bottleneck is not the GPU (idle at ~8%), not YOLO, and not the V2V "
  "<i>broadcast</i> (6 ms). It is the <b>V2V receive path</b> inside each "
  "CAV's per-tick update: at full penetration the 60 CAVs each drain, "
  "JSON-decode and fuse roughly 59 incoming messages every period, and the "
  "broker's delivery scan is O(in-flight) <i>per CAV</i>. As the in-flight "
  "queue grows during a run, the per-tick cost grows too &mdash; "
  "<b>super-linear</b> &mdash; so a 120 s cell on the denser Town10 map "
  "exceeds even a 25-minute per-cell timeout. The work is single-threaded "
  "(Python GIL + deterministic synchronous lockstep), so the fast CPU cores "
  "and the GPU sit idle while one core does the fusion.", BODY)
callout("Why not just lower fidelity for Town10?",
        "A reduced tier (5 Hz broadcast + 0.1 s timestep, ~4x less work) does "
        "complete Town10 p=1.0 cells. But mixing a reduced-fidelity Town10 "
        "with the max-fidelity Town05 study would break the apples-to-apples "
        "comparison. We chose to <b>exclude the full Town10 sweep rather than "
        "report mismatched-fidelity numbers</b>. The held-out Town10 points we "
        "do report (p0/p0.5, and p1.0 V2V n=4) are all at the study's full "
        "fidelity.")
P("<b>6.3&nbsp; The fix (future work).</b> The cost is well-localised: index "
  "the broker's in-flight queue by receiver so each CAV's delivery drain is "
  "O(its own messages) instead of O(all in-flight), and decode each payload "
  "once instead of once per receiver. This removes the super-linear term and "
  "should make full-fidelity Town10 / Town01 feasible. It was scoped out of "
  "Sprint 5 to avoid a broker rewrite late in the cycle.", BODY)

# === 7. CONCLUSIONS ======================================================
H("7.&nbsp; Conclusions and future work")
bullets([
    "<b>Realism fixes worked:</b> collision counts are trustworthy, roles are "
    "physically meaningful, spawns are clean (Sprint 5 aims 1, 3, 4).",
    "<b>Safety scales with CAV penetration</b> and generalises to a held-out "
    "map &mdash; the clearest, most robust result.",
    "<b>V2V helps where the scenario is hard enough to need it</b>, at a "
    "braking-churn cost &mdash; motivating coordinated (non-reactive) control.",
    "<b>Cooperative-perception fusion cost is the scaling wall</b>: O(N^2) "
    "single-threaded message processing, not the GPU. A receiver-indexed "
    "broker is the unlock for full cross-map coverage.",
])
P("<b>Open items:</b> the broker receiver-index optimisation; completing "
  "Town10 and adding Town01 once it lands; more seeds to settle the p=0.9 "
  "point; per-detection confidence weighting for lower detector quality on "
  "out-of-distribution maps.", BODY)

# === 8. APPENDIX =========================================================
H("8.&nbsp; Appendix &mdash; data inventory")
rows = [
    ["Directory (out/)", "Contents", "Cells"],
    ["ablation_sprint5_full/v2v", "Town05 (full) + Town10 (partial) V2V-on", "69"],
    ["ablation_sprint5_full/noV2V", "Town05 (full) V2I-only", "45"],
    ["ablation_sprint5_full/noV2V_t10", "Town10 V2I-only p0/p0.5", "19"],
    ["ablation_sprint5_p09/v2v", "p=0.9 Town05 V2V-on", "15"],
    ["ablation_sprint5_p09/noV2V", "p=0.9 Town05 V2I-only", "14"],
]
table(rows, [6.4 * cm, 8.0 * cm, 2.4 * cm])
gap(4)
P("Each directory holds <font face='Courier'>summary.csv</font>, "
  "<font face='Courier'>summary_by_cell.csv</font> and "
  "<font face='Courier'>figures/</font>. Detailed engineering change-log and "
  "the reduced-tier mitigation are in "
  "<font face='Courier'>SPRINT5_RESULTS.md</font>; profiling breakdowns in "
  "<font face='Courier'>out/speedtest/profile_t10_p100*.json</font>. "
  "Test suite: 241 passing.", SMALL)


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GREY)
    canvas.drawString(2 * cm, 1.1 * cm, "V2X-Sim  |  Sprint 5 Final Report")
    canvas.drawRightString(A4[0] - 2 * cm, 1.1 * cm, "Page %d" % doc.page)
    canvas.setStrokeColor(colors.HexColor("#cdd4e0"))
    canvas.line(2 * cm, 1.4 * cm, A4[0] - 2 * cm, 1.4 * cm)
    canvas.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                        topMargin=1.8 * cm, bottomMargin=1.8 * cm,
                        title="V2X-Sim Sprint 5 Final Report",
                        author="Taha Yasin Er & Doruk Topcu")
doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
print("wrote", OUT)
