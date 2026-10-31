const GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1_R_z-hBe1q0HGY2-co8U6MDROldoyhfwhwJwQaE3D9o/edit#gid=0";

let marketData = null;
let currentPeriod = "3mo";
let currentFilter = "ALL";
let searchQuery = "";
let currentSort = "score_desc"; // Recomendado: Ordenar por Score de Confluencia
let pendingDeleteTicker = null;
let alertSoundEnabled = localStorage.getItem("alertSoundEnabled") !== "false";
let previousAlertTickers = new Set();

document.addEventListener("DOMContentLoaded", () => {
  initApp();
});

async function initApp() {
  setupEventListeners();
  setupModalEventListeners();
  await loadMarketData();
  startLivePolling();
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

  // --- Centro de Alertas y Oportunidades (Idea 5) ---
  const btnAlertsBell = document.getElementById("btnAlertsBell");
  const alertsDropdown = document.getElementById("alertsDropdown");
  const chkAlertSound = document.getElementById("chkAlertSound");
  const btnTestSound = document.getElementById("btnTestSound");
  const btnToggleBrowserNotifs = document.getElementById("btnToggleBrowserNotifs");

  if (btnAlertsBell && alertsDropdown) {
    btnAlertsBell.addEventListener("click", (e) => {
      e.stopPropagation();
      const isVisible = alertsDropdown.style.display !== "none";
      alertsDropdown.style.display = isVisible ? "none" : "block";
    });
  }

  if (chkAlertSound) {
    chkAlertSound.checked = alertSoundEnabled;
    chkAlertSound.addEventListener("change", (e) => {
      alertSoundEnabled = e.target.checked;
      localStorage.setItem("alertSoundEnabled", alertSoundEnabled);
      showToast(alertSoundEnabled ? "Sonido Chime activado 🔊" : "Sonido Chime silenciado 🔇");
    });
  }

  if (btnTestSound) {
    btnTestSound.addEventListener("click", (e) => {
      e.stopPropagation();
      playAlertChime();
      showToast("🔊 Sonido Chime de alerta reproducido");
    });
  }

  if (btnToggleBrowserNotifs) {
    updateBrowserNotifButtonState();
    btnToggleBrowserNotifs.addEventListener("click", async (e) => {
      e.stopPropagation();
      await toggleBrowserNotifications();
    });
  }

  // Cerrar dropdown de alertas al hacer clic fuera
  document.addEventListener("click", (e) => {
    const alertsWrapper = document.querySelector(".notifications-wrapper");
    if (alertsDropdown && alertsWrapper && !alertsWrapper.contains(e.target)) {
      alertsDropdown.style.display = "none";
    }
  });
}

function setupModalEventListeners() {
  const btnOpenAddModal = document.getElementById("btnOpenAddModal");
  const btnCloseAddModal = document.getElementById("btnCloseAddModal");
  const btnCancelAddModal = document.getElementById("btnCancelAddModal");
  const btnValidateTicker = document.getElementById("btnValidateTicker");
  const addTickerInput = document.getElementById("addTickerInput");
  const btnSubmitAddAsset = document.getElementById("btnSubmitAddAsset");

  const btnCloseDeleteModal = document.getElementById("btnCloseDeleteModal");
  const btnCancelDeleteModal = document.getElementById("btnCancelDeleteModal");
  const btnConfirmDeleteAsset = document.getElementById("btnConfirmDeleteAsset");

  // Abrir Modal Añadir
  if (btnOpenAddModal) {
    btnOpenAddModal.addEventListener("click", () => {
      resetAddModal();
      const modal = document.getElementById("addAssetModal");
      if (modal) modal.style.display = "flex";
      setTimeout(() => { if (addTickerInput) addTickerInput.focus(); }, 100);
    });
  }

  // Cerrar Modal Añadir
  [btnCloseAddModal, btnCancelAddModal].forEach(btn => {
    if (btn) {
      btn.addEventListener("click", () => {
        const modal = document.getElementById("addAssetModal");
        if (modal) modal.style.display = "none";
      });
    }
  });

  // Validar Ticker
  if (btnValidateTicker) {
    btnValidateTicker.addEventListener("click", () => {
      validateTickerAction();
    });
  }

  if (addTickerInput) {
    addTickerInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        validateTickerAction();
      }
    });
  }

  // Guardar Activo
  if (btnSubmitAddAsset) {
    btnSubmitAddAsset.addEventListener("click", async () => {
      await submitAddAssetAction();
    });
  }

  // Modal Eliminar
  [btnCloseDeleteModal, btnCancelDeleteModal].forEach(btn => {
    if (btn) {
      btn.addEventListener("click", () => {
        const modal = document.getElementById("deleteAssetModal");
        if (modal) modal.style.display = "none";
        pendingDeleteTicker = null;
      });
    }
  });

  if (btnConfirmDeleteAsset) {
    btnConfirmDeleteAsset.addEventListener("click", async () => {
      await confirmDeleteAssetAction();
    });
  }

  // Cerrar Modal Gráfico Pantalla Completa
  const btnCloseFullscreenChart = document.getElementById("btnCloseFullscreenChart");
  if (btnCloseFullscreenChart) {
    btnCloseFullscreenChart.addEventListener("click", () => {
      closeFullscreenChart();
    });
  }

  // --- Modal Telegram & Auto-Sync ---
  const btnOpenTelegramModal = document.getElementById("btnOpenTelegramModal");
  const btnCloseTelegramModal = document.getElementById("btnCloseTelegramModal");
  const btnCancelTelegramModal = document.getElementById("btnCancelTelegramModal");
  const btnTestTelegram = document.getElementById("btnTestTelegram");
  const btnSaveTelegramSettings = document.getElementById("btnSaveTelegramSettings");

  if (btnOpenTelegramModal) {
    btnOpenTelegramModal.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const alertsDropdown = document.getElementById("alertsDropdown");
      if (alertsDropdown) alertsDropdown.style.display = "none";
      openTelegramModal();
    });
  }

  [btnCloseTelegramModal, btnCancelTelegramModal].forEach(btn => {
    if (btn) {
      btn.addEventListener("click", () => {
        const modal = document.getElementById("telegramModal");
        if (modal) modal.style.display = "none";
      });
    }
  });

  if (btnTestTelegram) {
    btnTestTelegram.addEventListener("click", async () => {
      await testTelegramAction();
    });
  }

  if (btnSaveTelegramSettings) {
    btnSaveTelegramSettings.addEventListener("click", async () => {
      await saveTelegramSettingsAction();
    });
  }

  // Cerrar modales con Escape y backdrop click
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeAllModals();
    }
  });

  document.querySelectorAll(".modal-backdrop").forEach(backdrop => {
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) {
        closeAllModals();
      }
    });
  });
}

function closeAllModals() {
  const addModal = document.getElementById("addAssetModal");
  const delModal = document.getElementById("deleteAssetModal");
  const tgModal = document.getElementById("telegramModal");
  if (addModal) addModal.style.display = "none";
  if (delModal) delModal.style.display = "none";
  if (tgModal) tgModal.style.display = "none";
  closeFullscreenChart();
  pendingDeleteTicker = null;
}

function closeFullscreenChart() {
  const chartModal = document.getElementById("fullscreenChartModal");
  const container = document.getElementById("fullscreenChartContainer");
  if (chartModal) chartModal.style.display = "none";
  if (container) container.innerHTML = "";
}

async function openTelegramModal() {
  const modal = document.getElementById("telegramModal");
  if (modal) modal.style.display = "flex";

  const tgEnabledToggle = document.getElementById("tgEnabledToggle");
  const tgBotTokenInput = document.getElementById("tgBotTokenInput");
  const tgChatIdInput = document.getElementById("tgChatIdInput");
  const syncIntervalSelect = document.getElementById("syncIntervalSelect");
  const chkNotifyGolden = document.getElementById("chkNotifyGolden");
  const chkNotifyConfluence = document.getElementById("chkNotifyConfluence");
  const resultBox = document.getElementById("tgTestResultBox");

  if (resultBox) {
    resultBox.style.display = "none";
    resultBox.textContent = "";
  }

  try {
    const resp = await fetch("/api/scheduler/status");
    if (resp.ok) {
      const data = await resp.json();
      const tg = data.telegram || {};
      if (tgEnabledToggle) tgEnabledToggle.checked = tg.enabled !== false;
      if (tgBotTokenInput) tgBotTokenInput.value = tg.bot_token || "";
      if (tgChatIdInput) tgChatIdInput.value = tg.chat_id || "";
      if (chkNotifyGolden) chkNotifyGolden.checked = tg.notify_on_golden_zone !== false;
      if (chkNotifyConfluence) chkNotifyConfluence.checked = tg.notify_on_high_confluence !== false;
      if (syncIntervalSelect) {
        if (!data.enabled) {
          syncIntervalSelect.value = "0";
        } else {
          syncIntervalSelect.value = String(data.interval_minutes || 30);
        }
      }
    }
  } catch (e) {
    console.warn("Error cargando configuración de Telegram:", e);
  }

  if (modal) modal.style.display = "flex";
}

async function testTelegramAction() {
  const tokenInput = document.getElementById("tgBotTokenInput");
  const chatInput = document.getElementById("tgChatIdInput");
  const resultBox = document.getElementById("tgTestResultBox");
  const btnTest = document.getElementById("btnTestTelegram");

  const bot_token = tokenInput ? tokenInput.value.trim() : "";
  const chat_id = chatInput ? chatInput.value.trim() : "";

  if (!bot_token || !chat_id) {
    if (resultBox) {
      resultBox.className = "tg-result-box error";
      resultBox.textContent = "Introduce el Bot Token y el Chat ID antes de realizar la prueba.";
      resultBox.style.display = "block";
    }
    return;
  }

  try {
    if (btnTest) {
      btnTest.disabled = true;
      btnTest.textContent = "Enviando...";
    }
    if (resultBox) resultBox.style.display = "none";

    const resp = await fetch("/api/telegram/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bot_token, chat_id })
    });

    const data = await resp.json();
    if (resultBox) {
      resultBox.style.display = "block";
      if (data.success) {
        resultBox.className = "tg-result-box success";
        resultBox.textContent = "✅ ¡Mensaje de prueba recibido en tu Telegram con éxito! Comprueba tu móvil.";
      } else {
        resultBox.className = "tg-result-box error";
        resultBox.textContent = `❌ Error de Telegram: ${data.message || "No se pudo entregar el mensaje"}`;
      }
    }
  } catch (err) {
    if (resultBox) {
      resultBox.className = "tg-result-box error";
      resultBox.textContent = `❌ Error de conexión al probar Telegram: ${err.message}`;
      resultBox.style.display = "block";
    }
  } finally {
    if (btnTest) {
      btnTest.disabled = false;
      btnTest.textContent = "📲 Probar en Móvil";
    }
  }
}

async function saveTelegramSettingsAction() {
  const tgEnabledToggle = document.getElementById("tgEnabledToggle");
  const tokenInput = document.getElementById("tgBotTokenInput");
  const chatInput = document.getElementById("tgChatIdInput");
  const syncIntervalSelect = document.getElementById("syncIntervalSelect");
  const chkNotifyGolden = document.getElementById("chkNotifyGolden");
  const chkNotifyConfluence = document.getElementById("chkNotifyConfluence");
  const btnSave = document.getElementById("btnSaveTelegramSettings");
  const txtSave = document.getElementById("txtSaveTelegram");

  const enabled = tgEnabledToggle ? tgEnabledToggle.checked : true;
  const bot_token = tokenInput ? tokenInput.value.trim() : "";
  const chat_id = chatInput ? chatInput.value.trim() : "";
  const interval_val = syncIntervalSelect ? parseInt(syncIntervalSelect.value, 10) : 30;
  const notify_on_golden_zone = chkNotifyGolden ? chkNotifyGolden.checked : true;
  const notify_on_high_confluence = chkNotifyConfluence ? chkNotifyConfluence.checked : true;

  try {
    if (btnSave) btnSave.disabled = true;
    if (txtSave) txtSave.textContent = "Guardando...";

    // 1. Guardar Telegram
    const respTg = await fetch("/api/telegram/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled,
        bot_token,
        chat_id,
        min_score: 70,
        notify_on_golden_zone,
        notify_on_high_confluence
      })
    });

    // 2. Guardar Scheduler
    const respSched = await fetch("/api/scheduler/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled: interval_val > 0,
        interval_minutes: interval_val > 0 ? interval_val : 30
      })
    });

    if (respTg.ok && respSched.ok) {
      const modal = document.getElementById("telegramModal");
      if (modal) modal.style.display = "none";
      const intervalMsg = interval_val > 0 ? `Auto-sync cada ${interval_val} min` : "Auto-sync pausado";
      showToast(`¡Configuración guardada! Telegram: ${enabled ? 'Activado 📲' : 'Pausado'}, ${intervalMsg}.`);
    } else {
      showToast("Hubo un problema al guardar la configuración en el servidor.");
    }
  } catch (e) {
    showToast("Error de conexión: " + e.message);
  } finally {
    if (btnSave) btnSave.disabled = false;
    if (txtSave) txtSave.textContent = "Guardar Configuración";
  }
}

function resetAddModal() {
  const addTickerInput = document.getElementById("addTickerInput");
  const addTabInput = document.getElementById("addTabInput");
  const addNameInput = document.getElementById("addNameInput");
  const previewBox = document.getElementById("tickerPreviewBox");
  const errorBox = document.getElementById("addModalError");

  if (addTickerInput) addTickerInput.value = "";
  if (addTabInput) addTabInput.value = "";
  if (addNameInput) addNameInput.value = "";
  if (previewBox) previewBox.style.display = "none";
  if (errorBox) {
    errorBox.style.display = "none";
    errorBox.textContent = "";
  }
}

async function validateTickerAction() {
  const tickerInput = document.getElementById("addTickerInput");
  const tabInput = document.getElementById("addTabInput");
  const nameInput = document.getElementById("addNameInput");
  const previewBox = document.getElementById("tickerPreviewBox");
  const errorBox = document.getElementById("addModalError");
  const btnValidate = document.getElementById("btnValidateTicker");

  const ticker = tickerInput ? tickerInput.value.trim().toUpperCase() : "";
  if (!ticker) {
    showAddModalError("Por favor introduce un ticker (ej: TSLA, AAPL, BTC-USD).");
    return;
  }

  try {
    if (btnValidate) btnValidate.textContent = "Verificando...";
    if (errorBox) errorBox.style.display = "none";

    const resp = await fetch("/api/assets/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker })
    });

    const data = await resp.json();
    if (data.valid) {
      if (previewBox) {
        document.getElementById("previewTicker").textContent = data.ticker;
        document.getElementById("previewName").textContent = data.name || data.ticker;
        document.getElementById("previewPrice").textContent = `$${formatCurrency(data.price)}`;
        previewBox.style.display = "flex";
      }

      // Autocompletar campos si están vacíos
      if (tabInput && !tabInput.value) {
        // Tomar el ticker o primera palabra corta
        let shortName = data.ticker.replace(/=F|\^/, "");
        if (data.name && data.name.length <= 8) shortName = data.name;
        tabInput.value = shortName;
      }
      if (nameInput && !nameInput.value) {
        nameInput.value = data.name || data.ticker;
      }
    } else {
      if (previewBox) previewBox.style.display = "none";
      showAddModalError(data.error || `No se pudo encontrar el ticker '${ticker}' en Yahoo Finance.`);
    }
  } catch (err) {
    showAddModalError("Error al contactar con el servidor: " + err.message);
  } finally {
    if (btnValidate) btnValidate.textContent = "Validar";
  }
}

function showAddModalError(msg) {
  const errorBox = document.getElementById("addModalError");
  if (errorBox) {
    errorBox.textContent = msg;
    errorBox.style.display = "block";
  }
}

async function submitAddAssetAction() {
  const tickerInput = document.getElementById("addTickerInput");
  const tabInput = document.getElementById("addTabInput");
  const nameInput = document.getElementById("addNameInput");
  const btnSubmit = document.getElementById("btnSubmitAddAsset");
  const submitText = document.getElementById("btnSubmitAddText");

  const ticker = tickerInput ? tickerInput.value.trim().toUpperCase() : "";
  const tab = tabInput ? tabInput.value.trim() : "";
  const name = nameInput ? nameInput.value.trim() : (tab || ticker);

  if (!ticker) {
    showAddModalError("El ticker es obligatorio.");
    return;
  }
  if (!tab) {
    showAddModalError("El nombre corto / pestaña es obligatorio.");
    return;
  }

  try {
    if (btnSubmit) btnSubmit.disabled = true;
    if (submitText) submitText.textContent = "Guardando y calculando...";

    const resp = await fetch("/api/assets/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker, tab, name })
    });

    const data = await resp.json();
    if (resp.ok) {
      marketData = data;
      closeAllModals();
      renderDashboard(marketData);
      showToast(`¡Activo ${tab} (${ticker}) añadido y calculado con éxito!`);
    } else {
      showAddModalError(data.error || "No se pudo añadir el activo.");
    }
  } catch (err) {
    showAddModalError("Error de conexión al guardar: " + err.message);
  } finally {
    if (btnSubmit) btnSubmit.disabled = false;
    if (submitText) submitText.textContent = "Guardar y Calcular";
  }
}

function promptDeleteAsset(ticker, tabName) {
  pendingDeleteTicker = ticker;
  const modal = document.getElementById("deleteAssetModal");
  const elName = document.getElementById("deleteAssetName");
  const elTicker = document.getElementById("deleteAssetTicker");

  if (elName) elName.textContent = tabName || ticker;
  if (elTicker) elTicker.textContent = ticker;
  if (modal) modal.style.display = "flex";
}

async function confirmDeleteAssetAction() {
  if (!pendingDeleteTicker) return;
  const btnConfirm = document.getElementById("btnConfirmDeleteAsset");

  try {
    if (btnConfirm) {
      btnConfirm.disabled = true;
      btnConfirm.textContent = "Eliminando...";
    }

    const resp = await fetch("/api/assets/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker: pendingDeleteTicker })
    });

    const data = await resp.json();
    if (resp.ok) {
      marketData = data;
      const removedTicker = pendingDeleteTicker;
      closeAllModals();
      renderDashboard(marketData);
      showToast(`Activo ${removedTicker} eliminado de seguimiento.`);
    } else {
      showToast(data.error || "Error al eliminar el activo.");
    }
  } catch (err) {
    showToast("Error de conexión: " + err.message);
  } finally {
    if (btnConfirm) {
      btnConfirm.disabled = false;
      btnConfirm.textContent = "Eliminar";
    }
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

function startLivePolling() {
  // Sondeo suave cada 20 segundos para reflejar actualizaciones del auto-scheduler en segundo plano
  setInterval(async () => {
    try {
      const resp = await fetch("/api/data");
      if (resp.ok) {
        const fresh = await resp.json();
        if (fresh && fresh.timestamp && (!marketData || fresh.timestamp !== marketData.timestamp)) {
          console.log(`[Live Polling] 🔄 Nuevos datos detectados (${fresh.timestamp}). Actualizando dashboard...`);
          marketData = fresh;
          if (marketData.period) {
            currentPeriod = marketData.period;
            updatePeriodPillsUI(currentPeriod);
          }
          renderDashboard(marketData);
        }
      }
    } catch (e) {
      // Manejar caídas temporales de red silenciosamente
    }
  }, 20000);
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

  // 3. Actualizar Radar de Alertas y Oportunidades (Idea 5)
  updateAlertsCenter(items);

  // 4. Renderizar tarjetas filtradas y ordenadas
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

function updateAlertsCenter(items) {
  const alertsBadge = document.getElementById("alertsBadge");
  const alertsSummaryCount = document.getElementById("alertsSummaryCount");
  const alertsList = document.getElementById("alertsList");
  const btnBell = document.getElementById("btnAlertsBell");

  if (!alertsList) return;

  // Filtrar activos que tengan alguna condición relevante de oportunidad
  const alertItems = [];

  items.forEach(item => {
    const isGolden = item.current_price <= item.fib_levels["61.8%"];
    const isConfluence = (item.score || 0) >= 70;
    const isBuy50 = item.current_price <= item.fib_levels["50.0%"];

    if (isGolden || isConfluence || isBuy50) {
      let priorityClass = "priority-buy";
      let priorityBadge = "🟢 Zona de Compra (50%)";
      let priorityWeight = 1;

      if (isGolden && isConfluence) {
        priorityClass = "priority-confluence";
        priorityBadge = "🔥 Confluencia Áurea";
        priorityWeight = 3;
      } else if (isGolden) {
        priorityClass = "priority-golden";
        priorityBadge = "🏆 Zona Áurea (61.8%)";
        priorityWeight = 2.5;
      } else if (isConfluence) {
        priorityClass = "priority-confluence";
        priorityBadge = "🔥 Confluencia Alta";
        priorityWeight = 2;
      }

      alertItems.push({
        item,
        priorityClass,
        priorityBadge,
        priorityWeight,
        score: item.score || 0,
        isGolden,
        isConfluence
      });
    }
  });

  // Ordenar por prioridad descendente y luego por score
  alertItems.sort((a, b) => {
    if (b.priorityWeight !== a.priorityWeight) {
      return b.priorityWeight - a.priorityWeight;
    }
    return b.score - a.score;
  });

  const totalAlerts = alertItems.length;

  // Actualizar Badge en la Campana
  if (alertsBadge) {
    if (totalAlerts > 0) {
      alertsBadge.textContent = totalAlerts;
      alertsBadge.style.display = "flex";
      if (btnBell) btnBell.classList.add("has-alerts");
    } else {
      alertsBadge.style.display = "none";
      if (btnBell) btnBell.classList.remove("has-alerts");
    }
  }

  if (alertsSummaryCount) {
    alertsSummaryCount.textContent = `${totalAlerts} ${totalAlerts === 1 ? 'oportunidad activa' : 'oportunidades activas'}`;
  }

  // Renderizar contenido de la lista
  alertsList.innerHTML = "";

  if (totalAlerts === 0) {
    alertsList.innerHTML = `
      <div class="alerts-empty-state">
        <div class="alerts-empty-icon">🛡️</div>
        <div class="alerts-empty-title">Sin alertas en este momento</div>
        <div class="alerts-empty-desc">Ningún activo se encuentra en Zona Áurea o Confluencia Alta para este periodo.</div>
      </div>
    `;
    return;
  }

  // Detectar si hay nuevos activos para sonido y notificación de escritorio
  const currentTickers = new Set(alertItems.map(a => a.item.ticker));
  let hasNewAlerts = false;
  currentTickers.forEach(t => {
    if (!previousAlertTickers.has(t)) {
      hasNewAlerts = true;
    }
  });

  // Sonar chime si hay nuevas oportunidades detectadas
  if (hasNewAlerts && alertSoundEnabled) {
    playAlertChime();
  }

  // Notificación nativa de escritorio
  if (hasNewAlerts && Notification.permission === "granted" && previousAlertTickers.size > 0) {
    const topAlert = alertItems[0];
    sendDesktopNotification(
      `🎯 Oportunidad: ${topAlert.item.tab} (${topAlert.item.ticker})`,
      `${topAlert.priorityBadge} a $${formatCurrency(topAlert.item.current_price)}. Score Técnico: ${topAlert.score}/100.`
    );
  }

  previousAlertTickers = currentTickers;

  // Renderizar tarjetas de cada oportunidad
  alertItems.forEach(({ item, priorityClass, priorityBadge, score }) => {
    const cardItem = document.createElement("div");
    cardItem.className = `alert-item ${priorityClass}`;

    let scoreClass = "score-low";
    if (score >= 80) scoreClass = "score-fire";
    else if (score >= 65) scoreClass = "score-high";

    cardItem.innerHTML = `
      <div class="alert-item-header">
        <div class="alert-item-title">
          <span>${item.tab}</span>
          <span class="alert-item-ticker">${item.ticker}</span>
        </div>
        <span class="alert-item-score ${scoreClass}">Score: ${score}/100</span>
      </div>
      <div class="alert-item-desc">
        <strong>${priorityBadge}</strong>: Cotizando a <strong>$${formatCurrency(item.current_price)}</strong> 
        (-${item.drop_pct.toFixed(1)}% desde máx). RSI: <strong>${item.rsi ? item.rsi.toFixed(1) : '--'}</strong>.
      </div>
      <div class="alert-item-actions">
        <button class="btn-alert-nav" data-ticker="${item.ticker}" title="Ver tarjeta de ${item.tab}">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 16 16 12 12 8"/><line x1="8" y1="12" x2="16" y2="12"/></svg>
          Ver Ficha
        </button>
        <button class="btn-alert-chart" data-ticker="${item.ticker}" data-tab="${item.tab}" title="Abrir gráfico avanzado">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>
          Gráfico ⛶
        </button>
      </div>
    `;

    // Botón para hacer scroll suave hasta la tarjeta del activo y resaltarla
    const btnNav = cardItem.querySelector(".btn-alert-nav");
    if (btnNav) {
      btnNav.addEventListener("click", () => {
        const dropdown = document.getElementById("alertsDropdown");
        if (dropdown) dropdown.style.display = "none";
        highlightCard(item.ticker);
      });
    }

    // Botón para abrir el gráfico fullscreen directamente
    const btnChart = cardItem.querySelector(".btn-alert-chart");
    if (btnChart) {
      btnChart.addEventListener("click", () => {
        const dropdown = document.getElementById("alertsDropdown");
        if (dropdown) dropdown.style.display = "none";
        openFullscreenChart(item.ticker, item.tab);
      });
    }

    alertsList.appendChild(cardItem);
  });
}

function highlightCard(ticker) {
  const cardId = `card-${ticker.replace(/[^a-zA-Z0-9]/g, '_')}`;
  const el = document.getElementById(cardId);
  if (el) {
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.remove("card-highlight");
    void el.offsetWidth; // forzar reflow para reiniciar animación
    el.classList.add("card-highlight");
    setTimeout(() => {
      el.classList.remove("card-highlight");
    }, 2000);
  }
}

function playAlertChime() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();

    if (ctx.state === "suspended") {
      ctx.resume();
    }

    const now = ctx.currentTime;
    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    const gain = ctx.createGain();

    // Tono armónico dual (D5 587.33Hz y A5 880Hz)
    osc1.type = "sine";
    osc1.frequency.setValueAtTime(587.33, now);
    osc1.frequency.exponentialRampToValueAtTime(880, now + 0.12);

    osc2.type = "triangle";
    osc2.frequency.setValueAtTime(880, now);
    osc2.frequency.exponentialRampToValueAtTime(1174.66, now + 0.18);

    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.22, now + 0.04);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.55);

    osc1.connect(gain);
    osc2.connect(gain);
    gain.connect(ctx.destination);

    osc1.start(now);
    osc2.start(now);
    osc1.stop(now + 0.6);
    osc2.stop(now + 0.6);
  } catch (e) {
    console.warn("Audio chime playback blocked or not supported:", e);
  }
}

function updateBrowserNotifButtonState() {
  const btn = document.getElementById("btnToggleBrowserNotifs");
  const txt = document.getElementById("txtBrowserNotif");
  if (!btn || !txt) return;

  if (!("Notification" in window)) {
    txt.textContent = "Avisos no soportados";
    btn.disabled = true;
    return;
  }

  if (Notification.permission === "granted") {
    btn.classList.add("active");
    txt.textContent = "Avisos de escritorio: ACTIVADOS ✓";
  } else if (Notification.permission === "denied") {
    btn.classList.remove("active");
    txt.textContent = "Avisos bloqueados por navegador";
  } else {
    btn.classList.remove("active");
    txt.textContent = "Activar avisos de escritorio";
  }
}

async function toggleBrowserNotifications() {
  if (!("Notification" in window)) {
    showToast("Tu navegador no soporta notificaciones de escritorio.");
    return;
  }

  if (Notification.permission === "granted") {
    showToast("Las notificaciones de escritorio ya están activadas.");
    updateBrowserNotifButtonState();
    return;
  }

  try {
    const permission = await Notification.requestPermission();
    if (permission === "granted") {
      showToast("¡Avisos de escritorio activados! Recibirás alertas en segundo plano.");
      sendDesktopNotification(
        "Radar de Oportunidades Activado 🎯",
        "Te avisaremos cuando un valor alcance la Zona Áurea o Confluencia Alta."
      );
    } else {
      showToast("Permiso de notificaciones denegado en el navegador.");
    }
  } catch (err) {
    console.warn("Error requesting notification permission:", err);
  }
  updateBrowserNotifButtonState();
}

function sendDesktopNotification(title, body) {
  if ("Notification" in window && Notification.permission === "granted") {
    try {
      new Notification(title, {
        body,
        icon: "https://www.tradingview.com/static/images/favicon.ico"
      });
    } catch (e) {
      console.warn("Notification error:", e);
    }
  }
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
  card.id = `card-${item.ticker.replace(/[^a-zA-Z0-9]/g, '_')}`;
  card.dataset.ticker = item.ticker;

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

  // TradingView Symbol mapping
  const tvSymbol = getTradingViewSymbol(item.ticker);

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
      <div style="display: flex; align-items: flex-start; gap: 8px;">
        <div class="asset-price-box">
          <div class="asset-current-price">$${formatCurrency(item.current_price)}</div>
          <span class="asset-drop-pill drop-negative">-${item.drop_pct.toFixed(1)}% desde máx</span>
        </div>
        <button class="btn-card-delete" title="Dejar de seguir ${item.tab} (${item.ticker})">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
        </button>
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

    <!-- Toolbar de Gráficos -->
    <div class="card-chart-toolbar">
      <button class="btn-toggle-chart" data-ticker="${item.ticker}" title="Ver u ocultar mini gráfico de ${item.tab}">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
        Mini Gráfico
      </button>
      <button class="btn-fullscreen-trigger" data-ticker="${item.ticker}" data-tab="${item.tab}" title="Abrir gráfico avanzado a pantalla completa">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>
        Expandir ⛶
      </button>
    </div>

    <!-- Drawer Desplegable con Mini-Gráfico TradingView -->
    <div class="card-chart-drawer" data-ticker="${item.ticker}" style="display: none;">
      <div class="chart-drawer-header">
        <span class="chart-drawer-title">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
          Tendencia TradingView (${currentPeriod.toUpperCase()})
        </span>
        <button class="btn-fullscreen-chart" data-ticker="${item.ticker}" data-tab="${item.tab}">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>
          Pantalla Completa
        </button>
      </div>
      <div class="chart-widget-wrapper">
        <div style="display: flex; align-items: center; justify-content: center; height: 100%; min-height: 200px; color: #94a3b8; font-size: 0.82rem;">
          Cargando gráfico interactivo de ${item.tab}...
        </div>
      </div>
    </div>

    <div class="card-actions">
      <a class="tv-link" href="https://www.tradingview.com/symbols/${encodeURIComponent(tvSymbol)}/" target="_blank" rel="noopener noreferrer">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
        TradingView Oficial
      </a>
      <span style="font-size: 0.75rem; color: #94a3b8;">Ref: Pestaña <strong>"${item.tab}"</strong></span>
    </div>
  `;

  // Asignar evento al botón eliminar
  const btnDelete = card.querySelector(".btn-card-delete");
  if (btnDelete) {
    btnDelete.addEventListener("click", (e) => {
      e.stopPropagation();
      promptDeleteAsset(item.ticker, item.tab);
    });
  }

  // Asignar evento al botón mini-gráfico (toggle accordion drawer)
  const btnToggleChart = card.querySelector(".btn-toggle-chart");
  if (btnToggleChart) {
    btnToggleChart.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleMiniChart(item.ticker, card, item.tab);
    });
  }

  // Asignar eventos a los botones de pantalla completa
  const btnFullscreenTriggers = card.querySelectorAll(".btn-fullscreen-trigger, .btn-fullscreen-chart");
  btnFullscreenTriggers.forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openFullscreenChart(item.ticker, item.tab);
    });
  });

  return card;
}

function toggleMiniChart(ticker, cardElement, tabName) {
  const drawer = cardElement.querySelector(`.card-chart-drawer[data-ticker="${ticker}"]`);
  const toggleBtn = cardElement.querySelector(`.btn-toggle-chart[data-ticker="${ticker}"]`);
  if (!drawer) return;

  const isHidden = drawer.style.display === "none";
  if (isHidden) {
    drawer.style.display = "block";
    if (toggleBtn) {
      toggleBtn.classList.add("active");
      toggleBtn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="18 15 12 9 6 15"/></svg>
        Ocultar Gráfico
      `;
    }

    const widgetWrapper = drawer.querySelector(".chart-widget-wrapper");
    if (widgetWrapper && !widgetWrapper.dataset.loaded) {
      widgetWrapper.dataset.loaded = "true";
      loadTradingViewMiniWidget(widgetWrapper, ticker);
    }
  } else {
    drawer.style.display = "none";
    if (toggleBtn) {
      toggleBtn.classList.remove("active");
      toggleBtn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
        Mini Gráfico
      `;
    }
  }
}

function loadTradingViewMiniWidget(containerEl, ticker) {
  const tvSymbol = getTradingViewSymbol(ticker);
  containerEl.innerHTML = "";

  const widgetContainer = document.createElement("div");
  widgetContainer.className = "tradingview-widget-container";
  widgetContainer.style.width = "100%";
  widgetContainer.style.height = "220px";

  const widgetSlot = document.createElement("div");
  widgetSlot.className = "tradingview-widget-container__widget";
  widgetSlot.style.width = "100%";
  widgetSlot.style.height = "220px";
  widgetContainer.appendChild(widgetSlot);

  const script = document.createElement("script");
  script.type = "text/javascript";
  script.src = "https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js";
  script.async = true;
  script.text = JSON.stringify({
    symbol: tvSymbol,
    width: "100%",
    height: "220",
    locale: "es",
    dateRange: "3M",
    colorTheme: "dark",
    isTransparent: true,
    autosize: true,
    largeChartUrl: ""
  });

  widgetContainer.appendChild(script);
  containerEl.appendChild(widgetContainer);
}

function openFullscreenChart(ticker, tabName) {
  const tvSymbol = getTradingViewSymbol(ticker);
  const titleEl = document.getElementById("fullscreenChartTitle");
  const subtitleEl = document.getElementById("fullscreenChartSubtitle");
  const container = document.getElementById("fullscreenChartContainer");
  const modal = document.getElementById("fullscreenChartModal");

  if (titleEl) {
    titleEl.textContent = `${tabName || ticker} (${ticker}) — Gráfico Técnico Avanzado`;
  }
  if (subtitleEl) {
    subtitleEl.textContent = `TradingView en tiempo real con velas japonesas, volumen y herramientas de análisis interactivo`;
  }
  if (container) {
    container.innerHTML = `
      <iframe src="https://s.tradingview.com/widgetembed/?symbol=${encodeURIComponent(tvSymbol)}&interval=D&theme=dark&style=1&timezone=Europe%2FMadrid&locale=es"
              style="width: 100%; height: 100%; border: none; min-height: 520px;"
              allowtransparency="true"
              scrolling="no"
              allowfullscreen>
      </iframe>
    `;
  }
  if (modal) modal.style.display = "flex";
}

function getTradingViewSymbol(ticker) {
  if (!ticker) return "SP:SPX";
  const t = ticker.toUpperCase().trim();

  const specialMap = {
    "GC=F": "COMEX:GC1!",
    "CL=F": "NYMEX:CL1!",
    "SI=F": "COMEX:SI1!",
    "^GSPC": "SP:SPX",
    "^DJI": "DJ:DJI",
    "^IXIC": "NASDAQ:IXIC",
    "BTC-USD": "COINBASE:BTCUSD",
    "ETH-USD": "COINBASE:ETHUSD",
    "SOL-USD": "COINBASE:SOLUSD",
    "EURUSD=X": "FX:EURUSD",
    "AMD": "NASDAQ:AMD",
    "NVDA": "NASDAQ:NVDA",
    "TSLA": "NASDAQ:TSLA",
    "META": "NASDAQ:META",
    "CEG": "NASDAQ:CEG",
    "AAPL": "NASDAQ:AAPL",
    "MSFT": "NASDAQ:MSFT",
    "AMZN": "NASDAQ:AMZN",
    "GOOGL": "NASDAQ:GOOGL"
  };

  if (specialMap[t]) return specialMap[t];
  if (t.endsWith(".MC")) return `BME:${t.replace(".MC", "")}`;
  return t;
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
