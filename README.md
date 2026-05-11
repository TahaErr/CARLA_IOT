# V2X-Sim — Cooperative Perception at Smart Intersections

Code for the CMP794 final project (Taha Yasin Er & Doruk Topçu).

**Current status:** Sprint 2 complete — detector fine-tuned and cross-town evaluated. Ready for Sprint 3 (CPM encoder + V2X channel). See `PROGRESS.md` for the full state.

---

## Setup (Windows + conda)

CARLA 0.9.16 ships official wheels only for Python 3.10 / 3.11 / 3.12; this project uses 3.10.

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
```

Sanity check:
```bat
python -c "import carla; print('carla', carla.__version__)"
python -c "import torch; print('cuda available:', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
```

---

## Start the CARLA server

In one terminal:
```bat
cd C:\path\to\CARLA_0.9.16
.\CarlaUE5.exe -quality-level=Low
:: or for UE4 builds: .\CarlaUE4.exe -quality-level=Low
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

The full pipeline produces a YOLO26 model fine-tuned on Town03 + Town04 + Town05, evaluated on Town10 as a held-out test set.

### 1. Survey intersection camera framing (optional)

Captures one frame per intersection with auto-yaw pointing at the intersection centroid:

```bat
python scripts\18_survey_intersections.py --map Town05
```

Open `out/intersection_survey/*.png` and visually verify each camera frames the intersection sensibly.

### 2. Generate training datasets (Town03 + Town04 + Town05)

Each sweep takes 30–45 min on RTX 5080. All three sweeps write into the same output directory; the patched frame-id scheme (`Town03_t00_l0_ClearNoon_000`) prevents collisions.

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

Imbalance should be < 4x for every class. Targets we hit:
- vehicle 1.0x, motorcycle 1.5x, bicycle 2.6x, pedestrian 1.2x

### 4. Generate the held-out Town10 test set

`--val-stride 1` puts every frame in the val split (the script treats Town10 as a pure evaluation set).

```bat
python scripts\15_generate_dataset.py --map Town10HD_Opt --out .\dataset_town10_v2 ^
  --weathers ClearNoon,CloudyNoon,WetNoon,ClearSunset,CloudySunset,HardRainNoon,SoftRainNoon ^
  --frames-per-config 12 --val-stride 1

python scripts\19_check_distribution.py .\dataset_town10_v2
```

### 5. Fine-tune YOLO26s

```bat
python scripts\16_train_yolo.py --data .\dataset_multi\data.yaml ^
  --name yolo26s_carla_multi
```

Defaults: `imgsz=1280, batch=8, epochs=50, patience=20, cache=False` (Windows-safe). Takes ~2–3 hours on RTX 5080.

Output: `runs/detect/yolo26s_carla_multi/weights/best.pt`. The script prints the final save path.

### 6. Cross-town evaluation

```bat
python scripts\17_eval_town10.py ^
  --weights runs/detect/yolo26s_carla_multi/weights/best.pt ^
  --data .\dataset_town10_v2\data.yaml
```

Expected metrics (multi-town strategy, Town10 cross-town):
- mAP@50 ≈ 0.53, mAP@50:95 ≈ 0.37
- precision ≈ 0.85, recall ≈ 0.50

PR curves and confusion matrix are saved under `runs/detect/yolo26s_carla_town10_eval/`.

---

## Project layout

```
v2x-sim/
├── pyproject.toml
├── README.md                           # this file
├── PROGRESS.md                         # detailed implementation notes
├── .gitignore
├── v2xsim/                             # importable package
│   ├── __init__.py
│   ├── carla_utils.py                  # connect + sync mode + ensure_map
│   ├── intersections.py                # discover_intersections (deterministic sort)
│   └── rsu.py                          # single-camera RSU class
└── scripts/
    ├── 01_smoke_test.py
    ├── 02_list_intersections.py
    ├── 03_rsu_capture.py
    ├── 12_rsu_video.py
    ├── 13_yolo_test.py                 # YOLO26 single-frame test
    ├── 14_rsu_video_yolo.py            # video + detection overlay
    ├── 15_generate_dataset.py          # dataset sweep (multi-map)
    ├── 16_train_yolo.py                # YOLO26 fine-tune
    ├── 17_eval_town10.py               # cross-town evaluation
    ├── 18_survey_intersections.py      # one frame per intersection
    └── 19_check_distribution.py        # class-balance check
```

---

## Troubleshooting

- **`pip install carla==0.9.16` fails:** confirm the env is Python 3.10 (CARLA 0.9.16 has no 3.9 wheel).
- **`RuntimeError: time-out of 20000ms` on connect:** the CARLA server isn't running, or it's on a different port. Default is 2000. Sometimes a previous crashed run leaves the server in sync mode — restart `CarlaUE*.exe`.
- **`Map 'Town10' not found`:** the CARLA packaged build names this map `Town10HD_Opt`. Use that as the `--map` argument.
- **CPU inference instead of GPU (~30 ms/frame):** the default torch wheel lacks Blackwell sm_120 kernels. Reinstall with the CUDA-12.8 build (see Setup).
- **`MemoryError` during train caching:** Windows multiprocessing cannot pickle a 22 GB RAM cache across worker processes. Use `--cache disk` or `--cache False` (already the default).
- **Train output ends up in `runs/detect/runs/detect/<name>`:** older versions of the scripts passed `--project=runs/detect` explicitly, which Ultralytics duplicated. The current scripts let Ultralytics use its own default; verify the train script log's `weights at:` line for the actual location.

---

## Next sprints (not yet implemented)

- **Sprint 3:** CPM Release 2 encoder/decoder; Coll-Perales latency model; Thandavarayan PDR model; edge-compute budget enforcement.
- **Sprint 4:** CAV time-aware late-fusion module with confirmation hysteresis; HDV NHTSA-anchored driver profiles; VRU stochastic walkers; full ablation runner.

See `PROGRESS.md` §10 for the Sprint 3 plan.
