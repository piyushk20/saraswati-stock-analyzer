"""
execution/flag_screener.py
-------------------------
Perfect Flag Screener for NSE/BSE markets.
Identifies high-momentum flag continuation patterns using 8 strict criteria.
"""

import logging
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────
FLAG_CONFIG = {
    "MAX_WORKERS": 50,
    "DATA_PERIOD": "2y",
    "SYMBOL_CAP": 500,
    "MIN_PRICE": 20.0,
    "MIN_SCORE": 40.0,
}

WEIGHTS = {
    "stage2":      0.20,
    "flagpole":    0.18,
    "pullback":    0.15,
    "depth":       0.12,
    "constructive":0.10,
    "young":       0.10,
    "volume":      0.15,
}

# ── Helper Functions ───────────────────────────────────────────────

def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()

def _safe_float(v) -> float | None:
    try:
        if v is None: return None
        f = float(v)
        if np.isnan(f) or np.isinf(f): return None
        return f
    except: return None

# ── Criterion Functions ────────────────────────────────────────────

def score_stage2(df: pd.DataFrame) -> tuple[bool, float, dict]:
    row = df.iloc[-1]
    c, e20, e50, s150, s200 = row["close"], row["ema20"], row["ema50"], row["sma150"], row["sma200"]
    stack = (c > e20) and (e20 > e50) and (e50 > s150) and (s150 > s200)
    if not stack: return False, 0.0, {"stage2_stack": False}
    w = 10
    s150_rising = df["sma150"].iloc[-1] > df["sma150"].iloc[-w]
    s200_rising = df["sma200"].iloc[-1] > df["sma200"].iloc[-w]
    pct_above = (c / s150 - 1) * 100
    score = 60.0
    if s150_rising: score += 20
    if s200_rising: score += 20
    return True, min(score, 100), {"stage2_stack": True, "sma150_rising": bool(s150_rising), "sma200_rising": bool(s200_rising), "pct_above_sma150": round(pct_above, 1)}

def find_flagpole(df: pd.DataFrame) -> tuple | None:
    closes = df["close"].values
    volumes = df["volume"].values
    n = len(closes)
    vol50 = np.convolve(volumes, np.ones(50)/50, mode="same")
    best = None
    best_score = 0.0
    search_from = max(60, n - 250)
    for end in range(n - 5, search_from, -1):
        for start in range(max(0, end - 60), end - 10):
            gain = (closes[end] / closes[start]) - 1
            if gain < 0.30: continue
            log_p = np.log(closes[start:end+1])
            x = np.arange(len(log_p))
            if len(x) < 3: continue
            corr = np.corrcoef(x, log_p)[0, 1]
            r2 = corr ** 2
            if r2 < 0.80: continue
            pole_vol = volumes[start:end+1].mean()
            base_vol = vol50[start]
            vol_ratio = pole_vol / base_vol if base_vol > 0 else 1.0
            if vol_ratio < 1.2: continue
            score = gain * r2 * min(vol_ratio, 2.0)
            if score > best_score:
                best_score = score
                best = (start, end, gain * 100, r2, vol_ratio)
    return best

def score_flagpole(df: pd.DataFrame) -> tuple[bool, float, dict]:
    result = find_flagpole(df)
    if result is None: return False, 0.0, {"flagpole_found": False}
    start, end, gain_pct, r2, vol_ratio = result
    s_gain = min(gain_pct / 0.80, 1.0) * 40
    s_r2 = (r2 - 0.80) / 0.20 * 30 if r2 > 0.80 else 0
    s_vol = min((vol_ratio - 1.2) / 0.8, 1.0) * 30
    return True, min(s_gain + s_r2 + s_vol, 100), {"flagpole_found": True, "pole_start_bar": int(start), "pole_end_bar": int(end), "pole_gain_pct": round(gain_pct, 1), "pole_r2": round(r2, 3), "pole_vol_ratio": round(vol_ratio, 2)}

def score_orderly_pullback(df: pd.DataFrame, pole_end: int) -> tuple[bool, float, dict]:
    flag_df = df.iloc[pole_end:]
    if len(flag_df) < 5: return False, 0.0, {}
    closes, highs, lows, atrs = flag_df["close"].values, flag_df["high"].values, flag_df["low"].values, flag_df["atr"].values
    atr_pcts = [atrs[i] / closes[i] * 100 for i in range(len(closes)) if closes[i] > 0]
    avg_atr_pct = np.mean(atr_pcts) if atr_pcts else 99
    overlaps = []
    for i in range(1, len(highs)):
        overlap_pct = (min(highs[i], highs[i-1]) - max(lows[i], lows[i-1])) / (highs[i-1] - lows[i-1] + 1e-9)
        overlaps.append(max(overlap_pct, 0))
    avg_overlap = np.mean(overlaps) if overlaps else 0
    score = max(0, (3.0 - avg_atr_pct) / 3.0) * 60 + max(0, (0.60 - avg_overlap) / 0.60) * 40
    return avg_atr_pct < 3.0, min(score, 100), {"avg_atr_pct": round(avg_atr_pct, 2), "avg_overlap": round(avg_overlap, 2), "flag_bars": len(flag_df)}

def score_shallow_depth(df: pd.DataFrame, pole_end: int) -> tuple[bool, float, dict]:
    flag_df = df.iloc[pole_end:]
    if len(flag_df) < 5: return False, 0.0, {}
    peak, trough = flag_df["high"].max(), flag_df["low"].min()
    depth = (peak - trough) / peak * 100
    return depth <= 20.0, min(max(0, (20.0 - depth) / 20.0) * 100, 100), {"flag_depth_pct": round(depth, 1)}

def score_constructive_base(df: pd.DataFrame, pole_end: int) -> tuple[bool, float, dict]:
    flag_df = df.iloc[pole_end:]
    if len(flag_df) < 8: return True, 40.0, {"too_short": True}
    lows, ranges = flag_df["low"].values, (flag_df["high"] - flag_df["low"]).values
    x = np.arange(len(lows))
    low_corr = np.corrcoef(x, lows)[0, 1] if len(lows) > 2 else 0
    rng_corr = np.corrcoef(x, ranges)[0, 1] if len(ranges) > 2 else 0
    score = 30.0 + (40 if low_corr > 0 else 0) + (30 if rng_corr < 0 else 0)
    return True, min(score, 100), {"rising_lows": low_corr > 0, "range_tightening": rng_corr < 0}

def score_young_trend(df: pd.DataFrame, pole_start: int) -> tuple[bool, float, dict]:
    pre = df.iloc[:pole_start]
    if len(pre) < 40: return True, 100.0, {"prior_rallies": 0}
    closes, rallies, i = pre["close"].values, 0, 0
    while i < len(closes) - 20:
        if (closes[i:i+20].max() / closes[i:i+20].min()) - 1 >= 0.30:
            rallies += 1
            i += 20
        else: i += 5
    score = 100.0 if rallies == 0 else (70.0 if rallies == 1 else 30.0)
    return rallies <= 1, score, {"prior_rallies": rallies}

def score_volume_contraction(df: pd.DataFrame, pole_end: int) -> tuple[bool, float, dict]:
    flag_df = df.iloc[pole_end:]
    if len(flag_df) < 5: return False, 0.0, {}
    vols, closes = flag_df["volume"].values, flag_df["close"].values
    vol_corr = np.corrcoef(np.arange(len(vols)), vols)[0, 1] if len(vols) > 2 else 0
    down_vols = [vols[i] for i in range(1, len(closes)) if closes[i] < closes[i-1]]
    up_vols = [vols[i] for i in range(1, len(closes)) if closes[i] >= closes[i-1]]
    quiet_down = (np.mean(down_vols) < np.mean(up_vols)) if (down_vols and up_vols) else False
    score = 20.0 + (50 if vol_corr < 0 else 0) + (30 if quiet_down else 0)
    return True, min(score, 100), {"declining_volume": vol_corr < 0, "quiet_down_days": quiet_down}

# ── Main Scanner ──────────────────────────────────────────────────

def _fetch_and_analyze(symbol: str) -> dict | None:
    ticker = symbol if symbol.endswith(".NS") else symbol + ".NS"
    try:
        df = yf.download(ticker, period=FLAG_CONFIG["DATA_PERIOD"], interval="1d", progress=False, auto_adjust=True)
        if df is None or len(df) < 200: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        
        c = df["close"]
        df["ema20"], df["ema50"], df["sma150"], df["sma200"] = ema(c, 20), ema(c, 50), sma(c, 150), sma(c, 200)
        df["atr"] = pd.concat([(df["high"]-df["low"]), (df["high"]-df["close"].shift()).abs(), (df["low"]-df["close"].shift()).abs()], axis=1).max(axis=1).rolling(14).mean()
        
        if (df["volume"].iloc[-20:].mean() < 100000) and (df["close"].iloc[-1] * df["volume"].iloc[-20:].mean() < 1e7): return None

        s2_pass, s2_score, s2_detail = score_stage2(df)
        if not s2_pass: return None
        
        pole_pass, pole_score, pole_detail = score_flagpole(df)
        if not pole_pass: return None
        
        pole_end, pole_start = pole_detail["pole_end_bar"], pole_detail["pole_start_bar"]
        pull_pass, pull_score, pull_detail = score_orderly_pullback(df, pole_end)
        dep_pass, dep_score, dep_detail = score_shallow_depth(df, pole_end)
        if not dep_pass: return None
        
        con_pass, con_score, con_detail = score_constructive_base(df, pole_end)
        young_pass, young_score, young_detail = score_young_trend(df, pole_start)
        vol_pass, vol_score, vol_detail = score_volume_contraction(df, pole_end)
        
        composite = (s2_score*WEIGHTS["stage2"] + pole_score*WEIGHTS["flagpole"] + pull_score*WEIGHTS["pullback"] + 
                     dep_score*WEIGHTS["depth"] + con_score*WEIGHTS["constructive"] + young_score*WEIGHTS["young"] + vol_score*WEIGHTS["volume"])
        
        if composite < FLAG_CONFIG["MIN_SCORE"]: return None

        return {
            "symbol": symbol.replace(".NS", ""),
            "price": round(float(df["close"].iloc[-1]), 2),
            "score": round(composite, 1),
            "gain_pct": pole_detail["pole_gain_pct"],
            "depth_pct": dep_detail["flag_depth_pct"],
            "rating": "⭐⭐⭐ PERFECT" if composite >= 85 else ("⭐⭐ STRONG" if composite >= 70 else "⭐ DEVELOPING")
        }
    except: return None

def scan_flag():
    from execution.vcp_screener import get_nse_500_symbols
    symbols = get_nse_500_symbols()[:FLAG_CONFIG["SYMBOL_CAP"]]
    logger.info(f"Scanning {len(symbols)} symbols for Perfect Flag...")
    candidates = []
    with ThreadPoolExecutor(max_workers=FLAG_CONFIG["MAX_WORKERS"]) as pool:
        futures = {pool.submit(_fetch_and_analyze, s): s for s in symbols}
        for fut in as_completed(futures):
            res = fut.result()
            if res: candidates.append(res)
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return {"flag_stocks": candidates, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

if __name__ == "__main__":
    import json
    print(json.dumps(scan_flag(), indent=2))
