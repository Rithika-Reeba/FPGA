"""
Starts the dashboard as the ONLY instance.

If another copy of the dashboard is already running (on any port), it is closed first, together with
the serial ports it holds, and this one becomes the proper instance. Only processes that are this
project's Streamlit dashboard are ever stopped; anything else that happens to use the port is left
alone and reported instead.

    venv\\Scripts\\python.exe run_dashboard.py [port]        (default port 8511)
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8511


def _powershell(script: str) -> str:
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                         capture_output=True, text=True, timeout=60)
    return out.stdout.strip()


def dashboard_processes():
    """Running processes whose command line is a Streamlit run of this project's dashboard/app.py."""
    script = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'streamlit' -and "
              "$_.CommandLine -match 'dashboard[/\\\\]app\\.py' } | "
              "Select-Object ProcessId, ParentProcessId | ConvertTo-Json -Compress")
    text = _powershell(script)
    if not text:
        return []
    data = json.loads(text)
    rows = data if isinstance(data, list) else [data]
    return [(int(r["ProcessId"]), int(r["ParentProcessId"])) for r in rows if int(r["ProcessId"]) != os.getpid()]


def port_owners(port: int):
    text = _powershell(f"Get-NetTCPConnection -State Listen -LocalPort {port} -ErrorAction SilentlyContinue | "
                       "Select-Object -ExpandProperty OwningProcess")
    return {int(x) for x in text.split() if x.strip().isdigit()}


def stop_old_instances() -> None:
    old = dashboard_processes()
    old_pids = {pid for pid, _ in old} | {ppid for _, ppid in old if ppid in {p for p, _ in old}}
    foreign = port_owners(PORT) - old_pids
    if foreign:
        print(f"Port {PORT} is used by another program (process {sorted(foreign)}) that is not this dashboard.")
        print("It was NOT stopped. Close it yourself, or pass another port:  run_dashboard.py 8512")
        sys.exit(1)
    if old:
        print(f"Another dashboard is running (process {sorted(p for p, _ in old)}); closing it ...")
        for pid in sorted(old_pids):
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        for _ in range(20):                                   # wait until its port and serial ports are free
            if not port_owners(PORT) and not dashboard_processes():
                break
            time.sleep(0.5)
        else:
            print("The old dashboard did not close; stop it manually and try again.")
            sys.exit(1)


if __name__ == "__main__":
    os.chdir(ROOT)
    stop_old_instances()
    print(f"Starting the dashboard on http://localhost:{PORT} ...")
    print("(The first page can take about 20 seconds: it reads the board first.  Ctrl+C stops it.)")
    cmd = [sys.executable, "-m", "streamlit", "run", "dashboard/app.py",
           "--server.port", str(PORT), "--server.address", "localhost"]
    sys.exit(subprocess.call(cmd))
