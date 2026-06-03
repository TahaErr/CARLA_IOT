# Sprint 5 — Final Ablation Plan (2-runner split)

The cooperative-perception penetration study, run after the v2 realism model +
braking/steer fixes. Two machines split the seeds and each run **one command**.

## Experiment matrix (identical on both machines — do not change)

| Dimension | Value |
| :--- | :--- |
| Communication arms | **combined** (V2X+V2V) · **v2i_only** (`--no-v2v`) · **v2v_only** (`--no-v2x`) |
| Penetration `p` | 0.0, 0.5, 0.9, 1.0 |
| Maps | Town01 (grid), Town05 (multi-lane), Town10HD_Opt (dense downtown) |
| Weather | ClearNoon, HardRainNoon |
| Sim duration | **90 s** per cell @ dt 0.05 (20 Hz) |
| CPM / V2V cadence | 100 ms (10 Hz) |
| Population | 60 vehicles + 60 walkers |
| HDV behaviour | HOSTILE_MIX (v2 model): attentive keep avoidance; distracted + aggressive_hostile avoidance OFF |
| CAV behaviour | AI_REALISTIC, TM avoidance ON, 7 m follow gap, closing-rate brake gate, steer-preserving overrides |

**Seed split:** Doruk = `0` · Taha = `1` → 2 seeds total.

Per machine: 3 maps × 2 weather × 1 seed × 4 pen = **24 cells/arm × 3 arms = 72 cells**.
Combined across both machines: **144 cells**.

## Prerequisites (each machine)

1. Conda env `v2xsim` (the repo's interpreter). All commands below use it.
2. The detector weights at `runs/detect/runs/detect/yolo26s_carla_multi-2/weights/best.pt`.
3. **CARLA running first**, Epic quality (pedestrians don't spawn at Low):
   ```
   CarlaUE4.exe -quality-level=Epic
   ```
4. Run from the repo root: `PythonAPI/v2x-sim`.

## The command

**Doruk (seed 0):**
```
python scripts/run_full_ablation.py --seeds 0 ^
    --detector runs/detect/runs/detect/yolo26s_carla_multi-2/weights/best.pt ^
    --carla-exe "C:/Users/Doruk-Topcu/Desktop/CARLA_0.9.16/CarlaUE4.exe"
```

**Taha (seed 1):**
```
python scripts/run_full_ablation.py --seeds 1 ^
    --detector runs/detect/runs/detect/yolo26s_carla_multi-2/weights/best.pt ^
    --carla-exe "C:/<taha-path>/CARLA_0.9.16/CarlaUE4.exe"
```

(Replace `--carla-exe` with each machine's real path. Add `--dry-run` first to print
the commands without running. `--python C:/.../envs/v2xsim/python.exe` if `python`
isn't already the v2xsim interpreter.)

The orchestrator runs the three arms **sequentially** into:
```
out/ablation_sprint5_final/
    combined/    *.json + logs/
    v2i_only/    *.json + logs/
    v2v_only/    *.json + logs/
```

### Robustness (already built in)
- `--cell-retries 2`: a cell that hits a transient CARLA crash is retried up to twice.
- `--carla-exe` watchdog: if the server dies during an overnight run, it's relaunched.
- `--skip-existing`: safe to Ctrl-C and re-run the same command — it resumes.

## After both machines finish — merge + aggregate

Cell filenames carry `sNN`, so the two result sets have **no collisions**. Copy Taha's
three arm folders into the same `out/ablation_sprint5_final/<arm>/` (next to Doruk's),
then aggregate each arm:
```
python scripts/41_ablation_aggregate.py --in-dir out/ablation_sprint5_final/combined
python scripts/41_ablation_aggregate.py --in-dir out/ablation_sprint5_final/v2i_only
python scripts/41_ablation_aggregate.py --in-dir out/ablation_sprint5_final/v2v_only
```
Each writes a `summary.csv` (mean ± sd over the 2 seeds). Report generation comes after.

> Note: `out/` is gitignored — only the **scripts/config** go to GitHub. Each runner
> produces data locally; share the JSON folders directly (zip/drive) to merge.

## Rough time estimate
~110–130 s wall per cell on average (Town10 high-penetration cells are the slow ones,
the steer fix keeps them lighter than before). For 72 cells/machine, **≈ 2.5–3.5 hours
per machine**.
