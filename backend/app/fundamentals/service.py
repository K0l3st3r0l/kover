"""Ingesta de fundamentales: SEC → facts → métricas → perfil → flags → snapshot.

El snapshot resultante nunca se sobrescribe si ya existe uno para la misma
fecha: es la base del backtesting sin look-ahead.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..logging_config import LogContext, get_logger
from ..models import Instrument
from ..models.fundamentals import (
    CorporateEventRow,
    FinancialFact as FinancialFactRow,
    FundamentalProfile,
    FundamentalSnapshot,
    RiskFlag,
    ScoreStatus,
    SecFiling,
)
from ..providers.base import ProviderError
from ..providers.sec_edgar import SecEdgarFundamentalsProvider, pad_cik
from .flags import DetectedFlag, detect_metric_flags, detect_text_flags
from .metrics import compute_metrics
from .normalizer import facts_by_metric, normalize_company_facts
from .profiles import classify
from .score import compute_financial_safety_score

logger = get_logger(__name__)

# Formularios cuyo texto se revisa buscando frases de riesgo.
TEXT_SCAN_FORMS = ["10-K", "10-Q"]
TEXT_SCAN_LIMIT = 2


def get_or_create_instrument(
    db: Session, symbol: str, provider: SecEdgarFundamentalsProvider
) -> Instrument:
    symbol = symbol.upper()
    instrument = db.query(Instrument).filter(Instrument.symbol == symbol).first()
    if instrument is None:
        instrument = Instrument(symbol=symbol)
        db.add(instrument)
    if not instrument.sec_cik:
        cik = provider.resolve_cik(symbol)
        if cik is None:
            raise ProviderError("sec_edgar", f"{symbol} no está en el mapa de tickers de SEC", retryable=False)
        instrument.sec_cik = cik
    if not instrument.name:
        instrument.name = provider.resolve_name(symbol)
    db.flush()
    return instrument


def _store_filings(
    db: Session, instrument: Instrument, provider: SecEdgarFundamentalsProvider
) -> list[SecFiling]:
    filings = provider.get_filings(instrument.sec_cik, forms=["10-K", "10-Q", "8-K"], limit=40)
    existing = {
        f.accession_no
        for f in db.query(SecFiling.accession_no)
        .filter(SecFiling.instrument_id == instrument.id)
        .all()
    }
    stored: list[SecFiling] = []
    for filing in filings:
        if filing.accession_no in existing:
            continue
        row = SecFiling(
            instrument_id=instrument.id,
            accession_no=filing.accession_no,
            form=filing.form,
            filing_date=filing.filing_date,
            accepted_at=filing.accepted_at,
            period_end=filing.period_end,
            primary_doc=filing.primary_doc,
            is_xbrl=True,
        )
        db.add(row)
        stored.append(row)
    db.flush()
    return (
        db.query(SecFiling)
        .filter(SecFiling.instrument_id == instrument.id)
        .order_by(SecFiling.accepted_at.desc())
        .all()
    )


def _store_facts(db: Session, instrument: Instrument, facts: list) -> int:
    existing = {
        (row.metric, row.source_tag, row.period_start, row.period_end, row.accession_no)
        for row in db.query(
            FinancialFactRow.metric,
            FinancialFactRow.source_tag,
            FinancialFactRow.period_start,
            FinancialFactRow.period_end,
            FinancialFactRow.accession_no,
        ).filter(FinancialFactRow.instrument_id == instrument.id)
    }
    inserted = 0
    for fact in facts:
        key = (fact.metric, fact.source_tag, fact.period_start, fact.period_end, fact.accession_no)
        if key in existing:
            continue
        existing.add(key)
        db.add(
            FinancialFactRow(
                instrument_id=instrument.id,
                metric=fact.metric,
                source_tag=fact.source_tag,
                value=fact.value,
                unit=fact.unit,
                form=fact.form,
                fiscal_year=fact.fiscal_year,
                period_start=fact.period_start,
                period_end=fact.period_end,
                filing_date=fact.filing_date,
                accepted_at=fact.accepted_at,
                accession_no=fact.accession_no,
            )
        )
        inserted += 1
    db.flush()
    return inserted


def _scan_filing_text(
    provider: SecEdgarFundamentalsProvider,
    instrument: Instrument,
    filings: list[SecFiling],
) -> list[DetectedFlag]:
    """Revisa el texto de los últimos 10-K/10-Q buscando frases de riesgo."""
    detected: list[DetectedFlag] = []
    scanned = 0
    for filing in filings:
        if filing.form not in TEXT_SCAN_FORMS or not filing.primary_doc:
            continue
        try:
            text = provider.get_filing_text(instrument.sec_cik, filing.accession_no, filing.primary_doc)
        except ProviderError as exc:
            logger.warning(
                "no se pudo leer el filing",
                extra={"ticker": instrument.symbol, "accession": filing.accession_no, "error": str(exc)[:200]},
            )
            continue
        for flag in detect_text_flags(text, section=f"{filing.form} {filing.filing_date}"):
            flag.detail = {**(flag.detail or {}), "filing_id": filing.id}
            detected.append(flag)
        scanned += 1
        if scanned >= TEXT_SCAN_LIMIT:
            break
    return detected


def _dedupe_flags(flags: list[DetectedFlag]) -> list[DetectedFlag]:
    """Un flag por tipo, quedándose con la severidad más alta."""
    order = {"REJECT": 0, "PENALIZE": 1, "INFO": 2}
    best: dict[str, DetectedFlag] = {}
    for flag in flags:
        key = flag.flag.value
        current = best.get(key)
        if current is None or order[flag.severity.value] < order[current.severity.value]:
            best[key] = flag
    return list(best.values())


def refresh_fundamentals(
    db: Session,
    symbol: str,
    provider: Optional[SecEdgarFundamentalsProvider] = None,
    scan_text: bool = True,
    recompute: bool = False,
) -> dict[str, Any]:
    """Descarga, normaliza, puntúa y persiste los fundamentales de un ticker."""
    provider = provider or SecEdgarFundamentalsProvider()
    symbol = symbol.upper()

    with LogContext(provider="sec_edgar", ticker=symbol):
        instrument = get_or_create_instrument(db, symbol, provider)
        filings = _store_filings(db, instrument, provider)

        payload = provider.get_company_facts(instrument.sec_cik)
        raw_facts = normalize_company_facts(payload)
        inserted = _store_facts(db, instrument, raw_facts)

        grouped = facts_by_metric(raw_facts)
        metrics = compute_metrics(grouped)

        # El SIC viene en submissions y decide FINANCIAL/REIT antes que cualquier ratio.
        sic = payload.get("sic") or _sic_from_submissions(provider, instrument.sec_cik)

        profile = classify(metrics, sic)

        latest_filing = filings[0] if filings else None
        filing_age = None
        if latest_filing is not None:
            filing_age = (date.today() - latest_filing.filing_date).days

        flags = detect_metric_flags(metrics, filing_age_days=filing_age)
        if scan_text:
            flags.extend(_scan_filing_text(provider, instrument, filings))
        flags = _dedupe_flags(flags)

        result = compute_financial_safety_score(metrics, profile, flags)

        _store_flags(db, instrument, flags)
        snapshot = _store_snapshot(
            db, instrument, metrics, profile, result, latest_filing, recompute=recompute
        )
        db.commit()

        logger.info(
            "fundamentales actualizados",
            extra={
                "profile": profile.value,
                "score": result.score,
                "status": result.status.value,
                "facts_nuevos": inserted,
                "flags": [f.flag.value for f in flags],
            },
        )

    return {
        "symbol": symbol,
        "cik": instrument.sec_cik,
        "profile": profile.value,
        "score": result.score,
        "status": result.status.value,
        "snapshot_id": snapshot.id,
        "facts_inserted": inserted,
        "flags": [f.flag.value for f in flags],
    }


def _sic_from_submissions(provider: SecEdgarFundamentalsProvider, cik: str) -> Optional[str]:
    try:
        payload = provider._get_json(
            f"https://data.sec.gov/submissions/CIK{pad_cik(cik)}.json",
            cache_key=f"submissions_{pad_cik(cik)}",
        )
        return payload.get("sic")
    except ProviderError:
        return None


def _store_flags(db: Session, instrument: Instrument, flags: list[DetectedFlag]) -> None:
    """Cierra los flags que dejaron de detectarse y agrega los nuevos."""
    now = datetime.now(timezone.utc)
    active = {
        row.flag: row
        for row in db.query(RiskFlag).filter(
            RiskFlag.instrument_id == instrument.id, RiskFlag.resolved_at.is_(None)
        )
    }
    detected_names = {f.flag.value for f in flags}

    for name, row in active.items():
        if name not in detected_names:
            row.resolved_at = now

    for flag in flags:
        if flag.flag.value in active:
            continue
        db.add(
            RiskFlag(
                instrument_id=instrument.id,
                flag=flag.flag.value,
                severity=flag.severity.value,
                origin=flag.origin,
                filing_id=(flag.detail or {}).get("filing_id"),
                section=flag.section,
                text_excerpt=flag.text_excerpt,
                detail=flag.detail,
            )
        )
    db.flush()


def _store_snapshot(
    db: Session,
    instrument: Instrument,
    metrics,
    profile: FundamentalProfile,
    result,
    latest_filing: Optional[SecFiling],
    recompute: bool = False,
) -> FundamentalSnapshot:
    as_of = metrics.as_of or date.today()
    accepted_at = latest_filing.accepted_at if latest_filing else datetime.now(timezone.utc)

    existing = (
        db.query(FundamentalSnapshot)
        .filter(
            FundamentalSnapshot.instrument_id == instrument.id,
            FundamentalSnapshot.as_of_date == as_of,
        )
        .first()
    )
    if existing is not None and not recompute:
        # Un snapshot histórico no se reescribe: si los datos de ese período
        # cambiaron por un restatement, eso es un snapshot nuevo con otra fecha.
        return existing

    if existing is not None:
        # `recompute` existe para cuando cambia la LÓGICA de cálculo, no los
        # datos. La inmutabilidad protege contra look-ahead —no reescribir con
        # información futura—, no obliga a conservar el resultado de un scorer
        # con un bug. Sin esta puerta, corregir el clasificador dejaría los
        # snapshots viejos mintiendo para siempre.
        db.delete(existing)
        db.flush()

    snapshot = FundamentalSnapshot(
        instrument_id=instrument.id,
        as_of_date=as_of,
        accepted_at=accepted_at,
        profile=profile.value,
        score_status=result.status.value,
        financial_safety_score=result.score,
        revenue_ttm=metrics.revenue_ttm,
        revenue_growth_yoy=metrics.revenue_growth_yoy,
        gross_profit_ttm=metrics.gross_profit_ttm,
        operating_income_ttm=metrics.operating_income_ttm,
        net_income_ttm=metrics.net_income_ttm,
        operating_margin=metrics.operating_margin,
        cash=metrics.cash,
        current_assets=metrics.current_assets,
        current_liabilities=metrics.current_liabilities,
        total_assets=metrics.total_assets,
        total_liabilities=metrics.total_liabilities,
        stockholders_equity=metrics.stockholders_equity,
        short_term_debt=metrics.short_term_debt,
        long_term_debt=metrics.long_term_debt,
        total_debt=metrics.total_debt,
        net_debt=metrics.net_debt,
        operating_cf_ttm=metrics.operating_cf_ttm,
        capex_ttm=metrics.capex_ttm,
        fcf_ttm=metrics.fcf_ttm,
        fcf_margin=metrics.fcf_margin,
        current_ratio=metrics.current_ratio,
        debt_to_equity=metrics.debt_to_equity,
        shares_outstanding=metrics.shares_outstanding,
        dilution_yoy=metrics.dilution_yoy,
        cash_runway_quarters=metrics.cash_runway_quarters,
        components=result.as_dict(),
        missing_metrics=metrics.missing,
        source_filing_id=latest_filing.id if latest_filing else None,
    )
    db.add(snapshot)
    db.flush()
    return snapshot
