@echo off
REM One-time setup: registers a Windows scheduled task that runs the collection every day at 11:00.
REM Double-click this file (no admin rights needed). Check it in Task Scheduler -> "ConsumerPriceDaily".
REM DoCA publishes the previous day's All-India prices by morning, so 11:00 picks up a fresh day.

schtasks /Create /F /SC DAILY /ST 11:00 /TN "ConsumerPriceDaily" /TR "\"%~dp0run_daily.bat\""
if %errorlevel%==0 (
    echo.
    echo Scheduled: ConsumerPriceDaily runs every day at 11:00.
    echo Run it now once to test:  schtasks /Run /TN "ConsumerPriceDaily"
    echo Log file: %~dp0..\logs\daily_collection.log
) else (
    echo Could not create the task. Try running this file as administrator.
)
pause
