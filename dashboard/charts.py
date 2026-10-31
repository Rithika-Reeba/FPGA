"""
Interactive Technical Chart Builders for FPGA Health Monitoring Dashboard
========================================================================
Built with Altair for high-performance, dark-themed, responsive visualizations.
Strictly separates distinct physical scales onto their own dedicated charts.
"""

from typing import List, Tuple, Optional, Dict
import pandas as pd
import numpy as np
import altair as alt

# Reference lines come from the single source of truth (health_rules.py)
from dashboard.config import (
    SENSOR_CONFIG,
    RO_FREQ_NOMINAL_MHZ,
    RO_FREQ_WARNING_LOW_MHZ,
    RO_FREQ_CRITICAL_LOW_MHZ,
    RO_DELAY_NOMINAL_NS,
    RO_DELAY_WARNING_HIGH_NS,
    RO_DELAY_CRITICAL_HIGH_NS,
)


def apply_dark_theme(chart: alt.Chart) -> alt.Chart:
    """Applies a clean FPGA laboratory dark aesthetic to Altair charts."""
    return chart.configure(
        background="transparent"
    ).configure_view(
        strokeOpacity=0
    ).configure_axis(
        gridColor="rgba(255, 255, 255, 0.07)",
        domainColor="rgba(255, 255, 255, 0.2)",
        tickColor="rgba(255, 255, 255, 0.2)",
        labelColor="#94A3B8",
        titleColor="#E2E8F0",
        labelFontSize=11,
        titleFontSize=12,
        titleFontWeight="normal",
        labelFont="JetBrains Mono, Consolas, monospace",
        titleFont="Inter, sans-serif"
    ).configure_legend(
        labelColor="#CBD5E1",
        titleColor="#E2E8F0",
        labelFont="Inter, sans-serif",
        titleFont="Inter, sans-serif"
    )


def compute_adaptive_y_domain(
    series: pd.Series,
    baseline: Optional[float] = None,
    thresholds: Optional[List[float]] = None,
    min_span: float = 0.4,
    small_dev_threshold: float = 2.0,
    small_dev_padding: float = 0.12,
    major_dev_padding: float = 0.10,
    clamp_min: Optional[float] = None,
    clamp_max: Optional[float] = None,
    zoom_factor: float = 3.0
) -> Tuple[List[float], bool]:
    """
    Intelligent Adaptive Domain Calculator for FPGA Telemetry Graphs:
    - Small Deviation: Zooms in tightly around data points, magnifying subtle
      jitter, oscillations, and noise so they show prominently across the entire chart.
    - Major Deviation: Widens the scale to comfortably capture large excursions.
      
    Returns:
        (domain, is_small_dev):
            domain: [y_min, y_max] suitable for alt.Scale(domain=...)
            is_small_dev: True if data is in small-deviation (magnified) mode, False if major excursion
    """
    clean = series.dropna().astype(float) if series is not None else pd.Series(dtype=float)
    if clean.empty:
        center = float(baseline) if baseline is not None else 0.0
        span = float(min_span) if min_span > 0 else 1.0
        return [round(center - span / 2.0, 6), round(center + span / 2.0, 6)], True

    y_min = float(clean.min())
    y_max = float(clean.max())
    spread = y_max - y_min

    # Focus primarily on the active data cluster
    targets = [y_min, y_max]

    zf = max(float(zoom_factor), 1.0)
    # Only pull baseline into target domain if it is within close proximity of the data cluster
    if baseline is not None:
        base_val = float(baseline)
        close_dist = max(spread * 1.3, min_span / zf)
        if abs(base_val - (y_min + y_max) / 2.0) <= close_dist:
            targets.append(base_val)

    # Excursion from baseline
    if baseline is not None:
        excursion = max(abs(y_min - baseline), abs(y_max - baseline))
    else:
        excursion = spread / 2.0

    # Determine whether deviation is small or major
    is_small_dev = (spread <= small_dev_threshold) and (excursion <= small_dev_threshold * 2.0)

    if is_small_dev:
        t_min, t_max = min(targets), max(targets)
        # Scale min_span and padding according to zoom_factor
        effective_min_span = max(min_span / zf, 0.000001)
        span = max(t_max - t_min, effective_min_span)
        # Tight headroom/footroom: ~12% at 1x down to ~4% at ultra zoom
        pad_fraction = max(small_dev_padding / (zf ** 0.5), 0.04)
        pad = span * pad_fraction
        dom_min = t_min - pad
        dom_max = t_max + pad
    else:
        # Major deviation regime: SCALE ACCORDINGLY!
        if baseline is not None:
            targets.append(float(baseline))
        if thresholds:
            for th in thresholds:
                if th is not None:
                    th_val = float(th)
                    if (y_min <= th_val <= y_max) or (abs(th_val - y_min) <= spread * 0.25) or (abs(th_val - y_max) <= spread * 0.25):
                        targets.append(th_val)
        t_min, t_max = min(targets), max(targets)
        span = max(t_max - t_min, min_span)
        pad = span * major_dev_padding
        dom_min = t_min - pad
        dom_max = t_max + pad

    if clamp_min is not None:
        dom_min = max(dom_min, clamp_min)
    if clamp_max is not None:
        dom_max = min(dom_max, clamp_max)

    if dom_max <= dom_min:
        dom_max = dom_min + (min_span / zf)

    return [round(dom_min, 6), round(dom_max, 6)], is_small_dev


def create_temperature_chart(
    df: pd.DataFrame,
    baseline_temp: float = SENSOR_CONFIG["Temperature"]["nominal"],
    warning_temp: float = SENSOR_CONFIG["Temperature"]["warning_high"],
    adaptive_scaling: bool = True,
    zoom_factor: float = 3.0
) -> alt.Chart:
    """Graph 3: FPGA Die Temperature Trend (°C) with adaptive deviation scaling."""
    plot_df = df.reset_index()
    plot_df["Sample_Index"] = plot_df.index

    if adaptive_scaling and "Temperature" in plot_df.columns and not plot_df["Temperature"].dropna().empty:
        domain, is_small_dev = compute_adaptive_y_domain(
            plot_df["Temperature"],
            baseline=baseline_temp,
            thresholds=[warning_temp],
            min_span=0.4,
            small_dev_threshold=2.5,
            small_dev_padding=0.10,
            major_dev_padding=0.10,
            clamp_min=0.0,
            zoom_factor=zoom_factor
        )
        scale = alt.Scale(domain=domain, zero=False)
    else:
        scale = alt.Scale(zero=False)

    line = alt.Chart(plot_df).mark_line(
        color="#FF5252",
        strokeWidth=2.2
    ).encode(
        x=alt.X("Sample_Index:Q", title="Timestamp / Sample Sequence"),
        y=alt.Y("Temperature:Q", title="Die Temperature (°C)", scale=scale, axis=alt.Axis(format=".2f")),
        tooltip=[
            alt.Tooltip("Sample_Index:Q", title="Sample #"),
            alt.Tooltip("Temperature:Q", title="Temperature (°C)", format=".2f")
        ]
    )

    # Baseline reference line
    base_df = pd.DataFrame({"y": [baseline_temp]})
    base_rule = alt.Chart(base_df).mark_rule(
        color="#00E676",
        strokeDash=[3, 3],
        strokeWidth=1.2,
        opacity=0.8
    ).encode(y=alt.Y("y:Q", scale=scale))

    # Warning threshold line at 50°C
    thresh_df = pd.DataFrame({"y": [warning_temp]})
    warn_rule = alt.Chart(thresh_df).mark_rule(
        color="#FF9100",
        strokeDash=[4, 4],
        strokeWidth=1.2,
        opacity=0.7
    ).encode(y=alt.Y("y:Q", scale=scale))

    return apply_dark_theme(line + base_rule + warn_rule)


def create_ro_frequency_chart(
    df: pd.DataFrame,
    baseline_freq: float = RO_FREQ_NOMINAL_MHZ,
    warning_freq: float = RO_FREQ_WARNING_LOW_MHZ,
    critical_freq: float = RO_FREQ_CRITICAL_LOW_MHZ,
    adaptive_scaling: bool = True,
    zoom_factor: float = 3.0
) -> alt.Chart:
    """Graph 1: Ring Oscillator Frequency Trend (MHz) with adaptive deviation scaling."""
    plot_df = df.reset_index()
    plot_df["Sample_Index"] = plot_df.index

    tooltips = [
        alt.Tooltip("Sample_Index:Q", title="Sample #"),
        alt.Tooltip("RO_Frequency:Q", title="Calibrated Overall RO (MHz)", format=".2f"),
    ]
    if "RO_Raw_Frequency" in plot_df.columns:
        tooltips.append(alt.Tooltip("RO_Raw_Frequency:Q", title="Raw Hardware Mean (MHz)", format=".2f"))
    for r in ["RO_R1", "RO_R2", "RO_R3", "RO_R4"]:
        if r in plot_df.columns:
            tooltips.append(alt.Tooltip(f"{r}:Q", title=f"{r} (MHz)", format=".2f"))

    if adaptive_scaling and "RO_Frequency" in plot_df.columns and not plot_df["RO_Frequency"].dropna().empty:
        # Fit the axis to the measured data so its real irregular behaviour is visible. The
        # baseline only shapes the axis when it is close to the data; otherwise its line is
        # simply drawn outside the view (and widens the axis later if the data moves toward it).
        _series = plot_df["RO_Frequency"].astype(float)
        _spread = float(_series.max() - _series.min())
        _near = abs(baseline_freq - float(_series.mean())) <= max(3.0 * _spread, 0.5)
        domain, is_small_dev = compute_adaptive_y_domain(
            plot_df["RO_Frequency"],
            baseline=baseline_freq if _near else None,
            thresholds=[warning_freq, critical_freq],
            min_span=0.4,
            small_dev_threshold=1.5,
            small_dev_padding=0.10,
            major_dev_padding=0.10,
            zoom_factor=zoom_factor
        )
        scale = alt.Scale(domain=domain, zero=False)
    else:
        scale = alt.Scale(zero=False)

    line = alt.Chart(plot_df).mark_line(
        color="#00E5FF",
        strokeWidth=2.2
    ).encode(
        x=alt.X("Sample_Index:Q", title="Timestamp / Sample Sequence"),
        y=alt.Y("RO_Frequency:Q", title="RO Frequency (MHz)", scale=scale, axis=alt.Axis(format=".2f")),
        tooltip=tooltips
    )

    # Baseline reference line
    base_df = pd.DataFrame({"y": [baseline_freq]})
    base_rule = alt.Chart(base_df).mark_rule(clip=True, color="#38BDF8",
        strokeDash=[3, 3],
        strokeWidth=1.2,
        opacity=0.8
    ).encode(y=alt.Y("y:Q", scale=scale))

    # Warning threshold reference line (e.g. 422.9 MHz)
    warn_df = pd.DataFrame({"y": [warning_freq]})
    warn_rule = alt.Chart(warn_df).mark_rule(clip=True, color="#FFB300",
        strokeDash=[4, 4],
        strokeWidth=1.2,
        opacity=0.7
    ).encode(y=alt.Y("y:Q", scale=scale))

    # Critical threshold reference line (e.g. 412.0 MHz)
    crit_df = pd.DataFrame({"y": [critical_freq]})
    crit_rule = alt.Chart(crit_df).mark_rule(clip=True, color="#FF1744",
        strokeDash=[4, 4],
        strokeWidth=1.2,
        opacity=0.7
    ).encode(y=alt.Y("y:Q", scale=scale))

    return apply_dark_theme(line + base_rule + warn_rule + crit_rule)


def create_ro_delay_chart(
    df: pd.DataFrame,
    baseline_delay: float = RO_DELAY_NOMINAL_NS,
    warning_delay: float = RO_DELAY_WARNING_HIGH_NS,
    critical_delay: float = RO_DELAY_CRITICAL_HIGH_NS,
    adaptive_scaling: bool = True,
    zoom_factor: float = 3.0
) -> alt.Chart:
    """Graph 2: Ring Oscillator Delay Trend with adaptive deviation scaling."""
    plot_df = df.reset_index()
    plot_df["Sample_Index"] = plot_df.index
    # tau = 100 / f_MHz at full precision: the stored column is rounded to 4 decimals, which
    # shows up as stair-steps once the axis is zoomed in on small variations.
    if "RO_Frequency" in plot_df.columns:
        freq = plot_df["RO_Frequency"].astype(float)
        plot_df["RO_Delay_ns"] = (100.0 / freq).where(freq > 0, plot_df.get("RO_Delay_ns"))

    if adaptive_scaling and "RO_Delay_ns" in plot_df.columns and not plot_df["RO_Delay_ns"].dropna().empty:
        domain, is_small_dev = compute_adaptive_y_domain(
            plot_df["RO_Delay_ns"],
            baseline=baseline_delay,
            thresholds=[warning_delay, critical_delay],
            min_span=0.0004,
            small_dev_threshold=0.0018,
            small_dev_padding=0.10,
            major_dev_padding=0.10,
            zoom_factor=zoom_factor
        )
        scale = alt.Scale(domain=domain, zero=False)
    else:
        scale = alt.Scale(zero=False)

    line = alt.Chart(plot_df).mark_line(
        color="#D946EF",
        strokeWidth=2.2
    ).encode(
        x=alt.X("Sample_Index:Q", title="Timestamp / Sample Sequence"),
        y=alt.Y("RO_Delay_ns:Q", title="Derived RO Stage Delay (ns)", scale=scale, axis=alt.Axis(format=".4f")),
        tooltip=[
            alt.Tooltip("Sample_Index:Q", title="Sample #"),
            alt.Tooltip("RO_Delay_ns:Q", title="Stage Delay (ns)", format=".4f")
        ]
    )

    # Baseline reference line
    base_df = pd.DataFrame({"y": [baseline_delay]})
    base_rule = alt.Chart(base_df).mark_rule(
        color="#A855F7",
        strokeDash=[3, 3],
        strokeWidth=1.2,
        opacity=0.8
    ).encode(y=alt.Y("y:Q", scale=scale))

    # Warning threshold reference line (e.g. 0.2365 ns)
    warn_df = pd.DataFrame({"y": [warning_delay]})
    warn_rule = alt.Chart(warn_df).mark_rule(
        color="#FFB300",
        strokeDash=[4, 4],
        strokeWidth=1.2,
        opacity=0.7
    ).encode(y=alt.Y("y:Q", scale=scale))

    # Critical threshold reference line (e.g. 0.2427 ns)
    crit_df = pd.DataFrame({"y": [critical_delay]})
    crit_rule = alt.Chart(crit_df).mark_rule(
        color="#FF1744",
        strokeDash=[4, 4],
        strokeWidth=1.2,
        opacity=0.7
    ).encode(y=alt.Y("y:Q", scale=scale))

    return apply_dark_theme(line + base_rule + warn_rule + crit_rule)


def create_error_rate_chart(
    df: pd.DataFrame,
    adaptive_scaling: bool = True,
    zoom_factor: float = 3.0
) -> alt.Chart:
    """Graph 4: Functional Error Rate Trend with adaptive deviation scaling."""
    plot_df = df.reset_index()
    plot_df["Sample_Index"] = plot_df.index

    if adaptive_scaling and "Error_Rate" in plot_df.columns and not plot_df["Error_Rate"].dropna().empty:
        clean = plot_df["Error_Rate"].dropna().astype(float)
        y_max = float(clean.max()) if not clean.empty else 0.000010
        y_min = float(clean.min()) if not clean.empty else 0.000010
        zf = max(float(zoom_factor), 1.0)
        if y_max <= 0.000100:
            # Small deviation (nominal PRBS ~10 ppm): zoom tightly around subtle ppm variations
            spr = max(y_max - y_min, 0.000003 / zf)
            pad = spr * max(0.08 / (zf ** 0.5), 0.03)
            dom_min = max(0.0, y_min - pad)
            dom_max = y_max + pad
            scale = alt.Scale(domain=[round(dom_min, 6), round(dom_max, 6)], zero=False)
        else:
            # Major deviation (fault injection ~2000 ppm): scale out smoothly
            dom_max = round(y_max * 1.12, 6)
            scale = alt.Scale(domain=[0.0, dom_max], zero=True)
    else:
        scale = alt.Scale(zero=True)

    area = alt.Chart(plot_df).mark_area(
        line={"color": "#FFAB00", "width": 2},
        color=alt.Gradient(
            gradient="linear",
            stops=[
                alt.GradientStop(color="rgba(255, 171, 0, 0.45)", offset=0),
                alt.GradientStop(color="rgba(255, 171, 0, 0.02)", offset=1)
            ],
            x1=1, x2=1, y1=1, y2=0
        )
    ).encode(
        x=alt.X("Sample_Index:Q", title="Timestamp / Sample Sequence"),
        y=alt.Y("Error_Rate:Q", title="Functional Error Rate", scale=scale, axis=alt.Axis(format=".5f")),
        tooltip=[
            alt.Tooltip("Sample_Index:Q", title="Sample #"),
            alt.Tooltip("Error_Rate:Q", title="Error Rate", format=".6f")
        ]
    )
    return apply_dark_theme(area)


def create_voltage_chart(
    df: pd.DataFrame,
    rail: str = "VCCINT",
    nominal_voltage: float = 1.000,
    adaptive_scaling: bool = True,
    zoom_factor: float = 3.0
) -> alt.Chart:
    """Graph 5: Supply Voltage Rail Trend (V) with adaptive deviation scaling."""
    plot_df = df.reset_index()
    plot_df["Sample_Index"] = plot_df.index

    rail_colors = {
        "VCCINT": "#00E676",
        "VCCAUX": "#38BDF8",
        "VCCBRAM": "#A855F7"
    }
    color = rail_colors.get(rail, "#00E676")

    if adaptive_scaling and rail in plot_df.columns and not plot_df[rail].dropna().empty:
        domain, is_small_dev = compute_adaptive_y_domain(
            plot_df[rail],
            baseline=nominal_voltage,
            min_span=0.005,
            small_dev_threshold=0.020,
            small_dev_padding=0.10,
            major_dev_padding=0.10,
            clamp_min=0.0,
            zoom_factor=zoom_factor
        )
        scale = alt.Scale(domain=domain, zero=False)
    else:
        scale = alt.Scale(zero=False)

    line = alt.Chart(plot_df).mark_line(
        color=color,
        strokeWidth=2.0
    ).encode(
        x=alt.X("Sample_Index:Q", title="Timestamp / Sample Sequence"),
        y=alt.Y(f"{rail}:Q", title=f"{rail} Voltage (V)", scale=scale, axis=alt.Axis(format=".3f")),
        tooltip=[
            alt.Tooltip("Sample_Index:Q", title="Sample #"),
            alt.Tooltip(f"{rail}:Q", title=f"{rail} (V)", format=".4f")
        ]
    )

    # Nominal voltage reference line
    nom_df = pd.DataFrame({"y": [nominal_voltage]})
    nom_rule = alt.Chart(nom_df).mark_rule(
        color="rgba(255, 255, 255, 0.35)",
        strokeDash=[2, 2],
        strokeWidth=1.0
    ).encode(y=alt.Y("y:Q", scale=scale))

    return apply_dark_theme(line + nom_rule)


def create_health_prediction_trend_chart(df: pd.DataFrame) -> alt.Chart:
    """
    Graph 6: FPGA Health Prediction Trend Over Time.
    Encodes Healthy=0, Warning=1, Degraded=2 with exact ML classes.
    """
    plot_df = df.reset_index()
    plot_df["Sample_Index"] = plot_df.index

    state_map = {"Healthy": 0, "Warning": 1, "Degraded": 2}
    if "Predicted_Health" in plot_df.columns:
        plot_df["Health_Level"] = plot_df["Predicted_Health"].map(lambda x: state_map.get(str(x), 0))
        plot_df["Health_Label"] = plot_df["Predicted_Health"].astype(str)
    elif "Health" in plot_df.columns:
        plot_df["Health_Level"] = plot_df["Health"].map(lambda x: state_map.get(str(x), 0))
        plot_df["Health_Label"] = plot_df["Health"].astype(str)
    else:
        plot_df["Health_Level"] = 0
        plot_df["Health_Label"] = "Healthy"

    chart = alt.Chart(plot_df).mark_circle(
        size=45
    ).encode(
        x=alt.X("Sample_Index:Q", title="Timestamp / Sample Sequence"),
        y=alt.Y(
            "Health_Level:O",
            title="Predicted Health State",
            axis=alt.Axis(
                values=[0, 1, 2],
                labelExpr="datum.value == 0 ? 'Healthy' : datum.value == 1 ? 'Warning' : 'Degraded'"
            )
        ),
        color=alt.Color(
            "Health_Label:N",
            scale=alt.Scale(
                domain=["Healthy", "Warning", "Degraded"],
                range=["#00E676", "#FFD600", "#FF9100"]
            ),
            legend=alt.Legend(title="Health State")
        ),
        tooltip=[
            alt.Tooltip("Sample_Index:Q", title="Sample #"),
            alt.Tooltip("Health_Label:N", title="Health State")
        ]
    )
    return apply_dark_theme(chart)


def create_normalized_indicators_chart(df: pd.DataFrame) -> alt.Chart:
    """
    Graph 7: Normalized FPGA Health Indicators.
    Normalizes:
    - Temperature (0 to 1)
    - RO Frequency Degradation (inverted: 0 at max freq, 1 at min freq)
    - RO Delay Increase (0 at min delay, 1 at max delay)
    - Functional Error Rate (0 to 1)
    """
    plot_df = pd.DataFrame()
    plot_df["Sample_Index"] = df.reset_index().index

    def min_max_norm(series: pd.Series, noise_floor: float = 0.01, invert: bool = False) -> pd.Series:
        s_min, s_max = series.min(), series.max()
        diff = s_max - s_min
        if diff < noise_floor:
            return pd.Series(0.0, index=series.index)
        norm = (series - s_min) / diff
        return (1.0 - norm) if invert else norm

    norm_temp = min_max_norm(df["Temperature"], noise_floor=0.5)
    norm_ro_deg = min_max_norm(df["RO_Frequency"], noise_floor=0.5, invert=True)
    norm_delay = min_max_norm(df["RO_Delay_ns"], noise_floor=0.0005)
    norm_error = min_max_norm(df["Error_Rate"], noise_floor=0.000020)

    melted = pd.DataFrame({
        "Sample_Index": plot_df["Sample_Index"],
        "Normalized Temperature": norm_temp.values,
        "RO Frequency Degradation": norm_ro_deg.values,
        "RO Delay Increase": norm_delay.values,
        "Functional Error Rate": norm_error.values
    }).melt(
        id_vars=["Sample_Index"],
        var_name="Indicator",
        value_name="Normalized_Value"
    )

    chart = alt.Chart(melted).mark_line(
        strokeWidth=2.0
    ).encode(
        x=alt.X("Sample_Index:Q", title="Timestamp / Sample Sequence"),
        y=alt.Y(
            "Normalized_Value:Q",
            title="Normalized Indicator Index (0.0 to 1.0)",
            scale=alt.Scale(domain=[0.0, 1.0])
        ),
        color=alt.Color(
            "Indicator:N",
            scale=alt.Scale(
                domain=[
                    "Normalized Temperature",
                    "RO Frequency Degradation",
                    "RO Delay Increase",
                    "Functional Error Rate"
                ],
                range=["#FF5252", "#00E5FF", "#D946EF", "#FFAB00"]
            ),
            legend=alt.Legend(title="Sensor Indicator", orient="top")
        ),
        tooltip=[
            alt.Tooltip("Sample_Index:Q", title="Sample #"),
            alt.Tooltip("Indicator:N", title="Indicator"),
            alt.Tooltip("Normalized_Value:Q", title="Score", format=".3f")
        ]
    )
    return apply_dark_theme(chart)


def create_feature_importance_chart(features: List[str], importances: np.ndarray, top_n: int = 8) -> alt.Chart:
    """Top Feature Importance horizontal bar chart."""
    pairs = sorted(zip(features, importances), key=lambda x: x[1], reverse=True)[:top_n]
    feat_df = pd.DataFrame(pairs, columns=["Feature", "Importance"])
    feat_df["Feature"] = feat_df["Feature"].str.replace("_", " ")

    chart = alt.Chart(feat_df).mark_bar(
        color="#00E5FF",
        cornerRadiusTopRight=4,
        cornerRadiusBottomRight=4
    ).encode(
        y=alt.Y("Feature:N", sort="-x", title="Telemetry Feature"),
        x=alt.X("Importance:Q", title="Relative Feature Importance Weight"),
        tooltip=[
            alt.Tooltip("Feature:N", title="Feature"),
            alt.Tooltip("Importance:Q", title="Weight", format=".4f")
        ]
    )
    return apply_dark_theme(chart)
