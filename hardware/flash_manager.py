"""
FPGA Hardware Programming Helper for Digilent Basys 3 (XC7A35T)
================================================================
Programs the precompiled health-monitor bitstream over JTAG (volatile: it is lost when the board
loses power) and can query/back up the device.

Several boards can be connected at once, so every operation selects its target by BOARD ID (the
Digilent cable id = the USB serial number without its last letter, e.g. 210183B31BC1). With more
than one board connected and no id given, it refuses instead of picking whichever board Vivado
lists first.
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple

HARDWARE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = HARDWARE_DIR.parent
BUILD_DIR = HARDWARE_DIR / "build"
DEFAULT_BACKUP_PATH = HARDWARE_DIR / "backup_original.bin"

VIVADO_BAT = os.environ.get("VIVADO_PATH", r"C:\AMDDesignTools\2026.1\Vivado\bin\vivado.bat")


def get_bitstream_path() -> Path:
    """The most recently built bitstream among the usual places."""
    candidates = [
        Path(r"C:\vivado_build\build\fpga_health_top.bit"),
        BUILD_DIR / "fpga_health_top.bit",
        HARDWARE_DIR / "fpga_health_top.bit",
    ]
    existing = [c for c in candidates if c.exists()]
    return max(existing, key=lambda c: c.stat().st_mtime) if existing else candidates[0]


BITSTREAM_PATH = get_bitstream_path()

_OPEN_TARGET_TCL = r"""
set targets [get_hw_targets]
if {[llength $targets] == 0} { puts "ERROR: no board found. Check the USB cable and the power switch."; exit 1 }
if {[llength $targets] > 1} {
    set want "__WANT__"
    if {$want eq ""} {
        puts "ERROR: [llength $targets] boards are connected; the board id is required."
        exit 1
    }
    set picked {}
    foreach tg $targets { if {[string match "*${want}*" $tg]} { lappend picked $tg } }
    if {[llength $picked] != 1} { puts "ERROR: board id $want matches [llength $picked] connected boards"; exit 1 }
    current_hw_target [lindex $picked 0]
}
puts "--> Target: [current_hw_target]"
open_hw_target
"""


def _open_target(board_id: Optional[str]) -> str:
    want = re.sub(r"[^A-Za-z0-9]", "", board_id or "")      # only letters/digits reach the Tcl
    return _OPEN_TARGET_TCL.replace("__WANT__", want)


def _error_lines(output: str):
    """Real Vivado errors only. Vivado also echoes the script's own source lines (starting with '#'),
    and those contain the text "ERROR:" inside puts commands; they must not count as errors."""
    return [l.strip() for l in output.splitlines() if l.lstrip().startswith("ERROR:")]


def run_vivado_tcl(tcl_commands: str, timeout_sec: int = 120) -> Tuple[bool, str]:
    """Run Vivado in batch mode on a temporary Tcl script. Success = exit code 0 and no ERROR line."""
    if not Path(VIVADO_BAT).exists():
        return False, f"Vivado executable not found at: {VIVADO_BAT}"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".tcl", delete=False) as tf:
        tf.write(tcl_commands)
        temp_tcl = tf.name
    cmd = [VIVADO_BAT, "-mode", "batch", "-nolog", "-nojournal", "-source", temp_tcl]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec, cwd=str(PROJECT_ROOT))
        output = proc.stdout + "\n" + proc.stderr
        return (proc.returncode == 0 and not _error_lines(output)), output
    except subprocess.TimeoutExpired:
        return False, f"Vivado operation timed out after {timeout_sec} seconds."
    except Exception as exc:
        return False, f"Failed to execute Vivado: {exc}"
    finally:
        try:
            os.remove(temp_tcl)
        except OSError:
            pass


def program_health_bitstream(bitstream_path: Optional[Path] = None, board_id: Optional[str] = None) -> Tuple[bool, str]:
    """Program the health-monitor bitstream into ONE board (selected by board_id)."""
    bit_path = Path(bitstream_path) if bitstream_path else get_bitstream_path()
    if not bit_path.exists():
        return False, f"Bitstream file not found at: {bit_path}. Build it first."
    bit_str = str(bit_path).replace("\\", "/")

    tcl = f"""
open_hw_manager
connect_hw_server -allow_non_jtag
{_open_target(board_id)}
set target_device [lindex [get_hw_devices xc7a35t_0] 0]
if {{$target_device eq ""}} {{ set target_device [lindex [get_hw_devices] 0] }}
current_hw_device $target_device
refresh_hw_device -update_hw_probes false [current_hw_device]
set_property PROGRAM.FILE "{bit_str}" [current_hw_device]
puts "--> Programming with: {bit_str}"
program_hw_devices [current_hw_device]
refresh_hw_device [current_hw_device]
close_hw_target
disconnect_hw_server
close_hw_manager
puts "SUCCESS: Basys 3 successfully programmed."
"""
    ok, out = run_vivado_tcl(tcl, timeout_sec=120)
    if ok and any(l.strip() == "SUCCESS: Basys 3 successfully programmed." for l in out.splitlines()):
        return True, f"Board {board_id or '(only board)'} programmed with {bit_path.name} (build in the V= field). Telemetry is on UART 115200 8N1."
    detail = _error_lines(out)[:4]
    return False, "Programming failed:\n" + ("\n".join(detail) or out[-600:])


if __name__ == "__main__":
    # python -m hardware.flash_manager program [board id]
    action = sys.argv[1] if len(sys.argv) > 1 else "help"
    if action == "program":
        ok, msg = program_health_bitstream(board_id=sys.argv[2] if len(sys.argv) > 2 else None)
        print(msg)
        sys.exit(0 if ok else 1)
    print("Usage: python -m hardware.flash_manager program [board id]")
