---
name: portfolio-journal
description: >-
  Gestionar compras, DCA, ventas y resultados reales de Cartera, o investigar señales,
  niveles fijos y tasa de acierto del Diario automático en Buscar un buen precio.
---

# Cartera real y Diario automático

## Separar los dos registros

- [portfolio_manager.py](../../../portfolio_manager.py) administra `portfolio.json`, privado e ignorado por Git. Solo una operación explícita de cartera registra compras o ventas reales.
- [journal_manager.py](../../../journal_manager.py) administra `journal.json`: simulaciones automáticas, independientes de la cartera y de las consultas al bot.
- El Diario es el único seguimiento de señales. El sistema de planes elegidos por botón fue retirado. `.trade_plans.json`, si existe, se conserva como archivo privado; no se importa ni se mezcla automáticamente con el Diario.

## Cartera

`upsert_position(..., merge=True)` acumula unidades y recalcula el precio medio ponderado del ticker. `merge=False` edita/sobrescribe la posición; no es otro DCA.

`remove_or_reduce_position(ticker, sell_shares=None, sell_price=None)` diferencia una eliminación sin venta de una salida con precio. Cuando hay venta, conserva el resultado en `closed_history`, también en salidas parciales. No trunques ese historial para simplificar la UI o calcular el beneficio acumulado.

`get_enriched_portfolio()` añade cotización, riesgos y P&L. Conserva los indicadores de datos ausentes/obsoletos y `valuation_incomplete`: una cotización ausente no equivale a valor de mercado cero. Los totales y resultados realizados se agrupan por divisa; no sumes monedas distintas como si hubiera conversión de cambio.

Rutas reales: `GET /api/portfolio`, `POST /api/portfolio/upsert`, `POST /api/portfolio/remove`. Consulta sus campos en [app.py](../../../app.py) antes de operar. No fabriques posiciones de prueba en el archivo privado del usuario.

## Diario: registro y evaluación

- `update_journal_with_market_data()` registra señales cuando el precio está en/bajo 61,8% o el score es al menos 70, sin abrir otra señal para un ticker que ya sigue activo. Los IDs actuales usan ticker y tiempo; no son claves diarias por `updated_at`.
- Entrada, objetivos, `initial_stop_loss`, score y periodo se conservan al crear la señal. Los cambios de ventana o cotización no sustituyen esos niveles. Las nuevas entradas guardan `period` y `stop_method`; en registros antiguos lo desconocido se muestra como No registrado.
- `get_tracking_signal()` es una consulta sin escrituras: prioriza una señal abierta y, si no existe, devuelve la última registrada. No crea operaciones ni borra un archivo corrupto.
- `_evaluate_price_point()` aplica el modelo de salida del 50% en TP1 y el resto en TP2 o entrada. Antes de TP1 el stop termina en `STOP_EJECUTADO/PERDIDA`; TP1 pasa a `TP1_ALCANZADO` y mueve el stop del resto a la entrada; TP2 termina en `TP2_ALCANZADO/GANADA`; la vuelta a la entrada después de TP1 termina en `BREAKEVEN_EJECUTADO/GANADA` con el beneficio parcial ponderado.
- `calculate_journal_stats()` calcula ganadas / operaciones cerradas, excluyendo las abiertas. Se recalcula durante las actualizaciones de mercado, no al cierre del día. No hay evaluación vigente a +7/+15/+30 días ni una regla de ganador basada en un pico porcentual.
- En el día de registro no se usan máximos/mínimos anteriores a la señal; después se revisan rangos diarios y precios puntuales. Ante un rango ambiguo el código comprueba primero el stop. No presentes la simulación como ejecución real ni como cobertura de todos los toques intradía.

## Investigar discrepancias

Compara ticker, fecha, periodo, score inicial, entrada, stop y objetivos registrados con los de la lectura actual. Un score o stop nuevo del motor no demuestra que haya fallado la evaluación del registro antiguo. Tampoco cierres retrospectivamente una señal usando el stop de otra propuesta. Conserva los datos antes de una reparación y prueba la causa con fixtures temporales.

Pruebas relevantes: `python -m unittest test_journal_manager test_portfolio_history test_quote_failures`. Para consumo del Diario en el bot, consulta [telegram-bot-ops](../telegram-bot-ops/SKILL.md) y revisa las expectativas actuales de `test_telegram_tracking.py`. Completa [git-auto-sync](../git-auto-sync/SKILL.md) sin subir datos privados de cartera.
