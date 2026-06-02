# Sprint 5 — Handoff (continue in a new chat)

**Written:** 2026-06-02. **Purpose:** carry full state into a fresh context.
Project: V2X-Sim, `PythonAPI/v2x-sim` (CMP794, Taha Yasin Er & Doruk Topçu).

---

## 0. TL;DR — what's happening right now

- A **background run is in progress**: the **full Town01 ablation** (both arms,
  p = 0.0/0.5/0.9/1.0 × 3 weather × 5 seeds, 60 veh + 60 walkers, **max
  fidelity**). Background task id **`bc1e17vum`**.
  Output log: `…\AppData\Local\Temp\claude\…\tasks\bc1e17vum.output`.
  Writes to `out/ablation_sprint5_t01/{v2v,noV2V}/`. ~5 h, 6.5 h hard cap,
  resumable (`--skip-existing`), server-watchdog on. First cell verified healthy
  (Town01 p0: 61 s, 42 collisions, 45/60 walkers spawned).
- **When it finishes:** aggregate the two `t01` dirs, then **regenerate the final
  PDF** with Town01 added (see §6 "Next steps").

---

## 1. Environment (critical — not on PATH)

- **Python (only env that works):**
  `C:\Users\Doruk-Topcu\anaconda3\envs\v2xsim\python.exe`
  (has carla 0.9.16, torch 2.11.0+cu128 on RTX 5080, numpy, asn1tools,
  ultralytics, reportlab, pytest). `conda`/`python` are NOT on PATH — always use
  the absolute path. The base anaconda env lacks the project deps.
- **Repo:** `C:\Users\Doruk-Topcu\Desktop\CARLA_0.9.16\PythonAPI\v2x-sim`
- **Detector weights:** `runs/detect/runs/detect/yolo26s_carla_multi-2/weights/best.pt`
  (note the *nested* `runs/detect/runs/detect/…-2` path — this is the real one).
- **CARLA server:** `C:\Users\Doruk-Topcu\Desktop\CARLA_0.9.16\CarlaUE4.exe`
  — **MUST run at `-quality-level=Epic`**. Low triggers a fatal "Pure virtual"
  crash on walker spawn. Currently running at Epic.
- **Run tests:** `& <env-python> -m pytest tests -q`  → **241 passing**.

---

## 2. What Sprint 5 did (all implemented + tested)

5 aims, all done (code in `v2xsim/`, runner in `scripts/40_ablation_run.py`):
1. **Collision counter** — count one incident per *unordered* pair + immobilise
   crashed cars (`_immobilize`); no actor-destroy crash.
2. **V2V** — new `v2xsim/v2v.py`: CAVs broadcast perceived objects (CPM) + pose +
   hard-brake intent (CAM/DENM); receivers fuse + pre-brake. Same broker.
3. **Spawn overlap** — `try_spawn_actor` + min-separation filter.
4. **Roles** — HDV = HOSTILE_MIX + avoidance OFF; CAV = new `hdv.AI_REALISTIC`
   (~1% errors) + avoidance ON.
5. **Ablation** — two-phase V2V-isolation (V2V on vs `--no-v2v`).

Tests 215 → **241**. New runner knobs: `--no-v2v`, `--v2v-range`,
`--cpm-period-ms`, `--dt`, `--cav-attentive`, `--profile`. Sweep wrapper
`42_ablation_sweep_subprocess.py` adds `--max-hours`, `--deadline-epoch`,
`--cell-timeout-s`, `--carla-exe` + `--restart-after-fails` (watchdog), `--no-v2v`.

---

## 3. Ablation maps & coverage (the key state)

Ablation maps = **Town05 (in-dist), Town10HD_Opt (held-out), Town01 (zero-shot)**.
**Town03 is NOT an ablation map** — it was a Sprint-2 *detector-training* map
(detector trained on Town03+04+05). Do not add Town03 to the ablation.

| Map | Coverage | Fidelity |
|---|---|---|
| **Town05** | ✅ complete — V2V on/off, p=0/0.5/0.9/1.0 | max (10 Hz, dt 0.05) |
| **Town01** | 🔄 RUNNING (this handoff's job) — full both arms, all p | max |
| **Town10HD_Opt** | ⚠️ partial — V2V p0/p0.5 + p1.0 (n=4); V2I only p0/p0.5 (CN+CS). **Left partial on purpose** (see §5). | max |

---

## 4. Results so far (incident counts; total / CAV-involved)

**Town05 (n=15), V2I-only | +V2V:**
| p | V2I-only | +V2V | V2I hb | +V2V hb |
|---|---|---|---|---|
| 0.0 | 27.5/0.0 | 27.5/0.0 | 0 | 0 |
| 0.5 | 14.7/7.3 | 15.5/7.3 | 2,782 | 13,892 |
| 0.9 | 19.4/19.1 (n14*) | 5.6/5.1 | 6,047 | 58,455 |
| 1.0 | 2.0/2.0 | 3.2/3.2 | 6,543 | 45,651 |

`+V2V` Town05 curve is monotone: **27.5 → 15.5 → 5.6 → 3.2**.
*p=0.9 V2I baseline is non-monotonic / high-variance (n=14) — report as suggestive.

**Town10 (held-out, CN+CS):** p0 V2I 41.3 / V2V 42.0; p0.5 V2I 32.2/20.8 → V2V
26.3/15.0 (**−18% / −28%**); p1.0 V2V 8.5/8.5 (n=4), V2I missing.

**Three findings:** (1) penetration is the dominant safety lever and generalises;
(2) V2V's value depends on scenario difficulty (neutral on easy Town05, helps on
hard Town10); (3) reactive cooperative braking costs 3–7× more hard-braking and
slightly rebounds at full penetration on Town05 → coordinated control = future work.

---

## 5. Key gotchas / decisions (carry these forward)

- **Two counting regimes — NEVER mix magnitudes.** Sprint ≤4 counted
  *contact-frames* (inflated, ~650); Sprint 5 counts *incidents* (~tens).
  Compare trends + V2V-on/off within Sprint 5 only.
- **The performance wall = O(N²) V2V *receive* cost.** Profiling
  (`--profile`): Town10 p=1.0 V2V = 249 ms/tick, **83% in `cav_decide`** (each of
  60 CAVs drains + JSON-decodes + fuses ~59 messages/period; `broker.deliveries_due`
  does an O(in-flight) scan *per CAV* → super-linear). V2I-only = 62 ms/tick.
  It's single-threaded (GIL + sync lockstep) → GPU/extra cores idle; 16 GB VRAM
  fits only one Epic server so can't parallelize. **Town10 p=1.0 max-fidelity is
  infeasible** (times out >25 min/cell). **Town01 is fine at max fidelity** (sparse
  grid, 80 ms/tick) — that's why Town01 runs full max-fid but Town10 didn't.
  **Future fix:** index the broker's in-flight queue by `receiver_id` (drain
  O(own messages)) + decode-once per payload → would unlock full Town10/Town01.
- **Reduced tier** (when needed): `--dt 0.1 --cpm-period-ms 200 --cell-timeout-s 1200`
  (~4× less V2V work; ~2.3× faster). NOT magnitude-comparable to max-fidelity —
  keep `*_fast` dirs separate in plots.
- **`42_` filename collision:** a single-map run omits the map from cell
  filenames → collides with other single-map runs in the same `--out-dir`. Always
  use a **dedicated out-dir per single-map run** (that's why Town01 → `…_t01/`).
- **p=0.9 caveat:** noisy V2I baseline (above), don't over-sell the −71%.

---

## 6. Next steps (do these in the new chat)

1. **Check the Town01 run.** Read `…\tasks\bc1e17vum.output` (look for
   `TOWN01 FULL ABLATION DONE`). If still running, wait / monitor; if interrupted,
   resume by re-running the same `42_` command with `--skip-existing` (it's in
   `bc1e17vum`'s command; or re-issue: maps Town01, pens 0.0,0.5,0.9,1.0, 3
   weather, 5 seeds, both arms → `out/ablation_sprint5_t01/{v2v,noV2V}`).
2. **Aggregate:** `python scripts/41_ablation_aggregate.py --in-dir out/ablation_sprint5_t01/v2v`
   and `… --in-dir out/ablation_sprint5_t01/noV2V`.
3. **Compute Town01 numbers** (collisions total/cav by p, both arms) — same script
   pattern used for Town05 (read JSONs, group by penetration).
4. **Regenerate the final PDF:** edit `scripts/make_sprint5_final_report.py` to add
   Town01 as a 2nd complete map (a Town01 results table in §5 + a cross-map
   comparison: in-dist Town05 vs zero-shot Town01 vs held-out Town10; update the
   coverage table in §6 and the data inventory in §8). Then
   `python scripts/make_sprint5_final_report.py` → `SPRINT5_FINAL_REPORT.pdf`.
5. **(Optional, from Taha's to-do):** Welch t-tests + Cohen's d on the incident
   data (penetration main effect per map; V2V-on vs V2I at p=0.5 Town05 vs Town10;
   the p=0.9 trend with its baseline variance).

---

## 7. Files & data inventory

**Reports/docs:**
- `SPRINT5_FINAL_REPORT.pdf` — current final report (WITHOUT Town01 yet; regen after).
- `scripts/make_sprint5_final_report.py` — regenerator (edit to add Town01).
- `SPRINT5_RESULTS.md` — detailed change-log, numbers, §9 data inventory + resume cmds.
- `SPRINT5_REPORT.pdf` — earlier draft (superseded).

**Data dirs (`out/`):** each has `summary.csv`, `summary_by_cell.csv`, `figures/`.
- `ablation_sprint5_full/{v2v,noV2V}` — Town05 p0/0.5/1.0 (+ Town10 v2v partial).
- `ablation_sprint5_full/noV2V_t10` — Town10 V2I p0/p0.5 (CN+CS).
- `ablation_sprint5_p09/{v2v,noV2V}` — Town05 p=0.9.
- `ablation_sprint5_t01/{v2v,noV2V}` — **Town01 (this run)**.
- `ablation_sprint5_t10p100*` — stray mixed-fidelity Town10 p1.0 cells; **NOT used
  in the report** (ignore / safe to delete).
- `out/speedtest/profile_*.json` — the `--profile` breakdowns.

Memory files (persist across chats): `…/.claude/projects/…/memory/MEMORY.md`,
`v2xsim-project-state.md`, `test-environment.md`.
