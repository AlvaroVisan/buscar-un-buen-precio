"""Pruebas HTTP locales sin arrancar scheduler, bot ni acceder a datos privados."""

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import app


class LocalServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        (root / "index.html").write_text("panel de prueba", encoding="utf-8")
        (root / "secrets.json").write_text('{"test": true}', encoding="utf-8")
        cls.directory_patch = patch.object(app, "DIRECTORY", cls.temporary.name)
        cls.directory_patch.start()
        cls.server = app.ThreadingFibonacciServer((app.HOST, 0), app.FibonacciHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.directory_patch.stop()
        cls.temporary.cleanup()

    def request(self, method="GET", path="/", headers=None, body=None):
        connection = http.client.HTTPConnection(app.HOST, self.port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_archive_endpoint_and_validation(self):
        headers = {"Content-Type": "application/json"}
        with patch("journal_manager.archive_journal_entries", return_value={"changed_ids": ["loss"], "journal": {}}) as archive:
            status, _, body = self.request("POST", "/api/journal/archive", headers, '{"ids":["loss"]}')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["changed_ids"], ["loss"])
            archive.assert_called_once_with(entry_ids=["loss"], clear_closed=False, archived=True)
        with patch("journal_manager.archive_journal_entries", side_effect=ValueError("Invalid")):
            self.assertEqual(self.request("POST", "/api/journal/archive", headers, '{}')[0], 400)
        with patch("journal_manager.archive_journal_entries") as archive:
            self.assertEqual(self.request("POST", "/api/journal/archive", {**headers, "Origin": "https://example.com"}, '{}')[0], 403)
            archive.assert_not_called()

    def test_fx_endpoint_uses_shared_quote(self):
        with patch('euro_display.get_quote', return_value=dict(base='EUR', quote='USD', rate=1.25, date='2026-11-05')):
            status, _, body = self.request(path='/api/fx')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['rate'], 1.25)

    def test_euro_purchase_and_sale_are_saved_in_native_currency(self):
        headers = {'Content-Type': 'application/json'}
        body = dict(ticker='AMD', shares=2, avg_price=100, custom_sl=80, custom_tp=160, input_currency='EUR', input_rate=1.25)
        with patch('portfolio_manager.load_portfolio', return_value={'positions': []}), patch('portfolio_manager.upsert_position') as upsert, patch('portfolio_manager.get_enriched_portfolio', return_value={}):
            self.assertEqual(self.request('POST', '/api/portfolio/upsert', headers, json.dumps(body))[0], 200)
        self.assertEqual(upsert.call_args.kwargs['avg_price'], 125)
        self.assertEqual(upsert.call_args.kwargs['custom_sl'], 100)
        self.assertEqual(upsert.call_args.kwargs['custom_tp'], 200)
        self.assertEqual(upsert.call_args.kwargs['currency'], '$')
        with patch('portfolio_manager.load_portfolio', return_value={'positions': [{'ticker': 'AMD', 'currency': '$'}]}), patch('portfolio_manager.remove_or_reduce_position') as remove, patch('portfolio_manager.get_enriched_portfolio', return_value={}):
            sale = dict(ticker='AMD', sell_shares=1, sell_price=120, input_currency='EUR', input_rate=1.25)
            self.assertEqual(self.request('POST', '/api/portfolio/remove', headers, json.dumps(sale))[0], 200)
        self.assertEqual(remove.call_args.kwargs['sell_price'], 150)

    def test_euro_purchase_without_rate_does_not_write(self):
        with patch('portfolio_manager.load_portfolio', return_value={'positions': []}), patch('portfolio_manager.upsert_position') as upsert:
            body = dict(ticker='AMD', shares=1, avg_price=100, input_currency='EUR')
            status, _, _ = self.request('POST', '/api/portfolio/upsert', {'Content-Type': 'application/json'}, json.dumps(body))
        self.assertEqual(status, 400)
        upsert.assert_not_called()

    def test_existing_native_euro_position_is_not_converted_again(self):
        with patch('portfolio_manager.load_portfolio', return_value={'positions': [{'ticker': 'AMD', 'currency': '€'}]}), patch('portfolio_manager.upsert_position') as upsert, patch('portfolio_manager.get_enriched_portfolio', return_value={}):
            body = dict(ticker='AMD', shares=1, avg_price=100, input_currency='EUR', input_rate=1.25)
            status, _, _ = self.request('POST', '/api/portfolio/upsert', {'Content-Type': 'application/json'}, json.dumps(body))
        self.assertEqual(status, 200)
        self.assertEqual(upsert.call_args.kwargs['currency'], '€')
        self.assertEqual(upsert.call_args.kwargs['avg_price'], 100)

    def test_local_panel_and_security_headers(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        for host in ("localhost", "127.0.0.1"):
            with self.subTest(host=host):
                status, headers, body = self.request(headers={"Host": f"{host}:{self.port}"})
                self.assertEqual(status, 200)
                self.assertEqual(body, b"panel de prueba")
                self.assertEqual(headers["X-Frame-Options"], "DENY")
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_foreign_host_and_origins_cannot_read_api(self):
        cases = [
            {"Host": f"example.com:{self.port}"},
            {"Origin": "https://example.com"},
            {"Origin": "null"},
            {"Origin": "http://localhost:9999"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Sec-Fetch-Site": "same-site"},
        ]
        with patch.object(app.portfolio_manager, "get_enriched_portfolio") as read:
            for headers in cases:
                with self.subTest(headers=headers):
                    self.assertEqual(self.request(path="/api/portfolio", headers=headers)[0], 403)
            read.assert_not_called()

    def test_foreign_posts_and_forms_cannot_change_data(self):
        with patch.object(app.market_updater, "switch_cached_period") as change:
            self.assertEqual(self.request("POST", "/api/period", {"Origin": "https://example.com", "Content-Type": "application/json"}, '{"period":"3mo"}')[0], 403)
            self.assertEqual(self.request("POST", "/api/period", {"Content-Type": "text/plain"}, '{"period":"3mo"}')[0], 415)
            change.assert_not_called()

    def test_same_origin_json_post_and_bodyless_post_work(self):
        origin = f"http://127.0.0.1:{self.port}"
        with patch.object(app.market_updater, "switch_cached_period", return_value={}) as change:
            self.assertEqual(self.request("POST", "/api/period", {"Origin": origin, "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"}, '{"period":"3mo"}')[0], 200)
            change.assert_called_once_with("3mo")
        with patch("journal_manager.save_journal") as save:
            self.assertEqual(self.request("POST", "/api/journal/reset", {"Origin": origin})[0], 200)
            save.assert_called_once()
        with patch("journal_manager.remove_journal_entry", return_value={"entries": []}) as rem:
            status, _, body = self.request("POST", "/api/journal/remove", {"Origin": origin, "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"}, '{"clear_closed":true}')
            self.assertEqual(status, 200)
            rem.assert_called_once_with(entry_id=None, clear_closed=True)

    def test_private_files_are_blocked_for_get_and_head(self):
        for method in ("GET", "HEAD"):
            with self.subTest(method=method):
                self.assertEqual(self.request(method, "/secrets.json")[0], 403)

    def test_business_only_queries_tracked_companies(self):
        config = {"assets": [{"ticker": "AMD"}, {"ticker": "^GSPC"}]}
        with patch.object(app.market_updater, "load_config", return_value=config), \
                patch.object(app.business_context, "get_business_context", return_value={"label": "Mixta"}) as read:
            for ticker in ("UNKNOWN", "^GSPC", ""):
                self.assertEqual(self.request(path=f"/api/business?ticker={ticker}")[0], 400)
            read.assert_not_called()
            status, _, body = self.request(path="/api/business?ticker=AMD")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), {"label": "Mixta"})
            read.assert_called_once_with("AMD")

    def test_business_cache_is_private(self):
        self.assertEqual(self.request(path="/.business_cache.json")[0], 403)

    def test_journal_is_the_only_tracking_source_and_old_archive_is_private(self):
        with patch("journal_manager.load_journal", return_value={"entries": [], "stats": {"win_rate_pct": 50}}):
            status, _, body = self.request(path="/api/journal")
            result = json.loads(body)
            self.assertEqual(status, 200)
            self.assertEqual(result["stats"]["win_rate_pct"], 50)
            self.assertNotIn("followed_plans", result)
        for method in ("GET", "HEAD"):
            self.assertEqual(self.request(method, "/.trade_plans.json")[0], 403)


if __name__ == "__main__":
    unittest.main()
