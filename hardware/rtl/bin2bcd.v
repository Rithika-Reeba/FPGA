`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: bin2bcd
// Description: Sequential "double dabble" binary-to-BCD converter (no division).
//              Converts W bits to D decimal digits in W clock cycles. It restarts by
//              itself whenever it is idle and i_start is high, so tying i_start = 1
//              gives a free-running converter that tracks a slowly changing input.
//////////////////////////////////////////////////////////////////////////////////

module bin2bcd #(
    parameter W = 24,
    parameter D = 8
)(
    input  wire           clk,
    input  wire           i_start,
    input  wire [W-1:0]   i_bin,
    output reg  [4*D-1:0] o_bcd,    // digit k is o_bcd[4*k +: 4] (k = 0 least significant)
    output reg            o_done
);

    reg [W-1:0]   shift = {W{1'b0}};
    reg [4*D-1:0] acc   = {(4*D){1'b0}};
    reg [5:0]     cnt   = 6'd0;
    reg           busy  = 1'b0;

    reg [4*D-1:0] adj;
    integer i;

    always @(posedge clk) begin
        o_done <= 1'b0;

        if (!busy) begin
            if (i_start) begin
                shift <= i_bin;
                acc   <= {(4*D){1'b0}};
                cnt   <= 6'd0;
                busy  <= 1'b1;
            end
        end else begin
            // add 3 to every digit that is 5 or more, then shift the next bit in
            adj = acc;
            for (i = 0; i < D; i = i + 1)
                if (acc[4*i +: 4] >= 4'd5)
                    adj[4*i +: 4] = acc[4*i +: 4] + 4'd3;

            acc   <= {adj[4*D-2:0], shift[W-1]};
            shift <= {shift[W-2:0], 1'b0};
            cnt   <= cnt + 6'd1;

            if (cnt == W - 1) begin
                o_bcd  <= {adj[4*D-2:0], shift[W-1]};
                o_done <= 1'b1;
                busy   <= 1'b0;
            end
        end
    end

endmodule
