"""
journal_manager.py
Módulo de gestión del Historial de Oportunidades y Diario de Trading Automático.
Registra cada vez que un activo entra en Zona Áurea (61.8%) o supera confluencia técnica >= 70,
y hace seguimiento de su evolución (Stop Loss, TP1, TP2, retorno máximo alcanzado).
"""

import os
import json
import time
from datetime import datetime

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
JOURNAL_PATH = os.path.join(DIRECTORY, "journal.json")

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
        "total_won": len(won),
        "total_lost": len(lost),
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss
    }


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
        entries = [e for e in entries if str(e.get("id")) != str(entry_id)]

    journal["entries"] = entries
    journal["stats"] = calculate_journal_stats(entries)
    journal["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_journal(journal)
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


def update_journal_with_market_data(market_data_list, histories=None):
    """
    Sincroniza el diario de trading:
    1. Registra nuevas oportunidades (si un activo entra en Zona Áurea o Score >= 70) al precio real actual.
    2. Actualiza el progreso de las operaciones activas revisando velas ocurridas desde la señal y precio actual.
    """
    journal = load_journal()
    entries = journal.get("entries", [])
    now_dt = datetime.now()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    today_day = now_dt.strftime("%Y-%m-%d")

    # Mantener referencias a las operaciones: insertar señales al principio
    # de entries desplaza los índices, pero no cambia estos objetos.
    active_by_ticker = {}
    for e in entries:
        if e.get("status") in ("ACTIVA", "TP1_ALCANZADO"):
            active_by_ticker[e.get("ticker")] = e

    for item in market_data_list:
        ticker = item.get("ticker")
        current_price = float(item.get("current_price", 0))
        if current_price <= 0:
            continue

        fibs = item.get("fib_levels", {})
        golden_price = float(fibs.get("61.8%", 0))
        score = item.get("score", 0)
        risk = item.get("risk_mgmt", {})

        dec = int(item.get("decimals", 2))
        curr_sym = item.get("currency", "$")
        min_risk_unit = 0.0001 if dec >= 4 else 0.01

        is_golden = current_price <= golden_price
        is_high_score = score >= 70

        # Caso A: El activo ya tiene una oportunidad abierta en seguimiento
        if ticker in active_by_ticker:
            trade = active_by_ticker[ticker]
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

        # Caso B: Nueva oportunidad detectada y no hay operación abierta actualmente para este ticker
        elif is_golden or is_high_score:
            # La entrada de una oportunidad activa siempre se registra al precio real de mercado en el momento de la señal
            entry_p = round(current_price, dec)
            default_sl = round(
                min(fibs.get("78.6%", entry_p * 0.95) * 0.98, item.get("min", entry_p) * 0.985),
                dec
            )

            if risk.get("entry_type") == "MARKET":
                sl = round(float(risk.get("stop_loss", default_sl)), dec)
                tp1 = round(float(risk.get("take_profit_1", max(fibs.get("38.2%", 0), entry_p * 1.05))), dec)
                tp2 = round(float(risk.get("take_profit_2", max(item.get("max", 0), tp1 * 1.04))), dec)
                rr_ratio = risk.get("rr_ratio_2", 2.0)
            else:
                raw_sl = float(risk.get("stop_loss", default_sl))
                sl = round(raw_sl if raw_sl < entry_p else entry_p * 0.96, dec)
                tp1 = round(max(float(fibs.get("38.2%", 0)), entry_p * 1.05), dec)
                tp2 = round(max(float(item.get("max", 0)), tp1 * 1.04), dec)
                risk_ps = max(min_risk_unit, entry_p - sl)
                rr_ratio = round((tp2 - entry_p) / risk_ps, 2)

            signal_type = "ZONA_AUREA" if is_golden else "CONFLUENCIA_ALTA"
            signal_label = "Zona Áurea (61.8%)" if is_golden else f"Confluencia Alta ({score}/100)"
            if is_golden and is_high_score:
                signal_label = f"Zona Áurea + Score {score}/100"

            new_entry = {
                "id": f"opp_{ticker}_{int(time.time())}",
                "ticker": ticker,
                "tab": item.get("tab", ticker),
                "name": item.get("name", ticker),
                "currency": curr_sym,
                "decimals": dec,
                "signal_date": now_str,
                "signal_type": signal_type,
                "signal_label": signal_label,
                "period": item.get("period"),
                "stop_method": "ESTRUCTURAL",
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
            active_by_ticker[ticker] = new_entry

    journal["entries"] = entries
    journal["stats"] = calculate_journal_stats(entries)
    journal["last_updated"] = now_str
    save_journal(journal)
    return journal
