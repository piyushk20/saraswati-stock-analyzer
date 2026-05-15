import pandas as pd
import numpy as np
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import logging
from datetime import datetime, timedelta

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vcp_screener")

# ── Configuration ─────────────────────────────────────────────────────────────
VCP_CONFIG = {
    "MAX_WORKERS": 50,
    "DATA_PERIOD": "2y",
    "SYMBOL_CAP":  500,
}

def cal_slope(arr):
    """Manual simple linear regression: slope = cov(x,y) / var(x)"""
    y = np.array(arr)
    x = np.arange(len(y))
    n = len(y)
    if n < 2: return 0.0
    x_mean = np.mean(x)
    y_mean = np.mean(y)
    numerator = np.sum((x - x_mean) * (y - y_mean))
    denominator = np.sum((x - x_mean) ** 2)
    if denominator == 0: return 0.0
    return numerator / denominator

def filter_by_vcp_conditions(df):
    """Apply Mark Minervini's Trend Template & VCP logic."""
    if len(df) < 200:
        df['Has_fulfilled'] = False
        return df[['Close', 'Has_fulfilled']]
        
    # SMAs
    df['SMA_50']  = df['Close'].rolling(window=50).mean()
    df['SMA_150'] = df['Close'].rolling(window=150).mean()
    df['SMA_200'] = df['Close'].rolling(window=200).mean()
    
    # Slopes for trend validation
    df['SMA_slope_200'] = df['SMA_200'].rolling(window=20).apply(cal_slope, raw=True)
    
    # 52-Week High/Low
    df['52_week_low']  = df['Close'].rolling(window=252).min()
    df['52_week_high'] = df['Close'].rolling(window=252).max()

    # Condition 1: Price > 150 MA & 200 MA
    c1 = (df['Close'] > df['SMA_150']) & (df['Close'] > df['SMA_200']) 
    # Condition 2: 150 MA > 200 MA
    c2 = (df['SMA_150'] > df['SMA_200']) 
    # Condition 3: 200 MA trending up for at least 1 month
    c3 = df['SMA_slope_200'] > 0.0
    # Condition 4: 50 MA > 150 MA & 200 MA
    c4 = (df['SMA_50'] > df['SMA_150']) & (df['SMA_150'] > df['SMA_200']) 
    # Condition 5: Price > 50MA
    c5 = (df['Close'] > df['SMA_50'])
    # Condition 6: Price > 52-week low + 25%
    c6 = (df['Close'] > df['52_week_low'] * 1.25) 
    # Condition 7: Price within 25% of 52-week high
    c7 = (df['Close'] > df['52_week_high'] * 0.75) 
    
    # Condition 8: Consolidation / Tightness (VCP Handle)
    # Check if max contraction in last 10-40 days is < 10%
    contraction = (df['Close'].rolling(window=20).max() - df['Close'].rolling(window=20).min()) / df['Close'].rolling(window=20).min()
    c8 = contraction < 0.12 # Slightly relaxed for broader discovery
    
    df['Has_fulfilled'] = c1 & c2 & c3 & c4 & c5 & c6 & c7 & c8

    return df[['Close', 'Has_fulfilled']]

def get_nse_500_symbols():
    """Fetch Nifty 500 symbols from NSE or local fallback."""
    url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        import requests
        from io import StringIO
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            df = pd.read_csv(StringIO(res.text))
            return [f"{s.strip()}.NS" for s in df['Symbol'].tolist() if s]
    except:
        pass
    
    # Fallback to local
    try:
        local_path = os.path.join(os.path.dirname(__file__), "..", "ind_nifty500list.csv")
        if os.path.exists(local_path):
            df = pd.read_csv(local_path)
            return [f"{s.strip()}.NS" for s in df['Symbol'].tolist() if s]
    except:
        pass
        
    return ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS"]

def _fetch_and_analyze(symbol: str) -> dict | None:
    """Analyze a single symbol for VCP."""
    try:
        t = yf.Ticker(symbol)
        df = t.history(period=VCP_CONFIG["DATA_PERIOD"], interval="1d", auto_adjust=True, timeout=10)
        
        if df is None or len(df) < 200:
            return None
            
        df = df.dropna(subset=["Close"])
        res_df = filter_by_vcp_conditions(df.copy())
        
        if res_df['Has_fulfilled'].iloc[-1]:
            return {
                "symbol": symbol.replace(".NS", ""),
                "price": round(float(res_df['Close'].iloc[-1]), 2)
            }
    except:
        pass
    return None

def scan_vcp():
    """Main VCP scanning orchestrator."""
    symbols = get_nse_500_symbols()[:VCP_CONFIG["SYMBOL_CAP"]]
    logger.info(f"Scanning {len(symbols)} symbols for VCP conditions...")
    
    vcp_stocks = []
    with ThreadPoolExecutor(max_workers=VCP_CONFIG["MAX_WORKERS"]) as pool:
        futures = {pool.submit(_fetch_and_analyze, s): s for s in symbols}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                vcp_stocks.append(res)
                
    vcp_stocks.sort(key=lambda x: x['symbol'])
    logger.info(f"VCP scan complete. Found {len(vcp_stocks)} stocks.")
    return {"vcp_stocks": vcp_stocks}

def run_vcp_screener():
    return scan_vcp()

if __name__ == "__main__":
    print(json.dumps(scan_vcp(), indent=2))
