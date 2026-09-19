import os
import sys
import matplotlib
matplotlib.use('Agg')  # Headless non-interactive backend

import pandas as pd
import numpy as np
import yfinance as yf
import vectorbt as vbt
import quantstats as qs
import json
import warnings

warnings.filterwarnings('ignore')

# Directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "backtest_results")
TEARSHEET_DIR = os.path.join(OUTPUT_DIR, "tearsheets")
os.makedirs(TEARSHEET_DIR, exist_ok=True)

# Technical Indicator Helpers
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calculate_macd(series, fast=12, slow=26, signal=9):
    fast_ema = series.ewm(span=fast, adjust=False).mean()
    slow_ema = series.ewm(span=slow, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    macd_hist = macd_line - signal_line
    return macd_line, signal_line, macd_hist

def calculate_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift(1)).abs()
    low_close = (df['Low'] - df['Close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def fetch_ticker_data(ticker, period="5y"):
    print(f"Downloading {ticker} daily OHLCV from Yahoo Finance...", flush=True)
    df = yf.download(ticker, period=period, interval="1d", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df = df.xs(ticker, level=1, axis=1) if ticker in df.columns.levels[1] else df.droplevel(0, axis=1)
    df = df.dropna()
    print(f"Downloaded {len(df)} candles for {ticker}.", flush=True)
    return df

# Strategy Signal Generators with Risk Controls & Trailing Stops
def strategy_sma_crossover(df):
    """Strategy 1: 50/200 SMA Golden Cross & 7/20 EMA Crossover"""
    close = df['Close']
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    
    entries = (sma50 > sma200) & (sma50.shift(1) <= sma200.shift(1))
    exits = (sma50 < sma200) & (sma50.shift(1) >= sma200.shift(1))
    return entries.fillna(False), exits.fillna(False)

def strategy_vcp(df):
    """Strategy 2: Volatility Contraction Pattern (VCP) Breakout with ATR Trailing Stop"""
    close = df['Close']
    volume = df['Volume']
    high20 = df['High'].rolling(20).max()
    sma50 = close.rolling(50).mean()
    vol_sma20 = volume.rolling(20).mean()
    atr14 = calculate_atr(df, 14)
    
    range10 = (df['High'].rolling(10).max() - df['Low'].rolling(10).min()) / close
    contraction = range10 < 0.10
    trend = close > sma50
    vol_breakout = volume > 1.1 * vol_sma20
    price_breakout = close >= high20.shift(1)
    
    entries = price_breakout & contraction & trend & vol_breakout
    # Exit on close below 20-day EMA or 2.0x ATR trailing stop
    ema20 = close.ewm(span=20, adjust=False).mean()
    atr_stop = close < (close.rolling(10).max() - 2.0 * atr14)
    exits = (close < ema20) | atr_stop
    return entries.fillna(False), exits.fillna(False)

def strategy_episodic_pivot(df):
    """Strategy 3: Episodic Pivot (EP) with RVOL & Gap Filter"""
    close = df['Close']
    open_p = df['Open']
    prev_close = close.shift(1)
    volume = df['Volume']
    vol_sma20 = volume.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    atr14 = calculate_atr(df, 14)
    
    gap_pct = (open_p - prev_close) / prev_close
    rvol = volume / vol_sma20
    stage2 = close > sma50
    
    entries = (gap_pct >= 0.03) & (rvol >= 1.5) & stage2
    ema20 = close.ewm(span=20, adjust=False).mean()
    exits = (close < ema20) | (close < (close - 1.5 * atr14))
    return entries.fillna(False), exits.fillna(False)

def strategy_rsi_multitimeframe(df):
    """Strategy 4: Multi-Timeframe RSI Setup"""
    close = df['Close']
    daily_rsi = calculate_rsi(close, 14)
    
    weekly_close = close.resample('W').last()
    weekly_rsi = calculate_rsi(weekly_close, 14).reindex(df.index, method='ffill')
    
    mtf_bullish = weekly_rsi > 50
    daily_trigger = (daily_rsi > 50) & (daily_rsi.shift(1) <= 50)
    
    entries = mtf_bullish & daily_trigger
    exits = (daily_rsi < 45) | (close < close.ewm(span=20, adjust=False).mean())
    return entries.fillna(False), exits.fillna(False)

def strategy_nse_momentum(df):
    """Strategy 5: NSE Momentum (EMA20 + RSI50 + MACD + Vol Surge)"""
    close = df['Close']
    volume = df['Volume']
    ema20 = close.ewm(span=20, adjust=False).mean()
    rsi14 = calculate_rsi(close, 14)
    _, _, macd_hist = calculate_macd(close)
    vol_sma20 = volume.rolling(20).mean()
    
    cond = (close > ema20) & (rsi14 > 50) & (macd_hist > 0) & (volume > 1.2 * vol_sma20)
    entries = cond & (~cond.shift(1).fillna(False))
    exits = (close < ema20) | (macd_hist < 0)
    return entries.fillna(False), exits.fillna(False)

def strategy_flag_pattern(df):
    """Strategy 6: Perfect Flag Pattern Breakout"""
    close = df['Close']
    high = df['High']
    low = df['Low']
    
    pole_gain = (close - close.shift(15)) / close.shift(15)
    flag_depth = (high.rolling(8).max() - low.rolling(8).min()) / close
    
    entries = (pole_gain >= 0.08) & (flag_depth <= 0.09) & (close >= high.rolling(8).max().shift(1))
    ema10 = close.ewm(span=10, adjust=False).mean()
    exits = close < ema10
    return entries.fillna(False), exits.fillna(False)


STRATEGIES = {
    "Golden_Cross_50_200": strategy_sma_crossover,
    "VCP_Breakout": strategy_vcp,
    "Episodic_Pivot": strategy_episodic_pivot,
    "MultiTimeframe_RSI": strategy_rsi_multitimeframe,
    "NSE_Momentum": strategy_nse_momentum,
    "Perfect_Flag_Pattern": strategy_flag_pattern
}

TICKERS = ["TCS.NS", "RELIANCE.NS", "INFY.NS", "^NSEI"]

def run_backtests():
    summary_results = []
    
    print("Fetching benchmark (^NSEI)...", flush=True)
    nifty_df = fetch_ticker_data("^NSEI", period="5y")
    benchmark_returns = nifty_df['Close'].pct_change().fillna(0)
    benchmark_returns.index = pd.to_datetime(benchmark_returns.index).tz_localize(None)
    
    for ticker in TICKERS:
        df = fetch_ticker_data(ticker, period="5y")
        close = df['Close']
        
        for strat_name, strat_func in STRATEGIES.items():
            print(f"\n[BACKTEST] {strat_name} on {ticker}", flush=True)
            entries, exits = strat_func(df)
            
            # VectorBT portfolio backtest with 0.15% NSE realistic transaction costs & slippage
            portfolio = vbt.Portfolio.from_signals(
                close=close,
                entries=entries,
                exits=exits,
                init_cash=100000,
                fees=0.0015,  # 0.15% STT + Brokerage + Slippage
                freq='1D'
            )
            
            total_return = portfolio.total_return() * 100
            bm_return = (close.iloc[-1] / close.iloc[0] - 1) * 100
            win_rate = portfolio.trades.win_rate() * 100 if len(portfolio.trades) > 0 else 0
            max_drawdown = portfolio.max_drawdown() * 100
            total_trades = portfolio.trades.count()
            sharpe = portfolio.sharpe_ratio()
            profit_factor = portfolio.trades.profit_factor()
            
            days = (df.index[-1] - df.index[0]).days
            years = max(days / 365.25, 0.1)
            cagr = ((portfolio.value().iloc[-1] / 100000) ** (1 / years) - 1) * 100
            
            safe_ticker_str = ticker.replace("^", "").replace(".", "_")
            tearsheet_filename = f"{safe_ticker_str}_{strat_name}_tearsheet.html"
            
            def safe_float(val, default=0.0):
                if val is None or np.isnan(val) or np.isinf(val):
                    return default
                return float(val)

            record = {
                "Ticker": ticker,
                "Strategy": strat_name,
                "Total Return (%)": round(safe_float(total_return), 2),
                "Buy & Hold Return (%)": round(safe_float(bm_return), 2),
                "CAGR (%)": round(safe_float(cagr), 2),
                "Max Drawdown (%)": round(safe_float(max_drawdown), 2),
                "Sharpe Ratio": round(safe_float(sharpe), 2),
                "Profit Factor": round(safe_float(profit_factor), 2),
                "Win Rate (%)": round(safe_float(win_rate), 2),
                "Total Trades": int(total_trades),
                "Tearsheet": tearsheet_filename
            }
            summary_results.append(record)
            print(f"  -> Total Return: {record['Total Return (%)']}%, CAGR: {record['CAGR (%)']}%, Sharpe: {record['Sharpe Ratio']}, Trades: {record['Total Trades']}", flush=True)
            
            # QuantStats Tearsheet Generation
            try:
                returns_series = portfolio.returns()
                returns_series.index = pd.to_datetime(returns_series.index).tz_localize(None)
                bm_ser = benchmark_returns.reindex(returns_series.index).fillna(0)
                
                tearsheet_file = os.path.join(TEARSHEET_DIR, tearsheet_filename)
                qs.reports.html(returns_series, benchmark=bm_ser, output=tearsheet_file, title=f"{strat_name} ({ticker}) Daily Backtest")
                print(f"  -> QuantStats Tearsheet saved: {tearsheet_file}", flush=True)
            except Exception as e:
                print(f"  -> QuantStats note for {strat_name} on {ticker}: {e}", flush=True)

    # Save summary table JSON & CSV
    df_summary = pd.DataFrame(summary_results)
    csv_file = os.path.join(OUTPUT_DIR, "backtest_summary.csv")
    json_file = os.path.join(OUTPUT_DIR, "backtest_summary.json")
    df_summary.to_csv(csv_file, index=False)
    with open(json_file, "w") as f:
        json.dump(summary_results, f, indent=2)
        
    print("\n================ BACKTEST SUMMARY RESULTS ================", flush=True)
    print(df_summary.to_string(index=False), flush=True)
    print(f"\nAll backtest summaries exported to: {csv_file}", flush=True)

if __name__ == "__main__":
    run_backtests()
