---
name: portfolio-journal
description: >-
  Use this skill when the user asks to manage their real portfolio (buy, DCA, close, or delete
  positions), review P&L or portfolio weights, inspect or repair the signal effectiveness journal,
  or troubleshoot portfolio_manager.py and journal_manager.py in "Buscar un buen precio".
---

# Gestión de Cartera Real y Diario de Señales (Backtesting)

Esta skill documenta el funcionamiento de la cartera real (`portfolio_manager.py`) y del diario histórico de señales (`journal_manager.py`).

## 1. Archivos Clave

- [portfolio_manager.py](file:///e:/Proyectos/Buscar%20un%20buen%20precio/portfolio_manager.py): Motor CRUD de posiciones reales, cálculo de DCA (precio medio ponderado), P&L en vivo, Stop Loss sugerido (`2x ATR(14)`) y peso porcentual de cada activo en cartera.
- `portfolio.json`: Base de datos local de posiciones abiertas y cerradas (**ignorado en Git** por privacidad financiera).
- [journal_manager.py](file:///e:/Proyectos/Buscar%20un%20buen%20precio/journal_manager.py): Registro automático de señales de compra (`<= 61.8%` de retroceso), evaluación retroactiva a `+7d`, `+15d` y `+30d` con barra `High` y `Close`, y estadísticas de Win-Rate.
- [journal.json](file:///e:/Proyectos/Buscar%20un%20buen%20precio/journal.json): Historial persistente de señales detectadas y su rendimiento real.

## 2. Operaciones sobre "💼 Mi Cartera Real"

### Endpoints REST en [app.py](file:///e:/Proyectos/Buscar%20un%20buen%20precio/app.py)
- `GET /api/portfolio`: Devuelve las posiciones enriquecidas con el último precio de `latest_data.json` (`positions`, `closed_positions`, `summary`).
- `POST /api/portfolio/buy`: Registra una compra o amplía una posición abierta calculando el nuevo precio medio ponderado (DCA).
  - Payload JSON: `{"ticker": "NVDA", "tab": "NVIDIA", "name": "NVIDIA Corp", "price": 175.50, "shares": 5, "notes": "Entrada en 61.8%"}`
- `POST /api/portfolio/close`: Cierra total o parcialmente una posición abierta y registra la ganancia/pérdida realizada en `closed_positions`.
  - Payload JSON: `{"id": "<pos_id>", "close_price": 195.00}`
- `DELETE /api/portfolio/<pos_id>`: Elimina una posición por completo.

### Reglas de Cálculo en `enrich_portfolio(assets_data)`
1. **DCA automático**: Si ya existe una posición abierta para el mismo `ticker`, `add_or_dca_position` suma las acciones y recalcula `avg_price = ((old_price * old_shares) + (new_price * new_shares)) / total_shares`.
2. **Stop Loss ATR**: Se calcula como `round(avg_price - 2 * atr_14, decimals)` usando el `atr_14` del activo en `latest_data.json`.
3. **Pesos de cartera (`weight_pct`)**: Solo se suman e integran en el capital total las posiciones que usan la misma divisa o se calcula el porcentaje sobre el valor de mercado total invertido.

## 3. Diario de Efectividad de Señales (`journal_manager.py`)

1. **Claves de señal deterministas**: El ID de cada entrada usa la fecha ISO (`YYYY-MM-DD`) de `updated_at[:10]` (ej: `"NVDA_2026-10-31"`), evitando duplicados por zona horaria.
2. **Evaluación de retornos (`+7d`, `+15d`, `+30d`)**:
   - Excluye el mismo día de entrada (`hist.index.date > signal_dt.date()`) para evitar contaminar el retorno con el máximo intradía previo a la señal.
   - Guarda tanto el retorno al cierre (`return_7d_close`) como la excursión máxima favorable (`max_return_7d` usando `High`).
3. **Win-Rate honesto**: Una señal se considera ganadora (`is_winner = True`) si el retorno al cierre más reciente disponible es `>= +1.5%` o si el pico máximo intradía en ventana fue `>= +3.5%`.

