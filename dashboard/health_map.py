"""
FPGA Physical Four-Region Health Architecture & Regional Map Generator
======================================================================
Replaces the conceptual 5x5 virtual matrix with a physical 2x2 regional
representation reflecting the four physically constrained hardware quadrants:
  - R1: Northwest (NW) — Clock Region X0Y2, Pblock pblock_R1
  - R2: Northeast (NE) — Clock Region X1Y2, Pblock pblock_R2
  - R3: Southwest (SW) — Clock Region X0Y0, Pblock pblock_R3
  - R4: Southeast (SE) — Clock Region X1Y0, Pblock pblock_R4

Physically Honest Fault Model:
  Ring Oscillator telemetry measures live gate propagation delay, thermal drift,
  and transistor aging. It does NOT claim to detect arbitrary single-LUT stuck-at
  faults. Configuration memory errors are managed via CRC/SEM, while functional
  data-path errors are tracked via the independent PRBS-7 error rate monitor.
"""

import textwrap
from typing import List, Dict, Any, Optional
from config import calculate_ro_delay_ns, RO_STAGES
import health_rules
from dashboard.config import (
    HEALTH_COLORS,
    STATUS_BG_COLORS,
    REGIONAL_CONFIG,
    DEFAULT_REGIONAL_WEIGHTS,
    REGION_QUORUM,
    RO_FREQ_NOMINAL_MHZ,
    RO_FREQ_WARNING_LOW_MHZ,
    RO_FREQ_CRITICAL_LOW_MHZ,
    evaluate_regional_health,
    validate_regional_baseline,
    validate_regional_weights,
    calculate_weighted_regional_frequency
)

# Default nominal benchmarks per region from physical Basys 3 telemetry
REGIONAL_DEFAULTS = {
    "R1": {
        "id": "R1",
        "name": "Region 1 (R1)",
        "quadrant": "Region 1 (R1)",
        "clock_region": "CLOCKREGION_X0Y2",
        "pblock": "pblock_R1",
        "slice_range": "SLICE_X0Y100:SLICE_X35Y149",
        "nominal_freq": 436.0,
        "nominal_delay_ns": 0.2294
    },
    "R2": {
        "id": "R2",
        "name": "Region 2 (R2)",
        "quadrant": "Region 2 (R2)",
        "clock_region": "CLOCKREGION_X1Y2",
        "pblock": "pblock_R2",
        "slice_range": "SLICE_X36Y100:SLICE_X57Y149",
        "nominal_freq": 436.0,
        "nominal_delay_ns": 0.2294
    },
    "R3": {
        "id": "R3",
        "name": "Region 3 (R3)",
        "quadrant": "Region 3 (R3)",
        "clock_region": "CLOCKREGION_X0Y0",
        "pblock": "pblock_R3",
        "slice_range": "SLICE_X0Y0:SLICE_X35Y49",
        "nominal_freq": 436.0,
        "nominal_delay_ns": 0.2294
    },
    "R4": {
        "id": "R4",
        "name": "Region 4 (R4)",
        "quadrant": "Region 4 (R4)",
        "clock_region": "CLOCKREGION_X1Y0",
        "pblock": "pblock_R4",
        "slice_range": "SLICE_X36Y0:SLICE_X65Y49",
        "nominal_freq": 436.0,
        "nominal_delay_ns": 0.2294
    }
}

# The literals above are placeholders only: the real nominals come from the single
# source of truth (health_rules.py via REGIONAL_CONFIG).
for _rid, _meta in REGIONAL_DEFAULTS.items():
    _meta["nominal_freq"] = REGIONAL_CONFIG[_rid]["nominal_freq"]
    _meta["nominal_delay_ns"] = REGIONAL_CONFIG[_rid]["nominal_delay_ns"]


def calculate_aggregate_risk_score(
    health_pred: str,
    confidence: float,
    temp: float,
    ro_freq_shift_pct: float,
    error_rate: float
) -> float:
    """
    Computes a continuous aggregate risk score in range [0.0, 1.0].
    0.0 = completely pristine / healthy baseline
    1.0 = maximum degradation / critical risk
    """
    base_scores = {"Healthy": 0.15, "Warning": 0.50, "Degraded": 0.85, "Critical": 0.95}
    score = base_scores.get(health_pred, 0.15)

    temp_factor = min(1.0, max(0.0, (temp - 35.0) / (health_rules.TEMP_CRIT_C - 35.0)))
    ro_factor = min(1.0, max(0.0, abs(min(0.0, ro_freq_shift_pct)) / (1.2 * health_rules.RO_CRIT_DROP_PCT)))
    err_factor = min(1.0, max(0.0, error_rate / (1.5 * health_rules.ERROR_RATE_CRIT)))

    composite_risk = (
        0.45 * score +
        0.20 * temp_factor +
        0.20 * ro_factor +
        0.15 * err_factor
    )
    return round(min(1.0, max(0.0, composite_risk)), 3)


def generate_four_region_data(
    telemetry: Dict[str, Any],
    regional_baselines: Optional[Dict[str, float]] = None
) -> List[Dict[str, Any]]:
    """
    Generates structured physical telemetry and health assessment for the four
    constrained FPGA regions (R1 Northwest, R2 Northeast, R3 Southwest, R4 Southeast).
    Uses the unified evaluate_regional_health() engine to ensure consistent safety limits.
    """
    baselines = regional_baselines or {}
    global_ro_freq = telemetry.get("RO_Frequency", RO_FREQ_NOMINAL_MHZ)

    regions = []
    region_keys = ["R1", "R2", "R3", "R4"]

    for r_key in region_keys:
        ro_k = f"RO_{r_key}"
        if ro_k in telemetry:
            meas_val = telemetry[ro_k]
            prov = "MEASURED"
        elif "RO_Frequency" in telemetry:
            meas_val = global_ro_freq
            prov = "DERIVED_GLOBAL"
        else:
            meas_val = None
            prov = "MISSING"

        base_val = baselines.get(ro_k)
        reg_eval = evaluate_regional_health(
            region_id=r_key,
            measurement=meas_val,
            baseline_freq=base_val,
            provenance=prov
        )
        regions.append(reg_eval)

    return regions


def render_four_region_map_html(
    regions: List[Dict[str, Any]],
    composite_risk: float = 0.0,
    weighted_summary: Optional[Dict[str, Any]] = None,
    regional_weights: Optional[Dict[str, float]] = None
) -> str:
    """
    Renders an interactive high-tech 2x2 physical FPGA quadrant layout:
       ┌──────────────┬──────────────┐
       │ R1 Northwest │ R2 Northeast │
       ├──────────────┼──────────────┤
       │ R3 Southwest │ R4 Southeast │
       └──────────────┴──────────────┘
    Includes an aggregate summary banner showing:
      1. Weighted RO Average (configurable weighted estimate)
      2. Hardware Arithmetic Mean (UART RO_Frequency baseline)
      3. Worst-Case Regional Frequency (independent safety bound)
    """
    summary = weighted_summary or calculate_weighted_regional_frequency(regions, weights=regional_weights)
    w_freq = summary.get("weighted_frequency")
    a_freq = summary.get("arithmetic_frequency")
    worst_freq = summary.get("worst_region_frequency")
    worst_id = summary.get("worst_region_id")
    weights_used = summary.get("weights_used", DEFAULT_REGIONAL_WEIGHTS)

    w_freq_str = f"{w_freq:.2f}" if w_freq is not None else "N/A"
    a_freq_str = f"{a_freq:.2f}" if a_freq is not None else "N/A"
    worst_freq_str = f"{worst_freq:.2f}" if worst_freq is not None else "N/A"

    weights_display_parts = [f"{r}:{w:.2f}" for r, w in sorted(weights_used.items())]
    weights_str = " | ".join(weights_display_parts)

    # Each region is judged against its own boundaries (single source of truth)
    def _crit(r):
        return r.get("critical_freq", RO_FREQ_CRITICAL_LOW_MHZ)

    def _warn(r):
        return r.get("warning_freq", RO_FREQ_WARNING_LOW_MHZ)

    crit_count = sum(1 for r in regions if r.get("current_freq", 999.0) <= _crit(r))
    warn_count = sum(1 for r in regions if _crit(r) < r.get("current_freq", 999.0) <= _warn(r))
    degrading_total = crit_count + warn_count

    worst_r = next((r for r in regions if r.get("id") == worst_id), {})
    crit_b, warn_b = _crit(worst_r), _warn(worst_r)

    # Determine worst region color and safety note with Quorum policy
    if worst_freq is not None and worst_freq <= crit_b:
        worst_color = HEALTH_COLORS["Degraded"]
        if degrading_total >= REGION_QUORUM:
            worst_note = f"Multi-pblock degradation (&ge; {REGION_QUORUM} pblocks; overall Degraded)"
        else:
            worst_note = f"Isolated pblock critical in {worst_id} (&le; {crit_b:.1f} MHz; Quorum: &ge; {REGION_QUORUM} for overall)"
    elif worst_freq is not None and worst_freq <= warn_b:
        worst_color = HEALTH_COLORS["Warning"]
        if degrading_total >= REGION_QUORUM:
            worst_note = f"Multi-pblock warning drift (&ge; {REGION_QUORUM} pblocks; overall Warning)"
        else:
            worst_note = f"Isolated pblock warning in {worst_id} (&le; {warn_b:.1f} MHz; Quorum: &ge; {REGION_QUORUM} for overall)"
    elif worst_freq is not None:
        worst_color = HEALTH_COLORS["Healthy"]
        worst_note = f"Healthy operating envelope ({worst_id})"
    else:
        worst_color = "#94A3B8"
        worst_note = "No valid regional telemetry"

    card_htmls = []
    for r in regions:
        drift_sign = "+" if r["drift_mhz"] >= 0 else ""
        delay_drift_sign = "+" if r["delay_drift_pct"] >= 0 else ""
        crit_str = f"{r['critical_boundary']:.1f} MHz" if r.get("critical_boundary") else (f"{r['critical_freq']:.1f} MHz" if r.get("critical_freq") else "N/A")
        prov_label = r.get("provenance", "MEASURED")

        card_htmls.append(f"""
        <div style="
            background: {r['bg']};
            border: 1px solid {r['border']};
            border-radius: 8px;
            padding: 14px 16px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
            transition: transform 0.15s ease-in-out;
        ">
            <!-- Region Header -->
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 6px;">
                <div>
                    <strong style="font-size: 1.05rem; color: #FFFFFF; font-family: 'JetBrains Mono', monospace;">{r['name']}</strong>
                    <div style="font-size: 0.75rem; color: #94A3B8; margin-top: 2px; line-height: 1.35;">
                        Clock Region: <code style="color: #38BDF8; font-size: 0.74rem;">{r['clock_region']}</code><br/>
                        Physical Constraint: <code style="color: #F1F5F9; font-size: 0.74rem;">{r['pblock']}</code>
                    </div>
                </div>
                <span style="
                    background: {r['bg']};
                    color: {r['color']};
                    border: 1px solid {r['color']};
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-size: 0.75rem;
                    font-weight: 700;
                    letter-spacing: 0.5px;
                ">
                    {r['state'].upper()}
                </span>
            </div>

            <!-- Key Metrics Grid -->
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px;">
                <div>
                    <div style="font-size: 0.72rem; color: #94A3B8; text-transform: uppercase;">Live Frequency</div>
                    <div style="font-size: 1.15rem; font-weight: 700; color: #F8FAFC; font-family: 'JetBrains Mono', monospace;">
                        {r['current_freq']:.2f} <span style="font-size: 0.75rem; color: #64748B;">MHz</span>
                    </div>
                    <div style="font-size: 0.72rem; color: #64748B;">Base: {r['baseline_freq']:.2f} MHz | Crit: {crit_str}</div>
                </div>
                <div>
                    <div style="font-size: 0.72rem; color: #94A3B8; text-transform: uppercase;">Stage Delay (&tau;)</div>
                    <div style="font-size: 1.15rem; font-weight: 700; color: #38BDF8; font-family: 'JetBrains Mono', monospace;">
                        {r['delay_ns']:.4f} <span style="font-size: 0.75rem; color: #64748B;">ns</span>
                    </div>
                    <div style="font-size: 0.72rem; color: #64748B;">Shift: {delay_drift_sign}{r['delay_drift_pct']:.2f}%</div>
                </div>
            </div>

            <!-- Timing Drift & Physical Mapping -->
            <div style="font-size: 0.78rem; line-height: 1.4; color: #CBD5E1; margin-bottom: 6px;">
                <strong>Timing Drift:</strong> <span style="font-family: 'JetBrains Mono', monospace; color: {r['color']}; font-weight: 600;">{drift_sign}{r['drift_mhz']:.2f} MHz ({drift_sign}{r['drift_pct']:.2f}%)</span>
                <br/><strong>Critical Boundary:</strong> <code style="color: #F87171; font-size: 0.72rem;">{crit_str}</code> | <strong>Provenance:</strong> <span style="color: #94A3B8; font-size: 0.72rem;">{prov_label}</span>
                <br/><strong>Silicon Coordinates:</strong> <code style="color: #64748B; font-size: 0.70rem;">{r['slice_range']}</code>
            </div>

            <!-- Indicator Badge -->
            <div style="font-size: 0.72rem; color: #94A3B8; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 6px;">
                Status: <span style="color: {r['color']}; font-weight: 600;">{r['indicator']}</span>
            </div>
        </div>
        """)

    grid_content = "\n".join(card_htmls)

    return textwrap.dedent(f"""
    <div style="background: rgba(15, 23, 42, 0.85); border: 1px solid #334155; border-radius: 10px; padding: 18px; margin: 12px 0;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
            <div>
                <strong style="font-size: 1.05rem; color: #F8FAFC;">Physical Four-Region FPGA Health Architecture</strong>
                <div style="font-size: 0.78rem; color: #94A3B8;">2&times;2 Spatially Constrained Ring-Oscillator Array (XC7A35T Artix-7)</div>
            </div>
            <div style="font-family: 'JetBrains Mono', monospace; font-size: 0.82rem; color: #00E5FF; background: rgba(0, 229, 255, 0.1); border: 1px solid rgba(0, 229, 255, 0.25); border-radius: 4px; padding: 4px 10px;">
                Overall Risk Index: {composite_risk * 100:.1f} %
            </div>
        </div>

        <!-- Aggregate Regional Summary Metrics Bar -->
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 14px; background: rgba(30, 41, 59, 0.7); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px; padding: 12px 14px;">
            <div>
                <div style="font-size: 0.72rem; color: #94A3B8; text-transform: uppercase; letter-spacing: 0.5px;">Weighted RO Average (Summary)</div>
                <div style="font-size: 1.20rem; font-weight: 700; color: #38BDF8; font-family: 'JetBrains Mono', monospace;">
                    {w_freq_str} <span style="font-size: 0.75rem; color: #64748B;">MHz</span>
                </div>
                <div style="font-size: 0.70rem; color: #94A3B8; margin-top: 2px;">
                    Weights: <code style="color: #CBD5E1; font-size: 0.68rem;">{weights_str}</code>
                </div>
            </div>
            <div>
                <div style="font-size: 0.72rem; color: #94A3B8; text-transform: uppercase; letter-spacing: 0.5px;">Hardware Arithmetic Mean</div>
                <div style="font-size: 1.20rem; font-weight: 700; color: #F8FAFC; font-family: 'JetBrains Mono', monospace;">
                    {a_freq_str} <span style="font-size: 0.75rem; color: #64748B;">MHz</span>
                </div>
                <div style="font-size: 0.70rem; color: #94A3B8; margin-top: 2px;">
                    UART Telemetry: <code style="color: #38BDF8; font-size: 0.68rem;">RO_Frequency (Sum &gt;&gt; 2)</code>
                </div>
            </div>
            <div>
                <div style="font-size: 0.72rem; color: #94A3B8; text-transform: uppercase; letter-spacing: 0.5px;">Worst-Case Regional Frequency</div>
                <div style="font-size: 1.20rem; font-weight: 700; color: {worst_color}; font-family: 'JetBrains Mono', monospace;">
                    {worst_freq_str} <span style="font-size: 0.75rem; color: #64748B;">MHz</span>
                </div>
                <div style="font-size: 0.70rem; color: {worst_color}; margin-top: 2px; font-weight: 500;">
                    {worst_note}
                </div>
            </div>
        </div>

        <!-- 2x2 Physical Layout Grid -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
            {grid_content}
        </div>

        <!-- Physical Health Methodology Callout -->
        <div style="margin-top: 14px; padding: 10px 12px; background: rgba(30, 41, 59, 0.6); border-left: 3px solid #38BDF8; border-radius: 4px; font-size: 0.75rem; color: #94A3B8; line-height: 1.45;">
            <strong>Physically Honest Fault Model:</strong> Each regional monitor tracks gate delay (tau = 100 / f_MHz) within its constrained Pblock.
            RO frequency shift reflects regional NBTI/HCI aging, supply droop, or thermal variation. Floorplan coordinates represent configured Pblock placement constraints in the Vivado floorplan, not dynamically localized physical defect coordinates.
            <br/><strong>Multi-Pblock Quorum Policy:</strong> The weighted RO average serves as the overall health metric on top. An isolated single-pblock anomaly (e.g. R2) does not degrade the entire chip; 2 or more degrading pblocks are required to trigger overall system degradation.
        </div>
    </div>
    """).strip()


# Backward Compatibility Aliases for legacy imports
def generate_risk_cells(risk_score: float) -> List[Dict[str, Any]]:
    """Legacy alias: maps to four-region data format."""
    dummy_telemetry = {"RO_Frequency": 436.0}
    return generate_four_region_data(dummy_telemetry)


def render_health_risk_map_html(cells_or_regions: List[Dict[str, Any]], composite_risk: float = 0.0) -> str:
    """Legacy alias: renders four-region map html."""
    if cells_or_regions and "quadrant" in cells_or_regions[0]:
        return render_four_region_map_html(cells_or_regions, composite_risk)
    else:
        # Fallback to generating 4-region representation
        regions = generate_four_region_data({"RO_Frequency": 436.0})
        return render_four_region_map_html(regions, composite_risk)
