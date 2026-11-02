"""Planes elegidos y Telegram sin credenciales, red ni archivos reales."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
import trade_plan_manager as plans
import telegram_notifier as bot

NOW = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)


def asset(price=100, **extra):
    return {"ticker": "AMD", "tab": "AMD", "name": "Empresa de prueba", "currency": "$", "decimals": 2,
            "current_price": price, "period": "1mo", "score": 80,
            "risk_mgmt": {"entry_price": 100, "entry_type": "MARKET", "stop_loss": 85,
                          "ssl_stop_loss": 90, "take_profit_1": 110, "take_profit_2": 120}, **extra}


class StorageCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "plans.json"
        for target, name, value in ((plans, "PLANS_PATH", str(self.path)), (plans, "utc_now", lambda: NOW)):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def follow(self, item=None):
        item = item or asset()
        offer = plans.create_offer(item, "one")
        return plans.follow_offer(offer["id"], "one")[0]

    def update(self, price, minutes=30, stale=False):
        with patch.object(plans, "utc_now", return_value=NOW + timedelta(minutes=minutes)):
            plans.update_followed_plans([asset(price, is_stale=stale)], histories={"AMD": None})
        return plans.get_plans("one")["plans"][0]

    def candles(self, rows, minutes=30):
        frame = pd.DataFrame([row[1] for row in rows], index=pd.to_datetime([row[0] for row in rows], utc=True))
        with patch.object(plans, "utc_now", return_value=NOW + timedelta(minutes=minutes)):
            plans.update_followed_plans([], histories={"AMD": frame})
        return plans.get_plans("one")["plans"][0]

class PlanTests(StorageCase):
    def test_button_freezes_exact_proposal_and_ssl_stop_not_new_market(self):
        item = asset()
        offer = plans.create_offer(item, "one")
        item["risk_mgmt"]["ssl_stop_loss"] = 70
        plan, created = plans.follow_offer(offer["id"], "one")
        self.assertTrue(created)
        self.assertEqual(plan["levels"], {"entry": 100, "stop": 90, "tp1": 110, "tp2": 120})
        self.assertEqual(plan["period"], "1mo")

    def test_query_creates_no_followed_plan_and_double_click_never_duplicates(self):
        offer = plans.create_offer(asset(), "one")
        self.assertEqual(plans.get_plans()["plans"], [])
        first, created = plans.follow_offer(offer["id"], "one")
        second, repeated = plans.follow_offer(offer["id"], "one")
        self.assertTrue(created)
        self.assertFalse(repeated)
        self.assertEqual(first["id"], second["id"])
        plans.cancel_plan(first["id"], "one")
        self.assertEqual(plans.follow_offer(offer["id"], "one")[0]["status"], "CANCELADA")
        self.assertEqual(len(plans.get_plans()["plans"]), 1)

    def test_new_analysis_cannot_replace_active_plan(self):
        first = self.follow()
        item = asset()
        item["risk_mgmt"]["ssl_stop_loss"] = 80
        second = plans.create_offer(item, "one")
        existing, created = plans.follow_offer(second["id"], "one")
        self.assertFalse(created)
        self.assertEqual(existing["id"], first["id"])
        self.assertEqual(existing["stop_loss"], 90)

    def test_ownership_is_checked_and_not_returned_by_public_read(self):
        offer = plans.create_offer(asset(), "one")
        with self.assertRaises(ValueError):
            plans.follow_offer(offer["id"], "two")
        plan, _ = plans.follow_offer(offer["id"], "one")
        with self.assertRaises(ValueError):
            plans.cancel_plan(plan["id"], "two")
        self.assertEqual(plans.get_plans("two")["plans"], [])
        self.assertNotIn("owner", plans.get_plans()["plans"][0])

    def test_stop_failure_is_final_and_never_moves_down(self):
        original = self.follow()
        stopped = self.update(88)
        self.assertEqual(stopped["status"], "STOP_EJECUTADO")
        self.assertEqual(stopped["final_return_pct"], -10)
        later = self.update(125, minutes=60)
        self.assertEqual(later["status"], "STOP_EJECUTADO")
        self.assertEqual(later["levels"], original["levels"])
        self.assertEqual(plans.get_plans()["stats"]["lost"], 1)

    def test_tp1_is_still_open_then_tp2_weights_half_exits(self):
        original = self.follow()
        partial = self.update(112)
        self.assertEqual(partial["status"], "TP1_ALCANZADO")
        self.assertEqual(partial["stop_loss"], 100)
        self.assertEqual(partial["levels"]["stop"], 90)
        self.assertEqual(plans.get_plans()["stats"]["closed"], 0)
        closed = self.update(121, minutes=60)
        self.assertEqual(closed["status"], "TP2_ALCANZADO")
        self.assertEqual(closed["final_return_pct"], 15)
        self.assertEqual(closed["levels"], original["levels"])

    def test_tp1_then_break_even_preserves_partial_profit(self):
        self.follow()
        self.update(112)
        closed = self.update(99, minutes=60)
        self.assertEqual(closed["status"], "BREAKEVEN_EJECUTADO")
        self.assertEqual(closed["final_return_pct"], 5)
        self.assertEqual(plans.get_plans()["stats"]["won"], 1)

    def test_cancel_is_retained_and_excluded_from_win_rate(self):
        original = self.follow()
        plans.cancel_plan(original["id"], "one")
        later = self.update(88)
        self.assertEqual(later["status"], "CANCELADA")
        self.assertEqual(plans.get_plans()["stats"]["closed"], 0)

    def test_stale_quote_does_not_close_plan(self):
        self.follow()
        result = self.update(80, stale=True)
        self.assertEqual(result["status"], "ACTIVA")
        self.assertTrue(result["quote_stale"])

    def test_old_quote_before_saving_is_not_used_as_new_observation(self):
        offer = plans.create_offer(asset(), "one")
        item = asset(80, last_success_at=(NOW - timedelta(minutes=10)).isoformat())
        plan, _ = plans.follow_offer(offer["id"], "one", item)
        self.assertEqual(plan["status"], "ACTIVA")
        self.assertTrue(plan["quote_stale"])

    def test_candle_before_saved_plan_is_ignored(self):
        self.follow()
        result = self.candles([("2026-11-02T14:55:00Z", {"High": 125, "Low": 80, "Close": 100})])
        self.assertEqual(result["status"], "ACTIVA")

    def test_intraday_stop_is_seen_even_if_price_later_recovers(self):
        self.follow()
        result = self.candles([
            ("2026-11-02T15:00:00Z", {"High": 102, "Low": 89, "Close": 95}),
            ("2026-11-02T15:05:00Z", {"High": 121, "Low": 100, "Close": 121}),
        ])
        self.assertEqual(result["status"], "STOP_EJECUTADO")

    def test_ambiguous_candle_is_conservative_and_flagged(self):
        self.follow()
        result = self.candles([("2026-11-02T15:00:00Z", {"High": 125, "Low": 99, "Close": 120})])
        self.assertEqual(result["status"], "BREAKEVEN_EJECUTADO")
        self.assertEqual(result["final_return_pct"], 5)
        self.assertIn("conservador", result["ambiguity_note"])

    def test_limit_plan_waits_for_entry_and_does_not_credit_earlier_high(self):
        item = asset(105)
        item["risk_mgmt"]["entry_type"] = "LIMIT_618"
        self.follow(item)
        self.assertEqual(self.update(103)["status"], "PENDIENTE_ENTRADA")
        self.assertEqual(self.update(99, minutes=60)["status"], "ACTIVA")
        self.assertEqual(self.update(111, minutes=90)["status"], "TP1_ALCANZADO")

    def test_invalid_levels_and_stale_proposals_have_no_follow_button(self):
        item = asset()
        item["risk_mgmt"]["take_profit_1"] = 99
        for invalid in (item, asset(is_stale=True)):
            with self.assertRaises(ValueError):
                plans.create_offer(invalid, "one")

    def test_corrupt_file_is_preserved(self):
        self.path.write_text("broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            plans.create_offer(asset(), "one")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "broken")

    def test_expired_unfollowed_offer_is_rejected_but_saved_plan_never_expires(self):
        unused = plans.create_offer(asset(), "two")
        saved = plans.create_offer(asset(), "one")
        plan, _ = plans.follow_offer(saved["id"], "one")
        with patch.object(plans, "utc_now", return_value=NOW + timedelta(days=31)):
            with self.assertRaises(ValueError):
                plans.follow_offer(unused["id"], "two")
            self.assertEqual(plans.follow_offer(saved["id"], "one")[0]["id"], plan["id"])

    def test_new_plan_after_closure_retains_both_histories(self):
        old = self.follow()
        self.update(88)
        new = self.follow()
        self.assertNotEqual(old["id"], new["id"])
        self.assertEqual(len(plans.get_plans()["plans"]), 2)
        self.assertEqual(plans.get_plans()["stats"]["closed"], 1)

    def test_limit_plan_invalidated_before_entry_is_not_counted_as_loss(self):
        item = asset(105)
        item["risk_mgmt"]["entry_type"] = "LIMIT_618"
        self.follow(item)
        result = self.update(80)
        self.assertEqual(result["status"], "INVALIDADA_SIN_ENTRADA")
        self.assertEqual(plans.get_plans()["stats"]["closed"], 0)

    def test_partial_bar_before_last_quote_is_not_replayed(self):
        self.follow()
        self.update(102, minutes=12)
        result = self.candles([("2026-11-02T15:10:00Z", {"High": 105, "Low": 80, "Close": 101})])
        self.assertEqual(result["status"], "ACTIVA")


class TelegramPlanTests(StorageCase):
    def test_follow_button_roundtrip_keeps_displayed_levels_after_market_changes(self):
        item = asset()
        with patch.object(bot, "find_asset_item", return_value=item), patch.object(bot, "send_telegram_message") as send:
            bot.handle_compra("unused", "one", "AMD")
        call = send.call_args
        keyboard = call.kwargs["reply_markup"]
        follow = keyboard["inline_keyboard"][0][0]["callback_data"]
        self.assertTrue(follow.startswith("planfollow:"))
        self.assertIn("$90.00", call.args[2])
        self.assertEqual(plans.get_plans()["plans"], [])
        self.assertLessEqual(len(call.args[2]), 4096)
        with patch.object(bot, "LATEST_DATA_PATH", str(self.path.parent / "missing.json")), \
                patch.object(bot, "send_telegram_message") as send, patch.object(bot, "answer_callback_query"):
            bot.process_callback_query("unused", "one", "cb", follow)
        self.assertEqual(plans.get_plans()["plans"][0]["stop_loss"], 90)
        self.assertIn("$90.00", send.call_args.args[2])
        with patch.object(bot, "find_asset_item", return_value=asset(95)), patch.object(bot, "send_telegram_message") as send:
            bot.handle_compra("unused", "one", "AMD")
        self.assertIn("Plan guardado", send.call_args.args[2])
        self.assertIn("distinta del plan guardado", send.call_args.args[2])

    def test_plan_command_and_cancel_require_explicit_confirmation(self):
        plan = self.follow()
        with patch.object(bot, "send_telegram_message") as send:
            bot.process_user_telegram_command("unused", "one", "/plan AMD")
            self.assertIn("PLAN GUARDADO", send.call_args.args[2])
            bot.handle_plan_callback("unused", "one", "plancancel", plan["id"])
            self.assertEqual(plans.get_plans()["plans"][0]["status"], "ACTIVA")
            bot.handle_plan_callback("unused", "one", "planconfirm", plan["id"])
            self.assertEqual(plans.get_plans()["plans"][0]["status"], "CANCELADA")


if __name__ == "__main__":
    unittest.main()
