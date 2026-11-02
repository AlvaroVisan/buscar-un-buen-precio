---
name: market-updater
description: >-
  Mantener las cotizaciones, cálculos Fibonacci multi-periodo, RSI, ATR, liquidez,
  resultados y sincronización de Buscar un buen precio. Usar también para investigar
  precios inmóviles, descargas fallidas y cadencia automática.
---

# Motor de mercado

## Puntos de entrada reales

- [market_updater.py](../../../market_updater.py): `run_updater(target_period=None, sync_sheets=True, custom_webhook=None)` coordina descargas paralelas, JSON, Sheets, Telegram y Diario bajo `SYNC_LOCK`.
- `fetch_asset_data()` obtiene historia diaria de un año, con fallback a dos años, y usa su último `Close` como precio. No hay streaming ni garantía de coincidencia con TradingView.
- `_compute_timeframe_snapshot()` calcula los periodos; `detect_fibonacci_clusters()`, `compute_liquidity_metrics()`, `compute_rsi()`, `compute_atr()` y `fetch_earnings_info()` contienen las fórmulas. Lee sus parámetros actuales antes de cambiar umbrales.
- [app.py](../../../app.py): `auto_scheduler_worker()` y `POST /api/sync` llaman al mismo motor dentro del proceso, sin un actualizador externo obligatorio.

## Periodos y datos persistentes

`SUPPORTED_PERIODS` contiene `1mo`, `3mo`, `6mo`, `1y`. `timeframes` conserva los cálculos por periodo. `switch_cached_period()` proyecta la ventana elegida sobre los campos principales y persiste la preferencia; no debe requerir red si existe esa ventana. El frontend también realiza la proyección inmediata.

`latest_data.json` contiene `timestamp`, `period`, `market_sentiment`, `market_hours`, `failed_tickers` y `data`. Cada activo identifica ticker, precio, divisa, decimales, periodos, indicadores y riesgo. Se escribe con `_atomic_write_json()`.

Ante una descarga fallida se conserva una cotización anterior válida, con `is_stale=true` y su `last_success_at` original. No conviertas errores en precios cero ni presentes la caché como dato fresco. Las salidas hacia Sheets, alertas y Diario excluyen los activos obsoletos.

El POC y el área de valor son estimaciones históricas construidas con velas diarias. Distingue `profile_type="VOLUME"` y `has_real_volume` de un fallback TPO; no equivalen a órdenes pendientes verificadas. El score técnico tampoco es una probabilidad calibrada de éxito.

## Cadencia y comandos

- Lee `config.scheduler`: `enabled`, `interval_minutes`, `smart_hours_only`. La configuración actual debe consultarse, no asumirse por los valores por defecto.
- El scheduler comprueba cada 30 segundos y hace una primera consulta tras arrancar. Con horario inteligente, bolsas cerradas pueden pausar consultas o ampliar a un mínimo de 120 minutos cuando hay cripto. El panel sondea la caché cada 20 segundos: sondear no descarga precios.
- Solo se avanza el reloj del scheduler tras una ejecución sin excepción; comprueba también `failed_tickers`, porque una ejecución puede acabar con fallos parciales.
- CLI actual: `python market_updater.py` o `python market_updater.py 6mo`. El periodo es posicional. `main()` no implementa `--force` ni `--period`; no documentes esos flags como operativos. El horario inteligente se aplica en el scheduler, no como filtro general del CLI.
- Para arrancar o reiniciar servicios, usa [app-launcher](../app-launcher/SKILL.md).

## Validación

Ejecuta `python -m unittest test_quote_failures test_auto_scheduler` cuando cambies este flujo. Añade pruebas de las fórmulas que realmente modifiques con datos controlados; simula las salidas externas.

Después de cambios de backend valida que el JSON se puede leer, no hay tickers duplicados, los precios presentes son finitos y positivos y el score/campos proyectados corresponden al periodo seleccionado. Comprueba conservación de cotizaciones, fechas de éxito y fallos explícitos. No lances una sincronización real solo para probar una función pura: puede enviar alertas, modificar el Diario y publicar en Sheets incluso con `sync_sheets=False`, que desactiva únicamente Sheets.

Para tocar niveles que consume el Diario, consulta [portfolio-journal](../portfolio-journal/SKILL.md). Finaliza con [git-auto-sync](../git-auto-sync/SKILL.md).
