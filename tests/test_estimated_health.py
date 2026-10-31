"""
Comprehensive Unit & Integration Test Suite for FPGA Health Monitoring System
=============================================================================
Verifies:
 1. All six telemetry values supplied.
 2. Only temperature supplied.
 3. Only RO frequency supplied.
 4. Temperature + RO frequency supplied.
 5. Invalid temperature handling.
 6. Invalid voltage handling.
 7. Invalid RO frequency handling.
 8. Invalid error rate handling.
 9. RO delay physical calculation (250 MHz -> 0.4000 ns, 240 MHz -> 0.4167 ns, 235 MHz -> 0.4255 ns).
10. Missing-value handling & provenance labeling (user_provided, derived, assumed).
11. Estimated-source metadata, completeness, and reliability scoring.
12. Existing Mock, Simulation, and UART data source integrity.
13. End-to-end ML classification and Diagnostic Agent integration.
"""

import os
os.environ["FPGA_CALIBRATION"] = "none"   # tests use the placeholder nominal, never a board calibration
import sys
import unittest
from pathlib import Path
import pandas as pd
import joblib

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import calculate_ro_delay_ns, validate_ro_delay, RO_STAGES
from dashboard.data_source import (
    EstimatedDataSource,
    MockCSVDataSource,
    LiveSimulationDataSource,
    LiveUARTDataSource
)
from agent.langgraph_agent import evaluate_fpga_health
from ml.feature_engineering import create_features


class TestEstimatedHealthAssessment(unittest.TestCase):

    def setUp(self):
        self.est_source = EstimatedDataSource()
        self.model_path = PROJECT_ROOT / "ml" / "models" / "fpga_health_model.pkl"
        if self.model_path.exists():
            bundle = joblib.load(self.model_path)
            self.model = bundle["model"]
            self.features = bundle["features"]
        else:
            self.model = None
            self.features = None

    # -------------------------------------------------------------------------
    # Test 1: All six values supplied
    # -------------------------------------------------------------------------
    def test_all_six_values_supplied(self):
        inputs = {
            "Temperature": 48.0,
            "VCCINT": 0.992,
            "VCCAUX": 1.792,
            "VCCBRAM": 0.994,
            "RO_Frequency": 241.0,
            "Error_Rate": 0.0015
        }
        valid, errors, warnings = self.est_source.set_inputs(inputs)
        self.assertTrue(valid, f"Validation failed: {errors}")
        self.assertEqual(len(errors), 0)

        history_df, latest, meta = self.est_source.get_data(window_size=50)

        self.assertEqual(meta["completeness_count"], 6)
        self.assertEqual(meta["completeness_str"], "6 / 6")
        self.assertEqual(meta["completeness_ratio"], 1.0)
        self.assertEqual(meta["reliability_score"], 1.0)
        self.assertEqual(len(meta["user_provided"]), 6)
        self.assertIn("RO_Delay_ns", meta["derived"])
        self.assertEqual(len(meta["assumed"]), 0)

        self.assertAlmostEqual(latest["Temperature"], 48.0, places=2)
        self.assertAlmostEqual(latest["RO_Frequency"], 241.0, places=2)
        self.assertAlmostEqual(latest["RO_Delay_ns"], round(100.0 / 241.0, 4), places=4)

    # -------------------------------------------------------------------------
    # Test 2: Only temperature supplied
    # -------------------------------------------------------------------------
    def test_only_temperature_supplied(self):
        inputs = {"Temperature": 52.5}
        valid, errors, warnings = self.est_source.set_inputs(inputs)
        self.assertTrue(valid)
        self.assertEqual(len(errors), 0)

        history_df, latest, meta = self.est_source.get_data(window_size=50)

        self.assertEqual(meta["completeness_count"], 1)
        self.assertEqual(meta["completeness_str"], "1 / 6")
        self.assertEqual(meta["user_provided"], ["Temperature"])
        self.assertIn("RO_Frequency", meta["assumed"])
        self.assertIn("RO_Delay_ns", meta["assumed"])
        self.assertIn("VCCINT", meta["assumed"])

        # Temperature is user-provided, remaining are nominal baselines
        self.assertAlmostEqual(latest["Temperature"], 52.5, places=2)
        self.assertAlmostEqual(latest["RO_Frequency"], 436.0, places=2)
        self.assertAlmostEqual(latest["RO_Delay_ns"], 0.2294, places=4)
        self.assertAlmostEqual(latest["VCCINT"], 1.000, places=3)

    # -------------------------------------------------------------------------
    # Test 3: Only RO frequency supplied
    # -------------------------------------------------------------------------
    def test_only_ro_frequency_supplied(self):
        inputs = {"RO_Frequency": 236.5}
        valid, errors, warnings = self.est_source.set_inputs(inputs)
        self.assertTrue(valid)

        history_df, latest, meta = self.est_source.get_data(window_size=50)

        self.assertEqual(meta["completeness_count"], 1)
        self.assertEqual(meta["user_provided"], ["RO_Frequency"])
        self.assertEqual(meta["derived"], ["RO_Delay_ns"])
        self.assertIn("Temperature", meta["assumed"])

        expected_delay = round(100.0 / 236.5, 4)
        self.assertAlmostEqual(latest["RO_Frequency"], 236.5, places=2)
        self.assertAlmostEqual(latest["RO_Delay_ns"], expected_delay, places=4)
        self.assertAlmostEqual(latest["Temperature"], 35.0, places=2)

    # -------------------------------------------------------------------------
    # Test 4: Temperature + RO frequency supplied
    # -------------------------------------------------------------------------
    def test_temperature_and_ro_frequency_supplied(self):
        inputs = {
            "Temperature": 50.0,
            "RO_Frequency": 238.0
        }
        valid, errors, warnings = self.est_source.set_inputs(inputs)
        self.assertTrue(valid)

        history_df, latest, meta = self.est_source.get_data(window_size=50)

        self.assertEqual(meta["completeness_count"], 2)
        self.assertEqual(meta["completeness_str"], "2 / 6")
        self.assertIn("Temperature", meta["user_provided"])
        self.assertIn("RO_Frequency", meta["user_provided"])
        self.assertIn("RO_Delay_ns", meta["derived"])

        expected_delay = round(100.0 / 238.0, 4)
        self.assertAlmostEqual(latest["RO_Delay_ns"], expected_delay, places=4)
        # Reliability weight: 0.30 (temp) + 0.35 (ro_freq) = 0.65
        self.assertAlmostEqual(meta["reliability_score"], 0.65, places=2)

    # -------------------------------------------------------------------------
    # Test 5: Invalid temperature bounds validation
    # -------------------------------------------------------------------------
    def test_invalid_temperature_bounds(self):
        # Out of bounds (< -40.0 or > 125.0)
        valid, errors, _ = self.est_source.set_inputs({"Temperature": 150.0})
        self.assertFalse(valid)
        self.assertTrue(any("outside physical sensor bounds" in e.lower() or "outside physical" in e.lower() for e in errors))

        valid_neg, errors_neg, _ = self.est_source.set_inputs({"Temperature": -50.0})
        self.assertFalse(valid_neg)
        self.assertTrue(any("outside physical sensor bounds" in e.lower() or "outside physical" in e.lower() for e in errors_neg))

    # -------------------------------------------------------------------------
    # Test 6: Invalid voltage bounds validation
    # -------------------------------------------------------------------------
    def test_invalid_voltage_bounds(self):
        valid, errors, _ = self.est_source.set_inputs({"VCCINT": 3.3})
        self.assertFalse(valid)
        self.assertTrue(any("VCCINT" in e for e in errors))

        valid2, errors2, _ = self.est_source.set_inputs({"VCCAUX": -0.5})
        self.assertFalse(valid2)
        self.assertTrue(any("VCCAUX" in e for e in errors2))

    # -------------------------------------------------------------------------
    # Test 7: Invalid RO frequency bounds validation
    # -------------------------------------------------------------------------
    def test_invalid_ro_frequency_bounds(self):
        valid, errors, _ = self.est_source.set_inputs({"RO_Frequency": 5.0})
        self.assertFalse(valid)
        self.assertTrue(any("Ring Oscillator Frequency" in e for e in errors))

        valid2, errors2, _ = self.est_source.set_inputs({"RO_Frequency": 850.0})
        self.assertFalse(valid2)
        self.assertTrue(any("Ring Oscillator Frequency" in e for e in errors2))

    # -------------------------------------------------------------------------
    # Test 8: Invalid error rate bounds validation
    # -------------------------------------------------------------------------
    def test_invalid_error_rate_bounds(self):
        valid, errors, _ = self.est_source.set_inputs({"Error_Rate": -0.05})
        self.assertFalse(valid)
        self.assertTrue(any("Functional Error Rate" in e for e in errors))

        valid2, errors2, _ = self.est_source.set_inputs({"Error_Rate": 2.5})
        self.assertFalse(valid2)
        self.assertTrue(any("Functional Error Rate" in e for e in errors2))

    # -------------------------------------------------------------------------
    # Test 9: RO Delay physical calculation precision
    # -------------------------------------------------------------------------
    def test_ro_delay_precision(self):
        # tau = 1000 / (2 * 5 * f_MHz) = 100.0 / f_MHz
        # 436.0 MHz (Physical Basys 3 nominal) -> 0.2294 ns
        delay_436 = calculate_ro_delay_ns(436.0, stages=RO_STAGES)
        self.assertEqual(delay_436, 0.2294)

        # 424.0 MHz (Warning threshold region) -> 0.2358 ns
        delay_424 = calculate_ro_delay_ns(424.0, stages=RO_STAGES)
        self.assertEqual(delay_424, 0.2358)

        # 410.0 MHz (Degraded threshold region) -> 0.2439 ns
        delay_410 = calculate_ro_delay_ns(410.0, stages=RO_STAGES)
        self.assertEqual(delay_410, 0.2439)

        # 250 MHz -> 0.4000 ns
        delay_250 = calculate_ro_delay_ns(250.0, stages=RO_STAGES)
        self.assertEqual(delay_250, 0.4000)

        # Sanity check validation
        is_valid_436, _ = validate_ro_delay(436.0, RO_STAGES, delay_436)
        self.assertTrue(is_valid_436)
        is_valid_250, _ = validate_ro_delay(250.0, RO_STAGES, delay_250)
        self.assertTrue(is_valid_250)

    # -------------------------------------------------------------------------
    # Test 10: Missing-value handling & provenance labeling
    # -------------------------------------------------------------------------
    def test_missing_value_handling_and_provenance(self):
        self.est_source.set_inputs({"Temperature": 45.0, "RO_Frequency": 242.0})
        history_df, latest, meta = self.est_source.get_data()

        # Categorization check
        self.assertListEqual(sorted(meta["user_provided"]), ["RO_Frequency", "Temperature"])
        self.assertListEqual(meta["derived"], ["RO_Delay_ns"])
        self.assertIn("VCCINT", meta["assumed"])
        self.assertIn("VCCAUX", meta["assumed"])
        self.assertIn("VCCBRAM", meta["assumed"])
        self.assertIn("Error_Rate", meta["assumed"])

        # Status dictionary check
        self.assertEqual(meta["channel_status"]["Temperature"], "USER_PROVIDED")
        self.assertEqual(meta["channel_status"]["RO_Frequency"], "USER_PROVIDED")
        self.assertEqual(meta["channel_status"]["VCCINT"], "ASSUMED_BASELINE")

    # -------------------------------------------------------------------------
    # Test 11: Estimated-source metadata & reliability score
    # -------------------------------------------------------------------------
    def test_estimated_metadata_and_reliability(self):
        self.est_source.set_inputs({"Temperature": 35.0})
        _, _, meta = self.est_source.get_data()

        self.assertEqual(meta["source_type"], "ESTIMATED")
        self.assertEqual(meta["source_label"], "ESTIMATED / USER PROVIDED")
        self.assertEqual(meta["completeness_str"], "1 / 6")
        self.assertAlmostEqual(meta["reliability_score"], 0.30, places=2)

    # -------------------------------------------------------------------------
    # Test 12: Existing Mock, Simulation, and UART data sources
    # -------------------------------------------------------------------------
    def test_existing_data_sources(self):
        # 1. Mock CSV
        csv_source = MockCSVDataSource()
        mock_hist, mock_latest, mock_meta = csv_source.get_data(window_size=50, sample_idx=100)
        self.assertEqual(len(mock_hist), 50)
        self.assertEqual(mock_meta["source_type"], "MOCK")

        # 2. Live Simulation
        sim_source = LiveSimulationDataSource(buffer_size=50)
        sim_hist, sim_latest, sim_meta = sim_source.get_data(window_size=50)
        self.assertEqual(len(sim_hist), 50)
        self.assertEqual(sim_meta["source_type"], "SIMULATION")

        # 3. Live UART
        uart_source = LiveUARTDataSource(port="COM3")
        uart_hist, uart_latest, uart_meta = uart_source.get_data(window_size=50)
        self.assertGreaterEqual(len(uart_hist), 1)
        self.assertEqual(uart_meta["source_type"], "LIVE_UART")

    # -------------------------------------------------------------------------
    # Test 13: End-to-end ML prediction and Diagnostic Agent integration
    # -------------------------------------------------------------------------
    def test_end_to_end_pipeline_integration(self):
        if self.model is None:
            self.skipTest("ML Model bundle not available.")

        # Test with degraded inputs: Temp=54°C, RO=234MHz, Error=0.003
        self.est_source.set_inputs({
            "Temperature": 54.0,
            "RO_Frequency": 234.0,
            "Error_Rate": 0.003
        })
        history_df, latest, meta = self.est_source.get_data(window_size=50)

        # 1. ML Model inference
        X = history_df[self.features]
        preds = self.model.predict(X)
        probs = self.model.predict_proba(X)
        latest_pred = preds[-1]
        latest_conf = float(probs[-1].max())

        self.assertIn(latest_pred, ["Healthy", "Warning", "Degraded"])
        self.assertEqual(latest_pred, "Degraded")

        # 2. Diagnostic agent evaluation
        agent_input = {
            "health": latest_pred,
            "confidence": latest_conf,
            "temperature": float(latest["Temperature"]),
            "vccint": float(latest["VCCINT"]),
            "vccaux": float(latest["VCCAUX"]),
            "vccbram": float(latest["VCCBRAM"]),
            "ro_frequency": float(latest["RO_Frequency"]),
            "ro_delay": float(latest["RO_Delay_ns"]),
            "error_rate": float(latest["Error_Rate"]),
            "ro_freq_shift_pct": ((float(latest["RO_Frequency"]) - 436.0) / 436.0) * 100.0,
            "ro_delay_shift_pct": ((float(latest["RO_Delay_ns"]) - 0.2294) / 0.2294) * 100.0,
            "temp_shift": float(latest["Temperature"]) - 35.0,
            "source": meta["source_type"],
            "completeness_str": meta["completeness_str"],
            "completeness_count": meta["completeness_count"],
            "reliability_score": meta["reliability_score"],
            "user_provided": meta["user_provided"],
            "assumed": meta["assumed"],
            "is_estimated": True
        }

        report = evaluate_fpga_health(agent_input)
        self.assertIn("risk_level", report)
        self.assertIn("condition_summary", report)
        self.assertIn("primary_indicators", report)
        self.assertIn("recommended_actions", report)
        self.assertTrue(any("Input completeness" in ind for ind in report["primary_indicators"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
