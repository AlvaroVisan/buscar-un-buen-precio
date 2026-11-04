import http.server
import json
import errno
import socket
import os
import sys
import urllib.parse
import webbrowser
import threading
import time
import market_updater
import portfolio_manager
import telegram_notifier
import business_context

PORT = 5050
HOST = "127.0.0.1"
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
MASK_PREFIX = "••••••••"
# La primera comprobación del scheduler debe descargar datos al arrancar.
last_auto_sync_time = 0.0


def mask_secret(val):
    """Enmascara tokens privados antes de enviarlos por HTTP al navegador."""
    s = str(val or "").strip()
    if not s:
        return ""
    if len(s) <= 8:
        return MASK_PREFIX
    return f"{MASK_PREFIX}{s[-6:]}"


def resolve_secret(incoming, current_saved):
    """Conserva el secreto guardado si el cliente reenvía la máscara intacta; permite borrarlo si llega vacío."""
    val = str(incoming or "").strip()
    if val.startswith("••••"):
        return str(current_saved or "").strip()
    return val


def _is_forbidden_static_path(route_path):
    """Bloquea el acceso HTTP directo a archivos internos, código fuente y credenciales."""
    decoded = urllib.parse.unquote(route_path or "/")
    rel = decoded.lstrip("/").replace("\\", "/")
    if not rel:
        return False

    parts = [p for p in rel.split("/") if p]
    for part in parts:
        if part == ".." or part.startswith("."):
            return True

    filename = parts[-1].lower()
    blocked_files = {"secrets.json", "config.json", "journal.json", "portfolio.json"}
    blocked_exts = (".py", ".pyc", ".pyo", ".bat", ".cmd", ".ps1", ".sh", ".tmp", ".log", ".env")
    if filename in blocked_files or filename.endswith(blocked_exts):
        return True

    return False


def auto_scheduler_worker():
    global last_auto_sync_time
    print("[Auto-Scheduler] 🕒 Hilo de sincronización periódica iniciado en segundo plano.")
    while True:
        try:
            time.sleep(30)  # Chequear cada 30 segundos
            cfg = market_updater.load_config()
            sched_cfg = cfg.get("scheduler", {})
            enabled = sched_cfg.get("enabled", True)
            interval_min = sched_cfg.get("interval_minutes", 30)
            smart_hours_only = sched_cfg.get("smart_hours_only", True)

            if not enabled or interval_min <= 0:
                continue

            if market_updater.SYNC_LOCK.locked():
                continue

            mh = market_updater.evaluate_market_hours(cfg.get("assets", []))
            if smart_hours_only and not mh["equities_open"]:
                if not mh["has_crypto"]:
                    # Bolsas cerradas y sin criptoactivos 24/7: descanso inteligente
                    continue
                # Con cripto 24/7: suavizar cadencia nocturna/fin de semana a mín. 120m
                effective_interval_min = max(interval_min, 120)
            else:
                effective_interval_min = interval_min

            interval_sec = effective_interval_min * 60
            now = time.time()
            if now - last_auto_sync_time >= interval_sec:
                period = cfg.get("period", "3mo")
                print(f"\n[Auto-Scheduler] ⏰ Intervalo de {effective_interval_min}m alcanzado ({mh['status_label']}). Sincronizando precios...")
                market_updater.run_updater(target_period=period)
                # Solo avanzar el reloj si la ejecución terminó correctamente.
                # Ante una excepción se reintenta en la siguiente comprobación.
                last_auto_sync_time = now
        except Exception as e:
            print(f"[Auto-Scheduler] ⚠️ Error en ciclo automático: {e}")


class ThreadingFibonacciServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def server_bind(self):
        # Windows permite compartir el puerto con SO_REUSEADDR: exigir exclusividad.
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class FibonacciHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def parse_request(self):
        if not super().parse_request():
            return False
        # Solo aceptar los nombres locales previstos. También evita que un
        # dominio externo resuelto a loopback acceda al panel (DNS rebinding).
        port = self.server.server_address[1]
        hosts = {f"localhost:{port}", f"127.0.0.1:{port}"}
        host_headers = self.headers.get_all("Host", [])
        if len(host_headers) != 1 or host_headers[0].lower() not in hosts:
            self.send_error(403, "Host no permitido")
            return False
        origins = self.headers.get_all("Origin", [])
        if origins and (len(origins) != 1 or origins[0].lower() != f"http://{host_headers[0].lower()}"):
            self.send_error(403, "Origen no permitido")
            return False
        if self.headers.get("Sec-Fetch-Site", "").lower() in ("cross-site", "same-site"):
            self.send_error(403, "Peticion desde otra pagina no permitida")
            return False
        return True

    def end_headers(self):
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def do_HEAD(self):
        if _is_forbidden_static_path(self.path.split("?", 1)[0]):
            self.send_error(403, "Acceso denegado a archivo interno")
            return
        super().do_HEAD()

    def do_GET(self):
        route = self.path.split("?", 1)[0]

        if route == "/api/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b'{"application":"buscar-un-buen-precio","status":"ok"}')
            return

        if route == "/api/business":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            ticker = query.get("ticker", [""])[0].strip().upper()
            assets = market_updater.load_config().get("assets", [])
            known = any(str(asset.get("ticker", "")).upper() == ticker for asset in assets)
            if not known or not business_context.is_company_candidate(ticker):
                self.send_error(400, "Selecciona una empresa de seguimiento")
                return
            payload = business_context.get_business_context(ticker)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"))
            return

        if route == "/api/data":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            latest_path = os.path.join(DIRECTORY, "latest_data.json")
            if os.path.exists(latest_path):
                with open(latest_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.wfile.write(b"{}")
            return

        if route == "/api/config":
            cfg = market_updater.load_config()
            safe_cfg = json.loads(json.dumps(cfg))
            safe_cfg["has_webhook"] = bool(safe_cfg.get("webhook_url"))
            safe_cfg["webhook_url"] = mask_secret(safe_cfg.get("webhook_url", ""))
            if "telegram" in safe_cfg and isinstance(safe_cfg["telegram"], dict):
                safe_cfg["telegram"]["has_token"] = bool(safe_cfg["telegram"].get("bot_token"))
                safe_cfg["telegram"]["bot_token"] = mask_secret(safe_cfg["telegram"].get("bot_token", ""))

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(safe_cfg, ensure_ascii=False).encode("utf-8"))
            return

        if route == "/api/scheduler/status":
            cfg = market_updater.load_config()
            sched_cfg = cfg.get("scheduler", {})
            interval_min = sched_cfg.get("interval_minutes", 30)
            enabled = sched_cfg.get("enabled", True)
            smart_hours_only = sched_cfg.get("smart_hours_only", True)
            mh = market_updater.evaluate_market_hours(cfg.get("assets", []))

            if smart_hours_only and not mh["equities_open"]:
                paused_by_smart_hours = not mh["has_crypto"]
                effective_interval_min = None if paused_by_smart_hours else max(interval_min, 120)
            else:
                paused_by_smart_hours = False
                effective_interval_min = interval_min

            elapsed = time.time() - last_auto_sync_time
            remaining = max(0, int((effective_interval_min * 60) - elapsed)) if (enabled and effective_interval_min) else None

            safe_tg = dict(cfg.get("telegram", {}))
            safe_tg["has_token"] = bool(safe_tg.get("bot_token"))
            safe_tg["bot_token"] = mask_secret(safe_tg.get("bot_token", ""))

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps({
                "enabled": enabled,
                "interval_minutes": interval_min,
                "smart_hours_only": smart_hours_only,
                "effective_interval_minutes": effective_interval_min,
                "paused_by_smart_hours": paused_by_smart_hours,
                "market_hours": mh,
                "remaining_seconds": remaining,
                "telegram": safe_tg
            }, ensure_ascii=False).encode("utf-8"))
            return

        if route == "/api/portfolio":
            try:
                pf_data = portfolio_manager.get_enriched_portfolio()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(json.dumps(pf_data, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        if route == "/api/journal":
            try:
                import journal_manager
                j_data = journal_manager.load_journal()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(json.dumps(j_data, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        if _is_forbidden_static_path(route):
            self.send_error(403, "Acceso denegado a archivo interno")
            return

        return super().do_GET()

    def do_POST(self):
        global last_auto_sync_time
        # Rechazar formularios y peticiones simples de otras páginas antes
        # de leer el cuerpo o ejecutar acciones. Se permite POST sin cuerpo.
        if self.headers.get("Content-Length", "0") != "0" and self.headers.get_content_type() != "application/json":
            self.send_error(415, "Se requiere application/json")
            return
        route = self.path.split("?", 1)[0]
        content_len = int(self.headers.get('Content-Length', 0))
        post_data = {}
        if content_len > 0:
            try:
                body = self.rfile.read(content_len)
                post_data = json.loads(body.decode('utf-8'))
            except Exception:
                pass

        if route == "/api/sync":
            try:
                target_period = post_data.get("period")
                print(f"\n[Web Dashboard] Solicitud de sincronización recibida (Periodo: {target_period or 'configurado'})...")
                updated_payload = market_updater.run_updater(target_period=target_period)
                last_auto_sync_time = time.time()

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(updated_payload, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                print(f"[Web Dashboard] Error en sincronización: {e}")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        if route == "/api/period":
            try:
                target_period = str(post_data.get("period", "")).strip()
                if target_period not in market_updater.SUPPORTED_PERIODS:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": f"Periodo '{target_period}' no soportado."}).encode("utf-8"))
                    return

                updated_payload = market_updater.switch_cached_period(target_period)
                was_cached = updated_payload is not None
                if updated_payload is None:
                    updated_payload = market_updater.run_updater(target_period=target_period)
                    last_auto_sync_time = time.time()

                resp_obj = dict(updated_payload)
                resp_obj["instant_cached"] = was_cached
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(resp_obj, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        if route == "/api/portfolio/upsert":
            try:
                ticker = str(post_data.get("ticker", "")).strip().upper()
                shares = post_data.get("shares")
                avg_price = post_data.get("avg_price")
                custom_sl = post_data.get("custom_sl")
                custom_tp = post_data.get("custom_tp")
                notes = post_data.get("notes", "")
                merge = bool(post_data.get("merge", True))

                # Resolver metadatos desde latest_data.json o detección rápida
                tab = str(post_data.get("tab", "")).strip()
                name = str(post_data.get("name", "")).strip()
                currency = str(post_data.get("currency", "")).strip()
                decimals = post_data.get("decimals")

                latest_path = os.path.join(DIRECTORY, "latest_data.json")
                if os.path.exists(latest_path):
                    try:
                        with open(latest_path, "r", encoding="utf-8") as f:
                            ldata = json.load(f).get("data", [])
                        found = next((it for it in ldata if str(it.get("ticker", "")).upper() == ticker), None)
                        if found:
                            tab = tab or found.get("tab", ticker)
                            name = name or found.get("name", tab)
                            currency = currency or found.get("currency", "$")
                            if decimals is None:
                                decimals = found.get("decimals", 2)
                    except Exception:
                        pass

                if not currency or decimals is None:
                    det_curr, det_dec = market_updater.detect_asset_format(ticker, float(avg_price or 100))
                    currency = currency or det_curr
                    decimals = det_dec if decimals is None else int(decimals)

                portfolio_manager.upsert_position(
                    ticker=ticker,
                    shares=shares,
                    avg_price=avg_price,
                    tab=tab or ticker,
                    name=name or tab or ticker,
                    currency=currency,
                    decimals=int(decimals),
                    custom_sl=custom_sl,
                    custom_tp=custom_tp,
                    notes=notes,
                    merge=merge
                )
                enriched = portfolio_manager.get_enriched_portfolio()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(enriched, ensure_ascii=False).encode("utf-8"))
            except ValueError as ve:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(ve)}, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))
            return

        if route == "/api/portfolio/remove":
            try:
                ticker = str(post_data.get("ticker", "")).strip().upper()
                sell_shares = post_data.get("sell_shares")
                sell_price = post_data.get("sell_price")
                portfolio_manager.remove_or_reduce_position(
                    ticker=ticker,
                    sell_shares=sell_shares,
                    sell_price=sell_price
                )
                enriched = portfolio_manager.get_enriched_portfolio()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(enriched, ensure_ascii=False).encode("utf-8"))
            except ValueError as ve:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(ve)}, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))
            return

        if route == "/api/journal/reset":
            try:
                import journal_manager
                empty_j = {
                    "version": "1.0",
                    "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "stats": {
                        "total_opportunities": 0, "active_count": 0, "closed_count": 0,
                        "win_rate_pct": 0.0, "loss_rate_pct": 0.0, "total_won": 0, "total_lost": 0,
                        "avg_win_pct": 0.0, "avg_loss_pct": 0.0
                    },
                    "entries": []
                }
                journal_manager.save_journal(empty_j)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        if route == "/api/journal/remove":
            try:
                import journal_manager
                entry_id = post_data.get("id")
                clear_closed = bool(post_data.get("clear_closed", False))
                updated = journal_manager.remove_journal_entry(entry_id=entry_id, clear_closed=clear_closed)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "journal": updated}, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))
            return

        if route == "/api/assets/validate":
            try:
                ticker = post_data.get("ticker", "").strip().upper()
                if not ticker:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"valid": False, "error": "Ticker vacío"}).encode("utf-8"))
                    return

                import yfinance as yf
                t = yf.Ticker(ticker)
                hist = t.history(period="5d")
                if hist.empty:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"valid": False, "error": f"No se encontraron datos para '{ticker}' en Yahoo Finance."}).encode("utf-8"))
                    return

                price = float(hist["Close"].iloc[-1])
                curr, dec = market_updater.detect_asset_format(ticker, price)
                # Intentar obtener nombre sugerido
                suggested_name = ticker
                try:
                    info = t.info
                    suggested_name = info.get("shortName") or info.get("longName") or ticker
                except Exception:
                    pass

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "valid": True,
                    "ticker": ticker,
                    "price": round(price, dec),
                    "currency": curr,
                    "decimals": dec,
                    "name": suggested_name
                }, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"valid": False, "error": str(e)}).encode("utf-8"))
            return

        if route == "/api/assets/add":
            try:
                ticker = post_data.get("ticker", "").strip().upper()
                tab = post_data.get("tab", "").strip() or ticker
                name = post_data.get("name", "").strip() or tab

                config = market_updater.load_config()
                assets = config.get("assets", [])

                # Verificar si ya existe
                if any(a["ticker"].upper() == ticker for a in assets):
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": f"El ticker '{ticker}' ya está en tu lista de seguimiento."}).encode("utf-8"))
                    return

                # Validar con Yahoo Finance
                import yfinance as yf
                t = yf.Ticker(ticker)
                hist = t.history(period="5d")
                if hist.empty:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": f"El ticker '{ticker}' no es válido o no tiene cotizaciones."}).encode("utf-8"))
                    return

                # Añadir a config
                new_asset = {"tab": tab, "ticker": ticker, "name": name}
                assets.append(new_asset)
                config["assets"] = assets
                market_updater.save_config(config)

                print(f"\n[Web Dashboard] Activo añadido: {tab} ({ticker}) - {name}. Actualizando mercado...")
                updated_payload = market_updater.run_updater(target_period=config.get("period", "3mo"))
                last_auto_sync_time = time.time()

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(updated_payload, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                print(f"[Web Dashboard] Error al añadir activo: {e}")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        if route == "/api/assets/remove":
            try:
                ticker = post_data.get("ticker", "").strip().upper()
                config = market_updater.load_config()
                assets = config.get("assets", [])

                config["assets"] = [a for a in assets if a["ticker"].upper() != ticker]
                market_updater.save_config(config)

                print(f"\n[Web Dashboard] Activo eliminado: {ticker}. Actualizando datos...")
                updated_payload = market_updater.run_updater(target_period=config.get("period", "3mo"))
                last_auto_sync_time = time.time()

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(updated_payload, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                print(f"[Web Dashboard] Error al eliminar activo: {e}")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        if route == "/api/telegram/test":
            try:
                cfg = market_updater.load_config()
                saved_token = cfg.get("telegram", {}).get("bot_token", "")
                bot_token = resolve_secret(post_data.get("bot_token", ""), saved_token)
                chat_id = post_data.get("chat_id", "").strip()
                ok, msg = telegram_notifier.test_telegram_connection(bot_token, chat_id)
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": ok, "message": msg}, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": str(e)}).encode("utf-8"))
            return

        if route == "/api/telegram/save":
            try:
                cfg = market_updater.load_config()
                saved_token = cfg.get("telegram", {}).get("bot_token", "")
                resolved_token = resolve_secret(post_data.get("bot_token", ""), saved_token)

                cfg["telegram"] = {
                    "enabled": bool(post_data.get("enabled", True)),
                    "bot_token": resolved_token,
                    "chat_id": post_data.get("chat_id", "").strip(),
                    "min_score": int(post_data.get("min_score", 70)),
                    "notify_on_golden_zone": bool(post_data.get("notify_on_golden_zone", True)),
                    "notify_on_high_confluence": bool(post_data.get("notify_on_high_confluence", True))
                }
                market_updater.save_config(cfg)

                safe_tg = dict(cfg["telegram"])
                safe_tg["has_token"] = bool(resolved_token)
                safe_tg["bot_token"] = mask_secret(resolved_token)

                print(f"[Web Dashboard] Configuración de Telegram actualizada (Activo: {cfg['telegram']['enabled']}).")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "telegram": safe_tg}, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        if route == "/api/scheduler/save":
            try:
                cfg = market_updater.load_config()
                prev_smart = cfg.get("scheduler", {}).get("smart_hours_only", True)
                cfg["scheduler"] = {
                    "enabled": bool(post_data.get("enabled", True)),
                    "interval_minutes": int(post_data.get("interval_minutes", 30)),
                    "smart_hours_only": bool(post_data.get("smart_hours_only", prev_smart))
                }
                market_updater.save_config(cfg)
                last_auto_sync_time = time.time()
                print(f"[Web Dashboard] Auto-Scheduler actualizado: {cfg['scheduler']['interval_minutes']} min (Activo: {cfg['scheduler']['enabled']}, SmartHours: {cfg['scheduler']['smart_hours_only']}).")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "scheduler": cfg["scheduler"],
                    "market_hours": market_updater.evaluate_market_hours(cfg.get("assets", []))
                }, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        self.send_error(404, "Endpoint no encontrado")


def run_server():
    # Reservar primero el puerto: una segunda apertura no debe iniciar servicios.
    try:
        httpd = ThreadingFibonacciServer((HOST, PORT), FibonacciHandler)
    except OSError as error:
        if error.errno == errno.EADDRINUSE or getattr(error, "winerror", None) == 10048:
            print(f"El puerto {PORT} ya está ocupado. Usa Iniciar_Aplicacion.bat para abrir el panel existente.")
            return 1
        raise

    with httpd:
        sched_thread = threading.Thread(target=auto_scheduler_worker, daemon=True)
        sched_thread.start()
        telegram_notifier.start_bot_listener_thread()
        print(f"\n=======================================================")
        print(f"  🌐 PANEL WEB 'BUSCAR UN BUEN PRECIO' ACTIVO")
        print(f"  Accede desde tu navegador en:")
        print(f"  👉 http://localhost:{PORT}")
        print(f"=======================================================\n")

        # Abrir navegador automáticamente tras 1 segundo
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor detenido.")


if __name__ == "__main__":
    sys.exit(run_server())
