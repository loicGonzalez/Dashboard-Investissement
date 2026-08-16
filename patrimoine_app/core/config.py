"""Tickers Yahoo et constantes visuelles."""

# Plusieurs symboles possibles par ISIN (premier qui répond gagne)
YAHOO_TICKERS = {
    # PEA — BNP Easy S&P 500
    "FR0011550185": ["ESE.PA", "ESE.MI", "ESEE.DE"],
    # PEA — BNP Easy Stoxx Europe 600
    "FR0011550193": ["ETZ.PA", "ETZ.MI"],
    # PEA — Amundi MSCI EM ESG PEA
    "FR0013412020": ["PAEEM.PA", "PAEEM.MI"],
    # PER — Amundi MSCI World II
    "FR0014003IY1": ["WLDC.PA", "WLDC.MI", "LWCR.DE"],
    # Actions FR
    "FR0000120073": ["AI.PA"],
    "FR0000051070": ["MAU.PA"],
    # CTO — iShares Core S&P 500 (EUR)
    "IE00B5BMR087": ["SXR8.DE", "CSPX.L", "SXR8.MI"],
    # CTO — Nasdaq 100
    "IE00BMFKG444": ["EXXT.DE", "EQQQ.DE", "CNDX.L", "XNAS.DE"],
    # European Lithium
    "AU000000EUR7": ["PF8.F", "EUR.AX"],
}

COLORS = ["#2E86AB", "#A23B72", "#F18F01", "#C73E1D", "#3B1F2B", "#6A994E", "#457B9D"]

ENV_COLORS = {
    "PEA": "#3b82f6",
    "PER": "#f59e0b",
    "CTO": "#10b981",
}
