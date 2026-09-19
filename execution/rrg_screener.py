"""
execution/rrg_screener.py
-------------------------
Computes Relative Rotation Graph (RRG) coordinates for NSE stock universes.
RRG measures the relative strength (RS-Ratio) and relative momentum (RS-Momentum)
of stocks against a benchmark (default: Nifty 50 index '^NSEI').
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

warnings.filterwarnings("ignore")
logger = logging.getLogger("rrg_screener")

RRG_CONFIG = {
    "MAX_WORKERS": 15,
    "DATA_PERIOD": "6mo",  # 6 months is plenty for 10-day rolling mean & 4-day momentum
    "DEFAULT_BENCHMARK": "^NSEI",
    "MAX_SYMBOLS": 100,  # Cap at 100 to prevent chart clutter and rate limits
}

SECTOR_MAP = {
    "^CNXFMCG":             "Nifty FMCG",
    "^CNXPSUBANK":          "Nifty PSU Bank",
    "^CNXREALTY":           "Nifty Realty",
    "^NSEBANK":             "Nifty Bank",
    "NIFTY_PVT_BANK.NS":    "Nifty Private Bank",
    "NIFTY_FIN_SERVICE.NS": "Nifty Financial Services",
    "^CNXMEDIA":            "Nifty Media",
    "^CNXFIN":              "Nifty Financial Services 25/50",
    "NIFTY_OIL_AND_GAS.NS": "NIFTY OIL & GAS",
    "^CNXMETAL":            "Nifty Metal",
    "^CNXAUTO":             "Nifty Auto",
    "NIFTY_CONSR_DURBL.NS": "NIFTY CONSUMER DURABLES",
    "^CNXPHARMA":           "Nifty Pharma",
    "NIFTY_MIDSML_HLTH.NS": "Nifty MidSmall Healthcare",
    "^CNXIT":               "Nifty IT",
    "NIFTY_HEALTHCARE.NS":  "Nifty Healthcare",
    "^CNXENERGY":           "Nifty Energy",
    "^CNXINFRA":            "Nifty Infra",
    "^CNXPSE":              "Nifty PSE",
    "^CNXCONSUM":           "Nifty India Consumption",
    "^CNXSERVICE":          "Nifty Services Sector",
}

def _fetch_series_for_rrg(ticker: str) -> pd.DataFrame | None:
    """Fetch daily series, falling back to hourly-to-daily aggregation for indices with limited daily bars."""
    try:
        df = get_historical_data_safe(ticker, period=RRG_CONFIG["DATA_PERIOD"])
        if df is not None and len(df) >= 20:
            df.columns = [c.lower() for c in df.columns]
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            return df
    except Exception:
        pass

    # Direct chart API fallback: fetch 6mo hourly and resample to daily
    try:
        import urllib.parse
        import requests
        from execution.yf_helper import get_yf_session
        session = get_yf_session()
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?range=6mo&interval=1h"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = session.get(url, headers=headers, timeout=10) if session else requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            res0 = r.json().get("chart", {}).get("result", [])[0]
            ts = res0.get("timestamp", [])
            closes = res0.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            if ts and closes:
                dates = [datetime.fromtimestamp(t) for t in ts]
                raw_df = pd.DataFrame({"close": closes}, index=pd.DatetimeIndex(dates)).dropna()
                daily = raw_df.resample("D").last().dropna()
                if len(daily) >= 15:
                    return daily
    except Exception as e:
        logger.debug(f"Hourly fallback failed for {ticker}: {e}")
    return None

def compute_rrg_for_stock(symbol: str, bench_df: pd.DataFrame, rs_window=10, mom_window=4) -> dict | None:
    """Computes rs_ratio and rs_momentum for a single stock against the benchmark."""
    ticker = symbol if (symbol.endswith((".NS", ".BO")) or symbol.startswith("^")) else symbol + ".NS"
    try:
        stock_df = _fetch_series_for_rrg(ticker)
        if stock_df is None or len(stock_df) < (rs_window + mom_window + 5):
            return None

        # Clean columns and index
        stock_df.columns = [c.lower() for c in stock_df.columns]
        if stock_df.index.tz is not None:
            stock_df.index = stock_df.index.tz_localize(None)
        stock_df.index = stock_df.index.normalize()

        # Align with benchmark data
        joined = pd.DataFrame({
            "stock": stock_df["close"],
            "bench": bench_df["close"]
        }).dropna()

        if len(joined) < (rs_window + mom_window + 5):
            return None

        # RRG Logic
        pr = joined["stock"] / joined["bench"]
        
        # RS Ratio: ratio of price to its rolling mean, scaled by 100
        rolling_mean = pr.rolling(window=rs_window).mean()
        rs_ratio = 100 * (pr / rolling_mean)
        
        # RS Momentum: rate of change of the RS Ratio, scaled by 100
        rs_mom = 100 + (rs_ratio.pct_change(periods=mom_window) * 100)

        # Get latest coordinates
        latest_ratio = rs_ratio.iloc[-1]
        latest_mom = rs_mom.iloc[-1]

        if np.isnan(latest_ratio) or np.isnan(latest_mom) or np.isinf(latest_ratio) or np.isinf(latest_mom):
            return None

        # Determine quadrant
        if latest_ratio >= 100 and latest_mom >= 100:
            quadrant = "Leading"
        elif latest_ratio >= 100 and latest_mom < 100:
            quadrant = "Weakening"
        elif latest_ratio < 100 and latest_mom < 100:
            quadrant = "Lagging"
        else:
            quadrant = "Improving"

        clean_sym = symbol.replace(".NS", "").replace(".BO", "")
        display_name = SECTOR_MAP.get(symbol, clean_sym)

        return {
            "symbol": clean_sym,
            "name": display_name,
            "raw_symbol": symbol,
            "rs_ratio": round(float(latest_ratio), 4),
            "rs_momentum": round(float(latest_mom), 4),
            "quadrant": quadrant,
            "price": round(float(joined["stock"].iloc[-1]), 2)
        }
    except Exception as e:
        logger.debug(f"Failed RRG calculation for {symbol}: {e}")
        return None

def scan_rrg(category: str = "nifty50", rs_window: int = 10, mom_window: int = 4) -> dict:
    """Scan and compute RRG coordinates for all stocks in the selected category."""
    # 1. Load universe symbols
    symbols = []
    # Complete 21 Sectoral indices universe
    SECTOR_INDICES = list(SECTOR_MAP.keys())
    try:
        from execution.vcp_screener import (
            get_nse_500_symbols,
            get_midcap_150_symbols,
            get_smallcap_250_symbols,
            get_microcap_250_symbols
        )
        from execution.screener import UNIVERSE
        
        if category == "sectors":
            symbols = SECTOR_INDICES
        else:
            symbols = UNIVERSE.get(category, [])
            if not symbols:
                if category == "nifty200":
                    symbols = get_nse_500_symbols()[:200]
                elif category == "midcap150":
                    symbols = get_midcap_150_symbols()
                elif category == "smallcap250":
                    symbols = get_smallcap_250_symbols()
                elif category == "microcap250":
                    symbols = get_microcap_250_symbols()
                elif category == "midcap100":
                    symbols = get_midcap_150_symbols()[:100]
                elif category == "smallcap100":
                    symbols = get_smallcap_250_symbols()[:100]
                elif category == "nifty500":
                    symbols = get_nse_500_symbols()
                else:
                    symbols = UNIVERSE.get("nifty50", [])
    except Exception as e:
        logger.error(f"Failed to load symbols for category {category}: {e}")
        symbols = ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"]

    # Cap list size to MAX_SYMBOLS
    if len(symbols) > RRG_CONFIG["MAX_SYMBOLS"]:
        symbols = symbols[:RRG_CONFIG["MAX_SYMBOLS"]]

    # 2. Fetch Benchmark Data
    # For sectoral RRG, use NIFTY 500 as the broad market benchmark
    bench_symbol = "^CRSLDX" if category == "sectors" else RRG_CONFIG["DEFAULT_BENCHMARK"]
    bench_df = get_historical_data_safe(bench_symbol, period=RRG_CONFIG["DATA_PERIOD"])
    
    # Fallback to Nifty 50 if NIFTY 500 fetch fails
    if bench_df is None or bench_df.empty:
        bench_symbol = RRG_CONFIG["DEFAULT_BENCHMARK"]
        bench_df = get_historical_data_safe(bench_symbol, period=RRG_CONFIG["DATA_PERIOD"])
    
    if bench_df is None or bench_df.empty:
        raise ValueError("Failed to fetch benchmark index daily prices.")
    
    bench_df.columns = [c.lower() for c in bench_df.columns]
    if bench_df.index.tz is not None:
        bench_df.index = bench_df.index.tz_localize(None)
    bench_df.index = bench_df.index.normalize()

    # 3. Process stocks concurrently
    results = []
    with ThreadPoolExecutor(max_workers=RRG_CONFIG["MAX_WORKERS"]) as pool:
        futures = {
            pool.submit(compute_rrg_for_stock, sym, bench_df, rs_window, mom_window): sym 
            for sym in symbols
        }
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                results.append(res)

    # Sort results alphabetically by symbol for UI consistency
    results.sort(key=lambda x: x["symbol"])

    return {
        "stocks": results,
        "benchmark": bench_symbol,
        "rs_window": rs_window,
        "mom_window": mom_window,
        "category": category,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

if __name__ == "__main__":
    import json
    print(json.dumps(scan_rrg("nifty50"), indent=2))
