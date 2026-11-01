---
name: market-updater
description: >-
  Use this skill when the user asks to update prices, modify calculation periods, adjust
  Fibonacci retracement logic, multi-timeframe clusters, ATR/RSI/Earnings calculations,
  or troubleshoot market data synchronization in "Buscar un buen precio".
---

# Procedimiento para Actualización de Mercado y Sincronización (v2)

Esta skill detalla cómo funciona el motor paralelo de cálculo de Fibonacci multi-periodo, confluencias (clusters), ATR(14), fechas de resultados (Earnings) y sincronización con Google Sheets.

## 1. Archivos Clave del Motor

- [market_updater.py](file:///e:/Proyectos/Buscar%20un%20buen%20precio/market_updater.py): Motor principal con descarga paralela (`ThreadPoolExecutor(max_workers=5)`), escritura atómica JSON y pre-cálculo de los 4 periodos (`1mo`, `3mo`, `6mo`, `1y`).
- [config.json](file:///e:/Proyectos/Buscar%20un%20buen%20precio/config.json): Parámetros de configuración públicos (`period`, `smart_market_hours`, `assets`).
- `secrets.json`: Credenciales privadas (`webhook_url`, `telegram.bot_token`, `telegram.chat_id`), fusionadas en memoria por `load_config()`.
- [latest_data.json](file:///e:/Proyectos/Buscar%20un%20buen%20precio/latest_data.json): Caché con métricas completas y diccionario `timeframes` por cada activo.
- [google_apps_script.js](file:///e:/Proyectos/Buscar%20un%20buen%20precio/google_apps_script.js): Receptor idempotente en Google Sheets (deduplica filas del mismo día y formatea `0.00` o `0.0000` según `decimals`).

## 2. Comandos de Ejecución

- **Actualizar todo respetando Horario Inteligente de Mercado**:
  ```powershell
  python market_updater.py
  ```
- **Forzar actualización (incluso en fin de semana o mercado cerrado)**:
  ```powershell
  python market_updater.py --force
  ```
- **Cambiar periodo activo por defecto y actualizar**:
  ```powershell
  python market_updater.py --period 6mo --force
  ```

## 3. Cálculos Técnicos Incluidos por Activo

1. **Multi-Timeframe Instantáneo (`timeframes`)**:
   - Con una sola descarga de `1y` de historia diaria en `yfinance`, se calculan simultáneamente los niveles de Fibonacci (`23.6%`, `38.2%`, `50.0%`, `61.8%`, `78.6%`), máximos/mínimos con fecha, tendencia (`UP`/`DOWN`) y chispa (`sparkline`) para `1mo` (22 sesiones), `3mo` (66 sesiones), `6mo` (126 sesiones) y `1y`.
   - Cambiar de periodo en la web (`POST /api/period`) es instantáneo (`0 ms`) porque activa el sub-diccionario pre-calculado en `latest_data.json` sin re-descargar de Yahoo Finance.
2. **Detector de Clusters de Fibonacci (`detect_fibonacci_clusters`)**:
   - Busca niveles áureos (`38.2%`, `50.0%`, `61.8%`, `78.6%`) de distintos periodos que converjan a menos de `1.2%` de distancia entre sí (exigiendo swings distintos `>= 2.5%` y al menos 2 ratios diferentes).
3. **Volatilidad y Riesgo (`ATR 14` y `Earnings`)**:
   - `calculate_atr_14(hist)` calcula el True Range medio de 14 sesiones y sugiere un Stop Loss dinámico a `2x ATR(14)` (`suggested_sl_2atr`).
   - `get_earnings_info(ticker_symbol, ticker_obj)` consulta y cachea por 12h en `.earnings_cache.json` la próxima fecha de presentación de resultados (`earnings_warning: true` si faltan `0–14` días).
4. **Horario Inteligente de Mercado (`is_any_market_open`)**:
   - Si `smart_market_hours: true` y es fin de semana (y no hay criptomonedas `24/7` en cartera), omite la descarga salvo que se pase `--force`.
5. **Motor de Liquidez Institucional (`compute_liquidity_metrics`)**:
   - **Volume Profile & Muro POC (24 bins + fallback TPO)**: Calcula `poc_price`, Área de Valor del 70% (`val_price`–`vah_price`) y la densidad de liquidez (`0–100%`, `🏦 Muro POC`, `🏦 Alta Liq.`, `💧 Media`, `🕳️ Vacío LVN`) sobre cada nivel de Fibonacci (`fib_liquidity`) y confluencias en zona de compra (`fib_poc_confluence`).
   - **Volumen Relativo (`RVOL`) y Absorción Institucional**: Compara el volumen con la media de 20 sesiones (`rvol`, `peak_rvol_3d`) y detecta velas de rechazo con mecha inferior larga en retroceso (`has_absorption`).
   - **Piscinas de Stops (`SSL Pool`) y Barridos SMC (`has_sweep`)**: Detecta Swing Lows / Dobles Suelos (`is_equal_lows`), barridos alcistas recuperados al cierre (Spring SMC) y calcula un Stop Loss protegido bajo la piscina de liquidez (`ssl_stop_loss` a `0.55x ATR` bajo el pool) para los 4 periodos (`1mo`, `3mo`, `6mo`, `1y`).
