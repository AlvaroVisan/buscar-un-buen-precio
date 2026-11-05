/* Modelo de presentación: nunca modifica las respuestas nativas ni los registros. */
window.EuroView = (() => {
  let quote = null, loadedAt = 0;
  const moneyKeys = new Set(('price min max range atr_14 sma_200 stop_loss initial_stop_loss trailing_stop atr_trailing_stop take_profit_1 take_profit_2 tp1 tp2 ssl_pool_ref ext_127 ext_161 center min_price max_price breakout confirmation_level invalidation target budget simulated_budget invested invested_val market_val pnl pnl_abs pnl_at_sl_abs pnl_at_tp_abs realized_pnl_abs avg_entry exit_price amount average_price peak_equity eps_avg TotalRevenue NetIncome OperatingCashFlow FreeCashFlow TotalDebt CashCashEquivalentsAndShortTermInvestments').split(' '));
  const monetary = (key, parent) => moneyKeys.has(key) || /(?:_price|_stop_loss|_per_share)$/.test(key) || ['custom_sl', 'custom_tp', 'effective_sl', 'effective_tp'].includes(key) || parent === 'fib_levels' || (parent === 'rebound_bars' || parent === 'chart_bars') && ['Open', 'High', 'Low', 'Close'].includes(key);
  const isUsd = currency => currency === '$' || currency === 'USD';
  const isEur = currency => currency === '€' || currency === 'EUR';
  const factor = currency => quote && isUsd(currency) ? 1 / quote.rate : 1;
  function walk(value, inherited = '$', parent = '') {
    if (Array.isArray(value)) return value.map(row => walk(row, inherited, parent));
    if (!value || typeof value !== 'object') return value;
    const currency = String(value.ticker || '').startsWith('^') ? 'puntos' : value.currency || value.financial_currency || inherited;
    const ratio = factor(currency);
    const output = {};
    for (const [key, field] of Object.entries(value)) {
      if (typeof field === 'number' && Number.isFinite(field) && monetary(key, parent)) output[key] = field * ratio;
      else if (typeof field === 'string' && (ratio !== 1 || currency === 'puntos')) output[key] = field.replace(/\$(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)/g, (_, raw) => (Number(raw.replaceAll(',', '')) * ratio).toLocaleString('es-ES', {minimumFractionDigits: 2, maximumFractionDigits: 4}) + (currency === 'puntos' ? ' puntos' : ' €'));
      else output[key] = walk(field, currency, key);
    }
    if ('currency' in value) {
      output.currency = quote && (isUsd(currency) || isEur(currency)) ? '€' : currency;
      if (quote && output.currency === '€') output.__eur_rate = value.__eur_rate || quote.rate;
    }
    if ('financial_currency' in value && quote && (isUsd(currency) || isEur(currency))) output.financial_currency = 'EUR';
    return output;
  }
  function convert(data) {
    if (!quote || !data || data.__eur_view) return data;
    const output = walk(data);
    // Las vigilancias no guardan divisa; resolverla mediante el ticker registrado.
    if (data.watches) {
      for (const [ticker, watch] of Object.entries(data.watches)) output.watches[ticker] = walk({...watch, ticker, currency: currencies.get(ticker) || '$'});
    }
    if (data.summary?.totals_by_currency) {
      const summary = output.summary;
      const totals = {};
      for (const [currency, bucket] of Object.entries(data.summary.totals_by_currency)) {
        const converted = walk(bucket, currency);
        const target = converted.currency;
        const sum = totals[target] ||= {currency: target, invested: 0, market_val: 0, pnl_abs: 0, positions: 0};
        for (const key of ['invested', 'market_val', 'pnl_abs', 'positions']) sum[key] += converted[key] || 0;
        sum.pnl_pct = sum.invested ? sum.pnl_abs / sum.invested * 100 : 0;
      }
      const realized = {};
      for (const [currency, amount] of Object.entries(data.summary.realized_by_currency || {})) {
        const target = isUsd(currency) || isEur(currency) ? '€' : currency;
        realized[target] = (realized[target] || 0) + amount * factor(currency);
      }
      const primary = totals['€'] || Object.values(totals)[0] || {currency: '€', invested: 0, market_val: 0, pnl_abs: 0, pnl_pct: 0};
      Object.assign(summary, {totals_by_currency: totals, realized_by_currency: realized, primary_currency: primary.currency, primary_invested: primary.invested, primary_market_val: primary.market_val, primary_pnl_abs: primary.pnl_abs, primary_pnl_pct: primary.pnl_pct, primary_realized_pnl: realized[primary.currency] || 0});
    }
    output.__eur_view = true;
    output.__eur_fx = `${quote.date}:${quote.rate}`;
    return output;
  }
  const currencies = new Map();
  async function init() {
    if (loadedAt && Date.now() - loadedAt < 3600000) return;
    loadedAt = Date.now();
    try {
      const response = await fetch('/api/fx');
      const data = await response.json();
      quote = response.ok && data.base === 'EUR' && data.quote === 'USD' && Number.isFinite(data.rate) && data.rate > 0 ? data : null;
    } catch { quote = null; }
    if (!quote) loadedAt = 0;
    const notice = document.getElementById('euroDisplayNotice');
    if (notice) notice.textContent = quote ? `Vista en euros · Cambio de referencia del ${quote.date}. Porcentajes en la moneda original; el cambio puede diferir del de tu bróker.` : 'Cambio a euros no disponible: se muestran las monedas originales. Los formularios usan la moneda mostrada.';
  }
  function market(data) {
    for (const item of data?.data || []) currencies.set(item.ticker, item.currency || '$');
    return convert(data);
  }
  function chart(container, item, period, large = false) {
    container.replaceChildren();
    const rows = (item?.chart_bars?.length ? item.chart_bars : item?.rebound_bars || []).slice(-({ '1mo': 22, '3mo': 63, '6mo': 126, '1y': 252 }[period] || 63)).filter(row => ['High', 'Low', 'Close'].every(key => Number.isFinite(row[key])));
    if (!rows.length) { container.textContent = 'El gráfico estará disponible tras la próxima actualización de precios.'; return; }
    const width = Math.max(320, Math.min(1100, container.clientWidth || 900)), height = large ? 450 : 250, pad = 100;
    const low = Math.min(...rows.map(row => row.Low)), high = Math.max(...rows.map(row => row.High));
    const range = high - low || Math.max(1, high * .01);
    const y = value => 16 + (high - value) / range * (height - 42);
    const step = (width - pad) / rows.length;
    const escape = value => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[ch]));
    const price = value => escape(formatPrice(value, item));
    let shapes = '';
    for (let tick = 0; tick < 4; tick++) {
      const value = low + range * tick / 3, pos = y(value);
      shapes += `<line x1="0" x2="${width - pad}" y1="${pos}" y2="${pos}" stroke="#292d35"/><text x="${width - pad + 5}" y="${pos + 4}" fill="#aaa" font-size="11">${price(value)}</text>`;
    }
    rows.forEach((row, index) => {
      const open = Number.isFinite(row.Open) ? row.Open : index ? rows[index - 1].Close : row.Close;
      const color = row.Close >= open ? '#5cc092' : '#df8181', x = step * (index + .5);
      shapes += `<g><title>${escape(row.time)} · ${price(row.Close)}</title><line x1="${x}" x2="${x}" y1="${y(row.High)}" y2="${y(row.Low)}" stroke="${color}"/><rect x="${x - step * .3}" y="${Math.min(y(open), y(row.Close))}" width="${Math.max(1, step * .6)}" height="${Math.max(1, Math.abs(y(open) - y(row.Close)))}" fill="${color}"/></g>`;
    });
    container.innerHTML = `<svg role="img" aria-label="Gráfico de ${escape(item.ticker)} en ${escape(item.currency)}" viewBox="0 0 ${width} ${height}" style="width:100%;height:auto;min-height:${large ? 300 : 180}px">${shapes}</svg>`;
    const note = document.createElement('p');
    note.className = 'journal-method-note';
    note.textContent = `${rows[0].time} — ${rows.at(-1).time} · ${item.chart_bars?.length ? 'Velas diarias' : 'Velas horarias'}. Importes convertidos al cambio de referencia mostrado; no reconstruye el cambio histórico de cada vela.`;
    container.append(note);
  }
  return {init, convert, market, chart, inputMeta: item => item?.__eur_rate || quote ? {input_currency: 'EUR', input_rate: item?.__eur_rate || quote.rate} : {}, get quote() {return quote;}};
})();
