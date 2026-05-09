# V2X-Sim — Cooperative Perception at Smart Intersections

Code scaffold for the CMP794 final project (Taha Yasin ER & Doruk TOPÇU).

This is the **Sprint 1** deliverable: environment smoke test + Town05 RSU
skeleton. No detector, no V2X channel model, no fusion module yet — those come
in subsequent sprints.

## Setup (Windows + conda)

CARLA 0.9.16 ships official wheels only for Python 3.10 / 3.11 / 3.12.
We use 3.10.

```bat
:: 1) create env
conda create -n v2xsim python=3.10 -y
conda activate v2xsim

:: 2) install package + deps in editable mode
pip install -e .
```

Sanity check:
```bat
python -c "import carla; print('carla', carla.__version__)"
```

## Run

In one terminal, start the CARLA server (UE5 build for 0.9.16):
```bat
cd C:\path\to\CARLA_0.9.16
.\CarlaUE5.exe -quality-level=Low
```
(If your build is the UE4 variant, use `CarlaUE4.exe` instead. The quality
flag is just to keep GPU load low while we develop.)

In another terminal, with `v2xsim` env active:

```bat
:: A2 — smoke test (writes out\smoke_test.png)
python scripts\01_smoke_test.py

:: B1 — list signalized intersections in Town05 (sanity check before B3)
python scripts\02_list_intersections.py --map Town05

:: B3 — mount one RSU on intersection 0, save one frame per camera
python scripts\03_rsu_capture.py --map Town05 --intersection 0
```

## Verify checklist

- [ ] **A2** `out\smoke_test.png` is a non-black image taken from a chase
      camera behind a Tesla Model 3 driving in autopilot.
- [ ] **B1** `02_list_intersections.py` prints **N > 0** entries for Town05.
      (Town05 has many signalized intersections; expect ~10+.)
- [ ] **B3** `out\rsu00_cam*.png` contains one image per traffic-light pole
      at intersection 0, each looking inward toward the intersection center.

If any of these fail, the failure mode is informative — see Troubleshooting.

## Layout

```
v2x-sim/
├── pyproject.toml              # editable install, deps
├── README.md                   # this file
├── .gitignore
├── v2xsim/                     # importable package
│   ├── __init__.py
│   ├── carla_utils.py          # connect helper + sync-mode context manager
│   ├── intersections.py        # discover signalized intersections
│   └── rsu.py                  # RSU class (cameras at light poles)
└── scripts/                    # runnable entry points
    ├── 01_smoke_test.py
    ├── 02_list_intersections.py
    └── 03_rsu_capture.py
```

## Troubleshooting

- **`pip install carla==0.9.16` fails:** confirm the env is Python 3.10 with
  `python --version`. CARLA 0.9.16 has no 3.9 wheel.
- **`RuntimeError: time-out of 20000ms` on connect:** the CARLA server isn't
  running, or it's bound to a different port. Default is 2000.
- **Server stuck after a failed run:** the synchronous-mode context manager
  restores async settings on exit, but if you killed the script with Ctrl+C
  during `world.tick()` the server may still be in sync mode. Restart
  `CarlaUE5.exe` to recover.
- **`No spawn points in current map`:** the server hasn't loaded a map yet.
  The smoke test uses whatever the server has loaded; load Town05 manually
  in the server config or pass `--map Town05` to script 03.

## Next sprints (not in this commit)

- Sprint 2: YOLOv8-s integration on RSU frames; detection IoU vs. CARLA
  ground truth on a held-out Town10 set.
- Sprint 3: CPM Release 2 encoder/decoder + Coll-Perales latency model
  + Thandavarayan PDR model + edge-compute budget gate.
- Sprint 4: CAV time-aware late-fusion module + confirmation hysteresis;
  HDV profile system; VRU stochastic walkers; full ablation runner.
