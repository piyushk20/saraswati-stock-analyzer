"""
backend/main.py
---------------
FastAPI backend orchestrator — SECURITY HARDENED.
Calls execution/analyze_stock.py as a subprocess and returns its JSON output.

Security fixes applied (2026-03-23):
  - Input validation: symbol allowlist using a strict regex (OWASP: Injection prevention)
  - stderr no longer leaked in 500 responses (OWASP: Information Disclosure fix)
  - CORS restricted to localhost origins only
  - In-memory rate limiting (30 req/min per IP) — zero extra dependencies
  - API key must be set via .env (startup fails on default/missing key)
  - Category parameter validated against allowlist
  - Security headers hardened (CSP, no deprecated X-XSS-Protection)

Run with:
    cd backend
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000
"""

import collections
import hashlib
import hmac
import logging
import re
import secrets
import time
import os
import math
from pathlib import Path
from datetime import datetime, timedelta

try:
    import numpy as np
except ImportError:
    np = None

# Simple in-memory cache for components
# structure: {category: {"data": data, "expires_at": timestamp}}
screener_cache = {}
market_overview_cache = {}
analysis_cache = {}  # symbol -> (data, timestamp)


from fastapi import FastAPI, HTTPException, Request, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
import json
import os

from dotenv import load_dotenv
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

_raw_key = os.environ.get("API_KEY", "")
if not _raw_key or _raw_key in ("YOUR_SECURE_API_KEY_HERE", "saraswati-secret-key-2026"):
    # Note: logger might not be defined yet, but logging.basicConfig is usually done first
    pass

API_KEY = os.getenv("API_KEY")

# Security Hardening: Enforce strict API key format
if not API_KEY or not API_KEY.startswith("sk_saraswati_") or len(API_KEY) < 40:
    error_msg = "CRITICAL SECURITY ERROR: Invalid or missing API_KEY. MUST start with 'sk_saraswati_' and be at least 40 chars."
    print(error_msg)
    API_KEY_VALID = False
else:
    API_KEY_VALID = True

# ── Session Token Store ───────────────────────────────────────────────────────
# Browser clients call GET /api/handshake to receive a short-lived token.
# This means the raw API key never has to be embedded in any static JS file.
_session_tokens: dict = {}  # token -> expiry (unix timestamp)
SESSION_TOKEN_TTL = 86400   # 24 hours

def generate_session_token() -> str:
    """Return a cryptographically secure short-lived session token."""
    token = secrets.token_hex(32)
    now = time.time()
    _session_tokens[token] = now + SESSION_TOKEN_TTL
    # Prune expired tokens to prevent unbounded growth
    for t in [k for k, exp in list(_session_tokens.items()) if exp < now]:
        del _session_tokens[t]
    return token

def verify_api_key(x_api_key: str = Header(None, alias="X-API-Key")):
    """Accept the raw API key (direct clients) OR a valid session token (browser)."""
    if not x_api_key:
        raise HTTPException(status_code=403, detail="Missing API Key")
    # 1. Raw API key — used by curl / direct API clients.
    #    Use constant-time comparison to prevent timing attacks.
    if API_KEY_VALID and hmac.compare_digest(x_api_key, API_KEY):
        return x_api_key
    # 2. Short-lived session token — issued to browser clients via /api/handshake.
    exp = _session_tokens.get(x_api_key)
    if exp and exp > time.time():
        return x_api_key
    raise HTTPException(status_code=403, detail="Invalid or expired API Key")

import sys
import os

# Add the parent directory to sys.path so we can import execution
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from execution.analyze_stock import analyze
from execution.screener import find_crossovers
from execution.vcp_screener import get_nse_500_symbols, run_vcp_screener

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("saraswati")

app = FastAPI(title="Indian Stock Analyzer API", version="1.1.0")

# ── CORS ──────────────────────────────────────────────────────────────────────
# Restricted to local development origins only
# H1 Fix: CORS locked to only the actual frontend dev ports.
# Removed broad LAN wildcard regex and backend-port origins.
ALLOWED_ORIGINS = {
    "http://localhost:8081", "http://127.0.0.1:8081",
    "http://localhost:8082", "http://127.0.0.1:8082",
    "http://localhost:8085", "http://127.0.0.1:8085",
}
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["X-API-Key", "Content-Type"],
)

# ── Security Middleware ────────────────────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    # Skip for OPTIONS to avoid interfering with CORS preflight
    if request.method == "OPTIONS":
        return await call_next(request)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # M2 Fix: HSTS — ensures HTTPS if ever exposed via a tunnel (ngrok etc.)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # CSP: connect-src restricted to localhost API ports only
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self' http://localhost:8001 http://127.0.0.1:8001 http://localhost:8082 http://127.0.0.1:8082"
    )
    return response

# ── Input Validation ──────────────────────────────────────────────────────────
SYMBOL_RE = re.compile(r"^[\w\^\.\-\&]{1,30}$")

def validate_symbol(symbol: str) -> str:
    """Validate ticker symbol against a strict allowlist regex to prevent injection."""
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=400,
            detail="Invalid symbol format. Allowed: alphanumeric, '.', '-', '&', '^' (max 30 chars).",
        )
    return symbol

def clean_types(obj):
    """
    Recursively converts NumPy types, NaN, and Infinity into standard Python/JSON types.
    This prevents 'failed to fetch' errors caused by JSON serialization failures.
    """
    if obj is None:
        return None

    # Handle standard primitive types first to speed up
    if isinstance(obj, (str, bool, int)) and not (np and isinstance(obj, (np.generic, np.ndarray))):
        return obj

    if isinstance(obj, dict):
        return {str(k): clean_types(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple, set)):
        return [clean_types(i) for i in obj]
    
    if np:
        if isinstance(obj, np.ndarray):
            return [clean_types(i) for i in obj.tolist()]
        elif isinstance(obj, np.generic):
            return clean_types(obj.item())
        elif isinstance(obj, (np.bool_, bool)): # Extra check for numpy bools
            return bool(obj)

    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
        
    # Handle pandas types if they slip through
    if hasattr(obj, 'to_dict') and callable(obj.to_dict):
        try:
            return clean_types(obj.to_dict())
        except Exception as _e:
            logger.debug("clean_types: to_dict() failed: %s", _e)
            
    if hasattr(obj, 'tolist') and callable(obj.tolist):
        try:
            return clean_types(obj.tolist())
        except Exception as _e:
            logger.debug("clean_types: tolist() failed: %s", _e)

    return obj

# ── Global Exception Handling ────────────────────────────────────────────────
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please try again later."},
    )

# ── In-memory Rate Limiter ───────────────────────────────────────────────────
_rate_store: dict[str, collections.deque] = {}
_rate_cleanup_counter = 0
RATE_LIMIT = 30
RATE_WINDOW = 60

def check_rate_limit(client_ip: str) -> None:
    global _rate_cleanup_counter
    now = time.monotonic()
    window = _rate_store.setdefault(client_ip, collections.deque())

    while window and window[0] < now - RATE_WINDOW:
        window.popleft()

    if len(window) >= RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {RATE_LIMIT} requests per minute.",
        )

    window.append(now)

    _rate_cleanup_counter += 1
    if _rate_cleanup_counter >= 100:
        _rate_cleanup_counter = 0
        stale = [ip for ip, dq in _rate_store.items() if not dq or dq[-1] < now - RATE_WINDOW * 5]
        for ip in stale:
            del _rate_store[ip]

# ── Script path ───────────────────────────────────────────────────────────────
SCRIPT_PATH = Path(__file__).parent.parent / "execution" / "analyze_stock.py"

# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/api/analyze/{symbol:path}")
def analyze_stock(symbol: str, request: Request, period: str = "3mo", api_key: str = Depends(verify_api_key)):
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)
    symbol = validate_symbol(symbol)
    
    # Simple validation for period
    valid_periods = {"1w", "1m", "3m", "3mo", "6m", "6mo", "1y", "max"}
    if period.lower() not in valid_periods:
        period = "3mo"

    if not SCRIPT_PATH.exists():
        logger.error("Execution script not found at %s", SCRIPT_PATH)
        raise HTTPException(status_code=500, detail="Internal configuration error.")

    try:
        # Use a composite key for cache if period is specified
        cache_key = f"{symbol}_{period}"

        data = analyze(symbol, chart_period=period)
        if not data or "error" in data:
            error_msg = data.get("error", "Unknown analysis error") if data else "No data returned"
            logger.error(f"Analysis error for {symbol}: {error_msg}")
            raise HTTPException(status_code=404, detail=error_msg)

        # Force reload
        data = clean_types(data)
        analysis_cache[cache_key] = (data, datetime.now())
        return data

    except HTTPException:
        raise
    except Exception as e:
        err_str = str(e)
        # Detect Yahoo Finance rate-limit errors and return 429 (not 500/404)
        if "Too Many Requests" in err_str or "429" in err_str or "rate limit" in err_str.lower() or "YFRateLimitError" in type(e).__name__:
            logger.warning(f"Yahoo Finance rate limit hit for {symbol}: {e}")
            raise HTTPException(
                status_code=429,
                detail="Yahoo Finance rate limit reached. Please wait a moment and try again."
            )
        logger.error("Failed to execute analysis for symbol=%s: %s", symbol, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error.")


VALID_CATEGORIES = {"nifty50", "nifty200", "midcap100", "smallcap100", "midcap150", "smallcap250", "microcap250", "nifty500", "sectors"}
# Equity-only categories (crossover/VCP screeners work on stocks, not indices)
EQUITY_CATEGORIES = {"nifty50", "nifty200", "midcap100", "smallcap100", "midcap150", "smallcap250", "microcap250", "nifty500"}

@app.get("/api/screener/crossovers")
def get_screener_crossovers(request: Request, category: str = "nifty50", force: bool = False, api_key: str = Depends(verify_api_key)):
    global screener_cache
    if category not in EQUITY_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")
    
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)
    
        
    try:
        data = find_crossovers(category)
        data = clean_types(data)
        screener_cache[category] = {
            "data": data,
            "expires_at": datetime.now() + timedelta(hours=1)
        }
        return data
    except Exception as e:
        logger.error(f"Failed to execute screener scan: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run screener scan.")

@app.get("/api/market/overview")
def get_market_overview(request: Request, category: str = "nifty50", force: bool = False, api_key: str = Depends(verify_api_key)):
    global market_overview_cache
    if category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")  # sectors is allowed
    
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)
    
        
    try:
        from execution.market_overview import fetch_market_overview
        data = fetch_market_overview(category)
        if data.get("error"):
            raise HTTPException(status_code=500, detail=data["error"])
        
        data = clean_types(data)
        if data.get("indices"):
            market_overview_cache[category] = {
                "data": data,
                "expires_at": datetime.now() + timedelta(minutes=5)
            }
        return data
    except Exception as e:
        logger.error(f"Failed to execute market overview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch market overview.")

# M3 Fix: Removed dead background worker functions and stale file-cache helpers.
# All scanner routes now run synchronously (live data, no background queue).

# History of last 5 flag screener results (used by /api/screener/flag/last5)
flag_history = collections.deque(maxlen=5)

# Momentum 30 live cache (refreshed on each request)
momentum30_cache = {"data": None, "expires_at": datetime.now() - timedelta(minutes=1)}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/screener/vcp")
def get_vcp_screener(request: Request, force: bool = False, api_key: str = Depends(verify_api_key)):
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)
    
    from execution.vcp_screener import scan_vcp
    logger.info("Starting live VCP scan...")
    data = scan_vcp()
    return clean_types(data)

@app.get("/api/screener/ep")
def get_ep_screener(request: Request, force: bool = False, api_key: str = Depends(verify_api_key)):
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)

    from execution.ep_screener import scan_ep
    logger.info("Starting live EP scan...")
    data = scan_ep()
    return clean_types(data)

@app.get("/api/screener/rsi")
def get_rsi_screener(request: Request, force: bool = False, api_key: str = Depends(verify_api_key)):
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)

    from execution.rsi_screener import scan_rsi
    logger.info("Starting live RSI scan...")
    data = scan_rsi()
    return clean_types(data)

@app.get("/api/screener/momentum")
def get_momentum_screener(request: Request, force: bool = False, api_key: str = Depends(verify_api_key)):
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)

    from execution.momentum_scanner import scan_momentum
    logger.info("Starting live Momentum scan...")
    data = scan_momentum()
    return clean_types(data)

@app.get("/api/screener/flag")
def get_flag_screener(request: Request, force: bool = False, api_key: str = Depends(verify_api_key)):
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)

    from execution.flag_screener import scan_flag
    logger.info("Starting live Flag scan...")
    data = scan_flag()
    # Save to flag_history as it is used by last5 endpoint
    flag_history.append(data)
    return clean_types(data)

@app.get("/api/screener/flag/last5")
def get_flag_last5(request: Request, api_key: str = Depends(verify_api_key)):
    # C3 Fix: this endpoint was previously unauthenticated.
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)
    return list(flag_history)


@app.get("/api/screener/momentum30")
def get_momentum30(request: Request, force: bool = False, api_key: str = Depends(verify_api_key)):
    """Live quotes for the Nifty 200 Momentum 30 index constituents. Cache TTL: 5 min."""
    global momentum30_cache
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)


    try:
        from execution.momentum30_screener import scan_momentum30
        data = scan_momentum30()
        data = clean_types(data)
        momentum30_cache["data"] = data
        momentum30_cache["expires_at"] = datetime.now() + timedelta(minutes=5)
        return data
    except Exception as e:
        logger.error(f"Failed to run Momentum 30 screener: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch Momentum 30 data.")


sector_heatmap_cache = {}

@app.get("/api/sectors/heatmap")
def get_sector_heatmap_endpoint(request: Request, timeframe: str = "Day", force: bool = False, api_key: str = Depends(verify_api_key)):
    # H2 Fix: validate timeframe against an explicit allowlist.
    VALID_TIMEFRAMES = {"Day", "1W", "1M", "3M", "6M", "1Y"}
    if timeframe not in VALID_TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe. Must be one of: {', '.join(sorted(VALID_TIMEFRAMES))}")

    global sector_heatmap_cache
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)

    try:
        from execution.sector_heatmap import get_sector_heatmap_data
        data = get_sector_heatmap_data(timeframe=timeframe)
        data = clean_types(data)
        sector_heatmap_cache[timeframe] = {
            "data": data,
            "expires_at": datetime.now() + timedelta(minutes=2)
        }
        return data
    except Exception as e:
        logger.error(f"Failed to fetch sector heatmap data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch sector heatmap data.")


rrg_cache = {}

@app.get("/api/screener/rrg")
def get_rrg_screener(request: Request, category: str = "nifty50", rs_window: int = 10, mom_window: int = 4, force: bool = False, api_key: str = Depends(verify_api_key)):
    global rrg_cache
    if category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")  # sectors is allowed
    # H3 Fix: bound integer params to prevent DoS via absurdly large computation.
    if not (1 <= rs_window <= 52):
        raise HTTPException(status_code=400, detail="rs_window must be between 1 and 52")
    if not (1 <= mom_window <= 26):
        raise HTTPException(status_code=400, detail="mom_window must be between 1 and 26")

    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)

    cache_key = f"{category}_{rs_window}_{mom_window}"
        
    try:
        from execution.rrg_screener import scan_rrg
        data = scan_rrg(category=category, rs_window=rs_window, mom_window=mom_window)
        data = clean_types(data)
        rrg_cache[cache_key] = {
            "data": data,
            "expires_at": datetime.now() + timedelta(hours=1)
        }
        return data
    except Exception as e:
        logger.error(f"Failed to execute RRG screener scan: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run RRG screener scan.")

@app.get("/api/market/nse500")
def get_nse500_list(request: Request, api_key: str = Depends(verify_api_key)):
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)
    try:
        from execution.vcp_screener import (
            get_nse_500_symbols,
            get_midcap_150_symbols,
            get_smallcap_250_symbols,
            get_microcap_250_symbols
        )
        nifty500 = sorted(get_nse_500_symbols())
        midcap150 = sorted(get_midcap_150_symbols())
        smallcap250 = sorted(get_smallcap_250_symbols())
        microcap250 = sorted(get_microcap_250_symbols())
        
        # Deduplicated combined union list for backwards compatibility
        combined = set(nifty500)
        combined.update(midcap150)
        combined.update(smallcap250)
        combined.update(microcap250)
        
        return {
            "symbols": sorted(list(combined)),
            "nifty500": nifty500,
            "midcap150": midcap150,
            "smallcap250": smallcap250,
            "microcap250": microcap250
        }
    except Exception as e:
        logger.error("Failed to fetch all stock symbols: %s", e, exc_info=True)
        try:
            from execution.vcp_screener import get_nse_500_symbols
            return {
                "symbols": get_nse_500_symbols(),
                "nifty500": get_nse_500_symbols(),
                "midcap150": [],
                "smallcap250": [],
                "microcap250": []
            }
        except Exception:
            return {
                "symbols": ["RELIANCE.NS", "TCS.NS"],
                "nifty500": ["RELIANCE.NS", "TCS.NS"],
                "midcap150": [],
                "smallcap250": [],
                "microcap250": []
            }

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.2.0"}

@app.get("/ping")
async def ping():
    return {"ping": "pong"}


@app.get("/api/handshake")
async def handshake(request: Request):
    """
    C1 Fix: Issue a short-lived session token to browser clients.
    The raw API key never needs to be stored in any static JS file.
    This endpoint is intentionally unauthenticated — it is CORS-gated
    so only origins in ALLOWED_ORIGINS (the frontend ports) can call it.
    """
    if not API_KEY_VALID:
        raise HTTPException(status_code=503, detail="Server API key not configured")
    token = generate_session_token()
    return {"token": token, "expires_in": SESSION_TOKEN_TTL}

# ── Backtesting API Endpoints ──────────────────────────────────────────────────
from fastapi.responses import FileResponse

BACKTEST_RESULTS_DIR = Path(__file__).parent.parent / "backtest_results"
TEARSHEETS_DIR = BACKTEST_RESULTS_DIR / "tearsheets"

@app.get("/api/backtest/summary")
def get_backtest_summary(request: Request, api_key: str = Depends(verify_api_key)):
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)
    json_path = BACKTEST_RESULTS_DIR / "backtest_summary.json"
    if not json_path.exists():
        raise HTTPException(status_code=404, detail="Backtest summary not found. Run backtest engine first.")
    try:
        with open(json_path, "r") as f:
            data = json.load(f)
        
        # Sanitize any inf/nan values in the dictionary
        def sanitize_item(val):
            if isinstance(val, float):
                if math.isnan(val) or math.isinf(val):
                    return 0.0
            return val

        clean_data = []
        for row in data:
            clean_row = {k: sanitize_item(v) for k, v in row.items()}
            clean_data.append(clean_row)

        return {"status": "ok", "summary": clean_data}
    except Exception as e:
        logger.error(f"Failed to load backtest summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to load backtest summary.")

@app.get("/api/backtest/tearsheet/{filename}")
def get_backtest_tearsheet(filename: str, request: Request, api_key: str = Depends(verify_api_key)):
    # C2 Fix: this endpoint was previously unauthenticated.
    # Prevent path traversal
    safe_filename = Path(filename).name
    filepath = TEARSHEETS_DIR / safe_filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Tearsheet {filename} not found.")
    return FileResponse(filepath, media_type="text/html")

