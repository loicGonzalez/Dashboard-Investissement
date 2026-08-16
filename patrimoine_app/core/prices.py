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
