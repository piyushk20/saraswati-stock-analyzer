from curl_cffi import requests as cffi_requests
import yfinance as yf
import time
import logging
import urllib.parse

logger = logging.getLogger(__name__)

_yf_session = None

def get_yf_session():
    """
    Constructs and returns a shared curl_cffi requests Session configured with chrome impersonation.
    This mimics a real browser request, preventing Yahoo Finance from rate-limiting
    our concurrent scanner runs.
    """
    global _yf_session
    if _yf_session is None:
        _yf_session = cffi_requests.Session(impersonate="chrome")
    return _yf_session


def _parse_chart_response(data, symbol):
    """Parse a Yahoo Finance v8 chart JSON response into a DataFrame. Returns None on failure."""
    import pandas as pd
    from datetime import datetime
    try:
        if "chart" in data and data["chart"]["result"]:
            result = data["chart"]["result"][0]
            if "timestamp" in result:
                timestamps = result["timestamp"]
                dates = [datetime.fromtimestamp(ts) for ts in timestamps]
                quote = result["indicators"]["quote"][0]

                adjclose = None
                if "adjclose" in result["indicators"]:
                    adjclose = result["indicators"]["adjclose"][0].get("adjclose")

                df = pd.DataFrame({
                    "Open": quote.get("open"),
                    "High": quote.get("high"),
                    "Low": quote.get("low"),
                    "Close": adjclose if adjclose is not None else quote.get("close"),
                    "Volume": quote.get("volume")
                }, index=pd.DatetimeIndex(dates))

                df = df.dropna(subset=["Close"])
                df.index.name = "Date"
                if not df.empty:
                    return df
    except Exception as e:
        logger.debug(f"Chart parse error for {symbol}: {e}")
    return None


class PatchedFastInfo:
    def __init__(self, symbol):
        self.symbol = symbol
        self._price = None
        self._prev = None
        self._high = None
        self._low = None
        self._fetched = False

    def _fetch(self):
        if self._fetched:
            return
        try:
            session = get_yf_session()
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(self.symbol)}"
            params = {"range": "1d", "interval": "1m"}
            r = session.get(url, params=params, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if "chart" in data and data["chart"]["result"]:
                    meta = data["chart"]["result"][0]["meta"]
                    self._price = meta.get("regularMarketPrice")
                    self._prev = meta.get("previousClose")
                    self._high = meta.get("regularMarketDayHigh") or self._price
                    self._low = meta.get("regularMarketDayLow") or self._price
        except Exception:
            pass
        self._fetched = True

    @property
    def last_price(self):
        self._fetch()
        return self._price

    @property
    def previous_close(self):
        self._fetch()
        return self._prev

    @property
    def day_high(self):
        self._fetch()
        return self._high

    @property
    def day_low(self):
        self._fetch()
        return self._low


def get_quote_summary_safe(symbol):
    """
    Fetches the full quote summary (equivalent to ticker.info) via direct Yahoo Finance API,
    using the curl_cffi Chrome-impersonating session to avoid rate limits.
    Returns a dict with standard yfinance .info keys on success, or {} on failure.
    """
    session = get_yf_session()
    modules = "price,summaryProfile,financialData,defaultKeyStatistics,assetProfile,earnings"
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(symbol)}"
    params = {"modules": modules}
    try:
        r = session.get(url, params=params, timeout=10)
        if r.status_code != 200:
            logger.warning(f"quoteSummary HTTP {r.status_code} for {symbol}")
            return {}
        data = r.json()
        qs = data.get("quoteSummary", {})
        if qs.get("error"):
            logger.warning(f"quoteSummary API error for {symbol}: {qs['error']}")
            return {}
        result = qs.get("result") or []
        if not result:
            return {}

        info = {}
        r0 = result[0]

        # price module → maps to standard yfinance .info keys
        price = r0.get("price", {})
        info["longName"]               = price.get("longName")
        info["shortName"]              = price.get("shortName")
        info["regularMarketPrice"]     = price.get("regularMarketPrice", {}).get("raw")
        info["regularMarketDayHigh"]   = price.get("regularMarketDayHigh", {}).get("raw")
        info["regularMarketDayLow"]    = price.get("regularMarketDayLow", {}).get("raw")
        info["regularMarketVolume"]    = price.get("regularMarketVolume", {}).get("raw")
        info["previousClose"]          = price.get("regularMarketPreviousClose", {}).get("raw")
        info["marketCap"]              = price.get("marketCap", {}).get("raw")
        info["quoteType"]              = price.get("quoteType")

        # defaultKeyStatistics module
        dks = r0.get("defaultKeyStatistics", {})
        info["trailingEps"]            = dks.get("trailingEps", {}).get("raw")
        info["forwardEps"]             = dks.get("forwardEps", {}).get("raw")
        info["bookValue"]              = dks.get("bookValue", {}).get("raw")
        info["fiftyTwoWeekHigh"]       = dks.get("52WeekChange", {}).get("raw")  # fallback below
        info["earningsGrowth"]         = dks.get("earningsGrowth", {}).get("raw")
        info["earningsQuarterlyGrowth"]= dks.get("earningsQuarterlyGrowth", {}).get("raw")
        info["revenueGrowth"]          = dks.get("revenueGrowth", {}).get("raw")

        # financialData module
        fd = r0.get("financialData", {})
        info["currentPrice"]           = fd.get("currentPrice", {}).get("raw")
        info["returnOnEquity"]         = fd.get("returnOnEquity", {}).get("raw")
        info["debtToEquity"]           = fd.get("debtToEquity", {}).get("raw")
        info["revenueGrowth"]          = fd.get("revenueGrowth", {}).get("raw") or info.get("revenueGrowth")
        info["earningsGrowth"]         = fd.get("earningsGrowth", {}).get("raw") or info.get("earningsGrowth")
        info["dividendYield"]          = fd.get("dividendYield", {}).get("raw")

        # summaryProfile module
        sp = r0.get("summaryProfile", {})
        info["sector"]                 = sp.get("sector")
        info["industry"]               = sp.get("industry")
        info["longBusinessSummary"]    = sp.get("longBusinessSummary")

        # assetProfile module (overlaps with summaryProfile)
        ap = r0.get("assetProfile", {})
        info["sector"]                 = info.get("sector") or ap.get("sector")
        info["industry"]               = info.get("industry") or ap.get("industry")
        info["longBusinessSummary"]    = info.get("longBusinessSummary") or ap.get("longBusinessSummary")

        # Fetch fiftyTwoWeekHigh/Low from chart meta (already available via v8)
        try:
            chart_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
            cr = session.get(chart_url, params={"range": "1d", "interval": "1d"}, timeout=5)
            if cr.status_code == 200:
                cd = cr.json()
                if cd.get("chart", {}).get("result"):
                    meta = cd["chart"]["result"][0]["meta"]
                    info["fiftyTwoWeekHigh"] = meta.get("fiftyTwoWeekHigh")
                    info["fiftyTwoWeekLow"]  = meta.get("fiftyTwoWeekLow")
                    info["regularMarketPrice"]   = info.get("regularMarketPrice") or meta.get("regularMarketPrice")
                    info["previousClose"]        = info.get("previousClose") or meta.get("previousClose")
                    info["regularMarketDayHigh"] = info.get("regularMarketDayHigh") or meta.get("regularMarketDayHigh")
                    info["regularMarketDayLow"]  = info.get("regularMarketDayLow") or meta.get("regularMarketDayLow")
                    info["regularMarketVolume"]  = info.get("regularMarketVolume") or meta.get("regularMarketVolume")
        except Exception:
            pass

        # Derive trailingPE / forwardPE from price data
        price_val = info.get("regularMarketPrice") or info.get("currentPrice")
        eps = info.get("trailingEps")
        fwd_eps = info.get("forwardEps")
        if price_val and eps and eps != 0:
            info["trailingPE"] = round(price_val / eps, 4)
        if price_val and fwd_eps and fwd_eps != 0:
            info["forwardPE"] = round(price_val / fwd_eps, 4)
        if price_val and info.get("bookValue") and info["bookValue"] != 0:
            info["priceToBook"] = round(price_val / info["bookValue"], 4)

        logger.debug(f"✅ quoteSummary fetched successfully for {symbol} via Direct API.")
        return info

    except Exception as e:
        logger.warning(f"⚠️ get_quote_summary_safe failed for {symbol}: {e}")
        return {}


def get_ticker(symbol) -> yf.Ticker:
    """
    Returns a yfinance Ticker instance with its history method and fast_info patched to use
    our premium Direct Chart API strategy as the primary fast bypass.
    """
    ticker = yf.Ticker(symbol, session=get_yf_session())

    # Dynamically subclass to override the read-only fast_info property descriptor
    class PatchedTicker(yf.Ticker):
        @property
        def fast_info(self):
            return PatchedFastInfo(symbol)

    ticker.__class__ = PatchedTicker

    # Save original history method
    orig_history = ticker.history

    def patched_history(self, period="5y", *args, **kwargs):
        # We can extract the period from kwargs if passed as a keyword
        if "period" in kwargs:
            period = kwargs["period"]

        try:
            session = get_yf_session()
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
            params = {"range": period, "interval": "1d"}
            r = session.get(url, params=params, timeout=10)
            if r.status_code == 200:
                df = _parse_chart_response(r.json(), symbol)
                if df is not None:
                    return df
        except Exception as e:
            logger.debug(f"Patched history direct chart fetch failed for {symbol}: {e}")

        # Fall back to original history method
        return orig_history(period=period, *args, **kwargs)

    import types
    ticker.history = types.MethodType(patched_history, ticker)
    return ticker


def get_historical_data_safe(symbol, period="5y", max_retries=3, backoff_factor=1.5):
    """
    Fetches historical data with direct Yahoo Finance chart API fallback and exponential backoff retries.
    This serves as an institutional-grade rate-limit bypass for concurrent broad market scans.
    Returns None on failure; raises YFRateLimitError if all retries exhausted on rate limit.
    """
    import pandas as pd
    from datetime import datetime

    session = get_yf_session()

    # ── Strategy 1: Direct v8 Chart API (Bypasses Cookie/Crumb Rate Limiting) ──
    # Retry up to 2 times on non-200 before giving up on Strategy 1
    for s1_attempt in range(2):
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
            params = {"range": period, "interval": "1d"}
            r = session.get(url, params=params, timeout=10)
            if r.status_code == 200:
                df = _parse_chart_response(r.json(), symbol)
                if df is not None:
                    logger.debug(f"✅ Fetched {symbol} via Direct Chart API (attempt {s1_attempt+1}).")
                    return df
                else:
                    logger.debug(f"Strategy 1 returned empty for {symbol}, trying Strategy 2.")
                    break  # Non-rate-limit issue — go to Strategy 2
            elif r.status_code == 429:
                wait = 2.0 * (s1_attempt + 1)
                logger.warning(f"⚠️ Strategy 1 rate limited for {symbol} (429). Waiting {wait}s before retry...")
                time.sleep(wait)
            else:
                logger.warning(f"⚠️ Strategy 1 HTTP {r.status_code} for {symbol}. Falling back.")
                break
        except Exception as e:
            logger.warning(f"⚠️ Direct Chart API strategy failed for {symbol}: {e}. Falling back to standard yfinance.")
            break

    # ── Strategy 2: Standard yfinance Ticker History (Fallback) ──
    ticker = yf.Ticker(symbol, session=session)
    last_exception = None

    for attempt in range(max_retries):
        try:
            df = ticker.history(period=period)
            if df is not None and not df.empty:
                return df
            logger.warning(f"Empty dataframe returned for {symbol} on attempt {attempt+1}")
        except Exception as e:
            last_exception = e
            err_msg = str(e)
            if "Too Many Requests" in err_msg or "429" in err_msg or "rate limit" in err_msg.lower() or "YFRateLimitError" in type(e).__name__:
                wait_time = (backoff_factor ** attempt) + 1.0
                logger.warning(f"⚠️ yfinance rate limit hit for {symbol}. Retrying in {wait_time:.1f}s... (Attempt {attempt+1}/{max_retries})")
                time.sleep(wait_time)
            else:
                logger.error(f"❌ Error fetching historical data for {symbol}: {e}")
                break
        time.sleep(0.2)

    # If we exhausted retries on rate limit, propagate so backend can return 429
    if last_exception is not None and ("Too Many Requests" in str(last_exception) or "YFRateLimitError" in type(last_exception).__name__):
        raise last_exception

    return None
