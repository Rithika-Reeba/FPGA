"""
AI-Assisted FPGA Health Monitoring and Predictive Health Management System
========================================================================
Main Streamlit Research & Demonstration Application
"""

import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

import streamlit as st
import pandas as pd
import numpy as np
import joblib

# -----------------------------------------------------------------------------
# Workspace Path Configuration
# -----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# -----------------------------------------------------------------------------
# Automatic board baseline. Must run BEFORE the config modules are imported (they read the
# calibration once, at import). The result is cached for the life of the server.
# -----------------------------------------------------------------------------
import os
from communication.board_calibration import detect_board_port, ensure_calibration, list_board_ports


@st.cache_resource(show_spinner=False)
def auto_baseline(port) -> dict:
    if not port:
        return {"state": "no-board", "port": None, "board_id": None, "build_id": None,
                "reason": "no Basys 3 detected on USB"}
    return ensure_calibration(port)


# One shared choice of board for the baseline AND the serial receiver (they must never differ):
# the board picked in the sidebar, else FPGA_PORT, else the first board found.
BOARD_PORT = st.session_state.get("board_port") or os.environ.get("FPGA_PORT") or detect_board_port()
BOARD_CAL = auto_baseline(BOARD_PORT)

from config import RO_STAGES, RO_FREQ_NOMINAL_MHZ
import health_rules
from dashboard.config import (
    DEVICE_NAME,
    ARCHITECTURE,
    HEALTH_COLORS,
    STATUS_BG_COLORS,
    SENSOR_CONFIG,
    evaluate_engineering_limits,
    determine_final_health,
    LimitSeverity,
    calibrate_history_dataframe
)
from dashboard.styles import get_custom_css
from dashboard.data_source import (
    MockCSVDataSource,
    LiveSimulationDataSource,
    LiveUARTDataSource,
    EstimatedDataSource,
    validate_and_clean_data
)
from communication.uart_receiver import FPGAUARTReceiver
from dashboard.components import (
    render_header,
    render_primary_health_kpis,
    render_measurements_grid,
    render_ring_oscillator_section,
    render_baseline_comparison,
    render_sensor_status_table,
    render_agent_recommendations_section,
    render_life_extension_section,
    render_estimated_input_breakdown,
    render_estimated_stress_index,
    render_hardware_connection_panel,
    render_hardware_vs_estimated_comparison,
    render_engineering_override_alert
)
from dashboard.charts import (
    create_temperature_chart,
    create_ro_frequency_chart,
    create_ro_delay_chart,
    create_error_rate_chart,
    create_voltage_chart,
    create_health_prediction_trend_chart,
    create_normalized_indicators_chart,
    create_feature_importance_chart
)
from dashboard.health_map import (
    calculate_aggregate_risk_score,
    generate_four_region_data,
    render_four_region_map_html,
    generate_risk_cells,
    render_health_risk_map_html
)
from agent.langgraph_agent import evaluate_fpga_health


# =============================================================================
# Streamlit Page Setup
# =============================================================================
st.set_page_config(
    page_title="AI-Assisted FPGA Health Monitoring",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Inject Custom Embedded Dark Theme CSS via st.html
st.html(get_custom_css())


# =============================================================================
# Model & Pipeline Loader (Cached)
# =============================================================================
@st.cache_resource(show_spinner=False)
def load_ml_pipeline():
    model_path = PROJECT_ROOT / "ml" / "models" / "fpga_health_model.pkl"
    if not model_path.exists():
        return None, None, f"Model file not found at: {model_path}"
    try:
        saved = joblib.load(model_path)
        return saved.get("model"), saved.get("features"), None
    except Exception as e:
        return None, None, f"Failed to deserialize model: {str(e)}"


@st.cache_resource(show_spinner=False)
def get_shared_uart_source(port: str) -> LiveUARTDataSource:
    """Provides a singleton LiveUARTDataSource shared across tabs and reruns to prevent COM port lockouts."""
    return LiveUARTDataSource(port=port)


_PROJECT_MODULES = (
    "health_rules", "config", "dashboard.config", "dashboard.charts", "dashboard.components",
    "dashboard.data_source", "dashboard.health_map", "agent.langgraph_agent",
    "communication.uart_receiver", "communication.board_calibration", "hardware.host.health_reader",
)


def recalibrate_and_reload(port=None, force=True) -> None:
    """Record a baseline now (force: a fresh one; the board must be cool and idle), then reload
    every project module so the new numbers take effect everywhere without restarting the
    server. Also used to switch to another board (port given, force off)."""
    try:
        st.session_state.uart_source.disconnect()          # free the serial port first
    except Exception:
        pass
    port = port or BOARD_PORT
    if port:
        st.session_state["board_port"] = port
    st.session_state["_recal_msg"] = (
        ensure_calibration(port, force=force) if port
        else {"state": "no-board", "reason": "no Basys 3 detected on USB"}
    )
    auto_baseline.clear()
    get_shared_uart_source.clear()
    for name in _PROJECT_MODULES:
        sys.modules.pop(name, None)
    for key in ("uart_source", "sim_source", "mock_source", "estimated_source"):
        st.session_state.pop(key, None)
    st.rerun()


# =============================================================================
# Session State Initialization
# =============================================================================
detected_fpga_port = BOARD_PORT      # the one shared choice; no "any USB serial port" fallback

if "data_mode" not in st.session_state:
    if detected_fpga_port:
        st.session_state.data_mode = "Physical UART Stream (Artix-7)"
    else:
        st.session_state.data_mode = "Mock Dataset (CSV Replay)"

if "sample_index" not in st.session_state:
    st.session_state.sample_index = 3500  # Default to an interesting transitional state
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = bool(detected_fpga_port)
if "refresh_rate" not in st.session_state:
    st.session_state.refresh_rate = 1 if detected_fpga_port else 2
if "auto_connect" not in st.session_state:
    st.session_state.auto_connect = True
if "sim_source" not in st.session_state:
    st.session_state.sim_source = LiveSimulationDataSource()
if "mock_source" not in st.session_state:
    try:
        st.session_state.mock_source = MockCSVDataSource()
    except Exception:
        st.session_state.mock_source = None
if "uart_source" not in st.session_state:
    initial_port = detected_fpga_port or "COM10"
    st.session_state.uart_source = get_shared_uart_source(initial_port)

# If in Physical UART mode and port is closed, attempt auto-connect (unless user explicitly disconnected)
if st.session_state.data_mode == "Physical UART Stream (Artix-7)":
    if not st.session_state.get("user_disconnected", False):
        if not st.session_state.uart_source.receiver.is_port_open and st.session_state.get("auto_connect", True):
            target_port = st.session_state.uart_source.receiver.port or detected_fpga_port
            if target_port and target_port not in ("NONE", "No Ports Detected"):
                st.session_state.uart_source.connect()

if "estimated_source" not in st.session_state:
    st.session_state.estimated_source = EstimatedDataSource()
if "est_temp" not in st.session_state:
    st.session_state.est_temp = ""
if "est_vccint" not in st.session_state:
    st.session_state.est_vccint = ""
if "est_vccaux" not in st.session_state:
    st.session_state.est_vccaux = ""
if "est_vccbram" not in st.session_state:
    st.session_state.est_vccbram = ""
if "est_ro_freq" not in st.session_state:
    st.session_state.est_ro_freq = ""
if "est_err_rate" not in st.session_state:
    st.session_state.est_err_rate = ""


# =============================================================================
# Sidebar Control Panel
# =============================================================================
with st.sidebar:
    st.markdown("### 🎛️ Telemetry Source & Controls")
    
    data_mode = st.selectbox(
        "Select Telemetry Source",
        [
            "Mock Dataset (CSV Replay)",
            "Dynamic Simulation Stream",
            "Physical UART Stream (Artix-7)",
            "Estimated Health Assessment"
        ],
        index=0 if st.session_state.data_mode == "Mock Dataset (CSV Replay)" else (
            1 if "Simulation" in st.session_state.data_mode else (
                2 if "UART" in st.session_state.data_mode else 3
            )
        )
    )
    st.session_state.data_mode = data_mode

    st.markdown("---")

    # Mode-specific controls
    if "Mock Dataset" in data_mode:
        if st.session_state.mock_source is not None:
            total_samples = len(st.session_state.mock_source.raw_df)
            st.session_state.sample_index = st.slider(
                "Historical Sample Timeline Scrubber",
                min_value=0,
                max_value=total_samples - 1,
                value=min(st.session_state.sample_index, total_samples - 1),
                step=50,
                help="Slide to simulate FPGA transition across healthy, warning, and degraded aging lifecycle."
            )

            col_p1, col_p2, col_p3 = st.columns(3)
            with col_p1:
                if st.button("🟢 Healthy", width="stretch"):
                    st.session_state.sample_index = 1000
                    st.rerun()
            with col_p2:
                if st.button("🟡 Warning", width="stretch"):
                    st.session_state.sample_index = 5000
                    st.rerun()
            with col_p3:
                if st.button("🟠 Degraded", width="stretch"):
                    st.session_state.sample_index = 9200
                    st.rerun()

    elif "Simulation" in data_mode:
        sim_deg = st.slider("Simulated Aging Degradation Factor", 0.0, 1.0, 0.45, 0.05)
        if st.button("⚡ Inject Step Measurement", width="stretch"):
            st.session_state.sim_source.step(degradation=sim_deg)
            st.rerun()
        if st.button("🔄 Reset Simulation Buffer", width="stretch"):
            st.session_state.sim_source.reset()
            st.rerun()

    elif "Physical UART" in data_mode:
        st.markdown("#### 🔌 Basys 3 Hardware Interface")
        rcv = st.session_state.uart_source.receiver

        _boards = list_board_ports()
        if len(_boards) > 1:
            _labels = [f"{dev} - board {bid}" for dev, bid in _boards]
            _cur = next((i for i, (dev, _) in enumerate(_boards) if dev == BOARD_PORT), 0)
            _pick = st.selectbox("Board to monitor", _labels, index=_cur, key="board_pick")
            _new_port = _boards[_labels.index(_pick)][0]
            if _new_port != BOARD_PORT:
                recalibrate_and_reload(port=_new_port, force=False)
        _icon = {"ok": "🟢", "created": "🟢", "waiting": "🟡", "error": "🔴"}.get(BOARD_CAL["state"], "⚪")
        st.caption(f"{_icon} **Baseline**: {BOARD_CAL['reason']}  \nRecorded automatically from the connected board. Build `{BOARD_CAL['build_id']}`")
        _recal = st.session_state.pop("_recal_msg", None)
        if _recal:
            (st.success if _recal["state"] in ("created", "ok") else st.warning)(f"Recalibration: {_recal['reason']}")
        if st.button("📏 Recalibrate now (board cool and idle)", width="stretch", key="recal_btn"):
            recalibrate_and_reload()

        # Real-time connection badge
        if rcv.is_streaming:
            st.success(f"🟢 **STREAMING LIVE**: `{rcv.port}` (115200 8N1)\n\n⚡ Rate: {rcv.get_packet_rate_hz()} Hz | Total: {rcv.packet_count:,}")
        elif rcv.is_port_open:
            st.warning(f"🟡 **PORT OPEN (`{rcv.port}`) — WAITING FOR FPGA**")
            if rcv.last_error_msg:
                st.caption(f"ℹ️ {rcv.last_error_msg}")
        else:
            st.error("🔴 **DISCONNECTED**")
            if rcv.last_error_msg:
                st.caption(f"⚠️ {rcv.last_error_msg}")

        # Port mapping and selection with descriptive labels
        port_map = FPGAUARTReceiver.get_port_display_map()
        display_labels = list(port_map.keys())

        # Determine index of current port
        cur_device = rcv.port
        default_idx = 0
        for i, lbl in enumerate(display_labels):
            if port_map[lbl] == cur_device:
                default_idx = i
                break
        else:
            if detected_fpga_port:
                for i, lbl in enumerate(display_labels):
                    if port_map[lbl] == detected_fpga_port:
                        default_idx = i
                        break

        col_port, col_ref = st.columns([4, 1])
        with col_port:
            selected_label = st.selectbox("UART COM Port", display_labels, index=default_idx)
            selected_device = port_map.get(selected_label, cur_device)
        with col_ref:
            st.write("") # spacing
            if st.button("🔄", help="Rescan serial ports"):
                st.rerun()

        # Switching port = switching board: the baseline must follow, so only Basys 3 style ports
        # (Digilent FT2232H) are accepted and the change always goes through the baseline step.
        if selected_device != BOARD_PORT and selected_device != "NONE":
            if selected_device in [dev for dev, _ in list_board_ports()]:
                recalibrate_and_reload(port=selected_device, force=False)
            else:
                st.warning(f"`{selected_device}` is not a Basys 3 USB-serial port, so it was not selected.")

        st.caption(f"**Target Device**: {DEVICE_NAME} (`{selected_device}`)")

        # Auto-connect toggle
        st.session_state.auto_connect = st.checkbox(
            "Auto-Connect when FPGA detected",
            value=st.session_state.get("auto_connect", True),
            help="Automatically attempts to connect to the detected Basys 3 USB port."
        )

        col_u1, col_u2 = st.columns(2)
        with col_u1:
            if not rcv.is_port_open:
                if st.button("🔌 Connect", width="stretch"):
                    st.session_state.user_disconnected = False
                    ok = st.session_state.uart_source.connect()
                    if not ok:
                        st.session_state.uart_connect_error = rcv.last_error_msg
                    else:
                        st.session_state.uart_connect_error = None
                    st.rerun()
            else:
                st.button("🔌 Connected", disabled=True, width="stretch")
        with col_u2:
            if rcv.is_port_open:
                if st.button("🛑 Disconnect", width="stretch"):
                    st.session_state.user_disconnected = True
                    st.session_state.uart_source.disconnect()
                    st.session_state.uart_connect_error = None
                    st.rerun()
            else:
                st.button("🛑 Disconnected", disabled=True, width="stretch")

        if st.session_state.get("uart_connect_error"):
            st.error(f"⚠️ {st.session_state.uart_connect_error}")

        # Comprehensive System-Wide Port Tracker & Diagnostic Sniffer
        with st.expander("🔍 All COM Ports Diagnostic Tracker", expanded=False):
            st.markdown("Track and probe **every** serial port on the system to locate the FPGA board:")
            
            probe_all = st.button("⚡ Probe All USB Ports for FPGA Telemetry", help="Actively tests each USB port to detect live FPGA JSON telemetry.")

            all_ports_meta = FPGAUARTReceiver.scan_all_ports_detailed(
                current_receiver=rcv,
                probe_telemetry=probe_all
            )

            if not all_ports_meta:
                st.warning("No COM ports found on this system. Check USB cable and drivers.")
            else:
                for p_meta in all_ports_meta:
                    p_name = p_meta["device"]
                    p_cat = p_meta["category"]
                    p_desc = p_meta["description"]
                    p_stat = p_meta["status_label"]
                    p_cur = p_meta["is_current"]
                    p_tel = p_meta["telemetry_detected"]
                    p_hwid = p_meta.get("hwid", "")

                    # Status indicator dot
                    if p_cur and rcv.is_streaming:
                        badge = "🟢 **STREAMING LIVE**"
                    elif p_tel:
                        badge = "🟢 **FPGA TELEMETRY DETECTED**"
                    elif p_cur:
                        badge = "🟡 **ACTIVE (CONNECTED)**"
                    elif "LOCKED" in p_meta.get("status", ""):
                        badge = "🔴 **PORT LOCKED / IN USE**"
                    elif p_meta.get("is_bluetooth"):
                        badge = "⚪ **BLUETOOTH LINK**"
                    else:
                        badge = "🔵 **AVAILABLE**"

                    st.markdown(f"**{p_name}** — `{p_cat}`")
                    st.caption(f"{badge} | {p_stat}\n\n*HWID: {p_hwid[:45]}...*")

                    col_pa, col_pb = st.columns(2)
                    with col_pa:
                        if not p_cur:
                            _is_board = p_name in [dev for dev, _ in list_board_ports()]
                            if st.button(f"🔌 Use {p_name}", key=f"track_btn_use_{p_name}", disabled=not _is_board,
                                         help=None if _is_board else "Not a Basys 3 USB-serial port"):
                                recalibrate_and_reload(port=p_name, force=False)
                        else:
                            st.info("👈 Currently selected")
                    with col_pb:
                        if not p_cur and not p_meta.get("is_bluetooth"):
                            if st.button(f"🔍 Test {p_name}", key=f"track_btn_test_{p_name}"):
                                p_res = FPGAUARTReceiver.probe_port(p_name, timeout=0.3)
                                st.write(p_res["message"])
                                if p_res.get("raw_sample"):
                                    st.code(p_res["raw_sample"], language="json")
                    st.markdown("---")

            st.caption("ℹ️ **Why COM port might not change when switching USB sockets:** Windows binds COM ports to FTDI chip EEPROM serial numbers. Moving the Basys 3 cable between physical ports often keeps it assigned to the same COM port.")

        with st.expander("⚡ FPGA Hardware Programmer", expanded=False):
            st.markdown("Burn the precompiled health monitor bitstream (Ring Oscillator, XADC, PRBS-7, UART) into the board:")
            st.caption(f"Programs ONLY the board being monitored (found automatically from its USB port). "
                       "The design is lost when the board loses power.")
            if st.button("🔥 Burn Precompiled Bitstream", width="stretch", disabled=not BOARD_CAL.get("board_id")):
                with st.spinner("Programming Basys 3 FPGA over JTAG..."):
                    try:
                        st.session_state.uart_source.disconnect()          # JTAG and UART share the USB chip
                        from hardware.flash_manager import program_health_bitstream
                        ok, msg = program_health_bitstream(board_id=BOARD_CAL.get("board_id"))
                    except Exception as e:
                        ok, msg = False, str(e)
                if ok:
                    st.success(msg)
                    recalibrate_and_reload(port=BOARD_PORT, force=False)   # new build => check/record its baseline
                else:
                    st.error(f"Programming failed: {msg}")

        with st.expander("🎮 Board Physical Controls", expanded=False):
            st.markdown("""
            **Interactive Switches (`sw[3:0]`):**
            - `sw[1]` (Pin V16): **Ring Oscillator Run / Halt**
              *(0 = Run @ ~436 MHz, 1 = Halt to test 0 MHz delay drift)*
            - `sw[2]` (Pin W16): **Synthetic Fault Injection**
              *(0 = Nominal PRBS-7, 1 = Injects bit errors to trigger Warning/Degraded)*
            - `sw[0]` (Pin V17): **Telemetry Format**
              *(0 = JSON Telemetry stream, 1 = Handshake burst)*

            **Health LEDs (`led[15:13]`):**
            - `led[13]` (N3): **Healthy** (Green)
            - `led[14]` (P1): **Warning** (Yellow)
            - `led[15]` (L1): **Degraded** (Red)
            """)

    elif "Estimated" in data_mode:
        st.markdown("#### 🎯 Quick Presets")
        col_ep1, col_ep2, col_ep3 = st.columns(3)
        with col_ep1:
            if st.button("🟢 Healthy", width="stretch", key="preset_healthy"):
                st.session_state.est_temp = "35.0"
                st.session_state.est_vccint = "1.000"
                st.session_state.est_vccaux = "1.800"
                st.session_state.est_vccbram = "1.000"
                st.session_state.est_ro_freq = f"{RO_FREQ_NOMINAL_MHZ:.1f}"
                st.session_state.est_err_rate = "0.00001"
                st.rerun()
        with col_ep2:
            if st.button("🟡 Warning", width="stretch", key="preset_warning"):
                st.session_state.est_temp = "47.0"
                st.session_state.est_vccint = "0.995"
                st.session_state.est_vccaux = "1.795"
                st.session_state.est_vccbram = "0.996"
                st.session_state.est_ro_freq = "424.0"
                st.session_state.est_err_rate = "0.0012"
                st.rerun()
        with col_ep3:
            if st.button("🟠 Degraded", width="stretch", key="preset_degraded"):
                st.session_state.est_temp = "53.5"
                st.session_state.est_vccint = "0.988"
                st.session_state.est_vccaux = "1.788"
                st.session_state.est_vccbram = "0.990"
                st.session_state.est_ro_freq = "410.0"
                st.session_state.est_err_rate = "0.0030"
                st.rerun()

        if st.button("🔄 Clear Form (Use Baselines)", width="stretch", key="preset_clear"):
            st.session_state.est_temp = ""
            st.session_state.est_vccint = ""
            st.session_state.est_vccaux = ""
            st.session_state.est_vccbram = ""
            st.session_state.est_ro_freq = ""
            st.session_state.est_err_rate = ""
            st.session_state.estimated_source.reset()
            st.rerun()

        st.markdown("#### 📝 Manual Telemetry Inputs")
        st.caption("Enter one or more available values. Blank channels default to nominal physical baselines.")

        in_temp = st.text_input("Temperature (°C)", value=st.session_state.est_temp, placeholder="e.g. 45.0 (nom: 35.0, 0-125°C)", key="input_temp")
        in_ro_freq = st.text_input("RO Frequency (MHz)", value=st.session_state.est_ro_freq, placeholder=f"e.g. {RO_FREQ_NOMINAL_MHZ:.1f} (nom: {RO_FREQ_NOMINAL_MHZ:.1f}, 50-800MHz)", key="input_ro_freq")
        in_vccint = st.text_input("VCCINT Core Voltage (V)", value=st.session_state.est_vccint, placeholder="e.g. 1.000 (nom: 1.000, 0.5-1.5V)", key="input_vccint")
        in_vccaux = st.text_input("VCCAUX Aux Voltage (V)", value=st.session_state.est_vccaux, placeholder="e.g. 1.800 (nom: 1.800, 1.0-2.5V)", key="input_vccaux")
        in_vccbram = st.text_input("VCCBRAM BRAM Voltage (V)", value=st.session_state.est_vccbram, placeholder="e.g. 1.000 (nom: 1.000, 0.5-1.5V)", key="input_vccbram")
        in_err_rate = st.text_input("Functional Error Rate", value=st.session_state.est_err_rate, placeholder="e.g. 0.0001 (nom: 0.00001, 0.0-1.0)", key="input_err_rate")

        st.session_state.est_temp = in_temp
        st.session_state.est_ro_freq = in_ro_freq
        st.session_state.est_vccint = in_vccint
        st.session_state.est_vccaux = in_vccaux
        st.session_state.est_vccbram = in_vccbram
        st.session_state.est_err_rate = in_err_rate

        raw_inputs = {
            "Temperature": in_temp,
            "RO_Frequency": in_ro_freq,
            "VCCINT": in_vccint,
            "VCCAUX": in_vccaux,
            "VCCBRAM": in_vccbram,
            "Error_Rate": in_err_rate
        }

        est_valid, est_errors, est_warnings = st.session_state.estimated_source.set_inputs(raw_inputs)
        if not est_valid:
            for err in est_errors:
                st.error(f"❌ {err}")
            st.stop()
        elif est_warnings:
            for warn in est_warnings:
                st.warning(f"⚠️ {warn}")

    if "Estimated" not in data_mode:
        st.markdown("---")
        st.markdown("### ⏱️ Live Auto-Refresh")
        st.session_state.auto_refresh = st.toggle("Enable Live Auto-Poll", value=st.session_state.auto_refresh)
        if st.session_state.auto_refresh:
            st.session_state.refresh_rate = st.select_slider(
                "Poll Interval (seconds)",
                options=[1, 2, 5, 10],
                value=st.session_state.refresh_rate
            )

    st.markdown("---")
    st.markdown("### 📋 Hardware Target")
    st.caption(f"**Device**: {DEVICE_NAME}\n\n**Process Node**: {ARCHITECTURE}\n\n**RO Inverter Stages (N)**: {RO_STAGES}\n\n**Sensor Package**: XADC Dual 12-bit 1MSPS + Ring Oscillator Aging Sensor")


# =============================================================================
# Data Acquisition & Feature Transformation
# =============================================================================
model, model_features, model_error = load_ml_pipeline()

if model_error:
    st.error(f"⚠️ {model_error}")
    st.stop()

# Select appropriate data source
try:
    if "Mock Dataset" in data_mode:
        if st.session_state.mock_source is None:
            st.session_state.mock_source = MockCSVDataSource()
        history_df, latest, meta = st.session_state.mock_source.get_data(
            window_size=150,
            sample_idx=st.session_state.sample_index
        )
        source_badge = "MOCK (CSV REPLAY)"

    elif "Simulation" in data_mode:
        if st.session_state.auto_refresh:
            st.session_state.sim_source.step(degradation=0.55)
        history_df, latest, meta = st.session_state.sim_source.get_data(window_size=150)
        source_badge = "LIVE SIMULATION"

    elif "Estimated" in data_mode:
        history_df, latest, meta = st.session_state.estimated_source.get_data(window_size=150)
        source_badge = "ESTIMATED / USER PROVIDED"

    else:
        st.session_state.uart_source.poll_hardware()
        history_df, latest, meta = st.session_state.uart_source.get_data(window_size=150)
        source_badge = f"LIVE UART ({st.session_state.uart_source.receiver.port})"

        # The board was reprogrammed while the dashboard was running: its baseline belongs to the
        # previous build. Re-check / record the baseline for the new build (once per build id).
        _build = meta.get("build_id")
        if _build and BOARD_CAL.get("build_id") and _build != BOARD_CAL["build_id"] \
                and st.session_state.get("_rebaselined_for") != _build:
            st.session_state["_rebaselined_for"] = _build
            recalibrate_and_reload(port=BOARD_PORT, force=False)

        # SW15 on the board injects a fault into R2's reading. Say so clearly: it is a demo, not wear.
        if meta.get("test_fault") and meta.get("has_real_data") and not meta.get("is_stale"):
            st.warning(f"**TEST FAULT INJECTED on {meta['test_fault']} (by the board: switch SW15 or the demo build).** "
                       f"{meta['test_fault']}'s frequency is reduced by the board on purpose to demonstrate a single-region "
                       "warning; it is NOT a measured degradation. The other regions show real readings.")

        # Show health only while telemetry is really arriving: no packets yet, a HELLO link test,
        # or telemetry that went quiet must never leave the last reading on screen as "live".
        _stale = bool(meta.get("is_stale", False))
        if not meta.get("has_real_data", False) or _stale:
            rcv = st.session_state.uart_source.receiver
            st.markdown("### 🔌 Basys 3 Hardware Interface Status")
            if _stale:
                st.error(
                    f"🔴 **NO DATA**: no telemetry for {meta.get('data_age_s', 0):.0f} s. "
                    "The values below are NOT shown because they would be out of date."
                )

            if not rcv.is_port_open:
                st.error(f"🔴 **Port Disconnected**: {rcv.last_error_msg or 'Serial port is currently closed.'}")
                st.info("Plug in the board's USB cable, then click **Connect to Board**.")
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("⚡ Connect to Board", type="primary", use_container_width=True):
                        if BOARD_PORT:
                            rcv.connect(BOARD_PORT)
                        st.rerun()
                with col_btn2:
                    if st.button("📊 Switch to Simulation Mode", use_container_width=True):
                        st.session_state.data_mode = "Dynamic Simulation Stream"
                        st.rerun()
            else:
                st.warning(
                    f"🟡 **Connected to `{rcv.port}`, but NO telemetry packets are arriving.**\n\n"
                    f"- **Port:** `{rcv.port}` (115200 8N1)\n"
                    f"- **Status:** {rcv.last_error_msg or 'Listening for telemetry packets...'}\n\n"
                    "**Troubleshooting Checklist:**\n"
                    "1. **Wrong board?** Pick the board in **Board to monitor** (sidebar).\n"
                    "2. **Unprogrammed FPGA?** The design is lost when the board loses power. Click **Burn Precompiled Bitstream** below.\n"
                    "3. **Physical Switch `sw[0]`:** it must be DOWN for telemetry (UP is the HELLO link test, which carries no readings)."
                )
                col_f1, col_f2, col_f3 = st.columns(3)
                with col_f1:
                    if st.button("🔥 Burn Precompiled Bitstream Now", type="primary", use_container_width=True,
                                 disabled=not BOARD_CAL.get("board_id")):
                        with st.spinner("Burning fpga_health_top.bit into the monitored board over JTAG..."):
                            try:
                                rcv.disconnect()                               # JTAG and UART share the USB chip
                                from hardware.flash_manager import program_health_bitstream
                                ok, msg = program_health_bitstream(board_id=BOARD_CAL.get("board_id"))
                            except Exception as e:
                                ok, msg = False, str(e)
                        if ok:
                            st.success(msg)
                            recalibrate_and_reload(port=BOARD_PORT, force=False)
                        else:
                            st.error(f"Programming failed: {msg}")
                with col_f2:
                    if st.button("🔄 Reconnect", use_container_width=True):
                        if BOARD_PORT:
                            rcv.connect(BOARD_PORT)
                        st.rerun()
                with col_f3:
                    if st.button("📊 Switch to Dynamic Simulation", use_container_width=True):
                        st.session_state.data_mode = "Dynamic Simulation Stream"
                        st.rerun()

            if rcv.is_port_open and st.session_state.get("auto_refresh", True):
                time.sleep(1)
                st.rerun()
            st.stop()

except Exception as e:
    st.error(f"Sensor data stream unavailable: {str(e)}")
    st.info("Waiting for valid FPGA telemetry stream...")
    st.stop()


# =============================================================================
# ML Inference & Health Classification
# =============================================================================
# ML Inference & Health Classification
# =============================================================================
try:
    # 0. Pre-evaluate Centralized Engineering Limits & Regional Summary
    prov_map = meta.get("provenance", {})
    reg_baselines = meta.get("regional_baselines") or meta.get("baseline", {})
    eng_assessment = evaluate_engineering_limits(
        latest.to_dict(),
        provenance_map=prov_map,
        regional_baselines=reg_baselines
    )

    # Calibrate history_df timing series across the entire window with Multi-Pblock Quorum & Weights
    history_df = calibrate_history_dataframe(history_df, weights=eng_assessment.regional_weights)
    latest = history_df.iloc[-1].copy()
    curr_ro_freq = float(latest["RO_Frequency"])
    curr_ro_delay = float(latest["RO_Delay_ns"])

    missing_feats = [f for f in model_features if f not in history_df.columns]
    if missing_feats:
        st.error(f"Missing required engineered features: {missing_feats}")
        st.stop()

    # The model was trained on data whose healthy RO frequency is the placeholder nominal. Express
    # this board's frequencies relative to its own baseline so the model judges drift, not the
    # absolute frequency, which depends on how Vivado happened to route the oscillators.
    _k = health_rules.RO_PLACEHOLDER_NOMINAL_MHZ / RO_FREQ_NOMINAL_MHZ
    X_window = history_df[model_features].copy()
    for _c in ("RO_Frequency", "RO_Frequency_mean", "RO_Frequency_std", "RO_Frequency_change"):
        if _c in X_window.columns:
            X_window[_c] = X_window[_c] * _k
    for _c in ("RO_Delay_ns", "RO_Delay_change"):
        if _c in X_window.columns:
            X_window[_c] = X_window[_c] / _k
    history_df["Predicted_Health"] = model.predict(X_window)
    probs = model.predict_proba(X_window)
    history_df["Confidence"] = probs.max(axis=1)

    ml_pred = str(history_df["Predicted_Health"].iloc[-1])
    ml_conf = float(history_df["Confidence"].iloc[-1])

    classes = list(model.classes_)
    latest_probs = probs[-1]
    prob_dict = {cls: float(latest_probs[i]) for i, cls in enumerate(classes)}

    final_health_dict = determine_final_health(ml_pred, ml_conf, eng_assessment)

    latest_pred = final_health_dict["final_health"]
    latest_conf = final_health_dict["confidence"]
    override_applied = final_health_dict["override_applied"]

except Exception as e:
    st.error(f"ML Model inference error: {str(e)}")
    st.stop()


# Baseline and shift metrics
baseline = meta.get("baseline", {})
base_ro_freq = float(baseline.get("RO_Frequency", RO_FREQ_NOMINAL_MHZ))
ro_freq_shift = ((curr_ro_freq - base_ro_freq) / base_ro_freq) * 100.0

base_ro_delay = float(baseline.get("RO_Delay_ns", 0.2294))
ro_delay_shift = ((curr_ro_delay - base_ro_delay) / base_ro_delay) * 100.0

curr_temp = float(latest["Temperature"])
base_temp = float(baseline.get("Temperature", 35.0))
temp_shift = curr_temp - base_temp

def compute_trend(series: pd.Series) -> str:
    if len(series) < 3:
        return "Stable"
    diff = series.iloc[-1] - series.iloc[-3]
    if diff > 0.05 * (abs(series.iloc[-3]) + 1e-6):
        return "Increasing"
    elif diff < -0.05 * (abs(series.iloc[-3]) + 1e-6):
        return "Decreasing"
    return "Stable"

temp_trend = compute_trend(history_df["Temperature"])
ro_freq_trend = compute_trend(history_df["RO_Frequency"])
error_trend = compute_trend(history_df["Error_Rate"])


# =============================================================================
# LangGraph AI Diagnostic Agent Invocation
# =============================================================================
try:
    agent_telemetry = {
        "health": latest_pred,
        "confidence": latest_conf,
        "ml_prediction": ml_pred,
        "ml_confidence": ml_conf,
        "final_health": latest_pred,
        "override_applied": override_applied,
        "override_title": final_health_dict.get("override_title", ""),
        "override_explanation": final_health_dict.get("override_explanation", ""),
        "override_reasons": final_health_dict.get("reasons", []),
        "engineering_evaluations": final_health_dict.get("evaluations", {}),
        "temperature": curr_temp,
        "vccint": float(latest["VCCINT"]),
        "vccaux": float(latest["VCCAUX"]),
        "vccbram": float(latest["VCCBRAM"]),
        "ro_frequency": curr_ro_freq,
        "ro_delay": curr_ro_delay,
        "error_rate": float(latest["Error_Rate"]),
        "ro_freq_shift_pct": ro_freq_shift,
        "ro_delay_shift_pct": ro_delay_shift,
        "temp_shift": temp_shift,
        "temp_trend": temp_trend,
        "ro_freq_trend": ro_freq_trend,
        "error_trend": error_trend,
        "source": meta.get("source_type", "LIVE"),
        "completeness_str": meta.get("completeness_str", "6 / 6"),
        "completeness_count": meta.get("completeness_count", 6),
        "reliability_score": meta.get("reliability_score", 1.0),
        "user_provided": meta.get("user_provided", []),
        "assumed": meta.get("assumed", []),
        "is_estimated": "Estimated" in data_mode
    }
    agent_report = evaluate_fpga_health(agent_telemetry)
except Exception as e:
    agent_report = {
        "risk_level": "UNKNOWN",
        "condition_summary": f"Agent diagnostic unavailable ({str(e)})",
        "primary_indicators": ["Live telemetry available, agentic node returned an exception."],
        "recommended_actions": {"Monitoring": "Continue tracking telemetry channels manually."},
        "life_extension_suggestions": {}
    }


# =============================================================================
# DASHBOARD PRESENTATION (Audited Structure & Separate Graphs)
# =============================================================================

if "UART" in st.session_state.data_mode and BOARD_CAL["state"] in ("waiting", "error"):
    st.warning(
        f"**No valid baseline for the connected board yet:** {BOARD_CAL['reason']}.  \n"
        "Until a baseline is recorded the region states below are compared with placeholder limits "
        "and are not meaningful. Once the board is cool and idle, press **Recalibrate now** in the sidebar."
    )

# 1. Header, FPGA Chip Logo, Monitoring Status
render_header(
    status_label="ESTIMATED MODE" if "Estimated" in data_mode else "ACTIVE",
    source_label=source_badge,
    platform=DEVICE_NAME
)

# 1.1 Hard Engineering Limit Safety Override Alert (if triggered)
if override_applied:
    render_engineering_override_alert(final_health_dict)

# 1.5. ESTIMATED INPUT PROVENANCE & COMPLETENESS BREAKDOWN (Estimated Mode Only)
composite_risk = calculate_aggregate_risk_score(
    health_pred=latest_pred,
    confidence=latest_conf,
    temp=curr_temp,
    ro_freq_shift_pct=ro_freq_shift,
    error_rate=float(latest["Error_Rate"])
)

if "Estimated" in data_mode:
    st.html('<div class="section-header">🔍 Telemetry Input & Provenance Breakdown <span class="tag">ESTIMATION COVERAGE</span></div>')
    render_estimated_input_breakdown(meta=meta, latest=latest)
    render_estimated_stress_index(composite_risk, latest_pred)

if "UART" in data_mode:
    st.html('<div class="section-header">🔌 Hardware UART Interface & Provenance <span class="tag">BASYS 3 ARTIX-7</span></div>')
    render_hardware_connection_panel(meta=meta)

# 2. CURRENT FPGA HEALTH
st.html('<div class="section-header">⚡ Current FPGA Health <span class="tag">' + ('ESTIMATED HEALTH ASSESSMENT' if 'Estimated' in data_mode else 'REAL-TIME STATUS') + '</span></div>')
render_primary_health_kpis(
    health_pred=latest_pred,
    confidence=latest_conf,
    temperature=curr_temp,
    error_rate=float(latest["Error_Rate"])
)

# 3. FPGA MEASUREMENTS
latest_top = latest.copy()
latest_top["RO_Frequency"] = curr_ro_freq
latest_top["RO_Delay_ns"] = curr_ro_delay

st.html('<div class="section-header">📊 FPGA Measurements <span class="tag">XADC & LOGIC TELEMETRY</span></div>')
render_measurements_grid(
    latest=latest_top,
    baseline=baseline,
    sample_num=meta.get("current_index", len(history_df))
)

# 4. RING OSCILLATOR MONITORING
st.html('<div class="section-header">⏱️ Ring Oscillator Aging Indicator <span class="tag">TIMING DEGRADATION</span></div>')
render_ring_oscillator_section(
    latest=latest_top,
    baseline=baseline
)

# 5. FPGA HEALTH TRENDS (Dedicated Independent Graphs)
st.html('<div class="section-header">📈 FPGA Health Trends <span class="tag">INDEPENDENT SENSOR DYNAMICS</span></div>')

col_scale1, col_scale2, col_scale3 = st.columns([2.5, 1.2, 1.3])
with col_scale1:
    st.caption("🔍 **Adaptive Dynamic Scaling**: Magnifies micro-fluctuations & sensor jitter for high-detail inspection; auto-widens for major excursions.")
with col_scale2:
    adaptive_zoom = st.toggle("Adaptive Zoom", value=True, help="Automatically magnifies small fluctuations when enabled.")
with col_scale3:
    zoom_choice = st.select_slider(
        "Zoom Level",
        options=["Standard (1x)", "High (3x)", "Ultra Zoom (10x)"],
        value="Ultra Zoom (10x)",
        disabled=not adaptive_zoom,
        help="Higher zoom narrows headroom to focus strictly on tiny variations with maximum vertical detail."
    )
    zoom_map = {"Standard (1x)": 1.0, "High (3x)": 3.0, "Ultra Zoom (10x)": 10.0}
    active_zoom_factor = zoom_map.get(zoom_choice, 5.0)

trend_tab1, trend_tab2, trend_tab3, trend_tab4, trend_tab5 = st.tabs([
    "⏱️ RO Frequency & Timing Delay",
    "🌡️ Die Temperature",
    "⚡ Supply Voltage Rails",
    "⚠️ Functional Error Rate",
    "🏷️ ML State & Multi-Sensor Index"
])

with trend_tab1:
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        st.caption(f"**Ring Oscillator Frequency Trend (MHz)** (Cyan line: Calibrated Overall Frequency, Blue dashed: Baseline {RO_FREQ_NOMINAL_MHZ:.1f} MHz, Orange/Red dashed: Warning/Critical limits)")
        st.altair_chart(create_ro_frequency_chart(history_df, baseline_freq=base_ro_freq, adaptive_scaling=adaptive_zoom, zoom_factor=active_zoom_factor), width="stretch")
    with col_g2:
        st.caption("**Ring Oscillator Delay Trend (Derived RO Stage Delay in ns)** (Magenta line: Calibrated Derived Delay, Purple dashed: Baseline 0.2294 ns, Orange/Red dashed: Warning/Critical limits)")
        st.altair_chart(create_ro_delay_chart(history_df, baseline_delay=base_ro_delay, adaptive_scaling=adaptive_zoom, zoom_factor=active_zoom_factor), width="stretch")

with trend_tab2:
    st.caption("**FPGA Die Temperature Trend (°C)** (Red line: measurement, Green dashed: baseline 35°C, Orange dashed: 50°C warning)")
    st.altair_chart(create_temperature_chart(history_df, baseline_temp=base_temp, adaptive_scaling=adaptive_zoom, zoom_factor=active_zoom_factor), width="stretch")

with trend_tab3:
    col_v1, col_v2, col_v3 = st.columns(3)
    with col_v1:
        st.caption("**VCCINT (1.000V Core Rail)**")
        st.altair_chart(create_voltage_chart(history_df, "VCCINT", 1.000, adaptive_scaling=adaptive_zoom, zoom_factor=active_zoom_factor), width="stretch")
    with col_v2:
        st.caption("**VCCAUX (1.800V Auxiliary Rail)**")
        st.altair_chart(create_voltage_chart(history_df, "VCCAUX", 1.800, adaptive_scaling=adaptive_zoom, zoom_factor=active_zoom_factor), width="stretch")
    with col_v3:
        st.caption("**VCCBRAM (1.000V BRAM Rail)**")
        st.altair_chart(create_voltage_chart(history_df, "VCCBRAM", 1.000, adaptive_scaling=adaptive_zoom, zoom_factor=active_zoom_factor), width="stretch")

with trend_tab4:
    st.caption("**Functional Error Rate Trend** (Amber area: soft error probability)")
    st.altair_chart(create_error_rate_chart(history_df, adaptive_scaling=adaptive_zoom, zoom_factor=active_zoom_factor), width="stretch")

with trend_tab5:
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.caption("**FPGA Health Prediction Trend** (Healthy, Warning, Degraded)")
        st.altair_chart(create_health_prediction_trend_chart(history_df), width="stretch")
    with col_s2:
        st.caption("**Normalized FPGA Health Indicators** (Normalized sensor indicators: 0.0=nominal, 1.0=stress)")
        st.altair_chart(create_normalized_indicators_chart(history_df), width="stretch")


# 6. BASELINE COMPARISON
st.html('<div class="section-header">⚖️ Baseline Comparison <span class="tag">DRIFT ANALYSIS</span></div>')
render_baseline_comparison(
    latest=latest,
    baseline=baseline
)

# 7. SENSOR STATUS EVALUATION
st.html('<div class="section-header">🔍 Current Sensor Status <span class="tag">THRESHOLD EVALUATION</span></div>')
render_sensor_status_table(
    latest=latest,
    history_df=history_df,
    provenance_map=meta.get("provenance", {})
)

# 8. ML HEALTH PREDICTION & ENGINEERING SAFETY EVALUATION
st.html('<div class="section-header">🤖 Machine Learning Prediction & Safety Evaluation <span class="tag">RANDOM FOREST + SAFETY ENVELOPE</span></div>')
col_m1, col_m2 = st.columns([1, 1])

with col_m1:
    override_badge_html = ""
    if override_applied:
        override_badge_html = f"""
        <div style="background: rgba(255, 23, 68, 0.15); border: 1px solid #FF1744; border-radius: 6px; padding: 8px 12px; margin-bottom: 12px;">
            <div style="color: #FF1744; font-weight: 700; font-size: 0.8rem; text-transform: uppercase; font-family: 'JetBrains Mono', monospace;">
                ⚠️ HARD ENGINEERING LIMIT OVERRIDE ACTIVE
            </div>
            <div style="color: #CBD5E1; font-size: 0.78rem; margin-top: 2px;">
                Final Assessment: <strong style="color: {HEALTH_COLORS.get(latest_pred, '#FF1744')};">{latest_pred.upper()}</strong> takes precedence over ML classifier.
            </div>
        </div>
        """

    st.html(f"""
    <div style="background: #111827; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 16px; height: 100%;">
        <div style="font-size: 0.8rem; color: #94A3B8; text-transform: uppercase; font-family: 'JetBrains Mono', monospace; margin-bottom: 6px;">
            Dual Architecture: ML Model + Safety Envelope
        </div>
        <div style="font-size: 1.25rem; font-weight: 700; color: #F8FAFC; margin-bottom: 12px;">
            Random Forest Ensemble (200 Estimators)
        </div>
        {override_badge_html}
        <div style="margin-bottom: 8px;">
            <span style="color: #94A3B8; font-size: 0.85rem;">Raw ML Prediction:</span>
            <span style="color: {HEALTH_COLORS.get(ml_pred, '#00E676')}; font-weight: 700; font-family: 'JetBrains Mono', monospace; font-size: 1.0rem; margin-left: 6px;">
                {ml_pred.upper()}
            </span>
            <span style="color: #64748B; font-size: 0.8rem; margin-left: 4px;">({ml_conf * 100:.1f}% conf)</span>
        </div>
        <div style="margin-bottom: 8px;">
            <span style="color: #94A3B8; font-size: 0.85rem;">Final Health Assessment:</span>
            <span style="color: {HEALTH_COLORS.get(latest_pred, '#00E676')}; font-weight: 800; font-family: 'JetBrains Mono', monospace; font-size: 1.05rem; margin-left: 6px;">
                {latest_pred.upper()}
            </span>
            {"<span style='color: #FF5252; font-size: 0.78rem; font-weight: 600; margin-left: 6px;'>[OVERRIDDEN]</span>" if override_applied else "<span style='color: #00E676; font-size: 0.78rem; margin-left: 6px;'>[CONFIRMED]</span>"}
        </div>
        <div style="margin-bottom: 14px;">
            <span style="color: #94A3B8; font-size: 0.85rem;">Overall Classification Confidence:</span>
            <span style="color: #00E5FF; font-weight: 700; font-family: 'JetBrains Mono', monospace; font-size: 1.05rem; margin-left: 6px;">
                {latest_conf * 100:.1f} %
            </span>
        </div>
        <div style="font-size: 0.8rem; color: #94A3B8; margin-bottom: 6px;">Raw ML Class Probability Breakdown:</div>
    </div>
    """)

    for cls_name in classes:
        prob_val = prob_dict.get(cls_name, 0.0)
        st.write(f"**{cls_name}**: {prob_val * 100:.1f}%")
        st.progress(min(1.0, max(0.0, prob_val)))

with col_m2:
    if hasattr(model, "feature_importances_"):
        st.caption("**Top Engineered Features Contributing to Prediction**")
        st.altair_chart(
            create_feature_importance_chart(model_features, model.feature_importances_, top_n=7),
            width="stretch"
        )


# 9. FPGA FOUR-REGION PHYSICAL HEALTH ARCHITECTURE
st.html('<div class="section-header">🗺️ Four-Region Physical FPGA Health Architecture <span class="tag">PHYSICAL 2×2 SILICON QUADRANTS</span></div>')
four_regions = generate_four_region_data(
    latest.to_dict(),
    meta.get("regional_baselines") or meta.get("baseline", {})
)
st.html(render_four_region_map_html(
    four_regions,
    composite_risk,
    weighted_summary=getattr(eng_assessment, "weighted_summary", None)
))


# 10. AI AGENT RECOMMENDATIONS (LangGraph)
st.html('<div class="section-header">🧠 AI Agent Diagnostic Recommendations <span class="tag">LANGGRAPH REASONING</span></div>')
render_agent_recommendations_section(agent_report)


# 11. FPGA LIFE EXTENSION SUGGESTIONS
st.html('<div class="section-header">🛡️ FPGA Lifetime Extension Guidelines <span class="tag">PROACTIVE MAINTENANCE</span></div>')
render_life_extension_section(agent_report)


# 12. LATEST MEASUREMENTS TABLE & ENGINEERED FEATURES EXPANDER
st.html('<div class="section-header">📋 Latest Telemetry Records <span class="tag">HISTORICAL BUFFER</span></div>')

raw_display_cols = [
    "Temperature", "VCCINT", "VCCAUX", "VCCBRAM",
    "RO_Frequency", "RO_Delay_ns"
]
for r in ["RO_R1", "RO_R2", "RO_R3", "RO_R4"]:
    if r in history_df.columns:
        raw_display_cols.append(r)
raw_display_cols.append("Error_Rate")
if "Predicted_Health" in history_df.columns:
    raw_display_cols.append("Predicted_Health")
if "Confidence" in history_df.columns:
    raw_display_cols.append("Confidence")

format_dict = {
    "Temperature": "{:.2f} °C",
    "VCCINT": "{:.4f} V",
    "VCCAUX": "{:.4f} V",
    "VCCBRAM": "{:.4f} V",
    "RO_Frequency": "{:.2f} MHz",
    "RO_Delay_ns": "{:.4f} ns",
    "Error_Rate": "{:.6f}",
    "Confidence": "{:.1%}"
}
for r in ["RO_R1", "RO_R2", "RO_R3", "RO_R4"]:
    if r in history_df.columns:
        format_dict[r] = "{:.2f} MHz"

st.dataframe(
    history_df[raw_display_cols].tail(15).style.format(format_dict),
    width="stretch"
)

with st.expander("🔬 Show Engineered ML Features (Differences & Rolling Statistics)"):
    st.dataframe(history_df.tail(15), width="stretch")

with st.expander("⚖️ Compare Hardware Telemetry vs Estimated Assessment"):
    est_src = st.session_state.get("estimated_source", EstimatedDataSource())
    render_hardware_vs_estimated_comparison(
        hw_latest=latest,
        est_inputs=est_src.user_inputs if hasattr(est_src, "user_inputs") else {},
        hw_pred=latest_pred,
        est_pred=latest_pred
    )


# 13. RESEARCH TRANSPARENCY & SYSTEM INFORMATION
with st.expander("ℹ️ System Information & Scientific Research Methodology"):
    st.markdown(f"""
    ### 🔬 System Architecture Pipeline
    ```
    +-----------------------------------------------------------------------------------+
    |                             DIGILENT BASYS 3 ARTIX-7                              |
    |  +-----------------------+   +----------------------+   +-----------------------+ |
    |  |  Ring Oscillator (RO) |   |    XADC Temp/Voltage |   |   Functional Error    | |
    |  |  Aging Delay Sensor   |   |   Die Monitor (1MSPS)|   |    Monitor Engine     | |
    |  +-----------+-----------+   +----------+-----------+   +-----------+-----------+ |
    +--------------|--------------------------|---------------------------|-------------+
                   +--------------------------+---------------------------+
                                              | UART Serial (115200 Baud)
                                              v
    +-----------------------------------------------------------------------------------+
    |                              HOST PROCESSING PIPELINE                             |
    |  +-----------------------+   +----------------------+   +-----------------------+ |
    |  |  Data Validation &    |-->| Feature Engineering  |-->| ML Model (Random      | |
    |  |  Sanitization Layer   |   | (Delta + Rolling Std)|   | Forest Classifier)    | |
    |  +-----------------------+   +----------------------+   +-----------+-----------+ |
    |                                                                     |             |
    |                                                                     v             |
    |  +-----------------------+   +----------------------+   +-----------------------+ |
    |  |  Streamlit Visual     |<--| Actionable Life-     |<--| LangGraph Diagnostic  | |
    |  |  Research Dashboard   |   | Extension Advisory   |   | Reasoning Agent       | |
    |  +-----------------------+   +----------------------+   +-----------------------+ |
    +-----------------------------------------------------------------------------------+
    ```

    **Key Technical Distinctions:**
    - **Observed Telemetry**: Measured hardware signals (XADC die temperature, supply voltages, RO frequency, and soft error rates).
    - **Inferred Health**: Numerical classification state generated by the trained Random Forest classifier (**Healthy**, **Warning**, **Degraded**).
    - **Recommended Actions**: Diagnostic hypotheses and operational life-extension strategies formulated by the LangGraph agentic reasoning graph.
    - **Non-Self-Healing System**: This system performs continuous monitoring, anomaly prediction, risk assessment, and recommendation. It does *not* autonomously repair or reconfigure on-chip hardware logic.

    **Development & Simulation Notice:**
    *Development mode: predictions and demonstrations currently utilize validated synthetic/mock FPGA aging data. Final hardware validation requires continuous accelerated aging data acquired from the physical Artix-7 board.*
    """)


# =============================================================================
# Auto-Refresh Handler
# =============================================================================
if st.session_state.auto_refresh:
    time.sleep(st.session_state.refresh_rate)
    st.rerun()