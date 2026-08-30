"""Session state et chargement des portefeuilles."""
from datetime import datetime

import pandas as pd
import streamlit as st

from core.parsers import (
    extract_transaction_from_pdf,
    extract_transaction_from_traderepublic,
    parse_csv_transactions,
    split_uc_and_fe,
)
from core.portfolio import (
    process_transactions,
    process_fonds_euros,
    compute_cash_and_contributions,
    build_history,
    build_summary,
)
from core.prices import get_current_prices, apply_price_fallbacks
from core.db import (
    init_db, load_operations, load_manual_prices,
    insert_operations, replace_enveloppe, save_manual_prices,
    count_operations, DB_PATH,
)


def init_session():
    defaults = {
        "pea_files_data": [],
        "pea_csv_data": [],
        "cto_files_data": [],
        "per_csv_data": [],
        "per_manual": [],
        "pea_liquidity": [],
        "manual_prices": {},
        "histories": {},
        "pea_files_names": [],
        "cto_files_names": [],
        "per_csv_name": None,
        "pea_csv_name": None,
        "db_loaded": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v if not isinstance(v, dict) else dict(v)
            if isinstance(v, list):
                st.session_state[k] = list(v)

    # Charge SQLite une seule fois par session navigateur
    if not st.session_state.get("db_loaded"):
        load_from_db()
        st.session_state["db_loaded"] = True


def load_from_db():
    """Remplit session_state depuis patrimoine.db."""
    try:
        init_db()
    except Exception:
        return
    pea = load_operations("PEA")
    per = load_operations("PER")
    cto = load_operations("CTO")

    def _is_liq(o):
        src = str(o.get("source") or "").lower()
        return o.get("kind") == "cash" or "liquidit" in src

    def _is_csv_titres(o):
        src = str(o.get("source") or "")
        return "CSV" in src and not _is_liq(o)

    # Sépare PDF / CSV titres / liquidité
    st.session_state["pea_files_data"] = [
        o for o in pea if "CSV" not in str(o.get("source", "")) and not _is_liq(o)
    ]
    st.session_state["pea_csv_data"] = [o for o in pea if _is_csv_titres(o)]
    st.session_state["pea_liquidity"] = [o for o in pea if _is_liq(o)]
    st.session_state["per_csv_data"] = [o for o in per if "Manuel" not in str(o.get("source", ""))]
    st.session_state["per_manual"] = [o for o in per if "Manuel" in str(o.get("source", ""))]
    st.session_state["cto_files_data"] = cto
    st.session_state["manual_prices"] = load_manual_prices()
    st.session_state["histories"] = {}
    if pea or per or cto:
        rebuild_portfolios()


def persist_enveloppe(ops: list, enveloppe: str, mode: str = "merge") -> tuple:
    """mode=merge → INSERT OR IGNORE ; mode=replace → DELETE + INSERT."""
    if mode == "replace":
        n = replace_enveloppe(ops, enveloppe)
        return n, 0
    return insert_operations(ops, enveloppe)


def _parse_pdfs(files, prefer_tr=False):
    txs = []
    for f in files or []:
        tx = None
        if prefer_tr:
            tx = extract_transaction_from_traderepublic(f)
            if tx is None:
                tx = extract_transaction_from_pdf(f)
        else:
            tx = extract_transaction_from_pdf(f)
            if tx is None:
                tx = extract_transaction_from_traderepublic(f)
        if tx:
            tx.setdefault("kind", "uc")
            txs.append(tx)
    return txs


def rebuild_portfolios():
    """Recalcule PEA / PER / CTO à partir de session_state."""
    # PEA
    pea = list(st.session_state.get("pea_files_data", []))
    pea += list(st.session_state.get("pea_csv_data", []))
    pea += list(st.session_state.get("pea_liquidity", []))
    pea_df, pea_by_isin = process_transactions(pea)

    # CTO
    cto = list(st.session_state.get("cto_files_data", []))
    cto_df, cto_by_isin = process_transactions(cto)

    # PER
    per_raw = list(st.session_state.get("per_csv_data", []))
    for m in st.session_state.get("per_manual", []):
        mm = dict(m)
        mm.setdefault("kind", "uc")
        per_raw.append(mm)
    per_uc, per_fe_ops = split_uc_and_fe(per_raw)
    per_df, per_by_isin = process_transactions(per_uc)
    per_fe_by_id = process_fonds_euros(per_fe_ops)

    st.session_state["pea"] = {"txs": pea, "df": pea_df, "by_isin": pea_by_isin}
    st.session_state["cto"] = {"txs": cto, "df": cto_df, "by_isin": cto_by_isin}
    st.session_state["per"] = {
        "txs": per_uc,
        "df": per_df,
        "by_isin": per_by_isin,
        "fe_by_id": per_fe_by_id,
        "fe_ops": per_fe_ops,
    }


def enrich(by_isin):
    """Prix + summary + open/sold."""
    if not by_isin:
        return {
            "prices": {},
            "summary": pd.DataFrame(),
            "open": pd.DataFrame(),
            "sold": pd.DataFrame(),
        }
    isins = tuple(by_isin.keys())
    prices = get_current_prices(isins)
    prices = apply_price_fallbacks(by_isin, prices, st.session_state.get("manual_prices", {}))
    summary = build_summary(by_isin, prices)
    if summary.empty:
        open_df = sold_df = summary
    else:
        open_df = summary[summary["Parts"] > 1e-9]
        sold_df = summary[summary["Parts"] <= 1e-9]
    return {"prices": prices, "summary": summary, "open": open_df, "sold": sold_df}



def sum_purchase_fees(txs: list) -> float:
    """Somme des frais d'exécution sur ACHAT (hors FRAIS de gestion / BONUS)."""
    total = 0.0
    for op in txs or []:
        typ = str(op.get("type", "")).upper()
        if typ != "ACHAT":
            continue
        f = op.get("frais")
        if f is None:
            continue
        try:
            total += float(f)
        except (TypeError, ValueError):
            pass
    return round(total, 2)


def metrics_for(txs, open_df, fe_by_id=None):
    flow = compute_cash_and_contributions(txs)
    fe_by_id = fe_by_id or {}
    fe_apports = sum(v["apports"] for v in fe_by_id.values()) if fe_by_id else 0.0
    fe_valo = sum(v["valo"] for v in fe_by_id.values()) if fe_by_id else 0.0
    fe_interets = sum(v["interets"] for v in fe_by_id.values()) if fe_by_id else 0.0

    investi_ouvert = float(open_df["Investi (€)"].sum()) if open_df is not None and not open_df.empty else 0.0
    valo_titres = float(open_df["Valorisation (€)"].sum()) if open_df is not None and not open_df.empty else 0.0
    if pd.isna(investi_ouvert):
        investi_ouvert = 0.0
    if pd.isna(valo_titres):
        valo_titres = 0.0

    apports = flow["apports"] + fe_apports
    patrimoine = valo_titres + flow["cash"] + fe_valo
    pv = patrimoine - apports
    pct = 100 * pv / apports if apports else 0.0
    frais_achat = sum_purchase_fees(txs)
    return {
        "flow": flow,
        "fe_apports": fe_apports,
        "fe_valo": fe_valo,
        "fe_interets": fe_interets,
        "investi_ouvert": investi_ouvert,
        "valo_titres": valo_titres,
        "apports": apports,
        "patrimoine": patrimoine,
        "pv": pv,
        "pct": pct,
        "frais_achat": frais_achat,
    }


def get_history(key, by_isin, txs):
    if key not in st.session_state["histories"]:
        st.session_state["histories"][key] = build_history(by_isin, txs)
    return st.session_state["histories"][key]
