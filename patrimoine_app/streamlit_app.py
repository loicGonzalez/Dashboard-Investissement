#!/usr/bin/env python3
"""Patrimoine — page d'accueil = Vue globale."""
import streamlit as st

st.set_page_config(
    page_title="Patrimoine — Vue globale",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

from core.state import init_session, rebuild_portfolios
from core.style import inject_css

init_session()
inject_css()

# Recalcule si des données sont déjà en session
if (
    st.session_state.get("pea_files_data")
    or st.session_state.get("pea_csv_data")
    or st.session_state.get("cto_files_data")
    or st.session_state.get("per_csv_data")
    or st.session_state.get("per_manual")
):
    rebuild_portfolios()

from core.nav import render_sidebar
render_sidebar(active="home")

# ——— Contenu Vue globale ———
"""Vue globale — style finance dark + données réelles."""
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.state import init_session, rebuild_portfolios, enrich, metrics_for, get_history
from core.style import inject_css, kpi_card, fmt_eur, PLOTLY_LAYOUT
from core.config import ENV_COLORS
from core.ui_detail import render_geo_section
from core.portfolio import process_transactions, performance_periods


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

# Historique léger pour scoreboard (1j / 1s)
all_txs_sb = pea["txs"] + per["txs"] + cto["txs"]
_, all_by_sb = process_transactions(all_txs_sb)
hist_sb = get_history(f"global_sb_{len(all_txs_sb)}", all_by_sb, all_txs_sb)
pv_sb = hist_sb.get("portfolio_value")
inv_sb = hist_sb.get("invested_cumul")
perf_sb = performance_periods(pv_sb, inv_sb) if pv_sb is not None else []
perf_map = {r["label"]: r for r in perf_sb}

def _chip_html(label, row):
    if not row or not row.get("available"):
        return f'<span class="chip-score chip-neutral">{label} · n/d</span>'
    d = row["delta_eur"]
    p = row["delta_pct"]
    cls = "chip-pos" if d >= 0 else "chip-neg"
    sign = "+" if d >= 0 else ""
    txt = f"{label} · {sign}{d:,.0f} € ({p:+.2f}%)".replace(",", " ")
    return f'<span class="chip-score {cls}">{txt}</span>'

chip_1j = _chip_html("1j", perf_map.get("1 jour"))
chip_1s = _chip_html("1s", perf_map.get("1 semaine"))

# Dernier import
from core.import_log import load_journal, missing_price_alerts_from_open_df
journal = load_journal()
if journal:
    last = journal[0]
    last_import_txt = f"{last.get('ts', '?')} · {last.get('enveloppe', '?')} · {last.get('source', '?')}"
    last_fail = int(last.get("failed") or 0)
else:
    last_import_txt = "aucun import enregistré"
    last_fail = 0

# Santé : cours manquants
_alerts_sb = []
for _info in (pea_i, per_i, cto_i):
    _alerts_sb.extend(missing_price_alerts_from_open_df(_info.get("open")))
n_miss = len(_alerts_sb)

# Cibles présentes ?
from core.db import get_allocation_targets
_tgt_ok = all(
    abs(sum(get_allocation_targets(e).values()) - 100) < 5
    for e in ("PEA", "PER", "CTO")
)

# Header + chips
h1, h2 = st.columns([3, 1])
with h1:
    st.markdown("## ◆ Patrimoine")
    st.markdown(chip_1j + chip_1s, unsafe_allow_html=True)
    st.caption(f"Vue globale · {datetime.now().strftime('%d/%m/%Y %H:%M')}")
with h2:
    st.markdown(
        '<div style="text-align:right;padding-top:0.6rem;">'
        '<span class="pill pill-pea">PEA</span> '
        '<span class="pill pill-per">PER</span> '
        '<span class="pill pill-cto">CTO</span></div>',
        unsafe_allow_html=True,
    )

# Bandeau santé
cls_cours = "health-ok" if n_miss == 0 else "health-bad"
cls_imp = "health-ok" if last_fail == 0 else "health-warn"
cls_tgt = "health-ok" if _tgt_ok else "health-warn"
_health = (
    '<div class="health-bar">'
    f'<span class="{cls_cours}">{"✓" if n_miss == 0 else "⚠"} {n_miss} cours manquant{"s" if n_miss != 1 else ""}</span>'
    f'<span class="{cls_imp}">{"✓" if last_fail == 0 else "⚠"} dernier import : {last_fail} échec{"s" if last_fail != 1 else ""} parse</span>'
    f'<span class="{cls_tgt}">{"✓" if _tgt_ok else "⚠"} cibles allocation {"OK" if _tgt_ok else "à revoir (somme ≠ 100 %)"}</span>'
    f'<span style="color:#6b7280;margin-left:auto;">Dernier import : {last_import_txt}</span>'
    '</div>'
)
st.markdown(_health, unsafe_allow_html=True)

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

# ——— Cartes enveloppes PEA / PER / CTO ———
from core.geography import allocation_gap, allocate_geo
from core.db import get_allocation_targets

def _env_card_data(name, m, open_df, fe_valo=0.0):
    valo = (m.get("valo_titres") or 0) + (fe_valo or 0)
    # PV latente titres
    inv = m.get("investi_ouvert") or 0
    pv_lat = (m.get("valo_titres") or 0) - inv
    pct_lat = (100 * pv_lat / inv) if inv else 0.0
    weight = (100 * valo / tot_patrimoine) if tot_patrimoine else 0.0
    # alertes cours
    n_miss = len(missing_price_alerts_from_open_df(open_df))
    # écart allocation fort (> 5 pts sur une zone)
    gap_strong = False
    try:
        positions = open_df.to_dict("records") if open_df is not None and not open_df.empty else []
        geo = allocate_geo(positions, fe_valo=fe_valo)
        gap_df = allocation_gap(geo, get_allocation_targets(name))
        if gap_df is not None and not gap_df.empty and "Écart (pts)" in gap_df.columns:
            for v in gap_df["Écart (pts)"].dropna():
                if abs(float(v)) >= 5:
                    gap_strong = True
                    break
    except Exception:
        pass
    if n_miss > 0:
        badge = "bad"
        badge_title = f"{n_miss} cours manquant(s)"
    elif gap_strong:
        badge = "warn"
        badge_title = "Écart d'allocation ≥ 5 pts"
    else:
        badge = ""
        badge_title = "OK"
    return {
        "name": name,
        "valo": valo,
        "pv_lat": pv_lat,
        "pct_lat": pct_lat,
        "weight": weight,
        "badge": badge,
        "badge_title": badge_title,
        "n_miss": n_miss,
        "cash": m.get("flow", {}).get("cash", 0) or 0,
    }

cards = [
    _env_card_data("PEA", pea_m, pea_i.get("open")),
    _env_card_data("PER", per_m, per_i.get("open"), fe_valo=per_m.get("fe_valo", 0)),
    _env_card_data("CTO", cto_m, cto_i.get("open")),
]
page_map = {
    "PEA": "pages/2_PEA.py",
    "PER": "pages/3_PER.py",
    "CTO": "pages/4_CTO.py",
}
color_map = {"PEA": "#60a5fa", "PER": "#a78bfa", "CTO": "#34d399"}

# ——— Objectif patrimoine ———
from core.db import get_patrimoine_goal, save_patrimoine_goal, init_db as _init_goal_db
_init_goal_db()
_goal = get_patrimoine_goal()
with st.expander("🎯 Objectif patrimoine", expanded=bool(_goal.get("target_eur"))):
    g1, g2, g3 = st.columns([1.2, 1, 1])
    with g1:
        _tgt = st.number_input(
            "Objectif (€)",
            min_value=0.0,
            value=float(_goal.get("target_eur") or 0),
            step=1000.0,
            key="goal_target",
        )
    with g2:
        _mensuel = st.number_input(
            "Apport mensuel estimé (€)",
            min_value=0.0,
            value=float(_goal.get("monthly_apport_eur") or 0),
            step=50.0,
            key="goal_monthly",
        )
    with g3:
        st.write("")
        st.write("")
        if st.button("Enregistrer l'objectif", key="save_goal"):
            save_patrimoine_goal(_tgt, _mensuel)
            st.success("Objectif enregistré")
            st.rerun()

    _disp_tgt = float(_goal.get("target_eur") or 0)
    if _disp_tgt > 0:
        _cur = float(tot_patrimoine)
        _pct = min(100.0, 100.0 * _cur / _disp_tgt) if _disp_tgt else 0.0
        _rest = max(0.0, _disp_tgt - _cur)
        _mens = float(_goal.get("monthly_apport_eur") or 0)
        if _mens > 0 and _rest > 0:
            _months = _rest / _mens
            _eta = "≈ {:.0f} mois au rythme de {:,.0f} €/mois".format(_months, _mens).replace(",", " ")
        elif _rest <= 0:
            _eta = "Objectif atteint"
        else:
            _eta = "Renseigne un apport mensuel pour estimer le délai"
        _html = (
            '<div class="goal-wrap">'
            '<div class="goal-label">Progression</div>'
            '<div class="goal-title">' + fmt_eur(_cur) + " / " + fmt_eur(_disp_tgt)
            + " · {:.1f}%</div>".format(_pct)
            + '<div class="goal-bar-bg"><div class="goal-bar-fg" style="width:{:.1f}%"></div></div>'.format(_pct)
            + '<div class="goal-meta">Reste ' + fmt_eur(_rest) + " · " + _eta + "</div>"
            + "</div>"
        )
        st.markdown(_html, unsafe_allow_html=True)

with st.expander("📦 Enveloppes", expanded=True):
    c_pea, c_per, c_cto = st.columns(3)
    for col, card in zip((c_pea, c_per, c_cto), cards):
        with col:
            badge_cls = f"env-card-badge {card['badge']}" if card["badge"] else "env-card-badge"
            pv_color = "#34d399" if card["pv_lat"] >= 0 else "#f87171"
            html = (
                f'<div class="env-card" title="{card["badge_title"]}">'
                f'<div class="{badge_cls}"></div>'
                f'<div class="env-card-title" style="color:{color_map[card["name"]]}">{card["name"]}</div>'
                f'<div class="env-card-valo">{fmt_eur(card["valo"])}</div>'
                f'<div class="env-card-sub">PV latente '
                f'<span style="color:{pv_color}">{fmt_eur(card["pv_lat"], signed=True)} '
                f'({card["pct_lat"]:+.1f}%)</span></div>'
                f'<span class="env-weight">{card["weight"]:.1f}% du patrimoine</span>'
                f'</div>'
            )
            st.markdown(html, unsafe_allow_html=True)
            try:
                st.page_link(page_map[card["name"]], label=f"Ouvrir {card['name']} →", icon="↗")
            except Exception:
                st.caption(f"Menu → {card['name']}")


# ——— Top / flop positions (PV latente) ———
with st.expander("📊 Top / flop positions", expanded=False):
    st.caption("Plus-value latente = valorisation − investi (positions ouvertes, toutes enveloppes).")
    _pos_rows = []
    for _env_name, _info, _m in (
        ("PEA", pea_i, pea_m),
        ("PER", per_i, per_m),
        ("CTO", cto_i, cto_m),
    ):
        _o = _info.get("open")
        if _o is None or getattr(_o, "empty", True):
            continue
        for _, r in _o.iterrows():
            try:
                inv = float(r.get("Investi (€)") or 0)
                valo = r.get("Valorisation (€)")
                if valo is None or (isinstance(valo, float) and pd.isna(valo)):
                    continue
                valo = float(valo)
                pv = valo - inv
                pct = (100 * pv / inv) if inv else 0.0
                _pos_rows.append({
                    "Enveloppe": _env_name,
                    "Nom": str(r.get("Nom") or r.get("ISIN") or "")[:40],
                    "ISIN": r.get("ISIN"),
                    "PV latente (€)": round(pv, 2),
                    "PV %": round(pct, 2),
                    "Valo (€)": round(valo, 2),
                    "Investi (€)": round(inv, 2),
                })
            except (TypeError, ValueError):
                continue
    if _pos_rows:
        _pos_df = pd.DataFrame(_pos_rows)
        _top = _pos_df.nlargest(3, "PV latente (€)")
        _flop = _pos_df.nsmallest(3, "PV latente (€)")
        c_top, c_flop = st.columns(2)
        with c_top:
            st.markdown("**Top 3** (meilleure PV latente)")
            st.dataframe(
                _top[["Enveloppe", "Nom", "PV latente (€)", "PV %", "Valo (€)"]],
                use_container_width=True,
                hide_index=True,
            )
        with c_flop:
            st.markdown("**Flop 3** (moins bonne PV latente)")
            st.dataframe(
                _flop[["Enveloppe", "Nom", "PV latente (€)", "PV %", "Valo (€)"]],
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.caption("Aucune position valorisée pour le classement.")

# ——— Activité récente ———
with st.expander("🕒 Activité récente", expanded=False):
    a1, a2 = st.columns(2)
    with a1:
        st.markdown("**Dernières opérations**")
        _ops = []
        for _env, _txs in (
            ("PEA", pea.get("txs") or []),
            ("PER", per.get("txs") or []),
            ("CTO", cto.get("txs") or []),
        ):
            for op in _txs:
                d = op.get("date") or op.get("date_str") or ""
                ds = str(d)[:10]
                if len(ds) == 10 and ds[2] == "/":
                    try:
                        dd, mm, yy = ds.split("/")
                        sort_key = f"{yy}-{mm}-{dd}"
                    except Exception:
                        sort_key = ds
                else:
                    sort_key = ds
                _ops.append({
                    "_sort": sort_key,
                    "Date": ds,
                    "Env.": _env,
                    "Type": str(op.get("type") or "").upper(),
                    "Nom": str(op.get("valeur") or op.get("nom") or op.get("isin") or "")[:28],
                    "Qté": op.get("quantite"),
                    "Montant (€)": op.get("montant"),
                    "Source": str(op.get("source") or "")[:20],
                })
        if _ops:
            _ops_df = pd.DataFrame(_ops).sort_values("_sort", ascending=False).head(10)
            st.dataframe(
                _ops_df.drop(columns=["_sort"]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("Aucune opération.")
    with a2:
        st.markdown("**Derniers imports**")
        _j = load_journal()
        if _j:
            _jrows = []
            for e in _j[:8]:
                _jrows.append({
                    "Date": e.get("ts"),
                    "Env.": e.get("enveloppe"),
                    "Source": e.get("source"),
                    "Insérées": e.get("inserted"),
                    "Doublons": e.get("duplicates"),
                    "Échecs": e.get("failed"),
                })
            st.dataframe(pd.DataFrame(_jrows), use_container_width=True, hide_index=True)
        else:
            st.caption("Aucun import dans le journal.")

# ——— Charts ———
with st.expander("📈 Évolution & répartition", expanded=True):
    left, right = st.columns([1.35, 1])
    all_txs = pea["txs"] + per["txs"] + cto["txs"]
    all_by = {}
    for src in (pea["by_isin"], per["by_isin"], cto["by_isin"]):
        for isin, v in src.items():
            if isin not in all_by:
                all_by[isin] = {"name": v["name"], "parts": 0.0, "investi": 0.0, "ops": []}
            all_by[isin]["ops"].extend(v["ops"])
            all_by[isin]["name"] = v["name"] or all_by[isin]["name"]
    _, all_by = process_transactions(all_txs)
    hist = get_history(f"global_{len(all_txs)}", all_by, all_txs)
    pv = hist["portfolio_value"]
    inv = hist["invested_cumul"]

    with left:
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
        if not pv.empty:
            st.markdown("**A · PV latente (aujourd'hui)**")
            st.caption("Valorisation actuelle − coût de revient des positions ouvertes (consolidé).")
            _inv_sum = _valo_sum = 0.0
            for _info in (pea_i, per_i, cto_i):
                _o = _info.get("open")
                if _o is not None and not _o.empty:
                    _inv_sum += float(_o["Investi (€)"].fillna(0).sum())
                    _valo_sum += float(_o["Valorisation (€)"].fillna(0).sum())
            _pv_lat = _valo_sum - _inv_sum
            _pct_lat = 100 * _pv_lat / _inv_sum if _inv_sum else 0.0
            _c1, _c2 = st.columns([1, 2])
            kpi_card(_c1, "PV latente", fmt_eur(_pv_lat, signed=True), delta=f"{_pct_lat:+.1f}%", positive=_pv_lat >= 0)
            with _c2:
                st.markdown(
                    f"<div style='padding:12px 8px;color:#9ca3af;font-size:0.9rem'>"
                    f"Valo <b style='color:#e5e7eb'>{fmt_eur(_valo_sum)}</b> − Investi "
                    f"<b style='color:#e5e7eb'>{fmt_eur(_inv_sum)}</b></div>",
                    unsafe_allow_html=True,
                )
            st.markdown("**B · Perf hors apports (par période)**")
            st.caption("(Δ valo − Δ investi) / valo début. Les versements ne comptent pas comme performance.")
            rows = performance_periods(pv, inv)
            pcs = st.columns(len(rows))
            for col, row in zip(pcs, rows):
                if not row["available"]:
                    kpi_card(col, row["label"], "—", sub="n/d")
                    continue
                kpi_card(
                    col,
                    row["label"],
                    fmt_eur(row["delta_eur"], signed=True),
                    delta=f'{row["delta_pct"]:+.2f}%',
                    positive=row["delta_eur"] >= 0,
                )

    with right:
        st.markdown("**Répartition par enveloppe**")
        env_labels = ["PEA", "PER", "CTO"]
        env_vals = [
            pea_m["valo_titres"],
            per_m["valo_titres"] + per_m["fe_valo"],
            cto_m["valo_titres"],
        ]
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

with st.expander("📋 Résumé KPI par enveloppe", expanded=False):
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

with st.expander("📑 Positions consolidées", expanded=False):
    frames = []
    for env_name, info in [("PEA", pea_i), ("PER", per_i), ("CTO", cto_i)]:
        o = info["open"]
        if o is not None and not o.empty:
            tf = o.copy()
            tf.insert(0, "Enveloppe", env_name)
            frames.append(tf)
    if frames:
        all_pos = pd.concat(frames, ignore_index=True)
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
        layout = {
            **PLOTLY_LAYOUT,
            "height": max(280, 28 * len(pos_sorted)),
            "xaxis": dict(showgrid=True, gridcolor="#1f2937"),
            "yaxis": dict(showgrid=False),
            "margin": dict(l=10, r=70, t=10, b=10),
        }
        fig_bar.update_layout(**layout)
        st.plotly_chart(fig_bar, use_container_width=True)
        st.dataframe(all_pos, use_container_width=True, hide_index=True)
    else:
        st.caption("Aucune position ouverte.")

# Alertes consolidées cours manquants
try:
    _all_alerts = []
    for _info in (pea_i, per_i, cto_i):
        _all_alerts.extend(missing_price_alerts_from_open_df(_info.get("open")))
    if _all_alerts:
        st.warning(
            f"⚠️ {len(_all_alerts)} position(s) sans cours de marché : "
            + ", ".join(str(a.get("ISIN")) for a in _all_alerts[:8])
            + " — corriger via Import → cours manuels."
        )
except Exception:
    pass

# Géo + réallocation
with st.expander("🌍 Allocation géographique & réallocation", expanded=True):
    st.markdown("### Répartition géographique (tous comptes)")
    all_open_frames = []
    for info in (pea_i, per_i, cto_i):
        o = info.get("open")
        if o is not None and not o.empty:
            all_open_frames.append(o)
    all_open = pd.concat(all_open_frames, ignore_index=True) if all_open_frames else pd.DataFrame()
    from core.db import average_allocation_targets, save_allocation_targets, get_allocation_targets
    from core.geography import allocate_geo, allocation_gap

    _weights = {
        "PEA": pea_m.get("valo_titres", 0) or 0,
        "PER": (per_m.get("valo_titres", 0) or 0) + (per_m.get("fe_valo", 0) or 0),
        "CTO": cto_m.get("valo_titres", 0) or 0,
    }
    _global_targets = average_allocation_targets(_weights)
    save_allocation_targets(_global_targets, "GLOBAL")

    st.markdown("### À réallouer")
    st.caption(
        "Écarts vs cibles globales (moyenne pondérée PEA/PER/CTO). "
        "Montants indicatifs sur la poche investie hors fonds euros."
    )
    try:
        _positions = all_open.to_dict("records") if all_open is not None and not all_open.empty else []
        _geo = allocate_geo(_positions, fe_valo=per_m.get("fe_valo", 0) or 0)
        _gap = allocation_gap(_geo, _global_targets)
        if _gap is not None and not _gap.empty and "Écart (€)" in _gap.columns:
            g = _gap[_gap["Cible (%)"].notna()].copy()
            g["Écart abs"] = g["Écart (€)"].abs()
            g = g[g["Écart abs"] >= 1]
            over = g[g["Écart (€)"] > 0].sort_values("Écart (€)", ascending=False).head(3)
            under = g[g["Écart (€)"] < 0].sort_values("Écart (€)", ascending=True).head(3)
            c_over, c_under = st.columns(2)
            with c_over:
                st.markdown("**Surpondéré** (réduire / vendre vers cible)")
                if over.empty:
                    st.caption("Aucun écart significatif")
                else:
                    for _, row in over.iterrows():
                        st.markdown(
                            f"- **{row['Zone']}** : +{row['Écart (pts)']:.1f} pts · "
                            f"**{row['Écart (€)']:,.0f} €** en trop".replace(",", " ")
                        )
            with c_under:
                st.markdown("**Sous-pondéré** (renforcer / acheter vers cible)")
                if under.empty:
                    st.caption("Aucun écart significatif")
                else:
                    for _, row in under.iterrows():
                        st.markdown(
                            f"- **{row['Zone']}** : {row['Écart (pts)']:.1f} pts · "
                            f"**{abs(row['Écart (€)']):,.0f} €** à ajouter".replace(",", " ")
                        )
            if not over.empty and not under.empty:
                top_o = over.iloc[0]
                top_u = under.iloc[0]
                move = min(abs(float(top_o["Écart (€)"])), abs(float(top_u["Écart (€)"])))
                if move >= 1:
                    st.info(
                        f"Piste simple : déplacer environ **{move:,.0f} €** de "
                        f"**{top_o['Zone']}** → **{top_u['Zone']}** "
                        f"(ordre de grandeur, hors fiscalité / frais).".replace(",", " ")
                    )
            elif g.empty:
                st.success("Allocation alignée sur les cibles (±1 €).")
        else:
            st.caption("Pas assez de données pour calculer les écarts.")
    except Exception as e:
        st.caption(f"Écarts d'allocation indisponibles : {e}")

    render_geo_section(
        all_open,
        fe_valo=per_m.get("fe_valo", 0),
        title="Exposition par zone (cible = moyenne pondérée PEA/PER/CTO)",
        enveloppe="GLOBAL",
        targets=_global_targets,
    )
