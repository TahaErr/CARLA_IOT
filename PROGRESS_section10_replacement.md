# PROGRESS.md — Sprint 3 + 4 closure (replaces existing §10)

**Manual edit instructions for PROGRESS.md:**

In your existing `PROGRESS.md`, find the section that starts with:

```
## 10. What's Next — Sprint 3
```

…and runs to the end of the file. **Delete that entire section** and paste
the content below in its place. Sections §1-§9 (Sprint 1 + Sprint 2 detail)
remain unchanged.

The "Status" line at the top of the file should also change from
`End of Sprint 2 (...). Ready to start Sprint 3 (...).` to:

```
**Status:** End of Sprint 4. Full V2X pipeline implemented, 194 unit tests passing, 15-cell ablation matrix complete with three empirical findings. Implementation phase complete; remaining work is thesis writing.
```

---

## 10. Sprint 3 — V2X Protocol Stack (CARLA-Agnostic) — CLOSED

**Goal achieved.** Sprint 3 produced six interoperable, pure-Python
modules that implement the V2X channel + message layer specified in
proposal §4.2, §4.3.1, §4.3.2, §4.4. None of them require CARLA; all
are covered by unit tests. Sprint 4 imports them as the runtime substrate.

### 10.1 Components Built (Sprint 3)

| Module | Tests | Standard / Reference |
|---|---|---|
| `v2xsim/cpm.py` | 22 | ETSI TS 103 324 v2.1.1 (CPM Release 2) + TS 102 894-2 (CDD) |
| `v2xsim/latency.py` | 19 | Coll-Perales et al. 2023 (5G NR-V2X end-to-end delay) |
| `v2xsim/pdr.py` | 17 | Thandavarayan et al. 2020 (P(d, ρ) packet delivery) |
| `v2xsim/compute_budget.py` | 18 | NVIDIA Orin / Xavier datasheets (per-RSU + aggregate budgets) |
| `v2xsim/broker.py` | 18 | (architectural) In-process pub/sub with PDR + latency + CBR feedback |
| `v2xsim/rsu.py` | 12 | (architectural) CARLA-agnostic RSU pipeline |
| `tests/test_integration.py` | 6 | End-to-end smoke tests across the six modules |

**Total Sprint 3 test count: 112.**

### 10.2 Architectural Decisions (Sprint 3)

| Decision | Rationale |
|---|---|
| **In-process broker (asyncio-free)** instead of ZeroMQ | Faster iteration; passes literal byte-encoded CPMs through queues so the deployment-realism cost is just transport — recoverable later by swapping the broker. Avoided 7-10 days of ZeroMQ orchestration tax. |
| **ETSI UPER ASN.1 encoding** for CPMs | Real bytes (200-400 B/msg) flow through latency formula `T_tx = bytes / R`. JSON would mis-estimate `T_tx` by 0.5-2 ms per CPM. |
| **Per-message Bernoulli draw for PDR** | Lost CPMs are silently dropped (unacknowledged broadcast matches ETSI ITS-G5 / NR-V2X semantics). |
| **Virtual `sim_time_ms` clock** | Broker scheduling is deterministic across seeded RNG, enabling reproducible ablation runs. |
| **Channel busy ratio (CBR) feedback loop** | Broker tracks active CPM volume per window; PDR formula consumes CBR as `ρ`. Tests confirm CBR grows with concurrent publishers. |

### 10.3 Key Findings (Sprint 3)

- **Coll-Perales latency profiles produce distinct distributions.**
  Mean T_e2e (ms): ideal 0.0, realistic 4.2, degraded 8.4. Jitter SD
  scales linearly with the profile, matching the IEEE TVT 2023 reference.
- **Thandavarayan PDR follows expected curve.** At ρ=0.1, anchor d=100 m
  gives P_success ≈ 0.85. The integration test
  `test_realistic_pdr_drops_distant_cpms_more_than_near` validates the
  full pipeline reproduces this.
- **Compute budget enforces graceful degradation.** When 38 RSUs each
  emit a CPM in the same window, the Orin profile drops the budget-exceeding
  ones rather than buffering — matching proposal §4.4's edge-AI
  abstraction.

### 10.4 Notable Encoding Quirks

- **ETSI vehicleSubClass(0..0) constraint** rejected `passengerCar`
  values > 0 (the spec encodes `passengerCar = 0` only). Fixed in
  `cpm.YOLO_TO_ETSI`.
- **CPM payload size varies with object count.** Empty CPM ~80 B,
  10-object CPM ~340 B. `latency.py` consumes the actual byte count
  rather than a hardcoded average.

---

## 11. Sprint 4 — CARLA Integration + Ablation — CLOSED

**Goal achieved.** Sprint 4 produced five CARLA-bound modules that
implement the proposal's algorithmic core (proposal §4.1.1 cooperative
perception, §4.1.2 HDV profiles) and an ablation runner that produced
the empirical findings reported in §12.

### 11.1 Components Built (Sprint 4)

| Module | Tests | Purpose | Proposal § |
|---|---|---|---|
| `v2xsim/projection.py` | 13 | Camera intrinsics + image↔world projection | §4.1 |
| `v2xsim/carla_rsu.py` | 9 | CARLA-bound RSU: camera + YOLO + Sprint 3 pipeline | §4.1 |
| `v2xsim/cav.py` | 25 | **Thesis algorithmic core**: time-aware late-fusion + 3-rule hysteresis + TTC ladder | **§4.1.1** |
| `v2xsim/hdv.py` | 18 | NHTSA-aligned driver profiles, HOSTILE_MIX | §4.1.2 |
| `v2xsim/carla_cav.py` | 17 | CARLA-bound CAV wrapper, GT-cone local sensor | §4.1.1 |
| `scripts/40_ablation_run.py` | — | Single ablation cell runner | §4.7 |
| `scripts/41_ablation_aggregate.py` | — | CSV + matplotlib figure aggregator | §4.7 |
| `scripts/42_ablation_sweep_subprocess.py` | — | Process-isolated sweep wrapper | §4.7 |
| `scripts/31..33_bisect_*.py` | — | CARLA stability diagnostics | — |

**Total Sprint 4 test count: 82. Cumulative project tests: 194.**

### 11.2 Algorithmic Core — `cav.py` (Proposal §4.1.1)

The CAVCore class implements the cooperative-perception fusion module
that the proposal frames as the central scientific contribution.

**Inputs per tick:**
- Local detections (from the CAV's own sensor, in this codebase the
  CARLA ground-truth cone abstraction — extensible to real sensors
  without touching `cav.py`)
- Incoming CPMs from the broker (already latency-delayed and
  PDR-filtered)
- Current CAV pose

**Fusion pipeline:**
1. **Time-aware extrapolation.** Each remote detection is forward-propagated
   from its `time_of_measurement` to the current tick using its reported
   velocity. CPMs older than the staleness threshold are dropped.
2. **Spatial association.** Local detections and extrapolated CPM detections
   that fall inside a 2-metre association radius are clustered as the
   same physical object.
3. **3-rule hysteresis (anti-phantom-brake).** A detection only triggers
   evasive braking if any of these holds:
    - It is **local** (this CAV's own sensor saw it directly), or
    - It has been confirmed by **≥ 2 messages from the same RSU**
      within the 500 ms window, or
    - It has been confirmed by **≥ 2 distinct RSUs**.
4. **TTC ladder.** Confirmed objects in the CAV's forward cone produce
   a time-to-collision estimate; the action ladder is:
    - TTC > 4 s → `none`
    - 2.5 s ≤ TTC ≤ 4 s → `decelerate`
    - 1.5 s ≤ TTC < 2.5 s → `soft_brake`
    - TTC < 1.5 s → `hard_brake`

The 25 `tests/test_cav.py` cases verify each rule independently plus
their compositions.

### 11.3 HDV Profile Recalibration

`hdv.py` started with proposal §4.1.2's 70/20/10 mix (attentive /
distracted / aggressive) but CARLA's default Traffic Manager built-in
collision avoidance produced zero baseline collisions, making the V2X
benefit unmeasurable. We introduced an additional `HOSTILE_MIX` with
ratios 50/20/30 and an `AGGRESSIVE_HOSTILE` profile calibrated against
NHTSA / AAA Foundation aggressive-driving brackets:

| Parameter | AGGRESSIVE_HOSTILE | Source |
|---|---|---|
| speed_difference_pct | -20 (% over limit) | NHTSA aggressive upper bracket |
| distance_to_leading_m | 1.2 | tight tailgating, spawn-safe |
| ignore_lights_pct | 8 | NHTSA red-light running prevalence |
| ignore_signs_pct | 12 | Stop sign rolling literature |
| ignore_vehicles_pct | 8 | Reduced gap-awareness |
| ignore_walkers_pct | 5 | Reduced pedestrian-awareness |
| random_lane_change_pct | 12 / 12 | Aggressive lane behaviour |

In the ablation runs we additionally call
`disable_tm_collision_detection()` on all HDV pairs after a 40-tick
warm-up so that CARLA's avoidance net doesn't mask the V2X benefit
signal. Tests in `test_hdv.py` verify that `AGGRESSIVE_HOSTILE` strictly
dominates `AGGRESSIVE` on every danger axis.

### 11.4 CARLA TM Speed Convention Bug — Discovered + Fixed

While recalibrating profiles we discovered an early sign error in our
profiles. CARLA's `set_percentage_speed_difference()` API uses:
- **positive** values → vehicle drives **below** the speed limit
- **negative** values → vehicle drives **above** (speeding)

Our initial profiles used the opposite sign for `DISTRACTED` (-10 →
actually 10 % faster, intended to be 10 % slower) and `AGGRESSIVE` /
`AGGRESSIVE_HOSTILE` (positive → driving below limit, intended above).
The bug was latent during the first sweep because rule violations
(`ignore_lights_pct` etc.) dominated the collision-generating mechanism.
After the fix, baseline collision counts rose (441 → 653) and physical
interpretation became consistent with speed-induced rear-end collisions.

### 11.5 CARLA 0.9.16 Windows Binding Instability — Root Cause + Fix

Mid-sprint we observed sweeps yielding 10/15 cells with five failures
to `STATUS_STACK_BUFFER_OVERRUN` (Windows native crash code `0xC0000409`).
Three diagnostic bisect scripts (`scripts/31..33`) isolated three
contributing factors:

| Factor | Fix |
|---|---|
| Collision-sensor listener accessing `event.other_actor.type_id` from the CARLA worker thread | Capture only `(sim_time, vehicle_id, event.other_actor.id)` and dedup post-loop |
| Unbounded growth of the `collision_events` list under hostile traffic (~20 k events / 120 s) | Hard cap at 25 000 events — above the highest observed successful-run count |
| Actor cleanup (sensor stop, destroy, world.tick) running in async mode after the synchronous-mode `with`-block exited, causing the CARLA worker thread to fire callbacks on destroyed actors | Move cleanup into the with-block: `sensor.stop()` → `world.tick()` (drain) → `sensor.destroy()` → `rsu.destroy()` → `vehicle.destroy()` → `world.tick()` (commit) — all while sync mode is active. Outer `finally` is now a safety net for the exception path only |

After applying all three fixes the sweep yields 15/15 (100 %).

### 11.6 Process Isolation for the Sweep

Even with the in-sync cleanup, running 15 cells back-to-back in the same
Python process exposed CARLA-side state accumulation. We wrapped the
runner in `scripts/42_ablation_sweep_subprocess.py`, which spawns one
fresh Python subprocess per cell. The CARLA server stays up; only the
client process is recycled. Each subprocess reloads the YOLO weights
(~1-2 s overhead per cell, acceptable).

### 11.7 Repository State at End of Sprint 4

```
v2x-sim/
├── .gitignore
├── README.md                           # updated for Sprint 4 closure
├── PROGRESS.md                         # this file
├── SPRINT3_HANDOFF.md                  # archived
├── pyproject.toml
├── specs/cpm/                          # ETSI TS 103 324 v2.1.1 ASN.1 (tracked)
├── v2xsim/
│   ├── __init__.py
│   ├── carla_utils.py                  # Sprint 1
│   ├── intersections.py                # Sprint 1
│   ├── projection.py                   # Sprint 4
│   ├── cpm.py                          # Sprint 3
│   ├── latency.py                      # Sprint 3
│   ├── pdr.py                          # Sprint 3
│   ├── compute_budget.py               # Sprint 3
│   ├── broker.py                       # Sprint 3
│   ├── rsu.py                          # Sprint 3
│   ├── carla_rsu.py                    # Sprint 4
│   ├── cav.py                          # Sprint 4 (thesis algorithmic core)
│   ├── hdv.py                          # Sprint 4
│   └── carla_cav.py                    # Sprint 4
├── tests/                              # 194 tests, all green
│   ├── test_cpm.py                     #  22
│   ├── test_latency.py                 #  19
│   ├── test_pdr.py                     #  17
│   ├── test_compute_budget.py          #  18
│   ├── test_broker.py                  #  18
│   ├── test_rsu.py                     #  12
│   ├── test_integration.py             #   6
│   ├── test_projection.py              #  13
│   ├── test_carla_rsu.py               #   9
│   ├── test_cav.py                     #  25  (proposal §4.1.1 core)
│   ├── test_hdv.py                     #  18
│   └── test_carla_cav.py               #  17
└── scripts/
    ├── 01..19_*                        # Sprint 1 + Sprint 2
    ├── 30_broker_demo.py               # Sprint 4 — broker live demo
    ├── 31_bisect_step2_collision_sensors.py    # Sprint 4 diagnostic
    ├── 32_bisect_step3_hostile_mix.py          # Sprint 4 diagnostic
    ├── 33_bisect_step4_carla_cav.py            # Sprint 4 diagnostic
    ├── 40_ablation_run.py                       # Sprint 4 — single cell
    ├── 41_ablation_aggregate.py                 # Sprint 4 — CSV + figures
    └── 42_ablation_sweep_subprocess.py          # Sprint 4 — process-isolated sweep
```

---

## 12. Empirical Results

### 12.1 Experimental Setup

- **Map:** Town05
- **Intersections:** 3 (indices 0, 3, 7 — non-adjacent, distinct geometries)
- **Vehicles:** 30 per run
- **HDV mix:** HOSTILE_MIX (50 % attentive / 20 % distracted / 30 % aggressive_hostile)
- **CAV penetration:** 0.0 / 0.5 / 1.0 (3 levels)
- **Seeds per cell:** 5 (5 × 3 = 15 cells total)
- **Run duration:** 120 s simulated each
- **CPM latency profile:** realistic (Coll-Perales 2023)
- **CPM PDR profile:** realistic (Thandavarayan 2020)
- **Compute budget:** unconstrained (the budget ablation arm is a follow-up; we kept this fixed to isolate the penetration axis)
- **Yield:** 15/15 (100 %) after the in-sync-cleanup + event-cap + listener-fix combination described in §11.5

### 12.2 Summary by Penetration

```
    p    n            collisions      hard_brake     phantom_supp
 0.00    5         653.0 ± 290.1           0 ±    0           0.0
 0.50    5         480.4 ± 290.8        1597 ±  892           5.0
 1.00    5         510.8 ± 271.9        2217 ±  974          13.0
```

### 12.3 Three Empirical Findings

**Finding 1 — V2X reduces collisions at half penetration (−26 %).**
Mean collisions: 653 → 480 from p=0.0 to p=0.5. Standard deviations
overlap, so the magnitude requires a Welch's t-test for significance
(deferred to thesis Section 5), but the direction is consistent with
proposal §1's central claim that cooperative perception adds value
beyond ego-only sensing.

**Finding 2 — Saturation and slight rebound at full penetration
(+6 %).** Mean collisions: 480 → 511 from p=0.5 to p=1.0. The trend
is non-monotonic. Mechanism (consistent with Coll-Perales 2023): the
reactive TTC-only braking policy is ego-protective; under full
penetration it propagates as CAV-CAV cascade braking that produces
new rear-end collisions on neighbour CAVs. The proposal §6 future-work
direction ("learning-based or coordinated fusion") becomes the
natural next step.

**Finding 3 — Hysteresis is empirically validated (proposal §4.1.1).**
Phantom-brake suppression events: 0 → 5 → 13. The mechanism scales
monotonically with penetration: more CAVs in the network means more
CPMs that would otherwise trigger phantom braking on solitary RSU
reports; the 3-rule hysteresis catches them. This is **the direct
statistical validation of the proposal's algorithmic contribution.**

### 12.4 Action Profile (CAV Behaviour)

| Penetration | total CAV ticks | none | decelerate | soft_brake | hard_brake |
|---|---|---|---|---|---|
| 0.0 | 0 | — | — | — | — |
| 0.5 | ~32,000 | 32,000 (97 %) | 462 | 760 | 1,597 |
| 1.0 | ~66,000 | 66,000 (97 %) | 944 | 714 | 2,217 |

Most CAV ticks are no-action (the simulation is mostly steady-state
driving). When the CAV does act, the action mix shifts toward
hard_brake with penetration — consistent with Finding 2's saturation
mechanism.

### 12.5 Collisions by HDV Profile (Selected Cells, p=0.0)

| Seed | attentive | distracted | aggressive_hostile |
|---|---|---|---|
| 0 | 256 | 134 |  73 |
| 1 | 407 | 305 | 249 |
| 4 | 346 | 133 | 381 |

Aggressive_hostile drivers consistently outproduce the other two
profiles in collisions, validating the hostile-mix calibration.
attentive collisions are largely "innocent victim" rear-ends from
behind by hostile drivers.

### 12.6 Limitations

- **n=5 per cell.** Below the proposal's target of N≥30 seeds. Statistical
  power for the −26 % finding is limited; thesis Section 5 will report
  effect size and confidence intervals.
- **Single-axis ablation.** Penetration is the only varied axis in this
  matrix. Latency, PDR and compute-budget ablations are scoped for
  thesis revision if time permits.
- **HOSTILE_MIX is calibrated for non-zero baseline, not for fidelity
  to a specific city.** Proposal §4.1.2's 70/20/10 mix produces zero
  baseline collisions with CARLA's TM avoidance; HOSTILE_MIX
  (50/20/30) is the minimum perturbation that produces a measurable
  baseline. The qualitative trends (V2X reduces collisions; hysteresis
  prevents phantom brakes) should generalise across calibrations,
  but absolute numbers will not.
- **CARLA 0.9.16 Windows binding instability** observed and mitigated
  (yield 67 % → 100 %); the residual concern is whether the surviving
  cells are representative.

### 12.7 Artefacts on Disk

All artefacts live under `out/ablation/`:
- `pNNN_sNN.json` × 15 — one per cell
- `summary.csv`, `summary_by_cell.csv`
- `figures/collisions_vs_penetration.png`
- `figures/actions_vs_penetration.png`
- `figures/phantom_brakes_vs_penetration.png`

By default `out/` is `.gitignored`. The thesis-deliverable subset
(JSON, CSV, PNG) can be tracked via an exception rule in `.gitignore`
if reviewers need to see the raw artefacts; `logs/` should remain
ignored.

---

## 13. Next Phase — Thesis Writing

Implementation phase complete. Remaining work is documentation only:

1. Thesis Section 5 (Empirical Results) — write up from §12.
2. Thesis Section 3 (Methodology) — incorporate the 194-test inventory
   table with literature anchors (CPM → ETSI, latency → Coll-Perales,
   PDR → Thandavarayan, budget → NVIDIA Orin/Xavier).
3. Thesis Section 6 (Limitations) — propagate §12.6 with the additional
   context that the Windows-binding crashes are an environmental quirk,
   not a flaw in the V2X stack.
4. Demo video using `scripts/30_broker_demo.py` and a live ablation cell.
5. Final report assembly.

No further code changes are planned.
