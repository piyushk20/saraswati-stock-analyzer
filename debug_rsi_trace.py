import yfinance as yf
import pandas as pd
import numpy as np
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def calculate_rsi(data, window=14):
    if len(data) < window + 1: 
        print(f"DEBUG: Data too short ({len(data)}) for window {window}")
        return pd.Series([None] * len(data))
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(loss != 0, 100)
    rsi = rsi.where((gain != 0) | (loss != 0), 50)
    return rsi

def debug_rsi(symbol):
    print(f"--- Debugging RSI for {symbol} ---")
    stock = yf.Ticker(symbol)
    
    # Daily
    d_df = stock.history(period="1mo", interval="1d")
    print(f"Daily rows: {len(d_df)}")
    if not d_df.empty:
        d_rsi = calculate_rsi(d_df['Close'])
        print(f"Daily RSI Last: {d_rsi.iloc[-1]}")
    
    # Weekly
    w_df = stock.history(period="1y", interval="1wk")
    print(f"Weekly rows: {len(w_df)}")
    if not w_df.empty:
        w_rsi = calculate_rsi(w_df['Close'])
        print(f"Weekly RSI Last: {w_rsi.iloc[-1]}")
        
    # Monthly
    m_df = stock.history(period="2y", interval="1mo")
    print(f"Monthly rows: {len(m_df)}")
    if not m_df.empty:
        m_rsi = calculate_rsi(m_df['Close'])
        print(f"Monthly RSI Last: {m_rsi.iloc[-1]}")

if __name__ == "__main__":
    debug_rsi("RELIANCE.NS")
    debug_rsi("^NSEI")
