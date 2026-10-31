"""
Automatic per-board, per-build baseline.

A ring oscillator's frequency depends on how Vivado routed it, so every bitstream build and
every board has its own "healthy" frequencies. This module finds out which board is on the
serial port (from its USB serial number) and which build it runs (the V= field of each
packet), and makes sure a matching baseline exists:

  * matching baseline already saved      -> use it
  * missing or recorded for another build -> record a new one, but ONLY if the board is cool,
    idle (no stress switch up), all oscillators alive and steady; otherwise report why not.

Nothing is recorded from a hot or stressed board, so it can never be mistaken for healthy.
Baselines are saved as hardware/host/calibration_<board_id>.json; the one in force is named in
hardware/host/active_board.txt (empty = none valid, the dashboard shows "not calibrated").
"""

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import health_rules as rules
from hardware.host.health_reader import REGIONS, build_calibration, parse_line

HOST_DIR = PROJECT_ROOT / "hardware" / "host"
ACTIVE_FILE = HOST_DIR / "active_board.txt"


def detect_board_port() -> Optional[str]:
    """Serial port of a Digilent/FTDI FT2232H (the Basys 3 USB bridge), without importing the
    dashboard modules (this runs before they are loaded)."""
    try:
        import serial.tools.list_ports as lp
    except ImportError:
        return None
    found = sorted(p.device for p in lp.comports() if p.vid == 0x0403 and p.pid == 0x6010)
    return found[0] if found else None          # sorted: the same board on every start


def list_board_ports() -> List[Tuple[str, Optional[str]]]:
    """Every Basys 3 style USB-serial port as (device, board id), lowest port name first."""
    try:
        import serial.tools.list_ports as lp
    except ImportError:
        return []
    found = [p.device for p in lp.comports() if p.vid == 0x0403 and p.pid == 0x6010]
    return [(d, board_id_for_port(d)) for d in sorted(found)]


def board_id_for_port(port: str) -> Optional[str]:
    """USB serial number of the FTDI chip behind `port`, without the trailing channel letter."""
    try:
        import serial.tools.list_ports as lp
    except ImportError:
        return None
    for p in lp.comports():
        if p.device == port and p.serial_number:
            serial_no = re.sub(r"[^A-Za-z0-9]", "", p.serial_number)
            return serial_no[:-1] if serial_no[-1:] in ("A", "B") else serial_no
    return None


def calibration_path(board_id: str) -> Path:
    return HOST_DIR / f"calibration_{board_id}.json"


def set_active(board_id: Optional[str]) -> None:
    ACTIVE_FILE.write_text(board_id or "", encoding="ascii")


def read_packets(port: str, count: int, timeout_s: float = 20.0) -> List[Dict[str, Any]]:
    """Read up to `count` valid telemetry packets from the board."""
    import serial
    out: List[Dict[str, Any]] = []
    with serial.Serial(port, 115200, timeout=1.5) as ser:
        ser.reset_input_buffer()
        end = time.time() + timeout_s
        while len(out) < count and time.time() < end:
            raw = ser.readline()
            if not raw:
                continue
            parsed = parse_line(raw.decode("ascii", errors="ignore"))
            if parsed:
                out.append(parsed)
    return out


def check_idle(samples: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """Is this stretch of telemetry a trustworthy healthy reference?"""
    if len(samples) < rules.AUTOCAL_SAMPLES:
        return False, f"only {len(samples)} of {rules.AUTOCAL_SAMPLES} packets received"
    if any(any(s["stress"].values()) for s in samples):
        return False, "a stress switch (sw12..sw15) is on; switch it off and let the chip cool"
    if any(not all(s["alive"].values()) for s in samples):
        return False, "a ring oscillator is not running (is sw1 up?)"
    hottest = max(s["temp_c"] for s in samples)
    if hottest > rules.TEMP_AUTOCAL_MAX_C:
        return False, f"board is warm ({hottest:.1f} C, limit {rules.TEMP_AUTOCAL_MAX_C:.0f} C); wait for it to cool"
    for r in REGIONS:
        vals = [s["freq_mhz"][r] for s in samples]
        mean = sum(vals) / len(vals)
        std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        if mean <= 0 or std / mean > rules.AUTOCAL_MAX_REL_STD:
            return False, f"{r} is not steady yet (variation {std / max(mean, 1e-9) * 100:.3f} %)"
    return True, "cool, idle and steady"


def ensure_calibration(port: str, force: bool = False) -> Dict[str, Any]:
    """
    Make sure a baseline valid for this board and build is in force.
    Returns {"state": "ok" | "created" | "waiting" | "error", "board_id", "build_id", "reason"}.
    Never raises on serial problems; they come back as state "error".
    """
    board_id = board_id_for_port(port) or "board"
    try:
        samples = read_packets(port, rules.AUTOCAL_SAMPLES)
    except Exception as exc:                                   # port busy, unplugged, ...
        return {"state": "error", "port": port, "board_id": board_id, "build_id": None, "reason": f"cannot read {port}: {exc}"}

    if not samples:
        return {"state": "error", "port": port, "board_id": board_id, "build_id": None,
                "reason": "no telemetry packets (is sw0 down and the design programmed?)"}

    build_id = samples[-1].get("build_id")
    path = calibration_path(board_id)

    if path.exists() and not force:
        try:
            cal = json.loads(path.read_text())
        except (OSError, ValueError):
            cal = None
        if cal and cal.get("build_id") == build_id:
            set_active(board_id)
            return {"state": "ok", "port": port, "board_id": board_id, "build_id": build_id,
                    "reason": "saved baseline matches this board and build"}

    ok, reason = check_idle(samples)
    if not ok:
        if not force:
            set_active(None)                   # a baseline for another build would be wrong
        # (a forced recalibration that cannot proceed leaves the working baseline untouched)
        return {"state": "waiting", "port": port, "board_id": board_id, "build_id": build_id, "reason": reason}

    cal = build_calibration(samples)
    cal.update({"board_id": board_id, "build_id": build_id,
                "recorded": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": "automatic"})
    path.write_text(json.dumps(cal, indent=2))
    set_active(board_id)
    return {"state": "created", "port": port, "board_id": board_id, "build_id": build_id,
            "reason": f"new baseline recorded ({cal['temp_c']:.1f} C, idle)"}
