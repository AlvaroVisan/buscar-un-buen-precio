const GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1_R_z-hBe1q0HGY2-co8U6MDROldoyhfwhwJwQaE3D9o/edit#gid=0";

document.addEventListener("DOMContentLoaded", () => {
  initApp();
});

let marketData = null;

async function initApp() {
  setupEventListeners();
  await loadMarketData();
}

function setupEventListeners() {
  const btnSync = document.getElementById("btnSync");
  const btnOpenSheet = document.getElementById("btnOpenSheet");

  if (btnOpenSheet) {
    btnOpenSheet.addEventListener("click", () => {
      window.open(GOOGLE_SHEET_URL, "_blank");
    });
  }

  if (btnSync) {
    btnSync.addEventListener("click", async () => {
      await syncMarketData();
    });
  }
}

async function loadMarketData() {
  try {
    // Intentar leer de la API local o del archivo latest_data.json
    let response;
    try {
      response = await fetch("/api/data");
    } catch {
      response = await fetch("latest_data.json");
    }

    if (!response.ok) {
      response = await fetch("latest_data.json");
    }

    if (response.ok) {
      marketData = await response.json();
      renderDashboard(marketData);
    } else {
      console.warn("No se pudo cargar latest_data.json directamente");
    }
  } catch (err) {
    console.error("Error al cargar datos:", err);
  }
}

async function syncMarketData() {
  const btnSync = document.getElementById("btnSync");
  const btnText = document.getElementById("btnSyncText");
  const syncIcon = document.querySelector(".sync-icon");

  try {
    if (btnSync) btnSync.disabled = true;
    if (btnText) btnText.textContent = "Sincronizando...";
    if (syncIcon) syncIcon.classList.add("rotating");

    const resp = await fetch("/api/sync", { method: "POST" });
    if (resp.ok) {
      marketData = await resp.json();
      renderDashboard(marketData);
      showToast("¡Precios y niveles de Fibonacci actualizados con éxito!");
    } else {
      // Si estamos en modo estático sin servidor Python API
      showToast("Para sincronizar en vivo, ejecuta 'python app.py' o 'Actualizar_Precios.bat'");
    }
  } catch (err) {
    console.warn("API de sincronización no activa en este puerto, recargando datos locales:", err);
    await loadMarketData();
    showToast("Datos locales recargados.");
  } finally {
    if (btnSync) btnSync.disabled = false;
    if (btnText) btnText.textContent = "Actualizar Precios";
    if (syncIcon) syncIcon.classList.remove("rotating");
  }
}

function renderDashboard(data) {
  if (!data || !data.data) return;

  const items = data.data;

  // 1. Render KPIs
  document.getElementById("kpiTotal").textContent = items.length;
  document.getElementById("kpiLastUpdate").textContent = data.timestamp ? data.timestamp.split(" ")[1] : "--:--:--";
  document.getElementById("kpiPeriod").textContent = `Cálculo automático: ${data.period || "3 meses"}`;

  let buyCount = 0;
  let buyNames = [];
  let maxDrop = 0;
  let maxDropName = "--";

  items.forEach(item => {
    if (item.current_price <= item.fib_levels["50.0%"]) {
      buyCount++;
      buyNames.push(item.tab);
    }
    if (item.drop_pct > maxDrop) {
      maxDrop = item.drop_pct;
      maxDropName = item.tab;
    }
  });

  document.getElementById("kpiBuyCount").textContent = buyCount;
  document.getElementById("kpiBuyNames").textContent = buyCount > 0 ? buyNames.join(", ") : "Ninguno en zona 50%+";
  document.getElementById("kpiMaxDrop").textContent = `-${maxDrop.toFixed(1)}%`;
  document.getElementById("kpiMaxDropName").textContent = maxDropName;

  // 2. Render Cards
  const grid = document.getElementById("assetsGrid");
  grid.innerHTML = "";

  items.forEach(item => {
    const card = createAssetCard(item);
    grid.appendChild(card);
  });
}

function createAssetCard(item) {
  const card = document.createElement("article");
  card.className = "asset-card";

  const isInBuyZone = item.current_price <= item.fib_levels["50.0%"];
  if (isInBuyZone) {
    card.classList.add("in-buy-zone");
  }

  // Determinar posición del precio en el rango 0% a 100%
  const range = item.max - item.min;
  let pctPos = 0;
  if (range > 0) {
    pctPos = ((item.current_price - item.min) / range) * 100;
    pctPos = Math.max(0, Math.min(100, pctPos));
  }

  // Determinar clase de señal
  let signalClass = "signal-watch";
  if (item.status_code === "BUY_GOLDEN" || item.status_code === "STRONG_BUY") {
    signalClass = "signal-buy-golden";
  } else if (item.status_code === "BUY_50") {
    signalClass = "signal-buy-50";
  } else if (item.status_code === "EXPENSIVE") {
    signalClass = "signal-expensive";
  }

  // TradingView Symbol Link
  let tvSymbol = item.ticker;
  if (tvSymbol === "GC=F") tvSymbol = "COMEX:GC1!";
  if (tvSymbol === "^GSPC") tvSymbol = "SP:SPX";

  card.innerHTML = `
    <div class="card-header-row">
      <div class="asset-identity">
        <h2 class="asset-name">${item.tab}</h2>
        <div class="asset-ticker-row">
          <span class="asset-ticker">${item.ticker}</span>
          <span class="asset-company">${item.name}</span>
        </div>
      </div>
      <div class="asset-price-box">
        <div class="asset-current-price">$${formatCurrency(item.current_price)}</div>
        <span class="asset-drop-pill drop-negative">-${item.drop_pct.toFixed(1)}% desde máx</span>
      </div>
    </div>

    <!-- Banner de Señal -->
    <div class="signal-banner ${signalClass}">
      <span>${item.signal}</span>
      <span style="font-size: 0.75rem; opacity: 0.85;">${item.zone_desc}</span>
    </div>

    <!-- Termómetro visual del Rango (Mínimo a Máximo) -->
    <div class="range-gauge-container">
      <div class="range-label-row">
        <span>Suelo (Mín): <strong>$${formatCurrency(item.min)}</strong></span>
        <span>Techo (Máx): <strong>$${formatCurrency(item.max)}</strong></span>
      </div>
      <div class="range-track">
        <div class="range-fill" style="width: ${pctPos}%;"></div>
        <div class="range-pin" style="left: ${pctPos}%;" title="Precio actual: $${formatCurrency(item.current_price)}"></div>
      </div>
      <div style="display: flex; justify-content: space-between; font-size: 0.7rem; color: #64748b; margin-top: 4px;">
        <span>Descuento Máximo</span>
        <span>Rango: $${formatCurrency(item.range)}</span>
        <span>Resistencia</span>
      </div>
    </div>

    <!-- Escalera de Retrocesos de Fibonacci -->
    <div class="fib-ladder">
      ${renderFibRow("23.6%", item.fib_levels["23.6%"], item.current_price, "🟡")}
      ${renderFibRow("38.2%", item.fib_levels["38.2%"], item.current_price, "🟡")}
      ${renderFibRow("50.0%", item.fib_levels["50.0%"], item.current_price, "🟢")}
      ${renderFibRow("61.8%", item.fib_levels["61.8%"], item.current_price, "🏆", true)}
      ${renderFibRow("78.6%", item.fib_levels["78.6%"], item.current_price, "💎")}
    </div>

    <div class="card-actions">
      <a class="tv-link" href="https://www.tradingview.com/symbols/${encodeURIComponent(tvSymbol)}/" target="_blank" rel="noopener noreferrer">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
        Ver gráfico en TradingView
      </a>
      <span style="font-size: 0.75rem; color: #94a3b8;">Ref: Pestaña <strong>"${item.tab}"</strong></span>
    </div>
  `;

  return card;
}

function renderFibRow(level, targetPrice, currentPrice, icon, isGolden = false) {
  const isReached = currentPrice <= targetPrice;
  const distPct = (((currentPrice - targetPrice) / targetPrice) * 100).toFixed(1);
  const goldenClass = isGolden ? "fib-golden" : "";
  const activeClass = isReached ? "active-level" : "";

  let distLabel = "";
  if (isReached) {
    distLabel = `<span style="color: #34d399; font-weight: 600;">✓ Alcanzado (-${Math.abs(distPct)}%)</span>`;
  } else {
    distLabel = `<span>A +${distPct}%</span>`;
  }

  return `
    <div class="fib-row ${goldenClass} ${activeClass}">
      <span class="fib-level-tag">
        <span>${icon}</span>
        <span>${level} ${isGolden ? "(Áureo)" : ""}</span>
      </span>
      <span class="fib-target-price">$${formatCurrency(targetPrice)}</span>
      <span class="fib-distance">${distLabel}</span>
    </div>
  `;
}

function formatCurrency(val) {
  if (typeof val !== "number") val = parseFloat(val) || 0;
  return val.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function showToast(message) {
  let toast = document.querySelector(".toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.className = "toast";
    document.body.appendChild(toast);
  }

  toast.innerHTML = `
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
    <span>${message}</span>
  `;

  toast.classList.add("show");
  setTimeout(() => {
    toast.classList.remove("show");
  }, 4000);
}
