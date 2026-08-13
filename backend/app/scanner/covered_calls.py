"""Métricas de covered call sobre una cadena real (K4).

Convención de precios, heredada de la regla del proyecto "`last` no es precio
ejecutable" (ver wiki/projects/kover/decisions/covered-call-scanner-stack.md):
**se compra la acción al ask y se vende la call al bid**. Es el peor lado de
ambos spreads a propósito — un ranking construido sobre mid se ve mejor de lo
que se puede ejecutar, y el error es sistemáticamente optimista, que es la peor
dirección posible para un ranking.

Ninguna métrica cae a 0 cuando falta un dato: se devuelve `None` con su razón,
igual que en el score fundamental y en el de riesgo de mercado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from ..providers.base import OptionQuote

CONTRACT_MULTIPLIER = 100

# Ventana de vencimientos. El piso es 5 y no 7 para que la ventana de los
# perfiles balanceado y agresivo (5–10 días, §14 del plan) quede cubierta
# entera: con min_dte=7 los contratos de 5 y 6 días nunca se evaluaban y esos
# perfiles quedaban con tres días útiles de solapamiento.
DEFAULT_MIN_DTE = 5
DEFAULT_MAX_DTE = 60
# Delta objetivo: la banda clásica de covered calls. Bajo 0,15 la prima no paga
# el riesgo; sobre 0,45 la probabilidad de que te asignen deja de ser un efecto
# secundario y pasa a ser el resultado esperado.
DEFAULT_MIN_DELTA = 0.15
DEFAULT_MAX_DELTA = 0.45
# Un spread ancho se come la prima al cerrar anticipado, que es parte de la
# estrategia (TP70/75/80 en K6).
DEFAULT_MAX_SPREAD_PCT = 0.20
DEFAULT_MIN_OPEN_INTEREST = 10


@dataclass
class CoveredCallMetrics:
    """Una call vendible contra 100 acciones, con todo lo necesario para decidir."""

    underlying: str
    occ_symbol: str
    expiration: date
    strike: float
    dte: int
    underlying_price: float
    stock_ask: float
    call_bid: float
    call_ask: float
    premium_total: float           # por contrato, en dólares
    premium_yield: float           # prima / capital comprometido
    annualized_premium_yield: float
    return_if_assigned: float      # incluye la ganancia hasta el strike
    annualized_return_if_assigned: float
    downside_protection: float     # cuánto puede caer el papel antes de perder
    breakeven: float
    spread_pct: Optional[float]
    moneyness: float               # (strike - precio) / precio
    delta: Optional[float]
    implied_volatility: Optional[float]
    volume: Optional[int]
    open_interest: Optional[int]
    liquidity_score: Optional[float]
    liquidity_components: list[dict] = field(default_factory=list)
    # Los llena K5 (app/scanner/scoring.py) después de tener toda la corrida:
    # cinco de los siete componentes se normalizan contra sus pares, así que no
    # se pueden calcular mirando un contrato aislado.
    cc_opportunity_score: Optional[float] = None
    cc_score_components: list[dict] = field(default_factory=list)
    final_score: Optional[float] = None
    final_score_status: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "underlying": self.underlying,
            "occ_symbol": self.occ_symbol,
            "expiration": self.expiration.isoformat(),
            "strike": self.strike,
            "dte": self.dte,
            "underlying_price": round(self.underlying_price, 4),
            "stock_ask": round(self.stock_ask, 4),
            "call_bid": round(self.call_bid, 4),
            "call_ask": round(self.call_ask, 4),
            "premium_total": round(self.premium_total, 2),
            "premium_yield": round(self.premium_yield, 6),
            "annualized_premium_yield": round(self.annualized_premium_yield, 6),
            "return_if_assigned": round(self.return_if_assigned, 6),
            "annualized_return_if_assigned": round(self.annualized_return_if_assigned, 6),
            "downside_protection": round(self.downside_protection, 6),
            "breakeven": round(self.breakeven, 4),
            "spread_pct": round(self.spread_pct, 6) if self.spread_pct is not None else None,
            "moneyness": round(self.moneyness, 6),
            "delta": self.delta,
            "implied_volatility": self.implied_volatility,
            "volume": self.volume,
            "open_interest": self.open_interest,
            "liquidity_score": self.liquidity_score,
            "liquidity_components": self.liquidity_components,
            "cc_opportunity_score": self.cc_opportunity_score,
            "cc_score_components": self.cc_score_components,
            "final_score": self.final_score,
            "final_score_status": self.final_score_status,
        }


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _better_below(value: Optional[float], good_at: float, bad_at: float) -> Optional[float]:
    """0–1 donde MENOS es mejor. Mismo criterio que `_safer_below` en market_risk."""
    if value is None:
        return None
    if value <= good_at:
        return 1.0
    if value >= bad_at:
        return 0.0
    return _clamp(1.0 - (value - good_at) / (bad_at - good_at))


def _better_above(value: Optional[float], bad_at: float, good_at: float) -> Optional[float]:
    """0–1 donde MÁS es mejor."""
    if value is None:
        return None
    if value >= good_at:
        return 1.0
    if value <= bad_at:
        return 0.0
    return _clamp((value - bad_at) / (good_at - bad_at))


def compute_liquidity_score(
    spread_pct: Optional[float], volume: Optional[int], open_interest: Optional[int]
) -> tuple[Optional[float], list[dict]]:
    """Option Liquidity Score 0–100: 40% spread, 30% volumen, 30% open interest.

    El spread pesa más que los otros dos porque la estrategia contempla cerrar
    anticipado (TP70/75/80): un contrato con volumen alto pero spread ancho se
    entra bien y se sale caro.

    Bandas absolutas, no percentiles dentro de la corrida. Los percentiles son
    de K5 y necesitan la población completa del run; acá interesa poder mirar un
    contrato aislado y saber si es líquido, sin depender de contra quién se
    compare. Un componente sin dato se excluye y el resto se renormaliza — misma
    regla que el score fundamental.
    """
    especificacion = [
        ("spread", _better_below(spread_pct, 0.03, 0.25), 0.40,
         "spread relativo al mid; 3% o menos es excelente, 25% inoperable"),
        ("volumen", _better_above(float(volume) if volume is not None else None, 0, 500),
         0.30, "contratos negociados hoy; 500+ satura"),
        ("open_interest", _better_above(float(open_interest) if open_interest is not None else None, 0, 2000),
         0.30, "contratos abiertos; 2000+ satura"),
    ]

    componentes: list[dict] = []
    peso_total = 0.0
    acumulado = 0.0
    for nombre, normalizado, peso, nota in especificacion:
        aporte = 0.0
        if normalizado is not None:
            peso_total += peso
            aporte = normalizado * peso
            acumulado += aporte
        componentes.append({
            "name": nombre,
            "normalized": round(normalizado, 4) if normalizado is not None else None,
            "weight": peso,
            "contribution": round(aporte, 4),
            "note": nota,
        })

    if peso_total <= 0:
        return None, componentes
    return round(100.0 * acumulado / peso_total, 2), componentes


def compute_covered_call(
    quote: OptionQuote,
    underlying_price: float,
    stock_ask: Optional[float],
    today: date,
) -> Optional[CoveredCallMetrics]:
    """Métricas de vender `quote` contra 100 acciones. None si no es vendible.

    `stock_ask` es el precio al que se compraría la acción. Si no hay ask se usa
    el último precio: es menos conservador, y por eso el llamador debería
    preferir el ask cuando exista.
    """
    if quote.right != "C":
        return None
    if quote.bid is None or quote.bid <= 0:
        return None  # sin bid no hay a quién venderle: no es una oportunidad
    if underlying_price is None or underlying_price <= 0:
        return None

    precio_compra = stock_ask if stock_ask and stock_ask > 0 else underlying_price
    dte = (quote.expiration - today).days
    if dte <= 0:
        return None

    prima_accion = quote.bid
    prima_total = prima_accion * CONTRACT_MULTIPLIER
    capital = precio_compra * CONTRACT_MULTIPLIER

    premium_yield = prima_total / capital
    # La ganancia si te asignan incluye la diferencia hasta el strike, que es
    # negativa si la call está ITM: vender una call bajo el costo de la acción
    # es aceptar una pérdida a cambio de prima, y el número tiene que mostrarlo.
    ganancia_asignado = (quote.strike - precio_compra) * CONTRACT_MULTIPLIER + prima_total
    return_if_assigned = ganancia_asignado / capital

    factor_anual = 365.0 / dte
    spread_pct = None
    if quote.ask is not None and quote.ask > 0 and quote.bid is not None:
        mid = (quote.ask + quote.bid) / 2
        if mid > 0:
            spread_pct = (quote.ask - quote.bid) / mid

    liquidity_score, liquidity_components = compute_liquidity_score(
        spread_pct, quote.volume, quote.open_interest
    )

    return CoveredCallMetrics(
        underlying=quote.underlying,
        occ_symbol=quote.occ_symbol or "",
        expiration=quote.expiration,
        strike=quote.strike,
        dte=dte,
        underlying_price=underlying_price,
        stock_ask=precio_compra,
        call_bid=quote.bid,
        call_ask=quote.ask if quote.ask is not None else quote.bid,
        premium_total=prima_total,
        premium_yield=premium_yield,
        annualized_premium_yield=premium_yield * factor_anual,
        return_if_assigned=return_if_assigned,
        annualized_return_if_assigned=return_if_assigned * factor_anual,
        # Cuánto puede caer la acción antes de que la operación pierda plata:
        # la prima cobrada, como fracción del precio de compra.
        downside_protection=prima_accion / precio_compra,
        breakeven=precio_compra - prima_accion,
        spread_pct=spread_pct,
        moneyness=(quote.strike - underlying_price) / underlying_price,
        delta=quote.delta,
        implied_volatility=quote.implied_volatility,
        volume=quote.volume,
        open_interest=quote.open_interest,
        liquidity_score=liquidity_score,
        liquidity_components=liquidity_components,
    )


@dataclass
class ChainFilter:
    min_dte: int = DEFAULT_MIN_DTE
    max_dte: int = DEFAULT_MAX_DTE
    min_delta: float = DEFAULT_MIN_DELTA
    max_delta: float = DEFAULT_MAX_DELTA
    max_spread_pct: float = DEFAULT_MAX_SPREAD_PCT
    min_open_interest: int = DEFAULT_MIN_OPEN_INTEREST
    require_otm: bool = True


def evaluate_chain(
    quotes: list[OptionQuote],
    underlying_price: float,
    today: date,
    stock_ask: Optional[float] = None,
    filtro: Optional[ChainFilter] = None,
) -> tuple[list[CoveredCallMetrics], dict[str, int]]:
    """Filtra la cadena a calls vendibles y las devuelve con sus métricas.

    Segundo valor: cuántos contratos cayó cada filtro. Sin eso, "0 candidatos"
    es indistinguible de "la cadena no llegó" — el mismo problema que el preview
    vacío en el import de IBKR.
    """
    f = filtro or ChainFilter()
    descartes = {
        "no_call": 0, "sin_bid": 0, "fuera_de_dte": 0, "itm": 0,
        "delta_fuera_de_banda": 0, "sin_delta": 0, "spread_ancho": 0,
        "open_interest_bajo": 0,
    }
    resultados: list[CoveredCallMetrics] = []

    for quote in quotes:
        if quote.right != "C":
            descartes["no_call"] += 1
            continue
        dte = (quote.expiration - today).days
        if dte < f.min_dte or dte > f.max_dte:
            descartes["fuera_de_dte"] += 1
            continue
        if f.require_otm and quote.strike <= underlying_price:
            descartes["itm"] += 1
            continue

        metrics = compute_covered_call(quote, underlying_price, stock_ask, today)
        if metrics is None:
            descartes["sin_bid"] += 1
            continue

        if metrics.delta is None:
            descartes["sin_delta"] += 1
            continue
        if not (f.min_delta <= abs(metrics.delta) <= f.max_delta):
            descartes["delta_fuera_de_banda"] += 1
            continue
        if metrics.spread_pct is not None and metrics.spread_pct > f.max_spread_pct:
            descartes["spread_ancho"] += 1
            continue
        if (metrics.open_interest or 0) < f.min_open_interest:
            descartes["open_interest_bajo"] += 1
            continue

        resultados.append(metrics)

    return resultados, descartes


def pick_best(candidatos: list[CoveredCallMetrics]) -> dict[str, Optional[CoveredCallMetrics]]:
    """Las tres lecturas del plan: balanceado, máxima prima, máximo recorrido.

    Un único "mejor" esconde que la pregunta tiene tres respuestas legítimas
    según qué quiere el operador ese mes. Se calculan las tres y se muestran.

    Si los candidatos ya traen `cc_opportunity_score` (K5 lo asigna tras ver la
    corrida completa), el balanceado sale de ahí. Si no —una llamada aislada,
    un test— cae al heurístico de prima ponderada por liquidez, que ordena
    parecido sin necesitar la población.
    """
    if not candidatos:
        return {"balanced": None, "premium": None, "upside": None}

    def puntaje_balanceado(c: CoveredCallMetrics) -> float:
        if c.cc_opportunity_score is not None:
            return c.cc_opportunity_score
        # Rendimiento anualizado ponderado por liquidez: una prima excelente en
        # un contrato que no se puede cerrar no es una oportunidad.
        liquidez = (c.liquidity_score if c.liquidity_score is not None else 50.0) / 100.0
        return c.annualized_premium_yield * (0.5 + 0.5 * liquidez)

    return {
        "balanced": max(candidatos, key=puntaje_balanceado),
        "premium": max(candidatos, key=lambda c: c.annualized_premium_yield),
        "upside": max(candidatos, key=lambda c: c.annualized_return_if_assigned),
    }
