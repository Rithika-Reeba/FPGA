# Opens the routed design in the Vivado GUI with the four physical partitions (Pblocks) highlighted.
#   vivado -mode gui -source hardware/vivado/show_floorplan.tcl
# Set FPGA_DCP to look at another build, e.g. C:/vivado_build/build_fault/post_route.dcp
set dcp "C:/vivado_build/build/post_route.dcp"
if {[info exists ::env(FPGA_DCP)]} { set dcp $::env(FPGA_DCP) }
open_checkpoint $dcp

# one colour per region: R1 red, R2 green, R3 blue, R4 orange (cells of that region's logic)
set colors {red green blue orange}
foreach i {1 2 3 4} {
    set c [lindex $colors [expr {$i - 1}]]
    catch { highlight_objects -color $c [get_cells -hierarchical -filter "NAME =~ u_region$i/* && IS_PRIMITIVE"] }
}

# the Pblock rectangles themselves are drawn in the Device window; select them so they stand out
catch { select_objects [get_pblocks] }
foreach pb [get_pblocks] {
    puts "[get_property NAME $pb]: [get_property GRID_RANGES $pb]"
}
puts "Device window: the coloured cells sit inside the four Pblock rectangles (pblock_R1 .. pblock_R4)."