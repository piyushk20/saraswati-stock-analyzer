"""
execution/momentum_scanner.py
-------------------------
NSE Momentum Scanner — EMA20 | RSI > 50 | MACD Cross | Volume > Vol SMA(20)

Conditions : Price > EMA(20)  AND  RSI(14) > 50  AND  MACD Line > Signal Line
             AND  Volume > SMA(Volume, 20)

Uses: yfinance, pandas, numpy, ta
"""

import logging
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
try:
    from execution.yf_helper import get_ticker, get_historical_data_safe
except ImportError:
    try:
        from yf_helper import get_ticker, get_historical_data_safe
    except ImportError:
        def get_ticker(symbol):
            return yf.Ticker(symbol)
        def get_historical_data_safe(symbol, period="5y"):
            return yf.Ticker(symbol).history(period=period)
from ta.trend import EMAIndicator, MACD, SMAIndicator
from ta.momentum import RSIIndicator

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

MOMENTUM_CONFIG = {
    "EMA_PERIOD": 20,
    "RSI_PERIOD": 14,
    "RSI_THRESHOLD": 50.0,
    "MACD_FAST": 12,
    "MACD_SLOW": 26,
    "MACD_SIGNAL": 9,
    "VOLUME_SMA_PERIOD": 20,
    "DATA_PERIOD": "1y",
    "MAX_WORKERS": 15,
    "SYMBOL_CAP": 800,
}

def _safe_float(v) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None

def _fetch_and_analyze(symbol: str) -> dict | None:
    ticker = symbol if symbol.endswith((".NS", ".BO")) else symbol + ".NS"

    try:
        t = get_ticker(ticker)
        df = t.history(
            period=MOMENTUM_CONFIG["DATA_PERIOD"],
            interval="1d",
            auto_adjust=True,
            timeout=10,
        )

        if df is None or len(df) < 50:
            return None

        df = df.dropna(subset=["Close", "Volume"])

        if len(df) < 50:
            return None

        # Ensure index is standard datetime
        df.index = pd.to_datetime(df.index)
        close = df["Close"].astype(float)
        volume = df["Volume"].astype(float)

        # Calculate indicators
        ema20 = EMAIndicator(close, window=MOMENTUM_CONFIG["EMA_PERIOD"]).ema_indicator()
        rsi14 = RSIIndicator(close, window=MOMENTUM_CONFIG["RSI_PERIOD"]).rsi()
        
        macd_indicator = MACD(
            close, 
            window_fast=MOMENTUM_CONFIG["MACD_FAST"], 
            window_slow=MOMENTUM_CONFIG["MACD_SLOW"], 
            window_sign=MOMENTUM_CONFIG["MACD_SIGNAL"]
        )
        macd_line = macd_indicator.macd()
        macd_signal = macd_indicator.macd_signal()
        macd_hist = macd_indicator.macd_diff()

        vol_sma20 = SMAIndicator(volume, window=MOMENTUM_CONFIG["VOLUME_SMA_PERIOD"]).sma_indicator()

        # Get latest values for safety checks
        latest_close = _safe_float(close.iloc[-1])
        latest_ema = _safe_float(ema20.iloc[-1])
        latest_rsi = _safe_float(rsi14.iloc[-1])
        latest_macd = _safe_float(macd_line.iloc[-1])
        latest_signal = _safe_float(macd_signal.iloc[-1])
        latest_hist = _safe_float(macd_hist.iloc[-1])
        latest_vol = _safe_float(volume.iloc[-1])
        latest_vol_sma = _safe_float(vol_sma20.iloc[-1])

        if None in (latest_close, latest_ema, latest_rsi, latest_macd, latest_signal, latest_vol, latest_vol_sma):
            return None

        # Check sessions S = -1, -2, -3
        def check_session(idx):
            try:
                c = _safe_float(close.iloc[idx])
                e = _safe_float(ema20.iloc[idx])
                r = _safe_float(rsi14.iloc[idx])
                m = _safe_float(macd_line.iloc[idx])
                s = _safe_float(macd_signal.iloc[idx])
                v = _safe_float(volume.iloc[idx])
                vs = _safe_float(vol_sma20.iloc[idx])
                
                if None in (c, e, r, m, s, v, vs):
                    return False
                    
                return c > e and r > MOMENTUM_CONFIG["RSI_THRESHOLD"] and m > s and v > vs
            except Exception:
                return False

        passed_today = check_session(-1)
        passed_yesterday = len(close) >= 2 and check_session(-2)
        passed_2days_ago = len(close) >= 3 and check_session(-3)

        if passed_today or passed_yesterday or passed_2days_ago:
            is_new_addition = passed_today and not passed_yesterday
            
            passed_sessions = []
            if passed_today:
                passed_sessions.append("Today")
            if passed_yesterday:
                passed_sessions.append("Yesterday")
            if passed_2days_ago:
                passed_sessions.append("2 Days Ago")

            date_str = str(df.index[-1].date())
            return {
                "symbol": ticker,
                "display_symbol": symbol,
                "date": date_str,
                "close": round(latest_close, 2) if latest_close is not None else 0.0,
                "ema_20": round(latest_ema, 2) if latest_ema is not None else 0.0,
                "pct_above_ema": round((latest_close / latest_ema - 1) * 100, 2) if latest_close and latest_ema else 0.0,
                "rsi": round(latest_rsi, 2) if latest_rsi is not None else 0.0,
                "macd": round(latest_macd, 4) if latest_macd is not None else 0.0,
                "macd_signal": round(latest_signal, 4) if latest_signal is not None else 0.0,
                "macd_hist": round(latest_hist, 4) if latest_hist is not None else 0.0,
                "volume": int(latest_vol) if latest_vol is not None else 0,
                "vol_sma_20": int(latest_vol_sma) if latest_vol_sma is not None else 0,
                "vol_ratio": round(latest_vol / latest_vol_sma, 2) if latest_vol and latest_vol_sma > 0 else 0.0,
                "passed_today": passed_today,
                "passed_yesterday": passed_yesterday,
                "passed_2days_ago": passed_2days_ago,
                "passed_sessions": passed_sessions,
                "is_new_addition": is_new_addition
            }

        return None

    except Exception as e:
        logger.debug("Momentum scan error for %s: %s", symbol, e)
        return None

def scan_momentum(cap: int = None) -> dict:
    try:
        from execution.vcp_screener import get_all_symbols
        symbols_raw = get_all_symbols()
    except Exception as e:
        logger.error("Could not load symbols: %s", e)
        return {"error": f"Could not load symbol list: {e}"}

    cap = cap or MOMENTUM_CONFIG["SYMBOL_CAP"]
    symbols = [s.replace(".NS", "").replace(".BO", "") for s in symbols_raw[:cap]]

    logger.info("Momentum Scan: scanning %d symbols...", len(symbols))

    candidates = []
    with ThreadPoolExecutor(max_workers=MOMENTUM_CONFIG["MAX_WORKERS"]) as pool:
        futures = {pool.submit(_fetch_and_analyze, s): s for s in symbols}
        for fut in as_completed(futures):
            result = fut.result()
            if result is not None:
                candidates.append(result)

    # Sort by RSI descending
    candidates.sort(key=lambda x: x["rsi"], reverse=True)

    logger.info("Momentum Scan complete: %d candidates found.", len(candidates))

    return {
        "momentum_stocks": candidates,
        "scanned": len(symbols),
        "found": len(candidates),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

if __name__ == "__main__":
    import json
    results = scan_momentum()
    print(json.dumps(results, indent=2))
