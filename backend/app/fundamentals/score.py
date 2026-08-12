"""Financial Safety Score: 0 = extremadamente peligroso, 100 = muy sólido.

Dos requisitos gobiernan el diseño:

1. **Explicable.** Cada componente guarda su valor crudo, su normalización, su
   peso y su aporte. La pregunta "¿por qué 67?" se responde leyendo
   `components`, sin recalcular nada.

2. **No es solo una media.** Los hard flags actúan aparte: un veto no se
   promedia, elimina. Una empresa con going concern no puede compensarlo con
   liquidez.

Los pesos son heurísticos por ahora. La calibración contra resultados reales es
trabajo de una fase posterior, y hacerla con la muestra actual sería
sobreajustar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..models.fundamentals import FlagSeverity, FundamentalProfile, ScoreStatus
from .flags import DetectedFlag, has_reject
from .metrics import FundamentalMetrics
from .profiles import is_supported

WEIGHTS = {
    "liquidity": 0.15,
    "solvency": 0.15,
    "cash": 0.20,
    "cash_flow": 0.15,
    "profitability": 0.10,
    "revenue_trend": 0.10,
    "dilution": 0.10,
    "filing_risk": 0.05,
}

# Penalización sobre el score final por cada flag no vetante.
PENALTY_PER_PENALIZE_FLAG = 6.0
MAX_FLAG_PENALTY = 25.0


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
            "raw_value": self.raw_value,
            "normalized": self.normalized,
            "weight": self.weight,
            "contribution": round(self.contribution, 3),
            "note": self.note,
        }


@dataclass
class ScoreResult:
    score: Optional[float]
    status: ScoreStatus
    components: list[ScoreComponent] = field(default_factory=list)
    penalties: list[dict] = field(default_factory=list)
    coverage: float = 0.0
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "status": self.status.value,
            "coverage": round(self.coverage, 3),
            "note": self.note,
            "components": [c.as_dict() for c in self.components],
            "penalties": self.penalties,
        }


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _band(value: Optional[float], low: float, high: float) -> Optional[float]:
    """Normaliza linealmente entre dos cotas. Fuera de rango satura, no extrapola."""
    if value is None:
        return None
    if high == low:
        return None
    return _clamp((value - low) / (high - low))


def _score_liquidity(m: FundamentalMetrics) -> ScoreComponent:
    ratio = m.current_ratio
    # Bajo 1 no alcanza a cubrir lo que vence dentro del año; sobre 3 la mejora
    # marginal es irrelevante para una covered call de 5 a 14 días.
    norm = _band(ratio, 0.5, 3.0)
    note = "activos corrientes sobre pasivos corrientes" if norm is not None else (
        m.missing.get("current_ratio", "sin datos")
    )
    return ScoreComponent("liquidity", ratio, norm, WEIGHTS["liquidity"], 0.0, note)


def _score_solvency(m: FundamentalMetrics) -> ScoreComponent:
    if m.stockholders_equity is not None and m.stockholders_equity < 0:
        return ScoreComponent("solvency", m.debt_to_equity, 0.0, WEIGHTS["solvency"], 0.0,
                              "patrimonio negativo")
    de = m.debt_to_equity
    if de is not None:
        # Menor es mejor: se invierte la banda.
        norm = _clamp(1.0 - _band(de, 0.0, 3.0))
        return ScoreComponent("solvency", de, norm, WEIGHTS["solvency"], 0.0, "deuda sobre patrimonio")

    # Respaldo: varias empresas grandes reportan la deuda con tags de extensión
    # propia que no existen en us-gaap (Ford entre ellas), pero `Liabilities` y
    # `Assets` son universales y miden apalancamiento igual de bien para el uso
    # que le da el scanner.
    lta = m.liabilities_to_assets
    if lta is not None:
        norm = _clamp(1.0 - _band(lta, 0.30, 0.95))
        return ScoreComponent("solvency", lta, norm, WEIGHTS["solvency"], 0.0,
                              "pasivos sobre activos (sin deuda desglosada en us-gaap)")

    return ScoreComponent("solvency", None, None, WEIGHTS["solvency"], 0.0,
                          m.missing.get("debt_to_equity", "sin datos de apalancamiento"))


def _score_cash(m: FundamentalMetrics, profile: FundamentalProfile) -> ScoreComponent:
    """En empresas que queman caja manda el runway; en las demás, la deuda neta."""
    if m.cash_runway_quarters is not None:
        # 2 trimestres es el veto; 12 (tres años) ya no agrega tranquilidad.
        norm = _band(m.cash_runway_quarters, 2.0, 12.0)
        return ScoreComponent("cash", m.cash_runway_quarters, norm, WEIGHTS["cash"], 0.0,
                              "trimestres de caja al ritmo de quema actual")

    if m.net_debt is not None and m.revenue_ttm:
        leverage = m.net_debt / m.revenue_ttm
        norm = _clamp(1.0 - _band(leverage, -0.5, 2.0))
        return ScoreComponent("cash", leverage, norm, WEIGHTS["cash"], 0.0,
                              "deuda neta sobre ingresos TTM")

    if m.net_debt is not None and m.net_debt < 0:
        return ScoreComponent("cash", m.net_debt, 1.0, WEIGHTS["cash"], 0.0,
                              "caja neta positiva")

    # Sin deuda desglosada, la caja relativa a los ingresos sigue diciendo cuánto
    # colchón hay para aguantar un trimestre malo.
    if m.cash_to_revenue is not None:
        norm = _band(m.cash_to_revenue, 0.02, 0.40)
        return ScoreComponent("cash", m.cash_to_revenue, norm, WEIGHTS["cash"], 0.0,
                              "caja sobre ingresos TTM (sin deuda desglosada)")

    return ScoreComponent("cash", None, None, WEIGHTS["cash"], 0.0,
                          m.missing.get("cash", "sin caja ni deuda neta"))


def _score_cash_flow(m: FundamentalMetrics) -> ScoreComponent:
    if m.fcf_ttm is None:
        return ScoreComponent("cash_flow", None, None, WEIGHTS["cash_flow"], 0.0,
                              m.missing.get("fcf_ttm", "sin flujo de caja libre"))
    if m.revenue_ttm:
        margin = m.fcf_ttm / m.revenue_ttm
        norm = _band(margin, -0.30, 0.20)
        return ScoreComponent("cash_flow", margin, norm, WEIGHTS["cash_flow"], 0.0,
                              "margen de flujo de caja libre")
    norm = 1.0 if m.fcf_ttm > 0 else 0.0
    return ScoreComponent("cash_flow", m.fcf_ttm, norm, WEIGHTS["cash_flow"], 0.0,
                          "flujo de caja libre, sin ingresos para relativizar")


def _score_profitability(m: FundamentalMetrics) -> ScoreComponent:
    margin = m.operating_margin
    norm = _band(margin, -0.25, 0.20)
    note = "margen operacional" if norm is not None else m.missing.get("operating_margin", "sin datos")
    return ScoreComponent("profitability", margin, norm, WEIGHTS["profitability"], 0.0, note)


def _score_revenue_trend(m: FundamentalMetrics) -> ScoreComponent:
    growth = m.revenue_growth_yoy
    # Una caída de 20% es señal seria; sobre 30% de alza el crecimiento ya no
    # dice nada nuevo sobre la seguridad financiera.
    norm = _band(growth, -0.20, 0.30)
    note = "crecimiento de ingresos TTM" if norm is not None else (
        m.missing.get("revenue_growth_yoy", "sin datos")
    )
    return ScoreComponent("revenue_trend", growth, norm, WEIGHTS["revenue_trend"], 0.0, note)


def _score_dilution(m: FundamentalMetrics) -> ScoreComponent:
    dilution = m.dilution_yoy
    if dilution is None:
        return ScoreComponent("dilution", None, None, WEIGHTS["dilution"], 0.0,
                              m.missing.get("dilution_yoy", "sin datos"))
    # Recompras (dilución negativa) puntúan al máximo; 30% de emisión anual, al mínimo.
    norm = _clamp(1.0 - _band(dilution, -0.02, 0.30))
    return ScoreComponent("dilution", dilution, norm, WEIGHTS["dilution"], 0.0,
                          "variación de acciones en circulación a 12 meses")


def _score_filing_risk(flags: list[DetectedFlag]) -> ScoreComponent:
    # Solo cuentan las señales que afirman un riesgo. Los INFO son contexto
    # ("restructuring plan" aparece en la nota contable de casi cualquier
    # empresa que reorganizó algo) y castigarlos penalizaría por informar bien.
    text_flags = [
        f for f in flags
        if f.origin == "FILING_TEXT" and f.severity != FlagSeverity.INFO
    ]
    if not text_flags:
        return ScoreComponent("filing_risk", 0, 1.0, WEIGHTS["filing_risk"], 0.0,
                              "sin frases de riesgo en los filings revisados")
    norm = _clamp(1.0 - 0.35 * len(text_flags))
    return ScoreComponent("filing_risk", len(text_flags), norm, WEIGHTS["filing_risk"], 0.0,
                          f"{len(text_flags)} señal(es) de riesgo en el texto de los filings")


def compute_financial_safety_score(
    metrics: FundamentalMetrics,
    profile: FundamentalProfile,
    flags: list[DetectedFlag],
) -> ScoreResult:
    if not is_supported(profile):
        return ScoreResult(
            score=None,
            status=ScoreStatus.UNSUPPORTED_PROFILE,
            note=(
                f"perfil {profile.value}: requiere métricas sectoriales todavía no "
                "implementadas, no se le asigna un score aproximado"
            ),
        )

    components = [
        _score_liquidity(metrics),
        _score_solvency(metrics),
        _score_cash(metrics, profile),
        _score_cash_flow(metrics),
        _score_profitability(metrics),
        _score_revenue_trend(metrics),
        _score_dilution(metrics),
        _score_filing_risk(flags),
    ]

    available = [c for c in components if c.normalized is not None]
    total_weight = sum(c.weight for c in available)
    coverage = total_weight / sum(WEIGHTS.values())

    # Con menos de la mitad del peso cubierto, cualquier número sería una
    # opinión disfrazada de medición.
    if coverage < 0.5:
        return ScoreResult(
            score=None,
            status=ScoreStatus.INSUFFICIENT_DATA,
            components=components,
            coverage=coverage,
            note=f"solo {coverage:.0%} del peso tiene datos; se necesita al menos 50%",
        )

    # Los componentes sin dato se excluyen y el resto se renormaliza, en vez de
    # contarlos como cero: ausencia de dato no es evidencia de fragilidad.
    for component in available:
        component.contribution = (component.normalized or 0.0) * component.weight / total_weight

    base = sum(c.contribution for c in available) * 100

    penalties: list[dict] = []
    penalty_total = 0.0
    if has_reject(flags):
        for flag in flags:
            if flag.is_reject:
                penalties.append({"flag": flag.flag.value, "severity": "REJECT", "effect": "score forzado a 0"})
        return ScoreResult(
            score=0.0,
            status=ScoreStatus.OK,
            components=components,
            penalties=penalties,
            coverage=coverage,
            note="hard flag de veto: el riesgo fundamental crítico no se compensa con nada",
        )

    for flag in flags:
        if flag.severity.value == "PENALIZE":
            penalty_total += PENALTY_PER_PENALIZE_FLAG
            penalties.append(
                {"flag": flag.flag.value, "severity": "PENALIZE", "effect": -PENALTY_PER_PENALIZE_FLAG}
            )
    penalty_total = min(penalty_total, MAX_FLAG_PENALTY)

    score = max(0.0, min(100.0, base - penalty_total))

    return ScoreResult(
        score=round(score, 2),
        status=ScoreStatus.OK,
        components=components,
        penalties=penalties,
        coverage=coverage,
        note=f"base {base:.1f} menos {penalty_total:.1f} de penalizaciones",
    )
