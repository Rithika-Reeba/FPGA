# Regenerates the Vivado project from the current RTL / constraints / floorplan hooks and runs
# synthesis + implementation (through routing), so that opening the .xpr and choosing
# "Open Implemented Design" shows the four Pblocks (physical partitions) in the Device window.
#   vivado -mode batch -source hardware/vivado/refresh_project.tcl
set script_dir [file dirname [file normalize [info script]]]
source $script_dir/create_project.tcl
launch_runs synth_1 -jobs 2
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} { error "synthesis failed" }
launch_runs impl_1 -to_step route_design -jobs 2
wait_on_run impl_1
puts "impl_1 status: [get_property STATUS [get_runs impl_1]]"
close_project