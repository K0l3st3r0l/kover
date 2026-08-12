"""Auditoría de corridas del sync de bróker (K7 — IBKR Flex).

No participa del dedupe ni de la escritura de transacciones: eso lo sigue
haciendo /confirm, sin cambios. Esta tabla solo deja rastro de qué trajo cada
preview — necesario dado que v1 es manual y sin auto-confirmación; si algo
no cuadra días después, esto dice qué se vio y cuándo.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from ..database import Base
from .infra import JSONVariant


class BrokerSyncRun(Base):
    __tablename__ = "broker_sync_runs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source = Column(String(16), nullable=False)  # TRADES | ACTIVITY | BOTH
    triggered_by = Column(String(16), nullable=False, default="MANUAL")  # MANUAL | SCHEDULED
    status = Column(String(16), nullable=False, default="OK")  # OK | ERROR
    raw_row_count = Column(Integer)
    importable_count = Column(Integer)
    duplicate_count = Column(Integer)
    warning_count = Column(Integer)
    position_mismatches = Column(JSONVariant)
    error_message = Column(Text)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at = Column(DateTime(timezone=True))

    def __repr__(self):
        return f"<BrokerSyncRun {self.id} user={self.user_id} status={self.status}>"
