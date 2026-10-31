import json
import os
import sys
import datetime
import requests
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
LATEST_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "latest_data.json")

def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"No se encontró el archivo de configuración {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def fetch_asset_data(asset, period="3mo"):
    tab = asset["tab"]
    ticker = asset["ticker"]
    name = asset.get("name", tab)

    print(f"  🔍 Consultando {name} ({ticker})...", end="\r")

    t = yf.Ticker(ticker)
    hist = t.history(period=period)

    if hist.empty:
        # Fallback si no hay datos en 3mo, probar 6mo
        hist = t.history(period="6mo")

    if hist.empty:
        print(f"  ❌ No se pudieron obtener datos para {ticker}")
        return None

    current_price = float(hist["Close"].iloc[-1])
    hi = float(hist["High"].max())
    lo = float(hist["Low"].min())
    price_range = hi - lo

    # Niveles de retroceso de Fibonacci desde el Máximo hacia el Mínimo
    # Precio Objetivo = Max - (Range * Nivel)
    fib_levels = {
        "23.6%": round(hi - (price_range * 0.236), 2),
        "38.2%": round(hi - (price_range * 0.382), 2),
        "50.0%": round(hi - (price_range * 0.500), 2),
        "61.8%": round(hi - (price_range * 0.618), 2),
        "78.6%": round(hi - (price_range * 0.786), 2),
    }

    # Caída % desde el máximo
    drop_pct = round(((hi - current_price) / hi) * 100, 2) if hi > 0 else 0.0

    # Determinar en qué zona de retroceso se encuentra el precio actual
    if current_price <= fib_levels["78.6%"]:
        zone_desc = "Zona > 78.6%"
        signal = "🟢 COMPRA FUERTE (78.6%)"
        status_code = "STRONG_BUY"
    elif current_price <= fib_levels["61.8%"]:
        zone_desc = "Zona Áurea 61.8%"
        signal = "🟢 COMPRA ÓPTIMA (61.8%)"
        status_code = "BUY_GOLDEN"
    elif current_price <= fib_levels["50.0%"]:
        zone_desc = "Zona Media 50.0%"
        signal = "🟢 ENTRADA BUENA (50.0%)"
        status_code = "BUY_50"
    elif current_price <= fib_levels["38.2%"]:
        zone_desc = "Zona 38.2%"
        signal = "🟡 EN OBSERVACIÓN (38.2%)"
        status_code = "WATCH_38"
    elif current_price <= fib_levels["23.6%"]:
        zone_desc = "Zona 23.6%"
        signal = "🟡 RETROCESO LEVE (23.6%)"
        status_code = "WATCH_23"
    else:
        zone_desc = "En Máximos (< 23.6%)"
        signal = "⚪ RESISTENCIA / CARO"
        status_code = "EXPENSIVE"

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
        "fib_levels": fib_levels
    }

def print_summary_table(results, period, timestamp):
    print("\n" + "=" * 90)
    print(f"📊 REPORTE DE MERCADO Y RETROCESOS FIBONACCI - {timestamp}")
    print(f"Ventana de cálculo automático: {period}")
    print("=" * 90)
    print(f"{'Activo':<10} {'Ticker':<8} {'Precio Actual':>14} {'Mínimo':>10} {'Máximo':>10} {'Caída %':>10} {'Señal / Estado':<24}")
    print("-" * 90)

    for r in results:
        curr_str = f"${r['current_price']:,.2f}"
        min_str = f"${r['min']:,.2f}"
        max_str = f"${r['max']:,.2f}"
        drop_str = f"-{r['drop_pct']:.1f}%"
        print(f"{r['tab']:<10} {r['ticker']:<8} {curr_str:>14} {min_str:>10} {max_str:>10} {drop_str:>10} {r['signal']:<24}")

    print("=" * 90)

def main():
    config = load_config()
    period = config.get("period", "3mo")
    webhook_url = config.get("webhook_url", "").strip()

    # Si se pasa URL por línea de comandos, guardarla
    if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
        webhook_url = sys.argv[1]
        config["webhook_url"] = webhook_url
        save_config(config)

    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    print("\n🚀 Iniciando sincronización de precios de mercado...")
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

    # Enviar a Google Sheets si hay webhook configurado
    if webhook_url:
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
                print(f"Respuesta del servidor: {resp.text}")
            else:
                print(f"⚠️ Error al actualizar Sheet. Código HTTP: {resp.status_code}")
                print(f"Detalle: {resp.text}")
        except Exception as e:
            print(f"❌ Error de conexión al enviar a Google Sheets: {e}")
    else:
        print("\nℹ️ [Nota]: Aún no has configurado la URL del Webhook de Google Sheets.")
        print("   Para activar la sincronización automática con tu Sheet, sigue los pasos de 'google_apps_script.js'")
        print("   y pega la URL en config.json o pásala como parámetro: python market_updater.py <URL>")

if __name__ == "__main__":
    main()
