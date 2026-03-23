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

def get_universe_symbols(category="nifty50"):
    """Duplicate logic or import from screener to get symbols by category."""
    # Hardcoded Nifty 50 for speed
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

def fetch_market_overview(category="nifty50"):
    try:
        results = {
            "indices": [],
            "top_gainers": [],
            "top_losers": []
        }

        # 1. Fetch Indices Data (One by one for robustness)
        for symbol, name in INDICES.items():
            try:
                ticker = yf.Ticker(symbol)
                df = ticker.history(period="5d")
                
                if df is None or df.empty:
                    logger.warning(f"No data for index {symbol}")
                    continue
                    
                df = df.dropna()
                if len(df) >= 2:
                    current_close = float(df['Close'].iloc[-1])
                    prev_close = float(df['Close'].iloc[-2])
                    day_high = float(df['High'].iloc[-1])
                    day_low = float(df['Low'].iloc[-1])
                    
                    pct_change = ((current_close - prev_close) / prev_close) * 100
                    
                    results["indices"].append({
                        "symbol": symbol.replace('^', ''), # Strip ^ for cleaner display if needed, but app.js handles it
                        "symbol_raw": symbol,
                        "name": name,
                        "price": round(current_close, 2),
                        "change_pct": round(pct_change, 2),
                        "high": round(day_high, 2),
                        "low": round(day_low, 2)
                    })
            except Exception as e:
                logger.error(f"Error processing index {symbol}: {e}")

        # 2. Fetch Universe Data for Gainers/Losers
        universe = get_universe_symbols(category)
        
        # We still use download for stocks as it's faster for large lists
        # but we handle errors better
        stocks_data = yf.download(universe, period="5d", group_by="ticker", progress=False)
        
        performance = []
        
        for symbol in universe:
            try:
                if len(universe) == 1:
                    df = stocks_data
                else:
                    if symbol not in stocks_data.columns.levels[0]:
                        continue
                    df = stocks_data[symbol]
                    
                if df is None or df.empty or 'Close' not in df:
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
                continue
                
        # Sort to find top gainers and losers
        performance.sort(key=lambda x: x["change_pct"], reverse=True)
        
        # Take top 5 gainers
        results["top_gainers"] = performance[:5]
        
        # Take top 5 losers
        results["top_losers"] = performance[-5:]
        results["top_losers"].sort(key=lambda x: x["change_pct"])
        
        return results

    except Exception as e:
        logger.error(f"Fatal error in fetch_market_overview: {e}")
        return {"error": f"Failed to fetch market overview: {str(e)}"}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default="nifty50")
    args = parser.parse_args()
    print(json.dumps(fetch_market_overview(args.category), indent=2))
