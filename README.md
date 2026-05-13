# 📈 Saraswati Stock Analyzer

**A robust, high-performance Indian market intelligence platform built with FastAPI and yfinance.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 🚀 Key Features

| Feature | Description |
| :--- | :--- |
| **📊 Advanced Charts** | Candlestick charts with EMA (20, 50, 200) and Volume SMA overlays. |
| **⚡ RSI Momentum** | Multi-timeframe (Daily, Weekly, Monthly) RSI screener. |
| **🔥 Episodic Pivot (EP)** | Signal burst detection based on gap-ups and high relative volume. |
| **📐 VCP Pattern** | Minervini-style Volatility Contraction Pattern identification. |
| **📡 SMA Crossovers** | Real-time Golden/Death cross detection in the last 7 days. |
| **🏢 Fundamentals** | P/E, EPS, Market Cap, Debt/Equity, and Business Summaries. |
| **📈 Market Heatmap** | Dynamic Nifty 50 overview with top gainers and losers. |

---

## 🏗️ Architecture

```text
indianstock/
├── backend/
│   ├── main.py              # FastAPI server (Ports: 8001)
│   └── requirements.txt     # Backend dependencies
├── execution/               # Optimized analysis engines
│   ├── analyze_stock.py     # Core logic (TA, RSI, MACD, Pivot Points)
│   ├── rsi_screener.py      # Momentum scanning
│   ├── ep_screener.py       # Episodic Pivot burst detection
│   ├── vcp_screener.py      # Trend Template & VCP logic
│   ├── screener.py          # SMA crossover detection
│   └── market_overview.py   # Global market performance fetcher
├── frontend/                # Glassmorphism Dashboard (Ports: 8081)
│   ├── index.html           # UI shell
│   ├── app.js               # Logic & asynchronous data fetching
│   └── style.css            # Modern dark-mode styling
├── .env                     # Backend API Key (sk_saraswati_...)
└── ind_nifty500list.csv     # Nifty 500 reference universe
```

---

## 🛠️ Quickstart

### 1. Environment Setup
```powershell
# Copy templates
cp .env.example .env
cp frontend/config.example.js frontend/config.js

# Note: Ensure API_KEY in both files matches and starts with 'sk_saraswati_'
```

### 2. Launch Backend (Port 8001)
```powershell
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8001
```

### 3. Launch Frontend (Port 8081)
```powershell
cd frontend
python -m http.server 8081
```

Access the dashboard at **[http://localhost:8081](http://localhost:8081)**.

---

## 🛡️ Stability & Performance
- **Threaded Execution**: All screeners use `ThreadPoolExecutor` for parallel `yfinance` fetches.
- **Robust Parsing**: Advanced error handling for delisted tickers and data gaps.
- **Cache-First**: Intelligent in-memory caching for API responses to respect rate limits.

---

## 📝 TODO

- [ ] Implement user-defined screening criteria in the UI.
- [ ] Add Telegram/Slack alerts for identified setups.
- [ ] Integrate real-time option chain Greeks (Delta/Theta).
- [ ] Add "Export to CSV" for all screener results.

---

## ⚖️ License
[MIT](https://opensource.org/licenses/MIT) © 2026 Piyush K
