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
        self.path.write_text(json.dumps({"entries": entries, "stats": {"win_rate_pct": 50}}), encoding="utf-8")

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
        frozen, current = message.split("Lectura actual del mercado", maxsplit=1)
        self.assertIn("SEGUIMIENTO ACTIVO DEL DIARIO", frozen)
        for value in ("$500.00", "$450.00", "$550.00", "$600.00", "6mo", "2026-11-01"):
            self.assertIn(value, frozen)
        self.assertNotIn("$455.00", frozen)  # SSL de la lectura actual no reemplaza el stop.
        self.assertIn("$455.00", current)
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
        frozen = message.split("Lectura actual del mercado", maxsplit=1)[0]
        self.assertIn("6mo", frozen)
        self.assertIn("$450.00", frozen)
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_period_and_unrecoverable_original_stop_are_not_invented(self):
        entry = signal(status="TP1_ALCANZADO", stop_loss=500)
        entry.pop("period")
        entry.pop("initial_stop_loss")
        self.seed([entry])
        message, _ = self.query()
        self.assertIn("Periodo original: No registrado", message)
        self.assertIn("Stop original: No registrado", message)
        self.assertIn("Stop de seguimiento: `$500.00`", message)

    def test_no_signal_reports_no_tracking_and_creates_nothing(self):
        message, keyboard = self.query()
        self.assertIn("Sin seguimiento activo", message)
        self.assertFalse(self.path.exists())
        self.assertNotIn("planfollow:", json.dumps(keyboard))

    def test_closed_signal_is_not_reported_as_active(self):
        self.seed([signal(status="STOP_EJECUTADO", result="PERDIDA", final_return_pct=-10)])
        message, _ = self.query()
        self.assertIn("Sin seguimiento activo", message)
        self.assertIn("Stop alcanzado; perdida", message)
        self.assertNotIn("SEGUIMIENTO ACTIVO DEL DIARIO", message)

    def test_active_signal_has_priority_over_newer_closed_history(self):
        self.seed([signal(signal_date="2026-11-02", status="STOP_EJECUTADO"), signal()])
        self.assertEqual(journal.get_tracking_signal("amd")["entry"]["signal_date"], "2026-11-01 10:00:00")

    def test_untracked_asset_still_exposes_its_historical_signal(self):
        self.seed([signal()])
        with patch.object(bot, "find_asset_item", return_value=None), patch.object(bot, "send_telegram_message") as send:
            bot.handle_ver_ticker("unused", "test-chat", "AMD")
        self.assertIn("SEGUIMIENTO ACTIVO DEL DIARIO", send.call_args.args[2])
        self.assertIn("no hay una lectura actual disponible", send.call_args.args[2])

    def test_corrupt_history_is_preserved_and_not_confused_with_no_signal(self):
        self.path.write_text("broken", encoding="utf-8")
        message, _ = self.query()
        self.assertIn("No se puede consultar", message)
        self.assertNotIn("Sin seguimiento activo", message)
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
        self.assertIn("SEGUIMIENTO ACTIVO DEL DIARIO", message)
        self.assertIn("$450.00", message)

    def test_compra_uses_the_same_journal_context_and_no_save_button(self):
        self.seed([signal()])
        message, keyboard = self.query(command="compra")
        self.assertIn("SEGUIMIENTO ACTIVO DEL DIARIO", message)
        self.assertNotIn("planfollow:", json.dumps(keyboard))

    def test_new_signal_records_period_and_keeps_levels_when_market_changes(self):
        item = market_item()
        result = journal.update_journal_with_market_data([item])
        original = deepcopy(result["entries"][0])
        self.assertEqual(original["period"], "1mo")
        self.assertEqual(original["stop_method"], "ESTRUCTURAL")
        self.assertEqual(original["initial_stop_loss"], 460)
        item["period"] = "1y"
        item["risk_mgmt"]["stop_loss"] = 430
        result = journal.update_journal_with_market_data([item])
        for field in ("entry_price", "tp1", "tp2", "initial_stop_loss", "stop_loss", "period"):
            self.assertEqual(result["entries"][0][field], original[field])

    def test_same_stop_is_shown_once_and_protected_stop_is_explained(self):
        self.seed([signal()])
        context = bot.journal_tracking_context(market_item())
        self.assertIn("Stop: `$450.00`", context)
        self.assertNotIn("Stop original:", context)
        self.assertNotIn("Stop de seguimiento:", context)
        self.seed([signal(status="TP1_ALCANZADO", stop_loss=500)])
        context = bot.journal_tracking_context(market_item())
        self.assertIn("Stop original: `$450.00`", context)
        self.assertIn("Stop del resto: `$500.00`", context)

    def test_ver_adds_context_after_frozen_signal_without_changing_records(self):
        self.seed([signal()])
        before = self.path.read_bytes()
        item = market_item()
        item.update(min=475, swing_type="FALLING_KNIFE", liquidity={
            "has_real_volume": True, "profile_type": "VOLUME", "poc_price": 530,
            "val_price": 490, "vah_price": 560,
        })
        message, _ = self.query(item)
        self.assertLess(message.index("SEGUIMIENTO ACTIVO"), message.index("Contexto actual"))
        self.assertIn("posible", message.lower())
        self.assertIn("resistencia durante un rebote", message)
        self.assertIn("mínimo puede seguir bajando", message)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertLess(len(message), 4096)


class CurrentMarketContextTests(unittest.TestCase):
    def test_actual_cluster_bounds_are_used_for_support(self):
        item = market_item()
        item["fib_clusters"] = [{"min_price": 470, "max_price": 474,
                                 "members_detail": [{"period": "1mo"}, {"period": "3mo"}]}]
        before = deepcopy(item)
        result = bot.format_current_market_context(item)
        self.assertIn("`$470.00`–`$474.00`", result)
        self.assertIn("varios periodos", result)
        self.assertEqual(item, before)

    def test_cluster_above_price_is_never_called_support(self):
        item = market_item()
        item["fib_clusters"] = [{"min_price": 490, "max_price": 500,
                                 "members_detail": [{"period": "1mo"}, {"period": "3mo"}]}]
        result = bot.format_current_market_context(item)
        self.assertIn("No hay referencias suficientes", result)
        self.assertNotIn("varios periodos", result)

    def test_single_level_uses_an_explicitly_approximate_band(self):
        item = market_item()
        item["min"] = 470
        result = bot.format_current_market_context(item)
        self.assertIn("`$467.65`–`$472.35`", result)
        self.assertIn("no suelo confirmado", result)

    def test_poc_role_depends_on_its_position_and_is_not_order_book(self):
        for poc, expected in ((530, "resistencia"), (450, "soporte"), (480, "zona de negociación")):
            with self.subTest(poc=poc):
                item = market_item()
                item["liquidity"] = {"has_real_volume": True, "profile_type": "VOLUME", "poc_price": poc}
                result = bot.format_current_market_context(item)
                self.assertIn(expected, result)
                self.assertIn("no muestra órdenes pendientes", result)

    def test_tpo_is_not_presented_as_real_volume(self):
        item = market_item()
        item["liquidity"] = {"has_real_volume": False, "profile_type": "TPO", "poc_price": 530}
        result = bot.format_current_market_context(item)
        self.assertIn("frecuencia de precios, no volumen", result)
        self.assertNotIn("Mayor concentración estimada de volumen", result)
        self.assertNotIn("gran *Muro de Volumen", bot.format_buy_advice(item))

    def test_stale_or_invalid_price_does_not_produce_new_zones(self):
        for item in (market_item() | {"is_stale": True}, market_item() | {"current_price": float("nan")}):
            result = bot.format_current_market_context(item)
            self.assertIn("No hay una cotización actual válida", result)
            self.assertNotIn("Posible zona de soporte", result)


if __name__ == "__main__":
    unittest.main()
