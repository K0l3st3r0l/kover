"""Saldo de caja derivado de las transacciones.

Antes `users.cash_balance` era un número escrito a mano por el usuario. Ahora sale
de sumar los flujos, con una salvedad: el historial no tiene los depósitos anteriores
a la primera importación, así que sumar todo desde cero da un saldo falso. El ancla
(`cash_opening_balance` a `cash_opening_date`) fija el punto de partida y solo se
suman los movimientos posteriores.

Sin ancla configurada se suma el historial completo, que es lo correcto únicamente
si las cuentas arrancaron en cero dentro de Kover.
"""

from sqlalchemy.orm import Session

from ..models import Transaction, TransactionType, User

# `total_amount` se guarda siempre positivo: el tipo decide la dirección.
CASH_IN = (
    TransactionType.SELL_STOCK,
    TransactionType.SELL_CALL,
    TransactionType.SELL_PUT,
    TransactionType.DIVIDEND,
    TransactionType.DEPOSIT,
)
CASH_OUT = (
    TransactionType.BUY_STOCK,
    TransactionType.BUY_CALL,
    TransactionType.BUY_PUT,
    TransactionType.WITHDRAWAL,
    TransactionType.FEE,
    TransactionType.WITHHOLDING_TAX,
)
# ASSIGNMENT y OPTION_EXPIRY quedan fuera a propósito: el efectivo de una asignación
# ya entra por las patas SELL_STOCK/BUY_CALL, y una expiración no mueve caja.


def compute_cash_balance(db: Session, user: User) -> dict:
    """Saldo de caja y su desglose. No escribe nada."""
    query = db.query(Transaction).filter(Transaction.user_id == user.id)

    opening_date = user.cash_opening_date
    if opening_date is not None:
        query = query.filter(Transaction.transaction_date >= opening_date)

    transactions = query.all()

    entradas = sum(
        abs(t.total_amount or 0.0) for t in transactions if t.transaction_type in CASH_IN
    )
    # Sin abs(): un fee o una retención que IB revierte se guarda negativo y así
    # vuelve a sumar caja. Las demás salidas son positivas por convención.
    salidas = sum(
        (t.total_amount or 0.0) for t in transactions if t.transaction_type in CASH_OUT
    )
    # Con signo: IB devuelve comisión en algunas recompras y esas filas quedan negativas.
    comisiones = sum(t.commission or 0.0 for t in transactions)

    opening = user.cash_opening_balance or 0.0
    balance = opening + entradas - salidas - comisiones

    return {
        "cash_balance": round(balance, 2),
        "opening_balance": round(opening, 2),
        "opening_date": opening_date.isoformat() if opening_date else None,
        "inflows": round(entradas, 2),
        "outflows": round(salidas, 2),
        "commissions": round(comisiones, 2),
        "transactions_counted": len(transactions),
        "is_derived": True,
    }
