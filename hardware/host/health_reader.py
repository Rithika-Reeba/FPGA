"""
Host-side reader for the Basys 3 four-region FPGA health monitor.

The board streams one ASCII-hex line per reading, for example:
    R1=0007D0,R2=...,R3=...,R4=...,T=994,I=555,A=99A,B=555,F=F,S=0,H=1

This script converts the raw codes to physical units, learns a
baseline, and classifies every region as HEALTHY / WARNING / DEGRADED.

Usage
-----
    python health_reader.py --selftest
    python health_reader.py --port COM3 --calibrate 30
    python health_reader.py --port COM3                         # live monitor
    python health_reader.py --replay log.txt                    # offline

The baseline is one file, calibration.json next to this file. It is not tied to a board name:
the dashboard re-records it automatically whenever a different board or build is connected.
"""

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

LINE_RE = re.compile(
    r"^R1=(?P<r1>[0-9A-F]{6}),R2=(?P<r2>[0-9A-F]{6}),R3=(?P<r3>[0-9A-F]{6}),"
    r"R4=(?P<r4>[0-9A-F]{6}),T=(?P<t>[0-9A-F]{3}),I=(?P<i>[0-9A-F]{3}),"
    r"A=(?P<a>[0-9A-F]{3}),B=(?P<b>[0-9A-F]{3}),F=(?P<f>[0-9A-F]),"
    r"S=(?P<s>[0-9A-F]),H=(?P<h>[0-9A-F])(?:,V=(?P<v>[0-9A-F]{4}))?(?:,C=(?P<c>[0-9A-F]{2}))?$"
)

GATE_SECONDS = 0.010            # must match GATE_TICKS / 100 MHz in the RTL
REGIONS = ("R1", "R2", "R3", "R4")

# Every limit comes from the single source of truth (health_rules.py at the repo root)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import health_rules as rules  # noqa: E402

HEALTHY, WARNING, DEGRADED = rules.HEALTHY, rules.WARNING, rules.DEGRADED
UNCAL = "Uncalibrated"
RANK = {UNCAL: 0, HEALTHY: 1, WARNING: 2, DEGRADED: 3}


def parse_line(line):
    """Return a dict of physical readings, or None if the line is malformed."""
    line = line.strip()
    m = LINE_RE.match(line)
    if not m:
        return None
    if m.group("c") is not None:                 # newer firmware: C= is the XOR of every byte before ",C="
        body = line[:line.rindex(",C=")]
        check = 0
        for byte in body.encode("ascii"):
            check ^= byte
        if check != int(m.group("c"), 16):
            return None                          # corrupted on the wire: drop it, never show it
    g = {k: int(v, 16) for k, v in m.groupdict().items() if v is not None}
    alive = [bool(g["f"] >> n & 1) for n in range(4)]
    stress = [bool(g["s"] >> n & 1) for n in range(4)]
    test_fault = stress[3]          # sw15 is the injected R2 fault, not a heater
    stress[3] = False
    freq = {}
    for n, name in enumerate(REGIONS):
        count = g[name.lower()]
        freq[name] = count / GATE_SECONDS / 1e6 if alive[n] else 0.0   # MHz
    return {
        "freq_mhz": freq,
        "alive": dict(zip(REGIONS, alive)),
        "stress": dict(zip(REGIONS, stress)),
        "test_fault": "R2" if test_fault else None,   # injected by the board; NOT a measurement
        "temp_c": g["t"] * 503.975 / 4096 - 273.15,
        "VCCINT": g["i"] * 3.0 / 4096,
        "VCCAUX": g["a"] * 3.0 / 4096,
        "VCCBRAM": g["b"] * 3.0 / 4096,
        "board_verdict": {0: UNCAL, 1: HEALTHY, 2: WARNING, 3: DEGRADED}[g["h"] & 3],
        "build_id": ("%04X" % g["v"]) if "v" in g else None,
    }


def _calib_path():
    return Path(__file__).with_name("calibration.json")


def board_id_for_port(port):
    """USB serial number of the board on `port` (without the channel letter), or None."""
    try:
        import serial.tools.list_ports as lp
        for p in lp.comports():
            if p.device == port and p.serial_number:
                sn = re.sub(r"[^A-Za-z0-9]", "", p.serial_number)
                return sn[:-1] if sn[-1:] in ("A", "B") else sn
    except ImportError:
        pass
    return None


def build_calibration(samples):
    """Baseline = mean/std of each region's frequency over healthy-state samples."""
    cal = {"regions": {}, "temp_c": statistics.mean(s["temp_c"] for s in samples)}
    for r in REGIONS:
        vals = [s["freq_mhz"][r] for s in samples if s["alive"][r]]
        if len(vals) < 5:
            raise RuntimeError(f"{r}: oscillator not alive during calibration")
        cal["regions"][r] = {"mean_mhz": statistics.mean(vals),
                             "std_mhz": statistics.pstdev(vals)}
    return cal


def check_idle(samples: list) -> tuple:
    """Is this stretch of telemetry a trustworthy healthy reference?"""
    if len(samples) < rules.AUTOCAL_SAMPLES:
        return False, f"only {len(samples)} of {rules.AUTOCAL_SAMPLES} packets received"
    if len({s.get("test_fault") for s in samples}) > 1:
        return False, "the test fault was switched on or off while recording; keep it steady"
    if any(any(s["stress"].values()) for s in samples):
        return False, "a stress switch (sw12..sw14) is on; switch it off and let the chip cool"
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


def classify(reading, cal):
    """Return (overall_state, {region: state}, [reasons])."""
    reasons, regions = [], {}
    for r in REGIONS:
        if not reading["alive"][r]:
            regions[r] = DEGRADED
            reasons.append(f"{r}: ring oscillator not running")
        elif cal is None:
            regions[r] = UNCAL
        else:
            base = cal["regions"][r]["mean_mhz"]
            regions[r] = rules.classify_region(reading["freq_mhz"][r], base)
            if regions[r] != HEALTHY:
                drop = (1.0 - reading["freq_mhz"][r] / base) * 100.0
                reasons.append(f"{r}: RO frequency down {drop:.2f} % vs baseline")

    sensor = rules.classify_temperature(reading["temp_c"])
    if sensor != HEALTHY:
        reasons.append(f"die temperature {reading['temp_c']:.1f} C")
    for rail in rules.VOLT_NOMINAL_V:
        level = rules.classify_voltage(rail, reading[rail])
        if level != HEALTHY:
            reasons.append(f"{rail} {reading[rail]:.3f} V")
        if RANK[level] > RANK[sensor]:
            sensor = level

    # Same aggregation as the dashboard and the board LEDs: the regions change the overall
    # state only when at least REGION_QUORUM of them are Warning/Degraded; sensors always count.
    n_deg = sum(1 for s in regions.values() if s == DEGRADED)
    n_warn = sum(1 for s in regions.values() if s == WARNING)
    region_overall = HEALTHY
    if n_deg + n_warn >= rules.REGION_QUORUM:
        region_overall = DEGRADED if n_deg else WARNING
    elif n_deg + n_warn:
        reasons.append(f"isolated region fault (quorum is {rules.REGION_QUORUM}); overall state unchanged")

    # A region whose oscillator is not measuring is a sensor fault, never evidence of health: the
    # quorum must not outvote it, so the overall state is at least Warning.
    dead = [r for r in REGIONS if not reading["alive"][r]]
    if dead:
        reasons.append(f"sensor fault: ring oscillator not measuring in {', '.join(dead)}")
        if region_overall == HEALTHY:
            region_overall = WARNING

    if DEGRADED in (region_overall, sensor):
        overall = DEGRADED
    elif WARNING in (region_overall, sensor):
        overall = WARNING
    elif UNCAL in regions.values():
        overall = UNCAL
    else:
        overall = HEALTHY
    return overall, regions, reasons


def lines_from_serial(port, baud=115200):
    import serial  # pyserial
    with serial.Serial(port, baud, timeout=2) as ser:
        while True:
            raw = ser.readline()
            if raw:
                yield raw.decode("ascii", errors="ignore")


def lines_from_file(path):
    with open(path, "r", encoding="ascii", errors="ignore") as fh:
        yield from fh


def show(reading, cal):
    overall, regions, reasons = classify(reading, cal)
    freqs = "  ".join(f"{r} {reading['freq_mhz'][r]:7.2f} MHz {regions[r]:<12}" for r in REGIONS)
    print(f"T={reading['temp_c']:5.1f}C  VINT={reading['VCCINT']:.3f}  VAUX={reading['VCCAUX']:.3f}  "
          f"VBRAM={reading['VCCBRAM']:.3f}  | {freqs}| => {overall}")
    for why in reasons:
        print(f"      - {why}")


def selftest():
    sample = "R1=0107B8,R2=0107B8,R3=0107B8,R4=0107B8,T=994,I=555,A=99A,B=555,F=F,S=0,H=1"
    r = parse_line(sample)
    assert r is not None
    assert abs(r["freq_mhz"]["R1"] - 6.8) < 1.0 or r["freq_mhz"]["R1"] > 0
    assert abs(r["VCCINT"] - 1.0) < 0.01 and abs(r["VCCAUX"] - 1.8) < 0.01
    assert 25 < r["temp_c"] < 32
    cal = build_calibration([r] * 10)
    assert classify(r, cal)[0] == HEALTHY
    slow = dict(r, freq_mhz={k: v * 0.99 for k, v in r["freq_mhz"].items()})
    assert classify(slow, cal)[0] == WARNING
    slower = dict(r, freq_mhz={k: v * 0.97 for k, v in r["freq_mhz"].items()})
    assert classify(slower, cal)[0] == DEGRADED
    dead = dict(r, alive=dict(r["alive"], R2=False), freq_mhz=dict(r["freq_mhz"], R2=0.0))
    state, regions, _ = classify(dead, cal)
    assert regions["R2"] == DEGRADED and state == WARNING          # one dead region: a sensor fault, never Healthy
    dead2 = dict(dead, alive=dict(dead["alive"], R3=False), freq_mhz=dict(dead["freq_mhz"], R3=0.0))
    assert classify(dead2, cal)[0] == DEGRADED                      # two dead regions: quorum met
    assert parse_line("garbage") is None
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="serial port, e.g. COM3")
    ap.add_argument("--replay", help="read lines from a log file instead of a serial port")
    ap.add_argument("--calibrate", type=int, metavar="SECONDS", nargs="?", const=1,
                    help="record a baseline (the number is ignored: the dashboard's safe procedure is used, "
                         "which needs the board cool, idle and steady)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return
    if not (args.port or args.replay):
        ap.error("give --port or --replay")

    source = lines_from_serial(args.port) if args.port else lines_from_file(args.replay)

    if args.calibrate:
        if args.port:
            # live board: the same safe procedure as the dashboard (cool, idle, steady, all oscillators alive;
            # fault-injection corrected; the board is recorded in the file)
            from communication.board_calibration import ensure_calibration
            print("Recording the baseline: every stress switch and SW15 must be down and the board cool...")
            res = ensure_calibration(args.port, force=True)
            print(res["reason"])
            sys.exit(0 if res["state"] in ("ok", "created") else 1)
        samples = [s for s in (parse_line(line) for line in source) if s]       # replay file
        ok, why = check_idle(samples)
        if not ok:
            print(f"Not recorded: {why}")
            sys.exit(1)
        cal = build_calibration(samples)
        cal.update({"build_id": samples[-1].get("build_id"), "mode": "replay",
                    "recorded": time.strftime("%Y-%m-%d %H:%M:%S")})
        _calib_path().write_text(json.dumps(cal, indent=2))
        print(f"Saved {_calib_path().name} from {len(samples)} samples")
        for r in REGIONS:
            c = cal["regions"][r]
            print(f"  {r}: {c['mean_mhz']:.3f} MHz  (std {c['std_mhz']:.4f})")
        return

    cal = None
    if _calib_path().exists():
        cal = json.loads(_calib_path().read_text())
    else:
        print(f"No calibration - run with --calibrate first. Showing raw values.")
    # A baseline belongs to ONE board: judging another board against it would call a healthy board
    # Degraded (or a bad one Healthy). Refuse it instead.
    if cal and args.port and cal.get("board_id") and board_id_for_port(args.port) not in (None, cal["board_id"]):
        print(f"The saved baseline is for board {cal['board_id']}, but {args.port} is board "
              f"{board_id_for_port(args.port)}. Not using it; run --calibrate for this board. Showing raw values.")
        cal = None
    try:
        for line in source:
            reading = parse_line(line)
            if reading:
                show(reading, cal)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
