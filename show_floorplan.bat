@echo off
rem Opens the routed design in the Vivado GUI with the four Pblocks (physical partitions) highlighted.
cd /d "%~dp0"
start "" "C:\AMDDesignTools\2026.1\Vivado\bin\vivado.bat" -mode gui -source hardware\vivado\show_floorplan.tcl
