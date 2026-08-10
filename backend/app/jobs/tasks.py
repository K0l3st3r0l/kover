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


def refresh_provider_status() -> list[dict[str, Any]]:
    """Verifica los proveedores activos. Los de fases futuras no se prueban aún."""
    return [check_provider("yfinance", _probe_yfinance)]


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
