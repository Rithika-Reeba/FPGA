`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: ring_oscillator
// Description: 5-stage ring oscillator (N = 5 inverting elements) used as an
//              on-chip delay / aging sensor.
// Formula:     tau = 1 / (2 * N * f)   [per-stage delay]
// Notes:       DONT_TOUCH / KEEP on every node keeps Vivado from optimising the
//              intentional combinatorial loop. Under SIMULATION the stages get a
//              transport delay (STAGE_DELAY_NS) so the loop oscillates in xsim.
//////////////////////////////////////////////////////////////////////////////////

module ring_oscillator #(
    parameter real STAGE_DELAY_NS = 0.23   // simulation only
)(
    input  wire i_en,      // 1 = oscillate, 0 = output held high
    output wire o_ro_clk
);

    (* DONT_TOUCH = "TRUE", KEEP = "TRUE", S = "TRUE" *) wire stage0_out;
    (* DONT_TOUCH = "TRUE", KEEP = "TRUE", S = "TRUE" *) wire stage1_out;
    (* DONT_TOUCH = "TRUE", KEEP = "TRUE", S = "TRUE" *) wire stage2_out;
    (* DONT_TOUCH = "TRUE", KEEP = "TRUE", S = "TRUE" *) wire stage3_out;
    (* DONT_TOUCH = "TRUE", KEEP = "TRUE", S = "TRUE" *) wire stage4_out;

`ifdef SIMULATION
    assign #(STAGE_DELAY_NS) stage0_out = ~(stage4_out & i_en);
    assign #(STAGE_DELAY_NS) stage1_out = ~stage0_out;
    assign #(STAGE_DELAY_NS) stage2_out = ~stage1_out;
    assign #(STAGE_DELAY_NS) stage3_out = ~stage2_out;
    assign #(STAGE_DELAY_NS) stage4_out = ~stage3_out;
`else
    assign stage0_out = ~(stage4_out & i_en);
    assign stage1_out = ~stage0_out;
    assign stage2_out = ~stage1_out;
    assign stage3_out = ~stage2_out;
    assign stage4_out = ~stage3_out;
`endif

    assign o_ro_clk = stage4_out;

endmodule
