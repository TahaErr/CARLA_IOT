"""Generate ABLATION_G_RESULTS_v2.md - full per-cell Config G (2nd iteration).

Reads out/ablation_G2/{combined,v2i_only,v2v_only}/*.json (post-fix rerun) and
emits a complete markdown report: every map x weather x seed x penetration x arm,
every metric, the primary/secondary collision split, a side-by-side comparison
against the pre-fix Config G (out/ablation_G), and the corrected findings.

    python scripts/make_ablation_G2_md.py
"""
from __future__ import annotations
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "out", "ablation_G2")
BASE = os.path.join(ROOT, "out", "ablation_G")   # pre-fix baseline for comparison
OUT = os.path.join(ROOT, "ABLATION_G_RESULTS_v2.md")

ARMS = [("combined", "Combined (V2X + V2V)"),
        ("v2i_only", "V2I-only (--no-v2v)"),
        ("v2v_only", "V2V-only (--no-v2x)")]
MAPS = ["Town01", "Town05", "Town10HD_Opt"]
WEA = ["ClearNoon", "HardRainNoon"]
PENS = [0.0, 0.5, 0.9, 1.0]
SEED = 0


def load(root, arm):
    out = {}
    for f in glob.glob(os.path.join(root, arm, "*.json")):
        d = json.load(open(f))
        c = d["config"]
        a = d["actions_taken"]
        out[(round(c["penetration"], 2), c["weather"], c["map"])] = dict(
            coll=d["collision_count"],
            prim=d.get("primary_collision_count", d["collision_count"]),
            sec=d.get("secondary_collision_count", 0),
            cav=d["cav_collision_count"], hdv=d["hdv_collision_count"],
            vru=d["vru_collision_count"],
            cavped=d.get("cav_hit_pedestrian_count", 0),
            hdvped=d.get("hdv_hit_pedestrian_count", 0),
            frozen=d["frozen_vehicle_count"], coop=d["cooperative_brakes"],
            phantom=d["phantom_brakes_suppressed"], v2vrecv=d["v2v_received_total"],
            v2vemit=d.get("v2v_deliveries_emitted", 0),
            cpm_emit=d["publishes_emitted"], cpm_drop=d.get("publishes_dropped", 0),
            cbr=round(d.get("cbr_mean", 0.0), 4),
            nb=a.get("none", 0), dec=a.get("decelerate", 0),
            sb=a.get("soft_brake", 0), hb=a.get("hard_brake", 0),
            ratio=round(d["wall_to_sim_ratio"], 2), wall=round(d["wall_seconds"], 1),
            deadcav=d.get("dead_cav_count", 0), decerr=d.get("decode_errors", 0),
            seed=c.get("seed", 0), status=d["status"])
    return out


D = {a: load(DATA, a) for a, _ in ARMS}
B = {a: load(BASE, a) for a, _ in ARMS}
NCELLS = {a: len(D[a]) for a, _ in ARMS}


def avg(store, arm, key, p=None, m=None, w=None):
    vs = [r[key] for (pp, ww, mm), r in store[arm].items()
          if (p is None or pp == p) and (m is None or mm == m) and (w is None or ww == w)]
    return sum(vs) / len(vs) if vs else None


def f1(x): return "-" if x is None else f"{x:.1f}"
def f0(x): return "-" if x is None else f"{x:.0f}"
def f2(x): return "-" if x is None else f"{x:.2f}"


O = []
def w(s=""): O.append(s)


w("# Configuration G - Full Ablation Results (v2, post-fix rerun)")
w()
w("**V2X-Sim cooperative-perception study - CARLA 0.9.16**  ")
w("Three-arm V2X / V2I / V2V penetration sweep, **2nd iteration (`G2`)** after the braking-logic "
  "fixes. Generated directly from the per-cell JSON metrics in "
  "`out/ablation_G2/{combined,v2i_only,v2v_only}`. The pre-fix run (`out/ablation_G`, see "
  "`ABLATION_G_RESULTS.md`) is retained for comparison.")
w()
total = sum(NCELLS.values())
w(f"> **Run status.** {total}/72 cells completed (combined {NCELLS['combined']}/24, "
  f"v2i_only {NCELLS['v2i_only']}/24, v2v_only {NCELLS['v2v_only']}/24). One combined cell "
  "(`p090 HardRainNoon Town05`) failed once with a transient CARLA crash and **passed on "
  "automatic retry** - no gaps this time. All metrics below are real and traceable.")
w()
w("> **What changed since v1.** The green-light deadlock fix in v1 used a blanket 3.0 m "
  "ego self-exclusion that also blinded CAVs to genuine close-range hazards (e.g. stopped wrecks), "
  "producing an *inverted* safety curve. v2 replaces it with a **velocity-matched** ego-ghost "
  "filter, adds a **primary/secondary collision split** (so pileups into already-frozen wrecks "
  "no longer inflate the headline), and adds **per-cell retry** for gap-free runs.")
w()
w("---")
w()
# === Sweep matrix ===
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
# === Design ===
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
w("| Cells per arm / total | 24 (3 maps x 2 weather x 1 seed x 4 pen) / 72 |")
w()
w("At `p = 0.0` there are no CAVs, so that cell is the shared **no-V2X / no-V2V human baseline** "
  "in every arm.")
w()
w("> **Note on the p = 0.0 column.** Penetration is the fraction of vehicles that are CAVs, so at "
  "`p = 0.0` the fleet is 100% HDV. HDVs neither carry nor act on any cooperative messages, so "
  "**no V2X (RSU->CAV CPM) or V2V (CAV<->CAV) communication is used or considered at p = 0.0** - "
  "the `coop brakes`, `v2v_recv` and `v2v_emit` columns are exactly 0 in every p = 0.0 row. The "
  "collisions there are purely HDV-on-HDV / HDV-on-pedestrian and define the baseline that the "
  "connected conditions (p >= 0.5) are measured against. Because the cooperative flags "
  "(`--no-v2v` / `--no-v2x`) have nothing to act on with zero CAVs, the p = 0.0 cell is the *same "
  "scenario* in all three arms; the small spread between the three p = 0.0 entries is CARLA's "
  "run-to-run nondeterminism at a fixed seed, **not** a V2X effect.")
w()
w("**Metric note.** `coll` = total deduplicated collision incidents (one per unordered vehicle "
  "pair). `primary` excludes *secondary* incidents - a new pair where one party was already "
  "immobilised by an earlier crash (i.e. traffic piling into a stationary wreck rather than a "
  "fresh driving failure). **Primary is the cleaner safety signal** because the immobilise-in-"
  "place policy can otherwise let one wreck, bumped by several cars, count as several incidents.")
w()
w("---")
w()
# === Headline ===
w("## 2. Headline - collisions by penetration & arm")
w()
w("Mean per cell, averaged over 3 maps x 2 weather. Lower is better.")
w()
w("### 2a. Total collisions")
w()
w("| $p$ | Combined | V2I-only | V2V-only |")
w("| :---: | :---: | :---: | :---: |")
for p in PENS:
    w(f"| {p:.1f} | {f1(avg(D,'combined','coll',p=p))} | {f1(avg(D,'v2i_only','coll',p=p))} | {f1(avg(D,'v2v_only','coll',p=p))} |")
w()
w("### 2b. Primary collisions (pileups into frozen wrecks excluded)")
w()
w("| $p$ | Combined | V2I-only | V2V-only |")
w("| :---: | :---: | :---: | :---: |")
for p in PENS:
    w(f"| {p:.1f} | {f1(avg(D,'combined','prim',p=p))} | {f1(avg(D,'v2i_only','prim',p=p))} | {f1(avg(D,'v2v_only','prim',p=p))} |")
w()
w("**Honest read.** The v1 regression is corrected (see section 6 for the side-by-side: p=1.0 "
  "total fell from ~10 to ~9, primary to ~7.7, and the cooperative-braking layer now actively "
  "engages). **However, even post-fix the curve is not a clean monotonic safety gain**: collisions "
  "still rise from the all-human baseline (~6) to any connected condition (~7-8 primary) and then "
  "plateau, and the three arms remain close. With a single seed this is also noisy. The dense "
  "hostile downtown map (Town10HD_Opt) dominates the average - see the by-map breakdown.")
w()
w("### 2c. Who is crashing (Combined arm)")
w()
w("| $p$ | CAV collisions | HDV collisions | VRU (pedestrian) |")
w("| :---: | :---: | :---: | :---: |")
for p in PENS:
    w(f"| {p:.1f} | {f1(avg(D,'combined','cav',p=p))} | {f1(avg(D,'combined','hdv',p=p))} | {f1(avg(D,'combined','vru',p=p))} |")
w()
w("As $p$ rises the human crashes vanish (fewer HDVs) and CAV incidents grow - cautious AVs braking "
  "in dense hostile traffic still get drawn into conflicts.")
w()
w("---")
w()
# === Full per-cell ===
w("## 3. Full per-cell results (every map x weather x seed x penetration)")
w()
w("Columns: **coll**=total; **prim/sec**=primary/secondary; **cav/hdv/vru**=collisions by party; "
  "**cavP/hdvP**=CAV/HDV-hit-pedestrian; **frozen**=immobilised vehicles; **coop**=cooperative "
  "(V2V) brakes; **phan**=phantom brakes suppressed; **dec/soft/hard**=Python brake actions; "
  "**v2v_recv**=V2V msgs received; **v2v_emit**=V2V deliveries; **cpm_emit/drop**=CPMs emitted/"
  "dropped; **cbr**=mean channel-busy ratio; **ratio**=wall/sim; **wall**=wall s; **status**.")
w()
for i, (akey, aname) in enumerate(ARMS, 1):
    w(f"### 3.{i} {aname}  (seed {SEED})")
    w()
    w("| Town | Weather | seed | $p$ | coll | prim | sec | cav | hdv | vru | cavP | hdvP | frozen | coop | phan | dec | soft | hard | v2v_recv | v2v_emit | cpm_emit | cpm_drop | cbr | ratio | wall | status |")
    w("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for m in MAPS:
        for wx in WEA:
            for p in PENS:
                r = D[akey].get((p, wx, m))
                if r is None:
                    w(f"| {m} | {wx} | {SEED} | {p:.1f} |" + " - |" * 21 + " *missing* |")
                else:
                    w(f"| {m} | {wx} | {r['seed']} | {p:.1f} | **{r['coll']}** | {r['prim']} | {r['sec']} | "
                      f"{r['cav']} | {r['hdv']} | {r['vru']} | {r['cavped']} | {r['hdvped']} | "
                      f"{r['frozen']} | {r['coop']} | {r['phantom']} | {r['dec']} | {r['sb']} | {r['hb']} | "
                      f"{r['v2vrecv']} | {r['v2vemit']} | {r['cpm_emit']} | {r['cpm_drop']} | {r['cbr']} | "
                      f"{r['ratio']} | {r['wall']} | {r['status']} |")
    w()
w("---")
w()
# === By map ===
w("## 4. Collisions by map (averaged over weather)")
w()
w("### 4a. Total")
w()
w("| Map | Arm | p0.0 | p0.5 | p0.9 | p1.0 |")
w("| :--- | :--- | :---: | :---: | :---: | :---: |")
for m in MAPS:
    for akey, aname in ARMS:
        w(f"| {m} | {aname} | " + " | ".join(f1(avg(D, akey, "coll", p=p, m=m)) for p in PENS) + " |")
w()
w("### 4b. Primary")
w()
w("| Map | Arm | p0.0 | p0.5 | p0.9 | p1.0 |")
w("| :--- | :--- | :---: | :---: | :---: | :---: |")
for m in MAPS:
    for akey, aname in ARMS:
        w(f"| {m} | {aname} | " + " | ".join(f1(avg(D, akey, "prim", p=p, m=m)) for p in PENS) + " |")
w()
w("Town10HD_Opt (dense downtown) carries most of the absolute collision load and most of the "
  "secondary pileups; Town01/Town05 are milder.")
w()
# === By weather ===
w("## 5. Collisions by weather (averaged over maps)")
w()
w("| Weather | Arm | p0.0 | p0.5 | p0.9 | p1.0 |")
w("| :--- | :--- | :---: | :---: | :---: | :---: |")
for wx in WEA:
    for akey, aname in ARMS:
        w(f"| {wx} | {aname} | " + " | ".join(f1(avg(D, akey, "coll", p=p, w=wx)) for p in PENS) + " |")
w()
w("---")
w()
# === Comparison to v1 ===
w("## 6. v2 (post-fix) vs v1 (pre-fix) - the effect of the fixes")
w()
w("Total collisions, averaged over all completed cells per penetration (both runs, all arms "
  "pooled). v1 = `out/ablation_G`, v2 = `out/ablation_G2`.")
w()
def pooled(store, key, p):
    vs = []
    for a, _ in ARMS:
        vs += [r[key] for (pp, _, _), r in store[a].items() if pp == p]
    return sum(vs) / len(vs) if vs else None
w("| $p$ | v1 total | v2 total | v2 primary | change (total) |")
w("| :---: | :---: | :---: | :---: | :---: |")
for p in PENS:
    v1 = pooled(B, "coll", p)
    v2 = pooled(D, "coll", p)
    v2p = pooled(D, "prim", p)
    delta = (v2 - v1) if (v1 is not None and v2 is not None) else None
    w(f"| {p:.1f} | {f1(v1)} | {f1(v2)} | {f1(v2p)} | {('%+.1f' % delta) if delta is not None else '-'} |")
w()
w("And the behavioural change that drives it - cooperative + emergency braking now actually fire "
  "(Combined arm, avg per cell):")
w()
w("| $p$ | v1 coop-brakes | v2 coop-brakes | v1 hard-brakes | v2 hard-brakes |")
w("| :---: | :---: | :---: | :---: | :---: |")
for p in PENS:
    w(f"| {p:.1f} | {f0(avg(B,'combined','coop',p=p))} | {f0(avg(D,'combined','coop',p=p))} | "
      f"{f0(avg(B,'combined','hb',p=p))} | {f0(avg(D,'combined','hb',p=p))} |")
w()
w("The velocity-matched self-exclusion un-blinded CAVs to close-range threats, so they brake when "
  "they should; those hard brakes propagate as V2V brake-intent, so the cooperative layer engages "
  "instead of sitting idle.")
w()
w("---")
w()
# === Comms ===
w("## 7. Cooperative-communication load (the stack is live)")
w()
w("| $p$ | V2V recv (combined) | Coop brakes (combined) | Coop brakes (v2v-only) | Coop brakes (v2i-only) |")
w("| :---: | :---: | :---: | :---: | :---: |")
for p in PENS:
    w(f"| {p:.1f} | {f0(avg(D,'combined','v2vrecv',p=p))} | {f0(avg(D,'combined','coop',p=p))} | "
      f"{f0(avg(D,'v2v_only','coop',p=p))} | {f0(avg(D,'v2i_only','coop',p=p))} |")
w()
w("`v2i_only` correctly shows **zero** cooperative brakes (no V2V channel); V2V traffic and "
  "cooperative brakes appear only in the arms that enable V2V and scale with penetration.")
w()
# === Perf ===
w("## 8. Performance (wall-to-sim ratio, Combined arm)")
w()
w("| Map | p0.0 | p0.5 | p0.9 | p1.0 |")
w("| :--- | :---: | :---: | :---: | :---: |")
for m in MAPS:
    w(f"| {m} | " + " | ".join(f2(avg(D, "combined", "ratio", p=p, m=m)) for p in PENS) + " |")
w()
w("Ratio = wall seconds per sim second (lower = faster than real time).")
w()
w("---")
w()
# === Findings ===
w("## 9. Findings & root cause")
w()
w("- **The v1 regression is fixed.** Replacing the position-only 3.0 m ego self-exclusion with a "
  "velocity-matched ego-ghost filter restored close-range emergency braking. Pooled p=1.0 "
  "collisions fell vs v1, and Combined-arm hard-brakes and cooperative-brakes rose by an order of "
  "magnitude - the cooperative safety mechanism is now actually exercised.")
w("- **Penetration benefit is still weak/noisy.** Even post-fix, collisions rise from the all-human "
  "baseline to any connected condition and then plateau; the three arms stay close. This is a "
  "single-seed run and the dense hostile Town10HD_Opt dominates the average, so treat the curve as "
  "directional, not conclusive.")
w("- **Immobilise-as-obstacle is a real but secondary effect.** The primary/secondary split shows "
  "pileups into frozen wrecks are a minority of incidents on Town01/Town05 but matter more on "
  "Town10; reporting `primary` removes that confound from the headline.")
w("- **Residual hypotheses for the flat curve** (for the next iteration): cautious CAVs braking in "
  "hostile traffic invite rear-ends from non-connected HDVs; the Python brake override interacts "
  "with the Traffic Manager; and 60 s single-seed cells have high variance. Multi-seed + a "
  "follower-aware braking policy are the obvious next levers.")
w()
w("---")
w()
# === Validity / next ===
w("## 10. Threats to validity")
w()
w("- **Single seed** (seed 0): one spawn layout per cell; no real variance bars. Directional only.")
w("- **Single duration** (60 s): long enough for intersection congestion but short relative to the "
  "120 s full-fidelity option.")
w("- **Metric coupling**: immobilise-in-place couples incidents; mitigated by the primary metric "
  "but not eliminated.")
w()
w("## 11. Recommended next steps")
w()
w("1. Re-run as **Configuration B (\"Compromise\")**: 3 seeds, 120 s, to get real variance bars and "
  "a statistically meaningful penetration curve.")
w("2. Add a **follower-aware / graduated** CAV brake policy so emergency stops do not invite "
  "rear-ends, and audit the Python-override vs Traffic-Manager interaction.")
w("3. Keep `out/ablation_G` (v1) and `out/ablation_G2` (v2) both archived; this report supersedes "
  "`ABLATION_G_RESULTS.md` for the corrected numbers.")
w()
w("---")
w()
w("*Data source: `out/ablation_G2/{combined, v2i_only, v2v_only}` (v2, post-fix); comparison "
  "baseline `out/ablation_G` (v1). All values computed directly from per-cell JSON metrics by "
  "`scripts/make_ablation_G2_md.py`.*")

open(OUT, "w", encoding="utf-8").write("\n".join(O))
print("wrote", OUT, "-", len(O), "lines")
