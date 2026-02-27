"""
execution/analyze_stock.py
--------------------------
Deterministic script to fetch and analyze an Indian stock or index.
Follows the SOP defined in directives/analyze_stock.md.

Usage:
    python analyze_stock.py --symbol RELIANCE.NS
    python analyze_stock.py --symbol ^NSEI

Output:
    JSON to stdout with comprehensive stock analysis.
"""

import argparse
import json
import sys
import os
import warnings

# Ensure execution directory is in path for imports when called from backend
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import yfinance as yf
from vcp_screener import filter_by_vcp_conditions

warnings.filterwarnings("ignore")


def calculate_rsi(series: pd.Series, period: int = 14) -> float | None:
    """Calculate Relative Strength Index (RSI)."""
    if len(series) < period + 1:
        return None
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = -delta.clip(upper=0).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return round(float(val), 2) if not np.isnan(val) else None


def calculate_macd(series: pd.Series, fast=12, slow=26, signal=9):
    """Calculate MACD and Signal line."""
    if len(series) < slow + signal:
        return None, None
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    macd_val = macd_line.iloc[-1]
    signal_val = signal_line.iloc[-1]
    return (
        round(float(macd_val), 2) if not np.isnan(macd_val) else None,
        round(float(signal_val), 2) if not np.isnan(signal_val) else None,
    )


def safe_get(d: dict, key: str, default=None):
    """Safely retrieve a value, returning default for None/NaN."""
    val = d.get(key, default)
    if val is None:
        return default
    try:
        if np.isnan(val):
            return default
    except (TypeError, ValueError):
        pass
    return val


def analyze(symbol: str) -> dict:
    """Main analysis function. Returns a rich dict of stock metrics."""
    is_index = symbol.startswith("^")

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info

        # Validate ticker
        if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
            return {"error": "Symbol not found or no live data available.", "symbol": symbol}

        # Fetch 1-year history for all technical indicators
        # Note: hist_5d / hist_1m removed — price changes are computed from hist slices
        hist = ticker.history(period="1y")

        if hist.empty:
            return {"error": "No historical data available for this symbol.", "symbol": symbol}

        closes = hist["Close"]
        current_price = closes.iloc[-1]
        prev_close = closes.iloc[-2] if len(closes) > 1 else current_price

        # Price changes
        change_1d = current_price - prev_close
        change_1d_pct = (change_1d / prev_close) * 100 if prev_close else 0

        week_closes = closes.iloc[-6:-1] if len(closes) >= 6 else closes
        change_1w_pct = ((current_price - week_closes.iloc[0]) / week_closes.iloc[0]) * 100 if len(week_closes) > 0 else 0

        month_closes = closes.iloc[-22:] if len(closes) >= 22 else closes
        change_1m_pct = ((current_price - month_closes.iloc[0]) / month_closes.iloc[0]) * 100 if len(month_closes) > 0 else 0

        change_1y_pct = ((current_price - closes.iloc[0]) / closes.iloc[0]) * 100 if len(closes) > 0 else 0

        # Benchmark / Relative Strength Analysis
        nifty_change_1m = 0
        nifty_change_1y = 0
        try:
            nifty_hist = yf.Ticker("^NSEI").history(period="1y")
            if not nifty_hist.empty:
                n_closes = nifty_hist["Close"]
                n_current = n_closes.iloc[-1]
                n_month = n_closes.iloc[-22:] if len(n_closes) >= 22 else n_closes
                nifty_change_1m = ((n_current - n_month.iloc[0]) / n_month.iloc[0]) * 100
                nifty_change_1y = ((n_current - n_closes.iloc[0]) / n_closes.iloc[0]) * 100
        except Exception:
            pass

        rs_nifty_1m = change_1m_pct - nifty_change_1m
        rs_nifty_1y = change_1y_pct - nifty_change_1y

        # Sector Benchmark (Simple mapping)
        sector_idx = None
        sector = str(safe_get(info, "sector") or "")
        if "Financial" in sector: sector_idx = "^NSEBANK"
        elif "Technology" in sector: sector_idx = "^CNXIT"
        elif "Healthcare" in sector: sector_idx = "^CNXPHARMA"
        elif "Consumer" in sector or "Auto" in sector: sector_idx = "^CNXAUTO"
        elif "Energy" in sector: sector_idx = "^CNXENERGY"
        elif "Basic Materials" in sector: sector_idx = "^CNXMETAL"

        sector_change_1m = None
        sector_change_1y = None
        if sector_idx and not is_index:
            try:
                s_hist = yf.Ticker(sector_idx).history(period="1y")
                if not s_hist.empty:
                    s_c = s_hist["Close"]
                    s_cur = s_c.iloc[-1]
                    s_mon = s_c.iloc[-22:] if len(s_c) >= 22 else s_c
                    sector_change_1m = ((s_cur - s_mon.iloc[0]) / s_mon.iloc[0]) * 100
                    sector_change_1y = ((s_cur - s_c.iloc[0]) / s_c.iloc[0]) * 100
            except Exception:
                pass
        
        rs_sector_1m = (change_1m_pct - sector_change_1m) if sector_change_1m is not None else None
        rs_sector_1y = (change_1y_pct - sector_change_1y) if sector_change_1y is not None else None

        # Technical indicators
        ma20 = round(float(closes.rolling(20).mean().iloc[-1]), 2) if len(closes) >= 20 else None
        ma50 = round(float(closes.rolling(50).mean().iloc[-1]), 2) if len(closes) >= 50 else None
        ma200 = round(float(closes.rolling(200).mean().iloc[-1]), 2) if len(closes) >= 200 else None

        # Fetch 2 years history to ensure enough data for Monthly RSI (needs at least 15 months)
        hist_2y = ticker.history(period="2y")
        if ma200 is None and not hist_2y.empty:
            ma200 = round(float(hist_2y["Close"].rolling(200).mean().iloc[-1]), 2)
            
        # Calculate Multi-Timeframe RSI
        rsi_daily = calculate_rsi(closes)
        
        rsi_weekly = None
        rsi_monthly = None
        vcp_matched = False
        if not hist_2y.empty:
            # Resample to weekly
            weekly_closes = hist_2y["Close"].resample("W").last().dropna()
            rsi_weekly = calculate_rsi(weekly_closes)
            
            # Resample to monthly
            monthly_closes = hist_2y["Close"].resample("M").last().dropna()
            rsi_monthly = calculate_rsi(monthly_closes)
            
            # VCP Pattern Check
            try:
                vcp_df = filter_by_vcp_conditions(hist_2y.copy())
                if 'Has_fulfilled' in vcp_df.columns and bool(vcp_df['Has_fulfilled'].iloc[-1]):
                    vcp_matched = True
            except Exception:
                pass

        macd_val, macd_signal = calculate_macd(closes)
        
        # All Time High / Low
        try:
            hist_max = ticker.history(period="max")
            all_time_high = round(float(hist_max["High"].max()), 2) if not hist_max.empty else None
            all_time_low = round(float(hist_max["Low"].min()), 2) if not hist_max.empty else None
        except Exception:
            all_time_high = None
            all_time_low = None

        # Pivot Points (Support/Resistance based on previous day's high/low/close)
        if len(hist) > 1:
            prev_day_high = hist["High"].iloc[-2]
            prev_day_low = hist["Low"].iloc[-2]
            prev_day_close = hist["Close"].iloc[-2]
        else:
            prev_day_high = hist["High"].iloc[-1]
            prev_day_low = hist["Low"].iloc[-1]
            prev_day_close = hist["Close"].iloc[-1]

        pivot_p = (prev_day_high + prev_day_low + prev_day_close) / 3
        pivot_r1 = (2 * pivot_p) - prev_day_low
        pivot_s1 = (2 * pivot_p) - prev_day_high
        pivot_r2 = pivot_p + (prev_day_high - prev_day_low)
        pivot_s2 = pivot_p - (prev_day_high - prev_day_low)
        pivot_r3 = prev_day_high + 2 * (pivot_p - prev_day_low)
        pivot_s3 = prev_day_low - 2 * (prev_day_high - pivot_p)

        # Volume Trend Analysis
        vol_mean = hist["Volume"].mean()
        avg_vol_20 = int(hist["Volume"].rolling(20).mean().iloc[-1]) if len(hist) >= 20 and not np.isnan(hist["Volume"].rolling(20).mean().iloc[-1]) else (int(vol_mean) if not np.isnan(vol_mean) else 0)
        current_vol = int(hist["Volume"].iloc[-1]) if not np.isnan(hist["Volume"].iloc[-1]) else 0

        vol_trend = "Neutral"
        if current_price >= prev_close: # Up day
            if current_vol > avg_vol_20 * 1.5:
                vol_trend = "Strong Buying (Accumulation)"
            elif current_vol > avg_vol_20:
                vol_trend = "Buying Pressure"
            else:
                vol_trend = "Light Buying"
        # Option Chain Analysis (Smart Money positioning) via Angel One
        options_data = {"current": None, "next": None}
        try:
            import sys
            import os
            sys.path.append(os.path.dirname(__file__))
            from angel_options import get_angel_option_chain
            options_data = get_angel_option_chain(symbol, is_index)
        except Exception as e:
            # Option chain might not be available
            logger.error("Option Chain Error for %s: %s", symbol, e)

        # Historical chart data (last 180 days for the chart)
        chart_hist = hist.iloc[-180:]
        chart_dates = [d.strftime("%Y-%m-%d") for d in chart_hist.index]
        chart_closes = [round(float(v), 2) for v in chart_hist["Close"]]
        chart_volumes = [int(v) if not np.isnan(v) else 0 for v in chart_hist["Volume"]]

        result = {
            "symbol": symbol,
            "name": safe_get(info, "longName") or safe_get(info, "shortName") or symbol,
            "currency": safe_get(info, "currency", "INR"),
            "exchange": safe_get(info, "exchange", "NSE"),
            "current_price": round(float(current_price), 2),
            "open": round(float(safe_get(info, "open") or hist["Open"].iloc[-1]), 2),
            "previous_close": round(float(prev_close), 2),
            "day_high": round(float(safe_get(info, "dayHigh") or hist["High"].iloc[-1]), 2),
            "day_low": round(float(safe_get(info, "dayLow") or hist["Low"].iloc[-1]), 2),
            "week_52_high": round(float(safe_get(info, "fiftyTwoWeekHigh") or closes.max()), 2),
            "week_52_low": round(float(safe_get(info, "fiftyTwoWeekLow") or closes.min()), 2),
            "all_time_high": all_time_high,
            "all_time_low": all_time_low,
            "vcp_matched": vcp_matched,
            "volume": int(safe_get(info, "volume") or hist["Volume"].iloc[-1] or 0),
            "avg_volume": int(safe_get(info, "averageVolume") or 0),
            "price_change_1d": round(float(change_1d), 2),
            "price_change_1d_pct": round(float(change_1d_pct), 2),
            "price_change_1w_pct": round(float(change_1w_pct), 2),
            "price_change_1m_pct": round(float(change_1m_pct), 2),
            "price_change_1y_pct": round(float(change_1y_pct), 2),
            "sma_20": ma20,
            "sma_50": ma50,
            "sma_200": ma200,
            "rsi_14": rsi_daily,
            "rsi_weekly": rsi_weekly,
            "rsi_monthly": rsi_monthly,
            "macd": macd_val,
            "macd_signal": macd_signal,
            "pivot_points": {
                "r3": round(float(pivot_r3), 2),
                "r2": round(float(pivot_r2), 2),
                "r1": round(float(pivot_r1), 2),
                "pp": round(float(pivot_p), 2),
                "s1": round(float(pivot_s1), 2),
                "s2": round(float(pivot_s2), 2),
                "s3": round(float(pivot_s3), 2),
            },
            "volume_trend": vol_trend,
            "avg_volume_20d": avg_vol_20,
            "relative_strength": {
                "nifty_1m": round(float(rs_nifty_1m), 2) if rs_nifty_1m is not None else None,
                "nifty_1y": round(float(rs_nifty_1y), 2) if rs_nifty_1y is not None else None,
                "sector_index": sector_idx,
                "sector_1m": round(float(rs_sector_1m), 2) if rs_sector_1m is not None else None,
                "sector_1y": round(float(rs_sector_1y), 2) if rs_sector_1y is not None else None,
            },
            "options_data": options_data,
            "historical_prices": {
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
            "error": None,
        }

        # Fundamental data (not available for indices)
        if not is_index:
            # Safely fetch financial statements
            financials = getattr(ticker, "financials", None)
            bs = getattr(ticker, "balance_sheet", None)
            cf = getattr(ticker, "cashflow", None)
            
            # Extract latest year financials if available
            f_revenue = None; f_net_income = None; f_gross_profit = None; f_operating_income = None
            if financials is not None and not financials.empty:
                f_doc = financials.iloc[:, 0]  # Latest column
                f_revenue = safe_get(f_doc, "Total Revenue")
                f_gross_profit = safe_get(f_doc, "Gross Profit")
                f_operating_income = safe_get(f_doc, "Operating Income")
                f_net_income = safe_get(f_doc, "Net Income")

            b_assets = None; b_liabilities = None; b_equity = None; b_debt = None
            if bs is not None and not bs.empty:
                b_doc = bs.iloc[:, 0]
                b_assets = safe_get(b_doc, "Total Assets")
                b_liabilities = (safe_get(b_doc, "Total Liabilities Net Minority Interest") or 
                                safe_get(b_doc, "Total Liabilities"))
                b_equity = (safe_get(b_doc, "Stockholders Equity") or 
                            safe_get(b_doc, "Total Equity Gross Minority Interest"))
                b_debt = safe_get(b_doc, "Total Debt")

            c_operating = None; c_investing = None; c_financing = None; c_fcf = None
            if cf is not None and not cf.empty:
                cf_doc = cf.iloc[:, 0]
                c_operating = safe_get(cf_doc, "Operating Cash Flow")
                c_investing = safe_get(cf_doc, "Investing Cash Flow")
                c_financing = safe_get(cf_doc, "Financing Cash Flow")
                c_fcf = safe_get(cf_doc, "Free Cash Flow")

            # Fallback for ROE if missing in info
            roe = safe_get(info, "returnOnEquity")
            if roe is None and f_net_income and b_equity:
                try:
                    roe = float(f_net_income) / float(b_equity)
                except (ZeroDivisionError, TypeError, ValueError):
                    roe = None

            result.update({
                "market_cap": safe_get(info, "marketCap"),
                "pe_ratio": safe_get(info, "trailingPE"),
                "forward_pe": safe_get(info, "forwardPE"),
                "eps": safe_get(info, "trailingEps"),
                "dividend_yield": safe_get(info, "dividendYield"),
                "beta": safe_get(info, "beta"),
                "book_value": safe_get(info, "bookValue"),
                "price_to_book": safe_get(info, "priceToBook"),
                "roe": roe,
                "debt_to_equity": safe_get(info, "debtToEquity"),
                "sector": safe_get(info, "sector"),
                "industry": safe_get(info, "industry"),
                "summary": safe_get(info, "longBusinessSummary"),
                "employees": safe_get(info, "fullTimeEmployees"),
                "website": safe_get(info, "website"),
                
                # New Income Statement Data
                "financials_revenue": f_revenue,
                "financials_gross_profit": f_gross_profit,
                "financials_operating_income": f_operating_income,
                "financials_net_income": f_net_income,
                
                # New Balance Sheet Data
                "bs_total_assets": b_assets,
                "bs_total_liabilities": b_liabilities,
                "bs_total_equity": b_equity,
                "bs_total_debt": b_debt,
                
                # New Cash Flow Data
                "cf_operating": c_operating,
                "cf_investing": c_investing,
                "cf_financing": c_financing,
                "cf_free_cash_flow": c_fcf,
            })
        else:
            result.update({
                "market_cap": None,
                "pe_ratio": None,
                "forward_pe": None,
                "eps": None,
                "dividend_yield": None,
                "beta": None,
                "book_value": None,
                "price_to_book": None,
                "roe": None,
                "debt_to_equity": None,
                "sector": "Index",
                "industry": "Market Index",
                "summary": f"{result['name']} is a major Indian market index.",
                "employees": None,
                "website": None,
                "financials_revenue": None,
                "financials_gross_profit": None,
                "financials_operating_income": None,
                "financials_net_income": None,
                "bs_total_assets": None,
                "bs_total_liabilities": None,
                "bs_total_equity": None,
                "bs_total_debt": None,
                "cf_operating": None,
                "cf_investing": None,
                "cf_financing": None,
                "cf_free_cash_flow": None,
            })

        return result

    except Exception as e:
        # Log full error server-side; return a sanitized message to avoid
        # leaking internal paths, stack traces, or library internals to callers.
        import logging
        logging.getLogger("analyze_stock").error("Error analyzing %s: %s", symbol, e, exc_info=True)
        return {"error": "Unable to retrieve data for this symbol. It may be delisted, unsupported, or temporarily unavailable.", "symbol": symbol}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze an Indian stock or index.")
    parser.add_argument("--symbol", required=True, help="yfinance ticker symbol (e.g. RELIANCE.NS or ^NSEI)")
    args = parser.parse_args()

    result = analyze(args.symbol)
    print(json.dumps(result, indent=2, default=str))
