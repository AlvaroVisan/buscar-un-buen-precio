"""
telegram_notifier.py
Módulo de notificaciones y bot interactivo para Telegram en 'Buscar un buen precio'.
Proporciona:
1. Alertas automáticas push cuando un activo entra en la Zona Áurea (61.8%) o alcanza alta confluencia.
2. Bot interactivo bidireccional (comandos /resumen, /alertas, /ver <ticker>, /sync, /periodo).
"""

import os
import json
import time
import threading
import requests

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
LATEST_DATA_PATH = os.path.join(DIRECTORY, "latest_data.json")
CONFIG_PATH = os.path.join(DIRECTORY, "config.json")

# Caché en memoria para evitar saturación de mensajes repetidos (cooldown de 4 horas por activo)
_last_alerts_cache = {}
ALERT_COOLDOWN_SECONDS = 4 * 3600  # 4 horas
_bot_listener_running = False
_sync_lock = threading.Lock()

# Teclado persistente con botones rápidos de acceso en la app de Telegram
TELEGRAM_MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "📊 Resumen"}, {"text": "🎯 Alertas"}],
        [{"text": "🔄 Sincronizar"}, {"text": "ℹ️ Ayuda"}]
    ],
    "resize_keyboard": True,
    "is_persistent": True
}

def parse_chat_ids(raw_chat_id):
    """
    Parsea uno o varios Chat IDs separados por comas, espacios o punto y coma,
    o desde una lista de strings/enteros.
    """
    if not raw_chat_id:
        return []
    if isinstance(raw_chat_id, list):
        ids = [str(x).strip() for x in raw_chat_id if str(x).strip()]
        return list(dict.fromkeys(ids))
    if isinstance(raw_chat_id, (int, float)):
        return [str(int(raw_chat_id))]
    if isinstance(raw_chat_id, str):
        import re
        tokens = re.split(r'[,;\s]+', raw_chat_id.strip())
        ids = [t for t in tokens if t]
        return list(dict.fromkeys(ids))
    return []

def get_tradingview_url(ticker):
    """
    Devuelve la URL directa a TradingView mapeando símbolos especiales.
    """
    tv_symbol = ticker
    if tv_symbol == "GC=F":
        tv_symbol = "COMEX:GC1!"
    elif tv_symbol == "^GSPC":
        tv_symbol = "SP:SPX"
    elif tv_symbol == "BTC-USD":
        tv_symbol = "COINBASE:BTCUSD"
    elif tv_symbol.endswith(".MC"):
        tv_symbol = f"BME:{tv_symbol.replace('.MC', '')}"
    return f"https://www.tradingview.com/symbols/{tv_symbol}/"

def send_telegram_message(bot_token, chat_id, text, parse_mode="Markdown", reply_markup=None):
    """
    Envía un mensaje de texto con formato Markdown a un chat_id de Telegram.
    Soporta botones de teclado rápido mediante reply_markup.
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
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        resp = requests.post(url, json=payload, timeout=12)
        data = resp.json()
        if resp.status_code == 200 and data.get("ok"):
            return True, "Mensaje enviado con éxito"
        else:
            err_desc = data.get("description", f"Error HTTP {resp.status_code}")
            return False, err_desc
    except Exception as e:
        return False, f"Error de conexión con Telegram: {str(e)}"

def setup_bot_commands(bot_token):
    """
    Registra el menú de comandos en Telegram para que aparezca el botón azul 'Menu'.
    """
    if not bot_token:
        return
    try:
        url = f"https://api.telegram.org/bot{bot_token.strip()}/setMyCommands"
        cmds = [
            {"command": "resumen", "description": "📊 Precios y Scores de todos los activos"},
            {"command": "alertas", "description": "🎯 Oportunidades en Zona Áurea / Alta Confluencia"},
            {"command": "riesgo", "description": "🛡️ Calculadora de riesgo, Stop Loss y lote"},
            {"command": "venta", "description": "🔴 Modo Venta / Toma de beneficios y extensiones"},
            {"command": "historial", "description": "📔 Diario de trading y tasa de acierto"},
            {"command": "sync", "description": "🔄 Sincronizar mercado y Google Sheets ahora"},
            {"command": "ayuda", "description": "ℹ️ Ayuda y lista de comandos"}
        ]
        requests.post(url, json={"commands": cmds}, timeout=10)
    except Exception as e:
        print(f"[Telegram Bot] Aviso al registrar menú de comandos: {e}")

def test_telegram_connection(bot_token, chat_ids_raw):
    """
    Envía un mensaje de prueba al usuario (o múltiples usuarios) y configura el teclado y menú interactivo.
    """
    setup_bot_commands(bot_token)
    chat_ids = parse_chat_ids(chat_ids_raw)
    if not chat_ids:
        return False, "No se ha proporcionado ningún Chat ID válido."

    message = (
        "🚀 *¡CONEXIÓN EXITOSA CON BUSCAR UN BUEN PRECIO!*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Tu bot de Telegram ha sido vinculado y configurado en modo *Asistente Interactivo*.\n\n"
        "A partir de ahora puedes:\n"
        "• Recibir alertas automáticas cuando un activo entre en *Zona Áurea (61.8%)*.\n"
        "• Pedirle resultados cuando quieras con los botones de abajo o escribiendo:\n"
        "  - `/resumen` (Precios y notas de toda tu lista)\n"
        "  - `/alertas` (Solo oportunidades activas)\n"
        "  - `/ver AMD` (Radiografía Fibonacci de un activo)\n"
        "  - `/sync` (Actualizar mercado y Google Sheets)\n\n"
        "⏱ _Sistema y botones de respuesta rápida activos._"
    )

    success_count = 0
    errors = []
    for cid in chat_ids:
        ok, res = send_telegram_message(bot_token, cid, message, reply_markup=TELEGRAM_MAIN_KEYBOARD)
        if ok:
            success_count += 1
        else:
            errors.append(f"ID {cid}: {res}")

    if success_count > 0:
        if len(errors) == 0:
            return True, f"Mensaje de prueba enviado con éxito a {success_count} destinatario(s)."
        else:
            return True, f"Enviado a {success_count} destinatario(s). Errores en: {', '.join(errors)}"
    else:
        return False, f"Error al enviar: {'; '.join(errors)}"

def format_telegram_alert(item, period="3mo"):
    """
    Construye un mensaje enriquecido para una oportunidad detectada.
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
    tv_url = get_tradingview_url(ticker)

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
    Usa caché con cooldown para evitar inundar el chat.
    Soporta múltiples destinatarios (Chat IDs separados por comas).
    """
    tg_config = config.get("telegram", {})
    if not tg_config.get("enabled"):
        return {"sent": 0, "status": "Telegram no está activado"}

    bot_token = tg_config.get("bot_token", "").strip()
    chat_ids = parse_chat_ids(tg_config.get("chat_id", ""))
    if not bot_token or not chat_ids:
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

        # Comprobar cooldown
        last_alert = _last_alerts_cache.get(ticker)
        if last_alert:
            elapsed = now - last_alert.get("timestamp", 0)
            if elapsed < ALERT_COOLDOWN_SECONDS:
                continue

        # Enviar alerta a todos los destinatarios autorizados
        alert_text = format_telegram_alert(item, period=period)
        delivered_to_any = False
        for cid in chat_ids:
            ok, res = send_telegram_message(bot_token, cid, alert_text, reply_markup=TELEGRAM_MAIN_KEYBOARD)
            if ok:
                delivered_to_any = True
                print(f"[Telegram Notifier] 📲 Alerta enviada para {ticker} ({item.get('tab')}) al chat {cid}")
            else:
                print(f"[Telegram Notifier] ❌ Error enviando alerta para {ticker} a {cid}: {res}")
            time.sleep(0.2)

        if delivered_to_any:
            sent_count += 1
            _last_alerts_cache[ticker] = {
                "timestamp": now,
                "price": current_price,
                "score": score
            }

    return {"sent": sent_count, "status": "Completado"}

# ==========================================
# GESTORES DE COMANDOS INTERACTIVOS (BOT 24/7)
# ==========================================

def handle_start_or_help(bot_token, chat_id):
    """
    Envía la guía completa de uso con el teclado de botones rápidos.
    """
    msg = (
        "🤖 *ASISTENTE VIRTUAL FIBONACCI*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "¡Hola! Puedes consultar tus activos y forzar actualizaciones en cualquier momento usando los botones de abajo o estos comandos:\n\n"
        "📊 */resumen* o */precios*\n"
        "Lista general de todos tus activos con precio, caída y score de confluencia.\n\n"
        "🎯 */alertas* u */oportunidades*\n"
        "Filtra solo los activos en Zona Áurea (61.8%) o con Score $\\ge 70$.\n\n"
        "🔍 */ver TICKER* (ej: `/ver AMD` o simplemente escribe `AMD`)\n"
        "Ficha técnica con todos los retrocesos Fibonacci, RSI, SMA 200 y enlace a TradingView.\n\n"
        "🛡️ */riesgo TICKER [capital]* (ej: `/riesgo AMD 100`)\n"
        "Calculadora de posición: Stop Loss, Take Profit 1 y 2, Ratio R:R y número exacto de acciones a comprar según tu presupuesto de riesgo.\n\n"
        "🔴 */venta* o */salidas*\n"
        "Modo Venta: Radar de activos sobrecomprados (RSI > 65), extensiones de Fibonacci (127.2% y 161.8%) y Trailing Stop para recogida de beneficios.\n\n"
        "📔 */historial* o */diario*\n"
        "Diario de Trading: Mide la tasa de acierto (Win Rate), operaciones ganadas/perdidas y estado de cada señal registrada.\n\n"
        "🔄 */sync*\n"
        "Fuerza la actualización de precios con Yahoo Finance y actualiza tu Google Sheets en remoto.\n\n"
        "⏱ */periodo <1mo|3mo|6mo|1y>*\n"
        "Cambia la ventana de cálculo de Fibonacci (ej: `/periodo 1mo`)."
    )
    send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)

def handle_resumen(bot_token, chat_id):
    """
    Genera un informe resumido con los precios, caídas y notas de todos los activos.
    """
    if not os.path.exists(LATEST_DATA_PATH):
        send_telegram_message(
            bot_token, chat_id,
            "⚠️ Aún no hay datos disponibles. Pulsa *🔄 Sincronizar* para calcularlos ahora.",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    try:
        with open(LATEST_DATA_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)

        items = payload.get("data", [])
        period = payload.get("period", "3mo").upper()
        ts = payload.get("timestamp", "").split(" ")[-1] if payload.get("timestamp") else "--"

        sentiment = payload.get("market_sentiment", {})
        s_score = sentiment.get("score")
        s_rating = sentiment.get("rating_es", "")
        s_icon = sentiment.get("icon", "🌡️")

        lines = [
            f"📊 *RESUMEN DE MERCADO ({period})*",
            f"🕒 _Hora de corte: {ts}_"
        ]
        if s_score is not None:
            lines.append(f"{s_icon} *Sentimiento CNN*: `{s_score}/100` ({s_rating})")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")

        for it in items:
            ticker = it.get("ticker", "")
            tab = it.get("tab", ticker)
            price = it.get("current_price", 0)
            drop = it.get("drop_pct", 0)
            score = it.get("score", 0)

            if score >= 80:
                icon = "🔥"
            elif score >= 65:
                icon = "🟢"
            elif score >= 45:
                icon = "🟡"
            else:
                icon = "⚪"

            lines.append(f"{icon} *{tab}* (`{ticker}`): `${price:,.2f}` (-{drop:.1f}%)\n   └ Score: *{score}/100* | {it.get('signal', '')}")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("💡 _Escribe `/ver TICKER` (ej: `/ver AMD`) para ver todos sus niveles Fibonacci._")

        msg = "\n".join(lines)
        send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)
    except Exception as e:
        send_telegram_message(bot_token, chat_id, f"❌ Error al generar resumen: {e}", reply_markup=TELEGRAM_MAIN_KEYBOARD)

def handle_alertas(bot_token, chat_id):
    """
    Muestra exclusivamente los activos que están en Zona Áurea (61.8%) o con alta confluencia.
    """
    if not os.path.exists(LATEST_DATA_PATH):
        send_telegram_message(
            bot_token, chat_id,
            "⚠️ Aún no hay datos calculados. Pulsa *🔄 Sincronizar* primero.",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    try:
        with open(LATEST_DATA_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)

        items = payload.get("data", [])
        period = payload.get("period", "3mo")

        opportunities = []
        for it in items:
            price = it.get("current_price", 0)
            fib_golden = it.get("fib_levels", {}).get("61.8%", 0)
            score = it.get("score", 0)
            if price <= fib_golden or score >= 70:
                opportunities.append(it)

        if not opportunities:
            msg = (
                "🎯 *RADAR DE OPORTUNIDADES*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "✅ Ningún activo está actualmente en Zona Áurea (61.8%) ni con Score $\\ge 70$.\n\n"
                "Todos cotizan por encima de las zonas de compra recomendadas. El mercado no presenta sobreventas extremas en tu lista."
            )
            send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)
            return

        lines = [
            f"🎯 *OPORTUNIDADES DETECTADAS ({len(opportunities)})*",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ]

        for it in opportunities:
            ticker = it.get("ticker", "")
            tab = it.get("tab", ticker)
            price = it.get("current_price", 0)
            drop = it.get("drop_pct", 0)
            score = it.get("score", 0)
            confluence = it.get("confluence_rating", "")
            fib_golden = it.get("fib_levels", {}).get("61.8%", 0)
            fib_buy = it.get("fib_levels", {}).get("50.0%", 0)
            rsi = it.get("rsi", "--")
            tv_url = get_tradingview_url(ticker)

            lines.append(
                f"🔥 *{tab}* (`{ticker}`) — Score: *{score}/100*\n"
                f"• Precio: `${price:,.2f}` (-{drop:.1f}%)\n"
                f"• Zona Áurea (61.8%): `${fib_golden:,.2f}`\n"
                f"• Zona 50%: `${fib_buy:,.2f}` | RSI: `{rsi}`\n"
                f"• [Ver en TradingView]({tv_url})\n"
            )

        msg = "\n".join(lines)
        send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)
    except Exception as e:
        send_telegram_message(bot_token, chat_id, f"❌ Error al consultar alertas: {e}", reply_markup=TELEGRAM_MAIN_KEYBOARD)

def handle_ver_ticker(bot_token, chat_id, query):
    """
    Muestra la radiografía técnica completa de un activo solicitado.
    """
    clean_query = query.strip().upper().replace("$", "").replace("/", "")

    matched_item = None
    period = "3mo"

    if os.path.exists(LATEST_DATA_PATH):
        try:
            with open(LATEST_DATA_PATH, "r", encoding="utf-8") as f:
                payload = json.load(f)
                period = payload.get("period", "3mo")
                for it in payload.get("data", []):
                    t = it.get("ticker", "").upper()
                    tab = it.get("tab", "").upper()
                    name = it.get("name", "").upper()
                    if clean_query in (t, tab, name) or (clean_query == "ORO" and t == "GC=F") or (clean_query == "SPX" and t == "^GSPC"):
                        matched_item = it
                        break
        except Exception:
            pass

    if not matched_item:
        msg = (
            f"🔍 *Activo no encontrado: '{clean_query}'*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "El activo no está en tu lista de seguimiento actual.\n\n"
            "💡 _Puedes añadir cualquier acción (ej: AAPL, BTC-USD) abriendo tu panel web en:_ http://localhost:5050"
        )
        send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)
        return

    # Construir tarjeta técnica detallada
    ticker = matched_item.get("ticker", "")
    tab = matched_item.get("tab", ticker)
    name = matched_item.get("name", tab)
    price = matched_item.get("current_price", 0)
    drop_pct = matched_item.get("drop_pct", 0)
    p_min = matched_item.get("min", 0)
    p_max = matched_item.get("max", 0)
    score = matched_item.get("score", 0)
    confluence = matched_item.get("confluence_rating", "")
    signal = matched_item.get("signal", "")
    fibs = matched_item.get("fib_levels", {})
    rsi = matched_item.get("rsi", "--")
    rsi_desc = matched_item.get("rsi_desc", "")
    sma_200 = matched_item.get("sma_200", 0)
    sma_dist = matched_item.get("sma_dist_pct", 0)
    sma_sign = "+" if sma_dist >= 0 else ""
    sma_trend = "🐂 Alcista (Sobre SMA)" if matched_item.get("is_above_sma") else "🐻 Bajista (Bajo SMA)"
    tv_url = get_tradingview_url(ticker)

    # Bloque de gestión de riesgo
    risk_info = ""
    risk_data = matched_item.get("risk_mgmt")
    if risk_data:
        entry_p = risk_data.get("entry_price", price)
        sl = risk_data.get("stop_loss", 0)
        sl_pct = risk_data.get("risk_pct", 0)
        tp1 = risk_data.get("take_profit_1", 0)
        tp1_pct = risk_data.get("reward_1_pct", 0)
        tp2 = risk_data.get("take_profit_2", 0)
        tp2_pct = risk_data.get("reward_2_pct", 0)
        rr2 = risk_data.get("rr_ratio_2", 0)
        rr_rating = risk_data.get("rr_rating", "")

        risk_info = (
            f"🛡️ *GESTIÓN DE RIESGO SUGERIDA:*\n"
            f"• Entrada: `${entry_p:,.2f}` ({risk_data.get('entry_label', '')})\n"
            f"• Stop Loss: `${sl:,.2f}` (-{sl_pct:.1f}%)\n"
            f"• TP 1 (38.2%): `${tp1:,.2f}` (+{tp1_pct:.1f}%)\n"
            f"• TP 2 (Máx): `${tp2:,.2f}` (+{tp2_pct:.1f}%)\n"
            f"• Ratio R:R (TP2): `1:{rr2}` ({rr_rating})\n"
            f"💡 _Calcula tu lote con:_ `/riesgo {ticker} 100`\n\n"
        )

    msg = (
        f"🎯 *ANÁLISIS TÉCNICO: {name} ({ticker})*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Precio Actual*: `${price:,.2f}` (-{drop_pct:.1f}% desde máx)\n"
        f"📊 *Rango ({period.upper()})*: `${p_min:,.2f}` - `${p_max:,.2f}`\n"
        f"🚦 *Estado*: `{signal}`\n\n"
        f"🏆 *RETROCESOS DE FIBONACCI:*\n"
        f"• 23.6%: `${fibs.get('23.6%', 0):,.2f}`\n"
        f"• 38.2%: `${fibs.get('38.2%', 0):,.2f}`\n"
        f"• 50.0% (Zona Compra): `${fibs.get('50.0%', 0):,.2f}`\n"
        f"• 61.8% (Zona Áurea): `${fibs.get('61.8%', 0):,.2f}`\n"
        f"• 78.6% (Soporte Extremo): `${fibs.get('78.6%', 0):,.2f}`\n\n"
        f"📈 *CONFLUENCIA TÉCNICA:*\n"
        f"🔥 *Score*: `{score}/100` ({confluence})\n"
        f"📉 *RSI (14 sesiones)*: `{rsi}` ({rsi_desc})\n"
        f"📊 *SMA 200*: `${sma_200:,.2f}` ({sma_sign}{sma_dist:.1f}% - {sma_trend})\n\n"
        f"{risk_info}"
        f"[📊 Abrir Gráfico Interactivo en TradingView]({tv_url})"
    )
    send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)

def handle_riesgo(bot_token, chat_id, raw_args):
    """
    Calculadora interactiva de gestión de riesgo y dimensionamiento de posición.
    Sintaxis: /riesgo <TICKER> [PRESUPUESTO_DE_RIESGO]
    Ejemplo: /riesgo AMD 100
    """
    tokens = raw_args.strip().split()
    if not tokens:
        send_telegram_message(
            bot_token, chat_id,
            "🛡️ *CALCULADORA DE GESTIÓN DE RIESGO*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Calcula el número exacto de acciones a comprar según el capital que estás dispuesto a arriesgar (Stop Loss).\n\n"
            "📌 *Uso:* `/riesgo <TICKER> [capital_a_arriesgar]`\n"
            "• Ejemplo arriesgando 100€: `/riesgo AMD 100`\n"
            "• Ejemplo con 250$: `/riesgo NVDA 250`\n"
            "• Ejemplo rápido (100€ por defecto): `/riesgo META`",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    query_ticker = tokens[0].upper().replace("$", "").replace("/", "")
    budget = 100.0
    if len(tokens) > 1:
        clean_num = tokens[1].replace("€", "").replace("$", "").replace(",", ".")
        try:
            val = float(clean_num)
            if val > 0:
                budget = val
        except ValueError:
            pass

    matched_item = None
    if os.path.exists(LATEST_DATA_PATH):
        try:
            with open(LATEST_DATA_PATH, "r", encoding="utf-8") as f:
                payload = json.load(f)
                for it in payload.get("data", []):
                    t = it.get("ticker", "").upper()
                    tab = it.get("tab", "").upper()
                    name = it.get("name", "").upper()
                    if query_ticker in (t, tab, name) or (query_ticker == "ORO" and t == "GC=F") or (query_ticker == "SPX" and t == "^GSPC"):
                        matched_item = it
                        break
        except Exception:
            pass

    if not matched_item:
        send_telegram_message(
            bot_token, chat_id,
            f"🔍 *Activo no encontrado: '{query_ticker}'*\n"
            "Por favor indica un ticker de tu lista (ej: `AMD`, `TSLA`, `NVDA`, `META`).",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    ticker = matched_item.get("ticker", "")
    tab = matched_item.get("tab", ticker)
    price = matched_item.get("current_price", 0)
    risk_mgmt = matched_item.get("risk_mgmt")

    if not risk_mgmt:
        send_telegram_message(
            bot_token, chat_id,
            f"⚠️ No hay cálculo de riesgo disponible para {ticker}. Pulsa *🔄 Sincronizar*.",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    entry = risk_mgmt.get("entry_price", price)
    sl = risk_mgmt.get("stop_loss", price * 0.95)
    risk_per_share = risk_mgmt.get("risk_per_share", max(0.01, entry - sl))
    risk_pct = risk_mgmt.get("risk_pct", 5.0)
    tp1 = risk_mgmt.get("take_profit_1", entry * 1.05)
    tp1_pct = risk_mgmt.get("reward_1_pct", 5.0)
    tp2 = risk_mgmt.get("take_profit_2", entry * 1.15)
    tp2_pct = risk_mgmt.get("reward_2_pct", 15.0)
    rr2 = risk_mgmt.get("rr_ratio_2", 2.0)
    rr_rating = risk_mgmt.get("rr_rating", "")

    # Dimensionamiento de posición
    shares = int(budget // risk_per_share) if risk_per_share > 0 else 0
    if shares == 0:
        shares_min = 1
        needed_risk = round(risk_per_share, 2)
        total_inv_min = round(shares_min * entry, 2)
        sizing_text = (
            f"⚠️ *Presupuesto de riesgo inferior al de 1 acción.*\n"
            f"• Con tu presupuesto ({budget:,.2f}€/$), el riesgo por acción ({risk_per_share:,.2f}€/$) es superior.\n"
            f"• Para comprar *1 acción* de {ticker}, tu riesgo real si toca Stop Loss será de *{needed_risk:,.2f}€/$* (Inversión: *${total_inv_min:,.2f}*).\n"
            f"• _Alternativa: compra acciones fraccionadas ({round(budget / risk_per_share, 2)} títulos)._"
        )
    else:
        total_inv = round(shares * entry, 2)
        max_loss = round(shares * risk_per_share, 2)
        gain_tp1 = round(shares * (tp1 - entry), 2)
        gain_tp2 = round(shares * (tp2 - entry), 2)
        sizing_text = (
            f"📦 *DIMENSIONAMIENTO DE POSICIÓN:*\n"
            f"• Acciones a comprar: *{shares} títulos*\n"
            f"• Capital total a invertir: *${total_inv:,.2f}*\n"
            f"• Pérdida máxima controlada (Stop Loss): *-${max_loss:,.2f}*\n"
            f"• Beneficio estimado TP1: *+${gain_tp1:,.2f}* (+{tp1_pct:.1f}%)\n"
            f"• Beneficio estimado TP2: *+${gain_tp2:,.2f}* (+{tp2_pct:.1f}%)"
        )

    tv_url = get_tradingview_url(ticker)
    msg = (
        f"🛡️ *PLAN DE TRADING Y RIESGO: {tab} ({ticker})*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💼 *Presupuesto de Riesgo Máximo*: `{budget:,.2f}€/$`\n"
        f"📍 *Punto de Entrada*: `${entry:,.2f}` ({risk_mgmt.get('entry_label', '')})\n"
        f"🛑 *Stop Loss Estratégico*: `${sl:,.2f}` (-{risk_pct:.1f}%)\n"
        f"🎯 *Take Profit 1 (38.2%)*: `${tp1:,.2f}` (+{tp1_pct:.1f}%)\n"
        f"🏆 *Take Profit 2 (Máximos)*: `${tp2:,.2f}` (+{tp2_pct:.1f}%)\n"
        f"⚖️ *Ratio Riesgo/Beneficio*: `1:{rr2}` ({rr_rating})\n\n"
        f"{sizing_text}\n\n"
        f"💡 _Regla de oro: No aumentes tu posición sin desplazar antes el Stop Loss a precio de entrada (Break-Even)._\n\n"
        f"[📊 Abrir Gráfico en TradingView]({tv_url})"
    )
    send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)

def handle_venta(bot_token, chat_id):
    """
    Radar de Modo Venta / Toma de Beneficios.
    Detecta activos sobrecalentados, cerca de techos o en extensiones de Fibonacci (127.2%, 161.8%).
    """
    if not os.path.exists(LATEST_DATA_PATH):
        send_telegram_message(
            bot_token, chat_id,
            "⚠️ No hay datos cargados. Pulsa *🔄 Sincronizar* primero.",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    try:
        with open(LATEST_DATA_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)

        items = payload.get("data", [])
        sell_candidates = []
        for it in items:
            sm = it.get("sell_mgmt", {})
            score = sm.get("sell_score", 0)
            rsi = it.get("rsi", 50)
            dist_high = sm.get("dist_to_high_pct", 10)
            if score >= 35 or rsi >= 62 or dist_high <= 4.0:
                sell_candidates.append(it)

        sell_candidates.sort(key=lambda x: x.get("sell_mgmt", {}).get("sell_score", 0), reverse=True)

        if not sell_candidates:
            msg = (
                "🔴 *MODO VENTA / RADAR DE TOMA DE BENEFICIOS*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "✅ Ningún activo está actualmente sobrecomprado ni en zona de resistencia.\n\n"
                "Tus activos cotizan en fases de descuento, acumulación o inicio de impulso alcista. ¡Buen momento para dejar correr las ganancias!"
            )
            send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)
            return

        lines = [
            f"🔴 *RADAR DE TOMA DE BENEFICIOS ({len(sell_candidates)})*",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "Activos con presión de venta, resistencias o extensiones alcanzadas:\n"
        ]

        for it in sell_candidates:
            ticker = it.get("ticker", "")
            tab = it.get("tab", ticker)
            price = it.get("current_price", 0)
            sm = it.get("sell_mgmt", {})
            score = sm.get("sell_score", 0)
            signal = sm.get("sell_signal", "Atención")
            action = sm.get("sell_action", "Revisar")
            rsi = it.get("rsi", "--")
            gain_low = sm.get("gain_from_low_pct", 0)
            dist_hi = sm.get("dist_to_high_pct", 0)
            ext127 = sm.get("ext_127", 0)
            ext161 = sm.get("ext_161", 0)
            t_stop = sm.get("trailing_stop", price * 0.94)

            icon = "🔥" if score >= 70 else ("🟠" if score >= 50 else "🟡")
            lines.append(
                f"{icon} *{tab}* (`{ticker}`) — Presión Venta: *{score}/100*\n"
                f"• Precio: `${price:,.2f}` (+{gain_low:.1f}% desde mín | -{dist_hi:.1f}% de máx)\n"
                f"• RSI: `{rsi}` | Estado: *{signal}*\n"
                f"• Extensión 127.2%: `${ext127:,.2f}` | 161.8%: `${ext161:,.2f}`\n"
                f"• Trailing Stop Sugerido: `${t_stop:,.2f}` (-5.5%)\n"
                f"💡 _{action}_\n"
            )

        msg = "\n".join(lines)
        send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)
    except Exception as e:
        send_telegram_message(bot_token, chat_id, f"❌ Error al consultar modo venta: {e}", reply_markup=TELEGRAM_MAIN_KEYBOARD)

def handle_historial(bot_token, chat_id):
    """
    Diario de Trading y Rendimiento del algoritmo.
    Muestra la tasa de acierto (Win Rate), operaciones ganadas/perdidas y últimas señales.
    """
    try:
        import journal_manager
        j_data = journal_manager.load_journal()
        stats = j_data.get("stats", {})
        entries = j_data.get("entries", [])

        total = stats.get("total_opportunities", 0)
        active = stats.get("active_count", 0)
        closed = stats.get("closed_count", 0)
        win_rate = stats.get("win_rate_pct", 0.0)
        won = stats.get("total_won", 0)
        lost = stats.get("total_lost", 0)
        avg_win = stats.get("avg_win_pct", 0.0)

        lines = [
            "📔 *DIARIO DE TRADING & HISTORIAL*",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"🎯 *Tasa de Acierto (Win Rate)*: `{win_rate:.1f}%`",
            f"📊 *Operaciones Totales*: `{total}` ({active} activas, {closed} cerradas)",
            f"🏆 *Cerradas en Ganancia*: `{won}` (Promedio: `+{avg_win:.1f}%`)",
            f"🛑 *Cerradas en Stop*: `{lost}`",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ]

        if not entries:
            lines.append("ℹ️ Aún no hay registros en el diario. Las oportunidades se guardarán automáticamente cada vez que un activo entre en Zona Áurea (61.8%) o alcance Confluencia $\\ge 70$.")
        else:
            lines.append("📋 *Últimas Oportunidades en Seguimiento:*\n")
            for e in entries[:5]:
                tab = e.get("tab", e.get("ticker", ""))
                ticker = e.get("ticker", "")
                entry_p = e.get("entry_price", 0)
                curr_p = e.get("current_price", entry_p)
                ret = e.get("current_return_pct", 0.0)
                max_ret = e.get("max_return_pct", 0.0)
                status = e.get("status", "ACTIVA")
                date = e.get("signal_date", "").split()[0]

                if status == "TP2_ALCANZADO":
                    status_badge = "🟢 TP2 Alcanzado (+Ganada)"
                elif status == "TP1_ALCANZADO":
                    status_badge = "🟡 TP1 Alcanzado (Break-Even)"
                elif status == "STOP_EJECUTADO":
                    status_badge = "🔴 Stop Ejecutado"
                else:
                    status_badge = "🔵 En Seguimiento"

                sign = "+" if ret >= 0 else ""
                lines.append(
                    f"• *{tab}* (`{ticker}`) — {status_badge}\n"
                    f"  Entrada: `${entry_p:,.2f}` ({date}) | Actual: `${curr_p:,.2f}`\n"
                    f"  Retorno: *{sign}{ret:.1f}%* (Máx alcanzado: +{max_ret:.1f}%)\n"
                )

        lines.append("💡 _Visualiza el gráfico y estadísticas completas abriendo http://localhost:5050 en tu navegador._")
        msg = "\n".join(lines)
        send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)
    except Exception as e:
        send_telegram_message(bot_token, chat_id, f"❌ Error al consultar historial: {e}", reply_markup=TELEGRAM_MAIN_KEYBOARD)

def handle_sync(bot_token, chat_id):
    """
    Fuerza la ejecución de la sincronización de precios y Google Sheets desde Telegram.
    """
    if _sync_lock.locked():
        send_telegram_message(
            bot_token, chat_id,
            "⏳ Ya hay una sincronización en progreso en este momento. Por favor espera unos segundos...",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    def run_sync_task():
        with _sync_lock:
            try:
                send_telegram_message(
                    bot_token, chat_id,
                    "⏳ *Sincronizando mercado...*\nDescargando precios frescos de Yahoo Finance y actualizando Google Sheets..."
                )
                import market_updater
                updated_payload = market_updater.run_updater()
                count = len(updated_payload.get("data", []))
                ts = updated_payload.get("timestamp", "").split(" ")[-1]

                msg = (
                    "✅ *¡SINCRONIZACIÓN EXITOSA!*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• Activos actualizados: `{count}`\n"
                    f"• Hora: `{ts}`\n"
                    "• Google Sheets y panel web sincronizados al 100%.\n\n"
                    "Pulsa *📊 Resumen* o *🎯 Alertas* para consultar los nuevos datos."
                )
                send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)
            except Exception as e:
                send_telegram_message(
                    bot_token, chat_id,
                    f"❌ Error durante la sincronización: {e}",
                    reply_markup=TELEGRAM_MAIN_KEYBOARD
                )

    threading.Thread(target=run_sync_task, daemon=True).start()

def handle_periodo(bot_token, chat_id, arg):
    """
    Permite cambiar la temporalidad (1mo, 3mo, 6mo, 1y) y recalcular.
    """
    valid = ["1mo", "3mo", "6mo", "1y"]
    period = arg.strip().lower()
    if period not in valid:
        send_telegram_message(
            bot_token, chat_id,
            f"⚠️ Periodo no reconocido: `{arg}`.\nOpciones válidas: `1mo`, `3mo`, `6mo`, `1y`.\nEjemplo: `/periodo 1mo`",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    try:
        import market_updater
        cfg = market_updater.load_config()
        cfg["period"] = period
        market_updater.save_config(cfg)
        send_telegram_message(
            bot_token, chat_id,
            f"⏱ *Temporalidad cambiada a {period.upper()}*.\nIniciando recálculo de Fibonacci..."
        )
        handle_sync(bot_token, chat_id)
    except Exception as e:
        send_telegram_message(bot_token, chat_id, f"❌ Error al cambiar periodo: {e}", reply_markup=TELEGRAM_MAIN_KEYBOARD)

def process_user_telegram_command(bot_token, chat_id, raw_text):
    """
    Enrutador principal de comandos y mensajes recibidos del usuario.
    """
    text = raw_text.strip()
    cmd = text.lower()

    if cmd in ("/start", "/help", "/ayuda", "ℹ️ ayuda", "ayuda"):
        handle_start_or_help(bot_token, chat_id)
        return

    if cmd in ("/resumen", "/precios", "📊 resumen", "resumen", "precios"):
        handle_resumen(bot_token, chat_id)
        return

    if cmd in ("/alertas", "/oportunidades", "🎯 alertas", "alertas", "oportunidades"):
        handle_alertas(bot_token, chat_id)
        return

    if cmd in ("/sync", "/actualizar", "🔄 sincronizar", "sincronizar", "sync"):
        handle_sync(bot_token, chat_id)
        return

    if cmd.startswith("/periodo"):
        parts = text.split()
        if len(parts) > 1:
            handle_periodo(bot_token, chat_id, parts[1])
        else:
            send_telegram_message(
                bot_token, chat_id,
                "Indica el periodo deseado: `/periodo 1mo`, `/periodo 3mo`, `/periodo 6mo`, `/periodo 1y`."
            )
        return

    if cmd.startswith(("/ver", "/analizar")):
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            handle_ver_ticker(bot_token, chat_id, parts[1])
        else:
            send_telegram_message(bot_token, chat_id, "Indica el ticker que deseas ver. Ej: `/ver AMD` o `/ver TSLA`.")
        return

    if cmd.startswith(("/riesgo", "/risk", "🛡️ riesgo")):
        parts = text.split(maxsplit=1)
        raw_args = parts[1] if len(parts) > 1 else ""
        handle_riesgo(bot_token, chat_id, raw_args)
        return

    if cmd in ("/venta", "/salidas", "/vender", "🔴 venta", "venta"):
        handle_venta(bot_token, chat_id)
        return

    if cmd in ("/historial", "/diario", "/journal", "/stats", "📔 historial", "historial", "diario"):
        handle_historial(bot_token, chat_id)
        return

    # Si el usuario escribe directamente el nombre de un ticker o tab (ej: AMD, TSLA, NVDA, META, CEG, GC=F)
    # Comprobar si coincide con algún activo de seguimiento
    if os.path.exists(LATEST_DATA_PATH):
        try:
            with open(LATEST_DATA_PATH, "r", encoding="utf-8") as f:
                payload = json.load(f)
                tracked_tickers = [it.get("ticker", "").upper() for it in payload.get("data", [])]
                tracked_tabs = [it.get("tab", "").upper() for it in payload.get("data", [])]
                upper_text = text.upper().replace("$", "")
                if upper_text in tracked_tickers or upper_text in tracked_tabs:
                    handle_ver_ticker(bot_token, chat_id, upper_text)
                    return
        except Exception:
            pass

    # Comando desconocido: mostrar ayuda amable
    msg = (
        f"🤔 No he reconocido el comando: `{text}`\n\n"
        "Puedes usar los botones del teclado inferior o escribir:\n"
        "• `/resumen` (Ver todos los precios)\n"
        "• `/alertas` (Ver oportunidades)\n"
        "• `/ver AMD` (Ver ficha de un activo)\n"
        "• `/riesgo AMD 100` (Calculadora de posición)\n"
        "• `/sync` (Sincronizar ahora)"
    )
    send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)

# ==========================================
# HILO DE ESCUCHA ACTIVA (LONG-POLLING)
# ==========================================

def telegram_bot_listener_worker():
    """
    Bucle en segundo plano que escucha mensajes de Telegram y responde al instante.
    """
    global _bot_listener_running
    if _bot_listener_running:
        return
    _bot_listener_running = True
    print("[Telegram Bot] 🤖 Servicio de escucha interactiva iniciado (Long-polling 24/7).")

    offset = None
    last_config_check = 0
    cached_token = ""
    cached_chat_ids = set()

    while True:
        try:
            now = time.time()
            if now - last_config_check > 8:
                last_config_check = now
                try:
                    import market_updater
                    cfg = market_updater.load_config()
                    tg_cfg = cfg.get("telegram", {})
                    if not tg_cfg.get("enabled"):
                        time.sleep(8)
                        continue
                    new_token = tg_cfg.get("bot_token", "").strip()
                    parsed_ids = parse_chat_ids(tg_cfg.get("chat_id", ""))

                    # Si el token ha cambiado, registrar menú
                    if new_token != cached_token and new_token:
                        setup_bot_commands(new_token)

                    cached_token = new_token
                    cached_chat_ids = set(parsed_ids)
                except Exception:
                    pass

            if not cached_token or not cached_chat_ids:
                time.sleep(8)
                continue

            url = f"https://api.telegram.org/bot{cached_token}/getUpdates"
            params = {"timeout": 15, "limit": 20}
            if offset is not None:
                params["offset"] = offset

            try:
                resp = requests.get(url, params=params, timeout=20)
            except (requests.exceptions.Timeout, requests.exceptions.ReadTimeout):
                continue
            except Exception:
                time.sleep(3)
                continue

            if resp.status_code != 200:
                time.sleep(4)
                continue

            data = resp.json()
            if not data.get("ok"):
                time.sleep(4)
                continue

            updates = data.get("result", [])
            for u in updates:
                offset = u["update_id"] + 1
                msg = u.get("message")
                if not msg:
                    continue

                from_chat_id = str(msg.get("chat", {}).get("id", "")).strip()
                raw_text = (msg.get("text") or "").strip()

                # Control de seguridad: solo responder a los Chat IDs autorizados
                if from_chat_id not in cached_chat_ids:
                    send_telegram_message(
                        cached_token,
                        from_chat_id,
                        "⛔ *Acceso Denegado*\nEste bot está configurado como monitor privado personal.\n\n"
                        "💡 Si eres familiar o amigo del propietario, pídele que añada tu Chat ID a la lista en el panel web (http://localhost:5050)."
                    )
                    continue

                if not raw_text:
                    continue

                print(f"[Telegram Bot] 📩 Mensaje recibido de chat {from_chat_id}: '{raw_text}'")
                process_user_telegram_command(cached_token, from_chat_id, raw_text)

        except Exception as loop_err:
            print(f"[Telegram Bot] ⚠️ Excepción en bucle de escucha: {loop_err}")
            time.sleep(5)

def start_bot_listener_thread():
    """
    Arranca el hilo demonio de escucha interactiva.
    """
    t = threading.Thread(target=telegram_bot_listener_worker, daemon=True, name="TelegramBotListener")
    t.start()
    return t
