@echo off
rem Opens the Vivado project of the health monitor (healthy design, four Pblocks) in the Vivado GUI.
rem Then in Flow Navigator choose "Open Implemented Design" and look at the Device window.
rem (Vivado's launcher does not accept a project file as an argument on Windows, so the project is opened
rem  by a small Tcl script instead.)
cd /d "%~dp0"
if not exist "C:\vivado_projects\fpga_health_project\fpga_health_project.xpr" (
    echo The project is not generated yet. Run:  vivado -mode batch -source hardware\vivado\refresh_project.tcl
    pause
    exit /b 1
)
start "" "C:\AMDDesignTools\2026.1\Vivado\bin\vivado.bat" -mode gui -source hardware\vivado\open_project.tcl
