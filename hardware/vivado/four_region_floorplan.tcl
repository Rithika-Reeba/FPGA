# ==============================================================================
# Four-Region Physical Health Floorplan for Digilent Basys 3 (xc7a35tcpg236-1)
# ==============================================================================
# Physical 2x2 Layout:
#   R1 (Northwest): CLOCKREGION_X0Y2 -> SLICE_X0Y100:SLICE_X35Y149
#   R2 (Northeast): CLOCKREGION_X1Y2 -> SLICE_X36Y100:SLICE_X57Y149
#   R3 (Southwest): CLOCKREGION_X0Y0 -> SLICE_X0Y0:SLICE_X35Y49
#   R4 (Southeast): CLOCKREGION_X1Y0 -> SLICE_X36Y0:SLICE_X65Y49
#
# Non-Regional / Global Logic (outside all Pblocks):
#   - XADC_X0Y0 in CLOCKREGION_X0Y1 (Midwest)
#   - Global Clock Buffers (BUFGCTRL) in CLOCKREGION_X0Y1 / X1Y1
#   - UART TX, packet formatter, error rate monitor, reset logic
# ==============================================================================

proc create_regional_pblock {pb_name cell_pattern slice_range} {
    puts "--> Configuring Pblock '$pb_name' for pattern '$cell_pattern' in range '$slice_range'..."
    
    # 1. Locate regional monitor cells in synthesized netlist
    set target_cells [get_cells -hierarchical -filter "NAME =~ *$cell_pattern*"]
    if {[llength $target_cells] == 0} {
        error "ERROR: No cells found matching pattern '$cell_pattern' for Pblock '$pb_name'!"
    }
    
    # 2. Create Pblock if needed
    if {[llength [get_pblocks -quiet $pb_name]] == 0} {
        create_pblock $pb_name
    }
    
    # 3. Assign target cell hierarchy
    add_cells_to_pblock [get_pblocks $pb_name] $target_cells
    
    # 4. Assign physical site range (verified from xc7a35tcpg236-1 device database)
    resize_pblock [get_pblocks $pb_name] -add $slice_range
    
    # 5. Set Pblock containment
    # HARD pblock: a soft one (what Vivado produced here by default) lets the placer ignore it
    set_property IS_SOFT false [get_pblocks $pb_name]
    set_property CONTAIN_ROUTING false [get_pblocks $pb_name]
    set_property EXCLUDE_PLACEMENT false [get_pblocks $pb_name]
    
    set num_sites [llength [get_sites -of [get_pblocks $pb_name]]]
    puts "    [get_pblocks $pb_name]: Assigned [llength $target_cells] cells to $num_sites physical sites."
}

# 1. R1 — Northwest (Clock Region X0Y2)
create_regional_pblock "pblock_R1" "u_region1" "SLICE_X0Y100:SLICE_X35Y149"

# 2. R2 — Northeast (Clock Region X1Y2)
create_regional_pblock "pblock_R2" "u_region2" "SLICE_X36Y100:SLICE_X57Y149"

# 3. R3 — Southwest (Clock Region X0Y0)
create_regional_pblock "pblock_R3" "u_region3" "SLICE_X0Y0:SLICE_X35Y49"

# 4. R4 — Southeast (Clock Region X1Y0)
create_regional_pblock "pblock_R4" "u_region4" "SLICE_X36Y0:SLICE_X65Y49"

# ------------------------------------------------------------------------------
# Floorplan Verification: Ensure 4 Pblocks exist and contain cells
# ------------------------------------------------------------------------------
puts "--> Verifying Pblock floorplan configuration..."
set pb_list [get_pblocks {pblock_R1 pblock_R2 pblock_R3 pblock_R4}]
if {[llength $pb_list] != 4} {
    error "ERROR: Expected 4 regional Pblocks, found [llength $pb_list]!"
}

foreach pb $pb_list {
    set pb_cells [get_cells -of $pb]
    if {[llength $pb_cells] == 0} {
        error "ERROR: Pblock '$pb' has no assigned cells!"
    }
    puts "    Pblock '$pb': Validated with [llength $pb_cells] cells assigned."
}

puts "SUCCESS: Four-region physical floorplan verified successfully."

# ------------------------------------------------------------------------------
# Pin each ring oscillator to fixed slices so its frequency is repeatable from build to build.
# (Without this the router places/routes the five LUTs differently on every build, which moved
# the oscillator frequencies by tens of percent and made every calibration build-specific.)
# Four LUTs share one slice (A6..D6LUT); the fifth sits in the slice directly above it.
# ------------------------------------------------------------------------------
proc find_slice_pair {xc yc} {
    for {set d 0} {$d <= 17} {incr d} {
        foreach x [list [expr {$xc + $d}] [expr {$xc - $d}]] {
            if {$x < 0} { continue }
            if {[llength [get_sites -quiet SLICE_X${x}Y${yc}]] && [llength [get_sites -quiet SLICE_X${x}Y[expr {$yc + 1}]]]} {
                return $x
            }
        }
    }
    error "no slice pair found near SLICE_X${xc}Y${yc}"
}

proc pin_ring_oscillator {idx xc yc} {
    set x    [find_slice_pair $xc $yc]
    set bels {A6LUT B6LUT C6LUT D6LUT A6LUT}
    set ys   [list $yc $yc $yc $yc [expr {$yc + 1}]]
    for {set k 0} {$k < 5} {incr k} {
        set c [get_cells -hierarchical -quiet -filter "NAME =~ u_region$idx/u_ring_osc/stage${k}_out_inferred_i_*"]
        if {[llength $c] != 1} {
            error "ring oscillator stage $k of region $idx: expected 1 LUT, found [llength $c]"
        }
        set_property LOC SLICE_X${x}Y[lindex $ys $k] $c
        set_property BEL [lindex $bels $k] $c
    }
    puts "    Region $idx ring oscillator pinned to SLICE_X${x}Y${yc}/Y[expr {$yc + 1}]"
}

pin_ring_oscillator 1 20 125
pin_ring_oscillator 2 45 125
pin_ring_oscillator 3 18 25
pin_ring_oscillator 4 50 25