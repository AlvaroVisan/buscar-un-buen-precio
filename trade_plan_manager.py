"""Planes elegidos por el usuario: niveles inmutables y seguimiento simulado."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import os
import threading
import uuid

import yfinance as yf
from journal_manager import _evaluate_price_point

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
PLANS_PATH = os.path.join(DIRECTORY, ".trade_plans.json")
ACTIVE = ("PENDIENTE_ENTRADA", "ACTIVA", "TP1_ALCANZADO")
_lock = threading.RLock()


def utc_now():
    return datetime.now(timezone.utc)


def _date(value):
    date = datetime.fromisoformat(str(value))
    return date.astimezone(timezone.utc)


def _positive(value):
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise ValueError("El plan no tiene niveles válidos.") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError("El plan no tiene niveles válidos.")
    return value


def _load():
    if not os.path.exists(PLANS_PATH):
        return {"offers": {}, "plans": []}
    try:
        with open(PLANS_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data.get("offers"), dict) or not isinstance(data.get("plans"), list):
            raise ValueError("Estructura incorrecta")
        return data
    except (OSError, ValueError, AttributeError):
        raise ValueError("No se puede leer el archivo de planes. Se conserva sin sobrescribirlo.") from None


def _save(data):
    temporary = f"{PLANS_PATH}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, allow_nan=False, indent=2)
        os.replace(temporary, PLANS_PATH)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def proposal(item, period=None):
    """La misma entrada, stop SSL preferente y objetivos que muestra el bot."""
    if item.get("is_stale"):
        raise ValueError("La cotización está desactualizada. Actualiza antes de guardar un plan.")
    risk = item.get("risk_mgmt") or {}
    entry = _positive(risk.get("entry_price") or item.get("current_price"))
    stop = _positive(risk.get("ssl_stop_loss") or risk.get("stop_loss"))
    tp1 = _positive(risk.get("take_profit_1"))
    tp2 = _positive(risk.get("take_profit_2"))
    if not stop < entry < tp1 <= tp2:
        raise ValueError("El plan necesita stop < entrada < TP1 ≤ TP2.")
    return {
        "ticker": str(item["ticker"]), "tab": item.get("tab", item["ticker"]),
        "name": item.get("name", item["ticker"]), "currency": item.get("currency", "$"),
        "decimals": max(0, min(8, int(item.get("decimals", 2)))),
        "period": period or item.get("period", "3mo"), "score": item.get("score"),
        "quote_at": item.get("last_success_at") or item.get("quote_at"),
        "quoted_price": _positive(item.get("current_price")),
        "entry_type": risk.get("entry_type", "MARKET"),
        "stop_method": "SSL" if risk.get("ssl_stop_loss") else "ESTRUCTURAL",
        "levels": {"entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2},
    }


def create_offer(item, chat_id, period=None):
    offer = proposal(item, period)
    offer.update(id=uuid.uuid4().hex[:20], owner=str(chat_id), proposed_at=utc_now().isoformat())
    with _lock:
        data = _load()
        cutoff = utc_now() - timedelta(days=30)
        data["offers"] = {key: value for key, value in data["offers"].items()
                          if _date(value["proposed_at"]) >= cutoff or value.get("plan_id")}
        data["offers"][offer["id"]] = offer
        _save(data)
    return deepcopy(offer)


def follow_offer(offer_id, chat_id, current_item=None):
    """Idempotente; no reemplaza un plan activo ni lee niveles del mercado nuevo."""
    with _lock:
        data = _load()
        offer = data["offers"].get(offer_id)
        if not offer or offer.get("owner") != str(chat_id):
            raise ValueError("Este botón no está disponible para este chat. Pide un análisis nuevo.")
        if offer.get("plan_id"):
            return deepcopy(next(plan for plan in data["plans"] if plan["id"] == offer["plan_id"])), False
        if _date(offer["proposed_at"]) < utc_now() - timedelta(days=30):
            raise ValueError("Esta propuesta ha caducado. Pide un análisis nuevo antes de seguirla.")
        existing = next((plan for plan in data["plans"] if plan["owner"] == str(chat_id)
                         and plan["ticker"] == offer["ticker"] and plan["status"] in ACTIVE), None)
        if existing:
            offer["plan_id"] = existing["id"]
            _save(data)
            return deepcopy(existing), False
        now = utc_now().isoformat()
        levels = offer["levels"]
        plan = {key: deepcopy(value) for key, value in offer.items() if key not in ("id", "plan_id")}
        plan.update(
            id=uuid.uuid4().hex[:20], saved_at=now, signal_date=now, tracking_since=now,
            entry_price=levels["entry"], initial_stop_loss=levels["stop"], stop_loss=levels["stop"],
            tp1=levels["tp1"], tp2=levels["tp2"], current_price=offer["quoted_price"],
            status="PENDIENTE_ENTRADA" if offer["entry_type"] != "MARKET" else "ACTIVA",
            result="EN_CURSO", current_return_pct=0.0, final_return_pct=None,
            max_price_seen=levels["entry"], min_price_seen=levels["entry"], max_return_pct=0.0,
            last_check=None, closed_date=None, quote_stale=True,
            coverage_note="Seguimiento simulado desde el guardado. No evalúa movimientos anteriores ni registra una compra real.",
        )
        if isinstance(current_item, list):
            current_item = next((item for item in current_item if item.get("ticker") == plan["ticker"]), None)
        if current_item and current_item.get("ticker") == plan["ticker"] and not current_item.get("is_stale"):
            price = _positive(current_item.get("current_price"))
            quote_at = current_item.get("last_success_at")
            observed = _date(quote_at).isoformat() if quote_at else now
            if _date(observed) >= _date(now):
                _observe(plan, price, price, price, observed)
                plan["last_observed_at"] = observed
                plan["quote_stale"] = False
        data["plans"].insert(0, plan)
        offer["plan_id"] = plan["id"]
        _save(data)
        return deepcopy(plan), True


def _observe(plan, high, low, close, observed_at, candle=False):
    if plan["status"] not in ACTIVE:
        return
    if plan["status"] == "PENDIENTE_ENTRADA":
        if low <= plan["initial_stop_loss"]:
            plan.update(status="INVALIDADA_SIN_ENTRADA", result="SIN_OPERACION", closed_date=observed_at)
        elif low <= plan["entry_price"]:
            plan.update(status="ACTIVA", entry_observed_at=observed_at)
            # No atribuir un máximo de la vela que pudo ocurrir antes de la entrada.
        plan.update(current_price=close, last_check=observed_at)
        return

    # Si una vela alcanza objetivo y stop, su orden es desconocido. Elegir el
    # resultado conservador y explicarlo, nunca reconstruir una secuencia favorable.
    if candle and plan["status"] == "ACTIVA" and high >= plan["tp1"] and low <= plan["entry_price"]:
        plan["ambiguity_note"] = "Una vela tocó varios niveles sin orden conocido; se aplicó el resultado conservador."
        if low > plan["stop_loss"]:
            _evaluate_price_point(plan, plan["tp1"], plan["entry_price"] + 1e-8, plan["tp1"], observed_at)
            _evaluate_price_point(plan, plan["entry_price"], plan["entry_price"], plan["entry_price"], observed_at)
        else:
            _evaluate_price_point(plan, high, low, close, observed_at)
    else:
        if candle and low <= plan["stop_loss"] and high >= plan["tp1"]:
            plan["ambiguity_note"] = "Una vela tocó stop y objetivo sin orden conocido; se aplicó el stop primero."
        _evaluate_price_point(plan, high, low, close, observed_at)
    if plan["status"] in ("ACTIVA", "TP1_ALCANZADO"):
        valued = (plan["tp1"] + close) / 2 if plan["status"] == "TP1_ALCANZADO" else close
        plan["current_return_pct"] = round((valued / plan["entry_price"] - 1) * 100, 2)
    plan.update(current_price=close, last_check=observed_at)


def update_followed_plans(items, histories=None):
    """Consulta velas de 5m solo para activos con planes abiertos; nunca velas previas al guardado."""
    with _lock:
        active = [deepcopy(plan) for plan in _load()["plans"] if plan["status"] in ACTIVE]
    if not active:
        return
    quotes = {item["ticker"]: item for item in items if not item.get("is_stale")}
    frames = dict(histories or {})
    for ticker in {plan["ticker"] for plan in active}:
        if ticker not in frames:
            try:
                frames[ticker] = yf.Ticker(ticker).history(period="1mo", interval="5m", auto_adjust=True, timeout=15)
            except Exception:
                frames[ticker] = None
    now = utc_now()
    with _lock:
        data = _load()
        for plan in data["plans"]:
            if plan["status"] not in ACTIVE:
                continue
            since = _date(plan["tracking_since"])
            plan["quote_stale"] = True
            frame = frames.get(plan["ticker"])
            has_candles = frame is not None and not frame.empty
            plan["coverage_note"] = "Cotizaciones y velas completas de 5 minutos posteriores al guardado; se omiten las velas parciales que solapan observaciones previas. Pueden faltar toques en esos tramos. Sin comisiones ni garantía de ejecución real."
            if has_candles:
                if _date(frame.index[0].isoformat()) > since + timedelta(days=7):
                    plan["coverage_note"] += " Hay un tramo anterior sin cobertura intradía; el resultado puede estar incompleto."
                for bar_at, row in frame.sort_index().iterrows():
                    start = _date(bar_at.isoformat())
                    end = start + timedelta(minutes=5)
                    if start < since or end > now:
                        continue
                    # Las observaciones puntuales ya procesadas nunca se revisan con
                    # el rango completo de una vela que había empezado antes de ellas.
                    if plan.get("last_observed_at") and start < _date(plan["last_observed_at"]):
                        continue
                    try:
                        high, low, close = (_positive(row[key]) for key in ("High", "Low", "Close"))
                    except ValueError:
                        continue
                    _observe(plan, high, low, close, end.isoformat(), candle=True)
                    plan["last_observed_at"] = end.isoformat()
                    plan["quote_stale"] = False
                    if plan["status"] not in ACTIVE:
                        break
            else:
                plan["coverage_note"] += " No se han podido recuperar las velas; pueden faltar toques entre consultas."
            quote = quotes.get(plan["ticker"])
            if quote and plan["status"] in ACTIVE:
                price = _positive(quote.get("current_price"))
                observed = _date(quote["last_success_at"]) if quote.get("last_success_at") else now
                if observed >= since:
                    if not plan.get("last_observed_at") or observed > _date(plan["last_observed_at"]):
                        _observe(plan, price, price, price, observed.isoformat())
                        plan["last_observed_at"] = observed.isoformat()
                    plan["quote_stale"] = now - observed > timedelta(hours=1)
            elif not has_candles and plan["status"] in ACTIVE:
                plan["quote_stale"] = True
        _save(data)


def get_plans(chat_id=None):
    with _lock:
        plans = deepcopy(_load()["plans"])
    if chat_id is not None:
        plans = [plan for plan in plans if plan["owner"] == str(chat_id)]
    for plan in plans:
        plan.pop("owner", None)
    closed = [p for p in plans if p.get("result") in ("GANADA", "PERDIDA")]
    won = sum(p.get("result") == "GANADA" for p in closed)
    return {"plans": plans, "stats": {
        "total": len(plans), "active": sum(p["status"] in ACTIVE for p in plans),
        "closed": len(closed), "won": won, "lost": len(closed) - won,
        "win_rate_pct": round(100 * won / len(closed), 1) if closed else 0.0,
    }}


def cancel_plan(plan_id, chat_id):
    with _lock:
        data = _load()
        plan = next((p for p in data["plans"] if p["id"] == plan_id and p["owner"] == str(chat_id)), None)
        if not plan:
            raise ValueError("No se encuentra este plan en tu seguimiento.")
        if plan["status"] in ACTIVE:
            plan.update(status="CANCELADA", result="CANCELADA", closed_date=utc_now().isoformat(), final_return_pct=None)
            _save(data)
        return deepcopy(plan)
