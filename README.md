<div align="center">

# 📈 Saraswati Stock Analyzer

**A full-stack Indian equity analysis platform powered by FastAPI + yfinance.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

![Dashboard Preview](screenshots/dashboard.png)

</div>

---

## Overview

Saraswati Stock Analyzer provides **live technical analysis, fundamental data, and momentum screeners** for NSE/BSE-listed stocks and major Indian indices. It uses a **FastAPI** backend to orchestrate analysis scripts and serve a **vanilla JS + Chart.js** frontend dashboard.

### Features

| Feature                | Description                                                 |
| ---------------------- | ----------------------------------------------------------- |
| 📊 Price Charts        | Interactive candlestick / line charts with EMA/SMA overlays |
| 🔢 Multi-timeframe RSI | Daily, weekly, and monthly RSI                              |
| 📐 Pivot Levels        | Classic, Fibonacci, and Camarilla pivots                    |
| 💹 VCP Screener        | Volatility Contraction Pattern scanner across NSE 500       |
| 📡 7-Day Crossovers    | EMA crossover signals across the NSE 500 universe           |
| 🏢 Fundamentals        | P/E, EPS, Market Cap, Dividend Yield, 52-week range         |
| 📃 Financials          | Revenue, Profit, Assets, Liabilities, Cash Flow history     |
| 📈 Market Overview     | Real-time Nifty/Sensex + category-wise momentum heatmap     |

---

## Architecture

```
indianstock/
├── backend/
│   ├── main.py              # FastAPI app — routing, auth, rate-limiting, CORS
│   └── requirements.txt
├── execution/               # Deterministic Python scripts (analysis engines)
│   ├── analyze_stock.py     # Core analysis: indicators, financials, options
│   ├── screener.py          # EMA crossover screener
│   ├── vcp_screener.py      # VCP pattern screener
│   └── market_overview.py   # Index/market data fetcher
├── frontend/
│   ├── index.html           # Single-page app shell
│   ├── app.js               # All frontend logic and API calls
│   ├── style.css            # Dark-mode UI styles
│   ├── config.example.js    # ← Copy to config.js and add your API key
│   └── config.js            # ← Gitignored — contains your real API key
├── directives/              # SOPs / instructions for AI orchestration
├── .env                     # ← Gitignored — contains API_KEY for backend
└── ind_nifty500list.csv     # NSE 500 symbol reference list
```

---

## Quickstart

### Prerequisites

- Python 3.10+
- `pip` (or `uv`)

### 1. Clone the repo

```bash
git clone https://github.com/piyushk20/saraswati-stock-analyzer.git
cd saraswati-stock-analyzer
```

### 2. Set up environment variables

```bash
# Copy the template and set a strong secret key
cp .env.example .env
# Edit .env and set:  API_KEY=<your-secret-key>
```

```bash
# Copy the frontend config template and set the SAME key
cp frontend/config.example.js frontend/config.js
# Edit frontend/config.js and set:  API_KEY: "<your-secret-key>"
```

> ⚠️ **Never commit `.env` or `frontend/config.js`** — they are listed in `.gitignore` and contain your real API key.

### 3. Install backend dependencies

```bash
pip install -r backend/requirements.txt
```

### 4. Start the backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

The API docs will be available at `http://127.0.0.1:8000/docs`.

### 5. Serve the frontend

```bash
# From the repo root:
cd frontend
python -m http.server 8081
```

Then open **http://127.0.0.1:8081** in your browser.

---

## API Reference

All endpoints require the `X-API-Key` header.

| Method | Endpoint                   | Description                       |
| ------ | -------------------------- | --------------------------------- |
| `GET`  | `/ping`                    | Health check (no auth)            |
| `GET`  | `/health`                  | Detailed health (auth required)   |
| `GET`  | `/api/analyze/{symbol}`    | Full stock/index analysis         |
| `GET`  | `/api/screener/crossovers` | EMA crossover signals             |
| `GET`  | `/api/screener/vcp`        | VCP pattern results               |
| `GET`  | `/api/market/overview`     | Nifty/Sensex + top gainers/losers |
| `GET`  | `/api/market/nse500`       | NSE 500 symbol list               |

**Symbol format:** yfinance-compatible — e.g. `RELIANCE.NS`, `TCS.NS`, `^NSEI`, `^CNXFMCG`

---

## Security

The backend implements multiple layers of defense:

| Control                | Details                                                                             |
| ---------------------- | ----------------------------------------------------------------------------------- |
| **API Key Auth**       | Every protected endpoint requires `X-API-Key` header                                |
| **Input Validation**   | Ticker symbols validated against a strict `[\\w^.\\-&]{1,30}` regex                 |
| **Rate Limiting**      | 500 requests / minute per IP (in-memory, no external dependency)                    |
| **Security Headers**   | `X-Frame-Options`, `X-XSS-Protection`, `Content-Security-Policy`, `HSTS`            |
| **Error Masking**      | Internal stack traces are logged server-side only; clients receive generic messages |
| **No Secret Logging**  | Auth failures log a warning without echoing the key                                 |
| **Gitignored Secrets** | `.env` and `frontend/config.js` are excluded from version control                   |

---

## Environment Variables

| Variable  | Where                | Description                              |
| --------- | -------------------- | ---------------------------------------- |
| `API_KEY` | `.env`               | Secret key used by the FastAPI backend   |
| `API_KEY` | `frontend/config.js` | Must match the backend key (client-side) |

Create `.env` from the template:

```dotenv
# .env
API_KEY=change-this-to-a-strong-random-secret
```

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Commit with conventional commits: `git commit -m "feat: add new screener"`
4. Open a Pull Request

Please do not commit API keys, debug scripts, or test output files — see `.gitignore` for the exclude list.

---

## License

[MIT](https://opensource.org/licenses/MIT) © 2026 Piyush K
