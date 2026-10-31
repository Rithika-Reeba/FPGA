`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: fpga_health_top
// Description: Four-region FPGA health monitor for the Digilent Basys 3.
//
//   * u_region1..u_region4 each hold a ring-oscillator sensor, edge counter and a
//     stress generator (fenced into Pblocks R1..R4 by the floorplan script).
//   * One XADC reader supplies die temperature and VCCINT/VCCAUX/VCCBRAM.
//   * Raw readings stream over UART as ASCII-hex lines (see packet_formatter).
//   * Health is judged against a per-region BASELINE captured on the board:
//     press btnU while the board is in a known-good state to calibrate.
//       Warning  : region RO count dropped by more than 1/2^WARN_SHIFT of baseline
//       Degraded : dropped by more than 1/2^DEG_SHIFT, or the oscillator stopped,
//                  or temperature / supply voltage left their limits.
//
// Controls:
//   btnC      reset                    btnU     capture baseline (calibrate)
//   sw[0]     1 = HELLO link test      sw[1]    1 = halt all ring oscillators
//   sw[12..15] stress region R1..R4 (self-limiting on temperature / VCCINT)
// LEDs (each LED sits under its switch):
//   led[0], led[1]      sw0 / sw1: slow blink = switch off (has a function), solid = on
//   led[2] healthy   led[3] warning   led[4] degraded   (all three off = not calibrated yet)
//   led[11:5]           mirror sw[11:5] (those switches have no function)
//   led[12..15]         stress switches R1..R4: slow blink = off, solid = heaters running,
//                       fast blink = switch on but the safety cut-out is holding them off
//////////////////////////////////////////////////////////////////////////////////

module fpga_health_top #(
    parameter GATE_TICKS    = 1000000,   // 10 ms gate
    parameter TIMEOUT_TICKS = 3500000,   // 35 ms without a measurement => RO dead
    parameter STRESS_LUTS   = 512,       // heater LUTs per region
    parameter TRANSMIT_HZ   = 2,
    parameter UART_BAUD     = 115200,
    parameter WARN_SHIFT    = 8,         // 1/256 = 0.39 % drop => warning
    parameter DEG_SHIFT     = 6,         // 1/64  = 1.56 % drop => degraded
    parameter REGION_QUORUM = 2,         // regions that must be bad before the overall state changes
    parameter PAGE_TICKS    = 200000000, // display page time (2 s)
    parameter [15:0] BUILD_ID = 16'h0001  // set by build_bitstream.tcl; baselines are tied to it
)(
    input  wire        clk,
    input  wire        btnC,
    input  wire        btnU,
    input  wire [15:0] sw,
    output wire [15:0] led,
    output wire        RsTx,
    output wire [6:0]  seg,        // seven-segment display (active low)
    output wire        dp,
    output wire [3:0]  an
);

    // -------------------------------------------------------------------------
    // Reset: asynchronous assert, synchronous release
    // -------------------------------------------------------------------------
    reg [2:0] rst_pipe = 3'b111;
    always @(posedge clk or posedge btnC) begin
        if (btnC) rst_pipe <= 3'b111;
        else      rst_pipe <= {rst_pipe[1:0], 1'b0};
    end
    wire rst = rst_pipe[2];

    // Synchronised inputs
    reg [1:0] bu_s = 2'b00;
    reg       bu_d = 1'b0;
    always @(posedge clk) begin
        bu_s <= {bu_s[0], btnU};
        bu_d <= bu_s[1];
    end
    wire cal_req = bu_s[1] & ~bu_d;

    reg [3:0] sw_s0 = 4'd0, sw_s1 = 4'd0;      // stress switches
    reg       ro_halt_s0 = 1'b0, ro_halt_s1 = 1'b0;
    always @(posedge clk) begin
        sw_s0      <= sw[15:12];
        sw_s1      <= sw_s0;
        ro_halt_s0 <= sw[1];
        ro_halt_s1 <= ro_halt_s0;
    end
    wire ro_enable = ~ro_halt_s1;

    // -------------------------------------------------------------------------
    // Heartbeat
    // -------------------------------------------------------------------------
    reg [26:0] hb_cnt = 27'd0;
    reg        hb_led = 1'b0;
    always @(posedge clk) begin
        if (hb_cnt == 27'd49999999) begin
            hb_cnt <= 27'd0;
            hb_led <= ~hb_led;
        end else begin
            hb_cnt <= hb_cnt + 27'd1;
        end
    end

    // -------------------------------------------------------------------------
    // XADC sensors (raw codes)
    // -------------------------------------------------------------------------
    wire [11:0] temp_code, vccint_code, vccaux_code, vccbram_code;
    wire        sensors_valid, sensors_ready;

    xadc_sensor_reader u_xadc_reader (
        .clk(clk),
        .rst(rst),
        .o_temp(temp_code),
        .o_vccint(vccint_code),
        .o_vccaux(vccaux_code),
        .o_vccbram(vccbram_code),
        .o_valid(sensors_valid),
        .o_ready(sensors_ready)
    );

    // Limits in raw XADC codes (temp: code*503.975/4096-273.15 ; volt: code*3/4096)
    localparam [11:0] T_WARN      = 12'd2708;   // ~60 degC
    localparam [11:0] T_DEG       = 12'd2789;   // ~70 degC
    localparam [11:0] T_STRESS_ON = 12'd2748;   // stress may resume below ~65 degC
    localparam [11:0] T_CAL_MAX   = 12'd2594;   // btnU calibrates only below ~46 degC

    localparam [11:0] VI_WARN_LO = 12'd1297, VI_WARN_HI = 12'd1433;   // 1.0 V +/-5 %
    localparam [11:0] VI_DEG_LO  = 12'd1229, VI_DEG_HI  = 12'd1501;   // 1.0 V +/-10 %
    localparam [11:0] VA_WARN_LO = 12'd2335, VA_WARN_HI = 12'd2581;   // 1.8 V +/-5 %
    localparam [11:0] VA_DEG_LO  = 12'd2212, VA_DEG_HI  = 12'd2704;   // 1.8 V +/-10 %

    // Stress safety interlock with hysteresis
    reg stress_ok = 1'b0;
    always @(posedge clk) begin
        if (rst || !sensors_ready)
            stress_ok <= 1'b0;
        else if (temp_code >= T_DEG || vccint_code < VI_DEG_LO)
            stress_ok <= 1'b0;
        else if (temp_code <= T_STRESS_ON)
            stress_ok <= 1'b1;
    end
    wire [3:0] stress_en = sw_s1 & {4{stress_ok}};

    // -------------------------------------------------------------------------
    // Four regional health monitors
    // -------------------------------------------------------------------------
    wire [23:0] cnt1, cnt2, cnt3, cnt4;
    wire [3:0]  alive;
    wire [3:0]  rvalid;
    wire [3:0]  ro_clk_obs;

    regional_health_monitor #(.GATE_TICKS(GATE_TICKS), .TIMEOUT_TICKS(TIMEOUT_TICKS), .STRESS_LUTS(STRESS_LUTS))
    u_region1 (.clk(clk), .rst(rst), .i_en(ro_enable), .i_stress_en(stress_en[0]),
               .o_count(cnt1), .o_valid(rvalid[0]), .o_alive(alive[0]), .o_ro_clk(ro_clk_obs[0]));

    regional_health_monitor #(.GATE_TICKS(GATE_TICKS), .TIMEOUT_TICKS(TIMEOUT_TICKS), .STRESS_LUTS(STRESS_LUTS))
    u_region2 (.clk(clk), .rst(rst), .i_en(ro_enable), .i_stress_en(stress_en[1]),
               .o_count(cnt2), .o_valid(rvalid[1]), .o_alive(alive[1]), .o_ro_clk(ro_clk_obs[1]));

    regional_health_monitor #(.GATE_TICKS(GATE_TICKS), .TIMEOUT_TICKS(TIMEOUT_TICKS), .STRESS_LUTS(STRESS_LUTS))
    u_region3 (.clk(clk), .rst(rst), .i_en(ro_enable), .i_stress_en(stress_en[2]),
               .o_count(cnt3), .o_valid(rvalid[2]), .o_alive(alive[2]), .o_ro_clk(ro_clk_obs[2]));

    regional_health_monitor #(.GATE_TICKS(GATE_TICKS), .TIMEOUT_TICKS(TIMEOUT_TICKS), .STRESS_LUTS(STRESS_LUTS))
    u_region4 (.clk(clk), .rst(rst), .i_en(ro_enable), .i_stress_en(stress_en[3]),
               .o_count(cnt4), .o_valid(rvalid[3]), .o_alive(alive[3]), .o_ro_clk(ro_clk_obs[3]));

    // -------------------------------------------------------------------------
    // Baseline capture (btnU)
    // -------------------------------------------------------------------------
    reg [23:0] base1 = 24'd0, base2 = 24'd0, base3 = 24'd0, base4 = 24'd0;
    reg        calibrated = 1'b0;

    always @(posedge clk) begin
        if (rst) begin
            calibrated <= 1'b0;
        end else if (cal_req && (&alive) && sensors_ready && temp_code < T_CAL_MAX && (sw_s1 == 4'd0)) begin
            // refused while hot, while a stress switch is up, or while any oscillator is dead:
            // a hot or stressed board must never be recorded as the healthy reference
            base1 <= cnt1;
            base2 <= cnt2;
            base3 <= cnt3;
            base4 <= cnt4;
            calibrated <= 1'b1;
        end
    end

    // -------------------------------------------------------------------------
    // Verdicts: 0 = not calibrated, 1 = healthy, 2 = warning, 3 = degraded
    // -------------------------------------------------------------------------
    function [1:0] region_verdict;
        input        is_alive;
        input [23:0] cnt;
        input [23:0] base;
        input        calib;
        reg   [23:0] d_warn, d_deg;
        begin
            d_warn = base >> WARN_SHIFT;
            d_deg  = base >> DEG_SHIFT;
            if (!is_alive)                   region_verdict = 2'd3;
            else if (!calib)                 region_verdict = 2'd0;
            else if (cnt < base - d_deg)     region_verdict = 2'd3;
            else if (cnt < base - d_warn)    region_verdict = 2'd2;
            else                             region_verdict = 2'd1;
        end
    endfunction

    wire [1:0] rv1 = region_verdict(alive[0], cnt1, base1, calibrated);
    wire [1:0] rv2 = region_verdict(alive[1], cnt2, base2, calibrated);
    wire [1:0] rv3 = region_verdict(alive[2], cnt3, base3, calibrated);
    wire [1:0] rv4 = region_verdict(alive[3], cnt4, base4, calibrated);

    wire sens_deg  = (temp_code >= T_DEG)
                  || (vccint_code  < VI_DEG_LO) || (vccint_code  > VI_DEG_HI)
                  || (vccaux_code  < VA_DEG_LO) || (vccaux_code  > VA_DEG_HI)
                  || (vccbram_code < VI_DEG_LO) || (vccbram_code > VI_DEG_HI);
    wire sens_warn = (temp_code >= T_WARN)
                  || (vccint_code  < VI_WARN_LO) || (vccint_code  > VI_WARN_HI)
                  || (vccaux_code  < VA_WARN_LO) || (vccaux_code  > VA_WARN_HI)
                  || (vccbram_code < VI_WARN_LO) || (vccbram_code > VI_WARN_HI);
    wire [1:0] sv = !sensors_ready ? 2'd0 : sens_deg ? 2'd3 : sens_warn ? 2'd2 : 2'd1;

    // Region quorum (same policy as the dashboard, health_rules.REGION_QUORUM): the overall
    // state follows the regions only when at least REGION_QUORUM of them are warning/degraded.
    // A single bad region is still shown on its own LED (led[11:8]). Sensor limits always apply.
    wire [2:0] n_deg  = (rv1 == 2'd3) + (rv2 == 2'd3) + (rv3 == 2'd3) + (rv4 == 2'd3);
    wire [2:0] n_warn = (rv1 == 2'd2) + (rv2 == 2'd2) + (rv3 == 2'd2) + (rv4 == 2'd2);
    wire       region_quorum = (n_deg + n_warn) >= REGION_QUORUM;
    wire       region_deg    = region_quorum && (n_deg  != 3'd0);
    wire       region_warn   = region_quorum && (n_deg  == 3'd0) && (n_warn != 3'd0);

    wire any_uncal = (rv1 == 2'd0) | (rv2 == 2'd0) | (rv3 == 2'd0) | (rv4 == 2'd0) | (sv == 2'd0);
    // A dead oscillator is a SENSOR FAULT, never evidence of health: the quorum must not outvote it,
    // so the overall state is at least Warning (Degraded still needs the quorum or a sensor limit).
    wire sensor_fault = ~(&alive);
    wire [1:0] verdict = (region_deg  || sv == 2'd3)                 ? 2'd3 :
                         (region_warn || sv == 2'd2 || sensor_fault) ? 2'd2 :
                         any_uncal                                     ? 2'd0 : 2'd1;

    // -------------------------------------------------------------------------
    // UART telemetry
    // -------------------------------------------------------------------------
    wire       tx_valid, tx_active, uart_busy;
    wire [7:0] tx_data;

    packet_formatter #(
        .CLK_FREQ_HZ(100000000),
        .TRANSMIT_HZ(TRANSMIT_HZ)
    ) u_formatter (
        .clk(clk),
        .rst(rst),
        .i_mode_select(sw[0]),
        .i_cnt1(cnt1), .i_cnt2(cnt2), .i_cnt3(cnt3), .i_cnt4(cnt4),
        .i_alive(alive),
        .i_stress(sw_s1),            // switch positions (the LEDs show whether the heaters really run)
        .i_temp(temp_code),
        .i_vccint(vccint_code),
        .i_vccaux(vccaux_code),
        .i_vccbram(vccbram_code),
        .i_verdict(verdict),
        .i_build_id(BUILD_ID),
        .i_uart_busy(uart_busy),
        .o_uart_valid(tx_valid),
        .o_uart_data(tx_data),
        .o_tx_active(tx_active)
    );

    uart_tx #(
        .CLK_FREQ_HZ(100000000),
        .BAUD_RATE(UART_BAUD)
    ) u_uart_tx (
        .clk(clk),
        .rst(rst),
        .i_valid(tx_valid),
        .i_data(tx_data),
        .o_tx(RsTx),
        .o_busy(uart_busy),
        .o_done()
    );

    // -------------------------------------------------------------------------
    // LEDs
    // -------------------------------------------------------------------------
    // Four-digit display: R1..R4 frequency ("1.431" = R1 at 431 MHz) then die temperature ("41.6C")
    display_ctrl #(.PAGE_TICKS(PAGE_TICKS)) u_display (
        .clk(clk),
        .rst(rst),
        .i_cnt1(cnt1), .i_cnt2(cnt2), .i_cnt3(cnt3), .i_cnt4(cnt4),
        .i_temp_code(temp_code),
        .o_seg(seg),
        .o_dp_n(dp),
        .o_an(an)
    );

    // Each LED sits under its switch on the Basys 3, so the LEDs follow the switches:
    //   switch WITH a function (sw0, sw1, sw12..15): LED blinks slowly while the switch is
    //   off ("this switch does something") and is solid once it is on.
    //   stress switches: solid = heaters really running, fast blink = switch on but the
    //   safety cut-out (temperature / VCCINT) is holding the heaters off.
    //   switch WITHOUT a function (sw5..11): LED simply mirrors the switch.
    // led[2..4] are the health lights (they sit under switches that have no function).
    wire blink_slow = hb_led;            // about 1 Hz
    wire blink_fast = hb_cnt[24];        // about 3 Hz

    assign led[0]     = sw[0]  ? 1'b1 : blink_slow;        // HELLO link-test mode
    assign led[1]     = sw[1]  ? 1'b1 : blink_slow;        // halt ring oscillators
    assign led[2]     = (verdict == 2'd1);                 // healthy
    assign led[3]     = (verdict == 2'd2);                 // warning
    assign led[4]     = (verdict == 2'd3);                 // degraded
    assign led[11:5]  = sw[11:5];                          // no function: mirror the switch
    assign led[12]    = sw[12] ? (stress_en[0] ? 1'b1 : blink_fast) : blink_slow;   // stress R1
    assign led[13]    = sw[13] ? (stress_en[1] ? 1'b1 : blink_fast) : blink_slow;   // stress R2
    assign led[14]    = sw[14] ? (stress_en[2] ? 1'b1 : blink_fast) : blink_slow;   // stress R3
    assign led[15]    = sw[15] ? (stress_en[3] ? 1'b1 : blink_fast) : blink_slow;   // stress R4

endmodule
