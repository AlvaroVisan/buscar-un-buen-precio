"""Lectura explicable de estados anuales, independiente del score técnico."""

from datetime import datetime, timezone
import json
import math
import os
import threading
import time
from urllib.parse import quote

import yfinance as yf

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(DIRECTORY, ".business_cache.json")
CACHE_TTL = 24 * 3600
RETRY_TTL = 5 * 60
_lock = threading.Lock()
_retry_after = {}
SCHEMA_VERSION = 2


def is_company_candidate(ticker):
    symbol = str(ticker).upper()
    return bool(symbol) and not (
        symbol.startswith("^") or "=" in symbol
        or symbol.endswith(("-USD", "-EUR", "-USDT"))
    )


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _annual_rows(frame, fields):
    """Orden descendente; nunca mezclar años distintos para completar huecos."""
    if frame is None or frame.empty:
        return []
    rows = []
    for column in sorted(frame.columns, reverse=True)[:3]:
        row = {"date": column.strftime("%Y-%m-%d")}
        for field in fields:
            row[field] = number(frame.at[field, column]) if field in frame.index else None
        rows.append(row)
    return rows


def build_context(ticker, info, income, cash, balance, now=None):
    now = now or datetime.now(timezone.utc)
    sources = [{"label": "Yahoo Finance · estados financieros",
                "url": f"https://finance.yahoo.com/quote/{quote(ticker, safe='')}/financials/"}]
    result = {
        "schema_version": SCHEMA_VERSION, "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "sector": info.get("sector"), "industry": info.get("industry"),
        "fetched_at": now.isoformat(), "is_stale": False,
        "classification": "insufficient", "label": "Información insuficiente",
        "strengths": [], "risks": [], "limitations": [], "details": [],
        "sources": sources,
        "valuation": "No hay datos suficientes para contextualizar el precio.",
        "summary": "No hay información suficiente para valorar la solidez del negocio.",
    }
    if info.get("quoteType") != "EQUITY":
        result.update(supported=False, summary="Esta ficha analiza empresas. Este activo no tiene estados empresariales comparables.")
        return result
    result["supported"] = True
    inc = _annual_rows(income, ("TotalRevenue", "NetIncome"))
    cf = _annual_rows(cash, ("OperatingCashFlow", "FreeCashFlow"))
    bs = _annual_rows(balance, ("TotalDebt", "CashCashEquivalentsAndShortTermInvestments"))
    result["details"] = [
        {"label": "Resultados anuales", "rows": inc},
        {"label": "Flujos de caja anuales", "rows": cf},
        {"label": "Balance anual", "rows": bs},
    ]
    result["financial_currency"] = info.get("financialCurrency") or "Divisa no informada"
    result["report_date"] = inc[0]["date"] if inc else None
    strengths, risks, limitations = result["strengths"], result["risks"], result["limitations"]
    positive, negative, covered = 0, 0, 0

    # Una conclusión favorable exige tres ejercicios y todas las dimensiones.
    profits = [row["NetIncome"] for row in inc]
    if len(profits) == 3 and all(v is not None for v in profits):
        covered += 1
        if all(v > 0 for v in profits):
            strengths.append("Ha obtenido beneficios en los tres últimos ejercicios disponibles.")
            positive += 1
        else:
            risks.append("Ha registrado pérdidas o resultados nulos en alguno de los tres ejercicios disponibles.")
            negative += 1
    else:
        limitations.append("Falta un historial completo de tres ejercicios de beneficios.")

    growth = None
    if len(inc) >= 2 and inc[0]["TotalRevenue"] is not None and (inc[1]["TotalRevenue"] or 0) > 0:
        growth = inc[0]["TotalRevenue"] / inc[1]["TotalRevenue"] - 1
        covered += 1
        if growth >= 0:
            strengths.append("Los ingresos del último ejercicio se mantienen o crecen frente al anterior.")
            positive += 1
        else:
            risks.append("Los ingresos del último ejercicio han caído frente al anterior.")
            negative += 1
    else:
        limitations.append("No se pueden comparar los ingresos de los dos últimos ejercicios.")

    margin_change = None
    if len(inc) >= 2 and all(row["NetIncome"] is not None and (row["TotalRevenue"] or 0) > 0 for row in inc[:2]):
        margin_change = inc[0]["NetIncome"] / inc[0]["TotalRevenue"] - inc[1]["NetIncome"] / inc[1]["TotalRevenue"]
        covered += 1
        if margin_change >= -0.02:
            strengths.append("El margen neto no se ha deteriorado más de dos puntos porcentuales en el último ejercicio.")
            positive += 1
        else:
            risks.append("El margen neto ha caído más de dos puntos porcentuales frente al ejercicio anterior.")
            negative += 1
    else:
        limitations.append("No se puede comparar la evolución del margen neto anual.")

    free_cash = [row["FreeCashFlow"] for row in cf]
    if len(free_cash) == 3 and all(v is not None for v in free_cash):
        covered += 1
        if all(v > 0 for v in free_cash):
            strengths.append("Ha generado caja libre positiva en los tres ejercicios disponibles.")
            positive += 1
        else:
            risks.append("La generación de caja libre no ha sido positiva en los tres ejercicios.")
            negative += 1
    else:
        limitations.append("Faltan tres ejercicios completos de flujo de caja libre.")

    leverage = None
    if bs and cf and bs[0]["date"] == cf[0]["date"]:
        debt, liquid, operating = bs[0]["TotalDebt"], bs[0]["CashCashEquivalentsAndShortTermInvestments"], cf[0]["OperatingCashFlow"]
        if debt is not None and liquid is not None and operating is not None and debt >= 0 and liquid >= 0:
            covered += 1
            net_debt = debt - liquid
            if net_debt <= 0:
                strengths.append("El efectivo y las inversiones líquidas cubren la deuda financiera declarada.")
                positive += 1
            elif operating > 0:
                leverage = net_debt / operating
                if leverage <= 3:
                    strengths.append("La deuda neta no supera tres veces el flujo de caja operativo anual.")
                    positive += 1
                else:
                    risks.append("La deuda neta supera tres veces la caja operativa anual; conviene revisar sus vencimientos.")
                    negative += 1
            else:
                risks.append("Tiene deuda neta y no generó caja operativa positiva en el último ejercicio.")
                negative += 1
    if not any("deuda" in s for s in strengths + risks):
        limitations.append("No se puede contrastar la deuda con la caja del mismo ejercicio.")

    dated_rows = inc[:1] + cf[:1] + bs[:1]
    aligned_reports = len(dated_rows) == 3 and len({r["date"] for r in dated_rows}) == 1
    if not aligned_reports:
        limitations.append("Los últimos resultados, flujos de caja y balance no corresponden al mismo cierre anual.")
    old_reports = any((now.date() - datetime.fromisoformat(r["date"]).date()).days > 550
                      or datetime.fromisoformat(r["date"]).date() > now.date() for r in dated_rows)
    if old_reports:
        limitations.append("Algún estado anual tiene más de 18 meses o una fecha no válida.")
    specialized = info.get("sector") in ("Financial Services", "Real Estate")
    if specialized:
        limitations.append("El sector financiero o inmobiliario necesita métricas específicas; estas reglas generales no bastan.")
    if not info.get("sector"):
        limitations.append("No se ha podido identificar el sector para comprobar si estas reglas son aplicables.")

    if covered == 5 and aligned_reports and not old_reports and not specialized and info.get("sector"):
        if positive == 5:
            result.update(classification="favorable", label="Favorable",
                          summary="Los estados disponibles muestran beneficios y caja libre positivos, ingresos sostenidos y deuda contenida, sin un deterioro relevante del margen neto según estas reglas.")
        elif negative >= 2:
            result.update(classification="weak", label="Débil",
                          summary="Los estados disponibles presentan varias señales de fragilidad. Conviene revisar sus causas antes de valorar una entrada técnica.")
        else:
            result.update(classification="mixed", label="Mixta",
                          summary="El negocio combina señales favorables con un punto de vigilancia relevante en sus estados financieros.")
    result["metrics"] = {"revenue_growth": growth, "net_margin_change": margin_change, "net_debt_to_operating_cash": leverage}
    pe = number(info.get("trailingPE"))
    if pe is not None and pe > 0:
        result["valuation"] = f"Cotiza a {pe:.1f} veces el beneficio de los últimos doce meses (PER). " + (
            "Un múltiplo superior a 35 exige especial atención a las expectativas de crecimiento. " if pe > 35 else ""
        ) + "Sin comparación sectorial e histórica, este dato no permite afirmar que esté barata o cara."
    elif number(info.get("trailingEps")) is not None and number(info.get("trailingEps")) <= 0:
        result["valuation"] = "El beneficio por acción de los últimos doce meses no es positivo; el PER no es una referencia útil."
    result["limitations"].append("Lectura automática de datos contables: no evalúa ventajas competitivas, dirección, litigios ni concentración por segmentos. No modifica el score técnico.")
    sources.extend([
        {"label": "Yahoo Finance · balance", "url": f"https://finance.yahoo.com/quote/{quote(ticker, safe='')}/balance-sheet/"},
        {"label": "Yahoo Finance · flujos de caja", "url": f"https://finance.yahoo.com/quote/{quote(ticker, safe='')}/cash-flow/"},
    ])
    return result


def get_business_context(ticker):
    """Caché privada, escritura atómica y recuperación sin ocultar errores de red."""
    with _lock:
        try:
            with open(CACHE_PATH, encoding="utf-8") as handle:
                cache = json.load(handle)
            if not isinstance(cache, dict):
                cache = {}
        except (OSError, ValueError):
            cache = {}
        old = cache.get(ticker)
        if not isinstance(old, dict) or old.get("schema_version") != SCHEMA_VERSION:
            old = None
        now = time.time()
        if old:
            try:
                age = now - datetime.fromisoformat(old["fetched_at"]).timestamp()
            except (KeyError, ValueError, TypeError):
                age = CACHE_TTL
            if 0 <= age < CACHE_TTL:
                return old
        def unavailable():
            if old:
                return {**old, "is_stale": True,
                        "notice": "No se pudo renovar la consulta. Se muestra la lectura anterior con su fecha original."}
            return {"ticker": ticker, "supported": True, "classification": "insufficient",
                    "label": "Información insuficiente", "summary": "No se han podido obtener los estados financieros. Vuelve a intentarlo en unos minutos.",
                    "is_stale": False, "fetched_at": None, "sources": []}
        if now < _retry_after.get(ticker, 0):
            return unavailable()
        try:
            company = yf.Ticker(ticker)
            info = company.get_info()
            if not isinstance(info, dict) or not info.get("quoteType"):
                raise ValueError("Información de empresa no disponible")
            if info["quoteType"] == "EQUITY":
                income = company.get_income_stmt(freq="yearly")
                cash = company.get_cashflow(freq="yearly")
                balance = company.get_balance_sheet(freq="yearly")
                if all(frame is None or frame.empty for frame in (income, cash, balance)):
                    raise ValueError("Estados financieros no disponibles")
            else:
                income = cash = balance = None
            result = build_context(ticker, info, income, cash, balance)
        except Exception:
            _retry_after[ticker] = now + RETRY_TTL
            return unavailable()
        cache[ticker] = result
        temporary = f"{CACHE_PATH}.{threading.get_ident()}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(cache, handle, ensure_ascii=False, allow_nan=False)
            os.replace(temporary, CACHE_PATH)
        except OSError:
            result["notice"] = "Consulta disponible; no se pudo guardar la caché local."
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
        return result
