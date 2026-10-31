# Reglas y Arquitectura del Proyecto: "Buscar un buen precio"

Este repositorio contiene un monitor inteligente de retrocesos de Fibonacci para activos financieros, con panel web interactivo y sincronización automática.

## Tecnologías Principales
- **Backend / Procesamiento**: Python 3 (`yfinance`, `requests`, `Flask`).
- **Frontend**: HTML5, Vanilla CSS moderno (Glassmorphism, tema oscuro) y JavaScript (ES6).
- **Integraciones**: TradingView (enlaces directos) y Google Sheets (Google Apps Script Webhook).

## Skills Disponibles en `.agents/skills/`
1. **`manage-assets`**: Procedimiento para añadir, modificar o remover activos en `config.json`.
2. **`market-updater`**: Ejecución de cálculos de Fibonacci, periodos temporales y sincronización.
3. **`web-panel-dev`**: Arquitectura del servidor Flask y componentes de la interfaz de usuario.

## Reglas de Desarrollo
1. Mantener la estética visual premium (modo oscuro, tokens CSS en `style.css`, sin frameworks CSS pesados).
2. Probar siempre la consistencia de los datos en `latest_data.json` tras cualquier cambio en el backend.
3. Conservar la compatibilidad de ejecución en Windows (`.bat` de un clic).
4. Commits claros y descriptivos al sincronizar con GitHub.
