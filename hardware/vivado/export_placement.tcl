# Writes every placed cell of regions R1..R4 (with its slice location) and the four Pblock rectangles to a CSV,
# for hardware/vivado/plot_floorplan.py.   vivado -mode batch -source hardware/vivado/export_placement.tcl
set dcp "C:/vivado_projects/fpga_health_project/fpga_health_project.runs/impl_1/fpga_health_top_routed.dcp"
if {[info exists ::env(FPGA_DCP)]} { set dcp $::env(FPGA_DCP) }
open_checkpoint $dcp
set fh [open C:/vivado_build/placement.csv w]
puts $fh "region,cell,site,kind"
foreach i {1 2 3 4} {
  foreach c [get_cells -hierarchical -filter "NAME =~ u_region$i/* && IS_PRIMITIVE"] {
    set loc [get_property LOC $c]
    if {$loc eq ""} continue
    puts $fh "R$i,[get_property NAME $c],$loc,[get_property REF_NAME $c]"
  }
}
foreach pb [get_pblocks] { puts $fh "PBLOCK,[get_property NAME $pb],[get_property GRID_RANGES $pb]," }
close $fh
puts "PLACEMENT_EXPORTED"