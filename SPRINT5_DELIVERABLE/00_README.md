# Sprint 5 — Final Ablation Deliverable

Self-contained package of the V2X-Sim cooperative-perception penetration study (CARLA 0.9.16). 144 cells: 3 arms × 4 penetrations × 3 maps × 2 weather × 2 seeds.

## Contents

| Folder | What |
| :--- | :--- |
| `01_settings/` | Every experiment setting explained |
| `02_config/` | Detailed configuration: driver profiles, CAV params, comms, model changes |
| `03_seed0/` | Seed-0 detailed results (md + csv) |
| `04_seed1/` | Seed-1 detailed results (md + csv) |
| `05_combined_eda/` | Combined (both seeds) detailed EDA + per-cell + rollup CSVs |
| `06_aggregated/` | Aggregator `summary.csv` / `summary_by_cell.csv` per arm |
| `07_figures/` | All charts (collisions/map/weather/actions/VRU) per arm |
| `08_reports/` | Final report (.md + .pdf) + ablation plan |
| `09_raw_data/` | Raw per-cell JSON metrics + run logs (source of truth) |

## One-line result
Mean collisions fall from ~22 (all-human baseline) to ~6 at full cooperative penetration — **~73% reduction**, monotonic, on every arm/map. Ordering: Combined ≤ V2I-only ≤ V2V-only.
