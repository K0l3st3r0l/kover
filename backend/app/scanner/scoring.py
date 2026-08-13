"""CC Opportunity Score y Final Score (K5).

Convierte el ranking crudo de K4 en una recomendación con la puerta aplicada
primero. Dos ideas que el plan (`docs/COVERED_CALL_SCANNER_PLAN.md` §15) pone
como no negociables:

1. **Los componentes de mercado se normalizan contra la corrida, no contra una
   tabla fija.** Un 4% de prima no significa lo mismo en un mercado tranquilo
   que en uno con IV alta. Se winsoriza a p5/p95 y se escala entre esas cotas,
   así un outlier no aplasta la escala del resto.

2. **Primero la puerta, después el ranking.** Una prima enorme no compensa un
   riesgo fundamental crítico. El gate se evalúa aparte del score y un papel
   vetado no entra al ranking por alto que puntúe.

Desviación consciente del plan: `delta_fit` y `dte_fit` **no** se normalizan por
percentil, se miden contra una banda absoluta. El argumento del percentil es que
el mercado cambia; pero un delta de 0,30 es 0,30 en cualquier mercado, y
rankear un "ajuste" por percentil haría que el contrato que peor calza de la
corrida saque 100 si todos calzan mal. Los cinco componentes que sí dependen de
las condiciones de mercado (prima, retorno si asignan, liquidez, spread, IV) van
por percentil.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

# Pesos del CC Opportunity Score. Suman 1,0.
WEIGHTS = {
    "premium_yield": 0.25,
    "return_if_assigned": 0.15,
    "option_liquidity": 0.15,
    "spread_quality": 0.15,
    "delta_fit": 0.10,
    "dte_fit": 0.10,
    "iv_opportunity": 0.10,
}

FINAL_WEIGHTS = {"cc_opportunity": 0.45, "financial_safety": 0.35, "market_safety": 0.20}

WINSOR_LOW = 5.0
WINSOR_HIGH = 95.0
MIN_POPULATION_FOR_PERCENTILES = 8

# Banda de delta que se considera ideal para un covered call, y hasta dónde
# sigue siendo aceptable. Fuera de `*_HARD` el ajuste es 0.
DELTA_IDEAL_LOW, DELTA_IDEAL_HIGH = 0.20, 0.35
DELTA_HARD_LOW, DELTA_HARD_HIGH = 0.10, 0.50
# Alineado con las ventanas de los perfiles (§14 del plan: 7–14 conservador,
# 5–10 balanceado y agresivo). La primera versión usaba 21–45 —la preferencia
# clásica de vender mensuales— y el resultado fue que el scan elegía como
# "mejor" un contrato a 36 días que después TODOS los perfiles rechazaban por
# DTE. Dos criterios peleando: el ranking apuntaba a mensuales y la puerta a
# semanales. Manda el plan.
DTE_IDEAL_LOW, DTE_IDEAL_HIGH = 7, 21
DTE_HARD_LOW, DTE_HARD_HIGH = 3, 60

FINAL_OK = "OK"
FINAL_MISSING_FUNDAMENTAL = "MISSING_FUNDAMENTAL"
FINAL_MISSING_MARKET = "MISSING_MARKET"
FINAL_MISSING_BOTH = "MISSING_BOTH"


@dataclass
class ScoreComponent:
    name: str
    raw_value: Optional[float]
    normalized: Optional[float]  # 0–1
    weight: float
    contribution: float
    note: str

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "raw_value": round(self.raw_value, 6) if self.raw_value is not None else None,
            "normalized": round(self.normalized, 4) if self.normalized is not None else None,
            "weight": self.weight,
            "contribution": round(self.contribution, 4),
            "note": self.note,
        }


@dataclass
class ScoreResult:
    score: Optional[float]
    components: list[ScoreComponent] = field(default_factory=list)
    coverage: float = 0.0
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "coverage": round(self.coverage, 3),
            "note": self.note,
            "components": [c.as_dict() for c in self.components],
        }


def _percentile(sorted_values: list[float], p: float) -> float:
    """Percentil por interpolación lineal. `sorted_values` no puede estar vacío."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * (p / 100.0)
    piso = int(k)
    techo = min(piso + 1, len(sorted_values) - 1)
    if piso == techo:
        return sorted_values[piso]
    return sorted_values[piso] + (sorted_values[techo] - sorted_values[piso]) * (k - piso)


def build_normalizer(
    values: list[Optional[float]], higher_is_better: bool = True
) -> Callable[[Optional[float]], Optional[float]]:
    """Devuelve una función que normaliza 0–1 contra la población de la corrida.

    Winsoriza a p5/p95 y escala linealmente entre esas cotas. El percentil crudo
    perdería la magnitud —el segundo mejor quedaría siempre en el mismo lugar
    aunque estuviera pegado al primero o muy lejos—, y el min-max sin winsorizar
    dejaría que un solo contrato absurdo comprima a todos los demás contra el
    piso. Winsorizar y después escalar conserva las distancias donde están los
    datos y acota el daño de los extremos.

    Límite conocido: la winsorización solo protege cuando el extremo cabe en la
    cola del 5%. Con una corrida de 11 contratos, un outlier es el 9% de la
    población, p95 interpola dentro de él y no hay nada que recortar. En una
    corrida del universo completo (miles de contratos) el caso no aparece, pero
    en un escaneo de un puñado de símbolos el score hay que leerlo con
    desconfianza. Test: `test_winsorizing_cannot_save_a_tiny_population`.
    """
    limpios = sorted(v for v in values if v is not None)
    if not limpios:
        return lambda _v: None

    if len(limpios) < MIN_POPULATION_FOR_PERCENTILES:
        # Con poca población los percentiles son ruido. Se usa el rango completo
        # observado, que al menos ordena bien, en vez de fingir precisión.
        low, high = limpios[0], limpios[-1]
    else:
        low = _percentile(limpios, WINSOR_LOW)
        high = _percentile(limpios, WINSOR_HIGH)

    def normalizar(value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        if high <= low:
            # Toda la población vale lo mismo: nadie destaca, todos al medio.
            return 0.5
        escalado = (value - low) / (high - low)
        escalado = max(0.0, min(1.0, escalado))
        return escalado if higher_is_better else 1.0 - escalado

    return normalizar


def _band_fit(value: Optional[float], ideal_low: float, ideal_high: float,
              hard_low: float, hard_high: float) -> Optional[float]:
    """1,0 dentro de la banda ideal, cayendo linealmente hasta 0 en los bordes duros."""
    if value is None:
        return None
    if ideal_low <= value <= ideal_high:
        return 1.0
    if value < ideal_low:
        if value <= hard_low:
            return 0.0
        return (value - hard_low) / (ideal_low - hard_low)
    if value >= hard_high:
        return 0.0
    return (hard_high - value) / (hard_high - ideal_high)


def compute_cc_opportunity(candidatos: list) -> list[ScoreResult]:
    """CC Opportunity 0–100 para cada candidato, normalizado contra la corrida.

    Recibe la lista completa de la corrida —no un contrato aislado— justamente
    porque cinco de los siete componentes se miden contra sus pares. Devuelve
    los resultados en el mismo orden.
    """
    if not candidatos:
        return []

    norm_prima = build_normalizer([c.annualized_premium_yield for c in candidatos], True)
    norm_asignado = build_normalizer([c.annualized_return_if_assigned for c in candidatos], True)
    norm_liquidez = build_normalizer([c.liquidity_score for c in candidatos], True)
    norm_spread = build_normalizer([c.spread_pct for c in candidatos], False)
    norm_iv = build_normalizer([c.implied_volatility for c in candidatos], True)

    resultados: list[ScoreResult] = []
    for c in candidatos:
        especificacion = [
            ("premium_yield", c.annualized_premium_yield, norm_prima(c.annualized_premium_yield),
             "prima anualizada, contra el resto de la corrida"),
            ("return_if_assigned", c.annualized_return_if_assigned, norm_asignado(c.annualized_return_if_assigned),
             "retorno anualizado si te asignan, contra el resto de la corrida"),
            ("option_liquidity", c.liquidity_score, norm_liquidez(c.liquidity_score),
             "Option Liquidity Score, contra el resto de la corrida"),
            ("spread_quality", c.spread_pct, norm_spread(c.spread_pct),
             "spread relativo; menos es mejor"),
            ("delta_fit", c.delta,
             _band_fit(abs(c.delta) if c.delta is not None else None,
                       DELTA_IDEAL_LOW, DELTA_IDEAL_HIGH, DELTA_HARD_LOW, DELTA_HARD_HIGH),
             f"ajuste a delta {DELTA_IDEAL_LOW}–{DELTA_IDEAL_HIGH}; banda absoluta, no percentil"),
            ("dte_fit", float(c.dte),
             _band_fit(float(c.dte), DTE_IDEAL_LOW, DTE_IDEAL_HIGH, DTE_HARD_LOW, DTE_HARD_HIGH),
             f"ajuste a {DTE_IDEAL_LOW}–{DTE_IDEAL_HIGH} días; banda absoluta, no percentil"),
            ("iv_opportunity", c.implied_volatility, norm_iv(c.implied_volatility),
             "IV del contrato, contra el resto de la corrida"),
        ]

        componentes: list[ScoreComponent] = []
        peso_total = 0.0
        acumulado = 0.0
        for nombre, crudo, normalizado, nota in especificacion:
            peso = WEIGHTS[nombre]
            aporte = 0.0
            if normalizado is not None:
                peso_total += peso
                aporte = normalizado * peso
                acumulado += aporte
            componentes.append(ScoreComponent(nombre, crudo, normalizado, peso, aporte, nota))

        if peso_total < 0.5:
            # Mismo criterio que el score fundamental y el de riesgo de mercado:
            # bajo la mitad del peso cubierto, cualquier número sería una
            # opinión disfrazada de medición.
            resultados.append(ScoreResult(None, componentes, peso_total,
                                          "INSUFFICIENT_DATA: menos del 50% del peso con dato"))
            continue

        resultados.append(ScoreResult(round(100.0 * acumulado / peso_total, 2), componentes, peso_total, ""))

    return resultados


def compute_final_score(
    cc_opportunity: Optional[float],
    financial_safety: Optional[float],
    market_safety: Optional[float],
) -> tuple[Optional[float], str]:
    """0,45 CC + 0,35 fundamental + 0,20 mercado. None si falta un ingrediente.

    **No se renormaliza cuando falta un componente**, a diferencia de los otros
    scores del proyecto. Acá renormalizar sería peor que no dar número: un papel
    sin fundamentales quedaría puntuado solo por prima y volatilidad, que es
    exactamente la recomendación que el plan prohíbe. Ausencia de dato no puede
    convertirse en un score alto por omisión.
    """
    if cc_opportunity is None:
        return None, "MISSING_CC_OPPORTUNITY"
    falta_fundamental = financial_safety is None
    falta_mercado = market_safety is None
    if falta_fundamental and falta_mercado:
        return None, FINAL_MISSING_BOTH
    if falta_fundamental:
        return None, FINAL_MISSING_FUNDAMENTAL
    if falta_mercado:
        return None, FINAL_MISSING_MARKET

    final = (
        FINAL_WEIGHTS["cc_opportunity"] * cc_opportunity
        + FINAL_WEIGHTS["financial_safety"] * financial_safety
        + FINAL_WEIGHTS["market_safety"] * market_safety
    )
    return round(final, 2), FINAL_OK


# ─── Perfiles y puerta ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Profile:
    name: str
    min_financial_safety: float
    min_market_safety: Optional[float]
    max_spread_pct: float
    delta_low: float
    delta_high: float
    dte_low: int
    dte_high: int


PROFILES = {
    "CONSERVADOR": Profile("CONSERVADOR", 75, 65, 0.08, 0.20, 0.30, 7, 14),
    "BALANCEADO": Profile("BALANCEADO", 60, 45, 0.12, 0.25, 0.35, 5, 10),
    "AGRESIVO": Profile("AGRESIVO", 45, None, 0.20, 0.30, 0.40, 5, 10),
}

GATE_PASS = "PASS"
GATE_VETO = "VETO_HARD_FLAG"
GATE_LOW_FUNDAMENTAL = "BAJO_FINANCIAL_SAFETY"
GATE_LOW_MARKET = "BAJO_MARKET_SAFETY"
GATE_WIDE_SPREAD = "SPREAD_ANCHO"
GATE_DELTA = "DELTA_FUERA_DE_PERFIL"
GATE_DTE = "DTE_FUERA_DE_PERFIL"
GATE_NO_FUNDAMENTAL = "SIN_FUNDAMENTALES"


def evaluate_gate(
    profile: Profile,
    financial_safety: Optional[float],
    market_safety: Optional[float],
    spread_pct: Optional[float],
    delta: Optional[float],
    dte: Optional[int],
) -> tuple[bool, list[str]]:
    """¿Este contrato es admisible bajo el perfil? Devuelve (pasa, razones).

    Se devuelven **todas** las razones, no la primera: saber que un papel falla
    por tres motivos distintos cambia la decisión respecto a fallar por uno solo
    que además está al borde.
    """
    razones: list[str] = []

    # El veto por hard flag aplica en todos los perfiles, incluido el agresivo.
    # Financial Safety exactamente 0 es la marca que deja un REJECT — ver
    # wiki/projects/kover/decisions/fundamentales-sec-edgar.md.
    if financial_safety is not None and financial_safety == 0:
        razones.append(GATE_VETO)
    elif financial_safety is None:
        # Sin fundamentales no se puede afirmar que pase la puerta. No es un
        # veto: es que no hay con qué decidir, y se dice así.
        razones.append(GATE_NO_FUNDAMENTAL)
    elif financial_safety < profile.min_financial_safety:
        razones.append(GATE_LOW_FUNDAMENTAL)

    if profile.min_market_safety is not None:
        if market_safety is None or market_safety < profile.min_market_safety:
            razones.append(GATE_LOW_MARKET)

    if spread_pct is not None and spread_pct > profile.max_spread_pct:
        razones.append(GATE_WIDE_SPREAD)

    if delta is not None and not (profile.delta_low <= abs(delta) <= profile.delta_high):
        razones.append(GATE_DELTA)

    if dte is not None and not (profile.dte_low <= dte <= profile.dte_high):
        razones.append(GATE_DTE)

    return (not razones), razones
