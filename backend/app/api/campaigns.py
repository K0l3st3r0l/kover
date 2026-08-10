"""Campañas: la vida completa de un bloque de acciones con sus calls adentro.

Las tablas son derivadas del histórico, así que aquí no hay escritura salvo el
rebuild. Ver `campaigns/builder.py`.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from ..campaigns.builder import rebuild_campaigns
from ..campaigns.metrics import campaign_summary, cycle_summary, portfolio_rollup
from ..database import get_db
from ..logging_config import get_logger
from ..market.market_data import MarketDataService
from ..models import Campaign, CampaignStatus, User
from ..utils.auth import get_current_user

router = APIRouter()
logger = get_logger(__name__)


def _prices_for(campaigns: list[Campaign]) -> dict[str, Optional[float]]:
    tickers = sorted({c.ticker for c in campaigns if c.shares and c.shares > 0})
    if not tickers:
        return {}
    try:
        return MarketDataService.get_multiple_prices(tickers)
    except Exception as exc:
        # Un proveedor caído no puede tumbar la vista del portfolio: se devuelven
        # las campañas sin precio y el front muestra el P/L realizado solamente.
        logger.warning("precios no disponibles", extra={"error": str(exc)[:300]})
        return {}


def _serialize(campaign: Campaign, price: Optional[float], with_cycles: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": campaign.id,
        "ticker": campaign.ticker,
        "status": campaign.status.value,
        "close_reason": campaign.close_reason.value if campaign.close_reason else None,
        "shares": campaign.shares,
        "shares_peak": campaign.shares_peak,
        "stock_cost_basis": campaign.stock_cost_basis,
        "cost_basis_status": campaign.cost_basis_status,
        "opened_at": campaign.opened_at.isoformat() if campaign.opened_at else None,
        "closed_at": campaign.closed_at.isoformat() if campaign.closed_at else None,
        "current_price": price,
        "cycles_count": len(campaign.cycles),
        "metrics": campaign_summary(campaign, price),
    }
    if with_cycles:
        payload["cycles"] = [cycle_summary(c) for c in campaign.cycles]
    return payload


@router.get("")
async def list_campaigns(
    status: Optional[str] = Query(None, description="OPEN | CLOSED | estado exacto"),
    ticker: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        db.query(Campaign)
        .options(joinedload(Campaign.cycles))
        .filter(Campaign.user_id == current_user.id)
    )
    if ticker:
        query = query.filter(Campaign.ticker == ticker.upper())
    if status:
        upper = status.upper()
        if upper == "OPEN":
            query = query.filter(Campaign.status != CampaignStatus.CLOSED)
        elif upper == "CLOSED":
            query = query.filter(Campaign.status == CampaignStatus.CLOSED)
        else:
            query = query.filter(Campaign.status == upper)

    campaigns = query.order_by(Campaign.opened_at.desc()).all()
    prices = _prices_for(campaigns)

    return {
        "campaigns": [_serialize(c, prices.get(c.ticker), False) for c in campaigns],
        "summary": portfolio_rollup(campaigns),
        "price_source": "yfinance" if prices else None,
    }


@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    campaign = (
        db.query(Campaign)
        .options(joinedload(Campaign.cycles))
        .filter(Campaign.id == campaign_id, Campaign.user_id == current_user.id)
        .first()
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")

    price = None
    if campaign.shares and campaign.shares > 0:
        try:
            price = MarketDataService.get_current_price(campaign.ticker)
        except Exception as exc:
            logger.warning(
                "precio no disponible",
                extra={"ticker": campaign.ticker, "error": str(exc)[:300]},
            )

    return _serialize(campaign, price, True)


@router.post("/rebuild")
async def rebuild(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Regenera las campañas del usuario desde sus transacciones.

    Es idempotente y no destructivo: borra solo las filas derivadas y las vuelve
    a construir desde el histórico, que es la fuente de verdad.
    """
    result = rebuild_campaigns(db, current_user.id)
    return {"status": "ok", **result}
