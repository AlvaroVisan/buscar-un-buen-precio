"""
telegram_notifier.py
Módulo de notificaciones y bot interactivo para Telegram en 'Buscar un buen precio'.
Proporciona:
1. Alertas automáticas push cuando un activo entra en la Zona Áurea (61.8%) o alcanza alta confluencia.
2. Bot interactivo bidireccional (comandos /resumen, /alertas, /ver <ticker>, /sync, /periodo).
"""

import os
import json
import math
import time
import threading
import requests
import journal_manager

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
LATEST_DATA_PATH = os.path.join(DIRECTORY, "latest_data.json")
CONFIG_PATH = os.path.join(DIRECTORY, "config.json")
ALERTS_CACHE_PATH = os.path.join(DIRECTORY, ".alerts_cache.json")

# Cooldown de 4 horas por activo persistido en disco para evitar alertas duplicadas al ejecutar .bat o reiniciar
ALERT_COOLDOWN_SECONDS = 4 * 3600  # 4 horas
_bot_listener_running = False


def escape_md(val):
    """Escapa caracteres especiales de Markdown v1 de Telegram para evitar errores HTTP 400 (can't parse entities)."""
    if val is None:
        return ""
    s = str(val)
    for ch in ("\\", "_", "*", "`", "["):
        s = s.replace(ch, f"\\{ch}")
    return s


def _load_alerts_cache():
    """Carga la caché de cooldown de alertas desde disco y limpia entradas expiradas."""
    if not os.path.exists(ALERTS_CACHE_PATH):
        return {}
    try:
        with open(ALERTS_CACHE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
            if not isinstance(raw, dict):
                return {}
            now = time.time()
            return {
                k: v for k, v in raw.items()
                if isinstance(v, dict) and (now - v.get("timestamp", 0)) < ALERT_COOLDOWN_SECONDS
            }
    except Exception:
        return {}


def _save_alerts_cache(cache_data):
    """Guarda de forma atómica la caché de cooldown de alertas en disco."""
    temp_path = f"{ALERTS_CACHE_PATH}.{threading.get_ident()}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, ALERTS_CACHE_PATH)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _format_fractional_units(val):
    """Formatea unidades fraccionadas con precisión adaptativa (útil para BTC-USD y acciones de alto precio)."""
    if val >= 0.1:
        return f"{val:.2f}"
    if val >= 0.001:
        return f"{val:.4f}"
    return f"{val:.6f}"


def _fmt_price(val, item=None):
    """Formatea un precio con la divisa y precisión decimal del activo."""
    curr = (item or {}).get("currency", "$")
    dec = int((item or {}).get("decimals", 2))
    num = float(val or 0)
    return f"{curr}{num:,.{dec}f}"

# Teclado persistente con botones rápidos de acceso en la app de Telegram
TELEGRAM_MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "📊 Resumen"}, {"text": "🎯 Alertas"}],
        [{"text": "💼 Mi Cartera"}, {"text": "📔 Historial"}],
        [{"text": "🔄 Sincronizar"}, {"text": "🧰 Herramientas"}, {"text": "ℹ️ Ayuda"}]
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
    Devuelve la URL directa a TradingView mapeando símbolos internacionales, futuros, índices, cripto y divisas.
    """
    tv_symbol = str(ticker or "").strip().upper()
    special_map = {
        "GC=F": "COMEX:GC1!",
        "SI=F": "COMEX:SI1!",
        "CL=F": "NYMEX:CL1!",
        "^GSPC": "SP:SPX",
        "^NDX": "NASDAQ:NDX",
        "^IXIC": "NASDAQ:IXIC",
        "^DJI": "DJ:DJI",
        "^IBEX": "BME:IBC"
    }
    if tv_symbol in special_map:
        tv_symbol = special_map[tv_symbol]
    elif tv_symbol.endswith("-USD"):
        tv_symbol = f"COINBASE:{tv_symbol.replace('-USD', '')}USD"
    elif tv_symbol.endswith("-EUR"):
        tv_symbol = f"COINBASE:{tv_symbol.replace('-EUR', '')}EUR"
    elif tv_symbol.endswith("=X"):
        tv_symbol = f"FX_IDC:{tv_symbol.replace('=X', '')}"
    elif tv_symbol.endswith(".MC"):
        tv_symbol = f"BME:{tv_symbol[:-3]}"
    elif tv_symbol.endswith(".DE"):
        tv_symbol = f"XETR:{tv_symbol[:-3]}"
    elif tv_symbol.endswith(".PA") or tv_symbol.endswith(".AS"):
        tv_symbol = f"EURONEXT:{tv_symbol[:-3]}"
    elif tv_symbol.endswith(".MI"):
        tv_symbol = f"MIL:{tv_symbol[:-3]}"
    elif tv_symbol.endswith(".L"):
        tv_symbol = f"LSE:{tv_symbol[:-2]}"
    return f"https://www.tradingview.com/symbols/{tv_symbol}/"


def answer_callback_query(bot_token, callback_id, text=""):
    """Responde a un botón Inline de Telegram para detener la animación de carga."""
    if not bot_token or not callback_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{bot_token.strip()}/answerCallbackQuery"
        payload = {"callback_query_id": callback_id}
        if text:
            payload["text"] = str(text)[:180]
        requests.post(url, json=payload, timeout=8)
        return True
    except Exception:
        return False


def build_alert_inline_keyboard(ticker):
    """Construye botonera Inline interactiva bajo cada alerta push."""
    t = str(ticker or "").strip().upper()
    return {
        "inline_keyboard": [
            [
                {"text": "🟢 Consejo Compra", "callback_data": f"compra:{t}"},
                {"text": "🔴 Consejo Venta", "callback_data": f"venta:{t}"}
            ],
            [
                {"text": "🛡️ Calcular Lote", "callback_data": f"riesgo:{t}:100"},
                {"text": "📈 TradingView ↗", "url": get_tradingview_url(t)}
            ]
        ]
    }


def build_buy_advice_inline_keyboard(ticker, active_period="3mo"):
    """Botonera interactiva limpia bajo el Consejo de Compra."""
    t = str(ticker or "").strip().upper()
    return {
        "inline_keyboard": [
            [
                {"text": "🔴 Consejo Venta", "callback_data": f"venta:{t}"},
                {"text": "📐 Detalle Técnico", "callback_data": f"fib:{t}:{active_period}"}
            ],
            [
                {"text": "🛡️ Calcular Lote", "callback_data": f"riesgo:{t}:100"},
                {"text": "📈 TradingView ↗", "url": get_tradingview_url(t)}
            ]
        ]
    }


def journal_tracking_context(item, _chat_id=None):
    """Pin compacto de una sola línea si hay señal activa en el Diario; cero ruido si no la hay."""
    ticker = str((item or {}).get("ticker", "")).strip()
    if not ticker:
        return ""
    try:
        tracking = journal_manager.get_tracking_signal(ticker)
    except Exception:
        return "⚠️ No se puede consultar el historial del Diario.\n\n"
    entry = tracking.get("entry")
    if not entry or not tracking.get("is_active"):
        return ""  # Cero texto si no hay seguimiento activo

    entry_p = entry.get("entry_price")
    ret = entry.get("final_return_pct")
    if ret is None:
        ret = entry.get("current_return_pct", 0.0)
    stop_p = entry.get("stop_loss")

    entry_str = _fmt_price(entry_p, entry) if isinstance(entry_p, (int, float)) else "--"
    stop_str = _fmt_price(stop_p, entry) if isinstance(stop_p, (int, float)) else "--"
    sign = "+" if ret >= 0 else ""

    return f"📌 *Seguimiento activo*: Entrada en `{entry_str}` (P&L: *{sign}{ret:.2f}%*) · Salida si cae de `{stop_str}`\n\n"


def format_current_market_context(item, period=None):
    """Sin bloques redundantemente largos; la información se integra en la narrativa principal."""
    return ""


def build_sell_advice_inline_keyboard(ticker, active_period="3mo"):
    """Botonera interactiva limpia bajo el Consejo de Venta."""
    t = str(ticker or "").strip().upper()
    return {
        "inline_keyboard": [
            [
                {"text": "🟢 Consejo Compra", "callback_data": f"compra:{t}"},
                {"text": "📐 Detalle Técnico", "callback_data": f"fib:{t}:{active_period}"}
            ],
            [
                {"text": "💼 Mi Cartera", "callback_data": "cartera"},
                {"text": "📈 TradingView ↗", "url": get_tradingview_url(t)}
            ]
        ]
    }


def build_fib_inline_keyboard(ticker, active_period="3mo"):
    """Botonera Multi-Timeframe para la vista detallada de Fibonacci."""
    t = str(ticker or "").strip().upper()
    tf_labels = [("1mo", "1M"), ("3mo", "3M"), ("6mo", "6M"), ("1y", "1A")]
    tf_row = [
        {
            "text": f"• {lbl} •" if p == active_period else lbl,
            "callback_data": f"fib:{t}:{p}"
        }
        for p, lbl in tf_labels
    ]
    return {
        "inline_keyboard": [
            tf_row,
            [
                {"text": "🟢 Consejo Compra", "callback_data": f"compra:{t}"},
                {"text": "🔴 Consejo Venta", "callback_data": f"venta:{t}"}
            ],
            [
                {"text": "📈 TradingView ↗", "url": get_tradingview_url(t)}
            ]
        ]
    }


def build_ticker_inline_keyboard(ticker, active_period="3mo"):
    """Construye botonera Inline Multi-Timeframe (0ms) y dimensionamiento rápido para una ficha técnica."""
    return build_buy_advice_inline_keyboard(ticker, active_period)

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
            return True, data.get("result", {})

        err_desc = data.get("description", f"Error HTTP {resp.status_code}")
        # Fallback automático en texto plano si falla el parseo de entidades Markdown
        if resp.status_code == 400 and parse_mode and "parse entities" in str(err_desc).lower():
            plain_payload = {k: v for k, v in payload.items() if k != "parse_mode"}
            resp_plain = requests.post(url, json=plain_payload, timeout=12)
            data_plain = resp_plain.json()
            if resp_plain.status_code == 200 and data_plain.get("ok"):
                return True, data_plain.get("result", {})
            err_desc = data_plain.get("description", err_desc)

        return False, err_desc
    except Exception as e:
        return False, f"Error de conexión con Telegram: {str(e)}"


def pin_telegram_message(bot_token, chat_id, message_id, disable_notification=True):
    """
    Fija un mensaje relevante en Telegram (PIN) para que quede anclado arriba del chat.
    disable_notification=True evita emitir un pitido molesto al anclarlo.
    """
    if not bot_token or not chat_id or not message_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{bot_token.strip()}/pinChatMessage"
        resp = requests.post(url, json={
            "chat_id": str(chat_id).strip(),
            "message_id": int(message_id),
            "disable_notification": disable_notification
        }, timeout=8)
        return resp.status_code == 200 and resp.json().get("ok")
    except Exception:
        return False

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
            {"command": "ver", "description": "🔍 Analizar un activo (ej: /ver AMD)"},
            {"command": "cartera", "description": "💼 Mi Cartera Real, PnL abierto y alertas SL/TP"},
            {"command": "historial", "description": "📔 Diario de trading y tasa de acierto"},
            {"command": "actualizar", "description": "🔄 Actualizar mercado y Google Sheets"},
            {"command": "herramientas", "description": "🧰 Análisis técnico y gestión de activos"},
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

def find_asset_item(query):
    """
    Busca un activo en latest_data.json por ticker, pestaña o nombre (insensible a mayúsculas).
    Soporta alias comunes como ORO, SPX, PLATA, NASDAQ.
    """
    if not query or not os.path.exists(LATEST_DATA_PATH):
        return None
    clean_query = str(query).strip().upper().replace("$", "").replace("/", "")
    alias_map = {
        "ORO": "GC=F", "GOLD": "GC=F",
        "PLATA": "SI=F", "SILVER": "SI=F",
        "PETROLEO": "CL=F", "CRUDE": "CL=F", "OIL": "CL=F",
        "SPX": "^GSPC", "S&P500": "^GSPC", "SP500": "^GSPC",
        "NDX": "^NDX", "NASDAQ": "^IXIC", "IBEX": "^IBEX"
    }
    target = alias_map.get(clean_query, clean_query)
    try:
        with open(LATEST_DATA_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        for it in payload.get("data", []):
            t = it.get("ticker", "").upper()
            tab = it.get("tab", "").upper()
            name = it.get("name", "").upper()
            if target in (t, tab, name) or clean_query in (t, tab, name):
                return it
    except Exception:
        pass
    return None


def format_buy_advice(item, period="3mo"):
    """
    Construye un pronóstico directo y plan de ejecución táctico (se moja):
    1. Pronóstico: ¿Sube, baja, o baja primero para luego rebotar?
    2. Contexto de inercia y suelo.
    3. Plan táctico de ejecución (entrada en 2 tramos, objetivos y stop).
    4. Pines de aviso relevante (Resultados / Earnings).
    """
    ticker = item.get("ticker", "")
    tab = escape_md(item.get("tab", ticker))
    price = item.get("current_price", 0)
    drop = item.get("drop_pct", 0)
    p_max = item.get("max", price)
    p_min = item.get("min", price)
    score = item.get("score", 0)
    swing_type = item.get("swing_type", "")

    risk = item.get("risk_mgmt") or {}
    liq = item.get("liquidity") or {}
    earnings = item.get("earnings") or {}

    poc_p = liq.get("poc_price", 0) if liq.get("has_real_volume") and liq.get("profile_type") == "VOLUME" else 0
    ssl_p = liq.get("ssl_pool_price", 0)
    floor_p = ssl_p if (ssl_p and ssl_p < price) else (p_min if (p_min and p_min < price) else price * 0.95)

    sl = risk.get("ssl_stop_loss") or risk.get("stop_loss") or (price * 0.95)
    tp1 = risk.get("take_profit_1") or (price * 1.10)
    tp2 = risk.get("take_profit_2") or p_max

    gain_tp1 = risk.get("reward_1_pct", ((tp1 - price) / price * 100) if price > 0 else 0)
    gain_tp2 = risk.get("reward_2_pct", ((tp2 - price) / price * 100) if price > 0 else 0)
    loss_pct = ((price - sl) / price * 100) if price > 0 else 0

    has_imminent_earnings = earnings.get("has_earnings") and (earnings.get("days_until") is not None and earnings.get("days_until") <= 2)

    # 1. PRONÓSTICO DIRECTO Y TRAYECTORIA
    if drop >= 10.0 or swing_type == "FALLING_KNIFE" or has_imminent_earnings:
        forecast_title = "🔮 *PRONÓSTICO: Baja primero, sube después.*"
        earn_clause = " y la tensión previa de resultados" if has_imminent_earnings else ""
        vol_clause = f" (muro de compras institucional en `{_fmt_price(poc_p, item)}`)" if poc_p > 0 else ""
        explanation = (
            f"Tras una corrección del *-{drop:.1f}%* desde sus máximos de `{_fmt_price(p_max, item)}`{earn_clause}, "
            f"la inercia presiona a testear el suelo en torno a `{_fmt_price(floor_p, item)}`{vol_clause}. "
            f"Desde esa zona de soporte, la proyección estadística apunta a un *rebote potente hacia `{_fmt_price(tp1, item)}` (+{gain_tp1:.1f}%)*."
        )
        plan_bullets = (
            f"🎯 *Plan de ejecución (Cómo se juega esto):*\n"
            f"• *Entrada en 2 tramos*: 50% de tu posición ahora en `{_fmt_price(price, item)}`, y guardas el otro 50% por si visita `{_fmt_price(floor_p, item)}` para cargar más barato.\n"
            f"• *Objetivo de beneficio*: Salida en `{_fmt_price(tp1, item)}` *(+{gain_tp1:.1f}%)*, con margen hacia `{_fmt_price(tp2, item)}` *(+{gain_tp2:.1f}%)*.\n"
            f"• *Dónde nos salimos si sale mal*: Si perfora los `{_fmt_price(sl, item)}` *(-{loss_pct:.1f}%)*, el pronóstico se anula y cerramos la posición sin dudar."
        )
        header_icon = "🟢"
    elif score >= 65 and drop >= 4.0:
        forecast_title = "🔮 *PRONÓSTICO: SUBE.*"
        explanation = (
            f"*{tab}* ha conseguido frenar en el soporte de `{_fmt_price(floor_p, item)}` tras retroceder un *-{drop:.1f}%*. "
            f"El volumen vendedor se ha secado y la proyección apunta a un rebote directo hacia `{_fmt_price(tp1, item)}` *(+{gain_tp1:.1f}%)*."
        )
        plan_bullets = (
            f"🎯 *Plan de ejecución:*\n"
            f"• *Entrada directa*: Compra aquí en `{_fmt_price(price, item)}`.\n"
            f"• *Objetivo*: `{_fmt_price(tp1, item)}` *(+{gain_tp1:.1f}%)*, y segundo impulso a `{_fmt_price(tp2, item)}` *(+{gain_tp2:.1f}%)*.\n"
            f"• *Dónde nos salimos si sale mal*: Si pierde los `{_fmt_price(sl, item)}` *(-{loss_pct:.1f}%)*, cortamos para proteger capital."
        )
        header_icon = "🟢"
    else:
        forecast_title = "🔮 *PRONÓSTICO: AÚN NO ENTRAR.*"
        explanation = (
            f"*{tab}* cotiza en `{_fmt_price(price, item)}` sin descuento técnico suficiente o sin suelo confirmado. "
            f"Entrar ahora tiene un riesgo innecesario. Lo sensato es esperar a que caiga hacia la zona de `{_fmt_price(floor_p, item)}` antes de arriesgar dinero."
        )
        plan_bullets = (
            f"🎯 *Plan de acción:*\n"
            f"• *No compres todavía*: Mantente al margen hasta que el precio visite `{_fmt_price(floor_p, item)}`.\n"
            f"• *Vigilar*: Si frena en ese suelo, se abrirá la ventana de rebote hacia `{_fmt_price(tp1, item)}`."
        )
        header_icon = "🟡"

    # Pines con información relevante adicional (Resultados)
    pins = []
    if earnings.get("has_earnings") and earnings.get("short_date"):
        ed = earnings.get("short_date")
        du = earnings.get("days_until")
        eps = earnings.get("eps_avg")
        eps_txt = f" (beneficio previsto: `${eps}`/acc)" if eps is not None else ""
        if du == 0:
            when = "HOY"
        elif du == 1:
            when = "MAÑANA"
        elif du is not None and du <= 5:
            when = f"en {du} días ({ed})"
        else:
            when = f"el {ed}"
        pins.append(f"📌 *Resultados*: Presenta cuentas *{when}*{eps_txt}. Atención a la volatilidad extrema.")

    pins_str = ("\n\n" + "\n".join(pins)) if pins else ""

    msg = (
        f"{header_icon} *{tab}* · `{_fmt_price(price, item)}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{forecast_title}\n\n"
        f"{explanation}\n\n"
        f"{plan_bullets}"
        f"{pins_str}"
    )
    stale_warn = f"⚠️ *Cotización desactualizada* ({escape_md(item.get('last_success_at') or '')})\n\n" if item.get("is_stale") else ""
    return stale_warn + msg


def format_sell_advice(item, period="3mo"):
    """
    Construye un pronóstico directo de salida y toma de beneficios:
    1. Pronóstico: BAJA (agotamiento alcista).
    2. Contexto de techo y cercanía a máximos.
    3. Plan táctico de aseguramiento de ganancias.
    4. Pines de aviso relevante.
    """
    ticker = item.get("ticker", "")
    tab = escape_md(item.get("tab", ticker))
    price = item.get("current_price", 0)
    p_max = item.get("max", price)
    p_min = item.get("min", price)
    sm = item.get("sell_mgmt") or {}
    gain_low = sm.get("gain_from_low_pct", 0)
    dist_hi = sm.get("dist_to_high_pct", 0)
    t_stop = sm.get("trailing_stop") or (price * 0.95)
    earnings = item.get("earnings") or {}

    fibs = item.get("fib_levels") or {}
    f50 = fibs.get("50.0%", p_min)
    prot_pct = ((price - t_stop) / price * 100) if price > 0 else 0

    forecast_title = "🔮 *PRONÓSTICO: BAJA (Toca recoger).* "
    explanation = (
        f"*{tab}* acumula un alza del *+{gain_low:.1f}%* desde mínimos y está a solo un *{dist_hi:.1f}%* de su techo en `{_fmt_price(p_max, item)}`. "
        f"El impulso comprador está agotado y el escenario más probable es un retroceso hacia el soporte de `{_fmt_price(f50, item)}`."
    )
    plan_bullets = (
        f"🎯 *Plan de acción:*\n"
        f"• *No comprar*: El tren de subida ya ha salido y el riesgo aquí es máximo.\n"
        f"• *Asegurar ganancias*: Toma beneficios parciales o pon un stop de protección en `{_fmt_price(t_stop, item)}` *(-{prot_pct:.1f}%)* para blindar lo ganado si el precio se gira."
    )

    pins = []
    if earnings.get("has_earnings") and earnings.get("short_date"):
        ed = earnings.get("short_date")
        du = earnings.get("days_until")
        eps = earnings.get("eps_avg")
        eps_txt = f" (beneficio previsto: `${eps}`/acc)" if eps is not None else ""
        if du == 0:
            when = "HOY"
        elif du == 1:
            when = "MAÑANA"
        elif du is not None and du <= 5:
            when = f"en {du} días ({ed})"
        else:
            when = f"el {ed}"
        pins.append(f"📌 *Resultados*: Presenta cuentas *{when}*{eps_txt}. Atención a la volatilidad extrema.")

    pins_str = ("\n\n" + "\n".join(pins)) if pins else ""

    msg = (
        f"🔴 *{tab}* · `{_fmt_price(price, item)}` (Zona de Venta)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{forecast_title}\n\n"
        f"{explanation}\n\n"
        f"{plan_bullets}"
        f"{pins_str}"
    )
    stale_warn = f"⚠️ *Cotización desactualizada* ({escape_md(item.get('last_success_at') or '')})\n\n" if item.get("is_stale") else ""
    return stale_warn + msg


def format_detailed_fibonacci(item, period="3mo"):
    """
    Construye la vista técnica de la Escalera de Fibonacci con etiquetas de liquidez
    (Muro POC, % de volumen, LVN) de forma concisa y elegante.
    """
    ticker = item.get("ticker", "")
    tab = escape_md(item.get("tab", ticker))
    price = item.get("current_price", 0)
    p_min = item.get("min", 0)
    p_max = item.get("max", 0)
    fibs = item.get("fib_levels", {})
    liq = item.get("liquidity") or {}
    fib_liq = liq.get("fib_liquidity") or {}

    def _tag(lvl):
        fl = fib_liq.get(lvl)
        if not fl:
            return ""
        if fl.get("is_poc"):
            return " `🏦 Muro POC`"
        if fl.get("tier") == "HIGH":
            return f" `🏦 Liq {fl.get('strength_pct', 0)}%`"
        if fl.get("tier") == "LOW":
            return " `🕳️ LVN`"
        return ""

    poc_p = liq.get("poc_price", price)
    val_p = liq.get("val_price", p_min)
    vah_p = liq.get("vah_price", p_max)
    tv_url = get_tradingview_url(ticker)

    msg = (
        f"📐 *ESCALERA FIBONACCI: {tab} ({ticker})*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Rango ({period.upper()})*: `{_fmt_price(p_min, item)}` – `{_fmt_price(p_max, item)}`\n"
        f"💰 *Precio actual*: `{_fmt_price(price, item)}`\n\n"
        f"🏆 *NIVELES Y DENSIDAD DE LIQUIDEZ:*\n"
        f"• 23.6%: `{_fmt_price(fibs.get('23.6%', 0), item)}`{_tag('23.6%')}\n"
        f"• 38.2%: `{_fmt_price(fibs.get('38.2%', 0), item)}`{_tag('38.2%')}\n"
        f"• 50.0% (Zona Compra): `{_fmt_price(fibs.get('50.0%', 0), item)}`{_tag('50.0%')}\n"
        f"• 61.8% (Zona Áurea): `{_fmt_price(fibs.get('61.8%', 0), item)}`{_tag('61.8%')}\n"
        f"• 78.6% (Soporte Extremo): `{_fmt_price(fibs.get('78.6%', 0), item)}`{_tag('78.6%')}\n\n"
        f"🏦 *Muro POC*: `{_fmt_price(poc_p, item)}` | *Área Valor 70%*: `{_fmt_price(val_p, item)}` – `{_fmt_price(vah_p, item)}`\n\n"
        f"[📊 Abrir Gráfico en TradingView]({tv_url})"
    )
    return (f"⚠️ Cotización desactualizada. Último dato válido: {escape_md(item.get('last_success_at') or 'fecha desconocida')}\n\n" if item.get("is_stale") else "") + msg


def format_telegram_alert(item, period="3mo"):
    """
    Construye la alerta sintetizada de oportunidad detectada utilizando el Consejo de Compra.
    """
    return format_buy_advice(item, period=period)

def dispatch_telegram_alerts(market_payload, config):
    """
    Evalúa los activos del payload y envía notificaciones a Telegram si cumplen los criterios.
    Usa caché con cooldown para evitar inundar el chat y respeta Horario Inteligente de Mercado.
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

    import market_updater
    smart_hours = config.get("scheduler", {}).get("smart_hours_only", True)
    mh = market_updater.evaluate_market_hours(config.get("assets", []))

    sent_count = 0
    now = time.time()
    alerts_cache = _load_alerts_cache()
    cache_modified = False

    for item in market_payload.get("data", []):
        ticker = item.get("ticker")
        # Con Horario Inteligente activo, silenciar alertas push de bolsa cerrada (manteniendo Cripto 24/7)
        if smart_hours and not mh["equities_open"] and not market_updater.is_crypto_ticker(ticker):
            continue

        current_price = item.get("current_price", 0)
        fib_golden = item.get("fib_levels", {}).get("61.8%", 0)
        score = item.get("score", 0)

        is_golden = current_price <= fib_golden
        is_high_score = score >= min_score

        qualifies = (notify_golden and is_golden) or (notify_confluence and is_high_score)
        if not qualifies:
            continue

        # Comprobar cooldown persistido en disco
        last_alert = alerts_cache.get(ticker)
        if last_alert:
            elapsed = now - last_alert.get("timestamp", 0)
            if elapsed < ALERT_COOLDOWN_SECONDS:
                continue

        # Enviar alerta con botonera Inline interactiva a todos los destinatarios autorizados
        alert_text = format_telegram_alert(item, period=period)
        delivered_to_any = False
        for cid in chat_ids:
            inline_kb = build_buy_advice_inline_keyboard(ticker, period)
            ok, res = send_telegram_message(bot_token, cid, journal_tracking_context(item, cid) + alert_text, reply_markup=inline_kb)
            if ok:
                delivered_to_any = True
                print(f"[Telegram Notifier] 📲 Alerta enviada para {ticker} ({item.get('tab')}) al chat {cid}")
                if isinstance(res, dict) and "message_id" in res:
                    pin_telegram_message(bot_token, cid, res["message_id"], disable_notification=True)
            else:
                print(f"[Telegram Notifier] ❌ Error enviando alerta para {ticker} a {cid}: {res}")
            time.sleep(0.2)

        if delivered_to_any:
            sent_count += 1
            alerts_cache[ticker] = {
                "timestamp": now,
                "price": current_price,
                "score": score
            }
            cache_modified = True

    if cache_modified:
        _save_alerts_cache(alerts_cache)

    return {"sent": sent_count, "status": "Completado"}

# ==========================================
# GESTORES DE COMANDOS INTERACTIVOS (BOT 24/7)
# ==========================================

def handle_start_or_help(bot_token, chat_id):
    """Guía breve de las consultas habituales."""
    msg = (
        "🤖 *ASISTENTE FIBONACCI*\n\n"
        "📊 /resumen — Todos los activos: precios y puntuación.\n"
        "🎯 /alertas — Solo los que cumplen los filtros de oportunidad.\n"
        "🔍 /ver TICKER — Análisis según la situación del activo.\n"
        "También puedes escribir directamente el ticker, por ejemplo `AMD`.\n"
        "Desde su ficha puedes abrir Compra, Venta, Fibonacci y Riesgo.\n\n"
        "💼 /cartera — Tus posiciones y PnL abierto.\n"
        "📔 /historial — Resultados de las señales del diario.\n"
        "📔 `/ver AMD` muestra primero si hay seguimiento activo y sus niveles originales.\n"
        "🔄 /actualizar — Actualizar mercado y Google Sheets.\n\n"
        "🧰 /herramientas — Análisis especializado y gestión de activos.\n"
        "Los comandos anteriores siguen disponibles."
    )
    send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)


def handle_herramientas(bot_token, chat_id):
    """Agrupa las opciones especializadas fuera del menú principal."""
    msg = (
        "🧰 *HERRAMIENTAS*\n\n"
        "*Análisis de un activo*\n"
        "• `/compra AMD` — Entrada, stop y objetivos.\n"
        "• `/venta AMD` — Plan de salida y trailing stop.\n"
        "• `/fibo AMD` — Niveles y botones de periodo.\n"
        "• `/riesgo AMD 100` — Tamaño de posición para arriesgar 100.\n\n"
        "*Radares*\n"
        "• /venta — Activos en resistencia o sobrecompra.\n"
        "• /liquidez — POC, volumen relativo y barridos de stops.\n\n"
        "*Gestión*\n"
        "• `/add AAPL Apple` — Añadir a seguimiento.\n"
        "• `/del AAPL` — Eliminar de seguimiento.\n"
        "• `/periodo 3mo` — Periodo global: 1mo, 3mo, 6mo, 1y.\n\n"
        "Para empezar por un activo, usa `/ver AMD`."
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
            tab = it.get("tab", ticker) + (" ⚠️ desactualizado" if it.get("is_stale") else "")
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

            lines.append(f"{icon} *{escape_md(tab)}* (`{ticker}`): `{_fmt_price(price, it)}` (-{drop:.1f}%)\n   └ Score: *{score}/100* | {escape_md(it.get('signal', ''))}")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("💡 _Escribe `/ver TICKER` (ej: `/ver AMD`) para ver todos sus niveles Fibonacci._")

        msg = "\n".join(lines)
        send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)
    except Exception as e:
        send_telegram_message(bot_token, chat_id, f"❌ Error al generar resumen: {escape_md(e)}", reply_markup=TELEGRAM_MAIN_KEYBOARD)

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
        opportunities = []
        for it in items:
            price = it.get("current_price", 0)
            fib_golden = it.get("fib_levels", {}).get("61.8%", 0)
            score = it.get("score", 0)
            if (fib_golden > 0 and price <= fib_golden) or score >= 70:
                opportunities.append(it)

        if not opportunities:
            msg = (
                "🎯 *RADAR DE OPORTUNIDADES*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "✅ Ningún activo está actualmente en Zona Áurea (61.8%) ni con Score ≥ 70.\n\n"
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
            tab = escape_md(it.get("tab", ticker))
            price = it.get("current_price", 0)
            drop = it.get("drop_pct", 0)
            score = it.get("score", 0)
            fib_golden = it.get("fib_levels", {}).get("61.8%", 0)
            rsi = it.get("rsi")
            rsi_str = f"{rsi:.1f}" if isinstance(rsi, (int, float)) else "--"

            lines.append(
                f"🔥 *{tab}* (`{ticker}`) — Score: *{score}/100*\n"
                f"• Precio: `{_fmt_price(price, it)}` (-{drop:.1f}% desc) | RSI: `{rsi_str}`\n"
                f"• Zona Áurea: `{_fmt_price(fib_golden, it)}` → `/compra {ticker}`\n"
            )

        lines.append("💡 _Pulsa un comando `/compra TICKER` para ver el plan operativo de entrada y Stop Loss._")
        msg = "\n".join(lines)
        send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)
    except Exception as e:
        send_telegram_message(bot_token, chat_id, f"❌ Error al consultar alertas: {escape_md(e)}", reply_markup=TELEGRAM_MAIN_KEYBOARD)


def handle_compra(bot_token, chat_id, query=""):
    """
    Envía la proyección narrativa de compra (Contexto, Hoja de Ruta, Invalidación y Veredicto).
    Si no se indica ticker, envía directamente la oportunidad #1 del mercado con accesos a las demás.
    """
    clean_q = (query or "").strip()
    if not clean_q:
        if os.path.exists(LATEST_DATA_PATH):
            try:
                with open(LATEST_DATA_PATH, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                items = sorted(payload.get("data", []), key=lambda x: x.get("score", 0), reverse=True)
                top = items[:3]
                if top:
                    best = top[0]
                    best_t = best.get("ticker", "")
                    others = [f"`/compra {it.get('ticker')}`" for it in top[1:] if it.get("ticker")]
                    others_txt = f"\n\n📌 *Otras oportunidades destacadas:* {' | '.join(others)}" if others else ""
                    period = best.get("period") or payload.get("period", "3mo")
                    text = journal_tracking_context(best, chat_id) + f"🏆 *OPORTUNIDAD DESTACADA #1 DEL MERCADO:*\n\n{format_buy_advice(best, period)}{others_txt}"
                    kb = build_buy_advice_inline_keyboard(best_t, period)
                    send_telegram_message(bot_token, chat_id, text, reply_markup=kb)
                    return
            except Exception:
                pass

        send_telegram_message(
            bot_token, chat_id,
            "🟢 *PROYECCIÓN DE COMPRA*\n━━━━━━━━━━━━━━━━━━━━━━━━━━\nIndica el ticker que deseas analizar.\n• Ejemplo: `/compra NVDA` o `/compra AMD`",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    item = find_asset_item(clean_q)
    if not item:
        send_telegram_message(
            bot_token, chat_id,
            f"🔍 *Activo no encontrado: '{escape_md(clean_q)}'*\n"
            "El activo no está en tu lista de seguimiento.\n\n"
            f"💡 _Añádelo con:_ `/add {escape_md(clean_q)}`",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    period = item.get("period", "3mo")
    text = journal_tracking_context(item, chat_id) + format_buy_advice(item, period)
    kb = build_buy_advice_inline_keyboard(item.get("ticker", clean_q), period)
    send_telegram_message(bot_token, chat_id, text, reply_markup=kb)


def handle_fibonacci_detail(bot_token, chat_id, query, forced_period=None):
    """
    Muestra la escalera detallada de Fibonacci con niveles de liquidez institucional (0ms Multi-Timeframe).
    """
    clean_q = (query or "").strip()
    if not clean_q:
        send_telegram_message(
            bot_token, chat_id,
            "📐 *ESCALERA FIBONACCI*\nIndica el ticker que deseas ver. Ej: `/fibo NVDA` o `/fibo AMD`.",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    item = find_asset_item(clean_q)
    if not item:
        send_telegram_message(
            bot_token, chat_id,
            f"🔍 *Activo no encontrado: '{escape_md(clean_q)}'*",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    view_item = dict(item)
    period = forced_period or item.get("period", "3mo")
    if forced_period and isinstance(item.get("timeframes"), dict) and forced_period in item["timeframes"]:
        view_item.update(item["timeframes"][forced_period])

    text = format_detailed_fibonacci(view_item, period=period)
    kb = build_fib_inline_keyboard(item.get("ticker", clean_q), active_period=period)
    send_telegram_message(bot_token, chat_id, journal_tracking_context(view_item, chat_id) + text, reply_markup=kb)


def handle_ver_ticker(bot_token, chat_id, query, forced_period=None):
    """
    Muestra el análisis sintetizado del activo solicitado.
    Si el activo tiene alta presión de venta, envía el Consejo de Venta.
    En caso contrario, envía el Consejo de Compra (con botones para ver Fibo, Venta, etc.).
    """
    clean_q = (query or "").strip()
    item = find_asset_item(clean_q)
    if not item:
        # Una señal histórica sigue siendo consultable aunque se retire el activo.
        try:
            tracking = journal_manager.get_tracking_signal(clean_q)
        except ValueError:
            tracking = {"entry": None}
        if tracking["entry"]:
            send_telegram_message(bot_token, chat_id,
                                  journal_tracking_context(tracking["entry"]) + "Este activo ya no está en la lista de seguimiento de precios; no hay una lectura actual disponible.",
                                  reply_markup=TELEGRAM_MAIN_KEYBOARD)
            return
        send_telegram_message(
            bot_token, chat_id,
            f"🔍 *Activo no encontrado: '{escape_md(clean_q)}'*\n"
            "El activo no está en tu lista de seguimiento actual.\n\n"
            f"💡 _Puedes añadirlo ahora mismo escribiendo:_ `/add {escape_md(clean_q)}`",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    view_item = dict(item)
    period = forced_period or item.get("period", "3mo")
    if forced_period and isinstance(item.get("timeframes"), dict) and forced_period in item["timeframes"]:
        view_item.update(item["timeframes"][forced_period])

    sm = view_item.get("sell_mgmt") or {}
    sell_score = sm.get("sell_score", 0)
    dist_high = sm.get("dist_to_high_pct", 10.0)

    # Si está sobrecomprado o en zona de resistencia, mostrar Consejo de Venta
    if sell_score >= 50 or dist_high <= 2.5:
        text = format_sell_advice(view_item, period=period)
        kb = build_sell_advice_inline_keyboard(view_item.get("ticker", clean_q), active_period=period)
    else:
        text = format_buy_advice(view_item, period=period)
        kb = build_buy_advice_inline_keyboard(view_item.get("ticker", clean_q), period)

    send_telegram_message(bot_token, chat_id, journal_tracking_context(view_item, chat_id) + text, reply_markup=kb)

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
            f"🔍 *Activo no encontrado: '{escape_md(query_ticker)}'*\n"
            "Por favor indica un ticker de tu lista (ej: `AMD`, `TSLA`, `NVDA`, `META`).",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    ticker = matched_item.get("ticker", "")
    tab = escape_md(matched_item.get("tab", ticker))
    price = matched_item.get("current_price", 0)
    risk_mgmt = matched_item.get("risk_mgmt")

    if not risk_mgmt:
        send_telegram_message(
            bot_token, chat_id,
            f"⚠️ No hay cálculo de riesgo disponible para {ticker}. Pulsa *🔄 Sincronizar*.",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    dec = int(matched_item.get("decimals", 2))
    curr_sym = matched_item.get("currency", "$")
    min_risk_unit = 0.0001 if dec >= 4 else 0.01
    entry = risk_mgmt.get("entry_price", price)
    sl = risk_mgmt.get("stop_loss", price * 0.95)
    risk_per_share = risk_mgmt.get("risk_per_share", max(min_risk_unit, entry - sl))
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
        exact_frac = (budget / risk_per_share) if risk_per_share > 0 else 0.0
        frac_str = _format_fractional_units(exact_frac)
        frac_inv = round(exact_frac * entry, 2)
        frac_gain_tp2 = round(exact_frac * (tp2 - entry), 2)
        sizing_text = (
            f"⚠️ *Presupuesto de riesgo inferior al de 1 título entero.*\n"
            f"• Con tu presupuesto (`{curr_sym}{budget:,.2f}`), el riesgo de 1 título completo (`{_fmt_price(risk_per_share, matched_item)}`) es superior.\n"
            f"• *Opción Fraccionada (recomendada)*: Compra *{frac_str} títulos* (Inversión: *{curr_sym}{frac_inv:,.2f}*) para limitar tu riesgo exactamente a *-{curr_sym}{budget:,.2f}* (Beneficio TP2: *+{curr_sym}{frac_gain_tp2:,.2f}*).\n"
            f"• *Opción 1 Título Entero*: Tu riesgo real si toca Stop Loss sería de *-{curr_sym}{needed_risk:,.2f}* (Inversión: *{curr_sym}{total_inv_min:,.2f}*)."
        )
    else:
        total_inv = round(shares * entry, 2)
        max_loss = round(shares * risk_per_share, 2)
        gain_tp1 = round(shares * (tp1 - entry), 2)
        gain_tp2 = round(shares * (tp2 - entry), 2)
        sizing_text = (
            f"📦 *DIMENSIONAMIENTO DE POSICIÓN:*\n"
            f"• Acciones a comprar: *{shares} títulos*\n"
            f"• Capital total a invertir: *{curr_sym}{total_inv:,.2f}*\n"
            f"• Pérdida máxima controlada (Stop Loss): *-{curr_sym}{max_loss:,.2f}*\n"
            f"• Beneficio estimado TP1: *+{curr_sym}{gain_tp1:,.2f}* (+{tp1_pct:.1f}%)\n"
            f"• Beneficio estimado TP2: *+{curr_sym}{gain_tp2:,.2f}* (+{tp2_pct:.1f}%)"
        )

    tv_url = get_tradingview_url(ticker)
    atr_sl = risk_mgmt.get("atr_stop_loss")
    atr_sl_pct = risk_mgmt.get("atr_risk_pct", 0)
    atr_line = f"🌊 *Stop Volatilidad (2x ATR 14)*: `{_fmt_price(atr_sl, matched_item)}` (-{atr_sl_pct:.1f}%)\n" if atr_sl else ""

    ssl_sl = risk_mgmt.get("ssl_stop_loss")
    ssl_sl_pct = risk_mgmt.get("ssl_risk_pct", 0)
    ssl_line = f"🧲 *Stop Bajo Piscina Liquidez (SSL)*: `{_fmt_price(ssl_sl, matched_item)}` (-{ssl_sl_pct:.1f}%)\n" if ssl_sl else ""

    earnings = matched_item.get("earnings") or {}
    earn_warn = ""
    if earnings.get("warning_level") == "IMMINENT" and earnings.get("label"):
        earn_warn = f"⚠️ *Aviso Resultados*: `{escape_md(earnings['label'])}` _(riesgo de gap)_\n"

    msg = (
        f"🛡️ *PLAN DE TRADING Y RIESGO: {tab} ({ticker})*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{earn_warn}"
        f"💼 *Presupuesto de Riesgo Máximo*: `{curr_sym}{budget:,.2f}`\n"
        f"📍 *Punto de Entrada*: `{_fmt_price(entry, matched_item)}` ({escape_md(risk_mgmt.get('entry_label', ''))})\n"
        f"🛑 *Stop Loss Fibonacci (78.6%)*: `{_fmt_price(sl, matched_item)}` (-{risk_pct:.1f}%)\n"
        f"{atr_line}"
        f"{ssl_line}"
        f"🎯 *Take Profit 1 (38.2%)*: `{_fmt_price(tp1, matched_item)}` (+{tp1_pct:.1f}%)\n"
        f"🏆 *Take Profit 2 (Máximos)*: `{_fmt_price(tp2, matched_item)}` (+{tp2_pct:.1f}%)\n"
        f"⚖️ *Ratio Riesgo/Beneficio*: `1:{rr2}` ({escape_md(rr_rating)})\n\n"
        f"{sizing_text}\n\n"
        f"💡 _Regla de oro: No aumentes tu posición sin desplazar antes el Stop Loss a precio de entrada (Break-Even)._\n\n"
        f"[📊 Abrir Gráfico en TradingView]({tv_url})"
    )
    send_telegram_message(bot_token, chat_id, journal_tracking_context(matched_item, chat_id) + msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)

def handle_venta(bot_token, chat_id, query=""):
    """
    Radar de Modo Venta / Consejo de Venta sintetizado.
    Si se especifica ticker, envía el Consejo de Venta individual.
    Si no, muestra el radar de activos sobrecalentados o en resistencia.
    """
    clean_q = (query or "").strip()
    if clean_q:
        item = find_asset_item(clean_q)
        if not item:
            send_telegram_message(
                bot_token, chat_id,
                f"🔍 *Activo no encontrado: '{escape_md(clean_q)}'*\n"
                "El activo no está en tu lista de seguimiento.",
                reply_markup=TELEGRAM_MAIN_KEYBOARD
            )
            return

        period = item.get("period", "3mo")
        text = journal_tracking_context(item, chat_id) + format_sell_advice(item, period)
        kb = build_sell_advice_inline_keyboard(item.get("ticker", clean_q), period)
        send_telegram_message(bot_token, chat_id, text, reply_markup=kb)
        return

    # Modo radar general (sin ticker especificado)
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
            if score >= 35 or (isinstance(rsi, (int, float)) and rsi >= 62) or dist_high <= 4.0:
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
            tab = escape_md(it.get("tab", ticker))
            price = it.get("current_price", 0)
            sm = it.get("sell_mgmt", {})
            score = sm.get("sell_score", 0)
            signal = escape_md(sm.get("sell_signal", "Atención"))
            action = escape_md(sm.get("sell_action", "Revisar"))
            rsi = it.get("rsi")
            rsi_str = f"{rsi:.1f}" if isinstance(rsi, (int, float)) else "--"
            dist_hi = sm.get("dist_to_high_pct", 0)
            t_stop = sm.get("trailing_stop", price * 0.94)

            icon = "🔥" if score >= 70 else ("🟠" if score >= 50 else "🟡")
            lines.append(
                f"{icon} *{tab}* (`{ticker}`) — Presión: *{score}/100*\n"
                f"• Precio: `{_fmt_price(price, it)}` (-{dist_hi:.1f}% techo) | RSI: `{rsi_str}`\n"
                f"• Trailing Stop: `{_fmt_price(t_stop, it)}` | Estado: *{signal}*\n"
                f"💡 _{action}_ → `/venta {ticker}`\n"
            )

        lines.append("💡 _Escribe `/venta TICKER` (ej: `/venta AAPL`) para ver su plan de salida individual._")
        msg = "\n".join(lines)
        send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)
    except Exception as e:
        send_telegram_message(bot_token, chat_id, f"❌ Error al consultar modo venta: {escape_md(e)}", reply_markup=TELEGRAM_MAIN_KEYBOARD)

def handle_historial(bot_token, chat_id, filter_mode="ALL"):
    """
    Diario de Trading y Rendimiento del algoritmo.
    Muestra la tasa de acierto (Win Rate), desglose de operaciones ganadas en TP y cerradas en Stop Loss.
    """
    try:
        import journal_manager
        j_data = journal_manager.load_journal()
        stats = j_data.get("stats", {})
        entries = j_data.get("entries", [])

        total = stats.get("total_opportunities", len(entries))
        active_entries = [e for e in entries if e.get("status") in ("ACTIVA", "TP1_ALCANZADO")]
        won_entries = [e for e in entries if e.get("result") == "GANADA" or e.get("status") in ("TP2_ALCANZADO", "BREAKEVEN_EJECUTADO")]
        lost_entries = [e for e in entries if e.get("result") == "PERDIDA" or e.get("status") == "STOP_EJECUTADO"]
        closed_entries = [e for e in entries if e.get("status") not in ("ACTIVA", "TP1_ALCANZADO")]

        active = stats.get("active_count", len(active_entries))
        closed = stats.get("closed_count", len(closed_entries))
        win_rate = stats.get("win_rate_pct", 0.0)
        loss_rate = stats.get("loss_rate_pct", 0.0)
        won = stats.get("total_won", len(won_entries))
        lost = stats.get("total_lost", len(lost_entries))
        avg_win = stats.get("avg_win_pct", 0.0)
        avg_loss = stats.get("avg_loss_pct", 0.0)

        f_mode = str(filter_mode or "ALL").upper()

        if closed == 0:
            bal_str = "0.0%"
        elif won == 0 and lost > 0:
            bal_str = f"-{loss_rate:.1f}%"
        elif won > 0 and lost == 0:
            bal_str = f"+{win_rate:.1f}%"
        else:
            net_bal = win_rate - loss_rate
            sign = "+" if net_bal > 0 else ""
            bal_str = f"{sign}{net_bal:.1f}%"

        lines = [
            "📔 *DIARIO DE TRADING & HISTORIAL*",
            "Seguimiento automático único. `/ver TICKER` muestra la señal registrada antes de la lectura actual.",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"🎯 *Balance de Acierto*: `{bal_str}` ({win_rate:.1f}% Ganadas | {loss_rate:.1f}% en Stop)",
            f"📊 *Operaciones Totales*: `{total}` ({active} activas, {closed} cerradas)",
            f"🏆 *Ganadas (+)*: `{won}` (`{win_rate:.1f}%`, Retorno medio: `+{avg_win:.1f}%`)",
            f"🛑 *En Stop Loss (-)*: `{lost}` (`{loss_rate:.1f}%`, Pérdida media: `{avg_loss:.1f}%`)",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ]

        if not entries:
            lines.append("ℹ️ Aún no hay registros en el diario. Las oportunidades se guardarán automáticamente cada vez que un activo entre en Zona Áurea (61.8%) o alcance Confluencia ≥ 70.")
        elif f_mode == "WON":
            lines.append(f"🏆 *REGISTRO DE OPERACIONES GANADAS (TP) ({len(won_entries)}):*\n")
            if not won_entries:
                lines.append("Aún no hay operaciones cerradas en Take Profit.")
            for e in won_entries:
                tab = escape_md(e.get("tab", e.get("ticker", "")))
                ticker = e.get("ticker", "")
                entry_p = e.get("entry_price", 0)
                ret = e.get("final_return_pct", e.get("current_return_pct", 0.0))
                sig_date = e.get("signal_date", "").split()[0]
                cls_date = (e.get("closed_date") or "").split()[0]
                cls_info = f" ➔ Cierre: `{cls_date}`" if cls_date else ""
                reason = escape_md(e.get("exit_reason") or "Take Profit alcanzado con éxito")
                status = "🟢 TP2 Ganada" if e.get("status") == "TP2_ALCANZADO" else "🟢 Break-Even (+TP1)"
                lines.append(
                    f"• *{tab}* (`{ticker}`) — {status} (*+{ret:.1f}%*)\n"
                    f"  Entrada: `{_fmt_price(entry_p, e)}` ({sig_date}){cls_info}\n"
                    f"  📝 _{reason}_\n"
                )
        elif f_mode == "LOST":
            lines.append(f"🛑 *REGISTRO DE OPERACIONES EN STOP LOSS ({len(lost_entries)}):*\n")
            if not lost_entries:
                lines.append("No hay operaciones cerradas en Stop Loss.")
            for e in lost_entries:
                tab = escape_md(e.get("tab", e.get("ticker", "")))
                ticker = e.get("ticker", "")
                entry_p = e.get("entry_price", 0)
                stop_p = e.get("stop_loss", 0)
                ret = e.get("final_return_pct", e.get("current_return_pct", 0.0))
                sig_date = e.get("signal_date", "").split()[0]
                cls_date = (e.get("closed_date") or "").split()[0]
                cls_info = f" ➔ Cierre: `{cls_date}`" if cls_date else ""
                reason = escape_md(e.get("exit_reason") or f"Stop Loss alcanzado en {_fmt_price(stop_p, e)}")
                lines.append(
                    f"• *{tab}* (`{ticker}`) — 🔴 Stop Ejecutado (*{ret:.1f}%*)\n"
                    f"  Entrada: `{_fmt_price(entry_p, e)}` ({sig_date}){cls_info} | Stop: `{_fmt_price(stop_p, e)}`\n"
                    f"  📝 _{reason}_\n"
                )
        elif f_mode == "ACTIVE":
            lines.append(f"🟢 *DETALLE DE OPERACIONES EN SEGUIMIENTO ({len(active_entries)}):*\n")
            if not active_entries:
                lines.append("No hay operaciones activas en este momento.")
            for e in active_entries:
                tab = escape_md(e.get("tab", e.get("ticker", "")))
                ticker = e.get("ticker", "")
                entry_p = e.get("entry_price", 0)
                curr_p = e.get("current_price", entry_p)
                stop_p = e.get("stop_loss", 0)
                ret = e.get("current_return_pct", 0.0)
                sig_date = e.get("signal_date", "").split()[0]
                sign = "+" if ret >= 0 else ""
                status_txt = "🟡 TP1 (Stop en BE)" if e.get("status") == "TP1_ALCANZADO" else "🔵 En Seguimiento"
                advice = f"\n  💡 _{escape_md(e.get('advice'))}_" if e.get("advice") else ""
                lines.append(
                    f"• *{tab}* (`{ticker}`) — {status_txt}\n"
                    f"  Entrada: `{_fmt_price(entry_p, e)}` ({sig_date}) | Actual: `{_fmt_price(curr_p, e)}` (P&L: *{sign}{ret:.1f}%*)\n"
                    f"  Stop: `{_fmt_price(stop_p, e)}` | TP1: `{_fmt_price(e.get('tp1'), e)}`{advice}\n"
                )
        else:
            if active_entries:
                lines.append(f"🟢 *En Seguimiento Activo ({len(active_entries)}):*")
                for e in active_entries[:4]:
                    tab = escape_md(e.get("tab", e.get("ticker", "")))
                    ret = e.get("current_return_pct", 0.0)
                    sign = "+" if ret >= 0 else ""
                    lines.append(f"• *{tab}*: Entrada `{_fmt_price(e.get('entry_price'), e)}` | P&L: *{sign}{ret:.1f}%* | Stop: `{_fmt_price(e.get('stop_loss'), e)}`")
                if len(active_entries) > 4:
                    lines.append(f"  _...y {len(active_entries) - 4} más (pulsa '🟢 Activas' para verlas todas)_")
                lines.append("")

            if won_entries:
                lines.append(f"🏆 *Ganadas en Take Profit ({len(won_entries)}):*")
                for e in won_entries[:3]:
                    tab = escape_md(e.get("tab", e.get("ticker", "")))
                    ret = e.get("final_return_pct", 0.0)
                    reason = escape_md(e.get("exit_reason") or "TP alcanzado")
                    lines.append(f"• *{tab}*: *+{ret:.1f}%* — _{reason}_")
                if len(won_entries) > 3:
                    lines.append(f"  _...y {len(won_entries) - 3} más (pulsa '🏆 Ganadas' abajo)_")
                lines.append("")

            if lost_entries:
                lines.append(f"🛑 *En Stop Loss ({len(lost_entries)}):*")
                for e in lost_entries[:3]:
                    tab = escape_md(e.get("tab", e.get("ticker", "")))
                    ret = e.get("final_return_pct", 0.0)
                    reason = escape_md(e.get("exit_reason") or "Stop alcanzado")
                    lines.append(f"• *{tab}*: *{ret:.1f}%* — _{reason}_")
                if len(lost_entries) > 3:
                    lines.append(f"  _...y {len(lost_entries) - 3} más (pulsa '🛑 En Stop' abajo)_")
                lines.append("")

        lines.append("💡 _Visualiza el gráfico y estadísticas completas abriendo http://localhost:5050 en tu navegador._")
        msg = "\n".join(lines)

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": f"🟢 Activas ({len(active_entries)})", "callback_data": "hist:ACTIVE"},
                    {"text": f"🏆 TP Ganadas ({len(won_entries)})", "callback_data": "hist:WON"},
                    {"text": f"🛑 En Stop ({len(lost_entries)})", "callback_data": "hist:LOST"}
                ],
                [
                    {"text": "📋 Ver Todo el Historial", "callback_data": "hist:ALL"}
                ]
            ]
        }
        send_telegram_message(bot_token, chat_id, msg, reply_markup=keyboard)
    except Exception as e:
        send_telegram_message(bot_token, chat_id, f"❌ Error al consultar historial: {escape_md(e)}", reply_markup=TELEGRAM_MAIN_KEYBOARD)


def handle_sync(bot_token, chat_id):
    """
    Fuerza la ejecución de la sincronización de precios y Google Sheets desde Telegram.
    """
    import market_updater
    if market_updater.SYNC_LOCK.locked():
        send_telegram_message(
            bot_token, chat_id,
            "⏳ Ya hay una sincronización en progreso en este momento. Por favor espera unos segundos...",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    def run_sync_task():
        try:
            send_telegram_message(
                bot_token, chat_id,
                "⏳ *Sincronizando mercado...*\nDescargando precios frescos de Yahoo Finance y actualizando Google Sheets..."
            )
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
                f"❌ Error durante la sincronización: {escape_md(e)}",
                reply_markup=TELEGRAM_MAIN_KEYBOARD
            )

    threading.Thread(target=run_sync_task, daemon=True).start()

def handle_periodo(bot_token, chat_id, arg):
    """
    Permite cambiar la temporalidad (1mo, 3mo, 6mo, 1y) al instante desde caché Multi-Timeframe (0ms).
    """
    valid = ["1mo", "3mo", "6mo", "1y"]
    period = arg.strip().lower()
    if period not in valid:
        send_telegram_message(
            bot_token, chat_id,
            f"⚠️ Periodo no reconocido: `{escape_md(arg)}`.\nOpciones válidas: `1mo`, `3mo`, `6mo`, `1y`.\nEjemplo: `/periodo 1mo`",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    try:
        import market_updater
        cached_payload = market_updater.switch_cached_period(period)
        if cached_payload is not None:
            send_telegram_message(
                bot_token, chat_id,
                f"⚡ *Temporalidad cambiada al instante a {period.upper()}* _(0 ms desde caché Multi-Timeframe)_.\n"
                "Pulsa *📊 Resumen* o *🎯 Alertas* para ver los niveles actualizados.",
                reply_markup=TELEGRAM_MAIN_KEYBOARD
            )
            return

        cfg = market_updater.load_config()
        cfg["period"] = period
        market_updater.save_config(cfg)
        send_telegram_message(
            bot_token, chat_id,
            f"⏱ *Temporalidad cambiada a {period.upper()}*.\nIniciando recálculo de Fibonacci..."
        )
        handle_sync(bot_token, chat_id)
    except Exception as e:
        send_telegram_message(bot_token, chat_id, f"❌ Error al cambiar periodo: {escape_md(e)}", reply_markup=TELEGRAM_MAIN_KEYBOARD)


def handle_cartera(bot_token, chat_id):
    """
    Muestra el resumen en vivo de 'Mi Cartera Real', PnL abierto y diagnósticos de Stop Loss / Take Profit.
    """
    try:
        import portfolio_manager
        pf = portfolio_manager.get_enriched_portfolio()
        summary = pf.get("summary", {})
        positions = pf.get("positions", [])

        if not positions:
            msg = (
                "💼 *MI CARTERA REAL*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "ℹ️ Aún no tienes posiciones registradas en tu cartera real.\n\n"
                "💡 _Abre la pestaña *💼 Mi Cartera Real* en tu panel web (http://localhost:5050) para registrar tus compras y monitorizar su PnL, Stop Loss y Take Profit en vivo._"
            )
            send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)
            return

        lines = [
            f"💼 *MI CARTERA REAL ({summary.get('positions_count', 0)} posiciones)*",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ]

        totals_by_curr = summary.get("totals_by_currency", {})
        if summary.get("valuation_incomplete"):
            lines.append("⚠️ Valoración provisional. Totales solo de posiciones con precio; pueden incluir cotizaciones desactualizadas.")
        for c_sym, b in totals_by_curr.items():
            if not b.get("positions"):
                continue
            pnl_abs = b.get("pnl_abs", 0.0)
            pnl_pct = b.get("pnl_pct", 0.0)
            sign = "+" if pnl_abs >= 0 else ""
            icon = "🟢" if pnl_abs >= 0 else "🔴"
            lines.append(
                f"{icon} *Balance ({c_sym})*: `{c_sym}{b.get('market_val', 0):,.2f}` "
                f"(_Inv: {c_sym}{b.get('invested', 0):,.2f}_ | PnL: *{sign}{c_sym}{pnl_abs:,.2f}* / *{sign}{pnl_pct:.2f}%*)"
            )

        realized_map = summary.get("realized_by_currency", {})
        if realized_map:
            real_parts = [f"{'+' if v >= 0 else ''}{k}{v:,.2f}" for k, v in realized_map.items()]
            lines.append(f"🏦 *PnL Realizado (Histórico)*: `{', '.join(real_parts)}`")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")

        for p in positions:
            if p.get("has_quote") is False:
                lines.append(f"• *{escape_md(p.get('ticker', ''))}* — ⚠️ Sin cotización. PnL no disponible; excluida de los totales.")
                continue
            t = p.get("ticker", "")
            tab = escape_md(p.get("tab", t))
            c = p.get("currency", "$")
            shares = p.get("shares", 0)
            avg_p = p.get("avg_price", 0)
            curr_p = p.get("current_price", avg_p)
            pnl_abs = p.get("pnl_abs", 0)
            pnl_pct = p.get("pnl_pct", 0)
            sl = p.get("effective_sl", 0)
            tp = p.get("effective_tp", 0)
            badge = escape_md(p.get("status_badge", ""))
            if p.get("is_stale"):
                badge += f" (último dato: {escape_md(p.get('last_success_at') or 'fecha desconocida')})"
            sign = "+" if pnl_abs >= 0 else ""
            shares_str = f"{int(shares)}" if abs(shares - round(shares)) < 1e-6 else _format_fractional_units(shares)

            lines.append(
                f"• *{tab}* (`{t}`) — {badge}\n"
                f"  Títulos: `{shares_str}` @ `{_fmt_price(avg_p, p)}` → Actual: `{_fmt_price(curr_p, p)}`\n"
                f"  PnL: *{sign}{c}{pnl_abs:,.2f} ({sign}{pnl_pct:.2f}%)* | SL: `{_fmt_price(sl, p)}` | TP: `{_fmt_price(tp, p)}`"
            )

        msg = "\n".join(lines)
        send_telegram_message(bot_token, chat_id, msg, reply_markup=TELEGRAM_MAIN_KEYBOARD)
    except Exception as e:
        send_telegram_message(bot_token, chat_id, f"❌ Error al consultar cartera: {escape_md(e)}", reply_markup=TELEGRAM_MAIN_KEYBOARD)


def handle_add_asset(bot_token, chat_id, raw_args):
    """
    Añade un nuevo activo a config.json desde Telegram tras validarlo en Yahoo Finance.
    Sintaxis: /add <TICKER> [NombreCorto]
    """
    parts = raw_args.strip().split(maxsplit=1)
    if not parts:
        send_telegram_message(
            bot_token, chat_id,
            "➕ *AÑADIR ACTIVO A SEGUIMIENTO*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📌 *Uso:* `/add <TICKER> [Nombre]`\n"
            "• Ejemplo EEUU: `/add AAPL Apple`\n"
            "• Ejemplo España: `/add SAN.MC Santander`\n"
            "• Ejemplo Cripto: `/add ETH-USD Ethereum`",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    ticker = parts[0].strip().upper().replace("$", "")
    custom_tab = parts[1].strip() if len(parts) > 1 else ""

    def _worker():
        try:
            import market_updater
            import yfinance as yf

            cfg = market_updater.load_config()
            assets = cfg.get("assets", [])
            if any(a.get("ticker", "").upper() == ticker for a in assets):
                send_telegram_message(
                    bot_token, chat_id,
                    f"ℹ️ El activo `{escape_md(ticker)}` ya está en tu lista de seguimiento.",
                    reply_markup=TELEGRAM_MAIN_KEYBOARD
                )
                return

            send_telegram_message(bot_token, chat_id, f"🔎 Validando `{escape_md(ticker)}` en Yahoo Finance...")
            yt = yf.Ticker(ticker)
            hist = yt.history(period="5d")
            if hist.empty:
                send_telegram_message(
                    bot_token, chat_id,
                    f"❌ No se encontraron cotizaciones para `{escape_md(ticker)}` en Yahoo Finance.",
                    reply_markup=TELEGRAM_MAIN_KEYBOARD
                )
                return

            suggested_name = custom_tab or ticker
            try:
                info = yt.info
                suggested_name = info.get("shortName") or info.get("longName") or suggested_name
            except Exception:
                pass

            tab_name = custom_tab or (suggested_name.split()[0][:12] if suggested_name else ticker)
            with market_updater.SYNC_LOCK:
                cfg = market_updater.load_config()
                assets = cfg.get("assets", [])
                if not any(a.get("ticker", "").upper() == ticker for a in assets):
                    assets.append({"tab": tab_name, "ticker": ticker, "name": suggested_name})
                    cfg["assets"] = assets
                    market_updater.save_config(cfg)

            payload = market_updater.run_updater(target_period=cfg.get("period", "3mo"))
            added_item = next((it for it in payload.get("data", []) if it.get("ticker", "").upper() == ticker), None)
            if added_item:
                msg = (
                    f"✅ *¡ACTIVO AÑADIDO: {escape_md(tab_name)} ({escape_md(ticker)})!*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• Nombre: `{escape_md(suggested_name)}`\n"
                    f"• Precio Actual: `{_fmt_price(added_item.get('current_price', 0), added_item)}`\n"
                    f"• Score Confluencia: *{added_item.get('score', 0)}/100*\n"
                    f"• Estado: `{escape_md(added_item.get('signal', ''))}`"
                )
                send_telegram_message(
                    bot_token, chat_id, msg,
                    reply_markup=build_ticker_inline_keyboard(ticker, payload.get("period", "3mo"))
                )
            else:
                send_telegram_message(bot_token, chat_id, f"✅ `{escape_md(ticker)}` añadido a la lista.", reply_markup=TELEGRAM_MAIN_KEYBOARD)
        except Exception as e:
            send_telegram_message(bot_token, chat_id, f"❌ Error añadiendo activo: {escape_md(e)}", reply_markup=TELEGRAM_MAIN_KEYBOARD)

    threading.Thread(target=_worker, daemon=True).start()


def handle_del_asset(bot_token, chat_id, raw_args):
    """
    Elimina un activo de config.json y latest_data.json desde Telegram.
    Sintaxis: /del <TICKER>
    """
    ticker = raw_args.strip().upper().replace("$", "")
    if not ticker:
        send_telegram_message(
            bot_token, chat_id,
            "🗑️ *ELIMINAR ACTIVO*\nUso: `/del <TICKER>` (ej: `/del AAPL`).",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    try:
        import market_updater
        with market_updater.SYNC_LOCK:
            cfg = market_updater.load_config()
            assets = cfg.get("assets", [])
            remaining = [a for a in assets if a.get("ticker", "").upper() != ticker and a.get("tab", "").upper() != ticker]
            if len(remaining) == len(assets):
                send_telegram_message(
                    bot_token, chat_id,
                    f"⚠️ No se encontró `{escape_md(ticker)}` en tu lista de seguimiento.",
                    reply_markup=TELEGRAM_MAIN_KEYBOARD
                )
                return

            removed_asset = next(a for a in assets if a not in remaining)
            removed_ticker = removed_asset.get("ticker", ticker).upper()
            cfg["assets"] = remaining
            market_updater.save_config(cfg)

            if os.path.exists(LATEST_DATA_PATH):
                try:
                    with open(LATEST_DATA_PATH, "r", encoding="utf-8") as f:
                        ldata = json.load(f)
                    ldata["data"] = [it for it in ldata.get("data", []) if it.get("ticker", "").upper() != removed_ticker]
                    ldata["market_hours"] = market_updater.evaluate_market_hours(remaining)
                    market_updater._atomic_write_json(LATEST_DATA_PATH, ldata)
                except Exception:
                    pass

        send_telegram_message(
            bot_token, chat_id,
            f"🗑️ Activo *{escape_md(removed_asset.get('tab', removed_ticker))}* (`{escape_md(removed_ticker)}`) eliminado de tu seguimiento.",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
    except Exception as e:
        send_telegram_message(bot_token, chat_id, f"❌ Error eliminando activo: {escape_md(e)}", reply_markup=TELEGRAM_MAIN_KEYBOARD)


def process_callback_query(bot_token, chat_id, callback_id, data_str):
    """
    Procesa pulsaciones en botones Inline:
    - compra:TICKER (Consejo de Compra sintetizado)
    - venta:TICKER (Consejo de Venta sintetizado)
    - fib:TICKER[:PERIOD] (Escalera detallada de Fibonacci)
    - tf:TICKER:PERIOD (Cambio instantáneo de temporalidad 0ms)
    - ver:TICKER (Ficha técnica sintetizada)
    - riesgo:TICKER:BUDGET (Cálculo de lote)
    - cartera (Resumen en vivo de Mi Cartera)
    """
    raw = str(data_str or "").strip()
    parts = raw.split(":")
    action = parts[0].lower() if parts else ""

    if action in ("planfollow", "planver", "plancancel", "planconfirm") and len(parts) == 2:
        answer_callback_query(bot_token, callback_id, "El seguimiento ahora está integrado en el Diario.")
        send_telegram_message(bot_token, chat_id, "El seguimiento es automático en el Diario. Usa `/ver AMD` para revisar la señal de un activo o /historial para ver sus resultados. Los botones de planes anteriores ya no crean ni cancelan seguimientos.")
    elif action == "compra" and len(parts) >= 2:
        t = parts[1]
        answer_callback_query(bot_token, callback_id, f"🟢 Consejo Compra {t}")
        handle_compra(bot_token, chat_id, t)
    elif action == "venta" and len(parts) >= 2:
        t = parts[1]
        answer_callback_query(bot_token, callback_id, f"🔴 Consejo Venta {t}")
        handle_venta(bot_token, chat_id, t)
    elif action == "fib" and len(parts) >= 2:
        t = parts[1]
        per = parts[2].lower() if len(parts) >= 3 else None
        tf_tag = f" ({per.upper()})" if per else ""
        answer_callback_query(bot_token, callback_id, f"📐 Fibonacci {t}{tf_tag}")
        handle_fibonacci_detail(bot_token, chat_id, t, forced_period=per)
    elif action == "ver" and len(parts) >= 2:
        t = parts[1]
        answer_callback_query(bot_token, callback_id, f"Ficha {t}")
        handle_ver_ticker(bot_token, chat_id, t)
    elif action == "tf" and len(parts) >= 3:
        t, per = parts[1], parts[2].lower()
        answer_callback_query(bot_token, callback_id, f"⚡ {t} en ventana {per.upper()}")
        handle_fibonacci_detail(bot_token, chat_id, t, forced_period=per)
    elif action == "riesgo" and len(parts) >= 3:
        t, bud = parts[1], parts[2]
        answer_callback_query(bot_token, callback_id, f"🛡️ Lote ({bud}) para {t}...")
        handle_riesgo(bot_token, chat_id, f"{t} {bud}")
    elif action == "cartera":
        answer_callback_query(bot_token, callback_id, "💼 Mi Cartera")
        handle_cartera(bot_token, chat_id)
    elif action == "hist":
        mode = parts[1].upper() if len(parts) >= 2 else "ALL"
        answer_callback_query(bot_token, callback_id, f"Diario ({mode})")
        handle_historial(bot_token, chat_id, filter_mode=mode)
    else:
        answer_callback_query(bot_token, callback_id, "Acción recibida")

def handle_liquidez(bot_token, chat_id):
    """
    Radar de Liquidez Institucional:
    Muestra Muro POC (Volume Profile), RVOL / Absorción de Ballenas y Piscinas / Barridos de Stops (SMC).
    """
    if not os.path.exists(LATEST_DATA_PATH):
        send_telegram_message(
            bot_token, chat_id,
            "⚠️ Aún no hay datos disponibles. Pulsa *🔄 Sincronizar* primero.",
            reply_markup=TELEGRAM_MAIN_KEYBOARD
        )
        return

    try:
        with open(LATEST_DATA_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)

        items = list(payload.get("data", []))
        period = payload.get("period", "3mo").upper()
        items.sort(key=lambda x: (x.get("liquidity") or {}).get("liquidity_score", 0), reverse=True)

        lines = [
            f"🏦 *RADAR DE LIQUIDEZ INSTITUCIONAL ({period})*",
            "_Muro POC (Vol. Profile) • RVOL Ballenas • Piscinas SSL_",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ]

        for it in items:
            ticker = it.get("ticker", "")
            tab = escape_md(it.get("tab", ticker))
            price = it.get("current_price", 0)
            liq = it.get("liquidity") or {}
            l_score = liq.get("liquidity_score", 0)
            poc_p = liq.get("poc_price", price)
            poc_dist = liq.get("poc_dist_pct", 0.0)
            poc_sign = "+" if poc_dist >= 0 else ""
            rvol_lbl = escape_md(liq.get("rvol_label", "Normal"))
            ssl_p = liq.get("ssl_pool_price", it.get("min", price))
            verdict = escape_md(liq.get("liquidity_verdict", "Flujo Normal"))

            if liq.get("has_sweep"):
                icon = "🧲"
            elif liq.get("has_absorption"):
                icon = "🐋"
            elif abs(poc_dist) <= 2.2 or liq.get("fib_poc_confluence", {}).get("has_confluence"):
                icon = "🏦"
            else:
                icon = "💧"

            lines.append(
                f"{icon} *{tab}* (`{ticker}`) — Liq: *{l_score}/100*\n"
                f"• Precio: `{_fmt_price(price, it)}` | POC: `{_fmt_price(poc_p, it)}` ({poc_sign}{poc_dist:.1f}%)\n"
                f"• RVOL: `{rvol_lbl}` | Stops SSL: `{_fmt_price(ssl_p, it)}`\n"
                f"• _{verdict}_\n"
            )

        lines.append("💡 _Escribe `/ver TICKER` para ver la liquidez exacta de cada escalón Fibonacci._")
        send_telegram_message(bot_token, chat_id, "\n".join(lines), reply_markup=TELEGRAM_MAIN_KEYBOARD)
    except Exception as e:
        send_telegram_message(bot_token, chat_id, f"❌ Error al consultar liquidez: {escape_md(e)}", reply_markup=TELEGRAM_MAIN_KEYBOARD)


def process_user_telegram_command(bot_token, chat_id, raw_text):
    """
    Enrutador principal de comandos y mensajes recibidos del usuario.
    """
    text = raw_text.strip()
    # Acepta /comando@NombreDelBot y compara nombres completos.
    parts = text.split(maxsplit=1)
    if parts and parts[0].startswith("/"):
        text = parts[0].split("@", 1)[0] + (" " + parts[1] if len(parts) > 1 else "")
    cmd = text.lower()
    command = cmd.split(maxsplit=1)[0] if cmd else ""

    if command in ("/planes", "/plan"):
        query = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
        if query:
            handle_ver_ticker(bot_token, chat_id, query)
        else:
            handle_historial(bot_token, chat_id)
        return

    if cmd in ("/start", "/help", "/ayuda", "ℹ️ ayuda", "ayuda"):
        handle_start_or_help(bot_token, chat_id)
        return

    if cmd in ("/herramientas", "🧰 herramientas", "herramientas"):
        handle_herramientas(bot_token, chat_id)
        return

    if cmd in ("/resumen", "/precios", "📊 resumen", "resumen", "precios"):
        handle_resumen(bot_token, chat_id)
        return

    if cmd in ("/alertas", "/oportunidades", "🎯 alertas", "alertas", "oportunidades"):
        handle_alertas(bot_token, chat_id)
        return

    if cmd in ("/liquidez", "/poc", "/ballenas", "/smc", "🏦 liquidez", "liquidez", "poc"):
        handle_liquidez(bot_token, chat_id)
        return

    if cmd in ("/sync", "/actualizar", "🔄 sincronizar", "sincronizar", "sync"):
        handle_sync(bot_token, chat_id)
        return

    if command in ("/compra", "/comprar") or cmd == "🟢 compra":
        parts = text.split(maxsplit=1)
        query = parts[1] if command.startswith("/") and len(parts) > 1 else ""
        handle_compra(bot_token, chat_id, query)
        return

    if command in ("/venta", "/salidas", "/vender") or cmd in ("🔴 venta", "🔴 modo venta"):
        parts = text.split(maxsplit=1)
        query = parts[1] if command.startswith("/") and len(parts) > 1 else ""
        handle_venta(bot_token, chat_id, query)
        return

    if command in ("/fibo", "/fibonacci") or cmd == "📐 fibo":
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            handle_fibonacci_detail(bot_token, chat_id, parts[1])
        else:
            send_telegram_message(bot_token, chat_id, "Indica el ticker que deseas ver. Ej: `/fibo AMD` o `/fibo NVDA`.")
        return

    if command == "/periodo":
        parts = text.split()
        if len(parts) > 1:
            handle_periodo(bot_token, chat_id, parts[1])
        else:
            send_telegram_message(
                bot_token, chat_id,
                "Indica el periodo deseado: `/periodo 1mo`, `/periodo 3mo`, `/periodo 6mo`, `/periodo 1y`."
            )
        return

    if command in ("/ver", "/analizar"):
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            handle_ver_ticker(bot_token, chat_id, parts[1])
        else:
            send_telegram_message(bot_token, chat_id, "Escribe `/ver AMD` o directamente el ticker para analizar un activo.")
        return

    if command in ("/riesgo", "/risk") or cmd == "🛡️ riesgo":
        parts = text.split(maxsplit=1)
        raw_args = parts[1] if len(parts) > 1 else ""
        handle_riesgo(bot_token, chat_id, raw_args)
        return

    if cmd in ("/cartera", "/portfolio", "💼 mi cartera", "💼 cartera", "mi cartera", "cartera"):
        handle_cartera(bot_token, chat_id)
        return

    if command in ("/add", "/añadir"):
        parts = text.split(maxsplit=1)
        handle_add_asset(bot_token, chat_id, parts[1] if len(parts) > 1 else "")
        return

    if command in ("/del", "/borrar", "/eliminar", "/rm"):
        parts = text.split(maxsplit=1)
        handle_del_asset(bot_token, chat_id, parts[1] if len(parts) > 1 else "")
        return

    if command in ("/historial", "/diario", "/journal", "/stats", "/seguimiento", "/seguimientos") or cmd in ("📔 historial", "historial", "diario", "seguimiento", "seguimientos"):
        arg = text.split(maxsplit=1)[1].strip().lower() if len(text.split(maxsplit=1)) > 1 else ""
        if arg in ("tp", "ganadas", "won", "ganada"):
            handle_historial(bot_token, chat_id, filter_mode="WON")
        elif arg in ("sl", "stop", "stops", "perdidas", "lost", "perdida"):
            handle_historial(bot_token, chat_id, filter_mode="LOST")
        elif arg in ("activas", "activa", "open", "active"):
            handle_historial(bot_token, chat_id, filter_mode="ACTIVE")
        elif arg in ("cerradas", "closed"):
            handle_historial(bot_token, chat_id, filter_mode="CLOSED")
        else:
            handle_historial(bot_token, chat_id, filter_mode="ALL")
        return

    if cmd in ("/ganadas", "/tp"):
        handle_historial(bot_token, chat_id, filter_mode="WON")
        return

    if cmd in ("/stops", "/sl", "/perdidas"):
        handle_historial(bot_token, chat_id, filter_mode="LOST")
        return

    if cmd in ("/activas", "/abiertas"):
        handle_historial(bot_token, chat_id, filter_mode="ACTIVE")
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
    safe_cmd = text.replace("`", "'")
    msg = (
        f"🤔 No he reconocido el comando: `{safe_cmd}`\n\n"
        "• `/ver AMD` — Analizar un activo.\n"
        "• /resumen — Todos los precios.\n"
        "• /alertas — Oportunidades filtradas.\n"
        "• /herramientas — Opciones especializadas.\n"
        "• /ayuda — Guía rápida."
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

                # 1. Gestionar pulsaciones en botones Inline (callback_query)
                cb = u.get("callback_query")
                if cb:
                    cb_id = cb.get("id")
                    cb_msg = cb.get("message") or {}
                    cb_chat_id = str(cb_msg.get("chat", {}).get("id", "")).strip()
                    cb_data = cb.get("data", "")
                    if cb_chat_id not in cached_chat_ids:
                        answer_callback_query(cached_token, cb_id, "⛔ Acceso denegado")
                        continue
                    print(f"[Telegram Bot] 🔘 Botón Inline pulsado en chat {cb_chat_id}: '{cb_data}'")
                    process_callback_query(cached_token, cb_chat_id, cb_id, cb_data)
                    continue

                # 2. Gestionar mensajes de texto normales
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
