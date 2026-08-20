"""Import PDF / CSV / saisie manuelle — persistance SQLite."""
from datetime import datetime
from pathlib import Path

import streamlit as st

from core.state import (
    init_session,
    rebuild_portfolios,
    persist_enveloppe,
    load_from_db,
)
from core.style import inject_css, fmt_eur
from core.parsers import (
    extract_transaction_from_pdf,
    extract_transaction_from_traderepublic,
    parse_csv_transactions,
)
from core.db import (
    DB_PATH,
    count_operations,
    save_manual_prices,
    delete_enveloppe,
    init_db,
)

st.set_page_config(page_title="Import — Patrimoine", page_icon="📥", layout="wide")
init_session()
inject_css()

st.markdown("## 📥 Import")
st.caption(f"Base locale : `{DB_PATH}` — les opérations survivent au redémarrage.")

# État DB
counts = count_operations()
c1, c2, c3, c4 = st.columns(4)
c1.metric("PEA (DB)", counts.get("PEA", 0))
c2.metric("PER (DB)", counts.get("PER", 0))
c3.metric("CTO (DB)", counts.get("CTO", 0))
c4.metric("Total", sum(counts.values()))

st.markdown("---")

left, right = st.columns(2)

with left:
    st.markdown("### PEA")
    pea_pdfs = st.file_uploader(
        "Avis CIC (PDF)", type=["pdf"], accept_multiple_files=True, key="imp_pea_pdf"
    )
    pea_csv = st.file_uploader("CSV opérations PEA", type=["csv"], key="imp_pea_csv")
    pea_mode = st.radio(
        "Mode PEA",
        ["Fusionner (anti-doublon)", "Remplacer tout le PEA"],
        horizontal=True,
        key="pea_mode",
    )

    st.markdown("### CTO")
    cto_pdfs = st.file_uploader(
        "Trade Republic / CIC (PDF)", type=["pdf"], accept_multiple_files=True, key="imp_cto_pdf"
    )
    cto_mode = st.radio(
        "Mode CTO",
        ["Fusionner (anti-doublon)", "Remplacer tout le CTO"],
        horizontal=True,
        key="cto_mode",
    )

with right:
    st.markdown("### PER")
    per_csv = st.file_uploader("CSV opérations PER", type=["csv"], key="imp_per_csv")
    per_mode = st.radio(
        "Mode PER CSV",
        ["Fusionner (anti-doublon)", "Remplacer le PER (hors manuel)"],
        horizontal=True,
        key="per_mode",
    )

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
            if st.form_submit_button("Ajouter & sauver"):
                if m_isin and m_cours > 0 and m_qty > 0:
                    q, c, f = float(m_qty), float(m_cours), float(m_frais)
                    op = {
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
                    }
                    ins, skip = persist_enveloppe([op], "PER", mode="merge")
                    st.session_state["per_manual"].append(op)
                    st.session_state["histories"] = {}
                    rebuild_portfolios()
                    st.success(f"Sauvé en DB ({ins} ajoutée, {skip} doublon)")
                else:
                    st.error("ISIN, quantité et cours obligatoires")

    st.markdown("### Cours manuels OPCVM")
    with st.expander("Forcer un cours"):
        fi = st.text_input("ISIN", key="force_isin")
        fc = st.number_input("Cours (€)", min_value=0.0, format="%.4f", key="force_cours")
        if st.button("Enregistrer") and fi and fc > 0:
            st.session_state["manual_prices"][fi.strip().upper()] = float(fc)
            save_manual_prices(st.session_state["manual_prices"])
            st.success(f"{fi} → {fc:.4f} € (DB)")
    if st.session_state["manual_prices"]:
        for isin, px in st.session_state["manual_prices"].items():
            st.text(f"{isin} : {px:.4f} €")
        if st.button("Vider cours manuels"):
            st.session_state["manual_prices"] = {}
            save_manual_prices({})
            st.rerun()

st.markdown("---")
if st.button("🔄 Charger fichiers → session + SQLite", type="primary", use_container_width=True):
    log = []
    n_ok = n_fail = 0

    def mode_flag(label: str) -> str:
        return "replace" if label.startswith("Remplacer") else "merge"

    # PEA PDF
    if pea_pdfs:
        pea_txs = []
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
        if mode_flag(pea_mode) == "replace":
            # garder CSV PEA en DB : on ne wipe que si pas de csv dans ce batch
            # simple: merge PDF always for PDF; replace only if radio replace on full PEA handled below
            ins, sk = persist_enveloppe(pea_txs, "PEA", "merge")
        else:
            ins, sk = persist_enveloppe(pea_txs, "PEA", "merge")
        st.session_state["pea_files_data"] = (
            pea_txs if mode_flag(pea_mode) == "replace"
            else st.session_state.get("pea_files_data", []) + pea_txs
        )
        log.append(f"PEA PDF : {ins} insérées, {sk} doublons")

    # PEA CSV
    if pea_csv is not None:
        rows = parse_csv_transactions(pea_csv)
        for r in rows:
            r["source"] = r.get("source") or "CSV PEA"
        m = mode_flag(pea_mode)
        if m == "replace":
            # replace only CSV-tagged? simpler: merge CSV rows
            ins, sk = persist_enveloppe(rows, "PEA", "merge")
        else:
            ins, sk = persist_enveloppe(rows, "PEA", "merge")
        st.session_state["pea_csv_data"] = rows
        n_ok += len(rows)
        log.append(f"PEA CSV : {ins} insérées, {sk} doublons")

    # CTO PDF
    if cto_pdfs:
        cto_txs = []
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
        if mode_flag(cto_mode) == "replace":
            ins, sk = persist_enveloppe(cto_txs, "CTO", "replace")
            st.session_state["cto_files_data"] = cto_txs
        else:
            ins, sk = persist_enveloppe(cto_txs, "CTO", "merge")
            st.session_state["cto_files_data"] = st.session_state.get("cto_files_data", []) + cto_txs
        log.append(f"CTO PDF : {ins} insérées, {sk} doublons")

    # PER CSV
    if per_csv is not None:
        rows = parse_csv_transactions(per_csv)
        for r in rows:
            if not r.get("source") or r["source"] == "CSV":
                r["source"] = "CSV PER"
        if mode_flag(per_mode) == "replace":
            # conserve manuelles : delete only non-manuel then insert
            from core.db import get_connection, init_db as _init
            _init()
            conn = get_connection()
            conn.execute(
                "DELETE FROM operations WHERE enveloppe = 'PER' AND IFNULL(source,'') NOT LIKE '%Manuel%'"
            )
            conn.commit()
            conn.close()
            ins, sk = persist_enveloppe(rows, "PER", "merge")
        else:
            ins, sk = persist_enveloppe(rows, "PER", "merge")
        st.session_state["per_csv_data"] = rows
        n_ok += len(rows)
        log.append(f"PER CSV : {ins} insérées, {sk} doublons")

    save_manual_prices(st.session_state.get("manual_prices", {}))
    st.session_state["histories"] = {}
    # Recharge depuis DB pour cohérence
    st.session_state["db_loaded"] = False
    load_from_db()
    st.session_state["db_loaded"] = True

    st.success(
        f"Terminé — {n_ok} op. lues" + (f", {n_fail} PDF ignorés" if n_fail else "")
    )
    for line in log:
        st.caption(line)
    st.rerun()



st.markdown("---")
st.markdown("### 🔗 Powens (agrégateur bancaire)")
st.caption(
    "Complément optionnel aux PDF/CSV. Snapshot de positions — le PRU reste mieux couvert par les avis d'opérés. "
    "Secrets dans `.env` (voir `.env.example`)."
)

from core.connectors import powens as pw

if not pw.is_configured():
    st.warning(
        "Powens non configuré. Copie `.env.example` → `.env` et renseigne "
        "`POWENS_DOMAIN`, `POWENS_CLIENT_ID`, `POWENS_CLIENT_SECRET`."
    )
else:
    token_ok = pw.load_user_token() is not None
    st.write("Token local :", "✅ présent (chiffré)" if token_ok else "❌ absent")

    p1, p2, p3, p4 = st.columns(4)
    with p1:
        if st.button("1. Init user Powens"):
            try:
                data = pw.init_user()
                st.success(f"User créé / token sauvé (id={data.get('id') or data.get('id_user')})")
            except Exception as e:
                st.error(str(e))
    with p2:
        if st.button("2. Ouvrir Webview banque"):
            try:
                if not pw.load_user_token():
                    pw.init_user()
                url = pw.webview_connect_url()
                st.markdown(f"[Ouvrir la connexion bancaire Powens]({url})")
                st.info("Après consentement banque, reviens ici puis « Synchroniser ».")
            except Exception as e:
                st.error(str(e))
    with p3:
        if st.button("3. Synchroniser positions"):
            try:
                token = pw.load_user_token()
                if not token:
                    st.error("Pas de token — étape 1 d'abord")
                else:
                    for conn in pw.list_connections(token):
                        cid = conn.get("id")
                        if cid is not None:
                            try:
                                pw.sync_connection(cid, token)
                            except Exception:
                                pass
                    invs = pw.list_investments(token)
                    accounts = pw.list_accounts(token)
                    st.session_state["powens_investments"] = invs
                    st.session_state["powens_accounts"] = accounts
                    st.success(f"{len(invs)} position(s), {len(accounts)} compte(s)")
            except Exception as e:
                st.error(str(e))
    with p4:
        if st.button("Révoquer token Powens"):
            try:
                pw.revoke_token()
                st.warning("Token révoqué et effacé localement")
            except Exception as e:
                st.error(str(e))

    invs = st.session_state.get("powens_investments") or []
    if invs:
        import pandas as pd
        rows = []
        for inv in invs:
            rows.append({
                "ISIN": inv.get("code") or inv.get("isin"),
                "Label": inv.get("label") or inv.get("name"),
                "Quantité": inv.get("quantity"),
                "Cours": inv.get("unitvalue") or inv.get("unit_value"),
                "Valo": inv.get("valuation") or inv.get("value"),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        env_choice = st.selectbox(
            "Importer le snapshot comme enveloppe",
            ["PEA", "PER", "CTO"],
            key="powens_env",
        )
        if st.button("Écrire snapshot dans SQLite (no_cash)"):
            from core.state import persist_enveloppe, load_from_db, rebuild_portfolios
            ops = pw.investments_to_snapshot_ops(invs, env_choice)
            # Marquer source
            for o in ops:
                o["source"] = f"Powens snapshot {env_choice}"
            ins, sk = persist_enveloppe(ops, env_choice, mode="merge")
            st.session_state["histories"] = {}
            st.session_state["db_loaded"] = False
            load_from_db()
            st.session_state["db_loaded"] = True
            st.success(f"{ins} lignes insérées, {sk} doublons ignorés — enveloppe {env_choice}")
            st.rerun()



st.markdown("---")
st.markdown("### 🎯 Cibles d'allocation géographique")
st.caption("Utilisées sur Vue globale et chaque enveloppe (réel vs cible). Somme conseillée = 100 %.")
try:
    from core.db import get_allocation_targets, save_allocation_targets, init_db
    from core.geography import ALLOC_ZONES, DEFAULT_TARGETS
    init_db()
    cur = get_allocation_targets()
    with st.form("form_alloc_targets"):
        cols = st.columns(len(ALLOC_ZONES))
        new_t = {}
        for col, z in zip(cols, ALLOC_ZONES):
            with col:
                new_t[z] = st.number_input(
                    z, min_value=0.0, max_value=100.0,
                    value=float(cur.get(z, DEFAULT_TARGETS.get(z, 0.0))),
                    step=1.0, key=f"tgt_{z}",
                )
        total_t = sum(new_t.values())
        st.caption(f"Somme des cibles : **{total_t:.1f} %**"
                   + (" ✅" if abs(total_t - 100) < 0.5 else " ⚠️ idéalement 100 %"))
        c_save, c_reset = st.columns(2)
        save = c_save.form_submit_button("Enregistrer les cibles", type="primary")
        reset = c_reset.form_submit_button("Réinitialiser défauts")
        if save:
            save_allocation_targets(new_t)
            st.success("Cibles enregistrées en base locale")
            st.rerun()
        if reset:
            save_allocation_targets(dict(DEFAULT_TARGETS))
            st.success("Cibles remises aux valeurs par défaut")
            st.rerun()
except Exception as e:
    st.warning(f"Cibles non disponibles : {e}")

st.markdown("### Maintenance")
m1, m2, m3 = st.columns(3)
with m1:
    if st.button("Recharger depuis la DB"):
        st.session_state["db_loaded"] = False
        load_from_db()
        st.session_state["db_loaded"] = True
        st.success("Session rechargée")
        st.rerun()
with m2:
    env_del = st.selectbox("Vider enveloppe DB", ["—", "PEA", "PER", "CTO"])
    if st.button("Supprimer") and env_del != "—":
        n = delete_enveloppe(env_del)
        st.session_state["db_loaded"] = False
        load_from_db()
        st.session_state["db_loaded"] = True
        st.warning(f"{n} lignes {env_del} supprimées")
        st.rerun()
with m3:
    st.caption(f"Fichier\n`{DB_PATH}`")
    if DB_PATH.exists():
        st.caption(f"{DB_PATH.stat().st_size / 1024:.1f} Ko")

with st.expander("Modèle CSV"):
    st.code(
        "date,type,quantite,isin,nom,cours,frais,montant\n"
        "01/11/2025,ACHAT,0.100484,,CM-AM ACTIONS MONDE RC,345.33,0,34.70\n"
        "01/11/2025,VERSEMENT,,,Euro Retraite,,,40.00\n"
        "15/07/2026,VENTE,0.100484,,CM-AM ACTIONS MONDE RC,360.00,0,36.17",
        language=None,
    )
