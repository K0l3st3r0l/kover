"""Métricas fundamentales derivadas de los facts normalizados.

Regla que atraviesa todo el módulo: si una métrica no se puede calcular, el
resultado es `None` acompañado de la razón en `missing`. Nunca 0. Un current
ratio de 0 y un current ratio desconocido llevan a decisiones opuestas, y el
scanner no puede distinguirlos si ambos llegan como 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from ..providers.base import FinancialFact
from .normalizer import INSTANT_METRICS as INSTANT_METRIC_NAMES

# Un trimestre fiscal real varía entre 13 y 14 semanas; un anual entre 360 y 371
# días según el calendario 52/53 semanas que usan muchas empresas.
QUARTER_DAYS = (80, 100)
ANNUAL_DAYS = (350, 380)
# Cuánto puede faltar para completar 365 días y aun así considerarse TTM.
TTM_MIN_COVERAGE_DAYS = 330

# Antigüedad máxima de un valor de balance respecto del período más reciente que
# reporta la empresa.
#
# Sin este límite el resultado es silenciosamente falso: Ford dejó de usar
# `LongTermDebtNoncurrent` en 2020, así que "el valor más reciente de ese tag"
# era de 2020-12-31 (0,29 mil millones). Combinado con la caja de 2026 daba una
# deuda neta de -17,36 mil millones y una solvencia casi perfecta para una
# automotriz fuertemente apalancada. Un dato viejo es peor que ninguno, porque no
# se ve como un hueco.
MAX_INSTANT_AGE_DAYS = 200


@dataclass
class FundamentalMetrics:
    as_of: Optional[date] = None

    revenue_ttm: Optional[float] = None
    revenue_ttm_prior: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    gross_profit_ttm: Optional[float] = None
    operating_income_ttm: Optional[float] = None
    net_income_ttm: Optional[float] = None
    operating_margin: Optional[float] = None

    cash: Optional[float] = None
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    stockholders_equity: Optional[float] = None
    short_term_debt: Optional[float] = None
    long_term_debt: Optional[float] = None
    total_debt: Optional[float] = None
    net_debt: Optional[float] = None

    operating_cf_ttm: Optional[float] = None
    capex_ttm: Optional[float] = None
    fcf_ttm: Optional[float] = None
    fcf_margin: Optional[float] = None

    current_ratio: Optional[float] = None
    debt_to_equity: Optional[float] = None
    # Respaldo de apalancamiento: muchas empresas grandes reportan su deuda con
    # tags de extensión propia que no existen en us-gaap (Ford es uno de esos
    # casos), pero `Liabilities` y `Assets` sí son universales.
    liabilities_to_assets: Optional[float] = None
    cash_to_revenue: Optional[float] = None
    shares_outstanding: Optional[float] = None
    shares_outstanding_prior: Optional[float] = None
    dilution_yoy: Optional[float] = None
    cash_runway_quarters: Optional[float] = None

    latest_period_end: Optional[date] = None
    latest_filing_date: Optional[date] = None
    missing: dict[str, str] = field(default_factory=dict)

    def mark_missing(self, metric: str, reason: str) -> None:
        self.missing[metric] = reason


def _duration_days(fact: FinancialFact) -> Optional[int]:
    if fact.period_start is None or fact.period_end is None:
        return None
    return (fact.period_end - fact.period_start).days


def _is_quarterly(fact: FinancialFact) -> bool:
    d = _duration_days(fact)
    return d is not None and QUARTER_DAYS[0] <= d <= QUARTER_DAYS[1]


def _is_annual(fact: FinancialFact) -> bool:
    d = _duration_days(fact)
    return d is not None and ANNUAL_DAYS[0] <= d <= ANNUAL_DAYS[1]


def latest_instant(
    facts: list[FinancialFact], reference: Optional[date] = None
) -> Optional[FinancialFact]:
    """El valor de balance más reciente, siempre que no esté obsoleto.

    `reference` es el período más reciente que la empresa reporta en cualquier
    métrica. Un valor que quedó más de MAX_INSTANT_AGE_DAYS atrás corresponde a
    un tag que la empresa dejó de usar, y arrastrarlo produce ratios que mezclan
    años distintos.
    """
    candidates = [f for f in facts if f.value is not None and f.period_end is not None]
    if not candidates:
        return None
    latest = max(candidates, key=lambda f: f.period_end)
    if reference is not None and (reference - latest.period_end).days > MAX_INSTANT_AGE_DAYS:
        return None
    return latest


def balance_reference_date(grouped: dict[str, list[FinancialFact]]) -> Optional[date]:
    """El período de balance más reciente que reporta la empresa."""
    ends = [
        f.period_end
        for name in INSTANT_METRIC_NAMES
        for f in grouped.get(name, [])
        if f.value is not None and f.period_end is not None
    ]
    return max(ends) if ends else None


def instant_near(
    facts: list[FinancialFact],
    target: date,
    tolerance_days: int = 60,
    source_tag: Optional[str] = None,
) -> Optional[FinancialFact]:
    """El valor de balance más cercano a una fecha, para comparaciones interanuales.

    `source_tag` restringe la búsqueda al mismo tag XBRL. Comparar tags distintos
    produce saltos que parecen cambios reales y no lo son: en Ford, medir la
    dilución contra un tag diferente daba 11,74% anual, que es la diferencia
    entre dos formas de contar acciones, no emisión de papeles nuevos.
    """
    candidates = [
        f for f in facts
        if f.value is not None and f.period_end is not None
        and (source_tag is None or f.source_tag == source_tag)
        and abs((f.period_end - target).days) <= tolerance_days
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda f: abs((f.period_end - target).days))


def compute_ttm(facts: list[FinancialFact], end_before: Optional[date] = None) -> tuple[Optional[float], Optional[date], str]:
    """Suma los últimos doce meses de una métrica de flujo.

    Devuelve (valor, fin_del_período, método). El método queda registrado porque
    un TTM armado con 4 trimestres y uno tomado de un anual no son igual de
    frescos, y eso importa al comparar empresas entre sí.
    """
    usable = [f for f in facts if f.value is not None and f.period_end is not None]
    if end_before is not None:
        usable = [f for f in usable if f.period_end <= end_before]
    if not usable:
        return None, None, "sin datos"

    quarters = sorted([f for f in usable if _is_quarterly(f)], key=lambda f: f.period_end, reverse=True)
    if len(quarters) >= 4:
        # Se exige que no se solapen: un YTD mal clasificado inflaría el total.
        picked: list[FinancialFact] = []
        for fact in quarters:
            if any(
                fact.period_start is not None
                and p.period_start is not None
                and fact.period_start < p.period_end
                and p.period_start < fact.period_end
                for p in picked
            ):
                continue
            picked.append(fact)
            if len(picked) == 4:
                break
        if len(picked) == 4:
            span = (picked[0].period_end - picked[-1].period_start).days
            if span >= TTM_MIN_COVERAGE_DAYS:
                return (
                    sum(f.value for f in picked),
                    picked[0].period_end,
                    "4 trimestres",
                )

    annuals = sorted([f for f in usable if _is_annual(f)], key=lambda f: f.period_end, reverse=True)
    if annuals:
        return annuals[0].value, annuals[0].period_end, "ejercicio anual"

    return None, None, "sin 4 trimestres consecutivos ni ejercicio anual"


def _safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def compute_metrics(grouped: dict[str, list[FinancialFact]]) -> FundamentalMetrics:
    """Calcula el set completo de métricas a partir de los facts agrupados."""
    m = FundamentalMetrics()

    def group(name: str) -> list[FinancialFact]:
        return grouped.get(name, [])

    # ── Flujos (TTM) ─────────────────────────────────────────────────────────
    m.revenue_ttm, revenue_end, revenue_method = compute_ttm(group("revenue"))
    if m.revenue_ttm is None:
        m.mark_missing("revenue_ttm", revenue_method)
    m.latest_period_end = revenue_end

    if revenue_end is not None:
        prior_cutoff = date(revenue_end.year - 1, revenue_end.month, min(revenue_end.day, 28))
        m.revenue_ttm_prior, _, _ = compute_ttm(group("revenue"), end_before=prior_cutoff)
        if m.revenue_ttm_prior and m.revenue_ttm is not None and m.revenue_ttm_prior != 0:
            m.revenue_growth_yoy = m.revenue_ttm / m.revenue_ttm_prior - 1
        else:
            m.mark_missing("revenue_growth_yoy", "sin TTM del año anterior para comparar")

    m.gross_profit_ttm, _, _ = compute_ttm(group("grossProfit"))
    m.operating_income_ttm, _, op_method = compute_ttm(group("operatingIncome"))
    if m.operating_income_ttm is None:
        m.mark_missing("operating_income_ttm", op_method)
    m.net_income_ttm, _, _ = compute_ttm(group("netIncome"))

    m.operating_margin = _safe_div(m.operating_income_ttm, m.revenue_ttm)
    if m.operating_margin is None:
        m.mark_missing("operating_margin", "faltan ingresos o resultado operacional TTM")

    m.operating_cf_ttm, _, ocf_method = compute_ttm(group("operatingCashFlow"))
    if m.operating_cf_ttm is None:
        m.mark_missing("operating_cf_ttm", ocf_method)
    m.capex_ttm, _, _ = compute_ttm(group("capitalExpenditure"))

    if m.operating_cf_ttm is not None:
        # El capex viene positivo en XBRL (es un pago); FCF lo resta.
        capex = abs(m.capex_ttm) if m.capex_ttm is not None else 0.0
        m.fcf_ttm = m.operating_cf_ttm - capex
        if m.capex_ttm is None:
            m.mark_missing("capex_ttm", "sin capex reportado: el FCF asume cero")
        m.fcf_margin = _safe_div(m.fcf_ttm, m.revenue_ttm)
    else:
        m.mark_missing("fcf_ttm", "sin flujo operacional TTM")

    # ── Balance (instantáneos) ───────────────────────────────────────────────
    reference = balance_reference_date(grouped)

    def instant(name: str, label: str) -> Optional[float]:
        raw_latest = latest_instant(group(name))
        fact = latest_instant(group(name), reference=reference)
        if fact is None:
            if raw_latest is not None and raw_latest.period_end is not None:
                m.mark_missing(
                    label,
                    f"último valor es de {raw_latest.period_end} ({raw_latest.source_tag}): "
                    f"demasiado viejo frente al balance de {reference}",
                )
            else:
                m.mark_missing(label, "no reportado en los filings disponibles")
            return None
        if m.latest_period_end is None or (fact.period_end and fact.period_end > m.latest_period_end):
            m.latest_period_end = fact.period_end
        if fact.filing_date and (m.latest_filing_date is None or fact.filing_date > m.latest_filing_date):
            m.latest_filing_date = fact.filing_date
        return fact.value

    m.cash = instant("cash", "cash")
    m.current_assets = instant("currentAssets", "current_assets")
    m.current_liabilities = instant("currentLiabilities", "current_liabilities")
    m.total_assets = instant("totalAssets", "total_assets")
    m.total_liabilities = instant("totalLiabilities", "total_liabilities")
    m.stockholders_equity = instant("stockholdersEquity", "stockholders_equity")
    m.short_term_debt = instant("shortTermDebt", "short_term_debt")
    m.long_term_debt = instant("longTermDebt", "long_term_debt")

    if m.short_term_debt is not None or m.long_term_debt is not None:
        m.total_debt = (m.short_term_debt or 0.0) + (m.long_term_debt or 0.0)
        if m.cash is not None:
            m.net_debt = m.total_debt - m.cash
    else:
        m.mark_missing("total_debt", "sin deuda de corto ni de largo plazo reportada")

    m.current_ratio = _safe_div(m.current_assets, m.current_liabilities)
    if m.current_ratio is None:
        m.mark_missing("current_ratio", "faltan activos o pasivos corrientes")

    m.liabilities_to_assets = _safe_div(m.total_liabilities, m.total_assets)
    m.cash_to_revenue = _safe_div(m.cash, m.revenue_ttm)

    if m.stockholders_equity is not None and m.stockholders_equity > 0:
        m.debt_to_equity = _safe_div(m.total_debt, m.stockholders_equity)
    elif m.stockholders_equity is not None:
        # Patrimonio negativo: el ratio no es interpretable, pero el hecho sí
        # importa y lo levanta el hard flag NEGATIVE_EQUITY.
        m.mark_missing("debt_to_equity", "patrimonio negativo: el ratio no es interpretable")

    # ── Acciones y dilución ──────────────────────────────────────────────────
    shares_facts = group("sharesOutstanding")
    latest_shares = latest_instant(shares_facts, reference=reference)
    if latest_shares is None:
        m.mark_missing("shares_outstanding", "sin conteo de acciones reciente")
    else:
        m.shares_outstanding = latest_shares.value
        if latest_shares.period_end:
            year_ago = date(
                latest_shares.period_end.year - 1,
                latest_shares.period_end.month,
                min(latest_shares.period_end.day, 28),
            )
            # Mismo tag a ambos lados: ver la nota en instant_near().
            prior = instant_near(shares_facts, year_ago, source_tag=latest_shares.source_tag)
            if prior is not None and prior.value:
                m.shares_outstanding_prior = prior.value
                m.dilution_yoy = m.shares_outstanding / prior.value - 1
            else:
                m.mark_missing(
                    "dilution_yoy",
                    f"sin conteo comparable de hace un año con el mismo tag ({latest_shares.source_tag})",
                )

    # ── Cash runway ──────────────────────────────────────────────────────────
    # Solo tiene sentido con FCF negativo: en una empresa que genera caja el
    # runway es infinito y publicarlo como número sería engañoso.
    if m.fcf_ttm is not None and m.fcf_ttm < 0:
        if m.cash is not None:
            quarterly_burn = abs(m.fcf_ttm) / 4
            m.cash_runway_quarters = m.cash / quarterly_burn if quarterly_burn > 0 else None
        else:
            m.mark_missing("cash_runway_quarters", "quema caja pero no reporta efectivo")

    m.as_of = m.latest_period_end
    return m
