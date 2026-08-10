"""Contratos de los proveedores externos.

La lógica del scanner, el scoring y el portfolio dependen SOLO de estos Protocols.
Cambiar de yfinance a IBKR debe ser cambiar una implementación, nunca la lógica.

Todo dato que sale de un proveedor viaja con `as_of` y `source`: sin eso no se
puede distinguir un precio fresco de uno de hace tres horas, y el scanner no debe
rankear datos viejos en silencio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional, Protocol, runtime_checkable


# ── Envoltorio de procedencia ─────────────────────────────────────────────────

@dataclass(frozen=True)
class Provenance:
    source: str
    as_of: datetime
    fetched_at: datetime

    def age_seconds(self, now: Optional[datetime] = None) -> float:
        reference = now or datetime.now(self.as_of.tzinfo)
        return (reference - self.as_of).total_seconds()


# ── Datos de mercado ──────────────────────────────────────────────────────────

@dataclass
class StockQuote:
    symbol: str
    price: Optional[float]
    bid: Optional[float]
    ask: Optional[float]
    volume: Optional[int]
    provenance: Provenance

    @property
    def mid(self) -> Optional[float]:
        if self.bid is None or self.ask is None:
            return None
        total = self.bid + self.ask
        return total / 2 if total > 0 else None


@dataclass
class DailyBar:
    symbol: str
    bar_date: date
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    close: Optional[float]
    volume: Optional[int]
    source: str


@dataclass
class OptionQuote:
    """Una cotización de contrato.

    `delta`/`gamma`/`theta`/`vega` pueden venir del proveedor o calcularse con
    Black-Scholes: `greeks_source` lo distingue y nunca debe perderse. yfinance no
    entrega Greeks, así que en v1 son siempre BS_CALCULATED.
    """

    underlying: str
    expiration: date
    strike: float
    right: str  # "C" | "P"
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]
    volume: Optional[int]
    open_interest: Optional[int]
    implied_volatility: Optional[float]
    provenance: Provenance
    occ_symbol: Optional[str] = None
    ibkr_conid: Optional[int] = None
    multiplier: int = 100
    min_tick: float = 0.01
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    greeks_source: Optional[str] = None

    @property
    def mid(self) -> Optional[float]:
        if self.bid is None or self.ask is None:
            return None
        total = self.bid + self.ask
        return total / 2 if total > 0 else None


# ── Fundamentales y eventos ───────────────────────────────────────────────────

@dataclass
class FinancialFact:
    """Un hecho XBRL con su tag de origen intacto: la trazabilidad no se pierde."""

    metric: str
    source_tag: str
    value: Optional[float]
    unit: Optional[str]
    form: Optional[str]
    fiscal_year: Optional[int]
    fiscal_quarter: Optional[int]
    period_start: Optional[date]
    period_end: Optional[date]
    filing_date: Optional[date]
    accepted_at: Optional[datetime]
    accession_no: Optional[str] = None


@dataclass
class Filing:
    accession_no: str
    form: str
    filing_date: date
    accepted_at: datetime
    period_end: Optional[date]
    primary_doc: Optional[str]


@dataclass
class CorporateEvent:
    symbol: str
    event_type: str  # EARNINGS | DIVIDEND | SPLIT
    event_date: date
    confirmed: bool
    source: str


# ── Bróker ────────────────────────────────────────────────────────────────────

@dataclass
class BrokerExecution:
    """Una ejecución tal como la reporta el bróker, antes de mapearla a Transaction."""

    external_id: str
    account_id: str
    symbol: str
    asset_category: str  # STK | OPT
    side: str  # BUY | SELL
    quantity: float
    price: float
    proceeds: float
    commission: float
    executed_at_utc: datetime
    source_timezone: str
    original_timestamp: str
    codes: list[str] = field(default_factory=list)
    underlying: Optional[str] = None
    strike: Optional[float] = None
    expiration: Optional[date] = None
    right: Optional[str] = None
    multiplier: Optional[int] = None
    conid: Optional[int] = None
    raw: dict[str, Any] = field(default_factory=dict)

    def has_code(self, target: str) -> bool:
        """Comparación token a token.

        Buscar el substring "A" da positivo en "IA" (importado ajustado) y en "Ca"
        (cancelado), que no son asignaciones. En el histórico real de la cuenta hay
        6 filas con `A` y 8 con `IA`: el substring daría 14 asignaciones falsas.
        """
        return target in self.codes


@dataclass
class BrokerCashTransaction:
    external_id: Optional[str]
    account_id: str
    type: str  # Dividends | Withholding Tax | Other Fees | Deposits/Withdrawals…
    symbol: Optional[str]
    amount: float
    settle_date: Optional[date]
    executed_at_utc: Optional[datetime]
    description: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class BrokerPositionLot:
    account_id: str
    symbol: str
    asset_category: str
    quantity: float
    cost_basis_price: Optional[float]
    cost_basis_money: Optional[float]
    open_date: Optional[datetime]
    mark_price: Optional[float] = None


# ── Protocols ─────────────────────────────────────────────────────────────────

@runtime_checkable
class MarketDataProvider(Protocol):
    name: str

    def get_quote(self, symbol: str) -> Optional[StockQuote]: ...

    def get_quotes(self, symbols: list[str]) -> dict[str, Optional[StockQuote]]: ...


@runtime_checkable
class HistoricalMarketDataProvider(Protocol):
    name: str

    def get_daily_bars(self, symbol: str, lookback_days: int) -> list[DailyBar]: ...


@runtime_checkable
class OptionDataProvider(Protocol):
    name: str

    def get_expirations(self, symbol: str) -> list[date]: ...

    def get_chain(self, symbol: str, expiration: date) -> list[OptionQuote]: ...


@runtime_checkable
class HistoricalOptionDataProvider(Protocol):
    name: str

    def get_option_daily_bars(
        self, occ_symbol: str, start: date, end: date
    ) -> list[DailyBar]: ...


@runtime_checkable
class FundamentalsProvider(Protocol):
    name: str

    def resolve_cik(self, symbol: str) -> Optional[str]: ...

    def get_filings(self, cik: str, forms: Optional[list[str]] = None) -> list[Filing]: ...

    def get_facts(self, cik: str) -> list[FinancialFact]: ...


@runtime_checkable
class CorporateEventsProvider(Protocol):
    name: str

    def get_events(self, symbols: list[str]) -> list[CorporateEvent]: ...


@runtime_checkable
class BrokerProvider(Protocol):
    name: str

    def get_executions(self) -> list[BrokerExecution]: ...

    def get_cash_transactions(self) -> list[BrokerCashTransaction]: ...

    def get_position_lots(self) -> list[BrokerPositionLot]: ...


class ProviderError(Exception):
    """Falla de un proveedor externo. Se registra en provider_status, no se traga."""

    def __init__(self, provider: str, message: str, retryable: bool = True):
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.retryable = retryable
