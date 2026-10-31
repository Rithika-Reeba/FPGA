import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import RO_STAGES, calculate_ro_delay_ns, validate_ro_delay
import health_rules as rules

# ============================================================
# Configuration
# ============================================================

NUM_SAMPLES = 10000
OUTPUT_FILE = PROJECT_ROOT / "data" / "raw" / "mock_fpga_data.csv"

np.random.seed(42)

# The ageing scenario (0..1 timeline) lives in health_rules.py and is shared with the live simulation.


# ============================================================
# Generate one FPGA measurement
# ============================================================

def generate_measurement(timestamp, degradation):
    """
    degradation:
        0.0 = healthy
        0.5 = stressed
        1.0 = degraded

    The Health label is NOT read off the timeline: it is computed from the generated
    sensor values with the same rules every other part of the project uses
    (health_rules.py), so a change to a limit changes the labels on regeneration.
    """

    nominal = rules.RO_PLACEHOLDER_NOMINAL_MHZ

    # Temperature (degC)
    temperature = rules.scenario_temp_c(degradation) + np.random.normal(0, 0.3)

    # Supply voltages (V): small drift, stays inside the +/-5 % band
    vccint = 1.000 - 0.010 * degradation + np.random.normal(0, 0.001)
    vccaux = 1.800 - 0.010 * degradation + np.random.normal(0, 0.001)
    vccbram = 1.000 - 0.008 * degradation + np.random.normal(0, 0.001)

    # Ring oscillator frequency (MHz): drops below the placeholder nominal as the part ages
    ro_frequency = nominal * (1.0 - rules.scenario_ro_drop_pct(degradation) / 100.0) + np.random.normal(0, 0.1)

    # Physical derived RO stage delay (ns): tau = 1000 / (2 * N * f_MHz)
    ro_delay_ns = calculate_ro_delay_ns(ro_frequency, stages=RO_STAGES)

    # Functional error rate
    error_rate = max(0.0, rules.scenario_error_rate(degradation) + np.random.normal(0, 0.00002))

    # Health label from the shared rules
    health = rules.worst_state([
        rules.classify_region(ro_frequency, nominal),
        rules.classify_temperature(temperature),
        rules.classify_voltage("VCCINT", vccint),
        rules.classify_voltage("VCCAUX", vccaux),
        rules.classify_voltage("VCCBRAM", vccbram),
        rules.classify_error_rate(error_rate),
    ])

    return {
        "Timestamp": timestamp,
        "Temperature": round(temperature, 4),
        "VCCINT": round(vccint, 4),
        "VCCAUX": round(vccaux, 4),
        "VCCBRAM": round(vccbram, 4),
        "RO_Frequency": round(ro_frequency, 4),
        "RO_Delay_ns": round(ro_delay_ns, 4),
        "Error_Rate": round(error_rate, 6),
        "Health": health
    }


# ============================================================
# Generate dataset
# ============================================================

def generate_dataset():
    data = []

    for i in range(NUM_SAMPLES):
        timestamp = i
        degradation = i / NUM_SAMPLES
        measurement = generate_measurement(timestamp, degradation)
        data.append(measurement)

    df = pd.DataFrame(data)

    # Perform physical sanity validation on generated dataset
    sample_freq = df["RO_Frequency"].iloc[0]
    sample_delay = df["RO_Delay_ns"].iloc[0]
    is_valid, msg = validate_ro_delay(sample_freq, RO_STAGES, sample_delay)
    if not is_valid:
        raise ValueError(f"CRITICAL SANITY CHECK FAILED: {msg}")

    # Create directory if necessary
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    df.to_csv(OUTPUT_FILE, index=False)

    print("==================================================")
    print("MOCK FPGA DATASET GENERATION & UNIT AUDIT")
    print("==================================================")
    print(f"Dataset generated successfully with {len(df)} samples.")
    print(f"Saved to: {OUTPUT_FILE}")
    print(f"RO Inverter Stages (N): {RO_STAGES}")
    print(f"Sample Initial Frequency: {sample_freq:.2f} MHz -> Delay: {sample_delay:.4f} ns/stage")
    print(f"Sample Degraded Frequency: {df['RO_Frequency'].iloc[-1]:.2f} MHz -> Delay: {df['RO_Delay_ns'].iloc[-1]:.4f} ns/stage")
    print(f"Validation Status: {msg}")
    print("\nHealth distribution (labels computed from health_rules.py):")
    print(df["Health"].value_counts())
    print("==================================================")


if __name__ == "__main__":
    generate_dataset()
