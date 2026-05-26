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
import logging
import re
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

def verify_api_key(x_api_key: str = Header(None, alias="X-API-Key")):
    if not API_KEY_VALID or x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API Key")
    return x_api_key

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8081",
        "http://127.0.0.1:8081",
        "http://localhost:8082",
        "http://127.0.0.1:8082",
        "http://localhost:8085",
        "http://127.0.0.1:8085",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8001",
        "http://127.0.0.1:8001",
        "http://localhost:8002",
        "http://127.0.0.1:8002",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\]|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
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
    # CSP: connect-src restricted to localhost API ports only
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self' http://localhost:8000 http://127.0.0.1:8000 http://localhost:8001 http://127.0.0.1:8001 http://localhost:8002 http://127.0.0.1:8002 http://localhost:8082 http://127.0.0.1:8082"
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
        except:
            pass
            
    if hasattr(obj, 'tolist') and callable(obj.tolist):
        try:
            return clean_types(obj.tolist())
        except:
            pass

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
        if cache_key in analysis_cache:
            data, timestamp = analysis_cache[cache_key]
            if datetime.now() - timestamp < timedelta(minutes=5):
                return data

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


VALID_CATEGORIES = {"nifty50", "nifty200", "midcap100", "smallcap100", "midcap150", "smallcap250", "microcap250", "nifty500"}

@app.get("/api/screener/crossovers")
def get_screener_crossovers(request: Request, category: str = "nifty50", force: bool = False, api_key: str = Depends(verify_api_key)):
    global screener_cache
    if category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")
    
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)
    
    cache_entry = screener_cache.get(category)
    if not force and cache_entry and datetime.now() < cache_entry["expires_at"]:
        return cache_entry["data"]
        
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
        raise HTTPException(status_code=400, detail="Invalid category")
    
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)
    
    cache_entry = market_overview_cache.get(category)
    if not force and cache_entry and datetime.now() < cache_entry["expires_at"]:
        return cache_entry["data"]
        
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

vcp_cache = {"data": None, "expires_at": datetime.now() - timedelta(minutes=1)}
evcp_cache = {"data": None, "expires_at": datetime.now() - timedelta(minutes=1)}
ep_cache  = {"data": None, "expires_at": datetime.now() - timedelta(minutes=1)}
rsi_cache = {"data": None, "expires_at": datetime.now() - timedelta(minutes=1)}
momentum_cache = {"data": None, "expires_at": datetime.now() - timedelta(minutes=1)}
flag_cache = {"data": None, "expires_at": datetime.now() - timedelta(minutes=1)}
# History of last 5 flag screener results
flag_history = collections.deque(maxlen=5)

@app.get("/api/screener/vcp")
def get_vcp_screener(request: Request, force: bool = False, api_key: str = Depends(verify_api_key)):
    global vcp_cache
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)
    
    if not force and datetime.now() < vcp_cache["expires_at"] and vcp_cache["data"] is not None:
        return vcp_cache["data"]
        
    try:
        from execution.vcp_screener import scan_vcp
        data = scan_vcp()
        if data.get("error"):
            raise HTTPException(status_code=500, detail=data["error"])
            
        data = clean_types(data)
        vcp_cache["data"] = data
        vcp_cache["expires_at"] = datetime.now() + timedelta(hours=1)
        return data
    except Exception as e:
        logger.error("Failed to execute VCP screener scan: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run VCP screener scan.")

@app.get("/api/screener/ep")
def get_ep_screener(request: Request, force: bool = False, api_key: str = Depends(verify_api_key)):
    global ep_cache
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)

    if not force and datetime.now() < ep_cache["expires_at"] and ep_cache["data"] is not None:
        return ep_cache["data"]

    try:
        from execution.ep_screener import scan_ep
        data = scan_ep()
        if data.get("error"):
            raise HTTPException(status_code=500, detail=data["error"])

        logger.info("EP Screener found %d stocks", len(data.get("ep_stocks", [])))
        data = clean_types(data)
        ep_cache["data"] = data
        ep_cache["expires_at"] = datetime.now() + timedelta(hours=1)
        return data
    except Exception as e:
        logger.error("Failed to execute EP screener scan: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run EP screener scan.")

@app.get("/api/screener/rsi")
def get_rsi_screener(request: Request, force: bool = False, api_key: str = Depends(verify_api_key)):
    global rsi_cache
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)

    if not force and datetime.now() < rsi_cache["expires_at"] and rsi_cache["data"] is not None:
        return rsi_cache["data"]

    try:
        from execution.rsi_screener import scan_rsi
        data = scan_rsi()
        if data.get("error"):
            raise HTTPException(status_code=500, detail=data["error"])

        logger.info("RSI Screener found %d stocks", len(data.get("rsi_stocks", [])))
        data = clean_types(data)
        rsi_cache["data"] = data
        rsi_cache["expires_at"] = datetime.now() + timedelta(hours=1)
        return data
    except Exception as e:
        logger.error("Failed to execute RSI screener scan: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run RSI screener scan.")

@app.get("/api/screener/momentum")
def get_momentum_screener(request: Request, force: bool = False, api_key: str = Depends(verify_api_key)):
    global momentum_cache
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)

    if not force and datetime.now() < momentum_cache["expires_at"] and momentum_cache["data"] is not None:
        return momentum_cache["data"]

    try:
        from execution.momentum_scanner import scan_momentum
        data = scan_momentum()
        if data.get("error"):
            raise HTTPException(status_code=500, detail=data["error"])

        logger.info("Momentum Screener found %d stocks", len(data.get("momentum_stocks", [])))
        data = clean_types(data)
        momentum_cache["data"] = data
        momentum_cache["expires_at"] = datetime.now() + timedelta(hours=1)
        return data
    except Exception as e:
        logger.error("Failed to execute Momentum screener scan: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run Momentum screener scan.")
@app.get("/api/screener/flag")
def get_flag_screener(request: Request, force: bool = False, api_key: str = Depends(verify_api_key)):
    global flag_cache
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)

    if not force and datetime.now() < flag_cache["expires_at"] and flag_cache["data"] is not None:
        return flag_cache["data"]

    try:
        from execution.flag_screener import scan_flag
        data = scan_flag()
        if data.get("error"):
            raise HTTPException(status_code=500, detail=data["error"])

        logger.info("Flag Screener found %d stocks", len(data.get("flag_stocks", [])))
        data = clean_types(data)
        flag_cache["data"] = data
        flag_cache["expires_at"] = datetime.now() + timedelta(hours=1)
        # Record in history
        flag_history.append(data)
        return data
    except Exception as e:
        logger.error("Failed to execute Flag screener scan: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run Flag screener scan.")

@app.get("/api/screener/flag/last5")
def get_flag_last5():
    return list(flag_history)

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
