"""Cours Yahoo Finance + fallbacks."""
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
import yfinance as yf

from core.config import YAHOO_TICKERS

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

def apply_price_fallbacks(by_isin, current_prices, manual_prices):
    """Priorité : manuel > Yahoo > dernier cours des opérations."""
    prices = dict(current_prices)
    for isin, px in (manual_prices or {}).items():
        prices[isin] = {"price": float(px), "date": datetime.now().date()}
    for isin, v in by_isin.items():
        if prices.get(isin) is not None:
            continue
        for op in reversed(sorted(v["ops"], key=lambda x: x["date"])):
            if op.get("cours"):
                d = op["date"]
                prices[isin] = {
                    "price": float(op["cours"]),
                    "date": d.date() if hasattr(d, "date") else d,
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
        if hist.empty:
            return pd.Series(dtype=float)
        s = hist["Close"].copy()
        s.index = s.index.tz_localize(None)
        return s
    except Exception:
        return pd.Series(dtype=float)


