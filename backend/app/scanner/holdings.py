"""Covered calls sobre lo que el usuario YA tiene (K5.1).

El scanner del universo evalúa cada papel como si se comprara de cero al ask.
Eso es correcto para el momento en que llega capital nuevo —que en esta
estrategia es justamente cuando te asignan y te devuelven el efectivo— pero es
la pregunta equivocada mientras tienes las acciones en cartera.

Sobre una posición abierta cambian tres cosas:

1. **El costo no es el precio de mercado, es `adjusted_cost_basis`**: el costo
   bruto menos las primas ya cobradas en el ciclo. En SMR la diferencia entre
   uno y otro era de $11,43 a $9,65 — usar el bruto daba pérdida en strikes que
   en realidad dejan ganancia.
2. **La cantidad de contratos la fija la posición**, no el capital disponible:
   265 acciones son 2 contratos, y quedan 65 acciones sin cubrir.
3. **La asignación no es un riesgo, es el objetivo.** El ciclo se cierra cuando
   te ejercen: ahí vuelve el capital para recomprar y volver a vender calls. Por
   eso cada fila lleva la probabilidad de asignación y el total si te ejercen,
   además de la prima.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from .covered_calls import CONTRACT_MULTIPLIER, CoveredCallMetrics

COST_BASIS_ADJUSTED = "ADJUSTED"
COST_BASIS_GROSS = "GROSS"


@dataclass
class HoldingCoveredCall:
    """Una call vendible contra una posición concreta, con su aritmética real."""

    metrics: CoveredCallMetrics
    cost_basis: float
    cost_basis_source: str          # ADJUSTED | GROSS
    shares: float
    contracts: int
    uncovered_shares: float
    premium_total: float            # por la posición entera, no por contrato
    gain_if_assigned: float         # solo la parte de capital
    total_if_assigned: float        # capital + prima
    below_cost_basis: bool          # el strike está bajo el costo real
    net_loss_if_assigned: bool      # ni siquiera la prima alcanza a cubrirlo
    assignment_probability: Optional[float]
    annualized_premium_on_cost: Optional[float]

    def as_dict(self) -> dict:
        base = self.metrics.as_dict()
        base.update({
            "cost_basis": round(self.cost_basis, 4),
            "cost_basis_source": self.cost_basis_source,
            "shares": self.shares,
            "contracts": self.contracts,
            "uncovered_shares": self.uncovered_shares,
            "position_premium_total": round(self.premium_total, 2),
            "gain_if_assigned": round(self.gain_if_assigned, 2),
            "total_if_assigned": round(self.total_if_assigned, 2),
            "below_cost_basis": self.below_cost_basis,
            "net_loss_if_assigned": self.net_loss_if_assigned,
            "assignment_probability": (
                round(self.assignment_probability, 4) if self.assignment_probability is not None else None
            ),
            "annualized_premium_on_cost": (
                round(self.annualized_premium_on_cost, 6) if self.annualized_premium_on_cost is not None else None
            ),
        })
        return base


def resolve_cost_basis(stock) -> tuple[Optional[float], str]:
    """El costo real de la posición: ajustado por primas si existe.

    `adjusted_cost_basis` descuenta las primas cobradas en el ciclo vigente, que
    es lo que la página Stocks muestra como "costo real" y lo único que permite
    decidir si un strike realiza ganancia o pérdida. Se devuelve cuál se usó:
    un número de costo sin decir de dónde sale no se puede auditar.
    """
    ajustado = getattr(stock, "adjusted_cost_basis", None)
    if ajustado is not None and ajustado > 0:
        return float(ajustado), COST_BASIS_ADJUSTED
    bruto = getattr(stock, "average_cost", None)
    if bruto is not None and bruto > 0:
        return float(bruto), COST_BASIS_GROSS
    return None, COST_BASIS_GROSS


def evaluate_for_holding(
    metrics: CoveredCallMetrics,
    cost_basis: float,
    cost_basis_source: str,
    shares: float,
) -> Optional[HoldingCoveredCall]:
    """Reescribe las métricas del contrato en términos de la posición real."""
    contracts = int(shares // CONTRACT_MULTIPLIER)
    if contracts < 1:
        return None  # menos de 100 acciones: no hay covered call que vender

    cubiertas = contracts * CONTRACT_MULTIPLIER
    prima = metrics.call_bid * cubiertas
    ganancia_capital = (metrics.strike - cost_basis) * cubiertas
    total = ganancia_capital + prima

    # Delta como aproximación de la probabilidad de terminar ITM. No es la
    # probabilidad de asignación exacta —ignora el ejercicio anticipado por
    # dividendo, entre otras cosas— pero es la que el mercado cotiza y no
    # requiere asumir un modelo propio.
    prob = abs(metrics.delta) if metrics.delta is not None else None

    # Rendimiento de la PRIMA sobre el capital inmovilizado, anualizado. Es lo
    # único que la decisión de vender la call agrega: la apreciación desde el
    # costo hasta el strike es de la acción, la tendrías igual sin vender nada.
    #
    # La primera versión rankeaba por un "valor esperado" que sumaba
    # `prob * (strike - costo) * acciones`, y eso ponía primero una call a
    # strike 20 con delta 0,05 sobre un papel a 14: le atribuía a la call
    # $2.070 de apreciación que no crea. Un test lo pescó — el error no era del
    # test.
    anualizado = None
    capital = cost_basis * cubiertas
    if capital > 0 and metrics.dte > 0:
        anualizado = (prima / capital) * (365.0 / metrics.dte)

    return HoldingCoveredCall(
        metrics=metrics,
        cost_basis=cost_basis,
        cost_basis_source=cost_basis_source,
        shares=shares,
        contracts=contracts,
        uncovered_shares=shares - cubiertas,
        premium_total=prima,
        gain_if_assigned=ganancia_capital,
        total_if_assigned=total,
        # Dos avisos distintos, y la diferencia importa: un strike bajo el
        # costo realiza una pérdida de capital, pero la prima puede taparla y
        # dejar el ciclo en verde igual. Confundirlos descartaría operaciones
        # que sí convienen.
        below_cost_basis=metrics.strike < cost_basis,
        net_loss_if_assigned=total < 0,
        assignment_probability=prob,
        annualized_premium_on_cost=anualizado,
    )


def rank_for_cycle(candidatos: list[HoldingCoveredCall]) -> list[HoldingCoveredCall]:
    """Ordena por rendimiento anualizado de la prima sobre el costo real.

    Deliberadamente NO se rankea por un valor esperado que incluya la
    apreciación hasta el strike: esa ganancia es de la acción que ya tienes, no
    la crea la call, y sumarla premia strikes lejanos con delta ínfima que en la
    práctica nunca se ejercen ni devuelven capital.

    La velocidad de reciclaje —que es lo que esta estrategia busca— no se
    esconde en el orden: viaja como `assignment_probability` y
    `total_if_assigned` en cada fila, para que la decisión entre "cobro más
    ahora" y "recupero el capital antes" la tome quien opera y no una
    ponderación fija.
    """
    return sorted(
        candidatos,
        key=lambda h: (h.annualized_premium_on_cost is not None, h.annualized_premium_on_cost or 0.0),
        reverse=True,
    )
