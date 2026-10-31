`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: regional_health_monitor
// Description: Everything that lives inside one Pblock region (R1..R4):
//              a ring-oscillator delay sensor, its gated edge counter and a
//              switchable stress generator. Instantiated four times in the top
//              level as u_region1..u_region4 so the floorplan script can fence
//              each copy into its own physical region.
//////////////////////////////////////////////////////////////////////////////////

module regional_health_monitor #(
    parameter GATE_TICKS    = 1000000,
    parameter TIMEOUT_TICKS = 3500000,
    parameter STRESS_LUTS   = 512
)(
    input  wire        clk,
    input  wire        rst,
    input  wire        i_en,         // ring oscillator enable
    input  wire        i_stress_en,  // stress generator enable (already safety-gated)
    output wire [23:0] o_count,      // raw RO edge count per gate window
    output wire        o_valid,
    output wire        o_alive,
    output wire        o_ro_clk
);

    wire ro_clk;

    ring_oscillator u_ring_osc (
        .i_en(i_en),
        .o_ro_clk(ro_clk)
    );

    frequency_counter #(
        .GATE_TICKS(GATE_TICKS),
        .TIMEOUT_TICKS(TIMEOUT_TICKS)
    ) u_freq_counter (
        .clk(clk),
        .rst(rst),
        .i_ro_clk(ro_clk),
        .o_count(o_count),
        .o_valid(o_valid),
        .o_alive(o_alive)
    );

    stress_generator #(
        .N(STRESS_LUTS)
    ) u_stress (
        .i_en(i_stress_en)
    );

    assign o_ro_clk = ro_clk;

endmodule
