"""Reglas de estado de campañas y ciclos, y detección de assignment.

El assignment es un resultado normal del sistema, no un fallo: cuando una call
termina asignada el capital se libera y la campaña cierra con su retorno. Pero el
histórico importado no lo dice explícitamente — los 3 assignments de la cuenta
quedaron guardados como `EXPIRED` porque el importador antiguo solo los buscaba
en Corporate Actions. Por eso se detectan aquí desde la forma de las
transacciones, en vez de confiar en `Option.status`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable, Optional

from ..models import CampaignStatus, CycleStatus

# IB fecha la venta de acciones del assignment el día de la expiración, pero la
# liquidación puede caer un par de días después según cómo se importó.
ASSIGNMENT_DATE_MARGIN_DAYS = 2

# Tolerancia al comparar precio de venta contra strike. Un assignment ejecuta
# exactamente al strike; este margen absorbe redondeos de importación.
STRIKE_MATCH_TOLERANCE = 0.005


_VALID_TRANSITIONS: dict[CampaignStatus, frozenset[CampaignStatus]] = {
    CampaignStatus.STOCK_ACQUIRED: frozenset(
        {CampaignStatus.STOCK_AVAILABLE, CampaignStatus.CALL_OPEN, CampaignStatus.CLOSED}
    ),
    CampaignStatus.STOCK_AVAILABLE: frozenset(
        {CampaignStatus.CALL_OPEN, CampaignStatus.CLOSED}
    ),
    CampaignStatus.CALL_OPEN: frozenset(
        {CampaignStatus.STOCK_AVAILABLE, CampaignStatus.CALL_OPEN, CampaignStatus.CLOSED}
    ),
    CampaignStatus.CLOSED: frozenset(),
}


def can_transition(current: CampaignStatus, target: CampaignStatus) -> bool:
    return target in _VALID_TRANSITIONS.get(current, frozenset())


@dataclass(frozen=True)
class AssignmentMatch:
    """Una venta de acciones que resultó de que asignaran una call."""

    sale_transaction_id: Optional[int]
    option_id: Optional[int]
    strike: float
    contracts: float
    shares: float
    sale_date: date


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if hasattr(value, "date"):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def detect_assignment(
    *,
    sale_price: Optional[float],
    sale_quantity: Optional[float],
    sale_date: Optional[date],
    open_cycles: Iterable[Any],
) -> Optional[AssignmentMatch]:
    """¿Esta venta de acciones es el resultado de un assignment?

    Una call asignada produce una venta al strike exacto, por 100 acciones por
    contrato, fechada en la expiración. Las tres condiciones juntas son
    específicas: una venta discrecional que coincidiera con las tres sería
    indistinguible de un assignment y contablemente equivalente.
    """
    if sale_price is None or not sale_quantity or sale_date is None:
        return None

    best: Optional[AssignmentMatch] = None
    best_distance: Optional[int] = None

    for cycle in open_cycles:
        strike = cycle.get("strike")
        contracts = cycle.get("contracts")
        expiration = _as_date(cycle.get("expiration"))
        if strike is None or not contracts or expiration is None:
            continue

        if abs(float(sale_price) - float(strike)) > STRIKE_MATCH_TOLERANCE:
            continue

        covered_shares = float(contracts) * 100
        if abs(float(sale_quantity) - covered_shares) > 1e-6:
            continue

        distance = abs((sale_date - expiration).days)
        if distance > ASSIGNMENT_DATE_MARGIN_DAYS:
            continue

        if best_distance is None or distance < best_distance:
            best_distance = distance
            best = AssignmentMatch(
                sale_transaction_id=cycle.get("sale_transaction_id"),
                option_id=cycle.get("option_id"),
                strike=float(strike),
                contracts=float(contracts),
                shares=covered_shares,
                sale_date=sale_date,
            )

    return best


def cycle_status_from_option(
    *,
    option_status: str,
    was_assigned: bool,
    was_rolled: bool,
    exit_premium: Optional[float],
) -> CycleStatus:
    """Traduce el estado de la fila `options` al del ciclo.

    `was_assigned` manda sobre `option_status`: el histórico trae assignments
    guardados como EXPIRED y la detección estructural es más confiable que el
    campo.
    """
    if was_assigned:
        return CycleStatus.ASSIGNED
    if was_rolled:
        return CycleStatus.ROLLED
    if option_status == "OPEN":
        return CycleStatus.OPEN
    if option_status == "ASSIGNED":
        return CycleStatus.ASSIGNED
    if option_status == "EXPIRED":
        return CycleStatus.EXPIRED_OTM
    if option_status == "CLOSED":
        # Sin precio de recompra no se puede afirmar que fue un take profit.
        return CycleStatus.CLOSED_MANUAL if exit_premium is None else CycleStatus.CLOSED_TP
    return CycleStatus.CLOSED_MANUAL


def campaign_status_after(
    *,
    shares: float,
    has_open_cycle: bool,
    ever_had_call: bool,
) -> CampaignStatus:
    if shares <= 1e-9:
        return CampaignStatus.CLOSED
    if has_open_cycle:
        return CampaignStatus.CALL_OPEN
    return CampaignStatus.STOCK_AVAILABLE if ever_had_call else CampaignStatus.STOCK_ACQUIRED


def within_margin(a: Optional[date], b: Optional[date], days: int) -> bool:
    if a is None or b is None:
        return False
    return abs((a - b).days) <= days


__all__ = [
    "ASSIGNMENT_DATE_MARGIN_DAYS",
    "AssignmentMatch",
    "STRIKE_MATCH_TOLERANCE",
    "campaign_status_after",
    "can_transition",
    "cycle_status_from_option",
    "detect_assignment",
    "within_margin",
]
