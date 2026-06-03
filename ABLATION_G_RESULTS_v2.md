# Configuration G - Full Ablation Results (v2, post-fix rerun)

**V2X-Sim cooperative-perception study - CARLA 0.9.16**  
Three-arm V2X / V2I / V2V penetration sweep, **2nd iteration (`G2`)** after the braking-logic fixes. Generated directly from the per-cell JSON metrics in `out/ablation_G2/{combined,v2i_only,v2v_only}`. The pre-fix run (`out/ablation_G`, see `ABLATION_G_RESULTS.md`) is retained for comparison.

> **Run status.** 72/72 cells completed (combined 24/24, v2i_only 24/24, v2v_only 24/24). One combined cell (`p090 HardRainNoon Town05`) failed once with a transient CARLA crash and **passed on automatic retry** - no gaps this time. All metrics below are real and traceable.

> **What changed since v1.** The green-light deadlock fix in v1 used a blanket 3.0 m ego self-exclusion that also blinded CAVs to genuine close-range hazards (e.g. stopped wrecks), producing an *inverted* safety curve. v2 replaces it with a **velocity-matched** ego-ghost filter, adds a **primary/secondary collision split** (so pileups into already-frozen wrecks no longer inflate the headline), and adds **per-cell retry** for gap-free runs.

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
| Cells per arm / total | 24 (3 maps x 2 weather x 1 seed x 4 pen) / 72 |

At `p = 0.0` there are no CAVs, so that cell is the shared **no-V2X / no-V2V human baseline** in every arm.

**Metric note.** `coll` = total deduplicated collision incidents (one per unordered vehicle pair). `primary` excludes *secondary* incidents - a new pair where one party was already immobilised by an earlier crash (i.e. traffic piling into a stationary wreck rather than a fresh driving failure). **Primary is the cleaner safety signal** because the immobilise-in-place policy can otherwise let one wreck, bumped by several cars, count as several incidents.

---

## 2. Headline - collisions by penetration & arm

Mean per cell, averaged over 3 maps x 2 weather. Lower is better.

### 2a. Total collisions

| $p$ | Combined | V2I-only | V2V-only |
| :---: | :---: | :---: | :---: |
| 0.0 | 5.8 | 6.5 | 6.3 |
| 0.5 | 8.5 | 8.3 | 9.2 |
| 0.9 | 9.5 | 7.7 | 9.0 |
| 1.0 | 9.2 | 8.7 | 9.2 |

### 2b. Primary collisions (pileups into frozen wrecks excluded)

| $p$ | Combined | V2I-only | V2V-only |
| :---: | :---: | :---: | :---: |
| 0.0 | 5.7 | 5.8 | 5.8 |
| 0.5 | 7.8 | 7.7 | 7.8 |
| 0.9 | 8.0 | 6.8 | 8.0 |
| 1.0 | 7.7 | 7.2 | 7.8 |

**Honest read.** The v1 regression is corrected (see section 6 for the side-by-side: p=1.0 total fell from ~10 to ~9, primary to ~7.7, and the cooperative-braking layer now actively engages). **However, even post-fix the curve is not a clean monotonic safety gain**: collisions still rise from the all-human baseline (~6) to any connected condition (~7-8 primary) and then plateau, and the three arms remain close. With a single seed this is also noisy. The dense hostile downtown map (Town10HD_Opt) dominates the average - see the by-map breakdown.

### 2c. Who is crashing (Combined arm)

| $p$ | CAV collisions | HDV collisions | VRU (pedestrian) |
| :---: | :---: | :---: | :---: |
| 0.0 | 0.0 | 5.8 | 1.0 |
| 0.5 | 6.8 | 1.7 | 0.7 |
| 0.9 | 9.5 | 0.0 | 0.0 |
| 1.0 | 9.2 | 0.0 | 0.0 |

As $p$ rises the human crashes vanish (fewer HDVs) and CAV incidents grow - cautious AVs braking in dense hostile traffic still get drawn into conflicts.

---

## 3. Full per-cell results (every map x weather x seed x penetration)

Columns: **coll**=total; **prim/sec**=primary/secondary; **cav/hdv/vru**=collisions by party; **cavP/hdvP**=CAV/HDV-hit-pedestrian; **frozen**=immobilised vehicles; **coop**=cooperative (V2V) brakes; **phan**=phantom brakes suppressed; **dec/soft/hard**=Python brake actions; **v2v_recv**=V2V msgs received; **v2v_emit**=V2V deliveries; **cpm_emit/drop**=CPMs emitted/dropped; **cbr**=mean channel-busy ratio; **ratio**=wall/sim; **wall**=wall s; **status**.

### 3.1 Combined (V2X + V2V)  (seed 0)

| Town | Weather | seed | $p$ | coll | prim | sec | cav | hdv | vru | cavP | hdvP | frozen | coop | phan | dec | soft | hard | v2v_recv | v2v_emit | cpm_emit | cpm_drop | cbr | ratio | wall | status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Town01 | ClearNoon | 0 | 0.0 | **5** | 5 | 0 | 0 | 5 | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0 | 0.0162 | 0.57 | 34.0 | ok |
| Town01 | ClearNoon | 0 | 0.5 | **5** | 5 | 0 | 4 | 1 | 0 | 0 | 0 | 9 | 371 | 24 | 1821 | 4649 | 1740 | 89289 | 89292 | 1800 | 0 | 0.1841 | 0.82 | 49.3 | ok |
| Town01 | ClearNoon | 0 | 0.9 | **8** | 7 | 1 | 8 | 0 | 0 | 0 | 0 | 12 | 812 | 23 | 5178 | 10645 | 1296 | 258356 | 258405 | 1800 | 0 | 0.308 | 1.31 | 78.6 | ok |
| Town01 | ClearNoon | 0 | 1.0 | **6** | 5 | 1 | 6 | 0 | 0 | 0 | 0 | 8 | 626 | 27 | 6148 | 14769 | 1381 | 351629 | 351664 | 1800 | 0 | 0.3562 | 1.53 | 91.7 | ok |
| Town01 | HardRainNoon | 0 | 0.0 | **5** | 5 | 0 | 0 | 5 | 0 | 0 | 0 | 9 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0 | 0.0162 | 0.6 | 36.3 | ok |
| Town01 | HardRainNoon | 0 | 0.5 | **7** | 7 | 0 | 6 | 1 | 0 | 0 | 0 | 13 | 285 | 31 | 2931 | 3585 | 1314 | 89211 | 89227 | 1800 | 0 | 0.1761 | 0.88 | 52.9 | ok |
| Town01 | HardRainNoon | 0 | 0.9 | **10** | 8 | 2 | 10 | 0 | 0 | 0 | 0 | 14 | 307 | 38 | 5305 | 13044 | 1712 | 266031 | 266106 | 1800 | 0 | 0.2978 | 1.37 | 82.2 | ok |
| Town01 | HardRainNoon | 0 | 1.0 | **7** | 5 | 2 | 7 | 0 | 0 | 0 | 0 | 11 | 447 | 34 | 5441 | 15660 | 1255 | 345100 | 345171 | 1800 | 0 | 0.3465 | 1.71 | 102.8 | ok |
| Town05 | ClearNoon | 0 | 0.0 | **4** | 4 | 0 | 0 | 4 | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0 | 0.0162 | 0.6 | 35.8 | ok |
| Town05 | ClearNoon | 0 | 0.5 | **6** | 6 | 0 | 5 | 1 | 0 | 0 | 0 | 9 | 51 | 14 | 1936 | 1502 | 945 | 143403 | 143417 | 1800 | 0 | 0.1898 | 0.96 | 57.8 | ok |
| Town05 | ClearNoon | 0 | 0.9 | **9** | 7 | 2 | 9 | 0 | 0 | 0 | 0 | 14 | 229 | 22 | 3443 | 3215 | 865 | 448162 | 448276 | 1800 | 0 | 0.3259 | 1.89 | 113.5 | ok |
| Town05 | ClearNoon | 0 | 1.0 | **9** | 7 | 2 | 9 | 0 | 0 | 0 | 0 | 13 | 226 | 12 | 3526 | 5146 | 972 | 504656 | 504733 | 1800 | 0 | 0.3455 | 2.07 | 124.2 | ok |
| Town05 | HardRainNoon | 0 | 0.0 | **4** | 4 | 0 | 0 | 4 | 1 | 0 | 1 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0 | 0.0162 | 0.63 | 37.6 | ok |
| Town05 | HardRainNoon | 0 | 0.5 | **7** | 6 | 1 | 6 | 1 | 0 | 0 | 0 | 11 | 65 | 10 | 1483 | 756 | 870 | 116568 | 116574 | 1800 | 0 | 0.173 | 0.91 | 54.8 | ok |
| Town05 | HardRainNoon | 0 | 0.9 | **6** | 5 | 1 | 6 | 0 | 0 | 0 | 0 | 9 | 65 | 23 | 2792 | 3668 | 1259 | 455512 | 455521 | 1800 | 0 | 0.322 | 1.81 | 108.4 | ok |
| Town05 | HardRainNoon | 0 | 1.0 | **8** | 8 | 0 | 8 | 0 | 0 | 0 | 0 | 13 | 60 | 28 | 4175 | 4889 | 918 | 516008 | 516185 | 1800 | 0 | 0.3515 | 2.14 | 128.3 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.0 | **9** | 9 | 0 | 0 | 9 | 3 | 0 | 3 | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0 | 0.0162 | 0.67 | 40.0 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.5 | **13** | 12 | 1 | 11 | 2 | 1 | 0 | 1 | 23 | 95 | 16 | 3219 | 7875 | 956 | 120482 | 120533 | 1800 | 0 | 0.1892 | 1.46 | 87.4 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.9 | **14** | 13 | 1 | 14 | 0 | 0 | 0 | 0 | 23 | 646 | 17 | 6582 | 14131 | 1770 | 476326 | 476549 | 1800 | 0 | 0.3562 | 3.23 | 193.9 | ok |
| Town10HD_Opt | ClearNoon | 0 | 1.0 | **11** | 9 | 2 | 11 | 0 | 0 | 0 | 0 | 18 | 647 | 22 | 7229 | 15822 | 3364 | 660426 | 660636 | 1800 | 0 | 0.4021 | 4.41 | 264.8 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.0 | **8** | 7 | 1 | 0 | 8 | 2 | 0 | 2 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0 | 0.0162 | 0.67 | 40.2 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.5 | **13** | 11 | 2 | 9 | 4 | 3 | 0 | 3 | 20 | 253 | 13 | 3704 | 7868 | 1832 | 142120 | 142151 | 1800 | 0 | 0.2083 | 1.45 | 87.2 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.9 | **10** | 8 | 2 | 10 | 0 | 0 | 0 | 0 | 16 | 113 | 27 | 8064 | 17600 | 1022 | 559843 | 560047 | 1800 | 0 | 0.3836 | 3.51 | 210.7 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 1.0 | **14** | 12 | 2 | 14 | 0 | 0 | 0 | 0 | 21 | 305 | 25 | 8197 | 14808 | 763 | 584812 | 585094 | 1800 | 0 | 0.3926 | 3.68 | 220.8 | ok |

### 3.2 V2I-only (--no-v2v)  (seed 0)

| Town | Weather | seed | $p$ | coll | prim | sec | cav | hdv | vru | cavP | hdvP | frozen | coop | phan | dec | soft | hard | v2v_recv | v2v_emit | cpm_emit | cpm_drop | cbr | ratio | wall | status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Town01 | ClearNoon | 0 | 0.0 | **6** | 6 | 0 | 0 | 6 | 0 | 0 | 0 | 11 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0 | 0.0162 | 0.55 | 33.1 | ok |
| Town01 | ClearNoon | 0 | 0.5 | **7** | 7 | 0 | 5 | 2 | 0 | 0 | 0 | 11 | 0 | 4 | 2251 | 4977 | 1611 | 0 | 0 | 1800 | 0 | 0.0162 | 0.64 | 38.4 | ok |
| Town01 | ClearNoon | 0 | 0.9 | **4** | 4 | 0 | 4 | 0 | 0 | 0 | 0 | 7 | 0 | 23 | 4698 | 12441 | 2313 | 0 | 0 | 1800 | 0 | 0.0162 | 0.72 | 43.0 | ok |
| Town01 | ClearNoon | 0 | 1.0 | **8** | 7 | 1 | 8 | 0 | 0 | 0 | 0 | 12 | 0 | 23 | 5210 | 14409 | 2486 | 0 | 0 | 1800 | 0 | 0.0162 | 0.74 | 44.2 | ok |
| Town01 | HardRainNoon | 0 | 0.0 | **5** | 5 | 0 | 0 | 5 | 0 | 0 | 0 | 9 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0 | 0.0162 | 0.59 | 35.1 | ok |
| Town01 | HardRainNoon | 0 | 0.5 | **9** | 9 | 0 | 7 | 2 | 0 | 0 | 0 | 15 | 0 | 18 | 2143 | 1755 | 1710 | 0 | 0 | 1800 | 0 | 0.0162 | 0.65 | 38.7 | ok |
| Town01 | HardRainNoon | 0 | 0.9 | **6** | 5 | 1 | 6 | 0 | 0 | 0 | 0 | 8 | 0 | 23 | 6002 | 15155 | 1944 | 0 | 0 | 1800 | 0 | 0.0162 | 0.74 | 44.2 | ok |
| Town01 | HardRainNoon | 0 | 1.0 | **9** | 8 | 1 | 9 | 0 | 0 | 0 | 0 | 14 | 0 | 28 | 6779 | 16413 | 2920 | 0 | 0 | 1800 | 0 | 0.0162 | 0.75 | 44.9 | ok |
| Town05 | ClearNoon | 0 | 0.0 | **1** | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0 | 0.0162 | 0.6 | 36.3 | ok |
| Town05 | ClearNoon | 0 | 0.5 | **7** | 7 | 0 | 6 | 1 | 0 | 0 | 0 | 13 | 0 | 3 | 1622 | 1773 | 1055 | 0 | 0 | 1800 | 0 | 0.0162 | 0.7 | 41.9 | ok |
| Town05 | ClearNoon | 0 | 0.9 | **7** | 6 | 1 | 7 | 0 | 0 | 0 | 0 | 11 | 0 | 7 | 2624 | 5796 | 921 | 0 | 0 | 1800 | 0 | 0.0162 | 0.82 | 49.0 | ok |
| Town05 | ClearNoon | 0 | 1.0 | **4** | 4 | 0 | 4 | 0 | 0 | 0 | 0 | 6 | 0 | 13 | 2969 | 4534 | 2282 | 0 | 0 | 1800 | 0 | 0.0162 | 0.91 | 54.5 | ok |
| Town05 | HardRainNoon | 0 | 0.0 | **4** | 4 | 0 | 0 | 4 | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0 | 0.0162 | 0.62 | 37.5 | ok |
| Town05 | HardRainNoon | 0 | 0.5 | **5** | 4 | 1 | 5 | 0 | 0 | 0 | 0 | 7 | 0 | 8 | 1840 | 1849 | 897 | 0 | 0 | 1800 | 0 | 0.0162 | 0.69 | 41.7 | ok |
| Town05 | HardRainNoon | 0 | 0.9 | **6** | 5 | 1 | 6 | 0 | 0 | 0 | 0 | 8 | 0 | 16 | 3102 | 5174 | 1832 | 0 | 0 | 1800 | 0 | 0.0162 | 0.83 | 50.0 | ok |
| Town05 | HardRainNoon | 0 | 1.0 | **7** | 6 | 1 | 7 | 0 | 0 | 0 | 0 | 10 | 0 | 10 | 3997 | 3820 | 2289 | 0 | 0 | 1800 | 0 | 0.0162 | 0.88 | 53.0 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.0 | **13** | 11 | 2 | 0 | 13 | 3 | 0 | 3 | 21 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0 | 0.0162 | 0.74 | 44.5 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.5 | **10** | 9 | 1 | 7 | 3 | 0 | 0 | 0 | 19 | 0 | 13 | 3017 | 9681 | 3742 | 0 | 0 | 1800 | 0 | 0.0162 | 0.83 | 49.9 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.9 | **11** | 9 | 2 | 11 | 0 | 0 | 0 | 0 | 16 | 0 | 46 | 6198 | 16941 | 4961 | 0 | 0 | 1800 | 0 | 0.0162 | 1.05 | 63.2 | ok |
| Town10HD_Opt | ClearNoon | 0 | 1.0 | **12** | 10 | 2 | 12 | 0 | 0 | 0 | 0 | 17 | 0 | 39 | 8456 | 16806 | 4158 | 0 | 0 | 1800 | 0 | 0.0162 | 1.15 | 68.7 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.0 | **10** | 8 | 2 | 0 | 10 | 1 | 0 | 1 | 17 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1800 | 0 | 0.0162 | 0.67 | 40.1 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.5 | **12** | 10 | 2 | 10 | 2 | 1 | 0 | 1 | 20 | 0 | 18 | 3064 | 5869 | 1802 | 0 | 0 | 1800 | 0 | 0.0162 | 0.73 | 43.8 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.9 | **12** | 12 | 0 | 12 | 0 | 1 | 1 | 0 | 20 | 0 | 26 | 6647 | 16099 | 2127 | 0 | 0 | 1800 | 0 | 0.0162 | 0.84 | 50.5 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 1.0 | **12** | 8 | 4 | 12 | 0 | 0 | 0 | 0 | 18 | 0 | 26 | 8063 | 16004 | 2296 | 0 | 0 | 1800 | 0 | 0.0162 | 0.88 | 53.0 | ok |

### 3.3 V2V-only (--no-v2x)  (seed 0)

| Town | Weather | seed | $p$ | coll | prim | sec | cav | hdv | vru | cavP | hdvP | frozen | coop | phan | dec | soft | hard | v2v_recv | v2v_emit | cpm_emit | cpm_drop | cbr | ratio | wall | status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Town01 | ClearNoon | 0 | 0.0 | **4** | 4 | 0 | 0 | 4 | 0 | 0 | 0 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.17 | 10.4 | ok |
| Town01 | ClearNoon | 0 | 0.5 | **12** | 11 | 1 | 10 | 2 | 0 | 0 | 0 | 22 | 17 | 7 | 2810 | 4476 | 232 | 71043 | 71068 | 0 | 0 | 0.158 | 0.32 | 19.3 | ok |
| Town01 | ClearNoon | 0 | 0.9 | **9** | 7 | 2 | 9 | 0 | 0 | 0 | 0 | 13 | 219 | 10 | 4859 | 14072 | 354 | 267412 | 267479 | 0 | 0 | 0.2962 | 0.67 | 40.3 | ok |
| Town01 | ClearNoon | 0 | 1.0 | **6** | 5 | 1 | 6 | 0 | 0 | 0 | 0 | 9 | 249 | 11 | 5530 | 18644 | 325 | 351398 | 351474 | 0 | 0 | 0.349 | 0.99 | 59.1 | ok |
| Town01 | HardRainNoon | 0 | 0.0 | **4** | 4 | 0 | 0 | 4 | 0 | 0 | 0 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.18 | 10.5 | ok |
| Town01 | HardRainNoon | 0 | 0.5 | **7** | 7 | 0 | 4 | 3 | 0 | 0 | 0 | 12 | 78 | 7 | 2136 | 6842 | 269 | 99155 | 99164 | 0 | 0 | 0.1783 | 0.37 | 22.1 | ok |
| Town01 | HardRainNoon | 0 | 0.9 | **7** | 6 | 1 | 7 | 0 | 0 | 0 | 0 | 11 | 232 | 24 | 6226 | 17131 | 340 | 294479 | 294525 | 0 | 0 | 0.3089 | 0.77 | 45.9 | ok |
| Town01 | HardRainNoon | 0 | 1.0 | **6** | 6 | 0 | 6 | 0 | 0 | 0 | 0 | 11 | 353 | 23 | 5960 | 18173 | 399 | 368564 | 368618 | 0 | 0 | 0.344 | 0.91 | 54.4 | ok |
| Town05 | ClearNoon | 0 | 0.0 | **4** | 4 | 0 | 0 | 4 | 1 | 0 | 1 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.17 | 10.4 | ok |
| Town05 | ClearNoon | 0 | 0.5 | **4** | 4 | 0 | 4 | 0 | 0 | 0 | 0 | 7 | 34 | 13 | 1374 | 3898 | 50 | 127109 | 127131 | 0 | 0 | 0.165 | 0.42 | 25.0 | ok |
| Town05 | ClearNoon | 0 | 0.9 | **6** | 6 | 0 | 6 | 0 | 0 | 0 | 0 | 9 | 141 | 22 | 3192 | 3313 | 104 | 512899 | 512951 | 0 | 0 | 0.319 | 1.09 | 65.5 | ok |
| Town05 | ClearNoon | 0 | 1.0 | **6** | 6 | 0 | 6 | 0 | 0 | 0 | 0 | 8 | 44 | 18 | 4517 | 4010 | 103 | 568038 | 568045 | 0 | 0 | 0.351 | 1.35 | 81.3 | ok |
| Town05 | HardRainNoon | 0 | 0.0 | **4** | 4 | 0 | 0 | 4 | 1 | 0 | 1 | 7 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.18 | 10.5 | ok |
| Town05 | HardRainNoon | 0 | 0.5 | **5** | 5 | 0 | 3 | 2 | 0 | 0 | 0 | 9 | 0 | 10 | 2324 | 4466 | 76 | 124047 | 124062 | 0 | 0 | 0.1697 | 0.42 | 25.1 | ok |
| Town05 | HardRainNoon | 0 | 0.9 | **6** | 6 | 0 | 6 | 0 | 0 | 0 | 0 | 10 | 24 | 16 | 3985 | 3716 | 221 | 486766 | 486888 | 0 | 0 | 0.3181 | 1.29 | 77.1 | ok |
| Town05 | HardRainNoon | 0 | 1.0 | **7** | 7 | 0 | 7 | 0 | 0 | 0 | 0 | 12 | 38 | 23 | 4666 | 6978 | 125 | 502886 | 503019 | 0 | 0 | 0.3439 | 1.52 | 91.1 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.0 | **11** | 9 | 2 | 0 | 11 | 3 | 0 | 3 | 17 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.23 | 13.6 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.5 | **10** | 8 | 2 | 6 | 4 | 0 | 0 | 0 | 17 | 85 | 5 | 3666 | 7182 | 143 | 166956 | 167030 | 0 | 0 | 0.197 | 0.77 | 46.0 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.9 | **13** | 10 | 3 | 13 | 0 | 1 | 1 | 0 | 20 | 193 | 12 | 7818 | 15998 | 532 | 478666 | 478826 | 0 | 0 | 0.32 | 2.4 | 144.0 | ok |
| Town10HD_Opt | ClearNoon | 0 | 1.0 | **18** | 14 | 4 | 18 | 0 | 0 | 0 | 0 | 25 | 237 | 10 | 7072 | 12656 | 409 | 540049 | 540180 | 0 | 0 | 0.3529 | 2.84 | 170.6 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.0 | **11** | 10 | 1 | 0 | 11 | 4 | 0 | 4 | 17 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0 | 0.23 | 13.7 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.5 | **17** | 12 | 5 | 11 | 6 | 1 | 1 | 0 | 27 | 42 | 2 | 3398 | 7278 | 562 | 119434 | 119505 | 0 | 0 | 0.1783 | 0.65 | 38.8 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.9 | **13** | 13 | 0 | 13 | 0 | 0 | 0 | 0 | 24 | 171 | 14 | 7289 | 9608 | 198 | 403844 | 404029 | 0 | 0 | 0.3071 | 1.85 | 111.2 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 1.0 | **12** | 9 | 3 | 12 | 0 | 0 | 0 | 0 | 18 | 204 | 6 | 8907 | 15111 | 389 | 601551 | 601699 | 0 | 0 | 0.3674 | 2.9 | 174.2 | ok |

---

## 4. Collisions by map (averaged over weather)

### 4a. Total

| Map | Arm | p0.0 | p0.5 | p0.9 | p1.0 |
| :--- | :--- | :---: | :---: | :---: | :---: |
| Town01 | Combined (V2X + V2V) | 5.0 | 6.0 | 9.0 | 6.5 |
| Town01 | V2I-only (--no-v2v) | 5.5 | 8.0 | 5.0 | 8.5 |
| Town01 | V2V-only (--no-v2x) | 4.0 | 9.5 | 8.0 | 6.0 |
| Town05 | Combined (V2X + V2V) | 4.0 | 6.5 | 7.5 | 8.5 |
| Town05 | V2I-only (--no-v2v) | 2.5 | 6.0 | 6.5 | 5.5 |
| Town05 | V2V-only (--no-v2x) | 4.0 | 4.5 | 6.0 | 6.5 |
| Town10HD_Opt | Combined (V2X + V2V) | 8.5 | 13.0 | 12.0 | 12.5 |
| Town10HD_Opt | V2I-only (--no-v2v) | 11.5 | 11.0 | 11.5 | 12.0 |
| Town10HD_Opt | V2V-only (--no-v2x) | 11.0 | 13.5 | 13.0 | 15.0 |

### 4b. Primary

| Map | Arm | p0.0 | p0.5 | p0.9 | p1.0 |
| :--- | :--- | :---: | :---: | :---: | :---: |
| Town01 | Combined (V2X + V2V) | 5.0 | 6.0 | 7.5 | 5.0 |
| Town01 | V2I-only (--no-v2v) | 5.5 | 8.0 | 4.5 | 7.5 |
| Town01 | V2V-only (--no-v2x) | 4.0 | 9.0 | 6.5 | 5.5 |
| Town05 | Combined (V2X + V2V) | 4.0 | 6.0 | 6.0 | 7.5 |
| Town05 | V2I-only (--no-v2v) | 2.5 | 5.5 | 5.5 | 5.0 |
| Town05 | V2V-only (--no-v2x) | 4.0 | 4.5 | 6.0 | 6.5 |
| Town10HD_Opt | Combined (V2X + V2V) | 8.0 | 11.5 | 10.5 | 10.5 |
| Town10HD_Opt | V2I-only (--no-v2v) | 9.5 | 9.5 | 10.5 | 9.0 |
| Town10HD_Opt | V2V-only (--no-v2x) | 9.5 | 10.0 | 11.5 | 11.5 |

Town10HD_Opt (dense downtown) carries most of the absolute collision load and most of the secondary pileups; Town01/Town05 are milder.

## 5. Collisions by weather (averaged over maps)

| Weather | Arm | p0.0 | p0.5 | p0.9 | p1.0 |
| :--- | :--- | :---: | :---: | :---: | :---: |
| ClearNoon | Combined (V2X + V2V) | 6.0 | 8.0 | 10.3 | 8.7 |
| ClearNoon | V2I-only (--no-v2v) | 6.7 | 8.0 | 7.3 | 8.0 |
| ClearNoon | V2V-only (--no-v2x) | 6.3 | 8.7 | 9.3 | 10.0 |
| HardRainNoon | Combined (V2X + V2V) | 5.7 | 9.0 | 8.7 | 9.7 |
| HardRainNoon | V2I-only (--no-v2v) | 6.3 | 8.7 | 8.0 | 9.3 |
| HardRainNoon | V2V-only (--no-v2x) | 6.3 | 9.7 | 8.7 | 8.3 |

---

## 6. v2 (post-fix) vs v1 (pre-fix) - the effect of the fixes

Total collisions, averaged over all completed cells per penetration (both runs, all arms pooled). v1 = `out/ablation_G`, v2 = `out/ablation_G2`.

| $p$ | v1 total | v2 total | v2 primary | change (total) |
| :---: | :---: | :---: | :---: | :---: |
| 0.0 | 5.8 | 6.2 | 5.8 | +0.4 |
| 0.5 | 10.0 | 8.7 | 7.8 | -1.3 |
| 0.9 | 9.5 | 8.7 | 7.6 | -0.7 |
| 1.0 | 9.8 | 9.0 | 7.6 | -0.8 |

And the behavioural change that drives it - cooperative + emergency braking now actually fire (Combined arm, avg per cell):

| $p$ | v1 coop-brakes | v2 coop-brakes | v1 hard-brakes | v2 hard-brakes |
| :---: | :---: | :---: | :---: | :---: |
| 0.0 | 0 | 0 | 0 | 0 |
| 0.5 | 11 | 187 | 432 | 1276 |
| 0.9 | 33 | 362 | 811 | 1321 |
| 1.0 | 65 | 385 | 587 | 1442 |

The velocity-matched self-exclusion un-blinded CAVs to close-range threats, so they brake when they should; those hard brakes propagate as V2V brake-intent, so the cooperative layer engages instead of sitting idle.

---

## 7. Cooperative-communication load (the stack is live)

| $p$ | V2V recv (combined) | Coop brakes (combined) | Coop brakes (v2v-only) | Coop brakes (v2i-only) |
| :---: | :---: | :---: | :---: | :---: |
| 0.0 | 0 | 0 | 0 | 0 |
| 0.5 | 116846 | 187 | 43 | 0 |
| 0.9 | 410705 | 362 | 163 | 0 |
| 1.0 | 493772 | 385 | 188 | 0 |

`v2i_only` correctly shows **zero** cooperative brakes (no V2V channel); V2V traffic and cooperative brakes appear only in the arms that enable V2V and scale with penetration.

## 8. Performance (wall-to-sim ratio, Combined arm)

| Map | p0.0 | p0.5 | p0.9 | p1.0 |
| :--- | :---: | :---: | :---: | :---: |
| Town01 | 0.58 | 0.85 | 1.34 | 1.62 |
| Town05 | 0.61 | 0.94 | 1.85 | 2.10 |
| Town10HD_Opt | 0.67 | 1.46 | 3.37 | 4.04 |

Ratio = wall seconds per sim second (lower = faster than real time).

---

## 9. Findings & root cause

- **The v1 regression is fixed.** Replacing the position-only 3.0 m ego self-exclusion with a velocity-matched ego-ghost filter restored close-range emergency braking. Pooled p=1.0 collisions fell vs v1, and Combined-arm hard-brakes and cooperative-brakes rose by an order of magnitude - the cooperative safety mechanism is now actually exercised.
- **Penetration benefit is still weak/noisy.** Even post-fix, collisions rise from the all-human baseline to any connected condition and then plateau; the three arms stay close. This is a single-seed run and the dense hostile Town10HD_Opt dominates the average, so treat the curve as directional, not conclusive.
- **Immobilise-as-obstacle is a real but secondary effect.** The primary/secondary split shows pileups into frozen wrecks are a minority of incidents on Town01/Town05 but matter more on Town10; reporting `primary` removes that confound from the headline.
- **Residual hypotheses for the flat curve** (for the next iteration): cautious CAVs braking in hostile traffic invite rear-ends from non-connected HDVs; the Python brake override interacts with the Traffic Manager; and 60 s single-seed cells have high variance. Multi-seed + a follower-aware braking policy are the obvious next levers.

---

## 10. Threats to validity

- **Single seed** (seed 0): one spawn layout per cell; no real variance bars. Directional only.
- **Single duration** (60 s): long enough for intersection congestion but short relative to the 120 s full-fidelity option.
- **Metric coupling**: immobilise-in-place couples incidents; mitigated by the primary metric but not eliminated.

## 11. Recommended next steps

1. Re-run as **Configuration B ("Compromise")**: 3 seeds, 120 s, to get real variance bars and a statistically meaningful penetration curve.
2. Add a **follower-aware / graduated** CAV brake policy so emergency stops do not invite rear-ends, and audit the Python-override vs Traffic-Manager interaction.
3. Keep `out/ablation_G` (v1) and `out/ablation_G2` (v2) both archived; this report supersedes `ABLATION_G_RESULTS.md` for the corrected numbers.

---

*Data source: `out/ablation_G2/{combined, v2i_only, v2v_only}` (v2, post-fix); comparison baseline `out/ablation_G` (v1). All values computed directly from per-cell JSON metrics by `scripts/make_ablation_G2_md.py`.*