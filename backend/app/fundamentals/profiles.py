"""Clasificación del perfil fundamental de una empresa.

No se evalúa igual a Ford que a una pre-revenue. Un FCF negativo es una alarma en
una madura y es el plan de negocio en una en desarrollo; un current ratio de 8 es
excelente en la primera y solo dice "acaba de levantar capital" en la segunda.
El perfil decide qué pesa en el score.
"""

from __future__ import annotations

from typing import Optional

from ..models.fundamentals import FundamentalProfile
from .metrics import FundamentalMetrics

# El criterio no es "SEC lo puso en el rango financiero" sino "sus estados
# financieros exigen métricas sectoriales distintas". Un banco no tiene current
# ratio interpretable; una minera de bitcoin sí.
#
# Por eso se excluyen rangos puntuales y no el bloque 6000–6799 completo: el SIC
# 6199 ("Finance Services") es un cajón de sastre donde SEC clasifica cripto,
# fintech y holdings operativos. MARA vive ahí y tiene ingresos, capex y flujo de
# caja perfectamente evaluables — dejarla sin score la sacaba del scanner por un
# tecnicismo de clasificación.
REIT_SIC = {6798}
FINANCIAL_SIC_RANGES = (
    (6020, 6036),  # bancos comerciales y de ahorro
    (6200, 6299),  # brokers, bolsas y servicios de inversión
    (6300, 6411),  # seguros
    (6726, 6726),  # fondos y sociedades de inversión
)

# Ingresos bajo este umbral describen a una empresa que todavía no vende de
# verdad: los ratios sobre ingresos se vuelven ruido.
DEVELOPMENT_REVENUE_CEILING = 10_000_000
HIGH_GROWTH_THRESHOLD = 0.20


def classify(metrics: FundamentalMetrics, sic: Optional[str] = None) -> FundamentalProfile:
    if sic:
        try:
            sic_code = int(str(sic).strip())
        except (TypeError, ValueError):
            sic_code = None
        if sic_code is not None:
            if sic_code in REIT_SIC:
                return FundamentalProfile.REIT
            if any(low <= sic_code <= high for low, high in FINANCIAL_SIC_RANGES):
                return FundamentalProfile.FINANCIAL

    revenue = metrics.revenue_ttm
    operating = metrics.operating_income_ttm

    if revenue is None and operating is None:
        return FundamentalProfile.UNKNOWN

    if revenue is not None and revenue < DEVELOPMENT_REVENUE_CEILING:
        return FundamentalProfile.DEVELOPMENT_STAGE

    if operating is None:
        return FundamentalProfile.UNKNOWN

    growth = metrics.revenue_growth_yoy
    if operating > 0:
        if growth is not None and growth >= HIGH_GROWTH_THRESHOLD:
            return FundamentalProfile.GROWTH_PROFITABLE
        return FundamentalProfile.MATURE_PROFITABLE

    return FundamentalProfile.GROWTH_PREPROFIT


# v1 puntúa con confianza estos cuatro. FINANCIAL y REIT necesitan métricas
# sectoriales (adecuación de capital, FFO) que todavía no existen, así que se
# registran sin score en vez de recibir uno inventado.
SUPPORTED_PROFILES = frozenset(
    {
        FundamentalProfile.MATURE_PROFITABLE,
        FundamentalProfile.GROWTH_PROFITABLE,
        FundamentalProfile.GROWTH_PREPROFIT,
        FundamentalProfile.DEVELOPMENT_STAGE,
    }
)


def is_supported(profile: FundamentalProfile) -> bool:
    return profile in SUPPORTED_PROFILES


PROFILE_LABEL = {
    FundamentalProfile.MATURE_PROFITABLE: "Madura y rentable",
    FundamentalProfile.GROWTH_PROFITABLE: "Crecimiento rentable",
    FundamentalProfile.GROWTH_PREPROFIT: "Crecimiento sin utilidades",
    FundamentalProfile.DEVELOPMENT_STAGE: "En desarrollo",
    FundamentalProfile.FINANCIAL: "Financiera",
    FundamentalProfile.REIT: "REIT",
    FundamentalProfile.UNKNOWN: "Sin clasificar",
}
