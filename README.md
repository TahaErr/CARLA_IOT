# V2X-Sim — Cooperative Perception at Smart Intersections

Code for the CMP794 final project (Taha Yasin Er & Doruk Topçu).

**Current status:** Sprint 4 complete — full V2X cooperative-perception
pipeline working end-to-end in CARLA, 194 unit tests passing, ablation
matrix run (3 penetrations × 5 seeds = 15/15 cells), three empirical
findings produced. See `PROGRESS.md` for the full state.

**Headline empirical findings (n=5 seeds per cell, 120 s each, Town05 + 3 RSUs + 30 vehicles):**

| Penetration | Collisions (mean ± std) | Phantom-brake suppression |
|---|---|---|
| 0.0 (HDV-only baseline) | 653 ± 290 | 0 |
| 0.5 (mixed traffic)     | 480 ± 291 | 5.0 |
| 1.0 (full CAV)          | 511 ± 272 | 13.0 |

1. **V2X reduces collisions** at half penetration (−26 %).
2. **Saturation/rebound** at full penetration (+6 %) — naive TTC-only
   reactive braking induces CAV-CAV cascades. Future work: coordinated
   longitudinal control.
3. **Hysteresis is empirically validated** (proposal §4.1.1): phantom-brake
   suppression scales monotonically with penetration (0 → 5 → 13).

---

## Setup (Windows + conda)

CARLA 0.9.16 ships official wheels only for Python 3.10 / 3.11 / 3.12;
this project uses 3.10.

```bat
:: create env
conda create -n v2xsim python=3.10 -y
conda activate v2xsim

:: install package + deps in editable mode
pip install -e .

:: install Ultralytics for YOLO26
pip install ultralytics

:: replace default torch with the CUDA-12.8 build (required for RTX 50-series / sm_120)
pip uninstall torch torchvision torchaudio -y
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

:: Sprint 3 dependencies
pip install asn1tools matplotlib
```

Sanity check:
```bat
python -c "import carla; print('carla', carla.__version__)"
python -c "import torch; print('cuda available:', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
```

Run the full test suite (no CARLA required for 178/194; the remaining
16 are CARLA-bound integration tests):

```bat
pytest -v
```

Expected: 194 passed, 0 failed.

---

## Start the CARLA server

In one terminal:
```bat
cd C:\path\to\CARLA_0.9.16
.\CarlaUE4.exe -quality-level=Low
```

All scripts below assume this server is running on `127.0.0.1:2000`.

---

## Sprint 1 — RSU smoke tests (verify the setup)

```bat
:: A — chase-camera smoke test
python scripts\01_smoke_test.py

:: B1 — list signalised intersections in a map
python scripts\02_list_intersections.py --map Town05

:: B3 — single RSU camera frame at intersection 0
python scripts\03_rsu_capture.py --map Town05 --intersection 0

:: B4 — HD video at a chosen intersection light pole
python scripts\12_rsu_video.py --intersection 0 --light-idx 0 --duration 10
```

Outputs go to `out/`. PASS = files non-empty and visually reasonable.

---

## Sprint 2 — Train a CARLA-specific detector

The full pipeline produces a YOLO26 model fine-tuned on Town03 + Town04
+ Town05, evaluated on Town10 as a held-out test set.

### 1. Survey intersection camera framing (optional)

```bat
python scripts\18_survey_intersections.py --map Town05
```

### 2. Generate training datasets (Town03 + Town04 + Town05)

Each sweep takes 30–45 min on RTX 5080.

```bat
python scripts\15_generate_dataset.py --map Town03 --out .\dataset_multi ^
  --weathers ClearNoon,CloudyNoon,WetNoon,ClearSunset,CloudySunset,HardRainNoon,SoftRainNoon ^
  --frames-per-config 12

python scripts\15_generate_dataset.py --map Town04 --out .\dataset_multi ^
  --weathers ClearNoon,CloudyNoon,WetNoon,ClearSunset,CloudySunset,HardRainNoon,SoftRainNoon ^
  --frames-per-config 12

python scripts\15_generate_dataset.py --map Town05 --out .\dataset_multi ^
  --weathers ClearNoon,CloudyNoon,WetNoon,ClearSunset,CloudySunset,HardRainNoon,SoftRainNoon ^
  --frames-per-config 12
```

### 3. Check class balance

```bat
python scripts\19_check_distribution.py .\dataset_multi
```

Imbalance should be < 4x for every class.

### 4. Generate the held-out Town10 test set

```bat
python scripts\15_generate_dataset.py --map Town10HD_Opt --out .\dataset_town10_v2 ^
  --weathers ClearNoon,CloudyNoon,WetNoon,ClearSunset,CloudySunset,HardRainNoon,SoftRainNoon ^
  --frames-per-config 12 --val-stride 1
```

### 5. Fine-tune YOLO26s

```bat
python scripts\16_train_yolo.py --data .\dataset_multi\data.yaml ^
  --name yolo26s_carla_multi
```

Defaults: `imgsz=1280, batch=8, epochs=50, patience=20, cache=False`.
Takes ~2–3 hours on RTX 5080.

Output: `runs/detect/yolo26s_carla_multi/weights/best.pt`.

### 6. Cross-town evaluation

```bat
python scripts\17_eval_town10.py ^
  --weights runs/detect/yolo26s_carla_multi/weights/best.pt ^
  --data .\dataset_town10_v2\data.yaml
```

Expected: mAP@50 ≈ 0.53, precision ≈ 0.85, recall ≈ 0.50.

---

## Sprint 3 — V2X protocol stack (CARLA-agnostic)

All Sprint 3 modules are pure-Python and don't require CARLA. Verified
by 96 unit tests in `tests/test_cpm.py`, `tests/test_latency.py`,
`tests/test_pdr.py`, `tests/test_compute_budget.py`, `tests/test_broker.py`
and `tests/test_integration.py`.

```bat
:: Verify the Sprint 3 stack in isolation
pytest tests\test_cpm.py tests\test_latency.py tests\test_pdr.py ^
       tests\test_broker.py tests\test_compute_budget.py tests\test_integration.py -v
```

Module map (`v2xsim/`):

| Module | Standard / reference | Purpose |
|---|---|---|
| `cpm.py` | ETSI TS 103 324 v2.1.1 | CPM Release 2 encoder/decoder, UPER ASN.1 |
| `latency.py` | Coll-Perales et al. 2023 | 5G NR-V2X end-to-end latency model |
| `pdr.py` | Thandavarayan et al. 2020 | Distance + channel-load packet delivery |
| `compute_budget.py` | NVIDIA Orin/Xavier datasheets | Per-RSU + aggregate edge compute caps |
| `broker.py` | (architectural) | In-process pub/sub with PDR/latency/CBR |
| `rsu.py` | (architectural) | CARLA-agnostic RSU pipeline |

ETSI ASN.1 specs live in `specs/cpm/` and are tracked in git. `cpm.py`
and the integration tests are skipped if the specs aren't present.

---

## Sprint 4 — CARLA integration and ablation matrix

Sprint 4 wires the Sprint 3 stack into a running CARLA simulation and
runs the ablation matrix defined in proposal §4.7.

### Module map (additions to `v2xsim/`)

| Module | Tests | Purpose |
|---|---|---|
| `projection.py` | 13 | Camera intrinsics + image↔world projection |
| `carla_rsu.py` | 9 | CARLA-bound RSU: camera + YOLO + Sprint 3 pipeline |
| `cav.py` | 25 | **Thesis algorithmic core** — CAVCore time-aware late-fusion + 3-rule hysteresis + TTC ladder |
| `hdv.py` | 18 | NHTSA-aligned driver profiles + HOSTILE_MIX |
| `carla_cav.py` | 17 | CARLA-bound CAV wrapper, GT-cone local sensor |

### Run the ablation matrix

The ablation runner spawns 30 vehicles in Town05 across 3 RSUs at
intersections 0, 3 and 7, runs the simulation for 120 s, and records
collisions, CAV decisions, and phantom-brake suppression events.
Penetration sweeps 0.0 / 0.5 / 1.0 with 5 seeds each (15 cells total).

The sweep is wrapped in a subprocess-isolation helper because CARLA
state would otherwise accumulate across cells:

```bat
:: Single cell (smoke test)
python scripts\40_ablation_run.py ^
  --detector runs\detect\yolo26s_carla_multi\weights\best.pt ^
  --penetration 0.0 --seed 0 --duration 20 ^
  --out out\ablation\smoke.json

:: Full 3 × 5 sweep (~30 min wall time)
python scripts\42_ablation_sweep_subprocess.py ^
  --detector runs\detect\yolo26s_carla_multi\weights\best.pt ^
  --out-dir out\ablation

:: Aggregate into CSVs + matplotlib figures
python scripts\41_ablation_aggregate.py --in-dir out\ablation
```

Outputs land in `out/ablation/`:
- `pNNN_sNN.json` × 15 — one per cell
- `summary.csv` — flat table, one row per cell
- `summary_by_cell.csv` — mean ± std per penetration level
- `figures/collisions_vs_penetration.png`
- `figures/actions_vs_penetration.png`
- `figures/phantom_brakes_vs_penetration.png`

### Resuming a partial sweep

If any cells crash (CARLA 0.9.16 Windows binding occasionally throws
`STATUS_STACK_BUFFER_OVERRUN` in the collision-sensor callback), rerun
with `--skip-existing` to fill only the missing cells:

```bat
python scripts\42_ablation_sweep_subprocess.py ^
  --detector runs\detect\yolo26s_carla_multi\weights\best.pt ^
  --out-dir out\ablation --skip-existing
```

In our experiments the post-fix yield is 15/15 (was 10/15 before the
in-sync-mode cleanup + event-cap fix in `scripts/40_ablation_run.py`).

---

## Project layout

```
v2x-sim/
├── pyproject.toml
├── README.md                           # this file
├── PROGRESS.md                         # detailed implementation notes
├── SPRINT3_HANDOFF.md                  # archived — Sprint 3 plan (kept for history)
├── .gitignore
├── specs/cpm/                          # ETSI TS 103 324 v2.1.1 ASN.1 (tracked)
├── v2xsim/                             # importable package
│   ├── __init__.py
│   ├── carla_utils.py
│   ├── intersections.py
│   ├── projection.py                   # Sprint 4
│   ├── cpm.py                          # Sprint 3
│   ├── latency.py                      # Sprint 3
│   ├── pdr.py                          # Sprint 3
│   ├── compute_budget.py               # Sprint 3
│   ├── broker.py                       # Sprint 3
│   ├── rsu.py                          # Sprint 3
│   ├── carla_rsu.py                    # Sprint 4
│   ├── cav.py                          # Sprint 4 (thesis core)
│   ├── hdv.py                          # Sprint 4
│   └── carla_cav.py                    # Sprint 4
├── tests/                              # 194 tests
│   ├── test_cpm.py                     #  22
│   ├── test_latency.py                 #  19
│   ├── test_pdr.py                     #  17
│   ├── test_compute_budget.py          #  18
│   ├── test_broker.py                  #  18
│   ├── test_rsu.py                     #  12
│   ├── test_integration.py             #   6
│   ├── test_projection.py              #  13
│   ├── test_carla_rsu.py               #   9
│   ├── test_cav.py                     #  25
│   ├── test_hdv.py                     #  18
│   └── test_carla_cav.py               #  17
└── scripts/
    ├── 01_smoke_test.py                # Sprint 1
    ├── 02_list_intersections.py        # Sprint 1
    ├── 03_rsu_capture.py               # Sprint 1
    ├── 12_rsu_video.py                 # Sprint 1
    ├── 13_yolo_test.py                 # Sprint 2
    ├── 14_rsu_video_yolo.py            # Sprint 2
    ├── 15_generate_dataset.py          # Sprint 2
    ├── 16_train_yolo.py                # Sprint 2
    ├── 17_eval_town10.py               # Sprint 2
    ├── 18_survey_intersections.py      # Sprint 2
    ├── 19_check_distribution.py        # Sprint 2
    ├── 30_broker_demo.py               # Sprint 4 — manual broker demo
    ├── 31_bisect_step2_collision_sensors.py   # Sprint 4 diagnostic
    ├── 32_bisect_step3_hostile_mix.py         # Sprint 4 diagnostic
    ├── 33_bisect_step4_carla_cav.py           # Sprint 4 diagnostic
    ├── 40_ablation_run.py              # Sprint 4 — single ablation cell
    ├── 41_ablation_aggregate.py        # Sprint 4 — CSV + figure aggregator
    └── 42_ablation_sweep_subprocess.py # Sprint 4 — process-isolated sweep
```

---

## Troubleshooting

- **`pip install carla==0.9.16` fails:** confirm the env is Python 3.10.
- **`RuntimeError: time-out of 20000ms` on connect:** the CARLA server
  isn't running, or it's on a different port. Default is 2000. A
  previous crashed run can leave the server in sync mode — restart
  `CarlaUE4.exe`.
- **`Map 'Town10' not found`:** the CARLA packaged build names it
  `Town10HD_Opt`. Use that as the `--map` argument.
- **CPU inference instead of GPU (~30 ms/frame):** reinstall torch with
  the CUDA-12.8 build.
- **`MemoryError` during train caching:** Use `--cache disk` or
  `--cache False` (default).
- **Train output ends up in `runs/detect/runs/detect/<name>`:** known
  Ultralytics 8.4.48 quirk; the current train script avoids it. Verify
  via the `weights at:` line.
- **Ablation cell crashes with rc=3221226505 (Windows):** this is
  `STATUS_STACK_BUFFER_OVERRUN`, a CARLA 0.9.16 Windows binding issue
  in the collision-sensor callback. The runner mitigates it via
  in-sync-mode cleanup and a hard cap on collision events. Surviving
  cells are valid; rerun missing ones with `--skip-existing`.

---

## Next phase — thesis writing

All implementation work is complete. Remaining tasks are documentation:
- Thesis Section 5 (Empirical Results) — write up from `summary_by_cell.csv` + figures
- Thesis Section 3 (Methodology) — incorporate the 194-test inventory table
- Thesis Section 6 (Limitations) — CARLA Windows binding stability,
  n=5 per cell, HOSTILE_MIX calibration justification
- Demo video
- Final report
