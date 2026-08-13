"""Corrida del scanner de covered calls (K4).

Toma el universo ya calificado por K3, pide la cadena de cada símbolo a CBOE,
evalúa cada call vendible y guarda los tres mejores contratos por símbolo.

No recalcula el universo ni los fundamentales: son capas con su propio job y su
propia cadencia. Este scan es el único que necesita datos frescos —una prima de
ayer no sirve— y por eso corre aparte y más seguido.
"""

from __future__ import annotations

import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..logging_config import LogContext, get_logger
from ..models import (
    PICK_BALANCED,
    PICK_PREMIUM,
    PICK_UPSIDE,
    AppSetting,
    CoveredCallCandidate,
    FundamentalSnapshot,
    Instrument,
    MarketRiskSnapshot,
)
from ..providers.base import ProviderError
from ..providers.cboe_chains import CboeChainsProvider
from .covered_calls import ChainFilter, evaluate_chain, pick_best
from .scoring import PROFILES, compute_cc_opportunity, compute_final_score, evaluate_gate
from .universe import STAGE_OPTIONABLE

logger = get_logger(__name__)

LAST_RUN_SETTING_KEY = "scanner:covered_calls:last_run"
# Los picks por perfil se guardan como PERFIL_<NOMBRE> en la misma columna
# pick_type. El índice único es (instrument_id, pick_type), así que no hace
# falta tabla ni columna nueva.
PICK_PROFILE_PREFIX = "PERFIL_"
# CBOE limita por ráfaga (429 con Retry-After ~9s). Medido: a ~5 req/s la
# corrida de 306 símbolos completó 60 y falló 246. Un request por segundo la
# sostiene entera —~5 min para el universo, aceptable para un job dos veces al
# día— y el provider igual respeta el Retry-After si aparece.
POLITE_DELAY_SECONDS = 1.0

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
        db.add(AppSetting(user_id=None, key=LAST_RUN_SETTING_KEY, value=summary))
    else:
        row.value = summary
    db.commit()


def _qualified_instruments(db: Session) -> list[Instrument]:
    return (
        db.query(Instrument)
        .filter(
            Instrument.universe_stage == STAGE_OPTIONABLE,
            Instrument.universe_rejected_reason.is_(None),
        )
        .order_by(Instrument.symbol)
        .all()
    )


def _latest_scores(db: Session, instrument_ids: list[int]) -> tuple[dict, dict]:
    """Último Financial Safety y Market Safety por instrumento.

    Se copian a cada fila del candidato: el ranking los necesita en todas las
    filas y los snapshots cambian entre corridas, así que guardarlos deja la
    recomendación explicable sin tener que reconstruir contra qué se rankeó.
    """
    fundamentales: dict[int, float] = {}
    for snap in (
        db.query(FundamentalSnapshot)
        .filter(FundamentalSnapshot.instrument_id.in_(instrument_ids))
        .order_by(FundamentalSnapshot.instrument_id, FundamentalSnapshot.accepted_at.desc())
        .all()
    ):
        if snap.instrument_id not in fundamentales and snap.financial_safety_score is not None:
            fundamentales[snap.instrument_id] = snap.financial_safety_score

    mercado: dict[int, float] = {}
    for snap in (
        db.query(MarketRiskSnapshot)
        .filter(MarketRiskSnapshot.instrument_id.in_(instrument_ids))
        .order_by(MarketRiskSnapshot.instrument_id, MarketRiskSnapshot.as_of_date.desc())
        .all()
    ):
        if snap.instrument_id not in mercado and snap.market_safety_score is not None:
            mercado[snap.instrument_id] = float(snap.market_safety_score)

    return fundamentales, mercado


def _upsert_candidate(
    db: Session,
    instrument: Instrument,
    pick_type: str,
    metrics,
    quote_as_of: datetime,
    fss: Optional[float],
    mss: Optional[float],
) -> None:
    row = (
        db.query(CoveredCallCandidate)
        .filter(
            CoveredCallCandidate.instrument_id == instrument.id,
            CoveredCallCandidate.pick_type == pick_type,
        )
        .first()
    )
    if row is None:
        row = CoveredCallCandidate(instrument_id=instrument.id, pick_type=pick_type)
        db.add(row)

    row.scanned_at = datetime.now(timezone.utc)
    row.quote_as_of = quote_as_of
    row.underlying_price = metrics.underlying_price
    row.stock_ask = metrics.stock_ask
    row.occ_symbol = metrics.occ_symbol
    row.expiration = metrics.expiration
    row.strike = metrics.strike
    row.dte = metrics.dte
    row.call_bid = metrics.call_bid
    row.call_ask = metrics.call_ask
    row.spread_pct = metrics.spread_pct
    row.delta = metrics.delta
    row.implied_volatility = metrics.implied_volatility
    row.volume = metrics.volume
    row.open_interest = metrics.open_interest
    row.premium_total = metrics.premium_total
    row.premium_yield = metrics.premium_yield
    row.annualized_premium_yield = metrics.annualized_premium_yield
    row.return_if_assigned = metrics.return_if_assigned
    row.annualized_return_if_assigned = metrics.annualized_return_if_assigned
    row.downside_protection = metrics.downside_protection
    row.breakeven = metrics.breakeven
    row.moneyness = metrics.moneyness
    row.liquidity_score = metrics.liquidity_score
    row.liquidity_components = metrics.liquidity_components
    row.financial_safety_score = fss
    row.market_safety_score = mss
    row.cc_opportunity_score = metrics.cc_opportunity_score
    row.cc_score_components = metrics.cc_score_components
    row.final_score = metrics.final_score
    row.final_score_status = metrics.final_score_status


def run(
    db: Session,
    symbols: Optional[list[str]] = None,
    filtro: Optional[ChainFilter] = None,
    provider: Optional[CboeChainsProvider] = None,
) -> dict[str, Any]:
    """Escanea el universo (o los símbolos dados) y persiste los mejores por papel."""
    global _is_running

    with _run_lock:
        if _is_running:
            return {"skipped": "ya hay una corrida en progreso"}
        _is_running = True

    inicio = time.monotonic()
    provider = provider or CboeChainsProvider()
    hoy = date.today()

    try:
        if symbols:
            objetivos = (
                db.query(Instrument)
                .filter(Instrument.symbol.in_([s.upper() for s in symbols]))
                .order_by(Instrument.symbol)
                .all()
            )
        else:
            objetivos = _qualified_instruments(db)

        fundamentales, mercado = _latest_scores(db, [i.id for i in objetivos])

        # ── Fase 1: traer y evaluar todas las cadenas ─────────────────────
        # No se puntúa ni se persiste todavía: cinco de los siete componentes
        # del CC Opportunity se normalizan contra el resto de la corrida (K5),
        # así que hay que ver la población completa antes de puntuar a nadie.
        por_simbolo: dict[int, list] = {}
        sin_candidatos: list[str] = []
        fallidos: list[dict] = []
        descartes_totales: dict[str, int] = {}

        for instrument in objetivos:
            try:
                quotes, underlying = provider.get_chain(instrument.symbol)
            except ProviderError as exc:
                fallidos.append({"symbol": instrument.symbol, "error": str(exc)[:200]})
                continue
            except Exception as exc:  # noqa: BLE001 — un símbolo raro no puede voltear la corrida
                fallidos.append({"symbol": instrument.symbol, "error": f"{type(exc).__name__}: {exc}"[:200]})
                continue
            finally:
                time.sleep(POLITE_DELAY_SECONDS)

            if underlying.price is None or underlying.price <= 0:
                fallidos.append({"symbol": instrument.symbol, "error": "CBOE no reportó precio del subyacente"})
                continue

            candidatos, descartes = evaluate_chain(
                quotes, underlying.price, hoy, stock_ask=underlying.ask, filtro=filtro
            )
            for clave, valor in descartes.items():
                descartes_totales[clave] = descartes_totales.get(clave, 0) + valor

            if not candidatos:
                sin_candidatos.append(instrument.symbol)
                continue

            por_simbolo[instrument.id] = (candidatos, underlying.as_of)

        # ── Fase 2: puntuar contra la corrida completa ─────────────────────
        poblacion = [c for candidatos, _ in por_simbolo.values() for c in candidatos]
        resultados = compute_cc_opportunity(poblacion)
        for metrics, resultado in zip(poblacion, resultados):
            metrics.cc_opportunity_score = resultado.score
            metrics.cc_score_components = [c.as_dict() for c in resultado.components]

        # ── Fase 3: elegir los tres por papel y persistir ──────────────────
        instrumentos_por_id = {i.id: i for i in objetivos}
        con_candidatos = 0
        for instrument_id, (candidatos, quote_as_of) in por_simbolo.items():
            instrument = instrumentos_por_id[instrument_id]
            fss = fundamentales.get(instrument_id)
            mss = mercado.get(instrument_id)
            for metrics in candidatos:
                metrics.final_score, metrics.final_score_status = compute_final_score(
                    metrics.cc_opportunity_score, fss, mss
                )

            mejores = pick_best(candidatos)
            elegidos = [
                (PICK_BALANCED, mejores["balanced"]),
                (PICK_PREMIUM, mejores["premium"]),
                (PICK_UPSIDE, mejores["upside"]),
            ]

            # Además, el mejor contrato QUE PASA cada perfil. Sin esto la puerta
            # se aplicaría sobre un contrato ya elegido con otro criterio, y un
            # papel quedaría rechazado aunque tuviera otro strike que sí
            # califica — el delta que maximiza el CC Opportunity (~0,40) queda
            # fuera de la banda conservadora (0,20–0,30) casi siempre.
            for nombre, perfil in PROFILES.items():
                admisibles = [
                    c for c in candidatos
                    if evaluate_gate(perfil, fss, mss, c.spread_pct, c.delta, c.dte)[0]
                ]
                if admisibles:
                    elegidos.append((
                        f"{PICK_PROFILE_PREFIX}{nombre}",
                        max(admisibles, key=lambda c: (
                            c.final_score if c.final_score is not None else -1,
                            c.cc_opportunity_score or 0,
                        )),
                    ))

            for pick_type, metrics in elegidos:
                if metrics is not None:
                    _upsert_candidate(db, instrument, pick_type, metrics, quote_as_of, fss, mss)
            vigentes = {pt for pt, m in elegidos if m is not None}
            obsoletos = (
                db.query(CoveredCallCandidate)
                .filter(
                    CoveredCallCandidate.instrument_id == instrument.id,
                    CoveredCallCandidate.pick_type.notin_(vigentes),
                )
                .all()
            )
            for fila in obsoletos:
                db.delete(fila)

            con_candidatos += 1
            db.commit()

        resumen = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(time.monotonic() - inicio, 1),
            "symbols_scanned": len(objetivos),
            "symbols_with_candidates": con_candidatos,
            "contracts_scored": len(poblacion),
            "symbols_without_candidates": len(sin_candidatos),
            "failed": fallidos[:50],
            "failed_count": len(fallidos),
            "rejections": descartes_totales,
        }
        _store_last_run(db, resumen)
        logger.info("scan de covered calls terminado", extra=resumen)
        return resumen
    finally:
        _is_running = False
