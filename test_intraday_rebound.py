"""Picos horarios: velas completas, sin duplicados ni entradas por datos ausentes."""
import unittest
from unittest.mock import Mock

import pandas as pd
from market_updater import fetch_rebound_bars
from scenario_engine import advance
from test_scenario_engine import history, item


class IntradayReboundTests(unittest.TestCase):
    def test_download_excludes_unfinished_hour(self):
        ticker = Mock()
        ticker.history.return_value = pd.DataFrame({"High": [101, 102, 103], "Low": [99, 100, 101], "Close": [100, 101, 102]}, index=pd.date_range("2026-01-05 08:00", periods=3, freq="h", tz="UTC"))
        rows = fetch_rebound_bars(ticker, pd.Timestamp("2026-01-05 10:30", tz="UTC").to_pydatetime())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["time"], "2026-01-05 10:00:00")
        ticker.history.assert_called_once_with(period="5d", interval="60m")

    def test_two_hourly_closes_confirm_same_frozen_roof(self):
        data = item(100)
        data['rebound_bars'] = [dict(time=f"2026-01-05 {hour:02d}:00:00", High=101, Low=99, Close=100) for hour in range(7, 11)]
        state = {"entries": [], "watches": {"TEST": dict(since="2026-01-01", breakout=514.61)}}
        self.assertEqual(advance(state, [data], {"TEST": history([100]*4)}, "2026-01-05 10:05:00+00:00"), set())
        watch = state['watches']['TEST']
        self.assertEqual(watch['breakout'], 101)
        self.assertEqual(watch['interval'], '1h')
        data['current_price'] = 105
        data['rebound_bars'].append(dict(time="2026-01-05 11:00:00", High=110, Low=100, Close=105))
        self.assertEqual(advance(state, [data], {}, "2026-01-05 11:05:00+00:00"), set())
        self.assertEqual(watch['confirmations'], 1)
        advance(state, [data], {}, "2026-01-05 11:45:00+00:00")
        self.assertEqual(watch['confirmations'], 1)
        data['current_price'] = 106
        data['rebound_bars'].append(dict(time="2026-01-05 12:00:00", High=108, Low=104, Close=106))
        # La vela de las 12 todavía está incompleta a las 11:50.
        self.assertEqual(advance(state, [data], {}, "2026-01-05 11:50:00+00:00"), set())
        self.assertEqual(advance(state, [data], {}, "2026-01-05 12:05:00+00:00"), {'TEST'})
        self.assertEqual(watch['breakout'], 101)

    def test_missing_hourly_data_does_not_fall_back_to_distant_daily_roof(self):
        data = dict(item(), rebound_bars=[])
        state = {"entries": [], "watches": {"TEST": dict(since="2026-01-01", breakout=514.61)}}
        self.assertEqual(advance(state, [data], {'TEST': history([100]*4+[120,125])}, "2026-01-07 10:00:00"), set())
        self.assertEqual(state['watches']['TEST']['state'], 'SIN_DATOS_HORARIOS')

    def test_failed_hourly_download_is_explicitly_empty(self):
        ticker = Mock()
        ticker.history.side_effect = OSError('simulated failure')
        self.assertEqual(fetch_rebound_bars(ticker), [])


if __name__ == '__main__':
    unittest.main()
