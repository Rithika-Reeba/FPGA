# ==============================================================================
# Create Vivado Project for FPGA Health Monitoring System
# Target Device: Digilent Basys 3 (XC7A35T-1CPG236C)
# ==============================================================================

set script_dir [file dirname [file normalize [info script]]]
set repo_root  [file normalize "$script_dir/../.."]
set proj_name  "fpga_health_project"
set part_num   "xc7a35tcpg236-1"

# Target project directory:
# Use local disk (C:/vivado_projects/fpga_health_project) to avoid OneDrive file locking and path limits
if {[info exists ::env(VIVADO_PROJ_DIR)]} {
    set proj_dir $::env(VIVADO_PROJ_DIR)
} else {
    set proj_dir "C:/vivado_projects/fpga_health_project"
}

file mkdir $proj_dir

puts "======================================================================"
puts " Creating Vivado Project: $proj_name"
puts " Location: $proj_dir"
puts " Target Part: $part_num"
puts "======================================================================"

# 1. Create project
create_project $proj_name $proj_dir -part $part_num -force

# 2. Add RTL Source Files
set rtl_files [glob -nocomplain "$repo_root/hardware/rtl/*.v"]
if {[llength $rtl_files] > 0} {
    add_files -fileset sources_1 $rtl_files
    puts "--> Added [llength $rtl_files] RTL source files."
} else {
    error "ERROR: No RTL source files found in $repo_root/hardware/rtl"
}

# Set Top Module
set_property top fpga_health_top [current_fileset]
# Build ID sent in every telemetry packet (V=): a baseline is tied to it, so it must change per build.
set build_id [expr {([clock seconds] % 65534) + 1}]
set_property generic "BUILD_ID=$build_id" [current_fileset]
puts "--> Build ID: [format %04X $build_id]"
update_compile_order -fileset sources_1

# 3. Add Constraints
add_files -fileset constrs_1 "$repo_root/hardware/constraints/basys3.xdc"
# The four-region floorplan is applied by hooks/pre_place.tcl (hard Pblocks + pinned oscillators); the
# old four_region_floorplan.xdc was removed because it duplicated it without the oscillator pinning.

# 4. Add Simulation Files
if {[file exists "$repo_root/hardware/sim/tb_fpga_health_top.v"]} {
    add_files -fileset sim_1 "$repo_root/hardware/sim/tb_fpga_health_top.v"
    set_property top tb_fpga_health_top [get_filesets sim_1]
    set_property -name {xsim.simulate.runtime} -value {20us} -objects [get_filesets sim_1]
    set_property verilog_define {SIMULATION=1} [get_filesets sim_1]
    update_compile_order -fileset sim_1
    puts "--> Added simulation testbench and configured sim_1."
}

# 5. Add Utilities / Hooks to utils_1 fileset
set hook_opt "$repo_root/hardware/vivado/hooks/pre_opt.tcl"
set hook_bit "$repo_root/hardware/vivado/hooks/pre_bitstream.tcl"
if {[file exists $hook_opt]} {
    add_files -fileset utils_1 $hook_opt
    set_property STEPS.OPT_DESIGN.TCL.PRE $hook_opt [get_runs impl_1]
}
if {[file exists $hook_bit]} {
    add_files -fileset utils_1 $hook_bit
    set_property STEPS.WRITE_BITSTREAM.TCL.PRE $hook_bit [get_runs impl_1]
}

set hook_place "$repo_root/hardware/vivado/hooks/pre_place.tcl"
if {[file exists $hook_place]} {
    add_files -fileset utils_1 $hook_place
    set_property STEPS.PLACE_DESIGN.TCL.PRE $hook_place [get_runs impl_1]
}

# 6. Configure Synthesis Runs
# Preserve module hierarchy for Pblock assignment
set_property -name {STEPS.SYNTH_DESIGN.ARGS.FLATTEN_HIERARCHY} -value {rebuilt} -objects [get_runs synth_1]

puts "======================================================================"
puts " Project successfully configured!"
puts " .xpr File: $proj_dir/$proj_name.xpr"
puts "======================================================================"
