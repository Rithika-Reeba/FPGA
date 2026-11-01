@echo off
rem Opens the routed design in the Vivado GUI with the four Pblocks (physical partitions) highlighted.
cd /d "%~dp0"
rem Vivado runs the simulation by starting compile.bat by name from its folder; that fails if this variable is set.
set NoDefaultCurrentDirectoryInExePath=
start "" "C:\AMDDesignTools\2026.1\Vivado\bin\vivado.bat" -mode gui -source hardware\vivado\show_floorplan.tcl
