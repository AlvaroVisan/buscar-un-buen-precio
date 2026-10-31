import http.server
import socketserver
import json
import os
import sys
import webbrowser
import threading
import market_updater

PORT = 5050
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

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

        self.send_error(404, "Endpoint no encontrado")

def run_server():
    socketserver.TCPServer.allow_reuse_address = True
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
