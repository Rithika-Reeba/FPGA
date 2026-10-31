# ==============================================================================
# Vivado Hardware Manager Programming Script: Basys 3 FPGA
# Target: Digilent Basys 3 (Artix-7 xc7a35t_0)
# ==============================================================================

set script_dir [file dirname [file normalize [info script]]]
set proj_root  [file normalize "$script_dir/.."]
set candidate_bits [list "C:/vivado_build/build/fpga_health_top.bit" "$proj_root/build/fpga_health_top.bit" "$proj_root/fpga_health_top.bit"]
set bitstream ""
foreach c $candidate_bits {
    if {[file exists $c]} {
        set bitstream $c
        break
    }
}

if {$bitstream eq ""} {
    puts "ERROR: Bitstream file not found."
    puts "Please run build_bitstream.tcl first to compile the design."
    exit 1
}

puts "======================================================================"
puts " Connecting to Vivado Hardware Manager & Programming Basys 3"
puts " Bitstream: $bitstream"
puts "======================================================================"

open_hw_manager
connect_hw_server -allow_non_jtag

# More than one board connected: never guess. The board id is the Digilent cable id, which is the
# USB serial number without its last letter (e.g. 210183B31BC1); pass it after -tclargs.
set targets [get_hw_targets]
if {[llength $targets] == 0} {
    puts "ERROR: no board found. Check the USB cable and the power switch."
    exit 1
}
if {[llength $targets] > 1} {
    if {[llength $argv] < 1} {
        puts "ERROR: [llength $targets] boards are connected:"
        foreach tg $targets { puts "    $tg" }
        puts "Say which one to program: vivado -mode batch -source program_fpga.tcl -tclargs <board id>"
        exit 1
    }
    set want [lindex $argv 0]
    set picked {}
    foreach tg $targets { if {[string match "*${want}*" $tg]} { lappend picked $tg } }
    if {[llength $picked] != 1} {
        puts "ERROR: board id '$want' matches [llength $picked] of the connected boards"
        exit 1
    }
    current_hw_target [lindex $picked 0]
}
puts "--> Programming target: [current_hw_target]"
open_hw_target

# Select the Artix-7 device
set target_device [lindex [get_hw_devices xc7a35t_0] 0]
if {$target_device eq ""} {
    # Fallback to first available device
    set target_device [lindex [get_hw_devices] 0]
}

current_hw_device $target_device
refresh_hw_device -update_hw_probes false [current_hw_device]

# Set bitstream file property and program
set_property PROGRAM.FILE $bitstream [current_hw_device]
puts "--> Programming device: [current_hw_device]..."
program_hw_devices [current_hw_device]
refresh_hw_device [current_hw_device]

puts "======================================================================"
puts " SUCCESS: Basys 3 FPGA successfully programmed!"
puts " Telemetry stream is now broadcasting on USB-UART at 115200 baud."
puts "======================================================================"

close_hw_target
disconnect_hw_server
close_hw_manager
