"""Agrégation portefeuille, cash, historique, synthèse."""
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd

from core.config import YAHOO_TICKERS
from core.prices import get_historical_prices

def process_fonds_euros(ops: list) -> dict:
    by_id = defaultdict(lambda: {
        "name": "", "verse": 0.0, "retire": 0.0, "interets": 0.0, "ops": []
    })
    for op in sorted(ops, key=lambda x: x["date"]):
        fid = op["isin"]
        by_id[fid]["name"] = op.get("valeur") or fid
        m = float(op["montant"])
        if op["type"] == "VERSEMENT":
            by_id[fid]["verse"] += m
        elif op["type"] in ("RETRAIT", "FRAIS_FE"):
            by_id[fid]["retire"] += m
        elif op["type"] == "INTERETS":
            by_id[fid]["interets"] += m
        by_id[fid]["ops"].append(op)
    for fid, v in by_id.items():
        v["apports"] = v["verse"] - v["retire"]
        v["valo"] = v["apports"] + v["interets"]
    return dict(by_id)

def process_transactions(transactions: list):
    if not transactions:
        return pd.DataFrame(), {}

    transactions = sorted(transactions, key=lambda x: x["date"])
    df = pd.DataFrame(transactions)
    df["date_str"] = df["date"].dt.strftime("%d/%m/%Y")

    by_isin = defaultdict(lambda: {"name": "", "parts": 0.0, "investi": 0.0, "ops": []})

    for t in transactions:
        isin = t["isin"]
        qty = float(t["quantite"])
        montant = t.get("montant") or t.get("debit") or 0.0
        typ = t.get("type", "ACHAT").upper()

        if t.get("valeur"):
            by_isin[isin]["name"] = str(t["valeur"]).split("(")[0].strip()

        if typ in ("ACHAT", "BONUS"):
            by_isin[isin]["parts"] += qty
            # BONUS (actions gratuites) : montant = 0 → dilue le PRU, n'augmente pas l'investi
            by_isin[isin]["investi"] += montant
        elif typ == "VENTE":
            if by_isin[isin]["parts"] > 0:
                cout_unitaire = by_isin[isin]["investi"] / by_isin[isin]["parts"]
                by_isin[isin]["parts"] = max(0.0, by_isin[isin]["parts"] - qty)
                by_isin[isin]["investi"] = max(0.0, by_isin[isin]["investi"] - cout_unitaire * qty)

        t["type"] = typ
        t["montant"] = montant
        by_isin[isin]["ops"].append(t)

        if t.get("solde") is not None:
            by_isin[isin]["parts"] = float(t["solde"])

    return df, dict(by_isin)

def compute_cash_and_contributions(transactions: list) -> dict:
    """Simule la trésorerie et estime les apports externes."""
    ops = sorted(transactions, key=lambda x: x["date"])
    cash = 0.0
    apports = 0.0
    total_achats = 0.0
    total_ventes = 0.0

    for op in ops:
        montant = float(op.get("montant") or 0.0)
        typ = op.get("type", "ACHAT").upper()
        no_cash = bool(op.get("no_cash"))

        if typ == "ACHAT":
            total_achats += montant
            cash -= montant
            if cash < -1e-9:
                apports += -cash
                cash = 0.0
        elif typ == "BONUS":
            pass  # actions gratuites : pas de mouvement de cash
        elif typ == "VENTE":
            # Frais de gestion (no_cash) : réduit les parts mais ne génère pas de cash
            if not no_cash:
                total_ventes += montant
                cash += montant

    return {
        "apports": round(apports, 2),
        "cash": round(cash, 2),
        "total_achats": round(total_achats, 2),
        "total_ventes": round(total_ventes, 2),
    }


def build_history(by_isin: dict, transactions: list) -> dict:
    """
    Historique investi + valorisation.
    - Investi : TOUS les supports (OPCVM inclus), dès le 1er ordre.
    - Valorisation : Yahoo si ticker dispo, sinon dernier cours connu des opérations (ffill).
    """
    if not transactions:
        return {
            "portfolio_value": pd.Series(dtype=float),
            "invested_cumul": pd.Series(dtype=float),
            "parts_history": {},
        }

    start_date = min(t["date"] for t in transactions) - timedelta(days=3)
    end_date = datetime.now()
    all_dates = pd.date_range(start=start_date, end=end_date, freq="B")

    portfolio_value = pd.Series(0.0, index=all_dates)
    invested_cumul = pd.Series(0.0, index=all_dates)
    parts_history = {}

    for isin, v in by_isin.items():
        parts_series = pd.Series(0.0, index=all_dates)
        cost_series = pd.Series(0.0, index=all_dates)
        # Série de cours « locaux » construite à partir des ops (pour OPCVM sans Yahoo)
        local_price = pd.Series(index=all_dates, dtype=float)
        running_parts = 0.0
        running_cost = 0.0

        for op in sorted(v["ops"], key=lambda x: x["date"]):
            qty = float(op.get("quantite") or 0)
            montant = float(op.get("montant") or op.get("debit") or 0.0)
            typ = op.get("type", "ACHAT").upper()
            cours_op = op.get("cours")

            if typ in ("ACHAT", "BONUS"):
                running_parts += qty
                running_cost += montant
            elif typ == "VENTE" and running_parts > 0:
                cout_unitaire = running_cost / running_parts
                running_cost = max(0.0, running_cost - cout_unitaire * qty)
                running_parts = max(0.0, running_parts - qty)

            mask = parts_series.index >= op["date"]
            parts_series.loc[mask] = running_parts
            cost_series.loc[mask] = running_cost

            # Enregistre le cours de l'opération pour fallback valorisation
            if cours_op and float(cours_op) > 0:
                local_price.loc[mask] = float(cours_op)

        # Toujours ajouter le coût de revient (OPCVM inclus)
        invested_cumul += cost_series
        parts_history[isin] = parts_series

        # Prix de marché
        ticker = YAHOO_TICKERS.get(isin)
        prices = pd.Series(dtype=float)
        if ticker:
            prices = get_historical_prices(ticker, start_date, end_date)

        if not prices.empty:
            prices = prices.reindex(all_dates).ffill()
            portfolio_value += (parts_series * prices).fillna(0)
        else:
            # Fallback : dernier cours connu des opérations (constant entre ops)
            local_price = local_price.ffill()
            portfolio_value += (parts_series * local_price).fillna(0)

    return {
        "portfolio_value": portfolio_value,
        "invested_cumul": invested_cumul,
        "parts_history": parts_history,
    }

def build_summary(by_isin, current_prices):
    rows = []
    for isin, v in by_isin.items():
        price_info = current_prices.get(isin)
        price = price_info["price"] if price_info else None
        valo = v["parts"] * price if price is not None else None
        plus_value = (valo - v["investi"]) if valo is not None else None
        pct_pv = (100 * plus_value / v["investi"]) if (plus_value is not None and v["investi"]) else None

        rows.append({
            "ISIN": isin,
            "Nom": v["name"],
            "Parts": v["parts"],
            "Investi (€)": round(v["investi"], 2),
            "Cours actuel (€)": round(price, 4) if price else None,
            "Valorisation (€)": round(valo, 2) if valo else None,
            "Plus-value (€)": round(plus_value, 2) if plus_value is not None else None,
            "Plus-value (%)": round(pct_pv, 1) if pct_pv is not None else None,
            "Nb ops": len(v["ops"]),
        })
    return pd.DataFrame(rows).sort_values("Valorisation (€)", ascending=False) if rows else pd.DataFrame()


