"""Normalización XBRL: tags de SEC → métricas canónicas.

**Nunca confiar en un único tag.** Las empresas eligen entre varios tags válidos
para el mismo concepto y cambian de elección entre ejercicios. Ford reporta
ingresos como `Revenues`; otras usan
`RevenueFromContractWithCustomerExcludingAssessedTax`. Cada métrica tiene una
lista de aliases en orden de preferencia.

Un mismo período aparece en varios filings con valores distintos (restatements):
Ford tiene 231 facts de `Revenues` para 98 períodos. Se conservan todos con su
`accepted_at`; elegir cuál usar es decisión de quien consulta, y en backtesting
esa decisión depende de la fecha de simulación.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

from ..providers.base import FinancialFact

# Orden = preferencia. El primero que exista para un período gana.
METRIC_ALIASES: dict[str, list[str]] = {
    # `Revenues` va primero porque es el total consolidado. Los
    # `RevenueFromContractWithCustomer*` son un desglose que puede cubrir solo
    # parte del negocio: MARA reporta 31,2M ahí (hosting) contra 349,5M en
    # `Revenues`, porque la minería de bitcoin no es "contrato con cliente".
    # Preferir el desglose capturaba el 9% de sus ingresos y hundía todos los
    # márgenes.
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "RevenuesNetOfInterestExpense",
    ],
    "grossProfit": ["GrossProfit"],
    "operatingIncome": [
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    ],
    "netIncome": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashAndCashEquivalentsIncludingDiscontinuedOperations",
    ],
    "shortTermInvestments": [
        "ShortTermInvestments",
        "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    ],
    "currentAssets": ["AssetsCurrent"],
    "currentLiabilities": ["LiabilitiesCurrent"],
    "totalAssets": ["Assets"],
    "totalLiabilities": ["Liabilities"],
    "stockholdersEquity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "shortTermDebt": [
        "DebtCurrent",
        "ShortTermBorrowings",
        "LongTermDebtCurrent",
        "NotesPayableCurrent",
    ],
    "longTermDebt": [
        "LongTermDebtNoncurrent",
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
    ],
    "operatingCashFlow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capitalExpenditure": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquirePropertyPlantAndEquipmentExcludingInterestCapitalized",
    ],
    "sharesOutstanding": [
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
        "CommonStockSharesIssued",
    ],
    "dilutedShares": [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ],
    "interestExpense": ["InterestExpense", "InterestExpenseDebt", "InterestIncomeExpenseNet"],
}

# Métricas de balance: valor instantáneo, sin período de inicio.
INSTANT_METRICS = frozenset(
    {
        "cash",
        "shortTermInvestments",
        "currentAssets",
        "currentLiabilities",
        "totalAssets",
        "totalLiabilities",
        "stockholdersEquity",
        "shortTermDebt",
        "longTermDebt",
        "sharesOutstanding",
    }
)

# Formularios aceptados. Se excluyen 8-K y similares: reportan cifras
# preliminares que después se corrigen en el 10-Q/10-K.
PRIMARY_FORMS = frozenset({"10-K", "10-Q", "10-K/A", "10-Q/A", "20-F", "40-F"})

_TAG_TO_METRIC: dict[str, tuple[str, int]] = {}
for _metric, _tags in METRIC_ALIASES.items():
    for _rank, _tag in enumerate(_tags):
        _TAG_TO_METRIC.setdefault(_tag, (_metric, _rank))


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _accepted_from_filed(filed: Optional[str]) -> Optional[datetime]:
    """companyfacts trae `filed` (fecha) pero no la hora de aceptación.

    Se usa el fin del día de presentación como cota superior conservadora: para
    evitar look-ahead, la duda tiene que resolverse a favor de "todavía no estaba
    disponible".
    """
    parsed = _parse_date(filed)
    if parsed is None:
        return None
    return datetime(parsed.year, parsed.month, parsed.day, 23, 59, 59, tzinfo=timezone.utc)


def normalize_company_facts(
    payload: dict[str, Any], units: Iterable[str] = ("USD", "shares")
) -> list[FinancialFact]:
    """Aplana companyfacts a métricas canónicas conservando el tag de origen."""
    facts: list[FinancialFact] = []
    taxonomies = payload.get("facts", {})
    accepted_units = set(units)

    for taxonomy_name, tags in taxonomies.items():
        for tag, tag_data in tags.items():
            mapped = _TAG_TO_METRIC.get(tag)
            if mapped is None:
                continue
            metric, _rank = mapped
            for unit, entries in tag_data.get("units", {}).items():
                if accepted_units and unit not in accepted_units:
                    continue
                for entry in entries:
                    form = entry.get("form")
                    if form not in PRIMARY_FORMS:
                        continue
                    facts.append(
                        FinancialFact(
                            metric=metric,
                            source_tag=tag,
                            value=entry.get("val"),
                            unit=unit,
                            form=form,
                            fiscal_year=entry.get("fy"),
                            fiscal_quarter=None,
                            period_start=_parse_date(entry.get("start")),
                            period_end=_parse_date(entry.get("end")),
                            filing_date=_parse_date(entry.get("filed")),
                            accepted_at=_accepted_from_filed(entry.get("filed")),
                            accession_no=entry.get("accn"),
                        )
                    )
    return facts


def _period_key(fact: FinancialFact) -> tuple:
    return (fact.metric, fact.period_start, fact.period_end)


def select_current_facts(
    facts: Iterable[FinancialFact], as_of: Optional[datetime] = None
) -> dict[tuple, FinancialFact]:
    """Para cada (métrica, período) elige el fact vigente.

    Criterios, en orden:
      1. Solo lo publicado antes de `as_of` — sin esto el backtesting usaría
         restatements que en la fecha simulada no existían.
      2. El alias más preferido de la métrica.
      3. La presentación más reciente (un restatement corrige al original).
    """
    best: dict[tuple, FinancialFact] = {}
    for fact in facts:
        if fact.value is None or fact.period_end is None:
            continue
        if as_of is not None and fact.accepted_at is not None and fact.accepted_at > as_of:
            continue

        key = _period_key(fact)
        rank = _TAG_TO_METRIC.get(fact.source_tag, (fact.metric, 99))[1]
        current = best.get(key)
        if current is None:
            best[key] = fact
            continue

        current_rank = _TAG_TO_METRIC.get(current.source_tag, (current.metric, 99))[1]
        if rank < current_rank:
            best[key] = fact
        elif rank == current_rank:
            new_filed = fact.filing_date or date.min
            old_filed = current.filing_date or date.min
            if new_filed > old_filed:
                best[key] = fact
    return best


def facts_by_metric(
    facts: Iterable[FinancialFact], as_of: Optional[datetime] = None
) -> dict[str, list[FinancialFact]]:
    """Agrupa los facts vigentes por métrica, ordenados por fin de período."""
    selected = select_current_facts(facts, as_of)
    grouped: dict[str, list[FinancialFact]] = {}
    for fact in selected.values():
        grouped.setdefault(fact.metric, []).append(fact)
    for rows in grouped.values():
        rows.sort(key=lambda f: (f.period_end or date.min))
    return grouped
