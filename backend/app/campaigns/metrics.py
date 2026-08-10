"""Métricas de campaña.

Regla del dominio: nunca mostrar solo el P/L de la opción. Una covered call se
juzga por `stock + opción = campaña`, porque el riesgo principal es la caída del
subyacente, no el assignment. Todas las funciones de aquí devuelven los tres
componentes separados.

Cuando un dato no se puede calcular se devuelve `None` con su razón, nunca 0: un
retorno de 0% y un retorno desconocido llevan a decisiones distintas.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..models import Campaign, CampaignStatus, CycleStatus


def _days_between(start: Optional[datetime], end: Optional[datetime]) -> Optional[int]:
    if start is None:
        return None
    finish = end or datetime.now(start.tzinfo or timezone.utc)
    return max(1, (finish.date() - start.date()).days)


def campaign_capital(campaign: Campaign) -> Optional[float]:
    """Capital comprometido en las acciones de la campaña."""
    if campaign.stock_cost_basis is None:
        return None
    shares = campaign.shares_peak or campaign.shares or 0.0
    if shares <= 0:
        return None
    return round(campaign.stock_cost_basis * shares, 2)


def campaign_summary(campaign: Campaign, current_price: Optional[float] = None) -> dict[str, Any]:
    """Resumen con stock, opciones y total siempre separados."""
    stock_pnl = campaign.stock_realized_pnl
    option_pnl = campaign.option_realized_pnl or 0.0
    option_open = campaign.option_open_premium or 0.0
    dividends = campaign.dividends_total or 0.0
    commissions = campaign.commissions_total or 0.0

    unrealized: Optional[float] = None
    if current_price is not None and campaign.shares > 0 and campaign.stock_cost_basis is not None:
        unrealized = round((current_price - campaign.stock_cost_basis) * campaign.shares, 2)

    if stock_pnl is None:
        total_realized = None
        total_reason = "costo base desconocido: el histórico no cubre la compra original"
    else:
        total_realized = round(stock_pnl + option_pnl + dividends - commissions, 2)
        total_reason = None

    capital = campaign_capital(campaign)
    days = campaign.days_deployed or _days_between(campaign.opened_at, campaign.closed_at)

    return_pct: Optional[float] = None
    annualized: Optional[float] = None
    if total_realized is not None and capital:
        return_pct = round(total_realized / capital * 100, 2)
        if days:
            annualized = round(return_pct * 365 / days, 2)

    premium_per_day: Optional[float] = None
    if days and (option_pnl or option_open):
        premium_per_day = round((option_pnl + option_open) / days, 4)

    return {
        "capital": capital,
        "days_deployed": days,
        "stock_realized_pnl": stock_pnl,
        "stock_unrealized_pnl": unrealized,
        "option_realized_pnl": round(option_pnl, 2),
        "option_open_premium": round(option_open, 2),
        "dividends": round(dividends, 2),
        "commissions": round(commissions, 2),
        "total_realized_pnl": total_realized,
        "total_realized_pnl_reason": total_reason,
        "mark_to_market_pnl": (
            round(total_realized + unrealized, 2)
            if total_realized is not None and unrealized is not None
            else None
        ),
        "return_pct": return_pct,
        "annualized_return_pct": annualized,
        "annualized_is_portfolio_return": False,
        "premium_per_day": premium_per_day,
    }


def cycle_summary(cycle: Any, current_ask: Optional[float] = None) -> dict[str, Any]:
    """Estado de un ciclo, con el take profit evaluado contra el ASK.

    Se usa el ask y no `last` porque recomprar exige pagar el ask: un `last` que
    ya no está disponible produce señales que no se pueden ejecutar.
    """
    from ..options_math.ticks import captured_pct

    captured = captured_pct(cycle.entry_premium, current_ask) if current_ask is not None else None

    if cycle.status != CycleStatus.OPEN:
        gross = cycle.gross_premium or 0.0
        realized_captured = (
            round((1 - (cycle.closing_cost or 0.0) / gross) * 100, 2) if gross else None
        )
    else:
        realized_captured = None

    days_open = _days_between(cycle.opened_at, cycle.closed_at)
    dte = None
    if cycle.expiration is not None and cycle.status == CycleStatus.OPEN:
        dte = (cycle.expiration.date() - datetime.now(cycle.expiration.tzinfo).date()).days

    return {
        "cycle_num": cycle.cycle_num,
        "status": cycle.status.value if hasattr(cycle.status, "value") else cycle.status,
        "ticker": cycle.ticker,
        "strike": cycle.strike,
        "contracts": cycle.contracts,
        "expiration": cycle.expiration.isoformat() if cycle.expiration else None,
        "opened_at": cycle.opened_at.isoformat() if cycle.opened_at else None,
        "closed_at": cycle.closed_at.isoformat() if cycle.closed_at else None,
        "dte": dte,
        "days_open": days_open,
        "entry_premium": cycle.entry_premium,
        "exit_premium": cycle.exit_premium,
        "gross_premium": cycle.gross_premium,
        "closing_cost": cycle.closing_cost,
        "commissions": cycle.commissions,
        "realized_pnl": cycle.realized_pnl,
        "open_premium": cycle.open_premium,
        "premium_source": cycle.premium_source,
        "tp70_price": cycle.tp70_price,
        "tp75_price": cycle.tp75_price,
        "tp80_price": cycle.tp80_price,
        "current_ask": current_ask,
        "captured_pct": captured,
        "realized_captured_pct": realized_captured,
        # La señal se evalúa sobre el ask; sin ask no hay señal, no una señal falsa.
        "tp80_reached": bool(
            current_ask is not None and cycle.tp80_price is not None and current_ask <= cycle.tp80_price
        ),
        "tp75_reached": bool(
            current_ask is not None and cycle.tp75_price is not None and current_ask <= cycle.tp75_price
        ),
    }


def portfolio_rollup(campaigns: list[Campaign]) -> dict[str, Any]:
    open_campaigns = [c for c in campaigns if c.status != CampaignStatus.CLOSED]
    closed = [c for c in campaigns if c.status == CampaignStatus.CLOSED]

    def _sum(rows: list[Campaign], attr: str) -> float:
        return round(sum(float(getattr(r, attr) or 0.0) for r in rows), 2)

    unknown_basis = [c.ticker for c in campaigns if c.stock_realized_pnl is None]
    capital_deployed = round(
        sum(v for v in (campaign_capital(c) for c in open_campaigns) if v is not None), 2
    )

    return {
        "open_campaigns": len(open_campaigns),
        "closed_campaigns": len(closed),
        "capital_deployed": capital_deployed,
        "stock_realized_pnl": _sum(campaigns, "stock_realized_pnl"),
        "option_realized_pnl": _sum(campaigns, "option_realized_pnl"),
        "option_open_premium": _sum(campaigns, "option_open_premium"),
        "dividends": _sum(campaigns, "dividends_total"),
        "commissions": _sum(campaigns, "commissions_total"),
        "total_realized_pnl": _sum(campaigns, "total_pnl"),
        # Las campañas sin costo base quedan fuera de los totales de acciones:
        # sumarlas como 0 inflaría la ganancia.
        "campaigns_with_unknown_cost_basis": unknown_basis,
    }
