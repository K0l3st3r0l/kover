from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from ..database import Base

class OptionType(str, enum.Enum):
    CALL = "CALL"
    PUT = "PUT"

class OptionStrategy(str, enum.Enum):
    COVERED_CALL = "COVERED_CALL"
    CASH_SECURED_PUT = "CASH_SECURED_PUT"

class OptionStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    ASSIGNED = "ASSIGNED"

class Option(Base):
    __tablename__ = "options"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    ticker = Column(String, index=True, nullable=False)
    option_type = Column(Enum(OptionType), nullable=False)
    strategy = Column(Enum(OptionStrategy), nullable=False)
    strike_price = Column(Float, nullable=False)
    contracts = Column(Integer, nullable=False)  # 1 contrato = 100 acciones
    premium_per_contract = Column(Float, nullable=False)  # Premium por contrato
    total_premium = Column(Float, nullable=False)  # Premium total (contracts * 100 * premium)
    expiration_date = Column(DateTime(timezone=True), nullable=False)
    status = Column(Enum(OptionStatus), default=OptionStatus.OPEN)
    
    # Fechas
    opened_at = Column(DateTime(timezone=True), nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    
    # P&L
    closing_premium = Column(Float, nullable=True)  # Si se compra para cerrar
    realized_pnl = Column(Float, nullable=True)  # Ganancia/pérdida realizada
    
    # Notas
    notes = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship
    stock = relationship("Stock", backref="options")

    def __repr__(self):
        return f"<Option {self.ticker} {self.strike_price} {self.option_type} exp:{self.expiration_date}>"
