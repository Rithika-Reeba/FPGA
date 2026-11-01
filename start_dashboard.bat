@echo off
rem Starts the FPGA health dashboard as the only instance (a copy already running is closed first).
rem The board does not have to be plugged in: without one the dashboard still works (mock / simulation).
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo The Python environment "venv" is missing. See START_HERE.md, section "First time on a new laptop".
    pause
    exit /b 1
)
venv\Scripts\python.exe run_dashboard.py
echo.
echo The dashboard has stopped. If it failed to start, read the message above.
pause
