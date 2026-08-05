import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.utils.portfolio_metrics import (
    annualize_simple_premium,
    build_option_transaction_ledger,
    calculate_total_return_breakdown,
    premium_by_ticker,
    split_option_premium,
    summarize_cycles,
)


def option(**kwargs):
    base = dict(
        id=1, ticker="SMR", strike_price=11.0, contracts=1,
        expiration_date=date(2026, 6, 18), opened_at=date(2026, 6, 15),
        closed_at=date(2026, 6, 18), status="CLOSED",
        total_premium=33.0, closing_premium=0.43, realized_pnl=-10.0,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def transaction(**kwargs):
    base = dict(
        id=1, option_id=None, ticker="SMR", transaction_type="SELL_CALL",
        total_amount=66.0, commission=1.4, quantity=2,
        transaction_date=date(2026, 6, 15),
        notes="IB | SMR Jun18'26 11 Call | Strike $11.0 | Exp 2026-06-18",
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


class PortfolioMetricsTests(unittest.TestCase):
    def test_annualized_premium_is_a_simple_cycle_metric(self):
        self.assertEqual(annualize_simple_premium(16, 1300, 3), 149.74)

    def test_summary_separates_closed_and_open_premiums(self):
        summary = summarize_cycles(
            [
                {"status": "CLOSED", "net_premium": 48, "net_premium_net_of_fees": 46.6,
                 "commissions": 1.4, "annualized_return": 73.61, "capital": 1700},
                {"status": "CLOSED", "net_premium": -47, "net_premium_net_of_fees": -49.1,
                 "commissions": 2.1, "annualized_return": -144.16, "capital": 1700},
                {"status": "OPEN", "net_premium": 108, "net_premium_net_of_fees": 106.6,
                 "commissions": 1.4, "annualized_return": 63.58, "capital": 2000},
            ]
        )

        self.assertEqual(summary["closed_net_premium"], 1.0)
        self.assertEqual(summary["open_net_premium"], 108.0)
        self.assertEqual(summary["total_net_premium"], 109.0)
        self.assertEqual(summary["total_commissions"], 4.9)
        self.assertEqual(summary["total_net_premium_after_fees"], 104.1)
        self.assertEqual(summary["closed_positive_cycles"], 1)
        self.assertEqual(summary["closed_negative_cycles"], 1)
        self.assertEqual(summary["closed_win_rate"], 50.0)
        self.assertEqual(summary["avg_closed_annualized"], -35.27)

    def test_open_premium_is_not_portfolio_return(self):
        result = calculate_total_return_breakdown(
            stock_realized_pnl=100,
            stock_unrealized_pnl=-20,
            closed_option_pnl=30,
            open_option_premium=108,
            dividends=5,
            commissions=10,
        )

        self.assertEqual(result["realized_total_pnl"], 125.0)
        self.assertEqual(result["mark_to_market_total_pnl"], 105.0)
        self.assertEqual(result["open_option_premium"], 108.0)

    def test_partial_option_keeps_realized_and_open_parts_separate(self):
        self.assertEqual(
            split_option_premium(status="OPEN", total_premium=80, realized_pnl=12),
            (12.0, 80.0),
        )
        self.assertEqual(
            split_option_premium(status="CLOSED", total_premium=80, closing_cost=20),
            (60.0, 0.0),
        )

    def test_transaction_ledger_requires_exact_option_metadata(self):
        transactions = [
            transaction(id=124),
            transaction(id=125, transaction_type="BUY_CALL", total_amount=40, quantity=1,
                        commission=1.05, transaction_date=date(2026, 6, 18)),
            transaction(id=127, transaction_type="BUY_CALL", total_amount=43, quantity=1,
                        commission=1.05, transaction_date=date(2026, 6, 18)),
            transaction(id=999, transaction_type="BUY_CALL", total_amount=99, quantity=1,
                        notes="IB | SMR Jun18'26 12 Call | Strike $12.0 | Exp 2026-06-18"),
        ]

        ledger = build_option_transaction_ledger([option()], transactions)
        row = ledger["options"][0]
        self.assertEqual(row["transaction_net"], -17.0)
        self.assertEqual(row["realized_net"], -17.0)
        self.assertEqual(row["commissions"], 3.5)
        self.assertEqual(ledger["unmatched_transaction_ids"], [999])

    def test_partial_close_keeps_the_original_contract_count(self):
        """El cierre parcial baja `contracts` en la fila; el numerador cubre 2."""
        transactions = [
            transaction(id=124, quantity=2),
            transaction(id=125, transaction_type="BUY_CALL", total_amount=40, quantity=1,
                        transaction_date=date(2026, 6, 18)),
            transaction(id=127, transaction_type="BUY_CALL", total_amount=43, quantity=1,
                        transaction_date=date(2026, 6, 18)),
        ]

        row = build_option_transaction_ledger([option(contracts=1)], transactions)["options"][0]
        self.assertEqual(row["row_contracts"], 1)
        self.assertEqual(row["sold_contracts"], 2)
        self.assertEqual(row["contracts"], 2)
        # -17 sobre 2 contratos a strike 11 en 3 días, no sobre 1.
        self.assertEqual(annualize_simple_premium(row["realized_net"], 11 * row["contracts"] * 100, 3), -94.02)

    def test_reselling_the_same_contract_does_not_double_count(self):
        """Vender, recomprar y volver a vender la misma terna crea dos filas."""
        first = option(id=1, opened_at=date(2026, 6, 1), closed_at=date(2026, 6, 5))
        second = option(id=2, opened_at=date(2026, 6, 10), closed_at=date(2026, 6, 18))
        transactions = [
            transaction(id=1, total_amount=50, quantity=1, transaction_date=date(2026, 6, 1)),
            transaction(id=2, transaction_type="BUY_CALL", total_amount=20, quantity=1,
                        transaction_date=date(2026, 6, 5)),
            transaction(id=3, total_amount=60, quantity=1, transaction_date=date(2026, 6, 10)),
            transaction(id=4, transaction_type="BUY_CALL", total_amount=15, quantity=1,
                        transaction_date=date(2026, 6, 18)),
        ]

        ledger = build_option_transaction_ledger([first, second], transactions)
        self.assertEqual(ledger["options"][0]["matched_transaction_ids"], [1, 2])
        self.assertEqual(ledger["options"][1]["matched_transaction_ids"], [3, 4])
        self.assertEqual(ledger["options"][0]["realized_net"], 30.0)
        self.assertEqual(ledger["options"][1]["realized_net"], 45.0)
        self.assertEqual(ledger["ambiguous_option_ids"], [])

    def test_unassignable_duplicate_is_flagged_instead_of_silently_doubled(self):
        """Sin fechas que las separen, la segunda fila queda marcada, no sumada a ciegas."""
        first = option(id=1, opened_at=date(2026, 6, 15), closed_at=date(2026, 6, 18))
        second = option(id=2, opened_at=date(2026, 6, 15), closed_at=date(2026, 6, 18))

        ledger = build_option_transaction_ledger([first, second], [transaction(id=1)])
        self.assertEqual(ledger["options"][0]["premium_source"], "TRANSACTIONS_EXACT")
        self.assertEqual(ledger["options"][1]["premium_source"], "OPTION_ROW_AMBIGUOUS")
        self.assertEqual(ledger["ambiguous_option_ids"], [2])

    def test_explicit_option_id_wins_over_note_metadata(self):
        other = option(id=7, opened_at=date(2026, 6, 15), closed_at=date(2026, 6, 18))
        ledger = build_option_transaction_ledger(
            [option(id=1), other],
            [transaction(id=50, option_id=7)],
        )
        self.assertEqual(ledger["options"][0]["matched_transaction_ids"], [])
        self.assertEqual(ledger["options"][1]["matched_transaction_ids"], [50])

    def test_expiry_date_is_read_in_utc_regardless_of_session_timezone(self):
        """Un vencimiento a medianoche UTC no puede correrse un día por el TZ."""
        santiago = timezone(timedelta(hours=-4))
        utc_midnight = datetime(2026, 6, 18, 0, 0, tzinfo=timezone.utc)
        shifted = utc_midnight.astimezone(santiago)  # 2026-06-17 20:00 -04

        ledger = build_option_transaction_ledger(
            [option(expiration_date=shifted, opened_at=None, closed_at=None)],
            [transaction(id=1)],
        )
        self.assertEqual(ledger["options"][0]["matched_transaction_ids"], [1])

    def test_settlement_margin_only_applies_when_the_strict_window_fails(self):
        """La recompra fechada en la liquidación sigue perteneciendo al ciclo."""
        ledger = build_option_transaction_ledger(
            [option(opened_at=date(2026, 6, 15), closed_at=date(2026, 6, 18))],
            [transaction(id=1, transaction_type="BUY_CALL", total_amount=10,
                         transaction_date=date(2026, 6, 20))],
        )
        self.assertEqual(ledger["options"][0]["matched_transaction_ids"], [1])
        self.assertEqual(ledger["unmatched_transaction_ids"], [])

    def test_premium_by_ticker_nets_commissions(self):
        ledger = build_option_transaction_ledger(
            [option(id=1, status="OPEN", closed_at=None, realized_pnl=None)],
            [transaction(id=1, total_amount=108, commission=1.4)],
        )
        totals = premium_by_ticker(ledger)
        self.assertEqual(totals["SMR"]["realized"], 0.0)
        self.assertEqual(totals["SMR"]["open"], 108.0)
        self.assertEqual(totals["SMR"]["commissions"], 1.4)
        self.assertEqual(totals["SMR"]["net_of_fees"], 106.6)

    def test_annualized_metric_rejects_invalid_denominator(self):
        self.assertEqual(annualize_simple_premium(10, 0, 3), 0.0)
        self.assertEqual(annualize_simple_premium(10, 100, 0), 0.0)


if __name__ == "__main__":
    unittest.main()
