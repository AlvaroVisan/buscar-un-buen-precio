"""Simulaciones aisladas: confirmación, reentrada y riesgo de acumulación."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import journal_manager as journal
from scenario_engine import advance


def history(values, start="2026-01-01"):
    return pd.DataFrame([dict(Open=p, High=p + 1, Low=p - 1, Close=p) for p in values],
                        index=pd.date_range(start, periods=len(values)))


def item(price=105):
    return dict(ticker="TEST", current_price=price, score=80, atr_14=2,
                currency="$", fib_levels={"61.8%": 110, "38.2%": 125}, max=140)


class ScenarioTests(unittest.TestCase):
    def test_no_entry_from_falling_price_or_unfinished_candle(self):
        state = {"entries": []}
        bars = history([110, 108, 106, 104, 102, 130])
        self.assertEqual(advance(state, [item(102)], {"TEST": bars}, "2026-01-06 12:00:00"), set())
        self.assertEqual(state["accumulation"], [])
        self.assertEqual(state["watches"]["TEST"]["breakout"], 107)
        self.assertEqual(advance(state, [item(130)], {"TEST": bars}, "2026-01-06 16:00:00"), set())

    def test_later_close_confirms_and_stop_requires_new_structure(self):
        state = {"entries": []}
        bars = history([100, 100, 100, 100])
        advance(state, [item()], {"TEST": bars}, "2026-01-05 12:00:00")
        bars = history([100, 100, 100, 100, 100, 105])
        self.assertEqual(advance(state, [item()], {"TEST": bars}, "2026-01-07 12:00:00"), {"TEST"})
        self.assertEqual(len(state["accumulation"]), 1)
        state["entries"].append(dict(ticker="TEST", status="STOP_EJECUTADO", closed_date="2026-01-07 12:01:00"))
        self.assertEqual(advance(state, [item()], {"TEST": bars}, "2026-01-07 12:02:00"), set())
        self.assertEqual(state["watches"]["TEST"]["since"], "2026-01-07 12:02:00")

    def test_weak_market_blocks_stocks(self):
        state = {"entries": [], "watches": {"TEST": dict(since="2026-01-02", breakout=101)}}
        histories = {"TEST": history([100] * 24 + [105]), "^GSPC": history(list(range(130, 105, -1)))}
        self.assertEqual(advance(state, [item()], histories, "2026-01-26 12:00:00"), set())
        self.assertIn("bloqueada", state["watches"]["TEST"]["market_context"])

    def test_accumulation_limit_average_and_fixed_invalidation(self):
        campaign = dict(ticker="TEST", currency="$", status="ACTIVA", budget=1000,
                        invalidation=70, target=130, tranches=[], invested=0, shares=0,
                        max_drawdown_pct=0, last_check="2026-01-05 12:00:00")
        from scenario_engine import buy
        buy(campaign, 110, "2026-01-05 12:00:00")
        state = {"entries": [], "accumulation": [campaign]}
        bars = history([95, 95, 95, 95, 95, 100])
        advance(state, [item(100)], {"TEST": bars}, "2026-01-07 12:00:00")
        self.assertEqual(len(campaign["tranches"]), 2)
        self.assertAlmostEqual(campaign["average_price"], 2 / (1 / 110 + 1 / 100))
        advance(state, [item(100)], {"TEST": bars}, "2026-01-07 13:00:00")
        self.assertEqual(len(campaign["tranches"]), 2)
        bars = history([85, 85, 85, 85, 85, 90], "2026-01-04")
        advance(state, [item(90)], {"TEST": bars}, "2026-01-10 12:00:00")
        self.assertEqual(len(campaign["tranches"]), 3)
        self.assertAlmostEqual(campaign["invested"], 1000)
        self.assertEqual(campaign["invalidation"], 70)
        advance(state, [item(65)], {"TEST": bars}, "2026-01-10 13:00:00")
        self.assertEqual(campaign["status"], "CERRADA")
        self.assertEqual(campaign["exit_price"], 65)
        self.assertLess(campaign["pnl"], 0)

    def test_missing_stale_and_invalid_prices_never_open(self):
        for data in (item(float("nan")), dict(item(), is_stale=True), item()):
            state = {"entries": []}
            self.assertEqual(advance(state, [data], {}, "2026-01-07"), set())
            self.assertEqual(state["accumulation"], [])

    def test_late_closed_candle_is_checked_after_intraday_observation(self):
        from scenario_engine import buy
        campaign = dict(ticker="TEST", currency="$", status="ACTIVA", budget=1000,
                        invalidation=90, target=130, tranches=[], invested=0, shares=0,
                        max_drawdown_pct=0, last_check="2026-01-05 12:00:00")
        buy(campaign, 100, "2026-01-04 12:00:00")
        state = {"entries": [], "accumulation": [campaign]}
        bars = history([100, 100, 100, 100, 100])
        bars.iloc[-1, bars.columns.get_loc("Low")] = 85
        advance(state, [item(100)], {"TEST": bars}, "2026-01-06 12:00:00")
        self.assertEqual(campaign["status"], "CERRADA")
        self.assertEqual(campaign["exit_price"], 90)

    def test_stop_in_current_update_blocks_both_new_scenarios(self):
        from test_journal_manager import open_trade
        with tempfile.TemporaryDirectory() as temp, patch.object(journal, "JOURNAL_PATH", str(Path(temp) / "journal.json")):
            legacy = open_trade("TEST", 120)
            journal.save_journal({"entries": [legacy], "watches": {"TEST": dict(since="2026-01-01", breakout=101)}})
            result = journal.update_journal_with_market_data([item()], {"TEST": history([100, 100, 100, 100, 100, 105])})
            self.assertEqual(len(result["entries"]), 1)
            self.assertEqual(result["entries"][0]["status"], "STOP_EJECUTADO")
            self.assertEqual(result["accumulation"], [])

    def test_integration_preserves_legacy_and_opens_only_after_confirmation(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(journal, "JOURNAL_PATH", str(Path(temp) / "journal.json")):
            old = dict(id="old", ticker="OLD", status="STOP_EJECUTADO", result="PERDIDA", final_return_pct=-5)
            state = {"entries": [copy.deepcopy(old)], "watches": {"TEST": dict(since="2026-01-01", breakout=101)}}
            journal.save_journal(state)
            result = journal.update_journal_with_market_data([item()], {"TEST": history([100, 100, 100, 100, 100, 105])})
            self.assertEqual(result["entries"][-1], old)
            self.assertEqual(result["entries"][0]["strategy"], "confirmation")
            self.assertEqual(result["entries"][0]["entry_price"], 105)
            self.assertLessEqual(result["entries"][0]["stop_loss"], 101)
            self.assertEqual(result["scenario_stats"]["legacy"]["total_lost"], 1)
            self.assertEqual(result["scenario_stats"]["confirmation"]["active_count"], 1)

    def test_legacy_active_does_not_block_parallel_confirmation(self):
        from test_journal_manager import open_trade
        with tempfile.TemporaryDirectory() as temp, patch.object(journal, "JOURNAL_PATH", str(Path(temp) / "journal.json")):
            legacy = open_trade("TEST", 100)
            journal.save_journal({"entries": [legacy], "watches": {"TEST": dict(since="2026-01-01", breakout=101)}})
            bars = {"TEST": history([100, 100, 100, 100, 100, 105])}
            result = journal.update_journal_with_market_data([item()], bars)
            self.assertEqual(len(result["entries"]), 2)
            result = journal.update_journal_with_market_data([item(106)], bars)
            self.assertEqual(len(result["entries"]), 2)
            self.assertTrue(all(e["current_price"] == 106 for e in result["entries"]))


if __name__ == "__main__":
    unittest.main()
