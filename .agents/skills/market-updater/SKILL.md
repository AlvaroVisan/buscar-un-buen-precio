---
name: market-updater
description: >-
  Use this skill when the user asks to update prices, modify calculation periods, adjust
  Fibonacci retracement logic, or troubleshoot market data synchronization in "Buscar un buen precio".
---

# Procedimiento para Actualización de Mercado y Sincronización

Esta skill detalla cómo funciona el motor de cálculo de Fibonacci, la extracción de precios y la sincronización con el panel web y Google Sheets.

## 1. Archivos Clave del Motor

- [market_updater.py](file:///e:/Proyectos/Buscar%20un%20buen%20precio/market_updater.py): Script principal de extracción y cálculo.
- [config.json](file:///e:/Proyectos/Buscar%20un%20buen%20precio/config.json): Parámetros de configuración (periodo, webhook, activos).
- [latest_data.json](file:///e:/Proyectos/Buscar%20un%20buen%20precio/latest_data.json): Archivo de datos calculados más reciente.
- [google_apps_script.js](file:///e:/Proyectos/Buscar%20un%20buen%20precio/google_apps_script.js): Script receptor en Google Sheets.

## 2. Comandos de Ejecución

- **Actualizar todo**:
  ```powershell
  python market_updater.py
  ```
  Esto descarga los datos históricos y precio actual con `yfinance`, calcula los retrocesos, guarda en `latest_data.json` y envía el webhook a Google Sheets.

- **Con un clic desde Windows**:
  Ejecutar [Actualizar_Precios.bat](file:///e:/Proyectos/Buscar%20un%20buen%20precio/Actualizar_Precios.bat).

## 3. Lógica de Retrocesos de Fibonacci y Señales

El cálculo del rango se realiza con el Mínimo y el Máximo del periodo seleccionado (`period` en `config.json`):
```python
rango = max_price - min_price
fib_levels = {
    "23.6%": max_price - 0.236 * rango,
    "38.2%": max_price - 0.382 * rango,
    "50.0%": max_price - 0.500 * rango,
    "61.8%": max_price - 0.618 * rango,  # Nivel Áureo
    "78.6%": max_price - 0.786 * rango   # Soporte clave
}
```

### Reglas de Señales:
1. `precio <= fib_786`: `"🟢 COMPRA FUERTE (Soporte 78.6%)"`
2. `precio <= fib_618`: `"🟢 COMPRA ÓPTIMA (Nivel Áureo 61.8%)"`
3. `precio <= fib_500`: `"🟢 ENTRADA BUENA (Retroceso 50%)"`
4. `precio <= fib_382`: `"🟡 EN OBSERVACIÓN (Caída moderada 38.2%)"`
5. `precio <= fib_236`: `"🟡 EN OBSERVACIÓN (Caída inicial 23.6%)"`
6. `precio > fib_236`: `"⚪ RESISTENCIA / CARO (Cerca de máximos)"`

## 4. Cambiar el Periodo de Análisis

Para cambiar el periodo temporal de cálculo:
1. Edita el valor `"period"` en [config.json](file:///e:/Proyectos/Buscar%20un%20buen%20precio/config.json).
2. Opciones estándar de `yfinance`:
   - `"1mo"`: 1 mes (muy a corto plazo).
   - `"3mo"`: 3 meses (por defecto, swing trading equilibrado).
   - `"6mo"`: 6 meses (tendencia intermedia).
   - `"1y"`: 1 año (largo plazo).
3. Vuelve a ejecutar `python market_updater.py`.

## 5. Diagnóstico de Problemas Comunes

- **Error de conexión con Google Sheets**: Si el webhook falla por permisos o URL cambiada, el script no se detiene; guarda los datos localmente en `latest_data.json` y el panel web sigue funcionando perfectamente.
- **Yahoo Finance rate limit o timeout**: Si algún ticker falla, revisar que el símbolo esté activo en Yahoo Finance (por ejemplo, buscar el ticker en finance.yahoo.com).
