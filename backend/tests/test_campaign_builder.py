"""Tests del builder de campañas con datos que imitan el histórico real.

El caso de MARA reproduce el assignment del 2026-04-10 que en la base quedó
guardado como EXPIRED: es la prueba de que la detección estructural funciona sin
depender de `Option.status`.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.campaigns.builder import plan_campaigns
from app.campaigns.state import detect_assignment
from app.models import CampaignCloseReason, CampaignStatus, CycleStatus, TransactionType


def dt(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def tx(id_, ticker, type_, qty, price, amount, date_, commission=0.0):
    return SimpleNamespace(
        id=id_,
        ticker=ticker,
        transaction_type=type_,
        quantity=qty,
        price=price,
        total_amount=amount,
        commission=commission,
        transaction_date=date_,
        option_id=None,
        notes=None,
    )


def opt(id_, ticker, strike, contracts, opened, expiration, status, premium,
        closing_premium=None, closed=None, realized=None):
    return SimpleNamespace(
        id=id_,
        ticker=ticker,
        strike_price=strike,
        contracts=contracts,
        opened_at=opened,
        expiration_date=expiration,
        closed_at=closed,
        status=SimpleNamespace(value=status),
        total_premium=premium,
        closing_premium=closing_premium,
        realized_pnl=realized,
        notes=None,
    )


def empty_ledger(options):
    return {
        "options": [
            {
                "option_id": o.id,
                "ticker": o.ticker,
                "matched": False,
                "realized_net": 0.0,
                "open_net": 0.0,
                "commissions": 0.0,
                "contracts": o.contracts,
                "premium_source": "OPTION_ROW_FALLBACK",
            }
            for o in options
        ],
        "unmatched_transaction_ids": [],
        "matched_transaction_ids": [],
        "ambiguous_option_ids": [],
    }


class TestDetectAssignment:
    def test_matches_strike_quantity_and_expiration(self):
        match = detect_assignment(
            sale_price=8.5,
            sale_quantity=200,
            sale_date=dt(2026, 4, 10).date(),
            open_cycles=[
                {"option_id": 1, "strike": 8.5, "contracts": 2, "expiration": dt(2026, 4, 10)}
            ],
        )
        assert match is not None
        assert match.option_id == 1
        assert match.shares == 200

    def test_rejects_when_price_is_not_the_strike(self):
        assert detect_assignment(
            sale_price=9.10,
            sale_quantity=200,
            sale_date=dt(2026, 4, 10).date(),
            open_cycles=[
                {"option_id": 1, "strike": 8.5, "contracts": 2, "expiration": dt(2026, 4, 10)}
            ],
        ) is None

    def test_rejects_when_quantity_does_not_cover_contracts(self):
        assert detect_assignment(
            sale_price=8.5,
            sale_quantity=150,
            sale_date=dt(2026, 4, 10).date(),
            open_cycles=[
                {"option_id": 1, "strike": 8.5, "contracts": 2, "expiration": dt(2026, 4, 10)}
            ],
        ) is None

    def test_rejects_when_far_from_expiration(self):
        assert detect_assignment(
            sale_price=8.5,
            sale_quantity=200,
            sale_date=dt(2026, 5, 1).date(),
            open_cycles=[
                {"option_id": 1, "strike": 8.5, "contracts": 2, "expiration": dt(2026, 4, 10)}
            ],
        ) is None


class TestPlanCampaigns:
    def test_simple_campaign_buy_sell(self):
        txs = [
            tx(1, "F", TransactionType.BUY_STOCK, 100, 10.0, 1000.0, dt(2026, 1, 5), 1.0),
            tx(2, "F", TransactionType.SELL_STOCK, 100, 12.0, 1200.0, dt(2026, 3, 1), 1.0),
        ]
        plans = plan_campaigns(txs, [], empty_ledger([]))
        assert len(plans) == 1
        plan = plans[0]
        assert plan.status == CampaignStatus.CLOSED
        assert plan.close_reason == CampaignCloseReason.STOCK_SALE
        assert plan.stock_realized_pnl == 200.0
        assert plan.stock_commissions == 2.0

    def test_assignment_closes_campaign_and_marks_cycle(self):
        """MARA: 200 acciones, call 8.5 x2, asignada el 2026-04-10.

        La fila de la opción dice EXPIRED —así quedó en la base por el bug del
        importador— y el builder igual la reconoce como asignada.
        """
        options = [
            opt(10, "MARA", 8.5, 2, dt(2026, 4, 1), dt(2026, 4, 10), "EXPIRED", 120.0)
        ]
        txs = [
            tx(1, "MARA", TransactionType.BUY_STOCK, 200, 8.0, 1600.0, dt(2026, 3, 20)),
            tx(2, "MARA", TransactionType.SELL_CALL, 2, 0.60, 120.0, dt(2026, 4, 1)),
            tx(3, "MARA", TransactionType.SELL_STOCK, 200, 8.5, 1700.0, dt(2026, 4, 10)),
        ]
        plans = plan_campaigns(txs, options, empty_ledger(options))
        assert len(plans) == 1
        plan = plans[0]
        assert plan.close_reason == CampaignCloseReason.ASSIGNED
        assert plan.status == CampaignStatus.CLOSED
        assert plan.stock_realized_pnl == 100.0
        assert len(plan.cycles) == 1
        assert plan.cycles[0].status == CycleStatus.ASSIGNED

    def test_multiple_cycles_in_one_campaign(self):
        options = [
            opt(1, "SMR", 13.0, 2, dt(2026, 5, 27), dt(2026, 6, 5), "EXPIRED", 100.0),
            opt(2, "SMR", 12.0, 2, dt(2026, 6, 8), dt(2026, 6, 12), "CLOSED", 80.0,
                closing_premium=0.10, closed=dt(2026, 6, 10)),
        ]
        txs = [tx(1, "SMR", TransactionType.BUY_STOCK, 200, 11.4, 2280.0, dt(2026, 5, 27))]
        plans = plan_campaigns(txs, options, empty_ledger(options))
        assert len(plans) == 1
        plan = plans[0]
        assert len(plan.cycles) == 2
        assert plan.shares == 200
        # Sin call abierta y con acciones en mano: lista para vender la siguiente.
        assert plan.status == CampaignStatus.STOCK_AVAILABLE

    def test_open_call_sets_call_open_status(self):
        options = [opt(1, "SMR", 12.0, 2, dt(2026, 7, 1), dt(2026, 7, 17), "OPEN", 90.0)]
        txs = [tx(1, "SMR", TransactionType.BUY_STOCK, 200, 11.0, 2200.0, dt(2026, 6, 1))]
        plans = plan_campaigns(txs, options, empty_ledger(options))
        assert plans[0].status == CampaignStatus.CALL_OPEN

    def test_two_campaigns_same_ticker(self):
        txs = [
            tx(1, "F", TransactionType.BUY_STOCK, 100, 10.0, 1000.0, dt(2026, 1, 5)),
            tx(2, "F", TransactionType.SELL_STOCK, 100, 11.0, 1100.0, dt(2026, 2, 1)),
            tx(3, "F", TransactionType.BUY_STOCK, 100, 12.0, 1200.0, dt(2026, 3, 1)),
        ]
        plans = plan_campaigns(txs, [], empty_ledger([]))
        assert len(plans) == 2
        assert plans[0].status == CampaignStatus.CLOSED
        assert plans[1].status == CampaignStatus.STOCK_ACQUIRED
        assert plans[1].shares == 100

    def test_sale_without_purchase_leaves_pnl_unknown_not_zero(self):
        """El histórico importado empieza después de la compra original."""
        txs = [tx(1, "KHC", TransactionType.SELL_STOCK, 50, 30.0, 1500.0, dt(2026, 2, 1))]
        plans = plan_campaigns(txs, [], empty_ledger([]))
        plan = plans[0]
        assert plan.stock_realized_pnl is None
        assert plan.cost_basis_status == "UNKNOWN_PRIOR_HISTORY"

    def test_dividends_land_in_the_open_campaign(self):
        txs = [
            tx(1, "F", TransactionType.BUY_STOCK, 100, 10.0, 1000.0, dt(2026, 1, 5)),
            tx(2, "F", TransactionType.DIVIDEND, 1, 15.0, 15.0, dt(2026, 6, 1)),
        ]
        plans = plan_campaigns(txs, [], empty_ledger([]))
        assert plans[0].dividends_total == 15.0

    def test_partial_sale_keeps_campaign_open(self):
        txs = [
            tx(1, "F", TransactionType.BUY_STOCK, 200, 10.0, 2000.0, dt(2026, 1, 5)),
            tx(2, "F", TransactionType.SELL_STOCK, 100, 12.0, 1200.0, dt(2026, 3, 1)),
        ]
        plans = plan_campaigns(txs, [], empty_ledger([]))
        assert len(plans) == 1
        assert plans[0].shares == 100
        assert plans[0].status == CampaignStatus.STOCK_ACQUIRED
        assert plans[0].stock_realized_pnl == 200.0
