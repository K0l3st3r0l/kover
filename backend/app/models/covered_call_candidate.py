"""Resultado del scanner de covered calls (K4).

Guarda los tres mejores contratos por símbolo, no la cadena. Ver el comentario
de migrations/013_covered_call_candidates.sql para el porqué.
"""

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.sql import func

from ..database import Base
from .infra import JSONVariant

PICK_BALANCED = "BALANCED"
PICK_PREMIUM = "PREMIUM"
PICK_UPSIDE = "UPSIDE"


class CoveredCallCandidate(Base):
    __tablename__ = "covered_call_candidates"

    id = Column(Integer, primary_key=True, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    pick_type = Column(String(16), nullable=False)
    scanned_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    quote_as_of = Column(DateTime(timezone=True))

    underlying_price = Column(Numeric(18, 6))
    stock_ask = Column(Numeric(18, 6))

    occ_symbol = Column(String(32), nullable=False)
    expiration = Column(Date, nullable=False)
    strike = Column(Numeric(18, 6), nullable=False)
    dte = Column(Integer, nullable=False)

    call_bid = Column(Numeric(18, 6))
    call_ask = Column(Numeric(18, 6))
    spread_pct = Column(Numeric(10, 6))
    delta = Column(Numeric(10, 6))
    implied_volatility = Column(Numeric(10, 6))
    volume = Column(Integer)
    open_interest = Column(Integer)

    premium_total = Column(Numeric(18, 2))
    premium_yield = Column(Numeric(12, 6))
    annualized_premium_yield = Column(Numeric(12, 6))
    return_if_assigned = Column(Numeric(12, 6))
    annualized_return_if_assigned = Column(Numeric(12, 6))
    downside_protection = Column(Numeric(12, 6))
    breakeven = Column(Numeric(18, 6))
    moneyness = Column(Numeric(12, 6))

    liquidity_score = Column(Numeric(6, 2))
    liquidity_components = Column(JSONVariant)

    financial_safety_score = Column(Numeric(6, 2))
    market_safety_score = Column(Numeric(6, 2))

    def __repr__(self):
        return f"<CoveredCallCandidate {self.occ_symbol} {self.pick_type}>"
