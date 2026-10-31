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
        if self.path == "/api/sync":
            try:
                content_len = int(self.headers.get('Content-Length', 0))
                target_period = None
                if content_len > 0:
                    post_body = self.rfile.read(content_len)
                    try:
                        req_json = json.loads(post_body.decode('utf-8'))
                        target_period = req_json.get("period")
                    except Exception:
                        pass

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
