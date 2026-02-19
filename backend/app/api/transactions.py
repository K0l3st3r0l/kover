from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from datetime import datetime, date
from ..database import get_db
from ..models import Transaction, TransactionType, User
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
        "total_invested": 0,
        "total_received": 0,
        "total_commissions": 0,
        "by_type": {}
    }
    
    for transaction in transactions:
        # Contar por tipo
        type_str = transaction.transaction_type.value
        if type_str not in summary["by_type"]:
            summary["by_type"][type_str] = {
                "count": 0,
                "total_amount": 0
            }
        
        summary["by_type"][type_str]["count"] += 1
        summary["by_type"][type_str]["total_amount"] += abs(transaction.total_amount)
        
        # Calcular totales
        summary["total_commissions"] += transaction.commission
        
        # Dinero gastado vs recibido
        if transaction.transaction_type in [TransactionType.BUY_STOCK, TransactionType.BUY_CALL, TransactionType.BUY_PUT]:
            summary["total_invested"] += abs(transaction.total_amount)
        elif transaction.transaction_type in [TransactionType.SELL_STOCK, TransactionType.SELL_CALL, TransactionType.SELL_PUT, TransactionType.DIVIDEND]:
            summary["total_received"] += abs(transaction.total_amount)
    
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
