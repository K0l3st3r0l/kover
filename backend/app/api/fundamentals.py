"""Fundamentales por instrumento, trazables al filing de origen."""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..fundamentals.profiles import PROFILE_LABEL
from ..fundamentals.service import refresh_fundamentals
from ..logging_config import get_logger
from ..models import Instrument, User
from ..models.fundamentals import (
    FinancialFact,
    FundamentalProfile,
    FundamentalSnapshot,
    RiskFlag,
    SecFiling,
)
from ..providers.base import ProviderError
from ..utils.auth import get_current_user

router = APIRouter()
logger = get_logger(__name__)

SEC_FILING_INDEX = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"


def _instrument_or_404(db: Session, symbol: str) -> Instrument:
    instrument = db.query(Instrument).filter(Instrument.symbol == symbol.upper()).first()
    if instrument is None:
        raise HTTPException(
            status_code=404,
            detail=f"{symbol.upper()} no tiene fundamentales cargados. Usa POST /api/instruments/{symbol.upper()}/fundamentals/refresh",
        )
    return instrument


def _snapshot_payload(snapshot: FundamentalSnapshot, filing: Optional[SecFiling]) -> dict[str, Any]:
    try:
        profile = FundamentalProfile(snapshot.profile)
        profile_label = PROFILE_LABEL[profile]
    except (ValueError, KeyError):
        profile_label = snapshot.profile

    return {
        "as_of_date": snapshot.as_of_date.isoformat() if snapshot.as_of_date else None,
        "accepted_at": snapshot.accepted_at.isoformat() if snapshot.accepted_at else None,
        "profile": snapshot.profile,
        "profile_label": profile_label,
        "score_status": snapshot.score_status,
        "financial_safety_score": snapshot.financial_safety_score,
        "metrics": {
            "revenue_ttm": snapshot.revenue_ttm,
            "revenue_growth_yoy": snapshot.revenue_growth_yoy,
            "gross_profit_ttm": snapshot.gross_profit_ttm,
            "operating_income_ttm": snapshot.operating_income_ttm,
            "net_income_ttm": snapshot.net_income_ttm,
            "operating_margin": snapshot.operating_margin,
            "cash": snapshot.cash,
            "current_assets": snapshot.current_assets,
            "current_liabilities": snapshot.current_liabilities,
            "total_assets": snapshot.total_assets,
            "total_liabilities": snapshot.total_liabilities,
            "stockholders_equity": snapshot.stockholders_equity,
            "total_debt": snapshot.total_debt,
            "net_debt": snapshot.net_debt,
            "operating_cf_ttm": snapshot.operating_cf_ttm,
            "capex_ttm": snapshot.capex_ttm,
            "fcf_ttm": snapshot.fcf_ttm,
            "fcf_margin": snapshot.fcf_margin,
            "current_ratio": snapshot.current_ratio,
            "debt_to_equity": snapshot.debt_to_equity,
            "shares_outstanding": snapshot.shares_outstanding,
            "dilution_yoy": snapshot.dilution_yoy,
            "cash_runway_quarters": snapshot.cash_runway_quarters,
        },
        # Por qué falta lo que falta. Un hueco explicado no es lo mismo que un cero.
        "missing_metrics": snapshot.missing_metrics or {},
        "score_breakdown": snapshot.components or {},
        "source_filing": (
            {
                "form": filing.form,
                "filing_date": filing.filing_date.isoformat(),
                "accepted_at": filing.accepted_at.isoformat(),
                "accession_no": filing.accession_no,
            }
            if filing
            else None
        ),
    }


@router.get("/{symbol}/fundamentals")
async def get_fundamentals(
    symbol: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instrument = _instrument_or_404(db, symbol)
    snapshot = (
        db.query(FundamentalSnapshot)
        .filter(FundamentalSnapshot.instrument_id == instrument.id)
        .order_by(FundamentalSnapshot.as_of_date.desc())
        .first()
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"{instrument.symbol} no tiene snapshots todavía")

    filing = (
        db.query(SecFiling).filter(SecFiling.id == snapshot.source_filing_id).first()
        if snapshot.source_filing_id
        else None
    )
    flags = (
        db.query(RiskFlag)
        .filter(RiskFlag.instrument_id == instrument.id, RiskFlag.resolved_at.is_(None))
        .all()
    )

    return {
        "symbol": instrument.symbol,
        "name": instrument.name,
        "cik": instrument.sec_cik,
        "sec_url": SEC_FILING_INDEX.format(cik=instrument.sec_cik) if instrument.sec_cik else None,
        **_snapshot_payload(snapshot, filing),
        "risk_flags": [
            {
                "flag": f.flag,
                "severity": f.severity,
                "origin": f.origin,
                "section": f.section,
                "text_excerpt": f.text_excerpt,
                "detail": f.detail,
                "detected_at": f.detected_at.isoformat() if f.detected_at else None,
            }
            for f in flags
        ],
        "has_reject_flag": any(f.severity == "REJECT" for f in flags),
    }


@router.get("/{symbol}/fundamentals/history")
async def get_fundamentals_history(
    symbol: str,
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Snapshots históricos. Nunca se sobrescriben: son la base del backtest."""
    instrument = _instrument_or_404(db, symbol)
    snapshots = (
        db.query(FundamentalSnapshot)
        .filter(FundamentalSnapshot.instrument_id == instrument.id)
        .order_by(FundamentalSnapshot.as_of_date.desc())
        .limit(limit)
        .all()
    )
    return {
        "symbol": instrument.symbol,
        "snapshots": [
            {
                "as_of_date": s.as_of_date.isoformat(),
                "accepted_at": s.accepted_at.isoformat() if s.accepted_at else None,
                "profile": s.profile,
                "score_status": s.score_status,
                "financial_safety_score": s.financial_safety_score,
                "revenue_ttm": s.revenue_ttm,
                "fcf_ttm": s.fcf_ttm,
                "cash": s.cash,
                "cash_runway_quarters": s.cash_runway_quarters,
                "shares_outstanding": s.shares_outstanding,
            }
            for s in snapshots
        ],
    }


@router.get("/{symbol}/filings")
async def get_filings(
    symbol: str,
    form: Optional[str] = None,
    limit: int = Query(40, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instrument = _instrument_or_404(db, symbol)
    query = db.query(SecFiling).filter(SecFiling.instrument_id == instrument.id)
    if form:
        query = query.filter(SecFiling.form == form.upper())
    filings = query.order_by(SecFiling.accepted_at.desc()).limit(limit).all()

    base = f"https://www.sec.gov/Archives/edgar/data/{int(instrument.sec_cik)}" if instrument.sec_cik else None
    return {
        "symbol": instrument.symbol,
        "filings": [
            {
                "accession_no": f.accession_no,
                "form": f.form,
                "filing_date": f.filing_date.isoformat(),
                "accepted_at": f.accepted_at.isoformat(),
                "period_end": f.period_end.isoformat() if f.period_end else None,
                "url": (
                    f"{base}/{f.accession_no.replace('-', '')}/{f.primary_doc}"
                    if base and f.primary_doc
                    else None
                ),
            }
            for f in filings
        ],
    }


@router.get("/{symbol}/risk-flags")
async def get_risk_flags(
    symbol: str,
    include_resolved: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    instrument = _instrument_or_404(db, symbol)
    query = db.query(RiskFlag).filter(RiskFlag.instrument_id == instrument.id)
    if not include_resolved:
        query = query.filter(RiskFlag.resolved_at.is_(None))
    flags = query.order_by(RiskFlag.detected_at.desc()).all()
    return {
        "symbol": instrument.symbol,
        "flags": [
            {
                "flag": f.flag,
                "severity": f.severity,
                "origin": f.origin,
                "section": f.section,
                "text_excerpt": f.text_excerpt,
                "detail": f.detail,
                "detected_at": f.detected_at.isoformat() if f.detected_at else None,
                "resolved_at": f.resolved_at.isoformat() if f.resolved_at else None,
            }
            for f in flags
        ],
    }


@router.get("/{symbol}/facts")
async def get_facts(
    symbol: str,
    metric: str = Query(..., description="métrica canónica, ej. revenue"),
    limit: int = Query(40, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Serie cruda de una métrica, con el tag XBRL de origen intacto."""
    instrument = _instrument_or_404(db, symbol)
    rows = (
        db.query(FinancialFact)
        .filter(FinancialFact.instrument_id == instrument.id, FinancialFact.metric == metric)
        .order_by(FinancialFact.period_end.desc())
        .limit(limit)
        .all()
    )
    return {
        "symbol": instrument.symbol,
        "metric": metric,
        "facts": [
            {
                "value": r.value,
                "unit": r.unit,
                "source_tag": r.source_tag,
                "form": r.form,
                "period_start": r.period_start.isoformat() if r.period_start else None,
                "period_end": r.period_end.isoformat() if r.period_end else None,
                "filing_date": r.filing_date.isoformat() if r.filing_date else None,
                "accession_no": r.accession_no,
            }
            for r in rows
        ],
    }


@router.post("/{symbol}/fundamentals/refresh")
async def refresh(
    symbol: str,
    scan_text: bool = Query(True, description="revisar el texto de los filings buscando riesgos"),
    recompute: bool = Query(False, description="recalcular el snapshot de hoy si cambió la lógica del score"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return refresh_fundamentals(db, symbol, scan_text=scan_text, recompute=recompute)
    except ProviderError as exc:
        db.rollback()
        # 502 y no 500: el fallo es del proveedor externo, no de la aplicación.
        raise HTTPException(status_code=502, detail=str(exc))
