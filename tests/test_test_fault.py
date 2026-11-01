import os
os.environ["FPGA_CALIBRATION"] = "none"   # tests use the placeholder nominal, never a board calibration
"""
SW15 on the board injects a fault into R2's reading (a demo of a single bad region). The packet
flags it in S bit 3, so the host must report it as a test fault, never as a heater, and must not
record a baseline while it is on.
"""

import unittest

from communication import board_calibration as bc
from communication.uart_receiver import FPGAUARTReceiver
from hardware.host.health_reader import parse_line
from tests.test_board_calibration import steady_samples

LINE = "R1=3180E8,R2=3C34B6,R3=436C92,R4=46D74A,T=A07,I=54E,A=99C,B=550,F=F,S={s},H=0,V=1A2B"


class TestTestFault(unittest.TestCase):
    def test_sw15_is_a_test_fault_not_an_r4_heater(self):
        p = parse_line(LINE.format(s="8"))
        self.assertEqual(p["test_fault"], "R2")
        self.assertFalse(any(p["stress"].values()))

    def test_heater_switches_are_still_stress(self):
        p = parse_line(LINE.format(s="5"))
        self.assertIsNone(p["test_fault"])
        self.assertEqual([r for r, on in p["stress"].items() if on], ["R1", "R3"])

    def test_no_switch_means_no_fault(self):
        self.assertIsNone(parse_line(LINE.format(s="0"))["test_fault"])

    def test_a_steady_fault_does_not_block_the_baseline(self):
        ok, _ = bc.check_idle(steady_samples(test_fault="R2"))
        self.assertTrue(ok)

    def test_a_fault_switched_during_recording_is_refused(self):
        samples = steady_samples()
        for s in samples[:5]:
            s["test_fault"] = "R2"
        ok, why = bc.check_idle(samples)
        self.assertFalse(ok)
        self.assertIn("test fault", why)

    def test_baseline_taken_with_the_fault_on_is_the_true_baseline(self):
        import copy, json, tempfile
        from pathlib import Path
        from unittest import mock
        import health_rules as rules
        clean = steady_samples()
        faulty = copy.deepcopy(clean)
        k = 1.0 - 2.0 ** -rules.TEST_FAULT_SHIFT
        for s in faulty:
            s["freq_mhz"]["R2"] *= k              # what the board reports with the fault injected
            s["test_fault"] = "R2"
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(bc, "CAL_FILE", Path(tmp) / "calibration.json"), \
                mock.patch.object(bc, "board_id_for_port", return_value="B"), \
                mock.patch.object(bc, "read_packets", return_value=faulty):
            self.assertEqual(bc.ensure_calibration("COM99")["state"], "created")
            cal = json.loads((Path(tmp) / "calibration.json").read_text())
        true_r2 = sum(s["freq_mhz"]["R2"] for s in clean) / len(clean)
        self.assertAlmostEqual(cal["regions"]["R2"]["mean_mhz"], true_r2, delta=true_r2 * 1e-6)
        self.assertEqual(cal["test_fault_compensated"], "R2")

    def test_receiver_exposes_the_flag_and_leaves_the_readings_alone(self):
        rcv = FPGAUARTReceiver()
        d = rcv._hex_packet_to_dict(LINE.format(s="8"))
        self.assertEqual(rcv.last_test_fault, "R2")
        self.assertNotIn("Test_Fault", d)                      # telemetry channels are untouched
        rcv._hex_packet_to_dict(LINE.format(s="0"))
        self.assertIsNone(rcv.last_test_fault)


if __name__ == "__main__":
    unittest.main()