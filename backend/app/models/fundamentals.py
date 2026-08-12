import enum

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func

from ..database import Base
from .infra import JSONVariant


class FundamentalProfile(str, enum.Enum):
    """No se evalúa igual a Ford que a una empresa pre-revenue.

    Un current ratio de 8 es excelente en una madura y normal en una que acaba de
    levantar capital; un FCF negativo es alarma en una y el plan de negocio en la
    otra. El perfil decide qué pesa.
    """

    MATURE_PROFITABLE = "MATURE_PROFITABLE"
    GROWTH_PROFITABLE = "GROWTH_PROFITABLE"
    GROWTH_PREPROFIT = "GROWTH_PREPROFIT"
    DEVELOPMENT_STAGE = "DEVELOPMENT_STAGE"
    FINANCIAL = "FINANCIAL"
    REIT = "REIT"
    UNKNOWN = "UNKNOWN"


class ScoreStatus(str, enum.Enum):
    OK = "OK"
    # El perfil existe pero sus métricas correctas son sectoriales y no están
    # implementadas: se registra sin score en vez de inventar uno.
    UNSUPPORTED_PROFILE = "UNSUPPORTED_PROFILE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class FundamentalRiskFlag(str, enum.Enum):
    GOING_CONCERN = "GOING_CONCERN"
    BANKRUPTCY = "BANKRUPTCY"
    RESTRUCTURING = "RESTRUCTURING"
    DELISTING_RISK = "DELISTING_RISK"
    SEVERE_LIQUIDITY_RISK = "SEVERE_LIQUIDITY_RISK"
    EXTREME_DILUTION = "EXTREME_DILUTION"
    NEGATIVE_EQUITY = "NEGATIVE_EQUITY"
    COVENANT_BREACH = "COVENANT_BREACH"
    AUDITOR_WARNING = "AUDITOR_WARNING"
    STALE_FILINGS = "STALE_FILINGS"


class FlagSeverity(str, enum.Enum):
    REJECT = "REJECT"
    PENALIZE = "PENALIZE"
    INFO = "INFO"


class SecFiling(Base):
    __tablename__ = "sec_filings"

    id = Column(Integer, primary_key=True, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    accession_no = Column(String(32), unique=True, nullable=False)
    form = Column(String(16), nullable=False)
    filing_date = Column(Date, nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(Date, nullable=True)
    primary_doc = Column(Text, nullable=True)
    is_xbrl = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<SecFiling {self.form} {self.filing_date}>"


class FinancialFact(Base):
    """Un hecho XBRL con su tag original.

    Se guardan todas las versiones de un mismo período: los restatements cambian
    el valor y el backtesting necesita saber qué número estaba publicado en cada
    momento.
    """

    __tablename__ = "financial_facts"

    id = Column(Integer, primary_key=True, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    metric = Column(String(64), nullable=False)
    source_tag = Column(String(128), nullable=False)
    taxonomy = Column(String(32), nullable=False, default="us-gaap")
    value = Column(Float, nullable=True)
    unit = Column(String(16), nullable=True)
    form = Column(String(16), nullable=True)
    fiscal_year = Column(Integer, nullable=True)
    fiscal_period = Column(String(8), nullable=True)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    frame = Column(String(24), nullable=True)
    filing_date = Column(Date, nullable=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    accession_no = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FundamentalSnapshot(Base):
    """Estado fundamental a una fecha. Nunca se sobrescribe."""

    __tablename__ = "fundamental_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    as_of_date = Column(Date, nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=False)
    profile = Column(String(32), nullable=False)
    score_status = Column(String(32), nullable=False)
    financial_safety_score = Column(Float, nullable=True)

    revenue_ttm = Column(Float, nullable=True)
    revenue_growth_yoy = Column(Float, nullable=True)
    gross_profit_ttm = Column(Float, nullable=True)
    operating_income_ttm = Column(Float, nullable=True)
    net_income_ttm = Column(Float, nullable=True)
    operating_margin = Column(Float, nullable=True)

    cash = Column(Float, nullable=True)
    current_assets = Column(Float, nullable=True)
    current_liabilities = Column(Float, nullable=True)
    total_assets = Column(Float, nullable=True)
    total_liabilities = Column(Float, nullable=True)
    stockholders_equity = Column(Float, nullable=True)
    short_term_debt = Column(Float, nullable=True)
    long_term_debt = Column(Float, nullable=True)
    total_debt = Column(Float, nullable=True)
    net_debt = Column(Float, nullable=True)

    operating_cf_ttm = Column(Float, nullable=True)
    capex_ttm = Column(Float, nullable=True)
    fcf_ttm = Column(Float, nullable=True)
    fcf_margin = Column(Float, nullable=True)

    current_ratio = Column(Float, nullable=True)
    debt_to_equity = Column(Float, nullable=True)
    shares_outstanding = Column(Float, nullable=True)
    dilution_yoy = Column(Float, nullable=True)
    cash_runway_quarters = Column(Float, nullable=True)

    components = Column(JSONVariant, nullable=True)
    missing_metrics = Column(JSONVariant, nullable=True)

    source_filing_id = Column(Integer, ForeignKey("sec_filings.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Snapshot {self.instrument_id} {self.as_of_date} score={self.financial_safety_score}>"


class RiskFlag(Base):
    __tablename__ = "fundamental_risk_flags"

    id = Column(Integer, primary_key=True, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    flag = Column(String(48), nullable=False)
    severity = Column(String(16), nullable=False)
    origin = Column(String(16), nullable=False)
    filing_id = Column(Integer, ForeignKey("sec_filings.id"), nullable=True)
    section = Column(String(128), nullable=True)
    text_excerpt = Column(Text, nullable=True)
    detail = Column(JSONVariant, nullable=True)
    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<RiskFlag {self.flag} {self.severity}>"


class CorporateEventRow(Base):
    __tablename__ = "corporate_events"

    id = Column(Integer, primary_key=True, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    event_type = Column(String(32), nullable=False)
    event_date = Column(Date, nullable=False)
    confirmed = Column(Boolean, default=False)
    source = Column(String(64), nullable=False)
    detail = Column(JSONVariant, nullable=True)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
