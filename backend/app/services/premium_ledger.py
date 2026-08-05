"""Única puerta de entrada al ledger canónico de primas.

Antes convivían tres fuentes con tres totales distintos: `Stock.total_premium_earned`,
la suma de las filas `options` y el neto de las transacciones. Todo endpoint que
muestre primas debe pasar por aquí.
"""

from sqlalchemy.orm import Session

from ..models import Option, Stock, Transaction, TransactionType
from ..utils.portfolio_metrics import build_option_transaction_ledger, premium_by_ticker

OPTION_TRANSACTION_TYPES = (
    TransactionType.SELL_CALL,
    TransactionType.BUY_CALL,
    TransactionType.SELL_PUT,
    TransactionType.BUY_PUT,
)


def load_option_ledger(
    db: Session,
    user_id: int,
    transactions: list[Transaction] | None = None,
) -> tuple[list[Option], dict]:
    """Return (options, ledger). Pass `transactions` to reuse a query already made."""
    options = (
        db.query(Option)
        .join(Stock)
        .filter(Stock.user_id == user_id)
        .order_by(Option.opened_at.asc())
        .all()
    )
    if transactions is None:
        option_transactions = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.transaction_type.in_(OPTION_TRANSACTION_TYPES),
            )
            .order_by(Transaction.transaction_date, Transaction.id)
            .all()
        )
    else:
        option_transactions = [
            tx for tx in transactions if tx.transaction_type in OPTION_TRANSACTION_TYPES
        ]
    return options, build_option_transaction_ledger(options, option_transactions)


def load_premium_by_ticker(
    db: Session,
    user_id: int,
    transactions: list[Transaction] | None = None,
) -> dict[str, dict[str, float]]:
    _, ledger = load_option_ledger(db, user_id, transactions)
    return premium_by_ticker(ledger)
