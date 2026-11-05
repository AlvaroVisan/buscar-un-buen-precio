"""Cambio de presentación con red y Telegram simulados."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import euro_display as euro
import telegram_notifier as bot


class EuroDisplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.quote = dict(base="EUR", quote="USD", rate=1.25, date=datetime.now(timezone.utc).date().isoformat())
        for name, value in (("CACHE_PATH", self.root / 'rate.json'), ("_quote", None), ("_fetched_at", 0), ("_last_attempt", 0)):
            patcher = patch.object(euro, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_prices_negatives_totals_and_crypto_precision(self):
        with patch.object(euro, 'get_quote', return_value=self.quote) as quote:
            result = euro.render_message('AMD $125.00 · Stop $100.00 · Total $1,250.00 · PnL $-12.50 · cripto $0.001250 · €100.00 · 10 títulos · +5% · BTC-USD')
        quote.assert_called_once()
        for expected in ('100,00 €', '80,00 €', '1.000,00 €', '-10,00 €', '0,001000 €', '10 títulos', '+5%', 'BTC-USD'):
            self.assertIn(expected, result)
        self.assertNotIn('$', result)

    def test_native_euros_and_plain_text_do_not_fetch_a_rate(self):
        with patch.object(euro, 'get_quote') as quote:
            self.assertEqual(euro.render_message('€100.00'), '100,00 €')
            self.assertEqual(euro.render_message('/ver BTC-USD · 1 de 2'), '/ver BTC-USD · 1 de 2')
            quote.assert_not_called()

    def test_failure_never_relabels_dollars_as_euros(self):
        with patch.object(euro, 'get_quote', return_value=None):
            result = euro.render_message('AMD $125.00')
        self.assertIn('$125.00', result)
        self.assertIn('moneda original', result)
        self.assertNotIn('125,00 €', result)

    def test_rate_is_cached_on_disk_and_reused_without_network(self):
        response = Mock()
        response.json.return_value = self.quote
        with patch.object(euro.requests, 'get', return_value=response) as get:
            self.assertEqual(euro.get_quote()['rate'], 1.25)
            euro._quote = None
            self.assertEqual(euro.get_quote()['rate'], 1.25)
        get.assert_called_once()
        self.assertTrue(euro.CACHE_PATH.exists())

    def test_recent_cached_rate_survives_network_failure_and_limits_retries(self):
        euro.CACHE_PATH.write_text(json.dumps({**self.quote, 'fetched_at': 0}), encoding='utf-8')
        with patch.object(euro.requests, 'get', side_effect=euro.requests.ConnectionError('offline')) as get:
            self.assertEqual(euro.get_quote()['rate'], 1.25)
            self.assertEqual(euro.get_quote()['rate'], 1.25)
        get.assert_called_once()

    def test_invalid_or_old_rate_is_rejected(self):
        for fields in (dict(rate=0), dict(rate=float('nan')), dict(base='USD'), dict(date='2026-02-30'), dict(date=(datetime.now(timezone.utc).date() - timedelta(days=8)).isoformat())):
            self.assertFalse(euro._valid({**self.quote, **fields}))

    def test_transport_sends_euros_and_keeps_keyboard_and_parse_fallback(self):
        rejected = Mock(status_code=400)
        rejected.json.return_value = dict(ok=False, description="can't parse entities")
        accepted = Mock(status_code=200)
        accepted.json.return_value = dict(ok=True, result={'message_id': 1})
        keyboard = {'inline_keyboard': [[{'text': 'Ver', 'callback_data': 'ver:AMD'}]]}
        with patch.object(euro, 'get_quote', return_value=self.quote), patch.object(bot.requests, 'post', side_effect=[rejected, accepted]) as post:
            self.assertTrue(bot.send_telegram_message('fake', 'fake', 'Entrada `$125.00`', reply_markup=keyboard)[0])
        for call in post.call_args_list:
            self.assertIn('100,00 €', call.kwargs['json']['text'])
            self.assertEqual(call.kwargs['json']['reply_markup'], keyboard)
        self.assertNotIn('parse_mode', post.call_args_list[-1].kwargs['json'])

    def test_index_levels_remain_points(self):
        raw = bot._fmt_price(5000, dict(ticker='^GSPC', currency='$'))
        with patch.object(euro, 'get_quote') as quote:
            self.assertIn('puntos', euro.render_message(raw))
            quote.assert_not_called()

    def test_risk_budget_is_euros_before_sizing_and_does_not_change_data(self):
        path = self.root / 'data.json'
        item = dict(ticker='AMD', tab='AMD', current_price=125, currency='$', risk_mgmt=dict(entry_price=125, stop_loss=112.5, risk_per_share=12.5, take_profit_1=150, take_profit_2=175))
        path.write_text(json.dumps({'data': [item]}), encoding='utf-8')
        before = path.read_bytes()
        with patch.object(bot, 'LATEST_DATA_PATH', str(path)), patch.object(euro, 'get_quote', return_value=self.quote), patch.object(bot, 'journal_tracking_context', return_value=''), patch.object(bot, 'send_telegram_message') as send:
            bot.handle_riesgo('fake', 'fake', 'AMD 100')
        text = send.call_args.args[2]
        self.assertIn('*10 títulos*', text)
        self.assertIn('$125.00', text)
        with patch.object(euro, 'get_quote', return_value=self.quote):
            displayed = euro.render_message(text)
        self.assertIn('100,00 €', displayed)
        self.assertIn('1.000,00 €', displayed)
        self.assertNotIn('$', displayed)
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
