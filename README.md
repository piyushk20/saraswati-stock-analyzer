# 📈 Saraswati Stock Analyzer — Indian Market Intelligence Platform

**A robust, high-performance Indian market intelligence platform built with FastAPI and yfinance.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 🚀 Key Features & Scanners

| Feature / Scanner | Description & Strict Criteria |
| :--- | :--- |
| **📊 Advanced Charts** | Candlestick charts with EMA (20, 50, 200) and Volume SMA overlays. |
| **🚩 Perfect Flag Pattern** | Stage 2 uptrend, tight pullback (<15% depth), flagpole regression ($R^2 > 0.8$), volume contraction. |
| **⚡ RSI Momentum** | Multi-timeframe momentum: **Monthly RSI > 60**, **Weekly RSI > 60**, and **Daily RSI strictly 55–65**. |
| **🔥 Episodic Pivot (EP)** | Breakout bursts: **Gap-up >= 6.5%**, **Relative Volume >= 2.0x**, Stage 2 SMA filters, 52W proximity >= 70%. |
| **📐 VCP Pattern** | Minervini-style Volatility Contraction Pattern identification with handle contraction **<= 10%**. |
| **📡 SMA Crossovers** | Real-time Golden/Death cross detection strictly in the **last 7 days** across Nifty indices. |
| **🚀 Momentum Screener** | Strict confluence: Price > EMA20, RSI14 > 50, MACD > Signal, Volume > SMA20. |
| **🏢 Fundamentals** | P/E, EPS, Market Cap, Debt/Equity, and Business Summaries. |
| **📈 Market Heatmap** | Dynamic Nifty 50 overview with top gainers and losers. |

---

## 🏗️ Architecture

```text
indianstock/
├── backend/
│   ├── main.py              # FastAPI server (Port: 8001, X-API-Key authenticated)
│   └── requirements.txt     # Backend dependencies
├── execution/               # Optimized analysis engines (MAX_WORKERS=15 throttled)
│   ├── analyze_stock.py     # Core TA, RSI, MACD, Pivot Points
│   ├── rsi_screener.py      # Multi-Timeframe RSI scanner
│   ├── ep_screener.py       # Episodic Pivot burst detection
│   ├── vcp_screener.py      # Minervini VCP & Trend Template
│   ├── momentum_scanner.py  # Confluence momentum scanner
│   ├── flag_screener.py     # Perfect Flag continuation scanner
│   ├── screener.py          # SMA crossover detection
│   └── market_overview.py   # Global market performance fetcher
├── frontend/                # Premium Glassmorphism Dashboard (Port: 8081)
│   ├── index.html           # UI shell
│   ├── app.js               # Sequential scanner orchestration & async charting
│   └── style.css            # Premium dark-mode styling
├── claude-mem/              # Persistent memory & stable states
├── run_app.py               # Automated detached server orchestrator with logging
└── ind_nifty500list.csv     # Nifty 500 reference universe
```

---

## 🛠️ Quickstart

### Automated Orchestration (Recommended)
Launch both backend and frontend servers simultaneously in background detached processes with automatic log redirection (`backend.log` and `frontend.log`):
```powershell
python run_app.py
```
Access the premium dashboard at **[http://localhost:8081](http://localhost:8081)**.

### Manual Launch
If you prefer running servers manually in separate terminal windows:
```powershell
# Terminal 1: Backend
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload

# Terminal 2: Frontend
cd frontend
python -m http.server 8081
```

---

## 🛡️ Stability, Memory & Performance
- **Persistent Stable State**: We maintain rigorous stable state documentation in `claude-mem/stable-state-2026-05-18.md`. Always review this baseline before making architectural changes.
- **Threaded Execution & Throttling**: All screeners use `ThreadPoolExecutor(max_workers=15)` to prevent GIL contention and Windows socket buffer exhaustion (`WSAENOBUFS`).
- **Sequential Frontend Loading**: `app.js` runs background scans sequentially to ensure instantaneous first-page rendering and prevent network bottlenecks.
- **Robust Parsing & Sanitization**: Complete NumPy type sanitization (`int64`, `float64`, `NaN`, `Infinity`) before JSON serialization in FastAPI.

---

## ⚖️ License
[MIT](https://opensource.org/licenses/MIT) © 2026 Piyush K
