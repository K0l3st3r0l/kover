from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as N
from unittest.mock import patch

import pytest

from tests.test_option_lifecycle import env, open_position
from tests.test_covered_calls import make_quote
from app.api.scanner import router as scanner_router
from app.models import Instrument, CoveredCallCandidate, Option, Campaign, CoveredCallCycle, CycleStatus, CampaignStatus
from app.scanner.cc_scan import run
from app.campaigns.metrics import campaign_summary
from app.campaigns.builder import _cycle_plan_from_option
from app.campaigns.valuation import option_marks
from app.services.premium_ledger import load_option_ledger
from app.scanner.covered_calls import compute_covered_call


def chain(*, age=0, quotes=None):
    now = datetime.now(timezone.utc)
    quote = make_quote(expiration=(now + timedelta(days=20)).date(), strike=22, bid=1, ask=1.1)
    return ([quote] if quotes is None else quotes, N(price=20, ask=20.01, as_of=now-timedelta(hours=age)))


def test_holdings_subtracts_reserved_calls_and_uses_ledger_cost(env):
    client, db, stock = env
    client.app.include_router(scanner_router, prefix="/scanner")
    open_position(client, contracts=1)
    stock.total_premium_earned = 999; stock.adjusted_cost_basis = 1; db.commit()
    with patch("app.api.scanner.CboeChainsProvider.get_chain", return_value=chain()):
        response = client.get("/scanner/covered-calls/holdings?include_loss_making=false")
    assert response.status_code == 200, response.text
    position = response.json()["positions"][0]
    assert position["contracts"] == 1
    assert position["cost_basis"] == 20
    assert position["reserved_contracts"] == 1
    assert position["candidates"][0]["position_premium_total"] == 100
    open_position(client, contracts=1)
    with patch("app.api.scanner.CboeChainsProvider.get_chain") as provider:
        assert client.get("/scanner/covered-calls/holdings").json()["positions"] == []
        provider.assert_not_called()


def test_holdings_rejects_stale_quotes(env):
    client, db, _ = env
    client.app.include_router(scanner_router, prefix="/scanner")
    with patch("app.api.scanner.CboeChainsProvider.get_chain", return_value=chain(age=25)):
        response = client.get("/scanner/covered-calls/holdings")
    assert response.status_code == 200, response.text
    assert response.json()["positions"] == []
    assert "24 horas" in response.json()["errors"][0]["error"]


def candidate(db, **overrides):
    inst = db.query(Instrument).first()
    if inst is None:
        inst = Instrument(symbol="TEST", name="Test", universe_stage="OPTIONABLE")
        db.add(inst); db.flush()
    now = datetime.now(timezone.utc)
    data = dict(instrument_id=inst.id, pick_type="BALANCED", occ_symbol="TEST-C", expiration=(now+timedelta(days=10)).date(),
        strike=22, dte=20, scanned_at=now, quote_as_of=now, premium_yield=.05, return_if_assigned=.15)
    data.update(overrides)
    row = CoveredCallCandidate(**data); db.add(row); db.commit()
    return row


def test_listing_drops_expired_and_stale_and_recalculates_dte(env):
    client, db, _ = env
    client.app.include_router(scanner_router, prefix="/scanner")
    now = datetime.now(timezone.utc)
    candidate(db, expiration=(now-timedelta(days=1)).date())
    candidate(db, quote_as_of=now-timedelta(hours=25))
    candidate(db)
    response = client.get("/scanner/covered-calls?max_dte=11")
    assert response.status_code == 200, response.text
    rows = response.json()["candidates"]
    assert len(rows) == 1
    assert rows[0]["dte"] in [10,11]
    assert rows[0]["annualized_premium_yield"] == pytest.approx(.05*365/rows[0]["dte"])


def test_scan_removes_old_picks_when_no_contract_remains(env):
    _, db, _ = env
    candidate(db)
    provider = N(get_chain=lambda symbol: chain(quotes=[]))
    with patch("app.scanner.cc_scan.time.sleep"):
        result = run(db, symbols=["TEST"], provider=provider)
    assert result["symbols_without_candidates"] == 1
    assert db.query(CoveredCallCandidate).count() == 0


def test_crossed_and_nonstandard_quotes_are_not_candidates():
    now = datetime.now(timezone.utc).date()
    assert compute_covered_call(make_quote(bid=1, ask=.5),20,20,now) is None
    assert compute_covered_call(make_quote(multiplier=10),20,20,now) is None


def campaign(**overrides):
    data=dict(stock_realized_pnl=0, option_realized_pnl=0, option_open_premium=100,
              dividends_total=0, commissions_total=0, shares=100, shares_peak=100,
              stock_cost_basis=20, days_deployed=30, opened_at=datetime.now(timezone.utc)-timedelta(days=30),
              closed_at=None, cycles=[])
    data.update(overrides)
    return N(**data)


def test_market_value_includes_option_liability_and_never_assumes_missing_ask_is_zero():
    assert campaign_summary(campaign(), 20, option_liability=20)["mark_to_market_pnl"] == 80
    missing = campaign_summary(campaign(), 20)
    assert missing["mark_to_market_pnl"] is None
    assert missing["mark_to_market_reason"]
    assert campaign_summary(campaign(shares=0,option_open_premium=0), None)["mark_to_market_pnl"] == 0


def test_partial_cycle_uses_original_gross_and_real_remaining_liability(env):
    client, db, _ = env
    oid = open_position(client).json()["id"]
    client.post(f"/options/{oid}/close",json={"contracts_to_close":1,"closing_premium":.25})
    option = db.get(Option,oid)
    ledger = load_option_ledger(db,1)[1]["options"][0]
    plan = _cycle_plan_from_option(option,ledger,False)
    assert plan.entry_premium == 1
    assert plan.gross_premium == 200
    assert plan.closing_cost == 25
    cycle = N(id=1,option_id=oid,status=CycleStatus.OPEN,ticker="TEST")
    quote = make_quote(expiration=option.expiration_date.date(),strike=option.strike_price,bid=.15,ask=.2)
    marks=option_marks(db,[N(cycles=[cycle])],provider=N(get_chain=lambda symbol: chain(quotes=[quote])))
    assert marks[1]["liability"] == 20
    stale=option_marks(db,[N(cycles=[cycle])],provider=N(get_chain=lambda symbol: chain(age=30,quotes=[quote])))
    assert stale[1]["error"]
