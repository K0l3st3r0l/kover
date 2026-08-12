"""Orquestador de Stage 1 (universo) + Stage 3 (riesgo de mercado).

Stage 2 (puerta fundamental) NO se ejecuta acá: dispararía cientos de
descargas SEC cada corrida, y esa capa ya tiene su propio job diario
(`fundamentals_refresh`) con caché de filings. El funnel solo *lee* el
`FundamentalSnapshot` más reciente si existe — nunca lo fuerza. Un candidato
sin fundamentales todavía no es un candidato rechazado, es uno pendiente: se
expone así en la API, nunca como cero.

Stage 4 (cadenas de opciones con precios) es K4 y no vive acá — la
optionabilidad que se chequea en Stage 1 es solo "¿aparece en el directorio
de símbolos de CBOE?", no una cotización.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timezone
from typing import Any, Optional

import pandas as pd
from sqlalchemy.orm import Session

from ..logging_config import LogContext, get_logger
from ..market.market_data import MarketDataService
from ..models import AppSetting, Instrument, MarketRiskSnapshot, StockDailyBar
from ..providers.nasdaq_universe import NasdaqUniverseProvider
from .market_risk import Bar, compute_market_safety_score, compute_metrics
from .universe import (
    REASON_OPTIONABLE_CHECK_FAILED,
    STAGE_LIQUIDITY,
    STAGE_OPTIONABLE,
    UniverseCandidate,
    run_universe_scan,
)

logger = get_logger(__name__)

LAST_RUN_SETTING_KEY = "scanner:universe:last_run"

_run_lock = threading.Lock()
_is_running = False


def is_running() -> bool:
    return _is_running


def get_last_run(db: Session) -> Optional[dict]:
    row = (
        db.query(AppSetting)
        .filter(AppSetting.user_id.is_(None), AppSetting.key == LAST_RUN_SETTING_KEY)
        .first()
    )
    return row.value if row else None


def _store_last_run(db: Session, summary: dict) -> None:
    row = (
        db.query(AppSetting)
        .filter(AppSetting.user_id.is_(None), AppSetting.key == LAST_RUN_SETTING_KEY)
        .first()
    )
    if row is None:
        row = AppSetting(user_id=None, key=LAST_RUN_SETTING_KEY, value=summary)
        db.add(row)
    else:
        row.value = summary
    db.commit()


def _get_or_create_instruments(db: Session, candidates: list[UniverseCandidate]) -> dict[str, Instrument]:
    symbols = [c.symbol for c in candidates]
    existing = {
        i.symbol: i
        for i in db.query(Instrument).filter(Instrument.symbol.in_(symbols)).all()
    }
    now = datetime.now(timezone.utc)
    for candidate in candidates:
        instrument = existing.get(candidate.symbol)
        if instrument is None:
            instrument = Instrument(symbol=candidate.symbol)
            db.add(instrument)
            existing[candidate.symbol] = instrument
        instrument.name = candidate.name or instrument.name
        instrument.exchange = candidate.exchange or instrument.exchange
        if instrument.instrument_type is None:
            instrument.instrument_type = "STOCK"
        instrument.is_active = True
        if candidate.is_optionable is not None:
            instrument.is_optionable = candidate.is_optionable
            instrument.optionable_checked_at = now
    db.flush()
    return existing


def _update_universe_stage(db: Session, instruments: dict[str, Instrument], candidates: list[UniverseCandidate]) -> None:
    now = datetime.now(timezone.utc)
    seen_symbols = set()
    for candidate in candidates:
        instrument = instruments[candidate.symbol]
        instrument.universe_stage = candidate.stage_reached
        instrument.universe_rejected_reason = candidate.rejected_reason
        instrument.universe_checked_at = now
        seen_symbols.add(candidate.symbol)

    # Lo que estaba marcado en el universo antes y hoy no reapareció (salió de
    # la banda de precio, se deslistó, o el proveedor no lo devolvió): no se
    # borra el instrumento —puede tener campaigns históricas— pero se limpia
    # el estado de universo para que no aparezca como vigente.
    stale = (
        db.query(Instrument)
        .filter(
            Instrument.universe_stage.isnot(None),
            Instrument.universe_checked_at < now,
            ~Instrument.symbol.in_(seen_symbols),
        )
        .all()
    )
    for instrument in stale:
        instrument.universe_stage = None
        instrument.universe_rejected_reason = "NO_LONGER_IN_UNIVERSE"
        instrument.universe_checked_at = now
    db.flush()


def _bars_to_daily_bar_rows(instrument_id: int, bars: list[Bar], existing_dates: set[date]) -> list[StockDailyBar]:
    rows = []
    for bar in bars:
        if bar.bar_date in existing_dates:
            continue
        rows.append(
            StockDailyBar(
                instrument_id=instrument_id,
                bar_date=bar.bar_date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                source="yfinance",
            )
        )
    return rows


def _fetch_bars(symbol: str) -> list[Bar]:
    df = MarketDataService.get_historical_data(symbol, period="6mo")
    if df is None or df.empty:
        return []
    bars = []
    def _num(value):
        return float(value) if pd.notna(value) else None

    for idx, row in df.iterrows():
        try:
            bar_date = idx.date() if hasattr(idx, "date") else idx
            volume = row.get("Volume")
            bars.append(
                Bar(
                    bar_date=bar_date,
                    open=_num(row.get("Open")),
                    high=_num(row.get("High")),
                    low=_num(row.get("Low")),
                    close=_num(row.get("Close")),
                    volume=int(volume) if pd.notna(volume) else None,
                )
            )
        except Exception:
            continue
    return bars


def _store_market_risk(db: Session, instrument: Instrument, bars: list[Bar]) -> Optional[MarketRiskSnapshot]:
    if not bars:
        return None

    existing_dates = {
        row.bar_date
        for row in db.query(StockDailyBar.bar_date).filter(StockDailyBar.instrument_id == instrument.id)
    }
    new_rows = _bars_to_daily_bar_rows(instrument.id, bars, existing_dates)
    for row in new_rows:
        db.add(row)

    metrics = compute_metrics(bars)
    if metrics.as_of is None:
        return None
    result = compute_market_safety_score(metrics)

    existing_snapshot = (
        db.query(MarketRiskSnapshot)
        .filter(MarketRiskSnapshot.instrument_id == instrument.id, MarketRiskSnapshot.as_of_date == metrics.as_of)
        .first()
    )
    if existing_snapshot is not None:
        db.delete(existing_snapshot)
        db.flush()

    snapshot = MarketRiskSnapshot(
        instrument_id=instrument.id,
        as_of_date=metrics.as_of,
        price=metrics.price,
        avg_daily_volume_20=int(metrics.avg_daily_volume_20) if metrics.avg_daily_volume_20 else None,
        avg_dollar_volume_20=metrics.avg_dollar_volume_20,
        atr14=metrics.atr14,
        atr_pct=metrics.atr_pct,
        realized_vol_20=metrics.realized_vol_20,
        realized_vol_60=metrics.realized_vol_60,
        return_5d=metrics.return_5d,
        return_20d=metrics.return_20d,
        max_drawdown_30d=metrics.max_drawdown_30d,
        max_drawdown_90d=metrics.max_drawdown_90d,
        gap_frequency=metrics.gap_frequency,
        worst_day_20d=metrics.worst_day_20d,
        market_safety_score=result.score,
        components=result.as_dict(),
        bars_used=metrics.bars_used,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def run(db: Session, check_optionable: bool = True) -> dict[str, Any]:
    """Corre el funnel completo y persiste resultados. No es reentrante."""
    global _is_running
    if not _run_lock.acquire(blocking=False):
        return {"status": "ALREADY_RUNNING"}
    _is_running = True
    started = datetime.now(timezone.utc)
    try:
        with LogContext(job_id="universe_scan"):
            provider = NasdaqUniverseProvider()
            candidates, counts = run_universe_scan(provider, check_optionable=check_optionable)

            instruments = _get_or_create_instruments(db, candidates)
            db.commit()
            _update_universe_stage(db, instruments, candidates)
            db.commit()

            risk_computed = 0
            risk_failed: list[str] = []
            # Llegar a OPTIONABLE implica haber pasado liquidez, sin importar el
            # resultado del check de opciones; quedarse en LIQUIDITY sin motivo de
            # rechazo es el caso check_optionable=False, y con
            # OPTIONABLE_CHECK_FAILED es un candidato válido cuyo check de opciones
            # falló (rate limit) — igual vale la pena calcularle el riesgo de
            # mercado. Cualquier otro rejected_reason en LIQUIDITY no pasó volumen.
            liquid_candidates = [
                c for c in candidates
                if c.stage_reached == STAGE_OPTIONABLE
                or (c.stage_reached == STAGE_LIQUIDITY and c.rejected_reason in (None, REASON_OPTIONABLE_CHECK_FAILED))
            ]
            for candidate in liquid_candidates:
                instrument = instruments[candidate.symbol]
                try:
                    bars = _fetch_bars(candidate.symbol)
                    snapshot = _store_market_risk(db, instrument, bars)
                    db.commit()
                    if snapshot is not None:
                        risk_computed += 1
                    else:
                        risk_failed.append(candidate.symbol)
                except Exception as exc:
                    db.rollback()
                    risk_failed.append(candidate.symbol)
                    logger.warning(
                        "riesgo de mercado falló",
                        extra={"symbol": candidate.symbol, "error": str(exc)[:300]},
                    )

            duration = (datetime.now(timezone.utc) - started).total_seconds()
            summary = {
                "status": "OK",
                "started_at": started.isoformat(),
                "duration_seconds": round(duration, 1),
                "funnel": counts.as_dict(),
                "market_risk": {"computed": risk_computed, "failed": risk_failed},
            }
            logger.info("universe scan completo", extra=summary["funnel"] | {"duration_s": summary["duration_seconds"]})
            _store_last_run(db, summary)
            return summary
    finally:
        _is_running = False
        _run_lock.release()
