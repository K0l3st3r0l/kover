from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from datetime import datetime, date
from ..database import get_db
from ..models import Transaction, TransactionType, Stock, User
from ..utils.auth import get_current_user

router = APIRouter()

@router.get("/")
async def get_transactions(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    ticker: Optional[str] = None,
    transaction_type: Optional[TransactionType] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtener el historial de transacciones con filtros opcionales
    """
    query = db.query(Transaction).filter(Transaction.user_id == current_user.id)
    
    # Aplicar filtros
    if ticker:
        query = query.filter(Transaction.ticker == ticker.upper())
    
    if transaction_type:
        query = query.filter(Transaction.transaction_type == transaction_type)
    
    if start_date:
        query = query.filter(Transaction.transaction_date >= start_date)
    
    if end_date:
        # Agregar 1 día para incluir todo el día final
        query = query.filter(Transaction.transaction_date < datetime.combine(end_date, datetime.max.time()))
    
    # Ordenar por fecha descendente (más recientes primero)
    transactions = query.order_by(desc(Transaction.transaction_date)).offset(skip).limit(limit).all()
    
    # Obtener el total para paginación
    total = query.count()
    
    return {
        "transactions": transactions,
        "total": total,
        "skip": skip,
        "limit": limit
    }

@router.get("/summary")
async def get_transaction_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtener resumen de transacciones
    """
    transactions = db.query(Transaction).filter(Transaction.user_id == current_user.id).all()

    summary = {
        "total_transactions": len(transactions),
        # Flujos históricos de acciones
        "stock_buys": 0,        # Total pagado en compras de acciones
        "stock_sells": 0,       # Total recibido en ventas de acciones
        # Opciones
        "premium_collected": 0, # Primas cobradas (SELL_CALL/SELL_PUT)
        "premium_paid": 0,      # Primas pagadas para cerrar (BUY_CALL/BUY_PUT)
        # Otros
        "dividends": 0,
        "total_commissions": 0,
        "by_type": {}
    }

    for transaction in transactions:
        tt = transaction.transaction_type
        type_str = tt.value
        amount = abs(transaction.total_amount)

        if type_str not in summary["by_type"]:
            summary["by_type"][type_str] = {"count": 0, "total_amount": 0}
        summary["by_type"][type_str]["count"] += 1
        summary["by_type"][type_str]["total_amount"] += amount

        summary["total_commissions"] += transaction.commission

        if tt == TransactionType.BUY_STOCK:
            summary["stock_buys"] += amount
        elif tt == TransactionType.SELL_STOCK:
            summary["stock_sells"] += amount
        elif tt in (TransactionType.SELL_CALL, TransactionType.SELL_PUT):
            summary["premium_collected"] += amount
        elif tt in (TransactionType.BUY_CALL, TransactionType.BUY_PUT):
            summary["premium_paid"] += amount
        elif tt == TransactionType.DIVIDEND:
            summary["dividends"] += amount

    # Capital activo actual (igual que el dashboard)
    active_stocks = db.query(Stock).filter(
        Stock.user_id == current_user.id,
        Stock.is_active == True
    ).all()
    summary["current_invested"] = round(sum(s.total_invested for s in active_stocks), 2)
    summary["net_premium"] = round(summary["premium_collected"] - summary["premium_paid"], 2)

    # Redondear
    for key in ("stock_buys", "stock_sells", "premium_collected", "premium_paid",
                "dividends", "total_commissions"):
        summary[key] = round(summary[key], 2)

    # Compat con versiones anteriores
    summary["total_invested"] = summary["stock_buys"]
    summary["total_received"] = round(
        summary["stock_sells"] + summary["premium_collected"] + summary["dividends"], 2
    )

    return summary

@router.get("/{transaction_id}")
async def get_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtener detalles de una transacción específica
    """
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id,
        Transaction.user_id == current_user.id
    ).first()
    
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    return transaction
