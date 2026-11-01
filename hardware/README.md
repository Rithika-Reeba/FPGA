# Digilent Basys 3 FPGA Health Monitoring Hardware Implementation

Complete hardware RTL design, constraints, synthesis, and programming guide for the **AI-Assisted FPGA Health Monitoring System** on the **Digilent Basys 3** (Xilinx Artix-7 `XC7A35T-1CPG236C`).

---

## 1. Hardware Architecture Overview

```
+-------------------------------------------------------------------------------------------------+
|                                    DIGILENT BASYS 3 ARTIX-7                                     |
|                                                                                                 |
|   +--------------------------+    +--------------------------+    +-------------------------+   |
|   |   5-Stage Inverting      |    |   XADC Dual 12-bit       |    |   PRBS-7 Functional     |   |
|   |   Ring Oscillator (RO)   |    |   Sensor Sequencer       |    |   Error Rate Monitor    |   |
|   |   Aging Delay Sensor     |    |   Temp, VCCINT/AUX/BRAM  |    |   Pattern Checker       |   |
|   +------------+-------------+    +------------+-------------+    +------------+------------+   |
|                |                               |                               |                |
|                v                               v                               v                |
|   +--------------------------+    +--------------------------+    +-------------------------+   |
|   |  Frequency Counter       |    |  DRP 50ms Poller         |    |  Error Accumulator      |   |
|   |  10ms Gate Window (CDC)  |    |  Fixed-Point Scaler      |    |  10^6 Bit Epoch Counter |   |
|   +------------+-------------+    +------------+-------------+    +------------+------------+   |
|                |                               |                               |                |
|                +-------------------------------+-------------------------------+                |
|                                                |                                                |
|                                                v                                                |
|                              +-----------------------------------+                              |
|                              |   Telemetry Packet Formatter      |                              |
|                              |   ASCII JSON & Handshake Engine   |                              |
|                              +-----------------+-----------------+                              |
|                                                |                                                |
|                                                v                                                |
|                              +-----------------------------------+                              |
|                              |   UART Transmitter (115200 8N1)   |                              |
|                              |   Divisor = 868 @ 100.0 MHz ClkW5 |                              |
|                              +-----------------+-----------------+                              |
|                                                | Pin A18 (RsTx)                                 |
+------------------------------------------------|------------------------------------------------+
                                                 v
                                   FTDI FT2232HQ USB-UART Bridge
                                                 v
                                        Host PC (Windows COM)
```

---

## 2. Pin Mappings, Switches & Diagnostic LEDs

### Switch Definitions
| Switch | Pin | Function | Description |
| :--- | :--- | :--- | :--- |
| `sw[0]` | `V17` | **Telemetry mode** | `0`: telemetry stream (hex line, 2 per second)<br>`1`: `HELLO FPGA` link test |
| `sw[1]` | `V16` | **Halt ring oscillators** | `0`: oscillators run<br>`1`: all four halted (they then read as dead = Degraded) |
| `sw[12]`..`sw[15]` | `W2` `U1` `T1` `R2` | **Stress region R1..R4** | `1`: switches on that region's heater LUTs (accelerated thermal stress). Self-limiting: they cut out near 70 C or if VCCINT droops |
| `sw[2]`..`sw[11]` | | *no function* | |
| `btnU` | `T18` | **Calibrate** | Captures every region's current count as its baseline (do this while the board is healthy and no stress switch is on) |
| `btnC` | `U18` | **Reset** | |

### LED Definitions (each LED sits under its switch)
| LED | Meaning |
| :--- | :--- |
| `led[0]`, `led[1]` | `sw[0]` / `sw[1]`: **slow blink = switch off (it has a function), solid = switch on** |
| `led[2]` | Health: **HEALTHY** |
| `led[3]` | Health: **WARNING** |
| `led[4]` | Health: **DEGRADED** (all three off = not calibrated yet) |
| `led[5]`..`led[11]` | Mirror `sw[5]`..`sw[11]` (those switches have no function) |
| `led[12]`..`led[15]` | Stress R1..R4: **slow blink = switch off, solid = heaters really running, fast blink = switch on but the safety cut-out is holding the heaters off** |

### Four-digit display
It rotates every 2 seconds through five pages (no buttons needed):

| Page | Shows | Example |
| :--- | :--- | :--- |
| 1..4 | Region R1..R4 ring-oscillator frequency: region digit with a dot, then MHz | `1.431` = R1 at 431 MHz (`3.000` = R3 oscillator stopped) |
| 5 | Die temperature | `41.6C` |
Overall health follows the dashboard's rule: a region only changes the overall state when at least two regions are Warning/Degraded (`REGION_QUORUM` in `health_rules.py`); temperature and supply limits always count. All limits live in `health_rules.py`.
### Master Clock and Serial Pins
- **System Clock**: 100.0 MHz on Pin `W5` (`sys_clk_pin`, Period 10.0 ns)
- **Master Reset**: Pin `U18` (`btnC`, Active High)
- **UART Serial TX**: Pin `A18` (`RsTx` connected to USB-UART bridge)

---

## 3. Vivado Build & Programming Instructions

### Method A: Automated Batch Build (Command Line)

1. Open **Vivado Command Prompt** (or any shell where Vivado is on your `PATH`).
2. Navigate to the project root:
   ```powershell
   cd D:\Work\Personal\FPGA
   ```
3. Run synthesis, implementation, and bitstream generation:
   ```powershell
   vivado -mode batch -source hardware/vivado/build_bitstream.tcl
   ```
   The compiled bitstream will be generated at `hardware/build/fpga_health_top.bit`.

4. Plug in the Basys 3 board via USB and program it:
   ```powershell
   vivado -mode batch -source hardware/vivado/program_fpga.tcl
   ```

### Method B: Vivado GUI Project

1. Open Vivado and create a new project targeting `xc7a35tcpg236-1`.
2. Add all Verilog files from `hardware/rtl/`:
   - `uart_tx.v`
   - `ring_oscillator.v`
   - `frequency_counter.v`
   - `xadc_sensor_reader.v`
   - `error_rate_monitor.v`
   - `packet_formatter.v`
   - `fpga_health_top.v`
3. Add constraints from `hardware/constraints/basys3.xdc`.
4. Click **Generate Bitstream**.
5. Open **Hardware Manager** -> **Auto Connect** -> **Program Device**.

---

## 4. Telemetry Verification

### Step 1: Verify the serial stream
Open the board's COM port at **115200 baud, 8N1** (PuTTY, Tera Term, or `python hardware/host/health_reader.py --port COMx`). With `sw[0]` **down** you get two lines per second:
```text
R1=3180E8,R2=3C34B6,R3=436C92,R4=46D74A,T=A07,I=54E,A=99C,B=550,F=F,S=0,H=0,V=896F
```
| Field | Meaning |
| :--- | :--- |
| `R1`..`R4` | Ring-oscillator edge count per 10 ms gate (hex). MHz = count / 10000 |
| `T` `I` `A` `B` | Raw 12-bit XADC codes: die temperature, VCCINT, VCCAUX, VCCBRAM |
| `F` / `S` | Oscillator-alive / stress-active flags, one bit per region (R1 = bit 0) |
| `H` | On-board verdict: 0 not calibrated, 1 healthy, 2 warning, 3 degraded |
| `V` | Build ID of this bitstream (baselines are tied to it) |

With `sw[0]` up the board sends `HELLO FPGA` instead (link test).

### Automatic baseline (per board and per build)
A ring oscillator's frequency depends on how it was routed, so "healthy" differs per board and per build. The oscillators are pinned to fixed slices (`four_region_floorplan.tcl`) so a rebuild changes the frequencies very little, but a baseline is still tied to the build ID.

When the dashboard starts it looks at the board on the USB port (identified by its USB serial number) and:
- uses the saved baseline `hardware/host/calibration.json` (one local file, git-ignored) if it was recorded for the same board and build;
- otherwise records a new one, **but only if the board is cool (below 46 C), idle (no stress switch up), all four oscillators run and the frequencies are steady** for about 10 seconds;
- if those conditions fail it records nothing and tells you why (a hot or stressed board is never mistaken for the healthy reference). Fix the condition and press **Recalibrate now** in the sidebar.

All thresholds are in `health_rules.py`.
### Step 2: Connect to Dashboard
1. Start the Streamlit application:
   ```powershell
   streamlit run dashboard/app.py
   ```
2. In the sidebar, select **Physical UART Stream (Artix-7)**.
3. Select your COM port from the dropdown and click **🔌 Connect**.
4. The dashboard will automatically detect the telemetry stream, validate the physical bounds, compute $\tau = 100/f$, engineer 16 features, evaluate health with Random Forest ML, and run the diagnostic reasoning agent in real time.
