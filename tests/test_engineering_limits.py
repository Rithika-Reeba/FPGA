"""
Comprehensive Unit & Integration Test Suite for FPGA Engineering Limits & Safety Envelope
========================================================================================
Tests:
 1. Temperature = 0°C -> NOT Healthy (Overridden to Degraded / Critical).
 2. Temperature = 35°C (nominal) -> No violation (Healthy).
 3. Temperature = 48°C -> Warning operating behavior.
 4. Temperature = 55°C / 125°C -> Critical thermal stress behavior.
 5. VCCINT = 0.2V -> Severe undervoltage critical violation.
 6. VCCINT = 1.3V -> Severe overvoltage critical violation.
 7. RO_Frequency = 220 MHz -> Severe gate delay / aging critical violation.
 8. Error_Rate = 0.003 -> Elevated functional error critical violation.
 9. ML predicts Healthy but hard limit violated -> Final Engineering Assessment overrides ML.
 10. All nominal -> ML result determines health (no override).
 11. Estimated mode with partial telemetry & hard limit violation -> Override applied & provenance tracked.
 12. Hardware telemetry with hard limit violation -> Override applied.
 13. Three-Tier Validation Distinction (Input Validity vs Physical Validity vs Operating Range).
 14. Diagnostic Reasoning Agent (LangGraph) incorporates safety override explanation.
"""

import os
os.environ["FPGA_BOARD"] = "none"   # tests use the placeholder nominal, never a board calibration
import sys
import unittest
from pathlib import Path
import pandas as pd
import joblib

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.config import (
    SENSOR_CONFIG,
    LimitSeverity,
    evaluate_single_channel,
    evaluate_engineering_limits,
    determine_final_health,
    get_error_risk_label
)
from dashboard.data_source import (
    EstimatedDataSource,
    MockCSVDataSource,
    LiveSimulationDataSource,
    LiveUARTDataSource
)
from agent.langgraph_agent import evaluate_fpga_health


import health_rules as rules

# Every limit below comes from the single source of truth (health_rules.py)
_NOM = rules.RO_PLACEHOLDER_NOMINAL_MHZ
_LIM = rules.ro_limits(_NOM)
WARN_F = round(_LIM["warn_low"], 2)               # warning boundary (MHz)
CRIT_F = round(_LIM["crit_low"], 2)               # critical boundary (MHz)
WARN_MID = round((WARN_F + CRIT_F) / 2.0, 1)      # a value inside the warning band
BELOW_CRIT = round(CRIT_F - 0.2, 1)               # just below the critical boundary
class TestEngineeringOperatingLimits(unittest.TestCase):

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
    # Test 1: Temperature = 0°C (Freeze fault / cold start) -> NOT Healthy
    # -------------------------------------------------------------------------
    def test_case_1_temp_zero_celsius_critical_override(self):
        reading = {
            "Temperature": 0.0,
            "VCCINT": 1.000,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": 436.0,
            "RO_Delay_ns": 0.2294,
            "Error_Rate": 0.00001
        }
        assessment = evaluate_engineering_limits(reading)
        self.assertTrue(assessment["has_critical"])
        self.assertEqual(assessment["max_severity"], LimitSeverity.CRITICAL)
        
        # Verify single channel eval
        temp_eval = assessment["evaluations"]["Temperature"]
        self.assertEqual(temp_eval.severity, LimitSeverity.CRITICAL)
        self.assertTrue(temp_eval.is_hard_override)
        self.assertIn("freeze fault", temp_eval.status_label.lower())
        self.assertIn("at or below 0", temp_eval.reason.lower())

        # Verify ML Override: Even if ML predicts Healthy, final MUST NOT be Healthy
        final_res = determine_final_health(
            ml_prediction="Healthy",
            ml_confidence=0.98,
            engineering_assessment=assessment
        )
        self.assertTrue(final_res["override_applied"])
        self.assertNotEqual(final_res["final_health"], "Healthy")
        self.assertIn(final_res["final_health"], ["Degraded", "Critical"])
        self.assertIn("Temperature", final_res["override_explanation"])

    # -------------------------------------------------------------------------
    # Test 2: Temperature = 35°C (Nominal) -> No violation
    # -------------------------------------------------------------------------
    def test_case_2_temp_nominal_35c_no_violation(self):
        reading = {
            "Temperature": 35.0,
            "VCCINT": 1.000,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": 436.0,
            "RO_Delay_ns": 0.2294,
            "Error_Rate": 0.00001
        }
        assessment = evaluate_engineering_limits(reading)
        self.assertFalse(assessment["has_critical"])
        self.assertFalse(assessment["has_warning"])
        self.assertEqual(assessment["max_severity"], LimitSeverity.NORMAL)

        final_res = determine_final_health(
            ml_prediction="Healthy",
            ml_confidence=0.96,
            engineering_assessment=assessment
        )
        self.assertFalse(final_res["override_applied"])
        self.assertEqual(final_res["final_health"], "Healthy")

    # -------------------------------------------------------------------------
    # Test 3: Temperature = 48°C -> Warning operating behavior
    # -------------------------------------------------------------------------
    def test_case_3_temp_warning_48c(self):
        reading = {
            "Temperature": rules.TEMP_WARN_C + 3.0,
            "VCCINT": 1.000,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": 436.0,
            "RO_Delay_ns": 0.2294,
            "Error_Rate": 0.00001
        }
        assessment = evaluate_engineering_limits(reading)
        self.assertFalse(assessment["has_critical"])
        self.assertTrue(assessment["has_warning"])
        self.assertEqual(assessment["max_severity"], LimitSeverity.WARNING)

        final_res = determine_final_health(
            ml_prediction="Healthy",
            ml_confidence=0.92,
            engineering_assessment=assessment
        )
        self.assertTrue(final_res["override_applied"])
        self.assertEqual(final_res["final_health"], "Warning")

    # -------------------------------------------------------------------------
    # Test 4: Temperature = 55°C & 125°C -> Critical thermal behavior
    # -------------------------------------------------------------------------
    def test_case_4_temp_critical_55c_and_125c(self):
        for temp_val in [rules.TEMP_CRIT_C + 3.0, 125.0]:
            reading = {
                "Temperature": temp_val,
                "VCCINT": 1.000,
                "VCCAUX": 1.800,
                "VCCBRAM": 1.000,
                "RO_Frequency": 250.0,
                "RO_Delay_ns": 0.4000,
                "Error_Rate": 0.00001
            }
            assessment = evaluate_engineering_limits(reading)
            self.assertTrue(assessment["has_critical"])
            temp_eval = assessment["evaluations"]["Temperature"]
            self.assertEqual(temp_eval.severity, LimitSeverity.CRITICAL)

            final_res = determine_final_health(
                ml_prediction="Healthy",
                ml_confidence=0.90,
                engineering_assessment=assessment
            )
            self.assertTrue(final_res["override_applied"])
            self.assertIn(final_res["final_health"], ["Degraded", "Critical"])

    # -------------------------------------------------------------------------
    # Test 5: VCCINT = 0.2V -> Severe undervoltage critical violation
    # -------------------------------------------------------------------------
    def test_case_5_vccint_low_0_2v_critical(self):
        reading = {
            "Temperature": 35.0,
            "VCCINT": 0.200,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": 436.0,
            "RO_Delay_ns": 0.2294,
            "Error_Rate": 0.00001
        }
        assessment = evaluate_engineering_limits(reading)
        self.assertTrue(assessment["has_critical"])
        vcc_eval = assessment["evaluations"]["VCCINT"]
        self.assertEqual(vcc_eval.severity, LimitSeverity.CRITICAL)
        self.assertIn("droop", vcc_eval.status_label.lower())
        self.assertIn("dropped below", vcc_eval.reason.lower())

        final_res = determine_final_health(
            ml_prediction="Healthy",
            ml_confidence=0.99,
            engineering_assessment=assessment
        )
        self.assertTrue(final_res["override_applied"])
        self.assertIn(final_res["final_health"], ["Degraded", "Critical"])

    # -------------------------------------------------------------------------
    # Test 6: VCCINT = 1.3V -> Severe overvoltage critical violation
    # -------------------------------------------------------------------------
    def test_case_6_vccint_high_1_3v_critical(self):
        reading = {
            "Temperature": 35.0,
            "VCCINT": 1.300,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": 436.0,
            "RO_Delay_ns": 0.2294,
            "Error_Rate": 0.00001
        }
        assessment = evaluate_engineering_limits(reading)
        self.assertTrue(assessment["has_critical"])
        vcc_eval = assessment["evaluations"]["VCCINT"]
        self.assertEqual(vcc_eval.severity, LimitSeverity.CRITICAL)
        self.assertIn("overvoltage", vcc_eval.status_label.lower())
        self.assertIn("exceeds maximum", vcc_eval.reason.lower())

        final_res = determine_final_health(
            ml_prediction="Healthy",
            ml_confidence=0.99,
            engineering_assessment=assessment
        )
        self.assertTrue(final_res["override_applied"])

    # -------------------------------------------------------------------------
    # Test 7: RO_Frequency = 220 MHz -> Critical timing degradation
    # -------------------------------------------------------------------------
    def test_case_7_ro_frequency_220mhz_critical(self):
        reading = {
            "Temperature": 35.0,
            "VCCINT": 1.000,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": 220.0,
            "RO_Delay_ns": 0.4545,
            "Error_Rate": 0.00001
        }
        assessment = evaluate_engineering_limits(reading)
        self.assertTrue(assessment["has_critical"])
        ro_eval = assessment["evaluations"]["RO_Frequency"]
        self.assertEqual(ro_eval.severity, LimitSeverity.CRITICAL)

        final_res = determine_final_health(
            ml_prediction="Healthy",
            ml_confidence=0.95,
            engineering_assessment=assessment
        )
        self.assertTrue(final_res["override_applied"])
        self.assertIn(final_res["final_health"], ["Degraded", "Critical"])

    # -------------------------------------------------------------------------
    # Test 8: Error_Rate = 0.003 -> Elevated functional error critical violation
    # -------------------------------------------------------------------------
    def test_case_8_error_rate_0_003_critical(self):
        reading = {
            "Temperature": 35.0,
            "VCCINT": 1.000,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": 436.0,
            "RO_Delay_ns": 0.2294,
            "Error_Rate": 0.003000
        }
        assessment = evaluate_engineering_limits(reading)
        self.assertTrue(assessment["has_critical"])
        err_eval = assessment["evaluations"]["Error_Rate"]
        self.assertEqual(err_eval.severity, LimitSeverity.CRITICAL)

        final_res = determine_final_health(
            ml_prediction="Healthy",
            ml_confidence=0.85,
            engineering_assessment=assessment
        )
        self.assertTrue(final_res["override_applied"])
        self.assertIn(final_res["final_health"], ["Degraded", "Critical"])

    # -------------------------------------------------------------------------
    # Test 9: ML predicts Healthy but hard limit violated -> Deterministic override
    # -------------------------------------------------------------------------
    def test_case_9_ml_predicts_healthy_but_hard_limit_violated(self):
        reading = {
            "Temperature": 0.0,  # Freeze fault hard limit
            "VCCINT": 1.000,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": 436.0,
            "RO_Delay_ns": 0.2294,
            "Error_Rate": 0.00001
        }
        assessment = evaluate_engineering_limits(reading)
        final_res = determine_final_health("Healthy", 0.99, assessment)
        
        self.assertTrue(final_res["override_applied"])
        self.assertEqual(final_res["ml_prediction"], "Healthy")
        self.assertEqual(final_res["ml_confidence"], 0.99)
        self.assertNotEqual(final_res["final_health"], "Healthy")
        self.assertGreater(len(final_res["reasons"]), 0)
        self.assertIn("Temperature", final_res["reasons"][0])

    # -------------------------------------------------------------------------
    # Test 10: All nominal -> ML result determines health
    # -------------------------------------------------------------------------
    def test_case_10_all_nominal_ml_determines_health(self):
        reading = {
            "Temperature": 35.0,
            "VCCINT": 1.000,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": 436.0,
            "RO_Delay_ns": 0.2294,
            "Error_Rate": 0.00001
        }
        assessment = evaluate_engineering_limits(reading)
        
        # Test ML = Healthy
        res_h = determine_final_health("Healthy", 0.95, assessment)
        self.assertFalse(res_h["override_applied"])
        self.assertEqual(res_h["final_health"], "Healthy")

        # Test ML = Warning
        res_w = determine_final_health("Warning", 0.88, assessment)
        self.assertFalse(res_w["override_applied"])
        self.assertEqual(res_w["final_health"], "Warning")

        # Test ML = Degraded
        res_d = determine_final_health("Degraded", 0.92, assessment)
        self.assertFalse(res_d["override_applied"])
        self.assertEqual(res_d["final_health"], "Degraded")

    # -------------------------------------------------------------------------
    # Test 11: Estimated mode with partial telemetry & hard limit violation
    # -------------------------------------------------------------------------
    def test_case_11_estimated_mode_partial_telemetry_hard_limit(self):
        # User provides ONLY Temperature = 0.0 (Freeze fault)
        inputs = {"Temperature": "0.0"}
        valid, errors, warnings = self.est_source.set_inputs(inputs)
        self.assertTrue(valid)
        self.assertGreater(len(warnings), 0)

        history_df, latest, meta = self.est_source.get_data(window_size=10)
        assessment = meta.get("engineering_assessment", {})
        
        self.assertTrue(assessment["has_critical"])
        self.assertEqual(meta["provenance"]["Temperature"], "USER_PROVIDED")
        self.assertEqual(meta["provenance"]["VCCINT"], "ASSUMED_BASELINE")
        self.assertEqual(meta["provenance"]["RO_Delay_ns"], "ASSUMED_BASELINE")

        final_res = determine_final_health("Healthy", 0.95, assessment)
        self.assertTrue(final_res["override_applied"])
        self.assertNotEqual(final_res["final_health"], "Healthy")

    # -------------------------------------------------------------------------
    # Test 12: Hardware telemetry with hard limit violation
    # -------------------------------------------------------------------------
    def test_case_12_hardware_telemetry_hard_limit_override(self):
        uart_src = LiveUARTDataSource(port="COM3")
        # Ingest mock hardware packets with severe undervoltage
        deg_json = '{"Temperature":35.0,"VCCINT":0.850,"VCCAUX":1.800,"VCCBRAM":1.000,"RO_Frequency":436.0,"Error_Rate":0.000010}'
        parsed = uart_src.receiver._parse_raw_line(deg_json)
        self.assertIsNotNone(parsed)
        for _ in range(15):
            uart_src.buffer.append(dict(parsed))
        history_df, latest, meta = uart_src.get_data(window_size=10)
        
        assessment = meta.get("engineering_assessment", {})
        self.assertTrue(assessment["has_critical"])
        self.assertEqual(meta["provenance"]["VCCINT"], "MEASURED")

        final_res = determine_final_health("Healthy", 0.95, assessment)
        self.assertTrue(final_res["override_applied"])
        self.assertIn("VCCINT", final_res["reasons"][0])

    # -------------------------------------------------------------------------
    # Test 13: Three-Tier Validation Distinction
    # -------------------------------------------------------------------------
    def test_case_13_three_tier_validation_distinction(self):
        # Tier 1: Input Validity (Syntax/Type)
        v1, num1, err1, w1 = self.est_source.validate_channel("Temperature", "abc")
        self.assertFalse(v1)
        self.assertIn("numeric", err1.lower())

        # Tier 2: Physical Plausibility (Sensor Range)
        v2, num2, err2, w2 = self.est_source.validate_channel("Temperature", "-500.0")
        self.assertFalse(v2)
        self.assertIn("physical sensor bounds", err2.lower())

        # Tier 3: Operating Health Range (Safe Envelope)
        # 0.0°C is physically valid, so it must be accepted as valid input, but generate an operating warning
        v3, num3, err3, w3 = self.est_source.validate_channel("Temperature", "0.0")
        self.assertTrue(v3)
        self.assertEqual(num3, 0.0)
        self.assertIsNone(err3)
        self.assertIsNotNone(w3)
        self.assertIn("outside", w3.lower())

    # -------------------------------------------------------------------------
    # Test 14: LangGraph Diagnostic Agent incorporates safety override
    # -------------------------------------------------------------------------
    def test_case_14_langgraph_agent_override_reasoning(self):
        telemetry = {
            "health": "Degraded",
            "confidence": 0.99,
            "ml_prediction": "Healthy",
            "ml_confidence": 0.95,
            "override_applied": True,
            "override_title": "HARD ENGINEERING LIMIT OVERRIDE: CRITICAL SAFETY LIMIT EXCEEDED",
            "override_explanation": "VCCINT is 0.8500 V which violates critical operating limit [0.9200, 1.0800 V].",
            "override_reasons": ["VCCINT = 0.8500 V: Critical core undervoltage"],
            "temperature": 35.0,
            "vccint": 0.85,
            "vccaux": 1.80,
            "vccbram": 1.00,
            "ro_frequency": 436.0,
            "ro_delay": 0.2294,
            "error_rate": 0.00001,
            "ro_freq_shift_pct": 0.0,
            "ro_delay_shift_pct": 0.0,
            "temp_shift": 0.0,
            "temp_trend": "Stable",
            "ro_freq_trend": "Stable",
            "error_trend": "Stable",
            "source": "LIVE",
            "completeness_str": "6 / 6",
            "completeness_count": 6,
            "reliability_score": 1.0,
            "user_provided": [],
            "assumed": []
        }
        report = evaluate_fpga_health(telemetry)
        
        self.assertIn("HIGH", report["risk_level"].upper())
        self.assertTrue(
            any("override" in ind.lower() or "vccint" in ind.lower() or "undervoltage" in ind.lower()
                for ind in report["primary_indicators"])
        )
        self.assertTrue(
            any("voltage" in str(act).lower() or "power" in str(act).lower()
                for act in report["recommended_actions"].values())
        )

    # =========================================================================
    # Validation Cases A - E (Mandatory Architecture & Calibration Verification)
    # =========================================================================

    def test_case_a_hardware_nominal_telemetry(self):
        """
        Case A — Current physical Basys 3 hardware telemetry:
        Temperature = 35.8, VCCINT = 1.000, VCCAUX = 1.791, VCCBRAM = 0.999,
        RO_Frequency = 436.3, Error_Rate = 0.00000
        Expected:
          - Temperature nominal
          - Voltage rails nominal
          - Error Risk = Low (independent)
          - RO classification based on validated hardware calibration (NORMAL)
          - Overall health is Healthy (not Degraded!)
        """
        telemetry = {
            "Temperature": 35.8,
            "VCCINT": 1.000,
            "VCCAUX": 1.791,
            "VCCBRAM": 0.999,
            "RO_Frequency": 436.3,
            "RO_Delay_ns": 0.2292,
            "Error_Rate": 0.00000
        }
        assessment = evaluate_engineering_limits(telemetry)
        self.assertFalse(assessment["has_critical"])
        self.assertFalse(assessment["has_warning"])
        self.assertEqual(assessment["max_severity"], LimitSeverity.NORMAL)
        
        # Verify RO frequency is evaluated as NORMAL under 436 MHz calibration
        ro_eval = assessment["evaluations"]["RO_Frequency"]
        self.assertEqual(ro_eval.severity, LimitSeverity.NORMAL)
        self.assertFalse(ro_eval.is_violation)

        # Verify Error Risk is Low
        risk_label, risk_color, _ = get_error_risk_label(telemetry["Error_Rate"])
        self.assertEqual(risk_label, "Low")

        # Verify ML classification on this physical point
        if self.model is not None:
            df = pd.DataFrame([telemetry] * 25)
            from ml.feature_engineering import create_features
            df_feat = create_features(df)
            ml_pred = self.model.predict(df_feat[self.features].iloc[[-1]])[0]
            self.assertEqual(ml_pred, "Healthy")

        # Final health decision must be Healthy with NO override applied
        final_res = determine_final_health("Healthy", 0.97, assessment)
        self.assertFalse(final_res["override_applied"])
        self.assertEqual(final_res["final_health"], "Healthy")

    def test_case_b_elevated_temperature(self):
        """
        Case B — Elevated temperature independently causes Warning / Degraded,
        while Error Risk remains Low.
        """
        # Warning condition: 48.0°C
        warn_telemetry = {
            "Temperature": rules.TEMP_WARN_C + 3.0,
            "VCCINT": 1.000,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": 436.0,
            "RO_Delay_ns": 0.2294,
            "Error_Rate": 0.00000
        }
        warn_assessment = evaluate_engineering_limits(warn_telemetry)
        self.assertTrue(warn_assessment["has_warning"])
        self.assertFalse(warn_assessment["has_critical"])
        warn_final = determine_final_health("Healthy", 0.95, warn_assessment)
        self.assertEqual(warn_final["final_health"], "Warning")
        self.assertTrue(warn_final["override_applied"])
        
        # Error risk must STILL be Low even when health is elevated to Warning
        risk_label, _, _ = get_error_risk_label(warn_telemetry["Error_Rate"])
        self.assertEqual(risk_label, "Low")

        # Critical condition: 54.0°C
        crit_telemetry = dict(warn_telemetry, Temperature=rules.TEMP_CRIT_C + 3.0)
        crit_assessment = evaluate_engineering_limits(crit_telemetry)
        self.assertTrue(crit_assessment["has_critical"])
        crit_final = determine_final_health("Healthy", 0.95, crit_assessment)
        self.assertEqual(crit_final["final_health"], "Degraded")
        self.assertTrue(crit_final["override_applied"])

    def test_case_c_genuine_high_error_rate(self):
        """
        Case C — Genuine high error rate:
        Verify Error Risk becomes elevated/high ONLY when Error_Rate crosses actual thresholds.
        """
        # Nominal zero errors
        label_0, _, _ = get_error_risk_label(0.00000)
        self.assertEqual(label_0, "Low")

        # Small noise floor error (100 ppm) -> Low
        label_noise, _, _ = get_error_risk_label(0.000100)
        self.assertEqual(label_noise, "Low")

        # Elevated error rate (800 ppm) -> Medium
        label_med, _, _ = get_error_risk_label(0.000800)
        self.assertEqual(label_med, "Medium")

        # Critical bit error rate (2500 ppm) -> High
        label_high, _, _ = get_error_risk_label(0.002500)
        self.assertEqual(label_high, "High")

        # High error rate triggers Degraded in engineering assessment
        high_err_telemetry = {
            "Temperature": 35.8,
            "VCCINT": 1.000,
            "VCCAUX": 1.791,
            "VCCBRAM": 0.999,
            "RO_Frequency": 436.0,
            "RO_Delay_ns": 0.2294,
            "Error_Rate": 0.003000
        }
        assessment = evaluate_engineering_limits(high_err_telemetry)
        self.assertTrue(assessment["has_critical"])
        final_res = determine_final_health("Healthy", 0.90, assessment)
        self.assertEqual(final_res["final_health"], "Degraded")

    def test_case_d_ro_degradation(self):
        """
        Case D — RO timing degradation:
        Starting from physical baseline (436 MHz), reduce RO frequency and verify
        smooth transitions: Normal -> Warning -> Degraded.
        """
        # Nominal 436 MHz -> Normal
        eval_nom = evaluate_single_channel("RO_Frequency", 436.0)
        self.assertEqual(eval_nom.severity, LimitSeverity.NORMAL)

        # Mild drift 424 MHz (< 427 MHz operating floor) -> Warning
        eval_warn = evaluate_single_channel("RO_Frequency", WARN_MID)
        self.assertEqual(eval_warn.severity, LimitSeverity.WARNING)
        self.assertIn("degradation", eval_warn.reason.lower())

        # Severe timing slowing 408 MHz (< 412 MHz critical floor) -> Critical / Degraded
        eval_crit = evaluate_single_channel("RO_Frequency", 408.0)
        self.assertEqual(eval_crit.severity, LimitSeverity.CRITICAL)
        self.assertIn("critical", eval_crit.status_label.lower())

    def test_case_e_simulation_and_mock_modes(self):
        """
        Case E — Existing mock/simulation modes:
        Verify LiveSimulationDataSource and MockCSVDataSource operate consistently
        with the updated physical 436.0 MHz calibration.
        """
        sim_source = LiveSimulationDataSource()
        history_df, latest, meta = sim_source.get_data()
        self.assertGreater(latest["RO_Frequency"], 400.0)
        self.assertLess(latest["RO_Frequency"], 450.0)
        self.assertAlmostEqual(latest["RO_Delay_ns"], round(100.0 / latest["RO_Frequency"], 4), places=3)
        self.assertAlmostEqual(meta["baseline"]["RO_Frequency"], rules.global_nominal_mhz(), places=6)

        # Mock CSV DataSource
        csv_source = MockCSVDataSource()
        csv_history, csv_latest, csv_meta = csv_source.get_data()
        self.assertGreater(csv_latest["RO_Frequency"], 400.0)
        self.assertEqual(csv_meta["source_type"], "MOCK")


class TestSingleSourceROTimingAndFourRegion(unittest.TestCase):
    """
    Explicit verification of single-source RO timing calibration, derived delay
    non-duplication, and four-region independent health assessment.
    """

    def test_case_1_ro_comfortably_healthy(self):
        """Case 1: RO frequency comfortably healthy (436.0 MHz) -> Healthy, 0 timing violations."""
        telemetry = {
            "Temperature": 35.8,
            "VCCINT": 1.000,
            "VCCAUX": 1.791,
            "VCCBRAM": 0.999,
            "RO_Frequency": 436.0,
            "RO_Delay_ns": round(100.0 / 436.0, 4),
            "Error_Rate": 0.00000
        }
        assessment = evaluate_engineering_limits(telemetry)
        self.assertFalse(assessment["has_critical"])
        self.assertFalse(assessment["has_warning"])
        self.assertEqual(len(assessment["timing_reasons"]), 0)
        self.assertEqual(len(assessment["override_reasons"]), 0)

        final_res = determine_final_health("Healthy", 0.98, assessment)
        self.assertFalse(final_res["override_applied"])
        self.assertEqual(final_res["final_health"], "Healthy")

    def test_case_2_ro_in_warning_range(self):
        """Case 2: RO frequency in warning range (420.0 MHz) -> Warning, exactly 1 timing warning."""
        telemetry = {
            "Temperature": 35.0,
            "VCCINT": 1.000,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": WARN_MID,
            "RO_Delay_ns": round(100.0 / WARN_MID, 4),
            "Error_Rate": 0.00000
        }
        assessment = evaluate_engineering_limits(telemetry)
        self.assertFalse(assessment["has_critical"])
        self.assertTrue(assessment["has_warning"])
        self.assertEqual(len(assessment["override_reasons"]), 1)
        self.assertIn("RO_Frequency", assessment["override_reasons"][0])
        # Crucial: verify RO_Delay_ns is NOT double counted in override_reasons
        self.assertFalse(any("RO_Delay_ns" in r for r in assessment["override_reasons"]))

        final_res = determine_final_health("Healthy", 0.95, assessment)
        self.assertTrue(final_res["override_applied"])
        self.assertEqual(final_res["final_health"], "Warning")

    def test_case_3_ro_just_above_degraded_boundary(self):
        """Case 3: RO frequency just above degraded boundary (412.5 MHz) -> Warning."""
        telemetry = {
            "Temperature": 35.0,
            "VCCINT": 1.000,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": CRIT_F + 0.1,
            "RO_Delay_ns": round(100.0 / (CRIT_F + 0.1), 4),
            "Error_Rate": 0.00000
        }
        assessment = evaluate_engineering_limits(telemetry)
        self.assertFalse(assessment["has_critical"])
        self.assertTrue(assessment["has_warning"])
        self.assertEqual(assessment["max_severity"], LimitSeverity.WARNING)

        final_res = determine_final_health("Healthy", 0.90, assessment)
        self.assertTrue(final_res["override_applied"])
        self.assertEqual(final_res["final_health"], "Warning")

    def test_case_4_ro_just_below_degraded_boundary(self):
        """Case 4: RO frequency just below degraded boundary (411.1 MHz) -> Degraded, exactly 1 timing violation."""
        telemetry = {
            "Temperature": 35.0,
            "VCCINT": 1.000,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": BELOW_CRIT,
            "RO_Delay_ns": round(100.0 / BELOW_CRIT, 4),
            "Error_Rate": 0.00000
        }
        assessment = evaluate_engineering_limits(telemetry)
        self.assertTrue(assessment["has_critical"])
        self.assertEqual(assessment["max_severity"], LimitSeverity.CRITICAL)
        
        # Exactly one timing violation reported
        self.assertEqual(len(assessment["timing_reasons"]), 1)
        self.assertEqual(len(assessment["override_reasons"]), 1)
        self.assertEqual(assessment["primary_channel"], "RO_Frequency")
        self.assertEqual(assessment["measured_str"], f"{BELOW_CRIT:.1f} MHz")
        self.assertEqual(assessment["limit_str"], f"{CRIT_F:.1f} MHz")
        self.assertIn(f"{100.0 / BELOW_CRIT:.4f} ns", assessment["derived_delay_str"])
        self.assertIn("derived from RO frequency", assessment["derived_delay_str"])

        final_res = determine_final_health("Healthy", 0.90, assessment)
        self.assertTrue(final_res["override_applied"])
        self.assertEqual(final_res["final_health"], "Degraded")

    def test_case_5_ml_warning_and_eng_degraded_precedence(self):
        """
        Case 5: ML predicts WARNING (49.5%), but engineering limit breached at 411.1 MHz.
        Final health must be DEGRADED with structured assessment panel explaining precedence.
        """
        telemetry = {
            "Temperature": 35.0,
            "VCCINT": 1.000,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": BELOW_CRIT,
            "RO_Delay_ns": round(100.0 / BELOW_CRIT, 4),
            "Error_Rate": 0.00000
        }
        assessment = evaluate_engineering_limits(telemetry)
        final_res = determine_final_health(
            ml_prediction="Warning",
            ml_confidence=0.495,
            engineering_assessment=assessment
        )
        self.assertTrue(final_res["override_applied"])
        self.assertEqual(final_res["final_health"], "Degraded")
        panel = final_res["assessment_panel"]
        self.assertEqual(panel["ml_prediction"], "WARNING")
        self.assertEqual(panel["ml_confidence_str"], "49.5%")
        self.assertEqual(panel["eng_assessment"], "DEGRADED")
        self.assertEqual(panel["measured_str"], f"{BELOW_CRIT:.1f} MHz")
        self.assertEqual(panel["limit_str"], f"{CRIT_F:.1f} MHz")
        self.assertIn(f"{100.0 / BELOW_CRIT:.4f} ns", panel["derived_delay_str"])
        self.assertIn("deterministic engineering limit takes precedence", panel["final_decision"])

    def test_case_6_mathematical_equivalence_of_boundaries(self):
        """
        Case 6: Exact mathematical equivalence of frequency and delay boundaries:
        tau = 100 / f_MHz.
        """
        from config import (
            RO_FREQ_NOMINAL_MHZ, RO_DELAY_NOMINAL_NS,
            RO_FREQ_OPERATING_MIN_MHZ, RO_DELAY_OPERATING_MAX_NS,
            RO_FREQ_WARNING_LOW_MHZ, RO_DELAY_WARNING_HIGH_NS,
            RO_FREQ_CRITICAL_LOW_MHZ, RO_DELAY_CRITICAL_HIGH_NS,
        )
        self.assertAlmostEqual(RO_DELAY_NOMINAL_NS, 100.0 / RO_FREQ_NOMINAL_MHZ, places=4)
        self.assertAlmostEqual(RO_DELAY_OPERATING_MAX_NS, 100.0 / RO_FREQ_OPERATING_MIN_MHZ, places=4)
        self.assertAlmostEqual(RO_DELAY_WARNING_HIGH_NS, 100.0 / RO_FREQ_WARNING_LOW_MHZ, places=4)
        self.assertAlmostEqual(RO_DELAY_CRITICAL_HIGH_NS, 100.0 / RO_FREQ_CRITICAL_LOW_MHZ, places=4)

    def test_case_7_no_double_counting_in_reasons(self):
        """
        Case 7: Frequency and delay are never double-counted in override_reasons or reasons.
        """
        telemetry = {
            "Temperature": 35.0,
            "VCCINT": 1.000,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": 405.0,  # Critical < 412 MHz
            "RO_Delay_ns": round(100.0 / 405.0, 4),  # Critical > 0.2427 ns
            "Error_Rate": 0.00000
        }
        assessment = evaluate_engineering_limits(telemetry)
        # Should have exactly 1 override reason, not 2
        self.assertEqual(len(assessment["override_reasons"]), 1)
        self.assertIn("RO_Frequency", assessment["override_reasons"][0])
        self.assertFalse(any(r.startswith("RO_Delay_ns") for r in assessment["override_reasons"]))

    def test_case_8_four_region_rule_no_masking_by_average(self):
        """
        Case 8: Four-region rule: R1=435, R2=436, R3=410 (critical), R4=436.
        Average frequency is 429.25 MHz (which is > 427 MHz nominal min),
        but R3 is critical. The system must flag R3 and NOT mask it by averaging!
        """
        telemetry = {
            "Temperature": 35.0,
            "VCCINT": 1.000,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": 435.0,
            "RO_Delay_ns": round(100.0 / 435.0, 4),
            "Error_Rate": 0.00000,
            "RO_R1": 410.0,  # Degradation in R1
            "RO_R2": 436.0,
            "RO_R3": 410.0,  # Degradation in R3 (>= 2 pblocks degraded triggers quorum)
            "RO_R4": 436.0,
        }
        assessment = evaluate_engineering_limits(telemetry)
        self.assertTrue(assessment["has_critical"])
        self.assertEqual(assessment["max_severity"], LimitSeverity.CRITICAL)
        self.assertTrue(assessment["quorum_triggered"])
        self.assertTrue(any("Multi-pblock" in r or "R1" in r or "R3" in r for r in assessment["override_reasons"]))

        final_res = determine_final_health("Healthy", 0.99, assessment)
        self.assertTrue(final_res["override_applied"])
        self.assertEqual(final_res["final_health"], "Degraded")

    def test_regional_baseline_validation_and_unhealthy_baseline_protection(self):
        """
        Confirms that passing an unhealthy regional baseline (e.g. 322.2 MHz for R2)
        does not poison the engineering assessment or hide a critical R2 reading,
        while overall status follows multi-pblock quorum policy.
        """
        telemetry = {
            "Temperature": 35.0,
            "VCCINT": 1.000,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "RO_Frequency": 435.0,
            "RO_Delay_ns": round(100.0 / 435.0, 4),
            "Error_Rate": 0.00000,
            "RO_R1": 436.3,
            "RO_R2": 322.1,  # Critical limit breached in R2
            "RO_R3": 436.1,
            "RO_R4": 435.9,
        }
        unhealthy_baselines = {
            "RO_R1": 436.3,
            "RO_R2": 322.20,  # Erroneous low baseline
            "RO_R3": 436.1,
            "RO_R4": 435.9
        }
        assessment = evaluate_engineering_limits(telemetry, regional_baselines=unhealthy_baselines)
        # R2 itself is evaluated as Critical despite erroneous baseline
        self.assertEqual(assessment.regional_evaluations["R2"]["severity"], LimitSeverity.CRITICAL)
        self.assertEqual(assessment.degraded_pblocks, ["R2"])
        # Under quorum policy (< 2 degraded pblocks), overall status is NORMAL
        self.assertEqual(assessment.max_severity, LimitSeverity.NORMAL)

        # When 2 or more pblocks degrade, quorum triggers overall Degraded status
        telemetry_2deg = telemetry.copy()
        telemetry_2deg["RO_R1"] = 405.0  # Second degraded pblock
        assessment_2deg = evaluate_engineering_limits(telemetry_2deg, regional_baselines=unhealthy_baselines)
        self.assertEqual(assessment_2deg.max_severity, LimitSeverity.CRITICAL)
        self.assertTrue(assessment_2deg.has_hard_violations)
        self.assertTrue(assessment_2deg.quorum_triggered)

        final_res = determine_final_health("Warning", 0.48, assessment_2deg)
        self.assertEqual(final_res["final_health"], "Degraded")
        self.assertTrue(final_res["override_applied"])


if __name__ == "__main__":
    unittest.main()
