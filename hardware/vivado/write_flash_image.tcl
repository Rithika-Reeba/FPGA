# Writes a saved flash image (.bin read with read_flash.tcl, or an .mcs) into ONE board's on-board flash, erasing and
# verifying it. Used to copy the stored program of one board onto another.
#   vivado -mode batch -source hardware/vivado/write_flash_image.tcl -tclargs <image .bin|.mcs> <board id> [flash part]
# Vivado checks the flash chip against the part and refuses to write on a mismatch.
set img  [lindex $argv 0]
set want [lindex $argv 1]
set part [expr {[llength $argv] > 2 ? [lindex $argv 2] : "mx25l3273f-spi-x1_x2_x4"}]
if {![file exists $img]} { puts "ERROR: image not found: $img"; exit 1 }
if {[string tolower [file extension $img]] eq ".bin"} {
    set mcs "C:/vivado_build/flash_image_[clock seconds].mcs"
    write_cfgmem -format mcs -size 4 -interface SPIx4 -loaddata "up 0x00000000 $img" -force -file $mcs
} else {
    set mcs $img
}
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
puts "SUCCESS: flash image written to board $want"
close_hw_target
disconnect_hw_server
close_hw_manager