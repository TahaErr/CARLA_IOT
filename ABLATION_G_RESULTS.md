# Configuration G - Full Ablation Results

**V2X-Sim cooperative-perception study - CARLA 0.9.16**  
Three-arm V2X / V2I / V2V penetration sweep. Generated directly from the per-cell JSON metrics in `out/ablation_G/{combined,v2i_only,v2v_only}`.

> **Status caveat - read first.** This run completed **70 / 72** cells and the cooperative communication stack is mechanically live, but the **safety result is inverted and flat**: collisions *rise* when connected vehicles are introduced and the three arms are statistically indistinguishable. The cause is a braking-logic regression introduced with the green-light deadlock fix (see Findings). Treat these numbers as a **pre-fix baseline, not a V2X-effectiveness result.**

---

## Where Configuration G sits among the sweep options

| Configuration | Sim Duration | Sweep Arms (V2V/V2X) | Penetration $p$ | Seeds | Weathers | Total Runs | Est. Wall Time |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: |
| A. "Full + Full" | 120 s | Combined / V2I-only / V2V-only | `0.0, 0.5, 0.9, 1.0` | `0,1,2,3,4` | `ClearNoon, ClearSunset, HardRainNoon` | 540 | ~43.5 h |
| B. "Compromise" | 120 s | Same | `0.0, 0.5, 0.9, 1.0` | `0,1,2` | `ClearNoon` | 108 | ~8.7 h |
| C. "Fast Multi-Seed" | 30 s | Same | `0.0, 0.5, 0.9, 1.0` | `0,1,2` | `ClearNoon` | 108 | ~1.7 h |
| D. "Minimal Trend" | 120 s | Same | `0.0, 0.5, 0.9, 1.0` | `0` | `ClearNoon` | 36 | ~2.9 h |
| E. "Smoke/Ultralight" | 30 s | Same | `0.0, 0.5, 0.9, 1.0` | `0` | `ClearNoon` | 36 | ~33 min |
| **G. "Weather & Map Focus"** | **60 s** | **Same** | **`0.0, 0.5, 0.9, 1.0`** | **`0`** | **`ClearNoon, HardRainNoon`** | **72** | **~2.3 h** |

---

## 1. Experimental design

| Dimension | Values |
| :--- | :--- |
| Communication arms | Combined (V2X+V2V) / V2I-only (`--no-v2v`) / V2V-only (`--no-v2x`) |
| Penetration $p$ | 0.0, 0.5, 0.9, 1.0 (fraction of vehicles that are CAVs) |
| Maps | Town01 (grid), Town05 (multi-lane), Town10HD_Opt (dense downtown) |
| Weather | ClearNoon, HardRainNoon |
| Seeds | 0 (single seed) |
| Sim duration | 60 s/cell @ dt 0.05 (20 Hz physics) |
| Population | 60 vehicles + 60 walkers |
| HDV behaviour | HOSTILE_MIX: 50% attentive, 20% distracted (20% ignore-veh), 30% aggressive-hostile (40% ignore-veh) |
| CAV behaviour | AI_REALISTIC: 3.0 m lead gap, ~1% rule slips, TM avoidance ON |
| RSU CPM / V2V cadence | 10 Hz (100 ms) |
| Cells per arm / total | 24 (3 maps x 2 weather x 4 pen) / 72 planned |

At `p = 0.0` there are no CAVs, so that cell is the shared **no-V2X / no-V2V human baseline** in every arm. The two missing `v2i_only` cells (Town01 `p0.0` ClearNoon and `p0.9` HardRainNoon) crashed at spawn with empty logs and are excluded from that arm.

Cells actually completed: **combined 24/24, v2i_only 22/24, v2v_only 24/24.**

---

## 2. Headline - total collisions by penetration & arm

Mean collision incidents per cell, averaged over 3 maps x 2 weather. Lower is better; a working stack should *fall* as $p$ rises and *differ* between arms.

| $p$ | Combined | V2I-only | V2V-only |
| :---: | :---: | :---: | :---: |
| 0.0 | 6.2 | 5.4 | 5.8 |
| 0.5 | 10.8 | 9.7 | 9.5 |
| 0.9 | 8.7 | 10.0 | 9.8 |
| 1.0 | 10.3 | 9.3 | 9.7 |

**Collisions roughly double from baseline (p=0.0) to any connected condition, then plateau. The three arms are within noise at every penetration.**

### Who is crashing (Combined arm)

| $p$ | CAV collisions | HDV collisions | VRU (pedestrian) |
| :---: | :---: | :---: | :---: |
| 0.0 | 0.0 | 6.2 | 0.7 |
| 0.5 | 9.0 | 1.8 | 0.8 |
| 0.9 | 8.7 | 0.0 | 0.2 |
| 1.0 | 10.3 | 0.0 | 0.0 |

As $p$ rises the human crashes vanish (fewer HDVs) and are **more than replaced** by CAV crashes.

---

## 3. Full per-cell results (every town x weather x penetration)

Columns: **coll**=total collisions; **cav/hdv/vru**=collisions by party; **frozen**=vehicles immobilised after a crash; **coop**=cooperative (V2V) brakes; **phantom**=phantom brakes suppressed; **dec/soft/hard**=Python brake actions; **v2v_recv**=V2V messages received; **cpm_emit**=CPMs emitted; **ratio**=wall/sim; **wall**=wall seconds; **status**.

### 3.1 Combined (V2X + V2V)

| Town | Weather | $p$ | coll | cav | hdv | vru | frozen | coop | phantom | dec | soft | hard | v2v_recv | cpm_emit | ratio | wall(s) | status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Town01 | ClearNoon | 0.0 | **5** | 0 | 5 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0.57 | 34.4 | ok |
| Town01 | ClearNoon | 0.5 | **7** | 6 | 1 | 0 | 13 | 0 | 10 | 3092 | 4500 | 156 | 81389 | 1800 | 0.83 | 49.8 | ok |
| Town01 | ClearNoon | 0.9 | **8** | 8 | 0 | 1 | 12 | 43 | 30 | 6380 | 12834 | 146 | 277510 | 1800 | 1.31 | 78.3 | ok |
| Town01 | ClearNoon | 1.0 | **12** | 12 | 0 | 0 | 20 | 48 | 14 | 5896 | 10825 | 230 | 298574 | 1800 | 1.32 | 79.2 | ok |
| Town01 | HardRainNoon | 0.0 | **3** | 0 | 3 | 0 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0.6 | 35.8 | ok |
| Town01 | HardRainNoon | 0.5 | **9** | 7 | 2 | 0 | 16 | 35 | 14 | 3326 | 4881 | 403 | 84961 | 1800 | 0.8 | 47.9 | ok |
| Town01 | HardRainNoon | 0.9 | **7** | 7 | 0 | 0 | 14 | 10 | 18 | 5401 | 14904 | 208 | 254549 | 1800 | 1.28 | 76.9 | ok |
| Town01 | HardRainNoon | 1.0 | **9** | 9 | 0 | 0 | 14 | 2 | 19 | 5643 | 13189 | 296 | 310161 | 1800 | 1.47 | 88.1 | ok |
| Town05 | ClearNoon | 0.0 | **6** | 0 | 6 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0.64 | 38.1 | ok |
| Town05 | ClearNoon | 0.5 | **4** | 4 | 0 | 0 | 6 | 0 | 4 | 1752 | 1854 | 16 | 126568 | 1800 | 0.99 | 59.5 | ok |
| Town05 | ClearNoon | 0.9 | **7** | 7 | 0 | 0 | 11 | 0 | 17 | 3009 | 4126 | 1231 | 446118 | 1800 | 2.04 | 122.2 | ok |
| Town05 | ClearNoon | 1.0 | **8** | 8 | 0 | 0 | 11 | 14 | 16 | 3864 | 4640 | 65 | 541772 | 1800 | 2.63 | 158.1 | ok |
| Town05 | HardRainNoon | 0.0 | **4** | 0 | 4 | 0 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0.63 | 37.7 | ok |
| Town05 | HardRainNoon | 0.5 | **8** | 6 | 2 | 0 | 14 | 30 | 4 | 1706 | 3644 | 568 | 137440 | 1800 | 1.03 | 61.9 | ok |
| Town05 | HardRainNoon | 0.9 | **8** | 8 | 0 | 0 | 14 | 1 | 20 | 3426 | 5266 | 1031 | 440258 | 1800 | 1.95 | 117.0 | ok |
| Town05 | HardRainNoon | 1.0 | **8** | 8 | 0 | 0 | 13 | 50 | 25 | 4645 | 4555 | 453 | 556857 | 1800 | 2.6 | 156.2 | ok |
| Town10HD_Opt | ClearNoon | 0.0 | **7** | 0 | 7 | 1 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0.77 | 45.9 | ok |
| Town10HD_Opt | ClearNoon | 0.5 | **16** | 13 | 3 | 3 | 26 | 0 | 10 | 3227 | 4913 | 616 | 134585 | 1800 | 1.6 | 95.8 | ok |
| Town10HD_Opt | ClearNoon | 0.9 | **12** | 12 | 0 | 0 | 20 | 35 | 18 | 8881 | 13064 | 655 | 505555 | 1800 | 3.65 | 219.0 | ok |
| Town10HD_Opt | ClearNoon | 1.0 | **12** | 12 | 0 | 0 | 19 | 111 | 16 | 8580 | 20148 | 656 | 646414 | 1800 | 4.56 | 273.6 | ok |
| Town10HD_Opt | HardRainNoon | 0.0 | **12** | 0 | 12 | 3 | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0.91 | 54.8 | ok |
| Town10HD_Opt | HardRainNoon | 0.5 | **21** | 18 | 3 | 2 | 32 | 0 | 5 | 3463 | 4743 | 830 | 103564 | 1800 | 1.17 | 70.3 | ok |
| Town10HD_Opt | HardRainNoon | 0.9 | **10** | 10 | 0 | 0 | 18 | 111 | 18 | 6957 | 19090 | 1594 | 574628 | 1800 | 4.26 | 255.6 | ok |
| Town10HD_Opt | HardRainNoon | 1.0 | **13** | 13 | 0 | 0 | 23 | 163 | 15 | 8815 | 15166 | 1821 | 640567 | 1800 | 4.3 | 258.2 | ok |

### 3.2 V2I-only (--no-v2v)

| Town | Weather | $p$ | coll | cav | hdv | vru | frozen | coop | phantom | dec | soft | hard | v2v_recv | cpm_emit | ratio | wall(s) | status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Town01 | ClearNoon | 0.0 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | *missing* |
| Town01 | ClearNoon | 0.5 | **7** | 5 | 2 | 0 | 13 | 0 | 11 | 3015 | 3605 | 139 | 0 | 1800 | 0.62 | 37.0 | ok |
| Town01 | ClearNoon | 0.9 | **7** | 7 | 0 | 0 | 11 | 0 | 12 | 5434 | 16660 | 246 | 0 | 1800 | 0.67 | 40.1 | ok |
| Town01 | ClearNoon | 1.0 | **6** | 6 | 0 | 0 | 9 | 0 | 2 | 5434 | 15902 | 250 | 0 | 1800 | 0.69 | 41.2 | ok |
| Town01 | HardRainNoon | 0.0 | **6** | 0 | 6 | 0 | 10 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0.54 | 32.5 | ok |
| Town01 | HardRainNoon | 0.5 | **11** | 9 | 2 | 0 | 18 | 0 | 2 | 2880 | 3542 | 204 | 0 | 1800 | 0.59 | 35.5 | ok |
| Town01 | HardRainNoon | 0.9 | - | - | - | - | - | - | - | - | - | - | - | - | - | - | *missing* |
| Town01 | HardRainNoon | 1.0 | **7** | 7 | 0 | 0 | 11 | 0 | 7 | 6072 | 18607 | 261 | 0 | 1800 | 0.7 | 41.9 | ok |
| Town05 | ClearNoon | 0.0 | **2** | 0 | 2 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0.6 | 36.0 | ok |
| Town05 | ClearNoon | 0.5 | **8** | 8 | 0 | 1 | 12 | 0 | 0 | 2004 | 3567 | 36 | 0 | 1800 | 0.72 | 43.0 | ok |
| Town05 | ClearNoon | 0.9 | **8** | 8 | 0 | 1 | 12 | 0 | 0 | 3954 | 4486 | 582 | 0 | 1800 | 0.86 | 51.4 | ok |
| Town05 | ClearNoon | 1.0 | **6** | 6 | 0 | 0 | 8 | 0 | 0 | 3881 | 7206 | 2577 | 0 | 1800 | 0.87 | 52.4 | ok |
| Town05 | HardRainNoon | 0.0 | **1** | 0 | 1 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0.63 | 37.9 | ok |
| Town05 | HardRainNoon | 0.5 | **6** | 5 | 1 | 0 | 10 | 0 | 0 | 2820 | 2004 | 789 | 0 | 1800 | 0.74 | 44.2 | ok |
| Town05 | HardRainNoon | 0.9 | **6** | 6 | 0 | 0 | 8 | 0 | 6 | 3597 | 2631 | 1728 | 0 | 1800 | 0.86 | 51.8 | ok |
| Town05 | HardRainNoon | 1.0 | **8** | 8 | 0 | 0 | 13 | 0 | 2 | 3688 | 7858 | 1385 | 0 | 1800 | 0.92 | 55.0 | ok |
| Town10HD_Opt | ClearNoon | 0.0 | **11** | 0 | 11 | 3 | 19 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0.8 | 48.3 | ok |
| Town10HD_Opt | ClearNoon | 0.5 | **16** | 13 | 3 | 0 | 26 | 0 | 3 | 2857 | 6981 | 1933 | 0 | 1800 | 0.84 | 50.1 | ok |
| Town10HD_Opt | ClearNoon | 0.9 | **12** | 12 | 0 | 0 | 18 | 0 | 16 | 7807 | 16584 | 2332 | 0 | 1800 | 1.07 | 64.4 | ok |
| Town10HD_Opt | ClearNoon | 1.0 | **16** | 16 | 0 | 0 | 22 | 0 | 9 | 6308 | 17587 | 1671 | 0 | 1800 | 1.08 | 65.0 | ok |
| Town10HD_Opt | HardRainNoon | 0.0 | **7** | 0 | 7 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0.86 | 51.4 | ok |
| Town10HD_Opt | HardRainNoon | 0.5 | **10** | 9 | 1 | 0 | 14 | 0 | 2 | 2984 | 5838 | 2175 | 0 | 1800 | 0.84 | 50.3 | ok |
| Town10HD_Opt | HardRainNoon | 0.9 | **17** | 17 | 0 | 0 | 27 | 0 | 10 | 5340 | 15308 | 1620 | 0 | 1800 | 0.83 | 50.0 | ok |
| Town10HD_Opt | HardRainNoon | 1.0 | **13** | 13 | 0 | 0 | 20 | 0 | 1 | 6371 | 20686 | 1887 | 0 | 1800 | 1.01 | 60.6 | ok |

### 3.3 V2V-only (--no-v2x)

| Town | Weather | $p$ | coll | cav | hdv | vru | frozen | coop | phantom | dec | soft | hard | v2v_recv | cpm_emit | ratio | wall(s) | status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Town01 | ClearNoon | 0.0 | **7** | 0 | 7 | 0 | 11 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.18 | 10.9 | ok |
| Town01 | ClearNoon | 0.5 | **9** | 8 | 1 | 0 | 15 | 0 | 14 | 2702 | 4652 | 186 | 84332 | 0 | 0.35 | 20.9 | ok |
| Town01 | ClearNoon | 0.9 | **9** | 9 | 0 | 0 | 14 | 12 | 8 | 5521 | 16447 | 401 | 256925 | 0 | 0.8 | 48.1 | ok |
| Town01 | ClearNoon | 1.0 | **9** | 9 | 0 | 1 | 13 | 0 | 16 | 5954 | 16877 | 254 | 341709 | 0 | 0.97 | 58.5 | ok |
| Town01 | HardRainNoon | 0.0 | **4** | 0 | 4 | 0 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.18 | 10.8 | ok |
| Town01 | HardRainNoon | 0.5 | **9** | 7 | 2 | 0 | 15 | 0 | 16 | 3090 | 2743 | 153 | 87232 | 0 | 0.34 | 20.6 | ok |
| Town01 | HardRainNoon | 0.9 | **10** | 10 | 0 | 0 | 16 | 9 | 6 | 5223 | 11937 | 298 | 267425 | 0 | 0.71 | 42.8 | ok |
| Town01 | HardRainNoon | 1.0 | **8** | 8 | 0 | 0 | 13 | 0 | 14 | 5939 | 18649 | 230 | 324205 | 0 | 0.91 | 54.4 | ok |
| Town05 | ClearNoon | 0.0 | **2** | 0 | 2 | 1 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.18 | 10.8 | ok |
| Town05 | ClearNoon | 0.5 | **6** | 6 | 0 | 0 | 9 | 0 | 6 | 1571 | 1067 | 86 | 124152 | 0 | 0.4 | 24.1 | ok |
| Town05 | ClearNoon | 0.9 | **6** | 6 | 0 | 0 | 9 | 2 | 10 | 2776 | 3919 | 48 | 489188 | 0 | 1.3 | 78.0 | ok |
| Town05 | ClearNoon | 1.0 | **5** | 5 | 0 | 0 | 9 | 0 | 23 | 3692 | 4976 | 14 | 562078 | 0 | 1.66 | 99.6 | ok |
| Town05 | HardRainNoon | 0.0 | **5** | 0 | 5 | 0 | 10 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.18 | 10.9 | ok |
| Town05 | HardRainNoon | 0.5 | **6** | 5 | 1 | 0 | 8 | 0 | 10 | 1179 | 2363 | 10 | 144500 | 0 | 0.48 | 28.9 | ok |
| Town05 | HardRainNoon | 0.9 | **3** | 3 | 0 | 0 | 5 | 0 | 20 | 2896 | 3989 | 12 | 456306 | 0 | 1.12 | 67.1 | ok |
| Town05 | HardRainNoon | 1.0 | **10** | 10 | 0 | 0 | 16 | 24 | 12 | 3916 | 7038 | 1100 | 535000 | 0 | 1.92 | 115.1 | ok |
| Town10HD_Opt | ClearNoon | 0.0 | **9** | 0 | 9 | 1 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.22 | 13.1 | ok |
| Town10HD_Opt | ClearNoon | 0.5 | **14** | 11 | 3 | 0 | 23 | 15 | 8 | 4057 | 8459 | 39 | 146682 | 0 | 0.85 | 50.9 | ok |
| Town10HD_Opt | ClearNoon | 0.9 | **14** | 14 | 0 | 1 | 21 | 19 | 3 | 7073 | 17170 | 434 | 516642 | 0 | 2.64 | 158.3 | ok |
| Town10HD_Opt | ClearNoon | 1.0 | **12** | 12 | 0 | 1 | 17 | 92 | 22 | 8765 | 19408 | 551 | 613422 | 0 | 3.23 | 194.0 | ok |
| Town10HD_Opt | HardRainNoon | 0.0 | **8** | 0 | 8 | 1 | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.23 | 14.0 | ok |
| Town10HD_Opt | HardRainNoon | 0.5 | **13** | 12 | 1 | 0 | 22 | 0 | 12 | 5149 | 6822 | 32 | 146555 | 0 | 0.76 | 45.4 | ok |
| Town10HD_Opt | HardRainNoon | 0.9 | **17** | 17 | 0 | 1 | 28 | 45 | 12 | 6711 | 11558 | 92 | 412846 | 0 | 1.82 | 109.1 | ok |
| Town10HD_Opt | HardRainNoon | 1.0 | **14** | 14 | 0 | 1 | 21 | 32 | 14 | 6902 | 18869 | 1413 | 599861 | 0 | 3.3 | 198.1 | ok |

---

## 4. Collisions by map (averaged over weather)

| Map | Arm | p0.0 | p0.5 | p0.9 | p1.0 |
| :--- | :--- | :---: | :---: | :---: | :---: |
| Town01 | Combined (V2X + V2V) | 4.0 | 8.0 | 7.5 | 10.5 |
| Town01 | V2I-only (--no-v2v) | 6.0 | 9.0 | 7.0 | 6.5 |
| Town01 | V2V-only (--no-v2x) | 5.5 | 9.0 | 9.5 | 8.5 |
| Town05 | Combined (V2X + V2V) | 5.0 | 6.0 | 7.5 | 8.0 |
| Town05 | V2I-only (--no-v2v) | 1.5 | 7.0 | 7.0 | 7.0 |
| Town05 | V2V-only (--no-v2x) | 3.5 | 6.0 | 4.5 | 7.5 |
| Town10HD_Opt | Combined (V2X + V2V) | 9.5 | 18.5 | 11.0 | 12.5 |
| Town10HD_Opt | V2I-only (--no-v2v) | 9.0 | 13.0 | 14.5 | 14.5 |
| Town10HD_Opt | V2V-only (--no-v2x) | 8.5 | 13.5 | 15.5 | 13.0 |

## 5. Collisions by weather (averaged over maps)

| Weather | Arm | p0.0 | p0.5 | p0.9 | p1.0 |
| :--- | :--- | :---: | :---: | :---: | :---: |
| ClearNoon | Combined (V2X + V2V) | 6.0 | 9.0 | 9.0 | 10.7 |
| ClearNoon | V2I-only (--no-v2v) | 6.5 | 10.3 | 9.0 | 9.3 |
| ClearNoon | V2V-only (--no-v2x) | 6.0 | 9.7 | 9.7 | 8.7 |
| HardRainNoon | Combined (V2X + V2V) | 6.3 | 12.7 | 8.3 | 10.0 |
| HardRainNoon | V2I-only (--no-v2v) | 4.7 | 9.0 | 11.5 | 9.3 |
| HardRainNoon | V2V-only (--no-v2x) | 5.7 | 9.3 | 10.0 | 10.7 |

---

## 6. Cooperative-communication load (the stack IS live)

| $p$ | V2V recv (combined) | Coop brakes (combined) | Coop brakes (v2v-only) | Coop brakes (v2i-only) |
| :---: | :---: | :---: | :---: | :---: |
| 0.0 | 0 | 0 | 0 | 0 |
| 0.5 | 111418 | 11 | 2 | 0 |
| 0.9 | 416436 | 33 | 14 | 0 |
| 1.0 | 499058 | 65 | 25 | 0 |

Half a million V2V messages per cell at high penetration, yet only ~65 cooperative-brake actions result - a vanishingly small share of the ~72,000 CAV decision cycles per cell. `v2i_only` correctly shows **zero** cooperative brakes (no V2V channel).

## 7. Performance (wall-to-sim ratio, Combined arm)

| Map | p0.0 | p0.5 | p0.9 | p1.0 |
| :--- | :---: | :---: | :---: | :---: |
| Town01 | 0.58 | 0.81 | 1.29 | 1.40 |
| Town05 | 0.64 | 1.01 | 2.00 | 2.62 |
| Town10HD_Opt | 0.84 | 1.39 | 3.96 | 4.43 |

Ratio = wall seconds per sim second (lower = faster than real time). The broker rewrite keeps even Town10 at p=1.0 around 4.4x - tractable where earlier versions stalled.

---

## Findings & root cause

Three facts in the data, together, identify the failure mode:

1. **Inverted curve** - collisions rise from ~6 (all-human) to ~9-11 once CAVs are present, then plateau. Adding connected vehicles makes things *worse*.
2. **Flat across arms** - Combined, V2I-only and V2V-only are within noise at every penetration. The cooperative *content* is not what determines outcomes.
3. **CAVs are the victims** - at high $p$ the crashes are almost entirely CAV-on-something, and ~15 of 60 vehicles end each Town cell **frozen** (immobilised after a collision).

### Root cause: the deadlock fix over-corrected

The green-light deadlock was caused by CAVs braking on the RSU's ghost detection of their own body. The fix drops **every** track within **3.0 m** of ego centre (`cav.py` ~L399, a blanket spatial `continue`). But it is a **position-only** gate: a genuine threat in that radius is discarded exactly like a self-ghost. Combined with a distance-fallback ladder whose 4.0 m hard-brake band sits below typical centre-to-centre spacing, the emergency-braking range is effectively blanked out. **CAVs under-brake and drive into hazards.** A correct fix must identify the ego-ghost by **velocity match** (co-located *and* co-moving), not proximity alone.

### Second, structural contributor

The flat-across-arms result points to a contributor independent of braking tuning: when two vehicles collide they are **immobilised in place**, becoming stationary obstacles that downstream traffic - including careful CAVs - then rear-ends, propagating incidents. This inflates counts in a way no message-passing can prevent, which is why the cooperative arms do not separate.

---

## Code changes that produced this run

- **Broker dispatch O(N^2)->O(N):** per-receiver message queues replace the flat scan; CPM/V2V payload decoding memoised (`lru_cache`). Removed the V2V congestion slowdown.
- **V2V directional + lateral gating:** a received hard-brake warning only acts if the sender is ahead within the heading cone (yaw dot-product > 0) **and** within 2.0 m lateral offset - killing the opposing-lane phantom braking.
- **Distance-based safety fallback:** a confirmed in-lane track triggers DECELERATE / SOFT_BRAKE / HARD_BRAKE at 9.0 / 6.5 / 4.0 m even when TTC is undefined (stopped-wreck case).
- **Restored TM avoidance for HDVs:** the blanket `disable_collision_detection_for()` call was removed so HDVs no longer pile up at spawn; conflicts now come from profile ignore-rates.
- **HDV ignore-rate boost:** aggressive-hostile ignore-vehicles 10%->40%, distracted 10%->20%.
- **Ego self-exclusion (the deadlock fix):** tracks within 3.0 m of ego centre dropped to stop CAVs braking on the RSU ghost reflection. **Prime suspect for the regression above.**

---

## Threats to validity

- **Single seed.** One spawn layout per cell; the +/-0 error bars are not real variance. Trends are directional only.
- **Braking regression.** The CAV decision layer is mis-calibrated for this run, so absolute collision counts overstate real CAV risk and must not be quoted as a V2X-effectiveness result.
- **Immobilise-as-obstacle.** The freeze-on-collision policy couples incidents; a metric-design choice needing review.
- **Two missing v2i cells.** Town01 p0.0 ClearNoon and p0.9 HardRainNoon crashed at spawn; v2i_only averages use surviving cells.

## Recommended next steps

1. Replace the 3.0 m self-exclusion with a **velocity-matched** ego-ghost filter; add a regression test asserting a closing in-lane track within 3 m still produces HARD_BRAKE.
2. Audit the collision/immobilise loop in `40_ablation_run.py` to quantify CAV crashes that are secondary rear-ends into frozen wrecks vs primary failures.
3. Re-validate on a small grid (1 map x 4 pen x combined arm); confirm the curve falls before a full multi-seed sweep.
4. Once corrected, re-run Configuration G (or the larger Compromise matrix) for the report-grade result; keep this G data archived as the pre-fix baseline.

---

*Data source: `out/ablation_G/{combined, v2i_only, v2v_only}`. All values computed directly from per-cell JSON metrics.*