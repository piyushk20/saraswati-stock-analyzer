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

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("saraswati")

app = FastAPI(title="Indian Stock Analyzer API", version="1.1.0")

# ── CORS — localhost + file:// (null) only ────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
        "null",          # Browsers send 'null' origin for file:// pages
        "file://"        # Required by some browsers for local file access
    ],
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
RATE_LIMIT = 10          # max requests
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
async def analyze_stock(symbol: str, request: Request):
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

    if not SCRIPT_PATH.exists():
        logger.error("Execution script not found at %s", SCRIPT_PATH)
        raise HTTPException(status_code=500, detail="Internal configuration error.")

    try:
        import sys
        import os
        # Add the parent directory to sys.path so we can import execution
        parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if parent_dir not in sys.path:
            sys.path.append(parent_dir)
            
        from execution.analyze_stock import analyze
        
        data = analyze(symbol)

        if data.get("error"):
            raise HTTPException(status_code=404, detail=data["error"])

        return data

    except Exception as e:
        logger.error("Failed to execute analysis for symbol=%s: %s", symbol, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run analysis.")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.1.0"}
