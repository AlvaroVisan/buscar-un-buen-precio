/* Contexto fundamental consultado bajo demanda; independiente de los periodos técnicos. */
function addBusinessButton(card, item) {
  const ticker = String(item.ticker || "");
  if (!ticker || ticker.startsWith("^") || ticker.includes("=") || /-(USD|EUR|USDT)$/i.test(ticker)) return;
  const identity = card.querySelector(".asset-identity");
  if (!identity) return;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "business-open-btn";
  button.dataset.businessTicker = ticker;
  button.dataset.businessName = item.name || item.tab || ticker;
  button.textContent = "Ver negocio";
  button.setAttribute("aria-haspopup", "dialog");
  identity.append(button);
}

(() => {
  let controller = null;
  let requestNumber = 0;
  let previousFocus = null;
  let activeTicker = "";
  const esc = value => escapeHtml(String(value ?? ""));
  const fields = {
    TotalRevenue: "Ingresos", NetIncome: "Beneficio neto",
    OperatingCashFlow: "Caja operativa", FreeCashFlow: "Caja libre",
    TotalDebt: "Deuda financiera",
    CashCashEquivalentsAndShortTermInvestments: "Efectivo e inversiones líquidas"
  };
  const formatDate = value => {
    if (!value) return "No disponible";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "No disponible" : date.toLocaleString("es-ES", {
      year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
    });
  };
  const list = (items, empty) => items && items.length
    ? `<ul>${items.map(text => `<li>${esc(text)}</li>`).join("")}</ul>`
    : `<p class="business-muted">${esc(empty)}</p>`;

  function render(context) {
    const tone = ["favorable", "mixed", "weak", "insufficient"].includes(context.classification)
      ? context.classification : "insufficient";
    const details = (context.details || []).map(group => `
      <section class="business-data-group"><h5>${esc(group.label)}</h5>
        ${(group.rows || []).map(row => `
          <div class="business-year"><strong>Ejercicio cerrado el ${esc(row.date)}</strong>
            <dl>${Object.entries(row).filter(([key]) => key !== "date").map(([key, value]) => `
              <div><dt>${esc(fields[key] || key)}</dt><dd>${typeof value === "number" && Number.isFinite(value)
                ? esc(new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1, notation: "compact" }).format(value))
                : "No disponible"}</dd></div>`).join("")}</dl>
          </div>`).join("") || '<p class="business-muted">Sin datos disponibles.</p>'}
      </section>`).join("");
    // Solo enlaces HTTPS de la fuente conocida; nunca insertar URLs arbitrarias del proveedor.
    const sources = (context.sources || []).filter(source => {
      try { const url = new URL(source.url); return url.protocol === "https:" && url.hostname === "finance.yahoo.com"; }
      catch { return false; }
    });
    document.getElementById("businessContent").innerHTML = `
      ${context.notice ? `<p class="business-notice" role="status">${esc(context.notice)}</p>` : ""}
      <section class="business-verdict business-${tone}">
        <span class="business-eyebrow">SOLIDEZ DEL NEGOCIO${context.is_stale ? " · LECTURA ANTERIOR" : ""}</span>
        <h4>${esc(context.label)}</h4><p>${esc(context.summary)}</p>
      </section>
      ${context.supported === false ? "" : `
        <div class="business-columns">
          <section><h4>A favor</h4>${list((context.strengths || []).slice(0, 3), "No hay evidencia suficiente para destacar fortalezas.")}</section>
          <section><h4>A vigilar</h4>${list((context.risks || []).slice(0, 3), context.classification === "insufficient"
            ? "La información disponible no permite descartar riesgos. Consulta las limitaciones en el detalle."
            : "No se han detectado alertas en las métricas evaluadas. Esto no descarta otros riesgos.")}</section>
        </div>
        <section class="business-valuation"><h4>¿Qué exige el precio?</h4><p>${esc(context.valuation || "Valoración no disponible.")}</p></section>
        <p class="business-scope">La solidez contable y el punto de entrada técnico responden a preguntas diferentes. Una lectura favorable no garantiza rentabilidad.</p>
        <details class="business-details"><summary>Ver datos y criterios de la lectura</summary>
          ${context.sector ? `<p>Sector: ${esc(context.sector)}${context.industry ? ` · ${esc(context.industry)}` : ""}</p>` : ""}
          <p>Importes en ${esc(context.financial_currency || "divisa no informada")}. Estados anuales; el PER utiliza beneficios de los últimos doce meses.</p>
          ${details}
          <h4>Cómo se interpreta</h4>
          <p>Favorable exige beneficios y caja libre positivos durante tres ejercicios, ingresos que no caen en el último año, margen neto que no pierda más de dos puntos porcentuales y deuda neta no superior a tres veces la caja operativa anual, o cubierta por efectivo e inversiones líquidas. Con dos o más señales adversas, la lectura es débil; con una, mixta.</p>
          <p>Si falta alguna dimensión o el sector, los estados tienen más de 18 meses o la empresa es financiera o inmobiliaria, la conclusión es información insuficiente. Son reglas generales, sin comparación sectorial. El umbral de PER 35 es orientativo.</p>
          <h4>Lectura completa</h4>${list(context.strengths, "Sin fortalezas identificadas.")}${list(context.risks, "Sin alertas identificadas en las dimensiones evaluadas.")}
          ${list(context.limitations, "No hay información adicional disponible.")}
        </details>`}
      <footer class="business-provenance">
        <p>Consultado: ${esc(formatDate(context.fetched_at))}${context.report_date ? ` · Último cierre anual de resultados: ${esc(context.report_date)}` : ""}</p>
        <p>Fuente: Yahoo Finance, consultada mediante yfinance. La consulta se conserva durante 24 horas.</p>
        <div class="business-sources">${sources.map(source => `<a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">${esc(source.label)} ↗</a>`).join("")}</div>
        ${!context.fetched_at ? '<button type="button" class="btn btn-secondary" id="retryBusiness">Volver a consultar</button><p>Tras un fallo, se espera hasta cinco minutos antes de repetir la descarga.</p>' : ""}
      </footer>`;
  }

  function closeBusiness() {
    const modal = document.getElementById("businessModal");
    if (!modal || modal.style.display === "none") return;
    requestNumber++;
    if (controller) controller.abort();
    modal.style.display = "none";
    if (previousFocus && previousFocus.isConnected) previousFocus.focus();
  }

  async function openBusiness(ticker, name, rememberFocus = true) {
    const modal = document.getElementById("businessModal");
    if (rememberFocus) previousFocus = document.activeElement;
    activeTicker = ticker;
    modal.style.display = "flex";
    document.getElementById("businessTitle").textContent = `${name || ticker} · ${ticker}`;
    document.getElementById("businessContent").innerHTML = '<div class="business-loading" role="status">Consultando la información del negocio…<p>La primera consulta puede tardar unos segundos.</p></div>';
    document.getElementById("closeBusinessModal").focus();
    if (controller) controller.abort();
    controller = new AbortController();
    const currentController = controller;
    const currentRequest = ++requestNumber;
    const timeout = setTimeout(() => currentController.abort(), 60000);
    try {
      const response = await fetch(`/api/business?ticker=${encodeURIComponent(ticker)}`, { signal: currentController.signal });
      if (!response.ok) throw new Error("No se pudo consultar esta empresa.");
      const context = EuroView.convert(await response.json());
      if (currentRequest === requestNumber) render(context);
    } catch (error) {
      if (currentRequest !== requestNumber) return;
      document.getElementById("businessContent").innerHTML = `<div class="business-loading" role="alert"><p>${error.name === "AbortError"
        ? "La consulta está tardando demasiado. Puedes volver a intentarlo."
        : "No se pudo obtener la ficha. Comprueba la conexión y que el panel esté actualizado."}</p><button class="btn btn-secondary" type="button" id="retryBusiness">Reintentar</button></div>`;
    } finally {
      clearTimeout(timeout);
    }
  }

  document.addEventListener("click", event => {
    const button = event.target.closest("[data-business-ticker]");
    if (button) {
      event.stopPropagation();
      openBusiness(button.dataset.businessTicker, button.dataset.businessName);
    }
    if (event.target.closest("#closeBusinessModal") || event.target.id === "businessModal") closeBusiness();
    if (event.target.closest("#retryBusiness")) openBusiness(activeTicker, activeTicker, false);
  });
  document.addEventListener("keydown", event => {
    const modal = document.getElementById("businessModal");
    if (!modal || modal.style.display === "none") return;
    if (event.key === "Escape") closeBusiness();
    if (event.key === "Tab") {
      const focusable = [...modal.querySelectorAll('button, a[href], summary')].filter(el => el.getClientRects().length);
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
})();
