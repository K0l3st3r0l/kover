"""Market Safety Score: 0 = extremadamente volátil, 100 = comportamiento tranquilo.

Stage 3 del scanner (§6 y §26 del plan). Es independiente del Financial Safety
Score: una empresa puede tener fundamentales sólidos y un subyacente que salta
15% en un día. El riesgo principal de la estrategia es la caída del subyacente,
así que este score existe aparte y no se promedia a ciegas con el fundamental.

Mismo criterio de explicabilidad que `fundamentals/score.py`: cada componente
guarda su valor crudo, su normalización y su peso — sin recalcular nada se
puede responder "¿por qué 42?".

Los umbrales están calibrados para el universo objetivo (US$10–20, optionable):
estas acciones son estructuralmente más volátiles que el S&P 500 grande, así
que "seguro" aquí no es "seguro" en una blue chip. Son heurísticos de arranque,
no una calibración estadística contra resultados reales — eso es trabajo de
K8 (backtest).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

TRADING_DAYS_YEAR = 252

WEIGHTS = {
    "atr_pct": 0.25,
    "realized_vol_20": 0.25,
    "max_drawdown_30d": 0.20,
    "gap_frequency": 0.15,
    "worst_day_20d": 0.15,
}

# Frecuencia de gaps: fracción de días con |open - cierre previo| / cierre previo
# sobre este umbral. 2% es un gap notable para una acción de este rango de precio.
GAP_THRESHOLD = 0.02


@dataclass
class Bar:
    bar_date: date
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    close: Optional[float]
    volume: Optional[int]


@dataclass
class RiskComponent:
    name: str
    raw_value: Optional[float]
    normalized: Optional[float]  # 0–1, 1 = más seguro
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
class MarketRiskMetrics:
    as_of: Optional[date] = None
    price: Optional[float] = None
    avg_daily_volume_20: Optional[float] = None
    avg_dollar_volume_20: Optional[float] = None
    atr14: Optional[float] = None
    atr_pct: Optional[float] = None
    realized_vol_20: Optional[float] = None
    realized_vol_60: Optional[float] = None
    return_5d: Optional[float] = None
    return_20d: Optional[float] = None
    max_drawdown_30d: Optional[float] = None
    max_drawdown_90d: Optional[float] = None
    gap_frequency: Optional[float] = None
    worst_day_20d: Optional[float] = None
    bars_used: int = 0
    missing: dict = field(default_factory=dict)


@dataclass
class RiskScoreResult:
    score: Optional[float]
    components: list[RiskComponent] = field(default_factory=list)
    coverage: float = 0.0
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "coverage": round(self.coverage, 3),
            "note": self.note,
            "components": [c.as_dict() for c in self.components],
        }


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _safer_below(value: Optional[float], safe_at: float, risky_at: float) -> Optional[float]:
    """Normaliza 0–1 donde MENOS es más seguro. `safe_at` < `risky_at`."""
    if value is None:
        return None
    if value <= safe_at:
        return 1.0
    if value >= risky_at:
        return 0.0
    return _clamp(1.0 - (value - safe_at) / (risky_at - safe_at))


def compute_metrics(bars: list[Bar]) -> MarketRiskMetrics:
    """Calcula las métricas crudas a partir de barras diarias ascendentes por fecha.

    Se necesitan al menos 90 barras para drawdown_90d y vol_60; con menos, esas
    dos quedan en None con motivo explícito en vez de calcularse sobre una
    ventana más corta disfrazada de la métrica pedida.
    """
    missing: dict[str, str] = {}
    clean = [b for b in bars if b.close is not None and b.close > 0]
    clean.sort(key=lambda b: b.bar_date)

    if len(clean) < 15:
        return MarketRiskMetrics(
            as_of=clean[-1].bar_date if clean else None,
            price=clean[-1].close if clean else None,
            bars_used=len(clean),
            missing={"_all": f"solo {len(clean)} barras válidas, se necesitan al menos 15"},
        )

    closes = [b.close for b in clean]
    price = closes[-1]
    as_of = clean[-1].bar_date

    # Volumen y volumen en dólares, últimas 20 sesiones.
    window20 = clean[-20:]
    volumes = [b.volume for b in window20 if b.volume is not None]
    avg_vol_20 = statistics.fmean(volumes) if volumes else None
    dollar_vols = [b.volume * b.close for b in window20 if b.volume is not None and b.close]
    avg_dollar_vol_20 = statistics.fmean(dollar_vols) if dollar_vols else None
    if avg_vol_20 is None:
        missing["avg_daily_volume_20"] = "sin volumen en las barras"

    # ATR14 (media simple de True Range; sin suavizado de Wilder por simplicidad
    # — con 14 barras la diferencia frente a EMA es marginal para el propósito
    # de rankear riesgo, no de tradear el ATR en sí).
    atr14 = None
    atr_pct = None
    tr_window = clean[-15:]  # 14 TR necesitan 15 barras (cierre previo incluido)
    if len(tr_window) >= 15:
        trs = []
        for i in range(1, len(tr_window)):
            prev_close = tr_window[i - 1].close
            bar = tr_window[i]
            if bar.high is None or bar.low is None or prev_close is None:
                continue
            tr = max(
                bar.high - bar.low,
                abs(bar.high - prev_close),
                abs(bar.low - prev_close),
            )
            trs.append(tr)
        if trs:
            atr14 = statistics.fmean(trs)
            atr_pct = atr14 / price if price else None
    if atr14 is None:
        missing["atr14"] = "faltan high/low en las barras recientes"

    # Retornos logarítmicos diarios para volatilidad realizada.
    log_returns = [
        math.log(closes[i] / closes[i - 1])
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]

    def _realized_vol(n: int) -> Optional[float]:
        sample = log_returns[-n:]
        if len(sample) < max(5, n // 2):
            return None
        return statistics.pstdev(sample) * math.sqrt(TRADING_DAYS_YEAR)

    realized_vol_20 = _realized_vol(20)
    realized_vol_60 = _realized_vol(60)
    if realized_vol_20 is None:
        missing["realized_vol_20"] = "menos de 10 retornos disponibles"
    if realized_vol_60 is None:
        missing["realized_vol_60"] = "menos de 30 retornos disponibles (se necesitan ~60 barras)"

    def _simple_return(n: int) -> Optional[float]:
        if len(closes) <= n:
            return None
        return closes[-1] / closes[-1 - n] - 1.0

    return_5d = _simple_return(5)
    return_20d = _simple_return(20)

    def _max_drawdown(n: int) -> Optional[float]:
        window = closes[-n:]
        if len(window) < min(n, 10):
            return None
        peak = window[0]
        worst = 0.0
        for c in window:
            peak = max(peak, c)
            dd = (peak - c) / peak if peak else 0.0
            worst = max(worst, dd)
        return worst

    max_dd_30 = _max_drawdown(30)
    max_dd_90 = _max_drawdown(90)
    if max_dd_90 is None:
        missing["max_drawdown_90d"] = "se necesitan ~90 barras"

    # Gaps: apertura vs cierre previo, últimas 60 sesiones (o las que haya).
    gap_window = clean[-60:]
    gap_days = 0
    gap_total = 0
    for i in range(1, len(gap_window)):
        prev_close = gap_window[i - 1].close
        open_ = gap_window[i].open
        if prev_close is None or open_ is None or prev_close == 0:
            continue
        gap_total += 1
        if abs(open_ - prev_close) / prev_close >= GAP_THRESHOLD:
            gap_days += 1
    gap_frequency = gap_days / gap_total if gap_total >= 10 else None
    if gap_frequency is None:
        missing["gap_frequency"] = "faltan aperturas suficientes"

    worst_day_20d = min(log_returns[-20:]) if len(log_returns) >= 10 else None
    worst_day_20d = abs(worst_day_20d) if worst_day_20d is not None and worst_day_20d < 0 else 0.0
    if len(log_returns) < 10:
        missing["worst_day_20d"] = "menos de 10 retornos disponibles"

    return MarketRiskMetrics(
        as_of=as_of,
        price=price,
        avg_daily_volume_20=avg_vol_20,
        avg_dollar_volume_20=avg_dollar_vol_20,
        atr14=atr14,
        atr_pct=atr_pct,
        realized_vol_20=realized_vol_20,
        realized_vol_60=realized_vol_60,
        return_5d=return_5d,
        return_20d=return_20d,
        max_drawdown_30d=max_dd_30,
        max_drawdown_90d=max_dd_90,
        gap_frequency=gap_frequency,
        worst_day_20d=worst_day_20d,
        bars_used=len(clean),
        missing=missing,
    )


def compute_market_safety_score(m: MarketRiskMetrics) -> RiskScoreResult:
    if m.bars_used < 15:
        return RiskScoreResult(
            score=None,
            note=m.missing.get("_all", "datos insuficientes"),
        )

    components = [
        RiskComponent(
            "atr_pct", m.atr_pct, _safer_below(m.atr_pct, 0.03, 0.10),
            WEIGHTS["atr_pct"], 0.0,
            "rango verdadero promedio (14d) como % del precio" if m.atr_pct is not None
            else m.missing.get("atr14", "sin datos"),
        ),
        RiskComponent(
            "realized_vol_20", m.realized_vol_20, _safer_below(m.realized_vol_20, 0.35, 0.90),
            WEIGHTS["realized_vol_20"], 0.0,
            "volatilidad realizada anualizada, 20 sesiones" if m.realized_vol_20 is not None
            else m.missing.get("realized_vol_20", "sin datos"),
        ),
        RiskComponent(
            "max_drawdown_30d", m.max_drawdown_30d, _safer_below(m.max_drawdown_30d, 0.08, 0.35),
            WEIGHTS["max_drawdown_30d"], 0.0,
            "peor caída peak-to-trough, últimos 30 días" if m.max_drawdown_30d is not None
            else m.missing.get("max_drawdown_30d", "sin datos"),
        ),
        RiskComponent(
            "gap_frequency", m.gap_frequency, _safer_below(m.gap_frequency, 0.05, 0.25),
            WEIGHTS["gap_frequency"], 0.0,
            f"fracción de aperturas con gap ≥{GAP_THRESHOLD:.0%} vs cierre previo" if m.gap_frequency is not None
            else m.missing.get("gap_frequency", "sin datos"),
        ),
        RiskComponent(
            "worst_day_20d", m.worst_day_20d, _safer_below(m.worst_day_20d, 0.05, 0.20),
            WEIGHTS["worst_day_20d"], 0.0,
            "peor retorno diario, últimas 20 sesiones" if m.worst_day_20d is not None
            else m.missing.get("worst_day_20d", "sin datos"),
        ),
    ]

    available = [c for c in components if c.normalized is not None]
    total_weight = sum(c.weight for c in available)
    coverage = total_weight / sum(WEIGHTS.values())

    if coverage < 0.5:
        return RiskScoreResult(
            score=None,
            components=components,
            coverage=coverage,
            note=f"solo {coverage:.0%} del peso tiene datos; se necesita al menos 50%",
        )

    for c in available:
        c.contribution = (c.normalized or 0.0) * c.weight / total_weight

    score = sum(c.contribution for c in available) * 100

    return RiskScoreResult(
        score=round(score, 2),
        components=components,
        coverage=coverage,
        note=f"{len(available)}/{len(components)} componentes con datos",
    )
