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

### Un único seguimiento: el Diario automático

* El Diario conserva las señales automáticas, sus niveles iniciales, su evolución y sus resultados. Se mantienen las señales existentes y sus estadísticas. Consultar el bot no crea una entrada ni sustituye los niveles de una señal abierta.
* `/ver AMD` indica primero si hay seguimiento activo y muestra la señal registrada: fecha, periodo, entrada, stop original, stop de seguimiento, TP1, TP2, score inicial, último precio evaluado y estado. Después presenta una **lectura actual separada**, que no modifica esa señal. Compra, Venta, Fibonacci y Riesgo también distinguen el seguimiento del análisis actual.
* `/ver` añade una **posible zona de soporte** y el **contexto del volumen histórico**. Elige la referencia más próxima cuyo centro no supere el precio actual: una confluencia de al menos dos periodos, un retroceso Fibonacci o el mínimo observado. Conserva los límites de las confluencias y presenta niveles aislados con una banda orientativa de ±0,5%; no es un intervalo estadístico ni un suelo confirmado. En caída activa recuerda que pueden seguir apareciendo mínimos.
* El POC se describe como concentración **estimada** de volumen histórico y como posible soporte, resistencia o zona de negociación según su posición respecto al precio (margen de proximidad ±0,5%). El perfil de la app aproxima el volumen a partir de velas diarias y no muestra órdenes pendientes. Sin volumen real, un perfil TPO se identifica como frecuencia de precios y no se anuncia concentración de volumen. Referencia conceptual: [perfil de volumen de TradingView](https://www.tradingview.com/support/solutions/43000502040-volume-profile-indicators-basic-concepts/).
* Mientras el stop original y el de seguimiento coincidan al redondear a los decimales del activo, el bot muestra una sola línea **Stop**. Tras TP1 distingue el stop original y el stop del resto en la entrada.
* El bloque de seguimiento utiliza los niveles del Diario, incluido su stop; no sustituye ese stop por uno SSL o por un suelo nuevo. Al alcanzar TP1 se simula la salida del 50% y se protege el resto en la entrada. El resultado final se registra al alcanzar TP2, stop o la entrada después de TP1. `/historial` muestra sus resultados y la tasa de acierto. Las compras reales se gestionan en Cartera.
* Las nuevas señales guardan el periodo y el tipo de stop. En entradas antiguas sin periodo o sin stop original recuperable se muestra **No registrado**, sin deducirlo de la configuración actual. Si no hay señal abierta, el bot lo indica y puede mostrar la última señal cerrada.
* Se retiran el botón Seguir este plan y la sección de planes separados. Los antiguos comandos `/plan` y `/planes` redirigen a la consulta del Diario; los botones antiguos explican el cambio y no modifican registros. El archivo privado `.trade_plans.json`, si existe, se conserva intacto como archivo histórico local: ya no recibe nuevos planes ni se mezcla con el Diario, y sigue excluido de Git y del acceso HTTP directo.
* El seguimiento utiliza los datos disponibles en cada actualización, no una cotización continua ni órdenes reales. En el día de registro solo se evalúan los precios observados después de crear la señal; en días posteriores se revisan también los rangos diarios. Pueden faltar movimientos intradía entre consultas, y una vela sin secuencia conocida se evalúa comprobando primero el stop.

---
## 📊 Google Sheets (`google_apps_script.js`)

* **Pestaña `RESUMEN GENERAL`**: Vista consolidada de todos los activos con Score `0-100`, RSI(14), distancia a SMA 200, estructura del impulso, sentimiento CNN y barra Sparkline (limpiando filas antiguas automáticamente si eliminas algún activo).
* **Pestañas Individuales**: Desglose completo de retrocesos Fibonacci, confluencia técnica, niveles de Stop Loss / Take Profit y extensiones de venta.
