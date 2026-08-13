"""Cadenas de opciones — endpoint público de cotizaciones diferidas de CBOE.

`docs/COVERED_CALL_SCANNER_PLAN.md` §K4 asumía yfinance con rate limiting y
backoff, más Black-Scholes local para los Greeks porque yfinance no los
entrega. Ninguna de las dos cosas hace falta: CBOE publica la cadena completa
—todas las expiraciones, con bid/ask, tamaños, IV, OI, volumen **y Greeks
calculados**— en un solo JSON por símbolo.

    https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json

Es el mismo razonamiento que resolvió la optionabilidad en K3 (ver
wiki/projects/kover/decisions/universo-market-safety-score.md): un archivo
público servido por CDN le gana a scraping de un endpoint no oficial con
detección de bots. Medido contra los símbolos reales del universo: 0,1–0,3s y
73–430 KB por símbolo.

**CBOE sí limita por ráfaga**, al contrario de lo que se asumió al escribir este
módulo: una corrida de 306 símbolos a ~5 req/s completó 60 y las otras 246
volvieron HTTP 429. La respuesta trae `Retry-After` (medido: 9s), así que el
límite se respeta leyendo el header en vez de adivinar un backoff, y el scan
espacia sus requests. No es el bloqueo por IP de yfinance —se destraba en
segundos y viene documentado en la respuesta— pero tampoco es barra libre.

**La cotización es diferida ~15 minutos.** Viene con su propio `timestamp`, que
se propaga como `as_of` en la Provenance: quien mire una prima tiene que poder
saber de cuándo es. Para vender covered calls con vencimientos de semanas el
delay es irrelevante, pero eso lo decide quien lee el dato, no este módulo.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

import requests

from ..logging_config import get_logger
from .base import OptionQuote, Provenance, ProviderError

logger = get_logger(__name__)


@dataclass
class UnderlyingQuote:
    """Cotización del papel, del mismo payload que la cadena."""

    symbol: str
    price: Optional[float]
    bid: Optional[float]
    ask: Optional[float]
    iv30: Optional[float]
    as_of: datetime


CHAIN_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"
REQUEST_TIMEOUT = 25
USER_AGENT = "kover/1.0 (covered call scanner)"
# CBOE limita por ráfaga con un 429 de Cloudflare y un Retry-After corto.
MAX_429_RETRIES = 3
DEFAULT_RETRY_AFTER = 10.0
MAX_RETRY_AFTER = 60.0

# OSI: raíz + AAMMDD + C/P + strike en milésimas (8 dígitos). El sufijo mide
# siempre 15 caracteres, así que se parsea por posición y no con una clase de
# caracteres para la raíz: hay tickers con punto (BRK.B, BF.B) que un
# `[A-Z0-9]{1,6}` descarta en silencio.
OSI_SUFFIX_LEN = 15
OSI_SUFFIX_RE = re.compile(r"^(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<right>[CP])(?P<strike>\d{8})$")


def parse_osi_symbol(symbol: str) -> Optional[tuple[str, date, str, float]]:
    """'F260814C00005000' -> ('F', date(2026,8,14), 'C', 5.0). None si no calza."""
    cleaned = symbol.strip().upper()
    if len(cleaned) <= OSI_SUFFIX_LEN:
        return None
    root, suffix = cleaned[:-OSI_SUFFIX_LEN].strip(), cleaned[-OSI_SUFFIX_LEN:]
    m = OSI_SUFFIX_RE.match(suffix)
    if not m or not root:
        return None
    try:
        expiration = date(2000 + int(m.group("yy")), int(m.group("mm")), int(m.group("dd")))
    except ValueError:
        return None
    return root, expiration, m.group("right"), int(m.group("strike")) / 1000.0


class CboeChainsProvider:
    name = "cboe_delayed_quotes"

    def __init__(self, session: Optional[requests.Session] = None):
        self._session = session or requests.Session()

    def _fetch(self, symbol: str) -> dict:
        url = CHAIN_URL.format(symbol=symbol.upper())
        resp = None

        for intento in range(MAX_429_RETRIES + 1):
            try:
                resp = self._session.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
            except requests.RequestException as exc:
                raise ProviderError(self.name, f"error de red pidiendo la cadena de {symbol}: {exc}") from exc

            if resp.status_code != 429:
                break

            # CBOE limita por ráfaga y dice explícitamente cuánto esperar en
            # Retry-After (medido: 9 segundos). Medido también el costo de
            # ignorarlo: una corrida de 306 símbolos a ~5 req/s completó 60 y
            # falló 246. Se respeta el header en vez de adivinar un backoff.
            espera = _retry_after_seconds(resp.headers.get("Retry-After"))
            if intento == MAX_429_RETRIES:
                raise ProviderError(
                    self.name,
                    f"{symbol}: CBOE sigue limitando tras {MAX_429_RETRIES} esperas (HTTP 429)",
                )
            logger.info(
                "CBOE limitó la ráfaga, esperando",
                extra={"symbol": symbol, "sleep_seconds": espera, "attempt": intento + 1},
            )
            time.sleep(espera)

        if resp.status_code == 404:
            # CBOE responde 404 para símbolos sin cadena publicada. Es un
            # negativo confirmado, no un fallo: se distingue con retryable=False
            # para que el scanner no lo reintente ni lo cuente como error de red.
            raise ProviderError(self.name, f"{symbol}: sin cadena publicada en CBOE (404)", retryable=False)
        if resp.status_code != 200:
            raise ProviderError(self.name, f"{symbol}: CBOE respondió HTTP {resp.status_code}")

        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderError(self.name, f"{symbol}: CBOE devolvió JSON inválido: {exc}") from exc

        if not isinstance(payload, dict) or "data" not in payload:
            raise ProviderError(self.name, f"{symbol}: respuesta de CBOE sin campo 'data'")
        return payload

    @staticmethod
    def _parse_timestamp(raw: Optional[str]) -> datetime:
        """'2026-08-13 14:32:39' -> datetime UTC-aware.

        CBOE no declara timezone en el campo. Si no viene o no parsea, se usa
        la hora actual: es el valor conservador, porque hace que el dato se vea
        *más* fresco de lo que es solo en el caso degenerado, y quien filtra por
        antigüedad ya no tiene un `None` que interpretar.
        """
        if raw:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
        return datetime.now(timezone.utc)

    def get_chain(self, symbol: str) -> tuple[list[OptionQuote], "UnderlyingQuote"]:
        """Cadena completa + cotización del subyacente, del mismo payload.

        El subyacente viaja junto con la cadena a propósito: usar un precio de
        otra fuente (o de otro momento) para calcular moneyness contra estos
        strikes mezcla dos instantes distintos, y el resultado se ve razonable
        aunque esté mal. CBOE entrega bid/ask del papel en el mismo JSON, así
        que el covered call se puede evaluar comprando al ask real y no a una
        aproximación.
        """
        payload = self._fetch(symbol)
        data = payload["data"]
        as_of = self._parse_timestamp(payload.get("timestamp"))
        fetched_at = datetime.now(timezone.utc)
        underlying = UnderlyingQuote(
            symbol=symbol.upper(),
            price=_as_float(data.get("current_price")),
            bid=_as_float(data.get("bid")),
            ask=_as_float(data.get("ask")),
            iv30=_as_float(data.get("iv30")),
            as_of=as_of,
        )

        quotes: list[OptionQuote] = []
        for raw in data.get("options", []) or []:
            osi = raw.get("option")
            parsed = parse_osi_symbol(osi) if osi else None
            if parsed is None:
                continue
            _root, expiration, right, strike = parsed

            quotes.append(
                OptionQuote(
                    underlying=symbol.upper(),
                    expiration=expiration,
                    strike=strike,
                    right=right,
                    bid=_as_float(raw.get("bid")),
                    ask=_as_float(raw.get("ask")),
                    last=_as_float(raw.get("last_trade_price")),
                    volume=_as_int(raw.get("volume")),
                    open_interest=_as_int(raw.get("open_interest")),
                    implied_volatility=_as_float(raw.get("iv")),
                    provenance=Provenance(source=self.name, as_of=as_of, fetched_at=fetched_at),
                    occ_symbol=osi,
                    delta=_as_float(raw.get("delta")),
                    gamma=_as_float(raw.get("gamma")),
                    theta=_as_float(raw.get("theta")),
                    vega=_as_float(raw.get("vega")),
                    # CBOE entrega los Greeks ya calculados: no se recalculan ni
                    # se marcan como BS_CALCULATED, que sería mentir sobre la
                    # procedencia. Ver la regla de as_of/source en
                    # wiki/projects/kover/decisions/covered-call-scanner-stack.md.
                    greeks_source="CBOE_REPORTED",
                )
            )

        if not quotes:
            raise ProviderError(self.name, f"{symbol}: CBOE devolvió una cadena vacía", retryable=False)
        return quotes, underlying

    def probe(self) -> dict:
        quotes, underlying = self.get_chain("AAPL")
        return {"contracts": len(quotes), "underlying_price": underlying.price}


def _retry_after_seconds(header: Optional[str]) -> float:
    """Segundos a esperar según Retry-After, acotado para no colgar la corrida."""
    if not header:
        return DEFAULT_RETRY_AFTER
    try:
        return min(max(float(header), 1.0), MAX_RETRY_AFTER)
    except (TypeError, ValueError):
        return DEFAULT_RETRY_AFTER


def _as_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value) -> Optional[int]:
    parsed = _as_float(value)
    return int(parsed) if parsed is not None else None
