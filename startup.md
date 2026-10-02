# AI-Assisted FPGA Health Monitoring & Predictive Health Management (PHM)
## Complete Cross-Platform Startup Guide (macOS & Windows)

[![Streamlit Dashboard](https://img.shields.io/badge/Dashboard-Streamlit-FF4B4B.svg)](https://streamlit.io/)
[![Machine Learning](https://img.shields.io/badge/ML-Scikit--Learn-F7931E.svg)](https://scikit-learn.org/)
[![AI Agent](https://img.shields.io/badge/Agent-LangGraph-0052FF.svg)](https://langchain-ai.github.io/langgraph/)
[![Target Hardware](https://img.shields.io/badge/Hardware-Xilinx%20Artix--7-blue.svg)](https://digilent.com/reference/programmable-logic/basys-3/start)

A research-grade health monitoring and predictive maintenance system for FPGAs (specifically modeled for Xilinx Artix-7 on Digilent Basys 3). The system tracks on-chip physical degradation mechanisms (Bias Temperature Instability, Hot Carrier Injection, thermal wear-out, and supply voltage droop) by monitoring Ring Oscillator (RO) timing drift across four physically constrained silicon quadrants, die temperature, multi-rail voltages, and functional error rates.

---

## ⚡ Quick Command Cheat Sheet

| Action | 🪟 Windows (PowerShell) | 🍎 macOS (Terminal / zsh) |
| :--- | :--- | :--- |
| **Clone Repo** | `git clone https://github.com/midhun474/FPGA.git; cd FPGA` | `git clone https://github.com/midhun474/FPGA.git && cd FPGA` |
| **Create venv** | `python -m venv venv` | `python3 -m venv venv` |
| **Activate venv** | `.\venv\Scripts\Activate.ps1` | `source venv/bin/activate` |
| **Bypass Script Policy (if blocked)** | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` | *(Not applicable)* |
| **Install Packages** | `pip install -r requirements.txt` | `pip install -r requirements.txt` |
| **Run Test Suite** | `python -m unittest discover tests` | `python3 -m unittest discover tests` |
| **Launch Dashboard** | `streamlit run dashboard/app.py` | `streamlit run dashboard/app.py` |
| **Find FPGA Serial Port** | `Get-CimInstance Win32_SerialPort \| Select DeviceID, Description` | `ls /dev/cu.usbserial*` |

---

## 🪟 Windows Setup Guide

### 1. Prerequisites
- **Python**: 3.10 to 3.12 (download from [python.org](https://www.python.org/downloads/windows/) — ensure **"Add python.exe to PATH"** is checked during installation).
- **Git**: [git-scm.com](https://git-scm.com/).
- **Terminal**: Windows PowerShell or Windows Terminal.

### 2. Clone & Environment Setup
Open PowerShell and navigate to your preferred workspace folder:

```powershell
# 1. Clone the repository
git clone https://github.com/midhun474/FPGA.git
cd FPGA

# 2. Allow local PowerShell scripts (if script execution is disabled)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# 3. Create virtual environment
python -m venv venv

# 4. Activate virtual environment
.\venv\Scripts\Activate.ps1
# (You should see `(venv)` prepended to your shell prompt)

# 5. Upgrade pip and install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Verify System Health (Test Suite)
Run the automated test suite (59 unit and integration tests):

```powershell
python -m unittest discover tests
```
*Expected output: `Ran 59 tests ... OK`*

### 4. Launch the Streamlit Dashboard
```powershell
streamlit run dashboard/app.py
```
If your default browser does not open automatically, browse to:
👉 **`http://localhost:8501`**

### 5. Connecting Physical Basys 3 FPGA on Windows
1. Plug the Digilent Basys 3 board into your PC via a micro-USB cable. Ensure the power switch (`POWER`) is flipped to **ON** (blue LED illuminates).
2. Check the assigned COM port:
   ```powershell
   Get-CimInstance Win32_SerialPort | Select-Object DeviceID, Description, Manufacturer
   ```
   *(Alternatively, open **Device Manager** $\to$ **Ports (COM & LPT)**; look for `USB Serial Port (COM3)` or `FTDI...`).*
3. In the Streamlit dashboard sidebar:
   - Select **Telemetry Source** $\to$ **Physical UART Stream**.
   - Select your detected port (e.g., `COM3`, `COM4`).
   - Baud Rate defaults to `115200`.
   - Click **Connect UART**.

---

## 🍎 macOS Setup Guide

### 1. Prerequisites
- **Homebrew**: If not already installed, run `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`
- **Python 3.10+**:
  ```bash
  brew install python@3.11 git
  ```
- **Terminal**: Built-in Terminal.app or iTerm2 (running zsh).

### 2. Clone & Environment Setup
Open Terminal and run:

```bash
# 1. Clone the repository
git clone https://github.com/midhun474/FPGA.git
cd FPGA

# 2. Create virtual environment
python3 -m venv venv

# 3. Activate virtual environment
source venv/bin/activate
# (You should see `(venv)` prepended to your prompt)

# 4. Upgrade pip and install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Verify System Health (Test Suite)
Run the 59 automated test cases across limits, physics derivations, and ML models:

```bash
python -m unittest discover tests
```
*Expected output: `Ran 59 tests ... OK`*

### 4. Launch the Streamlit Dashboard
```bash
streamlit run dashboard/app.py
```
Open your browser to:
👉 **`http://localhost:8501`**

### 5. Connecting Physical Basys 3 FPGA on macOS
1. Connect the Digilent Basys 3 board via USB.
2. Find the serial device node in `/dev/`:
   ```bash
   ls /dev/cu.usbserial*
   ```
   *Typically appears as `/dev/cu.usbserial-210183XXXXXX` or `/dev/tty.usbserial-*`.*
   > [!TIP]
   > On macOS, always prefer the `/dev/cu.*` (calling unit) device over `/dev/tty.*` because `/dev/cu.*` does not wait for a DCD (Data Carrier Detect) signal before opening.
3. In the Streamlit dashboard sidebar:
   - Select **Telemetry Source** $\to$ **Physical UART Stream**.
   - Choose the `/dev/cu.usbserial-...` port from the dropdown.
   - Set Baud rate to `115200`.
   - Click **Connect UART**.

> [!NOTE]
> macOS Permissions: If prompted by macOS (System Settings $\to$ Privacy & Security) about allowing an external USB device or FTDI driver, click **Allow**.

---

## 🎛️ Telemetry Modes in the Dashboard

Select from four modes in the left sidebar:

| Mode | Description | How to Use |
| :--- | :--- | :--- |
| **Physical UART Stream** | Reads real-time telemetry from physical Basys 3 FPGA over USB serial at 115200 baud. | Select COM/cu port, click **Connect UART**. |
| **Live Simulation** | Physics-based dynamic simulator with real-time drift, Gaussian noise, and temperature excursions. | Select **Live Simulation** and adjust simulation rate. |
| **Mock Dataset (CSV)** | Replays pre-recorded degradation telemetry (10,000 samples) with interactive slider. | Select **Mock Dataset (CSV)**, drag sample slider to inspect wear-out. |
| **Estimated Health Assessment** | Allows operators to test custom combinations of 1 to 6 sensor readings. | Input any subset of temperature, voltages, or frequency. Assumes baselines for missing values. |

---

## 🏛️ Four-Region Silicon Architecture ($R1$ - $R4$)

The physical Basys 3 board is partitioned into four independent physical clock & floorplan regions:

```text
                  Artix-7 XC7A35T (Basys 3)
         ┌────────────────────────┬────────────────────────┐
         │     Region 1 (R1)      │     Region 2 (R2)      │
         │   Northwest (X0Y1)     │   Northeast (X1Y1)     │
         │   pblock_R1 (SLICE)    │   pblock_R2 (SLICE)    │
         │   Nominal: 436.2 MHz   │   Nominal: 436.4 MHz   │
         ├────────────────────────┼────────────────────────┤
         │     Region 3 (R3)      │     Region 4 (R4)      │
         │   Southwest (X0Y0)     │   Southeast (X1Y0)     │
         │   pblock_R3 (SLICE)    │   pblock_R4 (SLICE)    │
         │   Nominal: 436.1 MHz   │   Nominal: 435.9 MHz   │
         └────────────────────────┴────────────────────────┘
```

- **Independent Health Probes**: Each region contains an isolated 5-stage Ring Oscillator with its own gated counter.
- **Single-Source Timing Evaluation**: Frequency ($f_{\text{MHz}}$) is the primary physical measurement. Inverter delay ($\tau = 100 / f$) is mathematically derived for observability, guaranteeing **zero double-counting** of timing violations.
- **No Masking by Averaging**: If any single quadrant experiences localized heating or NBTI timing degradation (e.g. $R3$ drops to $410\text{ MHz}$), it triggers a safety override for that specific quadrant without being masked by healthy quadrants.

---

## 🚨 Troubleshooting & FAQ

### 1. `ImportError: cannot import name 'RO_FREQ_NOMINAL_MHZ'`
- **Cause**: Python cached an older in-memory version of `config.py` from an already running background Streamlit instance.
- **Fix**:
  - On Windows:
    ```powershell
    Get-Process -Name "*streamlit*", "*python*" | Stop-Process -Force
    streamlit run dashboard/app.py
    ```
  - On macOS:
    ```bash
    pkill -f streamlit
    streamlit run dashboard/app.py
    ```

### 2. Windows: `File ... Activate.ps1 cannot be loaded because running scripts is disabled`
- **Fix**: Run in PowerShell:
  ```powershell
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
  .\venv\Scripts\Activate.ps1
  ```

### 3. Port in Use: `Network access error: Address already in use (port 8501)`
- **Fix**: Run Streamlit on an alternative port:
  ```bash
  streamlit run dashboard/app.py --server.port 8502
  ```

### 4. Serial Port "Access Denied" or Busy
- **Cause**: Another tool (PuTTY, Tera Term, Vivado Hardware Manager, screen, or another terminal) has the serial COM port locked.
- **Fix**: Close all serial terminal applications and Vivado Hardware Manager serial monitors before connecting in the dashboard.

### 5. Vivado Synthesis & Bitstream Generation (Optional Hardware Step)
To rebuild the physical bitstream with the four-region floorplan in Vivado (Windows or Linux host):
```powershell
cd hardware\vivado
vivado -mode batch -source build_bitstream.tcl
```
To program the board:
```powershell
vivado -mode batch -source program_fpga.tcl
```

---

## 📁 Repository Quick Reference

- [`dashboard/app.py`](dashboard/app.py): Main Streamlit dashboard application.
- [`config.py`](config.py): Master hardware constants, nominal baselines & single-source timing boundaries.
- [`dashboard/config.py`](dashboard/config.py): Sensor envelopes, regional floorplan configs & deterministic safety logic.
- [`dashboard/components.py`](dashboard/components.py): Diagnostic cards & structured safety override callout panel.
- [`ml/feature_engineering.py`](ml/feature_engineering.py): 16-feature rolling and differential telemetry extraction.
- [`ml/models/fpga_health_model.pkl`](ml/models/fpga_health_model.pkl): Trained Random Forest classifier (200 estimators).
- [`tests/test_engineering_limits.py`](tests/test_engineering_limits.py): Comprehensive unit and integration test suite.
