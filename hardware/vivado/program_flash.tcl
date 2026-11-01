# Writes a design into the Basys 3's on-board QSPI flash, so it loads by itself at every power-up (it survives
# power dips and USB drops). One board only; the board id picks it when several are connected.
#   vivado -mode batch -source hardware/vivado/program_flash.tcl -tclargs <bitstream.bit> <board id> [flash part]
# The boards here carry a Macronix MX25L3273F flash (default part below). Vivado checks the part against the chip
# it finds and refuses to write on a mismatch, so a wrong choice cannot damage anything; older Basys 3 boards
# carry a Spansion S25FL032P: pass s25fl032p-spi-x1_x2_x4 as the third argument for those.
# The jumper JP1 on the board must be on QSPI (not JTAG) for the board to boot from the flash.
# To undo, program hardware/backup_original.bin back (see hardware/README.md) or simply write another design.
set bit  [lindex $argv 0]
set want [lindex $argv 1]
set part [expr {[llength $argv] > 2 ? [lindex $argv 2] : "mx25l3273f-spi-x1_x2_x4"}]
if {![file exists $bit]} { puts "ERROR: bitstream not found: $bit"; exit 1 }
set stem [file rootname [file tail $bit]]
set mcs  "C:/vivado_build/flash_[clock seconds].mcs"

# flash image from the bitstream (4 MB, 4-bit SPI)
write_cfgmem -format mcs -size 4 -interface SPIx4 -loadbit "up 0x00000000 $bit" -force -file $mcs
puts "--> flash image: $mcs"

open_hw_manager
connect_hw_server -allow_non_jtag
set targets [get_hw_targets]
if {[llength $targets] == 0} { puts "ERROR: no board found. Check the USB cable and the power switch."; exit 1 }
if {[llength $targets] > 1} {
    if {$want eq ""} { puts "ERROR: [llength $targets] boards are connected; the board id is required."; exit 1 }
    set picked {}
    foreach tg $targets { if {[string match "*${want}*" $tg]} { lappend picked $tg } }
    if {[llength $picked] != 1} { puts "ERROR: board id $want matches [llength $picked] connected boards"; exit 1 }
    current_hw_target [lindex $picked 0]
}
puts "--> Target: [current_hw_target]"
open_hw_target
set dev [lindex [get_hw_devices xc7a35t_0] 0]
current_hw_device $dev
refresh_hw_device -update_hw_probes false $dev

create_hw_cfgmem -hw_device $dev [lindex [get_cfgmem_parts $part] 0]
set cm [get_property PROGRAM.HW_CFGMEM $dev]
set_property PROGRAM.ADDRESS_RANGE  {use_file} $cm
set_property PROGRAM.FILES          [list $mcs] $cm
set_property PROGRAM.PRM_FILE       {} $cm
set_property PROGRAM.UNUSED_PIN_TERMINATION {pull-none} $cm
set_property PROGRAM.BLANK_CHECK    0 $cm
set_property PROGRAM.ERASE          1 $cm
set_property PROGRAM.CFG_PROGRAM    1 $cm
set_property PROGRAM.VERIFY         1 $cm
set_property PROGRAM.CHECKSUM       0 $cm
create_hw_bitstream -hw_device $dev [get_property PROGRAM.HW_CFGMEM_BITFILE $dev]
program_hw_devices $dev
program_hw_cfgmem -hw_cfgmem $cm
puts "SUCCESS: flash programmed with $stem"
close_hw_target
disconnect_hw_server
close_hw_manager