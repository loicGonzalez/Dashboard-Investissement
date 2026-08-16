"""
Connecteur Powens (ex-Budget Insight) — usage local / perso.

Secrets : variables d'environnement ou fichier .env (jamais commit).
Token user : chiffré au repos dans secrets/powens_token.enc
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

# Racine app : patrimoine_app/
APP_ROOT = Path(__file__).resolve().parents[2]
SECRETS_DIR = APP_ROOT / "secrets"
TOKEN_FILE = SECRETS_DIR / "powens_token.enc"
TOKEN_META = SECRETS_DIR / "powens_meta.json"


def _load_dotenv():
    env_path = APP_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv()


def config() -> dict[str, str]:
    domain = os.environ.get("POWENS_DOMAIN", "").strip()
    return {
        "domain": domain,
        "client_id": os.environ.get("POWENS_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("POWENS_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.environ.get(
            "POWENS_REDIRECT_URI", "https://127.0.0.1:8765/callback"
        ).strip(),
        "base_url": f"https://{domain}.biapi.pro/2.0" if domain else "",
    }


def is_configured() -> bool:
    c = config()
    return bool(c["domain"] and c["client_id"] and c["client_secret"])


# ─── Chiffrement token (Fernet) ───────────────────────────────────────────

def _fernet():
    """Clé dérivée de POWENS_TOKEN_KEY ou générée une fois dans secrets/."""
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:
        raise RuntimeError(
            "Installe cryptography : pip install cryptography"
        ) from e

    key = os.environ.get("POWENS_TOKEN_KEY", "").strip()
    key_file = SECRETS_DIR / "powens_fernet.key"
    if not key:
        if key_file.exists():
            key = key_file.read_text(encoding="utf-8").strip()
        else:
            SECRETS_DIR.mkdir(parents=True, exist_ok=True)
            key = Fernet.generate_key().decode("utf-8")
            key_file.write_text(key, encoding="utf-8")
            try:
                key_file.chmod(0o600)
            except OSError:
                pass
    return Fernet(key.encode("utf-8") if isinstance(key, str) else key)


def save_user_token(token: str, user_id: int | None = None) -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    f = _fernet()
    TOKEN_FILE.write_bytes(f.encrypt(token.encode("utf-8")))
    try:
        TOKEN_FILE.chmod(0o600)
    except OSError:
        pass
    meta = {"user_id": user_id, "saved_at": datetime.now().isoformat(timespec="seconds")}
    TOKEN_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def load_user_token() -> str | None:
    if not TOKEN_FILE.exists():
        return None
    try:
        f = _fernet()
        return f.decrypt(TOKEN_FILE.read_bytes()).decode("utf-8")
    except Exception:
        return None


def clear_user_token() -> None:
    for p in (TOKEN_FILE, TOKEN_META):
        if p.exists():
            p.unlink()


# ─── API HTTP ─────────────────────────────────────────────────────────────

class PowensError(Exception):
    pass


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _request(method: str, path: str, token: str | None = None, **kwargs) -> Any:
    c = config()
    if not c["base_url"]:
        raise PowensError("POWENS_DOMAIN manquant dans .env")
    url = f"{c['base_url']}{path}"
    headers = kwargs.pop("headers", {})
    if token:
        headers.update(_headers(token))
    try:
        r = requests.request(method, url, headers=headers, timeout=60, **kwargs)
    except requests.RequestException as e:
        raise PowensError(f"Réseau : {e}") from e
    if r.status_code == 401:
        raise PowensError("Token invalide ou expiré (401) — reconnecte la Webview")
    if r.status_code >= 400:
        raise PowensError(f"API {r.status_code} : {r.text[:300]}")
    if not r.content:
        return None
    return r.json()


def init_user() -> dict:
    """Crée un user Powens + token permanent (première fois)."""
    c = config()
    if not is_configured():
        raise PowensError("Configure .env (DOMAIN, CLIENT_ID, CLIENT_SECRET)")
    # form-urlencoded souvent attendu sur auth
    r = requests.post(
        f"{c['base_url']}/auth/init",
        data={
            "client_id": c["client_id"],
            "client_secret": c["client_secret"],
        },
        timeout=60,
    )
    if r.status_code >= 400:
        raise PowensError(f"auth/init {r.status_code}: {r.text[:300]}")
    data = r.json()
    token = data.get("auth_token") or data.get("access_token")
    if not token:
        raise PowensError(f"Pas de token dans la réponse : {list(data.keys())}")
    save_user_token(token, data.get("id") or data.get("id_user"))
    return data


def generate_webview_code(token: str | None = None) -> str:
    token = token or load_user_token()
    if not token:
        raise PowensError("Pas de token — lance init_user() d'abord")
    data = _request("GET", "/auth/token/code", token=token)
    code = data.get("code") if isinstance(data, dict) else None
    if not code:
        raise PowensError(f"Pas de code webview : {data}")
    return code


def webview_connect_url(code: str | None = None) -> str:
    c = config()
    code = code or generate_webview_code()
    params = {
        "domain": f"{c['domain']}.biapi.pro",
        "client_id": c["client_id"],
        "code": code,
        "redirect_uri": c["redirect_uri"],
    }
    return f"https://webview.powens.com/fr/connect?{urlencode(params)}"


def list_connections(token: str | None = None) -> list:
    token = token or load_user_token()
    data = _request("GET", "/users/me/connections", token=token)
    if isinstance(data, dict):
        return data.get("connections") or data.get("values") or []
    return data or []


def list_accounts(token: str | None = None) -> list:
    token = token or load_user_token()
    data = _request("GET", "/users/me/accounts", token=token)
    if isinstance(data, dict):
        return data.get("accounts") or data.get("values") or []
    return data or []


def list_investments(token: str | None = None) -> list:
    token = token or load_user_token()
    data = _request("GET", "/users/me/investments", token=token)
    if isinstance(data, dict):
        return data.get("investments") or data.get("values") or []
    return data or []


def sync_connection(connection_id: int, token: str | None = None) -> Any:
    token = token or load_user_token()
    return _request(
        "POST",
        f"/users/me/connections/{connection_id}/synchronize",
        token=token,
        json={},
    )


def revoke_token(token: str | None = None) -> None:
    token = token or load_user_token()
    if not token:
        return
    try:
        _request("POST", "/auth/revoke", token=token, json={})
    except PowensError:
        pass
    clear_user_token()


# ─── Mapping vers le modèle local ─────────────────────────────────────────

def investments_to_snapshot_ops(investments: list, enveloppe: str = "PEA") -> list:
    """
    Convertit un snapshot de positions Powens en opérations ACHAT synthétiques
    (quantité / cours / valo à la date du jour).

    Attention : ce n'est PAS un historique d'ordres — utile pour valo / quantités.
    Le PRU fin reste mieux servi par PDF/CSV.
    """
    ops = []
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for inv in investments or []:
        isin = inv.get("code") or inv.get("isin") or ""
        qty = inv.get("quantity")
        if qty is None:
            continue
        try:
            qty = float(qty)
        except (TypeError, ValueError):
            continue
        if abs(qty) < 1e-12:
            continue
        unit = inv.get("unitvalue") or inv.get("unit_value") or inv.get("diff")
        valo = inv.get("valuation") or inv.get("value")
        try:
            unit = float(unit) if unit is not None else None
        except (TypeError, ValueError):
            unit = None
        try:
            valo = float(valo) if valo is not None else None
        except (TypeError, ValueError):
            valo = None
        if unit is None and valo is not None and qty:
            unit = valo / qty
        if unit is None:
            unit = 0.0
        montant = round(qty * unit, 2) if unit else (round(valo, 2) if valo else 0.0)
        nom = inv.get("label") or inv.get("name") or isin or "Position Powens"
        ops.append({
            "date": today,
            "type": "ACHAT",
            "quantite": qty,
            "valeur": nom,
            "isin": str(isin).upper() if isin else None,
            "cours": unit,
            "solde": None,
            "brut": montant,
            "frais": 0.0,
            "montant": montant,
            "source": "Powens snapshot",
            "kind": "uc",
            "no_cash": True,  # snapshot : ne pas fausser cash/apports
        })
    return ops


def guess_enveloppe(account: dict) -> str:
    """Heuristique label compte → PEA / PER / CTO."""
    label = f"{account.get('name', '')} {account.get('original_name', '')} {account.get('type', '')}".upper()
    if "PEA" in label:
        return "PEA"
    if "PER" in label or "RETRAITE" in label:
        return "PER"
    if "TITRE" in label or "CTO" in label or "BOURSE" in label or "MARKET" in label:
        return "CTO"
    # type enum Powens parfois
    t = str(account.get("type", "")).lower()
    if "pea" in t:
        return "PEA"
    if "lifeinsurance" in t or "capitalisation" in t:
        return "PER"
    if "market" in t or "investment" in t:
        return "CTO"
    return "CTO"
