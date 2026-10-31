import os
os.environ["FPGA_CALIBRATION"] = "none"   # tests use the placeholder nominal, never a board calibration
"""
Safety behaviour of the serial receiver and the limits: nothing may leave a stale or invalid
reading on screen as "live", and a dead sensor must never read as healthy.
"""

import unittest

import health_rules as rules
from communication.uart_receiver import ConnectionState, FPGAUARTReceiver
from dashboard.config import LimitSeverity, evaluate_engineering_limits
from hardware.host.health_reader import parse_line

GOOD = "R1=4296E0,R2=427F70,R3=428B28,R4=428358,T=A07,I=54E,A=99C,B=550,F=F,S=0,H=0,V=896F"
DEAD_R1 = "R1=000000,R2=427F70,R3=428B28,R4=428358,T=A07,I=54E,A=99C,B=550,F=E,S=0,H=0,V=896F"
VCCINT_COLLAPSED = "R1=4296E0,R2=427F70,R3=428B28,R4=428358,T=A07,I=000,A=99C,B=550,F=F,S=0,H=0,V=896F"
HOT = "R1=4296E0,R2=427F70,R3=428B28,R4=428358,T=FFF,I=54E,A=99C,B=550,F=F,S=0,H=0,V=896F"


class FakeSerial:
    """Just enough of pyserial for read_packet()."""
    is_open = True

    def __init__(self, lines):
        self.lines = [(l + "\r\n").encode() for l in lines]

    @property
    def in_waiting(self):
        return 1 if self.lines else 0

    def readline(self):
        return self.lines.pop(0) if self.lines else b""

    def close(self):
        self.is_open = False


def receiver_with(lines):
    rcv = FPGAUARTReceiver(port="COMTEST")
    rcv.serial_conn = FakeSerial(lines)
    rcv.state = ConnectionState.PORT_OPEN_WAITING
    return rcv


class TestStaleAndHello(unittest.TestCase):
    def test_hello_line_is_not_telemetry(self):
        rcv = receiver_with(["HELLO FPGA"])
        pkt = rcv.read_packet()
        self.assertEqual(pkt["packet_type"], "HANDSHAKE")
        self.assertEqual(rcv.packet_count, 0)
        self.assertEqual(rcv.last_packet_time, 0.0)
        self.assertFalse(rcv.is_streaming)
        self.assertNotEqual(rcv.state, ConnectionState.RECEIVING_TELEMETRY)
        self.assertIn("sw[0]", rcv.last_error_msg)

    def test_telemetry_is_streaming_then_stale_when_it_stops(self):
        rcv = receiver_with([GOOD])
        self.assertIsNotNone(rcv.read_packet())
        self.assertTrue(rcv.is_streaming)
        self.assertFalse(rcv.is_stale)
        rcv.last_packet_time -= rcv.stale_threshold_sec + 5          # silence for longer than the threshold
        self.assertTrue(rcv.is_stale)
        self.assertFalse(rcv.is_streaming)
        self.assertGreater(rcv.data_age_s, rcv.stale_threshold_sec)

    def test_no_packets_yet_is_not_called_stale(self):
        self.assertFalse(receiver_with([]).is_stale)

    def test_build_id_is_remembered(self):
        rcv = receiver_with([GOOD])
        rcv.read_packet()
        self.assertEqual(rcv.last_build_id, "896F")


class TestBadReadingsAreNotHidden(unittest.TestCase):
    def setUp(self):
        self.rcv = FPGAUARTReceiver(port="COMTEST")

    def test_collapsed_core_supply_reaches_the_limits(self):
        d = self.rcv._parse_raw_line(VCCINT_COLLAPSED)
        self.assertIsNotNone(d, "an out-of-range reading must not be silently dropped")
        a = evaluate_engineering_limits(d, provenance_map=d["Provenance"])
        self.assertIn(a.max_severity, (LimitSeverity.CRITICAL, LimitSeverity.PHYSICALLY_INVALID))

    def test_impossible_temperature_reaches_the_limits(self):
        d = self.rcv._parse_raw_line(HOT)
        self.assertIsNotNone(d)
        a = evaluate_engineering_limits(d, provenance_map=d["Provenance"])
        self.assertIn(a.max_severity, (LimitSeverity.CRITICAL, LimitSeverity.PHYSICALLY_INVALID))


class TestDeadSensorIsNeverHealthy(unittest.TestCase):
    def test_dashboard_limits_flag_a_single_dead_oscillator(self):
        rcv = FPGAUARTReceiver(port="COMTEST")
        d = rcv._parse_raw_line(DEAD_R1)
        baselines = {f"RO_{r}": rules.RO_PLACEHOLDER_NOMINAL_MHZ for r in rules.REGIONS}
        a = evaluate_engineering_limits(d, provenance_map=d["Provenance"], regional_baselines=baselines)
        self.assertEqual(a.max_severity, LimitSeverity.WARNING)
        self.assertTrue(any("Sensor fault" in r for r in a.override_reasons), a.override_reasons)

    def test_host_reader_flags_a_single_dead_oscillator(self):
        from hardware.host import health_reader as hr
        cal = {"regions": {r: {"mean_mhz": 436.0, "std_mhz": 0.05} for r in rules.REGIONS}}
        state, regions, reasons = hr.classify(parse_line(DEAD_R1), cal)
        self.assertEqual(regions["R1"], hr.DEGRADED)
        self.assertEqual(state, hr.WARNING)
        self.assertTrue(any("sensor fault" in r for r in reasons))


if __name__ == "__main__":
    unittest.main()
