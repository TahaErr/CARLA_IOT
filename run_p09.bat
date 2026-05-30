@echo off
REM run_p09.bat — Fleet-transition p=0.9 sweep (45 cells, ~1.5 hours wall time).
REM
REM Pre-requisites:
REM   1. CarlaUE4.exe running at quality-level=Epic (start it first, separate terminal).
REM   2. apply_patches.py already run successfully (40_ablation_run.py must support --cav-attentive).
REM
REM Skip-existing: re-running this script after a crash will resume from
REM where it left off; only missing cells are run.
REM
REM Run from repo root:   .\run_p09.bat

setlocal enabledelayedexpansion
set DETECTOR=runs\detect\runs\detect\yolo26s_carla_multi-2\weights\best.pt
set OUTDIR=out\ablation_p09
if not exist "%OUTDIR%" mkdir "%OUTDIR%"
if not exist "%OUTDIR%\logs" mkdir "%OUTDIR%\logs"

if not exist "%DETECTOR%" (
  echo FAIL: detector not found: %DETECTOR%
  exit /b 1
)

set TOTAL=0
set DONE=0
set CRASHED=0
set SKIPPED=0

REM Count total cells: 3 maps x 3 weathers x 5 seeds = 45
for %%M in (Town05 Town10HD_Opt Town01) do (
  for %%W in (ClearNoon ClearSunset HardRainNoon) do (
    for %%S in (0 1 2 3 4) do (
      set /a TOTAL=!TOTAL!+1
    )
  )
)

echo === Fleet-transition sweep ===
echo   detector:    %DETECTOR%
echo   out-dir:     %OUTDIR%
echo   cells:       !TOTAL!
echo   penetration: 0.9 (CAV=ATTENTIVE, HDV=HOSTILE_MIX)
echo   walkers:     60
echo.

for %%M in (Town05 Town10HD_Opt Town01) do (
  for %%W in (ClearNoon ClearSunset HardRainNoon) do (
    for %%S in (0 1 2 3 4) do (
      set /a DONE=!DONE!+1
      set OUT=%OUTDIR%\p090_w060_%%W_%%M_s0%%S.json
      set LOG=%OUTDIR%\logs\p090_w060_%%W_%%M_s0%%S.log

      if exist "!OUT!" (
        echo [!DONE!/!TOTAL!] SKIP existing: !OUT!
        set /a SKIPPED=!SKIPPED!+1
      ) else (
        echo [!DONE!/!TOTAL!] Running map=%%M weather=%%W seed=%%S
        python scripts\40_ablation_run.py ^
          --detector %DETECTOR% ^
          --map %%M --weather %%W ^
          --penetration 0.9 --seed %%S ^
          --n-vehicles 60 --n-walkers 60 ^
          --cav-attentive ^
          --out "!OUT!" ^
          --quiet > "!LOG!" 2>&1

        if errorlevel 1 (
          echo    CRASHED  see !LOG!
          set /a CRASHED=!CRASHED!+1
        ) else (
          echo    ok       log: !LOG!
        )
      )
    )
  )
)

echo.
echo === Sweep complete ===
echo   total:    !TOTAL!
echo   ok:       (run count - crashed - skipped)
echo   crashed:  !CRASHED!
echo   skipped:  !SKIPPED!
echo.
echo Next: python scripts\41_ablation_aggregate.py --in-dir %OUTDIR%

endlocal
