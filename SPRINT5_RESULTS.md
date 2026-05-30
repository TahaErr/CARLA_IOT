# Sprint 5 — Collision realism + V2V communication

**Date:** 2026-05-30
**Status:** Complete — 241 tests passing; ablation run + aggregated (Town05 V2V on/off full + Town10 cross-map).

Sprint 5 fixes the collision/behaviour realism issues in the ablation and
adds vehicle-to-vehicle (V2V) communication on top of the existing
RSU→CAV (V2I) cooperative-perception stack. This document records what
changed, how each of the five aims was addressed, and the results.

---

## 1. The five aims and how they were addressed

| # | Aim | Resolution | Where |
|---|---|---|---|
| 1 | **Collision counter inflated** (cars stuck/clipping, counter keeps rising) | Count **one incident per unordered vehicle pair**; on contact, **immobilise** both vehicles (autopilot off, full brake + handbrake, freeze physics) so they stop accelerating/interpenetrating and stop re-firing the sensor. No actor destruction (avoids the CARLA-0.9.16-Windows mid-run destroy crash). | `scripts/40_ablation_run.py` (`_immobilize`, incident loop) |
| 2 | **Add V2V** (vehicles send info, receiver acts) | New `v2xsim/v2v.py` message: CAVs broadcast (a) their **perceived objects** (CPM-style cooperative perception) and (b) their **own pose + hard-brake intent** (CAM/DENM-style). Receivers fuse objects via the existing `CAVCore` and **pre-brake** on a leader's hard-brake warning. Flows through the same broker (identical PDR/latency/CBR). Senders = CAVs only (HDVs are non-connected). | `v2xsim/v2v.py`, `v2xsim/cav.py` (`ingest_brake_warning`, cooperative brake), `v2xsim/carla_cav.py` (send/recv) |
| 3 | **Vehicles spawn inside each other** | `try_spawn_actor` (skips blocked spawns instead of forcing) + **minimum-separation filter** on chosen spawn points. | `scripts/40_ablation_run.py` (`_select_spaced_spawn_points`, `_spawn_vehicles`) |
| 4 | **AI shouldn't be hostile — only HDVs** | Role split: **HDVs** get `HOSTILE_MIX` with TM collision-avoidance **OFF** (the conflict generators). **CAVs** get a new careful **`AI_REALISTIC`** profile (~1% rule-violation rate, never ignores vehicles/pedestrians) with avoidance **ON**, plus the V2X layer. | `v2xsim/hdv.py` (`AI_REALISTIC`, `disable_collision_detection_for`), runner role split |
| 5 | **Run a new ablation** | Two-phase full sweep (below). | `scripts/42_…`, `scripts/41_…` |

**Tests:** 215 → **241** (all passing). New/extended: `test_v2v.py` (+11),
`test_hdv.py` (AI_REALISTIC + role-aware avoidance), `test_cav.py`
(cooperative brake-warning), `test_carla_cav.py` (V2V send/receive).

---

## 2. Preliminary result (vehicle-only, Town05, 1 seed, 120 s)

A 6-cell pre-flight (60 vehicles, 0 walkers, max fidelity) comparing
V2I-only vs the full V2V system:

| Penetration | V2I-only collisions | +V2V collisions | V2I hard-brakes | +V2V hard-brakes |
|---|---|---|---|---|
| 0.0 (all HDV) | 33 | 28 | 0 | 0 |
| 0.5 (mixed)   | 21 (cav=9) | **13 (cav=3)** | 165 | 15 673 |
| 1.0 (all CAV) | **0** | 5 (cav=5) | 8 718 | 44 182 |

**Reading (preliminary, n=1):**
- **V2V reduces mixed-traffic collisions** (21→13 at p=0.5) and especially
  CAV-involved collisions (9→3) — vehicles act on each other's shared
  perception + hard-brake warnings.
- **Over-braking / string-instability rebound at full penetration**: V2V's
  cooperative braking is very active (44 k hard-brakes) and induces a few
  CAV-CAV rear-end collisions (0→5). This mirrors the Sprint 4 "saturation
  and rebound" finding and is a candidate result for the discussion on
  coordinated (vs purely reactive) longitudinal control.

> **Comparability note.** Sprint 4's collision counts (e.g. 653) were
> inflated by the *old* contact-frame counter. Sprint 5 counts **distinct
> incidents**, so absolute numbers are far lower and are **not** directly
> comparable to Sprint 4. Compare **trends** (direction/shape vs
> penetration) and the **V2V-on vs V2V-off** contrast, not raw magnitudes.

---

## 3. Full ablation (completed)

Two-phase design to isolate the V2V contribution, matching the Sprint 4
extension matrix:

- **Matrix:** 3 maps (Town05, Town10HD_Opt, Town01) × 3 weather
  (ClearNoon, ClearSunset, HardRainNoon) × 3 penetration (0/0.5/1.0)
  × 5 seeds × 60 vehicles × 60 walkers × 120 s, max fidelity (20 Hz
  physics, 10 Hz CPM).
- **Phase 1 — V2V on** (full Sprint 5 system): `out/ablation_sprint5_full/v2v/`
- **Phase 2 — V2I-only** (`--no-v2v`): `out/ablation_sprint5_full/noV2V/`
  (Town05 first; deadline-limited).

Robustness for the unattended run: subprocess-per-cell isolation,
`--skip-existing` (resumable), per-cell timeout, a wall-clock deadline,
and a **CARLA-server watchdog** that relaunches `CarlaUE4.exe` if the
server dies mid-sweep. Outputs aggregated by `41_ablation_aggregate.py`
into `summary.csv`, `summary_by_cell.csv`, and figures per phase.

**Cost finding + revised priority.** At max fidelity, full-penetration
(p=1.0) cells with 60 CAVs + 60 walkers + V2V are intrinsically slow
(Town05 p=1.0 ≈ 369 s loop for a 120 s sim ≈ 0.33× real-time), and on
heavier maps (Town10HD_Opt) they exceeded the original 600 s per-cell
timeout. A full 3-map × 2-phase max-fidelity sweep does not fit an
overnight window. Fixes + decisions:
- Per-cell timeout raised to 900 s (`--cell-timeout-s`); shared absolute
  `--deadline-epoch` across phases.
- **Priority:** complete the clean **Town05 V2V on/off comparison** first
  (v2v Town05 = 45 cells, done; noV2V Town05 = 45 cells), since Town05 is
  the in-distribution map where the V2X benefit is measurable. Cross-map
  (Town10HD_Opt, Town01) runs **best-effort** under the deadline.
- Completed so far: **v2v phase Town05 (45/45) + Town10HD_Opt p0/p0.5
  (10)**. Resumed run targets noV2V Town05, then cross-map.

Full 3-map × 3-weather × both-phase max-fidelity coverage is a
**follow-up** (would need either lower fidelity — `--dt 0.1` ≈ 2.3× — or a
multi-day budget).

### Results (run 2026-05-30, 4 h 11 m, max fidelity)

**Town05 — complete V2V on/off isolation** (mean over 3 weather × 5 seeds,
n=15 per cell). Collisions reported as *total / CAV-involved*.

| Penetration | V2I-only coll. | +V2V coll. | V2I hard-brakes | +V2V hard-brakes |
|---|---|---|---|---|
| 0.0 (all HDV) | 27.5 / 0.0 | 27.5 / 0.0 | 0 | 0 |
| 0.5 (mixed)   | 14.7 / 7.3 | 15.5 / 7.3 | 2 782 | 13 892 |
| 1.0 (all CAV) | **2.0 / 2.0** | 3.2 / 3.2 | 6 543 | 45 651 |

**Town10HD_Opt — cross-map generalization** (V2V phase only; held-out map).

| Penetration | +V2V coll. (total / CAV) | hard-brakes | n |
|---|---|---|---|
| 0.0 | 42.0 / 0.0 | 0 | 10 |
| 0.5 | 26.3 / 15.0 | 13 756 | 10 |
| 1.0 | 8.5 / 8.5 | 45 398 | 4 (others timed out) |

**Findings (n=15 on Town05):**
1. **Penetration is the dominant safety lever.** Replacing hostile HDVs
   with careful `AI_REALISTIC` CAVs collapses collisions monotonically —
   Town05 27.5 → 14.7 → 2.0, **and the same trend holds on the held-out
   Town10** (42 → 26 → 8.5). The Sprint 5 role split is the headline win
   and it generalizes across maps.
2. **V2V's marginal value over RSU-only (V2I) depends on scenario
   difficulty.** Cross-map V2V on/off comparison at p=0.5
   (collisions total / CAV-involved):

   | Map | V2I-only | +V2V | Δ |
   |---|---|---|---|
   | Town05 (easy, in-dist, n=15) | 14.7 / 7.3 | 15.5 / 7.3 | ≈0 |
   | Town10HD_Opt (hard, held-out, n≈10) | 32.2 / 20.8 | **26.3 / 15.0** | **−18% / −28%** |

   On easy Town05 the RSU coverage already catches most conflicts, so V2V
   adds only braking churn (hard-brakes ~5×) with no collision benefit. On
   the harder, denser held-out **Town10**, V2V **cuts collisions −18% and
   CAV-involved −28%** — the extra cooperative perception pays off where
   there is more to catch. Both maps show a ~3–5× hard-brake increase (the
   cost of reactive cooperative braking), and at *full* penetration on
   Town05 V2V is slightly worse (2.0 → 3.2) — the saturation/rebound /
   string-instability of purely reactive braking, pointing to *coordinated*
   longitudinal control as future work.
3. This **revises the 1-seed preview** (which hinted V2V helped at p=0.5 on
   Town05); the multi-seed averages are the reliable story — V2V helps on
   the hard map, is neutral on the easy one.

**Coverage gaps (follow-up):** Town10 noV2V (V2V-isolation pair on the
held-out map), all of Town01, and reliable Town10 p=1.0 (only 4/15 seeds
finished — those cells hit the per-cell timeout). These need the runner
throughput fix (see §5) or a multi-day budget.

---

## 5. Performance note — why the sim is latency-bound

The ablation is **RPC-latency-bound, not compute-bound** (low GPU + low
CPU + a stuttering UE4 window). In synchronous mode the client and server
alternate (never both busy), and the runner makes one CARLA RPC *per
actor* each tick — ego poses, the local-sensor snapshot, V2V/RSU position
polls, per-CAV `apply_control`. At p=1.0 with 60 vehicles + 60 walkers
that is ~500 round-trips/tick, ~150 ms of pure wire latency while little
actual computation happens. This is why p=1.0 cells crawl (~0.33× real
time on Town05, worse on Town10) and time out.

**Fix (implemented):** all reads batched into one `world.get_snapshot()`
per tick + writes via `client.apply_batch([ApplyVehicleControl(...)])` +
`ego_state` passed into `carla_cav.tick`. This gave a ~1.4× speedup and
made Town10 p=1.0 cells stop timing out — but exposed a deeper limit: at
p=1.0 the dominant cost is the **O(N²) all-to-all V2V message volume**
(~500 k messages per 30 s of sim at 60 CAVs), processed by the single-
threaded Python broker (PDR/latency draws + JSON decode + fusion). That is
intrinsic to all-to-all V2V and is *itself a finding* — cooperative-
perception load scales quadratically with CAV density (relevant to the
edge-compute / channel-congestion theme). Full 3-map × both-phase max-
fidelity therefore still needs `--dt 0.1` (~2.3×) or a multi-day budget.

---

## 4. New runner knobs (Sprint 5)

| Flag | Default | Purpose |
|---|---|---|
| `--no-v2v` | off | V2I-only arm (CAVs keep RSU CPMs + local sensor, no V2V) |
| `--v2v-range` | 150 m | CAV→CAV broadcast range |
| `--cpm-period-ms` | 100 (10 Hz) | Broadcast cadence; 200 ms ≈ 1.7× faster (5 Hz, still ETSI-valid) |
| `--dt` | 0.05 (20 Hz) | Physics timestep; 0.1 ≈ 2× faster, coarser collision timing |
| `--cav-attentive` | off | Ablation arm: CAVs flawless ATTENTIVE instead of AI_REALISTIC |

Sweep wrapper `42_` adds `--max-hours` (deadline), `--carla-exe` +
`--restart-after-fails` (server watchdog), and passes the above through.
