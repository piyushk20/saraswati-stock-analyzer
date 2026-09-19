"""
execution/momentum30_screener.py
---------------------------------
Fetches live quotes for the Nifty 200 Momentum 30 index constituents.

Constituent resolution strategy (in priority order):
1. NSE India live API (nseindia.com/api/equity-stockIndices) -- gets BOTH
   the constituent list AND live prices in one call, always current.
2. Hardcoded fallback list -- used when NSE API is unavailable (e.g. market
   closed, rate-limited, or network issues).

The NSE India API is the official source; the hardcoded list reflects the
Sep-2026 rebalancing as provided by the user and is updated manually each
semi-annual rebalancing (March / September).
"""

import logging
import time
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf

try:
    from execution.yf_helper import get_ticker, get_yf_session
except ImportError:
    try:
        from yf_helper import get_ticker, get_yf_session
    except ImportError:
        def get_ticker(symbol):
            return yf.Ticker(symbol)
        def get_yf_session():
            return None

logger = logging.getLogger(__name__)

# ── Hardcoded fallback list (Sep 2026 rebalancing, provided by user) ─────────
MOMENTUM30_FALLBACK = [
    {"symbol": "ABB",         "name": "ABB India",                   "sector": "Capital Goods"},
    {"symbol": "ADANIENSOL",  "name": "Adani Energy Solutions",      "sector": "Power"},
    {"symbol": "ADANIGREEN",  "name": "Adani Green Energy",          "sector": "Power"},
    {"symbol": "ADANIPOWER",  "name": "Adani Power",                 "sector": "Power"},
    {"symbol": "ABCAPITAL",   "name": "Aditya Birla Capital",        "sector": "Financial Services"},
    {"symbol": "BSE",         "name": "BSE Ltd",                     "sector": "Financial Services"},
    {"symbol": "BHARATFORG",  "name": "Bharat Forge",                "sector": "Automobiles"},
    {"symbol": "BHEL",        "name": "Bharat Heavy Electricals",    "sector": "Capital Goods"},
    {"symbol": "CGPOWER",     "name": "CG Power & Industrial",       "sector": "Capital Goods"},
    {"symbol": "CUMMINSIND",  "name": "Cummins India",               "sector": "Capital Goods"},
    {"symbol": "FEDERALBNK",  "name": "Federal Bank",                "sector": "Financial Services"},
    {"symbol": "GEVERNOVA",   "name": "GE Vernova T&D India",        "sector": "Capital Goods"},
    {"symbol": "GLENMARK",    "name": "Glenmark Pharmaceuticals",    "sector": "Healthcare"},
    {"symbol": "HINDALCO",    "name": "Hindalco Industries",         "sector": "Metals & Mining"},
    {"symbol": "POWERINDIA",  "name": "Hitachi Energy India",        "sector": "Capital Goods"},
    {"symbol": "KEI",         "name": "KEI Industries",              "sector": "Capital Goods"},
    {"symbol": "LTF",         "name": "L&T Finance",                 "sector": "Financial Services"},
    {"symbol": "LAURUSLABS",  "name": "Laurus Labs",                 "sector": "Healthcare"},
    {"symbol": "MCX",         "name": "Multi Commodity Exchange",    "sector": "Financial Services"},
    {"symbol": "NTPC",        "name": "NTPC Ltd",                    "sector": "Power"},
    {"symbol": "NATIONALUM",  "name": "National Aluminium Co",       "sector": "Metals & Mining"},
    {"symbol": "POLYCAB",     "name": "Polycab India",               "sector": "Capital Goods"},
    {"symbol": "MOTHERSON",   "name": "Samvardhana Motherson",       "sector": "Automobiles"},
    {"symbol": "SHRIRAMFIN",  "name": "Shriram Finance",             "sector": "Financial Services"},
    {"symbol": "SOLARINDS",   "name": "Solar Industries",            "sector": "Chemicals"},
    {"symbol": "SAIL",        "name": "Steel Authority of India",    "sector": "Metals & Mining"},
    {"symbol": "TATASTEEL",   "name": "Tata Steel",                  "sector": "Metals & Mining"},
    {"symbol": "TORNTPHARM",  "name": "Torrent Pharmaceuticals",     "sector": "Healthcare"},
    {"symbol": "VEDL",        "name": "Vedanta Ltd",                 "sector": "Metals & Mining"},
    {"symbol": "IDEA",        "name": "Vodafone Idea",               "sector": "Telecom"},
]

MAX_WORKERS = 10

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}


def _fetch_nse_live():
    """
    Fetch constituent list AND live prices directly from NSE India's
    equity-stockIndices API. Returns list of dicts with symbol/name/
    sector/price/change_pct etc., or None on failure.
    
    NSE requires a real browser session (cookie warm-up on home page),
    then the actual API call works.
    """
    try:
        import requests
        session = requests.Session()
        session.headers.update(NSE_HEADERS)
        # Cookie warm-up
        warmup = session.get("https://www.nseindia.com", timeout=12)
        if warmup.status_code not in (200, 301, 302):
            logger.warning("NSE warmup failed: %s", warmup.status_code)
            return None
        time.sleep(1.5)
        # Fetch the index constituents + live prices
        resp = session.get(
            "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY200%20MOMENTUM%2030",
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning("NSE stockIndices API returned %s", resp.status_code)
            return None
        data = resp.json()
        rows = data.get("data", [])
        # First row is the index itself, skip it
        stocks_raw = [r for r in rows if r.get("symbol") and r.get("symbol") != "NIFTY200 MOMENTUM 30"]
        if len(stocks_raw) < 5:
            logger.warning("NSE API returned too few rows: %d", len(stocks_raw))
            return None
        results = []
        for r in stocks_raw:
            sym = r.get("symbol", "")
            price = r.get("lastPrice") or r.get("ltp")
            prev  = r.get("previousClose") or r.get("pClose")
            change_pct = r.get("pChange") or r.get("perChange")
            if not sym or price is None:
                continue
            price = float(price)
            prev  = float(prev) if prev else price
            change_pct = float(change_pct) if change_pct is not None else 0.0
            change_abs = round(price - prev, 2)
            results.append({
                "symbol":     sym,
                "name":       r.get("meta", {}).get("companyName", sym) if isinstance(r.get("meta"), dict) else r.get("companyName", sym),
                "sector":     r.get("meta", {}).get("industry", "—") if isinstance(r.get("meta"), dict) else "—",
                "price":      round(price, 2),
                "prev_close": round(prev, 2),
                "change_abs": change_abs,
                "change_pct": round(change_pct, 2),
                "source":     "nse_live",
            })
        logger.info("NSE live API returned %d constituents", len(results))
        return results if len(results) >= 5 else None
    except Exception as e:
        logger.warning("NSE live fetch failed: %s", e)
        return None


def _fetch_quote_yf(stock_meta):
    """Fetch live quote for a single stock via yfinance (fallback path)."""
    symbol = stock_meta["symbol"]
    ticker = symbol + ".NS"
    try:
        session = get_yf_session()
        tk = yf.Ticker(ticker, session=session) if session else yf.Ticker(ticker)
        info = tk.fast_info
        price = float(info.last_price)     if info.last_price     else None
        prev  = float(info.previous_close) if info.previous_close else None
        if price is None or prev is None or prev == 0:
            return None
        change_abs = round(price - prev, 2)
        change_pct = round(change_abs / prev * 100, 2)
        return {
            "symbol":     symbol,
            "name":       stock_meta["name"],
            "sector":     stock_meta["sector"],
            "price":      round(price, 2),
            "prev_close": round(prev, 2),
            "change_abs": change_abs,
            "change_pct": change_pct,
            "source":     "yfinance",
        }
    except Exception as e:
        logger.warning("yfinance quote failed for %s: %s", symbol, e)
        return None


def scan_momentum30():
    """
    Fetch live quotes for all Nifty 200 Momentum 30 stocks.
    Tries NSE India live API first (gets current constituents + live prices).
    Falls back to hardcoded list + yfinance if NSE API is unavailable.
    Returns dict: stocks, total, fetched, last_updated, source.
    """
    # --- Strategy 1: NSE India live API ---
    logger.info("Attempting NSE India live API for Momentum 30 constituents...")
    nse_results = _fetch_nse_live()
    
    if nse_results:
        nse_results.sort(key=lambda x: x["change_pct"], reverse=True)
        for i, r in enumerate(nse_results, 1):
            r["rank"] = i
        return {
            "stocks":       nse_results,
            "total":        len(nse_results),
            "fetched":      len(nse_results),
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source":       "NSE India (live)",
        }

    # --- Strategy 2: Hardcoded list + yfinance ---
    logger.info("NSE API unavailable, falling back to hardcoded list + yfinance...")
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_fetch_quote_yf, s): s for s in MOMENTUM30_FALLBACK}
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)
    results.sort(key=lambda x: x["change_pct"], reverse=True)
    for i, r in enumerate(results, 1):
        r["rank"] = i
    return {
        "stocks":       results,
        "total":        len(MOMENTUM30_FALLBACK),
        "fetched":      len(results),
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source":       "yfinance (fallback)",
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    data = scan_momentum30()
    print(json.dumps(data, indent=2))
