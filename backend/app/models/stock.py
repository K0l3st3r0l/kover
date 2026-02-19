from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from ..database import Base

class Stock(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    ticker = Column(String, index=True, nullable=False)
    company_name = Column(String, nullable=False)
    shares = Column(Float, nullable=False, default=0)
    average_cost = Column(Float, nullable=False)  # Precio medio ponderado
    total_invested = Column(Float, nullable=False)  # Total invertido
    total_premium_earned = Column(Float, default=0)  # Total de premiums ganados
    adjusted_cost_basis = Column(Float, nullable=False)  # Costo ajustado por premiums
    is_active = Column(Boolean, default=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<Stock {self.ticker}: {self.shares} shares @ ${self.average_cost}>"
