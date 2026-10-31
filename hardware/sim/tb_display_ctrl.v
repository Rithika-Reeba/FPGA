`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Self-checking testbench for display_ctrl: scans the multiplexed display like a human
// eye would, decodes the segments and checks every page.
//////////////////////////////////////////////////////////////////////////////////

module tb_display_ctrl;

    reg         clk = 1'b0;
    reg         rst = 1'b1;
    reg  [23:0] cnt1 = 24'd4318000;   // 431.8 MHz
    reg  [23:0] cnt2 = 24'd4515600;   // 451.56 MHz
    reg  [23:0] cnt3 = 24'd0;         // dead oscillator
    reg  [23:0] cnt4 = 24'd4560990;   // 456.1 MHz
    reg  [11:0] temp_code = 12'h9FB;  // 2555 -> 41.2 degC
    wire [6:0]  seg;
    wire        dp_n;
    wire [3:0]  an;

    always #5 clk = ~clk;

    display_ctrl #(.PAGE_TICKS(400000)) dut (
        .clk(clk), .rst(rst),
        .i_cnt1(cnt1), .i_cnt2(cnt2), .i_cnt3(cnt3), .i_cnt4(cnt4),
        .i_temp_code(temp_code),
        .o_seg(seg), .o_dp_n(dp_n), .o_an(an)
    );

    // decode helper: returns '0'..'9', 'C' or ' '
    function [7:0] decode;
        input [6:0] s;
        begin
            case (s)
                7'b1000000: decode = "0";
                7'b1111001: decode = "1";
                7'b0100100: decode = "2";
                7'b0110000: decode = "3";
                7'b0011001: decode = "4";
                7'b0010010: decode = "5";
                7'b0000010: decode = "6";
                7'b1111000: decode = "7";
                7'b0000000: decode = "8";
                7'b0010000: decode = "9";
                7'b1000110: decode = "C";
                7'b1111111: decode = " ";
                default:    decode = "?";
            endcase
        end
    endfunction

    reg [7:0] c3, c2, c1, c0;      // characters seen on digit 3 (left) .. 0 (right)
    reg       d3, d2, d1, d0;      // decimal points

    // sample all four digits over one full scan
    task scan;
        integer n;
        begin
            for (n = 0; n < 300000; n = n + 1) begin
                @(posedge clk);
                case (an)
                    4'b1110: begin c0 = decode(seg); d0 = ~dp_n; end
                    4'b1101: begin c1 = decode(seg); d1 = ~dp_n; end
                    4'b1011: begin c2 = decode(seg); d2 = ~dp_n; end
                    4'b0111: begin c3 = decode(seg); d3 = ~dp_n; end
                    default: ;
                endcase
            end
        end
    endtask

    integer errors = 0;
    task check;
        input cond;
        input [8*50-1:0] msg;
        begin
            if (cond) $display("  PASS: %0s", msg);
            else begin $display("  FAIL: %0s", msg); errors = errors + 1; end
        end
    endtask

    task show;
        begin
            $display("  display: %c%s%c%s%c%s%c%s", c3, d3 ? "." : "", c2, d2 ? "." : "",
                     c1, d1 ? "." : "", c0, d0 ? "." : "");
        end
    endtask

    initial begin
        #200 rst = 1'b0;

        // page 0 is shown first (conversions take ~30 clocks, well inside one page)
        #(5000 * 10);
        scan; show;
        check(c3 == "1" && d3 && c2 == "4" && c1 == "3" && c0 == "1", "page 0: R1 431 MHz  -> 1.431");

        wait (dut.page == 3'd1);
        #(5000 * 10);
        scan; show;
        check(c3 == "2" && d3 && c2 == "4" && c1 == "5" && c0 == "1", "page 1: R2 451 MHz  -> 2.451");

        wait (dut.page == 3'd2);
        #(5000 * 10);
        scan; show;
        check(c3 == "3" && d3 && c2 == "0" && c1 == "0" && c0 == "0", "page 2: R3 dead     -> 3.000");

        wait (dut.page == 3'd3);
        #(5000 * 10);
        scan; show;
        check(c3 == "4" && d3 && c2 == "4" && c1 == "5" && c0 == "6", "page 3: R4 456 MHz  -> 4.456");

        wait (dut.page == 3'd4);
        #(5000 * 10);
        scan; show;
        check(c3 == "4" && c2 == "1" && d2 && c1 == "2" && c0 == "C", "page 4: 41.2 degC    -> 41.2C");

        wait (dut.page == 3'd0);          // wraps around
        check(1'b1, "page sequence wraps back to page 0");

        $display("");
        if (errors == 0) $display("ALL TESTS PASSED");
        else             $display("TESTS FAILED: %0d error(s)", errors);
        $finish;
    end

    initial begin
        #80000000;
        $display("FAIL: simulation timeout");
        $finish;
    end

endmodule
