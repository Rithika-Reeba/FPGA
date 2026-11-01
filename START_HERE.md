# START HERE: running the FPGA health monitor on this laptop

Everything below works without any help. The project folder is
`C:\Users\user\OneDrive\Desktop\FPGA-Project-files\FPGA`.

## 1. Start the dashboard (the 30-second version)

1. Plug the Basys 3 board into a USB port and switch it on (power switch at the top-left of the board).
   Leave **every switch down**. The board is optional: without it the dashboard still starts.
2. Double-click **`start_dashboard.bat`** in the project folder.
3. Wait about 20 seconds, then open **http://localhost:8511** in a browser if it did not open itself.
   The first load is slow because the dashboard reads the board first.
4. To stop it, press `Ctrl+C` in the black window (or close the window).

Starting it from a terminal instead:

```
cd C:\Users\user\OneDrive\Desktop\FPGA-Project-files\FPGA
venv\Scripts\python.exe run_dashboard.py
```

`run_dashboard.py` (which `start_dashboard.bat` also uses) keeps **one** dashboard running: if another copy is already
running it is closed first (so it releases the boards' serial ports) and the new one takes over. It only ever closes this
project's dashboard; if some other program uses port 8511 it says so and stops without touching it
(use another port with `venv\Scripts\python.exe run_dashboard.py 8512`).

**Only one dashboard window works at a time, like WhatsApp Web.** If you open the dashboard in a second tab or window, the newest one works and the older one pauses with "The dashboard is open in another window" and a **Use here** button, which takes it back (and pauses the other one). This stops two tabs from fighting over the boards.

A serial port (`COMx`) can be used by one program at a time. If a script of yours is using the board, close it first.

## 2. Pick the data source

In the sidebar, "Select Telemetry Source":

| Source | What it is | Use it for |
|---|---|---|
| **Physical UART Stream (Artix-7)** | Real readings from the board | The real demo |
| Mock Dataset (CSV Replay) | A recorded ageing scenario, scrubbable | Showing the whole Healthy to Degraded story without hardware |
| Dynamic Simulation Stream | A simulated chip with an "ageing" slider | Playing with the limits |
| Estimated Health Assessment | You type values, it judges them | What-if checks |

Mock, simulation and estimated data are always labelled as such. Only the UART source is a real measurement.

## 3. Using a real board

### 3.1 Is the design on the board?

The board forgets its design when power is removed. After plugging it in, the **PROG DONE** LED (near the USB port)
must be lit. If it is off, or the dashboard says "waiting for FPGA / no telemetry packets":

- **Sidebar, "FPGA Hardware Programmer", "Burn Precompiled Bitstream"**: programs only the board being monitored. Or:
- From a terminal (replace the id with the board's, shown in the dashboard sidebar; find it with the last row of section 6):

```
vivado -mode batch -source hardware/vivado/program_fpga.tcl -tclargs 210183B3150C
```

Programming is volatile and reversible: it only lasts until the board loses power.
With two boards connected always give the board id, so the wrong one is never programmed.

The dashboard **never writes to a board's flash**. The program stored on each board stays as it is, and a power-off or
the PROG button brings that stored program back.

**Choosing which design is loaded:** a tiny, faint switch at the very bottom-left corner of the sidebar picks the design.
Flipping it loads the matching design into the monitored board (about 30 seconds; the skeleton screen shows): **on** =
the R2 demo-fault design, **off** = the normal design. The Burn button loads the design for the current switch position.
Both are temporary. The switch acts on the board currently shown in "Board to monitor".

### 3.2 The baseline (automatic)

Healthy is judged against the board's own frequencies. The dashboard records them by itself:

- when a board (or a new build) is seen for the first time, **if the board is cool (under 46 C), all stress switches and SW15 are down, and all four oscillators are steady**. It takes about 10 seconds;
- if it cannot (board warm, a switch up), the sidebar says why. Fix that, then press **"Recalibrate now"**;
- it is stored in `hardware/host/calibration.json` (one file, not committed to git). A different board or a new build replaces it automatically.

Nothing is ever recorded from a hot or stressed board, so it can never become the "healthy" reference.

### 3.3 Switches and buttons on the board

| Control | Function |
|---|---|
| SW0 (rightmost) | **Down = telemetry.** Up = HELLO link test (no readings) |
| SW1 | Up = stop all ring oscillators (simulates dead sensors; chip goes at least Warning) |
| SW12, SW13, SW14 | Stress heaters in R1, R2, R3: **really heat the chip**. Self-limiting on temperature. Expect Warning, then Degraded, as it heats |
| **SW15** | **Test fault on R2.** R2 shows **Degraded**, R1, R3, R4 stay Healthy, overall stays Healthy. It is an injected fault, not a measurement, and the dashboard says so in a one-line note |
| btnC (centre) | Reset |
| btnU (top) | Capture the board's own LED baseline (only accepted when cool and every stress switch is down) |

LEDs: LED2 = Healthy, LED3 = Warning, LED4 = Degraded (all three off = not calibrated). LED0, LED1 and LED12 to LED15 blink slowly
while their switch is down and are solid while it is up. The four-digit display cycles R1 to R4 frequency, then die temperature.

### 3.4 The usual demo

1. All switches down: every region and the overall state show **Healthy**.
2. Raise **SW15**: R2 shows **Degraded**; the others and the overall state stay Healthy (the overall state only changes when
   at least two regions are bad). A banner says it is a test fault.
3. Lower SW15. Optional real stress: raise **SW12 + SW13 + SW14** for a minute. Several regions slow down together
   and the overall state moves to Warning or Degraded. **Lower them afterwards** so the chip cools; the heaters switch
   themselves off above about 70 C anyway.

### 3.5 Two boards

Plug both in. The sidebar gets a **"Board to monitor"** picker; the dashboard watches one at a time. Each time you
switch boards it records that board's baseline (about 10 seconds, board cool, switches down). Use the same
program on both; the difference between a "normal" board and the "R2 fault" board is only whether SW15 is up.

## 4. Rebuilding the FPGA design (only if the hardware code changed)

```
vivado -mode batch -source hardware/vivado/build_bitstream.tcl
```

It takes several minutes and writes `C:\vivado_build\build\fpga_health_top.bit`. It **refuses to write the file** if timing
is not met or if a region's logic ends up outside its area, so a missing `.bit` after a build means a failed build; read the
last lines of the output. Vivado lives in `C:\AMDDesignTools\2026.1\Vivado\bin`; set the `VIVADO_PATH` environment variable
if it moves.

## 4b. See the four physical partitions (Pblocks) in Vivado

- **The project:** double-click `open_vivado.bat` (the healthy design). It opens the project by its real location,
  `C:\vivado_projects\fpga_health_project\fpga_health_project.xpr`. `vivado_project` in this folder is a link to that
  folder for browsing; **do not open the `.xpr` through the link**, Vivado then looks for the source files in the wrong
  place and reports 17 critical warnings.
  In Flow Navigator choose **Open Implemented Design**, then look at the **Device** window: the four rectangles
  `pblock_R1` to `pblock_R4` are the regions (R1 top-left, R2 top-right, R3 bottom-left, R4 bottom-right).
  If the project is out of date, regenerate it from the current design (about 10 minutes):
  `vivado -mode batch -source hardware/vivado/refresh_project.tcl`
- **Quicker:** double-click `show_floorplan.bat`. It opens the last routed design with each region's logic in its own colour.
- **Without a window:** `vivado -mode batch -source hardware/vivado/show_floorplan.tcl` prints each Pblock's area.

## 4c. The "fault board" demo build

(The dashboard's faint switch loads this design for you, temporarily; the commands here are the manual way.)

A bitstream with the R2 test fault permanently on is built with `set FPGA_FAULT_ALWAYS=1` before the build command in
section 4 (output goes to `C:\vivado_build\build_fault`, the normal `.bit` is untouched). Program it only into the board that
should show the fault. The dashboard labels it as an injected test fault, and the overall state stays Healthy.

## 5. Check that everything is healthy

```
venv\Scripts\python.exe -m unittest discover tests
```

Expected: `OK` (146 tests; one is skipped when no board is connected).

## 6. If something goes wrong

| Symptom | Cause and fix |
|---|---|
| Browser says `ERR_CONNECTION_REFUSED` | The dashboard is not running. Double-click `start_dashboard.bat` |
| Blank or "Streamlit" page for ~20 s | Normal on first load (it reads the board). Wait, do not reload repeatedly |
| Window says the port is already in use | A copy is already running. Close it, or open its address |
| "Access is denied" on `COMx` | Another program holds the board's serial port. Close the other dashboard or script |
| "Waiting for FPGA", no packets | Board has no design (programmed state lost at power-off) or SW0 is up. Check PROG DONE and SW0, then burn the bitstream (3.1) |
| "No valid baseline yet" | Board warm, a stress switch or SW15 up, or oscillators not steady. Lower the switches, let it cool, press "Recalibrate now" |
| Everything shows Warning with no switch up | Chip is warm (e.g. after stress) or the baseline came from a different state. Let it cool, then recalibrate |
| Board vanishes and reappears | Bad USB cable or connector. Use another cable, directly in the PC (no hub) |
| Code changed but the page did not | Stop (`Ctrl+C`) and start the dashboard again; some modules are only read at start |
| Find the board's id and port | `venv\Scripts\python.exe -c "import communication.board_calibration as b; print(b.list_board_ports())"` (run in the project folder) |

## 7. First time on a new laptop

1. Install **Python 3.12 or newer** (tick "Add python.exe to PATH"), and Vivado (for programming and rebuilding only).
2. In the project folder: `python -m venv venv`, then `venv\Scripts\python.exe -m pip install -r requirements.txt`.
3. Install the Digilent / FTDI USB driver if the board does not appear as a `COM` port in Device Manager.
4. Then use section 1.

Development notes: work is on the git branch `board-health-rework`; push only to the `fork` remote, never to `origin`.
