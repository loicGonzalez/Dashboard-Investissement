"""CSS et composants visuels partagés."""
import streamlit as st

GLOBAL_CSS = """
<style>
    .stApp {
        background: linear-gradient(180deg, #0b0f14 0%, #111827 40%, #0b0f14 100%);
        color: #e5e7eb;
    }
    header[data-testid="stHeader"] {
        background: rgba(11, 15, 20, 0.85);
    }
    h1, h2, h3 { color: #f9fafb !important; letter-spacing: -0.02em; }
    .kpi-card {
        background: #151b24;
        border: 1px solid #243041;
        border-radius: 16px;
        padding: 1.25rem 1.4rem;
        height: 100%;
    }
    .kpi-label {
        font-size: 0.78rem;
        color: #9ca3af;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 0.35rem;
    }
    .kpi-value {
        font-size: 1.75rem;
        font-weight: 650;
        color: #f9fafb;
        line-height: 1.15;
    }
    .kpi-delta-pos { color: #34d399; font-size: 0.9rem; margin-top: 0.35rem; }
    .kpi-delta-neg { color: #f87171; font-size: 0.9rem; margin-top: 0.35rem; }
    .kpi-sub { color: #6b7280; font-size: 0.8rem; margin-top: 0.2rem; }
    .section-card {
        background: #151b24;
        border: 1px solid #243041;
        border-radius: 16px;
        padding: 1.1rem 1.2rem 0.4rem 1.2rem;
        margin-bottom: 0.8rem;
    }
    .chip-score {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.35rem 0.75rem;
        border-radius: 999px;
        font-size: 0.8rem;
        font-weight: 600;
        border: 1px solid #243041;
        background: #151b24;
        margin-right: 0.4rem;
        margin-top: 0.25rem;
    }
    .chip-pos { color: #34d399; border-color: #065f46; background: #064e3b33; }
    .chip-neg { color: #f87171; border-color: #7f1d1d; background: #7f1d1d33; }
    .chip-neutral { color: #9ca3af; }
    .health-bar {
        background: #151b24;
        border: 1px solid #243041;
        border-radius: 12px;
        padding: 0.65rem 1rem;
        margin: 0.6rem 0 0.9rem 0;
        font-size: 0.85rem;
        color: #d1d5db;
        display: flex;
        flex-wrap: wrap;
        gap: 0.75rem 1.25rem;
        align-items: center;
    }
    .env-card {
        background: #151b24;
        border: 1px solid #243041;
        border-radius: 16px;
        padding: 1rem 1.15rem 0.85rem 1.15rem;
        height: 100%;
        position: relative;
    }
    .env-card-title {
        font-size: 0.85rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        margin-bottom: 0.45rem;
    }
    .env-card-valo {
        font-size: 1.45rem;
        font-weight: 650;
        color: #f9fafb;
        line-height: 1.2;
    }
    .env-card-sub { color: #9ca3af; font-size: 0.82rem; margin-top: 0.35rem; }
    .env-card-badge {
        position: absolute;
        top: 0.75rem;
        right: 0.85rem;
        width: 0.55rem;
        height: 0.55rem;
        border-radius: 999px;
        background: #34d399;
    }
    .env-card-badge.warn { background: #fbbf24; }
    .env-card-badge.bad { background: #f87171; }
    .env-weight {
        display: inline-block;
        margin-top: 0.5rem;
        padding: 0.15rem 0.5rem;
        border-radius: 999px;
        background: #1f2937;
        color: #d1d5db;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .health-ok { color: #34d399; }
    .health-warn { color: #fbbf24; }
    .health-bad { color: #f87171; }
    .pill {
        display: inline-block;
        padding: 0.2rem 0.65rem;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.04em;
    }
    .pill-pea { background: #1e3a5f; color: #93c5fd; }
    .pill-per { background: #3b2f1e; color: #fcd34d; }
    .pill-cto { background: #1f3b2e; color: #6ee7b7; }
    section[data-testid="stSidebar"] {
        background: #0d1219;
        border-right: 1px solid #1f2937;
    }
    hr { border-color: #1f2937 !important; }
</style>
"""

PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#9ca3af", size=12),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
)


def inject_css():
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def kpi_card(col, label, value, delta=None, sub=None, positive=True):
    """Carte KPI HTML (sans indentation Markdown qui transforme en bloc code)."""
    delta_html = ""
    if delta is not None:
        cls = "kpi-delta-pos" if positive else "kpi-delta-neg"
        delta_html = f'<div class="{cls}">{delta}</div>'
    sub_html = f'<div class="kpi-sub">{sub}</div>' if sub else ""
    # Important : HTML collé à gauche pour éviter le rendu "code" Markdown
    html = (
        f'<div class="kpi-card">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>'
        f'{delta_html}'
        f'{sub_html}'
        f'</div>'
    )
    col.markdown(html, unsafe_allow_html=True)


def fmt_eur(x, signed=False):
    if x is None:
        return "—"
    if signed:
        return f"{x:+,.2f} €".replace(",", " ")
    return f"{x:,.2f} €".replace(",", " ")
