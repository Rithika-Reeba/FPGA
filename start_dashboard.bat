@echo off
rem Starts the FPGA health dashboard. Double-click this file, or run it from a terminal.
rem The board does not have to be plugged in: without one the dashboard still works (mock / simulation).
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo The Python environment "venv" is missing. See START_HERE.md, section "First time on a new laptop".
    pause
    exit /b 1
)
echo Starting the dashboard on http://localhost:8511 ...
echo (The first page can take about 20 seconds: it reads the board first.)
echo Press Ctrl+C in this window to stop it.
venv\Scripts\python.exe -m streamlit run dashboard/app.py --server.port 8511 --server.address localhost
echo.
echo The dashboard has stopped. If it failed to start, read the message above (a copy may already be running on port 8511).
pause
