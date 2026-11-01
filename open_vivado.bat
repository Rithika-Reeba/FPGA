@echo off
rem Opens the Vivado project of the health monitor (healthy design, four Pblocks) in the Vivado GUI.
rem In Flow Navigator choose "Open Implemented Design", then look at the Device window.
set PROJ=%~dp0vivado_project\fpga_health_project.xpr
if not exist "%PROJ%" (
    echo The project is not generated yet. Run:  vivado -mode batch -source hardware\vivado\refresh_project.tcl
    pause
    exit /b 1
)
start "" "C:\AMDDesignTools\2026.1\Vivado\bin\vivado.bat" "%PROJ%"
