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

def save_journal(data):
    """
    Guarda el historial de oportunidades en journal.json de manera atómica.
    """
    try:
        temp_file = JOURNAL_PATH + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        if os.path.exists(JOURNAL_PATH):
            os.replace(temp_file, JOURNAL_PATH)
        else:
            os.rename(temp_file, JOURNAL_PATH)
        return True
    except Exception as e:
        print(f"[Journal Manager] Error al guardar journal.json: {e}")
        return False

def calculate_journal_stats(entries):
    """
    Calcula métricas clave de rendimiento: Tasa de acierto (Win Rate), operaciones ganadas/perdidas.
    """
    total = len(entries)
    active = [e for e in entries if e.get("status") in ("ACTIVA", "TP1_ALCANZADO")]
    closed = [e for e in entries if e.get("status") in ("TP2_ALCANZADO", "STOP_EJECUTADO", "CERRADA_MANUAL")]

    won = [e for e in closed if e.get("result") == "GANADA"]
    lost = [e for e in closed if e.get("result") == "PERDIDA"]

    win_rate = round((len(won) / len(closed)) * 100, 1) if closed else 0.0

    win_returns = [e.get("final_return_pct", 0) for e in won if e.get("final_return_pct") is not None]
    loss_returns = [e.get("final_return_pct", 0) for e in lost if e.get("final_return_pct") is not None]

    avg_win = round(sum(win_returns) / len(win_returns), 2) if win_returns else 0.0
    avg_loss = round(sum(loss_returns) / len(loss_returns), 2) if loss_returns else 0.0

    return {
        "total_opportunities": total,
        "active_count": len(active),
        "closed_count": len(closed),
        "win_rate_pct": win_rate,
        "total_won": len(won),
        "total_lost": len(lost),
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss
    }

def update_journal_with_market_data(market_data_list):
    """
    Sincroniza el diario de trading:
    1. Registra nuevas oportunidades (si un activo entra en Zona Áurea o Score >= 70).
    2. Actualiza el progreso de las operaciones activas existentes (Stop Loss, TP1, TP2).
    """
    journal = load_journal()
    entries = journal.get("entries", [])
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Mapear tickers activos en el diario
    active_by_ticker = {}
    for idx, e in enumerate(entries):
        if e.get("status") in ("ACTIVA", "TP1_ALCANZADO"):
            active_by_ticker[e.get("ticker")] = idx

    for item in market_data_list:
        ticker = item.get("ticker")
        current_price = item.get("current_price", 0)
        fibs = item.get("fib_levels", {})
        golden_price = fibs.get("61.8%", 0)
        score = item.get("score", 0)
        risk = item.get("risk_mgmt", {})

        is_golden = current_price <= golden_price
        is_high_score = score >= 70

        # Caso A: El activo ya tiene una oportunidad abierta en seguimiento
        if ticker in active_by_ticker:
            idx = active_by_ticker[ticker]
            trade = entries[idx]

            entry_p = trade.get("entry_price", current_price)
            sl = trade.get("stop_loss", entry_p * 0.95)
            tp1 = trade.get("tp1", entry_p * 1.05)
            tp2 = trade.get("tp2", entry_p * 1.15)

            # Actualizar máximos y mínimos vistos durante la vida de la operación
            max_seen = max(trade.get("max_price_seen", current_price), current_price)
            min_seen = min(trade.get("min_price_seen", current_price), current_price)
            trade["max_price_seen"] = round(max_seen, 2)
            trade["min_price_seen"] = round(min_seen, 2)

            curr_ret = round(((current_price - entry_p) / entry_p) * 100, 2) if entry_p > 0 else 0.0
            max_ret = round(((max_seen - entry_p) / entry_p) * 100, 2) if entry_p > 0 else 0.0
            trade["current_price"] = round(current_price, 2)
            trade["current_return_pct"] = curr_ret
            trade["max_return_pct"] = max_ret
            trade["last_check"] = now_str

            # Evaluar salidas / objetivos
            if current_price >= tp2:
                trade["status"] = "TP2_ALCANZADO"
                trade["result"] = "GANADA"
                trade["closed_date"] = now_str
                trade["final_return_pct"] = curr_ret
                trade["exit_reason"] = f"Objetivo principal (TP 2 en ${tp2:,.2f}) completado"
            elif current_price <= sl:
                trade["status"] = "STOP_EJECUTADO"
                trade["result"] = "PERDIDA"
                trade["closed_date"] = now_str
                trade["final_return_pct"] = curr_ret
                trade["exit_reason"] = f"Stop Loss alcanzado en ${sl:,.2f} para acotar riesgo"
            elif current_price >= tp1 and trade.get("status") == "ACTIVA":
                trade["status"] = "TP1_ALCANZADO"
                trade["tp1_hit_date"] = now_str
                trade["advice"] = "TP 1 alcanzado. Subir Stop Loss a Precio de Entrada (Break-Even) para riesgo cero."

            entries[idx] = trade

        # Caso B: Nueva oportunidad detectada y no hay operación abierta actualmente para este ticker
        elif is_golden or is_high_score:
            entry_p = risk.get("entry_price", current_price)
            sl = risk.get("stop_loss", round(min(fibs.get("78.6%", current_price * 0.95) * 0.98, item.get("min", current_price) * 0.985), 2))
            tp1 = risk.get("take_profit_1", fibs.get("38.2%", entry_p * 1.05))
            tp2 = risk.get("take_profit_2", item.get("max", entry_p * 1.15))

            signal_type = "ZONA_AUREA" if is_golden else "CONFLUENCIA_ALTA"
            signal_label = "Zona Áurea (61.8%)" if is_golden else f"Confluencia Alta ({score}/100)"
            if is_golden and is_high_score:
                signal_label = f"Zona Áurea + Score {score}/100"

            new_entry = {
                "id": f"opp_{ticker}_{int(time.time())}",
                "ticker": ticker,
                "tab": item.get("tab", ticker),
                "name": item.get("name", ticker),
                "signal_date": now_str,
                "signal_type": signal_type,
                "signal_label": signal_label,
                "score": score,
                "rsi": item.get("rsi"),
                "entry_price": round(entry_p, 2),
                "stop_loss": round(sl, 2),
                "tp1": round(tp1, 2),
                "tp2": round(tp2, 2),
                "rr_ratio": risk.get("rr_ratio_2", 2.0),
                "current_price": round(current_price, 2),
                "max_price_seen": round(current_price, 2),
                "min_price_seen": round(current_price, 2),
                "current_return_pct": 0.0,
                "max_return_pct": 0.0,
                "status": "ACTIVA",
                "result": "EN_CURSO",
                "closed_date": None,
                "final_return_pct": None,
                "exit_reason": None,
                "last_check": now_str
            }
            entries.insert(0, new_entry)  # Más reciente primero

    journal["entries"] = entries
    journal["stats"] = calculate_journal_stats(entries)
    journal["last_updated"] = now_str
    save_journal(journal)
    return journal
