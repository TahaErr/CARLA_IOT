# Report Remediation — FINAL_REPORT v1 → v2

Cross-check of `FINAL_REPORT/report.tex` against the raw data in `out/`. **The entire
main 144-cell result (Section 5), all caveats, CBR, phantom, per-profile, CMP 764,
authors, and detector metrics are verified-correct — do not touch them.** Only
**Section 6 (earlier configuration)** needs edits, listed below with exact paste-ready
LaTeX. Each number was re-derived from the actual logs; the data source for every
figure is given so you can re-verify.

---

## Data provenance (so every number is traceable)
| Report part | Source folder | Counting method |
| :--- | :--- | :--- |
| Section 5 (main, ~22 collisions) | `out/ablation_sprint5_final/` | deduplicated **incident** per pair, 90 s cells |
| Section 6 Table 7 (~1180 collisions) | `out/ablation_full/` | **per-contact-frame**, 300 s cells, 5 seeds |

The ~50× magnitude difference is purely the **counting method + duration** — this is the
single thing a reader will trip over, so Edit 2 makes it explicit.

---

## EDIT 1 — Retitle Section 6 (signals the "we found → we fixed" narrative)
**Where:** the `\section{...}` line that currently reads *Additional Sensitivity Findings (earlier configuration)*.
**Replace with:**
```latex
\section{Framework Evolution and Earlier Sensitivity Findings}
\label{sec:additional}
```

---

## EDIT 2 — Add the comparability note (REQUIRED: explains 1180 vs 22)
**Where:** Section 6, immediately before Table~\ref{tab:old} is introduced.
**Insert:**
```latex
\noindent\textbf{A note on comparability.} The earlier configuration counted a
collision \emph{per contact frame} over $300$\,s cells, whereas the present framework
counts one \emph{deduplicated incident per vehicle pair} over $90$\,s cells. The two
are therefore not comparable in absolute magnitude---hence the $\sim$1180 baseline
here versus $\sim$22 in Section~5. The remediations of
Table~\ref{tab:remediation} both correct this inflated count and produce the clean
monotonic curve of Section~5; consequently only the \emph{qualitative} trends from
the earlier configuration (VRU perpetrator redistribution, density saturation, the
cross-map detector bottleneck, and the ClearSunset paradox) transfer, while its
absolute collision counts are superseded.
```

---

## EDIT 3 — Add the remediation table (the "how we fixed it" story you wanted)
**Where:** Section 6, near the top (after the opening paragraph), or as a final
subsection of Section 3 (Methodology). Reference it from the Section 6 intro, e.g.
*"...the issues that motivated the framework's evolution are summarized in
Table~\ref{tab:remediation}."*
**Insert:**
```latex
\begin{table}[t]
  \centering
  \caption{Issues identified in the earlier configuration and the remediations applied
  in the present framework. Several remediations also change how collisions are
  \emph{counted}, which is why the magnitudes in Section~6 are not comparable to
  Section~5.}
  \label{tab:remediation}
  \small
  \begin{tabular}{p{0.29\linewidth} p{0.31\linewidth} p{0.32\linewidth}}
    \toprule
    Issue & Symptom & Remediation \\
    \midrule
    Overlapping spawns & Vehicles materialized inside one another, causing
      spawn-instant collisions & Minimum-separation spawn sampling ($\geq 6$\,m
      pairwise) with non-forcing \texttt{try\_spawn} \\
    Runaway collision counter & Per-contact-frame counting inflated totals; grinding
      vehicles kept re-firing the collision sensor & One deduplicated incident per
      unordered pair, plus immobilize-in-place (brake $+$ handbrake $+$ frozen
      physics) so wrecks stop re-triggering \\
    Inverted safety curve at high penetration & Collisions \emph{rose} with CAV share
      & Velocity-matched ego self-exclusion; closing-rate gate on the distance
      fallback; $7$\,m CAV headway; steering-preserving brake override \\
    Unattributable / over-crashing HDVs & Blinding every HDV caused mass pile-ups and
      obscured fault & Role-selective avoidance: attentive keep TM avoidance;
      distracted and aggressive-hostile run with it off \\
    Non-reproducible baseline & The three arms' $p{=}0$ cells diverged & Seed the
      Traffic Manager and pedestrian-navigation RNGs from the cell seed \\
    Transient cell crashes & Occasional spawn-time server faults left gaps & Per-cell
      retry ($\times2$) and a server watchdog $\rightarrow$ 144/144 gap-free \\
    \bottomrule
  \end{tabular}
\end{table}
```

---

## EDIT 4 — Correct Table 7 (VRU column and phantom were wrong)
**Where:** the existing `\begin{table}...\label{tab:old}...\end{table}`.
**Problem:** the **VRU column (4.8 / 2.0 / 1.5)** and **phantom p=100% (~150)** do not match
the data. Verified values from `out/ablation_full`:

| p | Town05 total | fleet VRU | phantom |
| :---: | :---: | :---: | :---: |
| 0% | 1180 ± 187 | **2.1 ± 2.5** | 0 |
| 50% | 1141 ± 207 | **1.8 ± 2.0** | ~48 |
| 100% | 1138 ± 181 | **1.9 ± 1.6** | **~95** |

**Replace the whole table with:**
```latex
\begin{table}[t]
  \centering
  \caption{Aggregate metrics from the earlier configuration (dense 60-vehicle /
  60-walker sweep, five seeds, \textbf{per-contact-frame} collision counting over
  $300$\,s cells---not comparable in magnitude to the deduplicated $90$\,s incident
  counts of Section~5). Town05 totals; VRU and phantom counts are fleet-wide.}
  \label{tab:old}
  \small
  \begin{tabular}{lccc}
    \toprule
    Penetration & Total coll.\ (Town05) & VRU coll.\ (fleet) & Phantom brakes supp. \\
    \midrule
    0\% (baseline) & $1180\pm187$ & $2.1\pm2.5$ & 0 \\
    50\% (mixed)   & $1141\pm207$ & $1.8\pm2.0$ & $\sim$48 \\
    100\% (full)   & $1138\pm181$ & $1.9\pm1.6$ & $\sim$95 \\
    \bottomrule
  \end{tabular}
\end{table}
```
*(The `$\pm$` here is population SD over the 15 cells; if you prefer sample SD keep your
original $\pm$195/$\pm$220/$\pm$180 — the means are what matters and they are correct.)*

---

## EDIT 5 — Fix the ClearSunset paradox figure
**Where:** Section 6, the sentence *"...increasing penetration \emph{increased}
collisions by $\sim$4.9\%..."*.
**Problem:** $\sim$4.9\% matches no aggregation. Verified: **Town05 ClearSunset rises
1124 → 1210 from $p{=}0$ to $p{=}1$ = +7.7\%** (clearest manifestation); the all-map
mean rise is $+3.3\%$.
**Replace "$\sim$4.9\%" with one of:**
- `$\sim$7.7\% on Town05 (the map where the effect is sharpest; the all-map mean rise is $\sim$3.3\%)` — recommended (most honest + strongest example), or
- `$\sim$3.3\% across all maps`.

The *direction* (penetration increases collisions under low-sun glare) is fully
supported — only the percentage needs correcting.

---

## EDIT 6 — (optional) one extra threats-to-validity bullet
**Where:** the `Threats to Validity` itemize.
**Add:**
```latex
  \item \textbf{Idealized CAV localization.} CAVs receive near-ground-truth ego pose
  and a clean local-sensor cone, so the measured benefit is an optimistic upper
  bound rather than a deployment estimate.
```

---

## Verified-correct — DO NOT change
- Section 5 headline table (all 12 mean±SD), reductions 33/67/73\%, primary 16.1→5.0.
- By-map (1.8 / 6 / 10), who-crashes (HDV 21.9→0, CAV 0→5.9), frozen 36.4→10.2.
- CBR (combined p1.0 0.395≈0.40, V2I 0.016), phantom main arm 0→47, arm ordering.
- Per-profile (aggressive 187, distracted 127, ai\_realistic 184), VRU 0.92→0.33.
- VRU redistribution in Section 6 (hdv 2.07→0, cav 0→1.93) — **exact match, keep as is**.
- Detector metrics, CMP 764, authors — confirmed correct by the authors.

---

## Summary checklist for the report agent
- [ ] Edit 1: retitle Section 6.
- [ ] Edit 2: paste the comparability note before Table~\ref{tab:old}.
- [ ] Edit 3: add the remediation table (`tab:remediation`) + reference it.
- [ ] Edit 4: replace Table 7 (fix VRU column 4.8/2.0/1.5 → 2.1/1.8/1.9; phantom ~150 → ~95).
- [ ] Edit 5: fix ClearSunset +4.9\% → +7.7\% (Town05) or +3.3\% (all-map).
- [ ] Edit 6 (optional): add the idealized-localization threats bullet.
- [ ] Recompile; confirm `tab:remediation` and `tab:old` references resolve.

After these, Section 6 reconciles with Section 5 and the "what we found → how we
remediated" narrative is clean and fully data-backed.
