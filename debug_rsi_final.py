import yfinance as yf
import pandas as pd
import numpy as np

def calculate_rsi(data, window=14):
    if len(data) < window + 1: return pd.Series([np.nan] * len(data))
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(loss != 0, 100)
    rsi = rsi.where((gain != 0) | (loss != 0), 50)
    return rsi

symbol = "RELIANCE.NS"
stock = yf.Ticker(symbol)

# Test Monthly Specifically
m_df = stock.history(period="5y", interval="1mo")
print(f"Monthly Data Rows: {len(m_df)}")
if not m_df.empty:
    m_rsi = calculate_rsi(m_df['Close'])
    print(f"Last 5 Monthly RSI Values:\n{m_rsi.tail(5)}")
    print(f"Final Value: {m_rsi.iloc[-1]}")

# Test Weekly
w_df = stock.history(period="2y", interval="1wk")
print(f"Weekly Data Rows: {len(w_df)}")
if not w_df.empty:
    w_rsi = calculate_rsi(w_df['Close'])
    print(f"Final Weekly Value: {w_rsi.iloc[-1]}")
