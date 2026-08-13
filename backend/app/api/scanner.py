"""Universo optionable US$10–20 y riesgo de mercado — K3 del scanner.

Ver `docs/COVERED_CALL_SCANNER_PLAN.md` §6 y §26. Todavía sin cadenas de
opciones con precio (eso es K4): esto responde "¿qué acciones califican para
que el scanner las evalúe después, y por qué las demás no?".
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..logging_config import get_logger
from ..models import CoveredCallCandidate, Instrument, MarketRiskSnapshot, Stock, User
from ..models.fundamentals import FundamentalSnapshot
from ..providers.base import ProviderError
from ..providers.cboe_chains import CboeChainsProvider
from ..scanner import cc_scan, funnel
from ..scanner.covered_calls import ChainFilter, evaluate_chain
from ..scanner.holdings import evaluate_for_holding, rank_for_cycle, resolve_cost_basis
from ..scanner.cc_scan import PICK_PROFILE_PREFIX
from ..scanner.scoring import PROFILES, evaluate_gate
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


# ─── K4: scanner de covered calls ─────────────────────────────────────────────


def _run_cc_scan_in_background(symbols: Optional[list[str]] = None) -> None:
    db = SessionLocal()
    try:
        cc_scan.run(db, symbols=symbols)
    except Exception as exc:
        logger.warning("scan de covered calls en background falló", extra={"error": str(exc)[:300]})
    finally:
        db.close()


@router.post("/covered-calls/run")
async def trigger_covered_call_scan(
    background_tasks: BackgroundTasks,
    symbols: Optional[str] = Query(None, description="lista separada por comas; por defecto, el universo calificado"),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if cc_scan.is_running():
        return {"status": "ALREADY_RUNNING"}
    lista = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
    background_tasks.add_task(_run_cc_scan_in_background, lista)
    return {"status": "STARTED", "symbols": lista or "universo calificado"}


@router.get("/covered-calls/status")
async def covered_call_scan_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return {"running": cc_scan.is_running(), "last_run": cc_scan.get_last_run(db)}


@router.get("/covered-calls/profiles")
async def list_profiles(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Los tres perfiles del plan, con sus umbrales, para que la UI no los duplique."""
    return {
        "profiles": [
            {
                "name": p.name,
                "min_financial_safety": p.min_financial_safety,
                "min_market_safety": p.min_market_safety,
                "max_spread_pct": p.max_spread_pct,
                "delta_low": p.delta_low,
                "delta_high": p.delta_high,
                "dte_low": p.dte_low,
                "dte_high": p.dte_high,
            }
            for p in PROFILES.values()
        ]
    }


@router.get("/covered-calls")
async def list_covered_call_candidates(
    pick_type: str = Query("BALANCED", description="BALANCED | PREMIUM | UPSIDE"),
    profile: Optional[str] = Query(None, description="CONSERVADOR | BALANCEADO | AGRESIVO"),
    include_rejected: bool = Query(False, description="incluir los que no pasan la puerta, marcados"),
    min_financial_safety: Optional[float] = Query(None, ge=0, le=100),
    min_market_safety: Optional[float] = Query(None, ge=0, le=100),
    max_spread_pct: Optional[float] = Query(None, gt=0, description="fracción, no porcentaje: 0.12 = 12%"),
    min_liquidity: Optional[float] = Query(None, ge=0, le=100),
    max_dte: Optional[int] = Query(None, ge=1),
    order_by: str = Query("final_score", description="final_score | cc_opportunity_score | annualized_premium_yield | annualized_return_if_assigned | liquidity_score"),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Candidatos de la última corrida, filtrables.

    Los filtros de seguridad son opcionales y por defecto vienen apagados: el
    usuario decide su umbral. Pero las filas exponen `financial_safety_score`
    en `null` cuando no hay snapshot, nunca en 0 — filtrar por `>= 45` no puede
    dejar pasar un papel sin fundamentales solo porque su ausencia se veía como
    cero. Ver la regla en wiki/projects/kover/decisions/fundamentales-sec-edgar.md.
    """
    columnas_validas = {
        "final_score": CoveredCallCandidate.final_score,
        "cc_opportunity_score": CoveredCallCandidate.cc_opportunity_score,
        "annualized_premium_yield": CoveredCallCandidate.annualized_premium_yield,
        "annualized_return_if_assigned": CoveredCallCandidate.annualized_return_if_assigned,
        "liquidity_score": CoveredCallCandidate.liquidity_score,
    }
    perfil = None
    pick = pick_type.upper()
    if profile:
        perfil = PROFILES.get(profile.upper())
        if perfil is None:
            raise HTTPException(status_code=400, detail=f"perfil inválido: {profile}")
        # Con perfil se lee el pick elegido DENTRO de ese perfil, no el
        # balanceado global: el contrato que maximiza el score suele quedar
        # fuera de la banda de delta conservadora, y filtrarlo después dejaría
        # al papel afuera aunque tuviera otro strike que sí califica.
        if pick_type.upper() == "BALANCED":
            pick = f"{PICK_PROFILE_PREFIX}{perfil.name}"
    if order_by not in columnas_validas:
        raise HTTPException(status_code=400, detail=f"order_by inválido: {order_by}")

    q = (
        db.query(CoveredCallCandidate, Instrument)
        .join(Instrument, Instrument.id == CoveredCallCandidate.instrument_id)
        .filter(CoveredCallCandidate.pick_type == pick)
    )
    if min_financial_safety is not None:
        q = q.filter(CoveredCallCandidate.financial_safety_score >= min_financial_safety)
    if min_market_safety is not None:
        q = q.filter(CoveredCallCandidate.market_safety_score >= min_market_safety)
    if max_spread_pct is not None:
        q = q.filter(CoveredCallCandidate.spread_pct <= max_spread_pct)
    if min_liquidity is not None:
        q = q.filter(CoveredCallCandidate.liquidity_score >= min_liquidity)
    if max_dte is not None:
        q = q.filter(CoveredCallCandidate.dte <= max_dte)

    filas = q.order_by(columnas_validas[order_by].desc().nullslast()).limit(limit).all()

    def _f(value):
        return float(value) if value is not None else None

    # La puerta se evalúa acá y no en el scan: depende del perfil que elija el
    # usuario, y guardarla obligaría a rescanear para cambiar de perfil cuando
    # lo único que cambia es un umbral. Sin perfil no hay puerta — la lista es
    # el ranking crudo de K4.
    evaluados = []
    for c, inst in filas:
        pasa, razones = (True, [])
        if perfil is not None:
            pasa, razones = evaluate_gate(
                perfil,
                _f(c.financial_safety_score),
                _f(c.market_safety_score),
                _f(c.spread_pct),
                _f(c.delta),
                c.dte,
            )
        if perfil is not None and not pasa and not include_rejected:
            continue
        evaluados.append((c, inst, pasa, razones))

    return {
        "pick_type": pick,
        "profile": perfil.name if perfil else None,
        "count": len(evaluados),
        "candidates": [
            {
                "symbol": inst.symbol,
                "gate_passed": pasa,
                "gate_reasons": razones,
                "cc_opportunity_score": _f(c.cc_opportunity_score),
                "cc_score_components": c.cc_score_components,
                "final_score": _f(c.final_score),
                "final_score_status": c.final_score_status,
                "name": inst.name,
                "occ_symbol": c.occ_symbol,
                "expiration": c.expiration.isoformat(),
                "strike": _f(c.strike),
                "dte": c.dte,
                "underlying_price": _f(c.underlying_price),
                "stock_ask": _f(c.stock_ask),
                "call_bid": _f(c.call_bid),
                "call_ask": _f(c.call_ask),
                "spread_pct": _f(c.spread_pct),
                "delta": _f(c.delta),
                "implied_volatility": _f(c.implied_volatility),
                "volume": c.volume,
                "open_interest": c.open_interest,
                "premium_total": _f(c.premium_total),
                "premium_yield": _f(c.premium_yield),
                "annualized_premium_yield": _f(c.annualized_premium_yield),
                "return_if_assigned": _f(c.return_if_assigned),
                "annualized_return_if_assigned": _f(c.annualized_return_if_assigned),
                "downside_protection": _f(c.downside_protection),
                "breakeven": _f(c.breakeven),
                "moneyness": _f(c.moneyness),
                "liquidity_score": _f(c.liquidity_score),
                "liquidity_components": c.liquidity_components,
                "financial_safety_score": _f(c.financial_safety_score),
                "market_safety_score": _f(c.market_safety_score),
                "quote_as_of": c.quote_as_of.isoformat() if c.quote_as_of else None,
                "scanned_at": c.scanned_at.isoformat() if c.scanned_at else None,
            }
            for c, inst, pasa, razones in evaluados
        ],
    }


@router.get("/covered-calls/holdings")
async def covered_calls_for_holdings(
    min_dte: int = Query(5, ge=1),
    max_dte: int = Query(60, ge=1),
    include_loss_making: bool = Query(True, description="incluir strikes bajo el costo real, marcados"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Covered calls sobre las posiciones que el usuario YA tiene.

    En vivo contra CBOE, no desde `covered_call_candidates`: son pocas
    posiciones (una consulta por papel) y acá el usuario está por mandar una
    orden — mostrarle la cadena del último scan programado sería darle precios
    de hace horas para decidir algo que ejecuta ahora.
    """
    posiciones = (
        db.query(Stock)
        .filter(Stock.user_id == current_user.id, Stock.is_active == True, Stock.shares >= 100)
        .order_by(Stock.ticker)
        .all()
    )

    provider = CboeChainsProvider()
    filtro = ChainFilter(
        min_dte=min_dte, max_dte=max_dte,
        min_delta=0.05, max_delta=0.60,
        max_spread_pct=0.35, min_open_interest=1,
        require_otm=False,   # un strike bajo el precio puede seguir sobre el costo real
    )

    resultado = []
    errores = []
    for stock in posiciones:
        cost_basis, fuente = resolve_cost_basis(stock)
        if cost_basis is None:
            errores.append({"ticker": stock.ticker, "error": "sin costo base registrado"})
            continue
        try:
            quotes, underlying = provider.get_chain(stock.ticker)
        except ProviderError as exc:
            errores.append({"ticker": stock.ticker, "error": str(exc)[:200]})
            continue
        if underlying.price is None or underlying.price <= 0:
            errores.append({"ticker": stock.ticker, "error": "CBOE no reportó precio"})
            continue

        candidatos, _ = evaluate_chain(
            quotes, underlying.price, date.today(), stock_ask=underlying.ask, filtro=filtro
        )
        evaluados = [
            h for h in (
                evaluate_for_holding(m, cost_basis, fuente, float(stock.shares)) for m in candidatos
            )
            if h is not None and (include_loss_making or not h.realizes_loss)
        ]

        resultado.append({
            "ticker": stock.ticker,
            "shares": float(stock.shares),
            "contracts": int(stock.shares // 100),
            "uncovered_shares": float(stock.shares) - int(stock.shares // 100) * 100,
            "cost_basis": round(cost_basis, 4),
            "cost_basis_source": fuente,
            "gross_cost": float(stock.average_cost) if stock.average_cost else None,
            "premium_collected": float(stock.total_premium_earned or 0),
            "market_price": underlying.price,
            "vs_cost_basis": round((underlying.price - cost_basis) / cost_basis, 6),
            "quote_as_of": underlying.as_of.isoformat(),
            "candidates": [h.as_dict() for h in rank_for_cycle(evaluados)],
        })

    return {"positions": resultado, "errors": errores}
