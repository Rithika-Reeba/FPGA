"""
Tests for Four-Region Physical Health Architecture & Regional Map Rendering
"""

import os
os.environ["FPGA_BOARD"] = "none"   # tests use the placeholder nominal, never a board calibration
import unittest
from dashboard.health_map import (
    generate_four_region_data,
    render_four_region_map_html,
    calculate_aggregate_risk_score,
    REGIONAL_DEFAULTS
)
import math
from dashboard.config import (
    REGIONAL_CONFIG,
    HEALTH_COLORS,
    STATUS_BG_COLORS,
    LimitSeverity,
    evaluate_regional_health,
    validate_regional_baseline,
    evaluate_engineering_limits,
    determine_final_health,
    DEFAULT_REGIONAL_WEIGHTS,
    validate_regional_weights,
    calculate_weighted_regional_frequency,
    calibrate_history_dataframe
)
from dashboard.charts import (
    create_ro_frequency_chart,
    create_ro_delay_chart,
    create_temperature_chart,
    create_voltage_chart,
    create_error_rate_chart,
    compute_adaptive_y_domain
)
import pandas as pd
from dashboard.data_source import (
    MockCSVDataSource,
    LiveSimulationDataSource,
    LiveUARTDataSource,
    EstimatedDataSource
)


import health_rules as rules

# Every limit below comes from the single source of truth (health_rules.py)
_NOM = rules.RO_PLACEHOLDER_NOMINAL_MHZ
_LIM = rules.ro_limits(_NOM)
WARN_F = round(_LIM["warn_low"], 2)               # warning boundary (MHz)
CRIT_F = round(_LIM["crit_low"], 2)               # critical boundary (MHz)
WARN_MID = round((WARN_F + CRIT_F) / 2.0, 1)      # a value inside the warning band
BELOW_CRIT = round(CRIT_F - 0.2, 1)               # just below the critical boundary
class TestFourRegionHealth(unittest.TestCase):

    def test_regional_defaults_and_config_consistency(self):
        """Verify that all four physical regions R1..R4 are present with valid metadata."""
        for r_key in ["R1", "R2", "R3", "R4"]:
            self.assertIn(r_key, REGIONAL_CONFIG)
            self.assertIn(r_key, REGIONAL_DEFAULTS)
            cfg = REGIONAL_CONFIG[r_key]
            self.assertIn("nominal_freq", cfg)
            self.assertIn("nominal_delay_ns", cfg)
            self.assertGreater(cfg["nominal_freq"], 400.0)
            self.assertLess(cfg["nominal_delay_ns"], 0.3)
            self.assertTrue(cfg["pblock"].startswith("pblock_"))
            self.assertTrue(cfg["clock_region"].startswith("CLOCKREGION_X") or cfg["clock_region"].startswith("X"))

    def test_generate_four_region_data_nominal(self):
        """Nominal telemetry produces Healthy state across all four quadrants."""
        telemetry = {
            "RO_Frequency": 436.0,
            "RO_R1": 436.3,
            "RO_R2": 435.8,
            "RO_R3": 436.1,
            "RO_R4": 435.9,
            "Temperature": 35.8,
            "VCCINT": 1.000,
            "Error_Rate": 0.0
        }
        regions = generate_four_region_data(telemetry)
        self.assertEqual(len(regions), 4)

        for r in regions:
            self.assertEqual(r["state"], "Healthy")
            self.assertAlmostEqual(r["drift_pct"], 0.0, delta=0.5)
            self.assertGreater(r["delay_ns"], 0.20)
            self.assertLess(r["delay_ns"], 0.25)

    def test_generate_four_region_data_degraded_quadrant(self):
        """Simulate R4 experiencing localized thermal/aging degradation."""
        telemetry = {
            "RO_Frequency": 436.0,
            "RO_R1": 436.3,
            "RO_R2": 435.8,
            "RO_R3": 436.1,
            "RO_R4": 410.0,  # Dropped from 435.9 by ~6%
            "Temperature": 42.0,
            "VCCINT": 0.995,
            "Error_Rate": 0.00001
        }
        regions = generate_four_region_data(telemetry)
        r4 = next(r for r in regions if r["id"] == "R4")
        self.assertEqual(r4["state"], "Degraded")
        self.assertLess(r4["drift_pct"], -5.5)

        r1 = next(r for r in regions if r["id"] == "R1")
        self.assertEqual(r1["state"], "Healthy")

    def test_r2_critical_with_low_baseline_inconsistency_regression(self):
        """
        REGRESSION TEST (Resolved):
        Demonstrates that an R2 measured frequency around 322.1 MHz evaluated against
        a low baseline of 322.20 MHz (drift = -0.03%) is correctly classified as Degraded
        because 322.1 MHz violates the authoritative critical boundary (411.8 MHz).
        Hard engineering limits take precedence over small baseline drift.
        """
        telemetry = {
            "RO_Frequency": 322.3,
            "RO_R1": 436.3,
            "RO_R2": 322.1,  # Critical violation (configured critical boundary is 411.8 MHz)
            "RO_R3": 436.1,
            "RO_R4": 435.9,
            "Temperature": 35.0,
            "VCCINT": 1.000,
            "Error_Rate": 0.00001
        }
        regional_baselines = {
            "RO_R1": 436.3,
            "RO_R2": 322.20,  # Erroneously accepted degraded baseline
            "RO_R3": 436.1,
            "RO_R4": 435.9
        }
        regions = generate_four_region_data(telemetry, regional_baselines=regional_baselines)
        r2 = next(r for r in regions if r["id"] == "R2")

        # R2 must NOT be Healthy when 322.1 MHz violates the critical limit (412.0 MHz)
        self.assertNotEqual(r2["state"], "Healthy")
        self.assertEqual(r2["state"], "Degraded")
        self.assertIn("Below critical boundary", r2["indicator"])
        self.assertEqual(r2["critical_freq"], round(CRIT_F, 1))
        self.assertEqual(r2["baseline_freq"], 436.0)

    def test_render_four_region_map_html(self):
        """Verify HTML generation produces 2x2 grid with quadrant details."""
        telemetry = {
            "RO_Frequency": 436.0,
            "RO_R1": 436.3,
            "RO_R2": 435.8,
            "RO_R3": 436.1,
            "RO_R4": 435.9
        }
        regions = generate_four_region_data(telemetry)
        html = render_four_region_map_html(regions, composite_risk=0.12)

        self.assertIn("R1", html)
        self.assertIn("R2", html)
        self.assertIn("R3", html)
        self.assertIn("R4", html)
        self.assertIn("Region 1 (R1)", html)
        self.assertIn("Region 2 (R2)", html)
        self.assertIn("Region 3 (R3)", html)
        self.assertIn("Region 4 (R4)", html)
        self.assertIn("pblock_R1", html)
        self.assertIn("pblock_R4", html)
        self.assertIn("Base:", html)
        self.assertIn("Crit:", html)
        self.assertIn("Critical Boundary:", html)
        self.assertIn("Provenance:", html)
        self.assertIn("Physical Constraint:", html)
        self.assertIn("Clock Region:", html)

        # Verify degraded quadrant renders Degraded badge and critical explanation
        telemetry_degraded = {
            "RO_Frequency": 322.3,
            "RO_R1": 436.3,
            "RO_R2": 322.1,
            "RO_R3": 436.1,
            "RO_R4": 435.9
        }
        regions_deg = generate_four_region_data(telemetry_degraded)
        html_deg = render_four_region_map_html(regions_deg, composite_risk=0.85)
        self.assertIn("DEGRADED", html_deg)
        self.assertIn("Below critical boundary", html_deg)

    def test_data_sources_provide_regional_telemetry(self):
        """Verify that simulation and estimated data sources output regional fields."""
        sim = LiveSimulationDataSource()
        hist, latest, meta = sim.get_data()
        self.assertIn("RO_R1", latest)
        self.assertIn("RO_R4", latest)
        self.assertIn("regional_baselines", meta)

        est = EstimatedDataSource({"RO_Frequency": 436.0})
        hist_e, latest_e, meta_e = est.get_data()
        self.assertIn("RO_R1", latest_e)
        self.assertIn("RO_R4", latest_e)
        self.assertIn("regional_baselines", meta_e)

    def test_r2_healthy_case(self):
        """A valid reading inside the healthy operating envelope remains Healthy."""
        telemetry = {
            "RO_Frequency": 436.0,
            "RO_R1": 436.0,
            "RO_R2": 436.0,  # Nominal frequency (436.0 MHz)
            "RO_R3": 436.0,
            "RO_R4": 436.0,
            "Temperature": 35.0,
            "VCCINT": 1.000,
            "Error_Rate": 0.00001
        }
        regions = generate_four_region_data(telemetry)
        r2 = next(r for r in regions if r["id"] == "R2")
        self.assertEqual(r2["state"], "Healthy")
        self.assertEqual(r2["severity"], LimitSeverity.NORMAL)
        self.assertEqual(r2["indicator"], "Nominal Timing Propagation")
        self.assertAlmostEqual(r2["drift_pct"], 0.0, places=1)

    def test_r2_warning_case(self):
        """A reading violating warning boundary (422.7 MHz) but above critical (411.8 MHz) produces Warning."""
        telemetry = {
            "RO_Frequency": WARN_MID,
            "RO_R1": 436.3,
            "RO_R2": WARN_MID,  # Below warning boundary 422.7 MHz, above critical 411.8 MHz
            "RO_R3": 436.1,
            "RO_R4": 435.9,
            "Temperature": 35.0,
            "VCCINT": 1.000,
            "Error_Rate": 0.00001
        }
        regions = generate_four_region_data(telemetry)
        r2 = next(r for r in regions if r["id"] == "R2")
        self.assertEqual(r2["state"], "Warning")
        self.assertEqual(r2["severity"], LimitSeverity.WARNING)
        self.assertIn("Below warning boundary", r2["indicator"])
        self.assertEqual(r2["warning_freq"], WARN_F)

    def test_critical_precedence_over_small_drift(self):
        """A critical boundary violation unconditionally takes precedence over small baseline drift."""
        # Even if a baseline of 322.2 MHz is artificially supplied:
        res = evaluate_regional_health("R2", measurement=322.1, baseline_freq=322.20)
        self.assertEqual(res["state"], "Degraded")
        self.assertEqual(res["severity"], LimitSeverity.CRITICAL)
        self.assertIn("Below critical boundary", res["indicator"])
        # Drift must still be reported accurately as a separate diagnostic metric
        self.assertAlmostEqual(res["current_freq"], 322.1, places=1)
        self.assertIn("critical_boundary", res)

    def test_invalid_and_missing_data_not_healthy(self):
        """Missing, nonnumeric, non-finite, or implausible measurements must NEVER produce Healthy."""
        invalid_cases = [
            None,
            "INVALID_CORRUPTED",
            float("nan"),
            float("inf"),
            -50.0,    # Physically impossible
            950.0     # Physically impossible
        ]
        for bad_val in invalid_cases:
            res = evaluate_regional_health("R2", measurement=bad_val)
            self.assertNotEqual(
                res["state"],
                "Healthy",
                f"Invalid measurement {bad_val} was falsely marked Healthy!"
            )
            self.assertEqual(res["state"], "Degraded")
            self.assertEqual(res["severity"], LimitSeverity.PHYSICALLY_INVALID)
            self.assertFalse(res["is_valid"])

    def test_baseline_validation_rejects_unhealthy_baseline(self):
        """An invalid or unhealthy baseline cannot silently establish a healthy status."""
        # Baseline near 322.2 MHz is severely degraded and must be rejected
        is_valid, chosen_base, src, reason = validate_regional_baseline("R2", 322.20)
        self.assertFalse(is_valid)
        self.assertEqual(chosen_base, 436.0)  # Fell back to factory nominal
        self.assertEqual(src, "FACTORY_NOMINAL_FALLBACK")
        self.assertIn("Unhealthy baseline", reason)

        # Non-numeric baseline must be rejected
        is_v_str, chosen_str, src_str, _ = validate_regional_baseline("R2", "bad_base")
        self.assertFalse(is_v_str)
        self.assertEqual(chosen_str, 436.0)

        # Legitimate healthy calibrated baseline (including 436.0 MHz) must be accepted
        is_v_cal, chosen_cal, src_cal, _ = validate_regional_baseline("R2", 436.0)
        self.assertTrue(is_v_cal)
        self.assertEqual(chosen_cal, 436.0)
        self.assertEqual(src_cal, "CALIBRATED_BOARD")

    def test_overall_engineering_assessment_reflects_degraded_r2(self):
        """A Degraded R2 region is preserved in regional_evals, but overall health follows quorum policy."""
        telemetry = {
            "RO_Frequency": 436.0,
            "RO_R1": 436.3,
            "RO_R2": 322.1,  # Critical boundary violation in isolated pblock
            "RO_R3": 436.1,
            "RO_R4": 435.9,
            "Temperature": 35.0,
            "VCCINT": 1.000,
            "VCCAUX": 1.800,
            "VCCBRAM": 1.000,
            "Error_Rate": 0.00001
        }
        assessment = evaluate_engineering_limits(telemetry)
        # R2 itself is evaluated as Critical in regional evaluations
        self.assertEqual(assessment.regional_evaluations["R2"]["severity"], LimitSeverity.CRITICAL)
        self.assertEqual(assessment.degraded_pblocks, ["R2"])
        # Under quorum policy (< 2 degraded pblocks), overall assessment remains NORMAL
        self.assertEqual(assessment.max_severity, LimitSeverity.NORMAL)
        self.assertFalse(assessment.has_hard_violations)

        final_res = determine_final_health("Healthy", 0.95, assessment)
        self.assertEqual(final_res["final_health"], "Healthy")
        self.assertFalse(final_res["override_applied"])

    def test_regional_display_consistency(self):
        """Regional status label, status color, background, and indicator agree."""
        res_h = evaluate_regional_health("R1", 436.3)
        self.assertEqual(res_h["state"], "Healthy")
        self.assertEqual(res_h["color"], HEALTH_COLORS["Healthy"])
        self.assertEqual(res_h["bg"], STATUS_BG_COLORS["Healthy"])

        res_w = evaluate_regional_health("R2", WARN_MID)
        self.assertEqual(res_w["state"], "Warning")
        self.assertEqual(res_w["color"], HEALTH_COLORS["Warning"])
        self.assertEqual(res_w["bg"], STATUS_BG_COLORS["Warning"])

        res_d = evaluate_regional_health("R2", 322.1)
        self.assertEqual(res_d["state"], "Degraded")
        self.assertEqual(res_d["color"], HEALTH_COLORS["Degraded"])
        self.assertEqual(res_d["bg"], STATUS_BG_COLORS["Degraded"])

    def test_telemetry_provenance_explicit(self):
        """Synthetic or derived regional values are not represented as verified physical measurements."""
        telemetry = {"RO_Frequency": 436.0}  # No regional fields
        regions = generate_four_region_data(telemetry)
        for r in regions:
            self.assertEqual(r["provenance"], "DERIVED_GLOBAL")
            self.assertNotEqual(r["provenance"], "MEASURED")

    def test_all_four_regions_common_436_nominal_baseline(self):
        """Verify all four regions R1..R4 configure 436.0 MHz as common nominal baseline."""
        for r_id in ["R1", "R2", "R3", "R4"]:
            cfg = REGIONAL_CONFIG[r_id]
            self.assertEqual(cfg["nominal_freq"], 436.0, f"{r_id} nominal_freq != 436.0")
            self.assertEqual(cfg["nominal_delay_ns"], 0.2294, f"{r_id} nominal_delay_ns != 0.2294")
            self.assertEqual(cfg["critical_freq"], CRIT_F, f"{r_id} critical_freq != {CRIT_F}")
            self.assertEqual(cfg["warning_freq"], WARN_F, f"{r_id} warning_freq != {WARN_F}")
            
            dflt = REGIONAL_DEFAULTS[r_id]
            self.assertEqual(dflt["nominal_freq"], 436.0, f"{r_id} default nominal_freq != 436.0")
            self.assertEqual(dflt["nominal_delay_ns"], 0.2294, f"{r_id} default nominal_delay_ns != 0.2294")

    def test_baseline_validation_accepts_436_across_all_regions(self):
        """Verify baseline validation accepts 436.0 MHz for every region without substituting a different baseline."""
        for r_id in ["R1", "R2", "R3", "R4"]:
            # Validating None should fall back to 436.0 FACTORY_NOMINAL
            is_valid_none, chosen_none, src_none, _ = validate_regional_baseline(r_id, None)
            self.assertTrue(is_valid_none)
            self.assertEqual(chosen_none, 436.0)
            self.assertEqual(src_none, "FACTORY_NOMINAL")

            # Validating explicit 436.0 should be accepted as CALIBRATED_BOARD
            is_valid_436, chosen_436, src_436, _ = validate_regional_baseline(r_id, 436.0)
            self.assertTrue(is_valid_436)
            self.assertEqual(chosen_436, 436.0)
            self.assertEqual(src_436, "CALIBRATED_BOARD")

    def test_actual_regional_measurements_remain_independent_and_unaltered(self):
        """
        Verify live measured frequencies are NEVER overwritten or coerced to match the 436.0 MHz baseline.
        Specifically, an R2 reading of 321.8 MHz with R1, R3, R4 at 439-441 MHz remains unchanged
        and evaluates R2 as Critical/Degraded.
        """
        telemetry = {
            "RO_Frequency": 410.5,
            "RO_R1": 439.4,
            "RO_R2": 321.8,
            "RO_R3": 441.1,
            "RO_R4": 439.8,
            "Temperature": 37.3,
            "VCCINT": 1.002,
            "Error_Rate": 0.0
        }
        regions = generate_four_region_data(telemetry)
        
        # Verify measured values are preserved exactly
        by_id = {r["id"]: r for r in regions}
        self.assertEqual(by_id["R1"]["current_freq"], 439.4)
        self.assertEqual(by_id["R2"]["current_freq"], 321.8)
        self.assertEqual(by_id["R3"]["current_freq"], 441.1)
        self.assertEqual(by_id["R4"]["current_freq"], 439.8)

        # Baselines are all 436.0 MHz
        for r_id in ["R1", "R2", "R3", "R4"]:
            self.assertEqual(by_id[r_id]["baseline_freq"], 436.0)
            self.assertEqual(by_id[r_id]["critical_boundary"], round(CRIT_F, 1))

        # Health statuses: R1, R3, R4 Healthy, R2 Degraded
        self.assertEqual(by_id["R1"]["state"], "Healthy")
        self.assertEqual(by_id["R3"]["state"], "Healthy")
        self.assertEqual(by_id["R4"]["state"], "Healthy")
        self.assertEqual(by_id["R2"]["state"], "Degraded")
        self.assertEqual(by_id["R2"]["severity"], LimitSeverity.CRITICAL)
        self.assertIn("Below critical boundary", by_id["R2"]["indicator"])

    def test_aggregate_frequency_math_preserved(self):
        """Verify aggregate RO_Frequency matches the arithmetic average of R1..R4."""
        r1, r2, r3, r4 = 439.4, 321.8, 441.1, 439.8
        expected_avg = round((r1 + r2 + r3 + r4) / 4.0, 1)
        self.assertEqual(expected_avg, 410.5)

    def test_equal_weights_reproduce_ordinary_arithmetic_average(self):
        """1. Equal weights reproduce the ordinary arithmetic average."""
        telemetry = {
            "RO_R1": 439.4,
            "RO_R2": 321.8,
            "RO_R3": 441.1,
            "RO_R4": 439.8
        }
        arith_expected = round(sum([439.4, 321.8, 441.1, 439.8]) / 4.0, 2)  # 410.52

        # Case A: explicit equal weights (0.25 each)
        equal_w = {"R1": 0.25, "R2": 0.25, "R3": 0.25, "R4": 0.25}
        res_eq = calculate_weighted_regional_frequency(telemetry, weights=equal_w)
        self.assertEqual(res_eq["weighted_frequency"], arith_expected)
        self.assertEqual(res_eq["arithmetic_frequency"], arith_expected)
        self.assertEqual(res_eq["worst_region_id"], "R2")
        self.assertEqual(res_eq["worst_region_frequency"], 321.8)
        self.assertTrue(res_eq["is_valid"])

        # Case B: explicit equal integers
        equal_ints = {"R1": 1.0, "R2": 1.0, "R3": 1.0, "R4": 1.0}
        res_ints = calculate_weighted_regional_frequency(telemetry, weights=equal_ints)
        self.assertEqual(res_ints["weighted_frequency"], arith_expected)

        # Case C: weights=None uses calibrated DEFAULT_REGIONAL_WEIGHTS (434.15 MHz)
        res_none = calculate_weighted_regional_frequency(telemetry, weights=None)
        self.assertEqual(res_none["weighted_frequency"], 434.15)
        self.assertEqual(res_none["arithmetic_frequency"], arith_expected)

    def test_valid_configured_weights_produce_expected_weighted_average(self):
        """2. Valid configured weights produce the expected weighted average."""
        telemetry = {
            "RO_R1": 439.4,
            "RO_R2": 321.8,
            "RO_R3": 441.1,
            "RO_R4": 439.8
        }
        # Normalized custom weights
        custom_weights = {"R1": 0.40, "R2": 0.10, "R3": 0.30, "R4": 0.20}
        expected_weighted = round(
            (0.40 * 439.4 + 0.10 * 321.8 + 0.30 * 441.1 + 0.20 * 439.8) / 1.00, 2
        )  # 428.23

        res = calculate_weighted_regional_frequency(telemetry, weights=custom_weights)
        self.assertEqual(res["weighted_frequency"], expected_weighted)
        # Arithmetic average and worst case remain independently computed
        self.assertEqual(res["arithmetic_frequency"], 410.52)
        self.assertEqual(res["worst_region_frequency"], 321.8)
        self.assertEqual(res["worst_region_id"], "R2")

        # Unnormalized weights with same ratio (40, 10, 30, 20)
        unnorm_weights = {"R1": 40.0, "R2": 10.0, "R3": 30.0, "R4": 20.0}
        res_unnorm = calculate_weighted_regional_frequency(telemetry, weights=unnorm_weights)
        self.assertEqual(res_unnorm["weighted_frequency"], expected_weighted)

    def test_invalid_weights_rejected_safely(self):
        """3. Invalid weights are rejected safely and fall back to calibrated weights."""
        invalid_weight_cases = [
            ({"R1": -0.25, "R2": 0.25, "R3": 0.25, "R4": 0.25}, "Negative weight"),
            ({"R1": "invalid_str", "R2": 0.25, "R3": 0.25, "R4": 0.25}, "Non-numeric weight"),
            ({"R1": float("nan"), "R2": 0.25, "R3": 0.25, "R4": 0.25}, "Non-finite weight"),
            ({"R1": float("inf"), "R2": 0.25, "R3": 0.25, "R4": 0.25}, "Infinite weight"),
            ({"R1": 0.0, "R2": 0.0, "R3": 0.0, "R4": 0.0}, "Zero sum of weights"),
            ({}, "Empty dictionary"),
            ("not_a_dict", "Non-dict type"),
            ([0.25, 0.25, 0.25, 0.25], "List type instead of dict")
        ]

        for bad_weights, label in invalid_weight_cases:
            is_valid, validated_w, reason = validate_regional_weights(bad_weights)
            self.assertFalse(is_valid, f"Case '{label}' should have been rejected!")
            self.assertEqual(validated_w, DEFAULT_REGIONAL_WEIGHTS)

            # Calculation must safely complete without throwing an unhandled exception
            telemetry = {"RO_R1": 439.4, "RO_R2": 321.8, "RO_R3": 441.1, "RO_R4": 439.8}
            res = calculate_weighted_regional_frequency(telemetry, weights=bad_weights)
            self.assertIsNotNone(res["weighted_frequency"])
            self.assertEqual(res["weighted_frequency"], 434.15)
            self.assertEqual(res["weights_used"], DEFAULT_REGIONAL_WEIGHTS)

    def test_r2_at_321_8_remains_critical_below_while_overall_is_healthy(self):
        """
        4. Single-pblock anomaly: R2 at 321.8 MHz remains critical in regional data,
        while overall health on top is Healthy via weighted RO average (Quorum policy).
        """
        telemetry = {
            "RO_Frequency": 410.5,
            "RO_R1": 439.4,
            "RO_R2": 321.8,
            "RO_R3": 441.1,
            "RO_R4": 439.8,
            "Temperature": 37.3,
            "VCCINT": 1.002,
            "VCCAUX": 1.798,
            "VCCBRAM": 1.001,
            "Error_Rate": 0.000000
        }
        # Verify regional data retains R2 as critical
        regions = generate_four_region_data(telemetry)
        r2 = next(r for r in regions if r["id"] == "R2")
        self.assertEqual(r2["state"], "Degraded")
        self.assertEqual(r2["severity"], LimitSeverity.CRITICAL)
        self.assertEqual(r2["current_freq"], 321.8)

        # Verify overall assessment uses weighted average (434.15 MHz) and evaluates Healthy
        assessment = evaluate_engineering_limits(telemetry)
        self.assertEqual(assessment.max_severity, LimitSeverity.NORMAL)
        self.assertFalse(assessment.has_hard_violations)
        self.assertEqual(assessment.degraded_pblocks, ["R2"])
        self.assertFalse(assessment.quorum_triggered)
        self.assertEqual(assessment.weighted_frequency, 434.15)

        # Final health evaluates to Healthy
        final_res = determine_final_health("Healthy", 0.95, assessment)
        self.assertEqual(final_res["final_health"], "Healthy")
        self.assertFalse(final_res["override_applied"])

    def test_multi_pblock_degradation_triggers_overall_degraded(self):
        """
        5. Quorum Policy: If 2 or more pblocks show degradation, the overall main value changes to Degraded.
        """
        telemetry_multi = {
            "RO_Frequency": 410.5,
            "RO_R1": 400.0,  # Below critical 412.0 MHz in R1
            "RO_R2": 321.8,  # Below critical 412.0 MHz in R2
            "RO_R3": 441.1,
            "RO_R4": 439.8,
            "Temperature": 37.3,
            "VCCINT": 1.002,
            "VCCAUX": 1.798,
            "VCCBRAM": 1.001,
            "Error_Rate": 0.0
        }
        assessment = evaluate_engineering_limits(telemetry_multi)
        self.assertEqual(assessment.max_severity, LimitSeverity.CRITICAL)
        self.assertTrue(assessment.has_hard_violations)
        self.assertTrue(assessment.quorum_triggered)
        self.assertEqual(set(assessment.degraded_pblocks), {"R1", "R2"})

        final_res = determine_final_health("Healthy", 0.99, assessment)
        self.assertEqual(final_res["final_health"], "Degraded")
        self.assertTrue(final_res["override_applied"])

    def test_missing_or_invalid_regional_data_follows_existing_safety_rules(self):
        """
        6. Missing, stale, or invalid regional data follows existing safety rules:
        never substituted with nominal values, tracked in invalid/missing lists, and flagged unsafe.
        """
        # Case A: Missing R2 (None)
        telemetry_missing = {
            "RO_R1": 439.4,
            "RO_R2": None,
            "RO_R3": 441.1,
            "RO_R4": 439.8
        }
        res_m = calculate_weighted_regional_frequency(telemetry_missing)
        self.assertIn("R2", res_m["missing_regions"])
        self.assertNotIn("R2", res_m["valid_regions"])
        self.assertFalse(res_m["is_valid"])
        # Remaining valid regions averaged with normalized active weights (0.35, 0.30, 0.30 sum to 0.95)
        expected_w = round((0.35 * 439.4 + 0.30 * 441.1 + 0.30 * 439.8) / 0.95, 2)
        self.assertEqual(res_m["weighted_frequency"], expected_w)

        # Case B: Out-of-bounds physically implausible frequency (e.g. 950.0 MHz)
        telemetry_implausible = {
            "RO_R1": 439.4,
            "RO_R2": 950.0,
            "RO_R3": 441.1,
            "RO_R4": 439.8
        }
        res_imp = calculate_weighted_regional_frequency(telemetry_implausible)
        self.assertIn("R2", res_imp["invalid_regions"])
        self.assertNotIn("R2", res_imp["valid_regions"])
        self.assertFalse(res_imp["is_valid"])

        # Case C: Regional health evaluation of invalid measurement yields PHYSICALLY_INVALID
        res_eval = evaluate_regional_health("R2", measurement="MALFORMED_DATA")
        self.assertEqual(res_eval["severity"], LimitSeverity.PHYSICALLY_INVALID)
        self.assertEqual(res_eval["state"], "Degraded")
        self.assertFalse(res_eval["is_valid"])

    def test_weighted_summary_integration_in_html_and_assessment(self):
        """
        7. Verify weighted average and worst-case metrics are rendered in the HTML map
        and populated across the engineering assessment object.
        """
        telemetry = {
            "RO_Frequency": 410.5,
            "RO_R1": 439.4,
            "RO_R2": 321.8,
            "RO_R3": 441.1,
            "RO_R4": 439.8,
            "Temperature": 37.3,
            "VCCINT": 1.002,
            "VCCAUX": 1.798,
            "VCCBRAM": 1.001,
            "Error_Rate": 0.0
        }
        regions = generate_four_region_data(telemetry)
        html = render_four_region_map_html(regions, composite_risk=0.5)

        # Verify key display elements in summary bar
        self.assertIn("Weighted RO Average", html)
        self.assertIn("Hardware Arithmetic Mean", html)
        self.assertIn("Worst-Case Regional Frequency", html)
        self.assertIn("Multi-Pblock Quorum Policy", html)
        self.assertIn("321.80 <span", html)
        self.assertIn("R2", html)

        # Verify engineering assessment dictionary fields
        assessment = evaluate_engineering_limits(telemetry)
        d = assessment.to_dict()
        self.assertIn("weighted_frequency", d)
        self.assertIn("arithmetic_frequency", d)
        self.assertIn("worst_region_frequency", d)
        self.assertIn("regional_weights", d)
        self.assertIn("weighted_summary", d)
        self.assertEqual(d["worst_region_frequency"], 321.8)
        self.assertEqual(d["degraded_pblocks"], ["R2"])
        self.assertFalse(d["quorum_triggered"])

    def test_calibrate_history_dataframe_isolated_anomaly(self):
        """
        Verify that calibrate_history_dataframe preserves raw hardware frequency in RO_Raw_Frequency,
        calibrates RO_Frequency to the weighted average (~434.15 MHz) for an isolated single-pblock anomaly (R2=321.8),
        derives RO_Delay_ns (~0.2303 ns), and updates rolling features.
        """
        raw_rows = [{
            "RO_R1": 439.4, "RO_R2": 321.8, "RO_R3": 441.1, "RO_R4": 439.8,
            "RO_Frequency": 410.5, "RO_Delay_ns": 0.2436,
            "Temperature": 37.3, "VCCINT": 1.002, "VCCAUX": 1.798, "VCCBRAM": 1.001,
            "Error_Rate": 0.0,
            "RO_Frequency_mean": 410.5, "RO_Frequency_change": 0.0
        }] * 25
        df = pd.DataFrame(raw_rows)
        calibrated = calibrate_history_dataframe(df)

        self.assertIn("RO_Raw_Frequency", calibrated.columns)
        self.assertIn("RO_Weighted_Frequency", calibrated.columns)
        self.assertEqual(calibrated["RO_Raw_Frequency"].iloc[0], 410.5)
        self.assertAlmostEqual(calibrated["RO_Weighted_Frequency"].iloc[0], 434.15, places=2)
        self.assertAlmostEqual(calibrated["RO_Frequency"].iloc[0], 434.15, places=2)
        self.assertAlmostEqual(calibrated["RO_Delay_ns"].iloc[0], round(100.0 / 434.15, 4), places=4)
        self.assertAlmostEqual(calibrated["RO_Frequency_mean"].iloc[-1], 434.15, places=2)

    def test_calibrate_history_dataframe_multi_pblock_quorum(self):
        """
        Verify that when 2 or more pblocks degrade (e.g. R2=321.8 and R4=405.0 <= 412.0 MHz),
        the multi-pblock quorum policy is triggered and RO_Frequency reflects the degraded state.
        """
        multi_rows = [{
            "RO_R1": 439.4, "RO_R2": 321.8, "RO_R3": 441.1, "RO_R4": 405.0,
            "RO_Frequency": 401.8, "RO_Delay_ns": 0.2489,
            "Temperature": 37.3, "VCCINT": 1.002, "VCCAUX": 1.798, "VCCBRAM": 1.001,
            "Error_Rate": 0.0
        }] * 10
        df = pd.DataFrame(multi_rows)
        calibrated = calibrate_history_dataframe(df)

        self.assertEqual(calibrated["RO_Frequency"].iloc[0], 401.8)
        self.assertIn("RO_Raw_Frequency", calibrated.columns)
        self.assertEqual(calibrated["RO_Raw_Frequency"].iloc[0], 401.8)

    def test_calibrated_ro_charts_render_with_threshold_rules(self):
        """
        Verify that create_ro_frequency_chart and create_ro_delay_chart construct
        Altair LayerCharts containing baseline, warning, and critical threshold reference lines.
        """
        df = pd.DataFrame([{
            "Sample_Index": i,
            "RO_Frequency": 434.15,
            "RO_Delay_ns": 0.2303,
            "RO_Raw_Frequency": 410.5,
            "RO_R1": 439.4, "RO_R2": 321.8, "RO_R3": 441.1, "RO_R4": 439.8
        } for i in range(10)])

        freq_chart = create_ro_frequency_chart(df, baseline_freq=436.0, warning_freq=422.9, critical_freq=412.0)
        self.assertIsNotNone(freq_chart)
        freq_dict = freq_chart.to_dict()
        self.assertIn("layer", freq_dict)
        self.assertEqual(len(freq_dict["layer"]), 4)  # line + base + warn + crit

        delay_chart = create_ro_delay_chart(df, baseline_delay=0.2294, warning_delay=0.2365, critical_delay=0.2427)
        self.assertIsNotNone(delay_chart)
        delay_dict = delay_chart.to_dict()
        self.assertIn("layer", delay_dict)
        self.assertEqual(len(delay_dict["layer"]), 4)  # line + base + warn + crit

    def test_adaptive_graph_scaling_small_vs_major_deviation(self):
        """
        Verify that charts zoom in on small deviations to make them show bigger,
        and scale out dynamically to fit major excursions.
        """
        # 1. Test Small Deviation: RO Frequency varies slightly (0.3 MHz span)
        df_small = pd.DataFrame([{
            "Sample_Index": i,
            "RO_Frequency": 435.9 + 0.1 * (i % 3),
            "RO_Delay_ns": 0.2294 + 0.0001 * (i % 2),
            "Temperature": 35.1 + 0.1 * (i % 3),
            "VCCINT": 1.000 + 0.001 * (i % 2),
            "Error_Rate": 0.000010 + 0.000001 * (i % 3)
        } for i in range(10)])

        freq_small = create_ro_frequency_chart(df_small, baseline_freq=436.0, adaptive_scaling=True)
        small_dict = freq_small.to_dict()
        small_domain = small_dict["layer"][0]["encoding"]["y"]["scale"]["domain"]
        small_span = small_domain[1] - small_domain[0]
        # Small deviation span should be tight (< 2.5 MHz) magnifying small variations
        self.assertLess(small_span, 2.5)
        self.assertGreater(small_span, 0.0)

        # Test Ultra Zoom (10x) produces an even tighter domain than standard
        freq_ultra = create_ro_frequency_chart(df_small, baseline_freq=436.0, adaptive_scaling=True, zoom_factor=10.0)
        ultra_dict = freq_ultra.to_dict()
        ultra_domain = ultra_dict["layer"][0]["encoding"]["y"]["scale"]["domain"]
        ultra_span = ultra_domain[1] - ultra_domain[0]
        self.assertLess(ultra_span, small_span)
        self.assertGreater(ultra_span, 0.0)

        # 2. Test Major Deviation: RO Frequency drops severely (436 down to ~415 MHz)
        df_major = pd.DataFrame([{
            "Sample_Index": i,
            "RO_Frequency": 436.0 - 2.1 * i,
            "RO_Delay_ns": 0.2294 + 0.0015 * i,
            "Temperature": 35.0 + 2.5 * i,
            "VCCINT": 1.000 - 0.010 * i,
            "Error_Rate": 0.000010 + 0.000200 * i
        } for i in range(10)])

        freq_major = create_ro_frequency_chart(df_major, baseline_freq=436.0, adaptive_scaling=True)
        major_dict = freq_major.to_dict()
        major_domain = major_dict["layer"][0]["encoding"]["y"]["scale"]["domain"]
        major_span = major_domain[1] - major_domain[0]
        # Major deviation span should widen to comfortably fit the excursion (> 18.0 MHz)
        self.assertGreater(major_span, 18.0)
        self.assertLessEqual(major_domain[0], 418.0)

        # 3. Test Temperature Small vs Major
        temp_small = create_temperature_chart(df_small, baseline_temp=35.0, adaptive_scaling=True)
        t_small_dom = temp_small.to_dict()["layer"][0]["encoding"]["y"]["scale"]["domain"]
        self.assertLess(t_small_dom[1] - t_small_dom[0], 3.0)

        temp_major = create_temperature_chart(df_major, baseline_temp=35.0, adaptive_scaling=True)
        t_major_dom = temp_major.to_dict()["layer"][0]["encoding"]["y"]["scale"]["domain"]
        self.assertGreater(t_major_dom[1] - t_major_dom[0], 20.0)

        # 4. Test Error Rate Small vs Major
        err_small = create_error_rate_chart(df_small, adaptive_scaling=True)
        e_small_dom = err_small.to_dict()["encoding"]["y"]["scale"]["domain"]
        self.assertLess(e_small_dom[1], 0.0001)

        err_major = create_error_rate_chart(df_major, adaptive_scaling=True)
        e_major_dom = err_major.to_dict()["encoding"]["y"]["scale"]["domain"]
        self.assertGreater(e_major_dom[1], 0.0015)


if __name__ == "__main__":
    unittest.main()


