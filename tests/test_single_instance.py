import os
os.environ["FPGA_CALIBRATION"] = "none"   # tests use the placeholder nominal, never a board calibration
"""
Only one dashboard tab is active at a time and the newest one has priority (dashboard/single_instance.py).
"""

import sys
import unittest

from dashboard import single_instance as one


class TestSingleActiveTab(unittest.TestCase):
    def setUp(self):
        self._saved = getattr(sys, "_fpga_active_session", None)
        sys._fpga_active_session = None
        self.addCleanup(lambda: setattr(sys, "_fpga_active_session", self._saved))

    def test_nobody_is_superseded_before_any_tab_exists(self):
        self.assertTrue(one.is_active("A"))

    def test_the_newest_tab_has_priority(self):
        one.claim("A")
        one.claim("B")
        self.assertTrue(one.is_active("B"))
        self.assertFalse(one.is_active("A"))

    def test_an_older_tab_can_take_priority_back_on_purpose(self):
        one.claim("A")
        one.claim("B")
        one.claim("A")
        self.assertTrue(one.is_active("A"))
        self.assertFalse(one.is_active("B"))

    def test_exactly_one_tab_is_active_among_many(self):
        for s in ("A", "B", "C", "D"):
            one.claim(s)
        self.assertEqual([s for s in ("A", "B", "C", "D") if one.is_active(s)], ["D"])

    def test_the_registry_survives_a_module_reload(self):
        import importlib
        one.claim("A")
        importlib.reload(one)
        self.assertTrue(one.is_active("A"))
        self.assertFalse(one.is_active("B"))

    def test_release_only_forgets_the_owner(self):
        one.claim("A")
        one.release("B")
        self.assertTrue(one.is_active("A") and not one.is_active("B"))
        one.release("A")
        self.assertTrue(one.is_active("B"))        # nobody recorded: nobody is superseded


if __name__ == "__main__":
    unittest.main()