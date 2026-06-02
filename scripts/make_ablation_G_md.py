"""Generate ABLATION_G_RESULTS.md - full per-cell Config G results + findings.

Reads out/ablation_G/{combined,v2i_only,v2v_only}/*.json and emits a complete
markdown report (every town x weather x penetration x arm, plus all findings).

    python scripts/make_ablation_G_md.py
"""
from __future__ import annotations
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "out", "ablation_G")
OUT = os.path.join(ROOT, "ABLATION_G_RESULTS.md")

ARMS = [("combined", "Combined (V2X + V2V)"),
        ("v2i_only", "V2I-only (--no-v2v)"),
        ("v2v_only", "V2V-only (--no-v2x)")]
MAPS = ["Town01", "Town05", "Town10HD_Opt"]
WEA = ["ClearNoon", "HardRainNoon"]
PENS = [0.0, 0.5, 0.9, 1.0]


def load(arm):
    out = {}
    for f in glob.glob(os.path.join(DATA, arm, "*.json")):
        d = json.load(open(f))
        c = d["config"]
        a = d["actions_taken"]
        out[(round(c["penetration"], 2), c["weather"], c["map"])] = dict(
            coll=d["collision_count"], cav=d["cav_collision_count"],
            hdv=d["hdv_collision_count"], vru=d["vru_collision_count"],
            frozen=d["frozen_vehicle_count"], coop=d["cooperative_brakes"],
            phantom=d["phantom_brakes_suppressed"], v2vrecv=d["v2v_received_total"],
            cpm_emit=d["publishes_emitted"], dec=a.get("decelerate", 0),
            sb=a.get("soft_brake", 0), hb=a.get("hard_brake", 0),
            ratio=round(d["wall_to_sim_ratio"], 2), wall=round(d["wall_seconds"], 1),
            status=d["status"])
    return out


D = {a: load(a) for a, _ in ARMS}


def avg(arm, key, p=None, m=None, w=None):
    vs = [r[key] for (pp, ww, mm), r in D[arm].items()
          if (p is None or pp == p) and (m is None or mm == m) and (w is None or ww == w)]
    return sum(vs) / len(vs) if vs else None


def f1(x): return "-" if x is None else f"{x:.1f}"
def f0(x): return "-" if x is None else f"{x:.0f}"
def f2(x): return "-" if x is None else f"{x:.2f}"


O = []
def w(s=""): O.append(s)


w("# Configuration G - Full Ablation Results")
w()
w("**V2X-Sim cooperative-perception study - CARLA 0.9.16**  ")
w("Three-arm V2X / V2I / V2V penetration sweep. Generated directly from the per-cell "
  "JSON metrics in `out/ablation_G/{combined,v2i_only,v2v_only}`.")
w()
w("> **Status caveat - read first.** This run completed **70 / 72** cells and the cooperative "
  "communication stack is mechanically live, but the **safety result is inverted and flat**: "
  "collisions *rise* when connected vehicles are introduced and the three arms are statistically "
  "indistinguishable. The cause is a braking-logic regression introduced with the green-light "
  "deadlock fix (see Findings). Treat these numbers as a **pre-fix baseline, not a "
  "V2X-effectiveness result.**")
w()
w("---")
w()
w("## Where Configuration G sits among the sweep options")
w()
w("| Configuration | Sim Duration | Sweep Arms (V2V/V2X) | Penetration $p$ | Seeds | Weathers | Total Runs | Est. Wall Time |")
w("| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: |")
w("| A. \"Full + Full\" | 120 s | Combined / V2I-only / V2V-only | `0.0, 0.5, 0.9, 1.0` | `0,1,2,3,4` | `ClearNoon, ClearSunset, HardRainNoon` | 540 | ~43.5 h |")
w("| B. \"Compromise\" | 120 s | Same | `0.0, 0.5, 0.9, 1.0` | `0,1,2` | `ClearNoon` | 108 | ~8.7 h |")
w("| C. \"Fast Multi-Seed\" | 30 s | Same | `0.0, 0.5, 0.9, 1.0` | `0,1,2` | `ClearNoon` | 108 | ~1.7 h |")
w("| D. \"Minimal Trend\" | 120 s | Same | `0.0, 0.5, 0.9, 1.0` | `0` | `ClearNoon` | 36 | ~2.9 h |")
w("| E. \"Smoke/Ultralight\" | 30 s | Same | `0.0, 0.5, 0.9, 1.0` | `0` | `ClearNoon` | 36 | ~33 min |")
w("| **G. \"Weather & Map Focus\"** | **60 s** | **Same** | **`0.0, 0.5, 0.9, 1.0`** | **`0`** | **`ClearNoon, HardRainNoon`** | **72** | **~2.3 h** |")
w()
w("---")
w()
w("## 1. Experimental design")
w()
w("| Dimension | Values |")
w("| :--- | :--- |")
w("| Communication arms | Combined (V2X+V2V) / V2I-only (`--no-v2v`) / V2V-only (`--no-v2x`) |")
w("| Penetration $p$ | 0.0, 0.5, 0.9, 1.0 (fraction of vehicles that are CAVs) |")
w("| Maps | Town01 (grid), Town05 (multi-lane), Town10HD_Opt (dense downtown) |")
w("| Weather | ClearNoon, HardRainNoon |")
w("| Seeds | 0 (single seed) |")
w("| Sim duration | 60 s/cell @ dt 0.05 (20 Hz physics) |")
w("| Population | 60 vehicles + 60 walkers |")
w("| HDV behaviour | HOSTILE_MIX: 50% attentive, 20% distracted (20% ignore-veh), 30% aggressive-hostile (40% ignore-veh) |")
w("| CAV behaviour | AI_REALISTIC: 3.0 m lead gap, ~1% rule slips, TM avoidance ON |")
w("| RSU CPM / V2V cadence | 10 Hz (100 ms) |")
w("| Cells per arm / total | 24 (3 maps x 2 weather x 4 pen) / 72 planned |")
w()
w("At `p = 0.0` there are no CAVs, so that cell is the shared **no-V2X / no-V2V human baseline** "
  "in every arm. The two missing `v2i_only` cells (Town01 `p0.0` ClearNoon and `p0.9` HardRainNoon) "
  "crashed at spawn with empty logs and are excluded from that arm.")
w()
w("Cells actually completed: **combined 24/24, v2i_only 22/24, v2v_only 24/24.**")
w()
w("---")
w()
w("## 2. Headline - total collisions by penetration & arm")
w()
w("Mean collision incidents per cell, averaged over 3 maps x 2 weather. Lower is better; a working "
  "stack should *fall* as $p$ rises and *differ* between arms.")
w()
w("| $p$ | Combined | V2I-only | V2V-only |")
w("| :---: | :---: | :---: | :---: |")
for p in PENS:
    w(f"| {p:.1f} | {f1(avg('combined','coll',p=p))} | {f1(avg('v2i_only','coll',p=p))} | {f1(avg('v2v_only','coll',p=p))} |")
w()
w("**Collisions roughly double from baseline (p=0.0) to any connected condition, then plateau. "
  "The three arms are within noise at every penetration.**")
w()
w("### Who is crashing (Combined arm)")
w()
w("| $p$ | CAV collisions | HDV collisions | VRU (pedestrian) |")
w("| :---: | :---: | :---: | :---: |")
for p in PENS:
    w(f"| {p:.1f} | {f1(avg('combined','cav',p=p))} | {f1(avg('combined','hdv',p=p))} | {f1(avg('combined','vru',p=p))} |")
w()
w("As $p$ rises the human crashes vanish (fewer HDVs) and are **more than replaced** by CAV crashes.")
w()
w("---")
w()
w("## 3. Full per-cell results (every town x weather x penetration)")
w()
w("Columns: **coll**=total collisions; **cav/hdv/vru**=collisions by party; **frozen**=vehicles "
  "immobilised after a crash; **coop**=cooperative (V2V) brakes; **phantom**=phantom brakes "
  "suppressed; **dec/soft/hard**=Python brake actions; **v2v_recv**=V2V messages received; "
  "**cpm_emit**=CPMs emitted; **ratio**=wall/sim; **wall**=wall seconds; **status**.")
w()
for i, (akey, aname) in enumerate(ARMS, 1):
    w(f"### 3.{i} {aname}")
    w()
    w("| Town | Weather | $p$ | coll | cav | hdv | vru | frozen | coop | phantom | dec | soft | hard | v2v_recv | cpm_emit | ratio | wall(s) | status |")
    w("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for m in MAPS:
        for wx in WEA:
            for p in PENS:
                r = D[akey].get((p, wx, m))
                if r is None:
                    w(f"| {m} | {wx} | {p:.1f} | - | - | - | - | - | - | - | - | - | - | - | - | - | - | *missing* |")
                else:
                    w(f"| {m} | {wx} | {p:.1f} | **{r['coll']}** | {r['cav']} | {r['hdv']} | {r['vru']} | "
                      f"{r['frozen']} | {r['coop']} | {r['phantom']} | {r['dec']} | {r['sb']} | {r['hb']} | "
                      f"{r['v2vrecv']} | {r['cpm_emit']} | {r['ratio']} | {r['wall']} | {r['status']} |")
    w()
w("---")
w()
w("## 4. Collisions by map (averaged over weather)")
w()
w("| Map | Arm | p0.0 | p0.5 | p0.9 | p1.0 |")
w("| :--- | :--- | :---: | :---: | :---: | :---: |")
for m in MAPS:
    for akey, aname in ARMS:
        w(f"| {m} | {aname} | " + " | ".join(f1(avg(akey, "coll", p=p, m=m)) for p in PENS) + " |")
w()
w("## 5. Collisions by weather (averaged over maps)")
w()
w("| Weather | Arm | p0.0 | p0.5 | p0.9 | p1.0 |")
w("| :--- | :--- | :---: | :---: | :---: | :---: |")
for wx in WEA:
    for akey, aname in ARMS:
        w(f"| {wx} | {aname} | " + " | ".join(f1(avg(akey, "coll", p=p, w=wx)) for p in PENS) + " |")
w()
w("---")
w()
w("## 6. Cooperative-communication load (the stack IS live)")
w()
w("| $p$ | V2V recv (combined) | Coop brakes (combined) | Coop brakes (v2v-only) | Coop brakes (v2i-only) |")
w("| :---: | :---: | :---: | :---: | :---: |")
for p in PENS:
    w(f"| {p:.1f} | {f0(avg('combined','v2vrecv',p=p))} | {f0(avg('combined','coop',p=p))} | "
      f"{f0(avg('v2v_only','coop',p=p))} | {f0(avg('v2i_only','coop',p=p))} |")
w()
w("Half a million V2V messages per cell at high penetration, yet only ~65 cooperative-brake actions "
  "result - a vanishingly small share of the ~72,000 CAV decision cycles per cell. `v2i_only` "
  "correctly shows **zero** cooperative brakes (no V2V channel).")
w()
w("## 7. Performance (wall-to-sim ratio, Combined arm)")
w()
w("| Map | p0.0 | p0.5 | p0.9 | p1.0 |")
w("| :--- | :---: | :---: | :---: | :---: |")
for m in MAPS:
    w(f"| {m} | " + " | ".join(f2(avg("combined", "ratio", p=p, m=m)) for p in PENS) + " |")
w()
w("Ratio = wall seconds per sim second (lower = faster than real time). The broker rewrite keeps "
  "even Town10 at p=1.0 around 4.4x - tractable where earlier versions stalled.")
w()
w("---")
w()
w("## Findings & root cause")
w()
w("Three facts in the data, together, identify the failure mode:")
w()
w("1. **Inverted curve** - collisions rise from ~6 (all-human) to ~9-11 once CAVs are present, then "
  "plateau. Adding connected vehicles makes things *worse*.")
w("2. **Flat across arms** - Combined, V2I-only and V2V-only are within noise at every penetration. "
  "The cooperative *content* is not what determines outcomes.")
w("3. **CAVs are the victims** - at high $p$ the crashes are almost entirely CAV-on-something, and "
  "~15 of 60 vehicles end each Town cell **frozen** (immobilised after a collision).")
w()
w("### Root cause: the deadlock fix over-corrected")
w()
w("The green-light deadlock was caused by CAVs braking on the RSU's ghost detection of their own "
  "body. The fix drops **every** track within **3.0 m** of ego centre (`cav.py` ~L399, a blanket "
  "spatial `continue`). But it is a **position-only** gate: a genuine threat in that radius is "
  "discarded exactly like a self-ghost. Combined with a distance-fallback ladder whose 4.0 m "
  "hard-brake band sits below typical centre-to-centre spacing, the emergency-braking range is "
  "effectively blanked out. **CAVs under-brake and drive into hazards.** A correct fix must "
  "identify the ego-ghost by **velocity match** (co-located *and* co-moving), not proximity alone.")
w()
w("### Second, structural contributor")
w()
w("The flat-across-arms result points to a contributor independent of braking tuning: when two "
  "vehicles collide they are **immobilised in place**, becoming stationary obstacles that "
  "downstream traffic - including careful CAVs - then rear-ends, propagating incidents. This "
  "inflates counts in a way no message-passing can prevent, which is why the cooperative arms do "
  "not separate.")
w()
w("---")
w()
w("## Code changes that produced this run")
w()
w("- **Broker dispatch O(N^2)->O(N):** per-receiver message queues replace the flat scan; CPM/V2V "
  "payload decoding memoised (`lru_cache`). Removed the V2V congestion slowdown.")
w("- **V2V directional + lateral gating:** a received hard-brake warning only acts if the sender is "
  "ahead within the heading cone (yaw dot-product > 0) **and** within 2.0 m lateral offset - "
  "killing the opposing-lane phantom braking.")
w("- **Distance-based safety fallback:** a confirmed in-lane track triggers DECELERATE / SOFT_BRAKE "
  "/ HARD_BRAKE at 9.0 / 6.5 / 4.0 m even when TTC is undefined (stopped-wreck case).")
w("- **Restored TM avoidance for HDVs:** the blanket `disable_collision_detection_for()` call was "
  "removed so HDVs no longer pile up at spawn; conflicts now come from profile ignore-rates.")
w("- **HDV ignore-rate boost:** aggressive-hostile ignore-vehicles 10%->40%, distracted 10%->20%.")
w("- **Ego self-exclusion (the deadlock fix):** tracks within 3.0 m of ego centre dropped to stop "
  "CAVs braking on the RSU ghost reflection. **Prime suspect for the regression above.**")
w()
w("---")
w()
w("## Threats to validity")
w()
w("- **Single seed.** One spawn layout per cell; the +/-0 error bars are not real variance. Trends "
  "are directional only.")
w("- **Braking regression.** The CAV decision layer is mis-calibrated for this run, so absolute "
  "collision counts overstate real CAV risk and must not be quoted as a V2X-effectiveness result.")
w("- **Immobilise-as-obstacle.** The freeze-on-collision policy couples incidents; a metric-design "
  "choice needing review.")
w("- **Two missing v2i cells.** Town01 p0.0 ClearNoon and p0.9 HardRainNoon crashed at spawn; "
  "v2i_only averages use surviving cells.")
w()
w("## Recommended next steps")
w()
w("1. Replace the 3.0 m self-exclusion with a **velocity-matched** ego-ghost filter; add a "
  "regression test asserting a closing in-lane track within 3 m still produces HARD_BRAKE.")
w("2. Audit the collision/immobilise loop in `40_ablation_run.py` to quantify CAV crashes that are "
  "secondary rear-ends into frozen wrecks vs primary failures.")
w("3. Re-validate on a small grid (1 map x 4 pen x combined arm); confirm the curve falls before a "
  "full multi-seed sweep.")
w("4. Once corrected, re-run Configuration G (or the larger Compromise matrix) for the report-grade "
  "result; keep this G data archived as the pre-fix baseline.")
w()
w("---")
w()
w("*Data source: `out/ablation_G/{combined, v2i_only, v2v_only}`. All values computed directly from "
  "per-cell JSON metrics.*")

open(OUT, "w", encoding="utf-8").write("\n".join(O))
print("wrote", OUT, "-", len(O), "lines")
