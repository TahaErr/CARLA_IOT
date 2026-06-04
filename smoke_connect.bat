@echo off
REM ============================================================
REM Smoke test 1 — CARLA connection check
REM
REM Runs a 10-second vehicle-only ablation cell to verify the
REM CARLA server is reachable and the runner pipeline works.
REM No walkers, smallest possible footprint.
REM
REM PASS:  console prints "wrote out\ablation\connect_test.json"
REM FAIL:  "time-out of 20000ms" -> CARLA server not running.
REM        Start it with: cd C:\path\to\CARLA_0.9.16 && CarlaUE4.exe -quality-level=Low
REM ============================================================
echo === Smoke test 1: CARLA connection check (10s, no walkers) ===
echo.

if not exist runs\detect\runs\detect\yolo26s_carla_multi-2\weights\best.pt (
    echo FAIL: detector weights not found at expected path.
    echo Looking for: runs\detect\runs\detect\yolo26s_carla_multi-2\weights\best.pt
    pause
    exit /b 1
)

python scripts\40_ablation_run.py ^
    --detector runs\detect\runs\detect\yolo26s_carla_multi-2\weights\best.pt ^
    --penetration 0.0 ^
    --seed 0 ^
    --duration 10 ^
    --n-walkers 0 ^
    --out out\ablation\connect_test.json

if errorlevel 1 (
    echo.
    echo === FAIL ===
    echo If you saw a "time-out of 20000ms" error, CARLA is not running.
    echo Start it in another terminal:
    echo     cd C:\Users\TAHA\Desktop\CARLA_0.9.16
    echo     CarlaUE4.exe -quality-level=Low
    echo Then wait until the main menu appears and try again.
    pause
    exit /b 1
)

echo.
echo === PASS — CARLA connection OK ===
echo Next: run smoke_walker.bat to verify the walker pipeline.
pause
