import yfinance as yf
import pandas as pd
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configure logging
logger = logging.getLogger("market_overview")

# Define Major Indices
INDICES = {
    "^NSEI": "NIFTY 50",
    "^BSESN": "SENSEX",
    "^NSEBANK": "NIFTY BANK",
    "^CNXIT": "NIFTY IT"
}

def get_universe_symbols(category="nifty50"):
    """Fetch symbols based on category."""
    nifty50 = [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "BHARTIARTL.NS",
        "SBIN.NS", "INFY.NS", "LICI.NS", "ITC.NS", "HINDUNILVR.NS",
        "LT.NS", "BAJFINANCE.NS", "HCLTECH.NS", "MARUTI.NS", "SUNPHARMA.NS",
        "ONGC.NS", "TATAMOTORS.NS", "NTPC.NS", "KOTAKBANK.NS", "TITAN.NS",
        "ADANIENT.NS", "ASIANPAINT.NS", "BAJAJFINSV.NS", "HAL.NS", "ULTRACEMCO.NS",
        "M&M.NS", "COALINDIA.NS", "POWERGRID.NS", "BAJAJ-AUTO.NS", "WIPRO.NS",
        "LTIM.NS", "ADANIPORTS.NS", "NESTLEIND.NS", "GRASIM.NS", "TECHM.NS",
        "HINDZINC.NS", "TATASTEEL.NS", "PIDILITIND.NS", "HDFCLIFE.NS", "IOC.NS",
        "SBILIFE.NS", "BRITANNIA.NS", "DRREDDY.NS", "APOLLOHOSP.NS", "INDIGO.NS",
        "CIPLA.NS", "EICHERMOT.NS", "TATACONSUM.NS", "DIVISLAB.NS", "BPCL.NS"
    ]
    if category == "nifty50":
        return nifty50
        
    try:
        import os
        csv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ind_nifty500list.csv")
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            symbols = [f"{s}.NS" for s in df['Symbol'].tolist()]
            if category == "nifty200": return symbols[:200]
            elif category == "midcap100": return symbols[100:200]
            elif category == "smallcap100": return symbols[250:350]
            elif category == "nifty500": return symbols
        return nifty50
    except:
        return nifty50

def _fetch_single_overview(symbol: str, name: str = None) -> dict | None:
    """Fetch 5-day performance for a single symbol."""
    try:
        t = yf.Ticker(symbol)
        df = t.history(period="5d", interval="1d", auto_adjust=True, timeout=10)
        
        if df is None or len(df) < 2:
            return None
            
        df = df.dropna(subset=["Close"])
        curr = float(df['Close'].iloc[-1])
        prev = float(df['Close'].iloc[-2])
        high = float(df['High'].iloc[-1])
        low  = float(df['Low'].iloc[-1])
        
        return {
            "symbol": symbol,
            "name": name or symbol.replace(".NS", ""),
            "price": round(curr, 2),
            "change_pct": round(((curr - prev) / prev) * 100, 2),
            "high": round(high, 2),
            "low": round(low, 2)
        }
    except:
        return None

def fetch_market_overview(category="nifty50"):
    """Fetch market overview with parallel processing."""
    results = {
        "indices": [],
        "top_gainers": [],
        "top_losers": []
    }
    
    # 1. Fetch Indices
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_fetch_single_overview, s, n): s for s, n in INDICES.items()}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                results["indices"].append(res)
                
    # 2. Fetch Universe for Gainers/Losers
    universe = get_universe_symbols(category)
    performance = []
    
    logger.info(f"Fetching overview for {len(universe)} symbols in {category}...")
    
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_fetch_single_overview, s): s for s in universe}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                performance.append(res)
                
    # Sort and slice
    performance.sort(key=lambda x: x["change_pct"], reverse=True)
    results["top_gainers"] = performance[:5]
    
    losers = performance[-5:]
    losers.sort(key=lambda x: x["change_pct"])
    results["top_losers"] = losers
    
    return results

if __name__ == "__main__":
    print(json.dumps(fetch_market_overview(), indent=2))
