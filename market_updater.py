import json
import os
import sys
import datetime
import requests
import pandas as pd
import yfinance as yf

# Asegurar codificación UTF-8 en consolas Windows
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
SECRETS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secrets.json")
LATEST_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "latest_data.json")

def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"No se encontró el archivo de configuración {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    # Fusionar credenciales privadas locales si existen (secrets.json ignorado en git)
    if os.path.exists(SECRETS_PATH):
        try:
            with open(SECRETS_PATH, "r", encoding="utf-8") as sf:
                secrets = json.load(sf)
                if "telegram" in secrets:
                    config.setdefault("telegram", {})
                    for k, v in secrets["telegram"].items():
                        if v:
                            config["telegram"][k] = v
                if "webhook_url" in secrets and secrets["webhook_url"]:
                    config["webhook_url"] = secrets["webhook_url"]
        except Exception as e:
            print(f"[Config] Error leyendo secrets.json: {e}")

    return config

def save_config(config):
    # Separar credenciales sensibles hacia secrets.json para que config.json nunca exponga secretos
    secrets_data = {}
    cfg_copy = json.loads(json.dumps(config))

    tg = cfg_copy.get("telegram", {})
    bot_token = tg.get("bot_token", "")
    chat_id = tg.get("chat_id", "")

    if bot_token or chat_id:
        secrets_data["telegram"] = {
            "bot_token": bot_token,
            "chat_id": chat_id
        }
        # Limpiar secretos de config.json para que sea seguro subirlo a git
        tg["bot_token"] = ""
        tg["chat_id"] = ""

    if secrets_data:
        try:
            with open(SECRETS_PATH, "w", encoding="utf-8") as sf:
                json.dump(secrets_data, sf, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Config] Error guardando secrets.json: {e}")

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg_copy, f, indent=2, ensure_ascii=False)

def compute_rsi(series, period=14):
    if len(series) < period + 1:
        return 50.0
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-9)
    rsi_series = 100 - (100 / (1 + rs))
    val = rsi_series.iloc[-1]
    return round(float(val), 1) if not series.empty and not pd.isna(val) else 50.0

def fetch_asset_data(asset, period="3mo"):
    tab = asset["tab"]
    ticker = asset["ticker"]
    name = asset.get("name", tab)

    print(f"  🔍 Consultando {name} ({ticker})...", end="\r")

    t = yf.Ticker(ticker)
    # Descargamos 1 año para tener SMA 200 y RSI robustos
    hist = t.history(period="1y")

    if hist.empty:
        hist = t.history(period="2y")

    if hist.empty:
        print(f"  ❌ No se pudieron obtener datos para {ticker}")
        return None

    current_price = float(hist["Close"].iloc[-1])

    # 1. Indicadores Técnicos Avanzados
    # RSI (14 días)
    rsi_14 = compute_rsi(hist["Close"], period=14)
    if rsi_14 < 30:
        rsi_desc = "Sobreventa Fuerte (<30)"
        rsi_zone = "OVERSOLD_STRONG"
    elif rsi_14 < 40:
        rsi_desc = "Zona Descuento (30-40)"
        rsi_zone = "OVERSOLD_MILD"
    elif rsi_14 <= 60:
        rsi_desc = "Neutral (40-60)"
        rsi_zone = "NEUTRAL"
    else:
        rsi_desc = "Sobrecompra (>60)"
        rsi_zone = "OVERBOUGHT"

    # SMA 200 (Media Móvil de 200 días)
    if len(hist) >= 200:
        sma_200 = float(hist["Close"].rolling(200).mean().iloc[-1])
    else:
        sma_200 = float(hist["Close"].mean())

    sma_dist_pct = round(((current_price - sma_200) / sma_200) * 100, 2)
    is_above_sma = current_price >= sma_200

    # 2. Ventana de Fibonacci según 'period' solicitado
    now = datetime.datetime.now(datetime.timezone.utc)
    if period == "1mo":
        start_date = now - datetime.timedelta(days=32)
    elif period == "3mo":
        start_date = now - datetime.timedelta(days=95)
    elif period == "6mo":
        start_date = now - datetime.timedelta(days=185)
    else:  # 1y o superior
        start_date = now - datetime.timedelta(days=366)

    if hist.index.tz is not None:
        fibo_hist = hist[hist.index >= start_date]
    else:
        fibo_hist = hist[hist.index >= start_date.replace(tzinfo=None)]

    if fibo_hist.empty:
        fibo_hist = hist

    hi = float(fibo_hist["High"].max())
    lo = float(fibo_hist["Low"].min())
    price_range = hi - lo

    # Niveles de retroceso de Fibonacci desde el Máximo hacia el Mínimo
    fib_levels = {
        "23.6%": round(hi - (price_range * 0.236), 2),
        "38.2%": round(hi - (price_range * 0.382), 2),
        "50.0%": round(hi - (price_range * 0.500), 2),
        "61.8%": round(hi - (price_range * 0.618), 2),
        "78.6%": round(hi - (price_range * 0.786), 2),
    }

    # Caída % desde el máximo
    drop_pct = round(((hi - current_price) / hi) * 100, 2) if hi > 0 else 0.0

    # Determinar zona de Fibonacci
    if current_price <= fib_levels["78.6%"]:
        zone_desc = "Zona > 78.6%"
        signal = "🟢 COMPRA FUERTE (78.6%)"
        status_code = "STRONG_BUY"
        fibo_pts = 40
    elif current_price <= fib_levels["61.8%"]:
        zone_desc = "Zona Áurea 61.8%"
        signal = "🟢 COMPRA ÓPTIMA (61.8%)"
        status_code = "BUY_GOLDEN"
        fibo_pts = 38
    elif current_price <= fib_levels["50.0%"]:
        zone_desc = "Zona Media 50.0%"
        signal = "🟢 ENTRADA BUENA (50.0%)"
        status_code = "BUY_50"
        fibo_pts = 30
    elif current_price <= fib_levels["38.2%"]:
        zone_desc = "Zona 38.2%"
        signal = "🟡 EN OBSERVACIÓN (38.2%)"
        status_code = "WATCH_38"
        fibo_pts = 18
    elif current_price <= fib_levels["23.6%"]:
        zone_desc = "Zona 23.6%"
        signal = "🟡 RETROCESO LEVE (23.6%)"
        status_code = "WATCH_23"
        fibo_pts = 8
    else:
        zone_desc = "En Máximos (< 23.6%)"
        signal = "⚪ RESISTENCIA / CARO"
        status_code = "EXPENSIVE"
        fibo_pts = 0

    # 3. Puntuación Técnica Compuesta (Score 0 a 100)
    # Factor RSI (0 a 30)
    if rsi_14 <= 30:
        rsi_pts = 30
    elif rsi_14 <= 35:
        rsi_pts = 26
    elif rsi_14 <= 40:
        rsi_pts = 20
    elif rsi_14 <= 48:
        rsi_pts = 14
    elif rsi_14 <= 55:
        rsi_pts = 8
    elif rsi_14 <= 65:
        rsi_pts = 3
    else:
        rsi_pts = 0

    # Factor SMA 200 (0 a 20)
    if is_above_sma:
        sma_pts = 20  # Tendencia alcista estructural (setup de rebote ideal)
    elif sma_dist_pct >= -4.0:
        sma_pts = 12  # Cerca de la media
    else:
        sma_pts = 4   # Por debajo de la media

    # Factor Caída acumulada (0 a 10)
    if drop_pct >= 25.0:
        drop_pts = 10
    elif drop_pct >= 18.0:
        drop_pts = 8
    elif drop_pct >= 12.0:
        drop_pts = 5
    elif drop_pct >= 6.0:
        drop_pts = 3
    else:
        drop_pts = 1

    total_score = min(100, fibo_pts + rsi_pts + sma_pts + drop_pts)

    if total_score >= 80:
        confluence_rating = "🔥 CONFLUENCIA MÁXIMA"
        confluence_code = "MAX_CONFLUENCE"
    elif total_score >= 65:
        confluence_rating = "🟢 ALTA PROBABILIDAD"
        confluence_code = "HIGH_PROB"
    elif total_score >= 45:
        confluence_rating = "🟡 MODERADA / SEGUIMIENTO"
        confluence_code = "MODERATE"
    else:
        confluence_rating = "⚪ NEUTRAL / CARO"
        confluence_code = "LOW"

    return {
        "tab": tab,
        "ticker": ticker,
        "name": name,
        "current_price": round(current_price, 2),
        "min": round(lo, 2),
        "max": round(hi, 2),
        "range": round(price_range, 2),
        "drop_pct": drop_pct,
        "zone_desc": zone_desc,
        "signal": signal,
        "status_code": status_code,
        "fib_levels": fib_levels,
        # Nuevos campos de análisis técnico avanzado:
        "rsi": rsi_14,
        "rsi_desc": rsi_desc,
        "rsi_zone": rsi_zone,
        "sma_200": round(sma_200, 2),
        "sma_dist_pct": sma_dist_pct,
        "is_above_sma": is_above_sma,
        "score": total_score,
        "confluence_rating": confluence_rating,
        "confluence_code": confluence_code
    }

def print_summary_table(results, period, timestamp):
    print("\n" + "=" * 105)
    print(f"📊 REPORTE DE MERCADO, FIBONACCI & CONFLUENCIA TÉCNICA - {timestamp}")
    print(f"Ventana Fibonacci: {period} | Indicadores: Wilder's RSI(14) + SMA 200")
    print("=" * 105)
    print(f"{'Activo':<10} {'Ticker':<8} {'Precio':>10} {'Caída %':>9} {'RSI':>6} {'SMA 200':>10} {'Dist SMA':>9} {'Score':>7} {'Confluencia':<22}")
    print("-" * 105)

    for r in results:
        curr_str = f"${r['current_price']:,.2f}"
        drop_str = f"-{r['drop_pct']:.1f}%"
        rsi_str = f"{r.get('rsi', 0):.1f}"
        sma_str = f"${r.get('sma_200', 0):,.2f}"
        dist_str = f"{r.get('sma_dist_pct', 0):+.1f}%"
        score_str = f"{r.get('score', 0)}/100"
        print(f"{r['tab']:<10} {r['ticker']:<8} {curr_str:>10} {drop_str:>9} {rsi_str:>6} {sma_str:>10} {dist_str:>9} {score_str:>7} {r.get('confluence_rating', ''):<22}")

    print("=" * 105)

def run_updater(target_period=None, sync_sheets=True, custom_webhook=None):
    config = load_config()
    period = target_period or config.get("period", "3mo")
    webhook_url = custom_webhook or config.get("webhook_url", "").strip()

    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n🚀 Iniciando sincronización de precios de mercado (Periodo: {period})...")
    results = []

    for asset in config.get("assets", []):
        data = fetch_asset_data(asset, period=period)
        if data:
            results.append(data)

    # Imprimir reporte en consola
    print_summary_table(results, period, timestamp)

    # Guardar localmente
    payload = {
        "timestamp": timestamp,
        "period": period,
        "data": results
    }
    with open(LATEST_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    # Actualizar periodo en config.json si se especificó uno nuevo
    if target_period and target_period != config.get("period"):
        config["period"] = target_period
        save_config(config)

    # Enviar a Google Sheets si hay webhook configurado y sync_sheets es True
    if sync_sheets and webhook_url:
        print(f"\n📤 Enviando datos a Google Sheets ({webhook_url[:40]}...)...")
        try:
            resp = requests.post(
                webhook_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=25
            )
            if resp.status_code == 200:
                print("✅ ¡GOOGLE SHEETS ACTUALIZADO CON ÉXITO!")
            else:
                print(f"⚠️ Error al actualizar Sheet. Código HTTP: {resp.status_code}")
                print(f"Detalle: {resp.text}")
        except Exception as e:
            print(f"❌ Error de conexión al enviar a Google Sheets: {e}")
    elif not webhook_url:
        print("\nℹ️ [Nota]: No hay webhook configurado para Google Sheets.")

    # Enviar alertas a Telegram si está configurado
    try:
        import telegram_notifier
        telegram_notifier.dispatch_telegram_alerts(payload, config)
    except Exception as e:
        print(f"⚠️ [Telegram] Error procesando alertas: {e}")

    return payload

def main():
    custom_webhook = None
    target_period = None

    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.startswith("http"):
                custom_webhook = arg
                config = load_config()
                config["webhook_url"] = custom_webhook
                save_config(config)
            elif arg in ["1mo", "3mo", "6mo", "1y", "2y", "5y", "max"]:
                target_period = arg

    run_updater(target_period=target_period, custom_webhook=custom_webhook)

if __name__ == "__main__":
    main()
