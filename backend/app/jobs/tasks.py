"""Tareas programadas, escritas como funciones invocables a mano.

Cada tarea abre y cierra su propia sesión y no depende del scheduler: se pueden
llamar desde un endpoint o desde un test sin levantar APScheduler. Eso es lo que
permitirá moverlas a Redis/RQ más adelante sin tocar la lógica.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..logging_config import LogContext, get_logger
from ..models import ProviderStatus, User

logger = get_logger(__name__)


def _record_provider(
    db: Session,
    provider: str,
    *,
    ok: bool,
    error: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
) -> None:
    now = datetime.now(timezone.utc)
    row = db.query(ProviderStatus).filter(ProviderStatus.provider == provider).first()
    if row is None:
        row = ProviderStatus(provider=provider)
        db.add(row)
    row.last_attempt = now
    row.detail = detail
    if ok:
        row.status = "OK"
        row.last_success = now
        row.consecutive_errors = 0
        row.last_error = None
    else:
        row.consecutive_errors = (row.consecutive_errors or 0) + 1
        row.status = "DOWN" if row.consecutive_errors >= 3 else "DEGRADED"
        row.last_error = error
        row.last_error_at = now


def check_provider(provider: str, probe: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Ejecuta un probe y deja el resultado en provider_status.

    Un proveedor caído nunca debe traducirse en datos silenciosamente viejos: el
    scanner consulta esta tabla antes de rankear.
    """
    db = SessionLocal()
    started = time.monotonic()
    try:
        with LogContext(provider=provider):
            try:
                detail = probe()
                _record_provider(db, provider, ok=True, detail=detail)
                db.commit()
                result = {"provider": provider, "status": "OK", "detail": detail}
            except Exception as exc:  # el probe no debe tumbar el scheduler
                _record_provider(db, provider, ok=False, error=str(exc)[:2000])
                db.commit()
                logger.warning("probe falló", extra={"error": str(exc)[:500]})
                result = {"provider": provider, "status": "ERROR", "error": str(exc)[:500]}
            result["duration_ms"] = int((time.monotonic() - started) * 1000)
            return result
    finally:
        db.close()


def _probe_yfinance() -> dict[str, Any]:
    from ..market.market_data import MarketDataService

    price = MarketDataService.get_current_price("SPY")
    if price is None:
        raise RuntimeError("sin precio para SPY")
    return {"probe_symbol": "SPY", "price": price}


def _probe_sec() -> dict[str, Any]:
    from ..providers.sec_edgar import SecEdgarFundamentalsProvider

    return SecEdgarFundamentalsProvider().probe()


def _probe_nasdaq_trader() -> dict[str, Any]:
    from ..providers.nasdaq_universe import NasdaqUniverseProvider

    return NasdaqUniverseProvider().probe()


def refresh_provider_status() -> list[dict[str, Any]]:
    """Verifica los proveedores activos. Los de fases futuras no se prueban aún."""
    return [
        check_provider("yfinance", _probe_yfinance),
        check_provider("sec_edgar", _probe_sec),
        check_provider("nasdaq_trader", _probe_nasdaq_trader),
    ]


def refresh_fundamentals_for_holdings() -> dict[str, Any]:
    """Actualiza fundamentales de lo que el usuario tiene o vigila.

    Antes de que exista el universo del scanner (K3), el conjunto relevante son
    las posiciones abiertas y la watchlist.
    """
    from ..fundamentals.service import refresh_fundamentals
    from ..models import Campaign, CampaignStatus, Watchlist

    db = SessionLocal()
    try:
        symbols = {
            row.ticker
            for row in db.query(Campaign.ticker)
            .filter(Campaign.status != CampaignStatus.CLOSED)
            .distinct()
        }
        symbols |= {row.ticker for row in db.query(Watchlist.ticker).distinct()}

        done, failed = [], []
        for symbol in sorted(symbols):
            try:
                with LogContext(job_id="fundamentals_refresh", ticker=symbol):
                    refresh_fundamentals(db, symbol)
                done.append(symbol)
            except Exception as exc:
                db.rollback()
                failed.append({"symbol": symbol, "error": str(exc)[:300]})
                logger.warning("fundamentales fallaron", extra={"ticker": symbol, "error": str(exc)[:300]})
        return {"updated": done, "failed": failed}
    finally:
        db.close()


def run_universe_scan() -> dict[str, Any]:
    """Stage 1 (universo $10–20 optionable) + Stage 3 (riesgo de mercado).

    Corre antes que `fundamentals_refresh`: esa tarea todavía solo cubre
    holdings + watchlist, pero el universo recién calculado es la lista
    natural para extenderla en cuanto K3 esté validado en producción.
    """
    from ..scanner.funnel import run as run_funnel

    db = SessionLocal()
    try:
        with LogContext(job_id="universe_scan"):
            return run_funnel(db)
    finally:
        db.close()


def rebuild_all_campaigns() -> dict[str, Any]:
    """Regenera las campañas de todos los usuarios desde su histórico."""
    from ..campaigns.builder import rebuild_campaigns

    db = SessionLocal()
    try:
        totals = {"users": 0, "campaigns": 0, "cycles": 0}
        for user in db.query(User).all():
            with LogContext(job_id="rebuild_campaigns", user_id=user.id):
                result = rebuild_campaigns(db, user.id)
            totals["users"] += 1
            totals["campaigns"] += result["campaigns"]
            totals["cycles"] += result["cycles"]
        return totals
    finally:
        db.close()
