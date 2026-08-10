"""Salud y frescura de los datos.

Un scanner nunca debe rankear datos viejos en silencio como si fueran actuales.
Este endpoint es el que hace visible esa diferencia.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..jobs import scheduler as scheduler_module
from ..jobs import tasks
from ..models import DataProvenance, ProviderStatus, User
from ..utils.auth import get_current_user

router = APIRouter()

# Cuánto puede tener un dato antes de considerarse viejo, por tipo.
FRESHNESS_LIMITS = {
    "stock_quote": timedelta(minutes=20),
    "option_quote": timedelta(minutes=20),
    "option_chain": timedelta(hours=1),
    "fundamental": timedelta(days=2),
    "corporate_event": timedelta(hours=12),
    "broker_sync": timedelta(days=1),
}
DEFAULT_LIMIT = timedelta(hours=6)


def _age(as_of: Optional[datetime]) -> Optional[float]:
    if as_of is None:
        return None
    now = datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    return (now - as_of).total_seconds()


@router.get("")
async def get_data_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    providers = []
    for row in db.query(ProviderStatus).order_by(ProviderStatus.provider).all():
        providers.append(
            {
                "provider": row.provider,
                "status": row.status,
                "last_success": row.last_success.isoformat() if row.last_success else None,
                "last_attempt": row.last_attempt.isoformat() if row.last_attempt else None,
                "last_error": row.last_error,
                "last_error_at": row.last_error_at.isoformat() if row.last_error_at else None,
                "consecutive_errors": row.consecutive_errors or 0,
                "seconds_since_success": _age(row.last_success),
                "detail": row.detail,
            }
        )

    # Última procedencia registrada por tipo de dato.
    freshness = []
    seen: set[str] = set()
    recent = (
        db.query(DataProvenance)
        .order_by(DataProvenance.fetched_at.desc())
        .limit(500)
        .all()
    )
    for row in recent:
        if row.entity_type in seen:
            continue
        seen.add(row.entity_type)
        age = _age(row.as_of)
        limit = FRESHNESS_LIMITS.get(row.entity_type, DEFAULT_LIMIT)
        freshness.append(
            {
                "entity_type": row.entity_type,
                "entity_key": row.entity_key,
                "source": row.source,
                "as_of": row.as_of.isoformat() if row.as_of else None,
                "age_seconds": age,
                "limit_seconds": limit.total_seconds(),
                "is_stale": bool(age is not None and age > limit.total_seconds()),
            }
        )

    degraded = [p for p in providers if p["status"] not in ("OK", "UNKNOWN")]
    stale = [f for f in freshness if f["is_stale"]]

    return {
        "status": "DEGRADED" if (degraded or stale) else "OK",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "providers": providers,
        "freshness": freshness,
        "scheduler": {"running": bool(scheduler_module.get_jobs()), "jobs": scheduler_module.get_jobs()},
        "issues": {
            "degraded_providers": [p["provider"] for p in degraded],
            "stale_entities": [f["entity_type"] for f in stale],
        },
    }


@router.post("/check")
async def run_health_check(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Fuerza un probe de los proveedores en vez de esperar al job."""
    return {"results": tasks.refresh_provider_status()}
