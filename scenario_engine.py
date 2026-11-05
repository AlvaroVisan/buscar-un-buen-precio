"""Escenarios prospectivos; nunca reinterpretan operaciones históricas."""
import math


def advance_watch(watch, bars, price, now):
    """Techo móvil hasta el primer cierre; dos sesiones sobre el mismo nivel."""
    if watch.get("rules_version") != 2:
        # Migración prospectiva: no convertir velas previas en señales nuevas.
        watch.update(rules_version=2, level_since=now[:10],
                     breakout=max(float(r["High"]) for _, r in bars[-2:]),
                     confirmations=0, last_breakout_day=bars[-1][0])
    for index, (day, bar) in enumerate(bars):
        if day <= max(watch["level_since"], watch["last_breakout_day"]):
            continue
        if index < 2:
            continue
        if watch["confirmations"] == 0:
            watch["breakout"] = max(float(r["High"]) for _, r in bars[index - 2:index])
        if float(bar["Close"]) > watch["breakout"]:
            watch["confirmations"] = min(2, watch["confirmations"] + 1)
        else:
            watch["confirmations"] = 0
            watch["breakout"] = max(float(r["High"]) for _, r in bars[max(0, index - 1):index + 1])
        watch["last_breakout_day"] = day
    if watch["confirmations"] == 0:
        watch["breakout"] = max(float(r["High"]) for _, r in bars[-2:])
    return watch["confirmations"] >= 2 and price >= watch["breakout"]


def advance(journal, items, histories, now):
    watches = journal.setdefault("watches", {})
    campaigns = journal.setdefault("accumulation", [])
    allowed = set()
    today = now[:10]
    benchmark = (histories or {}).get("^GSPC")
    market_ok = None
    if benchmark is not None:
        closed = benchmark[[str(t)[:10] < today for t in benchmark.index]]["Close"].tail(20)
        if len(closed) == 20 and all(math.isfinite(float(v)) and float(v) > 0 for v in closed):
            market_ok = float(closed.iloc[-1]) >= float(closed.mean())
    for item in items:
        ticker = item.get("ticker")
        price = float(item.get("current_price", 0))
        if not ticker or not math.isfinite(price) or price <= 0 or item.get("is_stale"):
            continue
        hist = (histories or {}).get(ticker)
        bars = [] if hist is None else [(str(t)[:10], r) for t, r in hist.sort_index().iterrows() if str(t)[:10] < today]
        bars = [(d, r) for d, r in bars if all(math.isfinite(float(r[k])) and float(r[k]) > 0 for k in ("High", "Low", "Close"))]
        risk = item.get("risk_mgmt", {})
        atr = float(item.get("atr_14") or risk.get("atr_14") or 0)
        qualified = price <= float(item.get("fib_levels", {}).get("61.8%", 0)) or item.get("score", 0) >= 70
        market_blocked = market_ok is False and not any(symbol in ticker for symbol in ("-", "=", "^"))
        watch = watches.get(ticker)
        losses = [e for e in journal.get("entries", []) if e.get("ticker") == ticker and e.get("status") == "STOP_EJECUTADO"]
        last_stop = max((str(e.get("closed_date") or e.get("last_check") or e.get("signal_date", "")) for e in losses), default="")
        last_campaign_close = max((c.get("closed_date", "") for c in campaigns if c["ticker"] == ticker), default="")
        reset_after = max(last_stop, last_campaign_close)
        if watch and reset_after > watch["since"]:
            watches.pop(ticker)
            watch = None
        if watch is None and qualified and len(bars) >= 4:
            watch = {"since": now, "state": "VIGILANCIA"}
            watches[ticker] = watch
        ready = False
        rebound = False
        trend = False
        if len(bars) >= 4:
            day, bar = bars[-1]
            close = float(bar["Close"])
            rebound = close > float(bars[-2][1]["Close"])
            # Tendencia corta ascendente y recuperación de estructura, con datos cerrados.
            trend = close > sum(float(r["Close"]) for _, r in bars[-4:]) / 4
            double_close = advance_watch(watch, bars, price, now) if watch else False
            ready = bool(watch and double_close and day > last_stop[:10]
                         and trend and not market_blocked)
        if watch:
            watch["state"] = "CONFIRMADA" if ready else "VIGILANCIA"
            watch["current_price"] = price
            watch["market_context"] = "Mercado débil: entrada bloqueada" if market_blocked else "Mercado favorable" if market_ok else "Mercado sin confirmar"
        if ready:
            allowed.add(ticker)

        active = next((c for c in campaigns if c["ticker"] == ticker and c["status"] == "ACTIVA"), None)
        if active:
            # Solo rangos posteriores a la última observación; nunca antes de comprar.
            unseen = [(d, r) for d, r in bars if d > active.get("last_candle_day", active["tranches"][-1]["date"][:10])]
            exit_price = None
            for day, bar in unseen:
                active["last_candle_day"] = day
                if float(bar["Low"]) <= active["invalidation"]:
                    exit_price = min(active["invalidation"], float(bar.get("Open", active["invalidation"])))
                elif float(bar["High"]) >= active["target"]:
                    exit_price = active["target"]
                if exit_price is not None:
                    break
                mark(active, float(bar["High"]))
                mark(active, float(bar["Low"]))
            if exit_price is None and price <= active["invalidation"]:
                exit_price = price
            elif exit_price is None and price >= active["target"]:
                exit_price = price
            if exit_price is not None:
                active["status"] = "CERRADA"
                active["closed_date"] = now
                active["exit_price"] = exit_price
            elif (len(active["tranches"]) < 3 and rebound and trend and not market_blocked
                  and float(bars[-1][1]["Close"]) > float(bars[-2][1]["High"])
                  and bars[-1][0] > active["tranches"][-1]["date"][:10]
                  and price <= active["tranches"][-1]["price"] * .95):
                buy(active, price, now)
            mark(active, exit_price if exit_price is not None else price)
            active["last_check"] = now
        elif ready and watch["since"] > last_campaign_close and not any(c["ticker"] == ticker and c.get("closed_date", "")[:10] >= bars[-1][0] for c in campaigns):
            invalidation = min(float(r["Low"]) for _, r in bars[-4:]) - atr
            target = float(item.get("fib_levels", {}).get("38.2%") or 0)
            if all(math.isfinite(value) for value in (invalidation, target, atr)) and 0 < invalidation < price < target and atr > 0:
                campaign = {"ticker": ticker, "currency": item.get("currency", "$"), "status": "ACTIVA",
                            "budget": 1000, "invalidation": invalidation, "target": target,
                            "tranches": [], "invested": 0, "shares": 0, "max_drawdown_pct": 0, "last_check": now}
                buy(campaign, price, now)
                mark(campaign, price)
                campaigns.insert(0, campaign)
    return allowed


def buy(campaign, price, now):
    amount = campaign["budget"] / 3
    campaign["tranches"].append({"date": now, "price": price, "amount": amount, "shares": amount / price})
    campaign["invested"] += amount
    campaign["shares"] += amount / price
    campaign["average_price"] = campaign["invested"] / campaign["shares"]
    campaign["last_candle_day"] = now[:10]


def mark(campaign, price):
    campaign["current_price"] = price
    campaign["pnl"] = campaign["shares"] * price - campaign["invested"]
    campaign["return_pct"] = campaign["pnl"] / campaign["invested"] * 100
    campaign["return_on_budget_pct"] = campaign["pnl"] / campaign["budget"] * 100
    equity = campaign["budget"] + campaign["pnl"]
    campaign["peak_equity"] = max(campaign.get("peak_equity", campaign["budget"]), equity)
    campaign["max_drawdown_pct"] = min(campaign["max_drawdown_pct"], (equity / campaign["peak_equity"] - 1) * 100)
