# Experiment Settings

| Setting | Value | Meaning |
| :--- | :--- | :--- |
| Communication arms | combined / v2i_only / v2v_only | V2X+V2V · RSU-CPM only (`--no-v2v`) · CAV↔CAV only (`--no-v2x`) |
| Penetration `p` | 0.0, 0.5, 0.9, 1.0 | fraction of vehicles that are CAVs |
| Maps | Town01, Town05, Town10HD_Opt | grid / multi-lane / dense downtown |
| Weather | ClearNoon, HardRainNoon | clear vs heavy-rain preset |
| Seeds | 0 (machine A) + 1 (machine B) | spawn-layout RNG; split across runners |
| Sim duration | 90 s/cell | simulated time per cell |
| dt | 0.05 s (20 Hz) | fixed physics timestep |
| CPM / V2V cadence | 100 ms (10 Hz) | ETSI broadcast rate |
| Vehicles | 60 | spawned vehicles per cell |
| Walkers | 60 | spawned pedestrians per cell |
| HDV mix | HOSTILE_MIX (50% attentive / 20% distracted / 30% aggressive_hostile) | human-driver population |
| CAV profile | AI_REALISTIC | cooperative AV |
| Total cells | 144 | 24/arm/seed × 2 seeds × 3 arms |

At `p = 0.0` the fleet is 100% HDV, so **no V2X or V2V is used or considered** — that column is the shared human baseline (identical across arms up to CARLA nondeterminism).

## Run command (per machine)

```
python scripts/run_full_ablation.py --seeds <0|1> \
    --detector runs/detect/runs/detect/yolo26s_carla_multi-2/weights/best.pt \
    --carla-exe "<path>/CarlaUE4.exe"
```
