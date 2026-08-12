"""Tests de la capa de fundamentales.

Los casos vienen de problemas reales encontrados al procesar los filings de Ford,
MARA, NuScale y D-Wave. No son hipotéticos: cada uno produjo un número falso
antes de corregirse.
"""

from datetime import date, datetime, timezone

import pytest

from app.fundamentals.flags import detect_metric_flags, detect_text_flags, strip_html
from app.fundamentals.metrics import FundamentalMetrics, compute_metrics, compute_ttm
from app.fundamentals.normalizer import (
    facts_by_metric,
    normalize_company_facts,
    select_current_facts,
)
from app.fundamentals.profiles import classify, is_supported
from app.fundamentals.score import compute_financial_safety_score
from app.models.fundamentals import FlagSeverity, FundamentalProfile, ScoreStatus
from app.providers.base import FinancialFact


def fact(metric, tag, value, start=None, end=None, filed=None, accn="acc-1", unit="USD"):
    return FinancialFact(
        metric=metric,
        source_tag=tag,
        value=value,
        unit=unit,
        form="10-Q",
        fiscal_year=None,
        fiscal_quarter=None,
        period_start=date.fromisoformat(start) if start else None,
        period_end=date.fromisoformat(end) if end else None,
        filing_date=date.fromisoformat(filed) if filed else None,
        accepted_at=(
            datetime.fromisoformat(filed).replace(tzinfo=timezone.utc) if filed else None
        ),
        accession_no=accn,
    )


def quarters(metric, tag, values, year=2025):
    """Cuatro trimestres consecutivos."""
    spans = [("01-01", "03-31"), ("04-01", "06-30"), ("07-01", "09-30"), ("10-01", "12-31")]
    return [
        fact(metric, tag, v, f"{year}-{s}", f"{year}-{e}", filed=f"{year}-12-31")
        for v, (s, e) in zip(values, spans)
    ]


class TestNormalizer:
    def test_revenues_wins_over_contract_revenue(self):
        """MARA: `Revenues` es el total; el desglose por contrato es el 9%."""
        payload = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {"USD": [
                            {"start": "2026-04-01", "end": "2026-06-30", "val": 349_500_000,
                             "form": "10-Q", "filed": "2026-08-06", "accn": "a"}
                        ]}
                    },
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {"USD": [
                            {"start": "2026-04-01", "end": "2026-06-30", "val": 31_200_000,
                             "form": "10-Q", "filed": "2026-08-06", "accn": "a"}
                        ]}
                    },
                }
            }
        }
        selected = select_current_facts(normalize_company_facts(payload))
        assert len(selected) == 1
        assert list(selected.values())[0].value == 349_500_000

    def test_ignores_8k_preliminary_numbers(self):
        payload = {
            "facts": {"us-gaap": {"Revenues": {"units": {"USD": [
                {"start": "2025-01-01", "end": "2025-12-31", "val": 100, "form": "8-K",
                 "filed": "2026-01-15", "accn": "a"}
            ]}}}}
        }
        assert normalize_company_facts(payload) == []

    def test_restatement_keeps_most_recent_filing(self):
        facts = [
            fact("revenue", "Revenues", 170_572, "2007-01-01", "2007-12-31", filed="2010-02-25", accn="a"),
            fact("revenue", "Revenues", 168_884, "2007-01-01", "2007-12-31", filed="2010-05-07", accn="b"),
        ]
        selected = select_current_facts(facts)
        assert list(selected.values())[0].value == 168_884

    def test_as_of_blocks_future_restatements(self):
        """Sin este corte el backtesting usaría cifras que en la fecha simulada
        todavía no se habían publicado."""
        facts = [
            fact("revenue", "Revenues", 170_572, "2007-01-01", "2007-12-31", filed="2010-02-25", accn="a"),
            fact("revenue", "Revenues", 168_884, "2007-01-01", "2007-12-31", filed="2010-05-07", accn="b"),
        ]
        cutoff = datetime(2010, 3, 1, tzinfo=timezone.utc)
        selected = select_current_facts(facts, as_of=cutoff)
        assert list(selected.values())[0].value == 170_572


class TestTTM:
    def test_sums_four_quarters(self):
        value, end, method = compute_ttm(quarters("revenue", "Revenues", [10, 20, 30, 40]))
        assert value == 100
        assert end == date(2025, 12, 31)
        assert method == "4 trimestres"

    def test_falls_back_to_annual(self):
        facts = [fact("revenue", "Revenues", 500, "2025-01-01", "2025-12-31", filed="2026-02-01")]
        value, _, method = compute_ttm(facts)
        assert value == 500
        assert method == "ejercicio anual"

    def test_ignores_overlapping_ytd_periods(self):
        """Un acumulado del año mezclado con trimestres duplicaría los ingresos."""
        facts = quarters("revenue", "Revenues", [10, 20, 30, 40])
        facts.append(fact("revenue", "Revenues", 60, "2025-01-01", "2025-06-30", filed="2025-07-30"))
        value, _, _ = compute_ttm(facts)
        assert value == 100

    def test_returns_reason_when_impossible(self):
        value, _, method = compute_ttm([])
        assert value is None
        assert method == "sin datos"


class TestBalanceStaleness:
    def test_discards_abandoned_tag(self):
        """Ford dejó de usar LongTermDebtNoncurrent en 2020.

        Sin el control de antigüedad, ese valor de 0,29B se combinaba con la caja
        de 2026 y daba deuda neta negativa para una automotriz apalancada.
        """
        grouped = {
            "cash": [fact("cash", "CashAndCashEquivalentsAtCarryingValue", 17_650, end="2026-03-31", filed="2026-04-30")],
            "longTermDebt": [fact("longTermDebt", "LongTermDebtNoncurrent", 291, end="2020-12-31", filed="2021-02-01")],
            "currentAssets": [fact("currentAssets", "AssetsCurrent", 116_329, end="2026-03-31", filed="2026-04-30")],
        }
        m = compute_metrics(grouped)
        assert m.cash == 17_650
        assert m.long_term_debt is None
        assert m.total_debt is None
        assert "2020-12-31" in m.missing["long_term_debt"]

    def test_keeps_recent_values(self):
        grouped = {
            "cash": [fact("cash", "CashAndCashEquivalentsAtCarryingValue", 100, end="2026-03-31", filed="2026-04-30")],
            "longTermDebt": [fact("longTermDebt", "LongTermDebtNoncurrent", 40, end="2026-03-31", filed="2026-04-30")],
        }
        m = compute_metrics(grouped)
        assert m.total_debt == 40
        assert m.net_debt == -60


class TestDilution:
    def test_compares_within_same_tag(self):
        """Cambiar de tag no es dilución.

        En Ford, medir contra un tag distinto daba 11,74% anual, que era la
        diferencia entre dos formas de contar acciones.
        """
        grouped = {
            "sharesOutstanding": [
                fact("sharesOutstanding", "EntityCommonStockSharesOutstanding", 3_730_000, end="2026-03-31", filed="2026-04-30", unit="shares"),
                fact("sharesOutstanding", "CommonStockSharesIssued", 3_340_000, end="2025-03-31", filed="2025-04-30", unit="shares"),
            ]
        }
        m = compute_metrics(grouped)
        assert m.shares_outstanding == 3_730_000
        assert m.dilution_yoy is None
        assert "mismo tag" in m.missing["dilution_yoy"]

    def test_real_dilution_is_measured(self):
        grouped = {
            "sharesOutstanding": [
                fact("sharesOutstanding", "CommonStockSharesOutstanding", 110, end="2026-03-31", filed="2026-04-30", unit="shares"),
                fact("sharesOutstanding", "CommonStockSharesOutstanding", 100, end="2025-03-31", filed="2025-04-30", unit="shares"),
            ]
        }
        m = compute_metrics(grouped)
        assert m.dilution_yoy == pytest.approx(0.10)


class TestRunway:
    def test_only_for_cash_burners(self):
        grouped = {
            "operatingCashFlow": quarters("operatingCashFlow", "NetCashProvidedByUsedInOperatingActivities", [-100, -100, -100, -100]),
            "cash": [fact("cash", "CashAndCashEquivalentsAtCarryingValue", 800, end="2025-12-31", filed="2026-02-01")],
        }
        m = compute_metrics(grouped)
        assert m.fcf_ttm == -400
        assert m.cash_runway_quarters == pytest.approx(8.0)

    def test_profitable_company_has_no_runway(self):
        grouped = {
            "operatingCashFlow": quarters("operatingCashFlow", "NetCashProvidedByUsedInOperatingActivities", [100, 100, 100, 100]),
            "cash": [fact("cash", "CashAndCashEquivalentsAtCarryingValue", 800, end="2025-12-31", filed="2026-02-01")],
        }
        m = compute_metrics(grouped)
        assert m.cash_runway_quarters is None


class TestProfiles:
    def test_mature_profitable(self):
        m = FundamentalMetrics(revenue_ttm=184_000_000_000, operating_income_ttm=4_700_000_000,
                               revenue_growth_yoy=0.022)
        assert classify(m) == FundamentalProfile.MATURE_PROFITABLE

    def test_growth_profitable_needs_high_growth(self):
        m = FundamentalMetrics(revenue_ttm=500_000_000, operating_income_ttm=50_000_000,
                               revenue_growth_yoy=0.35)
        assert classify(m) == FundamentalProfile.GROWTH_PROFITABLE

    def test_growth_preprofit(self):
        m = FundamentalMetrics(revenue_ttm=840_000_000, operating_income_ttm=-855_000_000)
        assert classify(m) == FundamentalProfile.GROWTH_PREPROFIT

    def test_development_stage_by_low_revenue(self):
        m = FundamentalMetrics(revenue_ttm=1_000_000, operating_income_ttm=-50_000_000)
        assert classify(m) == FundamentalProfile.DEVELOPMENT_STAGE

    def test_sic_marks_reit_and_financial(self):
        m = FundamentalMetrics(revenue_ttm=1e9, operating_income_ttm=1e8)
        assert classify(m, sic="6798") == FundamentalProfile.REIT
        assert classify(m, sic="6022") == FundamentalProfile.FINANCIAL
        assert classify(m, sic="6311") == FundamentalProfile.FINANCIAL

    def test_finance_services_catchall_is_still_evaluated(self):
        """MARA tiene SIC 6199 y es una minera de bitcoin, no un banco.

        SEC usa 6199 como cajón de sastre para cripto y fintech operativas. Sus
        estados sí admiten métricas industriales, así que no se descartan."""
        m = FundamentalMetrics(revenue_ttm=840_000_000, operating_income_ttm=-855_000_000)
        assert classify(m, sic="6199") == FundamentalProfile.GROWTH_PREPROFIT

    def test_reit_and_financial_are_not_scored_in_v1(self):
        assert not is_supported(FundamentalProfile.REIT)
        assert not is_supported(FundamentalProfile.FINANCIAL)


class TestFlags:
    def test_short_runway_vetoes(self):
        flags = detect_metric_flags(FundamentalMetrics(cash_runway_quarters=1.5))
        assert flags[0].severity == FlagSeverity.REJECT

    def test_medium_runway_only_penalizes(self):
        flags = detect_metric_flags(FundamentalMetrics(cash_runway_quarters=4.0))
        assert flags[0].severity == FlagSeverity.PENALIZE

    def test_healthy_runway_raises_nothing(self):
        assert detect_metric_flags(FundamentalMetrics(cash_runway_quarters=12.0)) == []

    def test_negative_equity_and_dilution(self):
        flags = detect_metric_flags(
            FundamentalMetrics(stockholders_equity=-500, dilution_yoy=0.40)
        )
        names = {f.flag.value for f in flags}
        assert names == {"NEGATIVE_EQUITY", "EXTREME_DILUTION"}

    def test_going_concern_is_detected_with_evidence(self):
        text = (
            "<p>These conditions raise substantial doubt about the Company's ability "
            "to continue as a going concern for one year.</p>"
        )
        flags = detect_text_flags(text, section="10-K 2026-03-01")
        assert len(flags) == 1
        assert flags[0].severity == FlagSeverity.REJECT
        # La evidencia trazable es obligatoria: ningún flag sin su cita.
        assert "going concern" in flags[0].text_excerpt
        assert flags[0].origin == "FILING_TEXT"

    def test_ordinary_going_concern_mention_is_not_flagged(self):
        """Casi todos los 10-K nombran la frase al describir criterios contables."""
        text = "The financial statements are prepared on a going concern basis."
        assert detect_text_flags(text) == []

    def test_material_weakness_penalizes(self):
        flags = detect_text_flags("We identified a material weakness in our internal control over financial reporting.")
        assert flags[0].flag.value == "AUDITOR_WARNING"
        assert flags[0].severity == FlagSeverity.PENALIZE

    def test_strip_html_removes_scripts_and_tags(self):
        assert "alert" not in strip_html("<script>alert(1)</script><p>Hola</p>")
        assert "Hola" in strip_html("<script>alert(1)</script><p>Hola</p>")


class TestScore:
    def _solid(self):
        return FundamentalMetrics(
            revenue_ttm=1_000_000, revenue_growth_yoy=0.25, operating_margin=0.18,
            current_ratio=2.8, debt_to_equity=0.2, net_debt=-200_000,
            fcf_ttm=180_000, dilution_yoy=-0.01, cash=300_000,
        )

    def test_solid_company_scores_high(self):
        result = compute_financial_safety_score(
            self._solid(), FundamentalProfile.MATURE_PROFITABLE, []
        )
        assert result.status == ScoreStatus.OK
        assert result.score > 80

    def test_every_component_is_explainable(self):
        result = compute_financial_safety_score(
            self._solid(), FundamentalProfile.MATURE_PROFITABLE, []
        )
        # "¿Por qué 84?" se responde sin recalcular nada.
        assert len(result.components) == 8
        for component in result.components:
            assert component.note
            assert component.weight > 0
        assert sum(c.contribution for c in result.components) == pytest.approx(
            result.score / 100 if not result.penalties else pytest.approx(result.score / 100, abs=0.3),
            abs=0.01,
        )

    def test_reject_flag_forces_zero(self):
        """Una prima enorme no compensa un going concern."""
        flags = detect_text_flags(
            "raise substantial doubt about our ability to continue as a going concern"
        )
        result = compute_financial_safety_score(
            self._solid(), FundamentalProfile.MATURE_PROFITABLE, flags
        )
        assert result.score == 0.0
        assert result.penalties[0]["severity"] == "REJECT"

    def test_penalize_flags_subtract(self):
        clean = compute_financial_safety_score(self._solid(), FundamentalProfile.MATURE_PROFITABLE, [])
        penalized = compute_financial_safety_score(
            self._solid(),
            FundamentalProfile.MATURE_PROFITABLE,
            detect_metric_flags(FundamentalMetrics(stockholders_equity=-1)),
        )
        assert penalized.score < clean.score

    def test_unsupported_profile_gets_no_invented_score(self):
        result = compute_financial_safety_score(self._solid(), FundamentalProfile.REIT, [])
        assert result.score is None
        assert result.status == ScoreStatus.UNSUPPORTED_PROFILE

    def test_insufficient_data_returns_none_not_a_low_score(self):
        """Sin datos no es lo mismo que ser frágil."""
        result = compute_financial_safety_score(
            FundamentalMetrics(current_ratio=1.5), FundamentalProfile.MATURE_PROFITABLE, []
        )
        assert result.score is None
        assert result.status == ScoreStatus.INSUFFICIENT_DATA

    def test_missing_components_do_not_count_as_zero(self):
        """Renormalizar sobre lo disponible, no castigar por ausencia de dato."""
        partial = FundamentalMetrics(
            current_ratio=2.8, debt_to_equity=0.2, revenue_ttm=1_000_000,
            net_debt=-200_000, fcf_ttm=180_000, operating_margin=0.18,
        )
        result = compute_financial_safety_score(partial, FundamentalProfile.MATURE_PROFITABLE, [])
        assert result.status == ScoreStatus.OK
        assert result.coverage < 1.0
        assert result.score > 70
