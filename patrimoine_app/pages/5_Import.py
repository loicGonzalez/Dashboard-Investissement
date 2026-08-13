"""Import PDF / CSV / saisie manuelle / cours manuels."""
from datetime import datetime

import streamlit as st

from core.state import init_session, rebuild_portfolios
from core.style import inject_css
from core.parsers import (
    extract_transaction_from_pdf,
    extract_transaction_from_traderepublic,
    parse_csv_transactions,
)

st.set_page_config(page_title="Import — Patrimoine", page_icon="📥", layout="wide")
init_session()
inject_css()

st.markdown("## 📥 Import")
st.caption("Charge tes documents une fois — les autres pages lisent la session.")

c1, c2 = st.columns(2)

with c1:
    st.markdown("### PEA")
    pea_pdfs = st.file_uploader(
        "Avis CIC (PDF)", type=["pdf"], accept_multiple_files=True, key="imp_pea_pdf"
    )
    pea_csv = st.file_uploader("CSV opérations PEA", type=["csv"], key="imp_pea_csv")

    st.markdown("### CTO")
    cto_pdfs = st.file_uploader(
        "Trade Republic / CIC (PDF)", type=["pdf"], accept_multiple_files=True, key="imp_cto_pdf"
    )

with c2:
    st.markdown("### PER")
    per_csv = st.file_uploader("CSV opérations PER", type=["csv"], key="imp_per_csv")

    with st.expander("➕ Opération PER manuelle"):
        with st.form("manual_per", clear_on_submit=True):
            a, b = st.columns(2)
            with a:
                m_date = st.date_input("Date", value=datetime.now())
                m_type = st.selectbox("Type", ["ACHAT", "VENTE"])
                m_qty = st.number_input("Quantité", min_value=0.0, step=0.001, format="%.4f", value=1.0)
                m_isin = st.text_input("ISIN")
            with b:
                m_nom = st.text_input("Nom")
                m_cours = st.number_input("Cours (€)", min_value=0.0, format="%.4f")
                m_frais = st.number_input("Frais (€)", min_value=0.0, format="%.2f")
            if st.form_submit_button("Ajouter"):
                if m_isin and m_cours > 0 and m_qty > 0:
                    q, c, f = float(m_qty), float(m_cours), float(m_frais)
                    st.session_state["per_manual"].append({
                        "date": datetime.combine(m_date, datetime.min.time()),
                        "type": m_type,
                        "quantite": q,
                        "valeur": m_nom.strip() or m_isin.strip().upper(),
                        "isin": m_isin.strip().upper(),
                        "cours": c,
                        "solde": None,
                        "brut": round(q * c, 2),
                        "frais": f,
                        "montant": round(q * c + f, 2),
                        "source": "Manuel PER",
                        "kind": "uc",
                    })
                    st.success(f"{m_type} ajouté")
                else:
                    st.error("ISIN, quantité et cours obligatoires")

    if st.session_state["per_manual"]:
        st.caption(f"{len(st.session_state['per_manual'])} op. manuelle(s)")
        if st.button("Vider PER manuelles"):
            st.session_state["per_manual"] = []
            st.rerun()

    st.markdown("### Cours manuels OPCVM")
    with st.expander("Forcer un cours"):
        fi = st.text_input("ISIN", key="force_isin")
        fc = st.number_input("Cours (€)", min_value=0.0, format="%.4f", key="force_cours")
        if st.button("Enregistrer") and fi and fc > 0:
            st.session_state["manual_prices"][fi.strip().upper()] = float(fc)
            st.success(f"{fi} → {fc:.4f} €")
    if st.session_state["manual_prices"]:
        for isin, px in st.session_state["manual_prices"].items():
            st.text(f"{isin} : {px:.4f} €")
        if st.button("Vider cours manuels"):
            st.session_state["manual_prices"] = {}
            st.rerun()

st.markdown("---")
if st.button("🔄 Charger / rafraîchir les données", type="primary", use_container_width=True):
    pea_txs, cto_txs = [], []
    n_ok = n_fail = 0

    if pea_pdfs:
        for f in pea_pdfs:
            tx = extract_transaction_from_pdf(f)
            if tx is None:
                tx = extract_transaction_from_traderepublic(f)
            if tx:
                tx.setdefault("kind", "uc")
                pea_txs.append(tx)
                n_ok += 1
            else:
                n_fail += 1
        st.session_state["pea_files_data"] = pea_txs
        st.session_state["pea_files_names"] = [f.name for f in pea_pdfs]

    if pea_csv is not None:
        rows = parse_csv_transactions(pea_csv)
        st.session_state["pea_csv_data"] = rows
        st.session_state["pea_csv_name"] = pea_csv.name
        n_ok += len(rows)

    if cto_pdfs:
        for f in cto_pdfs:
            tx = extract_transaction_from_traderepublic(f)
            if tx is None:
                tx = extract_transaction_from_pdf(f)
            if tx:
                tx.setdefault("kind", "uc")
                cto_txs.append(tx)
                n_ok += 1
            else:
                n_fail += 1
        st.session_state["cto_files_data"] = cto_txs
        st.session_state["cto_files_names"] = [f.name for f in cto_pdfs]

    if per_csv is not None:
        rows = parse_csv_transactions(per_csv)
        st.session_state["per_csv_data"] = rows
        st.session_state["per_csv_name"] = per_csv.name
        n_ok += len(rows)

    st.session_state["histories"] = {}  # invalide cache évolution
    rebuild_portfolios()
    st.success(f"Import terminé — {n_ok} opération(s) lue(s)" + (f", {n_fail} PDF ignoré(s)" if n_fail else ""))
    st.rerun()

st.markdown("### État de la session")
s1, s2, s3 = st.columns(3)
s1.metric("PEA ops", len(st.session_state.get("pea_files_data", [])) + len(st.session_state.get("pea_csv_data", [])))
s2.metric("PER ops", len(st.session_state.get("per_csv_data", [])) + len(st.session_state.get("per_manual", [])))
s3.metric("CTO ops", len(st.session_state.get("cto_files_data", [])))

with st.expander("Modèle CSV"):
    st.code(
        "date,type,quantite,isin,nom,cours,frais,montant\n"
        "01/11/2025,ACHAT,0.100484,,CM-AM ACTIONS MONDE RC,345.33,0,34.70\n"
        "01/11/2025,VERSEMENT,,,Euro Retraite,,,40.00\n"
        "15/07/2026,VENTE,0.100484,,CM-AM ACTIONS MONDE RC,360.00,0,36.17\n"
        "11/06/2026,BONUS,0.141236,FR0000120073,Air Liquide,0,0,0",
        language=None,
    )
    st.caption("Types UC : ACHAT / VENTE / FRAIS / BONUS · Fonds euros : VERSEMENT / RETRAIT / INTERETS / FRAIS_FE")
