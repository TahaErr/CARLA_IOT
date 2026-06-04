# Notes for the Report Writer — Cross-Check & Guidance

Companion to the Sprint 5 final ablation. Use this to (a) **cross-check every number**
you put in the report against the authoritative values below, and (b) keep the
**caveats** that make the result credible. Source of truth for all numbers:
`SPRINT5_DELIVERABLE/05_combined_eda/all_cells_144.csv` and the rollup CSVs — pull
from those, do not eyeball or re-type.

---

## A. Authoritative numbers (cross-check your tables against these)

**Total collisions — mean ± sd over 12 cells (2 seeds × 3 maps × 2 weather):**

| `p` | Combined | V2I-only | V2V-only |
| :---: | :---: | :---: | :---: |
| 0.0 | 21.9 ± 5.0 | 21.8 ± 4.9 | 21.8 ± 4.9 |
| 0.5 | 14.7 ± 4.1 | 14.5 ± 5.5 | 15.2 ± 4.7 |
| 0.9 | 7.2 ± 2.9 | 7.9 ± 3.9 | 8.3 ± 3.5 |
| 1.0 | 5.9 ± 3.5 | 6.1 ± 3.7 | 6.7 ± 2.9 |

**Primary collisions (frozen-wreck pileups excluded):**

| `p` | Combined | V2I-only | V2V-only |
| :---: | :---: | :---: | :---: |
| 0.0 | 16.1 ± 3.4 | 16.0 ± 3.4 | 16.0 ± 3.4 |
| 0.5 | 11.1 ± 2.8 | 10.3 ± 3.2 | 11.2 ± 2.4 |
| 0.9 | 6.3 ± 2.8 | 6.8 ± 3.2 | 7.5 ± 3.2 |
| 1.0 | 5.0 ± 2.9 | 5.0 ± 3.0 | 5.7 ± 2.9 |

**Headline reduction (Combined, total):** 21.9 → 5.9 = **~73%**, monotonic.

**By map (Combined, total, mean):** Town01 24.0 → 6.0 · Town05 15.5 → 1.8 · Town10HD_Opt 26.2 → 10.0
**By weather (Combined, total):** ClearNoon 21.8 → 6.0 · HardRainNoon 22.0 → 5.8
**Per-profile at-fault (Combined, pooled sum):** attentive 99 · distracted 127 · aggressive_hostile 187 · ai_realistic 184
**Cooperative brakes (Combined, mean):** p0 = 0 · p0.5 = 180 · p0.9 = 540 · p1.0 = 707
**Frozen vehicles (Combined):** p0 ≈ 36 → p1.0 ≈ 10 · **wall/sim:** 0.64 → 2.63

> If any number in the draft disagrees with the above, the draft is wrong — recompute from the CSV.

---

## B. Claims you CAN make
- Collisions fall **monotonically** with CAV penetration, ~73% from human baseline to full fleet, **on every arm and every map**.
- A **consistent ordering** Combined ≤ V2I-only ≤ V2V-only holds at each penetration.
- Town05 (clean multi-lane geometry) **nearly eliminates** collisions at full penetration; Town10 (dense downtown) plateaus.
- The result is **weather-robust** (ClearNoon ≈ HardRainNoon).
- Cooperative braking and V2V traffic **scale with penetration**; frozen wrecks fall sharply.

## C. Claims you must NOT make (without more data)
- ❌ "V2I is significantly better than V2V." The arm gaps are **small relative to the sd**; 2 seeds cannot establish significance. Say "consistent but not statistically established."
- ❌ Any real-world crash-rate forecast. The scenario is a **calibrated stress test** (~22 collisions/90 s/60 vehicles is far above real-world rates) designed to make conflicts measurable.
- ❌ "V2X eliminates collisions." It reduces them; Town10 floors at ~10, partly due to simulator artifacts (see D).
- ❌ Anything implying V2X did something at **p = 0.0** (there are zero CAVs there).

---

## D. Caveats that MUST appear (credibility-makers)
1. **p = 0.0 is the shared human baseline.** No V2X/V2V exists with 0 CAVs; the three arms at p=0 are the *same scenario*, and their small spread is CARLA run-to-run nondeterminism — not a V2X effect.
2. **Town10 junction artifact.** A real fraction of Town10's high-`p` collisions are CARLA Traffic-Manager wide-turn / lane-crossing geometry (cars arcing into the oncoming lane on tight corners), **not** cooperative-perception failures. This is why Town05 (cleaner geometry) reaches ~2 while Town10 floors at ~10. Be explicit.
3. **At-fault attribution** credits the collision sensor that fires first, so **attentive HDVs still appear in per-profile counts as victims** of reckless drivers, not as at-fault. State this next to the per-profile table.
4. **Immobilise-in-place couples some incidents** — hence the **primary vs secondary** split. Use *primary* as the headline safety metric and explain it.
5. **The CAV model is idealized** (clean localization, near-ground-truth local-sensor cone), so the measured benefit is an optimistic upper bound, not a deployment estimate.
6. **2 seeds** — variance is reported (sd) but the sample is small; trends are robust, fine-grained arm differences are suggestive.

---

## E. Statistical rigor (one real trap)
If you run significance tests (e.g. Welch t-test + Cohen's d on arms or penetration steps):
- The **12 cells per (p, arm) are NOT iid** — the 3 maps differ systematically (map is a confounder / blocking factor) and 2 of the 12 are merely the second seed. Treating them as "n = 12" overstates power.
- **Do instead:** treat **map (and weather) as blocking factors** — compare arms within matched map×weather×seed cells (paired/blocked), or report per-map and avoid a single pooled p-value. Penetration-step reductions are large and survive any reasonable test; arm-vs-arm differences likely won't, and that's fine to report honestly.
- With 2 seeds, prefer **descriptive stats + effect sizes** over p-values; don't manufacture significance.

---

## F. Methods honesty = a strength, not a weakness
Document the iteration openly — it reads as rigor:
- The **first full ablation (Config G) produced an *inverted* safety curve** (collisions rose with penetration). We diagnosed and fixed the causes:
  - over-aggressive **ego self-exclusion** blinding CAVs to close wrecks → velocity-matched filter;
  - **distance-fallback ignoring closing speed** → closing-rate gate;
  - **3 m follow distance** → 7 m;
  - **brake overrides zeroing the steering wheel mid-turn** → steer-preserving overrides (the single highest-impact fix: cut p=1.0 collisions **12 → 3** in Town01 validation).
- A short "what went wrong → fix → validation" subsection turns the messy path into evidence of a controlled methodology. Include the steer-fix before/after as a mini-result.

---

## G. Report writing & figures checklist
*(for the written final report — tables, figures, prose; not a slide deck)*
- [ ] Every quoted number traced to `all_cells_144.csv` / rollups (Section A as the gate).
- [ ] Define each metric once: penetration, *collision incident* (deduplicated unordered pair), primary/secondary, cooperative brake, phantom-brake-suppressed.
- [ ] **Money figure** = collisions vs penetration with **sd error bars**; add a **per-map small-multiple** (Town05/01/10 diverge — that's a finding).
- [ ] Per-profile table accompanied by the victim/at-fault caveat (D3).
- [ ] Reproducibility footer: config, seeds 0+1, the `updated-ablation` commit, the deliverable package.
- [ ] Center the algorithmic contribution (time-aware late fusion + confirmation hysteresis / phantom-brake suppression + V2V hard-brake intent), with the penetration curve as supporting evidence.

---

## H. Optional high-value addition (if time allows)
Implement the **head-on / off-lane collision tagging** (classify each collision by the relative heading of the two parties, and flag vehicles off the drivable lane). This converts caveat **D2** from a hand-wave into a number — "X% of Town10's p=1.0 collisions are turn-geometry artifacts" — and meaningfully strengthens the Town10 discussion. Read-only instrumentation; no behavior change.

---

*Authoritative data: `SPRINT5_DELIVERABLE/` (or `out/ablation_sprint5_final/`). When in doubt, recompute from the 144 raw cell JSONs.*
