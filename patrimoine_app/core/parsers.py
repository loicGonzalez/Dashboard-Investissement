"""Parsers PDF CIC / Trade Republic / CSV."""
import re
from collections import defaultdict
from datetime import datetime

import streamlit as st
import pdfplumber
import pandas as pd

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
    """Parse avis Trade Republic (CTO ou PEA) : achat, vente, bonus, plan."""
    try:
        with pdfplumber.open(pdf_file) as pdf:
            parts = []
            for page in pdf.pages[:3]:
                parts.append(page.extract_text() or "")
            text = "\n".join(parts)
    except Exception:
        return None

    text_up0 = text.upper()
    if not any(k in text_up0 for k in (
        "TRADE REPUBLIC",
        "CONFIRMATION DE L'INVESTISSEMENT",
        "CONFIRMATION DE LA VENTE",
        "BONUS",
    )):
        return None

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    text_up = text.upper()

    # ---------- BONUS / actions gratuites ----------
    if "BONUS" in text_up:
        # Date
        date = None
        for line in lines:
            m = re.search(r"DATE\s+(\d{2})\.(\d{2})\.(\d{4})", line, re.IGNORECASE)
            if m:
                try:
                    date = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                    break
                except ValueError:
                    pass
            m = re.search(r"(\d{2})/(\d{2})/(\d{4})", line)
            if m and date is None:
                try:
                    date = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                except ValueError:
                    pass
        if date is None:
            date = datetime.now()

        # ISIN
        isin = None
        m = re.search(r"\b([A-Z]{2}[A-Z0-9]{10})\b", text)
        if m:
            isin = m.group(1).upper()
        if not isin:
            return None

        # Quantité : "0.141236 unit." ou "0,141236"
        quantite = None
        m = re.search(r"(\d+[.,]\d+)\s*unit", text, re.IGNORECASE)
        if m:
            quantite = parse_fr_number(m.group(1))
        if quantite is None:
            m = re.search(r"(\d+[.,]\d{4,})", text)
            if m:
                quantite = parse_fr_number(m.group(1))
        if not quantite or quantite <= 0:
            return None

        # Nom
        nom = isin
        m = re.search(r"(?:TITRE|Crédit)\s+([A-Za-z0-9 &.\-]+)\s+" + re.escape(isin), text, re.IGNORECASE)
        if m:
            nom = m.group(1).strip()
        else:
            for line in lines:
                if isin in line.replace(" ", ""):
                    # "Air Liquide FR0000120073" ou lignes séparées
                    pass
            m = re.search(r"(Air Liquide|[A-Za-z][A-Za-z0-9 &.\-]{2,40})\s*\n?\s*" + re.escape(isin), text)
            if m:
                nom = m.group(1).strip()
            elif "Air Liquide" in text:
                nom = "Air Liquide"

        return {
            "date": date,
            "type": "BONUS",  # traité comme ACHAT à coût 0
            "quantite": quantite,
            "valeur": nom,
            "isin": isin,
            "cours": 0.0,
            "solde": None,
            "brut": 0.0,
            "frais": 0.0,
            "montant": 0.0,
            "source": "Trade Republic BONUS",
            "kind": "uc",
            "no_cash": True,
        }

    # ---------- Confirmation d'investissement classique ----------
    if "TRADE REPUBLIC" not in text_up and "CONFIRMATION DE L'INVESTISSEMENT" not in text_up:
        return None

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

    nom, quantite, cours, montant_brut = None, None, None, None
    search_lines = []
    if isin_line_idx is not None and isin_line_idx > 0:
        search_lines.append(lines[isin_line_idx - 1])
    for line in lines:
        if re.search(r"\d+,\d+\s+\d+[.,]\d+\s*EUR\s+\d+[.,]\d+\s*EUR", line):
            search_lines.append(line)

    for prev in search_lines:
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

    total = None
    for line in lines:
        m = re.search(r"TOTAL\s+(-[\d,]+)\s*EUR", line, re.IGNORECASE)
        if m:
            total = abs(parse_fr_number(m.group(1)) or 0)
            break
    if total is None:
        for line in lines:
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

    # Type ACHAT / VENTE
    typ = "ACHAT"
    if any(k in text_up for k in ("CONFIRMATION DE LA VENTE", "ORDRE DE VENTE", "VENTE DE", " SELL ")):
        typ = "VENTE"
    elif "VENTE" in text_up and "ACHAT" not in text_up and "INVESTISSEMENT" not in text_up:
        typ = "VENTE"

    # Enveloppe (PEA vs CTO) — purement informatif dans source
    env_tag = "PEA" if "PEA" in text_up else "CTO"
    if "PLAN D'INVESTISSEMENT" in text_up or "PLAN D’INVESTISSEMENT" in text_up or "SAVINGS PLAN" in text_up:
        env_tag = env_tag + " plan"

    return {
        "date": date,
        "type": typ,
        "quantite": quantite,
        "valeur": nom or isin,
        "isin": isin,
        "cours": cours,
        "solde": None,
        "brut": montant_brut,
        "frais": ttf,
        "montant": montant,
        "source": f"Trade Republic {env_tag}",
        "kind": "uc",
        "no_cash": False,
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



def _classify_liquidity_label(label: str, sense: str) -> tuple[str, str]:
    """
    Retourne (type, role) :
      type : VERSEMENT | RETRAIT | CASH_IN | CASH_OUT
      role : apport | cash (mouvement interne titres/frais)
    sense : "in" (crédit) | "out" (débit)
    """
    u = (label or "").upper()

    # Frais
    if any(k in u for k in ("COM. DE GEST", "COM DE GEST", "FRAIS BANCAIRES", "FRAIS DE")):
        return ("CASH_OUT", "cash") if sense == "out" else ("CASH_IN", "cash")

    # Souscriptions / achats titres
    if any(k in u for k in ("SOUSC", "SOUSCRIPTION", "ACHAT")):
        return ("CASH_OUT", "cash") if sense == "out" else ("CASH_IN", "cash")

    # Rachats → retour cash
    if "RACHAT" in u:
        return ("CASH_IN", "cash") if sense == "in" else ("CASH_OUT", "cash")

    # Apports / sorties externes
    if any(k in u for k in ("OUVERTURE", "VERSEMENT", "REGULARISATION")):
        return ("VERSEMENT", "apport") if sense == "in" else ("RETRAIT", "apport")

    if u.startswith("VIR") or "VIREMENT" in u:
        return ("VERSEMENT", "apport") if sense == "in" else ("RETRAIT", "apport")

    # Défaut : suivre le sens (évite d'ignorer des lignes)
    if sense == "in":
        return ("CASH_IN", "cash")
    return ("CASH_OUT", "cash")


def parse_liquidity_csv(uploaded_file) -> list:
    """
    Parse export liquidité PEA (CIC ou modèle).

    Colonnes : date, operation|libelle, debit, credit [, montant]

    - VERSEMENT / RETRAIT : apports nets (KPI Apports)
    - CASH_IN / CASH_OUT : mouvements caisse (SOUSC, ACHAT, RACHAT, frais)
    """
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
    rename = {}
    for c in list(df.columns):
        if c in ("libelle", "libellé", "label", "intitule", "intitulé", "description", "opé", "ope", "opération"):
            rename[c] = "operation"
        if c == "crédit":
            rename[c] = "credit"
    if rename:
        df = df.rename(columns=rename)

    if "date" not in df.columns:
        st.error(f"CSV liquidité : colonne date manquante. Colonnes: {list(df.columns)}")
        return []

    has_dc = "debit" in df.columns or "credit" in df.columns

    transactions = []
    for _, row in df.iterrows():
        try:
            date_val = row["date"]
            if isinstance(date_val, str):
                date = None
                for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
                    try:
                        date = datetime.strptime(date_val.strip()[:10], fmt)
                        break
                    except ValueError:
                        continue
                if date is None:
                    continue
            else:
                date = pd.to_datetime(date_val).to_pydatetime()

            label = str(row.get("operation") or "").strip() if "operation" in df.columns else ""
            debit = parse_fr_number(row.get("debit")) if "debit" in df.columns else None
            credit = parse_fr_number(row.get("credit")) if "credit" in df.columns else None
            montant = parse_fr_number(row.get("montant")) if "montant" in df.columns else None

            if has_dc:
                if credit and credit > 0:
                    amount, sense = credit, "in"
                elif debit and debit > 0:
                    amount, sense = debit, "out"
                else:
                    continue
            elif montant is not None:
                amount = abs(montant)
                sense = "in" if montant >= 0 else "out"
            else:
                continue

            typ, role = _classify_liquidity_label(label, sense)
            transactions.append({
                "date": date,
                "type": typ,
                "quantite": None,
                "valeur": label or typ,
                "isin": None,
                "cours": None,
                "solde": None,
                "brut": None,
                "frais": 0.0,
                "montant": round(float(amount), 2),
                "source": "CSV liquidité",
                "kind": "cash",
                "role": role,
                "no_cash": False,
            })
        except Exception:
            continue

    return transactions
