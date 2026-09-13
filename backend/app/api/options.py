from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Option, Stock, OptionType, OptionStrategy, OptionStatus, Transaction, TransactionType
from ..models.user import User
from ..utils.auth import get_current_user
from ..market import MarketDataService
from ..utils import OptionsCalculator
from ..utils.calculators import SANTIAGO_TZ
from ..services.premium_ledger import load_option_ledger, load_premium_by_ticker, adjusted_basis
from ..services.option_positions import available_call_contracts

router = APIRouter()


class OptionCreate(BaseModel):
    stock_id: int
    option_type: OptionType
    strategy: OptionStrategy
    strike_price: float = Field(gt=0, allow_inf_nan=False)
    contracts: int = Field(gt=0, strict=True)
    premium_per_contract: float = Field(ge=0, allow_inf_nan=False)
    expiration_date: datetime
    commission: float = Field(default=0, ge=0, allow_inf_nan=False)
    notes: Optional[str] = None
    opened_at: Optional[datetime] = None


class OptionResponse(BaseModel):
    id: int
    stock_id: int
    ticker: str
    option_type: OptionType
    strategy: OptionStrategy
    strike_price: float
    contracts: int
    premium_per_contract: float
    total_premium: float
    expiration_date: datetime
    status: OptionStatus
    opened_at: datetime
    closed_at: Optional[datetime] = None
    realized_pnl: Optional[float] = None
    days_to_expiration: Optional[int] = None
    settlement_pending: bool = False
    premium_yield: Optional[float] = None
    annualized_return: Optional[float] = None
    current_price: Optional[float] = None
    notes: Optional[str] = None
    capital_basis: Optional[str] = None
    editable_terms: bool = False

    class Config:
        from_attributes = True


def _today():
    return datetime.now(SANTIAGO_TZ).date()


def _enrich_response(response, option, stock=None, ledger_row=None):
    response.days_to_expiration = OptionsCalculator.calculate_days_to_expiration(option.expiration_date)
    response.settlement_pending = option.status == OptionStatus.OPEN and option.expiration_date.date() < _today()
    basis = option.strike_price if option.option_type == OptionType.PUT else (stock.average_cost if stock else None)
    response.capital_basis = "STRIKE" if option.option_type == OptionType.PUT else "STOCK_COST"
    contracts = (ledger_row or {}).get("contracts", option.contracts)
    premium = option.total_premium
    if ledger_row:
        premium = ledger_row["realized_net"] + ledger_row["open_net"] - ledger_row["commissions"]
        response.realized_pnl = ledger_row["realized_net"]
        if option.status != OptionStatus.OPEN and ledger_row.get("gross_premium") is not None:
            response.contracts = int(contracts)
            response.total_premium = ledger_row["gross_premium"]
            response.premium_per_contract = response.total_premium / (contracts * 100) if contracts else 0
    capital = (basis or 0) * contracts * 100
    if capital > 0:
        response.premium_yield = round(premium / capital * 100, 2)
        days = (option.expiration_date.date() - option.opened_at.date()).days
        if days > 0:
            response.annualized_return = round(premium / capital * 100 * 365 / days, 2)


def _editable(db, option, row):
    if option.status != OptionStatus.OPEN or option.realized_pnl is not None or not row or len(row["matched_transaction_ids"]) != 1:
        return False
    tx = db.get(Transaction, row["matched_transaction_ids"][0])
    return tx is not None and tx.option_id == option.id


def _response(db, option, user):
    _, ledger = load_option_ledger(db, user.id)
    row = next((r for r in ledger["options"] if r["option_id"] == option.id), None)
    response = OptionResponse.model_validate(option)
    response.editable_terms = _editable(db, option, row)
    _enrich_response(response, option, option.stock, row)
    return response


def _stock(db, stock_id, user_id):
    stock = db.query(Stock).filter(Stock.id == stock_id, Stock.user_id == user_id).with_for_update().populate_existing().first()
    if stock is None:
        raise HTTPException(404, "Stock not found")
    return stock


def _position(db, option_id, user_id):
    option = db.query(Option).join(Stock).filter(Option.id == option_id, Stock.user_id == user_id).first()
    if option is None:
        raise HTTPException(404, "Option not found")
    # All manual writes serialize on the underlying, including opening new calls.
    stock = _stock(db, option.stock_id, user_id)
    db.refresh(option)
    return option, stock


def _validate_terms(db, stock, option_type, strategy, contracts, expiration, opened, exclude_id=None):
    expected = OptionStrategy.COVERED_CALL if option_type == OptionType.CALL else OptionStrategy.CASH_SECURED_PUT
    if strategy != expected:
        raise HTTPException(422, "La estrategia no corresponde al tipo de opción.")
    if expiration.date() < opened.date():
        raise HTTPException(422, "El vencimiento no puede ser anterior a la apertura.")
    if option_type == OptionType.CALL:
        available = available_call_contracts(db, stock, exclude_id)
        if contracts > available:
            raise HTTPException(409, f"Cobertura insuficiente: quedan {available} contratos disponibles.")


def _sync_basis(db, stock, user_id):
    db.flush()
    premiums = load_premium_by_ticker(db, user_id)
    bucket = premiums.get(stock.ticker, {})
    stock.total_premium_earned = round(bucket.get("realized", 0) - bucket.get("commissions", 0), 2)
    stock.adjusted_cost_basis = adjusted_basis(stock, bucket)


def _transaction(db, option, user_id, *, opening, premium, contracts, commission=0, at=None, note=""):
    if option.option_type == OptionType.CALL:
        tt = TransactionType.SELL_CALL if opening else TransactionType.BUY_CALL
    else:
        tt = TransactionType.SELL_PUT if opening else TransactionType.BUY_PUT
    db.add(Transaction(
        user_id=user_id, stock_id=option.stock_id, option_id=option.id,
        ticker=option.ticker, transaction_type=tt, quantity=contracts,
        price=premium, total_amount=round(premium * contracts * 100, 2), commission=commission,
        transaction_date=at or datetime.now(timezone.utc),
        notes=f"{note} | Strike ${option.strike_price} | Exp {option.expiration_date.date().isoformat()}",
    ))


@router.post("/", response_model=OptionResponse)
def create_option(option: OptionCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    stock = _stock(db, option.stock_id, current_user.id)
    opened = option.opened_at or datetime.now(timezone.utc)
    _validate_terms(db, stock, option.option_type, option.strategy, option.contracts, option.expiration_date, opened)
    new = Option(**option.model_dump(exclude={"commission", "opened_at"}), ticker=stock.ticker,
                 total_premium=round(option.contracts * 100 * option.premium_per_contract, 2), opened_at=opened)
    db.add(new)
    db.flush()
    _transaction(db, new, current_user.id, opening=True, premium=option.premium_per_contract,
                 contracts=option.contracts, commission=option.commission, at=opened)
    _sync_basis(db, stock, current_user.id)
    db.commit()
    return _response(db, new, current_user)


@router.get("/", response_model=List[OptionResponse])
def get_options(status: OptionStatus = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    options, ledger = load_option_ledger(db, current_user.id)
    rows = {r["option_id"]: r for r in ledger["options"]}
    results = []
    for option in sorted(options, key=lambda o: o.expiration_date, reverse=True):
        if status and option.status != status:
            continue
        response = OptionResponse.model_validate(option)
        response.editable_terms = _editable(db, option, rows.get(option.id))
        _enrich_response(response, option, option.stock, rows.get(option.id))
        results.append(response)
    return results


@router.get("/expiring-soon", response_model=List[OptionResponse])
def get_expiring_soon_options(days: int = 7, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    options = get_options(OptionStatus.OPEN, db, current_user)
    # Overdue positions remain visible until their settlement is confirmed.
    results = [o for o in options if o.expiration_date.date() <= _today() + timedelta(days=days)]
    try:
        prices = MarketDataService.get_multiple_prices(list({o.ticker for o in results})) if results else {}
    except Exception:
        prices = {}
    for response in results:
        response.current_price = prices.get(response.ticker)
    return results


class OptionUpdate(BaseModel):
    strike_price: Optional[float] = Field(default=None, gt=0, allow_inf_nan=False)
    contracts: Optional[int] = Field(default=None, gt=0, strict=True)
    premium_per_contract: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    expiration_date: Optional[datetime] = None
    strategy: Optional[OptionStrategy] = None
    status: Optional[OptionStatus] = None
    notes: Optional[str] = None
    realized_pnl: Optional[float] = Field(default=None, allow_inf_nan=False)
    opened_at: Optional[datetime] = None


@router.put("/{option_id}", response_model=OptionResponse)
def update_option(option_id: int, data: OptionUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    option, stock = _position(db, option_id, current_user.id)
    changes = data.model_dump(exclude_none=True)
    if data.status is not None and data.status != option.status:
        raise HTTPException(409, "Registra el cierre o importa la liquidación desde el broker para cambiar el estado.")
    if data.realized_pnl is not None and data.realized_pnl != option.realized_pnl:
        raise HTTPException(409, "El resultado se calcula desde las transacciones; no se edita manualmente.")
    terms = {k: v for k, v in changes.items() if k not in {"notes", "status", "realized_pnl"} and v != getattr(option, k)}
    if terms:
        _, ledger = load_option_ledger(db, current_user.id)
        row = next(r for r in ledger["options"] if r["option_id"] == option.id)
        txs = db.query(Transaction).filter(Transaction.id.in_(row["matched_transaction_ids"])).all()
        if option.status != OptionStatus.OPEN or option.realized_pnl is not None or len(txs) != 1 or txs[0].option_id != option.id:
            raise HTTPException(409, "Este contrato tiene historial. Usa roll o corrige las transacciones de origen.")
        _validate_terms(db, stock, option.option_type, data.strategy or option.strategy,
                        data.contracts or option.contracts, data.expiration_date or option.expiration_date,
                        data.opened_at or option.opened_at, option.id)
        for key, value in terms.items():
            setattr(option, key, value)
        option.total_premium = round(option.contracts * option.premium_per_contract * 100, 2)
        tx = txs[0]
        tx.quantity, tx.price, tx.total_amount = option.contracts, option.premium_per_contract, option.total_premium
        tx.transaction_date = option.opened_at
        tx.notes = f"Manual correction | Strike ${option.strike_price} | Exp {option.expiration_date.date().isoformat()}"
    if data.notes is not None:
        option.notes = data.notes
    _sync_basis(db, stock, current_user.id)
    db.commit()
    return _response(db, option, current_user)


@router.delete("/{option_id}")
def delete_option(option_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    option, stock = _position(db, option_id, current_user.id)
    _, ledger = load_option_ledger(db, current_user.id)
    row = next(r for r in ledger["options"] if r["option_id"] == option.id)
    txs = db.query(Transaction).filter(Transaction.id.in_(row["matched_transaction_ids"])).all()
    if any(tx.option_id != option.id for tx in txs):
        raise HTTPException(409, "El contrato tiene transacciones importadas; corrige el histórico de origen.")
    # Derived campaigns reference this contract; preserve that history until reconciliation.
    from ..models import CoveredCallCycle
    if db.query(CoveredCallCycle).filter(CoveredCallCycle.option_id == option.id).first():
        raise HTTPException(409, "El contrato pertenece a una campaña. Corrige el histórico antes de eliminarlo.")
    for tx in txs:
        db.delete(tx)
    db.delete(option)
    _sync_basis(db, stock, current_user.id)
    db.commit()
    return {"message": "Option deleted successfully"}


@router.get("/{option_id}", response_model=OptionResponse)
def get_option(option_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    option = db.query(Option).join(Stock).filter(Option.id == option_id, Stock.user_id == current_user.id).first()
    if option is None:
        raise HTTPException(404, "Option not found")
    return _response(db, option, current_user)


class OptionClose(BaseModel):
    closing_premium: float = Field(default=0, ge=0, allow_inf_nan=False)
    contracts_to_close: Optional[int] = Field(default=None, gt=0, strict=True)
    commission: float = Field(default=0, ge=0, allow_inf_nan=False)
    confirm_expired: bool = False


class OptionRoll(BaseModel):
    closing_premium: float = Field(ge=0, allow_inf_nan=False)
    new_strike_price: float = Field(gt=0, allow_inf_nan=False)
    new_expiration_date: datetime
    new_premium_per_contract: float = Field(ge=0, allow_inf_nan=False)
    new_contracts: Optional[int] = Field(default=None, gt=0, strict=True)
    closing_commission: float = Field(default=0, ge=0, allow_inf_nan=False)
    opening_commission: float = Field(default=0, ge=0, allow_inf_nan=False)
    notes: Optional[str] = None


def _close(db, option, user_id, premium, contracts, commission=0, expired=False):
    if option.status != OptionStatus.OPEN:
        raise HTTPException(409, "Option is not open")
    if contracts > option.contracts:
        raise HTTPException(422, "La cantidad supera los contratos abiertos.")
    if expired and (premium != 0 or option.expiration_date.date() >= _today()):
        raise HTTPException(422, "Confirma la expiración sin valor después del vencimiento, con costo cero.")
    closed_premium = round(option.total_premium * contracts / option.contracts, 2)
    partial_pnl = round(closed_premium - premium * contracts * 100, 2)
    option.realized_pnl = round((option.realized_pnl or 0) + partial_pnl, 2)
    if contracts < option.contracts:
        option.contracts -= contracts
        option.total_premium = round(option.total_premium - closed_premium, 2)
    else:
        option.status = OptionStatus.EXPIRED if expired else OptionStatus.CLOSED
        option.closing_premium = premium
        option.closed_at = datetime.now(timezone.utc)
    # Zero-cost closes still identify which contracts were settled in the ledger.
    _transaction(db, option, user_id, opening=False, premium=premium, contracts=contracts,
                 commission=commission, note="Confirmed expiry" if expired else "Buy to close")
    return partial_pnl


@router.post("/{option_id}/roll", response_model=OptionResponse)
def roll_option(option_id: int, roll_data: OptionRoll, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    option, stock = _position(db, option_id, current_user.id)
    if option.status != OptionStatus.OPEN:
        raise HTTPException(409, "Option is not open")
    if option.expiration_date.date() < _today():
        raise HTTPException(409, "Confirma primero la liquidación del contrato vencido.")
    now = datetime.now(timezone.utc)
    contracts = roll_data.new_contracts if roll_data.new_contracts is not None else option.contracts
    _validate_terms(db, stock, option.option_type, option.strategy, contracts, roll_data.new_expiration_date, now, option.id)
    if roll_data.new_expiration_date.date() <= _today():
        raise HTTPException(422, "El nuevo vencimiento debe ser futuro.")
    _close(db, option, current_user.id, roll_data.closing_premium, option.contracts, roll_data.closing_commission)
    new = Option(stock_id=stock.id, ticker=stock.ticker, option_type=option.option_type, strategy=option.strategy,
                 strike_price=roll_data.new_strike_price, contracts=contracts,
                 premium_per_contract=roll_data.new_premium_per_contract,
                 total_premium=round(contracts * 100 * roll_data.new_premium_per_contract, 2),
                 expiration_date=roll_data.new_expiration_date, opened_at=now,
                 notes=roll_data.notes or f"Rolled from #{option.id}")
    option.notes = f"{option.notes or ''} | Rolled to new contract"
    db.add(new)
    db.flush()
    _transaction(db, new, current_user.id, opening=True, premium=roll_data.new_premium_per_contract,
                 contracts=contracts, commission=roll_data.opening_commission, at=now, note=f"Roll from #{option.id}")
    _sync_basis(db, stock, current_user.id)
    db.commit()
    return _response(db, new, current_user)


@router.post("/{option_id}/close")
def close_option(option_id: int, close_data: OptionClose, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    option, stock = _position(db, option_id, current_user.id)
    contracts = close_data.contracts_to_close if close_data.contracts_to_close is not None else option.contracts
    partial = _close(db, option, current_user.id, close_data.closing_premium, contracts, close_data.commission, close_data.confirm_expired)
    _sync_basis(db, stock, current_user.id)
    db.commit()
    return {"message": "Option closed successfully", "realized_pnl": option.realized_pnl, "closing_realized_pnl": partial}
