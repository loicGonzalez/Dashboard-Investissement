"""CSS et composants visuels — style fintech."""
import streamlit as st

GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}
.stApp { background: #0a0b0d; color: #e8eaed; }
header[data-testid="stHeader"] {
    background: rgba(10, 11, 13, 0.75);
    backdrop-filter: blur(12px);
}
h1, h2, h3 {
    color: #f5f6f8 !important;
    letter-spacing: -0.03em !important;
    font-weight: 600 !important;
}
.hero {
    background: linear-gradient(145deg, #12141a 0%, #0e1016 50%, #141820 100%);
    border: 1px solid #1c1f28;
    border-radius: 24px;
    padding: 1.75rem 1.75rem 1.5rem 1.75rem;
    margin: 0 0 1.25rem 0;
    position: relative;
    overflow: hidden;
}
.hero::before {
    content: "";
    position: absolute;
    top: -40%; right: -10%;
    width: 55%; height: 140%;
    background: radial-gradient(ellipse, rgba(99,102,241,0.12) 0%, transparent 70%);
    pointer-events: none;
}
.hero-label {
    font-size: 0.8rem; color: #8b92a5; font-weight: 500;
    letter-spacing: 0.04em; text-transform: uppercase; margin-bottom: 0.35rem;
}
.hero-value {
    font-size: 2.75rem; font-weight: 700; color: #ffffff;
    letter-spacing: -0.04em; line-height: 1.1; margin: 0.15rem 0 0.5rem 0;
}
.hero-delta-pos {
    display: inline-flex; align-items: center; gap: 0.35rem;
    color: #3dd68c; font-size: 1rem; font-weight: 600;
}
.hero-delta-neg {
    display: inline-flex; align-items: center; gap: 0.35rem;
    color: #ff6b6b; font-size: 1rem; font-weight: 600;
}
.hero-meta { color: #8b92a5; font-size: 0.85rem; margin-top: 0.65rem; }

.kpi-card {
    background: #12141a; border: 1px solid #1c1f28; border-radius: 18px;
    padding: 1.15rem 1.25rem; height: 100%;
}
.kpi-label {
    font-size: 0.72rem; color: #8b92a5; text-transform: uppercase;
    letter-spacing: 0.07em; font-weight: 500; margin-bottom: 0.4rem;
}
.kpi-value {
    font-size: 1.55rem; font-weight: 700; color: #f5f6f8;
    line-height: 1.15; letter-spacing: -0.02em;
}
.kpi-delta-pos { color: #3dd68c; font-size: 0.88rem; margin-top: 0.4rem; font-weight: 600; }
.kpi-delta-neg { color: #ff6b6b; font-size: 0.88rem; margin-top: 0.4rem; font-weight: 600; }
.kpi-sub { color: #6b7280; font-size: 0.78rem; margin-top: 0.25rem; }
.kpi-help {
    display: inline-block; margin-left: 0.3rem; color: #5c6370;
    font-size: 0.7rem; cursor: help; border-bottom: 1px dotted #5c6370;
}
.kpi-legend {
    color: #8b92a5; font-size: 0.78rem; line-height: 1.5;
    margin: 0.5rem 0 1rem 0; padding: 0.7rem 1rem;
    background: #0e1016; border: 1px solid #1c1f28; border-radius: 12px;
}
.env-card {
    background: #12141a; border: 1px solid #1c1f28; border-radius: 20px;
    padding: 1.2rem 1.25rem 1rem 1.25rem; height: 100%; position: relative;
}
.env-card-title {
    font-size: 0.75rem; font-weight: 600; letter-spacing: 0.08em;
    text-transform: uppercase; margin-bottom: 0.55rem;
}
.env-card-valo {
    font-size: 1.65rem; font-weight: 700; color: #ffffff;
    line-height: 1.15; letter-spacing: -0.03em;
}
.env-card-sub { color: #8b92a5; font-size: 0.82rem; margin-top: 0.45rem; }
.env-card-badge {
    position: absolute; top: 1rem; right: 1rem;
    width: 0.5rem; height: 0.5rem; border-radius: 999px;
    background: #3dd68c; box-shadow: 0 0 8px rgba(61,214,140,0.45);
}
.env-card-badge.warn { background: #f5a623; }
.env-card-badge.bad { background: #ff6b6b; }
.env-weight {
    display: inline-block; margin-top: 0.65rem; padding: 0.2rem 0.6rem;
    border-radius: 999px; background: #1a1d27; color: #b0b6c4;
    font-size: 0.72rem; font-weight: 600;
}
.chip-score {
    display: inline-flex; align-items: center; gap: 0.35rem;
    padding: 0.4rem 0.85rem; border-radius: 999px; font-size: 0.8rem;
    font-weight: 600; border: 1px solid #1c1f28; background: #12141a;
    margin-right: 0.4rem; margin-top: 0.25rem;
}
.chip-pos { color: #3dd68c; border-color: #1a3d2e; background: #0f1f18; }
.chip-neg { color: #ff6b6b; border-color: #3d1a1a; background: #1f1010; }
.chip-neutral { color: #8b92a5; }
.health-bar {
    background: #12141a; border: 1px solid #1c1f28; border-radius: 14px;
    padding: 0.7rem 1.1rem; margin: 0 0 1.1rem 0; font-size: 0.82rem;
    color: #b0b6c4; display: flex; flex-wrap: wrap; gap: 0.75rem 1.25rem; align-items: center;
}
.health-ok { color: #3dd68c; }
.health-warn { color: #f5a623; }
.health-bad { color: #ff6b6b; }
.section-card {
    background: #12141a; border: 1px solid #1c1f28; border-radius: 20px;
    padding: 1.15rem 1.25rem 0.5rem 1.25rem; margin-bottom: 0.9rem;
}
.empty-state {
    background: #12141a; border: 1px dashed #2a3040; border-radius: 20px;
    padding: 2.5rem 1.5rem; text-align: center; margin: 2rem 0;
}
.empty-state h3 { color: #f5f6f8; margin-bottom: 0.5rem; }
.empty-state p { color: #8b92a5; margin-bottom: 1rem; }
.goal-wrap {
    background: #12141a; border: 1px solid #1c1f28; border-radius: 18px;
    padding: 1.1rem 1.25rem; margin: 0.5rem 0 1rem 0;
}
.goal-label { color: #8b92a5; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.07em; }
.goal-title { color: #f5f6f8; font-weight: 700; font-size: 1.1rem; margin: 0.25rem 0 0.7rem 0; }
.goal-bar-bg { background: #1a1d27; border-radius: 999px; height: 8px; overflow: hidden; }
.goal-bar-fg {
    height: 100%; border-radius: 999px;
    background: linear-gradient(90deg, #6366f1, #3dd68c);
}
.goal-meta { color: #8b92a5; font-size: 0.82rem; margin-top: 0.55rem; }
.pill {
    display: inline-block; padding: 0.25rem 0.7rem; border-radius: 999px;
    font-size: 0.7rem; font-weight: 600; letter-spacing: 0.05em;
}
.pill-pea { background: #152038; color: #7eb6ff; }
.pill-per { background: #2a2210; color: #f0c14d; }
.pill-cto { background: #10241c; color: #5ee4a8; }
section[data-testid="stSidebar"] {
    background: #0c0d11 !important; border-right: 1px solid #1c1f28;
}
section[data-testid="stSidebar"] .stPageLink a {
    border-radius: 10px !important; padding: 0.45rem 0.65rem !important; font-weight: 500 !important;
}
section[data-testid="stSidebar"] .stPageLink a:hover { background: #161922 !important; }
div[data-testid="stExpander"] {
    background: #12141a; border: 1px solid #1c1f28; border-radius: 16px; margin-bottom: 0.65rem;
}
.stButton > button {
    border-radius: 12px !important; font-weight: 600 !important; border: 1px solid #2a3040 !important;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #6366f1, #4f46e5) !important;
    border: none !important; color: white !important;
}
</style>
"""


PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#b0b6c4", family="Inter, sans-serif", size=12),
    margin=dict(l=10, r=10, t=30, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
)

def inject_css():
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def kpi_card(col, label, value, delta=None, sub=None, positive=True, help_text=None):
    """Carte KPI HTML. help_text = info-bulle au survol du libellé."""
    delta_html = ""
    if delta is not None:
        cls = "kpi-delta-pos" if positive else "kpi-delta-neg"
        delta_html = f'<div class="{cls}">{delta}</div>'
    sub_html = f'<div class="kpi-sub">{sub}</div>' if sub else ""
    help_html = ""
    if help_text:
        # title = tooltip natif navigateur
        safe = str(help_text).replace('"', "&quot;")
        help_html = f'<span class="kpi-help" title="{safe}">?</span>'
    html = (
        f'<div class="kpi-card">'
        f'<div class="kpi-label">{label}{help_html}</div>'
        f'<div class="kpi-value">{value}</div>'
        f'{delta_html}'
        f'{sub_html}'
        f'</div>'
    )
    col.markdown(html, unsafe_allow_html=True)


def kpi_legend(lines):
    """Bloc légende sous une rangée de KPI. lines = liste de str."""
    if not lines:
        return
    body = "<br/>".join(lines)
    st.markdown(f'<div class="kpi-legend">{body}</div>', unsafe_allow_html=True)


def empty_state(title, message, page_link_path=None, page_label="Aller à Import"):
    """État vide avec CTA optionnel."""
    st.markdown(
        f'<div class="empty-state"><h3>{title}</h3><p>{message}</p></div>',
        unsafe_allow_html=True,
    )
    if page_link_path:
        try:
            st.page_link(page_link_path, label=page_label, icon="📥")
        except Exception:
            st.info(f"Ouvre la page **{page_label}** dans le menu.")


def fmt_eur(x, signed=False):
    if x is None:
        return "—"
    if signed:
        return f"{x:+,.2f} €".replace(",", " ")
    return f"{x:,.2f} €".replace(",", " ")
