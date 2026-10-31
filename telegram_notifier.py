"""
telegram_notifier.py
Módulo de notificaciones push para Telegram en 'Buscar un buen precio'.
Envía alertas automáticas cuando un activo entra en la Zona Áurea (61.8%)
o alcanza alta confluencia técnica (Fibonacci + RSI + SMA 200).
"""

import time
import requests

# Caché en memoria para evitar saturación de mensajes repetidos (cooldown de 4 horas por activo)
_last_alerts_cache = {}
ALERT_COOLDOWN_SECONDS = 4 * 3600  # 4 horas

def send_telegram_message(bot_token, chat_id, text, parse_mode="Markdown"):
    """
    Envía un mensaje de texto con formato Markdown a un chat_id de Telegram.
    """
    if not bot_token or not chat_id:
        return False, "Faltan credenciales de Telegram (bot_token o chat_id)."

    url = f"https://api.telegram.org/bot{bot_token.strip()}/sendMessage"
    payload = {
        "chat_id": str(chat_id).strip(),
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": False
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if resp.status_code == 200 and data.get("ok"):
            return True, "Mensaje enviado con éxito"
        else:
            err_desc = data.get("description", f"Error HTTP {resp.status_code}")
            return False, err_desc
    except Exception as e:
        return False, f"Error de conexión con Telegram: {str(e)}"

def test_telegram_connection(bot_token, chat_id):
    """
    Envía un mensaje de prueba al usuario para confirmar que el Bot Token y Chat ID funcionan.
    """
    message = (
        "🚀 *¡CONEXIÓN EXITOSA CON BUSCAR UN BUEN PRECIO!*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Tu bot de Telegram ha sido vinculado correctamente al panel web.\n\n"
        "A partir de ahora, cuando el monitor detecte que un activo entra en su "
        "*Zona Áurea (61.8%)* o alcance *Alta Confluencia Técnica*, "
        "recibirás un aviso instantáneo en este chat con enlaces directos a TradingView.\n\n"
        "⏱ _Sistema de alertas automáticas activo._"
    )
    return send_telegram_message(bot_token, chat_id, message)

def format_telegram_alert(item, period="3mo"):
    """
    Construye un mensaje enriquecido con emojis y formato profesional para una oportunidad.
    """
    ticker = item.get("ticker", "")
    tab = item.get("tab", ticker)
    price = item.get("current_price", 0)
    drop_pct = item.get("drop_pct", 0)
    score = item.get("score", 0)
    confluence = item.get("confluence_rating", "Oportunidad Técnica")
    fibs = item.get("fib_levels", {})
    golden_price = fibs.get("61.8%", 0)
    buy_price = fibs.get("50.0%", 0)
    rsi = item.get("rsi")
    rsi_str = f"{rsi:.1f}" if isinstance(rsi, (int, float)) else "--"
    sma_sign = "+" if item.get("sma_dist_pct", 0) >= 0 else ""
    sma_str = f"{sma_sign}{item.get('sma_dist_pct', 0):.1f}%"
    sma_trend = "🐂 Alcista" if item.get("is_above_sma") else "🐻 Bajista"

    # Mapeo a símbolo TradingView
    tv_symbol = ticker
    if tv_symbol == "GC=F":
        tv_symbol = "COMEX:GC1!"
    elif tv_symbol == "^GSPC":
        tv_symbol = "SP:SPX"
    elif tv_symbol.endswith(".MC"):
        tv_symbol = f"BME:{tv_symbol.replace('.MC', '')}"

    tv_url = f"https://www.tradingview.com/symbols/{tv_symbol}/"

    msg = (
        f"🎯 *¡ALERTA FIBONACCI: {tab} ({ticker})!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 *Score de Confluencia*: `{score}/100` ({confluence})\n"
        f"💰 *Precio Actual*: `${price:,.2f}` (-{drop_pct:.1f}% desde máx)\n"
        f"🏆 *Zona Áurea (61.8%)*: `${golden_price:,.2f}`\n"
        f"🟢 *Zona de Compra (50%)*: `${buy_price:,.2f}`\n"
        f"📉 *RSI (14 días)*: `{rsi_str}`\n"
        f"📈 *Estructura SMA 200*: `{sma_str}` ({sma_trend})\n"
        f"⏳ *Ventana de Análisis*: `{period.upper()}`\n\n"
        f"[📊 Abrir Gráfico en TradingView]({tv_url})"
    )
    return msg

def dispatch_telegram_alerts(market_payload, config):
    """
    Evalúa los activos del payload y envía notificaciones a Telegram si cumplen los criterios.
    Usa caché con cooldown para evitar inundar el chat con mensajes repetidos.
    """
    tg_config = config.get("telegram", {})
    if not tg_config.get("enabled"):
        return {"sent": 0, "status": "Telegram no está activado"}

    bot_token = tg_config.get("bot_token", "").strip()
    chat_id = tg_config.get("chat_id", "").strip()
    if not bot_token or not chat_id:
        return {"sent": 0, "status": "Faltan credenciales de Telegram"}

    min_score = tg_config.get("min_score", 70)
    notify_golden = tg_config.get("notify_on_golden_zone", True)
    notify_confluence = tg_config.get("notify_on_high_confluence", True)
    period = market_payload.get("period", config.get("period", "3mo"))

    sent_count = 0
    now = time.time()

    for item in market_payload.get("data", []):
        ticker = item.get("ticker")
        current_price = item.get("current_price", 0)
        fib_golden = item.get("fib_levels", {}).get("61.8%", 0)
        score = item.get("score", 0)

        is_golden = current_price <= fib_golden
        is_high_score = score >= min_score

        qualifies = (notify_golden and is_golden) or (notify_confluence and is_high_score)
        if not qualifies:
            continue

        # Comprobar cooldown para no repetir exactamente el mismo activo cada ciclo
        last_alert = _last_alerts_cache.get(ticker)
        if last_alert:
            elapsed = now - last_alert.get("timestamp", 0)
            if elapsed < ALERT_COOLDOWN_SECONDS:
                # Ya fue notificado recientemente dentro del periodo de cooldown
                continue

        # Enviar alerta
        alert_text = format_telegram_alert(item, period=period)
        ok, res = send_telegram_message(bot_token, chat_id, alert_text)
        if ok:
            sent_count += 1
            _last_alerts_cache[ticker] = {
                "timestamp": now,
                "price": current_price,
                "score": score
            }
            print(f"[Telegram Notifier] 📲 Alerta enviada para {ticker} ({item.get('tab')}) al chat {chat_id}")
            time.sleep(0.5)  # Breve pausa para respetar rate limit de Telegram
        else:
            print(f"[Telegram Notifier] ❌ Error enviando alerta para {ticker}: {res}")

    return {"sent": sent_count, "status": "Completado"}
