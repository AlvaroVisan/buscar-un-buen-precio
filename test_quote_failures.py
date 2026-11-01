import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import market_updater as market
import portfolio_manager as portfolio
import journal_manager
import telegram_notifier


class QuoteFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'latest_data.json'
        self.config = {'assets': [{'ticker': 'AAA'}, {'ticker': 'BBB'}], 'period': '3mo'}
        for module, name, value in [(market, 'LATEST_DATA_PATH', str(self.path)), (portfolio, 'LATEST_DATA_PATH', str(self.path))]:
            p = patch.object(module, name, value)
            p.start()
            self.addCleanup(p.stop)

    def update(self, fetch):
        with patch.object(market, 'load_config', return_value=self.config), patch.object(market, 'fetch_asset_data', side_effect=fetch), patch.object(market, 'fetch_cnn_fear_and_greed', return_value={}), patch.object(market, 'evaluate_market_hours', return_value={}), patch.object(market, 'print_summary_table'), patch.object(telegram_notifier, 'dispatch_telegram_alerts') as alerts, patch.object(journal_manager, 'update_journal_with_market_data') as journal:
            result = market.run_updater(sync_sheets=False)
            self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), result)
            self.assertTrue(all(not it.get('is_stale') for it in alerts.call_args.args[0]['data']))
            self.assertTrue(all(not it.get('is_stale') for it in journal.call_args.args[0]))
            return result

    def test_failure_retains_price_and_date_then_recovers(self):
        self.path.write_text(json.dumps({'timestamp': '2026-01-01 12:00:00', 'data': [{'ticker': 'AAA', 'current_price': 110}]}), encoding='utf-8')
        def partial(asset, **kwargs):
            if asset['ticker'] == 'AAA':
                raise RuntimeError('simulated download failure')
            return {'ticker': 'BBB', 'current_price': 20}, None
        result = self.update(partial)
        self.assertEqual([it['ticker'] for it in result['data']], ['AAA', 'BBB'])
        old = result['data'][0]
        self.assertEqual(old['current_price'], 110)
        self.assertEqual(old['last_success_at'], '2026-01-01 12:00:00')
        self.assertTrue(old['is_stale'])
        result = self.update(lambda *a, **k: (None, None))
        self.assertEqual(result['data'][0]['last_success_at'], old['last_success_at'])
        result = self.update(lambda asset, **k: ({'ticker': asset['ticker'], 'current_price': 120}, None))
        self.assertTrue(all(not it['is_stale'] for it in result['data']))
        self.assertEqual(result['failed_tickers'], [])

    def test_first_download_failure_is_explicit(self):
        result = self.update(lambda *a, **k: (None, None))
        self.assertEqual(result['data'], [])
        self.assertCountEqual(result['failed_tickers'], ['AAA', 'BBB'])

    def test_invalid_quote_falls_back(self):
        self.path.write_text(json.dumps({'timestamp': 'old', 'data': [{'ticker': 'AAA', 'current_price': 110}]}), encoding='utf-8')
        result = self.update(lambda asset, **k: ({'ticker': asset['ticker'], 'current_price': float('nan')}, None))
        self.assertEqual(result['data'][0]['current_price'], 110)
        self.assertTrue(result['data'][0]['is_stale'])

    def test_portfolio_missing_quote_does_not_fabricate_pnl(self):
        positions = [{'ticker': t, 'shares': 2, 'avg_price': 100} for t in ('AAA', 'BBB')]
        with patch.object(portfolio, 'load_portfolio', return_value={'positions': positions}):
            result = portfolio.get_enriched_portfolio([{'ticker': 'AAA', 'current_price': 110, 'is_stale': True}])
        missing = result['positions'][1]
        self.assertIsNone(missing['current_price'])
        self.assertIsNone(missing['pnl_abs'])
        self.assertIsNone(missing['pnl_pct'])
        self.assertEqual(missing['status_code'], 'NO_QUOTE')
        self.assertEqual(result['positions'][0]['status_code'], 'STALE_QUOTE')
        self.assertEqual(result['summary']['primary_market_val'], 220)
        self.assertEqual(result['summary']['primary_pnl_abs'], 20)
        self.assertTrue(result['summary']['valuation_incomplete'])
        self.assertEqual(result['summary']['missing_quotes_count'], 1)


if __name__ == '__main__':
    unittest.main()
