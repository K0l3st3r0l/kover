"""Reconstrucción de campañas y ciclos desde el histórico de transacciones.

`campaigns` y `covered_call_cycles` son tablas derivadas, como las posiciones que
reconstruye `rebuild_positions`. Nada las escribe fuera de aquí, y se pueden
borrar y regenerar enteras. Eso permite corregir el algoritmo de agrupación sin
migraciones destructivas ni riesgo sobre el histórico importado.

Las primas salen del ledger canónico (`build_option_transaction_ledger`), no de
las columnas de `options`: es la misma fuente que usa `/api/analytics/
covered-call-cycles`, así que los dos endpoints tienen que dar el mismo número.
Si divergen, hay un bug en uno de los dos.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..logging_config import get_logger
from ..models import (
    Campaign,
    CampaignEvent,
    CampaignStatus,
    CampaignCloseReason,
    CoveredCallCycle,
    CycleStatus,
    Transaction,
    TransactionType,
)
from ..options_math.ticks import take_profit_targets
from ..services.premium_ledger import load_option_ledger
from ..utils.portfolio_metrics import OPTION_TRANSACTION_TYPES
from .state import cycle_status_from_option, detect_assignment

logger = get_logger(__name__)

STOCK_TYPES = (TransactionType.BUY_STOCK, TransactionType.SELL_STOCK)


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


# ── Planificación (pura, sin base de datos) ───────────────────────────────────

@dataclass
class CyclePlan:
    option_id: Optional[int]
    ticker: str
    strike: float
    contracts: float
    expiration: Optional[datetime]
    opened_at: Optional[datetime]
    closed_at: Optional[datetime]
    status: CycleStatus
    entry_premium: float
    exit_premium: Optional[float]
    gross_premium: float
    closing_cost: float
    commissions: float
    realized_pnl: float
    open_premium: float
    premium_source: str
    min_tick: float = 0.01


@dataclass
class SalePlan:
    transaction_id: Optional[int]
    sale_date: Optional[date]
    quantity: float
    proceeds: float
    cost_basis_price: Optional[float]
    was_assignment: bool


@dataclass
class CampaignPlan:
    ticker: str
    opened_at: datetime
    closed_at: Optional[datetime] = None
    status: CampaignStatus = CampaignStatus.STOCK_ACQUIRED
    close_reason: Optional[CampaignCloseReason] = None
    shares: float = 0.0
    shares_peak: float = 0.0
    stock_invested: Optional[float] = 0.0
    stock_cost_basis: Optional[float] = None
    cost_basis_status: str = "KNOWN"
    stock_realized_pnl: Optional[float] = 0.0
    dividends_total: float = 0.0
    stock_commissions: float = 0.0
    sales: list[SalePlan] = field(default_factory=list)
    cycles: list[CyclePlan] = field(default_factory=list)

    # Estado interno del recorrido, no persistido.
    _running_shares: float = 0.0
    _running_cost: float = 0.0


def _build_assignment_index(
    transactions: list[Any], options: list[Any]
) -> dict[int, dict[str, Any]]:
    """Marca qué ventas de acciones vienen de una call asignada.

    No se usa `Option.status`: los 3 assignments del histórico están guardados
    como EXPIRED porque el importador antiguo solo los buscaba en Corporate
    Actions, mientras que IB los reporta como trades con código `A;C`.
    """
    options_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for opt in options:
        options_by_ticker[str(opt.ticker).upper()].append(
            {
                "option_id": opt.id,
                "strike": float(opt.strike_price or 0.0),
                "contracts": float(opt.contracts or 0.0),
                "expiration": opt.expiration_date,
            }
        )

    assignments: dict[int, dict[str, Any]] = {}
    claimed_options: set[int] = set()

    for tx in transactions:
        if tx.transaction_type != TransactionType.SELL_STOCK:
            continue
        ticker = str(tx.ticker).upper()
        candidates = [
            c for c in options_by_ticker.get(ticker, [])
            if c["option_id"] not in claimed_options
        ]
        # El precio de una venta se guarda por acción; el assignment ejecuta al strike.
        match = detect_assignment(
            sale_price=float(tx.price or 0.0),
            sale_quantity=float(tx.quantity or 0.0),
            sale_date=_as_date(tx.transaction_date),
            open_cycles=candidates,
        )
        if match is not None:
            assignments[tx.id] = {
                "option_id": match.option_id,
                "strike": match.strike,
                "contracts": match.contracts,
            }
            if match.option_id is not None:
                claimed_options.add(match.option_id)

    return assignments


def _cycle_plan_from_option(
    option: Any, ledger_row: Optional[dict[str, Any]], assigned: bool
) -> CyclePlan:
    contracts = float(
        (ledger_row or {}).get("contracts") or option.contracts or 0.0
    )
    shares_covered = contracts * 100

    closing_cost = 0.0
    if option.status.value != "OPEN" and option.closing_premium is not None:
        closing_cost = round(float(option.closing_premium) * contracts * 100, 2)

    if ledger_row and ledger_row["matched"]:
        realized = float(ledger_row["realized_net"])
        open_premium = float(ledger_row["open_net"])
        commissions = float(ledger_row["commissions"])
        source = ledger_row["premium_source"]
    else:
        realized = float(option.realized_pnl or 0.0)
        open_premium = float(option.total_premium or 0.0) if option.status.value == "OPEN" else 0.0
        if option.status.value != "OPEN" and option.realized_pnl is None:
            realized = float(option.total_premium or 0.0) - closing_cost
        commissions = 0.0
        source = (ledger_row or {}).get("premium_source", "OPTION_ROW_FALLBACK")

    gross_premium = float(option.total_premium or 0.0)
    entry_premium = (gross_premium / shares_covered) if shares_covered else 0.0
    exit_premium = float(option.closing_premium) if option.closing_premium is not None else None

    status = cycle_status_from_option(
        option_status=option.status.value,
        was_assigned=assigned,
        was_rolled=bool(option.notes and "roll" in str(option.notes).lower()),
        exit_premium=exit_premium,
    )

    return CyclePlan(
        option_id=option.id,
        ticker=str(option.ticker).upper(),
        strike=float(option.strike_price or 0.0),
        contracts=contracts,
        expiration=option.expiration_date,
        opened_at=option.opened_at,
        closed_at=option.closed_at,
        status=status,
        entry_premium=round(entry_premium, 6),
        exit_premium=exit_premium,
        gross_premium=round(gross_premium, 2),
        closing_cost=closing_cost,
        commissions=round(commissions, 2),
        realized_pnl=round(realized, 2),
        open_premium=round(open_premium, 2),
        premium_source=source,
    )


def plan_campaigns(
    transactions: list[Any],
    options: list[Any],
    ledger: dict[str, Any],
) -> list[CampaignPlan]:
    """Agrupa el histórico en campañas. Función pura: no toca la base de datos."""
    ledger_by_option = {row["option_id"]: row for row in ledger["options"]}
    assignments = _build_assignment_index(transactions, options)

    ordered = sorted(
        transactions,
        key=lambda t: (t.transaction_date, t.id or 0),
    )

    plans: list[CampaignPlan] = []
    open_by_ticker: dict[str, CampaignPlan] = {}

    for tx in ordered:
        ticker = str(tx.ticker).upper()
        tt = tx.transaction_type
        qty = float(tx.quantity or 0.0)
        amount = float(tx.total_amount or 0.0)
        commission = abs(float(tx.commission or 0.0))

        if tt == TransactionType.BUY_STOCK:
            current = open_by_ticker.get(ticker)
            if current is None:
                current = CampaignPlan(ticker=ticker, opened_at=tx.transaction_date)
                open_by_ticker[ticker] = current
                plans.append(current)
            current._running_shares += qty
            current._running_cost += amount
            current.shares = current._running_shares
            current.shares_peak = max(current.shares_peak, current.shares)
            current.stock_invested = (current.stock_invested or 0.0) + amount
            current.stock_commissions += commission

        elif tt == TransactionType.SELL_STOCK:
            current = open_by_ticker.get(ticker)
            if current is None:
                # Venta sin compra que la respalde: el histórico importado empieza
                # después de la compra original. El costo base es desconocido.
                current = CampaignPlan(
                    ticker=ticker,
                    opened_at=tx.transaction_date,
                    stock_invested=None,
                    cost_basis_status="UNKNOWN_PRIOR_HISTORY",
                    stock_realized_pnl=None,
                )
                open_by_ticker[ticker] = current
                plans.append(current)

            avg_cost = (
                current._running_cost / current._running_shares
                if current._running_shares > 0
                else None
            )
            was_assignment = tx.id in assignments

            current.sales.append(
                SalePlan(
                    transaction_id=tx.id,
                    sale_date=_as_date(tx.transaction_date),
                    quantity=qty,
                    proceeds=amount,
                    cost_basis_price=avg_cost,
                    was_assignment=was_assignment,
                )
            )
            current.stock_commissions += commission

            if avg_cost is not None and current.stock_realized_pnl is not None:
                current.stock_realized_pnl += amount - qty * avg_cost
            else:
                current.stock_realized_pnl = None
                current.cost_basis_status = "UNKNOWN_PRIOR_HISTORY"

            consumed = min(qty, current._running_shares)
            current._running_shares -= consumed
            if avg_cost is not None:
                current._running_cost = max(0.0, current._running_cost - consumed * avg_cost)
            current.shares = current._running_shares

            if current._running_shares <= 1e-9:
                current.closed_at = tx.transaction_date
                current.status = CampaignStatus.CLOSED
                current.close_reason = (
                    CampaignCloseReason.ASSIGNED if was_assignment else CampaignCloseReason.STOCK_SALE
                )
                open_by_ticker.pop(ticker, None)

        elif tt == TransactionType.DIVIDEND:
            current = open_by_ticker.get(ticker)
            if current is not None:
                current.dividends_total += amount

    # Las opciones se adjuntan a la campaña del ticker cuya ventana contiene su
    # apertura. Se hace después de recorrer las acciones porque una campaña solo
    # existe cuando ya se sabe cuándo empezó y cuándo terminó.
    plans_by_ticker: dict[str, list[CampaignPlan]] = defaultdict(list)
    for plan in plans:
        plans_by_ticker[plan.ticker].append(plan)

    for option in options:
        ticker = str(option.ticker).upper()
        opened = option.opened_at
        target: Optional[CampaignPlan] = None
        for plan in plans_by_ticker.get(ticker, []):
            if opened is None or plan.opened_at is None:
                continue
            if opened < plan.opened_at:
                continue
            if plan.closed_at is not None and opened > plan.closed_at:
                continue
            target = plan  # la última que califica: la campaña vigente
        if target is None:
            # Sin campaña que la contenga (call vendida sobre acciones que el
            # histórico no alcanza a cubrir): se cuelga de la más cercana del
            # ticker para no perder la prima del total.
            candidates = plans_by_ticker.get(ticker, [])
            target = candidates[-1] if candidates else None
        if target is None:
            logger.warning(
                "opción sin campaña", extra={"ticker": ticker, "option_id": option.id}
            )
            continue

        assigned = any(
            info.get("option_id") == option.id for info in assignments.values()
        )
        target.cycles.append(
            _cycle_plan_from_option(option, ledger_by_option.get(option.id), assigned)
        )

    for plan in plans:
        plan.cycles.sort(key=lambda c: (c.opened_at or datetime.min))
        _finalize(plan)

    return plans


def _finalize(plan: CampaignPlan) -> None:
    """Cierra los números de la campaña una vez que tiene todos sus ciclos."""
    if plan.shares > 0:
        has_open_cycle = any(c.status == CycleStatus.OPEN for c in plan.cycles)
        ever_had_call = bool(plan.cycles)
        if has_open_cycle:
            plan.status = CampaignStatus.CALL_OPEN
        elif ever_had_call:
            plan.status = CampaignStatus.STOCK_AVAILABLE
        else:
            plan.status = CampaignStatus.STOCK_ACQUIRED

    if plan._running_shares > 0 and plan._running_cost > 0:
        plan.stock_cost_basis = round(plan._running_cost / plan._running_shares, 6)
    elif plan.sales:
        known = [s.cost_basis_price for s in plan.sales if s.cost_basis_price is not None]
        plan.stock_cost_basis = round(sum(known) / len(known), 6) if known else None

    if plan.stock_realized_pnl is not None:
        plan.stock_realized_pnl = round(plan.stock_realized_pnl, 2)
    if plan.stock_invested is not None:
        plan.stock_invested = round(plan.stock_invested, 2)
    plan.dividends_total = round(plan.dividends_total, 2)
    plan.stock_commissions = round(plan.stock_commissions, 2)


# ── Persistencia ──────────────────────────────────────────────────────────────

def rebuild_campaigns(db: Session, user_id: int) -> dict[str, Any]:
    """Borra y regenera las campañas del usuario desde su histórico."""
    transactions = (
        db.query(Transaction)
        .filter(Transaction.user_id == user_id)
        .order_by(Transaction.transaction_date, Transaction.id)
        .all()
    )
    options, ledger = load_option_ledger(
        db,
        user_id,
        [tx for tx in transactions if tx.transaction_type in OPTION_TRANSACTION_TYPES],
    )

    plans = plan_campaigns(transactions, options, ledger)

    # Borrar en orden: los ciclos y eventos caen por CASCADE, pero se hace
    # explícito para no depender de la configuración de la FK.
    existing = db.query(Campaign).filter(Campaign.user_id == user_id).all()
    for campaign in existing:
        db.delete(campaign)
    db.flush()

    created = 0
    cycles_created = 0
    for plan in plans:
        campaign = Campaign(
            user_id=user_id,
            ticker=plan.ticker,
            status=plan.status,
            shares=plan.shares,
            shares_peak=plan.shares_peak,
            stock_cost_basis=plan.stock_cost_basis,
            stock_invested=plan.stock_invested,
            cost_basis_status=plan.cost_basis_status,
            opened_at=plan.opened_at,
            closed_at=plan.closed_at,
            close_reason=plan.close_reason,
            dividends_total=plan.dividends_total,
        )
        db.add(campaign)
        db.flush()
        created += 1

        option_realized = 0.0
        option_open = 0.0
        option_commissions = 0.0

        for index, cycle_plan in enumerate(plan.cycles, start=1):
            targets = take_profit_targets(cycle_plan.entry_premium, cycle_plan.min_tick)
            cycle = CoveredCallCycle(
                campaign_id=campaign.id,
                option_id=cycle_plan.option_id,
                cycle_num=index,
                status=cycle_plan.status,
                ticker=cycle_plan.ticker,
                strike=cycle_plan.strike,
                contracts=cycle_plan.contracts,
                expiration=cycle_plan.expiration,
                opened_at=cycle_plan.opened_at,
                closed_at=cycle_plan.closed_at,
                entry_premium=cycle_plan.entry_premium,
                exit_premium=cycle_plan.exit_premium,
                gross_premium=cycle_plan.gross_premium,
                closing_cost=cycle_plan.closing_cost,
                commissions=cycle_plan.commissions,
                realized_pnl=cycle_plan.realized_pnl,
                open_premium=cycle_plan.open_premium,
                min_tick=cycle_plan.min_tick,
                tp70_price=targets.get(70),
                tp75_price=targets.get(75),
                tp80_price=targets.get(80),
                premium_source=cycle_plan.premium_source,
            )
            db.add(cycle)
            cycles_created += 1
            option_realized += cycle_plan.realized_pnl
            option_open += cycle_plan.open_premium
            option_commissions += cycle_plan.commissions

        campaign.option_realized_pnl = round(option_realized, 2)
        campaign.option_open_premium = round(option_open, 2)
        campaign.commissions_total = round(option_commissions + plan.stock_commissions, 2)
        campaign.stock_realized_pnl = plan.stock_realized_pnl

        if plan.stock_realized_pnl is None:
            campaign.total_pnl = None
        else:
            campaign.total_pnl = round(
                plan.stock_realized_pnl
                + option_realized
                + plan.dividends_total
                - campaign.commissions_total,
                2,
            )

        end = plan.closed_at or datetime.now(plan.opened_at.tzinfo)
        campaign.days_deployed = max(1, (end.date() - plan.opened_at.date()).days)

    db.commit()

    logger.info(
        "campañas reconstruidas",
        extra={"user_id": user_id, "campaigns": created, "cycles": cycles_created},
    )
    return {"campaigns": created, "cycles": cycles_created}
