"""Import PDF / CSV / saisie manuelle — persistance SQLite."""
import pandas as pd
from datetime import datetime
from pathlib import Path

import streamlit as st

from core.state import (
    init_session,
    rebuild_portfolios,
    persist_enveloppe,
    load_from_db,
)
from core.style import inject_css
from core.nav import render_sidebar
from core.parsers import (
    extract_transaction_from_pdf,
    extract_transaction_from_traderepublic,
    parse_csv_transactions,
    parse_liquidity_csv,
    parse_livrets_csv,
)
from core.import_log import log_import_batch, load_journal, clear_journal, missing_price_alerts_from_open_df
from core.db import (
    DB_PATH,
    count_operations,
    save_manual_prices,
    delete_enveloppe,
    init_db,
    backup_db_bytes,
    restore_db_from_bytes,
    delete_cash_operations,
    load_ticker_overrides,
    save_ticker_overrides,
)

st.set_page_config(page_title="Import — Patrimoine", page_icon="📥", layout="wide")
init_session()
inject_css()
render_sidebar(active="import")

# Hero Import (style Finary)
_counts_h = count_operations()
_n_ops = sum(int(_counts_h.get(k, 0) or 0) for k in ("PEA", "PER", "CTO"))
st.markdown(
    '<div class="hero">'
    '<div class="hero-label">Import</div>'
    '<div class="hero-value" style="font-size:2rem;">Données &amp; synchronisation</div>'
    '<div class="hero-meta">'
    + f"Base locale · {_n_ops} opérations en DB · PEA {_counts_h.get('PEA', 0)} · "
    + f"PER {_counts_h.get('PER', 0)} · CTO {_counts_h.get('CTO', 0)}"
    + "</div></div>",
    unsafe_allow_html=True,
)
st.caption(f"Fichier SQLite : `{DB_PATH}`")

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
        "Avis PDF (CIC et/ou Trade Republic)",
        type=["pdf"],
        accept_multiple_files=True,
        key="imp_pea_pdf",
        help="Après transfert chez Trade Republic : dépose les confirmations d'investissement PEA. "
             "Les anciens avis CIC restent valides pour l'historique.",
    )
    st.caption(
        "Parseur **CIC** + **Trade Republic** (achat / vente / bonus / plan). "
        "Conserve l'historique CIC : mode **Fusionner**."
    )
    pea_csv = st.file_uploader("CSV opérations PEA", type=["csv"], key="imp_pea_csv")
    pea_liq = st.file_uploader(
        "CSV liquidité PEA (virements / versements / régularisations)",
        type=["csv"], key="imp_pea_liq",
    )
    st.caption("Modèle : data/modele_liquidite_pea.csv — colonnes date;operation;debit;credit")
    pea_mode = st.radio(
        "Mode PEA",
        ["Fusionner (anti-doublon)", "Remplacer tout le PEA"],
        horizontal=True,
        key="pea_mode",
    )
    with st.expander("Transfert PEA → Trade Republic — comment importer ?", expanded=False):
        st.markdown(
            """
1. **Ne clôture pas** le PEA CIC : demande un **transfert** vers TR.
2. Garde tous les **PDF CIC** déjà importés (historique / PRU).
3. Dès que TR envoie des **confirmations PEA**, importe-les ici (même zone PDF).
4. Mode recommandé : **Fusionner** (anti-doublon).
5. Les apports post-transfert : export **liquidité / cash** TR si disponible, sinon CSV manuel.
6. Si un PDF TR ne passe pas : envoie un exemple pour enrichir le parseur.
            """
        )

    st.markdown("### Livrets (A / LEP / LDDS)")
    liv_csv = st.file_uploader("CSV livrets", type=["csv"], key="imp_liv_csv")
    st.caption("Colonnes : date;livret;type;montant — livret=LA|LEP|LDDS · type=SOLDE|VERSEMENT|RETRAIT|INTERETS")
    liv_mode = st.radio("Mode Livrets", ["Fusionner", "Remplacer"], horizontal=True, key="liv_mode")

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

    # PEA PDF (CIC + Trade Republic)
    if pea_pdfs:
        pea_txs = []
        failed_names = []
        ok_names = []
        n_tr = n_cic = 0
        for f in pea_pdfs:
            fname = getattr(f, "name", str(f))
            # Trade Republic en premier (docs TR), puis CIC
            tx = extract_transaction_from_traderepublic(f)
            if tx is not None:
                n_tr += 1
            else:
                tx = extract_transaction_from_pdf(f)
                if tx is not None:
                    n_cic += 1
            if tx:
                tx.setdefault("kind", "uc")
                # Forcer enveloppe logique PEA si source TR sans tag
                src = str(tx.get("source") or "")
                if "Trade Republic" in src and "PEA" not in src:
                    tx["source"] = "Trade Republic PEA"
                pea_txs.append(tx)
                n_ok += 1
                ok_names.append(fname)
            else:
                n_fail += 1
                failed_names.append(fname)
        mflag = mode_flag(pea_mode)
        if mflag == "replace":
            ins, sk = persist_enveloppe(pea_txs, "PEA", "replace")
            st.session_state["pea_files_data"] = pea_txs
        else:
            ins, sk = persist_enveloppe(pea_txs, "PEA", "merge")
            st.session_state["pea_files_data"] = (
                st.session_state.get("pea_files_data", []) + pea_txs
            )
        log.append(
            f"PEA PDF : {ins} insérées, {sk} doublons, {len(failed_names)} échecs "
            f"(TR {n_tr} / CIC {n_cic})"
        )
        log_import_batch(
            enveloppe="PEA", source="PDF CIC+TR", files=ok_names + failed_names,
            inserted=ins, duplicates=sk, failed=len(failed_names),
            failed_files=failed_names, mode=mflag,
            extra=f"TR={n_tr} CIC={n_cic}",
        )

    # PEA CSV opérations titres
    if pea_csv is not None:
        rows = parse_csv_transactions(pea_csv)
        for r in rows:
            r["source"] = r.get("source") or "CSV PEA"
        m = mode_flag(pea_mode)
        ins, sk = persist_enveloppe(rows, "PEA", "merge")
        st.session_state["pea_csv_data"] = rows
        n_ok += len(rows)
        fname = getattr(pea_csv, "name", "pea.csv")
        log.append(f"PEA CSV : {ins} insérées, {sk} doublons ({len(rows)} lignes lues)")
        try:
            log_import_batch(
                enveloppe="PEA", source="CSV", files=[fname],
                inserted=ins, duplicates=sk, failed=0, mode=m,
                extra=f"{len(rows)} lignes parsées",
            )
        except Exception:
            pass

    # PEA CSV liquidité (apports + journal de caisse complet)
    if pea_liq is not None:
        liq_rows = parse_liquidity_csv(pea_liq)
        for r in liq_rows:
            r["source"] = r.get("source") or "CSV liquidité"
            r["kind"] = "cash"
        # Remplace l'ancien journal liquidité (évite VERSEMENT sans CASH_OUT)
        n_del = delete_cash_operations("PEA")
        ins, sk = persist_enveloppe(liq_rows, "PEA", "merge")
        st.session_state["pea_liquidity"] = liq_rows
        n_ok += len(liq_rows)
        n_vers = sum(1 for r in liq_rows if r.get("type") == "VERSEMENT")
        tot_ap = sum(r["montant"] for r in liq_rows if r.get("type") == "VERSEMENT")
        tot_ret = sum(r["montant"] for r in liq_rows if r.get("type") == "RETRAIT")
        log.append(
            f"PEA liquidité : {n_del} anciennes lignes cash purgées, {len(liq_rows)} flux retenus ({n_vers} versements, "
            f"apports +{tot_ap:.2f} € / retraits −{tot_ret:.2f} €), {ins} insérées DB, {sk} doublons"
        )

        try:
            from core.portfolio import compute_cash_and_contributions, cash_sanity_check
            _flow_liq = compute_cash_and_contributions(liq_rows)
            log.append(
                f"PEA liquidité contrôle cash : {_flow_liq.get('cash', 0):+.2f} € "
                f"(apports {_flow_liq.get('apports', 0):.2f} €, source {_flow_liq.get('apports_source')})"
            )
            _al = cash_sanity_check(_flow_liq)
            if _al:
                log.append("⚠ " + _al["message"])
            else:
                log.append("✓ Cash liquidité cohérent (≈ 0 €)")
        except Exception as _e:
            log.append(f"Contrôle cash liquidité indisponible : {_e}")

        try:
            log_import_batch(
                enveloppe="PEA", source="CSV liquidité",
                files=[getattr(pea_liq, "name", "liquidite.csv")],
                inserted=ins, duplicates=sk, failed=0, mode=mode_flag(pea_mode),
                extra=f"apports +{tot_ap:.2f} €",
            )
        except Exception:
            pass

    
    # Livrets CSV
    if liv_csv is not None:
        liv_rows = parse_livrets_csv(liv_csv)
        for r in liv_rows:
            r["kind"] = "livret"
        if liv_mode.startswith("Remplacer"):
            from core.db import replace_enveloppe
            n = replace_enveloppe(liv_rows, "LIVRETS")
            ins, sk = n, 0
            st.session_state["livrets_data"] = liv_rows
        else:
            ins, sk = persist_enveloppe(liv_rows, "LIVRETS", "merge")
            st.session_state["livrets_data"] = list(st.session_state.get("livrets_data", [])) + liv_rows
        n_ok += len(liv_rows)
        log.append(f"Livrets CSV : {len(liv_rows)} lignes, {ins} insérées, {sk} doublons")
        try:
            log_import_batch(
                enveloppe="LIVRETS", source="CSV",
                files=[getattr(liv_csv, "name", "livrets.csv")],
                inserted=ins, duplicates=sk, failed=0, mode=liv_mode,
            )
        except Exception:
            pass

    # CTO PDF
    if cto_pdfs:
        cto_txs = []
        failed_names = []
        ok_names = []
        for f in cto_pdfs:
            fname = getattr(f, "name", str(f))
            tx = extract_transaction_from_traderepublic(f)
            if tx is None:
                tx = extract_transaction_from_pdf(f)
            if tx:
                tx.setdefault("kind", "uc")
                cto_txs.append(tx)
                n_ok += 1
                ok_names.append(fname)
            else:
                n_fail += 1
                failed_names.append(fname)
        mflag = mode_flag(cto_mode)
        if mflag == "replace":
            ins, sk = persist_enveloppe(cto_txs, "CTO", "replace")
            st.session_state["cto_files_data"] = cto_txs
        else:
            ins, sk = persist_enveloppe(cto_txs, "CTO", "merge")
            st.session_state["cto_files_data"] = st.session_state.get("cto_files_data", []) + cto_txs
        log.append(f"CTO PDF : {ins} insérées, {sk} doublons, {len(failed_names)} échecs parse")
        log_import_batch(
            enveloppe="CTO", source="PDF", files=ok_names + failed_names,
            inserted=ins, duplicates=sk, failed=len(failed_names),
            failed_files=failed_names, mode=mflag,
        )

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
        log_import_batch(enveloppe="PER", source="CSV", files=[getattr(per_csv, "name", "per.csv")], inserted=ins, duplicates=sk, failed=0, mode="merge")
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


st.markdown("---")
st.markdown("### 📋 Journal d'import")
st.caption("Historique des derniers imports (persisté en SQLite). Max 100 entrées.")
jlog = load_journal()
if jlog:
    import pandas as pd
    jrows = []
    for e in jlog[:30]:
        jrows.append({
            "Date": e.get("ts"),
            "Enveloppe": e.get("enveloppe"),
            "Source": e.get("source"),
            "Mode": e.get("mode"),
            "Fichiers": e.get("n_files"),
            "Insérées": e.get("inserted"),
            "Doublons": e.get("duplicates"),
            "Échecs parse": e.get("failed"),
            "Fichiers en échec": ", ".join(e.get("failed_files") or [])[:80],
            "Détail": e.get("extra") or "",
        })
    st.dataframe(pd.DataFrame(jrows), use_container_width=True, hide_index=True)
    if st.button("Vider le journal d'import"):
        clear_journal()
        st.rerun()
else:
    st.caption("Aucune entrée pour l'instant — lance un import.")

st.markdown("### ⚠️ Alertes cours manquants")
st.caption("Positions ouvertes sans cours Yahoo ni fallback. Saisis un cours manuel ci-dessous ou vérifie le ticker.")
_alerts = []
for _key in ("pea", "per", "cto"):
    _data = st.session_state.get(_key)
    if not _data:
        continue
    _open = _data.get("open")
    if _open is None:
        # rebuild open via enrich if needed
        try:
            from core.state import enrich
            _info = enrich(_data.get("by_isin") or {})
            _open = _info.get("open")
        except Exception:
            _open = None
    _alerts.extend(missing_price_alerts_from_open_df(_open))
if _alerts:
    import pandas as pd
    st.warning(f"{len(_alerts)} position(s) sans cours de valorisation")
    st.dataframe(pd.DataFrame(_alerts), use_container_width=True, hide_index=True)
else:
    st.success("Aucun cours manquant sur les positions ouvertes chargées.")


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
st.caption(
    "Une grille de cibles **par enveloppe** (PEA / PER / CTO). "
    "La **Vue globale** utilise la **moyenne pondérée** par valorisation de chaque enveloppe."
)
try:
    from core.db import get_allocation_targets, save_allocation_targets, init_db, average_allocation_targets
    from core.geography import ALLOC_ZONES, DEFAULT_TARGETS
    init_db()
    env_sel = st.radio(
        "Enveloppe à configurer",
        ["PEA", "PER", "CTO"],
        horizontal=True,
        key="alloc_env_sel",
    )
    cur = get_allocation_targets(env_sel)
    with st.form("form_alloc_targets"):
        st.markdown(f"**Cibles — {env_sel}**")
        cols = st.columns(len(ALLOC_ZONES))
        new_t = {}
        for col, z in zip(cols, ALLOC_ZONES):
            with col:
                new_t[z] = st.number_input(
                    z, min_value=0.0, max_value=100.0,
                    value=float(cur.get(z, DEFAULT_TARGETS.get(z, 0.0))),
                    step=1.0, key=f"tgt_{env_sel}_{z}",
                )
        total_t = sum(new_t.values())
        st.caption(
            f"Somme des cibles ({env_sel}) : **{total_t:.1f} %**"
            + (" ✅" if abs(total_t - 100) < 0.5 else " ⚠️ idéalement 100 %")
        )
        c_save, c_reset, c_copy = st.columns(3)
        save = c_save.form_submit_button(f"Enregistrer ({env_sel})", type="primary")
        reset = c_reset.form_submit_button(f"Défauts → {env_sel}")
        copy_all = c_copy.form_submit_button("Appliquer à PEA+PER+CTO")
        if save:
            save_allocation_targets(new_t, env_sel)
            st.success(f"Cibles {env_sel} enregistrées")
            st.rerun()
        if reset:
            save_allocation_targets(dict(DEFAULT_TARGETS), env_sel)
            st.success(f"Cibles {env_sel} = valeurs par défaut")
            st.rerun()
        if copy_all:
            for e in ("PEA", "PER", "CTO"):
                save_allocation_targets(new_t, e)
            st.success("Mêmes cibles appliquées à PEA, PER et CTO")
            st.rerun()
    # Aperçu moyenne globale
    with st.expander("Aperçu moyenne globale (pondération égale ici)"):
        avg = average_allocation_targets()
        st.json(avg)
        st.caption("En Vue globale, la pondération suit la valorisation réelle de chaque enveloppe.")
except Exception as e:
    st.warning(f"Cibles non disponibles : {e}")



st.markdown("### Tickers Yahoo (ISIN → symbole)")
st.caption(
    "Priorité sur la table intégrée. Plusieurs symboles possibles, séparés par des virgules "
    "(le premier qui répond est utilisé). Utile si un cours est à 0 ou erroné."
)
from core.config import YAHOO_TICKERS as _YT_DEFAULT
if "ticker_overrides" not in st.session_state:
    st.session_state["ticker_overrides"] = load_ticker_overrides()

# Table éditable : union defaults + overrides
_all_isins = sorted(set(list(_YT_DEFAULT.keys()) + list(st.session_state["ticker_overrides"].keys())))
_rows_tk = []
for _isin in _all_isins:
    _ov = st.session_state["ticker_overrides"].get(_isin)
    if _ov:
        _tk = ", ".join(_ov) if isinstance(_ov, list) else str(_ov)
        _src = "perso"
    else:
        _raw = _YT_DEFAULT.get(_isin, [])
        _tk = ", ".join(_raw) if isinstance(_raw, list) else str(_raw)
        _src = "défaut"
    _rows_tk.append({"ISIN": _isin, "Tickers": _tk, "Source": _src})

_edited = st.data_editor(
    pd.DataFrame(_rows_tk) if _rows_tk else pd.DataFrame(columns=["ISIN", "Tickers", "Source"]),
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    key="ticker_editor",
    column_config={
        "ISIN": st.column_config.TextColumn("ISIN", width="medium"),
        "Tickers": st.column_config.TextColumn("Tickers Yahoo (virgules)", width="large"),
        "Source": st.column_config.TextColumn("Source", disabled=True, width="small"),
    },
)
c_tk1, c_tk2, c_tk3 = st.columns(3)
with c_tk1:
    if st.button("Enregistrer les tickers", type="primary", key="save_tickers"):
        _new = {}
        for _, r in _edited.iterrows():
            isin = str(r.get("ISIN") or "").strip().upper()
            tk = str(r.get("Tickers") or "").strip()
            if not isin or not tk:
                continue
            # Ne stocker que si différent du défaut ou isin nouveau
            default = _YT_DEFAULT.get(isin)
            default_s = ", ".join(default) if isinstance(default, list) else str(default or "")
            if tk.replace(" ", "") != default_s.replace(" ", "") or isin not in _YT_DEFAULT:
                _new[isin] = [x.strip() for x in tk.replace(";", ",").split(",") if x.strip()]
        save_ticker_overrides(_new)
        st.session_state["ticker_overrides"] = _new
        # invalider cache cours
        try:
            st.cache_data.clear()
        except Exception:
            pass
        st.success(f"{len(_new)} override(s) enregistré(s)")
        st.rerun()
with c_tk2:
    if st.button("Réinitialiser les overrides", key="reset_tickers"):
        save_ticker_overrides({})
        st.session_state["ticker_overrides"] = {}
        try:
            st.cache_data.clear()
        except Exception:
            pass
        st.success("Overrides effacés — table config par défaut")
        st.rerun()
with c_tk3:
    st.caption("Après modification : les cours se recalculent au prochain affichage Vue globale / PEA.")


st.markdown("### 💾 Sauvegarde base SQLite")
st.caption(
    "Télécharge une copie cohérente de `patrimoine.db` (opérations, cours manuels, "
    "cibles d'allocation, objectif, journal d'import)."
)
b1, b2 = st.columns(2)
with b1:
    try:
        _db_bytes, _db_name = backup_db_bytes()
        if _db_bytes:
            st.download_button(
                label="⬇️ Télécharger la sauvegarde (.db)",
                data=_db_bytes,
                file_name=_db_name,
                mime="application/x-sqlite3",
                type="primary",
            )
            st.caption(f"{len(_db_bytes) / 1024:.1f} Ko · {_db_name}")
        else:
            st.warning("Base vide ou introuvable.")
    except Exception as e:
        st.error(f"Sauvegarde impossible : {e}")
with b2:
    _up = st.file_uploader(
        "Restaurer une sauvegarde .db",
        type=["db", "sqlite", "sqlite3"],
        key="restore_db",
    )
    if _up is not None and st.button("Restaurer (écrase la base locale)", type="secondary"):
        try:
            restore_db_from_bytes(_up.read())
            st.session_state["db_loaded"] = False
            load_from_db()
            st.session_state["db_loaded"] = True
            st.session_state["histories"] = {}
            st.success("Base restaurée — session rechargée.")
            st.rerun()
        except Exception as e:
            st.error(f"Restauration échouée : {e}")

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
