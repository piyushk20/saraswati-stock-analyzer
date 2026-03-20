import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# Define our universe of stocks and indices to scan
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
        # For Nifty 50, use the hardcoded list for speed/reliability
        if category == "nifty50":
            return NIFTY_50
            
        import os
        import pandas as pd
        csv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ind_nifty500list.csv")
        
        if not os.path.exists(csv_path):
            return NIFTY_50
            
        df = pd.read_csv(csv_path)
        symbols = [f"{s}.NS" for s in df['Symbol'].tolist()]
        
        if category == "nifty200":
            return symbols[:200]
        elif category == "midcap100":
            # Roughly ranks 101-200 in the 500 list are midcaps
            return symbols[100:200]
        elif category == "smallcap100":
            # Roughly ranks 251-350 in the 500 list are smallcaps
            return symbols[250:350]
        elif category == "nifty500":
            return symbols
            
        return NIFTY_50
    except Exception as e:
        logger.error(f"Error loading universe {category}: {e}")
        return NIFTY_50

def find_crossovers(category="nifty50"):
    """
    Downloads 6 months of daily data for the specified universe.
    Calculates 20/50 SMA and finds symbols that had a Golden or Death cross 
    within the last 7 calendar days.
    """
    base_symbols = get_universe_symbols(category)
    # Always include major indices for context in the screener
    symbols = list(set(MAJOR_INDEXES + base_symbols))
    crossovers = []
    
    # 7 days ago at midnight
    seven_days_ago = pd.to_datetime((datetime.now() - timedelta(days=7)).date())
    
    try:
        # Download data for all symbols efficiently
        data = yf.download(symbols, period="6mo", progress=False, threads=True)
        
        # Check if we got data
        if 'Close' in data:
            close_prices = data['Close']
        else:
            return {"error": "Failed to extract Close prices from Yahoo Finance."}
            
        for symbol in symbols:
            try:
                # Handle single column vs multi-column
                if isinstance(close_prices, pd.Series):
                    if symbol != symbols[0]:
                        continue
                    df = close_prices.dropna().to_frame(name='Close')
                else:
                    if symbol not in close_prices.columns:
                        continue
                    df = close_prices[[symbol]].dropna().copy()
                    df.columns = ['Close']
                
                # Minimum 50 days needed for SMA_50
                if len(df) < 50:
                    continue
                    
                # Calculate SMAs
                df['SMA_20'] = df['Close'].rolling(window=20).mean()
                df['SMA_50'] = df['Close'].rolling(window=50).mean()
                
                # Check for crossovers
                df['prev_SMA_20'] = df['SMA_20'].shift(1)
                df['prev_SMA_50'] = df['SMA_50'].shift(1)
                
                # Golden Cross: prev 20 <= prev 50 AND curr 20 > curr 50
                golden = (df['prev_SMA_20'] <= df['prev_SMA_50']) & (df['SMA_20'] > df['SMA_50'])
                
                # Death Cross: prev 20 >= prev 50 AND curr 20 < curr 50
                death = (df['prev_SMA_20'] >= df['prev_SMA_50']) & (df['SMA_20'] < df['SMA_50'])
                
                # Iterate through matched dates
                for date, row in df[golden].iterrows():
                    if date >= seven_days_ago:
                        crossovers.append({
                            "symbol": symbol,
                            "type": "Golden Cross",
                            "date": date.strftime("%Y-%m-%d"),
                            "price": round(row['Close'], 2)
                        })
                        
                for date, row in df[death].iterrows():
                    if date >= seven_days_ago:
                        crossovers.append({
                            "symbol": symbol,
                            "type": "Death Cross",
                            "date": date.strftime("%Y-%m-%d"),
                            "price": round(row['Close'], 2)
                        })
                        
            except Exception as inner_e:
                logger.warning(f"Failed to process SMA crossover for {symbol}: {inner_e}")
                
    except Exception as e:
        logger.error(f"Error fetching crossover data: {e}", exc_info=True)
        return {"error": str(e)}
        
    # Sort by date descending (newest first)
    crossovers.sort(key=lambda x: x['date'], reverse=True)
    return {"crossovers": crossovers}

if __name__ == "__main__":
    result = find_crossovers()
    print(result)
