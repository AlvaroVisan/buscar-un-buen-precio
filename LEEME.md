# 📈 Proyecto: "Buscar un buen precio"
### Monitor Inteligente de Retrocesos de Fibonacci, Confluencia Técnica y Gestión de Riesgo

Este proyecto automatiza la extracción en paralelo de datos de mercado (acciones de EE. UU. y Europa, Materias Primas, Índices, Forex y Criptomonedas), evalúa la **confluencia técnica** (`Fibonacci + RSI(14) + SMA 200 + Estructura del Impulso`) junto al sentimiento **CNN Fear & Greed**, y sincroniza todo con tu **Panel Web**, **Bot de Telegram 24/7** y **Google Sheets**.

---

## ⚙️ Instalación Rápida (Requisitos)

```powershell
pip install -r requirements.txt
```

Las credenciales privadas (`bot_token`, `chat_id` y `webhook_url`) se almacenan automáticamente de forma local en `secrets.json` (excluido de Git por seguridad).

---

## 🎯 ¿Cómo usarlo en tu día a día?

### 1. Panel Web Interactivo (`Abrir_Panel_Web.bat`)
* Haz doble clic en **`Abrir_Panel_Web.bat`** (abre `http://localhost:5050` con servidor multihilo, auto-scheduler con **Horario Inteligente de Mercado** y escucha de Telegram en segundo plano). El servidor escucha exclusivamente en `127.0.0.1`: el panel y sus API son de uso local en este equipo. Rechaza peticiones desde otros orígenes del navegador; no requiere contraseña local. El bot de Telegram sigue funcionando mediante su conexión saliente.
* Cambio **Multi-Timeframe instantáneo (`0 ms`)** entre `1 Mes`, `3 Meses`, `6 Meses` y `1 Año`, con detección automática de **Clusters de Fibonacci Multi-Timeframe** y aviso de **próximos resultados (*Earnings*)**.
* Incluye **4 modos de operación**:
  * 🟢 **Modo Compra (Dip Hunter)**: Escalera de Fibonacci (`23.6%` a `78.6%`), Score `0-100`, detección de impulso alcista vs. caída activa, mini-gráficos TradingView y **Calculadora de Posición / Riesgo** (con selector entre Stop Fibonacci `78.6%` y Stop por Volatilidad `2x ATR(14)` + unidades fraccionadas).
  * 🔴 **Modo Venta (Profit Taking)**: Radar de sobrecompra, extensiones `127.2%` y `161.8%`, Trailing Stop y simulador de recogida parcial de beneficios.
  * 📔 **Diario de Oportunidades**: Historial automático con tasa de acierto (*Win Rate*), movimiento automático de Stop a *Break-Even* tras `TP1` y seguimiento de velas diarias.
  * 💼 **Mi Cartera Real**: Seguimiento local (`portfolio.json`) de tus compras reales, precio medio ponderado (*DCA*), PnL abierto en vivo, termómetro `Stop Loss ↔ Entrada ↔ Take Profit` y ventas parciales/totales con beneficio realizado.

### 2. Bot Interactivo de Telegram (24/7)
* Configúralo en 1 minuto desde el icono de campana 🔔 del panel web (`Alertas Móvil`).
* Botones **Inline** interactivos bajo cada alerta y ficha técnica (`[1M] [3M] [6M] [1A]`, `[🛡️ Lote 50/100/250]`, `[📈 TradingView ↗]`).
* Comandos disponibles desde el móvil: `/resumen`, `/alertas`, `/cartera`, `/ver <TICKER>`, `/riesgo <TICKER> [presupuesto]`, `/add <TICKER> [Nombre]`, `/del <TICKER>`, `/venta`, `/historial`, `/periodo <1mo|3mo|6mo|1y>` y `/sync`.

### 3. Actualización Rápida en 1 Clic (`Actualizar_Precios.bat`)
* Ejecuta **`Actualizar_Precios.bat`** para descargar toda la cartera en paralelo (~1.5 - 2 s), actualizar `latest_data.json`, disparar alertas y refrescar Google Sheets.

---

## 📊 Google Sheets (`google_apps_script.js`)

* **Pestaña `RESUMEN GENERAL`**: Vista consolidada de todos los activos con Score `0-100`, RSI(14), distancia a SMA 200, estructura del impulso, sentimiento CNN y barra Sparkline (limpiando filas antiguas automáticamente si eliminas algún activo).
* **Pestañas Individuales**: Desglose completo de retrocesos Fibonacci, confluencia técnica, niveles de Stop Loss / Take Profit y extensiones de venta.
