# Reglas y Arquitectura del Proyecto: "Buscar un buen precio"

Este repositorio contiene un monitor inteligente de retrocesos de Fibonacci multi-periodo para activos financieros, con panel web interactivo, gestión de cartera real, diario de backtesting, bot de Telegram y sincronización automática con Google Sheets.

## Tecnologías Principales
- **Backend / Procesamiento**: Python 3 (`yfinance`, `requests`, `Flask`, `ThreadPoolExecutor`).
- **Frontend**: HTML5, Vanilla CSS moderno (Glassmorphism, tema oscuro) y JavaScript (ES6).
- **Integraciones**: TradingView (enlaces directos limpios), Telegram Bot API (alertas push y comandos interactivos) y Google Sheets (Google Apps Script Webhook idempotente).

## Skills Disponibles en `.agents/skills/`
1. **`manage-assets`**: Procedimiento para añadir, modificar o remover activos en `config.json`.
2. **`market-updater`**: Motor paralelo de Fibonacci multi-timeframe (`1mo`, `3mo`, `6mo`, `1y`), detector de confluencias (clusters), ATR(14), fechas de Earnings y sincronización.
3. **`web-panel-dev`**: Arquitectura del servidor Flask, cambio instantáneo de periodo (`0 ms`), modales interactivos y componentes UI.
4. **`portfolio-journal`**: Gestión de "💼 Mi Cartera Real" (`portfolio_manager.py`, DCA, P&L, pesos, Stop Loss ATR) y diario de efectividad de señales (`journal_manager.py`).
5. **`telegram-bot-ops`**: Configuración de `secrets.json`, alertas push anti-spam y comandos interactivos del bot de Telegram (`telegram_notifier.py`).
6. **`git-auto-sync`**: Procedimiento de sincronización automática con Git y GitHub tras cualquier cambio.

## Reglas de Desarrollo (Obligatorias)
1. **Estética Visual**: Mantener la estética visual premium (modo oscuro, tokens CSS en `style.css`, sin frameworks CSS pesados).
2. **Consistencia de Datos**: Probar siempre la consistencia de los datos en `latest_data.json` tras cualquier cambio en el backend.
3. **Compatibilidad Windows**: Conservar la compatibilidad de ejecución en Windows (`.bat` de un clic).
4. **Seguridad y Privacidad**: Nunca exponer `secrets.json`, `portfolio.json`, `.alerts_cache.json` ni `.earnings_cache.json` en el repositorio. `config.json` debe mantener siempre vacíos los campos de credenciales (`webhook_url`, `bot_token`, `chat_id`).
5. **Subida Automática a Git (SIN PREGUNTAR)**: **NUNCA preguntes al usuario si quiere hacer commit o subir los cambios a Git/GitHub**. Siempre que termines de implementar, corregir o modificar cualquier archivo del proyecto, ejecuta automáticamente `git add -A`, `git commit -m "..."` (con mensaje claro y descriptivo en español) y `git push` a la rama `main`.
