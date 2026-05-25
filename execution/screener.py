"""
execution/screener.py
---------------------
Finds recent Golden Cross / Death Cross events for a given NSE universe.
- Golden Cross: SMA(50) crosses above SMA(200) within last 7 days
- Death Cross : SMA(50) crosses below SMA(200) within last 7 days
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

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

logger = logging.getLogger(__name__)

SCREENER_CONFIG = {
    "MAX_WORKERS": 15,
    "DATA_PERIOD": "1y",
    "LOOKBACK_DAYS": 7,   # strict 7-day crossover window
}

UNIVERSE = {
    "nifty50": [
        "RELIANCE","TCS","HDFCBANK","ICICIBANK","INFY","HINDUNILVR","ITC","SBIN","BHARTIARTL",
        "KOTAKBANK","LT","AXISBANK","ASIANPAINT","MARUTI","BAJFINANCE","HCLTECH","ULTRACEMCO",
        "WIPRO","ONGC","TITAN","ADANIENT","ADANIPORTS","BAJAJFINSV","NESTLEIND","DRREDDY",
        "SUNPHARMA","POWERGRID","NTPC","TECHM","GRASIM","DIVISLAB","CIPLA","TATASTEEL",
        "BPCL","EICHERMOT","COALINDIA","HEROMOTOCO","APOLLOHOSP","HINDALCO","JSWSTEEL",
        "TATACONSUM","HDFCLIFE","SBILIFE","BRITANNIA","UPL","INDUSINDBK","M&M","TATAPOWER",
        "BAJAJ-AUTO","VEDL"
    ],
    "nifty200": [],  # filled dynamically via get_nse_500_symbols slice
    "midcap100": [],
    "smallcap100": [],
    "midcap150": [],
    "smallcap250": [],
    "microcap250": [],
    "nifty500": [],
}


def _fetch_crossover(symbol: str, lookback: int) -> dict | None:
    ticker = symbol if symbol.endswith(".NS") else symbol + ".NS"
    try:
        # Use Ticker.history() — avoids the MultiIndex column bug from yf.download()
        t = get_ticker(ticker)
        df = t.history(period=SCREENER_CONFIG["DATA_PERIOD"], interval="1d", auto_adjust=True)
        if df is None or len(df) < 210:
            return None
        df.columns = [c.lower() for c in df.columns]

        # Strip timezone so pd.Timestamp comparison works on Windows
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        df["sma50"]  = df["close"].rolling(50).mean()
        df["sma200"] = df["close"].rolling(200).mean()
        df = df.dropna(subset=["sma50", "sma200"])
        if len(df) < 2:
            return None

        cutoff = pd.Timestamp(datetime.now() - timedelta(days=lookback))
        recent = df[df.index >= cutoff]

        clean_symbol = symbol.replace(".NS", "").replace(".BO", "")
        for i in range(1, len(recent)):
            prev_diff = recent["sma50"].iloc[i-1] - recent["sma200"].iloc[i-1]
            curr_diff = recent["sma50"].iloc[i]  - recent["sma200"].iloc[i]
            if prev_diff < 0 and curr_diff >= 0:
                return {
                    "symbol": clean_symbol,
                    "type": "Golden Cross",
                    "price": round(float(recent["close"].iloc[i]), 2),
                    "date": recent.index[i].strftime("%Y-%m-%d"),
                }
            if prev_diff > 0 and curr_diff <= 0:
                return {
                    "symbol": clean_symbol,
                    "type": "Death Cross",
                    "price": round(float(recent["close"].iloc[i]), 2),
                    "date": recent.index[i].strftime("%Y-%m-%d"),
                }

        # Fallback: flag stocks where SMA50 and SMA200 are within 1% — Near Cross zone
        last = df.iloc[-1]
        gap_pct = abs(last["sma50"] - last["sma200"]) / last["sma200"] * 100
        if gap_pct <= 1.0:
            cross_type = "Near Golden Cross" if last["sma50"] > last["sma200"] else "Near Death Cross"
            return {
                "symbol": clean_symbol,
                "type": cross_type,
                "price": round(float(last["close"]), 2),
                "date": df.index[-1].strftime("%Y-%m-%d"),
            }
        return None
    except Exception as e:
        logger.debug("Crossover check failed for %s: %s", symbol, e)
        return None


def find_crossovers(category: str = "nifty50") -> dict:
    """Main entry point called by the FastAPI endpoint."""
    symbols = UNIVERSE.get(category, UNIVERSE["nifty50"])

    # For dynamic categories, fall back to nifty50 list if empty
    if not symbols:
        try:
            from execution.vcp_screener import (
                get_nse_500_symbols,
                get_midcap_150_symbols,
                get_smallcap_250_symbols,
                get_microcap_250_symbols
            )
            if category == "nifty200":
                all_syms = get_nse_500_symbols()
                symbols = all_syms[:200]
            elif category == "midcap150":
                symbols = get_midcap_150_symbols()
            elif category == "smallcap250":
                symbols = get_smallcap_250_symbols()
            elif category == "microcap250":
                symbols = get_microcap_250_symbols()
            elif category == "midcap100":
                symbols = get_midcap_150_symbols()[:100]
            elif category == "smallcap100":
                symbols = get_smallcap_250_symbols()[:100]
            elif category == "nifty500":
                symbols = get_nse_500_symbols()
            else:
                symbols = get_nse_500_symbols()
        except Exception:
            symbols = UNIVERSE["nifty50"]

    lookback = SCREENER_CONFIG["LOOKBACK_DAYS"]
    results = []
    with ThreadPoolExecutor(max_workers=SCREENER_CONFIG["MAX_WORKERS"]) as pool:
        futures = {pool.submit(_fetch_crossover, s, lookback): s for s in symbols}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                results.append(res)

    # Sort: golden crosses first, then by date desc
    results.sort(key=lambda x: (0 if x["type"] == "Golden Cross" else 1, x["date"]), reverse=False)
    return {
        "crossovers": results,
        "category": category,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(find_crossovers("nifty50"), indent=2))
