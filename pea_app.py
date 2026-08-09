#!/usr/bin/env python3
"""
Application Streamlit - Suivi PEA + PER + CTO
- PEA  : PDF CIC + saisie manuelle (ACHAT/VENTE)
- PER  : CSV + saisie manuelle
- CTO  : PDF Trade Republic (+ fallback CIC)
- Cours manuels pour OPCVM sans Yahoo
- Graphiques, export, cumul
"""

import re
from collections import defaultdict
from datetime import datetime, timedelta

import streamlit as st
import pdfplumber
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Suivi PEA + PER + CTO",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

YAHOO_TICKERS = {
    "FR0011550185": "ESE.PA",       # BNPP Easy S&P 500
    "FR0011550193": "ETZ.PA",       # BNPP Easy Stoxx Europe 600
    "FR0013412020": "PAEEM.PA",     # Amundi PEA MSCI EM ESG
    "FR0014003IY1": "WLDC.MI",
    "FR0000120073": "AI.PA",        # Air Liquide
    "FR0000051070": "MAU.PA",       # Maurel & Prom
    "IE00B5BMR087": "CSPX.L",       # iShares Core S&P 500
    "IE00BMFKG444": "XNAS.DE",      # Xtrackers Nasdaq 100
    "AU000000EUR7": "PF8.F",        # European Lithium (EUR)
}

COLORS = ["#2E86AB", "#A23B72", "#F18F01", "#C73E1D", "#3B1F2B", "#6A994E", "#457B9D"]

# ─────────────────────────────────────────────
# Utilitaires
# ─────────────────────────────────────────────
def parse_fr_number(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    try:
        return float(str(s).strip().replace(" ", "").replace(",", "."))
    except Exception:
        return None


# ─────────────────────────────────────────────
# Parser CIC (PEA / CTO)
# ─────────────────────────────────────────────
def extract_transaction_from_pdf(pdf_file):
    try:
        with pdfplumber.open(pdf_file) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except Exception:
        return None

    def search(pattern, group=1):
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        return m.group(group) if m else None

    type_op = search(r"Type d'opération\s+(\w+)")
    quantite = search(r"Quantité\s+([\d\s,]+)")
    valeur = search(r"Valeur\s+(.+?)(?:\n|Lieu)")
    isin = search(r"\(([A-Z]{2}[A-Z0-9]{10})\)")
    date_str = search(r"Date et heure d'exécution\s+(\d{2}/\d{2}/\d{4})")
    cours = search(r"Cours d'exécution\s+([\d,]+)\s*EUR")
    solde = search(r"Nouveau solde sur la valeur\s+([\d\s,]+)")

    brut = parse_fr_number(search(r"Brut de l'opération\s+([\d\s,]+)\s*EUR"))
    frais_match = re.search(r"Frais de transaction\s+([\d\s,]+)\s*EUR", text, re.IGNORECASE)
    frais = parse_fr_number(frais_match.group(1)) if frais_match else 0.0

    if brut is not None:
        montant = round(brut + (frais or 0.0), 2)
    else:
        m = re.search(
            r"(?:Débit|Crédit) en date de valeur.*?(\d{1,3}(?:\s\d{3})*(?:,\d+)?)\s*EUR",
            text, re.IGNORECASE | re.DOTALL,
        )
        montant = parse_fr_number(m.group(1)) if m else None

    if not (isin and quantite and date_str and montant is not None):
        return None
    if montant > 100_000:
        return None

    type_op = (type_op or "ACHAT").upper()
    if type_op not in ("ACHAT", "VENTE"):
        type_op = "ACHAT"

    qty = parse_fr_number(quantite)
    if qty is None:
        return None

    return {
        "date": datetime.strptime(date_str, "%d/%m/%Y"),
        "type": type_op,
        "quantite": qty,
        "valeur": re.sub(r"\s+", " ", valeur).strip() if valeur else None,
        "isin": isin,
        "cours": parse_fr_number(cours),
        "solde": parse_fr_number(solde),
        "brut": brut,
        "frais": frais,
        "montant": montant,
        "source": "CIC",
    }


# ─────────────────────────────────────────────
# Parser Trade Republic (CTO)
# ─────────────────────────────────────────────
def extract_transaction_from_traderepublic(pdf_file):
    try:
        with pdfplumber.open(pdf_file) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except Exception:
        return None

    if "TRADE REPUBLIC" not in text.upper() and "CONFIRMATION DE L'INVESTISSEMENT" not in text.upper():
        return None

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # Date
    date = None
    for line in lines:
        m = re.search(r"le\s+(\d{2}/\d{2}/\d{4})", line)
        if m:
            try:
                date = datetime.strptime(m.group(1), "%d/%m/%Y")
                break
            except ValueError:
                pass
        m = re.search(r"DATE\s+(\d{2})\.(\d{2})\.(\d{4})", line, re.IGNORECASE)
        if m:
            try:
                date = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                break
            except ValueError:
                pass
    if date is None:
        return None

    # Ligne données + ISIN
    nom, quantite, cours, montant_brut, isin = None, None, None, None, None
    for i, line in enumerate(lines):
        isin_match = re.search(r"ISIN\s*[:\s]*([A-Z]{2}[A-Z0-9]{10})", line, re.IGNORECASE)
        if isin_match:
            isin = isin_match.group(1).upper()
            if i > 0:
                prev = lines[i - 1]
                m = re.search(r"^(.+)\s+([\d,]+)\s+([\d,]+)\s*EUR\s+([\d,]+)\s*EUR$", prev)
                if m:
                    nom = m.group(1).strip()
                    quantite = parse_fr_number(m.group(2))
                    cours = parse_fr_number(m.group(3))
                    montant_brut = parse_fr_number(m.group(4))
            break

    if not isin or quantite is None or quantite <= 0:
        return None

    # TTF
    ttf = 0.0
    for line in lines:
        m = re.search(r"Taxe sur les transactions financières\s*-?([\d,]+)\s*EUR", line, re.IGNORECASE)
        if m:
            ttf = parse_fr_number(m.group(1)) or 0.0
            break

    # Total débité
    total = None
    for line in lines:
        m = re.search(r"TOTAL\s+(-[\d,]+)\s*EUR", line, re.IGNORECASE)
        if m:
            total = abs(parse_fr_number(m.group(1)) or 0)
            break
    if total is None:
        for line in lines:
            m = re.search(r"TOTAL\s+([\d,]+)\s*EUR", line, re.IGNORECASE)
            if m:
                total = parse_fr_number(m.group(1))
                break

    if total is not None:
        montant = total
    elif montant_brut is not None:
        montant = round(montant_brut + ttf, 2)
    else:
        return None

    return {
        "date": date,
        "type": "ACHAT",
        "quantite": quantite,
        "valeur": nom or isin,
        "isin": isin,
        "cours": cours,
        "solde": None,
        "brut": montant_brut,
        "frais": ttf,
        "montant": montant,
        "source": "Trade Republic",
    }


# ─────────────────────────────────────────────
# CSV PER
# ─────────────────────────────────────────────
def parse_csv_transactions(uploaded_file) -> list:
    try:
        df = pd.read_csv(uploaded_file, sep=None, engine="python")
    except Exception:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file, sep=";", encoding="utf-8")

    df.columns = [str(c).strip().lower() for c in df.columns]
    if not {"date", "quantite", "isin"}.issubset(set(df.columns)):
        st.error("Colonnes obligatoires manquantes : date, quantite, isin")
        return []

    transactions = []
    for _, row in df.iterrows():
        try:
            date_val = row["date"]
            if isinstance(date_val, str):
                for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
                    try:
                        date = datetime.strptime(date_val.strip(), fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue
            else:
                date = pd.to_datetime(date_val).to_pydatetime()

            quantite = float(row["quantite"])
            isin = str(row["isin"]).strip().upper()
            nom = str(row.get("nom", "") or "").strip() or None
            cours = parse_fr_number(row.get("cours"))
            frais = parse_fr_number(row.get("frais")) or 0.0
            montant = parse_fr_number(row.get("debit") or row.get("montant"))
            if montant is None and cours is not None:
                montant = round(quantite * cours + frais, 2)
            if montant is None or quantite <= 0:
                continue

            typ = str(row.get("type", "ACHAT")).strip().upper()
            if typ not in ("ACHAT", "VENTE"):
                typ = "ACHAT"

            transactions.append({
                "date": date,
                "type": typ,
                "quantite": quantite,
                "valeur": nom,
                "isin": isin,
                "cours": cours,
                "solde": None,
                "brut": round(quantite * cours, 2) if cours else None,
                "frais": frais,
                "montant": montant,
                "source": "CSV",
            })
        except Exception:
            continue
    return transactions


# ─────────────────────────────────────────────
# Traitement commun (ACHAT / VENTE + float)
# ─────────────────────────────────────────────
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

        if typ == "ACHAT":
            by_isin[isin]["parts"] += qty
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


@st.cache_data(ttl=3600, show_spinner=False)
def get_current_prices(isins: tuple):
    prices = {}
    for isin in isins:
        ticker = YAHOO_TICKERS.get(isin)
        if not ticker:
            prices[isin] = None
            continue
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if not hist.empty:
                prices[isin] = {
                    "price": float(hist["Close"].iloc[-1]),
                    "date": hist.index[-1].date(),
                }
            else:
                prices[isin] = None
        except Exception:
            prices[isin] = None
    return prices


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def get_historical_prices(ticker: str, start: datetime, end: datetime):
    try:
        hist = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
        )
        if hist.empty:
            return pd.Series(dtype=float)
        s = hist["Close"].copy()
        s.index = s.index.tz_localize(None)
        return s
    except Exception:
        return pd.Series(dtype=float)


def build_history(by_isin: dict, transactions: list) -> dict:
    if not transactions:
        return {"portfolio_value": pd.Series(dtype=float), "invested_cumul": pd.Series(dtype=float), "parts_history": {}}

    start_date = min(t["date"] for t in transactions) - timedelta(days=3)
    end_date = datetime.now()
    all_dates = pd.date_range(start=start_date, end=end_date, freq="B")

    portfolio_value = pd.Series(0.0, index=all_dates)
    invested_cumul = pd.Series(0.0, index=all_dates)
    parts_history = {}

    for isin, v in by_isin.items():
        ticker = YAHOO_TICKERS.get(isin)
        if not ticker:
            continue
        prices = get_historical_prices(ticker, start_date, end_date)
        if prices.empty:
            continue

        parts_series = pd.Series(0.0, index=all_dates)
        cost_series = pd.Series(0.0, index=all_dates)
        running_parts = 0.0
        running_cost = 0.0

        for op in sorted(v["ops"], key=lambda x: x["date"]):
            qty = float(op["quantite"])
            montant = op.get("montant") or op.get("debit") or 0.0
            typ = op.get("type", "ACHAT").upper()

            if typ == "ACHAT":
                running_parts += qty
                running_cost += montant
            elif typ == "VENTE" and running_parts > 0:
                cout_unitaire = running_cost / running_parts
                running_cost = max(0.0, running_cost - cout_unitaire * qty)
                running_parts = max(0.0, running_parts - qty)

            mask = parts_series.index >= op["date"]
            parts_series.loc[mask] = running_parts
            cost_series.loc[mask] = running_cost

        prices = prices.reindex(all_dates).ffill()
        portfolio_value += (parts_series * prices).fillna(0)
        invested_cumul += cost_series
        parts_history[isin] = parts_series

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


# ─────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────
for key in ("pea_manual", "per_manual", "manual_prices", "histories"):
    if key not in st.session_state:
        st.session_state[key] = [] if key.endswith("manual") else {}

# ─────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────
st.title("📈 Suivi PEA + PER + CTO")

with st.sidebar:
    st.header("📂 Import")

    # —— PEA ——
    st.subheader("PEA (PDF CIC)")
    pea_files = st.file_uploader("Avis d'opération PEA", type=["pdf"], accept_multiple_files=True, key="pea")

    with st.expander("➕ Ajouter opération PEA manuellement"):
        with st.form("manual_pea_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                p_date = st.date_input("Date", value=datetime.now(), key="pea_date")
                p_type = st.selectbox("Type", ["ACHAT", "VENTE"], key="pea_type")
                p_quantite = st.number_input("Quantité", min_value=0.0, step=0.001, format="%.4f", value=1.0, key="pea_qty")
                p_isin = st.text_input("ISIN", key="pea_isin")
            with c2:
                p_nom = st.text_input("Nom (optionnel)", key="pea_nom")
                p_cours = st.number_input("Cours (€)", min_value=0.0, format="%.4f", key="pea_cours")
                p_frais = st.number_input("Frais (€)", min_value=0.0, format="%.2f", key="pea_frais")
            if st.form_submit_button("Ajouter"):
                if p_isin and p_cours > 0 and p_quantite > 0:
                    q, c, f = float(p_quantite), float(p_cours), float(p_frais)
                    montant = round(q * c + f, 2)
                    st.session_state["pea_manual"].append({
                        "date": datetime.combine(p_date, datetime.min.time()),
                        "type": p_type,
                        "quantite": q,
                        "valeur": p_nom.strip() or p_isin.strip().upper(),
                        "isin": p_isin.strip().upper(),
                        "cours": c,
                        "solde": None,
                        "brut": round(q * c, 2),
                        "frais": f,
                        "montant": montant,
                        "source": "Manuel PEA",
                    })
                    st.success(f"{p_type} PEA ajouté")
                else:
                    st.error("ISIN, Quantité et Cours obligatoires")

    if st.session_state["pea_manual"]:
        st.caption(f"{len(st.session_state['pea_manual'])} op. PEA manuelle(s)")
        if st.button("🗑️ Vider PEA manuelles"):
            st.session_state["pea_manual"] = []
            st.rerun()

    # —— CTO ——
    st.subheader("CTO (Trade Republic / CIC)")
    cto_files = st.file_uploader("Avis d'opération CTO", type=["pdf"], accept_multiple_files=True, key="cto")

    # —— PER ——
    st.subheader("PER")
    per_csv = st.file_uploader("CSV opérations PER", type=["csv"], key="per_csv")

    with st.expander("➕ Ajouter opération PER manuellement"):
        with st.form("manual_per_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                m_date = st.date_input("Date", value=datetime.now(), key="per_date")
                m_type = st.selectbox("Type", ["ACHAT", "VENTE"], key="per_type")
                m_quantite = st.number_input("Quantité", min_value=0.0, step=0.001, format="%.4f", value=1.0, key="per_qty")
                m_isin = st.text_input("ISIN", key="per_isin")
            with c2:
                m_nom = st.text_input("Nom (optionnel)", key="per_nom")
                m_cours = st.number_input("Cours (€)", min_value=0.0, format="%.4f", key="per_cours")
                m_frais = st.number_input("Frais (€)", min_value=0.0, format="%.2f", key="per_frais")
            if st.form_submit_button("Ajouter"):
                if m_isin and m_cours > 0 and m_quantite > 0:
                    q, c, f = float(m_quantite), float(m_cours), float(m_frais)
                    montant = round(q * c + f, 2)
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
                        "montant": montant,
                        "source": "Manuel PER",
                    })
                    st.success(f"{m_type} PER ajouté")
                else:
                    st.error("ISIN, Quantité et Cours obligatoires")

    if st.session_state["per_manual"]:
        st.caption(f"{len(st.session_state['per_manual'])} op. PER manuelle(s)")
        if st.button("🗑️ Vider PER manuelles"):
            st.session_state["per_manual"] = []
            st.rerun()

    # —— Cours manuels OPCVM ——
    st.subheader("Cours manuels (OPCVM)")
    with st.expander("Forcer un cours par ISIN"):
        force_isin = st.text_input("ISIN", key="force_isin")
        force_cours = st.number_input("Cours (€)", min_value=0.0, format="%.4f", key="force_cours")
        if st.button("Enregistrer le cours") and force_isin and force_cours > 0:
            st.session_state["manual_prices"][force_isin.strip().upper()] = float(force_cours)
            st.success(f"{force_isin} → {force_cours:.4f} €")

    if st.session_state["manual_prices"]:
        for isin, px in st.session_state["manual_prices"].items():
            st.text(f"{isin} : {px:.4f} €")
        if st.button("Vider les cours manuels"):
            st.session_state["manual_prices"] = {}
            st.rerun()

    mode = st.radio(
        "Mode d'affichage",
        ["PEA", "PER", "CTO", "Cumul PEA + PER", "Cumul total (PEA+PER+CTO)"],
    )

    st.markdown("---")
    st.markdown("**Modèle CSV PER**")
    st.code(
        "date,quantite,isin,nom,cours,frais,montant,type\n"
        "15/03/2026,20.5,FR0011550185,BNPP Easy S&P 500,31.50,2.50,648.25,ACHAT",
        language=None,
    )

# ─────────────────────────────────────────────
# Traitement
# ─────────────────────────────────────────────
try:
    # PEA
    pea_transactions = []
    if pea_files:
        for f in pea_files:
            tx = extract_transaction_from_pdf(f)
            if tx:
                pea_transactions.append(tx)
    pea_transactions.extend(st.session_state["pea_manual"])
    pea_df, pea_by_isin = process_transactions(pea_transactions)

    # CTO
    cto_transactions = []
    if cto_files:
        for f in cto_files:
            tx = extract_transaction_from_traderepublic(f)
            if tx is None:
                tx = extract_transaction_from_pdf(f)
            if tx:
                cto_transactions.append(tx)
    cto_df, cto_by_isin = process_transactions(cto_transactions)

    # PER
    per_transactions = []
    if per_csv is not None:
        per_transactions.extend(parse_csv_transactions(per_csv))
    per_transactions.extend(st.session_state["per_manual"])
    per_df, per_by_isin = process_transactions(per_transactions)

    # Mode
    if mode == "PEA":
        transactions, df, by_isin = pea_transactions, pea_df, pea_by_isin
        key = f"pea_{len(pea_transactions)}"
    elif mode == "PER":
        transactions, df, by_isin = per_transactions, per_df, per_by_isin
        key = f"per_{len(per_transactions)}"
    elif mode == "CTO":
        transactions, df, by_isin = cto_transactions, cto_df, cto_by_isin
        key = f"cto_{len(cto_transactions)}"
    elif mode == "Cumul PEA + PER":
        transactions = pea_transactions + per_transactions
        df, by_isin = process_transactions(transactions)
        key = f"pea_per_{len(pea_transactions)}_{len(per_transactions)}"
    else:
        transactions = pea_transactions + per_transactions + cto_transactions
        df, by_isin = process_transactions(transactions)
        key = f"total_{len(pea_transactions)}_{len(per_transactions)}_{len(cto_transactions)}"

    if not transactions:
        st.warning("Aucune opération chargée.")
        st.info("Dépose des PDF PEA/CTO, un CSV PER, ou utilise la saisie manuelle.")
        st.stop()

    # Valorisation
    isins = tuple(by_isin.keys())
    current_prices = get_current_prices(isins)

    # Cours manuels prioritaires
    for isin, px in st.session_state.get("manual_prices", {}).items():
        current_prices[isin] = {"price": px, "date": datetime.now().date()}

    summary_df = build_summary(by_isin, current_prices)

    total_investi = summary_df["Investi (€)"].sum() if not summary_df.empty else 0
    total_valo = summary_df["Valorisation (€)"].sum() if not summary_df.empty else 0
    total_pv = total_valo - total_investi
    total_pct = 100 * total_pv / total_investi if total_investi else 0

    # Historique
    if key not in st.session_state["histories"]:
        with st.spinner("Calcul de l'historique..."):
            st.session_state["histories"][key] = build_history(by_isin, transactions)

    hist = st.session_state["histories"][key]
    portfolio_value = hist["portfolio_value"]
    invested_cumul = hist["invested_cumul"]
    parts_history = hist["parts_history"]

    # Affichage
    st.subheader(f"Portefeuille : {mode}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Capital investi", f"{total_investi:,.2f} €")
    c2.metric("Valorisation", f"{total_valo:,.2f} €")
    c3.metric("Plus-value", f"{total_pv:+,.2f} €", f"{total_pct:+.1f}%")
    c4.metric("Opérations", len(transactions))

    st.markdown("---")

    tab1, tab2, tab3, tab4 = st.tabs(["📊 Synthèse", "📋 Opérations", "📈 Évolution", "💾 Export"])

    with tab1:
        if not summary_df.empty:
            valo = pd.to_numeric(summary_df["Valorisation (€)"], errors="coerce").fillna(0)
            investi = pd.to_numeric(summary_df["Investi (€)"], errors="coerce").fillna(0)
            labels = summary_df["Nom"].astype(str).str[:25]
            mask_valo = valo > 0
            mask_investi = investi > 0

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Répartition valorisation**")
                if mask_valo.any():
                    fig, ax = plt.subplots(figsize=(6, 5))
                    ax.pie(valo[mask_valo], labels=labels[mask_valo], autopct="%1.1f%%",
                           colors=COLORS[:mask_valo.sum()], startangle=90)
                    ax.set_title(f"Total : {valo.sum():,.0f} €")
                    st.pyplot(fig)
                    plt.close()
            with col2:
                st.markdown("**Répartition investi**")
                if mask_investi.any():
                    fig, ax = plt.subplots(figsize=(6, 5))
                    ax.pie(investi[mask_investi], labels=labels[mask_investi], autopct="%1.1f%%",
                           colors=COLORS[:mask_investi.sum()], startangle=90)
                    ax.set_title(f"Total : {investi.sum():,.0f} €")
                    st.pyplot(fig)
                    plt.close()

            st.dataframe(
                summary_df.style.format({
                    "Parts": "{:.4f}",
                    "Investi (€)": "{:,.2f}",
                    "Cours actuel (€)": "{:.4f}",
                    "Valorisation (€)": "{:,.2f}",
                    "Plus-value (€)": "{:+,.2f}",
                    "Plus-value (%)": "{:+.1f}",
                }, na_rep="-"),
                use_container_width=True,
                hide_index=True,
            )

    with tab2:
        if not df.empty:
            display_cols = ["date_str", "type", "quantite", "isin", "valeur", "cours", "montant", "frais", "solde", "source"]
            display_cols = [c for c in display_cols if c in df.columns]
            st.dataframe(
                df[display_cols].rename(columns={
                    "date_str": "Date", "type": "Type", "quantite": "Quantité",
                    "isin": "ISIN", "valeur": "Valeur", "cours": "Cours (€)",
                    "montant": "Montant (€)", "frais": "Frais (€)",
                    "solde": "Solde", "source": "Source",
                }),
                use_container_width=True,
                hide_index=True,
            )

    with tab3:
        if not portfolio_value.empty:
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(portfolio_value.index, portfolio_value, label="Valorisation", color="#2E86AB", lw=2)
            ax.plot(invested_cumul.index, invested_cumul, label="Investi", color="#A23B72", ls="--")
            ax.legend()
            ax.set_ylabel("€")
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
            st.pyplot(fig)
            plt.close()

            if parts_history:
                fig, ax = plt.subplots(figsize=(10, 4))
                for i, (isin, s) in enumerate(parts_history.items()):
                    ax.plot(s.index, s, label=by_isin[isin]["name"][:25], color=COLORS[i % len(COLORS)])
                ax.legend()
                ax.set_ylabel("Parts")
                st.pyplot(fig)
                plt.close()

    with tab4:
        if not summary_df.empty:
            st.download_button(
                "Télécharger synthèse CSV",
                summary_df.to_csv(index=False).encode("utf-8-sig"),
                f"synthese_{mode.replace(' ', '_')}.csv",
                "text/csv",
            )

except Exception as e:
    st.error("Une erreur est survenue :")
    st.exception(e)