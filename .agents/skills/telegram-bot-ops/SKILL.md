---
name: telegram-bot-ops
description: >-
  Configurar, mantener o diagnosticar Telegram en Buscar un buen precio: comandos,
  narrativa de análisis, seguimiento del Diario, alertas, mensajes fijados y credenciales.
---

# Bot de Telegram

## Código y estado actual

[telegram_notifier.py](../../../telegram_notifier.py) contiene router, formatters, envío y escucha. `app.run_server()` inicia `start_bot_listener_thread()`; no hace falta otra consola del bot. Para reinicios o versiones antiguas usa [app-launcher](../app-launcher/SKILL.md).

Lee `format_buy_advice`, `format_sell_advice`, `journal_tracking_context` y el router antes de editar mensajes. La versión actual usa un pronóstico narrativo integrado, plan de ejecución y avisos compactos; según el escenario, incluye entrada en dos tramos. No restaures el antiguo bloque largo de contexto por basarte en una conversación anterior.

`format_current_market_context()` permanece como stub que devuelve texto vacío y `/ver` no lo concatena: soporte y volumen se integran en los formatters principales. `journal_tracking_context()` muestra un pin compacto solo cuando hay señal activa, con entrada, P&L y salida/stop del Diario. Esto es presentación; el Diario sigue conservando sus niveles originales. Cambiar el formato no autoriza a modificar sus registros.

## Rutas de consulta

| Consulta | Handler y propósito |
|---|---|
| `/ver AMD`, `/analizar AMD` o ticker directo | `handle_ver_ticker`: Compra o Venta según situación, con pin del Diario |
| `/compra AMD`, `/venta AMD` | Lectura actual y propuesta de ejecución; no registran una compra real |
| `/fibo AMD` | Detalle Fibonacci y botones de periodo |
| `/riesgo AMD 100` | Dimensionamiento según presupuesto de riesgo |
| `/resumen`, `/precios` | Cotizaciones y puntuaciones guardadas |
| `/alertas`, `/oportunidades` | Filtro de zona áurea o score alto |
| `/historial`, `/diario`, `/seguimiento`, `/seguimientos` | Diario automático y resultados |
| `/cartera` | Posiciones reales y P&L |
| `/actualizar`, `/sync` | `run_updater()` en un hilo del mismo proceso |
| `/add`, `/del`, `/periodo` | Gestión de activos y ventana global |

Los alias antiguos `/plan` y `/planes` redirigen al Diario. Sus callbacks retirados explican el cambio; no deben crear o cancelar seguimientos. No reintroduzcas un segundo sistema de planes sin petición del usuario.

## Mensajes y alertas

- `find_asset_item()` lee `latest_data.json`; pedir análisis no descarga precios. Los mensajes antiguos del chat no se reescriben al reiniciar: pide una nueva consulta para comprobar el formato.
- Los niveles actuales pueden diferir de los de la señal registrada, incluido el stop SSL preferido por el análisis. Mantén clara esa distinción. El POC aproxima volumen histórico con velas diarias; TPO no equivale a volumen real y ninguno es un libro de órdenes. Un score no es una probabilidad calibrada; revisa cualquier afirmación de certeza o estadística al modificar la narrativa.
- `send_telegram_message()` devuelve `(ok, result_dict)` cuando Telegram acepta el envío; el resultado contiene `message_id`. En fallo devuelve el error. Conserva el fallback a texto plano ante errores de entidades Markdown, `escape_md()` y el límite de 4096 caracteres. Comprueba el resultado al diagnosticar envíos fallidos.
- `dispatch_telegram_alerts()` filtra zona áurea/score según `config.telegram`, respeta `scheduler.smart_hours_only` y aplica `ALERT_COOLDOWN_SECONDS` de cuatro horas por ticker. El estado se guarda en `.alerts_cache.json` al entregarse a algún destinatario; no hay cooldown de 24 horas ni borrado automático por histéresis en la implementación actual.
- Las alertas entregadas pueden fijarse con `pin_telegram_message()` usando `message_id`; un fallo de fijación no equivale a fallo del envío. Comprueba permisos de Telegram antes de insistir en fijar.

## Credenciales, pruebas y diagnóstico

Los secretos van en `secrets.json`; `load_config()` los fusiona en memoria y `save_config()` los separa de la configuración pública. Conserva la restricción de chats autorizados tanto para mensajes como callbacks. No imprimas tokens, URLs privadas ni IDs de chat en diagnósticos compartidos.

Prueba formatters y handlers con `unittest.mock.patch` de `send_telegram_message`, `answer_callback_query`, `requests` y, si procede, `pin_telegram_message`. Usa un Diario temporal. No envíes ni fijes mensajes reales como prueba sin una petición que lo autorice. `--test` y `/api/telegram/test` sí envían mensajes; no son comprobaciones inocuas.

`test_telegram_tracking.py` incluye expectativas de formatos anteriores: revisa sus fallos contra el contrato vigente y la petición. No reviertas la narrativa actual para satisfacer texto obsoleto ni ocultes una regresión real. Cuando cambies comportamiento, actualiza las expectativas afectadas y verifica que las consultas no escriben señales y que todos los activos generan mensajes válidos de longitud aceptable.

Si no llegan mensajes nuevos, comprueba primero proceso/versión, salud del panel, recepción del comando y retorno del envío. Distingue errores 400 de Markdown/longitud, 409 por escuchas concurrentes, credenciales/chats y cooldown. Los logs pueden contener datos privados: resume resultados sin volcarlos completos. Finaliza con [git-auto-sync](../git-auto-sync/SKILL.md).
