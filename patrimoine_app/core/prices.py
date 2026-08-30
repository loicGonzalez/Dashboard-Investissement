"""Cours Yahoo Finance + fallbacks robustes."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
import yfinance as yf

from core.config import YAHOO_TICKERS


def _tickers_for(isin: str) -> list[str]:
    raw = YAHOO_TICKERS.get(isin)
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    return list(raw)


def _fetch_last_price(ticker: str) -> float | None:
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1mo")
        if hist is not None and not hist.empty:
            return float(hist["Close"].dropna().iloc[-1])
        # fallback fast_info
        fi = getattr(t, "fast_info", None)
        if fi is not None:
            for key in ("lastPrice", "last_price", "regularMarketPrice"):
                try:
                    val = fi.get(key) if hasattr(fi, "get") else getattr(fi, key, None)
                    if val is not None and float(val) > 0:
                        return float(val)
                except Exception:
                    pass
    except Exception:
        return None
    return None


@st.cache_data(ttl=1800, show_spinner="Cours Yahoo…")
def get_current_prices(isins: tuple):
    """Retourne {isin: {price, date, ticker} | None}."""
    prices = {}
    for isin in isins:
        found = None
        for ticker in _tickers_for(isin):
            px = _fetch_last_price(ticker)
            if px is not None and px > 0:
                found = {
                    "price": px,
                    "date": datetime.now().date(),
                    "ticker": ticker,
                }
                break
        prices[isin] = found
    return prices


def apply_price_fallbacks(by_isin, current_prices, manual_prices):
    """Priorité : manuel > Yahoo > dernier cours op > montant/quantité."""
    prices = dict(current_prices or {})

    for isin, px in (manual_prices or {}).items():
        try:
            prices[isin] = {"price": float(px), "date": datetime.now().date(), "ticker": "manuel"}
        except (TypeError, ValueError):
            pass

    for isin, v in (by_isin or {}).items():
        info = prices.get(isin)
        if info is not None and info.get("price"):
            continue
        # dernier cours d'opération > 0
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
            # dériver du montant / quantité
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


@st.cache_data(ttl=6 * 3600, show_spinner=False)
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
