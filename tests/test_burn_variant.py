import os
os.environ["FPGA_CALIBRATION"] = "none"   # tests use the placeholder nominal, never a board calibration
"""
The dashboard's Test mode toggle chooses which design the Burn buttons write: the normal one, or the demo design
with the R2 fault. The two must never be mixed up, and each picks the newest build of its own kind.
"""

import os as _os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hardware import flash_manager as fm


class TestDesignChoice(unittest.TestCase):
    def test_fault_and_normal_use_different_files(self):
        self.assertTrue(set(map(str, fm.FAULT_BITSTREAMS)).isdisjoint(set(map(str, fm.NORMAL_BITSTREAMS))))
        self.assertIn("build_fault", str(fm.FAULT_BITSTREAMS[0]))

    def test_the_newest_build_of_the_chosen_kind_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, new, other = Path(tmp, "old.bit"), Path(tmp, "new.bit"), Path(tmp, "normal.bit")
            for f in (old, new, other):
                f.write_bytes(b"x")
            _os.utime(old, (time.time() - 100, time.time() - 100))
            with mock.patch.object(fm, "FAULT_BITSTREAMS", [old, new]), mock.patch.object(fm, "NORMAL_BITSTREAMS", [other]):
                self.assertEqual(fm.get_bitstream_path(fault=True), new)
                self.assertEqual(fm.get_bitstream_path(fault=False), other)

    def test_a_missing_design_falls_back_to_its_first_candidate_not_the_other_kind(self):
        with mock.patch.object(fm, "FAULT_BITSTREAMS", [Path("Z:/none_a.bit"), Path("Z:/none_b.bit")]):
            self.assertEqual(fm.get_bitstream_path(fault=True), Path("Z:/none_a.bit"))


if __name__ == "__main__":
    unittest.main()