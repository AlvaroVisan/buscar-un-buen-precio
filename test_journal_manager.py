"""Regresiones del diario con datos ficticios y archivos temporales."""

import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import journal_manager as journal


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
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "journal.json"
        patcher = patch.object(journal, "JOURNAL_PATH", str(self.path))
        patcher.start()
        self.addCleanup(patcher.stop)

    def seed(self, entries):
        self.path.write_text(json.dumps({"entries": entries}), encoding="utf-8")

    def test_new_signals_do_not_displace_existing_trades(self):
        items = [
            {"ticker": "NEW", "current_price": 50, "score": 80},
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
            {"ticker": "NEW1", "current_price": 50, "score": 80},
            {"ticker": "NEW2", "current_price": 60, "score": 80},
            {"ticker": "AAA", "current_price": 105},
        ])
        self.assertEqual([e["ticker"] for e in result["entries"]], ["NEW2", "NEW1", "AAA"])
        self.assertEqual(result["entries"][2]["current_return_pct"], 5)

    def test_repeated_new_ticker_does_not_create_duplicate(self):
        self.seed([])
        item = {"ticker": "NEW", "current_price": 50, "score": 80}
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


if __name__ == "__main__":
    unittest.main()
