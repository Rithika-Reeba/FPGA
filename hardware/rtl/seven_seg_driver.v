`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: seven_seg_driver
// Description: Time-multiplexed driver for the Basys 3 four-digit seven-segment display.
//              i_sym holds four 4-bit symbols (digit 3 in the top nibble = leftmost):
//                0..9 = digits, 10 = 'C', 15 = blank.
//              i_dp[n] lights the decimal point of digit n.
//              Outputs are active low, as on the board.
//////////////////////////////////////////////////////////////////////////////////

module seven_seg_driver (
    input  wire        clk,
    input  wire [15:0] i_sym,
    input  wire [3:0]  i_dp,
    output reg  [6:0]  o_seg,    // {g,f,e,d,c,b,a}, active low
    output reg         o_dp_n,   // active low
    output reg  [3:0]  o_an      // active low, o_an[0] = rightmost digit
);

    reg [16:0] refresh = 17'd0;
    always @(posedge clk) refresh <= refresh + 17'd1;

    wire [1:0] sel = refresh[16:15];     // about 760 Hz per full scan

    reg [3:0] code;
    reg       dp;

    always @(*) begin
        case (sel)
            2'd0:    begin o_an = 4'b1110; code = i_sym[3:0];   dp = i_dp[0]; end
            2'd1:    begin o_an = 4'b1101; code = i_sym[7:4];   dp = i_dp[1]; end
            2'd2:    begin o_an = 4'b1011; code = i_sym[11:8];  dp = i_dp[2]; end
            default: begin o_an = 4'b0111; code = i_sym[15:12]; dp = i_dp[3]; end
        endcase

        case (code)
            4'd0:    o_seg = 7'b1000000;
            4'd1:    o_seg = 7'b1111001;
            4'd2:    o_seg = 7'b0100100;
            4'd3:    o_seg = 7'b0110000;
            4'd4:    o_seg = 7'b0011001;
            4'd5:    o_seg = 7'b0010010;
            4'd6:    o_seg = 7'b0000010;
            4'd7:    o_seg = 7'b1111000;
            4'd8:    o_seg = 7'b0000000;
            4'd9:    o_seg = 7'b0010000;
            4'd10:   o_seg = 7'b1000110;   // 'C'
            default: o_seg = 7'b1111111;   // blank
        endcase

        o_dp_n = ~dp;
    end

endmodule
