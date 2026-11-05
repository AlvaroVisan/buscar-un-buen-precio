"""Bot con estado temporal y envíos simulados: ningún mensaje real."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import journal_manager as journal
import telegram_notifier as bot
from scenario_engine import buy, mark
from test_journal_manager import open_trade


class TelegramScenariosTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for module, key, filename in ((journal, "JOURNAL_PATH", "journal.json"), (bot, "ALERTS_CACHE_PATH", "alerts.json")):
            patcher = patch.object(module, key, str(self.root / filename))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.data = {"entries": [], "watches": {"AAA": dict(since="2026-01-01", breakout=105, rules_version=2, confirmations=0)}, "accumulation": []}
        self.item = dict(ticker="AAA", tab="AAA", current_price=100, score=95, currency="$", fib_levels={"61.8%": 110})
        self.config = {"telegram": dict(enabled=True, bot_token="fake", chat_id="test-a,test-b"), "scheduler": {"smart_hours_only": False}}
        self.send = patch.object(bot, "send_telegram_message", return_value=(True, {})).start()
        self.addCleanup(patch.stopall)
        patch.object(bot, "pin_telegram_message").start()
        patch.object(bot.time, "sleep").start()
        patch("market_updater.evaluate_market_hours", return_value={"equities_open": True}).start()
        self.save()

    def save(self):
        Path(journal.JOURNAL_PATH).write_text(json.dumps(self.data), encoding="utf-8")

    def dispatch(self):
        return bot.dispatch_telegram_alerts({"data": [self.item]}, self.config)

    def confirm(self):
        trade = dict(open_trade("AAA", 100), strategy="confirmation", currency="$")
        self.data["entries"] = [trade]
        self.save()
        return trade

    def campaign(self):
        campaign = dict(ticker="AAA", currency="$", status="ACTIVA", budget=1000,
                        invalidation=70, target=130, tranches=[], invested=0, shares=0,
                        max_drawdown_pct=0, last_check="2026-01-05")
        buy(campaign, 100, "2026-01-05")
        mark(campaign, 95)
        self.data["accumulation"] = [campaign]
        self.save()
        return campaign

    def test_watch_and_high_score_never_trigger_push_or_buy_advice(self):
        before = Path(journal.JOURNAL_PATH).read_bytes()
        self.assertEqual(self.dispatch()["sent"], 0)
        self.send.assert_not_called()
        advice = bot.format_buy_advice(self.item)
        self.assertIn("todavía no entraría", advice)
        self.assertNotIn("Compra aquí", advice)
        self.assertEqual(Path(journal.JOURNAL_PATH).read_bytes(), before)

    def test_delivered_event_is_not_repeated_after_restart_or_cooldown(self):
        self.confirm()
        self.assertEqual(self.dispatch()["sent"], 1)
        self.assertEqual(self.send.call_count, 2)
        with patch.object(bot.time, "time", return_value=10**12):
            self.assertEqual(self.dispatch()["sent"], 0)
        self.assertEqual(self.send.call_count, 2)

    def test_new_tranche_bypasses_old_event_and_closure_does_not_repeat(self):
        trade = self.confirm()
        campaign = self.campaign()
        self.dispatch()
        buy(campaign, 94, "2026-01-07")
        self.save()
        self.assertEqual(self.dispatch()["sent"], 1)
        self.assertEqual(self.send.call_count, 4)
        trade["status"] = "STOP_EJECUTADO"
        self.save()
        self.assertEqual(self.dispatch()["sent"], 0)

    def test_failed_recipient_is_retried_without_repeating_successful_one(self):
        self.confirm()
        self.send.side_effect = [(True, {}), (False, "simulated failure"), (True, {})]
        self.dispatch()
        self.dispatch()
        self.assertEqual([call.args[1] for call in self.send.call_args_list], ["test-a", "test-b", "test-b"])

    def test_stale_and_corrupt_journal_fail_closed(self):
        self.confirm()
        self.item["is_stale"] = True
        self.assertEqual(self.dispatch()["sent"], 0)
        self.item["is_stale"] = False
        Path(journal.JOURNAL_PATH).write_text("broken", encoding="utf-8")
        self.assertEqual(self.dispatch()["sent"], 0)
        self.assertIn("No hay entrada verificable", bot.format_buy_advice(self.item))
        self.assertEqual(Path(journal.JOURNAL_PATH).read_text(), "broken")

    def test_commands_and_callbacks_separate_scenarios_without_writes(self):
        self.confirm()
        self.campaign()
        self.data["entries"].append(dict(open_trade("LEGACY", 100), status="STOP_EJECUTADO", result="PERDIDA"))
        self.save()
        before = Path(journal.JOURNAL_PATH).read_bytes()
        for command, title in (("/diario", "Escenario: Confirmación"), ("/diario anterior", "Escenario: Historial anterior"), ("/acumulacion", "Escenario: Acumulación")):
            bot.process_user_telegram_command("fake", "test-a", command)
            self.assertIn(title, self.send.call_args.args[2])
        with patch.object(bot, "answer_callback_query"):
            bot.process_callback_query("fake", "test-a", "callback", "hist:ACTIVE:accumulation")
        self.assertIn("Escenario: Acumulación", self.send.call_args.args[2])
        self.assertIn("1/3 tramos", self.send.call_args.args[2])
        self.assertEqual(Path(journal.JOURNAL_PATH).read_bytes(), before)

    def test_message_lengths_with_multiple_campaigns(self):
        campaign = self.campaign()
        self.data["accumulation"] = [dict(copy.deepcopy(campaign), ticker="LONG-TICKER-" + str(i)) for i in range(25)]
        self.save()
        bot.handle_historial("fake", "test-a", scenario="accumulation")
        self.assertLess(len(self.send.call_args.args[2]), 4096)
        self.assertIn("8 de 25", self.send.call_args.args[2])
        self.assertLess(len(bot.format_buy_advice(self.item)), 4096)

    def test_plain_advice_gives_waiting_entry_and_roof_prices(self):
        self.item.update(min=90, drop_pct=15, max=130, risk_mgmt={"take_profit_1": 120})
        text = bot.format_buy_advice(self.item)
        for price in ("$100.00", "$90.00", "$105.00", "$120.00", "$130.00"):
            self.assertIn(price, text)
        self.assertIn("todavía puede quedar bajada", text)
        self.assertNotIn("entramos de una", text)

    def test_plain_advice_only_enters_near_recorded_confirmation(self):
        self.confirm()
        self.assertIn("entramos de una", bot.format_buy_advice(self.item))
        self.item['current_price'] = 108
        self.assertNotIn("entramos de una", bot.format_buy_advice(self.item))
        self.assertIn("no iría detrás del precio", bot.format_buy_advice(self.item))
        self.item['current_price'] = 85
        self.assertIn("Ahora no entraría", bot.format_buy_advice(self.item))
        self.item['is_stale'] = True
        self.assertNotIn("entramos de una", bot.format_buy_advice(self.item))


if __name__ == "__main__":
    unittest.main()
