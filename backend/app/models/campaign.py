import enum

from sqlalchemy import Column, DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base
from .infra import JSONVariant


class CampaignStatus(str, enum.Enum):
    """Estados de la vida de un bloque de acciones.

    STOCK_AVAILABLE es el estado "listo para vender otra call": es donde vuelve la
    campaña tras un take profit o una expiración OTM, y donde el scanner debería
    proponer el siguiente contrato.
    """

    STOCK_ACQUIRED = "STOCK_ACQUIRED"
    STOCK_AVAILABLE = "STOCK_AVAILABLE"
    CALL_OPEN = "CALL_OPEN"
    CLOSED = "CLOSED"


class CampaignCloseReason(str, enum.Enum):
    ASSIGNED = "ASSIGNED"
    STOCK_SALE = "STOCK_SALE"
    MANUAL = "MANUAL"


class CycleStatus(str, enum.Enum):
    OPEN = "OPEN"
    TP_ELIGIBLE = "TP_ELIGIBLE"
    CLOSED_TP = "CLOSED_TP"
    CLOSED_MANUAL = "CLOSED_MANUAL"
    EXPIRED_OTM = "EXPIRED_OTM"
    ASSIGNED = "ASSIGNED"
    ROLLED = "ROLLED"


# Los Enum de Python se guardan como VARCHAR (no como tipo enum de Postgres):
# la migración declara VARCHAR y agregar un estado nuevo no debe requerir un
# ALTER TYPE, porque estas tablas se regeneran enteras en cada rebuild.
_STR_ENUM = dict(native_enum=False, length=32)


class Campaign(Base):
    """Vida completa de un bloque de acciones, con todas sus calls adentro.

    Tabla derivada: `campaigns/builder.py` la reconstruye desde transactions.
    Nada escribe aquí fuera del builder.
    """

    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ticker = Column(String(16), nullable=False, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=True)

    status = Column(Enum(CampaignStatus, **_STR_ENUM), nullable=False)
    shares = Column(Float, nullable=False, default=0)
    shares_peak = Column(Float, nullable=False, default=0)
    # NULL = desconocido. Nunca 0 como sustituto: un costo base de cero convierte
    # una venta cualquiera en ganancia total.
    stock_cost_basis = Column(Float, nullable=True)
    stock_invested = Column(Float, nullable=True)
    cost_basis_status = Column(String(32), nullable=False, default="KNOWN")

    opened_at = Column(DateTime(timezone=True), nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    close_reason = Column(Enum(CampaignCloseReason, **_STR_ENUM), nullable=True)

    stock_realized_pnl = Column(Float, nullable=True)
    option_realized_pnl = Column(Float, nullable=True)
    option_open_premium = Column(Float, nullable=True)
    dividends_total = Column(Float, nullable=True)
    commissions_total = Column(Float, nullable=True)
    total_pnl = Column(Float, nullable=True)
    days_deployed = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    cycles = relationship(
        "CoveredCallCycle",
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="CoveredCallCycle.cycle_num",
    )
    events = relationship(
        "CampaignEvent", back_populates="campaign", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Campaign {self.ticker} {self.shares} sh [{self.status}]>"


class CoveredCallCycle(Base):
    """Una call individual vendida contra las acciones de una campaña."""

    __tablename__ = "covered_call_cycles"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    option_id = Column(Integer, ForeignKey("options.id"), nullable=True)
    cycle_num = Column(Integer, nullable=False)
    status = Column(Enum(CycleStatus, **_STR_ENUM), nullable=False)

    ticker = Column(String(16), nullable=False)
    strike = Column(Float, nullable=False)
    contracts = Column(Float, nullable=False)
    expiration = Column(DateTime(timezone=True), nullable=False)
    opened_at = Column(DateTime(timezone=True), nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    entry_premium = Column(Float, nullable=False)
    exit_premium = Column(Float, nullable=True)
    gross_premium = Column(Float, nullable=True)
    closing_cost = Column(Float, nullable=True)
    commissions = Column(Float, default=0)
    realized_pnl = Column(Float, nullable=True)
    open_premium = Column(Float, nullable=True)

    min_tick = Column(Float, default=0.01)
    tp70_price = Column(Float, nullable=True)
    tp75_price = Column(Float, nullable=True)
    tp80_price = Column(Float, nullable=True)

    premium_source = Column(String(32), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    campaign = relationship("Campaign", back_populates="cycles")

    def __repr__(self):
        return f"<Cycle {self.ticker} ${self.strike} [{self.status}]>"


class CampaignEvent(Base):
    __tablename__ = "campaign_events"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    cycle_id = Column(Integer, ForeignKey("covered_call_cycles.id", ondelete="CASCADE"), nullable=True)
    event_type = Column(String(48), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    payload = Column(JSONVariant, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    campaign = relationship("Campaign", back_populates="events")
