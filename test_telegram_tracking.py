"""Un solo seguimiento en el Diario; consultas del bot sin red ni escrituras."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import journal_manager as journal
import telegram_notifier as bot


def signal(**changes):
    return {
        "id": "signal_AMD", "ticker": "AMD", "tab": "AMD", "name": "Empresa de prueba",
        "currency": "$", "decimals": 2, "signal_date": "2026-11-01 10:00:00",
        "period": "6mo", "score": 75, "entry_price": 500,
        "initial_stop_loss": 450, "stop_loss": 450, "tp1": 550, "tp2": 600,
        "current_price": 480, "current_return_pct": -4, "final_return_pct": None,
        "last_check": "2026-11-02 15:00:00", "status": "ACTIVA", "result": "EN_CURSO",
        **changes,
    }


def market_item():
    return {
        "ticker": "AMD", "tab": "AMD", "name": "Empresa de prueba", "currency": "$", "decimals": 2,
        "current_price": 480, "period": "1mo", "score": 90,
        "risk_mgmt": {"entry_price": 480, "entry_type": "MARKET", "stop_loss": 460,
                      "ssl_stop_loss": 455, "take_profit_1": 520, "take_profit_2": 570},
    }


class JournalTrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "journal.json"
        patcher = patch.object(journal, "JOURNAL_PATH", str(self.path))
        patcher.start()
        self.addCleanup(patcher.stop)

    def seed(self, entries):
        self.path.write_text(json.dumps({"entries": entries, "stats": {"win_rate_pct": 50, "loss_rate_pct": 50}}), encoding="utf-8")

    def query(self, item=None, command="ver"):
        item = item if item is not None else market_item()
        with patch.object(bot, "find_asset_item", return_value=item), \
                patch.object(bot, "send_telegram_message") as send:
            bot.process_user_telegram_command("unused", "test-chat", f"/{command} AMD")
        return send.call_args.args[2], send.call_args.kwargs.get("reply_markup", {})

    def test_ver_shows_journal_levels_before_distinct_current_analysis(self):
        self.seed([signal()])
        before = self.path.read_bytes()
        message, keyboard = self.query()
        self.assertIn("📌 *Seguimiento activo*:", message)
        self.assertIn("Entrada en `$500.00`", message)
        self.assertIn("Salida si cae de `$450.00`", message)
        self.assertIn("PRONÓSTICO", message)
        self.assertNotIn("planfollow:", json.dumps(keyboard))
        self.assertNotIn("Seguir este plan", message)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertLess(len(message), 4096)

    def test_changing_current_price_and_period_does_not_rewrite_signal(self):
        self.seed([signal()])
        before = self.path.read_bytes()
        item = market_item()
        item.update(current_price=470, period="1y")
        message, _ = self.query(item)
        self.assertIn("Entrada en `$500.00`", message)
        self.assertIn("Salida si cae de `$450.00`", message)
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_period_and_unrecoverable_original_stop_are_not_invented(self):
        entry = signal(status="TP1_ALCANZADO", stop_loss=500)
        entry.pop("period")
        entry.pop("initial_stop_loss")
        self.seed([entry])
        message, _ = self.query()
        self.assertIn("Entrada en `$500.00`", message)
        self.assertIn("Salida si cae de `$500.00`", message)

    def test_no_signal_reports_no_tracking_and_creates_nothing(self):
        message, keyboard = self.query()
        self.assertNotIn("📌 *Seguimiento activo*:", message)
        self.assertFalse(self.path.exists())
        self.assertNotIn("planfollow:", json.dumps(keyboard))

    def test_closed_signal_is_not_reported_as_active(self):
        self.seed([signal(status="STOP_EJECUTADO", result="PERDIDA", final_return_pct=-10)])
        message, _ = self.query()
        self.assertNotIn("📌 *Seguimiento activo*:", message)

    def test_active_signal_has_priority_over_newer_closed_history(self):
        self.seed([signal(signal_date="2026-11-02", status="STOP_EJECUTADO"), signal()])
        self.assertEqual(journal.get_tracking_signal("amd")["entry"]["signal_date"], "2026-11-01 10:00:00")

    def test_untracked_asset_still_exposes_its_historical_signal(self):
        self.seed([signal()])
        with patch.object(bot, "find_asset_item", return_value=None), patch.object(bot, "send_telegram_message") as send:
            bot.handle_ver_ticker("unused", "test-chat", "AMD")
        self.assertIn("📌 *Seguimiento activo*:", send.call_args.args[2])
        self.assertIn("no hay una lectura actual disponible", send.call_args.args[2])

    def test_corrupt_history_is_preserved_and_not_confused_with_no_signal(self):
        self.path.write_text("broken", encoding="utf-8")
        message, _ = self.query()
        self.assertIn("No se puede consultar", message)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "broken")

    def test_old_buttons_cannot_create_cancel_or_overwrite_signals(self):
        self.seed([signal()])
        before = self.path.read_bytes()
        with patch.object(bot, "send_telegram_message") as send, patch.object(bot, "answer_callback_query"):
            for action in ("planfollow", "planver", "plancancel", "planconfirm"):
                bot.process_callback_query("unused", "test-chat", "callback", f"{action}:old-id")
                self.assertIn("seguimiento es automático", send.call_args.args[2])
        self.assertEqual(self.path.read_bytes(), before)

    def test_old_plan_command_uses_same_journal_tracking(self):
        self.seed([signal()])
        message, _ = self.query(command="plan")
        self.assertIn("📌 *Seguimiento activo*:", message)
        self.assertIn("$450.00", message)

    def test_compra_uses_the_same_journal_context_and_no_save_button(self):
        self.seed([signal()])
        message, keyboard = self.query(command="compra")
        self.assertIn("📌 *Seguimiento activo*:", message)
        self.assertNotIn("planfollow:", json.dumps(keyboard))

    def test_new_signal_records_period_and_keeps_levels_when_market_changes(self):
        item = market_item()
        item.update(atr_14=5, max=570, fib_levels={"38.2%": 520})
        with patch("scenario_engine.advance", return_value={"AMD"}):
            result = journal.update_journal_with_market_data([item])
        original = deepcopy(result["entries"][0])
        self.assertEqual(original["period"], "1mo")
        self.assertEqual(original["stop_method"], "ESTRUCTURAL_ATR")
        self.assertEqual(original["initial_stop_loss"], 460)
        item["period"] = "1y"
        item["risk_mgmt"]["stop_loss"] = 430
        result = journal.update_journal_with_market_data([item])
        for field in ("entry_price", "tp1", "tp2", "initial_stop_loss", "stop_loss", "period"):
            self.assertEqual(result["entries"][0][field], original[field])

    def test_same_stop_is_shown_once_and_protected_stop_is_explained(self):
        self.seed([signal()])
        context = bot.journal_tracking_context(market_item())
        self.assertIn("Salida si cae de `$450.00`", context)
        self.seed([signal(status="TP1_ALCANZADO", stop_loss=500)])
        context = bot.journal_tracking_context(market_item())
        self.assertIn("Salida si cae de `$500.00`", context)

    def test_ver_adds_context_after_frozen_signal_without_changing_records(self):
        self.seed([signal()])
        before = self.path.read_bytes()
        item = market_item()
        item.update(min=475, drop_pct=12.0, swing_type="FALLING_KNIFE", liquidity={
            "has_real_volume": True, "profile_type": "VOLUME", "poc_price": 530,
            "val_price": 490, "vah_price": 560,
        })
        message, _ = self.query(item)
        self.assertLess(message.index("📌 *Seguimiento activo*"), message.index("PRONÓSTICO"))
        self.assertIn("rebote", message.lower())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertLess(len(message), 4096)


class CurrentMarketContextTests(unittest.TestCase):
    def setUp(self):
        context = patch.object(journal, "get_scenario_context", return_value={"confirmation": None, "accumulation": None, "watch": None})
        context.start()
        self.addCleanup(context.stop)
    def test_stub_format_current_market_context_returns_empty_string(self):
        item = market_item()
        result = bot.format_current_market_context(item)
        self.assertEqual(result, "")

    def test_falling_price_requires_confirmation_instead_of_buying_now(self):
        item = market_item()
        item.update(drop_pct=15.0, current_price=100, min=90)
        advice = bot.format_buy_advice(item)
        self.assertIn("esperar confirmación", advice)
        self.assertNotIn("Entrada en 2 tramos", advice)

    def test_buy_advice_institutional_volume_wall_when_poc_real_volume(self):
        item = market_item()
        item.update(drop_pct=12.0, liquidity={
            "has_real_volume": True, "profile_type": "VOLUME", "poc_price": 450
        })
        advice = bot.format_buy_advice(item)
        self.assertIn("POC `$450.00`", advice)
        self.assertIn("No acredita órdenes institucionales", advice)

    def test_tpo_profile_does_not_trigger_volume_wall(self):
        item = market_item()
        item.update(drop_pct=12.0, liquidity={
            "has_real_volume": False, "profile_type": "TPO", "poc_price": 450
        })
        advice = bot.format_buy_advice(item)
        self.assertNotIn("muro de compras institucional", advice)

    def test_earnings_imminent_pin_in_buy_advice(self):
        item = market_item()
        item["earnings"] = {
            "has_earnings": True, "short_date": "15 Nov", "days_until": 1, "eps_avg": 2.5
        }
        advice = bot.format_buy_advice(item)
        self.assertIn("📌 *Resultados*", advice)
        self.assertIn("MAÑANA", advice)

    def test_stale_warning_in_buy_advice(self):
        item = market_item()
        item["is_stale"] = True
        item["last_success_at"] = "2026-11-01 10:00"
        advice = bot.format_buy_advice(item)
        self.assertIn("⚠️ *Cotización desactualizada*", advice)


class HistorialCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "journal.json"
        patcher = patch.object(journal, "JOURNAL_PATH", str(self.path))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_handle_historial_filters_won_and_lost_correctly(self):
        entries = [
            {
                "id": "e_won", "ticker": "NVDA", "tab": "NVDA", "status": "TP2_ALCANZADO",
                "result": "GANADA", "entry_price": 100, "current_price": 120, "final_return_pct": 15.0,
                "signal_date": "2026-11-01 10:00:00", "closed_date": "2026-11-03 14:00:00",
                "exit_reason": "TP2 alcanzado exitosamente"
            },
            {
                "id": "e_lost", "ticker": "CEG", "tab": "CEG", "status": "STOP_EJECUTADO",
                "result": "PERDIDA", "entry_price": 260, "stop_loss": 240, "final_return_pct": -7.7,
                "signal_date": "2026-11-01 10:00:00", "closed_date": "2026-11-04 16:00:00",
                "exit_reason": "Stop Loss alcanzado en $240.00"
            },
            {
                "id": "e_act", "ticker": "AMD", "tab": "AMD", "status": "ACTIVA",
                "result": "EN_CURSO", "entry_price": 500, "current_price": 490, "current_return_pct": -2.0,
                "stop_loss": 450, "tp1": 550, "signal_date": "2026-11-02 10:00:00"
            }
        ]
        for entry in entries:
            entry["strategy"] = "confirmation"
        self.path.write_text(json.dumps({"entries": entries, "stats": journal.calculate_journal_stats(entries)}), encoding="utf-8")

        # 1. Test filtro GANADAS (WON)
        with patch.object(bot, "send_telegram_message") as send:
            bot.handle_historial("unused", "chat1", filter_mode="WON")
            msg = send.call_args.args[2]
            self.assertIn("REGISTRO DE OPERACIONES GANADAS", msg)
            self.assertIn("NVDA", msg)
            self.assertIn("+15.0%", msg)
            self.assertNotIn("CEG", msg)

        # 2. Test filtro STOP LOSS (LOST)
        with patch.object(bot, "send_telegram_message") as send:
            bot.handle_historial("unused", "chat1", filter_mode="LOST")
            msg = send.call_args.args[2]
            self.assertIn("REGISTRO DE OPERACIONES EN STOP LOSS", msg)
            self.assertIn("CEG", msg)
            self.assertIn("-7.7%", msg)
            self.assertNotIn("NVDA", msg)

        # 3. Test comando interactivo /tp y /sl
        with patch.object(bot, "send_telegram_message") as send:
            bot.process_user_telegram_command("unused", "chat1", "/tp")
            self.assertIn("REGISTRO DE OPERACIONES GANADAS", send.call_args.args[2])

        with patch.object(bot, "send_telegram_message") as send:
            bot.process_user_telegram_command("unused", "chat1", "/sl")
            self.assertIn("REGISTRO DE OPERACIONES EN STOP LOSS", send.call_args.args[2])

        # 4. Test callback query hist:WON
        with patch.object(bot, "send_telegram_message") as send, patch.object(bot, "answer_callback_query"):
            bot.process_callback_query("unused", "chat1", "cb1", "hist:WON")
            self.assertIn("REGISTRO DE OPERACIONES GANADAS", send.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
