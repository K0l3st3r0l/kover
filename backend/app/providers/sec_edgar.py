"""Proveedor de fundamentales sobre SEC EDGAR.

SEC no pide API key pero sí un `User-Agent` identificable y limita el acceso
automatizado a ~10 req/s. Se configura 5 por margen: quedar bloqueado por la SEC
deja al scanner sin puerta fundamental, y esa puerta corre antes que todo lo demás.

Todas las llamadas son de backend: `data.sec.gov` no expone CORS.
"""

from __future__ import annotations

import gzip
import json
import os
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from ..logging_config import get_logger
from .base import Filing, FinancialFact, ProviderError

logger = get_logger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

CACHE_DIR = Path(os.getenv("SEC_CACHE_DIR", "/app/cache/sec"))
TICKERS_TTL = 24 * 3600
FACTS_TTL = 12 * 3600


class RateLimiter:
    """Espaciado mínimo entre requests, seguro entre hilos."""

    def __init__(self, max_rps: float):
        self._min_interval = 1.0 / max_rps if max_rps > 0 else 0.0
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            sleep_for = self._min_interval - (now - self._last)
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._last = time.monotonic()


def _user_agent() -> str:
    ua = os.getenv("SEC_USER_AGENT", "").strip()
    if not ua:
        # SEC rechaza o bloquea a quien no se identifica. Fallar temprano y claro
        # es mejor que recibir 403 en medio de una corrida del scanner.
        raise ProviderError(
            "sec_edgar",
            "SEC_USER_AGENT no configurado: SEC exige identificarse (ej. 'Kover/1.0 (correo@dominio)')",
            retryable=False,
        )
    return ua


def pad_cik(cik: str | int) -> str:
    return str(cik).lstrip("0").zfill(10)


class SecEdgarFundamentalsProvider:
    name = "sec_edgar"

    def __init__(self, max_rps: Optional[float] = None, cache_dir: Optional[Path] = None):
        rps = max_rps if max_rps is not None else float(os.getenv("SEC_MAX_RPS", "5"))
        self._limiter = RateLimiter(rps)
        self._cache_dir = cache_dir or CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._session = requests.Session()
        self._ticker_map: Optional[dict[str, dict[str, Any]]] = None

    # ── HTTP con caché ────────────────────────────────────────────────────────

    def _cache_path(self, key: str) -> Path:
        return self._cache_dir / f"{key}.json.gz"

    def _read_cache(self, key: str, ttl: int) -> Optional[dict]:
        path = self._cache_path(key)
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > ttl:
            return None
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def _write_cache(self, key: str, payload: dict) -> None:
        try:
            with gzip.open(self._cache_path(key), "wt", encoding="utf-8") as fh:
                json.dump(payload, fh)
        except OSError as exc:
            logger.warning("no se pudo cachear", extra={"key": key, "error": str(exc)[:200]})

    def _get_json(self, url: str, cache_key: Optional[str] = None, ttl: int = FACTS_TTL) -> dict:
        if cache_key:
            cached = self._read_cache(cache_key, ttl)
            if cached is not None:
                return cached

        self._limiter.wait()
        started = time.monotonic()
        try:
            response = self._session.get(
                url, headers={"User-Agent": _user_agent(), "Accept-Encoding": "gzip, deflate"}, timeout=30
            )
        except requests.RequestException as exc:
            raise ProviderError(self.name, f"error de red: {exc}") from exc

        duration_ms = int((time.monotonic() - started) * 1000)
        if response.status_code == 404:
            raise ProviderError(self.name, f"no encontrado: {url.rsplit('/', 1)[-1]}", retryable=False)
        if response.status_code == 403:
            raise ProviderError(
                self.name, "403: User-Agent rechazado o acceso bloqueado por exceso de requests", retryable=False
            )
        if response.status_code != 200:
            raise ProviderError(self.name, f"HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(self.name, f"respuesta no es JSON: {exc}") from exc

        logger.info(
            "sec fetch",
            extra={"duration_ms": duration_ms, "bytes": len(response.content), "cache_key": cache_key},
        )
        if cache_key:
            self._write_cache(cache_key, payload)
        return payload

    # ── Mapeo de ticker a CIK ─────────────────────────────────────────────────

    def _load_ticker_map(self) -> dict[str, dict[str, Any]]:
        if self._ticker_map is not None:
            return self._ticker_map
        payload = self._get_json(TICKERS_URL, cache_key="company_tickers", ttl=TICKERS_TTL)
        mapping: dict[str, dict[str, Any]] = {}
        for row in payload.values():
            ticker = str(row.get("ticker", "")).upper()
            if ticker:
                mapping[ticker] = {"cik": pad_cik(row["cik_str"]), "title": row.get("title")}
        self._ticker_map = mapping
        return mapping

    def resolve_cik(self, symbol: str) -> Optional[str]:
        entry = self._load_ticker_map().get(symbol.upper())
        return entry["cik"] if entry else None

    def resolve_name(self, symbol: str) -> Optional[str]:
        entry = self._load_ticker_map().get(symbol.upper())
        return entry.get("title") if entry else None

    # ── Filings ───────────────────────────────────────────────────────────────

    def get_filings(self, cik: str, forms: Optional[list[str]] = None, limit: int = 60) -> list[Filing]:
        cik = pad_cik(cik)
        payload = self._get_json(
            SUBMISSIONS_URL.format(cik=cik), cache_key=f"submissions_{cik}", ttl=FACTS_TTL
        )
        recent = payload.get("filings", {}).get("recent", {})
        if not recent:
            return []

        wanted = {f.upper() for f in forms} if forms else None
        results: list[Filing] = []
        count = len(recent.get("accessionNumber", []))
        for i in range(count):
            form = recent["form"][i]
            if wanted and form.upper() not in wanted:
                continue
            accepted_raw = recent["acceptanceDateTime"][i]
            try:
                accepted = datetime.fromisoformat(accepted_raw.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                accepted = datetime.combine(
                    date.fromisoformat(recent["filingDate"][i]),
                    datetime.min.time(),
                    tzinfo=timezone.utc,
                )
            period_end = recent.get("reportDate", [""] * count)[i] or None
            results.append(
                Filing(
                    accession_no=recent["accessionNumber"][i],
                    form=form,
                    filing_date=date.fromisoformat(recent["filingDate"][i]),
                    accepted_at=accepted,
                    period_end=date.fromisoformat(period_end) if period_end else None,
                    primary_doc=recent.get("primaryDocument", [None] * count)[i],
                )
            )
            if len(results) >= limit:
                break
        return results

    def filing_document_url(self, cik: str, accession_no: str, primary_doc: str) -> str:
        acc = accession_no.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{primary_doc}"

    def get_filing_text(self, cik: str, accession_no: str, primary_doc: str, max_bytes: int = 6_000_000) -> str:
        """Descarga el documento principal de un filing para el análisis textual."""
        url = self.filing_document_url(cik, accession_no, primary_doc)
        self._limiter.wait()
        try:
            response = self._session.get(url, headers={"User-Agent": _user_agent()}, timeout=60, stream=True)
        except requests.RequestException as exc:
            raise ProviderError(self.name, f"error de red bajando filing: {exc}") from exc
        if response.status_code != 200:
            raise ProviderError(self.name, f"HTTP {response.status_code} bajando filing")

        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(65536):
            chunks.append(chunk)
            total += len(chunk)
            if total >= max_bytes:
                break
        return b"".join(chunks).decode("utf-8", errors="replace")

    # ── Facts XBRL ────────────────────────────────────────────────────────────

    def get_company_facts(self, cik: str) -> dict:
        cik = pad_cik(cik)
        return self._get_json(
            COMPANYFACTS_URL.format(cik=cik), cache_key=f"companyfacts_{cik}", ttl=FACTS_TTL
        )

    def get_facts(self, cik: str) -> list[FinancialFact]:
        """Facts ya normalizados a métricas canónicas."""
        from ..fundamentals.normalizer import normalize_company_facts

        return normalize_company_facts(self.get_company_facts(cik))

    def probe(self) -> dict[str, Any]:
        """Verificación de salud para provider_status."""
        mapping = self._load_ticker_map()
        return {"tickers_mapped": len(mapping)}
