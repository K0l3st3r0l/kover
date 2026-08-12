"""Universo optionable US$10–20 y riesgo de mercado — K3 del scanner.

Ver `docs/COVERED_CALL_SCANNER_PLAN.md` §6 y §26. Todavía sin cadenas de
opciones con precio (eso es K4): esto responde "¿qué acciones califican para
que el scanner las evalúe después, y por qué las demás no?".
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..logging_config import get_logger
from ..models import Instrument, MarketRiskSnapshot, User
from ..models.fundamentals import FundamentalSnapshot
from ..scanner import funnel
from ..utils.auth import get_current_user

router = APIRouter()
logger = get_logger(__name__)


def _run_in_background() -> None:
    db = SessionLocal()
    try:
        funnel.run(db)
    except Exception as exc:
        logger.warning("universe scan en background falló", extra={"error": str(exc)[:300]})
    finally:
        db.close()


@router.post("/universe/run")
async def trigger_universe_run(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if funnel.is_running():
        return {"status": "ALREADY_RUNNING"}
    background_tasks.add_task(_run_in_background)
    return {"status": "STARTED"}


@router.get("/universe/status")
async def universe_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return {"running": funnel.is_running(), "last_run": funnel.get_last_run(db)}


@router.get("/universe")
async def list_universe(
    stage: Optional[str] = Query(None, description="PRICE_RANGE | LIQUIDITY | OPTIONABLE"),
    qualified_only: bool = Query(False, description="solo instrumentos que pasaron todas las etapas de K3"),
    search: Optional[str] = None,
    limit: int = Query(500, le=2000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    query = db.query(Instrument).filter(Instrument.universe_stage.isnot(None))
    if stage:
        query = query.filter(Instrument.universe_stage == stage.upper())
    if qualified_only:
        query = query.filter(
            Instrument.universe_stage == "OPTIONABLE",
            Instrument.universe_rejected_reason.is_(None),
        )
    if search:
        query = query.filter(Instrument.symbol.ilike(f"%{search.upper()}%"))
    instruments = query.order_by(Instrument.symbol).limit(limit).all()

    ids = [i.id for i in instruments]
    latest_risk: dict[int, MarketRiskSnapshot] = {}
    latest_fundamentals: dict[int, FundamentalSnapshot] = {}
    if ids:
        risk_rows = (
            db.query(MarketRiskSnapshot)
            .filter(MarketRiskSnapshot.instrument_id.in_(ids))
            .order_by(MarketRiskSnapshot.instrument_id, MarketRiskSnapshot.as_of_date.desc())
            .all()
        )
        for row in risk_rows:
            latest_risk.setdefault(row.instrument_id, row)

        fund_rows = (
            db.query(FundamentalSnapshot)
            .filter(FundamentalSnapshot.instrument_id.in_(ids))
            .order_by(FundamentalSnapshot.instrument_id, FundamentalSnapshot.as_of_date.desc())
            .all()
        )
        for row in fund_rows:
            latest_fundamentals.setdefault(row.instrument_id, row)

    items = []
    for instrument in instruments:
        risk = latest_risk.get(instrument.id)
        fund = latest_fundamentals.get(instrument.id)
        items.append(
            {
                "symbol": instrument.symbol,
                "name": instrument.name,
                "exchange": instrument.exchange,
                "is_optionable": instrument.is_optionable,
                "universe_stage": instrument.universe_stage,
                "rejected_reason": instrument.universe_rejected_reason,
                "qualified": instrument.universe_stage == "OPTIONABLE" and instrument.universe_rejected_reason is None,
                "checked_at": instrument.universe_checked_at.isoformat() if instrument.universe_checked_at else None,
                "price": float(risk.price) if risk and risk.price is not None else None,
                "avg_dollar_volume_20": float(risk.avg_dollar_volume_20) if risk and risk.avg_dollar_volume_20 is not None else None,
                "market_safety_score": float(risk.market_safety_score) if risk and risk.market_safety_score is not None else None,
                "market_risk_as_of": risk.as_of_date.isoformat() if risk else None,
                "financial_safety_score": float(fund.financial_safety_score) if fund and fund.financial_safety_score is not None else None,
                "financial_score_status": fund.score_status if fund else "PENDING",
            }
        )

    return {
        "last_run": funnel.get_last_run(db),
        "count": len(items),
        "instruments": items,
    }


@router.get("/universe/{symbol}")
async def get_universe_detail(
    symbol: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    instrument = db.query(Instrument).filter(Instrument.symbol == symbol.upper()).first()
    if instrument is None or instrument.universe_stage is None:
        raise HTTPException(status_code=404, detail=f"{symbol.upper()} no está en el universo actual")

    risk = (
        db.query(MarketRiskSnapshot)
        .filter(MarketRiskSnapshot.instrument_id == instrument.id)
        .order_by(MarketRiskSnapshot.as_of_date.desc())
        .first()
    )
    fund = (
        db.query(FundamentalSnapshot)
        .filter(FundamentalSnapshot.instrument_id == instrument.id)
        .order_by(FundamentalSnapshot.as_of_date.desc())
        .first()
    )

    return {
        "symbol": instrument.symbol,
        "name": instrument.name,
        "exchange": instrument.exchange,
        "is_optionable": instrument.is_optionable,
        "universe_stage": instrument.universe_stage,
        "rejected_reason": instrument.universe_rejected_reason,
        "checked_at": instrument.universe_checked_at.isoformat() if instrument.universe_checked_at else None,
        "market_risk": (
            {
                "as_of_date": risk.as_of_date.isoformat(),
                "price": float(risk.price) if risk.price is not None else None,
                "avg_daily_volume_20": risk.avg_daily_volume_20,
                "avg_dollar_volume_20": float(risk.avg_dollar_volume_20) if risk.avg_dollar_volume_20 is not None else None,
                "atr14": float(risk.atr14) if risk.atr14 is not None else None,
                "atr_pct": float(risk.atr_pct) if risk.atr_pct is not None else None,
                "realized_vol_20": float(risk.realized_vol_20) if risk.realized_vol_20 is not None else None,
                "realized_vol_60": float(risk.realized_vol_60) if risk.realized_vol_60 is not None else None,
                "return_5d": float(risk.return_5d) if risk.return_5d is not None else None,
                "return_20d": float(risk.return_20d) if risk.return_20d is not None else None,
                "max_drawdown_30d": float(risk.max_drawdown_30d) if risk.max_drawdown_30d is not None else None,
                "max_drawdown_90d": float(risk.max_drawdown_90d) if risk.max_drawdown_90d is not None else None,
                "gap_frequency": float(risk.gap_frequency) if risk.gap_frequency is not None else None,
                "worst_day_20d": float(risk.worst_day_20d) if risk.worst_day_20d is not None else None,
                "market_safety_score": float(risk.market_safety_score) if risk.market_safety_score is not None else None,
                "components": risk.components,
                "bars_used": risk.bars_used,
            }
            if risk
            else None
        ),
        "fundamentals": (
            {
                "as_of_date": fund.as_of_date.isoformat(),
                "profile": fund.profile,
                "score_status": fund.score_status,
                "financial_safety_score": float(fund.financial_safety_score) if fund.financial_safety_score is not None else None,
            }
            if fund
            else {"score_status": "PENDING", "note": f"usa POST /api/instruments/{instrument.symbol}/fundamentals/refresh"}
        ),
    }
