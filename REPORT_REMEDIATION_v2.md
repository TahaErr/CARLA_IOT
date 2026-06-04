# Section Updates — for the FINAL_REPORT (Taha v2)

Your v2 was cross-checked against the raw logs in `out/`. **It is verified-correct,
including the fixes your agent made independently — keep all of it as is.** There is
**one substantive addition** left (a remediation table the team wants), plus one
optional cosmetic change. Details below, paste-ready.

---

## What your v2 already got right — DO NOT change these
Re-verified against `out/ablation_full` and `out/ablation_sprint5_final`:

- Table 7 totals **1180±187 / 1141±207 / 1138±181** — correct.
- Table 7 VRU column **2.07 / 1.82 / 1.93** (fleet) — correct (matches hdv-hit+cav-hit).
- Table 7 phantom **0 / ~48 / ~95** — correct.
- Saturation **~3.6%** — correct.
- ClearSunset **+7.7% (Town05) / +3.3% (all-map)** — correct.
- **Cell duration 120 s** — correct (an earlier instruction said 300 s; that was wrong, your 120 s is right).
- "Raw undeduplicated contact-event count ≈21,000/cell" — correct (actual mean ≈21,833 on Town05 baseline).
- Comparability note, idealized-localization threats bullet — good, keep.

Section 5 (the entire 144-cell main result), CBR, phantom, per-profile, detector
metrics, CMP 764, and authors are all verified-correct — do not touch.

---

## ADD 1 (required) — the "Framework Evolution" remediation table
The team wants the report to explicitly show *what was found in the earlier
configuration and how it was remediated* (spawn-overlap fix, freeze/immobilize,
incident deduplication, steering-preserving brake override, role-selective driver
model, determinism, retry). Your prose mentions a few of these in the
density-saturation paragraph, but a compact table makes the contribution visible.

**Where:** in `\section{... earlier configuration ...}` (`sec:additional`), right after
the opening paragraph, before the "A note on comparability." paragraph.

**Also add one sentence to the §6 opening paragraph** so the table is referenced — e.g.
append to it:
```latex
The issues that motivated the framework's evolution from that configuration to the
present one are summarized in Table~\ref{tab:remediation}.
```

**Then insert this table:**
```latex
\begin{table}[t]
  \centering
  \caption{Issues identified in the earlier configuration and the remediations
  applied in the present framework. Several remediations also change how collisions
  are \emph{counted}, which is why the magnitudes in this section are not comparable
  to those in Section~5.}
  \label{tab:remediation}
  \small
  \begin{tabular}{p{0.29\linewidth} p{0.31\linewidth} p{0.32\linewidth}}
    \toprule
    Issue & Symptom & Remediation \\
    \midrule
    Overlapping spawns & Vehicles materialized inside one another, causing
      spawn-instant collisions & Minimum-separation spawn sampling ($\geq 6$\,m
      pairwise) with non-forcing \texttt{try\_spawn} \\
    Runaway collision counter & Per-contact counting inflated totals; grinding
      vehicles kept re-firing the collision sensor & One deduplicated incident per
      unordered pair, plus immobilize-in-place (brake $+$ handbrake $+$ frozen
      physics) so wrecks stop re-triggering \\
    Inverted safety curve at high penetration & Collisions \emph{rose} with CAV
      share & Velocity-matched ego self-exclusion; closing-rate gate on the distance
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
*(The `p{...\linewidth}` columns are valid 3-column rows; pdfLaTeX compiles them fine
even if a naive linter flags the spec.)*

---

## ADD 2 (optional, cosmetic) — retitle §6
To signal the "what we found → how we fixed it" narrative, change:
```latex
\section{Additional Sensitivity Findings (earlier configuration)}
```
to:
```latex
\section{Framework Evolution and Earlier Sensitivity Findings}
```
(Keep the existing `\label{sec:additional}` line unchanged so all `\ref`s still resolve.)

---

That's the only outstanding item. With the remediation table added, the report fully
reflects the team's "issues found and remediated" story and is data-consistent end to
end. Make sure `\ref{tab:remediation}` is referenced in the §6 prose (the sentence in
ADD 1) so the label is used.
