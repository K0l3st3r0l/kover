from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from ..database import Base


class Instrument(Base):
    """Identidad canónica de un subyacente.

    `stocks` es la posición del usuario; `instruments` es el papel en sí, y existe
    aunque nadie lo tenga en cartera. El scanner necesita lo segundo: evalúa
    cientos de tickers que no están en ninguna posición.
    """

    __tablename__ = "instruments"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(16), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    exchange = Column(String(32), nullable=True)
    currency = Column(String(8), default="USD")

    # Identificadores externos. `ibkr_conid` es estable ante cambios de símbolo;
    # `sec_cik` es la llave para SEC EDGAR.
    ibkr_conid = Column(Integer, nullable=True, index=True)
    sec_cik = Column(String(16), nullable=True, index=True)

    sector = Column(String(128), nullable=True)
    industry = Column(String(128), nullable=True)
    instrument_type = Column(String(32), default="STOCK")

    is_optionable = Column(Boolean, nullable=True)
    # Cuándo se confirmó `is_optionable` contra el directorio de símbolos de
    # CBOE (ver app/providers/cboe_optionable.py). Se pisa en cada corrida del
    # scanner; se conserva sobre todo para mostrar de cuándo es el dato.
    optionable_checked_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)

    # Estado vigente en el universo del scanner (Stage 1). Se sobrescribe en
    # cada corrida — a diferencia de fundamental_snapshots, no es histórico:
    # solo importa si el instrumento califica HOY.
    universe_stage = Column(String(32), nullable=True)
    universe_rejected_reason = Column(String(64), nullable=True)
    universe_checked_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<Instrument {self.symbol}>"
