"""Datos ficticios de 15 minutos; la calma nunca equivale a una compra."""
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd
from stabilization_context import analyze_stabilization
from market_updater import fetch_rebound_bars
import telegram_notifier as bot
from scenario_engine import advance


def rows(closes=None, size=6):
    closes = closes or [100, 100.1, 100, 100.1, 100, 100.05][:size]
    start = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)
    values = []
    for i, close in enumerate([100] * 4 + closes):
        spread = 2 if i < 4 else .2
        values.append(dict(time=(start + timedelta(minutes=15 * i)).strftime('%Y-%m-%d %H:%M:%S'), High=close + spread, Low=close - spread, Close=close))
    return values


def now(data):
    return datetime.fromisoformat(data[-1]['time']).replace(tzinfo=timezone.utc) + timedelta(minutes=1)


class StabilizationTests(unittest.TestCase):
    def test_narrow_sideways_range_is_context_only_and_preserves_inputs(self):
        data = rows()
        before = copy.deepcopy(data)
        result = analyze_stabilization(data, 100, now(data))
        self.assertEqual(result['state'], 'LATERAL')
        self.assertEqual(result['window_minutes'], 90)
        self.assertEqual(result['support'], 99.8)
        self.assertFalse(result['is_entry_signal'])
        self.assertEqual(data, before)
        json.dumps(result, allow_nan=False)
        state = {'entries': []}
        self.assertEqual(advance(state, [dict(ticker='TEST', current_price=100, score=10, stabilization=result)], {}, '2026-01-05 18:00:00'), set())
        self.assertEqual(state['entries'], [])
        self.assertEqual(state['accumulation'], [])

    def test_first_hour_is_only_attempting_a_base(self):
        data = rows(size=4)
        self.assertEqual(analyze_stabilization(data, 100, now(data))['state'], 'FORMING_BASE')

    def test_already_quiet_range_does_not_need_another_contraction(self):
        data = rows()
        for row in data:
            row['High'], row['Low'] = row['Close'] + .1, row['Close'] - .1
        self.assertEqual(analyze_stabilization(data, 100, now(data))['state'], 'LATERAL')

    def test_shrinking_downtrend_is_not_called_a_floor(self):
        data = rows([100, 99.8, 99.6, 99.4, 99.2, 99])
        result = analyze_stabilization(data, 99, now(data))
        self.assertLess(result['contraction_ratio'], .8)
        self.assertEqual(result['state'], 'FALLING')

    def test_directional_rebound_is_not_lateral(self):
        data = rows([100, 101, 102, 103, 104, 105])
        self.assertEqual(analyze_stabilization(data, 105, now(data))['state'], 'REBOUND')

    def test_live_price_breaks_the_range_without_creating_a_signal(self):
        data = rows()
        for price, expected in ((99, 'BREAKING_DOWN'), (102, 'BREAKING_UP')):
            result = analyze_stabilization(data, price, now(data))
            self.assertEqual(result['state'], expected)
            self.assertFalse(result['is_entry_signal'])

    def test_insufficient_old_missing_and_unfinished_candles(self):
        data = rows()
        self.assertEqual(analyze_stabilization(data[:3], 100, now(data))['state'], 'STALE')
        self.assertEqual(analyze_stabilization(data[-3:], 100, now(data))['state'], 'INSUFFICIENT')
        self.assertEqual(analyze_stabilization(data, 100, now(data) + timedelta(hours=2))['state'], 'STALE')
        gap = copy.deepcopy(data)
        gap[-1]['time'] = (now(data) + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
        self.assertEqual(analyze_stabilization(gap, 100, now(gap))['state'], 'INSUFFICIENT')
        future = dict(time=(now(data) + timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S'), High=200, Low=10, Close=100)
        self.assertEqual(analyze_stabilization(data + [future], 100, now(data)), analyze_stabilization(data, 100, now(data)))
        self.assertEqual(analyze_stabilization(data, float('nan'), now(data))['state'], 'INSUFFICIENT')

    def test_fifteen_minute_download_excludes_open_candle(self):
        from unittest.mock import Mock
        ticker = Mock()
        ticker.history.return_value = pd.DataFrame(dict(High=[101, 101], Low=[99, 99], Close=[100, 100]), index=pd.date_range('2026-01-05 14:30', periods=2, freq='15min', tz='UTC'))
        result = fetch_rebound_bars(ticker, datetime(2026, 1, 5, 14, 50, tzinfo=timezone.utc), interval='15m')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['time'], '2026-01-05 14:45:00')
        ticker.history.assert_called_once_with(period='5d', interval='15m')

    def test_bot_explains_range_without_changing_entry_rules(self):
        data = rows()
        context = analyze_stabilization(data, 100, now(data))
        item = dict(ticker='TEST', tab='TEST', current_price=100, currency='$', drop_pct=30, stabilization=context)
        with patch('journal_manager.get_scenario_context', return_value={'confirmation': None, 'watch': None, 'accumulation': None}):
            text = bot.format_buy_advice(item)
            sell_text = bot.format_sell_advice(item)
        self.assertIn('se calme ayuda', text)
        self.assertIn('90 minutos', text)
        self.assertIn('no una señal para comprar', text)
        self.assertNotIn('entramos de una', text)
        self.assertLess(len(text), 4096)
        self.assertIn('franja', sell_text.lower())


if __name__ == '__main__':
    unittest.main()
