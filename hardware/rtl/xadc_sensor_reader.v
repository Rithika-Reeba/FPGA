`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: xadc_sensor_reader
// Description: Reads die temperature and VCCINT / VCCAUX / VCCBRAM from the
//              Artix-7 XADC over the DRP port and outputs the RAW 12-bit codes.
//              No arithmetic is done on the FPGA; conversion is done on the host:
//                temp [degC] = code * 503.975 / 4096 - 273.15
//                volt [V]    = code * 3 / 4096
//
// Configuration is the same as the XADC Wizard setup proven in fpga_test
// (INIT_40 = 0x1000: 16-sample averaging, INIT_41 = 0x21A0: continuous
// sequencer, INIT_42 = 0x0400: DCLK/4). Reads are triggered by EOS.
//
// Under SIMULATION the XADC primitive is replaced by a small behavioural model.
//////////////////////////////////////////////////////////////////////////////////

module xadc_sensor_reader (
    input  wire        clk,
    input  wire        rst,          // synchronous, active high
    output reg  [11:0] o_temp,
    output reg  [11:0] o_vccint,
    output reg  [11:0] o_vccaux,
    output reg  [11:0] o_vccbram,
    output reg         o_valid,      // pulses after each full set of four reads
    output reg         o_ready       // sticky: at least one full set has been read
);

    reg  [6:0]  daddr = 7'h00;
    reg         den   = 1'b0;
    wire        drdy;
    wire [15:0] do_out;
    wire        eos;

`ifdef SIMULATION
    // ---- behavioural XADC stand-in ------------------------------------------
    reg [15:0] m_do    = 16'h0000;
    reg        m_drdy  = 1'b0;
    reg        m_eos   = 1'b0;
    reg        m_pend  = 1'b0;
    reg [2:0]  m_dly   = 3'd0;
    reg [6:0]  m_addr  = 7'h00;
    reg [11:0] m_eos_c = 12'd0;
    assign drdy   = m_drdy;
    assign do_out = m_do;
    assign eos    = m_eos;

    always @(posedge clk) begin
        m_drdy <= 1'b0;
        m_eos  <= 1'b0;
        m_eos_c <= m_eos_c + 12'd1;
        if (m_eos_c == 12'd1999) begin
            m_eos_c <= 12'd0;
            m_eos   <= 1'b1;
        end
        if (den) begin
            m_pend <= 1'b1;
            m_dly  <= 3'd4;
            m_addr <= daddr;
        end else if (m_pend) begin
            if (m_dly == 3'd0) begin
                m_pend <= 1'b0;
                m_drdy <= 1'b1;
                case (m_addr)
                    7'h00:   m_do <= {12'h994, 4'h0};  // ~28.5 degC
                    7'h01:   m_do <= {12'h555, 4'h0};  // 1.000 V
                    7'h02:   m_do <= {12'h99A, 4'h0};  // 1.800 V
                    7'h06:   m_do <= {12'h555, 4'h0};  // 1.000 V
                    default: m_do <= 16'h0000;
                endcase
            end else begin
                m_dly <= m_dly - 3'd1;
            end
        end
    end
`else
    XADC #(
        .INIT_40(16'h1000),
        .INIT_41(16'h21A0),
        .INIT_42(16'h0400),
        .INIT_43(16'h0000),
        .INIT_44(16'h0000),
        .INIT_45(16'h0000),
        .INIT_46(16'h0000),
        .INIT_47(16'h0000),
        .INIT_48(16'h4700),   // temp, VCCINT, VCCAUX, VCCBRAM
        .INIT_49(16'h0000),
        .INIT_4A(16'h4700),   // average temp, VCCINT, VCCAUX, VCCBRAM (16 samples, per INIT_40)
        .INIT_4B(16'h0000),
        .INIT_4C(16'h0000),
        .INIT_4D(16'h0000),
        .INIT_4E(16'h0000),
        .INIT_4F(16'h0000),
        .SIM_MONITOR_FILE("design.txt")
    ) u_xadc (
        .DCLK(clk),
        .RESET(rst),
        .DEN(den),
        .DWE(1'b0),
        .DADDR(daddr),
        .DI(16'h0000),
        .DO(do_out),
        .DRDY(drdy),
        .VP(1'b0),
        .VN(1'b0),
        .VAUXP(16'h0000),
        .VAUXN(16'h0000),
        .CONVST(1'b0),
        .CONVSTCLK(1'b0),
        .ALM(),
        .OT(),
        .BUSY(),
        .CHANNEL(),
        .EOC(),
        .EOS(eos),
        .JTAGBUSY(),
        .JTAGLOCKED(),
        .JTAGMODIFIED(),
        .MUXADDR()
    );
`endif

    localparam S_WAIT_EOS = 4'd0;
    localparam S_RD_T     = 4'd1;
    localparam S_WT_T     = 4'd2;
    localparam S_RD_I     = 4'd3;
    localparam S_WT_I     = 4'd4;
    localparam S_RD_A     = 4'd5;
    localparam S_WT_A     = 4'd6;
    localparam S_RD_B     = 4'd7;
    localparam S_WT_B     = 4'd8;

    reg [3:0] state = S_WAIT_EOS;

    always @(posedge clk) begin
        den     <= 1'b0;
        o_valid <= 1'b0;

        if (rst) begin
            state     <= S_WAIT_EOS;
            o_temp    <= 12'd0;
            o_vccint  <= 12'd0;
            o_vccaux  <= 12'd0;
            o_vccbram <= 12'd0;
            o_ready   <= 1'b0;
        end else begin
            case (state)
                S_WAIT_EOS: if (eos) state <= S_RD_T;

                S_RD_T: begin daddr <= 7'h00; den <= 1'b1; state <= S_WT_T; end
                S_WT_T: if (drdy) begin o_temp <= do_out[15:4]; state <= S_RD_I; end

                S_RD_I: begin daddr <= 7'h01; den <= 1'b1; state <= S_WT_I; end
                S_WT_I: if (drdy) begin o_vccint <= do_out[15:4]; state <= S_RD_A; end

                S_RD_A: begin daddr <= 7'h02; den <= 1'b1; state <= S_WT_A; end
                S_WT_A: if (drdy) begin o_vccaux <= do_out[15:4]; state <= S_RD_B; end

                S_RD_B: begin daddr <= 7'h06; den <= 1'b1; state <= S_WT_B; end
                S_WT_B: if (drdy) begin
                    o_vccbram <= do_out[15:4];
                    o_valid   <= 1'b1;
                    o_ready   <= 1'b1;
                    state     <= S_WAIT_EOS;
                end

                default: state <= S_WAIT_EOS;
            endcase
        end
    end

endmodule
