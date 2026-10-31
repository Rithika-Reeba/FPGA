"""
Unit & Integration Test Suite for FPGA UART Hardware Interface
==============================================================
Tests:
 1. COM Port enumeration & discovery.
 2. Handshake message parsing ("HELLO FPGA").
 3. JSON telemetry parsing with fixed-point floating precision.
 4. Physical derivation of Ring Oscillator stage delay (tau = 100 / f_MHz).
 5. Key-Value fallback string parsing.
 6. Malformed / corrupted serial packet rejection.
 7. Out-of-bounds sensor reading rejection.
 8. Stale data detection and connection state machine transitions.
 9. Field-level telemetry provenance tracking (MEASURED vs DERIVED).
10. LiveUARTDataSource rolling buffer and running baseline calibration.
11. End-to-End Hardware Pipeline -> Validation -> ML Model -> LangGraph Agent.
"""

import os
os.environ["FPGA_CALIBRATION"] = "none"   # tests use the placeholder nominal, never a board calibration
import sys
import time
import unittest
from pathlib import Path
import pandas as pd
import joblib

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import calculate_ro_delay_ns, RO_STAGES
from communication.uart_receiver import FPGAUARTReceiver, ConnectionState
from dashboard.data_source import LiveUARTDataSource, validate_and_clean_data
from ml.feature_engineering import create_features
from agent.langgraph_agent import evaluate_fpga_health


class TestFPGAPhysicalUART(unittest.TestCase):

    def setUp(self):
        self.receiver = FPGAUARTReceiver(port="COM3", baudrate=115200, timeout=0.5, stale_threshold_sec=1.0)
        self.data_source = LiveUARTDataSource(port="COM3", baudrate=115200, buffer_size=100)
        self.model_path = PROJECT_ROOT / "ml" / "models" / "fpga_health_model.pkl"
        if self.model_path.exists():
            bundle = joblib.load(self.model_path)
            self.model = bundle["model"]
            self.features = bundle["features"]
        else:
            self.model = None
            self.features = None

    # -------------------------------------------------------------------------
    # Test 1: Port Enumeration & Discovery
    # -------------------------------------------------------------------------
    def test_port_enumeration(self):
        ports = FPGAUARTReceiver.list_available_ports()
        self.assertIsInstance(ports, list)
        if not ports:
            self.skipTest("no serial port is connected (this test needs hardware)")

        detailed = FPGAUARTReceiver.list_detailed_ports()
        self.assertIsInstance(detailed, list)

        # Test system-wide port scanner
        scanned = FPGAUARTReceiver.scan_all_ports_detailed(current_receiver=self.receiver, probe_telemetry=False)
        self.assertIsInstance(scanned, list)
        if not scanned:
            self.skipTest("no serial port is connected (this test needs hardware)")
        for item in scanned:
            self.assertIn("device", item)
            self.assertIn("category", item)
            self.assertIn("status_label", item)
            self.assertIn("is_usb", item)
            self.assertIn("is_bluetooth", item)

    def test_device_classification_signatures(self):
        class DummyPort:
            def __init__(self, desc, hwid, vid=None, pid=None, mfg=None):
                self.description = desc
                self.hwid = hwid
                self.vid = vid
                self.pid = pid
                self.manufacturer = mfg

        # Basys 3 FTDI FT2232
        p1 = DummyPort("USB Serial Port (COM10)", "USB VID:PID=0403:6010 SER=210183B3150CB", 0x0403, 0x6010, "FTDI")
        cat1, _, is_usb1 = FPGAUARTReceiver._classify_port_device(p1)
        self.assertIn("Basys 3", cat1)
        self.assertTrue(is_usb1)

        # CP210x Bridge
        p2 = DummyPort("Silicon Labs CP210x USB to UART Bridge", "USB VID:PID=10C4:EA60", 0x10C4, 0xEA60, "Silicon Labs")
        cat2, _, is_usb2 = FPGAUARTReceiver._classify_port_device(p2)
        self.assertIn("CP210x", cat2)
        self.assertTrue(is_usb2)

        # Bluetooth Virtual Link
        p3 = DummyPort("Standard Serial over Bluetooth link (COM5)", "BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}", None, None, "Microsoft")
        cat3, _, is_usb3 = FPGAUARTReceiver._classify_port_device(p3)
        self.assertIn("Bluetooth", cat3)
        self.assertFalse(is_usb3)

    def test_probe_port_safety(self):
        # Probing a non-existent COM port should return clean status without crashing
        res = FPGAUARTReceiver.probe_port("COM999", timeout=0.1)
        self.assertIn(res["status"], ["NOT_FOUND", "ERROR"])
        self.assertFalse(res["telemetry"])


    # -------------------------------------------------------------------------
    # Test 2: Handshake Message Parsing ("HELLO FPGA")
    # -------------------------------------------------------------------------
    def test_handshake_message_parsing(self):
        # Simulate receiving the Basys 3 startup handshake banner
        raw_banner = "HELLO FPGA - Basys 3 Artix-7 Health Monitor Online"
        
        # When passed into the line parser
        parsed = self.receiver._parse_raw_line(raw_banner)
        # Should not treat banner as raw numerical telemetry
        self.assertIsNone(parsed)

    # -------------------------------------------------------------------------
    # Test 3: JSON Telemetry Parsing (Single and Four-Region Architecture)
    # -------------------------------------------------------------------------
    def test_valid_json_packet_parsing(self):
        sample_json = (
            '{"Temperature":36.4,"VCCINT":1.002,"VCCAUX":1.801,'
            '"VCCBRAM":1.000,"RO_Frequency":436.0,"Error_Rate":0.000015}'
        )
        parsed = self.receiver._parse_raw_line(sample_json)
        self.assertIsNotNone(parsed)
        self.assertAlmostEqual(parsed["Temperature"], 36.4, places=2)
        self.assertAlmostEqual(parsed["VCCINT"], 1.002, places=3)
        self.assertAlmostEqual(parsed["VCCAUX"], 1.801, places=3)
        self.assertAlmostEqual(parsed["VCCBRAM"], 1.000, places=3)
        self.assertAlmostEqual(parsed["RO_Frequency"], 436.0, places=2)
        self.assertAlmostEqual(parsed["Error_Rate"], 0.000015, places=6)

        # Verified physical derivation of RO stage delay
        expected_tau = round(100.0 / 436.0, 4)
        self.assertAlmostEqual(parsed["RO_Delay_ns"], expected_tau, places=4)
        # Backward compatibility: R1..R4 populated with RO_Frequency if omitted
        self.assertAlmostEqual(parsed["RO_R1"], 436.0, places=2)
        self.assertAlmostEqual(parsed["RO_R2"], 436.0, places=2)
        self.assertAlmostEqual(parsed["RO_R3"], 436.0, places=2)
        self.assertAlmostEqual(parsed["RO_R4"], 436.0, places=2)

    def test_four_region_json_telemetry_parsing(self):
        # Full four-region telemetry packet from Basys 3 hardware
        four_region_json = (
            '{"Temperature":35.8,"VCCINT":1.000,"VCCAUX":1.791,"VCCBRAM":0.999,'
            '"RO_R1":436.3,"RO_R2":435.8,"RO_R3":436.1,"RO_R4":435.9,'
            '"RO_Frequency":436.0,"Error_Rate":0.000000}'
        )
        parsed = self.receiver._parse_raw_line(four_region_json)
        self.assertIsNotNone(parsed)
        self.assertAlmostEqual(parsed["Temperature"], 35.8, places=2)
        self.assertAlmostEqual(parsed["VCCINT"], 1.000, places=3)
        self.assertAlmostEqual(parsed["RO_R1"], 436.3, places=2)
        self.assertAlmostEqual(parsed["RO_R2"], 435.8, places=2)
        self.assertAlmostEqual(parsed["RO_R3"], 436.1, places=2)
        self.assertAlmostEqual(parsed["RO_R4"], 435.9, places=2)
        self.assertAlmostEqual(parsed["RO_Frequency"], 436.0, places=2)

        # Verify regional delay derivations: tau = 100 / f_MHz
        self.assertAlmostEqual(parsed["RO_R1_Delay_ns"], round(100.0 / 436.3, 4), places=4)
        self.assertAlmostEqual(parsed["RO_R2_Delay_ns"], round(100.0 / 435.8, 4), places=4)
        self.assertAlmostEqual(parsed["RO_R3_Delay_ns"], round(100.0 / 436.1, 4), places=4)
        self.assertAlmostEqual(parsed["RO_R4_Delay_ns"], round(100.0 / 435.9, 4), places=4)

        # Verify provenance tags
        prov = parsed["Provenance"]
        self.assertEqual(prov["RO_R1"], "MEASURED")
        self.assertEqual(prov["RO_R1_Delay_ns"], "DERIVED")
        self.assertEqual(prov["RO_R4"], "MEASURED")
        self.assertEqual(prov["RO_R4_Delay_ns"], "DERIVED")


    # -------------------------------------------------------------------------
    # Test 4: Physical Derivation of RO Delay (N=5 stages)
    # -------------------------------------------------------------------------
    def test_ro_delay_derivation_benchmarks(self):
        # Formula: tau = 1000 / (2 * 5 * f_MHz) = 100 / f_MHz
        test_cases = [
            (436.0, 0.2294),  # Physical Basys 3 nominal
            (424.0, 0.2358),  # Timing delay drift (warning region)
            (410.0, 0.2439),  # Severe degradation (degraded region)
            (250.0, 0.4000),  # Historical benchmark
            (240.0, 0.4167),  # Mild degradation (100 / 240 = 0.416666...)
            (235.0, 0.4255),  # Moderate degradation (100 / 235 = 0.425531...)
            (225.0, 0.4444),  # Severe degradation
        ]
        for freq_mhz, exp_delay in test_cases:
            calc_delay = calculate_ro_delay_ns(freq_mhz, stages=RO_STAGES)
            self.assertEqual(calc_delay, exp_delay)

    # -------------------------------------------------------------------------
    # Test 5: Key-Value Fallback Parsing
    # -------------------------------------------------------------------------
    def test_key_value_fallback_parsing(self):
        kv_line = "TEMP:38.2,VCCINT:0.998,VCCAUX:1.795,VCCBRAM:0.999,RO:244.0,ERR:0.000250"
        parsed = self.receiver._parse_raw_line(kv_line)
        self.assertIsNotNone(parsed)
        self.assertAlmostEqual(parsed["Temperature"], 38.2, places=2)
        self.assertAlmostEqual(parsed["VCCINT"], 0.998, places=3)
        self.assertAlmostEqual(parsed["RO_Frequency"], 244.0, places=2)
        self.assertAlmostEqual(parsed["RO_Delay_ns"], round(100.0 / 244.0, 4), places=4)

    # -------------------------------------------------------------------------
    # Test 6: Malformed / Corrupted Serial Packet Rejection
    # -------------------------------------------------------------------------
    def test_malformed_packet_rejection(self):
        corrupted_samples = [
            '{"Temperature":36.4,"VCCINT":}',          # Incomplete JSON
            '{"Temperature": "abc", "VCCINT": 1.0}',     # Non-numeric string
            '{garbage_bytes_xyz}',                      # Corrupted payload
            'TEMP:INVALID,VCCINT:1.0',                  # Non-numeric KV
            '',                                         # Empty string
        ]
        for bad_line in corrupted_samples:
            parsed = self.receiver._parse_raw_line(bad_line)
            self.assertIsNone(parsed, f"Malformed packet was unexpectedly accepted: {bad_line}")

    # -------------------------------------------------------------------------
    # Test 7: Out-of-Bounds Physical Sensor Rejection
    # -------------------------------------------------------------------------
    def test_out_of_bounds_rejection(self):
        out_of_bounds_samples = [
            '{"Temperature":180.0,"VCCINT":1.0,"VCCAUX":1.8,"VCCBRAM":1.0,"RO_Frequency":250.0,"Error_Rate":0.0}', # Temp too high
            '{"Temperature":-20.0,"VCCINT":1.0,"VCCAUX":1.8,"VCCBRAM":1.0,"RO_Frequency":250.0,"Error_Rate":0.0}', # Temp negative
            '{"Temperature":35.0,"VCCINT":3.3,"VCCAUX":1.8,"VCCBRAM":1.0,"RO_Frequency":250.0,"Error_Rate":0.0}',   # VCCINT impossible
            '{"Temperature":35.0,"VCCINT":1.0,"VCCAUX":1.8,"VCCBRAM":1.0,"RO_Frequency":10.0,"Error_Rate":0.0}',    # RO Freq too low
        ]
        for oob_line in out_of_bounds_samples:
            parsed = self.receiver._parse_raw_line(oob_line)
            self.assertIsNone(parsed, f"Out-of-bounds packet was unexpectedly accepted: {oob_line}")

    # -------------------------------------------------------------------------
    # Test 8: Stale Data & Connection State Machine
    # -------------------------------------------------------------------------
    def test_stale_data_detection(self):
        # Simulate receiver in receiving state
        self.receiver.state = ConnectionState.RECEIVING_TELEMETRY
        self.receiver.last_packet_time = time.time() - 2.0  # 2.0s ago (> 1.0s stale threshold)

        # Trigger read attempt when no new data is waiting
        self.receiver.serial_conn = None
        # Diagnostics should report state or time since last packet
        diag = self.receiver.get_diagnostics()
        self.assertGreater(diag["seconds_since_last_packet"], 1.0)

    # -------------------------------------------------------------------------
    # Test 9: Telemetry Provenance Tracking (MEASURED vs DERIVED)
    # -------------------------------------------------------------------------
    def test_telemetry_provenance_tagging(self):
        sample = '{"Temperature":35.5,"VCCINT":1.000,"VCCAUX":1.800,"VCCBRAM":1.000,"RO_Frequency":250.0,"Error_Rate":0.000010}'
        parsed = self.receiver._parse_raw_line(sample)
        self.assertIsNotNone(parsed)

        prov = parsed.get("Provenance", {})
        self.assertEqual(prov["Temperature"], "MEASURED")
        self.assertEqual(prov["VCCINT"], "MEASURED")
        self.assertEqual(prov["VCCAUX"], "MEASURED")
        self.assertEqual(prov["VCCBRAM"], "MEASURED")
        self.assertEqual(prov["RO_Frequency"], "MEASURED")
        self.assertEqual(prov["Error_Rate"], "MEASURED")
        self.assertEqual(prov["RO_Delay_ns"], "DERIVED")

    # -------------------------------------------------------------------------
    # Test 10: LiveUARTDataSource Buffering & Baseline Calibration
    # -------------------------------------------------------------------------
    def test_uart_datasource_buffering_and_baseline(self):
        ds = LiveUARTDataSource(port="COM3", buffer_size=50)

        # Inject 10 simulated hardware packets
        for i in range(10):
            mock_pkt = {
                "Timestamp": time.time() + i,
                "Temperature": 35.0 + 0.1 * i,
                "VCCINT": 1.000,
                "VCCAUX": 1.800,
                "VCCBRAM": 1.000,
                "RO_Frequency": 436.0 - 0.2 * i,
                "RO_Delay_ns": calculate_ro_delay_ns(436.0 - 0.2 * i, RO_STAGES),
                "Error_Rate": 0.000010
            }
            ds.buffer.append(mock_pkt)

        # Compute baseline from first 5 samples
        init_df = pd.DataFrame(ds.buffer[:5])
        ds.baseline_sample = init_df[["Temperature", "VCCINT", "VCCAUX", "VCCBRAM", "RO_Frequency", "RO_Delay_ns", "Error_Rate"]].mean().to_dict()

        history_df, latest, meta = ds.get_data(window_size=20)
        self.assertEqual(len(history_df), 10)
        self.assertEqual(meta["source_type"], "LIVE_UART")
        self.assertIn("baseline", meta)
        self.assertAlmostEqual(meta["baseline"]["Temperature"], 35.2, places=1)
        self.assertEqual(meta["provenance"]["RO_Delay_ns"], "DERIVED")

    # -------------------------------------------------------------------------
    # Test 11: End-to-End Hardware Pipeline Integration
    # -------------------------------------------------------------------------
    def test_end_to_end_hardware_pipeline(self):
        if self.model is None:
            self.skipTest("ML Model bundle not available.")

        # Simulate hardware packet under aging degradation (e.g., heated FPGA + slowed RO)
        deg_json = '{"Temperature":53.0,"VCCINT":0.990,"VCCAUX":1.790,"VCCBRAM":0.992,"RO_Frequency":410.0,"Error_Rate":0.002800}'
        parsed = self.receiver._parse_raw_line(deg_json)
        self.assertIsNotNone(parsed)

        # Build rolling window for feature engineering
        window_records = [dict(parsed) for _ in range(30)]
        raw_df = pd.DataFrame(window_records)

        # Pipeline Stage 1: Validation
        clean_df, is_valid, warnings = validate_and_clean_data(raw_df)
        self.assertTrue(is_valid)

        # Pipeline Stage 2: Feature Engineering (16 features)
        engineered_df = create_features(clean_df)
        for feat in self.features:
            self.assertIn(feat, engineered_df.columns)

        # Pipeline Stage 3: ML Inference (Random Forest)
        X = engineered_df[self.features]
        preds = self.model.predict(X)
        probs = self.model.predict_proba(X)
        latest_pred = str(preds[-1])
        latest_conf = float(probs[-1].max())

        self.assertIn(latest_pred, ["Healthy", "Warning", "Degraded"])

        # Pipeline Stage 4: LangGraph Diagnostic Agent
        agent_input = {
            "health": latest_pred,
            "confidence": latest_conf,
            "temperature": float(parsed["Temperature"]),
            "vccint": float(parsed["VCCINT"]),
            "vccaux": float(parsed["VCCAUX"]),
            "vccbram": float(parsed["VCCBRAM"]),
            "ro_frequency": float(parsed["RO_Frequency"]),
            "ro_delay": float(parsed["RO_Delay_ns"]),
            "error_rate": float(parsed["Error_Rate"]),
            "ro_freq_shift_pct": ((float(parsed["RO_Frequency"]) - 436.0) / 436.0) * 100.0,
            "ro_delay_shift_pct": ((float(parsed["RO_Delay_ns"]) - 0.2294) / 0.2294) * 100.0,
            "temp_shift": float(parsed["Temperature"]) - 35.0,
            "source": "LIVE_UART",
            "completeness_str": "6 / 6",
            "completeness_count": 6,
            "reliability_score": 1.0,
            "user_provided": ["Temperature", "VCCINT", "VCCAUX", "VCCBRAM", "RO_Frequency", "Error_Rate"],
            "derived": ["RO_Delay_ns"],
            "assumed": [],
            "is_estimated": False
        }
        report = evaluate_fpga_health(agent_input)
        self.assertIn("risk_level", report)
        self.assertIn("condition_summary", report)
        self.assertIn("recommended_actions", report)
        self.assertIn("life_extension_suggestions", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
