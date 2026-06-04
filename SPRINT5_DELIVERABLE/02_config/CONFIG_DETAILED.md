# Detailed Configuration

## Driver profiles (CARLA Traffic Manager parameters)

| Profile | speed Δ% | follow gap (m) | ignore lights | ignore signs | ignore veh | ignore walkers | lane-change % | TM avoidance |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| attentive | 0 | 2.5 | 0% | 0% | 0% | 0% | 0% | **ON** |
| distracted | -10 | 2.0 | 5% | 10% | 20% | 10% | 2% | **OFF** |
| aggressive_hostile | +25 | 2.0 | 50% | 60% | 40% | 20% | 25% | **OFF** |
| AI_REALISTIC (CAV) | 0 | **7.0** | 1% | 1% | 0% | 0% | 0.5% | ON |

**Role model:** attentive HDVs keep TM collision-avoidance (so they are never the at-fault party); distracted + aggressive_hostile run with avoidance OFF, so each profile's own ignore-rate sets the conflict gradient. CAVs keep avoidance ON plus the cooperative-perception decision layer.

## CAV decision layer (`v2xsim/cav.py`)

- Time-aware late fusion of RSU CPMs + own local sensor; confirmation hysteresis (2 consecutive CPMs, or 2 distinct RSUs in 500 ms, or local-sensor confirm) to suppress phantom brakes.
- TTC ladder: HARD_BRAKE ≤1.0 s, SOFT_BRAKE ≤2.5 s, DECELERATE ≤4.0 s (min-confidence gated).
- Distance-based safety fallback (confirmed in-lane track) with a **closing-rate gate** (only fires when the gap is shrinking ≥0.5 m/s).
- **Velocity-matched ego self-exclusion** (drops only the RSU ghost of the CAV's own body).
- V2V cooperative brake-warning ingestion (DENM-style hard-brake intent from a leader ahead).

## Runner behaviour (`scripts/40_ablation_run.py`)

- Collisions deduplicated to one incident per unordered pair; colliding vehicles immobilised in place (no runaway counter / interpenetration).
- **Primary vs secondary** split: a new pair where one party was already wrecked is tagged secondary (pileup into a wreck), so the headline metric isn't inflated.
- **Steer-preserving brake overrides**: a brake override keeps the TM's current steering (does not zero the wheel mid-turn), preventing CAVs from arcing wide on corners.
- Determinism seeds (TM + pedestrians) from the cell seed; per-cell retry ×2; server watchdog.

## Communication stack

- RSUs run YOLO (detector `yolo26s_carla_multi`) → Collective Perception Messages (CPM).
- In-process Broker applies PDR (packet-drop), latency, and channel-busy-ratio models to both the RSU→CAV (V2I) and CAV↔CAV (V2V) paths.
- Arms toggle the channels: `--no-v2v` (V2I-only), `--no-v2x` (V2V-only).