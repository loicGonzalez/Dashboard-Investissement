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
        # Flux cash purs (liquidité) : pas de ligne titre
        if t.get("kind") == "cash" or t.get("type", "").upper() in (
            "VERSEMENT", "RETRAIT", "OUVERTURE", "REGULARISATION"
        ):
            if not t.get("isin"):
                continue
        isin = t.get("isin")
        if not isin:
            continue
        qty = float(t.get("quantite") or 0)
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
    """
    Trésorerie + apports.

    Si des flux kind=cash (CSV liquidité) sont présents :
      - apports = VERSEMENT − RETRAIT
      - cash = journal complet liquidité (VERSEMENT/CASH_IN − RETRAIT/CASH_OUT)
        sans rejouer les ACHAT/VENTE titres (évite le double comptage).

    Sinon (pas de liquidité) :
      - estimation classique via déficit de cash sur les ACHAT.
    """
    ops = sorted(transactions, key=lambda x: x["date"])
    cash = 0.0
    apports_estimes = 0.0
    apports_liquidite = 0.0
    has_liquidite = False
    total_achats = 0.0
    total_ventes = 0.0

    for op in ops:
        if op.get("kind") == "cash":
            has_liquidite = True
            break

    for op in ops:
        montant = float(op.get("montant") or 0.0)
        typ = op.get("type", "ACHAT").upper()
        no_cash = bool(op.get("no_cash"))
        kind = op.get("kind") or ""

        if kind == "cash":
            if typ == "VERSEMENT":
                apports_liquidite += montant
                cash += montant
            elif typ == "RETRAIT":
                apports_liquidite -= montant
                cash -= montant
            elif typ == "CASH_IN":
                cash += montant
            elif typ == "CASH_OUT":
                cash -= montant
            continue

        # Sans journal liquidité : simuler via ordres titres
        if has_liquidite:
            # compta achats/ventes stats only
            if typ == "ACHAT":
                total_achats += montant
            elif typ == "VENTE" and not no_cash:
                total_ventes += montant
            continue

        if typ == "ACHAT":
            total_achats += montant
            cash -= montant
            if cash < -1e-9:
                apports_estimes += -cash
                cash = 0.0
        elif typ == "BONUS":
            pass
        elif typ == "VENTE":
            if not no_cash:
                total_ventes += montant
                cash += montant

    apports = apports_liquidite if has_liquidite else apports_estimes
    return {
        "apports": round(apports, 2),
        "apports_source": "liquidite" if has_liquidite else "estime",
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
        raw = YAHOO_TICKERS.get(isin)
        tickers = [raw] if isinstance(raw, str) else list(raw or [])
        prices = pd.Series(dtype=float)
        for ticker in tickers:
            prices = get_historical_prices(ticker, start_date, end_date)
            if not prices.empty:
                break

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



def performance_periods(portfolio_value, invested_cumul=None) -> list[dict]:
    """
    Performance hors apports (approx.) :

        Δ marché = (Valo_fin − Valo_début) − (Investi_fin − Investi_début)
        Perf %   = Δ marché / Valo_début

    Ainsi un versement augmente valo et investi : la perf marché n'est pas
    gonflée artificiellement. Ce n'est pas un TRI exact, mais cohérent pour
    1j / 1s / 1m / YTD / depuis le début.
    """
    periods = [
        ("1 jour", 1),
        ("1 semaine", 7),
        ("1 mois", 30),
        ("Year to date", "ytd"),
        ("Depuis le début", "all"),
    ]
    empty = [
        {"label": lab, "delta_eur": None, "delta_pct": None, "available": False}
        for lab, _ in periods
    ]
    if portfolio_value is None or getattr(portfolio_value, "empty", True):
        return empty

    s = portfolio_value.dropna().sort_index()
    if s.empty:
        return empty

    inv = None
    if invested_cumul is not None and not getattr(invested_cumul, "empty", True):
        inv = invested_cumul.reindex(s.index).ffill().bfill()

    end = s.index.max()
    end_valo = float(s.iloc[-1])
    end_inv = float(inv.iloc[-1]) if inv is not None else None

    def _at_or_before(series, ts):
        sub = series[series.index <= ts]
        if sub.empty:
            return None
        return float(sub.iloc[-1])

    out = []
    for label, spec in periods:
        if spec == "all":
            nonzero = s[s > 0]
            start_ts = nonzero.index[0] if not nonzero.empty else s.index[0]
            start_valo = float(s.loc[start_ts]) if start_ts in s.index else float(s.iloc[0])
            # align: first common point
            start_valo = float(s.iloc[0]) if nonzero.empty else float(nonzero.iloc[0])
            start_inv = float(inv.iloc[0]) if inv is not None else None
            if inv is not None and not nonzero.empty:
                start_inv = float(inv.reindex(s.index).ffill().loc[nonzero.index[0]])
        elif spec == "ytd":
            ytd_start = pd.Timestamp(year=int(end.year), month=1, day=1)
            start_valo = _at_or_before(s, ytd_start)
            if start_valo is None:
                sub = s[s.index >= ytd_start]
                if sub.empty:
                    out.append({"label": label, "delta_eur": None, "delta_pct": None, "available": False})
                    continue
                start_valo = float(sub.iloc[0])
                ytd_start = sub.index[0]
            start_inv = _at_or_before(inv, ytd_start) if inv is not None else None
        else:
            target = end - pd.Timedelta(days=int(spec))
            start_valo = _at_or_before(s, target)
            start_inv = _at_or_before(inv, target) if inv is not None else None

        if start_valo is None:
            out.append({"label": label, "delta_eur": None, "delta_pct": None, "available": False})
            continue

        # Variation brute de valo
        delta_valo = end_valo - start_valo
        # Variation de l'investi (apports nets estimés sur la période)
        if end_inv is not None and start_inv is not None:
            delta_investi = end_inv - start_inv
            delta_marche = delta_valo - delta_investi
        else:
            # sans courbe investi : retombe sur variation brute (moins fiable)
            delta_marche = delta_valo

        if abs(start_valo) < 1e-9:
            out.append({"label": label, "delta_eur": None, "delta_pct": None, "available": False})
            continue

        pct = 100.0 * delta_marche / start_valo
        out.append({
            "label": label,
            "delta_eur": round(delta_marche, 2),
            "delta_pct": round(pct, 2),
            "available": True,
            "start_val": round(start_valo, 2),
            "end_val": round(end_valo, 2),
            "delta_apports": round((end_inv - start_inv), 2) if (end_inv is not None and start_inv is not None) else None,
        })
    return out


def render_performance_cards(portfolio_value, invested_cumul=None):
    """Affiche les cartes de performance (Streamlit)."""
    import streamlit as st
    from core.style import kpi_card, fmt_eur

    rows = performance_periods(portfolio_value, invested_cumul)
    cols = st.columns(len(rows))
    for col, row in zip(cols, rows):
        if not row["available"]:
            kpi_card(col, row["label"], "—", sub="données insuffisantes")
            continue
        kpi_card(
            col,
            row["label"],
            fmt_eur(row["delta_eur"], signed=True),
            delta=f'{row["delta_pct"]:+.2f}%',
            positive=row["delta_eur"] >= 0,
        )



def render_performance_cards(portfolio_value):
    """Affiche les cartes de performance (à appeler depuis Streamlit)."""
    import streamlit as st
    from core.style import kpi_card, fmt_eur

    rows = performance_periods(portfolio_value)
    cols = st.columns(len(rows))
    for col, row in zip(cols, rows):
        if not row["available"]:
            kpi_card(col, row["label"], "—", sub="données insuffisantes")
            continue
        d_eur = row["delta_eur"]
        d_pct = row["delta_pct"]
        positive = d_eur >= 0
        kpi_card(
            col,
            row["label"],
            fmt_eur(d_eur, signed=True),
            delta=f"{d_pct:+.2f}%",
            positive=positive,
        )
