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
