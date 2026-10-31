`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: packet_formatter
// Description: Serialises raw telemetry as one fixed-length ASCII-hex line:
//
//   R1=cccccc,R2=cccccc,R3=cccccc,R4=cccccc,T=ttt,I=iii,A=aaa,B=bbb,F=f,S=s,H=h\r\n
//
//   Rn  24-bit RO edge count of region n over one gate window (hex)
//   T   XADC die temperature code (12-bit)      I/A/B  VCCINT/VCCAUX/VCCBRAM codes
//   F   oscillator-alive flags {R4,R3,R2,R1}    S  stress-active flags {R4..R1}
//   H   on-board verdict: 0 = not calibrated, 1 = healthy, 2 = warning, 3 = degraded
//
// No division / modulo is used; the host converts the codes to physical units.
// With i_mode_select = 1 a short "HELLO FPGA" line is sent instead (link test).
//////////////////////////////////////////////////////////////////////////////////

module packet_formatter #(
    parameter CLK_FREQ_HZ = 100000000,
    parameter TRANSMIT_HZ = 2
)(
    input  wire        clk,
    input  wire        rst,            // synchronous, active high
    input  wire        i_mode_select,  // 0 = telemetry, 1 = HELLO
    input  wire [23:0] i_cnt1,
    input  wire [23:0] i_cnt2,
    input  wire [23:0] i_cnt3,
    input  wire [23:0] i_cnt4,
    input  wire [3:0]  i_alive,
    input  wire [3:0]  i_stress,
    input  wire [11:0] i_temp,
    input  wire [11:0] i_vccint,
    input  wire [11:0] i_vccaux,
    input  wire [11:0] i_vccbram,
    input  wire [1:0]  i_verdict,
    input  wire        i_uart_busy,
    output reg         o_uart_valid,
    output reg  [7:0]  o_uart_data,
    output reg         o_tx_active
);

    localparam INTERVAL_TICKS = CLK_FREQ_HZ / TRANSMIT_HZ;
    localparam PKT_BYTES      = 77;

    function [7:0] hx;
        input [3:0] n;
        begin
            hx = (n < 4'd10) ? (8'h30 + {4'd0, n}) : (8'h37 + {4'd0, n});
        end
    endfunction

    function [47:0] hex6;
        input [23:0] v;
        begin
            hex6 = {hx(v[23:20]), hx(v[19:16]), hx(v[15:12]),
                    hx(v[11:8]),  hx(v[7:4]),   hx(v[3:0])};
        end
    endfunction

    function [23:0] hex3;
        input [11:0] v;
        begin
            hex3 = {hx(v[11:8]), hx(v[7:4]), hx(v[3:0])};
        end
    endfunction

    wire [615:0] pkt_live = {
        "R1=", hex6(i_cnt1), ",",
        "R2=", hex6(i_cnt2), ",",
        "R3=", hex6(i_cnt3), ",",
        "R4=", hex6(i_cnt4), ",",
        "T=",  hex3(i_temp),   ",",
        "I=",  hex3(i_vccint), ",",
        "A=",  hex3(i_vccaux), ",",
        "B=",  hex3(i_vccbram), ",",
        "F=",  hx(i_alive),  ",",
        "S=",  hx(i_stress), ",",
        "H=",  hx({2'b00, i_verdict}),
        8'h0D, 8'h0A
    };

    wire [615:0] pkt_hello = {"HELLO FPGA", 8'h0D, 8'h0A, 520'd0};

    reg [615:0] pkt;
    reg [6:0]   pkt_len;
    reg [6:0]   idx;
    reg [27:0]  timer;

    localparam S_IDLE       = 3'd0;
    localparam S_LOAD       = 3'd1;
    localparam S_SEND       = 3'd2;
    localparam S_WAIT_BUSY  = 3'd3;
    localparam S_WAIT_READY = 3'd4;

    reg [2:0] state;

    wire [6:0] ridx = 7'd76 - idx;           // byte 0 lives in the top bits
    wire [9:0] lsb  = {ridx, 3'b000};

    always @(posedge clk) begin
        o_uart_valid <= 1'b0;

        if (rst) begin
            timer       <= 28'd0;
            state       <= S_IDLE;
            idx         <= 7'd0;
            pkt_len     <= 7'd0;
            pkt         <= 616'd0;
            o_uart_data <= 8'd0;
            o_tx_active <= 1'b0;
        end else begin
            case (state)
                S_IDLE: begin
                    o_tx_active <= 1'b0;
                    if (timer < INTERVAL_TICKS - 1) begin
                        timer <= timer + 28'd1;
                    end else begin
                        timer <= 28'd0;
                        state <= S_LOAD;
                    end
                end

                S_LOAD: begin
                    o_tx_active <= 1'b1;
                    idx         <= 7'd0;
                    pkt         <= i_mode_select ? pkt_hello : pkt_live;
                    pkt_len     <= i_mode_select ? 7'd12 : PKT_BYTES;
                    state       <= S_SEND;
                end

                S_SEND: begin
                    if (idx < pkt_len) begin
                        o_uart_data  <= pkt[lsb +: 8];
                        o_uart_valid <= 1'b1;
                        state        <= S_WAIT_BUSY;
                    end else begin
                        state <= S_IDLE;
                    end
                end

                S_WAIT_BUSY: begin
                    if (i_uart_busy) state <= S_WAIT_READY;
                end

                S_WAIT_READY: begin
                    if (!i_uart_busy) begin
                        idx   <= idx + 7'd1;
                        state <= S_SEND;
                    end
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
