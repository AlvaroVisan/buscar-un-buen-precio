const GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1_R_z-hBe1q0HGY2-co8U6MDROldoyhfwhwJwQaE3D9o/edit#gid=0";

let marketData = null;
let currentPeriod = "3mo";
let currentFilter = "ALL";
let searchQuery = "";
let currentSort = "score_desc"; // Recomendado: Ordenar por Score de Confluencia

document.addEventListener("DOMContentLoaded", () => {
  initApp();
});

async function initApp() {
  setupEventListeners();
  await loadMarketData();
}

function setupEventListeners() {
  const btnSync = document.getElementById("btnSync");
  const btnOpenSheet = document.getElementById("btnOpenSheet");
  const searchInput = document.getElementById("searchInput");
  const btnClearSearch = document.getElementById("btnClearSearch");
  const sortSelect = document.getElementById("sortSelect");
  const btnResetFilters = document.getElementById("btnResetFilters");

  // Botón Google Sheet
  if (btnOpenSheet) {
    btnOpenSheet.addEventListener("click", () => {
      window.open(GOOGLE_SHEET_URL, "_blank");
    });
  }

  // Botón Sincronizar General
  if (btnSync) {
    btnSync.addEventListener("click", async () => {
      await syncMarketData(currentPeriod);
    });
  }

  // Selector de Temporalidad (Pill buttons: 1mo, 3mo, 6mo, 1y)
  const periodPills = document.querySelectorAll(".period-btn");
  periodPills.forEach(btn => {
    btn.addEventListener("click", async () => {
      const selectedPeriod = btn.dataset.period;
      if (selectedPeriod === currentPeriod) return;

      periodPills.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentPeriod = selectedPeriod;

      showToast(`Cambiando temporalidad a ${formatPeriodLabel(currentPeriod)} y calculando...`);
      await syncMarketData(selectedPeriod);
    });
  });

  // Buscador reactivo
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      searchQuery = e.target.value.trim().toLowerCase();
      if (btnClearSearch) {
        btnClearSearch.style.display = searchQuery ? "flex" : "none";
      }
      renderFilteredCards();
    });
  }

  if (btnClearSearch) {
    btnClearSearch.addEventListener("click", () => {
      if (searchInput) searchInput.value = "";
      searchQuery = "";
      btnClearSearch.style.display = "none";
      renderFilteredCards();
    });
  }

  // Chips de Filtro
  const chipButtons = document.querySelectorAll(".chip-btn");
  chipButtons.forEach(chip => {
    chip.addEventListener("click", () => {
      chipButtons.forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      currentFilter = chip.dataset.filter || "ALL";
      renderFilteredCards();
    });
  });

  // Selector de Ordenación
  if (sortSelect) {
    sortSelect.value = currentSort;
    sortSelect.addEventListener("change", (e) => {
      currentSort = e.target.value;
      renderFilteredCards();
    });
  }

  // Botón Resetear Filtros
  if (btnResetFilters) {
    btnResetFilters.addEventListener("click", () => {
      currentFilter = "ALL";
      searchQuery = "";
      currentSort = "score_desc";

      if (searchInput) searchInput.value = "";
      if (btnClearSearch) btnClearSearch.style.display = "none";
      if (sortSelect) sortSelect.value = "score_desc";

      chipButtons.forEach(c => {
        c.classList.toggle("active", c.dataset.filter === "ALL");
      });

      renderFilteredCards();
    });
  }
}

async function loadMarketData() {
  try {
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
      if (marketData && marketData.period) {
        currentPeriod = marketData.period;
        updatePeriodPillsUI(currentPeriod);
      }
      renderDashboard(marketData);
    } else {
      console.warn("No se pudo cargar latest_data.json directamente");
    }
  } catch (err) {
    console.error("Error al cargar datos:", err);
  }
}

async function syncMarketData(periodToSync) {
  const btnSync = document.getElementById("btnSync");
  const btnText = document.getElementById("btnSyncText");
  const syncIcon = document.querySelector(".sync-icon");
  const periodButtons = document.querySelectorAll(".period-btn");

  const period = periodToSync || currentPeriod || "3mo";

  try {
    if (btnSync) btnSync.disabled = true;
    if (btnText) btnText.textContent = `Actualizando (${period})...`;
    if (syncIcon) syncIcon.classList.add("rotating");
    periodButtons.forEach(b => b.disabled = true);

    const resp = await fetch("/api/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ period: period })
    });

    if (resp.ok) {
      marketData = await resp.json();
      currentPeriod = marketData.period || period;
      updatePeriodPillsUI(currentPeriod);
      renderDashboard(marketData);
      showToast(`¡Mercado y Confluencia Técnica actualizados! Ventana: ${formatPeriodLabel(currentPeriod)}`);
    } else {
      showToast("Para sincronizar en vivo, ejecuta 'python app.py' o 'Actualizar_Precios.bat'");
    }
  } catch (err) {
    console.warn("Error en sincronización vía API:", err);
    await loadMarketData();
    showToast("Datos locales recargados.");
  } finally {
    if (btnSync) btnSync.disabled = false;
    if (btnText) btnText.textContent = "Actualizar Precios";
    if (syncIcon) syncIcon.classList.remove("rotating");
    periodButtons.forEach(b => b.disabled = false);
  }
}

function updatePeriodPillsUI(period) {
  const periodButtons = document.querySelectorAll(".period-btn");
  periodButtons.forEach(b => {
    b.classList.toggle("active", b.dataset.period === period);
  });
}

function formatPeriodLabel(p) {
  switch (p) {
    case "1mo": return "1 Mes";
    case "3mo": return "3 Meses";
    case "6mo": return "6 Meses";
    case "1y": return "1 Año";
    default: return p;
  }
}

function renderDashboard(data) {
  if (!data || !data.data) return;

  const items = data.data;

  // 1. Render KPIs Generales
  document.getElementById("kpiTotal").textContent = items.length;
  document.getElementById("kpiLastUpdate").textContent = data.timestamp ? data.timestamp.split(" ")[1] : "--:--:--";
  document.getElementById("kpiPeriod").textContent = `Ventana de cálculo: ${formatPeriodLabel(data.period || currentPeriod)}`;

  let buyCount = 0;
  let buyNames = [];
  let maxDrop = 0;
  let maxDropName = "--";
  let topScore = 0;
  let topScoreName = "--";
  let topScoreDesc = "Fibonacci + RSI + SMA200";

  items.forEach(item => {
    if (item.current_price <= item.fib_levels["50.0%"]) {
      buyCount++;
      buyNames.push(item.tab);
    }
    if (item.drop_pct > maxDrop) {
      maxDrop = item.drop_pct;
      maxDropName = item.tab;
    }
    const sc = item.score || 0;
    if (sc > topScore) {
      topScore = sc;
      topScoreName = item.tab;
      topScoreDesc = `${item.confluence_rating || "Alta Confluencia"} (RSI ${item.rsi ? item.rsi.toFixed(1) : "--"})`;
    }
  });

  document.getElementById("kpiBuyCount").textContent = buyCount;
  document.getElementById("kpiBuyNames").textContent = buyCount > 0 ? buyNames.join(", ") : "Ninguno en zona 50%+";
  document.getElementById("kpiMaxDrop").textContent = `-${maxDrop.toFixed(1)}%`;
  document.getElementById("kpiMaxDropName").textContent = maxDropName;

  const elTopScore = document.getElementById("kpiTopScore");
  const elTopScoreName = document.getElementById("kpiTopScoreName");
  const elTopScoreDesc = document.getElementById("kpiTopScoreDesc");

  if (elTopScore) elTopScore.textContent = `${topScore}/100`;
  if (elTopScoreName) elTopScoreName.textContent = topScoreName;
  if (elTopScoreDesc) elTopScoreDesc.textContent = topScoreDesc;

  // 2. Actualizar contadores en los chips de filtro
  updateFilterBadges(items);

  // 3. Renderizar tarjetas filtradas y ordenadas
  renderFilteredCards();
}

function updateFilterBadges(items) {
  let countAll = items.length;
  let countConfluence = 0;
  let countBuy = 0;
  let countGolden = 0;
  let countWatch = 0;

  items.forEach(it => {
    if ((it.score || 0) >= 70) countConfluence++;
    if (it.current_price <= it.fib_levels["50.0%"]) countBuy++;
    if (it.current_price <= it.fib_levels["61.8%"]) countGolden++;
    if (it.status_code === "WATCH_38" || it.status_code === "WATCH_23") countWatch++;
  });

  const elAll = document.getElementById("countAll");
  const elConfluence = document.getElementById("countConfluence");
  const elBuy = document.getElementById("countBuy");
  const elGolden = document.getElementById("countGolden");
  const elWatch = document.getElementById("countWatch");

  if (elAll) elAll.textContent = countAll;
  if (elConfluence) elConfluence.textContent = countConfluence;
  if (elBuy) elBuy.textContent = countBuy;
  if (elGolden) elGolden.textContent = countGolden;
  if (elWatch) elWatch.textContent = countWatch;
}

function renderFilteredCards() {
  if (!marketData || !marketData.data) return;

  const rawItems = [...marketData.data];

  // Aplicar Filtro de búsqueda
  let filtered = rawItems.filter(item => {
    if (!searchQuery) return true;
    const q = searchQuery;
    const matchTab = item.tab && item.tab.toLowerCase().includes(q);
    const matchTicker = item.ticker && item.ticker.toLowerCase().includes(q);
    const matchName = item.name && item.name.toLowerCase().includes(q);
    return matchTab || matchTicker || matchName;
  });

  // Aplicar Filtro de Categoría
  filtered = filtered.filter(item => {
    if (currentFilter === "ALL") return true;
    if (currentFilter === "CONFLUENCE") {
      return (item.score || 0) >= 70;
    }
    if (currentFilter === "BUY_ZONE") {
      return item.current_price <= item.fib_levels["50.0%"];
    }
    if (currentFilter === "GOLDEN") {
      return item.current_price <= item.fib_levels["61.8%"];
    }
    if (currentFilter === "WATCH") {
      return item.status_code === "WATCH_38" || item.status_code === "WATCH_23";
    }
    return true;
  });

  // Aplicar Ordenación
  filtered.sort((a, b) => {
    switch (currentSort) {
      case "score_desc":
        return (b.score || 0) - (a.score || 0);
      case "drop_desc":
        return b.drop_pct - a.drop_pct;
      case "drop_asc":
        return a.drop_pct - b.drop_pct;
      case "rsi_asc":
        return (a.rsi || 50) - (b.rsi || 50);
      case "price_asc":
        return a.current_price - b.current_price;
      case "price_desc":
        return b.current_price - a.current_price;
      case "name_asc":
        return a.tab.localeCompare(b.tab);
      default:
        return (b.score || 0) - (a.score || 0);
    }
  });

  const grid = document.getElementById("assetsGrid");
  const emptyState = document.getElementById("emptyState");
  const emptyStateMsg = document.getElementById("emptyStateMsg");

  grid.innerHTML = "";

  if (filtered.length === 0) {
    grid.style.display = "none";
    if (emptyState) {
      emptyState.style.display = "block";
      if (searchQuery) {
        emptyStateMsg.textContent = `No hay ningún activo que coincida con "${searchQuery}".`;
      } else {
        emptyStateMsg.textContent = "No hay ningún activo en la categoría de filtro seleccionada.";
      }
    }
  } else {
    grid.style.display = "grid";
    if (emptyState) emptyState.style.display = "none";

    filtered.forEach((item, idx) => {
      const card = createAssetCard(item);
      card.style.animationDelay = `${idx * 0.04}s`;
      grid.appendChild(card);
    });
  }
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

  // Indicadores Técnicos
  const score = item.score || 0;
  let scoreBadgeClass = "score-low";
  let scoreLabel = "Neutral";
  if (score >= 80) {
    scoreBadgeClass = "score-fire";
    scoreLabel = "🔥 Confluencia";
  } else if (score >= 65) {
    scoreBadgeClass = "score-high";
    scoreLabel = "🟢 Alta Prob.";
  } else if (score >= 45) {
    scoreBadgeClass = "score-moderate";
    scoreLabel = "🟡 Moderada";
  }

  const rsi = typeof item.rsi === "number" ? item.rsi : 50;
  let rsiClass = "neutral";
  let rsiLabel = "Neutral";
  if (rsi <= 30) {
    rsiClass = "oversold";
    rsiLabel = "Sobreventa";
  } else if (rsi <= 40) {
    rsiClass = "mild";
    rsiLabel = "Descuento";
  } else if (rsi > 60) {
    rsiClass = "overbought";
    rsiLabel = "Sobrecompra";
  }

  const isAboveSma = item.is_above_sma !== undefined ? item.is_above_sma : (item.sma_dist_pct >= 0);
  const smaDist = typeof item.sma_dist_pct === "number" ? item.sma_dist_pct : 0;
  const smaClass = isAboveSma ? "bullish" : "bearish";
  const smaSign = smaDist >= 0 ? "+" : "";
  const smaLabel = isAboveSma ? `${smaSign}${smaDist.toFixed(1)}% 🐂 Alcista` : `${smaSign}${smaDist.toFixed(1)}% 🐻 Bajista`;

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

    <!-- Banner de Señal Principal -->
    <div class="signal-banner ${signalClass}">
      <span>${item.signal}</span>
      <span style="font-size: 0.75rem; opacity: 0.85;">${item.zone_desc}</span>
    </div>

    <!-- Panel de Confluencia Técnica (Score, RSI, SMA 200) -->
    <div class="tech-metrics-grid">
      <div class="tech-metric-item">
        <span class="tech-metric-label">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
          Score Calidad
        </span>
        <div class="tech-metric-value">
          <span class="tech-score-val">${score}/100</span>
          <span class="tech-score-badge ${scoreBadgeClass}">${scoreLabel}</span>
        </div>
      </div>

      <div class="tech-metric-item">
        <span class="tech-metric-label">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
          RSI (14 días)
        </span>
        <div class="tech-metric-value">
          <span class="rsi-pill ${rsiClass}" title="RSI: ${rsi.toFixed(1)} (${rsiLabel})">
            <span class="rsi-dot"></span>
            ${rsi.toFixed(1)} <span style="font-size: 0.72rem; font-weight: 500; opacity: 0.85;">(${rsiLabel})</span>
          </span>
        </div>
      </div>

      <div class="tech-metric-item">
        <span class="tech-metric-label">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 14 14"/></svg>
          Tendencia SMA 200
        </span>
        <div class="tech-metric-value">
          <span class="sma-pill ${smaClass}" title="Media de 200 días: $${formatCurrency(item.sma_200)}">
            ${smaLabel}
          </span>
        </div>
      </div>
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
