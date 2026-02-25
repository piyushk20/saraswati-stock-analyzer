# Directive: Analyze Indian Stock

## Goal

Given an Indian stock ticker symbol (NSE format `TICKER.NS` or BSE index like `^NSEI`), produce a comprehensive JSON analysis including price data, technical indicators, fundamentals, and a narrative summary.

## Inputs

- `symbol` (str): The yfinance-compatible ticker. E.g., `RELIANCE.NS`, `TCS.NS`, `^NSEI`.

## Tools / Scripts

- **Script**: `execution/analyze_stock.py`
- **Library**: `yfinance`
- **Output**: JSON to stdout

## Output Schema (JSON)

```json
{
  "symbol": "RELIANCE.NS",
  "name": "Reliance Industries Ltd",
  "currency": "INR",
  "current_price": 2875.5,
  "open": 2850.0,
  "previous_close": 2860.0,
  "day_high": 2900.0,
  "day_low": 2830.0,
  "week_52_high": 3024.0,
  "week_52_low": 2220.0,
  "volume": 4200000,
  "avg_volume": 5100000,
  "market_cap": 1940000000000,
  "pe_ratio": 24.5,
  "eps": 117.0,
  "dividend_yield": 0.34,
  "beta": 0.95,
  "moving_avg_50": 2780.0,
  "moving_avg_200": 2650.0,
  "rsi_14": 58.4,
  "macd": 35.2,
  "macd_signal": 28.7,
  "price_change_1d": 15.5,
  "price_change_1d_pct": 0.54,
  "price_change_1w_pct": 2.1,
  "price_change_1m_pct": 4.3,
  "price_change_1y_pct": 18.7,
  "sector": "Energy",
  "industry": "Oil & Gas Refining & Marketing",
  "summary": "Reliance Industries is India's largest private-sector conglomerate...",
  "historical_prices": {
    "dates": ["2025-01-01", "..."],
    "closes": [2500.0, "..."]
  },
  "error": null
}
```

## Edge Cases

- If the symbol is invalid or data is unavailable, return `{"error": "Symbol not found or data unavailable", "symbol": "<input>"}`.
- For indices (starting with `^`), skip fundamental fields like `pe_ratio`, `eps`, `dividend_yield` as they are not applicable.
- RSI and MACD require at least 30 days of history. If unavailable, return `null` for those fields.

## Learnings

- `yfinance` often returns `None` for many fundamental fields for Indian stocks. Always handle with `.get()` and provide sensible defaults.
- Use `info` attribute for snapshot data; use `.history()` for OHLCV and technical calculations.
