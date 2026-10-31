`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: frequency_counter
// Description: Gated ring-oscillator edge counter with oscillator-alive detection.
//
// Operation:
//   * The reference domain (clk) opens a gate for GATE_TICKS cycles every
//     GATE_TICKS + GUARD_TICKS cycles (10 ms at 100 MHz by default).
//   * The RO domain counts RO edges while the (synchronised) gate is open.
//     The counter is a pipelined set of 4-bit slices with registered carries,
//     so every RO-domain path is one LUT level and works at several hundred MHz.
//   * The latched count is handed to the reference domain with a toggle
//     handshake. o_count is the raw edge count: f_RO[Hz] = o_count * 100 for the
//     default 10 ms gate. No division is done in hardware.
//   * If no new measurement arrives for TIMEOUT_TICKS cycles the oscillator is
//     declared dead: o_alive = 0 and o_count = 0 (never a stale value).
//////////////////////////////////////////////////////////////////////////////////

module frequency_counter #(
    parameter GATE_TICKS    = 1000000,  // gate-open time in clk cycles
    parameter GUARD_TICKS   = 64,       // gate-closed time in clk cycles
    parameter TIMEOUT_TICKS = 3500000   // no measurement for this long => dead
)(
    input  wire        clk,        // reference clock
    input  wire        rst,        // synchronous, active high
    input  wire        i_ro_clk,   // ring oscillator output
    output reg  [23:0] o_count,    // RO edges counted in one gate window
    output reg         o_valid,    // pulses when o_count is fresh
    output reg         o_alive     // 1 = oscillator is producing measurements
);

    // -------------------------------------------------------------------------
    // Reference domain: gate generator
    // -------------------------------------------------------------------------
    localparam PERIOD = GATE_TICKS + GUARD_TICKS;

    reg [20:0] gate_cnt;
    reg        gate_ref;

    always @(posedge clk) begin
        if (rst) begin
            gate_cnt <= 21'd0;
            gate_ref <= 1'b0;
        end else if (gate_cnt == PERIOD - 1) begin
            gate_cnt <= 21'd0;
            gate_ref <= 1'b1;
        end else begin
            gate_cnt <= gate_cnt + 21'd1;
            if (gate_cnt == GATE_TICKS - 1)
                gate_ref <= 1'b0;
        end
    end

    // -------------------------------------------------------------------------
    // RO domain: synchronise gate, count edges, latch result.
    // No reset here (the RO clock may not exist); state is initialised by the
    // bitstream and re-armed by every gate rising edge.
    // -------------------------------------------------------------------------
    localparam ST_IDLE  = 2'd0;
    localparam ST_COUNT = 2'd1;
    localparam ST_FLUSH = 2'd2;

    // Divide-by-2 prescaler: the only logic that runs at the full RO rate is this one toggle
    // flip-flop (about 1 ns of logic), so the counting logic below runs at half speed and
    // keeps up with oscillators of 450 MHz and more. Counts are doubled when latched.
    reg ro_div = 1'b0;
    always @(posedge i_ro_clk) ro_div <= ~ro_div;

    (* ASYNC_REG = "TRUE" *) reg g1 = 1'b0;
    (* ASYNC_REG = "TRUE" *) reg g2 = 1'b0;
    reg g3 = 1'b0;

    reg [1:0]  st = ST_IDLE;
    reg [3:0]  flush = 4'd0;
    reg        lat_en = 1'b0;

    reg [3:0]  s0 = 4'd0, s1 = 4'd0, s2 = 4'd0, s3 = 4'd0, s4 = 4'd0, s5 = 4'd0;
    reg        c0 = 1'b0, c1 = 1'b0, c2 = 1'b0, c3 = 1'b0, c4 = 1'b0;

    reg [23:0] latched = 24'd0;
    reg        done_tog = 1'b0;

    // "start" is registered: it clears 24 counter flops, and decoding the FSM state straight
    // into that fan-out was the slowest path in the oscillator domain. The one-cycle delay
    // shifts every measurement by exactly one edge (about 0.00002 %), which is negligible.
    wire start_pre = (st == ST_IDLE) && g2 && !g3;
    reg  start = 1'b0;
    wire stop  = (st == ST_COUNT) && !g2 && g3;

    always @(posedge ro_div) start <= start_pre;

    always @(posedge ro_div) begin
        g1 <= gate_ref;
        g2 <= g1;
        g3 <= g2;

        // Registered carries between 4-bit slices
        c0 <= (st == ST_COUNT) && (s0 == 4'hF);
        c1 <= c0 && (s1 == 4'hF);
        c2 <= c1 && (s2 == 4'hF);
        c3 <= c2 && (s3 == 4'hF);
        c4 <= c3 && (s4 == 4'hF);

        if (start) begin
            s0 <= 4'd0; s1 <= 4'd0; s2 <= 4'd0;
            s3 <= 4'd0; s4 <= 4'd0; s5 <= 4'd0;
        end else begin
            if (st == ST_COUNT) s0 <= s0 + 4'd1;
            s1 <= s1 + {3'd0, c0};
            s2 <= s2 + {3'd0, c1};
            s3 <= s3 + {3'd0, c2};
            s4 <= s4 + {3'd0, c3};
            s5 <= s5 + {3'd0, c4};
        end

        case (st)
            ST_IDLE: begin
                if (start) st <= ST_COUNT;
            end
            ST_COUNT: begin
                if (stop) begin
                    st    <= ST_FLUSH;
                    flush <= 4'd0;
                end
            end
            ST_FLUSH: begin
                // let the carry pipeline drain before latching
                flush <= flush + 4'd1;
            end
            default: st <= ST_IDLE;
        endcase

        // registered latch enable (keeps the 24-bit CE off a compare path)
        lat_en <= (st == ST_FLUSH) && (flush == 4'd8);
        if (lat_en) begin
            latched  <= {s5, s4, s3, s2, s1, s0} << 1;   // x2: ro_div counts every other RO edge
            done_tog <= ~done_tog;
            st       <= ST_IDLE;
        end
    end

    // -------------------------------------------------------------------------
    // Reference domain: receive result, watchdog for a dead oscillator
    // -------------------------------------------------------------------------
    (* ASYNC_REG = "TRUE" *) reg [1:0] tog_sync;
    reg        tog_prev;
    reg [21:0] idle_cnt;

    always @(posedge clk) begin
        if (rst) begin
            tog_sync <= 2'b00;
            tog_prev <= 1'b0;
            idle_cnt <= 22'd0;
            o_count  <= 24'd0;
            o_valid  <= 1'b0;
            o_alive  <= 1'b0;
        end else begin
            tog_sync <= {tog_sync[0], done_tog};
            tog_prev <= tog_sync[1];
            o_valid  <= 1'b0;

            if (tog_sync[1] != tog_prev) begin
                o_count  <= latched;
                o_valid  <= 1'b1;
                o_alive  <= 1'b1;
                idle_cnt <= 22'd0;
            end else if (idle_cnt < TIMEOUT_TICKS) begin
                idle_cnt <= idle_cnt + 22'd1;
            end else begin
                o_alive <= 1'b0;
                o_count <= 24'd0;
            end
        end
    end

endmodule
