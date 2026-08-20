"""Répartition géographique des positions (actions + ETF).

Taxonomie simplifiée :
- États-Unis
- Europe          (France incluse)
- Asie-Pacifique  (développé : Japon, Australie…)
- Émergents       (MSCI EM en un seul bloc)
- Monde (autre)   (résidu type Canada dans World)
- Fonds euros
- Non classé
"""
from __future__ import annotations

ZONES = [
    "États-Unis",
    "Europe",
    "Asie-Pacifique",
    "Émergents",
    "Monde (autre)",
    "Fonds euros",
    "Non classé",
]

# Zones pilotables (hors cash fonds euros / non classé)
ALLOC_ZONES = [
    "États-Unis",
    "Europe",
    "Asie-Pacifique",
    "Émergents",
    "Monde (autre)",
]

# Cibles par défaut (%). Ajustables dans l'UI / SQLite.
DEFAULT_TARGETS = {
    "États-Unis": 55.0,
    "Europe": 25.0,
    "Asie-Pacifique": 5.0,
    "Émergents": 10.0,
    "Monde (autre)": 5.0,
}

ZONE_COLORS = {
    "États-Unis": "#3b82f6",
    "Europe": "#8b5cf6",
    "Asie-Pacifique": "#10b981",
    "Émergents": "#f59e0b",
    "Monde (autre)": "#64748b",
    "Fonds euros": "#eab308",
    "Non classé": "#475569",
}

# Split indicatif type MSCI World (developed)
MSCI_WORLD_SPLIT = {
    "États-Unis": 0.70,
    "Europe": 0.18,           # UK + zone euro + Suisse… (France incluse)
    "Asie-Pacifique": 0.09,   # Japon, Australie, HK developed…
    "Monde (autre)": 0.03,    # Canada, etc.
}

# ETF Europe : 100 % Europe (plus de sous-part France)
EUROPE_100 = {"Europe": 1.0}

# ETF Émergents : un seul bloc
EM_100 = {"Émergents": 1.0}

GEO_MAP: dict[str, str | dict] = {
    # ——— ETF US ———
    "IE00B5BMR087": {"États-Unis": 1.0},          # iShares Core S&P 500
    "FR0011550185": {"États-Unis": 1.0},          # BNPP Easy S&P 500
    "IE00BMFKG444": {"États-Unis": 1.0},          # Nasdaq 100
    "IE00B53SZB19": {"États-Unis": 1.0},
    # ——— ETF Europe ———
    "FR0011550193": dict(EUROPE_100),             # BNPP Easy Stoxx Europe 600
    "IE00B60SWW18": dict(EUROPE_100),
    # ——— ETF Monde ———
    "FR0014003IY1": dict(MSCI_WORLD_SPLIT),       # Amundi MSCI World II
    "IE00B4L5Y983": dict(MSCI_WORLD_SPLIT),
    "LU1681043599": dict(MSCI_WORLD_SPLIT),
    # ——— ETF Émergents ———
    "FR0013412020": dict(EM_100),                 # Amundi PEA MSCI EM ESG
    "IE00B4L5YC18": dict(EM_100),
    # ——— Actions (Europe = France incluse) ———
    "FR0000120073": "Europe",                     # Air Liquide
    "FR0000051070": "Europe",                     # Maurel & Prom
    "FR0000120271": "Europe",                     # TotalEnergies
    "FR0000121014": "Europe",                     # LVMH
    "FR0000131104": "Europe",                     # BNP
    # ——— Asie-Pacifique developed ———
    "AU000000EUR7": "Asie-Pacifique",             # European Lithium (Australie)
    # ——— OPCVM ———
    "0P0001QJKF.F": dict(MSCI_WORLD_SPLIT),       # CM-AM Actions Monde
    "0P0001HNLZ.F": dict(EUROPE_100),             # CM-AM Convictions Euro
    "0P0001V5KH.F": {"Monde (autre)": 1.0},       # CIC Private Debt
}


def _normalize_split(spec) -> dict[str, float]:
    if isinstance(spec, str):
        return {spec: 1.0}
    if isinstance(spec, dict):
        s = sum(spec.values()) or 1.0
        return {k: v / s for k, v in spec.items()}
    return {"Non classé": 1.0}


def geo_for_isin(isin: str | None, nom: str | None = None) -> dict[str, float]:
    """Retourne {zone: poids} sommant à 1."""
    if isin and isin in GEO_MAP:
        return _normalize_split(GEO_MAP[isin])

    n = (nom or "").upper()
    if any(x in n for x in ("S&P 500", "S&P500", "NASDAQ", "SP500")):
        return {"États-Unis": 1.0}
    if "MSCI WORLD" in n or ("WORLD" in n and "EM" not in n):
        return dict(MSCI_WORLD_SPLIT)
    if any(x in n for x in ("EMERGING", "EM.ESG", "ÉMERG", "EMERGENTS", " MSCI EM")):
        return dict(EM_100)
    if any(x in n for x in ("EUROPE", "STOXX", "EURO ", "CAC", "DAX")):
        return dict(EUROPE_100)
    if "EURO RETRAITE" in n or "FONDS EURO" in n:
        return {"Fonds euros": 1.0}
    if isin and isin.startswith(("FR", "DE", "NL", "ES", "IT", "BE", "PT", "IE", "LU", "GB", "CH")):
        # domicile européen ≠ toujours exposition Europe pour un ETF,
        # mais pour une action non mappée c'est un fallback raisonnable
        if isin.startswith("FR") or isin[:2] in ("DE", "NL", "ES", "IT", "BE", "PT"):
            return {"Europe": 1.0}
    if isin and isin.startswith("US"):
        return {"États-Unis": 1.0}
    if isin and isin.startswith(("AU", "JP", "HK", "SG", "NZ")):
        return {"Asie-Pacifique": 1.0}
    return {"Non classé": 1.0}


def allocate_geo(open_positions, fe_valo: float = 0.0) -> dict[str, float]:
    totals = {z: 0.0 for z in ZONES}

    for pos in open_positions:
        row = pos if hasattr(pos, "get") else dict(pos)
        isin = row.get("ISIN") or row.get("isin")
        nom = row.get("Nom") or row.get("nom") or row.get("valeur")
        valo = row.get("Valorisation (€)") or row.get("valo") or 0.0
        try:
            valo = float(valo)
        except (TypeError, ValueError):
            valo = 0.0
        if valo <= 0:
            continue
        for zone, w in geo_for_isin(isin, nom).items():
            totals.setdefault(zone, 0.0)
            totals[zone] += valo * w

    if fe_valo and fe_valo > 0:
        totals["Fonds euros"] = totals.get("Fonds euros", 0.0) + float(fe_valo)

    return {z: round(v, 2) for z, v in totals.items() if v > 0.01}


def geo_to_frame(geo: dict):
    import pandas as pd
    total = sum(geo.values()) or 1.0
    rows = []
    for z in ZONES:
        if z in geo:
            rows.append({
                "Zone": z,
                "Valorisation (€)": geo[z],
                "%": round(100 * geo[z] / total, 1),
            })
    for z, v in geo.items():
        if z not in ZONES:
            rows.append({"Zone": z, "Valorisation (€)": v, "%": round(100 * v / total, 1)})
    return pd.DataFrame(rows)


def allocation_gap(geo: dict, targets: dict | None = None) -> "pd.DataFrame":
    """
    Compare allocation réelle (valo) vs cibles %.
    Les zones Fonds euros / Non classé sont affichées en réel mais hors cible.
    """
    import pandas as pd
    targets = targets or dict(DEFAULT_TARGETS)
    # Réel hors FE / non classé pour calculer les % "investissables"
    investable = {
        z: v for z, v in geo.items()
        if z not in ("Fonds euros", "Non classé") and v > 0
    }
    total_inv = sum(investable.values()) or 1.0
    total_all = sum(geo.values()) or 1.0

    rows = []
    zones_order = list(ALLOC_ZONES)
    for z in geo:
        if z not in zones_order:
            zones_order.append(z)

    for z in zones_order:
        real_eur = float(geo.get(z, 0.0) or 0.0)
        if z in ("Fonds euros", "Non classé"):
            real_pct = 100.0 * real_eur / total_all
            rows.append({
                "Zone": z,
                "Réel (€)": round(real_eur, 2),
                "Réel (%)": round(real_pct, 1),
                "Cible (%)": None,
                "Écart (pts)": None,
                "Écart (€)": None,
                "Statut": "hors cible",
            })
            continue
        real_pct = 100.0 * real_eur / total_inv
        tgt = float(targets.get(z, 0.0) or 0.0)
        gap_pts = real_pct - tgt
        gap_eur = real_eur - (tgt / 100.0) * total_inv
        if abs(gap_pts) < 1.0:
            statut = "OK"
        elif gap_pts > 0:
            statut = "Surpondéré"
        else:
            statut = "Sous-pondéré"
        rows.append({
            "Zone": z,
            "Réel (€)": round(real_eur, 2),
            "Réel (%)": round(real_pct, 1),
            "Cible (%)": round(tgt, 1),
            "Écart (pts)": round(gap_pts, 1),
            "Écart (€)": round(gap_eur, 2),
            "Statut": statut,
        })
    return pd.DataFrame(rows)
