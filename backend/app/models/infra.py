"""Tablas de soporte: trazabilidad de datos, settings y estado de proveedores.

Regla del proyecto: ningún dato se muestra sin poder decir de dónde salió y de
cuándo es. `DataProvenance` es la mitad persistida de esa regla; la otra mitad
viaja en las respuestas de la API.
"""

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from ..database import Base

# JSONB en Postgres, JSON genérico en cualquier otro dialecto: los tests corren
# sobre SQLite en memoria y `create_all` no sabe compilar JSONB ahí.
JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class DataProvenance(Base):
    __tablename__ = "data_provenance"

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String(64), nullable=False)  # stock_quote, option_quote, fundamental…
    entity_key = Column(String(128), nullable=False)  # normalmente el ticker o el conid
    source = Column(String(64), nullable=False)
    as_of = Column(DateTime(timezone=True), nullable=False)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
    is_stale = Column(Boolean, default=False)

    def __repr__(self):
        return f"<DataProvenance {self.entity_type}:{self.entity_key} from {self.source}>"


class AppSetting(Base):
    """Configuración del scanner. `user_id` NULL identifica un setting global."""

    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    key = Column(String(128), nullable=False)
    value = Column(JSONVariant, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<AppSetting {self.key} user={self.user_id}>"


class ProviderStatus(Base):
    """Última salud conocida de cada proveedor externo, para /api/data-health."""

    __tablename__ = "provider_status"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(32), nullable=False, default="UNKNOWN")
    last_success = Column(DateTime(timezone=True), nullable=True)
    last_attempt = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    last_error_at = Column(DateTime(timezone=True), nullable=True)
    consecutive_errors = Column(Integer, default=0)
    detail = Column(JSONVariant, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ProviderStatus {self.provider}={self.status}>"
