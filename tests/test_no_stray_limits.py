import os
os.environ["FPGA_BOARD"] = "none"   # tests use the placeholder nominal, never a board calibration
"""
Guard: the old limits of the original design (412.0 / 422.9 MHz and their delays) must not come
back anywhere in the application code. Every limit lives in health_rules.py; a literal copy
elsewhere silently drifts away from it. (tests/ and mock data are allowed to use numbers.)
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIRS = ["dashboard", "agent", "communication", "hardware", "mock", "ml"]
OLD_LIMITS = re.compile(r"(?<![\d.])(412\.0|422\.9|0\.2365|0\.2427)(?![\d])")


def app_python_files():
    yield ROOT / "config.py"
    for d in APP_DIRS:
        yield from (ROOT / d).rglob("*.py")


class TestNoStrayLimits(unittest.TestCase):
    def test_old_limits_do_not_reappear(self):
        offenders = []
        for path in app_python_files():
            for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if OLD_LIMITS.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
        self.assertEqual(offenders, [], "limit literals must come from health_rules.py:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
