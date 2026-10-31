---
name: manage-assets
description: >-
  Use this skill when the user asks to add, remove, or modify financial assets, tickers,
  or stocks in the "Buscar un buen precio" project. It guides ticker validation, config.json
  updates, and data verification.
---

# Procedimiento para Gestión de Activos y Tickers

Esta skill detalla el procedimiento estándar para añadir, modificar o eliminar activos en el proyecto.

## 1. Estructura de un Activo en `config.json`

Cada activo en [config.json](file:///e:/Proyectos/Buscar%20un%20buen%20precio/config.json) debe incluir exactamente:
- `tab`: Nombre corto que se usa para la pestaña de Google Sheets y el título de la tarjeta en el panel web (ej: `"AMD"`, `"Gold"`).
- `ticker`: Símbolo reconocido por Yahoo Finance (`yfinance`):
  - Acciones USA: `"NVDA"`, `"AAPL"`, `"TSLA"`, `"MSFT"`.
  - Materias Primas / Futuros: `"GC=F"` (Oro), `"CL=F"` (Petróleo), `"SI=F"` (Plata).
  - Criptomonedas: `"BTC-USD"`, `"ETH-USD"`.
  - Índices: `"^GSPC"` (S&P 500), `"^NDX"` (Nasdaq 100), `"^DJI"` (Dow Jones).
  - Acciones Europeas: `"ITX.MC"` (Inditex), `"SAN.MC"` (Santander).
- `name`: Nombre descriptivo completo para mostrar en la interfaz (ej: `"NVIDIA Corp"`, `"Bitcoin USD"`).

## 2. Pasos para Añadir un Nuevo Activo

1. **Editar [config.json](file:///e:/Proyectos/Buscar%20un%20buen%20precio/config.json)**:
   Añade el nuevo objeto a la lista `"assets"`:
   ```json
   {
     "tab": "Apple",
     "ticker": "AAPL",
     "name": "Apple Inc."
   }
   ```

2. **Validar la obtención de datos**:
   Ejecuta en consola una prueba de actualización para comprobar que el ticker descarga datos correctamente:
   ```powershell
   python market_updater.py
   ```

3. **Verificar el archivo de caché**:
   Asegúrate de que [latest_data.json](file:///e:/Proyectos/Buscar%20un%20buen%20precio/latest_data.json) contiene la nueva entrada con precios, mínimo, máximo y niveles de Fibonacci.

4. **Comprobar en el Panel Web**:
   Abre o refresca `http://localhost:5050` (o usa [Abrir_Panel_Web.bat](file:///e:/Proyectos/Buscar%20un%20buen%20precio/Abrir_Panel_Web.bat)) para confirmar que la tarjeta del nuevo activo aparece con su enlace directo a TradingView y su termómetro de Fibonacci.

## 3. Eliminación o Modificación de Activos

- Para eliminar, remueve el objeto correspondiente de `"assets"` en [config.json](file:///e:/Proyectos/Buscar%20un%20buen%20precio/config.json) y ejecuta `python market_updater.py`.
- Para cambiar el nombre visible o el ticker, modifica los campos en [config.json](file:///e:/Proyectos/Buscar%20un%20buen%20precio/config.json).
