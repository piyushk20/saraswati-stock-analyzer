// app.js
console.log("🚀 APP.JS LOADED v7 — back-btn fix! 🚀");

// ── Session Token Handshake ───────────────────────────────────────────────────
// Fetch a short-lived session token from the backend on startup.
// The raw API key is never stored in any static JS file (C1 security fix).
async function initSessionToken() {
  try {
    const res = await fetch(`${window.API_BASE}/api/handshake`, { method: "GET" });
    if (res.ok) {
      const data = await res.json();
      window.SESSION_TOKEN = data.token;
      console.log("✅ Session token acquired (expires in", Math.round(data.expires_in / 3600), "h)");
    } else {
      console.warn("⚠️ /api/handshake returned", res.status, "— API calls may be rejected");
    }
  } catch (e) {
    console.error("❌ Could not reach backend for handshake:", e);
  }
}

// Fetch with timeout — prevents scanner requests from hanging indefinitely
const SCANNER_TIMEOUT_MS = 120000; // 120s per scanner request
function fetchWithTimeout(url, options = {}, timeoutMs = SCANNER_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, { ...options, signal: controller.signal })
    .finally(() => clearTimeout(timer));
}

const isLocal = window.location.hostname === "localhost" || 
                window.location.hostname === "127.0.0.1" || 
                window.location.protocol === "file:" ||
                window.location.hostname.startsWith("192.168.") ||
                window.location.hostname.startsWith("10.") ||
                window.location.hostname === "";

// Backend (uvicorn) always on 8001; static file server on 8081
// window.API_BASE used by all fetch calls
window.API_BASE = isLocal ? "http://127.0.0.1:8001" : "";

let chartInstance = null;
let activeApiPort = "8001"; // Legacy reference — use window.API_BASE instead
let currentMomentumCategory = localStorage.getItem('lastCategory') || 'nifty50';
let currentSymbol = null; // To prevent race conditions
let currentPeriod = localStorage.getItem('lastPeriod') || '3m'; 
let currentTaData = null; // Global store for the active stock's detailed technical data


window.changeMomentumCategory = function(cat) {
  currentMomentumCategory = cat;
  localStorage.setItem('lastCategory', cat);
  
  // Update button active states
  document.querySelectorAll('.cat-btn').forEach(btn => {
    if (btn.getAttribute('onclick') && btn.getAttribute('onclick').includes(cat)) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });
  
  // Reload data
  loadMarketOverview(cat);
  loadScreenerData(cat);

  const rrgContent = document.getElementById("rrgTabContent");
  if (rrgContent && rrgContent.style.display === "flex") {
    triggerRrgScan(false);
  }
};

window.runScanners = async function(isNewSession) {
  const TOTAL_SCANNER_BUDGET_MS = 120000; // 120s total budget for all scanners
  const scanStart = performance.now();
  const scanners = [
    ['VCP',      () => loadVcpScreenerData(isNewSession)],
    ['EP',       () => loadEpScreenerData(isNewSession)],
    ['RSI',      () => loadRsiScreenerData(isNewSession)],
    ['Momentum', () => loadMomentumScreenerData(isNewSession)],
    ['Flag',     () => loadFlagScreenerData(isNewSession)],
  ];
  for (const [name, fn] of scanners) {
    const elapsed = performance.now() - scanStart;
    if (elapsed > TOTAL_SCANNER_BUDGET_MS) {
      console.warn(`⏱️ Scanner budget exhausted after ${(elapsed/1000).toFixed(1)}s — skipping remaining scanners`);
      break;
    }
    const t0 = performance.now();
    await fn().catch(e => console.error(`${name} scan error:`, e));
    console.log(`✅ ${name} scanner loaded in ${((performance.now()-t0)/1000).toFixed(1)}s`);
  }
  console.log(`🏁 All scanners completed in ${((performance.now()-scanStart)/1000).toFixed(1)}s`);
};

document.addEventListener("DOMContentLoaded", async () => {
  // Fetch session token from backend FIRST, before any authenticated API call.
  await initSessionToken();

  // Populate the dropdown with NSE 500 stocks
  loadNse500Stocks();
  
  // Stagger background fetches to avoid saturating backend/API
  const urlParams = new URLSearchParams(window.location.search);
  const skipScans = urlParams.get('noscan') === '1';
  const paramSymbol = urlParams.get('symbol');
  const lastStock = paramSymbol || localStorage.getItem('lastStock');
  
  if (lastStock) {
     const select = document.getElementById("stockSelector");
     if (select && !Array.from(select.options).some(o => o.value === lastStock)) {
        const tempOpt = document.createElement("option");
        tempOpt.value = lastStock;
        tempOpt.text = lastStock;
        select.add(tempOpt);
     }
     if (select) select.value = lastStock;
     loadStockDashboard(lastStock);
     // Pre-load market overview in background so it's ready when user clicks Back
     loadMarketOverview(currentMomentumCategory).catch(() => {});
     loadScreenerData(currentMomentumCategory).catch(() => {});
  } else if (!skipScans) {
    // Execute calls sequentially with delays instead of scattered timeouts
    // This prevents race conditions with layout loading and overlay hiding
    showOverlay("loadingOverlay");
    const initData = async () => {
      // Set active state for the saved category
      const buttons = document.querySelectorAll('.cat-btn');
      buttons.forEach(btn => {
        if (btn.getAttribute('onclick').includes(`'${currentMomentumCategory}'`)) {
          btn.classList.add('active');
        } else {
          btn.classList.remove('active');
        }
      });

      const forceScan = urlParams.get('force') === 'true';

      // Critical data first
      await Promise.all([
        loadScreenerData(currentMomentumCategory, forceScan).catch(e => console.error(e)),
        loadMarketOverview(currentMomentumCategory, forceScan).catch(e => console.error(e))
      ]);
      
      const initialDashboard = document.getElementById("initialDashboard");
      const stockSelector = document.getElementById("stockSelector");
      if (initialDashboard && (!stockSelector || !stockSelector.value)) {
        initialDashboard.style.display = "flex";
      }
      hideOverlay("loadingOverlay");
      
      // Load screeners sequentially to prevent backend saturation and load within a fixed, efficient time
      window.runScanners(forceScan);
    };
    initData();
  } else {
    console.log("? Background scans skipped via noscan=1 parameter.");
    hideOverlay("loadingOverlay");
    const initialDashboard = document.getElementById("initialDashboard");
    if (initialDashboard) initialDashboard.style.display = "flex";
  }

  const stockSelector = document.getElementById("stockSelector");
  const stockSearch = document.getElementById("stockSearch");
  
  // SEARCH FILTER LOGIC
  if (stockSearch && stockSelector) {
    stockSearch.addEventListener("keyup", (e) => {
      const term = e.target.value.toUpperCase();
      const options = stockSelector.options;
      
      for (let i = 1; i < options.length; i++) {
        const txt = options[i].text.toUpperCase();
        const val = options[i].value.toUpperCase();
        // Show if matches symbol or name
        const match = txt.includes(term) || val.includes(term);
        options[i].style.display = match ? "" : "none";
      }
    });

    // Fix: Search on Enter
    stockSearch.addEventListener("keypress", (e) => {
      if (e.key === "Enter") {
        const term = stockSearch.value.toUpperCase();
        const options = stockSelector.options;
        for (let i = 1; i < options.length; i++) {
          const txt = options[i].text.toUpperCase();
          const val = options[i].value.toUpperCase();
          if (txt.includes(term) || val.includes(term)) {
            stockSelector.value = options[i].value;
            loadStockDashboard(options[i].value);
            break;
          }
        }
      }
    });

    // Clear search on selection
    stockSelector.addEventListener("change", () => {
      stockSearch.value = "";
      // Reset visibility
      for (let i = 1; i < stockSelector.options.length; i++) {
        stockSelector.options[i].style.display = "";
      }
    });
  }
  
  stockSelector.addEventListener("change", async (e) => {
    const symbol = e.target.value;
    if (symbol) loadStockDashboard(symbol);
  });

  const backBtn = document.getElementById("backToDashboardBtn");
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      stockSelector.value = ""; // Reset dropdown
      localStorage.removeItem('lastStock'); // Forget it
      document.getElementById("dashboardEl").style.display = "none";
      const initialDashboard = document.getElementById("initialDashboard");
      if (initialDashboard) initialDashboard.style.display = "flex";
      
      // Since screenerBox is inside initialDashboard now, it should display if the initialDashboard displays,
      // but just in case we explicitly hid it before:
      const screenerBox = document.getElementById("screenerBox");
      if (screenerBox) screenerBox.style.display = "block";
      const vcpBox = document.getElementById("vcpBox");
      if (vcpBox) vcpBox.style.display = "block";
      const epBox = document.getElementById("epBox");
      if (epBox) epBox.style.display = "flex";
      const rsiScreenerBox = document.getElementById("rsiScreenerBox");
      if (rsiScreenerBox) rsiScreenerBox.style.display = "flex";
      const momentumBox = document.getElementById("momentumBox");
      if (momentumBox) momentumBox.style.display = "flex";
      const flagBox = document.getElementById("flagBox");
      if (flagBox) flagBox.style.display = "flex";
      
      // Always reload market overview so gainers/losers/sectors are fresh
      loadMarketOverview(currentMomentumCategory);
      loadScreenerData(currentMomentumCategory);

      const vcpBody = document.getElementById("vcpScreenerBody");
      if (vcpBody && vcpBody.innerHTML.includes("Scanning")) {
         window.runScanners(false);
      }
      
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  // Period Selector Event Delegation
  
  // TA Indicator Select Event
  const taSelect = document.getElementById("taIndicatorSelect");
  if (taSelect) {
    taSelect.addEventListener("change", (e) => {
      renderTaDetails(e.target.value);
    });
  }
});


async function loadStockDashboard(symbol, period = null) {
  if (!symbol) return;
  
  // Clear search bar and reset dropdown visibility
  const stockSearch = document.getElementById("stockSearch");
  if (stockSearch) stockSearch.value = "";
  const stockSelector = document.getElementById("stockSelector");
  if (stockSelector) {
    for (let i = 1; i < stockSelector.options.length; i++) {
      stockSelector.options[i].style.display = "";
    }
  }
  
  if (period) {
    currentPeriod = period;
  } else {
    // Sync UI with currentPeriod when opening dashboard
    const activeBtn = document.querySelector(`.period-btn[data-period="${currentPeriod}"]`);
    if (activeBtn) {
      document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
      activeBtn.classList.add('active');
    }
  }

  localStorage.setItem('lastStock', symbol);
  localStorage.setItem('lastPeriod', currentPeriod);
  
  showOverlay("loadingOverlay");
  hideOverlay("errorOverlay");
  
  // Only hide the main dashboard element if it's a NEW symbol
  // If it's just a period change, we might want to show a smaller loader inside the chart card instead,
  // but for now, full overlay is safer to avoid Chart.js artifacts.
  if (!period) {
     document.getElementById("dashboardEl").style.display = "none";
  }
  
  // Hide initial dashboard and parts
  const initialDashboard = document.getElementById("initialDashboard");
  if (initialDashboard) initialDashboard.style.display = "none";
  const screenerBox = document.getElementById("screenerBox");
  if (screenerBox) screenerBox.style.display = "none";
  
  try {
    currentSymbol = symbol;
    // Backend (uvicorn) is on port 8000; frontend HTTP server is on 8081
    const fetchUrl = `${window.API_BASE}/api/analyze/${encodeURIComponent(symbol)}?period=${currentPeriod}&v=${new Date().getTime()}`;

    console.log(`📡 Fetching from: ${fetchUrl} (Period: ${currentPeriod})`);

    const resp = await fetch(fetchUrl, {
      headers: { "X-API-Key": window.SESSION_TOKEN || "" },
      cache: "no-store"
    });
    
    // Race condition check
    if (symbol !== currentSymbol) {
      console.warn(`🛑 Abandoning request for ${symbol} as ${currentSymbol} is now active.`);
      return;
    }

    let data;
    if (resp.ok) {
      data = await resp.json();
    } else if (resp.status === 429) {
      // Yahoo Finance rate limit — show friendly retry countdown
      showRateLimitError(symbol);
      return;
    } else {
      const errorText = await resp.text();
      throw new Error(`Error fetching data: ${resp.status} - ${errorText}`);
    }
    
    renderDashboard(data);
    hideOverlay("loadingOverlay"); // Ensure overlay is hidden after successful render
  } catch (err) {
    console.error(err);
    showError(err.message);
  }
}

/**
 * Shows a user-friendly rate limit error with auto-retry countdown.
 */
function showRateLimitError(symbol) {
  hideOverlay("loadingOverlay");
  const errorBox = document.getElementById("errorBox");
  let seconds = 8;
  
  const update = () => {
    errorBox.innerHTML = `
      <div style="text-align:center;">
        <div style="font-size:1.5rem;margin-bottom:0.5rem;">⚡ Yahoo Finance Rate Limit</div>
        <div style="color:var(--text-dim);margin-bottom:1rem;font-size:0.9rem;">
          Too many requests were made during market scanning. Retrying <strong>${symbol}</strong> in ${seconds}s…
        </div>
        <button onclick="clearInterval(window._rlTimer);loadStockDashboard('${symbol}');"
          style="padding:0.5rem 1.5rem;background:var(--accent-teal,#00e5ff);color:#000;border:none;border-radius:8px;cursor:pointer;font-weight:600;">
          Retry Now
        </button>
      </div>`;
  };
  
  update();
  showOverlay("errorOverlay");
  
  window._rlTimer = setInterval(() => {
    seconds--;
    if (seconds <= 0) {
      clearInterval(window._rlTimer);
      hideOverlay("errorOverlay");
      loadStockDashboard(symbol);
    } else {
      update();
    }
  }, 1000);
}

/**
 * GLOBAL: Change Momentum Category
 */
window.changeMomentumCategory = function(category) {
  currentMomentumCategory = category;
  localStorage.setItem('lastCategory', category);
  
  // Update UI buttons
  const buttons = document.querySelectorAll('.cat-btn');
  buttons.forEach(btn => {
    if (btn.getAttribute('onclick') && btn.getAttribute('onclick').includes(`'${category}'`)) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });
  
  // Show localized loaders
  if (document.getElementById("screenerTableBody")) {
    document.getElementById("screenerTableBody").innerHTML = `<tr><td colspan="4" style="text-align:center;"><div class="pulse-loader">Refreshing ${category}...</div></td></tr>`;
  }
  if (document.getElementById("gainersTableBody")) {
    document.getElementById("gainersTableBody").innerHTML = `<tr><td colspan="3" style="text-align:center;"><div class="pulse-loader">Refreshing...</div></td></tr>`;
  }
  if (document.getElementById("losersTableBody")) {
    document.getElementById("losersTableBody").innerHTML = `<tr><td colspan="3" style="text-align:center;"><div class="pulse-loader">Refreshing...</div></td></tr>`;
  }
  
  // Trigger refreshes
  loadScreenerData(category);
  loadMarketOverview(category);

  // RRG tab refresh
  const rrgContent = document.getElementById("rrgTabContent");
  if (rrgContent && rrgContent.style.display === "flex") {
    triggerRrgScan(false);
  }
};

async function loadScreenerData(category = 'nifty50', force = false) {
  const tableBody = document.getElementById("screenerTableBody");
  const screenerBox = document.getElementById("screenerBox");
  
  if (!tableBody || !screenerBox) return;

  // Sector indices don't support EMA crossover screening — show a note instead
  if (category === 'sectors') {
    screenerBox.style.display = "block";
    tableBody.innerHTML = `<tr><td colspan="4" style="text-align:center; color:var(--text-muted); padding: 1.5rem;">
      EMA crossover scanning is not applicable for sector indices.<br>
      <span style="font-size:0.8rem;">Switch to the RRG tab to view sectoral relative strength.</span>
    </td></tr>`;
    return;
  }
  
  try {
    const forceParam = force ? "&force=true" : "";
    const fetchUrl = `${window.API_BASE}/api/screener/crossovers?category=${category}&v=${new Date().getTime()}${forceParam}`;

    const resp = await fetch(fetchUrl, {
      headers: { "X-API-Key": window.SESSION_TOKEN || "" },
      cache: "no-store"
    });
    
    if (!resp.ok) throw new Error(`Could not reach backend on port 8000: ${resp.status}`);
    const data = await resp.json();
    
    // Reveal the box only if no stock has been actively selected yet
    const stockSelector = document.getElementById("stockSelector");
    if (!stockSelector.value) {
      screenerBox.style.display = "block";
    }
    
    if (data.crossovers && data.crossovers.length > 0) {
      tableBody.innerHTML = "";
      
      data.crossovers.forEach(item => {
        const isGolden = item.type === "Golden Cross";
        const cssClass = isGolden ? "cross-golden" : "cross-death";
        
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><strong>${sanitize(item.symbol.replace(/%5E/i, '^'))}</strong></td>
          <td class="${sanitize(cssClass)}">${sanitize(item.type)}</td>
          <td style="font-family: var(--font-mono)">${sanitize(item.price)}</td>
          <td>${sanitize(item.date)}</td>
        `;
        
        tr.addEventListener("click", () => {
          // Deep link / Auto-Select symbol logic
          const select = document.getElementById("stockSelector");
          
          // For indexes or stocks not in the dropdown natively, 
          // ensure the option exists or just set the value and trigger change
          if (!Array.from(select.options).some(o => o.value === item.symbol)) {
            const tempOpt = document.createElement("option");
            tempOpt.value = item.symbol;
            tempOpt.text = item.symbol;
            select.add(tempOpt);
          }
          
          select.value = item.symbol;
          select.dispatchEvent(new Event('change'));
          window.scrollTo({ top: 0, behavior: 'smooth' });
        });
        
        tableBody.appendChild(tr);
      });
    } else {
      tableBody.innerHTML = `<tr><td colspan="4" style="text-align:center;">No recent crossovers found.</td></tr>`;
    }
  } catch (err) {
    if (tableBody) {
      tableBody.innerHTML = `<tr><td colspan="4" style="color:red; text-align:center; padding:20px;">Error: ${sanitize(err.message)}</td></tr>`;
    }
    console.error("Screener fetch error:", err);
  }
}

// -----------------------------------------------------------------
// VCP SCREENER
// -----------------------------------------------------------------
async function loadVcpScreenerData(force = false) {
  const vcpBody = document.getElementById("vcpScreenerBody");
  if (!vcpBody) return;
  
  vcpBody.innerHTML = `<tr><td colspan="2" style="text-align:center;"><div class="pulse-loader" style="color:var(--text-dim)">Scanning NSE 500 for VCP...</div></td></tr>`;
  
  try {
    console.log("📡 Fetching VCP Screener data...");
    const forceParam = force ? "&force=true" : "";
    const fetchUrl = `${window.API_BASE}/api/screener/vcp?v=${new Date().getTime()}${forceParam}`;

    const resp = await fetchWithTimeout(fetchUrl, {
      headers: { "X-API-Key": window.SESSION_TOKEN || "" },
      cache: "no-store"
    });
    
    if (!resp.ok) throw new Error("Could not fetch VCP screener data");
    const data = await resp.json();

    if (data.vcp_stocks && data.vcp_stocks.length > 0) {
      vcpBody.innerHTML = "";
      data.vcp_stocks.forEach(stock => {
        const tr = document.createElement("tr");
        tr.style.cursor = "pointer";
        tr.innerHTML = `
          <td><strong>${sanitize(stock.symbol)}</strong></td>
          <td class="text-green">${sanitize(fmt(stock.price))}</td>
        `;
        tr.addEventListener("click", () => {
           const select = document.getElementById("stockSelector");
           if (!Array.from(select.options).some(o => o.value === stock.symbol)) {
             const tempOpt = document.createElement("option");
             tempOpt.value = stock.symbol;
             tempOpt.text = stock.symbol;
             select.add(tempOpt);
           }
           select.value = stock.symbol;
           select.dispatchEvent(new Event('change'));
           window.scrollTo({ top: 0, behavior: 'smooth' });
        });
        vcpBody.appendChild(tr);
      });
    } else {
      vcpBody.innerHTML = `<tr><td colspan="2" style="text-align:center;">No VCP patterns detected today</td></tr>`;
    }

  } catch (err) {
    if (vcpBody) {
      vcpBody.innerHTML = `<tr><td colspan="2" style="color:red; text-align:center; padding:20px;">Error: ${sanitize(err.message)}</td></tr>`;
    }
    console.error("VCP fetch error:", err);
  }
}

// -----------------------------------------------------------------
// EP (EPISODIC PIVOT) SCREENER
// -----------------------------------------------------------------
async function loadEpScreenerData(force = false) {
  const epBody = document.getElementById("epScreenerBody");
  if (!epBody) return;

  epBody.innerHTML = `<tr><td colspan="8" style="text-align:center;"><div class="pulse-loader" style="color:var(--text-dim)">Scanning NSE 500 for Episodic Pivots...</div></td></tr>`;

  try {
    console.log("📡 Fetching EP Screener data...");
    const forceParam = force ? "&force=true" : "";
    const fetchUrl = `${window.API_BASE}/api/screener/ep?v=${new Date().getTime()}${forceParam}`;
    const resp = await fetchWithTimeout(fetchUrl, {
      headers: { "X-API-Key": window.SESSION_TOKEN || "" },
      cache: "no-store"
    });

    if (!resp.ok) throw new Error(`EP screener request failed: ${resp.status}`);
    const data = await resp.json();

    if (data.ep_stocks && data.ep_stocks.length > 0) {
      epBody.innerHTML = "";
      data.ep_stocks.forEach(stock => {
        const scoreVal = stock.score || 0;
        const scoreClass = scoreVal >= 75 ? "ep-score-high" : scoreVal >= 55 ? "ep-score-mid" : "ep-score-low";
        const dist52  = stock.pct_from_52h != null ? stock.pct_from_52h : null;
        const dist52Class = dist52 !== null && dist52 >= -10 ? "text-green" : "text-amber";
        const daysAgo = stock.days_ago === 0 ? "Today" : stock.days_ago === 1 ? "Yesterday" : `${stock.days_ago}d ago`;

        const tr = document.createElement("tr");
        tr.style.cursor = "pointer";
        tr.innerHTML = `
          <td><strong>${sanitize(stock.display_symbol || stock.symbol)}</strong></td>
          <td style="font-family:var(--font-mono)">₹${sanitize(String(stock.price))}</td>
          <td class="text-green bold">+${sanitize(String(stock.gap_pct))}%</td>
          <td class="text-amber">${sanitize(String(stock.rvol))}x</td>
          <td><span class="ep-score-pill ${sanitize(scoreClass)}">${sanitize(String(scoreVal))}</span></td>
          <td>${stock.is_stage2 ? '<span class="stage2-badge">✓ S2</span>' : '<span style="color:var(--text-muted)">—</span>'}</td>
          <td class="${sanitize(dist52Class)}">${dist52 !== null ? dist52 + '%' : '—'}</td>
          <td style="color:var(--text-muted);font-size:0.8rem">${sanitize(daysAgo)}</td>
        `;
        tr.addEventListener("click", () => {
          const sym = stock.symbol || stock.display_symbol;
          const select = document.getElementById("stockSelector");
          if (!Array.from(select.options).some(o => o.value === sym)) {
            const tempOpt = document.createElement("option");
            tempOpt.value = sym;
            tempOpt.text = stock.display_symbol || sym;
            select.add(tempOpt);
          }
          select.value = sym;
          select.dispatchEvent(new Event('change'));
          window.scrollTo({ top: 0, behavior: 'smooth' });
        });
        epBody.appendChild(tr);
      });

      // Show metadata footer
      const scanned  = data.scanned  || '?';
      const found    = data.found    || data.ep_stocks.length;
      const ts       = data.timestamp || '';
      const footer   = document.createElement("tr");
      footer.innerHTML = `<td colspan="8" style="text-align:center;color:var(--text-muted);font-size:0.75rem;padding:0.6rem;">Found ${sanitize(String(found))} EP setups from ${sanitize(String(scanned))} stocks · ${sanitize(ts)}</td>`;
      epBody.appendChild(footer);

    } else {
      epBody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:2rem;">No Episodic Pivot setups found today. Markets may be quiet or all gaps are below threshold.</td></tr>`;
    }

  } catch(err) {
    if (epBody) {
      epBody.innerHTML = `<tr><td colspan="8" style="color:var(--accent-magenta);text-align:center;padding:20px;">Error: ${sanitize(err.message)}</td></tr>`;
    }
    console.error("EP scan fetch error:", err);
  }
}

// MULTI-TIMEFRAME RSI SCREENER
// -----------------------------------------------------------------
async function loadRsiScreenerData(force = false) {
  const rsiBody = document.getElementById("rsiScreenerBody");
  if (!rsiBody) return;

  rsiBody.innerHTML = `<tr><td colspan="5" style="text-align:center;"><div class="pulse-loader" style="color:var(--text-dim)">Scanning NSE 500 for Multi-Timeframe RSI setups...</div></td></tr>`;

  try {
    console.log("📡 Fetching RSI Screener data...");
    const forceParam = force ? "&force=true" : "";
    const fetchUrl = `${window.API_BASE}/api/screener/rsi?v=${new Date().getTime()}${forceParam}`;
    const resp = await fetchWithTimeout(fetchUrl, {
      headers: { "X-API-Key": window.SESSION_TOKEN || "" },
      cache: "no-store"
    });

    if (!resp.ok) throw new Error(`RSI screener request failed: ${resp.status}`);
    const data = await resp.json();

    if (data.rsi_stocks && data.rsi_stocks.length > 0) {
      rsiBody.innerHTML = "";
      data.rsi_stocks.forEach(stock => {
        const tr = document.createElement("tr");
        tr.style.cursor = "pointer";
        tr.innerHTML = `
          <td><strong>${sanitize(stock.display_symbol || stock.symbol)}</strong></td>
          <td style="font-family:var(--font-mono)">₹${sanitize(String(stock.price))}</td>
          <td class="text-green bold">${sanitize(String(stock.monthly_rsi))}</td>
          <td class="text-green bold">${sanitize(String(stock.weekly_rsi))}</td>
          <td class="text-magenta bold" style="color:#ff00ff;">${sanitize(String(stock.daily_rsi))}</td>
        `;
        tr.addEventListener("click", () => {
          const sym = stock.symbol || stock.display_symbol;
          const select = document.getElementById("stockSelector");
          if (!Array.from(select.options).some(o => o.value === sym)) {
            const tempOpt = document.createElement("option");
            tempOpt.value = sym;
            tempOpt.text = stock.display_symbol || sym;
            select.add(tempOpt);
          }
          select.value = sym;
          select.dispatchEvent(new Event('change'));
          window.scrollTo({ top: 0, behavior: 'smooth' });
        });
        rsiBody.appendChild(tr);
      });

      // Show metadata footer
      const scanned  = data.scanned  || '?';
      const found    = data.found    || data.rsi_stocks.length;
      const ts       = data.timestamp || '';
      const footer   = document.createElement("tr");
      footer.innerHTML = `<td colspan="5" style="text-align:center;color:var(--text-muted);font-size:0.75rem;padding:0.6rem;">Found ${sanitize(String(found))} Multi-Timeframe RSI setups from ${sanitize(String(scanned))} stocks · ${sanitize(ts)}</td>`;
      rsiBody.appendChild(footer);

    } else {
      rsiBody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:2rem;">No Multi-Timeframe RSI setups found today.</td></tr>`;
    }

  } catch(err) {
    if (rsiBody) {
      rsiBody.innerHTML = `<tr><td colspan="5" style="color:var(--accent-magenta);text-align:center;padding:20px;">Error: ${sanitize(err.message)}</td></tr>`;
    }
    console.error("RSI scan fetch error:", err);
  }
}

// -----------------------------------------------------------------
// MOMENTUM SCREENER
// -----------------------------------------------------------------
async function loadMomentumScreenerData(force = false) {
  const momentumBody = document.getElementById("momentumScreenerBody");
  if (!momentumBody) return;

  momentumBody.innerHTML = `<tr><td colspan="6" style="text-align:center;"><div class="pulse-loader" style="color:var(--text-dim)">Scanning NSE 500 for Momentum setups...</div></td></tr>`;

  try {
    console.log("📡 Fetching Momentum Screener data...");
    const forceParam = force ? "&force=true" : "";
    const fetchUrl = `${window.API_BASE}/api/screener/momentum?v=${new Date().getTime()}${forceParam}`;
    const resp = await fetchWithTimeout(fetchUrl, {
      headers: { "X-API-Key": window.SESSION_TOKEN || "" },
      cache: "no-store"
    });

    if (!resp.ok) throw new Error(`Momentum screener request failed: ${resp.status}`);
    const data = await resp.json();

    if (data.momentum_stocks && data.momentum_stocks.length > 0) {
      momentumBody.innerHTML = "";
      data.momentum_stocks.forEach(stock => {
        const tr = document.createElement("tr");
        tr.style.cursor = "pointer";
        
        const histColor = stock.macd_hist >= 0 ? "text-green" : "text-red";
        const volColor = stock.vol_ratio >= 2.0 ? "text-green bold" : (stock.vol_ratio >= 1.5 ? "text-green" : "text-amber");

        const sessionsList = stock.passed_sessions || ["Today"];
        const sessionsHtml = sessionsList
          .map(s => {
            const cls = s === "Today" ? "passed-session-tag today" : "passed-session-tag";
            return `<span class="${cls}">${sanitize(s)}</span>`;
          })
          .join("");

        const newBadge = stock.is_new_addition 
          ? `<span class="badge-new" style="margin-left:8px;">New</span>` 
          : "";

        tr.innerHTML = `
          <td>
            <div style="display:flex; flex-direction:column; gap:4px;">
              <div style="display:flex; align-items:center;">
                <strong>${sanitize(stock.display_symbol || stock.symbol)}</strong>
                ${newBadge}
              </div>
              <div style="display:flex; flex-wrap:wrap; gap:2px;">
                ${sessionsHtml}
              </div>
            </div>
          </td>
          <td style="font-family:var(--font-mono)">₹${sanitize(String(stock.close))}</td>
          <td class="text-green bold">+${sanitize(String(stock.pct_above_ema))}%</td>
          <td class="text-magenta">${sanitize(String(stock.rsi))}</td>
          <td class="${histColor}">${sanitize(String(stock.macd_hist))}</td>
          <td class="${volColor}">${sanitize(String(stock.vol_ratio))}x</td>
        `;
        tr.addEventListener("click", () => {
          const sym = stock.symbol || stock.display_symbol;
          const select = document.getElementById("stockSelector");
          if (!Array.from(select.options).some(o => o.value === sym)) {
            const tempOpt = document.createElement("option");
            tempOpt.value = sym;
            tempOpt.text = stock.display_symbol || sym;
            select.add(tempOpt);
          }
          select.value = sym;
          select.dispatchEvent(new Event('change'));
          window.scrollTo({ top: 0, behavior: 'smooth' });
        });
        momentumBody.appendChild(tr);
      });

      // Show metadata footer
      const scanned  = data.scanned  || '?';
      const found    = data.found    || data.momentum_stocks.length;
      const ts       = data.timestamp || '';
      const footer   = document.createElement("tr");
      footer.innerHTML = `<td colspan="6" style="text-align:center;color:var(--text-muted);font-size:0.75rem;padding:0.6rem;">Found ${sanitize(String(found))} Momentum setups from ${sanitize(String(scanned))} stocks · ${sanitize(ts)}</td>`;
      momentumBody.appendChild(footer);

    } else {
      momentumBody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:2rem;">No Momentum setups found today.</td></tr>`;
    }

  } catch(err) {
    if (momentumBody) {
      momentumBody.innerHTML = `<tr><td colspan="6" style="color:var(--accent-magenta);text-align:center;padding:20px;">Error: ${sanitize(err.message)}</td></tr>`;
    }
    console.error("Momentum scan fetch error:", err);
  }
}

// -----------------------------------------------------------------
// PERFECT FLAG SCREENER
// -----------------------------------------------------------------
async function loadFlagScreenerData(force = false) {
  const flagBody = document.getElementById("flagScreenerBody");
  if (!flagBody) return;

  flagBody.innerHTML = `<tr><td colspan="6" style="text-align:center;"><div class="pulse-loader" style="color:var(--text-dim)">Scanning NSE 500 for Perfect Flag patterns...</div></td></tr>`;

  try {
    console.log("📡 Fetching Flag Screener data...");
    const forceParam = force ? "&force=true" : "";
    const fetchUrl = `${window.API_BASE}/api/screener/flag?v=${new Date().getTime()}${forceParam}`;
    const resp = await fetchWithTimeout(fetchUrl, {
      headers: { "X-API-Key": window.SESSION_TOKEN || "" },
      cache: "no-store"
    });

    if (!resp.ok) throw new Error(`Flag screener request failed: ${resp.status}`);
    const data = await resp.json();

    if (data.flag_stocks && data.flag_stocks.length > 0) {
      flagBody.innerHTML = "";
      data.flag_stocks.forEach(stock => {
        const tr = document.createElement("tr");
        tr.style.cursor = "pointer";
        
        const scoreColor = stock.score >= 80 ? "text-green bold" : (stock.score >= 60 ? "text-cyan" : "text-amber");

        tr.innerHTML = `
          <td><strong>${sanitize(stock.symbol)}</strong></td>
          <td style="font-family:var(--font-mono)">₹${sanitize(String(stock.price))}</td>
          <td class="${scoreColor}">${sanitize(String(stock.score))}</td>
          <td class="text-green">${sanitize(String(stock.gain_pct))}%</td>
          <td class="text-amber">${sanitize(String(stock.depth_pct))}%</td>
          <td>${sanitize(stock.rating)}</td>
        `;
        tr.addEventListener("click", () => {
          const sym = stock.symbol;
          const select = document.getElementById("stockSelector");
          if (!Array.from(select.options).some(o => o.value === sym)) {
            const tempOpt = document.createElement("option");
            tempOpt.value = sym;
            tempOpt.text = sym;
            select.add(tempOpt);
          }
          select.value = sym;
          select.dispatchEvent(new Event('change'));
          window.scrollTo({ top: 0, behavior: 'smooth' });
        });
        flagBody.appendChild(tr);
      });

      // Show metadata footer
      const ts = data.timestamp || '';
      const footer = document.createElement("tr");
      footer.innerHTML = `<td colspan="6" style="text-align:center;color:var(--text-muted);font-size:0.75rem;padding:0.6rem;">Found ${sanitize(String(data.flag_stocks.length))} Flag setups · ${sanitize(ts)}</td>`;
      flagBody.appendChild(footer);

    } else {
      flagBody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:2rem;">No Perfect Flag patterns found today.</td></tr>`;
    }

  } catch(err) {
    if (flagBody) {
      flagBody.innerHTML = `<tr><td colspan="6" style="color:var(--accent-magenta);text-align:center;padding:20px;">Error: ${sanitize(err.message)}</td></tr>`;
    }
    console.error("Flag scan fetch error:", err);
  }
}


// -----------------------------------------------------------------
// DROPDOWN LOAD
// -----------------------------------------------------------------
async function loadNse500Stocks() {
  const stockSelector = document.getElementById("stockSelector");
  if (!stockSelector) return;
  
  try {
    const fetchUrl = `${window.API_BASE}/api/market/nse500?v=${new Date().getTime()}`;

    const resp = await fetch(fetchUrl, {
      headers: { "X-API-Key": window.SESSION_TOKEN || "" },
      cache: "no-store"
    });
    
    if (!resp.ok) throw new Error(`Could not fetch stock list: ${resp.status}`);
    const data = await resp.json();
    
    const nifty500Group = document.getElementById("nifty500Group");
    const midcap150Group = document.getElementById("midcap150Group");
    const smallcap250Group = document.getElementById("smallcap250Group");
    const microcap250Group = document.getElementById("microcap250Group");
    
    if (nifty500Group) nifty500Group.innerHTML = "";
    if (midcap150Group) midcap150Group.innerHTML = "";
    if (smallcap250Group) smallcap250Group.innerHTML = "";
    if (microcap250Group) microcap250Group.innerHTML = "";
    
    // Fallback: if backend returns old format, populate nifty500Group with everything
    if (data && data.symbols && !data.nifty500) {
      data.symbols.forEach(symbol => {
         const option = document.createElement("option");
         option.value = symbol;
         option.text = symbol;
         if (nifty500Group) {
           nifty500Group.appendChild(option);
         } else {
           stockSelector.add(option);
         }
      });
      console.log(`Fallback: Loaded ${data.symbols.length} stocks into Nifty 500 Equities.`);
      return;
    }

    // Populate each group
    const populateGroup = (groupEl, symbols) => {
      if (groupEl && symbols) {
        symbols.forEach(symbol => {
          const option = document.createElement("option");
          option.value = symbol;
          option.text = symbol;
          groupEl.appendChild(option);
        });
      }
    };

    populateGroup(nifty500Group, data.nifty500);
    populateGroup(midcap150Group, data.midcap150);
    populateGroup(smallcap250Group, data.smallcap250);
    populateGroup(microcap250Group, data.microcap250);

    const totalLoaded = (data.nifty500?.length || 0) + (data.midcap150?.length || 0) + (data.smallcap250?.length || 0) + (data.microcap250?.length || 0);
    console.log(`Successfully loaded ${totalLoaded} stocks across 4 index categories.`);
  } catch (e) {
    console.error("Failed to load stocks list", e);
  }
}

async function loadMarketOverview(category = 'nifty50', force = false) {
  try {
    const forceParam = force ? "&force=true" : "";
    const fetchUrl = `${window.API_BASE}/api/market/overview?category=${category}&v=${new Date().getTime()}${forceParam}`;

    const resp = await fetch(fetchUrl, {
      headers: { "X-API-Key": window.SESSION_TOKEN || "" },
      cache: "no-store"
    });
    
    if (!resp.ok) throw new Error(`Could not fetch market overview: ${resp.status}`);
    const data = await resp.json();

    renderMarketOverview(data);
  } catch (e) {
    console.error("Failed to load market overview", e);
    const errText = `Error: ${e.message || e}`;
    const indicesRow = document.getElementById("indicesRow");
    if (indicesRow) indicesRow.innerHTML = `<div style="color: red; padding: 20px;">${sanitize(errText)}</div>`;
    
    const gainersBody = document.getElementById("gainersTableBody");
    if (gainersBody) gainersBody.innerHTML = `<tr><td colspan="3" style="color:red; text-align:center;">${sanitize(errText)}</td></tr>`;
    
    const losersBody = document.getElementById("losersTableBody");
    if (losersBody) losersBody.innerHTML = `<tr><td colspan="3" style="color:red; text-align:center;">${sanitize(errText)}</td></tr>`;
  }
}

function renderMarketOverview(data) {
  // Render Indices
  const indicesRow = document.getElementById("indicesRow");
  if (data.indices && data.indices.length > 0 && indicesRow) {
    indicesRow.innerHTML = "";
    data.indices.forEach(idx => {
      const isUp = idx.change_pct >= 0;
      const changeClass = isUp ? "up" : "down";
      const sign = isUp ? "+" : "";
      
      const card = document.createElement("div");
      card.className = "index-card";
      card.innerHTML = `
        <div class="index-name">${sanitize(idx.name)}</div>
        <div class="index-price-wrap">
          <div class="index-price">${sanitize(fmt(idx.price))}</div>
          <div class="index-change ${sanitize(changeClass)}">${sanitize(sign)}${(idx.change_pct != null ? idx.change_pct.toFixed(2) : '0.00')}%</div>
        </div>
        <div class="idx-range">
          <span>L: ${sanitize(fmt(idx.low).replace(/₹/, ''))}</span>
          <span>H: ${sanitize(fmt(idx.high).replace(/₹/, ''))}</span>
        </div>
      `;
      card.style.cursor = "pointer";
      card.addEventListener("click", () => {
         const select = document.getElementById("stockSelector");
         if (!Array.from(select.options).some(o => o.value === idx.symbol)) {
           const tempOpt = document.createElement("option");
           tempOpt.value = idx.symbol;
           tempOpt.text = idx.symbol;
           select.add(tempOpt);
         }
         select.value = idx.symbol;
         select.dispatchEvent(new Event('change'));
         window.scrollTo({ top: 0, behavior: 'smooth' });
      });
      indicesRow.appendChild(card);
    });
  } else if (indicesRow) {
    indicesRow.innerHTML = `<div>No indices data available</div>`;
  }

  // Render Top Gainers
  const gainersBody = document.getElementById("gainersTableBody");
  if (data.top_gainers && data.top_gainers.length > 0 && gainersBody) {
    gainersBody.innerHTML = "";
    data.top_gainers.forEach(g => {
      const tr = document.createElement("tr");
      tr.style.cursor = "pointer";
      tr.innerHTML = `
        <td><strong>${sanitize(g.symbol)}</strong></td>
        <td>${sanitize(fmt(g.price))}</td>
        <td class="text-green">${g.change_pct >= 0 ? '+' : ''}${(g.change_pct != null ? g.change_pct.toFixed(2) : '0.00')}%</td>
      `;
      tr.addEventListener("click", () => {
         const select = document.getElementById("stockSelector");
         if (!Array.from(select.options).some(o => o.value === g.symbol)) {
           const tempOpt = document.createElement("option");
           tempOpt.value = g.symbol;
           tempOpt.text = g.symbol;
           select.add(tempOpt);
         }
         select.value = g.symbol;
         select.dispatchEvent(new Event('change'));
         window.scrollTo({ top: 0, behavior: 'smooth' });
      });
      gainersBody.appendChild(tr);
    });
  }
  // Render Top Losers
  const losersBody = document.getElementById("losersTableBody");
  if (data.top_losers && data.top_losers.length > 0 && losersBody) {
    losersBody.innerHTML = "";
    data.top_losers.forEach(l => {
      const tr = document.createElement("tr");
      tr.style.cursor = "pointer";
      tr.innerHTML = `
        <td><strong>${sanitize(l.symbol)}</strong></td>
        <td>${sanitize(fmt(l.price))}</td>
        <td class="text-red">${l.change_pct > 0 ? '+' : ''}${(l.change_pct != null ? l.change_pct.toFixed(2) : '0.00')}%</td>
      `;
      tr.addEventListener("click", () => {
         const select = document.getElementById("stockSelector");
         if (!Array.from(select.options).some(o => o.value === l.symbol)) {
           const tempOpt = document.createElement("option");
           tempOpt.value = l.symbol;
           tempOpt.text = l.symbol;
           select.add(tempOpt);
         }
         select.value = l.symbol;
         select.dispatchEvent(new Event('change'));
         window.scrollTo({ top: 0, behavior: 'smooth' });
      });
      losersBody.appendChild(tr);
    });
  } else if (losersBody) {
    losersBody.innerHTML = `<tr><td colspan="3" style="text-align:center;">No losers data available</td></tr>`;
  }

  // Render Sector Distribution
  const sectorBody = document.getElementById("sectorDistributionBody");
  if (sectorBody) {
    if (data.sector_distribution && data.sector_distribution.length > 0) {
      sectorBody.innerHTML = "";
      data.sector_distribution.slice(0, 10).forEach(sec => {
        const item = document.createElement("div");
        item.style.display = "flex";
        item.style.flexDirection = "column";
        item.style.gap = "5px";
        item.style.marginBottom = "10px";
        item.style.padding = "6px 8px";
        item.style.background = "rgba(255, 255, 255, 0.02)";
        item.style.borderRadius = "6px";
        item.style.border = "1px solid rgba(255, 255, 255, 0.04)";
        
        const pct = sec.percentage;
        const change = sec.change || 0.0;
        const changeClass = change >= 0 ? "text-green" : "text-red";
        const sign = change > 0 ? "+" : "";
        
        let flowBadgeHtml = "";
        if (sec.flow === "Smart Money In") {
          flowBadgeHtml = `<span style="background:rgba(0,230,118,0.1); color:#00e676; border:1px solid rgba(0,230,118,0.3); padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em;">🔥 Smart Money In</span>`;
        } else if (sec.flow === "Smart Money Out") {
          flowBadgeHtml = `<span style="background:rgba(255,23,68,0.1); color:#ff1744; border:1px solid rgba(255,23,68,0.3); padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em;">⚠️ Smart Money Out</span>`;
        } else if (sec.flow === "Positive Flow") {
          flowBadgeHtml = `<span style="background:rgba(6,182,212,0.08); color:var(--accent-cyan); border:1px solid rgba(6,182,212,0.2); padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em;">Accumulating</span>`;
        } else if (sec.flow === "Negative Flow") {
          flowBadgeHtml = `<span style="background:rgba(236,72,153,0.08); color:var(--accent-magenta); border:1px solid rgba(236,72,153,0.2); padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em;">Softening</span>`;
        } else {
          flowBadgeHtml = `<span style="background:rgba(255,255,255,0.03); color:var(--text-muted); border:1px solid rgba(255,255,255,0.06); padding: 1px 5px; border-radius: 4px; font-size: 0.65rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.03em;">Neutral</span>`;
        }
        
        item.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.8rem;">
            <span style="font-weight:600; color:var(--text-main); max-width: 60%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${sanitize(sec.sector)}">${sanitize(sec.sector)}</span>
            <div style="display:flex; align-items:center; gap:8px;">
              <span class="${changeClass}" style="font-family:var(--font-mono); font-weight:700;">${sign}${change.toFixed(2)}%</span>
              ${flowBadgeHtml}
            </div>
          </div>
          <div style="display:flex; justify-content:space-between; font-size:0.72rem; color:var(--text-dim); margin-top: 2px;">
            <span>Weight: ${sanitize(String(sec.count))} stocks (${sanitize(pct.toFixed(1))}%)</span>
            <span style="font-family:var(--font-mono);">Vol Ratio: ${sec.vol_ratio.toFixed(2)}x</span>
          </div>
          <div style="background:rgba(255,255,255,0.05); height:4px; border-radius:2px; overflow:hidden; width:100%; margin-top:2px;">
            <div style="background:linear-gradient(90deg, var(--accent-blue), var(--accent-cyan)); height:100%; width:${pct}%; border-radius:2px;"></div>
          </div>
        `;
        sectorBody.appendChild(item);
      });
    } else {
      sectorBody.innerHTML = `<div style="text-align:center;color:var(--text-muted);padding:2rem;">No sector distribution data available</div>`;
    }
  }
}

function renderDashboard(data) {
  hideOverlay("loadingOverlay");
  hideOverlay("errorOverlay");
  document.getElementById("dashboardEl").style.display = "block";
  
  // Hero section
  document.getElementById("heroSymbol").textContent = (data.symbol || "").replace(/%5E/i, "^");
  document.getElementById("heroName").textContent = data.name || "N/A";
  document.getElementById("heroSector").textContent = `${data.sector || "N/A"} • ${data.industry || "N/A"}`;
  
  const currentPrice = data.price || data.current_price || data.regular_market_price || 0;
  const previousClose = data.previous_close || 0;
  const change = currentPrice - previousClose;
  const changePct = previousClose ? (change / previousClose * 100) : 0;
  
  document.getElementById("heroPrice").textContent = fmt(currentPrice);
  
  const changeEl = document.getElementById("heroChange");
  changeEl.className = `hero-change ${change >= 0 ? "up" : "down"}`;
  changeEl.textContent = `${change >= 0 ? "▲" : "▼"} ${fmtChange(change)} (${fmtPct(changePct)})`;
  
  renderChart(data);
  renderMetrics(data);
  renderTechGrid(data);
  renderMultiRSI(data);
  renderVolatility(data);
  renderFinancials(data);
  renderHistoricalFinancials(data);
  renderFundamentals(data);
  renderPivotGrid(data);
  renderExtremes(data);
  renderRelativeStrength(data);
  renderOptionsData(data);
  renderPerformance(data);
  renderTrendTemplate(data);
  
  // New: TA Explorer
  currentTaData = data.technical_indicators || null;
  const taSelect = document.getElementById("taIndicatorSelect");
  if (taSelect) {
    renderTaDetails(taSelect.value);
  }
}

// ─── CANDLESTICK CHART WITH EMA OVERLAYS ─────────────────────────────────────
function renderChart(data) {
  const chartData = data.chart || {};
  const dates   = chartData.dates   || [];
  const opens   = chartData.opens   || [];
  const highs   = chartData.highs   || [];
  const lows    = chartData.lows    || [];
  const closes  = chartData.closes  || [];
  const ema20   = chartData.ema20   || [];
  const ema50   = chartData.ema50   || [];
  const ema200  = chartData.ema200  || [];

  // Destroy previous chart
  if (chartInstance) { try { chartInstance.destroy(); } catch(_){} chartInstance = null; }
  const existing = Chart.getChart('candlestickChart') || Chart.getChart('mainChart');
  if (existing) try { existing.destroy(); } catch(_) {}

  const hasOHLC = opens.length > 0 && highs.length > 0 && lows.length > 0;

  // --- Detect candlestick controller via Chart's registry ---
  let hasCandlestick = false;
  if (typeof Chart !== 'undefined') {
    // CDN UMD build auto-registers; also try manual registration if globals exist
    if (window.CandlestickController) {
      try { Chart.register(window.CandlestickController, window.OhlcController, window.CandlestickElement, window.OhlcElement); } catch(_) {}
    }
    // Actually check if the type is registered
    try {
      hasCandlestick = !!Chart.registry.controllers.get('candlestick');
    } catch(_) {
      hasCandlestick = false;
    }
  }
  console.log(`📊 Candlestick plugin registered: ${hasCandlestick}, hasOHLC: ${hasOHLC}`);

  // Format x-axis labels (for line chart fallback)
  const labels = dates.map(d => {
    const dt = new Date(d);
    return dt.toLocaleDateString('en-IN', { month: 'short', day: 'numeric' });
  });

  const tooltipDefaults = {
    backgroundColor: 'rgba(10, 12, 28, 0.96)',
    titleColor: '#607d8b',
    bodyColor: '#e8eaf6',
    borderColor: 'rgba(0, 229, 255, 0.3)',
    borderWidth: 1,
    padding: 14,
    displayColors: true,
  };

  const scalesDefaults = {
    x: {
      type: 'timeseries',
      offset: true,
      grid: { display: false, color: 'rgba(255,255,255,0.02)' },
      ticks: { 
        maxTicksLimit: 8, 
        color: '#607d8b', 
        font: { size: 10 },
        source: 'data',
        maxRotation: 0,
        autoSkip: true,
      }
    },
    y: {
      position: 'right',
      grid: { color: 'rgba(255,255,255,0.04)' },
      ticks: { 
        color: '#90a4ae', 
        font: { size: 10 },
        callback: v => '₹' + v.toLocaleString('en-IN') 
      }
    }
  };

  // Build timestamped data arrays (shared by both paths)
  const ohlcData = dates.map((d, i) => ({
    x: new Date(d).getTime(),
    o: opens[i],
    h: highs[i],
    l: lows[i],
    c: closes[i]
  }));
  const ema20Data = dates.map((d, i) => ({ x: new Date(d).getTime(), y: ema20[i] })).filter(p => p.y != null);
  const ema50Data = dates.map((d, i) => ({ x: new Date(d).getTime(), y: ema50[i] })).filter(p => p.y != null);
  const ema200Data = dates.map((d, i) => ({ x: new Date(d).getTime(), y: ema200[i] })).filter(p => p.y != null);

  const emaDatasets = [
    { label: 'EMA 20',  data: ema20Data,  type: 'line', borderColor: '#ff9100', borderWidth: 1.2, pointRadius: 0, fill: false, tension: 0.1, order: 1 },
    { label: 'EMA 50',  data: ema50Data,  type: 'line', borderColor: '#00e5ff', borderWidth: 1.2, pointRadius: 0, fill: false, tension: 0.1, order: 1 },
    { label: 'EMA 200', data: ema200Data, type: 'line', borderColor: '#d32f2f', borderWidth: 1.2, borderDash: [4,4], pointRadius: 0, fill: false, tension: 0.1, order: 1 },
  ];

  if (hasCandlestick && hasOHLC) {
    // ── True Candlestick Chart ──────────────────────────
    const candlestickCtx = document.getElementById('candlestickChart');
    if (!candlestickCtx) return;
    const ctx = candlestickCtx.getContext('2d');

    try {
      chartInstance = new Chart(ctx, {
        type: 'candlestick',
        data: {
          datasets: [
            {
              label: 'OHLC',
              data: ohlcData,
              // chartjs-chart-financial v0.2.x color API
              color: {
                up: 'rgba(0, 230, 118, 0.85)',
                down: 'rgba(255, 23, 68, 0.85)',
                unchanged: 'rgba(144, 164, 174, 0.85)'
              },
              borderColor: {
                up: '#00e676',
                down: '#ff1744',
                unchanged: '#90a4ae'
              },
              order: 0,
            },
            ...emaDatasets
          ]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: { legend: { display: false }, tooltip: tooltipDefaults },
          scales: scalesDefaults
        }
      });
      console.log('✅ Candlestick chart rendered successfully');
      return; // Success — skip fallback
    } catch(chartErr) {
      console.error('⚠️ Candlestick chart failed, falling back to line chart:', chartErr);
      // Fall through to line chart
      if (chartInstance) { try { chartInstance.destroy(); } catch(_){} chartInstance = null; }
    }
  }

  // ── Fallback: Line Close + EMA lines ──────────────────
  const canvasId = document.getElementById('candlestickChart') ? 'candlestickChart' : 'mainChart';
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const startP = closes[0] || 0;
  const endP   = closes[closes.length - 1] || 0;
  const isUp   = endP >= startP;
  const lineColor = isUp ? '#00e676' : '#ff003c';
  const gradStart = isUp ? 'rgba(0,230,118,0.35)' : 'rgba(255,0,60,0.35)';

  const ctx = canvas.getContext('2d');
  const gradient = ctx.createLinearGradient(0, 0, 0, 380);
  gradient.addColorStop(0, gradStart);
  gradient.addColorStop(1, 'rgba(4,4,12,0)');

  chartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Close', data: closes,
          borderColor: lineColor, backgroundColor: gradient,
          borderWidth: 2, pointRadius: 0, pointHoverRadius: 5,
          fill: true, tension: 0.2
        },
        {
          label: 'EMA 20', data: ema20,
          borderColor: '#ff9100', borderWidth: 1.5,
          pointRadius: 0, fill: false, tension: 0.3
        },
        {
          label: 'EMA 50', data: ema50,
          borderColor: '#00e5ff', borderWidth: 1.5,
          pointRadius: 0, fill: false, tension: 0.3
        },
        {
          label: 'EMA 200', data: ema200,
          borderColor: '#ff003c', borderWidth: 1.5,
          borderDash: [4, 4],
          pointRadius: 0, fill: false, tension: 0.3
        }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: false }, tooltip: tooltipDefaults },
      scales: scalesDefaults
    }
  });
  console.log('📉 Rendered fallback line chart');
}

// ─── TREND TEMPLATE CHECKLIST ─────────────────────────────────────────────────
function renderTrendTemplate(data) {
  const container = document.getElementById('trendTemplateContainer');
  if (!container) return;

  const tt = data.trend_template;
  if (!tt) {
    container.innerHTML = '<div style="color:var(--text-muted);font-size:0.85rem;text-align:center;padding:2rem;">Trend Template data not available (indices only have technical criteria).</div>';
    return;
  }

  const { checks, passed, total, score_pct } = tt;
  const scoreClass = score_pct >= 70 ? 'strong' : score_pct >= 40 ? 'medium' : 'weak';
  const scoreLabel = score_pct >= 70 ? '🔥 Strong Setup' : score_pct >= 40 ? '⚡ Approaching' : '⚠ Weak Setup';

  // Group checks by group
  const grouped = {};
  (checks || []).forEach(c => {
    if (!grouped[c.group]) grouped[c.group] = [];
    grouped[c.group].push(c);
  });

  const groups = ['Technical', 'Fundamental', 'Other'];

  const groupIcons = {
    'Technical':    '📈',
    'Fundamental':  '💰',
    'Other':        '🔍'
  };

  let innerHtml = `
    <div class="trend-template-header">
      <div class="trend-template-icon">
        <svg viewBox="0 0 24 24"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>
      </div>
      <div>
        <div class="trend-template-title">Trend Template</div>
        <div class="trend-template-subtitle">Minervini / Weinstein Criteria — ${passed}/${total} passed</div>
      </div>
      <div class="trend-score-badge ${sanitize(scoreClass)}">${score_pct}% <span style="font-size:0.65rem;display:block;text-align:center;font-weight:500;margin-top:2px;">${sanitize(scoreLabel)}</span></div>
    </div>
    <div class="checklist-groups">`;

  groups.forEach(grp => {
    const items = grouped[grp];
    if (!items || items.length === 0) return;
    innerHtml += `<div class="checklist-group"><div class="checklist-group-title">${groupIcons[grp] || ''} ${sanitize(grp)}</div>`;
    items.forEach(c => {
      const iconClass = c.pass === true ? 'pass' : c.pass === false ? 'fail' : 'pending';
      const icon      = c.pass === true ? '✓'   : c.pass === false ? '✗'   : '–';
      innerHtml += `
        <div class="checklist-item">
          <div class="check-icon ${sanitize(iconClass)}">${icon}</div>
          <div class="checklist-text">${sanitize(c.label)}</div>
          <div class="checklist-value bold-val">${sanitize(c.value || '')}</div>
        </div>`;
    });
    innerHtml += '</div>';
  });

  innerHtml += '</div>';
  container.innerHTML = innerHtml;
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
  grid.innerHTML = ""; // Clear existing
  metrics.forEach(m => {
    const card = document.createElement("div");
    card.className = "metric-card";
    
    const label = document.createElement("div");
    label.className = "metric-label";
    label.textContent = m.label;
    
    const value = document.createElement("div");
    value.className = `metric-value ${m.klass || ""}`;
    value.textContent = m.value.replace(/^₹/, "");
    
    card.appendChild(label);
    card.appendChild(value);
    grid.appendChild(card);
  });
}

function renderTechGrid(data) {
  // Mini cards for RSI, MACD, Signal
  const rsi = data.rsi ? data.rsi.daily : null;
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

  const current = data.price || data.current_price || data.regular_market_price || 0;
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
  const isIndex = data.sector === "Index" || !("financials_revenue" in data);
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

function renderHistoricalFinancials(data) {
  const tbody = document.getElementById("historicalFinancialsBody");
  const box = document.getElementById("historicalFinancialsBox");
  if (!tbody || !box) return;
  
  const yearly = data.financials_yearly;
  if (!yearly || yearly.length === 0) {
    box.style.display = "none";
    return;
  }
  
  box.style.display = "block";
  
  for (let i = 0; i < 4; i++) {
    const th = document.getElementById(`year${i}Header`);
    if (th) {
      if (yearly[i] && yearly[i].year) {
         th.textContent = yearly[i].year;
      } else {
         th.textContent = `Past Year ${i}`;
      }
    }
  }

  const opmArr = [];
  const salesGrowthArr = [];
  const netProfitArr = [];
  
  for (let i = 0; i < 4; i++) {
    const yData = yearly[i];
    if (!yData) {
      opmArr.push("-");
      salesGrowthArr.push("-");
      netProfitArr.push("-");
      continue;
    }
    
    // OPM
    let opm = "-";
    if (yData.revenue && yData.operating_income) {
      opm = ((yData.operating_income / yData.revenue) * 100).toFixed(2) + "%";
    }
    opmArr.push(opm);
    
    // Net Profit
    let np = yData.net_income ? fmtMktCap(yData.net_income) : "-";
    netProfitArr.push(np);
    
    // Sales Growth
    let sg = "-";
    const prevYearData = yearly[i+1];
    if (yData.revenue && prevYearData && prevYearData.revenue) {
      const growth = ((yData.revenue - prevYearData.revenue) / prevYearData.revenue) * 100;
      sg = growth.toFixed(2) + "%";
    }
    salesGrowthArr.push(sg);
  }
  
  const html = `
    <tr style="border-bottom: 1px solid rgba(255,255,255,0.04);">
      <td style="padding: 10px; font-weight: 500;">OPM (%)</td>
      <td style="padding: 10px; font-family: var(--font-mono);">${opmArr[0]}</td>
      <td style="padding: 10px; font-family: var(--font-mono);">${opmArr[1]}</td>
      <td style="padding: 10px; font-family: var(--font-mono);">${opmArr[2]}</td>
      <td style="padding: 10px; font-family: var(--font-mono);">${opmArr[3]}</td>
    </tr>
    <tr style="border-bottom: 1px solid rgba(255,255,255,0.04);">
      <td style="padding: 10px; font-weight: 500;">Sales Growth (%)</td>
      <td style="padding: 10px; font-family: var(--font-mono);" class="${salesGrowthArr[0].startsWith('-') ? 'text-down' : (salesGrowthArr[0] !== '-' ? 'text-up' : '')}">${salesGrowthArr[0]}</td>
      <td style="padding: 10px; font-family: var(--font-mono);" class="${salesGrowthArr[1].startsWith('-') ? 'text-down' : (salesGrowthArr[1] !== '-' ? 'text-up' : '')}">${salesGrowthArr[1]}</td>
      <td style="padding: 10px; font-family: var(--font-mono);" class="${salesGrowthArr[2].startsWith('-') ? 'text-down' : (salesGrowthArr[2] !== '-' ? 'text-up' : '')}">${salesGrowthArr[2]}</td>
      <td style="padding: 10px; font-family: var(--font-mono);" class="${salesGrowthArr[3].startsWith('-') ? 'text-down' : (salesGrowthArr[3] !== '-' ? 'text-up' : '')}">${salesGrowthArr[3]}</td>
    </tr>
    <tr>
      <td style="padding: 10px; font-weight: 500;">Net Profit</td>
      <td style="padding: 10px; font-family: var(--font-mono);">${netProfitArr[0]}</td>
      <td style="padding: 10px; font-family: var(--font-mono);">${netProfitArr[1]}</td>
      <td style="padding: 10px; font-family: var(--font-mono);">${netProfitArr[2]}</td>
      <td style="padding: 10px; font-family: var(--font-mono);">${netProfitArr[3]}</td>
    </tr>
  `;
  
  tbody.innerHTML = html;
}

function renderMultiRSI(data) {
  const box = document.getElementById("rsiGridBox");
  if (!data.rsi) {
    box.style.display = "none";
    return;
  }
  box.style.display = "block";

  const renderCard = (elementId, title, rsiValue) => {
    let rsiColor = "var(--text-main)", rsiSignal = "NEUTRAL", rsiClass = "neutral";
    if (rsiValue !== null && rsiValue !== undefined) {
      if (rsiValue > 70) { rsiColor = "var(--negative)"; rsiSignal = "OVERBOUGHT"; rsiClass = "bearish"; }
      else if (rsiValue < 30) { rsiColor = "var(--positive)"; rsiSignal = "OVERSOLD"; rsiClass = "bullish"; }
    }
    const rsiFillPct = (rsiValue !== null && rsiValue !== undefined) ? Math.min(Math.max(rsiValue, 0), 100) : 50;

    const el = document.getElementById(elementId);
    if(el) {
      el.innerHTML = `
        <div class="indicator-label">${sanitize(title)}</div>
        <div class="indicator-val-primary" style="color:${sanitize(rsiColor)}">${(rsiValue !== null && rsiValue !== undefined) ? rsiValue.toFixed(1) : "N/A"}</div>
        <div class="rsi-track">
          <div class="rsi-fill" style="width:${rsiFillPct}%; background:${sanitize(rsiColor)}"></div>
        </div>
        <div class="signal-badge ${sanitize(rsiClass)}">${sanitize(rsiSignal)}</div>
      `;
    }
  };

  renderCard("rsiDailyCard", "Daily RSI", data.rsi ? data.rsi.daily : null);
  renderCard("rsiWeeklyCard", "Weekly RSI", data.rsi ? data.rsi.weekly : null);
  renderCard("rsiMonthlyCard", "Monthly RSI", data.rsi ? data.rsi.monthly : null);
}

function renderVolatility(data) {
  const box = document.getElementById("volatilityBox");
  const ti = data.technical_indicators || {};
  const vol = {
    adx: ti.adx?.adx,
    adx_pos: ti.adx?.pos,
    adx_neg: ti.adx?.neg,
    bb_high: ti.bollinger?.high,
    bb_mid: ti.bollinger?.mid,
    bb_low: ti.bollinger?.low
  };
  
  if (!ti.adx || !box) {
      if (box) box.style.display = "none";
      return;
  }
  box.style.display = "block";

  // ADX Card
  const adx = vol.adx;
  let adxColor = "var(--text-main)", adxSignal = "WEAK TREND", adxClass = "neutral";
  if (adx !== null && adx !== undefined) {
    if (adx > 50) { adxColor = "var(--accent-gold)"; adxSignal = "EXTREME TREND"; adxClass = "bullish"; }
    else if (adx > 25) { adxColor = "var(--accent-cyan)"; adxSignal = "STRONG TREND"; adxClass = "bullish"; }
    else if (adx < 20) { adxColor = "var(--text-muted)"; adxSignal = "SIDEWAYS"; adxClass = "neutral"; }
  }
  
  const adxCard = document.getElementById("adxCard");
  if (adxCard) {
    adxCard.innerHTML = `
      <div class="indicator-label">ADX Trend Strength</div>
      <div class="indicator-val-primary" style="color:${sanitize(adxColor)}">${(adx !== null && adx !== undefined) ? adx.toFixed(1) : "N/A"}</div>
      <div class="signal-badge ${sanitize(adxClass)}">${sanitize(adxSignal)}</div>
    `;
  }

  // BB Card
  const current = data.price || 0;
  const bbHigh = vol.bb_high;
  const bbLow = vol.bb_low;
  let bbSignal = "NEUTRAL", bbClass = "neutral", bbColor = "var(--text-main)";
  
  if (current && bbHigh && current >= bbHigh) { bbSignal = "OVEREXTENDED"; bbClass = "bearish"; bbColor = "var(--negative)"; }
  else if (current && bbLow && current <= bbLow) { bbSignal = "OVERSOLD"; bbClass = "bullish"; bbColor = "var(--positive)"; }

  const bbCard = document.getElementById("bbCard");
  if (bbCard) {
    bbCard.innerHTML = `
      <div class="indicator-label">Bollinger Bands</div>
      <div class="indicator-val-primary" style="color:${sanitize(bbColor)}">${current > 0 ? "BB" : "N/A"}</div>
      <div class="signal-badge ${sanitize(bbClass)}">${sanitize(bbSignal)}</div>
    `;
  }

  const items = [
    { label: "ADX (Trend)", value: vol.adx },
    { label: "+DI (Bull)", value: vol.adx_pos, klass: "text-up" },
    { label: "-DI (Bear)", value: vol.adx_neg, klass: "text-down" },
    { label: "BB Upper", value: fmt(vol.bb_high) },
    { label: "BB Middle", value: fmt(vol.bb_mid) },
    { label: "BB Lower", value: fmt(vol.bb_low) }
  ];

  const grid = document.getElementById("volatilityDataGrid");
  if (grid) {
    grid.innerHTML = items.map(item =>
      `<div class="data-row">
        <div class="data-label">${sanitize(item.label)}</div>
        <div class="data-value ${sanitize(item.klass || "")}">${sanitize(item.value)}</div>
      </div>`
    ).join("");
  }
}


function renderFundamentals(data) {
  const isIndex = data.sector === "Index" || !("pe_ratio" in data);
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
  const current = data.price || data.current_price || 0;

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

function renderExtremes(data) {
  const box = document.getElementById("extremesBox");
  if (!box) return;
  box.style.display = "block";

  const vcpStatus = data.vcp_matched ? "Matched" : "No Pattern";
  const vcpClass = data.vcp_matched ? "text-up" : "text-dim";

  const items = [
    { label: "52-Week High", value: fmt(data.week_52_high), highlight: "" },
    { label: "52-Week Low", value: fmt(data.week_52_low), highlight: "" },
    { label: "All-Time High", value: fmt(data.all_time_high), highlight: "text-up" },
    { label: "All-Time Low", value: fmt(data.all_time_low), highlight: "text-down" },
    { label: "VCP Criteria", value: vcpStatus, highlight: vcpClass }
  ];

  document.getElementById("extremesGrid").innerHTML = items.map(item =>
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
  if (!box) return;

  const grid = document.getElementById("optionsGrid");
  if (!grid) return;

  box.style.display = "block"; // Always show the box to indicate functionality exists
  
  if (!data.options_data && !data.implied_move_data) {
    grid.innerHTML = `<div class="data-row" style="color: var(--text-dim);">Options data unavailable (Market Data Feed disconnected).</div>`;
    return;
  }
  
  const opt = data.options_data || {};
  if (!opt.current && !opt.next && !data.implied_move_data) {
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
    items.push({
      label: `${labelPrefix} (Max Pain Area)`, 
      value: expData.max_pain ? fmt(expData.max_pain) : "N/A",
      highlight: ""
    });
  };

  if (opt.current) addExp("Current Expiry", opt.current);
  if (opt.next) addExp("Next Expiry", opt.next);

  // --- ADDED: Implied Move UI ---
  if (data.implied_move_data) {
    const im = data.implied_move_data;
    items.push({
      label: `Implied Move (${im.expiry || "Near Expiry"})`,
      value: `${im.implied_move.toFixed(2)}%`,
      highlight: "text-up"
    });
    items.push({
      label: `Straddle Price (ATM Buy)`,
      value: fmt(im.straddle),
      highlight: ""
    });
  }

  document.getElementById("optionsGrid").innerHTML = items.map(item =>
    `<div class="data-row">
      <div class="data-label">${sanitize(item.label)}</div>
      <div class="data-value ${item.highlight}">${sanitize(item.value)}</div>
    </div>`
  ).join("");
}

function renderTaDetails(type) {
  const container = document.getElementById("taIndicatorDetails");
  if (!container) return;
  
  if (!currentTaData) {
    container.innerHTML = `<div class="placeholder-text">Technical data unavailable for this symbol.</div>`;
    return;
  }
  
  const data = currentTaData[type];
  if (!data && type !== 'ichimoku' && type !== 'stochastic' && type !== 'keltner' && type !== 'bollinger' && type !== 'adx') {
    // For simple numeric values (atr, vwap, mfi, cci, williams_r)
    if (currentTaData[type] === undefined) {
      container.innerHTML = `<div class="placeholder-text">Indicator data not calculated.</div>`;
      return;
    }
  }

  let html = "";
  
  switch(type) {
    case 'bollinger':
      html = renderDataRows([
        { label: "Upper Band", value: fmt(data?.high) },
        { label: "Middle Band (SMA 20)", value: fmt(data?.mid) },
        { label: "Lower Band", value: fmt(data?.low) }
      ]);
      break;
    case 'keltner':
      html = renderDataRows([
        { label: "Upper Channel", value: fmt(data?.high) },
        { label: "Middle Line", value: fmt(data?.mid) },
        { label: "Lower Channel", value: fmt(data?.low) }
      ]);
      break;
    case 'ichimoku':
      html = renderDataRows([
        { label: "Senkou Span A", value: fmt(data?.span_a) },
        { label: "Senkou Span B", value: fmt(data?.span_b) },
        { label: "Kijun-sen (Base)", value: fmt(data?.base) },
        { label: "Tenkan-sen (Conversion)", value: fmt(data?.conversion) }
      ]);
      break;
    case 'adx':
      html = renderDataRows([
        { label: "ADX (Trend Strength)", value: data?.adx },
        { label: "+DI (Bullish Strength)", value: data?.pos, klass: "text-up" },
        { label: "-DI (Bearish Strength)", value: data?.neg, klass: "text-down" }
      ]);
      break;
    case 'stochastic':
      html = renderDataRows([
        { label: "%K (Fast)", value: data?.k },
        { label: "%D (Slow/Signal)", value: data?.d }
      ]);
      break;
    case 'atr':
      html = renderDataRows([{ label: "Average True Range", value: fmt(currentTaData.atr) }]);
      break;
    case 'vwap':
      html = renderDataRows([{ label: "VWAP", value: fmt(currentTaData.vwap) }]);
      break;
    case 'mfi':
      html = renderDataRows([{ label: "Money Flow Index", value: currentTaData.mfi }]);
      break;
    case 'cci':
      html = renderDataRows([{ label: "Commodity Channel Index", value: currentTaData.cci }]);
      break;
    case 'williams_r':
      html = renderDataRows([{ label: "Williams %R", value: currentTaData.williams_r }]);
      break;
    default:
      html = `<div class="placeholder-text">Select an indicator to view details</div>`;
  }
  
  container.innerHTML = html;
}

function renderDataRows(items) {
  return items.map(item =>
    `<div class="data-row">
      <div class="data-label">${sanitize(item.label)}</div>
      <div class="data-value ${sanitize(item.klass || "")}">${sanitize(item.value)}</div>
    </div>`
  ).join("");
}

function renderPerformance(data) {
  const perfs = data.performance || [];
  const grid = document.getElementById("perfGrid");
  grid.innerHTML = "";
  
  if (!perfs.length) {
      grid.innerHTML = `<div style="color: var(--text-dim);">No performance data available.</div>`;
      return;
  }

  perfs.forEach(p => {
    const up = p.pct >= 0;
    const pctDisplay = p.pct !== null && p.pct !== undefined
      ? `${up ? "+" : ""}${Number(p.pct).toFixed(2)}%`
      : "N/A";
    
    const block = document.createElement("div");
    block.className = "perf-block";
    
    const period = document.createElement("div");
    period.className = "perf-period";
    period.textContent = p.period;
    
    const pct = document.createElement("div");
    pct.className = `perf-pct ${up ? "up" : "down"}`;
    pct.textContent = pctDisplay;
    
    block.appendChild(period);
    block.appendChild(pct);
    grid.appendChild(block);
  });
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

function formatSymbol(sym) {
  if (!sym) return "";
  const clean = sym.replace(/%5E/i, "^").replace(".NS", "");
  const mapping = {
    "^NSEBANK": "BANK NIFTY",
    "^CNXIT": "NIFTY IT",
    "^CNXAUTO": "NIFTY AUTO",
    "^CNXFMCG": "NIFTY FMCG",
    "^CNXMETAL": "NIFTY METAL",
    "^CNXPHARMA": "NIFTY PHARMA",
    "^CNXREALTY": "NIFTY REALTY",
    "^CNXENERGY": "NIFTY ENERGY",
    "^CNXINFRA": "NIFTY INFRA",
    "^CNXFIN": "NIFTY FIN SERVICES",
    "^CNXPSE": "NIFTY PSE",
    "^CNXCOMM": "NIFTY COMMODITIES",
    "^CNXCONSUM": "NIFTY CONSUMPTION",
    "^NSEI": "NIFTY 50",
    "^BSESN": "SENSEX"
  };
  return mapping[clean] || clean;
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

// Global Event Delegation for Period Buttons
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.period-btn');
  if (!btn) return;
  const period = btn.getAttribute('data-period');
  if (period && currentSymbol) {
    document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentPeriod = period;
    localStorage.setItem('lastPeriod', period);
    loadStockDashboard(currentSymbol, period);
  }
});

// -----------------------------------------------------------------
// RELATIVE ROTATION GRAPH (RRG) TABS & CHARTING
// -----------------------------------------------------------------
let rrgChartInstance = null;


window.triggerRrgScan = async function(force = false) {
  const loader = document.getElementById("rrgLoader");
  const container = document.querySelector(".rrg-chart-container");
  
  if (loader) loader.style.display = "block";
  if (container) container.style.opacity = "0.4";
  
  try {
    const rsWindow = document.getElementById("rrgRsWindow").value || 10;
    const momWindow = document.getElementById("rrgMomWindow").value || 4;
    const cat = currentMomentumCategory || 'nifty50';
    
    console.log(`📡 Fetching RRG data for category ${cat} (RS: ${rsWindow}, Mom: ${momWindow})...`);
    const forceParam = force ? "&force=true" : "";
    const fetchUrl = `${window.API_BASE}/api/screener/rrg?category=${cat}&rs_window=${rsWindow}&mom_window=${momWindow}${forceParam}&v=${new Date().getTime()}`;
    
    const resp = await fetchWithTimeout(fetchUrl, {
      headers: { "X-API-Key": window.SESSION_TOKEN || "" },
      cache: "no-store"
    });
    
    if (!resp.ok) throw new Error(`RRG request failed: ${resp.status}`);
    const data = await resp.json();
    
    renderRrgChart(data);
    renderRrgLists(data.stocks);
    
  } catch (err) {
    console.error("RRG scan error:", err);
  } finally {
    if (loader) loader.style.display = "none";
    if (container) container.style.opacity = "1";
  }
};

window.renderRrgChart = function(data) {
  const canvas = document.getElementById("rrgChart");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  
  if (rrgChartInstance) {
    rrgChartInstance.destroy();
  }
  
  const stocks = data.stocks || [];
  
  const chartData = {
    datasets: [{
      label: 'Equities',
      data: stocks.map(s => ({ x: s.rs_ratio, y: s.rs_momentum, symbol: s.symbol, quadrant: s.quadrant })),
      backgroundColor: stocks.map(s => {
        if (s.quadrant === 'Leading') return '#00e676';
        if (s.quadrant === 'Improving') return '#00e5ff';
        if (s.quadrant === 'Weakening') return '#ff9100';
        return '#ff1744';
      }),
      borderColor: 'rgba(255, 255, 255, 0.25)',
      borderWidth: 1.5,
      pointRadius: 6,
      pointHoverRadius: 9,
    }]
  };
  
  // Find min/max to center around (100, 100)
  let maxDist = 2.0;
  stocks.forEach(s => {
    const dx = Math.abs(s.rs_ratio - 100);
    const dy = Math.abs(s.rs_momentum - 100);
    if (dx > maxDist) maxDist = dx;
    if (dy > maxDist) maxDist = dy;
  });
  
  maxDist = maxDist * 1.15;
  const xMin = 100 - maxDist;
  const xMax = 100 + maxDist;
  const yMin = 100 - maxDist;
  const yMax = 100 + maxDist;
  
  rrgChartInstance = new Chart(ctx, {
    type: 'scatter',
    data: chartData,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          min: xMin,
          max: xMax,
          grid: {
            color: 'rgba(255, 255, 255, 0.05)'
          },
          title: {
            display: true,
            text: 'RS Ratio (Relative Strength)',
            color: 'rgba(255, 255, 255, 0.7)',
            font: { family: 'Outfit', size: 12, weight: '600' }
          },
          ticks: { color: 'rgba(255, 255, 255, 0.5)' }
        },
        y: {
          min: yMin,
          max: yMax,
          grid: {
            color: 'rgba(255, 255, 255, 0.05)'
          },
          title: {
            display: true,
            text: 'RS Momentum (Relative Momentum)',
            color: 'rgba(255, 255, 255, 0.7)',
            font: { family: 'Outfit', size: 12, weight: '600' }
          },
          ticks: { color: 'rgba(255, 255, 255, 0.5)' }
        }
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function(context) {
              const item = context.raw;
              return `${item.symbol}: RS Ratio: ${item.x.toFixed(2)}, RS Momentum: ${item.y.toFixed(2)} (${item.quadrant})`;
            }
          }
        }
      }
    },
    plugins: [{
      id: 'quadrantShading',
      beforeDraw: function(chart) {
        const { ctx, chartArea: { left, top, right, bottom }, scales: { x, y } } = chart;
        const centerX = x.getPixelForValue(100);
        const centerY = y.getPixelForValue(100);
        
        ctx.save();
        
        // Shading: Leading
        ctx.fillStyle = 'rgba(0, 230, 118, 0.035)';
        ctx.fillRect(centerX, top, right - centerX, centerY - top);
        
        // Shading: Improving
        ctx.fillStyle = 'rgba(0, 229, 255, 0.035)';
        ctx.fillRect(left, top, centerX - left, centerY - top);
        
        // Shading: Weakening
        ctx.fillStyle = 'rgba(255, 145, 0, 0.035)';
        ctx.fillRect(centerX, centerY, right - centerX, bottom - centerY);
        
        // Shading: Lagging
        ctx.fillStyle = 'rgba(255, 23, 68, 0.035)';
        ctx.fillRect(left, centerY, centerX - left, bottom - centerY);
        
        // Lines
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
        
        ctx.beginPath();
        ctx.moveTo(centerX, top);
        ctx.lineTo(centerX, bottom);
        ctx.stroke();
        
        ctx.beginPath();
        ctx.moveTo(left, centerY);
        ctx.lineTo(right, centerY);
        ctx.stroke();
        
        // Text labels
        ctx.font = '600 12px Outfit';
        ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
        
        ctx.textAlign = 'right';
        ctx.fillText('LEADING', right - 15, top + 20);
        
        ctx.textAlign = 'left';
        ctx.fillText('IMPROVING', left + 15, top + 20);
        
        ctx.textAlign = 'right';
        ctx.fillText('WEAKENING', right - 15, bottom - 15);
        
        ctx.textAlign = 'left';
        ctx.fillText('LAGGING', left + 15, bottom - 15);
        
        ctx.restore();
      },
      afterDatasetsDraw: function(chart) {
        const { ctx, scales: { x, y } } = chart;
        const dataset = chart.data.datasets[0];
        
        ctx.save();
        ctx.font = '600 10px JetBrains Mono, Inter, monospace';
        ctx.fillStyle = 'rgba(255, 255, 255, 0.85)';
        ctx.textBaseline = 'middle';
        
        const showAll = document.getElementById("rrgShowAllLabels") && document.getElementById("rrgShowAllLabels").checked;
        const threshold = 1.6;
        
        // Track bounding boxes of drawn labels to prevent overlaps
        const drawnLabelBoxes = [];
        
        // Sort items by distance from center descending so outermost/important stocks get label priority
        const sortedData = [...dataset.data].sort((a, b) => {
          const distA = Math.sqrt(Math.pow(a.x - 100, 2) + Math.pow(a.y - 100, 2));
          const distB = Math.sqrt(Math.pow(b.x - 100, 2) + Math.pow(b.y - 100, 2));
          return distB - distA;
        });
        
        sortedData.forEach((item) => {
          const ptX = x.getPixelForValue(item.x);
          const ptY = y.getPixelForValue(item.y);
          
          const dist = Math.sqrt(Math.pow(item.x - 100, 2) + Math.pow(item.y - 100, 2));
          
          if (showAll || dist >= threshold) {
            if (ptX >= chart.chartArea.left && ptX <= chart.chartArea.right &&
                ptY >= chart.chartArea.top && ptY <= chart.chartArea.bottom) {
              
              const textWidth = ctx.measureText(item.symbol).width;
              const textHeight = 10;
              
              // Try placements around the dot: increasing distance (8px, 14px, 20px) and 8 directions (angles)
              let placed = false;
              const distances = [8, 14, 20];
              const angles = [0, 45, 90, 135, 180, 225, 270, 315]; // in degrees
              
              for (const r of distances) {
                if (placed) break;
                for (const angle of angles) {
                  const rad = (angle * Math.PI) / 180;
                  const dx = r * Math.cos(rad);
                  const dy = r * Math.sin(rad);
                  
                  // Text alignment based on direction
                  let align = 'center';
                  if (dx > 4) align = 'left';
                  else if (dx < -4) align = 'right';
                  
                  const posX = ptX + dx;
                  const posY = ptY + dy;
                  
                  const box = {
                    x1: align === 'left' ? posX - 2 : (align === 'right' ? posX - textWidth - 2 : posX - textWidth / 2 - 2),
                    y1: posY - textHeight / 2 - 2,
                    x2: align === 'left' ? posX + textWidth + 2 : (align === 'right' ? posX + 2 : posX + textWidth / 2 + 2),
                    y2: posY + textHeight / 2 + 2
                  };
                  
                  // 1. Check overlap with other drawn labels
                  let collision = false;
                  for (const other of drawnLabelBoxes) {
                    if (!(box.x2 < other.x1 || box.x1 > other.x2 || box.y2 < other.y1 || box.y1 > other.y2)) {
                      collision = true;
                      break;
                    }
                  }
                  
                  // 2. Check overlap with OTHER stock points (dots)
                  if (!collision) {
                    for (const otherItem of dataset.data) {
                      if (otherItem.symbol === item.symbol) continue;
                      const otherPtX = x.getPixelForValue(otherItem.x);
                      const otherPtY = y.getPixelForValue(otherItem.y);
                      
                      const dotMargin = 6;
                      const dotBox = {
                        x1: otherPtX - dotMargin,
                        y1: otherPtY - dotMargin,
                        x2: otherPtX + dotMargin,
                        y2: otherPtY + dotMargin
                      };
                      if (!(box.x2 < dotBox.x1 || box.x1 > dotBox.x2 || box.y2 < dotBox.y1 || box.y1 > dotBox.y2)) {
                        collision = true;
                        break;
                      }
                    }
                  }
                  
                  if (!collision) {
                    // Draw label
                    ctx.textAlign = align;
                    ctx.shadowColor = 'rgba(0, 0, 0, 0.95)';
                    ctx.shadowBlur = 4;
                    ctx.fillText(formatSymbol(item.symbol), posX, posY);
                    
                    // Record bounding box
                    drawnLabelBoxes.push(box);
                    placed = true;
                    break;
                  }
                }
              }
            }
          }
        });
        
        ctx.restore();
      }
    }]
  });
  window.rrgChartInstance = rrgChartInstance;
};

window.renderRrgLists = function(stocks) {
  const leading = document.getElementById("rrgLeadingList");
  const improving = document.getElementById("rrgImprovingList");
  const weakening = document.getElementById("rrgWeakeningList");
  const lagging = document.getElementById("rrgLaggingList");
  
  if (!leading || !improving || !weakening || !lagging) return;
  
  leading.innerHTML = "";
  improving.innerHTML = "";
  weakening.innerHTML = "";
  lagging.innerHTML = "";
  
  stocks.forEach(s => {
    const item = document.createElement("div");
    item.className = "rrg-list-item";
    // Sector indices (starting with ^) shouldn't get .NS suffix
    const clickSym = s.symbol.startsWith('^') ? s.symbol : s.symbol + ".NS";
    item.onclick = () => {
      loadStockDashboard(clickSym);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    };
    
    let quadClass = s.quadrant.toLowerCase();
    
    item.innerHTML = `
      <span>${sanitize(formatSymbol(s.symbol))}</span>
      <span class="rrg-val-pill ${quadClass}">${s.rs_ratio.toFixed(1)}</span>
    `;
    
    if (s.quadrant === 'Leading') leading.appendChild(item);
    else if (s.quadrant === 'Improving') improving.appendChild(item);
    else if (s.quadrant === 'Weakening') weakening.appendChild(item);
    else if (s.quadrant === 'Lagging') lagging.appendChild(item);
  });
  
  const placeholder = `<span style="color:var(--text-muted);font-size:0.8rem;font-style:italic;">No stocks</span>`;
  if (leading.children.length === 0) leading.innerHTML = placeholder;
  if (improving.children.length === 0) improving.innerHTML = placeholder;
  if (weakening.children.length === 0) weakening.innerHTML = placeholder;
  if (lagging.children.length === 0) lagging.innerHTML = placeholder;
};

// Human-readable labels for NSE sectoral index tickers
const RRG_SYMBOL_LABELS = {
  "^NSEBANK":              "Nifty Bank",
  "^CNXIT":                "Nifty IT",
  "^CNXAUTO":              "Nifty Auto",
  "^CNXFMCG":              "Nifty FMCG",
  "^CNXMETAL":             "Nifty Metal",
  "^CNXPHARMA":            "Nifty Pharma",
  "^CNXREALTY":            "Nifty Realty",
  "^CNXENERGY":            "Nifty Energy",
  "^CNXINFRA":             "Nifty Infra",
  "^CNXFIN":               "Nifty Fin Service 25/50",
  "^CNXPSE":               "Nifty PSE",
  "^CNXCONSUM":            "Nifty Consumption",
  "^CNXSERVICE":           "Nifty Services",
  "^CNXPSUBANK":           "Nifty PSU Bank",
  "^CNXMEDIA":             "Nifty Media",
  "NIFTY_PVT_BANK":        "Nifty Private Bank",
  "NIFTY_PVT_BANK.NS":     "Nifty Private Bank",
  "NIFTY_FIN_SERVICE":     "Nifty Financial Services",
  "NIFTY_FIN_SERVICE.NS":  "Nifty Financial Services",
  "NIFTY_OIL_AND_GAS":     "NIFTY OIL & GAS",
  "NIFTY_OIL_AND_GAS.NS":  "NIFTY OIL & GAS",
  "NIFTY_CONSR_DURBL":     "NIFTY CONSUMER DURABLES",
  "NIFTY_CONSR_DURBL.NS":  "NIFTY CONSUMER DURABLES",
  "NIFTY_MIDSML_HLTH":     "Nifty MidSmall Healthcare",
  "NIFTY_MIDSML_HLTH.NS":  "Nifty MidSmall Healthcare",
  "NIFTY_HEALTHCARE":      "Nifty Healthcare",
  "NIFTY_HEALTHCARE.NS":   "Nifty Healthcare",
  "^NSEI":                 "NIFTY 50",
  "^NSEMDCP50":            "NIFTY MID50",
  "^BSESN":                "SENSEX",
};

function formatSymbol(sym) {
  return RRG_SYMBOL_LABELS[sym] || sym;
}

// ── Tab Switcher & Data Loader ──────────────────────────────────────────────
window.switchDashboardTab = function(tab) {
  console.log("👉 switchDashboardTab called with:", tab);
  const overviewContent = document.getElementById("overviewTabContent");
  const sectorHeatmapContent = document.getElementById("sectorHeatmapTabContent");
  const rrgContent = document.getElementById("rrgTabContent");
  const backtestContent = document.getElementById("backtestTabContent");
  const momentum30Content = document.getElementById("momentum30TabContent");
  
  document.querySelectorAll(".dashboard-tabs .tab-nav-btn").forEach(btn => {
    btn.classList.remove("active");
  });
  
  if (tab === "overview") {
    if (overviewContent) overviewContent.style.display = "flex";
    if (sectorHeatmapContent) sectorHeatmapContent.style.display = "none";
    if (rrgContent) rrgContent.style.display = "none";
    if (backtestContent) backtestContent.style.display = "none";
    if (momentum30Content) momentum30Content.style.display = "none";
    const btn = document.getElementById("tabBtnOverview");
    if (btn) btn.classList.add("active");
  } else if (tab === "sectorHeatmap") {
    if (overviewContent) overviewContent.style.display = "none";
    if (sectorHeatmapContent) sectorHeatmapContent.style.display = "flex";
    if (rrgContent) rrgContent.style.display = "none";
    if (backtestContent) backtestContent.style.display = "none";
    if (momentum30Content) momentum30Content.style.display = "none";
    const btn = document.getElementById("tabBtnSectorHeatmap");
    if (btn) btn.classList.add("active");
    loadSectorHeatmap();
  } else if (tab === "rrg") {
    if (overviewContent) overviewContent.style.display = "none";
    if (sectorHeatmapContent) sectorHeatmapContent.style.display = "none";
    if (rrgContent) rrgContent.style.display = "flex";
    if (backtestContent) backtestContent.style.display = "none";
    if (momentum30Content) momentum30Content.style.display = "none";
    const btn = document.getElementById("tabBtnRrg");
    if (btn) btn.classList.add("active");
    if (typeof triggerRrgScan === "function") triggerRrgScan(false);
  } else if (tab === "backtest") {
    if (overviewContent) overviewContent.style.display = "none";
    if (sectorHeatmapContent) sectorHeatmapContent.style.display = "none";
    if (rrgContent) rrgContent.style.display = "none";
    if (backtestContent) backtestContent.style.display = "flex";
    if (momentum30Content) momentum30Content.style.display = "none";
    const btn = document.getElementById("tabBtnBacktest");
    if (btn) btn.classList.add("active");
    loadBacktestSummary(true);
  } else if (tab === "momentum30") {
    if (overviewContent) overviewContent.style.display = "none";
    if (sectorHeatmapContent) sectorHeatmapContent.style.display = "none";
    if (rrgContent) rrgContent.style.display = "none";
    if (backtestContent) backtestContent.style.display = "none";
    if (momentum30Content) momentum30Content.style.display = "flex";
    const btn = document.getElementById("tabBtnMomentum30");
    if (btn) btn.classList.add("active");
    loadMomentum30(false);
  }
};

window.loadBacktestSummary = async function(force = false) {
  const tbody = document.getElementById("backtestTableBody");
  if (!tbody) return;
  if (!force && tbody.querySelectorAll("tr").length > 1) return;

  tbody.innerHTML = `<tr><td colspan="10" style="text-align:center;"><div class="pulse-loader">Loading strategy backtest results...</div></td></tr>`;
  try {
    const apiKey = window.SESSION_TOKEN || "";
    const res = await fetch(`${window.API_BASE}/api/backtest/summary`, {
      headers: { "X-API-Key": apiKey }
    });
    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
    const data = await res.json();
    const summary = data.summary || [];

    if (summary.length === 0) {
      tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding: 20px;">No backtest data available. Run backtest engine first.</td></tr>`;
      return;
    }

    let rowsHtml = "";
    summary.forEach(item => {
      const totalRet = Number(item["Total Return (%)"]) || 0;
      const buyHold = Number(item["Buy & Hold Return (%)"]) || 0;
      const cagr = Number(item["CAGR (%)"]) || 0;
      const maxDd = Number(item["Max Drawdown (%)"]) || 0;
      const sharpe = Number(item["Sharpe Ratio"]) || 0;
      const winRate = Number(item["Win Rate (%)"]) || 0;
      const totalTrades = item["Total Trades"] !== undefined ? item["Total Trades"] : 0;
      const isRetPos = totalRet >= 0;
      const retClass = isRetPos ? "text-green" : "text-red";
      const retSign = isRetPos ? "+" : "";

      const tearsheetUrl = item["Tearsheet"] 
        ? `${window.API_BASE}/api/backtest/tearsheet/${item["Tearsheet"]}`
        : "#";

      rowsHtml += `
        <tr>
          <td style="font-weight: 600;">${sanitize(item.Ticker)}</td>
          <td style="color: var(--accent-cyan); font-weight: 500;">${sanitize(String(item.Strategy).replace(/_/g, ' '))}</td>
          <td class="${retClass}" style="font-weight: 600;">${retSign}${totalRet.toFixed(2)}%</td>
          <td style="color: var(--text-muted);">${buyHold.toFixed(2)}%</td>
          <td>${cagr.toFixed(2)}%</td>
          <td class="text-red">${maxDd.toFixed(2)}%</td>
          <td style="font-weight: 600;">${sharpe.toFixed(2)}</td>
          <td>${winRate.toFixed(1)}%</td>
          <td>${totalTrades}</td>
          <td>
            <a href="${tearsheetUrl}" target="_blank" class="glass-btn" style="padding: 4px 10px; font-size: 0.75rem; text-decoration: none; display: inline-flex; align-items: center; gap: 4px;">
              📊 View Tearsheet
            </a>
          </td>
        </tr>
      `;
    });
    tbody.innerHTML = rowsHtml;
  } catch (e) {
    console.error("Error loading backtest summary:", e);
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; color: var(--accent-red); padding: 20px;">Failed to load backtest results (${sanitize(e.message)}). Please ensure backend is running on port 8001.</td></tr>`;
  }
};

// ── Nifty 200 Momentum 30 Tab ─────────────────────────────────────────────────

let _momentum30Loaded = false;

window.loadMomentum30 = async function(force = false) {
  const tbody = document.getElementById("momentum30TableBody");
  const lastUpdatedEl = document.getElementById("momentum30LastUpdated");
  if (!tbody) return;

  if (!force && _momentum30Loaded) return;

  tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;"><div class="pulse-loader">Fetching live data for 30 stocks...</div></td></tr>`;

  try {
    const apiKey = window.SESSION_TOKEN || "";
    const url = `${window.API_BASE}/api/screener/momentum30${force ? "?force=true" : ""}`;
    const res = await fetchWithTimeout(url, { headers: { "X-API-Key": apiKey } }, 60000);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const stocks = data.stocks || [];

    if (lastUpdatedEl && data.last_updated) {
      const srcBadge = data.source && data.source.includes("NSE")
        ? `<span style="background:#00e5ff22;color:#00e5ff;border-radius:4px;padding:1px 6px;font-size:0.72rem;">🟢 NSE Live</span>`
        : `<span style="background:#ff910022;color:#ff9100;border-radius:4px;padding:1px 6px;font-size:0.72rem;">🟡 yfinance</span>`;
      lastUpdatedEl.innerHTML = `${srcBadge} &nbsp;Updated: ${data.last_updated} &nbsp;·&nbsp; ${data.fetched}/${data.total} stocks`;
    }

    if (stocks.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:20px;">No data returned. Check backend logs.</td></tr>`;
      return;
    }

    const SECTOR_COLORS = {
      "Capital Goods":      "#00e5ff",
      "Power":              "#ff9100",
      "Financial Services": "#a78bfa",
      "Automobiles":        "#34d399",
      "Healthcare":         "#f472b6",
      "Metals & Mining":    "#fbbf24",
      "Chemicals":          "#60a5fa",
      "Telecom":            "#94a3b8",
    };

    let html = "";
    stocks.forEach((s, idx) => {
      const isGain = s.change_pct >= 0;
      const changeClass = isGain ? "text-green" : "text-red";
      const arrow = isGain ? "\u25b2" : "\u25bc";
      const sign = isGain ? "+" : "";
      const rankStyle = idx === 0
        ? "background: rgba(255,193,7,0.2); color: #ffd700; border-radius: 4px; padding: 2px 6px; font-weight:700;"
        : "color: var(--text-muted); font-size: 0.85rem;";
      const sectorColor = SECTOR_COLORS[s.sector] || "var(--text-muted)";

      html += `
        <tr>
          <td><span style="${rankStyle}">${s.rank}</span></td>
          <td style="font-weight: 700; font-family: 'JetBrains Mono', monospace; color: white; letter-spacing: 0.03em;">${sanitize(s.symbol)}</td>
          <td style="color: var(--text-muted); font-size: 0.88rem;">${sanitize(s.name)}</td>
          <td><span style="font-size: 0.75rem; padding: 2px 8px; border-radius: 4px; background: ${sectorColor}22; color: ${sectorColor}; white-space:nowrap;">${sanitize(s.sector)}</span></td>
          <td style="text-align: right; font-family: 'JetBrains Mono', monospace; font-weight: 600;">\u20b9${Number(s.price).toLocaleString('en-IN', {minimumFractionDigits:2, maximumFractionDigits:2})}</td>
          <td class="${changeClass}" style="text-align: right; font-family: 'JetBrains Mono', monospace;">${sign}\u20b9${Math.abs(s.change_abs).toFixed(2)}</td>
          <td class="${changeClass}" style="text-align: right; font-weight: 700; font-family: 'JetBrains Mono', monospace;">${arrow} ${sign}${s.change_pct.toFixed(2)}%</td>
          <td style="text-align: center;">
            <button class="glass-btn" onclick="loadStockDashboard('${sanitize(s.symbol)}')"
              style="padding: 4px 10px; font-size: 0.75rem; display: inline-flex; align-items: center; gap: 4px;">
              \ud83d\udcc8 Chart
            </button>
          </td>
        </tr>`;
    });

    tbody.innerHTML = html;
    _momentum30Loaded = true;
  } catch (e) {
    console.error("Momentum 30 fetch error:", e);
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color: var(--accent-red); padding:20px;">Failed to load data: ${sanitize(e.message)}</td></tr>`;
  }
};

// ── Sectoral Heat Map (StockeZee-Style) Controller ───────────────────────────
let _currentHeatmapTimeframe = 'Day';
let _currentHeatmapView = 'heatmap';
let _sectorHeatmapData = null;
let _sectorBarChartInstance = null;

window.setSectorHeatmapTimeframe = function(tf) {
  _currentHeatmapTimeframe = tf;
  document.querySelectorAll('.sh-time-btn').forEach(btn => {
    if (btn.textContent.trim() === tf) btn.classList.add('active');
    else btn.classList.remove('active');
  });
  loadSectorHeatmap(tf, false);
};

window.setSectorHeatmapView = function(view) {
  _currentHeatmapView = view;
  const btnHeatmap = document.getElementById('btnViewHeatmap');
  const btnBarchart = document.getElementById('btnViewBarchart');
  const grid = document.getElementById('sectorHeatmapGrid');
  const chartWrap = document.getElementById('sectorBarChartContainer');

  if (view === 'heatmap') {
    if (btnHeatmap) btnHeatmap.classList.add('active');
    if (btnBarchart) btnBarchart.classList.remove('active');
    if (grid) grid.style.display = 'grid';
    if (chartWrap) chartWrap.style.display = 'none';
  } else {
    if (btnHeatmap) btnHeatmap.classList.remove('active');
    if (btnBarchart) btnBarchart.classList.add('active');
    if (grid) grid.style.display = 'none';
    if (chartWrap) chartWrap.style.display = 'flex';
    if (_sectorHeatmapData && _sectorHeatmapData.sectors) {
      renderSectorBarChart(_sectorHeatmapData.sectors);
    }
  }
};

window.createSvgSparkline = function(points, isBullish) {
  if (!points || points.length < 2) {
    return `<svg viewBox="0 0 200 55" preserveAspectRatio="none"><line x1="0" y1="27" x2="200" y2="27" stroke="rgba(255,255,255,0.2)" stroke-width="1.5"/></svg>`;
  }
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = (max - min) === 0 ? 1 : (max - min);
  const w = 200;
  const h = 55;
  const pad = 5;

  const coords = points.map((p, idx) => {
    const x = ((idx / (points.length - 1)) * w).toFixed(1);
    const y = (h - pad - ((p - min) / range) * (h - pad * 2)).toFixed(1);
    return [x, y];
  });

  const linePath = 'M ' + coords.map(c => `${c[0]},${c[1]}`).join(' L ');
  const areaPath = linePath + ` L ${w},${h} L 0,${h} Z`;

  const strokeColor = '#ffffff';
  const fillColor = isBullish ? 'rgba(0, 230, 118, 0.22)' : 'rgba(255, 23, 68, 0.22)';

  return `
    <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <path d="${areaPath}" fill="${fillColor}" />
      <path d="${linePath}" fill="none" stroke="${strokeColor}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  `;
};

window.loadSectorHeatmap = async function(timeframe = null, force = false) {
  if (timeframe) _currentHeatmapTimeframe = timeframe;
  const tf = _currentHeatmapTimeframe || 'Day';
  const loader = document.getElementById('sectorHeatmapLoader');
  const grid = document.getElementById('sectorHeatmapGrid');
  const updatedEl = document.getElementById('sectorHeatmapLastUpdated');

  if (loader) loader.style.display = 'block';
  if (grid) grid.style.opacity = '0.35';

  try {
    const apiKey = window.SESSION_TOKEN || "";
    const forceParam = force ? "&force=true" : "";
    const url = `${window.API_BASE}/api/sectors/heatmap?timeframe=${tf}${forceParam}&v=${new Date().getTime()}`;
    const res = await fetchWithTimeout(url, { headers: { "X-API-Key": apiKey } }, 35000);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _sectorHeatmapData = data;

    if (updatedEl && data.last_updated) {
      updatedEl.innerHTML = `<span style="background:rgba(0,229,255,0.12);color:var(--accent-cyan);padding:2px 8px;border-radius:4px;font-size:0.75rem;">🟢 Live NSE Quotes</span> &nbsp;Updated: ${data.last_updated} &nbsp;·&nbsp; ${data.fetched}/${data.total} sectors active &nbsp;·&nbsp; Timeframe: <strong>${tf}</strong>`;
    }

    renderSectorHeatmapGrid(data.sectors || []);

    if (_currentHeatmapView === 'barchart') {
      renderSectorBarChart(data.sectors || []);
    }
  } catch (err) {
    console.error("Sector Heatmap error:", err);
    if (grid) {
      grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--accent-red); padding: 30px;">Failed to load sector heatmap: ${sanitize(err.message)}</div>`;
    }
  } finally {
    if (loader) loader.style.display = 'none';
    if (grid) grid.style.opacity = '1';
  }
};

window.renderSectorHeatmapGrid = function(sectors) {
  const grid = document.getElementById('sectorHeatmapGrid');
  if (!grid) return;

  if (!sectors || sectors.length === 0) {
    grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 30px; color: var(--text-muted);">No sector data available.</div>`;
    return;
  }

  let html = '';
  sectors.forEach(s => {
    const isBullish = s.change_pct >= 0;
    const sign = isBullish ? '+' : '';
    const cardClass = isBullish ? 'bullish' : 'bearish';
    const sparkSvg = createSvgSparkline(s.sparkline, isBullish);
    const ltpFormatted = Number(s.price).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

    html += `
      <div class="sector-card ${cardClass}" onclick="handleSectorCardClick('${sanitize(s.symbol)}', '${sanitize(s.raw_symbol)}')">
        <div class="sector-card-header">
          <span class="sector-card-title" title="${sanitize(s.name)}">${sanitize(s.name)}</span>
          <span class="sector-card-pct">${sign}${s.change_pct.toFixed(2)}%</span>
        </div>
        <div class="sector-card-sparkline">
          ${sparkSvg}
        </div>
        <div class="sector-card-footer">
          <span class="sector-card-ltp-label">LTP</span>
          <span class="sector-card-ltp-val">₹${ltpFormatted}</span>
        </div>
      </div>
    `;
  });

  grid.innerHTML = html;
};

window.handleSectorCardClick = function(symbol, rawSymbol) {
  console.log("Sector card clicked:", symbol, rawSymbol);
  const clean = symbol.replace('^', '');
  window.open(`https://in.tradingview.com/chart/?symbol=NSE:${encodeURIComponent(clean)}`, '_blank');
};

window.renderSectorBarChart = function(sectors) {
  const canvas = document.getElementById('sectorBarChartCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  if (_sectorBarChartInstance) {
    _sectorBarChartInstance.destroy();
  }

  // Sort sectors ascending for horizontal bar chart (so top gainers display at the top)
  const sorted = [...sectors].sort((a, b) => a.change_pct - b.change_pct);
  const labels = sorted.map(s => s.name);
  const dataValues = sorted.map(s => s.change_pct);
  const bgColors = sorted.map(s => s.change_pct >= 0 ? 'rgba(0, 230, 118, 0.85)' : 'rgba(255, 23, 68, 0.85)');
  const borderColors = sorted.map(s => s.change_pct >= 0 ? '#00e676' : '#ff1744');

  _sectorBarChartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: '% Change',
        data: dataValues,
        backgroundColor: bgColors,
        borderColor: borderColors,
        borderWidth: 1,
        borderRadius: 4,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (context) => {
              const item = sorted[context.dataIndex];
              const sign = item.change_pct >= 0 ? '+' : '';
              return ` ${item.name}: ${sign}${item.change_pct.toFixed(2)}% (LTP: ₹${Number(item.price).toLocaleString('en-IN')})`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(255, 255, 255, 0.06)' },
          ticks: {
            color: 'rgba(255, 255, 255, 0.7)',
            callback: (v) => `${v > 0 ? '+' : ''}${v}%`
          }
        },
        y: {
          grid: { display: false },
          ticks: { color: '#ffffff', font: { family: 'Outfit', size: 12, weight: '500' } }
        }
      }
    }
  });
};

