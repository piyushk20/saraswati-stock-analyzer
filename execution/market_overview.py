"""
execution/market_overview.py
----------------------------
Fetches live market overview: index prices, top gainers & losers
for a given universe category.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import yfinance as yf

logger = logging.getLogger(__name__)

# Index symbols mapped to display names
INDEX_SYMBOLS = {
    "^NSEI":     "NIFTY 50",
    "^NSEBANK":  "BANK NIFTY",
    "^BSESN":    "SENSEX",
    "^CNXIT":    "NIFTY IT",
    "^NSEMDCP50":"NIFTY MIDCAP 50",
}

# Equity universes — slim lists for fast loading
UNIVERSES = {
    "nifty50": [
        "RELIANCE","TCS","HDFCBANK","ICICIBANK","INFY","HINDUNILVR","ITC","SBIN",
        "BHARTIARTL","KOTAKBANK","LT","AXISBANK","ASIANPAINT","MARUTI","BAJFINANCE",
        "HCLTECH","ULTRACEMCO","WIPRO","ONGC","TITAN","ADANIENT","ADANIPORTS",
        "BAJAJFINSV","NESTLEIND","DRREDDY","SUNPHARMA","POWERGRID","NTPC","TECHM",
        "GRASIM","DIVISLAB","CIPLA","TATASTEEL","BPCL","EICHERMOT","COALINDIA",
        "HEROMOTOCO","APOLLOHOSP","HINDALCO","JSWSTEEL","TATACONSUM","HDFCLIFE",
        "SBILIFE","BRITANNIA","UPL","INDUSINDBK","M&M","TATAMOTORS","BAJAJ-AUTO","VEDL"
    ],
    "nifty200": [],   # filled from vcp_screener
    "midcap100": [],
    "smallcap100": [],
    "nifty500": [],
}


def _fetch_quote(symbol: str) -> dict | None:
    """Fetch latest daily quote for a single equity symbol."""
    ticker = symbol if symbol.endswith(".NS") else symbol + ".NS"
    try:
        tk = yf.Ticker(ticker)
        info = tk.fast_info
        price     = float(info.last_price)      if info.last_price      else None
        prev      = float(info.previous_close)  if info.previous_close  else None
        day_high  = float(info.day_high)        if info.day_high        else None
        day_low   = float(info.day_low)         if info.day_low         else None
        if price is None or prev is None or prev == 0:
            return None
        change_pct = round((price - prev) / prev * 100, 2)
        return {
            "symbol":     symbol,
            "price":      round(price, 2),
            "change_pct": change_pct,
            "high":       round(day_high, 2) if day_high else price,
            "low":        round(day_low,  2) if day_low  else price,
        }
    except Exception as e:
        logger.debug("Quote fetch failed for %s: %s", symbol, e)
        return None


def _fetch_index(symbol: str, name: str) -> dict | None:
    """Fetch latest data for an index symbol."""
    try:
        tk = yf.Ticker(symbol)
        info = tk.fast_info
        price     = float(info.last_price)     if info.last_price     else None
        prev      = float(info.previous_close) if info.previous_close else None
        day_high  = float(info.day_high)       if info.day_high       else None
        day_low   = float(info.day_low)        if info.day_low        else None
        if price is None or prev is None or prev == 0:
            return None
        change_pct = round((price - prev) / prev * 100, 2)
        return {
            "symbol":     symbol,
            "name":       name,
            "price":      round(price, 2),
            "change_pct": change_pct,
            "high":       round(day_high, 2) if day_high else price,
            "low":        round(day_low,  2) if day_low  else price,
        }
    except Exception as e:
        logger.debug("Index fetch failed for %s: %s", symbol, e)
        return None


def fetch_market_overview(category: str = "nifty50") -> dict:
    """Main entry point called by the FastAPI endpoint."""
    # --- Indices (always the same set) ---
    indices = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = {pool.submit(_fetch_index, sym, name): sym
                for sym, name in INDEX_SYMBOLS.items()}
        for fut in as_completed(futs):
            res = fut.result()
            if res:
                indices.append(res)
    indices.sort(key=lambda x: list(INDEX_SYMBOLS.keys()).index(x["symbol"])
                 if x["symbol"] in INDEX_SYMBOLS else 99)

    # --- Equity universe ---
    symbols = UNIVERSES.get(category, UNIVERSES["nifty50"])
    if not symbols:
        try:
            from execution.vcp_screener import get_nse_500_symbols
            all_syms = get_nse_500_symbols()
            if category == "nifty200":
                symbols = all_syms[:200]
            elif category == "midcap100":
                symbols = all_syms[50:150]
            elif category == "smallcap100":
                symbols = all_syms[200:300]
            else:
                symbols = all_syms
        except Exception:
            symbols = UNIVERSES["nifty50"]

    quotes = []
    with ThreadPoolExecutor(max_workers=15) as pool:
        futs = {pool.submit(_fetch_quote, s): s for s in symbols}
        for fut in as_completed(futs):
            res = fut.result()
            if res:
                quotes.append(res)

    quotes.sort(key=lambda x: x["change_pct"], reverse=True)
    top_gainers = quotes[:10]
    top_losers  = sorted(quotes, key=lambda x: x["change_pct"])[:10]

    return {
        "indices":     indices,
        "top_gainers": top_gainers,
        "top_losers":  top_losers,
        "category":    category,
        "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(fetch_market_overview("nifty50"), indent=2))
