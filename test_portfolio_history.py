"""El historial completo debe sostener el PnL realizado acumulado."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import portfolio_manager as portfolio


class PortfolioHistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        patcher = patch.object(portfolio, "PORTFOLIO_PATH", str(Path(temporary.name) / "portfolio.json"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_more_than_fifty_full_sales_preserve_all_returns(self):
        expected = 0
        for index in range(60):
            ticker = f"TEST{index}"
            portfolio.upsert_position(ticker, 2, 100)
            exit_price = 110 if index % 2 == 0 else 95
            portfolio.remove_or_reduce_position(ticker, sell_price=exit_price)
            expected += (exit_price - 100) * 2

        saved = portfolio.load_portfolio()
        self.assertEqual(len(saved["closed_history"]), 60)
        self.assertEqual(saved["closed_history"][0]["ticker"], "TEST59")
        self.assertEqual(saved["closed_history"][-1]["ticker"], "TEST0")
        self.assertEqual(saved["positions"], [])
        enriched = portfolio.get_enriched_portfolio([])
        self.assertEqual(enriched["summary"]["primary_realized_pnl"], expected)
        self.assertEqual(enriched["summary"]["realized_by_currency"], {"$": expected})

    def test_partial_sales_preserve_history_and_separate_currencies(self):
        portfolio.upsert_position("USD", 61, 100)
        for _ in range(60):
            portfolio.remove_or_reduce_position("USD", sell_shares=1, sell_price=102)
        portfolio.remove_or_reduce_position("USD", sell_price=90)
        portfolio.upsert_position("EUR", 2, 50, currency="€")
        portfolio.remove_or_reduce_position("EUR", sell_price=55)

        saved = portfolio.load_portfolio()
        self.assertEqual(len(saved["closed_history"]), 62)
        self.assertEqual(sum(ch["close_type"] == "PARCIAL" for ch in saved["closed_history"]), 60)
        enriched = portfolio.get_enriched_portfolio([])
        self.assertEqual(enriched["summary"]["realized_by_currency"], {"$": 110, "€": 10})
        self.assertEqual(enriched["summary"]["primary_realized_pnl"], 110)


if __name__ == "__main__":
    unittest.main()
