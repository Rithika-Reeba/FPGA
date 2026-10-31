"""
Single source of truth for every FPGA health threshold.

Everything that decides Healthy / Warning / Degraded reads its numbers from here:
  * config.py and dashboard/config.py  (all four telemetry sources: UART, simulation,
    mock CSV replay and estimated assessment go through the same dashboard pipeline)
  * hardware/host/health_reader.py     (host-side live monitor)
  * hardware/rtl/fpga_health_top.v     (on-board LEDs) - kept in step by
    tests/test_rules_sync.py, which fails if the RTL constants drift from this file.

Change a limit here and it changes everywhere. The numbers below are deliberate
defaults, NOT measured values: tune them from real board data (see calibration).

Ring-oscillator limits are RELATIVE to a per-board baseline, because the absolute
frequency depends on each region's placement and routing. A baseline is stored by
`hardware/host/health_reader.py --calibrate` in calibration_<board>.json; select it
with the FPGA_BOARD environment variable. Without a calibration the placeholder
nominal below is used (it is only a default, not a property of any real board).
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional

REGIONS = ("R1", "R2", "R3", "R4")

# ---------------------------------------------------------------------------
# Ring oscillator (relative to baseline). 1/256 and 1/64 are exactly what the
# hardware LEDs compute with shifts (WARN_SHIFT = 8, DEG_SHIFT = 6).
# ---------------------------------------------------------------------------
RO_WARN_DROP_PCT = 100.0 / 256.0     # 0.390625 %  frequency drop  -> Warning
RO_CRIT_DROP_PCT = 100.0 / 64.0      # 1.5625   %  frequency drop  -> Degraded
RO_RISE_WARN_PCT = 2.5               # abnormal over-frequency (dashboard only)
RO_RISE_CRIT_PCT = 5.5
RO_PLACEHOLDER_NOMINAL_MHZ = 436.0   # used only until a board is calibrated

# ---------------------------------------------------------------------------
# Die temperature (XADC) and supply rails
# ---------------------------------------------------------------------------
TEMP_WARN_C = 60.0
TEMP_CRIT_C = 70.0
TEMP_STRESS_RESUME_C = 65.0   # stress heaters may switch back on below this (hysteresis)

VOLT_NOMINAL_V: Dict[str, float] = {"VCCINT": 1.0, "VCCAUX": 1.8, "VCCBRAM": 1.0}
VOLT_WARN_FRAC = 0.05     # +/- 5 %  -> Warning
VOLT_CRIT_FRAC = 0.10     # +/- 10 % -> Degraded

# Automatic baseline on first plug-in: only recorded while the board is cool, idle and steady,
# so a hot or stressed board can never be mistaken for the healthy reference.
TEMP_AUTOCAL_MAX_C = 46.0     # idle die temperature on the Basys 3 is about 42-43 C
AUTOCAL_SAMPLES = 20          # about 10 s of telemetry (2 packets per second)
AUTOCAL_MAX_REL_STD = 0.0005  # per-region frequency std/mean must stay below 0.05 %

# Functional error rate (fraction of bad bits). Not produced by the current board
# firmware; kept for the simulated sources and for a future hardware canary path.
ERROR_RATE_WARN = 0.0005
ERROR_RATE_CRIT = 0.002

# ---------------------------------------------------------------------------
# Aggregation (as in the report): the overall state changes only when at least
# REGION_QUORUM regions are Warning/Degraded. A single bad region is still shown
# on its own card (and on the board's per-region LEDs); it just does not by itself
# change the overall chip state. Sensor limits (temperature / rails) apply always.
# ---------------------------------------------------------------------------
REGION_QUORUM = 2

# Weights of the aggregate (weighted-average) RO frequency, as in the report.
REGION_WEIGHTS: Dict[str, float] = {"R1": 0.35, "R2": 0.05, "R3": 0.30, "R4": 0.30}


# ---------------------------------------------------------------------------
# Per-board calibration
# ---------------------------------------------------------------------------
def _calibration_path(board: str) -> Path:
    return Path(__file__).resolve().parent / "hardware" / "host" / f"calibration_{board}.json"


def active_board() -> Optional[str]:
    """Board whose calibration is in force: FPGA_BOARD env var, else hardware/host/active_board.txt
    (written by `health_reader.py --calibrate`)."""
    board = os.environ.get("FPGA_BOARD")
    if board:
        return board
    try:
        text = (Path(__file__).resolve().parent / "hardware" / "host" / "active_board.txt").read_text().strip()
        return text or None
    except OSError:
        return None


def load_calibration(board: Optional[str] = None) -> Optional[dict]:
    board = board or active_board()
    if not board:
        return None
    path = _calibration_path(board)
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def region_nominal_mhz(region: str, calibration: Optional[dict] = None) -> float:
    """Baseline frequency of one region: calibrated mean if available, else placeholder."""
    cal = calibration if calibration is not None else load_calibration()
    if cal:
        try:
            return float(cal["regions"][region]["mean_mhz"])
        except (KeyError, TypeError, ValueError):
            pass
    return RO_PLACEHOLDER_NOMINAL_MHZ


def global_nominal_mhz() -> float:
    """Nominal of the aggregate metric: the baselines combined with the SAME weights
    the aggregate frequency uses, so identical-to-baseline regions give zero drift."""
    return sum(REGION_WEIGHTS[r] * region_nominal_mhz(r) for r in REGIONS)


def ro_limits(nominal_mhz: float) -> Dict[str, float]:
    """Absolute RO frequency boundaries derived from a baseline."""
    return {
        "nominal": nominal_mhz,
        "warn_low": nominal_mhz * (1.0 - RO_WARN_DROP_PCT / 100.0),
        "crit_low": nominal_mhz * (1.0 - RO_CRIT_DROP_PCT / 100.0),
        "warn_high": nominal_mhz * (1.0 + RO_RISE_WARN_PCT / 100.0),
        "crit_high": nominal_mhz * (1.0 + RO_RISE_CRIT_PCT / 100.0),
    }


def volt_limits(rail: str) -> Dict[str, float]:
    nom = VOLT_NOMINAL_V[rail]
    return {
        "nominal": nom,
        "warn_low": round(nom * (1.0 - VOLT_WARN_FRAC), 4),
        "warn_high": round(nom * (1.0 + VOLT_WARN_FRAC), 4),
        "crit_low": round(nom * (1.0 - VOLT_CRIT_FRAC), 4),
        "crit_high": round(nom * (1.0 + VOLT_CRIT_FRAC), 4),
    }


# ---------------------------------------------------------------------------
# Raw XADC codes (what the RTL compares against)
#   temp [degC] = code * 503.975 / 4096 - 273.15      volt [V] = code * 3 / 4096
# ---------------------------------------------------------------------------
def temp_code(celsius: float) -> int:
    return int(round((celsius + 273.15) * 4096.0 / 503.975))


def volt_code(volts: float) -> int:
    return int(round(volts * 4096.0 / 3.0))


# ---------------------------------------------------------------------------
# Pure classifier used by the host reader (the dashboard uses the same numbers
# through dashboard/config.py)
# ---------------------------------------------------------------------------
HEALTHY, WARNING, DEGRADED = "Healthy", "Warning", "Degraded"


def classify_region(freq_mhz: float, baseline_mhz: float, alive: bool = True) -> str:
    if not alive or freq_mhz <= 0:
        return DEGRADED
    drop = (1.0 - freq_mhz / baseline_mhz) * 100.0
    if drop >= RO_CRIT_DROP_PCT:
        return DEGRADED
    if drop >= RO_WARN_DROP_PCT:
        return WARNING
    return HEALTHY


def classify_temperature(celsius: float) -> str:
    if celsius >= TEMP_CRIT_C:
        return DEGRADED
    if celsius >= TEMP_WARN_C:
        return WARNING
    return HEALTHY


def classify_error_rate(rate: float) -> str:
    if rate >= ERROR_RATE_CRIT:
        return DEGRADED
    if rate >= ERROR_RATE_WARN:
        return WARNING
    return HEALTHY


def worst_state(states) -> str:
    order = {HEALTHY: 0, WARNING: 1, DEGRADED: 2}
    return max(states, key=lambda s: order[s])


def classify_voltage(rail: str, volts: float) -> str:
    nom = VOLT_NOMINAL_V[rail]
    dev = abs(volts - nom) / nom
    if dev >= VOLT_CRIT_FRAC:
        return DEGRADED
    if dev >= VOLT_WARN_FRAC:
        return WARNING
    return HEALTHY
