---
name: web-panel-dev
description: >-
  Use this skill when the user asks to modify, redesign, style, or add features to the
  web panel UI (HTML, CSS, JS, Flask) of "Buscar un buen precio".
---

# Procedimiento para Desarrollo y Modificación del Panel Web (v2)

Esta skill describe la arquitectura, endpoints Flask y componentes interactivos del panel web.

## 1. Arquitectura del Servidor Backend ([app.py](file:///e:/Proyectos/Buscar%20un%20buen%20precio/app.py))

Servidor Flask en `http://localhost:5050` con bloqueo de concurrencia (`_update_lock`) para evitar solapamientos:
- `GET /`: Sirve [index.html](file:///e:/Proyectos/Buscar%20un%20buen%20precio/index.html).
- `GET /api/data` y `GET /api/config`: Devuelven `latest_data.json` y la configuración pública.
- `POST /api/update`: Ejecuta `python market_updater.py --force` con `timeout=180` y `_update_lock`.
- `POST /api/period`: Cambia el periodo activo (`1mo`, `3mo`, `6mo`, `1y`) en `0 ms` proyectando los datos ya pre-calculados en `timeframes` dentro de `latest_data.json` (solo invoca `market_updater.py` si faltan datos pre-calculados).
- `POST /api/assets` y `DELETE /api/assets/<ticker>`: Añaden o eliminan activos validando primero el ticker en `yfinance`.
- `GET /api/journal`: Devuelve las señales y métricas de efectividad de `journal.json`.
- `GET /api/portfolio`, `POST /api/portfolio/buy`, `POST /api/portfolio/close`, `DELETE /api/portfolio/<pos_id>`: CRUD completo de "💼 Mi Cartera Real".
- `POST /api/telegram/test`: Envía un mensaje de prueba al bot de Telegram.

## 2. Arquitectura Frontend ([index.html](file:///e:/Proyectos/Buscar%20un%20buen%20precio/index.html), [style.css](file:///e:/Proyectos/Buscar%20un%20buen%20precio/style.css), [app.js](file:///e:/Proyectos/Buscar%20un%20buen%20precio/app.js))

1. **Seguridad y Renderizado DOM**:
   - **Prohibido usar `onclick` inline con interpolación de strings** en HTML generado dinámicamente. Usa siempre atributos `data-*` (`data-del-ticker`, `data-calc-ticker`, `data-buy-ticker`, `data-close-id`) con delegación de eventos y `escapeHtml()`.
2. **Cambio de Periodo Instantáneo (`switchPeriod`)**:
   - Al pulsar `1M`, `3M`, `6M` o `1A`, `app.js` proyecta inmediatamente `asset.timeframes[period]` en el cliente (`0 ms`), re-renderiza la cuadrícula y persiste la preferencia en segundo plano mediante `POST /api/period`.
3. **Componentes en Tarjeta (`createCardHTML`)**:
   - **Badges técnicos**: RSI(14), Tendencia (`Alcista`/`Bajista`), Confluencia Multi-Timeframe (`🔥 CONFLUENCIA`) y alerta de Resultados (`⚠️ Resultados en Xd`).
   - **Posición en Cartera**: Si el usuario tiene acciones del activo, muestra badge `💼 En Cartera (X acc. · Peso Y%)` y banda con Precio Medio, P&L latente y Stop Loss ATR.
   - **Sparkline SVG Interactiva**: Línea de precios con bandas horizontales discontinuas para el `50%`, `61.8%` y `78.6%` de Fibonacci.
   - **Escalera de Fibonacci con Clic-para-Copiar**: Al hacer clic en cualquier fila `.fib-step`, copia el precio exacto al portapapeles.
   - **Acciones Rápidas**: Botón `💼 Comprar / DCA`, `🧮 Calc. Posición` (con Stop Loss `2x ATR(14)` autocompletado) y enlace limpio a TradingView (`getTradingViewUrl`).
4. **Modales Interactivos**:
   - **💼 Mi Cartera Real (`#portfolioModal`)**: Resumen de Valor Total, P&L Abierto/Cerrado, tabla de posiciones abiertas con barra de peso, acciones de DCA/Cerrar/Borrar e historial de operaciones cerradas.
   - **📈 Efectividad de Señales (`#journalModal`)**: Win-Rate y tabla comparativa de retorno al cierre (`Close`) y pico máximo (`Máx`) a `+7d`, `+15d` y `+30d`.
   - **🧮 Calculadora de Riesgo (`#calcModal`)**: Calcula acciones a comprar e importe total según capital, `%` de riesgo y Stop Loss (`78.6% Fib` o `2x ATR(14)`).
