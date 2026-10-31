import os
os.environ["FPGA_CALIBRATION"] = "none"   # tests use the placeholder nominal, never a board calibration
"""
Tests for the automatic per-board / per-build baseline (communication/board_calibration.py).
Serial access is replaced by canned packets; files go to a temporary folder.
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import health_rules as rules
from communication import board_calibration as bc
from hardware.host.health_reader import parse_line

LINE = "R1=3180E8,R2=3C34B6,R3=436C92,R4=46D74A,T=A07,I=54E,A=99C,B=550,F=F,S=0,H=0,V=1A2B"


def steady_samples(n=None, **override):
    base = parse_line(LINE)
    samples = []
    for i in range(n or rules.AUTOCAL_SAMPLES):
        s = copy.deepcopy(base)
        for r in s["freq_mhz"]:
            s["freq_mhz"][r] *= 1.0 + 0.00005 * ((i % 3) - 1)      # +/-0.005 % jitter
        samples.append(s)
    for key, value in override.items():
        for s in samples:
            s[key] = value
    return samples


class TestParsing(unittest.TestCase):
    def test_build_id_is_parsed(self):
        self.assertEqual(parse_line(LINE)["build_id"], "1A2B")

    def test_old_packets_without_build_id_still_parse(self):
        p = parse_line(LINE.rsplit(",V=", 1)[0])
        self.assertIsNotNone(p)
        self.assertIsNone(p["build_id"])


class TestIdleCheck(unittest.TestCase):
    def test_cool_idle_steady_board_is_accepted(self):
        ok, why = bc.check_idle(steady_samples())
        self.assertTrue(ok, why)

    def test_too_few_packets(self):
        self.assertFalse(bc.check_idle(steady_samples(n=5))[0])

    def test_stress_switch_blocks_it(self):
        ok, why = bc.check_idle(steady_samples(stress={"R1": True, "R2": False, "R3": False, "R4": False}))
        self.assertFalse(ok)
        self.assertIn("stress", why)

    def test_dead_oscillator_blocks_it(self):
        ok, why = bc.check_idle(steady_samples(alive={"R1": True, "R2": False, "R3": True, "R4": True}))
        self.assertFalse(ok)
        self.assertIn("not running", why)

    def test_warm_board_blocks_it(self):
        ok, why = bc.check_idle(steady_samples(temp_c=rules.TEMP_AUTOCAL_MAX_C + 3.0))
        self.assertFalse(ok)
        self.assertIn("warm", why)

    def test_unsteady_frequency_blocks_it(self):
        samples = steady_samples()
        for i, s in enumerate(samples):
            s["freq_mhz"]["R2"] *= 1.0 + 0.01 * (i % 2)               # 1 % flapping
        ok, why = bc.check_idle(samples)
        self.assertFalse(ok)
        self.assertIn("R2", why)


class TestEnsureCalibration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        host = Path(self.tmp.name)
        patches = [
            mock.patch.object(bc, "HOST_DIR", host),
            mock.patch.object(bc, "CAL_FILE", host / "calibration.json"),
            mock.patch.object(bc, "board_id_for_port", return_value="BOARD1"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.host = host
        self.cal_file = host / "calibration.json"

    def run_ensure(self, samples, force=False):
        with mock.patch.object(bc, "read_packets", return_value=samples):
            return bc.ensure_calibration("COM99", force=force)

    def test_first_plug_in_records_a_baseline(self):
        res = self.run_ensure(steady_samples())
        self.assertEqual(res["state"], "created")
        self.assertEqual(res["board_id"], "BOARD1")
        cal = json.loads(self.cal_file.read_text())
        self.assertEqual(cal["build_id"], "1A2B")
        self.assertEqual(cal["mode"], "automatic")
        self.assertTrue(self.cal_file.exists())

    def test_hot_board_records_nothing(self):
        res = self.run_ensure(steady_samples(temp_c=60.0))
        self.assertEqual(res["state"], "waiting")
        self.assertFalse(self.cal_file.exists())

    def test_matching_baseline_is_reused_even_when_warm(self):
        self.run_ensure(steady_samples())
        res = self.run_ensure(steady_samples(temp_c=60.0))
        self.assertEqual(res["state"], "ok")
        self.assertTrue(self.cal_file.exists())

    def test_baseline_from_another_build_is_not_used(self):
        self.run_ensure(steady_samples())
        newer = steady_samples(build_id="FFFF", temp_c=60.0)           # new build, board warm
        res = self.run_ensure(newer)
        self.assertEqual(res["state"], "waiting")
        self.assertFalse(self.cal_file.exists())   # stale baseline switched off

    def test_new_build_on_a_cool_board_gets_a_fresh_baseline(self):
        self.run_ensure(steady_samples())
        res = self.run_ensure(steady_samples(build_id="FFFF"))
        self.assertEqual(res["state"], "created")
        cal = json.loads(self.cal_file.read_text())
        self.assertEqual(cal["build_id"], "FFFF")

    def test_failed_forced_recalibration_keeps_the_working_baseline(self):
        self.run_ensure(steady_samples())
        res = self.run_ensure(steady_samples(temp_c=60.0), force=True)
        self.assertEqual(res["state"], "waiting")
        self.assertTrue(self.cal_file.exists())

    def test_a_different_board_gets_its_own_fresh_baseline(self):
        self.run_ensure(steady_samples())
        with mock.patch.object(bc, "board_id_for_port", return_value="BOARD2"):
            res = self.run_ensure(steady_samples(temp_c=60.0))       # other board, warm: cannot reuse BOARD1's
        self.assertEqual(res["state"], "waiting")
        self.assertFalse(self.cal_file.exists())
        with mock.patch.object(bc, "board_id_for_port", return_value="BOARD2"):
            res = self.run_ensure(steady_samples())
        self.assertEqual(res["state"], "created")
        self.assertEqual(json.loads(self.cal_file.read_text())["board_id"], "BOARD2")

    def test_no_packets_is_reported_not_raised(self):
        self.assertEqual(self.run_ensure([])["state"], "error")

    def test_unreadable_port_is_reported_not_raised(self):
        with mock.patch.object(bc, "read_packets", side_effect=OSError("port busy")):
            res = bc.ensure_calibration("COM99")
        self.assertEqual(res["state"], "error")
        self.assertIn("port busy", res["reason"])


if __name__ == "__main__":
    unittest.main()
