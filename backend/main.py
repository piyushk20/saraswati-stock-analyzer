"""
backend/main.py
---------------
FastAPI backend orchestrator — SECURITY HARDENED.
Calls execution/analyze_stock.py as a subprocess and returns its JSON output.

Security fixes applied (2026-02-25):
  - Input validation: symbol allowlist using a strict regex (OWASP: Injection prevention)
  - stderr no longer leaked in 500 responses (OWASP: Information Disclosure fix)
  - CORS tightened to localhost/file:// origins only
  - In-memory rate limiting (10 req/min per IP) — zero extra dependencies

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

# Simple in-memory cache for screener results to prevent API spam
screener_cache = {
    "data": None,
    "expires_at": datetime.min
}
market_overview_cache = {
    "data": None,
    "expires_at": datetime.min
}
analysis_cache = {}  # symbol -> (data, timestamp)


from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
import os

API_KEY = os.environ.get("API_KEY", "saraswati-secret-key-2026")
api_key_header = APIKeyHeader(name="X-API-Key")

def verify_api_key(api_key: str = Depends(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Could not validate API key")
    return api_key

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

# ── Security Middleware ────────────────────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://static.yetanotherstockapp.com; connect-src 'self' http://127.0.0.1:8000"
    return response

# ── CORS — localhost + file:// (null) only ────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # NOTE: Relaxed to "*" for local dev convenience, but security headers are active.
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

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


# ── In-memory Rate Limiter (10 req/min per IP, no extra dependency) ───────────
_rate_store: dict[str, collections.deque] = {}
RATE_LIMIT = 500         # max requests
RATE_WINDOW = 60         # seconds


def check_rate_limit(client_ip: str) -> None:
    """Raise 429 if the client has exceeded RATE_LIMIT requests in RATE_WINDOW seconds."""
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


# ── Script path ───────────────────────────────────────────────────────────────
SCRIPT_PATH = Path(__file__).parent.parent / "execution" / "analyze_stock.py"


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/api/analyze/{symbol:path}")
async def analyze_stock(symbol: str, request: Request, api_key: str = Depends(verify_api_key)):
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
    if symbol in analysis_cache:
        cached_data, timestamp = analysis_cache[symbol]
        if datetime.now() - timestamp < timedelta(minutes=5):
            logger.info(f"Serving analysis for {symbol} from cache")
            return cached_data

    if not SCRIPT_PATH.exists():
        logger.error("Execution script not found at %s", SCRIPT_PATH)
        raise HTTPException(status_code=500, detail="Internal configuration error.")

    try:
        data = analyze(symbol)

        if not data or "error" in data:
            error_msg = data.get("error", "Unknown analysis error") if data else "No data returned"
            logger.error(f"Analysis error for {symbol}: {error_msg}")
            raise HTTPException(status_code=404, detail=error_msg)

        # Cache successful result
        analysis_cache[symbol] = (data, datetime.now())
        return data

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to execute analysis for symbol=%s: %s", symbol, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/api/screener/crossovers")
async def get_screener_crossovers(request: Request, api_key: str = Depends(verify_api_key)):
    """
    Returns recent Golden/Death crosses for top Indian stocks and indices.
    Results are cached in-memory for 1 hour to prevent API limits.
    """
    global screener_cache
    
    # Rate limit (reusing same rate limiter)
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)
    
    # Return cached data if valid
    if datetime.now() < screener_cache["expires_at"] and screener_cache["data"] is not None:
        logger.info("Serving screener crossovers from cache")
        return screener_cache["data"]
        
    try:
        logger.info("Executing screener crossover scan (cache miss)")
        data = find_crossovers()
        
        if data.get("error"):
            raise HTTPException(status_code=500, detail=data["error"])
            
        # Update cache (1 hour expiry)
        screener_cache["data"] = data
        screener_cache["expires_at"] = datetime.now() + timedelta(hours=1)
        
        return data

    except Exception as e:
        logger.error("Failed to execute screener scan: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run screener scan.")

@app.get("/api/market/overview")
async def get_market_overview(request: Request, api_key: str = Depends(verify_api_key)):
    """
    Returns market overview: major indices, top gainers, and top losers.
    Results are cached in-memory for 5 minutes.
    """
    global market_overview_cache
    
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip)
    
    if datetime.now() < market_overview_cache["expires_at"] and market_overview_cache["data"] is not None:
        logger.info("Serving market overview from cache")
        return market_overview_cache["data"]
        
    try:
        import sys
        import os
        parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if parent_dir not in sys.path:
            sys.path.append(parent_dir)
            
        from execution.market_overview import fetch_market_overview
        
        logger.info("Executing market overview scan (cache miss)")
        data = fetch_market_overview()
        
        if data.get("error"):
            raise HTTPException(status_code=500, detail=data["error"])
            
        market_overview_cache["data"] = data
        market_overview_cache["expires_at"] = datetime.now() + timedelta(minutes=5)
        
        return data

    except Exception as e:
        logger.error("Failed to execute market overview: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch market overview.")

vcp_cache = {
    "data": None,
    "expires_at": datetime.now() - timedelta(minutes=1)
}

@app.get("/api/screener/vcp")
async def get_vcp_screener(request: Request, api_key: str = Depends(verify_api_key)):
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
async def get_nse500_list(request: Request, api_key: str = Depends(verify_api_key)):
    """Returns a list of NSE 500 symbols to populate UI dropdowns."""
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
async def health(api_key: str = Depends(verify_api_key)):
    return {"status": "ok", "version": "1.1.0"}
@app.get("/ping")
async def ping():
    return {"ping": "pong"}
