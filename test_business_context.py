"""Lectura contable y recuperación de fallos sin consultas de red."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import business_context as business

NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)


def statements():
    columns = pd.to_datetime(["2025-12-31", "2024-12-31", "2023-12-31"])
    income = pd.DataFrame({"TotalRevenue": [120, 110, 100], "NetIncome": [12, 10, 8]}, index=columns).T
    cash = pd.DataFrame({"OperatingCashFlow": [20, 18, 15], "FreeCashFlow": [10, 9, 7]}, index=columns).T
    balance = pd.DataFrame({"TotalDebt": [30, 35, 40], "CashCashEquivalentsAndShortTermInvestments": [10, 10, 10]}, index=columns).T
    return income, cash, balance


class BusinessReadingTests(unittest.TestCase):
    def read(self, modify=None, **info):
        frames = statements()
        if modify:
            modify(*frames)
        return business.build_context("TEST", {"quoteType": "EQUITY", "sector": "Technology", "trailingPE": 45, **info}, *frames, now=NOW)

    def test_favorable_requires_all_dimensions_and_separates_valuation(self):
        result = self.read()
        self.assertEqual(result["classification"], "favorable")
        self.assertEqual(len(result["strengths"]), 5)
        self.assertIn("45.0", result["valuation"])
        self.assertIn("expectativas", result["valuation"])
        self.assertEqual(result["report_date"], "2025-12-31")
        json.dumps(result, allow_nan=False)

    def test_missing_or_nan_cash_never_gets_favorable(self):
        result = self.read(lambda income, cash, balance: cash.loc.__setitem__("FreeCashFlow", float("nan")))
        self.assertEqual(result["classification"], "insufficient")
        json.dumps(result, allow_nan=False)

    def test_one_weakness_is_mixed_two_are_weak(self):
        def declining(income, cash, balance):
            income.iloc[income.index.get_loc("TotalRevenue"), 0] = 90
        self.assertEqual(self.read(declining)["classification"], "mixed")
        def loss_and_decline(income, cash, balance):
            declining(income, cash, balance)
            income.iloc[income.index.get_loc("NetIncome"), 0] = -5
        self.assertEqual(self.read(loss_and_decline)["classification"], "weak")

    def test_stale_statements_and_special_sectors_are_insufficient(self):
        frames = statements()
        result = business.build_context("TEST", {"quoteType": "EQUITY"}, *frames,
                                        now=datetime(2028, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(result["classification"], "insufficient")
        self.assertEqual(self.read(sector="Financial Services")["classification"], "insufficient")

    def test_misaligned_years_are_not_compared(self):
        def change_year(income, cash, balance):
            income.columns = pd.to_datetime(["2026-03-31", "2025-03-31", "2024-03-31"])
        self.assertEqual(self.read(change_year)["classification"], "insufficient")

    def test_funds_and_other_assets_are_not_companies(self):
        self.assertFalse(self.read(quoteType="ETF")["supported"])
        for symbol in ("^GSPC", "GC=F", "BTC-USD"):
            self.assertFalse(business.is_company_candidate(symbol))

    def test_non_positive_earnings_do_not_get_a_valuation_multiple(self):
        result = self.read(trailingPE=None, trailingEps=-2)
        self.assertIn("no es positivo", result["valuation"])

    def test_deteriorating_margin_is_a_risk_even_if_still_profitable(self):
        def shrinking_margin(income, cash, balance):
            income.iloc[income.index.get_loc("NetIncome"), 0] = 1
        result = self.read(shrinking_margin)
        self.assertEqual(result["classification"], "mixed")
        self.assertTrue(any("margen" in risk for risk in result["risks"]))

    def test_unknown_sector_cannot_receive_favorable_reading(self):
        self.assertEqual(self.read(sector=None)["classification"], "insufficient")


class BusinessCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "cache.json"
        patcher = patch.object(business, "CACHE_PATH", str(self.path))
        patcher.start()
        self.addCleanup(patcher.stop)
        retry = patch.object(business, "_retry_after", {})
        retry.start()
        self.addCleanup(retry.stop)

    def test_reuses_cached_financials_without_network(self):
        with patch.object(business.yf, "Ticker") as ticker:
            company = ticker.return_value
            company.get_info.return_value = {"quoteType": "EQUITY"}
            company.get_income_stmt.return_value, company.get_cashflow.return_value, company.get_balance_sheet.return_value = statements()
            first = business.get_business_context("TEST")
            second = business.get_business_context("TEST")
        self.assertEqual(first, second)
        ticker.assert_called_once_with("TEST")
        self.assertTrue(self.path.exists())

    def test_expired_cache_on_failure_keeps_original_date_and_marks_stale(self):
        old = {"schema_version": business.SCHEMA_VERSION, "ticker": "TEST", "fetched_at": "2020-01-01T00:00:00+00:00"}
        self.path.write_text(json.dumps({"TEST": old}), encoding="utf-8")
        with patch.object(business.yf, "Ticker", side_effect=RuntimeError("offline")) as ticker:
            first = business.get_business_context("TEST")
            second = business.get_business_context("TEST")
        self.assertTrue(first["is_stale"])
        self.assertEqual(first["fetched_at"], old["fetched_at"])
        self.assertEqual(first, second)
        self.assertEqual(ticker.call_count, 1)

    def test_network_failure_is_not_a_positive_reading(self):
        with patch.object(business.yf, "Ticker", side_effect=RuntimeError("offline")):
            result = business.get_business_context("TEST")
        self.assertEqual(result["classification"], "insufficient")
        self.assertIsNone(result["fetched_at"])


if __name__ == "__main__":
    unittest.main()
