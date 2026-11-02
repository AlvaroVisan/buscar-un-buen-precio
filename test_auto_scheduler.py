import unittest
from unittest.mock import patch

import app


class StopScheduler(BaseException):
    pass


class AutoSchedulerTests(unittest.TestCase):
    def run_cycles(self, times, updater_effect=None):
        config = {
            "period": "3mo",
            "assets": [{"ticker": "AMD"}],
            "scheduler": {
                "enabled": True,
                "interval_minutes": 30,
                "smart_hours_only": False,
            },
        }
        sleeps = [None] * len(times) + [StopScheduler()]
        with patch.object(app.time, "sleep", side_effect=sleeps), \
                patch.object(app.time, "time", side_effect=times), \
                patch.object(app.market_updater, "load_config", return_value=config), \
                patch.object(app.market_updater, "evaluate_market_hours", return_value={
                                 "equities_open": False, "has_crypto": False,
                                 "status_label": "Mercado cerrado",
                             }), \
                patch.object(app.market_updater, "run_updater", side_effect=updater_effect) as update:
            with self.assertRaises(StopScheduler):
                app.auto_scheduler_worker()
        return update

    def setUp(self):
        self.previous_time = app.last_auto_sync_time
        app.last_auto_sync_time = 0.0

    def tearDown(self):
        app.last_auto_sync_time = self.previous_time

    def test_startup_and_every_thirty_minutes_even_when_closed(self):
        update = self.run_cycles([10000, 11799, 11800, 13600])
        self.assertEqual(update.call_count, 3)
        update.assert_called_with(target_period="3mo")
        self.assertEqual(app.last_auto_sync_time, 13600)

    def test_failed_update_retries_on_next_check(self):
        update = self.run_cycles([10000, 10030], [RuntimeError("Sin conexión"), {}])
        self.assertEqual(update.call_count, 2)
        self.assertEqual(app.last_auto_sync_time, 10030)


if __name__ == "__main__":
    unittest.main()
