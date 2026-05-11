# V2X-Sim — Progress Report

**Project:** Cooperative Perception at Smart Intersections — A CARLA Study of 5G NR-V2X with ETSI CPM Release 2 under Realistic Edge-Compute and Latency Constraints in Mixed Traffic
**Course:** CMP794 — Final Project
**Authors:** Taha Yasin Er, Doruk Topçu
**Repository:** https://github.com/TahaErr/CARLA_IOT
**Status:** End of Sprint 2 (detector trained, cross-town evaluated). Ready to start Sprint 3 (CPM encoder + V2X channel model).

---

## 1. What This Document Covers

A detailed snapshot of the project's implementation state. It records what has been built, what design decisions were made (and why), what empirical findings have already shaped the project, and what remains. Each piece of work is anchored back to the original proposal section it implements, so the document doubles as a traceability record.

For the methodological rationale (why the project exists), see the proposal. For how to run anything described here, see `README.md`.

---

## 2. Environment & Stack

| Component | Version | Notes |
|---|---|---|
| OS | Windows 11 | UE4 build path; native CUDA + drivers |
| GPU | NVIDIA RTX 5080 (Blackwell, sm_120) | 16 GB VRAM |
| CUDA | 12.8 | Required for sm_120; older runtimes silently fall back to sm_89 |
| Python | 3.10 | CARLA 0.9.16 only ships wheels for 3.10 / 3.11 / 3.12 |
| CARLA | 0.9.16 (UE4 packaged build) | UE5 binary unavailable in this distribution |
| PyTorch | 2.11.0 + cu128 | First stable line with native sm_120 support is 2.7.0; 2.11.0 is the current recommended CUDA-12.8 build for Blackwell |
| Ultralytics | 8.4.48 | Required for YOLO26 model loader |
| Conda env | `v2xsim` | Editable install of the local `v2xsim` package |
| System RAM | 64 GB | Relevant because Windows multiprocessing + RAM cache pickle hit a MemoryError at 22 GB cached frames (see §5.4) |

---

## 3. Sprint 1 — RSU Infrastructure

**Goal.** Stand up the smallest possible Roadside Unit (RSU) substrate the rest of the project can grow on: a deterministic, programmatically-discoverable set of signalised intersections, and a working camera mounted to one of them, capturing frames into the project filesystem.

**Proposal mapping.** §4.1 (Architecture: smart intersections instrumented with cameras + Edge-AI compute), §4.5 (Map setup).

### 3.1 Components Built (Sprint 1)

| Module | Purpose |
|---|---|
| `v2xsim/carla_utils.py` | `connect()` helper with timeout; `synchronous_mode()` context manager that restores async settings on exit; `ensure_map()` to load a target town |
| `v2xsim/intersections.py` | `discover_intersections()` returning all signalised intersections, deterministically sorted by world coords |
| `v2xsim/rsu.py` | RSU class wrapping a single overhead camera mounted on a traffic-light pole |
| `scripts/01_smoke_test.py` | Sanity test: connect, spawn a Tesla, attach a chase camera, capture one image |
| `scripts/02_list_intersections.py` | Prints every signalised intersection in a given map with its centroid and number of lights |
| `scripts/03_rsu_capture.py` | Mounts an RSU at a chosen intersection and saves one frame per traffic-light pole |
| `scripts/12_rsu_video.py` | Captures HD video from the RSU camera while traffic flows through the intersection |

### 3.2 Findings (Sprint 1)

#### 3.2.1 Map intersection counts (used by Sprint 2 multi-town training)

| Map | Signalised intersections | Notes |
|---|---|---|
| Town03 | 11 | Downtown, varied geometries; intersections 6–7 are on an overpass (z = 8 m), giving useful diversity |
| Town04 | 12 | Highway + suburban mix |
| Town05 | 15 | Original train map for early Sprint 2 |
| Town10HD_Opt | 10 | Modern HD downtown; **held-out test map** (proposal §3) |

Total intersections used for training in Sprint 2 step 3: **38** (Town03 + Town04 + Town05). Test: **10** (Town10).

#### 3.2.2 Multi-camera limit in CARLA 0.9.16 (Windows packaged build)

Through systematic bisection: spawning ≥ 4 RGB cameras simultaneously, or 2+ standalone cameras at independent positions, crashes the engine in this build. The only configuration that works reliably is **a single standalone camera** at a time. **Sprint 1 originally read this as a hard constraint on yaw — `yaw=0` was the only value verified safe — but Sprint 2 (script `18_survey_intersections.py`, then dataset generator) confirmed this was a multi-camera-context bug. Single-camera at arbitrary yaw is safe.** The dataset generator now uses auto-yaw pointing at each intersection's centroid (see §5.1).

#### 3.2.3 Architectural consequence: single-camera RSU

The proposal originally describes one RSU per intersection with **four cameras** (one per approach). Given the bug, the architecture is **one camera per RSU**. Sprint 2 captures dataset configurations sequentially (one camera at a time, destroyed and re-spawned at each light) rather than in parallel. Production smart-intersection deployments (NYC DOT TRAVELERS, FDOT ATSPM, several MaaS Global pilots) typically use 1–2 cameras per intersection rather than four, so the simplification is defensible. The proposal §4.1 needs a revision note acknowledging this.

#### 3.2.4 Deterministic intersection numbering

`discover_intersections()` sorts by `(round(center.x, 1), round(center.y, 1))` and reassigns sequential IDs. Without this, intersection IDs reshuffled across CARLA server restarts, which would break the train/val split in Sprint 2 step 2 (split driven by `intersection_idx % val_stride`).

---

## 4. Sprint 2, Step 1 — Detection on RSU Frames

**Goal.** Confirm a real object detector runs on RSU frames, characterise its baseline behaviour on synthetic CARLA imagery, and identify what fine-tuning has to fix.

**Proposal mapping.** §4.1 (RSU pipeline: detector → CPM encoder), §4.4 (edge-compute budget tied to detector inference time), §5 (sim-to-real gap as a known limitation).

### 4.1 Migration: YOLOv8 → YOLO26

The proposal originally cites YOLOv8-s. After verification of the current ecosystem state, Sprint 2 was upgraded to **YOLO26** (Ultralytics, released September 2025): edge-first design, NMS-free, ProgLoss + STAL for small-object accuracy — directly relevant to the proposal's VRU detection target. Drop-in replacement; only the weight string changed (`yolov8s.pt` → `yolo26s.pt`).

### 4.2 GPU Configuration: RTX 5080 / Blackwell / sm_120

Default `pip install ultralytics` pulls a PyTorch wheel that lacks sm_120 kernels — the first run silently fell back to CPU inference at 34 ms/frame. Resolved by switching to the CUDA-12.8 build (`torch+cu128`) and adding an explicit `model.to("cuda")` + `device=0` everywhere.

### 4.3 Inference Performance (yolo26s on RTX 5080)

| Resolution | Inference / frame | Notes |
|---|---|---|
| 320×240 | 10 ms | CPU was 34 ms |
| 1280×720 | ~10 ms | Model resizes to `imgsz` internally |
| 1280 imgsz (training) | ~9 ms | Used by `16_train_yolo.py` |
| 640 imgsz (early eval) | ~3 ms | Discovered as a bug — train/eval imgsz mismatch (see §5.5) |

**Edge-compute consequence.** 9 ms at imgsz=1280 fits comfortably in both edge profiles defined in proposal §4.4: Orin (20 ms/frame) → 45% util; Xavier (50 ms/frame) → 18% util. Aggregate 38 RSUs × 9 ms = 342 ms vs. 10% of an L4 onboard system (~750 ms) → 46% util.

### 4.4 Empirical Evidence of Sim-to-Real Domain Shift

A 20 s run on Town05 with COCO-pretrained yolo26s produced false positives like `sheep` (a 30 km/h speed-limit sign), `cow`, `elephant`. Real vehicles were detected with high confidence (0.5–0.9). This is the empirical justification for fine-tuning — without it, downstream CPM encoders would receive untrustworthy detections.

---

## 5. Sprint 2, Step 2 — Sweep Dataset Generator

**Goal.** Produce a Town05 + Town03 + Town04 labelled dataset that lets us fine-tune YOLO26 on CARLA imagery, plus a Town10 cross-town test set.

**Proposal mapping.** §4.1 ("fine-tuned on a Town05-only labelled set" — extended to multi-town after empirical findings), §3 (cross-town generalisation as a central claim), §4.6 ("RSU detector precision/recall measured on the held-out Town10 map").

### 5.1 Implementation: `scripts/15_generate_dataset.py`

Sweeps across (intersection, light, weather) configurations. Each config: spawn one standalone camera at the chosen light pole (auto-yaw pointing at intersection centroid), warmup, capture N frames separated by sim ticks, write YOLO labels (axis-aligned 2D bbox from 3D bbox projection of all visible vehicles + walkers within 80 m).

**Class scheme (4-class):**
- 0 `vehicle` (4-wheel)
- 1 `motorcycle` (2-wheel + harley/kawasaki/yamaha/vespa keyword)
- 2 `bicycle` (2-wheel without motorcycle keyword)
- 3 `pedestrian` (walker.*)

### 5.2 Class Balance Strategy

The first end-to-end iteration on Town05 produced a 10:1 imbalance (vehicle dominant) because CARLA's vehicle blueprint pool is ~5x more 4-wheeled than 2-wheeled, and random walker spawning placed most pedestrians outside the RSU camera radius. The first fine-tune confirmed the impact: motorcycle mAP@50 = 0.11.

Two patches fixed this:

1. **`spawn_traffic_global` — balanced BP pool.** Partition blueprints by `number_of_wheels`, sample `n_two_wheelers + n_four_wheelers` independently via `random.choice`, shuffle the combined list before assigning to spawn points (a previous attempt assigned them sequentially and produced a spatial class bias). `--two-wheeler-fraction` defaults to 0.5.
2. **`spawn_walkers_near_intersections` — proximity-filtered.** Reject nav-mesh samples outside `--walker-radius` (default 50 m) of any intersection centre. Walker AI targets are also constrained to be near intersections so walkers don't drift out of RSU coverage.

### 5.3 Multi-Town Training Strategy

Initial training on Town05 only produced a Town10 cross-town mAP@50 of 0.41 with very poor bicycle generalisation (Town05 val = 0.85 → Town10 = 0.23, classic overfitting). Switched to training on **Town03 + Town04 + Town05** combined (38 intersections, 14930 train frames, 4141 val frames), with Town10 held out as the test set.

To support multi-map sweeps writing into the same dataset directory, the `frame_id` now includes a map slug: `Town03_t00_l0_ClearNoon_000`. Without this, intersection IDs would collide across maps and overwrite each other.

### 5.4 Final Dataset Statistics

**Train + val (`dataset_multi/`, Town03 + Town04 + Town05):**

| Class | Train | Val | Imbalance |
|---|---|---|---|
| 0 vehicle | 13572 | 5499 | 1.0x |
| 1 motorcycle | 8803 | 3556 | 1.5x |
| 2 bicycle | 5234 | 1385 | 2.6x |
| 3 pedestrian | 11684 | 4007 | 1.2x |
| **Total** | **39293** | **14447** | — |

**Cross-town test (`dataset_town10_v2/`, Town10HD_Opt, `--val-stride 1`):**

| Class | Val (test) |
|---|---|
| 0 vehicle | 5488 |
| 1 motorcycle | 2712 |
| 2 bicycle | 2400 |
| 3 pedestrian | 3921 |
| **Total** | **14521** |

Weather presets used (7 total): `ClearNoon`, `CloudyNoon`, `WetNoon`, `ClearSunset`, `CloudySunset`, `HardRainNoon`, `SoftRainNoon`. Frames per config: 12.

### 5.5 Train/Eval imgsz Mismatch (Bug, Fixed)

The first training run was at `imgsz=1280` but the eval script defaulted to `imgsz=640` — downsampling the model's input at evaluation time. This was caught by noticing inference speed: 2.9 ms (eval) vs ~9 ms (train), too fast for 1280. Town10 mAP@50 jumped from **0.347 → 0.411** after fixing the eval default to 1280. The bug demonstrated that 640 silently halves linear resolution and damages small-object (VRU) detection.

---

## 6. Sprint 2, Step 3 — Fine-Tune and Cross-Town Evaluation

**Goal.** Train yolo26s on the multi-town dataset, evaluate on the held-out Town10 test set, and report precision/recall per class as required by proposal §4.6.

### 6.1 Implementation: `scripts/16_train_yolo.py`, `scripts/17_eval_town10.py`

Standard Ultralytics fine-tune. Defaults:
- `imgsz=1280, batch=8, epochs=50, patience=20, seed=0`
- `cache=False` (Windows-safe; RAM cache fails on multiprocessing pickle — see §6.4)
- Augmentation: Ultralytics defaults (mosaic, hsv, fliplr, scale, translate, erasing, RandAugment)

### 6.2 Final Metrics

**Multi-town val (Town03 + Town04 + Town05 held-out intersections):**

| Class | Precision | Recall | mAP@50 | mAP@50:95 |
|---|---|---|---|---|
| vehicle | — | — | 0.793 | 0.694 |
| motorcycle | — | — | 0.827 | 0.699 |
| bicycle | — | — | 0.809 | 0.652 |
| pedestrian | — | — | 0.599 | 0.396 |
| **mean** | **0.926** | **0.712** | **0.757** | **0.610** |

**Town10 cross-town (test set):**

| Class | Precision | Recall | mAP@50 | mAP@50:95 |
|---|---|---|---|---|
| vehicle | 0.779 | 0.533 | 0.550 | 0.412 |
| motorcycle | 0.860 | 0.514 | 0.539 | 0.411 |
| bicycle | 0.871 | 0.528 | 0.565 | 0.388 |
| pedestrian | 0.897 | 0.426 | 0.484 | 0.266 |
| **mean** | **0.852** | **0.500** | **0.534** | **0.369** |

### 6.3 Findings

**Multi-town training closed the cross-town gap dramatically vs. Town05-only baseline.** Comparison at Town10 cross-town:

| Class | Town05-only mAP@50 | Multi-town mAP@50 | Δ |
|---|---|---|---|
| vehicle | 0.532 | 0.550 | +0.02 |
| motorcycle | 0.408 | 0.539 | +0.13 |
| bicycle | 0.301 | 0.565 | **+0.26** |
| pedestrian | 0.403 | 0.484 | +0.08 |
| **mean** | **0.411** | **0.534** | **+0.12** |

Bicycle had the largest gain (single-town overfitting eliminated). The remaining cross-town gap (val 0.76 → test 0.53, Δ = 0.22) is consistent across all four classes, suggesting it is a residual sim-to-sim domain shift specific to Town10's modern HD aesthetics rather than a class-specific problem.

**Precision-recall profile (Town10): high P (~0.85), moderate R (~0.50)** — the detector recognises what it sees with high confidence but misses about half of distant/occluded actors. This is the desired profile for Sprint 3: high precision means CPM messages will have few false positives (low phantom-braking risk on the CAV side); moderate recall is where V2X cooperative perception adds value (multiple RSUs share complementary detections).

### 6.4 Windows-Specific RAM Cache Failure

First train attempt with `cache='ram'` (22 GB cached frames) hit a `MemoryError` during multiprocessing dataloader worker spawn. Cause: Windows uses spawn (not fork), so each worker receives the parent's state via pickle — the 22 GB cache cannot be serialized across process boundaries with default IPC buffers. Resolved by switching default to `cache=False`. Linux fork would not exhibit this; on Linux, `cache='ram'` would be the right default.

### 6.5 Ultralytics save-dir duplicate-path bug

The `--project=runs/detect` argument, when passed explicitly, caused Ultralytics 8.4.48 to nest results under `runs/detect/runs/detect/<name>/`. Fixed by making `--project` default to `None` and only passing it to `model.train()` / `model.val()` when explicitly overridden, so Ultralytics uses its internal default (single `runs/detect/`).

---

## 7. Architectural Decisions Made (Reasoned)

| Decision | Reason |
|---|---|
| **CARLA-native, not OpenCDA** | OpenCDA's `V2XManager` is idealised (zero latency, perfect channel). We own the entire stack so our latency / PDR / edge-compute models are the experimental contribution rather than add-ons over a sanitised baseline. |
| **Single-camera RSU, not 4-camera** | Forced initially by the CARLA 0.9.16 multi-camera bug; defensible by production-deployment precedent (NYC DOT, FDOT ATSPM use 1–2 cameras per intersection). |
| **YOLO26 instead of YOLOv8** | Edge-first architecture aligns directly with proposal §4.4. NMS-free + DFL-free → cleaner export. ProgLoss + STAL → small-object accuracy for VRU detection. |
| **PyTorch CUDA-12.8 build, not the default torch** | RTX 5080 is Blackwell sm_120; older torch wheels lack the kernels (silent CPU fallback). |
| **4-class detection scheme** | Avoids fragmented small-class distributions on first fine-tune. 5-class subdivision (heavy-vehicle distinction per proposal §2.2) deferred to Sprint 3 when the CPM encoder forces it. |
| **Multi-town training (Town03+04+05), Town10 test** | Single-town training overfit to Town05; cross-town generalisation is the proposal's central scientific claim and required broader train distribution. |
| **`imgsz=1280` for training and eval** | Dataset is 1280×720 native. Downsampling to 640 shrinks distant VRUs below ~15 px, killing the small-object features YOLO26 was chosen for. |
| **Class-balanced spawning** | CARLA's default BP pool is heavily 4-wheeled; without the balanced-pool patch the dataset hit 10:1 vehicle:VRU imbalance, and motorcycle mAP collapsed to 0.11. |
| **Walker-near-intersection spawning** | Random map-wide nav-mesh spawning placed most pedestrians outside RSU coverage; constraining them to 50 m of an intersection ~3x'd pedestrian label count. |
| **Auto-yaw cameras** | Sprint 1's "yaw=0 only" rule was confirmed in Sprint 2 to be specific to the multi-camera bug context. Single-camera cameras can safely point at the intersection centroid. |
| **`cache=False` train default on Windows** | Windows multiprocessing pickles parent state per worker; large RAM cache hits MemoryError. `disk` cache works but adds 30 GB; `False` is the safe Windows default. |
| **Frame-id includes map slug** | Multi-map sweeps writing into the same dataset directory would otherwise collide on `t00_l0_ClearNoon_000`-style IDs. |
| **Deterministic intersection sort** | Without it, intersection IDs reshuffle across CARLA restarts, breaking the train/val split. |

---

## 8. Known Issues and Limitations Carried Forward

| Item | Status | Note |
|---|---|---|
| CARLA 0.9.16 multi-camera bug (≥4 simultaneous) | Confirmed, worked around | Single-camera sequential architecture |
| Occlusion not handled in label generator | Accepted | Distance filter (80 m) limits impact; cross-town eval would catch a serious problem; mAP numbers are healthy |
| Town05-vs-Town10 residual cross-town gap (~0.22) | Accepted | Sim-to-sim domain shift; aligns with proposal §5 |
| RAM cache fails on Windows multiprocessing | Documented, default changed | `disk` cache or `False` work on Windows |
| Multi-RSU simultaneous camera instantiation | Deferred to Sprint 4 | Options: clean CARLA reinstall, Linux Docker, or sequential RSU operation |
| 4-class scheme (no heavy-vehicle distinction) | Deferred | Sprint 3 may force 5-class when CPM encoder needs `car`/`truck`/`bus` separation per ETSI TS 103 324 |

---

## 9. Repository State

```
v2x-sim/
├── .gitignore                          # comprehensive
├── README.md                           # setup + run instructions
├── PROGRESS.md                         # this file
├── pyproject.toml                      # editable install, deps
├── v2xsim/                             # importable package
│   ├── __init__.py
│   ├── carla_utils.py                  # connect + sync-mode + ensure_map
│   ├── intersections.py                # discover_intersections (deterministic sort)
│   └── rsu.py                          # single-camera RSU class
└── scripts/
    ├── 01_smoke_test.py                # ✓ Sprint 1 sanity
    ├── 02_list_intersections.py        # ✓ list signalised intersections per map
    ├── 03_rsu_capture.py               # ✓ single overhead camera
    ├── 12_rsu_video.py                 # ✓ HD video capture
    ├── 13_yolo_test.py                 # ✓ YOLO26 single-frame inference test
    ├── 14_rsu_video_yolo.py            # ✓ RSU video + YOLO detection overlay
    ├── 15_generate_dataset.py          # ✓ multi-map sweep with balanced spawn
    ├── 16_train_yolo.py                # ✓ YOLO26 fine-tune
    ├── 17_eval_town10.py               # ✓ cross-town evaluation
    ├── 18_survey_intersections.py      # ✓ one frame per intersection (camera framing survey)
    └── 19_check_distribution.py        # ✓ dataset class-balance check
```

---

## 10. What's Next — Sprint 3

The detector is production-ready (precision 0.85, recall 0.50 cross-town). Sprint 3 builds the V2X channel and message layer on top of it.

**Modules to build:**

1. **CPM Release 2 encoder/decoder** (proposal §4.2, ETSI TS 103 324 v2.1.1)
   - Detection list → CPM message (station id, generation time, object list with class/pos/vel/confidence)
   - Decoder consumed by the CAV cooperative-perception module
2. **Coll-Perales end-to-end latency model** (proposal §4.3.1, IEEE TVT 2022)
   - `T_e2e(d, load) = T_proc_tx + T_tx + T_prop(d) + T_queue(load) + T_proc_rx`
   - Gaussian jitter; parameters anchored to NR-V2X measurements
3. **Thandavarayan PDR model** (proposal §4.3.2, IEEE TVT 2020)
   - `P_success(d, ρ) = (1 − α·ρ) · exp(−(d/d_ref)^γ)`
   - Per-message Bernoulli outcome; lost CPMs dropped (unacknowledged broadcast)
4. **Edge-compute budget enforcement** (proposal §4.4)
   - Per-RSU inference-time and VRAM caps; aggregate citywide budget
   - Graceful degradation: drop frame or downsample input when over budget

**Architectural choice to make first.** The proposal §4.2 sketches an in-process pub/sub (ZeroMQ / asyncio) for the V2X channel. Before coding, decide:
- ZeroMQ (process-isolated, network-realistic) vs. asyncio (in-process, faster iteration)
- CPM payload format: ETSI ASN.1 (canonical, harder to debug) vs. pydantic/dataclass JSON (debuggable, easy to log)
- Where the channel runs: same process as CARLA, separate process, or service

These will be resolved at the start of Sprint 3.

**Sprint 3 output.** A working pipeline where RSUs detect → encode CPM → channel applies latency + PDR → CAVs receive and decode. Sprint 4 builds the CAV fusion module on top of this.
