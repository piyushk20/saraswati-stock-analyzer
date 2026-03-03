import yfinance as yf
import pandas as pd
import json
import traceback
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Define Major Indices
INDICES = {
    "^NSEI": "NIFTY 50",
    "^BSESN": "SENSEX",
    "^NSEBANK": "NIFTY BANK",
    "^CNXIT": "NIFTY IT"
}

# Define Nifty 50 Universe for Gainers/Losers
NIFTY_50 = [
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

def fetch_market_overview():
    try:
        results = {
            "indices": [],
            "top_gainers": [],
            "top_losers": []
        }

        # 1. Fetch Indices Data
        if INDICES:
            tickers_indices = list(INDICES.keys())
            idx_data = yf.download(tickers_indices, period="5d", group_by="ticker", progress=False)
            
            for symbol, name in INDICES.items():
                try:
                    if len(tickers_indices) == 1:
                        df = idx_data
                    else:
                        df = idx_data[symbol]
                        
                    if df is None or df.empty:
                        continue
                        
                    df = df.dropna()
                    if len(df) >= 2:
                        current_close = float(df['Close'].iloc[-1])
                        prev_close = float(df['Close'].iloc[-2])
                        day_high = float(df['High'].iloc[-1])
                        day_low = float(df['Low'].iloc[-1])
                        
                        pct_change = ((current_close - prev_close) / prev_close) * 100
                        
                        results["indices"].append({
                            "symbol": symbol,
                            "name": name,
                            "price": round(current_close, 2),
                            "change_pct": round(pct_change, 2),
                            "high": round(day_high, 2),
                            "low": round(day_low, 2)
                        })
                except Exception as e:
                    logger.error(f"Error processing index {symbol}: {e}")

        # 2. Fetch Nifty 50 Data for Gainers/Losers
        stocks_data = yf.download(NIFTY_50, period="5d", group_by="ticker", progress=False)
        
        performance = []
        
        for symbol in NIFTY_50:
            try:
                df = stocks_data[symbol]
                if df is None or df.empty:
                    continue
                df = df.dropna()
                
                if len(df) >= 2:
                    current_close = float(df['Close'].iloc[-1])
                    prev_close = float(df['Close'].iloc[-2])
                    
                    pct_change = ((current_close - prev_close) / prev_close) * 100
                    
                    performance.append({
                        "symbol": symbol,
                        "change_pct": round(pct_change, 2),
                        "price": round(current_close, 2)
                    })
            except Exception as e:
                logger.error(f"Error processing stock {symbol}: {e}")
                continue
                
        # Sort to find top gainers and losers
        performance.sort(key=lambda x: x["change_pct"], reverse=True)
        
        # Take top 5 gainers
        results["top_gainers"] = performance[:5]
        
        # Take top 5 losers
        results["top_losers"] = performance[-5:]
        results["top_losers"].sort(key=lambda x: x["change_pct"]) # Sort ascending (worst first)
        
        return results

    except Exception as e:
        return {"error": f"Failed to fetch market overview: {str(e)}\n{traceback.format_exc()}"}

if __name__ == "__main__":
    print(json.dumps(fetch_market_overview(), indent=2))
