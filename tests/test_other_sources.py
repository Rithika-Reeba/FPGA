import os
os.environ["FPGA_BOARD"] = "none"   # tests use the placeholder nominal, never a board calibration
"""
The mock dataset, the live simulation and the estimated-health input all go through the same
limits as the real board. These tests keep them honest: a healthy scenario never trips a limit,
the ageing scenario crosses Warning and Degraded where the rules say, and every region is judged
against ITS OWN nominal (a calibrated board has different baselines per region).
"""

import unittest
from unittest import mock

import health_rules as rules
from dashboard import data_source as ds
from dashboard.config import LimitSeverity, evaluate_engineering_limits

FAKE_NOMINALS = {"R1": 495.0, "R2": 459.0, "R3": 459.0, "R4": 479.0}
FAKE_GLOBAL = sum(rules.REGION_WEIGHTS[r] * FAKE_NOMINALS[r] for r in FAKE_NOMINALS)


def calibrated():
    """Make the data sources behave as if a board with its own regional baselines were calibrated."""
    return mock.patch.multiple(ds, _NOM=FAKE_GLOBAL, _nom=lambda r: FAKE_NOMINALS[r])


def simulate(deg, n=30):
    src = ds.LiveSimulationDataSource(buffer_size=60)
    for _ in range(n):
        src.step(deg)
    return src.get_data(window_size=30)


class TestSharedScenario(unittest.TestCase):
    def state_at(self, d):
        nominal = rules.RO_PLACEHOLDER_NOMINAL_MHZ
        drop = rules.scenario_ro_drop_pct(d)
        return rules.worst_state([
            rules.classify_region(nominal * (1 - drop / 100.0), nominal),
            rules.classify_temperature(rules.scenario_temp_c(d)),
            rules.classify_error_rate(rules.scenario_error_rate(d)),
        ])

    def test_scenario_crosses_the_real_limits_in_order(self):
        self.assertEqual(self.state_at(0.0), rules.HEALTHY)
        self.assertEqual(self.state_at(0.2), rules.HEALTHY)
        self.assertEqual(self.state_at(0.5), rules.WARNING)
        self.assertEqual(self.state_at(0.95), rules.DEGRADED)
        self.assertEqual(self.state_at(1.0), rules.DEGRADED)

    def test_scenario_only_gets_worse(self):
        drops = [rules.scenario_ro_drop_pct(i / 20) for i in range(21)]
        temps = [rules.scenario_temp_c(i / 20) for i in range(21)]
        self.assertEqual(drops, sorted(drops))
        self.assertEqual(temps, sorted(temps))


class TestLiveSimulation(unittest.TestCase):
    def severity(self, deg):
        _, latest, meta = simulate(deg)
        a = evaluate_engineering_limits(latest.to_dict(), provenance_map=meta["provenance"],
                                        regional_baselines=meta["regional_baselines"])
        return a.max_severity

    def test_healthy_simulation_trips_nothing(self):
        self.assertEqual(self.severity(0.0), LimitSeverity.NORMAL)

    def test_mid_ageing_is_a_warning(self):
        self.assertEqual(self.severity(0.5), LimitSeverity.WARNING)

    def test_late_ageing_is_degraded(self):
        self.assertEqual(self.severity(1.0), LimitSeverity.CRITICAL)

    def test_each_region_varies_around_its_own_nominal(self):
        with calibrated():
            _, latest, meta = simulate(0.0)
        for r, nominal in FAKE_NOMINALS.items():
            self.assertLess(abs(latest[f"RO_{r}"] / nominal - 1.0), 0.003, r)
        self.assertAlmostEqual(meta["baseline"]["RO_R2"], FAKE_NOMINALS["R2"], places=2)

    def test_aggregate_is_the_weighted_mean_of_the_regions(self):
        _, latest, _ = simulate(0.5)
        expected = sum(rules.REGION_WEIGHTS[r] * latest[f"RO_{r}"] for r in rules.REGIONS)
        self.assertAlmostEqual(latest["RO_Frequency"], expected, delta=0.02)

    def test_simulation_is_labelled_simulation(self):
        _, _, meta = simulate(0.0)
        self.assertEqual(meta["source_type"], "SIMULATION")
        self.assertEqual(meta["provenance"]["RO_R1"], "SIMULATION")


class TestEstimatedHealth(unittest.TestCase):
    def test_baseline_delays_follow_the_baseline_frequencies(self):
        base = ds.EstimatedDataSource.NOMINAL_BASELINE
        self.assertAlmostEqual(base["RO_Delay_ns"], 100.0 / base["RO_Frequency"], places=4)
        for r in rules.REGIONS:
            self.assertAlmostEqual(base[f"RO_{r}_Delay_ns"], 100.0 / base[f"RO_{r}"], places=4)

    def test_entering_the_nominal_frequency_is_healthy(self):
        src = ds.EstimatedDataSource({"RO_Frequency": rules.RO_PLACEHOLDER_NOMINAL_MHZ})
        _, latest, meta = src.get_data()
        self.assertEqual(meta["engineering_assessment"]["max_severity"], LimitSeverity.NORMAL.value)

    def test_a_clearly_degraded_frequency_is_critical(self):
        src = ds.EstimatedDataSource({"RO_Frequency": 420.0})
        _, _, meta = src.get_data()
        self.assertEqual(meta["engineering_assessment"]["max_severity"], LimitSeverity.CRITICAL.value)

    def test_regions_scale_to_their_own_nominals(self):
        with calibrated():
            _, latest, _ = ds.EstimatedDataSource({"RO_Frequency": FAKE_GLOBAL}).get_data()
        for r, nominal in FAKE_NOMINALS.items():
            self.assertLess(abs(latest[f"RO_{r}"] / nominal - 1.0), 0.003, r)

    def test_missing_channels_are_marked_assumed(self):
        _, _, meta = ds.EstimatedDataSource({"Temperature": 40.0}).get_data()
        self.assertIn("Temperature", meta["user_provided"])
        self.assertIn("RO_Frequency", meta["assumed"])


if __name__ == "__main__":
    unittest.main()
