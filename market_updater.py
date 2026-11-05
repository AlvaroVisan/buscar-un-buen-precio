import json
import math
import os
import sys
import time
import datetime
import threading
import concurrent.futures
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
EARNINGS_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".earnings_cache.json")

SUPPORTED_PERIODS = ("1mo", "3mo", "6mo", "1y")
PERIOD_SHORT_LABELS = {"1mo": "1M", "3mo": "3M", "6mo": "6M", "1y": "1A"}
EARNINGS_CACHE_TTL_SECONDS = 12 * 3600  # 12 horas

# Candado global compartido entre Web, Auto-Scheduler y Bot de Telegram para evitar condiciones de carrera
SYNC_LOCK = threading.Lock()
_EARNINGS_CACHE_LOCK = threading.Lock()


def _atomic_write_json(path, data):
    """Escribe un archivo JSON de forma atómica para evitar lecturas corruptas en concurrencia."""
    temp_path = f"{path}.{threading.get_ident()}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise


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
                if "telegram" in secrets and isinstance(secrets["telegram"], dict):
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
    # Separar todas las credenciales sensibles (Telegram y Webhook) hacia secrets.json
    # para que config.json nunca exponga secretos en Git y permita limpiar valores vacíos.
    cfg_copy = json.loads(json.dumps(config))

    existing_secrets = {}
    if os.path.exists(SECRETS_PATH):
        try:
            with open(SECRETS_PATH, "r", encoding="utf-8") as sf:
                existing_secrets = json.load(sf) or {}
        except Exception:
            existing_secrets = {}

    tg = cfg_copy.setdefault("telegram", {})
    bot_token = str(tg.get("bot_token", "")).strip()
    chat_id = str(tg.get("chat_id", "")).strip()

    if "webhook_url" in cfg_copy:
        webhook_url = str(cfg_copy.get("webhook_url", "")).strip()
    else:
        webhook_url = str(existing_secrets.get("webhook_url", "")).strip()

    secrets_data = {
        "webhook_url": webhook_url,
        "telegram": {
            "bot_token": bot_token,
            "chat_id": chat_id
        }
    }

    # Limpiar secretos de config.json para que sea seguro subirlo a git
    cfg_copy["webhook_url"] = ""
    tg["bot_token"] = ""
    tg["chat_id"] = ""

    try:
        _atomic_write_json(SECRETS_PATH, secrets_data)
    except Exception as e:
        print(f"[Config] Error guardando secrets.json: {e}")

    _atomic_write_json(CONFIG_PATH, cfg_copy)

def translate_sentiment_rating(raw_rating):
    r_map = {
        "extreme fear": "Miedo Extremo",
        "fear": "Miedo",
        "neutral": "Neutral",
        "greed": "Codicia",
        "extreme greed": "Codicia Extrema"
    }
    return r_map.get(str(raw_rating).lower().strip(), str(raw_rating).capitalize())

def fetch_cnn_fear_and_greed():
    """
    Consulta el índice oficial CNN Fear & Greed de Wall Street.
    Devuelve score (0-100), estado, comparativas históricas y los 7 factores cuantificados.
    """
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            fg = data.get("fear_and_greed", {})
            score = float(fg.get("score", 50.0))
            raw_rating = str(fg.get("rating", "neutral")).strip().lower()

            # Mapeo interpretativo y en español
            if score <= 24:
                rating_code = "EXTREME_FEAR"
                rating_es = "Miedo Extremo"
                icon = "😱"
                advice = "Momento histórico de compra en rebajas (Buffett: 'Sé codicioso cuando los demás tienen miedo'). Alta confluencia con niveles 61.8% y 78.6%."
            elif score <= 44:
                rating_code = "FEAR"
                rating_es = "Miedo"
                icon = "😨"
                advice = "Sentimiento pesimista / Descuento general. Clima favorable para buscar entradas en retrocesos sólidos."
            elif score <= 55:
                rating_code = "NEUTRAL"
                rating_es = "Neutral"
                icon = "😐"
                advice = "Equilibrio entre compradores y vendedores. Priorizar la tendencia técnica individual de cada activo."
            elif score <= 75:
                rating_code = "GREED"
                rating_es = "Codicia"
                icon = "🤑"
                advice = "Mercado optimista. Ajustar Stop Loss y evitar perseguir precios cerca de máximos."
            else:
                rating_code = "EXTREME_GREED"
                rating_es = "Codicia Extrema"
                icon = "🔥"
                advice = "Euforia y sobrecalentamiento. Precaución con compras nuevas; momento óptimo para el Modo Venta y extensiones."

            # Desglose de los 7 pilares cuantitativos de Wall Street
            sub_indicators = {}
            factor_catalog = [
                ("market_momentum_sp500", "Momento S&P 500 (vs SMA 125)", "Mide si el S&P 500 cotiza por encima de su media de 125 días"),
                ("stock_price_strength", "Fuerza de Precios (Máx vs Mín 52 sem)", "Balance de acciones marcando máximos anuales frente a mínimos"),
                ("stock_price_breadth", "Amplitud de Mercado (Volumen NYSE)", "Volumen negociado en acciones que suben vs las que bajan"),
                ("put_call_options", "Opciones Put / Call (Cobertura)", "Demanda de opciones de venta defensivas vs opciones de compra"),
                ("market_volatility_vix", "Volatilidad VIX (vs SMA 50)", "Índice de volatilidad implícita y miedo en opciones del S&P 500"),
                ("safe_haven_demand", "Demanda Refugio (Bonos vs Acciones)", "Rendimiento relativo de bonos del Tesoro frente a renta variable"),
                ("junk_bond_demand", "Bonos Basura (Apetito de Riesgo)", "Diferencial de rendimiento entre deuda de alto riesgo e investment grade")
            ]

            for key, label, desc in factor_catalog:
                if key in data and isinstance(data[key], dict):
                    val = data[key].get("score")
                    raw_sub_rat = data[key].get("rating", "neutral")
                    if val is not None:
                        sub_indicators[key] = {
                            "label": label,
                            "description": desc,
                            "score": round(float(val), 1) if isinstance(val, (int, float)) else val,
                            "rating": str(raw_sub_rat).lower().strip(),
                            "rating_es": translate_sentiment_rating(raw_sub_rat)
                        }

            return {
                "score": round(score, 1),
                "rating": raw_rating,
                "rating_es": rating_es,
                "rating_code": rating_code,
                "icon": icon,
                "advice": advice,
                "previous_close": round(float(fg.get("previous_close", 0)), 1) if fg.get("previous_close") is not None else None,
                "previous_1_week": round(float(fg.get("previous_1_week", 0)), 1) if fg.get("previous_1_week") is not None else None,
                "previous_1_month": round(float(fg.get("previous_1_month", 0)), 1) if fg.get("previous_1_month") is not None else None,
                "previous_1_year": round(float(fg.get("previous_1_year", 0)), 1) if fg.get("previous_1_year") is not None else None,
                "timestamp": fg.get("timestamp"),
                "sub_indicators": sub_indicators,
                "status": "OK"
            }
    except Exception as e:
        print(f"[CNN Sentiment] ⚠️ Aviso consultando Fear & Greed: {e}")

    # Fallback si falla la red: intentar leer el último dato guardado
    if os.path.exists(LATEST_DATA_PATH):
        try:
            with open(LATEST_DATA_PATH, "r", encoding="utf-8") as f:
                old_payload = json.load(f)
                if "market_sentiment" in old_payload and old_payload["market_sentiment"]:
                    cached = old_payload["market_sentiment"]
                    cached["status"] = "CACHED"
                    return cached
        except Exception:
            pass

    return {
        "score": 50.0,
        "rating": "neutral",
        "rating_es": "Neutral (Estimado)",
        "rating_code": "NEUTRAL",
        "icon": "😐",
        "advice": "No se pudo conectar con el índice de sentimiento en este momento.",
        "previous_close": 50.0,
        "previous_1_week": 50.0,
        "timestamp": datetime.datetime.now().isoformat(),
        "sub_indicators": {},
        "status": "FALLBACK"
    }

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


def compute_atr(hist, period=14, decimals=2):
    """Calcula el Average True Range (ATR de Wilder de 14 sesiones) para medir volatilidad real."""
    if hist is None or hist.empty or len(hist) < 2:
        return 0.0, 0.0
    high = hist["High"]
    low = hist["Low"]
    prev_close = hist["Close"].shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    min_p = min(period, len(tr))
    atr_series = tr.ewm(alpha=1 / period, min_periods=min_p, adjust=False).mean()
    atr_val = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else 0.0
    last_close = float(hist["Close"].iloc[-1])
    atr_pct = round((atr_val / last_close) * 100, 2) if last_close > 0 else 0.0
    return round(atr_val, decimals), atr_pct


def is_crypto_ticker(ticker):
    t = str(ticker or "").upper().strip()
    return t.endswith("-USD") or t.endswith("-EUR") or t.endswith("-USDT")


def is_equity_ticker(ticker):
    """Determina si el símbolo corresponde a una acción corporativa con presentación de resultados (Earnings)."""
    t = str(ticker or "").upper().strip()
    if not t:
        return False
    if t.startswith("^") or t.endswith("=F") or t.endswith("=X") or is_crypto_ticker(t):
        return False
    return True


def evaluate_market_hours(assets=None, now_dt=None):
    """
    Evalúa si las bolsas tradicionales (Europa + Wall Street: L-V 08:45 a 22:30 hora local) están abiertas,
    y si la cartera contiene criptoactivos 24/7.
    """
    dt = now_dt or datetime.datetime.now()
    weekday = dt.weekday()  # 0=Lunes ... 6=Domingo
    hhmm = dt.hour * 60 + dt.minute
    open_min = 8 * 60 + 45   # 08:45
    close_min = 22 * 60 + 30  # 22:30

    equities_open = (weekday < 5) and (open_min <= hhmm <= close_min)
    asset_list = assets or []
    has_crypto = any(is_crypto_ticker(a.get("ticker", "")) for a in asset_list)
    has_equities = any(not is_crypto_ticker(a.get("ticker", "")) for a in asset_list) if asset_list else True

    if equities_open:
        label = "🟢 Bolsas Abiertas (Sesión EU / Wall St.)"
    elif weekday >= 5:
        label = "🌙 Fin de Semana (Bolsas Cerradas • Cripto 24/7)" if has_crypto else "🌙 Fin de Semana (Bolsas Cerradas)"
    else:
        label = "🌙 Fuera de Sesión Bursátil (08:45–22:30)"

    return {
        "equities_open": equities_open,
        "has_crypto": has_crypto,
        "has_equities": has_equities,
        "weekday": weekday,
        "status_label": label
    }


def _load_earnings_cache():
    if not os.path.exists(EARNINGS_CACHE_PATH):
        return {}
    try:
        with open(EARNINGS_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def fetch_earnings_info(ticker, yf_ticker_obj=None):
    """
    Obtiene la próxima fecha de presentación de resultados (Earnings) para acciones corporativas.
    Usa caché persistente de 12 horas en disco para velocidad instantánea (0ms) en sincronizaciones sucesivas.
    """
    t_sym = str(ticker or "").upper().strip()
    if not is_equity_ticker(t_sym):
        return {"has_earnings": False, "warning_level": "NONE"}

    now_ts = time.time()
    today = datetime.date.today()

    raw_date_str = None
    eps_avg = None

    with _EARNINGS_CACHE_LOCK:
        cache = _load_earnings_cache()
        cached_entry = cache.get(t_sym)
        if isinstance(cached_entry, dict) and (now_ts - cached_entry.get("fetched_at", 0)) < EARNINGS_CACHE_TTL_SECONDS:
            raw_date_str = cached_entry.get("next_date")
            eps_avg = cached_entry.get("eps_avg")
            cache_hit = True
        else:
            cache_hit = False

    if not cache_hit:
        try:
            yt = yf_ticker_obj or yf.Ticker(t_sym)
            cal = yt.calendar
            dates_raw = []
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if isinstance(ed, (list, tuple)):
                    dates_raw = list(ed)
                elif ed is not None:
                    dates_raw = [ed]
                eps_raw = cal.get("Earnings Average")
                if isinstance(eps_raw, (int, float)) and not pd.isna(eps_raw):
                    eps_avg = round(float(eps_raw), 2)
            elif hasattr(cal, "to_dict"):
                d_cal = cal.to_dict()
                if "Earnings Date" in d_cal:
                    vals = list(d_cal["Earnings Date"].values())
                    dates_raw = vals

            parsed_dates = []
            for d in dates_raw:
                if hasattr(d, "date") and callable(d.date):
                    parsed_dates.append(d.date())
                elif isinstance(d, datetime.date):
                    parsed_dates.append(d)
                elif isinstance(d, str) and len(d) >= 10:
                    try:
                        parsed_dates.append(datetime.date.fromisoformat(d[:10]))
                    except ValueError:
                        pass

            # Priorizar fechas futuras o del día actual
            upcoming = sorted([d for d in parsed_dates if (d - today).days >= -1])
            if upcoming:
                raw_date_str = upcoming[0].isoformat()
            elif parsed_dates:
                raw_date_str = sorted(parsed_dates)[-1].isoformat()
        except Exception:
            raw_date_str = None

        with _EARNINGS_CACHE_LOCK:
            cache = _load_earnings_cache()
            cache[t_sym] = {
                "fetched_at": now_ts,
                "next_date": raw_date_str,
                "eps_avg": eps_avg
            }
            try:
                _atomic_write_json(EARNINGS_CACHE_PATH, cache)
            except Exception:
                pass

    if not raw_date_str:
        return {"has_earnings": False, "warning_level": "NONE"}

    try:
        edate = datetime.date.fromisoformat(raw_date_str[:10])
    except ValueError:
        return {"has_earnings": False, "warning_level": "NONE"}

    days_until = (edate - today).days
    if days_until < 0:
        return {"has_earnings": False, "warning_level": "NONE"}

    months_es = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    short_date = f"{edate.day:02d} {months_es[edate.month - 1]}"

    if days_until == 0:
        warning_level = "IMMINENT"
        label = f"🚨 Resultados HOY ({short_date}) — Riesgo de Gap"
    elif days_until == 1:
        warning_level = "IMMINENT"
        label = f"⚠️ Resultados MAÑANA ({short_date}) — Riesgo de Gap"
    elif days_until <= 7:
        warning_level = "IMMINENT"
        label = f"⚠️ Resultados en {days_until} días ({short_date}) — Riesgo de Gap"
    elif days_until <= 21:
        warning_level = "UPCOMING"
        label = f"📅 Resultados en {days_until} días ({short_date})"
    else:
        warning_level = "DISTANT"
        label = f"📅 Resultados: {short_date} ({days_until}d)"

    return {
        "has_earnings": True,
        "next_date": raw_date_str[:10],
        "short_date": short_date,
        "days_until": days_until,
        "eps_avg": eps_avg,
        "warning_level": warning_level,
        "label": label
    }


def detect_asset_format(ticker, sample_price=100.0):
    """Detecta el símbolo de divisa y el número óptimo de decimales según el mercado y precio del activo."""
    t = str(ticker or "").upper().strip()
    eur_suffixes = (".MC", ".PA", ".DE", ".AS", ".MI", ".BR", ".LS", ".VI", ".HE", "-EUR")
    if t.endswith(eur_suffixes) or t in ("EUR=X",):
        currency = "€"
    elif t.endswith(".L"):
        currency = "£"
    else:
        currency = "$"

    if t.endswith("=X") or (0 < sample_price < 2.0):
        decimals = 4
    else:
        decimals = 2

    return currency, decimals


def compute_liquidity_metrics(fibo_hist, full_hist, fib_levels, current_price, currency, decimals):
    """
    Motor de Liquidez Institucional (3 Pilares):
    1. Volume Profile & POC (Point of Control), Área de Valor (70% VAL-VAH) y densidad de liquidez por nivel Fibonacci.
    2. RVOL (Volumen Relativo vs media 20 sesiones) y detector de Absorción Institucional (mecha inferior + volumen).
    3. Piscinas de Liquidez (Sell-Side Liquidity / Swing Lows / Equal Lows) y Barrido de Stops (Liquidity Sweep SMC).
    """
    num_bins = 24
    hi = float(fibo_hist["High"].max()) if not fibo_hist.empty else current_price
    lo = float(fibo_hist["Low"].min()) if not fibo_hist.empty else current_price
    price_range = hi - lo

    if fibo_hist.empty or len(fibo_hist) < 2 or price_range <= 1e-9:
        empty_fib_liq = {
            k: {"strength_pct": 50, "tier": "MEDIUM", "badge": "💧 Media", "is_poc": False}
            for k in fib_levels
        }
        return {
            "profile_type": "TPO",
            "has_real_volume": False,
            "poc_price": round(current_price, decimals),
            "poc_pct_pos": 50.0,
            "poc_dist_pct": 0.0,
            "val_price": round(lo, decimals),
            "vah_price": round(hi, decimals),
            "fib_liquidity": empty_fib_liq,
            "fib_poc_confluence": {
                "has_confluence": False,
                "level": None,
                "price": None,
                "strength_pct": 0,
                "is_poc": False,
                "label": ""
            },
            "rvol": 0.0,
            "peak_rvol_3d": 0.0,
            "rvol_status": "NO_VOL",
            "rvol_label": "N/D",
            "has_absorption": False,
            "absorption_label": "",
            "ssl_pool_price": round(lo, decimals),
            "ssl_dist_pct": 0.0,
            "ssl_type": "SWING_LOW",
            "ssl_type_label": "Suelo Periodo",
            "is_equal_lows": False,
            "all_swing_lows": [round(lo, decimals)],
            "has_sweep": False,
            "sweep_price": None,
            "sweep_date": None,
            "sweep_bars_ago": None,
            "sweep_label": "",
            "liquidity_score": 35,
            "liquidity_bonus_pts": 0,
            "liquidity_code": "NORMAL",
            "liquidity_verdict": "💧 Flujo de Liquidez Normal"
        }

    lows = fibo_hist["Low"].astype(float).to_numpy()
    highs = fibo_hist["High"].astype(float).to_numpy()
    opens = fibo_hist["Open"].astype(float).to_numpy()
    closes = fibo_hist["Close"].astype(float).to_numpy()
    if "Volume" in fibo_hist.columns:
        vols = fibo_hist["Volume"].fillna(0.0).astype(float).to_numpy()
    else:
        vols = pd.Series(0.0, index=fibo_hist.index).to_numpy()
    dates = fibo_hist.index
    n_bars = len(fibo_hist)

    # =========================================================================
    # PILAR 1: PERFIL DE VOLUMEN (VOLUME PROFILE), POC Y LIQUIDEZ POR FIBONACCI
    # =========================================================================
    has_real_volume = float(vols.sum()) > 0
    profile_type = "VOLUME" if has_real_volume else "TPO"
    bin_width = price_range / num_bins
    bins = [0.0] * num_bins

    for idx in range(n_bars):
        b_l = lows[idx]
        b_h = highs[idx]
        b_c = closes[idx]
        b_v = vols[idx] if has_real_volume else 1.0
        if b_v <= 0:
            continue

        tp = (b_h + b_l + 2.0 * b_c) / 4.0
        tp_bin = min(num_bins - 1, max(0, int((tp - lo) / bin_width)))
        i_start = min(num_bins - 1, max(0, int((b_l - lo) / bin_width)))
        i_end = min(num_bins - 1, max(0, int((b_h - lo) / bin_width)))
        span = max(1, (i_end - i_start) + 1)

        # 40% ponderado en precio típico de aceptación + 60% repartido en el rango de la vela
        bins[tp_bin] += b_v * 0.40
        share = (b_v * 0.60) / span
        for b_i in range(i_start, i_end + 1):
            bins[b_i] += share

    poc_idx = max(range(num_bins), key=lambda i: bins[i])
    max_bin_vol = bins[poc_idx] if bins[poc_idx] > 0 else 1.0
    poc_price = round(lo + (poc_idx + 0.5) * bin_width, decimals)
    poc_pct_pos = round(max(0.0, min(100.0, ((poc_price - lo) / price_range) * 100.0)), 1)
    poc_dist_pct = round(((current_price - poc_price) / poc_price) * 100.0, 2) if poc_price > 0 else 0.0

    # Área de Valor Institucional (70% del volumen negociado en torno al POC)
    total_bin_vol = sum(bins)
    va_low_idx = poc_idx
    va_high_idx = poc_idx
    acc_vol = bins[poc_idx]
    target_va_vol = total_bin_vol * 0.70

    while acc_vol < target_va_vol and (va_low_idx > 0 or va_high_idx < num_bins - 1):
        cand_down = bins[va_low_idx - 1] if va_low_idx > 0 else -1.0
        cand_up = bins[va_high_idx + 1] if va_high_idx < num_bins - 1 else -1.0
        if cand_down >= cand_up and va_low_idx > 0:
            va_low_idx -= 1
            acc_vol += bins[va_low_idx]
        elif va_high_idx < num_bins - 1:
            va_high_idx += 1
            acc_vol += bins[va_high_idx]
        else:
            break

    val_price = round(lo + va_low_idx * bin_width, decimals)
    vah_price = round(lo + (va_high_idx + 1) * bin_width, decimals)

    # Densidad de liquidez sobre cada nivel de Fibonacci
    fib_liquidity = {}
    for lvl_key, f_price in fib_levels.items():
        f_bin = min(num_bins - 1, max(0, int((f_price - lo) / bin_width)))
        local_vol = bins[f_bin]
        if f_bin > 0:
            prev_center = lo + (f_bin - 0.5) * bin_width
            if abs(f_price - prev_center) <= bin_width * 0.9:
                local_vol = max(local_vol, bins[f_bin - 1] * 0.90)
        if f_bin < num_bins - 1:
            next_center = lo + (f_bin + 1.5) * bin_width
            if abs(f_price - next_center) <= bin_width * 0.9:
                local_vol = max(local_vol, bins[f_bin + 1] * 0.90)

        strength_pct = int(round((local_vol / max_bin_vol) * 100.0))
        strength_pct = max(6, min(100, strength_pct))
        is_at_poc = (f_bin == poc_idx) or (abs(f_price - poc_price) / max(poc_price, 1e-9) * 100.0 <= 1.5)

        if is_at_poc:
            strength_pct = max(strength_pct, 94)
            tier = "POC_WALL"
            badge = "🏦 Muro POC"
        elif strength_pct >= 65:
            tier = "HIGH"
            badge = "🏦 Alta Liq."
        elif strength_pct >= 36:
            tier = "MEDIUM"
            badge = "💧 Media"
        else:
            tier = "LOW"
            badge = "🕳️ Vacío LVN"

        fib_liquidity[lvl_key] = {
            "strength_pct": strength_pct,
            "tier": tier,
            "badge": badge,
            "is_poc": is_at_poc
        }

    # Evaluar confluencia entre niveles de compra Fibonacci (50%, 61.8%, 78.6%) y Muro POC / HVN
    buy_fib_candidates = []
    for buy_lvl in ("61.8%", "50.0%", "78.6%"):
        fl = fib_liquidity.get(buy_lvl)
        if fl and (fl["is_poc"] or fl["strength_pct"] >= 72):
            priority = (1 if fl["is_poc"] else 0, 1 if buy_lvl == "61.8%" else 0, fl["strength_pct"])
            buy_fib_candidates.append((priority, buy_lvl, fl))

    if buy_fib_candidates:
        buy_fib_candidates.sort(key=lambda x: x[0], reverse=True)
        _, best_lvl, best_fl = buy_fib_candidates[0]
        wall_tag = "Muro POC" if best_fl["is_poc"] else "Liquidez HVN"
        fib_poc_confluence = {
            "has_confluence": True,
            "level": best_lvl,
            "price": fib_levels[best_lvl],
            "strength_pct": best_fl["strength_pct"],
            "is_poc": best_fl["is_poc"],
            "label": f"🏦 {wall_tag} en {best_lvl} ({currency}{fib_levels[best_lvl]:,.{decimals}f})"
        }
    else:
        fib_poc_confluence = {
            "has_confluence": False,
            "level": None,
            "price": None,
            "strength_pct": 0,
            "is_poc": False,
            "label": ""
        }

    # =========================================================================
    # PILAR 2: VOLUMEN RELATIVO (RVOL) Y ABSORCIÓN INSTITUCIONAL (BALLENAS)
    # =========================================================================
    avg_vol_20 = 0.0
    if full_hist is not None and not full_hist.empty and "Volume" in full_hist.columns:
        v_all = full_hist["Volume"].fillna(0.0).astype(float)
        base_slice = v_all.iloc[-21:-1] if len(v_all) > 3 else v_all
        pos_base = base_slice[base_slice > 0]
        if len(pos_base) >= 3:
            avg_vol_20 = float(pos_base.mean())

    if avg_vol_20 > 0:
        v_all = full_hist["Volume"].fillna(0.0).astype(float)
        last_vol = float(v_all.iloc[-1])
        if last_vol <= 0 and len(v_all) >= 2 and float(v_all.iloc[-2]) > 0:
            eff_vol = float(v_all.iloc[-2])
        else:
            eff_vol = last_vol

        rvol = round(eff_vol / avg_vol_20, 2)
        peak_rvol_3d = round(float(v_all.iloc[-min(3, len(v_all)):].max()) / avg_vol_20, 2)

        if rvol >= 1.85:
            rvol_status = "CLIMAX"
            rvol_label = f"{rvol:.2f}x 🔥 Clímax"
        elif rvol >= 1.30:
            rvol_status = "HIGH"
            rvol_label = f"{rvol:.2f}x 🐋 Alto"
        elif rvol >= 0.70:
            rvol_status = "NORMAL"
            rvol_label = f"{rvol:.2f}x Normal"
        else:
            rvol_status = "LOW"
            rvol_label = f"{rvol:.2f}x Seco"
    else:
        rvol = 0.0
        peak_rvol_3d = 0.0
        rvol_status = "NO_VOL"
        rvol_label = "TPO (Sin vol.)"

    has_absorption = False
    absorption_label = ""
    lookback_abs = min(3, n_bars)
    for offset in range(lookback_abs):
        idx = (n_bars - 1) - offset
        b_h, b_l, b_o, b_c = highs[idx], lows[idx], opens[idx], closes[idx]
        b_rng = b_h - b_l
        if b_rng <= 1e-9 or current_price < b_l:
            continue
        lower_wick = min(b_o, b_c) - b_l
        wick_ratio = lower_wick / b_rng
        close_pos = (b_c - b_l) / b_rng
        b_rvol = (vols[idx] / avg_vol_20) if avg_vol_20 > 0 else 1.0
        in_discount_zone = b_l <= (fib_levels["38.2%"] * 1.01)

        if avg_vol_20 > 0 and in_discount_zone:
            if (b_rvol >= 1.30 and wick_ratio >= 0.32 and close_pos >= 0.45) or (
                b_rvol >= 1.65 and b_c >= b_o and close_pos >= 0.55
            ):
                has_absorption = True
                absorption_label = f"🐋 Absorción Inst. ({b_rvol:.1f}x Vol)"
                break
        elif avg_vol_20 == 0 and in_discount_zone and wick_ratio >= 0.48 and close_pos >= 0.60:
            has_absorption = True
            absorption_label = "🐋 Mecha de Absorción"
            break

    # =========================================================================
    # PILAR 3: PISCINAS DE LIQUIDEZ (SSL POOL) Y BARRIDO DE STOPS (SWEEP SMC)
    # =========================================================================
    swing_lows = []  # lista de tuplas (bar_index, low_price)
    for i in range(2, n_bars - 2):
        if lows[i] <= lows[i - 1] and lows[i] <= lows[i - 2] and lows[i] <= lows[i + 1] and lows[i] <= lows[i + 2]:
            swing_lows.append((i, float(lows[i])))

    if n_bars >= 5:
        prior_min_idx = int(lows[:-2].argmin())
        prior_min_val = float(lows[prior_min_idx])
        if not any(abs(p - prior_min_val) / max(prior_min_val, 1e-9) < 0.002 for _, p in swing_lows):
            swing_lows.append((prior_min_idx, prior_min_val))
            swing_lows.sort(key=lambda x: x[0])

    # Detectar Equal Lows (Doble/Triple Suelo donde se acumulan miles de Stop Loss)
    eql_pools = []
    for i in range(len(swing_lows)):
        idx_a, price_a = swing_lows[i]
        for j in range(i + 1, len(swing_lows)):
            idx_b, price_b = swing_lows[j]
            if (idx_b - idx_a) < 3:
                continue
            diff_pct = abs(price_a - price_b) / max(price_a, 1e-9) * 100.0
            if diff_pct <= 0.95:
                pool_lvl = min(price_a, price_b)
                # Comprobar que no haya sido roto con cierre contundente (> 1.5%) después de idx_b
                post_closes = closes[idx_b + 1:]
                if len(post_closes) == 0 or float(post_closes.min()) >= pool_lvl * 0.985:
                    eql_pools.append(pool_lvl)

    # Seleccionar la piscina de liquidez vendedora (SSL) activa más relevante bajo/cerca del precio actual
    is_equal_lows = False
    below_eql = [p for p in eql_pools if p <= current_price * 1.01]
    if below_eql:
        ssl_raw = max(below_eql)  # El doble suelo más cercano por debajo del precio actual
        if ((current_price - ssl_raw) / max(current_price, 1e-9) * 100.0) <= 10.0:
            is_equal_lows = True
        else:
            below_eql = []

    if not below_eql:
        below_swings = [p for _, p in swing_lows if p <= current_price * 1.005]
        ssl_raw = max(below_swings) if below_swings else lo

    ssl_pool_price = round(float(ssl_raw), decimals)
    ssl_dist_pct = round(((current_price - ssl_pool_price) / current_price) * 100.0, 2) if current_price > 0 else 0.0
    ssl_type = "EQL" if is_equal_lows else "SWING_LOW"
    ssl_type_label = "Doble Suelo EQL" if is_equal_lows else "Swing Low (Stops)"

    # Detector de Barrido de Liquidez Alcista (Bullish Liquidity Sweep / Spring en últimas 3 velas)
    has_sweep = False
    sweep_price = None
    sweep_date = None
    sweep_bars_ago = None
    sweep_label = ""

    start_check = max(3, n_bars - 3)
    for idx in range(n_bars - 1, start_check - 1, -1):
        b_l, b_h, b_c = lows[idx], highs[idx], closes[idx]
        b_rng = b_h - b_l
        if b_rng <= 1e-9:
            continue
        close_recovery = (b_c - b_l) / b_rng
        if close_recovery < 0.38:
            continue

        # Pivotes formados al menos 3 sesiones antes cuya liquidez seguía intacta hasta esta vela
        prior_candidates = [p for p_i, p in swing_lows if p_i <= idx - 3]
        prior_candidates.sort(reverse=True)
        for p_low in prior_candidates:
            # Verificar que entre la formación y el barrido no se hubiese roto ya al cierre
            # Buscamos el primer índice del pivote
            p_indices = [p_i for p_i, p in swing_lows if abs(p - p_low) < 1e-9 and p_i <= idx - 3]
            if not p_indices:
                continue
            p_idx = p_indices[-1]
            inter_closes = closes[p_idx + 1:idx]
            if len(inter_closes) > 0 and float(inter_closes.min()) < p_low * 0.994:
                continue

            # Condición SMC Sweep: mecha perfora el Swing Low (hasta -3.8%), barre stops y cierra por encima
            if (p_low * 0.962) <= b_l < (p_low * 0.999) and b_c > p_low and current_price >= p_low:
                has_sweep = True
                sweep_price = round(float(p_low), decimals)
                ts_bar = dates[idx]
                sweep_date = ts_bar.strftime("%Y-%m-%d") if hasattr(ts_bar, "strftime") else str(ts_bar)[:10]
                sweep_bars_ago = int((n_bars - 1) - idx)
                sweep_label = f"🧲 Barrido de Stops ({currency}{sweep_price:,.{decimals}f})"
                break
        if has_sweep:
            break

    # =========================================================================
    # SCORE DE LIQUIDEZ (0-100), BONUS DE CONFLUENCIA Y VEREDICTO INSTITUCIONAL
    # =========================================================================
    in_buy_half = current_price <= fib_levels["50.0%"]
    near_poc = abs(poc_dist_pct) <= 2.2

    if in_buy_half and near_poc:
        poc_pts = 38
    elif near_poc:
        poc_pts = 34
    elif fib_poc_confluence["has_confluence"] and current_price <= fib_levels["38.2%"]:
        poc_pts = 28
    elif current_price <= poc_price:
        poc_pts = 22
    else:
        poc_pts = 12

    if has_absorption:
        vol_pts = 32
    elif rvol_status in ("CLIMAX", "HIGH") and in_buy_half:
        vol_pts = 24
    elif rvol_status == "LOW" and current_price <= fib_levels["61.8%"]:
        vol_pts = 18  # Secado de oferta en nivel áureo
    else:
        vol_pts = 10

    if has_sweep:
        sweep_pts = 30
    elif is_equal_lows and 0 <= ssl_dist_pct <= 4.0:
        sweep_pts = 18
    elif 0 <= ssl_dist_pct <= 3.0:
        sweep_pts = 14
    else:
        sweep_pts = 8

    liquidity_score = max(0, min(100, poc_pts + vol_pts + sweep_pts))

    bonus_pts = 0
    if has_sweep:
        bonus_pts += 4
    if has_absorption:
        bonus_pts += 3
    if (near_poc and current_price <= fib_levels["38.2%"]) or (in_buy_half and fib_poc_confluence["has_confluence"]):
        bonus_pts += 3
    liquidity_bonus_pts = min(9, bonus_pts)

    if has_sweep and has_absorption:
        liquidity_code = "SWEEP_ABSORPTION"
        liquidity_verdict = "🔥 Barrido de Stops + Absorción Institucional"
    elif has_sweep:
        liquidity_code = "SWEEP"
        liquidity_verdict = "🧲 Barrido de Liquidez Recuperado (Spring SMC)"
    elif has_absorption:
        liquidity_code = "ABSORPTION"
        liquidity_verdict = "🐋 Absorción Institucional en Retroceso"
    elif near_poc:
        liquidity_code = "AT_POC"
        liquidity_verdict = "🏦 Cotizando sobre Muro POC de Liquidez"
    elif fib_poc_confluence["has_confluence"]:
        liquidity_code = "FIB_POC"
        wall_name = "Muro POC" if fib_poc_confluence.get("is_poc") else "Liquidez HVN"
        liquidity_verdict = f"🏦 Soporte {fib_poc_confluence['level']} respaldado por {wall_name}"
    elif is_equal_lows and 0 < ssl_dist_pct <= 3.8:
        liquidity_code = "EQL_MAGNET"
        liquidity_verdict = "⚠️ Doble Suelo cercano (Imán de Stops debajo)"
    elif current_price < val_price:
        liquidity_code = "BELOW_VAL"
        liquidity_verdict = "💎 Descuento bajo Área de Valor (VAL)"
    else:
        liquidity_code = "NORMAL"
        liquidity_verdict = "💧 Flujo de Liquidez Normal"

    all_distinct_lows = sorted({round(float(p), decimals) for _, p in swing_lows} | {round(lo, decimals)})

    return {
        "profile_type": profile_type,
        "has_real_volume": has_real_volume,
        "poc_price": poc_price,
        "poc_pct_pos": poc_pct_pos,
        "poc_dist_pct": poc_dist_pct,
        "val_price": val_price,
        "vah_price": vah_price,
        "fib_liquidity": fib_liquidity,
        "fib_poc_confluence": fib_poc_confluence,
        "rvol": rvol,
        "peak_rvol_3d": peak_rvol_3d,
        "rvol_status": rvol_status,
        "rvol_label": rvol_label,
        "has_absorption": has_absorption,
        "absorption_label": absorption_label,
        "ssl_pool_price": ssl_pool_price,
        "ssl_dist_pct": ssl_dist_pct,
        "ssl_type": ssl_type,
        "ssl_type_label": ssl_type_label,
        "is_equal_lows": is_equal_lows,
        "all_swing_lows": all_distinct_lows,
        "has_sweep": has_sweep,
        "sweep_price": sweep_price,
        "sweep_date": sweep_date,
        "sweep_bars_ago": sweep_bars_ago,
        "sweep_label": sweep_label,
        "liquidity_score": liquidity_score,
        "liquidity_bonus_pts": liquidity_bonus_pts,
        "liquidity_code": liquidity_code,
        "liquidity_verdict": liquidity_verdict
    }


def _compute_timeframe_snapshot(
    hist,
    period,
    current_price,
    currency,
    decimals,
    rsi_14,
    rsi_pts,
    sma_dist_pct,
    is_above_sma,
    sma_pts,
    atr_14,
    atr_pct,
    earnings_info
):
    """Calcula todos los niveles Fibonacci, cronología, Score, Gestión de Riesgo (+ATR) y Modo Venta para un periodo dado."""
    latest_bar_ts = hist.index[-1]
    if period == "1mo":
        start_date = latest_bar_ts - datetime.timedelta(days=32)
    elif period == "3mo":
        start_date = latest_bar_ts - datetime.timedelta(days=95)
    elif period == "6mo":
        start_date = latest_bar_ts - datetime.timedelta(days=185)
    else:  # 1y o superior
        start_date = latest_bar_ts - datetime.timedelta(days=366)

    fibo_hist = hist[hist.index >= start_date]
    if fibo_hist.empty:
        fibo_hist = hist

    hi = float(fibo_hist["High"].max())
    lo = float(fibo_hist["Low"].min())
    price_range = hi - lo

    hi_idx = fibo_hist["High"].idxmax()
    lo_idx = fibo_hist["Low"].idxmin()
    hi_date = hi_idx.strftime("%Y-%m-%d") if hasattr(hi_idx, "strftime") else str(hi_idx)[:10]
    lo_date = lo_idx.strftime("%Y-%m-%d") if hasattr(lo_idx, "strftime") else str(lo_idx)[:10]

    lo_pos = fibo_hist.index.get_loc(lo_idx)
    if isinstance(lo_pos, slice):
        lo_pos = lo_pos.stop - 1
    elif hasattr(lo_pos, "__len__"):
        lo_pos = int(lo_pos[-1])
    bars_since_low = max(0, (len(fibo_hist) - 1) - int(lo_pos))
    rebound_from_low_pct = ((current_price - lo) / lo) * 100 if lo > 0 else 0.0

    fib_levels = {
        "23.6%": round(hi - (price_range * 0.236), decimals),
        "38.2%": round(hi - (price_range * 0.382), decimals),
        "50.0%": round(hi - (price_range * 0.500), decimals),
        "61.8%": round(hi - (price_range * 0.618), decimals),
        "78.6%": round(hi - (price_range * 0.786), decimals),
    }

    if lo_idx <= hi_idx:
        swing_type = "BULLISH_PULLBACK"
        swing_label = "🐂 Impulso Alcista (Mín→Máx)"
        swing_pts = 5 if current_price <= fib_levels["50.0%"] else 0
    elif bars_since_low <= 3 or rebound_from_low_pct <= 1.8:
        swing_type = "FALLING_KNIFE"
        swing_label = "⚠️ Caída Activa (Buscando Suelo)"
        swing_pts = -10 if not is_above_sma else -5
    else:
        swing_type = "BOTTOM_REBOUND"
        swing_label = "🔄 Rebote tras Suelo"
        swing_pts = 0

    drop_pct = round(((hi - current_price) / hi) * 100, 2) if hi > 0 else 0.0

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

    # Precaución suave (-5 pts) si presenta resultados en <= 3 días (alto riesgo de gap binario)
    earnings_pts = 0
    if earnings_info and earnings_info.get("warning_level") == "IMMINENT" and earnings_info.get("days_until", 99) <= 3:
        earnings_pts = -5

    # MOTOR DE LIQUIDEZ INSTITUCIONAL (Volume Profile POC + RVOL/Absorción + Piscinas SSL & Sweep)
    liquidity_data = compute_liquidity_metrics(
        fibo_hist=fibo_hist,
        full_hist=hist,
        fib_levels=fib_levels,
        current_price=current_price,
        currency=currency,
        decimals=decimals
    )
    liquidity_pts = int(liquidity_data.get("liquidity_bonus_pts", 0))
    all_swing_lows = liquidity_data.pop("all_swing_lows", [round(lo, decimals)])

    total_score = max(0, min(100, fibo_pts + rsi_pts + sma_pts + drop_pts + swing_pts + earnings_pts + liquidity_pts))

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

    # MÓDULO DE GESTIÓN DE RIESGO PROFESIONAL (Estructural Fibonacci + Volatilidad ATR 14 + Piscina Liquidez SSL)
    fib_61 = fib_levels["61.8%"]
    fib_78 = fib_levels["78.6%"]
    fib_38 = fib_levels["38.2%"]
    min_unit_risk = 0.0001 if decimals >= 4 else 0.01

    if current_price <= fib_61:
        entry_price = round(current_price, decimals)
        entry_type = "MARKET"
        entry_label = f"Precio de Mercado ({currency}{entry_price:,.{decimals}f})"
    else:
        entry_price = round(fib_61, decimals)
        entry_type = "LIMIT_618"
        entry_label = f"Límite 61.8% ({currency}{entry_price:,.{decimals}f})"

    # 1) Stop Loss Estructural Fibonacci (78.6% / suelo)
    suggested_sl = round(min(fib_78 * 0.98, lo * 0.985), decimals)
    if suggested_sl >= entry_price:
        suggested_sl = round(entry_price * 0.96, decimals)

    risk_per_share = round(max(min_unit_risk, entry_price - suggested_sl), decimals)
    risk_pct = round(((entry_price - suggested_sl) / entry_price) * 100, 2) if entry_price > 0 else 5.0

    # 2) Stop Loss Dinámico por Volatilidad (2.0x ATR 14)
    if atr_14 > 0:
        atr_sl_raw = entry_price - (2.0 * atr_14)
        if atr_sl_raw <= 0 or atr_sl_raw >= entry_price:
            atr_sl_raw = entry_price * 0.95
        atr_stop_loss = round(atr_sl_raw, decimals)
    else:
        atr_stop_loss = suggested_sl

    atr_risk_per_share = round(max(min_unit_risk, entry_price - atr_stop_loss), decimals)
    atr_risk_pct = round(((entry_price - atr_stop_loss) / entry_price) * 100, 2) if entry_price > 0 else risk_pct

    # 3) Stop Loss Protegido Bajo Piscina de Liquidez (SSL Pool - 0.5x ATR)
    lows_below_entry = [p for p in all_swing_lows if p < entry_price * 0.996]
    entry_ssl_pool = max(lows_below_entry) if lows_below_entry else min(lo, entry_price * 0.97)
    ssl_buffer = (0.55 * atr_14) if atr_14 > 0 else (entry_ssl_pool * 0.012)
    ssl_sl_raw = entry_ssl_pool - ssl_buffer
    if ssl_sl_raw <= 0 or ssl_sl_raw >= entry_price:
        ssl_sl_raw = entry_price * 0.955
    if (entry_price - ssl_sl_raw) > (entry_price * 0.24):
        ssl_sl_raw = entry_price * 0.84
    ssl_stop_loss = round(ssl_sl_raw, decimals)
    ssl_risk_per_share = round(max(min_unit_risk, entry_price - ssl_stop_loss), decimals)
    ssl_risk_pct = round(((entry_price - ssl_stop_loss) / entry_price) * 100, 2) if entry_price > 0 else risk_pct

    tp1 = round(max(fib_38, entry_price * 1.05), decimals)
    reward_1 = round(tp1 - entry_price, decimals)
    reward_1_pct = round(((tp1 - entry_price) / entry_price) * 100, 2)
    rr_ratio_1 = round(reward_1 / risk_per_share, 2) if risk_per_share > 0 else 1.0
    atr_rr_ratio_1 = round(reward_1 / atr_risk_per_share, 2) if atr_risk_per_share > 0 else rr_ratio_1
    ssl_rr_ratio_1 = round(reward_1 / ssl_risk_per_share, 2) if ssl_risk_per_share > 0 else rr_ratio_1

    tp2 = round(max(hi, tp1 * 1.04), decimals)
    reward_2 = round(tp2 - entry_price, decimals)
    reward_2_pct = round(((tp2 - entry_price) / entry_price) * 100, 2)
    rr_ratio_2 = round(reward_2 / risk_per_share, 2) if risk_per_share > 0 else 2.5
    atr_rr_ratio_2 = round(reward_2 / atr_risk_per_share, 2) if atr_risk_per_share > 0 else rr_ratio_2
    ssl_rr_ratio_2 = round(reward_2 / ssl_risk_per_share, 2) if ssl_risk_per_share > 0 else rr_ratio_2

    if rr_ratio_2 >= 3.0:
        rr_rating = "⭐ Excelente (R:R > 1:3)"
        rr_code = "EXCELLENT"
    elif rr_ratio_2 >= 2.0:
        rr_rating = "🟢 Favorable (R:R > 1:2)"
        rr_code = "FAVORABLE"
    elif rr_ratio_2 >= 1.5:
        rr_rating = "🟡 Aceptable (R:R > 1:1.5)"
        rr_code = "ACCEPTABLE"
    else:
        rr_rating = "⚪ Ajustado (R:R < 1:1.5)"
        rr_code = "TIGHT"

    risk_mgmt = {
        "entry_price": entry_price,
        "entry_type": entry_type,
        "entry_label": entry_label,
        "stop_loss": suggested_sl,
        "risk_per_share": risk_per_share,
        "risk_pct": risk_pct,
        "atr_14": atr_14,
        "atr_pct": atr_pct,
        "atr_stop_loss": atr_stop_loss,
        "atr_risk_per_share": atr_risk_per_share,
        "atr_risk_pct": atr_risk_pct,
        "atr_rr_ratio_1": atr_rr_ratio_1,
        "atr_rr_ratio_2": atr_rr_ratio_2,
        "ssl_pool_ref": round(float(entry_ssl_pool), decimals),
        "ssl_stop_loss": ssl_stop_loss,
        "ssl_risk_per_share": ssl_risk_per_share,
        "ssl_risk_pct": ssl_risk_pct,
        "ssl_rr_ratio_1": ssl_rr_ratio_1,
        "ssl_rr_ratio_2": ssl_rr_ratio_2,
        "take_profit_1": tp1,
        "reward_1_pct": reward_1_pct,
        "rr_ratio_1": rr_ratio_1,
        "take_profit_2": tp2,
        "reward_2_pct": reward_2_pct,
        "rr_ratio_2": rr_ratio_2,
        "rr_rating": rr_rating,
        "rr_code": rr_code
    }

    # MÓDULO DE MODO VENTA / TOMA DE BENEFICIOS
    gain_from_low = round(((current_price - lo) / lo) * 100, 2) if lo > 0 else 0.0
    dist_to_high = round(((hi - current_price) / hi) * 100, 2) if hi > 0 else 0.0

    ext_127 = round(hi + (price_range * 0.272), decimals)
    ext_161 = round(hi + (price_range * 0.618), decimals)

    dist_to_ext127 = round(((ext_127 - current_price) / current_price) * 100, 2)
    dist_to_ext161 = round(((ext_161 - current_price) / current_price) * 100, 2)

    if rsi_14 >= 75:
        rsi_sell_pts = 40
    elif rsi_14 >= 70:
        rsi_sell_pts = 32
    elif rsi_14 >= 65:
        rsi_sell_pts = 22
    elif rsi_14 >= 60:
        rsi_sell_pts = 10
    else:
        rsi_sell_pts = 0

    if current_price >= ext_161:
        ext_pts = 40
    elif current_price >= ext_127:
        ext_pts = 32
    elif dist_to_high <= 2.0:
        ext_pts = 26
    elif dist_to_high <= 5.0:
        ext_pts = 16
    elif dist_to_high <= 10.0:
        ext_pts = 8
    else:
        ext_pts = 0

    if sma_dist_pct >= 25.0:
        sma_sell_pts = 20
    elif sma_dist_pct >= 18.0:
        sma_sell_pts = 14
    elif sma_dist_pct >= 10.0:
        sma_sell_pts = 8
    else:
        sma_sell_pts = 0

    sell_score = min(100, rsi_sell_pts + ext_pts + sma_sell_pts)

    if sell_score >= 70 or rsi_14 >= 72 or current_price >= ext_127:
        sell_signal = "🔴 TOMA DE BENEFICIOS FUERTE"
        sell_action = "Venta parcial recomendada (30%-50%) o ajustar Trailing Stop ceñido."
        sell_status_code = "STRONG_SELL"
    elif sell_score >= 50 or rsi_14 >= 64 or dist_to_high <= 3.5:
        sell_signal = "🟠 ALERTA RESISTENCIA / PARCIAL"
        sell_action = "Subir Stop a Break-Even y valorar recogida parcial de ganancias."
        sell_status_code = "PARTIAL_SELL"
    elif sell_score >= 30:
        sell_signal = "🟡 MANTENER (Tendencia Sana)"
        sell_action = "Mantener posición con stop protector activo."
        sell_status_code = "HOLD"
    else:
        sell_signal = "🟢 SIN PRESIÓN DE VENTA"
        sell_action = "Activo en zona baja o de retroceso; no es momento de vender."
        sell_status_code = "ACCUMULATE"

    suggested_trailing_stop = round(current_price * 0.945, decimals)
    if atr_14 > 0 and (2.2 * atr_14) < (current_price * 0.35):
        atr_trailing_stop = round(current_price - (2.2 * atr_14), decimals)
        atr_trailing_pct = round(((current_price - atr_trailing_stop) / current_price) * 100, 2)
    else:
        atr_trailing_stop = suggested_trailing_stop
        atr_trailing_pct = 5.5

    sell_mgmt = {
        "sell_score": sell_score,
        "sell_signal": sell_signal,
        "sell_action": sell_action,
        "sell_status_code": sell_status_code,
        "gain_from_low_pct": gain_from_low,
        "dist_to_high_pct": dist_to_high,
        "ext_127": ext_127,
        "ext_161": ext_161,
        "dist_to_ext127_pct": dist_to_ext127,
        "dist_to_ext161_pct": dist_to_ext161,
        "trailing_stop": suggested_trailing_stop,
        "trailing_stop_pct": 5.5,
        "atr_trailing_stop": atr_trailing_stop,
        "atr_trailing_pct": atr_trailing_pct
    }

    return {
        "period": period,
        "min": round(lo, decimals),
        "max": round(hi, decimals),
        "range": round(price_range, decimals),
        "low_date": lo_date,
        "high_date": hi_date,
        "bars_since_low": bars_since_low,
        "swing_type": swing_type,
        "swing_label": swing_label,
        "drop_pct": drop_pct,
        "zone_desc": zone_desc,
        "signal": signal,
        "status_code": status_code,
        "fib_levels": fib_levels,
        "score": total_score,
        "confluence_rating": confluence_rating,
        "confluence_code": confluence_code,
        "liquidity": liquidity_data,
        "risk_mgmt": risk_mgmt,
        "sell_mgmt": sell_mgmt
    }


def detect_fibonacci_clusters(timeframes, current_price, currency, decimals, tolerance_pct=1.8):
    """
    Detecta Clusters de Confluencia Multi-Timeframe donde niveles relevantes (38.2%, 50%, 61.8%, 78.6%)
    de ondas/impulsos genuinamente distintos (1M, 3M, 6M, 1A) convergen en la misma franja de precio (<= 1.8%).
    """
    distinct_swings = []
    accepted_ranges = []
    for p in SUPPORTED_PERIODS:
        snap = timeframes.get(p)
        if not snap:
            continue
        s_min, s_max = float(snap["min"]), float(snap["max"])
        # Descartar ventanas cuyo suelo y techo sean prácticamente la misma onda (< 2.5% de diferencia)
        is_near_dup = False
        for prev_min, prev_max in accepted_ranges:
            min_diff = abs(s_min - prev_min) / max(prev_min, 1e-9) * 100
            max_diff = abs(s_max - prev_max) / max(prev_max, 1e-9) * 100
            if min_diff < 2.5 and max_diff < 2.5:
                is_near_dup = True
                break
        if is_near_dup:
            continue
        accepted_ranges.append((s_min, s_max))
        distinct_swings.append((p, PERIOD_SHORT_LABELS.get(p, p.upper()), snap["fib_levels"]))

    if len(distinct_swings) < 2:
        return []

    points = []
    for p_key, p_lbl, fibs in distinct_swings:
        for lvl_name in ("38.2%", "50.0%", "61.8%", "78.6%"):
            val = float(fibs.get(lvl_name, 0))
            if val > 0:
                points.append({
                    "period": p_key,
                    "period_label": p_lbl,
                    "level": lvl_name,
                    "price": val
                })

    points.sort(key=lambda x: x["price"], reverse=True)
    used = [False] * len(points)
    clusters = []

    for i, base in enumerate(points):
        if used[i]:
            continue
        group = [base]
        group_periods = {base["period"]}
        for j in range(i + 1, len(points)):
            if used[j]:
                continue
            cand = points[j]
            if cand["period"] in group_periods:
                continue
            diff_pct = abs(base["price"] - cand["price"]) / base["price"] * 100
            if diff_pct <= tolerance_pct:
                group.append(cand)
                group_periods.add(cand["period"])

        # Exigir al menos 2 niveles de Fibonacci distintos (confluencia armónica cruzada, ej. 38.2% + 61.8%)
        distinct_levels = {g["level"] for g in group}
        if len(group) >= 2 and len(distinct_levels) >= 2:
            for g in group:
                idx_g = points.index(g)
                used[idx_g] = True

            prices = [g["price"] for g in group]
            center = round(sum(prices) / len(prices), decimals)
            low_b = round(min(prices), decimals)
            high_b = round(max(prices), decimals)
            spread_pct = round(((high_b - low_b) / center) * 100, 2) if center > 0 else 0.0
            dist_from_curr_pct = round(((current_price - center) / center) * 100, 2) if center > 0 else 0.0
            has_golden = any(g["level"] == "61.8%" for g in group)
            has_buy_zone = any(g["level"] in ("50.0%", "61.8%", "78.6%") for g in group)
            members = [f"{g['period_label']} {g['level']}" for g in group]
            members_detail = [
                {
                    "period": g["period"],
                    "period_label": g["period_label"],
                    "level": g["level"],
                    "price": round(g["price"], decimals)
                }
                for g in group
            ]
            is_near_price = abs(dist_from_curr_pct) <= 2.5

            clusters.append({
                "center_price": center,
                "min_price": low_b,
                "max_price": high_b,
                "spread_pct": spread_pct,
                "dist_pct": dist_from_curr_pct,
                "members": members,
                "members_detail": members_detail,
                "strength": len(group),
                "has_golden": has_golden,
                "has_buy_zone": has_buy_zone,
                "is_active": is_near_price,
                "label": f"🧲 Cluster {'Áureo ' if has_golden else ''}MTF {currency}{center:,.{decimals}f} ({' + '.join(members)})"
            })

    # Ordenar priorizando clusters cercanos al precio actual y con proporción áurea
    clusters.sort(key=lambda c: (not c["is_active"], not c["has_golden"], abs(c["dist_pct"])))
    return clusters[:3]


def fetch_asset_data(asset, period="3mo", return_history=False, quiet=False):
    tab = asset["tab"]
    ticker = asset["ticker"]
    name = asset.get("name", tab)

    if not quiet:
        print(f"  🔍 Consultando {name} ({ticker})...", end="\r")

    t = yf.Ticker(ticker)
    # Descargamos 1 año para tener SMA 200, RSI, ATR(14) y las 4 ventanas MTF de una sola pasada
    hist = t.history(period="1y")

    if hist.empty:
        hist = t.history(period="2y")

    if hist.empty:
        print(f"  ❌ No se pudieron obtener datos para {ticker}")
        return (None, None) if return_history else None

    current_price = float(hist["Close"].iloc[-1])
    currency, decimals = detect_asset_format(ticker, current_price)

    # 1. Indicadores Técnicos Globales (RSI 14, SMA 200, ATR 14, Calendario de Resultados)
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

    if len(hist) >= 200:
        sma_200 = float(hist["Close"].rolling(200).mean().iloc[-1])
    else:
        sma_200 = float(hist["Close"].mean())

    sma_dist_pct = round(((current_price - sma_200) / sma_200) * 100, 2)
    is_above_sma = current_price >= sma_200
    if is_above_sma:
        sma_pts = 20
    elif sma_dist_pct >= -4.0:
        sma_pts = 12
    else:
        sma_pts = 4

    atr_14, atr_pct = compute_atr(hist, period=14, decimals=decimals)
    earnings_info = fetch_earnings_info(ticker, yf_ticker_obj=t)

    # 2. Precalcular las 4 temporalidades (1mo, 3mo, 6mo, 1y) en memoria (< 1ms)
    periods_to_calc = list(SUPPORTED_PERIODS)
    if period not in periods_to_calc:
        periods_to_calc.append(period)

    timeframes = {}
    for p_code in periods_to_calc:
        timeframes[p_code] = _compute_timeframe_snapshot(
            hist=hist,
            period=p_code,
            current_price=current_price,
            currency=currency,
            decimals=decimals,
            rsi_14=rsi_14,
            rsi_pts=rsi_pts,
            sma_dist_pct=sma_dist_pct,
            is_above_sma=is_above_sma,
            sma_pts=sma_pts,
            atr_14=atr_14,
            atr_pct=atr_pct,
            earnings_info=earnings_info
        )

    # 3. Detectar Clusters de Fibonacci Multi-Timeframe y bonificar confluencia activa
    fib_clusters = detect_fibonacci_clusters(timeframes, current_price, currency, decimals)
    best_cluster = fib_clusters[0] if fib_clusters else None
    has_active_buy_cluster = bool(best_cluster and best_cluster.get("is_active") and best_cluster.get("has_buy_zone"))

    if has_active_buy_cluster:
        for p_code, snap in timeframes.items():
            boosted = min(100, snap["score"] + 4)
            snap["score"] = boosted
            if boosted >= 80:
                snap["confluence_rating"] = "🔥 CONFLUENCIA MÁXIMA"
                snap["confluence_code"] = "MAX_CONFLUENCE"
            elif boosted >= 65:
                snap["confluence_rating"] = "🟢 ALTA PROBABILIDAD"
                snap["confluence_code"] = "HIGH_PROB"

    active_snap = timeframes.get(period) or timeframes["3mo"]

    asset_payload = {
        "tab": tab,
        "ticker": ticker,
        "name": name,
        "currency": currency,
        "decimals": decimals,
        "current_price": round(current_price, decimals),
        **active_snap,
        # Indicadores técnicos transversales:
        "rsi": rsi_14,
        "rsi_desc": rsi_desc,
        "rsi_zone": rsi_zone,
        "sma_200": round(sma_200, decimals),
        "sma_dist_pct": sma_dist_pct,
        "is_above_sma": is_above_sma,
        "atr_14": atr_14,
        "atr_pct": atr_pct,
        "earnings": earnings_info,
        "fib_clusters": fib_clusters,
        "best_cluster": best_cluster,
        "timeframes": timeframes
    }
    return (asset_payload, hist) if return_history else asset_payload


def switch_cached_period(new_period):
    """
    Cambia la temporalidad activa en latest_data.json y config.json en < 5ms utilizando las
    ventanas Multi-Timeframe precalculadas sin necesidad de volver a descargar de Yahoo Finance.
    Devuelve None si aún no existen datos precalculados.
    """
    if new_period not in SUPPORTED_PERIODS:
        raise ValueError(f"Periodo '{new_period}' no soportado.")

    with SYNC_LOCK:
        if not os.path.exists(LATEST_DATA_PATH):
            return None
        with open(LATEST_DATA_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)

        items = payload.get("data", [])
        if not items or not all(isinstance(it.get("timeframes"), dict) and new_period in it["timeframes"] for it in items):
            return None

        for it in items:
            snap = it["timeframes"][new_period]
            for k, v in snap.items():
                it[k] = v

        cfg = load_config()
        payload["period"] = new_period
        payload["market_hours"] = evaluate_market_hours(cfg.get("assets", []))
        _atomic_write_json(LATEST_DATA_PATH, payload)

        if cfg.get("period") != new_period:
            cfg["period"] = new_period
            save_config(cfg)

        return payload

def print_summary_table(results, period, timestamp, sentiment=None):
    print("\n" + "=" * 134)
    print(f"📊 REPORTE DE MERCADO, FIBONACCI & LIQUIDEZ INSTITUCIONAL - {timestamp}")
    print(f"Ventana Fibonacci: {period} | Indicadores: Wilder's RSI(14) + SMA 200 + Volume Profile POC + RVOL + Sweep SMC")
    if sentiment:
        s_score = sentiment.get("score", 50)
        s_rating = sentiment.get("rating_es", "Neutral")
        s_icon = sentiment.get("icon", "🌡️")
        s_adv = sentiment.get("advice", "")
        print(f"🌡️ Sentimiento CNN Fear & Greed: {s_score}/100 {s_icon} [{s_rating}] -> {s_adv}")
    print("=" * 134)
    print(f"{'Activo':<10} {'Ticker':<9} {'Precio':>11} {'Caída %':>8} {'RSI':>5} {'Muro POC':>11} {'RVOL':>7} {'Score':>7} {'Liquidez SMC':<20} {'Confluencia':<20}")
    print("-" * 134)

    for r in results:
        curr = r.get("currency", "$")
        dec = r.get("decimals", 2)
        liq = r.get("liquidity") or {}
        curr_str = f"{curr}{r['current_price']:,.{dec}f}"
        drop_str = f"-{r['drop_pct']:.1f}%"
        rsi_str = f"{r.get('rsi', 0):.1f}"
        poc_val = liq.get("poc_price", r["current_price"])
        poc_str = f"{curr}{poc_val:,.{dec}f}"
        rvol_str = f"{liq.get('rvol', 0):.2f}x" if liq.get("has_real_volume") else "TPO"
        score_str = f"{r.get('score', 0)}/100"
        if liq.get("has_sweep"):
            liq_short = "🧲 Barrido Stops"
        elif liq.get("has_absorption"):
            liq_short = "🐋 Absorción Inst."
        elif abs(liq.get("poc_dist_pct", 99)) <= 2.2:
            liq_short = "🏦 En Muro POC"
        elif liq.get("fib_poc_confluence", {}).get("has_confluence"):
            fpc = liq["fib_poc_confluence"]
            tag_name = "POC" if fpc.get("is_poc") else "HVN"
            liq_short = f"🏦 {tag_name} en {fpc['level']}"
        else:
            liq_short = f"💧 Liq {liq.get('liquidity_score', 0)}/100"
        print(f"{r['tab']:<10} {r['ticker']:<9} {curr_str:>11} {drop_str:>8} {rsi_str:>5} {poc_str:>11} {rvol_str:>7} {score_str:>7} {liq_short:<20} {r.get('confluence_rating', ''):<20}")

    print("=" * 134)

def run_updater(target_period=None, sync_sheets=True, custom_webhook=None):
    with SYNC_LOCK:
        t0 = time.perf_counter()
        config = load_config()
        period = target_period or config.get("period", "3mo")
        webhook_url = custom_webhook or config.get("webhook_url", "").strip()
        assets_list = config.get("assets", [])

        now = datetime.datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        previous = {}
        previous_timestamp = None
        if os.path.exists(LATEST_DATA_PATH):
            try:
                with open(LATEST_DATA_PATH, encoding="utf-8") as f:
                    cached = json.load(f)
                previous_timestamp = cached.get("timestamp")
                previous = {it["ticker"]: it for it in cached.get("data", [])}
            except (OSError, ValueError, KeyError, TypeError):
                pass

        print(f"\n🚀 Iniciando sincronización paralela de {len(assets_list)} activos (Periodo: {period})...")

        def _fetch_worker(idx_and_asset):
            idx, asset_item = idx_and_asset
            try:
                data, hist = fetch_asset_data(asset_item, period=period, return_history=True, quiet=True)
                price = float(data.get("current_price", 0)) if data else 0
                if not math.isfinite(price) or price <= 0:
                    raise ValueError("Cotización no válida")
                data.update(is_stale=False, last_success_at=timestamp)
                return idx, data, hist
            except Exception as err:
                print(f"  ❌ Error consultando {asset_item.get('ticker')}: {err}")
                return idx, None, None

        max_workers = min(8, max(2, len(assets_list) + 1))
        ordered_results = []
        histories_by_ticker = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            sentiment_future = executor.submit(fetch_cnn_fear_and_greed)
            asset_futures = [executor.submit(_fetch_worker, (i, a)) for i, a in enumerate(assets_list)]

            collected = []
            failed_tickers = []
            for fut in concurrent.futures.as_completed(asset_futures):
                idx, data, hist = fut.result()
                if data:
                    collected.append((idx, data))
                    if hist is not None and not hist.empty:
                        histories_by_ticker[data["ticker"]] = hist
                else:
                    ticker = assets_list[idx]["ticker"]
                    failed_tickers.append(ticker)
                    old = previous.get(ticker)
                    if old and isinstance(old.get("current_price"), (int, float)) and math.isfinite(old["current_price"]) and old["current_price"] > 0:
                        fallback = dict(old)
                        fallback.update(old.get("timeframes", {}).get(period, {}))
                        fallback.update(is_stale=True, last_success_at=old.get("last_success_at") or previous_timestamp)
                        collected.append((idx, fallback))

            sentiment = sentiment_future.result()

        collected.sort(key=lambda pair: pair[0])
        results = [item for _, item in collected]
        elapsed_fetch = time.perf_counter() - t0
        print(f"  ⚡ Descarga paralela completada en {elapsed_fetch:.2f}s | 🌡️ Sentimiento CNN: {sentiment.get('score', 50)}/100 ({sentiment.get('rating_es', 'Neutral')}) {sentiment.get('icon', '')}")

        # Imprimir reporte en consola
        print_summary_table(results, period, timestamp, sentiment=sentiment)

        # Guardar localmente de forma atómica
        payload = {
            "timestamp": timestamp,
            "period": period,
            "market_sentiment": sentiment,
            "market_hours": evaluate_market_hours(assets_list, now),
            "failed_tickers": failed_tickers,
            "data": results
        }
        _atomic_write_json(LATEST_DATA_PATH, payload)

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
                    data=json.dumps({**payload, "data": [it for it in results if not it.get("is_stale")]}),
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

        # Sincronizar Historial de Oportunidades y Diario de Trading (Módulo 3)
        journal_updated = False
        try:
            import journal_manager
            journal_manager.update_journal_with_market_data([it for it in results if not it.get("is_stale")], histories=histories_by_ticker)
            journal_updated = True
        except Exception as e:
            print(f"⚠️ [Journal] Error actualizando diario de trading: {e}")

        # Enviar alertas a Telegram si está configurado
        try:
            import telegram_notifier
            if journal_updated:
                telegram_notifier.dispatch_telegram_alerts({**payload, "data": [it for it in results if not it.get("is_stale")]}, config)
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
