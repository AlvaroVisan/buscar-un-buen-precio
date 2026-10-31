import http.server
import socketserver
import json
import os
import sys
import webbrowser
import threading
import time
import market_updater
import telegram_notifier

PORT = 5050
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
last_auto_sync_time = time.time()

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

            if not enabled or interval_min <= 0:
                continue

            interval_sec = interval_min * 60
            now = time.time()
            if now - last_auto_sync_time >= interval_sec:
                last_auto_sync_time = now
                period = cfg.get("period", "3mo")
                print(f"\n[Auto-Scheduler] ⏰ Intervalo de {interval_min}m alcanzado. Sincronizando precios y comprobando alertas móviles...")
                market_updater.run_updater(target_period=period)
        except Exception as e:
            print(f"[Auto-Scheduler] ⚠️ Error en ciclo automático: {e}")

class FibonacciHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        if self.path == "/api/data":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            latest_path = os.path.join(DIRECTORY, "latest_data.json")
            if os.path.exists(latest_path):
                with open(latest_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.wfile.write(b"{}")
            return
        
        if self.path == "/api/config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            cfg_path = os.path.join(DIRECTORY, "config.json")
            if os.path.exists(cfg_path):
                with open(cfg_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.wfile.write(b"{}")
            return

        if self.path == "/api/scheduler/status":
            cfg = market_updater.load_config()
            sched_cfg = cfg.get("scheduler", {})
            interval_min = sched_cfg.get("interval_minutes", 30)
            enabled = sched_cfg.get("enabled", True)
            elapsed = time.time() - last_auto_sync_time
            remaining = max(0, int((interval_min * 60) - elapsed)) if enabled else None

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "enabled": enabled,
                "interval_minutes": interval_min,
                "remaining_seconds": remaining,
                "telegram": cfg.get("telegram", {})
            }, ensure_ascii=False).encode("utf-8"))
            return

        if self.path == "/api/journal":
            try:
                import journal_manager
                j_data = journal_manager.load_journal()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(j_data, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        return super().do_GET()

    def do_POST(self):
        content_len = int(self.headers.get('Content-Length', 0))
        post_data = {}
        if content_len > 0:
            try:
                body = self.rfile.read(content_len)
                post_data = json.loads(body.decode('utf-8'))
            except Exception:
                pass

        if self.path == "/api/sync":
            try:
                target_period = post_data.get("period")
                print(f"\n[Web Dashboard] Solicitud de sincronización recibida (Periodo: {target_period or 'configurado'})...")
                updated_payload = market_updater.run_updater(target_period=target_period)

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

        if self.path == "/api/journal/reset":
            try:
                import journal_manager
                empty_j = {
                    "version": "1.0",
                    "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "stats": {
                        "total_opportunities": 0, "active_count": 0, "closed_count": 0,
                        "win_rate_pct": 0.0, "total_won": 0, "total_lost": 0,
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

        if self.path == "/api/assets/validate":
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
                    "price": round(price, 2),
                    "name": suggested_name
                }, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"valid": False, "error": str(e)}).encode("utf-8"))
            return

        if self.path == "/api/assets/add":
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

        if self.path == "/api/assets/remove":
            try:
                ticker = post_data.get("ticker", "").strip().upper()
                config = market_updater.load_config()
                assets = config.get("assets", [])

                config["assets"] = [a for a in assets if a["ticker"].upper() != ticker]
                market_updater.save_config(config)

                print(f"\n[Web Dashboard] Activo eliminado: {ticker}. Actualizando datos...")
                updated_payload = market_updater.run_updater(target_period=config.get("period", "3mo"))

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

        if self.path == "/api/telegram/test":
            try:
                bot_token = post_data.get("bot_token", "").strip()
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

        if self.path == "/api/telegram/save":
            try:
                cfg = market_updater.load_config()
                cfg["telegram"] = {
                    "enabled": bool(post_data.get("enabled", True)),
                    "bot_token": post_data.get("bot_token", "").strip(),
                    "chat_id": post_data.get("chat_id", "").strip(),
                    "min_score": int(post_data.get("min_score", 70)),
                    "notify_on_golden_zone": bool(post_data.get("notify_on_golden_zone", True)),
                    "notify_on_high_confluence": bool(post_data.get("notify_on_high_confluence", True))
                }
                market_updater.save_config(cfg)
                print(f"[Web Dashboard] Configuración de Telegram actualizada (Activo: {cfg['telegram']['enabled']}).")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "telegram": cfg["telegram"]}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        if self.path == "/api/scheduler/save":
            try:
                cfg = market_updater.load_config()
                cfg["scheduler"] = {
                    "enabled": bool(post_data.get("enabled", True)),
                    "interval_minutes": int(post_data.get("interval_minutes", 30))
                }
                market_updater.save_config(cfg)
                global last_auto_sync_time
                last_auto_sync_time = time.time()
                print(f"[Web Dashboard] Auto-Scheduler actualizado: {cfg['scheduler']['interval_minutes']} min (Activo: {cfg['scheduler']['enabled']}).")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "scheduler": cfg["scheduler"]}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        self.send_error(404, "Endpoint no encontrado")

def run_server():
    socketserver.TCPServer.allow_reuse_address = True
    
    # Iniciar hilo de sincronización automática en segundo plano
    sched_thread = threading.Thread(target=auto_scheduler_worker, daemon=True)
    sched_thread.start()

    # Iniciar hilo de escucha interactiva de Telegram (comandos bajo demanda)
    telegram_notifier.start_bot_listener_thread()

    with socketserver.TCPServer(("", PORT), FibonacciHandler) as httpd:
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
    run_server()
