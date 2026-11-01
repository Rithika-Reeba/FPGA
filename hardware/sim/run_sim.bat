@echo off
rem Runs the RTL testbench (hardware/sim/tb_fpga_health_top.v) with Vivado's command-line simulator and prints
rem PASS or FAIL. Use this when "Run Simulation" inside the Vivado window fails. It leaves your project untouched.
setlocal
set NoDefaultCurrentDirectoryInExePath=
set VBIN=C:\AMDDesignTools\2026.1\Vivado\bin
if defined VIVADO_BIN set VBIN=%VIVADO_BIN%
set SRC=%~dp0..\rtl
set SIMDIR=%TEMP%\fpga_health_sim
if not exist "%SIMDIR%" mkdir "%SIMDIR%"
pushd "%SIMDIR%"
set FILES=
for %%f in ("%SRC%\*.v") do call set FILES=%%FILES%% "%%~f"
echo Compiling the design and the testbench ...
call "%VBIN%\xvlog.bat" -d SIMULATION %FILES% "%~dp0tb_fpga_health_top.v" > compile.txt 2>&1
if errorlevel 1 ( type compile.txt & echo. & echo FAIL: compile error & popd & exit /b 1 )
echo Elaborating ...
call "%VBIN%\xelab.bat" -debug typical tb_fpga_health_top -s tbsim > elab.txt 2>&1
if errorlevel 1 ( type elab.txt & echo. & echo FAIL: elaboration error & popd & exit /b 1 )
echo Running the simulation (about a minute) ...
call "%VBIN%\xsim.bat" tbsim -runall > run.txt 2>&1
findstr /C:"FAIL" /C:"TESTS FAILED" run.txt
findstr /C:"ALL TESTS PASSED" run.txt >nul
if errorlevel 1 ( echo. & echo RESULT: FAIL - see %SIMDIR%\run.txt & popd & exit /b 1 )
echo.
echo RESULT: PASS - all testbench checks passed
popd
exit /b 0
