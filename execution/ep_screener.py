"""
execution/ep_screener.py
-------------------------
Episodic Pivot (EP) Screener for NSE/BSE markets.
Adapted from Qullamaggie / Stockbee EP methodology.

Strategy Logic:
  - Gap up >= 6.5% from previous close (catalyst/result day)
  - Relative volume >= 2.0x 20-day average
  - Price >= 150-day SMA (Stage 2 uptrend)
  - Price >= 50-day SMA (intermediate trend)
  - 52-week high proximity >= 70%
  - Scores each candidate 0-100

Uses only: yfinance, pandas, numpy (already in requirements.txt)
No pandas_ta dependency — RSI is computed inline.
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
logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────
EP_CONFIG = {
    "GAP_MIN_PCT":       6.5,    # Strict minimum gap-up % required
    "RVOL_MIN":          2.0,    # Strict relative volume vs 20-day avg
    "SMA150_FILTER":     True,   # Price must be above 150 SMA
    "SMA50_FILTER":      True,   # Price must be above 50 SMA
    "HIGH52W_PROXIMITY": 0.70,   # Price >= 70% of 52-week high
    "MIN_PRICE":         20.0,   # Minimum stock price (₹)
    "MAX_WORKERS":       15,     # Parallel threads
    "DATA_PERIOD":       "2y",   # yfinance history period
    "SYMBOL_CAP":        800,    # Max symbols to scan
    "LOOKBACK_DAYS":     5,      # Days back to detect EP burst (1=today, 2=incl yesterday, etc)
}


# ── Inline RSI (Wilder's EMA) ── no pandas_ta required ─────────────
def _calc_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Calculate RSI using Wilder's smoothing method."""
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)

    # Wilder smoothing (equivalent to EWM with alpha=1/length)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()

    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def _safe_float(v) -> float | None:
    """Convert value to float, returning None if NaN/None/invalid."""
    try:
        if v is None:
            return None
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


# ── Single symbol analysis ──────────────────────────────────────────
def _fetch_and_analyze(symbol: str) -> dict | None:
    """Download OHLCV data and compute EP signal for one symbol."""
    # Ensure .NS suffix
    ticker = symbol if symbol.endswith((".NS", ".BO")) else symbol + ".NS"

    try:
        t = get_ticker(ticker)
        df = t.history(
            period=EP_CONFIG["DATA_PERIOD"],
            interval="1d",
            auto_adjust=True,
            timeout=10,
        )

        if df is None or len(df) < 60:
            return None

        # Flatten MultiIndex columns (yfinance quirk with single ticker)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]

        df = df.dropna(subset=["Close", "Volume"])
        if len(df) < 60:
            return None

        close  = df["Close"].astype(float)
        high   = df["High"].astype(float)
        low    = df["Low"].astype(float)
        open_  = df["Open"].astype(float)
        volume = df["Volume"].astype(float)

        # ── Indicators ──────────────────────────────────────────────
        sma50   = close.rolling(50).mean()
        sma150  = close.rolling(150).mean()
        sma200  = close.rolling(200).mean()
        vol_avg = volume.rolling(20).mean()
        rsi14   = _calc_rsi(close, 14)

        # ── Snapshot values ─────────────────────────────────────────
        today_close = _safe_float(close.iloc[-1])
        if today_close is None or today_close < EP_CONFIG["MIN_PRICE"]:
            return None

        # ── 52-week metrics ─────────────────────────────────────────
        lookback = min(252, len(close))
        w52_high = _safe_float(high.iloc[-lookback:].max())
        w52_low  = _safe_float(low.iloc[-lookback:].min())
        if w52_high is None or w52_high == 0:
            return None

        pct_from_52h = ((today_close - w52_high) / w52_high) * 100.0

        # ── SMA values ──────────────────────────────────────────────
        s50  = _safe_float(sma50.iloc[-1])
        s150 = _safe_float(sma150.iloc[-1])
        s200 = _safe_float(sma200.iloc[-1])

        above_sma50  = bool(s50  and today_close >= s50)
        above_sma150 = bool(s150 and today_close >= s150)
        above_sma200 = bool(s200 and today_close >= s200)

        # ── Stage 2: price > SMA150 > SMA200, SMA200 trending up ───
        is_stage2 = False
        if s150 and s200 and len(sma200) > 22:
            s200_1mo = _safe_float(sma200.iloc[-22])
            is_stage2 = bool(
                today_close > s150 > s200
                and s200_1mo is not None
                and s200 > s200_1mo
            )

        # ── EP Detection: check last LOOKBACK_DAYS for a burst ─────
        burst_found = False
        burst_data  = {}
        lookback_n  = min(EP_CONFIG["LOOKBACK_DAYS"], len(df) - 2)

        for i in range(-1, -(lookback_n + 2), -1):
            try:
                day_close  = _safe_float(close.iloc[i])
                yday_close = _safe_float(close.iloc[i - 1])
                day_open   = _safe_float(open_.iloc[i])
                day_vol    = _safe_float(volume.iloc[i])
                avg_vol    = _safe_float(vol_avg.iloc[i - 1])  # avoid look-ahead
                prev_rsi   = _safe_float(rsi14.iloc[i - 1])

                if not all([day_close, yday_close, day_open, day_vol, avg_vol]):
                    continue
                if avg_vol == 0:
                    continue

                gap_pct = ((day_open - yday_close) / yday_close) * 100.0
                rvol    = day_vol / avg_vol

                if gap_pct < EP_CONFIG["GAP_MIN_PCT"]:
                    continue
                if rvol < EP_CONFIG["RVOL_MIN"]:
                    continue

                # ATR contraction (consolidation before burst)
                atr_now  = _safe_float((high - low).rolling(20).mean().iloc[i])
                atr_prev = _safe_float((high - low).rolling(60).mean().iloc[i - 3]) if len(df) > abs(i) + 3 else None
                consolidation = bool(atr_now and atr_prev and atr_now < atr_prev * 1.2)

                burst_date = str(df.index[i].date()) if hasattr(df.index[i], "date") else str(df.index[i])[:10]
                days_ago   = abs(i) - 1  # 0=today, 1=yesterday, etc.

                burst_data = {
                    "gap_pct":      round(gap_pct, 2),
                    "rvol":         round(rvol, 2),
                    "burst_date":   burst_date,
                    "days_ago":     days_ago,
                    "prev_rsi":     round(prev_rsi, 2) if prev_rsi else None,
                    "consolidation": consolidation,
                }
                burst_found = True
                break  # Most recent burst wins

            except (IndexError, TypeError):
                continue

        if not burst_found:
            return None

        # ── Filters ─────────────────────────────────────────────────
        if EP_CONFIG["SMA150_FILTER"] and not above_sma150:
            return None
        if EP_CONFIG["SMA50_FILTER"] and not above_sma50:
            return None
        if today_close / w52_high < EP_CONFIG["HIGH52W_PROXIMITY"]:
            return None

        # ── EP Score (0–100) ─────────────────────────────────────────
        score = 0.0
        gap_pct = burst_data["gap_pct"]
        rvol    = burst_data["rvol"]

        # Gap contribution (max 35 pts)
        if gap_pct >= EP_CONFIG["GAP_MIN_PCT"]:
            score += min(35.0, 10.0 + (gap_pct - EP_CONFIG["GAP_MIN_PCT"]) * 2.0)

        # Relative volume (max 30 pts)
        if rvol >= EP_CONFIG["RVOL_MIN"]:
            score += min(30.0, 10.0 + (rvol - EP_CONFIG["RVOL_MIN"]) * 5.0)

        # Trend filters (max 20 pts)
        if above_sma150: score += 8
        if above_sma200: score += 7
        if is_stage2:    score += 5

        # 52-week proximity (max 10 pts)
        if pct_from_52h >= -10:    score += 10
        elif pct_from_52h >= -20:  score += 5
        elif pct_from_52h >= -30:  score += 2

        # Consolidation bonus (max 5 pts)
        if burst_data.get("consolidation"): score += 5

        return {
            "symbol":        ticker,
            "display_symbol": symbol,
            "price":         round(today_close, 2),
            "gap_pct":       burst_data["gap_pct"],
            "rvol":          burst_data["rvol"],
            "burst_date":    burst_data["burst_date"],
            "days_ago":      burst_data["days_ago"],
            "prev_rsi":      burst_data.get("prev_rsi"),
            "consolidation": burst_data.get("consolidation", False),
            "above_sma50":   above_sma50,
            "above_sma150":  above_sma150,
            "above_sma200":  above_sma200,
            "is_stage2":     is_stage2,
            "w52_high":      round(w52_high, 2),
            "w52_low":       round(w52_low, 2) if w52_low else None,
            "pct_from_52h":  round(pct_from_52h, 2),
            "score":         round(min(score, 100.0), 1),
        }

    except Exception as e:
        logger.debug("EP scan error for %s: %s", symbol, e)
        return None


# ── Main scan function ──────────────────────────────────────────────
def scan_ep(cap: int = None) -> dict:
    """
    Screen NSE 500 for Episodic Pivot setups.
    Returns: {"ep_stocks": [...], "scanned": N, "timestamp": "..."}
    """
    try:
        # Import the shared symbol list from vcp_screener (no duplication)
        from execution.vcp_screener import get_all_symbols
        symbols_raw = get_all_symbols()
    except Exception as e:
        logger.error("Could not load symbols: %s", e)
        return {"error": f"Could not load symbol list: {e}"}

    cap = cap or EP_CONFIG["SYMBOL_CAP"]
    # Strip .NS suffix for display; re-added inside _fetch_and_analyze
    symbols = [s.replace(".NS", "").replace(".BO", "") for s in symbols_raw[:cap]]

    logger.info("EP Scan: scanning %d symbols...", len(symbols))

    candidates = []
    with ThreadPoolExecutor(max_workers=EP_CONFIG["MAX_WORKERS"]) as pool:
        futures = {pool.submit(_fetch_and_analyze, s): s for s in symbols}
        for fut in as_completed(futures):
            result = fut.result()
            if result is not None:
                candidates.append(result)

    # Sort by score descending
    candidates.sort(key=lambda x: x["score"], reverse=True)

    logger.info("EP Scan complete: %d candidates from %d symbols.", len(candidates), len(symbols))

    return {
        "ep_stocks": candidates,
        "scanned":   len(symbols),
        "found":     len(candidates),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


if __name__ == "__main__":
    import json
    results = scan_ep()
    print(json.dumps(results, indent=2))
