"""
journal_manager.py
Módulo de gestión del Historial de Oportunidades y Diario de Trading Automático.
Registra entradas tras vigilancia y confirmación de estructura, conserva el historial
y simula por separado acumulación por tramos con presupuesto limitado.
"""

import os
import json
import time
import threading
import math
from functools import wraps
from datetime import datetime

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
JOURNAL_PATH = os.path.join(DIRECTORY, "journal.json")
_JOURNAL_LOCK = threading.RLock()


def _locked(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _JOURNAL_LOCK:
            return function(*args, **kwargs)
    return wrapped

def load_journal():
    """
    Carga el historial de oportunidades desde journal.json.
    Si no existe, inicializa con estructura vacía.
    """
    if not os.path.exists(JOURNAL_PATH):
        empty_journal = {
            "version": "1.0",
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stats": {
                "total_opportunities": 0,
                "active_count": 0,
                "closed_count": 0,
                "win_rate_pct": 0.0,
                "total_won": 0,
                "total_lost": 0,
                "avg_win_pct": 0.0,
                "avg_loss_pct": 0.0
            },
            "entries": []
        }
        save_journal(empty_journal)
        return empty_journal

    try:
        with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Journal Manager] Error al leer journal.json: {e}")
        return {"version": "1.0", "stats": {}, "entries": []}

def get_tracking_signal(ticker):
    """Consulta sin modificar el historial; una señal abierta tiene prioridad."""
    if not os.path.exists(JOURNAL_PATH):
        return {"entry": None, "is_active": False}
    try:
        with open(JOURNAL_PATH, encoding="utf-8") as handle:
            journal = json.load(handle)
        entries = journal["entries"]
        if not isinstance(entries, list):
            raise ValueError("Historial incorrecto")
        matches = [entry for entry in entries if isinstance(entry, dict)
                   and str(entry.get("ticker", "")).upper() == str(ticker).upper()]
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("No se puede consultar el seguimiento del Diario. El historial se conserva sin modificar.") from None
    active = [entry for entry in matches if entry.get("status") in ("ACTIVA", "TP1_ALCANZADO")]
    selected = max(active or matches, key=lambda entry: str(entry.get("signal_date", "")), default=None)
    return {"entry": selected, "is_active": bool(active)}


def get_scenario_context(ticker):
    """Consulta sin escrituras del mismo estado que consume el panel."""
    if not os.path.exists(JOURNAL_PATH):
        return {"confirmation": None, "accumulation": None, "watch": None}
    with open(JOURNAL_PATH, encoding="utf-8") as handle:
        data = json.load(handle)
    ticker = str(ticker).upper()
    matches = [e for e in data.get("entries", []) if str(e.get("ticker", "")).upper() == ticker
               and e.get("strategy") == "confirmation" and e.get("status") in ("ACTIVA", "TP1_ALCANZADO")]
    campaigns = [c for c in data.get("accumulation", []) if str(c.get("ticker", "")).upper() == ticker and c.get("status") == "ACTIVA"]
    return {"confirmation": max(matches, key=lambda e: e.get("signal_date", ""), default=None),
            "accumulation": campaigns[0] if campaigns else None,
            "watch": data.get("watches", {}).get(ticker)}


def save_journal(data):
    """
    Guarda el historial de oportunidades en journal.json de manera atómica.
    """
    temp_file = f"{JOURNAL_PATH}.{os.getpid()}.tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_file, JOURNAL_PATH)
        return True
    except Exception as e:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass
        print(f"[Journal Manager] Error al guardar journal.json: {e}")
        return False


def calculate_journal_stats(entries):
    """
    Calcula métricas clave de rendimiento: Tasa de acierto positiva (Win Rate),
    tasa de fallo/pérdida negativa (Loss Rate), operaciones ganadas/perdidas y retornos medios.
    """
    total = len(entries)
    active = [e for e in entries if e.get("status") in ("ACTIVA", "TP1_ALCANZADO")]
    closed = [
        e for e in entries
        if e.get("status") in ("TP2_ALCANZADO", "STOP_EJECUTADO", "BREAKEVEN_EJECUTADO", "CERRADA_MANUAL")
    ]

    won = [e for e in closed if e.get("result") == "GANADA"]
    lost = [e for e in closed if e.get("result") == "PERDIDA"]

    win_rate = round((len(won) / len(closed)) * 100, 1) if closed else 0.0
    loss_rate = round((len(lost) / len(closed)) * 100, 1) if closed else 0.0
    net_win_rate = round(win_rate - loss_rate, 1) if closed else 0.0

    win_returns = [e.get("final_return_pct", 0) for e in won if e.get("final_return_pct") is not None]
    loss_returns = [e.get("final_return_pct", 0) for e in lost if e.get("final_return_pct") is not None]

    avg_win = round(sum(win_returns) / len(win_returns), 2) if win_returns else 0.0
    avg_loss = round(sum(loss_returns) / len(loss_returns), 2) if loss_returns else 0.0

    return {
        "total_opportunities": total,
        "active_count": len(active),
        "closed_count": len(closed),
        "win_rate_pct": win_rate,
        "loss_rate_pct": loss_rate,
        "net_win_rate_pct": net_win_rate,
        "total_won": len(won),
        "total_lost": len(lost),
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss
    }


def journal_view(journal):
    """Estadísticas por escenario al leer, también después de archivar o borrar."""
    result = dict(journal)
    entries = journal.get("entries", [])
    result["scenario_stats"] = {name: calculate_journal_stats([e for e in entries if e.get("strategy", "legacy") == name])
                                for name in ("legacy", "confirmation")}
    return result


@_locked
def archive_journal_entries(entry_ids=None, clear_closed=False, archived=True):
    """Oculta/restaura cierres sin excluirlos de las estadísticas."""
    if not isinstance(archived, bool) or not isinstance(clear_closed, bool):
        raise ValueError("Acción de archivo incorrecta")
    if not clear_closed and (not isinstance(entry_ids, list) or not entry_ids):
        raise ValueError("Selecciona las señales que quieres archivar o restaurar")
    journal = load_journal()
    ids = {str(value) for value in (entry_ids or [])}
    changed_ids = []
    for entry in journal.get("entries", []):
        if entry.get("status") in ("ACTIVA", "TP1_ALCANZADO"):
            continue
        if (clear_closed or str(entry.get("id")) in ids) and bool(entry.get("archived")) != archived:
            entry["archived"] = archived
            changed_ids.append(str(entry["id"]))
    journal["stats"] = calculate_journal_stats(journal.get("entries", []))
    journal["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not save_journal(journal):
        raise OSError("No se pudo guardar el Diario")
    return {"journal": journal, "changed_ids": changed_ids}


@_locked
def remove_journal_entry(entry_id=None, clear_closed=False):
    """
    Elimina una oportunidad del diario por ID o limpia todas las cerradas.
    Recalcula las estadísticas de acierto/pérdida de forma atómica.
    """
    journal = load_journal()
    entries = journal.get("entries", [])

    if clear_closed:
        entries = [e for e in entries if e.get("status") in ("ACTIVA", "TP1_ALCANZADO")]
    elif entry_id:
        entries = [e for e in entries if str(e.get("id")) != str(entry_id)
                   or e.get("status") in ("ACTIVA", "TP1_ALCANZADO")]

    journal["entries"] = entries
    journal["stats"] = calculate_journal_stats(entries)
    journal["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not save_journal(journal):
        raise OSError("No se pudo guardar el Diario")
    return journal


def _evaluate_price_point(trade, high_p, low_p, close_p, event_date_str):
    """
    Evalúa la evolución de una operación abierta frente a un rango de precios (High, Low, Close).
    Simula vender el 50% en TP1 y el resto en TP2 o Break-Even.
    """
    if trade.get("status") not in ("ACTIVA", "TP1_ALCANZADO"):
        return

    dec = int(trade.get("decimals", 2))
    curr_sym = trade.get("currency", "$")
    entry_p = float(trade.get("entry_price", close_p))
    sl = float(trade.get("stop_loss", round(entry_p * 0.95, dec)))
    tp1 = float(trade.get("tp1", round(entry_p * 1.05, dec)))
    tp2 = float(trade.get("tp2", round(entry_p * 1.15, dec)))

    # Si ya estaba en TP1_ALCANZADO de sesiones previas, asegurar que el Stop Loss esté en Break-Even
    if trade.get("status") == "TP1_ALCANZADO" and sl < entry_p:
        trade.setdefault("initial_stop_loss", round(sl, dec))
        sl = round(entry_p, dec)
        trade["stop_loss"] = sl

    max_seen = max(float(trade.get("max_price_seen", close_p)), high_p, close_p)
    min_seen = min(float(trade.get("min_price_seen", close_p)), low_p, close_p)
    trade["max_price_seen"] = round(max_seen, dec)
    trade["min_price_seen"] = round(min_seen, dec)
    if trade.get("strategy") == "confirmation":
        trade["max_drawdown_pct"] = round(min(trade.get("max_drawdown_pct", 0), (low_p / max_seen - 1) * 100), 2)
    trade["max_return_pct"] = round(((max_seen - entry_p) / entry_p) * 100, 2) if entry_p > 0 else 0.0

    # Evaluación conservadora: comprobar primero Stop Loss / Break-Even
    if low_p <= sl:
        if trade.get("status") == "TP1_ALCANZADO":
            tp1_ret = round(((tp1 - entry_p) / entry_p) * 100, 2) if entry_p > 0 else 0.0
            realized_ret = round(max(0.0, tp1_ret * 0.5), 2)
            trade["status"] = "BREAKEVEN_EJECUTADO"
            trade["result"] = "GANADA"
            trade["closed_date"] = event_date_str
            trade["final_return_pct"] = realized_ret
            trade["current_return_pct"] = realized_ret
            trade["exit_reason"] = (
                f"TP 1 asegurado (+{tp1_ret:.1f}% parcial) y resto cerrado en Break-Even ({curr_sym}{entry_p:,.{dec}f}) sin pérdidas"
            )
        else:
            sl_ret = round(((sl - entry_p) / entry_p) * 100, 2) if entry_p > 0 else 0.0
            trade["status"] = "STOP_EJECUTADO"
            trade["result"] = "PERDIDA"
            trade["closed_date"] = event_date_str
            trade["final_return_pct"] = sl_ret
            trade["current_return_pct"] = sl_ret
            trade["exit_reason"] = f"Stop Loss alcanzado en {curr_sym}{sl:,.{dec}f} para acotar riesgo"
        return

    if high_p >= tp2:
        # Incluso si ambos objetivos se cruzan en una sola vela, la primera
        # mitad sale en TP1. Ponderar antes de redondear el resultado final.
        realized_ret = round((((tp1 + tp2) / 2 - entry_p) / entry_p) * 100, 2) if entry_p > 0 else 0.0
        trade.setdefault("tp1_hit_date", event_date_str)
        trade["status"] = "TP2_ALCANZADO"
        trade["result"] = "GANADA"
        trade["closed_date"] = event_date_str
        trade["final_return_pct"] = realized_ret
        trade["current_return_pct"] = realized_ret
        trade["exit_reason"] = (
            f"50% cerrado en TP 1 ({curr_sym}{tp1:,.{dec}f}) y 50% en TP 2 "
            f"({curr_sym}{tp2:,.{dec}f}); retorno combinado {realized_ret:+.2f}%"
        )
        return

    if high_p >= tp1 and trade.get("status") == "ACTIVA":
        trade["status"] = "TP1_ALCANZADO"
        trade["tp1_hit_date"] = event_date_str
        trade.setdefault("initial_stop_loss", round(sl, dec))
        trade["stop_loss"] = round(entry_p, dec)
        trade["advice"] = "TP 1 alcanzado. Stop Loss movido automáticamente a Precio de Entrada (Break-Even) para riesgo cero."


@_locked
def update_journal_with_market_data(market_data_list, histories=None):
    """
    Sincroniza el diario de trading:
    1. Activa vigilancia en zona Fibonacci o score >= 70; entra tras confirmación y filtro de riesgo.
    2. Actualiza el progreso de las operaciones activas revisando velas ocurridas desde la señal y precio actual.
    """
    journal = load_journal()
    entries = journal.get("entries", [])
    now_dt = datetime.now()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    today_day = now_dt.strftime("%Y-%m-%d")
    import scenario_engine

    # Mantener referencias a las operaciones: insertar señales al principio
    # de entries desplaza los índices, pero no cambia estos objetos.
    active_by_ticker = {}
    for e in entries:
        if e.get("status") in ("ACTIVA", "TP1_ALCANZADO"):
            active_by_ticker.setdefault(e.get("ticker"), []).append(e)

    for item in market_data_list:
        ticker = item.get("ticker")
        current_price = float(item.get("current_price", 0))
        if not math.isfinite(current_price) or current_price <= 0 or item.get("is_stale"):
            continue

        dec = int(item.get("decimals", 2))
        curr_sym = item.get("currency", "$")

        # Caso A: El activo ya tiene una oportunidad abierta en seguimiento
        for trade in active_by_ticker.get(ticker, []):
            trade.setdefault("currency", curr_sym)
            trade.setdefault("decimals", dec)
            t_dec = int(trade.get("decimals", dec))
            entry_p = float(trade.get("entry_price", current_price))
            signal_day = str(trade.get("signal_date", ""))[:10] or today_day
            last_checked_day = str(trade.get("last_checked_candle_day") or signal_day)[:10]

            # 1. Revisar velas diarias posteriores al día de la señal si el equipo estuvo apagado varios días
            hist = histories.get(ticker) if isinstance(histories, dict) else None
            if hist is not None and not hist.empty:
                for bar_ts, row in hist.iterrows():
                    bar_day = bar_ts.strftime("%Y-%m-%d")
                    if bar_day <= signal_day:
                        continue
                    bar_high = float(row["High"])
                    bar_low = float(row["Low"])
                    bar_close = float(row["Close"])

                    if bar_day < today_day and bar_day > last_checked_day:
                        _evaluate_price_point(trade, bar_high, bar_low, bar_close, f"{bar_day} 22:00:00")
                        trade["last_checked_candle_day"] = bar_day
                    elif bar_day >= today_day and today_day > signal_day:
                        # En un día posterior a la señal, todo el rango intradía de hoy ocurrió tras la entrada
                        _evaluate_price_point(trade, bar_high, bar_low, current_price, now_str)

                    if trade.get("status") not in ("ACTIVA", "TP1_ALCANZADO"):
                        break

            # 2. Evaluar también la cotización puntual actual
            if trade.get("status") in ("ACTIVA", "TP1_ALCANZADO"):
                _evaluate_price_point(trade, current_price, current_price, current_price, now_str)

            trade["current_price"] = round(current_price, t_dec)
            if trade.get("status") in ("ACTIVA", "TP1_ALCANZADO"):
                valued_price = (float(trade["tp1"]) + current_price) / 2 if trade["status"] == "TP1_ALCANZADO" else current_price
                curr_ret = round(((valued_price - entry_p) / entry_p) * 100, 2) if entry_p > 0 else 0.0
                trade["current_return_pct"] = curr_ret
            trade["last_check"] = now_str

    # Evaluar cierres antes de decidir entradas: un stop de este ciclo ya bloquea reentrada.
    allowed = scenario_engine.advance(journal, market_data_list, histories, now_str)
    for item in market_data_list:
        ticker = item.get("ticker")
        current_price = float(item.get("current_price", 0))
        if not math.isfinite(current_price) or current_price <= 0 or item.get("is_stale"):
            continue
        fibs = item.get("fib_levels", {})
        score = item.get("score", 0)
        risk = item.get("risk_mgmt", {})
        dec = int(item.get("decimals", 2))
        curr_sym = item.get("currency", "$")

        # Cada escenario mantiene una sola posición abierta por ticker.
        if ticker in allowed and not any(e.get("strategy") == "confirmation" or e.get("status") == "STOP_EJECUTADO"
                                         for e in active_by_ticker.get(ticker, [])):
            # La entrada de una oportunidad activa siempre se registra al precio real de mercado en el momento de la señal
            entry_p = round(current_price, dec)
            default_sl = round(
                min(fibs.get("78.6%", entry_p * 0.95) * 0.98, item.get("min", entry_p) * 0.985),
                dec
            )

            raw_sl = float(risk.get("stop_loss", default_sl))
            sl = round(raw_sl if raw_sl < entry_p else entry_p * 0.96, dec)

            # Riesgo calculado desde la entrada efectiva y objetivos estructurales.
            atr = float(item.get("atr_14") or risk.get("atr_14") or 0)
            structural_target = float(fibs.get("38.2%") or 0)
            structural_high = float(item.get("max") or 0)
            if (not all(math.isfinite(value) for value in (atr, sl, structural_target, structural_high))
                    or atr <= 0 or structural_target <= entry_p or structural_high <= structural_target):
                continue
            sl = round(min(sl, entry_p - 2 * atr), dec)
            tp1, tp2 = round(structural_target, dec), round(structural_high, dec)
            if sl <= 0 or (tp1 - entry_p) / (entry_p - sl) < 1.5:
                continue
            rr_ratio = round((tp2 - entry_p) / (entry_p - sl), 2)
            signal_type = "CONFIRMACION"
            signal_label = f"Recuperación confirmada · Score {score}/100"

            new_entry = {
                "id": f"opp_{ticker}_{int(time.time())}",
                "strategy": "confirmation",
                "confirmation_level": journal.get("watches", {}).get(ticker, {}).get("breakout"),
                "confirmation_closes": journal.get("watches", {}).get(ticker, {}).get("confirmations", 0),
                "simulated_budget": 1000,
                "max_drawdown_pct": 0,
                "ticker": ticker,
                "tab": item.get("tab", ticker),
                "name": item.get("name", ticker),
                "currency": curr_sym,
                "decimals": dec,
                "signal_date": now_str,
                "signal_type": signal_type,
                "signal_label": signal_label,
                "period": item.get("period"),
                "stop_method": "ESTRUCTURAL_ATR",
                "score": score,
                "rsi": item.get("rsi"),
                "entry_price": entry_p,
                "initial_stop_loss": sl,
                "stop_loss": sl,
                "tp1": tp1,
                "tp2": tp2,
                "rr_ratio": rr_ratio,
                "current_price": round(current_price, dec),
                "max_price_seen": round(current_price, dec),
                "min_price_seen": round(current_price, dec),
                "current_return_pct": 0.0,
                "max_return_pct": 0.0,
                "status": "ACTIVA",
                "result": "EN_CURSO",
                "closed_date": None,
                "final_return_pct": None,
                "exit_reason": None,
                "last_checked_candle_day": today_day,
                "last_check": now_str
            }
            entries.insert(0, new_entry)  # Más reciente primero
            active_by_ticker.setdefault(ticker, []).append(new_entry)
            journal.get("watches", {}).pop(ticker, None)

    journal["entries"] = entries
    journal["stats"] = calculate_journal_stats(entries)
    journal["scenario_stats"] = {name: calculate_journal_stats([e for e in entries if e.get("strategy", "legacy") == name])
                                 for name in ("legacy", "confirmation")}
    journal["last_updated"] = now_str
    if not save_journal(journal):
        raise OSError("No se pudo guardar la actualización del Diario")
    return journal
