"""Contexto descriptivo de 60–90 minutos; no genera señales ni modifica scores."""
import math
from datetime import datetime, timezone


def analyze_stabilization(rows, price, now=None):
    now = now or datetime.now(timezone.utc)
    result = {"state": "INSUFFICIENT", "label": "Aún falta observar", "interval": "15m",
              "summary": "Aún faltan velas cerradas recientes para saber si está dejando de caer.",
              "is_entry_signal": False, "bars": 0}
    if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return result
    valid = {}
    for row in rows or []:
        try:
            stamp = datetime.fromisoformat(row["time"])
            stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
            values = [float(row[key]) for key in ("High", "Low", "Close")]
            if stamp <= now and all(math.isfinite(v) and v > 0 for v in values) and values[1] <= values[2] <= values[0]:
                valid[stamp] = values
        except (KeyError, TypeError, ValueError):
            continue
    ordered = sorted(valid.items())
    # No mezclar la sesión actual con ayer ni cruzar velas ausentes.
    recent = []
    for stamp, values in ordered:
        if recent and (stamp - recent[-1][0]).total_seconds() != 900:
            recent = []
        recent.append((stamp, values))
    if not recent:
        return result
    result["as_of"] = recent[-1][0].strftime("%Y-%m-%d %H:%M:%S UTC")
    if (now - recent[-1][0]).total_seconds() > 45 * 60:
        result.update(state="STALE", label="Lectura anterior", summary="No hay velas recientes suficientes para valorar la calma ahora.")
        return result
    if len(recent) < 8:
        result["bars"] = len(recent)
        return result
    size = min(6, len(recent) - 4)
    window = [values for _, values in recent[-size:]]
    baseline = [values for _, values in recent[-size - 4:-size]]
    closes = [values[2] for values in window]
    support = min(values[1] for values in window)
    resistance = max(values[0] for values in window)
    range_pct = (resistance - support) / (sum(closes) / size) * 100
    current_range = sum(high - low for high, low, _ in window) / size
    previous_range = sum(high - low for high, low, _ in baseline) / len(baseline)
    contraction = current_range / previous_range if previous_range else (1 if current_range == 0 else None)
    drift = (closes[-1] / closes[0] - 1) * 100
    path = sum(abs(right - left) for left, right in zip(closes, closes[1:]))
    efficiency = abs(closes[-1] - closes[0]) / path if path else 0
    split = size // 2
    new_low = min(values[1] for values in window[split:]) < min(values[1] for values in window[:split]) * .999
    narrow = (contraction is not None and contraction <= .8) or (current_range / (sum(closes) / size) * 100 <= .4 and range_pct <= 1.5)
    if drift < -max(.3, range_pct * .3) or (new_low and drift < -.15):
        state, label, summary = "FALLING", "Sigue bajando", "Todavía sigue bajando; moverse menos no significa que haya formado suelo."
    elif size >= 6 and narrow and not new_low and range_pct <= 2.5 and abs(drift) <= max(.15, range_pct * .25) and efficiency <= .4:
        state, label, summary = "LATERAL", "Se está quedando en una franja", "Se mueve en una franja más estrecha y no está haciendo mínimos nuevos. Puede estar asentándose, pero aún no sabemos por dónde romperá."
    elif narrow and not new_low and range_pct <= 4 and drift >= -max(.2, range_pct * .35) and efficiency <= .65:
        state, label, summary = "FORMING_BASE", "Intenta formar suelo", "La caída parece perder fuerza y empieza a sostener los mínimos. Todavía necesita más tiempo para dar el suelo por formado."
    elif drift > max(.3, range_pct * .35) and efficiency > .45:
        state, label, summary = "REBOUND", "Está rebotando", "Está recuperando terreno, pero eso todavía puede ser un rebote dentro de la caída."
    else:
        state, label, summary = "UNSETTLED", "Todavía se mueve demasiado", "Aún no veo una pausa clara y ordenada. De momento no daría el suelo por hecho."
    if state in ("LATERAL", "FORMING_BASE") and price < support * .999:
        state, label, summary = "BREAKING_DOWN", "Está perdiendo la franja", "El precio ya está por debajo de la franja reciente: la idea de que estaba formando suelo pierde fuerza."
    elif state in ("LATERAL", "FORMING_BASE") and price > resistance * 1.001:
        state, label, summary = "BREAKING_UP", "Intenta salir por arriba", "Está saliendo por arriba de la franja, pero aún necesita la confirmación de entrada habitual."
    result.update(state=state, label=label, summary=summary, bars=size, window_minutes=size * 15,
                  support=support, resistance=resistance, range_pct=round(range_pct, 3),
                  contraction_ratio=round(contraction, 3) if contraction is not None else None,
                  drift_pct=round(drift, 3), efficiency=round(efficiency, 3), new_lows=new_low)
    return result
