#!/usr/bin/env python3
"""
Application Streamlit - Suivi PEA + PER (version stabilisée)
"""

import re
import hashlib
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
    page_title="Suivi PEA + PER",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

YAHOO_TICKERS = {
    "FR0011550185": "ESE.PA",
    "FR0011550193": "ETZ.PA",
    "FR0013412020": "PAEEM.PA",
    "FR0014003IY1": "WLDC.MI"
}

COLORS = ["#2E86AB", "#A23B72", "#F18F01", "#C73E1D", "#3B1F2B", "#6A994E"]

# ─────────────────────────────────────────────
def parse_fr_number(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    try:
        return float(str(s).strip().replace(" ", "").replace(",", "."))
    except Exception:
        return None


def extract_transaction_from_pdf(pdf_file):
    """
    Extraction robuste d'un avis d'opération CIC.
    Méthode fiable : Débit = Brut + Frais
    """
    try:
        with pdfplumber.open(pdf_file) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except Exception:
        return None

    def search(pattern, group=1):
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        return m.group(group) if m else None

    # --- Champs principaux ---
    quantite = search(r"Quantité\s+(\d+)")
    valeur   = search(r"Valeur\s+(.+?)(?:\n|Lieu)")
    isin     = search(r"\((FR\d+)\)")
    date_str = search(r"Date et heure d'exécution\s+(\d{2}/\d{2}/\d{4})")
    cours    = search(r"Cours d'exécution\s+([\d,]+)\s*EUR")
    solde    = search(r"Nouveau solde sur la valeur\s+(\d+)")

    # --- Brut ---
    brut = parse_fr_number(search(r"Brut de l'opération\s+([\d\s,]+)\s*EUR"))

    # --- Frais de transaction ---
    frais_match = re.search(
        r"Frais de transaction\s+([\d\s,]+)\s*EUR",
        text,
        re.IGNORECASE
    )
    frais = parse_fr_number(frais_match.group(1)) if frais_match else 0.0

    # --- Débit (méthode fiable) ---
    if brut is not None:
        debit = round(brut + (frais or 0.0), 2)
    else:
        # Fallback très strict
        debit_match = re.search(
            r"Débit en date de valeur.*?(\d{1,3}(?:\s\d{3})*(?:,\d+)?)\s*EUR",
            text,
            re.IGNORECASE | re.DOTALL
        )
        debit = parse_fr_number(debit_match.group(1)) if debit_match else None

    # --- Contrôles de validité ---
    if not (isin and quantite and date_str and debit is not None):
        return None

    # Sécurité : on rejette les montants absurdes (n° de compte mal parsé)
    if debit > 100_000:
        return None

    return {
        "date": datetime.strptime(date_str, "%d/%m/%Y"),
        "quantite": int(quantite),
        "valeur": re.sub(r"\s+", " ", valeur).strip() if valeur else None,
        "isin": isin,
        "cours": parse_fr_number(cours),
        "solde": int(solde) if solde else None,
        "brut": brut,
        "frais": frais,
        "debit": debit,
        "source": "PDF",
    }


def parse_csv_transactions(uploaded_file) -> list[dict]:
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
            # Date
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

            quantite = float(row["quantite"])          # ← float
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


def process_transactions(transactions: list) -> tuple[pd.DataFrame, dict]:
    if not transactions:
        return pd.DataFrame(), {}

    transactions = sorted(transactions, key=lambda x: x["date"])
    df = pd.DataFrame(transactions)
    df["date_str"] = df["date"].dt.strftime("%d/%m/%Y")

    by_isin = defaultdict(lambda: {
        "name": "",
        "parts": 0.0,
        "investi": 0.0,
        "ops": []
    })

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
                cout_vendu = cout_unitaire * qty
                by_isin[isin]["parts"] = max(0.0, by_isin[isin]["parts"] - qty)
                by_isin[isin]["investi"] = max(0.0, by_isin[isin]["investi"] - cout_vendu)

        t["type"] = typ
        t["montant"] = montant
        by_isin[isin]["ops"].append(t)

        # Si le PDF fournit un solde, on le respecte en priorité
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


@st.cache_data(ttl=6*3600, show_spinner=False)
def get_historical_prices(ticker: str, start: datetime, end: datetime):
    try:
        hist = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=(end + timedelta(days=1)).strftime("%Y-%m-%d")
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
        ticker = YAHOO_TICKERS.get(isin)
        if not ticker:
            continue

        prices = get_historical_prices(ticker, start_date, end_date)
        if prices.empty:
            continue

        parts_series = pd.Series(0.0, index=all_dates)
        cost_series = pd.Series(0.0, index=all_dates)  # coût de revient restant

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
if "per_manual" not in st.session_state:
    st.session_state["per_manual"] = []
if "histories" not in st.session_state:
    st.session_state["histories"] = {}

# ─────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────
st.title("📈 Suivi PEA + PER")

with st.sidebar:
    st.header("📂 Import")

    st.subheader("PEA (PDF)")
    pea_files = st.file_uploader("Avis d'opération PEA", type=["pdf"], accept_multiple_files=True, key="pea")

    st.subheader("PER")
    per_csv = st.file_uploader("CSV opérations PER", type=["csv"], key="per_csv")

    with st.expander("➕ Ajouter une opération PER manuellement"):
        with st.form("manual_per_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
    
            with c1:
                m_date = st.date_input("Date", value=datetime.now())
                m_type = st.selectbox("Type d'opération", ["ACHAT", "VENTE"])
                m_quantite = st.number_input(
                    "Quantité (parts)",
                    min_value=0.0,
                    step=0.001,
                    format="%.4f",
                    value=1.0
                )
                m_isin = st.text_input("ISIN", placeholder="FR0011550185")
    
            with c2:
                m_nom = st.text_input("Nom (optionnel)", placeholder="BNPP Easy S&P 500")
                m_cours = st.number_input("Cours (€)", min_value=0.0, format="%.4f", value=0.0)
                m_frais = st.number_input("Frais (€)", min_value=0.0, format="%.2f", value=0.0)
    
            submitted = st.form_submit_button("Ajouter l'opération")
    
            if submitted:
                if not m_isin or m_cours <= 0 or m_quantite <= 0:
                    st.error("ISIN, Quantité et Cours sont obligatoires.")
                else:
                    quantite = float(m_quantite)
                    cours = float(m_cours)
                    frais = float(m_frais)
                    montant = round(quantite * cours + frais, 2)
    
                    st.session_state["per_manual"].append({
                        "date": datetime.combine(m_date, datetime.min.time()),
                        "type": m_type,
                        "quantite": quantite,
                        "valeur": m_nom.strip() or m_isin.strip().upper(),
                        "isin": m_isin.strip().upper(),
                        "cours": cours,
                        "solde": None,
                        "brut": round(quantite * cours, 2),
                        "frais": frais,
                        "montant": montant,
                        "source": "Manuel",
                    })
                    st.success(f"Opération {m_type} ajoutée ({quantite:.4f} parts)")

    if st.session_state["per_manual"]:
        st.caption(f"{len(st.session_state['per_manual'])} opération(s) manuelle(s)")
        if st.button("🗑️ Vider les opérations manuelles"):
            st.session_state["per_manual"] = []
            st.rerun()

    mode = st.radio("Mode d'affichage", ["PEA", "PER", "Cumul PEA + PER"])

    st.markdown("---")
    st.markdown("**Modèle CSV PER**")
    st.code("date,quantite,isin,nom,cours,frais,debit\n15/03/2026,20,FR0011550185,BNPP Easy S&P 500,31.50,2.50,632.50", language=None)

# ─────────────────────────────────────────────
# Traitement des données
# ─────────────────────────────────────────────
try:
    # PEA
    pea_transactions = []
    if pea_files:
        for f in pea_files:
            tx = extract_transaction_from_pdf(f)
            if tx:
                pea_transactions.append(tx)
    pea_df, pea_by_isin = process_transactions(pea_transactions)

    # PER
    per_transactions = []
    if per_csv is not None:
        per_transactions.extend(parse_csv_transactions(per_csv))
    per_transactions.extend(st.session_state["per_manual"])

    # Recalcul soldes PER
    if per_transactions:
        by_isin_qty = defaultdict(int)
        for t in sorted(per_transactions, key=lambda x: x["date"]):
            by_isin_qty[t["isin"]] += t["quantite"]
            t["solde"] = by_isin_qty[t["isin"]]

    per_df, per_by_isin = process_transactions(per_transactions)

    # Choix du mode
    if mode == "PEA":
        transactions = pea_transactions
        df = pea_df
        by_isin = pea_by_isin
        key = f"pea_{len(pea_transactions)}"
    elif mode == "PER":
        transactions = per_transactions
        df = per_df
        by_isin = per_by_isin
        key = f"per_{len(per_transactions)}"
    else:
        transactions = pea_transactions + per_transactions
        df, by_isin = process_transactions(transactions)
        key = f"cumul_{len(pea_transactions)}_{len(per_transactions)}"

    if not transactions:
        st.warning("Aucune opération chargée.")
        st.info("Dépose des PDF PEA ou un CSV / saisie manuelle pour le PER.")
        st.stop()

    # Valorisation
    isins = tuple(by_isin.keys())
    current_prices = get_current_prices(isins)
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

    # ─── Affichage ───
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
            # Force les colonnes numériques
            valo = pd.to_numeric(summary_df["Valorisation (€)"], errors="coerce").fillna(0)
            investi = pd.to_numeric(summary_df["Investi (€)"], errors="coerce").fillna(0)
            labels = summary_df["Nom"].astype(str).str[:25]
    
            # On ignore les lignes à 0 pour éviter les camemberts vides
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
                        colors=COLORS[:mask_valo.sum()],
                        startangle=90
                    )
                    ax.set_title(f"Total : {valo.sum():,.0f} €")
                    st.pyplot(fig)
                    plt.close()
                else:
                    st.info("Aucune valorisation disponible")
    
            with col2:
                st.markdown("**Répartition investi**")
                if mask_investi.any():
                    fig, ax = plt.subplots(figsize=(6, 5))
                    ax.pie(
                        investi[mask_investi],
                        labels=labels[mask_investi],
                        autopct="%1.1f%%",
                        colors=COLORS[:mask_investi.sum()],
                        startangle=90
                    )
                    ax.set_title(f"Total : {investi.sum():,.0f} €")
                    st.pyplot(fig)
                    plt.close()
                else:
                    st.info("Aucun capital investi")
    
            # Tableau
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
                hide_index=True
            )

    with tab2:
        if not df.empty:
            display_cols = ["date_str", "type", "quantite", "isin", "valeur", "cours", "montant", "frais", "solde", "source"]
            # On ne garde que les colonnes qui existent réellement
            display_cols = [c for c in display_cols if c in df.columns]
            
            st.dataframe(
                df[display_cols].rename(columns={
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
                }),
                use_container_width=True,
                hide_index=True
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
            st.download_button("Télécharger synthèse CSV",
                               summary_df.to_csv(index=False).encode("utf-8-sig"),
                               f"synthese_{mode}.csv", "text/csv")

except Exception as e:
    st.error("Une erreur est survenue :")
    st.exception(e)