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

### 1. Arranque único (`Iniciar_Aplicacion.bat`)
* Haz doble clic en **`Iniciar_Aplicacion.bat`**. Comprueba Python 3.10 o superior y las dependencias, inicia el panel en `http://127.0.0.1:5050`, la actualización automática de precios y el bot de Telegram configurado. Si ya hay un panel funcionando, abre esa instancia sin iniciar otros servicios. Si otro programa ocupa el puerto, muestra un error y no lo cierra.
* Mantén la ventana de la aplicación abierta y el equipo sin suspender para que los servicios continúen. Para detenerlos, pulsa **Ctrl+C** en esa ventana. Los precios se consultan con el intervalo configurado (30 minutos actualmente); el horario inteligente es opcional. Para aplicar cambios del código Python, detén la instancia anterior y abre de nuevo el lanzador.
* El servidor escucha exclusivamente en `127.0.0.1`: el panel y sus API son de uso local en este equipo. Rechaza peticiones desde otros orígenes del navegador; no requiere contraseña local. El bot de Telegram sigue funcionando mediante su conexión saliente.
* Cambio **Multi-Timeframe instantáneo (`0 ms`)** entre `1 Mes`, `3 Meses`, `6 Meses` y `1 Año`, con detección automática de **Clusters de Fibonacci Multi-Timeframe** y aviso de **próximos resultados (*Earnings*)**.
* Incluye **4 modos de operación**:
  * 🟢 **Modo Compra (Dip Hunter)**: Escalera de Fibonacci (`23.6%` a `78.6%`), Score `0-100`, detección de impulso alcista vs. caída activa, mini-gráficos TradingView y **Calculadora de Posición / Riesgo** (con selector entre Stop Fibonacci `78.6%` y Stop por Volatilidad `2x ATR(14)` + unidades fraccionadas).
  * 🔴 **Modo Venta (Profit Taking)**: Radar de sobrecompra, extensiones `127.2%` y `161.8%`, Trailing Stop y simulador de recogida parcial de beneficios.
  * 📔 **Diario de Oportunidades**: Historial automático con tasa de acierto (*Win Rate*), movimiento automático de Stop a *Break-Even* tras `TP1` y seguimiento de velas diarias.
  * 💼 **Mi Cartera Real**: Seguimiento local (`portfolio.json`) de tus compras reales, precio medio ponderado (*DCA*), PnL abierto en vivo, termómetro `Stop Loss ↔ Entrada ↔ Take Profit` y ventas parciales/totales con beneficio realizado.

### Ver negocio: contexto de las empresas

Las tarjetas de empresas, en Compra y Venta, incluyen **Ver negocio**. Abre un resumen de solidez **favorable, mixta, débil o información insuficiente**, con puntos a favor, aspectos a vigilar y una lectura separada del precio. No altera el score técnico ni las señales del diario.

La lectura aplica reglas visibles a tres ejercicios de beneficios y caja libre, la evolución anual de ingresos y margen neto, y la deuda neta frente a caja operativa. Requiere datos completos, sector identificado, cierres alineados y estados recientes para emitir una conclusión. Las empresas financieras e inmobiliarias se marcan como información insuficiente porque requieren métricas específicas. Los índices, futuros y criptomonedas no muestran este botón.

Los estados se obtienen de Yahoo Finance mediante yfinance al abrir la ficha y se conservan **24 horas** en `.business_cache.json`, ignorado por Git y bloqueado por HTTP. No intervienen en la actualización de precios de 30 minutos. Si falla una renovación, se identifica la lectura anterior y se conserva su fecha; sin datos previos se informa de que no hay información suficiente. Los fallos se reintentan después de cinco minutos.

La ficha muestra fecha de consulta, cierre anual, fuentes y un desplegable con los datos y criterios. La valoración usa el PER de los últimos doce meses, sin presentarlo como una comparación sectorial o histórica. Esta lectura contable no evalúa por sí sola ventajas competitivas, gestión, litigios o concentración del negocio.

### 2. Bot Interactivo de Telegram (24/7)
* Configúralo en 1 minuto desde el icono de campana 🔔 del panel web (`Alertas Móvil`).
* Botones **Inline** interactivos bajo cada alerta y ficha técnica (`[1M] [3M] [6M] [1A]`, `[🛡️ Lote 50/100/250]`, `[📈 TradingView ↗]`).
* Comandos disponibles desde el móvil: `/resumen`, `/alertas`, `/cartera`, `/ver <TICKER>`, `/riesgo <TICKER> [presupuesto]`, `/add <TICKER> [Nombre]`, `/del <TICKER>`, `/venta`, `/historial`, `/periodo <1mo|3mo|6mo|1y>` y `/sync`.

### 3. Actualizar precios cuando quieras
* Usa **Actualizar** dentro del panel, o `/actualizar` en Telegram, para consultar todos los activos sin esperar al siguiente ciclo automático. Ya no hay un `.bat` separado para esta tarea.
* El único archivo de arranque es `Iniciar_Aplicacion.bat`; sustituye a `Abrir_Panel_Web.bat` y `Actualizar_Precios.bat`. Conserva el resto de los archivos del proyecto junto al lanzador.

### Seguir un plan del bot sin cambiar sus niveles

* Consulta `/compra AMD` o la ficha de un activo y pulsa **Seguir este plan**. El botón conserva la entrada propuesta, el stop mostrado (SSL si lo hay), TP1, TP2, periodo y fecha **de ese mensaje**, aunque el mercado o el periodo cambien antes de pulsarlo. Las consultas y las alertas no inician seguimientos por sí solas.
* Solo se mantiene un plan abierto por activo y chat. Otra consulta muestra el estado del plan guardado y distingue el análisis nuevo. Pulsar repetidamente un botón nunca duplica ni sustituye el plan. Los botones pertenecen al chat al que se envió el mensaje; las propuestas no guardadas caducan a los 30 días.
* `/planes` muestra tus planes y su tasa de acierto; `/plan AMD` abre el último de ese activo. Al tocar TP1 se simula vender el 50% y se protege el resto al precio de entrada. Termina en TP2, stop o vuelta a la entrada después de TP1. Las entradas límite esperan a que se observe su precio; una invalidación antes de entrar no cuenta como pérdida. El historial se conserva sin caducidad y no se inicia otro plan automáticamente.
* Puedes **Cancelar seguimiento**, con confirmación. Se conserva como cancelado y queda excluido de la tasa de acierto. Los planes elegidos tienen su sección y estadísticas propias en el **Diario web**, separadas de las señales automáticas.
* El seguimiento empieza al guardar, sin atribuir máximos o mínimos anteriores a esa acción. Se revisa en cada actualización del mercado, recuperando las velas completas disponibles de cinco minutos. No se usan velas que solapen el guardado o una observación puntual ya evaluada. Puede haber toques sin observar en esos tramos o cuando faltan datos. Una vela que toca varios niveles sin orden conocido se resuelve de forma conservadora y se identifica como ambigua. Los precios de salida son simulados a los niveles previstos, sin comisiones ni garantía de ejecución en gaps.
* Estos planes sirven tanto para contrastar una idea como para acompañar una compra real; **no registran compras ni ejecutan órdenes**. El retorno del plan utiliza su entrada propuesta; registra tu precio y unidades reales en Cartera para ver el P&L real. Los planes y borradores se guardan localmente en `.trade_plans.json`, excluido de Git y del acceso HTTP directo. El Diario web devuelve los planes sin identificadores de chat ni borradores.

La descarga intradía utiliza la [API de históricos de yfinance](https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html), cuya cobertura reciente es limitada. Si se recupera un tramo incompleto se muestra el aviso; se conservan los niveles originales.

---

## 📊 Google Sheets (`google_apps_script.js`)

* **Pestaña `RESUMEN GENERAL`**: Vista consolidada de todos los activos con Score `0-100`, RSI(14), distancia a SMA 200, estructura del impulso, sentimiento CNN y barra Sparkline (limpiando filas antiguas automáticamente si eliminas algún activo).
* **Pestañas Individuales**: Desglose completo de retrocesos Fibonacci, confluencia técnica, niveles de Stop Loss / Take Profit y extensiones de venta.
