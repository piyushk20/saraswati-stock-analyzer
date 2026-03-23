import os
import sys
import yfinance as yf
import pandas as pd
import numpy as np
import json
import logging
import argparse
import time
from datetime import datetime, timedelta

# nsefin for historical data as requested
try:
    from nsefin import NSEClient
    nse_client = NSEClient()
except ImportError:
    nse_client = None

def get_historical_data(symbol, period="5y"):
    """
    Fetch historical data using nsefin with yfinance fallback.
    nsefin is used for candlestick charts as requested.
    """
    df = None
    
    # Try nsefin first for candlestick data
    if nse_client and not symbol.startswith('^'):
        try:
            # clean symbol for nsefin (remove .NS)
            nse_symbol = symbol.replace('.NS', '')
            logger.info(f"📡 Attempting nsefin fetch for {nse_symbol}...")
            
            # Map period to day_count (roughly)
            day_map = {'1mo': 30, '3mo': 90, '6mo': 180, '1y': 365, '2y': 730, '5y': 1825}
            days = day_map.get(period, 1825)
            
            # Use history method discovered via inspect: (self, symbol: 'str', day_count: 'int' = 365)
            df = nse_client.history(symbol=nse_symbol, day_count=days)
            
            if df is not None and not df.empty:
                logger.info(f"✅ nsefin fetch successful for {nse_symbol}")
                # nsefin returns Date, Open, High, Low, Close, Volume
                # Ensure index is datetime
                if 'Date' in df.columns:
                    df['Date'] = pd.to_datetime(df['Date'])
                    df.set_index('Date', inplace=True)
                return df
        except Exception as e:
            logger.warning(f"⚠️ nsefin failed for {symbol}: {e}. Falling back to yfinance.")

    # Fallback to yfinance
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)
        if df is not None and not df.empty:
            return df
    except Exception as e:
        logger.error(f"❌ yfinance fallback failed for {symbol}: {e}")
        
    return None

# Add the project root to sys.path to find our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    from execution.nse_options import get_nse_option_chain
    logger.debug("Successfully imported get_nse_option_chain from execution.nse_options")
except ImportError as e1:
    logger.debug("Failed first import in analyze_stock: %s", e1)
    # Handle if run directly from execution folder
    try:
        from nse_options import get_nse_option_chain
        logger.debug("Successfully imported get_nse_option_chain from nse_options")
    except ImportError as e2:
        logger.debug("Failed second import in analyze_stock: %s", e2)
        def get_nse_option_chain(symbol, is_index=False):
            logger.debug("Using dummy get_nse_option_chain returning None")
            return {"current": None, "next": None}

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
    except Exception:
        return default

def safe_round(val, digits=2):
    """Safely round value if not None/NaN."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    try:
        return round(float(val), digits)
    except Exception:
        return None

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
        "pp": safe_round(pp),
        "r1": safe_round(r1),
        "s1": safe_round(s1),
        "r2": safe_round(r2),
        "s2": safe_round(s2),
        "r3": safe_round(r3),
        "s3": safe_round(s3)
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
                "nifty_1m": safe_round(history_1m_pct - nifty_1m_pct),
                "nifty_1y": safe_round(history_1y_pct - nifty_1y_pct),
                "sector_index": "Nifty 50",
                "sector_1m": safe_round(history_1m_pct - nifty_1m_pct),
                "sector_1y": safe_round(history_1y_pct - nifty_1y_pct)
            }
    except Exception as e:
        logger.error(f"Error calculating RS for {symbol}: {e}")
        pass
    return None

def get_multi_tf_rsi(symbol, df_daily=None):
    """Calculates RSI for Daily and Weekly timeframes using provided daily data."""
    results: dict[str, float | None] = {"daily": None, "weekly": None, "monthly": None}
    try:
        # 1. Daily RSI
        if df_daily is not None and not df_daily.empty and len(df_daily) > 14:
            rsi_series = calculate_rsi(df_daily['Close'])
            if not rsi_series.empty:
                val = rsi_series.iloc[-1]
                results["daily"] = safe_round(val)

        # 2. Weekly RSI - Resample from Daily to avoid another API call
        if df_daily is not None and not df_daily.empty:
            # Resample daily data to weekly (end of week)
            # Use 'W-FRI' for typical stock market week ending Friday
            w_df = df_daily['Close'].resample('W-FRI').last()
            if len(w_df) > 14:
                w_rsi = calculate_rsi(w_df).iloc[-1]
                results["weekly"] = safe_round(w_rsi)
        
        # 3. Monthly RSI - Resample from Daily
        if df_daily is not None and not df_daily.empty:
            m_df = df_daily['Close'].resample('M').last()
            if len(m_df) > 14:
                m_rsi = calculate_rsi(m_df).iloc[-1]
                results["monthly"] = safe_round(m_rsi)
                    
    except Exception as e:
        logger.error(f"Error in get_multi_tf_rsi for {symbol}: {e}")
    return results

def compute_ema(series: pd.Series, span: int) -> float | None:
    """Compute the latest EMA value for a given span."""
    if len(series) < span // 2:
        return None
    ema = series.ewm(span=span, adjust=False).mean()
    val = ema.iloc[-1]
    if pd.isna(val):
        return None
    return safe_round(float(val))


def compute_ema_series(series: pd.Series, span: int, n: int = 90) -> list:
    """Return the last `n` EMA values as a list."""
    tail = series.tail(max(n * 3, span * 2))  # Need warm-up window
    ema = tail.ewm(span=span, adjust=False).mean().tail(n)
    return [safe_round(v) for v in ema]


def compute_trend_template(price, sma_20, sma_50, sma_200, df_full, wk52_high, wk52_low,
                           rs_data, eps_growth_pct=None, revenue_growth_pct=None,
                           margin_expanding=None, earnings_surprise=None):
    """
    Evaluate the Stan Weinstein / Minervini Trend Template.
    Returns a dict with per-criterion pass/fail and an overall score.
    """
    checks = []

    def add_check(label, passed, value_str="", group="Technical"):
        checks.append({
            "label": label,
            "pass": passed,
            "value": value_str,
            "group": group
        })

    # ── Technical Criteria ────────────────────────────────────────
    # 1. Price > 50, 150, 200 SMAs
    p50   = (price > sma_50)  if (price and sma_50)  else False
    p150  = (price > sma_20)  if (price and sma_20)  else False   # Using 20 SMA as proxy for 150 since we calculate it
    p200  = (price > sma_200) if (price and sma_200) else False
    add_check("Price > 50 SMA",  p50,  f"₹{price:.0f} vs ₹{sma_50:.0f}"  if (price and sma_50)  else "N/A")
    add_check("Price > 200 SMA", p200, f"₹{price:.0f} vs ₹{sma_200:.0f}" if (price and sma_200) else "N/A")

    # 2. 50 SMA > 200 SMA (MA alignment)
    ma_align = (sma_50 > sma_200) if (sma_50 and sma_200) else False
    add_check("50 SMA > 200 SMA", ma_align,
              f"₹{sma_50:.0f} vs ₹{sma_200:.0f}" if (sma_50 and sma_200) else "N/A")

    # 3. 200 SMA trending up (compare to 1 month ago, ~21 bars)
    sma200_trending_up = False
    sma200_val_1m = None
    try:
        closes = df_full['Close']
        sma200_series = closes.rolling(200).mean()
        if len(sma200_series.dropna()) > 21:
            sma200_val_1m = sma200_series.iloc[-22]
            if not pd.isna(sma200_val_1m):
                sma200_trending_up = sma_200 > float(sma200_val_1m)
    except Exception:
        pass
    add_check("200 SMA Trending Up", sma200_trending_up,
              f"Now ₹{sma_200:.0f}" if sma_200 else "N/A")

    # 4. Price within 25% of 52-week HIGH
    near_high = False
    if price and wk52_high:
        near_high = price >= (wk52_high * 0.75)
    add_check("Within 25% of 52W High", near_high,
              f"{((price/wk52_high)-1)*100:.1f}%" if (price and wk52_high) else "N/A")

    # 5. Price at least 30% above 52-week LOW
    above_low = False
    if price and wk52_low:
        above_low = price >= (wk52_low * 1.30)
    add_check("30%+ Above 52W Low", above_low,
              f"+{((price/wk52_low)-1)*100:.1f}%" if (price and wk52_low) else "N/A")

    # ── Fundamental Criteria ─────────────────────────────────────
    # EPS Growth
    eps_ok = (eps_growth_pct is not None and eps_growth_pct >= 20)
    add_check("EPS Growth 20%+",
              eps_ok,
              f"+{eps_growth_pct:.1f}%" if eps_growth_pct is not None else "N/A",
              group="Fundamental")

    # Revenue/Sales Growth
    rev_ok = (revenue_growth_pct is not None and revenue_growth_pct >= 20)
    add_check("Revenue Growth 20%+",
              rev_ok,
              f"+{revenue_growth_pct:.1f}%" if revenue_growth_pct is not None else "N/A",
              group="Fundamental")

    # Margin Expanding
    margin_ok = margin_expanding is True
    add_check("Expanding Margins", margin_ok,
              "Yes" if margin_expanding else ("No" if margin_expanding is False else "N/A"),
              group="Fundamental")

    # Positive Earnings Surprise
    surprise_ok = earnings_surprise is True
    add_check("Positive Earnings Surprise", surprise_ok,
              "Yes" if earnings_surprise else ("No" if earnings_surprise is False else "N/A"),
              group="Fundamental")

    # ── Other Factors ─────────────────────────────────────────────
    # RS Rating > 70
    rs_ok = False
    rs_score_val = None
    if rs_data:
        rs_1y = rs_data.get("nifty_1y") or 0
        # Simple mapping: outperform Nifty by >10% → RS 80+, >5% → RS 70+
        rs_score_val = 50 + rs_1y  # rough
        rs_ok = rs_score_val > 70
    add_check("Relative Strength > 70", rs_ok,
              f"~{rs_score_val:.0f}" if rs_score_val is not None else "N/A",
              group="Other")

    # Count pass/fail
    passed_count = sum(1 for c in checks if c["pass"])
    total = len(checks)
    score_pct = round(passed_count / total * 100) if total else 0

    return {
        "checks": checks,
        "passed": passed_count,
        "total": total,
        "score_pct": score_pct,
    }
def analyze(symbol):
    """Main analysis function."""
    try:
        # Normalization for Indian stocks and indices
        orig_symbol = symbol
        if symbol.upper() in ["NIFTY", "NIFTY 50", "NIFTY50"]:
            symbol = "^NSEI"
        elif symbol.upper() in ["BANKNIFTY", "NIFTY BANK"]:
            symbol = "^NSEBANK"
        elif not symbol.startswith("^") and not symbol.endswith(".NS"):
            symbol = f"{symbol.upper()}.NS"
            
        logger.info(f"Analyzing {symbol}...")
        
        # 1. Price Data - Fetch 5y once using get_historical_data
        df_full = get_historical_data(symbol, period="5y")
        if df_full is None or df_full.empty:
            return {"error": f"No data found for {symbol}", "symbol": symbol}
        
        # Create yfinance Ticker object for info, even if historical data came from nsefin
        ticker = yf.Ticker(symbol)
            
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
        
        # EMA values at current date
        ema_20_val  = compute_ema(df['Close'], 20)
        ema_50_val  = compute_ema(df['Close'], 50)
        ema_200_val = compute_ema(df_full['Close'], 200)

        # Chart Data – 90 days with OHLC + volume for candlestick + EMA lines
        chart_df = df.tail(90)
        chart_dates   = [d.strftime("%Y-%m-%d") for d in chart_df.index]
        chart_opens   = [safe_round(v) for v in chart_df['Open']]
        chart_highs   = [safe_round(v) for v in chart_df['High']]
        chart_lows    = [safe_round(v) for v in chart_df['Low']]
        chart_closes  = [safe_round(v) for v in chart_df['Close']]
        chart_volumes = [int(v) for v in chart_df['Volume']]

        # EMA series (last 90 bars)
        ema20_series  = compute_ema_series(df_full['Close'], 20,  90)
        ema50_series  = compute_ema_series(df_full['Close'], 50,  90)
        ema200_series = compute_ema_series(df_full['Close'], 200, 90)
        
        # 2. Options Data (NSE)
        nse_symbol = symbol
        is_nse_index = False
        if symbol == "^NSEI":
            nse_symbol = "NIFTY"
            is_nse_index = True
        elif symbol == "^NSEBANK":
            nse_symbol = "BANKNIFTY"
            is_nse_index = True
        elif symbol.endswith(".NS"):
            nse_symbol = symbol.replace(".NS", "")
            
        options_data = get_nse_option_chain(nse_symbol, is_nse_index)
        logger.debug("options_data result for %s: %s", nse_symbol, options_data)
        
        # 3. Multi-TF RSI (pass current daily DF to save a call)
        logger.debug("Calculating RSI for %s", symbol)
        rsi_data = get_multi_tf_rsi(symbol, df_full)
        logger.debug("RSI Results for %s: %s", symbol, rsi_data)
        
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
            "price": safe_round(current_price),
            "change": safe_round(change_1d),
            "change_pct": safe_round(change_1d_pct),
            "sma_20": safe_round(sma_20),
            "sma_50": safe_round(sma_50),
            "sma_200": safe_round(sma_200),
            "macd": safe_round(macd),
            "macd_signal": safe_round(macd_signal),
            "macd_histogram": safe_round(macd_hist),
            "volume_trend": vol_trend,
            "rsi": rsi_data,
            "ema_20":  ema_20_val,
            "ema_50":  ema_50_val,
            "ema_200": ema_200_val,
            "chart": {
                "dates":   chart_dates,
                "opens":   chart_opens,
                "highs":   chart_highs,
                "lows":    chart_lows,
                "closes":  chart_closes,
                "volumes": chart_volumes,
                "ema20":   ema20_series,
                "ema50":   ema50_series,
                "ema200":  ema200_series,
            },
            "performance": [
                {"period": "1D", "pct": safe_round(change_1d_pct)},
                {"period": "1W", "pct": safe_round(change_1w_pct)},
                {"period": "1M", "pct": safe_round(change_1m_pct)},
                {"period": "1Y", "pct": safe_round(change_1y_pct)},
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
        
        # --- Fundamentals & Trend Template ---
        result["trend_template"] = None
        eps_grow_pct = None
        rev_grow_pct = None
        margin_expanding = None
        earnings_surprise = None

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
                    "summary": (safe_get(info, "longBusinessSummary") or "")[:300],
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

                # Growth stats for Trend Template
                eps_growth = safe_get(info, "earningsGrowth")
                eps_grow_pct = float(eps_growth) * 100 if eps_growth else None
                rev_growth = safe_get(info, "revenueGrowth")
                rev_grow_pct = float(rev_growth) * 100 if rev_growth else None

                if (financials is not None and not financials.empty
                        and "Gross Profit" in financials.index
                        and len(financials.columns) >= 2):
                    gp_curr = financials.loc["Gross Profit"].iloc[0]
                    rev_curr = financials.loc["Total Revenue"].iloc[0] if "Total Revenue" in financials.index else None
                    gp_prev = financials.loc["Gross Profit"].iloc[1]
                    rev_prev = financials.loc["Total Revenue"].iloc[1] if "Total Revenue" in financials.index else None
                    if rev_curr and rev_prev and rev_curr != 0 and rev_prev != 0:
                        margin_expanding = bool((gp_curr / rev_curr) > (gp_prev / rev_prev))

                eq_growth = safe_get(info, "earningsQuarterlyGrowth")
                if eq_growth is not None:
                    earnings_surprise = bool(float(eq_growth) > 0)

            except Exception as fe:
                logger.warning(f"Error fetching fundamentals for {symbol}: {fe}")

        # Compute Trend Template (Always for technicals, fundamentals optional)
        try:
            result["trend_template"] = compute_trend_template(
                price=current_price, sma_20=sma_20, sma_50=sma_50, sma_200=sma_200,
                df_full=df_full, wk52_high=wk52_high, wk52_low=wk52_low,
                rs_data=rs_data, eps_growth_pct=eps_grow_pct, 
                revenue_growth_pct=rev_grow_pct, margin_expanding=margin_expanding,
                earnings_surprise=earnings_surprise
            )
        except Exception as tte:
            logger.warning(f"Trend Template computation failed for {symbol}: {tte}")
                
            # --- ADDED: Implied Move Analysis (Ref Code) ---
        straddle_price = 0
        implied_move = 0
        selected_exp = None
        
        # Use data from our robust nse_options fetcher
        if options_data and options_data.get("current"):
            curr = options_data["current"]
            selected_exp = curr.get("expiry")
            straddle_price = curr.get("straddle") or 0
            implied_move = curr.get("implied_move") or 0
        
        # Fallback to yfinance only if nse_options failed
        if not straddle_price:
            try:
                expirations = getattr(ticker, "options", [])
                if expirations:
                    selected_exp = expirations[0]  # Use nearest expiry by default
                    chain = ticker.option_chain(selected_exp)
                    calls = chain.calls
                    puts = chain.puts
                    
                    # Find ATM strike
                    strikes = pd.concat([calls["strike"], puts["strike"]]).unique()
                    if len(strikes) > 0:
                        call_strike = min(strikes, key=lambda x: abs(x - current_price))
                        
                        # ATM Call & Put (using ask prices as requested)
                        atm_call_rows = calls[calls["strike"] == call_strike]
                        atm_put_rows = puts[puts["strike"] == call_strike]
                        
                        atm_call_ask = atm_call_rows.iloc[0]["ask"] if not atm_call_rows.empty else 0
                        atm_put_ask = atm_put_rows.iloc[0]["ask"] if not atm_put_rows.empty else 0
                        
                        straddle_price = safe_round(float(atm_call_ask) + float(atm_put_ask))
                        
                        # Implied Move formula (Ref Code Adaptation)
                        try:
                            exp_date = datetime.strptime(selected_exp, "%Y-%m-%d").date()
                            today = datetime.now().date()
                            days_to_exp = (exp_date - today).days
                            
                            if days_to_exp > 0 and straddle_price and float(straddle_price) > 0:
                                implied_move = ((1 + float(straddle_price) / current_price) ** (1 / days_to_exp) - 1) * 100
                            else:
                                implied_move = 0
                        except Exception as e:
                            logger.error(f"Error calculating implied move from yf: {e}")
            except Exception as e:
                logger.debug(f"yfinance options fallback failed (normal for NSE): {e}")
                pass

        result.update({
            "implied_move_data": {
                "expiry": selected_exp,
                "straddle": straddle_price,
                "implied_move": safe_round(implied_move, 4)
            }
        })
        
        return result

    except Exception as e:
        logger.error(f"Analysis error for {symbol}: {e}", exc_info=True)
        return {"error": str(e), "symbol": symbol}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze an Indian stock or index.")
    parser.add_argument("symbol", nargs="?", default="^NSEI", help="yfinance ticker symbol")
    args = parser.parse_args()

    result = analyze(args.symbol)
    print(json.dumps(result, indent=2, default=str))
