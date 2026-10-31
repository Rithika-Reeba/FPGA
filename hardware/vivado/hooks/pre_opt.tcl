# ==============================================================================
# Vivado Implementation Pre-Opt Hook Script (project flow)
# Target: Digilent Basys 3 (XC7A35T)
# Purpose: ring-oscillator constraints (allowed loops, RO clocks) - the SAME script the batch
#          build uses, so the two flows cannot disagree.
# ==============================================================================
source [file join [file dirname [file normalize [info script]]] .. ro_constraints.tcl]