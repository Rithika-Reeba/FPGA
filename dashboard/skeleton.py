"""
Skeleton loading screen: grey placeholder blocks with a soft shimmer that stand in for the dashboard
while the first load (libraries, board baseline) or a board switch is running, so the page never looks
empty or frozen. Pure HTML/CSS; no data, nothing to configure.
"""

_CSS = """
<style>
.sk-wrap { padding: 8px 4px 24px 4px; font-family: 'Inter', system-ui, sans-serif; }
.sk-msg { display:flex; align-items:center; gap:10px; margin: 4px 0 18px 0; font-size: 0.95rem; color:#94A3B8; }
.sk-dot { width:10px; height:10px; border-radius:50%; background:#38BDF8; animation: sk-pulse 1.1s ease-in-out infinite; }
.sk-block { border-radius: 10px; background: linear-gradient(90deg, #131a2b 25%, #1d2740 37%, #131a2b 63%);
            background-size: 400% 100%; animation: sk-shimmer 1.4s ease infinite; }
.sk-title { height: 56px; width: 62%; margin: 0 auto 22px auto; }
.sk-row { display:grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 14px; }
.sk-grid { display:grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin-top: 8px; }
.sk-kpi { height: 92px; }
.sk-card { height: 200px; }
.sk-section { height: 26px; width: 38%; margin: 22px 0 12px 0; }
@keyframes sk-shimmer { 0% { background-position: 100% 50%; } 100% { background-position: 0 50%; } }
@keyframes sk-pulse { 0%, 100% { opacity: .35; transform: scale(.85); } 50% { opacity: 1; transform: scale(1); } }
@media (max-width: 700px) { .sk-row { grid-template-columns: repeat(2, 1fr); } .sk-grid { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .sk-block, .sk-dot { animation: none; } }
</style>
"""


def skeleton_html(message: str) -> str:
    """Markup of the skeleton screen; `message` says what is being waited for."""
    kpis = "".join('<div class="sk-block sk-kpi"></div>' for _ in range(4))
    cards = "".join('<div class="sk-block sk-card"></div>' for _ in range(4))
    return (
        _CSS
        + '<div class="sk-wrap" role="status" aria-live="polite">'
        + f'<div class="sk-msg"><span class="sk-dot"></span><span>{message}</span></div>'
        + '<div class="sk-block sk-title"></div>'
        + f'<div class="sk-row">{kpis}</div>'
        + '<div class="sk-block sk-section"></div>'
        + f'<div class="sk-grid">{cards}</div>'
        + "</div>"
    )
