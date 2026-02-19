from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum
from sqlalchemy.sql import func
import enum
from ..database import Base

class TransactionType(str, enum.Enum):
    BUY_STOCK = "BUY_STOCK"
    SELL_STOCK = "SELL_STOCK"
    SELL_CALL = "SELL_CALL"
    BUY_CALL = "BUY_CALL"  # Para cerrar posición
    SELL_PUT = "SELL_PUT"
    BUY_PUT = "BUY_PUT"  # Para cerrar posición
    ASSIGNMENT = "ASSIGNMENT"  # Cuando te asignan
    DIVIDEND = "DIVIDEND"

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=True)
    option_id = Column(Integer, ForeignKey("options.id"), nullable=True)
    ticker = Column(String, index=True, nullable=False)
    transaction_type = Column(Enum(TransactionType), nullable=False)
    quantity = Column(Float, nullable=False)  # Acciones o contratos
    price = Column(Float, nullable=False)
    total_amount = Column(Float, nullable=False)  # Cantidad total de la transacción
    commission = Column(Float, default=0)
    notes = Column(String, nullable=True)
    transaction_date = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Transaction {self.transaction_type} {self.ticker} {self.quantity}>"
