`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: display_ctrl
// Description: Shows live readings on the four-digit display, one page at a time.
//   Pages (each shown for PAGE_TICKS clocks, 2 s by default):
//     0..3  region 1..4 ring-oscillator frequency:  "n.fff"  e.g. "1.431" = R1 at 431 MHz
//     4     die temperature:                         "tt.tC"  e.g. "41.6C"
//   No division: the converter is a double-dabble BCD stage. The RO count is edges per
//   10 ms gate, so MHz = count / 10000 and the three MHz digits are digits 6..4 of the
//   decimal count. Temperature uses the XADC transfer function in fixed point.
//////////////////////////////////////////////////////////////////////////////////

module display_ctrl #(
    parameter PAGE_TICKS = 200000000      // 2 s at 100 MHz
)(
    input  wire        clk,
    input  wire        rst,               // synchronous, active high
    input  wire [23:0] i_cnt1,
    input  wire [23:0] i_cnt2,
    input  wire [23:0] i_cnt3,
    input  wire [23:0] i_cnt4,
    input  wire [11:0] i_temp_code,       // raw XADC temperature code
    output wire [6:0]  o_seg,
    output wire        o_dp_n,
    output wire [3:0]  o_an
);

    // ---- page sequencer ------------------------------------------------------
    reg [2:0]  page = 3'd0;
    reg [27:0] page_tmr = 28'd0;

    always @(posedge clk) begin
        if (rst) begin
            page     <= 3'd0;
            page_tmr <= 28'd0;
        end else if (page_tmr == PAGE_TICKS - 1) begin
            page_tmr <= 28'd0;
            page     <= (page == 3'd4) ? 3'd0 : page + 3'd1;
        end else begin
            page_tmr <= page_tmr + 28'd1;
        end
    end

    // ---- temperature in 0.1 degC:  code * 503.975 / 4096 - 273.15 ------------
    // (code * 1260) >> 10 = code * 1.2305 = 0.1 degC + 2731.5, off by < 0.02 %
    reg [22:0] temp_mul    = 23'd0;
    reg [12:0] temp_x10    = 13'd0;
    always @(posedge clk) begin
        temp_mul <= i_temp_code * 11'd1260;
        temp_x10 <= (temp_mul[22:10] > 13'd2731) ? (temp_mul[22:10] - 13'd2731) : 13'd0;
    end

    // ---- value for the current page -> BCD ------------------------------------
    reg [23:0] bin_in = 24'd0;
    always @(posedge clk) begin
        case (page)
            3'd0:    bin_in <= i_cnt1;
            3'd1:    bin_in <= i_cnt2;
            3'd2:    bin_in <= i_cnt3;
            3'd3:    bin_in <= i_cnt4;
            default: bin_in <= {11'd0, temp_x10};
        endcase
    end

    wire [31:0] bcd;
    wire        bcd_done;

    bin2bcd #(.W(24), .D(8)) u_bcd (
        .clk(clk),
        .i_start(1'b1),
        .i_bin(bin_in),
        .o_bcd(bcd),
        .o_done(bcd_done)
    );

    // ---- symbols -----------------------------------------------------------------
    reg [15:0] sym = {4'd15, 4'd15, 4'd15, 4'd15};
    reg [3:0]  dp  = 4'b0000;

    always @(posedge clk) begin
        if (bcd_done) begin
            if (page <= 3'd3) begin
                // region number, then MHz hundreds / tens / units (digits 6, 5, 4)
                sym <= {1'b0, page + 3'd1, bcd[27:24], bcd[23:20], bcd[19:16]};
                dp  <= 4'b1000;                                   // dot after the region digit
            end else begin
                // tens / units / tenths of a degree, then 'C'
                sym <= {bcd[11:8], bcd[7:4], bcd[3:0], 4'd10};
                dp  <= 4'b0100;                                   // dot before the tenths digit
            end
        end
    end

    seven_seg_driver u_drv (
        .clk(clk),
        .i_sym(sym),
        .i_dp(dp),
        .o_seg(o_seg),
        .o_dp_n(o_dp_n),
        .o_an(o_an)
    );

endmodule
