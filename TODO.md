# 📋 Project Roadmap & Backlog

## 🟢 In Progress (Current Sprint)
- [x] Refactor all screeners to `ThreadPoolExecutor` for stability.
- [x] Standardize backend/frontend ports (8001/8081).
- [x] Clean up 'dud' code and legacy `nsefin` imports.
- [x] Implement Episodic Pivot (EP) relaxed conditions for better discovery.

## 🟡 High Priority (Next Sprint)
- [ ] **Dynamic Filtering**: Allow users to change screener thresholds (e.g., Gap %, RSI levels) directly from the UI.
- [ ] **Alert System**: Backend service to check for new setups and send Telegram/WebPush notifications.
- [ ] **Data Persistence**: Save identified setups to a local SQLite database to track historical performance.
- [ ] **Sectoral Analysis**: Add a pie chart/breakdown of which sectors are showing the most momentum.

## 🔵 Backlog
- [ ] **Option Greeks**: Real-time Delta, Theta, and Gamma calculation for the Nifty/BankNifty option chain.
- [ ] **TradingView Integration**: Embed TradingView Advanced Charts for deeper technical analysis.
- [ ] **Portfolio Tracker**: Allow users to add their holdings and see automated analysis for their specific stocks.
- [ ] **Machine Learning**: Implement basic trend prediction using LSTM or XGBoost on historical OHLC data.

## 🛠️ Infrastructure Improvements
- [ ] Migrate to `uv` for lightning-fast dependency management.
- [ ] Containerize the application using `Docker` for easier deployment.
- [ ] Add unit tests for core analysis logic in `analyze_stock.py`.
