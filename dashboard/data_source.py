"""
Modular Data Source Interface for FPGA Health Monitoring
=========================================================
Provides clean abstraction for swapping between:
- Mock CSV Dataset Replay (MockCSVDataSource)
- Real-Time Dynamic Simulation (LiveSimulationDataSource)
- Physical Basys 3 Artix-7 UART Stream (LiveUARTDataSource)
"""

from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List
import time
import random
import numpy as np
import pandas as pd

from config import RO_STAGES, calculate_ro_delay_ns
import health_rules as _hr
from ml.feature_engineering import create_features
from communication.uart_receiver import FPGAUARTReceiver
from dashboard.config import (
    SENSOR_CONFIG,
    REGIONAL_CONFIG,
    evaluate_engineering_limits,
    validate_regional_baseline,
    LimitSeverity
)


# Nominal RO frequencies come from the single source of truth (health_rules.py)
_NOM = _hr.global_nominal_mhz()
_nom = _hr.region_nominal_mhz


def _apply_calibration(base: Dict[str, float]) -> Dict[str, float]:
    """A saved per-board calibration is authoritative for the RO baselines. Without it the
    baseline stays as given (measured from the first live readings or the placeholder)."""
    if _hr.load_calibration() is None:
        return base
    out = dict(base)
    out["RO_Frequency"] = _NOM
    out["RO_Delay_ns"] = round(100.0 / _NOM, 4)
    for r in ("R1", "R2", "R3", "R4"):
        out[f"RO_{r}"] = _nom(r)
        out[f"RO_{r}_Delay_ns"] = round(100.0 / _nom(r), 4)
    return out


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV_PATH = PROJECT_ROOT / "data" / "raw" / "mock_fpga_data.csv"


def validate_and_clean_data(df: pd.DataFrame) -> Tuple[pd.DataFrame, bool, List[str]]:
    """
    Validates sensor telemetry for missing columns, NaNs, and impossible physical bounds.
    Returns: (cleaned_df, is_valid, warning_messages)
    """
    warnings: List[str] = []
    if df is None or df.empty:
        return pd.DataFrame(), False, ["No telemetry data received."]

    required_cols = ["Temperature", "VCCINT", "VCCAUX", "VCCBRAM", "RO_Frequency", "Error_Rate"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        return df, False, [f"Missing required sensor channels: {', '.join(missing)}"]

    clean_df = df.copy()

    # Fill NaNs or drop invalid rows
    if clean_df[required_cols].isna().any().any():
        warnings.append("NaN values detected in sensor stream; applying forward-fill interpolation.")
        clean_df = clean_df.ffill().bfill()

    # Check and derive RO_Delay_ns using correct physical formula if missing
    if "RO_Delay_ns" not in clean_df.columns or clean_df["RO_Delay_ns"].isna().any():
        clean_df["RO_Delay_ns"] = clean_df["RO_Frequency"].apply(lambda f: calculate_ro_delay_ns(f, RO_STAGES))

    # Derive regional delays if regional RO frequencies present
    for r in ["R1", "R2", "R3", "R4"]:
        ro_col = f"RO_{r}"
        del_col = f"RO_{r}_Delay_ns"
        if ro_col in clean_df.columns and (del_col not in clean_df.columns or clean_df[del_col].isna().any()):
            clean_df[del_col] = clean_df[ro_col].apply(lambda f: calculate_ro_delay_ns(f, RO_STAGES))

    # Physical bounds checks (Absolute sensor limits)
    for col, cfg in SENSOR_CONFIG.items():
        if col in clean_df.columns:
            min_v = cfg.get("physical_min", cfg.get("min_valid", -40.0))
            max_v = cfg.get("physical_max", cfg.get("max_valid", 125.0))
            out_of_bounds = ((clean_df[col] < min_v) | (clean_df[col] > max_v)).sum()
            if out_of_bounds > 0:
                warnings.append(f"{out_of_bounds} samples in {col} exceeded physical sensor bounds [{min_v}, {max_v}]. Clipping.")
                clean_df[col] = clean_df[col].clip(lower=min_v, upper=max_v)

    return clean_df, True, warnings


class MockCSVDataSource:
    """
    Replays historical mock dataset from CSV file.
    Supports step-by-step scrubber/playhead indexing.
    """

    def __init__(self, csv_path: Path = DEFAULT_CSV_PATH):
        self.csv_path = csv_path
        self.raw_df: pd.DataFrame = pd.DataFrame()
        self.engineered_df: pd.DataFrame = pd.DataFrame()
        self.baseline_sample: Optional[pd.Series] = None
        self.load_data()

    def load_data(self):
        if not self.csv_path.exists():
            raise FileNotFoundError(f"Mock FPGA data file not found at: {self.csv_path}")

        raw = pd.read_csv(self.csv_path)
        clean_df, is_valid, _ = validate_and_clean_data(raw)
        if not is_valid:
            raise ValueError("Mock dataset failed validation checks.")

        self.raw_df = clean_df
        # If regional RO channels not in mock data, derive them with slight spatial variance
        if "RO_R1" not in self.raw_df.columns:
            self.raw_df["RO_R1"] = (self.raw_df["RO_Frequency"] + 0.3).round(2)
            self.raw_df["RO_R2"] = (self.raw_df["RO_Frequency"] - 0.2).round(2)
            self.raw_df["RO_R3"] = (self.raw_df["RO_Frequency"] + 0.1).round(2)
            self.raw_df["RO_R4"] = (self.raw_df["RO_Frequency"] - 0.1).round(2)
            for r in ["R1", "R2", "R3", "R4"]:
                self.raw_df[f"RO_{r}_Delay_ns"] = self.raw_df[f"RO_{r}"].apply(lambda f: calculate_ro_delay_ns(f, RO_STAGES))

        # The CSV was generated around the placeholder nominal; when a board is calibrated,
        # rescale it so "healthy" in the replay means healthy for that board.
        _ref = _hr.RO_PLACEHOLDER_NOMINAL_MHZ
        if abs(_NOM - _ref) > 1e-9 or any(abs(_nom(r) - _ref) > 1e-9 for r in ["R1", "R2", "R3", "R4"]):
            self.raw_df["RO_Frequency"] = self.raw_df["RO_Frequency"] * (_NOM / _ref)
            self.raw_df["RO_Delay_ns"] = self.raw_df["RO_Frequency"].apply(lambda f: calculate_ro_delay_ns(f, RO_STAGES))
            for r in ["R1", "R2", "R3", "R4"]:
                self.raw_df[f"RO_{r}"] = (self.raw_df[f"RO_{r}"] * (_nom(r) / _ref)).round(2)
                self.raw_df[f"RO_{r}_Delay_ns"] = self.raw_df[f"RO_{r}"].apply(lambda f: calculate_ro_delay_ns(f, RO_STAGES))

        # Baseline from early healthy samples (first 50 samples average)
        early_window = self.raw_df.head(50)
        base_cols = ["Temperature", "VCCINT", "VCCAUX", "VCCBRAM", "RO_Frequency", "RO_Delay_ns", "Error_Rate"]
        for r in ["R1", "R2", "R3", "R4"]:
            if f"RO_{r}" in self.raw_df.columns:
                base_cols.extend([f"RO_{r}", f"RO_{r}_Delay_ns"])
        self.baseline_sample = early_window[base_cols].mean()
        
        # Precompute features across full historical dataset
        self.engineered_df = create_features(self.raw_df.copy())

    def get_data(self, window_size: int = 150, sample_idx: Optional[int] = None) -> Tuple[pd.DataFrame, pd.Series, Dict[str, Any]]:
        total_samples = len(self.engineered_df)
        if sample_idx is None or sample_idx >= total_samples:
            sample_idx = total_samples - 1
        elif sample_idx < 0:
            sample_idx = 0

        # Extract window up to sample_idx
        start_idx = max(0, sample_idx - window_size + 1)
        history_df = self.engineered_df.iloc[start_idx:sample_idx + 1].copy()
        latest_sample = self.engineered_df.iloc[sample_idx].copy()

        base_dict = self.baseline_sample.to_dict() if self.baseline_sample is not None else {}
        regional_baselines = {}
        for r in ["R1", "R2", "R3", "R4"]:
            ro_k = f"RO_{r}"
            cand = base_dict.get(ro_k)
            _, chosen_base, _, _ = validate_regional_baseline(r, cand)
            regional_baselines[ro_k] = chosen_base

        eng_assessment = evaluate_engineering_limits(
            latest_sample.to_dict(),
            regional_baselines=regional_baselines
        )

        metadata = {
            "source_type": "MOCK",
            "source_label": "MOCK CSV DATASET",
            "total_samples": total_samples,
            "current_index": sample_idx,
            "baseline": base_dict,
            "regional_baselines": regional_baselines,
            "engineering_assessment": eng_assessment.to_dict(),
            "provenance": {
                "Temperature": "MOCK_REPLAY",
                "VCCINT": "MOCK_REPLAY",
                "VCCAUX": "MOCK_REPLAY",
                "VCCBRAM": "MOCK_REPLAY",
                "RO_Frequency": "MOCK_REPLAY",
                "RO_Delay_ns": "DERIVED",
                "Error_Rate": "MOCK_REPLAY",
                "RO_R1": "DERIVED_SPATIAL",
                "RO_R2": "DERIVED_SPATIAL",
                "RO_R3": "DERIVED_SPATIAL",
                "RO_R4": "DERIVED_SPATIAL"
            }
        }
        return history_df, latest_sample, metadata

    def reset(self):
        pass


class LiveSimulationDataSource:
    """
    Generates dynamic step-by-step FPGA sensor measurements in real time,
    gradually simulating aging degradation drift.
    """

    def __init__(self, buffer_size: int = 200):
        self.buffer_size = buffer_size
        self.buffer: List[Dict[str, float]] = []
        self.step_count = 0
        self.baseline_sample = {
            "Temperature": 35.0,
            "VCCINT": 1.000,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": _NOM,
            "RO_Delay_ns": 0.2294,
            "RO_R1": _nom("R1"),
            "RO_R1_Delay_ns": 0.2294,
            "RO_R2": _nom("R2"),
            "RO_R2_Delay_ns": 0.2294,
            "RO_R3": _nom("R3"),
            "RO_R3_Delay_ns": 0.2294,
            "RO_R4": _nom("R4"),
            "RO_R4_Delay_ns": 0.2294,
            "Error_Rate": 0.00001
        }
        self._initialize_buffer()

    def _initialize_buffer(self):
        self.buffer.clear()
        self.step_count = 0
        for i in range(50):
            deg = i / 1000.0
            meas = self._generate_step(deg)
            self.buffer.append(meas)

    def _generate_step(self, degradation: float) -> Dict[str, float]:
        self.step_count += 1
        deg = min(1.0, max(0.0, degradation))
        
        temp = 35.0 + 18.0 * deg + np.random.normal(0, 0.7)
        vccint = 1.000 - 0.010 * deg + np.random.normal(0, 0.0008)
        vccaux = 1.800 - 0.010 * deg + np.random.normal(0, 0.0008)
        vccbram = 1.000 - 0.008 * deg + np.random.normal(0, 0.0008)
        ro_freq = _NOM * (1.0 - 0.0573 * deg) + np.random.normal(0, 0.6)
        ro_delay = calculate_ro_delay_ns(ro_freq, stages=RO_STAGES)
        
        # Regional RO drift simulation
        ro_r1 = ro_freq + 0.3 - 2.0 * deg + np.random.normal(0, 0.3)
        ro_r2 = ro_freq - 0.2 - 2.5 * deg + np.random.normal(0, 0.3)
        ro_r3 = ro_freq + 0.1 - 1.8 * deg + np.random.normal(0, 0.3)
        ro_r4 = ro_freq - 0.1 - 3.0 * deg + np.random.normal(0, 0.3)

        base_err = 0.00001 + 0.003 * deg
        err_rate = max(0.0, base_err + np.random.normal(0, 0.00015))

        return {
            "Timestamp": time.time(),
            "Temperature": round(temp, 2),
            "VCCINT": round(vccint, 4),
            "VCCAUX": round(vccaux, 4),
            "VCCBRAM": round(vccbram, 4),
            "RO_Frequency": round(ro_freq, 2),
            "RO_Delay_ns": round(ro_delay, 4),
            "RO_R1": round(ro_r1, 2),
            "RO_R1_Delay_ns": round(calculate_ro_delay_ns(ro_r1, stages=RO_STAGES), 4),
            "RO_R2": round(ro_r2, 2),
            "RO_R2_Delay_ns": round(calculate_ro_delay_ns(ro_r2, stages=RO_STAGES), 4),
            "RO_R3": round(ro_r3, 2),
            "RO_R3_Delay_ns": round(calculate_ro_delay_ns(ro_r3, stages=RO_STAGES), 4),
            "RO_R4": round(ro_r4, 2),
            "RO_R4_Delay_ns": round(calculate_ro_delay_ns(ro_r4, stages=RO_STAGES), 4),
            "Error_Rate": round(err_rate, 6)
        }

    def step(self, degradation: float = 0.0):
        new_meas = self._generate_step(degradation)
        self.buffer.append(new_meas)
        if len(self.buffer) > self.buffer_size:
            self.buffer.pop(0)

    def get_data(self, window_size: int = 150, sample_idx: Optional[int] = None) -> Tuple[pd.DataFrame, pd.Series, Dict[str, Any]]:
        raw_df = pd.DataFrame(self.buffer)
        clean_df, _, _ = validate_and_clean_data(raw_df)
        engineered_df = create_features(clean_df)

        history_df = engineered_df.tail(window_size).copy()
        latest_sample = engineered_df.iloc[-1].copy()

        regional_baselines = {}
        for r in ["R1", "R2", "R3", "R4"]:
            ro_k = f"RO_{r}"
            cand = self.baseline_sample.get(ro_k)
            _, chosen_base, _, _ = validate_regional_baseline(r, cand)
            regional_baselines[ro_k] = chosen_base

        eng_assessment = evaluate_engineering_limits(
            latest_sample.to_dict(),
            regional_baselines=regional_baselines
        )

        metadata = {
            "source_type": "SIMULATION",
            "source_label": "DYNAMIC SIMULATION STREAM",
            "total_samples": len(engineered_df),
            "current_index": len(engineered_df) - 1,
            "baseline": self.baseline_sample,
            "regional_baselines": regional_baselines,
            "engineering_assessment": eng_assessment.to_dict(),
            "provenance": {
                "Temperature": "SIMULATION",
                "VCCINT": "SIMULATION",
                "VCCAUX": "SIMULATION",
                "VCCBRAM": "SIMULATION",
                "RO_Frequency": "SIMULATION",
                "RO_Delay_ns": "DERIVED",
                "Error_Rate": "SIMULATION",
                "RO_R1": "SIMULATION",
                "RO_R2": "SIMULATION",
                "RO_R3": "SIMULATION",
                "RO_R4": "SIMULATION"
            }
        }
        return history_df, latest_sample, metadata

    def reset(self):
        self._initialize_buffer()


class LiveUARTDataSource:
    """
    Receives live sensor telemetry over Serial/UART from the physical Artix-7 board.
    Buffers incoming measurements and generates rolling feature windows for ML and UI.
    """

    def __init__(self, port: str = "COM3", baudrate: int = 115200, buffer_size: int = 200):
        self.receiver = FPGAUARTReceiver(port=port, baudrate=baudrate)
        self.buffer_size = buffer_size
        self.buffer: List[Dict[str, float]] = []
        self.baseline_sample: Optional[Dict[str, float]] = None

    def connect(self) -> bool:
        return self.receiver.connect()

    def disconnect(self):
        self.receiver.disconnect()

    def poll_hardware(self) -> Optional[Dict[str, Any]]:
        # Allow initial packet capture on fresh connection if buffer is currently empty
        if not self.buffer and self.receiver.is_port_open:
            time.sleep(0.15)
        last_packet = None
        while True:
            packet = self.receiver.read_packet()
            if not packet:
                break
            last_packet = packet
            if "Temperature" in packet:
                meas_dict = {
                    "Timestamp": packet.get("Timestamp", time.time()),
                    "Temperature": float(packet["Temperature"]),
                    "VCCINT": float(packet["VCCINT"]),
                    "VCCAUX": float(packet["VCCAUX"]),
                    "VCCBRAM": float(packet["VCCBRAM"]),
                    "RO_Frequency": float(packet["RO_Frequency"]),
                    "RO_Delay_ns": float(packet["RO_Delay_ns"]),
                    "Error_Rate": float(packet["Error_Rate"])
                }
                for r in ["RO_R1", "RO_R2", "RO_R3", "RO_R4", "RO_R1_Delay_ns", "RO_R2_Delay_ns", "RO_R3_Delay_ns", "RO_R4_Delay_ns"]:
                    if r in packet:
                        meas_dict[r] = float(packet[r])
                    elif r.startswith("RO_R") and not r.endswith("_Delay_ns"):
                        meas_dict[r] = float(packet["RO_Frequency"])
                        meas_dict[f"{r}_Delay_ns"] = float(packet["RO_Delay_ns"])

                self.buffer.append(meas_dict)
                if len(self.buffer) > self.buffer_size:
                    self.buffer.pop(0)

                if self.baseline_sample is None and len(self.buffer) >= 5:
                    init_df = pd.DataFrame(self.buffer[:5])
                    base_cols = ["Temperature", "VCCINT", "VCCAUX", "VCCBRAM", "RO_Frequency", "RO_Delay_ns", "Error_Rate"]
                    for r in ["RO_R1", "RO_R2", "RO_R3", "RO_R4", "RO_R1_Delay_ns", "RO_R2_Delay_ns", "RO_R3_Delay_ns", "RO_R4_Delay_ns"]:
                        if r in init_df.columns:
                            base_cols.append(r)
                    cand_base = init_df[base_cols].mean().to_dict()

                    # Validate candidate baseline: A baseline MUST represent a verified healthy state.
                    # Degraded or out-of-limits initial readings must NOT poison the baseline reference.
                    is_candidate_healthy = True
                    for r in ["R1", "R2", "R3", "R4"]:
                        ro_k = f"RO_{r}"
                        if ro_k in cand_base:
                            is_v, _, _, _ = validate_regional_baseline(r, cand_base[ro_k])
                            if not is_v:
                                is_candidate_healthy = False
                                break

                    cand_eng = evaluate_engineering_limits(cand_base)
                    if not is_candidate_healthy or cand_eng.has_hard_violations or cand_eng.max_severity != LimitSeverity.NORMAL:
                        # Reject candidate; fall back to documented factory nominals
                        self.baseline_sample = _apply_calibration({
                            "Temperature": 35.0,
                            "VCCINT": 1.000,
                            "VCCAUX": 1.800,
                            "VCCBRAM": 1.000,
                            "RO_Frequency": _NOM,
                            "RO_Delay_ns": 0.2294,
                            "RO_R1": _nom("R1"),
                            "RO_R1_Delay_ns": 0.2294,
                            "RO_R2": _nom("R2"),
                            "RO_R2_Delay_ns": 0.2294,
                            "RO_R3": _nom("R3"),
                            "RO_R3_Delay_ns": 0.2294,
                            "RO_R4": _nom("R4"),
                            "RO_R4_Delay_ns": 0.2294,
                            "Error_Rate": 0.000010
                        })
                    else:
                        self.baseline_sample = _apply_calibration(cand_base)
        return last_packet

    def get_data(self, window_size: int = 150, sample_idx: Optional[int] = None) -> Tuple[pd.DataFrame, pd.Series, Dict[str, Any]]:
        if not self.buffer:
            dummy = [{
                "Timestamp": time.time(),
                "Temperature": 35.0,
                "VCCINT": 1.000,
                "VCCAUX": 1.800,
                "VCCBRAM": 1.000,
                "RO_Frequency": _NOM,
                "RO_Delay_ns": 0.2294,
                "RO_R1": _nom("R1"),
                "RO_R1_Delay_ns": 0.2294,
                "RO_R2": _nom("R2"),
                "RO_R2_Delay_ns": 0.2294,
                "RO_R3": _nom("R3"),
                "RO_R3_Delay_ns": 0.2294,
                "RO_R4": _nom("R4"),
                "RO_R4_Delay_ns": 0.2294,
                "Error_Rate": 0.000010
            }]
            raw_df = pd.DataFrame(dummy)
        else:
            raw_df = pd.DataFrame(self.buffer)

        clean_df, _, _ = validate_and_clean_data(raw_df)
        engineered_df = create_features(clean_df)

        history_df = engineered_df.tail(window_size).copy()
        latest_sample = engineered_df.iloc[-1].copy()

        diagnostics = self.receiver.get_diagnostics()

        has_real_data = (len(self.buffer) > 0)
        prov_map = {
            "Temperature": "MEASURED" if has_real_data else "UNAVAILABLE",
            "VCCINT": "MEASURED" if has_real_data else "UNAVAILABLE",
            "VCCAUX": "MEASURED" if has_real_data else "UNAVAILABLE",
            "VCCBRAM": "MEASURED" if has_real_data else "UNAVAILABLE",
            "RO_Frequency": "MEASURED" if has_real_data else "UNAVAILABLE",
            "RO_Delay_ns": "DERIVED" if has_real_data else "UNAVAILABLE",
            "Error_Rate": "SIMULATED" if has_real_data else "UNAVAILABLE"      # the board has no error counter
        }
        for r in ["RO_R1", "RO_R2", "RO_R3", "RO_R4"]:
            prov_map[r] = "MEASURED" if (has_real_data and r in latest_sample) else "UNAVAILABLE"
            prov_map[f"{r}_Delay_ns"] = "DERIVED" if (has_real_data and r in latest_sample) else "UNAVAILABLE"

        regional_baselines = {}
        for r in ["R1", "R2", "R3", "R4"]:
            ro_k = f"RO_{r}"
            cand_val = (self.baseline_sample or {}).get(ro_k)
            _, chosen_base, _, _ = validate_regional_baseline(r, cand_val)
            regional_baselines[ro_k] = chosen_base

        eng_assessment = evaluate_engineering_limits(
            latest_sample.to_dict(),
            provenance_map=prov_map,
            regional_baselines=regional_baselines
        )

        metadata = {
            "source_type": "LIVE_UART",
            "source_label": f"LIVE UART ({self.receiver.port})",
            "has_real_data": has_real_data,
            "is_stale": self.receiver.is_stale,
            "data_age_s": self.receiver.data_age_s,
            "build_id": self.receiver.last_build_id,
            "is_streaming": self.receiver.is_streaming,
            "is_port_open": self.receiver.is_port_open,
            "is_connected": self.receiver.is_connected,
            "state": self.receiver.state.value,
            "last_error_msg": self.receiver.last_error_msg,
            "packet_count": self.receiver.packet_count,
            "error_count": self.receiver.error_count,
            "packet_rate_hz": self.receiver.get_packet_rate_hz(),
            "handshake_detected": self.receiver.handshake_detected,
            "diagnostics": diagnostics,
            "user_provided": ["Temperature", "VCCINT", "VCCAUX", "VCCBRAM", "RO_Frequency", "Error_Rate"],
            "derived": ["RO_Delay_ns"],
            "assumed": [],
            "provenance": prov_map,
            "engineering_assessment": eng_assessment.to_dict(),
            "regional_baselines": regional_baselines,
            "baseline": self.baseline_sample or {
                "Temperature": 35.0,
                "VCCINT": 1.000,
                "VCCAUX": 1.800,
                "VCCBRAM": 1.000,
                "RO_Frequency": _NOM,
                "RO_Delay_ns": 0.2294,
                "RO_R1": _nom("R1"),
                "RO_R1_Delay_ns": 0.2294,
                "RO_R2": _nom("R2"),
                "RO_R2_Delay_ns": 0.2294,
                "RO_R3": _nom("R3"),
                "RO_R3_Delay_ns": 0.2294,
                "RO_R4": _nom("R4"),
                "RO_R4_Delay_ns": 0.2294,
                "Error_Rate": 0.000010
            }
        }
        return history_df, latest_sample, metadata

    def reset(self):
        self.buffer.clear()
        self.baseline_sample = None


class EstimatedDataSource:
    """
    Synthesizes a valid FPGA telemetry frame from user-provided manual inputs.
    Gracefully handles partial inputs, deterministic physical derivations (RO Delay),
    nominal baseline imputation for omitted channels, and provenance tracking.
    """

    NOMINAL_BASELINE: Dict[str, float] = {
        "Temperature": 35.0,
        "VCCINT": 1.000,
        "VCCAUX": 1.800,
        "VCCBRAM": 1.000,
        "RO_Frequency": _NOM,
        "RO_Delay_ns": 0.2294,
        "RO_R1": _nom("R1"),
        "RO_R1_Delay_ns": 0.2294,
        "RO_R2": _nom("R2"),
        "RO_R2_Delay_ns": 0.2294,
        "RO_R3": _nom("R3"),
        "RO_R3_Delay_ns": 0.2294,
        "RO_R4": _nom("R4"),
        "RO_R4_Delay_ns": 0.2294,
        "Error_Rate": 0.00001
    }

    # Relative diagnostic significance weights of telemetry channels
    CHANNEL_WEIGHTS: Dict[str, float] = {
        "Temperature": 0.30,
        "RO_Frequency": 0.35,
        "Error_Rate": 0.15,
        "VCCINT": 0.08,
        "VCCAUX": 0.06,
        "VCCBRAM": 0.06
    }

    def __init__(self, initial_inputs: Optional[Dict[str, Optional[float]]] = None):
        self.user_inputs: Dict[str, float] = {}
        if initial_inputs:
            self.set_inputs(initial_inputs)

    @staticmethod
    def validate_channel(channel: str, value: Any) -> Tuple[bool, Optional[float], Optional[str], Optional[str]]:
        """
        Validates a single telemetry value against the three-tier validation architecture:
          1. Input Validity (Numeric parsing)
          2. Physical Sensor Validity (Absolute limits)
          3. Operating Range (Operating bounds)
        Returns: (is_valid, parsed_float_or_None, error_message_or_None, warning_message_or_None)
        """
        if value is None or str(value).strip() == "":
            return True, None, None, None

        cfg = SENSOR_CONFIG.get(channel)
        if not cfg:
            return False, None, f"Unknown sensor channel: {channel}", None

        # 1. Input Validity Check
        try:
            val_float = float(value)
        except (ValueError, TypeError):
            return False, None, f"{cfg['display_name']} must be a valid numerical value.", None

        # 2. Physical Sensor Validity Check (Rejection of impossible values)
        phys_min = cfg.get("physical_min", cfg.get("min_valid", -40.0))
        phys_max = cfg.get("physical_max", cfg.get("max_valid", 125.0))
        if not (phys_min <= val_float <= phys_max):
            return False, None, (
                f"{cfg['display_name']} ({val_float} {cfg['unit']}) is outside physical sensor bounds "
                f"[{phys_min}, {phys_max}] {cfg['unit']}."
            ), None

        # 3. Operating Health Range Check (Soft warning, form is permitted to run)
        op_min = cfg.get("operating_min", cfg.get("min_nominal", phys_min))
        op_max = cfg.get("operating_max", cfg.get("max_nominal", phys_max))
        warning_msg = None
        if not (op_min <= val_float <= op_max):
            warning_msg = (
                f"{cfg['display_name']} ({val_float} {cfg['unit']}) is outside expected operating range "
                f"[{op_min}, {op_max}] {cfg['unit']}."
            )

        return True, val_float, None, warning_msg

    def set_inputs(self, raw_inputs: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
        """
        Validates and updates user-supplied telemetry values.
        Returns: (all_valid, list_of_validation_errors, list_of_operating_warnings)
        """
        errors: List[str] = []
        warnings: List[str] = []
        parsed_dict: Dict[str, float] = {}

        for ch in ["Temperature", "VCCINT", "VCCAUX", "VCCBRAM", "RO_Frequency", "Error_Rate"]:
            val = raw_inputs.get(ch)
            is_valid, parsed_val, err_msg, warn_msg = self.validate_channel(ch, val)
            if not is_valid and err_msg:
                errors.append(err_msg)
            elif parsed_val is not None:
                parsed_dict[ch] = parsed_val
                if warn_msg:
                    warnings.append(warn_msg)

        if errors:
            return False, errors, warnings

        self.user_inputs = parsed_dict
        return True, [], warnings

    def get_data(self, window_size: int = 150, sample_idx: Optional[int] = None) -> Tuple[pd.DataFrame, pd.Series, Dict[str, Any]]:
        """
        Synthesizes a complete, feature-engineered telemetry dataset from partial inputs.
        Omitted channels are imputed with verified nominal baselines and labeled as assumed.
        """
        user_provided: List[str] = []
        derived: List[str] = []
        assumed: List[str] = []

        # Temperature
        if "Temperature" in self.user_inputs:
            temp = float(self.user_inputs["Temperature"])
            user_provided.append("Temperature")
        else:
            temp = self.NOMINAL_BASELINE["Temperature"]
            assumed.append("Temperature")

        # Supply rails
        if "VCCINT" in self.user_inputs:
            vccint = float(self.user_inputs["VCCINT"])
            user_provided.append("VCCINT")
        else:
            vccint = self.NOMINAL_BASELINE["VCCINT"]
            assumed.append("VCCINT")

        if "VCCAUX" in self.user_inputs:
            vccaux = float(self.user_inputs["VCCAUX"])
            user_provided.append("VCCAUX")
        else:
            vccaux = self.NOMINAL_BASELINE["VCCAUX"]
            assumed.append("VCCAUX")

        if "VCCBRAM" in self.user_inputs:
            vccbram = float(self.user_inputs["VCCBRAM"])
            user_provided.append("VCCBRAM")
        else:
            vccbram = self.NOMINAL_BASELINE["VCCBRAM"]
            assumed.append("VCCBRAM")

        # Ring Oscillator Frequency & Delay
        if "RO_Frequency" in self.user_inputs:
            ro_freq = float(self.user_inputs["RO_Frequency"])
            ro_delay = calculate_ro_delay_ns(ro_freq, stages=RO_STAGES)
            user_provided.append("RO_Frequency")
            derived.append("RO_Delay_ns")
        else:
            ro_freq = self.NOMINAL_BASELINE["RO_Frequency"]
            ro_delay = self.NOMINAL_BASELINE["RO_Delay_ns"]
            assumed.append("RO_Frequency")
            assumed.append("RO_Delay_ns")

        # Error Rate
        if "Error_Rate" in self.user_inputs:
            err_rate = float(self.user_inputs["Error_Rate"])
            user_provided.append("Error_Rate")
        else:
            err_rate = self.NOMINAL_BASELINE["Error_Rate"]
            assumed.append("Error_Rate")

        # Regional RO derivation from RO_Frequency
        ro_r1 = ro_freq + 0.3
        ro_r2 = ro_freq - 0.2
        ro_r3 = ro_freq + 0.1
        ro_r4 = ro_freq - 0.1

        current_frame = {
            "Timestamp": time.time(),
            "Temperature": round(temp, 4),
            "VCCINT": round(vccint, 4),
            "VCCAUX": round(vccaux, 4),
            "VCCBRAM": round(vccbram, 4),
            "RO_Frequency": round(ro_freq, 4),
            "RO_Delay_ns": round(ro_delay, 4),
            "RO_R1": round(ro_r1, 4),
            "RO_R1_Delay_ns": round(calculate_ro_delay_ns(ro_r1, stages=RO_STAGES), 4),
            "RO_R2": round(ro_r2, 4),
            "RO_R2_Delay_ns": round(calculate_ro_delay_ns(ro_r2, stages=RO_STAGES), 4),
            "RO_R3": round(ro_r3, 4),
            "RO_R3_Delay_ns": round(calculate_ro_delay_ns(ro_r3, stages=RO_STAGES), 4),
            "RO_R4": round(ro_r4, 4),
            "RO_R4_Delay_ns": round(calculate_ro_delay_ns(ro_r4, stages=RO_STAGES), 4),
            "Error_Rate": round(err_rate, 6)
        }

        # Build steady-state rolling buffer of length window_size
        buf_len = max(30, window_size)
        buffer_data = [dict(current_frame) for _ in range(buf_len)]
        raw_df = pd.DataFrame(buffer_data)

        # Feature engineering creates delta and rolling stats smoothly
        engineered_df = create_features(raw_df)

        history_df = engineered_df.tail(window_size).copy()
        latest_sample = engineered_df.iloc[-1].copy()

        # Compute completeness and reliability metrics
        completeness_count = len(user_provided)
        completeness_ratio = round(completeness_count / 6.0, 2)
        reliability_score = round(sum(self.CHANNEL_WEIGHTS.get(c, 0.0) for c in user_provided), 2)

        # Build provenance map
        prov_map = {
            c: ("USER_PROVIDED" if c in user_provided else "ASSUMED_BASELINE")
            for c in ["Temperature", "VCCINT", "VCCAUX", "VCCBRAM", "RO_Frequency", "Error_Rate"]
        }
        prov_map["RO_Delay_ns"] = "DERIVED" if "RO_Frequency" in user_provided else "ASSUMED_BASELINE"
        for r in ["RO_R1", "RO_R2", "RO_R3", "RO_R4"]:
            prov_map[r] = "DERIVED_SPATIAL" if "RO_Frequency" in user_provided else "ASSUMED_BASELINE"
            prov_map[f"{r}_Delay_ns"] = "DERIVED" if "RO_Frequency" in user_provided else "ASSUMED_BASELINE"

        regional_baselines = {}
        for r in ["R1", "R2", "R3", "R4"]:
            ro_k = f"RO_{r}"
            cand = self.NOMINAL_BASELINE.get(ro_k)
            _, chosen_base, _, _ = validate_regional_baseline(r, cand)
            regional_baselines[ro_k] = chosen_base

        eng_assessment = evaluate_engineering_limits(
            current_frame,
            provenance_map=prov_map,
            regional_baselines=regional_baselines
        )

        metadata = {
            "source_type": "ESTIMATED",
            "source_label": "ESTIMATED / USER PROVIDED",
            "total_samples": 1,
            "current_index": 0,
            "baseline": dict(self.NOMINAL_BASELINE),
            "regional_baselines": regional_baselines,
            "completeness_count": completeness_count,
            "completeness_str": f"{completeness_count} / 6",
            "completeness_ratio": completeness_ratio,
            "reliability_score": reliability_score,
            "user_provided": user_provided,
            "derived": derived,
            "assumed": assumed,
            "raw_inputs": dict(self.user_inputs),
            "channel_status": {
                c: ("USER_PROVIDED" if c in user_provided else "ASSUMED_BASELINE")
                for c in ["Temperature", "VCCINT", "VCCAUX", "VCCBRAM", "RO_Frequency", "Error_Rate"]
            },
            "provenance": prov_map,
            "engineering_assessment": eng_assessment.to_dict()
        }

        return history_df, latest_sample, metadata

    def reset(self):
        """Clears all user inputs to initial empty state."""
        self.user_inputs.clear()
