"""
Reusable UI Components for the FPGA Health Monitoring Dashboard
==============================================================
Implements modular technical components adhering strictly to the
embedded-systems laboratory aesthetic and research guidelines.
Uses st.html() to cleanly render raw HTML/SVG without CommonMark code-block parsing.
"""

import textwrap
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import streamlit as st

from dashboard.config import (
    SENSOR_CONFIG,
    HEALTH_COLORS,
    STATUS_BG_COLORS,
    DEVICE_NAME,
    RO_STAGES,
    RO_FREQ_NOMINAL_MHZ,
    evaluate_single_channel,
    LimitSeverity,
    get_error_risk_label
)
from dashboard.styles import get_fpga_chip_svg, render_primary_health_card, render_measurement_card


def render_header(status_label: str = "ACTIVE", source_label: str = "MOCK DATA", platform: str = DEVICE_NAME):
    """Renders the top centered FPGA research banner with inline SVG chip."""
    chip_svg = get_fpga_chip_svg(size=90)
    if "ESTIMATED" in source_label.upper():
        badge_source_class = "badge-estimated"
    elif "MOCK" in source_label.upper():
        badge_source_class = "badge-mock"
    else:
        badge_source_class = "badge-live"

    html = textwrap.dedent(f"""
<div class="header-box">
    <div class="header-title">AI-Assisted FPGA Health Monitoring</div>
    <div>{chip_svg}</div>
    <div class="header-subtitle">
        AI-Based Predictive Health Monitoring and Intelligent Recommendation System
    </div>
    <div class="status-badge-container">
        <div class="badge-pill badge-active">
            <span class="pulse-dot"></span>
            Monitoring Status: {status_label}
        </div>
        <div class="badge-pill {badge_source_class}">
            DATA SOURCE: {source_label}
        </div>
        <div class="badge-pill badge-chip">
            Target: {platform}
        </div>
    </div>
</div>
""").strip()
    st.html(html)


def render_primary_health_kpis(
    health_pred: str,
    confidence: float,
    temperature: float,
    error_rate: float
):
    """
    Section 2: Four primary KPI cards:
    1. FPGA Health (Color-coded: Healthy, Warning, Degraded, Critical)
    2. ML Confidence (%)
    3. Die Temperature (°C)
    4. Error Risk (Low / Medium / High / Critical)
    """
    health_color = HEALTH_COLORS.get(health_pred, "#00E676")
    bg_color = STATUS_BG_COLORS.get(health_pred, "rgba(0, 230, 118, 0.12)")

    # Derive error risk label INDEPENDENTLY from Error_Rate
    risk_label, risk_color, risk_desc = get_error_risk_label(error_rate)

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.html(
            render_primary_health_card(
                title="FPGA Health",
                value=health_pred,
                subtext="ML Classified State",
                state_color=health_color,
                bg_color=bg_color
            )
        )

    with c2:
        st.html(
            render_primary_health_card(
                title="ML Confidence",
                value=f"{confidence * 100:.1f} %",
                subtext="Random Forest Probability",
                state_color="#00E5FF",
                bg_color="rgba(0, 229, 255, 0.12)"
            )
        )

    with c3:
        temp_color = "#FF5252" if temperature > 50.0 else ("#FFD600" if temperature > 42.0 else "#00E676")
        st.html(
            render_primary_health_card(
                title="Die Temperature",
                value=f"{temperature:.2f} °C",
                subtext="XADC On-Chip Sensor",
                state_color=temp_color,
                bg_color="rgba(255, 82, 82, 0.12)"
            )
        )

    with c4:
        st.html(
            render_primary_health_card(
                title="Error Risk",
                value=risk_label,
                subtext=f"Rate: {error_rate:.5f}",
                state_color=risk_color,
                bg_color="rgba(255, 23, 68, 0.12)" if risk_label == "High" else ("rgba(255, 214, 0, 0.12)" if risk_label == "Medium" else "rgba(0, 230, 118, 0.12)")
            )
        )


def render_measurements_grid(latest: pd.Series, baseline: Dict[str, float], sample_num: int = 0):
    """
    Section 3: Grid of 8 FPGA physical sensor telemetry cards with units & deltas.
    """
    c1, c2, c3, c4 = st.columns(4)
    c5, c6, c7, c8 = st.columns(4)

    temp_base = baseline.get("Temperature", 35.0)
    temp_delta = latest["Temperature"] - temp_base

    vccint_base = baseline.get("VCCINT", 1.000)
    vccint_delta = latest["VCCINT"] - vccint_base

    vccaux_base = baseline.get("VCCAUX", 1.800)
    vccaux_delta = latest["VCCAUX"] - vccaux_base

    vccbram_base = baseline.get("VCCBRAM", 1.000)
    vccbram_delta = latest["VCCBRAM"] - vccbram_base

    ro_freq_base = baseline.get("RO_Frequency", RO_FREQ_NOMINAL_MHZ)
    ro_freq_delta = latest["RO_Frequency"] - ro_freq_base

    ro_delay_base = baseline.get("RO_Delay_ns", 0.2294)
    ro_delay_delta = latest["RO_Delay_ns"] - ro_delay_base

    with c1:
        st.html(
            render_measurement_card(
                label="Die Temperature",
                value_str=f"{latest['Temperature']:.2f}",
                unit="°C",
                delta_str=f"Δ {temp_delta:+.2f} °C",
                delta_color="#FF5252" if temp_delta > 5 else "#00E676"
            )
        )

    with c2:
        st.html(
            render_measurement_card(
                label="VCCINT (Core)",
                value_str=f"{latest['VCCINT']:.3f}",
                unit="V",
                delta_str=f"Δ {vccint_delta:+.3f} V",
                delta_color="#94A3B8"
            )
        )

    with c3:
        st.html(
            render_measurement_card(
                label="VCCAUX (Aux)",
                value_str=f"{latest['VCCAUX']:.3f}",
                unit="V",
                delta_str=f"Δ {vccaux_delta:+.3f} V",
                delta_color="#94A3B8"
            )
        )

    with c4:
        st.html(
            render_measurement_card(
                label="VCCBRAM (Block RAM)",
                value_str=f"{latest['VCCBRAM']:.3f}",
                unit="V",
                delta_str=f"Δ {vccbram_delta:+.3f} V",
                delta_color="#94A3B8"
            )
        )

    with c5:
        st.html(
            render_measurement_card(
                label="RO Frequency",
                value_str=f"{latest['RO_Frequency']:.2f}",
                unit="MHz",
                delta_str=f"Δ {ro_freq_delta:+.2f} MHz",
                delta_color="#FF9100" if ro_freq_delta < -3.0 else "#00E676"
            )
        )

    with c6:
        st.html(
            render_measurement_card(
                label="Derived RO Stage Delay",
                value_str=f"{latest['RO_Delay_ns']:.4f}",
                unit="ns/stage",
                delta_str=f"Δ {ro_delay_delta:+.4f} ns",
                delta_color="#D946EF"
            )
        )

    with c7:
        st.html(
            render_measurement_card(
                label="Functional Error Rate",
                value_str=f"{latest['Error_Rate']:.5f}",
                unit="",
                delta_str=f"{'ELEVATED' if latest['Error_Rate'] > 0.001 else 'NOMINAL'}",
                delta_color="#FF9100" if latest['Error_Rate'] > 0.001 else "#00E676"
            )
        )

    with c8:
        st.html(
            render_measurement_card(
                label="Telemetry Cycle / Sample",
                value_str=f"#{sample_num}",
                unit="",
                delta_str="Synchronized",
                delta_color="#00E5FF"
            )
        )


def render_ring_oscillator_section(latest: pd.Series, baseline: Dict[str, float]):
    """
    Section 4: Dedicated Ring Oscillator Aging Indicator.
    Calculates Frequency Shift (%) and Delay Shift (%), and presents the mathematical model.
    """
    curr_freq = latest["RO_Frequency"]
    base_freq = baseline.get("RO_Frequency", RO_FREQ_NOMINAL_MHZ)
    freq_shift_pct = ((curr_freq - base_freq) / base_freq) * 100.0

    curr_delay = latest["RO_Delay_ns"]
    base_delay = baseline.get("RO_Delay_ns", 0.2294)
    delay_shift_pct = ((curr_delay - base_delay) / base_delay) * 100.0

    c1, c2, c3 = st.columns(3)

    with c1:
        st.html(
            render_primary_health_card(
                title="RO Frequency Shift",
                value=f"{freq_shift_pct:+.2f} %",
                subtext=f"Current: {curr_freq:.2f} MHz | Baseline: {base_freq:.2f} MHz",
                state_color="#FF9100" if freq_shift_pct < -3.0 else "#00E676",
                bg_color="rgba(255, 145, 0, 0.12)"
            )
        )

    with c2:
        st.html(
            render_primary_health_card(
                title="RO Delay Shift (Derived)",
                value=f"{delay_shift_pct:+.2f} %",
                subtext=f"Current: {curr_delay:.4f} ns | Baseline: {base_delay:.4f} ns",
                state_color="#D946EF" if delay_shift_pct > 3.0 else "#00E676",
                bg_color="rgba(217, 70, 239, 0.12)"
            )
        )

    with c3:
        status_text = "Severe Aging Drift" if freq_shift_pct < -5.0 else ("Moderate Degradation" if freq_shift_pct < -2.5 else "Nominal Frequency")
        status_color = HEALTH_COLORS["Degraded"] if freq_shift_pct < -5.0 else (HEALTH_COLORS["Warning"] if freq_shift_pct < -2.5 else HEALTH_COLORS["Healthy"])
        st.html(
            render_primary_health_card(
                title="Timing Degradation Status",
                value=status_text,
                subtext=f"Aging Signature: {'Positive (Gate Slowing)' if freq_shift_pct < -2.0 else 'None'}",
                state_color=status_color,
                bg_color="rgba(0, 229, 255, 0.12)"
            )
        )


def render_baseline_comparison(latest: pd.Series, baseline: Dict[str, float]):
    """
    Section 18: Baseline Comparison Table.
    """
    rows = []

    # Temperature
    t_curr = latest["Temperature"]
    t_base = baseline.get("Temperature", 35.0)
    t_delta = t_curr - t_base
    rows.append({
        "Sensor Channel": "Die Temperature",
        "Current Measurement": f"{t_curr:.2f} °C",
        "Baseline Benchmark": f"{t_base:.2f} °C",
        "Absolute / Relative Shift": f"{t_delta:+.2f} °C ({(t_delta/t_base)*100:+.1f}%)",
        "Assessment": "Elevated Thermal Dissipation" if t_delta > 10 else "Nominal Operating Temp"
    })

    # RO Frequency
    f_curr = latest["RO_Frequency"]
    f_base = baseline.get("RO_Frequency", RO_FREQ_NOMINAL_MHZ)
    f_shift = ((f_curr - f_base) / f_base) * 100.0
    rows.append({
        "Sensor Channel": "Ring Oscillator Frequency",
        "Current Measurement": f"{f_curr:.2f} MHz",
        "Baseline Benchmark": f"{f_base:.2f} MHz",
        "Absolute / Relative Shift": f"{f_curr - f_base:+.2f} MHz ({f_shift:+.2f}%)",
        "Assessment": "Degraded Logic Speed" if f_shift < -3.5 else "Nominal Oscillation"
    })

    # RO Delay
    d_curr = latest["RO_Delay_ns"]
    d_base = baseline.get("RO_Delay_ns", 0.2294)
    d_shift = ((d_curr - d_base) / d_base) * 100.0
    rows.append({
        "Sensor Channel": "Derived RO Stage Delay",
        "Current Measurement": f"{d_curr:.4f} ns",
        "Baseline Benchmark": f"{d_base:.4f} ns",
        "Absolute / Relative Shift": f"{d_curr - d_base:+.4f} ns ({d_shift:+.2f}%)",
        "Assessment": "Timing Margin Degradation" if d_shift > 3.5 else "Nominal Timing"
    })

    # VCCINT
    v_curr = latest["VCCINT"]
    v_base = baseline.get("VCCINT", 1.000)
    v_delta = v_curr - v_base
    rows.append({
        "Sensor Channel": "VCCINT (Internal Core Voltage)",
        "Current Measurement": f"{v_curr:.4f} V",
        "Baseline Benchmark": f"{v_base:.4f} V",
        "Absolute / Relative Shift": f"{v_delta:+.4f} V ({(v_delta/v_base)*100:+.2f}%)",
        "Assessment": "Stable Within Tolerance" if abs(v_delta) < 0.02 else "Voltage Droop"
    })

    # Error Rate
    e_curr = latest["Error_Rate"]
    e_base = baseline.get("Error_Rate", 0.00001)
    rows.append({
        "Sensor Channel": "Functional Error Rate",
        "Current Measurement": f"{e_curr:.6f}",
        "Baseline Benchmark": f"{e_base:.6f}",
        "Absolute / Relative Shift": f"{e_curr - e_base:+.6f}",
        "Assessment": "Elevated Error Stress" if e_curr > 0.001 else "Negligible Soft Errors"
    })

    df_comp = pd.DataFrame(rows)
    st.dataframe(df_comp, width="stretch", hide_index=True)


def render_engineering_override_alert(
    final_health_dict: Dict[str, Any]
):
    """
    Renders a prominent high-visibility laboratory callout when a hard physical or
    engineering operating limit overrides the Random Forest ML prediction.
    Displays clear, physically consistent root cause without double-counting derived metrics.
    """
    override_applied = final_health_dict.get("override_applied", False)
    if not override_applied:
        return

    ml_pred = final_health_dict.get("ml_prediction", "Healthy")
    ml_conf = final_health_dict.get("ml_confidence", 0.95)
    final_health = final_health_dict.get("final_health", "Degraded")
    title = final_health_dict.get("override_title", "HARD ENGINEERING LIMIT OVERRIDE")
    explanation = final_health_dict.get("override_explanation", "")

    primary_reason = final_health_dict.get("primary_reason", "Deterministic engineering limit violated")
    measured_str = final_health_dict.get("measured_str", "N/A")
    limit_str = final_health_dict.get("limit_str", "N/A")
    derived_delay_str = final_health_dict.get("derived_delay_str")
    final_decision_str = final_health_dict.get(
        "final_decision",
        f"{final_health.upper()} because the deterministic engineering limit takes precedence over the ML prediction."
    )

    state_color = HEALTH_COLORS.get(final_health, "#FF1744")

    delay_row_html = ""
    if derived_delay_str:
        delay_row_html = f"""
        <span style="color: #94A3B8; font-weight: 600;">DERIVED DELAY:</span>
        <span style="font-family: 'JetBrains Mono', monospace; color: #CBD5E1;">{derived_delay_str}</span>
        """

    html = textwrap.dedent(f"""
    <div style="background: linear-gradient(135deg, rgba(255, 23, 68, 0.15), rgba(17, 24, 39, 0.95)); border: 2px solid {state_color}; border-radius: 10px; padding: 18px 22px; margin: 16px 0 20px 0; box-shadow: 0 4px 20px rgba(255, 23, 68, 0.2);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
            <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 1.4rem;">⚠️</span>
                <span style="font-family: 'JetBrains Mono', monospace; font-size: 0.95rem; font-weight: 800; color: {state_color}; text-transform: uppercase; letter-spacing: 0.5px;">
                    {title}
                </span>
            </div>
            <div style="font-family: 'JetBrains Mono', monospace; font-size: 0.78rem; background: rgba(255,255,255,0.08); padding: 4px 10px; border-radius: 4px; color: #CBD5E1;">
                PRECEDENCE: HARD PHYSICAL / OPERATING BOUNDS > ML PREDICTION
            </div>
        </div>
        
        <!-- ML Output vs Engineering Assessment Row -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 10px 0 14px 0; background: rgba(0,0,0,0.25); padding: 12px 14px; border-radius: 6px;">
            <div>
                <div style="font-size: 0.75rem; color: #94A3B8; text-transform: uppercase; font-family: 'JetBrains Mono', monospace;">ML PREDICTION</div>
                <div style="font-size: 1.15rem; font-weight: 700; color: #F8FAFC; margin-top: 2px;">
                    {ml_pred.upper()} <span style="font-size: 0.85rem; color: #00E5FF; font-weight: 600;">({ml_conf * 100:.1f}%)</span>
                </div>
            </div>
            <div>
                <div style="font-size: 0.75rem; color: #94A3B8; text-transform: uppercase; font-family: 'JetBrains Mono', monospace;">ENGINEERING ASSESSMENT</div>
                <div style="font-size: 1.15rem; font-weight: 800; color: {state_color}; margin-top: 2px;">
                    {final_health.upper()} <span style="font-size: 0.85rem; color: #FCA5A5; font-weight: 600;">(Safety Override Applied)</span>
                </div>
            </div>
        </div>

        <!-- Structured Root Cause Panel -->
        <div style="background: rgba(0, 0, 0, 0.4); border-left: 3px solid {state_color}; border-radius: 4px; padding: 12px 14px; margin: 10px 0;">
            <div style="font-family: 'JetBrains Mono', monospace; font-size: 0.78rem; color: #94A3B8; text-transform: uppercase; margin-bottom: 8px; font-weight: 700;">
                Deterministic Safety Analysis
            </div>
            <div style="display: grid; grid-template-columns: 150px 1fr; gap: 6px 14px; font-size: 0.88rem; color: #E2E8F0;">
                <span style="color: #94A3B8; font-weight: 600;">PRIMARY REASON:</span>
                <span style="font-weight: 700; color: #FFFFFF;">{primary_reason}</span>

                <span style="color: #94A3B8; font-weight: 600;">MEASURED:</span>
                <span style="font-weight: 700; font-family: 'JetBrains Mono', monospace; color: #FF5252;">{measured_str}</span>

                <span style="color: #94A3B8; font-weight: 600;">LIMIT:</span>
                <span style="font-family: 'JetBrains Mono', monospace; color: #CBD5E1;">{limit_str}</span>

                {delay_row_html}

                <span style="color: #94A3B8; font-weight: 600;">FINAL DECISION:</span>
                <span style="color: #F8FAFC; font-weight: 600;">{final_decision_str}</span>
            </div>
        </div>

        <div style="font-size: 0.78rem; color: #94A3B8; margin-top: 8px; font-style: italic;">
            *Notice: The machine-learning model predicts probability distributions based on training features. When physical or engineering operating limits are violated, deterministic engineering constraints take absolute precedence.*
        </div>
    </div>
    """).strip()
    st.html(html)


def render_sensor_status_table(
    latest: pd.Series,
    history_df: pd.DataFrame,
    provenance_map: Optional[Dict[str, str]] = None
):
    """
    Section 7: Current Sensor Status Table with Centralized Operating Ranges,
    Physical Limits, Evaluation Status, and Provenance.
    """
    provenance_map = provenance_map or {}
    rows = []

    def get_trend_str(series: pd.Series) -> str:
        if len(series) < 3:
            return "→ Stable"
        diff = series.iloc[-1] - series.iloc[-3]
        pct = (diff / (abs(series.iloc[-3]) + 1e-9)) * 100.0
        if pct > 0.5:
            return "↑ Increasing"
        elif pct < -0.5:
            return "↓ Decreasing"
        return "→ Stable"

    for param, cfg in SENSOR_CONFIG.items():
        if param not in latest:
            continue
        val = latest[param]
        trend = get_trend_str(history_df[param]) if param in history_df.columns else "→ Stable"
        prov = provenance_map.get(param, "MEASURED")

        # Three-tier evaluation
        eval_res = evaluate_single_channel(param, val, provenance=prov)

        rows.append({
            "Sensor Channel": cfg["display_name"],
            "Current Reading": f"{val:.4f} {cfg['unit']}".strip(),
            "Nominal Benchmark": f"{cfg['nominal']:.4f} {cfg['unit']}".strip(),
            "Operating Health Range": eval_res.operating_range_str,
            "Status Evaluation": eval_res.status_label,
            "Provenance": prov,
            "Temporal Trend": trend
        })

    status_df = pd.DataFrame(rows)
    st.dataframe(status_df, width="stretch", hide_index=True)


def render_agent_recommendations_section(agent_res: Dict[str, Any]):
    """
    Section 10-13: LangGraph Agent AI Health Assessment & Recommendations.
    """
    risk_level = agent_res.get("risk_level", "LOW")
    summary = agent_res.get("condition_summary", "")
    indicators = agent_res.get("primary_indicators", [])
    actions = agent_res.get("recommended_actions", {})

    risk_color = (
        HEALTH_COLORS["Critical"] if "CRITICAL" in risk_level else (
            HEALTH_COLORS["Degraded"] if "HIGH" in risk_level else (
                HEALTH_COLORS["Warning"] if "MODERATE" in risk_level else HEALTH_COLORS["Healthy"]
            )
        )
    )

    indicators_html = "".join([f"<li style='margin-bottom: 6px;'>{ind}</li>" for ind in indicators])

    actions_html = ""
    for category, desc in actions.items():
        actions_html += f"""
        <div class="action-card">
            <div class="action-category">{category} Advisory</div>
            <div>{desc}</div>
        </div>
        """

    html = textwrap.dedent(f"""
<div class="agent-container">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap;">
        <div class="agent-badge">AI AGENTIC DIAGNOSTIC REASONING &bull; LANGGRAPH ENGINE</div>
        <div style="font-family: 'JetBrains Mono', monospace; font-weight: 700; color: {risk_color};">
            OPERATIONAL RISK: {risk_level}
        </div>
    </div>

    <div style="font-size: 1.05rem; font-weight: 600; color: #F8FAFC; margin-bottom: 14px;">
        {summary}
    </div>

    <div style="margin: 14px 0 16px 0;">
        <div style="font-size: 0.85rem; font-weight: 700; color: #00E5FF; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">
            Observed Physical & Telemetry Indicators:
        </div>
        <ul style="color: #CBD5E1; font-size: 0.9rem; padding-left: 20px;">
            {indicators_html}
        </ul>
    </div>

    <div style="margin-top: 18px;">
        <div style="font-size: 0.85rem; font-weight: 700; color: #38BDF8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">
            Targeted Engineering Recommendations:
        </div>
        {actions_html}
    </div>
</div>
""").strip()
    st.html(html)


def render_life_extension_section(agent_res: Dict[str, Any]):
    """
    Section 12: FPGA Life Extension Suggestions (Categorized Practical Tips).
    Uses proper non-guarantee scientific phrasing.
    """
    suggestions = agent_res.get("life_extension_suggestions", {})
    if not suggestions:
        return

    c1, c2 = st.columns(2)
    categories = list(suggestions.keys())

    half = (len(categories) + 1) // 2
    left_cats = categories[:half]
    right_cats = categories[half:]

    def build_cat_card(cat_name: str, tips: List[str]) -> str:
        tips_li = "".join([f"<li style='margin-bottom: 4px;'>{t}</li>" for t in tips])
        return textwrap.dedent(f"""
<div style="background: #111827; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 14px 16px; margin-bottom: 12px;">
    <div style="font-family: 'JetBrains Mono', monospace; font-size: 0.82rem; font-weight: 700; color: #00E5FF; text-transform: uppercase; margin-bottom: 6px;">
        ⚙️ {cat_name}
    </div>
    <ul style="color: #94A3B8; font-size: 0.84rem; padding-left: 18px; margin: 0;">
        {tips_li}
    </ul>
</div>
""").strip()

    with c1:
        for cat in left_cats:
            st.html(build_cat_card(cat, suggestions[cat]))

    with c2:
        for cat in right_cats:
            st.html(build_cat_card(cat, suggestions[cat]))

    st.caption(
        "💡 *Notice: Recommendations are based on accelerated silicon aging principles (e.g. Arrhenius thermal acceleration, BTI, and dynamic power scaling) and serve to guide operational optimization.*"
    )


def render_estimated_input_breakdown(meta: Dict[str, Any], latest: pd.Series):
    """
    Renders the transparency and provenance breakdown for Estimated Health Assessment:
    - Input Completeness (X / 6 channels supplied)
    - Assessment Reliability Score
    - Breakdown of User-Provided, Physically Derived, and Assumed Nominal Baselines.
    """
    user_provided = meta.get("user_provided", [])
    derived = meta.get("derived", [])
    assumed = meta.get("assumed", [])
    comp_str = meta.get("completeness_str", f"{len(user_provided)} / 6")
    rel_score = meta.get("reliability_score", 0.0)

    # Completeness badge color
    comp_pct = (len(user_provided) / 6.0) * 100.0
    comp_color = "#00E676" if comp_pct >= 80 else ("#FFD600" if comp_pct >= 50 else "#FF9100")

    c1, c2 = st.columns(2)
    with c1:
        st.html(
            render_primary_health_card(
                title="Input Completeness",
                value=comp_str,
                subtext=f"{comp_pct:.0f}% of Sensor Channels Provided",
                state_color=comp_color,
                bg_color="rgba(0, 229, 255, 0.10)"
            )
        )
    with c2:
        rel_color = "#00E676" if rel_score >= 0.70 else ("#FFD600" if rel_score >= 0.40 else "#FF9100")
        st.html(
            render_primary_health_card(
                title="Assessment Reliability",
                value=f"{rel_score * 100:.0f} %",
                subtext="Diagnostic Telemetry Coverage Weight",
                state_color=rel_color,
                bg_color="rgba(168, 85, 247, 0.12)"
            )
        )

    # Detailed channel breakdown list
    rows = []
    
    # 1. User provided channels
    for ch in user_provided:
        cfg = SENSOR_CONFIG.get(ch, {})
        val = latest.get(ch, 0.0)
        unit = cfg.get("unit", "")
        rows.append({
            "Sensor Channel": cfg.get("display_name", ch),
            "Value": f"{val:.4f} {unit}".strip(),
            "Provenance / Classification": "✅ User Provided (Operator Input)",
            "Methodology": "Direct Manual Input"
        })

    # 2. Derived channels
    for ch in derived:
        cfg = SENSOR_CONFIG.get(ch, {})
        val = latest.get(ch, 0.0)
        unit = cfg.get("unit", "")
        rows.append({
            "Sensor Channel": cfg.get("display_name", ch),
            "Value": f"{val:.4f} {unit}".strip(),
            "Provenance / Classification": "⚡ Physically Derived (τ = 100 / f_MHz)",
            "Methodology": "Deterministic Physical Formula (N=5 stages)"
        })

    # 3. Assumed nominal baseline channels
    for ch in assumed:
        if ch in derived:
            continue
        cfg = SENSOR_CONFIG.get(ch, {})
        val = latest.get(ch, 0.0)
        unit = cfg.get("unit", "")
        rows.append({
            "Sensor Channel": cfg.get("display_name", ch),
            "Value": f"{val:.4f} {unit}".strip(),
            "Provenance / Classification": "⚠️ Assumed Nominal Baseline",
            "Methodology": f"Imputed Nominal Benchmark (nom: {cfg.get('nominal', 0.0)} {unit})"
        })

    df_prov = pd.DataFrame(rows)
    st.dataframe(df_prov, width="stretch", hide_index=True)

    st.caption(
        "⚠️ **Estimation Notice:** Unsupplied telemetry channels are imputed using verified nominal Artix-7 physical baselines. "
        "Estimated assessments provide diagnostic guidance under partial data and do not substitute for direct hardware logging."
    )


def render_estimated_stress_index(stress_index: float, state_name: str):
    """
    Renders the continuous Estimated Health Stress Index.
    Clearly distinguishes stress score from physical silicon lifetime consumption.
    """
    if stress_index >= 0.75:
        stress_label = "High Stress / Elevated Wear"
        stress_color = HEALTH_COLORS["Degraded"]
    elif stress_index >= 0.40:
        stress_label = "Moderate Stress / Transitional"
        stress_color = HEALTH_COLORS["Warning"]
    else:
        stress_label = "Low Stress / Nominal"
        stress_color = HEALTH_COLORS["Healthy"]

    c1, c2 = st.columns([1, 1])
    with c1:
        st.html(f"""
        <div style="background: #111827; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 16px;">
            <div style="font-size: 0.8rem; color: #94A3B8; text-transform: uppercase; font-family: 'JetBrains Mono', monospace; margin-bottom: 4px;">
                Estimated Degradation / Health Stress Index
            </div>
            <div style="font-size: 2.1rem; font-weight: 800; color: {stress_color}; font-family: 'JetBrains Mono', monospace; margin-bottom: 6px;">
                {stress_index:.3f} <span style="font-size: 1.1rem; color: #94A3B8;">/ 1.000</span>
            </div>
            <div style="font-size: 0.85rem; color: {stress_color}; font-weight: 600;">
                Category: {stress_label}
            </div>
        </div>
        """)
    with c2:
        st.html(f"""
        <div style="background: #0F172A; border-left: 3px solid #00E5FF; border-radius: 0 8px 8px 0; padding: 14px 16px; font-size: 0.84rem; color: #CBD5E1; line-height: 1.45;">
            <strong>Scientific Methodology Note:</strong><br>
            The <em>Estimated Health Stress Index</em> reflects aggregate multi-domain stress computed from thermal, timing drift, and error rate parameters.
            It provides a comparative operational risk score and does <strong>not</strong> represent an absolute measured percentage of consumed silicon lifetime.
        </div>
        """)


def render_hardware_connection_panel(meta: Dict[str, Any]):
    """
    Renders the hardware UART connection status and diagnostics for the Basys 3 board.
    Displays live link state, packet metrics, and field-level telemetry provenance.
    """
    diag = meta.get("diagnostics", {})
    state = diag.get("state", "DISCONNECTED")
    port = diag.get("port", "COM3")
    baud = diag.get("baudrate", 115200)
    pkt_count = diag.get("packet_count", 0)
    err_count = diag.get("error_count", 0)
    rate_hz = diag.get("packet_rate_hz", 0.0)
    handshake = diag.get("handshake_detected", False)
    sec_since = diag.get("seconds_since_last_packet")
    last_err = diag.get("last_error_msg", "")

    if state == "RECEIVING_TELEMETRY":
        state_label = "STREAMING LIVE TELEMETRY"
        state_color = "#00E676"
        state_bg = "rgba(0, 230, 118, 0.12)"
    elif state == "CONNECTED":
        state_label = "CONNECTED (WAITING FOR FRAMES)"
        state_color = "#00E5FF"
        state_bg = "rgba(0, 229, 255, 0.12)"
    elif state == "STALE_DATA":
        state_label = f"STALE DATA ({sec_since:.1f}s SINCE LAST PACKET)"
        state_color = "#FF9100"
        state_bg = "rgba(255, 145, 0, 0.12)"
    elif state == "CONNECTING":
        state_label = "OPENING SERIAL PORT..."
        state_color = "#FFD600"
        state_bg = "rgba(255, 214, 0, 0.12)"
    elif state == "ERROR":
        state_label = f"ERROR: {last_err[:40]}" if last_err else "CONNECTION ERROR"
        state_color = "#FF5252"
        state_bg = "rgba(255, 82, 82, 0.12)"
    else:
        state_label = "DISCONNECTED (STANDBY)"
        state_color = "#94A3B8"
        state_bg = "rgba(148, 163, 184, 0.10)"

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.html(
            render_primary_health_card(
                title="Hardware Link State",
                value=state.replace("_", " "),
                subtext=state_label,
                state_color=state_color,
                bg_color=state_bg
            )
        )
    with c2:
        st.html(
            render_primary_health_card(
                title="Physical Interface",
                value=port,
                subtext=f"{baud} 8N1 UART Serial",
                state_color="#00E5FF",
                bg_color="rgba(0, 229, 255, 0.12)"
            )
        )
    with c3:
        st.html(
            render_primary_health_card(
                title="Telemetry Packets",
                value=f"#{pkt_count}",
                subtext=f"Stream Rate: {rate_hz:.1f} Hz (Errors: {err_count})",
                state_color="#00E676" if err_count == 0 else "#FF9100",
                bg_color="rgba(0, 230, 118, 0.10)"
            )
        )
    with c4:
        hs_text = "Verified (HELLO FPGA)" if handshake else "JSON Telemetry Stream"
        hs_color = "#00E676" if handshake else "#94A3B8"
        st.html(
            render_primary_health_card(
                title="FPGA Handshake",
                value="ONLINE" if handshake or pkt_count > 0 else "OFFLINE",
                subtext=hs_text,
                state_color=hs_color,
                bg_color="rgba(168, 85, 247, 0.12)"
            )
        )

    # Hardware provenance breakdown
    prov_rows = [
        {"Channel": "Die Temperature", "Provenance": "🟢 MEASURED (Physical On-Chip)", "Source": "7-Series XADC (DRP 0x00)"},
        {"Channel": "VCCINT Core Voltage", "Provenance": "🟢 MEASURED (Physical On-Chip)", "Source": "7-Series XADC (DRP 0x01)"},
        {"Channel": "VCCAUX Aux Voltage", "Provenance": "🟢 MEASURED (Physical On-Chip)", "Source": "7-Series XADC (DRP 0x02)"},
        {"Channel": "VCCBRAM RAM Voltage", "Provenance": "🟢 MEASURED (Physical On-Chip)", "Source": "7-Series XADC (DRP 0x06)"},
        {"Channel": "RO Frequency", "Provenance": "🟢 MEASURED (Physical On-Chip)", "Source": "5-Stage Ring Oscillator + 10ms Gated Counter"},
        {"Channel": "RO Stage Delay", "Provenance": "⚡ DERIVED (Mathematical Formula)", "Source": "tau = 1000 / (2 * 5 * f_MHz) = 100 / f_MHz"},
        {"Channel": "Functional Error Rate", "Provenance": "🟢 MEASURED (Physical On-Chip)", "Source": "PRBS-7 Hardware LFSR Pattern Checker"}
    ]
    df_prov = pd.DataFrame(prov_rows)
    st.dataframe(df_prov, width="stretch", hide_index=True)


def render_hardware_vs_estimated_comparison(
    hw_latest: pd.Series,
    est_inputs: Dict[str, Any],
    hw_pred: str,
    est_pred: str
):
    """
    Renders side-by-side comparison between real Basys 3 hardware telemetry
    and manual / estimated health assessment inputs.
    """
    rows = []
    channels = [
        ("Temperature", "Die Temperature", "°C"),
        ("VCCINT", "VCCINT Core Voltage", "V"),
        ("VCCAUX", "VCCAUX Aux Voltage", "V"),
        ("VCCBRAM", "VCCBRAM RAM Voltage", "V"),
        ("RO_Frequency", "Ring Oscillator Frequency", "MHz"),
        ("RO_Delay_ns", "Derived RO Stage Delay", "ns/stage"),
        ("Error_Rate", "Functional Error Rate", "")
    ]

    for key, name, unit in channels:
        hw_val = hw_latest.get(key, None)
        hw_str = f"{hw_val:.4f} {unit}".strip() if hw_val is not None else "N/A"

        est_val = est_inputs.get(key, None)
        if est_val is not None and str(est_val).strip() != "":
            try:
                est_float = float(est_val)
                est_str = f"{est_float:.4f} {unit}".strip()
            except ValueError:
                est_str = str(est_val)
        else:
            est_str = "Nominal Imputed"

        rows.append({
            "Sensor Channel": name,
            "Basys 3 Hardware (Live UART)": hw_str,
            "Estimated / Manual Input": est_str,
            "Agreement": "Aligned" if hw_str == est_str else "Variance"
        })

    comp_df = pd.DataFrame(rows)
    st.dataframe(comp_df, width="stretch", hide_index=True)

