"""Cours Yahoo Finance + fallbacks robustes."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
import yfinance as yf

from core.config import YAHOO_TICKERS
from core.db import load_ticker_overrides


def _tickers_for(isin: str) -> list[str]:
    isin = (isin or "").upper()
    # 1) overrides utilisateur (SQLite)
    try:
        ov = load_ticker_overrides()
        if isin in ov and ov[isin]:
            return list(ov[isin])
    except Exception:
        pass
    # 2) table config
    raw = YAHOO_TICKERS.get(isin)
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    return list(raw)



def _exchange_priority(isin: str, ticker: str) -> int:
    """Score bas = meilleur. Privilégie les cotations EUR proches du PEA/CTO FR."""
    t = (ticker or "").upper()
    isin = (isin or "").upper()
    # Places EUR
    if t.endswith(".PA"):
        return 0
    if t.endswith(".DE") or t.endswith(".F"):
        return 1
    if t.endswith(".MI") or t.endswith(".AS"):
        return 2
    if t.endswith(".L"):
        return 3  # souvent GBP/USD quote
    if t.endswith(".AX"):
        return 5
    return 4


def _fetch_last_price(ticker: str) -> dict | None:
    """Dernier close + méta. Évite fast_info (parfois hors séance / mauvais marché)."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="10d", auto_adjust=False)
        if hist is None or hist.empty:
            hist = t.history(period="1mo", auto_adjust=False)
        if hist is not None and not hist.empty:
            close = hist["Close"].dropna()
            if close.empty:
                return None
            px = float(close.iloc[-1])
            if px <= 0:
                return None
            d = close.index[-1]
            try:
                d = d.date() if hasattr(d, "date") else d
            except Exception:
                d = datetime.now().date()
            return {"price": px, "date": d, "ticker": ticker}
    except Exception:
        return None
    return None


def _pick_best_quote(isin: str, candidates: list[dict], ref_price: float | None) -> dict | None:
    """
    Choisit la meilleure cotation parmi plusieurs tickers.
    - Si ref_price (dernier cours d'op) : plus proche, écart max 25 %
    - Sinon : priorité place EUR (.PA > .DE > .MI > .L)
    """
    if not candidates:
        return None
    if ref_price and ref_price > 0:
        scored = []
        for c in candidates:
            px = c["price"]
            rel = abs(px - ref_price) / ref_price
            if rel > 0.25:
                continue  # écart aberrant (mauvais ticker / devise)
            scored.append((rel, _exchange_priority(isin, c["ticker"]), c))
        if scored:
            scored.sort(key=lambda x: (x[0], x[1]))
            return scored[0][2]
        # aucun dans les 25 % : garder le plus proche quand même si < 50 %
        scored = []
        for c in candidates:
            px = c["price"]
            rel = abs(px - ref_price) / ref_price
            if rel <= 0.50:
                scored.append((rel, _exchange_priority(isin, c["ticker"]), c))
        if scored:
            scored.sort(key=lambda x: (x[0], x[1]))
            return scored[0][2]
    # Pas de référence : place EUR
    candidates = sorted(candidates, key=lambda c: _exchange_priority(isin, c["ticker"]))
    return candidates[0]


def _ref_price_from_ops(ops: list) -> float | None:
    if not ops:
        return None
    for op in sorted(ops, key=lambda x: x.get("date") or datetime.min, reverse=True):
        try:
            c = float(op.get("cours") or 0)
            if c > 0:
                return c
        except (TypeError, ValueError):
            pass
        try:
            q = float(op.get("quantite") or 0)
            m = float(op.get("montant") or op.get("debit") or 0)
            if q > 0 and m > 0:
                return m / q
        except (TypeError, ValueError):
            pass
    return None


@st.cache_data(ttl=1800, show_spinner="Cours Yahoo…")
def get_current_prices(isins: tuple, ref_map: tuple = ()):
    """
    {isin: {price, date, ticker} | None}
    ref_map optionnel : tuple de (isin, ref_price) pour départager les tickers.
    """
    refs = {k: v for k, v in (ref_map or ()) if v}
    prices = {}
    for isin in isins:
        candidates = []
        for ticker in _tickers_for(isin):
            q = _fetch_last_price(ticker)
            if q:
                candidates.append(q)
        best = _pick_best_quote(isin, candidates, refs.get(isin))
        prices[isin] = best
    return prices


def get_current_prices_smart(isins: list, by_isin: dict | None = None) -> dict:
    """Construit les refs depuis les ops puis appelle le cache."""
    isins_t = tuple(sorted({i for i in isins if i}))
    refs = []
    if by_isin:
        for isin in isins_t:
            v = by_isin.get(isin) or {}
            ref = _ref_price_from_ops(v.get("ops") or [])
            if ref:
                refs.append((isin, float(ref)))
    return get_current_prices(isins_t, tuple(refs))


def apply_price_fallbacks(by_isin, current_prices, manual_prices):
    """Priorité : manuel > Yahoo (smart) > dernier cours op > montant/quantité."""
    prices = dict(current_prices or {})

    for isin, px in (manual_prices or {}).items():
        try:
            prices[isin] = {"price": float(px), "date": datetime.now().date(), "ticker": "manuel"}
        except (TypeError, ValueError):
            pass

    for isin, v in (by_isin or {}).items():
        info = prices.get(isin)
        if info is not None and info.get("price"):
            # Alerte douce : écart fort vs dernier cours d'op
            ref = _ref_price_from_ops(v.get("ops") or [])
            if ref and ref > 0 and info.get("ticker") not in ("manuel", "op", "op/montant"):
                rel = abs(float(info["price"]) - ref) / ref
                if rel > 0.15:
                    info = dict(info)
                    info["warning"] = f"écart {rel*100:.0f}% vs dernier cours op ({ref:.4f})"
                    prices[isin] = info
            continue
        ops = sorted(v.get("ops") or [], key=lambda x: x.get("date") or datetime.min)
        for op in reversed(ops):
            cours = op.get("cours")
            try:
                cours = float(cours) if cours is not None else None
            except (TypeError, ValueError):
                cours = None
            if cours and cours > 0:
                d = op.get("date") or datetime.now()
                prices[isin] = {
                    "price": cours,
                    "date": d.date() if hasattr(d, "date") else d,
                    "ticker": "op",
                }
                break
            qty = op.get("quantite")
            mont = op.get("montant") or op.get("debit")
            try:
                qty = float(qty) if qty else None
                mont = float(mont) if mont is not None else None
            except (TypeError, ValueError):
                continue
            if qty and qty > 0 and mont and mont > 0:
                d = op.get("date") or datetime.now()
                prices[isin] = {
                    "price": mont / qty,
                    "date": d.date() if hasattr(d, "date") else d,
                    "ticker": "op/montant",
                }
                break
    return prices


def get_historical_prices(ticker: str, start: datetime, end: datetime):
    try:
        hist = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
        )
        if hist is None or hist.empty:
            return pd.Series(dtype=float)
        s = hist["Close"].copy()
        try:
            s.index = s.index.tz_localize(None)
        except TypeError:
            pass
        return s
    except Exception:
        return pd.Series(dtype=float)


@st.cache_data(ttl=3600, show_spinner=False)
def get_benchmark_series(ticker: str, start: str, end: str | None = None) -> pd.Series:
    """
    Série Close journalière pour un ticker Yahoo.
    start/end : YYYY-MM-DD
    """
    if not ticker:
        return pd.Series(dtype=float)
    try:
        kwargs = {"start": start}
        if end:
            kwargs["end"] = end
        df = yf.download(ticker, progress=False, auto_adjust=True, **kwargs)
        if df is None or df.empty:
            return pd.Series(dtype=float)
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = close.dropna()
        close.index = pd.to_datetime(close.index).tz_localize(None)
        return close.astype(float)
    except Exception:
        return pd.Series(dtype=float)


def rebased_benchmark(portfolio_value: pd.Series, ticker: str) -> pd.Series | None:
    """
    Aligne un benchmark sur la 1re valeur non nulle du portefeuille.
    bench_t = portfolio_start * (price_t / price_start)
    """
    if portfolio_value is None or getattr(portfolio_value, "empty", True) or not ticker:
        return None
    pv = portfolio_value.dropna().sort_index()
    if pv.empty:
        return None
    start = pv.index.min()
    start_str = pd.Timestamp(start).strftime("%Y-%m-%d")
    end_str = pd.Timestamp(pv.index.max()).strftime("%Y-%m-%d")
    # un peu de marge avant
    start_fetch = (pd.Timestamp(start) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    bench = get_benchmark_series(ticker, start_fetch, end_str)
    if bench is None or bench.empty:
        return None
    # point de référence : premier cours bench >= start
    ref = bench[bench.index >= pd.Timestamp(start)]
    if ref.empty:
        ref = bench
    p0 = float(ref.iloc[0])
    if p0 <= 0:
        return None
    v0 = float(pv.iloc[0])
    # si première valo quasi 0, prendre première > 0
    nz = pv[pv > 0]
    if not nz.empty:
        v0 = float(nz.iloc[0])
        start_align = nz.index[0]
        ref = bench[bench.index >= pd.Timestamp(start_align)]
        if ref.empty:
            return None
        p0 = float(ref.iloc[0])
        if p0 <= 0:
            return None
    scaled = bench / p0 * v0
    # réindexer sur les dates du portefeuille (ffill)
    scaled = scaled.reindex(pv.index.union(scaled.index)).ffill()
    scaled = scaled.reindex(pv.index).ffill()
    return scaled.dropna()
