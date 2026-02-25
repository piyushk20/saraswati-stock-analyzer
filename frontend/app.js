// app.js

const isLocalhost = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
const API_BASE = isLocalhost ? "http://localhost:8000/api/analyze" : "/api/analyze";

let chartInstance = null;

document.addEventListener("DOMContentLoaded", () => {
  const stockSelector = document.getElementById("stockSelector");
  
  stockSelector.addEventListener("change", async (e) => {
    const symbol = e.target.value;
    if (!symbol) return;
    
    showOverlay("loadingOverlay");
    hideOverlay("errorOverlay");
    document.getElementById("dashboardEl").style.display = "none";
    
    try {
      const resp = await fetch(`${API_BASE}/${encodeURIComponent(symbol)}`);
      const data = await resp.json();
      
      if (!resp.ok) {
        throw new Error(data.detail || "Error fetching data.");
      }
      
      renderDashboard(data);
    } catch (err) {
      console.error(err);
      showError(err.message);
    }
  });
});

function renderDashboard(data) {
  hideOverlay("loadingOverlay");
  hideOverlay("errorOverlay");
  document.getElementById("dashboardEl").style.display = "block";
  
  // Hero section
  document.getElementById("heroSymbol").textContent = (data.symbol || "").replace(/%5E/i, "^");
  document.getElementById("heroName").textContent = data.name || "N/A";
  document.getElementById("heroSector").textContent = `${data.sector || "N/A"} • ${data.industry || "N/A"}`;
  
  const currentPrice = data.current_price || data.regular_market_price || 0;
  const previousClose = data.previous_close || 0;
  const change = currentPrice - previousClose;
  const changePct = previousClose ? (change / previousClose * 100) : 0;
  
  document.getElementById("heroPrice").innerHTML = fmt(currentPrice);
  
  const changeEl = document.getElementById("heroChange");
  changeEl.className = `hero-change ${change >= 0 ? "up" : "down"}`;
  changeEl.innerHTML = `${change >= 0 ? "▲" : "▼"} ${fmtChange(change)} (${fmtPct(changePct)})`;
  
  renderChart(data);
  renderMetrics(data);
  renderTechGrid(data);
  renderFinancials(data);
  renderFundamentals(data);
  renderPivotGrid(data);
  renderRelativeStrength(data);
  renderOptionsData(data);
  renderPerformance(data);
}

function renderChart(data) {
  const dates = data.historical_prices ? data.historical_prices.dates : [];
  const prices = data.historical_prices ? data.historical_prices.closes : [];
  const startPrice = prices[0] || 0;
  const endPrice = prices[prices.length - 1] || 0;
  const isUp = endPrice >= startPrice;
  
  const lineColor = isUp ? "#00FF66" : "#FF0055";
  const gradStart = isUp ? "rgba(0, 255, 102, 0.4)" : "rgba(255, 0, 85, 0.4)";
  
  let existingChart = Chart.getChart("mainChart");
  if (existingChart) {
    existingChart.destroy();
  }
  
  if (chartInstance) {
    chartInstance.destroy();
  }
  
  const ctx = document.getElementById("mainChart").getContext("2d");
  
  const gradient = ctx.createLinearGradient(0, 0, 0, 400);
  gradient.addColorStop(0, gradStart);
  gradient.addColorStop(1, "rgba(5, 5, 10, 0)");

  // 50-day moving average
  const ma50 = rollingMean(prices, 50);

  // 20-day exponential moving average
  const ema20 = calculateEMA(prices, 20);

  chartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: dates.map(d => {
        const dt = new Date(d);
        return dt.toLocaleDateString("en-IN", { month: "short", day: "numeric" });
      }),
      datasets: [
        {
          label: "Close Price",
          data: prices,
          borderColor: lineColor,
          backgroundColor: gradient,
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 6,
          fill: true,
          tension: 0.2
        },
        {
          label: "20-Day EMA",
          data: ema20,
          borderColor: "rgba(255, 0, 85, 0.8)", // Bright magenta/pink for EMA
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
          tension: 0.4
        },
        {
          label: "50-Day MA",
          data: ma50,
          borderColor: "rgba(0, 240, 255, 0.4)", // Dimming cyan slightly so it doesn't overpower
          borderWidth: 1.5,
          borderDash: [5, 5],
          pointRadius: 0,
          fill: false,
          tension: 0.4
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false,
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "rgba(18, 18, 28, 0.9)",
          titleColor: "#8A9AAB",
          bodyColor: "#FFFFFF",
          borderColor: "rgba(0, 240, 255, 0.3)",
          borderWidth: 1,
          padding: 12,
          displayColors: true
        }
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { maxTicksLimit: 6, color: "#8A9AAB" }
        },
        y: {
          position: "right",
          grid: { color: "rgba(255, 255, 255, 0.05)" },
          ticks: { color: "#8A9AAB" }
        }
      }
    }
  });
}

function renderMetrics(data) {
  const metrics = [
    { label: "Day High/Low", value: `${fmt(data.day_high)} / ${fmt(data.day_low)}` },
    { label: "Volume", value: fmtVolume(data.volume) },
    { label: "52-Week High", value: fmt(data.week_52_high), klass: "text-up" },
    { label: "52-Week Low", value: fmt(data.week_52_low), klass: "text-down" }
  ];
  
  if (data.market_cap) {
    metrics.push({ label: "Market Cap", value: fmtMktCap(data.market_cap) });
  }

  const grid = document.getElementById("metricsBar");
  grid.innerHTML = metrics.map(m =>
    `<div class="metric-card">
      <div class="metric-label">${sanitize(m.label)}</div>
      <div class="metric-value ${m.klass || ""}">${sanitize(m.value.replace(/^₹/, ""))}</div>
    </div>`
  ).join("");
}

function renderTechGrid(data) {
  // Mini cards for RSI, MACD, Signal
  const rsi = data.rsi_14;
  let rsiColor = "var(--text-main)", rsiSignal = "NEUTRAL", rsiClass = "neutral";
  if (rsi !== null && rsi !== undefined) {
    if (rsi > 70) { rsiColor = "var(--negative)"; rsiSignal = "OVERBOUGHT"; rsiClass = "bearish"; }
    else if (rsi < 30) { rsiColor = "var(--positive)"; rsiSignal = "OVERSOLD"; rsiClass = "bullish"; }
  }
  const rsiFillPct = (rsi !== null && rsi !== undefined) ? Math.min(Math.max(rsi, 0), 100) : 50;

  document.getElementById("rsiCard").innerHTML = `
    <div class="indicator-label">RSI Gauge (14D)</div>
    <div class="indicator-val-primary" style="color:${sanitize(rsiColor)}">${(rsi !== null && rsi !== undefined) ? rsi.toFixed(1) : "N"}</div>
    <div class="rsi-track">
      <div class="rsi-fill" style="width:${rsiFillPct}%; background:${sanitize(rsiColor)}"></div>
    </div>
    <div class="signal-badge ${sanitize(rsiClass)}">${sanitize(rsiSignal)}</div>
  `;

  const macd = data.macd;
  const macdUp = data.macd_histogram && data.macd_histogram > 0;
  const macdClass = macdUp ? "bullish" : "bearish";
  document.getElementById("macdCard").innerHTML = `
    <div class="indicator-label">MACD Oscillation</div>
    <div class="indicator-val-primary" style="color:${macdClass === "bullish" ? "var(--positive)" : "var(--negative)"}">
      ${(macd !== null && macd !== undefined) ? macd.toFixed(2) : "N"}
    </div>
    <div class="signal-badge ${sanitize(macdClass)}">${(macd === null || macd === undefined) ? "N/A" : macdUp ? "BULL momentum" : "BEAR momentum"}</div>
  `;

  const sig = data.macd_signal;
  const crossUp = (macd !== null && macd !== undefined && sig !== null && sig !== undefined) && macd > sig;
  document.getElementById("signalCard").innerHTML = `
    <div class="indicator-label">Signal Line</div>
    <div class="indicator-val-primary" style="color:${crossUp ? "var(--positive)" : "var(--negative)"}">
      ${(sig !== null && sig !== undefined) ? sig.toFixed(2) : "N"}
    </div>
    <div class="signal-badge ${crossUp ? "bullish" : "bearish"}">${(sig === null || sig === undefined) ? "N/A" : crossUp ? "BUY CROSS" : "SELL CROSS"}</div>
  `;

  const current = data.current_price || data.regular_market_price;
  let volSignal = null;
  if (data.volume_trend) {
      if (data.volume_trend.includes("Buying")) {
          volSignal = { t: "BUYERS", c: "bullish" };
      } else if (data.volume_trend.includes("Selling")) {
          volSignal = { t: "SELLERS", c: "bearish" };
      } else {
          volSignal = { t: "NEUTRAL", c: "neutral" };
      }
  }

  const items = [
    { label: "20-Day SMA", value: fmt(data.sma_20), signal: current > data.sma_20 ? {t:"ABOVE", c:"bullish"} : {t:"BELOW", c:"bearish"} },
    { label: "50-Day SMA", value: fmt(data.sma_50), signal: current > data.sma_50 ? {t:"ABOVE", c:"bullish"} : {t:"BELOW", c:"bearish"} },
    { label: "200-Day SMA", value: fmt(data.sma_200), signal: current > data.sma_200 ? {t:"UPTREND", c:"bullish"} : {t:"DOWNTREND", c:"bearish"} },
    { label: "Volume Trend", value: data.volume_trend || "Neutral", signal: volSignal },
  ];

  document.getElementById("techDataGrid").innerHTML = items.map(item =>
    `<div class="data-row">
      <div class="data-label">${sanitize(item.label)}</div>
      <div class="data-value">${sanitize(item.value)}
        ${item.signal ? `<span class="signal-badge ${sanitize(item.signal.c)}" style="margin-left:0.5rem; font-size: 0.65rem">${sanitize(item.signal.t)}</span>` : ""}
      </div>
    </div>`
  ).join("");
}

function renderFinancials(data) {
  // New "Financial Statements" data added from the backend request (P&L, Balance Sheet, Cash Flow)
  const isIndex = data.sector === "Index";
  const box = document.getElementById("financialsBox");
  if (isIndex || data.financials_revenue === null) {
      box.style.display = "none";
      return;
  } else {
      box.style.display = "block";
  }

  const items = [
    { label: "Total Revenue", value: fmtMktCap(data.financials_revenue) },
    { label: "Gross Profit", value: fmtMktCap(data.financials_gross_profit) },
    { label: "Operating Income", value: fmtMktCap(data.financials_operating_income) },
    { label: "Net Income", value: fmtMktCap(data.financials_net_income), highlight: data.financials_net_income > 0 ? "text-up" : "text-down" },
    { label: "Total Assets", value: fmtMktCap(data.bs_total_assets) },
    { label: "Total Liabilities", value: fmtMktCap(data.bs_total_liabilities) },
    { label: "Total Equity", value: fmtMktCap(data.bs_total_equity) },
    { label: "Total Debt", value: fmtMktCap(data.bs_total_debt) },
    { label: "Operating Cash Flow", value: fmtMktCap(data.cf_operating) },
    { label: "Free Cash Flow", value: fmtMktCap(data.cf_free_cash_flow), highlight: data.cf_free_cash_flow > 0 ? "text-up" : "text-down" }
  ];

  document.getElementById("financialsGrid").innerHTML = items.map(item =>
    `<div class="data-row">
      <div class="data-label">${sanitize(item.label)}</div>
      <div class="data-value ${item.highlight || ""}">${sanitize(item.value)}</div>
    </div>`
  ).join("");
}

function renderFundamentals(data) {
  const isIndex = data.sector === "Index";
  const box = document.getElementById("fundamentalsBox");
  if (isIndex) {
      box.style.display = "none";
      return;
  } else {
      box.style.display = "block";
  }

  const items = [
    { label: "P/E Ratio (TTM)", value: data.pe_ratio ? data.pe_ratio.toFixed(2) : "N/A" },
    { label: "Forward P/E", value: data.forward_pe ? data.forward_pe.toFixed(2) : "N/A" },
    { label: "EPS (TTM)", value: fmt(data.eps) },
    { label: "Dividend Yield", value: data.dividend_yield ? (data.dividend_yield * 100).toFixed(2) + "%" : "0.00%" },
    { label: "Price / Book", value: data.price_to_book ? data.price_to_book.toFixed(2) : "N/A" },
    { label: "Book Value/Sh", value: fmt(data.book_value) },
    { label: "Return on Equity", value: data.roe ? (data.roe * 100).toFixed(2) + "%" : "N/A" },
    { label: "Debt / Equity", value: data.debt_to_equity ? data.debt_to_equity.toFixed(2) : "N/A" }
  ];

  document.getElementById("fundGrid").innerHTML = items.map(item =>
    `<div class="data-row">
      <div class="data-label">${sanitize(item.label)}</div>
      <div class="data-value">${sanitize(item.value)}</div>
    </div>`
  ).join("");
}

function renderPivotGrid(data) {
  const box = document.getElementById("pivotBox");
  if (!data.pivot_points) {
      box.style.display = "none";
      return;
  }
  box.style.display = "block";

  const p = data.pivot_points;
  const current = data.current_price || 0;

  const getHighlight = (val) => {
    // If exact match (rare) neutral, if above current it's resistance, below is support.
    // For pure UI, R limits are red, S limits are green
    return "";
  };

  const items = [
    { label: "Resistance 3 (R3)", value: fmt(p.r3), highlight: "text-down" },
    { label: "Resistance 2 (R2)", value: fmt(p.r2), highlight: "text-down" },
    { label: "Resistance 1 (R1)", value: fmt(p.r1), highlight: "text-down" },
    { label: "Pivot Point (PP)", value: fmt(p.pp), highlight: "" },
    { label: "Support 1 (S1)", value: fmt(p.s1), highlight: "text-up" },
    { label: "Support 2 (S2)", value: fmt(p.s2), highlight: "text-up" },
    { label: "Support 3 (S3)", value: fmt(p.s3), highlight: "text-up" }
  ];

  document.getElementById("pivotGrid").innerHTML = items.map(item =>
    `<div class="data-row">
      <div class="data-label">${sanitize(item.label)}</div>
      <div class="data-value ${item.highlight}">${sanitize(item.value)}</div>
    </div>`
  ).join("");
}

function renderRelativeStrength(data) {
  const box = document.getElementById("rsBox");
  if (!data.relative_strength) {
    box.style.display = "none";
    return;
  }
  box.style.display = "block";

  const rs = data.relative_strength;
  
  const getStyle = (val) => {
    if (val === null || val === undefined) return "";
    return val >= 0 ? "text-up" : "text-down";
  };

  const getVal = (val) => {
    if (val === null || val === undefined) return "N/A";
    return (val > 0 ? "+" : "") + val.toFixed(2) + "%";
  };

  const items = [
    { label: "vs Nifty 50 (1M)", value: getVal(rs.nifty_1m), highlight: getStyle(rs.nifty_1m) },
    { label: "vs Nifty 50 (1Y)", value: getVal(rs.nifty_1y), highlight: getStyle(rs.nifty_1y) },
    { label: `vs ${rs.sector_index || 'Sector'} (1M)`, value: getVal(rs.sector_1m), highlight: getStyle(rs.sector_1m) },
    { label: `vs ${rs.sector_index || 'Sector'} (1Y)`, value: getVal(rs.sector_1y), highlight: getStyle(rs.sector_1y) },
  ];

  document.getElementById("rsGrid").innerHTML = items.map(item =>
    `<div class="data-row">
      <div class="data-label">${sanitize(item.label)}</div>
      <div class="data-value ${item.highlight}">${sanitize(item.value)}</div>
    </div>`
  ).join("");
}

function renderOptionsData(data) {
  const box = document.getElementById("optionsBox");
  if (!data.options_data) {
    box.style.display = "none";
    return;
  }
  
  const opt = data.options_data;
  if (!opt.current && !opt.next) {
    document.getElementById("optionsGrid").innerHTML = `<div class="data-row" style="color: var(--text-dim);">No options data available for this symbol.</div>`;
    box.style.display = "block";
    return;
  }
  
  box.style.display = "block";
  let items = [];

  const addExp = (labelPrefix, expData) => {
    if (!expData) return;
    items.push({
      label: `${labelPrefix} (Calls Max OI Strike)`, 
      value: expData.max_call_oi_strike ? fmt(expData.max_call_oi_strike) : "N/A",
      highlight: "text-down" // Huge Call OI often acts as resistance
    });
    items.push({
      label: `${labelPrefix} (Puts Max OI Strike)`, 
      value: expData.max_put_oi_strike ? fmt(expData.max_put_oi_strike) : "N/A",
      highlight: "text-up" // Huge Put OI often acts as support
    });
  };

  if (opt.current) addExp("Current Expiry", opt.current);
  if (opt.next) addExp("Next Expiry", opt.next);

  document.getElementById("optionsGrid").innerHTML = items.map(item =>
    `<div class="data-row">
      <div class="data-label">${sanitize(item.label)}</div>
      <div class="data-value ${item.highlight}">${sanitize(item.value)}</div>
    </div>`
  ).join("");
}

function renderPerformance(data) {
  const perfs = data.performance || [];
  if (!perfs.length) return;

  document.getElementById("perfGrid").innerHTML = perfs.map(p => {
    const up = p.pct >= 0;
    const pctDisplay = p.pct !== null && p.pct !== undefined
      ? `${up ? "+" : ""}${Number(p.pct).toFixed(2)}%`
      : "N/A";
    
    return `<div class="perf-block">
      <div class="perf-period">${sanitize(p.period)}</div>
      <div class="perf-pct ${up ? "up" : "down"}">${pctDisplay}</div>
    </div>`;
  }).join("");
}

// ============================================================
// Utilities
// ============================================================

function sanitize(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");
}

function fmt(val) {
  if (val === null || val === undefined) return "N/A";
  return "₹" + Number(val).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtChange(val) {
  if (val === null || val === undefined) return "N/A";
  const sign = val >= 0 ? "+" : "";
  return sign + "₹" + Math.abs(Number(val)).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(val) {
  if (val === null || val === undefined) return "";
  const sign = val >= 0 ? "+" : "";
  return sign + Number(val).toFixed(2) + "%";
}

function fmtVolume(val) {
  if (!val) return "N/A";
  if (val >= 1e7)  return (val / 1e7).toFixed(2) + " Cr";
  if (val >= 1e5)  return (val / 1e5).toFixed(2) + " L";
  if (val >= 1000) return (val / 1000).toFixed(1) + "K";
  return String(val);
}

function fmtMktCap(val) {
  if (!val) return "N/A";
  if (val >= 1e12) return "₹" + (val / 1e12).toFixed(2) + "T";
  if (val >= 1e9)  return "₹" + (val / 1e9).toFixed(2) + "B";
  if (val >= 1e7)  return "₹" + (val / 1e7).toFixed(2) + " Cr";
  return "₹" + val.toLocaleString("en-IN");
}

function rollingMean(arr, window) {
  return arr.map((_, i) => {
    if (i < window - 1) return null;
    const slice = arr.slice(i - window + 1, i + 1);
    return slice.reduce((a, b) => a + b, 0) / window;
  });
}

function calculateEMA(prices, window) {
  const k = 2 / (window + 1);
  const emaArray = new Array(prices.length).fill(null);
  
  if (prices.length < window) return emaArray;

  let sum = 0;
  for (let i = 0; i < window; i++) {
    sum += prices[i];
  }
  let prevEma = sum / window; // SMA for the first valid point
  emaArray[window - 1] = prevEma;

  for (let i = window; i < prices.length; i++) {
    const currentEma = (prices[i] * k) + (prevEma * (1 - k));
    emaArray[i] = currentEma;
    prevEma = currentEma;
  }
  
  return emaArray;
}

function showOverlay(id) {
  document.getElementById(id).classList.add("active");
  document.getElementById(id).style.display = "flex";
}

function hideOverlay(id) {
  document.getElementById(id).classList.remove("active");
  document.getElementById(id).style.display = "none";
}

function showError(msg) {
  hideOverlay("loadingOverlay");
  showOverlay("errorOverlay");
  document.getElementById("errorBox").textContent = msg;
}
