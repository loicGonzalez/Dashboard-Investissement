"""Vue globale — style finance dark + données réelles."""
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.state import init_session, rebuild_portfolios, enrich, metrics_for, get_history
from core.style import inject_css, kpi_card, fmt_eur, PLOTLY_LAYOUT
from core.config import ENV_COLORS
from core.portfolio import process_transactions

st.set_page_config(page_title="Vue globale — Patrimoine", page_icon="◆", layout="wide")
init_session()
inject_css()

# Assure portefeuilles à jour
has_data = any(
    st.session_state.get(k)
    for k in ("pea_files_data", "pea_csv_data", "cto_files_data", "per_csv_data", "per_manual")
)
if has_data and "pea" not in st.session_state:
    rebuild_portfolios()

pea = st.session_state.get("pea") or {"txs": [], "by_isin": {}, "df": pd.DataFrame()}
per = st.session_state.get("per") or {"txs": [], "by_isin": {}, "df": pd.DataFrame(), "fe_by_id": {}}
cto = st.session_state.get("cto") or {"txs": [], "by_isin": {}, "df": pd.DataFrame()}

if not has_data:
    st.markdown("## ◆ Patrimoine")
    st.info("Aucune donnée chargée. Va dans **Import** pour ajouter PDF / CSV.")
    st.stop()

# Enrichir chaque enveloppe
pea_i = enrich(pea["by_isin"])
per_i = enrich(per["by_isin"])
cto_i = enrich(cto["by_isin"])

pea_m = metrics_for(pea["txs"], pea_i["open"])
per_m = metrics_for(per["txs"], per_i["open"], per.get("fe_by_id"))
cto_m = metrics_for(cto["txs"], cto_i["open"])

# Totaux globaux
tot_apports = pea_m["apports"] + per_m["apports"] + cto_m["apports"]
tot_valo = pea_m["valo_titres"] + per_m["valo_titres"] + cto_m["valo_titres"]
tot_cash = pea_m["flow"]["cash"] + per_m["flow"]["cash"] + cto_m["flow"]["cash"]
tot_fe = per_m["fe_valo"]
tot_patrimoine = tot_valo + tot_cash + tot_fe
tot_pv = tot_patrimoine - tot_apports
tot_pct = 100 * tot_pv / tot_apports if tot_apports else 0.0
tot_frais = pea_m.get("frais_achat", 0) + per_m.get("frais_achat", 0) + cto_m.get("frais_achat", 0)

# Header
h1, h2 = st.columns([3, 1])
with h1:
    st.markdown("## ◆ Patrimoine")
    st.caption(f"Vue globale · {datetime.now().strftime('%d/%m/%Y %H:%M')}")
with h2:
    st.markdown(
        '<div style="text-align:right;padding-top:0.6rem;">'
        '<span class="pill pill-pea">PEA</span> '
        '<span class="pill pill-per">PER</span> '
        '<span class="pill pill-cto">CTO</span></div>',
        unsafe_allow_html=True,
    )

k1, k2, k3, k4, k5 = st.columns(5)
kpi_card(k1, "Apports estimés", fmt_eur(tot_apports))
kpi_card(
    k2, "Patrimoine",
    fmt_eur(tot_patrimoine),
    delta=f"{tot_pv:+,.0f} € ({tot_pct:+.1f}%)".replace(",", " "),
    positive=tot_pv >= 0,
)
kpi_card(k3, "Plus-value", fmt_eur(tot_pv, signed=True), sub=f"{tot_pct:+.1f}%", positive=tot_pv >= 0)
n_pos = sum(
    len(x["open"]) for x in (pea_i, per_i, cto_i) if x["open"] is not None and not x["open"].empty
)
kpi_card(k4, "Positions ouvertes", str(n_pos), sub=f"cash {fmt_eur(tot_cash)}")
kpi_card(
    k5, "Frais d'achat",
    fmt_eur(tot_frais),
    sub=f"{(100 * tot_frais / tot_apports) if tot_apports else 0:.2f}% des apports",
    positive=False,
)

st.markdown("")

# Charts
left, right = st.columns([1.35, 1])

# Historique cumulé
all_txs = pea["txs"] + per["txs"] + cto["txs"]
all_by = {}
for src in (pea["by_isin"], per["by_isin"], cto["by_isin"]):
    for isin, v in src.items():
        if isin not in all_by:
            all_by[isin] = {"name": v["name"], "parts": 0.0, "investi": 0.0, "ops": []}
        all_by[isin]["ops"].extend(v["ops"])
        all_by[isin]["name"] = v["name"] or all_by[isin]["name"]
# recalcul parts/investi agrégé
_, all_by = process_transactions(all_txs)
hist = get_history(f"global_{len(all_txs)}", all_by, all_txs)
pv = hist["portfolio_value"]
inv = hist["invested_cumul"]

with left:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown("**Évolution du patrimoine**")
    fig = go.Figure()
    if not pv.empty:
        fig.add_trace(go.Scatter(
            x=pv.index, y=pv, name="Valorisation",
            line=dict(color="#60a5fa", width=2.4),
            fill="tozeroy", fillcolor="rgba(96,165,250,0.08)",
            hovertemplate="%{x|%d/%m/%Y}<br>%{y:,.0f} €<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=inv.index, y=inv, name="Investi",
            line=dict(color="#a78bfa", width=2, dash="dot"),
            hovertemplate="%{x|%d/%m/%Y}<br>%{y:,.0f} €<extra></extra>",
        ))
    fig.update_layout(
        **PLOTLY_LAYOUT, height=340, hovermode="x unified",
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(showgrid=True, gridcolor="#1f2937", zeroline=False, ticksuffix=" €"),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

with right:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown("**Répartition par enveloppe**")
    env_labels = ["PEA", "PER", "CTO"]
    env_vals = [
        pea_m["valo_titres"],
        per_m["valo_titres"] + per_m["fe_valo"],
        cto_m["valo_titres"],
    ]
    # éviter pie vide
    if sum(env_vals) > 0:
        fig_pie = go.Figure(data=[go.Pie(
            labels=env_labels, values=env_vals, hole=0.62,
            marker=dict(colors=[ENV_COLORS["PEA"], ENV_COLORS["PER"], ENV_COLORS["CTO"]]),
            textinfo="label+percent", textfont=dict(size=12, color="#e5e7eb"),
            hovertemplate="%{label}<br>%{value:,.0f} €<extra></extra>",
        )])
        fig_pie.update_layout(**PLOTLY_LAYOUT, height=340, showlegend=False)
        total_txt = f"{sum(env_vals):,.0f} €".replace(",", " ")
        fig_pie.add_annotation(
            text=f"<b>{total_txt}</b><br><span style='font-size:11px;color:#9ca3af'>titres+FE</span>",
            x=0.5, y=0.5, showarrow=False, font=dict(size=15, color="#f9fafb"),
        )
        st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.caption("Pas de valorisation à afficher.")
    st.markdown("</div>", unsafe_allow_html=True)

# Cartes enveloppes
st.markdown("### Enveloppes")
e1, e2, e3 = st.columns(3)
for col, name, mtr, pill in [
    (e1, "PEA", pea_m, "pill-pea"),
    (e2, "PER", per_m, "pill-per"),
    (e3, "CTO", cto_m, "pill-cto"),
]:
    valo_env = mtr["valo_titres"] + mtr.get("fe_valo", 0)
    delta_cls = "kpi-delta-pos" if mtr["pv"] >= 0 else "kpi-delta-neg"
    col.markdown(
        f'<div class="kpi-card">'
        f'<span class="pill {pill}">{name}</span>'
        f'<div style="margin-top:0.8rem;" class="kpi-value">{fmt_eur(valo_env)}</div>'
        f'<div class="{delta_cls}">{fmt_eur(mtr["pv"], signed=True)} ({mtr["pct"]:+.1f}%)</div>'
        f'<div class="kpi-sub">apports {fmt_eur(mtr["apports"])}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

# Tableau positions consolidé
st.markdown("### Positions")
frames = []
for env_name, info in [("PEA", pea_i), ("PER", per_i), ("CTO", cto_i)]:
    o = info["open"]
    if o is not None and not o.empty:
        t = o.copy()
        t.insert(0, "Enveloppe", env_name)
        frames.append(t)
if frames:
    all_pos = pd.concat(frames, ignore_index=True)
    # barres
    pos_sorted = all_pos.sort_values("Valorisation (€)", ascending=True)
    colors = [ENV_COLORS.get(e, "#60a5fa") for e in pos_sorted["Enveloppe"]]
    fig_bar = go.Figure(go.Bar(
        x=pos_sorted["Valorisation (€)"],
        y=pos_sorted["Nom"].astype(str).str[:28],
        orientation="h",
        marker=dict(color=colors),
        text=[f"{v:,.0f} €".replace(",", " ") if pd.notna(v) else "—" for v in pos_sorted["Valorisation (€)"]],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>%{x:,.0f} €<extra></extra>",
    ))
    layout = {**PLOTLY_LAYOUT, "height": max(280, 28 * len(pos_sorted)),
              "xaxis": dict(showgrid=True, gridcolor="#1f2937"),
              "yaxis": dict(showgrid=False),
              "margin": dict(l=10, r=70, t=10, b=10)}
    fig_bar.update_layout(**layout)
    st.plotly_chart(fig_bar, use_container_width=True)
    st.dataframe(all_pos, use_container_width=True, hide_index=True)
else:
    st.caption("Aucune position ouverte.")
