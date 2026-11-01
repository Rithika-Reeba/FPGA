# Opens the health-monitor Vivado project (healthy design) and goes straight to the physical floorplan:
# the implemented design with the four Pblocks (physical partitions) drawn in the Device window and each
# region's logic highlighted (R1 red, R2 green, R3 blue, R4 orange). Started by open_vivado.bat.
# The project is opened by its REAL location: it stores its source paths relative to it.
open_project C:/vivado_projects/fpga_health_project/fpga_health_project.xpr
open_run impl_1

set colors {red green blue orange}
foreach i {1 2 3 4} {
    set c [lindex $colors [expr {$i - 1}]]
    catch { highlight_objects -color $c [get_cells -hierarchical -filter "NAME =~ u_region$i/* && IS_PRIMITIVE"] }
}
catch { select_objects [get_pblocks] }
foreach pb [get_pblocks] {
    puts "[get_property NAME $pb]: [get_property GRID_RANGES $pb]"
}
puts "Device window: the coloured cells sit inside the four Pblock rectangles (pblock_R1 .. pblock_R4)."