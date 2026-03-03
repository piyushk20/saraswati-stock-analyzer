import pandas as pd
import numpy as np
from scipy.stats import linregress
import yfinance as yf
import concurrent.futures
from tqdm import tqdm
import json
import os
import traceback

def cal_slope(arr):
    y = np.array(arr)
    x = np.arange(len(y))
    slope, intercept, rvalue, pvalue, stderr = linregress(x, y)
    return slope

def filter_by_vcp_conditions(df):
    if len(df) < 260: # need at least a year of data
        df['Has_fulfilled'] = False
        return df[['Close', 'Has_fulfilled']]
        
    moving_averages = [10, 20, 30, 50, 150, 200]
    for ma in moving_averages:
        df['SMA_' + str(ma)] = round(df['Close'].rolling(window=ma).mean(), 2)
        
    df['Avg_vol_50'] = round(df['Volume'].rolling(window=50).mean(), 2)
    df['SMA_slope_30'] = df['SMA_30'].rolling(window=20).apply(cal_slope, raw=True)
    df['SMA_slope_200'] = df['SMA_200'].rolling(window=20).apply(cal_slope, raw=True)
    df['52_week_low'] = df['Close'].rolling(window=5*52).min()
    df['52_week_high'] = df['Close'].rolling(window=5*52).max()

    # Condition 1: Price > 150 MA & 200 MA
    df['Condition1'] = (df['Close'] > df['SMA_150']) & (df['Close'] > df['SMA_200']) 
    # Condition 2: 150 MA > 200 MA
    df['Condition2'] = (df['SMA_150'] > df['SMA_200']) 
    # Condition 3: 200 MA trending up for at least 1 month
    df['Condition3'] = df['SMA_slope_200'] > 0.0
    # Condition 4: 50 MA > 150 MA & 200 MA
    df['Condition4'] = (df['SMA_50'] > df['SMA_150']) & (df['SMA_150'] > df['SMA_200']) 
    # Condition 5: Price > 50MA
    df['Condition5'] = (df['Close'] > df['SMA_50'])
    # Condition 6: Price > 52-week low + 25%
    df['Condition6'] = (df['Close'] > df['52_week_low']* 1.25) 
    # Condition 7: Price > 52-week high - 25%
    df['Condition7'] = (df['Close'] > df['52_week_high']* 0.75) 
    # Condition 8: Pivot (5 day) Breakout
    winsize = 5
    df['Condition8'] = df['Close'] > ((df['Close']).rolling(window=winsize).mean() + (df['Close']).rolling(window=winsize).max() + (df['Close']).rolling(window=winsize).min())/3 
    
    # Condition 9: Contraction below 10%
    cond9_cols = []
    for handlesize in range(5, 41):
        col_name = f'Condition9.{handlesize}'
        df[col_name] = ((df['Close']).rolling(window=handlesize).max() - (df['Close']).rolling(window=handlesize).min()) / (df['Close']).rolling(window=handlesize).min() < 0.1
        cond9_cols.append(col_name)
    
    df['Condition9'] = df[cond9_cols].any(axis='columns')
    
    df['Has_fulfilled'] = df[['Condition1','Condition2','Condition3','Condition4','Condition5','Condition6','Condition7','Condition8','Condition9']].all(axis='columns')

    return df[['Close','Has_fulfilled']]

def get_nse_500_symbols():
    url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        import requests
        from io import StringIO
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            df = pd.read_csv(StringIO(res.text))
            if 'Symbol' in df.columns:
                symbols = df['Symbol'].tolist()
                # Clean symbols and add .NS suffix
                clean_symbols = [f"{str(s).strip()}.NS" for s in symbols if s]
                return clean_symbols
        
        # Fallback to local file if request fails
        import os
        from pathlib import Path
        local_csv_path = Path(os.path.dirname(os.path.abspath(__file__))) / ".." / "ind_nifty500list.csv"
        
        if local_csv_path.exists():
            df = pd.read_csv(local_csv_path)
            if 'Symbol' in df.columns:
                symbols = df['Symbol'].tolist()
                return [f"{str(s).strip()}.NS" for s in symbols if s]
                
        # Ultimate fallback
        return [
            "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", 
            "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "BAJFINANCE.NS"
        ]
    except Exception as e:
        print("Could not fetch NSE 500 from official source or local file:", e)
        # Ultimate fallback
        return [
            "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", 
            "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "BAJFINANCE.NS"
        ]

def process_stock(ticker_string):
    try:
        ticker = yf.Ticker(ticker_string)
        # Fetching 2 years data is enough for 200 EMA + 52-week highs/lows
        ticker_history = ticker.history(period='2y')
        if ticker_history.empty:
            return None
            
        data = filter_by_vcp_conditions(ticker_history)
        if data['Has_fulfilled'].tail(1).iloc[0] == True:
            current_price = data['Close'].tail(1).iloc[0]
            return {
                "symbol": ticker_string,
                "price": round(float(current_price), 2)
            }
        return None
    except Exception:
        return None

def scan_vcp():
    try:
        symbols = get_nse_500_symbols()
        print(f"Scanning {len(symbols)} symbols for VCP conditions...")
        vcp_stocks = []
        
        # Use ThreadPoolExecutor for I/O bound yfinance calls
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = {executor.submit(process_stock, symbol): symbol for symbol in symbols}
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result:
                    vcp_stocks.append(result)
        
        return {"vcp_stocks": vcp_stocks}
                
    except Exception as e:
        return {"error": f"Failed to run VCP scan: {str(e)}\n{traceback.format_exc()}"}

def run_vcp_screener():
    """Entry point for the backend to run the VCP scan."""
    return scan_vcp()

if __name__ == "__main__":
    results = run_vcp_screener()
    print(json.dumps(results, indent=2))
