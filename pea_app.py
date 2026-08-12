#!/usr/bin/env python3
"""
Application Streamlit - Suivi PEA + PER + CTO
- PEA  : PDF CIC + CSV (ACHAT/VENTE)
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
    "IE00B5BMR087": "SXR8.DE",      # iShares Core S&P 500 Acc (EUR, Xetra)
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
        t = str(s).strip().replace(" ", "").replace("\u00a0", "")
        # "1.716,90" (FR) ou "1,716.90" (US) ou "1716.90"
        if t.count(",") == 1 and t.count(".") >= 1:
            if t.rfind(",") > t.rfind("."):
                t = t.replace(".", "").replace(",", ".")  # FR
            else:
                t = t.replace(",", "")  # US thousands
        elif t.count(",") == 1 and t.count(".") == 0:
            t = t.replace(",", ".")
        else:
            t = t.replace(",", "")
        return float(t)
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

    # ISIN
    isin = None
    isin_line_idx = None
    for i, line in enumerate(lines):
        m = re.search(r"ISIN\s*[:\s]*([A-Z]{2}[A-Z0-9]{10})", line, re.IGNORECASE)
        if m:
            isin = m.group(1).upper()
            isin_line_idx = i
            break
    if not isin:
        return None

    # Ligne données : nom + quantité + cours + montant (juste avant ISIN)
    # Ex: "Air Liquide 0,056753 176,20 EUR 10,00 EUR"
    # Ex: "Core S&P 500 USD (Acc) 0,0816 612,74 EUR 50,00 EUR"
    nom, quantite, cours, montant_brut = None, None, None, None
    search_lines = []
    if isin_line_idx is not None and isin_line_idx > 0:
        search_lines.append(lines[isin_line_idx - 1])
    # aussi chercher dans toutes les lignes POSITION
    for line in lines:
        if re.search(r"\d+,\d+\s+\d+[.,]\d+\s*EUR\s+\d+[.,]\d+\s*EUR", line):
            search_lines.append(line)

    for prev in search_lines:
        # Quantité peut avoir beaucoup de décimales (0,056753)
        m = re.search(
            r"^(.+?)\s+(\d+,\d+|\d+\.\d+|\d+)\s+(\d+[.,]\d+)\s*EUR\s+(\d+[.,]\d+)\s*EUR\s*$",
            prev,
        )
        if m:
            nom = m.group(1).strip()
            quantite = parse_fr_number(m.group(2))
            cours = parse_fr_number(m.group(3))
            montant_brut = parse_fr_number(m.group(4))
            if quantite and quantite > 0:
                break

    if not quantite or quantite <= 0:
        return None

    # TTF / frais
    ttf = 0.0
    for line in lines:
        m = re.search(
            r"Taxe sur les transactions financières\s*-?([\d,]+)\s*EUR",
            line,
            re.IGNORECASE,
        )
        if m:
            ttf = parse_fr_number(m.group(1)) or 0.0
            break

    # Total débité (prioritaire)
    total = None
    for line in lines:
        m = re.search(r"TOTAL\s+(-[\d,]+)\s*EUR", line, re.IGNORECASE)
        if m:
            total = abs(parse_fr_number(m.group(1)) or 0)
            break
    if total is None:
        for line in lines:
            # ligne "TOTAL -10,04 EUR" déjà couverte ; sinon TOTAL positif
            m = re.search(r"^TOTAL\s+([\d,]+)\s*EUR", line, re.IGNORECASE)
            if m:
                total = parse_fr_number(m.group(1))
                break

    if total is not None and total > 0:
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
        "kind": "uc",
    }



def parse_csv_transactions(uploaded_file) -> list:
    """Parse CSV UC/ETF (ACHAT/VENTE) et fonds euros (VERSEMENT/RETRAIT/INTERETS)."""
    try:
        df = pd.read_csv(uploaded_file, sep=None, engine="python", encoding="utf-8-sig")
    except Exception:
        uploaded_file.seek(0)
        try:
            df = pd.read_csv(uploaded_file, sep=";", encoding="utf-8-sig")
        except Exception:
            uploaded_file.seek(0)
            df = pd.read_csv(uploaded_file, sep=",", encoding="utf-8")

    df.columns = [str(c).replace("\ufeff", "").strip().lower() for c in df.columns]

    if "debit" in df.columns and "montant" not in df.columns:
        df = df.rename(columns={"debit": "montant"})

    if "date" not in df.columns:
        st.error(f"Colonne date manquante. Colonnes: {list(df.columns)}")
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

            typ = str(row.get("type", "ACHAT") or "ACHAT").strip().upper()
            nom = str(row.get("nom", "") or "").strip() or None
            isin_raw = row.get("isin", "")
            isin = (
                str(isin_raw).strip().upper()
                if pd.notna(isin_raw) and str(isin_raw).strip()
                else None
            )
            cours = parse_fr_number(row.get("cours"))
            frais = parse_fr_number(row.get("frais")) or 0.0
            montant = parse_fr_number(row.get("montant") if "montant" in row.index else None)
            if montant is None:
                montant = parse_fr_number(row.get("debit") if "debit" in row.index else None)
            quantite = parse_fr_number(row.get("quantite") if "quantite" in row.index else None)

            # Fonds euros
            if typ in ("VERSEMENT", "RETRAIT", "INTERETS", "FRAIS_FE"):
                if montant is None or montant <= 0:
                    continue
                fid = isin or (
                    "FE_" + "".join(ch for ch in (nom or "DEFAULT").upper() if ch.isalnum())[:20]
                )
                transactions.append({
                    "date": date,
                    "type": typ,
                    "quantite": None,
                    "valeur": nom or "Fonds euros",
                    "isin": fid,
                    "cours": None,
                    "solde": None,
                    "brut": None,
                    "frais": frais,
                    "montant": montant,
                    "source": "CSV",
                    "kind": "fonds_euros",
                    "no_cash": typ == "FRAIS_FE",
                })
                continue

            # Frais UC = vente sans cash
            no_cash = False
            if typ == "FRAIS":
                typ = "VENTE"
                no_cash = True

            if typ not in ("ACHAT", "VENTE"):
                typ = "ACHAT"

            if quantite is None or quantite <= 0:
                continue
            if montant is None and cours is not None:
                montant = round(quantite * cours + frais, 2)
            if montant is None:
                continue

            if not isin:
                isin = "ID_" + "".join(ch for ch in (nom or "UNKNOWN").upper() if ch.isalnum())[:14]

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
                "kind": "uc",
                "no_cash": no_cash,
            })
        except Exception:
            continue
    return transactions


def split_uc_and_fe(transactions: list):
    uc = [t for t in transactions if t.get("kind") != "fonds_euros"]
    fe = [t for t in transactions if t.get("kind") == "fonds_euros"]
    return uc, fe


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




def apply_price_fallbacks(by_isin, current_prices, manual_prices):
    """Priorité : manuel > Yahoo > dernier cours des opérations."""
    prices = dict(current_prices)
    for isin, px in (manual_prices or {}).items():
        prices[isin] = {"price": float(px), "date": datetime.now().date()}
    for isin, v in by_isin.items():
        if prices.get(isin) is not None:
            continue
        for op in reversed(sorted(v["ops"], key=lambda x: x["date"])):
            if op.get("cours"):
                d = op["date"]
                prices[isin] = {
                    "price": float(op["cours"]),
                    "date": d.date() if hasattr(d, "date") else d,
                }
                break
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
for key, default in (
    ("per_manual", []),
    ("manual_prices", {}),
    ("histories", {}),
):
    if key not in st.session_state:
        st.session_state[key] = default

# ─────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────
st.title("📈 Suivi PEA + PER + CTO")

with st.sidebar:
    st.header("📂 Import")

    # —— PEA ——
    st.subheader("PEA")
    pea_files = st.file_uploader(
        "Avis d'opération PEA (PDF CIC)", type=["pdf"], accept_multiple_files=True, key="pea"
    )
    pea_csv = st.file_uploader("CSV opérations PEA", type=["csv"], key="pea_csv")

    # —— CTO ——
    st.subheader("CTO (Trade Republic / CIC)")
    cto_files = st.file_uploader(
        "Avis d'opération CTO", type=["pdf"], accept_multiple_files=True, key="cto"
    )

    # —— PER ——
    st.subheader("PER")
    per_csv = st.file_uploader("CSV opérations PER", type=["csv"], key="per_csv")

    with st.expander("➕ Ajouter opération PER manuellement"):
        with st.form("manual_per_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                m_date = st.date_input("Date", value=datetime.now(), key="per_date")
                m_type = st.selectbox("Type", ["ACHAT", "VENTE"], key="per_type")
                m_quantite = st.number_input(
                    "Quantité", min_value=0.0, step=0.001, format="%.4f", value=1.0, key="per_qty"
                )
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
    st.markdown("**Modèle CSV PEA / PER**")
    st.code(
        "date,type,quantite,isin,nom,cours,frais,montant\n"
        "01/11/2025,ACHAT,0.100484,,CM-AM ACTIONS MONDE RC,345.33,0,34.70\n"
        "01/11/2025,VERSEMENT,,,Euro Retraite,,,40.00\n"
        "15/06/2026,VENTE,0.100484,,CM-AM ACTIONS MONDE RC,360.00,0,36.17\n"
        "18/07/2026,ACHAT,92.1281,FR0014003IY1,AMUNDI MSCI WORLD II,18.636,0,1716.90",
        language=None,
    )
    st.caption(
        "Types : ACHAT / VENTE / FRAIS (UC) · VERSEMENT / RETRAIT / INTERETS / FRAIS_FE (fonds euros). "
        "ISIN optionnel pour les OPCVM non cotés."
    )

# ─────────────────────────────────────────────
# Traitement
# ─────────────────────────────────────────────
try:
    # PEA (PDF + CSV)
    pea_transactions = []
    if pea_files:
        for f in pea_files:
            tx = extract_transaction_from_pdf(f)
            if tx:
                pea_transactions.append(tx)
    if pea_csv is not None:
        pea_transactions.extend(parse_csv_transactions(pea_csv))
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

    per_fe_by_id = {}

    # PER (UC/ETF + fonds euros)
    per_raw = []
    if per_csv is not None:
        per_raw.extend(parse_csv_transactions(per_csv))
    # saisie manuelle = UC
    for m in st.session_state["per_manual"]:
        m = dict(m)
        m.setdefault("kind", "uc")
        per_raw.append(m)
    per_uc, per_fe_ops = split_uc_and_fe(per_raw)
    per_df, per_by_isin = process_transactions(per_uc)
    per_fe_by_id = process_fonds_euros(per_fe_ops)
    per_transactions = per_uc  # pour historique UC

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
        st.info("Dépose des PDF PEA/CTO, un CSV PEA/PER, ou utilise la saisie manuelle PER.")
        st.stop()

    # Valorisation
    isins = tuple(by_isin.keys())
    current_prices = get_current_prices(isins)
    current_prices = apply_price_fallbacks(
        by_isin, current_prices, st.session_state.get("manual_prices", {})
    )

    summary_df = build_summary(by_isin, current_prices)
    open_df = summary_df[summary_df["Parts"] > 1e-9] if not summary_df.empty else summary_df
    sold_df = summary_df[summary_df["Parts"] <= 1e-9] if not summary_df.empty else pd.DataFrame()

    flow = compute_cash_and_contributions(transactions)

    # Fonds euros (PER uniquement, ou cumul si on affiche PER)
    fe_by_id = {}
    if mode in ("PER", "Cumul PEA + PER", "Cumul total (PEA+PER+CTO)"):
        fe_by_id = per_fe_by_id
    fe_apports = sum(v["apports"] for v in fe_by_id.values()) if fe_by_id else 0.0
    fe_valo = sum(v["valo"] for v in fe_by_id.values()) if fe_by_id else 0.0
    fe_interets = sum(v["interets"] for v in fe_by_id.values()) if fe_by_id else 0.0

    investi_ouvert = float(open_df["Investi (€)"].sum()) if not open_df.empty else 0.0
    valo_titres = float(open_df["Valorisation (€)"].sum()) if not open_df.empty else 0.0
    if pd.isna(investi_ouvert):
        investi_ouvert = 0.0
    if pd.isna(valo_titres):
        valo_titres = 0.0

    apports_total = flow["apports"] + fe_apports
    patrimoine = valo_titres + flow["cash"] + fe_valo
    pv_totale = patrimoine - apports_total
    pct_totale = 100 * pv_totale / apports_total if apports_total else 0.0

    total_investi = apports_total
    total_valo = patrimoine
    total_pv = pv_totale
    total_pct = pct_totale

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
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Apports estimés", f"{apports_total:,.2f} €")
    c2.metric("Cash estimé", f"{flow['cash']:,.2f} €")
    c3.metric("Valorisation titres", f"{valo_titres:,.2f} €")
    c4.metric("Patrimoine total", f"{patrimoine:,.2f} €")
    c5.metric("Plus-value totale", f"{pv_totale:+,.2f} €", f"{pct_totale:+.1f}%")

    extra = ""
    if fe_valo or fe_apports:
        extra = f" — Fonds euros : valo {fe_valo:,.2f} € (apports {fe_apports:,.2f} €, intérêts {fe_interets:,.2f} €)"
    st.caption(
        f"Investi UC (coût ouvert) : {investi_ouvert:,.2f} € — "
        f"Σ achats UC {flow['total_achats']:,.2f} € / Σ ventes {flow['total_ventes']:,.2f} € — "
        f"{len(transactions)} ops UC"
        + extra
    )

    if not sold_df.empty:
        st.info(
            f"{len(sold_df)} position(s) entièrement vendue(s). "
            "Le cash issu des ventes est inclus dans « Cash estimé » / « Patrimoine total »."
        )

    st.markdown("---")

    tab1, tab2, tab3, tab4 = st.tabs(["📊 Synthèse", "📋 Opérations", "📈 Évolution", "💾 Export"])

    with tab1:
        if not open_df.empty:
            valo = pd.to_numeric(open_df["Valorisation (€)"], errors="coerce").fillna(0)
            investi = pd.to_numeric(open_df["Investi (€)"], errors="coerce").fillna(0)
            labels = open_df["Nom"].astype(str).str[:25]
            mask_valo = valo > 0
            mask_investi = investi > 0

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Répartition valorisation**")
                if mask_valo.any():
                    fig, ax = plt.subplots(figsize=(6, 5))
                    ax.pie(
                        valo[mask_valo],
                        labels=labels[mask_valo],
                        autopct="%1.1f%%",
                        colors=COLORS[: mask_valo.sum()],
                        startangle=90,
                    )
                    ax.set_title(f"Total : {valo.sum():,.0f} €")
                    st.pyplot(fig)
                    plt.close()
            with col2:
                st.markdown("**Répartition investi**")
                if mask_investi.any():
                    fig, ax = plt.subplots(figsize=(6, 5))
                    ax.pie(
                        investi[mask_investi],
                        labels=labels[mask_investi],
                        autopct="%1.1f%%",
                        colors=COLORS[: mask_investi.sum()],
                        startangle=90,
                    )
                    ax.set_title(f"Total : {investi.sum():,.0f} €")
                    st.pyplot(fig)
                    plt.close()

            st.markdown("**Positions ouvertes**")
            st.dataframe(
                open_df.style.format(
                    {
                        "Parts": "{:.4f}",
                        "Investi (€)": "{:,.2f}",
                        "Cours actuel (€)": "{:.4f}",
                        "Valorisation (€)": "{:,.2f}",
                        "Plus-value (€)": "{:+,.2f}",
                        "Plus-value (%)": "{:+.1f}",
                    },
                    na_rep="-",
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.warning("Aucune position ouverte dans ce mode.")

        if not sold_df.empty:
            with st.expander(f"Positions soldées ({len(sold_df)})"):
                st.dataframe(
                    sold_df.style.format(
                        {
                            "Parts": "{:.4f}",
                            "Investi (€)": "{:,.2f}",
                            "Cours actuel (€)": "{:.4f}",
                            "Valorisation (€)": "{:,.2f}",
                            "Plus-value (€)": "{:+,.2f}",
                            "Plus-value (%)": "{:+.1f}",
                        },
                        na_rep="-",
                    ),
                    use_container_width=True,
                    hide_index=True,
                )


        if fe_by_id:
            fe_rows = []
            for fid, v in fe_by_id.items():
                fe_rows.append({
                    "ID": fid,
                    "Nom": v["name"],
                    "Versements (€)": round(v["verse"], 2),
                    "Retraits (€)": round(v["retire"], 2),
                    "Intérêts (€)": round(v["interets"], 2),
                    "Apports nets (€)": round(v["apports"], 2),
                    "Valorisation (€)": round(v["valo"], 2),
                })
            st.markdown("**Fonds euros**")
            st.dataframe(pd.DataFrame(fe_rows), use_container_width=True, hide_index=True)

    with tab2:
        if not df.empty:
            display_cols = [
                "date_str", "type", "quantite", "isin", "valeur",
                "cours", "montant", "frais", "solde", "source",
            ]
            display_cols = [c for c in display_cols if c in df.columns]
            st.dataframe(
                df[display_cols].rename(
                    columns={
                        "date_str": "Date",
                        "type": "Type",
                        "quantite": "Quantité",
                        "isin": "ISIN",
                        "valeur": "Valeur",
                        "cours": "Cours (€)",
                        "montant": "Montant (€)",
                        "frais": "Frais (€)",
                        "solde": "Solde",
                        "source": "Source",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

    with tab3:
        if not portfolio_value.empty:
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(
                portfolio_value.index, portfolio_value,
                label="Valorisation", color="#2E86AB", lw=2,
            )
            ax.plot(
                invested_cumul.index, invested_cumul,
                label="Investi", color="#A23B72", ls="--",
            )
            ax.legend()
            ax.set_ylabel("€")
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
            st.pyplot(fig)
            plt.close()

            if parts_history:
                fig, ax = plt.subplots(figsize=(10, 4))
                for i, (isin, s) in enumerate(parts_history.items()):
                    ax.plot(
                        s.index, s,
                        label=by_isin[isin]["name"][:25],
                        color=COLORS[i % len(COLORS)],
                    )
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
