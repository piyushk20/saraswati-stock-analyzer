import os
import sys
import yfinance as yf
import pandas as pd
import numpy as np
import json
import logging
import argparse
from datetime import datetime, timedelta

# Add the project root to sys.path to find our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from execution.nse_options import get_nse_option_chain
    print("DEBUG: Successfully imported get_nse_option_chain from execution.nse_options")
except ImportError as e1:
    print(f"DEBUG: Failed first import in analyze_stock: {e1}")
    # Handle if run directly from execution folder
    try:
        from nse_options import get_nse_option_chain
        print("DEBUG: Successfully imported get_nse_option_chain from nse_options")
    except ImportError as e2:
        print(f"DEBUG: Failed second import in analyze_stock: {e2}")
        def get_nse_option_chain(symbol, is_index=False):
            print("DEBUG: Using dummy get_nse_option_chain returning None")
            return {"current": None, "next": None}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def safe_get(data, key, default=None):
    """Safely get value from dictionary or Series."""
    if data is None: return default
    try:
        if hasattr(data, "get"):
            val = data.get(key, default)
        else:
            val = data[key] if key in data else default
            
        if pd.isna(val): return default
        return val
    except:
        return default

def calculate_rsi(data, window=14):
    """Calculates Relative Strength Index (RSI)."""
    if len(data) < window + 1: return pd.Series([None] * len(data))
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    
    # To handle division by zero where loss is 0
    # Standard RSI: gain/loss. If loss is 0, RSI is 100.
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    # Handle cases where loss is 0 (set to 100) or both are 0 (set to 50)
    rsi = rsi.where(loss != 0, 100)
    rsi = rsi.where((gain != 0) | (loss != 0), 50)
    
    # Final cleanup for JSON serialization (no inf/nan)
    rsi = rsi.replace([np.inf, -np.inf], 100).fillna(50)
    
    return rsi

def calculate_macd(data, fast=12, slow=26, signal=9):
    """Calculates MACD."""
    if len(data) < slow: return None, None, None
    exp1 = data.ewm(span=fast, adjust=False).mean()
    exp2 = data.ewm(span=slow, adjust=False).mean()
    macd = exp1 - exp2
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - signal_line
    return macd.iloc[-1], signal_line.iloc[-1], hist.iloc[-1]

def calculate_pivot_points(high, low, close):
    """Calculates Daily Pivot Points."""
    pp = (high + low + close) / 3
    r1 = (2 * pp) - low
    s1 = (2 * pp) - high
    r2 = pp + (high - low)
    s2 = pp - (high - low)
    r3 = high + 2 * (pp - low)
    s3 = low - 2 * (high - pp)
    return {
        "pp": round(float(pp), 2),
        "r1": round(float(r1), 2),
        "s1": round(float(s1), 2),
        "r2": round(float(r2), 2),
        "s2": round(float(s2), 2),
        "r3": round(float(r3), 2),
        "s3": round(float(s3), 2)
    }

def get_relative_strength(symbol, history_1m_pct, history_1y_pct):
    """Calculates Relative Strength against Nifty 50."""
    try:
        nifty = yf.Ticker("^NSEI").history(period="1y")
        if not nifty.empty and len(nifty) >= 21:
            n_curr = nifty['Close'].iloc[-1]
            n_1m = nifty['Close'].iloc[-21]
            n_1y = nifty['Close'].iloc[0]
            
            nifty_1m_pct = ((n_curr - n_1m) / n_1m) * 100
            nifty_1y_pct = ((n_curr - n_1y) / n_1y) * 100
            
            return {
                "nifty_1m": round(float(history_1m_pct - nifty_1m_pct), 2),
                "nifty_1y": round(float(history_1y_pct - nifty_1y_pct), 2),
                "sector_index": "Nifty 50",
                "sector_1m": round(float(history_1m_pct - nifty_1m_pct), 2),
                "sector_1y": round(float(history_1y_pct - nifty_1y_pct), 2)
            }
    except Exception as e:
        logger.error(f"Error calculating RS for {symbol}: {e}")
        pass
    return None

def get_multi_tf_rsi(symbol, df_daily=None):
    """Calculates RSI for Daily, Weekly, and Monthly timeframes."""
    results = {"daily": None, "weekly": None, "monthly": None}
    try:
        # 1. Daily RSI
        if df_daily is not None and not df_daily.empty and len(df_daily) > 14:
            rsi_series = calculate_rsi(df_daily['Close'])
            if not rsi_series.empty:
                val = rsi_series.iloc[-1]
                if pd.notnull(val):
                    results["daily"] = round(float(val), 2)
                    logger.info(f"Calculated Daily RSI for {symbol}: {results['daily']}")

        stock = yf.Ticker(symbol)
        
        # 2. Weekly RSI
        # Fetch slightly more data to ensure 14 periods
        w_df = stock.history(period="2y", interval="1wk")
        if not w_df.empty and len(w_df) > 14:
            rsi_series = calculate_rsi(w_df['Close'])
            if not rsi_series.empty:
                val = rsi_series.iloc[-1]
                if pd.notnull(val):
                    results["weekly"] = round(float(val), 2)
                    logger.info(f"Calculated Weekly RSI for {symbol}: {results['weekly']}")

        # 3. Monthly RSI
        m_df = stock.history(period="5y", interval="1mo")
        if not m_df.empty and len(m_df) > 14:
            rsi_series = calculate_rsi(m_df['Close'])
            if not rsi_series.empty:
                val = rsi_series.iloc[-1]
                if pd.notnull(val):
                    results["monthly"] = round(float(val), 2)
                    logger.info(f"Calculated Monthly RSI for {symbol}: {results['monthly']}")
                    
    except Exception as e:
        logger.error(f"FATAL Error in get_multi_tf_rsi for {symbol}: {e}")
        import traceback
        logger.error(traceback.format_exc())
    return results

def analyze(symbol):
    """Main analysis function."""
    try:
        logger.info(f"Analyzing {symbol}...")
        ticker = yf.Ticker(symbol)
        
        # 1. Price Data
        df_full = ticker.history(period="5y")
        if df_full.empty:
            return {"error": f"No data found for {symbol}", "symbol": symbol}
            
        df = df_full.tail(252)
        
        info = getattr(ticker, "info", {})
        is_index = symbol.startswith("^") or (info.get("quoteType") == "INDEX")
        
        current_price = df['Close'].iloc[-1]
        prev_price = df['Close'].iloc[-2]
        change_1d = current_price - prev_price
        change_1d_pct = (change_1d / prev_price) * 100
        
        # Performance over periods
        history_1w = df['Close'].iloc[-5] if len(df) >= 5 else df['Close'].iloc[0]
        change_1w_pct = ((current_price - history_1w) / history_1w) * 100
        
        history_1m = df['Close'].iloc[-21] if len(df) >= 21 else df['Close'].iloc[0]
        change_1m_pct = ((current_price - history_1m) / history_1m) * 100
        
        history_1y = df['Close'].iloc[0]
        change_1y_pct = ((current_price - history_1y) / history_1y) * 100
        
        # SMAs
        sma_20 = df['Close'].rolling(window=20).mean().iloc[-1]
        sma_50 = df['Close'].rolling(window=50).mean().iloc[-1]
        sma_200 = df_full['Close'].rolling(window=200).mean().iloc[-1]
        
        # MACD
        macd, macd_signal, macd_hist = calculate_macd(df['Close'])
        
        # Volume Trend
        vol_trend = "Neutral"
        if len(df) >= 3:
            v_curr = df['Volume'].iloc[-1]
            v_prev = df['Volume'].iloc[-2]
            if v_curr > v_prev * 1.5 and current_price > prev_price:
                vol_trend = "Strong Buying"
            elif v_curr > v_prev and current_price > prev_price:
                vol_trend = "Buying"
            elif v_curr > v_prev * 1.5 and current_price < prev_price:
                vol_trend = "Strong Selling"
            elif v_curr > v_prev and current_price < prev_price:
                vol_trend = "Selling"
                
        # Relative Strength
        rs_data = get_relative_strength(symbol, change_1m_pct, change_1y_pct)
        
        # Pivot Points
        try:
            pivot_data = calculate_pivot_points(df['High'].iloc[-1], df['Low'].iloc[-1], df['Close'].iloc[-1])
        except Exception:
            pivot_data = None
        
        # Chart Data
        chart_df = df.tail(100)
        chart_dates = [d.strftime("%Y-%m-%d") for d in chart_df.index]
        chart_closes = [round(float(c), 2) for c in chart_df['Close']]
        chart_volumes = [int(v) for v in chart_df['Volume']]
        
        # 2. Options Data (NSE)
        nse_symbol = symbol
        is_nse_index = False
        if symbol == "^NSEI":
            nse_symbol = "NIFTY"
            is_nse_index = True
        elif symbol == "^NSEBANK":
            nse_symbol = "BANKNIFTY"
            is_index = True
        elif symbol.endswith(".NS"):
            nse_symbol = symbol.replace(".NS", "")
            
        options_data = get_nse_option_chain(nse_symbol, is_nse_index)
        
        # 3. Multi-TF RSI (pass current daily DF to save a call)
        print(f"DEBUG: Calculating RSI for {symbol}")
        rsi_data = get_multi_tf_rsi(symbol, df_full)
        print(f"DEBUG: RSI Results for {symbol}: {rsi_data}")
        
        # 4. Result Construction
        # Calculate max/min safely from history
        day_high = df['High'].iloc[-1] if not df.empty else None
        day_low = df['Low'].iloc[-1] if not df.empty else None
        vol = int(df['Volume'].iloc[-1]) if not df.empty else None
        wk52_high = df['High'].max() if not df.empty else None
        wk52_low = df['Low'].min() if not df.empty else None
        at_high = df_full['High'].max() if not df_full.empty else wk52_high
        at_low = df_full['Low'].min() if not df_full.empty else wk52_low
        
        vcp_matched = False
        if wk52_high and current_price >= wk52_high * 0.9 and vol_trend in ["Neutral", "Selling"]:
            vcp_matched = True

        result = {
            "symbol": symbol,
            "name": info.get("longName") or info.get("shortName") or symbol,
            "price": round(float(current_price), 2),
            "change": round(float(change_1d), 2),
            "change_pct": round(float(change_1d_pct), 2),
            "sma_20": round(float(sma_20), 2) if not pd.isna(sma_20) else None,
            "sma_50": round(float(sma_50), 2) if not pd.isna(sma_50) else None,
            "sma_200": round(float(sma_200), 2) if not pd.isna(sma_200) else None,
            "macd": round(float(macd), 2) if macd is not None and not pd.isna(macd) else None,
            "macd_signal": round(float(macd_signal), 2) if macd_signal is not None and not pd.isna(macd_signal) else None,
            "macd_histogram": round(float(macd_hist), 2) if macd_hist is not None and not pd.isna(macd_hist) else None,
            "volume_trend": vol_trend,
            "rsi": rsi_data,
            "chart": {
                "dates": chart_dates,
                "closes": chart_closes,
                "volumes": chart_volumes,
            },
            "performance": [
                {"period": "1D", "pct": round(float(change_1d_pct), 2)},
                {"period": "1W", "pct": round(float(change_1w_pct), 2)},
                {"period": "1M", "pct": round(float(change_1m_pct), 2)},
                {"period": "1Y", "pct": round(float(change_1y_pct), 2)},
            ],
            "options_data": options_data,
            "pivot_points": pivot_data,
            "relative_strength": rs_data,
            "vcp_matched": vcp_matched,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "day_high": safe_get(info, "regularMarketDayHigh", day_high),
            "day_low": safe_get(info, "regularMarketDayLow", day_low),
            "volume": safe_get(info, "regularMarketVolume", vol),
            "week_52_high": safe_get(info, "fiftyTwoWeekHigh", wk52_high),
            "week_52_low": safe_get(info, "fiftyTwoWeekLow", wk52_low),
            "all_time_high": at_high,
            "all_time_low": at_low,
            "previous_close": safe_get(info, "previousClose", float(prev_price) if not df.empty else None),
        }
        
        # Add Fundamentals for non-indices
        if not is_index:
            try:
                financials = getattr(ticker, "financials", None)
                bs = getattr(ticker, "balance_sheet", None)
                cf = getattr(ticker, "cashflow", None)
                
                f_revenue = None; f_net_income = None
                f_gross_profit = None; f_operating_income = None
                if financials is not None and not financials.empty and len(financials.columns) > 0:
                    f_revenue = safe_get(financials.iloc[:, 0], "Total Revenue")
                    f_net_income = safe_get(financials.iloc[:, 0], "Net Income")
                    f_gross_profit = safe_get(financials.iloc[:, 0], "Gross Profit")
                    f_operating_income = safe_get(financials.iloc[:, 0], "Operating Income")
                
                b_assets = None; b_equity = None
                b_liabilities = None; b_debt = None
                if bs is not None and not bs.empty and len(bs.columns) > 0:
                    b_assets = safe_get(bs.iloc[:, 0], "Total Assets")
                    b_equity = safe_get(bs.iloc[:, 0], "Stockholders Equity")
                    b_liabilities = safe_get(bs.iloc[:, 0], "Total Liabilities Net Minority Interest", safe_get(bs.iloc[:, 0], "Total Liabilities"))
                    b_debt = safe_get(bs.iloc[:, 0], "Total Debt")
                    
                c_operating = None; c_free = None
                if cf is not None and not cf.empty and len(cf.columns) > 0:
                    c_operating = safe_get(cf.iloc[:, 0], "Operating Cash Flow")
                    c_free = safe_get(cf.iloc[:, 0], "Free Cash Flow")
                    
                result.update({
                    "market_cap": safe_get(info, "marketCap"),
                    "pe_ratio": safe_get(info, "trailingPE"),
                    "forward_pe": safe_get(info, "forwardPE"),
                    "eps": safe_get(info, "trailingEps"),
                    "dividend_yield": safe_get(info, "dividendYield"),
                    "price_to_book": safe_get(info, "priceToBook"),
                    "book_value": safe_get(info, "bookValue"),
                    "roe": safe_get(info, "returnOnEquity"),
                    "debt_to_equity": safe_get(info, "debtToEquity"),
                    "sector": safe_get(info, "sector"),
                    "industry": safe_get(info, "industry"),
                    "summary": safe_get(info, "longBusinessSummary"),
                    "financials_revenue": f_revenue,
                    "financials_gross_profit": f_gross_profit,
                    "financials_operating_income": f_operating_income,
                    "financials_net_income": f_net_income,
                    "bs_total_assets": b_assets,
                    "bs_total_liabilities": b_liabilities,
                    "bs_total_equity": b_equity,
                    "bs_total_debt": b_debt,
                    "cf_operating": c_operating,
                    "cf_free_cash_flow": c_free
                })
            except Exception as fe:
                logger.warning(f"Error fetching fundamentals for {symbol}: {fe}")
                
        return result

    except Exception as e:
        logger.error(f"Analysis error for {symbol}: {e}", exc_info=True)
        return {"error": str(e), "symbol": symbol}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze an Indian stock or index.")
    parser.add_argument("--symbol", required=False, default="^NSEI", help="yfinance ticker symbol")
    args = parser.parse_args()

    result = analyze(args.symbol)
    print(json.dumps(result, indent=2, default=str))
