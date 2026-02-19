from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta
from ..database import get_db
from ..models import Option, Stock, OptionType, OptionStrategy, OptionStatus, Transaction, TransactionType
from ..models.user import User
from ..utils.auth import get_current_user
from ..utils import OptionsCalculator

router = APIRouter()

# Schemas
class OptionCreate(BaseModel):
    stock_id: int
    option_type: OptionType
    strategy: OptionStrategy
    strike_price: float
    contracts: int
    premium_per_contract: float
    expiration_date: datetime
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
    premium_yield: Optional[float] = None
    annualized_return: Optional[float] = None

    class Config:
        from_attributes = True


def _enrich_response(response: OptionResponse, option) -> None:
    """Calcula y agrega métricas derivadas al response: días, yield y retorno anualizado."""
    from datetime import timezone as _tz
    response.days_to_expiration = OptionsCalculator.calculate_days_to_expiration(option.expiration_date)
    capital = option.strike_price * option.contracts * 100
    if capital > 0:
        response.premium_yield = round((option.total_premium / capital) * 100, 2)
        # Duración total del contrato en días calendario (fecha a fecha, sin horas)
        exp_date = option.expiration_date.date() if hasattr(option.expiration_date, 'date') else option.expiration_date
        opened_date = option.opened_at.date() if hasattr(option.opened_at, 'date') else option.opened_at
        total_days = (exp_date - opened_date).days
        if total_days > 0:
            response.annualized_return = round(response.premium_yield * (365 / total_days), 2)

@router.post("/", response_model=OptionResponse)
def create_option(
    option: OptionCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Crear una nueva posición de opción"""
    
    # Verificar que el stock existe y pertenece al usuario
    stock = db.query(Stock).filter(
        Stock.id == option.stock_id,
        Stock.user_id == current_user.id
    ).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    
    # Calcular el premium total
    total_premium = option.contracts * 100 * option.premium_per_contract
    
    # Crear la opción
    new_option = Option(
        stock_id=option.stock_id,
        ticker=stock.ticker,
        option_type=option.option_type,
        strategy=option.strategy,
        strike_price=option.strike_price,
        contracts=option.contracts,
        premium_per_contract=option.premium_per_contract,
        total_premium=total_premium,
        expiration_date=option.expiration_date,
        opened_at=option.opened_at or datetime.now(),
        notes=option.notes
    )
    
    db.add(new_option)
    db.flush()
    
    # Actualizar el stock con el premium ganado
    stock.total_premium_earned += total_premium
    
    # Ajustar el costo base
    stock.adjusted_cost_basis = OptionsCalculator.adjust_cost_basis(
        stock.adjusted_cost_basis,
        total_premium,
        stock.shares
    )
    
    # Registrar la transacción
    transaction_type = None
    if option.strategy == OptionStrategy.COVERED_CALL:
        transaction_type = TransactionType.SELL_CALL
    elif option.strategy == OptionStrategy.CASH_SECURED_PUT:
        transaction_type = TransactionType.SELL_PUT
    
    transaction = Transaction(
        user_id=current_user.id,
        stock_id=stock.id,
        option_id=new_option.id,
        ticker=stock.ticker,
        transaction_type=transaction_type,
        quantity=option.contracts,
        price=option.premium_per_contract,
        total_amount=total_premium,
        transaction_date=datetime.now()
    )
    
    db.add(transaction)
    db.commit()
    db.refresh(new_option)
    
    # Agregar campos calculados
    response = OptionResponse.from_orm(new_option)
    _enrich_response(response, new_option)
    
    return response

@router.get("/", response_model=List[OptionResponse])
def get_options(
    status: OptionStatus = None, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtener todas las opciones"""
    # Filtrar por opciones del usuario a través de la relación con stocks
    query = db.query(Option).join(Stock).filter(Stock.user_id == current_user.id)
    if status:
        query = query.filter(Option.status == status)
    
    options = query.order_by(Option.expiration_date.desc()).all()
    
    results = []
    for opt in options:
        response = OptionResponse.from_orm(opt)
        _enrich_response(response, opt)
        results.append(response)
    
    return results

@router.get("/expiring-soon", response_model=List[OptionResponse])
def get_expiring_soon_options(
    days: int = 7,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtener opciones que expiran pronto (por defecto en 7 días o menos)"""
    cutoff_date = datetime.now() + timedelta(days=days)
    
    options = db.query(Option).join(Stock).filter(
        Stock.user_id == current_user.id,
        Option.status == OptionStatus.OPEN,
        Option.expiration_date <= cutoff_date,
        Option.expiration_date >= datetime.now()
    ).order_by(Option.expiration_date).all()
    
    # Enriquecer con días hasta expiración
    result = []
    for option in options:
        response = OptionResponse.from_orm(option)
        _enrich_response(response, option)
        result.append(response)
    
    return result

class OptionUpdate(BaseModel):
    strike_price: Optional[float] = None
    contracts: Optional[int] = None
    premium_per_contract: Optional[float] = None
    expiration_date: Optional[datetime] = None
    strategy: Optional[OptionStrategy] = None
    status: Optional[OptionStatus] = None
    notes: Optional[str] = None
    realized_pnl: Optional[float] = None
    opened_at: Optional[datetime] = None

@router.put("/{option_id}", response_model=OptionResponse)
def update_option(
    option_id: int,
    data: OptionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Modificar una opción existente"""
    option = db.query(Option).join(Stock).filter(
        Option.id == option_id,
        Stock.user_id == current_user.id
    ).first()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")

    stock = db.query(Stock).filter(Stock.id == option.stock_id).first()

    # Recalcular premium si cambian contratos o prima
    new_contracts = data.contracts if data.contracts is not None else option.contracts
    new_ppc = data.premium_per_contract if data.premium_per_contract is not None else option.premium_per_contract
    new_total_premium = new_contracts * 100 * new_ppc

    # Delta de premium → ajusta el stock
    premium_delta = new_total_premium - option.total_premium
    if premium_delta != 0:
        stock.total_premium_earned = max(0, stock.total_premium_earned + premium_delta)
        if stock.shares > 0:
            stock.adjusted_cost_basis = round(
                stock.average_cost - (stock.total_premium_earned / stock.shares), 2
            )
        # Actualizar también la transacción SELL original de esta opción
        sell_type = TransactionType.SELL_CALL if option.option_type == OptionType.CALL else TransactionType.SELL_PUT
        orig_tx = db.query(Transaction).filter(
            Transaction.option_id == option.id,
            Transaction.transaction_type == sell_type
        ).first()
        if orig_tx:
            orig_tx.quantity = new_contracts
            orig_tx.price = new_ppc
            orig_tx.total_amount = new_total_premium

    # Aplicar cambios
    if data.strike_price is not None:     option.strike_price = data.strike_price
    if data.contracts is not None:        option.contracts = data.contracts
    if data.premium_per_contract is not None:
        option.premium_per_contract = data.premium_per_contract
    option.total_premium = new_total_premium
    if data.expiration_date is not None:  option.expiration_date = data.expiration_date
    if data.strategy is not None:         option.strategy = data.strategy
    if data.notes is not None:            option.notes = data.notes
    if data.realized_pnl is not None:     option.realized_pnl = data.realized_pnl
    if data.opened_at is not None:        option.opened_at = data.opened_at

    # Cambio de estado
    if data.status is not None and data.status != option.status:
        option.status = data.status
        if data.status == OptionStatus.OPEN:
            option.closed_at = None
            option.closing_premium = None
            if data.realized_pnl is None:
                option.realized_pnl = None
        elif option.closed_at is None:
            option.closed_at = datetime.now()

    db.commit()
    db.refresh(option)

    response = OptionResponse.from_orm(option)
    _enrich_response(response, option)
    return response


@router.delete("/{option_id}")
def delete_option(
    option_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Eliminar una opción y revertir su impacto en el stock"""
    option = db.query(Option).join(Stock).filter(
        Option.id == option_id,
        Stock.user_id == current_user.id
    ).first()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")

    stock = db.query(Stock).filter(Stock.id == option.stock_id).first()

    # Revertir el impacto de la prima original sobre el stock
    # (total_premium fue sumado al crear; el cierre/roll no lo resta del stock)
    stock.total_premium_earned = max(0, stock.total_premium_earned - option.total_premium)
    if stock.shares > 0:
        stock.adjusted_cost_basis = round(
            stock.average_cost - (stock.total_premium_earned / stock.shares), 2
        )

    # Eliminar transacciones vinculadas
    db.query(Transaction).filter(Transaction.option_id == option.id).delete()

    # Eliminar la opción
    db.delete(option)
    db.commit()

    return {"message": "Option deleted successfully"}


@router.get("/{option_id}", response_model=OptionResponse)
def get_option(
    option_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtener una opción específica"""
    option = db.query(Option).join(Stock).filter(
        Option.id == option_id,
        Stock.user_id == current_user.id
    ).first()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")
    
    response = OptionResponse.from_orm(option)
    _enrich_response(response, option)
    
    return response

class OptionClose(BaseModel):
    closing_premium: float = 0  # Si es 0, expiró sin valor

class OptionRoll(BaseModel):
    closing_premium: float          # costo por contrato para recomprar la opción actual
    new_strike_price: float
    new_expiration_date: datetime
    new_premium_per_contract: float
    new_contracts: Optional[int] = None   # si None, usa el mismo número de contratos
    notes: Optional[str] = None

@router.post("/{option_id}/roll", response_model=OptionResponse)
def roll_option(
    option_id: int,
    roll_data: OptionRoll,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Hacer roll de una opción: cierra la actual y abre una nueva con distinto strike/expiración"""
    option = db.query(Option).join(Stock).filter(
        Option.id == option_id,
        Stock.user_id == current_user.id
    ).first()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")
    if option.status != OptionStatus.OPEN:
        raise HTTPException(status_code=400, detail="Option is not open")

    stock = db.query(Stock).filter(Stock.id == option.stock_id).first()
    new_contracts = roll_data.new_contracts or option.contracts

    # 1. Cerrar la opción original
    total_closing_cost = roll_data.closing_premium * option.contracts * 100
    realized_pnl = option.total_premium - total_closing_cost

    option.closing_premium = roll_data.closing_premium
    option.realized_pnl = realized_pnl
    option.closed_at = datetime.now()
    option.status = OptionStatus.CLOSED

    # 2. Transacción buy-to-close
    close_tx_type = TransactionType.BUY_CALL if option.option_type == OptionType.CALL else TransactionType.BUY_PUT
    db.add(Transaction(
        user_id=current_user.id,
        stock_id=option.stock_id,
        option_id=option.id,
        ticker=option.ticker,
        transaction_type=close_tx_type,
        quantity=option.contracts,
        price=roll_data.closing_premium,
        total_amount=total_closing_cost,
        notes=f"Roll out: buy to close #{option.id}",
        transaction_date=datetime.now()
    ))

    # 3. Crear nueva opción rodada
    new_total_premium = new_contracts * 100 * roll_data.new_premium_per_contract
    new_option = Option(
        stock_id=option.stock_id,
        ticker=option.ticker,
        option_type=option.option_type,
        strategy=option.strategy,
        strike_price=roll_data.new_strike_price,
        contracts=new_contracts,
        premium_per_contract=roll_data.new_premium_per_contract,
        total_premium=new_total_premium,
        expiration_date=roll_data.new_expiration_date,
        opened_at=datetime.now(),
        notes=roll_data.notes or f"Rolled from #{option.id} (${option.strike_price} exp {option.expiration_date.strftime('%Y-%m-%d')})"
    )
    db.add(new_option)
    db.flush()

    # 4. Transacción sell-to-open (nueva pata)
    open_tx_type = TransactionType.SELL_CALL if option.option_type == OptionType.CALL else TransactionType.SELL_PUT
    db.add(Transaction(
        user_id=current_user.id,
        stock_id=option.stock_id,
        option_id=new_option.id,
        ticker=option.ticker,
        transaction_type=open_tx_type,
        quantity=new_contracts,
        price=roll_data.new_premium_per_contract,
        total_amount=new_total_premium,
        notes=f"Roll in: sell to open (rolled from #{option.id})",
        transaction_date=datetime.now()
    ))

    # 5. Actualizar stock con el neto del roll
    net_premium = new_total_premium - total_closing_cost
    stock.total_premium_earned += net_premium
    if stock.shares > 0:
        stock.adjusted_cost_basis = round(
            stock.average_cost - (stock.total_premium_earned / stock.shares), 2
        )

    db.commit()
    db.refresh(new_option)

    response = OptionResponse.from_orm(new_option)
    _enrich_response(response, new_option)
    return response

@router.post("/{option_id}/close")
def close_option(
    option_id: int, 
    close_data: OptionClose, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cerrar una opción"""
    option = db.query(Option).join(Stock).filter(
        Option.id == option_id,
        Stock.user_id == current_user.id
    ).first()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")
    
    if option.status != OptionStatus.OPEN:
        raise HTTPException(status_code=400, detail="Option is not open")
    
    # Calcular P&L
    total_closing_cost = close_data.closing_premium * option.contracts * 100
    realized_pnl = option.total_premium - total_closing_cost
    
    option.closing_premium = close_data.closing_premium
    option.realized_pnl = realized_pnl
    option.closed_at = datetime.now()
    option.status = OptionStatus.CLOSED if close_data.closing_premium > 0 else OptionStatus.EXPIRED
    
    # Registrar transacción si se compró para cerrar
    if close_data.closing_premium > 0:
        transaction_type = TransactionType.BUY_CALL if option.option_type == OptionType.CALL else TransactionType.BUY_PUT
        
        transaction = Transaction(
            stock_id=option.stock_id,
            option_id=option.id,
            ticker=option.ticker,
            transaction_type=transaction_type,
            quantity=option.contracts,
            price=close_data.closing_premium,
            total_amount=total_closing_cost,
            transaction_date=datetime.now()
        )
        db.add(transaction)
    
    db.commit()
    
    return {"message": "Option closed successfully", "realized_pnl": realized_pnl}
