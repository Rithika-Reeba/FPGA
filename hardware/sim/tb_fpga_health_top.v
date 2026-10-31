`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Self-checking testbench for fpga_health_top (run with -d SIMULATION).
//
// Speed-ups: 100 us gate, 3.125 Mbaud UART, 1 kHz telemetry, 20 MHz sim RO,
// behavioural XADC stub, heaters tied off. Checks:
//   1. packets are well formed and carry the expected counts / sensor codes
//   2. verdict is 0 (not calibrated) until btnU is pressed, then 1 (healthy)
//   3. a halted oscillator is reported dead (F=0, count 0) and verdict 3
//   4. recovery after the oscillator restarts
//////////////////////////////////////////////////////////////////////////////////

module tb_fpga_health_top;

    reg         clk = 1'b0;
    reg         btnC = 1'b0;
    reg         btnU = 1'b0;
    reg  [15:0] sw   = 16'h0002;   // sw[1] = 1 -> ring oscillators halted at start
    wire [15:0] led;
    wire        RsTx;

    always #5 clk = ~clk;

    fpga_health_top #(
        .GATE_TICKS(10000),
        .TIMEOUT_TICKS(40000),
        .STRESS_LUTS(4),
        .TRANSMIT_HZ(1000),
        .UART_BAUD(3125000)
    ) dut (
        .clk(clk), .btnC(btnC), .btnU(btnU), .sw(sw), .led(led), .RsTx(RsTx)
    );

    // Slow the simulated ring oscillators down: period = 2*5*5 ns = 50 ns (20 MHz)
    defparam dut.u_region1.u_ring_osc.STAGE_DELAY_NS = 5.0;
    defparam dut.u_region2.u_ring_osc.STAGE_DELAY_NS = 5.0;
    defparam dut.u_region3.u_ring_osc.STAGE_DELAY_NS = 5.0;
    defparam dut.u_region4.u_ring_osc.STAGE_DELAY_NS = 5.0;

    // -------------------------------------------------------------------------
    // UART receiver (32 clk per bit = 320 ns)
    // -------------------------------------------------------------------------
    localparam BIT_NS = 320;

    reg [7:0] cur [0:127];
    reg [7:0] last [0:127];
    integer   cur_len = 0;
    integer   last_len = 0;
    integer   line_count = 0;
    reg [7:0] rx_byte;
    integer   i, k;

    always begin
        @(negedge RsTx);
        #(BIT_NS + BIT_NS/2);
        for (i = 0; i < 8; i = i + 1) begin
            rx_byte[i] = RsTx;
            #(BIT_NS);
        end
        cur[cur_len] = rx_byte;
        cur_len = cur_len + 1;
        if (rx_byte == 8'h0A) begin
            for (k = 0; k < cur_len; k = k + 1) last[k] = cur[k];
            last_len   = cur_len;
            cur_len    = 0;
            line_count = line_count + 1;
        end
    end

    function [7:0] ch;
        input integer pos;
        begin ch = last[pos]; end
    endfunction

    function [3:0] nib;
        input [7:0] c;
        begin
            if (c >= "0" && c <= "9") nib = c - "0";
            else                      nib = c - "A" + 4'd10;
        end
    endfunction

    function [23:0] hexval;
        input integer start;
        input integer len;
        integer j;
        begin
            hexval = 24'd0;
            for (j = 0; j < len; j = j + 1)
                hexval = {hexval[19:0], nib(last[start + j])};
        end
    endfunction

    // -------------------------------------------------------------------------
    // Check helpers
    // -------------------------------------------------------------------------
    integer errors = 0;
    integer target;

    task check;
        input cond;
        input [8*60-1:0] msg;
        begin
            if (cond) $display("  PASS: %0s", msg);
            else begin
                $display("  FAIL: %0s", msg);
                errors = errors + 1;
            end
        end
    endtask

    task wait_lines;
        input integer n;
        begin
            target = line_count + n;
            wait (line_count >= target);
        end
    endtask

    task show_line;
        integer j;
        begin
            $write("  line: ");
            for (j = 0; j < last_len - 2; j = j + 1) $write("%c", last[j]);
            $write("\n");
        end
    endtask

    // field accessors on the most recent line
    function [23:0] f_r1; input dummy; begin f_r1 = hexval(3, 6);  end endfunction
    function [23:0] f_r4; input dummy; begin f_r4 = hexval(33, 6); end endfunction
    function [23:0] f_t;  input dummy; begin f_t  = hexval(42, 3); end endfunction
    function [23:0] f_i;  input dummy; begin f_i  = hexval(48, 3); end endfunction
    function [23:0] f_a;  input dummy; begin f_a  = hexval(54, 3); end endfunction
    function [23:0] f_f;  input dummy; begin f_f  = hexval(66, 1); end endfunction
    function [23:0] f_h;  input dummy; begin f_h  = hexval(74, 1); end endfunction
    function [23:0] f_s;  input dummy; begin f_s  = hexval(70, 1); end endfunction
    function [23:0] f_v;  input dummy; begin f_v  = hexval(78, 4); end endfunction

    // -------------------------------------------------------------------------
    // Test sequence
    // -------------------------------------------------------------------------
    initial begin
        #100  btnC = 1'b1;
        #200  btnC = 1'b0;
        #2000 sw[1] = 1'b0;                       // release the oscillators

        $display("== Phase 1: uncalibrated telemetry ==");
        wait_lines(3);
        show_line;
        check(last_len == 84,                "packet length is 84 bytes");
        check(ch(0) == "R" && ch(2) == "=",  "packet starts with R1=");
        check(f_r1(0) >= 24'd1990 && f_r1(0) <= 24'd2010, "R1 count ~2000 (20 MHz x 100 us)");
        check(f_r4(0) >= 24'd1990 && f_r4(0) <= 24'd2010, "R4 count ~2000");
        check(f_t(0) == 24'h994,             "temperature code from XADC stub");
        check(f_i(0) == 24'h555,             "VCCINT code from XADC stub");
        check(f_a(0) == 24'h99A,             "VCCAUX code from XADC stub");
        check(f_f(0) == 24'hF,               "all four oscillators alive");
        check(f_h(0) == 24'h0,               "verdict 0 = not calibrated");
        check(f_v(0) == 24'h0001,           "build ID V=0001 is reported in the packet");
        check(led[4:2] == 3'b000,           "health LEDs off while uncalibrated");

        $display("== Phase 2: calibrate with btnU ==");
        #1000 btnU = 1'b1;
        #200  btnU = 1'b0;
        wait_lines(3);
        show_line;
        check(f_h(0) == 24'h1,               "verdict 1 = healthy after calibration");
        check(led[2] == 1'b1,                "healthy LED lit");

        $display("== Phase 3: halt oscillators (simulated dead sensors) ==");
        sw[1] = 1'b1;
        wait_lines(4);
        show_line;
        check(f_f(0) == 24'h0,               "all oscillators reported dead");
        check(f_r1(0) == 24'd0,              "dead region reports count 0 (no stale value)");
        check(f_h(0) == 24'h3,               "verdict 3 = degraded");
        check(led[4] == 1'b1,                "degraded LED lit");

        $display("== Phase 4: oscillators restart ==");
        sw[1] = 1'b0;
        wait_lines(6);
        show_line;
        check(f_f(0) == 24'hF,               "oscillators alive again");
        check(f_h(0) == 24'h1,               "verdict back to healthy");

        $display("== Phase 5: quorum - one dead region does not change the overall state ==");
        force dut.u_region1.ro_clk = 1'b0;         // R1's oscillator stops (net is private to R1)
        wait_lines(4);
        show_line;
        check(f_f(0) == 24'hE,               "only R1 reported dead (F=E)");

        check(f_h(0) == 24'h2,               "one dead oscillator = sensor fault: at least Warning, never Healthy");

        $display("== Phase 6: quorum - two dead regions change the overall state ==");
        force dut.u_region2.ro_clk = 1'b0;         // R2's oscillator stops as well
        wait_lines(4);
        show_line;
        check(f_f(0) == 24'hC,               "R1 and R2 reported dead (F=C)");
        check(f_h(0) == 24'h3,               "overall degraded (quorum met)");
        release dut.u_region1.ro_clk;
        release dut.u_region2.ro_clk;
        wait_lines(6);
        check(f_h(0) == 24'h1,               "recovers to healthy after release");
        $display("== Phase 7: switch LEDs follow the switches ==");
        sw[5]  = 1'b1;                              // no function: LED mirrors the switch
        sw[12] = 1'b1;                              // stress R1 (sensors fine, so heaters may run)
        wait_lines(3);
        show_line;
        check(led[5]  == 1'b1,               "sw5 mirrored on led5");
        check(led[12] == 1'b1,               "sw12 on and heaters running -> led12 solid");
        check(f_s(0)  == 24'h1,              "packet reports stress active on R1 only");
        sw[5]  = 1'b0;
        sw[12] = 1'b0;
        wait_lines(2);
        check(led[5]  == 1'b0,               "sw5 off -> led5 off");
        $display("== Phase 8: btnU refuses to calibrate while a stress switch is up ==");
        #1000 btnC = 1'b1;
        #200  btnC = 1'b0;                          // reset: not calibrated again
        wait_lines(3);
        sw[13] = 1'b1;                              // stress switch up
        wait_lines(3);
        #1000 btnU = 1'b1;
        #200  btnU = 1'b0;
        wait_lines(3);
        check(f_h(0) == 24'h0,               "btnU refused while a stress switch is up (still not calibrated)");
        sw[13] = 1'b0;
        wait_lines(3);
        #1000 btnU = 1'b1;
        #200  btnU = 1'b0;
        wait_lines(3);
        check(f_h(0) == 24'h1,               "btnU calibrates once the switch is down");

        $display("");
        if (errors == 0) $display("ALL TESTS PASSED");
        else             $display("TESTS FAILED: %0d error(s)", errors);
        $finish;
    end

    // watchdog
    initial begin
        #120000000;
        $display("FAIL: simulation timeout (lines received: %0d)", line_count);
        $finish;
    end

endmodule
