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
try:
    from execution.yf_helper import get_ticker, get_historical_data_safe, get_yf_session
except ImportError:
    try:
        from yf_helper import get_ticker, get_historical_data_safe, get_yf_session
    except ImportError:
        def get_ticker(symbol):
            return yf.Ticker(symbol)
        def get_historical_data_safe(symbol, period="5y"):
            return yf.Ticker(symbol).history(period=period)
        def get_yf_session():
            return None

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
    "sectors": [
        "^CNXFMCG", "^CNXPSUBANK", "^CNXREALTY", "^NSEBANK", "NIFTY_PVT_BANK.NS",
        "NIFTY_FIN_SERVICE.NS", "^CNXMEDIA", "^CNXFIN", "NIFTY_OIL_AND_GAS.NS",
        "^CNXMETAL", "^CNXAUTO", "NIFTY_CONSR_DURBL.NS", "^CNXPHARMA",
        "NIFTY_MIDSML_HLTH.NS", "^CNXIT", "NIFTY_HEALTHCARE.NS", "^CNXENERGY",
        "^CNXINFRA", "^CNXPSE", "^CNXCONSUM", "^CNXSERVICE"
    ],
    "midcap100": [],
    "smallcap100": [],
    "midcap150": [],
    "smallcap250": [],
    "microcap250": [],
    "nifty500": [],
}


def _fetch_quote(symbol: str) -> dict | None:
    """Fetch latest daily quote for a single equity symbol."""
    # Suffix logic for indices vs regular equities
    ticker = symbol if (symbol.endswith((".NS", ".BO")) or symbol.startswith("^")) else symbol + ".NS"
    try:
        session = get_yf_session()
        tk = yf.Ticker(ticker, session=session) if session else yf.Ticker(ticker)
        info = tk.fast_info
        price      = float(info.last_price)      if info.last_price      else None
        prev       = float(info.previous_close)  if info.previous_close  else None
        day_high   = float(info.day_high)        if info.day_high        else None
        day_low    = float(info.day_low)         if info.day_low         else None
        volume     = float(info.last_volume)     if info.last_volume     else None
        avg_volume = float(info.three_month_average_volume) if info.three_month_average_volume else None
        
        if price is None or prev is None or prev == 0:
            return None
        change_pct = round((price - prev) / prev * 100, 2)
        vol_ratio = round(volume / avg_volume, 2) if (volume and avg_volume and avg_volume > 0) else 1.0
        
        return {
            "symbol":     symbol,
            "price":      round(price, 2),
            "change_pct": change_pct,
            "high":       round(day_high, 2) if day_high else price,
            "low":        round(day_low,  2) if day_low  else price,
            "vol_ratio":  vol_ratio,
        }
    except Exception as e:
        logger.exception("Quote fetch failed for %s: %s", symbol, e)
        return None


def _fetch_index(symbol: str, name: str) -> dict | None:
    """Fetch latest data for an index symbol."""
    try:
        session = get_yf_session()
        tk = yf.Ticker(symbol, session=session) if session else yf.Ticker(symbol)
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
        logger.exception("Index fetch failed for %s: %s", symbol, e)
        return None


def get_sector_distribution(category: str, quotes: list = None) -> list:
    import os
    import pandas as pd
    import numpy as np

    # For sectoral category, return each index as its own "sector" row
    if category == "sectors" and quotes:
        SECTOR_LABELS = {
            "^NSEBANK":  "BANK NIFTY",
            "^CNXIT":    "NIFTY IT",
            "^CNXAUTO":  "NIFTY AUTO",
            "^CNXFMCG":  "NIFTY FMCG",
            "^CNXMETAL": "NIFTY METAL",
            "^CNXPHARMA":"NIFTY PHARMA",
            "^CNXREALTY":"NIFTY REALTY",
            "^CNXENERGY":"NIFTY ENERGY",
            "^CNXINFRA": "NIFTY INFRA",
            "^CNXFIN":   "NIFTY FIN SERV",
            "^CNXPSE":   "NIFTY PSE",
            "^CNXCOMM":  "NIFTY COMMS",
            "^CNXCONSUM":"NIFTY CONSUM DURABLES",
        }
        dist = []
        for q in quotes:
            sym = q["symbol"]
            label = SECTOR_LABELS.get(sym, sym)
            change = q.get("change_pct", 0.0)
            vol_ratio = q.get("vol_ratio", 1.0)
            if change > 0.4 and vol_ratio > 1.15:
                flow = "Smart Money In"
            elif change < -0.4 and vol_ratio > 1.15:
                flow = "Smart Money Out"
            elif change > 0.1:
                flow = "Positive Flow"
            elif change < -0.1:
                flow = "Negative Flow"
            else:
                flow = "Neutral Flow"
            dist.append({
                "sector": label,
                "count": 1,
                "percentage": round(100.0 / max(len(quotes), 1), 2),
                "change": round(change, 2),
                "vol_ratio": round(vol_ratio, 2),
                "flow": flow
            })
        dist.sort(key=lambda x: x["change"], reverse=True)
        return dist

    # Map category to CSV file
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    csv_map = {
        "nifty500": "ind_nifty500list.csv",
        "nifty200": "ind_nifty500list.csv",
        "nifty50": "ind_nifty500list.csv",
        "midcap150": "ind_niftymidcap150list.csv",
        "midcap100": "ind_niftymidcap150list.csv",
        "smallcap250": "ind_niftysmallcap250list.csv",
        "smallcap100": "ind_niftysmallcap250list.csv",
        "microcap250": "ind_niftymicrocap250_list.csv"
    }
    
    filename = csv_map.get(category, "ind_nifty500list.csv")
    csv_path = os.path.join(base_dir, filename)
    
    if not os.path.exists(csv_path):
        return []
        
    try:
        df = pd.read_csv(csv_path)
        df["Symbol_clean"] = df["Symbol"].str.strip()
        
        # Get the actual symbols in the category
        from execution.vcp_screener import (
            get_nse_500_symbols,
            get_midcap_150_symbols,
            get_smallcap_250_symbols,
            get_microcap_250_symbols
        )
        
        if category == "nifty50":
            cat_syms = [s.replace(".NS", "") for s in UNIVERSES["nifty50"]]
        elif category == "nifty200":
            cat_syms = [s.replace(".NS", "") for s in get_nse_500_symbols()[:200]]
        elif category == "midcap150":
            cat_syms = [s.replace(".NS", "") for s in get_midcap_150_symbols()]
        elif category == "midcap100":
            cat_syms = [s.replace(".NS", "") for s in get_midcap_150_symbols()[:100]]
        elif category == "smallcap250":
            cat_syms = [s.replace(".NS", "") for s in get_smallcap_250_symbols()]
        elif category == "smallcap100":
            cat_syms = [s.replace(".NS", "") for s in get_smallcap_250_symbols()[:100]]
        elif category == "microcap250":
            cat_syms = [s.replace(".NS", "") for s in get_microcap_250_symbols()]
        else: # nifty500
            cat_syms = [s.replace(".NS", "") for s in get_nse_500_symbols()]
            
        filtered_df = df[df["Symbol_clean"].isin(cat_syms)]
        if filtered_df.empty:
            filtered_df = df
            
        # Create mapping of symbol -> sector
        symbol_to_sector = dict(zip(filtered_df["Symbol_clean"], filtered_df["Industry"]))
        
        # Group quotes by sector
        sector_quotes = {}
        if quotes:
            for q in quotes:
                sym_clean = q["symbol"].replace(".NS", "")
                sec = symbol_to_sector.get(sym_clean)
                if sec:
                    if sec not in sector_quotes:
                        sector_quotes[sec] = []
                    sector_quotes[sec].append(q)
                    
        counts = filtered_df["Industry"].value_counts()
        total = len(filtered_df)
        
        dist = []
        for ind, count in counts.items():
            sec_qs = sector_quotes.get(ind, [])
            avg_change = 0.0
            avg_vol_ratio = 1.0
            
            if sec_qs:
                avg_change = float(np.mean([q.get("change_pct", 0.0) for q in sec_qs]))
                avg_vol_ratio = float(np.mean([q.get("vol_ratio", 1.0) for q in sec_qs]))
                
            # Smart money flow status:
            # If average change is positive and average volume ratio is high -> Accumulation (Smart Money In)
            # If average change is negative and average volume ratio is high -> Distribution (Smart Money Out / Laggard)
            if avg_change > 0.4 and avg_vol_ratio > 1.15:
                flow = "Smart Money In"
            elif avg_change < -0.4 and avg_vol_ratio > 1.15:
                flow = "Smart Money Out"
            elif avg_change > 0.1:
                flow = "Positive Flow"
            elif avg_change < -0.1:
                flow = "Negative Flow"
            else:
                flow = "Neutral Flow"
                
            dist.append({
                "sector": ind,
                "count": int(count),
                "percentage": round((count / total) * 100, 2),
                "change": round(avg_change, 2),
                "vol_ratio": round(avg_vol_ratio, 2),
                "flow": flow
            })
            
        dist.sort(key=lambda x: x["count"], reverse=True)
        return dist
    except Exception as e:
        logger.error(f"Error computing sector distribution: {e}")
        return []

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
        "sector_distribution": get_sector_distribution(category, quotes),
        "category":    category,
        "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(fetch_market_overview("nifty50"), indent=2))
