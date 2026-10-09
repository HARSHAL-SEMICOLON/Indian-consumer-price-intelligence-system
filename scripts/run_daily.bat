@echo off
REM Daily price collection - called by Windows Task Scheduler (see scripts\setup_daily_task.bat).
REM Collects a new snapshot, loads only what is new, re-runs data quality, analysis and the Power BI export.

cd /d "%~dp0.."
if not exist logs mkdir logs

REM Find Python: PATH first, then the usual Anaconda / Python install locations.
set "PY="
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY set "PY=%%P"
if not defined PY if exist "%USERPROFILE%\anaconda3\python.exe" set "PY=%USERPROFILE%\anaconda3\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY (
    echo [%date% %time%] Python not found >> logs\daily_collection.log
    exit /b 1
)

echo. >> logs\daily_collection.log
echo ===== %date% %time% ===== >> logs\daily_collection.log
"%PY%" run_pipeline.py --extract >> logs\daily_collection.log 2>&1
echo exit code %errorlevel% >> logs\daily_collection.log
