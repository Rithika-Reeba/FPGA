import os
os.environ["FPGA_BOARD"] = "none"   # tests use the placeholder nominal, never a board calibration
"""
End-to-end checks for the real-board path: hex packet -> dashboard telemetry -> engineering limits.
"""

import unittest

import health_rules as rules
from communication.uart_receiver import FPGAUARTReceiver
from dashboard.config import LimitSeverity, evaluate_engineering_limits

#   R1=436.4  R2=435.8  R3=436.1  R4=435.9 MHz  (near the 436 MHz placeholder nominal used by the tests)
LINE = "R1=4296E0,R2=427F70,R3=428B28,R4=428358,T=A07,I=54E,A=99C,B=550,F=F,S=0,H=0,V=896F"
DEAD_R1 = "R1=000000,R2=427F70,R3=428B28,R4=428358,T=A07,I=54E,A=99C,B=550,F=E,S=0,H=0,V=896F"


class TestHexPipeline(unittest.TestCase):
    def setUp(self):
        self.rcv = FPGAUARTReceiver()

    def test_regions_are_converted_to_mhz(self):
        d = self.rcv._parse_raw_line(LINE)
        self.assertAlmostEqual(d["RO_R1"], 436.4, delta=0.1)
        self.assertAlmostEqual(d["RO_R2"], 435.8, delta=0.1)

    def test_aggregate_is_the_weighted_average(self):
        d = self.rcv._parse_raw_line(LINE)
        w = rules.REGION_WEIGHTS
        expected = sum(w[r] * d[f"RO_{r}"] for r in rules.REGIONS)
        self.assertAlmostEqual(d["RO_Frequency"], expected, delta=0.02)

    def test_error_rate_is_marked_simulated(self):
        d = self.rcv._parse_raw_line(LINE)
        self.assertEqual(d["Provenance"]["Error_Rate"], "SIMULATED")

    def test_dead_oscillator_reaches_the_dashboard_as_zero(self):
        d = self.rcv._parse_raw_line(DEAD_R1)
        self.assertEqual(d["RO_R1"], 0.0)

    def test_healthy_regions_are_not_overridden_by_the_aggregate(self):
        """Regression: with regional data present and every region at its own baseline, a
        low aggregate value must NOT raise a Warning by itself (the regions govern)."""
        d = self.rcv._parse_raw_line(LINE)
        baselines = {f"RO_{r}": d[f"RO_{r}"] for r in rules.REGIONS}
        telemetry = dict(d, RO_Frequency=420.0, RO_Delay_ns=round(100.0 / 420.0, 4))   # -3.7 % aggregate
        a = evaluate_engineering_limits(telemetry, provenance_map=d["Provenance"], regional_baselines=baselines)
        self.assertEqual(a.max_severity, LimitSeverity.NORMAL, a.primary_reason)

    def test_a_dead_region_is_still_reported_but_quorum_decides_the_overall_state(self):
        d = self.rcv._parse_raw_line(DEAD_R1)
        baselines = {"RO_R1": 436.4, "RO_R2": 435.8, "RO_R3": 436.1, "RO_R4": 435.9}
        a = evaluate_engineering_limits(d, provenance_map=d["Provenance"], regional_baselines=baselines)
        self.assertIn("R1", a.degraded_pblocks)
        # one bad region does not meet the quorum of 2, but a dead sensor is a fault, never Healthy
        self.assertEqual(a.max_severity, LimitSeverity.WARNING)


if __name__ == "__main__":
    unittest.main()
