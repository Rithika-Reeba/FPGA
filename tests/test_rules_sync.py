"""
Keeps the on-board LED limits (hardware/rtl/fpga_health_top.v) in step with the
single source of truth (health_rules.py). If someone changes a limit in one place
and not the other, this test fails.

XADC raw codes in the RTL are rounded integers, so a +/-1 code tolerance (about
0.7 mV or 0.12 degC) is allowed.
"""

import os
os.environ["FPGA_CALIBRATION"] = "none"   # tests use the placeholder nominal, never a board calibration
import math
import re
import unittest
from pathlib import Path

import health_rules as rules

RTL = Path(__file__).resolve().parent.parent / "hardware" / "rtl" / "fpga_health_top.v"


def _rtl_value(name: str) -> int:
    text = RTL.read_text(encoding="utf-8")
    m = re.search(rf"\b{name}\s*=\s*(?:12'd)?(\d+)", text)
    if not m:
        raise AssertionError(f"{name} not found in {RTL.name}")
    return int(m.group(1))


class TestRtlMatchesRules(unittest.TestCase):

    def assertCodeNear(self, name, expected):
        actual = _rtl_value(name)
        self.assertLessEqual(abs(actual - expected), 1, f"{name}: RTL {actual} vs rules {expected}")

    def test_temperature_codes(self):
        self.assertCodeNear("T_WARN", rules.temp_code(rules.TEMP_WARN_C))
        self.assertCodeNear("T_DEG", rules.temp_code(rules.TEMP_CRIT_C))
        self.assertCodeNear("T_STRESS_ON", rules.temp_code(rules.TEMP_STRESS_RESUME_C))
        self.assertCodeNear("T_CAL_MAX", rules.temp_code(rules.TEMP_AUTOCAL_MAX_C))

    def test_vccint_and_vccbram_codes(self):
        lim = rules.volt_limits("VCCINT")
        self.assertCodeNear("VI_WARN_LO", rules.volt_code(lim["warn_low"]))
        self.assertCodeNear("VI_WARN_HI", rules.volt_code(lim["warn_high"]))
        self.assertCodeNear("VI_DEG_LO", rules.volt_code(lim["crit_low"]))
        self.assertCodeNear("VI_DEG_HI", rules.volt_code(lim["crit_high"]))
        self.assertEqual(rules.volt_limits("VCCBRAM"), lim)   # the RTL reuses VI_* for VCCBRAM

    def test_vccaux_codes(self):
        lim = rules.volt_limits("VCCAUX")
        self.assertCodeNear("VA_WARN_LO", rules.volt_code(lim["warn_low"]))
        self.assertCodeNear("VA_WARN_HI", rules.volt_code(lim["warn_high"]))
        self.assertCodeNear("VA_DEG_LO", rules.volt_code(lim["crit_low"]))
        self.assertCodeNear("VA_DEG_HI", rules.volt_code(lim["crit_high"]))

    def test_ro_drop_shifts(self):
        # the RTL computes "base >> SHIFT", i.e. a drop of 100 / 2**SHIFT percent
        self.assertAlmostEqual(100.0 / 2 ** _rtl_value("WARN_SHIFT"), rules.RO_WARN_DROP_PCT, places=6)
        self.assertAlmostEqual(100.0 / 2 ** _rtl_value("DEG_SHIFT"), rules.RO_CRIT_DROP_PCT, places=6)

    def test_region_quorum(self):
        self.assertEqual(_rtl_value("REGION_QUORUM"), rules.REGION_QUORUM)


class TestSingleSourceOfTruth(unittest.TestCase):

    def test_dashboard_config_uses_rules(self):
        from dashboard.config import REGIONAL_CONFIG, SENSOR_CONFIG, REGION_QUORUM
        self.assertEqual(REGION_QUORUM, rules.REGION_QUORUM)
        for r_id, meta in REGIONAL_CONFIG.items():
            lim = rules.ro_limits(rules.region_nominal_mhz(r_id))
            self.assertAlmostEqual(meta["warning_freq"], lim["warn_low"], places=2)
            self.assertAlmostEqual(meta["critical_freq"], lim["crit_low"], places=2)
        self.assertEqual(SENSOR_CONFIG["Temperature"]["warning_high"], rules.TEMP_WARN_C)
        self.assertEqual(SENSOR_CONFIG["Temperature"]["critical_high"], rules.TEMP_CRIT_C)
        for rail in rules.VOLT_NOMINAL_V:
            lim = rules.volt_limits(rail)
            self.assertAlmostEqual(SENSOR_CONFIG[rail]["critical_low"], lim["crit_low"], places=4)
            self.assertAlmostEqual(SENSOR_CONFIG[rail]["critical_high"], lim["crit_high"], places=4)

    def test_limits_survive_streamlit_import_order(self):
        """When Streamlit runs dashboard/app.py the dashboard folder is first on sys.path, so
        `import config` resolves to dashboard/config.py. The limits must still match the rules."""
        import json
        import os
        import subprocess
        import sys
        root = Path(__file__).resolve().parent.parent
        code = (
            "import sys, json, warnings; warnings.filterwarnings('ignore'); "
            f"sys.path.insert(0, r'{root / 'dashboard'}'); import config; "
            "print(json.dumps([config.RO_FREQ_NOMINAL_MHZ, config.RO_FREQ_WARNING_LOW_MHZ, config.RO_FREQ_CRITICAL_LOW_MHZ]))"
        )
        env = dict(os.environ, FPGA_CALIBRATION="none")
        out = subprocess.run([sys.executable, "-c", code], cwd=root, env=env,
                             capture_output=True, text=True, timeout=60).stdout.strip().splitlines()[-1]
        nominal, warn, crit = json.loads(out)
        lim = rules.ro_limits(rules.global_nominal_mhz())
        self.assertAlmostEqual(nominal, lim["nominal"], places=6)
        self.assertAlmostEqual(warn, lim["warn_low"], places=6)
        self.assertAlmostEqual(crit, lim["crit_low"], places=6)

    def test_mock_labels_follow_rules(self):
        import pandas as pd
        csv = Path(__file__).resolve().parent.parent / "data" / "raw" / "mock_fpga_data.csv"
        df = pd.read_csv(csv)
        nominal = rules.RO_PLACEHOLDER_NOMINAL_MHZ
        for _, row in df.iloc[::250].iterrows():
            expected = rules.worst_state([
                rules.classify_region(row["RO_Frequency"], nominal),
                rules.classify_temperature(row["Temperature"]),
                rules.classify_voltage("VCCINT", row["VCCINT"]),
                rules.classify_voltage("VCCAUX", row["VCCAUX"]),
                rules.classify_voltage("VCCBRAM", row["VCCBRAM"]),
                rules.classify_error_rate(row["Error_Rate"]),
            ])
            self.assertEqual(row["Health"], expected, f"sample {int(row['Timestamp'])}")

    def test_classifiers_agree_at_the_boundaries(self):
        nom = 436.0
        self.assertEqual(rules.classify_region(nom, nom), rules.HEALTHY)
        self.assertEqual(rules.classify_region(nom * (1 - (rules.RO_WARN_DROP_PCT + 0.01) / 100), nom), rules.WARNING)
        self.assertEqual(rules.classify_region(nom * (1 - (rules.RO_CRIT_DROP_PCT + 0.01) / 100), nom), rules.DEGRADED)
        self.assertEqual(rules.classify_region(0.0, nom, alive=False), rules.DEGRADED)
        self.assertEqual(rules.classify_temperature(rules.TEMP_WARN_C), rules.WARNING)
        self.assertEqual(rules.classify_temperature(rules.TEMP_CRIT_C), rules.DEGRADED)
        self.assertTrue(math.isclose(rules.global_nominal_mhz(), sum(
            rules.REGION_WEIGHTS[r] * rules.region_nominal_mhz(r) for r in rules.REGIONS)))


if __name__ == "__main__":
    unittest.main()
