"""Integración sobre SQLite en memoria: cubre el caso que motivó el rediseño.

El ciclo SMR 11 Jun18 se cerró en dos tramos. La fila `options` quedó con 1
contrato y un `realized_pnl` que perdió la pata parcial, así que es justo donde
numerador y denominador se pueden desalinear.
"""

import asyncio
import unittest
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    Option, OptionStatus, OptionStrategy, OptionType,
    Stock, Transaction, TransactionType, User,
)
from app.api.analytics import get_covered_call_cycles, get_performance_metrics
from app.api.dashboard import get_dashboard_summary

NOTES = "IB | SMR Jun18'26 11 Call | Strike $11.0 | Exp 2026-06-18"
OPEN_NOTES = "IB | SMR 21AUG26 10 C | Strike $10.0 | Exp 2026-08-21"


class AnalyticsEndpointTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        user = User(id=1, email="t@t.cl", username="t", hashed_password="x")
        stock = Stock(
            id=1, user_id=1, ticker="SMR", company_name="SMR", shares=200,
            average_cost=10.0, total_invested=2000.0, adjusted_cost_basis=10.0,
            total_premium_earned=141.0, is_active=True,
        )
        self.db.add_all([user, stock])
        self.db.flush()

        self.db.add_all([
            Option(
                id=17, stock_id=1, ticker="SMR", option_type=OptionType.CALL,
                strategy=OptionStrategy.COVERED_CALL, strike_price=11.0,
                contracts=1, premium_per_contract=0.33, total_premium=33.0,
                expiration_date=datetime(2026, 6, 18), status=OptionStatus.CLOSED,
                opened_at=datetime(2026, 6, 15), closed_at=datetime(2026, 6, 18),
                closing_premium=0.43, realized_pnl=-10.0,
            ),
            Option(
                id=20, stock_id=1, ticker="SMR", option_type=OptionType.CALL,
                strategy=OptionStrategy.COVERED_CALL, strike_price=10.0,
                contracts=2, premium_per_contract=0.54, total_premium=108.0,
                expiration_date=datetime(2026, 8, 21), status=OptionStatus.OPEN,
                opened_at=datetime(2026, 7, 21),
            ),
        ])
        self.db.add_all([
            Transaction(id=124, user_id=1, stock_id=1, ticker="SMR",
                        transaction_type=TransactionType.SELL_CALL, quantity=2, price=0.33,
                        total_amount=66.0, commission=1.4, notes=NOTES,
                        transaction_date=datetime(2026, 6, 15)),
            Transaction(id=125, user_id=1, stock_id=1, ticker="SMR",
                        transaction_type=TransactionType.BUY_CALL, quantity=1, price=0.40,
                        total_amount=40.0, commission=1.05, notes=NOTES,
                        transaction_date=datetime(2026, 6, 18)),
            Transaction(id=127, user_id=1, stock_id=1, ticker="SMR",
                        transaction_type=TransactionType.BUY_CALL, quantity=1, price=0.43,
                        total_amount=43.0, commission=1.05, notes=NOTES,
                        transaction_date=datetime(2026, 6, 18)),
            Transaction(id=136, user_id=1, stock_id=1, ticker="SMR",
                        transaction_type=TransactionType.SELL_CALL, quantity=2, price=0.54,
                        total_amount=108.0, commission=1.4, notes=OPEN_NOTES,
                        transaction_date=datetime(2026, 7, 21)),
        ])
        self.db.commit()
        self.user = self.db.query(User).first()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_partially_closed_cycle_uses_the_full_contract_denominator(self):
        result = asyncio.run(get_covered_call_cycles(db=self.db, current_user=self.user))
        cycle = next(c for c in result["cycles"] if c["strike_price"] == 11.0)

        self.assertEqual(cycle["premium_source"], "TRANSACTIONS_EXACT")
        self.assertEqual(cycle["row_contracts"], 1)
        self.assertEqual(cycle["contracts"], 2)
        self.assertEqual(cycle["capital"], 2200.0)
        self.assertEqual(cycle["net_premium"], -17.0)
        self.assertEqual(cycle["raw_option_net_premium"], -10.0)
        self.assertEqual(cycle["commissions"], 3.5)
        self.assertEqual(cycle["net_premium_net_of_fees"], -20.5)
        self.assertEqual(cycle["annualized_return_gross"], -94.02)
        self.assertEqual(cycle["annualized_return"], -113.37)

    def test_cycles_summary_reconciles_against_the_transaction_ledger(self):
        summary = asyncio.run(get_covered_call_cycles(db=self.db, current_user=self.user))["summary"]

        self.assertEqual(summary["ledger_status"], "RECONCILED")
        self.assertEqual(summary["transaction_net_premium"], 91.0)
        self.assertEqual(summary["total_net_premium"], 91.0)
        self.assertEqual(summary["closed_net_premium"], -17.0)
        self.assertEqual(summary["open_net_premium"], 108.0)
        self.assertEqual(summary["option_row_net_premium"], 98.0)
        self.assertEqual(summary["option_row_difference"], 7.0)
        self.assertEqual(summary["total_commissions"], 4.9)
        self.assertEqual(summary["unmatched_transaction_count"], 0)
        self.assertEqual(summary["ambiguous_option_ids"], [])
        self.assertFalse(summary["annualized_is_portfolio_return"])

    def test_open_premium_stays_out_of_dashboard_total_pnl(self):
        with patch("app.api.dashboard.MarketDataService.get_current_price", return_value=None):
            summary = get_dashboard_summary(db=self.db, current_user=self.user)

        self.assertEqual(summary["total_premium_earned"], -17.0)
        self.assertEqual(summary["open_option_premium"], 108.0)
        self.assertEqual(summary["option_commissions"], 4.9)
        self.assertEqual(summary["total_premium_net_of_fees"], -21.9)
        self.assertEqual(summary["ledger_status"], "RECONCILED")
        # unrealized 0 + cerrado -17 + dividendos 0 - comisiones 4.9
        self.assertEqual(summary["total_pnl"], -21.9)

    def test_performance_metrics_reports_the_same_ledger(self):
        with patch("app.api.analytics.MarketDataService.get_current_price", return_value=None):
            metrics = asyncio.run(get_performance_metrics(db=self.db, current_user=self.user))

        self.assertEqual(metrics["closed_option_pnl"], -17.0)
        self.assertEqual(metrics["open_option_premium"], 108.0)
        self.assertEqual(metrics["transaction_option_net"], 91.0)
        self.assertEqual(metrics["option_ledger_difference"], 0.0)
        self.assertEqual(metrics["ledger_status"], "RECONCILED")
        self.assertFalse(metrics["roi_net_total_is_portfolio_return"])


if __name__ == "__main__":
    unittest.main()
