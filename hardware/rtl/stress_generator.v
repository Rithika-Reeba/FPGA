`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: stress_generator
// Description: Switchable "power waster" used to apply accelerated thermal /
//              supply stress to one floorplan region. N single-LUT oscillators
//              (out = ~(out & en)) toggle at very high rate when i_en = 1, which
//              heats the local silicon and loads the supply. This is a real
//              physical effect, used to demonstrate Warning / Degraded states.
//
// Safety:      The top level only asserts i_en while the XADC die temperature
//              and VCCINT are inside safe limits (with hysteresis).
// Simulation:  Zero-delay loops would hang the simulator, so under SIMULATION
//              the heaters are tied off.
//////////////////////////////////////////////////////////////////////////////////

module stress_generator #(
    parameter N = 512
)(
    input wire i_en
);

    genvar i;
    generate
        for (i = 0; i < N; i = i + 1) begin : g_heater
            (* DONT_TOUCH = "TRUE", KEEP = "TRUE" *) wire h;
`ifdef SIMULATION
            assign h = 1'b1;
`else
            assign h = ~(h & i_en);
`endif
        end
    endgenerate

endmodule
