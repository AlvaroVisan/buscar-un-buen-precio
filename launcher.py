"""Arranque único del panel, sin dependencias externas para diagnosticar fallos."""

import http.client
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import webbrowser

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 5050
APP_ID = "buscar-un-buen-precio"
PANEL_URL = f"http://{HOST}:{PORT}/"


def _read_response(path, host, port):
    connection = http.client.HTTPConnection(host, port, timeout=3)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read(1024 * 1024).decode("utf-8", errors="replace")
    finally:
        connection.close()


def _port_is_available(host, port):
    """Comprobar bind evita confundir un timeout de conexión con un puerto ocupado."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            if os.name == "nt":
                candidate.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            candidate.bind((host, port))
        return True
    except OSError:
        return False


def probe_panel(host=HOST, port=PORT):
    """Devuelve running/free/occupied sin confundir otro servicio con el panel."""
    if _port_is_available(host, port):
        return "free"

    try:
        status, body = _read_response("/api/health", host, port)
        if status == 200:
            try:
                health = json.loads(body)
            except ValueError:
                health = None
            if isinstance(health, dict) and health.get("application") == APP_ID:
                return "running"

        # Reconocer también una instancia anterior a este lanzador.
        status, body = _read_response("/", host, port)
        if status == 200 and "Buscar un Buen Precio | Monitor Fibonacci &amp; TradingView" in body:
            return "running"
        if status == 200 and "Buscar un Buen Precio | Monitor Fibonacci & TradingView" in body:
            return "running"
    except (OSError, http.client.HTTPException):
        pass
    return "occupied"


def open_panel():
    try:
        if webbrowser.open(PANEL_URL):
            return
    except (webbrowser.Error, OSError):
        pass
    print(f"Abre esta dirección en tu navegador: {PANEL_URL}")


def main():
    status = probe_panel()
    if status == "running":
        print("La aplicación ya está funcionando. Abriendo el panel existente...")
        open_panel()
        return 0
    if status == "occupied":
        print(f"No se puede iniciar: el puerto {PORT} está ocupado o no responde como este panel.")
        print("Cierra el programa que utiliza ese puerto y vuelve a intentarlo.")
        return 1

    missing = [module for module in ("yfinance", "requests", "pandas")
               if importlib.util.find_spec(module) is None]
    if missing:
        print("Faltan dependencias: " + ", ".join(missing))
        print("Para instalarlas, abre una terminal en esta carpeta y ejecuta:")
        print(f'"{sys.executable}" -m pip install -r requirements.txt')
        return 1
    if not (ROOT / "app.py").is_file():
        print("No se encuentra app.py. Conserva el lanzador junto a los archivos del proyecto.")
        return 1

    print("Iniciando panel, actualizador automático y bot de Telegram configurado...")
    print("Mantén esta ventana abierta para que los servicios sigan funcionando.")
    print("Para detener la aplicación, pulsa Ctrl+C en esta ventana.")
    try:
        completed = subprocess.run([sys.executable, "-u", str(ROOT / "app.py")], cwd=ROOT)
    except KeyboardInterrupt:
        return 0
    except OSError as error:
        print(f"No se pudo iniciar Python: {error}")
        return 1
    if completed.returncode and probe_panel() == "running":
        # Otra apertura pudo ganar el puerto entre la comprobación y el arranque.
        print("Otra instancia ya ha iniciado la aplicación. Abriendo ese panel...")
        open_panel()
        return 0
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
