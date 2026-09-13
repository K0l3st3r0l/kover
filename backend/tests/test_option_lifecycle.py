"""Regression coverage for manual operations against an isolated database."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.options import router
from app.database import Base, get_db
from app.utils.auth import get_current_user
from app.models import User, Stock, Option, OptionStatus, Transaction, TransactionType
from app.services.premium_ledger import load_option_ledger


@pytest.fixture
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    user = User(id=1, email="test@example.com", username="test", hashed_password="x")
    stock = Stock(id=1, user_id=1, ticker="TEST", company_name="Test", shares=200,
                  average_cost=20, total_invested=4000, adjusted_cost_basis=20, total_premium_earned=0)
    db.add_all([user, stock]); db.commit()
    app = FastAPI(); app.include_router(router, prefix="/options")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        yield client, db, stock
    db.close(); engine.dispose()


def open_position(client, **kwargs):
    now = datetime.now(timezone.utc)
    data = dict(stock_id=1, option_type="CALL", strategy="COVERED_CALL", strike_price=22,
                contracts=2, premium_per_contract=1, opened_at=now.isoformat(),
                expiration_date=(now + timedelta(days=30)).isoformat())
    data.update(kwargs)
    return client.post("/options/", json=data)


def test_partial_then_final_preserves_realized_and_ledger(env):
    client, db, stock = env
    opened = open_position(client); assert opened.status_code == 200, opened.text
    oid = opened.json()["id"]
    partial = client.post(f"/options/{oid}/close", json={"closing_premium": .25, "contracts_to_close": 1})
    assert partial.status_code == 200, partial.text
    assert partial.json()["realized_pnl"] == 75
    assert db.get(Option, oid).contracts == 1
    closed = client.post(f"/options/{oid}/close", json={"closing_premium": .5})
    assert closed.status_code == 200, closed.text
    assert closed.json()["realized_pnl"] == 125
    row = load_option_ledger(db, 1)[1]["options"][0]
    assert row["realized_net"] == 125
    assert row["gross_premium"] == 200
    assert row["closing_cost"] == 75
    assert stock.total_premium_earned == 125
    history = client.get(f"/options/{oid}").json()
    assert history["contracts"] == 2
    assert history["total_premium"] == 200
    assert history["premium_per_contract"] == 1
    assert client.post(f"/options/{oid}/close", json={"closing_premium": 0}).status_code == 409


def test_roll_preserves_original_sell_and_partial_profit(env):
    client, db, stock = env
    oid = open_position(client).json()["id"]
    client.post(f"/options/{oid}/close", json={"closing_premium": .25, "contracts_to_close": 1})
    result = client.post(f"/options/{oid}/roll", json={
        "closing_premium": .4, "new_strike_price": 23,
        "new_premium_per_contract": .8, "new_contracts": 2,
        "new_expiration_date": (datetime.now(timezone.utc) + timedelta(days=60)).isoformat(),
        "closing_commission": .65, "opening_commission": 1.3,
    })
    assert result.status_code == 200, result.text
    assert result.json()["id"] != oid
    assert db.get(Option, oid).realized_pnl == 135
    txs = db.query(Transaction).order_by(Transaction.id).all()
    assert [(t.transaction_type, t.total_amount) for t in txs] == [
        (TransactionType.SELL_CALL, 200), (TransactionType.BUY_CALL, 25),
        (TransactionType.BUY_CALL, 40), (TransactionType.SELL_CALL, 160)]
    assert stock.total_premium_earned == pytest.approx(133.05)


def test_get_does_not_settle_an_overdue_position(env):
    client, db, stock = env
    now = datetime.now(timezone.utc)
    oid = open_position(client, opened_at=(now-timedelta(days=40)).isoformat(), expiration_date=(now-timedelta(days=2)).isoformat()).json()["id"]
    before = db.query(Transaction).count()
    response = client.get("/options/")
    assert response.status_code == 200
    assert response.json()[0]["status"] == "OPEN"
    assert response.json()[0]["settlement_pending"] is True
    assert db.query(Transaction).count() == before
    assert db.get(Option, oid).realized_pnl is None
    assert open_position(client, contracts=1).status_code == 409
    client.post(f"/options/{oid}/close", json={"closing_premium": 0, "confirm_expired": True})
    assert db.get(Option, oid).status == OptionStatus.EXPIRED
    assert db.get(Option, oid).realized_pnl == 200


@pytest.mark.parametrize("field,value", [("contracts",0),("contracts",-1),("contracts",1.5),("premium_per_contract",-1),("strike_price",0)])
def test_invalid_create_is_rejected_without_writes(env, field, value):
    client, db, _ = env
    assert open_position(client, **{field:value}).status_code == 422
    assert db.query(Option).count() == 0
    assert db.query(Transaction).count() == 0


@pytest.mark.parametrize("payload", [{"contracts_to_close":0},{"contracts_to_close":-1},{"contracts_to_close":3},{"closing_premium":-1}])
def test_invalid_close_does_not_change_position(env, payload):
    client, db, _ = env
    oid = open_position(client).json()["id"]
    assert client.post(f"/options/{oid}/close", json=payload).status_code == 422
    assert db.get(Option, oid).contracts == 2
    assert db.query(Transaction).count() == 1


def test_coverage_counts_other_calls_when_rolling(env):
    client, db, _ = env
    oid = open_position(client, contracts=1).json()["id"]
    assert open_position(client, contracts=1).status_code == 200
    response = client.post(f"/options/{oid}/roll", json={"closing_premium": .2,
        "new_strike_price": 23, "new_premium_per_contract": 1, "new_contracts": 2,
        "new_expiration_date": (datetime.now(timezone.utc)+timedelta(days=40)).isoformat()})
    assert response.status_code == 409
    assert db.get(Option, oid).status == OptionStatus.OPEN
    assert db.query(Transaction).count() == 2


def test_edit_cannot_rewrite_closed_or_partially_closed_history(env):
    client, db, _ = env
    oid = open_position(client).json()["id"]
    client.post(f"/options/{oid}/close", json={"closing_premium": .2, "contracts_to_close": 1})
    assert client.put(f"/options/{oid}", json={"premium_per_contract": 3}).status_code == 409
    assert client.put(f"/options/{oid}", json={"notes": "Checked with broker"}).status_code == 200
    assert db.query(Transaction).filter(Transaction.transaction_type == TransactionType.SELL_CALL).one().total_amount == 200


def test_manual_correction_keeps_transaction_date_and_metadata_consistent(env):
    client, db, _ = env
    oid = open_position(client, contracts=1).json()["id"]
    date = datetime.now(timezone.utc)-timedelta(days=1)
    response = client.put(f"/options/{oid}", json={"strike_price":23,"opened_at":date.isoformat()})
    assert response.status_code == 200, response.text
    tx = db.query(Transaction).one()
    assert tx.transaction_date.date() == date.date()
    assert "Strike $23" in tx.notes


def test_put_with_zero_shares_does_not_divide_by_zero(env):
    client, db, stock = env
    stock.shares = 0; db.commit()
    response = open_position(client, option_type="PUT", strategy="CASH_SECURED_PUT", contracts=1)
    assert response.status_code == 200, response.text
    assert response.json()["capital_basis"] == "STRIKE"


def test_loss_is_not_truncated_and_delete_reverses_net(env):
    client, db, stock = env
    oid = open_position(client, contracts=1).json()["id"]
    client.post(f"/options/{oid}/close", json={"closing_premium": 2})
    assert stock.total_premium_earned == -100
    assert stock.adjusted_cost_basis == 20.5
    assert client.delete(f"/options/{oid}").status_code == 200
    assert stock.total_premium_earned == 0
    assert db.query(Transaction).count() == 0


def test_import_closes_correct_expiration_and_preserves_partial_profit(env):
    import asyncio
    from app.api.import_ib import ImportRequest, confirm_import
    from tests.test_import_ib_sections import TRADES_HEADER, parse
    client, db, _ = env
    first = open_position(client, opened_at="2026-08-01T00:00:00", expiration_date="2026-10-16T00:00:00").json()["id"]
    db.get(Stock,1).shares = 400; db.commit()
    second = open_position(client, opened_at="2026-08-01T00:00:00", expiration_date="2026-11-20T00:00:00").json()["id"]
    csv = TRADES_HEADER + (
        'Trades,Data,Order,Equity and Index Options,USD,TEST 20NOV26 22 C,"2026-09-10, 12:00:00",1,0.25,0.3,-25,0,100,75,0,C\n'
        'Trades,Data,Order,Equity and Index Options,USD,TEST 20NOV26 22 C,"2026-09-11, 12:00:00",1,0.50,0.5,-50,0,100,50,0,C\n'
    )
    parsed, errors = parse(csv)
    assert not errors
    result = asyncio.run(confirm_import(body=ImportRequest(transacciones=parsed, omitir_duplicados=False), db=db, current_user=db.get(User,1)))
    assert db.get(Option,first).status == OptionStatus.OPEN, result
    assert db.get(Option,second).status == OptionStatus.CLOSED, result
    assert db.get(Option,second).realized_pnl == 125
