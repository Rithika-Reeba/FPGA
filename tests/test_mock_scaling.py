import os
os.environ["FPGA_CALIBRATION"] = "none"   # tests use the placeholder nominal, never a board calibration
"""
The mock CSV is generated around the placeholder nominal. When a board is calibrated the replay
is rescaled to that board's baseline. It must be rescaled exactly ONCE (a duplicated block once
scaled it twice, which made the mock 'Healthy' sample read +20 % and flagged Degraded).
"""

import unittest
from unittest import mock

import pandas as pd

import health_rules as rules
from dashboard import data_source as ds

FAKE_NOMINALS = {"R1": 495.0, "R2": 459.0, "R3": 459.0, "R4": 479.0}      # a board with its own baselines
FAKE_GLOBAL = sum(rules.REGION_WEIGHTS[r] * FAKE_NOMINALS[r] for r in FAKE_NOMINALS)


class TestMockScaling(unittest.TestCase):
    def raw(self):
        return pd.read_csv(ds.DEFAULT_CSV_PATH)

    def test_without_calibration_the_csv_is_left_alone(self):
        src = ds.MockCSVDataSource()
        raw = self.raw()
        self.assertAlmostEqual(src.raw_df["RO_Frequency"].iloc[1000], raw["RO_Frequency"].iloc[1000], places=3)

    def test_with_calibration_the_csv_is_scaled_exactly_once(self):
        with mock.patch.object(ds, "_NOM", FAKE_GLOBAL), \
             mock.patch.object(ds, "_nom", lambda r: FAKE_NOMINALS[r]):
            src = ds.MockCSVDataSource()
        raw = self.raw()
        ratio = FAKE_GLOBAL / rules.RO_PLACEHOLDER_NOMINAL_MHZ
        self.assertAlmostEqual(src.raw_df["RO_Frequency"].iloc[1000] / raw["RO_Frequency"].iloc[1000], ratio, places=3)
        # a region is scaled by ITS OWN nominal (not by the global one)
        r1_ratio = src.raw_df["RO_R1"].iloc[1000] / (raw["RO_Frequency"].iloc[1000] + 0.3)
        self.assertAlmostEqual(r1_ratio, FAKE_NOMINALS["R1"] / rules.RO_PLACEHOLDER_NOMINAL_MHZ, places=2)

    def test_healthy_mock_sample_stays_healthy_on_a_calibrated_board(self):
        with mock.patch.object(ds, "_NOM", FAKE_GLOBAL), \
             mock.patch.object(ds, "_nom", lambda r: FAKE_NOMINALS[r]):
            src = ds.MockCSVDataSource()
            _, latest, meta = src.get_data(150, 1000)               # the dashboard's "Healthy" preset
        for r, nominal in FAKE_NOMINALS.items():                    # regions sit at ~their own baseline
            self.assertLess(abs(latest[f"RO_{r}"] / nominal - 1.0), 0.002, r)


if __name__ == "__main__":
    unittest.main()
