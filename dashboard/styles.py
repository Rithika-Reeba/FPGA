"""
Custom CSS & Styling Definitions for the FPGA Health Monitoring Dashboard
========================================================================
Embedded-systems / FPGA laboratory aesthetic with technical typography,
dark slate background, glowing status badges, and an inline SVG FPGA chip illustration.
"""

import textwrap
from dashboard.config import HEALTH_COLORS, STATUS_BG_COLORS


def get_fpga_chip_svg(size: int = 110) -> str:
    """
    Returns a clean, high-tech SVG illustration of an FPGA chip (BGA/QFP package)
    with exposed silicon die, logic fabric array, gold wire traces, and IC pinouts.
    Zero external URL dependency.
    """
    return textwrap.dedent(f"""
<svg width="{size}" height="{size}" viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" style="display: block; margin: 0 auto; filter: drop-shadow(0 0 12px rgba(0, 229, 255, 0.45));">
  <rect x="15" y="15" width="90" height="90" rx="8" fill="#121826" stroke="#00E5FF" stroke-width="2.2" />
  <circle cx="23" cy="23" r="3.5" fill="#00E5FF" />
  <path d="M15 35 H30 M15 50 H30 M15 65 H30 M15 80 H30" stroke="#00E5FF" stroke-width="1.2" opacity="0.6"/>
  <path d="M105 35 H90 M105 50 H90 M105 65 H90 M105 80 H90" stroke="#00E5FF" stroke-width="1.2" opacity="0.6"/>
  <path d="M35 15 V30 M50 15 V30 M65 15 V30 M80 15 V30" stroke="#00E5FF" stroke-width="1.2" opacity="0.6"/>
  <path d="M35 105 V90 M50 105 V90 M65 105 V90 M80 105 V90" stroke="#00E5FF" stroke-width="1.2" opacity="0.6"/>
  <rect x="32" y="32" width="56" height="56" rx="4" fill="#0A0E17" stroke="#00B0FF" stroke-width="1.5" />
  <g stroke="#00E5FF" stroke-width="0.8" opacity="0.45">
    <line x1="38" y1="42" x2="82" y2="42" />
    <line x1="38" y1="52" x2="82" y2="52" />
    <line x1="38" y1="62" x2="82" y2="62" />
    <line x1="38" y1="72" x2="82" y2="72" />
    <line x1="42" y1="38" x2="42" y2="82" />
    <line x1="52" y1="38" x2="52" y2="82" />
    <line x1="62" y1="38" x2="62" y2="82" />
    <line x1="72" y1="38" x2="72" y2="82" />
  </g>
  <circle cx="60" cy="60" r="10" fill="#00E5FF" fill-opacity="0.15" stroke="#00E5FF" stroke-width="1.8" />
  <circle cx="60" cy="60" r="4" fill="#00E5FF" />
  <text x="60" y="50" font-family="'Consolas', 'Courier New', monospace" font-size="5" fill="#90CAF9" text-anchor="middle" font-weight="bold" letter-spacing="0.5">ARTIX-7</text>
  <text x="60" y="74" font-family="'Consolas', 'Courier New', monospace" font-size="4" fill="#00E5FF" text-anchor="middle" letter-spacing="0.5">RO ENGINE</text>
</svg>
""").strip()


def get_custom_css() -> str:
    """Returns CSS rules for the entire dashboard."""
    return textwrap.dedent("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;800&family=Inter:wght@400;500;600;700&display=swap');

.main, .stApp {
    background-color: #0B0F19;
    color: #E2E8F0;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

code, .stMetricValue, .tech-mono {
    font-family: 'JetBrains Mono', 'Consolas', monospace !important;
}

.header-box {
    text-align: center;
    padding: 20px 24px;
    background: linear-gradient(180deg, rgba(16, 24, 40, 0.85) 0%, rgba(11, 15, 25, 0.95) 100%);
    border: 1px solid rgba(0, 229, 255, 0.25);
    border-radius: 12px;
    margin-bottom: 24px;
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.5), inset 0 0 16px rgba(0, 229, 255, 0.05);
}

.header-title {
    font-size: 2.25rem;
    font-weight: 800;
    letter-spacing: -0.5px;
    margin: 12px 0 6px 0;
    background: linear-gradient(135deg, #FFFFFF 30%, #00E5FF 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    text-shadow: 0 0 20px rgba(0, 229, 255, 0.3);
}

.header-subtitle {
    font-size: 1.05rem;
    color: #94A3B8;
    font-weight: 500;
    margin: 10px 0 14px 0;
    letter-spacing: 0.2px;
}

.status-badge-container {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    margin-top: 8px;
}

.badge-pill {
    display: inline-flex;
    align-items: center;
    padding: 5px 14px;
    border-radius: 9999px;
    font-size: 0.82rem;
    font-weight: 600;
    letter-spacing: 0.5px;
    font-family: 'JetBrains Mono', monospace;
}

.badge-active {
    background: rgba(0, 230, 118, 0.12);
    color: #00E676;
    border: 1px solid rgba(0, 230, 118, 0.4);
    box-shadow: 0 0 10px rgba(0, 230, 118, 0.2);
}

.badge-mock {
    background: rgba(0, 229, 255, 0.12);
    color: #00E5FF;
    border: 1px solid rgba(0, 229, 255, 0.4);
}

.badge-live {
    background: rgba(255, 145, 0, 0.15);
    color: #FF9100;
    border: 1px solid rgba(255, 145, 0, 0.5);
    box-shadow: 0 0 12px rgba(255, 145, 0, 0.25);
}

.badge-estimated {
    background: rgba(168, 85, 247, 0.15);
    color: #C084FC;
    border: 1px solid rgba(168, 85, 247, 0.5);
    box-shadow: 0 0 12px rgba(168, 85, 247, 0.25);
}

.badge-chip {
    background: rgba(148, 163, 184, 0.1);
    color: #CBD5E1;
    border: 1px solid rgba(148, 163, 184, 0.25);
}

.pulse-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background-color: #00E676;
    margin-right: 8px;
    box-shadow: 0 0 8px #00E676;
    animation: pulse-animation 1.8s infinite;
}

@keyframes pulse-animation {
    0% { transform: scale(0.95); opacity: 0.8; }
    50% { transform: scale(1.3); opacity: 1; }
    100% { transform: scale(0.95); opacity: 0.8; }
}

.section-header {
    font-size: 1.35rem;
    font-weight: 700;
    color: #F8FAFC;
    margin: 28px 0 14px 0;
    padding-bottom: 8px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    display: flex;
    align-items: center;
    gap: 10px;
    letter-spacing: 0.2px;
}

.section-header span.tag {
    font-size: 0.75rem;
    font-family: 'JetBrains Mono', monospace;
    padding: 2px 8px;
    border-radius: 4px;
    background: rgba(0, 229, 255, 0.12);
    color: #00E5FF;
    border: 1px solid rgba(0, 229, 255, 0.3);
    font-weight: 600;
}

.health-card {
    background: #111827;
    border-radius: 10px;
    padding: 20px;
    border-top: 4px solid;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
    transition: all 0.25s ease;
    position: relative;
    overflow: hidden;
}

.health-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.45);
}

.card-label {
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #94A3B8;
    font-weight: 600;
    margin-bottom: 6px;
}

.card-value {
    font-size: 2.1rem;
    font-weight: 800;
    font-family: 'JetBrains Mono', monospace;
    line-height: 1.1;
    margin-bottom: 6px;
}

.card-subtext {
    font-size: 0.82rem;
    color: #64748B;
    font-weight: 500;
}

.measurement-card {
    background: #111827;
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 8px;
    padding: 14px 16px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
    transition: border-color 0.2s;
}

.measurement-card:hover {
    border-color: rgba(0, 229, 255, 0.35);
}

.meas-label {
    font-size: 0.78rem;
    color: #94A3B8;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
}

.meas-value {
    font-size: 1.45rem;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
    color: #F8FAFC;
}

.meas-unit {
    font-size: 0.85rem;
    color: #00E5FF;
    font-weight: 500;
    margin-left: 3px;
}

.meas-delta {
    font-size: 0.75rem;
    margin-top: 4px;
    font-family: 'JetBrains Mono', monospace;
}

.science-callout {
    background: rgba(15, 23, 42, 0.75);
    border-left: 3px solid #00E5FF;
    border-radius: 0 8px 8px 0;
    padding: 10px 14px;
    margin: 10px 0 16px 0;
    font-size: 0.84rem;
    color: #CBD5E1;
    line-height: 1.45;
}

.science-callout strong {
    color: #00E5FF;
}

/* Full-width container with compact centered cubes for FPGA Health Risk Map */
.risk-map-container {
    background: #0F172A;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    padding: 18px 24px;
    margin: 10px 0;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
    width: 100%;
}

.risk-grid-wrapper {
    display: flex;
    justify-content: center;
    align-items: center;
    margin: 14px 0;
}

.risk-grid {
    display: grid;
    grid-template-columns: repeat(5, 52px);
    gap: 8px;
    justify-content: center;
}

.risk-cell {
    width: 52px;
    height: 52px;
    border-radius: 6px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.64rem;
    font-weight: 700;
    transition: all 0.25s ease;
    box-shadow: inset 0 0 8px rgba(0, 0, 0, 0.35);
    border: 1px solid rgba(255, 255, 255, 0.12);
}

.risk-cell:hover {
    transform: scale(1.08);
    box-shadow: 0 0 12px rgba(0, 229, 255, 0.4);
    z-index: 2;
}

.risk-cell-label {
    font-size: 0.52rem;
    opacity: 0.72;
    font-weight: 500;
    margin-bottom: 2px;
}

.agent-container {
    background: linear-gradient(180deg, #111827 0%, #0F172A 100%);
    border: 1px solid rgba(0, 229, 255, 0.3);
    border-radius: 10px;
    padding: 22px;
    margin: 14px 0;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
}

.agent-badge {
    display: inline-block;
    background: rgba(0, 229, 255, 0.15);
    color: #00E5FF;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    padding: 3px 10px;
    border-radius: 4px;
    font-weight: 700;
    letter-spacing: 0.5px;
    margin-bottom: 12px;
}

.action-card {
    background: rgba(15, 23, 42, 0.85);
    border-left: 3px solid #38BDF8;
    border-radius: 0 6px 6px 0;
    padding: 10px 14px;
    margin-bottom: 8px;
    font-size: 0.88rem;
}

.action-category {
    font-weight: 700;
    color: #38BDF8;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    text-transform: uppercase;
    margin-bottom: 2px;
}

div[data-testid="stMetricValue"] {
    font-size: 1.6rem !important;
    font-weight: 700 !important;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
}

.stTabs [data-baseweb="tab"] {
    border-radius: 6px 6px 0 0;
    padding: 8px 16px;
    background-color: rgba(15, 23, 42, 0.6);
    color: #94A3B8;
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-bottom: none;
}

.stTabs [aria-selected="true"] {
    background-color: #1E293B !important;
    color: #00E5FF !important;
    border-color: rgba(0, 229, 255, 0.4) !important;
}
/* Test mode switch: very small and faint, pinned to the bottom-left corner; fully visible only on hover. */
[data-testid="stSidebar"] .st-key-test_mode {
    position: fixed; left: 8px; bottom: 4px; z-index: 50;
    opacity: 0.12 !important; transform: scale(0.5); transform-origin: left bottom;
    width: auto !important; transition: opacity .25s;
}
[data-testid="stSidebar"] .st-key-test_mode:hover { opacity: 0.9 !important; }

/* Streamlit fades every element left over from the previous run to about a third of its brightness while
   the script runs, which turned the whole page nearly black on every refresh and board switch. Keep
   everything at full brightness instead. */
[data-stale="true"], .stale-element, [data-testid="stMain"] [data-stale="true"] {
    opacity: 1 !important;
    transition: none !important;
}
</style>
""").strip()


def render_primary_health_card(title: str, value: str, subtext: str, state_color: str, bg_color: str) -> str:
    """Generates HTML for top-level health KPI metric cards."""
    return textwrap.dedent(f"""
<div class="health-card" style="border-top-color: {state_color}; background-color: #111827;">
    <div class="card-label">{title}</div>
    <div class="card-value" style="color: {state_color};">{value}</div>
    <div class="card-subtext">{subtext}</div>
</div>
""").strip()


def render_measurement_card(label: str, value_str: str, unit: str, delta_str: str = "", delta_color: str = "#94A3B8") -> str:
    """Generates HTML for individual sensor telemetry metric cards."""
    delta_html = f'<div class="meas-delta" style="color: {delta_color};">{delta_str}</div>' if delta_str else ''
    return textwrap.dedent(f"""
<div class="measurement-card">
    <div class="meas-label">{label}</div>
    <div>
        <span class="meas-value">{value_str}</span>
        <span class="meas-unit">{unit}</span>
    </div>
    {delta_html}
</div>
""").strip()
