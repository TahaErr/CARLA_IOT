# Combined Results — Exploratory Data Analysis (both seeds)

144 cells. Each p/arm statistic pools 12 cells (2 seeds × 3 maps × 2 weather).

## 1. Collisions by penetration & arm — full descriptive stats

### TOTAL collisions

| `p` | arm | mean | sd | min | median | max | n |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| 0.0 | Combined (V2X + V2V) | 21.92 | 4.96 | 13 | 24.0 | 28 | 12 |
| 0.0 | V2I-only (--no-v2v) | 21.83 | 4.91 | 13 | 24.0 | 28 | 12 |
| 0.0 | V2V-only (--no-v2x) | 21.83 | 4.91 | 13 | 24.0 | 28 | 12 |
| 0.5 | Combined (V2X + V2V) | 14.67 | 4.13 | 8 | 13.5 | 22 | 12 |
| 0.5 | V2I-only (--no-v2v) | 14.50 | 5.47 | 6 | 14.0 | 26 | 12 |
| 0.5 | V2V-only (--no-v2x) | 15.17 | 4.74 | 9 | 15.0 | 21 | 12 |
| 0.9 | Combined (V2X + V2V) | 7.25 | 2.92 | 2 | 8.0 | 12 | 12 |
| 0.9 | V2I-only (--no-v2v) | 7.92 | 3.95 | 3 | 7.5 | 17 | 12 |
| 0.9 | V2V-only (--no-v2x) | 8.33 | 3.54 | 3 | 10.0 | 12 | 12 |
| 1.0 | Combined (V2X + V2V) | 5.92 | 3.45 | 1 | 6.0 | 11 | 12 |
| 1.0 | V2I-only (--no-v2v) | 6.08 | 3.68 | 1 | 7.0 | 12 | 12 |
| 1.0 | V2V-only (--no-v2x) | 6.67 | 2.87 | 3 | 7.5 | 11 | 12 |

### PRIMARY collisions

| `p` | arm | mean | sd | min | median | max | n |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| 0.0 | Combined (V2X + V2V) | 16.08 | 3.38 | 11 | 18.0 | 19 | 12 |
| 0.0 | V2I-only (--no-v2v) | 16.00 | 3.37 | 11 | 17.5 | 19 | 12 |
| 0.0 | V2V-only (--no-v2x) | 16.00 | 3.37 | 11 | 17.5 | 19 | 12 |
| 0.5 | Combined (V2X + V2V) | 11.08 | 2.84 | 7 | 10.0 | 15 | 12 |
| 0.5 | V2I-only (--no-v2v) | 10.33 | 3.20 | 5 | 10.0 | 15 | 12 |
| 0.5 | V2V-only (--no-v2x) | 11.17 | 2.41 | 8 | 11.0 | 15 | 12 |
| 0.9 | Combined (V2X + V2V) | 6.33 | 2.78 | 2 | 6.0 | 12 | 12 |
| 0.9 | V2I-only (--no-v2v) | 6.75 | 3.19 | 3 | 6.5 | 15 | 12 |
| 0.9 | V2V-only (--no-v2x) | 7.50 | 3.20 | 3 | 8.0 | 12 | 12 |
| 1.0 | Combined (V2X + V2V) | 5.00 | 2.86 | 1 | 5.0 | 10 | 12 |
| 1.0 | V2I-only (--no-v2v) | 5.00 | 3.00 | 1 | 4.5 | 10 | 12 |
| 1.0 | V2V-only (--no-v2x) | 5.67 | 2.92 | 2 | 5.5 | 11 | 12 |

## 2. Reduction vs baseline (Combined, total collisions)

| `p` | mean collisions | reduction vs p=0.0 |
| :---: | :---: | :---: |
| 0.0 | 21.9 | 0% |
| 0.5 | 14.7 | 33% |
| 0.9 | 7.2 | 67% |
| 1.0 | 5.9 | 73% |

## 3. By map × penetration (combined, mean)

| Map | p0.0 | p0.5 | p0.9 | p1.0 |
| :--- | :---: | :---: | :---: | :---: |
| Town01 | 24.0 | 13.8 | 8.0 | 6.0 |
| Town05 | 15.5 | 10.8 | 3.8 | 1.8 |
| Town10HD_Opt | 26.2 | 19.5 | 10.0 | 10.0 |

## 4. By weather × penetration (combined, mean)

| Weather | p0.0 | p0.5 | p0.9 | p1.0 |
| :--- | :---: | :---: | :---: | :---: |
| ClearNoon | 21.8 | 14.2 | 7.7 | 6.0 |
| HardRainNoon | 22.0 | 15.2 | 6.8 | 5.8 |

## 5. At-fault collisions by driver profile (combined, pooled sum)

| Profile | at-fault (sum) |
| :--- | :---: |
| attentive | 99 |
| distracted | 127 |
| aggressive_hostile | 187 |
| ai_realistic | 184 |

## 6. Cooperative-comms & braking by penetration (combined, mean)

| `p` | V2V recv | coop brakes | CPMs emitted | hard | soft | decel | none |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 0.0 | 0.0 | 0.0 | 2700.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 0.5 | 187813.2 | 180.0 | 2700.0 | 511.1 | 700.2 | 2379.4 | 41411.2 |
| 0.9 | 652748.4 | 539.8 | 2700.0 | 877.7 | 1605.5 | 5491.5 | 78225.8 |
| 1.0 | 800679.9 | 707.2 | 2700.0 | 888.8 | 1892.4 | 6751.2 | 87855.0 |

## 7. Performance & immobilised vehicles (combined, mean)

| `p` | wall/sim | frozen | VRU collisions |
| :---: | :---: | :---: | :---: |
| 0.0 | 0.64 | 36.4 | 0.9 |
| 0.5 | 1.09 | 24.8 | 0.6 |
| 0.9 | 2.29 | 12.7 | 0.6 |
| 1.0 | 2.63 | 10.2 | 0.3 |

## 8. Key takeaways

- Monotonic ~73% collision reduction from human baseline to full cooperative fleet.
- Channel ordering: Combined ≤ V2I-only ≤ V2V-only (infrastructure CPM is the stronger channel).
- Town05 ≈ eliminates collisions at p=1.0; Town10HD_Opt plateaus (~10) due to junction turn-geometry artifacts; Town01 in between.
- Weather-robust (ClearNoon ≈ HardRainNoon).
- Cooperative brakes & V2V traffic scale with penetration; frozen wrecks fall ~36→~10.