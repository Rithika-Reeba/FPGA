# READ-ONLY: copies the whole content of ONE board's on-board flash into a .bin file. Nothing is written to the flash.
# (Vivado loads a small helper design into the FPGA to reach the flash, so the board's running design pauses until
#  the next power-up or programming; the stored program is untouched.)
#   vivado -mode batch -source hardware/vivado/read_flash.tcl -tclargs <board id> <out.bin> [flash part]
set want [lindex $argv 0]
set out  [lindex $argv 1]
set part [expr {[llength $argv] > 2 ? [lindex $argv 2] : "mx25l3273f-spi-x1_x2_x4"}]
open_hw_manager
connect_hw_server -allow_non_jtag
set targets [get_hw_targets]
set picked {}
foreach tg $targets { if {[string match "*${want}*" $tg]} { lappend picked $tg } }
if {[llength $picked] != 1} { puts "ERROR: board id $want matches [llength $picked] connected boards"; exit 1 }
current_hw_target [lindex $picked 0]
puts "--> Target: [current_hw_target]"
open_hw_target
set dev [lindex [get_hw_devices xc7a35t_0] 0]
current_hw_device $dev
refresh_hw_device -update_hw_probes false $dev
create_hw_cfgmem -hw_device $dev [lindex [get_cfgmem_parts $part] 0]
set cm [get_property PROGRAM.HW_CFGMEM $dev]
create_hw_bitstream -hw_device $dev [get_property PROGRAM.HW_CFGMEM_BITFILE $dev]
program_hw_devices $dev
readback_hw_cfgmem -all -file $out -format bin -force $cm
puts "SUCCESS: flash read to $out"
close_hw_target
disconnect_hw_server
close_hw_manager