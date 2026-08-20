"""Journal d'import + détection cours manquants."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from core.db import get_meta, set_meta, init_db

LOG_KEY = "import_journal"
MAX_ENTRIES = 100


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_journal() -> list[dict]:
    init_db()
    data = get_meta(LOG_KEY, [])
    return data if isinstance(data, list) else []


def append_journal_entry(entry: dict) -> None:
    """Ajoute une entrée en tête du journal (persisté SQLite)."""
    init_db()
    log = load_journal()
    entry = dict(entry)
    entry.setdefault("ts", _now())
    log.insert(0, entry)
    set_meta(LOG_KEY, log[:MAX_ENTRIES])


def clear_journal() -> None:
    set_meta(LOG_KEY, [])


def log_import_batch(
    *,
    enveloppe: str,
    source: str,
    files: list[str] | None = None,
    inserted: int = 0,
    duplicates: int = 0,
    failed: int = 0,
    failed_files: list[str] | None = None,
    mode: str = "merge",
    extra: str | None = None,
) -> dict:
    entry = {
        "ts": _now(),
        "enveloppe": enveloppe,
        "source": source,
        "mode": mode,
        "files": files or [],
        "n_files": len(files or []),
        "inserted": int(inserted),
        "duplicates": int(duplicates),
        "failed": int(failed),
        "failed_files": failed_files or [],
        "extra": extra,
    }
    append_journal_entry(entry)
    return entry


def missing_price_alerts(by_isin: dict, prices: dict) -> list[dict]:
    """
    Positions ouvertes (parts > 0) sans cours exploitable.
    prices: {isin: {price: float, ...} | None}
    """
    alerts = []
    for isin, v in (by_isin or {}).items():
        parts = float(v.get("parts") or 0)
        if parts <= 1e-12:
            continue
        info = (prices or {}).get(isin)
        px = None
        src = None
        if isinstance(info, dict):
            px = info.get("price")
            src = info.get("ticker")
        if px is None or float(px) <= 0:
            alerts.append({
                "ISIN": isin,
                "Nom": v.get("name") or isin,
                "Parts": round(parts, 6),
                "Investi (€)": round(float(v.get("investi") or 0), 2),
                "Cours": None,
                "Source cours": src or "—",
                "Alerte": "Cours manquant",
            })
    return alerts


def missing_price_alerts_from_open_df(open_df) -> list[dict]:
    """Variante à partir du DataFrame open (colonne Cours actuel)."""
    if open_df is None or getattr(open_df, "empty", True):
        return []
    alerts = []
    for _, row in open_df.iterrows():
        cours = row.get("Cours actuel (€)")
        try:
            ok = cours is not None and float(cours) > 0
        except (TypeError, ValueError):
            ok = False
        if ok:
            continue
        alerts.append({
            "ISIN": row.get("ISIN"),
            "Nom": row.get("Nom"),
            "Parts": row.get("Parts"),
            "Investi (€)": row.get("Investi (€)"),
            "Cours": None,
            "Alerte": "Cours manquant",
        })
    return alerts
