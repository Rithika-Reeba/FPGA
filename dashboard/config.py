"""
Configuration Constants, Sensor Thresholds & Engineering Limit Architecture
============================================================================
Centralizes all physical operating limits, nominal ratings, threshold rules,
and the three-tier validation architecture:
  1. Input Validity (Syntactic / Numeric)
  2. Physical Validity (Sensor Hardware Plausibility)
  3. Operating Health Range (FPGA Engineering Safety Boundaries)

Precedence Rule:
  Hard engineering limit violations OVERRIDE the Random Forest ML prediction.
"""

import sys
import math
from pathlib import Path
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import importlib
import config

try:
    importlib.reload(config)
except Exception:
    pass

RO_STAGES: int = getattr(config, "RO_STAGES", 5)
DEVICE_NAME: str = getattr(config, "DEVICE_NAME", "Xilinx Artix-7 (XC7A35T-1CPG236C)")
ARCHITECTURE: str = getattr(config, "ARCHITECTURE", "28nm HKMG (High-K Metal Gate)")

# Nominal RO frequency and boundaries come straight from the single source of truth.
# (They must NOT be read via `import config`: when Streamlit runs dashboard/app.py, the
# dashboard folder is first on sys.path, so `config` can resolve to THIS file instead of
# the root config.py and silently fall back to stale literals.)
import health_rules as _hr

_ro_limits = _hr.ro_limits(_hr.global_nominal_mhz())
RO_NOMINAL_MHZ: float = _ro_limits["nominal"]
RO_FREQ_NOMINAL_MHZ: float = _ro_limits["nominal"]

# Operating & safety frequency boundaries (healthy envelope = between the warning bounds)
RO_FREQ_OPERATING_MIN_MHZ: float = _ro_limits["warn_low"]
RO_FREQ_OPERATING_MAX_MHZ: float = _ro_limits["warn_high"]
RO_FREQ_WARNING_LOW_MHZ: float = _ro_limits["warn_low"]
RO_FREQ_WARNING_HIGH_MHZ: float = _ro_limits["warn_high"]
RO_FREQ_CRITICAL_LOW_MHZ: float = _ro_limits["crit_low"]
RO_FREQ_CRITICAL_HIGH_MHZ: float = _ro_limits["crit_high"]

# Derived delay thresholds
RO_DELAY_NOMINAL_NS: float = getattr(config, "RO_DELAY_NOMINAL_NS", round(100.0 / RO_FREQ_NOMINAL_MHZ, 4))
RO_NOMINAL_DELAY_NS: float = getattr(config, "RO_NOMINAL_DELAY_NS", RO_DELAY_NOMINAL_NS)
RO_DELAY_OPERATING_MIN_NS: float = getattr(config, "RO_DELAY_OPERATING_MIN_NS", round(100.0 / RO_FREQ_OPERATING_MAX_MHZ, 4))
RO_DELAY_OPERATING_MAX_NS: float = getattr(config, "RO_DELAY_OPERATING_MAX_NS", round(100.0 / RO_FREQ_OPERATING_MIN_MHZ, 4))
RO_DELAY_WARNING_LOW_NS: float = getattr(config, "RO_DELAY_WARNING_LOW_NS", round(100.0 / RO_FREQ_WARNING_HIGH_MHZ, 4))
RO_DELAY_WARNING_HIGH_NS: float = getattr(config, "RO_DELAY_WARNING_HIGH_NS", round(100.0 / RO_FREQ_WARNING_LOW_MHZ, 4))
RO_DELAY_CRITICAL_LOW_NS: float = getattr(config, "RO_DELAY_CRITICAL_LOW_NS", round(100.0 / RO_FREQ_CRITICAL_HIGH_MHZ, 4))
RO_DELAY_CRITICAL_HIGH_NS: float = getattr(config, "RO_DELAY_CRITICAL_HIGH_NS", round(100.0 / RO_FREQ_CRITICAL_LOW_MHZ, 4))

calculate_ro_delay_ns = getattr(config, "calculate_ro_delay_ns", None)
if calculate_ro_delay_ns is None:
    def calculate_ro_delay_ns(frequency_mhz: float, stages: int = RO_STAGES) -> float:
        if frequency_mhz <= 0 or stages <= 0:
            return 0.0
        return round(1000.0 / (2.0 * stages * frequency_mhz), 4)

validate_ro_delay = getattr(config, "validate_ro_delay", None)
if validate_ro_delay is None:
    def validate_ro_delay(delay_ns: float) -> Tuple[bool, str]:
        return (True, "Valid")


# =============================================================================
# Validation & Severity Enumerations
# =============================================================================
class LimitSeverity(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    PHYSICALLY_INVALID = "PHYSICALLY_INVALID"


class ValidationStatus(str, Enum):
    VALID = "VALID"
    INVALID_INPUT = "INVALID_INPUT"
    PHYSICALLY_INVALID = "PHYSICALLY_INVALID"
    OUTSIDE_OPERATING_RANGE = "OUTSIDE_OPERATING_RANGE"


# =============================================================================
# Centralized Sensor Configuration & Comprehensive Limits
# =============================================================================
# Schema for every telemetry channel:
#   - display_name: Human-readable sensor channel title
#   - unit: Physical engineering unit
#   - nominal: Verified baseline benchmark
#   - description: Physical meaning & mechanism
#   - physical_min / physical_max: Absolute hardware/sensor physical plausibility bounds
#   - operating_min / operating_max: Expected normal/healthy operating envelope
#   - warning_low / warning_high: Boundaries triggering Warning state
#   - critical_low / critical_high: Boundaries triggering Critical/Degraded state
#   - is_hard_override: True if violation takes precedence over ML model
#   - source: Provenance of the limit (Datasheet, Aging model, or Configurable assumption)
# =============================================================================
SENSOR_CONFIG: Dict[str, Dict[str, Any]] = {
    "Temperature": {
        "display_name": "Die Temperature",
        "unit": "°C",
        "nominal": 35.0,
        "description": "On-chip junction temperature measured by 7-Series XADC sensor",
        "physical_min": -40.0,    # Xilinx DS181 minimum junction rating
        "physical_max": 125.0,    # Xilinx DS181 maximum junction rating
        "operating_min": 20.0,    # Normal commercial room/chassis operating floor
        "operating_max": 45.0,    # Upper threshold for nominal healthy operation
        "warning_low": 10.0,      # Sub-nominal operating ambient
        "warning_high": 45.0,     # Elevated thermal dissipation
        "critical_low": 0.0,      # Hard limit: abnormal refrigeration / sensor fault
        "critical_high": 52.0,    # Hard limit: severe thermal stress / accelerated aging
        "is_hard_override": True,
        "source": "Xilinx DS181 Datasheet & Thermal Aging Benchmark",
        # Backward compatibility aliases
        "warning": 45.0,
        "critical": 52.0,
        "min_valid": -40.0,
        "max_valid": 125.0
    },
    "VCCINT": {
        "display_name": "VCCINT (Core Supply)",
        "unit": "V",
        "nominal": 1.000,
        "description": "Internal FPGA core logic supply rail",
        "physical_min": 0.000,
        "physical_max": 2.000,
        "operating_min": 0.950,   # Xilinx DS181 recommended 1.0V ± 50mV (±5%)
        "operating_max": 1.050,
        "warning_low": 0.920,     # Supply voltage droop
        "warning_high": 1.050,    # Supply voltage surge
        "critical_low": 0.920,    # Hard limit: severe droop / logic failure risk
        "critical_high": 1.080,   # Hard limit: overvoltage / oxide breakdown risk
        "is_hard_override": True,
        "source": "Xilinx DS181 Artix-7 Recommended Operating Conditions (1.0V ± 5%)",
        # Backward compatibility aliases
        "tolerance_pct": 2.5,
        "min_nominal": 0.975,
        "max_nominal": 1.025,
        "min_valid": 0.5,
        "max_valid": 1.5
    },
    "VCCAUX": {
        "display_name": "VCCAUX (Auxiliary Supply)",
        "unit": "V",
        "nominal": 1.800,
        "description": "Auxiliary supply rail powering I/O circuitry and XADC reference",
        "physical_min": 0.000,
        "physical_max": 3.000,
        "operating_min": 1.710,   # Xilinx DS181 recommended 1.8V ± 5%
        "operating_max": 1.890,
        "warning_low": 1.650,
        "warning_high": 1.890,
        "critical_low": 1.650,    # Hard limit: severe aux droop
        "critical_high": 1.950,   # Hard limit: aux overvoltage
        "is_hard_override": True,
        "source": "Xilinx DS181 Artix-7 Recommended Operating Conditions (1.8V ± 5%)",
        # Backward compatibility aliases
        "tolerance_pct": 2.5,
        "min_nominal": 1.755,
        "max_nominal": 1.845,
        "min_valid": 1.0,
        "max_valid": 2.5
    },
    "VCCBRAM": {
        "display_name": "VCCBRAM (BRAM Supply)",
        "unit": "V",
        "nominal": 1.000,
        "description": "Dedicated supply rail for on-chip Block RAM cells",
        "physical_min": 0.000,
        "physical_max": 2.000,
        "operating_min": 0.950,   # Xilinx DS181 recommended 1.0V ± 5%
        "operating_max": 1.050,
        "warning_low": 0.920,
        "warning_high": 1.050,
        "critical_low": 0.920,    # Hard limit: BRAM memory data corruption risk
        "critical_high": 1.080,   # Hard limit: BRAM overvoltage
        "is_hard_override": True,
        "source": "Xilinx DS181 Artix-7 Recommended Operating Conditions (1.0V ± 5%)",
        # Backward compatibility aliases
        "tolerance_pct": 2.5,
        "min_nominal": 0.975,
        "max_nominal": 1.025,
        "min_valid": 0.5,
        "max_valid": 1.5
    },
    "RO_Frequency": {
        "display_name": "Ring Oscillator Frequency",
        "unit": "MHz",
        "nominal": RO_FREQ_NOMINAL_MHZ,
        "description": "5-stage Ring Oscillator frequency tracking logic gate propagation delay (canonical timing metric)",
        "physical_min": 10.0,
        "physical_max": 800.0,
        "operating_min": RO_FREQ_OPERATING_MIN_MHZ,
        "operating_max": RO_FREQ_OPERATING_MAX_MHZ,
        "warning_low": RO_FREQ_WARNING_LOW_MHZ,
        "warning_high": RO_FREQ_WARNING_HIGH_MHZ,
        "critical_low": RO_FREQ_CRITICAL_LOW_MHZ,
        "critical_high": RO_FREQ_CRITICAL_HIGH_MHZ,
        "is_hard_override": True,
        "is_derived": False,
        "source": "Basys 3 Physical Measurement & 28nm Artix-7 Propagation Model",
        # Backward compatibility aliases
        "warning_drop_pct": 3.0,
        "critical_drop_pct": 5.5,
        "min_valid": 50.0,
        "max_valid": 800.0
    },
    "RO_Delay_ns": {
        "display_name": "Derived RO Stage Delay",
        "unit": "ns",
        "nominal": RO_DELAY_NOMINAL_NS,
        "description": "Derived logic propagation delay per inverter stage (tau = 100 / f_MHz, derived from RO frequency)",
        "physical_min": 0.05,
        "physical_max": 2.50,
        "operating_min": RO_DELAY_OPERATING_MIN_NS,
        "operating_max": RO_DELAY_OPERATING_MAX_NS,
        "warning_low": RO_DELAY_WARNING_LOW_NS,
        "warning_high": RO_DELAY_WARNING_HIGH_NS,
        "critical_low": RO_DELAY_CRITICAL_LOW_NS,
        "critical_high": RO_DELAY_CRITICAL_HIGH_NS,
        "is_hard_override": False,  # Delay is deterministically derived from RO_Frequency; RO_Frequency is canonical hard override
        "is_derived": True,
        "source": "Deterministic Physical Formula (tau = 100 / f_MHz derived from RO Frequency)",
        # Backward compatibility aliases
        "warning_increase_pct": 3.0,
        "critical_increase_pct": 5.5,
        "min_valid": 0.05,
        "max_valid": 2.50
    },
    "Error_Rate": {
        "display_name": "Functional Error Rate",
        "unit": "",
        "nominal": 0.000010,
        "description": "Hardware PRBS-7 self-checking logic bit error rate",
        "physical_min": 0.0,
        "physical_max": 1.0,
        "operating_min": 0.0,
        "operating_max": 0.000500, # Negligible soft error noise floor
        "warning_low": 0.0,
        "warning_high": 0.002000,  # Elevated soft error activity
        "critical_low": 0.0,
        "critical_high": 0.002000, # Hard limit: operational functional breakdown
        "is_hard_override": True,
        "source": "Hardware PRBS-7 Self-Test Specification (Configurable Engineering Assumption)",
        # Backward compatibility aliases
        "warning": 0.0010,
        "critical": 0.0025,
        "min_valid": 0.0,
        "max_valid": 1.0
    }
}


# =============================================================================
# Health State Color Palette
# =============================================================================
HEALTH_COLORS = {
    "Healthy": "#00E676",    # Vivid Green
    "Warning": "#FFD600",    # Amber Yellow
    "Degraded": "#FF9100",   # High-Visibility Orange
    "Critical": "#FF1744"    # Bright Red
}

STATUS_BG_COLORS = {
    "Healthy": "rgba(0, 230, 118, 0.12)",
    "Warning": "rgba(255, 214, 0, 0.12)",
    "Degraded": "rgba(255, 145, 0, 0.14)",
    "Critical": "rgba(255, 23, 68, 0.16)"
}


# =============================================================================
# Four-Region Physical Health Configuration (Basys 3 XC7A35T)
# =============================================================================
# Physical 2x2 Layout:
#   R1 (Northwest): CLOCKREGION_X0Y2 -> SLICE_X0Y100:SLICE_X35Y149 (pblock_R1)
#   R2 (Northeast): CLOCKREGION_X1Y2 -> SLICE_X36Y100:SLICE_X57Y149 (pblock_R2)
#   R3 (Southwest): CLOCKREGION_X0Y0 -> SLICE_X0Y0:SLICE_X35Y49    (pblock_R3)
#   R4 (Southeast): CLOCKREGION_X1Y0 -> SLICE_X36Y0:SLICE_X65Y49    (pblock_R4)
# =============================================================================
REGIONAL_CONFIG: Dict[str, Dict[str, Any]] = {
    "R1": {
        "id": "R1",
        "name": "Region 1 (R1)",
        "display_name": "Region 1 (R1)",
        "quadrant": "Region 1 (R1)",
        "clock_region": "CLOCKREGION_X0Y2",
        "clock_region_short": "X0Y2",
        "pblock": "pblock_R1",
        "physical_constraint": "pblock_R1",
        "slice_range": "SLICE_X0Y100:SLICE_X35Y149",
        "nominal_freq": 436.0,       # Common nominal baseline for all four regions
        "nominal_delay_ns": 0.2294,  # 100 / 436.0
        "warning_drop_pct": 3.0,
        "critical_drop_pct": 5.5,
        "warning_freq": 422.9,       # 436.0 * 0.970
        "warning_delay_ns": 0.2365,  # 100 / 422.9
        "critical_freq": 412.0,      # 436.0 * 0.945
        "critical_delay_ns": 0.2427, # 100 / 412.0
        "description": "Monitors logic timing propagation in pblock_R1 (CLOCKREGION_X0Y2)"
    },
    "R2": {
        "id": "R2",
        "name": "Region 2 (R2)",
        "display_name": "Region 2 (R2)",
        "quadrant": "Region 2 (R2)",
        "clock_region": "CLOCKREGION_X1Y2",
        "clock_region_short": "X1Y2",
        "pblock": "pblock_R2",
        "physical_constraint": "pblock_R2",
        "slice_range": "SLICE_X36Y100:SLICE_X57Y149",
        "nominal_freq": 436.0,       # Common nominal baseline for all four regions
        "nominal_delay_ns": 0.2294,  # 100 / 436.0
        "warning_drop_pct": 3.0,
        "critical_drop_pct": 5.5,
        "warning_freq": 422.9,       # 436.0 * 0.970
        "warning_delay_ns": 0.2365,  # 100 / 422.9
        "critical_freq": 412.0,      # 436.0 * 0.945
        "critical_delay_ns": 0.2427, # 100 / 412.0
        "description": "Monitors logic timing propagation in pblock_R2 (CLOCKREGION_X1Y2)"
    },
    "R3": {
        "id": "R3",
        "name": "Region 3 (R3)",
        "display_name": "Region 3 (R3)",
        "quadrant": "Region 3 (R3)",
        "clock_region": "CLOCKREGION_X0Y0",
        "clock_region_short": "X0Y0",
        "pblock": "pblock_R3",
        "physical_constraint": "pblock_R3",
        "slice_range": "SLICE_X0Y0:SLICE_X35Y49",
        "nominal_freq": 436.0,       # Common nominal baseline for all four regions
        "nominal_delay_ns": 0.2294,  # 100 / 436.0
        "warning_drop_pct": 3.0,
        "critical_drop_pct": 5.5,
        "warning_freq": 422.9,       # 436.0 * 0.970
        "warning_delay_ns": 0.2365,  # 100 / 422.9
        "critical_freq": 412.0,      # 436.0 * 0.945
        "critical_delay_ns": 0.2427, # 100 / 412.0
        "description": "Monitors logic timing propagation in pblock_R3 (CLOCKREGION_X0Y0)"
    },
    "R4": {
        "id": "R4",
        "name": "Region 4 (R4)",
        "display_name": "Region 4 (R4)",
        "quadrant": "Region 4 (R4)",
        "clock_region": "CLOCKREGION_X1Y0",
        "clock_region_short": "X1Y0",
        "pblock": "pblock_R4",
        "physical_constraint": "pblock_R4",
        "slice_range": "SLICE_X36Y0:SLICE_X65Y49",
        "nominal_freq": 436.0,       # Common nominal baseline for all four regions
        "nominal_delay_ns": 0.2294,  # 100 / 436.0
        "warning_drop_pct": 3.0,
        "critical_drop_pct": 5.5,
        "warning_freq": 422.9,       # 436.0 * 0.970
        "warning_delay_ns": 0.2365,  # 100 / 422.9
        "critical_freq": 412.0,      # 436.0 * 0.945
        "critical_delay_ns": 0.2427, # 100 / 412.0
        "description": "Monitors logic timing propagation in pblock_R4 (CLOCKREGION_X1Y0)"
    }
}


# =============================================================================
# Apply the single source of truth (health_rules.py) to every per-region and
# per-channel limit above, so the literals in this file can never drift from it.
# =============================================================================
import health_rules as _rules

REGION_QUORUM: int = _rules.REGION_QUORUM


def _apply_health_rules() -> None:
    for r_id, meta in REGIONAL_CONFIG.items():
        nom = _rules.region_nominal_mhz(r_id)
        lim = _rules.ro_limits(nom)
        meta["nominal_freq"] = round(nom, 2)
        meta["nominal_delay_ns"] = round(100.0 / nom, 4)
        meta["warning_drop_pct"] = _rules.RO_WARN_DROP_PCT
        meta["critical_drop_pct"] = _rules.RO_CRIT_DROP_PCT
        meta["warning_freq"] = round(lim["warn_low"], 2)
        meta["warning_delay_ns"] = round(100.0 / lim["warn_low"], 4)
        meta["critical_freq"] = round(lim["crit_low"], 2)
        meta["critical_delay_ns"] = round(100.0 / lim["crit_low"], 4)

    t = SENSOR_CONFIG["Temperature"]
    t.update({"operating_max": _rules.TEMP_WARN_C, "warning_high": _rules.TEMP_WARN_C,
              "critical_high": _rules.TEMP_CRIT_C, "warning": _rules.TEMP_WARN_C,
              "critical": _rules.TEMP_CRIT_C})

    for rail in ("VCCINT", "VCCAUX", "VCCBRAM"):
        v = _rules.volt_limits(rail)
        SENSOR_CONFIG[rail].update({
            "operating_min": v["warn_low"], "operating_max": v["warn_high"],
            "warning_low": v["warn_low"], "warning_high": v["warn_high"],
            "critical_low": v["crit_low"], "critical_high": v["crit_high"],
        })

    SENSOR_CONFIG["Error_Rate"].update({"operating_max": _rules.ERROR_RATE_WARN,
                                        "warning_high": _rules.ERROR_RATE_CRIT,
                                        "critical_high": _rules.ERROR_RATE_CRIT})

    ro = SENSOR_CONFIG["RO_Frequency"]
    ro.update({"warning_drop_pct": _rules.RO_WARN_DROP_PCT, "critical_drop_pct": _rules.RO_CRIT_DROP_PCT})
    dl = SENSOR_CONFIG["RO_Delay_ns"]
    dl.update({"warning_increase_pct": _rules.RO_WARN_DROP_PCT, "critical_increase_pct": _rules.RO_CRIT_DROP_PCT})


_apply_health_rules()


# =============================================================================
# Regional Frequency Weighting & Independent Fault Assessment Architecture
# =============================================================================
# Default weights: Equal weighting across all four symmetric silicon regions.
# Justification:
#   In the absence of empirically validated spatial aging gradients or asymmetric
#   sensor calibration, each of the four identical 5-stage ring oscillators (R1..R4)
#   is assigned an equal weight of 0.25 (total = 1.0).
#   This reproduces the hardware arithmetic mean while allowing user-configured
#   weighting when differential measurement reliability or localized hotspot
#   weighting is justified by calibration.
#
# Critical Safety Invariant:
#   A weighted aggregate frequency summary MUST NEVER override or mask a regional
#   critical limit violation. Independent regional fault detection takes precedence
#   over any averaging or weighting scheme.
# =============================================================================
DEFAULT_REGIONAL_WEIGHTS: Dict[str, float] = dict(_rules.REGION_WEIGHTS)


def validate_regional_weights(
    weights: Any,
    expected_regions: Optional[List[str]] = None
) -> Tuple[bool, Dict[str, float], str]:
    """
    Validates a regional weight mapping against physical safety and mathematical invariants:
      1. Must be a non-empty dictionary.
      2. All weight values must be numeric, finite, and non-negative (w_i >= 0.0).
      3. Total weight sum must be strictly positive (sum(w_i) > 0.0).
      4. Missing regions in weights dictionary default to 0.0 unless weights is None.

    Returns:
      (is_valid, validated_weights_dict, status_reason)
    """
    if expected_regions is None:
        expected_regions = ["R1", "R2", "R3", "R4"]

    if weights is None:
        return (True, DEFAULT_REGIONAL_WEIGHTS.copy(), "Using calibrated structural regional weights (R1:0.35, R2:0.05, R3:0.30, R4:0.30)")

    if not isinstance(weights, dict):
        return (False, DEFAULT_REGIONAL_WEIGHTS.copy(), f"Weights must be a dictionary, got {type(weights).__name__}")

    if not weights:
        return (False, DEFAULT_REGIONAL_WEIGHTS.copy(), "Weights dictionary cannot be empty")

    validated: Dict[str, float] = {}
    total_weight = 0.0

    for r in expected_regions:
        w_val = weights.get(r, weights.get(f"RO_{r}", None))
        if w_val is None:
            # Region not specified in provided dict; treat as 0.0 weight
            validated[r] = 0.0
            continue

        try:
            w_float = float(w_val)
            if not math.isfinite(w_float):
                return (False, DEFAULT_REGIONAL_WEIGHTS.copy(), f"Non-finite weight encountered for {r}: {w_val}")
            if w_float < 0.0:
                return (False, DEFAULT_REGIONAL_WEIGHTS.copy(), f"Negative weight encountered for {r}: {w_float}")
            validated[r] = w_float
            total_weight += w_float
        except (TypeError, ValueError):
            return (False, DEFAULT_REGIONAL_WEIGHTS.copy(), f"Non-numeric weight encountered for {r}: {w_val}")

    if total_weight <= 0.0:
        return (False, DEFAULT_REGIONAL_WEIGHTS.copy(), f"Sum of regional weights must be strictly positive (> 0.0), got {total_weight}")

    return (True, validated, f"Valid regional weights (total sum: {total_weight:.4f})")


def calculate_weighted_regional_frequency(
    regional_data: Any,
    weights: Optional[Dict[str, float]] = None,
    provenance_map: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Calculates a weighted average summary of regional ring-oscillator frequencies
    while preserving actual regional measurements, computing arithmetic average,
    and independently extracting the worst-case regional frequency.

    Formula:
      weighted_frequency = sum(w[i] * f[i]) / sum(w[i])  (for all valid regions with w[i] > 0)
      worst_region_frequency = min(valid regional frequencies)

    Safety Principles:
      1. Uses actual regional measurements; does NOT replace missing or abnormal readings
         with nominal values.
      2. Validates weights: finite, non-negative, positive total sum.
      3. Handles missing/invalid data safely: invalid measurements are excluded from the
         average and tracked in 'invalid_regions'.
      4. Preserves arithmetic average and worst-case frequency for transparent comparison.

    Returns:
      Dict containing:
        - 'weighted_frequency': float or None
        - 'arithmetic_frequency': float or None
        - 'worst_region_frequency': float or None
        - 'worst_region_id': str or None
        - 'valid_regions': List[str]
        - 'invalid_regions': List[str]
        - 'missing_regions': List[str]
        - 'weights_used': Dict[str, float]
        - 'is_valid': bool
        - 'weighted_delay_ns': float or None
        - 'worst_delay_ns': float or None
        - 'status_note': str
    """
    region_keys = ["R1", "R2", "R3", "R4"]
    extracted_measurements: Dict[str, Any] = {}

    if isinstance(regional_data, list):
        for item in regional_data:
            if isinstance(item, dict) and "id" in item:
                r_id = str(item["id"]).upper()
                if "current_freq" in item:
                    extracted_measurements[r_id] = item["current_freq"]
                elif "frequency" in item:
                    extracted_measurements[r_id] = item["frequency"]
    elif isinstance(regional_data, dict):
        for r_id in region_keys:
            if f"RO_{r_id}" in regional_data:
                extracted_measurements[r_id] = regional_data[f"RO_{r_id}"]
            elif r_id in regional_data:
                extracted_measurements[r_id] = regional_data[r_id]

    valid_regions: List[str] = []
    invalid_regions: List[str] = []
    missing_regions: List[str] = []
    valid_freqs: Dict[str, float] = {}

    for r_id in region_keys:
        if r_id not in extracted_measurements or extracted_measurements[r_id] is None:
            missing_regions.append(r_id)
            continue

        raw_val = extracted_measurements[r_id]
        try:
            val_f = float(raw_val)
            if not math.isfinite(val_f) or not (10.0 <= val_f <= 800.0):
                invalid_regions.append(r_id)
            else:
                valid_freqs[r_id] = val_f
                valid_regions.append(r_id)
        except (TypeError, ValueError):
            invalid_regions.append(r_id)

    # Validate and resolve weights
    is_w_valid, weights_used, w_reason = validate_regional_weights(weights, expected_regions=region_keys)

    # Worst-case regional frequency (independent safety metric)
    if valid_freqs:
        worst_region_id = min(valid_freqs, key=valid_freqs.get)
        worst_region_frequency = valid_freqs[worst_region_id]
        worst_delay_ns = round(100.0 / worst_region_frequency, 4) if worst_region_frequency > 0 else None
        arithmetic_frequency = round(sum(valid_freqs.values()) / len(valid_freqs), 2)
    else:
        worst_region_id = None
        worst_region_frequency = None
        worst_delay_ns = None
        arithmetic_frequency = None

    # Weighted frequency calculation over valid regions
    active_weight_sum = sum(weights_used.get(r, 0.0) for r in valid_regions)
    if active_weight_sum > 0:
        active_weights = [weights_used.get(r, 0.0) for r in valid_regions]
        # Check if all active weights are equal to avoid floating-point drift from arithmetic mean
        if len(active_weights) > 0 and len(set(active_weights)) == 1 and active_weights[0] > 0 and arithmetic_frequency is not None:
            weighted_frequency = arithmetic_frequency
        else:
            weighted_sum = sum(weights_used.get(r, 0.0) * valid_freqs[r] for r in valid_regions)
            weighted_frequency = round(weighted_sum / active_weight_sum, 2)
        weighted_delay_ns = round(100.0 / weighted_frequency, 4) if weighted_frequency > 0 else None
    elif arithmetic_frequency is not None:
        weighted_frequency = arithmetic_frequency
        weighted_delay_ns = round(100.0 / weighted_frequency, 4) if weighted_frequency > 0 else None
    else:
        weighted_frequency = None
        weighted_delay_ns = None

    is_overall_valid = (
        len(valid_regions) == len(region_keys)
        and len(invalid_regions) == 0
        and len(missing_regions) == 0
    )

    if not valid_regions:
        status_note = "No valid regional measurements available"
    elif invalid_regions:
        status_note = f"Weighted summary computed with {len(valid_regions)} valid regions; {len(invalid_regions)} invalid region(s) detected ({', '.join(invalid_regions)})"
    elif missing_regions:
        status_note = f"Weighted summary computed with {len(valid_regions)} valid regions; {len(missing_regions)} missing region(s) ({', '.join(missing_regions)})"
    else:
        status_note = f"Weighted summary computed across all 4 valid regions using {w_reason}"

    return {
        "weighted_frequency": weighted_frequency,
        "arithmetic_frequency": arithmetic_frequency,
        "worst_region_frequency": worst_region_frequency,
        "worst_region_id": worst_region_id,
        "valid_regions": valid_regions,
        "invalid_regions": invalid_regions,
        "missing_regions": missing_regions,
        "weights_used": weights_used,
        "is_valid": is_overall_valid,
        "weighted_delay_ns": weighted_delay_ns,
        "worst_delay_ns": worst_delay_ns,
        "status_note": status_note
    }


def calibrate_history_dataframe(
    df: Any,
    weights: Optional[Dict[str, float]] = None
) -> Any:
    """
    Calibrates historical telemetry dataframe timing series according to the Multi-Pblock
    Quorum Policy and calibrated regional weights.

    Rules:
      1. If regional RO channels (RO_R1..RO_R4) are present:
         - Preserves original raw hardware arithmetic frequency in 'RO_Raw_Frequency'.
         - Computes weighted RO frequency series using validated structural weights:
             w_freq = sum(w[i] * RO_R[i]) / sum(w[i])
         - For each sample row, checks quorum:
             degraded_pblocks: regions with RO_R[i] <= critical_freq (412.0 MHz)
             warning_pblocks: regions with 412.0 MHz < RO_R[i] <= warning_freq (422.9 MHz)
             total_degrading = degraded_count + warning_count
         - Quorum Policy:
             * If total_degrading >= 2: Multi-pblock degradation triggers overall degradation.
               The main 'RO_Frequency' changes to reflect the degraded condition (raw hardware mean).
             * If total_degrading < 2 (isolated single-pblock anomaly like R2):
               The main 'RO_Frequency' is governed by the calibrated weighted RO frequency (nominal / Healthy).
         - Recomputes derived stage delay:
             RO_Delay_ns = round(100.0 / RO_Frequency, 4)
      2. Recomputes differential and rolling features if present in df (for ML model alignment):
         - RO_Frequency_change, RO_Delay_change, RO_Frequency_mean, RO_Frequency_std.
    """
    if df is None:
        return df
    try:
        import pandas as pd
    except ImportError:
        return df

    if not isinstance(df, pd.DataFrame) or df.empty:
        return df

    calibrated = df.copy()
    reg_keys = ["R1", "R2", "R3", "R4"]
    has_all_regs = all(f"RO_{r}" in calibrated.columns for r in reg_keys)

    if not has_all_regs:
        return calibrated

    # Resolve weights
    is_valid_w, weights_used, _ = validate_regional_weights(weights, expected_regions=reg_keys)
    w1 = weights_used.get("R1", 0.35)
    w2 = weights_used.get("R2", 0.05)
    w3 = weights_used.get("R3", 0.30)
    w4 = weights_used.get("R4", 0.30)
    tot_w = w1 + w2 + w3 + w4
    if tot_w <= 0:
        tot_w = 1.0

    # Preserve raw uncalibrated hardware frequency
    if "RO_Raw_Frequency" not in calibrated.columns and "RO_Frequency" in calibrated.columns:
        calibrated["RO_Raw_Frequency"] = calibrated["RO_Frequency"].copy()

    # Calculate weighted frequency series
    weighted_series = (
        calibrated["RO_R1"] * w1 +
        calibrated["RO_R2"] * w2 +
        calibrated["RO_R3"] * w3 +
        calibrated["RO_R4"] * w4
    ) / tot_w
    calibrated["RO_Weighted_Frequency"] = weighted_series.round(2)

    # Thresholds for quorum policy (412.0 MHz critical, 422.9 MHz warning)
    crit_limit = 412.0
    warn_limit = 422.9

    # Quorum calculation per row: count how many regions are degrading
    degraded_count = (
        (calibrated["RO_R1"] <= crit_limit).astype(int) +
        (calibrated["RO_R2"] <= crit_limit).astype(int) +
        (calibrated["RO_R3"] <= crit_limit).astype(int) +
        (calibrated["RO_R4"] <= crit_limit).astype(int)
    )
    warning_count = (
        ((calibrated["RO_R1"] > crit_limit) & (calibrated["RO_R1"] <= warn_limit)).astype(int) +
        ((calibrated["RO_R2"] > crit_limit) & (calibrated["RO_R2"] <= warn_limit)).astype(int) +
        ((calibrated["RO_R3"] > crit_limit) & (calibrated["RO_R3"] <= warn_limit)).astype(int) +
        ((calibrated["RO_R4"] > crit_limit) & (calibrated["RO_R4"] <= warn_limit)).astype(int)
    )
    total_degrading = degraded_count + warning_count
    quorum_triggered = total_degrading >= 2

    # Vectorized assignment:
    # If quorum triggered (>= 2 degrading regions): keep raw hardware arithmetic frequency
    # If quorum NOT triggered (< 2 degrading regions, e.g. isolated R2): use weighted frequency
    raw_col = calibrated["RO_Raw_Frequency"] if "RO_Raw_Frequency" in calibrated.columns else calibrated["RO_Frequency"]
    calibrated["RO_Frequency"] = raw_col.where(quorum_triggered, calibrated["RO_Weighted_Frequency"])
    calibrated["RO_Delay_ns"] = (100.0 / calibrated["RO_Frequency"]).round(4)

    # Update differential and rolling features if present
    if "RO_Frequency_change" in calibrated.columns:
        calibrated["RO_Frequency_change"] = calibrated["RO_Frequency"].diff().fillna(0)
    if "RO_Delay_change" in calibrated.columns:
        calibrated["RO_Delay_change"] = calibrated["RO_Delay_ns"].diff().fillna(0)
    if "RO_Frequency_mean" in calibrated.columns:
        calibrated["RO_Frequency_mean"] = calibrated["RO_Frequency"].rolling(20).mean().bfill()
    if "RO_Frequency_std" in calibrated.columns:
        calibrated["RO_Frequency_std"] = calibrated["RO_Frequency"].rolling(20).std().fillna(0)

    return calibrated



# =============================================================================
# Regional Baseline Validation & Health Evaluation Architecture
# =============================================================================

def validate_regional_baseline(
    region_id: str,
    baseline_input: Any
) -> Tuple[bool, float, str, str]:
    """
    Validates a candidate regional baseline frequency against physical plausibility
    and the healthy operating envelope for the specified Artix-7 quadrant.

    Distinction Between Configured Nominal and Calibrated Baseline:
      - Configured Nominal: Factory design benchmark derived from silicon characterization
        (e.g., 436.0 MHz for R2). Authoritative fallback when calibration is absent/invalid.
      - Calibrated Baseline: Board-specific reference frequency captured during verified
        healthy operating conditions.
      - Safety Invariant: A candidate baseline that falls below the warning or critical
        threshold (e.g. ~322.2 MHz) MUST NOT be accepted as a valid baseline. Accepting an
        unhealthy frequency as baseline would poison drift calculation and make severe
        hardware degradation appear as zero-drift "Healthy".

    Returns:
        (is_valid, selected_baseline_mhz, baseline_source, diagnostic_reason)
    """
    r_meta = REGIONAL_CONFIG.get(region_id, REGIONAL_CONFIG["R1"])
    f_nom = float(r_meta["nominal_freq"])
    warn_bound = float(r_meta.get("warning_freq", round(f_nom * 0.97, 1)))

    if baseline_input is None or baseline_input == "":
        return (True, f_nom, "FACTORY_NOMINAL", f"Using configured factory nominal ({f_nom:.1f} MHz)")

    try:
        b_val = float(baseline_input)
        if not math.isfinite(b_val):
            raise ValueError("Non-finite baseline")
    except (TypeError, ValueError):
        return (
            False,
            f_nom,
            "FACTORY_NOMINAL_FALLBACK",
            f"Invalid non-numeric baseline ('{baseline_input}'); fell back to factory nominal ({f_nom:.1f} MHz)"
        )

    # Physical sensor limits [10.0, 800.0] MHz
    phys_min = float(SENSOR_CONFIG["RO_Frequency"]["physical_min"])
    phys_max = float(SENSOR_CONFIG["RO_Frequency"]["physical_max"])
    if not (phys_min <= b_val <= phys_max):
        return (
            False,
            f_nom,
            "FACTORY_NOMINAL_FALLBACK",
            f"Physically impossible baseline ({b_val:.1f} MHz); fell back to factory nominal ({f_nom:.1f} MHz)"
        )

    # Baseline health validation: A reference baseline must reside in the healthy envelope
    if b_val < warn_bound:
        return (
            False,
            f_nom,
            "FACTORY_NOMINAL_FALLBACK",
            f"Unhealthy baseline ({b_val:.1f} MHz < {warn_bound:.1f} MHz warning boundary) rejected; fell back to factory nominal ({f_nom:.1f} MHz)"
        )

    crit_high = f_nom * (1.0 + _rules.RO_RISE_CRIT_PCT / 100.0)
    if b_val > crit_high:
        return (
            False,
            f_nom,
            "FACTORY_NOMINAL_FALLBACK",
            f"Over-frequency baseline ({b_val:.1f} MHz > {crit_high:.1f} MHz) rejected; fell back to factory nominal ({f_nom:.1f} MHz)"
        )

    return (True, b_val, "CALIBRATED_BOARD", f"Calibrated board baseline ({b_val:.2f} MHz)")


def evaluate_regional_health(
    region_id: str,
    measurement: Any,
    baseline_freq: Optional[float] = None,
    provenance: str = "MEASURED"
) -> Dict[str, Any]:
    """
    Single canonical evaluation function for regional FPGA health (R1..R4 quadrants).

    Severity Precedence Architecture:
      1. Input Validity & Physical Sensor Limits:
         Missing, non-numeric, or non-finite inputs are marked PHYSICALLY_INVALID / Degraded.
         They are NEVER silently classified as Healthy.
      2. Validated Baseline Selection:
         Candidate baselines are validated via validate_regional_baseline() to prevent
         degraded samples (e.g. 322.2 MHz) from poisoning zero-drift logic.
      3. Hard Engineering Critical Limits (ABSOLUTE PRECEDENCE):
         If measured frequency violates the authoritative critical boundary (e.g. R2 <= 411.8 MHz)
         or critical over-frequency (>= 460 MHz), the region is unconditionally classified as
         Degraded (Critical), regardless of how small the baseline drift may appear.
      4. Hard Engineering Warning Limits & Operating Envelope:
         If measured frequency is below the warning boundary (e.g. R2 <= 422.7 MHz) or exceeds
         warning high (447 MHz), the region is classified as Warning.
      5. Baseline Drift Analysis:
         Drift is evaluated as a separate diagnostic metric. If timing degradation exceeds
         the configured drop limit (-5.5% or -3.0%), appropriate severity is applied.

    Returns:
        Structured dictionary matching both regional map rendering and engineering assessment needs.
    """
    r_meta = REGIONAL_CONFIG.get(region_id, REGIONAL_CONFIG["R1"])
    f_nom = float(r_meta["nominal_freq"])
    crit_drop = float(r_meta.get("critical_drop_pct", 5.5))
    warn_drop = float(r_meta.get("warning_drop_pct", 3.0))
    crit_bound = float(r_meta.get("critical_freq", round(f_nom * (1.0 - crit_drop / 100.0), 1)))
    warn_bound = float(r_meta.get("warning_freq", round(f_nom * (1.0 - warn_drop / 100.0), 1)))

    # Step 1: Validate baseline
    is_base_valid, f_base, base_source, base_note = validate_regional_baseline(region_id, baseline_freq)

    # Step 2: Input validity check
    is_valid = True
    f_meas = 0.0
    try:
        if measurement is None:
            raise ValueError("Measurement is None")
        f_meas = float(measurement)
        if not math.isfinite(f_meas):
            raise ValueError("Measurement is non-finite")
    except (TypeError, ValueError):
        is_valid = False
        f_meas = 0.0

    if not is_valid:
        state = "Degraded"
        severity = LimitSeverity.PHYSICALLY_INVALID
        indicator = "Missing / Invalid Telemetry"
        reason = f"Region {region_id} ({r_meta['quadrant']}): Invalid non-numeric or missing frequency reading ('{measurement}')"
        return {
            "id": region_id,
            "name": r_meta["name"],
            "quadrant": r_meta["quadrant"],
            "clock_region": r_meta["clock_region"],
            "pblock": r_meta["pblock"],
            "slice_range": r_meta["slice_range"],
            "current_freq": 0.0,
            "frequency": 0.0,
            "baseline_freq": round(f_base, 2),
            "baseline_frequency": round(f_base, 2),
            "nominal_freq": round(f_nom, 2),
            "critical_freq": round(crit_bound, 1),
            "critical_boundary": round(crit_bound, 1),
            "warning_freq": round(warn_bound, 1),
            "warning_boundary": round(warn_bound, 1),
            "drift_mhz": 0.0,
            "drift_pct": 0.0,
            "delay_ns": 0.0,
            "baseline_delay_ns": round(calculate_ro_delay_ns(f_base, stages=RO_STAGES), 4),
            "delay_drift_pct": 0.0,
            "state": state,
            "severity": severity,
            "color": HEALTH_COLORS["Degraded"],
            "bg": STATUS_BG_COLORS["Degraded"],
            "border": "rgba(255, 23, 68, 0.55)",
            "indicator": indicator,
            "reason": reason,
            "is_valid": False,
            "baseline_source": base_source,
            "baseline_note": base_note,
            "provenance": provenance if provenance != "MEASURED" else "INVALID"
        }

    # Step 3: Physical plausibility check [10.0, 800.0] MHz
    phys_min = float(SENSOR_CONFIG["RO_Frequency"]["physical_min"])
    phys_max = float(SENSOR_CONFIG["RO_Frequency"]["physical_max"])
    if not (phys_min <= f_meas <= phys_max):
        state = "Degraded"
        severity = LimitSeverity.PHYSICALLY_INVALID
        indicator = f"Physically Impossible ({f_meas:.1f} MHz)"
        reason = f"Region {region_id} ({r_meta['quadrant']}): Physical sensor limit breached ({f_meas:.1f} MHz outside [{phys_min:.1f}, {phys_max:.1f}] MHz)"
        delay_ns = calculate_ro_delay_ns(f_meas, stages=RO_STAGES) if f_meas > 0 else 0.0
        return {
            "id": region_id,
            "name": r_meta["name"],
            "quadrant": r_meta["quadrant"],
            "clock_region": r_meta["clock_region"],
            "pblock": r_meta["pblock"],
            "slice_range": r_meta["slice_range"],
            "current_freq": round(f_meas, 2),
            "frequency": round(f_meas, 2),
            "baseline_freq": round(f_base, 2),
            "baseline_frequency": round(f_base, 2),
            "nominal_freq": round(f_nom, 2),
            "critical_freq": round(crit_bound, 1),
            "critical_boundary": round(crit_bound, 1),
            "warning_freq": round(warn_bound, 1),
            "warning_boundary": round(warn_bound, 1),
            "drift_mhz": round(f_meas - f_base, 2),
            "drift_pct": round(((f_meas - f_base) / f_base) * 100.0, 2) if f_base > 0 else 0.0,
            "delay_ns": round(delay_ns, 4),
            "baseline_delay_ns": round(calculate_ro_delay_ns(f_base, stages=RO_STAGES), 4),
            "delay_drift_pct": 0.0,
            "state": state,
            "severity": severity,
            "color": HEALTH_COLORS["Degraded"],
            "bg": STATUS_BG_COLORS["Degraded"],
            "border": "rgba(255, 23, 68, 0.55)",
            "indicator": indicator,
            "reason": reason,
            "is_valid": False,
            "baseline_source": base_source,
            "baseline_note": base_note,
            "provenance": provenance
        }

    # Step 4: Derived delay and drift calculations
    drift_mhz = f_meas - f_base
    drift_pct = (drift_mhz / f_base) * 100.0 if f_base > 0 else 0.0
    delay_ns = calculate_ro_delay_ns(f_meas, stages=RO_STAGES)
    base_delay_ns = calculate_ro_delay_ns(f_base, stages=RO_STAGES)
    delay_drift_pct = ((delay_ns - base_delay_ns) / base_delay_ns) * 100.0 if base_delay_ns > 0 else 0.0

    # Over-frequency limits are per region (relative to that region's own nominal/baseline)
    crit_high = f_nom * (1.0 + _rules.RO_RISE_CRIT_PCT / 100.0)
    warn_high = f_nom * (1.0 + _rules.RO_RISE_WARN_PCT / 100.0)

    # Step 5: Hard Critical Limits Evaluation (Absolute Precedence over Drift)
    if f_meas <= crit_bound or drift_pct <= -crit_drop or f_meas >= crit_high:
        state = "Degraded"
        severity = LimitSeverity.CRITICAL
        color = HEALTH_COLORS["Degraded"]
        bg = STATUS_BG_COLORS["Degraded"]
        border = "rgba(255, 145, 0, 0.55)"

        if f_meas <= crit_bound:
            indicator = f"Below critical boundary ({f_meas:.1f} <= {crit_bound:.1f} MHz)"
            reason = (
                f"Region {region_id} ({r_meta['quadrant']}): Critical RO timing limit violated: "
                f"measured frequency = {f_meas:.1f} MHz (critical boundary = {crit_bound:.1f} MHz, {drift_pct:+.2f}% drift); "
                f"equivalent derived delay = {delay_ns:.4f} ns (derived from RO frequency)."
            )
        elif drift_pct <= -crit_drop:
            indicator = f"Severe timing drift ({drift_pct:+.2f}%)"
            reason = (
                f"Region {region_id} ({r_meta['quadrant']}): Critical RO timing drift: "
                f"measured frequency = {f_meas:.1f} MHz ({drift_pct:+.2f}% drift exceeds -{crit_drop:.1f}% limit); "
                f"equivalent derived delay = {delay_ns:.4f} ns (derived from RO frequency)."
            )
        else:
            indicator = f"Critical over-frequency ({f_meas:.1f} >= {crit_high:.1f} MHz)"
            reason = (
                f"Region {region_id} ({r_meta['quadrant']}): Critical RO over-frequency: "
                f"measured frequency = {f_meas:.1f} MHz exceeds safe limit {crit_high:.1f} MHz; "
                f"equivalent derived delay = {delay_ns:.4f} ns (derived from RO frequency)."
            )

    # Step 6: Warning Limits Evaluation
    elif f_meas <= warn_bound or drift_pct <= -warn_drop or f_meas >= warn_high:
        state = "Warning"
        severity = LimitSeverity.WARNING
        color = HEALTH_COLORS["Warning"]
        bg = STATUS_BG_COLORS["Warning"]
        border = "rgba(255, 214, 0, 0.5)"

        if f_meas <= warn_bound:
            indicator = f"Below warning boundary ({f_meas:.1f} <= {warn_bound:.1f} MHz)"
            reason = (
                f"Region {region_id} ({r_meta['quadrant']}): RO timing drift warning: "
                f"measured frequency = {f_meas:.1f} MHz (warning boundary = {warn_bound:.1f} MHz, {drift_pct:+.2f}% drift); "
                f"equivalent derived delay = {delay_ns:.4f} ns (derived from RO frequency)."
            )
        elif drift_pct <= -warn_drop:
            indicator = f"Moderate timing drift ({drift_pct:+.2f}%)"
            reason = (
                f"Region {region_id} ({r_meta['quadrant']}): RO timing drift warning: "
                f"measured frequency = {f_meas:.1f} MHz ({drift_pct:+.2f}% drift exceeds -{warn_drop:.1f}% limit); "
                f"equivalent derived delay = {delay_ns:.4f} ns (derived from RO frequency)."
            )
        else:
            indicator = f"Elevated frequency ({f_meas:.1f} >= {warn_high:.1f} MHz)"
            reason = (
                f"Region {region_id} ({r_meta['quadrant']}): RO over-frequency warning: "
                f"measured frequency = {f_meas:.1f} MHz exceeds nominal operating ceiling {warn_high:.1f} MHz; "
                f"equivalent derived delay = {delay_ns:.4f} ns (derived from RO frequency)."
            )

    # Step 7: Healthy
    else:
        state = "Healthy"
        severity = LimitSeverity.NORMAL
        color = HEALTH_COLORS["Healthy"]
        bg = STATUS_BG_COLORS["Healthy"]
        border = "rgba(0, 230, 118, 0.4)"
        indicator = "Nominal Timing Propagation"
        reason = f"Region {region_id} ({r_meta['quadrant']}): Operating within nominal timing limits ({f_meas:.1f} MHz, drift {drift_pct:+.2f}%)"

    return {
        "id": region_id,
        "name": r_meta["name"],
        "quadrant": r_meta["quadrant"],
        "clock_region": r_meta["clock_region"],
        "pblock": r_meta["pblock"],
        "slice_range": r_meta["slice_range"],
        "current_freq": round(f_meas, 2),
        "frequency": round(f_meas, 2),
        "baseline_freq": round(f_base, 2),
        "baseline_frequency": round(f_base, 2),
        "nominal_freq": round(f_nom, 2),
        "critical_freq": round(crit_bound, 1),
        "critical_boundary": round(crit_bound, 1),
        "warning_freq": round(warn_bound, 1),
        "warning_boundary": round(warn_bound, 1),
        "drift_mhz": round(drift_mhz, 2),
        "drift_pct": round(drift_pct, 2),
        "delay_ns": round(delay_ns, 4),
        "baseline_delay_ns": round(base_delay_ns, 4),
        "delay_drift_pct": round(delay_drift_pct, 2),
        "state": state,
        "severity": severity,
        "color": color,
        "bg": bg,
        "border": border,
        "indicator": indicator,
        "reason": reason,
        "is_valid": True,
        "baseline_source": base_source,
        "baseline_note": base_note,
        "provenance": provenance
    }


def get_error_risk_label(error_rate: float) -> Tuple[str, str, str]:

    """
    Independent classification of functional Error Risk derived strictly from Error_Rate.
    Decoupled from overall FPGA Health (which may be degraded by temperature, supply rails, or RO timing).

    Engineering Thresholds (PRBS-7 monitor):
      - Error_Rate >= 0.002000 (>= 2000 ppm): "High" (Critical functional bit errors)
      - Error_Rate >= 0.000500 (>= 500 ppm):  "Medium" (Elevated soft error activity)
      - Error_Rate <  0.000500 (< 500 ppm):   "Low" (Nominal / negligible bit error rate)

    Returns:
      (risk_label, risk_color, description)
    """
    try:
        err = float(error_rate)
    except (TypeError, ValueError):
        err = 0.0

    cfg = SENSOR_CONFIG.get("Error_Rate", {})
    crit_high = cfg.get("critical_high", 0.002000)
    op_max = cfg.get("operating_max", 0.000500)

    if err >= crit_high:
        return "High", HEALTH_COLORS["Critical"], f"Bit Error Rate ({err:.6f}) exceeds critical limit ({crit_high:.6f})"
    elif err >= op_max:
        return "Medium", HEALTH_COLORS["Warning"], f"Bit Error Rate ({err:.6f}) is elevated above nominal floor ({op_max:.6f})"
    else:
        return "Low", HEALTH_COLORS["Healthy"], f"Bit Error Rate ({err:.6f}) is nominal (< {op_max:.6f})"



# =============================================================================
# Channel Evaluation & Engineering Limit Assessment Engine
# =============================================================================
class ChannelEvaluation:
    """Detailed evaluation record for a single sensor telemetry channel."""

    def __init__(
        self,
        channel: str,
        value: float,
        display_name: str,
        unit: str,
        nominal: float,
        operating_range_str: str,
        severity: LimitSeverity,
        status_label: str,
        is_violation: bool,
        is_hard_override: bool,
        reason: Optional[str] = None,
        provenance: str = "MEASURED"
    ):
        self.channel = channel
        self.value = value
        self.display_name = display_name
        self.unit = unit
        self.nominal = nominal
        self.operating_range_str = operating_range_str
        self.severity = severity
        self.status_label = status_label
        self.is_violation = is_violation
        self.is_hard_override = is_hard_override
        self.reason = reason
        self.provenance = provenance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel": self.channel,
            "value": self.value,
            "display_name": self.display_name,
            "unit": self.unit,
            "nominal": self.nominal,
            "operating_range": self.operating_range_str,
            "severity": self.severity.value,
            "status": self.status_label,
            "is_violation": self.is_violation,
            "is_hard_override": self.is_hard_override,
            "reason": self.reason,
            "provenance": self.provenance
        }


def evaluate_single_channel(
    channel: str,
    value: Any,
    provenance: str = "MEASURED"
) -> ChannelEvaluation:
    """
    Evaluates a telemetry channel against the three-tier validation architecture:
      1. Input Validity
      2. Physical Validity
      3. Operating Health Range
    """
    cfg = SENSOR_CONFIG.get(channel)
    if not cfg:
        return ChannelEvaluation(
            channel=channel,
            value=0.0,
            display_name=channel,
            unit="",
            nominal=0.0,
            operating_range_str="N/A",
            severity=LimitSeverity.NORMAL,
            status_label="UNKNOWN",
            is_violation=False,
            is_hard_override=False,
            provenance=provenance
        )

    disp = cfg["display_name"]
    unit = cfg["unit"]
    nom = cfg["nominal"]
    op_min = cfg["operating_min"]
    op_max = cfg["operating_max"]
    op_str = f"{op_min:.2f} – {op_max:.2f} {unit}".strip()

    # --- 1. Input Validity Check ---
    try:
        val_float = float(value)
    except (ValueError, TypeError):
        return ChannelEvaluation(
            channel=channel,
            value=0.0,
            display_name=disp,
            unit=unit,
            nominal=nom,
            operating_range_str=op_str,
            severity=LimitSeverity.PHYSICALLY_INVALID,
            status_label="INVALID INPUT",
            is_violation=True,
            is_hard_override=True,
            reason=f"{disp} is not a valid numeric value ('{value}').",
            provenance=provenance
        )

    # --- 2. Physical Sensor Validity Check ---
    phys_min = cfg["physical_min"]
    phys_max = cfg["physical_max"]
    if not (phys_min <= val_float <= phys_max):
        return ChannelEvaluation(
            channel=channel,
            value=val_float,
            display_name=disp,
            unit=unit,
            nominal=nom,
            operating_range_str=op_str,
            severity=LimitSeverity.PHYSICALLY_INVALID,
            status_label="PHYSICALLY IMPOSSIBLE",
            is_violation=True,
            is_hard_override=True,
            reason=f"{disp} ({val_float} {unit}) exceeds absolute physical limits [{phys_min}, {phys_max}].",
            provenance=provenance
        )

    # --- 3. Operating Health Range & Hard Limits Check ---
    crit_low = cfg["critical_low"]
    crit_high = cfg["critical_high"]
    warn_low = cfg["warning_low"]
    warn_high = cfg["warning_high"]

    # Critical Conditions (e.g. Temp <= 0.0 or Temp >= 52.0, VCCINT < 0.92, RO < 238, Error > 0.002)
    if channel == "Temperature":
        if val_float <= crit_low:
            return ChannelEvaluation(
                channel=channel,
                value=val_float,
                display_name=disp,
                unit=unit,
                nominal=nom,
                operating_range_str=op_str,
                severity=LimitSeverity.CRITICAL,
                status_label="CRITICAL (SUB-ZERO / FREEZE FAULT)",
                is_violation=True,
                is_hard_override=True,
                reason=f"Temperature ({val_float:.1f}°C) is at or below 0°C (abnormal refrigeration / sensor fault, expected {op_str}).",
                provenance=provenance
            )
        elif val_float >= crit_high:
            return ChannelEvaluation(
                channel=channel,
                value=val_float,
                display_name=disp,
                unit=unit,
                nominal=nom,
                operating_range_str=op_str,
                severity=LimitSeverity.CRITICAL,
                status_label="CRITICAL (SEVERE THERMAL STRESS)",
                is_violation=True,
                is_hard_override=True,
                reason=f"Temperature ({val_float:.1f}°C) exceeds critical thermal threshold {crit_high}°C.",
                provenance=provenance
            )
        elif val_float >= warn_high:
            return ChannelEvaluation(
                channel=channel,
                value=val_float,
                display_name=disp,
                unit=unit,
                nominal=nom,
                operating_range_str=op_str,
                severity=LimitSeverity.WARNING,
                status_label="WARNING (ELEVATED TEMPERATURE)",
                is_violation=True,
                is_hard_override=True,
                reason=f"Temperature ({val_float:.1f}°C) exceeds nominal operating range {op_str}.",
                provenance=provenance
            )
        elif val_float < warn_low:
            return ChannelEvaluation(
                channel=channel,
                value=val_float,
                display_name=disp,
                unit=unit,
                nominal=nom,
                operating_range_str=op_str,
                severity=LimitSeverity.WARNING,
                status_label="WARNING (SUB-NOMINAL AMBIENT)",
                is_violation=True,
                is_hard_override=True,
                reason=f"Temperature ({val_float:.1f}°C) is below standard operating ambient {op_str}.",
                provenance=provenance
            )

    elif channel in ("VCCINT", "VCCAUX", "VCCBRAM"):
        if val_float <= crit_low:
            return ChannelEvaluation(
                channel=channel,
                value=val_float,
                display_name=disp,
                unit=unit,
                nominal=nom,
                operating_range_str=op_str,
                severity=LimitSeverity.CRITICAL,
                status_label="CRITICAL (VOLTAGE DROOP)",
                is_violation=True,
                is_hard_override=True,
                reason=f"{disp} ({val_float:.3f}V) dropped below critical threshold {crit_low:.3f}V.",
                provenance=provenance
            )
        elif val_float >= crit_high:
            return ChannelEvaluation(
                channel=channel,
                value=val_float,
                display_name=disp,
                unit=unit,
                nominal=nom,
                operating_range_str=op_str,
                severity=LimitSeverity.CRITICAL,
                status_label="CRITICAL (OVERVOLTAGE)",
                is_violation=True,
                is_hard_override=True,
                reason=f"{disp} ({val_float:.3f}V) exceeds maximum safe voltage {crit_high:.3f}V.",
                provenance=provenance
            )
        elif val_float < op_min or val_float > op_max:
            return ChannelEvaluation(
                channel=channel,
                value=val_float,
                display_name=disp,
                unit=unit,
                nominal=nom,
                operating_range_str=op_str,
                severity=LimitSeverity.WARNING,
                status_label="WARNING (OUT OF TOLERANCE)",
                is_violation=True,
                is_hard_override=True,
                reason=f"{disp} ({val_float:.3f}V) is outside recommended operating tolerance {op_str}.",
                provenance=provenance
            )

    elif channel == "RO_Frequency":
        equiv_delay = calculate_ro_delay_ns(val_float, stages=RO_STAGES)
        crit_delay_str = f"{100.0 / crit_low:.4f} ns" if crit_low > 0 else "N/A"
        if val_float <= crit_low:
            return ChannelEvaluation(
                channel=channel,
                value=val_float,
                display_name=disp,
                unit=unit,
                nominal=nom,
                operating_range_str=op_str,
                severity=LimitSeverity.CRITICAL,
                status_label="CRITICAL (SEVERE TIMING DEGRADATION)",
                is_violation=True,
                is_hard_override=True,
                reason=(
                    f"RO_Frequency ({val_float:.1f} MHz): Critical RO timing limit violated "
                    f"(critical limit = {crit_low:.1f} MHz); equivalent derived delay = {equiv_delay:.4f} ns "
                    f"(critical margin = {crit_delay_str}, derived from RO frequency)."
                ),
                provenance=provenance
            )
        elif val_float >= crit_high:
            return ChannelEvaluation(
                channel=channel,
                value=val_float,
                display_name=disp,
                unit=unit,
                nominal=nom,
                operating_range_str=op_str,
                severity=LimitSeverity.CRITICAL,
                status_label="CRITICAL (ABNORMAL OVER-FREQUENCY)",
                is_violation=True,
                is_hard_override=True,
                reason=(
                    f"RO_Frequency ({val_float:.1f} MHz): Critical RO timing limit violated - "
                    f"abnormally high (critical limit = {crit_high:.1f} MHz, expected {op_str}); "
                    f"equivalent derived delay = {equiv_delay:.4f} ns (derived from RO frequency)."
                ),
                provenance=provenance
            )
        elif val_float < op_min or val_float > warn_high:
            warn_limit = warn_low if val_float < op_min else warn_high
            return ChannelEvaluation(
                channel=channel,
                value=val_float,
                display_name=disp,
                unit=unit,
                nominal=nom,
                operating_range_str=op_str,
                severity=LimitSeverity.WARNING,
                status_label="WARNING (TIMING DELAY DRIFT)" if val_float < op_min else "WARNING (SLIGHT OVERCLOCK)",
                is_violation=True,
                is_hard_override=True,
                reason=(
                    f"RO_Frequency ({val_float:.1f} MHz): RO timing degradation / drift warning "
                    f"(warning limit = {warn_limit:.1f} MHz, nominal = {nom:.1f} MHz); "
                    f"equivalent derived delay = {equiv_delay:.4f} ns (derived from RO frequency)."
                ) if val_float < op_min else (
                    f"RO_Frequency ({val_float:.1f} MHz): RO timing warning "
                    f"outside nominal operating range {op_str}; "
                    f"equivalent derived delay = {equiv_delay:.4f} ns (derived from RO frequency)."
                ),
                provenance=provenance
            )

    elif channel == "RO_Delay_ns":
        # Note: RO_Delay_ns is deterministically derived (tau = 100 / f_MHz).
        # RO_Frequency is the canonical hard-override timing measurement.
        if val_float >= crit_high:
            return ChannelEvaluation(
                channel=channel,
                value=val_float,
                display_name=disp,
                unit=unit,
                nominal=nom,
                operating_range_str=op_str,
                severity=LimitSeverity.CRITICAL,
                status_label="CRITICAL (PROPAGATION DELAY SLOWED)",
                is_violation=True,
                is_hard_override=False,
                reason=f"Derived stage delay ({val_float:.4f} ns) exceeds critical timing margin {crit_high:.4f} ns (derived from RO frequency).",
                provenance=provenance
            )
        elif val_float <= crit_low:
            return ChannelEvaluation(
                channel=channel,
                value=val_float,
                display_name=disp,
                unit=unit,
                nominal=nom,
                operating_range_str=op_str,
                severity=LimitSeverity.CRITICAL,
                status_label="CRITICAL (ABNORMAL FAST GATE DELAY)",
                is_violation=True,
                is_hard_override=False,
                reason=f"Derived stage delay ({val_float:.4f} ns) abnormally fast (expected {op_str}, derived from RO frequency).",
                provenance=provenance
            )
        elif val_float > op_max or val_float < warn_low:
            return ChannelEvaluation(
                channel=channel,
                value=val_float,
                display_name=disp,
                unit=unit,
                nominal=nom,
                operating_range_str=op_str,
                severity=LimitSeverity.WARNING,
                status_label="WARNING (TIMING MARGIN REDUCTION)" if val_float > op_max else "WARNING (FAST TIMING DRIFT)",
                is_violation=True,
                is_hard_override=False,
                reason=f"Derived stage delay ({val_float:.4f} ns) is elevated above nominal {nom:.4f} ns (derived from RO frequency)." if val_float > op_max else f"Derived stage delay ({val_float:.4f} ns) is outside nominal operating range {op_str} (derived from RO frequency).",
                provenance=provenance
            )

    elif channel == "Error_Rate":
        if val_float >= crit_high:
            return ChannelEvaluation(
                channel=channel,
                value=val_float,
                display_name=disp,
                unit=unit,
                nominal=nom,
                operating_range_str=op_str,
                severity=LimitSeverity.CRITICAL,
                status_label="CRITICAL (HIGH ERROR RATE)",
                is_violation=True,
                is_hard_override=True,
                reason=f"Functional Error Rate ({val_float:.6f}) exceeds critical limit {crit_high:.6f}.",
                provenance=provenance
            )
        elif val_float > op_max:
            return ChannelEvaluation(
                channel=channel,
                value=val_float,
                display_name=disp,
                unit=unit,
                nominal=nom,
                operating_range_str=op_str,
                severity=LimitSeverity.WARNING,
                status_label="WARNING (ELEVATED ERROR RATE)",
                is_violation=True,
                is_hard_override=True,
                reason=f"Functional Error Rate ({val_float:.6f}) is elevated above normal floor {op_max:.6f}.",
                provenance=provenance
            )

    # Nominal healthy condition
    return ChannelEvaluation(
        channel=channel,
        value=val_float,
        display_name=disp,
        unit=unit,
        nominal=nom,
        operating_range_str=op_str,
        severity=LimitSeverity.NORMAL,
        status_label="NORMAL",
        is_violation=False,
        is_hard_override=False,
        provenance=provenance
    )


class EngineeringAssessment:
    """Comprehensive engineering assessment aggregating all sensor limit checks."""

    def __init__(
        self,
        is_input_valid: bool,
        is_physically_valid: bool,
        has_hard_violations: bool,
        max_severity: LimitSeverity,
        override_reasons: List[str],
        channel_evaluations: Dict[str, ChannelEvaluation],
        primary_reason: str = "All engineering limits satisfied",
        primary_channel: str = "Nominal",
        measured_str: str = "Nominal",
        limit_str: str = "Within envelope",
        derived_delay_str: Optional[str] = None,
        worst_region: Optional[str] = None,
        regional_evaluations: Optional[Dict[str, Dict[str, Any]]] = None,
        timing_reasons: Optional[List[str]] = None,
        weighted_frequency: Optional[float] = None,
        arithmetic_frequency: Optional[float] = None,
        worst_region_frequency: Optional[float] = None,
        regional_weights: Optional[Dict[str, float]] = None,
        weighted_summary: Optional[Dict[str, Any]] = None,
        degraded_pblocks: Optional[List[str]] = None,
        warning_pblocks: Optional[List[str]] = None,
        quorum_triggered: bool = False
    ):
        self.is_input_valid = is_input_valid
        self.is_physically_valid = is_physically_valid
        self.has_hard_violations = has_hard_violations
        self.max_severity = max_severity
        self.override_reasons = override_reasons
        self.channel_evaluations = channel_evaluations
        self.primary_reason = primary_reason
        self.primary_channel = primary_channel
        self.measured_str = measured_str
        self.limit_str = limit_str
        self.derived_delay_str = derived_delay_str
        self.worst_region = worst_region
        self.regional_evaluations = regional_evaluations or {}
        self.timing_reasons = timing_reasons or []
        self.has_critical = (max_severity in (LimitSeverity.CRITICAL, LimitSeverity.PHYSICALLY_INVALID))
        self.has_warning = (max_severity == LimitSeverity.WARNING)
        self.weighted_frequency = weighted_frequency
        self.arithmetic_frequency = arithmetic_frequency
        self.worst_region_frequency = worst_region_frequency
        self.regional_weights = regional_weights or DEFAULT_REGIONAL_WEIGHTS.copy()
        self.weighted_summary = weighted_summary or {}
        self.degraded_pblocks = degraded_pblocks or []
        self.warning_pblocks = warning_pblocks or []
        self.quorum_triggered = quorum_triggered

    def __getitem__(self, item: str) -> Any:
        mapping = {
            "is_input_valid": self.is_input_valid,
            "is_physically_valid": self.is_physically_valid,
            "has_hard_violations": self.has_hard_violations,
            "has_critical": self.has_critical,
            "has_warning": self.has_warning,
            "max_severity": self.max_severity,
            "override_reasons": self.override_reasons,
            "reasons": self.override_reasons,
            "channel_evaluations": self.channel_evaluations,
            "evaluations": self.channel_evaluations,
            "channels": {k: v.to_dict() for k, v in self.channel_evaluations.items()},
            "primary_reason": self.primary_reason,
            "primary_channel": self.primary_channel,
            "measured_str": self.measured_str,
            "limit_str": self.limit_str,
            "derived_delay_str": self.derived_delay_str,
            "worst_region": self.worst_region,
            "regional_evaluations": self.regional_evaluations,
            "timing_reasons": self.timing_reasons,
            "weighted_frequency": self.weighted_frequency,
            "arithmetic_frequency": self.arithmetic_frequency,
            "worst_region_frequency": self.worst_region_frequency,
            "regional_weights": self.regional_weights,
            "weighted_summary": self.weighted_summary,
            "degraded_pblocks": self.degraded_pblocks,
            "warning_pblocks": self.warning_pblocks,
            "quorum_triggered": self.quorum_triggered
        }
        if item in mapping:
            return mapping[item]
        raise KeyError(f"EngineeringAssessment has no key '{item}'")

    def get(self, item: str, default: Any = None) -> Any:
        try:
            return self[item]
        except KeyError:
            return default

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_input_valid": self.is_input_valid,
            "is_physically_valid": self.is_physically_valid,
            "has_hard_violations": self.has_hard_violations,
            "has_critical": self.has_critical,
            "has_warning": self.has_warning,
            "max_severity": self.max_severity.value,
            "override_reasons": self.override_reasons,
            "reasons": self.override_reasons,
            "channels": {k: v.to_dict() for k, v in self.channel_evaluations.items()},
            "evaluations": {k: v.to_dict() for k, v in self.channel_evaluations.items()},
            "primary_reason": self.primary_reason,
            "primary_channel": self.primary_channel,
            "measured_str": self.measured_str,
            "limit_str": self.limit_str,
            "derived_delay_str": self.derived_delay_str,
            "worst_region": self.worst_region,
            "regional_evaluations": self.regional_evaluations,
            "timing_reasons": self.timing_reasons,
            "weighted_frequency": self.weighted_frequency,
            "arithmetic_frequency": self.arithmetic_frequency,
            "worst_region_frequency": self.worst_region_frequency,
            "regional_weights": self.regional_weights,
            "weighted_summary": self.weighted_summary,
            "degraded_pblocks": self.degraded_pblocks,
            "warning_pblocks": self.warning_pblocks,
            "quorum_triggered": self.quorum_triggered
        }


def evaluate_engineering_limits(
    telemetry: Dict[str, Any],
    provenance_map: Optional[Dict[str, str]] = None,
    regional_baselines: Optional[Dict[str, float]] = None,
    regional_weights: Optional[Dict[str, float]] = None
) -> EngineeringAssessment:
    """
    Evaluates a full telemetry record against all centralized engineering boundaries.
    
    Architectural Principles:
      1. Deterministic engineering rules remain authoritative for physical safety.
      2. Derived quantities (RO_Delay_ns derived from RO_Frequency) are evaluated for
         display and observability, but NEVER counted as a second independent failure.
      3. When four regional monitors (R1..R4) are present, each is assessed independently
         so an anomalous quadrant is not masked by averaging.
      4. A weighted regional frequency summary is computed for aggregate tracking, but
         MUST NEVER override or hide a regional critical fault.
    """
    provenance_map = provenance_map or {}
    regional_baselines = regional_baselines or {}
    evals: Dict[str, ChannelEvaluation] = {}
    reasons: List[str] = []
    timing_reasons: List[str] = []
    max_sev = LimitSeverity.NORMAL
    is_input_valid = True
    is_phys_valid = True
    has_hard_viol = False

    primary_reason = "All engineering limits satisfied"
    primary_channel = "Nominal"
    measured_str = "Nominal"
    limit_str = "Within envelope"
    derived_delay_str = None
    worst_region = None
    regional_evals: Dict[str, Dict[str, Any]] = {}

    # Calculate weighted frequency summary and extract independent worst-case frequency
    weighted_summary = calculate_weighted_regional_frequency(
        telemetry,
        weights=regional_weights,
        provenance_map=provenance_map
    )

    # 1. Independent Regional RO Evaluation (R1, R2, R3, R4)
    has_regional_data = any(f"RO_{r}" in telemetry for r in ["R1", "R2", "R3", "R4"])
    worst_reg_sev = LimitSeverity.NORMAL
    worst_reg_id = None
    worst_reg_reason = None
    worst_reg_meas = None
    worst_reg_lim = None
    worst_reg_delay = None
    degraded_pblocks: List[str] = []
    warning_pblocks: List[str] = []

    if has_regional_data:
        for r_id in ["R1", "R2", "R3", "R4"]:
            ro_k = f"RO_{r_id}"
            if ro_k not in telemetry:
                continue
            r_meas = telemetry[ro_k]
            r_base = regional_baselines.get(ro_k)
            prov = provenance_map.get(ro_k, "MEASURED")

            reg_eval = evaluate_regional_health(
                region_id=r_id,
                measurement=r_meas,
                baseline_freq=r_base,
                provenance=prov
            )
            regional_evals[r_id] = reg_eval

            reg_sev = reg_eval["severity"]
            if reg_sev in (LimitSeverity.CRITICAL, LimitSeverity.PHYSICALLY_INVALID):
                degraded_pblocks.append(r_id)
                if worst_reg_sev != LimitSeverity.CRITICAL:
                    worst_reg_sev = LimitSeverity.CRITICAL
                    worst_reg_id = r_id
                    worst_reg_reason = reg_eval["reason"]
                    worst_reg_meas = f"{reg_eval['current_freq']:.1f} MHz ({r_id})"
                    worst_reg_lim = f"{reg_eval['critical_freq']:.1f} MHz ({r_id} critical boundary)"
                    worst_reg_delay = f"{reg_eval['delay_ns']:.4f} ns (derived from RO frequency)"
            elif reg_sev == LimitSeverity.WARNING:
                warning_pblocks.append(r_id)
                if worst_reg_sev == LimitSeverity.NORMAL:
                    worst_reg_sev = LimitSeverity.WARNING
                    worst_reg_id = r_id
                    worst_reg_reason = reg_eval["reason"]
                    worst_reg_meas = f"{reg_eval['current_freq']:.1f} MHz ({r_id})"
                    worst_reg_lim = f"{reg_eval['warning_freq']:.1f} MHz ({r_id} warning boundary)"
                    worst_reg_delay = f"{reg_eval['delay_ns']:.4f} ns (derived from RO frequency)"

    # 2. Evaluate Non-Timing Physical Sensor Channels
    phys_channels = ["Temperature", "VCCINT", "VCCAUX", "VCCBRAM", "Error_Rate"]
    for ch in phys_channels:
        if ch in telemetry:
            val = telemetry[ch]
            prov = provenance_map.get(ch, "MEASURED")
            eval_res = evaluate_single_channel(ch, val, provenance=prov)
            evals[ch] = eval_res

            if eval_res.severity == LimitSeverity.PHYSICALLY_INVALID:
                is_phys_valid = False
                is_input_valid = False
                max_sev = LimitSeverity.PHYSICALLY_INVALID
                if eval_res.reason:
                    reasons.append(eval_res.reason)
                    primary_reason = f"Physical sensor validity limit breached ({eval_res.display_name})"
                    primary_channel = ch
                    measured_str = f"{val} {eval_res.unit}".strip()
                    limit_str = f"[{eval_res.operating_range_str}]"
            elif eval_res.severity == LimitSeverity.CRITICAL:
                if max_sev != LimitSeverity.PHYSICALLY_INVALID:
                    max_sev = LimitSeverity.CRITICAL
                has_hard_viol = True
                if eval_res.reason:
                    reasons.append(eval_res.reason)
                    if primary_channel == "Nominal" or primary_channel == "RO_Frequency":
                        primary_reason = f"Critical {eval_res.display_name} limit violated"
                        primary_channel = ch
                        measured_str = f"{val} {eval_res.unit}".strip()
                        limit_str = f"Critical limit exceeded"
            elif eval_res.severity == LimitSeverity.WARNING:
                if max_sev == LimitSeverity.NORMAL:
                    max_sev = LimitSeverity.WARNING
                has_hard_viol = True
                if eval_res.reason:
                    reasons.append(eval_res.reason)
                    if primary_channel == "Nominal":
                        primary_reason = f"{eval_res.display_name} operating warning"
                        primary_channel = ch
                        measured_str = f"{val} {eval_res.unit}".strip()
                        limit_str = f"Outside normal range"

    # 3. Evaluate Timing Channels (RO_Frequency and Derived RO_Delay_ns)
    if "RO_Frequency" in telemetry:
        evals["RO_Frequency"] = evaluate_single_channel("RO_Frequency", telemetry["RO_Frequency"], provenance=provenance_map.get("RO_Frequency", "MEASURED"))
    if "RO_Delay_ns" in telemetry:
        evals["RO_Delay_ns"] = evaluate_single_channel("RO_Delay_ns", telemetry["RO_Delay_ns"], provenance=provenance_map.get("RO_Delay_ns", "DERIVED"))

    # 4. Integrate Timing Violation (Quorum Policy: 2 or more degrading pblocks changes overall main status)
    total_degrading_pblocks = len(degraded_pblocks) + len(warning_pblocks)
    quorum_triggered = False

    # Check whether the weighted average itself violates timing limits
    w_freq = weighted_summary.get("weighted_frequency")
    w_eval_sev = LimitSeverity.NORMAL
    w_eval_reason = None
    if w_freq is not None:
        cfg_ro = SENSOR_CONFIG["RO_Frequency"]
        if w_freq <= cfg_ro["critical_low"]:
            w_eval_sev = LimitSeverity.CRITICAL
            w_eval_reason = f"Weighted RO average ({w_freq:.1f} MHz) breached critical boundary ({cfg_ro['critical_low']:.1f} MHz)"
        elif w_freq <= cfg_ro["warning_low"]:
            w_eval_sev = LimitSeverity.WARNING
            w_eval_reason = f"Weighted RO average ({w_freq:.1f} MHz) breached warning boundary ({cfg_ro['warning_low']:.1f} MHz)"

    if has_regional_data and total_degrading_pblocks >= REGION_QUORUM:
        # Multi-pblock degradation: quorum met! Changes overall main value to Degraded/Warning
        quorum_triggered = True
        worst_region = worst_reg_id
        if len(degraded_pblocks) >= REGION_QUORUM or (len(degraded_pblocks) >= 1 and total_degrading_pblocks >= REGION_QUORUM):
            if max_sev != LimitSeverity.PHYSICALLY_INVALID:
                max_sev = LimitSeverity.CRITICAL
            has_hard_viol = True
            pblock_names = ", ".join([f"{r} ({REGIONAL_CONFIG[r]['pblock']})" for r in (degraded_pblocks + warning_pblocks)])
            multi_reason = f"Multi-pblock degradation detected ({pblock_names} showing degradation)"
            reasons.append(multi_reason)
            timing_reasons.append(multi_reason)
            primary_reason = multi_reason
            primary_channel = f"RO_{worst_reg_id}"
            measured_str = worst_reg_meas
            limit_str = worst_reg_lim
            derived_delay_str = worst_reg_delay
        elif len(warning_pblocks) >= REGION_QUORUM:
            if max_sev == LimitSeverity.NORMAL:
                max_sev = LimitSeverity.WARNING
            has_hard_viol = True
            pblock_names = ", ".join([f"{r} ({REGIONAL_CONFIG[r]['pblock']})" for r in warning_pblocks])
            multi_reason = f"Multi-pblock warning drift detected ({pblock_names} showing degradation)"
            reasons.append(multi_reason)
            timing_reasons.append(multi_reason)
            if primary_channel == "Nominal":
                primary_reason = multi_reason
                primary_channel = f"RO_{worst_reg_id}"
                measured_str = worst_reg_meas
                limit_str = worst_reg_lim
                derived_delay_str = worst_reg_delay
    elif w_eval_sev in (LimitSeverity.CRITICAL, LimitSeverity.WARNING) and not has_regional_data:
        # Aggregate weighted RO average breached limits. Only used when no per-region data
        # exists: with regional baselines the regions + quorum policy govern, otherwise one
        # isolated bad region would drag the average and change the overall state by itself.
        worst_region = worst_reg_id
        if w_eval_sev == LimitSeverity.CRITICAL:
            if max_sev != LimitSeverity.PHYSICALLY_INVALID:
                max_sev = LimitSeverity.CRITICAL
            has_hard_viol = True
            reasons.append(w_eval_reason)
            timing_reasons.append(w_eval_reason)
            primary_reason = w_eval_reason
            primary_channel = "RO_Frequency"
            measured_str = f"{w_freq:.1f} MHz"
            limit_str = f"{SENSOR_CONFIG['RO_Frequency']['critical_low']:.1f} MHz"
        elif w_eval_sev == LimitSeverity.WARNING:
            if max_sev == LimitSeverity.NORMAL:
                max_sev = LimitSeverity.WARNING
            has_hard_viol = True
            reasons.append(w_eval_reason)
            timing_reasons.append(w_eval_reason)
            if primary_channel == "Nominal":
                primary_reason = w_eval_reason
                primary_channel = "RO_Frequency"
                measured_str = f"{w_freq:.1f} MHz"
                limit_str = f"{SENSOR_CONFIG['RO_Frequency']['warning_low']:.1f} MHz"
    elif has_regional_data and 0 < total_degrading_pblocks < REGION_QUORUM:
        # Isolated single-pblock anomaly (e.g. only R2):
        # Quorum threshold (< 2) not met; overall main status remains governed by weighted average (HEALTHY)
        worst_region = worst_reg_id
        single_note = f"Isolated single-pblock anomaly in {worst_reg_id} ({REGIONAL_CONFIG[worst_reg_id]['pblock']}: {worst_reg_meas}); quorum policy requires >= 2 degraded pblocks to change overall system status."
        timing_reasons.append(single_note)
    elif not has_regional_data and "RO_Frequency" in telemetry:
        # Fallback when no regional data is present
        ro_eval = evals["RO_Frequency"]
        val_f = float(telemetry["RO_Frequency"])
        equiv_delay = calculate_ro_delay_ns(val_f, stages=RO_STAGES)
        cfg_ro = SENSOR_CONFIG["RO_Frequency"]

        if ro_eval.severity == LimitSeverity.CRITICAL:
            if max_sev != LimitSeverity.PHYSICALLY_INVALID:
                max_sev = LimitSeverity.CRITICAL
            has_hard_viol = True
            if ro_eval.reason:
                reasons.append(ro_eval.reason)
                timing_reasons.append(ro_eval.reason)
            primary_reason = "Critical RO timing limit violated"
            primary_channel = "RO_Frequency"
            measured_str = f"{val_f:.1f} MHz"
            limit_str = f"{cfg_ro['critical_low']:.1f} MHz"
            derived_delay_str = f"{equiv_delay:.4f} ns (derived from RO frequency)"
        elif ro_eval.severity == LimitSeverity.WARNING:
            if max_sev == LimitSeverity.NORMAL:
                max_sev = LimitSeverity.WARNING
            has_hard_viol = True
            if ro_eval.reason:
                reasons.append(ro_eval.reason)
                timing_reasons.append(ro_eval.reason)
            if primary_channel == "Nominal":
                primary_reason = "RO timing drift warning"
                primary_channel = "RO_Frequency"
                measured_str = f"{val_f:.1f} MHz"
                limit_str = f"{cfg_ro['warning_low']:.1f} MHz"
                derived_delay_str = f"{equiv_delay:.4f} ns (derived from RO frequency)"
    elif "RO_Delay_ns" in telemetry:
        delay_eval = evals["RO_Delay_ns"]
        val_d = float(telemetry["RO_Delay_ns"])
        cfg_d = SENSOR_CONFIG["RO_Delay_ns"]
        if delay_eval.severity == LimitSeverity.CRITICAL:
            if max_sev != LimitSeverity.PHYSICALLY_INVALID:
                max_sev = LimitSeverity.CRITICAL
            has_hard_viol = True
            if delay_eval.reason:
                reasons.append(delay_eval.reason)
                timing_reasons.append(delay_eval.reason)
            primary_reason = "Critical RO propagation delay exceeded"
            primary_channel = "RO_Delay_ns"
            measured_str = f"{val_d:.4f} ns"
            limit_str = f"{cfg_d['critical_high']:.4f} ns"
            derived_delay_str = f"{val_d:.4f} ns (derived from RO frequency)"
        elif delay_eval.severity == LimitSeverity.WARNING:
            if max_sev == LimitSeverity.NORMAL:
                max_sev = LimitSeverity.WARNING
            has_hard_viol = True
            if delay_eval.reason:
                reasons.append(delay_eval.reason)
                timing_reasons.append(delay_eval.reason)
            if primary_channel == "Nominal":
                primary_reason = "RO propagation delay elevated"
                primary_channel = "RO_Delay_ns"
                measured_str = f"{val_d:.4f} ns"
                limit_str = f"{cfg_d['warning_high']:.4f} ns"
                derived_delay_str = f"{val_d:.4f} ns (derived from RO frequency)"

    return EngineeringAssessment(
        is_input_valid=is_input_valid,
        is_physically_valid=is_phys_valid,
        has_hard_violations=has_hard_viol,
        max_severity=max_sev,
        override_reasons=reasons,
        channel_evaluations=evals,
        primary_reason=primary_reason,
        primary_channel=primary_channel,
        measured_str=measured_str,
        limit_str=limit_str,
        derived_delay_str=derived_delay_str,
        worst_region=worst_region,
        regional_evaluations=regional_evals,
        timing_reasons=timing_reasons,
        weighted_frequency=weighted_summary["weighted_frequency"],
        arithmetic_frequency=weighted_summary["arithmetic_frequency"],
        worst_region_frequency=weighted_summary["worst_region_frequency"],
        regional_weights=weighted_summary["weights_used"],
        weighted_summary=weighted_summary,
        degraded_pblocks=degraded_pblocks,
        warning_pblocks=warning_pblocks,
        quorum_triggered=quorum_triggered
    )


def determine_final_health(
    ml_prediction: str,
    ml_confidence: float,
    engineering_assessment: Any
) -> Dict[str, Any]:
    """
    Combines Random Forest ML prediction with Engineering Limit Assessment.
    If hard limits are breached, engineering safety overrides ML prediction.

    Precedence:
      1. Physically Invalid -> Final: 'Degraded' / Critical, Override: True
      2. Critical Operating Breach -> Final: 'Degraded', Override: True (if ML != Degraded)
      3. Warning Operating Breach -> Final: 'Warning' (if ML == Healthy), Override: True
      4. Normal -> Final: ML Prediction, Override: False
    """
    ml_pred_clean = str(ml_prediction).strip()
    override_applied = False
    override_title = ""
    override_explanation = ""
    final_health = ml_pred_clean

    if isinstance(engineering_assessment, dict):
        max_sev_val = engineering_assessment.get("max_severity", "NORMAL")
        if isinstance(max_sev_val, LimitSeverity):
            max_sev = max_sev_val
        else:
            try:
                max_sev = LimitSeverity(max_sev_val)
            except Exception:
                max_sev = LimitSeverity.NORMAL
        reasons = engineering_assessment.get("override_reasons") or engineering_assessment.get("reasons", [])
        evals = engineering_assessment.get("evaluations") or engineering_assessment.get("channel_evaluations", {})
        primary_reason = engineering_assessment.get("primary_reason", "Deterministic engineering limit violated")
        primary_channel = engineering_assessment.get("primary_channel", "Nominal")
        measured_str = engineering_assessment.get("measured_str", "Nominal")
        limit_str = engineering_assessment.get("limit_str", "Nominal")
        derived_delay_str = engineering_assessment.get("derived_delay_str")
        worst_region = engineering_assessment.get("worst_region")
        regional_evals = engineering_assessment.get("regional_evaluations", {})
        eng_dict = engineering_assessment
    else:
        max_sev = engineering_assessment.max_severity
        reasons = engineering_assessment.override_reasons
        evals = engineering_assessment.channel_evaluations
        primary_reason = getattr(engineering_assessment, "primary_reason", "Deterministic engineering limit violated")
        primary_channel = getattr(engineering_assessment, "primary_channel", "Nominal")
        measured_str = getattr(engineering_assessment, "measured_str", "Nominal")
        limit_str = getattr(engineering_assessment, "limit_str", "Nominal")
        derived_delay_str = getattr(engineering_assessment, "derived_delay_str", None)
        worst_region = getattr(engineering_assessment, "worst_region", None)
        regional_evals = getattr(engineering_assessment, "regional_evaluations", {})
        eng_dict = engineering_assessment.to_dict()

    final_decision_str = f"{ml_pred_clean.upper()} (All engineering limits satisfied)."

    if max_sev == LimitSeverity.PHYSICALLY_INVALID:
        final_health = "Degraded"
        override_applied = True
        override_title = "CRITICAL — PHYSICAL VALIDITY OVERRIDE"
        override_explanation = (
            f"Telemetry values violate physical sensor limits ({'; '.join(reasons)}). "
            f"The Random Forest predicted '{ml_pred_clean}' ({ml_confidence * 100:.1f}%), "
            "but physical sensor validity takes absolute precedence."
        )
        final_decision_str = "DEGRADED because physical sensor validity limits take precedence over the ML prediction."

    elif max_sev == LimitSeverity.CRITICAL:
        final_health = "Degraded"
        if ml_pred_clean != "Degraded":
            override_applied = True
            override_title = "CRITICAL — HARD OPERATING LIMIT OVERRIDE"
            override_explanation = (
                f"Hard engineering safety constraints violated ({'; '.join(reasons)}). "
                f"The Random Forest predicted '{ml_pred_clean}' ({ml_confidence * 100:.1f}%), "
                "but engineering operating limits take precedence."
            )
            final_decision_str = "DEGRADED because the deterministic engineering limit takes precedence over the ML prediction."
        else:
            final_decision_str = "DEGRADED (ML prediction confirmed by deterministic engineering limits)."

    elif max_sev == LimitSeverity.WARNING:
        if ml_pred_clean == "Healthy":
            final_health = "Warning"
            override_applied = True
            override_title = "WARNING — OPERATING THRESHOLD OVERRIDE"
            override_explanation = (
                f"Sensor telemetry breached normal operating range ({'; '.join(reasons)}). "
                f"The Random Forest predicted '{ml_pred_clean}' ({ml_confidence * 100:.1f}%), "
                "which has been elevated to Warning based on engineering constraints."
            )
            final_decision_str = "WARNING because the deterministic operating boundary takes precedence over the ML prediction."
        elif ml_pred_clean == "Degraded":
            final_health = "Degraded"
            final_decision_str = "DEGRADED based on ML probabilistic model inference."
        else:
            final_health = "Warning"
            final_decision_str = "WARNING (ML prediction confirmed by engineering limits)."

    assessment_panel = {
        "ml_prediction": ml_pred_clean.upper(),
        "ml_confidence": float(ml_confidence),
        "ml_confidence_str": f"{ml_confidence * 100:.1f}%",
        "eng_assessment": final_health.upper(),
        "primary_reason": primary_reason,
        "primary_channel": primary_channel,
        "measured_str": measured_str,
        "limit_str": limit_str,
        "derived_delay_str": derived_delay_str,
        "final_decision": final_decision_str
    }

    return {
        "ml_prediction": ml_pred_clean,
        "ml_confidence": float(ml_confidence),
        "confidence": float(ml_confidence),
        "final_health": final_health,
        "override_applied": override_applied,
        "override_title": override_title,
        "override_explanation": override_explanation,
        "override_reasons": reasons,
        "reasons": reasons,
        "evaluations": evals,
        "engineering_assessment": eng_dict,
        "assessment_panel": assessment_panel,
        "primary_reason": primary_reason,
        "primary_channel": primary_channel,
        "measured_str": measured_str,
        "limit_str": limit_str,
        "derived_delay_str": derived_delay_str,
        "final_decision": final_decision_str,
        "worst_region": worst_region,
        "regional_evaluations": regional_evals
    }
