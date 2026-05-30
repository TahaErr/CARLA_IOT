@echo off
REM ============================================================
REM Smoke test 2 — walker spawn validation
REM
REM Runs a 20-second cell with p=0.5 (half CAVs) and 20 walkers.
REM This is the smallest run that exercises the full VRU pipeline:
REM walker spawn, post-warmup AI start, walker-on-CAV CPM inclusion,
REM VRU collision metric classification, in-sync walker cleanup.
REM
REM Visual check (in the CARLA viewport):
REM   - Walkers should be WALKING, not frozen in T-pose
REM   - Walkers near intersections, within RSU camera framing
REM   - Vehicles still flowing through intersections
REM
REM Output check (console):
REM   - "wrote out\ablation\walker_smoke.json"
REM   - "collisions: N (cav=X hdv=Y)"
REM   - "VRU collisions: K (cav-hit=A hdv-hit=B)"  <-- proves VRU axis works
REM   - "actions taken: {...hard_brake: M}"        <-- CAV reacting
REM
REM If the VRU collisions line is missing -> walker axis not wired up.
REM If walkers are frozen in T-pose -> AI controllers didn't start.
REM ============================================================
echo === Smoke test 2: walker spawn + VRU pipeline (20s, p=0.5, n_walkers=20) ===
echo.

if not exist runs\detect\runs\detect\yolo26s_carla_multi-2\weights\best.pt (
    echo FAIL: detector weights not found at expected path.
    pause
    exit /b 1
)

python scripts\40_ablation_run.py ^
    --detector runs\detect\runs\detect\yolo26s_carla_multi-2\weights\best.pt ^
    --penetration 0.5 ^
    --seed 0 ^
    --duration 20 ^
    --n-walkers 20 ^
    --out out\ablation\walker_smoke.json

if errorlevel 1 (
    echo.
    echo === FAIL ===
    echo If you saw a "time-out of 20000ms" error, CARLA is not running.
    echo If you saw a traceback, share the log content with Claude.
    pause
    exit /b 1
)

echo.
echo === PASS — walker pipeline working ===
echo.
echo Visual verification (look at the CARLA viewport BEFORE closing):
echo   1. Did you see walkers WALKING (not frozen in T-pose)?
echo   2. Were walkers near the 3 intersections (0, 3, 7)?
echo   3. Did any walkers interact with vehicles?
echo.
echo If all yes: ready for the full 30-cell sweep:
echo     python scripts\42_ablation_sweep_subprocess.py ^
echo         --detector runs\detect\runs\detect\yolo26s_carla_multi-2\weights\best.pt ^
echo         --out-dir out\ablation --walker-counts 0,20
echo.
pause
