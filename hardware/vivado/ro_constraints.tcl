# ==============================================================================
# Constraints for the ring oscillators: allow their intentional combinatorial loops, declare each
# oscillator output (and its divide-by-2 counting clock) as a clock so STA checks the counters,
# and keep every oscillator domain asynchronous. Sourced by BOTH the batch build and the
# Vivado project flow (hooks/pre_opt.tcl) so the two can never disagree.
# Run on a synthesized design (netlist open).
# ==============================================================================

# Allow intentional combinatorial feedback loop for the Ring Oscillators
set_property ALLOW_COMBINATORIAL_LOOPS TRUE [get_nets -hierarchical *stage*out*]
catch { set_property ALLOW_COMBINATORIAL_LOOPS TRUE [get_nets -hierarchical -quiet *ro*clk*] }
catch { set_property ALLOW_COMBINATORIAL_LOOPS TRUE [get_nets -hierarchical -quiet *g_heater*] }

# Treat each ring-oscillator output as a (fast) clock so STA checks the edge counters,
# and keep all RO domains asynchronous to the 100 MHz domain and to each other.
set ro_clks {}
foreach i {1 2 3 4} {
    set n [get_nets -quiet -hierarchical -filter "NAME =~ *u_region$i/*stage4_out*"]
    if {[llength $n] == 0} { puts "WARNING: RO net for region $i not found; its domain stays unconstrained"; continue }
    set drv [get_pins -quiet -of_objects [lindex $n 0] -filter {DIRECTION == OUT && IS_LEAF}]
    if {[llength $drv] > 1} { set drv [lindex $drv 0] }
    # 2.0 ns = 500 MHz: faster than any oscillator measured on the board (about 456 MHz max)
    if {[catch { create_clock -name ro_clk_r$i -period 2.0 $drv } err]} {
        puts "WARNING: could not create RO clock for region $i: $err"
    } else {
        # the counting logic runs on the divide-by-2 flip-flop, so declare that clock too
        set div [get_pins -quiet -hierarchical -filter "NAME =~ *u_region$i/*ro_div_reg/Q"]
        if {[llength $div] == 0} {
            puts "WARNING: ro_div flip-flop for region $i not found; its divided clock is unconstrained"
            lappend ro_clks ro_clk_r$i
        } else {
            create_generated_clock -name ro_div_r$i -source $drv -divide_by 2 [lindex $div 0]
            lappend ro_clks "ro_clk_r$i ro_div_r$i"
        }
    }
}
if {[llength $ro_clks] > 0} {
    set groups [list -group sys_clk_pin]
    foreach c $ro_clks { lappend groups -group $c }
    set_clock_groups -asynchronous {*}$groups
}
catch { set_property SEVERITY {Warning} [get_drc_checks LUTLP-1] }
