# ==============================================================================
# Vivado Implementation Pre-Place Hook Script (project flow)
# Purpose: apply the four-region floorplan (hard Pblocks + pinned ring oscillators) - the SAME Tcl
#          the batch build uses. (The old four_region_floorplan.xdc had no oscillator pinning.)
# ==============================================================================
source [file join [file dirname [file normalize [info script]]] .. four_region_floorplan.tcl]