# ==============================================================================
# Vivado Non-Project Build Script: Four-Region FPGA Health Monitoring Bitstream
# Target: Digilent Basys 3 (Xilinx Artix-7 xc7a35tcpg236-1)
# ==============================================================================

set script_dir [file dirname [file normalize [info script]]]
set proj_root  [file normalize "$script_dir/.."]
# Switch working directory and build output to local non-OneDrive disk
set local_work "C:/vivado_build"
# Demo variant: FPGA_FAULT_ALWAYS=1 builds a bitstream whose R2 test fault is always on. It goes to its
# own folder so the normal bitstream is never overwritten.
set fault_always [expr {[info exists ::env(FPGA_FAULT_ALWAYS)] && $::env(FPGA_FAULT_ALWAYS) eq "1"}]
set output_dir "$local_work/build[expr {$fault_always ? "_fault" : ""}]"
file mkdir $local_work
file mkdir $output_dir
cd $local_work

puts "======================================================================"
puts " Starting Vivado Four-Region Synthesis & Implementation for Basys 3"
puts " Working directory: [pwd]"
puts " Output directory:  $output_dir"
puts "======================================================================"

# 1. Read RTL Verilog Source Files
read_verilog [glob $proj_root/rtl/*.v]

# 2. Read Constraints
read_xdc $proj_root/constraints/basys3.xdc

# 3. Synthesis
puts "--> Running Synthesis (preserving module hierarchy for Pblock assignment)..."
set build_id [expr {([clock seconds] % 65534) + 1}]
puts "--> Build ID: [format %04X $build_id] (sent in every telemetry packet as V=; baselines are tied to it)"
synth_design -top fpga_health_top -part xc7a35tcpg236-1 -flatten_hierarchy rebuilt -generic BUILD_ID=$build_id -generic FAULT_ALWAYS=$fault_always

source $proj_root/vivado/ro_constraints.tcl

write_checkpoint -force $output_dir/post_synth.dcp
report_utilization -file $output_dir/post_synth_utilization.rpt

# 4. Apply Four-Region Floorplan
puts "--> Applying Four-Region Physical Pblock Floorplan..."
source $proj_root/vivado/four_region_floorplan.tcl

# Verify all four regional modules are strictly assigned to their intended Pblocks
puts "--> Verifying Pblock containment..."
set required_pbs {pblock_R1 pblock_R2 pblock_R3 pblock_R4}
foreach pb $required_pbs {
    if {[llength [get_pblocks -quiet $pb]] == 0} {
        error "BUILD FAILED: Required Pblock '$pb' does not exist in design!"
    }
    set assigned_cells [get_cells -of [get_pblocks $pb]]
    if {[llength $assigned_cells] == 0} {
        error "BUILD FAILED: Pblock '$pb' has no assigned cells (module was not constrained)!"
    }
    puts "    $pb: Verified [llength $assigned_cells] assigned cells."
}

# A bitstream left over from an earlier run must never be mistaken for this build's result.
file delete -force $output_dir/fpga_health_top.bit

# 5. Logic Optimization
puts "--> Running Logic Optimization (opt_design)..."
opt_design
write_checkpoint -force $output_dir/post_opt.dcp

# 6. Placement
puts "--> Running Placement (place_design with regional Pblocks)..."
place_design
write_checkpoint -force $output_dir/post_place.dcp
# Every cell of a region must really sit inside that region's Pblock. (A soft Pblock is only a hint:
# in an earlier build 15-29 % of each region's cells, heaters included, ended up outside it.)
puts "--> Verifying placement containment..."
foreach i {1 2 3 4} {
    set pb [get_pblocks pblock_R$i]
    set outside 0
    set total 0
    foreach c [get_cells -hierarchical -filter "NAME =~ u_region$i/* && IS_PRIMITIVE"] {
        set loc [get_property LOC $c]
        if {$loc eq "" || ![string match "SLICE_*" $loc]} { continue }
        incr total
        if {![llength [get_sites -quiet -of_objects $pb $loc]]} { incr outside }
    }
    puts "    region $i: $total placed slice cells, $outside outside pblock_R$i"
    if {$outside > 0} { error "BUILD FAILED: $outside cells of region $i were placed outside pblock_R$i" }
}

# 7. Routing
puts "--> Running Routing (route_design)..."
route_design
write_checkpoint -force $output_dir/post_route.dcp

# 8. Generate Reports
puts "--> Generating Implementation Reports..."
report_timing_summary -file $output_dir/timing_summary.rpt
report_utilization -file $output_dir/utilization.rpt
foreach pb [get_pblocks] {
    catch { report_utilization -pblocks $pb -file "$output_dir/utilization_${pb}.rpt" }
}
report_drc -file $output_dir/drc.rpt

# Timing gate: a design that misses timing (setup or hold) is not written out. The oscillator
# counters run at hundreds of MHz, so a miss there can give wrong readings.
set wns [get_property SLACK [get_timing_paths -max_paths 1 -setup]]
set whs [get_property SLACK [get_timing_paths -max_paths 1 -hold]]
puts "--> Timing after route: WNS=$wns ns, WHS=$whs ns"
if {$wns < 0 || $whs < 0} { error "BUILD FAILED: timing not met (WNS=$wns ns, WHS=$whs ns); no bitstream written" }

# 9. Write Bitstream
catch { set_property SEVERITY {Warning} [get_drc_checks LUTLP-1] }
set bitstream_path "$output_dir/fpga_health_top.bit"
puts "--> Writing Bitstream to $bitstream_path..."
write_bitstream -force $bitstream_path

# Copy fresh bitstream to project hardware root
set local_bit "$proj_root/fpga_health_top.bit"
if {!$fault_always} {   ;# the demo fault build must never replace the normal bitstream
    file copy -force $bitstream_path $local_bit
    puts "--> Copied fresh bitstream to: $local_bit"
}

puts "======================================================================"
puts " SUCCESS: Four-Region Bitstream successfully generated at:"
puts " $bitstream_path"
puts "======================================================================"

