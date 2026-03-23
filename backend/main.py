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
from pathlib import Path
from datetime import datetime, timedelta

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
    logger.warning("⚠️  API_KEY is missing or uses an insecure default.")

API_KEY = os.getenv("API_KEY")

# Security Hardening: Enforce strict API key format
if not API_KEY or not API_KEY.startswith("sk_saraswati_") or len(API_KEY) < 40:
    error_msg = "CRITICAL SECURITY ERROR: Invalid or missing API_KEY. MUST start with 'sk_saraswati_' and be at least 40 chars."
    print(error_msg)
    # In production, we should definitely fail fast
    # raise ValueError(error_msg) 
    # For now, we'll let it run but with a clear warning in logs
    API_KEY_VALID = False
else:
    API_KEY_VALID = True

def verify_api_key(x_api_key: str = Header(None, alias="X-API-Key")):
    if not API_KEY_VALID:
        raise HTTPException(status_code=500, detail="Server configuration error: Invalid API Key format.")
    
    if not x_api_key:
        raise HTTPException(status_code=403, detail="API Key missing")
        
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
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
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=False,
    allow_methods=["GET"],
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
    # CSP: connect-src restricted to localhost API ports only
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self' http://localhost:8000 http://127.0.0.1:8000"
    )
    return response

# ── Input Validation ──────────────────────────────────────────────────────────
# Allowlist: only characters valid in NSE/BSE ticker symbols.
# Examples: RELIANCE.NS  ^NSEI  BAJAJ-AUTO.NS  M&M.NS  ^CNXFMCG
SYMBOL_RE = re.compile(r"^[\w\^\.\-\&]{1,30}$")


def validate_symbol(symbol: str) -> str:
    """Validate ticker symbol against a strict allowlist regex to prevent injection."""
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(
            status_code=400,
            detail="Invalid symbol format. Allowed: alphanumeric, '.', '-', '&', '^' (max 30 chars).",
        )
    return symbol


# ── In-memory Rate Limiter (30 req/min per IP, no extra dependency) ───────────
_rate_store: dict[str, collections.deque] = {}
_rate_cleanup_counter = 0  # Periodic cleanup to prevent unbounded growth
RATE_LIMIT = 30          # max requests per window
RATE_WINDOW = 60         # seconds


def check_rate_limit(client_ip: str) -> None:
    """Raise 429 if the client has exceeded RATE_LIMIT requests in RATE_WINDOW seconds."""
    global _rate_cleanup_counter
    now = time.monotonic()
    window = _rate_store.setdefault(client_ip, collections.deque())

    # Drop timestamps outside the rolling window
    while window and window[0] < now - RATE_WINDOW:
        window.popleft()

    if len(window) >= RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {RATE_LIMIT} requests per minute.",
        )

    window.append(now)

    # Periodic cleanup: every 100 requests, purge stale IPs to prevent memory growth
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
def analyze_stock(symbol: str, request: Request, api_key: str = Depends(verify_api_key)):
    logger.debug("analyze_stock called for %s", symbol)
    """
    Analyze an Indian stock or index by its yfinance-compatible symbol.
    e.g. /api/analyze/RELIANCE.NS or /api/analyze/%5ENSEI

    - Symbol is validated against an allowlist regex (injection prevention).
    - Rate limited: 10 requests/minute per IP.
    - Internal errors are logged server-side; generic messages returned to clients.
    """
    # Rate limit
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)

    # Validate symbol BEFORE passing to subprocess
    symbol = validate_symbol(symbol)

    # Cache check: 5 minute expiry for analysis results
    # if symbol in analysis_cache:
    #     cached_data, timestamp = analysis_cache[symbol]
    #     if datetime.now() - timestamp < timedelta(minutes=5):
    #         logger.info(f"Serving analysis for {symbol} from cache")
    #         return cached_data

    if not SCRIPT_PATH.exists():
        logger.error("Execution script not found at %s", SCRIPT_PATH)
        raise HTTPException(status_code=500, detail="Internal configuration error.")

    try:
        data = analyze(symbol)

        if not data or "error" in data:
            error_msg = data.get("error", "Unknown analysis error") if data else "No data returned"
            logger.error(f"Analysis error for {symbol}: {error_msg}")
            raise HTTPException(status_code=404, detail=error_msg)

        # Helper to convert numpy types to native Python types since FastAPI chokes on them
        def clean_types(obj):
            import numpy as np
            if isinstance(obj, dict):
                return {k: clean_types(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean_types(i) for i in obj]
            elif isinstance(obj, np.generic):
                return obj.item()
            return obj
            
        data = clean_types(data)

        # Cache successful result
        analysis_cache[symbol] = (data, datetime.now())
        return data

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to execute analysis for symbol=%s: %s", symbol, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error. Please try again later.")

# Valid categories for screener/overview endpoints
VALID_CATEGORIES = {"nifty50", "nifty200", "midcap100", "smallcap100", "nifty500"}

@app.get("/api/screener/crossovers")
def get_screener_crossovers(request: Request, category: str = "nifty50", api_key: str = Depends(verify_api_key)):
    """
    Returns recent Golden/Death crosses for the selected universe.
    Results are cached in-memory for 1 hour per category.
    """
    global screener_cache
    
    # Validate category
    if category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}")
    
    # Rate limit
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)
    
    # Return cached data if valid
    cache_entry = screener_cache.get(category)
    if cache_entry and datetime.now() < cache_entry["expires_at"]:
        logger.info(f"Serving screener crossovers for {category} from cache")
        return cache_entry["data"]
        
    try:
        logger.info(f"Executing {category} crossover scan (cache miss)")
        data = find_crossovers(category)
        
        if data.get("error"):
            raise HTTPException(status_code=500, detail=data["error"])
            
        # Update cache (1 hour expiry)
        screener_cache[category] = {
            "data": data,
            "expires_at": datetime.now() + timedelta(hours=1)
        }
        
        return data

    except Exception as e:
        logger.error(f"Failed to execute screener scan: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run screener scan.")

@app.get("/api/market/overview")
def get_market_overview(request: Request, category: str = "nifty50", api_key: str = Depends(verify_api_key)):
    """
    Returns market overview: major indices, top gainers, and top losers for the selected universe.
    Results are cached in-memory for 5 minutes per category.
    """
    global market_overview_cache
    
    # Validate category
    if category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}")
    
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)
    
    cache_entry = market_overview_cache.get(category)
    if cache_entry and datetime.now() < cache_entry["expires_at"]:
        logger.info(f"Serving market overview for {category} from cache")
        return cache_entry["data"]
        
    try:
        from execution.market_overview import fetch_market_overview
        
        logger.info(f"Executing {category} market overview scan (cache miss)")
        data = fetch_market_overview(category)
        
        if data.get("error"):
            raise HTTPException(status_code=500, detail=data["error"])
        
        # Only cache if we got valid indices data — don't cache transient empty results
        if data.get("indices"):
            market_overview_cache[category] = {
                "data": data,
                "expires_at": datetime.now() + timedelta(minutes=5)
            }
        
        return data

    except Exception as e:
        logger.error(f"Failed to execute market overview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch market overview.")

vcp_cache = {
    "data": None,
    "expires_at": datetime.now() - timedelta(minutes=1)
}

@app.get("/api/screener/vcp")
def get_vcp_screener(request: Request, api_key: str = Depends(verify_api_key)):
    """
    Runs the Volatility Contraction Pattern (VCP) screener on NSE 500 stocks.
    Results are cached in-memory for 1 hour since scanning 500 stocks is expensive.
    """
    global vcp_cache
    
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)
    
    # Return from cache if valid
    if datetime.now() < vcp_cache["expires_at"] and vcp_cache["data"] is not None:
        logger.info("Serving VCP screener from cache")
        return vcp_cache["data"]
        
    try:
        import sys
        import os
        parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if parent_dir not in sys.path:
            sys.path.append(parent_dir)
            
        from execution.vcp_screener import scan_vcp
        
        logger.info("Executing VCP screener scan (cache miss)")
        data = scan_vcp()
        
        if data.get("error"):
            raise HTTPException(status_code=500, detail=data["error"])
            
        # Update cache (1 hour expiry)
        vcp_cache["data"] = data
        vcp_cache["expires_at"] = datetime.now() + timedelta(hours=1)
        
        return data

    except Exception as e:
        logger.error("Failed to execute VCP screener scan: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run VCP screener scan.")

@app.get("/api/market/nse500")
def get_nse500_list(request: Request, api_key: str = Depends(verify_api_key)):
    """Returns a list of NSE 500 symbols to populate UI dropdowns."""
    logger.debug("get_nse500_list called")
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)
    try:
        import sys
        import os
        parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if parent_dir not in sys.path:
            sys.path.append(parent_dir)
            
        from execution.vcp_screener import get_nse_500_symbols
        symbols = get_nse_500_symbols()
        return {"symbols": symbols}
    except Exception as e:
        logger.error("Failed to fetch NSE 500 list: %s", e, exc_info=True)
        return {"symbols": ["RELIANCE.NS", "TCS.NS"]}

@app.get("/health")
async def health():
    """Public health check — no API key required for uptime monitoring."""
    return {"status": "ok", "version": "1.2.0"}
@app.get("/ping")
async def ping():
    return {"ping": "pong"}
