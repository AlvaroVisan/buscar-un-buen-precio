# Reglas y Arquitectura del Proyecto: "Buscar un buen precio"

Este repositorio contiene un monitor inteligente de retrocesos de Fibonacci multi-periodo para activos financieros, con panel web interactivo, gestión de cartera real, diario de backtesting, bot de Telegram y sincronización automática con Google Sheets.

## Tecnologías Principales
- **Backend / Procesamiento**: Python 3.10 o superior (`http.server`, `yfinance`, `requests`, `pandas`, `ThreadPoolExecutor`). El servidor no usa Flask.
- **Frontend**: HTML5, Vanilla CSS con tokens de tema oscuro y JavaScript (ES6), sin frameworks pesados.
- **Integraciones**: TradingView (enlaces directos limpios), Telegram Bot API (alertas push y comandos interactivos) y Google Sheets (Google Apps Script Webhook idempotente).

## Skills Disponibles en `.agents/skills/`
1. **`manage-assets`**: Procedimiento para añadir, modificar o remover activos en `config.json`.
2. **`market-updater`**: Motor paralelo de Fibonacci multi-timeframe (`1mo`, `3mo`, `6mo`, `1y`), detector de confluencias (clusters), ATR(14), fechas de Earnings y sincronización.
3. **`web-panel-dev`**: Servidor HTTP multihilo, rutas reales de API, cambio de periodo desde caché, modales y componentes UI.
4. **`portfolio-journal`**: Gestión de "💼 Mi Cartera Real" (`portfolio_manager.py`, DCA, P&L, pesos, Stop Loss ATR) y diario de efectividad de señales (`journal_manager.py`).
5. **`telegram-bot-ops`**: Configuración de `secrets.json`, alertas push anti-spam y comandos interactivos del bot de Telegram (`telegram_notifier.py`).
6. **`git-auto-sync`**: Procedimiento de sincronización automática con Git y GitHub tras cualquier cambio.
7. **`app-launcher`**: Arranque único de Windows, puertos, procesos duplicados, reinicios y carga de versiones nuevas del bot.
8. **`business-context`**: Datos, reglas de solidez, valoración, caché y modal de «Ver negocio».

## Puntos de Entrada y Contratos

- **Arranque único**: `Iniciar_Aplicacion.bat` → `launcher.py` → `app.py`. El panel inicia el scheduler y el listener de Telegram; no hacen falta otros `.bat`. Reabrir el lanzador reutiliza la instancia, no recarga Python. Para reinicios sigue `.agents/skills/app-launcher/SKILL.md`.
- **Datos de mercado**: `market_updater.run_updater()` y `POST /api/sync`. Los periodos precalculados viven en `latest_data.json`; el sondeo del navegador no descarga precios. Lee la configuración actual del scheduler antes de diagnosticar la cadencia.
- **Seguimiento único**: el Diario automático conserva las señales originales y sus resultados; Cartera registra operaciones reales. Los antiguos planes por botón están retirados y su archivo privado se conserva, sin mezclarse con las estadísticas.
- **Formato actual del bot**: el pronóstico se integra en la narrativa y el seguimiento activo se muestra como pin compacto. Lee los formatters actuales antes de restaurar bloques o expectativas de versiones anteriores.
- **Ver negocio**: consulta fundamental bajo demanda e independiente de la actualización de precios y del score técnico.
- **Pruebas**: `python -m unittest` reúne las regresiones; cada skill indica los módulos relevantes. Revisa si un fallo representa una regresión o una expectativa de presentación desfasada antes de modificar comportamiento. Para skills usa el validador de `skill-creator` y comprueba enlaces locales. No envíes mensajes ni modifiques datos reales para probar funciones que admiten mocks y archivos temporales.

## Reglas de Desarrollo (Obligatorias)
1. **Estética Visual**: Mantener la estética visual premium (modo oscuro, tokens CSS en `style.css`, sin frameworks CSS pesados).
2. **Consistencia de Datos**: Probar siempre la consistencia de los datos en `latest_data.json` tras cualquier cambio en el backend.
3. **Compatibilidad Windows**: Conservar la compatibilidad de ejecución en Windows (`.bat` de un clic).
4. **Seguridad y Privacidad**: Nunca exponer `secrets.json`, `portfolio.json`, `.alerts_cache.json`, `.earnings_cache.json`, `.business_cache.json`, `.trade_plans.json` ni logs o archivos privados/locales en el repositorio. `config.json` debe mantener siempre vacíos los campos de credenciales (`webhook_url`, `bot_token`, `chat_id`). Conserva cambios locales ajenos a la tarea en `journal.json` y `latest_data.json` sin incluirlos accidentalmente en commits.
5. **Subida Automática a Git (SIN PREGUNTAR)**: **NUNCA preguntes al usuario si quiere hacer commit o subir los cambios a Git/GitHub**. Siempre que termines de implementar, corregir o modificar cualquier archivo del proyecto, ejecuta automáticamente `git add -A`, `git commit -m "..."` (con mensaje claro y descriptivo en español) y `git push` a la rama `main`.
