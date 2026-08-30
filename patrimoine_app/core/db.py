"""Persistance SQLite locale."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

# data/ à côté de core/ (patrimoine_app/data/patrimoine.db)
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "patrimoine.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enveloppe TEXT NOT NULL,
    date TEXT NOT NULL,
    type TEXT NOT NULL,
    quantite REAL,
    isin TEXT,
    nom TEXT,
    cours REAL,
    frais REAL DEFAULT 0,
    montant REAL,
    source TEXT,
    kind TEXT DEFAULT 'uc',
    no_cash INTEGER DEFAULT 0,
    file_hash TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(enveloppe, date, type, isin, quantite, montant, source, kind)
);

CREATE TABLE IF NOT EXISTS cours_manuels (
    isin TEXT PRIMARY KEY,
    cours REAL NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_ops_env ON operations(enveloppe);
CREATE INDEX IF NOT EXISTS idx_ops_isin ON operations(isin);
"""


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | None = None) -> Path:
    path = Path(db_path) if db_path else DB_PATH
    conn = get_connection(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    return path


def _date_to_str(d) -> str:
    if d is None:
        return ""
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    if hasattr(d, "strftime"):
        return d.strftime("%Y-%m-%d")
    s = str(d)[:10]
    # dd/mm/yyyy → yyyy-mm-dd
    if len(s) == 10 and s[2] == "/":
        dd, mm, yy = s.split("/")
        return f"{yy}-{mm}-{dd}"
    return s


def _str_to_date(s: str) -> datetime:
    if not s:
        return datetime.now()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return datetime.now()


def op_to_row(op: dict, enveloppe: str) -> dict:
    return {
        "enveloppe": enveloppe,
        "date": _date_to_str(op.get("date")),
        "type": str(op.get("type", "ACHAT")).upper(),
        "quantite": op.get("quantite"),
        "isin": (op.get("isin") or None),
        "nom": op.get("valeur") or op.get("nom"),
        "cours": op.get("cours"),
        "frais": float(op.get("frais") or 0),
        "montant": op.get("montant") if op.get("montant") is not None else op.get("debit"),
        "source": op.get("source") or "",
        "kind": op.get("kind") or "uc",
        "no_cash": 1 if op.get("no_cash") else 0,
        "file_hash": op.get("file_hash"),
    }


def row_to_op(row) -> dict:
    r = dict(row) if not isinstance(row, dict) else row
    return {
        "date": _str_to_date(r["date"]),
        "type": r["type"],
        "quantite": r["quantite"],
        "valeur": r["nom"],
        "isin": r["isin"],
        "cours": r["cours"],
        "solde": None,
        "brut": None,
        "frais": r["frais"] or 0.0,
        "montant": r["montant"],
        "source": r["source"] or "DB",
        "kind": r["kind"] or "uc",
        "no_cash": bool(r["no_cash"]),
    }


def insert_operations(ops: list, enveloppe: str, db_path: Path | None = None) -> tuple[int, int]:
    """Insert ops. Returns (inserted, skipped_duplicates)."""
    if not ops:
        return 0, 0
    init_db(db_path)
    conn = get_connection(db_path)
    inserted = skipped = 0
    sql = """
        INSERT OR IGNORE INTO operations
        (enveloppe, date, type, quantite, isin, nom, cours, frais, montant, source, kind, no_cash, file_hash)
        VALUES
        (:enveloppe, :date, :type, :quantite, :isin, :nom, :cours, :frais, :montant, :source, :kind, :no_cash, :file_hash)
    """
    try:
        for op in ops:
            row = op_to_row(op, enveloppe)
            cur = conn.execute(sql, row)
            if cur.rowcount:
                inserted += 1
            else:
                skipped += 1
        conn.commit()
    finally:
        conn.close()
    return inserted, skipped


def replace_enveloppe(ops: list, enveloppe: str, db_path: Path | None = None) -> int:
    """Supprime puis réinsère toutes les ops d'une enveloppe (import CSV complet)."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM operations WHERE enveloppe = ?", (enveloppe,))
        conn.commit()
    finally:
        conn.close()
    inserted, _ = insert_operations(ops, enveloppe, db_path)
    return inserted


def load_operations(enveloppe: str | None = None, db_path: Path | None = None) -> list:
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        if enveloppe:
            rows = conn.execute(
                "SELECT * FROM operations WHERE enveloppe = ? ORDER BY date, id",
                (enveloppe,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM operations ORDER BY date, id"
            ).fetchall()
        return [row_to_op(r) for r in rows]
    finally:
        conn.close()


def count_operations(db_path: Path | None = None) -> dict:
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT enveloppe, COUNT(*) AS n FROM operations GROUP BY enveloppe"
        ).fetchall()
        return {r["enveloppe"]: r["n"] for r in rows}
    finally:
        conn.close()


def delete_enveloppe(enveloppe: str, db_path: Path | None = None) -> int:
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute("DELETE FROM operations WHERE enveloppe = ?", (enveloppe,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def save_manual_prices(prices: dict, db_path: Path | None = None) -> None:
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM cours_manuels")
        for isin, cours in (prices or {}).items():
            conn.execute(
                "INSERT INTO cours_manuels (isin, cours, updated_at) VALUES (?, ?, ?)",
                (isin, float(cours), datetime.now().isoformat(timespec="seconds")),
            )
        conn.commit()
    finally:
        conn.close()


def load_manual_prices(db_path: Path | None = None) -> dict:
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT isin, cours FROM cours_manuels").fetchall()
        return {r["isin"]: float(r["cours"]) for r in rows}
    finally:
        conn.close()


def set_meta(key: str, value: str, db_path: Path | None = None) -> None:
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def get_meta(key: str, default: str | None = None, db_path: Path | None = None) -> str | None:
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def file_content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def get_meta(key: str, default=None, db_path: Path | None = None):
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return row["value"]
    finally:
        conn.close()


def set_meta(key: str, value, db_path: Path | None = None) -> None:
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def get_allocation_targets(enveloppe: str = "GLOBAL", db_path: Path | None = None) -> dict:
    """Cibles % par zone pour une enveloppe (PEA|PER|CTO|GLOBAL)."""
    from core.geography import DEFAULT_TARGETS
    env = (enveloppe or "GLOBAL").upper()
    all_saved = get_meta("allocation_targets_by_env", None, db_path)
    if not isinstance(all_saved, dict):
        # migration depuis l'ancienne clé unique
        legacy = get_meta("allocation_targets", None, db_path)
        if isinstance(legacy, dict) and legacy:
            all_saved = {"PEA": legacy, "PER": legacy, "CTO": legacy, "GLOBAL": legacy}
        else:
            all_saved = {}
    saved = all_saved.get(env)
    if isinstance(saved, dict) and saved:
        return {k: float(v) for k, v in saved.items()}
    return dict(DEFAULT_TARGETS)


def save_allocation_targets(targets: dict, enveloppe: str = "GLOBAL", db_path: Path | None = None) -> None:
    env = (enveloppe or "GLOBAL").upper()
    clean = {str(k): float(v) for k, v in targets.items() if float(v) >= 0}
    all_saved = get_meta("allocation_targets_by_env", None, db_path)
    if not isinstance(all_saved, dict):
        all_saved = {}
    all_saved[env] = clean
    set_meta("allocation_targets_by_env", all_saved, db_path)


def average_allocation_targets(weights: dict | None = None, db_path: Path | None = None) -> dict:
    """
    Moyenne des cibles PEA/PER/CTO.
    Si weights = {"PEA": valo, "PER": valo, "CTO": valo}, moyenne pondérée.
    Sinon moyenne arithmétique simple.
    """
    from core.geography import ALLOC_ZONES, DEFAULT_TARGETS
    envs = ["PEA", "PER", "CTO"]
    targets_list = [(e, get_allocation_targets(e, db_path)) for e in envs]
    if weights:
        w = {e: max(0.0, float(weights.get(e, 0) or 0)) for e in envs}
        total_w = sum(w.values()) or 1.0
    else:
        w = {e: 1.0 for e in envs}
        total_w = 3.0
    out = {}
    for z in ALLOC_ZONES:
        s = 0.0
        for e, t in targets_list:
            s += float(t.get(z, DEFAULT_TARGETS.get(z, 0.0))) * w[e]
        out[z] = round(s / total_w, 2)
    return out


def get_patrimoine_goal(db_path: Path | None = None) -> dict:
    """Objectif patrimoine : {target_eur, monthly_apport_eur, label}."""
    data = get_meta("patrimoine_goal", None, db_path)
    if isinstance(data, dict):
        return {
            "target_eur": float(data.get("target_eur") or 0),
            "monthly_apport_eur": float(data.get("monthly_apport_eur") or 0),
            "label": str(data.get("label") or "Objectif patrimoine"),
        }
    return {"target_eur": 0.0, "monthly_apport_eur": 0.0, "label": "Objectif patrimoine"}


def save_patrimoine_goal(target_eur: float, monthly_apport_eur: float = 0.0,
                         label: str = "Objectif patrimoine",
                         db_path: Path | None = None) -> None:
    set_meta("patrimoine_goal", {
        "target_eur": float(target_eur or 0),
        "monthly_apport_eur": float(monthly_apport_eur or 0),
        "label": label or "Objectif patrimoine",
    }, db_path)


def backup_db_bytes(db_path: Path | None = None) -> tuple[bytes, str]:
    """
    Lecture safe de la base pour téléchargement.
    Retourne (contenu, nom_fichier_suggéré).
    """
    import shutil
    from datetime import datetime as _dt

    path = Path(db_path) if db_path else DB_PATH
    init_db(path)
    if not path.exists():
        return b"", "patrimoine_empty.db"

    # Copie via SQLite backup API pour éviter un fichier verrouillé à moitié écrit
    stamp = _dt.now().strftime("%Y%m%d_%H%M%S")
    out_name = f"patrimoine_backup_{stamp}.db"
    tmp = path.parent / f".backup_tmp_{stamp}.db"
    try:
        src = get_connection(path)
        try:
            dst = sqlite3.connect(str(tmp))
            try:
                src.backup(dst)
                dst.commit()
            finally:
                dst.close()
        finally:
            src.close()
        data = tmp.read_bytes()
        return data, out_name
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def restore_db_from_bytes(data: bytes, db_path: Path | None = None) -> Path:
    """Remplace la base locale par le contenu fourni (bytes .db)."""
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    # Écriture atomique
    tmp = path.with_suffix(".db.restore_tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


def delete_cash_operations(enveloppe: str, db_path: Path | None = None) -> int:
    """Supprime les opérations kind=cash (journal liquidité) d'une enveloppe."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            "DELETE FROM operations WHERE enveloppe = ? AND (kind = 'cash' OR source LIKE '%iquidité%' OR source LIKE '%iquidite%')",
            (enveloppe,),
        )
        conn.commit()
        return cur.rowcount or 0
    finally:
        conn.close()
