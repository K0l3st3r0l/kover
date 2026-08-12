"""Stage 1 del scanner: universo optionable US$10–20 con liquidez.

Tres pasadas, cada una más cara que la anterior y sobre un conjunto más chico:

1. **Listado** (`NasdaqUniverseProvider`, un solo request): excluye ETFs,
   test issues y lo que el nombre delata como no-acción-común (warrants,
   preferentes, units). Miles → miles (no filtra por precio todavía).
2. **Precio + liquidez** (yfinance en lotes de `CHUNK_SIZE`): precio en banda
   y volumen mínimo. Miles → decenas/cientos.
3. **Optionabilidad** (yfinance, un request por sobreviviente): solo corre
   sobre la salida de la pasada 2, que ya es chica.

Los resultados fuera de la banda de precio o sin datos NO se persisten como
`Instrument` — son la mayoría del listado y no aportan nada de vuelta al
usuario. Los que sí caen en la banda de precio se persisten siempre, aunque
después se descarten por liquidez u optionabilidad: esa es la zona donde el
usuario quiere ver el motivo exacto ("¿por qué no ANEB?").
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import yfinance as yf

from ..logging_config import get_logger
from ..market.market_data import MarketDataService

logger = get_logger(__name__)

PRICE_MIN = 10.0
PRICE_MAX = 20.0
AVG_DAILY_VOLUME_MIN = 500_000
AVG_DOLLAR_VOLUME_MIN = 10_000_000

CHUNK_SIZE = 150
OPTIONABLE_CHECK_DELAY = 0.2  # segundos entre checks secuenciales, buena vecindad con Yahoo

STAGE_PRICE_RANGE = "PRICE_RANGE"
STAGE_LIQUIDITY = "LIQUIDITY"
STAGE_OPTIONABLE = "OPTIONABLE"

REASON_PRICE_OUT_OF_RANGE = "PRICE_OUT_OF_RANGE"
REASON_NO_PRICE_DATA = "NO_PRICE_DATA"
REASON_LOW_VOLUME = "LOW_VOLUME"
REASON_LOW_DOLLAR_VOLUME = "LOW_DOLLAR_VOLUME"
REASON_NOT_OPTIONABLE = "NOT_OPTIONABLE"


@dataclass
class UniverseCandidate:
    symbol: str
    name: Optional[str]
    exchange: Optional[str]
    stage_reached: str
    rejected_reason: Optional[str]
    price: Optional[float] = None
    avg_daily_volume_20: Optional[float] = None
    avg_dollar_volume_20: Optional[float] = None
    is_optionable: Optional[bool] = None

    @property
    def qualified(self) -> bool:
        return self.stage_reached == STAGE_OPTIONABLE and self.rejected_reason is None


@dataclass
class UniverseFunnelCounts:
    listed_total: int = 0
    excluded_etf: int = 0
    excluded_test_issue: int = 0
    excluded_not_common: int = 0
    listing_passed: int = 0
    price_checked: int = 0
    price_no_data: int = 0
    price_out_of_range: int = 0
    price_in_range: int = 0
    low_volume: int = 0
    optionable_checked: int = 0
    not_optionable: int = 0
    qualified: int = 0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _filter_listing(provider) -> tuple[list, UniverseFunnelCounts]:
    listings = provider.get_listings()
    counts = UniverseFunnelCounts(listed_total=len(listings))
    passed = []
    for listing in listings:
        if listing.is_etf:
            counts.excluded_etf += 1
            continue
        if listing.is_test_issue:
            counts.excluded_test_issue += 1
            continue
        if not listing.looks_like_common_stock():
            counts.excluded_not_common += 1
            continue
        passed.append(listing)
    counts.listing_passed = len(passed)
    return passed, counts


def _chunked(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _fetch_price_volume_batch(symbols: list[str]) -> dict[str, dict]:
    """Precio de cierre y volumen promedio (20 sesiones) vía yfinance en lote.

    Devuelve {symbol: {"price": float, "avg_volume": float, "avg_dollar_volume": float}}
    para lo que se pudo leer. Un chunk que falla completo se salta y se loguea:
    no debe tumbar la corrida entera por un problema transitorio de red.
    """
    result: dict[str, dict] = {}
    for chunk in _chunked(symbols, CHUNK_SIZE):
        try:
            data = yf.download(
                tickers=" ".join(chunk),
                period="1mo",
                group_by="ticker",
                progress=False,
                auto_adjust=True,
                threads=True,
            )
        except Exception as exc:
            logger.warning("chunk de precios falló", extra={"size": len(chunk), "error": str(exc)[:300]})
            continue

        for symbol in chunk:
            try:
                if len(chunk) == 1:
                    df = data
                else:
                    if symbol not in data.columns.get_level_values(0):
                        continue
                    df = data[symbol]
                closes = df["Close"].dropna()
                volumes = df["Volume"].dropna()
                if closes.empty:
                    continue
                price = float(closes.iloc[-1])
                if price <= 0:
                    continue
                vol_window = volumes.tail(20)
                avg_volume = float(vol_window.mean()) if not vol_window.empty else None
                avg_dollar_volume = (
                    float((df["Close"].tail(20) * df["Volume"].tail(20)).dropna().mean())
                    if not vol_window.empty
                    else None
                )
                result[symbol] = {
                    "price": price,
                    "avg_volume": avg_volume,
                    "avg_dollar_volume": avg_dollar_volume,
                }
            except Exception:
                continue
    return result


def _check_optionable(symbol: str) -> bool:
    try:
        expirations = MarketDataService.get_available_expirations(symbol)
        return bool(expirations)
    except Exception as exc:
        logger.warning("check de optionabilidad falló", extra={"symbol": symbol, "error": str(exc)[:200]})
        return False


def run_universe_scan(
    provider,
    price_min: float = PRICE_MIN,
    price_max: float = PRICE_MAX,
    avg_volume_min: float = AVG_DAILY_VOLUME_MIN,
    avg_dollar_volume_min: float = AVG_DOLLAR_VOLUME_MIN,
    check_optionable: bool = True,
) -> tuple[list[UniverseCandidate], UniverseFunnelCounts]:
    listings, counts = _filter_listing(provider)
    listing_by_symbol = {l.symbol: l for l in listings}

    price_data = _fetch_price_volume_batch([l.symbol for l in listings])
    counts.price_checked = len(price_data)
    counts.price_no_data = counts.listing_passed - len(price_data)

    in_range: list[UniverseCandidate] = []
    for symbol, values in price_data.items():
        listing = listing_by_symbol[symbol]
        price = values["price"]
        if not (price_min <= price <= price_max):
            counts.price_out_of_range += 1
            continue
        candidate = UniverseCandidate(
            symbol=symbol,
            name=listing.security_name,
            exchange=listing.listing_exchange,
            stage_reached=STAGE_PRICE_RANGE,
            rejected_reason=None,
            price=price,
            avg_daily_volume_20=values["avg_volume"],
            avg_dollar_volume_20=values["avg_dollar_volume"],
        )
        in_range.append(candidate)
    counts.price_in_range = len(in_range)

    liquid: list[UniverseCandidate] = []
    for candidate in in_range:
        vol_ok = (candidate.avg_daily_volume_20 or 0) >= avg_volume_min
        dollar_ok = (candidate.avg_dollar_volume_20 or 0) >= avg_dollar_volume_min
        if not (vol_ok and dollar_ok):
            candidate.stage_reached = STAGE_LIQUIDITY
            candidate.rejected_reason = REASON_LOW_VOLUME if not vol_ok else REASON_LOW_DOLLAR_VOLUME
            counts.low_volume += 1
            continue
        candidate.stage_reached = STAGE_LIQUIDITY
        liquid.append(candidate)

    all_candidates = list(in_range)  # incluye los descartados por liquidez, ya marcados

    if not check_optionable:
        return all_candidates, counts

    for candidate in liquid:
        counts.optionable_checked += 1
        is_optionable = _check_optionable(candidate.symbol)
        candidate.is_optionable = is_optionable
        candidate.stage_reached = STAGE_OPTIONABLE
        if not is_optionable:
            candidate.rejected_reason = REASON_NOT_OPTIONABLE
            counts.not_optionable += 1
        else:
            counts.qualified += 1
        time.sleep(OPTIONABLE_CHECK_DELAY)

    return all_candidates, counts
