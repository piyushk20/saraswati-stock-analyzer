// app.js
console.log("🚀 APP.JS LOADED v6! 🚀");

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

document.addEventListener("DOMContentLoaded", () => {
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
      
      // Ensure data is loaded
      if (document.getElementById("screenerTableBody").innerHTML.includes("Refreshing") || document.getElementById("screenerTableBody").innerHTML.trim() === "") {
         loadScreenerData(currentMomentumCategory);
         loadMarketOverview(currentMomentumCategory);
      }
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
      headers: { "X-API-Key": window.CONFIG.API_KEY },
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
  if (category === currentMomentumCategory) return;
  
  console.log(`🔄 Switching category to: ${category}`);
  currentMomentumCategory = category;
  localStorage.setItem('lastCategory', category);
  
  // Update UI buttons
  const buttons = document.querySelectorAll('.cat-btn');
  buttons.forEach(btn => {
    if (btn.getAttribute('onclick').includes(`'${category}'`)) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });
  
  // Show localized loaders
  document.getElementById("screenerTableBody").innerHTML = `<tr><td colspan="4" style="text-align:center;"><div class="pulse-loader">Refreshing ${category}...</div></td></tr>`;
  document.getElementById("gainersTableBody").innerHTML = `<tr><td colspan="3" style="text-align:center;"><div class="pulse-loader">Refreshing...</div></td></tr>`;
  document.getElementById("losersTableBody").innerHTML = `<tr><td colspan="3" style="text-align:center;"><div class="pulse-loader">Refreshing...</div></td></tr>`;
  
  // Trigger refreshes
  loadScreenerData(category);
  loadMarketOverview(category);
};

async function loadScreenerData(category = 'nifty50', force = false) {
  const tableBody = document.getElementById("screenerTableBody");
  const screenerBox = document.getElementById("screenerBox");
  
  if (!tableBody || !screenerBox) return;
  
  try {
    const forceParam = force ? "&force=true" : "";
    const fetchUrl = `${window.API_BASE}/api/screener/crossovers?category=${category}&v=${new Date().getTime()}${forceParam}`;

    const resp = await fetch(fetchUrl, {
      headers: { "X-API-Key": window.CONFIG.API_KEY },
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
      headers: { "X-API-Key": window.CONFIG.API_KEY },
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
      headers: { "X-API-Key": window.CONFIG.API_KEY },
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
      headers: { "X-API-Key": window.CONFIG.API_KEY },
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
      headers: { "X-API-Key": window.CONFIG.API_KEY },
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
      headers: { "X-API-Key": window.CONFIG.API_KEY },
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
      headers: { "X-API-Key": window.CONFIG.API_KEY },
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
      headers: { "X-API-Key": window.CONFIG.API_KEY },
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

  // --- Detect and Register chartjs-chart-financial plugins ---
  if (typeof Chart !== 'undefined') {
    if (window.CandlestickController) {
      Chart.register(window.CandlestickController, window.OhlcController, window.CandlestickElement, window.OhlcElement);
    }
  }

  let hasCandlestick = true; // Force true since we include Candlestick CDN scripts unconditionally
  console.log(`📊 Candlestick plugin available: ${hasCandlestick}, hasOHLC: ${hasOHLC}`);

  // Format x-axis labels
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
      grid: { display: false, color: 'rgba(255,255,255,0.02)' },
      ticks: { 
        maxTicksLimit: 8, 
        color: '#607d8b', 
        font: { size: 10 },
        source: 'data'
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

  if (hasCandlestick && hasOHLC) {
    // ── True Candlestick Chart ──────────────────────────
    const candlestickCtx = document.getElementById('candlestickChart');
    if (!candlestickCtx) return;
    const ctx = candlestickCtx.getContext('2d');

    const chartData = dates.map((d, i) => ({
      x: new Date(d).getTime(),
      o: opens[i],
      h: highs[i],
      l: lows[i],
      c: closes[i]
    }));

    const ema20Data = dates.map((d, i) => ({ x: new Date(d).getTime(), y: ema20[i] }));
    const ema50Data = dates.map((d, i) => ({ x: new Date(d).getTime(), y: ema50[i] }));
    const ema200Data = dates.map((d, i) => ({ x: new Date(d).getTime(), y: ema200[i] }));

    chartInstance = new Chart(ctx, {
      type: 'candlestick',
      data: {
        datasets: [
          {
            label: 'OHLC',
            data: chartData,
            color: { up: '#00e676', down: '#ff1744', unchanged: '#90a4ae' },
            borderColor: { up: '#00e676', down: '#ff1744', unchanged: '#90a4ae' },
            wickColor: { up: '#00e676', down: '#ff1744', unchanged: '#90a4ae' }
          },
          { label: 'EMA 20',  data: ema20Data,  type: 'line', borderColor: '#ff9100', borderWidth: 1.2, pointRadius: 0, fill: false, tension: 0.1 },
          { label: 'EMA 50',  data: ema50Data,  type: 'line', borderColor: '#00e5ff', borderWidth: 1.2, pointRadius: 0, fill: false, tension: 0.1 },
          { label: 'EMA 200', data: ema200Data, type: 'line', borderColor: '#d32f2f', borderWidth: 1.2, borderDash: [4,4], pointRadius: 0, fill: false, tension: 0.1 },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { display: false }, tooltip: tooltipDefaults },
        scales: scalesDefaults
      }
    });
  } else {
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
  }
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
