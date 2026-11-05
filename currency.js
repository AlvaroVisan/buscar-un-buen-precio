/* EUR/USD de referencia: los importes nunca salen del navegador. */
(() => {
  "use strict";
  const el = id => document.getElementById(id);
  const dialog = el("currencyDialog"), trigger = el("btnCurrencyConverter");
  const amount = el("currencyAmount"), direction = el("currencyDirection");
  const result = el("currencyResult"), status = el("currencyRateStatus");
  const refresh = el("refreshCurrencyRate"), error = el("currencyInputError");
  let quote = null, fetchedAt = 0, pending = false, failed = false;

  function render() {
    const euros = direction.value === "EUR", raw = amount.value.trim();
    el("currencyAmountLabel").textContent = euros ? "Importe en euros (EUR)" : "Importe en dólares (USD)";
    const value = Number(raw.replace(",", "."));
    const valid = /^\d+(?:[.,]\d{0,8})?$/.test(raw) && Number.isFinite(value) && value <= 1e12;
    error.hidden = valid || raw === "";
    error.textContent = error.hidden ? "" : "Introduce un importe entre 0 y 1 billón, sin separadores de miles.";
    amount.setAttribute("aria-invalid", String(!error.hidden));
    result.textContent = valid && quote ? new Intl.NumberFormat("es-ES", {
      style: "currency", currency: euros ? "USD" : "EUR", maximumFractionDigits: 2
    }).format(euros ? value * quote.rate : value / quote.rate) : "—";
  }
  function describeQuote() {
    const rate = direction.value === "EUR" ? quote.rate : 1 / quote.rate;
    const text = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 6 }).format(rate);
    const [year, month, day] = quote.date.split("-");
    return `1 ${direction.value} = ${text} ${direction.value === "EUR" ? "USD" : "EUR"} · Fecha del cambio: ${day}/${month}/${year}`;
  }
  function renderStatus() {
    if (!quote) return;
    status.textContent = describeQuote() + (failed ? " · No se pudo actualizar. Se conserva el último cambio consultado." : Date.now() - fetchedAt >= 3600000 ? " · Consulta anterior; actualiza el cambio." : "");
  }
  async function loadRate() {
    if (pending) return;
    pending = true;
    refresh.disabled = true;
    refresh.textContent = "Consultando…";
    status.textContent = quote ? `${describeQuote()} · Comprobando actualización…` : "Consultando el cambio de referencia…";
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch("/api/fx", {
        signal: controller.signal, credentials: "omit", referrerPolicy: "no-referrer"
      });
      if (!response.ok) throw new Error("No disponible");
      const data = await response.json();
      if (data.base !== "EUR" || data.quote !== "USD" || typeof data.rate !== "number" || !Number.isFinite(data.rate) || data.rate <= 0 || !/^\d{4}-\d{2}-\d{2}$/.test(data.date)) throw new Error("Cambio incorrecto");
      const date = new Date(`${data.date}T00:00:00Z`);
      if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== data.date || date.getTime() > Date.now() + 86400000) throw new Error("Fecha incorrecta");
      quote = { rate: data.rate, date: data.date };
      fetchedAt = Date.now(); failed = false;
      renderStatus();
    } catch {
      failed = true;
      if (quote) renderStatus();
      else status.textContent = "No se pudo obtener el cambio. Comprueba tu conexión y pulsa Reintentar.";
    } finally {
      clearTimeout(timeout); pending = false; refresh.disabled = false;
      refresh.textContent = quote ? "Actualizar cambio" : "Reintentar";
      render();
    }
  }
  trigger.addEventListener("click", () => {
    dialog.showModal(); amount.focus(); render(); renderStatus();
    if (!quote || Date.now() - fetchedAt >= 3600000) loadRate();
  });
  el("closeCurrencyDialog").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => trigger.focus());
  dialog.addEventListener("click", event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  // El diálogo nativo conserva el foco y gestiona Escape de forma independiente.
  dialog.addEventListener("keydown", event => event.stopPropagation());
  amount.addEventListener("input", render);
  direction.addEventListener("change", () => { render(); if (!pending) renderStatus(); });
  refresh.addEventListener("click", loadRate);
})();
