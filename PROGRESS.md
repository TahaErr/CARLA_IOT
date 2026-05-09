# V2X-Sim — Progress Report

**Project:** Cooperative Perception at Smart Intersections — A CARLA Study of 5G NR-V2X with ETSI CPM Release 2 under Realistic Edge-Compute and Latency Constraints in Mixed Traffic
**Course:** CMP794 — Final Project
**Authors:** Taha Yasin Er, Doruk Topçu
**Repository:** https://github.com/TahaErr/CARLA_IOT
**Status:** End of Sprint 2, Step 1 (complete) → Sprint 2, Step 2 (code complete, validation pending)

---

## 1. What This Document Covers

This is a detailed snapshot of the project's implementation state. It records what has been built, what design decisions were made (and why), what empirical findings have already shaped the project, and what remains. Each piece of work is anchored back to the original proposal section it implements, so the document doubles as a traceability record.

For the methodological rationale (why the project exists), see the proposal. For how to run anything described here, see `README.md`.

---

## 2. Environment & Stack

| Component | Version | Notes |
|---|---|---|
| OS | Windows 11 | UE4 build path; native CUDA + drivers |
| GPU | NVIDIA RTX 5080 (Blackwell, sm_120) | 16 GB VRAM, idle for visualisation tasks |
| CUDA | 12.8 | Required for sm_120; older runtimes silently fall back to sm_89 |
| Python | 3.10 | CARLA 0.9.16 only ships wheels for 3.10 / 3.11 / 3.12 |
| CARLA | 0.9.16 (UE4 packaged build) | UE5 binary unavailable in this distribution |
| PyTorch | 2.11.0 + cu128 | First stable line with native sm_120 support is 2.7.0; 2.11.0 is the current recommended CUDA-12.8 build for Blackwell |
| Ultralytics | 8.4.44+ | Required for YOLO26 model loader |
| Conda env | `v2xsim` | Editable install of the local `v2xsim` package |

Reasoning behind the non-default choices is captured in §6.

---

## 3. Sprint 1 — RSU Infrastructure

**Goal.** Stand up the smallest possible Roadside Unit (RSU) substrate the rest of the project can grow on: a deterministic, programmatically-discoverable set of signalised intersections, and a working camera mounted to one of them, capturing frames into the project filesystem.

**Proposal mapping.** §4.1 (Architecture: smart intersections instrumented with cameras + Edge-AI compute), §4.5 (Map setup: Town05 train, Town10 cross-town test).

### 3.1 Components Built

| Module | Purpose |
|---|---|
| `v2xsim/carla_utils.py` | `connect()` helper with timeout; `synchronous_mode()` context manager that restores async settings on exit; `ensure_map()` to load a target town |
| `v2xsim/intersections.py` | `discover_intersections()` returning all signalised intersections in the current map. Uses CARLA's `get_group_traffic_lights()` (groups come from OpenDRIVE — no spatial-clustering hyperparameter) |
| `v2xsim/rsu.py` | RSU class wrapping a single overhead camera mounted on a traffic-light pole |
| `scripts/01_smoke_test.py` | Sanity test: connect, spawn a Tesla, attach a chase camera, capture one image |
| `scripts/02_list_intersections.py` | Prints every signalised intersection in a given map with its centroid and number of lights |
| `scripts/03_rsu_capture.py` | Mounts an RSU at a chosen intersection and saves one frame per traffic-light pole |
| `scripts/12_rsu_video.py` | Captures an HD video from the RSU camera while traffic flows through the intersection |

### 3.2 Findings

#### 3.2.1 Town05 has 15 signalised intersections

Discovered via `02_list_intersections.py`. After deterministic sort (see §3.2.3) intersections are stable across CARLA restarts.

#### 3.2.2 Multi-camera limit in CARLA 0.9.16 (Windows packaged build)

A consequential bug. Through systematic bisection (debug scripts since deleted):

| Camera count | Behaviour |
|---|---|
| 1 standalone camera | Works |
| 2–3 cameras attached to one parent | Works |
| 4+ cameras | Crashes the engine |
| 2+ standalone cameras at independent positions | Crashes |
| Cameras attached to `traffic_light` parents | Crashes |
| Buried-mast pattern with offset | Streaming connection refused |

The behaviour is independent of available VRAM (RTX 5080 idle), driver version, and code path. It is a CARLA 0.9.16 Windows build limitation. The only configuration that works reliably is **a single standalone camera** spawned at a fixed offset above a chosen traffic-light pole (`pitch = -25°`, `yaw = 0°`, `FOV = 90°`).

#### 3.2.3 Architectural consequence: single-camera RSU

The proposal originally describes one RSU per intersection with **four cameras** (one per approach). Given the bug, the architecture has been adjusted to **one camera per RSU**, and Sprint 2 Step 2 captures dataset configurations sequentially (one camera at a time, destroyed and re-spawned at each light) rather than in parallel.

**This is defensible, not just a workaround.** Production smart-intersection deployments (NYC DOT TRAVELERS, FDOT ATSPM, several MaaS Global pilots) typically use 1–2 cameras per intersection rather than four; a single overhead camera with a 90° FOV covers most intersection geometries. The proposal §4.1 will need a revision note acknowledging this. Defaulting to single-camera RSUs also removes a confound the original four-camera design would have introduced (per-camera detection fusion at the RSU level, before V2X transmission, which was never the intended contribution).

#### 3.2.4 Deterministic intersection numbering

`discover_intersections()` was updated mid-Sprint 2 to **sort by `(round(center.x, 1), round(center.y, 1))` and reassign sequential IDs**. Without this, intersection IDs reshuffled across CARLA server restarts, which would have broken the train/val split in Sprint 2 Step 2 (the split is driven by `intersection_idx % val_stride`).

---

## 4. Sprint 2, Step 1 — Detection on RSU Frames

**Goal.** Confirm a real object detector runs on RSU frames, characterise its baseline behaviour on synthetic CARLA imagery, and identify what fine-tuning has to fix.

**Proposal mapping.** §4.1 (RSU pipeline: detector → CPM encoder), §4.4 (edge-compute budget tied to detector inference time), §5 (sim-to-real gap as a known limitation).

### 4.1 Migration: YOLOv8 → YOLO26

The original proposal cites YOLOv8-s. After verification of the current ecosystem state (Mar 2026), Sprint 2 was upgraded to **YOLO26** (Ultralytics, released September 2025). Reasons:

1. **Edge-first design.** YOLO26 removes Distribution Focal Loss (DFL) and is natively NMS-free, simplifying export to ONNX/TensorRT/TFLite. This aligns directly with proposal §4.4's "Jetson-class edge platform" framing — YOLO26's whole design target is edge deployment.
2. **Small-object accuracy.** YOLO26 introduces ProgLoss and Small-Target-Aware Label Assignment (STAL), reported by Ultralytics and the Sapkota et al. arXiv paper as substantially improving small-object detection. **This matters for our pedestrian/cyclist (VRU) class** which is the proposal's central safety target.
3. **Drop-in replacement.** Same Ultralytics package, same training API. The only code change required was the model weight string (`yolov8s.pt` → `yolo26s.pt`).
4. **Recency.** A September 2025 release is current at the time of submission and lets the project cite a SOTA detector rather than one that is two release cycles old.

The migration preserves the proposal's claim — the detector is still small (yolo26s, ~19 MB), still COCO-pretrained, still fine-tuned on a Town05-only labelled set (the Sprint 2 Step 2 dataset).

### 4.2 GPU Configuration: RTX 5080 / Blackwell / sm_120

Default `pip install ultralytics` pulls a PyTorch wheel built against an older CUDA runtime that does not include sm_120 kernels. The first run on the RTX 5080 silently fell back to CPU inference at 34 ms/frame.

Resolved by replacing the default torch with the CUDA-12.8 build:

```bat
pip uninstall torch torchvision torchaudio -y
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

After the swap, `torch.cuda.is_available() == True` and `torch.cuda.get_device_name(0) == "NVIDIA GeForce RTX 5080"`. Ultralytics, however, does not auto-place the model on CUDA at load time; this was fixed in `14_rsu_video_yolo.py` by an explicit `model.to("cuda")` call after instantiation and an explicit `device=0` argument on every inference call.

### 4.3 Inference Performance

Measured on Town05 with 80 vehicles in autopilot:

| Resolution | Device | Inference / frame | Wall-clock for 20 s sim |
|---|---|---|---|
| 320×240 | CPU | 34 ms | 19.4 s |
| 320×240 | RTX 5080 | 10 ms | 8.3 s |
| 1280×720 | RTX 5080 | ~10 ms | ~8.5 s |
| 1920×1080 | RTX 5080 | ~17 ms | ~17 s (CARLA-bound, not detector-bound) |

Resolution does not increase YOLO inference time meaningfully because the model resizes input to its `imgsz` (640 by default); only the rendering and the `cv2.VideoWriter` are heavier at higher resolutions.

**Edge-compute consequence.** The baseline 10 ms inference at 320×240 fits comfortably inside both edge profiles defined in proposal §4.4:
- **Orin-class** (20 ms/frame) → 50 % budget utilisation.
- **Xavier-class** (50 ms/frame) → 20 % budget utilisation.
- **Aggregate (15 RSUs × 10 ms = 150 ms)** versus a 10 % share of an L4 onboard system (≈750 ms) → 20 % utilisation.

These are real numbers the simulator can defend in the ablation matrix, not assumed budgets.

### 4.4 Empirical Evidence of Sim-to-Real Domain Shift

A 20 s detection run on Town05 with Full HD frames and the COCO-pretrained yolo26s produced this class distribution:

```
car          509     (correct)
stop sign    364     (correct: visible street signs)
sheep        293     (false positive: 30 km/h speed-limit signs)
truck        231     (mostly correct; some Tesla Cybertruck → "truck")
person       111     (correct: spawned walkers + ambient NPCs)
bus          106     (some correct; fire trucks → "bus")
motorcycle    49     (correct)
cow            3     (false positive)
train          2     (false positive)
elephant       1     (false positive)
```

Visual inspection of frames at t = 2 s and t = 10 s confirmed:
- **Real vehicles are detected** with confidences 0.46–0.94, and the bounding boxes are well-fit.
- **A 30 km/h speed-limit sign is repeatedly classified as "sheep"** with confidence 0.66 — a clean, photogenic example of the sim-to-real gap.

This is **the proposal's own §5 prediction validated empirically**. It is also the empirical justification for why fine-tuning is not optional: with this many false-positive classes, downstream pipeline components (CPM encoder in Sprint 3, CAV fusion module in Sprint 4) would receive untrustworthy detections and any safety metric reported in the ablation matrix would be uninterpretable.

---

## 5. Sprint 2, Step 2 — Sweep Dataset Generator (Code Complete, Validation Pending)

**Goal.** Produce an automatically-labelled Town05 dataset that lets us fine-tune YOLO26 on CARLA imagery, plus a Town10 test set for cross-town generalisation evaluation.

**Proposal mapping.** §4.1 ("fine-tuned on a Town05-only labelled set"), §3 (cross-town generalisation as central claim), §4.6 ("RSU detector precision/recall measured on the held-out Town10 map").

### 5.1 Why Sweep Across Configurations Rather Than Capture from One Point

A single-point dataset would overfit the detector to one viewpoint, one lighting condition, and one geometry; it would fail at any other intersection in Town05 and catastrophically at Town10. The cross-town generalisation claim in the proposal would then be unmeasurable.

Diversity is built across four axes:

| Axis | Values | Diversity captured |
|---|---|---|
| Intersection | All 15 in Town05 (12 train / 3 val) | Geometric variation: 4-way, T-junction, corner |
| Light index | Every traffic-light pole at each intersection | Approach-angle variation (~58 viewpoints total) |
| Weather | ClearNoon, CloudyNoon, WetNoon | Lighting and reflective-surface variation |
| Traffic state | Frames separated by 5 sim ticks | Within-config decorrelation |

### 5.2 Train / Val / Test Split Methodology

```
TRAIN  Town05, intersections with idx % 5 != 0   →  12 intersections, ~1100 frames
VAL    Town05, intersections with idx % 5 == 0   →   3 intersections,  ~280 frames
TEST   Town10 (separate map, not in training)    →  ~200 frames
```

- **Train → Val** measures within-map intersection generalisation. The detector saw 12 intersections; can it cope with 3 unseen ones in the same town?
- **Train → Test** measures cross-domain generalisation. This is the proposal's central scientific claim and the basis for the precision/recall numbers reported in §4.6.

### 5.3 Class Scheme (4-class)

```
0  vehicle      (4-wheel: car / truck / bus combined)
1  motorcycle   (2-wheel + harley/kawasaki/yamaha/vespa keyword)
2  bicycle      (2-wheel + bh/crossbike/diamondback/gazelle keyword)
3  pedestrian   (walker.*)
```

A 5-class subdivision (per proposal §2.2: passenger car / heavy vehicle / motorcycle / pedestrian / cyclist) is left for Sprint 3, when the CPM encoder needs the heavy-vehicle distinction. Starting with four keeps the first fine-tune simple and avoids a fragmented training distribution where some classes have very few samples.

### 5.4 Implementation: `scripts/15_generate_dataset.py`

A single ~600-line script that runs the entire sweep in one CARLA session:

1. **Connect, load map, discover intersections** (deterministic sort).
2. **Spawn persistent global traffic** — 100 vehicles in autopilot across the whole map plus 50 walkers on the navigation mesh with AI controllers, all spawned once at the start. They circulate during every config; no per-config respawn.
3. **For each `(intersection, light, weather)` configuration:**
   a. `world.set_weather(carla.WeatherParameters.<preset>)`.
   b. Spawn one standalone camera at the chosen light pole (single camera at a time → never trips the multi-camera bug).
   c. Warm up 80 sim ticks (4 sim-seconds) so traffic populates the new viewpoint.
   d. Capture N frames, separated by 5 sim ticks each.
   e. For each captured frame: get all `vehicle.*` and `walker.*` actors, project each one's 3D bounding box (`bb.get_world_vertices(actor.get_transform())`) to image space using the camera intrinsic matrix `K` and extrinsic `cam.get_transform().get_inverse_matrix()`, take axis-aligned min/max of the eight projected vertices as the 2D box. Filter out boxes that are behind the camera, off-screen, or too small (< 25 px²), or whose actor is more than 80 m from the camera.
   f. Write the image (`<frame_id>.png`) and YOLO label (`<frame_id>.txt`, normalised `class cx cy w h`).
   g. Optionally write a debug image with ground-truth boxes drawn (`--debug-vis`).
   h. Destroy the camera.
4. **Write `data.yaml`** in the YOLO format pointing at the train/val splits.

**Bounding-box math.** CARLA's camera frame is left-handed (UE4: `x=fwd, y=right, z=up`). Projection swizzles this to OpenCV image coordinates (`x=right, y=down, z=fwd`) before the intrinsic multiplication. The full projection is:

```
p_cam = world_to_cam @ [x_world, y_world, z_world, 1]
(x', y', z') = (p_cam.y, -p_cam.z, p_cam.x)        # axis swizzle
(u, v) = (K @ (x', y', z'))[:2] / z'
```

**Single-camera-at-a-time as design, not workaround.** The destroy-and-respawn pattern means we never have two cameras simultaneously — the multi-camera CARLA bug never fires. The dataset generation is naturally sequential, so this costs us nothing in throughput.

### 5.5 Estimated Wall-Clock

On RTX 5080:

| Stage | Estimate |
|---|---|
| Smoke test (1 intersection × 1 light × 1 weather × 5 frames, with debug visualisation) | ~1 min |
| Town05 full sweep (15 intersections × all lights × 3 weathers × 8 frames ≈ 1400 frames) | ~35–45 min |
| Town10 test set (10 intersections × all lights × 1 weather × 8 frames ≈ 200 frames) | ~5–8 min |

### 5.6 Validation Plan

The script is written but has not yet been run end-to-end. The next action is:

1. Run a smoke test producing 5 frames with `--debug-vis`.
2. Open 2–3 debug PNGs and visually verify the ground-truth bounding boxes are correctly aligned with vehicles and pedestrians.
3. **If correct**, run the full Town05 sweep, then the Town10 test sweep.
4. **If incorrect** (e.g. boxes shifted, rotated, or off by a sign), debug the projection axis swizzle or extrinsic-inverse computation; the smoke test wastes only a minute, the full sweep would waste 45 minutes.

This visual gate is the safest path: the bbox math is mathematically standard but CARLA's left-handed UE4 coordinate convention has caught more than one published codebase.

---

## 6. Architectural Decisions Made (Reasoned)

| Decision | Reason |
|---|---|
| **CARLA-native, not OpenCDA** | OpenCDA's `V2XManager` is idealized (zero latency, perfect channel) — exactly the assumption proposal §5 criticises. We own the entire stack so our latency / PDR / edge-compute models are the experimental contribution rather than add-ons over a sanitised baseline. OpenCDA mainline also only supports CARLA 0.9.11/0.9.12 with Python 3.7. |
| **Single-camera RSU, not 4-camera** | Forced by the CARLA 0.9.16 multi-camera bug; defensible by the production-deployment precedent (NYC DOT, FDOT ATSPM use 1–2 cameras per intersection). |
| **YOLO26 instead of YOLOv8 / YOLO11** | Edge-first architecture aligns directly with proposal §4.4. NMS-free + DFL-free → cleaner export. ProgLoss + STAL → improved small-object accuracy, directly relevant to VRU detection (proposal's central safety target). Sept 2025 release positions the work as current. |
| **PyTorch CUDA-12.8 build, not the default torch** | RTX 5080 is Blackwell sm_120; older torch wheels lack the kernels. Without this, inference silently falls back to CPU (34 ms vs. 10 ms). |
| **4-class detection scheme to start** | Avoids fragmented small-class distributions on first fine-tune. 5-class subdivision can be done in Sprint 3 when the CPM encoder forces the heavy-vehicle distinction. |
| **Held-out intersections for val, Town10 for test** | Train→val measures within-map generalisation; train→test measures cross-domain generalisation (proposal's central claim, §3). |
| **Persistent global traffic, not per-config respawn** | Saves ~5 minutes per sweep. Vehicles in autopilot for the whole sweep produce more natural trajectories than freshly-spawned ones, and avoid spawn-collision retries. |
| **Single camera at a time during sweep** | Works around the multi-camera bug while being the natural sequential order anyway (we sweep configurations one at a time). |
| **Deterministic intersection sort (`x, y` rounded)** | Without this, intersection IDs change across CARLA restarts, breaking reproducibility of the train/val split. |

---

## 7. Known Issues, Risks, and Mitigations

| Item | Status | Mitigation |
|---|---|---|
| CARLA 0.9.16 multi-camera bug (≥4 cameras crash) | Confirmed | Single-camera architecture; sequential sweep |
| sm_120 silent fallback to CPU | Resolved | Explicit CUDA-12.8 PyTorch build |
| Bbox projection math may have axis-sign errors | Untested | Smoke test with `--debug-vis` planned before full sweep |
| Walkers may stop after reaching destination | Accepted | Stopped walkers are still valid training data; redirection loop deferred to Sprint 3 |
| Detector still untrained on CARLA pixels | Expected | Fine-tuning is precisely Sprint 2 Step 2's purpose |
| Sim-to-real gap (sheep, train, elephant FPs) | Identified | Fine-tuning + cross-town eval will quantify it |
| Multi-RSU simultaneous instantiation impossible | Deferred to Sprint 4 | Options: clean CARLA reinstall, sequential RSU instantiation, Linux Docker |

---

## 8. Repository State

```
v2x-sim/
├── .gitignore                          # comprehensive (out/, dataset_*/, *.pt, runs/, ...)
├── README.md                           # setup + run instructions
├── pyproject.toml                      # editable install, deps
├── v2xsim/                             # importable package
│   ├── __init__.py
│   ├── carla_utils.py                  # connect + sync-mode context manager + ensure_map
│   ├── intersections.py                # discover_intersections (deterministic sort)
│   └── rsu.py                          # single-camera RSU class
└── scripts/
    ├── 01_smoke_test.py                # ✓ Sprint 1 sanity
    ├── 02_list_intersections.py        # ✓ Sprint 1 — Town05 = 15 intersections
    ├── 03_rsu_capture.py               # ✓ Sprint 1 — single overhead camera
    ├── 12_rsu_video.py                 # ✓ Sprint 2.1 — HD video capture
    ├── 13_yolo_test.py                 # ✓ Sprint 2.1 — YOLO26 single-frame test
    ├── 14_rsu_video_yolo.py            # ✓ Sprint 2.1 — RSU video + detection overlay
    └── 15_generate_dataset.py          # ✓ Sprint 2.2 code complete, smoke test pending
```

---

## 9. Pending Work

### Immediate (Sprint 2 Step 2 completion)

1. Smoke-test `15_generate_dataset.py` (5 frames, debug visualisation, ~1 min wall-clock).
2. Visually verify ground-truth bounding boxes.
3. Run full Town05 sweep (~45 min).
4. Run Town10 test sweep (~10 min).

### Sprint 2 Step 3 — Fine-tune

5. `scripts/16_train_yolo.py`: load `dataset_town05/data.yaml`, fine-tune `yolo26s.pt` for ~50 epochs (~30–60 min on RTX 5080), output `best.pt`.
6. `scripts/17_eval_town10.py`: evaluate `best.pt` on `dataset_town10` (cross-town), report mAP@50, mAP@50:95, per-class precision/recall.

### Sprint 3 — V2X channel and CPM encoder

7. CPM Release 2 encoder/decoder (proposal §4.2).
8. Coll-Perales latency model (proposal §4.3.1).
9. Thandavarayan PDR model (proposal §4.3.2).
10. Edge-compute budget enforcement (proposal §4.4).

### Sprint 4 — CAV fusion and full pipeline

11. CAV time-aware late-fusion module with confirmation hysteresis (proposal §4.1.1).
12. HDV NHTSA-anchored driver profiles (proposal §4.1.2).
13. VRU stochastic walkers (proposal §4.5).
14. Ablation runner across the four axes in proposal §4.6.

### Documentation

15. Revise proposal §4.1 to acknowledge single-camera RSU architecture.
16. Document the multi-camera bug and the workaround in the final report.
17. Demo video (proposal §7, week 11).

---

## 10. Summary

At end-of-Sprint-2-Step-1 the project has:
- A working, reproducible CARLA + Python environment with GPU acceleration on RTX 5080.
- A deterministic, programmatically-discoverable map of Town05's 15 signalised intersections.
- A working RSU camera that captures Full HD video.
- A working YOLO26 detector running at 10 ms/frame on the GPU.
- Empirical evidence that COCO-pretrained YOLO does not generalise to CARLA imagery without fine-tuning.
- A complete, sweep-aware dataset generator script ready to produce ~1400 train+val frames in Town05 and ~200 test frames in Town10.

The main piece of pending work in Sprint 2 is to actually **run** the dataset generator (after a smoke-test validation pass), then fine-tune. After that, the project moves into Sprint 3 (CPM encoding + V2X channel modelling).
