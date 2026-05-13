import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("screener")

# Define universes
MAJOR_INDEXES = ["^NSEI", "^NSEBANK", "^CNXIT", "^CNXAUTO", "^CNXPHARMA"]
NIFTY_50 = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "BHARTIARTL.NS",
    "SBIN.NS", "INFY.NS", "LICI.NS", "ITC.NS", "HINDUNILVR.NS",
    "LT.NS", "BAJFINANCE.NS", "HCLTECH.NS", "MARUTI.NS", "SUNPHARMA.NS",
    "TATAMOTORS.NS", "ONGC.NS", "KOTAKBANK.NS", "NTPC.NS", "AXISBANK.NS",
    "M&M.NS", "POWERGRID.NS", "ULTRACEMCO.NS", "ASIANPAINT.NS", "BAJAJFINSV.NS",
    "COALINDIA.NS", "TITAN.NS", "ADANIPORTS.NS", "TATASTEEL.NS", "HAL.NS",
    "ADANIENT.NS", "WIPRO.NS", "NESTLEIND.NS", "GRASIM.NS", "TECHM.NS",
    "INDUSINDBK.NS", "HEROMOTOCO.NS", "HINDALCO.NS", "SBILIFE.NS",
    "DRREDDY.NS", "HDFCLIFE.NS", "BAJAJ-AUTO.NS", "CIPLA.NS", "BRITANNIA.NS",
    "TATACONSUM.NS", "APOLLOHOSP.NS", "EICHERMOT.NS", "DIVISLAB.NS", "UPL.NS"
]

def get_universe_symbols(category="nifty50"):
    """Returns a list of symbols for the given category."""
    try:
        if category == "nifty50":
            return NIFTY_50
            
        import os
        csv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ind_nifty500list.csv")
        
        if not os.path.exists(csv_path):
            return NIFTY_50
            
        df = pd.read_csv(csv_path)
        symbols = [f"{s}.NS" for s in df['Symbol'].tolist()]
        
        if category == "nifty200":
            return symbols[:200]
        elif category == "midcap100":
            return symbols[100:200]
        elif category == "smallcap100":
            return symbols[250:350]
        elif category == "nifty500":
            return symbols
            
        return NIFTY_50
    except Exception as e:
        logger.error(f"Error loading universe {category}: {e}")
        return NIFTY_50

def _analyze_crossover(symbol: str, seven_days_ago) -> list:
    """Analyze a single symbol for crossovers in the last 7 days."""
    try:
        t = yf.Ticker(symbol)
        df = t.history(period="6mo", interval="1d", auto_adjust=True, timeout=10)
        
        if df is None or len(df) < 50:
            return []
            
        df = df.dropna(subset=["Close"])
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        
        df['prev_SMA_20'] = df['SMA_20'].shift(1)
        df['prev_SMA_50'] = df['SMA_50'].shift(1)
        
        # Golden Cross
        golden = (df['prev_SMA_20'] <= df['prev_SMA_50']) & (df['SMA_20'] > df['SMA_50'])
        # Death Cross
        death = (df['prev_SMA_20'] >= df['prev_SMA_50']) & (df['SMA_20'] < df['SMA_50'])
        
        found = []
        for date, row in df[golden].iterrows():
            if pd.to_datetime(date.date()) >= seven_days_ago:
                found.append({
                    "symbol": symbol,
                    "type": "Golden Cross",
                    "date": date.strftime("%Y-%m-%d"),
                    "price": round(float(row['Close']), 2)
                })
                
        for date, row in df[death].iterrows():
            if pd.to_datetime(date.date()) >= seven_days_ago:
                found.append({
                    "symbol": symbol,
                    "type": "Death Cross",
                    "date": date.strftime("%Y-%m-%d"),
                    "price": round(float(row['Close']), 2)
                })
        return found
    except:
        return []

def find_crossovers(category="nifty50"):
    """Orchestrate SMA crossover scan using thread pool."""
    base_symbols = get_universe_symbols(category)
    symbols = list(set(MAJOR_INDEXES + base_symbols))
    
    seven_days_ago = pd.to_datetime((datetime.now() - timedelta(days=7)).date())
    crossovers = []
    
    logger.info(f"Scanning {len(symbols)} symbols for crossovers...")
    
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_analyze_crossover, s, seven_days_ago): s for s in symbols}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                crossovers.extend(res)
                
    crossovers.sort(key=lambda x: x['date'], reverse=True)
    return {"crossovers": crossovers}

if __name__ == "__main__":
    import json
    print(json.dumps(find_crossovers(), indent=2))
