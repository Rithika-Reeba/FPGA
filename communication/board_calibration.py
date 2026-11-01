"""
Automatic baseline for whichever Basys 3 is plugged in; nothing to set up.

A ring oscillator's frequency depends on how Vivado routed it and on the individual chip, so the
"healthy" frequencies are measured from the board itself. There is ONE baseline file
(hardware/host/calibration.json), not one per board:

  * the saved baseline matches the connected board and build -> use it
  * otherwise (new board, new build, no file)               -> record a new one, but ONLY if the
    board is cool, idle (no stress switch up), all oscillators alive and steady; otherwise report
    why not and leave NO baseline in force (the dashboard shows "not calibrated").

Nothing is recorded from a hot or stressed board, so it can never be mistaken for healthy.
The USB serial number is stored inside the file only to notice that a different board was
plugged in; it is never a file name or something the user selects.
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
from hardware.host.health_reader import REGIONS, build_calibration, check_idle, parse_line

HOST_DIR = PROJECT_ROOT / "hardware" / "host"
CAL_FILE = rules.calibration_path()


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


def clear_calibration() -> None:
    """No baseline in force (a stale one for another board or build would be wrong)."""
    try:
        CAL_FILE.unlink()
    except FileNotFoundError:
        pass


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


def ensure_calibration(port: str, force: bool = False) -> Dict[str, Any]:
    """
    Make sure a baseline valid for this board and build is in force.
    Returns {"state": "ok" | "created" | "waiting" | "error", "board_id", "build_id", "reason"}.
    Never raises on serial problems; they come back as state "error".
    """
    board_id = board_id_for_port(port) or "board"
    try:
        # Two packets are enough to learn which build runs and whether the saved baseline matches;
        # the full 20 (about 10 s) are only read when a new baseline has to be recorded.
        samples = read_packets(port, 2, timeout_s=6.0)       # a silent board is reported after 6 s, not 20
    except Exception as exc:                                   # port busy, unplugged, ...
        return {"state": "error", "port": port, "board_id": board_id, "build_id": None, "reason": f"cannot read {port}: {exc}"}

    if not samples:
        return {"state": "error", "port": port, "board_id": board_id, "build_id": None,
                "reason": "no telemetry packets (is sw0 down and the design programmed?)"}

    build_id = samples[-1].get("build_id")

    if CAL_FILE.exists() and not force:
        try:
            cal = json.loads(CAL_FILE.read_text())
        except (OSError, ValueError):
            cal = None
        if cal and cal.get("build_id") == build_id and cal.get("board_id") == board_id:
            return {"state": "ok", "port": port, "board_id": board_id, "build_id": build_id,
                    "reason": "saved baseline matches this board and build"}

    if len(samples) < rules.AUTOCAL_SAMPLES:
        try:
            samples = read_packets(port, rules.AUTOCAL_SAMPLES)
        except Exception as exc:
            return {"state": "error", "port": port, "board_id": board_id, "build_id": build_id,
                    "reason": f"cannot read {port}: {exc}"}
    ok, reason = check_idle(samples)
    if not ok:
        if not force:
            clear_calibration()                # a baseline for another board or build would be wrong
        # (a forced recalibration that cannot proceed leaves the working baseline untouched)
        return {"state": "waiting", "port": port, "board_id": board_id, "build_id": build_id, "reason": reason}

    cal = build_calibration(samples)
    fault = samples[-1].get("test_fault")
    if fault:       # baseline taken with the injected fault on: undo it, so the baseline is the TRUE one
        k = 1.0 - 2.0 ** -rules.TEST_FAULT_SHIFT
        cal["regions"][fault]["mean_mhz"] /= k
        cal["regions"][fault]["std_mhz"] /= k
        cal["test_fault_compensated"] = fault
    cal.update({"board_id": board_id, "build_id": build_id,
                "recorded": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": "automatic"})
    CAL_FILE.write_text(json.dumps(cal, indent=2))
    return {"state": "created", "port": port, "board_id": board_id, "build_id": build_id,
            "reason": f"new baseline recorded ({cal['temp_c']:.1f} C, idle)"}
