import os
os.environ["FPGA_CALIBRATION"] = "none"   # tests use the placeholder nominal, never a board calibration
"""
`health_reader.py --calibrate` used to crash on an empty read and to accept a hot or stressed board as the healthy
reference. It must now refuse those, and write nothing, exactly like the dashboard's automatic baseline.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hardware.host import health_reader as hr

GOOD = "R1=4B6AFA,R2=45E072,R3=45E072,R4=490162,T=A01,I=556,A=998,B=556,F=F,S=0,H=0,V=AAAA"
HOT = GOOD.replace("T=A01", "T=B30")                    # about 79 C
STRESSED = GOOD.replace("S=0", "S=1")                   # a heater switch is up


class TestCalibrateCli(unittest.TestCase):
    def run_cli(self, lines):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp, "log.txt")
            log.write_text("\n".join(lines) + "\n")
            out = Path(tmp, "calibration.json")
            with mock.patch.object(hr, "_calib_path", lambda: out), \
                    mock.patch.object(sys, "argv", ["health_reader.py", "--replay", str(log), "--calibrate"]):
                try:
                    hr.main()
                    code = 0
                except SystemExit as exc:
                    code = exc.code or 0
            return code, (json.loads(out.read_text()) if out.exists() else None)

    def test_an_empty_read_is_refused_without_crashing(self):
        code, cal = self.run_cli([])
        self.assertEqual(code, 1)
        self.assertIsNone(cal)

    def test_garbage_only_is_refused(self):
        code, cal = self.run_cli(["garbage"] * 30)
        self.assertEqual(code, 1)
        self.assertIsNone(cal)

    def test_a_hot_board_is_not_recorded(self):
        code, cal = self.run_cli([HOT] * 25)
        self.assertEqual(code, 1)
        self.assertIsNone(cal)

    def test_a_stressed_board_is_not_recorded(self):
        code, cal = self.run_cli([STRESSED] * 25)
        self.assertEqual(code, 1)
        self.assertIsNone(cal)

    def test_too_few_samples_are_refused(self):
        code, cal = self.run_cli([GOOD] * 3)
        self.assertEqual(code, 1)
        self.assertIsNone(cal)

    def test_a_cool_idle_board_is_recorded(self):
        code, cal = self.run_cli([GOOD] * 25)
        self.assertEqual(code, 0)
        self.assertEqual(cal["build_id"], "AAAA")
        self.assertAlmostEqual(cal["regions"]["R1"]["mean_mhz"], 0x4B6AFA / 10000, places=3)


if __name__ == "__main__":
    unittest.main()