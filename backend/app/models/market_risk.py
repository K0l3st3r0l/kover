"""Barras diarias y riesgo de mercado — Stage 3 del scanner.

`stock_daily_bars` es la fuente cruda; `market_risk_snapshots` es el
resultado calculado. A diferencia de `fundamental_snapshots`, esto sí se
recalcula libremente día a día: no hay problema de look-ahead porque el
backtest de mercado usará las barras crudas con su propia fecha, no el
snapshot vigente.
"""

from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.sql import func

from ..database import Base
from .infra import JSONVariant


class StockDailyBar(Base):
    __tablename__ = "stock_daily_bars"

    id = Column(Integer, primary_key=True, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    bar_date = Column(Date, nullable=False)
    open = Column(Numeric(18, 6), nullable=True)
    high = Column(Numeric(18, 6), nullable=True)
    low = Column(Numeric(18, 6), nullable=True)
    close = Column(Numeric(18, 6), nullable=True)
    volume = Column(BigInteger, nullable=True)
    source = Column(String(32), nullable=False)

    def __repr__(self):
        return f"<StockDailyBar {self.instrument_id} {self.bar_date} close={self.close}>"


class MarketRiskSnapshot(Base):
    __tablename__ = "market_risk_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    as_of_date = Column(Date, nullable=False)

    price = Column(Numeric(18, 6), nullable=True)
    avg_daily_volume_20 = Column(BigInteger, nullable=True)
    avg_dollar_volume_20 = Column(Numeric(24, 2), nullable=True)
    atr14 = Column(Numeric(18, 6), nullable=True)
    atr_pct = Column(Numeric(10, 6), nullable=True)
    realized_vol_20 = Column(Numeric(10, 6), nullable=True)
    realized_vol_60 = Column(Numeric(10, 6), nullable=True)
    return_5d = Column(Numeric(10, 6), nullable=True)
    return_20d = Column(Numeric(10, 6), nullable=True)
    max_drawdown_30d = Column(Numeric(10, 6), nullable=True)
    max_drawdown_90d = Column(Numeric(10, 6), nullable=True)
    gap_frequency = Column(Numeric(10, 6), nullable=True)
    worst_day_20d = Column(Numeric(10, 6), nullable=True)
    market_safety_score = Column(Numeric(6, 2), nullable=True)
    components = Column(JSONVariant, nullable=True)
    bars_used = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<MarketRiskSnapshot {self.instrument_id} {self.as_of_date} score={self.market_safety_score}>"
