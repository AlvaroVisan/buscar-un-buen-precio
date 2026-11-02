---
name: manage-assets
description: >-
  Añadir, retirar o renombrar activos y validar tickers de Yahoo Finance en Buscar un buen precio.
  Usar para cambios en config.assets y su reflejo en el panel, Telegram o Sheets.
---

# Activos y tickers

## Código y contrato

- [config.json](../../../config.json): `assets` contiene objetos con `ticker`, `tab` y `name`. `tab` es el nombre corto de tarjeta y pestaña de Sheets; `ticker` identifica el activo.
- [app.py](../../../app.py): `POST /api/assets/validate`, `/api/assets/add`, `/api/assets/remove`. Todos usan JSON; no hay endpoint DELETE de activos.
- [telegram_notifier.py](../../../telegram_notifier.py): `handle_add_asset`, `handle_del_asset`, `find_asset_item` y `get_tradingview_url`.
- [market_updater.py](../../../market_updater.py): `load_config`, `save_config`, `detect_asset_format`, `fetch_asset_data`, `run_updater`.

## Cambiar un activo

1. Identifica el ticker y comprueba duplicados sin distinguir mayúsculas. Conserva los demás activos y la preferencia de periodo del usuario.
2. Valida datos con Yahoo antes de guardar un ticker nuevo. Los endpoints existentes consultan `Ticker.history(period="5d")`; vacío o un error de red no demuestra que otro ticker parecido sea correcto. No sustituyas el activo por una conjetura.
3. Guarda únicamente la configuración pública. Si usas `load_config()`, el resultado incluye credenciales: persiste mediante `save_config()`, nunca con un `json.dump` directo de ese objeto.
4. Actualiza la caché cuando forme parte de la petición. `run_updater()` también puede escribir en Sheets, enviar alertas y actualizar el Diario; no lo ejecutes para una simple inspección.
5. Comprueba la presencia o ausencia del ticker en `latest_data.json`, precio finito y positivo, divisa, decimales, `timeframes` y enlace de TradingView. `is_stale=true` significa cotización conservada, no descarga nueva satisfactoria.

Símbolos como `GC=F`, `^GSPC`, `BTC-USD` o `ITX.MC` requieren tratamiento distinto en formato y enlaces. No apliques métricas empresariales a índices, futuros o criptomonedas. Revisa las conversiones existentes antes de añadir excepciones.

Retirar un ticker de `assets` no autoriza a borrar posiciones reales, ventas ni señales históricas. El Diario mantiene sus registros aunque el activo ya no esté en la lista de precios.

## Verificación y entrega

- Para cambios de validación o conservación de precios: `python -m unittest test_quote_failures test_local_server`.
- Para comprobar la tarjeta, utiliza el panel iniciado con [Iniciar_Aplicacion.bat](../../../Iniciar_Aplicacion.bat); no recrees los lanzadores retirados.
- Contrasta el resultado con la petición y completa [git-auto-sync](../git-auto-sync/SKILL.md).
