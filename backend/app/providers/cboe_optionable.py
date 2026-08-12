"""Optionabilidad — directorio público de símbolos de CBOE.

Reemplaza el chequeo uno-a-uno contra `yf.Ticker(symbol).options`. Ese enfoque
demostró ser frágil en producción: Yahoo bloqueó el endpoint de opciones para
la IP del VPS incluso con un solo request aislado, sin relación aparente con
el volumen de la corrida (ver
wiki/projects/kover/bugs/scanner-rate-limit-false-not-optionable.md). Un solo
request a un archivo público reemplaza cientos de requests a un endpoint no
oficial y sujeto a bloqueo — exactamente lo que el plan original proponía
(`docs/COVERED_CALL_SCANNER_PLAN.md` §6) antes de optar por yfinance como
atajo.

Las opciones sobre acciones US se negocian multi-listadas por norma del
mercado (OPRA consolida cotizaciones de todos los exchanges de opciones), así
que "aparece en el symbol directory de CBOE" es un proxy confiable de "tiene
opciones listadas" — no hace falta consultar cada exchange por separado.
"""

from __future__ import annotations

import csv
import io
import os
import time
from pathlib import Path
from typing import Optional

import requests

from ..logging_config import get_logger
from .base import ProviderError

logger = get_logger(__name__)

SYMBOL_DIR_URL = "https://www.cboe.com/us/options/symboldir/?download=csv"
CACHE_DIR = Path(os.getenv("SCANNER_CACHE_DIR", "/app/cache/scanner"))
CACHE_TTL = 20 * 3600  # una corrida diaria; no hay razón para pedirlo más seguido
MAX_RETRIES = 2
RETRY_BACKOFF = (2.0, 5.0)


class CboeOptionableProvider:
    name = "cboe_symbol_directory"

    def __init__(self, cache_dir: Optional[Path] = None):
        self._cache_dir = cache_dir or CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._session = requests.Session()

    def _cache_path(self) -> Path:
        return self._cache_dir / "cboe_optionable.csv"

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

        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = self._session.get(
                    SYMBOL_DIR_URL,
                    headers={"User-Agent": "Kover/1.0 (mhrehbein@gmail.com)"},
                    timeout=30,
                )
                resp.raise_for_status()
                text = resp.text
                if not text or "Stock Symbol" not in text.splitlines()[0]:
                    raise ProviderError(
                        "cboe_symbol_directory", "respuesta sin cabecera esperada", retryable=False
                    )
                self._write_cache(text)
                return text
            except requests.RequestException as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF[attempt])
        raise ProviderError("cboe_symbol_directory", f"fallo al descargar: {last_error}") from last_error

    def get_optionable_symbols(self) -> set[str]:
        """Todo el universo de símbolos con opciones listadas en CBOE."""
        text = self._fetch_raw()
        reader = csv.reader(io.StringIO(text))
        next(reader, None)  # cabecera: Company Name, Stock Symbol, DPM Name, ...
        symbols: set[str] = set()
        for row in reader:
            if len(row) < 2:
                continue
            symbol = row[1].strip().upper()
            if symbol:
                symbols.add(symbol)
        logger.info("symbol directory de CBOE descargado", extra={"symbols": len(symbols)})
        return symbols

    def probe(self) -> dict:
        symbols = self.get_optionable_symbols()
        return {"optionable_symbols": len(symbols)}
