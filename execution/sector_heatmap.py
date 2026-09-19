"""
execution/sector_heatmap.py
----------------------------
Fetches live sectoral index performance and sparkline charts for the
interactive Sectoral Heat Map (StockeZee-style visualization).

Supports timeframes:
- Day : Intraday 5m data & today's % change
- 1W  : 5-day 15m data & 1-week % change
- 1M  : 1-month hourly data & 1-month % change
- 3M  : 3-month hourly data & 3-month % change
- 6M  : 6-month hourly data & 6-month % change
- 1Y  : 1-year hourly data & 1-year % change
"""

import logging
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import pandas as pd
import yfinance as yf

try:
    from execution.yf_helper import get_yf_session
except ImportError:
    try:
        from yf_helper import get_yf_session
    except ImportError:
        def get_yf_session():
            return None

logger = logging.getLogger("sector_heatmap")

# Complete list of 21 NSE Sectoral & Thematic Indices
# Matches all sectors from the StockeZee sector heatmap
ALL_SECTORS = [
    {"symbol": "^CNXFMCG",              "name": "Nifty FMCG"},
    {"symbol": "^CNXPSUBANK",           "name": "Nifty PSU Bank"},
    {"symbol": "^CNXREALTY",            "name": "Nifty Realty"},
    {"symbol": "^NSEBANK",              "name": "Nifty Bank"},
    {"symbol": "NIFTY_PVT_BANK.NS",     "name": "Nifty Private Bank"},
    {"symbol": "NIFTY_FIN_SERVICE.NS",  "name": "Nifty Financial Services"},
    {"symbol": "^CNXMEDIA",             "name": "Nifty Media"},
    {"symbol": "^CNXFIN",               "name": "Nifty Financial Services 25/50"},
    {"symbol": "NIFTY_OIL_AND_GAS.NS",  "name": "NIFTY OIL & GAS"},
    {"symbol": "^CNXMETAL",             "name": "Nifty Metal"},
    {"symbol": "^CNXAUTO",              "name": "Nifty Auto"},
    {"symbol": "NIFTY_CONSR_DURBL.NS",  "name": "NIFTY CONSUMER DURABLES"},
    {"symbol": "^CNXPHARMA",            "name": "Nifty Pharma"},
    {"symbol": "NIFTY_MIDSML_HLTH.NS",  "name": "Nifty MidSmall Healthcare"},
    {"symbol": "^CNXIT",                "name": "Nifty IT"},
    {"symbol": "NIFTY_HEALTHCARE.NS",   "name": "Nifty Healthcare"},
    {"symbol": "^CNXENERGY",            "name": "Nifty Energy"},
    {"symbol": "^CNXINFRA",             "name": "Nifty Infra"},
    {"symbol": "^CNXPSE",               "name": "Nifty PSE"},
    {"symbol": "^CNXCONSUM",            "name": "Nifty India Consumption"},
    {"symbol": "^CNXSERVICE",           "name": "Nifty Services Sector"},
]

TIMEFRAME_CONFIG = {
    "Day": {"range": "1d",  "interval": "5m",  "max_points": 50},
    "1W":  {"range": "5d",  "interval": "15m", "max_points": 50},
    "1M":  {"range": "1mo", "interval": "1h",  "max_points": 45},
    "3M":  {"range": "3mo", "interval": "1h",  "max_points": 50},
    "6M":  {"range": "6mo", "interval": "1h",  "max_points": 50},
    "1Y":  {"range": "1y",  "interval": "1h",  "max_points": 50},
}


def _downsample(arr: list, target_len: int = 45) -> list:
    """Evenly downsample a list of numeric points for smooth sparkline rendering."""
    if not arr or len(arr) <= target_len:
        return arr
    step = (len(arr) - 1) / (target_len - 1)
    sampled = []
    for i in range(target_len):
        idx = int(round(i * step))
        if idx >= len(arr):
            idx = len(arr) - 1
        sampled.append(arr[idx])
    return sampled


def fetch_sector_card_data(sector_meta: dict, timeframe: str = "Day") -> dict | None:
    symbol = sector_meta["symbol"]
    name = sector_meta["name"]
    cfg = TIMEFRAME_CONFIG.get(timeframe, TIMEFRAME_CONFIG["Day"])
    
    session = get_yf_session()
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
    params = {"range": cfg["range"], "interval": cfg["interval"]}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        r = session.get(url, params=params, headers=headers, timeout=10) if session else None
        if not r or r.status_code != 200:
            import requests
            r = requests.get(url, params=params, headers=headers, timeout=10)

        if r.status_code != 200:
            logger.warning(f"Failed HTTP {r.status_code} for {symbol}")
            return None

        data = r.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        res0 = result[0]
        meta = res0.get("meta", {})
        quotes = res0.get("indicators", {}).get("quote", [{}])[0]
        closes = quotes.get("close", [])
        
        # Clean null values
        clean_closes = [float(c) for c in closes if c is not None]
        if not clean_closes:
            return None

        # Price calculation
        latest_price = meta.get("regularMarketPrice")
        if not latest_price or latest_price <= 0:
            latest_price = clean_closes[-1]

        prev_close = meta.get("chartPreviousClose")
        
        if timeframe == "Day":
            if prev_close and prev_close > 0:
                base_price = prev_close
            elif len(clean_closes) > 1:
                base_price = clean_closes[0]
            else:
                base_price = latest_price
        else:
            # For 1W, 1M, 3M, 6M, 1Y: base is the first data point in range
            base_price = clean_closes[0]

        change_abs = latest_price - base_price
        change_pct = (change_abs / base_price * 100) if base_price > 0 else 0.0

        high_val = max(clean_closes) if clean_closes else latest_price
        low_val = min(clean_closes) if clean_closes else latest_price

        # Downsample sparkline to target points for fast browser rendering
        sparkline = _downsample([round(x, 2) for x in clean_closes], cfg["max_points"])

        clean_sym = symbol.replace(".NS", "").replace(".BO", "")

        return {
            "symbol": clean_sym,
            "raw_symbol": symbol,
            "name": name,
            "price": round(float(latest_price), 2),
            "change_pct": round(float(change_pct), 2),
            "change_abs": round(float(change_abs), 2),
            "high": round(float(high_val), 2),
            "low": round(float(low_val), 2),
            "sparkline": sparkline,
            "timeframe": timeframe,
        }
    except Exception as e:
        logger.error(f"Error fetching {name} ({symbol}): {e}")
        return None


def get_sector_heatmap_data(timeframe: str = "Day") -> dict:
    """
    Fetches all 21 sectoral indices concurrently and returns formatted cards.
    Sorted by % change descending (top gainers first).
    """
    if timeframe not in TIMEFRAME_CONFIG:
        timeframe = "Day"

    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_sector_card_data, s, timeframe) for s in ALL_SECTORS]
        for f in futures:
            res = f.result()
            if res:
                results.append(res)

    # Sort descending by change_pct
    results.sort(key=lambda x: x["change_pct"], reverse=True)

    return {
        "timeframe": timeframe,
        "total": len(ALL_SECTORS),
        "fetched": len(results),
        "sectors": results,
        "last_updated": datetime.now().strftime("%d-%b-%Y %H:%M:%S")
    }


if __name__ == "__main__":
    import json
    data = get_sector_heatmap_data("Day")
    print(f"Fetched {data['fetched']}/{data['total']} sectors:")
    for s in data["sectors"]:
        print(f"  {s['name']:<30} | LTP: {s['price']:10.2f} | Chg: {s['change_pct']:+6.2f}% | Spark: {len(s['sparkline'])} pts")
