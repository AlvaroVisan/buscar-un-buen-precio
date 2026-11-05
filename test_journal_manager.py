"""Regresiones del diario con datos ficticios y archivos temporales."""

import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import journal_manager as journal


def candidate(ticker, price):
    return {"ticker": ticker, "current_price": price, "score": 80,
            "atr_14": price * .01, "max": price * 1.5,
            "fib_levels": {"38.2%": price * 1.2}}


def open_trade(ticker, price):
    return {
        "id": f"existing_{ticker}", "ticker": ticker,
        "status": "ACTIVA", "result": "EN_CURSO",
        "entry_price": price, "current_price": price,
        "stop_loss": price * 0.9, "tp1": price * 1.1,
        "tp2": price * 1.2, "signal_date": "2026-01-01 12:00:00",
    }


class JournalUpdateTests(unittest.TestCase):
    def setUp(self):
        # Aquí se prueba el seguimiento y la inserción; el filtro se prueba sin mocks en test_scenario_engine.
        gate = patch("scenario_engine.advance", return_value={"NEW", "NEW1", "NEW2"})
        gate.start()
        self.addCleanup(gate.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "journal.json"
        patcher = patch.object(journal, "JOURNAL_PATH", str(self.path))
        patcher.start()
        self.addCleanup(patcher.stop)

    def seed(self, entries):
        self.path.write_text(json.dumps({"entries": entries}), encoding="utf-8")

    def test_archive_restore_keeps_loss_and_active_trade(self):
        loss = {**open_trade("CEG", 100), "id": "loss", "status": "STOP_EJECUTADO",
                "result": "PERDIDA", "final_return_pct": -10}
        active = open_trade("CEG", 100)
        self.seed([loss, active])
        original_stats = journal.calculate_journal_stats([loss, active])
        result = journal.archive_journal_entries(clear_closed=True)
        self.assertEqual(result["changed_ids"], ["loss"])
        self.assertEqual(result["journal"]["stats"], original_stats)
        self.assertTrue(result["journal"]["entries"][0]["archived"])
        self.assertNotIn("archived", result["journal"]["entries"][1])
        journal.update_journal_with_market_data([{"ticker": "CEG", "current_price": 101}])
        self.assertTrue(journal.load_journal()["entries"][0]["archived"])
        result = journal.archive_journal_entries(entry_ids=["loss"], archived=False)
        self.assertEqual(result["changed_ids"], ["loss"])
        self.assertEqual(result["journal"]["stats"], original_stats)
        self.assertFalse(result["journal"]["entries"][0]["archived"])
        self.assertEqual(journal.archive_journal_entries(entry_ids=["loss"], archived=False)["changed_ids"], [])

    def test_archive_skips_active_and_reports_save_failure(self):
        self.seed([open_trade("CEG", 100)])
        self.assertEqual(journal.archive_journal_entries(entry_ids=["existing_CEG"])["changed_ids"], [])
        with patch.object(journal, "save_journal", return_value=False):
            with self.assertRaises(OSError):
                journal.archive_journal_entries(clear_closed=True)
        with self.assertRaises(ValueError):
            journal.archive_journal_entries(entry_ids=["existing_CEG"], archived="false")

    def test_new_signals_do_not_displace_existing_trades(self):
        items = [
            candidate("NEW", 50),
            {"ticker": "AAA", "current_price": 112},
            {"ticker": "BBB", "current_price": 170},
        ]
        for ordering in itertools.permutations(items):
            with self.subTest(order=[item["ticker"] for item in ordering]):
                closed = {"id": "old", "ticker": "OLD", "status": "CERRADA_MANUAL"}
                self.seed([open_trade("AAA", 100), closed, open_trade("BBB", 200)])
                result = journal.update_journal_with_market_data(ordering)
                entries = result["entries"]
                self.assertEqual(len(entries), 4)
                self.assertEqual(len({entry["id"] for entry in entries}), 4)
                by_ticker = {entry["ticker"]: entry for entry in entries}
                self.assertEqual(by_ticker["AAA"]["id"], "existing_AAA")
                self.assertEqual(by_ticker["AAA"]["status"], "TP1_ALCANZADO")
                self.assertEqual(by_ticker["AAA"]["current_price"], 112)
                self.assertEqual(by_ticker["BBB"]["id"], "existing_BBB")
                self.assertEqual(by_ticker["BBB"]["status"], "STOP_EJECUTADO")
                self.assertEqual(by_ticker["BBB"]["current_price"], 170)
                self.assertEqual(by_ticker["NEW"]["entry_price"], 50)
                self.assertEqual(by_ticker["OLD"], closed)
                self.assertEqual(entries[0]["ticker"], "NEW")
                self.assertEqual(result["stats"]["active_count"], 2)
                self.assertEqual(result["stats"]["closed_count"], 2)
                self.assertEqual(journal.load_journal(), result)

    def test_multiple_insertions_keep_existing_trade(self):
        self.seed([open_trade("AAA", 100)])
        result = journal.update_journal_with_market_data([
            candidate("NEW1", 50),
            candidate("NEW2", 60),
            {"ticker": "AAA", "current_price": 105},
        ])
        self.assertEqual([e["ticker"] for e in result["entries"]], ["NEW2", "NEW1", "AAA"])
        self.assertEqual(result["entries"][2]["current_return_pct"], 5)

    def test_repeated_new_ticker_does_not_create_duplicate(self):
        self.seed([])
        item = candidate("NEW", 50)
        result = journal.update_journal_with_market_data([item, item])
        self.assertEqual(len(result["entries"]), 1)
        again = journal.update_journal_with_market_data([item])
        self.assertEqual(len(again["entries"]), 1)
        self.assertEqual(again["entries"][0]["id"], result["entries"][0]["id"])

    def test_tp1_open_return_includes_realized_half(self):
        trade = open_trade("AAA", 100)
        trade.update(tp1=110, tp2=120)
        self.seed([trade])
        result = journal.update_journal_with_market_data([{"ticker": "AAA", "current_price": 112}])
        self.assertEqual(result["entries"][0]["status"], "TP1_ALCANZADO")
        self.assertEqual(result["entries"][0]["current_return_pct"], 11)


class JournalExitTests(unittest.TestCase):
    def trade(self):
        trade = open_trade("AAA", 100)
        trade.update(tp1=110, tp2=120)
        return trade

    def test_tp2_after_tp1_uses_both_halves(self):
        trade = self.trade()
        journal._evaluate_price_point(trade, 112, 101, 111, "day1")
        self.assertEqual(trade["status"], "TP1_ALCANZADO")
        journal._evaluate_price_point(trade, 122, 105, 121, "day2")
        self.assertEqual(trade["status"], "TP2_ALCANZADO")
        self.assertEqual(trade["final_return_pct"], 15)
        self.assertEqual(trade["current_return_pct"], 15)
        self.assertEqual(trade["tp1_hit_date"], "day1")
        self.assertEqual(journal.calculate_journal_stats([trade])["avg_win_pct"], 15)

    def test_both_targets_in_same_candle_use_both_halves(self):
        trade = self.trade()
        journal._evaluate_price_point(trade, 125, 101, 124, "day1")
        self.assertEqual(trade["final_return_pct"], 15)
        self.assertEqual(trade["tp1_hit_date"], "day1")
        snapshot = dict(trade)
        journal._evaluate_price_point(trade, 130, 80, 85, "day2")
        self.assertEqual(trade, snapshot)

    def test_tp1_then_breakeven_keeps_half_profit(self):
        trade = self.trade()
        journal._evaluate_price_point(trade, 112, 101, 111, "day1")
        journal._evaluate_price_point(trade, 108, 99, 100, "day2")
        self.assertEqual(trade["status"], "BREAKEVEN_EJECUTADO")
        self.assertEqual(trade["final_return_pct"], 5)

    def test_ambiguous_candle_keeps_conservative_stop_priority(self):
        for partial, expected_status, expected_return in [
            (False, "STOP_EJECUTADO", -10),
            (True, "BREAKEVEN_EJECUTADO", 5),
        ]:
            with self.subTest(partial=partial):
                trade = self.trade()
                if partial:
                    journal._evaluate_price_point(trade, 112, 101, 111, "day1")
                journal._evaluate_price_point(trade, 125, 85, 110, "day2")
                self.assertEqual(trade["status"], expected_status)
                self.assertEqual(trade["final_return_pct"], expected_return)


class JournalRemovalAndStatsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "journal.json"
        patcher = patch.object(journal, "JOURNAL_PATH", str(self.path))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_stats_calculates_win_and_loss_rates(self):
        entries = [
            {"id": "1", "status": "TP2_ALCANZADO", "result": "GANADA", "final_return_pct": 10.0},
            {"id": "2", "status": "STOP_EJECUTADO", "result": "PERDIDA", "final_return_pct": -5.0},
            {"id": "3", "status": "ACTIVA", "result": "EN_CURSO", "current_return_pct": 2.0},
        ]
        stats = journal.calculate_journal_stats(entries)
        self.assertEqual(stats["total_opportunities"], 3)
        self.assertEqual(stats["active_count"], 1)
        self.assertEqual(stats["closed_count"], 2)
        self.assertEqual(stats["total_won"], 1)
        self.assertEqual(stats["total_lost"], 1)
        self.assertEqual(stats["win_rate_pct"], 50.0)
        self.assertEqual(stats["loss_rate_pct"], 50.0)
        self.assertEqual(stats["net_win_rate_pct"], 0.0)
        self.assertEqual(stats["avg_win_pct"], 10.0)
        self.assertEqual(stats["avg_loss_pct"], -5.0)

    def test_remove_single_journal_entry(self):
        entries = [
            {"id": "e1", "status": "STOP_EJECUTADO", "result": "PERDIDA", "final_return_pct": -5.0},
            {"id": "e2", "status": "ACTIVA", "result": "EN_CURSO", "current_return_pct": 2.0},
        ]
        self.path.write_text(json.dumps({"entries": entries}), encoding="utf-8")
        updated = journal.remove_journal_entry(entry_id="e1")
        self.assertEqual(len(updated["entries"]), 1)
        self.assertEqual(updated["entries"][0]["id"], "e2")
        self.assertEqual(updated["stats"]["closed_count"], 0)

    def test_remove_clear_closed_entries(self):
        entries = [
            {"id": "e1", "status": "STOP_EJECUTADO", "result": "PERDIDA", "final_return_pct": -5.0},
            {"id": "e2", "status": "TP2_ALCANZADO", "result": "GANADA", "final_return_pct": 12.0},
            {"id": "e3", "status": "ACTIVA", "result": "EN_CURSO", "current_return_pct": 2.0},
            {"id": "e4", "status": "TP1_ALCANZADO", "result": "EN_CURSO", "current_return_pct": 6.0},
        ]
        self.path.write_text(json.dumps({"entries": entries}), encoding="utf-8")
        updated = journal.remove_journal_entry(clear_closed=True)
        # Solo quedan activas (ACTIVA y TP1_ALCANZADO)
        self.assertEqual([e["id"] for e in updated["entries"]], ["e3", "e4"])
        self.assertEqual(updated["stats"]["active_count"], 2)
        self.assertEqual(updated["stats"]["closed_count"], 0)


if __name__ == "__main__":
    unittest.main()
