"""Universo de símbolos — Nasdaq Trader Symbol Directory.

Fuente pública, sin API key: `nasdaqtraded.txt` cubre NYSE + NASDAQ + AMEX (no
solo NASDAQ, pese al nombre — es el consolidado que usa el propio operador).
Trae flags de ETF y test issue, pero **no** optionabilidad ni exclusión de
preferentes/warrants/units de forma explícita: eso se infiere de
`Security Name` con un heurístico de texto, documentado abajo. El plan original
(`docs/COVERED_CALL_SCANNER_PLAN.md` §6) señala CBOE como fuente separada de
optionabilidad; en vez de mantener un segundo proveedor, K3 verifica
optionabilidad directamente contra yfinance (`scanner/universe.py`), sobre los
sobrevivientes del filtro de precio/volumen — más caro por símbolo pero solo
corre sobre cientos, no miles.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

from ..logging_config import get_logger
from .base import ProviderError

logger = get_logger(__name__)

SYMBOL_DIRECTORY_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
CACHE_DIR = Path(os.getenv("SCANNER_CACHE_DIR", "/app/cache/scanner"))
CACHE_TTL = 20 * 3600  # una corrida diaria; margen para reintentos manuales

# Nombres de seguridad que casi nunca son la acción común que la estrategia de
# covered call busca. Substring, case-insensitive contra Security Name.
_NAME_EXCLUDE_PATTERNS = (
    "warrant",
    "right",
    " unit",
    "units ",
    "preferred",
    "depositary",
    " notes",
    "debenture",
    "trust pfd",
    " when issued",
    "convertible",
)


@dataclass(frozen=True)
class NasdaqListing:
    symbol: str
    security_name: str
    listing_exchange: str
    is_etf: bool
    is_test_issue: bool
    round_lot_size: Optional[int]

    def looks_like_common_stock(self) -> bool:
        name = self.security_name.lower()
        if any(pattern in name for pattern in _NAME_EXCLUDE_PATTERNS):
            return False
        # Símbolos con sufijo de clase (BRK.A → "BRK/A" en este feed) o tickers
        # con caracteres no alfabéticos casi siempre son instrumentos exóticos
        # para la estrategia (warrants "SYM.WS", units "SYM.U", etc.).
        if not self.symbol.isalpha():
            return False
        if len(self.symbol) > 5:
            return False
        return True


class NasdaqUniverseProvider:
    name = "nasdaq_trader"

    def __init__(self, cache_dir: Optional[Path] = None):
        self._cache_dir = cache_dir or CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._session = requests.Session()

    def _cache_path(self) -> Path:
        return self._cache_dir / "nasdaqtraded.txt"

    def _read_cache(self) -> Optional[str]:
        path = self._cache_path()
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > CACHE_TTL:
            return None
        return path.read_text()

    def _write_cache(self, text: str) -> None:
        self._cache_path().write_text(text)

    def _fetch_raw(self) -> str:
        cached = self._read_cache()
        if cached is not None:
            return cached
        try:
            resp = self._session.get(SYMBOL_DIRECTORY_URL, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise ProviderError("nasdaq_trader", f"fallo al descargar symbol directory: {exc}") from exc
        text = resp.text
        if not text or "Symbol" not in text.splitlines()[0]:
            raise ProviderError("nasdaq_trader", "respuesta sin cabecera esperada", retryable=False)
        self._write_cache(text)
        return text

    def get_listings(self) -> list[NasdaqListing]:
        """Todo el directorio, sin filtrar. `scanner/universe.py` aplica las reglas."""
        text = self._fetch_raw()
        lines = text.splitlines()
        if not lines:
            return []
        header = lines[0].split("|")
        try:
            idx_symbol = header.index("Symbol")
            idx_name = header.index("Security Name")
            idx_exchange = header.index("Listing Exchange")
            idx_etf = header.index("ETF")
            idx_lot = header.index("Round Lot Size")
            idx_test = header.index("Test Issue")
        except ValueError as exc:
            raise ProviderError("nasdaq_trader", f"formato inesperado: falta columna {exc}", retryable=False)

        listings: list[NasdaqListing] = []
        for line in lines[1:]:
            if not line or line.startswith("File Creation Time"):
                continue
            fields = line.split("|")
            if len(fields) <= max(idx_symbol, idx_name, idx_exchange, idx_etf, idx_lot, idx_test):
                continue
            symbol = fields[idx_symbol].strip().upper()
            if not symbol:
                continue
            try:
                lot = int(fields[idx_lot]) if fields[idx_lot].strip() else None
            except ValueError:
                lot = None
            listings.append(
                NasdaqListing(
                    symbol=symbol,
                    security_name=fields[idx_name].strip(),
                    listing_exchange=fields[idx_exchange].strip(),
                    is_etf=fields[idx_etf].strip().upper() == "Y",
                    is_test_issue=fields[idx_test].strip().upper() == "Y",
                    round_lot_size=lot,
                )
            )
        logger.info("symbol directory descargado", extra={"listings": len(listings)})
        return listings

    def probe(self) -> dict:
        listings = self.get_listings()
        return {"listings": len(listings)}
