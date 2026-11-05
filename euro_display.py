"""Conversión de presentación para Telegram; los registros siguen en su divisa."""
import json
import math
import os
import re
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests

CACHE_PATH = Path(__file__).with_name(".exchange_cache.local.json")
RATE_URL = "https://api.frankfurter.dev/v2/providers/ecb/rate/eur/usd"
_lock = threading.RLock()
_quote = None
_fetched_at = 0
_last_attempt = 0
_MONEY = re.compile(r"(?P<currency>[$€])(?P<amount>-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)")


def native_inputs(values, currency, rate):
    """Deshace exactamente el cambio con el que se rellenó el formulario web."""
    if currency in ("€", "EUR"):
        factor = 1
    elif currency in ("$", "USD") and isinstance(rate, (float, int)) and not isinstance(rate, bool) and math.isfinite(rate) and rate > 0:
        factor = rate
    else:
        raise ValueError("No hay un cambio válido para guardar precios en euros")
    result = []
    for value in values:
        if value in (None, ""):
            result.append(None)
        elif isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value):
            result.append(value * factor)
        else:
            raise ValueError("El precio debe ser un número finito")
    return result


def _valid(quote):
    try:
        stamp = date.fromisoformat(quote["date"])
        age = (datetime.now(timezone.utc).date() - stamp).days
        return (quote.get("base") == "EUR" and quote.get("quote") == "USD"
                and isinstance(quote["rate"], (int, float)) and not isinstance(quote["rate"], bool)
                and math.isfinite(quote["rate"]) and quote["rate"] > 0 and 0 <= age <= 7)
    except (ValueError, TypeError, KeyError):
        return False


def get_quote():
    """USD por EUR, caché de seis horas y reintento limitado en fallos de red."""
    global _quote, _fetched_at, _last_attempt
    with _lock:
        now = time.time()
        if _quote is None:
            try:
                saved = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
                if _valid(saved):
                    _quote = saved
                    _fetched_at = float(saved.get("fetched_at", 0))
            except (OSError, ValueError, TypeError):
                pass
        if _valid(_quote) and 0 <= now - _fetched_at < 6 * 3600:
            return dict(_quote)
        if 0 <= now - _last_attempt < 60:
            return dict(_quote) if _valid(_quote) else None
        _last_attempt = now
        try:
            response = requests.get(RATE_URL, timeout=6)
            response.raise_for_status()
            quote = response.json()
            if not _valid(quote):
                raise ValueError("Cambio de referencia incorrecto")
            _quote = {key: quote[key] for key in ("base", "quote", "date", "rate")}
            _fetched_at = now
            temporary = CACHE_PATH.with_suffix(".tmp")
            try:
                temporary.write_text(json.dumps({**_quote, "fetched_at": now}), encoding="utf-8")
                os.replace(temporary, CACHE_PATH)
            except OSError:
                pass
        except (requests.RequestException, ValueError, TypeError, KeyError):
            pass
        return dict(_quote) if _valid(_quote) else None


def render_message(text):
    """Un solo cambio para todo el mensaje; solo convierte tokens monetarios."""
    matches = list(_MONEY.finditer(text))
    if not matches:
        return text
    needs_rate = any(match["currency"] == "$" for match in matches)
    quote = get_quote() if needs_rate else None
    if needs_rate and quote is None:
        return text + "\n\nNo pude consultar el cambio a euros; estos importes siguen en su moneda original."

    def convert(match):
        raw = match["amount"]
        number = float(raw.replace(",", ""))
        if match["currency"] == "$":
            number /= quote["rate"]
        decimals = max(2, min(8, len(raw.rsplit(".", 1)[1]) if "." in raw else 2))
        formatted = f"{number:,.{decimals}f}".translate(str.maketrans({",": ".", ".": ","}))
        return formatted + " €"

    result = _MONEY.sub(convert, text).replace("Balance ($)", "Balance (USD en euros)")
    if needs_rate:
        result += f"\n\nEuros aproximados · cambio de referencia del {quote['date']}. Porcentajes en la moneda original."
        if "MI CARTERA" in text:
            result += " El beneficio convertido usa este cambio, no el de cada compra o venta."
    return result
