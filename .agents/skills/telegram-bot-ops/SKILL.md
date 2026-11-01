---
name: telegram-bot-ops
description: >-
  Use this skill when the user asks to configure, test, extend, or troubleshoot the Telegram
  alert system, interactive bot commands (/precios, /compras, /activos, /cartera, /actualizar),
  anti-spam cache, or credentials in secrets.json in "Buscar un buen precio".
---

# Sistema de Alertas y Bot Interactivo de Telegram

Esta skill detalla la arquitectura de notificaciones push y los comandos interactivos del bot de Telegram en [telegram_notifier.py](file:///e:/Proyectos/Buscar%20un%20buen%20precio/telegram_notifier.py).

## 1. Gestión Segura de Credenciales (`secrets.json`)

- **Nunca** guardes `bot_token`, `chat_id` ni `webhook_url` en [config.json](file:///e:/Proyectos/Buscar%20un%20buen%20precio/config.json).
- Todas las credenciales viven en `secrets.json` (archivo local ignorado por [`.gitignore`](file:///e:/Proyectos/Buscar%20un%20buen%20precio/.gitignore)):
  ```json
  {
    "webhook_url": "https://script.google.com/macros/s/.../exec",
    "telegram": {
      "enabled": true,
      "bot_token": "123456:ABC-DEF...",
      "chat_id": "123456789",
      "alert_on_levels": ["78.6%", "61.8%"]
    }
  }
  ```
- [market_updater.py](file:///e:/Proyectos/Buscar%20un%20buen%20precio/market_updater.py) fusiona automáticamente `secrets.json` sobre `config.json` en memoria mediante `load_config()`.

## 2. Alertas Automáticas y Caché Anti-Spam (`.alerts_cache.json`)

- Durante cada ejecución de `market_updater.py`, se llama a `process_telegram_alerts(config, assets_data)`.
- **Reglas de disparo**:
  - Activos cuyo `signal_level` coincide con `alert_on_levels` (por defecto `"78.6%"` y `"61.8%"`).
  - Activos que presentan una **Confluencia Multi-Timeframe (`has_cluster: true`)** a menos de `1.8%` del precio actual.
- **Anti-Spam e Histeresis**:
  - Se guarda en `.alerts_cache.json` el nivel notificado y el timestamp (`cooldown` de 24h para el mismo nivel).
  - Si un activo sube y sale de zona de compra (`signal_level not in alert_levels` y recuperó un margen `> 1.5%` por encima de `fib_618`), se limpia de `.alerts_cache.json` para que vuelva a alertar si cae de nuevo.

## 3. Comandos Interactivos del Bot (`--listen`)

El bot soporta polling ligero (`getUpdates`) ejecutando:
```powershell
python telegram_notifier.py --listen
```
Comandos disponibles (restringidos exclusivamente al `chat_id` autorizado):
- `/compra <TICKER>`: **🟢 Consejo de Compra Sintetizado**: Veredicto inmediato, Plan Operativo (Entrada, Stop Loss SSL/Fibo 78.6%, TP1, TP2 y ratio R:R) y Claves Técnicas (Muro POC, Smart Money, Confluencia, RSI y Resultados).
- `/venta [TICKER]`: **🔴 Consejo de Venta / Modo Venta**: Radar de sobrecalentamiento o Consejo individual con Trailing Stop protector, extensiones 127.2% / 161.8% y recomendación táctica de salida.
- `/fibo <TICKER>`: **📐 Escalera de Fibonacci Detallada**: Niveles Fibo enriquecidos con densidad de volumen (`🏦 Muro POC`, `% de volumen`, `🕳️ LVN`) y botones Multi-Timeframe instantáneos (1M, 3M, 6M, 1A).
- `/ver <TICKER>`: Radiografía ejecutiva inteligente (enruta automáticamente a Consejo de Venta si está en resistencia/sobrecompra o Consejo de Compra si está en descuento).
- `/riesgo <TICKER> [capital]`: Calculadora de dimensionamiento de posición y gestión de riesgo según capital a arriesgar (ej: `/riesgo NVDA 100`).
- `/precios` o `/resumen`: Lista todos los activos con su precio actual, caída y score de confluencia.
- `/alertas` u `/oportunidades`: Filtra activos en zona áurea (`<= 61.8%`) o con Score de confluencia `>= 70`.
- `/liquidez`, `/poc` o `/smc`: Radar institucional con Muro POC (Volume Profile), Volumen Relativo (`RVOL`), Absorción de Ballenas, Barridos de Stops (Spring SMC) y Piscinas de Liquidez (`SSL`).
- `/cartera`: Consulta en vivo `portfolio_manager.py` y responde con el P&L latente, valor total y desglose de posiciones abiertas.
- `/add <TICKER> [Nombre]` y `/del <TICKER>`: Gestión de activos directamente desde el chat de Telegram.
- `/sync` o `/actualizar`: Lanza `python market_updater.py` en segundo plano y responde al terminar con las oportunidades detectadas.
- `/ayuda` o `/start`: Muestra el menú de comandos y teclado rápido persistente.

## 4. Comandos de Prueba y Diagnóstico

- **Enviar mensaje de prueba**:
  ```powershell
  python telegram_notifier.py --test
  ```
- **Desde el Panel Web**: Botón de campana `🔔` en la cabecera (`POST /api/telegram/test`).

