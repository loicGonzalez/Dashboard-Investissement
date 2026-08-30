"""Épargne de sécurité — Livret A, LEP, LDDS."""
import streamlit as st
import pandas as pd
from datetime import datetime

from core.state import init_session, rebuild_portfolios, persist_enveloppe
from core.style import inject_css, kpi_card, fmt_eur
from core.nav import render_sidebar
from core.config import LIVRET_LABELS, LIVRET_PLAFONDS
from core.portfolio import process_livrets

st.set_page_config(page_title="Livrets · Patrimoine", page_icon="◆", layout="wide")
init_session()
inject_css()
render_sidebar(active="livrets")

if st.session_state.get("livrets_data") is not None:
    rebuild_portfolios()

liv = st.session_state.get("livrets") or {"txs": [], "by_code": process_livrets([])}
by = liv.get("by_code") or process_livrets(liv.get("txs") or [])
total_valo = sum(v["valo"] for v in by.values())
total_apports = sum(v["apports"] for v in by.values())
total_int = sum(v["interets"] for v in by.values())

_hero = (
    '<div class="hero">'
    '<div class="hero-label"><span class="pill" style="background:#2e1065;color:#c4b5fd;">ÉPARGNE SÉCURITÉ</span></div>'
    '<div class="hero-value">' + fmt_eur(total_valo) + '</div>'
    '<div class="hero-meta">'
    + "Apports " + fmt_eur(total_apports)
    + " | Intérêts " + fmt_eur(total_int)
    + "</div></div>"
)
st.markdown(_hero, unsafe_allow_html=True)

c1, c2, c3 = st.columns(3)
for col, code in zip((c1, c2, c3), ("LA", "LEP", "LDDS")):
    v = by.get(code) or {}
    plafond = v.get("plafond") or LIVRET_PLAFONDS.get(code, 0)
    pct = v.get("pct_plafond")
    sub = f"{pct:.0f} % du plafond" if pct is not None else ""
    with col:
        st.markdown(
            '<div class="env-card">'
            f'<div class="env-card-title">{LIVRET_LABELS.get(code, code)}</div>'
            f'<div class="env-card-valo">{fmt_eur(v.get("valo", 0))}</div>'
            f'<div class="env-card-sub">Plafond {fmt_eur(plafond)} · {sub}</div>'
            f'<div class="env-card-sub">Intérêts {fmt_eur(v.get("interets", 0))}</div>'
            "</div>",
            unsafe_allow_html=True,
        )

st.markdown("#### Ajouter un mouvement")
with st.form("livret_mvt", clear_on_submit=True):
    a, b, c, d = st.columns(4)
    with a:
        m_date = st.date_input("Date", value=datetime.now())
    with b:
        m_liv = st.selectbox("Livret", ["LA", "LEP", "LDDS"], format_func=lambda x: LIVRET_LABELS.get(x, x))
    with c:
        m_type = st.selectbox("Type", ["SOLDE", "VERSEMENT", "RETRAIT", "INTERETS"])
    with d:
        m_montant = st.number_input("Montant (€)", min_value=0.0, format="%.2f", value=0.0)
    if st.form_submit_button("Enregistrer"):
        if m_montant > 0:
            op = {
                "date": datetime.combine(m_date, datetime.min.time()),
                "type": m_type,
                "quantite": None,
                "valeur": LIVRET_LABELS.get(m_liv, m_liv),
                "isin": m_liv,
                "cours": None,
                "solde": m_montant if m_type == "SOLDE" else None,
                "brut": None,
                "frais": 0.0,
                "montant": float(m_montant),
                "source": "Manuel livrets",
                "kind": "livret",
            }
            persist_enveloppe([op], "LIVRETS", "merge")
            st.session_state.setdefault("livrets_data", []).append(op)
            rebuild_portfolios()
            st.success("Mouvement enregistré")
            st.rerun()
        else:
            st.error("Montant > 0 requis")

st.markdown("#### Historique")
ops = liv.get("txs") or []
if ops:
    rows = []
    for o in sorted(ops, key=lambda x: x.get("date") or datetime.min, reverse=True):
        rows.append({
            "Date": o["date"].strftime("%d/%m/%Y") if hasattr(o.get("date"), "strftime") else str(o.get("date")),
            "Livret": LIVRET_LABELS.get(str(o.get("isin")), o.get("isin")),
            "Type": o.get("type"),
            "Montant (€)": o.get("montant"),
            "Source": o.get("source"),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
else:
    st.info("Aucun mouvement. Saisis un **SOLDE** actuel pour chaque livret, ou importe un CSV depuis Import.")
