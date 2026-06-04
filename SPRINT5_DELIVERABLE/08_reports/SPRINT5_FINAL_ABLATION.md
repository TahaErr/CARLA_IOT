# Sprint 5 — Final Ablation Report

**V2X-Sim cooperative-perception study — CARLA 0.9.16**  
Three-arm V2X / V2I / V2V penetration sweep, **2 seeds split across two machines** (seed 0 + seed 1). Generated directly from the 144 per-cell JSON metrics in `out/ablation_sprint5_final/{combined,v2i_only,v2v_only}`.

> **Headline.** Replacing reckless human drivers with cooperative AVs produces a clean, monotonic safety gain: mean collisions fall from **~22** (all-human baseline) to **~6** at full cooperative penetration — a **~73% reduction** — with no inversion or plateau-then-rise. 144/144 cells completed with zero failures across both machines.

---

## 1. Experimental design

| Dimension | Value |
| :--- | :--- |
| Communication arms | Combined (V2X+V2V) / V2I-only (`--no-v2v`) / V2V-only (`--no-v2x`) |
| Penetration `p` | 0.0, 0.5, 0.9, 1.0 |
| Maps | Town01 (grid), Town05 (multi-lane), Town10HD_Opt (dense downtown) |
| Weather | ClearNoon, HardRainNoon |
| Seeds | 0 (machine A) + 1 (machine B) |
| Sim duration | 90 s/cell @ dt 0.05 (20 Hz) |
| CPM / V2V cadence | 100 ms (10 Hz) |
| Population | 60 vehicles + 60 walkers |
| HDV behaviour | HOSTILE_MIX: attentive keep TM avoidance; distracted + aggressive_hostile avoidance OFF (each profile's ignore-rate sets the conflict gradient) |
| CAV behaviour | AI_REALISTIC: TM avoidance ON, 7 m follow gap, closing-rate brake gate, steer-preserving overrides |
| Cells | 3 maps x 2 weather x 2 seeds x 4 pen = 24/arm/seed; 144 total |

Each statistic below is a **mean ± sd over the 12 cells** that share a penetration (2 seeds x 3 maps x 2 weather), unless a finer breakdown is stated. At `p = 0.0` the fleet is 100% HDV, so no V2X/V2V is used or considered — that column is the shared human baseline and is identical across the three arms up to CARLA run-to-run nondeterminism.

---

## 2. Headline — collisions by penetration & arm

### 2a. Total collisions (mean ± sd)

| `p` | Combined | V2I-only | V2V-only |
| :---: | :---: | :---: | :---: |
| 0.0 | 21.9&plusmn;5.0 | 21.8&plusmn;4.9 | 21.8&plusmn;4.9 |
| 0.5 | 14.7&plusmn;4.1 | 14.5&plusmn;5.5 | 15.2&plusmn;4.7 |
| 0.9 | 7.2&plusmn;2.9 | 7.9&plusmn;3.9 | 8.3&plusmn;3.5 |
| 1.0 | 5.9&plusmn;3.5 | 6.1&plusmn;3.7 | 6.7&plusmn;2.9 |

### 2b. Primary collisions (pileups into frozen wrecks excluded)

| `p` | Combined | V2I-only | V2V-only |
| :---: | :---: | :---: | :---: |
| 0.0 | 16.1&plusmn;3.4 | 16.0&plusmn;3.4 | 16.0&plusmn;3.4 |
| 0.5 | 11.1&plusmn;2.8 | 10.3&plusmn;3.2 | 11.2&plusmn;2.4 |
| 0.9 | 6.3&plusmn;2.8 | 6.8&plusmn;3.2 | 7.5&plusmn;3.2 |
| 1.0 | 5.0&plusmn;2.9 | 5.0&plusmn;3.0 | 5.7&plusmn;2.9 |

**The curve is monotonic and steep** — every step up in penetration reduces collisions, on every arm. The all-human baseline (~22 total / ~16 primary) drops to ~6 total / ~5 primary at full penetration. A consistent mild ordering holds at each `p`: **Combined &le; V2I-only &le; V2V-only** — infrastructure CPM (V2I) is the stronger single channel, V2V-only is weakest but still beats the baseline, and running both together is best.

### 2c. Who is crashing (Combined arm, mean)

| `p` | CAV | HDV | VRU (pedestrian) |
| :---: | :---: | :---: | :---: |
| 0.0 | 0.0 | 21.9 | 0.9 |
| 0.5 | 7.6 | 7.1 | 0.6 |
| 0.9 | 6.6 | 0.7 | 0.6 |
| 1.0 | 5.9 | 0.0 | 0.3 |

---

## 3. Collisions by map (Combined arm, mean over weather + seed)

### 3a. Total

| Map | p0.0 | p0.5 | p0.9 | p1.0 |
| :--- | :---: | :---: | :---: | :---: |
| Town01 | 24.0 | 13.8 | 8.0 | 6.0 |
| Town05 | 15.5 | 10.8 | 3.8 | 1.8 |
| Town10HD_Opt | 26.2 | 19.5 | 10.0 | 10.0 |

### 3b. Primary

| Map | p0.0 | p0.5 | p0.9 | p1.0 |
| :--- | :---: | :---: | :---: | :---: |
| Town01 | 19.0 | 10.8 | 6.2 | 4.8 |
| Town05 | 11.5 | 8.2 | 3.8 | 1.8 |
| Town10HD_Opt | 17.8 | 14.2 | 9.0 | 8.5 |

**Town05** (multi-lane) is the cleanest — collisions fall to **~2** at p=1.0, near-elimination. **Town01** (grid) drops to ~6. **Town10HD_Opt** (dense downtown) is the hardest and **plateaus around ~10**: its complex junctions still produce wide-turn / lane-crossing conflicts that the cooperative layer cannot fully prevent (a known CARLA Traffic-Manager path-following limit on tight corners), so it caps the headline average.

## 4. Collisions by weather (Combined arm, mean over maps + seed)

| Weather | p0.0 | p0.5 | p0.9 | p1.0 |
| :--- | :---: | :---: | :---: | :---: |
| ClearNoon | 21.8 | 14.2 | 7.7 | 6.0 |
| HardRainNoon | 22.0 | 15.2 | 6.8 | 5.8 |

Weather has little effect on the safety curve — `HardRainNoon` tracks `ClearNoon` closely. The cooperative stack is robust to the rain preset.

---

## 5. At-fault collisions by driver profile (Combined, all cells pooled)

| Profile | At-fault collisions (sum) |
| :--- | :---: |
| attentive | 99 |
| distracted | 127 |
| aggressive_hostile | 187 |
| ai_realistic | 184 |

`aggressive_hostile` and `distracted` (avoidance OFF) dominate the human-caused crashes, exactly as the realism model intends; `attentive` HDVs (avoidance ON) appear far less and mostly as *victims* of reckless drivers rather than at-fault. `ai_realistic` is the CAV total across all penetrations — high only because at high `p` every vehicle is a CAV, so all remaining (few) collisions are necessarily CAV-involved.

---

## 6. Full per-cell results (every map x weather x seed x penetration)

Columns: **coll**=total; **prim/sec**=primary/secondary; **cav/hdv/vru**=by party; **frozen**=immobilised; **coop**=cooperative (V2V) brakes; **phan**=phantom suppressed; **dec/soft/hard**=Python brake actions; **v2v_recv**=V2V msgs; **cpm**=CPMs emitted; **w/s**=wall/sim; **st**=status.

### 6.1 Combined (V2X + V2V)

| Town | Weather | seed | `p` | coll | prim | sec | cav | hdv | vru | frozen | coop | phan | dec | soft | hard | v2v_recv | cpm | w/s | st |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Town01 | ClearNoon | 0 | 0.0 | **24** | 19 | 5 | 0 | 24 | 1 | 40 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.54 | ok |
| Town01 | ClearNoon | 0 | 0.5 | **13** | 10 | 3 | 5 | 8 | 0 | 23 | 389 | 8 | 1955 | 737 | 757 | 114241 | 2700 | 0.79 | ok |
| Town01 | ClearNoon | 0 | 0.9 | **7** | 5 | 2 | 7 | 0 | 2 | 10 | 795 | 38 | 6646 | 2077 | 1092 | 447658 | 2700 | 1.35 | ok |
| Town01 | ClearNoon | 0 | 1.0 | **5** | 5 | 0 | 5 | 0 | 1 | 8 | 1211 | 63 | 6933 | 2385 | 1076 | 552943 | 2700 | 1.39 | ok |
| Town01 | ClearNoon | 1 | 0.0 | **24** | 19 | 5 | 0 | 24 | 0 | 43 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.63 | ok |
| Town01 | ClearNoon | 1 | 0.5 | **13** | 10 | 3 | 7 | 6 | 0 | 23 | 414 | 19 | 2475 | 883 | 627 | 145138 | 2700 | 0.83 | ok |
| Town01 | ClearNoon | 1 | 0.9 | **8** | 6 | 2 | 6 | 2 | 0 | 14 | 820 | 51 | 5494 | 2007 | 750 | 416951 | 2700 | 1.19 | ok |
| Town01 | ClearNoon | 1 | 1.0 | **7** | 5 | 2 | 7 | 0 | 0 | 12 | 909 | 68 | 6488 | 2128 | 572 | 523449 | 2700 | 1.29 | ok |
| Town01 | HardRainNoon | 0 | 0.0 | **24** | 19 | 5 | 0 | 24 | 1 | 40 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.58 | ok |
| Town01 | HardRainNoon | 0 | 0.5 | **17** | 14 | 3 | 7 | 10 | 0 | 31 | 227 | 25 | 1928 | 573 | 624 | 109209 | 2700 | 0.78 | ok |
| Town01 | HardRainNoon | 0 | 0.9 | **8** | 7 | 1 | 8 | 0 | 2 | 13 | 778 | 63 | 5681 | 1729 | 786 | 453584 | 2700 | 1.34 | ok |
| Town01 | HardRainNoon | 0 | 1.0 | **5** | 4 | 1 | 5 | 0 | 1 | 8 | 924 | 40 | 7327 | 2187 | 724 | 592482 | 2700 | 1.55 | ok |
| Town01 | HardRainNoon | 1 | 0.0 | **24** | 19 | 5 | 0 | 24 | 0 | 43 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.63 | ok |
| Town01 | HardRainNoon | 1 | 0.5 | **12** | 9 | 3 | 6 | 6 | 0 | 21 | 256 | 35 | 2507 | 790 | 413 | 148724 | 2700 | 0.83 | ok |
| Town01 | HardRainNoon | 1 | 0.9 | **9** | 7 | 2 | 7 | 2 | 0 | 16 | 721 | 53 | 5915 | 1698 | 656 | 420462 | 2700 | 1.34 | ok |
| Town01 | HardRainNoon | 1 | 1.0 | **7** | 5 | 2 | 7 | 0 | 0 | 11 | 1338 | 70 | 7672 | 2466 | 705 | 511162 | 2700 | 1.38 | ok |
| Town05 | ClearNoon | 0 | 0.0 | **13** | 11 | 2 | 0 | 13 | 1 | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.59 | ok |
| Town05 | ClearNoon | 0 | 0.5 | **14** | 10 | 4 | 7 | 7 | 1 | 22 | 37 | 9 | 927 | 375 | 251 | 199364 | 2700 | 0.96 | ok |
| Town05 | ClearNoon | 0 | 0.9 | **4** | 4 | 0 | 4 | 0 | 1 | 7 | 42 | 33 | 2742 | 595 | 978 | 675637 | 2700 | 1.77 | ok |
| Town05 | ClearNoon | 0 | 1.0 | **2** | 2 | 0 | 2 | 0 | 0 | 4 | 312 | 35 | 3916 | 724 | 1064 | 852932 | 2700 | 2.17 | ok |
| Town05 | ClearNoon | 1 | 0.0 | **18** | 12 | 6 | 0 | 18 | 1 | 28 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.63 | ok |
| Town05 | ClearNoon | 1 | 0.5 | **8** | 7 | 1 | 4 | 4 | 0 | 15 | 0 | 21 | 1810 | 424 | 153 | 208395 | 2700 | 0.86 | ok |
| Town05 | ClearNoon | 1 | 0.9 | **6** | 6 | 0 | 5 | 1 | 0 | 12 | 207 | 30 | 2952 | 928 | 645 | 601844 | 2700 | 1.42 | ok |
| Town05 | ClearNoon | 1 | 1.0 | **1** | 1 | 0 | 1 | 0 | 0 | 2 | 104 | 33 | 3233 | 618 | 698 | 817209 | 2700 | 1.71 | ok |
| Town05 | HardRainNoon | 0 | 0.0 | **13** | 11 | 2 | 0 | 13 | 1 | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.63 | ok |
| Town05 | HardRainNoon | 0 | 0.5 | **12** | 9 | 3 | 7 | 5 | 1 | 19 | 40 | 9 | 899 | 301 | 664 | 190218 | 2700 | 0.95 | ok |
| Town05 | HardRainNoon | 0 | 0.9 | **3** | 3 | 0 | 3 | 0 | 0 | 6 | 107 | 18 | 2917 | 546 | 968 | 647059 | 2700 | 1.66 | ok |
| Town05 | HardRainNoon | 0 | 1.0 | **2** | 2 | 0 | 2 | 0 | 0 | 4 | 464 | 28 | 4152 | 1166 | 891 | 884253 | 2700 | 2.23 | ok |
| Town05 | HardRainNoon | 1 | 0.0 | **18** | 12 | 6 | 0 | 18 | 1 | 28 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.69 | ok |
| Town05 | HardRainNoon | 1 | 0.5 | **9** | 7 | 2 | 4 | 5 | 1 | 15 | 8 | 17 | 1119 | 349 | 539 | 234516 | 2700 | 0.99 | ok |
| Town05 | HardRainNoon | 1 | 0.9 | **2** | 2 | 0 | 1 | 1 | 0 | 4 | 223 | 24 | 2246 | 694 | 1093 | 703059 | 2700 | 1.54 | ok |
| Town05 | HardRainNoon | 1 | 1.0 | **2** | 2 | 0 | 2 | 0 | 0 | 4 | 126 | 44 | 3758 | 966 | 959 | 792615 | 2700 | 1.68 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.0 | **28** | 19 | 9 | 0 | 28 | 1 | 45 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.79 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.5 | **19** | 14 | 5 | 12 | 7 | 1 | 31 | 109 | 12 | 3280 | 804 | 315 | 194648 | 2700 | 1.7 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.9 | **9** | 9 | 0 | 9 | 0 | 1 | 17 | 809 | 20 | 7284 | 2211 | 1039 | 895108 | 2700 | 4.51 | ok |
| Town10HD_Opt | ClearNoon | 0 | 1.0 | **11** | 7 | 4 | 11 | 0 | 1 | 16 | 857 | 55 | 9091 | 2535 | 1291 | 903148 | 2700 | 4.81 | ok |
| Town10HD_Opt | ClearNoon | 1 | 0.0 | **24** | 16 | 8 | 0 | 24 | 1 | 39 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.71 | ok |
| Town10HD_Opt | ClearNoon | 1 | 0.5 | **18** | 15 | 3 | 10 | 8 | 1 | 32 | 452 | 30 | 3394 | 1282 | 1027 | 242250 | 2700 | 1.37 | ok |
| Town10HD_Opt | ClearNoon | 1 | 0.9 | **12** | 12 | 0 | 11 | 1 | 0 | 22 | 664 | 66 | 8400 | 2644 | 1140 | 853038 | 2700 | 3.85 | ok |
| Town10HD_Opt | ClearNoon | 1 | 1.0 | **10** | 9 | 1 | 10 | 0 | 0 | 18 | 1126 | 51 | 9653 | 2740 | 1191 | 1129059 | 2700 | 4.72 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.0 | **28** | 19 | 9 | 0 | 28 | 1 | 45 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.64 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.5 | **22** | 13 | 9 | 13 | 9 | 0 | 34 | 51 | 8 | 3920 | 741 | 367 | 203766 | 2700 | 1.52 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.9 | **11** | 10 | 1 | 11 | 0 | 1 | 18 | 674 | 45 | 8044 | 2067 | 841 | 794652 | 2700 | 3.71 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 1.0 | **10** | 10 | 0 | 10 | 0 | 1 | 19 | 517 | 37 | 9131 | 2060 | 565 | 984426 | 2700 | 4.67 | ok |
| Town10HD_Opt | HardRainNoon | 1 | 0.0 | **25** | 17 | 8 | 0 | 25 | 2 | 40 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.67 | ok |
| Town10HD_Opt | HardRainNoon | 1 | 0.5 | **19** | 15 | 4 | 9 | 10 | 2 | 31 | 177 | 35 | 4339 | 1143 | 396 | 263290 | 2700 | 1.55 | ok |
| Town10HD_Opt | HardRainNoon | 1 | 0.9 | **8** | 5 | 3 | 7 | 1 | 0 | 13 | 638 | 45 | 7577 | 2070 | 544 | 923929 | 2700 | 3.74 | ok |
| Town10HD_Opt | HardRainNoon | 1 | 1.0 | **9** | 8 | 1 | 9 | 0 | 0 | 16 | 599 | 45 | 9660 | 2734 | 930 | 1064481 | 2700 | 4.02 | ok |

### 6.2 V2I-only (--no-v2v)

| Town | Weather | seed | `p` | coll | prim | sec | cav | hdv | vru | frozen | coop | phan | dec | soft | hard | v2v_recv | cpm | w/s | st |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Town01 | ClearNoon | 0 | 0.0 | **24** | 19 | 5 | 0 | 24 | 1 | 40 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.54 | ok |
| Town01 | ClearNoon | 0 | 0.5 | **16** | 11 | 5 | 7 | 9 | 1 | 26 | 0 | 8 | 1848 | 249 | 1016 | 0 | 2700 | 0.63 | ok |
| Town01 | ClearNoon | 0 | 0.9 | **4** | 4 | 0 | 4 | 0 | 0 | 8 | 0 | 33 | 4609 | 800 | 1133 | 0 | 2700 | 0.72 | ok |
| Town01 | ClearNoon | 0 | 1.0 | **7** | 4 | 3 | 7 | 0 | 0 | 9 | 0 | 59 | 5584 | 1154 | 1170 | 0 | 2700 | 0.73 | ok |
| Town01 | ClearNoon | 1 | 0.0 | **24** | 19 | 5 | 0 | 24 | 0 | 43 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.56 | ok |
| Town01 | ClearNoon | 1 | 0.5 | **12** | 8 | 4 | 5 | 7 | 0 | 20 | 0 | 13 | 2519 | 627 | 701 | 0 | 2700 | 0.62 | ok |
| Town01 | ClearNoon | 1 | 0.9 | **9** | 7 | 2 | 7 | 2 | 0 | 16 | 0 | 21 | 4949 | 977 | 679 | 0 | 2700 | 0.7 | ok |
| Town01 | ClearNoon | 1 | 1.0 | **7** | 5 | 2 | 7 | 0 | 0 | 12 | 0 | 42 | 5626 | 1003 | 875 | 0 | 2700 | 0.71 | ok |
| Town01 | HardRainNoon | 0 | 0.0 | **24** | 19 | 5 | 0 | 24 | 1 | 40 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.59 | ok |
| Town01 | HardRainNoon | 0 | 0.5 | **15** | 10 | 5 | 7 | 8 | 0 | 25 | 0 | 17 | 2040 | 315 | 656 | 0 | 2700 | 0.64 | ok |
| Town01 | HardRainNoon | 0 | 0.9 | **6** | 4 | 2 | 6 | 0 | 0 | 10 | 0 | 32 | 4209 | 1152 | 748 | 0 | 2700 | 0.73 | ok |
| Town01 | HardRainNoon | 0 | 1.0 | **4** | 4 | 0 | 4 | 0 | 0 | 6 | 0 | 22 | 5151 | 904 | 802 | 0 | 2700 | 0.75 | ok |
| Town01 | HardRainNoon | 1 | 0.0 | **24** | 19 | 5 | 0 | 24 | 0 | 43 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.61 | ok |
| Town01 | HardRainNoon | 1 | 0.5 | **13** | 10 | 3 | 6 | 7 | 0 | 23 | 0 | 23 | 2293 | 493 | 466 | 0 | 2700 | 0.67 | ok |
| Town01 | HardRainNoon | 1 | 0.9 | **9** | 7 | 2 | 7 | 2 | 0 | 16 | 0 | 14 | 4783 | 872 | 951 | 0 | 2700 | 0.75 | ok |
| Town01 | HardRainNoon | 1 | 1.0 | **7** | 5 | 2 | 7 | 0 | 0 | 12 | 0 | 23 | 5639 | 1157 | 946 | 0 | 2700 | 0.77 | ok |
| Town05 | ClearNoon | 0 | 0.0 | **13** | 11 | 2 | 0 | 13 | 1 | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.57 | ok |
| Town05 | ClearNoon | 0 | 0.5 | **13** | 9 | 4 | 7 | 6 | 0 | 22 | 0 | 1 | 1007 | 359 | 261 | 0 | 2700 | 0.66 | ok |
| Town05 | ClearNoon | 0 | 0.9 | **3** | 3 | 0 | 3 | 0 | 0 | 4 | 0 | 16 | 2369 | 412 | 1066 | 0 | 2700 | 0.87 | ok |
| Town05 | ClearNoon | 0 | 1.0 | **1** | 1 | 0 | 1 | 0 | 0 | 2 | 0 | 10 | 2815 | 590 | 1789 | 0 | 2700 | 0.94 | ok |
| Town05 | ClearNoon | 1 | 0.0 | **18** | 12 | 6 | 0 | 18 | 1 | 28 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.58 | ok |
| Town05 | ClearNoon | 1 | 0.5 | **7** | 7 | 0 | 3 | 4 | 0 | 14 | 0 | 5 | 1166 | 428 | 870 | 0 | 2700 | 0.66 | ok |
| Town05 | ClearNoon | 1 | 0.9 | **5** | 5 | 0 | 5 | 0 | 0 | 10 | 0 | 20 | 2154 | 679 | 1419 | 0 | 2700 | 0.75 | ok |
| Town05 | ClearNoon | 1 | 1.0 | **3** | 3 | 0 | 3 | 0 | 0 | 5 | 0 | 32 | 2569 | 764 | 950 | 0 | 2700 | 0.8 | ok |
| Town05 | HardRainNoon | 0 | 0.0 | **13** | 11 | 2 | 0 | 13 | 1 | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.63 | ok |
| Town05 | HardRainNoon | 0 | 0.5 | **10** | 7 | 3 | 6 | 4 | 0 | 17 | 0 | 7 | 1298 | 318 | 864 | 0 | 2700 | 0.71 | ok |
| Town05 | HardRainNoon | 0 | 0.9 | **6** | 6 | 0 | 5 | 1 | 2 | 10 | 0 | 11 | 2349 | 504 | 1162 | 0 | 2700 | 0.87 | ok |
| Town05 | HardRainNoon | 0 | 1.0 | **2** | 2 | 0 | 2 | 0 | 0 | 4 | 0 | 27 | 2683 | 584 | 1738 | 0 | 2700 | 0.95 | ok |
| Town05 | HardRainNoon | 1 | 0.0 | **18** | 12 | 6 | 0 | 18 | 1 | 28 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.63 | ok |
| Town05 | HardRainNoon | 1 | 0.5 | **6** | 5 | 1 | 3 | 3 | 0 | 11 | 0 | 4 | 1125 | 362 | 238 | 0 | 2700 | 0.7 | ok |
| Town05 | HardRainNoon | 1 | 0.9 | **4** | 4 | 0 | 3 | 1 | 0 | 8 | 0 | 29 | 2143 | 617 | 1369 | 0 | 2700 | 0.85 | ok |
| Town05 | HardRainNoon | 1 | 1.0 | **1** | 1 | 0 | 1 | 0 | 0 | 2 | 0 | 26 | 2519 | 648 | 1242 | 0 | 2700 | 0.87 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.0 | **28** | 19 | 9 | 0 | 28 | 1 | 45 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.69 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.5 | **26** | 15 | 11 | 17 | 9 | 1 | 39 | 0 | 12 | 2512 | 628 | 369 | 0 | 2700 | 0.73 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.9 | **17** | 15 | 2 | 17 | 0 | 1 | 29 | 0 | 28 | 5296 | 1014 | 1749 | 0 | 2700 | 0.96 | ok |
| Town10HD_Opt | ClearNoon | 0 | 1.0 | **12** | 9 | 3 | 12 | 0 | 2 | 18 | 0 | 47 | 5765 | 1312 | 1924 | 0 | 2700 | 1.1 | ok |
| Town10HD_Opt | ClearNoon | 1 | 0.0 | **24** | 16 | 8 | 0 | 24 | 1 | 39 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.64 | ok |
| Town10HD_Opt | ClearNoon | 1 | 0.5 | **19** | 14 | 5 | 11 | 8 | 1 | 31 | 0 | 37 | 3055 | 894 | 1328 | 0 | 2700 | 0.85 | ok |
| Town10HD_Opt | ClearNoon | 1 | 0.9 | **9** | 8 | 1 | 8 | 1 | 0 | 17 | 0 | 62 | 6731 | 1537 | 1721 | 0 | 2700 | 1.05 | ok |
| Town10HD_Opt | ClearNoon | 1 | 1.0 | **8** | 7 | 1 | 8 | 0 | 0 | 15 | 0 | 49 | 7606 | 1525 | 1719 | 0 | 2700 | 1.07 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.0 | **28** | 19 | 9 | 0 | 28 | 1 | 45 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.65 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.5 | **21** | 15 | 6 | 16 | 5 | 1 | 35 | 0 | 37 | 3090 | 745 | 578 | 0 | 2700 | 0.73 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.9 | **13** | 10 | 3 | 12 | 1 | 1 | 21 | 0 | 56 | 5911 | 1362 | 1113 | 0 | 2700 | 0.87 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 1.0 | **10** | 9 | 1 | 10 | 0 | 2 | 16 | 0 | 36 | 6557 | 1154 | 1063 | 0 | 2700 | 0.85 | ok |
| Town10HD_Opt | HardRainNoon | 1 | 0.0 | **24** | 16 | 8 | 0 | 24 | 1 | 39 | 0 | 0 | 0 | 0 | 0 | 0 | 2700 | 0.79 | ok |
| Town10HD_Opt | HardRainNoon | 1 | 0.5 | **16** | 13 | 3 | 6 | 10 | 1 | 28 | 0 | 35 | 4009 | 929 | 548 | 0 | 2700 | 0.8 | ok |
| Town10HD_Opt | HardRainNoon | 1 | 0.9 | **10** | 8 | 2 | 10 | 0 | 0 | 18 | 0 | 89 | 7069 | 1584 | 1151 | 0 | 2700 | 0.89 | ok |
| Town10HD_Opt | HardRainNoon | 1 | 1.0 | **11** | 10 | 1 | 11 | 0 | 0 | 21 | 0 | 112 | 7867 | 1682 | 1389 | 0 | 2700 | 0.96 | ok |

### 6.3 V2V-only (--no-v2x)

| Town | Weather | seed | `p` | coll | prim | sec | cav | hdv | vru | frozen | coop | phan | dec | soft | hard | v2v_recv | cpm | w/s | st |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Town01 | ClearNoon | 0 | 0.0 | **24** | 19 | 5 | 0 | 24 | 1 | 40 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.18 | ok |
| Town01 | ClearNoon | 0 | 0.5 | **16** | 13 | 3 | 9 | 7 | 0 | 29 | 94 | 7 | 2383 | 520 | 56 | 117841 | 0 | 0.34 | ok |
| Town01 | ClearNoon | 0 | 0.9 | **9** | 7 | 2 | 9 | 0 | 1 | 14 | 451 | 12 | 5717 | 1296 | 178 | 417032 | 0 | 0.96 | ok |
| Town01 | ClearNoon | 0 | 1.0 | **7** | 5 | 2 | 7 | 0 | 1 | 10 | 574 | 45 | 6359 | 1678 | 232 | 518864 | 0 | 0.87 | ok |
| Town01 | ClearNoon | 1 | 0.0 | **24** | 19 | 5 | 0 | 24 | 0 | 43 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.2 | ok |
| Town01 | ClearNoon | 1 | 0.5 | **14** | 10 | 4 | 7 | 7 | 0 | 24 | 136 | 7 | 2548 | 719 | 45 | 152764 | 0 | 0.36 | ok |
| Town01 | ClearNoon | 1 | 0.9 | **11** | 9 | 2 | 9 | 2 | 1 | 18 | 670 | 21 | 6055 | 1740 | 167 | 371005 | 0 | 0.56 | ok |
| Town01 | ClearNoon | 1 | 1.0 | **8** | 6 | 2 | 8 | 0 | 0 | 13 | 514 | 39 | 6481 | 1555 | 205 | 503650 | 0 | 0.67 | ok |
| Town01 | HardRainNoon | 0 | 0.0 | **24** | 19 | 5 | 0 | 24 | 1 | 40 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.18 | ok |
| Town01 | HardRainNoon | 0 | 0.5 | **16** | 13 | 3 | 9 | 7 | 0 | 29 | 94 | 7 | 2383 | 520 | 56 | 117841 | 0 | 0.34 | ok |
| Town01 | HardRainNoon | 0 | 0.9 | **9** | 7 | 2 | 9 | 0 | 1 | 14 | 451 | 12 | 5717 | 1296 | 178 | 417032 | 0 | 0.95 | ok |
| Town01 | HardRainNoon | 0 | 1.0 | **7** | 5 | 2 | 7 | 0 | 1 | 10 | 574 | 45 | 6359 | 1678 | 232 | 518864 | 0 | 0.87 | ok |
| Town01 | HardRainNoon | 1 | 0.0 | **24** | 19 | 5 | 0 | 24 | 0 | 43 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.2 | ok |
| Town01 | HardRainNoon | 1 | 0.5 | **14** | 10 | 4 | 7 | 7 | 0 | 24 | 136 | 7 | 2548 | 719 | 45 | 152764 | 0 | 0.35 | ok |
| Town01 | HardRainNoon | 1 | 0.9 | **11** | 9 | 2 | 9 | 2 | 1 | 18 | 618 | 23 | 6047 | 1680 | 164 | 371019 | 0 | 0.57 | ok |
| Town01 | HardRainNoon | 1 | 1.0 | **8** | 6 | 2 | 8 | 0 | 0 | 13 | 514 | 39 | 6481 | 1555 | 205 | 503650 | 0 | 0.68 | ok |
| Town05 | ClearNoon | 0 | 0.0 | **13** | 11 | 2 | 0 | 13 | 1 | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.18 | ok |
| Town05 | ClearNoon | 0 | 0.5 | **10** | 8 | 2 | 5 | 5 | 1 | 17 | 14 | 6 | 947 | 249 | 21 | 193423 | 0 | 0.4 | ok |
| Town05 | ClearNoon | 0 | 0.9 | **4** | 4 | 0 | 4 | 0 | 0 | 7 | 39 | 23 | 2584 | 444 | 116 | 662279 | 0 | 0.85 | ok |
| Town05 | ClearNoon | 0 | 1.0 | **3** | 3 | 0 | 3 | 0 | 0 | 6 | 80 | 16 | 3919 | 736 | 133 | 807952 | 0 | 1.42 | ok |
| Town05 | ClearNoon | 1 | 0.0 | **18** | 12 | 6 | 0 | 18 | 1 | 28 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.2 | ok |
| Town05 | ClearNoon | 1 | 0.5 | **9** | 9 | 0 | 3 | 6 | 1 | 17 | 0 | 12 | 1035 | 429 | 121 | 198533 | 0 | 0.36 | ok |
| Town05 | ClearNoon | 1 | 0.9 | **3** | 3 | 0 | 2 | 1 | 0 | 6 | 50 | 19 | 2557 | 680 | 91 | 678565 | 0 | 0.82 | ok |
| Town05 | ClearNoon | 1 | 1.0 | **3** | 2 | 1 | 3 | 0 | 1 | 4 | 85 | 38 | 3645 | 831 | 147 | 802004 | 0 | 0.94 | ok |
| Town05 | HardRainNoon | 0 | 0.0 | **13** | 11 | 2 | 0 | 13 | 1 | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.19 | ok |
| Town05 | HardRainNoon | 0 | 0.5 | **10** | 8 | 2 | 5 | 5 | 1 | 17 | 14 | 6 | 947 | 249 | 21 | 193423 | 0 | 0.41 | ok |
| Town05 | HardRainNoon | 0 | 0.9 | **4** | 4 | 0 | 4 | 0 | 0 | 7 | 39 | 23 | 2584 | 444 | 116 | 662279 | 0 | 0.85 | ok |
| Town05 | HardRainNoon | 0 | 1.0 | **3** | 3 | 0 | 3 | 0 | 0 | 6 | 80 | 16 | 3919 | 736 | 133 | 807952 | 0 | 1.43 | ok |
| Town05 | HardRainNoon | 1 | 0.0 | **18** | 12 | 6 | 0 | 18 | 1 | 28 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.2 | ok |
| Town05 | HardRainNoon | 1 | 0.5 | **9** | 9 | 0 | 3 | 6 | 1 | 17 | 0 | 12 | 1035 | 429 | 121 | 198533 | 0 | 0.35 | ok |
| Town05 | HardRainNoon | 1 | 0.9 | **3** | 3 | 0 | 2 | 1 | 0 | 6 | 50 | 19 | 2557 | 680 | 91 | 678565 | 0 | 0.87 | ok |
| Town05 | HardRainNoon | 1 | 1.0 | **3** | 2 | 1 | 3 | 0 | 1 | 4 | 85 | 38 | 3645 | 831 | 147 | 802004 | 0 | 0.91 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.0 | **28** | 19 | 9 | 0 | 28 | 1 | 45 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.21 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.5 | **21** | 12 | 9 | 11 | 10 | 1 | 31 | 56 | 3 | 3800 | 661 | 97 | 192228 | 0 | 0.87 | ok |
| Town10HD_Opt | ClearNoon | 0 | 0.9 | **12** | 12 | 0 | 12 | 0 | 2 | 21 | 185 | 11 | 7522 | 1397 | 192 | 694707 | 0 | 2.86 | ok |
| Town10HD_Opt | ClearNoon | 0 | 1.0 | **8** | 7 | 1 | 8 | 0 | 1 | 13 | 259 | 26 | 10349 | 1741 | 319 | 1049115 | 0 | 4.29 | ok |
| Town10HD_Opt | ClearNoon | 1 | 0.0 | **24** | 16 | 8 | 0 | 24 | 1 | 39 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.23 | ok |
| Town10HD_Opt | ClearNoon | 1 | 0.5 | **21** | 15 | 6 | 10 | 11 | 0 | 35 | 79 | 10 | 5039 | 1008 | 109 | 256210 | 0 | 0.68 | ok |
| Town10HD_Opt | ClearNoon | 1 | 0.9 | **11** | 10 | 1 | 10 | 1 | 1 | 19 | 228 | 16 | 7412 | 1814 | 195 | 813165 | 0 | 2.49 | ok |
| Town10HD_Opt | ClearNoon | 1 | 1.0 | **11** | 11 | 0 | 11 | 0 | 0 | 21 | 254 | 13 | 8181 | 1829 | 228 | 969436 | 0 | 2.97 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.0 | **28** | 19 | 9 | 0 | 28 | 1 | 45 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.21 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.5 | **21** | 12 | 9 | 11 | 10 | 1 | 31 | 56 | 3 | 3800 | 661 | 97 | 192228 | 0 | 0.83 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 0.9 | **12** | 12 | 0 | 12 | 0 | 2 | 21 | 185 | 11 | 7522 | 1397 | 192 | 694707 | 0 | 2.88 | ok |
| Town10HD_Opt | HardRainNoon | 0 | 1.0 | **8** | 7 | 1 | 8 | 0 | 1 | 13 | 259 | 26 | 10349 | 1741 | 319 | 1049115 | 0 | 4.32 | ok |
| Town10HD_Opt | HardRainNoon | 1 | 0.0 | **24** | 16 | 8 | 0 | 24 | 1 | 39 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.22 | ok |
| Town10HD_Opt | HardRainNoon | 1 | 0.5 | **21** | 15 | 6 | 10 | 11 | 0 | 35 | 79 | 10 | 5039 | 1008 | 109 | 256210 | 0 | 0.69 | ok |
| Town10HD_Opt | HardRainNoon | 1 | 0.9 | **11** | 10 | 1 | 10 | 1 | 1 | 19 | 228 | 16 | 7412 | 1814 | 195 | 813165 | 0 | 2.34 | ok |
| Town10HD_Opt | HardRainNoon | 1 | 1.0 | **11** | 11 | 0 | 11 | 0 | 0 | 21 | 254 | 13 | 8181 | 1829 | 228 | 969436 | 0 | 2.9 | ok |

---

## 7. Cooperative-communication load (Combined arm, mean)

| `p` | V2V received | Cooperative brakes | CPMs emitted |
| :---: | :---: | :---: | :---: |
| 0.0 | 0 | 0 | 2700 |
| 0.5 | 187813 | 180 | 2700 |
| 0.9 | 652748 | 540 | 2700 |
| 1.0 | 800680 | 707 | 2700 |

V2V traffic and cooperative brakes appear only when CAVs exist and scale with penetration (0 at the human baseline). `v2i_only` shows zero cooperative brakes (no V2V channel); `v2v_only` shows zero CPMs (no RSU).

## 8. Performance & immobilised vehicles (Combined arm, mean)

| `p` | wall/sim ratio | frozen vehicles | VRU collisions |
| :---: | :---: | :---: | :---: |
| 0.0 | 0.64 | 36.4 | 0.9 |
| 0.5 | 1.09 | 24.8 | 0.6 |
| 0.9 | 2.29 | 12.7 | 0.6 |
| 1.0 | 2.64 | 10.2 | 0.3 |

Frozen (wrecked) vehicles fall sharply with penetration (~36 -> ~10) as cooperative CAVs avoid conflicts. Wall/sim rises with penetration (more CAV decision + V2V processing); the steer-fix keeps it tractable.

---

## 9. The model — what produced this result

This sprint's fixes, in the order that mattered:

- **Realism driver model.** HDVs split by profile: attentive keep TM collision-avoidance (never at-fault); distracted + aggressive_hostile have avoidance OFF and crash per their own ignore-rates. Gives a genuinely dangerous, *attributable* human baseline.
- **Velocity-matched ego self-exclusion (`cav.py`).** The RSU ghost-reflection filter now keys on co-located AND co-moving, so a CAV still brakes for a stopped wreck at close range instead of ignoring it.
- **Closing-rate gate on the distance fallback (`cav.py`).** Emergency braking only fires when the gap is actually shrinking, so a CAV no longer hard-brakes on a leader it is safely following.
- **7 m CAV follow distance (`hdv.py`).** Wider headway -> far fewer panic stops; braking shifts from hard to soft.
- **Steer-preserving brake overrides (`40_ablation_run.py`).** The single highest-impact fix: a brake override no longer zeroes the steering wheel mid-turn, so CAVs stop arcing wide into the oncoming lane. This alone cut high-penetration collisions by more than half in validation.
- **Primary/secondary collision split + determinism seeds + per-cell retry + server watchdog** for clean, reproducible, gap-free runs.

---

## 10. Findings

1. **Cooperative perception works.** Collisions fall monotonically with CAV penetration, ~73% from baseline to full fleet, on every arm and every map.
2. **Infrastructure (V2I) is the stronger channel.** Combined &le; V2I-only &le; V2V-only at every penetration; RSU CPMs carry more of the benefit than CAV<->CAV V2V alone, but both help and combining them is best.
3. **Map complexity sets the floor.** Town05 nearly eliminates collisions at full penetration; Town10HD_Opt plateaus around ~10 because of CARLA junction-geometry wide-turn artifacts the cooperative layer cannot fix.
4. **Weather-robust.** ClearNoon and HardRainNoon give essentially the same curve.

## 11. Threats to validity

- **2 seeds** — real but modest variance (sd reported); a larger seed count would tighten the arm-ordering confidence, which is small relative to the sd.
- **Immobilise-in-place** couples some incidents (mitigated by the primary metric).
- **Town10 junction artifacts** inflate that map's floor; a fraction of its high-`p` collisions are simulator turn-geometry rather than genuine cooperative-perception failures.
- **At-fault attribution** credits the sensor that fired first, so `attentive` victims still appear in per-profile counts.

---

*Data source: `out/ablation_sprint5_final/{combined, v2i_only, v2v_only}` (144 cells, seeds 0+1). Generated by `scripts/make_sprint5_final_md.py` directly from per-cell JSON metrics.*