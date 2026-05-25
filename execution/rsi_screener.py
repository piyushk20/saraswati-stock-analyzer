"""
execution/rsi_screener.py
-------------------------
Multi-Timeframe RSI Screener for NSE/BSE markets.

Strategy Logic:
  - Monthly RSI > 60
  - Weekly RSI > 60
  - Daily RSI in range 55 - 65

Uses: yfinance, pandas, numpy
"""

import logging
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
try:
    from execution.yf_helper import get_ticker, get_historical_data_safe
except ImportError:
    try:
        from yf_helper import get_ticker, get_historical_data_safe
    except ImportError:
        def get_ticker(symbol):
            return yf.Ticker(symbol)
        def get_historical_data_safe(symbol, period="5y"):
            return yf.Ticker(symbol).history(period=period)
from ta.momentum import RSIIndicator


warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

RSI_CONFIG = {
    "MONTHLY_MIN": 60.0,   # strict monthly momentum
    "WEEKLY_MIN":  60.0,   # strict weekly momentum
    "DAILY_MIN":   55.0,   # daily in consolidation/breakout range
    "DAILY_MAX":   65.0,   # daily upper boundary
    "MIN_PRICE":   20.0,
    "MAX_WORKERS": 15,
    "DATA_PERIOD": "2y",   # bumped from 1y to ensure enough monthly bars (need 15+)
    "SYMBOL_CAP": 800,
}

def _calc_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Calculate RSI using ta library."""
    if len(close) < length + 1: return pd.Series([50.0] * len(close))
    return RSIIndicator(close=close, window=length).rsi()


def _safe_float(v) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None

def _fetch_and_analyze(symbol: str) -> dict | None:
    ticker = symbol if symbol.endswith((".NS", ".BO")) else symbol + ".NS"

    try:
        t = get_ticker(ticker)
        df = t.history(
            period=RSI_CONFIG["DATA_PERIOD"],
            interval="1d",
            auto_adjust=True,
            timeout=10,
        )


        if df is None or len(df) < 100:
            return None

        df = df.dropna(subset=["Close"])

        if len(df) < 100:
            return None

        # Ensure index is standard datetime for resampling
        df.index = pd.to_datetime(df.index)
        close = df["Close"].astype(float)

        today_close = _safe_float(close.iloc[-1])
        if today_close is None or today_close < RSI_CONFIG["MIN_PRICE"]:
            return None

        # 1. Daily RSI
        rsi_daily = _calc_rsi(close, 14)
        d_rsi = _safe_float(rsi_daily.iloc[-1])
        if d_rsi is None or not (RSI_CONFIG["DAILY_MIN"] <= d_rsi <= RSI_CONFIG["DAILY_MAX"]):
            return None

        # 2. Weekly RSI
        w_close = close.resample("W-FRI").last().dropna()
        if len(w_close) < 15:
            return None
        rsi_weekly = _calc_rsi(w_close, 14)
        w_rsi = _safe_float(rsi_weekly.iloc[-1])
        if w_rsi is None or w_rsi <= RSI_CONFIG["WEEKLY_MIN"]:
            return None

        # 3. Monthly RSI — try ME (newer pandas), fall back to M
        try:
            m_close = close.resample("ME").last().dropna()
        except Exception:
            m_close = close.resample("M").last().dropna()
        if len(m_close) < 15:
            return None
        rsi_monthly = _calc_rsi(m_close, 14)
        m_rsi = _safe_float(rsi_monthly.iloc[-1])
        if m_rsi is None or m_rsi <= RSI_CONFIG["MONTHLY_MIN"]:
            return None

        return {
            "symbol":        ticker,
            "display_symbol": symbol,
            "price":         round(today_close, 2),
            "monthly_rsi":   round(m_rsi, 1),
            "weekly_rsi":    round(w_rsi, 1),
            "daily_rsi":     round(d_rsi, 1),
        }

    except Exception as e:
        logger.debug("RSI scan error for %s: %s", symbol, e)
        return None

def scan_rsi(cap: int = None) -> dict:
    try:
        from execution.vcp_screener import get_all_symbols
        symbols_raw = get_all_symbols()
    except Exception as e:
        logger.error("Could not load symbols: %s", e)
        return {"error": f"Could not load symbol list: {e}"}

    cap = cap or RSI_CONFIG["SYMBOL_CAP"]
    symbols = [s.replace(".NS", "").replace(".BO", "") for s in symbols_raw[:cap]]

    logger.info("RSI Scan: scanning %d symbols...", len(symbols))

    candidates = []
    with ThreadPoolExecutor(max_workers=RSI_CONFIG["MAX_WORKERS"]) as pool:
        futures = {pool.submit(_fetch_and_analyze, s): s for s in symbols}
        for fut in as_completed(futures):
            result = fut.result()
            if result is not None:
                candidates.append(result)

    # Sort by weekly RSI descending
    candidates.sort(key=lambda x: x["weekly_rsi"], reverse=True)

    logger.info("RSI Scan complete: %d candidates found.", len(candidates))

    return {
        "rsi_stocks": candidates,
        "scanned":    len(symbols),
        "found":      len(candidates),
        "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

if __name__ == "__main__":
    import json
    results = scan_rsi()
    print(json.dumps(results, indent=2))
