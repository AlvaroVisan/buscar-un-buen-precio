"""Arranque, reutilización y errores sin abrir navegador ni iniciar el bot."""

import errno
import subprocess
import threading
import unittest
from unittest.mock import patch

import app
import launcher


class LauncherTests(unittest.TestCase):
    def test_running_panel_opens_without_starting_services_or_checking_dependencies(self):
        with patch.object(launcher, "probe_panel", return_value="running"), \
                patch.object(launcher, "open_panel") as browser, \
                patch.object(launcher.subprocess, "run") as start, \
                patch.object(launcher.importlib.util, "find_spec") as dependency:
            self.assertEqual(launcher.main(), 0)
        browser.assert_called_once()
        start.assert_not_called()
        dependency.assert_not_called()

    def test_occupied_port_never_starts_services(self):
        with patch.object(launcher, "probe_panel", return_value="occupied"), \
                patch.object(launcher.subprocess, "run") as start, \
                patch.object(launcher, "open_panel") as browser:
            self.assertEqual(launcher.main(), 1)
        start.assert_not_called()
        browser.assert_not_called()

    def test_missing_dependencies_produce_actionable_error(self):
        with patch.object(launcher, "probe_panel", return_value="free"), \
                patch.object(launcher.importlib.util, "find_spec", return_value=None), \
                patch.object(launcher.subprocess, "run") as start, \
                patch("builtins.print") as output:
            self.assertEqual(launcher.main(), 1)
        start.assert_not_called()
        self.assertIn("pip install -r requirements.txt", str(output.call_args_list))

    def test_new_instance_uses_same_python_and_project_directory(self):
        with patch.object(launcher, "probe_panel", return_value="free"), \
                patch.object(launcher.importlib.util, "find_spec", return_value=object()), \
                patch.object(launcher.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as start:
            self.assertEqual(launcher.main(), 0)
        start.assert_called_once_with([launcher.sys.executable, "-u", str(launcher.ROOT / "app.py")], cwd=launcher.ROOT)

    def test_simultaneous_launch_reuses_instance_that_won_the_port(self):
        with patch.object(launcher, "probe_panel", side_effect=["free", "running"]), \
                patch.object(launcher.importlib.util, "find_spec", return_value=object()), \
                patch.object(launcher.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)), \
                patch.object(launcher, "open_panel") as browser:
            self.assertEqual(launcher.main(), 0)
        browser.assert_called_once()

    def test_server_reserves_port_before_starting_bot_or_scheduler(self):
        with patch.object(app, "ThreadingFibonacciServer", side_effect=OSError(errno.EADDRINUSE, "Port in use")), \
                patch.object(app.threading, "Thread") as thread, \
                patch.object(app.telegram_notifier, "start_bot_listener_thread") as bot:
            self.assertEqual(app.run_server(), 1)
        thread.assert_not_called()
        bot.assert_not_called()


class ProbeTests(unittest.TestCase):
    def test_free_port(self):
        with launcher.socket.socket() as temporary:
            temporary.bind((app.HOST, 0))
            port = temporary.getsockname()[1]
        # Una conexión lenta o bloqueada no debe impedir detectar un puerto libre.
        with patch.object(launcher.socket, "create_connection", side_effect=TimeoutError):
            self.assertEqual(launcher.probe_panel(port=port), "free")

    def test_old_panel_is_recognized(self):
        with patch.object(launcher, "_port_is_available", return_value=False), \
                patch.object(launcher, "_read_response", side_effect=[
                    (404, "missing"), (200, "<title>Buscar un Buen Precio | Monitor Fibonacci &amp; TradingView</title>")]):
            self.assertEqual(launcher.probe_panel(), "running")

    def test_other_service_is_not_treated_as_panel(self):
        with patch.object(launcher, "_port_is_available", return_value=False), \
                patch.object(launcher, "_read_response", side_effect=[(200, "{}"), (200, "Other application")]):
            self.assertEqual(launcher.probe_panel(), "occupied")

    def test_new_panel_health_and_exclusive_bind_on_real_local_socket(self):
        server = app.ThreadingFibonacciServer((app.HOST, 0), app.FibonacciHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_port
            self.assertEqual(launcher.probe_panel(port=port), "running")
            with self.assertRaises(OSError):
                app.ThreadingFibonacciServer((app.HOST, port), app.FibonacciHandler)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
