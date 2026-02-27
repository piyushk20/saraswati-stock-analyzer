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
    fallback_universe = [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", 
        "HINDUNILVR.NS", "SBI.NS", "BHARTIARTL.NS", "ITC.NS", "BAJFINANCE.NS",
        "ASIANPAINT.NS", "HCLTECH.NS", "MARUTI.NS", "SUNPHARMA.NS", "TITAN.NS",
        "ULTRACEMCO.NS", "TATASTEEL.NS", "NTPC.NS", "POWERGRID.NS", "ONGC.NS",
        "M&M.NS", "KOTAKBANK.NS", "LT.NS", "WIPRO.NS", "AXISBANK.NS",
        "BAJAJFINSV.NS", "NESTLEIND.NS", "JSWSTEEL.NS", "TECHM.NS", "HDFCLIFE.NS",
        "TVSMOTOR.NS", "HINDALCO.NS", "GRASIM.NS", "CIPLA.NS", "HEROMOTOCO.NS",
        "APOLLOHOSP.NS", "DIVISLAB.NS", "SBILIFE.NS", "TATAMOTORS.NS", "SHREECEM.NS",
        "ADANIENT.NS", "ADANIPORTS.NS", "EICHERMOT.NS", "UPL.NS", "DRREDDY.NS",
        "BRITANNIA.NS", "INDUSINDBK.NS", "COALINDIA.NS", "BPCL.NS", "RECLTD.NS",
        "ZOMATO.NS", "TRENT.NS", "AARTIIND.NS", "ABBOTINDIA.NS", "ALKEM.NS",
        "AUROPHARMA.NS", "BOSCHLTD.NS", "CHOLAFIN.NS", "CUMMINSIND.NS",
        "DABUR.NS", "DIXON.NS", "ESCORTS.NS", "HAVELLS.NS",
        "ICICIGI.NS", "INDIGO.NS", "JUBLFOOD.NS", "LTIM.NS",
        "MARICO.NS", "MUTHOOTFIN.NS", "NAUKRI.NS", "NAVINFLUOR.NS",
        "PEL.NS", "PERSISTENT.NS", "PETRONET.NS", "PIDILITIND.NS",
        "POLYCAB.NS", "SRF.NS", "TATACOMM.NS", "TATACONSUM.NS",
        "TATAPOWER.NS", "TORNTPOWER.NS", "VOLTAS.NS"
    ]
    try:
        import requests
        from io import StringIO
        url = "https://en.wikipedia.org/wiki/NIFTY_500"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        res = requests.get(url, headers=headers, timeout=10)
        tables = pd.read_html(StringIO(res.text))
        for df in tables:
            if 'Symbol' in df.columns:
                symbols = df['Symbol'].tolist()
                return [f"{s}.NS" for s in symbols]
        
        return fallback_universe
    except Exception as e:
        print("Could not fetch NSE 500 from Wikipedia:", e)
        return fallback_universe

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

if __name__ == "__main__":
    result = scan_vcp()
    print(json.dumps(result, indent=2))
